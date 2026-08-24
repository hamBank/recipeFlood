"""scripts/import_recipe_history.py's dedup and idempotency logic: the
part that decides whether a row needs a live fetch, whether a recipe
already exists, and whether a re-run of the same CSV creates anything
twice. `fetch_recipe_draft` is monkeypatched throughout — no network.
"""

from datetime import date

import pytest
from sqlmodel import select

from backend.models import CookList, CookListRecipe, ImportSource, PreparedEvent, Recipe
from backend.recipe_fetch import FetchedRecipe
from backend.recipe_history import CookRecord
from scripts.import_recipe_history import (
    _backfill_cook_lists,
    _record_event,
    _resolve_book_recipe,
    _resolve_url_recipe,
    to_ingredient_inputs,
)


def record(**overrides):
    defaults = dict(
        cook_date=date(2024, 3, 1),
        name="Cake",
        raw_name="Cake",
        url=None,
        book_name=None,
        book_page=None,
    )
    return CookRecord(**{**defaults, **overrides})


class TestToIngredientInputs:
    def test_a_recognised_unit_is_kept(self):
        result = to_ingredient_inputs([{"name": "flour", "quantity": 2.0, "unit": "cup"}])
        assert result[0].name == "flour"
        assert result[0].quantity == 2.0
        assert result[0].unit == "cup"

    def test_an_unrecognised_unit_becomes_none_not_an_error(self):
        result = to_ingredient_inputs([{"name": "flour", "unit": "handfuls"}])
        assert result[0].unit is None


class TestResolveUrlRecipe:
    def test_a_usable_json_ld_draft_creates_a_recipe(self, session, monkeypatch):
        draft = {
            "title": "Cake",
            "description": None,
            "section": None,
            "tags": [],
            "servings": None,
            "servings_note": None,
            "prep_minutes": None,
            "cook_minutes": None,
            "storage": None,
            "ingredients": [
                {"name": "flour", "quantity": 2.0, "unit": "cup", "raw_text": "2 cups flour"}
            ],
            "steps": [{"text": "Bake."}],
            "notes": None,
            "confidence": 1.0,
            "uncertain": [],
        }
        monkeypatch.setattr(
            "scripts.import_recipe_history.fetch_recipe_draft",
            lambda url, **kw: FetchedRecipe(draft=draft, tier="json_ld"),
        )
        recipe, reason = _resolve_url_recipe(session, {}, None, record(url="https://example.test/cake"))
        assert reason is None
        assert recipe is not None
        assert recipe.title == "Cake"
        assert recipe.source_url == "https://example.test/cake"
        assert recipe.import_source == ImportSource.web
        assert recipe.needs_review is True

    def test_a_draft_with_no_title_or_ingredients_is_a_failure(self, session, monkeypatch):
        empty_draft = {"title": "", "ingredients": []}
        monkeypatch.setattr(
            "scripts.import_recipe_history.fetch_recipe_draft",
            lambda url, **kw: FetchedRecipe(draft=empty_draft, tier="ai_text"),
        )
        recipe, reason = _resolve_url_recipe(session, {}, None, record(url="https://example.test/blank"))
        assert recipe is None
        assert "no usable" in reason

    def test_a_fetch_error_is_reported_not_raised(self, session, monkeypatch):
        def boom(url, **kw):
            raise RuntimeError("503")

        monkeypatch.setattr("scripts.import_recipe_history.fetch_recipe_draft", boom)
        recipe, reason = _resolve_url_recipe(session, {}, None, record(url="https://example.test/down"))
        assert recipe is None
        assert "fetch failed" in reason

    def test_an_existing_recipe_with_the_same_source_url_is_reused_without_fetching(
        self, session, monkeypatch
    ):
        existing = Recipe(slug="cake", title="Cake", source_url="https://example.test/cake")
        session.add(existing)
        session.commit()

        def boom(url, **kw):
            raise AssertionError("should not fetch — a matching recipe already exists")

        monkeypatch.setattr("scripts.import_recipe_history.fetch_recipe_draft", boom)
        recipe, reason = _resolve_url_recipe(session, {}, None, record(url="https://example.test/cake"))
        assert reason is None
        assert recipe.id == existing.id

    def test_a_url_already_seen_this_run_is_not_fetched_twice(self, session, monkeypatch):
        calls = []

        def fetch(url, **kw):
            calls.append(url)
            return FetchedRecipe(
                draft={"title": "Cake", "ingredients": [{"name": "flour", "raw_text": "flour"}]},
                tier="json_ld",
            )

        monkeypatch.setattr("scripts.import_recipe_history.fetch_recipe_draft", fetch)
        cache = {}
        r1, _ = _resolve_url_recipe(session, cache, None, record(url="https://example.test/cake"))
        r2, _ = _resolve_url_recipe(session, cache, None, record(url="https://example.test/cake"))
        assert len(calls) == 1
        assert r1.id == r2.id


class TestResolveBookRecipe:
    def test_creates_a_title_only_stub(self, session):
        recipe = _resolve_book_recipe(session, {}, "Plenty More", 133, "Braised Kale")
        assert recipe.title == "Braised Kale"
        assert recipe.source_name == "Plenty More"
        assert recipe.source_page == 133
        assert recipe.source_url is None
        assert recipe.import_source == ImportSource.web
        assert recipe.needs_review is True

    def test_the_same_citation_reuses_the_existing_recipe(self, session):
        first = _resolve_book_recipe(session, {}, "Plenty More", 133, "Braised Kale")
        second = _resolve_book_recipe(session, {}, "Plenty More", 133, "Braised Kale (again)")
        assert first.id == second.id
        # Not renamed by the second sighting — the first stub's title stands.
        assert second.title == "Braised Kale"

    def test_a_different_page_in_the_same_book_is_a_different_recipe(self, session):
        first = _resolve_book_recipe(session, {}, "Plenty More", 133, "Braised Kale")
        second = _resolve_book_recipe(session, {}, "Plenty More", 90, "Roast Fennel")
        assert first.id != second.id


class TestRecordEvent:
    def test_creates_one_event_for_a_new_recipe_and_date(self, session):
        recipe = Recipe(slug="cake", title="Cake")
        session.add(recipe)
        session.commit()
        created = _record_event(session, set(), recipe, date(2024, 3, 1))
        session.commit()
        assert created is True
        assert len(session.exec(select(PreparedEvent)).all()) == 1

    def test_a_missing_cook_date_creates_nothing(self, session):
        recipe = Recipe(slug="cake", title="Cake")
        session.add(recipe)
        session.commit()
        assert _record_event(session, set(), recipe, None) is False
        assert session.exec(select(PreparedEvent)).all() == []

    def test_the_same_recipe_and_date_is_not_duplicated_across_runs(self, session):
        # Simulates a re-run: the in-run `seen` set is fresh, but the row
        # already made it to the database on an earlier run.
        recipe = Recipe(slug="cake", title="Cake")
        session.add(recipe)
        session.commit()
        session.add(PreparedEvent(recipe_id=recipe.id, prepared_on=date(2024, 3, 1)))
        session.commit()

        created = _record_event(session, set(), recipe, date(2024, 3, 1))
        assert created is False
        assert len(session.exec(select(PreparedEvent)).all()) == 1

    def test_the_same_recipe_and_date_is_not_duplicated_within_one_run(self, session):
        recipe = Recipe(slug="cake", title="Cake")
        session.add(recipe)
        session.commit()
        seen = set()
        assert _record_event(session, seen, recipe, date(2024, 3, 1)) is True
        assert _record_event(session, seen, recipe, date(2024, 3, 1)) is False


class TestBackfillCookLists:
    def test_creates_one_list_per_date_with_its_recipes(self, session):
        a = Recipe(slug="a", title="A")
        b = Recipe(slug="b", title="B")
        session.add_all([a, b])
        session.commit()

        created, touched = _backfill_cook_lists(
            session, {date(2024, 3, 1): {a.id, b.id}}
        )
        session.commit()
        assert created == 1
        assert touched == 0
        cook_list = session.exec(select(CookList)).one()
        assert cook_list.cook_date == date(2024, 3, 1)
        # Already cooked, definitionally — stamped completed so it doesn't
        # clutter the list screen alongside lists still being planned.
        assert cook_list.completed is True
        members = session.exec(
            select(CookListRecipe).where(CookListRecipe.cook_list_id == cook_list.id)
        ).all()
        assert {m.recipe_id for m in members} == {a.id, b.id}

    def test_a_second_run_extends_rather_than_duplicates(self, session):
        a = Recipe(slug="a", title="A")
        b = Recipe(slug="b", title="B")
        session.add_all([a, b])
        session.commit()

        _backfill_cook_lists(session, {date(2024, 3, 1): {a.id}})
        session.commit()
        created, touched = _backfill_cook_lists(session, {date(2024, 3, 1): {a.id, b.id}})
        session.commit()

        assert created == 0
        assert touched == 1
        assert len(session.exec(select(CookList)).all()) == 1
        members = session.exec(select(CookListRecipe)).all()
        assert {m.recipe_id for m in members} == {a.id, b.id}

    def test_extending_an_existing_list_does_not_touch_its_completed_flag(self, session):
        # completed is only stamped at creation — a re-run must not undo a
        # household manually reopening an imported list by hand.
        a = Recipe(slug="a", title="A")
        b = Recipe(slug="b", title="B")
        session.add_all([a, b])
        session.commit()

        _backfill_cook_lists(session, {date(2024, 3, 1): {a.id}})
        session.commit()
        cook_list = session.exec(select(CookList)).one()
        cook_list.completed = False
        session.add(cook_list)
        session.commit()

        _backfill_cook_lists(session, {date(2024, 3, 1): {a.id, b.id}})
        session.commit()
        session.refresh(cook_list)
        assert cook_list.completed is False

    def test_a_human_made_cook_list_on_the_same_date_is_left_alone(self, session):
        # Only lists this script itself created (marked via `description`)
        # are reused — a list a person made by hand for that date must not
        # be silently repurposed as the import's.
        a = Recipe(slug="a", title="A")
        session.add(a)
        session.add(CookList(cook_date=date(2024, 3, 1), description="Anna's birthday"))
        session.commit()

        created, touched = _backfill_cook_lists(session, {date(2024, 3, 1): {a.id}})
        session.commit()
        assert created == 1
        assert touched == 0
        assert len(session.exec(select(CookList)).all()) == 2
