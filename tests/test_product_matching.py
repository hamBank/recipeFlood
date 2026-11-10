"""find_ingredient and the rule "tinned, frozen, smoked and dried are
different ingredients" (SPEC.md, "What is the same ingredient")."""

from backend.models import Ingredient
from backend.recipes_service import find_ingredient


def row(session, name, *, slug=None, aliases=None):
    ingredient = Ingredient(slug=slug or name.lower().replace(" ", "-"), name=name, aliases=aliases or [])
    session.add(ingredient)
    session.commit()
    return ingredient


def test_a_frozen_line_finds_the_frozen_row(session):
    row(session, "spinach")
    frozen = row(session, "frozen spinach")
    assert find_ingredient(session, "frozen spinach").id == frozen.id


def test_a_frozen_line_does_not_fall_back_to_the_fresh_row_through_the_old_slug(session):
    # The original key dropped "frozen", so slug "spinach" was a candidate.
    row(session, "spinach")
    assert find_ingredient(session, "frozen spinach") is None


def test_a_plain_line_never_reaches_a_lone_product_row(session):
    row(session, "frozen peas")
    row(session, "chilli sauce")
    assert find_ingredient(session, "peas") is None
    assert find_ingredient(session, "chilli") is None


def test_containment_still_works_without_a_product_word(session):
    jar = row(session, "jar garlic")
    assert find_ingredient(session, "garlic").id == jar.id


def test_a_row_named_this_beats_a_row_with_it_as_an_alias(session):
    row(session, "pouring cream", aliases=["thickened cream"])
    thickened = row(session, "thickened cream", slug="cream-thick")
    assert find_ingredient(session, "thickened cream").id == thickened.id


def test_an_alias_still_works_alone(session):
    pouring = row(session, "pouring cream", aliases=["thickened cream"])
    assert find_ingredient(session, "thickened cream").id == pouring.id


def test_a_dash_type_row_is_found_from_a_recipe_line(session):
    pear = row(session, "Pear - Green", slug="pear-green")
    row(session, "pear")
    assert find_ingredient(session, "2 green pears").id == pear.id
    assert find_ingredient(session, "pears").name == "pear"


def test_a_synonym_reaches_the_shop_name(session):
    capsicum = row(session, "Capsicum - Green", slug="capsicum-green")
    assert find_ingredient(session, "green bell pepper").id == capsicum.id
