from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from thefuzz import fuzz

from src.config import Config, DATA_DIR
from src.feature_extractor import extract_features
from src.models import Listing, _normalize_address
from src.scorer import score_listing

logger = logging.getLogger(__name__)

SOURCE_PRIORITY = {"rentcast": 5, "zillow": 4, "redfin": 3, "zumper": 2, "craigslist": 1}


def load_listings(path: Path | None = None) -> list[Listing]:
    p = path or (DATA_DIR / "listings.json")
    if not p.exists():
        return []
    with open(p) as f:
        data = json.load(f)
    return [Listing.from_dict(d) for d in data]


def save_listings(listings: list[Listing], path: Path | None = None):
    p = path or (DATA_DIR / "listings.json")
    with open(p, "w") as f:
        json.dump([l.to_dict() for l in listings], f, indent=2, default=str)


def load_collaboration(path: Path | None = None) -> dict:
    p = path or (DATA_DIR / "collaboration.json")
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)


def save_run_log(results: dict, path: Path | None = None):
    p = path or (DATA_DIR / "runs.json")
    runs = []
    if p.exists():
        with open(p) as f:
            runs = json.load(f)
    runs.append(results)
    if len(runs) > 200:
        runs = runs[-200:]
    with open(p, "w") as f:
        json.dump(runs, f, indent=2, default=str)


def find_duplicate(
    listing: Listing,
    existing: list[Listing],
    existing_index: dict[str, Listing],
) -> Listing | None:
    if listing.id in existing_index:
        return existing_index[listing.id]

    new_addr = _normalize_address(listing.address) if listing.address else ""
    if not new_addr:
        return None

    for ex in existing:
        ex_addr = _normalize_address(ex.address) if ex.address else ""
        if not ex_addr:
            continue
        addr_sim = fuzz.ratio(new_addr, ex_addr)
        price_diff = abs(listing.price - ex.price)
        same_beds = listing.bedrooms == ex.bedrooms
        if addr_sim > 85 and price_diff < 500 and same_beds:
            return ex

    return None


def merge_listing(existing: Listing, new: Listing) -> Listing:
    ex_priority = SOURCE_PRIORITY.get(existing.source, 0)
    new_priority = SOURCE_PRIORITY.get(new.source, 0)

    if new_priority > ex_priority:
        new.merge_from(existing)
        new.first_seen = existing.first_seen
        new.status = existing.status
        new.notes = existing.notes
        new.votes = existing.votes
        return new
    else:
        existing.merge_from(new)
        return existing


def process_listings(
    raw_listings: list[Listing],
    existing_listings: list[Listing],
    config: Config,
) -> tuple[list[Listing], list[Listing]]:
    existing_index = {l.id: l for l in existing_listings}
    seen_ids = set()
    merged = list(existing_listings)
    new_listings = []

    for raw in raw_listings:
        if raw.id in seen_ids:
            continue
        seen_ids.add(raw.id)

        dup = find_duplicate(raw, merged, existing_index)
        if dup:
            idx = merged.index(dup)
            merged[idx] = merge_listing(dup, raw)
            merged[idx].is_active = True
            merged[idx].last_seen = datetime.now(timezone.utc).isoformat()
        else:
            new_listings.append(raw)
            merged.append(raw)
            existing_index[raw.id] = raw

    for listing in merged:
        extract_features(listing)
        listing.score = score_listing(
            listing,
            config.scoring.weights,
            config.search.move_in_deadline,
            preferred_bathrooms=config.search.preferred_bathrooms,
            neighborhoods=config.search.neighborhoods,
        )

    collab = load_collaboration()
    for listing in merged:
        if listing.id in collab:
            entry = collab[listing.id]
            listing.status = entry.get("status", listing.status)
            listing.notes = entry.get("notes", listing.notes)
            listing.votes = entry.get("votes", listing.votes)

    merged.sort(key=lambda l: (l.score or 0), reverse=True)

    logger.info(
        f"Processed: {len(merged)} total, {len(new_listings)} new, "
        f"{sum(1 for l in merged if l.is_active)} active"
    )

    return merged, new_listings
