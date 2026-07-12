"""Bidirectional projection-domain validation for legacy-quarantined projected silver tables.

SILVER-F020: a partition-projection enum (``projection.<key>.values``) is a CLOSED domain -- Athena
only resolves partition values listed in it. When the physical S3 tree carries a ``commodity=X``
directory whose value is absent from the enum (the ``silver_nass_annual`` canola_ice defect), that
partition's data is INVISIBLE to every consumer. The reverse -- an enum value with no physical data
-- is benign only when it is a deliberately pre-declared future value.

This module validates both directions WITHOUT querying the projection table (INV-3: never
``start-query-execution`` against a projection.* surface). The physical values are supplied by the
caller (a bounded S3 ``list-objects`` delimiter probe / the R0 census evidence), never inferred from
the enum's own range.

  * HIDDEN physical values (physical - catalog)                -> FATAL (data is unreachable).
  * catalog-only values (catalog - physical - allow_future)    -> violation unless allow-listed.

Pure + AWS-free.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProjectionDomainReport:
    """The verdict of one projection-key domain check."""

    projection_key: str
    catalog_values: tuple[str, ...]
    physical_values: tuple[str, ...]
    hidden_physical: tuple[str, ...] = field(default=())   # physical but NOT in the enum (FATAL)
    catalog_only: tuple[str, ...] = field(default=())      # enum but no physical data (needs allow)
    allow_future: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.hidden_physical and not self.catalog_only

    def problems(self) -> list[str]:
        out: list[str] = []
        if self.hidden_physical:
            out.append(
                f"{self.projection_key}: physical partition value(s) hidden by the projection enum "
                f"(data unreachable): {list(self.hidden_physical)}"
            )
        if self.catalog_only:
            out.append(
                f"{self.projection_key}: enum value(s) with NO physical data and not allow-listed "
                f"as future: {list(self.catalog_only)}"
            )
        return out


def parse_enum_values(contract: dict, projection_key: str) -> list[str]:
    """Ordered enum values for a projection key from a registry contract's ``projection_domains``."""
    domains = contract.get("projection_domains") or {}
    raw = domains.get(projection_key, "")
    return [v for v in str(raw).split(",") if v]


def validate_projection_domain(
    catalog_values,
    physical_values,
    *,
    projection_key: str = "projection.commodity.values",
    allow_future=(),
) -> ProjectionDomainReport:
    """Bidirectional check of a projection enum against the physically-present partition values.

    ``catalog_values`` is the enum (registry/Glue). ``physical_values`` is the set of partition
    values actually present in S3. ``allow_future`` are enum values deliberately pre-declared with no
    physical data yet (they suppress the catalog-only violation, never the hidden-physical one)."""
    cat = list(dict.fromkeys(catalog_values))          # de-dupe, keep order
    phys = list(dict.fromkeys(physical_values))
    cat_set, phys_set, fut_set = set(cat), set(phys), set(allow_future)
    hidden = tuple(v for v in phys if v not in cat_set)
    cat_only = tuple(v for v in cat if v not in phys_set and v not in fut_set)
    return ProjectionDomainReport(
        projection_key=projection_key,
        catalog_values=tuple(cat),
        physical_values=tuple(phys),
        hidden_physical=hidden,
        catalog_only=cat_only,
        allow_future=tuple(allow_future),
    )


def validate_contract_projection(
    contract: dict,
    physical_values,
    *,
    projection_key: str = "projection.commodity.values",
    allow_future=(),
) -> ProjectionDomainReport:
    """Convenience: validate a registry contract's enum for ``projection_key`` against physical values."""
    return validate_projection_domain(
        parse_enum_values(contract, projection_key),
        physical_values,
        projection_key=projection_key,
        allow_future=allow_future,
    )
