"""Unit tests for leviathan.ingestion.weather.nasa_power."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from leviathan.ingestion.weather.nasa_power import fetch_nasa_power_daily

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

_BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
_DEFAULT_KWARGS: dict = dict(
    base_url=_BASE_URL,
    latitude=7.5,
    longitude=-1.2,
    start_date="20200101",
    end_date="20200103",
    parameters=["T2M", "PRECTOTCORR"],
)


class TestFetchNasaPowerDaily:
    def test_returns_payload_on_success(self):
        payload = json.loads((_FIXTURES_DIR / "nasa_power_payload.json").read_text())

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = payload

        with patch(
            "leviathan.ingestion.weather.nasa_power.requests.get",
            return_value=mock_response,
        ):
            result = fetch_nasa_power_daily(**_DEFAULT_KWARGS)

        assert result == payload

    def test_raises_for_status_called(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {}

        with patch(
            "leviathan.ingestion.weather.nasa_power.requests.get",
            return_value=mock_response,
        ):
            fetch_nasa_power_daily(**_DEFAULT_KWARGS)

        mock_response.raise_for_status.assert_called_once()

    def test_get_called_with_correct_params(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {}

        with patch(
            "leviathan.ingestion.weather.nasa_power.requests.get",
            return_value=mock_response,
        ) as mock_get:
            fetch_nasa_power_daily(**_DEFAULT_KWARGS)

        args, kwargs = mock_get.call_args
        assert args == (_BASE_URL,)
        assert kwargs["timeout"] == 60
        assert kwargs["params"] == {
            "parameters": "T2M,PRECTOTCORR",
            "community": "AG",
            "longitude": -1.2,
            "latitude": 7.5,
            "start": "20200101",
            "end": "20200103",
            "format": "JSON",
        }

    def test_raises_on_persistent_http_error(self):
        """tenacity wraps unhandled errors in RetryError after all attempts."""
        import tenacity

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("503 Server Error")

        with patch(
            "leviathan.ingestion.weather.nasa_power.requests.get",
            return_value=mock_response,
        ):
            with patch("tenacity.nap.time.sleep"):
                with pytest.raises((requests.HTTPError, tenacity.RetryError)):
                    fetch_nasa_power_daily(**_DEFAULT_KWARGS)

        # 3 attempts total (stop_after_attempt(3))
        assert mock_response.raise_for_status.call_count == 3

    def test_retries_exactly_three_times_on_failure(self):
        import tenacity

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.ConnectionError("timeout")

        with patch(
            "leviathan.ingestion.weather.nasa_power.requests.get",
            return_value=mock_response,
        ):
            with patch("tenacity.nap.time.sleep"):
                with pytest.raises((requests.ConnectionError, tenacity.RetryError)):
                    fetch_nasa_power_daily(**_DEFAULT_KWARGS)

        assert mock_response.raise_for_status.call_count == 3
