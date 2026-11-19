"""A list row linked to the pantry shows the pantry's name (2026-11-19: "bell
pepper", merged into capsicum, still read "bell pepper" on the list)."""

from sqlmodel import select

from backend.models import Ingredient, ShoppingItem


def row(session, name, **fields):
    ingredient = Ingredient(slug=name.lower().replace(" ", "-"), name=name, **fields)
    session.add(ingredient)
    session.commit()
    session.refresh(ingredient)
    return ingredient


def item(session, name, ingredient=None, **fields):
    thing = ShoppingItem(name=name, ingredient_id=ingredient.id if ingredient else None, **fields)
    session.add(thing)
    session.commit()
    session.refresh(thing)
    return thing


def fresh(session, thing):
    session.expire_all()
    return session.get(ShoppingItem, thing.id)


def test_merging_renames_the_absorbed_rows_list_items(client, session):
    capsicum = row(session, "capsicum")
    bell = row(session, "bell pepper")
    line = item(session, "bell pepper", bell, weight_grams=700)
    assert client.post("/ingredients/capsicum/merge/bell-pepper").status_code == 200
    line = fresh(session, line)
    assert (line.ingredient_id, line.name, line.note, line.weight_grams) == (capsicum.id, "capsicum", None, 700)
    assert line.sheet_dirty


def test_a_new_alias_links_and_renames(client, session):
    row(session, "brown onion")
    line = item(session, "onions")
    client.patch("/ingredients/brown-onion", json={"aliases": ["onion"]})
    line = fresh(session, line)
    assert line.name == "brown onion" and line.ingredient_id is not None


def test_renaming_the_pantry_row_renames_its_items(client, session):
    pear = row(session, "green pear")
    line = item(session, "green pear", pear)
    client.patch("/ingredients/green-pear", json={"name": "Pear - Green"})
    assert fresh(session, line).name == "Pear - Green"


def test_a_typed_item_shows_the_pantry_name(client, session):
    row(session, "capsicum", aliases=["bell pepper"])
    made = client.post("/shopping", json={"name": "bell pepper"}).json()
    assert made["name"] == "capsicum"
    assert not made.get("note")


def test_words_beyond_the_pantry_name_become_the_note(client, session):
    row(session, "butter")
    made = client.post("/shopping", json={"name": "cold butter"}).json()
    assert made["name"] == "butter"
    assert made["note"] == "cold butter"


def test_an_unlinked_item_keeps_its_wording(client, session):
    made = client.post("/shopping", json={"name": "Dragonfruit"}).json()
    assert made["name"] == "Dragonfruit"


def test_the_finders_renames_reach_the_list(session):
    from scripts.find_duplicate_ingredients import apply_renames, rename_proposals

    tomato = row(session, "tinned tomatoes")
    line = item(session, "tinned tomatoes", tomato)
    apply_renames(session, rename_proposals([tomato]), {"tinned tomatoes"})
    assert fresh(session, line).name == "Tomato - Canned"


def test_a_ticked_item_is_renamed_too(client, session):
    capsicum = row(session, "capsicum")
    bell = row(session, "bell pepper")
    line = item(session, "bell pepper", bell, is_checked=True)
    client.post("/ingredients/capsicum/merge/bell-pepper")
    line = fresh(session, line)
    assert line.name == "capsicum" and line.ingredient_id == capsicum.id


def test_only_rows_for_that_ingredient_change(client, session):
    row(session, "capsicum")
    row(session, "bell pepper")
    other = item(session, "dragonfruit")
    client.post("/ingredients/capsicum/merge/bell-pepper")
    assert fresh(session, other).name == "dragonfruit"
    assert len(session.exec(select(ShoppingItem)).all()) == 1


def test_the_finder_lists_and_fixes_stale_list_names(session, monkeypatch, capsys):
    import sys

    from scripts import find_duplicate_ingredients as finder

    capsicum = row(session, "capsicum", aliases=["bell pepper"])
    line = item(session, "bell pepper", capsicum, weight_grams=700)  # linked before this change
    monkeypatch.setattr(finder, "engine", session.get_bind())
    monkeypatch.setattr(sys, "argv", ["finder"])
    finder.main()
    assert "'bell pepper'  →  'capsicum'" in capsys.readouterr().out
    assert fresh(session, line).name == "bell pepper"  # the report changes nothing

    monkeypatch.setattr(sys, "argv", ["finder", "--rename"])
    finder.main()
    line = fresh(session, line)
    assert (line.name, line.weight_grams, line.sheet_dirty) == ("capsicum", 700, True)
