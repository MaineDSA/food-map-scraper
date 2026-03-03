# ruff: noqa: PLR2004

import cloudscraper
import pytest

from src.main import BASE_URL, Address, extract_schema_data, get_restaurant_links, process_restaurants

FOOD_MAP_URL_BASE = "https://www.portlandfoodmap.com/restaurants"


@pytest.fixture
def vcr_scraper() -> cloudscraper.CloudScraper:
    """Provide a real scraper instance for VCR to intercept."""
    return cloudscraper.create_scraper(browser={"browser": "firefox", "platform": "windows", "mobile": False})


@pytest.mark.vcr
class TestScraperNetwork:
    """Integration tests using recorded network interactions."""

    def test_get_restaurant_links(self, vcr_scraper: cloudscraper.CloudScraper) -> None:
        """Test fetching links using a recorded VCR cassette."""
        links = get_restaurant_links(BASE_URL, vcr_scraper)

        assert isinstance(links, list)
        assert len(links) > 0
        # Verify the format matches our expected marker
        assert any(FOOD_MAP_URL_BASE in link for link in links)

    def test_extract_schema_data_success(self, vcr_scraper: cloudscraper.CloudScraper) -> None:
        """Test extracting specific restaurant data from a recorded page."""
        test_url = f"{FOOD_MAP_URL_BASE}/central-provisions/"
        data = extract_schema_data(test_url, vcr_scraper)

        assert data is not None
        assert data["name"] == "Central Provisions"
        assert isinstance(data["address"], Address)
        assert data["address"].street_address == "414 Fore St"

    def test_process_restaurants_integration(self, vcr_scraper: cloudscraper.CloudScraper) -> None:
        """Test the full loop for a small subset of URLs."""
        subset_urls = [f"{FOOD_MAP_URL_BASE}/central-provisions/", f"{FOOD_MAP_URL_BASE}/scales/"]

        # Use delay=0 for faster test execution
        results = process_restaurants(subset_urls, vcr_scraper, delay=0)

        assert len(results) == 2
        assert results[0].name == "Central Provisions"
        assert results[1].name == "Scales"

    def test_extract_schema_data_invalid_url(self, vcr_scraper: cloudscraper.CloudScraper) -> None:
        """Verify behavior when a page is missing or 404s."""
        data = extract_schema_data(f"{FOOD_MAP_URL_BASE}/non-existent-place-12345/", vcr_scraper)
        assert data is None
