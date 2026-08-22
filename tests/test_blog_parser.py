"""The rule-based fallback parser for the Blogger posts.

The fixture below is a real post from the source blog, verbatim: an
ingredient block and a numbered method separated only by `<br />`, with no
headings anywhere. That shape is the entire problem this parser solves.
"""

from backend.blog_parser import (
    classify_line,
    find_servings,
    guess_category,
    html_to_lines,
    is_heading,
    normalise_steps,
    parse_post,
    split_sections,
)

POST = {
    "title": "Cauliflower and tahini fritters with warm quinoa tabouleh",
    "published": "2015-07-06T10:00:00.000+10:00",
    "labels": ["Cauliflower", "fritter", "quinoa", "warm salad"],
    "url": "https://foobie-rcp.blogspot.com/2015/07/cauliflower.html",
    "image_urls": [],
    "content_html": (
        "1 cup tri coloured quinoa, rinsed, drained<br />\n"
        "2 tbsp plain flour<br />\n"
        "1 tsp hot chilli powder<br />\n"
        "1 egg white, lightly beaten<br />\n"
        "1/2 cup tahini<br />\n"
        "extra virgin olive oil, for shallow frying<br />\n"
        "<br />\n"
        "1. Place the quinoa and 1 cup cold water in a saucepan over high heat. "
        "Cover. Bring to the boil. Reduce heat to low.<br />\n"
        "2. Meanwhile, place flour and chilli powder in a bowl. Make a well in "
        "the centre.<br />\n"
        "3. Serve fritters with tabouleh. Serves 4.<br />\n"
    ),
}


class TestClassification:
    def test_amount_led_lines_are_ingredients(self):
        assert classify_line("1 cup tri coloured quinoa, rinsed, drained") == "ingredient"
        assert classify_line("2 tbsp plain flour") == "ingredient"

    def test_numbered_lines_are_steps(self):
        assert classify_line("1. Place the quinoa in a saucepan.") == "step"

    def test_verb_led_prose_is_a_step(self):
        assert classify_line("Preheat oven to 180 C and line two tins.") == "step"

    def test_short_unpunctuated_lines_are_ingredients(self):
        assert classify_line("salt and pepper") == "ingredient"
        assert classify_line("extra virgin olive oil, for shallow frying") == "ingredient"

    def test_headings_are_neither(self):
        assert is_heading("Ingredients:")
        assert is_heading("METHOD")
        assert classify_line("Ingredients:") == "other"


class TestSplitting:
    def test_finds_the_boundary_between_amounts_and_method(self):
        ingredients, steps, _ = split_sections(html_to_lines(POST["content_html"]))
        assert len(ingredients) == 6
        assert ingredients[0].startswith("1 cup tri coloured quinoa")
        assert ingredients[-1].startswith("extra virgin olive oil")
        assert len(steps) == 3

    def test_a_wordy_ingredient_does_not_end_the_block_early(self):
        # One step-looking line among the amounts must not truncate them —
        # that is why the boundary needs two consecutive step lines.
        lines = [
            "2 tbsp plain flour",
            "extra virgin olive oil, for shallow frying",
            "1 tsp salt",
            "Place everything in a bowl and mix well until combined properly.",
            "Bake for 30 minutes until golden and set aside to cool completely.",
        ]
        ingredients, steps, _ = split_sections(lines)
        assert len(ingredients) == 3
        assert len(steps) == 2


class TestSteps:
    def test_numbering_is_stripped(self):
        steps = normalise_steps(["1. Heat the oven.", "2. Mix the flour."])
        assert steps == ["Heat the oven.", "Mix the flour."]

    def test_a_prose_paragraph_is_split_into_sentences(self):
        steps = normalise_steps(
            ["Preheat oven to 180 C. Line a tin with baking paper. Bake for 30 mins."]
        )
        assert len(steps) == 3
        assert steps[0] == "Preheat oven to 180 C."

    def test_short_fragments_are_glued_onto_the_previous_step(self):
        steps = normalise_steps(["Bring to the boil. Cover. Simmer for 15 mins."])
        assert steps[0].endswith("Cover.")
        assert len(steps) == 2


class TestMetadata:
    def test_finds_servings(self):
        # The note keeps the author's wording; `servings` takes the low end.
        assert find_servings("Serve warm. Serves 8-10.") == (8, "Serves 8-10")
        assert find_servings("Makes 24 biscuits") == (24, "Makes 24")
        assert find_servings("no yield here") == (None, None)

    def test_category_from_the_longest_matching_label(self):
        assert guess_category(["Cauliflower", "warm salad"], "") == "salad"
        assert guess_category(["baking", "cake", "chocolate"], "") == "cake"

    def test_category_falls_back_to_the_title(self):
        assert guess_category([], "Leek and Potato Soup") == "soup"

    def test_no_signal_means_no_category(self):
        assert guess_category([], "A thing") is None


class TestParsePost:
    def test_produces_the_ai_draft_shape(self):
        draft = parse_post(POST)
        assert draft["title"] == POST["title"]
        assert draft["category_slug"] == "salad"
        assert draft["tags"] == ["cauliflower", "fritter", "quinoa", "warm salad"]
        assert len(draft["ingredients"]) == 6
        assert len(draft["steps"]) >= 3
        assert draft["servings"] == 4

    def test_amounts_are_parsed_out_of_each_line(self):
        first = parse_post(POST)["ingredients"][0]
        assert first["quantity"] == 1.0
        assert first["unit"] == "cup"
        assert first["name"] == "tri coloured quinoa"
        assert first["raw_text"] == "1 cup tri coloured quinoa, rinsed, drained"

    def test_confidence_stays_below_the_review_threshold(self):
        # The rule parser can never supply a description, times or storage,
        # so its output always lands in the review queue.
        assert parse_post(POST)["confidence"] < 0.75

    def test_an_empty_post_does_not_explode(self):
        draft = parse_post({"title": "Nothing", "content_html": "", "labels": []})
        assert draft["ingredients"] == []
        assert "no ingredient lines identified" in draft["uncertain"]
