"""Base classes for Leviathan raw→bronze and bronze→silver Glue Python Shell jobs.

Lives in src/leviathan/common/ (an existing package) — no new subpackage required.
Both base classes are installed via the leviathan wheel and imported inside Glue
scripts after the bootstrap step that pip-installs the wheel from S3.

Usage pattern
-------------
    class MysourceBronzeToSilver(BaseBronzeToSilverJob):
        source = "mysource"

        def bronze_prefix(self) -> str: ...   # override if non-weather path
        def silver_prefix(self) -> str: ...
        def transform(self, df: pd.DataFrame) -> pd.DataFrame: ...
        def get_partitions(self, df): ...
        def _silver_key(self, key_dict: dict) -> str: ...

    MysourceBronzeToSilver().run()
"""
from __future__ import annotations

import io
import sys
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import ClassVar, Iterable

import yaml
import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.common.types import ProcessResult
from leviathan.storage.dead_letter import write_dead_letter
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)

logger = get_logger(__name__)

# awsglue is only available inside AWS Glue Python Shell; guard the import so
# the wheel remains importable locally (tests, notebooks, etc.).
try:
    from awsglue.utils import getResolvedOptions as _glue_get_opts  # type: ignore[import]
    _HAS_GLUE = True
except ImportError:
    _HAS_GLUE = False
    _glue_get_opts = None  # type: ignore[assignment]


class _BaseGlueJob:
    """Shared arg-parsing helpers inherited by both base job classes."""

    required_glue_args: ClassVar[list[str]] = ["commodity", "bucket", "aws_region"]

    def _parse_args(self) -> dict[str, str]:
        if _HAS_GLUE and _glue_get_opts is not None:
            return _glue_get_opts(sys.argv, self.required_glue_args)
        # Fallback: manual parse for local runs / unit tests
        result: dict[str, str] = {}
        for arg in self.required_glue_args:
            idx = next((i for i, a in enumerate(sys.argv) if a == f"--{arg}"), None)
            if idx is not None and idx + 1 < len(sys.argv):
                result[arg] = sys.argv[idx + 1]
            else:
                raise RuntimeError(f"Missing required argument: --{arg}")
        return result

    def _parse_optional_str(self, name: str, default: str = "") -> str:
        idx = next((i for i, a in enumerate(sys.argv) if a == f"--{name}"), None)
        return sys.argv[idx + 1] if idx is not None and idx + 1 < len(sys.argv) else default

    def _parse_optional_bool(self, name: str) -> bool:
        idx = next((i for i, a in enumerate(sys.argv) if a == f"--{name}"), None)
        return (
            idx is not None
            and idx + 1 < len(sys.argv)
            and sys.argv[idx + 1].lower() == "true"
        )


# ---------------------------------------------------------------------------
# BaseRawToBronzeJob
# ---------------------------------------------------------------------------

class BaseRawToBronzeJob(_BaseGlueJob, ABC):
    """Base for raw→bronze jobs that process many S3 files concurrently.

    Subclass responsibilities
    -------------------------
    - Set ``source`` class variable (e.g. ``source = "nasa_power"``).
    - Implement ``bronze_key(raw_key)`` — maps a raw S3 key to the target bronze key.
    - Implement ``transform(raw_bytes, raw_key)`` — converts raw bytes to a DataFrame.
    - Optionally override ``validate_raw(raw_bytes, raw_key)`` for schema checks.
    - Optionally override ``raw_prefix()``, ``bronze_prefix()``, ``raw_suffix()``.

    The base ``run()`` handles: arg parsing, S3 listing, skip-existing check,
    ThreadPoolExecutor (64 workers), per-file retry via ``s3_download_with_retry``,
    dead-lettering on exhausted retries, and final raise on any failures.
    """

    source: ClassVar[str]
    _MAX_WORKERS: ClassVar[int] = 64

    def __init__(self) -> None:
        self.args = self._parse_args()
        self.commodity: str = self.args["commodity"]
        self.bucket: str = self.args["bucket"]
        self.aws_region: str = self.args["aws_region"]
        self.force_overwrite: bool = self._parse_optional_bool("force_overwrite")

    # ------------------------------------------------------------------
    # Path helpers — override in subclass for non-weather sources
    # ------------------------------------------------------------------

    def raw_prefix(self) -> str:
        return f"raw/weather/source={self.source}/commodity={self.commodity}/"

    def bronze_prefix(self) -> str:
        return f"bronze/weather/source={self.source}/commodity={self.commodity}/"

    def raw_suffix(self) -> str:
        return ".json"

    # ------------------------------------------------------------------
    # Optional validation hook
    # ------------------------------------------------------------------

    def validate_raw(self, raw_bytes: bytes, raw_key: str) -> None:
        """Schema validation hook. Default: no-op. Override to add validation."""

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        raw_keys = list_s3_keys(
            self.bucket, self.raw_prefix(), suffix=self.raw_suffix(), aws_region=self.aws_region
        )
        logger.info(
            "Found %d raw files for commodity=%s source=%s",
            len(raw_keys), self.commodity, self.source,
        )

        if self.force_overwrite:
            existing_bronze: set[str] = set()
            logger.info("force_overwrite=true — reprocessing all files")
        else:
            existing_bronze = set(
                list_s3_keys(
                    self.bucket, self.bronze_prefix(), suffix=".parquet", aws_region=self.aws_region
                )
            )
            logger.info("%d existing bronze files will be skipped", len(existing_bronze))

        success = skipped = failed = 0

        with ThreadPoolExecutor(max_workers=self._MAX_WORKERS) as pool:
            futures = {
                pool.submit(self._process_one, k, existing_bronze): k for k in raw_keys
            }
            for future in as_completed(futures):
                status, info = future.result()
                if status == "success":
                    success += 1
                elif status == "skipped":
                    skipped += 1
                else:
                    failed += 1
                    logger.error("Failed: %s", info)

        logger.info(
            "raw→bronze %s complete. success=%d  skipped=%d  failed=%d",
            self.source, success, skipped, failed,
        )
        if failed > 0:
            raise RuntimeError(
                f"{failed} files failed during raw→bronze {self.source} (commodity={self.commodity})."
            )

    def _process_one(
        self,
        raw_key: str,
        existing_bronze: set[str],
    ) -> ProcessResult:
        bkey = self.bronze_key(raw_key)
        if bkey in existing_bronze:
            return ("skipped", bkey)

        try:
            s3_client = get_thread_local_s3_client(self.aws_region)
            raw_bytes = s3_download_with_retry(self.bucket, raw_key, s3_client)
            self.validate_raw(raw_bytes, raw_key)
            df = self.transform(raw_bytes, raw_key)

            buf = io.BytesIO()
            df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
            s3_client.put_object(Body=buf.getvalue(), Bucket=self.bucket, Key=bkey)
            return ("success", bkey)

        except Exception as exc:  # noqa: BLE001
            write_dead_letter(
                self.bucket, self.source, self.commodity, raw_key, str(exc), self.aws_region
            )
            return ("failed", f"{raw_key}: {exc}")

    # ------------------------------------------------------------------
    # Abstract methods
    # ------------------------------------------------------------------

    @abstractmethod
    def bronze_key(self, raw_key: str) -> str:
        """Return the bronze S3 key that corresponds to *raw_key*."""

    @abstractmethod
    def transform(self, raw_bytes: bytes, raw_key: str) -> pd.DataFrame:
        """Convert raw bytes into a bronze DataFrame."""


# ---------------------------------------------------------------------------
# BaseBronzeToSilverJob
# ---------------------------------------------------------------------------

class BaseBronzeToSilverJob(_BaseGlueJob, ABC):
    """Base for bronze→silver jobs.

    Key improvement over the original scripts: replaces ``ds.dataset(...).to_table()``
    (which fires all S3 reads simultaneously with no per-file retry — the pyarrow
    thundering-herd problem) with a ThreadPoolExecutor loop where each file is
    downloaded via ``s3_download_with_retry`` and read individually.

    Subclass responsibilities
    -------------------------
    - Set ``source`` class variable.
    - Optionally override ``bronze_prefix()`` and ``silver_prefix()``.
    - Implement ``transform(df)`` — receives full concatenated bronze DataFrame,
      returns cleaned silver DataFrame.
    - Implement ``get_partitions(df)`` — yields ``(key_dict, partition_df)`` tuples.
    - Implement ``_silver_key(key_dict)`` — returns the S3 key for a partition.
    """

    source: ClassVar[str]
    _MAX_WORKERS: ClassVar[int] = 64

    def __init__(self) -> None:
        self.args = self._parse_args()
        self.commodity: str = self.args["commodity"]
        self.bucket: str = self.args["bucket"]
        self.aws_region: str = self.args["aws_region"]
        self.force_overwrite: bool = self._parse_optional_bool("force_overwrite")

    # ------------------------------------------------------------------
    # Path helpers — override in subclass for non-weather sources
    # ------------------------------------------------------------------

    def bronze_prefix(self) -> str:
        return f"bronze/weather/source={self.source}/commodity={self.commodity}/"

    def silver_prefix(self) -> str:
        return f"silver/weather/source={self.source}/commodity={self.commodity}/"

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        # 1. List bronze files
        bronze_keys = list_s3_keys(
            self.bucket, self.bronze_prefix(), suffix=".parquet", aws_region=self.aws_region
        )
        logger.info(
            "Found %d bronze files for commodity=%s source=%s",
            len(bronze_keys), self.commodity, self.source,
        )

        if not bronze_keys:
            logger.warning(
                "No bronze files found for commodity=%s source=%s — nothing to do.",
                self.commodity, self.source,
            )
            return

        # 2. Per-file read with retry (replaces ds.dataset(...).to_table() thundering herd)
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
            raise RuntimeError(
                f"All {len(bronze_keys)} bronze files failed to read for "
                f"{self.source}/{self.commodity}."
            )

        df = pd.concat(frames, ignore_index=True)
        logger.info(
            "Loaded %d rows from %d/%d bronze files",
            len(df), len(frames), len(bronze_keys),
        )

        # 3. Apply silver transform
        silver_df = self.transform(df)
        logger.info("Silver transform produced %d rows", len(silver_df))

        if silver_df.empty:
            logger.warning("Silver transform returned empty DataFrame — nothing to write.")
            return

        # 4. Silver quality checks + report
        from leviathan.common.quality import (  # noqa: PLC0415
            run_silver_quality_checks,
            write_quality_report_to_s3,
        )

        expected_countries = self._load_expected_countries()
        quality_report = run_silver_quality_checks(
            silver_df, self.commodity, self.source, expected_countries
        )
        write_quality_report_to_s3(
            quality_report, self.bucket, self.source, self.commodity, self.aws_region
        )
        if not quality_report["passed"]:
            failures = quality_report.get("hard_failures", {})
            raise RuntimeError(
                f"Silver quality checks failed for {self.source}/{self.commodity}: {failures}"
            )

        # 5. Get partitions + skip-existing check
        partitions = list(self.get_partitions(silver_df))
        logger.info("Total silver partitions: %d", len(partitions))

        if not self.force_overwrite:
            existing = set(
                list_s3_keys(
                    self.bucket, self.silver_prefix(), suffix=".parquet", aws_region=self.aws_region
                )
            )
            before = len(partitions)
            partitions = [
                (kd, pdf) for kd, pdf in partitions
                if self._silver_key(kd) not in existing
            ]
            logger.info(
                "Skipping %d existing silver partitions. Writing %d new.",
                before - len(partitions), len(partitions),
            )

        if not partitions:
            logger.info("All silver partitions already exist — nothing to write.")
            return

        # 6. Write partitions concurrently
        write_success = write_failed = 0
        with ThreadPoolExecutor(max_workers=self._MAX_WORKERS) as pool:
            futures_w = {
                pool.submit(self._write_partition, kd, pdf): kd for kd, pdf in partitions
            }
            for future in as_completed(futures_w):
                try:
                    future.result()
                    write_success += 1
                except Exception as exc:  # noqa: BLE001
                    write_failed += 1
                    logger.error("Partition write failed: %s", exc)

        logger.info(
            "bronze→silver %s complete. written=%d  failed=%d",
            self.source, write_success, write_failed,
        )
        if read_failed > 0 or write_failed > 0:
            raise RuntimeError(
                f"bronze→silver {self.source} (commodity={self.commodity}): "
                f"{read_failed} read failures, {write_failed} write failures."
            )

    def validate_bronze(self, df: pd.DataFrame, bronze_key: str) -> None:
        """Bronze validation hook called for each bronze file before transform.

        Default: attempts to load ``{source}_bronze`` or ``{source}`` schema
        and runs :func:`~leviathan.common.validation.validate_bronze_df`.
        Override in subclass to customise or disable.
        """
        from leviathan.common.validation import (  # noqa: PLC0415
            SchemaValidationError,
            load_schema,
            validate_bronze_df,
        )

        schema = None
        for candidate in (f"{self.source}_bronze", self.source):
            try:
                candidate_schema = load_schema(candidate)
                if "required_columns" in candidate_schema:
                    schema = candidate_schema
                    break
            except SchemaValidationError:
                continue

        if schema is None:
            return

        validate_bronze_df(df, schema, source=self.source, context=bronze_key)

    def _load_expected_countries(self) -> list[str]:
        """Load expected country keys from the geography config for this commodity.

        Returns an empty list if no geography config is found (e.g. FAOSTAT
        without a region-level config).
        """
        try:
            key = f"configs/geographies/{self.commodity}_regions.yaml"
            s3_client = get_thread_local_s3_client(self.aws_region)
            body = s3_client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            config = yaml.safe_load(body)
            return [r["country"] for r in config.get("regions", [])]
        except Exception:  # noqa: BLE001
            return []

    def _read_one(self, key: str) -> tuple[pd.DataFrame | None, str]:
        try:
            import pyarrow.parquet as pq  # noqa: PLC0415

            s3_client = get_thread_local_s3_client(self.aws_region)
            data = s3_download_with_retry(self.bucket, key, s3_client)
            df = pq.read_table(io.BytesIO(data)).to_pandas()
            self.validate_bronze(df, key)
            return (df, key)
        except Exception as exc:  # noqa: BLE001
            write_dead_letter(
                self.bucket, self.source, self.commodity, key, str(exc), self.aws_region
            )
            return (None, f"{key}: {exc}")

    def _write_partition(self, key_dict: dict, part_df: pd.DataFrame) -> str:
        silver_key = self._silver_key(key_dict)
        buf = io.BytesIO()
        part_df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        get_thread_local_s3_client(self.aws_region).put_object(
            Body=buf.getvalue(), Bucket=self.bucket, Key=silver_key
        )
        return silver_key

    # ------------------------------------------------------------------
    # Abstract methods
    # ------------------------------------------------------------------

    @abstractmethod
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply silver cleaning to the full concatenated bronze DataFrame."""

    @abstractmethod
    def get_partitions(self, df: pd.DataFrame) -> Iterable[tuple[dict, pd.DataFrame]]:
        """Yield (key_dict, partition_df) pairs for every silver partition."""

    @abstractmethod
    def _silver_key(self, key_dict: dict) -> str:
        """Return the S3 key for the silver partition described by *key_dict*."""
