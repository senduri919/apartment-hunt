#!/usr/bin/env python3
"""Apartment Hunt Monitor — CLI entry point."""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from src.collectors import COLLECTORS
from src.config import DATA_DIR, load_config
from src.models import Listing
from src.processor import load_listings, process_listings, save_listings, save_run_log

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("apartment-hunt")


def cmd_collect(config):
    all_listings = []
    errors = []

    for name, CollectorClass in COLLECTORS.items():
        collector_config = config.collectors.get(name)
        if not collector_config or not collector_config.enabled:
            logger.info(f"{name}: disabled, skipping")
            continue

        try:
            collector = CollectorClass(config)
            listings = collector.collect()
            all_listings.extend(listings)
            logger.info(f"{name}: collected {len(listings)} listings")
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
            logger.error(f"{name} failed: {e}", exc_info=True)

    raw_path = DATA_DIR / "raw_latest.json"
    with open(raw_path, "w") as f:
        json.dump([l.to_dict() for l in all_listings], f, indent=2, default=str)

    logger.info(f"Collected {len(all_listings)} total raw listings")
    if errors:
        logger.warning(f"Errors: {errors}")

    return all_listings, errors


def cmd_process(config):
    raw_path = DATA_DIR / "raw_latest.json"
    if not raw_path.exists():
        logger.error("No raw listings found. Run 'collect' first.")
        return [], []

    with open(raw_path) as f:
        raw_data = json.load(f)
    raw_listings = [Listing.from_dict(d) for d in raw_data]

    existing = load_listings()

    prev_count = len(existing)
    all_listings, new_listings = process_listings(raw_listings, existing, config)

    old_count = len(load_listings())
    if old_count > 0 and len(all_listings) < old_count * 0.5:
        logger.error(
            f"Processed count ({len(all_listings)}) is <50% of previous ({old_count}). "
            "Keeping old data to prevent data loss."
        )
        return existing, []

    save_listings(all_listings)

    active = [l for l in all_listings if l.is_active]
    save_listings(active, DATA_DIR / "active.json")

    new_path = DATA_DIR / "new_listings.json"
    with open(new_path, "w") as f:
        json.dump([l.to_dict() for l in new_listings], f, indent=2, default=str)

    logger.info(f"Saved {len(all_listings)} listings ({len(new_listings)} new, {len(active)} active)")
    return all_listings, new_listings


def cmd_generate(config):
    from src.site_generator import generate_site
    listings = load_listings(DATA_DIR / "active.json")
    if not listings:
        listings = load_listings()
    generate_site(listings, config)
    logger.info(f"Generated static site with {len(listings)} listings")


def cmd_notify(config, new_listings=None):
    from src.notifier import send_notification

    if new_listings is None:
        new_path = DATA_DIR / "new_listings.json"
        if new_path.exists():
            with open(new_path) as f:
                data = json.load(f)
            new_listings = [Listing.from_dict(d) for d in data]
        else:
            new_listings = []

    if not new_listings:
        logger.info("No new listings to notify about")
        return

    min_score = config.notifications.min_score_to_notify
    filtered = [l for l in new_listings if (l.score or 0) >= min_score]

    if not filtered:
        logger.info(f"No new listings above min score threshold ({min_score})")
        return

    send_notification(filtered, config)


def cmd_run(config):
    run_start = datetime.now(timezone.utc)

    raw_listings, collect_errors = cmd_collect(config)
    all_listings, new_listings = cmd_process(config)

    if new_listings:
        new_path = DATA_DIR / "new_listings.json"
        with open(new_path, "w") as f:
            json.dump([l.to_dict() for l in new_listings], f, indent=2, default=str)

    cmd_generate(config)
    cmd_notify(config, new_listings)

    run_log = {
        "timestamp": run_start.isoformat(),
        "duration_seconds": (datetime.now(timezone.utc) - run_start).total_seconds(),
        "raw_collected": len(raw_listings),
        "total_listings": len(all_listings),
        "new_listings": len(new_listings),
        "active_listings": sum(1 for l in all_listings if l.is_active),
        "errors": collect_errors,
    }
    save_run_log(run_log)

    logger.info(
        f"Run complete: {len(raw_listings)} raw, {len(new_listings)} new, "
        f"{sum(1 for l in all_listings if l.is_active)} active"
    )


def main():
    parser = argparse.ArgumentParser(description="Apartment Hunt Monitor")
    parser.add_argument(
        "command",
        choices=["collect", "process", "generate", "notify", "run"],
        help="Command to execute",
    )
    parser.add_argument("--config", type=str, help="Path to config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)

    commands = {
        "collect": lambda: cmd_collect(config),
        "process": lambda: cmd_process(config),
        "generate": lambda: cmd_generate(config),
        "notify": lambda: cmd_notify(config),
        "run": lambda: cmd_run(config),
    }

    try:
        commands[args.command]()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
