"""L5 ROUND 2 -- THE MONTHLY FOLD ADVANCES ITS OWN BASELINE, AND IT LEAVES A TRACE.

TWO DEFECTS ARE PINNED HERE. Both are absent from the round-1 file as well as from HEAD, so every
test below fails against `git show HEAD:jobs/batch/corpus_fold_task.py` AND against the round-1
worktree copy -- the module has no `census_write_step`, no `census_roll_target`, no
`assert_baseline_is_the_rolled_key`, no `verify_baseline_advanced`, no `fold_metric_datums` and no
ledger at all.

FATAL -- THE REGRESSION GATE WAS FROZEN AGAINST A SNAPSHOT NOTHING REFRESHED. The scheduled fold's
`--census-baseline` is an EventBridge Scheduler Input, frozen at apply time, naming ONE object:
`s3://leviathan-dev-shahem-001/graphrag_evidence/eval/e1_census.json`, LastModified
2026-08-02T00:36:09Z (HEAD 2026-09-22, read-only). Nothing refreshes it -- `e1_census --diff` is a
read-only gate that never calls `write()`, and no schedule in the account runs a plain census. The
gate's teeth (`population_drops`, POP_DROP_REFUSE = 0.10) compare each slice to THE BASELINE'S
value, so on a store designed to grow every month a true partial regression would read GREEN. The
fold now writes the census it just produced to the key it diffs against -- the same
advance-after-green shape as `jobs/audit/advance_rolling_census.py` -- and NEVER on a red chain.

MAJOR -- THE FOLD HAD NO LIVENESS INSTRUMENT AT ALL. At HEAD it wrote no ledger, no heartbeat and
no metric; the rule `leviathan-dev-batch-job-failed` targets only a log group, the filter that feeds
an alarm WITH AN ACTION matches no `corpus-*` jobName, and the catch-all backstop alarm has zero
alarm actions. A monthly fold that failed every month paged nobody.

NOT COVERED HERE: no S3, no Batch, no network. The fakes below are the seam.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError
from leviathan.graphrag import corpus_coverage as cc

_REPO = Path(__file__).resolve().parents[2]
_TASK = _REPO / "jobs" / "batch" / "corpus_fold_task.py"
_TF = _REPO / "infra" / "terraform" / "envs" / "dev" / "schedule_corpus.tf"

LIVE = "s3://leviathan-dev-shahem-001/graphrag_evidence"
BASELINE = LIVE + "/eval/e1_census.json"
_NOW = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def fold():
    return _load(_TASK, "_corpus_fold_task_r2")


def _args(fold, *extra):
    return fold.build_parser().parse_args(
        ["--stage", "fold", "--evidence-s3", LIVE, "--census-baseline", BASELINE, *extra])


class _FakeS3:
    """head_object/list/get over dicts. Records every call so a deck can assert what was NOT done."""

    def __init__(self, *, heads=None, manifests=None, objects=None):
        self.heads = dict(heads or {})
        self.manifests = dict(manifests or {})          # key -> (stamp-bearing key) -> doc
        self.objects = dict(objects or {})
        self.puts: list = []
        self.copies: list = []

    def head_object(self, Bucket, Key):                 # noqa: N803 -- boto3 kwarg casing
        if Key not in self.heads:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        return {"LastModified": self.heads[Key], "ContentLength": 1}

    def put_object(self, Bucket, Key, Body, **kw):      # noqa: N803
        self.puts.append((Key, json.loads(Body.decode("utf-8"))))

    def copy(self, src, bucket, dst):
        self.copies.append((src["Key"], dst))

    def get_object(self, Bucket, Key):                  # noqa: N803
        return {"Body": SimpleNamespace(read=lambda: json.dumps(self.manifests[Key]).encode())}

    def get_paginator(self, _op):
        outer = self

        class _P:
            def paginate(self, Bucket, Prefix, **kw):   # noqa: N803
                keys = sorted(k for k in list(outer.manifests) + list(outer.objects)
                              if k.startswith(Prefix))
                yield {"Contents": [{"Key": k} for k in keys]}
        return _P()


# ---------------------------------------------------------------------------
# FATAL -- the roll
# ---------------------------------------------------------------------------

def test_the_chain_ENDS_with_a_census_WRITE_so_the_baseline_advances(fold) -> None:
    """THE PIN THAT FAILS ON HEAD AND ON ROUND 1: the chain was lint -> rebuild -> census --diff and
    stopped, so the object the gate reads was never rewritten by anything, ever."""
    steps = fold.chain_steps(_args(fold, "--i-know-this-is-live"))
    assert len(steps) == 4
    assert steps[0] == ["-m", "leviathan.graphrag.driver_slices_manifest", "--check"]
    assert steps[1] == ["-m", "leviathan.graphrag.evidence_batch", "--rebuild-slices"]
    assert steps[2] == ["-m", "leviathan.graphrag.e1_census", "--diff", "--baseline", BASELINE]
    assert steps[3] == ["-m", "leviathan.graphrag.e1_census"], \
        "step 4 must be a PLAIN census run -- with --diff it reads and writes nothing"
    assert "--diff" not in steps[3] and "--local-only" not in steps[3], \
        "--local-only would skip the S3 copy, which IS the baseline the next fold reads"


def test_the_write_step_is_derived_from_the_gate_step_and_cannot_drift(fold) -> None:
    """Hand-typing the module name here would be a second definition free to drift from the gate it
    must roll. It is `_CENSUS_GATE_CMD` minus `--diff`, from the submitter, one source."""
    sm = fold._guards()
    assert fold.census_write_step() == [t for t in sm._CENSUS_GATE_CMD if t != "--diff"]


def test_the_roll_lands_on_exactly_the_key_the_schedule_names(fold) -> None:
    """The frozen Input does not change -- it names a key the fold now rolls. If those two ever
    diverge the gate is frozen again, silently."""
    tf = _TF.read_text(encoding="utf-8")
    m = re.search(r"\n\s*corpus_fold_command\s*=\s*\[(.*?)\n\s*\]", tf, re.S)
    frozen = re.findall(r'"([^"]*)"', m.group(1))
    declared = frozen[frozen.index("--census-baseline") + 1]
    assert declared == fold.census_roll_target(frozen[frozen.index("--evidence-s3") + 1])
    assert declared == BASELINE


def test_NO_ROLL_ON_RED_the_write_never_runs_after_a_failing_step(fold, monkeypatch) -> None:
    """The whole fence. A dirty census must NOT be enshrined as the next month's baseline -- the
    same rule advance_rolling_census states as `if rc != 0: return rc` BEFORE its upload. Here it is
    `run_chain`'s first-nonzero-wins, proven rather than assumed."""
    launched: list = []

    def _call(cmd, env=None):
        launched.append(cmd[1:])
        return 1 if "--diff" in cmd else 0                    # the GATE fails

    monkeypatch.setattr(fold.subprocess, "call", _call)
    steps = fold.chain_steps(_args(fold, "--i-know-this-is-live"))
    rc = fold.run_chain(steps, env={"EVIDENCE_S3": LIVE})
    assert rc == 1
    assert fold.census_write_step() not in launched, \
        "the census WRITE ran after a red gate -- that enshrines a dirty census as the baseline"
    assert len(launched) == 3


def test_a_GREEN_chain_runs_the_write_last(fold, monkeypatch) -> None:
    launched: list = []
    monkeypatch.setattr(fold.subprocess, "call", lambda cmd, env=None: launched.append(cmd[1:]) or 0)
    rc = fold.run_chain(fold.chain_steps(_args(fold, "--i-know-this-is-live")),
                        env={"EVIDENCE_S3": LIVE})
    assert rc == 0 and launched[-1] == fold.census_write_step()


def test_GUARD4_refuses_a_LIVE_fold_that_would_roll_a_key_it_does_not_diff(fold) -> None:
    """A fold that judges itself against one object and advances another is the frozen-snapshot
    defect wearing a rolling fold's clothes. On the live path that is refused before a dollar is
    spent, not warned about."""
    bad = fold.build_parser().parse_args(
        ["--stage", "fold", "--evidence-s3", LIVE, "--i-know-this-is-live",
         "--census-baseline", "s3://leviathan-dev-shahem-001/graphrag_evidence/eval/OTHER.json"])
    with pytest.raises(SystemExit) as exc:
        fold.assert_baseline_is_the_rolled_key(bad)
    assert "is not the key this fold can roll" in str(exc.value)


def test_GUARD4_lets_a_SHADOW_rehearsal_diff_against_a_foreign_baseline(fold) -> None:
    """A fresh shadow prefix holds no census at all, so its ONLY legal baseline is the live one. It
    rolls its OWN key and leaves the live key untouched -- refusing here would refuse R2, the only
    safe way to exercise the fold."""
    said: list = []
    shadow = fold.build_parser().parse_args(
        ["--stage", "fold", "--evidence-s3", LIVE + "/shadow_originpolicy",
         "--census-baseline", BASELINE])
    fold.assert_baseline_is_the_rolled_key(shadow, echo=said.append)      # does NOT raise
    assert any("FOREIGN baseline" in s for s in said)
    assert fold.census_roll_target(shadow.evidence_s3).endswith(
        "/shadow_originpolicy/eval/e1_census.json")


def test_a_GREEN_chain_whose_baseline_did_NOT_move_is_turned_RED(fold) -> None:
    """The post-condition. `e1_census.write()`'s S3 leg is conditional and prints rather than raises,
    so a dropped environment variable or a stray --local-only would leave the chain green with the
    baseline untouched and nobody told. One HEAD against a fence that would otherwise be decorative."""
    stale = _FakeS3(heads={"graphrag_evidence/eval/e1_census.json": _NOW - timedelta(days=51)})
    with pytest.raises(SystemExit) as exc:
        fold.verify_baseline_advanced(stale, LIVE, since=_NOW)
    assert "did not reach the store" in str(exc.value) or "not newer" in str(exc.value)
    fresh = _FakeS3(heads={"graphrag_evidence/eval/e1_census.json": _NOW + timedelta(minutes=4)})
    fold.verify_baseline_advanced(fresh, LIVE, since=_NOW, echo=lambda *_: None)   # passes


def test_a_rolled_object_that_cannot_be_READ_is_also_RED(fold) -> None:
    with pytest.raises(SystemExit):
        fold.verify_baseline_advanced(_FakeS3(), LIVE, since=_NOW)


# ---------------------------------------------------------------------------
# MAJOR -- the liveness instrument
# ---------------------------------------------------------------------------

_MANIFEST_20260821 = {                       # the SHAPE of the live 2026-08-21 fold manifest
    "docs": {"written": 0, "overwritten": 0},
    "slices": {"commodity": {f"c{i}": {"after_n": 100} for i in range(52)},
               "drivers": {f"d{i}": {"after_n": 100} for i in range(144)}},
}


def test_the_work_number_is_SLICE_OBJECTS_and_never_docs_written(fold) -> None:
    """MEASURED, not preferred. The live manifest of the last real fold
    (eval/write_manifest_rebuild_20260821T212319Z.json, read 2026-09-22) records
    `docs {"written": 0, "overwritten": 0}` beside 52 commodity + 144 driver slices and 2,742,847
    rows. An alarm on `docs.written == 0` would have paged on a 4h29m fold that rewrote 196 objects,
    which is why the metric handed to lane 7 is CorpusFoldSlicesWritten."""
    assert _MANIFEST_20260821["docs"]["written"] == 0
    assert fold.slices_written(_MANIFEST_20260821) == 196
    assert fold.slices_written({"slices": {}}) == 0
    assert fold.slices_written({}) == 0


def test_the_three_datums_are_one_namespace_one_constant_dimension(fold) -> None:
    datums = fold.fold_metric_datums(slices=196, failed=False)
    assert [d["MetricName"] for d in datums] == list(fold.FOLD_METRIC_NAMES)
    assert all(d["Dimensions"] == [{"Name": "Family", "Value": "graphrag_evidence"}] for d in datums)
    assert all(d["Unit"] == "Count" for d in datums)
    assert cc.METRIC_NAMESPACE == "Leviathan/Silver" and cc.FAMILY == "graphrag_evidence"


def test_RUNS_is_emitted_whatever_the_outcome_so_silence_means_NO_FIRE(fold) -> None:
    """The distinction the estate could not make: a fold that ran and failed looked exactly like a
    fold that never fired, because no metric filter that feeds an alarm with an action matches a
    corpus-* jobName and the backstop alarm has zero actions."""
    ok = {d["MetricName"]: d["Value"] for d in fold.fold_metric_datums(slices=196, failed=False)}
    bad = {d["MetricName"]: d["Value"] for d in fold.fold_metric_datums(slices=0, failed=True)}
    assert ok[fold.METRIC_RUNS] == bad[fold.METRIC_RUNS] == 1.0
    assert ok[fold.METRIC_FAILURES] == 0.0 and bad[fold.METRIC_FAILURES] == 1.0
    assert ok[fold.METRIC_SLICES_WRITTEN] == 196.0 and bad[fold.METRIC_SLICES_WRITTEN] == 0.0


def test_the_manifest_read_is_bounded_by_THIS_folds_start(fold) -> None:
    """Deliberately not write_guard.newest_run_manifest(): that helper prefers the LOCAL eval/
    archive, which on a laptop returns a 2026-08-21 manifest and would make a fold that wrote
    nothing report another pass's 196."""
    s3 = _FakeS3(manifests={
        "graphrag_evidence/eval/write_manifest_rebuild_20260821T212319Z.json": _MANIFEST_20260821,
        "graphrag_evidence/eval/write_manifest_rebuild_20261022T090000Z.json": _MANIFEST_20260821,
    })
    doc, label = fold.newest_manifest_since(s3, LIVE, stamp="20261022T080000Z")
    assert doc is not None and label.endswith("20261022T090000Z.json")
    none, why = fold.newest_manifest_since(s3, LIVE, stamp="20261122T080000Z")
    assert none is None and "no write_manifest_" in why


def test_a_NON_REBUILD_manifest_can_never_report_this_folds_work(fold) -> None:
    """R2 MINOR-1 -- a FALSE RED, and a false red is how an alarm gets muted.

    MEASURED 2026-09-22: `graphrag_evidence/eval/` holds 9 `write_manifest_*` objects and FIVE are
    not rebuilds (`seed`, `retrieve` x2, `x2_tail`); the two read carry `slices == {}`, so
    `slices_written()` on one returns 0. Matching `write_manifest_*` meant that any such manifest
    stamped after this fold's own rebuild manifest -- which a hand fire beside the chunk pass
    produces -- would make a fold that wrote 196 objects report `CorpusFoldSlicesWritten = 0` and
    trip lane 7's `corpus_fold_wrote_nothing` alarm (LessThanThreshold 1, 1 datapoint)."""
    s3 = _FakeS3(manifests={
        "graphrag_evidence/eval/write_manifest_rebuild_20261022T090000Z.json": _MANIFEST_20260821,
        # written LATER, by another pass, and it carries no slices at all
        "graphrag_evidence/eval/write_manifest_x2_tail_20261022T093000Z.json": {"slices": {},
                                                                                "docs": {}},
        "graphrag_evidence/eval/write_manifest_seed_20261022T094000Z.json": {"slices": {}},
    })
    doc, label = fold.newest_manifest_since(s3, LIVE, stamp="20261022T080000Z")
    assert label.endswith("write_manifest_rebuild_20261022T090000Z.json"), label
    assert fold.slices_written(doc) == 196, "the fold's OWN work number, not another pass's zero"


def test_the_ledger_line_records_BOTH_numbers_so_neither_can_be_misread(fold) -> None:
    doc = fold.fold_ledger_document(outcome="CORPUS_FOLD_OK", rc=0, started=_NOW,
                                    finished=_NOW + timedelta(hours=4), evidence_s3=LIVE,
                                    slices=196, rows=2742847, manifest_label="s3://x/y.json",
                                    manifest_docs_written=0, baseline=BASELINE)
    assert doc["slice_objects_written"] == 196 and doc["manifest_docs_written"] == 0
    assert doc["census_rolled_to"] == BASELINE and doc["census_baseline"] == BASELINE
    assert doc["rc"] == 0 and doc["outcome"] == "CORPUS_FOLD_OK"
    json.dumps(doc).encode("ascii")                         # ASCII, like every artifact in the lane


# ---------------------------------------------------------------------------
# main() -- the paths a schedule actually takes
# ---------------------------------------------------------------------------

def _patched_main(fold, monkeypatch, *, chain_rc: int, rolled, manifests=None):
    sm = fold._guards()
    monkeypatch.setattr(sm, "assert_not_live_rebuild", lambda **kw: None)
    monkeypatch.setattr(fold.subprocess, "call", lambda cmd, env=None: chain_rc)
    heads = {"graphrag_evidence/eval/e1_census.json": rolled} if rolled else {}
    s3 = _FakeS3(heads=heads, manifests=manifests or {})
    puts: list = []

    class _CW:
        def put_metric_data(self, **kw):
            puts.append(kw)

    import boto3
    monkeypatch.setattr(boto3, "client",
                        lambda service, **kw: _CW() if service == "cloudwatch" else s3)
    monkeypatch.setattr(fold.cc, "bind_evidence_prefix", lambda p, **kw: p.rstrip("/"))
    rc = fold.main(["--stage", "fold", "--evidence-s3", LIVE, "--i-know-this-is-live",
                    "--census-baseline", BASELINE])
    return rc, s3, puts


def test_a_FAILED_fold_still_reports_and_says_it_wrote_nothing(fold, monkeypatch) -> None:
    rc, s3, puts = _patched_main(fold, monkeypatch, chain_rc=1, rolled=None)
    assert rc == 1
    assert len(puts) == 1 and puts[0]["Namespace"] == "Leviathan/Silver"
    by = {d["MetricName"]: d["Value"] for d in puts[0]["MetricData"]}
    assert by[fold.METRIC_RUNS] == 1.0 and by[fold.METRIC_FAILURES] == 1.0
    assert by[fold.METRIC_SLICES_WRITTEN] == 0.0
    ledger = [(k, v) for k, v in s3.puts if k.endswith("fold/last_run.json")]
    assert ledger and ledger[0][1]["outcome"] == "CORPUS_FOLD_CHAIN_FAILED"
    assert ledger[0][1]["rc"] == 1


def test_a_GREEN_fold_whose_baseline_did_not_move_reports_a_REFUSAL_and_exits_nonzero(
        fold, monkeypatch) -> None:
    """The worst outcome this lane can have is a green fold nobody can trust. A chain that returned
    0 without rolling is RED, it says why, and the record survives the process."""
    rc, s3, puts = _patched_main(fold, monkeypatch, chain_rc=0,
                                 rolled=datetime(2026, 8, 2, tzinfo=timezone.utc))
    assert rc != 0
    ledger = dict(s3.puts)["graphrag_evidence/fold/last_run.json"]
    assert ledger["outcome"] == "CORPUS_FOLD_REFUSED" and "not newer" in ledger["note"]
    assert {d["MetricName"]: d["Value"] for d in puts[0]["MetricData"]}[fold.METRIC_FAILURES] == 1.0


def test_a_GREEN_fold_that_DID_roll_reports_the_slice_count(fold, monkeypatch) -> None:
    rc, s3, puts = _patched_main(
        fold, monkeypatch, chain_rc=0, rolled=datetime.now(timezone.utc) + timedelta(hours=1),
        manifests={"graphrag_evidence/eval/write_manifest_rebuild_%s.json"
                   % datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"): _MANIFEST_20260821})
    assert rc == 0
    ledger = dict(s3.puts)["graphrag_evidence/fold/last_run.json"]
    assert ledger["outcome"] == "CORPUS_FOLD_OK"
    assert ledger["slice_objects_written"] == 196 and ledger["manifest_docs_written"] == 0
    assert {d["MetricName"]: d["Value"]
            for d in puts[0]["MetricData"]}[fold.METRIC_SLICES_WRITTEN] == 196.0


def test_a_GUARD4_refusal_is_itself_REPORTED_and_costs_nothing(fold, monkeypatch) -> None:
    """A pre-flight refusal is a fire that happened and wrote nothing. Unreported, a monthly fold
    could refuse every month for 35 days before the liveness alarm noticed; reported, the failure
    alarm sees it the next day. And it must spend nothing: no backup LIST, no chain."""
    sm = fold._guards()
    monkeypatch.setattr(sm, "assert_not_live_rebuild", lambda **kw: None)
    monkeypatch.setattr(fold.subprocess, "call",
                        lambda *a, **k: pytest.fail("a refused fold must not launch a step"))
    s3, puts = _FakeS3(), []

    class _CW:
        def put_metric_data(self, **kw):
            puts.append(kw)

    import boto3
    monkeypatch.setattr(boto3, "client",
                        lambda service, **kw: _CW() if service == "cloudwatch" else s3)
    monkeypatch.setattr(fold.cc, "bind_evidence_prefix", lambda p, **kw: p.rstrip("/"))
    rc = fold.main(["--stage", "fold", "--evidence-s3", LIVE, "--i-know-this-is-live",
                    "--census-baseline", LIVE + "/eval/SOMETHING_ELSE.json"])
    assert rc == 1 and s3.copies == []
    ledger = dict(s3.puts)["graphrag_evidence/fold/last_run.json"]
    assert ledger["outcome"] == "CORPUS_FOLD_REFUSED"
    assert "is not the key this fold can roll" in ledger["note"]
    assert {d["MetricName"]: d["Value"] for d in puts[0]["MetricData"]}[fold.METRIC_FAILURES] == 1.0


def test_a_fold_that_REBUILT_and_then_failed_its_gate_reports_BOTH_facts(fold, monkeypatch) -> None:
    """Why there are three metrics and not two. A red census gate stops the chain AFTER the rebuild
    has already rewritten its 196 objects, so `SlicesWritten` is 196 on that fire and an alarm on
    "wrote nothing" cannot see it. `CorpusFoldFailures` can, and the ledger carries the rc."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rc, s3, puts = _patched_main(
        fold, monkeypatch, chain_rc=1, rolled=None,
        manifests={"graphrag_evidence/eval/write_manifest_rebuild_%s.json" % stamp:
                   _MANIFEST_20260821})
    assert rc == 1
    by = {d["MetricName"]: d["Value"] for d in puts[0]["MetricData"]}
    assert by[fold.METRIC_SLICES_WRITTEN] == 196.0 and by[fold.METRIC_FAILURES] == 1.0
    ledger = dict(s3.puts)["graphrag_evidence/fold/last_run.json"]
    assert ledger["outcome"] == "CORPUS_FOLD_CHAIN_FAILED" and ledger["slice_objects_written"] == 196


def test_a_fold_that_CRASHES_IN_ITS_BACKUP_still_reports_that_it_FIRED(fold, monkeypatch) -> None:
    """R2 MINOR-2. "Every exit leaves a ledger line and three datums" was true only for SystemExit.

    `take_backup` raises SystemExit for a PARTIAL copy, but `s3.copy` itself raises ClientError /
    S3UploadFailedError -- and that escaped main() with NO ledger and NO datum, so a fold that died
    in its own backup was indistinguishable from a fold that NEVER FIRED, which is precisely the
    distinction `CorpusFoldRuns` was added to make. It would have surfaced on the 35-day liveness
    alarm instead of the next-day failure alarm."""
    sm = fold._guards()
    monkeypatch.setattr(sm, "assert_not_live_rebuild", lambda **kw: None)
    monkeypatch.setattr(fold.subprocess, "call", lambda cmd, env=None: 0)

    class _Crashing(_FakeS3):
        def copy(self, src, bucket, dst):
            raise ClientError({"Error": {"Code": "SlowDown", "Message": "please"}}, "CopyObject")

    s3 = _Crashing(objects={"graphrag_evidence/cocoa.jsonl": 1})
    puts: list = []

    class _CW:
        def put_metric_data(self, **kw):
            puts.append(kw)

    import boto3
    monkeypatch.setattr(boto3, "client",
                        lambda service, **kw: _CW() if service == "cloudwatch" else s3)
    monkeypatch.setattr(fold.cc, "bind_evidence_prefix", lambda p, **kw: p.rstrip("/"))
    rc = fold.main(["--stage", "fold", "--evidence-s3", LIVE, "--i-know-this-is-live",
                    "--census-baseline", BASELINE])
    assert rc == 1, "a crashed backup is a FAILED fold, never a quiet one"
    assert puts, "the datums must exist -- this is the fire/no-fire distinction itself"
    by = {d["MetricName"]: d["Value"] for d in puts[0]["MetricData"]}
    assert by[fold.METRIC_RUNS] == 1.0 and by[fold.METRIC_FAILURES] == 1.0
    ledger = dict(s3.puts)["graphrag_evidence/fold/last_run.json"]
    assert ledger["outcome"] == "CORPUS_FOLD_CRASHED" and "ClientError" in ledger["note"]
    # AND THE REBUILD NEVER RAN: the backup is STEP 1 and a fold does not proceed without it.
    assert s3.puts and ledger["slice_objects_written"] == 0


def test_a_DRY_RUN_emits_NOTHING_and_writes_NOTHING(fold, monkeypatch) -> None:
    """The lane's contract, and the reason sitting 1 could run this task read-only."""
    sm = fold._guards()
    monkeypatch.setattr(sm, "assert_not_live_rebuild", lambda **kw: None)
    s3, puts = _FakeS3(), []

    class _CW:
        def put_metric_data(self, **kw):
            puts.append(kw)

    import boto3
    monkeypatch.setattr(boto3, "client",
                        lambda service, **kw: _CW() if service == "cloudwatch" else s3)
    monkeypatch.setattr(fold.cc, "bind_evidence_prefix", lambda p, **kw: p.rstrip("/"))
    rc = fold.main(["--stage", "fold", "--evidence-s3", LIVE, "--census-baseline", BASELINE,
                    "--dry-run"])
    assert rc == 0 and puts == [] and s3.puts == [] and s3.copies == []


def test_the_task_still_offers_no_allow_churn_and_no_way_to_skip_the_roll(fold) -> None:
    """A guard on this change: the roll must not have opened a door the round-1 guards closed, and
    there must be no flag that turns the roll off -- an optional fence decays into an absent one."""
    with pytest.raises(SystemExit):
        fold.build_parser().parse_args(["--stage", "fold", "--evidence-s3", LIVE,
                                        "--allow-churn", "50.0"])
    for flag in ("--no-advance-baseline", "--no-roll", "--skip-census-write"):
        with pytest.raises(SystemExit):
            fold.build_parser().parse_args(["--stage", "fold", "--evidence-s3", LIVE, flag])


def test_the_source_is_ascii(fold) -> None:
    _TASK.read_text(encoding="utf-8").encode("ascii")
