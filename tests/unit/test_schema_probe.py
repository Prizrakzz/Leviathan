"""WS-B compact-output schema — mocked unit tests (no network): round-trip equivalence, the recall scorer,
and the go/no-go decision."""
from __future__ import annotations

from leviathan.graphrag import extract as ex
from leviathan.graphrag import schema_probe as sp

# a FULL emission and its SLIM / SHORT equivalents on identical content
_FULL = {"entities": [{"id": "cotton", "type": "commodity", "canonical_name": "cotton", "mapped": True},
                      {"id": "excess_rain", "type": "hazard", "canonical_name": "excess_rain", "mapped": True}],
         "relationships": [{"src": "excess_rain", "dst": "cotton", "relation_type": "affects_yield_of",
                            "metric": "yield", "sign": "-", "evidence_class": "reported_claim",
                            "marker": "due to", "verbatim": "yield fell due to rain", "mapped": True}],
         "events": [], "quantitative_claims": [{"entity": "cotton", "metric": "yield", "value": None,
                                                "unit": "", "period": "", "direction": "-", "verbatim": "x"}],
         "unmapped_relations": [], "unmapped_entities": ["shrimp"]}
_SLIM = {"entities": [{"id": "cotton", "type": "commodity"}, {"id": "excess_rain", "type": "hazard"}],
         "relationships": [{"src": "excess_rain", "dst": "cotton", "relation_type": "affects_yield_of",
                            "metric": "yield", "sign": "-", "evidence_class": "reported_claim", "marker": "due to"}],
         "events": [], "quantitative_claims": [{"entity": "cotton", "metric": "yield", "direction": "-"}],
         "unmapped_relations": [], "unmapped_entities": ["shrimp"]}
_SHORT = {"E": [{"i": "cotton", "t": "commodity"}, {"i": "excess_rain", "t": "hazard"}],
          "R": [{"s": "excess_rain", "d": "cotton", "r": "affects_yield_of", "m": "yield", "g": "-",
                 "c": "reported_claim", "k": "due to"}],
          "Q": [{"e": "cotton", "m": "yield", "g": "-"}], "UE": ["shrimp"]}


def _sig(x):
    return (sorted((e.id, e.type) for e in x.entities),
            sorted((r.src, r.dst, r.relation_type, r.metric, r.sign, r.marker) for r in x.relationships),
            sorted((q.entity, q.metric, q.direction) for q in x.quantitative_claims),
            sorted(x.unmapped_entities))


def test_parse_compact_slim_and_short_roundtrip_full():
    full = ex.parse_extraction(_FULL)
    assert _sig(ex.parse_compact(_SLIM, short=False)) == _sig(full)
    assert _sig(ex.parse_compact(_SHORT, short=True)) == _sig(full)


def test_parse_compact_defaults_verbatim_and_canonical():
    x = ex.parse_compact(_SLIM)
    assert x.relationships[0].verbatim == "" and x.entities[0].canonical_name == "cotton"


def test_compact_tool_omits_verbatim_and_shortens_keys():
    rel_full = ex.compact_output_tool(short=False)["input_schema"]["properties"]["relationships"]["items"]["properties"]
    assert "verbatim" not in rel_full and "src" in rel_full          # semantic keys, no verbatim
    short = ex.compact_output_tool(short=True)["input_schema"]["properties"]
    assert "R" in short and "relationships" not in short             # shortened top-level keys
    assert ex.compact_output_tool()["name"] == "emit_extraction"     # same name → forced tool_choice unchanged


def test_micro_recall_precision():
    pairs = [({1, 2, 3}, {1, 2}), ({4}, {2, 4})]                     # tp: {1,2}∩ + {4}∩ = 1+1=... compute
    # ref total = 2+2 = 4; test total = 3+1 = 4; inter = |{1,2}|=2 + |{4}|=1 = 3
    r, p = sp._micro(pairs)
    assert round(r, 3) == 0.75 and round(p, 3) == 0.75


def test_edges_scoring_against_gold():
    x = ex.parse_extraction(_FULL)
    gold = [{"src": "excess_rain", "rel": "affects_yield_of", "dst": "cotton", "metric": "yield", "sign": "-"}]
    assert sp._edges_x(x) == sp._edges_gold(gold)                    # exact match → recall/precision 1.0


# ── decision logic ───────────────────────────────────────────────────────────────────
def _arm(name, out_tok, read=4000):
    a = sp.ArmResult(name=name)
    a.usages = [ex.Usage(input_tokens=80, output_tokens=out_tok, cache_read=read) for _ in range(5)]
    a.extractions = [ex.ChunkExtraction() for _ in range(5)]
    return a


def test_report_picks_slim_when_recall_holds_but_short_fails():
    arms = {"FULL": _arm("FULL", 380), "SLIM": _arm("SLIM", 250), "SHORT": _arm("SHORT", 200)}
    scores = {
        "FULL": {"edge_g": (0.90, 0.85), "ent_g": (0.9, 0.9), "quant_g": (0.8, 0.8)},
        "SLIM": {"edge_g": (0.89, 0.85), "ent_g": (0.9, 0.9), "quant_g": (0.8, 0.8), "edge_f": (0.99, 0.98)},
        "SHORT": {"edge_g": (0.80, 0.85), "ent_g": (0.9, 0.9), "quant_g": (0.8, 0.8), "edge_f": (0.88, 0.9)},
    }
    rep = sp.build_report(arms, scores, n=5)
    assert "Decision: **SLIM**" in rep and "out save" in rep


def test_report_keeps_full_when_no_arm_holds_recall():
    arms = {"FULL": _arm("FULL", 380), "SLIM": _arm("SLIM", 250), "SHORT": _arm("SHORT", 200)}
    scores = {
        "FULL": {"edge_g": (0.90, 0.85), "ent_g": (0.9, 0.9), "quant_g": (0.8, 0.8)},
        "SLIM": {"edge_g": (0.80, 0.85), "ent_g": (0.9, 0.9), "quant_g": (0.8, 0.8), "edge_f": (0.88, 0.9)},
        "SHORT": {"edge_g": (0.70, 0.85), "ent_g": (0.9, 0.9), "quant_g": (0.8, 0.8), "edge_f": (0.77, 0.9)},
    }
    rep = sp.build_report(arms, scores, n=5)
    assert "Decision: **FULL**" in rep and "keep FULL" in rep
