"""Plurals: "tomatoes" is "tomato", and the pantry rows already named "tomatoe" still work.

The original rule dropped one trailing "s", so "tomatoes", "cherries" and
"leaves" became "tomatoe", "cherrie" and "leave", and the pantry rows minted
from them carry those names. These tests pin both halves: new rows are named
properly, and nothing that matched a mangled row before stops matching.
"""
import pytest
from sqlmodel import select

from backend.afcd import tokenise
from backend.models import Ingredient, RecipeIngredient
from backend.pantry_import import _singular
from backend.recipes_service import Pantry, find_ingredient, get_or_create_ingredient
from scripts.find_duplicate_ingredients import (
    apply_name_repairs,
    corpus_words,
    classify,
    merge_groups,
    name_repairs,
    usage_counts,
)


def row(session, name, *, slug=None, aliases=None):
    ingredient = Ingredient(slug=slug or name.lower().replace(" ", "-"), name=name, aliases=aliases or [])
    session.add(ingredient)
    session.commit()
    session.refresh(ingredient)
    return ingredient


class TestNewRowsAreNamedProperly:
    @pytest.mark.parametrize(
        "line, name",
        [
            ("tomatoes", "tomato"), ("potatoes", "potato"), ("cherries", "cherry"),
            ("raspberries", "raspberry"), ("bay leaves", "bay leaf"), ("chillies", "chilli"),
            ("peaches", "peach"), ("mangoes", "mango"), ("anchovies", "anchovy"),
            ("molasses", "molasses"), ("cookies", "cookie"), ("asparagus", "asparagus"),
        ],
    )
    def test_the_stub_the_importer_mints(self, session, line, name):
        assert get_or_create_ingredient(session, line).name == name

    def test_a_recipe_saved_through_the_api_gets_the_same(self, client):
        client.post(
            "/recipes",
            json={"title": "Salsa", "steps": [], "ingredients": [{"name": "tomatoes", "quantity": 4, "unit": "piece"}]},
        )
        assert [i["name"] for i in client.get("/ingredients").json()] == ["tomato"]


class TestRowsAlreadyNamedTheOldWayStillMatch:
    def test_a_mangled_row_is_found_by_the_plural_it_came_from(self, session):
        legacy = row(session, "tomatoe")  # what the old importer left behind
        assert find_ingredient(session, "tomatoes").id == legacy.id
        assert find_ingredient(session, "tomato").id == legacy.id
        assert find_ingredient(session, "Tomatoes, diced").id == legacy.id

    def test_the_row_is_reused_not_duplicated(self, session):
        legacy = row(session, "cherrie")
        assert get_or_create_ingredient(session, "cherries").id == legacy.id
        assert len(session.exec(select(Ingredient)).all()) == 1

    def test_a_correct_row_is_found_by_a_mangled_name(self, session):
        correct = row(session, "tomato")
        assert find_ingredient(session, "tomatoe").id == correct.id

    def test_a_row_with_the_plural_in_its_name_is_found_by_the_singular(self, session):
        typed = row(session, "Tomatoes")
        assert find_ingredient(session, "tomato").id == typed.id

    def test_an_alias_written_the_old_way_still_matches(self, session):
        pantry_row = row(session, "tomato", aliases=["tomatoe"])
        assert find_ingredient(session, "tomatoes").id == pantry_row.id

    def test_the_exact_slug_still_wins(self, session):
        row(session, "tomatoe")
        right = row(session, "tomato")
        assert find_ingredient(session, "tomatoes").id == right.id

    def test_when_two_rows_are_the_same_ingredient_the_oldest_is_used(self, session):
        older = row(session, "cherrie", slug="cherrie-a")
        row(session, "cherry", slug="cherry-b")
        assert find_ingredient(session, "Cherries (pitted)").id == older.id

    def test_whole_word_containment_folds_plurals_too(self, session):
        jar = row(session, "jar tomatoes")
        assert find_ingredient(session, "tomato").id == jar.id

    def test_a_preloaded_pantry_agrees(self, session):
        legacy = row(session, "tomatoe")
        assert find_ingredient(session, "tomatoes", pantry=Pantry.load(session)).id == legacy.id

    def test_creating_a_row_still_allows_deliberately_distinct_names(self, client):
        # The create check compares slugs and aliases, not names: "large egg"
        # and "egg" may be separate rows on purpose.
        client.post("/ingredients", json={"name": "large egg"})
        assert client.post("/ingredients", json={"name": "egg"}).status_code == 201

    def test_creating_the_plural_of_a_mangled_row_is_still_refused(self, client, session):
        # The create check compares slugs and aliases only, so it reaches a row
        # named the old way through the original key. Dropping that candidate
        # would let a duplicate of "tomatoe" be created as "tomatoes".
        row(session, "tomatoe")
        response = client.post("/ingredients", json={"name": "tomatoes"})
        assert response.status_code == 409

    def test_creating_the_plural_of_a_row_that_exists_is_refused(self, client):
        client.post("/ingredients", json={"name": "tomato"})
        assert client.post("/ingredients", json={"name": "tomatoes"}).status_code == 409


class TestDifferentWordsStayDifferent:
    @pytest.mark.parametrize(
        "pantry_name, line",
        [("pea", "pear"), ("pea", "peach"), ("rice", "rich"), ("oat", "oath"),
         ("tomato", "potato"), ("cherry", "cheese"), ("mint", "mince")],
    )
    def test_no_false_match(self, session, pantry_name, line):
        row(session, pantry_name)
        assert find_ingredient(session, line) is None

    def test_brie_is_not_a_mangled_bries(self, session):
        row(session, "brie")
        assert find_ingredient(session, "brie").name == "brie"
        assert get_or_create_ingredient(session, "brie").name == "brie"


class TestOnTheShoppingList:
    def test_unlinked_singular_and_plural_merge(self, client):
        def recipe(title, name):
            return client.post(
                "/recipes",
                json={"title": title, "steps": [], "ingredients": [{"name": name, "quantity": 1, "unit": "piece"}]},
            ).json()

        a, b = recipe("A", "bay leaves"), recipe("B", "bay leaf")
        for slug in ("bay-leaf",):
            client.delete(f"/ingredients/{slug}")
        response = client.post("/cook-lists", json={"recipes": [{"recipe_id": a["id"]}, {"recipe_id": b["id"]}]})
        client.post(f"/cook-lists/{response.json()['id']}/add-to-shopping")
        items = client.get("/shopping").json()["items"]
        assert len(items) == 1 and items[0]["quantity"] == 2

    def test_a_typed_plural_joins_the_row_already_there(self, client):
        client.post("/shopping", json={"name": "cherries", "quantity": 1, "unit": "piece"})
        client.post("/shopping", json={"name": "Cherry", "quantity": 2, "unit": "piece"})
        items = client.get("/shopping").json()["items"]
        assert len(items) == 1 and items[0]["quantity"] == 3


class TestNutritionLookup:
    """afcd.tokenise compares word sets, so a mangled plural never reached the
    government database's singular entry."""

    def test_plurals_and_mangled_plurals_tokenise_alike(self):
        for text in ("tomatoes", "tomatoe", "Tomato, raw"):
            assert "tomato" in tokenise(text)
        assert tokenise("raspberries") == {"raspberry"}

    def test_words_that_end_in_s_but_are_singular_survive(self):
        assert tokenise("molasses") == {"molasses"}
        assert tokenise("asparagus") == {"asparagus"}

    def test_the_pantry_import_compares_plurals_equal(self):
        assert _singular("red onions") == _singular("red onion")
        assert _singular("tomatoes") == _singular("tomatoe")


class TestCleaningUpExistingRows:
    def test_mangled_and_correct_rows_are_exact_duplicates(self, session):
        rows = [row(session, "cherrie"), row(session, "cherry"), row(session, "cherries")]
        (group,) = classify(rows).confident
        assert {m.name for m in group} == {"cherrie", "cherry", "cherries"}

    def test_merging_them_keeps_every_recipe_line_linked(self, session):
        legacy, correct = row(session, "tomatoe"), row(session, "tomato")
        recipe_lines = []
        from backend.models import Recipe

        recipe = Recipe(slug="r", title="R")
        session.add(recipe)
        session.commit()
        for ingredient in (legacy, correct):
            line = RecipeIngredient(recipe_id=recipe.id, raw_text="x", name="x", ingredient_id=ingredient.id)
            session.add(line)
            recipe_lines.append(line)
        session.commit()
        merge_groups(session, classify([legacy, correct]).confident, usage_counts(session))
        (kept,) = session.exec(select(Ingredient)).all()
        lines = session.exec(select(RecipeIngredient)).all()
        assert len(lines) == 2 and {l.ingredient_id for l in lines} == {kept.id}

    def test_an_alias_never_pulls_a_second_ingredient_into_the_merge(self, session):
        # "cherrie" is also known as "tomatoe". That alias is a claim, not a
        # fact: until 2026-11-10 it made cherry and tomato one group (and the
        # household's report merged water and sugar into onion the same way).
        x = row(session, "cherrie", aliases=["tomatoe"])
        y, z = row(session, "cherry"), row(session, "tomato")
        report = classify([x, y, z])
        (group,) = report.confident
        assert {m.id for m in group} == {x.id, y.id}
        assert [(r.id, alias, o.id) for r, alias, o in report.alias_links] == [(x.id, "tomatoe", z.id)]
        merge_groups(session, report.confident, usage_counts(session))
        assert {i.name for i in session.exec(select(Ingredient)).all()} == {"cherry", "tomato"}

    def test_disjoint_groups_stay_separate(self, session):
        rows = [row(session, n) for n in ("cherrie", "cherry", "tomatoe", "tomato", "lemon")]
        groups = classify(rows).confident
        assert sorted(sorted(m.name for m in g) for g in groups) == [["cherrie", "cherry"], ["tomato", "tomatoe"]]

    def _corpus(self, session, names):
        from backend.models import Recipe

        recipe = Recipe(slug="r", title="R")
        session.add(recipe)
        session.commit()
        for name in names:
            session.add(RecipeIngredient(recipe_id=recipe.id, raw_text=name, name=name))
        session.commit()
        return corpus_words(session, list(session.exec(select(Ingredient)).all()))

    def test_a_mangled_name_is_repaired_when_the_household_uses_the_right_word(self, session):
        legacy = row(session, "cherrie")
        corpus = self._corpus(session, ["cherries, pitted", "cherry tomatoes"])
        assert name_repairs([legacy], corpus) == [(legacy, "cherry")]

    def test_a_name_that_only_looks_mangled_is_left_alone(self, session):
        # "Marie" would repair to "Mary"; nothing in the data says Mary.
        biscuit = row(session, "Marie biscuit")
        corpus = self._corpus(session, ["Marie biscuits", "plain flour"])
        assert name_repairs([biscuit], corpus) == []

    def test_real_words_are_never_repaired(self, session):
        cookie = row(session, "cookie")
        corpus = self._corpus(session, ["cookies", "cooky mix"])
        assert name_repairs([cookie], corpus) == []

    def test_case_and_other_words_are_kept(self, session):
        legacy = row(session, "Fresh Tomatoe")
        corpus = self._corpus(session, ["tomatoes"])
        assert name_repairs([legacy], corpus) == [(legacy, "Fresh Tomato")]

    def test_applying_a_repair_keeps_the_old_name_as_an_alias_and_the_slug(self, session):
        legacy = row(session, "tomatoe")
        corpus = self._corpus(session, ["tomatoes"])
        renamed, skipped = apply_name_repairs(session, name_repairs([legacy], corpus), {"tomatoe"})
        session.refresh(legacy)
        assert (renamed, skipped) == (1, [])
        assert legacy.name == "tomato" and legacy.slug == "tomatoe" and legacy.aliases == ["tomatoe"]
        assert find_ingredient(session, "tomatoes").id == legacy.id  # still found

    def test_a_repair_that_would_duplicate_a_name_is_skipped(self, session):
        legacy, correct = row(session, "tomatoe"), row(session, "tomato")
        corpus = self._corpus(session, ["tomatoes"])
        renamed, skipped = apply_name_repairs(
            session, name_repairs([legacy], corpus), {"tomatoe", "tomato"}
        )
        session.refresh(legacy)
        assert renamed == 0 and [s[0].id for s in skipped] == [legacy.id] and legacy.name == "tomatoe"
        assert correct.name == "tomato"
