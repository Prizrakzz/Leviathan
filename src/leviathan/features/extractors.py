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

from dataclasses import dataclass

import pandas as pd
import pyarrow.dataset as ds

from leviathan.common.logging import get_logger
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
    files: tuple[str, ...]  # fragment paths — input fingerprint for the manifest


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
_PINK_SHEET_REQUIRED = ("date", "blended_npk_index_zscore_5yr", "brent_crude_usd_bbl_zscore_5yr")
_CONAB_REQUIRED = ("safra_year", "survey_number", "region", "production_revision_thousand_bags")
_FGIS_REQUIRED = ("marketing_year", "week_of_marketing_year", "destination_country", "exports_mt_weekly")

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


def _location(root: str, relative: str) -> str:
    return f"{root.rstrip('/')}/{relative}"


def probe_source(source_key: str, location: str) -> SourceProbe:
    """Footer-only probe: existence, file list, row count, schema columns."""
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


def _load(probe: SourceProbe, columns: list[str],
          filter_expr: ds.Expression | None = None) -> pd.DataFrame:
    dataset = ds.dataset(probe.location, format="parquet")
    available = [c for c in columns if c in dataset.schema.names]
    table = dataset.to_table(columns=available, filter=filter_expr)
    return table.to_pandas()


def extract_weather(
    root: str, commodity: str, source: str
) -> tuple[pd.DataFrame | None, SourceProbe]:
    """Long-format silver weather for one (source, commodity)."""
    source_key = f"weather:{source}"
    location = _location(root, f"silver/weather/source={source}/commodity={commodity}")
    probe = probe_source(source_key, location)
    if not probe.exists or probe.num_rows == 0:
        logger.info("%s: no data at %s — structural missingness", source_key, location)
        return None, probe

    df = _load(probe, list(probe.columns))

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


def extract_all(
    root: str, commodity: str, source_keys: set[str]
) -> tuple[dict[str, pd.DataFrame], list[SourceProbe]]:
    """Extract every source the registry requires for *commodity*.

    Returns ``(inputs, probes)`` — *inputs* holds only sources that exist;
    *probes* records every attempt (incl. misses) for the run manifest.
    """
    inputs: dict[str, pd.DataFrame] = {}
    probes: list[SourceProbe] = []

    # Commodity-agnostic sources only need to be loaded once regardless of how
    # many feature families reference them; de-duplicate via the inputs dict.
    _agnostic_cache: dict[str, tuple[pd.DataFrame | None, SourceProbe]] = {}

    for key in sorted(source_keys):
        if key.startswith("weather:"):
            df, probe = extract_weather(root, commodity, key.split(":", 1)[1])
        elif key == "production:faostat":
            df, probe = extract_faostat(root, commodity)
        elif key == "psd":
            df, probe = extract_psd(root, commodity)
        elif key == "oni":
            if "oni" not in _agnostic_cache:
                _agnostic_cache["oni"] = extract_oni(root)
            df, probe = _agnostic_cache["oni"]
        elif key == "iod":
            if "iod" not in _agnostic_cache:
                _agnostic_cache["iod"] = extract_iod(root)
            df, probe = _agnostic_cache["iod"]
        elif key == "cot":
            if "cot" not in _agnostic_cache:
                _agnostic_cache["cot"] = extract_cot(root)
            df, probe = _agnostic_cache["cot"]
        elif key == "pink_sheet":
            if "pink_sheet" not in _agnostic_cache:
                _agnostic_cache["pink_sheet"] = extract_pink_sheet(root)
            df, probe = _agnostic_cache["pink_sheet"]
        elif key == "conab":
            df, probe = extract_conab(root, commodity)
        elif key == "fgis":
            df, probe = extract_fgis(root, commodity)
        else:
            raise ExtractionContractError(f"Unknown source key in registry: {key!r}")
        probes.append(probe)
        if df is not None:
            inputs[key] = df
    return inputs, probes
