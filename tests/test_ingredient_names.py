"""backend/ingredient_names.py: pulling a name apart.

The cases are real ingredient lines from the blog snapshot (data/recipes.heuristic.json),
as they look after `units.parse_amount` has taken the leading amount off.
"""
import pytest

from backend.ingredient_names import (
    clean_name,
    entry_for,
    explain,
    fold_word,
    join_notes,
    legacy_key,
    match_key,
    merge_key,
    normalise_ingredient_name,
    prep_extras,
    prep_match,
    repair,
    singular,
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
        # Cornstarch is cornflour here: the shop's name wins (SYNONYMS).
        assert normalise_ingredient_name("cornstarch (corn flour)") == "cornflour"


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
        # Brackets and instructions go from both, but the merge key keeps
        # noise words the match key drops.
        assert merge_key("frozen peas") != merge_key("peas")
        assert merge_key("organic peas") != merge_key("peas")
        assert normalise_ingredient_name("organic peas") == normalise_ingredient_name("peas")


class TestPlurals:
    """`singular` names things, `repair` undoes what the original rule did to
    singulars already stored, `fold_word` makes every spelling comparable."""

    @pytest.mark.parametrize(
        "plural, word",
        [
            ("tomatoes", "tomato"), ("potatoes", "potato"), ("mangoes", "mango"),
            ("cherries", "cherry"), ("raspberries", "raspberry"), ("anchovies", "anchovy"),
            ("leaves", "leaf"), ("halves", "half"), ("loaves", "loaf"),
            ("peaches", "peach"), ("radishes", "radish"), ("boxes", "box"), ("glasses", "glass"),
            ("chillies", "chilli"), ("onions", "onion"), ("eggs", "egg"), ("peas", "pea"),
            ("oats", "oat"), ("olives", "olive"), ("cloves", "clove"),
            ("cookies", "cookie"), ("brownies", "brownie"), ("shoes", "shoe"), ("quiches", "quiche"),
        ],
    )
    def test_singular(self, plural, word):
        assert singular(plural) == word

    @pytest.mark.parametrize(
        "word", ["molasses", "asparagus", "hummus", "couscous", "cress", "watercress", "lemongrass", "swiss", "grass"]
    )
    def test_words_that_end_in_s_but_are_singular_are_left_alone(self, word):
        assert singular(word) == word

    @pytest.mark.parametrize("word", ["tomato", "cherry", "leaf", "egg", "rice", "brie", "pie", "oat"])
    def test_a_singular_is_unchanged(self, word):
        assert singular(word) == word

    @pytest.mark.parametrize(
        "mangled, word",
        [
            ("tomatoe", "tomato"), ("potatoe", "potato"), ("mangoe", "mango"),
            ("cherrie", "cherry"), ("raspberrie", "raspberry"), ("blueberrie", "blueberry"),
            ("anchovie", "anchovy"), ("peache", "peach"), ("radishe", "radish"), ("pinche", "pinch"),
            ("leave", "leaf"), ("halve", "half"), ("molasse", "molasses"), ("chillie", "chilli"),
        ],
    )
    def test_repair_undoes_the_original_rule(self, mangled, word):
        assert repair(mangled) == word

    @pytest.mark.parametrize(
        "word", ["cookie", "brownie", "smoothie", "shoe", "canoe", "quiche", "brioche", "mousse", "brie"]
    )
    def test_repair_leaves_real_words_that_merely_look_mangled(self, word):
        assert repair(word) == word

    @pytest.mark.parametrize(
        "forms",
        [
            ("tomato", "tomatoes", "tomatoe"),
            ("cherry", "cherries", "cherrie"),
            ("leaf", "leaves", "leave"),
            ("peach", "peaches", "peache"),
            ("mango", "mangoes", "mangoe"),
            ("chilli", "chillies", "chillie", "chilly"),
            ("molasses", "molasse"),
            ("cookie", "cookies"),
            ("quiche", "quiches"),
            ("egg", "eggs"),
        ],
    )
    def test_every_spelling_of_a_word_folds_to_one_string(self, forms):
        assert len({fold_word(f) for f in forms}) == 1, forms

    @pytest.mark.parametrize(
        "a, b",
        [("pea", "pear"), ("pea", "peach"), ("rice", "rich"), ("oat", "oath"), ("tomato", "potato"),
         ("clove", "cloth"), ("leaf", "lead"), ("mint", "mince"), ("cherry", "cheese")],
    )
    def test_different_words_stay_different(self, a, b):
        assert fold_word(a) != fold_word(b)

    def test_the_original_rule_is_still_what_the_legacy_key_uses(self):
        # Pantry slugs were minted with it; slug lookup still tries it.
        assert legacy_key("2 tomatoes") == "2 tomatoe"
        assert legacy_key("cherries") == "cherrie"
        assert normalise_ingredient_name("cherries") == "cherry"

    def test_the_match_key_is_one_string_for_every_spelling_of_an_ingredient(self):
        keys = {match_key(n) for n in ("Tomatoes, diced", "tomato", "tomatoe", "fresh tomatoes")}
        assert keys == {"tomato"}

    def test_prep_terms_match_through_the_fold(self):
        # The row is named "bay leaf": the line "bay leaves" is that name, folded.
        bay = entry_for(_ing("bay leaf", prep=["dried"]))
        assert prep_match(clean_name("bay leaves").key_words, [bay]) == 1
        assert prep_match(clean_name("bay leaf").key_words, [bay]) == 1
        # ...and it is not the bay *tree*: "bay" alone is a different row.
        assert prep_match(clean_name("bay").key_words, [bay]) is None
        parsley = entry_for(_ing("parsley", prep=["leaf"]))
        assert prep_match(clean_name("parsley leaves").key_words, [parsley]) == 1


class TestLeaf:
    """"leaf" used to be blanket noise (for "flat leaf parsley"), which made
    "lime leaf" the same as "lime" and "curry leaf" the same as "curry"."""

    @pytest.mark.parametrize("raw", ["flat leaf parsley", "flat-leaf parsley", "finely chopped flat-leaf parsley"])
    def test_flat_leaf_is_still_dropped_from_parsley(self, raw):
        assert normalise_ingredient_name(raw) == "parsley"

    @pytest.mark.parametrize(
        "leaf, fruit",
        [("lime leaf", "lime"), ("lime leaves", "lime"), ("kaffir lime leaves", "kaffir lime"),
         ("curry leaves", "curry"), ("banana leaf", "banana"), ("bay leaf", "bay")],
    )
    def test_a_leaf_is_not_the_thing_it_comes_from(self, leaf, fruit):
        assert match_key(leaf) != match_key(fruit)

    def test_every_spelling_of_leaf_behaves_alike(self):
        assert len({match_key(n) for n in ("oregano leaf", "oregano leaves", "oregano leave")}) == 1

    def test_the_original_rule_still_finds_what_it_found(self):
        # find_ingredient tries legacy_key too, so a "basil leaf" line still
        # reaches a "basil" row by slug, exactly as before.
        assert legacy_key("basil leaf") == "basil"

    def test_a_herb_that_lists_leaf_as_prep_still_matches_its_leaves(self):
        basil = entry_for(_ing("basil", prep=["leaves"]))
        for raw in ("basil leaf", "basil leaves", "basil leave"):
            assert prep_match(clean_name(raw).key_words, [basil]) == 1, raw


class TestNameDashType:
    """The pantry names types "Pear - Green"; a dash before an instruction is
    still a note."""

    def test_a_type_after_a_dash_is_part_of_the_key(self):
        assert normalise_ingredient_name("Pear - Green") == normalise_ingredient_name("green pears")
        assert normalise_ingredient_name("Cream - Thickened") == "thickened cream"
        assert clean_name("Pear - Beurre Bosc").display == "Pear - Beurre Bosc"

    def test_an_instruction_after_a_dash_is_a_note(self):
        for line, key in [
            ("onion - finely chopped", "onion"),
            ("basil - to serve", "basil"),
            ("tomatoes - see note", "tomato"),
            ("all-purpose flour - sift before measuring", "plain flour"),
            ("butter - softened", "butter"),
        ]:
            assert normalise_ingredient_name(line) == key, line

    def test_a_type_is_not_the_plain_ingredient(self):
        assert normalise_ingredient_name("cheese - blue") != normalise_ingredient_name("cheese")


class TestProductsAndSynonyms:
    def test_frozen_and_dried_are_part_of_the_name(self):
        assert normalise_ingredient_name("frozen spinach") == "frozen spinach"
        assert normalise_ingredient_name("dried figs") == "dried fig"

    def test_a_tin_makes_it_canned(self):
        # "Canned" is the household's word; tinned and a tin are the same.
        for line in ("x 400 g tin tomatoes", "canned tomatoes", "tinned tomatoes", "Tomatoes - Canned"):
            assert normalise_ingredient_name(line) == "canned tomato", line

    def test_the_shop_name_wins(self):
        assert normalise_ingredient_name("green bell peppers") == "green capsicum"
        assert normalise_ingredient_name("cilantro") == "coriander"
        assert normalise_ingredient_name("chili powder") == normalise_ingredient_name("chilli powder")


class TestAmountsInTheName:
    """A pantry name minted from a recipe line can carry how much: those words
    go to the note, not the name."""

    def test_leading_amount_and_packaging_words(self):
        for line, name in [
            ("block halloumi", "halloumi"),
            ("sheets filo pastry", "filo pastry"),
            ("handfuls rice", "rice"),
            ("x 5g packets roasted seaweed snack", "roasted seaweed snack"),
            ("bunch coriander", "coriander"),
        ]:
            assert clean_name(line).display == name, line

    def test_a_word_alone_is_still_the_name(self):
        assert clean_name("pinch").display == "pinch"
        assert clean_name("cloves").display == "cloves"

    def test_a_jar_is_still_part_of_the_name(self):
        assert normalise_ingredient_name("jar garlic") == "jar garlic"

    def test_a_note_pointer_is_not_the_name(self):
        assert clean_name("swiss cheese note 1").display == "swiss cheese"
        assert "note 1" in clean_name("swiss cheese note 1").notes
        assert clean_name("salt (see note)").display == "salt"


class TestAustralianNames:
    def test_the_australian_name_wins(self):
        for us, au in [
            ("all-purpose flour", "plain flour"),
            ("powdered sugar", "icing sugar"),
            ("baking soda", "bicarb soda"),
            ("ground beef", "beef mince"),
            ("shrimp", "prawn"),
            ("greek yogurt", "greek yoghurt"),
            ("scallions", "spring onion"),
        ]:
            assert normalise_ingredient_name(us) == normalise_ingredient_name(au), us

    def test_steamed_buns_are_chinese_steamed_buns(self):
        assert normalise_ingredient_name("steamed buns") == "chinese steamed bun"
        assert normalise_ingredient_name("chinese steamed buns") == "chinese steamed bun"
