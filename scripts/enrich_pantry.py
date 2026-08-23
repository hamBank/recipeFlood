#!/usr/bin/env python3
"""Fill in nutrition and price for pantry items, using Claude.

    python scripts/fetch_afcd.py                          # once, first
    python -m scripts.enrich_pantry --dry-run
    python -m scripts.enrich_pantry --limit 20 --report /tmp/enrich.csv
    python -m scripts.enrich_pantry
    python -m scripts.enrich_pantry --only nutrition
    python -m scripts.enrich_pantry --resume-from 500

Nutrition is filled in two passes, in this order:

  1. **AFCD** (backend/afcd.py) — the government-published Australian Food
     Composition Database, matched locally with no network call. When it
     finds a confident match, that is the real, published figure for that
     food, labelled `nutrition_source = "AFCD (<matched food>)"`. Run
     `scripts/fetch_afcd.py` once first; without it this pass matches
     nothing and everything falls through to step 2.
  2. **Claude** (backend/ingredient_enrichment.py), for whatever AFCD
     didn't confidently match. Labelled `nutrition_source =
     "AI estimate (Claude)"` — a well-informed guess, not a lookup.

Needs ANTHROPIC_API_KEY for step 2 and for price, which AFCD does not
carry at all and which only needs to be roughly right — see
backend/ingredient_enrichment.py for that accuracy stance. Neither pass
ever overwrites a value already on the row — this only fills blanks.

**Selection.** By default, every `is_food` ingredient missing nutrition,
a price, or a package size. `--only nutrition` / `--only price` narrows
that to just one, which is worth doing once you've reviewed a batch of
prices and want to stop re-asking for items that already have one.

**Reclassification.** The model is also asked, for each item, whether it's
actually a human food at all — the same question backend/pantry_import.py
answers with a keyword list on the way in, but with more context. When it
says no with any confidence, this script sets `is_food = False` on that
row and writes nothing else to it, catching what the keyword list missed
(a shopping list's "cat mince" or "cat tin" has no food keyword in it).

**Cost.** Batched — one API call covers ~20 ingredients — so a pantry of a
few thousand items costs dozens of calls, not thousands. Flushed to the
database after every batch, so an interrupted run loses at most one
batch; `--resume-from N` skips the first N candidates (sorted by id) to
continue after a stop without re-spending on what already landed.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from backend.afcd import find_match, load_afcd  # noqa: E402
from backend.database import engine  # noqa: E402
from backend.ingredient_enrichment import (  # noqa: E402
    cost_source_label,
    enrich_names,
    is_configured,
)
from backend.models import Ingredient, utcnow  # noqa: E402
from backend.nutrition import NUTRIENT_FIELDS, has_nutrition  # noqa: E402

DEFAULT_BATCH_SIZE = 20


def needs_enrichment(ingredient: Ingredient, only: str) -> bool:
    if not ingredient.is_food:
        return False
    wants_nutrition = only in ("all", "nutrition") and not has_nutrition(ingredient)
    wants_price = only in ("all", "price") and ingredient.cost_per_kg_cents is None
    wants_package = only == "all" and ingredient.package_size_grams is None
    return wants_nutrition or wants_price or wants_package


def apply_afcd_match(ingredient: Ingredient, afcd_food, score: float) -> list[str]:
    """Write an AFCD match's nutrients onto a row that has none yet.

    The matched food's *name* becomes part of nutrition_source — not just
    "AFCD" — so a look at the Pantry page shows exactly which government
    entry answered for "chicken thigh", and a wrong match is something a
    human can actually catch and fix, not a black box.
    """
    if has_nutrition(ingredient):
        return []
    changed = []
    for field in (*NUTRIENT_FIELDS,):
        value = afcd_food.nutrients.get(field)
        if value is not None:
            setattr(ingredient, field, value)
            changed.append(field)
    if changed:
        ingredient.nutrition_source = f"AFCD ({afcd_food.name})"
        ingredient.nutrition_updated_at = utcnow()
    return changed


def apply_result(ingredient: Ingredient, result: dict, *, only: str) -> list[str]:
    """Write a normalised result onto a row, filling blanks only.
    Returns the field names actually changed, for the report."""
    changed: list[str] = []

    if not result["is_human_food"]:
        if ingredient.is_food:
            ingredient.is_food = False
            changed.append("is_food")
        return changed

    if only in ("all", "nutrition"):
        nutrition = result["nutrition"]
        if not has_nutrition(ingredient) and any(
            nutrition.get(f) is not None for f in (*NUTRIENT_FIELDS, "energy_kj")
        ):
            for field in (*NUTRIENT_FIELDS, "energy_kj"):
                value = nutrition.get(field)
                if value is not None:
                    setattr(ingredient, field, value)
                    changed.append(field)
            ingredient.nutrition_source = "AI estimate (Claude)"
            ingredient.nutrition_updated_at = utcnow()

    if only in ("all", "price") and ingredient.cost_per_kg_cents is None:
        if result["cost_per_kg_cents"] is not None:
            ingredient.cost_per_kg_cents = result["cost_per_kg_cents"]
            ingredient.cost_source = cost_source_label()
            ingredient.cost_updated_at = utcnow()
            changed.append("cost_per_kg_cents")

    if only == "all" and ingredient.package_size_grams is None:
        if result["package_size_grams"] is not None:
            ingredient.package_size_grams = result["package_size_grams"]
            changed.append("package_size_grams")

    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--only", choices=["all", "nutrition", "price"], default="all",
        help="restrict what is requested and written (default: all)",
    )
    parser.add_argument(
        "--phase", choices=["all", "local", "network"], default="all",
        help=(
            "which passes to run. 'local' is the AFCD nutrition match only — "
            "no network, no API key, no cost, finishes in seconds. 'network' "
            "is the Claude pass only (nutrition Claude has to guess, plus "
            "price and package size). Default runs local then network."
        ),
    )
    parser.add_argument(
        "--skip-afcd", action="store_true",
        help="alias for --phase network, kept for existing scripts",
    )
    parser.add_argument(
        "--concurrency", type=int, default=4,
        help="Claude batches to keep in flight at once (default: 4)",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=None, help="stop after N ingredients")
    parser.add_argument(
        "--resume-from", type=int, default=0,
        help="skip the first N Claude candidates (sorted by id) — for continuing a stopped run",
    )
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds between batches")
    parser.add_argument("--report", type=Path, help="write a per-item CSV of what was set")
    args = parser.parse_args()

    report_rows: list[dict] = []
    afcd_matched = enriched = reclassified = failed = 0

    with Session(engine) as session:
        # --- Pass 1: AFCD, local, free. Runs before any API key check, and
        # over every candidate regardless of --limit/--resume-from — those
        # exist to bound Claude spend, and this pass has none. ---
        run_local = args.phase in ("all", "local") and not args.skip_afcd
        run_network = args.phase in ("all", "network")

        if run_local and args.only in ("all", "nutrition"):
            afcd_foods = load_afcd()
            if not afcd_foods:
                print(
                    "no local AFCD data (run scripts/fetch_afcd.py first) — "
                    + (
                        "nothing for this phase to do"
                        if args.phase == "local"
                        else "falling through to AI estimates for nutrition"
                    )
                )
            else:
                nutrition_candidates = [
                    i
                    for i in session.exec(select(Ingredient)).all()
                    if i.is_food and not has_nutrition(i)
                ]
                for ingredient in nutrition_candidates:
                    match = find_match(ingredient.name, afcd_foods)
                    if match is None:
                        continue
                    food, score = match
                    changed = apply_afcd_match(ingredient, food, score)
                    if changed:
                        afcd_matched += 1
                        if not args.dry_run:
                            session.add(ingredient)
                        report_rows.append(
                            {
                                "name": ingredient.name, "source": "AFCD",
                                "matched_to": food.name, "match_score": round(score, 2),
                                "is_human_food": True, "confidence": "", "note": "",
                                "changed_fields": ";".join(changed),
                                "cost_per_kg_cents": "", "calories_kcal": ingredient.calories_kcal or "",
                            }
                        )
                if not args.dry_run:
                    session.flush()
                print(f"AFCD: matched {afcd_matched}/{len(nutrition_candidates)} against local data")

        # --- Pass 2: Claude, for whatever pass 1 didn't cover, plus price
        # (which AFCD never carries) and package size. This is the slow,
        # costed half — everything above is local and free, which is why
        # --phase local exists to run it on its own. ---
        candidates = sorted(
            (i for i in session.exec(select(Ingredient)).all() if needs_enrichment(i, args.only)),
            key=lambda i: i.id,
        )
        candidates = candidates[args.resume_from :]
        if args.limit is not None:
            candidates = candidates[: args.limit]

        if not run_network:
            if candidates:
                print(
                    f"\n{len(candidates)} item(s) still need Claude — "
                    "run again with --phase network to fill those in."
                )
        elif not candidates:
            print("nothing left for Claude — every food item already has what --only asked for")
        elif not is_configured():
            print(
                f"\n{len(candidates)} item(s) still need Claude, but ANTHROPIC_API_KEY is not "
                "set — see .env.example. Nutrition from AFCD (if any) is still saved below."
            )
        else:
            batches = [
                candidates[start : start + args.batch_size]
                for start in range(0, len(candidates), args.batch_size)
            ]
            workers = max(1, args.concurrency)
            print(
                f"Claude: {len(candidates)} ingredient(s) in {len(batches)} batches "
                f"of {args.batch_size}, {workers} at a time"
            )

            def fetch(batch: list[Ingredient]) -> dict[str, dict]:
                names = [i.name for i in batch]
                notes: list[str] = []
                results = enrich_names(names, on_note=notes.append)
                for note in notes:
                    print(f"    - {note}", file=sys.stderr)
                return results

            done = 0
            # Batches are fetched in parallel but applied on this thread:
            # the API calls are what the run waits on, and a Session is not
            # safe to write from several threads at once.
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for group_start in range(0, len(batches), workers):
                    group = batches[group_start : group_start + workers]
                    for batch, results in zip(group, pool.map(fetch, group)):
                        done += len(batch)
                        names = [i.name for i in batch]
                        print(f"  [{done}/{len(candidates)}] {', '.join(names[:4])}...")

                        for ingredient in batch:
                            result = results.get(ingredient.name)
                            if result is None:
                                failed += 1
                                continue
                            changed = apply_result(ingredient, result, only=args.only)
                            if changed:
                                if not args.dry_run:
                                    session.add(ingredient)
                                if "is_food" in changed:
                                    reclassified += 1
                                else:
                                    enriched += 1
                            report_rows.append(
                                {
                                    "name": ingredient.name, "source": "Claude",
                                    "matched_to": "", "match_score": "",
                                    "is_human_food": result["is_human_food"],
                                    "confidence": result["confidence"],
                                    "note": result["note"] or "",
                                    "changed_fields": ";".join(changed),
                                    "cost_per_kg_cents": ingredient.cost_per_kg_cents or "",
                                    "calories_kcal": ingredient.calories_kcal or "",
                                }
                            )

                    if not args.dry_run:
                        session.flush()  # a stop here loses at most this group
                    if args.sleep:
                        time.sleep(args.sleep)

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    if args.report and report_rows:
        with args.report.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(report_rows[0].keys()))
            writer.writeheader()
            writer.writerows(report_rows)
        print(f"report -> {args.report}")

    print(
        f"\n{'DRY RUN — nothing written' if args.dry_run else 'done'}\n"
        f"  AFCD matches  : {afcd_matched}\n"
        f"  AI enriched   : {enriched}\n"
        f"  reclassified  : {reclassified} (flagged not-food, nutrition/price skipped)\n"
        f"  no usable data: {failed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
