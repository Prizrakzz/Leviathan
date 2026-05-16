"""Glue Python Shell: bronze → silver CHIRPS.

.. deprecated::
   This Glue job is superseded by the AWS Batch Fargate task
   ``jobs/batch/bronze_to_silver_chirps_task.py``.  Keep this file only as a
   Glue fallback reference.

Reads all bronze Parquet files for a commodity from S3, applies silver
cleaning (melt to long/tidy format), and writes per-partition silver
Parquet files.  Skips existing partitions unless --force_overwrite is set.

Required args: --commodity, --bucket, --aws_region
Optional args: --force_overwrite (default: false)
"""
from __future__ import annotations

import sys
from typing import Iterable

_bucket = next(
    (sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--bucket" and i + 1 < len(sys.argv)),
    None,
)
if _bucket is None:
    raise RuntimeError("--bucket argument required for leviathan bootstrap")
try:
    from bootstrap import ensure_leviathan_installed
    ensure_leviathan_installed(_bucket)
except Exception as _exc:
    print(f"[BOOTSTRAP ERROR] {type(_exc).__name__}: {_exc}", flush=True)
    raise

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
