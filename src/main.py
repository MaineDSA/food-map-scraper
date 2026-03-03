"""
Web scraper for Portland Food Map restaurant data.

This module scrapes restaurant information from portlandfoodmap.com by:
1. Fetching restaurant links from the list view page
2. Extracting schema.org Restaurant structured data from each page
3. Flattening the data and saving to a CSV file
"""

import csv
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import cloudscraper
import requests
from bs4 import BeautifulSoup, Tag
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(levelname)s : food-map-scraper:%(name)s : %(message)s")
logger = logging.getLogger(__name__)

HTTP_OK = 200
BASE_URL = "https://www.portlandfoodmap.com/list-view/"
OUTPUT_FILE = Path("portland_restaurants.csv")
RESTAURANT_PATH_MARKER = "/restaurants/"

scraper = cloudscraper.create_scraper(browser={"browser": "firefox", "platform": "windows", "mobile": False})


@dataclass
class Address:
    """Represents a postal address."""

    street_address: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""

    @classmethod
    def from_text(cls, address_text: str) -> "Address":
        """Parse address from text format: '263 Saint John Street, Portland, ME, USA'."""
        parts = [p.strip() for p in address_text.split(",")]

        address = cls()
        if len(parts) >= 1:
            address.street_address = parts[0]
        if len(parts) >= 2:  # noqa: PLR2004
            address.city = parts[1]
        if len(parts) >= 4:  # noqa: PLR2004
            address.country = parts[3]
        if len(parts) >= 3:  # noqa: PLR2004
            if not address.country:
                # Split "ME USA" or similar
                state_country = parts[2].split()
                if len(state_country) >= 1:
                    address.state = state_country[0]
                if len(state_country) >= 2:  # noqa: PLR2004
                    address.country = state_country[1]
            else:
                address.state = parts[2]

        return address

    @classmethod
    def from_schema(cls, schema_address: dict) -> "Address":
        """Create Address from schema.org address dictionary."""
        return cls(
            street_address=schema_address.get("streetAddress", ""),
            city=schema_address.get("addressLocality", ""),
            state=schema_address.get("addressRegion", ""),
            postal_code=schema_address.get("postalCode", ""),
            country=schema_address.get("addressCountry", ""),
        )


@dataclass
class Restaurant:
    """Represents a restaurant with all its details."""

    name: str = ""
    street_address: str = ""
    telephone: str = ""
    url: str = ""

    @classmethod
    def from_schema(cls, schema: dict) -> "Restaurant":
        """Create Restaurant from schema.org data."""
        street_address = ""
        if schema_address := schema.get("address"):
            if isinstance(schema_address, dict):
                street_address = schema_address.get("streetAddress", "")
            elif isinstance(schema_address, Address):
                street_address = schema_address.street_address

        return cls(
            name=schema.get("name", ""),
            street_address=street_address,
            telephone=schema.get("telephone", ""),
            url=schema.get("url", ""),
        )

    def to_flat_dict(self) -> dict[str, str]:
        """Convert Restaurant to flat dictionary for CSV export."""
        return {
            "name": self.name,
            "street_address": self.street_address,
            "telephone": self.telephone,
            "url": self.url,
        }


def fetch_url(url: str, error_context: str) -> str | None:
    """Fetch URL content with unified error handling."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        response = scraper.get(url, headers=headers, timeout=15)

        if response.status_code != HTTP_OK:
            logger.error("HTTP %d error for %s: %s", response.status_code, error_context, url)
            return None

        return response.text

    except requests.exceptions.RequestException as e:
        logger.error("%s error for %s (%s): %s", type(e).__name__, error_context, url, e)
        return None


def extract_schema_data(url: str) -> dict | None:
    """Extract Restaurant schema.org data from a restaurant page using microdata."""
    data = fetch_url(url, "restaurant page")
    if not data:
        return None

    soup = BeautifulSoup(data, "html.parser")
    article = soup.find("article", itemtype="http://schema.org/Restaurant")
    if not article or not isinstance(article, Tag):
        return None

    schema: dict = {"@type": "Restaurant"}

    itemprop_fields = ["telephone"]
    for item_field in itemprop_fields:
        elem = article.find(itemprop=item_field)
        if elem and isinstance(elem, Tag):
            schema[item_field] = elem.get_text(strip=True)

    # Special cases
    name_elem = article.find("h1", class_="entry-title")
    if name_elem and isinstance(name_elem, Tag):
        schema["name"] = name_elem.get_text(strip=True)

    url_elem = article.find("a", itemprop="url")
    if url_elem and isinstance(url_elem, Tag):
        href = url_elem.get("href")
        if href:
            schema["url"] = str(href)

    address_elem = article.find(itemprop="address")
    if address_elem and isinstance(address_elem, Tag):
        schema["address"] = Address.from_text(address_elem.get_text(strip=True))

    return schema


def get_restaurant_links(list_url: str) -> list[str]:
    """Get all unique restaurant links from the list view page."""
    data = fetch_url(list_url, "list page")
    if not data:
        return []

    soup = BeautifulSoup(data, "html.parser")
    links = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]

        # Check if this is a restaurant detail page
        if RESTAURANT_PATH_MARKER in href:
            full_url = urljoin(list_url, href)

            if full_url not in seen:
                seen.add(full_url)
                links.append(full_url)

    return links


def save_to_csv(restaurants: list[Restaurant], output_path: Path) -> None:
    """Save restaurant data to CSV file."""
    if not restaurants:
        logger.warning("No restaurants to save.")
        return

    flat_restaurants = [r.to_flat_dict() for r in restaurants]
    fieldnames = sorted(set().union(*(r.keys() for r in flat_restaurants)))

    logger.info("Writing %d restaurants to %s...", len(restaurants), output_path)
    with output_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat_restaurants)

    logger.info("Done! Data saved to %s", output_path)


def main() -> None:
    """Hey, I just met you, and this is crazy, but I'm the main function, so call me maybe."""
    logger.info("Fetching restaurant links...")
    restaurant_urls = get_restaurant_links(BASE_URL)
    logger.info("Found %d restaurant links", len(restaurant_urls))

    if not restaurant_urls:
        logger.warning("No restaurant links found. The page structure may have changed.")
        return

    all_restaurants = []
    logger.info("Extracting restaurant data...")

    for url in tqdm(restaurant_urls, unit="restaurant"):
        schema_data = extract_schema_data(url)

        if schema_data:
            restaurant = Restaurant.from_schema(schema_data)
            all_restaurants.append(restaurant)
        time.sleep(1)

    if not all_restaurants:
        logger.warning("No restaurant data extracted.")
        return

    save_to_csv(all_restaurants, OUTPUT_FILE)


if __name__ == "__main__":
    main()
