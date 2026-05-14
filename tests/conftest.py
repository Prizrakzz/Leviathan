"""Shared pytest fixtures for the Leviathan unit test suite."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def nasa_power_payload() -> dict:
    """Minimal valid NASA POWER API payload with all 7 required parameters × 3 dates."""
    return json.loads((FIXTURES_DIR / "nasa_power_payload.json").read_text())


@pytest.fixture()
def faostat_bronze_df() -> pd.DataFrame:
    """Bronze FAOSTAT DataFrame as produced by transform_faostat_qcl_zip_to_bronze().

    Represents cocoa production data for Ghana, 2020, with all three FAO elements.
    """
    return pd.DataFrame(
        {
            "area": ["Ghana", "Ghana", "Ghana"],
            "item": ["Cocoa beans", "Cocoa beans", "Cocoa beans"],
            "element": ["Production", "Area harvested", "Yield"],
            "year": [2020, 2020, 2020],
            "unit": ["tonnes", "ha", "hg/ha"],
            "value": [900_000.0, 1_800_000.0, 5_000.0],
            "flag": ["A", "A", ""],
            "ingest_date": ["2024-01-01", "2024-01-01", "2024-01-01"],
        }
    )


@pytest.fixture()
def weather_bronze_wide_df() -> pd.DataFrame:
    """Bronze NASA POWER DataFrame as produced by nasa_power_payload_to_daily_dataframe().

    Wide format with lowercased raw parameter names, 3 rows.
    """
    return pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "year": [2020, 2020, 2020],
            "month": [1, 1, 1],
            "day": [1, 2, 3],
            "source": ["nasa_power", "nasa_power", "nasa_power"],
            "commodity": ["cocoa", "cocoa", "cocoa"],
            "country": ["ghana", "ghana", "ghana"],
            "region": ["gh_main", "gh_main", "gh_main"],
            "ingest_date": ["2024-01-01", "2024-01-01", "2024-01-01"],
            "source_file_name": ["sample.json", "sample.json", "sample.json"],
            "t2m": [25.5, 26.1, 24.8],
            "t2m_max": [30.2, 31.0, 29.5],
            "t2m_min": [20.1, 21.3, 19.8],
            "prectotcorr": [2.5, 0.0, 1.1],
            "rh2m": [75.0, 72.0, 78.0],
            "ws2m": [2.1, 1.8, 2.5],
            "allsky_sfc_sw_dwn": [18.5, 20.1, 15.3],
        }
    )
