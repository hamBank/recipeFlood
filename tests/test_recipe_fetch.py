"""Structuring a fetched recipe page: JSON-LD extraction, the ISO 8601
duration format schema.org uses, and the plain-text fallback for AI
extraction. No network here — see recipe_fetch.py's docstring for why
fetch_html/fetch_recipe_draft are excluded.
"""

from backend.recipe_fetch import (
    draft_from_json_ld,
    extract_json_ld_recipe,
    html_to_text,
    parse_iso8601_duration,
)


class TestParseIso8601Duration:
    def test_minutes_only(self):
        assert parse_iso8601_duration("PT20M") == 20

    def test_hours_and_minutes(self):
        assert parse_iso8601_duration("PT1H30M") == 90

    def test_hours_only(self):
        assert parse_iso8601_duration("PT2H") == 120

    def test_days_and_hours(self):
        assert parse_iso8601_duration("P1DT2H") == 1560

    def test_seconds_are_truncated_not_rounded(self):
        # Under a minute; a recipe's timing is never precise to the second.
        assert parse_iso8601_duration("PT45S") == 0

    def test_all_zero_components_is_treated_as_absent(self):
        assert parse_iso8601_duration("P0D") is None

    def test_none_is_passed_through(self):
        assert parse_iso8601_duration(None) is None

    def test_empty_string(self):
        assert parse_iso8601_duration("") is None

    def test_garbage_is_not_a_duration(self):
        assert parse_iso8601_duration("30 minutes") is None


def _script(payload: str) -> str:
    return f'<html><head><script type="application/ld+json">{payload}</script></head></html>'


class TestExtractJsonLdRecipe:
    def test_a_bare_recipe_object(self):
        node = extract_json_ld_recipe(_script('{"@type": "Recipe", "name": "Cake"}'))
        assert node == {"@type": "Recipe", "name": "Cake"}

    def test_a_recipe_nested_in_a_graph(self):
        payload = """
        {"@graph": [
            {"@type": "WebSite", "name": "Example"},
            {"@type": "Recipe", "name": "Cake"}
        ]}
        """
        node = extract_json_ld_recipe(_script(payload))
        assert node is not None
        assert node["name"] == "Cake"

    def test_a_recipe_among_several_top_level_script_tags(self):
        html_text = (
            '<script type="application/ld+json">{"@type": "Organization", "name": "Example"}</script>'
            '<script type="application/ld+json">{"@type": "Recipe", "name": "Cake"}</script>'
        )
        node = extract_json_ld_recipe(html_text)
        assert node is not None
        assert node["name"] == "Cake"

    def test_an_at_type_list_still_matches(self):
        node = extract_json_ld_recipe(_script('{"@type": ["Recipe", "NewsArticle"], "name": "Cake"}'))
        assert node is not None
        assert node["name"] == "Cake"

    def test_malformed_json_in_one_block_does_not_hide_a_valid_one(self):
        html_text = (
            '<script type="application/ld+json">{not valid json</script>'
            '<script type="application/ld+json">{"@type": "Recipe", "name": "Cake"}</script>'
        )
        node = extract_json_ld_recipe(html_text)
        assert node is not None
        assert node["name"] == "Cake"

    def test_no_recipe_anywhere_is_none(self):
        node = extract_json_ld_recipe(_script('{"@type": "Organization", "name": "Example"}'))
        assert node is None

    def test_no_json_ld_at_all_is_none(self):
        assert extract_json_ld_recipe("<html><body>Just a page.</body></html>") is None


class TestDraftFromJsonLd:
    def test_ingredient_lines_are_parsed_for_quantity_and_unit(self):
        node = {
            "@type": "Recipe",
            "name": "Cake",
            "recipeIngredient": ["2 cups plain flour", "1 tsp salt", "vanilla essence"],
        }
        ingredients = draft_from_json_ld(node)["ingredients"]
        assert ingredients[0] == {
            "name": "plain flour",
            "quantity": 2.0,
            "quantity_max": None,
            "unit": "cup",
            "note": None,
            "optional": False,
            "group": None,
            "raw_text": "2 cups plain flour",
        }
        assert ingredients[2]["name"] == "vanilla essence"
        assert ingredients[2]["quantity"] is None

    def test_a_howtostep_list(self):
        node = {
            "@type": "Recipe",
            "name": "Cake",
            "recipeInstructions": [
                {"@type": "HowToStep", "text": "Heat the oven."},
                {"@type": "HowToStep", "text": "Mix and bake."},
            ],
        }
        assert draft_from_json_ld(node)["steps"] == [
            {"text": "Heat the oven."},
            {"text": "Mix and bake."},
        ]

    def test_a_single_newline_separated_instructions_string(self):
        node = {
            "@type": "Recipe",
            "name": "Cake",
            "recipeInstructions": "Heat the oven.\nMix and bake.\n",
        }
        assert draft_from_json_ld(node)["steps"] == [
            {"text": "Heat the oven."},
            {"text": "Mix and bake."},
        ]

    def test_howtosections_nest_their_steps(self):
        node = {
            "@type": "Recipe",
            "name": "Cake",
            "recipeInstructions": [
                {
                    "@type": "HowToSection",
                    "name": "Batter",
                    "itemListElement": [
                        {"@type": "HowToStep", "text": "Mix dry ingredients."},
                        {"@type": "HowToStep", "text": "Fold in eggs."},
                    ],
                },
                {"@type": "HowToStep", "text": "Bake."},
            ],
        }
        assert draft_from_json_ld(node)["steps"] == [
            {"text": "Mix dry ingredients."},
            {"text": "Fold in eggs."},
            {"text": "Bake."},
        ]

    def test_recipe_yield_as_a_bare_number(self):
        draft = draft_from_json_ld({"@type": "Recipe", "name": "Cake", "recipeYield": "8"})
        assert draft["servings"] == 8
        assert draft["servings_note"] is None

    def test_recipe_yield_as_free_text(self):
        draft = draft_from_json_ld(
            {"@type": "Recipe", "name": "Cake", "recipeYield": "Serves 4-6"}
        )
        assert draft["servings"] == 4
        assert draft["servings_note"] == "Serves 4-6"

    def test_recipe_yield_as_a_list(self):
        draft = draft_from_json_ld({"@type": "Recipe", "name": "Cake", "recipeYield": ["8"]})
        assert draft["servings"] == 8

    def test_prep_and_cook_time(self):
        draft = draft_from_json_ld(
            {"@type": "Recipe", "name": "Cake", "prepTime": "PT20M", "cookTime": "PT40M"}
        )
        assert draft["prep_minutes"] == 20
        assert draft["cook_minutes"] == 40

    def test_confidence_is_1_because_this_is_the_pages_own_data(self):
        assert draft_from_json_ld({"@type": "Recipe", "name": "Cake"})["confidence"] == 1.0

    def test_missing_ingredients_is_an_empty_list_not_an_error(self):
        assert draft_from_json_ld({"@type": "Recipe", "name": "Cake"})["ingredients"] == []


class TestHtmlToText:
    def test_strips_script_and_style_blocks(self):
        html_text = "<html><head><style>.a{}</style><script>var x=1;</script></head><body>Cake</body></html>"
        assert html_to_text(html_text) == "Cake"

    def test_breaks_and_paragraphs_become_newlines(self):
        html_text = "<p>Heat the oven.</p><p>Mix and bake.</p>"
        assert html_to_text(html_text) == "Heat the oven.\nMix and bake."

    def test_remaining_tags_are_removed(self):
        assert html_to_text("<div><b>Cake</b> recipe</div>") == "Cake recipe"

    def test_entities_are_unescaped(self):
        assert html_to_text("<p>Salt &amp; pepper</p>") == "Salt & pepper"

    def test_runs_of_blank_lines_are_collapsed(self):
        html_text = "<p>First.</p><br/><br/><br/><p>Second.</p>"
        assert html_to_text(html_text) == "First.\n\nSecond."
