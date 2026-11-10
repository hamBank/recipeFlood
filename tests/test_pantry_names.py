"""backend/pantry_names.py: new pantry rows are named the way the household
names them, so the duplicate finder's RENAMES list doesn't fill up again."""

import pytest
from sqlmodel import select

from backend.models import Ingredient
from backend.pantry_names import new_row_name


@pytest.mark.parametrize("line,name", [
    ("green pears", "Pear - Green"),
    ("Green Pears, sliced", "Pear - Green"),
    ("tinned tomatoes", "Tomato - Canned"),
    ("x 400 g tin chickpeas", "Chickpea - Canned"),
    ("japanese eggplant", "Eggplant - Japanese"),
    ("sour cream", "Cream - Sour"),
    ("red wine", "Wine - Red"),
    ("shredded gruyere cheese divided", "shredded gruyere cheese"),
    ("x 250g blocks halloumi thickly", "halloumi"),
    ("bell peppers", "capsicum"),
    ("Extra virgin olive oil", "extra virgin olive oil"),
    ("frozen peas", "frozen pea"),
    ("cream of tartar", "cream of tartar"),
])
def test_a_new_row_is_named_by_the_house_rules(line, name):
    assert new_row_name(line) == name


@pytest.mark.parametrize("line", ["coconut cream", "rice wine", "ice cream", "cream cheese"])
def test_another_ingredient_in_front_of_cream_or_wine_is_not_a_type(line):
    assert " - " not in new_row_name(line)


def test_prose_is_left_as_it_is():
    # Nothing can turn a sentence into a name reliably; the finder's REVIEW
    # list is where a person deals with it.
    assert new_row_name("depending on liquid content your banana") == "depending on liquid content your banana"


def save_recipe(client, title, names):
    response = client.post(
        "/recipes", json={"title": title, "steps": [], "ingredients": [{"name": n} for n in names]}
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestRecipeSaves:
    def test_a_recipe_line_mints_a_well_named_row(self, client, session):
        save_recipe(client, "Tart", ["green pears", "x 400 g tin tomatoes", "bell pepper"])
        names = {i.name for i in session.exec(select(Ingredient)).all()}
        assert names == {"Pear - Green", "Tomato - Canned", "capsicum"}

    def test_later_lines_find_that_row_instead_of_minting_another(self, client, session):
        save_recipe(client, "Tart", ["green pears", "tinned tomatoes"])
        save_recipe(client, "Crumble", ["2 green pears, sliced", "canned tomatoes", "Pear - Green"])
        rows = session.exec(select(Ingredient)).all()
        assert sorted(i.name for i in rows) == ["Pear - Green", "Tomato - Canned"]

    def test_a_typed_pantry_row_keeps_the_name_typed(self, client):
        made = client.post("/ingredients", json={"name": "green pears"}).json()
        assert made["name"] == "green pears"

    def test_a_line_whose_house_name_already_exists_uses_that_row(self, client, session):
        # Found on the blog snapshot: "butter cubed", "cold butter" and
        # "chilled butter" each minted another row named "butter".
        save_recipe(client, "Pastry", ["butter", "butter cubed", "cold butter", "• Garlic as required", "garlic"])
        names = sorted(i.name for i in session.exec(select(Ingredient)).all())
        assert names == ["butter", "garlic"]

    def test_the_same_words_in_another_order_are_the_same_row(self, client, session):
        save_recipe(client, "Dressing", ["lime juice", "juice of a lime", "garlic clove", "cloves garlic",
                                         "buttermilk", "well-shaken buttermilk"])
        names = sorted(i.name for i in session.exec(select(Ingredient)).all())
        assert names == ["buttermilk", "garlic clove", "lime juice"]

    def test_a_can_in_front_is_canned(self, client, session):
        save_recipe(client, "Sauce", ["14.5-ounce can tomatoes", "can tomatoes", "tinned tomatoes"])
        assert [i.name for i in session.exec(select(Ingredient)).all()] == ["Tomato - Canned"]
