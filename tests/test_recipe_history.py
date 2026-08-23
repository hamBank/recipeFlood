"""Parsing the cooking-history export: forward-filled dates, a source
column that's sometimes a link and sometimes a book reference, and light
name cleaning. See backend/recipe_history.py's module docstring."""

from datetime import date

from backend.recipe_history import (
    classify_source,
    clean_name,
    normalise_url,
    parse_book_ref,
    parse_date,
    parse_rows,
)


class TestParseDate:
    def test_two_digit_year(self):
        assert parse_date("22/8/26") == date(2026, 8, 22)

    def test_four_digit_year(self):
        assert parse_date("04/08/2010") == date(2010, 8, 4)

    def test_single_and_double_digit_forms_both_work(self):
        assert parse_date("1/7/26") == date(2026, 7, 1)
        assert parse_date("09/04/2012") == date(2012, 4, 9)

    def test_junk_values_are_not_dates(self):
        assert parse_date("Lockdown") is None
        assert parse_date("Xmas") is None
        assert parse_date("25/6//20") is None
        assert parse_date("") is None

    def test_a_recipe_name_that_looks_date_shaped_is_not_swallowed(self):
        # Guards the specific failure mode: a row whose "date" cell is
        # actually overflow text must not crash or silently become a date.
        assert parse_date("parmesan crusted eggplant with a cherry tomato salad") is None


class TestCleanName:
    def test_collapses_whitespace(self):
        assert clean_name("braised  kale   with crispy shallots ") == "Braised Kale With Crispy Shallots"

    def test_strips_trailing_question_mark(self):
        # Mixed case ("BBQ" upper, "kebabs" lower) is left alone — only
        # the trailing "?" is stripped.
        assert clean_name("BBQ - kebabs?") == "BBQ - kebabs"

    def test_strips_trailing_plus(self):
        assert clean_name("tempura + asian veg stirfry +") == "Tempura + Asian Veg Stirfry"

    def test_a_mid_string_plus_is_left_alone(self):
        # Not auto-split — a multi-dish entry stays one name for a human
        # to deal with, per the recipe-CSV-import plan.
        name = "corn pakoras with chaat masala + Indian potatoes"
        assert clean_name(name) == name

    def test_all_caps_is_title_cased(self):
        assert clean_name("HERB AND MOZARELLA MUSHROOMS") == "Herb And Mozarella Mushrooms"

    def test_all_lowercase_is_title_cased(self):
        assert clean_name("avo chicken") == "Avo Chicken"

    def test_mixed_case_is_left_alone(self):
        # A leading capital with lowercase after is already a real title;
        # title-casing it again would be a no-op at best.
        name = "Grilled sweet potato tacos with spicy mayo"
        assert clean_name(name) == name

    def test_already_good_title_case_is_unchanged(self):
        assert clean_name("Fennel and orange salad") == "Fennel and orange salad"


class TestNormaliseUrl:
    def test_passes_through_a_clean_url(self):
        url = "https://www.recipetineats.com/asian-slaw/"
        assert normalise_url(url) == url

    def test_adds_a_scheme_to_a_bare_www_link(self):
        assert normalise_url("www.example.com/recipe") == "https://www.example.com/recipe"

    def test_strips_tracking_params(self):
        url = "https://example.com/recipe?utm_source=pinterest&utm_medium=social"
        assert normalise_url(url) == "https://example.com/recipe"

    def test_keeps_a_non_tracking_query_param(self):
        url = "https://example.com/recipe?ref=abc123&servings=4"
        # ref/ref_src are tracking noise; an unrelated param survives.
        assert normalise_url(url) == "https://example.com/recipe?servings=4"

    def test_strips_wprm_recipe_card_fragment(self):
        url = "https://www.loveandlemons.com/black-bean-and-corn-salad/#wprm-recipe-container-58254"
        assert normalise_url(url) == "https://www.loveandlemons.com/black-bean-and-corn-salad/"

    def test_a_book_reference_is_not_a_url(self):
        assert normalise_url("DH dec 2017 p34 issue 90") is None

    def test_free_text_is_not_a_url(self):
        assert normalise_url("add chared corn") is None

    def test_blank_is_not_a_url(self):
        assert normalise_url("") is None


class TestParseBookRef:
    def test_extracts_a_plain_page_number(self):
        assert parse_book_ref("plenty more p133") == ("plenty more", 133)

    def test_extracts_page_with_the_word_spelled_out(self):
        assert parse_book_ref("around the table page 90") == ("around the table", 90)

    def test_trailing_text_after_the_page_number_is_kept(self):
        assert parse_book_ref("DH dec 2017 p34 issue 90") == ("DH dec 2017 issue 90", 34)

    def test_an_ambiguous_page_marker_is_left_in_the_name_rather_than_guessed(self):
        # "p168q" is not a clean page number — could be a typo, could be
        # something else. Safer to leave it as part of the name than guess.
        assert parse_book_ref("ottolenghi simple p168q") == ("ottolenghi simple p168q", None)

    def test_a_bare_number_with_no_page_marker_is_not_extracted(self):
        # No "p"/"page"/"pg" prefix — could be an issue number, a year, a
        # phone extension. Only an explicitly marked page counts.
        assert parse_book_ref("Tonights Dinner 107") == ("Tonights Dinner 107", None)

    def test_blank_is_nothing(self):
        assert parse_book_ref("") == (None, None)
        assert parse_book_ref("   ") == (None, None)


class TestClassifySource:
    def test_url_in_the_source_column(self):
        url, book, page = classify_source("https://example.com/x", "")
        assert (url, book, page) == ("https://example.com/x", "", None)

    def test_url_falls_back_to_the_notes_column(self):
        url, book, page = classify_source(
            "DH dec 2017 p34", "https://thesweetoccasion.com/cherry-apple-crumble/"
        )
        assert url == "https://thesweetoccasion.com/cherry-apple-crumble/"

    def test_a_free_text_note_is_not_mistaken_for_a_citation(self):
        # "add chared corn" in the notes column is a note, not a source —
        # only a URL is ever rescued from that column; parse_book_ref is
        # never applied to it.
        url, book, page = classify_source("", "add chared corn")
        assert url is None
        assert book == ""

    def test_book_reference_when_neither_column_has_a_url(self):
        url, book, page = classify_source("plenty more p133", "")
        assert url is None
        assert (book, page) == ("plenty more", 133)

    def test_a_source_column_url_wins_over_a_notes_column_book_looking_string(self):
        url, book, page = classify_source("https://example.com/x", "p90 somewhere")
        assert url == "https://example.com/x"


class TestParseRows:
    def test_forward_fills_the_date(self):
        rows = [
            ["1/7/26", "First"],
            ["", "Second"],
            ["", "Third"],
        ]
        records = parse_rows(rows)
        assert [r.cook_date for r in records] == [date(2026, 7, 1)] * 3

    def test_a_new_date_takes_over(self):
        rows = [
            ["1/7/26", "First"],
            ["2/7/26", "Second"],
        ]
        records = parse_rows(rows)
        assert records[0].cook_date == date(2026, 7, 1)
        assert records[1].cook_date == date(2026, 7, 2)

    def test_an_unparseable_date_cell_does_not_reset_the_current_date(self):
        rows = [
            ["1/7/26", "First"],
            ["Lockdown", "Second"],
            ["", "Third"],
        ]
        records = parse_rows(rows)
        assert [r.cook_date for r in records] == [date(2026, 7, 1)] * 3

    def test_a_blank_title_row_produces_no_record_and_does_not_break_forward_fill(self):
        rows = [
            ["1/7/26", "First"],
            ["", ""],
            ["", "Second"],
        ]
        records = parse_rows(rows)
        assert [r.name for r in records] == ["First", "Second"]
        assert records[1].cook_date == date(2026, 7, 1)

    def test_short_rows_do_not_crash(self):
        # Real export rows are padded to 22 columns, but parse_rows should
        # not depend on that.
        rows = [["1/7/26", "First"]]
        records = parse_rows(rows)
        assert records[0].name == "First"
        assert records[0].url is None
        assert records[0].book_name is None

    def test_column_4_is_source_and_column_5_is_notes(self):
        row = ["1/7/26", "Cake", "", "", "https://example.com/cake", "double this"]
        records = parse_rows([row])
        assert records[0].url == "https://example.com/cake"

    def test_records_before_any_date_have_no_date(self):
        rows = [["", "Untimed"]]
        assert parse_rows(rows)[0].cook_date is None

    def test_a_realistic_slice_matches_the_expected_shape(self):
        rows = [
            ["22/8/26", "keto chilli", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
            ["", "avo chicken", "", "", "https://www.lowcarbmaven.com/low-carb-keto-chicken-salad-avocado/", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
            ["19/6/25", "spicy tomato and black bean salsa with crispy tortilla", "", "", "DH dec 2017 p34 issue 90", "add chared corn", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ]
        records = parse_rows(rows)
        assert records[0].name == "Keto Chilli"
        assert records[0].cook_date == date(2026, 8, 22)
        assert records[1].url == "https://www.lowcarbmaven.com/low-carb-keto-chicken-salad-avocado/"
        assert records[2].cook_date == date(2025, 6, 19)
        assert records[2].book_name == "DH dec 2017 issue 90"
        assert records[2].book_page == 34
