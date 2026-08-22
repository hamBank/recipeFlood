"""Tags, and the section flag that turns some of them into navigation."""

import pytest


@pytest.fixture
def recipes(client, section):
    """Two recipes: one in the Cake section, one with free tags only."""
    client.post(
        "/recipes",
        json={"title": "Chocolate Cake", "tags": ["cake", "chocolate", "baking"]},
    )
    client.post("/recipes", json={"title": "Squid", "tags": ["seafood", "squid"]})


class TestListing:
    def test_sections_come_back_in_nav_order(self, client, section):
        client.post(
            "/tags",
            json={"name": "Bread", "is_section": True, "sort_order": 20},
        )
        names = [t["name"] for t in client.get("/tags?section=true").json()]
        assert names == ["Bread", "Cake"]  # sort_order 20 before 30

    def test_an_unused_section_still_appears(self, client, section):
        # An empty section must stay in the nav so an editor can file into it.
        rows = client.get("/tags?section=true").json()
        assert [t["slug"] for t in rows] == ["cake"]
        assert rows[0]["recipe_count"] == 0

    def test_free_tags_exclude_sections(self, client, recipes):
        slugs = [t["slug"] for t in client.get("/tags?section=false").json()]
        assert "cake" not in slugs
        assert {"chocolate", "baking", "seafood", "squid"} <= set(slugs)

    def test_free_tags_are_most_used_first(self, client, recipes):
        client.post("/recipes", json={"title": "Brownie", "tags": ["chocolate"]})
        rows = client.get("/tags?section=false").json()
        assert rows[0]["slug"] == "chocolate"
        assert rows[0]["recipe_count"] == 2

    def test_min_count_drops_the_long_tail_but_never_a_section(
        self, client, recipes
    ):
        # Over half the imported blog labels are used exactly once, which is
        # why the filter exists — but the nav must survive it.
        rows = client.get("/tags?min_count=2").json()
        assert [t["slug"] for t in rows if t["is_section"]] == ["cake"]
        assert "squid" not in [t["slug"] for t in rows]

    def test_counts_are_public(self, guest_client, recipes):
        assert guest_client.get("/tags?section=true").status_code == 200


class TestRecipeSectionSplit:
    def test_sections_are_the_navigation_subset_of_tags(self, client, recipes):
        recipe = client.get("/recipes/chocolate-cake").json()
        assert recipe["sections"] == ["Cake"]
        assert set(recipe["tags"]) == {"Cake", "chocolate", "baking"}

    def test_a_recipe_can_sit_in_no_section(self, client, recipes):
        recipe = client.get("/recipes/squid").json()
        assert recipe["sections"] == []
        assert set(recipe["tags"]) == {"seafood", "squid"}

    def test_a_recipe_can_sit_in_several(self, client, section):
        # The thing a single-valued Category could not express: a chocolate
        # tart is honestly both a Dessert and a Pastry.
        client.post("/tags", json={"name": "Dessert", "is_section": True, "sort_order": 60})
        client.post(
            "/recipes",
            json={"title": "Choc Tart", "tags": ["cake", "dessert", "chocolate"]},
        )
        recipe = client.get("/recipes/choc-tart").json()
        assert recipe["sections"] == ["Cake", "Dessert"]  # nav order, 30 then 60


class TestPromotion:
    def test_promoting_a_free_tag_moves_its_recipes_into_the_nav(
        self, client, recipes, admin
    ):
        # The payoff of one table: no recipe changes, because every recipe
        # already links to this exact tag row.
        assert client.get("/recipes?tag=seafood").json()[0]["sections"] == []

        promoted = client.patch(
            "/tags/seafood", json={"is_section": True, "sort_order": 110}
        ).json()
        assert promoted["is_section"] is True

        assert [t["slug"] for t in client.get("/tags?section=true").json()] == [
            "cake",
            "seafood",
        ]
        assert client.get("/recipes/squid").json()["sections"] == ["seafood"]

    def test_demoting_a_section_leaves_the_recipes_alone(self, client, recipes, admin):
        client.patch("/tags/cake", json={"is_section": False})
        recipe = client.get("/recipes/chocolate-cake").json()
        assert recipe["sections"] == []
        assert "Cake" in recipe["tags"]  # still tagged, just not navigation

    def test_a_recipe_naming_a_section_attaches_to_it_rather_than_forking(
        self, client, section
    ):
        # "cake" must find the existing section, not create a second tag.
        client.post("/recipes", json={"title": "Lemon Cake", "tags": ["cake"]})
        assert len(client.get("/tags").json()) == 1
        assert client.get("/recipes/lemon-cake").json()["sections"] == ["Cake"]

    def test_promotion_is_admin_only(self, guest_client, section):
        assert guest_client.patch("/tags/cake", json={"is_section": False}).status_code == 401


class TestWrites:
    def test_create_derives_a_slug(self, client, admin):
        created = client.post("/tags", json={"name": "Dips & Spreads"}).json()
        assert created["slug"] == "dips-spreads"
        assert created["is_section"] is False

    def test_blank_name_is_rejected(self, client, admin):
        assert client.post("/tags", json={"name": "  "}).status_code == 422

    def test_delete_removes_the_tag_and_its_links(self, client, recipes, admin):
        assert client.delete("/tags/chocolate").status_code == 204
        assert client.get("/tags/chocolate").status_code == 404
        assert "chocolate" not in client.get("/recipes/chocolate-cake").json()["tags"]

    def test_guests_cannot_write(self, guest_client, section):
        assert guest_client.post("/tags", json={"name": "x"}).status_code == 401
        assert guest_client.delete("/tags/cake").status_code == 401
