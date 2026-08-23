"""backend/image_generation.py's prompt building and retry-delay math —
the parts of the module with no network call. generate_image itself (the
OpenAI call) is exactly the kind of thing excluded from unit coverage
here, same reasoning as recipe_fetch.py's fetch_html/fetch_recipe_draft.
"""

from backend.image_generation import _retry_delay, build_prompt


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


class TestRetryDelay:
    def test_honours_a_valid_retry_after_header(self):
        assert _retry_delay(0, "12") == 12.0

    def test_a_negative_retry_after_is_clamped_to_zero(self):
        assert _retry_delay(0, "-5") == 0.0

    def test_falls_back_to_exponential_backoff_with_no_header(self):
        # 1s, 2s, 4s... plus up to 0.5s of jitter.
        for attempt, base in enumerate((1.0, 2.0, 4.0, 8.0)):
            delay = _retry_delay(attempt, None)
            assert base <= delay < base + 0.5

    def test_an_unparseable_header_falls_back_to_backoff(self):
        delay = _retry_delay(0, "not-a-number")
        assert 1.0 <= delay < 1.5
