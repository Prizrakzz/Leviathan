"""S3-backed configuration loaders for the leviathan pipeline."""
from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

from leviathan.common.types import Region


def load_commodity_regions(s3_client: S3Client, bucket: str, commodity: str) -> list[Region]:
    """Load geographic sampling locations for a commodity from S3.

    Reads ``configs/geographies/{commodity}_regions.yaml`` and flattens the
    nested country → locations structure into a list of Region dicts.
    """
    key = f"configs/geographies/{commodity}_regions.yaml"
    body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    config = yaml.safe_load(body)
    locations: list[Region] = []
    for region_block in config["regions"]:
        country = region_block["country"]
        for loc in region_block["locations"]:
            locations.append({
                "country":   country,
                "region":    loc["region"],
                "latitude":  loc["latitude"],
                "longitude": loc["longitude"],
            })
    return locations
