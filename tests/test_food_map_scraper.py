from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.main import BASE_URL, Address, Restaurant, extract_schema_data, get_restaurant_links, save_to_csv

FOOD_MAP_URL_BASE = "https://www.portlandfoodmap.com/restaurants"


class TestDataModels:
    @pytest.mark.parametrize(
        ("address_str", "results"),
        [
            ("263 Saint John Street, Portland, ME, USA", ["263 Saint John Street", "Portland", "ME", "USA"]),
            ("263 Saint John Street, Portland, ME USA", ["263 Saint John Street", "Portland", "ME", "USA"]),
            ("263 Saint John Street, Portland, ME", ["263 Saint John Street", "Portland", "ME", ""]),
        ],
        ids=["Portland, ME, USA", "Portland, ME USA", "Portland, ME"],
    )
    def test_address_parsing(self, address_str: str, results: list[str]) -> None:
        addr = Address.from_text(address_str)

        assert addr.street_address == results[0]
        assert addr.city == results[1]
        assert addr.state == results[2]
        assert addr.country == results[3]

    def test_address_from_schema_dict(self) -> None:
        schema_addr = {"streetAddress": "123 Main St", "addressLocality": "Portland", "addressRegion": "ME", "postalCode": "04101", "addressCountry": "USA"}
        addr = Address.from_schema(schema_addr)

        assert addr.street_address == "123 Main St"
        assert addr.city == "Portland"
        assert addr.state == "ME"
        assert addr.postal_code == "04101"
        assert addr.country == "USA"

    def test_restaurant_from_schema(self) -> None:
        schema = {
            "name": "Scheme Milk Dairy Bar",
            "telephone": "207-555-0123",
            "url": "https://scheme-milk-dairy-bar.com",
            "address": Address(street_address="123 Main St"),
        }
        res = Restaurant.from_schema(schema)

        assert res.name == "Scheme Milk Dairy Bar"
        assert res.telephone == "207-555-0123"
        assert res.url == "https://scheme-milk-dairy-bar.com"
        assert res.street_address == "123 Main St"

    def test_restaurant_from_schema_with_dict_address(self) -> None:
        schema = {"name": "The Great Dict Tater", "address": {"streetAddress": "456 Dictionary Ave"}}
        res = Restaurant.from_schema(schema)

        assert res.name == "The Great Dict Tater"
        assert res.street_address == "456 Dictionary Ave"


@pytest.mark.vcr
class TestScraperNetwork:
    def test_get_restaurant_links(self) -> None:
        links = get_restaurant_links(BASE_URL)

        assert isinstance(links, list)
        assert len(links) > 0
        assert all(f"{FOOD_MAP_URL_BASE}/" in link for link in links[:5])

    @patch("src.main.fetch_url")
    def test_get_restaurant_links_no_data(self, mock_fetch: MagicMock) -> None:
        """Test the 'if not data' branch by forcing fetch_url to return None."""
        mock_fetch.return_value = None
        links = get_restaurant_links("https://any-url.com")

        assert links == []
        mock_fetch.assert_called_once()

    def test_extract_schema_data_success(self) -> None:
        test_url = f"{FOOD_MAP_URL_BASE}/central-provisions/"
        data = extract_schema_data(test_url)

        assert data is not None
        assert "@type" in data
        assert "name" in data
        assert isinstance(data["address"], Address)

    def test_extract_schema_data_invalid_url(self) -> None:
        data = extract_schema_data(f"{FOOD_MAP_URL_BASE}/non-existent-place/")

        assert data is None


class TestFileSystem:
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
