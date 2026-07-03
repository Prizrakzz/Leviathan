"""Deterministic citation verifier — every rule + the repair policy (no LLM, no I/O).

Pins the anchor model (the model's own `sources` ledger maps [n] -> {source, date}; prose checks run
against the ledger-resolved items), the strip-never-retry policy, ledger date CORRECTION vs
fabrication DROP, number-scale matching, and the kill switch.
"""
from __future__ import annotations

from leviathan.graphrag import verify as vf

EV = [
    {"source": "usda_gain_soybean_oil", "date": "2026-03-31",
     "text": "Brazil remains a marginal source of soybean meal for Mexico, whose imports rose modestly."},
    {"source": "usda_wasde", "date": "2012-08-10",
     "text": "Record soybean and corn prices occurred in July and August 2012 due to the US drought."},
]
NUMS = [{"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn"},
         "rows": [{"value": "31400000", "knowledge_date": "2012-09-12"}]}]


def _structured(tldr, sources, mechanism=""):
    return {"tldr": tldr, "mechanism": mechanism, "sources": sources}


def test_fabricated_attribution_stripped_enso_case():
    """The measured defect: a tariff claim pinned on the Mexico-meal prop -> no overlap -> stripped."""
    s = _structured(
        "Tariff escalation concentrates Chinese buying on Brazilian beans, documented near the as-of [1].",
        [{"ref": "1", "source": "usda_gain_soybean_oil", "date": "2026-03-31", "note": ""}])
    rep = vf.verify_citations(s, EV, [])
    assert "[1]" not in s["tldr"]
    assert rep["stripped"] == 1 and rep["by_rule"].get("no_lexical_overlap") == 1


def test_supported_claim_survives():
    s = _structured("Record corn prices occurred in August 2012 on the drought [2].",
                    [{"ref": "2", "source": "usda_wasde", "date": "2012-08-10", "note": ""}])
    rep = vf.verify_citations(s, EV, [])
    assert "[2]" in s["tldr"] and rep["stripped"] == 0


def test_ledger_source_nobody_provided_is_dropped():
    s = _structured("Prices rose [3].",
                    [{"ref": "3", "source": "reuters_live_wire", "date": "2026-01-01", "note": ""}])
    rep = vf.verify_citations(s, EV, [])
    assert s["sources"] == []                                        # fabricated ledger entry dropped
    assert "[3]" not in s["tldr"]
    assert rep["by_rule"].get("fabricated_citation", 0) >= 1


def test_mistyped_ledger_date_corrected_not_dropped():
    s = _structured("Record prices in 2012 on the drought [1].",
                    [{"ref": "1", "source": "usda_wasde", "date": "2012-08-11", "note": ""}])
    rep = vf.verify_citations(s, EV, [])
    assert s["sources"][0]["date"] == "2012-08-10"                   # corrected to the real item
    assert rep["corrected"] == 1 and "[1]" in s["tldr"]


def test_quote_must_substring_match():
    s = _structured('The report said "yields collapsed by half across the belt" [1].',
                    [{"ref": "1", "source": "usda_wasde", "date": "2012-08-10", "note": ""}])
    rep = vf.verify_citations(s, EV, [])
    assert "[1]" not in s["tldr"] and rep["by_rule"].get("quote_mismatch") == 1


def test_number_handle_scale_match_and_mismatch():
    ok = _structured("Ending stocks were 31.4 million MT [N1].", [])
    assert vf.verify_citations(ok, EV, NUMS)["stripped"] == 0 and "[N1]" in ok["tldr"]
    bad = _structured("Ending stocks were 48.2 million MT [N1].", [])
    rep = vf.verify_citations(bad, EV, NUMS)
    assert "[N1]" not in bad["tldr"] and rep["by_rule"].get("number_mismatch") == 1


def test_number_handle_out_of_range():
    s = _structured("Stocks were 31.4 million MT [N7].", [])
    rep = vf.verify_citations(s, EV, NUMS)
    assert "[N7]" not in s["tldr"] and rep["by_rule"].get("index_out_of_range") == 1


def test_undeclared_handle_kept_only_when_some_item_supports():
    sup = _structured("Record corn prices occurred in the 2012 drought [9].", [])
    assert vf.verify_citations(sup, EV, [])["stripped"] == 0         # supported by EV[1] -> benefit of doubt
    unsup = _structured("Freight rates spiked on Panama canal restrictions [9].", [])
    rep = vf.verify_citations(unsup, EV, [])
    assert "[9]" not in unsup["tldr"] and rep["by_rule"].get("undeclared_unsupported") == 1


def test_formatting_preserved_across_paragraphs():
    mech = "Para one about drought prices in 2012 [1].\n\n- bullet stays\n- so does this [1]."
    s = _structured("t", [{"ref": "1", "source": "usda_wasde", "date": "2012-08-10"}], mechanism=mech)
    vf.verify_citations(s, EV, [])
    assert "\n\n- bullet stays\n" in s["mechanism"]                  # position-based strip, no reflow


def test_kill_switch_and_never_raises(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_VERIFY", "off")
    s = _structured("anything [1]", [])
    assert vf.verify_citations(s, EV, [])["enabled"] is False and "[1]" in s["tldr"]
    monkeypatch.delenv("GRAPHRAG_VERIFY")
    weird = {"tldr": None, "mechanism": 42, "sources": "not-a-list"}
    rep = vf.verify_citations(weird, None, None)                     # garbage in -> report, never raise
    assert isinstance(rep, dict)
