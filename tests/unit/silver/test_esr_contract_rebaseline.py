"""SILVER-F030: the ESR contract re-baseline is codified in the operational registry.

Asserts the frozen semantic ADR at the CONTRACT level (registry.py loads the YAML the generator
emits): the true physical natural key, changes_1000mt deprecated, publication-lag/PIT semantics
reconciled against the numbers TableSpec, the slug-coverage boundary, and the additive-migration
artifacts. AWS-free; pure registry + reconcile reads under the F002 isolation guard.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from leviathan.silver.registry import load_registry
from leviathan.silver import reconcile as R

_REPO = Path(__file__).resolve().parents[3]
_ADR = _REPO / "reports" / "silver_readiness" / "R2_esr" / "F030_esr_adr.json"
_MIGRATION = _REPO / "sql" / "athena" / "migrations" / "silver" / "silver_esr_f030_additive.sql"

_ESR_KEY = ["commodity_code", "market_year", "as_of_date", "country_code", "week_ending_date"]


@pytest.fixture(scope="module")
def reg():
    return load_registry()


class TestGrainAndNaturalKey:
    def test_silver_esr_natural_key_is_the_true_physical_key(self, reg):
        assert reg.table("silver_esr")["natural_key"] == _ESR_KEY

    def test_compact_natural_key_matches(self, reg):
        assert reg.table("silver_esr_compact")["natural_key"] == _ESR_KEY

    def test_required_nonnull_tracks_the_key(self, reg):
        assert reg.table("silver_esr")["required_nonnull"] == _ESR_KEY

    def test_partition_dims_are_registered_not_projected(self, reg):
        for name in ("silver_esr", "silver_esr_compact"):
            c = reg.table(name)
            assert c["partition_mode"] == "registered"
            assert c["projection"] == "forbidden"
            assert all(pk.get("projected") is False for pk in c["partition_keys"])


class TestChangesDeprecated:
    def test_changes_1000mt_is_deprecated_on_both(self, reg):
        for name in ("silver_esr", "silver_esr_compact"):
            col = next(c for c in reg.table(name)["physical_columns"]
                       if c["name"] == "changes_1000mt")
            assert col.get("deprecated") is True, name
            assert col["nullable"] is True, name

    def test_changes_still_a_registry_value_column(self, reg):
        # deprecated != removed: it stays a declared value column (nullable, never synthesized).
        assert "changes_1000mt" in reg.value_columns("silver_esr")


class TestPublicationLagReconciled:
    def test_pit_semantics_match_numbers_tablespec(self, reg):
        divs = R.reconcile_numbers(reg)
        esr = [d for d in divs if d.table == "silver_esr"]
        assert esr == [], f"ESR publication_lag / PIT divergence vs the numbers TableSpec: {esr}"

    def test_lag_fields_are_frozen(self, reg):
        # BF-W2 SILVER-F031 supersedes the F030 v1 interim (data_date + 7d): per-week as_of vintages,
        # the as_of stamp IS the publication event -> vintage semantics, lag 0 (runbook ESR-R2/R4).
        c = reg.table("silver_esr")
        assert c["knowledge_date_col"] == "as_of_date"
        assert c["knowledge_semantics"] == "vintage"
        assert c["publication_lag_days"] == 0

    def test_whole_registry_reconciles_clean(self, reg):
        assert R.unallowed(R.reconcile_all(reg)) == []


class TestCoverageBoundaryAndAdrArtifacts:
    def test_notes_record_the_slug_coverage_boundary(self, reg):
        notes = reg.table("silver_esr")["notes"]
        assert "all_wheat" in notes and "grain_sorghum" in notes and "white_wheat" in notes
        assert "NOT contract" in notes

    def test_adr_record_exists_and_freezes_the_decisions(self):
        adr = json.loads(_ADR.read_text(encoding="utf-8"))
        assert adr["status"] == "frozen"
        assert adr["field_decisions"]["changes_1000mt"]["decision"].startswith("DEPRECATED")
        # the 5 target additive net-commitment columns are named for BF-W2.
        cols = {c["name"] for c in adr["target_additive_schema_bf_w2"]["columns"]}
        assert cols == {
            "accumulated_exports_1000mt", "current_my_net_sales_1000mt",
            "current_my_total_commitment_1000mt", "next_my_outstanding_sales_1000mt",
            "next_my_net_sales_1000mt",
        }

    def test_additive_migration_is_additive_only(self):
        sql = _MIGRATION.read_text(encoding="utf-8").lower()
        assert "add columns" in sql
        # additive-only: no destructive verbs.
        for banned in ("drop table", "drop column", "drop partition", "rename"):
            assert banned not in sql, banned
        assert "not applied" in sql  # the R2 gating note survives
