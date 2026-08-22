#!/usr/bin/env python3
"""Download the Australian Food Composition Database (Release 3) locally.

    python scripts/fetch_afcd.py
    python scripts/fetch_afcd.py --force

Pulls two files FSANZ publishes — food descriptions and their per-100g
nutrient profiles — into `data/afcd/`, which is **gitignored**. The FSANZ
download page states plain copyright with no licence grant, so this
dataset is not redistributed in this public repo; run this once, locally
or on the server, before `scripts/enrich_pantry.py` can use it.

Without it, enrichment still works — every ingredient just falls back to
an AI estimate instead of a government-sourced figure for the ones AFCD
covers. See backend/afcd.py for what "covers" means: it only ever returns
a match it has real coverage for, never a guess dressed as one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

BASE = "https://www.foodstandards.gov.au/sites/default/files/2025-12/"
FILES = {
    "food_details.xlsx": BASE + "AFCD%20Release%203%20-%20Food%20Details.xlsx",
    "nutrient_profiles.xlsx": BASE + "AFCD%20Release%203%20-%20Nutrient%20profiles.xlsx",
}

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "afcd"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in FILES.items():
        destination = DATA_DIR / filename
        if destination.exists() and not args.force:
            print(f"  {filename} already present, skipping (--force to re-fetch)")
            continue
        print(f"  fetching {filename} ...")
        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
        except requests.RequestException as error:
            print(f"    ! failed: {error}", file=sys.stderr)
            return 1
        destination.write_bytes(response.content)
        print(f"    -> {destination} ({len(response.content):,} bytes)")

    print(f"AFCD data ready in {DATA_DIR.relative_to(DATA_DIR.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
