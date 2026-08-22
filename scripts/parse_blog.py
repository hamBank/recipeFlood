#!/usr/bin/env python3
"""Step 3 of the blog import: structure the posts into recipe drafts.

    # the real run — needs ANTHROPIC_API_KEY, ~321 calls, costs money
    python scripts/parse_blog.py

    # no API key: deterministic rules instead (see backend/blog_parser.py)
    python scripts/parse_blog.py --offline

    python scripts/parse_blog.py --limit 5          # try it on five posts
    python scripts/parse_blog.py --resume           # continue after a stop

Reads `data/blog_raw.json`, writes `data/recipes.json` — the structured
snapshot that `load_snapshot.py` turns into database rows. That snapshot is
committed, so the API spend happens once and anyone can rebuild the
collection from the repo without a key.

`--resume` re-reads the output file and skips posts already present, so an
interrupted run (or a rate limit) costs only the posts it hadn't reached.
Progress is flushed to disk after every post for the same reason.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import ai_import  # noqa: E402
from backend.blog_parser import html_to_lines, parse_post  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = REPO_ROOT / "data" / "blog_raw.json"
AI_OUTPUT = REPO_ROOT / "data" / "recipes.json"
OFFLINE_OUTPUT = REPO_ROOT / "data" / "recipes.heuristic.json"

#: Below this, the recipe is flagged for review on load.
REVIEW_THRESHOLD = 0.75


def load_existing(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {r["source_url"]: r for r in data.get("recipes", []) if r.get("source_url")}


def write_output(path: Path, records: dict[str, dict], *, parser: str, model: str | None) -> None:
    ordered = sorted(records.values(), key=lambda r: r.get("published") or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "parser": parser,
                "model": model,
                "recipe_count": len(ordered),
                "recipes": ordered,
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n"
    )


def build_record(post: dict, draft: dict, *, parser: str) -> dict:
    uncertain = list(draft.get("uncertain") or [])
    if not draft.get("ingredients"):
        uncertain.append("no ingredients")
    if not draft.get("steps"):
        uncertain.append("no method")

    confidence = float(draft.get("confidence") or 0.0)
    return {
        **draft,
        "confidence": confidence,
        "uncertain": uncertain,
        "needs_review": confidence < REVIEW_THRESHOLD or bool(uncertain),
        "parser": parser,
        "source_url": post["url"],
        "source_name": "Recipe 'n stuff",
        "published": post["published"],
        "labels": post.get("labels", []),
        "image_source_url": (post.get("image_urls") or [None])[0],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="use the rule-based parser instead of the Claude API",
    )
    parser.add_argument("--raw", type=Path, default=RAW_PATH)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None, help="stop after N posts")
    parser.add_argument(
        "--resume", action="store_true", help="skip posts already in the output"
    )
    parser.add_argument(
        "--sleep", type=float, default=0.0, help="seconds to pause between API calls"
    )
    args = parser.parse_args()

    if not args.raw.exists():
        print(f"{args.raw} not found — run scripts/fetch_blog.py first", file=sys.stderr)
        return 1

    output = args.output or (OFFLINE_OUTPUT if args.offline else AI_OUTPUT)
    mode = "heuristic" if args.offline else "ai"
    model = None if args.offline else ai_import.settings.anthropic_model

    if not args.offline and not ai_import.is_configured():
        print(
            "ANTHROPIC_API_KEY is not set.\n"
            "Set it to run the real import, or pass --offline for the "
            "rule-based parser (see backend/blog_parser.py).",
            file=sys.stderr,
        )
        return 2

    posts = json.loads(args.raw.read_text())["posts"]
    records = load_existing(output) if args.resume else {}

    processed = failed = 0
    for index, post in enumerate(posts, start=1):
        if not post.get("url"):
            continue
        if args.resume and post["url"] in records:
            continue
        if args.limit is not None and processed >= args.limit:
            break

        title = post.get("title") or "(untitled)"
        print(f"[{index}/{len(posts)}] {title[:70]}", file=sys.stderr)
        try:
            if args.offline:
                draft = parse_post(post)
            else:
                text = "\n".join(line for line in html_to_lines(post["content_html"]) if line)
                draft = ai_import.draft_from_text(text, title_hint=title)
                # The model is told to keep the title; the post's own title
                # is still the authority on what this recipe is called.
                draft["title"] = title or draft.get("title") or "Untitled"
                draft.setdefault("tags", [])
                draft["tags"] = sorted(
                    {*(draft.get("tags") or []), *(t.lower() for t in post.get("labels", []))}
                )
        except Exception as error:  # noqa: BLE001 - one bad post must not end the run
            print(f"    ! failed: {error}", file=sys.stderr)
            failed += 1
            continue

        records[post["url"]] = build_record(post, draft, parser=mode)
        processed += 1
        # Flush every post: an interrupted paid run should never lose work.
        write_output(output, records, parser=mode, model=model)
        if args.sleep and not args.offline:
            time.sleep(args.sleep)

    write_output(output, records, parser=mode, model=model)
    review = sum(1 for r in records.values() if r["needs_review"])
    print(
        f"\n{output.relative_to(REPO_ROOT)}: {len(records)} recipes "
        f"({processed} this run, {failed} failed, {review} flagged for review)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
