"""graphdev answer orchestrator — mocked (no S3/Bedrock/Anthropic)."""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as g


def _d(id, **o):
    return cs.Driver(id=id, type=o.pop("type", "hazard"), sign=o.pop("sign", "+"),
                     mechanism=o.pop("mechanism", "m"), **o)


def test_attach_provenance_stamps_source_key_without_changing_sources():
    """6.4: each kept evidence source gains its source_key (for the durable chip join) — additive, order
    and membership unchanged; a ref the verifier didn't resolve gets no key."""
    structured = {"sources": [{"ref": "1", "source": "usda_gain_corn", "date": "2022-01-01", "note": "x"},
                              {"ref": "2", "source": "usda_wasde", "date": "2022-01-05"},
                              {"ref": "N1", "source": "USDA PSD", "date": "2021-06-11"}]}
    verifier = {"resolved": {"1": {"source_key": "text/source=usda_gain_corn/y/document.json"}}}
    before = [dict(s) for s in structured["sources"]]
    an._attach_provenance(structured, verifier)
    assert len(structured["sources"]) == 3
    assert structured["sources"][0]["source_key"] == "text/source=usda_gain_corn/y/document.json"
    assert "source_key" not in structured["sources"][1]      # ref 2 not in resolved -> no key
    assert "source_key" not in structured["sources"][2]      # numbers ref -> no evidence key
    # nothing else mutated
    for b, a in zip(before, structured["sources"]):
        for k, v in b.items():
            assert a[k] == v


def test_humanize_structured_cleans_ui_fields():
    """The UI renders structured.{tldr,mechanism,sources} DIRECTLY (not the flattened body), so 6.1
    humanizes those in place: leaked regime ids/tokens gone, source ids -> official names."""
    d = {
        "tldr": "A bullish_drought_squeeze read; conf=high on drought.",
        "mechanism": "La Nina raises price (bullish). A bearish_glut is the offset.",
        "sources": [{"ref": 1, "source": "usda_gain_corn", "date": "2022-01-01",
                     "note": "supports the bullish_drought_squeeze"}],
    }
    an._humanize_structured(d)
    assert "bullish_drought_squeeze" not in d["tldr"] and "conf=" not in d["tldr"]
    assert "drought squeeze (price-supportive)" in d["tldr"] and "high confidence" in d["tldr"]
    assert "bearish_glut" not in d["mechanism"] and "supply glut (price-pressuring)" in d["mechanism"]
    assert "(price-supportive)" in d["mechanism"]                     # bare '(bullish)' -> _MOOD safety net
    assert "bullish" not in d["mechanism"] and "bearish" not in d["mechanism"]
    assert d["sources"][0]["source"] == "USDA FAS GAIN Report — Corn"
    assert "bullish_drought_squeeze" not in d["sources"][0]["note"]
    # no internal-token leaks survive in the reader-facing fields
    from leviathan.graphrag import register as reg
    assert reg.register_leaks(d["tldr"] + " " + d["mechanism"]) == []


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


def test_answer_renders_single_validated_source_list():
    """Citations v2: ONE reader-facing Sources block, numbered by the model's OWN validated handles —
    the parallel [E1]-numbered footer is gone (two lists with independent numbering read as
    'mismatched citations' and inflated the judge's hallucination tally)."""
    gr = _graph()

    def fake_call(system, user, *, model, tool):
        return {"tldr": "stocks are tight [1].", "mechanism": "y", "diagram_mermaid": "",
                "sources": [{"ref": "1", "source": "usda_wasde", "date": "2022-01-01", "note": ""}]}

    def fake_retrieve(q, contract, *, k, asof=None, near=None):
        return [{"date": "2022-01-01", "source": "usda_wasde", "source_key": f"s3://{contract}",
                 "text": f"{contract} ending stocks note"}]

    out = an.answer("arabica coffee outlook", graph=gr, retrieve=fake_retrieve, call=fake_call)
    assert out["answer"].count("## Sources") == 1
    assert "[1] USDA WASDE (2022-01-01):" in out["answer"]                    # model handle, official name (6.1)
    assert "[E1]" not in out["answer"]                                        # the parallel footer is gone
    assert out["citations"] and out["citations"][0]["kind"] == "evidence"     # machine list unchanged
    assert out["citations"][0]["locator"]["kind"] == "doc"


def test_answer_verifier_off_keeps_legacy_footer(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_VERIFY", "off")
    gr = _graph()

    def fake_call(system, user, *, model, tool):
        return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}

    def fake_retrieve(q, contract, *, k, asof=None, near=None):
        return [{"date": "2022-01-01", "source": "usda_wasde", "source_key": f"s3://{contract}",
                 "text": f"{contract} ending stocks note"}]

    out = an.answer("arabica coffee outlook", graph=gr, retrieve=fake_retrieve, call=fake_call)
    assert "## Sources" in out["answer"] and "[E1]" in out["answer"]          # legacy rendering intact
    monkeypatch.delenv("GRAPHRAG_VERIFY")


def test_context_block_surfaces_confidence_and_target_metric():
    c = cs.CausalContract(contract="arabica_coffee", drivers=[
        _d("frost", sign="+", confidence="high", mechanism="frost kills trees"),
        _d("dry", sign="-", confidence="low", target_metric="yield", mechanism="dryness cuts yield")])
    block = an._context_block(g.CausalGraph({"arabica_coffee": c}, silver=set()), "arabica_coffee")
    assert "conf=high" in block and "conf=low" in block          # confidence surfaced -> feeds hypothesis framing
    assert "- frost | + on price" in block                       # default contract target
    assert "- dry | - on yield" in block                         # per-driver target_metric override (#3)


def test_system_prompt_carries_grounding_guardrails():
    assert "APPROVED EDGES ONLY" in an._SYSTEM and "CONFIDENCE:" in an._SYSTEM   # #25 do-not-infer guardrails present


def test_system_prompt_convexity_research_register():
    s = an._SYSTEM                                                    # resolves to _SYSTEM_MENTOR (default bind)
    import re
    assert "convex" in s.lower() and "tail risk" in s.lower()                   # convexity/tail framing
    assert "position sizing" in s.lower()                                       # explicitly out of scope (research)
    assert "physical trader" in s and "fund analyst" in s                       # P9-A mixed-room framing
    assert "OUTPUT REGISTER" in s                                               # register block present
    # the ONE sanctioned negative instruction carved out, then NO residual mood word anywhere in the prompt
    residual = re.sub(r"NEVER write 'bullish' or 'bearish'\.?", "", s)
    assert not re.search(r"bullish|bearish", residual)
    assert "mechanism" in s.lower() and "higher prices" in s.lower()            # mentor register present


def test_mentor_voice_env_gate(monkeypatch):
    """P9-A D9: the persona flips PER CALL on GRAPHRAG_MENTOR_VOICE (a memoized read would make the
    env-off rollback a silent no-op on a long-lived serving process)."""
    monkeypatch.delenv("GRAPHRAG_MENTOR_VOICE", raising=False)
    assert an._system() is an._SYSTEM_MENTOR                          # default on
    monkeypatch.setenv("GRAPHRAG_MENTOR_VOICE", "off")
    assert an._system() is an._SYSTEM_LEGACY                          # flips without re-import
    monkeypatch.setenv("GRAPHRAG_MENTOR_VOICE", "on")
    assert an._system() is an._SYSTEM_MENTOR


def test_answer_l2_walks_grounds_and_overrides_diagram(monkeypatch):
    gr = _graph()
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[1.0 if "frost" in t.lower() else 0.0] for t in texts])

    captured = {}

    def fake_call(system, user, *, model, tool):
        captured["user"] = user
        return {"tldr": "frost bullish [1]", "mechanism": "frost raises price (bullish) [1]", "diagram_mermaid": "",
                "sources": [{"ref": 1, "source": "GAIN", "date": "2021-07-20", "note": "frost"}]}

    def fake_retrieve(q, node, *, k, asof=None, near=None):
        return [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{node}", "text": "July frost hit"}]

    out = an.answer("trace how a coffee frost spikes price", graph=gr, planner="l2", asof="2021-08-01",
                    retrieve=fake_retrieve, call=fake_call, route_fn=lambda q, g: ["arabica_coffee"])
    assert out["trace"]["planner"] == "l2"
    diagram = out["structured"]["diagram_mermaid"]
    assert "flowchart" in diagram and "frost" in diagram                        # graph-derived diagram overrode the LLM's ""
    # firing needs an as-of anchor + recent evidence (2021-07-20 falls within the window before 2021-08-01)
    assert ("arabica_coffee", "squeeze") in {(r["contract"], r["name"]) for r in out["trace"]["fired_regimes"]}
    assert "frost kills trees" in captured["user"]                              # the walked subgraph's prior reached the reasoner
    assert "```mermaid" in out["answer"] and "## Sources" in out["answer"]


def test_source_tier_and_ev_block_tagging():
    assert an.source_tier("usda_wasde") == 1 and an.source_tier("usda_fas_coffee_wmt") == 1   # official/balance-sheet
    assert an.source_tier("usda_gain_coffee") == 2                                            # USDA attache
    assert an.source_tier("fnc") == 3 and an.source_tier("mpoc") == 3 and an.source_tier("conab") == 3
    assert an.source_tier("wb_cmo_outlook") == 4                                              # macro outlook
    assert an.source_tier("mystery") == 3                                                     # unknown -> mid
    block = an._ev_block([{"source": "wb_cmo_outlook", "date": "2016-09-01", "text": "frost damage"},
                          {"source": "usda_wasde", "date": "2016-01-01", "text": "stocks"}])
    assert "[T4] (wb_cmo_outlook" in block and "[T1] (usda_wasde" in block                    # tiers tag the evidence


def test_banned_mood_words_counted_pre_sanitize():
    """P9-A: the count runs on the RAW structured (sanitize would neutralize the words and read 0)."""
    raw = {"tldr": "Soybeans are bullish.", "mechanism": "A bearish offset; still bullish overall.", "sources": []}
    assert an._count_banned_mood(raw) == 3
    assert an._count_banned_mood({"tldr": "", "mechanism": ""}) == 0
    assert an._count_banned_mood({"tldr": "points to higher prices", "mechanism": "price-pressuring"}) == 0
    # and the sanitized rendering of the same fields carries none (the safety net rewrites them)
    from leviathan.graphrag import register as reg
    assert "bullish" not in reg.sanitize(raw["tldr"]) and "bearish" not in reg.sanitize(raw["mechanism"])


def test_ev_block_renders_usable_event_date_only():
    """P9-A W0: '; event <date>' renders only for a REAL event date — sentinel/None/same-as-report stay silent."""
    base = {"source": "usda_gain", "date": "2010-09-01", "text": "Russia bans wheat exports."}
    assert "; event 2010-08-05" in an._ev_block([{**base, "event_date": "2010-08-05"}])
    assert "; event" not in an._ev_block([{**base, "event_date": "1970-01-01"}])   # sentinel rejected
    assert "; event" not in an._ev_block([{**base, "event_date": None}])
    assert "; event" not in an._ev_block([{**base, "event_date": "2010-09-01"}])   # == report date: no dup
    assert an._usable_date("2010-08-05") == "2010-08-05"
    assert an._usable_date("1970-01-01") is None and an._usable_date(None) is None
