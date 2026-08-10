from __future__ import annotations

from datetime import datetime, timezone

from dateutil.parser import parse as parse_date

from src.models import Listing


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _score_sqft(sqft: int | None) -> float:
    if sqft is None:
        return 30.0
    return _clamp((sqft - 1000) / (2500 - 1000) * 100)


def _score_building_type(building_type: str | None) -> float:
    mapping = {
        "modern": 100, "new-construction": 100, "contemporary": 100,
        "renovated": 70, "remodeled": 70, "updated": 70,
        "victorian": 50, "edwardian": 50,
    }
    if not building_type:
        return 40.0
    return float(mapping.get(building_type.lower(), 40))


def _score_laundry(has_in_unit: bool | None) -> float:
    if has_in_unit is None:
        return 30.0
    return 100.0 if has_in_unit else 0.0


def _score_transit(transit_score: int | None, nearest_transit: str | None) -> float:
    if transit_score is not None:
        return _clamp(float(transit_score))
    if nearest_transit:
        text = nearest_transit.lower()
        if "bart" in text or "16th" in text or "24th" in text:
            return 85.0
        if "muni" in text:
            return 70.0
        return 60.0
    return 50.0


def _score_parking(has_parking: bool | None, parking_type: str | None) -> float:
    if has_parking is False:
        return 0.0
    if has_parking is None:
        return 20.0
    mapping = {"garage": 100, "lot": 70, "street": 40}
    return float(mapping.get(parking_type or "", 50))


def _score_pets(is_pet_friendly: bool | None, pet_details: str | None) -> float:
    if is_pet_friendly is None:
        return 30.0
    if not is_pet_friendly:
        return 0.0
    if pet_details and "cats only" in pet_details.lower():
        return 50.0
    return 100.0


def _score_outdoor(has_outdoor: bool | None) -> float:
    if has_outdoor is None:
        return 20.0
    return 100.0 if has_outdoor else 0.0


def _score_move_in(available_date: str | None, deadline: str = "2026-10-31") -> float:
    if not available_date:
        return 50.0
    try:
        avail = parse_date(available_date).replace(tzinfo=None)
        dl = datetime.strptime(deadline, "%Y-%m-%d")
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        if avail <= now:
            return 100.0
        if avail > dl:
            days_over = (avail - dl).days
            return _clamp(100 - days_over * 5)

        total_window = (dl - now).days or 1
        days_until = (avail - now).days
        return _clamp(100 - (days_until / total_window) * 30)
    except (ValueError, TypeError):
        return 50.0


def _score_lease(lease_term: str | None) -> float:
    if not lease_term:
        return 50.0
    term = lease_term.lower()
    if "month-to-month" in term or "flexible" in term or "short" in term:
        return 100.0
    if "12" in term or "1 year" in term or "one year" in term:
        return 60.0
    if "24" in term or "2 year" in term or "two year" in term:
        return 20.0
    return 50.0


def _score_price(price: int) -> float:
    if price <= 4000:
        return 100.0
    if price >= 10000:
        return 0.0
    return _clamp((10000 - price) / (10000 - 4000) * 100)


def _score_bathroom_match(bathrooms: float, preferred: int = 2) -> float:
    if bathrooms >= preferred:
        return 100.0
    if bathrooms >= 1.5:
        return 60.0
    if bathrooms >= 1:
        return 30.0
    return 0.0


def _score_neighborhood(
    neighborhood: str, target_neighborhoods: list[str]
) -> float:
    if not neighborhood:
        return 10.0
    hood_lower = neighborhood.lower()
    for target in target_neighborhoods:
        if target.lower() in hood_lower or hood_lower in target.lower():
            return 100.0
    return 20.0


def score_listing(
    listing: Listing,
    weights: dict,
    move_in_deadline: str = "2026-10-31",
    preferred_bathrooms: int = 2,
    neighborhoods: list[str] | None = None,
) -> float:
    scorers = {
        "neighborhood": _score_neighborhood(
            listing.neighborhood, neighborhoods or []
        ),
        "bathroom_match": _score_bathroom_match(
            listing.bathrooms, preferred_bathrooms
        ),
        "sqft": _score_sqft(listing.sqft),
        "building_type": _score_building_type(listing.building_type),
        "laundry": _score_laundry(listing.has_in_unit_laundry),
        "transit": _score_transit(listing.transit_score, listing.nearest_transit),
        "parking": _score_parking(listing.has_parking, listing.parking_type),
        "pets": _score_pets(listing.is_pet_friendly, listing.pet_details),
        "outdoor": _score_outdoor(listing.has_outdoor_space),
        "move_in": _score_move_in(listing.available_date, move_in_deadline),
        "lease": _score_lease(listing.lease_term),
        "price": _score_price(listing.price),
    }

    listing.score_breakdown = {k: round(v, 1) for k, v in scorers.items()}

    total_weight = sum(weights.values())
    if total_weight == 0:
        return 0.0

    weighted_sum = sum(scorers.get(k, 0) * w for k, w in weights.items())
    return round(weighted_sum / total_weight, 1)
