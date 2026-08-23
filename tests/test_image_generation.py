"""backend/image_generation.py's prompt building — the only part of the
module with no network call. generate_image (the OpenAI call) is exactly
the kind of thing excluded from unit coverage here, same reasoning as
recipe_fetch.py's fetch_html/fetch_recipe_draft.
"""

from backend.image_generation import build_prompt


class TestBuildPrompt:
    def test_includes_the_title(self):
        assert "Flax Bread" in build_prompt("Flax Bread", None, None)

    def test_includes_the_description_when_present(self):
        prompt = build_prompt("Flax Bread", "A dense, seedy loaf.", None)
        assert "A dense, seedy loaf." in prompt

    def test_omits_a_missing_description(self):
        prompt = build_prompt("Flax Bread", None, None)
        assert "None" not in prompt

    def test_omits_a_blank_description(self):
        prompt = build_prompt("Flax Bread", "   ", None)
        assert "   " not in prompt

    def test_mentions_the_section_when_present(self):
        prompt = build_prompt("Flax Bread", None, "Bread")
        assert "bread dish" in prompt.lower()

    def test_never_invents_plating_the_recipe_did_not_state(self):
        # Nothing here should introduce specifics ("on a wooden board",
        # "garnished with parsley") that the recipe itself never said.
        prompt = build_prompt("Flax Bread", None, None)
        for word in ("wooden", "parsley", "garnish"):
            assert word not in prompt.lower()

    def test_asks_for_no_text_or_people(self):
        prompt = build_prompt("Flax Bread", None, None).lower()
        assert "no text" in prompt
        assert "no people" in prompt
