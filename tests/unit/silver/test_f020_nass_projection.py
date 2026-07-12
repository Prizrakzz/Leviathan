"""SILVER-F020: expose NASS annual canola through projection metadata.

36 physical ``commodity=canola_ice`` parquets (1991-2026) are HIDDEN because the projection enum omits
``canola_ice``. Per the cross-lane R2 convention the checked-in registry/DDL stay == live Glue and the
GATED ``SET TBLPROPERTIES`` migration (``reports/silver_readiness/R2_SA/F020_canola_migration.json``)
carries the target enum. These tests exercise the bidirectional projection-domain validator: it flags
the current enum as hiding canola, and confirms the migration target resolves it. INV-3: no Athena
query against the projection table is performed.
"""
from __future__ import annotations

import json
from pathlib import Path

from leviathan.silver.projection_validation import (
    parse_enum_values,
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

# The NASS-annual producer maps CANOLA -> canola_ice; these are the contract slugs it physically
# writes (the R0 enum's six commodities + the canola restoration).
_PHYSICAL = [
    "corn_cbot", "soybeans_cbot", "rough_rice_cbot", "cotton",
    "soft_red_winter_wheat_cbot", "hard_red_spring_wheat_mgex", "canola_ice",
]


def _contract() -> dict:
    return load_registry().table("silver_nass_annual")


def _target_enum() -> list[str]:
    return _MIGRATION["target"]["projection.commodity.values"].split(",")


def test_migration_adds_canola_only():
    assert _MIGRATION["added_values"] == ["canola_ice"]
    assert "canola_ice" in _target_enum()


def test_migration_is_gated_and_not_applied():
    assert _MIGRATION["gated"] is True
    assert _MIGRATION["applied"] is False
    assert _MIGRATION["risk"].startswith("metadata-only")


def test_current_registry_enum_hides_canola():
    """The defect: the checked-in enum (== live Glue) hides the physical canola partitions."""
    report = validate_contract_projection(_contract(), _PHYSICAL)
    assert report.hidden_physical == ("canola_ice",)
    assert not report.ok


def test_migration_target_enum_resolves_canola():
    report = validate_projection_domain(_target_enum(), _PHYSICAL)
    assert report.hidden_physical == ()
    assert report.ok, report.problems()


def test_migration_target_is_superset_of_live_rollback():
    live = _MIGRATION["rollback_basis"]["projection.commodity.values"].split(",")
    target = _target_enum()
    assert set(live) < set(target)
    assert set(target) - set(live) == {"canola_ice"}


def test_apply_and_rollback_sql_present():
    assert any("canola_ice" in s for s in _MIGRATION["apply_sql"])
    assert all("canola_ice" not in s for s in _MIGRATION["rollback_sql"])


def test_pre_fix_enum_hides_canola_generic():
    pre_fix = [v for v in _PHYSICAL if v != "canola_ice"]
    report = validate_projection_domain(pre_fix, _PHYSICAL)
    assert report.hidden_physical == ("canola_ice",)


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
