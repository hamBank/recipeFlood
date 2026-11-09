"""Ingredient.prep_terms: per-ingredient preparation words.

A pantry row lists the words that are preparation for it ("juice", "zest" for a
lemon). A recipe line whose extra words are all on that list is the same
purchase. The terms ride the same endpoints as aliases.
"""
from sqlmodel import select

from backend.models import Ingredient, ShoppingItem
from backend.recipes_service import Pantry, find_ingredient


def add(client, name, **fields):
    response = client.post("/ingredients", json={"name": name, **fields})
    assert response.status_code == 201, response.text
    return response.json()


class TestTheApi:
    def test_terms_are_stored_lowercased_trimmed_and_without_repeats(self, client):
        lemon = add(client, "lemon", prep_terms=["Juice", " zest ", "juice", "", "Finely  Grated"])
        assert lemon["prep_terms"] == ["juice", "zest", "finely grated"]

    def test_the_default_is_no_terms(self, client):
        assert add(client, "salt")["prep_terms"] == []

    def test_terms_can_be_edited_and_cleared(self, client):
        add(client, "lemon")
        edited = client.patch("/ingredients/lemon", json={"prep_terms": ["Juice", "ZEST"]}).json()
        assert edited["prep_terms"] == ["juice", "zest"]
        cleared = client.patch("/ingredients/lemon", json={"prep_terms": []}).json()
        assert cleared["prep_terms"] == []

    def test_editing_something_else_leaves_the_terms_alone(self, client):
        add(client, "lemon", prep_terms=["juice"])
        client.patch("/ingredients/lemon", json={"cost_per_kg_cents": 500})
        assert client.get("/ingredients/lemon").json()["prep_terms"] == ["juice"]

    def test_a_row_written_before_the_column_existed_still_reads(self, client, session):
        add(client, "lemon")
        row = session.exec(select(Ingredient)).one()
        row.prep_terms = None  # as a database that skipped the backfill would hold it
        session.add(row)
        session.commit()
        assert client.get("/ingredients/lemon").json()["prep_terms"] == []
        assert client.get("/ingredients").json()[0]["prep_terms"] == []


class TestMatching:
    def test_a_line_with_only_listed_extras_finds_the_row(self, client, session):
        add(client, "chicken thigh", prep_terms=["boneless", "skinless", "fillet"])
        found = find_ingredient(session, "boneless skinless chicken thigh fillets")
        assert found.name == "chicken thigh"

    def test_one_unlisted_extra_and_it_is_not_a_match(self, client, session):
        add(client, "chicken thigh", prep_terms=["boneless"])
        assert find_ingredient(session, "smoked boneless chicken thigh") is None

    def test_an_exact_pantry_row_beats_a_prep_match(self, client, session):
        add(client, "lemon", prep_terms=["juice"])
        add(client, "lemon juice")
        assert find_ingredient(session, "lemon juice").name == "lemon juice"

    def test_the_duplicate_check_on_create_ignores_prep_terms(self, client):
        # Creating "lemon juice" as its own row is a deliberate choice, and
        # lemon's prep terms must not block it (fuzzy=False, see find_ingredient).
        add(client, "lemon", prep_terms=["juice"])
        assert client.post("/ingredients", json={"name": "lemon juice"}).status_code == 201

    def test_the_row_with_the_most_specific_name_wins(self, client, session):
        add(client, "chicken", prep_terms=["thigh", "fillet"])
        add(client, "chicken thigh", prep_terms=["fillet"])
        assert find_ingredient(session, "chicken thigh fillet").name == "chicken thigh"

    def test_two_rows_that_both_qualify_equally_are_not_guessed_between(self, client, session):
        add(client, "lemon", prep_terms=["juice"])
        session.add(Ingredient(slug="lemon-2", name="lemon", prep_terms=["juice"]))
        session.commit()
        assert find_ingredient(session, "lemon juice") is None

    def test_a_preloaded_pantry_gives_the_same_answer(self, client, session):
        add(client, "lemon", prep_terms=["juice"])
        pantry = Pantry.load(session)
        assert find_ingredient(session, "juice 1 lemon", pantry=pantry).name == "lemon"
        assert find_ingredient(session, "dragonfruit", pantry=pantry) is None

    def test_what_matched_before_still_matches(self, client, session):
        # Slugs were minted from the original key; the cleaner only adds.
        session.add(Ingredient(slug="ripe-banana", name="ripe banana"))
        session.commit()
        assert find_ingredient(session, "ripe bananas").name == "ripe banana"


class TestRetroactive:
    def test_adding_a_term_links_lines_that_were_waiting(self, client, session):
        add(client, "lemon")
        recipe = client.post(
            "/recipes",
            json={"title": "Dressing", "steps": [], "ingredients": [{"name": "juice 1 lemon"}]},
        ).json()
        line = recipe["ingredients"][0]
        assert line["ingredient_id"] != add_id(client, "lemon")  # a stub, not lemon
        client.delete(f"/ingredients/{_slug_of(client, line['ingredient_id'])}")
        assert client.get(f"/recipes/{recipe['slug']}").json()["ingredients"][0]["ingredient_id"] is None

        client.patch("/ingredients/lemon", json={"prep_terms": ["juice"]})

        relinked = client.get(f"/recipes/{recipe['slug']}").json()["ingredients"][0]
        assert relinked["ingredient_id"] == add_id(client, "lemon")

    def test_it_reaches_shopping_items_too(self, client, session):
        lemon = add(client, "lemon")
        session.add(ShoppingItem(name="juice 1 lemon"))
        session.commit()
        client.patch("/ingredients/lemon", json={"prep_terms": ["juice"]})
        item = session.exec(select(ShoppingItem)).one()
        session.refresh(item)
        assert item.ingredient_id == lemon["id"]


class TestMerge:
    def test_merging_keeps_both_rows_terms(self, client):
        add(client, "lemon", prep_terms=["juice"])
        add(client, "bottled lemon", prep_terms=["zest", "juice"])
        merged = client.post("/ingredients/lemon/merge/bottled-lemon").json()
        assert merged["prep_terms"] == ["juice", "zest"]


def add_id(client, slug):
    return client.get(f"/ingredients/{slug}").json()["id"]


def _slug_of(client, ingredient_id):
    return next(i["slug"] for i in client.get("/ingredients").json() if i["id"] == ingredient_id)
