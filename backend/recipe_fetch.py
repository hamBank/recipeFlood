"""Turning a URL from the cooking-history CSV into a recipe draft.

Two tiers, cheapest and most trustworthy first:

1. **schema.org JSON-LD.** Most recipe sites already embed a machine-
   readable `Recipe` object for their own SEO — `extract_json_ld_recipe`
   finds it, `draft_from_json_ld` reshapes it into the same draft shape
   `ai_import.py` produces. No API call, no guessing.
2. **AI-from-text.** Sites with no structured data fall back to
   `ai_import.draft_from_text` over the page's stripped visible text —
   the same model pipeline the paste-a-recipe endpoint uses.

Both tiers return the identical draft shape (title, ingredients, steps,
...), so the importer that calls `fetch_recipe_draft` doesn't need to care
which one fired — only that a JSON-LD draft is the page's own data
(confidence 1.0) and an ai_text draft is a model's read of it.

This module never fetches, stores, or re-displays anything but text: see
SPEC.md's "Recipes from other sites, and copyright" for why — formatting
and images are never preserved, only the facts, and `source_url` always
keeps the link back to the original.

Only `fetch_html` and `fetch_recipe_draft` touch the network; everything
else is pure and unit tested against saved HTML fixtures.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from . import ai_import
from .units import parse_amount

USER_AGENT = (
    "recipeFlood/1.0 (+https://github.com/hamBank/recipeflood; "
    "personal recipe archive, one request at a time)"
)

_JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BREAK_RE = re.compile(r"<\s*(br|/p|/div|/li|/h[1-6])\s*/?\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def parse_iso8601_duration(value: str | None) -> int | None:
    """"PT1H30M" -> 90. None for anything empty, malformed, or all-zero.

    Seconds are truncated rather than rounded — a recipe's stated minutes
    are never precise to the second anyway.
    """
    if not value:
        return None
    match = _ISO_DURATION_RE.match(value.strip())
    if not match:
        return None
    parts = {k: int(v) for k, v in match.groupdict(default="0").items()}
    if not any(parts.values()):
        return None
    total_seconds = (
        parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]
    )
    return total_seconds // 60


def _iter_json_ld_blocks(html_text: str):
    for match in _JSON_LD_RE.finditer(html_text):
        raw = html.unescape(match.group(1)).strip()
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue


def _iter_ld_nodes(blob):
    """Flatten a JSON-LD payload, however it's nested: a bare object, a
    list of objects, or an @graph wrapper — recipe sites use all three."""
    if isinstance(blob, list):
        for item in blob:
            yield from _iter_ld_nodes(item)
    elif isinstance(blob, dict):
        if "@graph" in blob:
            yield from _iter_ld_nodes(blob["@graph"])
        else:
            yield blob


def _is_recipe_node(node: dict) -> bool:
    node_type = node.get("@type")
    if isinstance(node_type, list):
        return "Recipe" in node_type
    return node_type == "Recipe"


def extract_json_ld_recipe(html_text: str) -> dict | None:
    """The first schema.org Recipe node in the page's JSON-LD, if any."""
    for blob in _iter_json_ld_blocks(html_text):
        for node in _iter_ld_nodes(blob):
            if isinstance(node, dict) and _is_recipe_node(node):
                return node
    return None


def _parse_yield(value) -> tuple[int | None, str | None]:
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    match = re.search(r"\d+", text)
    servings = int(match.group()) if match else None
    note = None if text.isdigit() else text
    return servings, note


def _parse_ingredient_line(line: str) -> dict:
    quantity, quantity_max, unit, remainder = parse_amount(line)
    return {
        "name": remainder.strip() or line.strip(),
        "quantity": quantity,
        "quantity_max": quantity_max,
        "unit": unit.value if unit else None,
        "note": None,
        "optional": False,
        "group": None,
        "raw_text": line.strip(),
    }


def _parse_instructions(value) -> list[dict]:
    texts: list[str] = []

    def add_block(text: str) -> None:
        for line in text.splitlines():
            line = line.strip()
            if line:
                texts.append(line)

    def walk(node) -> None:
        if node is None:
            return
        if isinstance(node, str):
            add_block(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            # HowToSection nests further steps under itemListElement;
            # HowToStep (or a plain object some sites use instead) carries
            # its text directly.
            if "itemListElement" in node:
                walk(node["itemListElement"])
            elif "text" in node:
                add_block(str(node["text"]))
            elif "name" in node:
                add_block(str(node["name"]))

    walk(value)
    return [{"text": text} for text in texts]


def draft_from_json_ld(node: dict) -> dict:
    """The same draft shape `ai_import.normalise_draft` produces, built
    from a schema.org Recipe node instead of a model response.

    Confidence is 1.0: this is the page's own structured data, not a
    read of it. It still ships `needs_review=True` like every import —
    that flag is about trusting a stranger's recipe, not about parse
    accuracy — but it isn't uncertain the way a model transcription is.
    """
    ingredients = [
        _parse_ingredient_line(str(line))
        for line in (node.get("recipeIngredient") or node.get("ingredients") or [])
        if str(line).strip()
    ]
    servings, servings_note = _parse_yield(node.get("recipeYield"))
    description = node.get("description")
    if isinstance(description, str):
        description = description.strip() or None
    else:
        description = None
    return {
        "title": str(node.get("name") or "").strip(),
        "description": description,
        "section": None,
        "tags": [],
        "servings": servings,
        "servings_note": servings_note,
        "prep_minutes": parse_iso8601_duration(node.get("prepTime")),
        "cook_minutes": parse_iso8601_duration(node.get("cookTime")),
        "storage": None,
        "ingredients": ingredients,
        "steps": _parse_instructions(node.get("recipeInstructions")),
        "notes": None,
        "confidence": 1.0,
        "uncertain": [],
    }


def html_to_text(html_text: str) -> str:
    """Strip a page down to its visible text, for the AI-from-text
    fallback. Not meant to be readable — draft_from_text only needs the
    words, in roughly the right line breaks."""
    text = _SCRIPT_STYLE_RE.sub(" ", html_text)
    text = _BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK_LINES_RE.sub("\n\n", text).strip()


def _is_usable(draft: dict) -> bool:
    """A JSON-LD draft counts as a hit only once it clears the bar an
    empty or malformed Recipe node wouldn't — no title, or no
    ingredients, means the AI fallback still has something to add."""
    return bool(draft.get("title")) and bool(draft.get("ingredients"))


_last_request_at = 0.0


def _cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.html"


def fetch_html(
    url: str,
    *,
    cache_dir: Path | None = None,
    timeout: float = 15.0,
    min_interval: float = 2.0,
) -> str:
    """The page's raw HTML, cached to disk by URL hash so a re-run costs
    nothing. `min_interval` is the polite floor between any two live
    requests this process makes — irrelevant once a URL is cached, which
    is the point: a re-run of the whole CSV only ever re-fetches what
    changed.
    """
    if cache_dir is not None:
        cached = _cache_path(cache_dir, url)
        if cached.exists():
            return cached.read_text(encoding="utf-8")

    global _last_request_at
    wait = min_interval - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    _last_request_at = time.monotonic()
    response.raise_for_status()

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        _cache_path(cache_dir, url).write_text(response.text, encoding="utf-8")
    return response.text


@dataclass(frozen=True)
class FetchedRecipe:
    draft: dict
    tier: str  # "json_ld" or "ai_text"


def fetch_recipe_draft(url: str, *, cache_dir: Path | None = None) -> FetchedRecipe:
    """Fetch and structure a recipe, cheapest tier first.

    Raises whatever `requests` or `ai_import.draft_from_text` raise on
    failure (a bad status, a timeout, no API key configured) — the
    caller (scripts/import_recipe_history.py) is what decides a failed
    fetch just means one more row in the look-up-later CSV.
    """
    html_text = fetch_html(url, cache_dir=cache_dir)
    node = extract_json_ld_recipe(html_text)
    if node is not None:
        draft = draft_from_json_ld(node)
        if _is_usable(draft):
            return FetchedRecipe(draft=draft, tier="json_ld")
    return FetchedRecipe(draft=ai_import.draft_from_text(html_to_text(html_text)), tier="ai_text")
