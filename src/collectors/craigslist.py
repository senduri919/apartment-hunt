from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import feedparser
import requests
from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector
from src.config import Config
from src.models import Listing, generate_listing_id

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

NEIGHBORHOOD_KEYWORDS = {
    "mission district": ["mission district", "mission dist", "the mission", "mission sf",
                         "valencia", "guerrero", "24th street", "16th st mission"],
    "hayes valley": ["hayes valley", "hayes st", "patricia's green", "hayes"],
}


class CraigslistCollector(BaseCollector):

    @property
    def name(self) -> str:
        return "craigslist"

    def collect(self) -> list[Listing]:
        search = self.config.search
        params = {
            "min_bedrooms": search.min_bedrooms,
            "min_bathrooms": search.min_bathrooms,
            "max_price": search.max_price,
            "availabilityMode": 0,
            "format": "rss",
        }
        url = f"https://sfbay.craigslist.org/search/sfc/apa?{urlencode(params)}"

        logger.info(f"Fetching Craigslist RSS: {url}")

        try:
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except requests.RequestException as e:
            logger.error(f"Craigslist fetch error: {e}")
            feed = feedparser.parse(url)

        if feed.bozo:
            logger.warning(f"Craigslist RSS bozo: {feed.bozo_exception}")

        if not feed.entries:
            logger.warning("Craigslist: no entries found in RSS feed, trying HTML fallback")
            return self._collect_html_fallback()

        listings = []
        for entry in feed.entries:
            listing = self._parse_entry(entry)
            if listing:
                listings.append(listing)

        logger.info(f"Craigslist: found {len(listings)} listings from RSS")

        for listing in listings[:20]:
            self._enrich_listing(listing)
            time.sleep(random.uniform(1.5, 3.0))

        return listings

    def _parse_entry(self, entry: dict) -> Listing | None:
        title = entry.get("title", "")
        link = entry.get("link", "")
        summary = entry.get("summary", "")
        published = entry.get("published", "")

        price = self._extract_price(title)
        if not price or price > self.config.search.max_price:
            return None

        bedrooms = self._extract_bedrooms(title)
        neighborhood = self._detect_neighborhood(title + " " + summary)

        address = self._extract_location(title, entry)

        listing = Listing(
            source="craigslist",
            source_id=link.split("/")[-1].replace(".html", ""),
            source_url=link,
            address=address,
            neighborhood=neighborhood,
            price=price,
            bedrooms=bedrooms or self.config.search.min_bedrooms,
            description=self._clean_html(summary),
        )

        if published:
            try:
                listing.first_seen = published
            except (ValueError, TypeError):
                pass

        listing.id = generate_listing_id(listing.address or link, listing.price, listing.bedrooms)
        return listing

    def _enrich_listing(self, listing: Listing):
        try:
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            resp = requests.get(listing.source_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return

            soup = BeautifulSoup(resp.text, "html.parser")

            attrs_group = soup.select(".mapAndAttrs .attrgroup")
            for group in attrs_group:
                text = group.get_text(" ", strip=True).lower()
                sqft_match = re.search(r'(\d{3,5})\s*ft', text)
                if sqft_match:
                    listing.sqft = int(sqft_match.group(1))

                bath_match = re.search(r'(\d+(?:\.\d)?)\s*ba', text)
                if bath_match:
                    listing.bathrooms = float(bath_match.group(1))

                br_match = re.search(r'(\d+)\s*br', text)
                if br_match:
                    listing.bedrooms = int(br_match.group(1))

            body = soup.select_one("#postingbody")
            if body:
                listing.description = body.get_text("\n", strip=True).replace(
                    "QR Code Link to This Post", ""
                ).strip()

            images = []
            for img in soup.select("#thumbs a"):
                href = img.get("href", "")
                if href:
                    images.append(href)
            if not images:
                for img in soup.select(".gallery img, .swipe img"):
                    src = img.get("src", "")
                    if src and "images.craigslist.org" in src:
                        images.append(src)
            listing.images = images[:10]

            address_el = soup.select_one(".mapaddress")
            if address_el:
                listing.address = address_el.get_text(strip=True)

            map_el = soup.select_one("#map")
            if map_el:
                lat = map_el.get("data-latitude")
                lng = map_el.get("data-longitude")
                if lat and lng:
                    listing.latitude = float(lat)
                    listing.longitude = float(lng)

        except requests.RequestException as e:
            logger.debug(f"Failed to enrich listing {listing.source_url}: {e}")

    def _collect_html_fallback(self) -> list[Listing]:
        search = self.config.search
        params = {
            "min_bedrooms": search.min_bedrooms,
            "min_bathrooms": search.min_bathrooms,
            "max_price": search.max_price,
            "availabilityMode": 0,
        }
        url = f"https://sfbay.craigslist.org/search/sfc/apa?{urlencode(params)}"

        try:
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Craigslist HTML fallback error: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        listings = []

        selectors = [
            ".cl-static-search-result",
            ".result-row",
            "li.cl-search-result",
            ".result-info",
            ".gallery-card",
        ]
        results = []
        for sel in selectors:
            results = soup.select(sel)
            if results:
                logger.info(f"Craigslist HTML: matched {len(results)} elements with '{sel}'")
                break

        if not results:
            all_links = soup.select("a[href*='/apa/']")
            logger.info(f"Craigslist HTML: found {len(all_links)} links containing '/apa/'")
            results = all_links

        for result in results:
            try:
                link_el = result if result.name == "a" else result.select_one("a[href]")
                if not link_el:
                    continue
                link = link_el.get("href", "")
                if not link.startswith("http"):
                    link = f"https://sfbay.craigslist.org{link}"

                if "/apa/" not in link and "/d/" not in link:
                    continue

                title = link_el.get_text(strip=True) or result.get_text(strip=True)

                price = self._extract_price(title)
                if not price:
                    price_el = result.select_one(".priceinfo, .result-price, .price")
                    if price_el:
                        price = self._extract_price(price_el.get_text())
                if not price:
                    full_text = result.get_text()
                    price = self._extract_price(full_text)
                if not price or price > search.max_price:
                    continue

                bedrooms = self._extract_bedrooms(title) or search.min_bedrooms
                neighborhood = self._detect_neighborhood(title)

                listing = Listing(
                    source="craigslist",
                    source_id=link.split("/")[-1].replace(".html", ""),
                    source_url=link,
                    address=self._extract_location(title, {}),
                    neighborhood=neighborhood,
                    price=price,
                    bedrooms=bedrooms,
                    description=title,
                )
                listing.id = generate_listing_id(listing.address or link, listing.price, listing.bedrooms)
                listings.append(listing)

            except Exception as e:
                logger.debug(f"Craigslist HTML parse error for result: {e}")
                continue

        logger.info(f"Craigslist HTML fallback: {len(listings)} listings before neighborhood filter")

        for listing in listings[:30]:
            self._enrich_listing(listing)
            time.sleep(random.uniform(1.5, 3.0))

        logger.info(f"Craigslist HTML fallback: {len(listings)} listings after enrichment")
        return listings

    def _matches_neighborhood(self, listing: Listing) -> bool:
        if listing.neighborhood:
            return True
        text = f"{listing.address} {listing.description}".lower()
        for hood, keywords in NEIGHBORHOOD_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return True
        return False

    def _detect_neighborhood(self, text: str) -> str:
        text_lower = text.lower()
        for hood, keywords in NEIGHBORHOOD_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return hood.title()
        return ""

    def _extract_price(self, title: str) -> int | None:
        match = re.search(r'\$(\d{1,2}[,.]?\d{3})', title)
        if match:
            return int(match.group(1).replace(",", "").replace(".", ""))
        return None

    def _extract_bedrooms(self, title: str) -> int | None:
        match = re.search(r'(\d+)\s*br\b', title, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def _extract_location(self, title: str, entry: dict) -> str:
        loc_match = re.search(r'\(([^)]+)\)\s*$', title)
        if loc_match:
            return loc_match.group(1).strip()
        dc_source = entry.get("dc_source", "")
        if dc_source:
            return dc_source
        return ""

    @staticmethod
    def _clean_html(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(" ", strip=True)
