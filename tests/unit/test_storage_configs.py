"""Unit tests for leviathan.storage.configs."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import yaml
from botocore.exceptions import ClientError
from leviathan.storage.configs import load_commodity_regions


def _make_s3_client(yaml_content: bytes) -> MagicMock:
    """Return a mock S3Client whose get_object().Body.read() yields *yaml_content*."""
    mock_body = MagicMock()
    mock_body.read.return_value = yaml_content
    mock_client = MagicMock()
    mock_client.get_object.return_value = {"Body": mock_body}
    return mock_client


def _yaml_bytes(regions: list[dict]) -> bytes:
    return yaml.dump({"regions": regions}).encode()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLoadCommodityRegions:
    _SAMPLE_REGIONS = [
        {
            "country": "ghana",
            "locations": [
                {"region": "gh_main", "latitude": 6.5, "longitude": -1.2},
                {"region": "gh_north", "latitude": 9.0, "longitude": -1.0},
            ],
        },
        {
            "country": "ivory_coast",
            "locations": [
                {"region": "ic_abidjan", "latitude": 5.3, "longitude": -4.0},
            ],
        },
    ]

    def test_returns_flat_list_of_region_dicts(self) -> None:
        client = _make_s3_client(_yaml_bytes(self._SAMPLE_REGIONS))
        result = load_commodity_regions(client, "my-bucket", "cocoa")

        assert len(result) == 3
        assert result[0] == {
            "country": "ghana",
            "region": "gh_main",
            "latitude": 6.5,
            "longitude": -1.2,
        }
        assert result[2]["country"] == "ivory_coast"
        assert result[2]["region"] == "ic_abidjan"

    def test_uses_correct_s3_key(self) -> None:
        client = _make_s3_client(_yaml_bytes(self._SAMPLE_REGIONS))
        load_commodity_regions(client, "test-bucket", "corn_cbot")

        client.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="configs/geographies/corn_cbot_regions.yaml",
        )

    def test_single_country_single_location(self) -> None:
        regions = [
            {"country": "brazil", "locations": [{"region": "br_south", "latitude": -25.0, "longitude": -51.0}]}
        ]
        client = _make_s3_client(_yaml_bytes(regions))
        result = load_commodity_regions(client, "bucket", "arabica_coffee")

        assert len(result) == 1
        assert result[0]["country"] == "brazil"

    def test_many_locations_across_countries(self) -> None:
        """Verify that all locations from all country blocks are returned."""
        regions = [
            {
                "country": f"country_{i}",
                "locations": [
                    {"region": f"region_{i}_{j}", "latitude": float(i), "longitude": float(j)}
                    for j in range(5)
                ],
            }
            for i in range(4)
        ]
        client = _make_s3_client(_yaml_bytes(regions))
        result = load_commodity_regions(client, "bucket", "raw_sugar")
        assert len(result) == 20  # 4 countries × 5 locations

    def test_raises_on_s3_client_error(self) -> None:
        """ClientError from S3 propagates to the caller."""
        mock_client = MagicMock()
        mock_client.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
            "GetObject",
        )
        with pytest.raises(ClientError):
            load_commodity_regions(mock_client, "bucket", "missing_commodity")
