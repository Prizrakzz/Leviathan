"""SILVER-F082 freshness-audit additions (2026-07-23):
  * the usda_nass family ceiling drops 170 -> 14 (the registry max_lag_days=170 that masked the
    stalled weekly crop_progress producer is corrected via dag_catalog.FRESHNESS_LAG_OVERRIDES);
  * per-TABLE freshness alarms exist for the four burned tables, each fully-specified, uniquely
    named, breaching, at its justified ceiling;
  * the emitted tfvars carry the per-table map and the corrected family ceiling.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from leviathan.silver.dag_catalog import FRESHNESS_LAG_OVERRIDES, build_catalog

_REPO = Path(__file__).resolve().parents[3]
_MOD = _REPO / "jobs" / "observability" / "silver_alarms.py"


@pytest.fixture(scope="module")
def sa():
    spec = importlib.util.spec_from_file_location("silver_alarms", _MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doc(sa):
    return sa.build_document()


class TestUsdaNassCorrection:
    def test_override_targets_crop_progress(self):
        assert FRESHNESS_LAG_OVERRIDES.get("silver_nass_crop_progress") == 14

    def test_family_ceiling_drops_to_14(self):
        # The mask (registry max_lag_days=170 on a weekly cadence) is corrected -> tightest member 14.
        assert build_catalog()["usda_nass"].max_sla_lag_days == 14

    def test_override_only_tightens(self):
        # Applying the override must never LOOSEN a family ceiling vs the raw registry-derived value.
        cat = build_catalog()
        assert cat["usda_nass"].max_sla_lag_days <= 170


class TestPerTableAlarms:
    def test_one_alarm_per_burned_table(self, sa, doc):
        table_alarms = [a for a in doc["alarms"] if a["failure_mode"] == "freshness_sla_breach_table"]
        assert {a["table"] for a in table_alarms} == set(sa.BURNED_TABLE_FRESHNESS)
        assert len(table_alarms) == 4

    def test_thresholds_and_dimensions(self, sa, doc):
        by_table = {a["table"]: a for a in doc["alarms"] if a["failure_mode"] == "freshness_sla_breach_table"}
        for table, (family, max_lag, _basis) in sa.BURNED_TABLE_FRESHNESS.items():
            a = by_table[table]
            assert a["threshold"] == max_lag
            # Single-dim {Table}: MUST match the poller's {Table} datapoint. A {Table,Family} composite
            # is never emitted (freshness.metric_data_for writes {Table} and {Family} SEPARATELY), so a
            # composite-dimensioned alarm would get no data and, under breaching, page permanently.
            assert a["dimensions"] == {"Table": table}
            assert a["family"] == family  # family is carried as a field (description), not a dimension
            assert a["metric_name"] == "FreshnessLagDays"
            assert a["treat_missing_data"] == "breaching"

    def test_specified_thresholds(self, doc):
        by_table = {a["table"]: a for a in doc["alarms"] if a.get("failure_mode") == "freshness_sla_breach_table"}
        assert by_table["silver_nass_crop_progress"]["threshold"] == 14
        assert by_table["silver_fgis"]["threshold"] == 14
        assert by_table["silver_unica_biweekly_season_history"]["threshold"] == 21
        assert by_table["silver_nass_citrus"]["threshold"] == 400

    def test_per_table_alarms_carry_full_contract(self, sa, doc):
        table_alarms = [a for a in doc["alarms"] if a["failure_mode"] == "freshness_sla_breach_table"]
        for a in table_alarms:
            assert not [k for k in sa.REQUIRED_ALARM_KEYS if k not in a]

    def test_all_alarm_names_unique_incl_per_table(self, doc):
        names = [a["alarm_name"] for a in doc["alarms"]]
        assert len(names) == len(set(names))

    def test_two_burned_tables_share_family_but_not_name(self, doc):
        # crop_progress + citrus are both usda_nass -> the name must key on the TABLE, not the family.
        nass = [a for a in doc["alarms"]
                if a["failure_mode"] == "freshness_sla_breach_table" and a["family"] == "usda_nass"]
        assert len(nass) == 2
        assert len({a["alarm_name"] for a in nass}) == 2


class TestTfvars:
    def test_family_ceiling_corrected_in_tfvars(self, sa):
        assert sa.build_tfvars()["silver_freshness_slas"]["usda_nass"] == 14

    def test_table_freshness_map_present(self, sa):
        tfm = sa.build_tfvars()["silver_table_freshness_slas"]
        assert set(tfm) == set(sa.BURNED_TABLE_FRESHNESS)
        for table, (family, threshold, basis) in sa.BURNED_TABLE_FRESHNESS.items():
            assert tfm[table] == {"family": family, "threshold": threshold, "basis": basis}

    def test_emitted_tfvars_file_matches(self, sa):
        import json
        path = _REPO / "infra" / "terraform" / "envs" / "dev" / "silver_observability.auto.tfvars.json"
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk == sa.build_tfvars()
