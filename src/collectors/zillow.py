from __future__ import annotations

import json
import logging
import time
import urllib.parse

import requests

from src.collectors.base import BaseCollector
from src.models import Listing, generate_listing_id

logger = logging.getLogger(__name__)

NEIGHBORHOOD_BOUNDS = {
    "Mission District": {"lat": (37.748, 37.766), "lng": (-122.427, -122.406)},
    "Hayes Valley": {"lat": (37.770, 37.780), "lng": (-122.432, -122.416)},
    "Financial District": {"lat": (37.790, 37.798), "lng": (-122.403, -122.394)},
}

APIFY_ACTOR = "maxcopell~zillow-scraper"

SF_MAP_BOUNDS = {
    "north": 37.812,
    "south": 37.708,
    "east": -122.357,
    "west": -122.514,
}


def _build_search_url(min_beds: int, max_price: int) -> str:
    search_state = {
        "isMapVisible": True,
        "mapBounds": SF_MAP_BOUNDS,
        "filterState": {
            "fr": {"value": True},
            "fsba": {"value": False},
            "fsbo": {"value": False},
            "nc": {"value": False},
            "cmsn": {"value": False},
            "auc": {"value": False},
            "fore": {"value": False},
            "beds": {"min": min_beds},
            "mp": {"max": max_price},
        },
        "isListVisible": True,
    }
    encoded = urllib.parse.quote(json.dumps(search_state, separators=(",", ":")))
    return f"https://www.zillow.com/san-francisco-ca/rentals/?searchQueryState={encoded}"


class ZillowCollector(BaseCollector):

    @property
    def name(self) -> str:
        return "zillow"

    def collect(self) -> list[Listing]:
        if not self.config.apify_api_key:
            logger.warning("Zillow: no Apify API key configured, skipping")
            return []

        if not self.check_budget():
            return []

        search_url = _build_search_url(
            self.config.search.min_bedrooms,
            self.config.search.max_price,
        )
        logger.info(f"Zillow: searching via Apify actor {APIFY_ACTOR}")

        headers = {
            "Authorization": f"Bearer {self.config.apify_api_key}",
            "Content-Type": "application/json",
        }

        run_input = {
            "searchUrls": [{"url": search_url}],
            "resultsLimit": 100,
            "extractionMethod": "PAGINATION",
        }

        results = self._run_actor(run_input, headers)
        if not results:
            logger.warning("Zillow: no results from Apify scraper")
            return []

        logger.info(f"Zillow: scraped {len(results)} raw results")

        listings = []
        filtered_count = 0
        for item in results:
            listing = self._parse_listing(item)
            if not listing:
                continue
            if self._matches_filters(listing):
                listings.append(listing)
            else:
                filtered_count += 1
                if filtered_count <= 3:
                    logger.info(
                        f"Zillow filtered out: price={listing.price} beds={listing.bedrooms} "
                        f"baths={listing.bathrooms} zip={listing.zip_code} hood={listing.neighborhood}"
                    )

        logger.info(f"Zillow: {len(listings)} listings after filtering ({len(results)} raw)")
        return listings

    def _run_actor(self, run_input: dict, headers: dict) -> list | None:
        start_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/runs"

        try:
            resp = requests.post(start_url, json=run_input, headers=headers, timeout=30)
            self.record_api_call()

            if resp.status_code == 429:
                logger.warning("Zillow/Apify: rate limited")
                return []

            if resp.status_code in (401, 403):
                logger.error(f"Zillow/Apify auth error ({resp.status_code}): {resp.text[:200]}")
                return None

            resp.raise_for_status()
            run_data = resp.json().get("data", {})
            run_id = run_data.get("id")

            if not run_id:
                logger.error("Zillow: failed to start Apify actor")
                return None

            return self._wait_for_results(run_id, headers, self.config.apify_api_key)

        except requests.RequestException as e:
            logger.error(f"Zillow/Apify error: {e}")
            return None

    def _wait_for_results(self, run_id: str, headers: dict, token: str, max_wait: int = 120) -> list:
        run_url = f"https://api.apify.com/v2/actor-runs/{run_id}"
        token_param = {"token": token}
        elapsed = 0
        poll_interval = 10

        while elapsed < max_wait:
            try:
                resp = requests.get(run_url, headers=headers, params=token_param, timeout=15)
                resp.raise_for_status()
                status = resp.json().get("data", {}).get("status")
                logger.info(f"Zillow Apify run status: {status}")

                if status == "SUCCEEDED":
                    dataset_id = resp.json()["data"].get("defaultDatasetId")
                    if dataset_id:
                        items_resp = requests.get(
                            f"https://api.apify.com/v2/datasets/{dataset_id}/items",
                            headers=headers, params=token_param, timeout=30,
                        )
                        items_resp.raise_for_status()
                        items = items_resp.json()
                        logger.info(f"Zillow: dataset returned {len(items)} items")
                        return items
                    return []

                if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    logger.error(f"Zillow Apify run {status}")
                    return []

            except requests.RequestException as e:
                logger.warning(f"Polling Zillow Apify run: {e}")

            time.sleep(poll_interval)
            elapsed += poll_interval

        logger.warning("Zillow: Apify run timed out")
        return []

    def _parse_listing(self, item: dict) -> Listing | None:
        address = item.get("address", "") or item.get("addressStreet", "")
        if not address or item.get("isUndisclosedAddress"):
            return None

        price = item.get("unformattedPrice")
        if not price:
            price_str = item.get("price", "")
            if isinstance(price_str, str):
                try:
                    price = int(float(price_str.replace("$", "").replace(",", "").split("/")[0]))
                except (ValueError, TypeError):
                    return None
            elif isinstance(price_str, (int, float)):
                price = int(price_str)
        if not price:
            return None

        bedrooms = item.get("bedrooms") or item.get("beds") or 0
        bathrooms = item.get("bathrooms") or item.get("baths") or 0

        lat_long = item.get("latLong") or item.get("coordinates") or {}
        lat = lat_long.get("latitude") if isinstance(lat_long, dict) else None
        lng = lat_long.get("longitude") if isinstance(lat_long, dict) else None

        detail_url = item.get("detailUrl", "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = f"https://www.zillow.com{detail_url}"

        listing = Listing(
            source="zillow",
            source_id=str(item.get("zpid", item.get("id", ""))),
            source_url=detail_url,
            address=item.get("addressStreet", address.split(",")[0].strip()),
            city=item.get("addressCity", "San Francisco"),
            state=item.get("addressState", "CA"),
            zip_code=str(item.get("addressZipcode", "")),
            latitude=lat,
            longitude=lng,
            price=int(price),
            bedrooms=int(bedrooms or 0),
            bathrooms=float(bathrooms or 0),
            sqft=item.get("livingArea") or item.get("area"),
            property_type=item.get("homeType"),
        )

        if item.get("imgSrc"):
            listing.images = [item["imgSrc"]]

        if item.get("availabilityDate"):
            listing.available_date = str(item["availabilityDate"]).split(" ")[0]

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
        elif zip_code in {"94104", "94111"} or "financial" in addr_lower or "fidi" in addr_lower:
            listing.neighborhood = "Financial District"

        if not listing.neighborhood and listing.latitude and listing.longitude:
            for hood, bounds in NEIGHBORHOOD_BOUNDS.items():
                lat_min, lat_max = bounds["lat"]
                lng_min, lng_max = bounds["lng"]
                if lat_min <= listing.latitude <= lat_max and lng_min <= listing.longitude <= lng_max:
                    listing.neighborhood = hood
                    return

    def _matches_filters(self, listing: Listing) -> bool:
        search = self.config.search
        if listing.price > search.max_price:
            return False
        if listing.bedrooms < search.min_bedrooms:
            return False
        if listing.bedrooms > search.max_bedrooms:
            return False
        if listing.bathrooms and listing.bathrooms < search.min_bathrooms:
            return False
        valid_zips = set(search.zip_codes)
        if listing.zip_code and listing.zip_code not in valid_zips and not listing.neighborhood:
            return False
        return True
