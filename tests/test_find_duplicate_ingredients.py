"""scripts/find_duplicate_ingredients.py: the rule that sorts near-duplicates
into CONFIDENT (merge), REVIEW (a person decides) and UNCHANGED (kept apart),
and the `Name - Type` renames.

Most cases here are from the household's own report of 2026-11-10, where the
old tiers offered to merge water, sugar and cinnamon into onion (chained
through aliases), frozen spinach into spinach, and dried figs into a ripe fig.
"""

from backend.models import Ingredient, Recipe, RecipeIngredient, ShoppingItem
from scripts.find_duplicate_ingredients import (
    APART,
    CONFIDENT,
    REVIEW,
    apply_renames,
    classify,
    judge,
    merge_groups,
    rename_proposals,
    row_for,
    usage_counts,
)

_ids = iter(range(1, 100_000))


def ing(name, *, aliases=None, prep_terms=None):
    """An unsaved row: the rule is pure, so most tests need no database."""
    return Ingredient(
        id=next(_ids), slug=name.lower().replace(" ", "-"), name=name,
        aliases=aliases or [], prep_terms=prep_terms or [],
    )


def verdict(a, b, *, others=()):
    rows = [row_for(i) for i in (ing(a), ing(b), *(ing(o) for o in others))]
    singles = frozenset(r.core[0] for r in rows if len(r.core) == 1)
    return judge(rows[0], rows[1], singles)


def kind(a, b, **kw):
    v = verdict(a, b, **kw)
    return v.kind if v else None


def make(session, name, *, aliases=None):
    ingredient = Ingredient(slug=name.lower().replace(" ", "-"), name=name, aliases=aliases or [])
    session.add(ingredient)
    session.commit()
    session.refresh(ingredient)
    return ingredient


def use(session, ingredient, times=1):
    recipe = Recipe(slug=f"r-{next(_ids)}", title="R")
    session.add(recipe)
    session.flush()
    for n in range(times):
        session.add(RecipeIngredient(
            recipe_id=recipe.id, position=n, name=ingredient.name, raw_text=ingredient.name,
            ingredient_id=ingredient.id,
        ))
    session.commit()


class TestConfident:
    def test_only_size_or_chopping_differs(self):
        assert kind("onion", "med onion") == CONFIDENT
        assert kind("butter", "butter cubed") == CONFIDENT
        assert kind("banana", "mashed ripe banana") == CONFIDENT

    def test_spelling_case_and_plural(self):
        assert kind("Coriander seed", "coriander seeds") == CONFIDENT
        assert kind("cherry", "cherries") == CONFIDENT

    def test_the_same_thing_under_its_other_name(self):
        assert kind("green bell pepper", "green capsicum") == CONFIDENT
        assert kind("coriander", "cilantro") == CONFIDENT
        assert kind("tinned lentils", "canned lentils") == CONFIDENT

    def test_a_word_the_row_lists_as_its_own_preparation(self):
        lemon = row_for(ing("lemon", prep_terms=["juice"]))
        juice = row_for(ing("lemon juice"))
        assert judge(lemon, juice, frozenset()).kind == CONFIDENT


class TestDifferentProducts:
    """Tinned, frozen, smoked and dried are different ingredients."""

    def test_frozen_spinach_is_not_spinach(self):
        assert kind("spinach", "frozen spinach") == APART

    def test_dried_figs_are_not_a_ripe_fig(self):
        assert kind("ripe fig", "dried figs") == APART

    def test_tinned_and_smoked(self):
        assert kind("tomatoes", "tinned tomatoes") == APART
        assert kind("salmon", "smoked salmon") == APART

    def test_a_form_of_the_thing(self):
        assert kind("yuzu", "yuzu juice") == APART
        assert kind("pear", "pear juice") == APART
        assert kind("chilli sauce", "chilli bean sauce") == APART or kind(
            "chilli sauce", "chilli bean sauce") == REVIEW

    def test_the_last_word_says_what_it_is(self):
        assert kind("cream", "cream cheese") == APART
        assert kind("milk", "milk chocolate easter egg") == APART
        assert kind("egg", "milk chocolate easter egg", others=["milk", "chocolate"]) == APART
        assert kind("museli", "kids museli bars") == APART
        assert kind("yuzu", "yuzu koshō") == APART
        # kecap manis, the sweet soy: not tomato ketchup
        assert kind("ketchup", "ketchup manus") == APART
        assert kind("pork loin", "pork loin chops") == APART
        assert kind("beans", "chilli bean sauce") == APART
        assert kind("cream", "dutch cream potato") == APART

    def test_another_ingredient_in_front_of_cream_or_wine(self):
        assert kind("cream", "coconut cream", others=["coconut"]) == APART
        assert kind("wine", "rice wine", others=["rice"]) == APART


class TestTypes:
    """A type of fruit, vegetable, cream or wine stays its own row, named
    `Name - Type`."""

    def test_kept_apart_from_the_plain_one(self):
        assert kind("eggplant", "japanese eggplant") == APART
        assert kind("pear", "green pear") == APART
        assert kind("cream", "thickened cream") == APART
        assert kind("cream", "sour cream") == APART

    def test_named_name_dash_type(self):
        rows = [ing(n) for n in (
            "green pear", "nashi pear", "beurre bosc pear", "thickened cream",
            "sour cream", "green capsicum", "japanese eggplant", "red wine", "cherry tomato",
        )]
        assert {i.name: new for i, new in rename_proposals(rows)} == {
            "green pear": "Pear - Green",
            "nashi pear": "Pear - Nashi",
            "beurre bosc pear": "Pear - Beurre Bosc",
            "thickened cream": "Cream - Thickened",
            "sour cream": "Cream - Sour",
            "green capsicum": "Capsicum - Green",
            "japanese eggplant": "Eggplant - Japanese",
            "red wine": "Wine - Red",
            "cherry tomato": "Tomato - Cherry",
        }

    def test_what_is_not_a_type(self):
        rows = [ing(n) for n in (
            "coconut", "coconut cream", "cream cheese", "sweet potato", "spring onion",
            "frozen peas", "rind 2 lemons", "stewed rhubarb", "pear", "Pear - Green",
            "ice cream", "red", "baking pears",
        )]
        assert [new for _, new in rename_proposals(rows) if " - " in new] == []

    def test_a_name_dash_type_row_matches_the_words_in_any_order(self):
        assert kind("Pear - Green", "green pears") == CONFIDENT
        assert kind("Capsicum - Green", "green bell pepper") == CONFIDENT

    def test_a_dash_type_is_not_the_plain_one(self):
        assert kind("cheese", "cheese - blue") == REVIEW
        assert kind("pear", "Pear - Green") == APART


class TestTidyNames:
    """The household's corrections of 2026-11-10."""

    def test_amounts_notes_and_packaging_come_off(self):
        rows = [ing(n) for n in (
            "block halloumi", "swiss cheese note 1", "x 5g packets roasted seaweed snack",
            "sheets filo pastry", "handfuls rice", "med onion", "• 2 garlic cloves",
        )]
        assert {i.name: new for i, new in rename_proposals(rows)} == {
            "block halloumi": "halloumi",
            "swiss cheese note 1": "swiss cheese",
            "x 5g packets roasted seaweed snack": "roasted seaweed snack",
            "sheets filo pastry": "filo pastry",
            "handfuls rice": "rice",
            "med onion": "onion",
            "• 2 garlic cloves": "garlic cloves",
        }

    def test_australian_names(self):
        rows = [ing(n) for n in ("bell pepper", "green bell pepper", "steamed buns", "greek yogurt", "cilantro")]
        assert {i.name: new for i, new in rename_proposals(rows)} == {
            "bell pepper": "capsicum",
            "green bell pepper": "Capsicum - Green",
            "steamed buns": "chinese steamed buns",
            "greek yogurt": "greek yoghurt",
            "cilantro": "coriander",
        }

    def test_canned_is_name_dash_canned(self):
        rows = [ing(n) for n in ("tinned tomatoes", "canned chickpeas", "can coconut milk", "Tomatoes - Canned")]
        assert {i.name: new for i, new in rename_proposals(rows)} == {
            "tinned tomatoes": "Tomato - Canned",
            "canned chickpeas": "Chickpea - Canned",
        }

    def test_the_snapshot_s_odd_cases(self):
        rows = [ing(n) for n in (
            "sized orange zest 1 orange", "x 7 g tin anchovies –", "seeded mustard", "1 cup",
            "bibb lettuce green lettuce see note", "basket 4 qt/4 l peach",
            "x 500g jars pitted sweet cherry", "x 395g cans sweetened condensed milk",
        )]
        assert {i.name: new for i, new in rename_proposals(rows)} == {
            "sized orange zest 1 orange": "orange",
            "x 7 g tin anchovies –": "Anchovy - Canned",
            "bibb lettuce green lettuce see note": "bibb lettuce green lettuce",
            "basket 4 qt/4 l peach": "peach",
            "x 500g jars pitted sweet cherry": "jarred sweet cherry",
            "x 395g cans sweetened condensed milk": "Sweetened condensed milk - Canned",
        }

    def test_a_rename_onto_an_existing_name_is_a_merge_not_a_rename(self):
        rows = [ing("warm milk"), ing("milk")]
        assert rename_proposals(rows) == []

    def test_what_a_tidy_name_keeps(self):
        rows = [ing(n) for n in ("cream of tartar", "salt and pepper", "fresh pasta", "shredded coconut")]
        assert rename_proposals(rows) == []

    def test_a_canned_row_matches_every_way_of_saying_it(self, session):
        from backend.recipes_service import find_ingredient

        row = make(session, "tinned tomatoes")
        apply_renames(session, rename_proposals([row]), {"tinned tomatoes"})
        assert row.name == "Tomato - Canned"
        for line in ("canned tomatoes", "tinned tomatoes", "x 400 g tin tomatoes", "Tomatoes - Canned"):
            assert find_ingredient(session, line).id == row.id, line


class TestReview:
    """Where the line isn't clear, a person decides."""

    def test_a_qualifier_the_rule_does_not_know(self):
        assert kind("curry powder", "japanese curry powder") == REVIEW
        assert kind("chili powder", "kashmiri chili powder") == REVIEW
        assert kind("cocoa powder", "dark cocoa powder") == REVIEW
        assert kind("sugar", "caster sugar") == REVIEW
        assert kind("rice", "basmati rice") == REVIEW
        assert kind("rhubarb", "stewed rhubarb") == REVIEW

    def test_firm_is_for_a_person_to_judge(self):
        # Firm tofu is not silken tofu; a firm pear is a pear.
        assert kind("tofu", "firm tofu") == REVIEW
        assert kind("silken tofu", "silken firm tofu") == REVIEW
        assert kind("pear", "firm pear") == REVIEW

    def test_steamed_buns_are_not_buns(self):
        assert kind("buns", "steamed buns") == REVIEW
        assert kind("steamed buns", "chinese steamed buns") == CONFIDENT

    def test_words_that_are_sometimes_how_it_is_sold(self):
        assert kind("coconut", "shredded coconut") == REVIEW
        assert kind("almonds", "slivered almonds") == REVIEW
        assert kind("coriander", "ground coriander") == REVIEW
        assert kind("olive oil", "extra virgin olive oil") == REVIEW

    def test_a_part_of_the_thing(self):
        assert kind("coriander", "coriander leaves") == REVIEW

    def test_unrelated_names_are_not_compared(self):
        assert kind("plain flour", "00 flour") is None
        assert kind("salt", "malt") is None
        assert kind("lime leaf", "lime juice") is None


class TestClassify:
    def test_aliases_never_chain_rows_into_a_merge(self):
        # The report that started this: one alias per row joined onion, water,
        # sugar and cinnamon into one "exact" group.
        rows = [
            ing("onion", aliases=["water"]),
            ing("water", aliases=["sugar"]),
            ing("sugar", aliases=["cinnamon"]),
            ing("cinnamon"),
        ]
        report = classify(rows)
        assert report.confident == []
        assert {(r.name, alias, o.name) for r, alias, o in report.alias_links} == {
            ("onion", "water", "water"), ("water", "sugar", "sugar"), ("sugar", "cinnamon", "cinnamon"),
        }

    def test_groups_are_disjoint_and_only_same_product(self):
        rows = [ing(n) for n in (
            "onion", "onions", "med onion", "red onion", "frozen spinach", "spinach",
            "baby spinach", "cherry", "cherries", "divided",
        )]
        report = classify(rows)
        groups = [sorted(r.name for r in g) for g in report.confident]
        assert sorted(groups) == [["cherries", "cherry"], ["med onion", "onion", "onions"]]
        ids = [r.id for g in report.confident for r in g]
        assert len(ids) == len(set(ids))
        assert [r.name for r in report.no_core] == ["divided"]

    def test_a_prep_term_absorbs_into_the_most_specific_row(self):
        rows = [
            ing("chicken", prep_terms=["fillet"]),
            ing("chicken thigh", prep_terms=["fillet"]),
            ing("chicken thigh fillets"),
        ]
        groups = [sorted(r.name for r in g) for g in classify(rows).confident]
        assert groups == [["chicken thigh", "chicken thigh fillets"]]

    def test_two_rows_whose_prep_terms_tie_go_to_review(self):
        rows = [
            ing("lemon", prep_terms=["juice"]),
            ing("Lemon", prep_terms=["juice"]),
            ing("lemon juice"),
        ]
        report = classify(rows)
        # The two lemons are one group; lemon juice is explained by that group.
        assert sorted(sorted(r.name for r in g) for g in report.confident) == [
            ["Lemon", "lemon", "lemon juice"],
        ]


class TestGroupNames:
    """The name a merged group ends up with, which the report shows, so the
    CONFIDENT list never reads as if "handful kalamata olive" will stay.
    The household's corrections of 2026-11-10."""

    def name_of(self, *names):
        from scripts.find_duplicate_ingredients import group_name

        return group_name([row_for(ing(n)) for n in names])

    def test_amounts_and_notes_never_survive_a_merge(self):
        assert self.name_of("x 250g blocks halloumi thickly", "block halloumi about 16 slice") == "halloumi"
        assert self.name_of("basket 4 qt/4 l peache", "peach") == "peach"
        assert self.name_of('sheets 22cm/8.5" round rice paper note 1', "rice paper round") == "rice paper round"
        assert self.name_of("handfuls rice 500 600g", "handfuls rice") == "rice"
        assert self.name_of("swiss cheese note 1", "swiss cheese") == "swiss cheese"
        assert self.name_of("sheets filo pastry", "packet filo pastry") == "filo pastry"

    def test_australian_names_and_types(self):
        assert self.name_of("green bell pepper", "green capsicum") == "Capsicum - Green"
        assert self.name_of("bell pepper", "bell peppers") == "capsicum"
        assert self.name_of("handful kalamata olive", "kalamata olives") == "Olive - Kalamata"

    def test_canned_groups_are_name_dash_canned(self):
        assert self.name_of("canned chickpeas", "tinned chickpeas", "x 400 g tin chickpeas") == "Chickpea - Canned"


class TestMerging:
    def test_keeps_the_most_used_row_and_repoints_everything(self, session):
        onion = make(session, "onion")
        med = make(session, "med onion")
        use(session, med, 3)
        use(session, onion, 1)
        item = ShoppingItem(name="onion", ingredient_id=onion.id)
        session.add(item)
        session.commit()

        merged = merge_groups(session, classify([onion, med]).confident, usage_counts(session))

        assert merged == 1
        assert session.get(Ingredient, onion.id) is None
        kept = session.get(Ingredient, med.id)
        # The busier row is kept, but takes the plainer name.
        assert kept.name == "onion"
        assert "med onion" in kept.aliases
        session.refresh(item)
        assert item.ingredient_id == med.id

    def test_never_merges_review_or_unchanged(self, session):
        rows = [make(session, n) for n in ("spinach", "frozen spinach", "sugar", "caster sugar")]
        report = classify(rows)
        assert merge_groups(session, report.confident, usage_counts(session)) == 0
        assert all(session.get(Ingredient, r.id) for r in rows)


class TestRenaming:
    def test_keeps_the_old_name_as_an_alias_and_the_slug(self, session):
        pear = make(session, "green pear")
        renamed, skipped = apply_renames(session, rename_proposals([pear]), {"green pear"})
        session.refresh(pear)
        assert (renamed, skipped) == (1, [])
        assert pear.name == "Pear - Green"
        assert pear.slug == "green-pear"
        assert "green pear" in pear.aliases

    def test_skips_a_name_another_row_has(self, session):
        pear = make(session, "green pear")
        renamed, skipped = apply_renames(
            session, rename_proposals([pear]), {"green pear", "pear - green"}
        )
        assert renamed == 0 and skipped[0][1] == "Pear - Green"

    def test_the_renamed_row_still_matches_recipe_lines(self, session):
        from backend.recipes_service import find_ingredient

        pear = make(session, "green pear")
        apply_renames(session, rename_proposals([pear]), {"green pear"})
        assert find_ingredient(session, "2 green pears, sliced").id == pear.id
        assert find_ingredient(session, "Pear - Green").id == pear.id


class TestUsageCounts:
    def test_counts_only_linked_recipe_lines(self, session):
        egg = make(session, "egg")
        use(session, egg, 2)
        assert usage_counts(session) == {egg.id: 2}


class TestTheHouseholdsSecondReview:
    """2026-11-10, second pass over the production report."""

    def test_the_rule_now_merges_these_on_its_own(self):
        for a, b in [
            ("almond milk", "unsweetened almond milk"),
            ("baguette", "costco baguette"),
            ("beef", "beef preferably wagyu but any braising beef"),
            ("black pepper", "cracked black pepper"),
            ("black pepper", "few turns cracked black pepper"),
            ("scallion /shallot", "shallots / scallion"),
            ("spring onion", "shallots / scallion"),
        ]:
            assert kind(a, b) == CONFIDENT, (a, b)

    def test_alternatives_collapse_to_the_australian_name(self):
        from scripts.find_duplicate_ingredients import group_name

        group = [row_for(ing(n)) for n in ("scallion /shallot", "shallots / scallion")]
        assert group_name(group) == "spring onion"

    def test_what_only_a_person_can_decide(self):
        # "black" is not preparation in general (black pepper is not pepper),
        # and the banana line is prose: these merge only because the
        # household said so, in data/pantry_decisions.json.
        assert kind("aleppo pepper", "black aleppo pepper") == REVIEW
        rows = [ing("aleppo pepper"), ing("black aleppo pepper"), ing("banana"),
                ing("depending on liquid content your banana")]
        decisions = [("aleppo pepper", "black aleppo pepper"),
                     ("Banana", "depending on liquid content your banana")]
        report = classify(rows, decisions)
        assert sorted(sorted(r.name for r in g) for g in report.confident) == [
            ["aleppo pepper", "black aleppo pepper"],
            ["banana", "depending on liquid content your banana"],
        ]
        assert report.review == []

    def test_a_decision_finds_a_row_by_its_old_name(self):
        renamed = ing("halloumi", aliases=["block halloumi"])
        other = ing("x 250g blocks haloumi")
        report = classify([renamed, other], [("block halloumi", "x 250g blocks haloumi")])
        assert [sorted(r.name for r in g) for g in report.confident] == [["halloumi", "x 250g blocks haloumi"]]

    def test_a_decision_naming_nothing_changes_nothing(self):
        rows = [ing("onion"), ing("water")]
        assert classify(rows, [("unicorn", "rainbow")]).confident == []

    def test_the_shipped_decisions_file_loads(self):
        from scripts.find_duplicate_ingredients import DECISIONS, load_decisions

        pairs = load_decisions(DECISIONS)
        assert ("aleppo pepper", "black aleppo pepper") in pairs
        assert all(len(p) == 2 for p in pairs)
