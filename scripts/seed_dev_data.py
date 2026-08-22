#!/usr/bin/env python3
"""Optional local fixtures: the navigation sections, the starter pantry, and
some prepared-log entries so the "recently cooked" views aren't empty.

    python scripts/seed_dev_data.py

Safe to re-run. Does not touch production data patterns — for a real
collection use scripts/load_snapshot.py.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.models import PreparedEvent, Recipe  # noqa: E402
from scripts.seed_sections import SECTIONS_PATH, seed  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    with Session(engine) as session:
        created, updated = seed(session, json.loads(SECTIONS_PATH.read_text()))
        print(f"sections: {created} created, {updated} updated")

    subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "seed_pantry.py")], check=True)

    with Session(engine) as session:
        recipes = session.exec(select(Recipe).limit(40)).all()
        if not recipes:
            print("no recipes yet — run: python -m scripts.load_snapshot --heuristic")
            return 0
        if session.exec(select(PreparedEvent)).first():
            print("prepared log already has entries — leaving it alone")
            return 0

        rng = random.Random(20260822)  # deterministic, so reruns look the same
        for recipe in rng.sample(recipes, min(12, len(recipes))):
            for _ in range(rng.randint(1, 3)):
                session.add(
                    PreparedEvent(
                        recipe_id=recipe.id,
                        prepared_on=date.today() - timedelta(days=rng.randint(1, 700)),
                        rating=rng.choice([None, 3, 4, 4, 5, 5]),
                    )
                )
        session.commit()
    print("prepared log: seeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
