"""scripts/find_duplicate_ingredients.py's two detection tiers. No
network, pure functions over whatever's in the pantry — see the script's
own module docstring for why a plain spelling-similarity score was
rejected in favour of "one's normalised words are a subset of the
other's": it scored unrelated pairs like "salt"/"malt" higher than real
duplicates like "hand soap"/"handwash".
"""

from backend.models import Ingredient, RecipeIngredient
from scripts.find_duplicate_ingredients import (
    find_exact_groups,
    find_qualified_variants,
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
        from backend.models import Recipe

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
