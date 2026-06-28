"""graphdev answer orchestrator — mocked (no S3/Bedrock/Anthropic)."""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import graph as g


def _d(id, **o):
    return cs.Driver(id=id, type=o.pop("type", "hazard"), sign=o.pop("sign", "+"),
                     mechanism=o.pop("mechanism", "m"), **o)


def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica", "KC"],
        drivers=[_d("frost", sign="+", mechanism="frost kills trees")],
        convergence=[cs.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=1, drivers=["frost"])],
        inter_commodity=[cs.InterCommodityEdge(driver_commodity="robusta_coffee", relation="substitutes_for", sign="-")])
    corn = cs.CausalContract(contract="corn", aliases=["maize"], drivers=[_d("drought")])
    return g.CausalGraph({"arabica_coffee": coffee, "corn": corn}, silver=set())


def test_route_picks_contract_by_alias():
    gr = _graph()
    assert an.route("what drives arabica coffee prices", gr)[0] == "arabica_coffee"
    assert an.route("maize export pace", gr)[0] == "corn"          # alias 'maize' -> corn
    assert an.route("bitcoin volatility", gr) == []                # nothing tracked matches


def test_answer_assembles_context_and_returns_trace():
    gr = _graph()
    captured = {}

    def fake_chat(system, user, *, model, **kw):
        captured.update(system=system, user=user, model=model)
        return "Frost raises price (GAIN, 2021-07)."

    def fake_retrieve(q, contract, *, k, asof=None):
        return [{"date": "2021-07-20", "source": "GAIN", "source_key": "s3://k1",
                 "text": "July frost hit Sul de Minas"}]

    out = an.answer("what caused the 2021 coffee spike", graph=gr, model="claude-sonnet-4-6",
                    retrieve=fake_retrieve, chat=fake_chat)
    assert out["contract"] == "arabica_coffee" and out["model"] == "claude-sonnet-4-6"
    assert out["evidence"][0]["source"] == "GAIN" and out["trace"]["evidence_ids"] == ["s3://k1"]
    assert "squeeze" in out["trace"]["regimes"]
    # the serving model was fed the driver mechanism, the regime, and the dated evidence
    assert "frost kills trees" in captured["user"] and "July frost hit Sul de Minas" in captured["user"]
    assert "2021-07-20" in captured["user"] and captured["model"] == "claude-sonnet-4-6"


def test_answer_no_contract_match_short_circuits():
    out = an.answer("tesla stock", graph=_graph(), retrieve=lambda *a, **k: [], chat=lambda *a, **k: "x")
    assert out["contract"] is None and out["evidence"] == []
