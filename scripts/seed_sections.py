#!/usr/bin/env python3
"""Create (or refresh) the section tags from data/sections.json.

Section tags are the site's navigation — the curated handful of the tag
table that carry `is_section` (see the Tag docstring in backend/models.py).

Idempotent, matched by slug. Re-running after editing the JSON updates
names, descriptions and nav order without disturbing any recipe link. A
tag that already exists as a free-form label is *promoted* rather than
duplicated, so the recipes already carrying it join the section
immediately. Run by deploy.sh on every deploy.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.models import Tag  # noqa: E402

SECTIONS_PATH = Path(__file__).resolve().parent.parent / "data" / "sections.json"


def seed(session: Session, definitions: list[dict]) -> tuple[int, int]:
    created = promoted = 0
    for definition in definitions:
        existing = session.exec(
            select(Tag).where(Tag.slug == definition["slug"])
        ).first()
        if existing is None:
            session.add(Tag(**definition))
            created += 1
        else:
            for field, value in definition.items():
                setattr(existing, field, value)
            session.add(existing)
            promoted += 1
    session.commit()
    return created, promoted


def main() -> int:
    definitions = json.loads(SECTIONS_PATH.read_text())
    with Session(engine) as session:
        created, promoted = seed(session, definitions)
    print(f"sections: {created} created, {promoted} updated/promoted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
