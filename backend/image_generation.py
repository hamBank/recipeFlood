"""Generating a placeholder photo for a recipe with none.

Claude has no image-generation endpoint of its own — this calls OpenAI's
Images API instead, a separate provider and a separate key
(`OPENAI_API_KEY`). Nothing here writes to the database or the
filesystem; `scripts/generate_recipe_images.py` is what saves the result
and updates the recipe.

Every image this produces is a generated illustration, never a photo of
the actual dish — `Recipe.image_generated` records that, so the UI can
say so rather than let it pass as a real photo. That distinction also
sidesteps SPEC.md's "Images" copyright caution around the blog's
hotlinked photos entirely: there's no original to attribute, because
there isn't one — this is original output from a text prompt.
"""

from __future__ import annotations

import base64
import random
import time

import requests

from .config import settings

#: Per-image price OpenAI publishes for gpt-image-1 at 1024x1024, as of
#: August 2026 — used only to estimate spend before a run. Verify against
#: platform.openai.com/pricing before a large one: gpt-image-1 is
#: scheduled for deprecation 2026-10-23, and a different model configured
#: via OPENAI_IMAGE_MODEL will price differently regardless.
COST_PER_IMAGE_USD = {
    "low": 0.011,
    "medium": 0.042,
    "high": 0.167,
}

_ENDPOINT = "https://api.openai.com/v1/images/generations"

#: A backfill run fires this endpoint hundreds of times in a row, so
#: hitting OpenAI's rate limit is routine, not exceptional — worth a few
#: retries before letting a recipe count as a real failure.
_MAX_ATTEMPTS = 5
_BASE_DELAY_SECONDS = 1.0


class ImageGenerationUnavailable(RuntimeError):
    """Raised when no API key is configured — callers turn this into a
    "not set up yet" message rather than a stack trace."""


def is_configured() -> bool:
    return bool(settings.openai_api_key)


def build_prompt(title: str, description: str | None, section: str | None) -> str:
    """A food-photography prompt built only from what the recipe actually
    states. Deliberately generic beyond that — nothing here invents a
    specific plating, garnish or setting the recipe never mentioned.
    """
    parts = [f"A professional, appetizing food photograph of {title.strip()}."]
    if description and description.strip():
        parts.append(description.strip())
    if section and section.strip():
        parts.append(f"This is a {section.strip().lower()} dish.")
    parts.append(
        "Natural lighting, shallow depth of field, served on a plate or in "
        "a bowl. No text, no watermark, no hands, no people."
    )
    return " ".join(parts)


def _retry_delay(attempt: int, retry_after_header: str | None) -> float:
    """Seconds to wait before retrying a rate-limited (429) request.

    Honours the server's own `Retry-After` header when it sends a valid
    one; otherwise falls back to exponential backoff (1s, 2s, 4s, 8s...)
    with a little jitter so retries piling up from the same burst don't
    all land on the same second.
    """
    if retry_after_header is not None:
        try:
            return max(0.0, float(retry_after_header))
        except ValueError:
            pass
    return _BASE_DELAY_SECONDS * (2**attempt) + random.uniform(0, 0.5)


def generate_image(
    prompt: str, *, quality: str = "low", size: str = "1024x1024"
) -> bytes:
    """One image, as raw bytes (PNG unless `size`/model says otherwise).

    Raises `ImageGenerationUnavailable` with no key configured, or lets
    `requests`' own exceptions / a `ValueError` (an unexpected response
    shape) propagate otherwise — the caller (the backfill script) is what
    decides a failed generation just means one more recipe skipped this
    run. A 429 (rate limited) is retried with backoff up to
    `_MAX_ATTEMPTS` times before it's allowed to propagate that way too.
    """
    if not is_configured():
        raise ImageGenerationUnavailable(
            "OPENAI_API_KEY is not set — image generation is unavailable"
        )
    payload = {
        "model": settings.openai_image_model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": 1,
        # GPT image models always return base64 and reject
        # response_format outright — omitted, not set to "b64_json".
    }
    for attempt in range(_MAX_ATTEMPTS):
        response = requests.post(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json=payload,
            timeout=120,
        )
        if response.status_code == 429 and attempt < _MAX_ATTEMPTS - 1:
            time.sleep(_retry_delay(attempt, response.headers.get("Retry-After")))
            continue
        break
    response.raise_for_status()
    data = response.json().get("data") or []
    if not data or not data[0].get("b64_json"):
        raise ValueError(f"no image returned: {response.text[:200]!r}")
    return base64.b64decode(data[0]["b64_json"])
