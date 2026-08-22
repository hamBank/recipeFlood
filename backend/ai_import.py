"""Turning unstructured recipe text (or a photo) into a structured draft.

One module, three callers: the offline blog importer
(`scripts/parse_blog.py`), the paste-a-recipe endpoint, and the
photo-of-a-recipe endpoint. They differ only in how the content reaches
Claude — the schema, the prompt and the post-processing are shared, so a
fix to the parsing rules improves all three at once.

Nothing here writes to the database. Every path produces a *draft* that a
human confirms: the blog importer writes drafts to a JSON snapshot for
review, and the endpoints return one for the entry form to pre-fill. AI
output is a first pass, not a source of truth.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from .config import settings

#: The navigation sections — validated on the way back so a hallucinated
#: one can't create junk taxonomy. Mirrors data/sections.json.
SECTION_SLUGS = [
    "breakfast", "bread", "cake", "biscuits-slices", "pastry-tarts",
    "dessert", "salad", "soup", "main-vegetarian", "main-meat",
    "main-seafood", "pasta-noodles", "curry", "side", "snack",
    "dips-spreads", "sauces-dressings", "preserves-chutney", "drinks",
    "basics",
]

UNIT_VALUES = [
    "g", "kg", "mg", "ml", "l", "cup", "tbsp", "dsp", "tsp", "fl_oz",
    "oz", "lb", "piece", "slice", "clove", "bunch", "sprig", "can",
    "pinch", "to_taste",
]

SYSTEM_PROMPT = f"""\
You convert recipe text into structured JSON. The recipes are Australian:
a cup is 250ml, a tablespoon is 20ml, temperatures are Celsius.

Return ONLY a JSON object, no prose and no markdown fence, with keys:

  title            string
  description      string - one or two sentences describing the dish.
                   Write one if the source has none; do not invent
                   provenance or claims about taste you cannot support.
  section          the single best fit from: {", ".join(SECTION_SLUGS)}
                   This is the site's navigation, so pick the most
                   specific one that is true. null if none fit.
  tags             array of short lowercase strings (ingredients,
                   technique, occasion). 3-8 of them. Do NOT repeat the
                   section here; it is added automatically.
  servings         integer or null - only if the text states or clearly
                   implies it ("serves 8", "makes 24 biscuits" -> 24)
  servings_note    string or null - the original wording, e.g. "serves 8-10"
  prep_minutes     integer or null - ONLY if the text states it
  cook_minutes     integer or null - ONLY if the text states it, or if a
                   step gives an explicit oven/stove time you can total
  storage          string or null - ONLY if the text says how to keep it
  ingredients      array of objects:
                     name        string - the ingredient alone, no amount
                                 and no preparation words
                     quantity    number or null
                     quantity_max number or null - for "2-3 tbsp"
                     unit        one of {", ".join(UNIT_VALUES)}, or null
                     note        string or null - preparation ("finely
                                 chopped", "at room temperature")
                     optional    boolean
                     group       string or null - a sub-heading such as
                                 "For the sauce", if the recipe has them
                     raw_text    string - the original line, verbatim
  steps            array of strings, in order, one per action. Split a
                   run-on method paragraph into sensible numbered steps.
  notes            string or null - anything that is neither ingredient
                   nor step (yield, serving suggestion, attribution)
  confidence       number 0-1 - your confidence that the split into
                   ingredients and steps is correct
  uncertain        array of strings - anything you had to guess at

Rules:
- Never invent a prep time, cook time, storage instruction or serving
  count that the source does not support. null is the correct answer.
- Keep the author's wording in steps; fix only obvious typos.
- Ingredient lines that are really instructions ("extra virgin olive oil,
  for shallow frying") stay ingredients, with the purpose in `note`.
"""


class AIImportUnavailable(RuntimeError):
    """Raised when no API key is configured — callers turn this into a 503
    rather than a stack trace, so the feature degrades to "not set up yet"
    instead of "broken"."""


def is_configured() -> bool:
    return bool(settings.anthropic_api_key)


def _client():
    if not is_configured():
        raise AIImportUnavailable(
            "ANTHROPIC_API_KEY is not set — AI import is unavailable"
        )
    from anthropic import Anthropic  # imported lazily; not needed to serve recipes

    return Anthropic(api_key=settings.anthropic_api_key)


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def parse_json_response(text: str) -> dict[str, Any]:
    """Pull the JSON object out of a model response.

    Strips a markdown fence if one snuck in, and falls back to the outermost
    brace pair — cheaper and more predictable than retrying the call.
    """
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError(f"no JSON object in model response: {text[:200]!r}")
        return json.loads(cleaned[start : end + 1])


def normalise_draft(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce a model response into the shape the API and importer expect.

    Everything here is defensive: an out-of-vocabulary section becomes
    null rather than a bad link, a unit we don't know becomes null rather
    than a validation error, and a step list of dicts (which the model
    occasionally returns despite the prompt) is flattened to strings.
    """
    def as_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None and value != "" else None
        except (TypeError, ValueError):
            return None

    def as_float(value: Any) -> float | None:
        try:
            return float(value) if value is not None and value != "" else None
        except (TypeError, ValueError):
            return None

    section = raw.get("section")
    if section not in SECTION_SLUGS:
        section = None

    ingredients = []
    for item in raw.get("ingredients") or []:
        if isinstance(item, str):
            item = {"name": item, "raw_text": item}
        name = (item.get("name") or "").strip()
        if not name:
            continue
        unit = item.get("unit")
        ingredients.append(
            {
                "name": name,
                "quantity": as_float(item.get("quantity")),
                "quantity_max": as_float(item.get("quantity_max")),
                "unit": unit if unit in UNIT_VALUES else None,
                "note": (item.get("note") or None),
                "optional": bool(item.get("optional")),
                "group": (item.get("group") or None),
                "raw_text": (item.get("raw_text") or name).strip(),
            }
        )

    steps = []
    for step in raw.get("steps") or []:
        text = step if isinstance(step, str) else (step or {}).get("text", "")
        text = (text or "").strip()
        if text:
            steps.append({"text": text})

    tags = [
        str(tag).strip().lower()
        for tag in (raw.get("tags") or [])
        if str(tag).strip()
    ]
    # The section is just another tag as far as a recipe is concerned —
    # carrying it in `section` too is only so the importer can report it.
    if section and section not in tags:
        tags.insert(0, section)

    return {
        "title": (raw.get("title") or "").strip(),
        "description": (raw.get("description") or None),
        "section": section,
        "tags": tags[:12],
        "servings": as_int(raw.get("servings")),
        "servings_note": raw.get("servings_note") or None,
        "prep_minutes": as_int(raw.get("prep_minutes")),
        "cook_minutes": as_int(raw.get("cook_minutes")),
        "storage": raw.get("storage") or None,
        "ingredients": ingredients,
        "steps": steps,
        "notes": raw.get("notes") or None,
        "confidence": as_float(raw.get("confidence")) or 0.0,
        "uncertain": [str(u) for u in (raw.get("uncertain") or [])],
    }


def _call(content: list[dict[str, Any]], *, max_tokens: int = 4096) -> dict[str, Any]:
    response = _client().messages.create(
        model=settings.anthropic_model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    return normalise_draft(parse_json_response(text))


def draft_from_text(text: str, *, title_hint: str | None = None) -> dict[str, Any]:
    """Structure a pasted (or scraped) recipe."""
    prefix = f"The recipe is titled: {title_hint}\n\n" if title_hint else ""
    return _call([{"type": "text", "text": f"{prefix}Recipe text:\n\n{text}"}])


def draft_from_image(
    image_bytes: bytes, media_type: str, *, title_hint: str | None = None
) -> dict[str, Any]:
    """Structure a photo or scan of a recipe."""
    prefix = f"The recipe is titled: {title_hint}\n\n" if title_hint else ""
    return _call(
        [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(image_bytes).decode("ascii"),
                },
            },
            {
                "type": "text",
                "text": f"{prefix}Transcribe and structure the recipe in this image.",
            },
        ],
        max_tokens=8192,
    )
