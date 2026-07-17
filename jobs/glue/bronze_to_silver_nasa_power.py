"""Glue Python Shell: bronze -> silver NASA POWER (canonical WIDE, SILVER-F021).

Reads all bronze Parquet files for a commodity from S3 with per-file retry, applies the canonical WIDE
silver transform (``nasa_power_bronze_to_silver`` -- one row per date, six measurement columns,
``source_file_name`` retained, NASA sentinels scrubbed), and writes per-partition silver Parquet files
THROUGH the INV-2 pinned pyarrow schema (``NASA_POWER_WIDE_SCHEMA``), never ``df.to_parquet`` inference.

Because silver_nasa_power is WIDE, the shared LONG quality runner (which requires variable/value/
commodity) cannot validate it; ``run()`` is overridden to use the wide-schema quality checker
(``run_wide_weather_quality_checks``) and the SILVER-V002 freshness-aware skip-existing helper
(``select_partitions_to_write``) reused from base_jobs. Skip-existing refreshes any partition whose
bronze is newer than its silver (closes the CHIRPS-class stale-silver hazard).

Required args: --commodity, --bucket, --aws_region
Optional args: --force_overwrite (default: false)
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

from bootstrap import run_bootstrap

run_bootstrap()

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.storage.base_jobs import (
    BaseBronzeToSilverJob,
    filter_keys_by_year,
    select_partitions_to_write,
)
from leviathan.storage.paths import silver_weather_staging_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys_with_mtime,
)
from leviathan.transforms.bronze_to_silver._weather_quality import run_wide_weather_quality_checks
from leviathan.transforms.bronze_to_silver._weather_schema import (
    NASA_POWER_WIDE_SCHEMA,
    to_parquet_bytes,
)
from leviathan.transforms.bronze_to_silver.nasa_power_weather import nasa_power_bronze_to_silver

logger = get_logger("bronze_to_silver_nasa_power")


class NasaPowerBronzeToSilver(BaseBronzeToSilverJob):
    source = "nasa_power"
    staging = True  # month-grain -> _staging tier; compact publishes the canonical [commodity, year]

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return nasa_power_bronze_to_silver(df, source_label=f"{self.source}/{self.commodity}")

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
            "nasa_power", self.commodity, key_dict["country"], key_dict["region"],
            int(key_dict["year"]), int(key_dict["month"]), "part-000.parquet",
        )

    def _write_partition(self, key_dict: dict, part_df: pd.DataFrame) -> str:
        """INV-2 override: serialise through the pinned WIDE arrow schema (drops the path-only
        ``commodity`` column), not pandas inference."""
        silver_key = self._silver_key(key_dict)
        body = to_parquet_bytes(part_df, NASA_POWER_WIDE_SCHEMA)
        get_thread_local_s3_client(self.aws_region).put_object(
            Body=body, Bucket=self.bucket, Key=silver_key
        )
        return silver_key

    def run(self) -> None:
        """WIDE-aware bronze->silver run: reuses the base read/freshness helpers but swaps the LONG
        quality gate for the wide-schema one (the shared runner would false-fail on the wide shape)."""
        bronze_objects = list_s3_keys_with_mtime(
            self.bucket, self.bronze_prefix(), suffix=".parquet", aws_region=self.aws_region
        )
        bronze_keys = sorted(bronze_objects)
        if self.year_window is not None:
            bronze_keys = filter_keys_by_year(bronze_keys, self.year_window)
        self._bronze_max_mtime = (
            max((bronze_objects[k] for k in bronze_keys), default=None) if bronze_keys else None
        )
        if not bronze_keys:
            logger.warning("No bronze for commodity=%s source=%s year_window=%s -- nothing to do.",
                           self.commodity, self.source, self.year_window)
            return

        frames: list[pd.DataFrame] = []
        read_failed = 0
        with ThreadPoolExecutor(max_workers=self._MAX_WORKERS) as pool:
            futures = {pool.submit(self._read_one, k): k for k in bronze_keys}
            for future in as_completed(futures):
                result, info = future.result()
                if result is not None:
                    frames.append(result)
                else:
                    read_failed += 1
                    logger.error("Failed to read bronze file: %s", info)
        if not frames:
            raise RuntimeError(f"All {len(bronze_keys)} bronze files failed to read.")

        df = pd.concat(frames, ignore_index=True)
        silver_df = self.transform(df)
        logger.info("WIDE silver transform produced %d rows", len(silver_df))
        if silver_df.empty:
            logger.warning("Silver transform returned empty DataFrame -- nothing to write.")
            return

        report = run_wide_weather_quality_checks(silver_df, self.commodity, self.source)
        if not report["passed"]:
            raise RuntimeError(
                f"WIDE silver quality checks failed for {self.source}/{self.commodity}: "
                f"{report['hard_failures']}"
            )

        partitions = list(self.get_partitions(silver_df))
        if not self.force_overwrite:
            existing = list_s3_keys_with_mtime(
                self.bucket, self.silver_prefix(), suffix=".parquet", aws_region=self.aws_region
            )
            partitions, skipped_fresh, stale_refreshed = select_partitions_to_write(
                partitions, existing, self._bronze_max_mtime, self._silver_key
            )
            logger.info("Skipping %d fresh; writing %d (%d new + %d stale-refresh; SILVER-V002).",
                        skipped_fresh, len(partitions), len(partitions) - len(stale_refreshed),
                        len(stale_refreshed))
        if not partitions:
            logger.info("All silver partitions already exist -- nothing to write.")
            return

        write_success = write_failed = 0
        with ThreadPoolExecutor(max_workers=self._MAX_WORKERS) as pool:
            fut_w = {pool.submit(self._write_partition, kd, pdf): kd for kd, pdf in partitions}
            for f in as_completed(fut_w):
                try:
                    f.result()
                    write_success += 1
                except Exception as exc:  # noqa: BLE001
                    write_failed += 1
                    logger.error("Partition write failed: %s", exc)
        logger.info("bronze->silver nasa_power complete. written=%d failed=%d",
                    write_success, write_failed)
        if read_failed or write_failed:
            raise RuntimeError(f"nasa_power b2s: {read_failed} read / {write_failed} write failures.")


# Thin-contract entry (A-Wave-3): --commodity all (default) iterates every commodity discovered under
# the nasa_power bronze prefix, self-windowed to the current year; a named --commodity in the Glue
# DefaultArguments preserves the single-commodity backfill (all years). Glue delivers job args in
# sys.argv, so the raw-argv thin-contract runner needs no getResolvedOptions here.
NasaPowerBronzeToSilver.run_thin_contract()
