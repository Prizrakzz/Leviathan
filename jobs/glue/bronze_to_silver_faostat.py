"""Glue Python Shell: bronze → silver FAOSTAT.

Reads all bronze Parquet files for a commodity from S3 with per-file retry
(eliminates pyarrow thundering-herd), applies the silver transform (long/tidy
format: variable + value), and writes per-year silver Parquet files to S3.

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

    _bucket = next(
        (sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--bucket" and i + 1 < len(sys.argv)),
        None,
    )
    if not _bucket:
        raise RuntimeError("--bucket argument required for leviathan bootstrap")
    _whl = "/tmp/leviathan-0.1.0-py3-none-any.whl"
    if not _os.path.exists(_whl):
        _boto3.client("s3").download_file(_bucket, "glue-libs/leviathan-0.1.0-py3-none-any.whl", _whl)
    _subprocess.check_call([sys.executable, "-m", "pip", "install", _whl, "--no-deps", "--quiet"])


try:
    _install_leviathan()
except Exception as _exc:
    print(f"[BOOTSTRAP ERROR] {type(_exc).__name__}: {_exc}", flush=True)
    raise
# ---- End bootstrap ----

import pandas as pd

from leviathan.common.base_jobs import BaseBronzeToSilverJob
from leviathan.transforms.bronze_to_silver.faostat_production import transform_faostat_production_silver_df


class FaostatBronzeToSilver(BaseBronzeToSilverJob):
    source = "faostat"

    def bronze_prefix(self) -> str:
        return f"bronze/production/source=faostat/dataset=QCL/commodity={self.commodity}/"

    def silver_prefix(self) -> str:
        return f"silver/production/source=faostat/commodity={self.commodity}/"

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        year_frames = transform_faostat_production_silver_df(df, commodity=self.commodity)
        if not year_frames:
            return pd.DataFrame()
        return pd.concat([ydf for _, ydf in year_frames], ignore_index=True)

    def get_partitions(self, df: pd.DataFrame) -> Iterable[tuple[dict, pd.DataFrame]]:
        for year, group in df.groupby("year"):
            yield {"year": int(year)}, group.reset_index(drop=True)

    def _silver_key(self, key_dict: dict) -> str:
        return (
            f"silver/production/source=faostat/commodity={self.commodity}"
            f"/year={key_dict['year']}/part-000.parquet"
        )


FaostatBronzeToSilver().run()
