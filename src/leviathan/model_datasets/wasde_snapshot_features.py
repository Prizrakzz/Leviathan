"""Dynamic WASDE point-in-time features for snapshot model-ready rows."""
from __future__ import annotations

import re
from typing import Iterable

import numpy as np
import pandas as pd

from leviathan.model_datasets.wasde_snapshot_mapping import (
    WasdeSnapshotMappingConfig,
    load_wasde_snapshot_mappings,
    normalize_wasde_token,
)

DYNAMIC_FEATURE_ID_COLUMNS = [
    "dataset_key",
    "contract_key",
    "origin_key",
    "target_market_year",
    "as_of_date",
    "snapshot_stage",
]

DYNAMIC_FEATURE_METADATA_COLUMNS = [
    "wasde_commodity",
    "wasde_origin",
    "source_release_date_max",
    "source_release_count_visible",
]

DEFAULT_ATTRIBUTES = (
    "production",
    "ending_stocks",
    "exports",
    "imports",
    "domestic_total",
    "total_use",
    "feed",
    "feed_residual",
    "beginning_stocks",
    "total_supply",
)

SOURCE_NATURAL_KEY = [
    "release_date",
    "wasde_commodity",
    "wasde_origin",
    "target_market_year",
    "attribute",
]


def _finite(value: object) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except Exception:  # noqa: BLE001
        return False


def _year_start(value: object) -> int | None:
    match = re.search(r"\d{4}", str(value or ""))
    return int(match.group(0)) if match else None


def _zscore(value: float, history: pd.Series, *, min_history_years: int) -> float:
    if not _finite(value):
        return np.nan
    prior = pd.to_numeric(history, errors="coerce").dropna()
    if len(prior) < min_history_years:
        return np.nan
    std = float(prior.std(ddof=0))
    if not np.isfinite(std) or std == 0.0:
        return np.nan
    return float((float(value) - float(prior.mean())) / std)


def _trend_pct_deviation(
    value: float,
    years: pd.Series,
    history: pd.Series,
    *,
    target_year: int,
    min_history_years: int,
) -> float:
    if not _finite(value):
        return np.nan
    frame = pd.DataFrame({
        "year": pd.to_numeric(years, errors="coerce"),
        "value": pd.to_numeric(history, errors="coerce"),
    }).dropna()
    frame = frame.drop_duplicates("year", keep="last").sort_values("year")
    if len(frame) < min_history_years or frame["year"].nunique() < 2:
        return np.nan
    coeffs = np.polyfit(frame["year"].to_numpy(dtype=float), frame["value"].to_numpy(dtype=float), 1)
    trend = float(np.polyval(coeffs, float(target_year)))
    if not np.isfinite(trend) or trend == 0.0:
        return np.nan
    return float((float(value) - trend) / abs(trend))


def _consecutive_revision_count(revisions: Iterable[object]) -> float:
    values = pd.to_numeric(pd.Series(list(revisions)), errors="coerce").dropna()
    if values.empty:
        return np.nan
    signs = np.sign(values.to_numpy(dtype=float))
    last = signs[-1]
    if last == 0:
        return 0.0
    count = 0
    for sign in signs[::-1]:
        if sign == 0 or sign != last:
            break
        count += 1
    return float(count * last)


def _constant_rate(series: pd.Series) -> float:
    non_null = series.dropna()
    if non_null.empty:
        return np.nan
    shares = non_null.value_counts(dropna=True, normalize=True)
    return float(shares.max()) if not shares.empty else np.nan


def prepare_wasde_snapshot_feature_source(
    wasde_df: pd.DataFrame,
    *,
    mapping_config: WasdeSnapshotMappingConfig | None = None,
    attributes: tuple[str, ...] = DEFAULT_ATTRIBUTES,
) -> pd.DataFrame:
    """Normalize and validate long-form WASDE rows for dynamic features."""
    required = {"release_date", "commodity", "region", "marketing_year", "attribute", "estimate"}
    missing = required - set(wasde_df.columns)
    if missing:
        raise ValueError(f"WASDE dynamic feature source missing columns: {sorted(missing)}")

    cfg = mapping_config or load_wasde_snapshot_mappings()
    source = wasde_df.copy()
    source["release_date"] = pd.to_datetime(source["release_date"], errors="coerce")
    source["wasde_commodity"] = source["commodity"].map(normalize_wasde_token)
    source["wasde_region"] = source["region"].map(normalize_wasde_token)
    source["wasde_origin"] = source["wasde_region"].map(
        lambda value: cfg.region_aliases.get(value, value)
    )
    source["target_market_year"] = source["marketing_year"].map(_year_start)
    source["attribute"] = source["attribute"].map(normalize_wasde_token)
    source["estimate"] = pd.to_numeric(source["estimate"], errors="coerce")
    if "revision" in source.columns:
        source["source_revision"] = pd.to_numeric(source["revision"], errors="coerce")
    else:
        source["source_revision"] = np.nan

    allowed_attrs = {normalize_wasde_token(attr) for attr in attributes}
    source = source.loc[source["attribute"].isin(allowed_attrs)].copy()
    source = source.dropna(subset=["release_date", "target_market_year"]).copy()
    source["target_market_year"] = source["target_market_year"].astype(int)

    exact_count = len(source)
    source = source.drop_duplicates().reset_index(drop=True)
    if len(source) < exact_count:
        source = source.copy()

    source = _dedupe_conflicting_wasde_cells(source)
    return source.sort_values(SOURCE_NATURAL_KEY).reset_index(drop=True)


def _dedupe_conflicting_wasde_cells(source: pd.DataFrame) -> pd.DataFrame:
    """Resolve duplicate WASDE cells when parser tables overlap.

    Older WASDE parsed releases can contain both a US table row and a world
    table row for the same non-US origin. For contract-origin features, the
    world table is the correct non-US source, while US origins should prefer
    the US table. Remaining ambiguous conflicts still raise.
    """
    if source.empty:
        return source
    conflict_mask = source.duplicated(SOURCE_NATURAL_KEY, keep=False)
    if not conflict_mask.any():
        return source

    resolved: list[pd.DataFrame] = []
    ambiguous: list[dict[str, object]] = []
    for _, group in source.groupby(SOURCE_NATURAL_KEY, dropna=False, sort=False):
        if len(group) == 1:
            resolved.append(group)
            continue
        if group["estimate"].nunique(dropna=False) <= 1:
            resolved.append(group.tail(1))
            continue

        if "table_type" not in group.columns:
            ambiguous.append(group.iloc[0][SOURCE_NATURAL_KEY].to_dict())
            continue

        table_type = group["table_type"].map(normalize_wasde_token)
        origin = str(group.iloc[0]["wasde_origin"])
        preferred_table_type = "us" if origin == "united_states" else "world"
        preference = table_type.eq(preferred_table_type).astype(int) * 10
        preference = preference + group["source_revision"].notna().astype(int)
        max_pref = int(preference.max())
        winners = group.loc[preference == max_pref]
        if winners["estimate"].nunique(dropna=False) > 1:
            ambiguous.append(group.iloc[0][SOURCE_NATURAL_KEY].to_dict())
            continue
        resolved.append(winners.tail(1))

    if ambiguous:
        raise ValueError(
            "WASDE dynamic feature source has conflicting duplicate cells: "
            f"{ambiguous[:5]}"
        )
    return pd.concat(resolved, ignore_index=True)


def _snapshot_spine(snapshot_targets: pd.DataFrame) -> pd.DataFrame:
    required = {
        "dataset_key",
        "contract_key",
        "origin_key",
        "target_market_year",
        "as_of_date",
        "snapshot_stage",
        "wasde_commodity",
        "wasde_origin",
    }
    missing = required - set(snapshot_targets.columns)
    if missing:
        raise ValueError(f"snapshot target frame missing columns: {sorted(missing)}")
    spine = snapshot_targets[
        [
            "dataset_key",
            "contract_key",
            "origin_key",
            "target_market_year",
            "as_of_date",
            "snapshot_stage",
            "wasde_commodity",
            "wasde_origin",
        ]
    ].drop_duplicates().copy()
    spine["target_market_year"] = pd.to_numeric(spine["target_market_year"], errors="coerce")
    spine["as_of_date"] = pd.to_datetime(spine["as_of_date"], errors="coerce")
    spine["wasde_commodity"] = spine["wasde_commodity"].map(normalize_wasde_token)
    spine["wasde_origin"] = spine["wasde_origin"].map(normalize_wasde_token)
    spine = spine.dropna(subset=["target_market_year", "as_of_date"]).copy()
    spine["target_market_year"] = spine["target_market_year"].astype(int)
    duplicates = spine.duplicated(DYNAMIC_FEATURE_ID_COLUMNS, keep=False)
    if duplicates.any():
        conflicts = (
            spine.loc[duplicates, DYNAMIC_FEATURE_ID_COLUMNS]
            .drop_duplicates()
            .sort_values(DYNAMIC_FEATURE_ID_COLUMNS)
            .to_dict("records")
        )
        raise ValueError(f"duplicate snapshot feature spine rows: {conflicts[:5]}")
    return spine.sort_values(DYNAMIC_FEATURE_ID_COLUMNS).reset_index(drop=True)


def _visible_attribute_rows(
    source: pd.DataFrame,
    *,
    commodity: str,
    origin: str,
    market_year: int,
    as_of_date: pd.Timestamp,
    attribute: str,
) -> pd.DataFrame:
    rows = source.loc[
        (source["wasde_commodity"] == commodity)
        & (source["wasde_origin"] == origin)
        & (source["target_market_year"] == int(market_year))
        & (source["attribute"] == attribute)
        & (source["release_date"] <= as_of_date)
    ].sort_values("release_date")
    return rows


def _historical_at_sequence(
    enriched_attr: pd.DataFrame,
    *,
    market_year: int,
    release_sequence: int,
    value_column: str,
) -> pd.DataFrame:
    prior = enriched_attr.loc[
        (enriched_attr["target_market_year"] < int(market_year))
        & (enriched_attr["release_sequence"] <= int(release_sequence))
    ].copy()
    if prior.empty:
        return prior
    return (
        prior.sort_values(["target_market_year", "release_sequence", "release_date"])
        .groupby("target_market_year", sort=True)
        .tail(1)
        .dropna(subset=[value_column])
    )


def _enrich_source_revisions(source: pd.DataFrame) -> pd.DataFrame:
    if source.empty:
        return source.copy()
    out = source.copy().sort_values(SOURCE_NATURAL_KEY).reset_index(drop=True)
    release_key = ["wasde_commodity", "wasde_origin", "target_market_year"]
    release_dates = (
        out[release_key + ["release_date"]]
        .drop_duplicates()
        .sort_values(release_key + ["release_date"])
        .copy()
    )
    release_dates["release_sequence"] = release_dates.groupby(release_key).cumcount() + 1
    out = out.merge(release_dates, on=release_key + ["release_date"], how="left")

    attr_key = [*release_key, "attribute"]
    out["mom_revision"] = out.groupby(attr_key)["estimate"].diff()
    first_estimate = out.groupby(attr_key)["estimate"].transform("first")
    out["first_estimate"] = first_estimate
    out["revision_since_first"] = out["estimate"] - first_estimate
    out["latest_vs_first_forecast_pct"] = np.where(
        first_estimate.abs() > 0,
        out["revision_since_first"] / first_estimate.abs(),
        np.nan,
    )
    streaks: list[float] = []
    for _, group in out.groupby(attr_key, sort=False):
        revisions = group["mom_revision"].tolist()
        for idx in range(len(group)):
            streaks.append(_consecutive_revision_count(revisions[: idx + 1]))
    out["consecutive_revision_count"] = streaks
    return out.sort_values(SOURCE_NATURAL_KEY).reset_index(drop=True)


def _build_release_wide_features(
    enriched: pd.DataFrame,
    *,
    attributes: tuple[str, ...],
    min_history_years: int,
) -> pd.DataFrame:
    """Precompute dynamic features once per WASDE release/attribute."""
    index_cols = [
        "wasde_commodity",
        "wasde_origin",
        "target_market_year",
        "release_date",
    ]
    if enriched.empty:
        return pd.DataFrame(columns=[
            *index_cols,
            "source_release_date_max",
            "source_release_count_visible",
        ])

    feature_rows: list[dict[str, object]] = []
    for (commodity, origin, attribute), group in enriched.groupby(
        ["wasde_commodity", "wasde_origin", "attribute"],
        sort=False,
    ):
        if attribute not in attributes:
            continue
        attr_group = group.sort_values([
            "release_sequence",
            "target_market_year",
            "release_date",
        ]).copy()
        attr_group["latest_z_precomputed"] = np.nan
        attr_group["revision_z_precomputed"] = np.nan
        attr_group["latest_vs_trend_z_precomputed"] = np.nan

        for _, seq_group in attr_group.groupby("release_sequence", sort=False):
            ordered = seq_group.sort_values(["target_market_year", "release_date"]).copy()
            for value_col, output_col in (
                ("estimate", "latest_z_precomputed"),
                ("mom_revision", "revision_z_precomputed"),
            ):
                values = pd.to_numeric(ordered[value_col], errors="coerce")
                prior_count = values.expanding(min_periods=1).count().shift(1)
                prior_mean = values.expanding(min_periods=1).mean().shift(1)
                prior_std = values.expanding(min_periods=1).std(ddof=0).shift(1)
                z = (values - prior_mean) / prior_std
                z = z.where((prior_count >= min_history_years) & (prior_std > 0))
                attr_group.loc[ordered.index, output_col] = z

            values = pd.to_numeric(ordered["estimate"], errors="coerce").reset_index(drop=True)
            years = pd.to_numeric(ordered["target_market_year"], errors="coerce").reset_index(drop=True)
            trend_values: list[float] = []
            for idx, value in enumerate(values):
                prior = pd.DataFrame({
                    "year": years.iloc[:idx],
                    "value": values.iloc[:idx],
                }).dropna()
                if len(prior) < min_history_years or prior["year"].nunique() < 2 or not _finite(value):
                    trend_values.append(np.nan)
                    continue
                coeffs = np.polyfit(
                    prior["year"].to_numpy(dtype=float),
                    prior["value"].to_numpy(dtype=float),
                    1,
                )
                trend = float(np.polyval(coeffs, float(years.iloc[idx])))
                trend_values.append(
                    float((float(value) - trend) / abs(trend))
                    if np.isfinite(trend) and trend != 0.0 else np.nan
                )
            attr_group.loc[ordered.index, "latest_vs_trend_z_precomputed"] = trend_values

        attr_group = attr_group.sort_values(["target_market_year", "release_sequence", "release_date"])
        prefix = f"wasde_{attribute}"
        for row in attr_group.itertuples(index=False):
            market_year = int(row.target_market_year)
            release_sequence = int(row.release_sequence)
            latest = float(row.estimate) if _finite(row.estimate) else np.nan
            values = {
                f"{prefix}_latest": latest,
                f"{prefix}_mom_revision": (
                    float(row.mom_revision) if _finite(row.mom_revision) else np.nan
                ),
                f"{prefix}_revision_since_first": (
                    float(row.revision_since_first)
                    if _finite(row.revision_since_first) else np.nan
                ),
                f"{prefix}_consecutive_revision_count": (
                    float(row.consecutive_revision_count)
                    if _finite(row.consecutive_revision_count) else np.nan
                ),
                f"{prefix}_revision_z": (
                    float(row.revision_z_precomputed)
                    if _finite(row.revision_z_precomputed) else np.nan
                ),
                f"{prefix}_latest_z": (
                    float(row.latest_z_precomputed)
                    if _finite(row.latest_z_precomputed) else np.nan
                ),
                f"{prefix}_latest_vs_trend_z": (
                    float(row.latest_vs_trend_z_precomputed)
                    if _finite(row.latest_vs_trend_z_precomputed) else np.nan
                ),
                f"{prefix}_latest_vs_first_forecast_pct": (
                    float(row.latest_vs_first_forecast_pct)
                    if _finite(row.latest_vs_first_forecast_pct) else np.nan
                ),
            }
            for feature, value in values.items():
                feature_rows.append({
                    "wasde_commodity": commodity,
                    "wasde_origin": origin,
                    "target_market_year": market_year,
                    "release_date": row.release_date,
                    "release_sequence": release_sequence,
                    "feature": feature,
                    "value": value,
                })

    if not feature_rows:
        return pd.DataFrame(columns=[
            *index_cols,
            "source_release_date_max",
            "source_release_count_visible",
        ])

    long = pd.DataFrame(feature_rows)
    wide = (
        long.pivot_table(
            index=[*index_cols, "release_sequence"],
            columns="feature",
            values="value",
            aggfunc="last",
        )
        .reset_index()
    )
    wide.columns = [str(col) for col in wide.columns]
    expected_suffixes = (
        "latest",
        "mom_revision",
        "revision_since_first",
        "consecutive_revision_count",
        "revision_z",
        "latest_z",
        "latest_vs_trend_z",
        "latest_vs_first_forecast_pct",
    )
    for attribute in attributes:
        for suffix in expected_suffixes:
            col = f"wasde_{attribute}_{suffix}"
            if col not in wide.columns:
                wide[col] = np.nan
    wide["source_release_date_max"] = wide["release_date"]
    wide["source_release_count_visible"] = wide["release_sequence"].astype(int)
    wide["wasde_snapshot_month_code"] = pd.to_datetime(wide["release_date"]).dt.month.astype(int)
    wide["wasde_release_sequence"] = wide["release_sequence"].astype(float)
    wide["wasde_visible_release_count"] = wide["release_sequence"].astype(float)
    wide["wasde_is_first_estimate"] = np.where(wide["release_sequence"].astype(int) == 1, 1.0, 0.0)
    wide["wasde_is_latest_visible_release"] = 1.0
    first_release = wide.groupby(
        ["wasde_commodity", "wasde_origin", "target_market_year"]
    )["release_date"].transform("min")
    release_ts = pd.to_datetime(wide["release_date"])
    first_ts = pd.to_datetime(first_release)
    wide["wasde_months_since_first_forecast"] = (
        (release_ts.dt.year - first_ts.dt.year) * 12
        + (release_ts.dt.month - first_ts.dt.month)
    ).astype(float)

    production = wide.get("wasde_production_latest", pd.Series(np.nan, index=wide.index))
    imports = wide.get("wasde_imports_latest", pd.Series(np.nan, index=wide.index))
    beginning = wide.get("wasde_beginning_stocks_latest", pd.Series(np.nan, index=wide.index))
    exports = wide.get("wasde_exports_latest", pd.Series(np.nan, index=wide.index))
    ending = wide.get("wasde_ending_stocks_latest", pd.Series(np.nan, index=wide.index))
    domestic = wide.get("wasde_domestic_total_latest", pd.Series(np.nan, index=wide.index))
    total_supply = wide.get("wasde_total_supply_latest", pd.Series(np.nan, index=wide.index))
    total_use = wide.get("wasde_total_use_latest", pd.Series(np.nan, index=wide.index))
    computed_supply = beginning + production + imports
    computed_use = domestic + exports
    wide["wasde_total_supply_estimate"] = total_supply.where(total_supply.notna(), computed_supply)
    wide["wasde_total_use_estimate"] = total_use.where(total_use.notna(), computed_use)
    denominator = wide["wasde_total_use_estimate"]
    wide["wasde_stock_to_use_estimate"] = np.where(
        denominator.notna() & (denominator.astype(float) != 0.0) & ending.notna(),
        ending.astype(float) / denominator.astype(float),
        np.nan,
    )
    wide["wasde_ending_stocks_to_use_estimate"] = wide["wasde_stock_to_use_estimate"]
    return wide.drop(columns=["release_sequence"]).reset_index(drop=True)


def _feature_values_for_snapshot(
    *,
    source_groups: dict[tuple[str, str, int], pd.DataFrame],
    enriched_year_attr_groups: dict[tuple[str, str, int, str], pd.DataFrame],
    enriched_attr_groups: dict[tuple[str, str, str], pd.DataFrame],
    empty_source: pd.DataFrame,
    empty_enriched: pd.DataFrame,
    snapshot: pd.Series,
    attributes: tuple[str, ...],
    min_history_years: int,
) -> dict[str, object]:
    commodity = str(snapshot["wasde_commodity"])
    origin = str(snapshot["wasde_origin"])
    market_year = int(snapshot["target_market_year"])
    as_of_date = pd.Timestamp(snapshot["as_of_date"])

    source_group = source_groups.get((commodity, origin, market_year), empty_source)
    base_visible = source_group.loc[source_group["release_date"] <= as_of_date].copy()

    out: dict[str, object] = {
        "dataset_key": snapshot["dataset_key"],
        "contract_key": snapshot["contract_key"],
        "origin_key": snapshot["origin_key"],
        "target_market_year": market_year,
        "as_of_date": as_of_date,
        "snapshot_stage": snapshot["snapshot_stage"],
        "wasde_commodity": commodity,
        "wasde_origin": origin,
        "source_release_date_max": base_visible["release_date"].max() if not base_visible.empty else pd.NaT,
        "source_release_count_visible": int(base_visible["release_date"].nunique()) if not base_visible.empty else 0,
        "wasde_snapshot_month_code": int(as_of_date.month),
    }

    latest_by_attr: dict[str, float] = {}
    current_release_sequence = 0
    for attribute in attributes:
        attr_group = enriched_year_attr_groups.get(
            (commodity, origin, market_year, attribute),
            empty_enriched,
        )
        visible = attr_group.loc[attr_group["release_date"] <= as_of_date].sort_values("release_date")
        prefix = f"wasde_{attribute}"
        if visible.empty:
            out[f"{prefix}_latest"] = np.nan
            out[f"{prefix}_mom_revision"] = np.nan
            out[f"{prefix}_revision_since_first"] = np.nan
            out[f"{prefix}_consecutive_revision_count"] = np.nan
            out[f"{prefix}_revision_z"] = np.nan
            out[f"{prefix}_latest_z"] = np.nan
            out[f"{prefix}_latest_vs_trend_z"] = np.nan
            out[f"{prefix}_latest_vs_first_forecast_pct"] = np.nan
            continue

        latest = visible.iloc[-1]
        latest_estimate = float(latest["estimate"]) if _finite(latest["estimate"]) else np.nan
        latest_by_attr[attribute] = latest_estimate
        release_sequence = int(latest["release_sequence"])
        current_release_sequence = max(current_release_sequence, release_sequence)
        attr_history = enriched_attr_groups.get((commodity, origin, attribute), empty_enriched)
        hist_est = _historical_at_sequence(
            attr_history,
            market_year=market_year,
            release_sequence=release_sequence,
            value_column="estimate",
        )
        hist_rev = _historical_at_sequence(
            attr_history,
            market_year=market_year,
            release_sequence=release_sequence,
            value_column="mom_revision",
        )

        out[f"{prefix}_latest"] = latest_estimate
        out[f"{prefix}_mom_revision"] = (
            float(latest["mom_revision"]) if _finite(latest["mom_revision"]) else np.nan
        )
        out[f"{prefix}_revision_since_first"] = (
            float(latest["revision_since_first"])
            if _finite(latest["revision_since_first"]) else np.nan
        )
        out[f"{prefix}_consecutive_revision_count"] = (
            float(latest["consecutive_revision_count"])
            if _finite(latest["consecutive_revision_count"]) else np.nan
        )
        out[f"{prefix}_revision_z"] = _zscore(
            out[f"{prefix}_mom_revision"],
            hist_rev["mom_revision"] if not hist_rev.empty else pd.Series(dtype=float),
            min_history_years=min_history_years,
        )
        out[f"{prefix}_latest_z"] = _zscore(
            latest_estimate,
            hist_est["estimate"] if not hist_est.empty else pd.Series(dtype=float),
            min_history_years=min_history_years,
        )
        out[f"{prefix}_latest_vs_trend_z"] = _trend_pct_deviation(
            latest_estimate,
            hist_est["target_market_year"] if not hist_est.empty else pd.Series(dtype=float),
            hist_est["estimate"] if not hist_est.empty else pd.Series(dtype=float),
            target_year=market_year,
            min_history_years=min_history_years,
        )
        out[f"{prefix}_latest_vs_first_forecast_pct"] = (
            float(latest["latest_vs_first_forecast_pct"])
            if _finite(latest["latest_vs_first_forecast_pct"]) else np.nan
        )

    production = latest_by_attr.get("production", np.nan)
    imports = latest_by_attr.get("imports", np.nan)
    beginning_stocks = latest_by_attr.get("beginning_stocks", np.nan)
    exports = latest_by_attr.get("exports", np.nan)
    ending_stocks = latest_by_attr.get("ending_stocks", np.nan)
    domestic_total = latest_by_attr.get("domestic_total", np.nan)
    total_supply = latest_by_attr.get("total_supply", np.nan)
    total_use = latest_by_attr.get("total_use", np.nan)

    computed_supply = (
        beginning_stocks + production + imports
        if all(_finite(value) for value in (beginning_stocks, production, imports))
        else np.nan
    )
    computed_use = (
        domestic_total + exports
        if all(_finite(value) for value in (domestic_total, exports))
        else np.nan
    )
    out["wasde_total_supply_estimate"] = (
        total_supply if _finite(total_supply) else computed_supply
    )
    out["wasde_total_use_estimate"] = total_use if _finite(total_use) else computed_use
    denominator = out["wasde_total_use_estimate"]
    out["wasde_stock_to_use_estimate"] = (
        ending_stocks / denominator
        if _finite(ending_stocks) and _finite(denominator) and float(denominator) != 0.0
        else np.nan
    )
    out["wasde_ending_stocks_to_use_estimate"] = out["wasde_stock_to_use_estimate"]
    out["wasde_release_sequence"] = current_release_sequence if current_release_sequence else np.nan
    out["wasde_visible_release_count"] = current_release_sequence if current_release_sequence else np.nan
    out["wasde_is_first_estimate"] = (
        1.0 if current_release_sequence == 1 else 0.0 if current_release_sequence else np.nan
    )
    out["wasde_is_latest_visible_release"] = 1.0 if current_release_sequence else np.nan
    first_release = base_visible["release_date"].min() if not base_visible.empty else pd.NaT
    out["wasde_months_since_first_forecast"] = (
        (as_of_date.year - first_release.year) * 12 + (as_of_date.month - first_release.month)
        if pd.notna(first_release) else np.nan
    )
    return out


def build_wasde_snapshot_dynamic_features(
    wasde_df: pd.DataFrame,
    snapshot_targets: pd.DataFrame,
    *,
    mapping_config: WasdeSnapshotMappingConfig | None = None,
    attributes: tuple[str, ...] = DEFAULT_ATTRIBUTES,
    min_history_years: int = 5,
) -> pd.DataFrame:
    """Build dynamic WASDE features at the snapshot target spine grain."""
    cfg = mapping_config or load_wasde_snapshot_mappings()
    spine = _snapshot_spine(snapshot_targets)
    if spine.empty:
        return pd.DataFrame(columns=[*DYNAMIC_FEATURE_ID_COLUMNS, *DYNAMIC_FEATURE_METADATA_COLUMNS])
    source = prepare_wasde_snapshot_feature_source(
        wasde_df,
        mapping_config=cfg,
        attributes=attributes,
    )
    allowed_pairs = spine[["wasde_commodity", "wasde_origin"]].drop_duplicates()
    source = source.merge(
        allowed_pairs,
        on=["wasde_commodity", "wasde_origin"],
        how="inner",
    )
    if not source.empty:
        max_years = (
            spine.groupby(["wasde_commodity", "wasde_origin"], sort=False)["target_market_year"]
            .max()
            .reset_index(name="max_target_market_year")
        )
        source = source.merge(max_years, on=["wasde_commodity", "wasde_origin"], how="left")
        source = source.loc[
            source["target_market_year"] <= source["max_target_market_year"]
        ].drop(columns=["max_target_market_year"])
    enriched = _enrich_source_revisions(source)
    release_features = _build_release_wide_features(
        enriched,
        attributes=attributes,
        min_history_years=min_history_years,
    )
    joined = spine.merge(
        release_features,
        left_on=["wasde_commodity", "wasde_origin", "target_market_year", "as_of_date"],
        right_on=["wasde_commodity", "wasde_origin", "target_market_year", "release_date"],
        how="left",
    )
    if "release_date" in joined.columns:
        joined = joined.drop(columns=["release_date"])
    return validate_wasde_snapshot_features(joined)


def validate_wasde_snapshot_features(features: pd.DataFrame) -> pd.DataFrame:
    """Validate dynamic WASDE feature rows and point-in-time release dates."""
    if features.empty:
        return pd.DataFrame(columns=[*DYNAMIC_FEATURE_ID_COLUMNS, *DYNAMIC_FEATURE_METADATA_COLUMNS])
    missing = set(DYNAMIC_FEATURE_ID_COLUMNS) - set(features.columns)
    if missing:
        raise ValueError(f"WASDE dynamic features missing ID columns: {sorted(missing)}")
    out = features.copy()
    out["as_of_date"] = pd.to_datetime(out["as_of_date"], errors="coerce")
    if "source_release_date_max" in out.columns:
        out["source_release_date_max"] = pd.to_datetime(
            out["source_release_date_max"], errors="coerce"
        )
        future = out.loc[
            out["source_release_date_max"].notna()
            & (out["source_release_date_max"] > out["as_of_date"])
        ]
        if not future.empty:
            raise ValueError(
                "WASDE dynamic features contain future source releases: "
                f"{future[DYNAMIC_FEATURE_ID_COLUMNS + ['source_release_date_max']].head(5).to_dict('records')}"
            )
    duplicates = out.duplicated(DYNAMIC_FEATURE_ID_COLUMNS, keep=False)
    if duplicates.any():
        conflicts = (
            out.loc[duplicates, DYNAMIC_FEATURE_ID_COLUMNS]
            .drop_duplicates()
            .sort_values(DYNAMIC_FEATURE_ID_COLUMNS)
            .to_dict("records")
        )
        raise ValueError(f"duplicate WASDE dynamic feature rows: {conflicts[:5]}")
    return out.sort_values(DYNAMIC_FEATURE_ID_COLUMNS).reset_index(drop=True)


def dynamic_feature_columns(features: pd.DataFrame) -> list[str]:
    """Return model feature columns, excluding identity and metadata columns."""
    excluded = set(DYNAMIC_FEATURE_ID_COLUMNS) | set(DYNAMIC_FEATURE_METADATA_COLUMNS)
    return [
        col for col in features.columns
        if col not in excluded and col.startswith("wasde_")
    ]


def build_wasde_feature_quality_report(features: pd.DataFrame) -> pd.DataFrame:
    """Summarize dynamic feature completeness and constancy."""
    columns = [
        "feature",
        "non_null_rate",
        "constant_rate",
        "min_as_of_date",
        "max_as_of_date",
        "attribute",
        "row_count",
        "source_release_count",
    ]
    if features.empty:
        return pd.DataFrame(columns=columns)
    feature_cols = dynamic_feature_columns(features)
    rows: list[dict[str, object]] = []
    source_release_count = (
        int(features["source_release_date_max"].nunique())
        if "source_release_date_max" in features.columns else 0
    )
    for feature in feature_cols:
        series = features[feature]
        parts = feature.removeprefix("wasde_").split("_")
        attribute = "_".join(parts[:2]) if parts[:2] in (["ending", "stocks"], ["domestic", "total"], ["total", "use"], ["total", "supply"]) else parts[0]
        rows.append({
            "feature": feature,
            "non_null_rate": float(series.notna().mean()) if len(series) else np.nan,
            "constant_rate": _constant_rate(series),
            "min_as_of_date": pd.to_datetime(features["as_of_date"]).min(),
            "max_as_of_date": pd.to_datetime(features["as_of_date"]).max(),
            "attribute": attribute,
            "row_count": int(len(features)),
            "source_release_count": source_release_count,
        })
    return pd.DataFrame(rows, columns=columns).sort_values("feature").reset_index(drop=True)
