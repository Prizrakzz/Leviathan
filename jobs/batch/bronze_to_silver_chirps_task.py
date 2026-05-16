"""AWS Batch Fargate task: bronze → silver for CHIRPS data.

No bootstrap needed — leviathan is installed in the Docker image.

Required job parameters (overridden at submission via Batch parameters):
  --commodity   e.g. arabica_coffee
  --bucket      S3 bucket name
  --aws_region  e.g. us-east-1

Optional:
  --force_overwrite true
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from leviathan.common.base_jobs import BaseBronzeToSilverJob
from leviathan.transforms.bronze_to_silver.chirps_weather import chirps_bronze_to_silver


class ChirpsBronzeToSilver(BaseBronzeToSilverJob):
    source = "chirps"

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
        return (
            f"silver/weather/source=chirps/commodity={self.commodity}"
            f"/country={key_dict['country']}/region={key_dict['region']}"
            f"/year={key_dict['year']}/month={key_dict['month']:02d}/part-000.parquet"
        )


ChirpsBronzeToSilver().run()
