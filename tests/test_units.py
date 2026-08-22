"""Amount parsing and weight conversion — the Australian-measures rules."""

import pytest

from backend.models import MeasureUnit, WeightSource
from backend.units import (
    format_amount,
    lookup_density,
    parse_amount,
    parse_quantity,
    to_grams,
)


class TestParseQuantity:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("2", 2.0),
            ("1.5", 1.5),
            ("1/2", 0.5),
            ("1 1/2", 1.5),
            ("3/4", 0.75),
            ("", None),
            ("abc", None),
            ("1/0", None),  # a zero denominator must not raise
        ],
    )
    def test_parses(self, text, expected):
        assert parse_quantity(text) == expected


class TestParseAmount:
    def test_quantity_unit_and_name(self):
        assert parse_amount("1 1/2 cups plain flour, sifted") == (
            1.5,
            None,
            MeasureUnit.cup,
            "plain flour, sifted",
        )

    def test_range(self):
        quantity, quantity_max, unit, rest = parse_amount("2-3 tbsp olive oil")
        assert (quantity, quantity_max, unit, rest) == (2.0, 3.0, MeasureUnit.tbsp, "olive oil")

    def test_blog_spelling_of_tablespoon(self):
        # The source blog writes "tblsp" — it has to resolve, or every
        # tablespoon in the collection loses its weight.
        _, _, unit, _ = parse_amount("1.5 tblsp cold water")
        assert unit == MeasureUnit.tbsp

    def test_bare_count_keeps_the_noun(self):
        assert parse_amount("4 tomatoes, diced") == (
            4.0,
            None,
            MeasureUnit.piece,
            "tomatoes, diced",
        )

    def test_unicode_fraction(self):
        quantity, _, unit, rest = parse_amount("½ cup tahini")
        assert (quantity, unit, rest) == (0.5, MeasureUnit.cup, "tahini")

    def test_no_amount(self):
        assert parse_amount("salt and pepper") == (None, None, None, "salt and pepper")


class TestToGrams:
    def test_mass_passes_through_as_explicit(self):
        assert to_grams(1.5, MeasureUnit.kg, "cauliflower") == (1500.0, WeightSource.explicit)

    def test_australian_tablespoon_is_20ml(self):
        # The whole reason units_system exists. At AU 20ml with butter at
        # 0.91 g/ml a tablespoon is 18.2g; the US 15ml spoon would give 13.65g.
        grams, source = to_grams(1, MeasureUnit.tbsp, "butter", density_g_per_ml=0.91)
        assert grams == pytest.approx(18.2)
        assert source == WeightSource.converted

        us_grams, _ = to_grams(1, MeasureUnit.tbsp, "butter", density_g_per_ml=0.91, system="us")
        assert us_grams == pytest.approx(13.65)

    def test_australian_cup_is_250ml(self):
        grams, _ = to_grams(1, MeasureUnit.cup, "plain flour", density_g_per_ml=0.6)
        assert grams == pytest.approx(150.0)

    def test_linked_density_beats_the_keyword_table(self):
        _, source = to_grams(1, MeasureUnit.cup, "plain flour", density_g_per_ml=0.6)
        assert source == WeightSource.converted

    def test_keyword_density_is_only_an_estimate(self):
        grams, source = to_grams(1, MeasureUnit.cup, "caster sugar")
        assert grams == pytest.approx(220.0)
        assert source == WeightSource.estimated

    def test_count_uses_grams_per_piece(self):
        grams, source = to_grams(3, MeasureUnit.piece, "egg", grams_per_piece=50)
        assert (grams, source) == (150.0, WeightSource.converted)

    def test_count_falls_back_to_the_keyword_table(self):
        grams, source = to_grams(2, MeasureUnit.piece, "brown onion")
        assert (grams, source) == (300.0, WeightSource.estimated)

    def test_unknown_solid_in_cups_is_not_guessed_as_water(self):
        # Assuming 1ml = 1g for an unrecognised solid would quietly invent
        # a weight. Better to report that we don't know.
        assert to_grams(1, MeasureUnit.cup, "gruyere shavings") == (None, WeightSource.unknown)

    def test_unquantifiable_units(self):
        assert to_grams(1, MeasureUnit.pinch, "salt") == (None, WeightSource.unknown)
        assert to_grams(None, MeasureUnit.g, "salt") == (None, WeightSource.unknown)


class TestDensityTable:
    def test_longest_keyword_wins(self):
        assert lookup_density("brown sugar") == 0.80
        assert lookup_density("caster sugar") == 0.88
        assert lookup_density("icing sugar") == 0.48

    def test_self_raising_flour_is_not_generic_flour_by_accident(self):
        assert lookup_density("self-raising flour") == 0.60


def test_format_amount_round_trips_for_display():
    assert format_amount(1.5, None, MeasureUnit.cup) == "1.5 cup"
    assert format_amount(2, 3, MeasureUnit.tbsp) == "2-3 tbsp"
    assert format_amount(4, None, MeasureUnit.piece) == "4"
    assert format_amount(None, None, MeasureUnit.g) == ""
