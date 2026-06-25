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

import time
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
        start = time.monotonic()
        logger.info("%s: extracting source for commodity=%s", key, commodity)
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
        elif key == "nass_crop_progress":
            df, probe = extract_nass_crop_progress(root, commodity)
        elif key == "wap_revisions":
            if "wap_revisions" not in _agnostic_cache:
                _agnostic_cache["wap_revisions"] = extract_wap_revisions(root)
            df, probe = _agnostic_cache["wap_revisions"]
        elif key == "mpob":
            if "mpob" not in _agnostic_cache:
                _agnostic_cache["mpob"] = extract_mpob(root)
            df, probe = _agnostic_cache["mpob"]
        elif key == "fred_fx":
            if "fred_fx" not in _agnostic_cache:
                _agnostic_cache["fred_fx"] = extract_fred_fx(root)
            df, probe = _agnostic_cache["fred_fx"]
        elif key == "sagis_deliveries":
            if "sagis_deliveries" not in _agnostic_cache:
                _agnostic_cache["sagis_deliveries"] = extract_sagis_weekly(root)
            df, probe = _agnostic_cache["sagis_deliveries"]
        elif key == "sagis_cec":
            if "sagis_cec" not in _agnostic_cache:
                _agnostic_cache["sagis_cec"] = extract_sagis_cec(root)
            df, probe = _agnostic_cache["sagis_cec"]
        elif key == "futures_prices":
            if "futures_prices" not in _agnostic_cache:
                _agnostic_cache["futures_prices"] = extract_futures_prices(root)
            df, probe = _agnostic_cache["futures_prices"]
        elif key == "conab":
            df, probe = extract_conab(root, commodity)
        elif key == "fgis":
            df, probe = extract_fgis(root, commodity)
        elif key == "esr":
            df, probe = extract_esr(root, commodity)
        else:
            raise ExtractionContractError(f"Unknown source key in registry: {key!r}")
        elapsed = time.monotonic() - start
        rows = 0 if df is None else len(df)
        logger.info(
            "%s: extracted rows=%d files=%d metadata_rows=%d elapsed=%.1fs",
            key, rows, probe.num_files, probe.num_rows, elapsed,
        )
        probes.append(probe)
        if df is not None:
            inputs[key] = df
    return inputs, probes
