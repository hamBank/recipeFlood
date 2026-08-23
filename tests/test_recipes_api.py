"""Recipe endpoints, with the visibility rules that make the site public."""

import pytest


@pytest.fixture
def recipe_payload(section):
    return {
        "title": "Chocolate Walnut Cake",
        "description": "A dense flourless cake.",
        "servings": 8,
        "prep_minutes": 20,
        "cook_minutes": 40,
        "storage": "Airtight, 4 days",
        "source_url": "https://example.test/cake",
        # "cake" is a section tag; the other two are free-form. One list.
        "tags": ["cake", "baking", "chocolate"],
        "ingredients": [
            {"name": "plain flour", "quantity": 2, "unit": "cup"},
            {"name": "caster sugar", "quantity": 1, "unit": "cup"},
            {"name": "salt", "unit": "pinch"},
        ],
        "steps": [{"text": "Heat the oven."}, {"text": "Mix and bake."}],
    }


def create(client, payload):
    response = client.post("/recipes", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


class TestCreate:
    def test_creates_with_children_and_a_slug(self, client, recipe_payload, flour):
        recipe = create(client, recipe_payload)
        assert recipe["slug"] == "chocolate-walnut-cake"
        assert len(recipe["ingredients"]) == 3
        assert len(recipe["steps"]) == 2
        assert recipe["steps"][1]["position"] == 1
        assert sorted(recipe["tags"]) == ["Cake", "baking", "chocolate"]
        # `sections` is the navigation subset of `tags`, not a separate field
        assert recipe["sections"] == ["Cake"]

    def test_total_time_is_derived_from_prep_plus_cook(self, client, recipe_payload):
        assert create(client, recipe_payload)["total_minutes"] == 60

    def test_total_time_override_wins(self, client, recipe_payload):
        recipe_payload["total_minutes_override"] = 180  # includes chilling
        assert create(client, recipe_payload)["total_minutes"] == 180

    def test_amounts_are_converted_to_grams_on_the_way_in(self, client, recipe_payload, flour):
        recipe = create(client, recipe_payload)
        by_name = {i["name"]: i for i in recipe["ingredients"]}
        # flour is linked to the master row, which carries a real density
        assert by_name["plain flour"]["weight_grams"] == pytest.approx(300.0)
        assert by_name["plain flour"]["weight_source"] == "converted"
        # sugar is not in the pantry, so the keyword table estimates it
        assert by_name["caster sugar"]["weight_grams"] == pytest.approx(220.0)
        assert by_name["caster sugar"]["weight_source"] == "estimated"
        # a pinch is not a weight in any system
        assert by_name["salt"]["weight_grams"] is None
        assert by_name["salt"]["weight_source"] == "unknown"

    def test_volume_amounts_are_also_converted_to_millilitres(self, client, recipe_payload):
        # Pure unit arithmetic, independent of the weight conversion above
        # (and of any linked ingredient) — see units.to_ml.
        recipe_payload["ingredients"].append({"name": "milk", "quantity": 2, "unit": "cup"})
        recipe = create(client, recipe_payload)
        milk = next(i for i in recipe["ingredients"] if i["name"] == "milk")
        assert milk["volume_ml"] == pytest.approx(500.0)
        # salt ("pinch") and the count-unit lines have no volume unit
        assert next(i for i in recipe["ingredients"] if i["name"] == "salt")["volume_ml"] is None

    def test_duplicate_titles_get_distinct_slugs(self, client, recipe_payload):
        first = create(client, recipe_payload)
        second = create(client, recipe_payload)
        assert first["slug"] == "chocolate-walnut-cake"
        assert second["slug"] == "chocolate-walnut-cake-2"

    def test_blank_title_is_rejected(self, client, recipe_payload):
        recipe_payload["title"] = "   "
        assert client.post("/recipes", json=recipe_payload).status_code == 422

    def test_source_page_round_trips_for_a_book_citation(self, client, recipe_payload):
        del recipe_payload["source_url"]
        recipe_payload["source_name"] = "Plenty More"
        recipe_payload["source_page"] = 133
        recipe = create(client, recipe_payload)
        assert recipe["source_name"] == "Plenty More"
        assert recipe["source_page"] == 133


class TestRead:
    def test_lists_with_a_total_count_header(self, client, recipe_payload):
        create(client, recipe_payload)
        response = client.get("/recipes")
        assert response.status_code == 200
        assert response.headers["X-Total-Count"] == "1"

    def test_fetch_by_slug_or_id(self, client, recipe_payload):
        recipe = create(client, recipe_payload)
        assert client.get(f"/recipes/{recipe['slug']}").json()["id"] == recipe["id"]
        assert client.get(f"/recipes/{recipe['id']}").json()["slug"] == recipe["slug"]

    def test_missing_recipe_is_a_404(self, client):
        assert client.get("/recipes/nope").status_code == 404

    def test_search_filters_on_title(self, client, recipe_payload):
        create(client, recipe_payload)
        assert len(client.get("/recipes?q=walnut").json()) == 1
        assert len(client.get("/recipes?q=lasagne").json()) == 0

    def test_one_tag_filter_serves_sections_and_free_tags_alike(
        self, client, recipe_payload
    ):
        create(client, recipe_payload)
        assert len(client.get("/recipes?tag=cake").json()) == 1  # a section
        assert len(client.get("/recipes?tag=chocolate").json()) == 1  # free-form
        assert len(client.get("/recipes?tag=soup").json()) == 0

    def test_sort_by_title(self, client, recipe_payload):
        create(client, recipe_payload)
        create(client, {**recipe_payload, "title": "Apple Cake"})
        titles = [r["title"] for r in client.get("/recipes?sort=title&order=asc").json()]
        assert titles == ["Apple Cake", "Chocolate Walnut Cake"]

    def test_a_web_imported_recipe_reads_back_with_its_import_source(self, client, session):
        # import_source isn't settable through POST /recipes — only the
        # history importer (scripts/import_recipe_history.py) writes 'web',
        # straight to the database — so this seeds the row directly rather
        # than going through `create`.
        from backend.models import ImportSource, Recipe

        session.add(
            Recipe(
                slug="fetched-from-elsewhere",
                title="Fetched From Elsewhere",
                import_source=ImportSource.web,
                source_url="https://example.test/fetched",
            )
        )
        session.commit()
        recipe = client.get("/recipes/fetched-from-elsewhere").json()
        assert recipe["import_source"] == "web"


class TestVisibility:
    """Public read, costs behind login — the rule from SPEC.md."""

    def test_a_guest_can_read_recipes(self, client, guest_client, recipe_payload):
        create(client, recipe_payload)
        assert guest_client.get("/recipes").status_code == 200
        assert guest_client.get("/recipes/chocolate-walnut-cake").status_code == 200

    def test_a_guest_never_sees_cost(self, client, guest_client, recipe_payload, flour):
        create(client, recipe_payload)
        public = guest_client.get("/recipes/chocolate-walnut-cake").json()
        assert public["cost"] is None
        assert all(item["cost_cents"] is None for item in public["ingredients"])

    def test_a_signed_in_user_does_see_cost(self, client, recipe_payload, flour):
        create(client, recipe_payload)
        private = client.get("/recipes/chocolate-walnut-cake").json()
        assert private["cost"]["total_cents"] == 75  # 300g flour at $2.50/kg
        assert private["cost"]["per_serving_cents"] == 9

    def test_nutrition_is_public(self, client, guest_client, recipe_payload, flour):
        # Nutrition is not commercially sensitive; only prices are.
        create(client, recipe_payload)
        public = guest_client.get("/recipes/chocolate-walnut-cake").json()
        assert public["nutrition"]["protein_g"] == pytest.approx(30.0)

    def test_a_guest_cannot_write(self, guest_client, recipe_payload):
        assert guest_client.post("/recipes", json=recipe_payload).status_code == 401

    def test_a_guest_cannot_see_the_pantry(self, guest_client):
        assert guest_client.get("/ingredients").status_code == 401

    def test_unpublished_recipes_are_hidden_from_guests(
        self, client, guest_client, recipe_payload
    ):
        create(client, {**recipe_payload, "is_published": False})
        assert guest_client.get("/recipes").json() == []
        assert guest_client.get("/recipes/chocolate-walnut-cake").status_code == 404
        assert len(client.get("/recipes?include_unpublished=true").json()) == 1


class TestUpdate:
    def test_patches_only_what_was_sent(self, client, recipe_payload):
        recipe = create(client, recipe_payload)
        updated = client.patch(
            f"/recipes/{recipe['slug']}", json={"storage": "Freezes well"}
        ).json()
        assert updated["storage"] == "Freezes well"
        assert len(updated["ingredients"]) == 3  # untouched

    def test_children_are_replaced_wholesale_when_sent(self, client, recipe_payload):
        recipe = create(client, recipe_payload)
        updated = client.patch(
            f"/recipes/{recipe['slug']}",
            json={"steps": [{"text": "One step only."}]},
        ).json()
        assert [s["text"] for s in updated["steps"]] == ["One step only."]

    def test_editing_clears_the_review_flag(self, client, recipe_payload):
        recipe = create(client, recipe_payload)
        client.patch(f"/recipes/{recipe['slug']}", json={"needs_review": True})
        assert client.get(f"/recipes/{recipe['slug']}").json()["needs_review"] is True
        client.patch(f"/recipes/{recipe['slug']}", json={"needs_review": False})
        assert client.get(f"/recipes/{recipe['slug']}").json()["needs_review"] is False

    def test_the_slug_survives_an_edit_that_is_not_a_rename(self, client, recipe_payload):
        recipe = create(client, recipe_payload)
        updated = client.patch(
            f"/recipes/{recipe['slug']}", json={"description": "Changed."}
        ).json()
        assert updated["slug"] == recipe["slug"]

    def test_renaming_reslugs(self, client, recipe_payload):
        recipe = create(client, recipe_payload)
        updated = client.patch(
            f"/recipes/{recipe['slug']}", json={"title": "Hazelnut Cake"}
        ).json()
        assert updated["slug"] == "hazelnut-cake"


class TestPreparedLog:
    def test_marking_prepared_sets_the_last_prepared_date(self, client, recipe_payload, admin):
        recipe = create(client, recipe_payload)
        response = client.post(
            f"/recipes/{recipe['slug']}/prepared",
            json={"prepared_on": "2026-01-15", "rating": 5, "note": "Halved the sugar"},
        )
        assert response.status_code == 201
        fetched = client.get(f"/recipes/{recipe['slug']}").json()
        assert fetched["last_prepared_on"] == "2026-01-15"
        assert fetched["prepared_count"] == 1

    def test_the_newest_entry_wins(self, client, recipe_payload, admin):
        recipe = create(client, recipe_payload)
        for day in ("2026-01-15", "2026-03-02", "2025-11-01"):
            client.post(f"/recipes/{recipe['slug']}/prepared", json={"prepared_on": day})
        fetched = client.get(f"/recipes/{recipe['slug']}").json()
        assert fetched["last_prepared_on"] == "2026-03-02"
        assert fetched["prepared_count"] == 3

    def test_entries_can_be_removed(self, client, recipe_payload, admin):
        recipe = create(client, recipe_payload)
        event = client.post(
            f"/recipes/{recipe['slug']}/prepared", json={"prepared_on": "2026-01-15"}
        ).json()
        assert (
            client.delete(f"/recipes/{recipe['slug']}/prepared/{event['id']}").status_code
            == 204
        )
        assert client.get(f"/recipes/{recipe['slug']}").json()["prepared_count"] == 0

    def test_not_prepared_days_filter(self, client, recipe_payload, admin):
        recipe = create(client, recipe_payload)
        create(client, {**recipe_payload, "title": "Never Made"})
        client.post(
            f"/recipes/{recipe['slug']}/prepared", json={}  # defaults to today
        )
        stale = client.get("/recipes?not_prepared_days=30").json()
        assert [r["title"] for r in stale] == ["Never Made"]


class TestDelete:
    def test_deletes_the_recipe_and_its_children(self, client, recipe_payload, admin):
        recipe = create(client, recipe_payload)
        assert client.delete(f"/recipes/{recipe['slug']}").status_code == 204
        assert client.get(f"/recipes/{recipe['slug']}").status_code == 404
