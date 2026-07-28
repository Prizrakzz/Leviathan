"""SILVER-F082: alarms-as-code -- the alarm definitions must parse + carry the full per-alarm
contract, cover every backfillable family, and stay in sync with the terraform tfvars.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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


class TestAlarmContract:
    def test_every_alarm_has_the_required_contract_keys(self, sa, doc):
        for a in doc["alarms"]:
            missing = [k for k in sa.REQUIRED_ALARM_KEYS if k not in a]
            assert not missing, (a.get("alarm_name"), missing)

    def test_alarm_field_types_are_well_formed(self, doc):
        for a in doc["alarms"]:
            assert isinstance(a["threshold"], (int, float))
            assert isinstance(a["period_seconds"], int) and a["period_seconds"] > 0
            assert isinstance(a["evaluation_periods"], int) and a["evaluation_periods"] >= 1
            assert isinstance(a["dimensions"], dict)
            assert a["treat_missing_data"] in {"breaching", "notBreaching", "missing", "ignore"}
            assert a["comparison_operator"].startswith(("GreaterThan", "LessThan"))
            assert a["metric_namespace"] == "Leviathan/Silver"
            assert a["retention_days"] > 0
            assert a["dedup_key"]
            assert a["oncall_destination"]

    def test_alarm_names_unique(self, doc):
        names = [a["alarm_name"] for a in doc["alarms"]]
        assert len(names) == len(set(names))


class TestFailureModeCoverage:
    def test_three_failure_mode_classes_present(self, doc):
        modes = doc["alarms_by_failure_mode"]
        assert modes["batch_job_failed"] >= 1
        assert modes["freshness_sla_breach"] >= 1
        assert modes["value_census_regression"] == 1

    def test_every_backfillable_family_has_batch_and_freshness_alarm(self, sa, doc):
        from leviathan.silver.dag_catalog import build_catalog
        families = {k for k, f in build_catalog().items() if f.backfillable}
        batch = {a["family"] for a in doc["alarms"] if a["failure_mode"] == "batch_job_failed"}
        fresh = {a["family"] for a in doc["alarms"] if a["failure_mode"] == "freshness_sla_breach"}
        assert batch == families
        assert fresh == families

    def test_model_output_has_no_batch_alarm(self, doc):
        batch_families = {a["family"] for a in doc["alarms"] if a["failure_mode"] == "batch_job_failed"}
        assert "model_output" not in batch_families

    def test_value_census_regression_is_p1(self, sa, doc):
        census = [a for a in doc["alarms"] if a["failure_mode"] == "value_census_regression"][0]
        assert census["severity"] == sa.SEV_P1
        assert census["metric_name"] == "ValueCensusHardFailTables"
        assert census["threshold"] == 0

    def test_freshness_threshold_matches_family_ceiling(self, sa, doc):
        from leviathan.silver.dag_catalog import build_catalog
        catalog = build_catalog()
        for a in doc["alarms"]:
            if a["failure_mode"] == "freshness_sla_breach":
                assert a["threshold"] == catalog[a["family"]].max_sla_lag_days


class TestTfvars:
    def test_tfvars_shape(self, sa):
        tf = sa.build_tfvars()
        assert isinstance(tf["silver_batch_families"], list)
        assert isinstance(tf["silver_freshness_slas"], dict)
        assert set(tf["silver_freshness_slas"]) == set(tf["silver_batch_families"])
        assert tf["silver_metric_namespace"] == "Leviathan/Silver"

    def test_tfvars_excludes_generation_only(self, sa):
        assert "model_output" not in sa.build_tfvars()["silver_batch_families"]

    def test_tfvars_excludes_pre_publish_families(self, sa):
        # A family whose table has had no first canonical publish emits NO FreshnessLagDays datapoint
        # (freshness_poller: EMPTY canonical prefix -> no datapoint), and the per-family freshness
        # alarm is treat_missing_data="breaching" -- so declaring it would instant-breach the shared
        # on-call topic on the next apply and page continuously until the producer lands.
        tf = sa.build_tfvars()
        assert sa.PRE_PUBLISH_FAMILIES, "the exclusion set must stay explicit, not empty-by-accident"
        for fam in sa.PRE_PUBLISH_FAMILIES:
            assert fam not in tf["silver_batch_families"]
            assert fam not in tf["silver_freshness_slas"]

    def test_pre_publish_families_still_have_no_producer(self, sa):
        # The removal trigger, pinned: an entry may only leave PRE_PUBLISH_FAMILIES once its family
        # actually publishes. This FAILS the moment a producer transform lands (forcing the entry out
        # + a tfvars re-emit + an apply), and it FAILS today if someone parks a live family here.
        from leviathan.silver.dag_catalog import build_catalog
        from leviathan.silver.registry import load_registry
        reg = load_registry()
        catalog = build_catalog(reg)
        for fam in sa.PRE_PUBLISH_FAMILIES:
            assert fam in catalog, f"{fam} is not a DAG family"
            for table in catalog[fam].tables:
                transform = (reg.table(table).get("producer") or {}).get("transform")
                assert transform is None, (
                    f"{table} now has a producer transform ({transform}) -- drop {fam!r} from "
                    f"silver_alarms.PRE_PUBLISH_FAMILIES, re-emit the tfvars and apply, so its "
                    f"batch-failure + freshness alarms actually arm")

    def test_emitted_tfvars_file_matches_current_registry(self, sa):
        # the checked-in auto.tfvars.json must equal a fresh emit (no drift).
        import json
        path = _REPO / "infra" / "terraform" / "envs" / "dev" / "silver_observability.auto.tfvars.json"
        if not path.exists():
            pytest.skip("tfvars not emitted in this tree")
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk == sa.build_tfvars()
