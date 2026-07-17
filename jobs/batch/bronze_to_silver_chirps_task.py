"""AWS Batch Fargate task: bronze → silver for CHIRPS data.

No bootstrap needed — leviathan is installed in the Docker image.

Thin-contract invocation (A-Wave-3 weather_daily retrofit)
----------------------------------------------------------
The descriptor invokes this task with NO args; every argument defaults:
  --commodity   e.g. arabica_coffee, or 'all' to iterate every commodity discovered under
                ``bronze/weather/source=chirps/commodity=*/`` and self-window each to the CURRENT
                calendar year (default: all).
  --bucket      S3 bucket name.            DEFAULT: ``$LEVIATHAN_BUCKET``.
  --aws_region  e.g. us-east-1.            DEFAULT: ``$AWS_REGION``.
Single-commodity invocation is the preserved backfill form (``--commodity X --bucket B
--aws_region R``): it processes that commodity across ALL years unchanged.

Optional:
  --force_overwrite true

Layout coherence (SILVER-F047): month-grain silver is written to the ``_staging`` tier
(``silver/weather/source=chirps/_staging/commodity=<c>/...``), OUTSIDE the ``commodity=`` data plane.
compact_weather_silver reads staging UNION canonical and publishes the coarse ``[commodity, year]``
object canonically; keeping month-grain out of ``commodity=`` is what stops the feature extractor +
gold reader from double-reading every weather row.
"""
from __future__ import annotations

import logging
from typing import Iterable

import pandas as pd

from leviathan.storage.base_jobs import BaseBronzeToSilverJob
from leviathan.storage.paths import silver_weather_staging_key
from leviathan.storage.s3 import get_thread_local_s3_client
from leviathan.transforms.bronze_to_silver._weather_schema import (
    CHIRPS_LONG_SCHEMA,
    to_parquet_bytes,
)
from leviathan.transforms.bronze_to_silver.chirps_weather import chirps_bronze_to_silver


class ChirpsBronzeToSilver(BaseBronzeToSilverJob):
    source = "chirps"
    staging = True  # month-grain -> _staging tier; compact publishes the canonical [commodity, year]

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return chirps_bronze_to_silver(df, source_label=f"{self.source}/{self.commodity}")

    def get_partitions(self, df: pd.DataFrame) -> Iterable[tuple[dict, pd.DataFrame]]:
        for (country, region, year, month), group in df.groupby(
            ["country", "region", "year", "month"]
        ):
            yield (
                {"country": country, "region": region, "year": int(year), "month": int(month)},
                group.reset_index(drop=True),
            )

    def _silver_key(self, key_dict: dict) -> str:
        return silver_weather_staging_key(
            "chirps", self.commodity, key_dict["country"], key_dict["region"],
            int(key_dict["year"]), int(key_dict["month"]), "part-000.parquet",
        )

    def _write_partition(self, key_dict: dict, part_df: pd.DataFrame) -> str:
        """INV-2 override: serialise through the pinned LONG arrow schema (no ``string``/``large_string``
        drift). Writes to the ``_staging`` tier (see module docstring); compact_weather_silver merges
        staging + canonical and publishes the coarse registered ``[commodity, year]`` object."""
        silver_key = self._silver_key(key_dict)
        body = to_parquet_bytes(part_df, CHIRPS_LONG_SCHEMA)
        get_thread_local_s3_client(self.aws_region).put_object(
            Body=body, Bucket=self.bucket, Key=silver_key
        )
        return silver_key


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    ChirpsBronzeToSilver.run_thin_contract()


if __name__ == "__main__":
    main()
