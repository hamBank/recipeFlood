"""scripts/backfill_cook_list_prepared_events.py — syncing prepared
events for cooking-list memberships that predate the auto-logging in
backend/routers/cook_lists.py."""

from datetime import date

from sqlmodel import select

from backend.models import CookList, CookListRecipe, PreparedEvent, Recipe
from scripts.backfill_cook_list_prepared_events import backfill


def make_recipe(session, title="Soup"):
    recipe = Recipe(slug=title.lower(), title=title)
    session.add(recipe)
    session.commit()
    session.refresh(recipe)
    return recipe


def make_cook_list(session, recipe, cook_date=date(2026, 8, 24), created_by=None):
    cook_list = CookList(cook_date=cook_date, created_by=created_by)
    session.add(cook_list)
    session.flush()
    session.add(CookListRecipe(cook_list_id=cook_list.id, recipe_id=recipe.id))
    session.commit()
    session.refresh(cook_list)
    return cook_list


class TestBackfill:
    def test_a_membership_with_no_linked_event_gets_one(self, session):
        recipe = make_recipe(session)
        cook_list = make_cook_list(session, recipe)

        lists_scanned, touched = backfill(session)
        session.commit()

        assert (lists_scanned, touched) == (1, 1)
        events = session.exec(select(PreparedEvent)).all()
        assert len(events) == 1
        assert events[0].recipe_id == recipe.id
        assert events[0].prepared_on == cook_list.cook_date
        assert events[0].cook_list_id == cook_list.id

    def test_the_event_is_attributed_to_whoever_created_the_list(self, session):
        recipe = make_recipe(session)
        make_cook_list(session, recipe, created_by=42)

        backfill(session)
        session.commit()

        assert session.exec(select(PreparedEvent)).first().user_id == 42

    def test_rerunning_does_not_duplicate_events(self, session):
        recipe = make_recipe(session)
        make_cook_list(session, recipe)

        backfill(session)
        session.commit()
        backfill(session)
        session.commit()

        assert len(session.exec(select(PreparedEvent)).all()) == 1

    def test_an_already_linked_event_is_left_alone_bar_its_date(self, session):
        recipe = make_recipe(session)
        cook_list = make_cook_list(session, recipe)
        session.add(
            PreparedEvent(
                recipe_id=recipe.id,
                prepared_on=cook_list.cook_date,
                cook_list_id=cook_list.id,
                rating=5,
                note="so good",
            )
        )
        session.commit()

        backfill(session)
        session.commit()

        events = session.exec(select(PreparedEvent)).all()
        assert len(events) == 1
        assert events[0].rating == 5
        assert events[0].note == "so good"

    def test_a_hand_logged_event_is_not_touched_or_deduplicated_against(self, session):
        """A manual PreparedEvent (cook_list_id is null) is a different
        thing from the auto-logged one — the backfill adds its own rather
        than claiming the hand-logged entry as already covering the list."""
        recipe = make_recipe(session)
        cook_list = make_cook_list(session, recipe)
        session.add(PreparedEvent(recipe_id=recipe.id, prepared_on=cook_list.cook_date))
        session.commit()

        backfill(session)
        session.commit()

        events = session.exec(select(PreparedEvent)).all()
        assert len(events) == 2
        assert sum(1 for e in events if e.cook_list_id is None) == 1
        assert sum(1 for e in events if e.cook_list_id == cook_list.id) == 1

    def test_multiple_lists_and_recipes_are_all_scanned(self, session):
        soup = make_recipe(session, "Soup")
        stew = make_recipe(session, "Stew")
        make_cook_list(session, soup, cook_date=date(2026, 1, 1))
        second = CookList(cook_date=date(2026, 2, 1))
        session.add(second)
        session.flush()
        session.add(CookListRecipe(cook_list_id=second.id, recipe_id=soup.id))
        session.add(CookListRecipe(cook_list_id=second.id, recipe_id=stew.id))
        session.commit()

        lists_scanned, touched = backfill(session)

        assert (lists_scanned, touched) == (2, 3)

    def test_an_empty_database_is_a_no_op(self, session):
        assert backfill(session) == (0, 0)
