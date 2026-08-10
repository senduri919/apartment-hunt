from __future__ import annotations

import logging

import requests

from src.collectors.base import BaseCollector
from src.models import Listing, generate_listing_id

logger = logging.getLogger(__name__)


class RedfinCollector(BaseCollector):

    @property
    def name(self) -> str:
        return "redfin"

    def collect(self) -> list[Listing]:
        if not self.config.rapidapi_key:
            logger.warning("Redfin: no RapidAPI key configured, skipping")
            return []

        if not self.check_budget():
            return []

        search = self.config.search
        url = "https://redfin-com-data.p.rapidapi.com/properties/search-rent"
        params = {
            "location": f"{search.city}, {search.state}",
            "minBeds": search.min_bedrooms,
            "minBaths": search.min_bathrooms,
            "maxRent": search.max_price,
        }
        headers = {
            "x-rapidapi-key": self.config.rapidapi_key,
            "x-rapidapi-host": "redfin-com-data.p.rapidapi.com",
        }

        try:
            logger.info("Fetching Redfin listings via RapidAPI")
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            self.record_api_call()

            if resp.status_code == 429:
                logger.warning("Redfin: rate limited")
                return []

            if resp.status_code == 403:
                logger.error(f"Redfin: 403 Forbidden — you may need to subscribe to the "
                             f"Redfin provider on RapidAPI. Response: {resp.text[:300]}")
                return []

            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error(f"Redfin API error: {e}")
            return []

        if isinstance(data, dict):
            logger.info(f"Redfin response keys: {list(data.keys())}")

        props = data.get("properties", data.get("results", data.get("data", [])))
        if not isinstance(props, list):
            props = []

        listings = []
        for item in props:
            listing = self._parse_listing(item)
            if listing and self._matches_filters(listing):
                listings.append(listing)

        logger.info(f"Redfin: found {len(listings)} matching listings")
        return listings

    def _parse_listing(self, item: dict) -> Listing | None:
        address = (item.get("address", "") or item.get("streetAddress", "")
                   or item.get("formattedAddress", ""))
        price = item.get("price") or item.get("rent") or item.get("listPrice")

        if not price:
            return None

        if isinstance(price, str):
            try:
                price = int(float(price.replace("$", "").replace(",", "").split("/")[0]))
            except (ValueError, TypeError):
                return None

        listing = Listing(
            source="redfin",
            source_id=str(item.get("id", item.get("propertyId", item.get("mlsId", "")))),
            source_url=item.get("url", item.get("listingUrl", "")),
            address=address,
            city=item.get("city", "San Francisco"),
            state=item.get("state", "CA"),
            zip_code=str(item.get("zipCode", item.get("zip", ""))),
            latitude=item.get("latitude") or item.get("lat"),
            longitude=item.get("longitude") or item.get("lng"),
            price=int(price),
            bedrooms=int(item.get("beds", item.get("bedrooms", 0)) or 0),
            bathrooms=float(item.get("baths", item.get("bathrooms", 0)) or 0),
            sqft=item.get("sqft") or item.get("squareFootage") or item.get("livingArea"),
            property_type=item.get("propertyType") or item.get("homeType"),
            description=item.get("description", ""),
        )

        images = item.get("photos", []) or item.get("images", [])
        if isinstance(images, list):
            listing.images = [
                img if isinstance(img, str) else img.get("url", img.get("href", ""))
                for img in images[:10]
            ]

        listing.id = generate_listing_id(listing.address or str(listing.source_id), listing.price, listing.bedrooms)
        self._detect_neighborhood(listing)
        return listing

    def _detect_neighborhood(self, listing: Listing):
        addr_lower = listing.address.lower()
        zip_code = listing.zip_code
        if zip_code in {"94110", "94114"} or "mission" in addr_lower:
            listing.neighborhood = "Mission District"
        elif zip_code in {"94102", "94103"} or "hayes" in addr_lower:
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
