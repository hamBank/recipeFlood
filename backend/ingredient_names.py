"""Reading an ingredient's name out of a recipe line.

A recipe line's name is rarely just the name. Blog posts and pasted lists give
us things like::

    kecap manis (or dark chinese soy)      alternatives in brackets
    red (cayenne) pepper                   a synonym in the middle
    onion, finely chopped                  preparation after the name
    x 7 g tin anchovies – drained          a pack size, a container, a method
    sugar 250 mL                           a second quantity fused to the name
    juice 2 lemons                         the amount sits inside the name

Left as they are, each of those becomes its own pantry row and its own
shopping line, so "sugar" and "sugar 250 mL" never merge. This module pulls a
name apart into the part that says *what to buy* and the parts that say how
much and how to prepare it, so the rest of the app can match on the first and
keep the others as a note.

## What lives here, and what doesn't

* `clean_name` is pure text: it never looks at the pantry.
* `MATCH_NOISE` words are dropped from the *match key* everywhere. They are
  prep and quality words that never change what you walk out of the shop with
  ("finely", "chopped", "organic").
* Words that can be a product in their own right ("shredded cheese", "cube
  steak", "jar garlic", "ground almonds") are **not** in that list. They only
  stop counting against a match where the pantry row says so, in its own
  `prep_terms` (see `prep_match`). That is the point of keeping the
  vocabulary in the pantry: whether "boneless" is prep or part of the name is
  a fact about the ingredient, not about English.

* `PRODUCT_WORDS` ("frozen", "canned", "smoked", "dried", "juice", "paste")
  make a different product. They are never noise, and no fuzzy match may add
  one: a "peas" line never reaches a lone "frozen peas" row.
* A type after a spaced dash is part of the name: "Pear - Green" keys as
  "green pear", the pantry's naming for types of fruit, vegetables, cream
  and wine. An instruction after a dash ("onion - finely chopped") is still
  a note.
* `SYNONYMS` give the shop's name: "bell pepper" is "capsicum", "cilantro"
  is "coriander", "tinned" is "canned", American spellings are Australian.

Matching is deliberately conservative, for the reason `shopping.py` gives: a
wrong merge is worse than no merge. In the same spirit `leaf` is not noise
("lime leaf" is not "lime"); what a leaf means for a herb is the pantry's to
say, in `prep_terms`.

## Plurals

The original rule dropped one trailing "s", which turned "tomatoes",
"cherries" and "leaves" into "tomatoe", "cherrie" and "leave", and pantry rows
were named with those. The fix is not to rename the world and hope: every
comparison goes through `fold_word`, which maps all spellings of a word, the
mangled ones too, to one real word (see the section below).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .models import MeasureUnit
from .units import UNIT_ALIASES, normalise_fractions

#: Words dropped from an ingredient name before matching it against the pantry,
#: so "finely chopped fresh flat-leaf parsley" finds "parsley". These never
#: change the product. (The first block is the long-standing list from
#: `recipes_service`; the second is words the importers kept tripping on.)
_BASE_NOISE: frozenset[str] = frozenset({
    "fresh", "dried", "frozen", "chopped", "finely", "roughly", "thinly",
    "sliced", "diced", "grated", "crushed", "minced", "ground", "whole",
    "large", "small", "medium", "extra", "good", "quality", "free",
    "range", "organic", "raw", "cooked", "peeled", "trimmed", "washed",
    "rinsed", "drained", "lightly", "beaten", "melted", "softened",
    "toasted", "flat", "leaf", "plus", "more", "to", "serve", "taste",
    "of", "the", "a", "an", "and", "or", "for", "at", "room", "temperature",
})
#: `leaf` is not noise any more. It was there for "flat leaf parsley", but it
#: also made "lime leaf" the same as "lime" and "curry leaf" the same as
#: "curry", and only for the singular ("leaves" was never noise). "Flat leaf" is
#: handled as the pair it is (see `clean_name`); what a leaf means for a herb is
#: the pantry's to say, with `prep_terms`. The original list stays in
#: `_BASE_NOISE` so `legacy_key` can still reach every row it used to.
MATCH_NOISE: frozenset[str] = (_BASE_NOISE - {"leaf"} - {"frozen", "dried"}) | frozenset({
    # Added with the name cleaner: adverbs, sizes and qualifiers.
    "freshly", "ripe", "very", "about", "approximately", "optional", "sifted",
    "firmly", "loosely", "coarsely", "thickly", "med", "sized", "scant",
    "heaped", "heaping", "level", "generous", "big",
})

#: Words that make a different product, not a prepared version of the same one:
#: frozen spinach is not spinach, a tin of tomatoes is not tomatoes. They are
#: never noise, and no fuzzy match may add one (`find_ingredient`). ("frozen"
#: and "dried" were noise until 2026-11; `legacy_key` still drops them, for the
#: slugs minted back then.)
PRODUCT_WORDS: frozenset[str] = frozenset({
    "tinned", "canned", "tin", "tins", "frozen", "smoked", "dried", "dry",
    "pickled", "preserved", "candied", "glace", "crystallised", "crystallized",
    "desiccated", "evaporated", "condensed", "powdered", "instant", "cured",
    "jarred", "bottled", "juice", "paste", "powder", "sauce", "oil", "stock",
    "extract", "essence", "syrup", "jam", "soup", "flavour", "flavor",
    "flavoured", "flavored", "vinegar", "cordial", "liqueur", "concentrate",
})

#: The same thing under another name: the Australian name and spelling win,
#: because that is what the shop calls it. Compared on folded words, so plurals
#: are covered. Used for matching keys and, by the duplicate finder, to rename.
SYNONYMS: dict[tuple[str, ...], tuple[str, ...]] = {
    ("bell", "pepper"): ("capsicum",),
    ("sweet", "pepper"): ("capsicum",),
    ("chili",): ("chilli",),
    ("chile",): ("chilli",),
    ("cilantro",): ("coriander",),
    ("courgette",): ("zucchini",),
    ("aubergine",): ("eggplant",),
    ("scallion",): ("spring", "onion"),
    ("green", "onion"): ("spring", "onion"),
    ("arugula",): ("rocket",),
    ("romaine",): ("cos",),
    ("cornstarch",): ("cornflour",),
    ("corn", "starch"): ("cornflour",),
    ("all", "purpose", "flour"): ("plain", "flour"),
    ("powdered", "sugar"): ("icing", "sugar"),
    ("confectioners", "sugar"): ("icing", "sugar"),
    ("superfine", "sugar"): ("caster", "sugar"),
    ("castor", "sugar"): ("caster", "sugar"),
    ("baking", "soda"): ("bicarb", "soda"),
    ("bicarbonate", "soda"): ("bicarb", "soda"),
    ("ground", "beef"): ("beef", "mince"),
    ("minced", "beef"): ("beef", "mince"),
    ("shrimp",): ("prawn",),
    ("garbanzo",): ("chickpea",),
    ("chick", "pea"): ("chickpea",),
    ("golden", "raisin"): ("sultana",),
    ("yogurt",): ("yoghurt",),
    ("flavor",): ("flavour",),
    ("flavored",): ("flavoured",),
    ("color",): ("colour",),
    # Canned, not tinned: the household's word.
    ("tinned",): ("canned",),
    ("tin",): ("canned",),
    # The household's name for bao.
    ("steamed", "bun"): ("chinese", "steamed", "bun"),
}

#: Words after a spaced dash that are instructions, not a type: "basil - to
#: serve", "tomatoes - see note".
_INSTRUCTION_WORDS: frozenset[str] = frozenset({
    "see", "note", "notes", "garnish", "garnishing", "serving", "serve",
    "divided", "reserved", "optional", "plus", "extra", "approx", "approximately",
    "about", "or", "and", "for", "to", "at", "if", "as", "needed", "taste",
    "before", "after", "until", "then", "when", "sift", "use", "see",
})

#: Preparation-method words. Not part of the match key (a "cube steak" is a
#: real cut of meat) but safe to ignore once a pantry row claims them, and
#: used by `scripts/find_duplicate_ingredients.py`.
PREP_WORDS: frozenset[str] = frozenset({
    "shredded", "julienned", "julienne", "cubed", "cube", "cubes",
    "quartered", "quarters", "halved", "halves", "wedged", "wedges",
    "mashed", "pureed", "puree", "zested", "zest", "juiced", "seeded", "deseeded",
    "hulled", "pitted", "stemmed", "shelled", "boned", "skinned",
    "diagonally", "lengthwise", "crosswise", "cut", "strips", "chunks",
    "pieces", "slivered", "slivers", "into",
})

#: Qualitative size/amount words — "1 Big Onion", "Generous Pinch Salt".
SIZE_WORDS: frozenset[str] = frozenset({"big", "generous", "heaped", "heaping", "level", "scant", "pinch"})

#: Units that show up attached to a bare number right in a name.
UNIT_WORDS: frozenset[str] = frozenset({
    "oz", "ounce", "ounces", "g", "gram", "grams", "kg", "kilogram",
    "kilograms", "lb", "lbs", "pound", "pounds", "ml", "l", "litre",
    "liter", "litres", "liters", "mg", "inch", "inches", "cm", "mm",
})

#: Packaging words. Only treated as noise next to a pack size ("x 7 g tin") or
#: an "of" ("packet of biscuits"): on their own they can be the product ("jar
#: garlic" is not the same purchase as "garlic").
#: How much, said in front of the name: "handfuls rice", "block halloumi",
#: "sheets filo pastry". Never the name itself (the name follows), so dropped
#: from the front wherever they are, into the note.
AMOUNT_WORDS: frozenset[str] = frozenset({
    "handful", "handfuls", "block", "blocks", "sheet", "sheets", "bunch", "bunches",
    "sprig", "sprigs", "pinch", "pinches", "dash", "dashes", "splash", "knob", "knobs",
    "packet", "packets", "pkt", "pkts", "punnet", "punnets", "bag", "bags", "slab",
    "basket", "baskets", "tray", "trays", "bucket", "qt",
})

CONTAINER_WORDS: frozenset[str] = frozenset({
    "tin", "tins", "can", "cans", "jar", "jars", "packet", "packets", "pack",
    "packs", "bottle", "bottles", "bag", "bags", "tub", "tubs", "punnet",
    "punnets", "sachet", "sachets", "carton", "cartons", "box", "boxes",
})

# Units recognised in "250 mL", "7 g", "1.5 cups". A short, unambiguous list:
# "c", "ts", "tb" and "cc" are valid aliases for parsing a leading amount but
# would eat real words here.
_MEASURE_UNITS = (
    "kilograms", "kilogram", "kilos", "kilo", "kg", "grams", "gram", "gms", "gm", "g",
    "milligrams", "milligram", "mg", "millilitres", "millilitre", "milliliters",
    "milliliter", "mls", "ml", "litres", "litre", "liters", "liter", "l",
    "tablespoons", "tablespoon", "tbsp", "teaspoons", "teaspoon", "tsp",
    "cups", "cup", "ounces", "ounce", "oz", "pounds", "pound", "lbs", "lb",
    "inches", "inch", "cm", "mm", "qt",
)
_NUM = r"\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?"
_MEASURE_RE = re.compile(
    rf"(?<![\w./]){_NUM}(?:\s*(?:-|–|—|to)\s*{_NUM})?\s*({'|'.join(_MEASURE_UNITS)})\b\.?",
    re.IGNORECASE,
)
#: A bare number standing alone: a count ("juice 2 lemons"), not "00 flour".
_COUNT_RE = re.compile(r"(?<![\w./-])(?!0\d)(\d+(?:\.\d+)?(?:\s*/\s*\d+)?)(?![\w./%-])")
_BRACKETS = (re.compile(r"\([^()]*\)"), re.compile(r"\[[^\[\]]*\]"))
_UNCLOSED = re.compile(r"[(\[][^)\]]*$")
_NOTE_RE = re.compile(r"\b(?:see\s+)?notes?(?:\s*\d+[a-z]?)?\b\.?", re.IGNORECASE)
#: Where the name ends and the instructions begin.
_TAIL_RE = re.compile(r"\s[–—-]\s|[,;]")
_SPACES = re.compile(r"\s+")
_EDGE = re.compile(r"^[\s.,;:\-–—!?]+|[\s.,;:\-–—!?]+$")


@dataclass(frozen=True)
class Measure:
    """A quantity found inside a name: "250 mL", "7 g"."""

    text: str
    quantity: float
    unit: MeasureUnit | None


@dataclass(frozen=True)
class CleanedName:
    """A name pulled apart. See the module docstring."""

    #: What to show: the name with brackets, instructions and measured
    #: quantities taken out, wording and case as written.
    display: str
    #: The same with bare counts ("juice 2 lemons" -> "juice lemons") removed too.
    display_no_counts: str
    #: Lower-case words to match on: noise and bare numbers dropped.
    key_words: tuple[str, ...]
    #: What was taken out, in reading order, for the line's note.
    notes: tuple[str, ...]
    measures: tuple[Measure, ...] = ()
    #: Bare numbers left in the name.
    counts: tuple[float, ...] = ()
    #: Whether a pack size ("x 7 g tin") was seen.
    pack: bool = False
    #: What survives as the match key, as a string, last word singularised.
    key: str = field(default="", compare=False)
    #: Every word of the name in key order, noise included: a "Pear - Green"
    #: type moved to the front, synonyms applied, bare numbers dropped.
    words: tuple[str, ...] = field(default=(), compare=False)


# --------------------------------------------------------------------------
# Plurals
#
# Three rules live here, for three jobs:
#
# * `_crude_singular` is the original rule, kept verbatim. Pantry slugs and the
#   names of stub rows were minted with it, so `legacy_key` still uses it:
#   anything that matched before still matches.
# * `singular` is the right answer, for naming things: "tomatoes" -> "tomato",
#   not the "tomatoe" the original rule gave (and left in the pantry).
# * `fold_word` is for *comparing*: every spelling of a word, including the
#   mangled ones already stored, maps to one string. Equality only; never shown.
# --------------------------------------------------------------------------

#: Words that end in "s" and are already singular.
_SINGULAR_S = frozenset({
    "asparagus", "hummus", "couscous", "molasses", "series", "species", "swiss",
    "cress", "watercress", "lemongrass", "citrus", "bass", "grass", "brussels",
})
#: Irregular plurals ("ves" and friends) and spellings where "ies" is not "y".
_IRREGULAR = {
    "leaves": "leaf", "loaves": "loaf", "halves": "half", "knives": "knife",
    "shelves": "shelf", "calves": "calf", "wolves": "wolf", "wives": "wife",
    "chillies": "chilli",
}
#: Real singulars that end like a mangled plural, so are never "repaired".
_SINGULAR_IE = frozenset({
    "cookie", "brownie", "smoothie", "veggie", "calorie", "zombie", "movie",
    "selfie", "hoodie", "rookie", "pie", "tie", "lie",
})
_SINGULAR_OE = frozenset({"shoe", "toe", "canoe", "oboe", "aloe", "horseshoe"})
_SINGULAR_CHE = frozenset({
    "quiche", "brioche", "cache", "niche", "moustache", "ganache", "pistache", "mousse",
})
_SINGULAR_ENDINGS = _SINGULAR_IE | _SINGULAR_OE | _SINGULAR_CHE
#: What the original rule turned a plural into, where the right word is not
#: reachable by a suffix rule.
_MANGLED = {
    "leave": "leaf", "halve": "half", "knive": "knife", "shelve": "shelf",
    "calve": "calf", "wolve": "wolf", "wive": "wife", "molasse": "molasses",
    "chillie": "chilli", "chilly": "chilli",
}


def _crude_singular(word: str) -> str:
    """The original rule: drop one trailing "s", leaving "cress", "hummus" and
    "asparagus" alone. Wrong for "tomatoes", "cherries" and "leaves"."""
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def singular(word: str) -> str:
    """The singular of a plural word, for naming: "tomatoes" -> "tomato",
    "cherries" -> "cherry", "leaves" -> "leaf", "peaches" -> "peach". A word
    that is not plural comes back unchanged."""
    if word in _SINGULAR_S or len(word) <= 3 or not word.endswith("s"):
        return word
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if word[:-1] in _SINGULAR_ENDINGS:
        return word[:-1]
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    if word.endswith(("ss", "us", "is")):
        return word
    return word[:-1]


def repair(word: str) -> str:
    """Undo what the original rule did to a singular: "tomatoe" -> "tomato",
    "cherrie" -> "cherry", "peache" -> "peach". Words that really end that way
    ("cookie", "shoe", "quiche") are left alone."""
    if word in _MANGLED:
        return _MANGLED[word]
    if len(word) <= 4 or word in _SINGULAR_ENDINGS:
        return word
    if word.endswith("ie"):
        return word[:-2] + "y"
    if word.endswith("oe"):
        return word[:-1]
    if word.endswith(("che", "she", "xe", "sse")):
        return word[:-1]
    return word


def fold_word(word: str) -> str:
    """One string for every spelling of a word, mangled ones included, for
    comparing: "tomato", "tomatoes" and the "tomatoe" already in the pantry
    all fold to "tomato". Always a real word, so it reads in a debugger."""
    return repair(singular(word.lower()))


def _parse_number(text: str) -> float:
    text = text.replace(",", ".").strip()
    total = 0.0
    for part in text.split():
        if "/" in part:
            num, _, den = part.partition("/")
            total += float(num) / float(den)
        else:
            total += float(part)
    return total


def _unit_for(token: str) -> MeasureUnit | None:
    return UNIT_ALIASES.get(token.lower().rstrip("."))


def _strip_brackets(text: str, notes: list[str]) -> str:
    changed = True
    while changed:
        changed = False
        for pattern in _BRACKETS:
            def grab(match: re.Match) -> str:
                inner = match.group(0)[1:-1].strip()
                if inner:
                    notes.append(inner)
                return " "

            text, n = pattern.subn(grab, text)
            changed = changed or n > 0
    match = _UNCLOSED.search(text)
    if match:
        inner = match.group(0)[1:].strip()
        if inner:
            notes.append(inner)
        text = text[: match.start()]
    return text


def _tidy(text: str) -> str:
    return _EDGE.sub("", _SPACES.sub(" ", text)).strip()


def clean_name(raw: str | None) -> CleanedName:
    """Pull `raw` apart into a name, a match key and the bits that were taken
    out. Pure text; never looks at the pantry."""
    text = unicodedata.normalize("NFKC", normalise_fractions(raw or "")).strip()
    notes: list[str] = []

    text = _strip_brackets(text, notes)
    # "swiss cheese note 1", "see note": a pointer into the recipe, not the name.
    for note in _NOTE_RE.finditer(text):
        notes.append(_tidy(note.group(0)))
    text = _NOTE_RE.sub(" ", text)

    # Instructions after the name: ", finely chopped", "; fresh grated",
    # " – drained and chopped".
    # Except a pantry-style type after a dash, "Pear - Green" or
    # "Cream - Thickened": that is part of what to buy, and keys as "green pear".
    type_words: list[str] = []
    type_text = ""
    split = _TAIL_RE.search(text)
    if split:
        head, tail = text[: split.start()], _tidy(text[split.end():])
        if split.group(0).strip() in "-–—" and _is_type(tail):
            type_text = " ".join(tail.split())
            type_words = type_text.lower().split()
        elif tail:
            notes.append(tail)
        text = head

    # "x 7 g tin anchovies": the "x" belongs to a count that parse_amount has
    # already taken; what follows is a pack size.
    pack = False
    lead = re.match(r"^\s*[x×]\s*(?=\d)", text, re.IGNORECASE)
    if lead:
        text = text[lead.end():]
        pack = True

    measures: list[Measure] = []

    def grab_measure(match: re.Match) -> str:
        unit = _unit_for(match.group(1))
        quantity_text = re.match(rf"\s*({_NUM})", match.group(0))
        try:
            quantity = _parse_number(quantity_text.group(1)) if quantity_text else 0.0
        except (ValueError, ZeroDivisionError):
            quantity = 0.0
        measures.append(Measure(text=_tidy(match.group(0)), quantity=quantity, unit=unit))
        return " "

    text = _MEASURE_RE.sub(grab_measure, text)
    notes.extend(m.text for m in measures)
    # A fused trailing/embedded "250 mL" is not a pack size; only the
    # "x 7 g tin" form (the "x" taken above) is.

    display = _tidy(text)
    words = display.split()
    # Packaging next to a pack size ("tin anchovies") or an "of" ("packet of
    # Marie biscuits") is not the product.
    while len(words) > 1 and (
        words[0].lower() in {"of", "a", "an"}
        or words[0].lower() in AMOUNT_WORDS
        or (
            words[0].lower() in CONTAINER_WORDS
            and (pack or words[1].lower() == "of")
        )
    ):
        dropped = words.pop(0)
        if dropped.lower() in AMOUNT_WORDS and dropped.lower() not in CONTAINER_WORDS:
            notes.append(dropped.lower())
        if dropped.lower() in CONTAINER_WORDS:
            notes.append(dropped.lower())
            # The packaging goes, but a tin is still what makes it tinned.
            if dropped.lower() in {"tin", "tins", "can", "cans"} and "canned" not in type_words:
                type_words.insert(0, "canned")
    display = " ".join(words)

    counts = tuple(_parse_number(m.group(1)) for m in _COUNT_RE.finditer(display))
    display_no_counts = _tidy(_COUNT_RE.sub(" ", display))

    key_source = display.lower().replace("-", " ")
    all_words = [w.strip("().!?:") for w in key_source.split()]
    all_words = _apply_synonyms([*type_words, *(w for w in all_words if w)])
    if type_text:
        display = f"{display} - {type_text}"
    kept = [
        w
        for i, w in enumerate(all_words)
        if w not in MATCH_NOISE
        and not _is_bare_number(w)
        and not (w == "leaf" and i > 0 and all_words[i - 1] == "flat")
    ]
    if not kept:
        kept = all_words
    key = " ".join([*kept[:-1], singular(kept[-1])]) if kept else ""

    return CleanedName(
        display=display,
        display_no_counts=display_no_counts or display,
        key_words=tuple(kept),
        notes=tuple(notes),
        measures=tuple(measures),
        counts=counts,
        pack=pack,
        key=key,
        words=tuple(w for w in all_words if not _is_bare_number(w)),
    )


def _is_type(tail: str) -> bool:
    """Whether the text after a dash names a type ("Green", "Beurre Bosc")
    rather than saying what to do ("finely chopped", "to serve")."""
    words = tail.lower().split()
    if not 1 <= len(words) <= 3 or not all(w.isalpha() for w in words):
        return False
    instructions = MATCH_NOISE | PREP_WORDS | SIZE_WORDS | CONTAINER_WORDS | _INSTRUCTION_WORDS
    # "- sift before measuring": a verb is an instruction ("Wine - Sparkling" is not).
    verb = any(len(w) > 4 and w.endswith("ing") and w != "sparkling" for w in words)
    return not verb and not any(w in instructions or w in UNIT_WORDS for w in words)


def _apply_synonyms(words: list[str]) -> list[str]:
    """Replace each `SYNONYMS` phrase with the name the shop uses."""
    out: list[str] = []
    i = 0
    folded = [fold_word(w) for w in words]
    while i < len(words):
        for phrase, replacement in _SYNONYMS_FOLDED:
            n = len(phrase)
            if tuple(folded[i:i + n]) == phrase:
                # Already said in full ("chinese steamed buns"): leave it.
                lead = replacement[: len(replacement) - n] if replacement[-n:] == phrase else ()
                if lead and tuple(fold_word(w) for w in out[-len(lead):]) == lead:
                    out.extend(words[i:i + n])
                else:
                    out.extend(replacement)
                i += n
                break
        else:
            out.append(words[i])
            i += 1
    return out


def _is_bare_number(word: str) -> bool:
    """A number that is a quantity, not part of a name: "00 flour" and
    "1000 island" keep theirs."""
    return bool(re.fullmatch(r"(?!0\d)\d+(?:\.\d+)?", word))


def normalise_ingredient_name(name: str) -> str:
    """Reduce an ingredient phrase to its matchable core.

    "1 cup fresh flat leaf parsley leaves, chopped" has already had its
    amount stripped by `units.parse_amount`; this drops brackets, instructions,
    measured quantities, preparation words and a trailing plural so it can find
    the master row for "parsley".
    """
    return clean_name(name).key


def legacy_key(name: str) -> str:
    """The match key as it was before the name cleaner existed.

    Pantry slugs were minted from it, so `find_ingredient` still tries it:
    anything that matched before keeps matching. New behaviour only adds
    matches.
    """
    core = name.split(",")[0].lower().replace("-", " ")
    words = [w.strip("().") for w in core.split()]
    kept = [w for w in words if w and w not in _BASE_NOISE]
    if not kept:
        kept = [w for w in words if w]
    if kept:
        kept[-1] = _crude_singular(kept[-1])
    return " ".join(kept)


def match_key(name: str) -> str:
    """`normalise_ingredient_name` folded word by word: equal for every spelling
    of the same ingredient, however the pantry row happens to be spelled.
    For comparing and grouping, never for display."""
    return " ".join(fold_word(w) for w in clean_name(name).key_words)


def stem(word: str) -> str:
    """The form words are compared in when matching sets of words."""
    return fold_word(word)


def stems(words) -> frozenset[str]:
    return frozenset(stem(w) for w in words if w)


def word_stems(text: str) -> frozenset[str]:
    """Stems of the match words of `text`: a pantry name, an alias or a
    prep term, reduced the same way a recipe line is."""
    return stems(clean_name(text).key.split())


def join_notes(*parts: str | None) -> str | None:
    """Combine notes, skipping repeats and blanks, in the order given."""
    seen: list[str] = []
    for part in parts:
        for piece in (part or "").split(";"):
            piece = piece.strip()
            if piece and piece.lower() not in {s.lower() for s in seen}:
                seen.append(piece)
    return "; ".join(seen) or None


@dataclass(frozen=True)
class PantryEntry:
    """One pantry row, pre-digested for matching."""

    ingredient_id: int
    #: The name and each alias as a set of word stems.
    forms: tuple[frozenset[str], ...]
    #: Every word the pantry says is preparation for this ingredient.
    prep: frozenset[str]


def entry_for(ingredient) -> PantryEntry:
    forms = tuple(
        form for form in (word_stems(n) for n in (ingredient.name, *(ingredient.aliases or []))) if form
    )
    prep: set[str] = set()
    for term in ingredient.prep_terms or []:
        prep |= stems(re.split(r"[\s/-]+", term.lower().replace("-", " ")))
    # A prep term is judged the way a line's words are: noise removed.
    return PantryEntry(ingredient.id, forms, frozenset(prep))


def prep_match(line_words, entries: list[PantryEntry]) -> int | None:
    """The pantry row a line belongs to when every word it has beyond the
    row's own name is something the row lists as preparation.

        "boneless skinless chicken thigh fillets"  ->  chicken thigh
        (prep_terms: boneless, skinless, fillet)

    Returns the ingredient id, or None when nothing qualifies or two different
    rows tie. The most specific row wins ("chicken thigh" over "chicken" when
    both would qualify), but only if it is strictly more specific: a tie is a
    guess, and a guess here silently mislinks that line's cost and nutrition.
    """
    wanted = stems(line_words)
    if not wanted:
        return None
    best: int | None = None
    best_size = 0
    tied = False
    for entry in entries:
        if not entry.prep:
            continue
        for form in entry.forms:
            if form <= wanted and (wanted - form) <= entry.prep:
                size = len(form)
                if size > best_size:
                    best, best_size, tied = entry.ingredient_id, size, False
                elif size == best_size and entry.ingredient_id != best:
                    tied = True
    return None if tied else best


def prep_extras(line_words, entry: PantryEntry) -> list[str] | None:
    """The words of a line that are not the pantry row's own name, when the
    row's prep terms account for all of them (what a successful `prep_match`
    explains away as preparation); None when they do not."""
    wanted = [w for w in line_words if w]
    have = stems(wanted)
    best: frozenset[str] | None = None
    for form in entry.forms:
        if form <= have and (have - form) <= entry.prep and (best is None or len(form) > len(best)):
            best = form
    if best is None:
        return None
    return [w for w in wanted if stem(w) not in best]


#: Joining words that carry no information once the preparation is a note.
_CONNECTORS = frozenset({"of", "and", "or", "the", "a", "an", "for", "to", "at", "with", "plus"})


def explain(cleaned: CleanedName, ingredient) -> list[str] | None:
    """What `cleaned` says beyond the pantry row's own name, as words for a
    note, when the row's `prep_terms` account for all of it. None when the
    row has no terms or the line says something the row does not know.

        explain(clean_name("Zest and juice 2 lemons"), lemon[juice, zest]) == ["Zest", "juice"]

    Words are taken from the display text, so noise like "finely" and
    "chopped" is kept for the note instead of vanishing.
    """
    if not ingredient.prep_terms:
        return None
    entry = entry_for(ingredient)
    if prep_extras(cleaned.key_words, entry) is None:
        return None
    have = stems(cleaned.key_words)
    form = max((f for f in entry.forms if f <= have), key=len)
    leftovers: list[str] = []
    for word in cleaned.display.split():
        bare = word.strip("().!?,:;")
        if not bare or _is_bare_number(bare.lower()) or bare.lower() in _CONNECTORS:
            continue
        if stem(bare) not in form:
            leftovers.append(bare)
    return leftovers


def merge_key(name: str | None) -> str:
    """What two shopping lines are compared on when neither is linked to the
    pantry: the name without its brackets, instructions and measured
    quantities, case, punctuation and plurals. Deliberately *not* the match
    key: "frozen peas" and "peas" are different purchases even though the
    pantry may file them both under "peas"."""
    cleaned = clean_name(name)
    text = (cleaned.display or (name or "")).lower().replace("-", " ")
    return " ".join(stem(w) for w in re.sub(r"[^\w\s]", " ", text).split())


def australian(text: str) -> str:
    """`text` with each `SYNONYMS` phrase replaced by the Australian name,
    other words as written: "green bell peppers" -> "green capsicums". For
    renaming; matching uses the folded keys."""
    words = text.split()
    folded = [fold_word(re.sub(r"[^\w]", "", w.lower())) for w in words]
    out: list[str] = []
    i = 0
    while i < len(words):
        for phrase, replacement in _SYNONYMS_FOLDED:
            n = len(phrase)
            if tuple(folded[i:i + n]) != phrase:
                continue
            lead = replacement[: len(replacement) - n] if replacement[-n:] == phrase else ()
            if lead and tuple(fold_word(w.lower()) for w in out[-len(lead):]) == lead:
                out.extend(words[i:i + n])  # already in full
                i += n
                break
            last = words[i + n - 1].lower()
            plural = singular(last) != last
            new = list(replacement)
            if plural:
                new[-1] = new[-1] + ("es" if new[-1].endswith(("sh", "ch", "x", "s")) else "s")
            out.extend(new)
            i += n
            break
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


_SYNONYMS_FOLDED = tuple(
    (tuple(fold_word(w) for w in phrase), replacement) for phrase, replacement in SYNONYMS.items()
)

#: `PRODUCT_WORDS` as `fold_word` spells them, for comparing folded keys.
PRODUCT_FOLDS: frozenset[str] = frozenset(fold_word(w) for w in PRODUCT_WORDS)
