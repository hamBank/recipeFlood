"""Two-way sync between the one permanent shopping list and a Google Sheet
the household already uses. See SPEC.md's "Google Sheet sync" for the
rules this module implements; the HARD SAFETY RULE there — never empty a
sheet row's cells except through `clear_items_from_sheet` or a reconcile,
id-matched against a fresh read of column I, never by cached row number —
is the one rule every function here is written around. No row is ever
deleted, inserted or moved: removing an item empties A, B and I and leaves
the row (its G formula and anything else in it) for the next item.

Every change goes to the sheet as one `write_rows` call, so a row's text,
status and strikethrough land together or not at all.

Two directions:

* **Push** (`sync_item`, `clear_items_from_sheet`) — fire-and-forget,
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
from .sheet_client import CLEARED, RestSheetClient, SheetClient
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


def _is_free(row: dict) -> bool:
    """A row with nothing in the app's own columns: a spare row set up in
    advance, or one an earlier removal emptied. Whatever else it holds (G's
    formula, anything in C–F or H) stays as it is."""
    return not any((row.get(col) or "").strip() for col in ("a", "b", "i"))


def _slots(rows: list[dict]):
    """Rows a new item can go in, top first: free rows within what was
    read, then the ones after it."""
    for row in rows:
        if _is_free(row):
            yield row["row"]
    after = max((row["row"] for row in rows), default=0)
    while True:
        after += 1
        yield after


def _row_cells(item: ShoppingItem) -> dict:
    status = "ticked" if item.is_checked else "synced"
    return {
        "A": item.name,
        "B": amount_text(item),
        "I": _status_cell(item.id, status),
        # Always stated, so a reused row never keeps an old strikethrough.
        "strike": item.is_checked,
    }


# --------------------------------------------------------------------------
# Push: app -> sheet
# --------------------------------------------------------------------------


def sync_item(item_id: int) -> None:
    """Push one item's current state to the sheet, along with anything
    else still owed: other items whose own push failed (left dirty) or
    never happened.

    A never-linked item takes the first free row (skipped while checked —
    SPEC.md: "Do not append items that are already checked"); a linked one
    has its row's A/B/strikethrough/status refreshed. One read and one
    write, however many items are owed, so ticking things off quickly in a
    shop can't run past Google's per-minute quota one item at a time.
    Intended as a `BackgroundTasks` target after any create/update; safe to
    call more than once (idempotent) and never raises.
    """
    if not sheet_sync_enabled():
        return
    with _lock:
        try:
            with Session(database.engine) as session:
                owed = [
                    item
                    for item in session.exec(
                        select(ShoppingItem).where(ShoppingItem.sheet_detached == False)  # noqa: E712
                    ).all()
                    if (
                        (item.id == item_id or item.sheet_dirty)
                        if item.sheet_linked
                        else not item.is_checked
                    )
                ]
                if not owed:
                    return
                client = _client()
                rows = client.read_rows()
                row_of = _rows_by_id(rows)
                slots = _slots(rows)
                updates: dict[int, dict] = {}
                pushed = []
                for item in owed:
                    if item.sheet_linked:
                        row = row_of.get(item.id)
                        if row is None:
                            # Its row vanished from the sheet. Only a full
                            # reconcile resolves that (ticks + detaches it) —
                            # a push has no business guessing why.
                            continue
                    else:
                        row = next(slots)
                    updates[row] = _row_cells(item)
                    pushed.append(item)
                client.write_rows(updates)
                for item in pushed:
                    item.sheet_linked = True
                    item.sheet_dirty = False
                    session.add(item)
                session.commit()
        except Exception:
            logger.exception("Sheet sync failed for shopping item %s", item_id)


def _rows_by_id(rows: list[dict]) -> dict[int, int]:
    """item id -> the first row carrying it in column I."""
    found: dict[int, int] = {}
    for row in rows:
        item_id = _parse_id(row["i"])
        if item_id is not None:
            found.setdefault(item_id, row["row"])
    return found


def clear_items_from_sheet(item_ids: list[int]) -> None:
    """Empty these items' rows on the sheet — the only push that removes
    anything. Always re-reads column I fresh and clears only rows whose id
    matches exactly, and only their A, B and I (plus the strikethrough):
    the row stays, with its G formula and anything else in it. On any
    failure, queues a `SheetPendingDelete` for every requested id so the
    next on-demand sync retries; on success, clears any such pending rows
    for the ids just cleared (or found not to exist — already gone is not a
    failure).
    """
    wanted = {i for i in item_ids if i is not None}
    if not wanted or not sheet_sync_enabled():
        return
    with _lock:
        failed = False
        try:
            client = _client()
            rows = client.read_rows()
            client.write_rows(
                {row["row"]: dict(CLEARED) for row in rows if _parse_id(row["i"]) in wanted}
            )
        except Exception:
            logger.exception("Clearing sheet rows failed for items %s", sorted(wanted))
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
    empty = {"imported": 0, "linked": 0, "ticked": 0, "pushed": 0, "cleared": 0, "errors": []}
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
        slots = _slots(raw_rows)

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

        writes: dict[int, dict] = {}
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

        # Step 4: rows whose rf: id doesn't exist in the app at all. One
        # removed in the app whose clearing failed is cleared now; any other
        # is flagged for a human to look at.
        to_clear: set[int] = set()
        resolved_pending: set[int] = set()
        for item_id, row_number in list(sheet_ids.items()):
            if item_id in by_id or item_id in newly_imported_ids:
                continue
            pending = session.get(SheetPendingDelete, item_id)
            if pending is not None:
                writes[row_number] = dict(CLEARED)
                to_clear.add(row_number)
                resolved_pending.add(item_id)
            else:
                writes.setdefault(row_number, {})["I"] = _status_cell(item_id, "missing in app")

        # Step 5: push — append unchecked/undetached/unlinked app items,
        # refresh dirty linked ones.
        for item in all_items:
            if item.sheet_detached or item.id in already_linked_this_pass:
                continue
            if not item.sheet_linked:
                if item.is_checked:
                    continue
                writes[next(slots)] = _row_cells(item)
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
                writes.setdefault(row_number, {}).update(_row_cells(item))
                item.sheet_dirty = False
                session.add(item)
                pushed += 1

        try:
            client.write_rows(writes)
        except Exception as exc:
            # Nothing reached the sheet (the write is all-or-nothing), so
            # none of the links, imports, appends or clears decided above
            # are real: committing them would leave items "linked" to rows
            # that carry no rf: id, and the next sync would tick those items
            # off (step 3) and re-import the rows as duplicates (step 2).
            # Undo the lot and let the next sync redo it.
            logger.exception("Sheet write failed during sync")
            session.rollback()
            return {**empty, "errors": [str(exc)]}

        for item_id in resolved_pending:
            pending = session.get(SheetPendingDelete, item_id)
            if pending is not None:
                session.delete(pending)
        session.commit()
        return {
            "imported": imported,
            "linked": linked,
            "ticked": ticked,
            "pushed": pushed,
            "cleared": len(to_clear),
            "errors": [],
        }
