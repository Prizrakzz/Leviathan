"""Declarative feature registry — single source of truth for the feature spine.

Loads ``configs/features/features.yaml`` + ``configs/features/feature_params.yaml``
and validates every spec at load time: the computation family must exist in the
dispatch table, commodities must be valid, the visibility class must be known.

The spine output schema, validation ranges, and Athena DDL are all derived from
this registry, so adding a feature is a YAML entry + a computation function —
never a schema edit in three places.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from leviathan.common.constants import ALL_COMMODITIES
from leviathan.common.logging import get_logger

logger = get_logger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs" / "features"

VISIBILITY_CLASSES = (
    "crop_year_direct",
    "prior_history",
    "prior_marketing_year",
    "psd_vintage_snapshot",
)


class RegistryError(Exception):
    """Raised when the feature registry fails validation at load time."""


@dataclass(frozen=True)
class FeatureSpec:
    """One feature family declared in features.yaml."""
    family: str
    sources: tuple[str, ...]
    visibility: str
    commodities: tuple[str, ...]   # resolved (never "all"/"calendar" sentinels)
    value_range: tuple[float | None, float | None]
    is_label: bool
    params: dict = field(default_factory=dict)

    def applies_to(self, commodity: str) -> bool:
        return commodity in self.commodities


@dataclass(frozen=True)
class FeatureRegistry:
    """All validated feature specs + shared parameters."""
    specs: tuple[FeatureSpec, ...]
    shared_params: dict
    params_hash: str  # sha256 of the params YAML — goes into run manifests

    def specs_for(self, commodity: str) -> list[FeatureSpec]:
        return [s for s in self.specs if s.applies_to(commodity)]

    def sources_for(self, commodity: str) -> set[str]:
        out: set[str] = set()
        for spec in self.specs_for(commodity):
            out.update(spec.sources)
        return out


def load_registry(
    config_dir: str | Path | None = None,
    calendar_commodities: set[str] | None = None,
) -> FeatureRegistry:
    """Load and validate the registry.

    Args:
        config_dir: Directory holding features.yaml + feature_params.yaml
            (defaults to repo configs/features/).
        calendar_commodities: Commodities with a crop calendar entry — used to
            resolve the ``commodities: calendar`` sentinel.  When None, loads
            crop_calendars.yaml from the same config dir.

    Raises:
        RegistryError: On any spec that fails validation.
    """
    cfg = Path(config_dir) if config_dir is not None else _CONFIG_DIR

    params_text = (cfg / "feature_params.yaml").read_text(encoding="utf-8")
    shared_params: dict = yaml.safe_load(params_text) or {}
    params_hash = hashlib.sha256(params_text.encode("utf-8")).hexdigest()

    if calendar_commodities is None:
        from leviathan.features.calendar import load_crop_calendars
        calendar_commodities = set(load_crop_calendars(cfg / "crop_calendars.yaml"))

    raw_specs = yaml.safe_load((cfg / "features.yaml").read_text(encoding="utf-8")) or []
    if not isinstance(raw_specs, list):
        raise RegistryError("features.yaml must be a list of feature specs")

    # Imported here to avoid a circular import (computations import nothing
    # from registry, but keeping the dependency one-way at module load).
    from leviathan.features.computations import COMPUTATIONS

    specs: list[FeatureSpec] = []
    seen_families: set[str] = set()
    valid_commodities = set(ALL_COMMODITIES)

    for i, raw in enumerate(raw_specs):
        family = raw.get("family")
        if not family:
            raise RegistryError(f"spec[{i}]: missing 'family'")
        if family in seen_families:
            raise RegistryError(f"spec[{i}]: duplicate family '{family}'")
        seen_families.add(family)

        if family not in COMPUTATIONS:
            raise RegistryError(
                f"spec[{i}] '{family}': no computation registered — "
                f"known families: {sorted(COMPUTATIONS)}"
            )

        visibility = raw.get("visibility")
        if visibility not in VISIBILITY_CLASSES:
            raise RegistryError(
                f"spec[{i}] '{family}': visibility '{visibility}' not in {VISIBILITY_CLASSES}"
            )

        sources = raw.get("sources") or []
        if not sources:
            raise RegistryError(f"spec[{i}] '{family}': at least one source required")

        commodities_raw = raw.get("commodities", "all")
        if commodities_raw == "all":
            commodities = tuple(ALL_COMMODITIES)
        elif commodities_raw == "calendar":
            commodities = tuple(sorted(valid_commodities & calendar_commodities))
        else:
            unknown = set(commodities_raw) - valid_commodities
            if unknown:
                raise RegistryError(
                    f"spec[{i}] '{family}': unknown commodities {sorted(unknown)}"
                )
            commodities = tuple(commodities_raw)

        range_raw = raw.get("value_range")
        if range_raw is None:
            value_range: tuple[float | None, float | None] = (None, None)
        else:
            if len(range_raw) != 2:
                raise RegistryError(f"spec[{i}] '{family}': value_range must be [min, max]")
            value_range = (
                None if range_raw[0] is None else float(range_raw[0]),
                None if range_raw[1] is None else float(range_raw[1]),
            )

        specs.append(FeatureSpec(
            family=family,
            sources=tuple(sources),
            visibility=visibility,
            commodities=commodities,
            value_range=value_range,
            is_label=bool(raw.get("is_label", False)),
            params=raw.get("params") or {},
        ))

    logger.info("Feature registry loaded: %d families, params_hash=%s",
                len(specs), params_hash[:12])
    return FeatureRegistry(
        specs=tuple(specs),
        shared_params=shared_params,
        params_hash=params_hash,
    )
