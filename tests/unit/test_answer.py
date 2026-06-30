"""graphdev answer orchestrator — mocked (no S3/Bedrock/Anthropic)."""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import evidence as ev
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


def _retrieve(q, contract, *, k, asof=None, near=None):
    return [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{contract}",
             "text": "July frost hit Sul de Minas"}]


def test_route_picks_contract_by_alias():
    gr = _graph()
    assert an.route("what drives arabica coffee prices", gr)[0] == "arabica_coffee"
    assert an.route("maize export pace", gr)[0] == "corn"
    assert an.route("bitcoin volatility", gr) == []


def test_valid_mermaid_and_render():
    base = {"tldr": "t", "mechanism": "m", "sources": [{"ref": 1, "source": "S", "date": "2020", "note": "n"}]}
    assert "```mermaid" not in an.render({**base, "diagram_mermaid": ""})              # empty -> omitted
    assert "```mermaid" not in an.render({**base, "diagram_mermaid": "not a diagram"})  # invalid -> dropped
    md = an.render({**base, "diagram_mermaid": 'flowchart LR\n a["x +"] --> b'})
    assert md.startswith("**TL;DR.**") and "**Why.**" in md and "```mermaid" in md and "[1] S" in md
    assert an._valid_mermaid('flowchart LR\n a["x"] --> b') and not an._valid_mermaid("graph (oops]")


def test_answer_structured_render_and_trace():
    gr = _graph()
    captured = {}
    structured = {"tldr": "Frost squeezed arabica [1].", "mechanism": "frost raises price (+) [1].",
                  "diagram_mermaid": 'flowchart LR\n frost["frost +"] --> price["price up"]',
                  "sources": [{"ref": 1, "source": "GAIN", "date": "2021-07-20", "note": "frost"}]}

    def fake_call(system, user, *, model, tool):
        captured.update(user=user, model=model, tool=tool["name"])
        return structured

    out = an.answer("trace how a coffee frost spikes price", graph=gr, model="claude-sonnet-4-6",
                    retrieve=_retrieve, call=fake_call)
    assert out["contract"] == "arabica_coffee" and out["structured"] == structured
    assert captured["tool"] == "emit_answer" and captured["model"] == "claude-sonnet-4-6"
    md = out["answer"]                                                    # reader-first markdown
    assert md.startswith("**TL;DR.**") and "**Why.**" in md and "```mermaid" in md and "[1] GAIN" in md
    assert out["trace"]["has_diagram"] is True and "squeeze" in out["trace"]["regimes"]
    assert "frost kills trees" in captured["user"] and "July frost hit Sul de Minas" in captured["user"]


def test_answer_multi_contract_synthesis():
    gr = _graph()
    seen = {}

    def fake_call(system, user, *, model, tool):
        seen["user"] = user
        return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}

    def fake_retrieve(q, contract, *, k, asof=None, near=None):
        return [{"date": "2022-01-01", "source": "WASDE", "source_key": f"s3://{contract}", "text": f"{contract} note"}]

    out = an.answer("how does the maize vs arabica spread move", graph=gr, retrieve=fake_retrieve, call=fake_call)
    assert set(out["trace"]["contracts"]) == {"corn", "arabica_coffee"}
    assert {e["contract"] for e in out["evidence"]} == {"corn", "arabica_coffee"}
    assert "corn note" in seen["user"] and "arabica_coffee note" in seen["user"]
    assert out["trace"]["has_diagram"] is False                          # empty diagram -> none


def test_answer_no_contract_match_short_circuits():
    out = an.answer("tesla stock", graph=_graph(), retrieve=lambda *a, **k: [], call=lambda *a, **k: {},
                    route_fn=lambda q, g: [])                       # all tiers returned nothing
    assert out["contract"] is None and out["evidence"] == [] and out["structured"] is None


def test_route_smart_lexical_tier_wins():
    assert an.route_smart("what drives arabica coffee", _graph())[0] == "arabica_coffee"   # tier 1, no fallback


def test_route_smart_semantic_fallback():
    gr = _graph()
    an._PROFILE_CACHE.clear()
    def fake_embed(texts, **k):                                    # query + coffee profile -> [1,0]; corn -> [0,1]
        return [[1.0, 0.0] if ("coffee" in t or "frost" in t or "cold snap" in t) else [0.0, 1.0] for t in texts]
    got = an.route_smart("a damaging cold snap in the growing belt", gr, embed=fake_embed, k=1)
    assert got == ["arabica_coffee"]                               # no commodity token -> semantic matched coffee


def test_route_smart_llm_fallback():
    gr = _graph()
    an._PROFILE_CACHE.clear()
    called = {}
    def fake_route_call(system, user, *, model, tool):
        called["yes"] = True
        return {"contracts": ["corn"]}
    got = an.route_smart("zzz", gr, embed=lambda t, **k: [[0.0, 0.0] for _ in t], route_call=fake_route_call)
    assert got == ["corn"] and called["yes"]                       # lexical + semantic empty -> LLM tier


def test_answer_pulls_cross_cutting_driver_evidence(monkeypatch):
    gr = _graph()
    monkeypatch.setattr(ev, "driver_specs", lambda: {"frost": {"terms": ["frost"]}})
    monkeypatch.setattr(ev, "driver_slices_for", lambda t: ["frost"] if "frost" in t else [])
    seen = {}

    def fake_call(system, user, *, model, tool):
        seen["user"] = user
        return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}

    def fake_retrieve(q, node, *, k, asof=None, near=None):
        if node.startswith("drivers/"):                                  # the cross-cutting driver slice
            return [{"date": "2021-07-01", "source": "wb_cmo_outlook", "source_key": "s3://d",
                     "text": "a damaging frost hit the belt", "event_date": "2021-06-20"}]
        return [{"date": "2021-07-20", "source": "GAIN", "source_key": "s3://c", "text": "arabica note"}]

    out = an.answer("trace how a frost spikes arabica", graph=gr, retrieve=fake_retrieve,
                    driver_retrieve=fake_retrieve, call=fake_call)
    assert out["trace"]["drivers"] == ["frost"] and out["trace"]["n_driver_evidence"] == 1
    assert "CROSS-CUTTING DRIVER EVIDENCE" in seen["user"] and "{driver: frost}" in seen["user"]
    assert "event 2021-06-20" in seen["user"]                            # event date surfaced for the timeline


def test_source_tier_and_ev_block_tagging():
    assert an.source_tier("usda_wasde") == 1 and an.source_tier("usda_fas_coffee_wmt") == 1   # official/balance-sheet
    assert an.source_tier("usda_gain_coffee") == 2                                            # USDA attache
    assert an.source_tier("fnc") == 3 and an.source_tier("mpoc") == 3 and an.source_tier("conab") == 3
    assert an.source_tier("wb_cmo_outlook") == 4                                              # macro outlook
    assert an.source_tier("mystery") == 3                                                     # unknown -> mid
    block = an._ev_block([{"source": "wb_cmo_outlook", "date": "2016-09-01", "text": "frost damage"},
                          {"source": "usda_wasde", "date": "2016-01-01", "text": "stocks"}])
    assert "[T4] (wb_cmo_outlook" in block and "[T1] (usda_wasde" in block                    # tiers tag the evidence
