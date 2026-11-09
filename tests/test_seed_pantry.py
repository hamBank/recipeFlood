"""scripts/seed_pantry.py: the starter pantry, including its prep terms."""
import json
import sys

import pytest
from sqlmodel import Session, select

from backend.models import Ingredient
from scripts import seed_pantry


@pytest.fixture
def seed(engine, monkeypatch):
    monkeypatch.setattr(seed_pantry, "engine", engine)

    def run(*args):
        monkeypatch.setattr(sys, "argv", ["seed_pantry", *args])
        assert seed_pantry.main() == 0

    return run


def row(engine, name):
    with Session(engine) as session:
        return session.exec(select(Ingredient).where(Ingredient.name == name)).one()


def test_the_starter_data_is_valid_and_seeds_prep_terms(engine, seed):
    seed()
    assert row(engine, "garlic").prep_terms == ["clove", "bulb"]
    assert row(engine, "coriander").prep_terms == ["leaves", "sprigs", "stalks", "stems", "roots"]
    assert row(engine, "plain flour").prep_terms == []


def test_a_term_added_by_hand_survives_a_reseed(engine, seed):
    seed()
    with Session(engine) as session:
        garlic = session.exec(select(Ingredient).where(Ingredient.name == "garlic")).one()
        garlic.prep_terms = [*garlic.prep_terms, "crushed"]
        session.add(garlic)
        session.commit()
    seed()
    assert row(engine, "garlic").prep_terms == ["clove", "bulb", "crushed"]


def test_reseeding_does_not_duplicate_terms(engine, seed):
    seed()
    seed()
    assert row(engine, "garlic").prep_terms == ["clove", "bulb"]


def test_every_seeded_term_is_lowercase_and_a_plain_word():
    data = json.loads(seed_pantry.PANTRY_PATH.read_text())["ingredients"]
    for definition in data:
        for term in definition.get("prep_terms", []):
            assert term == term.lower().strip() and term.replace(" ", "").isalpha(), (definition["name"], term)


def test_the_words_that_change_what_you_buy_are_not_seeded():
    # "juice" on lemon would turn "1/4 cup lemon juice" into lemons.
    data = {d["name"]: d for d in json.loads(seed_pantry.PANTRY_PATH.read_text())["ingredients"]}
    assert "juice" not in data["lemon"].get("prep_terms", [])
