"""Base classes for Leviathan raw→bronze and bronze→silver Glue Python Shell jobs.

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

import pandas as pd
import yaml

from leviathan.common.logging import get_logger
from leviathan.common.types import ProcessResult
from leviathan.storage.dead_letter import write_dead_letter
from leviathan.storage.paths import parse_hive_key, weather_staging_prefix
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    list_s3_keys_with_mtime,
    s3_download_with_retry,
)

logger = get_logger(__name__)


def _extract_cli_opt(argv: list[str], name: str, default: str | None = None) -> str | None:
    """Return the value following ``--name`` in ``argv`` (or ``default`` if absent).

    A raw sys.argv scan that works identically under AWS Batch (plain argv) and Glue Python Shell
    (Glue also delivers ``--key value`` pairs in ``sys.argv``), so the A-Wave-3 thin-contract runner
    needs no ``getResolvedOptions`` dependency and stays unit-testable with an explicit ``argv``.
    Both the space form (``--name value``) and the equals form (``--name=value``) are accepted."""
    flag = f"--{name}"
    eq_prefix = f"{flag}="
    for i, tok in enumerate(argv):
        if tok == flag and i + 1 < len(argv):
            return argv[i + 1]
        if tok.startswith(eq_prefix):
            return tok[len(eq_prefix):]
    return default


def filter_keys_by_year(keys: list[str], year: int | None) -> list[str]:
    """Keep only keys whose ``year=`` Hive segment equals ``year`` (all keys when ``year is None``).

    The daily thin-contract b2s self-windows to the CURRENT calendar year so a scheduled run reads
    only that year's bronze and stages only that year's month-grain (bounded); a named-commodity
    backfill passes ``year_window=None`` and processes every year unchanged."""
    if year is None:
        return list(keys)
    out: list[str] = []
    for k in keys:
        try:
            raw = parse_hive_key(k, "year")
        except (TypeError, ValueError):
            raw = None
        if raw is not None and str(raw) == str(year):
            out.append(k)
    return out


def select_partitions_to_write(
    partitions: list[tuple[dict, "pd.DataFrame"]],
    existing_silver_mtimes: dict,
    bronze_max_mtime,
    silver_key_fn,
) -> tuple[list[tuple[dict, "pd.DataFrame"]], int, list[str]]:
    """SILVER-V002 freshness-aware skip-existing selection.

    Returns ``(to_write, skipped_fresh, stale_refreshed_keys)``.

    A silver partition is written when EITHER its object does not exist yet, OR the
    newest bronze object is newer than the existing silver object (``silver_mtime <
    bronze_max_mtime``). This closes the CHIRPS stale-silver hazard: the previous
    ``base_jobs.py:338-356`` skip-existing declined to refresh a partition whose bronze
    had since been re-ingested (silver 2026-05-16 vs bronze 2026-06-16), silently
    shipping stale silver. An existing silver object at or newer than every bronze
    object is still skipped, so a benign no-op rerun stays a no-op (AV-12).

    This helper is pure (no AWS) so the freshness logic is unit-tested directly.
    """
    to_write: list[tuple[dict, "pd.DataFrame"]] = []
    skipped_fresh = 0
    stale_refreshed: list[str] = []
    for key_dict, part_df in partitions:
        silver_key = silver_key_fn(key_dict)
        if silver_key not in existing_silver_mtimes:
            to_write.append((key_dict, part_df))
            continue
        silver_mtime = existing_silver_mtimes.get(silver_key)
        if (
            bronze_max_mtime is not None
            and silver_mtime is not None
            and silver_mtime < bronze_max_mtime
        ):
            to_write.append((key_dict, part_df))
            stale_refreshed.append(silver_key)
        else:
            skipped_fresh += 1
    return to_write, skipped_fresh, stale_refreshed

# awsglue is only available inside AWS Glue Python Shell; guard the import so
# the wheel remains importable locally (tests, notebooks, etc.).
try:
    from awsglue.utils import getResolvedOptions as _glue_get_opts
    _HAS_GLUE = True
except ImportError:
    _HAS_GLUE = False
    _glue_get_opts = None


class _BaseGlueJob:
    """Shared arg-parsing helpers inherited by both base job classes."""

    required_glue_args: ClassVar[list[str]] = ["commodity", "bucket", "aws_region"]

    def _parse_args(self) -> dict[str, str]:
        if _HAS_GLUE and _glue_get_opts is not None:
            return _glue_get_opts(sys.argv, self.required_glue_args)  # type: ignore[no-any-return]
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
        # Set by run_thin_contract in 'all' mode: restrict the raw listing to this year so the
        # daily chain is incremental; None (every explicit invocation) = all years (backfill).
        self.year_window: int | None = None

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
    # A-Wave-3 thin-contract runner ('all' sentinel + env defaults)
    # ------------------------------------------------------------------

    @classmethod
    def _discover_commodities(cls, bucket: str, aws_region: str) -> list[str]:
        """Distinct commodity slugs present under ``raw/weather/source=<source>/``."""
        keys = list_s3_keys(bucket, f"raw/weather/source={cls.source}/", aws_region=aws_region)
        return sorted({c for c in (parse_hive_key(k, "commodity") for k in keys) if c})

    @classmethod
    def run_thin_contract(cls, argv: list[str] | None = None) -> None:
        """Zero-required-arg entry the weather_daily descriptor invokes (Glue DefaultArguments).

        ``--commodity all`` (the default) iterates every commodity discovered under the source's raw
        prefix and self-windows each to the CURRENT calendar year; a single named ``--commodity`` (the
        preserved backfill invocation) processes that commodity across ALL years. ``--bucket`` /
        ``--aws_region`` default to ``$LEVIATHAN_BUCKET`` / ``$AWS_REGION``. Remaining argv tokens
        (``--ingest_date``, ``--force_overwrite``, Glue system args) pass through to each
        per-commodity run unchanged. One commodity's failure is logged and the loop continues; a
        nonzero exit is raised iff any commodity failed."""
        import datetime as _dt  # noqa: PLC0415
        import sys as _sys  # noqa: PLC0415

        from leviathan.common.config import get_required_env, load_env  # noqa: PLC0415

        load_env()
        args = list(_sys.argv[1:] if argv is None else argv)
        commodity = _extract_cli_opt(args, "commodity", "all") or "all"
        bucket = _extract_cli_opt(args, "bucket") or get_required_env("LEVIATHAN_BUCKET")
        aws_region = _extract_cli_opt(args, "aws_region") or get_required_env("AWS_REGION")

        if commodity.strip().lower() == "all":
            commodities = cls._discover_commodities(bucket, aws_region)
            year_window: int | None = _dt.date.today().year
        else:
            commodities = [c.strip() for c in commodity.split(",") if c.strip()]
            year_window = None  # named-commodity backfill: every year

        # __init__ parses sys.argv directly (getResolvedOptions in Glue takes the LAST occurrence,
        # the local fallback the FIRST), so the consumed opts must be stripped from the passthrough
        # remainder and re-supplied exactly once per commodity.
        def _without(tokens: list[str], names: tuple[str, ...]) -> list[str]:
            out: list[str] = []
            i = 0
            while i < len(tokens):
                tok = tokens[i]
                hit = next((n for n in names if tok == f"--{n}" or tok.startswith(f"--{n}=")), None)
                if hit is None:
                    out.append(tok)
                    i += 1
                elif tok == f"--{hit}" and i + 1 < len(tokens):
                    i += 2
                else:
                    i += 1
            return out

        passthrough = _without(args, ("commodity", "bucket", "aws_region"))
        script = _sys.argv[0] if _sys.argv else cls.source
        logger.info(
            "thin-contract %s raw->bronze: %d commodities, year_window=%s",
            cls.source, len(commodities), year_window,
        )
        failures: list[str] = []
        for c in commodities:
            _sys.argv = [script, "--commodity", c, "--bucket", bucket,
                         "--aws_region", aws_region, *passthrough]
            try:
                job = cls()
                job.year_window = year_window
                job.run()
            except Exception as exc:  # noqa: BLE001 — one commodity's failure must not kill the rest
                logger.error("[%s] %s raw->bronze FAILED: %s: %s", c, cls.source,
                             type(exc).__name__, str(exc)[:300])
                failures.append(c)
        if failures:
            raise SystemExit(1)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        raw_keys = list_s3_keys(
            self.bucket, self.raw_prefix(), suffix=self.raw_suffix(), aws_region=self.aws_region
        )
        if self.year_window is not None:
            raw_keys = filter_keys_by_year(raw_keys, self.year_window)
        logger.info(
            "Found %d raw files for commodity=%s source=%s year_window=%s",
            len(raw_keys), self.commodity, self.source, self.year_window,
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

        except Exception as exc:  # noqa: BLE001 — intentional: dead-letter gateway — per-file failure must not abort the batch run
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

    Each bronze file is downloaded individually via ``s3_download_with_retry`` to
    avoid the pyarrow thundering-herd problem where ``ds.dataset(...).to_table()``
    fires all S3 reads simultaneously with no per-file retry.

    Subclass responsibilities
    -------------------------
    - Set ``source`` class variable.
    - Optionally override ``bronze_prefix()`` and ``silver_prefix()``.
    - Implement ``transform(df)`` — receives full concatenated bronze DataFrame,
      returns cleaned silver DataFrame.
    - Implement ``get_partitions(df)`` — yields ``(key_dict, partition_df)`` tuples.
    - Implement ``_silver_key(key_dict)`` — returns the S3 key for a partition.

    Weather-trio subclasses set ``staging = True`` so their month-grain silver is written to the
    ``silver/weather/source=<s>/_staging/`` tier (OUTSIDE the ``commodity=`` data plane) rather than
    canonical. compact_weather_silver reads staging UNION canonical and publishes the coarse
    ``[commodity, year]`` object canonically; keeping month-grain out of ``commodity=`` is what stops
    the feature extractor + gold reader from double-reading every weather row (retire_projected_weather
    docstring; SILVER-F047). Month-grain must NEVER land under ``commodity=`` in the daily chain.
    """

    source: ClassVar[str]
    _MAX_WORKERS: ClassVar[int] = 64
    # When True, silver writes go to the ``_staging`` tier (weather trio); default keeps the legacy
    # per-source ``commodity=`` canonical location for every other family.
    staging: ClassVar[bool] = False

    def __init__(
        self,
        commodity: str | None = None,
        bucket: str | None = None,
        aws_region: str | None = None,
        force_overwrite: bool | None = None,
        year_window: int | None = None,
    ) -> None:
        # Explicit-params branch (A-Wave-3 thin-contract runner constructs one job per commodity);
        # the no-arg branch preserves the legacy ``Subclass().run()`` sys.argv/getResolvedOptions path.
        if commodity is None:
            self.args = self._parse_args()
            self.commodity: str = self.args["commodity"]
            self.bucket: str = self.args["bucket"]
            self.aws_region: str = self.args["aws_region"]
            self.force_overwrite: bool = self._parse_optional_bool("force_overwrite")
        else:
            self.commodity = commodity
            self.bucket = bucket  # type: ignore[assignment]
            self.aws_region = aws_region  # type: ignore[assignment]
            self.force_overwrite = bool(force_overwrite)
        # None = every year (backfill); an int restricts the bronze read to that calendar year (daily).
        self.year_window: int | None = year_window

    # ------------------------------------------------------------------
    # Path helpers — override in subclass for non-weather sources
    # ------------------------------------------------------------------

    def bronze_prefix(self) -> str:
        return f"bronze/weather/source={self.source}/commodity={self.commodity}/"

    def silver_prefix(self) -> str:
        if self.staging:
            return weather_staging_prefix(self.source, self.commodity)
        return f"silver/weather/source={self.source}/commodity={self.commodity}/"

    # ------------------------------------------------------------------
    # A-Wave-3 thin-contract runner ('all' sentinel + env defaults + staging)
    # ------------------------------------------------------------------

    @classmethod
    def _discover_commodities(cls, bucket: str, aws_region: str) -> list[str]:
        """Distinct commodity slugs present under ``bronze/weather/source=<source>/``."""
        keys = list_s3_keys(bucket, f"bronze/weather/source={cls.source}/",
                            suffix=".parquet", aws_region=aws_region)
        return sorted({c for c in (parse_hive_key(k, "commodity") for k in keys) if c})

    @classmethod
    def run_thin_contract(cls, argv: list[str] | None = None) -> None:
        """Zero-required-arg entry the weather_daily descriptor invokes (bare script path).

        ``--commodity all`` (the default) iterates every commodity discovered under the source's bronze
        prefix and self-windows each to the CURRENT calendar year; a single named ``--commodity`` (the
        preserved backfill invocation) processes that commodity across ALL years. ``--bucket`` /
        ``--aws_region`` default to ``$LEVIATHAN_BUCKET`` / ``$AWS_REGION``. One commodity's failure is
        logged and the loop continues; a nonzero exit is raised iff any commodity failed."""
        import datetime as _dt  # noqa: PLC0415
        import sys as _sys  # noqa: PLC0415

        from leviathan.common.config import get_required_env, load_env  # noqa: PLC0415

        load_env()
        args = list(_sys.argv[1:] if argv is None else argv)
        commodity = _extract_cli_opt(args, "commodity", "all") or "all"
        bucket = _extract_cli_opt(args, "bucket") or get_required_env("LEVIATHAN_BUCKET")
        aws_region = _extract_cli_opt(args, "aws_region") or get_required_env("AWS_REGION")
        force = (_extract_cli_opt(args, "force_overwrite", "false") or "false").lower() == "true"

        if commodity.strip().lower() == "all":
            commodities = cls._discover_commodities(bucket, aws_region)
            year_window: int | None = _dt.date.today().year
        else:
            commodities = [c.strip() for c in commodity.split(",") if c.strip()]
            year_window = None  # named-commodity backfill: every year

        logger.info(
            "thin-contract %s bronze->silver: %d commodities, year_window=%s staging=%s",
            cls.source, len(commodities), year_window, cls.staging,
        )
        failures: list[str] = []
        for c in commodities:
            try:
                cls(commodity=c, bucket=bucket, aws_region=aws_region,
                    force_overwrite=force, year_window=year_window).run()
            except Exception as exc:  # noqa: BLE001 — one commodity's failure must not kill the rest
                logger.error("[%s] %s b2s FAILED: %s: %s", c, cls.source,
                             type(exc).__name__, str(exc)[:300])
                failures.append(c)
        if failures:
            raise SystemExit(1)

    def run_quality_gate(self, silver_df: pd.DataFrame) -> None:
        """Step-4 quality gate, an OVERRIDABLE SEAM (Lane 4, 2026-08-26).

        The DEFAULT body is the legacy generic gate, byte-equivalent to what every armed family
        (the weather chains) has always run: ``run_silver_quality_checks`` over the weather-era
        SILVER_REQUIRED_COLUMNS / SILVER_NATURAL_KEY, report to S3, raise on hard failures.

        WHY THE SEAM EXISTS: that generic gate PREDATES the SILVER-F010 contract system and its
        column/key rosters are weather-shaped (date/month/day/region/variable). The first-ever run
        of the retrofitted FAOSTAT silver leg died on it -- the gate demanded columns the F022
        canonical schema deliberately does not have, counted the M-flag's contract-sanctioned NULL
        values as failures, and keyed dedup on a 3-column subset that made 25,970 of 26k rows read
        as duplicates. A family with an F010 contract overrides this seam and validates against
        THE CONTRACT; families without one keep the legacy gate untouched."""
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

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        # 1. List bronze files (with mtimes for the SILVER-V002 freshness contract).
        bronze_objects = list_s3_keys_with_mtime(
            self.bucket, self.bronze_prefix(), suffix=".parquet", aws_region=self.aws_region
        )
        bronze_keys = sorted(bronze_objects)
        if self.year_window is not None:
            bronze_keys = filter_keys_by_year(bronze_keys, self.year_window)
        self._bronze_max_mtime = (
            max((bronze_objects[k] for k in bronze_keys), default=None) if bronze_keys else None
        )
        logger.info(
            "Found %d bronze files for commodity=%s source=%s (year_window=%s)",
            len(bronze_keys), self.commodity, self.source, self.year_window,
        )

        if not bronze_keys:
            logger.warning(
                "No bronze files found for commodity=%s source=%s — nothing to do.",
                self.commodity, self.source,
            )
            return

        # 2. Per-file read with retry
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

        silver_df = self.transform(df)
        logger.info("Silver transform produced %d rows", len(silver_df))

        if silver_df.empty:
            logger.warning("Silver transform returned empty DataFrame — nothing to write.")
            return

        # 4. Silver quality checks + report (overridable seam -- see run_quality_gate)
        self.run_quality_gate(silver_df)

        # 5. Get partitions + skip-existing check
        partitions = list(self.get_partitions(silver_df))
        logger.info("Total silver partitions: %d", len(partitions))

        if not self.force_overwrite:
            existing_mtimes = list_s3_keys_with_mtime(
                self.bucket, self.silver_prefix(), suffix=".parquet", aws_region=self.aws_region
            )
            before = len(partitions)
            partitions, skipped_fresh, stale_refreshed = select_partitions_to_write(
                partitions,
                existing_mtimes,
                getattr(self, "_bronze_max_mtime", None),
                self._silver_key,
            )
            logger.info(
                "Skipping %d fresh silver partitions. Writing %d (%d new + %d stale-refresh; "
                "SILVER-V002 freshness).",
                skipped_fresh,
                len(partitions),
                len(partitions) - len(stale_refreshed),
                len(stale_refreshed),
            )
            if stale_refreshed:
                logger.warning(
                    "Refreshing %d silver partitions whose bronze is newer (was silently declined "
                    "pre-V002): %s%s",
                    len(stale_refreshed),
                    ", ".join(stale_refreshed[:5]),
                    " ..." if len(stale_refreshed) > 5 else "",
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
            for future_w in as_completed(futures_w):
                try:
                    future_w.result()
                    write_success += 1
                except Exception as exc:  # noqa: BLE001 — any S3 write error is logged; loop continues
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
        except Exception:  # noqa: BLE001 — geography config is optional; missing or inaccessible config skips country validation
            logger.debug(
                "Could not load geography config for %s/%s — country validation skipped",
                self.source, self.commodity,
                exc_info=True,
            )
            return []

    def _read_one(self, key: str) -> tuple[pd.DataFrame | None, str]:
        try:
            import pyarrow.parquet as pq  # noqa: PLC0415

            s3_client = get_thread_local_s3_client(self.aws_region)
            data = s3_download_with_retry(self.bucket, key, s3_client)
            df = pq.read_table(io.BytesIO(data)).to_pandas()
            self.validate_bronze(df, key)
            return (df, key)
        except Exception as exc:  # noqa: BLE001 — any read or validation error is dead-lettered; caller counts failures
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
