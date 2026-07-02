"""WASDE snapshot mapping config loading and validation."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from leviathan.model_datasets.psd_targets import (
    PSDMetricTargetConfig,
    load_psd_metric_targets,
)

_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "ml" / "wasde_snapshot_mappings.yaml"
)

REQUIRED_SOURCE_FIELDS = {
    "source_key",
    "source_table",
    "s3_prefix",
    "release_date_field",
    "commodity_field",
    "region_field",
    "marketing_year_field",
    "attribute_field",
    "value_field",
}

SURFACE_TYPES = {"solo_contract", "contract_with_substitutes", "segment"}
SURFACE_STATUSES = {"active", "deferred", "deprecated"}
MAPPING_CONFIDENCE = {"high", "medium", "low", "none"}
ORIGIN_ROLES = {"primary_target", "target_origin", "substitute_context", "segment_member", "macro_context"}
SEGMENT_MEMBER_STATUSES = {"active", "active_proxy", "deferred_mapping_review"}
DEFERRED_MEMBER_STATUSES = {"deferred_mapping_review"}


@dataclass(frozen=True)
class WasdeOriginMapping:
    origin_key: str
    wasde_region_aliases: tuple[str, ...]
    role: str
    mapping_confidence: str


@dataclass(frozen=True)
class WasdeContextCommodity:
    wasde_commodity: str
    context_role: str
    contracts: tuple[str, ...]
    origins: tuple[str, ...]
    mapping_confidence: str
    note: str


@dataclass(frozen=True)
class WasdeSegmentMember:
    contract_key: str
    wasde_commodity: str
    target_status: str
    origins: tuple[str, ...]
    mapping_confidence: str
    note: str

    @property
    def is_active(self) -> bool:
        return self.target_status not in DEFERRED_MEMBER_STATUSES


@dataclass(frozen=True)
class WasdeSnapshotSurface:
    dataset_key: str
    surface_type: str
    status: str
    primary_contract: str
    primary_wasde_commodity: str
    commodity_group: str
    mapping_confidence: str
    target_origins: tuple[WasdeOriginMapping, ...]
    context_commodities: tuple[WasdeContextCommodity, ...]
    segment_members: tuple[WasdeSegmentMember, ...]
    deferred_contracts: tuple[str, ...]
    note: str

    @property
    def active_segment_members(self) -> tuple[WasdeSegmentMember, ...]:
        return tuple(member for member in self.segment_members if member.is_active)


@dataclass(frozen=True)
class WasdeSnapshotMappingConfig:
    surfaces: dict[str, WasdeSnapshotSurface]
    region_aliases: dict[str, str]
    aggregate_regions: tuple[str, ...]
    core_attributes: tuple[str, ...]
    excluded_region_classes: tuple[str, ...]
    config_sha: str
    raw: dict[str, Any]


def normalize_wasde_token(value: object) -> str:
    """Normalize WASDE commodity, region, and origin tokens."""
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def mapping_sha(raw: dict[str, Any] | WasdeSnapshotMappingConfig) -> str:
    """Return a stable SHA for mapping raw config or a loaded config."""
    payload = raw.raw if isinstance(raw, WasdeSnapshotMappingConfig) else raw
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _as_tuple(value: Any) -> tuple[str, ...]:
    return tuple(normalize_wasde_token(item) for item in (value or []))


def _validate_source(source: dict[str, Any]) -> None:
    missing = REQUIRED_SOURCE_FIELDS - set(source)
    if missing:
        raise ValueError(f"WASDE snapshot mapping source missing fields: {sorted(missing)}")
    if source.get("source_key") != "wasde":
        raise ValueError("WASDE snapshot mapping source.source_key must be 'wasde'")


def _is_garbled_token(value: str) -> bool:
    alpha_count = sum(ch.isalpha() for ch in value)
    digit_count = sum(ch.isdigit() for ch in value)
    return alpha_count == 0 or (digit_count > alpha_count and digit_count >= 3)


def _validate_clean_origin_token(
    value: str,
    *,
    aggregate_regions: set[str],
    context: str,
) -> None:
    if not value:
        raise ValueError(f"{context}: blank origin/region token is not allowed")
    if value in aggregate_regions or value.startswith("major_"):
        raise ValueError(f"{context}: aggregate region is not allowed: {value}")
    if _is_garbled_token(value):
        raise ValueError(f"{context}: garbled region token is not allowed: {value}")


def _load_origin(
    item: dict[str, Any],
    *,
    surface_key: str,
    aggregate_regions: set[str],
) -> WasdeOriginMapping:
    origin_key = normalize_wasde_token(item.get("origin_key"))
    aliases = _as_tuple(item.get("wasde_region_aliases"))
    role = str(item.get("role") or "")
    confidence = str(item.get("mapping_confidence") or "")

    if not origin_key:
        raise ValueError(f"{surface_key}: target origin missing origin_key")
    if not aliases:
        raise ValueError(f"{surface_key}:{origin_key}: missing wasde_region_aliases")
    if role not in ORIGIN_ROLES:
        raise ValueError(f"{surface_key}:{origin_key}: invalid origin role {role!r}")
    if confidence not in MAPPING_CONFIDENCE:
        raise ValueError(f"{surface_key}:{origin_key}: invalid mapping_confidence {confidence!r}")

    _validate_clean_origin_token(
        origin_key,
        aggregate_regions=aggregate_regions,
        context=f"{surface_key}:{origin_key}",
    )
    for alias in aliases:
        _validate_clean_origin_token(
            alias,
            aggregate_regions=aggregate_regions,
            context=f"{surface_key}:{origin_key}:alias",
        )

    return WasdeOriginMapping(
        origin_key=origin_key,
        wasde_region_aliases=aliases,
        role=role,
        mapping_confidence=confidence,
    )


def _load_context_commodity(
    item: dict[str, Any],
    *,
    surface_key: str,
    aggregate_regions: set[str],
) -> WasdeContextCommodity:
    wasde_commodity = normalize_wasde_token(item.get("wasde_commodity"))
    origins = _as_tuple(item.get("origins"))
    contracts = tuple(str(contract) for contract in (item.get("contracts") or []))
    confidence = str(item.get("mapping_confidence") or "")
    note = str(item.get("note") or "").strip()

    if not wasde_commodity:
        raise ValueError(f"{surface_key}: context commodity missing wasde_commodity")
    if not origins:
        raise ValueError(f"{surface_key}:{wasde_commodity}: context commodity missing origins")
    if not contracts:
        raise ValueError(f"{surface_key}:{wasde_commodity}: context commodity missing contracts")
    if confidence not in MAPPING_CONFIDENCE:
        raise ValueError(
            f"{surface_key}:{wasde_commodity}: invalid mapping_confidence {confidence!r}"
        )
    if not note:
        raise ValueError(f"{surface_key}:{wasde_commodity}: context commodity requires note")

    for origin in origins:
        _validate_clean_origin_token(
            origin,
            aggregate_regions=aggregate_regions,
            context=f"{surface_key}:{wasde_commodity}:origin",
        )

    return WasdeContextCommodity(
        wasde_commodity=wasde_commodity,
        context_role=str(item.get("context_role") or ""),
        contracts=contracts,
        origins=origins,
        mapping_confidence=confidence,
        note=note,
    )


def _load_segment_member(
    item: dict[str, Any],
    *,
    surface_key: str,
    aggregate_regions: set[str],
) -> WasdeSegmentMember:
    contract_key = str(item.get("contract_key") or "")
    wasde_commodity = normalize_wasde_token(item.get("wasde_commodity"))
    status = str(item.get("target_status") or "")
    origins = _as_tuple(item.get("origins"))
    confidence = str(item.get("mapping_confidence") or "")
    note = str(item.get("note") or "").strip()

    if not contract_key:
        raise ValueError(f"{surface_key}: segment member missing contract_key")
    if not wasde_commodity:
        raise ValueError(f"{surface_key}:{contract_key}: missing wasde_commodity")
    if status not in SEGMENT_MEMBER_STATUSES:
        raise ValueError(f"{surface_key}:{contract_key}: invalid target_status {status!r}")
    if not origins:
        raise ValueError(f"{surface_key}:{contract_key}: segment member missing origins")
    if confidence not in MAPPING_CONFIDENCE:
        raise ValueError(f"{surface_key}:{contract_key}: invalid mapping_confidence {confidence!r}")
    if status != "active" and not note:
        raise ValueError(f"{surface_key}:{contract_key}: non-active members require note")

    for origin in origins:
        _validate_clean_origin_token(
            origin,
            aggregate_regions=aggregate_regions,
            context=f"{surface_key}:{contract_key}:origin",
        )

    return WasdeSegmentMember(
        contract_key=contract_key,
        wasde_commodity=wasde_commodity,
        target_status=status,
        origins=origins,
        mapping_confidence=confidence,
        note=note,
    )


def _validate_alias_collisions(surface: WasdeSnapshotSurface) -> None:
    seen: dict[str, str] = {}
    for origin in surface.target_origins:
        for alias in origin.wasde_region_aliases:
            existing = seen.get(alias)
            if existing is not None and existing != origin.origin_key:
                raise ValueError(
                    f"{surface.dataset_key}: region alias {alias!r} maps to both "
                    f"{existing!r} and {origin.origin_key!r}"
                )
            seen[alias] = origin.origin_key


def _load_surface(
    item: dict[str, Any],
    *,
    aggregate_regions: set[str],
) -> WasdeSnapshotSurface:
    dataset_key = str(item.get("dataset_key") or "")
    if not dataset_key:
        raise ValueError("WASDE snapshot surface missing dataset_key")
    surface_type = str(item.get("surface_type") or "")
    status = str(item.get("status") or "")
    confidence = str(item.get("mapping_confidence") or "")

    if surface_type not in SURFACE_TYPES:
        raise ValueError(f"{dataset_key}: invalid surface_type {surface_type!r}")
    if status not in SURFACE_STATUSES:
        raise ValueError(f"{dataset_key}: invalid status {status!r}")
    if confidence not in MAPPING_CONFIDENCE:
        raise ValueError(f"{dataset_key}: invalid mapping_confidence {confidence!r}")

    primary_contract = str(item.get("primary_contract") or "")
    primary_wasde_commodity = normalize_wasde_token(item.get("primary_wasde_commodity"))
    if not primary_contract:
        raise ValueError(f"{dataset_key}: missing primary_contract")
    if not primary_wasde_commodity:
        raise ValueError(f"{dataset_key}: missing primary_wasde_commodity")

    target_origins = tuple(
        _load_origin(origin, surface_key=dataset_key, aggregate_regions=aggregate_regions)
        for origin in (item.get("target_origins") or [])
    )
    if not target_origins:
        raise ValueError(f"{dataset_key}: missing target_origins")

    surface = WasdeSnapshotSurface(
        dataset_key=dataset_key,
        surface_type=surface_type,
        status=status,
        primary_contract=primary_contract,
        primary_wasde_commodity=primary_wasde_commodity,
        commodity_group=str(item.get("commodity_group") or ""),
        mapping_confidence=confidence,
        target_origins=target_origins,
        context_commodities=tuple(
            _load_context_commodity(
                context,
                surface_key=dataset_key,
                aggregate_regions=aggregate_regions,
            )
            for context in (item.get("context_commodities") or [])
        ),
        segment_members=tuple(
            _load_segment_member(
                member,
                surface_key=dataset_key,
                aggregate_regions=aggregate_regions,
            )
            for member in (item.get("segment_members") or [])
        ),
        deferred_contracts=tuple(str(contract) for contract in (item.get("deferred_contracts") or [])),
        note=str(item.get("note") or "").strip(),
    )
    _validate_alias_collisions(surface)
    if surface.surface_type == "segment" and not surface.segment_members:
        raise ValueError(f"{dataset_key}: segment surfaces require segment_members")
    if surface.surface_type != "segment" and surface.segment_members:
        raise ValueError(f"{dataset_key}: non-segment surfaces cannot define segment_members")
    return surface


def _validate_against_psd_targets(
    surfaces: dict[str, WasdeSnapshotSurface],
    psd_config: PSDMetricTargetConfig,
) -> None:
    for surface in surfaces.values():
        primary = psd_config.contract_mappings.get(surface.primary_contract)
        if primary is None:
            raise ValueError(f"{surface.dataset_key}: unknown primary_contract {surface.primary_contract}")
        psd_origins = {
            normalize_wasde_token(origin.get("origin_key"))
            for origin in primary.target_origins
        }
        surface_origins = {origin.origin_key for origin in surface.target_origins}
        missing = sorted(surface_origins - psd_origins)
        if missing:
            raise ValueError(
                f"{surface.dataset_key}: target origins not present in PSD mapping for "
                f"{surface.primary_contract}: {missing}"
            )

        for member in surface.segment_members:
            if not member.is_active:
                continue
            psd_member = psd_config.contract_mappings.get(member.contract_key)
            if psd_member is None:
                raise ValueError(
                    f"{surface.dataset_key}: unknown active segment contract "
                    f"{member.contract_key}"
                )
            member_psd_origins = {
                normalize_wasde_token(origin.get("origin_key"))
                for origin in psd_member.target_origins
            }
            member_missing = sorted(set(member.origins) - member_psd_origins)
            if member_missing:
                raise ValueError(
                    f"{surface.dataset_key}:{member.contract_key}: segment origins not "
                    f"present in PSD mapping: {member_missing}"
                )


def load_wasde_snapshot_mappings(
    path: str | Path | None = None,
    *,
    validate_psd: bool = True,
    psd_config: PSDMetricTargetConfig | None = None,
) -> WasdeSnapshotMappingConfig:
    """Load and validate governed WASDE snapshot mappings."""
    config_path = Path(path) if path is not None else _CONFIG_PATH
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if int(raw.get("schema_version", 0)) != 1:
        raise ValueError(
            f"unsupported WASDE snapshot mapping schema_version: {raw.get('schema_version')}"
        )
    _validate_source(raw.get("source") or {})

    aggregate_regions = _as_tuple(raw.get("aggregate_regions"))
    aggregate_set = set(aggregate_regions)
    region_aliases = {
        normalize_wasde_token(alias): normalize_wasde_token(origin)
        for alias, origin in (raw.get("region_aliases") or {}).items()
    }
    for alias, origin in region_aliases.items():
        _validate_clean_origin_token(alias, aggregate_regions=aggregate_set, context="region_aliases")
        _validate_clean_origin_token(origin, aggregate_regions=aggregate_set, context="region_aliases")

    surfaces: dict[str, WasdeSnapshotSurface] = {}
    for item in raw.get("surfaces") or []:
        surface = _load_surface(item, aggregate_regions=aggregate_set)
        if surface.dataset_key in surfaces:
            raise ValueError(f"duplicate WASDE snapshot surface: {surface.dataset_key}")
        surfaces[surface.dataset_key] = surface
    if not surfaces:
        raise ValueError("WASDE snapshot mapping config has no surfaces")

    if validate_psd:
        _validate_against_psd_targets(
            surfaces,
            psd_config=psd_config or load_psd_metric_targets(),
        )

    defaults = raw.get("defaults") or {}
    return WasdeSnapshotMappingConfig(
        surfaces=surfaces,
        region_aliases=region_aliases,
        aggregate_regions=aggregate_regions,
        core_attributes=_as_tuple(raw.get("core_attributes")),
        excluded_region_classes=tuple(str(item) for item in (defaults.get("excluded_region_classes") or [])),
        config_sha=mapping_sha(raw),
        raw=raw,
    )


def get_surface(
    config: WasdeSnapshotMappingConfig,
    dataset_key: str,
) -> WasdeSnapshotSurface:
    """Return a named snapshot surface or raise a useful error."""
    try:
        return config.surfaces[dataset_key]
    except KeyError as exc:
        raise KeyError(f"unknown WASDE snapshot dataset_key: {dataset_key}") from exc


def surface_contracts(
    config: WasdeSnapshotMappingConfig,
    dataset_key: str,
    *,
    include_deferred: bool = False,
) -> tuple[str, ...]:
    """Return contracts referenced by a snapshot surface."""
    surface = get_surface(config, dataset_key)
    contracts: list[str] = [surface.primary_contract]
    for context in surface.context_commodities:
        contracts.extend(context.contracts)
    for member in surface.segment_members:
        if include_deferred or member.is_active:
            contracts.append(member.contract_key)
    contracts.extend(surface.deferred_contracts if include_deferred else ())
    return tuple(dict.fromkeys(contracts))


def allowed_snapshot_context(
    config: WasdeSnapshotMappingConfig,
    dataset_key: str,
) -> dict[str, Any]:
    """Return the allowed target/context contract and origin scope for a surface."""
    surface = get_surface(config, dataset_key)
    return {
        "dataset_key": surface.dataset_key,
        "primary_contract": surface.primary_contract,
        "primary_wasde_commodity": surface.primary_wasde_commodity,
        "target_origins": [origin.origin_key for origin in surface.target_origins],
        "context_commodities": [
            {
                "wasde_commodity": context.wasde_commodity,
                "context_role": context.context_role,
                "contracts": list(context.contracts),
                "origins": list(context.origins),
            }
            for context in surface.context_commodities
        ],
        "active_segment_members": [
            {
                "contract_key": member.contract_key,
                "wasde_commodity": member.wasde_commodity,
                "origins": list(member.origins),
                "target_status": member.target_status,
            }
            for member in surface.active_segment_members
        ],
    }


def resolve_wasde_origin(
    config: WasdeSnapshotMappingConfig,
    dataset_key: str,
    wasde_commodity: str,
    region: object,
) -> str | None:
    """Resolve a WASDE region to an allowed origin for a surface.

    Unknown, aggregate, garbled, and out-of-scope regions return ``None``.
    """
    surface = get_surface(config, dataset_key)
    commodity = normalize_wasde_token(wasde_commodity)
    region_token = normalize_wasde_token(region)
    canonical = config.region_aliases.get(region_token, region_token)
    if canonical in set(config.aggregate_regions) or canonical.startswith("major_"):
        return None
    if _is_garbled_token(canonical):
        return None

    allowed: set[tuple[str, str]] = set()
    if commodity == surface.primary_wasde_commodity:
        for origin in surface.target_origins:
            for alias in origin.wasde_region_aliases:
                allowed.add((commodity, config.region_aliases.get(alias, alias)))
            allowed.add((commodity, origin.origin_key))
    for context in surface.context_commodities:
        for origin in context.origins:
            allowed.add((context.wasde_commodity, origin))
    for member in surface.segment_members:
        if member.is_active:
            for origin in member.origins:
                allowed.add((member.wasde_commodity, origin))

    return canonical if (commodity, canonical) in allowed else None
