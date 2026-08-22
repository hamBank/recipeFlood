"""scripts/enrich_pantry.py's write logic: what gets asked for, and what
actually lands on a row. No database session needed — these operate on
plain (unpersisted) Ingredient instances, the same objects the script's
main loop would have loaded."""

import pytest

from backend.afcd import AfcdFood
from backend.models import Ingredient
from scripts.enrich_pantry import apply_afcd_match, apply_result, needs_enrichment

FULL_RESULT = {
    "is_human_food": True,
    "confidence": "high",
    "note": None,
    "nutrition": {
        "energy_kj": 418, "calories_kcal": 100, "protein_g": 5, "fat_g": 1,
        "saturated_fat_g": 0.2, "carbs_g": 20, "sugars_g": 2, "fibre_g": 1,
        "sodium_mg": 10,
    },
    "cost_per_kg_cents": 300,
    "package_size_grams": 500,
}

NOT_FOOD_RESULT = {
    "is_human_food": False,
    "confidence": "high",
    "note": "pet food",
    "nutrition": {},
    "cost_per_kg_cents": None,
    "package_size_grams": None,
}


class TestNeedsEnrichment:
    def test_a_bare_ingredient_needs_everything(self):
        assert needs_enrichment(Ingredient(slug="x", name="x"), "all") is True

    def test_a_complete_ingredient_needs_nothing(self):
        full = Ingredient(
            slug="x", name="x", cost_per_kg_cents=200, package_size_grams=500,
            calories_kcal=1, protein_g=1, fat_g=1, carbs_g=1, sodium_mg=1,
        )
        assert needs_enrichment(full, "all") is False

    def test_non_food_never_needs_anything(self):
        assert needs_enrichment(Ingredient(slug="x", name="x", is_food=False), "all") is False

    def test_only_narrows_what_counts(self):
        priced_no_nutrition = Ingredient(
            slug="x", name="x", cost_per_kg_cents=200, package_size_grams=500
        )
        assert needs_enrichment(priced_no_nutrition, "nutrition") is True
        assert needs_enrichment(priced_no_nutrition, "price") is False

    def test_package_size_only_counted_under_all(self):
        no_package = Ingredient(
            slug="x", name="x", cost_per_kg_cents=200,
            calories_kcal=1, protein_g=1, fat_g=1, carbs_g=1, sodium_mg=1,
        )
        assert needs_enrichment(no_package, "all") is True
        assert needs_enrichment(no_package, "nutrition") is False
        assert needs_enrichment(no_package, "price") is False


class TestApplyResult:
    def test_fills_every_blank_field(self):
        ingredient = Ingredient(slug="x", name="x")
        changed = apply_result(ingredient, FULL_RESULT, only="all")
        assert ingredient.calories_kcal == 100
        assert ingredient.cost_per_kg_cents == 300
        assert ingredient.package_size_grams == 500
        assert ingredient.nutrition_source == "AI estimate (Claude)"
        assert set(changed) >= {"calories_kcal", "cost_per_kg_cents", "package_size_grams"}

    def test_never_overwrites_an_existing_price(self):
        ingredient = Ingredient(slug="x", name="x", cost_per_kg_cents=999, cost_source="manual")
        apply_result(ingredient, FULL_RESULT, only="all")
        assert ingredient.cost_per_kg_cents == 999
        assert ingredient.cost_source == "manual"

    def test_never_overwrites_existing_nutrition(self):
        ingredient = Ingredient(slug="x", name="x", calories_kcal=1, nutrition_source="packet")
        apply_result(ingredient, FULL_RESULT, only="all")
        assert ingredient.calories_kcal == 1
        assert ingredient.nutrition_source == "packet"

    def test_a_null_field_in_the_result_is_not_written_or_counted(self):
        result = {**FULL_RESULT, "nutrition": {**FULL_RESULT["nutrition"], "saturated_fat_g": None}}
        ingredient = Ingredient(slug="x", name="x")
        changed = apply_result(ingredient, result, only="all")
        assert ingredient.saturated_fat_g is None
        assert "saturated_fat_g" not in changed

    def test_reclassifies_a_non_food_item_and_writes_nothing_else(self):
        ingredient = Ingredient(slug="x", name="cat mince")
        changed = apply_result(ingredient, NOT_FOOD_RESULT, only="all")
        assert ingredient.is_food is False
        assert changed == ["is_food"]
        assert ingredient.calories_kcal is None
        assert ingredient.cost_per_kg_cents is None

    def test_only_nutrition_never_touches_price(self):
        ingredient = Ingredient(slug="x", name="x")
        apply_result(ingredient, FULL_RESULT, only="nutrition")
        assert ingredient.calories_kcal == 100
        assert ingredient.cost_per_kg_cents is None

    def test_only_price_never_touches_nutrition(self):
        ingredient = Ingredient(slug="x", name="x")
        apply_result(ingredient, FULL_RESULT, only="price")
        assert ingredient.cost_per_kg_cents == 300
        assert ingredient.calories_kcal is None

    def test_already_food_true_is_not_reclassified_a_second_time(self):
        # is_food is already True by default; applying a food result must
        # not report it as a change.
        ingredient = Ingredient(slug="x", name="x")
        changed = apply_result(ingredient, FULL_RESULT, only="all")
        assert "is_food" not in changed


class TestApplyAfcdMatch:
    def food(self, **nutrients):
        defaults = {f: None for f in (
            "energy_kj", "calories_kcal", "protein_g", "fat_g", "saturated_fat_g",
            "carbs_g", "sugars_g", "fibre_g", "sodium_mg",
        )}
        defaults.update(nutrients)
        return AfcdFood(key="F1", name="Chicken, breast, lean flesh, raw", tokens=frozenset(), nutrients=defaults)

    def test_fills_blanks_and_labels_the_matched_food_by_name(self):
        ingredient = Ingredient(slug="x", name="chicken breast")
        changed = apply_afcd_match(ingredient, self.food(calories_kcal=98, protein_g=22), 0.9)
        assert ingredient.calories_kcal == 98
        assert ingredient.protein_g == 22
        assert ingredient.nutrition_source == "AFCD (Chicken, breast, lean flesh, raw)"
        assert set(changed) == {"calories_kcal", "protein_g"}

    def test_never_overwrites_existing_nutrition(self):
        ingredient = Ingredient(slug="x", name="x", calories_kcal=1, nutrition_source="packet")
        changed = apply_afcd_match(ingredient, self.food(calories_kcal=98), 0.9)
        assert ingredient.calories_kcal == 1
        assert ingredient.nutrition_source == "packet"
        assert changed == []

    def test_a_match_with_no_usable_nutrients_changes_nothing(self):
        ingredient = Ingredient(slug="x", name="x")
        changed = apply_afcd_match(ingredient, self.food(), 0.9)  # all None
        assert changed == []
        assert ingredient.nutrition_source is None
