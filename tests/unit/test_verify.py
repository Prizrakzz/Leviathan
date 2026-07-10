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


def test_resolved_mapping_exposed_for_unified_rendering():
    s = _structured("Record corn prices occurred in August 2012 on the drought [2].",
                    [{"ref": "2", "source": "usda_wasde", "date": "2012-08-10", "note": ""}])
    rep = vf.verify_citations(s, EV, [])
    r = rep["resolved"]["2"]
    assert r["source"] == "usda_wasde" and r["date"] == "2012-08-10"
    assert r["snippet"].startswith("Record soybean and corn prices")


def test_foreign_regime_name_stripped_own_survives():
    s = _structured("The bullish_weather_squeeze conditions are documented; the bullish_protein_squeeze "
                    "regime also looms on the drought [2].",
                    [{"ref": "2", "source": "usda_wasde", "date": "2012-08-10", "note": ""}])
    rep = vf.verify_citations(s, EV, [], foreign_names={"bullish_protein_squeeze"})
    assert "bullish_protein_squeeze" not in s["tldr"]                # another contract's regime = fabrication
    assert "bullish_weather_squeeze" in s["tldr"]                    # this contract's own regime survives
    assert rep["by_rule"].get("foreign_regime_name") == 1


# ── P7-P0.1: claim_count — the strip-RATE denominator ────────────────────────────────────────────────
def test_claim_count_counts_sentences_pre_strip():
    # Three sentences, one cited (supported), one cited (fabricated -> stripped), one uncited.
    s = {"tldr": "Prices rose on the 2012 US drought [2]. Turkish hazelnut tariffs doubled overnight [9].",
         "mechanism": "Buffers were thin.",
         "sources": [{"ref": "2", "source": "usda_wasde", "date": "2012-08-10"},
                     {"ref": "9", "source": "made_up_journal", "date": "1999-01-01"}]}
    rep = vf.verify_citations(s, EV, NUMS)
    assert rep["claim_count"] == 3                          # sentences, counted BEFORE any handle stripping
    assert rep["checked"] >= 2                              # handles remain the secondary denominator
    assert rep["stripped"] >= 1                             # the fabricated [9] ledger row / claim strips
    # the denominator is not reduced by the strip (captured pre-mutation)
    assert rep["claim_count"] == 3


def test_claim_count_zero_handles_answer_not_degenerate():
    # An all-uncited answer: claim_count counts sentences; handles checked == 0; rate reads 0, never NaN.
    s = {"tldr": "Stocks are tight. Exports are slow.", "mechanism": "", "sources": []}
    rep = vf.verify_citations(s, EV, NUMS)
    assert rep["claim_count"] == 2 and rep["checked"] == 0 and rep["stripped"] == 0
    assert rep["stripped"] / max(1, rep["claim_count"]) == 0.0


def test_claim_count_zero_when_verifier_off(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_VERIFY", "off")
    rep = vf.verify_citations({"tldr": "One. Two."}, EV, NUMS)
    assert rep["enabled"] is False and rep.get("claim_count", 0) == 0


# ── P9-B: the all-numbers guard (number_unbacked) ────────────────────────────────────────────────────
def test_number_unbacked_strips_free_riding_figure():
    """'rose to 5900 [N3], up 18%' with only 5900 injected -> the 18 rides unverified -> strip."""
    from leviathan.graphrag import verify as vf
    calls = [{"rows": [{"value": "5900"}]}]
    assert vf._check_number_handle("exports rose to 5900 [N1], up 18%", 1, calls) == "number_unbacked"
    calls2 = calls + [{"rows": [{"value": 18.0}]}]                    # the pct-change row injected -> passes
    assert vf._check_number_handle("exports rose to 5900 [N1], up 18%", 1, calls2) is None


def test_number_unbacked_percent_vs_ratio():
    """The ratio trap: a pre-scaled 36.0/'%' row backs '~36%'; a raw 0.36 ratio does NOT back '~40%'
    (scale-1 _num_backed, no multi-scale bridging)."""
    from leviathan.graphrag import verify as vf
    assert vf._check_number_handle("S/U near 36% [N1]", 1, [{"rows": [{"value": 36.0, "unit": "%"}]}]) is None
    assert vf._check_number_handle("S/U near 40% [N1]", 1,
                                   [{"rows": [{"value": 0.36, "unit": "ratio"}]}]) is not None


def test_number_unbacked_year_token_exempt():
    """A bare 4-digit year is a date, not a strippable magnitude; handle digits are stripped too."""
    from leviathan.graphrag import verify as vf
    assert vf._check_number_handle("the 2012 drought cut S/U to 8% [N1]", 1,
                                   [{"rows": [{"value": 8.0}]}]) is None


def test_number_unbacked_single_flag_rollback(monkeypatch):
    """GRAPHRAG_CASCADE_QUANT=off fully reverts the stricter guard (no second env to unset)."""
    from leviathan.graphrag import verify as vf
    monkeypatch.setenv("GRAPHRAG_CASCADE_QUANT", "off")
    calls = [{"rows": [{"value": "5900"}]}]
    assert vf._check_number_handle("exports rose to 5900 [N1], up 18%", 1, calls) is None
