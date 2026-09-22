"""SILVER-F082: alarms-as-code -- the alarm definitions must parse + carry the full per-alarm
contract, cover every backfillable family, and stay in sync with the terraform tfvars.
"""
from __future__ import annotations

import importlib.util
import re
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


class TestTheTextAndCorpusLivenessAlarms:
    """Round 2, handed by the text/corpus lane. DOCUMENTED here; the apply is gated on a datapoint.

    The three metrics do not exist in the account today -- measured 2026-09-22, `list-metrics
    --namespace Leviathan/Silver` returns eleven names and none of them starts with Corpus or
    Wasde -- because the emitters ship inside images whose pins predate the change.
    """

    def _one(self, doc, mode):
        got = [a for a in doc["alarms"] if a["failure_mode"] == mode]
        assert len(got) == 1, mode
        return got[0]

    def test_the_fold_liveness_bound_is_the_derived_one_SPENT_AS_DAYS(self, doc):
        # 35 is not a preference. The fold schedule is cron(0 8 22 * ? *), so the longest HEALTHY
        # gap is 31 days (22 Jul -> 22 Aug); a 30-day bound would go red across every 31-day month
        # pair. 35 = that worst case + a four-day grace, reachable only by a MISSED fire.
        #
        # ROUND 3: the 35 is UNCHANGED and is now spent as 35 DAYS OF AGE, not 35 evaluation
        # PERIODS. Round 2 asked for 86,400 x 35 = 3,024,000 s and CloudWatch refuses anything over
        # 604,800 -- so the alarm this deck certified as delivered could never have been created.
        from leviathan.silver.freshness import ledger_gauge

        gauge = ledger_gauge("corpus_fold")
        a = self._one(doc, "corpus_fold_liveness")
        assert a["metric_name"] == gauge.metric_name == "CorpusFoldAgeDays"
        assert a["dimensions"] == {"Family": "graphrag_evidence"}
        assert (a["evaluation_periods"], a["datapoints_to_alarm"]) == (1, 1)
        assert a["period_seconds"] == 86400
        assert a["statistic"] == "Maximum"
        assert a["comparison_operator"] == "GreaterThanThreshold"
        # THE ONE NUMBER: the alarm reads the gauge declaration the poller prints beside its
        # reading, so the threshold and the bound in the log line can never drift apart.
        assert a["threshold"] == gauge.threshold_days == 35.0
        # breaching means ONE thing on a daily gauge: the POLLER published no age -- it did not run
        # or could not read the ledger. It no longer depends on the monthly fold emitting anything.
        assert a["treat_missing_data"] == "breaching"
        # The basis travels with the alarm, so an operator reading the console gets the derivation.
        assert "31 days" in a["description"] and "four-day grace" in a["description"]

    def test_the_work_alarm_counts_slices_and_never_docs(self, doc):
        # THE REFUTED NAME. A fold is a re-derivation from the chunk cache, so docs.written is 0 BY
        # CONSTRUCTION on a perfect fold: the 2026-08-21 manifest records docs {"written": 0} beside
        # 196 slice objects and 2,742,847 rows. An alarm on DocsWritten would have paged on a
        # 4h29m fold that did all of that work.
        a = self._one(doc, "corpus_fold_wrote_nothing")
        assert a["metric_name"] == "CorpusFoldSlicesWritten"
        assert "CorpusFoldDocsWritten" not in str(doc)
        assert a["treat_missing_data"] == "notBreaching"   # liveness is the OTHER alarm's job
        assert (a["evaluation_periods"], a["datapoints_to_alarm"]) == (1, 1)
        assert a["comparison_operator"] == "LessThanThreshold" and a["threshold"] == 1

    def test_the_wasde_text_leg_is_watched_by_its_error_counter(self, doc):
        a = self._one(doc, "wasde_text_errors")
        assert a["metric_name"] == "WasdeTextErrors"
        assert a["dimensions"] == {"Family": "usda_wasde"}
        # ROUND 3 (handed, H-L5-R3-1): > 1, not >= 1. The leg TOLERATES one document error by
        # design and exits 0, so an alarm at >= 1 would page on the tolerated state -- the way an
        # alarm teaches its operators to ignore it. Maximum, never Sum: six fires a month, and a
        # daily Sum would add two fires together and invent a breach no single fire had.
        assert a["comparison_operator"] == "GreaterThanThreshold" and a["threshold"] == 0
        assert a["statistic"] == "Maximum"
        assert a["treat_missing_data"] == "notBreaching"   # the family fires on days 8-13 only
        # NOT DocsWritten == 0: a month whose document is already current writes 0, correctly.
        assert "WasdeTextDocsWritten" not in a["metric_name"]

    def test_the_error_threshold_IS_the_legs_own_constant(self, doc):
        # ONE NUMBER IN TWO FILES, joined, and the join is MANDATORY (closing review MAJOR-R4-1: the
        # first form of this pin matched a constant the producer had RETIRED, its body sat under
        # `if m:`, and the deck stayed green over a live false green). The producer spells the
        # number ONCE as WASDE_TEXT_ERROR_ALARM_THRESHOLD; a hand that moves it has to come back here.
        a = self._one(doc, "wasde_text_errors")
        src = _REPO / "jobs" / "batch" / "wasde_text_task.py"
        assert src.exists(), src
        text = src.read_text(encoding="utf-8")
        assert re.search(r"^MAX_TOLERATED_DOC_FAILURES\s*=", text, re.M) is None, "a retired constant"
        m = re.search(r"^WASDE_TEXT_ERROR_ALARM_THRESHOLD\s*=\s*(\d+)", text, re.M)
        assert m is not None, "the leg must spell its alarm number once, by this name"
        assert a["threshold"] == float(m.group(1)), (a["threshold"], m.group(1))

    def test_the_INFRA_class_has_its_own_alarm_and_it_pages_on_the_first_one(self, doc):
        # closing review MAJOR-R4-1: an S3 throttle exits 1 on the leg AND must be readable on the
        # board apart from a document failure. Maximum > 0, quiet on the 25 days the family sleeps.
        a = self._one(doc, "wasde_text_infra_errors")
        assert a["metric_name"] == "WasdeTextInfraErrors" and a["statistic"] == "Maximum"
        assert a["comparison_operator"] == "GreaterThanThreshold" and a["threshold"] == 0
        assert a["treat_missing_data"] == "notBreaching"

    def test_the_text_legs_OTHER_half_is_an_age_gauge_on_the_PARTITION(self, doc):
        # The error counter cannot see a chain that never fires: it raises nothing, writes nothing
        # and counts nothing. The brief asked for "missing data over 40 days" -- 86,400 x 40 =
        # 3,456,000 s, which CloudWatch refuses -- so it is the same daily age gauge as the fold's.
        from leviathan.silver.freshness import ledger_gauge

        gauge = ledger_gauge("wasde_text")
        a = self._one(doc, "wasde_text_tip_stale")
        assert a["metric_name"] == gauge.metric_name == "WasdeTextAgeDays"
        assert a["dimensions"] == {"Family": "usda_wasde"}
        assert (a["period_seconds"], a["evaluation_periods"]) == (86400, 1)
        assert a["comparison_operator"] == "GreaterThanThreshold"
        assert a["threshold"] == gauge.threshold_days == 40.0
        assert a["treat_missing_data"] == "breaching"     # an unreadable prefix is a blindness
        # THE MEASUREMENT TRAVELS WITH THE ALARM: an operator reading the console is told why this
        # gauge reads the key and not the object, and that red on arrival is intended.
        assert "release_date" in a["description"] and "33.2" in a["description"]
        assert "RED ON ARRIVAL" in a["description"]
        assert gauge.partition_key == "release_date"

    def test_none_of_them_reaches_the_applied_variables(self, sa):
        # THE GATE, asserted rather than trusted to a comment: an alarm whose metric has never
        # published may not be created, because treat_missing_data="breaching" would make it red on
        # the apply that creates it. They enter the tfvars only after one fire emits.
        import json

        tf = json.dumps(sa.build_tfvars())
        assert "Corpus" not in tf and "WasdeText" not in tf

    def test_the_liveness_alarm_no_longer_depends_on_the_job_it_watches(self, doc, sa):
        # The shape defect underneath M-A, stated as a property: the alarm that answers "did the
        # monthly job die" must not be fed by the monthly job. Round 2's was (CorpusFoldRuns, from
        # corpus_fold_task), which is why it needed a 35-period window and treat_missing_data to
        # say anything at all. Round 3's is fed by the DAILY poller.
        a = self._one(doc, "corpus_fold_liveness")
        assert "freshness_poller_task.py" in a["description"]
        assert "corpus_fold_task.py" not in a["description"]
        # and the work alarm still IS fed by the job, because "it ran and did nothing" is a fact
        # only the job can report.
        assert "corpus_fold_task.py" in self._one(doc, "corpus_fold_wrote_nothing")["description"]

    def test_the_optional_contract_field_never_changed_an_existing_alarm(self, sa, doc):
        # datapoints_to_alarm is OPTIONAL and omitted by default, so every alarm that predates it
        # is byte-identical; CloudWatch defaults it to evaluation_periods.
        carriers = {a["failure_mode"] for a in doc["alarms"] if "datapoints_to_alarm" in a}
        assert carriers == {"corpus_fold_liveness", "corpus_fold_wrote_nothing", "wasde_text_infra_errors",
                            "wasde_text_errors", "wasde_text_tip_stale"}
        for a in doc["alarms"]:
            for key in sa.REQUIRED_ALARM_KEYS:
                assert key in a, (a["alarm_name"], key)


# ---------------------------------------------------------------------------
# ROUND 3 (adversarial review M-A / M-B, 2026-09-22). THE CLASS THAT MUST NOT RECUR: AN ALARM
# SHAPE CLOUDWATCH REFUSES.
#
# Round 2 put `corpus_fold_liveness` at period 86400 x evaluation_periods 35 = 3,024,000 s into the
# document, into a paste-ready HCL handed to the owner and into five GREEN unit tests, and
# `envs/dev/schedule_corpus.tf::corpus_lane_liveness` put 86,400 x 10 = 864,000 s into a 52-add
# plan the owner was asked to apply. PutMetricAlarm refuses both. Nothing between the choice and
# `terraform apply` could say no -- not the document, not the tfvars, not a plan that exited 0,
# because a PLAN does not call PutMetricAlarm.
#
# These tests are that no, in three places: the BOUND itself (read out of botocore's own service
# model, so it cannot be a hand-copied number that rots), every alarm the GENERATOR writes, and
# every alarm resource in the terraform TREE -- including the ones this lane does not own.
# ---------------------------------------------------------------------------
class TestNoAlarmAsksForAWindowCloudWatchRefuses:
    TF_ROOT = Path(__file__).resolve().parents[3] / "infra" / "terraform"
    # The ONE file whose alarm shapes are generated (values arrive through for_each / var), so a
    # literal scan cannot read them. They are covered instead by
    # test_every_generated_alarm_is_inside_the_bound, which reads the generator's own output.
    GENERATOR_OWNED = "modules/silver_observability/main.tf"

    def test_the_bound_is_the_one_the_api_documents(self):
        # NOT a hand-copied constant: botocore ships the CloudWatch service model this estate's own
        # boto3 calls are built from, and PutMetricAlarm.Period documents the ceiling in words.
        # If AWS ever moves it, this test moves with the SDK instead of rotting silently.
        from leviathan.silver.freshness import CLOUDWATCH_MAX_EVALUATION_SECONDS

        assert CLOUDWATCH_MAX_EVALUATION_SECONDS == 7 * 24 * 3600 == 604800
        documented = _documented_cloudwatch_bound()
        if documented is not None:
            assert documented == CLOUDWATCH_MAX_EVALUATION_SECONDS, documented

    def test_every_generated_alarm_is_inside_the_bound(self, doc):
        from leviathan.silver.freshness import CLOUDWATCH_MAX_EVALUATION_SECONDS

        over = [(a["alarm_name"], a["period_seconds"], a["evaluation_periods"],
                 a["period_seconds"] * a["evaluation_periods"])
                for a in doc["alarms"]
                if a["period_seconds"] * a["evaluation_periods"] > CLOUDWATCH_MAX_EVALUATION_SECONDS]
        assert over == [], over
        # M of N is still M <= N, which PutMetricAlarm also refuses to violate.
        for a in doc["alarms"]:
            if "datapoints_to_alarm" in a:
                assert 1 <= a["datapoints_to_alarm"] <= a["evaluation_periods"], a["alarm_name"]

    def test_the_generator_REFUSES_to_mint_an_uncreatable_alarm(self, sa):
        # THE FENCE AT THE BOUNDARY, not a lint after the fact: `_alarm` raises, so an uncreatable
        # definition never becomes a dict, never reaches a document and never reaches a test that
        # could certify it. This is the assertion that fails on the round-2 worktree.
        with pytest.raises(ValueError) as e:
            sa._alarm(failure_mode="probe_uncreatable", family="graphrag_evidence",
                      metric_name="CorpusFoldRuns", dimensions={}, statistic="SampleCount",
                      period_seconds=86400, evaluation_periods=35,
                      comparison_operator="LessThanThreshold", threshold=1,
                      treat_missing_data="breaching", severity=sa.SEV_P2, owner="o",
                      dedup_key="d", retention_days=90, description="x")
        msg = str(e.value)
        assert "604,800" in msg and "3,024,000" in msg
        # The refusal NAMES THE REMEDY. A generator that only says no teaches nothing.
        assert "AgeDays" in msg and "86400 x 1" in msg
        # and the creatable edge (exactly seven days) is NOT refused -- the fence bounds, it does
        # not tighten.
        sa._alarm(failure_mode="probe_edge", family="graphrag_evidence", metric_name="M",
                  dimensions={}, statistic="Maximum", period_seconds=86400, evaluation_periods=7,
                  comparison_operator="LessThanThreshold", threshold=1,
                  treat_missing_data="breaching", severity=sa.SEV_P2, owner="o", dedup_key="d",
                  retention_days=90, description="x")

    def test_every_alarm_resource_in_the_terraform_tree_is_inside_the_bound(self):
        # M-B's class. The generator's own output is only half the estate: `corpus_lane_liveness`
        # was hand-written HCL in another lane's file and would have failed the apply for everyone.
        from leviathan.silver.freshness import CLOUDWATCH_MAX_EVALUATION_SECONDS

        blocks = _terraform_alarm_blocks(self.TF_ROOT)
        assert blocks, "no aws_cloudwatch_metric_alarm resources found -- the scan is broken"
        over = [(b["file"], b["name"], b["period"], b["evaluation_periods"])
                for b in blocks
                if b["period"] and b["evaluation_periods"]
                and b["period"] * b["evaluation_periods"] > CLOUDWATCH_MAX_EVALUATION_SECONDS]
        assert over == [], over
        for b in blocks:
            if b["period"] and b["evaluation_periods"] and b["datapoints_to_alarm"]:
                assert b["datapoints_to_alarm"] <= b["evaluation_periods"], (b["file"], b["name"])

    def test_an_alarm_whose_shape_cannot_be_read_lives_only_in_the_generated_module(self):
        # THE HOLE IN A LITERAL SCAN, closed instead of ignored: a resource whose period or
        # evaluation_periods is an expression cannot be checked by reading the file. Exactly one
        # file is allowed to contain such resources -- the module the generator feeds, whose shapes
        # are asserted from the generator's OUTPUT by the test above. Anything else fails here, so
        # the next dynamic alarm has to declare where its numbers come from.
        unreadable = [(b["file"], b["name"]) for b in _terraform_alarm_blocks(self.TF_ROOT)
                      if not (b["period"] and b["evaluation_periods"])]
        assert all(f == self.GENERATOR_OWNED for f, _ in unreadable), unreadable

    def test_a_terraform_alarm_on_a_LEDGER_GAUGE_metric_carries_that_gauge_s_bound(self):
        # The two halves of a gauge live in different repos-worth of file: the THRESHOLD is
        # declared in freshness.LEDGER_GAUGES (which the poller prints and the generator reads) and
        # `corpus_lane_liveness` is hand-written HCL in the text/corpus lane's file. This is the
        # join, so the hand-written half cannot drift from the declaration in silence.
        from leviathan.silver.freshness import LEDGER_GAUGES

        by_metric = {g.metric_name: g for g in LEDGER_GAUGES}
        seen = []
        for b in _terraform_alarm_blocks(self.TF_ROOT):
            gauge = by_metric.get(b["metric_name"])
            if gauge is None:
                continue
            seen.append((b["file"], b["name"], b["metric_name"]))
            assert b["period"] == 86400, (b["file"], b["name"])
            assert b["evaluation_periods"] == 1, (b["file"], b["name"])
            assert b["threshold"] == gauge.threshold_days, (b["file"], b["name"], b["threshold"])
            assert b["comparison_operator"] == "GreaterThanThreshold", (b["file"], b["name"])
        # Recorded rather than required: the fold gauge's alarm is generator-owned and is not in
        # the tree until its tfvars key is added, so `seen` is allowed to be short -- but any row
        # it DOES contain has been checked.
        assert all(m in by_metric for _f, _n, m in seen)


def _documented_cloudwatch_bound():
    """The ceiling as botocore's own CloudWatch service model states it, or None if unreadable.

    Returning None rather than skipping is deliberate: the caller still asserts the constant's
    arithmetic identity (seven days), so a missing model weakens the test by exactly one clause
    instead of turning it green by default."""
    import gzip
    import json
    import os
    import re

    try:
        import botocore

        path = os.path.join(os.path.dirname(botocore.__file__), "data", "cloudwatch",
                            "2010-08-01", "service-2.json.gz")
        with gzip.open(path) as fh:
            model = json.loads(fh.read().decode("utf-8"))
        doc = model["shapes"]["PutMetricAlarmInput"]["members"]["Period"]["documentation"]
    except Exception:                                            # noqa: BLE001
        return None
    m = re.search(r"can't be more than ([\d,]+) seconds", re.sub(r"<[^>]+>", "", doc))
    return int(m.group(1).replace(",", "")) if m else None


_ALARM_RE = re.compile(r'resource\s+"aws_cloudwatch_metric_alarm"\s+"([^"]+)"\s*\{')


def _terraform_alarm_blocks(root):
    """Every ``aws_cloudwatch_metric_alarm`` resource under ``root``, as a flat dict per block.

    A deliberately small HCL reader: it takes the block by brace balance (strings and comments
    excluded) and reads only top-level `key = value` scalars. Non-literal values come back None,
    which is a FINDING for the caller, never a pass."""
    out = []
    for path in sorted(Path(root).rglob("*.tf")):
        text = path.read_text(encoding="utf-8")
        for m in _ALARM_RE.finditer(text):
            body = _balanced_block(text, m.end() - 1)
            rel = path.relative_to(root).as_posix()
            out.append({
                "file": rel,
                "name": m.group(1),
                "period": _int_attr(body, "period"),
                "evaluation_periods": _int_attr(body, "evaluation_periods"),
                "datapoints_to_alarm": _int_attr(body, "datapoints_to_alarm"),
                "threshold": _float_attr(body, "threshold"),
                "metric_name": _str_attr(body, "metric_name"),
                "comparison_operator": _str_attr(body, "comparison_operator"),
            })
    return out


def _balanced_block(text, open_brace_idx):
    depth, i, n = 0, open_brace_idx, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':                       # skip a quoted string, braces and all
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch == "#":                     # skip a comment to end of line
            while i < n and text[i] != "\n":
                i += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_idx:i + 1]
        i += 1
    raise AssertionError("unbalanced alarm block")


def _attr(body, key):
    m = re.search(r"^\s*%s\s*=\s*(.+)$" % re.escape(key), body, re.M)
    return m.group(1).strip() if m else None


def _int_attr(body, key):
    raw = _attr(body, key)
    return int(raw) if raw and re.fullmatch(r"-?\d+", raw) else None


def _float_attr(body, key):
    raw = _attr(body, key)
    return float(raw) if raw and re.fullmatch(r"-?\d+(\.\d+)?", raw) else None


def _str_attr(body, key):
    raw = _attr(body, key)
    if raw and raw.startswith('"') and raw.endswith('"') and "${" not in raw:
        return raw[1:-1]
    return None

