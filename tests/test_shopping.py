"""The shopping list: merging, grouping, pricing and checking off.

The tests that matter here are the ones about what *doesn't* merge. A
shopping list that silently combines two things that aren't the same
sends you home with the wrong amount of food, and that failure is invisible
until you're already cooking.
"""

import pytest

from backend.models import Ingredient, IngredientSource, MeasureUnit, ShoppingItem
from backend.shopping import SHOP_ORDER, amount_text, shop_sort_key


@pytest.fixture
def onion(session):
    """A pantry onion with a piece weight, so "2 onions" becomes grams."""
    ingredient = Ingredient(
        slug="brown-onion",
        name="brown onion",
        aliases=["onion", "onions"],
        grams_per_piece=150,
        cost_per_kg_cents=400,  # $4/kg
        source=IngredientSource.markets,
    )
    session.add(ingredient)
    session.commit()
    session.refresh(ingredient)
    return ingredient


@pytest.fixture
def parsley(session):
    """Bought by the bunch, and the pantry has never been told what a
    bunch weighs — the honest "can't price this" case."""
    ingredient = Ingredient(
        slug="parsley",
        name="parsley",
        source=IngredientSource.markets,
    )
    session.add(ingredient)
    session.commit()
    session.refresh(ingredient)
    return ingredient


@pytest.fixture
def milk(session):
    """Sold and shelf-priced by the litre, no density set — the case
    volume merging exists for."""
    from backend.models import MeasureKind

    ingredient = Ingredient(
        slug="milk",
        name="milk",
        measure_kind=MeasureKind.volume,
        cost_per_litre_cents=200,  # $2/L
        source=IngredientSource.supermarket,
    )
    session.add(ingredient)
    session.commit()
    session.refresh(ingredient)
    return ingredient


def make_recipe(client, title, ingredients, **extra):
    response = client.post(
        "/recipes",
        json={"title": title, "ingredients": ingredients, "steps": [], **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def make_list(client, recipes, **extra):
    response = client.post(
        "/cook-lists",
        json={"recipes": [{"recipe_id": r["id"]} for r in recipes], **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestPrivacy:
    def test_both_routers_need_a_signed_in_user(self, guest_client):
        assert guest_client.get("/shopping").status_code == 401
        assert guest_client.post("/shopping", json={"name": "milk"}).status_code == 401
        assert guest_client.get("/cook-lists").status_code == 401
        assert guest_client.post("/cook-lists", json={}).status_code == 401


class TestMerging:
    def test_the_same_ingredient_in_two_recipes_becomes_one_line(
        self, client, onion, flour
    ):
        a = make_recipe(client, "Soup", [{"name": "onion", "quantity": 2, "unit": "piece"}])
        b = make_recipe(client, "Stew", [{"name": "onion", "quantity": 1, "unit": "piece"}])
        cook_list = make_list(client, [a, b])

        result = client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping").json()
        assert result["added"] == 1
        assert result["merged"] == 1

        items = client.get("/shopping").json()["items"]
        assert len(items) == 1
        assert items[0]["weight_grams"] == pytest.approx(450)  # 3 x 150g
        assert items[0]["amount_text"] == "450 g"

    def test_a_merged_line_records_which_recipe_wanted_what(self, client, onion):
        a = make_recipe(client, "Soup", [{"name": "onion", "quantity": 2, "unit": "piece"}])
        b = make_recipe(client, "Stew", [{"name": "onion", "quantity": 1, "unit": "piece"}])
        cook_list = make_list(client, [a, b])
        client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping")

        contributions = client.get("/shopping").json()["items"][0]["contributions"]
        assert [c["recipe"] for c in contributions] == ["Soup", "Stew"]

    def test_unlinked_lines_never_merge_even_with_identical_text(self, client):
        """Deleting a pantry row leaves its recipe lines linked to nothing
        (see ingredients.delete_ingredient). Two such lines look identical
        and are still not evidence of the same purchase — nothing has
        confirmed they are one item rather than two similarly named ones."""
        a = make_recipe(
            client, "One", [{"name": "mystery spice blend", "quantity": 1, "unit": "tsp"}]
        )
        b = make_recipe(
            client, "Two", [{"name": "mystery spice blend", "quantity": 2, "unit": "tsp"}]
        )
        assert client.delete("/ingredients/mystery-spice-blend").status_code == 204

        cook_list = make_list(client, [a, b])
        client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping")

        items = client.get("/shopping").json()["items"]
        assert len(items) == 2
        assert all(i["ingredient_id"] is None for i in items)

    def test_the_same_ingredient_in_the_same_unit_adds_up(self, client, parsley):
        """No weight either side, but "1 bunch" plus "2 bunch" is still
        arithmetic we can do honestly."""
        a = make_recipe(client, "One", [{"name": "parsley", "quantity": 1, "unit": "bunch"}])
        b = make_recipe(client, "Two", [{"name": "parsley", "quantity": 2, "unit": "bunch"}])
        cook_list = make_list(client, [a, b])
        client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping")

        items = client.get("/shopping").json()["items"]
        assert len(items) == 1
        assert items[0]["amount_text"] == "3 bunch"

    def test_a_weightless_line_stays_separate_from_a_weighed_one(
        self, client, parsley
    ):
        """Folding "1 bunch" into 250g would mean inventing a bunch weight
        the pantry has never been told, and the total would quietly be
        missing some of the food."""
        a = make_recipe(client, "Soup", [{"name": "parsley", "quantity": 250, "unit": "g"}])
        b = make_recipe(client, "Salad", [{"name": "parsley", "quantity": 1, "unit": "bunch"}])
        cook_list = make_list(client, [a, b])
        client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping")

        items = client.get("/shopping").json()["items"]
        assert len(items) == 2
        assert sorted(i["amount_text"] for i in items) == ["1 bunch", "250 g"]

    def test_a_checked_item_is_not_merged_into(self, client, onion):
        """Adding to something already in the trolley would reopen it
        silently, and the shopper would walk straight past."""
        a = make_recipe(client, "Soup", [{"name": "onion", "quantity": 2, "unit": "piece"}])
        cook_list = make_list(client, [a])
        client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping")

        item_id = client.get("/shopping").json()["items"][0]["id"]
        client.patch(f"/shopping/{item_id}", json={"is_checked": True})

        b = make_recipe(client, "Stew", [{"name": "onion", "quantity": 1, "unit": "piece"}])
        second = make_list(client, [b])
        client.post(f"/cook-lists/{second['id']}/add-to-shopping")

        items = client.get("/shopping").json()["items"]
        assert len(items) == 2

    def test_an_ingredient_with_no_stated_amount_still_reaches_the_list(self, client):
        """"olive oil" with no quantity still means buy olive oil. Leaving
        it off because the amount is unknown is the one failure a shopping
        list must not have."""
        recipe = make_recipe(client, "Soup", [{"name": "olive oil"}])
        cook_list = make_list(client, [recipe])
        result = client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping").json()
        assert result["added"] == 1
        assert result["skipped"] == []

        item = client.get("/shopping").json()["items"][0]
        assert item["name"] == "olive oil"
        assert item["amount_text"] == ""

    def test_salt_to_taste_lands_on_the_list_without_an_amount(self, client):
        recipe = make_recipe(client, "Soup", [{"name": "salt", "unit": "to_taste"}])
        cook_list = make_list(client, [recipe])
        result = client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping").json()
        assert result["skipped"] == []
        assert client.get("/shopping").json()["items"][0]["amount_text"] == "to taste"


class TestScaling:
    def test_asking_for_double_the_serves_doubles_the_shopping(self, client, onion):
        recipe = make_recipe(
            client,
            "Soup",
            [{"name": "onion", "quantity": 2, "unit": "piece"}],
            servings=4,
        )
        created = client.post(
            "/cook-lists",
            json={"recipes": [{"recipe_id": recipe["id"], "servings": 8}]},
        ).json()
        assert created["recipes"][0]["scale_factor"] == 2.0
        assert created["recipes"][0]["scalable"] is True

        client.post(f"/cook-lists/{created['id']}/add-to-shopping")
        assert client.get("/shopping").json()["items"][0]["weight_grams"] == pytest.approx(600)

    def test_a_recipe_with_no_serving_size_reports_that_it_cannot_scale(
        self, client, onion
    ):
        """Most scraped recipes never recorded how many they make. Saying so
        beats multiplying by a number nobody supplied."""
        recipe = make_recipe(
            client, "Soup", [{"name": "onion", "quantity": 2, "unit": "piece"}]
        )
        created = client.post(
            "/cook-lists",
            json={"recipes": [{"recipe_id": recipe["id"], "servings": 8}]},
        ).json()
        assert created["recipes"][0]["scalable"] is False
        assert created["recipes"][0]["scale_factor"] == 1.0

        client.post(f"/cook-lists/{created['id']}/add-to-shopping")
        assert client.get("/shopping").json()["items"][0]["weight_grams"] == pytest.approx(300)

    def test_fixing_the_recipes_servings_later_corrects_the_factor(
        self, client, onion
    ):
        """The factor is derived live, not frozen when the list was made."""
        recipe = make_recipe(
            client, "Soup", [{"name": "onion", "quantity": 2, "unit": "piece"}]
        )
        created = client.post(
            "/cook-lists",
            json={"recipes": [{"recipe_id": recipe["id"], "servings": 8}]},
        ).json()
        assert created["recipes"][0]["scalable"] is False

        client.patch(f"/recipes/{recipe['slug']}", json={"servings": 4})
        refreshed = client.get(f"/cook-lists/{created['id']}").json()
        assert refreshed["recipes"][0]["scalable"] is True
        assert refreshed["recipes"][0]["scale_factor"] == 2.0


class TestVolumeMerging:
    """Liquids merge on millilitres, computed straight from the unit —
    no density, and no prior reclassification of the pantry row, required.
    See backend/shopping.py's module docstring."""

    def test_different_volume_units_of_the_same_liquid_merge_exactly(
        self, client, milk
    ):
        """"2 cups" and "500ml" are the same amount by fixed unit
        arithmetic alone — this is the improvement over the old
        exact-unit-only "quantity" merge, which would have kept these as
        two separate lines."""
        a = make_recipe(client, "Pancakes", [{"name": "milk", "quantity": 2, "unit": "cup"}])
        b = make_recipe(client, "White sauce", [{"name": "milk", "quantity": 500, "unit": "ml"}])
        cook_list = make_list(client, [a, b])

        result = client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping").json()
        assert result["merged"] == 1

        items = client.get("/shopping").json()["items"]
        assert len(items) == 1
        assert items[0]["volume_ml"] == pytest.approx(1000)  # 500ml (2 cups) + 500ml
        assert items[0]["weight_grams"] is None
        assert items[0]["amount_text"] == "1 l"

    def test_a_freshly_auto_created_liquid_still_merges_on_volume(self, client):
        """The pantry row for a brand-new ingredient defaults to
        measure_kind=weight and has no density — exactly the state a
        recipe importer leaves it in. It should still merge on volume
        rather than fail to merge at all."""
        a = make_recipe(client, "One", [{"name": "vegetable stock", "quantity": 1, "unit": "cup"}])
        b = make_recipe(client, "Two", [{"name": "vegetable stock", "quantity": 250, "unit": "ml"}])
        cook_list = make_list(client, [a, b])
        client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping")

        items = client.get("/shopping").json()["items"]
        assert len(items) == 1
        assert items[0]["volume_ml"] == pytest.approx(500)

    def test_a_volume_ingredient_with_a_density_still_merges_on_volume(
        self, client, session, milk
    ):
        """Costing prices milk per litre; merging on weight instead — just
        because a density happens to be set — would leave volume_ml unset
        on the merged item and the whole line unpriceable."""
        milk.density_g_per_ml = 1.03
        session.add(milk)
        session.commit()

        recipe = make_recipe(client, "Soup", [{"name": "milk", "quantity": 500, "unit": "ml"}])
        cook_list = make_list(client, [recipe])
        client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping")

        item = client.get("/shopping").json()["items"][0]
        assert item["volume_ml"] == pytest.approx(500)
        assert item["weight_grams"] is None
        assert item["cost_cents"] == 100  # 500ml at $2/L

    def test_a_weight_ingredient_with_no_density_keeps_grams_and_ml_apart(
        self, client
    ):
        """measure_kind=weight (the default) with no density: a line in
        grams gets weight_grams straight away (mass needs no conversion),
        while a line in ml has nothing to convert it to grams with and
        falls back to volume. Genuinely two different kinds for the same
        ingredient, and merging them would need a density nobody
        supplied."""
        a = make_recipe(client, "One", [{"name": "honey", "quantity": 500, "unit": "g"}])
        b = make_recipe(client, "Two", [{"name": "honey", "quantity": 500, "unit": "ml"}])
        cook_list = make_list(client, [a, b])
        client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping")

        items = client.get("/shopping").json()["items"]
        assert len(items) == 2
        assert {items[0]["weight_grams"], items[1]["weight_grams"]} == {500, None}
        assert {items[0]["volume_ml"], items[1]["volume_ml"]} == {500, None}

    def test_a_volume_line_is_priced_correctly_through_the_api(self, client, milk):
        recipe = make_recipe(client, "Soup", [{"name": "milk", "quantity": 1, "unit": "l"}])
        cook_list = make_list(client, [recipe])
        result = client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping").json()
        assert result["items"][0]["cost_cents"] == 200  # 1L at $2/L


class TestShops:
    def test_items_are_grouped_by_where_they_are_bought(
        self, client, session, onion, flour
    ):
        flour.source = IngredientSource.supermarket
        session.add(flour)
        session.commit()

        recipe = make_recipe(
            client,
            "Soup",
            [
                {"name": "onion", "quantity": 2, "unit": "piece"},
                {"name": "plain flour", "quantity": 100, "unit": "g"},
            ],
        )
        cook_list = make_list(client, [recipe])
        client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping")

        body = client.get("/shopping").json()
        assert body["shops"] == ["markets", "supermarket"]
        assert {i["name"]: i["shop"] for i in body["items"]} == {
            "onion": "markets",
            "plain flour": "supermarket",
        }

    def test_an_unlinked_item_lands_in_other(self, client):
        client.post("/shopping", json={"name": "birthday candles"})
        body = client.get("/shopping").json()
        assert body["items"][0]["shop"] == "other"

    def test_shops_sort_in_walking_order_not_alphabetically(self):
        shops = ["other", "butcher", "supermarket", "markets"]
        assert sorted(shops, key=shop_sort_key) == [
            "markets",
            "supermarket",
            "butcher",
            "other",
        ]

    def test_a_shop_missing_from_the_walking_order_still_sorts_sanely(self):
        """A source added to the enum and forgotten here must not vanish or
        jump to the front."""
        assert shop_sort_key("brand_new_shop") < shop_sort_key("other")
        assert shop_sort_key("markets") < shop_sort_key("brand_new_shop")

    def test_every_ingredient_source_has_a_place_in_the_walking_order(self):
        assert {s.value for s in IngredientSource} == set(SHOP_ORDER)


class TestPricing:
    def test_the_list_totals_what_it_can_and_says_how_much_that_covers(
        self, client, onion, parsley
    ):
        recipe = make_recipe(
            client,
            "Soup",
            [
                {"name": "onion", "quantity": 2, "unit": "piece"},  # 300g @ $4/kg
                {"name": "parsley", "quantity": 1, "unit": "bunch"},  # unpriceable
            ],
        )
        cook_list = make_list(client, [recipe])
        client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping")

        body = client.get("/shopping").json()
        assert body["total_cents"] == 120
        assert body["priced_fraction"] == 0.5

    def test_checked_items_drop_out_of_the_total(self, client, onion):
        recipe = make_recipe(
            client, "Soup", [{"name": "onion", "quantity": 2, "unit": "piece"}]
        )
        cook_list = make_list(client, [recipe])
        client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping")
        item_id = client.get("/shopping").json()["items"][0]["id"]

        client.patch(f"/shopping/{item_id}", json={"is_checked": True})
        assert client.get("/shopping").json()["total_cents"] == 0


class TestManualItems:
    def test_a_typed_name_is_matched_against_the_pantry(self, client, onion):
        """So "onions" gets the right shop and a price without being picked
        from a list."""
        item = client.post("/shopping", json={"name": "onions", "weight_grams": 500}).json()
        assert item["ingredient_id"] == onion.id
        assert item["shop"] == "markets"
        assert item["cost_cents"] == 200

    def test_an_unknown_name_is_still_accepted(self, client):
        item = client.post("/shopping", json={"name": "tin foil"}).json()
        assert item["ingredient_id"] is None
        assert item["cost_cents"] is None

    def test_a_shorter_typed_name_matches_a_pantry_row_that_contains_it(self, client):
        # No alias needed: "garlic" is a plain substring (whole-word) of
        # the pantry's "jar garlic", so it should still get that row's
        # shop and price rather than landing as unmatched plain text.
        jar_garlic = client.post(
            "/ingredients",
            json={"name": "jar garlic", "source": "supermarket", "cost_per_kg_cents": 1500},
        ).json()
        item = client.post("/shopping", json={"name": "garlic"}).json()
        assert item["ingredient_id"] == jar_garlic["id"]
        assert item["shop"] == "supermarket"

    def test_editing_an_amount_by_hand_drops_the_now_stale_breakdown(
        self, client, onion
    ):
        recipe = make_recipe(
            client, "Soup", [{"name": "onion", "quantity": 2, "unit": "piece"}]
        )
        cook_list = make_list(client, [recipe])
        client.post(f"/cook-lists/{cook_list['id']}/add-to-shopping")
        item = client.get("/shopping").json()["items"][0]
        assert item["contributions"]

        updated = client.patch(
            f"/shopping/{item['id']}", json={"weight_grams": 1000}
        ).json()
        assert updated["contributions"] == []


class TestCheckingOff:
    def test_clearing_removes_only_the_checked_items(self, client):
        keep = client.post("/shopping", json={"name": "milk"}).json()
        drop = client.post("/shopping", json={"name": "bread"}).json()
        client.patch(f"/shopping/{drop['id']}", json={"is_checked": True})

        body = client.post("/shopping/clear-checked").json()
        assert [i["id"] for i in body["items"]] == [keep["id"]]

    def test_unchecking_everything_undoes_a_round_of_ticking(self, client):
        item = client.post("/shopping", json={"name": "milk"}).json()
        client.patch(f"/shopping/{item['id']}", json={"is_checked": True})

        body = client.post("/shopping/uncheck-all").json()
        assert body["checked_count"] == 0
        assert body["items"][0]["checked_at"] is None

    def test_checked_items_sort_below_the_rest(self, client):
        first = client.post("/shopping", json={"name": "aaa"}).json()
        client.post("/shopping", json={"name": "zzz"})
        client.patch(f"/shopping/{first['id']}", json={"is_checked": True})

        names = [i["name"] for i in client.get("/shopping").json()["items"]]
        assert names == ["zzz", "aaa"]


class TestAmountText:
    @pytest.mark.parametrize(
        "grams,expected",
        [(450, "450 g"), (1000, "1 kg"), (1250, "1.25 kg"), (0.5, "0 g")],
    )
    def test_weights_read_as_grams_below_a_kilo_and_kilos_above(self, grams, expected):
        assert amount_text(ShoppingItem(name="x", weight_grams=grams)) == expected

    @pytest.mark.parametrize(
        "ml,expected",
        [(450, "450 ml"), (1000, "1 l"), (1250, "1.25 l"), (0.5, "0 ml")],
    )
    def test_volumes_read_as_ml_below_a_litre_and_litres_above(self, ml, expected):
        assert amount_text(ShoppingItem(name="x", volume_ml=ml)) == expected

    def test_weight_wins_over_volume_when_somehow_both_are_set(self):
        # Shouldn't happen in practice (add_lines populates only one), but
        # weight is the higher-precision figure if it ever does.
        item = ShoppingItem(name="x", weight_grams=500, volume_ml=500)
        assert amount_text(item) == "500 g"

    def test_a_countable_amount_keeps_its_unit(self):
        item = ShoppingItem(name="x", quantity=2, unit=MeasureUnit.bunch)
        assert amount_text(item) == "2 bunch"

    def test_nothing_to_say_says_nothing(self):
        assert amount_text(ShoppingItem(name="x")) == ""
