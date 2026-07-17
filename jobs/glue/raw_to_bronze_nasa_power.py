"""Glue Python Shell: raw → bronze NASA POWER.

Downloads raw JSON files from S3, parses the NASA POWER payload into daily rows,
and writes bronze Parquet files. Processes files concurrently using a thread pool.
Skips files that already have a bronze counterpart unless --force_overwrite is set.

Required args: --commodity, --bucket, --aws_region
Optional args: --ingest_date (default: today), --force_overwrite (default: false)
"""
from __future__ import annotations

import json
from datetime import date

from bootstrap import run_bootstrap

run_bootstrap()

import pandas as pd

from leviathan.common.validation import load_schema, validate_raw_json
from leviathan.storage.base_jobs import BaseRawToBronzeJob
from leviathan.storage.paths import bronze_weather_key, parse_hive_key
from leviathan.transforms.raw_to_bronze.nasa_power import nasa_power_payload_to_daily_dataframe


class NasaPowerRawToBronze(BaseRawToBronzeJob):
    source = "nasa_power"

    def __init__(self) -> None:
        super().__init__()
        self.ingest_date: str = self._parse_optional_str("ingest_date", default=date.today().isoformat())
        self._schema = load_schema(self.source)  # load once; validate_raw is called in the thread pool

    def bronze_key(self, raw_key: str) -> str:
        country = parse_hive_key(raw_key, "country")
        region = parse_hive_key(raw_key, "region")
        year = int(parse_hive_key(raw_key, "year"))
        month = int(parse_hive_key(raw_key, "month"))
        filename = raw_key.rsplit("/", 1)[-1].replace(".json", ".parquet")
        return bronze_weather_key("nasa_power", self.commodity, country, region, year, month, filename)

    def transform(self, raw_bytes: bytes, raw_key: str) -> pd.DataFrame:
        payload = json.loads(raw_bytes)
        country = parse_hive_key(raw_key, "country")
        region = parse_hive_key(raw_key, "region")
        return nasa_power_payload_to_daily_dataframe(
            payload=payload,
            source_file_name=raw_key.rsplit("/", 1)[-1],
            commodity=self.commodity,
            country=country,
            region=region,
            ingest_date=self.ingest_date,
        )

    def validate_raw(self, raw_bytes: bytes, raw_key: str) -> None:
        validate_raw_json(json.loads(raw_bytes), self._schema, context=raw_key)


# Thin-contract entry (A-Wave-3): --commodity all (default) iterates every commodity discovered under
# the nasa_power raw prefix, self-windowed to the current year; a named --commodity in the Glue
# DefaultArguments preserves the single-commodity backfill (all years). Glue delivers job args in
# sys.argv, so the raw-argv thin-contract runner needs no getResolvedOptions here.
NasaPowerRawToBronze.run_thin_contract()
