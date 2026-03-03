# ruff: noqa: PLR2004
from pathlib import Path

import cloudscraper
import pytest

from src.main import BASE_URL, Address, Restaurant, extract_schema_data, get_restaurant_links, process_restaurants, save_to_csv

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


class TestFileSystem:
    """Test behavior of csv data export."""

    def test_save_to_csv(self, tmp_path: Path) -> None:
        output_file = tmp_path / "test_restaurants.csv"
        restaurants = [
            Restaurant(name="Place A", street_address="123 St", telephone="111", url="url1"),
            Restaurant(name="Place B", street_address="456 St", telephone="222", url="url2"),
        ]

        save_to_csv(restaurants, output_file)

        assert output_file.exists()
        content = output_file.read_text()
        assert "Place A" in content
        assert "Place B" in content
        assert "street_address" in content

    def test_save_to_csv_no_results(self, tmp_path: Path) -> None:
        output_file = tmp_path / "test_restaurants.csv"

        save_to_csv([], output_file)

        assert not output_file.exists()
