from __future__ import annotations

from typing import cast

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from leviathan.common.logging import get_logger
from leviathan.common.types import NasaPowerPayload


logger = get_logger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
)
def fetch_nasa_power_daily(
    base_url: str,
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    parameters: list[str],
    community: str = "AG",
    output_format: str = "JSON",
) -> NasaPowerPayload:
    """start_date and end_date must be in YYYYMMDD format."""

    query_params = {
        "parameters": ",".join(parameters),
        "community": community,
        "longitude": longitude,
        "latitude": latitude,
        "start": start_date,
        "end": end_date,
        "format": output_format,
    }

    logger.info(
        "Fetching NASA POWER daily data lat=%s lon=%s start=%s end=%s",
        latitude,
        longitude,
        start_date,
        end_date,
    )

    response = requests.get(base_url, params=query_params, timeout=60)
    response.raise_for_status()

    return cast(NasaPowerPayload, response.json())
