"""GET/PATCH /auth/me — the signed-in user's own profile."""

from backend.models import UserRole


class TestMe:
    def test_get_includes_the_shopping_show_ticked_preference(self, client, admin):
        body = client.get("/auth/me").json()
        assert body["shopping_show_ticked"] is True

    def test_patch_updates_the_preference(self, client, admin):
        response = client.patch("/auth/me", json={"shopping_show_ticked": False})
        assert response.status_code == 200
        assert response.json()["shopping_show_ticked"] is False
        assert client.get("/auth/me").json()["shopping_show_ticked"] is False

    def test_patch_ignores_fields_outside_the_self_editable_schema(self, client, admin):
        response = client.patch("/auth/me", json={"role": "admin", "name": "Nope"})
        assert response.status_code == 200
        assert response.json()["role"] == UserRole.admin.value
        assert response.json()["name"] != "Nope"

    def test_requires_auth(self, guest_client):
        assert guest_client.get("/auth/me").status_code == 401
        assert guest_client.patch("/auth/me", json={"shopping_show_ticked": False}).status_code == 401
