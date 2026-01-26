"""
Web scraper for Portland Food Map restaurant data.

This module scrapes restaurant information from portlandfoodmap.com by:
1. Fetching restaurant links from the list view page
2. Extracting schema.org Restaurant structured data from each page
3. Flattening the data and saving to a CSV file
"""

import csv
import json
import logging
from pathlib import Path
from urllib.parse import urljoin

import cloudscraper
import requests
from bs4 import BeautifulSoup, ResultSet
from tqdm import tqdm

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s : food-map-scraper:%(name)s : %(message)s")
logger = logging.getLogger(__name__)

# Constants
HTTP_OK = 200
BASE_URL = "https://www.portlandfoodmap.com/list-view/"
OUTPUT_FILE = Path("portland_restaurants.csv")
RESTAURANT_PATH_MARKER = "/restaurants/"

# Create a cloudscraper instance that handles Cloudflare
scraper = cloudscraper.create_scraper(browser={"browser": "firefox", "platform": "windows", "mobile": False})


def fetch_url(url: str, error_context: str) -> bytes | None:
    """Fetch URL content with unified error handling."""
    try:
        response = scraper.get(url, timeout=15)

        if response.status_code != HTTP_OK:
            logger.error("HTTP %d error for %s: %s", response.status_code, error_context, url)
            return None

        return response.content

    except requests.exceptions.RequestException as e:
        logger.error("%s error for %s (%s): %s", type(e).__name__, error_context, url, e)
        return None


def find_restaurant_schema(schema_scripts: ResultSet) -> dict | None:
    """
    Find Restaurant schema from JSON-LD script tags.

    Searches for @type: "Restaurant" in the schema data, handling both
    single objects and arrays of objects.
    """
    for script in schema_scripts:
        try:
            data = json.loads(script.string)

            # Handle single object
            if isinstance(data, dict) and data.get("@type") == "Restaurant":
                return data

            # Handle array of objects
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Restaurant":
                        return item

        except json.JSONDecodeError:
            continue

    return None


def extract_schema_data(url: str) -> dict | None:
    """Extract Restaurant schema.org data from a restaurant page."""
    data = fetch_url(url, "restaurant page")
    if not data:
        return None

    soup = BeautifulSoup(data, "html.parser")
    schema_scripts = soup.find_all("script", type="application/ld+json")

    return find_restaurant_schema(schema_scripts)


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


def flatten_schema_data(schema: dict) -> dict[str, str]:
    """
    Flatten schema.org Restaurant data into a flat dictionary for CSV.

    Extracts common fields, address components, and geo coordinates.
    """
    flat = {}

    # Map schema.org field names to CSV column names
    simple_fields = {
        "name": "name",
        "description": "description",
        "telephone": "telephone",
        "priceRange": "priceRange",
        "servesCuisine": "cuisine",
        "url": "url",
        "image": "image",
    }

    # Extract simple fields
    for schema_key, csv_key in simple_fields.items():
        if schema_key in schema:
            value = schema[schema_key]
            flat[csv_key] = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)

    # Extract address components
    if (address := schema.get("address")) and isinstance(address, dict):
        address_mapping = {
            "streetAddress": "street_address",
            "addressLocality": "city",
            "addressRegion": "state",
            "postalCode": "postal_code",
            "addressCountry": "country",
        }
        for schema_key, csv_key in address_mapping.items():
            flat[csv_key] = address.get(schema_key, "")

    # Extract geo coordinates
    if (geo := schema.get("geo")) and isinstance(geo, dict):
        flat["latitude"] = geo.get("latitude", "")
        flat["longitude"] = geo.get("longitude", "")

    return flat


def save_to_csv(restaurants: list[dict], output_path: Path) -> None:
    """Save restaurant data to CSV file."""
    # Collect all unique field names
    fieldnames = sorted(set().union(*(r.keys() for r in restaurants)))

    logger.info("Writing %d restaurants to %s...", len(restaurants), output_path)
    with output_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(restaurants)

    logger.info("Done! Data saved to %s", output_path)


def main() -> None:
    """Hey, I just met you, and this is crazy, but I'm the main function, so call me maybe."""
    # Fetch restaurant URLs
    logger.info("Fetching restaurant links...")
    restaurant_urls = get_restaurant_links(BASE_URL)
    logger.info("Found %d restaurant links", len(restaurant_urls))

    if not restaurant_urls:
        logger.warning("No restaurant links found. The page structure may have changed.")
        return

    # Extract data from each restaurant page
    all_restaurants = []
    logger.info("Extracting restaurant data...")

    for url in tqdm(restaurant_urls, unit="restaurants"):
        schema_data = extract_schema_data(url)

        if schema_data:
            flat_data = flatten_schema_data(schema_data)
            flat_data["source_url"] = url
            all_restaurants.append(flat_data)

    if not all_restaurants:
        logger.warning("No restaurant data extracted.")
        return

    # Save results
    save_to_csv(all_restaurants, OUTPUT_FILE)


if __name__ == "__main__":
    main()
