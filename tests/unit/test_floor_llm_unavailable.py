"""W8: `llm_unavailable` -- the 5th floor cause class, and the death of the display-string sniff.

Two defects, one theme: the floor could not say WHY it fired, and the eval gate that protects every
published aggregate identified a floored turn by reading a UI label.

  (a) The floor's own definition is "every LLM attempt has failed" (providers.py: typed backoff ladder ->
      one degraded-model attempt -> raise), so a provider outage is its single most likely cause -- and it
      landed in `other`, indistinguishable from a code bug. The 2026-07-19 incident cost hours because
      "the model tier is down" and "our retrieval is broken" produced identical telemetry.
  (b) `eval.report` counted floored turns with `out['model'] == "(unavailable)"`. That is the human-facing
      model label. A copy edit of a display string would have silently disarmed the RUN-INCONCLUSIVE gate,
      and an outage would then be read as a quality regression against a healthy baseline.

Pinned as UNCHANGED: `trace.floor` stays `evidence_only` -- it names WHICH floor served the turn, and the
new slug is a CAUSE, on `trace.floor_cause` / the FloorTurns `cause` dimension. Conflating the two would
make the eval's presence test a value test.

Mocked end to end (the reasoner is a fake that raises, retrieval is injected). No LLM/AWS spend.
"""
from __future__ import annotations

import json

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import eval as gev
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import providers as pv


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
    """The floor calls evidence.retrieve DIRECTLY (an._RETRIEVAL), which would reach pgvector/bge here."""
    from leviathan.graphrag import evidence as ev
    monkeypatch.setattr(ev, "retrieve",
                        lambda q, node, **kw: [{"date": "2024-01-01", "source": "usda_wasde",
                                                "source_key": f"s3://{node}", "text": "stocks note"}])


# The SDK availability errors, by the names the classifier matches. Declared locally (as the F4a suite
# does for psycopg's) because instantiating anthropic's are response-object-dependent; the coupling to the
# REAL SDK classes is pinned separately below, which is what actually protects this.
class RateLimitError(Exception):
    """anthropic 429."""


class InternalServerError(Exception):
    """anthropic >=500, incl. 529 overloaded_error."""


class APIConnectionError(Exception):
    """anthropic network failure."""


class ThrottlingException(Exception):
    """botocore/bedrock-runtime throttle (GRAPHRAG_PROVIDER=bedrock)."""


class OperationalError(Exception):
    """psycopg connection-class failure -- must NOT be reclassified."""


def _floor_turn(monkeypatch, exc: BaseException, *, kind: str = "reasoning") -> dict:
    monkeypatch.setenv("GRAPHRAG_PLANNER", "onehop")

    def dead_call(system, user, *, model, tool):
        raise exc

    return orch.respond("arabica frost outlook", graph=_graph(), asof="2024-01-01", call=dead_call,
                        retrieve=_retrieve, classify=lambda q, call=None: {"intent": kind})


def _emf_lines(capsys) -> tuple[list[dict], str]:
    out = capsys.readouterr().out
    return [json.loads(ln) for ln in out.splitlines() if ln.startswith("{")], out


# -- (a) the new cause class --------------------------------------------------------------------------
@pytest.mark.parametrize("exc", [RateLimitError("rate_limit_error: 429"),
                                 InternalServerError("overloaded_error"),
                                 APIConnectionError("connection error"),
                                 ThrottlingException("Too many requests")],
                         ids=["429", "529_overloaded", "connection", "bedrock_throttle"])
def test_provider_outage_stamps_llm_unavailable(monkeypatch, capsys, exc):
    res = _floor_turn(monkeypatch, exc)
    assert res["trace"]["floor_cause"] == "llm_unavailable"
    assert "llm_unavailable" in orch._FLOOR_CAUSES               # closed set: no minted dimension values
    assert res["trace"]["floor"] == "evidence_only"              # UNCHANGED: which floor served the turn
    assert res["model"] == "(unavailable)"                       # payload untouched -- telemetry only
    assert res["answer"].startswith("**Service notice.**")

    docs, out = _emf_lines(capsys)
    assert "cause_class=llm_unavailable" in out                  # the one structured [floor] line
    floors = [d for d in docs if "FloorTurns" in d]
    assert len(floors) == 1 and floors[0]["cause"] == "llm_unavailable"


def test_the_slug_is_coupled_to_the_real_sdk_exception_names():
    """The classifier matches TYPE NAMES, so it must track providers.RETRYABLE -- the exact tuple the
    serving fallback chain gives up on. If anthropic renames one, or a class is added to RETRYABLE
    without a matcher, that outage silently reverts to `other` and this fails."""
    assert pv.RETRYABLE, "the retry ladder lost its typed-exception set"
    for cls in pv.RETRYABLE:
        name = cls.__name__.lower()
        assert any(t in name for t in orch._LLM_UNAVAILABLE_TYPES), f"{cls.__name__} -> would fall to other"


def test_other_causes_are_not_reclassified(monkeypatch):
    """Precedence pin: the LLM test runs LAST, so an infra failure keeps its own, more specific class."""
    assert orch._floor_cause(OperationalError("connection to server was lost")) == "pg_operational"
    assert orch._floor_cause(OperationalError("canceling statement due to statement timeout")) \
        == "pg_statement_timeout"
    assert orch._floor_cause(OSError("We couldn't connect to 'https://huggingface.co' to load the files")) \
        == "model_download"
    assert orch._floor_cause(RuntimeError("provider hard down")) == "other"   # prose is not a signal
    assert orch._floor_cause(Exception()) == "other"                          # classifier stays total


# -- (b) the eval gate, keyed on the trace slug ------------------------------------------------------
def _row(*, floored: bool, cause: str = "llm_unavailable", model: str = "claude-sonnet-4-6") -> dict:
    trace = {"floor": "evidence_only", "floor_cause": cause} if floored else {}
    return {"q": {"id": "q1", "category": "convergence", "question": "what caused the spike",
                  "contract": "arabica_coffee"},
            "out": {"answer": "a", "contract": "arabica_coffee", "evidence": [], "model": model,
                    "trace": trace},
            "rubric": {"routed_right": True}}


def test_run_inconclusive_gate_survives_a_display_string_rename():
    """THE POINT: the model label is renamed to something the old sniff would never match, and the gate
    still trips -- because it reads `trace.floor`, a machine contract, not a UI string."""
    rows = [_row(floored=True, model="(model temporarily unavailable)") for _ in range(2)]
    rows += [_row(floored=False) for _ in range(6)]               # 2/8 = 25% > 15%
    rep = gev.report(rows, model="claude-sonnet-4-6")
    assert "RUN INCONCLUSIVE -- 2/8 turns floored" in rep
    assert "llm_unavailable" in rep                               # and it says WHICH outage it was
    assert "(unavailable)" not in rep                             # the sniff string is gone entirely


def test_gate_reports_the_cause_mix_and_stays_quiet_on_a_healthy_run():
    rows = [_row(floored=True, cause="llm_unavailable"), _row(floored=True, cause="pg_statement_timeout")]
    rows += [_row(floored=False) for _ in range(6)]
    rep = gev.report(rows, model="claude-sonnet-4-6")
    assert "llm_unavailable x1" in rep and "pg_statement_timeout x1" in rep

    healthy = gev.report([_row(floored=False) for _ in range(8)], model="claude-sonnet-4-6")
    assert "RUN INCONCLUSIVE" not in healthy


def test_gate_does_not_trip_below_the_threshold():
    rows = [_row(floored=True)] + [_row(floored=False) for _ in range(9)]   # 1/10 = 10% <= 15%
    assert "RUN INCONCLUSIVE" not in gev.report(rows, model="claude-sonnet-4-6")
