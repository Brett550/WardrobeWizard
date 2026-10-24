"""Drip: the wardrobe wizard helper. Gemma 4 thinks; the front end changes things.

The front end owns the state. Each request carries a compact snapshot (wardrobe, week plan,
forecast, style). Drip's tools check every argument against that snapshot and record an
action; nothing on the server is changed. The front end applies the actions with its own
functions (drop, sendToLaundry, wash, planWeek), so a bad model reply can't corrupt anything.

  POST /drip/chat  (server.py)  DripRequest -> DripResponse {message, mood, actions}

Bad tool calls raise ModelRetry with a plain explanation, so Gemma corrects itself instead
of making things up ("Plain White Tee is in the hamper; pick a clean top").
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from .agent import DEFAULT_MODELS, TRANSIENT_ERRORS, build_model

Day = Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
Category = Literal["hat", "top", "bottom", "underwear", "socks", "shoes"]
Mood = Literal["happy", "thinking", "casting", "shocked", "cool"]
DAYS: list[str] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
LONG_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
CATS = ["hat", "top", "bottom", "underwear", "socks", "shoes"]
VIBES = ["comfy", "campus", "sporty", "dressy"]
MAX_HISTORY = 12          # messages sent back to Gemma; older ones are dropped
MAX_ITEMS = 120           # snapshot cap, keeps the prompt small
MAX_REPLY_CHARS = 400     # bubble-sized; longer replies are sent back to Gemma to shorten

PERSONA = """\
You are Drip, a cool pixel-art wizard in sunglasses who lives in the user's closet app.
Help with outfits, laundry, weather and how to use the app. Nothing else: for other topics,
say briefly that you only know clothes.
Reply in 1 to 3 short sentences. Light wizard flavor is fine; never more than one pun.
Only use item ids from the wardrobe list. Never invent clothes. If the user names something
that isn't in the wardrobe, say so and offer the closest real item.
When the user wants something changed, call the tools, then say what you changed.
Questions like "what should I wear Thursday?" are advice: name items from the wardrobe and why,
and do NOT call tools. Only change the plan when the user asks you to.
If more than one item matches what the user named (for example "the hoodie" when there are two
hoodies), do not pick one: ask which one, listing their names, and call no tools.
Items with status "laundry" are in the hamper: they can't be worn until washed.
Locked days are protected: don't change them unless the user unlocks them first.
Pick mood: "casting" when you changed something, "cool" for outfit advice, "shocked" for
problems (hamper overflowing, missing clothes), "thinking" when asking a question, else "happy".

App guide (for how-to questions):
- Drag clothes from the closet onto a day, between days to swap, or into the hamper.
- The lock under each day protects that outfit from Plan week.
- Click the hamper to see what's inside; Wash all returns everything.
- Weather, Style, Plan week, Filter, Sort and Add clothes are in the tool rail on the right.
- Click any item to rename it, change its type or color, or plan it for a day.
"""


# ------------------------------------------------------------------ request --

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class SnapshotItem(BaseModel):
    id: str
    name: str
    cat: Category
    subtype: str | None = None
    warmth: int | None = None
    formality: int | None = None
    tags: list[str] = Field(default_factory=list)
    status: Literal["clean", "laundry"] = "clean"


class PlanDay(BaseModel):
    day: Day
    hat: str | None = None
    top: str | None = None
    bottom: str | None = None
    underwear: str | None = None
    socks: str | None = None
    shoes: str | None = None
    locked: bool = False
    hat_on: bool = True


class ForecastDay(BaseModel):
    day: Day
    cond: str
    hi: int
    lo: int | None = None


class Style(BaseModel):
    vibe: str = "campus"
    mood: str = "mix"


class DripRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    wardrobe: list[SnapshotItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    plan: list[PlanDay] = Field(default_factory=list)
    forecast: list[ForecastDay] = Field(default_factory=list)
    style: Style = Field(default_factory=Style)
    today: Day | None = None


class DripReply(BaseModel):
    """What Drip says. Actions are collected separately by the tools."""
    message: str = Field(max_length=MAX_REPLY_CHARS, description="1 to 3 short sentences for the speech bubble")
    mood: Mood = Field(default="happy", description="Face to show")


class DripResponse(DripReply):
    actions: list[dict] = Field(default_factory=list)


class DripError(RuntimeError):
    pass


# --------------------------------------------------------------------- deps --

@dataclass
class DripDeps:
    wardrobe: dict[str, dict]                 # id -> item (mutated as tools run, so later calls see it)
    plan: list[dict]                          # 7 days, mutated the same way
    actions: list[dict] = field(default_factory=list)

    @classmethod
    def from_request(cls, req: DripRequest) -> "DripDeps":
        plan = [p.model_dump() for p in req.plan]
        by_day = {p["day"]: p for p in plan}
        plan = [by_day.get(d) or PlanDay(day=d).model_dump() for d in DAYS]
        return cls({i.id: i.model_dump() for i in req.wardrobe}, plan)

    def item(self, item_id: str) -> dict:
        it = self.wardrobe.get(item_id)
        if it is None:
            close = [i for i in self.wardrobe if item_id.lower() in i.lower() or i.lower() in item_id.lower()]
            hint = f" Did you mean {close[0]}?" if close else ""
            raise ModelRetry(f"No item with id {item_id!r}. Use an id from the wardrobe list.{hint}")
        return it

    def day(self, day: str) -> int:
        d = str(day).strip()[:3].title()
        if d not in DAYS:
            raise ModelRetry(f"{day!r} isn't a day. Use one of {', '.join(DAYS)}.")
        return DAYS.index(d)


def snapshot_text(req: DripRequest) -> str:
    """Compact JSON the model reads each turn (ids, names, category, warmth, tags, status)."""
    wardrobe = [{k: v for k, v in i.model_dump().items() if v not in (None, [], "")} for i in req.wardrobe]
    plan = [{k: v for k, v in p.model_dump().items() if v is not None} for p in req.plan]
    data = {"today": req.today, "style": req.style.model_dump(), "forecast": [f.model_dump() for f in req.forecast],
            "plan": plan, "wardrobe": wardrobe}
    return "Current app state (JSON):\n" + json.dumps(data, separators=(",", ":"))


# -------------------------------------------------------------------- agent --

def _register_tools(agent: Agent) -> None:
    @agent.tool
    def set_slot(ctx: RunContext[DripDeps], day: Day, category: Category, item_id: str) -> str:
        """Put a clean item on a day in its category row."""
        d, it = ctx.deps.day(day), ctx.deps.item(item_id)
        if it["status"] != "clean":
            raise ModelRetry(f"{it['name']} is in the hamper; pick a clean {category} or wash it first.")
        if it["cat"] != category:
            raise ModelRetry(f"{it['name']} is a {it['cat']}, not a {category}. Use category {it['cat']!r}.")
        p = ctx.deps.plan[d]
        if p["locked"]:
            raise ModelRetry(f"{LONG_DAYS[d]} is locked. Ask the user to unlock it first.")
        p[category] = item_id
        if category == "hat":
            p["hat_on"] = True
        ctx.deps.actions.append({"type": "set_slot", "day": d, "category": category, "item_id": item_id})
        return f"{it['name']} is set for {LONG_DAYS[d]}."

    @agent.tool
    def clear_slot(ctx: RunContext[DripDeps], day: Day, category: Category) -> str:
        """Empty one slot on a day (for example: no hat on Tuesday)."""
        d = ctx.deps.day(day)
        p = ctx.deps.plan[d]
        if p["locked"]:
            raise ModelRetry(f"{LONG_DAYS[d]} is locked. Ask the user to unlock it first.")
        p[category] = None
        if category == "hat":
            p["hat_on"] = False
        ctx.deps.actions.append({"type": "clear_slot", "day": d, "category": category})
        return f"Cleared the {category} on {LONG_DAYS[d]}."

    @agent.tool
    def send_to_laundry(ctx: RunContext[DripDeps], item_id: str) -> str:
        """Put a dirty item in the hamper. The app refills any days that were using it."""
        it = ctx.deps.item(item_id)
        if it["status"] != "clean":
            raise ModelRetry(f"{it['name']} is already in the hamper.")
        it["status"] = "laundry"
        for p in ctx.deps.plan:
            for c in CATS:
                if p.get(c) == item_id:
                    p[c] = None
        ctx.deps.actions.append({"type": "send_to_laundry", "item_id": item_id})
        return f"{it['name']} is in the hamper. The app will swap in another {it['cat']} where it was planned."

    @agent.tool
    def wash(ctx: RunContext[DripDeps], item_ids: list[str]) -> str:
        """Take items out of the hamper (washed). Pass every hamper id to wash everything."""
        if not item_ids:
            raise ModelRetry("Pass at least one item id from the hamper.")
        names = []
        for i in item_ids:
            it = ctx.deps.item(i)
            if it["status"] != "laundry":
                raise ModelRetry(f"{it['name']} isn't in the hamper. Only wash items with status 'laundry'.")
            it["status"] = "clean"
            names.append(it["name"])
        ctx.deps.actions.append({"type": "wash", "item_ids": list(item_ids)})
        return f"Washed {', '.join(names)}."

    @agent.tool
    def replan(ctx: RunContext[DripDeps], days: list[Day] | None = None,
               vibe: Literal["comfy", "campus", "sporty", "dressy"] | None = None) -> str:
        """Re-run the app's outfit planner for some days (default: every unlocked day),
        optionally switching the style vibe first. The app chooses the clothes."""
        idx = sorted({ctx.deps.day(d) for d in days}) if days else list(range(7))
        locked = [LONG_DAYS[d] for d in idx if ctx.deps.plan[d]["locked"]]
        idx = [d for d in idx if not ctx.deps.plan[d]["locked"]]
        if not idx:
            raise ModelRetry(f"{', '.join(locked)} {'is' if len(locked) == 1 else 'are'} locked; nothing to replan.")
        ctx.deps.actions.append({"type": "replan", "days": idx, "vibe": vibe})
        skipped = f" Skipped locked {', '.join(locked)}." if locked else ""
        return f"Replanning {', '.join(LONG_DAYS[d] for d in idx)}{f' with a {vibe} vibe' if vibe else ''}.{skipped}"

    @agent.tool
    def lock_day(ctx: RunContext[DripDeps], day: Day, locked: bool) -> str:
        """Lock (protect from Plan week) or unlock a day's outfit."""
        d = ctx.deps.day(day)
        ctx.deps.plan[d]["locked"] = locked
        ctx.deps.actions.append({"type": "lock_day", "day": d, "locked": locked})
        return f"{LONG_DAYS[d]} is {'locked' if locked else 'unlocked'}."


def build_drip(provider: str | None = None, model=None, retries: int = 3) -> Agent:
    """model: a model id for the provider, or a ready Pydantic AI model object (tests)."""
    provider = provider or os.getenv("WARDROBE_PROVIDER", "google")
    if model is not None and not isinstance(model, str):
        m = model
    elif provider == "test":
        m = _offline_drip_model()
    else:
        m = build_model(provider, model or os.getenv("WARDROBE_MODEL"))
    agent = Agent(m, deps_type=DripDeps, output_type=DripReply, instructions=PERSONA, retries=retries,
                  model_settings={"temperature": 0.4})
    _register_tools(agent)

    @agent.output_validator
    def _speakable(reply: DripReply) -> DripReply:
        words = re.findall(r"[a-z']+", reply.message.lower())
        # Gemma sometimes loops on one word ("appropriate appropriate ..."): ask again.
        if any(len(set(words[i:i + 4])) == 1 for i in range(len(words) - 3)):
            raise ModelRetry("Your reply repeated the same word over and over. Answer again in 1 to 3 short sentences.")
        if not reply.message.strip():
            raise ModelRetry("Your reply was empty. Answer in 1 to 3 short sentences.")
        return reply

    return agent


def _history(messages: list[ChatMessage]):
    hist = []
    for msg in messages[-MAX_HISTORY:-1]:
        if msg.role == "user":
            hist.append(ModelRequest(parts=[UserPromptPart(content=msg.content)]))
        else:
            hist.append(ModelResponse(parts=[TextPart(content=msg.content)]))
    return hist


async def chat(agent: Agent, req: DripRequest, *, attempts: int = 2, timeout: float = 40.0) -> DripResponse:
    if req.messages[-1].role != "user":
        raise DripError("the last message must be from the user")
    for attempt in range(attempts):
        deps = DripDeps.from_request(req)      # fresh each attempt: a failed try leaves no actions
        try:
            result = await agent.run(req.messages[-1].content, message_history=_history(req.messages),
                                     instructions=snapshot_text(req), deps=deps, timeout=timeout)
            return DripResponse(**result.output.model_dump(), actions=deps.actions)
        except UnexpectedModelBehavior as e:
            raise DripError(f"Drip got confused: {e}") from e
        except TRANSIENT_ERRORS as e:
            if attempt == attempts - 1:
                raise DripError(f"model API kept failing: {e}") from e
            await asyncio.sleep(2)
        except (ModelAPIError, TimeoutError) as e:
            raise DripError(f"model API error: {e}") from e
    raise DripError("unreachable")


# ------------------------------------------------------------ offline model --

def _offline_drip_model():
    """Fake Drip for --provider test: keyword intents that make REAL tool calls, so the tool
    validation and the front end's action handling can be exercised with no key."""
    from pydantic_ai.messages import ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    def final(info: AgentInfo, message: str, mood: str = "happy") -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"message": message, "mood": mood})])

    def respond(messages, info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        returned = [p for p in last.parts if isinstance(p, ToolReturnPart)]
        failed = [p for p in returned if getattr(p, "outcome", "success") != "success"]
        if failed:   # a tool refused (ModelRetry): pass its reason on instead of retrying blindly
            return final(info, str(failed[0].content).split(". ")[0] + ".", "shocked")
        if returned:
            return final(info, " ".join(str(p.content) for p in returned), "casting")

        text = next((p.content for p in reversed(last.parts) if isinstance(p, UserPromptPart)), "")
        text = text if isinstance(text, str) else " ".join(x for x in text if isinstance(x, str))
        snap = json.loads((info.instructions or "").split("Current app state (JSON):\n", 1)[-1] or "{}")
        items = snap.get("wardrobe", [])
        low = text.lower()

        def mentioned():
            words = set(re.findall(r"[a-z]+", low)) - {"the", "my", "on", "a", "i", "in", "of", "to"}
            scored = [(sum(w in i["name"].lower() for w in words), i) for i in items]
            best = max((s for s, _ in scored), default=0)
            return [i for s, i in scored if s == best and s > 0]

        if "wash" in low and any(w in low for w in ("all", "everything")):
            dirty = [i["id"] for i in items if i.get("status") == "laundry"]
            if not dirty:
                return final(info, "The hamper is already empty.")
            return ModelResponse(parts=[ToolCallPart("wash", {"item_ids": dirty})])
        if any(w in low for w in ("spill", "dirty", "stain", "hamper")):
            hits = mentioned()
            if len(hits) > 1:
                return final(info, f"Which one: {' or '.join(i['name'] for i in hits[:3])}?", "thinking")
            if hits:
                return ModelResponse(parts=[ToolCallPart("send_to_laundry", {"item_id": hits[0]["id"]})])
        for d, long in zip(DAYS, LONG_DAYS):
            if long.lower() in low and ("lock" in low):
                return ModelResponse(parts=[ToolCallPart("lock_day", {"day": d, "locked": "unlock" not in low})])
        if "plan" in low or "comfy" in low:
            vibe = next((v for v in VIBES if v in low), None) or ("comfy" if "comfy" in low else None)
            days = ["Sat", "Sun"] if "weekend" in low else None
            return ModelResponse(parts=[ToolCallPart("replan", {"days": days, "vibe": vibe})])
        return final(info, "I'm the offline Drip, so I only know a few spells: wash everything, "
                           "plan the week, lock a day, or tell me what you spilled on.")

    return FunctionModel(respond)
