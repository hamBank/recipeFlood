#!/usr/bin/env python3
"""One-off backfill for existing cooking-list memberships.

    python scripts/backfill_cook_list_prepared_events.py
    python scripts/backfill_cook_list_prepared_events.py --dry-run

`POST /cook-lists/{id}/recipes` now logs a `PreparedEvent` for every
recipe added to a list (see SPEC.md "Adding a recipe logs a prepared
event"), but that only happens going forward — a `CookListRecipe` row
created before that change has no linked event. This walks every
existing cooking list and recipe on it through the same
`sync_prepared_event` the live endpoint uses, so already-planned cooking
gets the same "made this" history a fresh add would.

Safe to re-run: syncing an entry that's already linked just refreshes its
date (a no-op if the list hasn't moved since), the same idempotency the
live endpoint relies on.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from backend.cook_lists import entries_of, sync_prepared_event  # noqa: E402
from backend.database import engine  # noqa: E402
from backend.models import CookList  # noqa: E402


def backfill(session: Session) -> tuple[int, int]:
    """Sync a `PreparedEvent` for every recipe on every existing cooking
    list. Returns (lists scanned, recipe memberships synced)."""
    cook_lists = session.exec(select(CookList)).all()
    touched = 0
    for cook_list in cook_lists:
        for entry in entries_of(session, cook_list.id):
            sync_prepared_event(session, cook_list, entry.recipe_id, cook_list.created_by)
            touched += 1
    return len(cook_lists), touched


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with Session(engine) as session:
        lists_scanned, touched = backfill(session)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    prefix = "dry run: " if args.dry_run else ""
    print(f"{prefix}{lists_scanned} cooking lists scanned, {touched} recipe memberships synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
