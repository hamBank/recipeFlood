#!/usr/bin/env python3
"""Step 4 of the blog import: load the structured snapshot into the database.

    python scripts/load_snapshot.py                    # data/recipes.json
    python scripts/load_snapshot.py --heuristic        # the offline snapshot
    python scripts/load_snapshot.py --with-images      # also attach photos
    python scripts/load_snapshot.py --dry-run

Idempotent, keyed on `source_url`: re-running updates the recipes it
already created rather than duplicating them, so the AI snapshot can be
regenerated and re-loaded over the top of a heuristic first pass.

Loading also *builds the master ingredient list*. Every distinct ingredient
phrase across the collection becomes a stub row — name only — ready for a
price and nutrition figures. That is what turns 321 scraped posts into a
pantry worth looking things up in.

### Images are opt-in, deliberately

None of the blog's 44 images were hosted by the blog. Every one is a
hotlink to a commercial recipe site (goodfood.com.au, taste.com.au, ABC,
BBC Good Food); 40 of the 44 are now dead or refuse the request, and the
four that still resolve are someone else's press photography. Since the
site is publicly readable, `--with-images` is off by default and the
recipes keep only `image_source_url` for provenance. See SPEC.md "Images".
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.database import engine  # noqa: E402
from backend.models import (  # noqa: E402
    ImportSource,
    MeasureUnit,
    Recipe,
    RecipeIngredientIn,
    RecipeStepIn,
)
from backend.recipes_service import (  # noqa: E402
    allocate_slug,
    apply_ingredients,
    apply_steps,
    apply_tags,
)
from backend.slugs import slugify  # noqa: E402
from scripts.seed_sections import SECTIONS_PATH, seed  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
AI_SNAPSHOT = REPO_ROOT / "data" / "recipes.json"
HEURISTIC_SNAPSHOT = REPO_ROOT / "data" / "recipes.heuristic.json"
IMAGE_DIR = REPO_ROOT / "data" / "images"
IMAGE_INDEX = IMAGE_DIR / "index.json"


def parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


_UNIT_VALUES = {unit.value for unit in MeasureUnit}


def to_ingredient_inputs(items: list[dict]) -> list[RecipeIngredientIn]:
    """Snapshot dicts -> the same input schema `POST /recipes` takes.

    An unrecognised unit becomes None rather than an error: the line still
    loads with its raw text intact, and simply has no weight until someone
    fixes it in the editor.
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


def attach_image(recipe: Recipe, index: dict, source_url: str | None) -> None:
    """Copy a downloaded blog image into the upload dir and link it."""
    entry = index.get(source_url or "")
    if not entry:
        return
    source = IMAGE_DIR / entry["file"]
    if not source.exists():
        return
    relative = Path("recipes") / f"{recipe.slug}{source.suffix}"
    destination = Path(settings.upload_dir) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    recipe.image_path = str(relative)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument(
        "--heuristic",
        action="store_true",
        help="load data/recipes.heuristic.json instead of the AI snapshot",
    )
    parser.add_argument(
        "--with-images",
        action="store_true",
        help="also copy data/images into the upload dir (read the caveat above)",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    snapshot_path = args.input or (HEURISTIC_SNAPSHOT if args.heuristic else AI_SNAPSHOT)
    if not snapshot_path.exists():
        alternative = (
            "run scripts/parse_blog.py (needs ANTHROPIC_API_KEY), or pass "
            "--heuristic to load the committed rule-parsed snapshot"
        )
        print(f"{snapshot_path} not found — {alternative}", file=sys.stderr)
        return 1

    snapshot = json.loads(snapshot_path.read_text())
    recipes = snapshot["recipes"]
    if args.limit:
        recipes = recipes[: args.limit]

    image_index: dict = {}
    if args.with_images and IMAGE_INDEX.exists():
        image_index = json.loads(IMAGE_INDEX.read_text())

    created = updated = 0
    with Session(engine) as session:
        # Seed the navigation sections first: they are tags, so a recipe
        # naming "dessert" then attaches to the existing section rather
        # than creating a second, free-form tag with the same name.
        seed(session, json.loads(SECTIONS_PATH.read_text()))

        for record in recipes:
            source_url = record.get("source_url")
            recipe = None
            if source_url:
                recipe = session.exec(
                    select(Recipe).where(Recipe.source_url == source_url)
                ).first()

            title = (record.get("title") or "Untitled").strip()
            is_new = recipe is None
            if is_new:
                recipe = Recipe(slug=allocate_slug(session, title), title=title)
                created += 1
            else:
                # Keep the existing slug so links survive a re-load, but
                # re-slug if the title genuinely changed between snapshots.
                if slugify(title) != slugify(recipe.title):
                    recipe.slug = allocate_slug(session, title)
                recipe.title = title
                updated += 1

            recipe.description = record.get("description")
            recipe.added_date = parse_published(record.get("published")) or recipe.added_date
            recipe.prep_minutes = record.get("prep_minutes")
            recipe.cook_minutes = record.get("cook_minutes")
            recipe.servings = record.get("servings")
            recipe.servings_note = record.get("servings_note")
            recipe.storage = record.get("storage")
            recipe.nutrition_note = record.get("notes")
            recipe.source_url = source_url
            recipe.source_name = record.get("source_name")
            recipe.units_system = "au"
            recipe.import_source = ImportSource.blog
            recipe.needs_review = bool(record.get("needs_review"))
            uncertain = record.get("uncertain") or []
            recipe.review_note = (
                f"{record.get('parser', 'import')} import, "
                f"confidence {record.get('confidence', 0):.2f}"
                + (f"; {'; '.join(uncertain)}" if uncertain else "")
            )
            recipe.image_source_url = record.get("image_source_url")

            session.add(recipe)
            session.flush()

            if args.with_images:
                attach_image(recipe, image_index, record.get("image_source_url"))
                session.add(recipe)

            # The snapshot already folds the section into `tags`; this is
            # belt-and-braces for a hand-edited one that didn't.
            tags = list(record.get("tags") or [])
            section = record.get("section")
            if section and section not in tags:
                tags.insert(0, section)
            apply_tags(session, recipe, tags)
            # auto_create: this is what populates the master ingredient list.
            apply_ingredients(
                session,
                recipe,
                to_ingredient_inputs(record.get("ingredients") or []),
                auto_create=True,
            )
            apply_steps(
                session,
                recipe,
                [RecipeStepIn(text=s["text"] if isinstance(s, dict) else s)
                 for s in (record.get("steps") or [])],
            )

        if args.dry_run:
            session.rollback()
            print(f"dry run: would create {created}, update {updated}")
            return 0
        session.commit()

    from backend.models import Ingredient, RecipeIngredient  # noqa: E402

    with Session(engine) as session:
        pantry = len(session.exec(select(Ingredient)).all())
        lines = session.exec(select(RecipeIngredient)).all()
        linked = sum(1 for line in lines if line.ingredient_id)
        weighed = sum(1 for line in lines if line.weight_grams)
    print(
        f"loaded {snapshot_path.name}: {created} recipes created, {updated} updated\n"
        f"master ingredients: {pantry}\n"
        f"ingredient lines: {len(lines)} ({linked} linked, {weighed} with a weight)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
