"""Audit helpers for WASDE snapshot model-ready planning.

The Phase 0 snapshot audit is intentionally read-only.  It answers whether the
current WASDE/PSD/static-feature surfaces can support point-in-time snapshot
experiments before we build new model-ready matrices.
"""
from __future__ import annotations

import json
import re
from typing import Any

import numpy as np
import pandas as pd

from leviathan.common.config import load_yaml
from leviathan.model_datasets.psd_target_builder import build_psd_target_panel
from leviathan.model_datasets.psd_targets import load_psd_metric_targets

CORE_WASDE_ATTRIBUTES = (
    "production",
    "ending_stocks",
    "exports",
    "imports",
    "domestic_total",
    "total_use",
    "feed",
    "feed_residual",
)

FOCUS_WASDE_COMMODITIES = (
    "corn",
    "wheat",
    "rice",
    "soybeans",
    "soybean_meal",
    "soybean_oil",
)

FOCUS_REGION_ALIASES: dict[str, str] = {
    "us": "united_states",
    "u_s": "united_states",
    "united_states": "united_states",
    "brazil": "brazil",
    "argentina": "argentina",
    "ukraine": "ukraine",
    "china": "china",
    "european_union": "european_union",
    "eu": "european_union",
    "france": "france",
    "canada": "canada",
    "russia": "russia",
    "india": "india",
    "thailand": "thailand",
    "vietnam": "vietnam",
}

AGGREGATE_REGIONS = {
    "world",
    "total",
    "total_foreign",
    "foreign",
    "major_exporters",
    "major_importers",
    "selected_exporters",
    "selected_importers",
    "other_foreign",
    "other_countries",
}

STATIC_FEATURE_SETS_TO_AUDIT = (
    "corn_preseason_core",
    "preseason_physical",
    "inseason_weather_dense",
    "physical_flow",
    "crop_condition",
    "planting_incentives",
    "trade_competitiveness",
    "balance_sheet",
    "wasde_monthly_revision",
)


def _normalize_token(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def classify_wasde_region(region: object) -> dict[str, str]:
    """Classify a WASDE region string for mapping readiness."""
    normalized = _normalize_token(region)
    if not normalized:
        return {
            "normalized_region": "",
            "quality_class": "unknown_review_required",
            "recommended_origin": "",
            "reason": "blank_region",
        }

    alpha_count = sum(ch.isalpha() for ch in normalized)
    digit_count = sum(ch.isdigit() for ch in normalized)
    if alpha_count == 0 or (digit_count > alpha_count and digit_count >= 3):
        return {
            "normalized_region": normalized,
            "quality_class": "garbled_parser_artifact",
            "recommended_origin": "",
            "reason": "mostly_numeric_region",
        }

    if normalized in FOCUS_REGION_ALIASES:
        return {
            "normalized_region": normalized,
            "quality_class": "clean_origin",
            "recommended_origin": FOCUS_REGION_ALIASES[normalized],
            "reason": "known_focus_origin_alias",
        }

    if normalized in AGGREGATE_REGIONS or normalized.startswith("major_"):
        return {
            "normalized_region": normalized,
            "quality_class": "aggregate_region",
            "recommended_origin": "",
            "reason": "aggregate_region_not_contract_origin",
        }

    if digit_count > 0:
        return {
            "normalized_region": normalized,
            "quality_class": "unknown_review_required",
            "recommended_origin": "",
            "reason": "mixed_alpha_numeric_region",
        }

    return {
        "normalized_region": normalized,
        "quality_class": "unknown_review_required",
        "recommended_origin": normalized,
        "reason": "alphabetic_region_not_in_focus_aliases",
    }


def _year_start(value: object) -> float:
    match = re.search(r"\d{4}", str(value or ""))
    return float(match.group(0)) if match else np.nan


def prepare_wasde_frame(wasde: pd.DataFrame) -> pd.DataFrame:
    """Normalize WASDE columns needed by the audit."""
    out = wasde.copy()
    if out.empty:
        return out
    for col in ("commodity", "region", "attribute"):
        if col in out.columns:
            out[col] = out[col].astype(str).str.strip().str.lower()
    if "release_date" in out.columns:
        out["release_date"] = pd.to_datetime(out["release_date"], errors="coerce")
    if "marketing_year" in out.columns:
        out["marketing_year_start"] = out["marketing_year"].map(_year_start)
    if "estimate" in out.columns:
        out["estimate"] = pd.to_numeric(out["estimate"], errors="coerce")
    if "revision" in out.columns:
        out["revision"] = pd.to_numeric(out["revision"], errors="coerce")
    return out


def build_wasde_inventory(wasde: pd.DataFrame) -> pd.DataFrame:
    """Return commodity-level WASDE coverage and core-attribute counts."""
    source = prepare_wasde_frame(wasde)
    columns = [
        "commodity",
        "row_count",
        "release_date_count",
        "release_date_min",
        "release_date_max",
        "marketing_year_count",
        "marketing_year_min",
        "marketing_year_max",
        "region_count",
        "core_snapshot_key_count",
        "annual_region_year_attribute_key_count",
        *[f"{attribute}_row_count" for attribute in CORE_WASDE_ATTRIBUTES],
    ]
    if source.empty or "commodity" not in source.columns:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for commodity, group in source.groupby("commodity", dropna=False):
        release_dates = group.get("release_date", pd.Series(dtype="datetime64[ns]")).dropna()
        years = pd.to_numeric(
            group.get("marketing_year_start", pd.Series(dtype=float)), errors="coerce"
        ).dropna()
        attrs = group.get("attribute", pd.Series(dtype=str)).astype(str)
        core = group.loc[attrs.isin(set(CORE_WASDE_ATTRIBUTES))].copy()
        row: dict[str, object] = {
            "commodity": str(commodity),
            "row_count": int(len(group)),
            "release_date_count": int(release_dates.nunique()),
            "release_date_min": release_dates.min().date().isoformat()
            if not release_dates.empty else "",
            "release_date_max": release_dates.max().date().isoformat()
            if not release_dates.empty else "",
            "marketing_year_count": int(years.nunique()),
            "marketing_year_min": int(years.min()) if not years.empty else None,
            "marketing_year_max": int(years.max()) if not years.empty else None,
            "region_count": int(group["region"].nunique()) if "region" in group.columns else 0,
            "core_snapshot_key_count": int(
                len(core.drop_duplicates([
                    col for col in (
                        "release_date",
                        "commodity",
                        "region",
                        "marketing_year",
                        "attribute",
                    )
                    if col in core.columns
                ]))
            ) if not core.empty else 0,
            "annual_region_year_attribute_key_count": int(
                len(core.drop_duplicates([
                    col for col in ("commodity", "region", "marketing_year", "attribute")
                    if col in core.columns
                ]))
            ) if not core.empty else 0,
        }
        for attribute in CORE_WASDE_ATTRIBUTES:
            row[f"{attribute}_row_count"] = int((attrs == attribute).sum())
        rows.append(row)
    return pd.DataFrame(rows, columns=columns).sort_values("commodity").reset_index(drop=True)


def build_wasde_region_quality(
    wasde: pd.DataFrame,
    *,
    focus_commodities: tuple[str, ...] = FOCUS_WASDE_COMMODITIES,
) -> pd.DataFrame:
    """Return region quality rows by commodity and region."""
    source = prepare_wasde_frame(wasde)
    columns = [
        "commodity",
        "region",
        "normalized_region",
        "quality_class",
        "recommended_origin",
        "reason",
        "row_count",
        "release_date_count",
        "marketing_year_count",
        "attribute_count",
        "attributes",
    ]
    if source.empty or not {"commodity", "region"}.issubset(source.columns):
        return pd.DataFrame(columns=columns)

    source = source.loc[source["commodity"].isin(set(focus_commodities))].copy()
    rows: list[dict[str, object]] = []
    for (commodity, region), group in source.groupby(["commodity", "region"], dropna=False):
        classification = classify_wasde_region(region)
        attrs = sorted(group.get("attribute", pd.Series(dtype=str)).dropna().astype(str).unique())
        release_dates = group.get("release_date", pd.Series(dtype="datetime64[ns]")).dropna()
        years = pd.to_numeric(
            group.get("marketing_year_start", pd.Series(dtype=float)), errors="coerce"
        ).dropna()
        rows.append({
            "commodity": str(commodity),
            "region": str(region),
            **classification,
            "row_count": int(len(group)),
            "release_date_count": int(release_dates.nunique()),
            "marketing_year_count": int(years.nunique()),
            "attribute_count": len(attrs),
            "attributes": ",".join(attrs),
        })
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["commodity", "quality_class", "region"]
    ).reset_index(drop=True)


def build_wasde_region_mapping_candidates(region_quality: pd.DataFrame) -> pd.DataFrame:
    """Return clean origin candidates that can seed the mapping config."""
    if region_quality.empty:
        return pd.DataFrame(columns=[
            "commodity",
            "region",
            "recommended_origin",
            "row_count",
            "release_date_count",
            "marketing_year_count",
            "attributes",
        ])
    clean = region_quality.loc[region_quality["quality_class"] == "clean_origin"].copy()
    cols = [
        "commodity",
        "region",
        "recommended_origin",
        "row_count",
        "release_date_count",
        "marketing_year_count",
        "attributes",
    ]
    return clean[cols].sort_values(["commodity", "recommended_origin"]).reset_index(drop=True)


def _stress_mask(values: pd.Series, direction: str, threshold: float) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if direction == "higher_is_stress":
        return numeric >= threshold
    if direction == "two_sided":
        return numeric.abs() >= threshold
    return numeric <= -threshold


def _quintile_mask(values: pd.Series, direction: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric.dropna()
    if finite.empty:
        return pd.Series(False, index=values.index)
    if direction == "higher_is_stress":
        threshold = finite.quantile(0.80)
        return numeric >= threshold
    if direction == "two_sided":
        threshold = finite.abs().quantile(0.80)
        return numeric.abs() >= threshold
    threshold = finite.quantile(0.20)
    return numeric <= threshold


def build_psd_target_compatibility_audit(
    psd: pd.DataFrame,
    *,
    source_dataset_version: str,
    commodities: tuple[str, ...] | list[str] | set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build PSD target summary and stress-label balance rows."""
    config = load_psd_metric_targets()
    targets = build_psd_target_panel(
        psd,
        source_dataset_version=source_dataset_version,
        config=config,
        commodities=commodities,
    )
    summary_cols = [
        "commodity",
        "target_key",
        "target_family",
        "target_attribute",
        "row_count",
        "trainable_row_count",
        "origin_count",
        "market_year_min",
        "market_year_max",
        "mapping_confidence_counts",
        "target_status_counts",
    ]
    balance_cols = [
        "commodity",
        "target_key",
        "target_family",
        "target_attribute",
        "stress_event_direction",
        "threshold_type",
        "threshold_value",
        "row_count",
        "trainable_row_count",
        "positive_event_count",
        "positive_event_rate",
        "origin_count",
        "market_year_count",
    ]
    if targets.empty:
        return pd.DataFrame(columns=summary_cols), pd.DataFrame(columns=balance_cols)

    metric_direction = {
        key: metric.stress_event_direction
        for key, metric in config.metrics.items()
    }
    summary_rows: list[dict[str, object]] = []
    balance_rows: list[dict[str, object]] = []
    for (commodity, target_key), group in targets.groupby(["commodity", "target_key"], dropna=False):
        trainable = group.loc[group["is_trainable"].fillna(False).astype(bool)].copy()
        years = pd.to_numeric(group["target_market_year"], errors="coerce").dropna()
        summary_rows.append({
            "commodity": str(commodity),
            "target_key": str(target_key),
            "target_family": str(group["target_family"].dropna().iloc[0]),
            "target_attribute": str(group["target_attribute"].dropna().iloc[0]),
            "row_count": int(len(group)),
            "trainable_row_count": int(len(trainable)),
            "origin_count": int(group["country"].nunique()),
            "market_year_min": int(years.min()) if not years.empty else None,
            "market_year_max": int(years.max()) if not years.empty else None,
            "mapping_confidence_counts": json.dumps(
                group["mapping_confidence"].value_counts(dropna=False).to_dict(),
                sort_keys=True,
            ),
            "target_status_counts": json.dumps(
                group["target_status"].value_counts(dropna=False).to_dict(),
                sort_keys=True,
            ),
        })
        direction = metric_direction.get(str(target_key), "lower_is_stress")
        for threshold in (0.05, 0.10):
            events = _stress_mask(trainable["target_value"], direction, threshold)
            balance_rows.append({
                "commodity": str(commodity),
                "target_key": str(target_key),
                "target_family": str(group["target_family"].dropna().iloc[0]),
                "target_attribute": str(group["target_attribute"].dropna().iloc[0]),
                "stress_event_direction": direction,
                "threshold_type": f"fixed_{int(threshold * 100)}pct",
                "threshold_value": threshold,
                "row_count": int(len(group)),
                "trainable_row_count": int(len(trainable)),
                "positive_event_count": int(events.sum()),
                "positive_event_rate": float(events.mean()) if len(events) else np.nan,
                "origin_count": int(trainable["country"].nunique()) if len(trainable) else 0,
                "market_year_count": int(trainable["target_market_year"].nunique())
                if len(trainable) else 0,
            })
        quintile = _quintile_mask(trainable["target_value"], direction)
        balance_rows.append({
            "commodity": str(commodity),
            "target_key": str(target_key),
            "target_family": str(group["target_family"].dropna().iloc[0]),
            "target_attribute": str(group["target_attribute"].dropna().iloc[0]),
            "stress_event_direction": direction,
            "threshold_type": "history_quintile",
            "threshold_value": np.nan,
            "row_count": int(len(group)),
            "trainable_row_count": int(len(trainable)),
            "positive_event_count": int(quintile.sum()),
            "positive_event_rate": float(quintile.mean()) if len(quintile) else np.nan,
            "origin_count": int(trainable["country"].nunique()) if len(trainable) else 0,
            "market_year_count": int(trainable["target_market_year"].nunique())
            if len(trainable) else 0,
        })

    return (
        pd.DataFrame(summary_rows, columns=summary_cols)
        .sort_values(["commodity", "target_key"]).reset_index(drop=True),
        pd.DataFrame(balance_rows, columns=balance_cols)
        .sort_values(["commodity", "target_key", "threshold_type"]).reset_index(drop=True),
    )


def build_static_feature_reuse_audit(
    feature_sets_config: dict[str, Any] | None = None,
    *,
    feature_set_ids: tuple[str, ...] = STATIC_FEATURE_SETS_TO_AUDIT,
) -> pd.DataFrame:
    """Classify feature sets for snapshot reuse readiness."""
    config = feature_sets_config or load_yaml("configs/features/feature_sets.yaml")
    by_id = {
        str(item.get("id")): item
        for item in (config.get("feature_sets") or [])
        if item.get("id")
    }
    rows: list[dict[str, object]] = []
    for feature_set_id in feature_set_ids:
        spec = by_id.get(feature_set_id, {})
        components = spec.get("component_feature_sets") or []
        if feature_set_id in {"preseason_physical", "corn_preseason_core"}:
            decision = "safe_all_snapshots"
            availability = "annual_prior_or_preseason_context"
            stages = "preseason,early_season,midseason,late_season,post_harvest,finalization"
            reason = "Designed as preseason/lagged physical context."
        elif feature_set_id in {"planting_incentives", "trade_competitiveness"}:
            decision = "safe_all_snapshots"
            availability = "lagged_certified_economic_driver"
            stages = "preseason,early_season,midseason,late_season,post_harvest,finalization"
            reason = "Configured with min_lag_days and certified economic-driver policy."
        elif feature_set_id in {"inseason_weather_dense", "crop_condition", "physical_flow"}:
            decision = "stage_limited_requires_as_of_filter"
            availability = "inseason_observation_must_be_visible_by_snapshot"
            stages = "early_season,midseason,late_season,post_harvest,finalization"
            reason = "In-season source; safe only if observation/release date <= as_of_date."
        elif feature_set_id == "balance_sheet":
            decision = "safe_if_prior_marketing_year"
            availability = "prior_marketing_year_at_snapshot"
            stages = "preseason,early_season,midseason,late_season,post_harvest,finalization"
            reason = "Balance-sheet context must be prior or point-in-time visible."
        elif feature_set_id == "wasde_monthly_revision":
            decision = "dynamic_snapshot_feature_not_static_join"
            availability = "computed_from_wasde_release_rows"
            stages = "preseason,early_season,midseason,late_season,post_harvest,finalization"
            reason = "Should be recomputed at snapshot grain rather than joined as annual static."
        else:
            decision = "review_required"
            availability = "unknown"
            stages = ""
            reason = "Feature set is not part of the Phase 0 reuse allowlist."
        rows.append({
            "feature_set_id": feature_set_id,
            "exists": bool(spec),
            "decision": decision,
            "availability_policy": availability,
            "allowed_snapshot_stages": stages,
            "component_feature_sets": ",".join(str(item) for item in components),
            "allow_diagnostic": bool(spec.get("allow_diagnostic", False)),
            "min_lag_days": int(spec.get("min_lag_days", config.get("defaults", {}).get("min_lag_days", 0))),
            "reason": reason,
        })
    return pd.DataFrame(rows).sort_values("feature_set_id").reset_index(drop=True)


def build_phase0_audit_report(
    *,
    bucket: str,
    wasde_inventory: pd.DataFrame,
    region_quality: pd.DataFrame,
    mapping_candidates: pd.DataFrame,
    psd_target_audit: pd.DataFrame,
    target_class_balance: pd.DataFrame,
    static_feature_reuse: pd.DataFrame,
) -> dict[str, Any]:
    """Summarize Phase 0 audit outcomes for JSON/markdown reports."""
    corn = wasde_inventory.loc[wasde_inventory["commodity"] == "corn"]
    corn_release_count = int(corn["release_date_count"].iloc[0]) if not corn.empty else 0
    clean = region_quality.loc[region_quality["quality_class"] == "clean_origin"]
    garbled = region_quality.loc[region_quality["quality_class"] == "garbled_parser_artifact"]
    usable_corn_origins = sorted(
        mapping_candidates.loc[
            mapping_candidates["commodity"] == "corn", "recommended_origin"
        ].dropna().astype(str).unique()
    )
    corn_target_rows = int(
        psd_target_audit.loc[
            psd_target_audit["commodity"] == "corn_cbot", "trainable_row_count"
        ].sum()
    ) if not psd_target_audit.empty else 0
    stage_limited_sets = sorted(
        static_feature_reuse.loc[
            static_feature_reuse["decision"].str.contains("stage_limited", na=False),
            "feature_set_id",
        ].astype(str).tolist()
    )
    blockers: list[str] = []
    if corn_release_count < 100:
        blockers.append("corn_wasde_release_history_too_short")
    if len(usable_corn_origins) == 0:
        blockers.append("no_clean_corn_wasde_origins")
    if corn_target_rows == 0:
        blockers.append("no_trainable_corn_psd_targets")

    return {
        "bucket": bucket,
        "phase": "wasde_snapshot_phase0_audit",
        "wasde": {
            "commodity_count": int(len(wasde_inventory)),
            "corn_release_date_count": corn_release_count,
            "corn_usable_origins": usable_corn_origins,
            "clean_region_count": int(len(clean)),
            "garbled_region_count": int(len(garbled)),
        },
        "psd_targets": {
            "target_summary_rows": int(len(psd_target_audit)),
            "class_balance_rows": int(len(target_class_balance)),
            "corn_trainable_target_rows_total": corn_target_rows,
        },
        "static_features": {
            "audited_feature_set_count": int(len(static_feature_reuse)),
            "stage_limited_feature_sets": stage_limited_sets,
        },
        "phase1_recommendation": {
            "proceed": not blockers,
            "blockers": blockers,
            "recommended_first_surface": "corn_wasde_snapshot_solo",
            "notes": [
                "Use WASDE release snapshots for dynamic features.",
                "Reuse static annual features only after availability policy review.",
                "Group CV by contract/origin/target_market_year.",
            ],
        },
    }


def render_phase0_markdown(
    report: dict[str, Any],
    *,
    wasde_inventory: pd.DataFrame,
    region_quality: pd.DataFrame,
    psd_target_audit: pd.DataFrame,
    target_class_balance: pd.DataFrame,
    static_feature_reuse: pd.DataFrame,
) -> str:
    """Render a concise human-readable Phase 0 audit report."""
    def table(df: pd.DataFrame, cols: list[str], limit: int = 20) -> str:
        if df.empty:
            return "_No rows._"
        sub = df[cols].head(limit).fillna("").astype(str)
        header = "| " + " | ".join(cols) + " |"
        divider = "| " + " | ".join(["---"] * len(cols)) + " |"
        rows = [
            "| " + " | ".join(str(row[col]).replace("\n", " ") for col in cols) + " |"
            for _, row in sub.iterrows()
        ]
        return "\n".join([header, divider, *rows])

    recommendation = report["phase1_recommendation"]
    lines = [
        "# WASDE Snapshot Phase 0 Audit",
        "",
        "## Decision",
        "",
        f"- Proceed to Phase 1: `{recommendation['proceed']}`",
        f"- Blockers: `{', '.join(recommendation['blockers']) or 'none'}`",
        f"- Recommended first surface: `{recommendation['recommended_first_surface']}`",
        "",
        "## WASDE Inventory",
        "",
        table(
            wasde_inventory.sort_values("row_count", ascending=False),
            [
                "commodity",
                "row_count",
                "release_date_count",
                "marketing_year_count",
                "region_count",
                "core_snapshot_key_count",
            ],
            12,
        ),
        "",
        "## Region Quality",
        "",
        table(
            region_quality.groupby(["commodity", "quality_class"], as_index=False)
            .agg(region_count=("region", "nunique"), row_count=("row_count", "sum"))
            .sort_values(["commodity", "quality_class"]),
            ["commodity", "quality_class", "region_count", "row_count"],
            30,
        ),
        "",
        "## PSD Target Compatibility",
        "",
        table(
            psd_target_audit.loc[
                psd_target_audit["commodity"].isin([
                    "corn_cbot",
                    "soft_red_winter_wheat_cbot",
                    "rough_rice_cbot",
                    "soybeans_cbot",
                    "soybean_meal_cbot",
                    "soybean_oil_cbot",
                ])
            ],
            [
                "commodity",
                "target_key",
                "row_count",
                "trainable_row_count",
                "origin_count",
                "market_year_min",
                "market_year_max",
            ],
            36,
        ),
        "",
        "## Target Event Balance",
        "",
        table(
            target_class_balance.loc[
                (target_class_balance["commodity"] == "corn_cbot")
                & (target_class_balance["threshold_type"].isin([
                    "fixed_5pct",
                    "fixed_10pct",
                    "history_quintile",
                ]))
            ],
            [
                "commodity",
                "target_key",
                "stress_event_direction",
                "threshold_type",
                "trainable_row_count",
                "positive_event_count",
                "positive_event_rate",
            ],
            24,
        ),
        "",
        "## Static Feature Reuse",
        "",
        table(
            static_feature_reuse,
            [
                "feature_set_id",
                "decision",
                "availability_policy",
                "allowed_snapshot_stages",
            ],
            20,
        ),
        "",
        "## Notes",
        "",
        "- `silver/wasde` is the dynamic monthly release surface; raw WASDE cells must be",
        "  aggregated into snapshot features rather than used as one row per cell.",
        "- Current static gold/model-ready features can be reused where availability policy",
        "  is safe for the snapshot date.",
        "- Later CV must hold out whole contract/origin/market-year groups.",
    ]
    return "\n".join(lines) + "\n"
