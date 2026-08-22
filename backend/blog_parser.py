"""Deterministic fallback parser for the Blogger posts.

The primary import path is `scripts/parse_blog.py` driving Claude over
every post (see ai_import.py) — it reads prose methods, writes
descriptions, and picks categories far better than rules can. This module
is the offline alternative, and it earns its place three ways:

* the pipeline is testable and the loader verifiable without an API key;
* re-running the AI import is never *required* to rebuild the site;
* its output is the same draft shape, so the two are interchangeable.

The blog's posts have no headings at all. Every one is a run of `<br />`
separated lines: an ingredient block, a blank line, then the method. So
the whole problem is deciding where the ingredients stop, which is what
`classify_line` and `split_sections` below do.
"""

from __future__ import annotations

import html
import re

from .units import UNIT_ALIASES, normalise_fractions, parse_amount

_BREAK = re.compile(r"<\s*(br|/p|/div|/li|/h[1-6])\s*/?\s*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_NUMBERED = re.compile(r"^\s*(\d{1,2})\s*[.)]\s+")
_STEP_VERBS = frozenset(
    """place preheat combine heat add mix stir bake cook simmer boil whisk beat
    pour spread sprinkle serve remove drain season transfer cover chill
    refrigerate freeze roast fry saute sauté grill toss line grease melt
    knead roll cut slice arrange bring reduce return divide fold blend
    process pulse strain rinse soak marinate garnish top scatter dust turn
    allow leave set continue repeat meanwhile using once when""".split()
)
_UNIT_WORDS = frozenset(UNIT_ALIASES)

#: Blog labels that imply a category. Checked longest-first, so
#: "warm salad" resolves before "salad".
_LABEL_CATEGORY = {
    "panforte": "biscuits-slices", "biscuit": "biscuits-slices",
    "shortbread": "biscuits-slices", "slice": "biscuits-slices",
    "brownie": "biscuits-slices", "bar": "biscuits-slices",
    "cake": "cake", "muffin": "cake", "cupcakes": "cake", "sponge": "cake",
    "bread": "bread", "croissant": "pastry-tarts", "pastry": "pastry-tarts",
    "profiterole": "pastry-tarts", "tart": "pastry-tarts",
    "pie": "pastry-tarts", "strudel": "pastry-tarts",
    "dessert": "dessert", "pudding": "dessert", "icecream": "dessert",
    "panna cotta": "dessert", "creme brulee": "dessert",
    "creme caramel": "dessert", "tiramisu": "dessert", "mousse": "dessert",
    "granita": "dessert", "crumble": "dessert", "cheesecake": "dessert",
    "custard": "basics", "pastry cream": "basics", "honeycomb": "basics",
    "salad": "salad", "warm salad": "salad", "coleslaw": "salad",
    "soup": "soup", "curry": "curry", "dahl": "curry", "dhal": "curry",
    "pasta": "pasta-noodles", "gnocchi": "pasta-noodles",
    "noodle": "pasta-noodles",
    "seafood": "main-seafood", "fish": "main-seafood",
    "salmon": "main-seafood", "prawns": "main-seafood",
    "squid": "main-seafood", "calamari": "main-seafood",
    "chicken": "main-meat", "lamb": "main-meat", "veal": "main-meat",
    "beef": "main-meat", "pork": "main-meat", "roast": "main-meat",
    "vegetarian": "main-vegetarian", "tofu": "main-vegetarian",
    "vegie burger": "main-vegetarian", "burger": "main-vegetarian",
    "breakfast": "breakfast", "pancake": "breakfast",
    "bircher museli": "breakfast", "crepe": "breakfast",
    "preserves": "preserves-chutney", "chutney": "preserves-chutney",
    "jam": "preserves-chutney", "butter": "preserves-chutney",
    "dip": "dips-spreads", "baba ganouj": "dips-spreads",
    "sauce": "sauces-dressings", "salsa": "sauces-dressings",
    "pesto": "sauces-dressings", "salsa verde": "sauces-dressings",
    "punch": "drinks", "mocktail": "drinks",
    "fritter": "snack", "protein balls": "snack", "toffee": "snack",
    "truffle": "snack", "fruit and nut": "snack",
    "gratin": "side", "vegetable": "side", "roast vegies": "side",
}


def html_to_lines(content_html: str) -> list[str]:
    """Flatten a post body to a list of visible text lines."""
    text = _BREAK.sub("\n", content_html or "")
    text = _TAG.sub("", text)
    text = html.unescape(text).replace("\xa0", " ")
    return [line.strip() for line in text.split("\n")]


#: Lines that are section labels, not content. The posts have no real
#: headings, but a handful type one out ("Ingredients:", "Method").
_HEADING = re.compile(
    r"^\s*(ingredients?|method|directions?|instructions?|preparation|steps?|"
    r"you will need|to serve|notes?)\s*[:\-–]?\s*$",
    re.IGNORECASE,
)


def is_heading(line: str) -> bool:
    return bool(_HEADING.match(line.strip()))


def classify_line(line: str) -> str:
    """'ingredient', 'step' or 'other' for a single line.

    The signals, in the order they actually decide things:
      * "1." / "2)" prefix          -> step, unambiguously
      * starts with a number and is short     -> ingredient
      * contains a unit word early and is short -> ingredient
      * opens with a cooking verb    -> step
      * long                         -> step (methods are prose, amounts aren't)
    """
    stripped = line.strip()
    if not stripped:
        return "other"
    if is_heading(stripped):
        return "other"
    if _NUMBERED.match(stripped):
        return "step"

    words = normalise_fractions(stripped).split()
    if not words:
        return "other"
    lowered = [w.strip(",.()").lower() for w in words]

    starts_numeric = bool(re.match(r"^[\d½¼¾⅓⅔⅛]", normalise_fractions(stripped)))
    has_early_unit = any(w in _UNIT_WORDS for w in lowered[:3])
    short = len(words) <= 14

    if starts_numeric and short:
        return "ingredient"
    if has_early_unit and short:
        return "ingredient"
    if lowered[0] in _STEP_VERBS:
        return "step"
    if len(words) > 18 or stripped.count(".") >= 2:
        return "step"
    if short and not stripped.endswith("."):
        # A bare "salt and pepper" or "olive oil, for frying".
        return "ingredient"
    return "step"


def split_sections(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Partition a post into (ingredients, steps, leftovers).

    Ingredients are taken as the leading run: scanning from the top,
    ingredient-classified lines are collected until two consecutive step
    lines appear, which is where the method starts. Requiring *two* stops a
    single wordy ingredient ("extra virgin olive oil, for shallow frying")
    from ending the block early.
    """
    ingredients: list[str] = []
    steps: list[str] = []
    other: list[str] = []

    index = 0
    consecutive_steps = 0
    while index < len(lines):
        line = lines[index]
        if not line:
            index += 1
            continue
        kind = classify_line(line)
        if kind == "ingredient" and consecutive_steps < 2:
            ingredients.append(line)
            consecutive_steps = 0
        elif kind == "step":
            consecutive_steps += 1
            if consecutive_steps >= 2 or ingredients:
                break
            other.append(line)
        else:
            other.append(line)
        index += 1

    # Everything from the break onwards is method.
    for line in lines[index:]:
        if line:
            steps.append(line)
    return ingredients, steps, other


_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def normalise_steps(raw_steps: list[str]) -> list[str]:
    """Turn method lines into a clean ordered list.

    Numbered lines keep their own boundaries with the number stripped. A
    single unnumbered paragraph — about 40% of these posts — is split on
    sentence boundaries, then very short fragments are glued back onto the
    previous step so "Cool." doesn't become a step of its own.
    """
    # (text, was_explicitly_numbered) — the flag matters below.
    steps: list[tuple[str, bool]] = []
    for line in raw_steps:
        stripped = _NUMBERED.sub("", line).strip()
        if not stripped:
            continue
        if _NUMBERED.match(line):
            steps.append((stripped, True))
        else:
            steps.extend(
                (part.strip(), False) for part in _SENTENCE.split(stripped) if part.strip()
            )

    merged: list[str] = []
    previous_numbered = False
    for text, numbered in steps:
        # Glue only fragments the sentence splitter produced. An author who
        # numbered "2. Mix the flour." meant it as its own step, however
        # short it is.
        if merged and not numbered and not previous_numbered and len(text.split()) <= 3:
            merged[-1] = f"{merged[-1]} {text}"
        else:
            merged.append(text)
            previous_numbered = numbered
    return merged


_SERVES = re.compile(r"\b(?:serves|makes)\s+(?:about\s+)?(\d+)(?:\s*[-–to]+\s*(\d+))?", re.I)
_OVEN_MINUTES = re.compile(r"(\d+)\s*(?:-|–|to)?\s*(\d+)?\s*(min|mins|minutes|hour|hours|hr|hrs)\b", re.I)


def find_servings(text: str) -> tuple[int | None, str | None]:
    """Pull "Serves 8" / "Makes 24" out of the body, if present."""
    match = _SERVES.search(text)
    if not match:
        return None, None
    return int(match.group(1)), match.group(0).strip()


def guess_category(labels: list[str], title: str) -> str | None:
    """Map the post's Blogger labels onto a category slug.

    Longest label match wins so "warm salad" beats "salad"; the title is a
    fallback for the 40-odd posts with no labels at all.
    """
    haystack = [label.lower() for label in labels]
    best: tuple[int, str] | None = None
    for label in haystack:
        for key, slug in _LABEL_CATEGORY.items():
            if key == label and (best is None or len(key) > best[0]):
                best = (len(key), slug)
    if best:
        return best[1]
    lowered = f" {title.lower()} "
    for key, slug in sorted(_LABEL_CATEGORY.items(), key=lambda kv: -len(kv[0])):
        if f" {key}" in lowered:
            return slug
    return None


def parse_post(post: dict) -> dict:
    """Turn one raw blog post into the same draft dict `ai_import` returns."""
    title = (post.get("title") or "").strip().lower()
    lines = [
        line
        for line in html_to_lines(post.get("content_html", ""))
        # Several posts restate their own title as the first body line;
        # left in, it classifies as an ingredient and pollutes the pantry.
        if line.strip().lower().rstrip(":") != title or not title
    ]
    plain = "\n".join(lines)
    ingredient_lines, step_lines, other = split_sections(lines)
    steps = normalise_steps(step_lines)

    ingredients = []
    for line in ingredient_lines:
        quantity, quantity_max, unit, remainder = parse_amount(line)
        name, _, note = remainder.partition(",")
        ingredients.append(
            {
                "name": name.strip() or remainder.strip() or line,
                "quantity": quantity,
                "quantity_max": quantity_max,
                "unit": unit.value if unit else None,
                "note": note.strip() or None,
                "optional": "optional" in line.lower(),
                "group": None,
                "raw_text": line,
            }
        )

    servings, servings_note = find_servings(plain)

    # Confidence is deliberately capped below the AI path's: even a
    # well-formed post gives no description, times or storage, so these
    # drafts should always sort above AI ones in the review queue.
    confidence = 0.0
    if ingredients and steps:
        confidence = 0.6 if len(ingredients) >= 3 else 0.4
    uncertain = []
    if not ingredients:
        uncertain.append("no ingredient lines identified")
    if not steps:
        uncertain.append("no method identified")
    if other:
        uncertain.append(f"{len(other)} line(s) not classified")

    return {
        "title": post.get("title") or "Untitled",
        "description": None,
        "category_slug": guess_category(post.get("labels", []), post.get("title", "")),
        "tags": [label.lower() for label in post.get("labels", [])],
        "servings": servings,
        "servings_note": servings_note,
        "prep_minutes": None,
        "cook_minutes": None,
        "storage": None,
        "ingredients": ingredients,
        "steps": [{"text": step} for step in steps],
        "notes": "\n".join(other) or None,
        "confidence": confidence,
        "uncertain": uncertain,
    }
