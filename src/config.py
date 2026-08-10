from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DATA_DIR = PROJECT_ROOT / "data"
SITE_DIR = PROJECT_ROOT / "site"
TEMPLATES_DIR = PROJECT_ROOT / "templates"


@dataclass
class SearchConfig:
    city: str = "San Francisco"
    state: str = "CA"
    neighborhoods: list[str] = field(default_factory=lambda: ["Mission District", "Hayes Valley"])
    zip_codes: list[str] = field(default_factory=lambda: ["94110", "94102", "94103", "94114"])
    min_bedrooms: int = 4
    max_bedrooms: int = 4
    min_bathrooms: int = 1
    preferred_bathrooms: int = 2
    max_price: int = 10000
    move_in_deadline: str = "2026-10-31"


@dataclass
class CollectorConfig:
    enabled: bool = True
    max_calls_per_month: int = 50


@dataclass
class ScoringConfig:
    weights: dict = field(default_factory=lambda: {
        "sqft": 20, "building_type": 15, "laundry": 15,
        "transit": 10, "parking": 8, "pets": 7,
        "outdoor": 7, "move_in": 8, "lease": 5, "price": 5,
    })


@dataclass
class NotificationConfig:
    enabled: bool = True
    from_email: str = "onboarding@resend.dev"
    recipients: list[str] = field(default_factory=list)
    min_score_to_notify: int = 0


@dataclass
class SiteConfig:
    title: str = "SF Apartment Hunt"
    base_url: str = ""


@dataclass
class Config:
    search: SearchConfig = field(default_factory=SearchConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    collectors: dict[str, CollectorConfig] = field(default_factory=dict)
    site: SiteConfig = field(default_factory=SiteConfig)

    rentcast_api_key: str = ""
    rapidapi_key: str = ""
    apify_api_key: str = ""
    resend_api_key: str = ""


def load_config(config_path: Path | None = None) -> Config:
    path = config_path or CONFIG_PATH
    with open(path) as f:
        raw = yaml.safe_load(f)

    config = Config()

    if "search" in raw:
        config.search = SearchConfig(**raw["search"])

    if "scoring" in raw:
        config.scoring = ScoringConfig(**raw["scoring"])

    if "notifications" in raw:
        config.notifications = NotificationConfig(**raw["notifications"])

    if "collectors" in raw:
        config.collectors = {
            name: CollectorConfig(**opts)
            for name, opts in raw["collectors"].items()
        }

    if "site" in raw:
        config.site = SiteConfig(**raw["site"])

    config.rentcast_api_key = os.environ.get("RENTCAST_API_KEY", "")
    config.rapidapi_key = os.environ.get("RAPIDAPI_KEY", "")
    config.apify_api_key = os.environ.get("APIFY_API_KEY", "")
    config.resend_api_key = os.environ.get("RESEND_API_KEY", "")

    return config
