"""The master ingredient list: private, and load-bearing for weights."""

import pytest


@pytest.fixture
def cake(client, section, flour):
    """A recipe whose flour is measured in cups, so its weight depends
    entirely on what the pantry says about flour."""
    response = client.post(
        "/recipes",
        json={
            "title": "Test Cake",
            "tags": ["cake"],
            "servings": 4,
            "ingredients": [
                {"name": "plain flour", "quantity": 2, "unit": "cup"},
                {"name": "egg", "quantity": 3, "unit": "piece"},
            ],
            "steps": [{"text": "Bake."}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestPrivacy:
    def test_the_whole_router_needs_a_signed_in_user(self, guest_client):
        assert guest_client.get("/ingredients").status_code == 401
        assert guest_client.post("/ingredients", json={"name": "x"}).status_code == 401
        assert guest_client.get("/ingredients/plain-flour").status_code == 401


class TestListing:
    def test_lists_with_derived_costs(self, client, flour):
        items = client.get("/ingredients").json()
        row = next(i for i in items if i["slug"] == "plain-flour")
        assert row["cost_per_gram"] == pytest.approx(0.0025)
        assert row["package_cost_cents"] == 250
        assert row["has_nutrition"] is True

    def test_usage_count(self, client, cake, flour):
        row = client.get("/ingredients/plain-flour").json()
        assert row["recipe_count"] == 1

    def test_work_queue_filters(self, client, flour):
        client.post("/ingredients", json={"name": "gruyere"})
        missing = client.get("/ingredients?missing_cost=true").json()
        assert [i["slug"] for i in missing] == ["gruyere"]
        priced = client.get("/ingredients?missing_cost=false").json()
        assert [i["slug"] for i in priced] == ["plain-flour"]
        no_nutrition = client.get("/ingredients?missing_nutrition=true").json()
        assert [i["slug"] for i in no_nutrition] == ["gruyere"]

    def test_search(self, client, flour):
        assert len(client.get("/ingredients?q=flour").json()) == 1
        assert len(client.get("/ingredients?q=zzz").json()) == 0


class TestCreate:
    def test_creates_and_slugs(self, client):
        created = client.post("/ingredients", json={"name": "Golden Syrup"}).json()
        assert created["slug"] == "golden-syrup"

    def test_rejects_something_that_already_matches(self, client, flour):
        # "flour" is an alias of plain flour; a second row would silently
        # split the recipes that use it.
        assert client.post("/ingredients", json={"name": "flour"}).status_code == 409


class TestUpdateRederivesWeights:
    def test_adding_a_density_updates_every_recipe_that_uses_it(self, client, cake, flour):
        before = client.get(f"/recipes/{cake['slug']}").json()
        flour_line = next(i for i in before["ingredients"] if i["name"] == "plain flour")
        assert flour_line["weight_grams"] == pytest.approx(300.0)  # 0.6 g/ml

        client.patch("/ingredients/plain-flour", json={"density_g_per_ml": 0.55})

        after = client.get(f"/recipes/{cake['slug']}").json()
        flour_line = next(i for i in after["ingredients"] if i["name"] == "plain flour")
        assert flour_line["weight_grams"] == pytest.approx(275.0)  # 2 x 250ml x 0.55
        assert flour_line["weight_source"] == "converted"

    def test_grams_per_piece_upgrades_an_estimate_to_a_conversion(self, client, cake):
        before = client.get(f"/recipes/{cake['slug']}").json()
        egg = next(i for i in before["ingredients"] if i["name"] == "egg")
        assert egg["weight_source"] == "estimated"  # keyword table: 50g

        client.patch("/ingredients/egg", json={"grams_per_piece": 60})

        after = client.get(f"/recipes/{cake['slug']}").json()
        egg = next(i for i in after["ingredients"] if i["name"] == "egg")
        assert egg["weight_grams"] == pytest.approx(180.0)
        assert egg["weight_source"] == "converted"

    def test_an_explicit_weight_is_never_overwritten(self, client, section, flour):
        recipe = client.post(
            "/recipes",
            json={
                "title": "Weighed Cake",
                "ingredients": [{"name": "plain flour", "quantity": 250, "unit": "g"}],
            },
        ).json()
        client.patch("/ingredients/plain-flour", json={"density_g_per_ml": 0.1})
        after = client.get(f"/recipes/{recipe['slug']}").json()
        assert after["ingredients"][0]["weight_grams"] == pytest.approx(250.0)
        assert after["ingredients"][0]["weight_source"] == "explicit"

    def test_nutrition_edits_stamp_a_timestamp(self, client, flour):
        updated = client.patch("/ingredients/plain-flour", json={"sugars_g": 1.5}).json()
        assert updated["sugars_g"] == 1.5
        assert updated["nutrition_updated_at"] is not None


class TestMerge:
    def test_folds_one_row_into_another(self, client, cake, flour, admin):
        duplicate = client.post("/ingredients", json={"name": "plain white flour"}).json()
        # Point the cake's flour line at the duplicate to prove it moves.
        merged = client.post(
            f"/ingredients/plain-flour/merge/{duplicate['slug']}"
        ).json()
        assert "plain white flour" in merged["aliases"]
        assert client.get(f"/ingredients/{duplicate['slug']}").status_code == 404

    def test_the_survivor_inherits_what_it_was_missing(self, client, admin):
        keep = client.post("/ingredients", json={"name": "brown onion"}).json()
        other = client.post(
            "/ingredients",
            json={"name": "onion", "cost_per_kg_cents": 300, "grams_per_piece": 150},
        ).json()
        merged = client.post(
            f"/ingredients/{keep['slug']}/merge/{other['slug']}"
        ).json()
        assert merged["cost_per_kg_cents"] == 300
        assert merged["grams_per_piece"] == 150

    def test_cannot_merge_into_itself(self, client, flour, admin):
        assert (
            client.post("/ingredients/plain-flour/merge/plain-flour").status_code == 400
        )


class TestDelete:
    def test_deleting_unlinks_rather_than_damaging_recipes(self, client, cake, flour, admin):
        assert client.delete("/ingredients/plain-flour").status_code == 204
        after = client.get(f"/recipes/{cake['slug']}").json()
        line = next(i for i in after["ingredients"] if i["name"] == "plain flour")
        assert line["ingredient_id"] is None
        assert line["raw_text"]  # the recipe still reads correctly


class TestAliasMatching:
    """The alias lookup is what stops a re-import creating a second row."""

    def test_an_alias_is_matched_after_normalisation(self, client, session, flour):
        # The bug this covers: find_ingredient compared the *normalised*
        # query against *raw* aliases, so an alias only matched when
        # normalisation was a no-op. The alias "pinenuts" never matched a
        # line reading "pinenut", and re-importing a shopping list created
        # a duplicate row every time.
        from backend.models import Ingredient
        from backend.recipes_service import find_ingredient

        session.add(Ingredient(slug="pine-nuts", name="pine nuts", aliases=["pinenuts"]))
        session.commit()

        assert find_ingredient(session, "pinenuts").name == "pine nuts"
        assert find_ingredient(session, "pinenut").name == "pine nuts"
        assert find_ingredient(session, "PINENUTS").name == "pine nuts"

    def test_an_unrelated_name_still_misses(self, client, session, flour):
        from backend.recipes_service import find_ingredient

        assert find_ingredient(session, "dragonfruit") is None


class TestIsFood:
    def test_defaults_to_food(self, client):
        created = client.post("/ingredients", json={"name": "quinoa"}).json()
        assert created["is_food"] is True

    def test_can_be_flagged_and_filtered(self, client):
        client.post("/ingredients", json={"name": "quinoa"})
        client.post("/ingredients", json={"name": "cat litter", "is_food": False})

        food = [i["slug"] for i in client.get("/ingredients?is_food=true").json()]
        not_food = [i["slug"] for i in client.get("/ingredients?is_food=false").json()]
        assert "quinoa" in food and "cat-litter" not in food
        assert not_food == ["cat-litter"]

    def test_can_be_toggled(self, client):
        client.post("/ingredients", json={"name": "cat litter", "is_food": False})
        updated = client.patch("/ingredients/cat-litter", json={"is_food": True}).json()
        assert updated["is_food"] is True


class TestMeasureKind:
    """Most groceries are weighed, but most liquids are sold and shelf-
    priced by volume — see backend/models.py's MeasureKind."""

    def test_defaults_to_weight(self, client):
        created = client.post("/ingredients", json={"name": "quinoa"}).json()
        assert created["measure_kind"] == "weight"
        assert created["cost_per_ml"] is None

    def test_a_volume_ingredient_is_priced_and_packaged_by_the_litre(self, client):
        created = client.post(
            "/ingredients",
            json={
                "name": "milk",
                "measure_kind": "volume",
                "package_size_ml": 2000,
                "cost_per_litre_cents": 200,
            },
        ).json()
        assert created["cost_per_ml"] == pytest.approx(0.002)
        assert created["package_cost_cents"] == 400  # 2L at $2/L

    def test_a_weight_ingredients_volume_price_is_never_read(self, client, flour):
        # flour is measure_kind=weight with only cost_per_kg_cents set;
        # package_cost_cents must come from that, not silently be None
        # because someone looks at the wrong pair of fields.
        row = client.get("/ingredients/plain-flour").json()
        assert row["measure_kind"] == "weight"
        assert row["package_cost_cents"] == 250  # 1kg at $2.50/kg, from flour fixture

    def test_can_be_reclassified(self, client):
        client.post("/ingredients", json={"name": "olive oil"})
        updated = client.patch(
            "/ingredients/olive-oil",
            json={"measure_kind": "volume", "cost_per_litre_cents": 900},
        ).json()
        assert updated["measure_kind"] == "volume"
        assert updated["cost_per_ml"] == pytest.approx(0.009)

    def test_changing_the_litre_price_stamps_provenance_like_the_kilo_price_does(
        self, client
    ):
        created = client.post(
            "/ingredients", json={"name": "milk", "measure_kind": "volume"}
        ).json()
        assert created["cost_updated_at"] is None

        updated = client.patch(
            "/ingredients/milk", json={"cost_per_litre_cents": 200}
        ).json()
        assert updated["cost_updated_at"] is not None
        assert updated["cost_source"] == "manual"

    def test_an_unchanged_price_does_not_restamp(self, client):
        created = client.post(
            "/ingredients",
            json={"name": "milk", "measure_kind": "volume", "cost_per_litre_cents": 200},
        ).json()
        stamped = client.patch(
            "/ingredients/milk", json={"cost_per_litre_cents": 200}
        ).json()
        assert stamped["cost_updated_at"] == created["cost_updated_at"]

    def test_merging_inherits_the_volume_fields_the_survivor_was_missing(
        self, client, admin
    ):
        client.post(
            "/ingredients",
            json={"name": "full cream milk", "measure_kind": "volume", "package_size_ml": 1000, "cost_per_litre_cents": 220},
        )
        client.post("/ingredients", json={"name": "milk"})
        merged = client.post(
            "/ingredients/milk/merge/full-cream-milk"
        ).json()
        assert merged["package_size_ml"] == 1000
        assert merged["cost_per_litre_cents"] == 220
        # Reclassifying is not part of the merge — the survivor's own
        # measure_kind (its default, weight) is left as it was rather than
        # silently flipped by whatever the absorbed row happened to be.
        assert merged["measure_kind"] == "weight"


class TestExtendedSources:
    def test_the_shops_from_the_shopping_list_are_accepted(self, client):
        for name, source in [
            ("ling fillet", "fishmonger"),
            ("burger bun", "bakery"),
            ("marsala", "bottle_shop"),
            ("fondant", "cake_supplies"),
        ]:
            created = client.post("/ingredients", json={"name": name, "source": source}).json()
            assert created["source"] == source

    def test_an_unknown_source_is_rejected(self, client):
        response = client.post("/ingredients", json={"name": "x", "source": "spaceport"})
        assert response.status_code == 422
