"""Build PSD-first target panels from silver PSD balance-sheet rows."""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.model_datasets.psd_targets import (
    PSDMetricTargetConfig,
    PSDTargetMetric,
    load_psd_metric_targets,
)

PSD_TARGET_COLUMNS = [
    "source_dataset_version",
    "dataset_key",
    "commodity",
    "contract_key",
    "target_key",
    "target_title",
    "target_source",
    "target_family",
    "target_attribute",
    "target_source_table",
    "target_unit",
    "target_value_unit",
    "target_status",
    "mapping_confidence",
    "psd_source_slug",
    "psd_commodity",
    "psd_country",
    "origin_key",
    "origin_role",
    "country",
    "crop_year",
    "target_market_year",
    "actual_value",
    "target_value",
    "trend_prediction",
    "prior_year_value",
    "trailing_mean_prediction",
    "zero_anomaly_baseline",
    "prior_year_anomaly_baseline",
    "trailing_mean_anomaly_baseline",
    "trailing_trend_anomaly_baseline",
    "history_years",
    "is_trainable",
    "excluded_reason",
    "target_release_context",
    "target_observation_release_date",
    "target_source_vintage",
    "psd_mapping_sha",
]

PSD_REQUIRED_COLUMNS = {
    "leviathan_slug",
    "country",
    "market_year",
    "release_date",
}


def _finite(value: object) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except Exception:  # noqa: BLE001
        return False


def _pct_deviation(value: float | None, baseline: float | None) -> float:
    if not _finite(value) or not _finite(baseline):
        return np.nan
    baseline_f = float(baseline)
    if baseline_f == 0:
        return np.nan
    return (float(value) - baseline_f) / abs(baseline_f)


def _linear_prediction(years: np.ndarray, values: np.ndarray, year: float) -> float:
    if len(years) < 2 or len(np.unique(years)) < 2:
        return np.nan
    coeffs = np.polyfit(years.astype(float), values.astype(float), 1)
    return float(np.polyval(coeffs, float(year)))


def _required_metric_columns(config: PSDMetricTargetConfig) -> set[str]:
    return {metric.psd_attribute for metric in config.metrics.values() if metric.allowed_as_target}


def _validate_psd_frame(psd_df: pd.DataFrame, config: PSDMetricTargetConfig) -> pd.DataFrame:
    required = PSD_REQUIRED_COLUMNS | _required_metric_columns(config)
    missing = required - set(psd_df.columns)
    if missing:
        raise ValueError(f"PSD target source missing required columns: {sorted(missing)}")

    base = psd_df.copy()
    base["market_year"] = pd.to_numeric(base["market_year"], errors="coerce")
    base["release_date"] = pd.to_datetime(base["release_date"], errors="coerce")
    if base["market_year"].isna().any():
        raise ValueError("PSD target source contains invalid market_year values")
    if base["release_date"].isna().any():
        raise ValueError("PSD target source contains invalid release_date values")

    natural_key = ["leviathan_slug", "country", "market_year", "release_date"]
    exact_count = len(base)
    base = base.drop_duplicates().reset_index(drop=True)
    if len(base) < exact_count:
        base = base.copy()

    conflict_mask = base.duplicated(natural_key, keep=False)
    if conflict_mask.any():
        conflicts = (
            base.loc[conflict_mask, natural_key]
            .drop_duplicates()
            .sort_values(natural_key)
            .to_dict("records")
        )
        raise ValueError(f"PSD target source has conflicting duplicate rows: {conflicts[:5]}")
    return base


def _latest_release_rows(source: pd.DataFrame) -> pd.DataFrame:
    ordered = source.sort_values(
        ["leviathan_slug", "country", "market_year", "release_date"]
    ).reset_index(drop=True)
    idx = ordered.groupby(
        ["leviathan_slug", "country", "market_year"], sort=False
    )["release_date"].idxmax()
    return ordered.loc[idx].sort_values(
        ["leviathan_slug", "country", "market_year"]
    ).reset_index(drop=True)


def _row_exclusion_reason(
    *,
    actual: float,
    history_years: int,
    min_history_years: int,
    trend_prediction: float,
    target_value: float,
    near_zero_trend_epsilon: float,
) -> str:
    if not _finite(actual):
        return "missing_actual"
    if history_years < min_history_years:
        return "insufficient_history"
    if not _finite(trend_prediction):
        return "missing_trend"
    if abs(float(trend_prediction)) <= near_zero_trend_epsilon:
        return "invalid_trend_denominator"
    if not _finite(target_value):
        return "invalid_target"
    return ""


def _build_metric_rows(
    metric_source: pd.DataFrame,
    *,
    metric: PSDTargetMetric,
    metadata: dict[str, object],
    min_history_years: int,
    near_zero_trend_epsilon: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    base = metric_source[
        ["target_market_year", "target_observation_release_date", metric.psd_attribute]
    ].copy()
    base = base.rename(columns={metric.psd_attribute: "actual_value"})
    base["target_market_year"] = pd.to_numeric(base["target_market_year"], errors="coerce")
    base["actual_value"] = pd.to_numeric(base["actual_value"], errors="coerce")
    base = base.sort_values("target_market_year").reset_index(drop=True)
    history = (
        base[["target_market_year", "actual_value"]]
        .dropna(subset=["target_market_year", "actual_value"])
        .sort_values("target_market_year")
    )
    by_year = {
        int(row.target_market_year): float(row.actual_value)
        for row in history.itertuples(index=False)
    }

    for row in base.itertuples(index=False):
        target_market_year = (
            int(row.target_market_year) if _finite(row.target_market_year) else None
        )
        actual = float(row.actual_value) if _finite(row.actual_value) else np.nan
        prior = (
            history.loc[history["target_market_year"] < target_market_year]
            if target_market_year is not None else history.iloc[0:0]
        )
        history_years = int(len(prior))
        prior_year_value = (
            by_year.get(target_market_year - 1) if target_market_year is not None else np.nan
        )
        trailing_mean = (
            float(prior["actual_value"].mean()) if history_years > 0 else np.nan
        )
        trend_prediction = (
            _linear_prediction(
                prior["target_market_year"].to_numpy(dtype=float),
                prior["actual_value"].to_numpy(dtype=float),
                float(target_market_year),
            )
            if history_years >= min_history_years and target_market_year is not None
            else np.nan
        )
        target_value = (
            _pct_deviation(actual, trend_prediction)
            if _finite(trend_prediction)
            and abs(float(trend_prediction)) > near_zero_trend_epsilon
            else np.nan
        )
        valid_trend_denominator = (
            _finite(trend_prediction)
            and abs(float(trend_prediction)) > near_zero_trend_epsilon
        )
        excluded_reason = _row_exclusion_reason(
            actual=actual,
            history_years=history_years,
            min_history_years=min_history_years,
            trend_prediction=trend_prediction,
            target_value=target_value,
            near_zero_trend_epsilon=near_zero_trend_epsilon,
        )

        release_date = row.target_observation_release_date
        output = {
            **metadata,
            "target_key": metric.target_key,
            "target_title": metadata["metric_titles"][metric.target_key],
            "target_family": metric.target_family,
            "target_attribute": metric.psd_attribute,
            "target_unit": metric.unit,
            "target_value_unit": metric.value_unit,
            "crop_year": target_market_year,
            "target_market_year": target_market_year,
            "actual_value": actual,
            "target_value": target_value,
            "trend_prediction": trend_prediction,
            "prior_year_value": prior_year_value,
            "trailing_mean_prediction": trailing_mean,
            "zero_anomaly_baseline": 0.0,
            "prior_year_anomaly_baseline": (
                _pct_deviation(prior_year_value, trend_prediction)
                if valid_trend_denominator else np.nan
            ),
            "trailing_mean_anomaly_baseline": (
                _pct_deviation(trailing_mean, trend_prediction)
                if valid_trend_denominator else np.nan
            ),
            "trailing_trend_anomaly_baseline": 0.0,
            "history_years": history_years,
            "is_trainable": excluded_reason == "",
            "excluded_reason": excluded_reason,
            "target_observation_release_date": release_date,
            "target_source_vintage": release_date,
        }
        output.pop("metric_titles", None)
        rows.append(output)
    return rows


def build_psd_target_panel(
    psd_df: pd.DataFrame,
    *,
    source_dataset_version: str,
    config: PSDMetricTargetConfig | None = None,
    commodities: list[str] | tuple[str, ...] | set[str] | None = None,
) -> pd.DataFrame:
    """Build PSD-first target rows from silver PSD data.

    The output is a long target table at contract/origin/market-year/target grain.
    It deliberately carries mapping status and confidence so proxy-derived target
    rows cannot be mistaken for clean contract-level truth.
    """
    cfg = config or load_psd_metric_targets()
    source = _validate_psd_frame(psd_df, cfg)
    latest = _latest_release_rows(source)
    defaults = cfg.raw.get("defaults") or {}
    source_meta = cfg.raw.get("source") or {}
    dataset_key = str(defaults.get("dataset_key") or "psd_snd_anomaly")
    min_history_years = int(defaults.get("min_history_years", 5))
    near_zero_trend_epsilon = float(defaults.get("near_zero_trend_epsilon", 1e-9))
    target_release_context = str(
        defaults.get("target_release_context") or "latest_available_psd_release"
    )
    selected_commodities = set(commodities or cfg.contract_mappings)

    rows: list[dict[str, object]] = []
    raw_metric_titles = {
        str(item.get("target_key")): str(item.get("title") or item.get("target_key"))
        for item in (cfg.raw.get("target_metrics") or [])
    }
    metric_titles = {
        metric.target_key: raw_metric_titles.get(metric.target_key, metric.target_key)
        for metric in cfg.metrics.values()
    }

    for contract_key in sorted(selected_commodities):
        mapping = cfg.contract_mappings.get(contract_key)
        if mapping is None:
            raise ValueError(f"unknown PSD contract mapping: {contract_key}")
        if not mapping.is_trainable_target:
            continue
        if not mapping.psd_source_slug:
            continue

        contract_rows = latest.loc[latest["leviathan_slug"] == mapping.psd_source_slug]
        if contract_rows.empty:
            continue

        for origin in mapping.target_origins:
            origin_key = str(origin.get("origin_key") or "")
            psd_country = str(origin.get("psd_country") or "")
            origin_role = str(origin.get("role") or "")
            if not origin_key or not psd_country:
                raise ValueError(f"{contract_key}: target origin missing origin_key/psd_country")

            origin_rows = contract_rows.loc[contract_rows["country"] == psd_country].copy()
            if origin_rows.empty:
                continue
            origin_rows["target_market_year"] = origin_rows["market_year"].astype(int)
            origin_rows["target_observation_release_date"] = origin_rows["release_date"]

            metadata = {
                "source_dataset_version": source_dataset_version,
                "dataset_key": dataset_key,
                "commodity": contract_key,
                "contract_key": contract_key,
                "target_source": "psd",
                "target_source_table": str(source_meta.get("source_table") or "silver_psd"),
                "target_status": mapping.target_status,
                "mapping_confidence": mapping.mapping_confidence,
                "psd_source_slug": mapping.psd_source_slug,
                "psd_commodity": mapping.psd_commodity,
                "psd_country": psd_country,
                "origin_key": origin_key,
                "origin_role": origin_role,
                "country": origin_key,
                "target_release_context": target_release_context,
                "psd_mapping_sha": cfg.config_sha,
                "metric_titles": metric_titles,
            }

            for target_key in mapping.allowed_targets:
                metric = cfg.metrics[target_key]
                if not metric.allowed_as_target:
                    continue
                rows.extend(
                    _build_metric_rows(
                        origin_rows,
                        metric=metric,
                        metadata=metadata,
                        min_history_years=min_history_years,
                        near_zero_trend_epsilon=near_zero_trend_epsilon,
                    )
                )

    if not rows:
        return pd.DataFrame(columns=PSD_TARGET_COLUMNS)
    return pd.DataFrame(rows, columns=PSD_TARGET_COLUMNS).sort_values(
        ["commodity", "origin_key", "target_key", "target_market_year"]
    ).reset_index(drop=True)
