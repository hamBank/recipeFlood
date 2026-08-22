"""URL slug generation.

Recipes are addressed by slug (`/recipes/flax-bread`) rather than id so
links survive a database rebuild from the committed snapshot — the blog
importer is re-runnable, and re-running it must not change anyone's
bookmarks.
"""

import re
import unicodedata
from typing import Callable

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, max_length: int = 80) -> str:
    """"Salt & Pepper Squid!" -> "salt-pepper-squid"."""
    normalised = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalised.encode("ascii", "ignore").decode("ascii").lower()
    slug = _NON_SLUG.sub("-", ascii_text).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or "untitled"


def unique_slug(text: str, exists: Callable[[str], bool], *, max_length: int = 80) -> str:
    """Slugify, then append -2, -3... until `exists` says the slug is free.

    The blog has two posts titled "Croissant" and two "Salad of freekeh
    with pickled red onion, cherries, toasted walnuts and mint", so this
    is load-bearing on the very first import, not a theoretical guard.
    """
    base = slugify(text, max_length=max_length)
    if not exists(base):
        return base
    for suffix in range(2, 1000):
        candidate = f"{base}-{suffix}"
        if not exists(candidate):
            return candidate
    raise ValueError(f"could not find a free slug for {text!r}")
