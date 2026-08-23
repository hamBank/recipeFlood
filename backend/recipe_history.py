"""Reading a cooking-history spreadsheet: one row per recipe, forward-filled
dates, and a source column that is sometimes a link and sometimes a
handwritten book reference.

The export this was built against is a "date | title | … | source | notes"
dump going back to 2009 — 5,000+ rows, most with no date of their own
because the date only changes when the household actually moved on to a
new week. That shape drives everything here:

* **Dates forward-fill.** A row with no date in column 0 belongs to the
  most recent date above it. A cell that isn't a recognisable date (a
  stray word like "Lockdown", a mis-typed "25/6//20") is treated as *no
  date on this row* rather than an error — the date in force doesn't
  change, and the row still parses.
* **The source column holds two different things.** A URL, or a
  hand-written book/magazine reference ("DH dec 2017 p34"). Which one it
  is has to be sniffed, not assumed from the column alone — and the link,
  when there is one, sometimes ended up in the *notes* column instead
  (whoever filled this in used whichever cell was handy).
* **Names need light cleaning, not rewriting.** ALL CAPS and all-lowercase
  titles both appear from copy-pasting between sources; trailing "?" and
  "+" mark tentative or multi-dish entries. None of that is corrected
  automatically beyond whitespace and case — a recipe title is not a
  spelling-correction problem the way a pantry item name is.

This module only parses. Fetching, deduping against the database, and
writing rows live in scripts/import_recipe_history.py, which is what
actually touches the network or the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

#: dd/mm/yy or dd/mm/yyyy, single- or double-digit day/month. Rejects the
#: junk values seen in the wild ("25/6//20", "Lockdown", "Xmas") by simply
#: not matching them — see forward-fill note above.
_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")

#: A source-column cell that looks enough like a URL to fetch. Deliberately
#: permissive — a bare "www.example.com" (no scheme) still counts, since a
#: few rows in the wild are missing "https://".
_URL_RE = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)

#: "p34", "page 34", "pg. 34", trailing on a book/magazine reference.
_PAGE_RE = re.compile(r"\bp(?:age|g)?\.?\s*(\d{1,4})\b", re.IGNORECASE)

#: Tracking params and Blogger/WPRM fragment noise worth dropping so the
#: same recipe reached from two slightly different links dedupes as one.
_STRIP_QUERY_PREFIXES = ("utm_", "fbclid", "ref", "ref_src", "igshid")
_STRIP_FRAGMENT_PREFIXES = ("wprm-recipe-container",)


def parse_date(text: str) -> date | None:
    """dd/mm/yy or dd/mm/yyyy -> a date, or None if it isn't one.

    Two-digit years use the same 1969/2068 pivot as `datetime.strptime`'s
    `%y` — every date in this export is well within that range.
    """
    match = _DATE_RE.match(text.strip())
    if not match:
        return None
    day, month, year = match.groups()
    year_i = int(year)
    if len(year) == 2:
        year_i += 2000 if year_i < 69 else 1900
    try:
        return date(year_i, int(month), int(day))
    except ValueError:
        return None


def clean_name(text: str) -> str:
    """Trim, collapse whitespace, drop a trailing "?" or "+", and fix
    ALL-CAPS or all-lowercase titles to title case.

    Mixed-case titles ("Fennel and orange salad") are left exactly as
    typed — they're already fine, and title-casing "3 cheese, pesto and
    zuchini calzones" would capitalise "3" into nothing useful anyway.
    """
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"[?+]+\s*$", "", cleaned).strip()
    if cleaned and (cleaned == cleaned.upper() or cleaned == cleaned.lower()):
        cleaned = cleaned.title()
    return cleaned


def normalise_url(text: str) -> str | None:
    """A source-column cell -> a clean URL, or None if it isn't one.

    Adds a scheme to a bare "www." link, strips tracking-query params and
    known fragment noise (Blogger/WPRM recipe-card anchors) so two links to
    the same post compare equal, and drops a trailing "#" or "?" left
    behind by that stripping.
    """
    candidate = text.strip()
    if not _URL_RE.match(candidate):
        return None
    if candidate.lower().startswith("www."):
        candidate = f"https://{candidate}"

    if "?" in candidate:
        base, _, query = candidate.partition("?")
        kept = [
            part
            for part in query.split("&")
            if part and not part.lower().startswith(_STRIP_QUERY_PREFIXES)
        ]
        candidate = base + (f"?{'&'.join(kept)}" if kept else "")

    if "#" in candidate:
        base, _, fragment = candidate.partition("#")
        if fragment.lower().startswith(_STRIP_FRAGMENT_PREFIXES):
            candidate = base

    return candidate.rstrip("?#")


def parse_book_ref(text: str) -> tuple[str | None, int | None]:
    """"DH dec 2017 p34 issue 90" -> ("DH dec 2017 issue 90", 34).

    Only the page marker is extracted structurally; the rest is kept
    verbatim as the book/magazine name rather than parsed further — "DH"
    for Donna Hay, "delicious" for the magazine and so on are recognisable
    to a human reading the recipe page, and guessing at abbreviations here
    would be more likely to mangle a title than clarify one.
    """
    stripped = text.strip()
    if not stripped:
        return None, None
    match = _PAGE_RE.search(stripped)
    if not match:
        return stripped, None
    page = int(match.group(1))
    name = (stripped[: match.start()] + stripped[match.end() :]).strip()
    name = re.sub(r"\s+", " ", name).strip(" ,-")
    return (name or None), page


@dataclass(frozen=True)
class CookRecord:
    """One row of the export, parsed. `url` and `book_name`/`book_page`
    are mutually exclusive — a row has a link, a book reference, or
    neither, never both (see `classify_source`)."""

    cook_date: date | None
    name: str
    raw_name: str
    url: str | None
    book_name: str | None
    book_page: int | None


def classify_source(source_cell: str, notes_cell: str) -> tuple[str | None, str, int | None]:
    """Work out what a row's source actually is.

    Checks the source column first, then falls back to the notes column —
    whoever filled this in sometimes put the link there instead. Returns
    (url, book_name_or_empty, book_page); a book reference found in the
    notes column is not treated as one, since free-text notes are exactly
    that (a note), not a citation — only a URL is worth rescuing from
    there.
    """
    for cell in (source_cell, notes_cell):
        url = normalise_url(cell)
        if url:
            return url, "", None
    book_name, book_page = parse_book_ref(source_cell)
    return None, (book_name or ""), book_page


def parse_rows(rows: list[list[str]]) -> list[CookRecord]:
    """The whole export -> one CookRecord per named row.

    Column layout: 0 = date, 1 = title, 4 = source, 5 = notes. Columns 2,
    3 and 6+ are unused in every row seen so far and are ignored rather
    than asserted on, in case a future export adds something there.
    """
    records: list[CookRecord] = []
    current_date: date | None = None

    for row in rows:
        if row and row[0].strip():
            parsed = parse_date(row[0])
            if parsed is not None:
                current_date = parsed
            # An unparseable date cell (see module docstring) leaves
            # current_date exactly as it was — it is not an error.

        raw_name = row[1].strip() if len(row) > 1 else ""
        if not raw_name:
            continue

        source_cell = row[4].strip() if len(row) > 4 else ""
        notes_cell = row[5].strip() if len(row) > 5 else ""
        url, book_name, book_page = classify_source(source_cell, notes_cell)

        records.append(
            CookRecord(
                cook_date=current_date,
                name=clean_name(raw_name),
                raw_name=raw_name,
                url=url,
                book_name=book_name or None,
                book_page=book_page,
            )
        )

    return records
