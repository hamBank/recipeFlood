"""Shopping list consolidation: brackets, instructions and quantities in names.

The failure these cover is the one that makes a shopping list look careless:
"red onion (finely chopped)", "red onion, diced" and "red onion" arriving as
three lines, or "sugar 250 mL" as its own purchase next to "sugar". The rule
from shopping.py still holds, though: a wrong merge is worse than no merge, so
a good half of these are about what must NOT happen.
"""

import pytest
from sqlmodel import select

from backend.models import ShoppingItem


def make_recipe(client, title, ingredients, **extra):
    response = client.post(
        "/recipes", json={"title": title, "ingredients": ingredients, "steps": [], **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


def shop_for(client, *recipes):
    """Put these recipes on a cooking list and add it to the shopping list."""
    response = client.post(
        "/cook-lists", json={"recipes": [{"recipe_id": r["id"]} for r in recipes]}
    )
    assert response.status_code == 201, response.text
    result = client.post(f"/cook-lists/{response.json()['id']}/add-to-shopping")
    assert result.status_code == 200, result.text
    return client.get("/shopping").json()["items"]


def unlink(client, *slugs):
    """Delete pantry rows the recipe save minted, leaving the lines unlinked."""
    for slug in slugs:
        assert client.delete(f"/ingredients/{slug}").status_code == 204


def add_ingredient(client, name, **fields):
    response = client.post("/ingredients", json={"name": name, **fields})
    assert response.status_code == 201, response.text
    return response.json()


class TestBrackets:
    def test_a_bracketed_instruction_does_not_make_a_second_line(self, client):
        # Bay leaves have no estimated weight, so the lines merge as a plain count.
        a = make_recipe(client, "Soup", [{"name": "bay leaf (torn)", "quantity": 1, "unit": "piece"}])
        b = make_recipe(client, "Stew", [{"name": "bay leaf", "quantity": 2, "unit": "piece"}])
        items = shop_for(client, a, b)
        assert len(items) == 1
        assert items[0]["name"] == "bay leaf"
        assert items[0]["quantity"] == 3
        assert items[0]["note"] == "torn"

    def test_alternatives_in_brackets_go_to_the_note(self, client):
        a = make_recipe(client, "Noodles", [{"name": "kecap manis (or dark chinese soy)", "quantity": 2, "unit": "tbsp"}])
        (item,) = shop_for(client, a)
        assert item["name"] == "kecap manis"
        assert item["note"] == "or dark chinese soy"

    def test_instructions_after_a_comma_go_to_the_note(self, client):
        a = make_recipe(client, "Roast", [{"name": "pumpkin, peeled and cut into pieces", "quantity": 1, "unit": "kg"}])
        (item,) = shop_for(client, a)
        assert item["name"] == "pumpkin"
        assert item["note"] == "peeled and cut into pieces"

    def test_a_recipes_own_note_is_kept_and_joined(self, client):
        a = make_recipe(client, "Soup", [{"name": "carrot (scrubbed)", "note": "organic", "quantity": 3, "unit": "piece"}])
        (item,) = shop_for(client, a)
        assert item["note"] == "organic; scrubbed"

    def test_notes_from_merged_lines_accumulate_without_repeats(self, client):
        a = make_recipe(client, "A", [{"name": "bay leaf (torn)", "quantity": 2, "unit": "piece"}])
        b = make_recipe(client, "B", [{"name": "bay leaf, torn", "quantity": 1, "unit": "piece"}])
        c = make_recipe(client, "C", [{"name": "bay leaf (fresh)", "quantity": 1, "unit": "piece"}])
        (item,) = shop_for(client, a, b, c)
        assert item["quantity"] == 4
        assert item["note"] == "torn; fresh"

    def test_the_cleaned_name_keeps_the_wording_as_written(self, client):
        # Only the brackets go: "Marie biscuits" keeps its capital.
        a = make_recipe(client, "Slice", [{"name": "Packet of Marie biscuits (crushed)"}])
        (item,) = shop_for(client, a)
        assert item["name"] == "Marie biscuits"


class TestQuantitiesInNames:
    def test_a_second_quantity_in_the_name_is_kept_as_a_note(self, client):
        a = make_recipe(client, "Syrup", [{"name": "sugar 250 mL", "quantity": 1, "unit": "cup"}])
        b = make_recipe(client, "Cake", [{"name": "sugar", "quantity": 1, "unit": "cup"}])
        items = shop_for(client, a, b)
        assert len(items) == 1
        assert items[0]["name"] == "sugar"
        assert "250 mL" in items[0]["note"]

    def test_the_pantry_no_longer_mints_a_row_for_a_name_with_a_quantity(self, client):
        make_recipe(client, "Syrup", [{"name": "sugar 250 mL", "quantity": 1, "unit": "cup"}])
        names = [i["name"] for i in client.get("/ingredients").json()]
        assert "sugar" in names
        assert not any("250" in n for n in names)

    def test_a_line_with_no_amount_takes_the_one_in_its_name(self, client):
        a = make_recipe(client, "Bread", [{"name": "water 500 mL"}])
        b = make_recipe(client, "Soup", [{"name": "water", "quantity": 250, "unit": "ml"}])
        (item,) = shop_for(client, a, b)
        assert item["name"] == "water"
        assert item["volume_ml"] == pytest.approx(750)
        assert item["note"] is None

    def test_a_weight_in_the_name_becomes_the_amount(self, client):
        a = make_recipe(client, "Cake", [{"name": "flour 500g"}])
        (item,) = shop_for(client, a)
        assert item["weight_grams"] == pytest.approx(500)
        assert item["name"] == "flour"

    def test_a_line_that_states_an_amount_is_never_overridden_by_its_name(self, client):
        a = make_recipe(client, "Syrup", [{"name": "water 500 mL", "quantity": 1, "unit": "cup"}])
        (item,) = shop_for(client, a)
        assert item["volume_ml"] == pytest.approx(250)  # 1 cup, as stated
        assert "500 mL" in item["note"]

    def test_a_pack_size_and_container_are_not_the_product(self, client):
        a = make_recipe(client, "Pizza", [{"name": "x 7 g tin anchovies – drained", "quantity": 1, "unit": "can"}])
        (item,) = shop_for(client, a)
        assert item["name"] == "anchovies"
        assert "7 g" in item["note"]

    def test_the_amount_is_scaled_like_any_other(self, client):
        a = make_recipe(client, "Bread", [{"name": "water 500 mL"}], servings=2)
        response = client.post("/cook-lists", json={"recipes": [{"recipe_id": a["id"], "servings": 4}]})
        client.post(f"/cook-lists/{response.json()['id']}/add-to-shopping")
        (item,) = client.get("/shopping").json()["items"]
        assert item["volume_ml"] == pytest.approx(1000)


class TestPrepTermsOnTheList:
    def test_juice_and_zest_lines_become_the_ingredient_and_a_count(self, client):
        lemon = add_ingredient(client, "lemon", prep_terms=["juice", "zest", "rind"])
        a = make_recipe(client, "Curd", [{"name": "Zest and juice 2 lemons"}])
        b = make_recipe(client, "Dressing", [{"name": "juice 1 lemon"}])
        # Linked when the recipe was saved: no stray "juice lemon" row was minted.
        assert {i["ingredient_id"] for r in (a, b) for i in r["ingredients"]} == {lemon["id"]}
        assert [i["name"] for i in client.get("/ingredients").json()] == ["lemon"]
        items = shop_for(client, a, b)
        assert len(items) == 1
        assert items[0]["name"] == "lemon"
        assert items[0]["weight_grams"] == pytest.approx(300)  # 3 lemons, 100 g each
        assert items[0]["note"] == "Zest; juice"

    def test_a_lemon_you_can_hold_still_merges_with_them(self, client):
        add_ingredient(client, "lemon", prep_terms=["juice", "zest"])
        a = make_recipe(client, "Curd", [{"name": "juice 2 lemons"}])
        b = make_recipe(client, "Tea", [{"name": "lemon", "quantity": 1, "unit": "piece"}])
        (item,) = shop_for(client, a, b)
        assert item["name"] == "lemon" and item["weight_grams"] == pytest.approx(300)

    def test_without_prep_terms_the_pantry_is_left_alone(self, client):
        # No terms, no guess: "juice 1 lemon" stays its own thing.
        add_ingredient(client, "lemon")
        a = make_recipe(client, "Dressing", [{"name": "juice 1 lemon"}])
        b = make_recipe(client, "Tea", [{"name": "lemon", "quantity": 1, "unit": "piece"}])
        assert len(shop_for(client, a, b)) == 2

    def test_an_unlinked_line_is_matched_when_it_reaches_the_list(self, client):
        # Matching used to run once, when the recipe was saved. A line saved
        # before the pantry knew these words must not stay unlinked for good.
        a = make_recipe(client, "Dressing", [{"name": "juice 1 lemon"}])
        unlink(client, "juice-lemon")
        lemon = add_ingredient(client, "lemon", prep_terms=["juice"], source="markets")
        (item,) = shop_for(client, a)
        assert item["ingredient_id"] == lemon["id"]
        assert item["shop"] == "markets"
        assert item["name"] == "lemon"

    def test_extra_words_the_pantry_does_not_list_are_not_guessed(self, client):
        add_ingredient(client, "lemon", prep_terms=["juice"])
        a = make_recipe(client, "Drink", [{"name": "smoked lemon salt"}])
        unlink(client, "smoked-lemon-salt")
        (item,) = shop_for(client, a)
        assert item["ingredient_id"] is None
        assert item["name"] == "smoked lemon salt"

    def test_a_number_that_belongs_to_the_name_is_not_a_quantity(self, client):
        add_ingredient(client, "chinese 5 spice")
        a = make_recipe(client, "Duck", [{"name": "chinese 5 spice"}])
        (item,) = shop_for(client, a)
        assert item["name"] == "chinese 5 spice"
        assert item["quantity"] is None


class TestWhatStaysApart:
    def test_frozen_and_plain_are_different_purchases_when_unlinked(self, client):
        a = make_recipe(client, "Pie", [{"name": "frozen peas", "quantity": 1, "unit": "cup"}])
        b = make_recipe(client, "Soup", [{"name": "peas", "quantity": 1, "unit": "cup"}])
        unlink(client, "pea")
        assert len(shop_for(client, a, b)) == 2

    def test_a_jar_of_garlic_is_not_garlic(self, client):
        # With both rows in the pantry (the whole-word rule only reaches for a
        # lone "jar garlic"), a container word is part of the name.
        add_ingredient(client, "garlic")
        add_ingredient(client, "jar garlic")
        a = make_recipe(client, "A", [{"name": "jar garlic", "quantity": 1, "unit": "piece"}])
        b = make_recipe(client, "B", [{"name": "garlic", "quantity": 1, "unit": "clove"}])
        names = {i["name"] for i in shop_for(client, a, b)}
        assert names == {"jar garlic", "garlic"}

    def test_lines_linked_to_different_pantry_rows_never_merge_on_name(self, client):
        # Two explicit, different links are the strongest evidence of two
        # purchases there is. The looser name key (plurals, brackets) must not
        # override them: "onions" here is the red onion, not the brown one.
        brown = add_ingredient(client, "onion")
        red = add_ingredient(client, "red onion")
        a = make_recipe(client, "A", [{"name": "onion", "ingredient_id": brown["id"], "quantity": 1, "unit": "piece"}])
        b = make_recipe(client, "B", [{"name": "Onions (sliced)", "ingredient_id": red["id"], "quantity": 1, "unit": "piece"}])
        items = shop_for(client, a, b)
        assert {i["ingredient_id"] for i in items} == {brown["id"], red["id"]}
        assert len(items) == 2

    def test_amounts_of_different_kinds_still_do_not_add(self, client):
        a = make_recipe(client, "A", [{"name": "parsley (chopped)", "quantity": 1, "unit": "bunch"}])
        b = make_recipe(client, "B", [{"name": "parsley", "quantity": 250, "unit": "g"}])
        assert len(shop_for(client, a, b)) == 2


class TestTypedItems:
    def test_a_typed_name_merges_with_a_cleaned_recipe_line(self, client):
        a = make_recipe(client, "Soup", [{"name": "bay leaf (torn)", "quantity": 1, "unit": "piece"}])
        shop_for(client, a)
        response = client.post("/shopping", json={"name": "Bay Leaf (dried)", "quantity": 2, "unit": "piece"})
        assert response.status_code == 201
        items = client.get("/shopping").json()["items"]
        assert len(items) == 1 and items[0]["quantity"] == 3

    def test_the_note_is_stored_on_the_row(self, client, session):
        a = make_recipe(client, "Soup", [{"name": "red onion (finely chopped)", "quantity": 1, "unit": "piece"}])
        shop_for(client, a)
        assert session.exec(select(ShoppingItem)).one().note == "finely chopped"
