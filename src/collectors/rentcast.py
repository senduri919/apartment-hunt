from __future__ import annotations

import logging

import requests

from src.collectors.base import BaseCollector
from src.config import Config
from src.models import Listing, generate_listing_id

logger = logging.getLogger(__name__)

API_BASE = "https://api.rentcast.io/v1/listings/rental/long-term"


class RentCastCollector(BaseCollector):

    @property
    def name(self) -> str:
        return "rentcast"

    def collect(self) -> list[Listing]:
        if not self.config.rentcast_api_key:
            logger.warning("RentCast: no API key configured, skipping")
            return []

        if not self.check_budget():
            return []

        search = self.config.search
        params = {
            "city": search.city,
            "state": search.state,
            "bedrooms": search.min_bedrooms,
            "bathrooms": search.min_bathrooms,
            "status": "Active",
            "limit": 500,
        }

        headers = {
            "X-Api-Key": self.config.rentcast_api_key,
            "Accept": "application/json",
        }

        try:
            logger.info(f"Fetching RentCast listings for {search.city}, {search.state}")
            resp = requests.get(API_BASE, params=params, headers=headers, timeout=30)
            self.record_api_call()

            if resp.status_code == 429:
                logger.warning("RentCast: rate limited")
                return []

            if resp.status_code == 403:
                logger.error(f"RentCast: 403 Forbidden — the listings endpoint may not be "
                             f"available on the free tier. Response: {resp.text[:300]}")
                return []

            resp.raise_for_status()
            data = resp.json()

        except requests.RequestException as e:
            logger.error(f"RentCast API error: {e}")
            return []

        raw_listings = data if isinstance(data, list) else data.get("listings", data.get("results", []))

        listings = []
        for item in raw_listings:
            listing = self._parse_listing(item)
            if listing and self._matches_filters(listing):
                listings.append(listing)

        logger.info(f"RentCast: found {len(listings)} matching listings")
        return listings

    def _parse_listing(self, item: dict) -> Listing | None:
        address = item.get("formattedAddress") or item.get("addressLine1", "")
        price = item.get("price") or item.get("rent")
        if not address or not price:
            return None

        try:
            price = int(price)
        except (ValueError, TypeError):
            return None

        bedrooms = item.get("bedrooms", 0) or 0
        bathrooms = item.get("bathrooms", 0) or 0

        listing = Listing(
            source="rentcast",
            source_id=str(item.get("id", "")),
            source_url=item.get("listingUrl", ""),
            address=address,
            city=item.get("city", "San Francisco"),
            state=item.get("state", "CA"),
            zip_code=str(item.get("zipCode", "")),
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
            price=price,
            bedrooms=int(bedrooms),
            bathrooms=float(bathrooms),
            sqft=item.get("squareFootage"),
            property_type=item.get("propertyType"),
            year_built=item.get("yearBuilt"),
        )

        if item.get("lastSeenDate"):
            listing.last_seen = item["lastSeenDate"]

        listing.id = generate_listing_id(listing.address, listing.price, listing.bedrooms)

        self._detect_neighborhood(listing)

        return listing

    def _detect_neighborhood(self, listing: Listing):
        addr_lower = listing.address.lower()
        zip_code = listing.zip_code

        mission_zips = {"94110", "94114"}
        hayes_zips = {"94102", "94103"}

        if zip_code in mission_zips or "mission" in addr_lower:
            listing.neighborhood = "Mission District"
        elif zip_code in hayes_zips or "hayes" in addr_lower:
            listing.neighborhood = "Hayes Valley"

    def _matches_filters(self, listing: Listing) -> bool:
        search = self.config.search
        if listing.price > search.max_price:
            return False
        if listing.bedrooms < search.min_bedrooms:
            return False
        if listing.bathrooms < search.min_bathrooms:
            return False
        valid_zips = set(search.zip_codes)
        if listing.zip_code and listing.zip_code not in valid_zips and not listing.neighborhood:
            return False
        return True
