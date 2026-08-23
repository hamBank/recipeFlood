#!/usr/bin/env python3
"""Generate a placeholder photo for every recipe that doesn't have one.

    python -m scripts.generate_recipe_images --dry-run
    python -m scripts.generate_recipe_images --budget 5.00
    python -m scripts.generate_recipe_images --limit 20 --quality low

Needs OPENAI_API_KEY (see .env.example) — Claude has no image-generation
endpoint of its own, so this is a separate provider from the rest of the
app's AI features. `--dry-run` works without a key: it shows what would
be generated and the estimated cost, and spends nothing.

Recipes with no image at all (`image_path IS NULL` — never uploaded,
never self-hosted from the blog, never generated before) are the
candidates, **most-cooked first**: a recipe made a dozen times is worth a
placeholder before one nobody's made yet. `--limit` caps how many to
generate; `--budget` caps estimated spend instead, stopping before the
next image would exceed it — pass either, both, or neither.

Every image is saved self-hosted (same convention as an uploaded photo)
and the recipe is flagged `image_generated=True`, so the UI can say
"AI-generated" rather than let an illustration pass as a real photo of
the dish. See backend/image_generation.py's docstring for why that also
means none of SPEC.md's "Images" copyright caution applies here — there's
no original to attribute, because there isn't one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, func, select  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.database import engine  # noqa: E402
from backend.image_generation import (  # noqa: E402
    COST_PER_IMAGE_USD,
    build_prompt,
    generate_image,
    is_configured,
)
from backend.models import PreparedEvent, Recipe  # noqa: E402
from backend.recipes_service import recipe_tags  # noqa: E402


def select_recipes_needing_images(session: Session, limit: int | None = None) -> list[Recipe]:
    """Every recipe with no image of any kind, most-cooked first.

    "Most-cooked" is a plain COUNT of PreparedEvent per recipe, done in
    SQL rather than in Python, so this stays one query regardless of how
    many recipes there are.
    """
    times_cooked = (
        select(PreparedEvent.recipe_id, func.count().label("n"))
        .group_by(PreparedEvent.recipe_id)
        .subquery()
    )
    statement = (
        select(Recipe)
        .join(times_cooked, times_cooked.c.recipe_id == Recipe.id, isouter=True)
        .where(Recipe.image_path.is_(None))
        .order_by(func.coalesce(times_cooked.c.n, 0).desc(), Recipe.id)
    )
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.exec(statement).all())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="generate at most N images")
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="stop before estimated spend would exceed this many dollars",
    )
    parser.add_argument("--quality", choices=sorted(COST_PER_IMAGE_USD), default="medium")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not is_configured():
        print(
            "OPENAI_API_KEY is not set — nothing to do. Use --dry-run to preview "
            "without a key.",
            file=sys.stderr,
        )
        return 1

    cost_per_image = COST_PER_IMAGE_USD[args.quality]

    with Session(engine) as session:
        candidates = select_recipes_needing_images(session, limit=args.limit)
        if not candidates:
            print("Nothing to do — every recipe already has a photo.")
            return 0

        if args.budget is not None:
            affordable = max(0, int(args.budget // cost_per_image))
            candidates = candidates[:affordable]
            if not candidates:
                print(
                    f"Budget ${args.budget:.2f} doesn't cover even one "
                    f"{args.quality}-quality image (est. ${cost_per_image:.3f} each)."
                )
                return 0

        estimated_total = len(candidates) * cost_per_image
        print(
            f"{len(candidates)} recipe(s) selected, most-cooked first — "
            f"est. ${cost_per_image:.3f} each, ${estimated_total:.2f} total "
            f"({args.quality}, {args.size})"
        )

        if args.dry_run:
            for recipe in candidates:
                print(f"  would generate: {recipe.title}")
            return 0

        upload_root = Path(settings.upload_dir) / "recipes"
        upload_root.mkdir(parents=True, exist_ok=True)

        generated = failed = 0
        spent = 0.0
        for recipe in candidates:
            _, sections = recipe_tags(session, recipe.id)
            prompt = build_prompt(recipe.title, recipe.description, sections[0] if sections else None)

            print(f"  generating: {recipe.title}", flush=True)
            try:
                image_bytes = generate_image(prompt, quality=args.quality, size=args.size)
            except Exception as exc:  # noqa: BLE001 - one failure must not stop the run
                print(f"    failed: {exc}", flush=True)
                failed += 1
                continue

            relative = f"recipes/{recipe.slug}.png"
            (upload_root / f"{recipe.slug}.png").write_bytes(image_bytes)
            recipe.image_path = relative
            recipe.image_generated = True
            session.add(recipe)
            session.commit()

            spent += cost_per_image
            generated += 1
            print(f"    saved (est. running spend ${spent:.2f})", flush=True)

    print(f"generated {generated}, failed {failed}, est. total spend ${spent:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
