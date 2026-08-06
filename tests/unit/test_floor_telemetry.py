"""F4a (latency RCA 2026-07-25): the deterministic floor is now LOUD -- and still byte-identical.

135 floor turns in 3 days (17.6% of all turns, p50 242.6s, each returning a 279-char service notice) were
invisible to every dashboard: the exception rode `trace.error` to the caller and nothing counted it. These
pins cover the three things F4a adds and the one thing it must NOT change:
  * a bounded `cause_class` slug per failure class, on a single ASCII line at the seam;
  * an EMF `FloorTurns=1` counter carrying that slug as a `cause` DIMENSION -- absent on healthy turns;
  * the same treatment on the LIVE-route seam, which logged nothing at all before;
  * the floor ANSWER payload, unchanged to the byte (this is observability only).
Mocked end to end: the reasoner is a fake that raises, retrieval is injected. No LLM/S3/AWS spend.
"""
from __future__ import annotations

import json

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch


def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(contract="arabica_coffee", aliases=["arabica"],
                               drivers=[cs.Driver(id="frost", type="hazard", sign="+",
                                                  mechanism="frost kills trees")])
    return g.CausalGraph({"arabica_coffee": coffee}, silver=set())


def _retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2024-01-01", "source": "usda_wasde", "source_key": f"s3://{node}",
             "text": "stocks note"}]


@pytest.fixture(autouse=True)
def _stub_floor_retrieval(monkeypatch):
    """The floor calls `evidence.retrieve` DIRECTLY (`an._RETRIEVAL`, never the caller's injected retrieve),
    which in a unit env would reach for pgvector / the bge model. Stub it so the floor is hermetic and it is
    the evidence-BEARING banner branch (the 8.1% of floor turns that DO retrieve) under test."""
    from leviathan.graphrag import evidence as ev
    monkeypatch.setattr(ev, "retrieve",
                        lambda q, node, **kw: [{"date": "2024-01-01", "source": "usda_wasde",
                                                "source_key": f"s3://{node}", "text": "stocks note"}])


# ── the live failure classes, as they arrive in the logs ─────────────────────────────────────────────
class QueryCanceled(Exception):
    """psycopg's type for a statement timeout (the 92 `canceling statement` events in 7d)."""


class OperationalError(Exception):
    """psycopg/SQLAlchemy connection-class failure (the 123 `OperationalError` events in 7d)."""


_HF_MSG = ("We couldn't connect to 'https://huggingface.co' to load the files, and couldn't find them "
           "in the cached files.")

_CASES = [
    (QueryCanceled("canceling statement due to statement timeout"), "pg_statement_timeout"),
    (OperationalError("canceling statement due to statement timeout"), "pg_statement_timeout"),
    (OperationalError("connection to server was lost"), "pg_operational"),
    (RuntimeError("pg numbers failed (psycopg.OperationalError: server closed the connection)"),
     "pg_operational"),
    (OSError(_HF_MSG), "model_download"),
    (RuntimeError("provider hard down"), "other"),
]
_IDS = ["querycanceled", "wrapped_timeout", "operational", "psycopg_in_message", "hf_download", "other"]


def _floor_turn(monkeypatch, exc: BaseException, *, kind: str = "reasoning") -> dict:
    """One real respond() turn whose reasoner raises `exc` -> the deterministic floor."""
    monkeypatch.setenv("GRAPHRAG_PLANNER", "onehop")   # floor is planner-agnostic; skip the L2 embed load

    def dead_call(system, user, *, model, tool):
        raise exc

    return orch.respond("arabica frost outlook", graph=_graph(), asof="2024-01-01", call=dead_call,
                        retrieve=_retrieve, classify=lambda q, call=None: {"intent": kind})


def _emf_lines(capsys) -> tuple[list[dict], str]:
    out = capsys.readouterr().out
    return [json.loads(ln) for ln in out.splitlines() if ln.startswith("{")], out


# ── (a) the structured log line + the cause slug ────────────────────────────────────────────────────
@pytest.mark.parametrize(("exc", "slug"), _CASES, ids=_IDS)
def test_floor_log_carries_bounded_cause_class(monkeypatch, capsys, exc, slug):
    res = _floor_turn(monkeypatch, exc)
    _, out = _emf_lines(capsys)
    line = next(ln for ln in out.splitlines() if ln.startswith("[floor]"))
    assert f"cause_class={slug}" in line
    assert slug in orch._FLOOR_CAUSES                                  # closed set: no minted values
    # APPEND-ONLY format: the pre-F4a fields the 137 [floor] log records were read with still parse
    assert line.startswith("[floor] kind=reasoning ")
    assert f"cause={type(exc).__name__}: " in line
    assert res["trace"]["floor_cause"] == slug
    assert res["trace"]["error"].startswith(f"{type(exc).__name__}: ")  # raw error kept exactly as before


def test_floor_log_is_one_ascii_line(monkeypatch, capsys):
    """A multi-line / non-ASCII driver message must not split the record or kill a cp1252 stdout."""
    _floor_turn(monkeypatch, OperationalError("connection lost\nCONTEXT:  whère\r\nDETAIL: x"))
    _, out = _emf_lines(capsys)
    lines = [ln for ln in out.splitlines() if "[floor]" in ln or "CONTEXT" in ln]
    assert len(lines) == 1
    assert lines[0].isascii() and "cause_class=pg_operational" in lines[0]


def test_floor_cause_classifier_is_total():
    """Every input maps into the closed set -- including a bare exception with an empty message."""
    assert orch._floor_cause(Exception()) == "other"
    for exc, slug in _CASES:
        assert orch._floor_cause(exc) == slug


# ── (b) the EMF counter, with cause as its own dimension ────────────────────────────────────────────
@pytest.mark.parametrize(("exc", "slug"), _CASES, ids=_IDS)
def test_floorturns_emits_once_per_class(monkeypatch, capsys, exc, slug):
    _floor_turn(monkeypatch, exc)
    docs, _ = _emf_lines(capsys)
    floors = [d for d in docs if "FloorTurns" in d]
    assert len(floors) == 1 and floors[0]["FloorTurns"] == 1
    assert floors[0]["cause"] == slug and floors[0]["intent"] == "reasoning"
    names = {m["Name"] for m in floors[0]["_aws"]["CloudWatchMetrics"][0]["Metrics"]}
    assert names == {"FloorTurns"}                       # its own record: `cause` never re-dimensions the
    turn = next(d for d in docs if "TurnLatencyMs" in d)  # turn block, whose (intent, model, mode) series stands
    assert "cause" not in turn
    assert ["intent", "model", "mode"] in turn["_aws"]["CloudWatchMetrics"][0]["Dimensions"]


def test_healthy_turn_emits_no_floorturns(monkeypatch, capsys):
    """No 0-semantics: a successful turn must not emit FloorTurns at all, so a SUM alarm needs no filter."""
    monkeypatch.setenv("GRAPHRAG_PLANNER", "onehop")

    def live_call(system, user, *, model, tool):
        return {"tldr": "t", "mechanism": "m", "diagram_mermaid": "", "sources": []}

    res = orch.respond("arabica frost outlook", graph=_graph(), asof="2024-01-01", call=live_call,
                       retrieve=_retrieve, classify=lambda q, call=None: {"intent": "reasoning"})
    assert "floor" not in res["trace"] and res["model"] != "(unavailable)"
    docs, out = _emf_lines(capsys)
    assert docs and not any("FloorTurns" in d for d in docs)
    assert "[floor]" not in out


# ── (c) the live-route seam, which logged nothing before ────────────────────────────────────────────
def test_live_route_floor_is_logged_and_counted(monkeypatch, capsys):
    """The `it.is_live` early-return seam had NO log line at all: a floor there was fully silent."""
    monkeypatch.setenv("GRAPHRAG_PLANNER", "onehop")
    monkeypatch.setattr(orch, "run_live",
                        lambda *a, **k: (_ for _ in ()).throw(QueryCanceled("statement timeout")))
    monkeypatch.setattr(orch, "_today", lambda: "2024-01-01")
    res = orch.respond("any news on arabica right now", graph=_graph(), asof="2024-01-01",
                       call=lambda *a, **k: {}, retrieve=_retrieve)
    assert res["trace"]["floor"] == "evidence_only"
    assert res["trace"]["floor_cause"] == "pg_statement_timeout"
    docs, out = _emf_lines(capsys)
    assert "[floor] kind=live cause_class=pg_statement_timeout" in out
    assert any(d.get("FloorTurns") == 1 and d.get("cause") == "pg_statement_timeout" for d in docs)


# ── (d) the thing that must NOT change: the floor answer payload ─────────────────────────────────────
def test_floor_answer_payload_is_byte_identical(monkeypatch, capsys):
    """F4a is observability ONLY. The floor payload is compared against _evidence_only's own output --
    the untouched producer -- key for key, so a logging/metric side effect on the answer would fail here."""
    exc = QueryCanceled("canceling statement due to statement timeout")
    res = _floor_turn(monkeypatch, exc)
    capsys.readouterr()
    direct = orch._evidence_only("arabica frost outlook", "2024-01-01", graph=_graph(),
                                 kind="reasoning", exc=exc, route_fn=None, near=None)
    for k in ("answer", "structured", "contract", "contracts", "citations", "evidence", "model", "intent"):
        assert res[k] == direct[k], k
    assert res["answer"].startswith("**Service notice.**")
    assert res["trace"]["error"] == direct["trace"]["error"]            # raw error unchanged
    # the ONLY trace addition at the floor seam is the bounded slug (respond/writeback add their own keys)
    assert set(direct["trace"]) | {"floor_cause"} <= set(res["trace"])
