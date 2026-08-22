"""Nutrition and cost are both summed from the master ingredient list, and
both report how much of the recipe they could actually account for."""

import pytest
from sqlmodel import Session

from backend.costing import compute_cost, cost_per_gram, package_cost_cents
from backend.models import Ingredient, MeasureUnit, RecipeIngredient, WeightSource
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
