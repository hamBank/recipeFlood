"""Filling in the master ingredient list with Claude: nutrition and price.

Two different accuracy bars for two different numbers, and the module is
built around keeping them apart rather than blending them:

* **Nutrition should be right.** Per-100g composition for a whole food
  (rice, chicken breast, olive oil) is a well-documented, slow-changing
  fact — the same handful of figures appear consistently across USDA
  FoodData Central, Australia's AUSNUT/NUTTAB, and every packet in a
  supermarket, so a model's trained knowledge of it is genuinely good for
  common ingredients. It is weaker for obscure or branded items and cannot
  read an actual label. So every value this module writes is truthfully
  labelled `nutrition_source = "AI estimate (Claude)"`, never presented as
  a verified lookup, and never overwrites a value someone already entered.
* **Price only needs to be in the right neighbourhood.** It exists so a
  recipe's cost panel isn't empty, not to reconcile a receipt. The prompt
  asks for a mid-season, mid-tier Australian retail price and says so
  through `cost_source`.

Nothing here calls the network directly — `enrich_batch` does that;
`normalise_result` and `derive_energy_kj` are pure and unit-tested without
a key. That split is what `test_ingredient_enrichment.py` exercises.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .config import settings
from .nutrition import kj_from_kcal

#: Anything outside this per-100g range for a plausible food is very
#: unlikely to be a genuine value; treat it as noise rather than fact.
PLAUSIBLE_RANGES = {
    "calories_kcal": (0, 950),   # pure fat/oil tops out around 900
    "protein_g": (0, 100),
    "fat_g": (0, 100),
    "saturated_fat_g": (0, 100),
    "carbs_g": (0, 100),
    "sugars_g": (0, 100),
    "fibre_g": (0, 60),
    "sodium_mg": (0, 40_000),    # stock powder and salt itself run high
}

#: A rough ceiling on believable Australian retail price. Above this, a
#: response is more likely a unit mistake (per-100g instead of per-kg)
#: than a genuine price.
MAX_PLAUSIBLE_COST_PER_KG_CENTS = 30_000  # $300/kg — saffron territory

NUTRITION_LABEL = "AI estimate (Claude)"
COST_LABEL_PREFIX = "AI estimate (mid-season, indicative)"

SYSTEM_PROMPT = f"""\
You describe grocery items for an Australian household pantry database.
For each item name given, return standard nutrition and a rough retail
price. Return ONLY a JSON array, no prose and no markdown fence, one
object per input item, in the SAME ORDER as the input, with keys:

  name              string — echo the input name back exactly
  is_human_food     boolean — false for pet food, cleaning products, or
                    anything else that ended up on a grocery list but a
                    person would not eat (e.g. "cat mince", "cat litter",
                    "dishwasher tablets"). When false, every field below
                    is null and `note` says what it actually is.
  calories_kcal     number or null, per 100g/100ml as typically sold
  protein_g         number or null, per 100g
  fat_g             number or null, per 100g
  saturated_fat_g   number or null, per 100g — null if unknown even when
                    fat_g is known; do not guess a fraction of it
  carbs_g           number or null, per 100g
  sugars_g          number or null, per 100g
  fibre_g           number or null, per 100g
  sodium_mg         number or null, per 100g
  cost_per_kg_cents integer or null — a typical Australian retail price in
                    cents per kilogram (or per litre for liquids). For
                    fruit and vegetables with a strong season, price as if
                    bought mid-season at a mid-range price, not the
                    cheapest special or the out-of-season peak.
  package_size_grams number or null — the usual pack size this is sold in,
                    if there plainly is one (a jar of jam, a block of
                    butter). Null for things bought loose or in whatever
                    quantity a recipe needs (garlic, onion, herbs).
  confidence        "high" / "medium" / "low" — your genuine confidence in
                    the nutrition figures specifically (not the price).
                    "low" for anything branded, prepared, or unfamiliar.
  note              string or null — a short reason ONLY when confidence
                    is "low", when is_human_food is false, or when you had
                    to assume a specific form (e.g. "as dried, not cooked").
                    Null otherwise.

Rules:
- Nutrition is per 100g/100ml of the item as normally sold, raw/dry unless
  the name says otherwise ("cooked rice" vs "rice").
- Never invent a precise-looking number for something you are not
  reasonably confident about — use null and explain briefly in `note`
  instead, or set confidence to "low".
- A prepared dish name ("chicken stir fry") rather than a raw ingredient
  should get null nutrition and a note saying so, unless it's a single
  well-defined product (e.g. "hummus" has a standard composition).
- cost_per_kg_cents is never null for a real, human food grocery item —
  give your best mid-range estimate even when unsure; that number only
  needs to be in the right neighbourhood.
"""

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


class EnrichmentUnavailable(RuntimeError):
    """Raised when no API key is configured."""


def is_configured() -> bool:
    return bool(settings.anthropic_api_key)


def _client():
    if not is_configured():
        raise EnrichmentUnavailable(
            "ANTHROPIC_API_KEY is not set — pantry enrichment is unavailable"
        )
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


def parse_json_response(text: str) -> Any:
    """Pull the JSON array out of a model response, tolerating a fence."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start == -1 or end <= start:
            raise ValueError(f"no JSON array in model response: {text[:200]!r}")
        return json.loads(cleaned[start : end + 1])


def derive_energy_kj(calories_kcal: float | None) -> float | None:
    """kJ from kcal by the standard factor, rather than asking the model
    for both and hoping they agree — see the module docstring."""
    return kj_from_kcal(calories_kcal)


def _plausible(field: str, value: float | None) -> float | None:
    if value is None:
        return None
    low, high = PLAUSIBLE_RANGES[field]
    return value if low <= value <= high else None


def _as_number(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def normalise_result(raw: dict, *, requested_name: str) -> dict:
    """One model response object -> the shape the script writes to a row.

    Defensive by field: a single out-of-range or malformed number is
    dropped rather than discarding everything else the response got
    right. `requested_name` is trusted over the model's echoed `name` for
    matching (see `match_results`); it is carried through only for the
    audit report.
    """
    is_human_food = bool(raw.get("is_human_food", True))
    confidence = str(raw.get("confidence") or "medium").lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"

    if not is_human_food:
        return {
            "name": requested_name,
            "is_human_food": False,
            "confidence": confidence,
            "note": (raw.get("note") or "not a human food item").strip(),
            "nutrition": {},
            "cost_per_kg_cents": None,
            "package_size_grams": None,
        }

    nutrition = {}
    for field in PLAUSIBLE_RANGES:
        nutrition[field] = _plausible(field, _as_number(raw.get(field)))
    nutrition["energy_kj"] = derive_energy_kj(nutrition["calories_kcal"])

    cost = _as_number(raw.get("cost_per_kg_cents"))
    cost_cents = None
    if cost is not None and 0 < cost <= MAX_PLAUSIBLE_COST_PER_KG_CENTS:
        cost_cents = round(cost)

    package = _as_number(raw.get("package_size_grams"))
    package_grams = package if package and package > 0 else None

    return {
        "name": requested_name,
        "is_human_food": True,
        "confidence": confidence,
        "note": (raw.get("note") or None),
        "nutrition": nutrition,
        "cost_per_kg_cents": cost_cents,
        "package_size_grams": package_grams,
    }


def match_results(names: list[str], raw_results: list[dict]) -> dict[str, dict]:
    """Line up a (possibly short, possibly reordered) response with the
    names that were actually asked about.

    The prompt asks for the same order and count back, but nothing here
    trusts that: results are matched by the model's echoed `name` field
    first, falling back to position only where that name is missing or
    doesn't appear in the request. A name the response never addressed is
    absent from the returned mapping — callers should treat that as "try
    again later", not "confirmed no data".
    """
    by_echoed_name = {}
    for item in raw_results:
        echoed = (item.get("name") or "").strip().lower()
        if echoed:
            by_echoed_name.setdefault(echoed, item)

    matched: dict[str, dict] = {}
    remaining = list(raw_results)
    for name in names:
        raw = by_echoed_name.get(name.strip().lower())
        if raw is None and remaining:
            # No usable name match at this position — fall back to
            # whatever is next in the response, keeping counts aligned as
            # long as nothing has drifted yet.
            raw = remaining[0]
        if raw is not None:
            if raw in remaining:
                remaining.remove(raw)
            matched[name] = normalise_result(raw, requested_name=name)
    return matched


def enrich_batch(names: list[str]) -> dict[str, dict]:
    """Ask Claude about a batch of ingredient names. See `match_results`
    for how the response is lined back up with `names`."""
    response = _client().messages.create(
        model=settings.anthropic_model,
        max_tokens=400 * max(len(names), 1),
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": "Items:\n" + "\n".join(f"- {name}" for name in names),
            }
        ],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    raw_results = parse_json_response(text)
    if not isinstance(raw_results, list):
        raise ValueError(f"expected a JSON array, got {type(raw_results).__name__}")
    return match_results(names, raw_results)


def cost_source_label() -> str:
    from datetime import date

    return f"{COST_LABEL_PREFIX} {date.today().isoformat()[:7]}"
