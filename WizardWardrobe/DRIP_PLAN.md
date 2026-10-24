# Drip: the wardrobe wizard helper

Drip is the app's one voice. Every tip, warning, loading message and suggestion comes from Drip, and you
can click Drip to ask for outfit help or to change your week by just saying what happened ("I spilled
coffee on the stripe tee"). Gemma 4 does the thinking. The app's existing functions do the changing.

## What Drip does

| Job | Example | Needs Gemma? |
| --- | --- | --- |
| **App guide** | "How do I keep Friday from changing?" → "Tap the lock under Friday." | No (canned answers) |
| **Narrator** | Laundry and weather warnings appear in Drip's speech bubble instead of the notes box. | No |
| **Stylist** | "What should I wear to an interview Wednesday?" | Yes, read-only |
| **Assistant** | "Move the flannel to Thursday and wash my socks." | Yes, with tools |
| **Morning briefing** | "Rain at 46°. Hoodie, joggers, boots today." | Optional |

## Build in three phases

Each phase is demo-able on its own, so if time runs out you still have something that works.

**Phase 0: Drip is on screen (1–2 hours, no model).** Drip sits bottom-right with a pixel speech
bubble. The existing toasts and laundry notes route into the bubble. Face changes with app state:
shocked when the hamper is full, sleepy after a minute idle, casting during uploads. Clicking Drip opens
a chat panel with quick-reply chips. A small keyword matcher answers "how do I…" questions about lock,
hamper, filter, sort and style from a canned list.

**Phase 1: Drip gives advice (2–3 hours).** Messages go to a Gemma 4 chat agent along with a compact
snapshot of the wardrobe, week plan and forecast. Drip can answer style questions but can't change
anything yet.

**Phase 2: Drip changes things (2–3 hours).** The same agent gets tools. When Gemma calls one, the
backend checks it and records it as an action. The front end applies the actions with the functions it
already has (`drop`, `sendToLaundry`, `wash`, `planWeek`) and plays the matching animation. The board
updates while Drip answers.

## Architecture

The front end owns the state, so the backend never edits the wardrobe directly. Gemma proposes actions,
the backend validates them, and the front end applies them. That keeps the prototype's in-browser state
the single source of truth, and a bad model reply can't corrupt anything.

```
 Front end                         Backend (FastAPI)                         Gemma 4
 ─────────                         ─────────────────                         ───────
 chat msg + snapshot  ──POST──►   /drip/chat
                                   Pydantic AI agent  ──── prompt + tools ──►  thinks, calls tools
                                   tools validate + record actions  ◄────────  tool calls
                                   DripReply {message, mood, actions} ◄──────  final answer
 apply actions, animate, ◄────────
 show bubble + face
```

### Request and response

```json
// POST /drip/chat
{
  "messages": [{ "role": "user", "content": "I spilled coffee on the stripe tee" }],
  "wardrobe": [
    { "id": "candy-stripe-long-sleeve", "name": "Candy Stripe Long Sleeve", "cat": "top",
      "warmth": 3, "tags": ["bold", "campus"], "status": "clean" }
  ],
  "plan": [{ "day": "Mon", "hat": null, "top": "candy-stripe-long-sleeve", "bottom": "classic-blue-jeans" }],
  "forecast": [{ "day": "Mon", "cond": "sun", "hi": 64 }],
  "style": { "vibe": "campus", "mood": "mix" }
}
```

```json
// response
{
  "message": "Into the hamper it goes. I put the white tee on Monday instead.",
  "mood": "casting",
  "actions": [
    { "type": "send_to_laundry", "item_id": "candy-stripe-long-sleeve" },
    { "type": "set_slot", "day": 0, "category": "top", "item_id": "plain-white-tee" }
  ]
}
```

Keep the snapshot compact: IDs, names, category, warmth, tags and status, with no sprites or colors as
hex. Forty items fit in about 2,000 tokens, which keeps Gemma fast.

### Tools

| Tool | What it does | Validation |
| --- | --- | --- |
| `set_slot(day, category, item_id)` | Puts an item on a day | Item exists, is clean, and matches the category |
| `clear_slot(day, category)` | Empties a slot (e.g. no hat) | Valid day and category |
| `send_to_laundry(item_id)` | Marks dirty; the front end refills its slots | Item exists and is clean |
| `wash(item_ids)` | Returns items from the hamper | Items are in the hamper |
| `replan(days, vibe)` | Re-runs the planner | Valid days and vibe |
| `lock_day(day, locked)` | Locks or unlocks a day | Valid day |

Every tool checks its arguments against the snapshot. Bad calls raise `ModelRetry` with a plain
explanation ("plain-white-tee is in the hamper; pick a clean top"), so Gemma corrects itself instead of
making things up. Gemma 4 supports function calling natively, so this uses Pydantic AI's normal tool
path.

### Agent sketch (`wardrobe_pixels/drip.py`)

```python
from dataclasses import dataclass, field
from typing import Literal
from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext
from .agent import build_model

@dataclass
class DripDeps:
    wardrobe: dict[str, dict]          # id -> compact item
    plan: list[dict]
    actions: list[dict] = field(default_factory=list)

class DripReply(BaseModel):
    message: str                        # 1-3 short sentences
    mood: Literal["happy", "thinking", "casting", "shocked", "cool"] = "happy"

drip = Agent(build_model("google"), deps_type=DripDeps, output_type=DripReply,
             instructions=DRIP_PERSONA, retries=3)

@drip.tool
def send_to_laundry(ctx: RunContext[DripDeps], item_id: str) -> str:
    """Put a dirty item in the hamper."""
    it = ctx.deps.wardrobe.get(item_id)
    if not it:
        raise ModelRetry(f"No item with id {item_id}. Use an id from the wardrobe list.")
    if it["status"] != "clean":
        raise ModelRetry(f"{it['name']} is already in the hamper.")
    it["status"] = "laundry"                       # keep the snapshot in sync for later tool calls
    ctx.deps.actions.append({"type": "send_to_laundry", "item_id": item_id})
    return f"{it['name']} is in the hamper."

# set_slot, clear_slot, wash, replan, lock_day follow the same pattern
```

The endpoint runs the agent with the message history and the snapshot, then returns `reply.message`,
`reply.mood` and `deps.actions`.

### Persona prompt

```
You are Drip, a cool pixel-art wizard who lives in the user's closet app.
Help with outfits, laundry, weather and how to use the app. Nothing else: for other
topics, say you only know clothes, briefly.
Reply in 1 to 3 short sentences. Light wizard flavor is fine; never more than one pun.
Only use item ids from the wardrobe list. Never invent clothes.
When the user wants something changed, use the tools, then say what you changed.
If a request is unclear, ask one short question instead of guessing.
```

The voice lives in the bubble's short replies, not long monologues. One joke per reply at most, so it
stays charming at message 30.

## Front end

| Piece | Details |
| --- | --- |
| **Corner Drip** | About 96px, bottom-right, on top of the board. A gentle bob every few seconds, nothing more. |
| **Speech bubble** | Pixel border like the rest of the app. Auto-hides after 6 seconds unless the chat is open. |
| **Chat panel** | Opens above Drip. Message list, input, and chips: "What should I wear today?", "I spilled on something", "Plan a cozy week", "How does the hamper work?" |
| **Faces** | happy, thinking (while waiting on Gemma), casting (when actions apply), shocked (hamper full, or an error), cool (outfit planned), sleepy (idle). The `mood` field picks the face. |
| **Applying actions** | Each action runs the existing function and plays its animation: hamper bounce, slot pop, wand sparkle. |
| **Failure** | If the server is down or slow (15 second timeout), Drip says "My crystal ball is cloudy. Try again in a sec." The app keeps working without Drip. |

### Art needed from `dripWizard.png`

The file has a solid blue background baked in, so the first step is cutting Drip out to a transparent
PNG. Then make five or six face variants by editing only the face pixels: blink, mouth open (alternate
with closed while "talking"), shocked, eyes closed (sleepy), and raised arm with wand (casting).

## Demo script

1. Open the app with the sample closet. Drip says hi and points out Thursday's rain.
2. Ask "What should I wear Wednesday? I have a presentation." Drip suggests the chinos and flannel.
3. Say "I spilled coffee on the stripe long sleeve." It goes in the hamper and Monday's top changes
   while Drip answers.
4. Say "Make the weekend comfy." Saturday and Sunday re-plan with hoodies and sweatpants.
5. Drag three more things into the hamper. Drip looks shocked and says it's laundry time.

## Test prompts

Run these before the demo, since they cover the ways chat assistants usually break.

| Prompt | Expect |
| --- | --- |
| "Wear the purple pants Monday" (none exist) | Says there aren't any and offers the closest option |
| "Put the hoodie on Monday" (there are two) | Asks which one |
| "Wash everything" | Calls `wash` with all hamper items |
| "Wear the white tee Monday" while it's in the hamper | Refuses, or offers to wash it first |
| "What's the capital of France?" | Short redirect to clothes |
| An empty wardrobe | Suggests adding clothes; no tool calls |
| Ten messages in a row | Replies stay short and on topic |
