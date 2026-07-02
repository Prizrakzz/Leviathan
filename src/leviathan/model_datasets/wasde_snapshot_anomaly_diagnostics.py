"""Diagnostics for WASDE snapshot anomaly-score evaluation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.model_datasets.wasde_snapshot_anomaly_scores import (
    SNAPSHOT_SCORE_ID_COLUMNS,
)

MISSINGNESS_COLUMNS = [
    "detector_id",
    "target_key",
    "origin_key",
    "snapshot_stage",
    "row_count",
    "non_null_count",
    "non_null_rate",
    "null_reasons",
]

CORRELATION_COLUMNS = [
    "component_a",
    "component_b",
    "correlation",
    "abs_correlation",
    "observation_count",
]

CLUSTER_COLUMNS = [
    "cluster_id",
    "component",
    "cluster_size",
    "max_abs_correlation_in_cluster",
]

REDUNDANT_FAMILY_COLUMNS = [
    "source_attribute",
    "detector_id",
    "source_transform",
    "score_name_count",
    "row_count",
    "non_null_count",
    "non_null_rate",
]

DOMINANCE_COLUMNS = [
    "target_key",
    "detector_id",
    "component_group",
    "component_count",
    "top_attribute",
    "top_attribute_contribution_share",
    "top_feature",
    "top_feature_contribution_share",
    "effective_component_count",
]


def _safe_float(value: object) -> float:
    try:
        out = float(value)
    except Exception:  # noqa: BLE001
        return np.nan
    return out if np.isfinite(out) else np.nan


def _component_stress_value(score: object, detector_id: object) -> float:
    value = _safe_float(score)
    if not np.isfinite(value):
        return np.nan
    if str(detector_id) == "stage_level_percentile":
        return float(np.clip(value, 0.0, 1.0))
    return float(1.0 / (1.0 + np.exp(-float(np.clip(value, -8.0, 8.0)))))


def build_score_missingness_diagnostics(scores: pd.DataFrame) -> pd.DataFrame:
    """Summarize score coverage by detector, target, origin, and stage."""
    if scores.empty:
        return pd.DataFrame(columns=MISSINGNESS_COLUMNS)
    rows: list[dict[str, object]] = []
    group_cols = ["detector_id", "target_key", "origin_key", "snapshot_stage"]
    for keys, group in scores.groupby(group_cols, dropna=False, sort=True):
        values = dict(zip(group_cols, keys, strict=False))
        score = pd.to_numeric(group["score_value"], errors="coerce")
        reasons = sorted(
            str(reason)
            for reason in group.loc[score.isna(), "score_null_reason"].dropna().unique()
            if str(reason)
        )
        rows.append({
            **values,
            "row_count": int(len(group)),
            "non_null_count": int(score.notna().sum()),
            "non_null_rate": float(score.notna().mean()) if len(score) else np.nan,
            "null_reasons": ",".join(reasons),
        })
    return pd.DataFrame(rows, columns=MISSINGNESS_COLUMNS).reset_index(drop=True)


def _component_name(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["detector_id"].astype(str)
        + "|"
        + frame["source_attribute"].astype(str)
        + "|"
        + frame["source_transform"].astype(str)
    )


def build_score_component_correlation(scores: pd.DataFrame) -> pd.DataFrame:
    """Build pairwise correlations between score components."""
    if scores.empty:
        return pd.DataFrame(columns=CORRELATION_COLUMNS)
    usable = scores.loc[
        (scores["detector_id"].astype(str) != "missing_input")
        & pd.to_numeric(scores["score_value"], errors="coerce").notna()
    ].copy()
    if usable.empty:
        return pd.DataFrame(columns=CORRELATION_COLUMNS)
    usable["component"] = _component_name(usable)
    usable["score_value"] = pd.to_numeric(usable["score_value"], errors="coerce")
    pivot = usable.pivot_table(
        index=SNAPSHOT_SCORE_ID_COLUMNS,
        columns="component",
        values="score_value",
        aggfunc="max",
    )
    if pivot.shape[1] < 2:
        return pd.DataFrame(columns=CORRELATION_COLUMNS)
    corr = pivot.corr(min_periods=3)
    rows: list[dict[str, object]] = []
    cols = list(corr.columns)
    for i, left in enumerate(cols):
        for right in cols[i + 1:]:
            value = _safe_float(corr.loc[left, right])
            if not np.isfinite(value):
                continue
            obs = int(pivot[[left, right]].dropna().shape[0])
            rows.append({
                "component_a": str(left),
                "component_b": str(right),
                "correlation": value,
                "abs_correlation": abs(value),
                "observation_count": obs,
            })
    return pd.DataFrame(rows, columns=CORRELATION_COLUMNS).sort_values(
        "abs_correlation",
        ascending=False,
    ).reset_index(drop=True)


def build_score_component_clusters(
    correlations: pd.DataFrame,
    *,
    threshold: float = 0.90,
) -> pd.DataFrame:
    """Return simple connected components from high-correlation pairs."""
    if correlations.empty:
        return pd.DataFrame(columns=CLUSTER_COLUMNS)
    pairs = correlations.loc[correlations["abs_correlation"] >= float(threshold)]
    components = sorted(set(pairs["component_a"].astype(str)) | set(pairs["component_b"].astype(str)))
    parent = {component: component for component in components}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pb] = pa

    for _, row in pairs.iterrows():
        union(str(row["component_a"]), str(row["component_b"]))
    clusters: dict[str, list[str]] = {}
    for component in components:
        clusters.setdefault(find(component), []).append(component)
    rows: list[dict[str, object]] = []
    for cluster_id, members in enumerate(clusters.values()):
        max_corr = _safe_float(
            pairs.loc[
                pairs["component_a"].isin(members) | pairs["component_b"].isin(members),
                "abs_correlation",
            ].max()
        )
        for member in sorted(members):
            rows.append({
                "cluster_id": int(cluster_id),
                "component": member,
                "cluster_size": int(len(members)),
                "max_abs_correlation_in_cluster": max_corr,
            })
    return pd.DataFrame(rows, columns=CLUSTER_COLUMNS).reset_index(drop=True)


def build_redundant_feature_family_report(scores: pd.DataFrame) -> pd.DataFrame:
    """Summarize repeated score families by attribute/transform/detector."""
    if scores.empty:
        return pd.DataFrame(columns=REDUNDANT_FAMILY_COLUMNS)
    rows: list[dict[str, object]] = []
    group_cols = ["source_attribute", "detector_id", "source_transform"]
    for keys, group in scores.groupby(group_cols, dropna=False, sort=True):
        values = dict(zip(group_cols, keys, strict=False))
        score = pd.to_numeric(group["score_value"], errors="coerce")
        rows.append({
            **values,
            "score_name_count": int(group["score_name"].nunique()),
            "row_count": int(len(group)),
            "non_null_count": int(score.notna().sum()),
            "non_null_rate": float(score.notna().mean()) if len(score) else np.nan,
        })
    return pd.DataFrame(rows, columns=REDUNDANT_FAMILY_COLUMNS).sort_values(
        ["source_attribute", "detector_id", "source_transform"]
    ).reset_index(drop=True)


def build_composite_dominance_report(scores: pd.DataFrame) -> pd.DataFrame:
    """Report whether composite stress is dominated by one attribute/feature."""
    if scores.empty:
        return pd.DataFrame(columns=DOMINANCE_COLUMNS)
    usable = scores.loc[
        scores["detector_id"].isin({"stage_level_percentile", "revision_shock", "revision_streak"})
        & pd.to_numeric(scores["score_value"], errors="coerce").notna()
    ].copy()
    if usable.empty:
        return pd.DataFrame(columns=DOMINANCE_COLUMNS)
    usable["component_stress"] = [
        _component_stress_value(score, detector)
        for score, detector in zip(usable["score_value"], usable["detector_id"], strict=False)
    ]
    usable = usable.loc[pd.to_numeric(usable["component_stress"], errors="coerce").notna()]
    rows: list[dict[str, object]] = []
    for target_key, group in usable.groupby("target_key", dropna=False, sort=True):
        total = float(group["component_stress"].sum())
        if total <= 0:
            continue
        attr = group.groupby("source_attribute")["component_stress"].sum().sort_values(ascending=False)
        feat = group.groupby("source_feature")["component_stress"].sum().sort_values(ascending=False)
        attr_shares = attr / total
        feat_shares = feat / total
        shares = group.groupby(["source_attribute", "source_feature"])["component_stress"].sum() / total
        effective = float(1.0 / np.square(shares.to_numpy()).sum()) if len(shares) else np.nan
        rows.append({
            "target_key": str(target_key),
            "detector_id": "composite_balance_sheet_stress",
            "component_group": "all_components",
            "component_count": int(group["source_feature"].nunique()),
            "top_attribute": str(attr_shares.index[0]),
            "top_attribute_contribution_share": _safe_float(attr_shares.iloc[0]),
            "top_feature": str(feat_shares.index[0]),
            "top_feature_contribution_share": _safe_float(feat_shares.iloc[0]),
            "effective_component_count": effective,
        })
    return pd.DataFrame(rows, columns=DOMINANCE_COLUMNS).reset_index(drop=True)
