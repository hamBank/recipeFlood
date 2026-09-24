"""Google Sheet sync — see backend/sheet_sync.py and SPEC.md "Google Sheet
sync". Uses an in-memory FakeSheetClient (backend/sheet_client.py); nothing
here touches the network.

Background push tasks (`sync_item`, `delete_items_from_sheet`) run inside
`TestClient`'s request/response cycle, so `client.post(...)` etc. have
already completed their push by the time the call returns — see the
`app` fixture's engine patch in conftest.py.
"""

import pytest

from backend import sheet_sync
from backend.models import Ingredient, IngredientSource, ShoppingItem, SheetPendingDelete
from backend.sheet_client import FakeSheetClient


@pytest.fixture
def onion(session):
    ingredient = Ingredient(
        slug="brown-onion",
        name="brown onion",
        aliases=["onion", "onions"],
        grams_per_piece=150,
        cost_per_kg_cents=400,
        source=IngredientSource.markets,
    )
    session.add(ingredient)
    session.commit()
    session.refresh(ingredient)
    return ingredient


@pytest.fixture
def sheet():
    fake = FakeSheetClient()
    sheet_sync.set_client_override(fake)
    yield fake
    sheet_sync.set_client_override(None)


def _row_for(fake, item_id):
    for row, entry in fake.rows.items():
        if entry.get("i", "").startswith(f"rf:{item_id}"):
            return row, entry
    return None, None


class TestPush:
    def test_append_on_add(self, client, sheet):
        item = client.post("/shopping", json={"name": "milk"}).json()
        row, entry = _row_for(sheet, item["id"])
        assert row == 1
        assert entry["a"] == "milk"
        assert entry["b"] == "1"
        assert entry["i"] == f"rf:{item['id']} synced"

    def test_a_checked_new_item_is_never_appended(self, client, sheet):
        """Only reachable via PATCH is_checked right after creation in
        practice, but add_item itself never creates a checked row, so this
        exercises sync_item's own guard directly."""
        item = client.post("/shopping", json={"name": "milk"}).json()
        client.patch(f"/shopping/{item['id']}", json={"is_checked": True})
        # Ticking an already-linked item refreshes it (strikethrough), it
        # doesn't unlink it — this just proves there's still exactly one row.
        assert len(sheet.rows) == 1

    def test_b_updates_on_amount_change(self, client, sheet):
        item = client.post("/shopping", json={"name": "flour", "weight_grams": 500}).json()
        _row, entry = _row_for(sheet, item["id"])
        assert entry["b"] == "500 g"

        client.patch(f"/shopping/{item['id']}", json={"weight_grams": 1000})
        _row, entry = _row_for(sheet, item["id"])
        assert entry["b"] == "1 kg"

    def test_b_updates_on_cook_list_merge(self, client, sheet, onion):
        recipe_a = client.post(
            "/recipes",
            json={
                "title": "Soup",
                "ingredients": [{"name": "onion", "quantity": 2, "unit": "piece"}],
                "steps": [],
            },
        ).json()
        list_a = client.post(
            "/cook-lists", json={"recipes": [{"recipe_id": recipe_a["id"]}]}
        ).json()
        client.post(f"/cook-lists/{list_a['id']}/add-to-shopping")

        item = client.get("/shopping").json()["items"][0]
        _row, entry = _row_for(sheet, item["id"])
        assert entry["b"] == "300 g"  # 2 x 150g

        recipe_b = client.post(
            "/recipes",
            json={
                "title": "Stew",
                "ingredients": [{"name": "onion", "quantity": 1, "unit": "piece"}],
                "steps": [],
            },
        ).json()
        list_b = client.post(
            "/cook-lists", json={"recipes": [{"recipe_id": recipe_b["id"]}]}
        ).json()
        client.post(f"/cook-lists/{list_b['id']}/add-to-shopping")

        _row, entry = _row_for(sheet, item["id"])
        assert entry["b"] == "450 g"

    def test_strikethrough_on_tick_and_untick(self, client, sheet):
        item = client.post("/shopping", json={"name": "bread"}).json()
        row, _entry = _row_for(sheet, item["id"])
        assert sheet.rows[row]["strike"] is False

        client.patch(f"/shopping/{item['id']}", json={"is_checked": True})
        assert sheet.rows[row]["strike"] is True
        assert sheet.rows[row]["i"] == f"rf:{item['id']} ticked"

        client.patch(f"/shopping/{item['id']}", json={"is_checked": False})
        assert sheet.rows[row]["strike"] is False
        assert sheet.rows[row]["i"] == f"rf:{item['id']} synced"

    def test_name_edit_updates_a(self, client, sheet):
        item = client.post("/shopping", json={"name": "tin foil"}).json()
        client.patch(f"/shopping/{item['id']}", json={"name": "aluminium foil"})
        _row, entry = _row_for(sheet, item["id"])
        assert entry["a"] == "aluminium foil"

    def test_row_deleted_on_remove(self, client, sheet):
        item = client.post("/shopping", json={"name": "bread"}).json()
        assert _row_for(sheet, item["id"])[0] is not None
        client.delete(f"/shopping/{item['id']}")
        assert _row_for(sheet, item["id"])[0] is None
        assert len(sheet.rows) == 0

    def test_row_deleted_on_clear_checked(self, client, sheet):
        keep = client.post("/shopping", json={"name": "milk"}).json()
        drop = client.post("/shopping", json={"name": "bread"}).json()
        client.patch(f"/shopping/{drop['id']}", json={"is_checked": True})
        client.post("/shopping/clear-checked")
        assert _row_for(sheet, drop["id"])[0] is None
        assert _row_for(sheet, keep["id"])[0] is not None

    def test_g_is_never_written(self, client, sheet):
        item = client.post("/shopping", json={"name": "flour", "weight_grams": 500}).json()
        row, entry = _row_for(sheet, item["id"])
        original_g = entry["g"]
        client.patch(f"/shopping/{item['id']}", json={"weight_grams": 1000, "is_checked": True})
        assert sheet.rows[row]["g"] == original_g

    def test_uncheck_all_does_not_delete_rows(self, client, sheet):
        item = client.post("/shopping", json={"name": "milk"}).json()
        client.patch(f"/shopping/{item['id']}", json={"is_checked": True})
        client.post("/shopping/uncheck-all")
        assert len(sheet.rows) == 1
        assert sheet.rows[1]["strike"] is False

    def test_a_sheets_error_during_a_request_does_not_fail_the_request(self, client, sheet, monkeypatch):
        def boom(*_args, **_kwargs):
            raise RuntimeError("Sheets API is down")

        monkeypatch.setattr(sheet, "read_rows", boom)
        response = client.post("/shopping", json={"name": "milk"})
        assert response.status_code == 201
        # The item exists in the app even though the sheet push failed.
        assert client.get("/shopping").json()["items"][0]["name"] == "milk"


class TestDeletionSafety:
    def test_deletion_matches_a_fresh_id_read_not_a_cached_row(self, client, sheet):
        """If deletion trusted a remembered row number instead of re-reading
        column I, a row that moved after being linked would delete
        whatever now happens to sit at the old position."""
        item = client.post("/shopping", json={"name": "milk"}).json()
        moved = dict(sheet.rows[1])
        sheet.rows[2] = moved  # simulate the sheet moving this row down...
        sheet.rows[1] = {"a": "unrelated item", "b": "", "g": "", "i": "", "strike": False}

        client.delete(f"/shopping/{item['id']}")

        assert sheet.rows[1]["a"] == "unrelated item"  # untouched
        assert _row_for(sheet, item["id"])[0] is None  # the real row is gone

    def test_a_row_with_no_id_or_a_different_id_is_never_deleted(self, app, sheet):
        sheet.seed(1, a="blank status row", i="")
        sheet.seed(2, a="someone else's item", i="rf:999 synced")
        sheet_sync.delete_items_from_sheet([42])
        assert sheet.rows[1]["a"] == "blank status row"
        assert sheet.rows[2]["a"] == "someone else's item"

    def test_pending_delete_retried_on_sync(self, client, sheet, session, monkeypatch):
        item = client.post("/shopping", json={"name": "milk"}).json()

        real_delete_rows = sheet.delete_rows
        monkeypatch.setattr(sheet, "delete_rows", lambda rows: (_ for _ in ()).throw(RuntimeError("down")))
        client.delete(f"/shopping/{item['id']}")

        pending = session.get(SheetPendingDelete, item["id"])
        assert pending is not None
        # The row is still there — the failure didn't silently drop it.
        assert _row_for(sheet, item["id"])[0] is not None

        monkeypatch.setattr(sheet, "delete_rows", real_delete_rows)
        sheet_sync.reconcile(session)

        assert _row_for(sheet, item["id"])[0] is None
        session.expire_all()
        assert session.get(SheetPendingDelete, item["id"]) is None

    def test_a_retried_delete_does_not_shift_writes_onto_the_wrong_row(
        self, client, sheet, session
    ):
        """A pending delete above an unlinked row: the import's I-cell write
        must land on that row, not on whatever slides into its old number
        once the row above is gone."""
        session.add(SheetPendingDelete(item_id=424242))
        session.commit()
        sheet.seed(1, a="old thing", i="rf:424242 synced")
        sheet.seed(2, a="bread")
        sheet.seed(3, a="someone else's note")

        sheet_sync.reconcile(session)

        bread = next(e for e in sheet.rows.values() if e["a"] == "bread")
        assert bread["i"].startswith("rf:") and bread["i"].endswith(" synced")
        note = next(e for e in sheet.rows.values() if e["a"] == "someone else's note")
        assert note["i"].startswith("rf:")  # imported and linked in its own row
        assert all(e["a"] != "old thing" for e in sheet.rows.values())
        assert len({e["i"] for e in sheet.rows.values()}) == len(sheet.rows)


class TestReconcile:
    def test_disabled_config_is_a_full_no_op(self, client, session):
        sheet_sync.set_client_override(None)  # ensure no override; settings are blank in tests
        item = client.post("/shopping", json={"name": "milk"}).json()
        result = client.post("/shopping/sheet-sync").json()
        assert result == {
            "imported": 0, "linked": 0, "ticked": 0, "pushed": 0, "deleted": 0, "errors": [],
        }
        refreshed = session.get(ShoppingItem, item["id"])
        assert refreshed.sheet_linked is False

    def test_imports_an_unlinked_row_with_a_parsed_weight(self, client, sheet):
        sheet.seed(1, a="plain flour", b="500 g")
        result = client.post("/shopping/sheet-sync").json()
        assert result["imported"] == 1

        items = client.get("/shopping").json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "plain flour"
        assert items[0]["weight_grams"] == pytest.approx(500)
        assert sheet.rows[1]["i"].startswith(f"rf:{items[0]['id']} synced")

    def test_imports_an_unlinked_row_with_no_amount_as_quantity_one(self, client, sheet):
        sheet.seed(1, a="birthday candles", b="")
        client.post("/shopping/sheet-sync")
        item = client.get("/shopping").json()["items"][0]
        assert item["quantity"] == 1
        assert item["weight_grams"] is None

    def test_links_a_same_name_unchecked_item_instead_of_duplicating(self, client, sheet, session):
        # Created while sync is off, so it starts unlinked.
        sheet_sync.set_client_override(None)
        item = client.post("/shopping", json={"name": "Milk"}).json()
        sheet_sync.set_client_override(sheet)

        sheet.seed(1, a="milk", i="")
        result = client.post("/shopping/sheet-sync").json()
        assert result["linked"] == 1
        assert result["imported"] == 0

        items = client.get("/shopping").json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == item["id"]
        assert sheet.rows[1]["i"] == f"rf:{item['id']} synced"

    def test_ticks_and_detaches_an_item_whose_row_vanished_and_never_reappends_it(
        self, client, sheet, session
    ):
        item = client.post("/shopping", json={"name": "milk"}).json()
        row, _ = _row_for(sheet, item["id"])
        del sheet.rows[row]  # simulate a human deleting the row on the sheet

        result = client.post("/shopping/sheet-sync").json()
        assert result["ticked"] == 1

        refreshed = client.get("/shopping").json()["items"][0]
        assert refreshed["is_checked"] is True

        rows_before = dict(sheet.rows)
        client.post("/shopping/sheet-sync")
        assert dict(sheet.rows) == rows_before  # not re-appended

    def test_marks_a_row_whose_id_is_not_in_the_app(self, client, sheet):
        sheet.seed(1, a="mystery item", i="rf:999999 synced")
        client.post("/shopping/sheet-sync")
        assert sheet.rows[1]["i"] == "rf:999999 missing in app"

    def test_blank_rows_are_skipped(self, client, sheet):
        sheet.seed(1, a="milk")
        sheet.rows[2] = {"a": "", "b": "", "g": "", "i": "", "strike": False}
        sheet.seed(3, a="bread")
        result = client.post("/shopping/sheet-sync").json()
        assert result["imported"] == 2
