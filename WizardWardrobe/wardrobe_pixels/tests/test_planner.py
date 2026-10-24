"""Week planner, offline: the validator is the contract between Gemma and the page."""
import asyncio

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from wardrobe_pixels.planner import DayOutfit, PlanRequest, WeekPlan, _Deps, build_planner, plan_week, problems

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CLOSET = ([{"id": f"top{i}", "name": f"Top {i}", "cat": "top", "warmth": 2 + i % 3} for i in range(4)] +
          [{"id": f"bot{i}", "name": f"Bottom {i}", "cat": "bottom"} for i in range(3)] +
          [{"id": f"und{i}", "name": f"Undies {i}", "cat": "underwear"} for i in range(7)] +
          [{"id": f"sock{i}", "name": f"Socks {i}", "cat": "socks"} for i in range(3)] +
          [{"id": "shoe0", "name": "Shoe", "cat": "shoes"}, {"id": "cap0", "name": "Cap", "cat": "hat"},
           {"id": "dirty-top", "name": "Dirty Top", "cat": "top", "status": "laundry"}])


def req(**kw):
    plan = [{"day": d, "locked": d == "Fri", "hat_on": d in ("Mon", "Sat")} for d in DAYS]
    return PlanRequest(wardrobe=CLOSET, plan=plan,
                       forecast=[{"day": d, "cond": "sun", "hi": 60} for d in DAYS], **kw)


def test_offline_plan_is_valid_and_skips_locked_days():
    out = asyncio.run(plan_week(build_planner("test"), req()))
    assert [d.day for d in out.days] == ["Mon", "Tue", "Wed", "Thu", "Sat", "Sun"]
    assert out.days[0].hat == "cap0" and out.days[1].hat is None          # hat_on respected
    assert problems(out, _Deps(req())) == []


def _good():
    return [{"day": d, "hat": None, "top": f"top{n % 4}", "bottom": "bot0", "underwear": f"und{n}",
             "socks": f"sock{n % 3}", "shoes": "shoe0"} for n, d in enumerate(["Mon", "Tue", "Wed", "Thu", "Sat", "Sun"])]


@pytest.mark.parametrize("edit,why", [
    (lambda p: p[0].update(top="dirty-top"), "in the hamper"),
    (lambda p: p[0].update(top="bot1"), "not a top"),
    (lambda p: p[0].update(top="ghost"), "not in the closet"),
    (lambda p: p.append({**p[0], "day": "Fri"}), "Fri"),
    (lambda p: p.pop(), "Plan these days too: Sun"),
    (lambda p: p[1].update(underwear="und0"), "Don't repeat underwear"),
    (lambda p: p[1].update(hat="cap0"), "hat_on is false"),
    (lambda p: p[2].update(shoes=None), "pick a shoes"),
])
def test_validator_catches(edit, why):
    days = _good()
    edit(days)
    plan = WeekPlan(days=[DayOutfit(**d) for d in days])
    bad = problems(plan, _Deps(req()))
    assert any(why in b for b in bad), bad


def test_socks_may_repeat_when_there_are_not_enough():
    plan = WeekPlan(days=[DayOutfit(**d) for d in _good()])      # 3 socks for 6 days, repeats allowed
    assert not any("socks" in b for b in problems(plan, _Deps(req())))


def test_bad_plan_goes_back_to_gemma_then_good_plan_is_used():
    calls = {"n": 0}

    def respond(messages, info):
        calls["n"] += 1
        days = _good()
        if calls["n"] == 1:
            days[0]["top"] = "dirty-top"
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"days": days})])
    out = asyncio.run(plan_week(build_planner("test", model=FunctionModel(respond)), req()))
    assert calls["n"] == 2 and out.days[0].top == "top0"


def test_endpoint(monkeypatch):
    monkeypatch.setenv("WARDROBE_PROVIDER", "test")
    import importlib

    from fastapi.testclient import TestClient

    import wardrobe_pixels.server as server
    importlib.reload(server)
    c = TestClient(server.app)
    r = c.post("/plan/week", json=req().model_dump())
    assert r.status_code == 200 and len(r.json()["days"]) == 6
    all_locked = req().model_dump()
    for p in all_locked["plan"]:
        p["locked"] = True
    assert c.post("/plan/week", json=all_locked).status_code == 502
