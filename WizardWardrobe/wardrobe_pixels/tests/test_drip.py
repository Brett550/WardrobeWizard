"""Drip agent + endpoint, offline. Tool calls are real; only the model is faked."""
import asyncio

import pytest
from pydantic_ai.messages import ModelResponse, RetryPromptPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from wardrobe_pixels.drip import DripRequest, build_drip, chat

WARDROBE = [
    {"id": "candy-stripe-long-sleeve", "name": "Candy Stripe Long Sleeve", "cat": "top", "warmth": 3, "tags": ["bold"]},
    {"id": "plain-white-tee", "name": "Plain White Tee", "cat": "top", "warmth": 2, "status": "laundry"},
    {"id": "heather-grey-hoodie", "name": "Heather Grey Hoodie", "cat": "top", "warmth": 4},
    {"id": "lilac-hoodie", "name": "Lilac Hoodie", "cat": "top", "warmth": 4},
    {"id": "classic-blue-jeans", "name": "Classic Blue Jeans", "cat": "bottom", "warmth": 3},
    {"id": "red-stripe-socks", "name": "Red Stripe Socks", "cat": "socks", "status": "laundry"},
]
PLAN = [{"day": d, "top": "candy-stripe-long-sleeve" if d == "Mon" else None, "bottom": "classic-blue-jeans",
         "locked": d == "Fri"} for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]]


def req(text, **kw):
    return DripRequest(messages=[{"role": "user", "content": text}], wardrobe=WARDROBE, plan=PLAN,
                       forecast=[{"day": "Thu", "cond": "rain", "hi": 46}], **kw)


def run(agent, r):
    return asyncio.run(chat(agent, r))


@pytest.fixture(scope="module")
def offline():
    return build_drip("test")


def test_spill_sends_the_right_item_to_laundry(offline):
    out = run(offline, req("I spilled coffee on the stripe long sleeve"))
    assert out.actions == [{"type": "send_to_laundry", "item_id": "candy-stripe-long-sleeve"}]
    assert out.mood == "casting" and "hamper" in out.message


def test_ambiguous_item_asks_instead_of_guessing(offline):
    out = run(offline, req("I spilled on my hoodie"))
    assert out.actions == [] and "?" in out.message and out.mood == "thinking"


def test_wash_everything_washes_exactly_the_hamper(offline):
    out = run(offline, req("wash everything please"))
    assert out.actions == [{"type": "wash", "item_ids": ["plain-white-tee", "red-stripe-socks"]}]


def test_replan_weekend_with_vibe(offline):
    out = run(offline, req("make the weekend comfy"))
    assert out.actions == [{"type": "replan", "days": [5, 6], "vibe": "comfy"}]


def _scripted(*calls):
    """Model that makes the given tool calls in order, then reports what came back."""
    state = {"i": 0, "seen": []}

    def respond(messages, info):
        for p in messages[-1].parts:
            # this pydantic-ai returns a refused call as a ToolReturnPart with outcome "retried"
            if isinstance(p, RetryPromptPart) or (isinstance(p, ToolReturnPart) and p.outcome != "success"):
                state["seen"].append(p)
        if state["i"] < len(calls):
            name, args = calls[state["i"]]
            state["i"] += 1
            return ModelResponse(parts=[ToolCallPart(name, args)])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"message": "done", "mood": "happy"})])
    return FunctionModel(respond), state


@pytest.mark.parametrize("args,why", [
    ({"day": "Mon", "category": "top", "item_id": "plain-white-tee"}, "in the hamper"),
    ({"day": "Mon", "category": "bottom", "item_id": "lilac-hoodie"}, "not a bottom"),
    ({"day": "Fri", "category": "top", "item_id": "lilac-hoodie"}, "locked"),
    ({"day": "Mon", "category": "top", "item_id": "purple-pants"}, "No item"),
])
def test_bad_set_slot_is_sent_back_to_the_model_not_applied(args, why):
    model, state = _scripted(("set_slot", args))
    out = run(build_drip("test", model=model), req("x"))
    assert out.actions == []
    assert any(why in str(p.content) for p in state["seen"])


def test_tools_see_earlier_changes_in_the_same_turn():
    """Laundry first, then trying to wear the same item: the second call must be refused."""
    model, state = _scripted(("send_to_laundry", {"item_id": "lilac-hoodie"}),
                             ("set_slot", {"day": "Tue", "category": "top", "item_id": "lilac-hoodie"}),
                             ("set_slot", {"day": "Tue", "category": "top", "item_id": "heather-grey-hoodie"}))
    out = run(build_drip("test", model=model), req("x"))
    assert out.actions == [{"type": "send_to_laundry", "item_id": "lilac-hoodie"},
                           {"type": "set_slot", "day": 1, "category": "top", "item_id": "heather-grey-hoodie"}]


def test_replan_skips_locked_days():
    model, _ = _scripted(("replan", {"days": ["Thu", "Fri"]}))
    out = run(build_drip("test", model=model), req("x"))
    assert out.actions == [{"type": "replan", "days": [3], "vibe": None}]


def test_history_and_snapshot_reach_the_model():
    seen = {}

    def respond(messages, info):
        seen["n"] = len(messages)
        seen["instructions"] = info.instructions
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"message": "hi"})])
    r = DripRequest(messages=[{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                              {"role": "user", "content": "c"}], wardrobe=WARDROBE, plan=PLAN)
    run(build_drip("test", model=FunctionModel(respond)), r)
    assert seen["n"] == 3 and "candy-stripe-long-sleeve" in seen["instructions"] and "You are Drip" in seen["instructions"]


def test_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("WARDROBE_PROVIDER", "test")
    page = tmp_path / "page.html"
    page.write_text("<html>wizard</html>")
    monkeypatch.setenv("WARDROBE_PAGE", str(page))
    import importlib

    from fastapi.testclient import TestClient

    import wardrobe_pixels.server as server
    importlib.reload(server)
    c = TestClient(server.app)
    body = req("I spilled on the candy stripe long sleeve").model_dump()
    r = c.post("/drip/chat", json=body)
    assert r.status_code == 200 and r.json()["actions"][0]["type"] == "send_to_laundry"
    assert c.post("/drip/chat", json={"messages": []}).status_code == 422
    assert c.get("/health").json()["ok"] is True
    assert "wizard" in c.get("/").text


def test_offline_drip_reports_a_refusal(offline):
    out = run(offline, req("lock friday"))           # fine
    assert out.actions == [{"type": "lock_day", "day": 4, "locked": True}]
    model, _ = _scripted(("wash", {"item_ids": ["lilac-hoodie"]}))   # not in the hamper
    out = run(build_drip("test", model=model), req("x"))
    assert out.actions == []


def test_looping_reply_is_sent_back_and_replaced():
    replies = iter(["fine " * 6, "Wear the grey hoodie Thursday, it'll be cold."])

    def respond(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"message": next(replies), "mood": "cool"})])
    out = run(build_drip("test", model=FunctionModel(respond)), req("what should I wear thursday?"))
    assert out.message.startswith("Wear the grey hoodie") and out.actions == []
