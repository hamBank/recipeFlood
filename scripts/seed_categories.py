#!/usr/bin/env python3
"""Create (or refresh) the recipe categories from data/categories.json.

Idempotent — matched by slug, so re-running after editing the JSON updates
names, descriptions and ordering without disturbing recipe links. Run by
deploy.sh on every deploy.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.models import Category  # noqa: E402

CATEGORIES_PATH = Path(__file__).resolve().parent.parent / "data" / "categories.json"


def seed(session: Session, definitions: list[dict]) -> tuple[int, int]:
    created = updated = 0
    for definition in definitions:
        existing = session.exec(
            select(Category).where(Category.slug == definition["slug"])
        ).first()
        if existing is None:
            session.add(Category(**definition))
            created += 1
        else:
            for field, value in definition.items():
                setattr(existing, field, value)
            session.add(existing)
            updated += 1
    session.commit()
    return created, updated


def main() -> int:
    definitions = json.loads(CATEGORIES_PATH.read_text())
    with Session(engine) as session:
        created, updated = seed(session, definitions)
    print(f"categories: {created} created, {updated} updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
