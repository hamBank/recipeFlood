"""backend/ingredient_names.py: pulling a name apart.

The cases are real ingredient lines from the blog snapshot (data/recipes.heuristic.json),
as they look after `units.parse_amount` has taken the leading amount off.
"""
import pytest

from backend.ingredient_names import (
    clean_name,
    entry_for,
    explain,
    join_notes,
    merge_key,
    normalise_ingredient_name,
    prep_extras,
    prep_match,
)
from backend.models import Ingredient, MeasureUnit


class TestBrackets:
    @pytest.mark.parametrize(
        "raw, display, note",
        [
            ("kecap manis (or dark chinese soy)", "kecap manis", "or dark chinese soy"),
            ("cornstarch (corn flour)", "cornstarch", "corn flour"),
            ("Packet of Marie biscuits (crushed)", "Marie biscuits", "crushed"),
            ("butter (4oz)", "butter", "4oz"),
            ("warm water (110 degrees F/45 degrees C)", "warm water", "110 degrees F/45 degrees C"),
            ("Chocolate cake (see recipe  below)", "Chocolate cake", "see recipe below"),
        ],
    )
    def test_brackets_come_out_of_the_name_and_into_the_note(self, raw, display, note):
        cleaned = clean_name(raw)
        assert cleaned.display == display
        assert note.replace("  ", " ") in [n.replace("  ", " ") for n in cleaned.notes] or note in " ".join(cleaned.notes)

    def test_an_unclosed_bracket_runs_to_the_end(self):
        cleaned = clean_name("Bibb lettuce or green leaf lettuce (see  Note")
        assert cleaned.display == "Bibb lettuce or green leaf lettuce"
        assert "see Note" in " ".join(cleaned.notes).replace("  ", " ")

    def test_nested_brackets(self):
        assert clean_name("stock (chicken (low salt))").display == "stock"

    def test_a_synonym_in_brackets_does_not_pollute_the_key(self):
        # The old key was "kecap manis dark chinese soy": a name nobody has.
        assert normalise_ingredient_name("kecap manis (or dark chinese soy)") == "kecap manis"
        assert normalise_ingredient_name("cornstarch (corn flour)") == "cornstarch"


class TestInstructionsAfterTheName:
    @pytest.mark.parametrize(
        "raw, display",
        [
            ("onion, finely chopped", "onion"),
            ("gingerroot; fresh grated", "gingerroot"),
            ("anchovies – drained, blotted of excess oil and chopped", "anchovies"),
            ("spinach - washed", "spinach"),
        ],
    )
    def test_the_tail_goes_to_the_note(self, raw, display):
        cleaned = clean_name(raw)
        assert cleaned.display == display
        assert cleaned.notes

    def test_a_hyphen_inside_a_word_is_not_a_tail(self):
        assert clean_name("self-raising flour").display == "self-raising flour"
        assert clean_name("flat-leaf parsley").display == "flat-leaf parsley"


class TestQuantitiesInTheName:
    @pytest.mark.parametrize(
        "raw, display, measure",
        [
            ("sugar 250 mL", "sugar", "250 mL"),
            ("water 500 mL", "water", "500 mL"),
            ("whole cloves 5 mL", "whole cloves", "5 mL"),
            ("cinnamon stick 20 cm", "cinnamon stick", "20 cm"),
            ("250ml water", "water", "250ml"),
            ("flour 500g", "flour", "500g"),
        ],
    )
    def test_a_measured_quantity_is_taken_out_and_kept(self, raw, display, measure):
        cleaned = clean_name(raw)
        assert cleaned.display == display
        assert [m.text for m in cleaned.measures] == [measure]
        assert measure in cleaned.notes

    def test_the_measure_is_parsed(self):
        (m,) = clean_name("sugar 250 mL").measures
        assert (m.quantity, m.unit) == (250.0, MeasureUnit.ml)
        (m,) = clean_name("anchovies 1.5 kg").measures
        assert (m.quantity, m.unit) == (1.5, MeasureUnit.kg)

    def test_a_pack_size_and_its_container_are_not_the_product(self):
        # "1 x 7 g tin anchovies – drained": parse_amount took the 1.
        cleaned = clean_name("x 7 g tin anchovies – drained, blotted of excess oil and chopped")
        assert cleaned.display == "anchovies"
        assert cleaned.pack is True
        assert "7 g" in cleaned.notes and "tin" in cleaned.notes
        cleaned = clean_name("x 400ml cans coconut milk")
        assert cleaned.display == "coconut milk"

    def test_a_container_on_its_own_is_part_of_the_name(self):
        # "jar garlic" is a different purchase from "garlic".
        assert clean_name("jar garlic").display == "jar garlic"
        assert clean_name("can condensed milk").display == "can condensed milk"

    def test_a_container_before_of_is_dropped(self):
        assert clean_name("Packet of Marie biscuits").display == "Marie biscuits"

    def test_a_number_that_is_part_of_the_name_stays(self):
        assert clean_name("00 flour").display == "00 flour"
        assert "00" in clean_name("00 flour").key
        assert clean_name("chinese 5 spice").counts == (5.0,)

    def test_a_bare_count_is_reported_and_can_be_left_out(self):
        cleaned = clean_name("Zest and juice 2 lemons")
        assert cleaned.counts == (2.0,)
        assert cleaned.display_no_counts == "Zest and juice lemons"
        assert cleaned.display == "Zest and juice 2 lemons"
        assert cleaned.key_words == ("zest", "juice", "lemons")

    def test_a_range_is_not_a_count(self):
        assert clean_name("1 to 1.5 cups coarse breadcrumbs").measures[0].text.endswith("cups")


class TestTheMatchKey:
    @pytest.mark.parametrize(
        "raw, key",
        [
            ("finely chopped fresh flat-leaf parsley", "parsley"),
            ("Large Eggs", "egg"),
            ("ripe bananas, mashed", "banana"),
            ("very ripe large bananas", "banana"),
            ("freshly ground black pepper", "black pepper"),
            ("sifted icing sugar", "icing sugar"),
            ("sugar 250 ml", "sugar"),
            ("olive oil 3 tbsp", "olive oil"),
            ("cress", "cress"),
            ("hummus", "hummus"),
        ],
    )
    def test_the_key(self, raw, key):
        assert normalise_ingredient_name(raw) == key

    def test_a_name_made_only_of_noise_keeps_its_words(self):
        assert normalise_ingredient_name("fresh") == "fresh"

    def test_the_key_of_a_name_with_no_quantity_is_what_it_always_was(self):
        # Existing pantry slugs were minted from this; plain names must not move.
        for name in ("plain flour", "brown onion", "pine nuts", "coconut milk", "spring onions"):
            old = name.split(",")[0].lower().replace("-", " ")
            assert normalise_ingredient_name(name).split()[:-1] == old.split()[:-1]


class TestNotes:
    def test_notes_are_joined_without_repeats(self):
        assert join_notes("finely chopped", "Finely chopped; 250 mL", None, "") == "finely chopped; 250 mL"

    def test_nothing_to_join(self):
        assert join_notes(None, "") is None


def _ing(name, *, aliases=(), prep=(), id=1):
    return Ingredient(id=id, slug=name.replace(" ", "-"), name=name, aliases=list(aliases), prep_terms=list(prep))


class TestPrepMatch:
    """A line belongs to a pantry row when everything it says beyond the
    row's own name is something the row lists as preparation."""

    def test_extra_words_that_the_row_lists_are_prep(self):
        thigh = entry_for(_ing("chicken thigh", prep=["boneless", "skinless", "fillet"]))
        words = clean_name("boneless skinless chicken thigh fillets").key_words
        assert prep_match(words, [thigh]) == 1

    def test_an_extra_word_the_row_does_not_list_blocks_the_match(self):
        thigh = entry_for(_ing("chicken thigh", prep=["boneless"]))
        assert prep_match(clean_name("smoked chicken thigh").key_words, [thigh]) is None

    def test_a_row_with_no_prep_terms_never_matches_extra_words(self):
        assert prep_match(clean_name("juice lemon").key_words, [entry_for(_ing("lemon"))]) is None

    def test_juice_and_zest_of_a_lemon(self):
        lemon = entry_for(_ing("lemon", prep=["juice", "zest", "rind"]))
        for raw in ("juice 1 lemon", "Zest and juice 2 lemons", "rind lemon", "lemon juice, fresh"):
            assert prep_match(clean_name(raw).key_words, [lemon]) == 1, raw

    def test_a_prep_word_is_only_prep_where_the_row_says_so(self):
        # "shredded" is not noise everywhere ("shredded cheese" is a product),
        # so lemon has to list it before "shredded rind lemon" is a lemon.
        words = clean_name("shredded rind 1 lemon").key_words
        assert prep_match(words, [entry_for(_ing("lemon", prep=["juice", "zest", "rind"]))]) is None
        assert prep_match(words, [entry_for(_ing("lemon", prep=["rind", "shredded"]))]) == 1

    def test_the_more_specific_row_wins(self):
        chicken = entry_for(_ing("chicken", prep=["thigh", "fillet"], id=1))
        thigh = entry_for(_ing("chicken thigh", prep=["fillet"], id=2))
        assert prep_match(clean_name("chicken thigh fillet").key_words, [chicken, thigh]) == 2

    def test_two_equally_specific_rows_are_a_tie_not_a_guess(self):
        a = entry_for(_ing("lemon", prep=["juice"], id=1))
        b = entry_for(_ing("lemon", prep=["juice"], id=2))
        assert prep_match(clean_name("lemon juice").key_words, [a, b]) is None

    def test_an_alias_counts_as_the_name(self):
        coriander = entry_for(_ing("coriander", aliases=["cilantro"], prep=["leaves", "stalks"]))
        assert prep_match(clean_name("cilantro leaves").key_words, [coriander]) == 1

    def test_plurals_match_either_way(self):
        garlic = entry_for(_ing("garlic", prep=["clove"]))
        assert prep_match(clean_name("garlic cloves").key_words, [garlic]) == 1
        clove = entry_for(_ing("garlic", prep=["cloves"]))
        assert prep_match(clean_name("garlic clove").key_words, [clove]) == 1

    def test_word_order_does_not_matter(self):
        oil = entry_for(_ing("olive oil", prep=["extra", "virgin"]))
        assert prep_match(clean_name("virgin olive oil").key_words, [oil]) == 1

    def test_the_extras_are_reported(self):
        thigh = entry_for(_ing("chicken thigh", prep=["boneless", "fillet"]))
        words = clean_name("boneless chicken thigh fillets").key_words
        assert prep_extras(words, thigh) == ["boneless", "fillets"]

    def test_nothing_to_match(self):
        assert prep_match((), [entry_for(_ing("lemon", prep=["juice"]))]) is None


class TestExplainAndMergeKey:
    def test_explain_gives_the_words_for_the_note(self):
        lemon = _ing("lemon", prep=["juice", "zest"])
        assert explain(clean_name("Zest and juice 2 lemons"), lemon) == ["Zest", "juice"]

    def test_explain_is_none_when_the_pantry_row_cannot_account_for_it(self):
        lemon = _ing("lemon", prep=["juice"])
        assert explain(clean_name("smoked lemon"), lemon) is None
        assert explain(clean_name("juice lemon"), _ing("lemon")) is None  # no terms at all

    def test_prep_extras_says_no_rather_than_guess(self):
        thigh = entry_for(_ing("chicken thigh", prep=["boneless"]))
        assert prep_extras(clean_name("smoked chicken thigh").key_words, thigh) is None

    def test_the_merge_key_ignores_case_punctuation_plurals_and_brackets(self):
        keys = {merge_key(n) for n in ("Red Onions (finely chopped)", "red onion.", "RED ONION, diced")}
        assert keys == {"red onion"}

    def test_the_merge_key_is_not_the_match_key(self):
        # "frozen peas" and "peas" are different purchases even though the
        # pantry may file both under "peas".
        assert merge_key("frozen peas") != merge_key("peas")
        assert normalise_ingredient_name("frozen peas") == normalise_ingredient_name("peas")
