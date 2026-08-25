"""scripts/find_duplicate_ingredients.py's three detection tiers. No
network, pure functions over whatever's in the pantry — see the script's
own module docstring for why a plain spelling-similarity score was
rejected in favour of "one's normalised words are a subset of the
other's": it scored unrelated pairs like "salt"/"malt" higher than real
duplicates like "hand soap"/"handwash".
"""

from backend.models import Ingredient, Recipe, RecipeIngredient, ShoppingItem
from scripts.find_duplicate_ingredients import (
    find_exact_groups,
    find_prep_size_groups,
    find_qualified_variants,
    merge_exact_groups,
    strip_prep_and_size,
    usage_counts,
)


def make(session, name, *, aliases=None, slug=None):
    ingredient = Ingredient(
        slug=slug or name.lower().replace(" ", "-"), name=name, aliases=aliases or []
    )
    session.add(ingredient)
    session.commit()
    session.refresh(ingredient)
    return ingredient


class TestExactGroups:
    def test_groups_names_that_normalise_the_same(self, session):
        egg = make(session, "Egg")
        eggs = make(session, "Eggs")
        large_eggs = make(session, "Large Eggs")  # "large" is noise, "eggs" singularises
        groups = find_exact_groups([egg, eggs, large_eggs])
        assert len(groups) == 1
        assert {m.id for m in groups[0]} == {egg.id, eggs.id, large_eggs.id}

    def test_an_alias_can_also_form_a_group(self, session):
        a = make(session, "Coriander")
        b = make(session, "Cilantro", aliases=["coriander"])
        groups = find_exact_groups([a, b])
        assert len(groups) == 1
        assert {m.id for m in groups[0]} == {a.id, b.id}

    def test_unrelated_names_are_not_grouped(self, session):
        a = make(session, "Salt")
        b = make(session, "Malt")
        assert find_exact_groups([a, b]) == []

    def test_a_singleton_is_not_a_group(self, session):
        a = make(session, "Vanilla")
        assert find_exact_groups([a]) == []


class TestStripPrepAndSize:
    def test_strips_a_preparation_method(self):
        assert strip_prep_and_size("Shredded Chicken") == "chicken"

    def test_strips_a_multi_word_preparation_phrase(self):
        # Word-level stripping handles this without any phrase-matching:
        # both "cut" and "diagonally" are noise words on their own.
        assert strip_prep_and_size("Carrots Cut Diagonally") == "carrot"

    def test_strips_a_sizing_phrase_with_a_leading_number(self):
        assert strip_prep_and_size("1 Inch Cubed Chicken Breast") == "chicken breast"

    def test_strips_a_qualitative_size_word(self):
        assert strip_prep_and_size("1 Big Onion") == "onion"

    def test_strips_a_generous_pinch(self):
        assert strip_prep_and_size("Generous Pinch Salt") == "salt"

    def test_strips_a_spaced_out_weight(self):
        assert strip_prep_and_size("2.5 oz Chocolate") == "chocolate"

    def test_strips_a_weight_fused_to_its_number(self):
        assert strip_prep_and_size("500g Flour") == "flour"

    def test_strips_a_fused_kg(self):
        assert strip_prep_and_size("1kg Sugar") == "sugar"

    def test_leaves_a_plain_name_alone(self):
        assert strip_prep_and_size("Onion") == "onion"

    def test_falls_back_to_the_plain_normalised_form_if_nothing_is_left(self):
        # No food word at all, just size/prep words ("cube" is one of
        # them too) — stripping everything would leave nothing to group
        # on, so this returns the plain normalised form (itself already
        # singularised to "cube") rather than an empty string a dozen
        # other over-stripped names could collide on.
        assert strip_prep_and_size("1 Inch Cubes") == "1 inch cube"


class TestPrepSizeGroups:
    def test_a_plain_name_matches_its_diced_variant(self, session):
        onion = make(session, "Onion")
        diced = make(session, "1 Inch Diced Onion")
        groups = find_prep_size_groups([onion, diced], exclude_ids=set())
        assert len(groups) == 1
        assert {m.id for m in groups[0]} == {onion.id, diced.id}

    def test_unrelated_names_are_not_grouped(self, session):
        salt = make(session, "Salt")
        malt = make(session, "Malt")
        assert find_prep_size_groups([salt, malt], exclude_ids=set()) == []

    def test_exact_group_members_are_excluded_from_this_tier(self, session):
        egg = make(session, "Egg")
        eggs = make(session, "Eggs")
        groups = find_prep_size_groups([egg, eggs], exclude_ids={egg.id, eggs.id})
        assert groups == []

    def test_a_singleton_is_not_a_group(self, session):
        a = make(session, "Shredded Carrot")
        assert find_prep_size_groups([a], exclude_ids=set()) == []


class TestQualifiedVariants:
    def test_a_variety_qualifier_is_flagged(self, session):
        onion = make(session, "Onion")
        red_onion = make(session, "Red Onion")
        pairs = find_qualified_variants([onion, red_onion], exclude_ids=set())
        assert {p.id for p in pairs[0]} == {onion.id, red_onion.id}

    def test_coincidental_spelling_overlap_is_not_flagged(self, session):
        # The exact case a plain similarity score gets wrong: "salt" and
        # "malt" share three of four letters but are not the same food,
        # and neither's normalised words are a subset of the other's.
        salt = make(session, "Salt")
        malt = make(session, "Malt")
        assert find_qualified_variants([salt, malt], exclude_ids=set()) == []

    def test_a_shared_second_word_alone_is_not_enough(self, session):
        # "lima beans" and "lime" share no words at all — a token-subset
        # check (unlike character similarity) never even considers this
        # a near miss.
        lime = make(session, "Lime")
        lima_beans = make(session, "Lima Beans")
        assert find_qualified_variants([lime, lima_beans], exclude_ids=set()) == []

    def test_exact_group_members_are_excluded_from_this_tier(self, session):
        # A pair already reported as an exact match shouldn't also show
        # up here — that would just be the same suggestion twice.
        egg = make(session, "Egg")
        eggs = make(session, "Eggs")
        pairs = find_qualified_variants([egg, eggs], exclude_ids={egg.id, eggs.id})
        assert pairs == []

    def test_identical_normalised_forms_are_not_a_variant_pair(self, session):
        # Two names that normalise identically are an exact match, not a
        # "subset of itself" variant — this only matters when the caller
        # doesn't pre-exclude them (defence in depth for find_exact_groups
        # not having run first).
        a = make(session, "Egg")
        b = make(session, "EGG", slug="egg-2")
        assert find_qualified_variants([a, b], exclude_ids=set()) == []


class TestUsageCounts:
    def test_counts_only_linked_recipe_ingredients(self, session):
        flour = make(session, "Flour")
        recipe = Recipe(slug="bread", title="Bread")
        session.add(recipe)
        session.flush()
        session.add(
            RecipeIngredient(
                recipe_id=recipe.id, position=0, name="flour", raw_text="2 cups flour",
                ingredient_id=flour.id,
            )
        )
        session.add(
            RecipeIngredient(
                recipe_id=recipe.id, position=1, name="salt", raw_text="a pinch salt",
                ingredient_id=None,
            )
        )
        session.commit()
        counts = usage_counts(session)
        assert counts == {flour.id: 1}


class TestMergeExactGroups:
    def test_keeps_the_most_used_member_and_absorbs_the_rest(self, session):
        # "Egg" is linked to a recipe, "Eggs" isn't — the busier row should
        # survive even though it wasn't first in the group.
        eggs = make(session, "Eggs")
        egg = make(session, "Egg")
        recipe = Recipe(slug="omelette", title="Omelette")
        session.add(recipe)
        session.flush()
        session.add(
            RecipeIngredient(
                recipe_id=recipe.id, position=0, name="egg", raw_text="2 eggs",
                ingredient_id=egg.id,
            )
        )
        session.commit()

        usage = usage_counts(session)
        merged = merge_exact_groups(session, [[eggs, egg]], usage)

        assert merged == 1
        assert session.get(Ingredient, eggs.id) is None
        kept = session.get(Ingredient, egg.id)
        assert kept is not None
        assert "eggs" in kept.aliases

    def test_repoints_recipe_lines_and_shopping_items_off_the_absorbed_row(self, session):
        egg = make(session, "Egg")
        eggs = make(session, "Eggs")
        recipe = Recipe(slug="omelette", title="Omelette")
        session.add(recipe)
        session.flush()
        # Two lines linked to "Egg" so it out-uses "Eggs" and is the one
        # merge_exact_groups keeps — the line and item under test, linked
        # to "Eggs", are the ones that should end up repointed.
        session.add(
            RecipeIngredient(
                recipe_id=recipe.id, position=0, name="egg", raw_text="1 egg",
                ingredient_id=egg.id,
            )
        )
        session.add(
            RecipeIngredient(
                recipe_id=recipe.id, position=1, name="egg", raw_text="1 more egg",
                ingredient_id=egg.id,
            )
        )
        line = RecipeIngredient(
            recipe_id=recipe.id, position=2, name="eggs", raw_text="3 eggs",
            ingredient_id=eggs.id,
        )
        item = ShoppingItem(name="Eggs", ingredient_id=eggs.id)
        session.add(line)
        session.add(item)
        session.commit()

        merge_exact_groups(session, [[egg, eggs]], usage_counts(session))

        session.refresh(line)
        session.refresh(item)
        assert line.ingredient_id == egg.id
        assert item.ingredient_id == egg.id

    def test_merges_every_group_independently_and_totals_the_count(self, session):
        egg = make(session, "Egg")
        eggs = make(session, "Eggs")
        onion = make(session, "Onion")
        onions = make(session, "Onions")

        merged = merge_exact_groups(session, [[egg, eggs], [onion, onions]], usage_counts(session))

        assert merged == 2
        assert session.get(Ingredient, eggs.id) is None
        assert session.get(Ingredient, onions.id) is None
        assert session.get(Ingredient, egg.id) is not None
        assert session.get(Ingredient, onion.id) is not None

    def test_a_three_way_group_leaves_exactly_one_survivor(self, session):
        a = make(session, "Egg")
        b = make(session, "Eggs")
        c = make(session, "Large Eggs")

        merged = merge_exact_groups(session, [[a, b, c]], usage_counts(session))

        assert merged == 2
        survivors = [i for i in (a, b, c) if session.get(Ingredient, i.id) is not None]
        assert len(survivors) == 1
