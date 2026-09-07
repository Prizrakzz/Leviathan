"""Phase G sitting 1 -- the two script-form wrappers and the writer seam they gate.

THE LOAD-BEARING PIN IS THE DESCRIPTOR LINT. `scripts/silver/gen_sfn_inputs.py:311-323` accepts
exactly two Batch shapes -- module-form must carry `-m` at command[0] AND a `jobs.*` name at
command[1]; script-form must end command[0] in `.py` -- and it also runs a REQUIRED-OPTIONS probe
(:363-371) that AST-reads the target script for `required=True` arguments and rejects a command that
omits one. The design's draft wrote `python -m leviathan.graphrag.evidence_batch --fill ...` and
`["-c", script]`; BOTH are rejected, which is why these two wrappers exist at all. The tests below
run the real lint over the real frozen commands so "the schedule is legal" is a measurement, not a
claim.

The second pin is FLAG-OFF BYTE IDENTITY. G2 sits in `raw_to_text.writer.write_document`, which every
text producer calls. With `CORPUS_LANE_GATES` unset the function must put the SAME bytes with the
SAME kwargs it put before the gate existed -- including for a key the armed gate would refuse.

NOT COVERED HERE: no S3, no Batch, no Anthropic client, no network. The wrappers' S3 paths are
exercised by the live read-only dry runs, not by this deck.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from leviathan.graphrag import batch_extract as bx
from leviathan.graphrag import corpus_coverage as cc
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import evidence_batch as eb
from leviathan.transforms.raw_to_text import writer as wr

_REPO = Path(__file__).resolve().parents[2]


def _load(path: Path, name: str):
    """Import a jobs/ script by path (jobs/ is a namespace package with no __init__.py)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ingest():
    return _load(_REPO / "jobs" / "batch" / "corpus_ingest_task.py", "_corpus_ingest_task")


@pytest.fixture(scope="module")
def fold():
    return _load(_REPO / "jobs" / "batch" / "corpus_fold_task.py", "_corpus_fold_task")


@pytest.fixture(scope="module")
def lint():
    sys.path.insert(0, str(_REPO / "scripts" / "silver"))
    import gen_sfn_inputs
    return gen_sfn_inputs


# ---------------------------------------------------------------------------
# THE FROZEN COMMANDS -- exactly as the design's S 7.2 writes them
# ---------------------------------------------------------------------------

INGEST_COMMAND = ["jobs/batch/corpus_ingest_task.py", "--stage", "chunk",
                  "--max-docs", "200", "--max-usd", "5", "--poll-budget-seconds", "5400"]
FOLD_COMMAND = ["jobs/batch/corpus_fold_task.py", "--stage", "fold",
                "--evidence-s3", "s3://leviathan-dev-shahem-001/graphrag_evidence",
                "--census-baseline",
                "s3://leviathan-dev-shahem-001/graphrag_evidence/eval/e1_census.json"]


def _descriptor(task_id: str, command: list[str]) -> dict:
    """A minimal descriptor shaped like configs/silver/dags/wap.json, carrying ONE task."""
    return {
        "schedule": "corpus_lane_probe", "family": "graphrag_evidence", "wave": 3,
        "cron": "cron(0 12 ? * MON *)", "publish_class": "A", "promote_mode": "stop_and_notify",
        "auth_mode": "kms", "gate_tables": ["silver_wap_table01"],
        "gate_baseline_uri": "s3://leviathan-dev-shahem-001/cascade_census/rolling/wap/census.json",
        "asof": "<aws.scheduler.scheduled-time>",
        "retry": {"maximum_retry_attempts": 3, "maximum_event_age_in_seconds": 86400},
        "phases": [{"name": "silver", "tasks": [{
            "id": task_id, "invocation_form": "s", "integration": "batch",
            "jobdef": "leviathan-dev-evidence-build", "queue": "leviathan-dev-queue-ondemand",
            "command": command, "env": {}, "publishes": False}]}],
    }


@pytest.mark.parametrize("task_id,command", [("corpus_ingest_chunk", INGEST_COMMAND),
                                             ("corpus_fold", FOLD_COMMAND)])
def test_the_frozen_commands_pass_the_descriptor_lint(lint, task_id, command) -> None:
    errs = lint.lint_descriptor(_descriptor(task_id, command), "corpus_lane_probe")
    task_errs = [e for e in errs if task_id in e]
    assert task_errs == [], task_errs
    assert errs == [], errs


@pytest.mark.parametrize("command", [INGEST_COMMAND, FOLD_COMMAND])
def test_script_form_rule_command_zero_ends_in_py_and_the_file_exists(lint, command) -> None:
    """`gen_sfn_inputs.py:320-323`: script-form command[0] must be a .py path. And the required-
    options probe reads that FILE, so it has to exist and be AST-parseable before any schedule can
    render."""
    assert str(command[0]).endswith(".py")
    script = lint._script_path(command)
    assert script is not None and script.exists()


@pytest.mark.parametrize("command", [INGEST_COMMAND, FOLD_COMMAND])
def test_every_required_option_the_script_declares_is_present_in_the_frozen_command(
        lint, command) -> None:
    """The 2026-08-18 defect this probe exists for: `production_faostat`'s fetch leg was
    `upload_faostat.py` with NO `--file`, which that script declares required -- the family was armed
    with a command that could never run and argparse-exit-2'd terminally at fire time."""
    required = lint._required_options(lint._script_path(command))
    assert required, "the wrapper must declare at least one required option so the probe is not vacuous"
    assert [opt for opt in required if opt not in command] == []


@pytest.mark.parametrize("command", [INGEST_COMMAND, FOLD_COMMAND])
def test_no_value_expecting_option_is_left_dangling(lint, command) -> None:
    """The SFN passes the container override VERBATIM, so a bare value-option makes the job's
    argparse exit 2 ("expected one argument"). No token in these commands is a `--opt` that ends the
    command or is followed by another `--opt`."""
    for i, tok in enumerate(command):
        if not (isinstance(tok, str) and tok.startswith("--")):
            continue
        assert i + 1 < len(command), tok
        assert not str(command[i + 1]).startswith("--"), tok


def test_the_frozen_ingest_command_actually_parses(ingest) -> None:
    args = ingest.build_parser().parse_args(INGEST_COMMAND[1:])
    assert args.stage == "chunk"
    assert args.max_docs == 200 and args.max_usd == 5.0 and args.poll_budget_seconds == 5400
    assert args.dry_run is False


def test_the_wrappers_defaults_are_the_designs_caps(ingest) -> None:
    args = ingest.build_parser().parse_args(["--stage", "census"])
    assert args.max_docs == cc.MAX_DOCS_DEFAULT == 200
    assert args.max_usd == cc.MAX_USD_DEFAULT == 5.0
    assert args.poll_budget_seconds == cc.POLL_BUDGET_SECONDS_DEFAULT == 5400


def test_stage_is_required_and_bounded(ingest) -> None:
    with pytest.raises(SystemExit):
        ingest.build_parser().parse_args([])
    with pytest.raises(SystemExit):
        ingest.build_parser().parse_args(["--stage", "fold"])
    assert set(ingest.STAGES) == {"fetch", "text", "chunk", "census"}


def test_the_run_date_is_injectable_and_is_the_only_clock_read(ingest) -> None:
    """Every pure core takes `today` explicitly; this is the ONE place the lane reads a clock, and
    `--asof` overrides it so a rehearsal is reproducible."""
    assert ingest._run_date("2026-05-21") == date(2026, 5, 21)
    assert ingest._run_date("2026-05-21T18:00:00Z") == date(2026, 5, 21)
    assert isinstance(ingest._run_date(None), date)


# ---------------------------------------------------------------------------
# the fold wrapper's inline guards
# ---------------------------------------------------------------------------

def test_the_fold_task_offers_no_allow_churn_flag(fold) -> None:
    """An add-only fold must never need one, and a refusal on an add-only pass IS the finding. The
    2026-08-21 rebuild ran `--allow-churn 50.0` and recorded `barley_yellow_dwarf_virus` (prior 2
    props) and `wheat_blast` (prior 123) as `unwritten` rather than refusing."""
    opts = {s for a in fold.build_parser()._actions for s in a.option_strings}
    assert "--allow-churn" not in opts
    with pytest.raises(SystemExit):                         # argparse exits 2 before any work
        fold.build_parser().parse_args(
            ["--stage", "fold", "--evidence-s3", "s3://b/p", "--allow-churn", "25"])


def test_the_fold_task_requires_stage_and_evidence_s3(fold) -> None:
    """Both are in the design's frozen command AND are `required=True`, so the descriptor lint's
    required-options probe proves the schedule carries them."""
    ap = fold.build_parser()
    with pytest.raises(SystemExit):
        ap.parse_args([])
    with pytest.raises(SystemExit):
        ap.parse_args(["--stage", "fold"])
    args = ap.parse_args(FOLD_COMMAND[1:])
    assert args.stage == "fold" and args.evidence_s3.startswith("s3://")
    assert args.with_pg_load is False and args.with_pg_swap is False


def test_the_fold_chain_is_lint_then_rebuild_then_census_with_an_explicit_baseline(fold) -> None:
    ns = _ns(stage="fold", evidence_s3="s3://b/p", census_baseline="s3://b/p/eval/e1_census.json",
             with_pg_load=False, with_pg_swap=False, pg_shadow_table="evidence_props_shadow")
    steps = fold.chain_steps(ns)
    assert steps[0] == ["-m", "leviathan.graphrag.driver_slices_manifest", "--check"]
    assert steps[1] == ["-m", "leviathan.graphrag.evidence_batch", "--rebuild-slices"]
    assert steps[2] == ["-m", "leviathan.graphrag.e1_census", "--diff",
                        "--baseline", "s3://b/p/eval/e1_census.json"]
    assert len(steps) == 3
    assert all("--allow-churn" not in s for s in steps)


def test_the_pg_legs_are_off_by_default_and_append_in_order(fold) -> None:
    """R3 stays MANUAL for its first three cycles; these switches exist so the chain is expressible
    and rehearsable, not so a schedule flips pg on its own."""
    ns = _ns(stage="fold", evidence_s3="s3://b/p", census_baseline="x",
             with_pg_load=True, with_pg_swap=True, pg_shadow_table="evidence_props_shadow")
    steps = fold.chain_steps(ns)
    assert steps[3] == ["-m", "jobs.utils.load_pg_evidence", "--all",
                        "--table", "evidence_props_shadow"]
    assert steps[4] == ["-m", "jobs.utils.pg_evidence_swap", "--swap"]


def test_the_fold_task_imports_the_submitters_guards_rather_than_copying_them(fold) -> None:
    """ONE definition of `assert_not_live_rebuild` and of the gated chain, so no copy can drift.
    The descriptor path never touches the submitter, which is why the guards run container-side."""
    sm = fold._guards()
    assert callable(sm.assert_not_live_rebuild)
    assert callable(sm.build_command)
    assert sm._MANIFEST_LINT_CMD[:2] == ["-m", "leviathan.graphrag.driver_slices_manifest"]
    assert sm._CENSUS_GATE_CMD[:2] == ["-m", "leviathan.graphrag.e1_census"]


def test_the_backup_plan_maps_every_commodity_and_driver_slice_into_the_backup_root(fold) -> None:
    """Every prior slice-rewriting pass in this estate took a copy first; the write guard emits only
    WARNs on real drops and is demonstrably not a substitute.

    (Renamed in the fix pass: this test never asserted a SIBLING root -- it asserts the CHILD root
    `graphrag_evidence/_backup_pre_corpuslane_<date>`, the same property the next test pins. A safety
    pin whose name states the defect it was written to close is a readability hazard.)"""
    s3 = MagicMock()
    s3.get_paginator.return_value.paginate.side_effect = [
        [{"Contents": [{"Key": "graphrag_evidence/soybeans.jsonl"},
                       {"Key": "graphrag_evidence/corn.jsonl"}]}],
        [{"Contents": [{"Key": "graphrag_evidence/drivers/tariff.jsonl"}]}],
    ]
    bp = fold.backup_plan(s3, "s3://leviathan-dev-shahem-001/graphrag_evidence",
                          stamp="_backup_pre_corpuslane_20260907")
    assert bp["n"] == 3
    assert bp["dst_root"] == "graphrag_evidence/_backup_pre_corpuslane_20260907"
    assert bp["plan"]["graphrag_evidence/drivers/tariff.jsonl"] == \
        "graphrag_evidence/_backup_pre_corpuslane_20260907/drivers/tariff.jsonl"


def test_the_backup_root_is_a_CHILD_of_the_prefix_not_a_sibling(fold) -> None:
    """MEASURED on the first fold dry run: a SIBLING root sent a shadow rehearsal's backup into the
    LIVE prefix's namespace (`graphrag_evidence/_backup_pre_corpuslane_<date>`), where it would
    collide with the live fold's own backup of the same date. The estate's five prior backup
    prefixes are all CHILDREN of `graphrag_evidence/`."""
    s3 = MagicMock()
    s3.get_paginator.return_value.paginate.side_effect = [
        [{"Contents": [{"Key": "graphrag_evidence/shadow_originpolicy/soybeans.jsonl"}]}],
        [{"Contents": [{"Key": "graphrag_evidence/shadow_originpolicy/drivers/tariff.jsonl"}]}],
    ]
    bp = fold.backup_plan(s3, "s3://b/graphrag_evidence/shadow_originpolicy",
                          stamp="_backup_pre_corpuslane_20260907")
    assert bp["dst_root"] == \
        "graphrag_evidence/shadow_originpolicy/_backup_pre_corpuslane_20260907"
    assert all(v.startswith(bp["src_prefix"] + "/") for v in bp["plan"].values())


def test_a_partial_backup_refuses_the_fold(fold) -> None:
    s3 = MagicMock()
    s3.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "graphrag_evidence/_backup_pre_corpuslane_20260907/a.jsonl"}]}]
    bp = {"bucket": "b", "src_prefix": "graphrag_evidence",
          "dst_root": "graphrag_evidence/_backup_pre_corpuslane_20260907",
          "plan": {"graphrag_evidence/a.jsonl": "graphrag_evidence/_backup_pre_corpuslane_20260907/a.jsonl",
                   "graphrag_evidence/b.jsonl": "graphrag_evidence/_backup_pre_corpuslane_20260907/b.jsonl"},
          "n": 2}
    with pytest.raises(SystemExit) as exc:
        fold.take_backup(s3, bp)
    assert "partial backup" in str(exc.value)


def _ns(**kw):
    class _N:
        pass
    n = _N()
    for k, v in kw.items():
        setattr(n, k, v)
    return n


# ---------------------------------------------------------------------------
# G2 at the writer seam: flag-off byte identity
# ---------------------------------------------------------------------------

_DOC = {"source": "usda_wasde", "raw_key": "raw/k.pdf", "extraction_method": "pdfplumber",
        "extracted_at": "2026-09-07T00:00:00Z", "sections": [], "full_text": "hello"}
_REFUSABLE_KEY = "text/source=zzz_new_source/whatever/document.json"       # layout == unknown


def test_the_writer_gate_is_dark_by_default_and_the_body_is_byte_identical(monkeypatch) -> None:
    """FLAG OFF: the same bytes, the same kwargs, for a key the ARMED gate would refuse. This is the
    pin that lets the gate ship dark into every text producer."""
    monkeypatch.delenv(wr._GATE_FLAG, raising=False)
    s3 = MagicMock()
    wr.write_document(s3, "my-bucket", _REFUSABLE_KEY, _DOC)
    kw = s3.put_object.call_args.kwargs
    expected = json.dumps(_DOC, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert kw == {"Bucket": "my-bucket", "Key": _REFUSABLE_KEY, "Body": expected,
                  "ContentType": "application/json"}
    assert kw["Body"] == expected                       # byte identity, not merely equal JSON
    assert b"\n" not in kw["Body"]


def test_the_writer_gate_armed_refuses_an_unknown_layout_and_writes_NOTHING(monkeypatch) -> None:
    monkeypatch.setenv(wr._GATE_FLAG, "on")
    cc.reset_refusals()
    s3 = MagicMock()
    with pytest.raises(cc.KeyLayoutRefused):
        wr.write_document(s3, "my-bucket", _REFUSABLE_KEY, _DOC)
    s3.put_object.assert_not_called()
    assert cc.refusal_counts()["refused"] == 1
    cc.reset_refusals()


@pytest.mark.parametrize("key", [
    "text/source=conab/crop_year=2024_25/survey=03/document.json",
    "text/source=mpob/release_type=overview_pdf/year=2016/document.json",
])
def test_the_writer_gate_armed_takes_conab_and_mpob_out_of_the_write_path(monkeypatch, key) -> None:
    monkeypatch.setenv(wr._GATE_FLAG, "on")
    s3 = MagicMock()
    with pytest.raises(cc.KeyLayoutRefused):
        wr.write_document(s3, "b", key, _DOC)
    s3.put_object.assert_not_called()


def test_the_writer_gate_armed_still_writes_a_dateable_key(monkeypatch) -> None:
    monkeypatch.setenv(wr._GATE_FLAG, "on")
    s3 = MagicMock()
    good = "text/source=usda_wasde/release_date=2026-08-12/document.json"
    wr.write_document(s3, "b", good, _DOC)
    s3.put_object.assert_called_once()


def test_the_flag_name_and_truthy_set_cannot_drift_from_corpus_coverage() -> None:
    """writer.py duplicates the two constants rather than importing the module, so the DARK path
    pays no import at all (corpus_coverage reaches evidence.py -> extract.py -> yaml + pydantic).
    This is the pin that makes the duplication safe."""
    assert wr._GATE_FLAG == cc.GATE_FLAG == "CORPUS_LANE_GATES"
    assert wr._TRUTHY == cc._TRUTHY
    assert wr._gate_armed.__module__ == wr.__name__


def test_document_exists_is_untouched_by_the_gate(monkeypatch) -> None:
    """The idempotency gate stays exactly where it was (writer.py:14-26, head_object). G2 sits
    before the WRITE, not before the existence check."""
    monkeypatch.setenv(wr._GATE_FLAG, "on")
    s3 = MagicMock()
    s3.head_object.return_value = {}
    assert wr.document_exists(s3, "b", _REFUSABLE_KEY) is True


# ===========================================================================
# THE BILLED LEG -- the stage that spends money and mutates the store
# ===========================================================================
# WHY THIS SECTION EXISTS. The first pass shipped 71 green tests that pinned the pure cores, the
# gates, the descriptor lint, the metric cardinality and the writer's flag-off byte identity -- and
# nothing at all on `stage_chunk`. A grep for `stage_chunk|_gap_doc_keys|_drain_batch|
# _set_outstanding|_write_ledger|submit_docs` across tests/unit/ returned NOTHING and neither deck
# mentioned `EVIDENCE_S3`. That is exactly why two fatals shipped undetected: `--evidence-s3` was
# honoured by the census, the caps and the ledger while every billed call read the ENVIRONMENT
# instead (evidence._evid_s3, evidence.py:42-43), so the flag could point at a shadow while the
# chunks landed live, and with the variable unset `_cached_hashes()` came back EMPTY -- 127
# candidates / 1,352 blocks / $6.21 on usda_gain_soybeans against 69 candidates / 0 blocks bound.
# Each pin below is one assertion away from the defect it closes. NO S3, NO ANTHROPIC, NO NETWORK.

_LIVE = "s3://leviathan-dev-shahem-001/graphrag_evidence"
_SHADOW = "s3://leviathan-dev-shahem-001/graphrag_evidence/shadow_originpolicy"
_TODAY = date(2026, 9, 7)


@pytest.fixture
def evidence_env():
    """Snapshot/restore EVIDENCE_S3 around a test that lets production code MUTATE os.environ.

    monkeypatch.setenv cannot do this job alone: `main()` writes the variable itself, and
    `monkeypatch.delenv(..., raising=False)` on an unset name records nothing to restore, so the
    write would leak into every later test in the session."""
    prior = os.environ.get("EVIDENCE_S3")
    try:
        yield os.environ
    finally:
        if prior is None:
            os.environ.pop("EVIDENCE_S3", None)
        else:
            os.environ["EVIDENCE_S3"] = prior


def _census(**per_source):
    """A census shaped like `build_census`'s output -- every key the chunk stage AND the post-fire
    `ledger_document` read, so a stub can never pass a test the real census would fail."""
    src = {name: {"gap": rec.get("gap", 1),
                  "struck_from_write_path": rec.get("struck", False),
                  "newest_covered_pub": rec.get("covered"),
                  "coverage": rec.get("coverage", 1.0),
                  "chunk_lag_days": rec.get("chunk_lag"),
                  "fetch_lag_days": rec.get("fetch_lag")}
           for name, rec in per_source.items()}
    return {"sources": src, "totals": {"docs": sum(r["gap"] for r in src.values())}}


def _stub_reads(monkeypatch, census):
    monkeypatch.setattr(cc, "read_inputs", lambda **kw: {"text_keys": [], "chunk_names": [],
                                                         "alias_rows": [], "raw_keys": []})
    monkeypatch.setattr(cc, "build_census", lambda *a, **k: census)


def _stub_split(monkeypatch, *, n_blocks, doc_keys):
    """The free local split: `_build_requests_from_docs` returns (requests, manifest)."""
    monkeypatch.setattr(eb, "select_docs", lambda sources, **kw: list(doc_keys))
    monkeypatch.setattr(eb, "store_path_index", lambda s3: {})
    monkeypatch.setattr(eb, "DedupGate", lambda **kw: MagicMock())
    monkeypatch.setattr(eb, "DocReadTally", lambda **kw: MagicMock())
    monkeypatch.setattr(eb, "DarkTally", lambda **kw: MagicMock())
    manifest = {i: {"source_key": k} for i, k in enumerate(doc_keys)}
    monkeypatch.setattr(eb, "_build_requests_from_docs",
                        lambda s3, keys, **kw: ([{"i": i} for i in range(n_blocks)], manifest))


def _chunk_args(**kw):
    base = dict(stage="chunk", sources="", max_docs=cc.MAX_DOCS_DEFAULT,
                max_usd=cc.MAX_USD_DEFAULT, poll_budget_seconds=5400, poll_seconds=20,
                all_gap=True, asof="2026-09-07", evidence_s3=_SHADOW, bucket=cc.BUCKET,
                aws_region="us-east-1", ledger_out=None, dry_run=True)
    base.update(kw)
    return _ns(**base)


# --- the prefix binding: the ONE channel evidence_batch actually reads ------------------

def test_every_stage_exports_the_flag_as_EVIDENCE_S3_before_the_stage_runs(
        ingest, monkeypatch, evidence_env) -> None:
    """THE FATAL, PINNED. `evidence_batch` has no --evidence-s3 flag: `_cached_hashes`,
    `store_path_index`, `DedupGate`, `_build_requests_from_docs`, `submit_docs`, `retrieve` and
    `_save_manifest` all resolve `evidence._evid_s3()`. So the flag is only real if it reaches the
    environment, and it must reach it BEFORE the stage runs."""
    os.environ["EVIDENCE_S3"] = _LIVE
    seen = {}

    def fake_stage(args, today):
        seen["env"] = os.environ.get("EVIDENCE_S3")
        seen["args"] = args.evidence_s3
        seen["evid"] = ev._evid_s3()                            # the exact call the billed path makes
        return 0

    monkeypatch.setattr(ingest, "stage_census", fake_stage)
    assert ingest.main(["--stage", "census", "--dry-run", "--evidence-s3", _SHADOW]) == 0
    assert seen["env"] == seen["args"] == seen["evid"] == _SHADOW


def test_a_disagreeing_ambient_prefix_is_rebound_loudly_never_silently(
        ingest, monkeypatch, capsys, evidence_env) -> None:
    """The jobdef bakes the LIVE prefix (submit_batch_evidence_maintenance.py:228), so a shadow
    rehearsal ALWAYS disagrees with the ambient value. Refusing there would refuse every rehearsal;
    the flag wins and the override is announced."""
    os.environ["EVIDENCE_S3"] = _LIVE
    monkeypatch.setattr(ingest, "stage_census", lambda a, t: 0)
    ingest.main(["--stage", "census", "--dry-run", "--evidence-s3", _SHADOW])
    out = capsys.readouterr().out
    assert "EVIDENCE_S3 REBOUND" in out and _LIVE in out and _SHADOW in out


def test_the_billed_leg_refuses_when_the_prefix_is_neither_declared_nor_inherited(
        ingest, monkeypatch, evidence_env) -> None:
    """MEASURED: with EVIDENCE_S3 unset `_cached_hashes()` returns an EMPTY set, so the idempotency
    skip, the store_path layer and the alias index are all dead and `--all-gap --sources
    usda_gain_soybeans` read 127 candidates / 1,352 blocks / $6.21 instead of 69 / 0. The chunk leg
    does NOT fall through to a hardcoded default."""
    os.environ.pop("EVIDENCE_S3", None)
    ran = []
    monkeypatch.setattr(ingest, "stage_chunk", lambda a, t: ran.append(1) or 0)
    with pytest.raises(SystemExit) as exc:
        ingest.main(["--stage", "chunk", "--dry-run"])
    assert "1,352 blocks" in str(exc.value) and "_cached_hashes" in str(exc.value)
    assert ran == []                                            # refused BEFORE the stage


def test_a_read_only_stage_may_fall_back_but_binds_what_it_falls_back_to(
        ingest, monkeypatch, evidence_env) -> None:
    """The census has always defaulted to the live prefix and stays free to; what it may NOT do is
    leave two readers in one process disagreeing about which store it measured."""
    os.environ.pop("EVIDENCE_S3", None)
    seen = {}
    monkeypatch.setattr(ingest, "stage_census",
                        lambda a, t: seen.update(env=os.environ.get("EVIDENCE_S3"),
                                                 args=a.evidence_s3) or 0)
    assert ingest.main(["--stage", "census", "--dry-run"]) == 0
    assert seen["env"] == seen["args"] == cc.evidence_prefix()


def test_stage_chunk_refuses_a_diverged_prefix_before_it_reads_anything(
        ingest, monkeypatch, evidence_env) -> None:
    """Defence in depth, read through `evidence._evid_s3` itself rather than a copy of the idea: if
    anything between main() and here moves the variable, the fire refuses instead of pricing one
    store and writing to another."""
    os.environ["EVIDENCE_S3"] = _LIVE
    with pytest.raises(SystemExit) as exc:
        ingest.stage_chunk(_chunk_args(evidence_s3=_SHADOW), _TODAY)
    assert _LIVE in str(exc.value) and _SHADOW in str(exc.value)


# --- the caps, the drain, the ledger ----------------------------------------------------

def test_the_cap_refusal_inside_stage_chunk_bills_nothing_and_names_the_number(
        ingest, monkeypatch, capsys, evidence_env) -> None:
    """rc=2, LOUD, and `submit_docs` untouched. The caps bound HAIKU TOKENS ONLY -- the wall clock
    is bounded by --poll-budget-seconds -- and the refusal says so."""
    os.environ["EVIDENCE_S3"] = _SHADOW
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: MagicMock())
    monkeypatch.setattr(cc, "read_ledger", lambda **kw: {})
    _stub_reads(monkeypatch, _census(usda_fas_coffee_wmt={"gap": 300}))
    _stub_split(monkeypatch, n_blocks=2213, doc_keys=["k%d" % i for i in range(686)])
    submitted = []
    monkeypatch.setattr(eb, "submit_docs", lambda *a, **k: submitted.append(a) or "msgbatch_x")
    rc = ingest.stage_chunk(_chunk_args(dry_run=False, max_docs=200, max_usd=5.0), _TODAY)
    out = capsys.readouterr().out
    assert rc == 2 and submitted == []
    assert "686" in out and "2213" in out and "10.16" in out


def test_the_outstanding_batch_is_drained_before_anything_new_is_selected(
        ingest, monkeypatch, evidence_env) -> None:
    """THE TWO-PHASE FIRE. `_save_manifest` (evidence_batch.py:837-845) persists the block manifest
    to <EVIDENCE_S3>/_batches/<bid>.json precisely so a DIFFERENT Fargate job can retrieve it, and
    the poll budget only works if the NEXT fire drains before it submits."""
    os.environ["EVIDENCE_S3"] = _SHADOW
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: MagicMock())
    monkeypatch.setattr(cc, "read_ledger", lambda **kw: {"outstanding_batch_id": "msgbatch_prior"})
    order = []
    _stub_reads(monkeypatch, _census(usda_wasde={"gap": 1}))
    monkeypatch.setattr(cc, "read_inputs", lambda **kw: order.append("select") or
                        {"text_keys": [], "chunk_names": [], "alias_rows": [], "raw_keys": []})
    _stub_split(monkeypatch, n_blocks=0, doc_keys=[])
    monkeypatch.setattr(ingest, "_drain_batch",
                        lambda a, s3, bid, **kw: order.append("drain:" + bid) or 0)
    ingest.stage_chunk(_chunk_args(dry_run=False), _TODAY)
    assert order[0] == "drain:msgbatch_prior"


def test_the_poll_budget_expiry_parks_the_bid_in_the_ledger_and_exits_0(
        ingest, monkeypatch, evidence_env) -> None:
    """`retrieve` polls forever on its own (evidence_batch.py:1369-1371) and the jobdef is
    `timeout: None` -- a 24 h Batch SLA is $28.35 for ONE fire. On expiry the bid is PARKED and the
    exit is 0: the designed outcome, not a failure."""
    os.environ["EVIDENCE_S3"] = _SHADOW
    import anthropic
    client = MagicMock()
    client.messages.batches.retrieve.return_value.processing_status = "in_progress"
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: client)
    monkeypatch.setattr(bx, "_api_key", lambda: "sk-test")
    parked = []
    monkeypatch.setattr(ingest, "_set_outstanding", lambda a, bid: parked.append(bid))
    retrieved = []
    monkeypatch.setattr(eb, "retrieve", lambda *a, **k: retrieved.append(a))
    rc = ingest._drain_batch(_chunk_args(poll_budget_seconds=0), MagicMock(), "msgbatch_slow")
    assert rc == 0 and parked == ["msgbatch_slow"] and retrieved == []


def test_a_drained_batch_clears_the_outstanding_id_and_does_NOT_route(
        ingest, monkeypatch, evidence_env) -> None:
    """A doc-list retrieve does not route by construction (evidence_batch.py:1428-1432): it grows
    chunks/ and touches no guarded slice. That is what makes the chunk leg legal on the staged seam
    while the FOLD never is."""
    os.environ["EVIDENCE_S3"] = _SHADOW
    import anthropic
    from leviathan.graphrag import write_guard as wg
    client = MagicMock()
    client.messages.batches.retrieve.return_value.processing_status = "ended"
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: client)
    monkeypatch.setattr(bx, "_api_key", lambda: "sk-test")
    monkeypatch.setattr(eb, "_chunk_version", lambda: "v9")
    monkeypatch.setattr(wg, "RunManifest", lambda *a, **k: MagicMock())
    calls = {}
    monkeypatch.setattr(eb, "retrieve", lambda s3, cl, bid, **kw: calls.setdefault("bid", bid))
    cleared = []
    monkeypatch.setattr(ingest, "_set_outstanding", lambda a, bid: cleared.append(bid))
    rc = ingest._drain_batch(_chunk_args(), MagicMock(), "msgbatch_done")
    assert rc == 0 and calls["bid"] == "msgbatch_done" and cleared == [None]
    assert "nodes" not in calls                                  # no routing argument, ever


def test_the_post_fire_ledger_is_written_from_a_SECOND_census(
        ingest, monkeypatch, evidence_env) -> None:
    """Design G5: the ledger and the heartbeat go LAST, and they must describe the store AFTER this
    fire, not before it -- so a half-finished fire never advertises itself as complete."""
    os.environ["EVIDENCE_S3"] = _SHADOW
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: MagicMock())
    monkeypatch.setattr(cc, "read_ledger", lambda **kw: {})
    censuses = []
    monkeypatch.setattr(cc, "read_inputs", lambda **kw: censuses.append("read") or
                        {"text_keys": [], "chunk_names": [], "alias_rows": [], "raw_keys": []})
    monkeypatch.setattr(cc, "build_census", lambda *a, **k: _census(usda_wasde={"gap": 1}))
    _stub_split(monkeypatch, n_blocks=3, doc_keys=["a", "b"])
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: MagicMock())
    monkeypatch.setattr(bx, "_api_key", lambda: "sk-test")
    monkeypatch.setattr(eb, "submit_docs", lambda *a, **k: "msgbatch_new")
    monkeypatch.setattr(ingest, "_set_outstanding", lambda a, bid: None)
    monkeypatch.setattr(ingest, "_drain_batch", lambda *a, **k: 0)
    written = {}
    monkeypatch.setattr(ingest, "_write_ledger", lambda a, led, **kw: written.update(led))
    rc = ingest.stage_chunk(_chunk_args(dry_run=False), _TODAY)
    assert rc == 0
    assert len(censuses) == 2                                    # before the submit, and after it
    assert written["outstanding_batch_id"] is None


def test_the_dry_run_prices_the_split_and_submits_NOTHING(
        ingest, monkeypatch, capsys, evidence_env) -> None:
    os.environ["EVIDENCE_S3"] = _SHADOW
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: MagicMock())
    monkeypatch.setattr(cc, "read_ledger", lambda **kw: {})
    _stub_reads(monkeypatch, _census(usda_wasde={"gap": 1}))
    _stub_split(monkeypatch, n_blocks=12, doc_keys=["a", "b"])
    submitted = []
    monkeypatch.setattr(eb, "submit_docs", lambda *a, **k: submitted.append(1))
    rc = ingest.stage_chunk(_chunk_args(dry_run=True), _TODAY)
    out = capsys.readouterr().out
    assert rc == 0 and submitted == []
    assert "SPLIT: 12 blocks over 2 NEW docs" in out and "$0 billed" in out


def test_the_backlog_rider_names_the_671_deposed_canonicals(
        ingest, monkeypatch, capsys, evidence_env) -> None:
    """An `--all-gap` pass is NOT purely additive: `DedupGate.flush()` re-points 671 existing alias
    canonicals at later-dated byte-identical twins, changing which document's publication date
    survives. PIT-relevant, and it belongs beside the dollars in the backlog's price tag."""
    os.environ["EVIDENCE_S3"] = _SHADOW
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: MagicMock())
    monkeypatch.setattr(cc, "read_ledger", lambda **kw: {})
    _stub_reads(monkeypatch, _census(usda_wasde={"gap": 1}))
    _stub_split(monkeypatch, n_blocks=1, doc_keys=["a"])
    ingest.stage_chunk(_chunk_args(dry_run=True, all_gap=True), _TODAY)
    assert "671 canonical(s) DEPOSED" in capsys.readouterr().out


# --- the fold's chain: the guard and the rebuild cannot describe different stores --------

def test_the_fold_pins_the_bound_prefix_into_every_childs_environment(fold) -> None:
    """THE INVERTED GUARD, PINNED. `chain_steps` step 2 is literally
    ["-m","leviathan.graphrag.evidence_batch","--rebuild-slices"]
    (submit_batch_evidence_maintenance.py:55) and evidence_batch has NO --evidence-s3 flag, so a
    `subprocess.call` with no `env=` rebuilt whatever the JOBDEF baked -- the LIVE store -- while
    GUARD 1 had cleared the SHADOW one and the backup had copied the shadow's objects."""
    env = fold.child_env(_SHADOW, base={"EVIDENCE_S3": _LIVE, "PATH": "/usr/bin"})
    assert env["EVIDENCE_S3"] == _SHADOW
    assert env["PATH"] == "/usr/bin"                            # the rest is inherited verbatim


def test_the_fold_chain_runs_every_step_with_that_environment(fold, monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(fold.subprocess, "call",
                        lambda cmd, env=None: seen.append(env["EVIDENCE_S3"]) or 0)
    steps = [["-m", "a"], ["-m", "leviathan.graphrag.evidence_batch", "--rebuild-slices"]]
    assert fold.run_chain(steps, env={"EVIDENCE_S3": _SHADOW}) == 0
    assert seen == [_SHADOW, _SHADOW]


def test_the_fold_chain_cannot_be_run_without_an_explicit_environment(fold) -> None:
    """`env` is keyword-REQUIRED. A default of "the ambient environment" is exactly the defect."""
    with pytest.raises(TypeError):
        fold.run_chain([["-m", "x"]])

# --- the quiet paths leave a trace (verify seat, 2026-09-07) ---------------------------------

def _recording_ledger(monkeypatch, ingest):
    calls = []
    monkeypatch.setattr(ingest, "_write_ledger",
                        lambda args, ledger, heartbeat=True, outcome="CORPUS_INGEST_OK":
                        calls.append((ledger, heartbeat, outcome)))
    return calls


def test_a_scheduled_fire_with_no_candidates_still_writes_the_ledger_and_heartbeat(
        ingest, monkeypatch, evidence_env) -> None:
    """The weekly no-op path is the ONLY path today (861-document gap vs a 200-document cap), and a
    fire that leaves nothing on S3 is indistinguishable from a fire that never ran."""
    os.environ["EVIDENCE_S3"] = _SHADOW
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: MagicMock())
    monkeypatch.setattr(cc, "read_ledger", lambda **kw: {})
    _stub_reads(monkeypatch, _census(usda_fas_coffee_wmt={"gap": 3}))
    monkeypatch.setattr(ingest, "_gap_doc_keys", lambda args, census, sources: [])
    calls = _recording_ledger(monkeypatch, ingest)
    rc = ingest.stage_chunk(_chunk_args(dry_run=False), _TODAY)
    assert rc == 0
    assert len(calls) == 1 and calls[0][1] is True
    assert calls[0][2] == "CORPUS_INGEST_NO_CANDIDATES"
    assert calls[0][0]["outstanding_batch_id"] is None


def test_the_cap_refusal_leaves_a_heartbeat_that_says_refused(
        ingest, monkeypatch, evidence_env) -> None:
    os.environ["EVIDENCE_S3"] = _SHADOW
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: MagicMock())
    monkeypatch.setattr(cc, "read_ledger", lambda **kw: {})
    _stub_reads(monkeypatch, _census(usda_fas_coffee_wmt={"gap": 300}))
    _stub_split(monkeypatch, n_blocks=2213, doc_keys=["k%d" % i for i in range(686)])
    monkeypatch.setattr(eb, "submit_docs", lambda *a, **k: (_ for _ in ()).throw(AssertionError("billed")))
    calls = _recording_ledger(monkeypatch, ingest)
    rc = ingest.stage_chunk(_chunk_args(dry_run=False, max_docs=200, max_usd=5.0), _TODAY)
    assert rc == 2
    assert [c[2] for c in calls] == ["CORPUS_INGEST_REFUSED_CAP"]


def test_a_dry_run_writes_neither_ledger_nor_heartbeat_on_any_quiet_path(
        ingest, monkeypatch, evidence_env) -> None:
    os.environ["EVIDENCE_S3"] = _SHADOW
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: MagicMock())
    monkeypatch.setattr(cc, "read_ledger", lambda **kw: {})
    _stub_reads(monkeypatch, _census(usda_fas_coffee_wmt={"gap": 3}))
    monkeypatch.setattr(ingest, "_gap_doc_keys", lambda args, census, sources: [])
    calls = _recording_ledger(monkeypatch, ingest)
    assert ingest.stage_chunk(_chunk_args(dry_run=True), _TODAY) == 0
    assert calls == []

