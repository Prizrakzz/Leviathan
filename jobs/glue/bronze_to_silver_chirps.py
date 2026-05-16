"""Glue Python Shell: bronze → silver CHIRPS.

Reads all bronze Parquet files for a commodity from S3, applies silver
cleaning (melt to long/tidy format), and writes per-partition silver
Parquet files.  Skips existing partitions unless --force_overwrite is set.

Required args: --commodity, --bucket, --aws_region
Optional args: --force_overwrite (default: false)
"""
from __future__ import annotations

import sys
from typing import Iterable

# ---- Bootstrap: install leviathan package from S3 at runtime ----
import os as _os
import subprocess as _subprocess


def _install_leviathan() -> None:
    import boto3 as _boto3
    import time as _time

    _bucket = next(
        (sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--bucket" and i + 1 < len(sys.argv)),
        None,
    )
    if not _bucket:
        raise RuntimeError("--bucket argument required for leviathan bootstrap")
    _whl = "/tmp/leviathan-0.1.0-py3-none-any.whl"
    for _attempt in range(3):
        try:
            if not _os.path.exists(_whl):
                _boto3.client("s3").download_file(_bucket, "glue-libs/leviathan-0.1.0-py3-none-any.whl", _whl)
            _subprocess.check_call([sys.executable, "-m", "pip", "install", _whl, "--no-deps", "--quiet"])
            return
        except Exception:
            if _attempt == 2:
                raise
            if _os.path.exists(_whl):
                _os.remove(_whl)
            _time.sleep(5 * (_attempt + 1))


try:
    _install_leviathan()
except Exception as _exc:
    print(f"[BOOTSTRAP ERROR] {type(_exc).__name__}: {_exc}", flush=True)
    raise
# ---- End bootstrap ----

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
