"""Glue Python Shell: bronze -> canonical silver_production (FAOSTAT). SILVER-F022.

Reads all bronze Parquet for a commodity, applies the 12-column canonical silver transform, and
writes one silver Parquet per year to the CANONICAL projected layout
``silver/production/commodity=<c>/year=<y>/part-000.parquet`` -- NOT the legacy
``silver/production/source=faostat/`` prefix (which the projection does not resolve).

Every write:
  * carries only the 12 canonical physical columns (commodity/year are path partition keys);
  * is cast to the INV-2 arrow writer schema from the SILVER-F010 registry contract before upload;
  * passes the ``assert_canonical_production_key`` layout guard (a ``source=faostat`` key is refused).

Required args: --commodity, --bucket, --aws_region.  Optional: --force_overwrite (default: false).
"""
from __future__ import annotations

import io
from typing import Iterable

from bootstrap import run_bootstrap

run_bootstrap()

import pandas as pd

from leviathan.silver.flat_producer import encode_parquet
from leviathan.silver.registry import load_registry
from leviathan.storage.base_jobs import BaseBronzeToSilverJob
from leviathan.storage.paths import silver_production_key
from leviathan.storage.s3 import get_thread_local_s3_client
from leviathan.transforms.bronze_to_silver.faostat_production import (
    CANONICAL_PHYSICAL_COLUMNS,
    assert_canonical_production_key,
    transform_faostat_production_silver_df,
)

_TABLE = "silver_production"


class FaostatBronzeToSilver(BaseBronzeToSilverJob):
    source = "faostat"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._contract = load_registry().table(_TABLE)

    def bronze_prefix(self) -> str:
        return f"bronze/production/source=faostat/dataset=QCL/commodity={self.commodity}/"

    def silver_prefix(self) -> str:
        # canonical projected layout -- NO source=faostat segment (SILVER-F022).
        return f"silver/production/commodity={self.commodity}/"

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        year_frames = transform_faostat_production_silver_df(df, commodity=self.commodity)
        if not year_frames:
            return pd.DataFrame()
        parts = []
        for year, body in year_frames:
            b = body.copy()
            b["year"] = year                 # routing helper columns (NOT written to the body)
            b["commodity"] = self.commodity
            parts.append(b)
        return pd.concat(parts, ignore_index=True)

    def get_partitions(self, df: pd.DataFrame) -> Iterable[tuple[dict, pd.DataFrame]]:
        for (commodity, year), group in df.groupby(["commodity", "year"]):
            yield {"commodity": str(commodity), "year": int(year)}, group.reset_index(drop=True)

    def _silver_key(self, key_dict: dict) -> str:
        key = silver_production_key(key_dict["commodity"], key_dict["year"], "part-000.parquet")
        return assert_canonical_production_key(key)

    def _write_partition(self, key_dict: dict, part_df: pd.DataFrame) -> str:
        # INV-2: encode the body under the exact registry arrow writer schema (12 canonical columns;
        # commodity/year routing helpers dropped) via the shared SILVER-F015/F062 flat encoder.
        silver_key = self._silver_key(key_dict)
        body = part_df[CANONICAL_PHYSICAL_COLUMNS].reset_index(drop=True)
        get_thread_local_s3_client(self.aws_region).put_object(
            Body=encode_parquet(body, self._contract), Bucket=self.bucket, Key=silver_key
        )
        return silver_key


FaostatBronzeToSilver().run()
