"""Build point-in-time WASDE snapshot target rows."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from leviathan.model_datasets.psd_target_builder import build_psd_target_panel
from leviathan.model_datasets.psd_targets import (
    PSDContractTargetMapping,
    PSDMetricTargetConfig,
    load_psd_metric_targets,
)
from leviathan.model_datasets.schema_columns import (
    WASDE_SNAPSHOT_GROUP_KEY as GROUP_KEY,
)
from leviathan.model_datasets.schema_columns import (
    WASDE_SNAPSHOT_NATURAL_KEY as NATURAL_KEY,
)
from leviathan.model_datasets.schema_columns import (
    WASDE_SNAPSHOT_TARGET_COLUMNS,
)
from leviathan.model_datasets.wasde_snapshot_mapping import (
    WasdeSnapshotMappingConfig,
    WasdeSnapshotSurface,
    load_wasde_snapshot_mappings,
    normalize_wasde_token,
)

SNAPSHOT_POLICY = "wasde_release_month_v1"


@dataclass(frozen=True)
class SnapshotTargetSpec:
    contract_key: str
    wasde_commodity: str
    origin_key: str
    psd_mapping: PSDContractTargetMapping
    psd_country: str
    origin_role: str
    surface_role: str


def _finite(value: object) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except Exception:  # noqa: BLE001
        return False


def _year_start(value: object) -> int | None:
    match = re.search(r"\d{4}", str(value or ""))
    return int(match.group(0)) if match else None


def assign_snapshot_stage(as_of_date: object) -> str:
    """Assign a deterministic first-pass stage from a WASDE release month."""
    ts = pd.Timestamp(as_of_date)
    month = int(ts.month)
    if month in {5, 6}:
        return "preseason"
    if month in {7, 8}:
        return "early_season"
    if month in {9, 10}:
        return "midseason"
    if month in {11, 12}:
        return "late_season"
    if month in {1, 2}:
        return "post_harvest"
    return "finalization"


def _metric_title_lookup(psd_config: PSDMetricTargetConfig) -> dict[str, str]:
    return {
        str(item.get("target_key")): str(item.get("title") or item.get("target_key"))
        for item in (psd_config.raw.get("target_metrics") or [])
    }


def _origin_metadata(
    mapping: PSDContractTargetMapping,
    origin_key: str,
) -> tuple[str, str]:
    for origin in mapping.target_origins:
        if normalize_wasde_token(origin.get("origin_key")) == origin_key:
            return str(origin.get("psd_country") or ""), str(origin.get("role") or "")
    raise ValueError(f"{mapping.contract_key}: origin {origin_key!r} missing from PSD mapping")


def _target_specs_for_surface(
    surface: WasdeSnapshotSurface,
    *,
    psd_config: PSDMetricTargetConfig,
) -> list[SnapshotTargetSpec]:
    specs: list[SnapshotTargetSpec] = []
    if surface.surface_type in {"solo_contract", "contract_with_substitutes"}:
        mapping = psd_config.contract_mappings[surface.primary_contract]
        for origin in surface.target_origins:
            psd_country, origin_role = _origin_metadata(mapping, origin.origin_key)
            specs.append(
                SnapshotTargetSpec(
                    contract_key=surface.primary_contract,
                    wasde_commodity=surface.primary_wasde_commodity,
                    origin_key=origin.origin_key,
                    psd_mapping=mapping,
                    psd_country=psd_country,
                    origin_role=origin_role,
                    surface_role=origin.role,
                )
            )
        return specs

    if surface.surface_type == "segment":
        for member in surface.active_segment_members:
            mapping = psd_config.contract_mappings[member.contract_key]
            for origin_key in member.origins:
                origin_norm = normalize_wasde_token(origin_key)
                psd_country, origin_role = _origin_metadata(mapping, origin_norm)
                specs.append(
                    SnapshotTargetSpec(
                        contract_key=member.contract_key,
                        wasde_commodity=member.wasde_commodity,
                        origin_key=origin_norm,
                        psd_mapping=mapping,
                        psd_country=psd_country,
                        origin_role=origin_role,
                        surface_role="segment_member",
                    )
                )
        return specs

    raise ValueError(f"{surface.dataset_key}: unsupported surface_type {surface.surface_type!r}")


def _prepare_wasde_frame(
    wasde_df: pd.DataFrame,
    *,
    mapping_config: WasdeSnapshotMappingConfig,
) -> pd.DataFrame:
    required = {"release_date", "commodity", "region", "marketing_year"}
    missing = required - set(wasde_df.columns)
    if missing:
        raise ValueError(f"WASDE snapshot source missing required columns: {sorted(missing)}")
    source = wasde_df.copy()
    source["release_date"] = pd.to_datetime(source["release_date"], errors="coerce")
    source["wasde_commodity"] = source["commodity"].map(normalize_wasde_token)
    source["wasde_region"] = source["region"].map(normalize_wasde_token)
    source["wasde_origin"] = source["wasde_region"].map(
        lambda value: mapping_config.region_aliases.get(value, value)
    )
    source["target_market_year"] = source["marketing_year"].map(_year_start)
    if "attribute" in source.columns:
        source["attribute"] = source["attribute"].map(normalize_wasde_token)
        core_attrs = set(mapping_config.core_attributes)
        if core_attrs:
            source = source.loc[source["attribute"].isin(core_attrs)].copy()
    source = source.dropna(subset=["release_date", "target_market_year"]).copy()
    source["target_market_year"] = source["target_market_year"].astype(int)
    return source


def _snapshot_keys_for_specs(
    wasde_df: pd.DataFrame,
    specs: list[SnapshotTargetSpec],
    *,
    mapping_config: WasdeSnapshotMappingConfig,
) -> pd.DataFrame:
    source = _prepare_wasde_frame(wasde_df, mapping_config=mapping_config)
    if source.empty or not specs:
        return pd.DataFrame(
            columns=[
                "contract_key",
                "wasde_commodity",
                "wasde_origin",
                "target_market_year",
                "as_of_date",
                "wasde_region",
            ]
        )
    allowed = pd.DataFrame(
        [
            {
                "contract_key": spec.contract_key,
                "wasde_commodity": spec.wasde_commodity,
                "wasde_origin": spec.origin_key,
            }
            for spec in specs
        ]
    ).drop_duplicates()
    matched = source.merge(
        allowed,
        on=["wasde_commodity", "wasde_origin"],
        how="inner",
    )
    if matched.empty:
        return pd.DataFrame(
            columns=[
                "contract_key",
                "wasde_commodity",
                "wasde_origin",
                "target_market_year",
                "as_of_date",
                "wasde_region",
            ]
        )
    keys = (
        matched.rename(columns={"release_date": "as_of_date"})
        .sort_values(
            [
                "contract_key",
                "wasde_commodity",
                "wasde_origin",
                "target_market_year",
                "as_of_date",
                "wasde_region",
            ]
        )
        .drop_duplicates(
            [
                "contract_key",
                "wasde_commodity",
                "wasde_origin",
                "target_market_year",
                "as_of_date",
            ]
        )[
            [
                "contract_key",
                "wasde_commodity",
                "wasde_origin",
                "target_market_year",
                "as_of_date",
                "wasde_region",
            ]
        ]
        .reset_index(drop=True)
    )
    return keys


def _event_threshold(
    *,
    target_value: object,
    threshold_type: str,
    direction: str,
    prior_values: pd.Series,
) -> tuple[float, bool | None, str]:
    if not _finite(target_value):
        return np.nan, None, "missing_target_value"
    value = float(target_value)
    if threshold_type == "fixed_5pct":
        threshold = 0.05
    elif threshold_type == "fixed_10pct":
        threshold = 0.10
    elif threshold_type == "history_quintile":
        prior = pd.to_numeric(prior_values, errors="coerce").dropna()
        if len(prior) < 5:
            return np.nan, None, "insufficient_prior_history_for_quintile"
        if direction == "lower_is_stress":
            threshold = float(prior.quantile(0.20))
        elif direction == "higher_is_stress":
            threshold = float(prior.quantile(0.80))
        else:
            threshold = float(prior.abs().quantile(0.80))
    else:
        raise ValueError(
            "target_event_threshold_type must be one of fixed_5pct, fixed_10pct, history_quintile"
        )

    if direction == "lower_is_stress":
        return (
            threshold,
            bool(
                value <= -threshold if threshold_type.startswith("fixed_") else value <= threshold
            ),
            "",
        )
    if direction == "higher_is_stress":
        return threshold, bool(value >= threshold), ""
    if direction == "two_sided":
        return threshold, bool(abs(value) >= threshold), ""
    raise ValueError(f"unsupported target_event_direction: {direction!r}")


def build_event_labels(
    targets: pd.DataFrame,
    *,
    psd_config: PSDMetricTargetConfig,
    target_event_threshold_type: str = "fixed_10pct",
) -> pd.DataFrame:
    """Add event labels to annual target rows before snapshot expansion."""
    if targets.empty:
        return targets.copy()
    out = targets.copy()
    metric_direction = {
        key: metric.stress_event_direction for key, metric in psd_config.metrics.items()
    }
    out["target_event_direction"] = out["target_key"].map(metric_direction).fillna("")
    out["target_event_threshold_type"] = target_event_threshold_type
    out["target_event_threshold"] = np.nan
    out["target_event_label"] = pd.Series(pd.array([pd.NA] * len(out), dtype="boolean"))
    out["target_event_definition"] = ""

    history_key = ["contract_key", "origin_key", "target_key"]
    ordered = out.sort_values([*history_key, "target_market_year"]).copy()
    for idx, row in ordered.iterrows():
        prior = ordered.loc[
            (ordered["contract_key"] == row["contract_key"])
            & (ordered["origin_key"] == row["origin_key"])
            & (ordered["target_key"] == row["target_key"])
            & (ordered["target_market_year"] < row["target_market_year"])
            & (ordered["is_trainable"].astype(bool)),
            "target_value",
        ]
        threshold, label, reason = _event_threshold(
            target_value=row["target_value"],
            threshold_type=target_event_threshold_type,
            direction=str(row["target_event_direction"]),
            prior_values=prior,
        )
        out.at[idx, "target_event_threshold"] = threshold
        if label is not None:
            out.at[idx, "target_event_label"] = bool(label)
            out.at[idx, "target_event_definition"] = (
                f"{row['target_key']} {row['target_event_direction']} {target_event_threshold_type}"
            )
        else:
            out.at[idx, "target_event_definition"] = reason
    return out


def _metadata_rows_for_specs(
    specs: list[SnapshotTargetSpec],
    *,
    psd_config: PSDMetricTargetConfig,
    mapping_config: WasdeSnapshotMappingConfig,
    source_dataset_version: str,
    dataset_key: str,
    commodity_group: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    metric_titles = _metric_title_lookup(psd_config)
    for spec in specs:
        mapping = spec.psd_mapping
        for target_key in mapping.allowed_targets:
            metric = psd_config.metrics[target_key]
            rows.append(
                {
                    "source_dataset_version": source_dataset_version,
                    "dataset_key": dataset_key,
                    "contract_key": spec.contract_key,
                    "commodity": spec.contract_key,
                    "commodity_group": commodity_group,
                    "origin": spec.origin_key,
                    "origin_key": spec.origin_key,
                    "target_key": target_key,
                    "target_title": metric_titles.get(target_key, target_key),
                    "target_family": metric.target_family,
                    "target_attribute": metric.psd_attribute,
                    "target_source": "psd",
                    "target_status": mapping.target_status,
                    "mapping_confidence": mapping.mapping_confidence,
                    "psd_source_slug": mapping.psd_source_slug,
                    "psd_commodity": mapping.psd_commodity,
                    "psd_country": spec.psd_country,
                    "origin_role": spec.origin_role,
                    "wasde_commodity": spec.wasde_commodity,
                    "wasde_origin": spec.origin_key,
                    "psd_mapping_sha": psd_config.config_sha,
                    "wasde_mapping_sha": mapping_config.config_sha,
                }
            )
    return pd.DataFrame(rows)


def expand_psd_targets_to_wasde_snapshots(
    psd_targets: pd.DataFrame,
    wasde_df: pd.DataFrame,
    *,
    dataset_key: str,
    source_dataset_version: str,
    mapping_config: WasdeSnapshotMappingConfig,
    psd_config: PSDMetricTargetConfig,
    target_event_threshold_type: str = "fixed_10pct",
) -> pd.DataFrame:
    """Expand annual PSD targets onto valid WASDE release snapshots."""
    surface = mapping_config.surfaces.get(dataset_key)
    if surface is None:
        raise KeyError(f"unknown WASDE snapshot dataset_key: {dataset_key}")
    specs = _target_specs_for_surface(surface, psd_config=psd_config)
    snapshot_keys = _snapshot_keys_for_specs(
        wasde_df,
        specs,
        mapping_config=mapping_config,
    )
    if snapshot_keys.empty:
        return pd.DataFrame(columns=WASDE_SNAPSHOT_TARGET_COLUMNS)

    metadata = _metadata_rows_for_specs(
        specs,
        psd_config=psd_config,
        mapping_config=mapping_config,
        source_dataset_version=source_dataset_version,
        dataset_key=dataset_key,
        commodity_group=surface.commodity_group,
    )
    scaffold = snapshot_keys.merge(
        metadata,
        left_on=["contract_key", "wasde_commodity", "wasde_origin"],
        right_on=["contract_key", "wasde_commodity", "wasde_origin"],
        how="inner",
    )

    targets = psd_targets.copy()
    if not targets.empty:
        targets = targets.rename(columns={"dataset_key": "annual_target_dataset_key"})
        targets = build_event_labels(
            targets,
            psd_config=psd_config,
            target_event_threshold_type=target_event_threshold_type,
        )

    join_cols = ["contract_key", "origin_key", "target_market_year", "target_key"]
    joined = scaffold.merge(
        targets,
        on=join_cols,
        how="left",
        suffixes=("", "_target"),
    )

    for col in (
        "target_value",
        "actual_value",
        "trend_prediction",
        "prior_year_value",
        "trailing_mean_prediction",
        "zero_anomaly_baseline",
        "prior_year_anomaly_baseline",
        "trailing_mean_anomaly_baseline",
        "trailing_trend_anomaly_baseline",
        "history_years",
        "target_observation_release_date",
        "target_source_vintage",
        "target_event_label",
        "target_event_threshold",
        "target_event_threshold_type",
        "target_event_direction",
        "target_event_definition",
    ):
        if col not in joined.columns:
            joined[col] = np.nan

    joined["target_available"] = joined["actual_value"].notna()
    joined["snapshot_available"] = joined["as_of_date"].notna()
    metric_direction = {
        key: metric.stress_event_direction for key, metric in psd_config.metrics.items()
    }
    joined["target_event_threshold_type"] = joined["target_event_threshold_type"].fillna(
        target_event_threshold_type
    )
    joined["target_event_direction"] = joined["target_event_direction"].fillna(
        joined["target_key"].map(metric_direction)
    )
    joined["crop_year"] = joined["target_market_year"]
    joined["target_anomaly_pct"] = joined["target_value"]
    joined["as_of_date"] = pd.to_datetime(joined["as_of_date"])
    joined["snapshot_stage"] = joined["as_of_date"].map(assign_snapshot_stage)
    joined["snapshot_month_code"] = joined["as_of_date"].dt.month.astype(int)
    joined["snapshot_policy"] = SNAPSHOT_POLICY
    joined["cv_time"] = pd.to_numeric(joined["target_market_year"], errors="coerce").astype("Int64")
    joined["cv_group"] = (
        joined["contract_key"].astype(str)
        + "|"
        + joined["origin_key"].astype(str)
        + "|"
        + joined["target_market_year"].astype(str)
    )

    joined = joined.sort_values([*GROUP_KEY, "as_of_date"]).reset_index(drop=True)
    joined["snapshot_sequence"] = joined.groupby(GROUP_KEY).cumcount() + 1
    joined["snapshot_count"] = joined.groupby(GROUP_KEY)["as_of_date"].transform("nunique")
    joined["wasde_release_count_for_group"] = joined["snapshot_count"]
    joined["sample_weight"] = 1.0 / joined["snapshot_count"].astype(float)

    target_is_trainable = (
        joined["is_trainable"].where(joined["is_trainable"].notna(), False).astype(bool)
        if "is_trainable" in joined.columns
        else pd.Series(False, index=joined.index)
    )
    joined["excluded_reason"] = joined.get("excluded_reason", "").fillna("").astype(str)
    missing_target = ~joined["target_available"]
    joined.loc[missing_target, "excluded_reason"] = "missing_target"
    joined["is_trainable"] = target_is_trainable & joined["snapshot_available"] & ~missing_target

    return validate_snapshot_target_rows(joined.reindex(columns=WASDE_SNAPSHOT_TARGET_COLUMNS))


def build_wasde_snapshot_target_rows(
    psd_df: pd.DataFrame,
    wasde_df: pd.DataFrame,
    *,
    source_dataset_version: str,
    dataset_key: str = "corn_wasde_snapshot_solo",
    mapping_config: WasdeSnapshotMappingConfig | None = None,
    psd_config: PSDMetricTargetConfig | None = None,
    target_event_threshold_type: str = "fixed_10pct",
) -> pd.DataFrame:
    """Build point-in-time snapshot target rows for a mapped WASDE surface."""
    wasde_mapping = mapping_config or load_wasde_snapshot_mappings()
    psd_targets = psd_config or load_psd_metric_targets()
    surface = wasde_mapping.surfaces.get(dataset_key)
    if surface is None:
        raise KeyError(f"unknown WASDE snapshot dataset_key: {dataset_key}")
    specs = _target_specs_for_surface(surface, psd_config=psd_targets)
    contracts = sorted({spec.contract_key for spec in specs})
    annual_targets = build_psd_target_panel(
        psd_df,
        source_dataset_version=source_dataset_version,
        config=psd_targets,
        commodities=contracts,
    )
    return expand_psd_targets_to_wasde_snapshots(
        annual_targets,
        wasde_df,
        dataset_key=dataset_key,
        source_dataset_version=source_dataset_version,
        mapping_config=wasde_mapping,
        psd_config=psd_targets,
        target_event_threshold_type=target_event_threshold_type,
    )


def validate_snapshot_target_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """Validate snapshot target rows and return a sorted copy."""
    if rows.empty:
        return pd.DataFrame(columns=WASDE_SNAPSHOT_TARGET_COLUMNS)
    missing = set(WASDE_SNAPSHOT_TARGET_COLUMNS) - set(rows.columns)
    if missing:
        raise ValueError(f"WASDE snapshot targets missing columns: {sorted(missing)}")

    out = rows.copy()
    out["as_of_date"] = pd.to_datetime(out["as_of_date"], errors="coerce")
    duplicate_mask = out.duplicated(NATURAL_KEY, keep=False)
    if duplicate_mask.any():
        conflicts = (
            out.loc[duplicate_mask, NATURAL_KEY]
            .drop_duplicates()
            .sort_values(NATURAL_KEY)
            .to_dict("records")
        )
        raise ValueError(f"duplicate WASDE snapshot target rows: {conflicts[:5]}")

    for key, group in out.groupby(GROUP_KEY, dropna=False):
        count = int(group["as_of_date"].nunique())
        if count <= 0:
            raise ValueError(f"{key}: snapshot group has no as_of_date")
        if not np.isclose(float(group["sample_weight"].sum()), 1.0, atol=1e-9):
            raise ValueError(f"{key}: sample_weight must sum to 1.0")
        for col in ("target_value", "actual_value", "target_event_label"):
            if col not in group.columns:
                continue
            non_null = group[col].dropna()
            if non_null.nunique() > 1:
                raise ValueError(f"{key}: {col} changes across snapshots")

    bad_cv = out.loc[
        out["cv_group"].astype(str).str.contains(r"\d{4}-\d{2}-\d{2}", regex=True, na=False)
    ]
    if not bad_cv.empty:
        raise ValueError("cv_group must not include month/day snapshot dates")

    return out.sort_values(NATURAL_KEY).reset_index(drop=True)
