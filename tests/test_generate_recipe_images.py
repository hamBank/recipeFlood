"""scripts/generate_recipe_images.py's selection logic: which recipes
count as candidates, and what order they come back in. No network — see
backend/image_generation.py's own tests for the pure prompt-building
half, and the module docstring for why generate_image itself isn't
covered here.
"""

from datetime import date

from backend.models import PreparedEvent, Recipe, RecipeStep
from scripts.generate_recipe_images import select_recipes_needing_images


def make_recipe(session, title, *, image_path=None, empty=False):
    """A recipe with at least one method step, so it isn't itself excluded
    by the "empty recipe" filter — unless the test asks for `empty=True`,
    to exercise that filter directly."""
    recipe = Recipe(slug=title.lower().replace(" ", "-"), title=title, image_path=image_path)
    session.add(recipe)
    session.commit()
    session.refresh(recipe)
    if not empty:
        session.add(RecipeStep(recipe_id=recipe.id, position=0, text="Cook it."))
        session.commit()
    return recipe


def cook(session, recipe, *dates):
    for day in dates:
        session.add(PreparedEvent(recipe_id=recipe.id, prepared_on=day))
    session.commit()


class TestSelectRecipesNeedingImages:
    def test_a_recipe_with_a_photo_is_not_a_candidate(self, session):
        make_recipe(session, "Has A Photo", image_path="recipes/has-a-photo.jpg")
        assert select_recipes_needing_images(session) == []

    def test_a_recipe_with_no_photo_is_a_candidate(self, session):
        recipe = make_recipe(session, "No Photo")
        assert select_recipes_needing_images(session) == [recipe]

    def test_most_cooked_comes_first(self, session):
        rarely = make_recipe(session, "Rarely Made")
        often = make_recipe(session, "Often Made")
        cook(session, rarely, date(2026, 1, 1))
        cook(session, often, date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1))

        assert select_recipes_needing_images(session) == [often, rarely]

    def test_a_never_cooked_recipe_is_still_included(self, session):
        # No PreparedEvent row at all — the outer join must not drop it.
        never_cooked = make_recipe(session, "Never Cooked")
        made_once = make_recipe(session, "Made Once")
        cook(session, made_once, date(2026, 1, 1))

        assert select_recipes_needing_images(session) == [made_once, never_cooked]

    def test_limit_caps_the_result(self, session):
        for i in range(3):
            make_recipe(session, f"Recipe {i}")
        assert len(select_recipes_needing_images(session, limit=2)) == 2

    def test_an_empty_recipe_is_not_a_candidate(self, session):
        # A bare book-citation stub from the history import — nothing to
        # depict, so no point spending on a placeholder photo for it.
        make_recipe(session, "Just A Citation", empty=True)
        assert select_recipes_needing_images(session) == []
