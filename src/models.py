from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def _normalize_address(address: str) -> str:
    addr = address.lower().strip()
    addr = re.sub(r'\b(apt|unit|suite|ste|#)\s*\S+', '', addr)
    replacements = {
        'street': 'st', 'avenue': 'ave', 'boulevard': 'blvd',
        'drive': 'dr', 'court': 'ct', 'place': 'pl',
        'lane': 'ln', 'road': 'rd', 'terrace': 'ter',
    }
    for full, abbr in replacements.items():
        addr = re.sub(rf'\b{full}\b', abbr, addr)
    addr = re.sub(r'\s+', ' ', addr).strip()
    return addr


def generate_listing_id(address: str, price: int, bedrooms: int) -> str:
    normalized = _normalize_address(address)
    raw = f"{normalized}|{price}|{bedrooms}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class Listing:
    id: str = ""
    source: str = ""
    source_id: str = ""
    source_url: str = ""

    address: str = ""
    neighborhood: str = ""
    city: str = "San Francisco"
    state: str = "CA"
    zip_code: str = ""
    latitude: float | None = None
    longitude: float | None = None

    price: int = 0
    bedrooms: int = 0
    bathrooms: float = 0.0
    sqft: int | None = None
    property_type: str | None = None
    year_built: int | None = None

    has_in_unit_laundry: bool | None = None
    has_parking: bool | None = None
    parking_type: str | None = None
    is_pet_friendly: bool | None = None
    pet_details: str | None = None
    has_outdoor_space: bool | None = None
    outdoor_details: str | None = None
    building_type: str | None = None

    available_date: str | None = None
    lease_term: str | None = None
    move_in_cost: str | None = None

    transit_score: int | None = None
    nearest_transit: str | None = None

    images: list[str] = field(default_factory=list)
    description: str = ""

    first_seen: str = ""
    last_seen: str = ""
    is_active: bool = True
    score: float | None = None
    score_breakdown: dict = field(default_factory=dict)

    status: str = "new"
    notes: list[dict] = field(default_factory=list)
    votes: dict = field(default_factory=dict)

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.first_seen:
            self.first_seen = now
        if not self.last_seen:
            self.last_seen = now
        if not self.id and self.address and self.price:
            self.id = generate_listing_id(self.address, self.price, self.bedrooms)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Listing:
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        listing = cls(**filtered)
        return listing

    def merge_from(self, other: Listing):
        for fld in self.__dataclass_fields__:
            if fld in ('id', 'source', 'source_id', 'source_url', 'first_seen',
                       'status', 'notes', 'votes', 'score', 'score_breakdown'):
                continue
            other_val = getattr(other, fld)
            self_val = getattr(self, fld)
            if other_val is not None and (self_val is None or self_val == "" or self_val == 0):
                setattr(self, fld, other_val)
        self.last_seen = other.last_seen
        if other.source_url and not self.source_url:
            self.source_url = other.source_url
        if other.images and not self.images:
            self.images = other.images
