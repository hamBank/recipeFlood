"""Rationalising a shopping-list export.

Most of these assertions are here because the rule's absence produced a
specific wrong result on the real 2,303-row file. Where that is so, the bad
output is named in the test.
"""

import pytest

from backend.models import IngredientSource
from backend.pantry_import import (
    clean_item,
    correct_spelling,
    is_food,
    map_source,
    pack_metrics,
    parse_number,
    resolve_source,
)


class TestCleanItem:
    def test_trims_and_lowercases(self):
        assert clean_item("  Aged Cheddar  ") == "aged cheddar"

    def test_collapses_inner_whitespace(self):
        assert clean_item("almond   milk ") == "almond milk"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1/4 red cabbage", "red cabbage"),
            ("400g sausage mince", "sausage mince"),
            ("1 titanium-strength gelatine leaf", "titanium-strength gelatine leaf"),
        ],
    )
    def test_strips_a_leading_amount(self, raw, expected):
        assert clean_item(raw) == expected

    @pytest.mark.parametrize("raw", ["00 flour", "3 bean mix", "7 spice"])
    def test_keeps_a_number_that_is_part_of_the_name(self, raw):
        # "00" is a flour grade and "3 bean mix" is what the product is
        # called. Stripping any leading digit would mangle both.
        assert clean_item(raw) == raw.lower()


class TestParseNumber:
    def test_numbers(self):
        assert parse_number("0.3") == 0.3
        assert parse_number(" 12 ") == 12.0

    def test_blank_is_none(self):
        assert parse_number("") is None
        assert parse_number(None) is None

    def test_a_shop_name_in_the_price_column_is_none(self):
        # Twenty rows of the export are shifted, repeating the shop in the
        # Price column: "breakfast mushrooms,,Markets,Markets".
        assert parse_number("Markets") is None


class TestMapSource:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("SM", IngredientSource.supermarket),
            ("costco", IngredientSource.supermarket),
            ("Costo", IngredientSource.supermarket),   # a typo in the export
            ("Markets", IngredientSource.markets),
            ("markets", IngredientSource.markets),
            ("Nuts", IngredientSource.nut_shop),
            ("Fish", IngredientSource.fishmonger),
            ("Bakery", IngredientSource.bakery),
            ("Alcholo", IngredientSource.bottle_shop),  # also a typo
            ("Bunnings", IngredientSource.hardware),
            ("Indian", IngredientSource.asian_grocery),
        ],
    )
    def test_maps_the_shop_spellings(self, raw, expected):
        assert map_source(raw) == expected

    def test_unknown_and_blank_fall_back_to_other(self):
        assert map_source("Somewhere New") is IngredientSource.other
        assert map_source("") is IngredientSource.other
        assert map_source(None) is IngredientSource.other


class TestResolveSource:
    def test_most_frequent_wins(self):
        assert resolve_source(
            [IngredientSource.supermarket, IngredientSource.markets, IngredientSource.markets]
        ) is IngredientSource.markets

    def test_other_never_beats_a_real_shop(self):
        # `other` is the fallback, not an observation, so two rows of it
        # should not outvote one row that actually named a shop.
        assert resolve_source(
            [IngredientSource.other, IngredientSource.other, IngredientSource.deli]
        ) is IngredientSource.deli

    def test_other_wins_when_it_is_all_there_is(self):
        assert resolve_source([IngredientSource.other]) is IngredientSource.other

    def test_ties_are_deterministic(self):
        pair = [IngredientSource.deli, IngredientSource.butcher]
        assert resolve_source(pair) == resolve_source(list(reversed(pair)))


class TestIsFood:
    @pytest.mark.parametrize(
        "name", ["9V batteries", "cat litter", "toilet paper", "Astrid shampoo"]
    )
    def test_household_items_are_not_food(self, name):
        assert not is_food(name, IngredientSource.supermarket)

    def test_a_non_food_shop_condemns_whatever_it_sold(self):
        assert not is_food("hooks", IngredientSource.hardware)
        assert not is_food("parachoc", IngredientSource.chemist)

    @pytest.mark.parametrize(
        "name", ["plain flour", "cauliflower", "green prawns", "bocconcini"]
    )
    def test_food_is_food(self, name):
        assert is_food(name, IngredientSource.markets)

    @pytest.mark.parametrize("name", ["fennel bulb", "garlic bulbs", "globe artichoke"])
    def test_bulb_and_globe_are_vegetables_not_lighting(self, name):
        # A "bulb"/"globe" keyword condemned all three on the first pass.
        assert is_food(name, IngredientSource.markets)

    def test_light_bulb_is_still_caught_as_a_phrase(self):
        assert not is_food("light bulb", IngredientSource.supermarket)

    @pytest.mark.parametrize("name", ["candle nuts", "choc sponge"])
    def test_the_exceptions_survive_their_keywords(self, name):
        # "candle" and "sponge" both look like cleaning products.
        assert is_food(name, IngredientSource.asian_grocery)


class TestPackMetrics:
    def test_derives_cost_per_kg(self):
        # 0.8kg for $12 -> $15/kg -> 1500 cents
        assert pack_metrics(0.8, 12.0) == (800.0, 1500)

    def test_the_bulk_edit_placeholders_are_ignored(self):
        # 251 of 323 weights are exactly 0.3 and 232 of 341 prices exactly
        # 3. Treating those as measurements would put invented numbers in
        # the cost panel.
        assert pack_metrics(0.3, 3.0) == (None, None)

    def test_a_deliberate_price_against_a_placeholder_weight_gives_no_cost(self):
        grams, cents = pack_metrics(0.3, 4.0)
        assert grams is None and cents is None

    def test_weight_without_price(self):
        assert pack_metrics(0.5, None) == (500.0, None)

    def test_price_without_weight_is_not_guessed_at(self):
        assert pack_metrics(None, 4.0) == (None, None)

    def test_nothing(self):
        assert pack_metrics(None, None) == (None, None)


class TestCorrectSpelling:
    VOCAB = {"avocado", "mushroom", "capsicum", "pine nuts", "raisins", "pear", "sage"}

    def test_corrects_toward_a_known_spelling(self):
        result = correct_spelling(["avacado", "avocado"], self.VOCAB)
        assert result["avacado"] == "avocado"

    def test_leaves_a_known_spelling_alone(self):
        assert "avocado" not in correct_spelling(["avacado", "avocado"], self.VOCAB)

    @pytest.mark.parametrize("short", ["peas", "sake", "foil", "milo", "mints"])
    def test_short_words_are_never_corrected(self, short):
        # peas->pear, sake->sage, foil->oil, milo->milk and mints->mint were
        # all produced before the minimum-length rule existed.
        assert short not in correct_spelling([short], self.VOCAB | {"pear", "sage", "oil", "milk", "mint"})

    def test_never_merge_pairs_are_left_alone(self):
        # Both are real and distinct: craisins are dried cranberries.
        assert "craisins" not in correct_spelling(["craisins"], self.VOCAB)

    def test_plurals_are_left_to_the_grouping_key(self):
        # normalise_ingredient_name singularises, so these merge downstream
        # without a guess here.
        assert "avocados" not in correct_spelling(["avocados"], self.VOCAB)

    def test_ambiguity_produces_no_correction(self):
        # One edit from both "pear" and "peas" — we cannot tell, so nothing.
        assert "peat" not in correct_spelling(["peat"], {"pear", "peas"})

    def test_known_misspellings_win_over_frequency(self):
        # The shopping list uses "vegimite" and "mozarella" repeatedly. An
        # earlier version treated repetition as evidence and corrected the
        # *right* spellings onto the wrong ones.
        result = correct_spelling(["vegimite", "vegemite", "mozarella", "mozzarella"], set())
        assert result["vegimite"] == "vegemite"
        assert result["mozarella"] == "mozzarella"
        assert "vegemite" not in result
        assert "mozzarella" not in result

    def test_no_cycles_when_the_pantry_holds_the_misspelling(self):
        # The blog pantry contains "haloumi" and "mozarella". Without the
        # override guard the distance rule mapped the corrected spellings
        # straight back onto them: halloumi -> haloumi -> halloumi.
        result = correct_spelling(
            ["haloumi", "halloumi", "mozarella", "mozzarella"],
            {"haloumi", "mozarella"},
        )
        assert result.get("haloumi") == "halloumi"
        assert "halloumi" not in result
        for wrong, right in result.items():
            assert result.get(right) != wrong, f"cycle: {wrong} <-> {right}"

    def test_extra_overrides_are_honoured(self):
        result = correct_spelling(["froozen peas"], set(), extra={"froozen peas": "frozen peas"})
        assert result["froozen peas"] == "frozen peas"
