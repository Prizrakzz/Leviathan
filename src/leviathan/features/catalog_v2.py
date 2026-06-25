"""Build feature metadata tables for immutable gold_v2 dataset versions."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from leviathan.features.taxonomy_v2 import FeatureTaxonomyRegistry, load_feature_taxonomy_v2

FEATURE_CATALOG_V2_COLUMNS = [
    "dataset_version",
    "feature",
    "semantic_scope",
    "mechanism",
    "policy",
    "sources",
    "groups",
    "entity_count",
    "commodity_count",
    "origin_count",
    "row_count",
    "non_null_rate",
    "first_as_of_date",
    "last_as_of_date",
    "first_available_at",
    "last_available_at",
    "is_label",
]

FEATURE_ENTITY_MAP_V2_COLUMNS = [
    "dataset_version",
    "feature",
    "entity_id",
    "contract_slug",
    "physical_commodity",
    "origin",
    "row_count",
    "non_null_count",
    "first_as_of_date",
    "last_as_of_date",
]

FEATURE_GROUP_MAP_V2_COLUMNS = [
    "dataset_version",
    "feature",
    "group",
    "entity_count",
    "commodity_count",
    "row_count",
]


@dataclass(frozen=True)
class FeatureCatalogV2Result:
    catalog: pd.DataFrame
    entity_map: pd.DataFrame
    group_map: pd.DataFrame


def _dataset_version(df: pd.DataFrame, dataset_version: str | None) -> str:
    if dataset_version:
        return dataset_version
    if "dataset_version" in df.columns and df["dataset_version"].nunique(dropna=True) == 1:
        return str(df["dataset_version"].dropna().iloc[0])
    return "unknown"


def _date_min(series: pd.Series) -> pd.Timestamp | None:
    values = pd.to_datetime(series, errors="coerce").dropna()
    return None if values.empty else values.min().normalize()


def _date_max(series: pd.Series) -> pd.Timestamp | None:
    values = pd.to_datetime(series, errors="coerce").dropna()
    return None if values.empty else values.max().normalize()


def _csv(values: set[str] | tuple[str, ...]) -> str:
    return ",".join(sorted(str(value) for value in values if str(value)))


def _groups_for_feature(
    feature_rows: pd.DataFrame,
    taxonomy: FeatureTaxonomyRegistry,
    configured_groups: tuple[str, ...],
) -> tuple[str, ...]:
    commodities = set(feature_rows["contract_slug"].dropna().astype(str))
    observed = set(taxonomy.groups.groups_for_commodities(commodities))
    configured = set(configured_groups)
    if configured and observed:
        intersected = configured & observed
        if intersected:
            return tuple(sorted(intersected))
    return tuple(sorted(configured or observed))


def build_feature_catalog_v2(
    spine_df: pd.DataFrame,
    *,
    dataset_version: str | None = None,
    taxonomy: FeatureTaxonomyRegistry | None = None,
) -> FeatureCatalogV2Result:
    """Create catalog, entity-map, and group-map tables from a gold_v2 spine."""
    taxonomy = taxonomy or load_feature_taxonomy_v2()
    version = _dataset_version(spine_df, dataset_version)
    if spine_df.empty:
        return FeatureCatalogV2Result(
            catalog=pd.DataFrame(columns=FEATURE_CATALOG_V2_COLUMNS),
            entity_map=pd.DataFrame(columns=FEATURE_ENTITY_MAP_V2_COLUMNS),
            group_map=pd.DataFrame(columns=FEATURE_GROUP_MAP_V2_COLUMNS),
        )

    work = spine_df.copy()
    if "dataset_version" not in work.columns:
        work["dataset_version"] = version
    if "commodity" not in work.columns:
        work["commodity"] = work.get("contract_slug", pd.Series(dtype="string"))

    catalog_rows: list[dict] = []
    entity_rows: list[dict] = []
    group_rows: list[dict] = []

    for feature, feature_rows in work.groupby("feature", sort=True):
        classification = taxonomy.classify_feature(str(feature))
        groups = _groups_for_feature(feature_rows, taxonomy, classification.groups)
        catalog_rows.append({
            "dataset_version": version,
            "feature": str(feature),
            "semantic_scope": classification.semantic_scope,
            "mechanism": classification.mechanism,
            "policy": classification.policy,
            "sources": _csv(classification.sources),
            "groups": _csv(set(groups)),
            "entity_count": int(feature_rows["entity_id"].nunique(dropna=True)),
            "commodity_count": int(feature_rows["contract_slug"].nunique(dropna=True)),
            "origin_count": int(feature_rows["origin"].nunique(dropna=True)),
            "row_count": int(len(feature_rows)),
            "non_null_rate": float(feature_rows["value"].notna().mean()),
            "first_as_of_date": _date_min(feature_rows["as_of_date"]),
            "last_as_of_date": _date_max(feature_rows["as_of_date"]),
            "first_available_at": _date_min(feature_rows["feature_available_at"]),
            "last_available_at": _date_max(feature_rows["feature_available_at"]),
            "is_label": bool(feature_rows["is_label"].fillna(False).any()),
        })

        for entity_id, entity_feature_rows in feature_rows.groupby("entity_id", sort=True):
            first = entity_feature_rows.iloc[0]
            entity_rows.append({
                "dataset_version": version,
                "feature": str(feature),
                "entity_id": str(entity_id),
                "contract_slug": str(first["contract_slug"]),
                "physical_commodity": str(first["physical_commodity"]),
                "origin": str(first["origin"]),
                "row_count": int(len(entity_feature_rows)),
                "non_null_count": int(entity_feature_rows["value"].notna().sum()),
                "first_as_of_date": _date_min(entity_feature_rows["as_of_date"]),
                "last_as_of_date": _date_max(entity_feature_rows["as_of_date"]),
            })

        for group in groups:
            group_feature_rows = feature_rows.loc[
                feature_rows["contract_slug"].astype(str).map(
                    lambda commodity: group in taxonomy.groups.groups_for_commodity(commodity)
                )
            ]
            if group_feature_rows.empty:
                group_feature_rows = feature_rows
            group_rows.append({
                "dataset_version": version,
                "feature": str(feature),
                "group": group,
                "entity_count": int(group_feature_rows["entity_id"].nunique(dropna=True)),
                "commodity_count": int(group_feature_rows["contract_slug"].nunique(dropna=True)),
                "row_count": int(len(group_feature_rows)),
            })

    return FeatureCatalogV2Result(
        catalog=pd.DataFrame(catalog_rows, columns=FEATURE_CATALOG_V2_COLUMNS),
        entity_map=pd.DataFrame(entity_rows, columns=FEATURE_ENTITY_MAP_V2_COLUMNS),
        group_map=pd.DataFrame(group_rows, columns=FEATURE_GROUP_MAP_V2_COLUMNS),
    )
