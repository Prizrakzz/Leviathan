"""Silver readers for the feature spine: probe, load, contract-check.

Probe-before-load: every source is first probed via Parquet footer metadata
(file list, row counts, schema) without reading data pages — a few KB of S3
GETs.  An absent or empty source is structural missingness (the spine emits
NaN + availability flags), never a crash.  A PRESENT source that violates its
contract (missing columns, duplicate natural keys) is an upstream bug and
fails hard before any feature is computed.

All readers accept a *root* that is either a local directory (tests) or an
``s3://bucket`` URI (production) — pyarrow.dataset handles both.
"""
from __future__ import annotations

import os
import re
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import pyarrow.dataset as ds
import pyarrow.fs as pafs

from leviathan.common.logging import get_logger
from leviathan.storage.s3 import get_thread_local_s3_client
from leviathan.transforms.bronze_to_silver.faostat_production import (
    standardize_country_name,
)

logger = get_logger(__name__)


class ExtractionContractError(Exception):
    """A present silver source violates its input contract — upstream bug."""


@dataclass(frozen=True)
class SourceProbe:
    """Footer-metadata probe result for one silver source."""
    source_key: str
    location: str
    exists: bool
    num_files: int
    num_rows: int
    columns: tuple[str, ...]
    files: tuple[str, ...]  # fragment paths - input fingerprint for the manifest
    read_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceLoadPlan:
    """Optional bounds and parallelism for one commodity source extraction."""
    year_min: int | None = None
    year_max: int | None = None
    workers: int = 1


# Required in-file columns per source family (partition values are duplicated
# in-file by the silver writers, so no hive-partition discovery is needed).
_WEATHER_REQUIRED = ("date", "year", "month", "country", "region", "source",
                     "variable", "value")
_FAOSTAT_REQUIRED = ("country_key", "metric", "year", "value")
_PSD_REQUIRED = ("leviathan_slug", "country", "market_year",
                 "wasde_release_month", "release_date", "su_ratio")
_ONI_REQUIRED = ("year", "month", "oni_anom", "el_nino_flag", "la_nina_flag")
_IOD_REQUIRED = ("year", "month", "iod_dmi_3month_avg")
_COT_REQUIRED = ("report_date", "leviathan_slug", "mm_net_z_3yr", "mm_pct_oi_z_3yr")
_PINK_SHEET_REQUIRED = ("date", "blended_npk_index_zscore_5yr", "brent_crude_usd_bbl_zscore_5yr",
                        "urea_usd_mt_zscore_5yr", "dap_usd_mt_zscore_5yr")
_CONAB_REQUIRED = ("safra_year", "survey_number", "region", "production_revision_thousand_bags")
_FRED_FX_REQUIRED = ("date", "brl_usd_pct_change_90d", "cny_usd_pct_change_90d")
_MPOB_REQUIRED = ("date", "production_cpo_mt", "closing_stocks_palm_oil_mt",
                  "exports_palm_oil_mt", "su_ratio")
_WAP_REVISIONS_REQUIRED = ("release_month", "commodity", "country",
                            "marketing_year", "vintage_type", "row_label",
                            "value_mmt", "revision_mmt")
_NASS_REQUIRED = ("state", "year", "date", "pct_good_excellent")
_SAGIS_WEEKLY_REQUIRED = ("season", "crop", "week_number", "z_vs_3yr_avg")
_SAGIS_CEC_REQUIRED = ("production_year", "report_month", "release_date", "crop", "scope",
                        "revision_surprise")
_FUTURES_PRICES_REQUIRED = ("date", "leviathan_slug", "close")
_FGIS_REQUIRED = ("marketing_year", "week_of_marketing_year", "destination_country", "exports_mt_weekly")
_ESR_REQUIRED = (
    "commodity_name", "market_year", "week_ending_date",
    "outstanding_sales_1000mt", "weekly_exports_1000mt", "gross_new_sales_1000mt",
)
_WASDE_REQUIRED = (
    "release_date", "commodity", "table_type", "region", "marketing_year",
    "attribute", "estimate", "revision",
)
_NASS_CITRUS_REQUIRED = (
    "season", "release_date", "report_month", "crop", "state",
    "forecast_1000_boxes", "revision_1000_boxes",
)
_AMS_COTTON_QUALITY_REQUIRED = (
    "commodity", "season", "geography", "percent_tenderable",
)
_UNICA_BIWEEKLY_REQUIRED = (
    "harvest_year", "fortnight_seq", "fortnight_date", "region",
    "cane_crushed_t", "sugar_produced_t", "source_position_date",
)

# Columns that are metadata/identifiers in wide-format weather files.
# Everything else is a climate variable to be melted into (variable, value).
_WEATHER_ID_COLS = frozenset({
    "date", "year", "month", "day", "country", "region", "source",
    "commodity", "ingest_date", "source_file_name",
})

# Natural keys whose duplication in silver is a hard failure.
_WEATHER_KEY = ["date", "country", "region", "source", "variable"]
_FAOSTAT_KEY = ["country_key", "metric", "year"]
_PSD_KEY = ["country", "market_year", "wasde_release_month", "release_date"]
_ESR_KEY = ["commodity_name", "market_year", "week_ending_date", "country_code"]
_YEAR_PARTITION_RE = re.compile(r"(?:^|/)year=(\d{4})(?:/|$)")
_SLUG_TO_WASDE_COMMODITY: dict[str, str] = {
    "corn_cbot": "corn",
    "campinas_corn_reference_bmf": "corn",
    "french_maize_matif": "corn",
    "soft_red_winter_wheat_cbot": "wheat",
    "hard_red_winter_wheat_kcbt": "wheat",
    "hard_red_spring_wheat_mgex": "wheat",
    "french_wheat_matif": "wheat",
    "soybeans_cbot": "soybeans",
    "soybeans_no_1_dce": "soybeans",
    "soybeans_no_2_dce": "soybeans",
    "soybean_meal_cbot": "soybean_meal",
    "soybean_meal_dce": "soybean_meal",
    "soybean_oil_cbot": "soybean_oil",
    "soybean_oil_dce": "soybean_oil",
    "rough_rice_cbot": "rice",
    "cotton": "cotton",
    "raw_sugar": "sugar",
    "white_sugar": "sugar",
}


def _location(root: str, relative: str) -> str:
    return f"{root.rstrip('/')}/{relative}"


def _aws_region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def _year_from_path(path: str) -> int | None:
    match = _YEAR_PARTITION_RE.search(path.replace("\\", "/"))
    if not match:
        return None
    return int(match.group(1))


def _paths_with_year_partitions(
    location: str, year_min: int | None, year_max: int | None
) -> tuple[str, ...]:
    """Return parquet paths under *location* within the requested year range."""
    parsed = urlparse(location)
    paths: list[str] = []
    if parsed.scheme == "s3":
        bucket = parsed.netloc
        prefix = parsed.path.lstrip("/").rstrip("/") + "/"
        s3 = get_thread_local_s3_client(_aws_region())
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".parquet"):
                    continue
                year = _year_from_path(key)
                if year is None:
                    continue
                if year_min is not None and year < year_min:
                    continue
                if year_max is not None and year > year_max:
                    continue
                paths.append(f"s3://{bucket}/{key}")
    else:
        base = Path(location)
        if not base.exists():
            return ()
        for path in base.rglob("*.parquet"):
            year = _year_from_path(path.as_posix())
            if year is None:
                continue
            if year_min is not None and year < year_min:
                continue
            if year_max is not None and year > year_max:
                continue
            paths.append(str(path))
    return tuple(sorted(paths))


def _parquet_paths(location: str) -> tuple[str, ...]:
    """Return every parquet object/path under *location*.

    Used by source-specific readers when ``pyarrow.dataset`` schema unification
    is too brittle for legacy shards (currently WASDE).
    """
    parsed = urlparse(location)
    paths: list[str] = []
    if parsed.scheme == "s3":
        bucket = parsed.netloc
        prefix = parsed.path.lstrip("/").rstrip("/") + "/"
        s3 = get_thread_local_s3_client(_aws_region())
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".parquet"):
                    paths.append(f"s3://{bucket}/{key}")
    else:
        base = Path(location)
        if not base.exists():
            return ()
        paths = [str(path) for path in base.rglob("*.parquet")]
    return tuple(sorted(paths))


def _read_parquet_path(path: str, columns: list[str]) -> pd.DataFrame:
    parsed = urlparse(path)
    if parsed.scheme == "s3":
        s3 = get_thread_local_s3_client(_aws_region())
        body = s3.get_object(
            Bucket=parsed.netloc,
            Key=parsed.path.lstrip("/"),
        )["Body"].read()
        return pd.read_parquet(io.BytesIO(body), columns=columns)
    return pd.read_parquet(path, columns=columns)


def _load_parquet_paths(
    paths: tuple[str, ...],
    columns: list[str],
    *,
    workers: int = 1,
) -> pd.DataFrame:
    if not paths:
        return pd.DataFrame(columns=columns)
    if workers <= 1 or len(paths) <= 1:
        frames = [_read_parquet_path(path, columns) for path in paths]
    else:
        frames = []
        with ThreadPoolExecutor(max_workers=min(workers, len(paths))) as executor:
            futures = [
                executor.submit(_read_parquet_path, path, columns)
                for path in paths
            ]
            for future in as_completed(futures):
                frames.append(future.result())
    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True)


def _dataset_from_paths(paths: tuple[str, ...], location: str):
    if urlparse(location).scheme == "s3":
        fs = pafs.S3FileSystem(region=_aws_region())
        normalized = [
            f"{urlparse(path).netloc}{urlparse(path).path}"
            for path in paths
        ]
        return ds.dataset(normalized, filesystem=fs, format="parquet")
    return ds.dataset(list(paths), format="parquet")


def _path_chunks(paths: tuple[str, ...], chunk_size: int = 64) -> list[tuple[str, ...]]:
    return [
        tuple(paths[i:i + chunk_size])
        for i in range(0, len(paths), chunk_size)
    ]


def probe_source(
    source_key: str,
    location: str,
    *,
    year_min: int | None = None,
    year_max: int | None = None,
) -> SourceProbe:
    """Footer-only probe: existence, file list, row count, schema columns."""
    if year_min is not None or year_max is not None:
        read_paths = _paths_with_year_partitions(location, year_min, year_max)
        if not read_paths:
            return SourceProbe(source_key, location, False, 0, 0, (), ())
        try:
            dataset = _dataset_from_paths((read_paths[0],), location)
        except (FileNotFoundError, OSError, pd.errors.EmptyDataError):
            return SourceProbe(source_key, location, False, 0, 0, (), ())
        return SourceProbe(
            source_key=source_key,
            location=location,
            exists=True,
            num_files=len(read_paths),
            num_rows=-1,
            columns=tuple(dataset.schema.names),
            files=read_paths,
            read_paths=read_paths,
        )

    try:
        dataset = ds.dataset(location, format="parquet")
        fragments = list(dataset.get_fragments())
    except (FileNotFoundError, OSError, pd.errors.EmptyDataError):
        return SourceProbe(source_key, location, False, 0, 0, (), ())
    if not fragments:
        return SourceProbe(source_key, location, False, 0, 0, (), ())

    num_rows = sum(f.count_rows() for f in fragments)
    return SourceProbe(
        source_key=source_key,
        location=location,
        exists=True,
        num_files=len(fragments),
        num_rows=num_rows,
        columns=tuple(dataset.schema.names),
        files=tuple(f.path for f in fragments),
    )


def _check_contract(
    df: pd.DataFrame,
    source_key: str,
    required: tuple[str, ...],
    natural_key: list[str],
) -> None:
    missing = set(required) - set(df.columns)
    if missing:
        raise ExtractionContractError(
            f"{source_key}: missing required columns {sorted(missing)}"
        )
    dupes = int(df.duplicated(subset=natural_key).sum())
    if dupes:
        raise ExtractionContractError(
            f"{source_key}: {dupes} duplicate rows on natural key {natural_key} — "
            "fix the silver source; aggregating over duplicates would corrupt features"
        )


def _dedup_natural_key(
    df: pd.DataFrame, source_key: str, natural_key: list[str]
) -> pd.DataFrame:
    """Drop benign duplicate rows on the natural key, keeping the last after a
    deterministic full-column sort.

    A handful of duplicates in an auxiliary, commodity-agnostic silver source —
    a year-boundary artifact in a derived column, a late revision retained as a
    second row — must not crash the entire spine the way a strict contract would.
    The dropped count is warned so the upstream silver issue stays visible.  Use
    this only where duplicates are genuinely interchangeable for the feature;
    where extra rows are legitimately distinct (e.g. multiple report vintages),
    widen the natural key instead.
    """
    dupes = int(df.duplicated(subset=natural_key).sum())
    if not dupes:
        return df
    logger.warning(
        "%s: %d duplicate rows on %s — keeping last after deterministic sort "
        "(dedup the silver source upstream)", source_key, dupes, natural_key,
    )
    sort_cols = natural_key + [c for c in df.columns if c not in natural_key]
    return (
        df.sort_values(sort_cols, kind="mergesort")
        .drop_duplicates(subset=natural_key, keep="last")
        .reset_index(drop=True)
    )


def _load_dataset_to_pandas(
    source,
    columns: list[str],
    filter_expr: ds.Expression | None,
) -> pd.DataFrame:
    dataset = (
        _dataset_from_paths(source, source[0])
        if isinstance(source, tuple)
        else ds.dataset(source, format="parquet")
    )
    available = [c for c in columns if c in dataset.schema.names]
    table = dataset.to_table(columns=available, filter=filter_expr)
    return table.to_pandas()


def _load(probe: SourceProbe, columns: list[str],
          filter_expr: ds.Expression | None = None, workers: int = 1) -> pd.DataFrame:
    if not probe.read_paths:
        return _load_dataset_to_pandas(probe.location, columns, filter_expr)

    if workers <= 1 or len(probe.read_paths) <= 64:
        return _load_dataset_to_pandas(probe.read_paths, columns, filter_expr)

    frames: list[pd.DataFrame] = []
    chunks = _path_chunks(probe.read_paths)
    with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as executor:
        futures = [
            executor.submit(_load_dataset_to_pandas, chunk, columns, filter_expr)
            for chunk in chunks
        ]
        for future in as_completed(futures):
            frames.append(future.result())
    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True)


def extract_weather(
    root: str, commodity: str, source: str, plan: SourceLoadPlan | None = None
) -> tuple[pd.DataFrame | None, SourceProbe]:
    """Long-format silver weather for one (source, commodity)."""
    plan = plan or SourceLoadPlan()
    source_key = f"weather:{source}"
    location = _location(root, f"silver/weather/source={source}/commodity={commodity}")
    probe = probe_source(
        source_key, location, year_min=plan.year_min, year_max=plan.year_max
    )
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe

    filter_expr = None
    if "year" in probe.columns:
        if plan.year_min is not None:
            filter_expr = ds.field("year") >= plan.year_min
        if plan.year_max is not None:
            upper = ds.field("year") <= plan.year_max
            filter_expr = upper if filter_expr is None else filter_expr & upper

    df = _load(probe, list(probe.columns), filter_expr=filter_expr, workers=plan.workers)

    # Source-specific silver schemas (e.g. MODIS NDVI, on 8-day "period"
    # composites) omit the standard month/source id columns.  Derive them before
    # the melt so they stay id columns (not melted into variable/value) and the
    # long contract holds.
    if "source" not in df.columns:
        df["source"] = source
    if "month" not in df.columns and "date" in df.columns:
        df["month"] = pd.to_datetime(df["date"], errors="coerce").dt.month

    # Wide-format sources (e.g. NASA POWER) store each climate variable as a
    # separate column.  Melt to the long (variable, value) format expected by
    # all computation functions.
    if "variable" not in df.columns or "value" not in df.columns:
        id_cols = [c for c in df.columns if c in _WEATHER_ID_COLS]
        value_cols = [c for c in df.columns if c not in _WEATHER_ID_COLS]
        df = df.melt(id_vars=id_cols, value_vars=value_cols,
                     var_name="variable", value_name="value")

    _check_contract(df, source_key, _WEATHER_REQUIRED, _WEATHER_KEY)
    return df, probe


# FAOSTAT area names mechanically slugify to verbose forms that don't match the
# pipeline's geography convention (shared with PSD/weather/geographies YAMLs).
# Without this reconciliation, US-only commodities (e.g. KCBT/CBOT wheat) join
# nothing and lose every production label.  FAOSTAT key -> pipeline country.
_FAOSTAT_COUNTRY_ALIASES = {
    "united_states_of_america": "united_states",
    "viet_nam": "vietnam",
    "ethiopia_pdr": "ethiopia",          # pre-1993 FAO area; continuous with "ethiopia"
    "european_union_27": "european_union",
}


def extract_faostat(
    root: str, commodity: str
) -> tuple[pd.DataFrame | None, SourceProbe]:
    """Long-format FAOSTAT production silver for one commodity."""
    source_key = "production:faostat"
    location = _location(root, f"silver/production/commodity={commodity}")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe

    df = _load(probe, ["country_key", "metric", "year", "value", "unit",
                       "is_official", "ingest_date"])
    _check_contract(df, source_key, _FAOSTAT_REQUIRED, _FAOSTAT_KEY)
    # Normalize to pipeline-standard names used by all computation functions.
    df = df.rename(columns={"country_key": "country", "metric": "variable"})
    df["country"] = df["country"].replace(_FAOSTAT_COUNTRY_ALIASES)
    return df, probe


def extract_psd(
    root: str, commodity: str
) -> tuple[pd.DataFrame | None, SourceProbe]:
    """Wide PSD silver filtered to the commodity slug, countries standardized."""
    source_key = "psd"
    location = _location(root, "silver/psd")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe

    df = _load(
        probe,
        ["leviathan_slug", "country", "market_year", "wasde_release_month",
         "release_date", "su_ratio", "su_ratio_yoy_delta",
         "production_mt_revision", "ending_stocks_mt_revision"],
        filter_expr=ds.field("leviathan_slug") == commodity,
    )
    if df.empty:
        logger.info("%s: no rows for slug=%s", source_key, commodity)
        return None, probe
    _check_contract(df, source_key, _PSD_REQUIRED, _PSD_KEY)

    # PSD countries arrive as USDA display names ("United States", "Brazil");
    # the spine joins on the standardized convention shared with FAOSTAT and
    # the geography YAMLs ("united_states", "brazil").
    df = df.copy()
    df["country"] = df["country"].astype(str).map(standardize_country_name)
    return df, probe


def extract_oni(root: str) -> tuple[pd.DataFrame | None, SourceProbe]:
    """Global ONI/ENSO monthly silver (commodity-agnostic)."""
    source_key = "oni"
    location = _location(root, "silver/weather/source=noaa_oni")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    _check_contract(df, source_key, _ONI_REQUIRED, ["year", "month"])
    return df, probe


def extract_iod(root: str) -> tuple[pd.DataFrame | None, SourceProbe]:
    """Global IOD monthly silver (commodity-agnostic).

    The IOD silver sometimes contains two rows per (year, month) from different
    source series.  Deduplicate by preferring rows with a valid 3-month average
    over rows where it is NaN, then keep the last after sorting by dmi_value.
    """
    source_key = "iod"
    location = _location(root, "silver/weather/source=noaa_iod")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    # Prefer rows with a non-null 3-month average; sort so those sink to the
    # bottom, then drop_duplicates(keep="last") retains them.
    df = (
        df.assign(_has_avg=df["iod_dmi_3month_avg"].notna().astype(int))
        .sort_values(["year", "month", "_has_avg"])
        .drop(columns=["_has_avg"])
        .drop_duplicates(subset=["year", "month"], keep="last")
        .reset_index(drop=True)
    )
    _check_contract(df, source_key, _IOD_REQUIRED, ["year", "month"])
    return df, probe


def extract_cot(root: str) -> tuple[pd.DataFrame | None, SourceProbe]:
    """CFTC COT managed-money silver (all slugs; computation filters by commodity)."""
    source_key = "cot"
    location = _location(root, "silver/cot")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    _check_contract(df, source_key, _COT_REQUIRED, ["report_date", "leviathan_slug"])
    return df, probe


def extract_pink_sheet(root: str) -> tuple[pd.DataFrame | None, SourceProbe]:
    """World Bank Pink Sheet monthly silver (commodity-agnostic)."""
    source_key = "pink_sheet"
    location = _location(root, "silver/pink_sheet")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    _check_contract(df, source_key, _PINK_SHEET_REQUIRED, ["date"])
    return df, probe


def extract_nass_crop_progress(
    root: str, commodity: str
) -> tuple[pd.DataFrame | None, SourceProbe]:
    """USDA NASS weekly crop progress silver for one commodity."""
    source_key = "nass_crop_progress"
    location = _location(root, f"silver/nass_crop_progress/commodity={commodity}")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    _check_contract(df, source_key, _NASS_REQUIRED, ["state", "year", "date"])
    return df, probe


def extract_wap_revisions(root: str) -> tuple[pd.DataFrame | None, SourceProbe]:
    """WAP Table 01 revision series silver (all commodities and countries)."""
    source_key = "wap_revisions"
    location = _location(root, "silver/wap_table01_revisions")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    # row_label distinguishes the monthly vs. annual-projection vintage rows that
    # share (release_month, commodity, country, marketing_year); without it the
    # key spuriously collapses ~70k legitimate rows.
    _check_contract(df, source_key, _WAP_REVISIONS_REQUIRED,
                    ["release_month", "commodity", "country", "marketing_year",
                     "row_label"])
    return df, probe


def extract_mpob(root: str) -> tuple[pd.DataFrame | None, SourceProbe]:
    """MPOB monthly CPO supply/demand silver (commodity-agnostic at load)."""
    source_key = "mpob"
    location = _location(root, "silver/mpob")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    _check_contract(df, source_key, _MPOB_REQUIRED, ["date"])
    return df, probe


def extract_fred_fx(root: str) -> tuple[pd.DataFrame | None, SourceProbe]:
    """FRED FX daily silver — BRL/USD and CNY/USD 90-day pct changes."""
    source_key = "fred_fx"
    location = _location(root, "silver/fred_fx")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    # Year-end dates carry a few duplicate rows (a 90-day pct_change boundary
    # artifact in the silver); the feature only reads the latest value per date.
    df = _dedup_natural_key(df, source_key, ["date"])
    _check_contract(df, source_key, _FRED_FX_REQUIRED, ["date"])
    return df, probe


def extract_sagis_weekly(root: str) -> tuple[pd.DataFrame | None, SourceProbe]:
    """SAGIS progressive delivery totals silver (all crops; computation filters)."""
    source_key = "sagis_deliveries"
    location = _location(root, "silver/sagis_weekly_deliveries")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    # A late delivery revision can leave a second row for one (season, crop,
    # week); keep the last.  (Observed once, on a wheat week the maize feature
    # filters out anyway.)
    df = _dedup_natural_key(df, source_key, ["season", "crop", "week_number"])
    _check_contract(df, source_key, _SAGIS_WEEKLY_REQUIRED,
                    ["season", "crop", "week_number"])
    return df, probe


def extract_sagis_cec(root: str) -> tuple[pd.DataFrame | None, SourceProbe]:
    """SAGIS Crop Estimates Committee silver (all crops; computation filters)."""
    source_key = "sagis_cec"
    location = _location(root, "silver/sagis_cec")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    _check_contract(df, source_key, _SAGIS_CEC_REQUIRED,
                    ["production_year", "report_month", "crop", "scope"])
    return df, probe


def extract_conab(
    root: str, commodity: str
) -> tuple[pd.DataFrame | None, SourceProbe]:
    """CONAB coffee production silver for one commodity (arabica or robusta)."""
    source_key = "conab"
    location = _location(root, f"silver/conab_coffee/commodity={commodity}")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    _check_contract(df, source_key, _CONAB_REQUIRED, ["safra_year", "survey_number", "region"])
    return df, probe


def extract_fgis(
    root: str, commodity: str
) -> tuple[pd.DataFrame | None, SourceProbe]:
    """USDA FGIS weekly export inspection silver for one commodity slug."""
    source_key = "fgis"
    location = _location(root, f"silver/fgis/leviathan_slug={commodity}")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    _check_contract(df, source_key, _FGIS_REQUIRED,
                    ["marketing_year", "week_of_marketing_year", "destination_country"])
    return df, probe


def extract_esr(
    root: str, commodity: str
) -> tuple[pd.DataFrame | None, SourceProbe]:
    """USDA FAS ESR weekly export commitment silver for one commodity slug."""
    source_key = "esr"
    location = _location(root, f"silver/esr/commodity={commodity}")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    _check_contract(df, source_key, _ESR_REQUIRED, _ESR_KEY)
    return df, probe


def extract_wasde(
    root: str, commodity: str, plan: SourceLoadPlan | None = None
) -> tuple[pd.DataFrame | None, SourceProbe]:
    """USDA WASDE direct monthly estimate/revision silver.

    Loaded commodity-agnostic at the S3 prefix but filtered to the WASDE
    commodity categories relevant to the requested Leviathan slug.  The
    computation layer performs the final region/attribute filtering.
    """
    source_key = "wasde"
    plan = plan or SourceLoadPlan()
    location = _location(root, "silver/wasde")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s â€” structural missingness", source_key, location)
        return None, probe
    wasde_commodity = _SLUG_TO_WASDE_COMMODITY.get(commodity)
    if wasde_commodity is None:
        logger.info("%s: no WASDE commodity mapping for slug=%s", source_key, commodity)
        return None, probe
    paths = _parquet_paths(location)
    columns = [c for c in [
        "release_date", "commodity", "table_type", "region", "marketing_year",
        "attribute", "unit", "estimate", "prior_release_date", "prior_estimate",
        "revision", "revision_direction", "months_to_marketing_year_end",
        "is_first_estimate", "is_final_or_latest", "source",
    ] if c in probe.columns]
    df = _load_parquet_paths(paths, columns, workers=plan.workers)
    df = df[df["commodity"] == wasde_commodity].copy()
    if df.empty:
        logger.info("%s: no rows for slug=%s commodity=%s",
                    source_key, commodity, wasde_commodity)
        return None, probe
    _check_contract(
        df,
        source_key,
        _WASDE_REQUIRED,
        ["release_date", "commodity", "table_type", "region", "marketing_year", "attribute"],
    )
    return df, probe


def extract_nass_citrus(root: str) -> tuple[pd.DataFrame | None, SourceProbe]:
    """USDA NASS citrus monthly forecast silver."""
    source_key = "nass_citrus"
    location = _location(root, "silver/nass_citrus")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s â€” structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    _check_contract(
        df, source_key, _NASS_CITRUS_REQUIRED,
        ["season", "release_date", "crop", "state"],
    )
    return df, probe


def extract_ams_cotton_quality(root: str) -> tuple[pd.DataFrame | None, SourceProbe]:
    """USDA AMS annual cotton classing quality silver."""
    source_key = "ams_cotton_quality"
    location = _location(root, "silver/ams_cotton_quality")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s â€” structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    _check_contract(
        df, source_key, _AMS_COTTON_QUALITY_REQUIRED,
        ["commodity", "geography", "season"],
    )
    return df, probe


def extract_unica_biweekly(root: str) -> tuple[pd.DataFrame | None, SourceProbe]:
    """UNICA Center-South biweekly sugarcane season-history silver."""
    source_key = "unica_biweekly"
    location = _location(root, "silver/unica_biweekly_season_history")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s â€” structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    _check_contract(
        df, source_key, _UNICA_BIWEEKLY_REQUIRED,
        ["harvest_year", "region", "fortnight_seq"],
    )
    return df, probe


def extract_futures_prices(root: str) -> tuple[pd.DataFrame | None, SourceProbe]:
    """Daily futures-price silver (all contracts; computation filters by slug).

    Commodity-agnostic at load — the crush-margin computation selects the soy
    complex legs.  Prices are used only where they encode an economic driver
    (board crush); raw momentum/vol columns are intentionally not surfaced as
    features.
    """
    source_key = "futures_prices"
    location = _location(root, "silver/futures_prices")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe
    df = _load(probe, list(probe.columns))
    df = _dedup_natural_key(df, source_key, ["date", "leviathan_slug"])
    _check_contract(df, source_key, _FUTURES_PRICES_REQUIRED, ["date", "leviathan_slug"])
    return df, probe


def _extract_one(
    root: str, commodity: str, key: str, plan: SourceLoadPlan
) -> tuple[str, pd.DataFrame | None, SourceProbe]:
    start = time.monotonic()
    logger.info("%s: extracting source for commodity=%s", key, commodity)
    if key.startswith("weather:"):
        df, probe = extract_weather(root, commodity, key.split(":", 1)[1], plan)
    elif key == "production:faostat":
        df, probe = extract_faostat(root, commodity)
    elif key == "psd":
        df, probe = extract_psd(root, commodity)
    elif key == "oni":
        df, probe = extract_oni(root)
    elif key == "iod":
        df, probe = extract_iod(root)
    elif key == "cot":
        df, probe = extract_cot(root)
    elif key == "pink_sheet":
        df, probe = extract_pink_sheet(root)
    elif key == "nass_crop_progress":
        df, probe = extract_nass_crop_progress(root, commodity)
    elif key == "wap_revisions":
        df, probe = extract_wap_revisions(root)
    elif key == "mpob":
        df, probe = extract_mpob(root)
    elif key == "fred_fx":
        df, probe = extract_fred_fx(root)
    elif key == "sagis_deliveries":
        df, probe = extract_sagis_weekly(root)
    elif key == "sagis_cec":
        df, probe = extract_sagis_cec(root)
    elif key == "futures_prices":
        df, probe = extract_futures_prices(root)
    elif key == "conab":
        df, probe = extract_conab(root, commodity)
    elif key == "fgis":
        df, probe = extract_fgis(root, commodity)
    elif key == "esr":
        df, probe = extract_esr(root, commodity)
    elif key == "wasde":
        df, probe = extract_wasde(root, commodity, plan)
    elif key == "nass_citrus":
        df, probe = extract_nass_citrus(root)
    elif key == "ams_cotton_quality":
        df, probe = extract_ams_cotton_quality(root)
    elif key == "unica_biweekly":
        df, probe = extract_unica_biweekly(root)
    else:
        raise ExtractionContractError(f"Unknown source key in registry: {key!r}")

    elapsed = time.monotonic() - start
    rows = 0 if df is None else len(df)
    logger.info(
        "%s: extracted rows=%d files=%d metadata_rows=%d elapsed=%.1fs",
        key, rows, probe.num_files, probe.num_rows, elapsed,
    )
    return key, df, probe


def extract_all(
    root: str,
    commodity: str,
    source_keys: set[str],
    *,
    plan: SourceLoadPlan | None = None,
) -> tuple[dict[str, pd.DataFrame], list[SourceProbe]]:
    """Extract every source the registry requires for *commodity*.

    Returns ``(inputs, probes)`` - *inputs* holds only sources that exist;
    *probes* records every attempt (incl. misses) for the run manifest.
    """
    plan = plan or SourceLoadPlan()
    keys = sorted(source_keys)
    results: dict[str, tuple[pd.DataFrame | None, SourceProbe]] = {}
    errors: dict[str, str] = {}

    if plan.workers <= 1 or len(keys) <= 1:
        for key in keys:
            _, df, probe = _extract_one(root, commodity, key, plan)
            results[key] = (df, probe)
    else:
        max_workers = min(plan.workers, len(keys))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_key = {
                executor.submit(_extract_one, root, commodity, key, plan): key
                for key in keys
            }
            for future in as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    _, df, probe = future.result()
                    results[key] = (df, probe)
                except Exception as exc:  # noqa: BLE001 - aggregate after all futures finish
                    logger.exception("%s: extraction failed for commodity=%s", key, commodity)
                    errors[key] = str(exc)
        if errors:
            raise ExtractionContractError(
                f"{commodity}: {len(errors)} source extraction failures: {errors}"
            )

    inputs: dict[str, pd.DataFrame] = {}
    probes: list[SourceProbe] = []
    for key in keys:
        df, probe = results[key]
        probes.append(probe)
        if df is not None:
            inputs[key] = df
    return inputs, probes
