"""Post-processing of model output.

No API calls here — these cover the defensive layer that sits between a
model response and the database, which is where the real risk is.
"""

import pytest

from backend.ai_import import SECTION_SLUGS, normalise_draft, parse_json_response


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
    def test_keeps_a_valid_section(self):
        draft = normalise_draft({"section": "cake"})
        assert draft["section"] == "cake"
        # ...and folds it into the tag list, which is what a recipe stores.
        assert draft["tags"] == ["cake"]

    def test_drops_an_invented_section(self):
        # A hallucinated slug must not create junk navigation.
        draft = normalise_draft({"section": "puddings", "tags": ["sweet"]})
        assert draft["section"] is None
        assert draft["tags"] == ["sweet"]

    def test_does_not_duplicate_a_section_already_in_tags(self):
        draft = normalise_draft({"section": "cake", "tags": ["cake", "chocolate"]})
        assert draft["tags"] == ["cake", "chocolate"]

    def test_every_section_slug_is_a_string(self):
        assert SECTION_SLUGS and all(isinstance(s, str) for s in SECTION_SLUGS)

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


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _response(text, stop_reason="end_turn"):
    from types import SimpleNamespace

    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
    )


@pytest.fixture
def fake_client(monkeypatch):
    from backend import ai_import

    def install(response):
        client = _FakeClient(response)
        monkeypatch.setattr(ai_import, "_client", lambda: client)
        return client

    return install


class TestStructuredOutput:
    """The request asks the API for schema-valid JSON, and the reply is
    checked for being cut off or refused before it is parsed."""

    def test_the_request_carries_the_recipe_schema(self, fake_client):
        from backend.ai_import import RECIPE_SCHEMA, draft_from_text

        client = fake_client(_response('{"title": "Scones", "ingredients": [], "steps": []}'))
        draft = draft_from_text("Scones. Mix and bake.")

        assert draft["title"] == "Scones"
        assert client.messages.kwargs["output_config"] == {
            "format": {"type": "json_schema", "schema": RECIPE_SCHEMA}
        }

    def test_an_inch_mark_inside_a_value_survives(self, fake_client):
        """The import that prompted structured outputs: a raw `2"` inside a
        string. With the schema enforced the API escapes it, so it parses."""
        from backend.ai_import import draft_from_text

        reply = '{"title": "Roast", "ingredients": [], "steps": ["Cut into 2\\" pieces."]}'
        fake_client(_response(reply))

        assert draft_from_text("...")["steps"] == [{"text": 'Cut into 2" pieces.'}]

    def test_a_cut_off_reply_says_so(self, fake_client):
        from backend.ai_import import draft_from_text

        fake_client(_response('{"title": "Cake", "steps": ["Mix the', stop_reason="max_tokens"))
        with pytest.raises(ValueError, match="too long"):
            draft_from_text("...")

    def test_a_refusal_says_so(self, fake_client):
        from backend.ai_import import draft_from_image

        fake_client(_response("", stop_reason="refusal"))
        with pytest.raises(ValueError, match="declined"):
            draft_from_image(b"\x89PNG", "image/png")

    def test_the_schema_covers_every_key_the_prompt_asks_for(self):
        from backend.ai_import import RECIPE_SCHEMA, SYSTEM_PROMPT

        top = set(RECIPE_SCHEMA["properties"])
        assert top == set(RECIPE_SCHEMA["required"])
        for key in top:
            assert f"\n  {key} " in SYSTEM_PROMPT
        item = RECIPE_SCHEMA["properties"]["ingredients"]["items"]
        assert set(item["properties"]) == set(item["required"])
        for key in item["properties"]:
            assert f"{key} " in SYSTEM_PROMPT

    def test_every_object_forbids_extra_keys(self):
        """The API rejects a schema whose objects allow additional keys."""
        from backend.ai_import import RECIPE_SCHEMA

        def objects(schema):
            if isinstance(schema, dict):
                if schema.get("type") == "object":
                    yield schema
                for value in schema.values():
                    yield from objects(value)
            elif isinstance(schema, list):
                for value in schema:
                    yield from objects(value)

        found = list(objects(RECIPE_SCHEMA))
        assert len(found) == 2
        assert all(obj.get("additionalProperties") is False for obj in found)

    def test_the_schema_stays_inside_the_apis_union_type_limit(self):
        """Structured outputs allow at most 16 parameters using anyOf (each
        nullable field here is one) across a request; past that the API
        rejects the schema and every import fails with a 400."""
        from backend.ai_import import RECIPE_SCHEMA

        def unions(properties):
            return sum(1 for prop in properties.values() if "anyOf" in prop)

        item = RECIPE_SCHEMA["properties"]["ingredients"]["items"]
        total = unions(RECIPE_SCHEMA["properties"]) + unions(item["properties"])
        assert total <= 16
