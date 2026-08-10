from __future__ import annotations

import logging
import time

import requests

from src.collectors.base import BaseCollector
from src.models import Listing, generate_listing_id

logger = logging.getLogger(__name__)

APIFY_ACTOR_ID = "scrapemind~zumpercom-scraper"


class ZumperCollector(BaseCollector):

    @property
    def name(self) -> str:
        return "zumper"

    def collect(self) -> list[Listing]:
        if not self.config.apify_api_key:
            logger.warning("Zumper: no Apify API key configured, skipping")
            return []

        if not self.check_budget():
            return []

        search = self.config.search
        run_input = {
            "city": search.city,
            "state": search.state,
            "minBedrooms": search.min_bedrooms,
            "minBathrooms": search.min_bathrooms,
            "maxPrice": search.max_price,
            "maxResults": 100,
        }

        headers = {
            "Authorization": f"Bearer {self.config.apify_api_key}",
            "Content-Type": "application/json",
        }

        try:
            logger.info("Starting Zumper scraper via Apify")
            start_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs"
            resp = requests.post(start_url, json=run_input, headers=headers, timeout=30)
            self.record_api_call()

            if resp.status_code == 429:
                logger.warning("Zumper/Apify: rate limited")
                return []

            if resp.status_code in (401, 403):
                logger.error(f"Zumper/Apify auth error ({resp.status_code}): {resp.text[:300]}")
                token_url = f"{start_url}?token={self.config.apify_api_key}"
                logger.info("Retrying Apify with token query param")
                resp = requests.post(token_url, json=run_input, timeout=30)
                if resp.status_code in (401, 403):
                    logger.error(f"Zumper/Apify retry failed ({resp.status_code}): {resp.text[:300]}")
                    return []

            resp.raise_for_status()
            run_data = resp.json().get("data", {})
            run_id = run_data.get("id")

            if not run_id:
                logger.error("Zumper: failed to start Apify actor run")
                return []

            results = self._wait_for_results(run_id, headers, self.config.apify_api_key)
            if not results:
                return []

        except requests.RequestException as e:
            logger.error(f"Zumper/Apify error: {e}")
            return []

        listings = []
        for item in results:
            listing = self._parse_listing(item)
            if listing and self._matches_filters(listing):
                listings.append(listing)

        logger.info(f"Zumper: found {len(listings)} matching listings")
        return listings

    def _wait_for_results(self, run_id: str, headers: dict, token: str, max_wait: int = 120) -> list:
        dataset_url = f"https://api.apify.com/v2/actor-runs/{run_id}"
        token_param = {"token": token}
        elapsed = 0
        poll_interval = 10

        while elapsed < max_wait:
            try:
                resp = requests.get(dataset_url, headers=headers, params=token_param, timeout=15)
                resp.raise_for_status()
                status = resp.json().get("data", {}).get("status")
                logger.info(f"Apify run status: {status}")

                if status == "SUCCEEDED":
                    dataset_id = resp.json()["data"].get("defaultDatasetId")
                    if dataset_id:
                        items_resp = requests.get(
                            f"https://api.apify.com/v2/datasets/{dataset_id}/items",
                            headers=headers, params=token_param, timeout=30,
                        )
                        items_resp.raise_for_status()
                        return items_resp.json()
                    return []

                if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    logger.error(f"Zumper Apify run {status}")
                    return []

            except requests.RequestException as e:
                logger.warning(f"Polling Apify run status: {e}")

            time.sleep(poll_interval)
            elapsed += poll_interval

        logger.warning("Zumper: Apify run timed out")
        return []

    def _parse_listing(self, item: dict) -> Listing | None:
        address = item.get("address", "") or item.get("streetAddress", "")
        price = item.get("price") or item.get("rent")

        if not price:
            return None

        if isinstance(price, str):
            try:
                price = int(float(price.replace("$", "").replace(",", "").split("/")[0].split("-")[0]))
            except (ValueError, TypeError):
                return None

        listing = Listing(
            source="zumper",
            source_id=str(item.get("id", "")),
            source_url=item.get("url", ""),
            address=address,
            city=item.get("city", "San Francisco"),
            state=item.get("state", "CA"),
            zip_code=str(item.get("zipCode", item.get("zip", ""))),
            latitude=item.get("latitude") or item.get("lat"),
            longitude=item.get("longitude") or item.get("lng"),
            price=int(price),
            bedrooms=int(item.get("bedrooms", 0) or 0),
            bathrooms=float(item.get("bathrooms", 0) or 0),
            sqft=item.get("sqft") or item.get("squareFeet"),
            property_type=item.get("propertyType") or item.get("buildingType"),
            description=item.get("description", ""),
        )

        images = item.get("images", []) or item.get("photos", [])
        if isinstance(images, list):
            listing.images = [img if isinstance(img, str) else img.get("url", "") for img in images[:10]]

        if item.get("amenities"):
            amenities_lower = " ".join(str(a).lower() for a in item["amenities"])
            if "laundry in unit" in amenities_lower or "washer" in amenities_lower:
                listing.has_in_unit_laundry = True
            if "parking" in amenities_lower or "garage" in amenities_lower:
                listing.has_parking = True
            if "pet" in amenities_lower or "dog" in amenities_lower or "cat" in amenities_lower:
                listing.is_pet_friendly = True

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
