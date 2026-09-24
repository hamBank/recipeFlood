"""Two-way sync between the one permanent shopping list and a Google Sheet
the household already uses. See SPEC.md's "Google Sheet sync" for the
rules this module implements; the HARD SAFETY RULE there — never delete a
sheet row except through `delete_items_from_sheet`, id-matched against a
fresh read of column I, never by cached row number — is the one rule
every function here is written around.

Two directions:

* **Push** (`sync_item`, `delete_items_from_sheet`) — fire-and-forget,
  called from a `BackgroundTasks` hook after a request's own DB commit, so
  a slow or failing Sheets API call never fails the user's request. Each
  call opens its own DB session (the request's session is already closed
  by the time a background task runs) and is guarded by a process-level
  lock, since this app runs as a single uvicorn process and the Sheets
  API has no transaction of its own to serialise concurrent writers.
* **Pull** (`reconcile`) — only ever run on demand, from
  `POST /shopping/sheet-sync`, inside the request itself so its summary
  can be returned. No cron, no polling.

Every entry point degrades to a silent no-op when sync isn't configured
(`sheet_sync_enabled()` false) or a Sheets API call raises — errors are
logged, never propagated, and leave state (`sheet_dirty`,
`SheetPendingDelete`) for the next push or on-demand sync to retry.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Optional

from sqlmodel import Session, select

from . import database
from .config import settings
from .models import MeasureUnit, SheetPendingDelete, ShoppingItem
from .recipes_service import find_ingredient
from .sheet_client import RestSheetClient, SheetClient
from .shopping import amount_text, set_checked
from .units import MASS_G, parse_amount, to_grams, to_ml

logger = logging.getLogger(__name__)

#: Matches "rf:123", "rf:123 synced", "rf:123 ticked", "rf:123 missing in
#: app" — and survives a human editing the rest of the status text, since
#: only the leading tag is parsed.
_ID_RE = re.compile(r"^\s*rf:(\d+)")

#: Guards every read-then-write sequence against this sheet — both push
#: and reconcile take it for their whole operation, so an append and a
#: reconcile (say) never interleave their reads and writes of the same
#: rows. Single uvicorn process, so a plain Lock is enough; nothing here
#: is ever awaited while held.
_lock = threading.Lock()

_client_override: Optional[SheetClient] = None
_client_cache: Optional[SheetClient] = None


def set_client_override(client: SheetClient | None) -> None:
    """Test hook: substitute a fake client and force sync on, bypassing
    config and real credentials entirely. `None` clears it."""
    global _client_override, _client_cache
    _client_override = client
    _client_cache = None


def sheet_sync_enabled() -> bool:
    """Whether any sync hook should do anything at all. An override always
    counts (tests use it without setting config); otherwise both the
    sheet id and the service-account key file must be set."""
    return _client_override is not None or bool(
        settings.google_sheet_id and settings.google_service_account_file
    )


def _client() -> SheetClient:
    global _client_cache
    if _client_override is not None:
        return _client_override
    if _client_cache is None:
        _client_cache = RestSheetClient(
            settings.google_sheet_id,
            settings.google_sheet_tab,
            settings.google_service_account_file,
        )
    return _client_cache


def _parse_id(cell: str | None) -> int | None:
    match = _ID_RE.match(cell or "")
    return int(match.group(1)) if match else None


def _status_cell(item_id: int, status: str) -> str:
    return f"rf:{item_id} {status}"


def _has_content(row: dict) -> bool:
    return bool((row.get("a") or "").strip() or (row.get("i") or "").strip())


# --------------------------------------------------------------------------
# Push: app -> sheet
# --------------------------------------------------------------------------


def sync_item(item_id: int) -> None:
    """Push one item's current state to the sheet.

    Appends a row if the item has never been linked (skipping a checked
    item — SPEC.md: "Do not append items that are already checked"), else
    refreshes that row's A/B/strikethrough/status. Intended as a
    `BackgroundTasks` target after any create/update; safe to call more
    than once (idempotent) and never raises.
    """
    if not sheet_sync_enabled():
        return
    with _lock:
        try:
            with Session(database.engine) as session:
                item = session.get(ShoppingItem, item_id)
                if item is None or item.sheet_detached:
                    return
                client = _client()
                if not item.sheet_linked:
                    if item.is_checked:
                        return
                    _append(client, item)
                else:
                    _refresh(client, item)
                item.sheet_dirty = False
                session.add(item)
                session.commit()
        except Exception:
            logger.exception("Sheet sync failed for shopping item %s", item_id)


def _append(client: SheetClient, item: ShoppingItem) -> None:
    rows = client.read_rows()
    last = max((r["row"] for r in rows if _has_content(r)), default=0)
    target = last + 1
    client.write_cells(
        {target: {"A": item.name, "B": amount_text(item), "I": _status_cell(item.id, "synced")}}
    )
    item.sheet_linked = True


def _refresh(client: SheetClient, item: ShoppingItem) -> None:
    rows = client.read_rows()
    row = next((r["row"] for r in rows if _parse_id(r["i"]) == item.id), None)
    if row is None:
        # Its row vanished from the sheet. Only a full reconcile resolves
        # that (ticks + detaches it) — a push in flight has no business
        # guessing why the row is missing.
        return
    status = "ticked" if item.is_checked else "synced"
    client.write_cells(
        {row: {"A": item.name, "B": amount_text(item), "I": _status_cell(item.id, status)}}
    )
    client.set_strikethrough([row], item.is_checked)


def delete_items_from_sheet(item_ids: list[int]) -> None:
    """Remove these items' rows from the sheet — the only function in the
    codebase allowed to delete a sheet row. Always re-reads column I
    fresh and deletes only rows whose id matches exactly, bottom-up. On
    any failure, queues a `SheetPendingDelete` for every requested id so
    the next on-demand sync retries; on success, clears any such pending
    rows for the ids just deleted (or found not to exist — already gone
    is not a failure).
    """
    wanted = {i for i in item_ids if i is not None}
    if not wanted or not sheet_sync_enabled():
        return
    with _lock:
        found: set[int] = set()
        failed = False
        try:
            client = _client()
            rows = client.read_rows()
            to_delete = []
            for row in rows:
                item_id = _parse_id(row["i"])
                if item_id in wanted:
                    to_delete.append(row["row"])
                    found.add(item_id)
            client.delete_rows(to_delete)
        except Exception:
            logger.exception("Sheet row deletion failed for items %s", sorted(wanted))
            failed = True

        with Session(database.engine) as session:
            if failed:
                for item_id in wanted:
                    if session.get(SheetPendingDelete, item_id) is None:
                        session.add(SheetPendingDelete(item_id=item_id))
            else:
                for item_id in wanted:
                    pending = session.get(SheetPendingDelete, item_id)
                    if pending is not None:
                        session.delete(pending)
            session.commit()


# --------------------------------------------------------------------------
# Pull: sheet -> app (POST /shopping/sheet-sync only)
# --------------------------------------------------------------------------


def _amount_from_cell(text: str) -> dict:
    """weight_grams/volume_ml/quantity(+unit) kwargs for a ShoppingItem
    imported from an unlinked row's column B — mirrors POST /shopping's
    own "unparseable or empty -> quantity 1" default."""
    text = (text or "").strip()
    if not text:
        return {"quantity": 1}
    qty, _qty_max, unit, rest = parse_amount(text)
    if qty is None or rest:
        return {"quantity": 1}
    if unit in MASS_G:
        grams, _source = to_grams(qty, unit)
        return {"weight_grams": grams} if grams is not None else {"quantity": 1}
    millilitres = to_ml(qty, unit)
    if millilitres is not None:
        return {"volume_ml": millilitres}
    if unit == MeasureUnit.piece:
        return {"quantity": qty}
    return {"quantity": qty, "unit": unit}


def reconcile(session: Session) -> dict:
    """Full two-way reconcile, run synchronously inside the request that
    calls `POST /shopping/sheet-sync`. See SPEC.md "Google Sheet sync" for
    the five numbered steps this follows."""
    empty = {"imported": 0, "linked": 0, "ticked": 0, "pushed": 0, "deleted": 0, "errors": []}
    if not sheet_sync_enabled():
        return empty

    with _lock:
        try:
            client = _client()
            raw_rows = client.read_rows()
        except Exception as exc:
            logger.exception("Sheet read failed during sync")
            return {**empty, "errors": [str(exc)]}

        rows = [r for r in raw_rows if _has_content(r)]
        next_row = max((r["row"] for r in raw_rows if _has_content(r)), default=0)

        sheet_ids: dict[int, int] = {}  # item_id -> row, from the sheet as read
        unlinked_rows = []
        for row in rows:
            item_id = _parse_id(row["i"])
            if item_id is not None:
                sheet_ids[item_id] = row["row"]
            else:
                unlinked_rows.append(row)

        all_items = list(session.exec(select(ShoppingItem)).all())
        by_id = {item.id: item for item in all_items}

        writes: dict[int, dict[str, str]] = {}
        strike_on: list[int] = []
        strike_off: list[int] = []
        imported = linked = ticked = pushed = 0

        # Step 2: unlinked rows -> link to a same-name unchecked, not-yet-
        # linked item, else import as a new one.
        already_linked_this_pass: set[int] = set()
        newly_imported_ids: set[int] = set()
        for row in unlinked_rows:
            name = (row["a"] or "").strip()
            if not name:
                continue
            match = next(
                (
                    item
                    for item in all_items
                    if not item.is_checked
                    and not item.sheet_linked
                    and item.id not in already_linked_this_pass
                    and item.name.strip().lower() == name.lower()
                ),
                None,
            )
            if match is not None:
                match.sheet_linked = True
                match.sheet_dirty = False
                session.add(match)
                already_linked_this_pass.add(match.id)
                sheet_ids[match.id] = row["row"]
                writes.setdefault(row["row"], {})["I"] = _status_cell(match.id, "synced")
                linked += 1
            else:
                ingredient = find_ingredient(session, name)
                new_item = ShoppingItem(
                    name=name,
                    ingredient_id=ingredient.id if ingredient else None,
                    sheet_linked=True,
                    **_amount_from_cell(row["b"]),
                )
                session.add(new_item)
                session.flush()  # need new_item.id for the I-column write below
                sheet_ids[new_item.id] = row["row"]
                newly_imported_ids.add(new_item.id)
                writes.setdefault(row["row"], {})["I"] = _status_cell(new_item.id, "synced")
                imported += 1

        # Step 3: linked app items whose id no longer appears anywhere on
        # the sheet -> tick off + detach (never re-appended).
        for item in all_items:
            if (
                item.sheet_linked
                and not item.sheet_detached
                and item.id not in sheet_ids
                and item.id not in already_linked_this_pass
            ):
                item.sheet_detached = True
                if not item.is_checked:
                    set_checked(item, True)
                    ticked += 1
                session.add(item)

        # Step 4: rows whose rf: id doesn't exist in the app at all.
        to_delete_rows: list[int] = []
        resolved_pending: set[int] = set()
        for item_id, row_number in list(sheet_ids.items()):
            if item_id in by_id or item_id in newly_imported_ids:
                continue
            pending = session.get(SheetPendingDelete, item_id)
            if pending is not None:
                to_delete_rows.append(row_number)
                resolved_pending.add(item_id)
            else:
                writes.setdefault(row_number, {})["I"] = _status_cell(item_id, "missing in app")

        # The step-4 deletions themselves run last, after every write below:
        # all row numbers here come from the one read at the top, and a
        # deletion shifts every row beneath it up by one.

        # Step 5: push — append unchecked/undetached/unlinked app items,
        # refresh dirty linked ones.
        for item in all_items:
            if item.sheet_detached or item.id in already_linked_this_pass:
                continue
            if not item.sheet_linked:
                if item.is_checked:
                    continue
                next_row += 1
                writes.setdefault(next_row, {}).update(
                    {"A": item.name, "B": amount_text(item), "I": _status_cell(item.id, "synced")}
                )
                item.sheet_linked = True
                item.sheet_dirty = False
                session.add(item)
                pushed += 1
            elif item.sheet_dirty:
                row_number = sheet_ids.get(item.id)
                if row_number is None:
                    # Its row wasn't in this read (e.g. deleted concurrently
                    # since — step 3 above only fires for items that were
                    # already linked at the *start* of this pass). Leave it
                    # dirty for the next sync rather than guessing a row.
                    continue
                status = "ticked" if item.is_checked else "synced"
                writes.setdefault(row_number, {}).update(
                    {"A": item.name, "B": amount_text(item), "I": _status_cell(item.id, status)}
                )
                (strike_on if item.is_checked else strike_off).append(row_number)
                item.sheet_dirty = False
                session.add(item)
                pushed += 1

        deleted = 0
        try:
            client.write_cells(writes)
            if strike_on:
                client.set_strikethrough(strike_on, True)
            if strike_off:
                client.set_strikethrough(strike_off, False)
            if to_delete_rows:
                client.delete_rows(sorted(set(to_delete_rows), reverse=True))
                deleted = len(set(to_delete_rows))
                for item_id in resolved_pending:
                    pending = session.get(SheetPendingDelete, item_id)
                    if pending is not None:
                        session.delete(pending)
        except Exception as exc:
            logger.exception("Sheet write failed during sync")
            session.commit()  # keep the imports/links/ticks already decided
            return {
                "imported": imported,
                "linked": linked,
                "ticked": ticked,
                "pushed": 0,
                "deleted": deleted,
                "errors": [str(exc)],
            }

        session.commit()
        return {
            "imported": imported,
            "linked": linked,
            "ticked": ticked,
            "pushed": pushed,
            "deleted": deleted,
            "errors": [],
        }
