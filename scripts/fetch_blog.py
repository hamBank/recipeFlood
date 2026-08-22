#!/usr/bin/env python3
"""Step 1 of the blog import: snapshot the Blogger feed.

    python scripts/fetch_blog.py [--blog foobie-rcp.blogspot.com]

Writes `data/blog_raw.json` — every post's title, publish date, labels,
permalink, raw HTML body and image URLs. The output is committed, which is
what makes the rest of the pipeline reproducible: `parse_blog.py` and
`load_snapshot.py` never touch the network, so the collection can be
rebuilt from the repo alone even if the blog disappears.

Blogger's JSON feed caps a page at 150 entries regardless of what
`max-results` asks for, so this pages with `start-index` until it has the
count the feed itself reports.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

DEFAULT_BLOG = "foobie-rcp.blogspot.com"
PAGE_SIZE = 150
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "blog_raw.json"

_IMG_SRC = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def fetch_page(blog: str, start_index: int) -> dict:
    response = requests.get(
        f"https://{blog}/feeds/posts/default",
        params={"alt": "json", "max-results": PAGE_SIZE, "start-index": start_index},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["feed"]


def alternate_link(entry: dict) -> str | None:
    for link in entry.get("link", []):
        if link.get("rel") == "alternate":
            return link.get("href")
    return None


def image_urls(html: str) -> list[str]:
    """Post image URLs, de-duplicated, in document order.

    Blogger serves the same photo at several sizes under
    `/s320/`, `/s640/`... — the `/s1600/` variant is the original, so
    rewrite whatever size the post embedded up to it.
    """
    seen: list[str] = []
    for url in _IMG_SRC.findall(html):
        if not url.startswith("http"):
            continue
        full = re.sub(r"/s\d+(-c)?/", "/s1600/", url)
        full = re.sub(r"=s\d+(-c)?$", "=s1600", full)
        if full not in seen:
            seen.append(full)
    return seen


def fetch_blog(blog: str) -> list[dict]:
    entries: list[dict] = []
    start_index = 1
    total: int | None = None

    while True:
        feed = fetch_page(blog, start_index)
        if total is None:
            total = int(feed.get("openSearch$totalResults", {}).get("$t", 0))
            print(f"feed reports {total} posts", file=sys.stderr)
        page = feed.get("entry", [])
        if not page:
            break
        for entry in page:
            html = entry.get("content", {}).get("$t", "")
            entries.append(
                {
                    "id": entry.get("id", {}).get("$t"),
                    "title": entry.get("title", {}).get("$t", "").strip(),
                    "published": entry.get("published", {}).get("$t"),
                    "updated": entry.get("updated", {}).get("$t"),
                    "labels": [c["term"] for c in entry.get("category", [])],
                    "url": alternate_link(entry),
                    "content_html": html,
                    "image_urls": image_urls(html),
                }
            )
        print(f"  fetched {len(entries)}/{total}", file=sys.stderr)
        if total is not None and len(entries) >= total:
            break
        start_index += PAGE_SIZE
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blog", default=DEFAULT_BLOG, help="blog hostname")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    entries = fetch_blog(args.blog)
    if not entries:
        print("no posts fetched — refusing to overwrite the snapshot", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "blog": args.blog,
                "source_name": urlparse(f"https://{args.blog}").netloc,
                "post_count": len(entries),
                "posts": entries,
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n"
    )
    with_images = sum(1 for e in entries if e["image_urls"])
    print(
        f"wrote {args.output.relative_to(REPO_ROOT)}: "
        f"{len(entries)} posts, {with_images} with images"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
