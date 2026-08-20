"""SILVER-F020: NASS annual projection-enum visibility -- RESOLVED 2026-08-20.

HISTORY: 36 physical ``commodity=canola_ice`` parquets (1991-2026) were HIDDEN because the projection
enum omitted ``canola_ice``. The gated canola-only migration
(``reports/silver_readiness/R2_SA/F020_canola_migration.json``) was RETIRED UNAPPLIED when the D-EC
wheat-lane repair ALTERed live Glue to the full TEN-value enum (a superset of its target) in the same
change as the canonical promote that landed the wheat and cotton-class partitions. Per the R2
convention the checked-in registry enum mirrors live Glue, so these tests now pin the RESOLVED state:
the registry enum exposes every physical partition, the historical migration record stays internally
consistent and marked superseded, and the bidirectional projection-domain validator still catches both
defect directions on synthetic inputs. INV-3: no Athena query against the projection table is performed.
"""
from __future__ import annotations

import json
from pathlib import Path

from leviathan.silver.projection_validation import (
    validate_contract_projection,
    validate_projection_domain,
)
from leviathan.silver.registry import load_registry

_REPO = Path(__file__).resolve().parents[3]
_MIGRATION = json.loads(
    (_REPO / "reports" / "silver_readiness" / "R2_SA" / "F020_canola_migration.json").read_text(
        encoding="utf-8"
    )
)

# The contract slugs the producer physically writes as of the 2026-08-20 canonical promote --
# verified by S3 listing (ten commodity= partitions).
_PHYSICAL = [
    "corn_cbot", "soybeans_cbot", "rough_rice_cbot", "cotton",
    "soft_red_winter_wheat_cbot", "hard_red_spring_wheat_mgex", "canola_ice",
    "cottonseed", "upland_cotton", "pima_cotton",
]

# What the estate physically held when the canola-only migration was authored (2026-07-12):
# the R0 six plus the then-hidden canola.
_PHYSICAL_AT_AUTHORING = _PHYSICAL[:7]


def _contract() -> dict:
    return load_registry().table("silver_nass_annual")


def _registry_enum() -> list[str]:
    return _contract()["projection_domains"]["projection.commodity.values"].split(",")


def test_registry_enum_exposes_every_physical_partition():
    """The RESOLVED state: checked-in enum (== live Glue, R2 convention) hides nothing."""
    report = validate_contract_projection(_contract(), _PHYSICAL)
    assert report.hidden_physical == ()
    assert report.ok, report.problems()


def test_registry_enum_is_exactly_the_physical_set():
    """No catalog-only promises either: the enum is the measured ten, nothing more."""
    assert sorted(_registry_enum()) == sorted(_PHYSICAL)


def test_historical_migration_record_is_superseded_not_applied():
    """The canola-only migration was retired unapplied when the ten-value ALTER superseded it."""
    assert _MIGRATION["applied"] is False
    assert _MIGRATION["gated"] is True
    assert "superseded" in _MIGRATION and "RETIRED UNAPPLIED" in _MIGRATION["superseded"]


def test_historical_record_stays_internally_consistent():
    assert _MIGRATION["added_values"] == ["canola_ice"]
    target = _MIGRATION["target"]["projection.commodity.values"].split(",")
    live_then = _MIGRATION["rollback_basis"]["projection.commodity.values"].split(",")
    assert set(live_then) < set(target)
    assert set(target) - set(live_then) == {"canola_ice"}
    assert any("canola_ice" in s for s in _MIGRATION["apply_sql"])
    assert all("canola_ice" not in s for s in _MIGRATION["rollback_sql"])


def test_historical_target_resolved_the_then_physical_set():
    """Against what physically existed at authoring time, the migration target was complete."""
    target = _MIGRATION["target"]["projection.commodity.values"].split(",")
    report = validate_projection_domain(target, _PHYSICAL_AT_AUTHORING)
    assert report.hidden_physical == ()
    assert report.ok, report.problems()


def test_current_enum_is_a_superset_of_the_retired_target():
    """The supersession claim, checked: today's enum contains the retired migration's whole target."""
    target = set(_MIGRATION["target"]["projection.commodity.values"].split(","))
    assert target < set(_registry_enum())
    assert set(_registry_enum()) - target == {"cottonseed", "upland_cotton", "pima_cotton"}


def test_validator_still_catches_a_hiding_enum():
    """The defect direction F020 existed for, kept alive on synthetic input."""
    pre_fix = [v for v in _PHYSICAL if v != "canola_ice"]
    report = validate_projection_domain(pre_fix, _PHYSICAL)
    assert report.hidden_physical == ("canola_ice",)
    assert not report.ok


def test_catalog_only_value_needs_allow_future():
    enum = _PHYSICAL + ["frozen_orange_juice"]
    assert validate_projection_domain(enum, _PHYSICAL).catalog_only == ("frozen_orange_juice",)
    assert validate_projection_domain(enum, _PHYSICAL, allow_future=["frozen_orange_juice"]).ok


def test_hidden_physical_beats_allow_future():
    report = validate_projection_domain(
        ["corn_cbot"], ["corn_cbot", "canola_ice"], allow_future=["canola_ice"]
    )
    assert report.hidden_physical == ("canola_ice",)
    assert not report.ok
