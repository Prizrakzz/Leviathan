"""L5 -- THE WASDE TEXT LEG: it is in the chain, it is in a phase the machine MAPS, and it stops
being blind to a corrected release.

THREE THINGS ARE PINNED HERE AND EACH ONE FAILS ON HEAD.

1. THE DESCRIPTOR. `configs/silver/dags/wasde_monthly.json` was `fetch -> bronze_modern -> silver`
   and nothing else, so `jobs/batch/wasde_text_task.py` -- which exists, is committed, and has a
   registered jobdef -- was reachable by no schedule in the estate. Measured 2026-09-22:
   `raw/production/source=usda_wasde/release_date=2026-09-11/wasde0926.pdf` landed
   2026-09-11T18:13:24Z and `text/source=usda_wasde/` stopped at `release_date=2026-08-12`; that ONE
   document was the uniform 41-day tip of 27 commodity evidence slices.

2. THE PHASE NAME. A `text` phase is NOT a phase this estate has. `gen_sfn_inputs.lint_descriptor`
   accepts only fetch/bronze/silver/gold, and -- worse, because it is silent -- `render_input`
   buckets ONLY those four, so a `text` phase would be DROPPED from the rendered input with no
   error at all. The task therefore rides the SILVER phase and the deck proves it survives the
   render.

3. THE SKIP RULE. Existence-only idempotency on a source whose objects are overwritten in place is
   the MPOB freeze class (cea8818a), and WASDE raw IS overwritten in place: 626 objects across 626
   DISTINCT release_date partitions, zero partitions with a second object, and the whole 1973-1994
   scanned era re-fetched at 2026-08-13T18:06Z over documents written 2026-07-08.

4. THE CLASS, AND THE BACKLOG (round 4, census B-R3-2). Round 3 answered an unbounded tolerance
   with a COUNT, and a count cannot see a class: the round-3 reviewer drove the real `_process_one`
   against a stub S3 and measured ONE head_object throttle TOLERATED (pure infra, exit 0) and TWO
   unreadable PDFs BLOCKING THE MONTH'S CANONICAL (pure document, exit 1) -- backwards in both
   directions. The class is now read off the EXCEPTION, and the tolerance is bounded by a RECORD
   (one marker object per failed release) instead of by a number, because `text_is_current` retries
   a failed release forever and the tolerance is what fills the backlog the number assumed empty.

NOT COVERED HERE: no S3, no Batch, no network. The stubs below are the seam.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

_REPO = Path(__file__).resolve().parents[2]
_DESCRIPTOR = _REPO / "configs" / "silver" / "dags" / "wasde_monthly.json"
_TASK = _REPO / "jobs" / "batch" / "wasde_text_task.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def task():
    return _load(_TASK, "_wasde_text_task")


@pytest.fixture(scope="module")
def desc():
    return json.loads(_DESCRIPTOR.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def lint():
    sys.path.insert(0, str(_REPO / "scripts" / "silver"))
    import gen_sfn_inputs
    return gen_sfn_inputs


def _text_task(desc: dict) -> dict | None:
    for phase in desc.get("phases", []):
        for t in phase.get("tasks", []):
            if str((t.get("command") or [None])[0]).endswith("wasde_text_task.py"):
                return t
    return None


# ---------------------------------------------------------------------------
# 1 + 2 -- the descriptor, and the phase the machine actually maps
# ---------------------------------------------------------------------------

def test_the_wasde_chain_carries_a_text_task_at_all(desc) -> None:
    """THE PIN THAT FAILS ON HEAD. Before this change the text leg was wired into 1 of 30 DAG
    descriptors (mpob.json) and the September WASDE had no document eleven days after it landed."""
    t = _text_task(desc)
    assert t is not None, "wasde_monthly.json has no task running jobs/batch/wasde_text_task.py"
    assert t["invocation_form"] == "s" and t["integration"] == "batch"
    assert t["jobdef"] == "leviathan-dev-text-to-graphrag"
    assert t["queue"] == "leviathan-dev-queue-ondemand"
    assert t.get("publishes") is False, "the text leg writes text/, never a canonical table"
    assert "publish_mode" not in t


def test_the_text_task_is_the_LAST_task_of_the_SILVER_phase(desc) -> None:
    """Position is a blast-radius decision, not a preference. The Map is MaxConcurrency=1, so tasks
    run in descriptor order; here the numbers shadow is already written when the text leg runs, so a
    text failure costs the month's PROMOTE and never the silver derivation. The mpob.json precedent
    (text inside BRONZE) would cost the derivation itself."""
    silver = [p for p in desc["phases"] if p["name"] == "silver"]
    assert len(silver) == 1
    tasks = silver[0]["tasks"]
    assert str(tasks[-1]["command"][0]).endswith("wasde_text_task.py")
    assert tasks[-1]["id"] == "wasde_text"
    assert any(t.get("publish_mode") == "shadow_canonical" for t in tasks[:-1]), \
        "the publishing silver task must come BEFORE the text leg"


def test_there_is_no_text_PHASE_because_the_renderer_would_drop_it(desc, lint) -> None:
    """`render_input` buckets fetch/bronze/silver/gold and nothing else. A `text` phase fails the
    lint AND is silently absent from the rendered input -- the worse half, because a lint can be
    read and a silent drop cannot."""
    assert {p["name"] for p in desc["phases"]} <= {"fetch", "bronze", "silver", "gold"}
    bad = dict(desc)
    bad["phases"] = list(desc["phases"]) + [{"name": "text", "tasks": []}]
    assert any("unknown phase name" in e for e in lint.lint_descriptor(bad, "wasde_monthly"))
    assert "text" not in lint.render_input(bad)["phases"]


def test_the_descriptor_still_lints_clean_and_the_text_task_survives_the_render(desc, lint) -> None:
    assert lint.lint_descriptor(desc, "wasde_monthly") == []
    rendered = lint.render_input(desc)
    cmds = [t["command"] for t in rendered["phases"]["silver"]["tasks"]]
    assert ["jobs/batch/wasde_text_task.py", "--era", "all"] in cmds, cmds
    # A non-publishing task never takes --publish-mode and never enters the promote leg.
    assert all("--publish-mode" not in c for c in cmds if c[0].endswith("wasde_text_task.py"))
    assert all(not t["command"][0].endswith("wasde_text_task.py")
               for t in rendered["promote"]["tasks"])


def test_every_flag_in_the_scheduled_command_is_one_the_script_declares(desc) -> None:
    """THE IMAGE-GATE CLASS, pinned. A baked argparse exits 2 on an unknown flag and that is
    TERMINAL after one attempt, so a descriptor may only carry options the image's own parser
    already knows. This command carries only `--era`, declared since the file was written, which is
    why it needs no repin of leviathan-dev-text-to-graphrag to land."""
    declared: set[str] = set()
    for node in ast.walk(ast.parse(_TASK.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_argument":
            for a in node.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                        and a.value.startswith("--"):
                    declared.add(a.value)
    cmd = _text_task(desc)["command"]
    used = {tok for tok in cmd if isinstance(tok, str) and tok.startswith("--")}
    assert used and used <= declared, sorted(used - declared)


# ---------------------------------------------------------------------------
# 3 -- the correction-freeze fence
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


class _FakeS3:
    """head_object over a {key: LastModified} map; a missing key 404s like the real client."""

    def __init__(self, mtimes: dict, *, deny: set | None = None):
        self.mtimes = dict(mtimes)
        self.deny = set(deny or ())
        self.heads: list[str] = []

    def head_object(self, Bucket, Key):                        # noqa: N803 -- boto3 kwarg casing
        self.heads.append(Key)
        if Key in self.deny:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}},
                              "HeadObject")
        if Key not in self.mtimes:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        return {"LastModified": self.mtimes[Key], "ContentLength": 1}


RAW = "raw/production/source=usda_wasde/release_date=2026-09-11/wasde0926.pdf"
TXT = "text/source=usda_wasde/release_date=2026-09-11/document.json"

# THREE MORE IN-SCOPE RELEASES, so a fire can have a failure AND a survivor. Round 3's bound turns
# on exactly that distinction and round 2's deck could not express it: every tolerance test drove
# main() over ONE key, which is now the all-failed edge rather than the tolerated one.
RAW2 = "raw/production/source=usda_wasde/release_date=2026-08-12/wasde0826.pdf"
TXT2 = "text/source=usda_wasde/release_date=2026-08-12/document.json"
RAW3 = "raw/production/source=usda_wasde/release_date=2026-07-11/wasde0726.pdf"
TXT3 = "text/source=usda_wasde/release_date=2026-07-11/document.json"
RAW4 = "raw/production/source=usda_wasde/release_date=2026-06-11/wasde0626.pdf"
TXT4 = "text/source=usda_wasde/release_date=2026-06-11/document.json"


def test_a_document_newer_than_its_raw_is_current_and_is_skipped(task) -> None:
    s3 = _FakeS3({RAW: _NOW - timedelta(days=11), TXT: _NOW - timedelta(days=1)})
    assert task.text_is_current(s3, "b", RAW, TXT) is True


def test_a_RE_FETCHED_raw_makes_the_document_STALE_and_it_is_re_extracted(task) -> None:
    """THE MPOB FREEZE CLASS, closed. USDA re-issues a corrected WASDE under the SAME release_date
    and `fetch_usda_wasde.py --skip-existing-s3` is source_url-aware, so the correction OVERWRITES
    the raw key; 626 raw objects across 626 distinct release_date partitions on 2026-09-22 prove
    there is no second key to notice. Under existence-only idempotency that correction was invisible
    forever and the text layer served the superseded edition."""
    s3 = _FakeS3({RAW: _NOW - timedelta(hours=1), TXT: _NOW - timedelta(days=30)})
    assert task.text_is_current(s3, "b", RAW, TXT) is False


def test_no_document_is_not_current(task) -> None:
    s3 = _FakeS3({RAW: _NOW})
    assert task.text_is_current(s3, "b", RAW, TXT) is False


def test_a_raw_that_cannot_be_HEADED_fails_CLOSED_into_re_extraction(task) -> None:
    """Not-current is the branch that does WORK. A raw object that has vanished (a re-partition, a
    lifecycle rule) must never be read as 'the document is fine'."""
    s3 = _FakeS3({TXT: _NOW})
    assert task.text_is_current(s3, "b", RAW, TXT) is False


def test_a_DENIAL_is_raised_and_never_read_as_absent(task) -> None:
    """A throttle or an AccessDenied is not a 404. Swallowing it would turn one IAM regression into
    a silent full re-extraction of the archive, or -- on the text head -- into a silent skip."""
    s3 = _FakeS3({RAW: _NOW, TXT: _NOW}, deny={TXT})
    with pytest.raises(ClientError):
        task.text_is_current(s3, "b", RAW, TXT)


def _stub_process(task, monkeypatch, s3, *, written: list):
    monkeypatch.setattr(task, "get_thread_local_s3_client", lambda region: s3)
    monkeypatch.setattr(task, "s3_download_with_retry", lambda b, k, c: b"%PDF-1.4")
    monkeypatch.setattr(task, "extract_wasde_digital", lambda body, key: {"full_text": "x"})
    monkeypatch.setattr(task, "extract_wasde_txt", lambda body, key: {"full_text": "x"})
    monkeypatch.setattr(task, "write_document",
                        lambda c, b, k, d: written.append(k))


def test_process_one_skips_a_current_document_and_downloads_NOTHING(task, monkeypatch) -> None:
    written: list = []
    s3 = _FakeS3({RAW: _NOW - timedelta(days=11), TXT: _NOW})
    _stub_process(task, monkeypatch, s3, written=written)
    monkeypatch.setattr(task, "s3_download_with_retry",
                        lambda *a, **k: pytest.fail("a skipped release must not be downloaded"))
    status, key = task._process_one(raw_key=RAW, era="digital", bucket="b",
                                    aws_region="us-east-1", force_overwrite=False)
    assert (status, key) == ("skipped", TXT)
    assert written == []


def test_process_one_rewrites_a_document_whose_raw_moved(task, monkeypatch) -> None:
    written: list = []
    s3 = _FakeS3({RAW: _NOW, TXT: _NOW - timedelta(days=30)})
    _stub_process(task, monkeypatch, s3, written=written)
    status, key = task._process_one(raw_key=RAW, era="digital", bucket="b",
                                    aws_region="us-east-1", force_overwrite=False)
    assert (status, key) == ("written", TXT)
    assert written == [TXT]


def test_force_overwrite_still_bypasses_the_check_entirely(task, monkeypatch) -> None:
    """The operator's flag keeps its meaning, and it does so without a single head_object: a forced
    run has already decided."""
    written: list = []
    s3 = _FakeS3({RAW: _NOW - timedelta(days=11), TXT: _NOW})
    _stub_process(task, monkeypatch, s3, written=written)
    status, _key = task._process_one(raw_key=RAW, era="digital", bucket="b",
                                     aws_region="us-east-1", force_overwrite=True)
    assert status == "written"
    assert s3.heads == []


def test_the_scanned_era_is_still_out_of_scope_so_textract_documents_are_never_clobbered(
        task) -> None:
    """`--era all` means all NON-Textract. The 251 scanned 1973-1994 raws were re-fetched in place
    on 2026-08-13 and are exactly the population a naive 'raw is newer' sweep would re-extract with
    a parser that cannot read them -- `_classify_key` keeps them out, as it always did."""
    assert task._classify_key(
        "raw/production/source=usda_wasde/release_date=1993-01-12/wasde0193.pdf") is None
    assert task._classify_key(
        "raw/production/source=usda_wasde/release_date=1997-01-10/wasde0197.txt") == "txt"
    assert task._classify_key(RAW) == "digital"


# ---------------------------------------------------------------------------
# 4 (ROUND 2) -- THE BLAST RADIUS: a text failure must never withhold the month's
#                CANONICAL WASDE publish, and it must never be swallowed either.
# ---------------------------------------------------------------------------

def test_there_is_NO_descriptor_phase_after_promote_which_is_why_the_exit_code_moved(
        desc, lint) -> None:
    """THE MEASUREMENT THAT FORCES THE FALLBACK, taken from the generator and the machine rather
    than argued. The ruling was "move it to a phase that runs AFTER promote; if only fail-fast
    phases exist, make the task tolerant by its own exit code". Both halves say no such phase
    exists: `lint_descriptor` rejects every name outside fetch/bronze/silver/gold, `render_input`
    folds a `gold` phase INTO the silver Map (there is no Gold Map), and the machine's one
    post-promote state is `Reconcile`, a FIXED task whose command is generated from
    `$.gate_baseline_uri` -- no descriptor phase follows the promote for any of the 28 families."""
    for name in ("promote", "reconcile", "text", "post_promote"):
        bad = dict(desc)
        bad["phases"] = list(desc["phases"]) + [{"name": name, "tasks": []}]
        assert any("unknown phase name" in e for e in lint.lint_descriptor(bad, "wasde_monthly"))
    gold = dict(desc)
    gold["phases"] = list(desc["phases"]) + [
        {"name": "gold", "tasks": [{"id": "x", "invocation_form": "s", "integration": "batch",
                                    "jobdef": "j", "queue": "q", "command": ["a.py"], "env": {},
                                    "publishes": False}]}]
    rendered = lint.render_input(gold)
    assert "gold" not in rendered["phases"], "a gold phase does not get its own Map"
    assert rendered["phases"]["silver"]["tasks"][-1]["command"] == ["a.py"], \
        "it is APPENDED TO SILVER -- i.e. still inside the fail-fast phase, before promote"
    sfn = (_REPO / "infra" / "terraform" / "modules" / "step_functions" / "main.tf").read_text(
        encoding="utf-8")
    assert 'Next           = "Reconcile"' in sfn and "jobs.audit.advance_rolling_census" in sfn
    assert "Bronze, Silver and Promote stay FAIL-FAST" in sfn


def test_only_the_FETCH_map_catches_a_failed_leg_so_a_SILVER_exit_1_BLOCKS_canonical(
        desc, lint) -> None:
    """THE PLACEMENT EDGE, pinned from the machine rather than asserted in a report (round 3).

    The round-3 ruling reads "that exit reaches the DAG as a failed post-promote leg, never as a
    blocked canonical". MEASURED, IT DOES NOT, and the lane says so instead of pretending: the
    per-item Catch that turns a failed leg into a RECORDED result rather than a thrown Map exists
    in the FETCH processor ALONE -- `phase == "Fetch" ? local.fetch_only_batch_overrides : []` --
    so a non-zero exit from this task raises States.TaskFailed out of the Silver Map and [Gate] and
    [Promote] are never entered. That is deliberate and it is the estate's own rule for the class
    that crosses the bound (the fetch phase's InfraFailNotify: "that is NOT a blocked source, so it
    was NOT tolerated ... canonical was never touched"). What the DOCUMENT class costs the month's
    numbers is still nothing.

    This deck exists so a later hand that moves the task into the FETCH phase to get the tolerant
    Catch has to come here first: that move would make the machine's own DegradedNotify text
    ("with ONE measured exception, weather_daily task chirps_to_bronze") FALSE, and that file is
    not this lane's to edit."""
    sfn = (_REPO / "infra" / "terraform" / "modules" / "step_functions" / "main.tf").read_text(
        encoding="utf-8")
    assert 'phase == "Fetch" ? local.fetch_only_batch_overrides : []' in sfn, \
        "the two-arm per-item Catch is FETCH-ONLY; if that ever changes, re-read this whole ruling"
    assert 'ItemsPath      = "$.phases.silver.tasks"' in sfn
    assert "with ONE measured exception, weather_daily task chirps_to_bronze" in sfn, \
        "the notifier names exactly one non-fetch leg in the fetch phase -- do not make it lie"
    # and the descriptor still puts the text task in SILVER, never in the tolerant FETCH map
    placed = [p["name"] for p in desc["phases"]
              for t in p["tasks"] if t is _text_task(desc) or t.get("id") == "wasde_text"]
    assert placed == ["silver"], f"text leg must stay in the silver phase, found {placed}"
    rendered = lint.render_input(desc)
    assert all(not str(t["command"][0]).endswith("wasde_text_task.py")
               for t in rendered["phases"]["fetch"]["tasks"])


def test_a_document_level_failure_does_NOT_fail_the_run(task, monkeypatch) -> None:
    """THE PIN THAT FAILS ON HEAD AND ON ROUND 1 (`if counts["error"]: sys.exit(1)`). One
    unreadable PDF out of 375 would have withheld the month's canonical publish on all six fires of
    the 8th-13th window, because Bronze/Silver/Promote are fail-fast and the jobdef's
    evaluateOnExit makes exit 1 terminal after one attempt.

    THE LOWER EDGE OF THE BOUND (round 3). One failure AMONG OTHERS THAT DID NOT FAIL is the
    DOCUMENT class and still exits 0. The fire that is ONE document and that one failed is the
    other edge and lives in the all-failed test below -- it is not a document class, it is a fire
    with nothing left standing."""
    rc = _run_main(task, monkeypatch, outcomes={RAW: RuntimeError("layout changed"),
                                                RAW2: ("skipped", TXT2),
                                                RAW3: ("written", TXT3)})
    assert rc == 0


def test_a_SKIP_PATH_ClientError_is_INFRA_and_fails_the_leg_ALONE(task, monkeypatch) -> None:
    """ROW A OF THE REVIEWER'S PROBE, FLIPPED (census B-R3-2 / MAJOR-R3-1).

    Round 3 bounded the tolerance with a COUNT, and a count cannot see a class: the reviewer drove
    the REAL `_process_one` against a stub S3 that throttles `head_object` and measured
    `rc=0 errors=1` -- ONE pure-infra fault TOLERATED, which the lane's own doctrine sentence says
    the estate tolerates nowhere. `_last_modified` raises a non-404 ClientError BY DESIGN, so that
    class arrives here as a ClientError and is now read off the EXCEPTION: any number of them,
    including one, fails the leg. The fire must RE-RUN, and the family fires again tomorrow inside
    the 8th-13th window.

    AND THE TWO CLASSES ARE COUNTED APART, which is the same finding stated as an instrument: the
    infra fault must not land on the counter whose alarm is the DOCUMENT class's only detector."""
    seen: list = []
    rc = _run_main(task, monkeypatch, puts=seen, outcomes={
        RAW: ClientError({"Error": {"Code": "SlowDown", "Message": "slow"}}, "HeadObject"),
        RAW2: ("skipped", TXT2),
        RAW3: ("written", TXT3),
    })
    assert rc == 1, "one skip-path throttle is INFRA and is never tolerated"
    by = _datums(seen, task)
    assert by[task.METRIC_INFRA] == 1.0
    assert by[task.METRIC_ERRORS] == 0.0, "an infra fault must never be counted as a document"
    assert by[task.METRIC_RUNS] == 1.0


def test_a_TIMEOUT_is_the_same_INFRA_class_even_though_it_is_not_a_ClientError(
    task, monkeypatch,
) -> None:
    """A read timeout arrives as `BotoCoreError`, not `ClientError`. Classifying on one of the two
    would tolerate the other, which is the same defect in a second spelling."""
    from botocore.exceptions import ConnectTimeoutError
    rc = _run_main(task, monkeypatch, outcomes={
        RAW: ConnectTimeoutError(endpoint_url="https://s3.amazonaws.com"),
        RAW2: ("skipped", TXT2),
    })
    assert rc == 1
    assert isinstance(ConnectTimeoutError(endpoint_url="x"), task.BotoCoreError)


def test_TWO_UNREADABLE_PDFs_are_still_the_DOCUMENT_class(task, monkeypatch) -> None:
    """ROW C OF THE REVIEWER'S PROBE, FLIPPED. Round 3 exited 1 on two unreadable PDFs out of 375
    -- `States.TaskFailed` out of the silver Map, [Gate] and [Promote] never entered, THE MONTH'S
    CANONICAL WASDE NOT PUBLISHED -- on the reasoning that a second simultaneous failure "cannot be
    a second bad PDF". It can: a layout change is the one defect that breaks every new release
    identically, and the tolerance itself fills the backlog it needs to be empty.

    Two documents are two documents. They are tolerated, counted, named -- and RECORDED, so this is
    the last fire on which they are new."""
    seen: list = []
    marks: list = []
    rc = _run_main(task, monkeypatch, puts=seen, markers=marks, outcomes={
        RAW: RuntimeError("layout changed"), RAW2: ValueError("layout changed"),
        RAW3: ("skipped", TXT3), RAW4: ("skipped", TXT4)})
    assert rc == 0, "the DOCUMENT class must never withhold the month's canonical numbers"
    by = _datums(seen, task)
    assert by[task.METRIC_ERRORS] == 2.0 and by[task.METRIC_INFRA] == 0.0
    assert sorted(m["Key"] for m in marks) == sorted([
        task.failure_marker_key("2026-09-11"), task.failure_marker_key("2026-08-12")])


def test_an_ALL_FAILED_leg_still_FAILS_because_NOTHING_IS_LEFT_STANDING(task, monkeypatch) -> None:
    """MAJOR-R2-1, THE UPPER EDGE, KEPT. Round 2's tolerance was UNBOUNDED: three of three in-scope
    documents failing returned 0 with `WasdeTextErrors=3` -- raw present, text frozen, nothing red,
    verbatim the state this lane was opened for.

    The estate's own tolerant phase does not do that (`AnyFetchLegFailed` tolerates a failed leg
    only while ANOTHER leg succeeded), and neither does this one. Round 4 only renames the reason:
    it is not "an INFRA class wearing document clothes" -- the infra class is now read off the
    exception -- it is that nothing was left standing."""
    seen: list = []
    rc = _run_main(task, monkeypatch, puts=seen, outcomes={
        RAW: RuntimeError("bad pdf"),
        RAW2: RuntimeError("bad pdf"),
        RAW3: RuntimeError("bad pdf"),
    })
    assert rc == 1
    # AND THE DATUM STILL EXISTS. A red fire that emitted nothing would make CloudWatch and the
    # execution history disagree about the same fire.
    by = _datums(seen, task)
    assert by[task.METRIC_ERRORS] == 3.0 and by[task.METRIC_RUNS] == 1.0


def test_a_ONE_DOCUMENT_fire_that_failed_is_ALSO_all_failed(task, monkeypatch) -> None:
    """A fire whose whole scope is one release -- the steady state once the tip is current, where
    `text_is_current` selects 1 of 375 -- must not pass as "a tolerated document error" when that
    one document IS the entire fire."""
    assert _run_main(task, monkeypatch, outcomes={RAW: RuntimeError("boom")}) == 1


def test_that_red_fires_ONCE_and_the_RECORD_retires_it(task, monkeypatch) -> None:
    """THE MONTH-2 TRAP, CLOSED (census B-R3-2). `text_is_current` returns False while no document
    exists, so a failed release is re-attempted forever; under round 3 the September failure came
    back in October as a SECOND error and withheld October's canonical on all six fires of the
    window, and every month after.

    Fire 1: the release fails, nothing is left standing, rc 1 -- and the failure is RECORDED.
    Fire 2: the same release fails the same way, it is KNOWN, it is excluded from the "nothing left
    standing" denominator, rc 0, canonical publishes. The blast radius of a permanently unparseable
    release is ONE fire of six, not every fire forever."""
    marks: list = []
    assert _run_main(task, monkeypatch, markers=marks,
                     outcomes={RAW: RuntimeError("layout changed")}) == 1
    assert [m["Key"] for m in marks] == [task.failure_marker_key("2026-09-11")]

    seen: list = []
    rc = _run_main(task, monkeypatch, puts=seen, known=("2026-09-11",),
                   outcomes={RAW: RuntimeError("layout changed")})
    assert rc == 0, "a KNOWN failure must never withhold the month's canonical a second time"
    by = _datums(seen, task)
    assert by[task.METRIC_ERRORS] == 0.0, "a known failure is not a NEW one; the alarm must clear"
    assert by[task.METRIC_KNOWN] == 1.0, "and it is never dark: the backlog has its own gauge"


def test_a_KNOWN_backlog_beside_a_LIVE_release_does_not_shrink_the_denominator_dishonestly(
    task, monkeypatch,
) -> None:
    """The known set is subtracted from the work, not from the truth: a fire holding one known-bad
    release and one live release that SUCCEEDS is green with the backlog still counted."""
    seen: list = []
    rc = _run_main(task, monkeypatch, puts=seen, known=("2026-09-11",), outcomes={
        RAW: RuntimeError("layout changed"), RAW2: ("written", TXT2)})
    assert rc == 0
    by = _datums(seen, task)
    assert by[task.METRIC_KNOWN] == 1.0 and by[task.METRIC_WRITTEN] == 1.0
    assert by[task.METRIC_ERRORS] == 0.0


def test_the_marker_is_the_RECORD_and_it_names_the_release_the_class_and_the_error(
    task, monkeypatch,
) -> None:
    """What "recorded" means, in bytes. The key is one object per release (a repeat overwrites it,
    so the backlog's size is the number of broken releases, never the number of fires) and the body
    names the release, the raw key, the exception class and the message."""
    marks: list = []
    _run_main(task, monkeypatch, markers=marks,
              outcomes={RAW: ValueError("page 3 has no table"), RAW2: ("skipped", TXT2)})
    assert len(marks) == 1
    assert marks[0]["Key"] == (
        "text_extraction_failures/source=usda_wasde/release_date=2026-09-11/extraction_failure.json")
    body = json.loads(marks[0]["Body"].decode("utf-8"))
    assert body["release_date"] == "2026-09-11" and body["class"] == "DOCUMENT"
    assert body["error_class"] == "ValueError" and "page 3" in body["error"]
    assert body["raw_key"] == RAW


def test_a_failure_the_fire_could_NOT_record_stays_NEW_so_it_keeps_PAGING(
    task, monkeypatch,
) -> None:
    """A failed RECORD never fails the leg -- that would hand the text layer back the blast radius
    this change removes -- and it is not a swallow either: the release is not retired, so the next
    fire counts it NEW again and the error alarm pages again, every fire, until a human acts. The
    un-retired case is the LOUD one."""
    seen: list = []
    rc = _run_main(task, monkeypatch, puts=seen,
                   marker_raises=ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}},
                                             "PutObject"),
                   outcomes={RAW: RuntimeError("bad pdf"), RAW2: ("skipped", TXT2)})
    assert rc == 0
    assert _datums(seen, task)[task.METRIC_ERRORS] == 1.0


def test_an_UNREADABLE_BACKLOG_counts_every_failure_NEW_so_the_alarm_PAGES(
    task, monkeypatch,
) -> None:
    """The backlog reader fails LOUD, never quiet. If the list raises, the empty set is the answer
    that PAGES (everything is new); "assume they are all known" would silence the alarm on the fire
    whose own instrument just broke."""
    seen: list = []
    rc = _run_main(task, monkeypatch, puts=seen, known=("2026-09-11",),
                   list_raises=ClientError({"Error": {"Code": "SlowDown", "Message": "s"}},
                                           "ListObjectsV2"),
                   outcomes={RAW: RuntimeError("bad pdf"), RAW2: ("skipped", TXT2)})
    assert rc == 0
    assert _datums(seen, task)[task.METRIC_ERRORS] == 1.0
    assert _datums(seen, task)[task.METRIC_KNOWN] == 0.0


def test_the_backlog_reader_NAMES_ITS_OWN_OBJECT_SET(task, monkeypatch) -> None:
    """The same narrowing round 3 gave the fold's `newest_manifest_since`: a key that does not begin
    with the failure prefix is dropped even though the LIST was asked for that prefix. A raw key
    parses a release_date perfectly well, so a reader that trusted the filter it did not apply
    itself would read 375 raw objects as 375 retired failures -- and then nothing is ever NEW."""
    monkeypatch.setattr(task, "list_s3_keys",
                        lambda bucket, prefix, *a, **k: [RAW, RAW2,
                                                         task.failure_marker_key("2026-09-11")])
    assert task.known_failed_releases("b", "us-east-1") == {"2026-09-11"}


def test_an_era_all_fire_with_ZERO_in_scope_work_is_a_FAULT_not_a_quiet_month(
    task, monkeypatch,
) -> None:
    """MINOR-R3-1. The scheduled command is `--era all` with no `--limit`, and `--era all` has 375
    in-scope objects today, so a zero-length work list there is a listing / prefix / bucket /
    credential fault reported as a perfectly healthy fire. A quiet fire is still real for
    `--era txt` and for a `--limit` run."""
    assert _run_main(task, monkeypatch, outcomes={}) == 1
    assert task.tolerance_verdict(0, 0, era="txt") == (0, "")
    assert task.tolerance_verdict(0, 0, era="all", limit=5) == (0, "")
    assert "BLIND" in task.tolerance_verdict(0, 0)[1]


def test_the_verdict_reads_a_CLASS_and_the_alarms_number_is_spelled_ONCE(task) -> None:
    """The pure verdict function, every arm, with no main() and no stubs at all.

    ROUND 3'S `MAX_TOLERATED_DOC_FAILURES` IS RETIRED, DELIBERATELY AND BY NAME: the exit code no
    longer reds on a COUNT of document errors, so a constant called "max tolerated" would mean
    nothing here and something else in lane 7's alarm. What lane 7 spends now is
    `WASDE_TEXT_ERROR_ALARM_THRESHOLD` -- ZERO, because the exit code tolerates the document class
    outright and the alarm is its only same-fire detector, so it must speak at the FIRST new
    failure."""
    assert task.WASDE_TEXT_ERROR_ALARM_THRESHOLD == 0
    assert not hasattr(task, "MAX_TOLERATED_DOC_FAILURES"), \
        "round 3's count-shaped bound is retired; a number that means two things is a drift"
    # the DOCUMENT class: tolerated, at one and at two, beside survivors
    assert task.tolerance_verdict(0, 375) == (0, "")
    assert task.tolerance_verdict(1, 375)[0] == 0
    assert task.tolerance_verdict(2, 375)[0] == 0        # row C of the probe
    # the INFRA class: never tolerated, not even one, whatever the document count is
    assert task.tolerance_verdict(0, 375, n_infra=1)[0] == 1      # row A of the probe
    assert "infra" in task.tolerance_verdict(0, 375, n_infra=1)[1].lower()
    # nothing left standing
    assert task.tolerance_verdict(375, 375)[0] == 1
    assert task.tolerance_verdict(1, 1)[0] == 1
    # ... and the known backlog is out of that denominator, so it never re-blocks
    assert task.tolerance_verdict(0, 1, n_known=1) == (0, "")
    assert task.tolerance_verdict(1, 2, n_known=1)[0] == 1
    assert task.tolerance_verdict(0, 2, n_known=2) == (0, "")


def test_the_failure_is_COUNTED_and_NAMED_never_swallowed(task, monkeypatch, capsys) -> None:
    """Tolerant is not silent. Every failed key is logged, the tally is printed, and the count
    rides a metric an alarm can read -- the fence CORRECTS the blast radius, it does not delete the
    finding."""
    seen: list = []
    rc = _run_main(task, monkeypatch, puts=seen,
                   outcomes={RAW: RuntimeError("boom"), RAW2: ("skipped", TXT2)})
    assert rc == 0
    assert len(seen) == 1
    by = {d["MetricName"]: d["Value"] for d in seen[0]["MetricData"]}
    assert by[task.METRIC_ERRORS] == 1.0
    assert by[task.METRIC_RUNS] == 1.0
    assert seen[0]["Namespace"] == task.METRIC_NAMESPACE


def test_strict_exit_restores_the_old_behaviour_for_a_HAND_run_only(task, monkeypatch) -> None:
    assert _run_main(task, monkeypatch, argv=["--strict-exit"],
                     outcomes={RAW: RuntimeError("boom"), RAW2: ("skipped", TXT2)}) == 1
    assert _run_main(task, monkeypatch, outcomes={RAW: ("written", TXT)}, argv=["--strict-exit"]) == 0
    assert task.tolerance_verdict(1, 375, strict_exit=True)[0] == 1


def test_the_scheduled_command_does_NOT_carry_strict_exit(desc) -> None:
    """The flag exists for a hand run. In the chain it would re-arm the exact blast radius this
    change removed, so the descriptor may never carry it."""
    assert "--strict-exit" not in _text_task(desc)["command"]


def test_a_clean_run_still_reports_so_silence_only_ever_means_NO_FIRE(task, monkeypatch) -> None:
    """`WasdeTextDocsWritten == 0` is the NORMAL steady state once the tip is current -- the month's
    document is already newer than its raw. That is why the alarm handed to lane 7 is on ERRORS and
    never on a zero write count."""
    seen: list = []
    rc = _run_main(task, monkeypatch, outcomes={RAW: ("skipped", TXT)}, puts=seen)
    assert rc == 0
    by = {d["MetricName"]: d["Value"] for d in seen[0]["MetricData"]}
    assert by[task.METRIC_RUNS] == 1.0 and by[task.METRIC_WRITTEN] == 0.0
    assert by[task.METRIC_ERRORS] == 0.0


def test_a_failed_PUT_does_not_fail_the_leg(task, monkeypatch) -> None:
    """An instrument must never become a new way for the text leg to cost the month's numbers."""
    assert _run_main(task, monkeypatch, outcomes={RAW: ("written", TXT)},
                     put_raises=RuntimeError("throttled")) == 0


def test_the_datums_are_the_estates_own_namespace_and_one_constant_dimension(task) -> None:
    from leviathan.graphrag import corpus_coverage as cc
    assert task.METRIC_NAMESPACE == cc.METRIC_NAMESPACE == "Leviathan/Silver"
    datums = task.metric_datums({"written": 1, "skipped": 374, "error": 0})
    assert [d["MetricName"] for d in datums] == list(task.METRIC_NAMES)
    assert all(d["Dimensions"] == [{"Name": "Family", "Value": "usda_wasde"}] for d in datums)
    assert all(d["Unit"] == "Count" for d in datums)


def _run_main(task, monkeypatch, *, outcomes: dict, argv=None, puts=None, put_raises=None,
              known=(), markers=None, marker_raises=None, list_raises=None):
    """Drive main() over the in-scope raw keys with a stubbed worker, a stubbed LIST and a stubbed
    CloudWatch. No S3, no network, no extraction.

    ROUND 4 ADDS THE BACKLOG SEAM, and it is a REAL one: `known` is turned into the marker keys the
    task's own `failure_marker_key` mints, the LIST is answered PER PREFIX (raw keys for the raw
    prefix, markers for the failure prefix), and `record_document_failure` runs for real against a
    stub client whose `put_object` records what it was asked to write. So the key shape, the
    prefix narrowing and the record are exercised rather than mocked away."""
    marker_keys = [task.failure_marker_key(r) for r in known]

    def _list(bucket, prefix, *a, **k):
        if prefix == task._FAILURE_PREFIX:
            if list_raises:
                raise list_raises
            return list(marker_keys)
        return list(outcomes)

    monkeypatch.setattr(task, "list_s3_keys", _list)

    def _one(raw_key, era, bucket, aws_region, force_overwrite):
        r = outcomes[raw_key]
        if isinstance(r, BaseException):
            raise r
        return r

    monkeypatch.setattr(task, "_process_one", _one)

    class _S3:
        def put_object(self, **kw):                            # noqa: N803 -- boto3 kwarg casing
            if marker_raises:
                raise marker_raises
            if markers is not None:
                markers.append(kw)

    monkeypatch.setattr(task, "get_thread_local_s3_client", lambda region: _S3())

    class _CW:
        def put_metric_data(self, **kw):
            if put_raises:
                raise put_raises
            if puts is not None:
                puts.append(kw)

    import boto3
    monkeypatch.setattr(boto3, "client", lambda service, **kw: _CW())
    monkeypatch.setattr(sys, "argv", ["wasde_text_task.py", *(argv or [])])
    return task.main()


def _datums(puts: list, task) -> dict:
    return {d["MetricName"]: d["Value"] for d in puts[0]["MetricData"]}
