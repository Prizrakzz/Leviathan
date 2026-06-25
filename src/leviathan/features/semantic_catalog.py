"""Semantic feature catalog generation for immutable gold datasets."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import yaml

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs" / "features"

CATALOG_COLUMNS = [
    "dataset_version",
    "feature",
    "feature_family",
    "semantic_scope",
    "empirical_scope",
    "policy",
    "mechanism",
    "sources",
    "source_cadence",
    "is_label",
    "entity_count",
    "commodity_count",
    "origin_count",
    "row_count",
    "non_null_rate",
    "first_event_time",
    "last_event_time",
    "groups",
    "notes",
]

ENTITY_MAP_COLUMNS = [
    "dataset_version",
    "feature",
    "commodity",
    "country",
    "crop_year_min",
    "crop_year_max",
    "row_count",
    "non_null_rate",
    "is_label",
]

GROUP_MAP_COLUMNS = [
    "dataset_version",
    "feature",
    "group",
    "commodity_count",
    "row_count",
    "non_null_rate",
    "semantic_scope",
    "policy",
]

POLICY_VALUES = {
    "fundamental_physical",
    "certified_economic_driver",
    "diagnostic_only",
    "excluded_market_signal",
}


@dataclass(frozen=True)
class TaxonomyRule:
    rule_id: str
    patterns: tuple[re.Pattern[str], ...]
    feature_family: str
    semantic_scope: str
    policy: str
    mechanism: str
    sources: tuple[str, ...]
    source_cadence: str
    notes: str

    def matches(self, feature: str) -> bool:
        return any(pattern.search(feature) for pattern in self.patterns)


@dataclass(frozen=True)
class FeatureTaxonomy:
    rules: tuple[TaxonomyRule, ...]
    default: TaxonomyRule

    def classify(self, feature: str) -> TaxonomyRule:
        for rule in self.rules:
            if rule.matches(feature):
                return rule
        return self.default


def _as_tuple(raw: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(str(item) for item in (raw or []))


def _rule_from_dict(raw: dict, default_id: str = "default") -> TaxonomyRule:
    policy = str(raw.get("policy", "diagnostic_only"))
    if policy not in POLICY_VALUES:
        raise ValueError(f"unsupported feature policy: {policy}")
    patterns = tuple(re.compile(str(pattern)) for pattern in raw.get("patterns", [r".*"]))
    return TaxonomyRule(
        rule_id=str(raw.get("id", default_id)),
        patterns=patterns,
        feature_family=str(raw.get("feature_family", "unknown")),
        semantic_scope=str(raw.get("semantic_scope", "unknown_review_required")),
        policy=policy,
        mechanism=str(raw.get("mechanism", "unknown")),
        sources=_as_tuple(raw.get("sources")),
        source_cadence=str(raw.get("source_cadence", "unknown")),
        notes=str(raw.get("notes", "")),
    )


def load_taxonomy(path: str | Path | None = None) -> FeatureTaxonomy:
    config_path = Path(path) if path is not None else _CONFIG_DIR / "feature_taxonomy.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    rules = tuple(_rule_from_dict(item) for item in raw.get("rules", []))
    default = _rule_from_dict(raw.get("defaults", {}), default_id="default")
    return FeatureTaxonomy(rules=rules, default=default)


def load_feature_groups(path: str | Path | None = None) -> dict[str, set[str]]:
    config_path = Path(path) if path is not None else _CONFIG_DIR / "feature_groups.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    groups: dict[str, set[str]] = {}
    for group, spec in (raw.get("groups") or {}).items():
        groups[str(group)] = {str(c) for c in spec.get("commodities", [])}
    return groups


def _empirical_scope(present_in: set[str], all_commodities: set[str]) -> str:
    if present_in >= all_commodities:
        return "universal"
    if len(present_in) == 1:
        return "commodity"
    return "group"


def _groups_for_commodities(
    commodities: set[str],
    feature_groups: dict[str, set[str]],
) -> list[str]:
    return sorted(
        group for group, members in feature_groups.items()
        if commodities & members
    )


def _join(values: Iterable[str]) -> str:
    return ",".join(sorted({str(value) for value in values if str(value)}))


def _non_null_rate(values: pd.Series) -> float:
    if len(values) == 0:
        return 0.0
    return float(values.notna().mean())


def build_semantic_catalog(
    spine_df: pd.DataFrame,
    *,
    dataset_version: str,
    taxonomy: FeatureTaxonomy,
    feature_groups: dict[str, set[str]],
    expected_commodities: set[str],
    unknown_row_threshold: int = 0,
) -> pd.DataFrame:
    required = {"commodity", "country", "crop_year", "feature", "value", "is_label", "event_time"}
    missing = required - set(spine_df.columns)
    if missing:
        raise ValueError(f"spine dataframe missing required columns: {sorted(missing)}")

    rows = []
    unknown_high_volume: list[tuple[str, int]] = []
    spine = spine_df.copy()
    spine["event_time"] = pd.to_datetime(spine["event_time"], errors="coerce")

    for feature, g in spine.groupby("feature", sort=True):
        feature = str(feature)
        commodities = {str(c) for c in g["commodity"].dropna().unique()}
        countries = {str(c) for c in g["country"].dropna().unique()}
        groups = _groups_for_commodities(commodities, feature_groups)
        rule = taxonomy.classify(feature)
        row_count = int(len(g))
        if (
            rule.semantic_scope == "unknown_review_required"
            and row_count > unknown_row_threshold
        ):
            unknown_high_volume.append((feature, row_count))

        rows.append({
            "dataset_version": dataset_version,
            "feature": feature,
            "feature_family": rule.feature_family,
            "semantic_scope": rule.semantic_scope,
            "empirical_scope": _empirical_scope(commodities, expected_commodities),
            "policy": rule.policy,
            "mechanism": rule.mechanism,
            "sources": _join(rule.sources),
            "source_cadence": rule.source_cadence,
            "is_label": bool(g["is_label"].any()),
            "entity_count": int(g[["commodity", "country"]].drop_duplicates().shape[0]),
            "commodity_count": int(len(commodities)),
            "origin_count": int(len(countries)),
            "row_count": row_count,
            "non_null_rate": _non_null_rate(g["value"]),
            "first_event_time": (
                g["event_time"].min().date().isoformat()
                if g["event_time"].notna().any() else None
            ),
            "last_event_time": (
                g["event_time"].max().date().isoformat()
                if g["event_time"].notna().any() else None
            ),
            "groups": _join(groups),
            "notes": rule.notes,
        })

    if unknown_high_volume:
        sample = ", ".join(f"{name}({count})" for name, count in unknown_high_volume[:10])
        raise ValueError(
            "high-volume features are missing taxonomy rules: "
            f"{sample}"
        )

    return pd.DataFrame(rows, columns=CATALOG_COLUMNS)


def build_feature_entity_map(
    spine_df: pd.DataFrame,
    *,
    dataset_version: str,
) -> pd.DataFrame:
    rows = []
    for (feature, commodity, country), g in spine_df.groupby(
        ["feature", "commodity", "country"], sort=True
    ):
        years = pd.to_numeric(g["crop_year"], errors="coerce")
        rows.append({
            "dataset_version": dataset_version,
            "feature": str(feature),
            "commodity": str(commodity),
            "country": str(country),
            "crop_year_min": int(years.min()),
            "crop_year_max": int(years.max()),
            "row_count": int(len(g)),
            "non_null_rate": _non_null_rate(g["value"]),
            "is_label": bool(g["is_label"].any()),
        })
    return pd.DataFrame(rows, columns=ENTITY_MAP_COLUMNS)


def build_feature_group_map(
    spine_df: pd.DataFrame,
    catalog_df: pd.DataFrame,
    *,
    dataset_version: str,
    feature_groups: dict[str, set[str]],
) -> pd.DataFrame:
    catalog_lookup = catalog_df.set_index("feature")
    rows = []
    for feature, feature_rows in spine_df.groupby("feature", sort=True):
        feature = str(feature)
        if feature not in catalog_lookup.index:
            continue
        cat = catalog_lookup.loc[feature]
        for group, members in sorted(feature_groups.items()):
            g = feature_rows.loc[feature_rows["commodity"].isin(members)]
            if g.empty:
                continue
            rows.append({
                "dataset_version": dataset_version,
                "feature": feature,
                "group": group,
                "commodity_count": int(g["commodity"].nunique()),
                "row_count": int(len(g)),
                "non_null_rate": _non_null_rate(g["value"]),
                "semantic_scope": str(cat["semantic_scope"]),
                "policy": str(cat["policy"]),
            })
    return pd.DataFrame(rows, columns=GROUP_MAP_COLUMNS)
