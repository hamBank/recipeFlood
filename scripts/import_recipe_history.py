#!/usr/bin/env python3
"""Import the household's cooking-history spreadsheet.

    python scripts/import_recipe_history.py --input path/to/history.csv
    python scripts/import_recipe_history.py --input history.csv --limit 50 --dry-run

The export is never committed to this repo (it's someone's personal
browsing/cooking history) — `--input` is always required.

Every named row becomes, depending on what its source column held:

* **A URL** — fetched via `recipe_fetch.fetch_recipe_draft` (JSON-LD, else
  AI-from-text), deduped against existing recipes by `source_url`, and
  written as a full Recipe (`import_source=web`, `needs_review=True`). A
  fetch that fails, or a page with no usable title or ingredients, is
  *not* imported — it goes to the look-up CSV instead.
* **A book/magazine citation with a page number** ("Plenty More", p133) —
  deduped by `(source_name, source_page)`, written as a title-only stub
  with nothing to fetch. Still real provenance, just missing content
  until a human opens the book.
* **A citation with no page number, or neither a link nor a citation** —
  not specific enough to identify one recipe from. These go to the
  look-up CSV, not the database.

Every row that *did* resolve to a Recipe (of either kind above) also gets
a `PreparedEvent` for its cook date — one per row, so a recipe cooked a
dozen times over the years gets a dozen events even though it was only
imported once — and that date's resolved recipes are grouped into one
`CookList` per date (reusing an existing one on a re-run, so this script
is safe to run again over an updated export).

See SPEC.md's "Recipes from other sites, and copyright": nothing here
preserves formatting or fetches images, and `source_url`/`source_name`/
`source_page` are kept so the original is always one click away.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from backend.cook_lists import IMPORTED_COOK_LIST_DESCRIPTION  # noqa: E402
from backend.database import engine  # noqa: E402
from backend.models import (  # noqa: E402
    CookList,
    CookListRecipe,
    ImportSource,
    MeasureUnit,
    PreparedEvent,
    Recipe,
    RecipeIngredientIn,
    RecipeStepIn,
)
from backend.recipe_fetch import fetch_recipe_draft  # noqa: E402
from backend.recipe_history import CookRecord, parse_rows  # noqa: E402
from backend.recipes_service import (  # noqa: E402
    allocate_slug,
    apply_ingredients,
    apply_steps,
    apply_tags,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "recipe_html"
DEFAULT_LOOKUP_OUTPUT = REPO_ROOT / "data" / "recipes_to_look_up.csv"

#: Marks a CookList this script created, so a re-run finds and extends it
#: instead of creating a second list for the same date. Shared with
#: backend/cook_lists.py, which uses the same marker to filter these back
#: out of quick-add's "most recent list" lookup.
COOK_LIST_MARKER = IMPORTED_COOK_LIST_DESCRIPTION

_UNIT_VALUES = {unit.value for unit in MeasureUnit}


def to_ingredient_inputs(items: list[dict]) -> list[RecipeIngredientIn]:
    """Draft ingredient dicts -> the input schema `apply_ingredients` takes.

    An unrecognised unit becomes None rather than an error: the line still
    imports with its raw text intact.
    """
    result = []
    for item in items:
        unit = item.get("unit")
        result.append(
            RecipeIngredientIn(
                name=item["name"],
                raw_text=item.get("raw_text"),
                quantity=item.get("quantity"),
                quantity_max=item.get("quantity_max"),
                unit=MeasureUnit(unit) if unit in _UNIT_VALUES else None,
                note=item.get("note"),
                optional=bool(item.get("optional")),
                group=item.get("group"),
            )
        )
    return result


def _apply_draft(session: Session, recipe: Recipe, draft: dict, *, tier: str, source_url: str) -> None:
    recipe.title = (draft.get("title") or recipe.title).strip()
    recipe.description = draft.get("description")
    recipe.servings = draft.get("servings")
    recipe.servings_note = draft.get("servings_note")
    recipe.prep_minutes = draft.get("prep_minutes")
    recipe.cook_minutes = draft.get("cook_minutes")
    recipe.storage = draft.get("storage")
    recipe.units_system = "au"
    recipe.import_source = ImportSource.web
    recipe.needs_review = True
    recipe.source_url = source_url
    recipe.source_name = None
    recipe.source_page = None
    confidence = draft.get("confidence") or 0.0
    uncertain = draft.get("uncertain") or []
    recipe.review_note = (
        f"web import ({tier}), confidence {confidence:.2f}"
        + (f"; {'; '.join(uncertain)}" if uncertain else "")
    )
    session.add(recipe)
    session.flush()

    apply_tags(session, recipe, list(draft.get("tags") or []))
    apply_ingredients(
        session, recipe, to_ingredient_inputs(draft.get("ingredients") or []), auto_create=True
    )
    apply_steps(
        session,
        recipe,
        [RecipeStepIn(text=s["text"] if isinstance(s, dict) else s) for s in (draft.get("steps") or [])],
    )


def _resolve_url_recipe(
    session: Session,
    cache: dict[str, Recipe | None],
    cache_dir: Path,
    record: CookRecord,
) -> tuple[Recipe | None, str | None]:
    """A Recipe for `record.url`, fetching and creating one if needed.

    Returns (recipe, failure_reason). `cache` remembers both hits and
    misses for this URL within the run, so a recipe cooked fifty times
    only ever gets fetched once — and a URL that failed once doesn't get
    retried fifty times too.
    """
    url = record.url
    assert url is not None
    if url in cache:
        recipe = cache[url]
        return recipe, (None if recipe else "fetch failed (see earlier row for this URL)")

    recipe = session.exec(select(Recipe).where(Recipe.source_url == url)).first()
    if recipe is not None:
        # Deliberately not re-fetched or re-applied: this recipe already
        # went through needs_review once, and a re-run (the CSV gaining
        # new rows over time) must not clobber whatever a human has since
        # edited. Only new PreparedEvents/CookList membership get added.
        cache[url] = recipe
        return recipe, None

    try:
        fetched = fetch_recipe_draft(url, cache_dir=cache_dir)
        if not fetched.draft.get("title") and not fetched.draft.get("ingredients"):
            raise ValueError("fetched page had no usable title or ingredients")
    except Exception as exc:  # noqa: BLE001 - any failure just means "couldn't import this one"
        cache[url] = None
        return None, f"fetch failed: {exc}"

    recipe = Recipe(slug=allocate_slug(session, fetched.draft.get("title") or record.name), title=record.name)
    _apply_draft(session, recipe, fetched.draft, tier=fetched.tier, source_url=url)
    cache[url] = recipe
    return recipe, None


def _resolve_book_recipe(
    session: Session,
    cache: dict[tuple[str, int], Recipe],
    book_name: str,
    book_page: int,
    title: str,
) -> Recipe:
    key = (book_name, book_page)
    recipe = cache.get(key)
    if recipe is not None:
        return recipe

    recipe = session.exec(
        select(Recipe).where(
            Recipe.source_name == book_name,
            Recipe.source_page == book_page,
            Recipe.import_source == ImportSource.web,
        )
    ).first()
    if recipe is None:
        recipe = Recipe(
            slug=allocate_slug(session, title),
            title=title,
            source_name=book_name,
            source_page=book_page,
            import_source=ImportSource.web,
            needs_review=True,
            review_note="web import (book citation) — open the reference and add the recipe",
        )
        session.add(recipe)
        session.flush()
    cache[key] = recipe
    return recipe


def _record_event(
    session: Session, seen: set[tuple[int, date]], recipe: Recipe, cook_date: date | None
) -> bool:
    if cook_date is None:
        return False
    key = (recipe.id, cook_date)
    if key in seen:
        return False
    seen.add(key)
    exists = session.exec(
        select(PreparedEvent).where(
            PreparedEvent.recipe_id == recipe.id, PreparedEvent.prepared_on == cook_date
        )
    ).first()
    if exists is not None:
        return False
    session.add(PreparedEvent(recipe_id=recipe.id, prepared_on=cook_date))
    return True


def _backfill_cook_lists(session: Session, resolved_by_date: dict[date, set[int]]) -> tuple[int, int]:
    created = touched = 0
    for cook_date, recipe_ids in resolved_by_date.items():
        cook_list = session.exec(
            select(CookList).where(
                CookList.cook_date == cook_date, CookList.description == COOK_LIST_MARKER
            )
        ).first()
        if cook_list is None:
            # Already cooked, definitionally — stamped completed on
            # creation so it doesn't clutter the list screen. Only set at
            # creation, never on a later re-run touching an existing row,
            # in case a household has since reopened it by hand.
            cook_list = CookList(
                cook_date=cook_date, description=COOK_LIST_MARKER, completed=True
            )
            session.add(cook_list)
            session.flush()
            created += 1
        else:
            touched += 1

        existing_ids = {
            entry.recipe_id
            for entry in session.exec(
                select(CookListRecipe).where(CookListRecipe.cook_list_id == cook_list.id)
            ).all()
        }
        position = len(existing_ids)
        for recipe_id in sorted(recipe_ids - existing_ids):
            session.add(CookListRecipe(cook_list_id=cook_list.id, recipe_id=recipe_id, position=position))
            position += 1
    return created, touched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True, help="the cooking-history CSV export")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--lookup-output", type=Path, default=DEFAULT_LOOKUP_OUTPUT)
    parser.add_argument("--limit", type=int, default=None, help="only process the first N rows")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"{args.input} not found", file=sys.stderr)
        return 1

    with args.input.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    records = parse_rows(rows)
    if args.limit:
        records = records[: args.limit]

    recipes_created = events_created = 0
    fetch_failures = no_source = 0
    url_cache: dict[str, Recipe | None] = {}
    book_cache: dict[tuple[str, int], Recipe] = {}
    event_seen: set[tuple[int, date]] = set()
    resolved_by_date: dict[date, set[int]] = defaultdict(set)
    lookup_rows: list[dict] = []

    with Session(engine) as session:
        for record in records:
            recipe: Recipe | None = None
            reason: str | None = None

            if record.url:
                before = record.url not in url_cache
                if before:
                    print(f"  fetching: {record.name} -> {record.url}", flush=True)
                recipe, reason = _resolve_url_recipe(session, url_cache, args.cache_dir, record)
                if before and recipe is not None:
                    recipes_created += 1
                elif before:
                    print(f"    failed: {reason}", flush=True)
            elif record.book_name and record.book_page:
                before = (record.book_name, record.book_page) not in book_cache
                recipe = _resolve_book_recipe(session, book_cache, record.book_name, record.book_page, record.name)
                if before:
                    recipes_created += 1
            elif record.book_name:
                reason = "book reference with no page number"
                no_source += 1
            else:
                reason = "no link or citation"
                no_source += 1

            if recipe is not None:
                if record.cook_date:
                    resolved_by_date[record.cook_date].add(recipe.id)
                if _record_event(session, event_seen, recipe, record.cook_date):
                    events_created += 1
            else:
                if reason and reason.startswith("fetch failed"):
                    fetch_failures += 1
                lookup_rows.append(
                    {
                        "cook_date": record.cook_date.isoformat() if record.cook_date else "",
                        "name": record.name,
                        "url": record.url or "",
                        "book_name": record.book_name or "",
                        "book_page": record.book_page or "",
                        "reason": reason or "",
                    }
                )

        cook_lists_created, cook_lists_touched = _backfill_cook_lists(session, resolved_by_date)

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    args.lookup_output.parent.mkdir(parents=True, exist_ok=True)
    with args.lookup_output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["cook_date", "name", "url", "book_name", "book_page", "reason"]
        )
        writer.writeheader()
        writer.writerows(lookup_rows)

    prefix = "dry run: " if args.dry_run else ""
    print(
        f"{prefix}{len(records)} rows processed\n"
        f"recipes created/matched: {recipes_created}\n"
        f"prepared events created: {events_created}\n"
        f"cook lists created: {cook_lists_created}, extended: {cook_lists_touched}\n"
        f"fetch failures: {fetch_failures}\n"
        f"no usable source: {no_source}\n"
        f"look-up CSV written to {args.lookup_output} ({len(lookup_rows)} rows)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
