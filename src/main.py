"""Web scraper for Portland Food Map restaurant data."""

import csv
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import cloudscraper
import requests
from bs4 import BeautifulSoup, Tag
from tqdm import tqdm

# Constants
HTTP_OK = 200
BASE_URL = "https://www.portlandfoodmap.com/list-view/"
OUTPUT_FILE = Path("portland_restaurants.csv")
RESTAURANT_PATH_MARKER = "/restaurants/"

logging.basicConfig(level=logging.INFO, format="%(levelname)s : food-map-scraper:%(name)s : %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class Address:
    """
    Represents a postal address.

    Attributes:
        street_address: The house number and street name.
        city: The city name.
        state: The state or province.
        postal_code: The ZIP or postal code.
        country: The country name.

    """

    street_address: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""

    @classmethod
    def from_text(cls, address_text: str) -> "Address":
        """
        Parse address from text.

        Handles formats with or without leading name.

        Args:
            address_text:
                Raw string like 'Central Provisions, 414 Fore St, Portland, ME, USA'
                or '414 Fore St, Portland, ME, USA'.

        """
        parts = [p.strip() for p in address_text.split(",")]
        address = cls()

        combined_name_and_address_parts = 5
        if len(parts) >= combined_name_and_address_parts:
            street_idx, city_idx, state_idx, country_idx = 1, 2, 3, 4
        else:  # not all addresses start with a name
            street_idx, city_idx, state_idx, country_idx = 0, 1, 2, 3

        if len(parts) > street_idx:
            address.street_address = parts[street_idx]
        if len(parts) > city_idx:
            address.city = parts[city_idx]
        if len(parts) > country_idx:
            address.country = parts[country_idx]

        # State/Country logic for the 3rd/4th slots
        if len(parts) > state_idx:
            if not address.country:
                state_country = parts[state_idx].split()
                if len(state_country) >= 1:
                    address.state = state_country[0]
                combined_state_and_country_parts = 2
                if len(state_country) >= combined_state_and_country_parts:
                    address.country = state_country[1]
            else:
                address.state = parts[state_idx]

        return address


@dataclass
class Restaurant:
    """
    Represents a restaurant with all its details.

    Attributes:
        name: Business name.
        street_address: Physical location.
        telephone: Contact number.
        url: Official website.

    """

    name: str = ""
    street_address: str = ""
    telephone: str = ""
    url: str = ""

    @classmethod
    def from_schema(cls, schema: dict[str, Any]) -> "Restaurant":
        """
        Create Restaurant from schema.org data.

        Args:
            schema: Dictionary of schema.org properties.

        Returns:
            A Restaurant instance.

        """
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
        """
        Convert Restaurant to flat dictionary for CSV export.

        Returns:
            dict[str, str]:
                A dictionary where keys are field names and values are strings.

        """
        return {
            "name": self.name,
            "street_address": self.street_address,
            "telephone": self.telephone,
            "url": self.url,
        }


def fetch_url(url: str, scraper_client: cloudscraper.CloudScraper, error_context: str) -> str | None:
    """
    Fetch URL content with unified error handling.

    Args:
        url: The target URL.
        scraper_client: The session/scraper instance to use.
        error_context: String used for logging context.

    Returns:
        str
            The HTML response text or None if the request fails.

    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        response = scraper_client.get(url, headers=headers, timeout=15)
        if response.status_code != HTTP_OK:
            logger.error("HTTP %d error for %s: %s", response.status_code, error_context, url)
            return None
        return response.text
    except requests.exceptions.RequestException as e:
        logger.error("%s error for %s (%s): %s", type(e).__name__, error_context, url, e)
        return None


def extract_schema_data(url: str, scraper_client: cloudscraper.CloudScraper) -> dict[str, Any] | None:
    """
    Extract Restaurant schema.org data from a restaurant page.

    Args:
        url: The restaurant detail page URL.
        scraper_client: The session/scraper instance.

    Returns:
        dict[str, Any]
            Schema data or None if not found.

    """
    data = fetch_url(url, scraper_client, "restaurant page")
    if not data:
        return None

    soup = BeautifulSoup(data, "html.parser")

    article = soup.find("article", itemtype="http://schema.org/Restaurant")
    if not article or not isinstance(article, Tag):
        return None

    schema: dict[str, Any] = {"@type": "Restaurant"}

    # Extract standard fields
    for field in ["telephone"]:
        elem = article.find(itemprop=field)
        if elem and isinstance(elem, Tag):
            schema[field] = elem.get_text(strip=True)

    # Name
    name_elem = article.find("h1", class_="entry-title")
    if name_elem and isinstance(name_elem, Tag):
        schema["name"] = name_elem.get_text(strip=True)

    # URL
    url_elem = article.find("a", itemprop="url")
    if url_elem and isinstance(url_elem, Tag):
        schema["url"] = str(url_elem.get("href", ""))

    # Address
    address_elem = article.find(itemprop="address")
    if address_elem and isinstance(address_elem, Tag):
        schema["address"] = Address.from_text(address_elem.get_text(strip=True))

    return schema


def get_restaurant_links(list_url: str, scraper_client: cloudscraper.CloudScraper) -> list[str]:
    """
    Get all unique restaurant links from the list view page.

    Args:
        list_url: The listing page URL.
        scraper_client: The session/scraper instance.

    Returns:
        list:
            A list of unique restaurant URLs.

    """
    data = fetch_url(list_url, scraper_client, "list page")
    if not data:
        return []

    soup = BeautifulSoup(data, "html.parser")

    links: list[str] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if RESTAURANT_PATH_MARKER in href:
            full_url = urljoin(list_url, href)
            if full_url not in seen:
                seen.add(full_url)
                links.append(full_url)

    return links


def process_restaurants(urls: list[str], scraper_client: cloudscraper.CloudScraper, delay: int = 1) -> list[Restaurant]:
    """
    Scrape restaurant data from a list of URLs.

    Args:
        urls: List of restaurant URLs.
        scraper_client: The session/scraper instance.
        delay: Seconds to sleep between requests.

    Returns:
        list:
            A list of successfully parsed Restaurant objects.

    """
    results: list[Restaurant] = []
    for url in tqdm(urls, unit="restaurant"):
        schema_data = extract_schema_data(url, scraper_client)
        if schema_data:
            results.append(Restaurant.from_schema(schema_data))
        if len(urls) > 1:
            time.sleep(delay)
    return results


def save_to_csv(restaurants: list[Restaurant], output_path: Path) -> None:
    """
    Save restaurant data to CSV file.

    Args:
        restaurants: List of Restaurant objects.
        output_path: Path to the target CSV file.

    """
    if not restaurants:
        logger.warning("No restaurants to save.")
        return

    flat_data = [r.to_flat_dict() for r in restaurants]
    fieldnames = sorted(set().union(*(row.keys() for row in flat_data)))

    logger.info("Writing %d restaurants to %s...", len(restaurants), output_path)
    with output_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat_data)
    logger.info("Done! Data saved to %s", output_path)


def main() -> None:
    """Hey, I just met you, and this is crazy, but I'm the main function, so call me maybe."""
    client = cloudscraper.create_scraper(browser={"browser": "firefox"})

    urls = get_restaurant_links(BASE_URL, client)
    restaurants = process_restaurants(urls, client)
    save_to_csv(restaurants, OUTPUT_FILE)


if __name__ == "__main__":
    main()
