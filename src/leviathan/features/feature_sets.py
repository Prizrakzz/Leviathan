"""Resolve model-purpose feature sets from a semantic catalog."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import yaml

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs" / "features"

FEATURE_SET_COLUMNS = [
    "dataset_version",
    "feature_set_id",
    "feature_set_version",
    "feature_set_sha",
    "feature",
    "feature_family",
    "semantic_scope",
    "policy",
    "mechanism",
    "sources",
    "source_cadence",
    "empirical_scope",
    "groups",
    "is_label",
    "row_count",
    "commodity_count",
    "non_null_rate",
    "target_compatibility",
    "missingness_policy",
    "min_lag_days",
]

CORE_BLOCKED_POLICIES = {"diagnostic_only", "excluded_market_signal"}


@dataclass(frozen=True)
class FeatureSetSpec:
    feature_set_id: str
    version: str
    description: str
    allowed_policies: tuple[str, ...]
    blocked_policies: tuple[str, ...]
    allowed_semantic_scopes: tuple[str, ...]
    allowed_feature_families: tuple[str, ...]
    allowed_mechanisms: tuple[str, ...]
    allowed_sources: tuple[str, ...]
    allowed_groups: tuple[str, ...]
    include_feature_patterns: tuple[re.Pattern[str], ...]
    exclude_feature_patterns: tuple[re.Pattern[str], ...]
    exclude_labels: bool
    min_non_null_rate: float
    min_lag_days: int
    allow_empty: bool
    allow_diagnostic: bool
    target_compatibility: tuple[str, ...]
    missingness_policy: str


def _as_tuple(value: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(str(item) for item in (value or []))


def _as_bool(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _compile_patterns(values: Iterable[str] | None) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(str(value)) for value in (values or []))


def _config_sha(raw: dict) -> str:
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_feature_set_config(path: str | Path | None = None) -> tuple[list[FeatureSetSpec], str]:
    """Load feature-set specs and the stable SHA of the YAML content."""
    config_path = Path(path) if path is not None else _CONFIG_DIR / "feature_sets.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults") or {}
    specs: list[FeatureSetSpec] = []
    seen: set[str] = set()

    for item in raw.get("feature_sets", []):
        merged = {**defaults, **(item or {})}
        feature_set_id = str(merged["id"])
        if feature_set_id in seen:
            raise ValueError(f"duplicate feature_set id: {feature_set_id}")
        seen.add(feature_set_id)
        specs.append(FeatureSetSpec(
            feature_set_id=feature_set_id,
            version=str(merged.get("version", "1")),
            description=str(merged.get("description", "")),
            allowed_policies=_as_tuple(merged.get("allowed_policies")),
            blocked_policies=_as_tuple(merged.get("blocked_policies")),
            allowed_semantic_scopes=_as_tuple(merged.get("allowed_semantic_scopes")),
            allowed_feature_families=_as_tuple(merged.get("allowed_feature_families")),
            allowed_mechanisms=_as_tuple(merged.get("allowed_mechanisms")),
            allowed_sources=_as_tuple(merged.get("allowed_sources")),
            allowed_groups=_as_tuple(merged.get("allowed_groups")),
            include_feature_patterns=_compile_patterns(merged.get("include_feature_patterns")),
            exclude_feature_patterns=_compile_patterns(merged.get("exclude_feature_patterns")),
            exclude_labels=_as_bool(merged.get("exclude_labels"), default=True),
            min_non_null_rate=float(merged.get("min_non_null_rate", 0.0)),
            min_lag_days=int(merged.get("min_lag_days", 0)),
            allow_empty=_as_bool(merged.get("allow_empty"), default=False),
            allow_diagnostic=_as_bool(merged.get("allow_diagnostic"), default=False),
            target_compatibility=_as_tuple(merged.get("target_compatibility")),
            missingness_policy=str(merged.get("missingness_policy", "tree_models_allow_nan")),
        ))

    if not specs:
        raise ValueError(f"feature set config has no feature_sets: {config_path}")
    return specs, _config_sha(raw)


def _split_csv(value: object) -> set[str]:
    return {part.strip() for part in str(value or "").split(",") if part.strip()}


def _contains_any_csv(value: object, allowed: Iterable[str]) -> bool:
    present = _split_csv(value)
    return bool(present & set(allowed))


def _feature_set_sha(feature_set_id: str, version: str, config_sha: str, features: list[str]) -> str:
    payload = {
        "feature_set_id": feature_set_id,
        "feature_set_version": version,
        "config_sha": config_sha,
        "features": sorted(features),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _features_in_groups(group_map_df: pd.DataFrame, groups: tuple[str, ...]) -> set[str]:
    if not groups:
        return set()
    required = {"feature", "group"}
    missing = required - set(group_map_df.columns)
    if missing:
        raise ValueError(f"group map missing required columns: {sorted(missing)}")
    return set(
        group_map_df.loc[group_map_df["group"].isin(groups), "feature"].astype(str)
    )


def _select_one(
    catalog_df: pd.DataFrame,
    group_map_df: pd.DataFrame,
    spec: FeatureSetSpec,
) -> tuple[pd.DataFrame, dict[str, int]]:
    selected = catalog_df.copy()
    rejection_counts: dict[str, int] = {}

    def apply_mask(name: str, mask: pd.Series) -> None:
        nonlocal selected
        rejection_counts[name] = int((~mask).sum())
        selected = selected.loc[mask].copy()

    if spec.exclude_labels and "is_label" in selected.columns:
        apply_mask("labels", ~selected["is_label"].fillna(False).astype(bool))

    if spec.allowed_policies:
        apply_mask("allowed_policies", selected["policy"].isin(spec.allowed_policies))

    if spec.blocked_policies:
        apply_mask("blocked_policies", ~selected["policy"].isin(spec.blocked_policies))

    if spec.allowed_semantic_scopes:
        apply_mask(
            "allowed_semantic_scopes",
            selected["semantic_scope"].isin(spec.allowed_semantic_scopes),
        )

    if spec.allowed_feature_families:
        apply_mask(
            "allowed_feature_families",
            selected["feature_family"].isin(spec.allowed_feature_families),
        )

    if spec.allowed_mechanisms:
        apply_mask("allowed_mechanisms", selected["mechanism"].isin(spec.allowed_mechanisms))

    if spec.allowed_sources:
        apply_mask(
            "allowed_sources",
            selected["sources"].apply(lambda value: _contains_any_csv(value, spec.allowed_sources)),
        )

    if spec.allowed_groups:
        allowed_features = _features_in_groups(group_map_df, spec.allowed_groups)
        apply_mask("allowed_groups", selected["feature"].astype(str).isin(allowed_features))

    if spec.include_feature_patterns:
        apply_mask(
            "include_feature_patterns",
            selected["feature"].astype(str).apply(
                lambda feature: any(pattern.search(feature) for pattern in spec.include_feature_patterns)
            ),
        )

    if spec.exclude_feature_patterns:
        apply_mask(
            "exclude_feature_patterns",
            ~selected["feature"].astype(str).apply(
                lambda feature: any(pattern.search(feature) for pattern in spec.exclude_feature_patterns)
            ),
        )

    apply_mask(
        "min_non_null_rate",
        pd.to_numeric(selected["non_null_rate"], errors="coerce").fillna(0.0)
        >= spec.min_non_null_rate,
    )

    return selected, rejection_counts


def build_feature_set_membership(
    catalog_df: pd.DataFrame,
    group_map_df: pd.DataFrame,
    *,
    dataset_version: str,
    specs: list[FeatureSetSpec],
    config_sha: str,
) -> tuple[pd.DataFrame, dict]:
    """Resolve configured feature sets from a semantic catalog."""
    required = {
        "feature",
        "feature_family",
        "semantic_scope",
        "policy",
        "mechanism",
        "sources",
        "source_cadence",
        "empirical_scope",
        "groups",
        "is_label",
        "row_count",
        "commodity_count",
        "non_null_rate",
    }
    missing = required - set(catalog_df.columns)
    if missing:
        raise ValueError(f"semantic catalog missing required columns: {sorted(missing)}")

    frames: list[pd.DataFrame] = []
    per_set_counts: dict[str, int] = {}
    per_set_shas: dict[str, str] = {}
    rejected: dict[str, dict[str, int]] = {}
    empty_sets: list[str] = []

    for spec in specs:
        selected, rejection_counts = _select_one(catalog_df, group_map_df, spec)
        selected_features = sorted(selected["feature"].astype(str).unique())
        feature_set_sha = _feature_set_sha(
            spec.feature_set_id, spec.version, config_sha, selected_features
        )
        per_set_counts[spec.feature_set_id] = int(len(selected_features))
        per_set_shas[spec.feature_set_id] = feature_set_sha
        rejected[spec.feature_set_id] = rejection_counts

        if not selected_features and not spec.allow_empty:
            empty_sets.append(spec.feature_set_id)
            continue

        if not spec.allow_diagnostic:
            bad_policies = set(selected["policy"].astype(str)) & CORE_BLOCKED_POLICIES
            if bad_policies:
                raise ValueError(
                    f"core feature set {spec.feature_set_id} selected blocked policies: "
                    f"{sorted(bad_policies)}"
                )

        if spec.exclude_labels and selected["is_label"].fillna(False).astype(bool).any():
            raise ValueError(f"feature set {spec.feature_set_id} selected label features")

        out = selected.copy()
        out["dataset_version"] = dataset_version
        out["feature_set_id"] = spec.feature_set_id
        out["feature_set_version"] = spec.version
        out["feature_set_sha"] = feature_set_sha
        out["target_compatibility"] = ",".join(spec.target_compatibility)
        out["missingness_policy"] = spec.missingness_policy
        out["min_lag_days"] = spec.min_lag_days
        frames.append(out[FEATURE_SET_COLUMNS])

    if empty_sets:
        raise ValueError(f"feature sets resolved to zero features: {sorted(empty_sets)}")

    membership = (
        pd.concat(frames, ignore_index=True)
        if frames else pd.DataFrame(columns=FEATURE_SET_COLUMNS)
    )
    membership = membership.sort_values(["feature_set_id", "feature"]).reset_index(drop=True)
    summary = {
        "dataset_version": dataset_version,
        "config_sha": config_sha,
        "feature_set_count": int(len(specs)),
        "selected_row_count": int(len(membership)),
        "per_set_counts": per_set_counts,
        "per_set_shas": per_set_shas,
        "rejection_counts": rejected,
        "policy_counts": {
            str(key): int(value)
            for key, value in membership["policy"].value_counts().sort_index().items()
        },
    }
    return membership, summary


def selected_features_for_set(membership_df: pd.DataFrame, feature_set_id: str) -> list[str]:
    """Return the sorted feature list for one feature set."""
    rows = membership_df.loc[membership_df["feature_set_id"] == feature_set_id]
    if rows.empty:
        raise ValueError(f"unknown or empty feature set: {feature_set_id}")
    rows = rows.loc[~rows["is_label"].fillna(False).astype(bool)]
    return sorted(rows["feature"].astype(str).unique())
