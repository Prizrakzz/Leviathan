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
    "beginning_stocks",
    "total_supply",
)

STOCK_TO_USE_COMPONENT_ATTRIBUTES = (
    "ending_stocks",
    "total_use",
    "domestic_total",
    "exports",
)

SOURCE_TRUTH_NATURAL_KEY = (
    "release_date",
    "commodity",
    "normalized_origin",
    "marketing_year_start",
    "attribute",
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

    numeric_fragments = re.findall(r"(?:^|_)(\d+)(?=_|$)", normalized)
    alpha_prefix = re.sub(r"(?:_\d+)+$", "", normalized)
    if (
        len(numeric_fragments) >= 2
        or (
            numeric_fragments
            and alpha_prefix in FOCUS_REGION_ALIASES
            and normalized != alpha_prefix
        )
    ):
        return {
            "normalized_region": normalized,
            "quality_class": "garbled_parser_artifact",
            "recommended_origin": "",
            "reason": "numeric_parser_fragment_region",
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
    if "region" in out.columns:
        classifications = out["region"].map(classify_wasde_region)
        out["normalized_region"] = [
            item.get("normalized_region", "") for item in classifications
        ]
        out["region_quality_class"] = [
            item.get("quality_class", "unknown_review_required")
            for item in classifications
        ]
        out["normalized_origin"] = [
            item.get("recommended_origin") or item.get("normalized_region", "")
            for item in classifications
        ]
        out["region_quality_reason"] = [
            item.get("reason", "") for item in classifications
        ]
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


def _coverage_class(
    *,
    quality_class: str,
    market_year_count: int,
    median_releases_per_year: float,
    estimate_coverage_rate: float,
    revision_coverage_rate: float,
) -> tuple[str, str]:
    """Classify whether a source slice can support core snapshot features."""
    if quality_class == "garbled_parser_artifact":
        return "blocked_parser_artifact", "blocked"
    if quality_class == "aggregate_region":
        return "diagnostic_only", "aggregate_context_not_target_origin"
    if quality_class == "unknown_review_required":
        return "blocked_mapping_gap", "blocked"
    if market_year_count < 5:
        return "blocked_insufficient_history", "blocked"
    if (
        market_year_count >= 10
        and median_releases_per_year >= 4.0
        and estimate_coverage_rate >= 0.80
    ):
        return "core_model_feature", "core"
    if market_year_count >= 5 and estimate_coverage_rate >= 0.50:
        if revision_coverage_rate < 0.25:
            return "secondary_sparse_feature", "estimate_dense_revision_sparse"
        return "secondary_sparse_feature", "secondary"
    return "diagnostic_only", "too_sparse_for_core"


def classify_wasde_coverage(row: pd.Series | dict[str, object]) -> str:
    """Return a source-truth coverage class for one summary row."""
    values = dict(row)
    quality = str(values.get("quality_class") or values.get("region_quality_class") or "")
    market_year_count = int(values.get("market_year_count") or 0)
    median_releases = float(values.get("median_releases_per_year") or 0.0)
    estimate_rate = float(values.get("estimate_coverage_rate") or 0.0)
    revision_rate = float(values.get("revision_coverage_rate") or 0.0)
    coverage_class, _ = _coverage_class(
        quality_class=quality,
        market_year_count=market_year_count,
        median_releases_per_year=median_releases,
        estimate_coverage_rate=estimate_rate,
        revision_coverage_rate=revision_rate,
    )
    return coverage_class


def _month_list(series: pd.Series) -> str:
    dates = pd.to_datetime(series, errors="coerce").dropna()
    if dates.empty:
        return ""
    return ",".join(str(int(month)) for month in sorted(dates.dt.month.unique()))


def _first_iso(series: pd.Series) -> str:
    values = pd.to_datetime(series, errors="coerce").dropna()
    return values.min().date().isoformat() if not values.empty else ""


def _last_iso(series: pd.Series) -> str:
    values = pd.to_datetime(series, errors="coerce").dropna()
    return values.max().date().isoformat() if not values.empty else ""


def _duplicate_counts(group: pd.DataFrame) -> tuple[int, int]:
    present_key = [col for col in SOURCE_TRUTH_NATURAL_KEY if col in group.columns]
    if not present_key:
        return 0, 0
    duplicate_cell_count = 0
    conflicting_duplicate_count = 0
    for _, cell in group.groupby(present_key, dropna=False):
        if len(cell) <= 1:
            continue
        duplicate_cell_count += int(len(cell) - 1)
        estimates = pd.to_numeric(cell.get("estimate", pd.Series(dtype=float)), errors="coerce")
        if estimates.nunique(dropna=True) > 1:
            conflicting_duplicate_count += int(len(cell))
    return duplicate_cell_count, conflicting_duplicate_count


def build_wasde_source_truth_audit(wasde: pd.DataFrame) -> pd.DataFrame:
    """Audit source coverage at commodity/origin/year/attribute grain.

    This keeps estimate and revision coverage separate. Sparse `revision` values
    should not automatically block dense latest-estimate features.
    """
    source = prepare_wasde_frame(wasde)
    columns = [
        "commodity",
        "region",
        "normalized_region",
        "normalized_origin",
        "quality_class",
        "marketing_year_start",
        "attribute",
        "row_count",
        "release_count",
        "first_release_date",
        "last_release_date",
        "estimate_non_null_count",
        "revision_non_null_count",
        "estimate_non_null_rate",
        "revision_non_null_rate",
        "first_estimate_release_date",
        "last_estimate_release_date",
        "release_months_present",
        "release_sequence_count",
        "table_type_count",
        "duplicate_cell_count",
        "conflicting_duplicate_count",
    ]
    required = {"commodity", "region", "marketing_year_start", "attribute"}
    if source.empty or not required.issubset(source.columns):
        return pd.DataFrame(columns=columns)

    frames: list[dict[str, object]] = []
    group_cols = [
        "commodity",
        "region",
        "normalized_region",
        "normalized_origin",
        "region_quality_class",
        "marketing_year_start",
        "attribute",
    ]
    for keys, group in source.groupby(group_cols, dropna=False, sort=True):
        (
            commodity,
            region,
            normalized_region,
            normalized_origin,
            quality_class,
            marketing_year_start,
            attribute,
        ) = keys
        release_dates = pd.to_datetime(group["release_date"], errors="coerce")
        estimates = pd.to_numeric(group.get("estimate", pd.Series(dtype=float)), errors="coerce")
        revisions = pd.to_numeric(group.get("revision", pd.Series(dtype=float)), errors="coerce")
        estimate_rows = group.loc[estimates.notna()]
        duplicate_count, conflict_count = _duplicate_counts(group)
        frames.append({
            "commodity": str(commodity),
            "region": str(region),
            "normalized_region": str(normalized_region),
            "normalized_origin": str(normalized_origin),
            "quality_class": str(quality_class),
            "marketing_year_start": (
                int(marketing_year_start)
                if pd.notna(marketing_year_start) else None
            ),
            "attribute": str(attribute),
            "row_count": int(len(group)),
            "release_count": int(release_dates.dropna().nunique()),
            "first_release_date": _first_iso(release_dates),
            "last_release_date": _last_iso(release_dates),
            "estimate_non_null_count": int(estimates.notna().sum()),
            "revision_non_null_count": int(revisions.notna().sum()),
            "estimate_non_null_rate": float(estimates.notna().mean()) if len(group) else 0.0,
            "revision_non_null_rate": float(revisions.notna().mean()) if len(group) else 0.0,
            "first_estimate_release_date": _first_iso(estimate_rows.get("release_date", pd.Series(dtype=str))),
            "last_estimate_release_date": _last_iso(estimate_rows.get("release_date", pd.Series(dtype=str))),
            "release_months_present": _month_list(release_dates),
            "release_sequence_count": int(release_dates.dropna().nunique()),
            "table_type_count": (
                int(group["table_type"].nunique(dropna=True))
                if "table_type" in group.columns else 0
            ),
            "duplicate_cell_count": duplicate_count,
            "conflicting_duplicate_count": conflict_count,
        })
    return pd.DataFrame(frames, columns=columns).sort_values(
        ["commodity", "normalized_origin", "marketing_year_start", "attribute"]
    ).reset_index(drop=True)


def build_release_sequence_coverage(
    source_truth: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize release-count distributions by commodity/origin/attribute."""
    columns = [
        "commodity",
        "normalized_origin",
        "attribute",
        "market_year_count",
        "release_count_total",
        "median_releases_per_year",
        "p10_releases_per_year",
        "p90_releases_per_year",
        "first_supported_market_year",
        "last_supported_market_year",
    ]
    if source_truth.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for (commodity, origin, attribute), group in source_truth.groupby(
        ["commodity", "normalized_origin", "attribute"],
        dropna=False,
        sort=True,
    ):
        years = pd.to_numeric(group["marketing_year_start"], errors="coerce").dropna()
        release_counts = pd.to_numeric(group["release_count"], errors="coerce").fillna(0)
        rows.append({
            "commodity": str(commodity),
            "normalized_origin": str(origin),
            "attribute": str(attribute),
            "market_year_count": int(years.nunique()),
            "release_count_total": int(release_counts.sum()),
            "median_releases_per_year": float(release_counts.median()) if len(release_counts) else 0.0,
            "p10_releases_per_year": float(release_counts.quantile(0.10)) if len(release_counts) else 0.0,
            "p90_releases_per_year": float(release_counts.quantile(0.90)) if len(release_counts) else 0.0,
            "first_supported_market_year": int(years.min()) if not years.empty else None,
            "last_supported_market_year": int(years.max()) if not years.empty else None,
        })
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["commodity", "normalized_origin", "attribute"]
    ).reset_index(drop=True)


def build_origin_attribute_coverage(
    source_truth: pd.DataFrame,
) -> pd.DataFrame:
    """Classify model-readiness by commodity/origin/attribute."""
    columns = [
        "commodity",
        "normalized_origin",
        "attribute",
        "quality_class",
        "market_year_count",
        "release_count_total",
        "median_releases_per_year",
        "p10_releases_per_year",
        "p90_releases_per_year",
        "estimate_coverage_rate",
        "revision_coverage_rate",
        "first_supported_market_year",
        "last_supported_market_year",
        "coverage_class",
        "recommended_use",
        "stock_to_use_constructible_year_count",
    ]
    if source_truth.empty:
        return pd.DataFrame(columns=columns)

    release_coverage = build_release_sequence_coverage(source_truth)
    rows: list[dict[str, object]] = []
    for (commodity, origin, attribute), group in source_truth.groupby(
        ["commodity", "normalized_origin", "attribute"],
        dropna=False,
        sort=True,
    ):
        release_row = release_coverage.loc[
            (release_coverage["commodity"] == commodity)
            & (release_coverage["normalized_origin"] == origin)
            & (release_coverage["attribute"] == attribute)
        ].iloc[0]
        quality = str(group["quality_class"].mode(dropna=True).iloc[0])
        row_count = int(group["row_count"].sum())
        estimate_count = int(group["estimate_non_null_count"].sum())
        revision_count = int(group["revision_non_null_count"].sum())
        estimate_rate = float(estimate_count / row_count) if row_count else 0.0
        revision_rate = float(revision_count / row_count) if row_count else 0.0
        coverage_class, recommended_use = _coverage_class(
            quality_class=quality,
            market_year_count=int(release_row["market_year_count"]),
            median_releases_per_year=float(release_row["median_releases_per_year"]),
            estimate_coverage_rate=estimate_rate,
            revision_coverage_rate=revision_rate,
        )
        rows.append({
            "commodity": str(commodity),
            "normalized_origin": str(origin),
            "attribute": str(attribute),
            "quality_class": quality,
            "market_year_count": int(release_row["market_year_count"]),
            "release_count_total": int(release_row["release_count_total"]),
            "median_releases_per_year": float(release_row["median_releases_per_year"]),
            "p10_releases_per_year": float(release_row["p10_releases_per_year"]),
            "p90_releases_per_year": float(release_row["p90_releases_per_year"]),
            "estimate_coverage_rate": estimate_rate,
            "revision_coverage_rate": revision_rate,
            "first_supported_market_year": release_row["first_supported_market_year"],
            "last_supported_market_year": release_row["last_supported_market_year"],
            "coverage_class": coverage_class,
            "recommended_use": recommended_use,
            "stock_to_use_constructible_year_count": 0,
        })
    coverage = pd.DataFrame(rows, columns=columns)
    constructible = build_stock_to_use_constructibility(source_truth)
    if not constructible.empty:
        counts = (
            constructible.loc[constructible["stock_to_use_constructible"]]
            .groupby(["commodity", "normalized_origin"], dropna=False)["marketing_year_start"]
            .nunique()
            .rename("stock_to_use_constructible_year_count")
            .reset_index()
        )
        coverage = coverage.drop(columns=["stock_to_use_constructible_year_count"]).merge(
            counts,
            on=["commodity", "normalized_origin"],
            how="left",
        )
        coverage["stock_to_use_constructible_year_count"] = (
            coverage["stock_to_use_constructible_year_count"].fillna(0).astype(int)
        )
    return coverage.sort_values(
        ["commodity", "normalized_origin", "attribute"]
    ).reset_index(drop=True)


def build_stock_to_use_constructibility(source_truth: pd.DataFrame) -> pd.DataFrame:
    """Report whether stock/use can be built by official total_use or components."""
    columns = [
        "commodity",
        "normalized_origin",
        "marketing_year_start",
        "has_ending_stocks",
        "has_total_use",
        "has_domestic_total",
        "has_exports",
        "stock_to_use_constructible",
        "stock_to_use_method",
    ]
    if source_truth.empty:
        return pd.DataFrame(columns=columns)
    attrs = source_truth.loc[
        source_truth["attribute"].isin(STOCK_TO_USE_COMPONENT_ATTRIBUTES)
    ].copy()
    if attrs.empty:
        return pd.DataFrame(columns=columns)
    flags = (
        attrs.assign(has_estimate=attrs["estimate_non_null_count"].astype(int) > 0)
        .pivot_table(
            index=["commodity", "normalized_origin", "marketing_year_start"],
            columns="attribute",
            values="has_estimate",
            aggfunc="max",
            fill_value=False,
        )
        .reset_index()
    )
    for attribute in STOCK_TO_USE_COMPONENT_ATTRIBUTES:
        if attribute not in flags.columns:
            flags[attribute] = False
    flags["has_ending_stocks"] = flags["ending_stocks"].astype(bool)
    flags["has_total_use"] = flags["total_use"].astype(bool)
    flags["has_domestic_total"] = flags["domestic_total"].astype(bool)
    flags["has_exports"] = flags["exports"].astype(bool)
    flags["stock_to_use_constructible"] = flags["has_ending_stocks"] & (
        flags["has_total_use"] | (flags["has_domestic_total"] & flags["has_exports"])
    )
    flags["stock_to_use_method"] = np.where(
        flags["has_ending_stocks"] & flags["has_total_use"],
        "official_total_use",
        np.where(
            flags["has_ending_stocks"]
            & flags["has_domestic_total"]
            & flags["has_exports"],
            "domestic_total_plus_exports",
            "",
        ),
    )
    return flags[columns].sort_values(
        ["commodity", "normalized_origin", "marketing_year_start"]
    ).reset_index(drop=True)


def build_parser_artifact_report(source_truth: pd.DataFrame) -> pd.DataFrame:
    """Return suspicious parser-artifact and duplicate-conflict slices."""
    columns = [
        "commodity",
        "region",
        "normalized_region",
        "normalized_origin",
        "quality_class",
        "attribute",
        "row_count",
        "release_count",
        "market_year_count",
        "duplicate_cell_count",
        "conflicting_duplicate_count",
        "reason",
    ]
    if source_truth.empty:
        return pd.DataFrame(columns=columns)
    grouped = source_truth.groupby(
        [
            "commodity",
            "region",
            "normalized_region",
            "normalized_origin",
            "quality_class",
            "attribute",
        ],
        dropna=False,
        sort=True,
    ).agg(
        row_count=("row_count", "sum"),
        release_count=("release_count", "sum"),
        market_year_count=("marketing_year_start", "nunique"),
        duplicate_cell_count=("duplicate_cell_count", "sum"),
        conflicting_duplicate_count=("conflicting_duplicate_count", "sum"),
    ).reset_index()
    suspect = grouped.loc[
        grouped["quality_class"].isin({"garbled_parser_artifact", "unknown_review_required"})
        | (grouped["conflicting_duplicate_count"] > 0)
    ].copy()
    if suspect.empty:
        return pd.DataFrame(columns=columns)
    suspect["reason"] = np.select(
        [
            suspect["quality_class"].eq("garbled_parser_artifact"),
            suspect["conflicting_duplicate_count"].gt(0),
            suspect["quality_class"].eq("unknown_review_required"),
        ],
        [
            "garbled_parser_artifact",
            "conflicting_duplicate_cells",
            "mapping_gap_review_required",
        ],
        default="review_required",
    )
    return suspect[columns].sort_values(
        ["commodity", "quality_class", "region", "attribute"]
    ).reset_index(drop=True)


def build_wasde_mapping_gaps(source_truth: pd.DataFrame) -> pd.DataFrame:
    """Return unknown non-aggregate regions with enough rows to review."""
    columns = [
        "commodity",
        "region",
        "normalized_region",
        "row_count",
        "release_count",
        "market_year_count",
        "attributes",
        "reason",
    ]
    if source_truth.empty:
        return pd.DataFrame(columns=columns)
    unknown = source_truth.loc[source_truth["quality_class"] == "unknown_review_required"].copy()
    if unknown.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for (commodity, region, normalized_region), group in unknown.groupby(
        ["commodity", "region", "normalized_region"], dropna=False, sort=True
    ):
        attrs = sorted(group["attribute"].dropna().astype(str).unique())
        rows.append({
            "commodity": str(commodity),
            "region": str(region),
            "normalized_region": str(normalized_region),
            "row_count": int(group["row_count"].sum()),
            "release_count": int(group["release_count"].sum()),
            "market_year_count": int(group["marketing_year_start"].nunique()),
            "attributes": ",".join(attrs),
            "reason": "unknown_non_aggregate_region",
        })
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["commodity", "row_count"],
        ascending=[True, False],
    ).reset_index(drop=True)


def build_phase1_source_truth_report(
    *,
    bucket: str,
    source_truth: pd.DataFrame,
    origin_attribute_coverage: pd.DataFrame,
    parser_artifacts: pd.DataFrame,
    mapping_gaps: pd.DataFrame,
    stock_to_use_constructibility: pd.DataFrame,
    commodities: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return a compact JSON report for Phase 1 source truth."""
    selected = origin_attribute_coverage.copy()
    if commodities:
        selected = selected.loc[selected["commodity"].isin(set(commodities))].copy()
    corn = selected.loc[selected["commodity"] == "corn"].copy()
    coverage_counts = (
        selected["coverage_class"].value_counts(dropna=False).sort_index().to_dict()
        if not selected.empty else {}
    )
    corn_core = corn.loc[corn["coverage_class"] == "core_model_feature"]
    corn_phase2_core = corn_core.loc[
        corn_core["attribute"].isin(set(CORE_WASDE_ATTRIBUTES))
    ].copy()
    constructible = stock_to_use_constructibility.loc[
        stock_to_use_constructibility["stock_to_use_constructible"]
    ]
    return {
        "bucket": bucket,
        "phase": "wasde_snapshot_phase1_source_truth_audit",
        "source_truth": {
            "row_count": int(len(source_truth)),
            "commodity_count": int(source_truth["commodity"].nunique())
            if not source_truth.empty else 0,
            "coverage_class_counts": {str(k): int(v) for k, v in coverage_counts.items()},
            "parser_artifact_rows": int(len(parser_artifacts)),
            "mapping_gap_rows": int(len(mapping_gaps)),
        },
        "corn": {
            "core_feature_count": int(len(corn_phase2_core)),
            "core_origins": sorted(
                corn_phase2_core["normalized_origin"].dropna().astype(str).unique()
            ),
            "core_attributes": sorted(
                corn_phase2_core["attribute"].dropna().astype(str).unique()
            ),
            "all_dense_attributes": sorted(
                corn_core["attribute"].dropna().astype(str).unique()
            ),
            "stock_to_use_constructible_years": int(
                constructible.loc[constructible["commodity"] == "corn"][
                    ["normalized_origin", "marketing_year_start"]
                ].drop_duplicates().shape[0]
            ) if not constructible.empty else 0,
        },
        "phase2_recommendation": {
            "proceed": bool(len(corn_phase2_core) > 0),
            "recommended_core_features": [
                "latest_estimate",
                "stock_to_use_estimate",
                "revision_since_first",
                "release_sequence",
            ],
            "notes": [
                "Use estimate density as the core signal; revision sparsity should only downgrade revision-specific features.",
                "Build release-date snapshot rows before running certification again.",
                "Keep parser-artifact and mapping-gap regions out of target-origin features.",
            ],
        },
    }


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
