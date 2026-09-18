"""Nutrition and cost are both summed from the master ingredient list, and
both report how much of the recipe they could actually account for."""

import pytest
from sqlmodel import Session

from backend.costing import (
    amount_cost_cents,
    compute_cost,
    cost_per_gram,
    cost_per_ml,
    cost_per_unit,
    package_cost_cents,
)
from backend.models import Ingredient, MeasureKind, MeasureUnit, RecipeIngredient, WeightSource
from backend.nutrition import compute_nutrition, has_nutrition


def line(name, grams, ingredient_id=None, optional=False):
    return RecipeIngredient(
        id=abs(hash((name, grams))) % 100000,
        recipe_id=1,
        name=name,
        raw_text=name,
        weight_grams=grams,
        weight_source=WeightSource.explicit,
        unit=MeasureUnit.g,
        ingredient_id=ingredient_id,
        optional=optional,
    )


def volume_line(name, ml, ingredient_id=None):
    return RecipeIngredient(
        id=abs(hash((name, ml, "ml"))) % 100000,
        recipe_id=1,
        name=name,
        raw_text=name,
        volume_ml=ml,
        weight_source=WeightSource.unknown,
        unit=MeasureUnit.ml,
        ingredient_id=ingredient_id,
    )


def quantity_line(name, count, ingredient_id=None):
    return RecipeIngredient(
        id=abs(hash((name, count, "each"))) % 100000,
        recipe_id=1,
        name=name,
        raw_text=name,
        quantity=count,
        weight_source=WeightSource.unknown,
        unit=MeasureUnit.piece,
        ingredient_id=ingredient_id,
    )


@pytest.fixture
def egg(session: Session):
    """A piece-priced ingredient: 50c each, a dozen to a carton — the case
    this feature exists for (sold per item, not by weight or volume)."""
    ingredient = Ingredient(
        slug="egg",
        name="egg",
        measure_kind=MeasureKind.piece,
        package_size_units=12,
        cost_per_unit_cents=50,
    )
    session.add(ingredient)
    session.commit()
    session.refresh(ingredient)
    return ingredient


@pytest.fixture
def milk(session: Session):
    """A volume-priced ingredient: $2/L, sold and shelf-priced by the
    litre, with no density set — the case this whole feature exists for."""
    ingredient = Ingredient(
        slug="milk",
        name="milk",
        measure_kind=MeasureKind.volume,
        package_size_ml=2000,
        cost_per_litre_cents=200,
    )
    session.add(ingredient)
    session.commit()
    session.refresh(ingredient)
    return ingredient


class TestCost:
    def test_cost_per_gram_has_useful_resolution(self, flour):
        # $2.50/kg is a quarter of a cent per gram — a two-decimal dollars
        # figure would round it to 0.00.
        assert cost_per_gram(flour) == pytest.approx(0.0025)

    def test_package_cost(self, flour):
        assert package_cost_cents(flour) == 250  # 1kg at $2.50/kg

    def test_unpriced_ingredient_has_no_cost(self, session: Session):
        plain = Ingredient(slug="mystery", name="mystery")
        session.add(plain)
        session.commit()
        assert cost_per_gram(plain) is None
        assert package_cost_cents(plain) is None

    def test_total_and_known_fraction(self, session: Session, flour):
        lines = [line("plain flour", 300, flour.id), line("gruyere", 100)]
        cost, per_line = compute_cost(session, lines, servings=4)
        assert cost.total_cents == 75  # 300g at $2.50/kg
        assert cost.per_serving_cents == 19
        assert cost.priced_count == 1
        assert cost.ingredient_count == 2
        assert cost.known_fraction == pytest.approx(0.5)
        assert per_line[lines[0].id] == 75

    def test_optional_ingredients_are_excluded(self, session: Session, flour):
        lines = [line("plain flour", 300, flour.id, optional=True)]
        cost, _ = compute_cost(session, lines)
        assert cost.total_cents == 0
        assert cost.ingredient_count == 0

    def test_no_servings_means_no_per_serving_figure(self, session: Session, flour):
        cost, _ = compute_cost(session, [line("plain flour", 300, flour.id)])
        assert cost.per_serving_cents is None


class TestVolumeCost:
    """Ingredients that are sold and shelf-priced by volume — most
    liquids — need no density to be costed. See costing.py's module
    docstring and Ingredient.measure_kind."""

    def test_cost_per_ml_has_useful_resolution(self, milk):
        # $2/L is a fifth of a cent per ml — display-only, matches
        # cost_per_gram's reasoning for weight ingredients.
        assert cost_per_ml(milk) == pytest.approx(0.002)

    def test_package_cost(self, milk):
        assert package_cost_cents(milk) == 400  # 2L at $2/L

    def test_a_weight_ingredients_volume_fields_are_ignored(self, flour):
        # flour has no cost_per_litre_cents/package_size_ml at all — this
        # just confirms measure_kind=weight (flour's default) never looks
        # at them, rather than crashing on missing fields.
        assert cost_per_ml(flour) is None

    def test_line_cost_uses_volume_not_weight(self, milk):
        priced = amount_cost_cents(milk, weight_grams=1000, volume_ml=500)
        assert priced == 100  # 500ml at $2/L, not 1000g at any weight price
        assert amount_cost_cents(milk, weight_grams=1000, volume_ml=None) is None

    def test_a_volume_ingredient_with_no_price_is_unpriced(self, session: Session):
        unpriced = Ingredient(slug="stock", name="stock", measure_kind=MeasureKind.volume)
        session.add(unpriced)
        session.commit()
        assert cost_per_ml(unpriced) is None
        assert amount_cost_cents(unpriced, volume_ml=500) is None

    def test_total_prices_a_volume_line_alongside_a_weight_line(
        self, session: Session, flour, milk
    ):
        lines = [
            line("plain flour", 300, flour.id),  # 75c
            volume_line("milk", 500, milk.id),  # 100c
        ]
        cost, per_line = compute_cost(session, lines, servings=2)
        assert cost.total_cents == 175
        assert cost.known_fraction == 1.0
        assert per_line[lines[1].id] == 100

    def test_a_volume_line_with_no_ingredient_is_unpriced(self, session: Session):
        cost, _ = compute_cost(session, [volume_line("mystery liquid", 500)])
        assert cost.total_cents == 0
        assert cost.known_fraction == 0.0


class TestPieceCost:
    """Ingredients sold and priced per item rather than by weight or
    volume — eggs, a can of something. See costing.py's module docstring
    and Ingredient.measure_kind."""

    def test_cost_per_unit(self, egg):
        assert cost_per_unit(egg) == pytest.approx(0.50)

    def test_package_cost(self, egg):
        assert package_cost_cents(egg) == 600  # a dozen at 50c each

    def test_a_weight_ingredients_unit_fields_are_ignored(self, flour):
        assert cost_per_unit(flour) is None

    def test_line_cost_uses_quantity_not_weight(self, egg):
        priced = amount_cost_cents(egg, weight_grams=1000, quantity=3)
        assert priced == 150  # 3 eggs at 50c, not 1000g at any weight price
        assert amount_cost_cents(egg, weight_grams=1000, quantity=None) is None

    def test_a_piece_ingredient_with_no_price_is_unpriced(self, session: Session):
        unpriced = Ingredient(slug="lime", name="lime", measure_kind=MeasureKind.piece)
        session.add(unpriced)
        session.commit()
        assert cost_per_unit(unpriced) is None
        assert amount_cost_cents(unpriced, quantity=3) is None

    def test_total_prices_a_piece_line_alongside_a_weight_line(
        self, session: Session, flour, egg
    ):
        lines = [
            line("plain flour", 300, flour.id),  # 75c
            quantity_line("egg", 3, egg.id),  # 150c
        ]
        cost, per_line = compute_cost(session, lines, servings=2)
        assert cost.total_cents == 225
        assert cost.known_fraction == 1.0
        assert per_line[lines[1].id] == 150

    def test_a_piece_line_with_no_ingredient_is_unpriced(self, session: Session):
        cost, _ = compute_cost(session, [quantity_line("mystery item", 3)])
        assert cost.total_cents == 0
        assert cost.known_fraction == 0.0


class TestPieceCountPricedByWeight:
    """A weight-priced ingredient (the default, and the common case) with
    a `grams_per_piece` still needs to price a line that only has a piece
    count and no weight at all — a shopping-list line typed or edited by
    hand never goes through the recipe-ingredient weight converter, so it
    only ever has `quantity`. See costing.py's module docstring."""

    @pytest.fixture
    def onion(self, session: Session):
        ingredient = Ingredient(
            slug="brown-onion",
            name="brown onion",
            grams_per_piece=150,
            cost_per_kg_cents=400,  # $4/kg
        )
        session.add(ingredient)
        session.commit()
        session.refresh(ingredient)
        return ingredient

    def test_a_bare_quantity_is_priced_via_grams_per_piece(self, onion):
        # 2 onions at 150g each = 300g, at $4/kg = $1.20
        assert amount_cost_cents(onion, quantity=2) == 120

    def test_a_real_weight_still_wins_over_the_quantity_fallback(self, onion):
        # Whatever actually converted the line's weight (density, an
        # explicit gram amount) is more trustworthy than re-deriving one
        # from a possibly-stale quantity — same principle as volume/weight
        # already not being mixed.
        assert amount_cost_cents(onion, weight_grams=1000, quantity=2) == 400

    def test_no_grams_per_piece_means_still_unpriced(self, session: Session):
        no_conversion = Ingredient(
            slug="parsley", name="parsley", cost_per_kg_cents=1000
        )
        session.add(no_conversion)
        session.commit()
        assert amount_cost_cents(no_conversion, quantity=2) is None

    def test_no_kg_price_means_still_unpriced(self, session: Session):
        unpriced = Ingredient(slug="chive", name="chive", grams_per_piece=5)
        session.add(unpriced)
        session.commit()
        assert amount_cost_cents(unpriced, quantity=10) is None

    def test_a_piece_ingredient_never_falls_back_to_a_weight_guess(
        self, session: Session
    ):
        """measure_kind=piece is a deliberate flag that this ingredient is
        NOT to be priced by weight — grams_per_piece left over from before
        it was reclassified must not quietly resurrect a weight price."""
        reclassified = Ingredient(
            slug="egg-again",
            name="egg again",
            measure_kind=MeasureKind.piece,
            grams_per_piece=50,
            cost_per_kg_cents=6000,  # stale, from before reclassifying
        )
        session.add(reclassified)
        session.commit()
        assert amount_cost_cents(reclassified, quantity=3) is None

    def test_total_prices_a_bare_quantity_line_via_the_pantry(
        self, session: Session, onion
    ):
        cost, per_line = compute_cost(session, [quantity_line("onion", 2, onion.id)])
        assert cost.total_cents == 120
        assert cost.known_fraction == 1.0


def bare_line(name, ingredient_id=None):
    """A recipe line with no stated amount at all — "olive oil", no
    quantity, no unit — the case TestNoAmountAtAll exists for."""
    return RecipeIngredient(
        id=abs(hash((name, "bare"))) % 100000,
        recipe_id=1,
        name=name,
        raw_text=name,
        weight_source=WeightSource.unknown,
        ingredient_id=ingredient_id,
    )


class TestNoAmountAtAll:
    """Not even a piece count — a recipe line that states no amount at
    all still gets a price when the pantry can support a reasonable
    default guess, rather than being left out of the total just because
    nobody said how much. See costing.py's module docstring."""

    def test_a_piece_priced_ingredient_assumes_one(self, egg):
        assert amount_cost_cents(egg) == 50  # 1 egg at 50c

    def test_a_volume_priced_ingredient_assumes_one_package(self, milk):
        assert amount_cost_cents(milk) == 400  # 2L package at $2/L

    def test_a_volume_priced_ingredient_with_no_package_size_stays_unpriced(
        self, session: Session
    ):
        no_package = Ingredient(
            slug="stock", name="stock", measure_kind=MeasureKind.volume,
            cost_per_litre_cents=300,
        )
        session.add(no_package)
        session.commit()
        assert amount_cost_cents(no_package) is None

    def test_a_weight_priced_countable_ingredient_assumes_its_own_default_weight(
        self, session: Session
    ):
        onion = Ingredient(
            slug="brown-onion", name="brown onion",
            grams_per_piece=150, cost_per_kg_cents=400,  # $4/kg
        )
        session.add(onion)
        session.commit()
        assert amount_cost_cents(onion) == 60  # 150g at $4/kg

    def test_falls_back_to_one_package_when_there_is_no_default_item_weight(
        self, flour
    ):
        # flour has no grams_per_piece (it isn't naturally countable) but
        # does have a package size — 1kg at $2.50/kg — so that's the guess.
        assert amount_cost_cents(flour) == 250

    def test_a_weight_priced_ingredient_with_neither_stays_unpriced(
        self, session: Session
    ):
        nothing_to_go_on = Ingredient(slug="salt", name="salt", cost_per_kg_cents=500)
        session.add(nothing_to_go_on)
        session.commit()
        assert amount_cost_cents(nothing_to_go_on) is None

    def test_a_piece_priced_ingredient_with_no_price_stays_unpriced_not_guessed_by_weight(
        self, session: Session
    ):
        reclassified = Ingredient(
            slug="lime", name="lime", measure_kind=MeasureKind.piece,
            grams_per_piece=100, cost_per_kg_cents=4000,
        )
        session.add(reclassified)
        session.commit()
        assert amount_cost_cents(reclassified) is None

    def test_total_prices_a_recipe_line_with_no_stated_amount_at_all(
        self, session: Session, egg
    ):
        cost, per_line = compute_cost(session, [bare_line("egg", egg.id)])
        assert cost.total_cents == 50
        assert cost.known_fraction == 1.0


class TestNutrition:
    def test_has_nutrition(self, session: Session, flour):
        assert has_nutrition(flour)
        assert not has_nutrition(Ingredient(slug="x", name="x"))

    def test_sums_per_100g_figures(self, session: Session, flour):
        whole, per_serving = compute_nutrition(
            session, [line("plain flour", 300, flour.id)], servings=2
        )
        assert whole.protein_g == pytest.approx(30.0)  # 10g/100g x 300g
        assert whole.energy_kj == pytest.approx(4440.0)
        assert per_serving.protein_g == pytest.approx(15.0)
        assert per_serving.per_serving is True

    def test_coverage_reports_what_it_could_not_account_for(self, session: Session, flour):
        whole, _ = compute_nutrition(
            session, [line("plain flour", 300, flour.id), line("gruyere", 100)]
        )
        assert whole.total_grams == 400
        assert whole.covered_grams == 300
        assert whole.coverage == pytest.approx(0.75)

    def test_a_field_nobody_supplied_stays_none(self, session: Session, flour):
        # flour has no sugars_g — reporting 0.0 would be a claim we can't make.
        whole, _ = compute_nutrition(session, [line("plain flour", 300, flour.id)])
        assert whole.sugars_g is None

    def test_weightless_lines_contribute_nothing(self, session: Session, flour):
        whole, _ = compute_nutrition(session, [line("plain flour", None, flour.id)])
        assert whole.total_grams == 0
        assert whole.coverage == 0.0

    def test_no_servings_means_no_per_serving_panel(self, session: Session, flour):
        _, per_serving = compute_nutrition(session, [line("plain flour", 300, flour.id)])
        assert per_serving is None
