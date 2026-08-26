"""Cooking lists: membership, ordering and what survives a deletion."""

from datetime import date

import pytest


@pytest.fixture
def soup(client):
    response = client.post(
        "/recipes",
        json={"title": "Soup", "ingredients": [{"name": "onion"}], "steps": []},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def stew(client):
    response = client.post(
        "/recipes",
        json={"title": "Stew", "ingredients": [{"name": "beef"}], "steps": []},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def cake(client):
    response = client.post(
        "/recipes",
        json={"title": "Cake", "ingredients": [{"name": "flour"}], "steps": []},
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestCreating:
    def test_a_list_defaults_to_today(self, client):
        created = client.post("/cook-lists", json={}).json()
        assert created["cook_date"] == date.today().isoformat()
        assert created["recipe_count"] == 0

    def test_a_list_can_be_created_with_its_recipes(self, client, soup, stew):
        created = client.post(
            "/cook-lists",
            json={
                "cook_date": "2026-08-24",
                "description": "Week of the 24th",
                "recipes": [{"recipe_id": soup["id"]}, {"recipe_id": stew["id"]}],
            },
        ).json()
        assert created["description"] == "Week of the 24th"
        assert [r["title"] for r in created["recipes"]] == ["Soup", "Stew"]
        assert [r["position"] for r in created["recipes"]] == [0, 1]

    def test_a_blank_description_is_stored_as_absent(self, client):
        created = client.post("/cook-lists", json={"description": "   "}).json()
        assert created["description"] is None

    def test_two_lists_can_share_a_date(self, client):
        """A week of dinners and Saturday's cake are separate plans that
        happen to start on the same Monday."""
        first = client.post("/cook-lists", json={"cook_date": "2026-08-24"})
        second = client.post("/cook-lists", json={"cook_date": "2026-08-24"})
        assert first.status_code == 201 and second.status_code == 201

    def test_an_unknown_recipe_is_rejected(self, client):
        response = client.post(
            "/cook-lists", json={"recipes": [{"recipe_id": 9999}]}
        )
        assert response.status_code == 422


class TestMembership:
    def test_a_recipe_can_be_added_to_an_existing_list(self, client, soup):
        created = client.post("/cook-lists", json={}).json()
        body = client.post(
            f"/cook-lists/{created['id']}/recipes", json={"recipe_id": soup["id"]}
        ).json()
        assert [r["title"] for r in body["recipes"]] == ["Soup"]

    def test_adding_the_same_recipe_twice_updates_it_rather_than_duplicating(
        self, client, soup
    ):
        """A double-tap is not a plan to cook it twice — and it would
        double the shopping."""
        created = client.post("/cook-lists", json={}).json()
        client.post(f"/cook-lists/{created['id']}/recipes", json={"recipe_id": soup["id"]})
        body = client.post(
            f"/cook-lists/{created['id']}/recipes",
            json={"recipe_id": soup["id"], "servings": 6},
        ).json()
        assert body["recipe_count"] == 1
        assert body["recipes"][0]["servings"] == 6

    def test_a_duplicate_in_a_wholesale_replacement_is_collapsed(self, client, soup):
        created = client.post(
            "/cook-lists",
            json={"recipes": [{"recipe_id": soup["id"]}, {"recipe_id": soup["id"]}]},
        ).json()
        assert created["recipe_count"] == 1

    def test_a_recipe_can_be_removed(self, client, soup, stew):
        created = client.post(
            "/cook-lists",
            json={"recipes": [{"recipe_id": soup["id"]}, {"recipe_id": stew["id"]}]},
        ).json()
        body = client.delete(
            f"/cook-lists/{created['id']}/recipes/{soup['id']}"
        ).json()
        assert [r["title"] for r in body["recipes"]] == ["Stew"]

    def test_removing_a_recipe_that_is_not_on_the_list_is_a_404(self, client, soup):
        created = client.post("/cook-lists", json={}).json()
        response = client.delete(f"/cook-lists/{created['id']}/recipes/{soup['id']}")
        assert response.status_code == 404

    def test_patching_recipes_replaces_the_membership_in_order(
        self, client, soup, stew
    ):
        created = client.post(
            "/cook-lists", json={"recipes": [{"recipe_id": soup["id"]}]}
        ).json()
        body = client.patch(
            f"/cook-lists/{created['id']}",
            json={"recipes": [{"recipe_id": stew["id"]}, {"recipe_id": soup["id"]}]},
        ).json()
        assert [r["title"] for r in body["recipes"]] == ["Stew", "Soup"]

    def test_patching_without_recipes_leaves_the_membership_alone(
        self, client, soup
    ):
        created = client.post(
            "/cook-lists", json={"recipes": [{"recipe_id": soup["id"]}]}
        ).json()
        body = client.patch(
            f"/cook-lists/{created['id']}", json={"description": "Renamed"}
        ).json()
        assert body["description"] == "Renamed"
        assert body["recipe_count"] == 1


class TestListing:
    def test_lists_come_back_newest_date_first(self, client):
        for day in ("2026-08-01", "2026-08-20", "2026-08-10"):
            client.post("/cook-lists", json={"cook_date": day})
        dates = [row["cook_date"] for row in client.get("/cook-lists").json()]
        assert dates == ["2026-08-20", "2026-08-10", "2026-08-01"]

    def test_a_date_range_can_be_asked_for(self, client):
        for day in ("2026-07-01", "2026-08-10", "2026-09-01"):
            client.post("/cook-lists", json={"cook_date": day})
        rows = client.get("/cook-lists?since=2026-08-01&until=2026-08-31").json()
        assert [r["cook_date"] for r in rows] == ["2026-08-10"]

    def test_the_total_count_is_reported_for_paging(self, client):
        for day in ("2026-08-01", "2026-08-02"):
            client.post("/cook-lists", json={"cook_date": day})
        response = client.get("/cook-lists?limit=1")
        assert response.headers["X-Total-Count"] == "2"
        assert len(response.json()) == 1

    def test_exclude_imported_skips_cooking_history_batches(self, client):
        # A history import backdates its lists close to "now" by definition
        # (that was the last thing logged), so a plain newest-first lookup
        # would otherwise readily surface one instead of a list someone is
        # actually planning — see backend/cook_lists.py.
        client.post(
            "/cook-lists",
            json={"cook_date": "2026-08-22", "description": "Cooking history import"},
        )
        planned = client.post("/cook-lists", json={"cook_date": "2026-08-10"}).json()

        rows = client.get("/cook-lists?exclude_imported=true").json()
        assert [r["id"] for r in rows] == [planned["id"]]

    def test_completed_lists_are_hidden_by_default_but_reachable(self, client):
        done = client.post("/cook-lists", json={"cook_date": "2026-08-10"}).json()
        client.patch(f"/cook-lists/{done['id']}", json={"completed": True})
        planned = client.post("/cook-lists", json={"cook_date": "2026-08-15"}).json()

        assert [r["id"] for r in client.get("/cook-lists").json()] == [planned["id"]]
        ids = {r["id"] for r in client.get("/cook-lists?include_completed=true").json()}
        assert ids == {done["id"], planned["id"]}


class TestCompleting:
    def test_a_list_defaults_to_not_completed(self, client):
        created = client.post("/cook-lists", json={}).json()
        assert created["completed"] is False

    def test_completed_can_be_toggled_via_patch(self, client):
        created = client.post("/cook-lists", json={}).json()
        marked = client.patch(f"/cook-lists/{created['id']}", json={"completed": True}).json()
        assert marked["completed"] is True
        reopened = client.patch(
            f"/cook-lists/{created['id']}", json={"completed": False}
        ).json()
        assert reopened["completed"] is False

    def test_patching_an_unrelated_field_does_not_touch_completed(self, client):
        created = client.post("/cook-lists", json={}).json()
        client.patch(f"/cook-lists/{created['id']}", json={"completed": True})
        updated = client.patch(
            f"/cook-lists/{created['id']}", json={"description": "Renamed"}
        ).json()
        assert updated["completed"] is True


class TestCompletingARecipe:
    def test_a_recipe_defaults_to_not_completed(self, client, soup):
        created = client.post(
            "/cook-lists", json={"recipes": [{"recipe_id": soup["id"]}]}
        ).json()
        assert created["recipes"][0]["completed"] is False

    def test_completed_can_be_toggled_via_patch(self, client, soup):
        created = client.post(
            "/cook-lists", json={"recipes": [{"recipe_id": soup["id"]}]}
        ).json()
        marked = client.patch(
            f"/cook-lists/{created['id']}/recipes/{soup['id']}", json={"completed": True}
        ).json()
        assert marked["recipes"][0]["completed"] is True

        reopened = client.patch(
            f"/cook-lists/{created['id']}/recipes/{soup['id']}", json={"completed": False}
        ).json()
        assert reopened["recipes"][0]["completed"] is False

    def test_completing_a_recipe_not_on_the_list_is_a_404(self, client, soup):
        created = client.post("/cook-lists", json={}).json()
        response = client.patch(
            f"/cook-lists/{created['id']}/recipes/{soup['id']}", json={"completed": True}
        )
        assert response.status_code == 404

    def test_completing_on_an_unknown_list_is_a_404(self, client, soup):
        response = client.patch(
            f"/cook-lists/9999/recipes/{soup['id']}", json={"completed": True}
        )
        assert response.status_code == 404

    def test_completed_recipes_sink_to_the_bottom(self, client, soup, stew, cake):
        created = client.post(
            "/cook-lists",
            json={
                "recipes": [
                    {"recipe_id": soup["id"]},
                    {"recipe_id": stew["id"]},
                    {"recipe_id": cake["id"]},
                ]
            },
        ).json()
        client.patch(f"/cook-lists/{created['id']}/recipes/{soup['id']}", json={"completed": True})

        body = client.get(f"/cook-lists/{created['id']}").json()
        assert [r["title"] for r in body["recipes"]] == ["Stew", "Cake", "Soup"]

    def test_relative_order_within_each_group_is_preserved(self, client, soup, stew, cake):
        # Two completed, one not — the completed pair should keep their own
        # planned order relative to each other, not just land at the bottom
        # in whatever order the sort happens to produce.
        created = client.post(
            "/cook-lists",
            json={
                "recipes": [
                    {"recipe_id": soup["id"]},
                    {"recipe_id": stew["id"]},
                    {"recipe_id": cake["id"]},
                ]
            },
        ).json()
        client.patch(f"/cook-lists/{created['id']}/recipes/{soup['id']}", json={"completed": True})
        client.patch(f"/cook-lists/{created['id']}/recipes/{cake['id']}", json={"completed": True})

        body = client.get(f"/cook-lists/{created['id']}").json()
        assert [r["title"] for r in body["recipes"]] == ["Stew", "Soup", "Cake"]

    def test_uncompleting_moves_it_back_out_of_the_completed_group(
        self, client, soup, stew
    ):
        created = client.post(
            "/cook-lists",
            json={"recipes": [{"recipe_id": soup["id"]}, {"recipe_id": stew["id"]}]},
        ).json()
        client.patch(f"/cook-lists/{created['id']}/recipes/{soup['id']}", json={"completed": True})
        client.patch(f"/cook-lists/{created['id']}/recipes/{soup['id']}", json={"completed": False})

        body = client.get(f"/cook-lists/{created['id']}").json()
        assert [r["title"] for r in body["recipes"]] == ["Soup", "Stew"]


class TestDeleting:
    def test_deleting_a_list_leaves_its_shopping_behind(self, client, soup):
        """The shop may already be half done. Losing the plan is not a
        reason to lose the list of what to buy."""
        created = client.post(
            "/cook-lists", json={"recipes": [{"recipe_id": soup["id"]}]}
        ).json()
        client.post(f"/cook-lists/{created['id']}/add-to-shopping")
        assert client.get("/shopping").json()["total_count"] == 1

        assert client.delete(f"/cook-lists/{created['id']}").status_code == 204
        items = client.get("/shopping").json()["items"]
        assert len(items) == 1
        assert items[0]["cook_list_id"] is None

    def test_a_deleted_recipe_does_not_break_the_page(self, client, soup, stew):
        """A membership row can outlive its recipe. The list should lose a
        row, not return a 500."""
        created = client.post(
            "/cook-lists",
            json={"recipes": [{"recipe_id": soup["id"]}, {"recipe_id": stew["id"]}]},
        ).json()
        assert client.delete(f"/recipes/{soup['slug']}").status_code == 204

        body = client.get(f"/cook-lists/{created['id']}").json()
        assert [r["title"] for r in body["recipes"]] == ["Stew"]
        assert body["recipe_count"] == 1

    def test_an_unknown_list_is_a_404(self, client):
        assert client.get("/cook-lists/9999").status_code == 404
        assert client.delete("/cook-lists/9999").status_code == 404


class TestAddingToShopping:
    def test_adding_twice_adds_twice(self, client, soup):
        """"We're cooking this again" is a real thing to want, and guessing
        otherwise would silently drop a shop."""
        created = client.post(
            "/cook-lists", json={"recipes": [{"recipe_id": soup["id"]}]}
        ).json()
        first = client.post(f"/cook-lists/{created['id']}/add-to-shopping").json()
        second = client.post(f"/cook-lists/{created['id']}/add-to-shopping").json()
        assert first["added"] == 1
        assert second["added"] + second["merged"] == 1

    def test_the_response_lists_what_it_touched(self, client, soup, stew):
        created = client.post(
            "/cook-lists",
            json={"recipes": [{"recipe_id": soup["id"]}, {"recipe_id": stew["id"]}]},
        ).json()
        result = client.post(f"/cook-lists/{created['id']}/add-to-shopping").json()
        assert {i["name"] for i in result["items"]} == {"onion", "beef"}
