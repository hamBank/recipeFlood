"""Amount parsing and volume/count -> weight conversion.

Every recipe ingredient wants a weight in grams, because weight is the only
form that costs and nutrition can be computed from. Recipes rarely give
one. This module bridges that gap and — just as importantly — records *how*
it bridged it, so the UI can distinguish "the recipe said 250g" from "we
guessed a cup of flour is 150g".

## The Australian measures problem

The source blog is Australian, and Australian spoons are not everyone
else's spoons:

    unit    AU      US/int'l
    cup     250ml   240ml
    tbsp     20ml    15ml     <- 33% larger; the one that actually bites
    tsp       5ml     5ml

A 20ml tablespoon is four teaspoons, not three. Getting this wrong
overstates every tablespoon of butter, oil and golden syrup in the whole
collection by a third, so the convention is explicit per recipe
(`Recipe.units_system`) rather than global-and-forgotten.

## Conversion precedence

1. The amount is already a mass (g/kg/oz/lb)      -> `explicit`
2. Volume x the linked master ingredient's density -> `converted`
3. Count x the linked ingredient's grams_per_piece -> `converted`
4. Volume x a density from DENSITIES below         -> `estimated`
5. Count x a weight from PIECE_WEIGHTS below       -> `estimated`
6. Nothing matched                                 -> `unknown`, no weight

Steps 4 and 5 are keyword lookups against the ingredient name and are
deliberately marked `estimated`: they are good enough for a shopping list
and a rough cost, and not good enough to present as fact.
"""

from __future__ import annotations

import re
import unicodedata

from .models import MeasureUnit, WeightSource

# --------------------------------------------------------------------------
# Unit definitions
# --------------------------------------------------------------------------

#: Millilitres per volume unit, per convention.
VOLUME_ML: dict[str, dict[MeasureUnit, float]] = {
    "au": {
        MeasureUnit.ml: 1.0,
        MeasureUnit.l: 1000.0,
        MeasureUnit.cup: 250.0,
        MeasureUnit.tbsp: 20.0,
        MeasureUnit.dsp: 10.0,
        MeasureUnit.tsp: 5.0,
        MeasureUnit.fl_oz: 30.0,
    },
    "us": {
        MeasureUnit.ml: 1.0,
        MeasureUnit.l: 1000.0,
        MeasureUnit.cup: 240.0,
        MeasureUnit.tbsp: 15.0,
        MeasureUnit.dsp: 10.0,
        MeasureUnit.tsp: 5.0,
        MeasureUnit.fl_oz: 29.5735,
    },
}

#: Grams per mass unit.
MASS_G: dict[MeasureUnit, float] = {
    MeasureUnit.mg: 0.001,
    MeasureUnit.g: 1.0,
    MeasureUnit.kg: 1000.0,
    MeasureUnit.oz: 28.3495,
    MeasureUnit.lb: 453.592,
}

#: Units that mean "one of these things" rather than a measured amount.
COUNT_UNITS = {
    MeasureUnit.piece,
    MeasureUnit.slice,
    MeasureUnit.clove,
    MeasureUnit.bunch,
    MeasureUnit.sprig,
    MeasureUnit.can,
}

#: Written forms accepted on input, mapped to the canonical unit. Order
#: doesn't matter — lookup is exact against a normalised token.
UNIT_ALIASES: dict[str, MeasureUnit] = {
    "g": MeasureUnit.g, "gram": MeasureUnit.g, "grams": MeasureUnit.g,
    "gm": MeasureUnit.g, "gms": MeasureUnit.g, "gr": MeasureUnit.g,
    "kg": MeasureUnit.kg, "kilo": MeasureUnit.kg, "kilos": MeasureUnit.kg,
    "kilogram": MeasureUnit.kg, "kilograms": MeasureUnit.kg,
    "mg": MeasureUnit.mg, "milligram": MeasureUnit.mg,
    "ml": MeasureUnit.ml, "mls": MeasureUnit.ml, "millilitre": MeasureUnit.ml,
    "millilitres": MeasureUnit.ml, "milliliter": MeasureUnit.ml,
    "milliliters": MeasureUnit.ml, "cc": MeasureUnit.ml,
    "l": MeasureUnit.l, "lt": MeasureUnit.l, "litre": MeasureUnit.l,
    "litres": MeasureUnit.l, "liter": MeasureUnit.l, "liters": MeasureUnit.l,
    "cup": MeasureUnit.cup, "cups": MeasureUnit.cup, "c": MeasureUnit.cup,
    "tbsp": MeasureUnit.tbsp, "tbs": MeasureUnit.tbsp, "tb": MeasureUnit.tbsp,
    "tblsp": MeasureUnit.tbsp,  # appears verbatim in the source blog
    "tblspn": MeasureUnit.tbsp, "tbspn": MeasureUnit.tbsp,
    "tablespoon": MeasureUnit.tbsp, "tablespoons": MeasureUnit.tbsp,
    "dsp": MeasureUnit.dsp, "dessertspoon": MeasureUnit.dsp,
    "dessertspoons": MeasureUnit.dsp, "dstspn": MeasureUnit.dsp,
    "tsp": MeasureUnit.tsp, "tspn": MeasureUnit.tsp, "ts": MeasureUnit.tsp,
    "teaspoon": MeasureUnit.tsp, "teaspoons": MeasureUnit.tsp,
    "floz": MeasureUnit.fl_oz, "fl_oz": MeasureUnit.fl_oz,
    "oz": MeasureUnit.oz, "ounce": MeasureUnit.oz, "ounces": MeasureUnit.oz,
    "lb": MeasureUnit.lb, "lbs": MeasureUnit.lb, "pound": MeasureUnit.lb,
    "pounds": MeasureUnit.lb,
    "clove": MeasureUnit.clove, "cloves": MeasureUnit.clove,
    "slice": MeasureUnit.slice, "slices": MeasureUnit.slice,
    "bunch": MeasureUnit.bunch, "bunches": MeasureUnit.bunch,
    "sprig": MeasureUnit.sprig, "sprigs": MeasureUnit.sprig,
    "can": MeasureUnit.can, "cans": MeasureUnit.can, "tin": MeasureUnit.can,
    "tins": MeasureUnit.can, "jar": MeasureUnit.can, "packet": MeasureUnit.can,
    "pinch": MeasureUnit.pinch, "pinches": MeasureUnit.pinch,
}

#: Densities in g/ml, keyed by a substring of the ingredient name. Derived
#: from Australian cup weights (1 cup = 250ml), e.g. a cup of plain flour is
#: 150g -> 0.60. Longest key wins, so "brown sugar" beats "sugar".
DENSITIES: dict[str, float] = {
    # liquids
    "water": 1.00, "milk": 1.03, "buttermilk": 1.03, "stock": 1.00,
    "broth": 1.00, "juice": 1.04, "wine": 0.99, "vinegar": 1.01,
    "cream": 1.00, "sour cream": 1.00, "yoghurt": 1.03, "yogurt": 1.03,
    "coconut milk": 1.00, "coconut cream": 1.00, "oil": 0.92,
    "olive oil": 0.92, "honey": 1.42, "golden syrup": 1.42, "treacle": 1.42,
    "molasses": 1.40, "maple syrup": 1.32, "soy sauce": 1.15,
    "tomato paste": 1.10, "passata": 1.05, "tahini": 1.07,
    "peanut butter": 1.08, "mayonnaise": 0.94, "condensed milk": 1.28,
    # flours & dry baking
    "plain flour": 0.60, "self raising flour": 0.60,
    "self-raising flour": 0.60, "wholemeal flour": 0.60, "bakers flour": 0.60,
    "flour": 0.60, "cornflour": 0.48, "cornstarch": 0.48, "semolina": 0.68,
    "polenta": 0.68, "cocoa": 0.40, "cacao": 0.40, "almond meal": 0.44,
    "ground almonds": 0.44, "hazelnut meal": 0.44, "coconut flour": 0.45,
    "baking powder": 0.90, "bicarbonate of soda": 0.90, "baking soda": 0.90,
    # sugars
    "caster sugar": 0.88, "castor sugar": 0.88, "white sugar": 0.88,
    "raw sugar": 0.88, "brown sugar": 0.80, "icing sugar": 0.48,
    "sugar": 0.88,
    # grains, pulses, seeds
    "rice": 0.80, "arborio": 0.80, "quinoa": 0.68, "freekeh": 0.72,
    "burghul": 0.72, "bulgur": 0.72, "couscous": 0.72, "farro": 0.76,
    "pearl barley": 0.80, "lentil": 0.80, "split pea": 0.80,
    "rolled oats": 0.36, "oats": 0.36, "muesli": 0.44, "breadcrumbs": 0.40,
    "fresh breadcrumbs": 0.24, "chia": 0.68, "linseed": 0.60,
    "flaxseed": 0.60, "sesame seeds": 0.60, "poppy seeds": 0.60,
    "pine nuts": 0.56, "desiccated coconut": 0.34,
    "shredded coconut": 0.28, "nuts": 0.48, "almonds": 0.56,
    "walnuts": 0.48, "pecans": 0.44, "hazelnuts": 0.56,
    "macadamias": 0.56, "pistachios": 0.50, "peanuts": 0.58,
    # dairy & fats
    "butter": 0.91, "margarine": 0.91, "ricotta": 1.00, "cream cheese": 1.00,
    "grated cheese": 0.40, "parmesan": 0.36, "cheese": 0.40,
    # sweets & misc
    "chocolate chips": 0.68, "choc chips": 0.68, "chocolate": 0.68,
    "sultanas": 0.64, "raisins": 0.64, "currants": 0.64, "dates": 0.64,
    "dried fruit": 0.64, "glace cherries": 0.72, "salt": 1.20,
    "herbs": 0.10, "parsley": 0.10, "mint": 0.10, "coriander": 0.10,
    "basil": 0.10, "rocket": 0.10, "spinach": 0.12, "baby spinach": 0.12,
}

#: Grams for one of a countable thing, keyed by ingredient-name substring.
#: Same longest-key-wins rule as DENSITIES.
PIECE_WEIGHTS: dict[str, float] = {
    "egg": 50.0, "egg white": 33.0, "egg yolk": 18.0,
    "garlic": 4.0, "garlic clove": 4.0, "shallot": 30.0,
    "onion": 150.0, "red onion": 130.0, "brown onion": 150.0,
    "spring onion": 15.0, "leek": 250.0,
    "potato": 170.0, "sweet potato": 300.0, "carrot": 90.0,
    "tomato": 120.0, "cherry tomato": 15.0, "capsicum": 160.0,
    "zucchini": 200.0, "eggplant": 400.0, "cauliflower": 900.0,
    "broccoli": 350.0, "cabbage": 900.0, "celery": 40.0,
    "cucumber": 300.0, "avocado": 200.0, "corn": 250.0,
    "mushroom": 20.0, "beetroot": 150.0, "parsnip": 130.0,
    "pumpkin": 1200.0, "fennel": 250.0, "celeriac": 700.0,
    "apple": 150.0, "banana": 118.0, "pear": 180.0, "orange": 180.0,
    "lemon": 100.0, "lime": 65.0, "mango": 300.0, "peach": 150.0,
    "plum": 66.0, "rhubarb": 60.0,
    "bacon": 30.0, "rasher": 30.0, "sausage": 60.0,
    "chicken breast": 200.0, "chicken thigh": 100.0,
    "bread": 35.0, "tortilla": 45.0, "sheet": 170.0,
    "bunch": 30.0, "sprig": 2.0, "can": 400.0, "tin": 400.0,
}

#: Unicode vulgar fractions the blog uses inline (½ cup, ¼ tsp).
_VULGAR = {
    "¼": 0.25, "½": 0.5, "¾": 0.75,
    "⅓": 1 / 3, "⅔": 2 / 3,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}

_NUM = r"\d+(?:\.\d+)?(?:\s*/\s*\d+)?"
_AMOUNT_RE = re.compile(
    rf"^\s*(?P<qty>{_NUM}(?:\s+\d+\s*/\s*\d+)?)"
    rf"(?:\s*(?:-|–|—|to)\s*(?P<qty2>{_NUM}))?"
    r"\s*(?P<unit>[a-zA-Z_]+\.?)?\s*(?P<rest>.*)$",
    re.DOTALL,
)


def normalise_fractions(text: str) -> str:
    """Rewrite ½ as 1/2 and NBSP as space so the numeric regex can see them."""
    out = []
    for ch in text:
        if ch in _VULGAR:
            num = _VULGAR[ch]
            out.append(f" {num.as_integer_ratio()[0]}/{num.as_integer_ratio()[1]} ")
        else:
            out.append(ch)
    return unicodedata.normalize("NFKC", "".join(out)).replace("\xa0", " ")


def parse_quantity(text: str) -> float | None:
    """Parse "2", "1.5", "1/2" or "1 1/2" into a float. None if unparseable."""
    text = text.strip()
    if not text:
        return None
    total = 0.0
    for part in text.split():
        if "/" in part:
            num, _, den = part.partition("/")
            try:
                den_f = float(den)
                if den_f == 0:
                    return None
                total += float(num) / den_f
            except ValueError:
                return None
        else:
            try:
                total += float(part)
            except ValueError:
                return None
    return total


def parse_unit(token: str | None) -> MeasureUnit | None:
    """Map a written unit token to a MeasureUnit, or None if it isn't one."""
    if not token:
        return None
    return UNIT_ALIASES.get(token.strip().rstrip(".").lower())


def parse_amount(line: str) -> tuple[float | None, float | None, MeasureUnit | None, str]:
    """Split an ingredient line into (quantity, quantity_max, unit, remainder).

    "1 1/2 cups plain flour, sifted" -> (1.5, None, cup, "plain flour, sifted")
    "2-3 tbsp olive oil"             -> (2.0, 3.0, tbsp, "olive oil")
    "salt and pepper"                -> (None, None, None, "salt and pepper")

    A leading number with no recognised unit is treated as a count, and the
    word stays in the remainder: "4 tomatoes, diced" -> (4.0, None, piece,
    "tomatoes, diced").
    """
    text = normalise_fractions(line).strip()
    match = _AMOUNT_RE.match(text)
    if not match:
        return None, None, None, text

    qty = parse_quantity(match.group("qty") or "")
    if qty is None:
        return None, None, None, text
    qty_max = parse_quantity(match.group("qty2") or "") if match.group("qty2") else None

    unit_token = match.group("unit")
    unit = parse_unit(unit_token)
    rest = match.group("rest").strip()
    if unit is None and unit_token:
        # The token wasn't a unit — it's the start of the name ("4 tomatoes").
        # Don't insert a space before punctuation the regex left in `rest`,
        # or "4 tomatoes, diced" comes back as "tomatoes , diced".
        separator = "" if rest[:1] in ",.;:)" else " "
        rest = f"{unit_token}{separator}{rest}".strip()
        unit = MeasureUnit.piece
    elif unit is None:
        unit = MeasureUnit.piece
    return qty, qty_max, unit, rest


def _longest_match(name: str, table: dict[str, float]) -> float | None:
    """Longest keyword in `table` contained in `name`, so "brown sugar"
    wins over "sugar" and "egg white" over "egg"."""
    lowered = f" {name.lower()} "
    best_key: str | None = None
    for key in table:
        if key in lowered or lowered.strip().startswith(key):
            if best_key is None or len(key) > len(best_key):
                best_key = key
    return table[best_key] if best_key else None


def lookup_density(name: str) -> float | None:
    """Estimated g/ml for an ingredient name, from the keyword table."""
    return _longest_match(name, DENSITIES)


def lookup_piece_weight(name: str) -> float | None:
    """Estimated grams for one of an ingredient, from the keyword table."""
    return _longest_match(name, PIECE_WEIGHTS)


def to_grams(
    quantity: float | None,
    unit: MeasureUnit | None,
    name: str = "",
    *,
    density_g_per_ml: float | None = None,
    grams_per_piece: float | None = None,
    system: str = "au",
) -> tuple[float | None, WeightSource]:
    """Convert an amount to grams. Returns (grams, how-we-got-there).

    `density_g_per_ml` and `grams_per_piece` come from the linked master
    ingredient when there is one; passing them is what upgrades the result
    from `estimated` to `converted`. See the precedence list in the module
    docstring.
    """
    if quantity is None or unit is None:
        return None, WeightSource.unknown
    if unit in (MeasureUnit.pinch, MeasureUnit.to_taste):
        return None, WeightSource.unknown

    if unit in MASS_G:
        return round(quantity * MASS_G[unit], 3), WeightSource.explicit

    volumes = VOLUME_ML.get(system, VOLUME_ML["au"])
    if unit in volumes:
        millilitres = quantity * volumes[unit]
        if density_g_per_ml:
            return round(millilitres * density_g_per_ml, 3), WeightSource.converted
        estimated = lookup_density(name)
        if estimated:
            return round(millilitres * estimated, 3), WeightSource.estimated
        # No density anywhere: for water-like things 1ml ~ 1g is defensible,
        # but guessing that for an unknown solid is not. Leave it unset.
        return None, WeightSource.unknown

    if unit in COUNT_UNITS:
        if grams_per_piece:
            return round(quantity * grams_per_piece, 3), WeightSource.converted
        estimated = lookup_piece_weight(name)
        if estimated:
            return round(quantity * estimated, 3), WeightSource.estimated
        return None, WeightSource.unknown

    return None, WeightSource.unknown


def format_amount(
    quantity: float | None,
    quantity_max: float | None,
    unit: MeasureUnit | None,
) -> str:
    """Render an amount back to human text for `raw_text` reconstruction."""
    if quantity is None:
        return ""
    def num(value: float) -> str:
        return f"{value:g}"
    amount = num(quantity)
    if quantity_max:
        amount += f"-{num(quantity_max)}"
    if unit is None or unit == MeasureUnit.piece:
        return amount
    if unit == MeasureUnit.to_taste:
        return "to taste"
    return f"{amount} {unit.value}"
