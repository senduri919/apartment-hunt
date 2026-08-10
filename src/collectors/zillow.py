from __future__ import annotations

import logging

import requests

from src.collectors.base import BaseCollector
from src.models import Listing, generate_listing_id

logger = logging.getLogger(__name__)


class ZillowCollector(BaseCollector):

    @property
    def name(self) -> str:
        return "zillow"

    API_HOST = "real-estate-zillow-com.p.rapidapi.com"
    API_BASE = f"https://{API_HOST}"

    SEARCH_URLS = [
        "https://www.zillow.com/mission-district-san-francisco-ca/rentals/4-_beds/",
        "https://www.zillow.com/hayes-valley-san-francisco-ca/rentals/4-_beds/",
        "https://www.zillow.com/san-francisco-ca/rentals/4-_beds/",
    ]

    def collect(self) -> list[Listing]:
        if not self.config.rapidapi_key:
            logger.warning("Zillow: no RapidAPI key configured, skipping")
            return []

        if not self.check_budget():
            return []

        headers = {
            "x-rapidapi-key": self.config.rapidapi_key,
            "x-rapidapi-host": self.API_HOST,
        }

        all_listings = []
        seen_ids = set()
        for url in self.SEARCH_URLS:
            listings = self._try_search(headers, {"url": url})
            for listing in listings:
                if listing.source_id not in seen_ids:
                    seen_ids.add(listing.source_id)
                    all_listings.append(listing)
            if all_listings:
                break

        if not all_listings:
            logger.warning("Zillow: no listings found from any URL")
        else:
            logger.info(f"Zillow: {len(all_listings)} unique listings total")
        return all_listings

    def _try_search(self, headers: dict, location_params: dict) -> list[Listing]:
        url = f"{self.API_BASE}/v1/search/rent"
        params = dict(location_params)

        label = list(location_params.keys())[0]
        logger.info(f"Zillow: trying {label}={list(location_params.values())[0]}")

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            self.record_api_call()

            if resp.status_code == 429:
                logger.warning("Zillow: rate limited")
                return []

            if resp.status_code in (403, 404):
                logger.warning(f"Zillow: {resp.status_code}, trying next params")
                return []

            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error(f"Zillow API error: {e}")
            return []

        if isinstance(data, dict):
            api_status = data.get("status")
            if api_status and api_status >= 400:
                desc = data.get("description", "unknown error")
                logger.warning(f"Zillow API error {api_status}: {desc}")
                return []
            logger.info(f"Zillow response keys: {list(data.keys())}")

        props = self._extract_results(data)
        if not props:
            snippet = str(data)[:500]
            logger.warning(f"Zillow: 0 results. Preview: {snippet}")
            return []

        logger.info(f"Zillow: extracted {len(props)} raw results")
        if props:
            first = props[0]
            logger.info(f"Zillow first result keys: {list(first.keys()) if isinstance(first, dict) else type(first)}")

        listings = []
        parsed = 0
        for item in props:
            listing = self._parse_listing(item)
            if not listing:
                continue
            parsed += 1
            if self._matches_filters(listing):
                listings.append(listing)
            elif parsed <= 3:
                logger.info(f"Zillow filtered out: price={listing.price} beds={listing.bedrooms} "
                            f"baths={listing.bathrooms} zip={listing.zip_code} hood={listing.neighborhood}")

        logger.info(f"Zillow: {len(listings)} listings after filtering ({parsed} parsed, {len(props)} raw)")
        return listings

    def _extract_results(self, data) -> list:
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        for key in ("props", "results", "searchResults", "properties",
                     "listings", "data", "items", "list", "cat1"):
            val = data.get(key)
            if isinstance(val, list) and val:
                return val
            if isinstance(val, dict):
                for sub_key in ("listings", "listResults", "searchResults",
                                "results", "properties", "items"):
                    sub = val.get(sub_key)
                    if isinstance(sub, list) and sub:
                        return sub
        return []

    def _parse_listing(self, item: dict) -> Listing | None:
        address = (item.get("address", "") or item.get("addressStreet", "")
                   or item.get("streetAddress", ""))

        price = item.get("price") or item.get("minBaseRent") or item.get("rentZestimate")
        units = item.get("units")
        if not price and isinstance(units, list) and units:
            unit_prices = []
            for u in units:
                p = u.get("price")
                if p:
                    try:
                        unit_prices.append(int(str(p).replace("$", "").replace(",", "").replace("+", "").split("/")[0]))
                    except (ValueError, TypeError):
                        pass
            price = min(unit_prices) if unit_prices else None
        if isinstance(price, str):
            try:
                price = int(float(price.replace("$", "").replace(",", "").replace("+", "").split("/")[0]))
            except (ValueError, TypeError):
                return None
        if not price:
            return None
        price = int(price)

        bedrooms = item.get("bedrooms") or item.get("beds") or 0
        bathrooms = item.get("bathrooms") or item.get("baths") or 0
        if not bedrooms and isinstance(units, list) and units:
            for u in units:
                b = u.get("beds") or u.get("bedrooms")
                if b:
                    bedrooms = max(int(b), int(bedrooms or 0))
                ba = u.get("baths") or u.get("bathrooms")
                if ba:
                    bathrooms = max(float(ba), float(bathrooms or 0))

        detail_url = item.get("detailUrl", "")
        if detail_url and detail_url.startswith("/"):
            detail_url = f"https://www.zillow.com{detail_url}"
        if not detail_url:
            zpid = item.get("zpid", "")
            if zpid:
                detail_url = f"https://www.zillow.com/homedetails/{zpid}_zpid/"

        lat_long = item.get("latLong")
        lat = item.get("latitude") or (lat_long.get("latitude") if isinstance(lat_long, dict) else None)
        lng = item.get("longitude") or (lat_long.get("longitude") if isinstance(lat_long, dict) else None)

        listing = Listing(
            source="zillow",
            source_id=str(item.get("zpid", item.get("id", ""))),
            source_url=detail_url,
            address=address,
            city=item.get("city", item.get("addressCity", "San Francisco")),
            state=item.get("state", item.get("addressState", "CA")),
            zip_code=str(item.get("zipcode", item.get("addressZipcode", ""))),
            latitude=lat,
            longitude=lng,
            price=price,
            bedrooms=int(bedrooms or 0),
            bathrooms=float(bathrooms or 0),
            sqft=item.get("livingArea") or item.get("area") or item.get("sqft"),
            property_type=item.get("homeType") or item.get("propertyType"),
        )

        if item.get("imgSrc"):
            listing.images = [item["imgSrc"]]
        if item.get("buildingName"):
            listing.description = item["buildingName"]

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
        if listing.bedrooms and listing.bedrooms < search.min_bedrooms:
            return False
        if listing.bathrooms and listing.bathrooms < search.min_bathrooms:
            return False
        valid_zips = set(search.zip_codes)
        if listing.zip_code and listing.zip_code not in valid_zips and not listing.neighborhood:
            return False
        return True
