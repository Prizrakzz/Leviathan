"""D-PR-28 / D-SG G3-4: the gate's verdict metric, and the promise that it can never cost a verdict.

Two things are asserted here and they pull in opposite directions.

  * The metric must be COMPLETE where a verdict exists. `PASS_WITH_DRIFT` is exit 0 by design
    (D-PR-5), so before this emitter a PASS that rode over another family's drift left one stdout
    line inside one of 26 daily Batch containers and reached nobody. Same for
    ``ValueCensusHardFailTables``, whose P1 alarm has been live and hollow since the F082 apply.
  * The metric must be INERT where no verdict exists, and it must never change an exit code. It is
    emitted from a ``finally`` in ``main()``, which is the one place in the gate that sees every
    path -- and a ``finally`` that raises would rewrite the verdict the whole file exists to
    protect. So the exit-code matrix is run twice, once with a healthy emitter and once with a
    CloudWatch that fails, and the two lists must be identical.

AWS-free: ``_emit_gate_metrics`` imports boto3 inside the function, so a stub client is all it takes.
"""
from __future__ import annotations

import pytest

from jobs.audit import silver_rebuild_gate as g


class _StubCloudWatch:
    """Records put_metric_data calls; optionally fails like a throttled/denied CloudWatch."""

    def __init__(self, raises: bool = False):
        self.calls: list[dict] = []
        self.raises = raises

    def put_metric_data(self, **kwargs):
        if self.raises:
            raise RuntimeError("AccessDenied: cloudwatch:PutMetricData")
        self.calls.append(kwargs)


@pytest.fixture()
def cw(monkeypatch):
    import boto3
    stub = _StubCloudWatch()
    monkeypatch.setattr(boto3, "client", lambda name, *a, **k: stub)
    return stub


def _stage(name: str, status: str) -> dict:
    return {"name": name, "status": status, "detail": f"{name}={status}"}


def _bundle(verdict: str, *, global_drift: int = 0, census_red_tables: int = 0) -> dict:
    results = []
    for i in range(max(census_red_tables, 1)):
        red = i < census_red_tables
        results.append({
            "table": f"silver_t{i}", "branch": "B", "ok": not red,
            "stages": [_stage("value_census", g.RED if red else g.GREEN)],
        })
    return {"run_id": "r1", "verdict": verdict, "results": results,
            "banner": {"tables": len(results), "branch_a": 0, "branch_b": len(results),
                       "unknown": 0, "red_tables": census_red_tables,
                       "global_drift": global_drift, "warn_tables": 0}}


def _run(monkeypatch, tmp_path, bundle, tables="silver_cot"):
    monkeypatch.setattr(g, "_preflight_image_config", lambda tables, **k: {"ok": True})
    monkeypatch.setattr(g, "_build_live_context", lambda tables, **k: object())
    monkeypatch.setattr(g, "run_gate", lambda tables, ctx: bundle)
    return g.main(["--tables", tables, "--json", str(tmp_path / "b.json")])


# =========================================================================================================
# 1. THE VOCABULARY -- three verdicts, and the one the exit code cannot carry
# =========================================================================================================
@pytest.mark.parametrize("verdict,drift,want", [
    ("PASS", 0, "PASS"),
    ("PASS", 2, "PASS_WITH_DRIFT"),
    ("FAIL", 0, "FAIL"),
    ("FAIL", 3, "FAIL"),
])
def test_the_verdict_dimension_is_the_gates_own_three_words(monkeypatch, tmp_path, cw, verdict,
                                                            drift, want):
    """PASS_WITH_DRIFT is banner.global_drift > 0 on an otherwise-passing bundle. A FAIL stays FAIL
    however much drift it also carried -- the refusal is the headline, and it already pages."""
    _run(monkeypatch, tmp_path, _bundle(verdict, global_drift=drift))
    assert len(cw.calls) == 1
    verdicts = {d["Dimensions"][-1]["Value"] for d in cw.calls[0]["MetricData"]
                if d["MetricName"] == g.GATE_VERDICT_METRIC}
    assert verdicts == {want}


def test_yellow_is_not_a_word_the_gate_speaks():
    """The gate's banner has no YELLOW; naming the drift verdict after the banner keeps the metric
    readable against the thing it is derived from."""
    assert g.VERDICT_PASS_WITH_DRIFT == "PASS_WITH_DRIFT"
    assert "YELLOW" not in {g.VERDICT_PASS, g.VERDICT_PASS_WITH_DRIFT, g.VERDICT_FAIL}


def test_both_dimension_shapes_are_emitted_into_the_granted_namespace(monkeypatch, tmp_path, cw):
    """{Family,Verdict} for attribution and {Verdict} for the estate-wide alarm -- a CloudWatch alarm
    needs an exact dimension set, so the second datum is what keeps the alarm out of metric math. The
    namespace is load-bearing too: the role's PutMetricData grant is conditioned on it."""
    _run(monkeypatch, tmp_path, _bundle("PASS", global_drift=1))
    call = cw.calls[0]
    assert call["Namespace"] == "Leviathan/Silver"
    shapes = [tuple(d["Name"] for d in datum["Dimensions"]) for datum in call["MetricData"]
              if datum["MetricName"] == g.GATE_VERDICT_METRIC]
    assert sorted(shapes) == [("Family", "Verdict"), ("Verdict",)]


def test_the_family_dimension_is_derived_from_the_tables():
    """No renderer, descriptor or state-machine change: every rendered gate --tables list resolves to
    exactly one family. A run that spans families or maps to none is still emitted, labelled."""
    assert g._gate_family(["silver_cot"]) == "cftc"
    assert g._gate_family(["silver_esr", "silver_esr_compact"]) == "usda_esr"
    assert g._gate_family(["silver_cot", "silver_esr"]) == "mixed"
    assert g._gate_family(["not_a_table_at_all"]) == "unknown"
    assert g._gate_family([]) == "unknown"


# =========================================================================================================
# 2. THE HOLLOW P1 ALARM GETS ITS FIRST EMITTER
# =========================================================================================================
@pytest.mark.parametrize("red", [0, 1, 3])
def test_value_census_hard_fail_tables_is_a_count_of_tables(monkeypatch, tmp_path, cw, red):
    """leviathan-dev-value-census-regression (P1, threshold 0) has never had a publisher. The count is
    TABLES whose value_census stage came back RED, undimensioned to match the alarm."""
    _run(monkeypatch, tmp_path, _bundle("FAIL" if red else "PASS", census_red_tables=red))
    datums = [d for d in cw.calls[0]["MetricData"] if d["MetricName"] == g.CENSUS_HARDFAIL_METRIC]
    assert len(datums) == 1
    assert datums[0]["Value"] == float(red)
    assert datums[0]["Dimensions"] == []


# =========================================================================================================
# 3. THE NON-VERDICTS STAY SILENT (D-PR-8: 64 / 70 / 71 / 72 are faults, not decisions)
# =========================================================================================================
def _no_verdict_paths(monkeypatch):
    """(label, argv, want_rc) for every exit that is NOT a verdict, each with its stub installed."""
    from leviathan.common import image_stamp
    from leviathan.silver.registry import RegistryError

    cases = []

    def usage(_mp, tmp_path):
        return ([], g.EXIT_USAGE)

    def preflight(mp, tmp_path):
        mp.setattr(g, "_preflight_image_config", lambda tables, **k: {
            "ok": False, "reason": "image_predates_config", "lines": ["IMAGE IS STALE"],
            "red_tables": [(t, "stale") for t in tables], "image": image_stamp.image_facts()})
        return (["--tables", "silver_wasde", "--json", str(tmp_path / "p.json")], g.EXIT_PREFLIGHT)

    def bad_registry(mp, tmp_path):
        mp.setattr(g, "_preflight_image_config", lambda tables, **k: {"ok": True})

        def boom(tables, **k):
            raise RegistryError("silver_cot.yaml: schema: expected type ['string'], got int")

        mp.setattr(g, "_build_live_context", boom)
        return (["--tables", "silver_cot", "--json", str(tmp_path / "r.json")], g.EXIT_PREFLIGHT)

    def baseline(mp, tmp_path):
        mp.setattr(g, "_preflight_image_config", lambda tables, **k: {"ok": True})

        def boom(tables, **k):
            raise g.BaselineFetchError("baseline census fetch failed for s3://b/k: stubbed")

        mp.setattr(g, "_build_live_context", boom)
        return (["--tables", "silver_wasde"], g.EXIT_BASELINE_FETCH)

    def crash(mp, tmp_path):
        mp.setattr(g, "_preflight_image_config", lambda tables, **k: {"ok": True})

        def boom(tables, **k):
            raise ModuleNotFoundError("No module named 'psycopg'")

        mp.setattr(g, "_build_live_context", boom)
        return (["--tables", "silver_wasde"], g.EXIT_INTERNAL)

    for name, fn in [("usage", usage), ("preflight", preflight), ("bad_registry", bad_registry),
                     ("baseline_fetch", baseline), ("crash", crash)]:
        cases.append((name, fn))
    return cases


@pytest.mark.parametrize("name,build", _no_verdict_paths(None))
def test_a_path_that_produced_no_verdict_emits_nothing(monkeypatch, tmp_path, cw, name, build):
    """These four codes are faults in the gate's inputs or image, not decisions about data -- they
    already page via batch-job-failed-scheduled. Minting a verdict row for them would put INFRA into
    a metric whose only question is 'did the machinery judge, and how'."""
    argv, want = build(monkeypatch, tmp_path)
    assert g.main(argv) == want
    assert cw.calls == []


def test_a_second_run_does_not_inherit_the_first_runs_verdict(monkeypatch, tmp_path, cw):
    """_VERDICT_RECORD is module state. 'Empty means no verdict' has to hold per RUN, or a crash
    following a PASS in the same interpreter would publish the PASS again."""
    _run(monkeypatch, tmp_path, _bundle("PASS"))
    assert len(cw.calls) == 1

    def boom(tables, **k):
        raise ModuleNotFoundError("No module named 'psycopg'")

    monkeypatch.setattr(g, "_build_live_context", boom)
    assert g.main(["--tables", "silver_wasde"]) == g.EXIT_INTERNAL
    assert len(cw.calls) == 1  # unchanged: the crash published nothing


# =========================================================================================================
# 4. THE PIN: A METRIC OUTAGE IS NEVER A PROMOTE OUTAGE
# =========================================================================================================
def _exit_matrix(monkeypatch, tmp_path) -> list[tuple[str, int]]:
    """Every exit the gate can produce, in one list, so two runs can be compared element by element."""
    out: list[tuple[str, int]] = []
    for name, build in _no_verdict_paths(None):
        with monkeypatch.context() as mp:
            argv, _want = build(mp, tmp_path)
            out.append((name, g.main(argv)))
    for verdict, drift in [("PASS", 0), ("PASS", 2), ("FAIL", 0)]:
        with monkeypatch.context() as mp:
            rc = _run(mp, tmp_path, _bundle(verdict, global_drift=drift))
            out.append((f"{verdict}_drift{drift}", rc))
    return out


def test_a_cloudwatch_outage_changes_no_exit_code(monkeypatch, tmp_path):
    """THE POINT OF THE finally. Run the whole exit matrix against a healthy CloudWatch and against
    one that raises on every call; the two lists must be byte-identical. A verdict is a decision about
    data and cannot be allowed to depend on whether telemetry was reachable."""
    import boto3

    healthy = _StubCloudWatch()
    with monkeypatch.context() as mp:
        mp.setattr(boto3, "client", lambda name, *a, **k: healthy)
        good = _exit_matrix(mp, tmp_path)

    broken = _StubCloudWatch(raises=True)
    with monkeypatch.context() as mp:
        mp.setattr(boto3, "client", lambda name, *a, **k: broken)
        bad = _exit_matrix(mp, tmp_path)

    assert good == bad
    assert healthy.calls and not broken.calls  # the healthy run really did emit


def test_the_emitter_swallows_its_own_failure_and_says_so(capsys):
    """One line, ASCII, naming the exception class -- and the verdict above it stands."""
    import boto3

    def boom(*a, **k):
        raise RuntimeError("AccessDenied: cloudwatch:PutMetricData")

    original = boto3.client
    boto3.client = boom
    try:
        g._emit_gate_metrics({"family": "cftc", "verdict": "PASS", "census_hard_fail": 0})
    finally:
        boto3.client = original
    out = capsys.readouterr().out
    assert "[metric] WARN" in out and "RuntimeError" in out
    assert "the verdict above stands" in out
    assert out.isascii()


def test_an_empty_record_is_a_no_op_and_touches_no_client(monkeypatch):
    """The empty-record short-circuit runs BEFORE the boto3 import, which is what makes every
    no-verdict path AWS-free rather than merely error-tolerant."""
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: pytest.fail("built a client for no verdict"))
    g._emit_gate_metrics({})
