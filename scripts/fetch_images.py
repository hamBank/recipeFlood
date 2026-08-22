#!/usr/bin/env python3
"""Step 2 of the blog import: self-host the post images.

    python scripts/fetch_images.py [--force]

Reads `data/blog_raw.json`, downloads the first image of each post that has
one into `data/images/<slug>.<ext>`, and records the mapping in
`data/images/index.json`.

Only 44 of the 321 posts have a photo. Those images are downloaded and
committed rather than hotlinked back to Blogger, so the site keeps working
if the blog is ever taken down, and so a rebuild from this repo produces
the same pages. `load_snapshot.py` copies them into the app's upload
directory at load time.

Idempotent: an image already on disk is skipped unless --force.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.slugs import slugify  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = REPO_ROOT / "data" / "blog_raw.json"
IMAGE_DIR = REPO_ROOT / "data" / "images"
INDEX_PATH = IMAGE_DIR / "index.json"

CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_BYTES = 8 * 1024 * 1024


def download(url: str, destination_stem: Path, *, force: bool) -> Path | None:
    existing = list(destination_stem.parent.glob(f"{destination_stem.name}.*"))
    if existing and not force:
        return existing[0]

    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"    ! {url}: {error}", file=sys.stderr)
        return None

    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    extension = CONTENT_TYPE_EXT.get(content_type)
    if extension is None:
        print(f"    ! {url}: unexpected content type {content_type!r}", file=sys.stderr)
        return None
    if len(response.content) > MAX_BYTES:
        print(f"    ! {url}: {len(response.content)} bytes, over the limit", file=sys.stderr)
        return None

    for stale in existing:
        stale.unlink()
    path = destination_stem.with_suffix(extension)
    path.write_bytes(response.content)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    parser.add_argument("--raw", type=Path, default=RAW_PATH)
    args = parser.parse_args()

    if not args.raw.exists():
        print(f"{args.raw} not found — run scripts/fetch_blog.py first", file=sys.stderr)
        return 1

    posts = json.loads(args.raw.read_text())["posts"]
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}
    if INDEX_PATH.exists() and not args.force:
        index = json.loads(INDEX_PATH.read_text())

    downloaded = skipped = failed = 0
    used_slugs: set[str] = set()
    for post in posts:
        if not post["image_urls"]:
            continue
        slug = slugify(post["title"] or "untitled")
        # Two posts share the title "Croissant"; keep both images distinct.
        candidate, n = slug, 2
        while candidate in used_slugs:
            candidate, n = f"{slug}-{n}", n + 1
        slug = candidate
        used_slugs.add(slug)

        url = post["image_urls"][0]
        before = list(IMAGE_DIR.glob(f"{slug}.*"))
        path = download(url, IMAGE_DIR / slug, force=args.force)
        if path is None:
            failed += 1
            continue
        if before and not args.force:
            skipped += 1
        else:
            downloaded += 1
            print(f"  {path.name}  <- {url[:80]}")
        index[post["url"]] = {
            "title": post["title"],
            "file": path.name,
            "source_url": url,
        }

    INDEX_PATH.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n")
    print(
        f"images: {downloaded} downloaded, {skipped} already present, {failed} failed "
        f"-> {IMAGE_DIR.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
