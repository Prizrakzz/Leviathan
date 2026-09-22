"""L5 -- THE CORPUS LANE IS REACHABLE, AND A FIRE THAT INGESTS NOTHING SAYS SO.

TWO DEFECTS ARE PINNED HERE AND BOTH FAIL ON HEAD.

A. NOTHING FIRED THE LANE. `jobs/batch/corpus_ingest_task.py` and `jobs/batch/corpus_fold_task.py`
   were built, unit-pinned and reachable by no schedule: on 2026-09-22 all 30 EventBridge Scheduler
   schedules and all 4 EventBridge rules were listed and NONE targeted `leviathan-dev-evidence-build`.
   The store the writer cites had been frozen since 2026-08-21.

B. NOTHING MEASURED THE LANE. `corpus_coverage.metric_payloads` has been written and unit-tested
   since the lane's first sitting, and `corpus_ingest_task.py:186` was its ONLY caller in the whole
   estate -- and that call only PRINTED. `list_metrics(Namespace="Leviathan/Silver")` returned 11
   names on 2026-09-22 and not one of the four was among them, so the `graphrag_evidence` family's
   only instrument was the weekly TIMELINE rebuild's heartbeat, reading 1.395 d GREEN over a corpus
   whose newest fact was 41 days old.

The terraform is read as TEXT here on purpose. A deck that re-implemented the HCL would pin its own
opinion; reading the applied file back and running the extracted command through the wrappers' own
argparse pins the thing that will actually be submitted at 04:00Z.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from leviathan.graphrag import corpus_coverage as cc

_REPO = Path(__file__).resolve().parents[2]
_TF = _REPO / "infra" / "terraform" / "envs" / "dev" / "schedule_corpus.tf"

JOBDEF = "leviathan-dev-evidence-build"
QUEUE_LOCAL = "local.ondemand_job_queue_arn"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ingest():
    return _load(_REPO / "jobs" / "batch" / "corpus_ingest_task.py", "_corpus_ingest_task_sched")


@pytest.fixture(scope="module")
def fold():
    return _load(_REPO / "jobs" / "batch" / "corpus_fold_task.py", "_corpus_fold_task_sched")


@pytest.fixture(scope="module")
def tf() -> str:
    assert _TF.exists(), "infra/terraform/envs/dev/schedule_corpus.tf does not exist"
    return _TF.read_text(encoding="utf-8")


def _hcl_list(tf: str, name: str) -> list[str]:
    """The string items of a top-level `<name> = [ ... ]` HCL list local."""
    m = re.search(r"\n\s*%s\s*=\s*\[(.*?)\n\s*\]" % re.escape(name), tf, re.S)
    assert m, "local %r not found in schedule_corpus.tf" % name
    return re.findall(r'"([^"]*)"', m.group(1))


# ---------------------------------------------------------------------------
# A -- the schedules exist, target the right thing, and cannot retry
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("resource", ["corpus_chunk", "corpus_fold"])
def test_the_schedule_exists_and_is_enabled(tf, resource) -> None:
    """THE PIN THAT FAILS ON HEAD: before this change neither resource existed and no schedule in
    the estate reached leviathan-dev-evidence-build."""
    m = re.search(r'resource\s+"aws_scheduler_schedule"\s+"%s"\s*\{(.*?)\n\}' % resource, tf, re.S)
    assert m, resource
    body = m.group(1)
    assert re.search(r'state\s*=\s*"ENABLED"', body), "a schedule that is never enabled is not a fix"
    assert "flexible_time_window" in body and 'mode = "OFF"' in body
    assert "local.corpus_job_definition_name" in body
    assert QUEUE_LOCAL in body, "the scheduled thin contract runs on the ON-DEMAND queue, never SPOT"
    assert "dead_letter_config" in body
    assert re.search(r"maximum_retry_attempts\s*=\s*0", body), \
        "both fires mutate state (a billed Anthropic batch / all 196 slice objects) -- a delivery " \
        "retry is a second mutation"
    assert "AttemptDurationSeconds" in body, \
        "the jobdef's own timeout is None; without an attempt duration a wedged fire bills to the " \
        "24h Batch SLA"


@pytest.mark.parametrize("unit", ["corpus_chunk", "corpus_fold"])
def test_each_schedule_carries_its_OWN_scoped_role_and_its_OWN_dlq(tf, unit) -> None:
    """A scheduler role's SubmitJob grant is RESOURCE-SCOPED: a borrowed role fails at FIRE time,
    not at apply time, so the schedule looks armed and the job never exists."""
    assert 'resource "aws_iam_role" "%s_scheduler"' % unit in tf
    assert 'resource "aws_iam_role_policy" "%s_scheduler"' % unit in tf
    assert 'resource "aws_sqs_queue" "%s_dlq"' % unit in tf
    assert 'resource "aws_cloudwatch_metric_alarm" "%s_dlq_depth"' % unit in tf
    pol = re.search(r'resource\s+"aws_iam_role_policy"\s+"%s_scheduler"\s*\{(.*?)\n\}' % unit,
                    tf, re.S).group(1)
    assert "local.corpus_job_definition_arns" in pol and QUEUE_LOCAL in pol
    assert "local.%s_dlq_arn" % unit in pol


def test_both_arn_forms_are_granted(tf) -> None:
    """The bare ARN authorizes SubmitJob with an unversioned name; the `:*` form is what Batch
    resolves it to. Granting one and not the other is an AccessDenied at fire time."""
    arns = re.search(r"corpus_job_definition_arns\s*=\s*\[(.*?)\n\s*\]", tf, re.S).group(1)
    assert "job-definition/${local.corpus_job_definition_name}\"" in arns
    assert "job-definition/${local.corpus_job_definition_name}:*\"" in arns


def test_the_chunk_cadence_does_not_collide_with_the_timeline_rebuild(tf) -> None:
    """leviathan-dev-timeline-rebuild holds cron(0 3 ? * SUN *) and is ENABLED. Two 16 vCPU jobs on
    one queue at one minute makes the chunk pass wait for capacity while its own 5400 s poll budget
    is already running."""
    body = re.search(r'resource\s+"aws_scheduler_schedule"\s+"corpus_chunk"\s*\{(.*?)\n\}',
                     tf, re.S).group(1)
    expr = re.search(r'schedule_expression\s*=\s*"([^"]+)"', body).group(1)
    assert expr != "cron(0 3 ? * SUN *)"
    assert expr == "cron(0 4 ? * SUN *)"


def test_the_fold_runs_after_the_months_wasde_and_wap_text_has_been_chunked(tf) -> None:
    """The date is DERIVED. wasde_monthly fires cron(0 18 8-13 * ? *) and wap cron(0 18 12-14 * ? *),
    so the month's text does not exist before the 14th at 18:00Z; chunking is the Sunday pass, whose
    worst case puts the month's first chunk on the 21st. A fold on the 2nd -- the sketch's date --
    would always fold the PREVIOUS month's WASDE and sit 21 to 51 days behind its own source against
    a declared 35-day served ceiling."""
    body = re.search(r'resource\s+"aws_scheduler_schedule"\s+"corpus_fold"\s*\{(.*?)\n\}',
                     tf, re.S).group(1)
    expr = re.search(r'schedule_expression\s*=\s*"([^"]+)"', body).group(1)
    day = int(re.match(r"cron\(\d+ \d+ (\d+) ", expr).group(1))
    assert day >= 22, expr


# ---------------------------------------------------------------------------
# A2 -- the frozen commands are the ones the wrappers can actually run
# ---------------------------------------------------------------------------

CHUNK_COMMAND = ["jobs/batch/corpus_ingest_task.py", "--stage", "chunk",
                 "--max-docs", "200", "--max-usd", "5", "--poll-budget-seconds", "5400"]


def test_the_scheduled_chunk_command_is_the_docstrings_frozen_command(tf) -> None:
    assert _hcl_list(tf, "corpus_chunk_command") == CHUNK_COMMAND


def test_the_scheduled_chunk_command_parses_and_carries_the_designs_caps(tf, ingest) -> None:
    args = ingest.build_parser().parse_args(_hcl_list(tf, "corpus_chunk_command")[1:])
    assert args.stage == "chunk"
    assert (args.max_docs, args.max_usd, args.poll_budget_seconds) == (200, 5.0, 5400)
    assert args.dry_run is False and args.all_gap is False
    assert args.evidence_s3 is None, \
        "the frozen command carries no --evidence-s3: leviathan-dev-evidence-build BAKES " \
        "EVIDENCE_S3, and bind_evidence_prefix(require=True) refuses the billed leg if a future " \
        "revision ever drops it"


def test_the_scheduled_fold_command_parses(tf, fold) -> None:
    args = fold.build_parser().parse_args(_hcl_list(tf, "corpus_fold_command")[1:])
    assert args.stage == "fold"
    assert args.evidence_s3 == "s3://leviathan-dev-shahem-001/graphrag_evidence"
    assert args.census_baseline, "without an explicit baseline the e1_census --diff gate PASSES SILENTLY"
    assert args.no_backup is False
    assert args.with_pg_load is False and args.with_pg_swap is False, \
        "R3 stays the operator's for its first three cycles: a fold moves S3, not the served mirror"


def test_the_fold_command_declares_the_live_prefix_or_it_could_never_run(tf, fold) -> None:
    """MEASURED AT HEAD, and it is the reason this flag is in the Input. corpus_fold_task.main runs
    GUARD 1 (assert_not_live_rebuild) against the jobdef's OWN baked EVIDENCE_S3 and, outside a dry
    run, RE-RAISES. The fold's prefix IS that baked prefix, so without the declaration the scheduled
    fold would exit nonzero on its first fire and on every fire after it."""
    cmd = _hcl_list(tf, "corpus_fold_command")
    assert "--i-know-this-is-live" in cmd
    args = fold.build_parser().parse_args(cmd[1:])
    assert args.i_know_this_is_live is True
    # ...and the declaration buys exactly one guard, never the others.
    assert "--no-backup" not in cmd
    assert "--allow-churn" not in cmd


def test_the_fold_task_still_offers_no_allow_churn_at_all(fold) -> None:
    """The 2026-08-21 pass ran --allow-churn 50.0 and recorded barley_yellow_dwarf_virus and
    wheat_blast as `unwritten`. An add-only fold must never need one, and a refusal IS the finding
    -- so there must be no flag here to override it, whatever the schedule says."""
    with pytest.raises(SystemExit):
        fold.build_parser().parse_args(
            ["--stage", "fold", "--evidence-s3", "s3://x/y", "--allow-churn", "50.0"])


def test_the_fold_chain_is_lint_then_rebuild_then_census_then_THE_ROLL(tf, fold) -> None:
    """ROUND 2: a FOURTH step. Without it the frozen Input diffs against one 2026-08-02 object
    forever -- `e1_census --diff` never writes and no schedule runs a plain census -- so a growing
    store's partial regression reads GREEN. The roll is pinned in full in
    tests/unit/test_corpus_fold_task.py; this deck pins that the SCHEDULED command produces it."""
    args = fold.build_parser().parse_args(_hcl_list(tf, "corpus_fold_command")[1:])
    steps = fold.chain_steps(args)
    assert len(steps) == 4
    assert steps[0] == ["-m", "leviathan.graphrag.driver_slices_manifest", "--check"]
    assert steps[1] == ["-m", "leviathan.graphrag.evidence_batch", "--rebuild-slices"]
    assert steps[2][:2] == ["-m", "leviathan.graphrag.e1_census"] and "--diff" in steps[2]
    assert steps[3] == ["-m", "leviathan.graphrag.e1_census"]
    assert "--allow-churn" not in sum(steps, [])


def test_the_scheduled_baseline_IS_the_key_the_scheduled_fold_rolls(tf, fold) -> None:
    """The frozen Input is safe ONLY because the key it names is the one the fold advances. If an
    edit ever points it elsewhere, GUARD 4 refuses the live fold instead of pretending -- and this
    deck catches it before the apply."""
    cmd = _hcl_list(tf, "corpus_fold_command")
    args = fold.build_parser().parse_args(cmd[1:])
    assert args.census_baseline == fold.census_roll_target(args.evidence_s3)
    fold.assert_baseline_is_the_rolled_key(args, echo=lambda *_: None)     # does not raise


def test_the_fold_emits_its_own_liveness_and_the_tf_does_not_arm_those_alarms(tf, fold) -> None:
    """MAJOR-3: at HEAD the fold wrote no ledger, no heartbeat and no metric, and no metric filter
    that feeds an alarm WITH AN ACTION matches a corpus-* jobName. The two alarms over these names
    belong to lane 7's generator; this file must not grow a second home for them."""
    assert fold.FOLD_METRIC_NAMES == ("CorpusFoldRuns", "CorpusFoldSlicesWritten",
                                      "CorpusFoldFailures")
    assert fold.FOLD_LEDGER_SUFFIX == "fold/last_run.json"
    for name in fold.FOLD_METRIC_NAMES:
        assert name not in re.sub(r"#.*", "", tf), \
            "%s is lane 7's alarm to write, and it must not be armed before a fire has emitted" % name


# ---------------------------------------------------------------------------
# B -- the metric line
# ---------------------------------------------------------------------------

def _census(**per_source) -> dict:
    src = {name: {"gap": rec.get("gap", 1),
                  "struck_from_write_path": rec.get("struck", False),
                  "newest_covered_pub": rec.get("covered"),
                  "coverage": rec.get("coverage", 1.0),
                  "chunk_lag_days": rec.get("chunk_lag"),
                  "fetch_lag_days": rec.get("fetch_lag")}
           for name, rec in per_source.items()}
    return {"sources": src, "totals": {"docs": sum(r["gap"] for r in src.values())}}


def _ledger(census: dict) -> dict:
    return cc.ledger_document(census, generated_at="2026-09-22T04:00:00Z", fulltext_cap=150000)


def _args(**kw):
    base = dict(aws_region="us-east-1", evidence_s3="s3://leviathan-dev-shahem-001/graphrag_evidence",
                bucket=cc.BUCKET, dry_run=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_the_ledger_minted_datums_are_the_modules_own_datums(ingest) -> None:
    """THE ANTI-DRIFT PIN. The wrapper builds the datums from the LEDGER so CloudWatch and
    coverage/ledger.json can never disagree; this proves that minting is the same minting
    `corpus_coverage.metric_payloads` performs over the census the ledger was built from."""
    census = _census(usda_wasde={"coverage": 1.0, "chunk_lag": 3, "fetch_lag": 11},
                     usda_gain_coffee={"coverage": 0.84, "chunk_lag": 125, "fetch_lag": 125},
                     conab={"struck": True, "coverage": 0.0, "chunk_lag": 900, "fetch_lag": 900})
    assert ingest.metric_datums(_ledger(census)) == cc.metric_payloads(census)


def test_the_four_datums_carry_one_constant_dimension_and_nothing_per_source(ingest) -> None:
    """Cardinality is the module's decision and it was priced: 28 sources x 3 + 1 = 85 metrics at
    $0.30 = $25.50/month, more than the entire lane. Four family-rolled metrics cost $1.60."""
    census = _census(usda_wasde={"chunk_lag": 3, "fetch_lag": 11},
                     usda_gain_coffee={"chunk_lag": 125, "fetch_lag": 125})
    datums = ingest.metric_datums(_ledger(census))
    assert {d["MetricName"] for d in datums} <= set(cc.FAMILY_METRIC_NAMES)
    assert len(datums) <= 4
    assert all(d["Dimensions"] == [{"Name": "Family", "Value": "graphrag_evidence"}] for d in datums)


def test_a_starving_lane_is_LOUD_in_the_numbers_it_emits(ingest) -> None:
    """A fire that ingests nothing must not read like a fire that had nothing to do. The lags are
    MAXIMA over the scored sources and the breach count names how many are past the declared
    contract, so a stalled source shows up in the datums the very fire that failed to move it."""
    stalled = ingest.metric_datums(_ledger(_census(
        usda_wasde={"coverage": 0.6, "chunk_lag": 41, "fetch_lag": 11})))
    by = {d["MetricName"]: d["Value"] for d in stalled}
    assert by[cc.METRIC_CHUNK_LAG_MAX] == 41.0 > cc.CHUNK_LAG_CEILING_DAYS
    assert by[cc.METRIC_BREACH_COUNT] == 1.0
    healthy = ingest.metric_datums(_ledger(_census(
        usda_wasde={"coverage": 1.0, "chunk_lag": 3, "fetch_lag": 4})))
    assert {d["MetricName"]: d["Value"] for d in healthy}[cc.METRIC_BREACH_COUNT] == 0.0


def test_writing_the_ledger_PUTS_the_datums(ingest, monkeypatch) -> None:
    """THE PIN THAT FAILS ON HEAD: `put_metric_data` appeared nowhere in this lane, so the four
    metrics could not exist and no alarm could be written against them."""
    puts: list = []
    fake_s3 = MagicMock()

    def _client(service, **kw):
        if service == "cloudwatch":
            cw = MagicMock()
            cw.put_metric_data.side_effect = lambda **k: puts.append(k)
            return cw
        return fake_s3

    import boto3
    monkeypatch.setattr(boto3, "client", _client)
    census = _census(usda_wasde={"coverage": 1.0, "chunk_lag": 3, "fetch_lag": 4})
    ingest._write_ledger(_args(), _ledger(census))
    assert len(puts) == 1
    assert puts[0]["Namespace"] == cc.METRIC_NAMESPACE == "Leviathan/Silver"
    assert puts[0]["MetricData"] == cc.metric_payloads(census)
    # the ledger AND the heartbeat still commit, and the metrics ride that same commit point
    assert [c.kwargs["Key"] for c in fake_s3.put_object.call_args_list] == [
        "graphrag_evidence/coverage/ledger.json", "graphrag_evidence/coverage/last_run.json"]


def test_a_quiet_fire_still_reports_so_silence_only_ever_means_no_fire(ingest, monkeypatch) -> None:
    """The quiet outcomes (NOTHING_TO_DO / NO_CANDIDATES / ALL_CACHED) and the loud one
    (REFUSED_CAP) all reach `_write_ledger`, so every one of them emits. That is what lets the
    liveness alarm read missing datapoints as 'no fire ran' rather than 'the fire found nothing'."""
    puts: list = []

    def _client(service, **kw):
        cw = MagicMock()
        cw.put_metric_data.side_effect = lambda **k: puts.append(k)
        return cw if service == "cloudwatch" else MagicMock()

    import boto3
    monkeypatch.setattr(boto3, "client", _client)
    census = _census(usda_wasde={"coverage": 0.9, "chunk_lag": 41, "fetch_lag": 11})
    ingest._write_ledger(_args(), _ledger(census), outcome="CORPUS_INGEST_REFUSED_CAP")
    assert len(puts) == 1 and puts[0]["MetricData"]


def test_a_failed_put_does_not_throw_away_a_committed_ledger(ingest, monkeypatch) -> None:
    """Not fail-open: this module's own convention is that the alarm's treat_missing_data=breaching
    OWNS the silence, so a datum that never arrives reads RED. Failing the job here would discard a
    ledger and a heartbeat that already committed."""
    def _client(service, **kw):
        c = MagicMock()
        if service == "cloudwatch":
            c.put_metric_data.side_effect = RuntimeError("throttled")
        return c

    import boto3
    monkeypatch.setattr(boto3, "client", _client)
    ingest._write_ledger(_args(), _ledger(_census(usda_wasde={"chunk_lag": 3, "fetch_lag": 4})))


def test_an_UNMEASURABLE_lag_is_OMITTED_while_the_breach_count_still_reports(
        ingest, monkeypatch) -> None:
    """R2 MINOR-2: THIS TEST'S OLD NAME SAID THE OPPOSITE OF ITS OWN ASSERTION, and a pin that
    misnames its subject is the defect class this estate audits for. What is true:
    `metric_payloads` OMITS a None lag or coverage on purpose -- a lane with no measurable lag must
    leave that stream empty and let the alarm own it, never publish a 0 that reads as perfect
    health -- while `len(breaching_sources)` is an int by construction, so the breach count is
    emitted on EVERY real ledger. That is what the liveness alarm needs: a datum on every fire.
    The "nothing measurable -- NOTHING emitted" branch in `_emit_metrics` is therefore unreachable
    for a real ledger and is a guard against a malformed one."""
    puts: list = []

    def _client(service, **kw):
        cw = MagicMock()
        cw.put_metric_data.side_effect = lambda **k: puts.append(k)
        return cw if service == "cloudwatch" else MagicMock()

    import boto3
    monkeypatch.setattr(boto3, "client", _client)
    census = {"sources": {}, "totals": {"docs": 0}}
    datums = ingest.metric_datums(_ledger(census))
    assert [d["MetricName"] for d in datums] == [cc.METRIC_BREACH_COUNT]
    assert all(d["MetricName"] != cc.METRIC_CHUNK_LAG_MAX for d in datums)


def test_the_liveness_alarm_asks_whether_a_fire_REPORTED_not_whether_it_was_good(tf) -> None:
    """The four contract ceilings are MAXIMA over every scored source and raw usda_gain_* has not
    moved since 2026-05-21, so arming them today would add three permanently-red legs to the very
    board the alarm-hygiene fix exists to clean. The armed alarm asks LIVENESS and nothing else.

    RE-SHAPED IN ROUND 3, and the deck follows the resource rather than the other way round: the
    round-2 shape (SampleCount over TEN DAILY periods) COULD NOT BE CREATED. CloudWatch's own
    service model bounds an alarm's total evaluation window at seven days -- Period x
    EvaluationPeriods <= 604,800 s -- and 86,400 x 10 = 864,000 s, so `terraform apply` would have
    failed on this resource and taken the whole 52-add plan with it. The QUESTION and the 10 are
    unchanged; the 10 is now TEN DAYS OF AGE on the daily `CorpusChunkAgeDays` gauge, evaluated
    once (86,400 x 1). A job can only emit while it runs, so "it did not run" is the one datapoint
    a dead chunk pass cannot publish -- a daily gauge inverts that and the NUMBER carries the
    silence."""
    body = re.search(
        r'resource\s+"aws_cloudwatch_metric_alarm"\s+"corpus_lane_liveness"\s*\{(.*?)\n\}',
        tf, re.S).group(1)
    assert re.search(r'namespace\s*=\s*"Leviathan/Silver"', body)
    assert re.search(r'metric_name\s*=\s*"CorpusChunkAgeDays"', body)
    assert re.search(r'treat_missing_data\s*=\s*"breaching"', body)
    assert re.search(r"threshold\s*=\s*10", body), \
        "a healthy weekly cadence leaves at most 6 quiet days; 10 days of age is ONE missed fire"
    assert re.search(r'comparison_operator\s*=\s*"GreaterThanThreshold"', body)
    # and the ceilings are NOT armed
    assert cc.METRIC_CHUNK_LAG_MAX not in re.sub(r"#.*", "", tf)


def test_NO_alarm_in_this_file_can_exceed_CLOUDWATCHS_SEVEN_DAY_EVALUATION_BOUND(tf) -> None:
    """THE PIN THAT WOULD HAVE CAUGHT THE UNBUILDABLE ALARM BEFORE THE APPLY (round 3).

    botocore's CloudWatch service model: "An alarm's total current evaluation period can be no
    longer than seven days, so Period multiplied by EvaluationPeriods can't be more than 604,800
    seconds." Corroborated against the live account 2026-09-22: of 75 metric alarms the MAXIMUM
    Period x EvaluationPeriods is 86,400, because nothing longer can exist. A resource that cannot
    be created does not fail alone -- it fails the apply it rides in."""
    bound = 7 * 24 * 3600
    blocks = re.findall(
        r'resource\s+"aws_cloudwatch_metric_alarm"\s+"([a-z0-9_]+)"\s*\{(.*?)\n\}', tf, re.S)
    assert blocks, "this file declares alarms; if it stops, delete this deck rather than pass it"
    for name, body in blocks:
        clean = re.sub(r"#.*", "", body)
        period = re.search(r"\bperiod\s*=\s*(\d+)", clean)
        periods = re.search(r"\bevaluation_periods\s*=\s*(\d+)", clean)
        if not period or not periods:
            continue                                  # a metric_query alarm carries neither here
        total = int(period.group(1)) * int(periods.group(1))
        assert total <= bound, (
            "%s: period x evaluation_periods = %d s > %d s -- PutMetricAlarm REFUSES it and the "
            "whole apply fails with it" % (name, total, bound))


def test_the_metric_names_in_the_terraform_are_the_modules_own(tf) -> None:
    """A hand-typed metric name in HCL is an alarm that watches a stream nothing writes."""
    assert cc.METRIC_BREACH_COUNT == "CorpusCoverageBreachCount"
    assert cc.FAMILY == "graphrag_evidence"
    assert re.search(r'dimensions\s*=\s*\{ Family = "%s" \}' % cc.FAMILY, tf)


def test_the_run_date_is_still_the_one_clock_and_the_stages_are_unchanged(ingest) -> None:
    """A guard on this change: the metric line must not have moved the lane's other contracts."""
    assert ingest.STAGES == ("fetch", "text", "chunk", "census")
    assert ingest._run_date("2026-09-22T04:00:00Z") == date(2026, 9, 22)


def test_the_header_no_longer_claims_the_file_never_calls_cloudwatch() -> None:
    """The docstring said 'never calls CloudWatch' in the same file that now must. A comment that
    contradicts the code is the defect class this estate audits for."""
    src = (_REPO / "jobs" / "batch" / "corpus_ingest_task.py").read_text(encoding="utf-8")
    assert "never touches pg, and never passes `--allow-churn`" in src
    assert "never calls CloudWatch" not in src


def test_the_tf_is_ascii(tf) -> None:
    json.dumps(tf)                                   # no surrogates
    tf.encode("ascii")
