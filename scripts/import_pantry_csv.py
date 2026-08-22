#!/usr/bin/env python3
"""Import a shopping-list export into the master ingredient list.

    python -m scripts.import_pantry_csv shopping_list.csv
    python -m scripts.import_pantry_csv shopping_list.csv --dry-run
    python -m scripts.import_pantry_csv shopping_list.csv --report out.csv

Expects the columns Item, Weight, Location, Price. The rationalising rules
live in backend/shopping_list.py, where they are unit-tested; this script is
the I/O around them.

**Nothing is duplicated.** Every candidate is matched against the existing
pantry with the same matcher the recipe importer uses (name, slug, alias,
and a normalised form that strips preparation words), so an item already
there is updated in place rather than added again. Within the file itself,
rows collapse on whitespace, case, plurals and — where there is evidence
for the correct spelling — typos.

**Updates only fill blanks.** An existing pantry row keeps every value it
already has; the import can add a shop, a package size or a price where
there wasn't one, never overwrite. That way it is safe to re-run, and safe
to run after you have priced things by hand.

Note the file itself is deliberately not committed: a real shopping list
names family members and their medications, and this repository is public.
Keep it outside the repo, or in data/ where .gitignore excludes it.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.models import Ingredient, utcnow  # noqa: E402
from backend.recipes_service import find_ingredient, normalise_ingredient_name  # noqa: E402
from backend.shopping_list import (  # noqa: E402
    clean_item,
    correct_spelling,
    is_food,
    map_source,
    pack_metrics,
    parse_number,
    resolve_source,
)
from backend.slugs import unique_slug  # noqa: E402
from backend.units import DENSITIES, PIECE_WEIGHTS  # noqa: E402

REQUIRED_COLUMNS = {"Item", "Weight", "Location", "Price"}


def build_vocabulary(session: Session) -> set[str]:
    """Spellings we have *independent* evidence for — see `correct_spelling`.

    Two sources only: what the pantry already holds (names and aliases,
    which came from the recipes), and the ingredient keyword tables in
    units.py.

    Deliberately NOT included: names this file happens to repeat. An
    earlier version counted a name used twice as evidence, and the shopping
    list uses "vegimite" and "mozarella" more than once — so those became
    canonical and pulled the correct spellings onto them. Repetition in a
    shopping list is evidence of habit, not of spelling.
    """
    vocabulary: set[str] = set()
    for ingredient in session.exec(select(Ingredient)).all():
        vocabulary.add(ingredient.name.lower())
        vocabulary.update(a.lower() for a in (ingredient.aliases or []))
    vocabulary.update(DENSITIES)
    vocabulary.update(PIECE_WEIGHTS)
    return vocabulary


def aliases_for(group: dict, canonical: str) -> set[str]:
    """Every spelling seen for this item, minus the one we chose to keep."""
    return {v for v in group["variants"] if v and v != canonical}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path, help="write a per-item CSV of what was decided")
    args = parser.parse_args()

    if not args.csv_path.exists():
        print(f"{args.csv_path} not found", file=sys.stderr)
        return 1

    with args.csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            print(f"missing column(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 1
        rows = list(reader)

    cleaned = [(clean_item(r["Item"]), r) for r in rows]
    cleaned = [(name, r) for name, r in cleaned if name]
    blank = len(rows) - len(cleaned)

    with Session(engine) as session:
        vocabulary = build_vocabulary(session)
        corrections = correct_spelling([n for n, _ in cleaned], vocabulary)

        # Group every row that means the same item.
        groups: dict[str, dict] = {}
        for original, row in cleaned:
            name = corrections.get(original, original)
            key = normalise_ingredient_name(name) or name
            group = groups.setdefault(
                key,
                {"display": name, "sources": [], "grams": [], "costs": [],
                 "rows": 0, "variants": set()},
            )
            group["rows"] += 1
            # Every spelling that fed this group, including the one we
            # corrected away from. Stored as aliases below.
            group["variants"].add(name)
            group["variants"].add(original)
            source = map_source(row["Location"])
            group["sources"].append(source)
            grams, cents = pack_metrics(parse_number(row["Weight"]), parse_number(row["Price"]))
            if grams is not None:
                group["grams"].append(grams)
            if cents is not None:
                group["costs"].append(cents)

        created = updated = enriched = 0
        non_food = 0
        report: list[dict] = []

        for key, group in sorted(groups.items()):
            display = group["display"]
            source = resolve_source(group["sources"])
            food = is_food(display, source)
            if not food:
                non_food += 1
            # Median-ish: the smallest of the deliberate values, which is the
            # conservative choice for a package size and for a price.
            grams = min(group["grams"]) if group["grams"] else None
            cents = min(group["costs"]) if group["costs"] else None

            existing = find_ingredient(session, display)
            action = "update" if existing else "create"
            if existing is None:
                slug = unique_slug(
                    display,
                    lambda s: session.exec(
                        select(Ingredient).where(Ingredient.slug == s)
                    ).first()
                    is not None,
                )
                existing = Ingredient(
                    slug=slug, name=display, aliases=sorted(aliases_for(group, display))
                )
                session.add(existing)
                session.flush()
                existing.source = source
                existing.is_food = food
                existing.package_size_grams = grams
                existing.cost_per_kg_cents = cents
                created += 1
            else:
                # Fill blanks only — never overwrite what is already known.
                changed = False
                if existing.source.value == "supermarket" and source.value != "supermarket":
                    existing.source, changed = source, True
                if existing.package_size_grams is None and grams is not None:
                    existing.package_size_grams, changed = grams, True
                if existing.cost_per_kg_cents is None and cents is not None:
                    existing.cost_per_kg_cents, changed = cents, True
                if existing.is_food and not food:
                    existing.is_food, changed = False, True
                # Bind every shopping-list spelling to this row as an alias.
                # This is what makes a re-import stable: the correction rules
                # consult the pantry, so they can stop firing as the pantry
                # grows — but an alias is permanent, and find_ingredient
                # checks aliases, so the misspelling still lands here rather
                # than becoming a second row. It also means a recipe written
                # with "capcicum" matches the capsicum row.
                aliases = {a.lower() for a in (existing.aliases or [])}
                merged = aliases | aliases_for(group, existing.name.lower())
                if merged != aliases:
                    existing.aliases = sorted(merged)
                    changed = True
                updated += 1
                enriched += 1 if changed else 0

            if not args.dry_run:
                existing.updated_at = utcnow()
                session.add(existing)

            report.append(
                {
                    "item": display,
                    "matched_key": key,
                    "action": action,
                    "rows_collapsed": group["rows"],
                    "source": source.value,
                    "is_food": food,
                    "package_size_grams": grams or "",
                    "cost_per_kg_cents": cents or "",
                }
            )

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    if args.report:
        with args.report.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(report[0].keys()))
            writer.writeheader()
            writer.writerows(report)
        print(f"report -> {args.report}")

    print(
        f"{'DRY RUN — nothing written' if args.dry_run else 'imported'}\n"
        f"  rows read            : {len(rows)} ({blank} with no item name)\n"
        f"  spellings corrected  : {len(corrections)}\n"
        f"  distinct items       : {len(groups)}\n"
        f"  created              : {created}\n"
        f"  matched existing     : {updated} ({enriched} gained new detail)\n"
        f"  marked as non-food   : {non_food}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
