"""Post-processing of model output.

No API calls here — these cover the defensive layer that sits between a
model response and the database, which is where the real risk is.
"""

import pytest

from backend.ai_import import CATEGORY_SLUGS, normalise_draft, parse_json_response


class TestParseJsonResponse:
    def test_plain_json(self):
        assert parse_json_response('{"title": "Cake"}') == {"title": "Cake"}

    def test_strips_a_markdown_fence(self):
        assert parse_json_response('```json\n{"title": "Cake"}\n```') == {"title": "Cake"}

    def test_recovers_json_surrounded_by_prose(self):
        text = 'Here is the recipe:\n{"title": "Cake"}\nHope that helps!'
        assert parse_json_response(text) == {"title": "Cake"}

    def test_no_json_at_all_raises(self):
        with pytest.raises(ValueError):
            parse_json_response("I could not read that image.")


class TestNormaliseDraft:
    def test_keeps_a_valid_category(self):
        assert normalise_draft({"category_slug": "cake"})["category_slug"] == "cake"

    def test_drops_an_invented_category(self):
        # A hallucinated slug must not create junk taxonomy.
        assert normalise_draft({"category_slug": "puddings"})["category_slug"] is None
        assert all(slug in CATEGORY_SLUGS for slug in CATEGORY_SLUGS)

    def test_drops_an_unknown_unit(self):
        draft = normalise_draft(
            {"ingredients": [{"name": "flour", "quantity": 2, "unit": "handfuls"}]}
        )
        assert draft["ingredients"][0]["unit"] is None
        assert draft["ingredients"][0]["quantity"] == 2.0

    def test_flattens_step_objects_to_strings(self):
        draft = normalise_draft({"steps": [{"text": "Mix."}, "Bake.", {"text": "  "}]})
        assert draft["steps"] == [{"text": "Mix."}, {"text": "Bake."}]

    def test_accepts_bare_string_ingredients(self):
        draft = normalise_draft({"ingredients": ["2 eggs"]})
        assert draft["ingredients"][0]["name"] == "2 eggs"
        assert draft["ingredients"][0]["raw_text"] == "2 eggs"

    def test_drops_nameless_ingredients(self):
        assert normalise_draft({"ingredients": [{"name": "  "}]})["ingredients"] == []

    def test_coerces_string_numbers(self):
        draft = normalise_draft({"servings": "8", "prep_minutes": "", "cook_minutes": "abc"})
        assert draft["servings"] == 8
        assert draft["prep_minutes"] is None
        assert draft["cook_minutes"] is None

    def test_caps_and_lowercases_tags(self):
        draft = normalise_draft({"tags": [f"Tag{i}" for i in range(20)]})
        assert len(draft["tags"]) == 12
        assert draft["tags"][0] == "tag0"

    def test_an_empty_response_yields_a_usable_empty_draft(self):
        draft = normalise_draft({})
        assert draft["title"] == ""
        assert draft["ingredients"] == []
        assert draft["confidence"] == 0.0
