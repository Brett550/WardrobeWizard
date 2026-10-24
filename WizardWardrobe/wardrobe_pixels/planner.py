"""Gemma 4 plans the week: seven outfits chosen by item id from the clean closet.

  POST /plan/week  (server.py)  PlanRequest -> WeekPlan {days: [DayOutfit], summary}

Same pattern as the sprite spec and Drip: a schema plus a validator. Gemma picks ids; the
validator rejects anything the app couldn't wear (unknown or dirty items, wrong row, locked
days, repeated underwear/socks while clean pairs remain) and sends the reasons back, so
Gemma fixes its own plan instead of the page receiving a broken one. The front end applies
the result; on any failure it falls back to its local planner.
"""
from __future__ import annotations

import asyncio
import json
import os
from collections import Counter

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, PromptedOutput, RunContext, ToolOutput
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior

from .agent import TRANSIENT_ERRORS, build_model
from .drip import CATS, DAYS, Day, ForecastDay, PlanDay, SnapshotItem, Style

PLANNER = """\
You plan a week of outfits from the user's closet for a pixel-art wardrobe app.
For each requested day pick one item id per row: hat, top, bottom, underwear, socks, shoes.
Use only ids from the closet list, only items with status "clean", and only in their own row
(an item's "cat" is its row). Never invent items.
- Match warmth to the forecast high: below 45F warmth 5, 45-53F warmth 4, 54-63F 3, 64-73F 2, 74F+ 1.
  Shorts only on days 74F or warmer. Rainy or cold days suit hoodies and closed shoes.
- Favor items whose tags fit the style vibe (comfy, campus, sporty, dressy). For "dressy",
  prefer higher formality. Color mood: "bold" likes bright items, "calm" likes neutrals.
- Spread the closet around: don't wear the same top on two days in a row. Never repeat
  underwear or socks while unused clean pairs remain.
- hat is null on days where hat_on is false; otherwise pick a hat if one suits the day.
- A row may be null only if the closet has no clean item for it.
Answer with item ids only, no explanations.
"""


class PlanRequest(BaseModel):
    wardrobe: list[SnapshotItem] = Field(default_factory=list, max_length=200)
    plan: list[PlanDay] = Field(default_factory=list)          # current plan: locked days + hat_on
    forecast: list[ForecastDay] = Field(default_factory=list)
    style: Style = Field(default_factory=Style)
    days: list[Day] | None = None                              # default: every unlocked day


class DayOutfit(BaseModel):
    day: Day
    hat: str | None = None
    top: str | None = None
    bottom: str | None = None
    underwear: str | None = None
    socks: str | None = None
    shoes: str | None = None


class WeekPlan(BaseModel):
    # Ids only: free-text fields here sent Gemma into repetition loops ("mix-mix-mix-...").
    days: list[DayOutfit]


class PlanError(RuntimeError):
    pass


class _Deps:
    def __init__(self, req: PlanRequest):
        self.items = {i.id: i for i in req.wardrobe}
        plan = {p.day: p for p in req.plan}
        self.plan = {d: plan.get(d) or PlanDay(day=d) for d in DAYS}
        wanted = req.days or DAYS
        self.days = [d for d in DAYS if d in wanted and not self.plan[d].locked]
        self.clean = {c: [i for i in req.wardrobe if i.cat == c and i.status == "clean"] for c in CATS}


def problems(plan: WeekPlan, deps: _Deps) -> list[str]:
    """Everything the app couldn't apply as-is. Empty list = valid."""
    out = []
    got = [d.day for d in plan.days]
    missing = [d for d in deps.days if d not in got]
    extra = [d for d in got if d not in deps.days]
    if missing:
        out.append(f"Plan these days too: {', '.join(missing)}.")
    if extra:
        out.append(f"Don't plan {', '.join(extra)} (locked or not requested).")
    if len(got) != len(set(got)):
        out.append("Each day must appear once.")
    for day in plan.days:
        if day.day not in deps.days:
            continue
        for c in CATS:
            iid = getattr(day, c)
            if iid is None:
                if c == "hat" or not deps.clean[c]:
                    continue
                out.append(f"{day.day}: pick a {c}; clean ones exist.")
                continue
            it = deps.items.get(iid)
            if it is None:
                out.append(f"{day.day}: {iid!r} is not in the closet.")
            elif it.cat != c:
                out.append(f"{day.day}: {it.name} is a {it.cat}, not a {c}.")
            elif it.status != "clean":
                out.append(f"{day.day}: {it.name} is in the hamper.")
        if day.hat and not deps.plan[day.day].hat_on:
            out.append(f"{day.day}: hat_on is false, so hat must be null.")
    for c in ("underwear", "socks"):
        used = Counter(getattr(d, c) for d in plan.days if d.day in deps.days and getattr(d, c))
        repeats = [deps.items[i].name for i, n in used.items() if n > 1 and i in deps.items]
        if repeats and len(deps.clean[c]) >= len(deps.days):
            out.append(f"Don't repeat {c} ({', '.join(repeats)}): there are enough clean pairs for every day.")
    return out


def request_text(req: PlanRequest, deps: _Deps) -> str:
    closet = [{k: v for k, v in i.model_dump().items() if v not in (None, [], "")}
              for i in req.wardrobe if i.status == "clean"]
    days = [{"day": d, "hat_on": deps.plan[d].hat_on,
             **next((f.model_dump(exclude={"day"}) for f in req.forecast if f.day == d), {})} for d in deps.days]
    return ("Plan these days:\n" + json.dumps(days, separators=(",", ":")) +
            f"\nStyle: {json.dumps(req.style.model_dump())}\nClean closet:\n" +
            json.dumps(closet, separators=(",", ":")))


# Gemma 4 on AI Studio thinks before answering (~6-7k thought tokens for a week, 1-2.5 min) and
# rejects thinking_budget / thinking_level, so the cap must leave room for that.
MAX_OUTPUT_TOKENS = 12000


def build_planner(provider: str | None = None, model=None, retries: int = 1,
                  output_mode: str | None = None) -> Agent:
    provider = provider or os.getenv("WARDROBE_PROVIDER", "google")
    if model is not None and not isinstance(model, str):
        m = model
    elif provider == "test":
        m = _offline_planner_model()
    else:
        m = build_model(provider, model or os.getenv("WARDROBE_MODEL"))
    mode = output_mode or os.getenv("WARDROBE_PLAN_OUTPUT", "prompted")
    if provider == "test" or (model is not None and not isinstance(model, str)):
        mode = "tool"   # the offline/test models answer through the output tool
    output = PromptedOutput(WeekPlan, name="week_plan") if mode == "prompted" else ToolOutput(WeekPlan)
    agent = Agent(m, deps_type=_Deps, output_type=output, instructions=PLANNER, retries=retries,
                  model_settings={"temperature": 0.3, "max_tokens": MAX_OUTPUT_TOKENS})

    @agent.output_validator
    def _valid(ctx: RunContext[_Deps], plan: WeekPlan) -> WeekPlan:
        bad = problems(plan, ctx.deps)
        if bad:
            raise ModelRetry("Fix these and send the whole plan again: " + " ".join(bad[:12]))
        plan.days = [d for d in plan.days if d.day in ctx.deps.days]
        return plan

    return agent


async def plan_week(agent: Agent, req: PlanRequest, *, attempts: int = 2, timeout: float = 300.0) -> WeekPlan:
    deps = _Deps(req)
    if not deps.days:
        raise PlanError("every requested day is locked")
    if not req.wardrobe:
        raise PlanError("the closet is empty")
    for attempt in range(attempts):
        try:
            result = await agent.run(request_text(req, deps), deps=deps, timeout=timeout)
            return result.output
        except UnexpectedModelBehavior as e:
            raise PlanError(f"Gemma never produced a valid plan: {e}") from e
        except TRANSIENT_ERRORS as e:
            if attempt == attempts - 1:
                raise PlanError(f"model API kept failing: {e}") from e
            await asyncio.sleep(3)
        except (ModelAPIError, TimeoutError) as e:
            raise PlanError(f"model API error: {e}") from e
    raise PlanError("unreachable")


def _offline_planner_model():
    """Fake Gemma for --provider test: a deterministic valid plan (rotates through clean items)."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    def respond(messages, info: AgentInfo) -> ModelResponse:
        text = next(p.content for m in messages for p in getattr(m, "parts", []) if isinstance(p, UserPromptPart))
        days = json.loads(text.split("Plan these days:\n", 1)[1].split("\nStyle:", 1)[0])
        closet = json.loads(text.split("Clean closet:\n", 1)[1])
        pools = {c: [i["id"] for i in closet if i["cat"] == c] for c in CATS}
        out = []
        for n, d in enumerate(days):
            pick = {c: (pools[c][n % len(pools[c])] if pools[c] else None) for c in CATS}
            if not d.get("hat_on", True):
                pick["hat"] = None
            out.append({"day": d["day"], **pick})
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"days": out})])

    return FunctionModel(respond)
