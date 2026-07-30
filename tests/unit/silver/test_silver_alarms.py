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
        #
        # THE SET IS EMPTY AS OF 2026-07-29 and that is EARNED, not drift: `futures_eod` was its one
        # member and it left through the front door -- canonical hand-published for all five legs,
        # union gates PASS, both chains flipped to promote_mode=autonomous so the canonical prefix
        # now advances nightly. The old `assert sa.PRE_PUBLISH_FAMILIES` guard was deleted here in
        # that same commit, exactly as its own comment instructed; keeping it would have made the
        # legitimate emptying impossible to express.
        #
        # What is asserted now is the RULE rather than a census of its members, so this test keeps
        # working for the next table registered ahead of its producer: whatever is in the set is out
        # of the tfvars. The evidence-derived interlock (which fails BOTH ways) is
        # test_pre_publish_membership_is_bound_to_the_canonical_publish_marker below.
        tf = sa.build_tfvars()
        for fam in sa.PRE_PUBLISH_FAMILIES:
            assert fam not in tf["silver_batch_families"]
            assert fam not in tf["silver_freshness_slas"]
        # And the released family is now genuinely armed -- the other half of the same fact.
        assert "futures_eod" not in sa.PRE_PUBLISH_FAMILIES
        assert "futures_eod" in tf["silver_batch_families"]
        assert tf["silver_freshness_slas"]["futures_eod"] > 0

    def test_pre_publish_membership_is_bound_to_the_canonical_publish_marker(self, sa):
        """THE REMOVAL TRIGGER, PINNED IN BOTH DIRECTIONS -- and the trigger is the first CANONICAL
        PUBLISH, not the producer code landing.

        This deliberately does NOT read `producer.transform`. That was the earlier form, and it is
        the WRONG signal twice over: W1a/W1b landed five futures_eod producer transforms without a
        single canonical byte, so the assertion only still passed because the generated registry
        field is stale -- and the moment the registry is regenerated it would have FORCED
        `futures_eod` out of the exclusion set, arming a treat_missing_data="breaching" freshness
        alarm on an EMPTY canonical prefix. That is precisely the pager the set exists to prevent.

        The marker used instead is two independent facts in two other files, so this cannot be
        satisfied by editing silver_alarms.py alone:
          * every DAG schedule for the family is still `promote_mode: stop_and_notify` -- the
            machine publishes SHADOW ONLY and a shadow publish never resets the freshness clock, so
            canonical cannot be advancing; and
          * readiness_certify.PRE_PUBLISH_PACKAGE still carries one of the family's tables, whose
            own documented removal condition is first canonical publish AND census.

        FAILS if a family leaves PRE_PUBLISH_FAMILIES while both are still true (removal ahead of
        the publish -- the W1a hazard), and FAILS if a family lingers here after its chains are
        flipped to `autonomous` (removal owed, alarms never armed).
        """
        import json
        from jobs.audit.readiness_certify import PRE_PUBLISH_PACKAGE
        from leviathan.silver.dag_catalog import build_catalog

        catalog = build_catalog()
        family_of = {t: fam for fam, f in catalog.items() for t in f.tables}

        promote_modes: dict[str, set] = {}
        for p in sorted((_REPO / "configs" / "silver" / "dags").glob("*.json")):
            if p.name.endswith(".schema.json"):
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
            if "family" in d and "promote_mode" in d:
                promote_modes.setdefault(d["family"], set()).add(d["promote_mode"])

        # A family is SHADOW-ONLY when it has at least one schedule and every one of them is
        # stop_and_notify. A family with no schedule at all is not evidence either way.
        shadow_only = {fam for fam, modes in promote_modes.items() if modes == {"stop_and_notify"}}
        declared_pre_publish = {family_of[t] for t in PRE_PUBLISH_PACKAGE if t in family_of}

        # (1) never remove early: still shadow-only AND still declared pre-publish -> must be here.
        for fam in sorted(declared_pre_publish & shadow_only):
            assert fam in sa.PRE_PUBLISH_FAMILIES, (
                f"{fam!r} has NO canonical publish marker -- every one of its schedules is still "
                f"promote_mode=stop_and_notify (shadow only) and readiness_certify."
                f"PRE_PUBLISH_PACKAGE still lists its table -- so it MUST stay in "
                f"silver_alarms.PRE_PUBLISH_FAMILIES. Removing it here arms a "
                f"treat_missing_data='breaching' freshness alarm on an EMPTY canonical prefix, "
                f"which breaches on the next apply of ANY unrelated change in envs/dev. Correct "
                f"order: backfill -> promote canonical BY HAND -> flip the descriptors to "
                f"promote_mode=autonomous -> THEN drop it here, re-emit the tfvars, and apply.")

        # (2) never linger: once a schedule is autonomous, canonical advances nightly and the
        #     exclusion is a hole in the on-call coverage.
        for fam in sorted(sa.PRE_PUBLISH_FAMILIES):
            assert fam in catalog, f"{fam} is not a DAG family"
            if fam in promote_modes:
                assert fam in shadow_only, (
                    f"{fam!r} now has a schedule at promote_mode={sorted(promote_modes[fam])} -- "
                    f"canonical advances on its own, so drop {fam!r} from PRE_PUBLISH_FAMILIES, "
                    f"re-emit the tfvars and apply so its batch-failure + freshness alarms arm")

    def test_emitted_tfvars_file_matches_current_registry(self, sa):
        # the checked-in auto.tfvars.json must equal a fresh emit (no drift).
        import json
        path = _REPO / "infra" / "terraform" / "envs" / "dev" / "silver_observability.auto.tfvars.json"
        if not path.exists():
            pytest.skip("tfvars not emitted in this tree")
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk == sa.build_tfvars()
