"""Pydantic AI harness around Gemma 4.

Providers (the "plugin" slot):
  google  Gemma 4 through Google AI Studio with your API key (GEMINI_API_KEY)
  ollama  Gemma 4 running locally (`ollama pull gemma4`)
  test    Offline fake model, so the UI/backend can be built with no key and no network

Output modes:
  prompted (default)  Schema goes in the prompt; JSON is parsed and validated. Works on any model.
  tool                Gemma returns the spec as a function call (Gemma 4 supports function calling).
  native              Provider-enforced JSON schema, if the endpoint supports it for Gemma.
Whatever the mode, a bad answer is sent back to Gemma with the validation error (up to `retries`).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass

from pydantic_ai import Agent, BinaryContent, ModelRetry, NativeOutput, PromptedOutput, RunContext, ToolOutput
from pydantic_ai.exceptions import (ModelAPIError, ModelConnectionError, ModelOverloadedError,
                                    ModelRateLimitError, ModelServerError, ModelTimeoutError,
                                    ModelUnavailableError, UnexpectedModelBehavior)

from .spec import GarmentSpec

DEFAULT_MODELS = {
    "google": "gemma-4-26b-a4b-it",  # confirm the exact ID in AI Studio; gemma-4-31b-it is the larger one
    "ollama": "gemma4",
}

INSTRUCTIONS = """\
You label clothing photos for a cute pixel-art wardrobe game.
Each photo shows ONE garment with its background removed (shown on white).
Sometimes a person is still wearing it: then set worn to true and describe only the main garment
(ignore skin, hair and other clothes when choosing colors).
You are given a numbered list of colors measured from the garment's pixels.
Describe the garment so a pixel-art renderer can draw it:
- Choose the subtype by the garment's SHAPE. Sweaters, crewnecks, button-ups and jackets are
  "longsleeve". Jeans and joggers are "pants". Baseball, trucker and dad hats are "cap"; knit hats
  are "beanie"; brimmed soft hats are "bucket". Low shoes are "sneakers"; ankle-high shoes and boots
  are "hightops".
- Colors are chosen by INDEX from the measured list, never as hex codes.
- If two measured colors are just the same fabric in light and shadow, use only one.
- secondary_color is for a real second fabric color: stripes, plaid, collar, cuffs, soles, a brim.
- accent_color is only for a printed graphic or logo on the front.
- If the print is mainly a single letter or number (like a team or college logo), use
  graphic "letter" and give that character. A short team or college word (like "PITT" or
  "UCLA") also counts: use graphic "letter" with its first letter. Use "text" only for
  slogans or several words.
- Whenever the print has lettering, also copy it into graphic_text exactly as printed
  (e.g. "PITT"), even when graphic is "letter".
"""


class SpriteGenerationError(RuntimeError):
    pass


# Worth retrying: the request was fine, the service had a bad moment (500s, 429s, timeouts).
TRANSIENT_ERRORS = (ModelServerError, ModelOverloadedError, ModelRateLimitError, ModelUnavailableError,
                    ModelTimeoutError, ModelConnectionError)
API_ATTEMPTS = 3


@dataclass
class SpriteDeps:
    colors: list[dict]


def build_user_prompt(colors: list[dict], hint: str | None = None) -> str:
    lines = "\n".join(f"  {i}: {c['hex']} ({round(c['share'] * 100)}% of garment pixels)"
                      for i, c in enumerate(colors))
    hint_line = f"\nThe user says this is a {hint}." if hint else ""
    return f"Measured colors (valid indices 0 to {len(colors) - 1}):\n{lines}{hint_line}\n\nDescribe this garment."


# ---------------------------------------------------------------- providers --

def build_model(provider: str, model_name: str | None = None, api_key: str | None = None):
    if provider == "google":
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise SpriteGenerationError("Set GEMINI_API_KEY (get one at aistudio.google.com/apikey)")
        return GoogleModel(model_name or DEFAULT_MODELS["google"], provider=GoogleProvider(api_key=key))

    if provider == "ollama":
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.ollama import OllamaProvider

        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        return OpenAIChatModel(model_name or DEFAULT_MODELS["ollama"], provider=OllamaProvider(base_url=base))

    if provider == "test":
        return _offline_model()

    raise SpriteGenerationError(f"unknown provider {provider!r} (use google, ollama or test)")


def _offline_model():
    """Fake Gemma: returns a plausible spec as JSON text. Respects --hint."""
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    def respond(messages, info: AgentInfo) -> ModelResponse:
        text = ""
        for m in messages:
            for part in getattr(m, "parts", []):
                content = getattr(part, "content", "")
                items = content if isinstance(content, list) else [content]
                text += " ".join(x for x in items if isinstance(x, str))
        hint = re.search(r"this is an? ([\w\- ]+?)\.", text)
        n = len(re.findall(r"^\s+\d+: #", text, flags=re.M)) or 1
        subtype = hint.group(1) if hint else "tshirt"
        spec = {
            "name": f"Mystery {subtype.title()}", "subtype": subtype, "pattern": "solid",
            "primary_color": 0, "secondary_color": 1 if n > 1 else None, "accent_color": None,
            "graphic": "none", "graphic_letter": None, "warmth": 3, "formality": 2,
            "vibe_tags": ["casual"], "worn": False, "graphic_text": None,
        }
        return ModelResponse(parts=[TextPart(content=json.dumps(spec))])

    return FunctionModel(respond)


def _output_type(mode: str):
    if mode == "prompted":
        return PromptedOutput(GarmentSpec, name="garment_spec",
                              description="Sprite recipe for the garment in the photo")
    if mode == "tool":
        return ToolOutput(GarmentSpec, name="submit_garment_spec")
    if mode == "native":
        return NativeOutput(GarmentSpec, name="garment_spec")
    raise SpriteGenerationError(f"unknown output mode {mode!r}")


# ------------------------------------------------------------------- harness --

class GemmaSpriter:
    """Build once, reuse for every upload."""

    def __init__(self, provider: str = "google", model: str | None = None, api_key: str | None = None,
                 output_mode: str = "prompted", retries: int = 3, temperature: float = 0.2):
        if provider == "test":
            output_mode = "prompted"  # the fake model answers in plain JSON text
        self.provider = provider
        self.model_name = model or DEFAULT_MODELS.get(provider, provider)
        self.agent: Agent[SpriteDeps, GarmentSpec] = Agent(
            build_model(provider, model, api_key),
            deps_type=SpriteDeps,
            output_type=_output_type(output_mode),
            instructions=INSTRUCTIONS,
            retries=retries,  # bare int = same budget for tool and output retries
            model_settings={"temperature": temperature},
        )

        @self.agent.output_validator
        def _check_colors(ctx: RunContext[SpriteDeps], spec: GarmentSpec) -> GarmentSpec:
            problems = spec.color_problems(len(ctx.deps.colors))
            if problems:
                raise ModelRetry("; ".join(problems) + ". Choose indices from the measured color list.")
            return spec

    @classmethod
    def from_env(cls) -> "GemmaSpriter":
        return cls(provider=os.getenv("WARDROBE_PROVIDER", "google"),
                   model=os.getenv("WARDROBE_MODEL") or None,
                   output_mode=os.getenv("WARDROBE_OUTPUT_MODE", "prompted"))

    async def describe(self, image_png: bytes, colors: list[dict], hint: str | None = None) -> GarmentSpec:
        for attempt in range(API_ATTEMPTS):
            try:
                result = await self.agent.run(
                    # Image before text is the recommended order for Gemma multimodal prompts.
                    [BinaryContent(data=image_png, media_type="image/png"), build_user_prompt(colors, hint)],
                    deps=SpriteDeps(colors=colors),
                )
                return result.output
            except UnexpectedModelBehavior as e:
                raise SpriteGenerationError(f"Gemma never produced a valid spec: {e}") from e
            except TRANSIENT_ERRORS as e:
                if attempt == API_ATTEMPTS - 1:
                    raise SpriteGenerationError(f"model API kept failing ({API_ATTEMPTS} tries): {e}") from e
                await asyncio.sleep(2 * 3 ** attempt)  # 2s, 6s
            except ModelAPIError as e:  # bad key, unknown model id, ... retrying won't help
                raise SpriteGenerationError(f"model API error: {e}") from e
