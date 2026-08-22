"""Matching a pantry name to the Australian Food Composition Database.

Fixtures are small and synthetic — hand-built AfcdFood records shaped like
the real dataset's naming convention, not the downloaded xlsx files. That
keeps this test independent of the 3MB government download (gitignored,
not fetched in CI) while still exercising the real scoring logic against
cases the real dataset actually produces — several of these are lifted
directly from failures found while tuning the scorer against the live
1,588-row dataset, and are named for what they used to get wrong.
"""

import pytest

from backend.afcd import AfcdFood, build_foods, find_match, tokenise


def food(name: str, **nutrients) -> AfcdFood:
    defaults = {
        "energy_kj": 100.0, "calories_kcal": 24.0, "protein_g": 1.0,
        "fat_g": 1.0, "saturated_fat_g": 0.1, "carbs_g": 1.0,
        "sugars_g": 1.0, "fibre_g": 1.0, "sodium_mg": 1.0,
    }
    defaults.update(nutrients)
    return AfcdFood(key=name, name=name, tokens=tokenise(name), nutrients=defaults)


class TestTokenise:
    def test_lowercases_and_splits(self):
        assert tokenise("Chicken, Thigh, Raw") == {"chicken", "thigh", "raw"}

    def test_drops_digits_as_noise(self):
        # "(~3.5%)" and similar formatting shouldn't affect matching.
        assert "3" not in tokenise("Milk, regular fat (~3.5%)")
        assert "5" not in tokenise("Milk, regular fat (~3.5%)")

    def test_singularises(self):
        assert tokenise("eggs") == {"egg"}
        assert tokenise("cashews") == {"cashew"}

    def test_does_not_mangle_short_or_already_singular_words(self):
        # The "ss"/"us"/"is" guard: these must survive untouched.
        assert "grass" in tokenise("grass")
        assert "hummus" in tokenise("hummus")
        assert "cress" in tokenise("cress")


class TestFindMatch:
    def test_prefers_the_plain_form_over_a_manufactured_product(self):
        # "banana" -> "Banana chip" was the bug that started this: a short
        # AFCD name scored higher purely for having fewer tokens to dilute
        # word-overlap, even though it names a different, processed food.
        foods = [food("Banana chip"), food("Banana, cavendish, peeled, raw")]
        match, score = find_match("banana", foods)
        assert match.name == "Banana, cavendish, peeled, raw"

    def test_prefers_the_head_category_over_a_food_containing_the_word(self):
        # "milk" must find actual milk, not "Chocolate, milk" (a chocolate
        # product) or "Cake, carrot" for a "carrot" query — AFCD files the
        # true category first and the word can appear anywhere.
        foods = [food("Chocolate, milk"), food("Milk, cow, fluid, regular fat")]
        match, _ = find_match("milk", foods)
        assert match.name == "Milk, cow, fluid, regular fat"

    def test_powder_is_not_a_harmless_qualifier(self):
        # Milk powder is a genuinely different, concentrated product from
        # fluid milk — nutritionally, not just in wording.
        foods = [food("Milk, cow, powder, regular fat"), food("Milk, cow, fluid, regular fat")]
        match, _ = find_match("milk", foods)
        assert match.name == "Milk, cow, fluid, regular fat"

    def test_a_bare_name_prefers_raw_over_a_named_cooking_state(self):
        foods = [food("Chicken, thigh, lean flesh, baked"), food("Chicken, thigh, lean flesh, raw")]
        match, _ = find_match("chicken thigh", foods)
        assert match.name == "Chicken, thigh, lean flesh, raw"

    def test_naming_a_cooking_state_finds_that_state(self):
        foods = [food("Chicken, thigh, lean flesh, baked"), food("Chicken, thigh, lean flesh, raw")]
        match, _ = find_match("baked chicken thigh", foods)
        assert match.name == "Chicken, thigh, lean flesh, baked"

    def test_prefers_regular_fat_over_reduced_when_otherwise_tied(self):
        foods = [food("Milk, cow, fluid, reduced fat"), food("Milk, cow, fluid, regular fat")]
        match, _ = find_match("milk", foods)
        assert match.name == "Milk, cow, fluid, regular fat"

    def test_reduced_fat_wins_when_asked_for(self):
        foods = [food("Milk, cow, fluid, reduced fat"), food("Milk, cow, fluid, regular fat")]
        match, _ = find_match("reduced fat milk", foods)
        assert match.name == "Milk, cow, fluid, reduced fat"

    def test_a_plural_query_finds_the_singular_entry(self):
        foods = [food("Egg, chicken, whole, raw")]
        assert find_match("eggs", foods) is not None

    def test_a_short_partial_overlap_does_not_match(self):
        # "chicken stir fry" against a lamb dish shares only "stir"/"fry"-
        # adjacent words, not the actual protein — must not pass.
        foods = [food("Lamb, stir-fry strips, lean, raw")]
        assert find_match("chicken stir fry", foods) is None

    def test_no_plausible_candidate_returns_none(self):
        foods = [food("Broccoli, fresh, raw"), food("Carrot, mature, peeled, fresh, raw")]
        assert find_match("basmati rice", foods) is None

    def test_a_non_food_item_does_not_coincidentally_match(self):
        foods = [food("Cat food, dry, complete"), food("Beef, mince, regular fat, raw")]
        assert find_match("9v batteries", foods) is None

    def test_ties_prefer_the_shorter_plainer_name(self):
        foods = [
            food("Tomato, common, ripe, fresh, raw, unpeeled"),
            food("Tomato, fresh, raw"),
        ]
        match, _ = find_match("tomato", foods)
        assert match.name == "Tomato, fresh, raw"


class TestBuildFoods:
    def test_joins_on_food_key(self):
        details = {"F001": "Banana, raw", "F002": "Apple, raw"}
        profiles = {"F001": {"calories_kcal": 89.0, "protein_g": 1.1}}
        foods = build_foods(details, profiles)
        assert [f.name for f in foods] == ["Banana, raw"]

    def test_drops_a_food_with_no_usable_nutrients(self):
        details = {"F001": "Mystery item"}
        profiles = {"F001": {"calories_kcal": None, "protein_g": None}}
        assert build_foods(details, profiles) == []

    def test_drops_a_food_missing_from_the_profile_table(self):
        details = {"F001": "Banana, raw", "F002": "Not in profiles"}
        profiles = {"F001": {"calories_kcal": 89.0}}
        assert len(build_foods(details, profiles)) == 1
