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


def test_number_handle_scale_match_and_mismatch(monkeypatch):
    ok = _structured("Ending stocks were 31.4 million MT [N1].", [])
    assert vf.verify_citations(ok, EV, NUMS)["stripped"] == 0 and "[N1]" in ok["tldr"]
    # the MISMATCH half is pinned in legacy mode: under the default the sentence is repairable (one claim
    # number, one row value), so the handle-only strip it asserts is exactly what GRAPHRAG_VERIFY_NUM_MODE
    # =handle preserves. The default behaviour on this same input is pinned below.
    monkeypatch.setenv("GRAPHRAG_VERIFY_NUM_MODE", "handle")
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


def test_resolved_mapping_carries_span_offsets_when_the_item_has_them():
    """Phase F: char_start/char_end/offset_kind ride the resolved payload to structured.sources -> the FE
    PDF highlight. An offset-less item (pre-offset vintage) resolves with honest Nones -- same shape,
    never a KeyError."""
    ev_with = [{**EV[1], "source_key": "text/s=usda_wasde/document.json",
                "char_start": 5120, "char_end": 5208, "offset_kind": "exact_ws"}]
    s = _structured("Record corn prices occurred in August 2012 on the drought [1].",
                    [{"ref": "1", "source": "usda_wasde", "date": "2012-08-10", "note": ""}])
    rep = vf.verify_citations(s, ev_with, [])
    r = rep["resolved"]["1"]
    assert r["char_start"] == 5120 and r["char_end"] == 5208 and r["offset_kind"] == "exact_ws"
    s2 = _structured("Record corn prices occurred in August 2012 on the drought [2].",
                     [{"ref": "2", "source": "usda_wasde", "date": "2012-08-10", "note": ""}])
    r2 = vf.verify_citations(s2, EV, [])["resolved"]["2"]
    assert r2["char_start"] is None and r2["char_end"] is None and r2["offset_kind"] is None


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


# -- Stage-1 RCA fixes (2026-07-11): sign-blind prose vs signed delta rows; suffixed-handle leak --
def test_number_backing_is_sign_insensitive():
    """The Stage-1 signature: prose narrates unsigned magnitudes ('fell 14.573 MMT') while injected
    decline delta/pct rows are SIGNED (-14.573) -- every narrated DECLINE stripped while identical
    gains passed. Magnitude backs magnitude; direction lives in the prose verb."""
    from leviathan.graphrag import verify as vf
    decline = [{"query": {"metric": "exports_mt_delta"}, "rows": [{"value": "-14.573"}]}]
    assert vf._check_number_handle("Russian exports fell 14.573 MMT [N1]", 1, decline) is None
    gain = [{"query": {"metric": "exports_mt_delta"}, "rows": [{"value": "11.216"}]}]
    assert vf._check_number_handle("US exports rose 11.216 MMT [N1]", 1, gain) is None
    # a number matching NO row magnitude still strips -- abs() must not widen into backfill
    assert vf._check_number_handle("exports fell 9.9 MMT [N1]", 1, decline) == "number_mismatch"


def test_num_matches_own_row_sign_insensitive():
    """The legacy own-row bridge is also magnitude-based: 'down 5.058 million' vs its own -5058000 row."""
    from leviathan.graphrag import verify as vf
    assert vf._num_matches([5.058], [-5058000.0])
    assert not vf._num_matches([9.9], [-5058000.0])


def test_suffixed_handle_variants_strip_not_leak():
    """Model-minted variants like [E1b] must be CONSUMED by the handle regex (checked + strippable),
    never left as literal reader-facing text (Stage-1 q7: fabricated variants leaked)."""
    from leviathan.graphrag import verify as vf
    structured = {"tldr": "x.", "mechanism": "The ratio fell sharply [E1b].", "sources": []}
    rep = vf.verify_citations(structured, [], [])
    assert "[E1b]" not in structured["mechanism"]                   # consumed (stripped), not leaked
    assert rep["checked"] >= 1


# -- W3 RCA: GRAPHRAG_STRIP_AUDIT captures stripped SENTENCE TEXT (flag-gated, capture-only) -----------
def test_strip_audit_on_records_rule_field_and_text(monkeypatch):
    """Flag ON: a field with one backed [N] sentence + one unbacked computed-magnitude sentence yields a
    strip_audit entry naming the rule (number_unbacked), the field, and the stripped sentence text."""
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    # sentence A: fully backed (keeps its handle). sentence B: 31.4M backs N1 but the '18%' free-rides.
    s = _structured("Ending stocks were 31.4 million MT [N1]. Exports climbed 31.4 million MT [N1], up 18%.",
                    [])
    rep = vf.verify_citations(s, EV, NUMS)
    assert s["tldr"].count("[N1]") == 1                            # only the free-riding sentence strips
    audit = rep["strip_audit"]
    assert len(audit) == 1
    entry = audit[0]
    assert entry["rule"] == "number_unbacked" and entry["field"] == "tldr"
    assert "up 18%" in entry["text"]                               # the stripped sentence text is captured
    assert 18.0 in entry["numbers"]                                # offending free-riding magnitude captured
    assert 1.0 not in entry["numbers"]                            # the [N1] handle digit is NOT a magnitude


def test_strip_audit_off_absent_and_behavior_byte_identical():
    """Flag OFF (default): no strip_audit key, and the report/prose are exactly what the existing
    fabricated-attribution test pins -- capture is completely inert when unset."""
    s = _structured(
        "Tariff escalation concentrates Chinese buying on Brazilian beans, documented near the as-of [1].",
        [{"ref": "1", "source": "usda_gain_soybean_oil", "date": "2026-03-31", "note": ""}])
    rep = vf.verify_citations(s, EV, [])
    assert "strip_audit" not in rep                                 # no key when the flag is unset
    assert "[1]" not in s["tldr"]                                   # identical strip decision as before
    assert rep["stripped"] == 1 and rep["by_rule"].get("no_lexical_overlap") == 1


def test_strip_audit_on_captures_field_and_foreign_regime(monkeypatch):
    """The audit spans both prose fields and the foreign-regime strip path, tagging each with its field."""
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    s = _structured("The bullish_protein_squeeze regime also looms on the drought [2].",
                    [{"ref": "2", "source": "usda_wasde", "date": "2012-08-10", "note": ""}],
                    mechanism="Freight rates spiked on Panama canal restrictions [9].")
    rep = vf.verify_citations(s, EV, [], foreign_names={"bullish_protein_squeeze"})
    rules = {(e["field"], e["rule"]) for e in rep["strip_audit"]}
    assert ("tldr", "foreign_regime_name") in rules                 # cross-contract name, tldr field
    assert ("mechanism", "undeclared_unsupported") in rules        # unsupported handle, mechanism field


# -- W3 F1: verifier time/name-token exemptions (years, year-range tails, letter-glued codes) ----------
# These pin the RCA's DOMINANT false-positive class: legit citations stripped because a bare year, a
# range tail, or an alphanumeric code was mistaken for an unbacked magnitude. The extractor exempts them
# so the strip DECISION and the strip_audit numbers list agree; fabricated magnitudes still strip.
def test_claim_extractor_exempts_years_ranges_codes_keeps_magnitudes():
    from leviathan.graphrag import verify as vf
    # standalone calendar years exempt; comma/decimal-punctuated look-alikes stay magnitudes
    assert vf._claim_numbers_in("in 2007 and 2023 exports climbed") == []
    assert vf._claim_numbers_in("the MY2021 baseline held") == []           # MY2021: letter-glued -> exempt
    assert 2021.0 in vf._claim_numbers_in("held 2,021 MT")                  # comma -> a magnitude, not a year
    assert 2010.5 in vf._claim_numbers_in("index at 2010.5 points")        # decimal -> a magnitude
    # year RANGE: the leading year AND the trailing short token both exempt; the magnitude survives
    assert vf._claim_numbers_in("the 1998-99 devaluation cut exports 3.2 MMT") == [3.2]
    assert vf._claim_numbers_in("the 1998/99 season") == []
    assert vf._claim_numbers_in("the 1998–99 season") == []           # en-dash variant
    # letter-glued codes never yield their digits, even multi-char ones
    assert vf._claim_numbers_in("a formal B40 push and a T2 GAIN report on CO2") == []
    # a genuine magnitude with a unit is always a claim
    assert vf._claim_numbers_in("exports hit 23.5 MMT") == [23.5]
    # a bare '99' NOT in a range is still a magnitude (e.g. a percent)
    assert vf._claim_numbers_in("up 99% on the year") == [99.0]


def test_year_valued_magnitude_with_unit_is_a_claim():
    """Review fold (major #2): a 4-digit token IMMEDIATELY followed by a unit is a MAGNITUDE, not a year --
    'exports hit 1950 MMT' was the named refutation case. A bare year without a unit stays exempt."""
    from leviathan.graphrag import verify as vf
    assert vf._claim_numbers_in("exports were 2010 MT") == [2010.0]
    assert vf._claim_numbers_in("exports hit 1950 MMT") == [1950.0]
    assert vf._claim_numbers_in("the drought of 1950 cut area") == []


def test_range_tail_exemption_is_year_scoped_and_short():
    """Review fold (BLOCKER): the range-tail exemption applies ONLY to a 1-2 digit tail after a YEAR
    prefix -- a fabricated 4-digit upper bound of an ordinary range must stay a claim."""
    from leviathan.graphrag import verify as vf
    assert vf._claim_numbers_in("band 5900-6100 MT") == [5900.0, 6100.0]   # non-year range: BOTH claims
    assert vf._claim_numbers_in("code 12345-99 seen") == [12345.0, 99.0]   # non-year prefix: tail counts
    assert vf._claim_numbers_in("the 1998-99 devaluation") == []           # true year range stays exempt
    decline = [{"query": {"metric": "exports_mt"}, "rows": [{"value": "5900"}]}]
    sent = "exports ranged 5900-9999 MT [N1]"
    assert vf._check_number_handle(sent, 1, decline) is not None           # fabricated 9999 still strips


def test_sentence_with_only_year_and_backed_magnitude_survives_with_handle():
    """The RCA signature: '...2010 wheat ban collapsed shipments by roughly 14.6 MMT [N3]' -- 14.6 backs
    its row (-14.573, sign-insensitive, within 1pct) and '2010' is a year -> the whole sentence + its
    legit handle survive."""
    from leviathan.graphrag import verify as vf
    decline = [{"query": {"metric": "exports_mt_delta"}, "rows": [{"value": "-14.573"}]}]
    sent = "Russia's 2010 wheat export ban collapsed Russian shipments by roughly 14.6 MMT [N1]"
    assert vf._check_number_handle(sent, 1, decline) is None


def test_sentence_with_only_years_and_codes_no_magnitude_survives():
    """A handled sentence whose ONLY numerals are years + a letter-code and a backed figure keeps its
    handle -- no free-riding magnitude remains to strip."""
    from leviathan.graphrag import verify as vf
    calls = [{"rows": [{"value": "5900"}]}]
    assert vf._check_number_handle("in 2007 and 2023 a B40 push lifted exports to 5900 [N1]", 1, calls) is None


def test_year_range_tail_does_not_trigger_unbacked():
    """'the 1998-99 devaluation ... 3.2 MMT [N1]' with 3.2 injected: the '99' tail must not free-ride,
    and the real 3.2 magnitude must NOT be swallowed by the exemptions."""
    from leviathan.graphrag import verify as vf
    calls = [{"rows": [{"value": "3.2"}]}]
    assert vf._check_number_handle("the 1998-99 devaluation cut exports 3.2 MMT [N1]", 1, calls) is None
    # 3.2 is still extracted as a claim: with only a '99' row it fails its cited-row check -> strips
    assert vf._check_number_handle("the 1998-99 devaluation cut exports 3.2 MMT [N1]", 1,
                                   [{"rows": [{"value": "99"}]}]) == "number_mismatch"


def test_fabricated_magnitude_with_valid_handle_still_strips():
    """The anti-fabrication contract holds: a fabricated magnitude strips even when years/codes share the
    sentence and the handle index is valid -- exemptions never shield a real magnitude."""
    from leviathan.graphrag import verify as vf
    calls = [{"rows": [{"value": "5900"}]}]
    # 23.5 != the cited row 5900 -> mismatch; the 2010 year and B40 code do not shield it
    assert vf._check_number_handle("in 2010 a B40 push sent exports to 23.5 MMT [N1]", 1,
                                   calls) == "number_mismatch"
    # a free-riding fabricated 23.5 ALONGSIDE the backed 5900 -> the all-rows guard fires (number_unbacked)
    assert vf._check_number_handle("in 2010 a B40 push lifted exports to 5900 [N1], up 23.5%", 1,
                                   calls) == "number_unbacked"


def test_strip_audit_numbers_agree_with_strip_decision_on_exemptions(monkeypatch):
    """Extractor-level exemption means the strip_audit `numbers` list carries the SAME magnitudes the
    strip decision saw: the year and the letter-code are absent; the backed 5900 and free-riding 23.5
    (the reason for the strip) are present."""
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    s = _structured("In 2010 a B40 push lifted exports to 5900 [N1], up 23.5%.", [])
    calls = [{"rows": [{"value": "5900"}]}]
    rep = vf.verify_citations(s, EV, calls)
    assert "[N1]" not in s["tldr"]                                  # stripped: 23.5 free-rides
    audit = rep["strip_audit"]
    assert len(audit) == 1 and audit[0]["rule"] == "number_unbacked"
    nums = audit[0]["numbers"]
    assert 23.5 in nums and 5900.0 in nums                          # the real magnitudes captured
    assert 2010.0 not in nums and 40.0 not in nums                 # year + B40's '40' exempted, not listed


# -- T2b Lane-B RCA (2026-07-28): the NUMBERS-ROW LEDGER DECLARATION is not a fabricated citation ------
# answer.py types the ledger `ref` as {"type": "integer"} and _SYSTEM instructs "handle [E1] -> {ref: 1}
# (an integer, not the string \"E1\")". So a model that correctly declares the [N] rows it cited emits
# {ref: 3} for [N3] -- which the ledger loop's `ref.startswith("N")` skip can never recognise. Before the
# fix each such declaration was matched against the EVIDENCE list, failed, and was charged
# fabricated_citation (19 of 50 strips on gate run 94468a0b) while ALSO deleting the reader's Sources
# entry. Worse, it wrote resolved[ref] = [] and so stripped a LEGITIMATE [E] handle sharing the integer.
_PR_NUMS = [
    {"query": {"table": "gold_pattern_records", "metric": "recorded_firings"}, "rows": [{"value": 9}]},
    {"query": {"table": "silver_esr", "metric": "outstanding_sales_1000mt"}, "rows": [{"value": 0.0}]},
    {"query": {"table": "silver_esr", "metric": "wow_change"}, "rows": [{"value": -251.438}]},
]


def test_integer_ledger_ref_for_a_cited_N_handle_is_not_a_fabrication():
    """The measured regression: three [N] rows declared with the schema-mandated bare-integer refs."""
    s = _structured("Weekly export pace is 0 [N2]. It fell 251.438 [N3].",
                    [{"ref": 1, "source": "gold_pattern_records", "date": "2026-07-25"},
                     {"ref": 2, "source": "silver_esr", "date": "2026-07-25"},
                     {"ref": 3, "source": "silver_esr", "date": "2026-07-25"}],
                    mechanism="## The record\nThe engine records 9 firings [N1].")
    rep = vf.verify_citations(s, EV, _PR_NUMS)
    assert rep["by_rule"].get("fabricated_citation", 0) == 0        # a numbers row is not a bad document
    assert rep["stripped"] == 0
    assert [x["ref"] for x in s["sources"]] == [1, 2, 3]            # the ledger survives for rendering
    assert "[N1]" in s["mechanism"] and "[N2]" in s["tldr"]


def test_number_declaration_does_not_clobber_a_real_evidence_ref_on_the_same_integer():
    """E/N namespaces COLLIDE under an integer ref: [E1] and [N1] both declare {ref: 1}. The numbers
    entry must not overwrite the resolved evidence item and strip a citation of a real dated document."""
    s = _structured("Record corn prices occurred in August 2012 on the drought [E1]. The engine "
                    "records 9 firings [N1].",
                    [{"ref": 1, "source": "usda_wasde", "date": "2012-08-10"},
                     {"ref": 1, "source": "gold_pattern_records", "date": "2026-07-25"}])
    rep = vf.verify_citations(s, EV, _PR_NUMS)
    assert rep["by_rule"].get("fabricated_citation", 0) == 0
    assert "[E1]" in s["tldr"] and "[N1]" in s["tldr"]              # BOTH handles survive
    assert rep["resolved"]["1"]["source"] == "usda_wasde"           # the real item still resolves


def test_invented_document_still_strips_when_the_index_is_not_used_as_a_number():
    """The anti-fabrication contract is intact: an unmatched ledger entry whose integer is NEVER written
    as [N<idx>] in the prose is still a fabricated citation."""
    s = _structured("Prices rose [3].",
                    [{"ref": 3, "source": "reuters_live_wire", "date": "2026-01-01"}])
    rep = vf.verify_citations(s, EV, _PR_NUMS)
    assert rep["by_rule"].get("fabricated_citation", 0) >= 1         # ledger entry + the prose handle
    assert s["sources"] == [] and "[3]" not in s["tldr"]


def test_number_declaration_beyond_the_injected_call_count_still_strips():
    """A ledger ref that indexes PAST the injected rows is not a declaration of anything -- it strips
    (the ledger cannot launder an out-of-range handle into a free pass)."""
    s = _structured("The ratio was 9 [N9].",
                    [{"ref": 9, "source": "gold_pattern_records", "date": "2026-07-25"}])
    rep = vf.verify_citations(s, EV, _PR_NUMS)                      # only 3 calls injected
    assert rep["by_rule"].get("fabricated_citation", 0) == 1
    assert s["sources"] == []


def test_zero_row_backs_a_zero_claim_the_F8_materialized_zero():
    """T2b Lane-B RCA: a citable ZERO is the whole point of the pattern-records F8 doctrine ("the engine
    has recorded no firing on any of its N sweeps") and the deck's ESR pace rows are literally 0.0.
    _num_matches guarded BOTH of its scale tests on truthiness (`if b and ...` / `if a and ...`), so a 0
    claim against a 0 row fell through every arm and was charged number_mismatch."""
    calls = [{"rows": [{"value": 0}]}]
    assert vf._check_number_handle("weekly export pace reads 0 [N1]", 1, calls) is None
    assert vf._num_matches([0.0], [0.0]) is True


def test_zero_is_not_a_wildcard_in_either_direction():
    """0 matches only 0 (the _num_backed rule): a zero row must not back a non-zero claim, and a zero
    claim must not be backed by a non-zero row."""
    assert vf._num_matches([5.0], [0.0]) is False
    assert vf._num_matches([0.0], [5.0]) is False
    assert vf._check_number_handle("exports were 5.0 MMT [N1]", 1,
                                   [{"rows": [{"value": 0}]}]) == "number_mismatch"


# -- T2b Lane-B RCA: the DAY of a date is not a magnitude ---------------------------------------------
# Measured on the T2b deck's strip audit: 25.0 -- the day out of "as of 25 July 2026" and "2026-07-25" --
# was the offending magnitude in 4 of the 10 audited strips, killing sentences whose REAL figures were
# all backed. orchestrator._verify_numbers_answer already scrubs these tokens; this is the same rule.
def test_date_day_component_is_not_a_claim_magnitude():
    assert vf._claim_numbers_in("first recorded 2026-05-30.") == []
    assert vf._claim_numbers_in("the engine recorded 0 sweeps as of 2026-07-25 [N3]") == [0.0]
    assert vf._claim_numbers_in("verdict as of 25 July 2026 declined; the streak stands at 2") == [2.0]
    assert vf._claim_numbers_in("on July 25, 2026 stocks were 31.4 MMT") == [31.4]


def test_day_exemption_never_shields_a_unit_suffixed_magnitude():
    """A short number carrying a UNIT is a claim even when a month name follows it."""
    assert vf._claim_numbers_in("exports hit 25 MMT in May") == [25.0]
    assert vf._claim_numbers_in("held 2,021 MT") == [2021.0]
    assert vf._claim_numbers_in("ranged 5900-9999 MT") == [5900.0, 9999.0]
    assert vf._claim_numbers_in("exports rose 12. Stocks fell 8.") == [12.0, 8.0]


def test_pattern_records_preface_only_the_denominator_is_unbacked():
    """The engine's OWN preface sentence: with the day exempted, 9 and 156 are the only magnitudes left,
    so the strip decision now turns solely on whether the ledger DENOMINATOR (156, carried on the row as
    `sweeps_total`, never as `value`) is collected -- which is the remaining, separately-owned defect."""
    sent = ("The engine has recorded export_pace on CBOT corn firing on 9 of 156 weekly replay "
            "asofs [N1], first recorded 2026-05-30.")
    assert vf._claim_numbers_in(sent) == [9.0, 156.0]


# -- W4 A/B RCA (2026-07-31): number_mismatch is FAIL-CLOSED --------------------------------------------
# The handle-only strip removed the CITATION and left the FABRICATED FIGURE on the page, now reading as the
# analyst's own number. The eval judge scored four such fabrications on ONE row while by_rule already carried
# number_mismatch=3 -- the verifier SAW them and published them anyway. Default policy now: rewrite the
# figure from the cited row when the sentence is unambiguous, delete the whole sentence otherwise.
def _calls(rows: dict, unit: str | None = None) -> list:
    """number_calls long enough for the highest cited [N] index; a listed index carries exactly ONE row.

    CYCLE-9 (2026-08-08): `unit` is new and it is REQUIRED to reach the repair path at all. Under the
    repair-eligibility ALLOWLIST an unknown unit class on either side is INELIGIBLE (fail closed), so a
    unit-less fixture -- which is what this helper always built -- now DROPS its sentence instead of
    rewriting it. Every pin below that is about the repair MECHANISM (which pool sources the value, the
    sign discipline, comma grouping, the audit rule name, the mode knob) names its unit so the mechanism
    is still exercised; every pin that is about the unit-less CONTRACT itself now pins the drop."""
    row = (lambda v: {"value": v, **({"unit": unit} if unit else {})})
    return [{"query": {"metric": "m"}, "rows": ([row(rows[i])] if i in rows else [])}
            for i in range(1, max(rows) + 1)]


def _window_calls(spec: dict) -> list:
    """THE RUN-TIME SHAPE that escaped (2026-08-01 RCA). A cascade era-window call carries the WHOLE
    window's rows while its rendered line prints ONE endpoint: spec maps [N] index -> (shown, decoy), so
    `rows` holds both the endpoint and the member row the model quoted, and `shown` holds the endpoint
    alone. Under the all-rows pool the decoy cleared the citation; under shown-binding it cannot."""
    return [{"query": {"metric": "m"},
             "rows": ([{"value": spec[i][0], "unit": "degC"}, {"value": spec[i][1], "unit": "degC"}]
                      if i in spec else []),
             **({"shown": [spec[i][0]]} if i in spec else {})}
            for i in range(1, max(spec) + 1)]


def test_judge_fixture_transcription_fabrications_now_DROP_never_repair_cycle10():
    """CYCLE-10 (2026-08-08) -- THE TERMINATION BRANCH, PINNED AT THE FIXTURE THAT DEFINED THE REPAIR.

    This pin used to read `..._are_repaired_in_place` and assert the TRUE value landing in the prose with
    the handle intact. That capability is deleted: three recorded repair ops across gates 6-7 produced
    three corrupted sentences, the last of them through a clean pass of all four cycle-9 allowlist clauses
    (see `verify._num_repair`). Every one of these fixtures is now a whole-sentence DROP -- the charge is
    identical, the remedy is the one this module always gave for ambiguity, and no numeral is written.

    THE COST IS REAL AND IS THE POINT: these three ARE genuine transcription errors whose true value was
    knowable. The reader loses the sentence instead of receiving a figure the verifier minted."""
    cases = [
        ("The index sat at -0.693675 z [N14].", _calls({14: -2.1035}, unit="sigma")),
        ("The index sat at -1.78323 z [N15].", _calls({15: -1.4097}, unit="sigma")),
        ("It peaked at +2.47 degC [N1].", _calls({1: 2.75}, unit="degC")),
    ]
    for prose, calls in cases:
        s = _structured(prose, [])
        rep = vf.verify_citations(s, [], calls)
        assert s["tldr"] == "", prose                          # the sentence goes, whole
        assert rep["stripped"] == 1, prose                     # ...and it is CHARGED, never laundered
        assert rep["repaired"] == 0 and rep["repairs"] == [], prose
        assert rep["by_rule"] == {"number_mismatch": 1}, prose
        assert "number_mismatch_repaired" not in rep["by_rule"], prose
    # ...and the two-handle member of the same family drops exactly as it did under cycle-9 clause (a)
    s2 = _structured("Anomalies ran -0.72 degC [N12][N4].", [])
    rep2 = vf.verify_citations(s2, [], _calls({4: 0.06, 12: 0.06}, unit="degC"))
    assert s2["tldr"] == "" and rep2["repaired"] == 0
    assert rep2["by_rule"] == {"number_mismatch": 2}


def test_judge_fixtures_are_charged_even_when_the_call_carries_the_member_row():
    """(d) The SAME figures in the shape they actually shipped in: the cited call carries the true endpoint
    AND the member row the model lifted, and only the endpoint was displayed. Under the old all-rows pool
    every one of these cleared uncharged (measured: rep_w4_on.md renders all four with handles intact);
    bound to `shown` they charge and repair to the displayed value.
    CYCLE-9: the '[N12][N4]' member of the family drops under allowlist clause (a) -- see the pin above.
    CYCLE-10: the CHARGE is what this pin is for and the charge is UNMOVED -- every one of these shapes is
    still convicted number_mismatch against the `shown` pool, which is the property `_mismatch_pool` exists
    to hold. What changed is only the remedy: the sentence is dropped instead of rewritten."""
    cases = [
        ("The index sat at -0.693675 degC [N14].", _window_calls({14: (-2.1035, -0.693675)})),
        ("The index sat at -1.78323 degC [N15].", _window_calls({15: (-1.4097, -1.78323)})),
        ("It peaked at +2.47 degC [N1].", _window_calls({1: (2.75, 2.47)})),
    ]
    for prose, calls in cases:
        s = _structured(prose, [])
        rep = vf.verify_citations(s, [], calls)
        assert s["tldr"] == "", prose                          # charged on `shown`, dropped whole
        assert rep["by_rule"] == {"number_mismatch": 1}, prose
        assert rep["stripped"] == 1 and rep["repairs"] == [], prose
    # and the proof it is the POOL that changed: the same fixtures go silent on the legacy pool
    import os as _os
    _os.environ["GRAPHRAG_VERIFY_NUM_POOL"] = "all"
    try:
        for prose, calls in cases:
            s = _structured(prose, [])
            rep = vf.verify_citations(s, [], calls)
            assert s["tldr"] == prose and rep["by_rule"] == {}, prose   # the escape, reproduced
    finally:
        _os.environ.pop("GRAPHRAG_VERIFY_NUM_POOL", None)


# -- the DILUTION fixture: one call, a whole window of rows, one displayed endpoint --------------------
# CYCLE-9: the rows carry their `degC` unit, which the served cascade rows have always carried and this
# fixture never bothered to state. Under the repair-eligibility allowlist an unknown source class is
# ineligible, so an unstated unit would make this pin about clause (b) instead of about the POOL.
_DILUTION = [{"query": {"table": "gold_weather_z", "metric": "oni_anomaly"},
              "rows": [{"value": 0.06, "unit": "degC"}, {"value": -0.72, "unit": "degC"},
                       {"value": 0.31, "unit": "degC"}],                       # the Jan-Jun window series
              "shown": [0.06]}]                                                # what the [N1] line printed


def test_window_row_dilution_is_charged_and_DROPPED_cycle9_review():
    """(a) The measured escape in miniature. -0.72 IS a row on the cited call -- it is the January member
    of a Jan-Jun window -- but the panel line printed 0.06, so narrating -0.72 as the window's reading is a
    fabrication the reader was never shown. THE CHARGE is what this pin exists for and it is unchanged.

    CYCLE-9 REVIEW (2026-08-08), MAJOR 4 -- THE REPAIR HALF IS RETIRED, INVERTED IN PLACE. This fixture
    used to publish "The window read -0.06 degC": a MINUS sign the row denies (`shown` is +0.06) wrapped
    around a magnitude 12x from what the page said. Clause (e) refuses both -- an explicit prose sign the
    row contradicts, and a replacement outside one order of magnitude of the numeral it replaces -- so the
    sentence now takes the fail-closed drop. The `shown`-binding discipline this family was built for is
    unaffected: which POOL sources a repair is pinned below, on a fixture whose sign and scale agree."""
    s = _structured("The window read -0.72 degC [N1].", [])
    rep = vf.verify_citations(s, [], _DILUTION)
    assert s["tldr"] == ""                                         # dropped whole, not rewritten
    assert rep["by_rule"].get("number_mismatch") == 1
    assert rep["by_rule"].get("number_mismatch_repaired") is None
    assert rep["corrected"] == 0 and rep["stripped"] == 1


def test_window_row_dilution_clears_under_the_legacy_pool(monkeypatch):
    """(b) GRAPHRAG_VERIFY_NUM_POOL=all reproduces the escape exactly -- pinned so the rollback is proven
    to be a rollback, and so the regression can never be re-introduced silently."""
    monkeypatch.setenv("GRAPHRAG_VERIFY_NUM_POOL", "all")
    s = _structured("The window read -0.72 degC [N1].", [])
    rep = vf.verify_citations(s, [], _DILUTION)
    assert s["tldr"] == "The window read -0.72 degC [N1]."      # untouched: -0.72 matched a member row
    assert rep["by_rule"] == {} and rep["stripped"] == 0 and rep["corrected"] == 0


def test_call_without_shown_keeps_the_all_rows_behaviour():
    """(c) The agent lane and every legacy fixture emit calls with NO `shown` key -- they fall back to the
    full row list, so a figure matching any row still clears and a figure matching none still charges."""
    agent = [{"query": {"metric": "m"}, "rows": [{"value": 0.06}, {"value": -0.72}, {"value": 0.31}]}]
    ok = _structured("The window read -0.72 degC [N1].", [])
    assert vf.verify_citations(ok, [], agent)["by_rule"] == {}          # no shown -> all rows -> clears
    bad = _structured("The window read -9.9 degC [N1].", [])
    rep = vf.verify_citations(bad, [], agent)
    assert rep["by_rule"].get("number_mismatch") == 1                   # 3 pool values -> no repair, drop
    assert bad["tldr"] == ""


def test_shown_pool_drives_the_charge_and_no_repair_can_follow_it_cycle10():
    """The pool is the CHARGE's pool and there is no longer a second reader of it. This pin used to assert
    that a rewrite sourced from `shown` (`_num_repair(...)[2] == "0.06"`) rather than from `rows`; CYCLE-10
    deleted the rewrite, so what survives is the half that was always the point -- `_mismatch_pool` binds
    the check to the value the panel line PRINTED, and the decoy member row neither clears the charge nor
    can be spliced anywhere."""
    assert vf._mismatch_pool(_DILUTION[0], vf._row_vals(_DILUTION[0])) == [0.06]
    assert vf._num_repair("The window read 0.31 degC [N1].", 1, _DILUTION) is None
    s = _structured("The window read 0.31 degC [N1].", [])
    rep = vf.verify_citations(s, [], _DILUTION)
    assert s["tldr"] == "" and rep["by_rule"] == {"number_mismatch": 1} and rep["repairs"] == []
    # >1 shown value (the su_ratio line prints endpoint + baseline + delta): same answer, as it always was
    multi = [{"rows": [{"value": 8.1}], "shown": [8.1, 9.4, -1.3]}]
    assert vf._num_repair("Stocks-to-use eased to 7.2% [N1].", 1, multi) is None


def test_no_sign_question_survives_because_no_numeral_is_written_cycle10():
    """The prose sign was the last thing a repair had to reason about: `_CLAIM_NUM` cannot see a minus, so
    the row's MAGNITUDE went in and the page's sign stayed. CYCLE-10 removes the question with the writer
    -- the sentence is dropped and the reader's own sign is never re-argued because nothing is spliced."""
    s = _structured("The anomaly read -0.693675 z [N1].", [])
    rep = vf.verify_citations(s, [], _calls({1: -2.1035}, unit="sigma"))
    assert s["tldr"] == "" and rep["repaired"] == 0 and rep["repairs"] == []
    assert rep["by_rule"] == {"number_mismatch": 1}


def test_audit_entry_names_the_mismatch_rule_never_a_repaired_one_cycle10(monkeypatch):
    """The audit record survives the deletion -- it just never says 'repaired' again. `strip_audit` carries
    the drop under `number_mismatch`, with the offending sentence and its magnitudes, exactly as every
    other rule records itself."""
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    s = _structured("It peaked at +2.47 degC [N1].", [])
    rep = vf.verify_citations(s, [], _calls({1: 2.75}, unit="degC"))
    assert [e["rule"] for e in rep["strip_audit"]] == ["number_mismatch"]
    assert rep["strip_audit"][0]["field"] == "tldr" and "2.47" in rep["strip_audit"][0]["text"]
    assert 2.47 in rep["strip_audit"][0]["numbers"]


def test_ambiguous_multi_number_sentence_is_deleted_whole_with_its_other_handles():
    """TWO claim numbers -> no rewrite can be made without guessing which numeral is the fabrication, so the
    sentence goes. The innocent [N2] rides out with it: dropped ONCE, counted ZERO times."""
    calls = _calls({1: 9.9, 2: 2.2, 3: 5.5})                   # N3 backs the 5.5 so N2 is otherwise clean
    s = _structured("Stocks held steady. Exports ran 5.5 MMT [N1] against a 2.2 MMT [N2] baseline. "
                    "Prices firmed.", [])
    rep = vf.verify_citations(s, [], calls)
    assert s["tldr"] == "Stocks held steady. Prices firmed."   # no doubled space, no orphan punctuation
    assert rep["checked"] == 2 and rep["stripped"] == 1        # ONE offending handle charged, not two
    assert rep["by_rule"] == {"number_mismatch": 1}            # the existing rule key, so by_rule compares
    # the same sentence FIRST in the field: it takes the following space, never leaving a leading indent
    s2 = _structured("Exports ran 5.5 MMT [N1] against a 2.2 MMT [N2] baseline. Prices firmed.", [])
    vf.verify_citations(s2, [], calls)
    assert s2["tldr"] == "Prices firmed."


def test_a_sibling_backed_figure_is_never_rewritten_only_the_miscitation_goes():
    """One claim number, one mismatched handle and one MATCHING handle in the same sentence. The matching
    handle MATERIALIZES the figure, so the figure is not a fabrication and the fail-closed rewrite must not
    touch it -- the mis-citing handle alone is stripped and the sentence survives intact.

    r5 RCA (2026-08-01). This case previously repaired: -0.72 was rewritten to [N1]'s 0.06 while [N2] --
    which backs 0.72 -- stayed attached to a figure that was no longer its own. Rendered, that shipped a
    handle contradicting itself inside ONE deck (ol_cocoa_thin_record '+0.47 degC ... [N3] [N4]' against
    ol_bait_bare_target_demanded '+5 degC [N3]', both citing the same +0.98 degC ONI call). A clean handle
    still never drags its sentence down -- it now PROTECTS the figure instead of being dragged along."""
    s = _structured("The anomaly reached -0.72 degC [N1][N2].", [])
    rep = vf.verify_citations(s, [], _calls({1: 0.06, 2: 0.72}))
    assert s["tldr"] == "The anomaly reached -0.72 degC [N2]."   # figure kept, only [N1] removed
    assert rep["stripped"] == 1 and rep["corrected"] == 0
    assert rep["by_rule"] == {"number_mismatch": 1}


def test_sibling_backing_needs_a_real_backer_not_just_a_second_handle():
    """The guard reads the sibling's POOL, not its presence: two handles that both miss the numeral leave it
    unbacked, so the four judge fixtures' shape (N12/N4 both on 0.06, prose says -0.72) still repairs."""
    assert vf._sibling_backed("Anomalies ran -0.72 degC [N12][N4].", 12, _calls({4: 0.06, 12: 0.06})) is False
    assert vf._sibling_backed("The anomaly reached -0.72 degC [N1][N2].", 1, _calls({1: 0.06, 2: 0.72})) is True
    # two claim numerals -> nobody can say which one the charged handle meant: the drop keeps the sentence
    assert vf._sibling_backed("Exports ran 5.5 MMT [N1] against 2.2 MMT [N2].", 1,
                              _calls({1: 9.9, 2: 2.2})) is False


# -- r5 RCA (2026-08-01): the UNIT guard on the repair source ------------------------------------------
# The verifier MINTED a hallucination. cascade._pace_legs binds a pace_streak call's `shown` to the streak
# RUN LENGTH with unit '<grain>s' (cascade.py:1420), so a sentence citing the streak next to an ONI level
# charged the level's numeral against a pool of [5] and rewrote "+0.98 degC" to "+5 degC" -- a physically
# impossible anomaly, published in ol_bait_bare_target_demanded and caught by the judge, not the verifier.
def _streak_call(run: int, grain: str = "month", metric: str = "oni_anomaly") -> dict:
    """The RUN-TIME shape cascade._pace_synth(kind='pace_streak') emits: one row, the count, a grain unit."""
    return {"query": {"table": "gold_weather_z", "metric": f"{metric}_pace_streak"},
            "rows": [{"value": run, "unit": f"{grain}s"}], "shown": [float(run)]}


def test_a_run_count_never_repairs_a_temperature_the_r5_plus5_degc():
    """The measured defect in miniature, with NO sibling to fall back on: the streak is the only handle, the
    charge is real, and the remedy must be the fail-closed DROP -- never '+5 degC'."""
    calls = [_streak_call(5)]
    s = _structured("The ONI anomaly reached +0.98 degC over the run [N1].", [])
    rep = vf.verify_citations(s, [], calls)
    assert "+5" not in s["tldr"] and s["tldr"] == ""            # the sentence goes, the count never lands
    assert rep["by_rule"] == {"number_mismatch": 1} and rep["corrected"] == 0
    assert vf._num_repair("The ONI anomaly reached +0.98 degC over the run [N1].", 1, calls) is None


def test_the_count_refusal_survives_a_call_that_lost_its_unit():
    """Belt and braces, now structural: the streak call had its own COUNT tell (`_pace_streak`) and its own
    unit, and CYCLE-10 deleted both readers along with the rewrite. The refusal no longer depends on any
    tell being present -- `_call_unit_class` is gone and the answer is the drop either way."""
    calls = [{"query": {"metric": "oni_anomaly_pace_streak"}, "rows": [{"value": 5}], "shown": [5.0]}]
    assert not hasattr(vf, "_call_unit_class")             # the class fence went with what it fenced
    assert vf._num_repair("The anomaly reached +0.98 degC [N1].", 1, calls) is None


def test_a_count_no_longer_repairs_a_count_either_cycle10():
    """THE HONEST COST, PINNED. A miscounted run in a count sentence was the one shape the r5 unit guard
    deliberately kept repairing -- same class, same dimension, a real transcription error. It DROPS now.
    Cycle-9 already recorded why a same-class certificate is not certification (gate-7's `0.6 z` ->
    `-0.6267 z` passed exactly that test), so 'the classes agree' buys nothing any more."""
    s = _structured("The metric rose in each of the last 4 months [N1].", [])
    rep = vf.verify_citations(s, [], [_streak_call(5)])
    assert s["tldr"] == "" and rep["repaired"] == 0 and rep["repairs"] == []
    assert rep["by_rule"] == {"number_mismatch": 1}


def test_unit_foreign_replacement_is_refused_percent_row_into_a_degc_sentence():
    """The general class: cascade._delta_call(kind='pct') stamps unit '%'. Splicing it beside 'degC' would
    manufacture a figure in the wrong dimension -- and CYCLE-10 removes the splice itself, so the sentence
    goes for the same reason every other mismatched sentence now goes."""
    pct = [{"query": {"metric": "oni_anomaly_pct"}, "rows": [{"value": 18.0, "unit": "%"}], "shown": [18.0]}]
    assert vf._num_repair("The anomaly reached +0.98 degC [N1].", 1, pct) is None
    s = _structured("The anomaly reached +0.98 degC [N1].", [])
    assert vf.verify_citations(s, [], pct)["by_rule"] == {"number_mismatch": 1}
    assert s["tldr"] == ""
    # ... and a tonnage row never repairs a price
    mass = [{"rows": [{"value": 31.4, "unit": "MMT"}], "shown": [31.4]}]
    assert vf._num_repair("Cash traded at $4.20 [N1].", 1, mass) is None


def test_a_unit_compatible_replacement_is_refused_too_now_cycle10():
    """The inversion completed. Cycle-7 through cycle-9 all held 'same class in, repair out', including the
    degree-sign twin; gate-7 shipped a corruption THROUGH that clause (a `*_pace_change` signed delta into
    a slot whose own word already carried the direction, z into z). Both spellings now drop."""
    degc = [{"rows": [{"value": 2.75, "unit": "degC"}], "shown": [2.75]}]
    for prose in ("It peaked at +2.47 degC [N1].", "It peaked at +2.47 °C [N1]."):
        s = _structured(prose, [])
        rep = vf.verify_citations(s, [], degc)
        assert s["tldr"] == "", prose
        assert rep["by_rule"] == {"number_mismatch": 1}, prose
        assert rep["repaired"] == 0 and rep["repairs"] == [], prose


def test_an_unknown_unit_on_either_side_is_now_INELIGIBLE_cycle9():
    """CYCLE-9 (2026-08-08) -- THE INVERSION, PINNED AT THE SITE OF THE CONTRACT IT REPLACES.

    This pin used to read `..._never_refuses` and assert the legacy contract: "the agent lane and every
    fixture emit rows with NO unit key ... unknown -> no opinion -> repair as before". THAT is the door the
    gate-6 tldr corruption walked through. `el_nino_flag` serves unit "0/1", `_unit_class` did not know the
    token, `src_cls` came back None, and the cross-class fence -- spelled `if src_cls and tgt_cls and
    src_cls != tgt_cls` -- was SKIPPED, so a boolean was spliced into a degC slot ("at 1 degC").

    The classification helpers are UNCHANGED (an unrecognized token is still None; that is honest). What
    changed is what None BUYS at the repair site: it used to buy permission, and it now costs eligibility.
    The sentence takes the fail-closed drop every other ambiguity takes.

    CYCLE-10 (2026-08-08): the inversion is now total. The KNOWN-and-AGREEING arm this pin still carried --
    the one shape cycle-9 left repairing -- drops too, and the classification helpers it asserted against
    (`_unit_class`, `_call_unit_class`) are GONE, because gate-7's corruption came in THROUGH a known,
    agreeing pair. Unknown, known-and-disagreeing and known-and-agreeing are one answer now: drop."""
    assert not hasattr(vf, "_unit_class") and not hasattr(vf, "_call_unit_class")
    s = _structured("The index sat at -0.693675 z [N1].", [])
    rep = vf.verify_citations(s, [], _calls({1: -2.1035}))          # no unit anywhere
    assert s["tldr"] == "" and rep["repaired"] == 0
    assert rep["by_rule"] == {"number_mismatch": 1}
    # the same fixture with the source class KNOWN and AGREEING -- cycle-9 repaired this; cycle-10 drops it
    ok = _structured("The index sat at -0.693675 z [N1].", [])
    assert vf.verify_citations(ok, [], _calls({1: -2.1035}, unit="sigma"))["repaired"] == 0
    assert ok["tldr"] == ""
    # ...and a KNOWN source into an UNKNOWN slot, the same answer it already gave
    bad = _structured("The index sat at -0.693675 furlongs [N1].", [])
    assert vf._num_repair("The index sat at -0.693675 furlongs [N1].", 1,
                          _calls({1: -2.1035}, unit="sigma")) is None
    assert vf.verify_citations(bad, [], _calls({1: -2.1035}, unit="sigma"))["repaired"] == 0


def test_the_boolean_class_may_never_source_a_repair_cycle9():
    """The gate-6 covenant tldr corruption in miniature. Cycle-9 closed it by NAMING the boolean class so
    an "0/1" row could not read as unknown; CYCLE-10 closes it structurally instead -- there is no source
    for any repair, boolean or otherwise, so the named class and its lookup table are deleted. The
    fixture is kept verbatim because it is the shape that shipped, and it must stay pinned as a DROP."""
    assert not hasattr(vf, "_UNIT_CLASSES") and not hasattr(vf, "_metric_tell_class")
    flag = [{"query": {"table": "gold_weather_z", "metric": "el_nino_flag"},
             "rows": [{"value": 1, "unit": "0/1"}], "shown": [1.0]}]
    assert vf._num_repair("The ONI anomaly is at 0.98 degC [N1].", 1, flag) is None
    s = _structured("The ONI anomaly is at 0.98 degC [N1].", [])
    assert vf.verify_citations(s, [], flag)["by_rule"] == {"number_mismatch": 1}
    assert s["tldr"] == "" and "1 degC" not in s["tldr"]
    # the row that lost its unit -- cycle-9 needed the metric NAME to catch it; nothing needs to now
    bare = [{"query": {"metric": "el_nino_flag"}, "rows": [{"value": 1}], "shown": [1.0]}]
    assert vf._num_repair("The ONI anomaly is at 0.98 degC [N1].", 1, bare) is None


def test_handle_masking_survives_the_repair_deletion_cycle10():
    """`_mask_handles` was written for the repair (it needed the numeral's position AS WRITTEN) and STAYS,
    because `_sibling_backed` reads it: a handle sitting where a unit would be must not be counted as a
    claim numeral when the rescue asks whether the sentence has exactly one. The `_sentence_unit_class`
    reader that shared it was repair-only and is gone."""
    assert not hasattr(vf, "_sentence_unit_class")
    masked = vf._mask_handles("It reached 0.98 [N1] degC.")
    assert masked == "It reached 0.98      degC." and len(masked) == len("It reached 0.98 [N1] degC.")
    assert [v for _a, _b, v in vf._claim_number_spans(masked)] == [0.98]
    m2 = vf._mask_handles("Cash traded at $4.20 [N1].")
    a, b, _v = vf._claim_number_spans(m2)[0]                    # the span EXCLUDES the '$' prefix
    assert m2[a:b] == "4.20"


def test_no_repair_when_the_cited_call_carries_several_rows():
    """Two row values = no single TRUE figure to write, so the sentence is deleted rather than guessed."""
    calls = [{"query": {"metric": "m"}, "rows": [{"value": 0.06}, {"value": 0.09}]}]
    s = _structured("Anomalies ran -0.72 degC [N1].", [])
    rep = vf.verify_citations(s, [], calls)
    assert s["tldr"] == "" and rep["by_rule"] == {"number_mismatch": 1}


def test_legacy_handle_mode_restores_the_handle_only_strip(monkeypatch):
    """GRAPHRAG_VERIFY_NUM_MODE=handle: the citation goes, the figure stays -- exactly the pre-fix behaviour
    (kept as the rollback, not as a recommendation: the fabricated 2.47 is what the reader still sees)."""
    monkeypatch.setenv("GRAPHRAG_VERIFY_NUM_MODE", "handle")
    s = _structured("It peaked at +2.47 degC [N1].", [])
    rep = vf.verify_citations(s, [], _calls({1: 2.75}))
    assert s["tldr"] == "It peaked at +2.47 degC." and rep["stripped"] == 1
    assert rep["by_rule"] == {"number_mismatch": 1} and rep["corrected"] == 0


def test_any_other_value_of_the_knob_is_fail_closed(monkeypatch):
    """Only the literal 'handle' opts out; a typo, an empty string or an unset var all get the fail-closed
    default -- which CYCLE-10 makes the WHOLE-SENTENCE DROP, there being no other arm left."""
    for val in ("failclosed", "on", "", "Handle"):
        monkeypatch.setenv("GRAPHRAG_VERIFY_NUM_MODE", val)
        s = _structured("It peaked at +2.47 degC [N1].", [])
        rep = vf.verify_citations(s, [], _calls({1: 2.75}, unit="degC"))
        assert s["tldr"] == "", val
        assert rep["stripped"] == 1 and rep["repaired"] == 0, val


def test_scale_word_refuses_the_repair_and_the_sentence_goes():
    """'48.2 million MT' citing a raw 31400000 row: the numeral is denominated, the row may not be, and
    splicing '31,400,000' next to 'million' would manufacture a THIRD figure -- so no rewrite is attempted
    and the fail-closed default deletes the sentence instead."""
    calls = [{"query": {"metric": "m"}, "rows": [{"value": 31400000}]}]
    s = _structured("Ending stocks were 48.2 million MT [N1]. Prices firmed.", [])
    rep = vf.verify_citations(s, [], calls)
    assert s["tldr"] == "Prices firmed."
    assert rep["by_rule"] == {"number_mismatch": 1} and rep["corrected"] == 0


def test_large_integer_no_longer_repairs_at_all_cycle10():
    """The prose-formatting rule (comma-grouped, never 8.85e+07) was a property of a WRITER this module no
    longer has. Both arms -- the integer that used to render and the non-integer that was refused -- are
    one behaviour now: the sentence goes and no numeral is formatted anywhere."""
    mt = [{"query": {"metric": "m"}, "rows": [{"value": 88500000, "unit": "MT"}]}]   # CYCLE-9: class known
    s = _structured("Output reached 92000000 MT [N1].", [])
    rep = vf.verify_citations(s, [], mt)
    assert s["tldr"] == "" and "88,500,000" not in str(rep["repairs"])
    assert rep["corrected"] == 0 and rep["by_rule"] == {"number_mismatch": 1}
    s2 = _structured("Output reached 92000000 MT [N1].", [])
    rep2 = vf.verify_citations(s2, [], [{"query": {"metric": "m"},
                                         "rows": [{"value": 88500000.5, "unit": "MT"}]}])
    assert s2["tldr"] == "" and rep2["by_rule"] == {"number_mismatch": 1}


def test_claim_number_spans_locate_the_token_core_not_its_punctuation():
    """The span-yielding core the repair indexes through: positions are the NUMERAL's, never the sentence
    punctuation _CLAIM_NUM sweeps into the match, and the values agree with the wrapper exactly."""
    s = "exports rose 12. Stocks fell 8."
    assert vf._claim_number_spans(s) == [(13, 15, 12.0), (29, 30, 8.0)]
    assert [v for _a, _b, v in vf._claim_number_spans(s)] == vf._claim_numbers_in(s)
    assert vf._mask_handles("held 5 [N12] MMT") == "held 5       MMT"   # same length, digits neutralised


# ── D-RC-15a: the script gate on no_lexical_overlap ────────────────────────────────────────────────
# A non-Latin sentence can never share a [a-z]{5,} token with Latin evidence, and its Arabic-Indic
# digits never string-equal ASCII ones -- for those sentences the lexical test is VACUOUS, not
# failed, and verification falls back to value-level checks. Latin sentences are untouched.

AR_EV = [
    {"source": "usda_wasde", "date": "2012-08-10",
     "text": "Record soybean and corn prices occurred in 2012; prices rose 12.5 percent on the drought."},
]


def test_script_gate_non_latin_no_numbers_kept():
    """The probe defect: a correct Arabic sentence citing a resolved item was stripped for sharing
    no lexical token -- impossible by script, not by falsehood."""
    s = _structured("سجلت أسعار الذرة مستويات قياسية بسبب الجفاف [1].",
                    [{"ref": "1", "source": "usda_wasde", "date": "2012-08-10", "note": ""}])
    rep = vf.verify_citations(s, AR_EV, [])
    assert "[1]" in s["tldr"] and rep["stripped"] == 0


def test_script_gate_arabic_indic_value_matches_ascii_source():
    """١٢.٥ (12.5 in Arabic-Indic digits) must compare as a VALUE against the source's
    ASCII 12.5 -- the digit-STRING intersection can never equate them."""
    s = _structured("ارتفعت الأسعار ١٢.٥ بالمئة [1].",
                    [{"ref": "1", "source": "usda_wasde", "date": "2012-08-10", "note": ""}])
    rep = vf.verify_citations(s, AR_EV, [])
    assert "[1]" in s["tldr"] and rep["stripped"] == 0


def test_script_gate_unbacked_magnitude_still_strips():
    """The gate is not an amnesty: a pure-[E] Arabic sentence claiming a magnitude its cited source
    does not carry still strips as no_lexical_overlap."""
    s = _structured("ارتفع الإنتاج 87.3 بالمئة [1].",
                    [{"ref": "1", "source": "usda_wasde", "date": "2012-08-10", "note": ""}])
    rep = vf.verify_citations(s, AR_EV, [])
    assert "[1]" not in s["tldr"]
    assert rep["by_rule"].get("no_lexical_overlap") == 1


def test_script_gate_n_handle_numbers_are_not_e_handle_business():
    """The probe's stripped TL;DR shape: Arabic sentence carrying an [N] figure plus an [E]
    attribution. The number's truth belongs to _check_number_handle; the E-handle must not strip
    the sentence for lacking lexical overlap it cannot have."""
    s = _structured("بلغت المخزونات 31400000 [N1] وفقا للتقرير [1].",
                    [{"ref": "1", "source": "usda_wasde", "date": "2012-08-10", "note": ""}])
    rep = vf.verify_citations(s, AR_EV, NUMS)
    assert "[1]" in s["tldr"] and "[N1]" in s["tldr"] and rep["stripped"] == 0


def test_script_gate_closed_for_latin_short_words():
    """An all-ASCII sentence of short words also yields zero _tokens -- the gate must NOT open for
    it (that would weaken the verifier on English), so it still strips."""
    s = _structured("It was up a lot [1].",
                    [{"ref": "1", "source": "usda_wasde", "date": "2012-08-10", "note": ""}])
    rep = vf.verify_citations(s, AR_EV, [])
    assert "[1]" not in s["tldr"]
    assert rep["by_rule"].get("no_lexical_overlap") == 1


def test_script_gate_closed_for_accented_latin():
    """Latin-Extended accents (Cote d'Ivoire, cafe with an accent) are still Latin -- no fallback."""
    s = _structured("Côte d'Ivoire cocoa bénéfice [1].",
                    [{"ref": "1", "source": "usda_wasde", "date": "2012-08-10", "note": ""}])
    rep = vf.verify_citations(s, AR_EV, [])
    assert "[1]" not in s["tldr"]
    assert rep["by_rule"].get("no_lexical_overlap") == 1


def test_non_latin_predicate():
    assert vf._non_latin("ما الذي يحدث")          # Arabic
    assert vf._non_latin("экспорт")                                  # Cyrillic
    assert not vf._non_latin("Côte d'Ivoire, São Paulo")                                           # accents stay Latin
    assert not vf._non_latin("plain english 12.5%")
    assert not vf._non_latin("")


# -- D-DV-1(i)(ii): the QUOTE-SPAN instrument -----------------------------------------------------------
# Step-0 forensics on the 2026-08-06 three-mode eval: 5 of deep's 6 quote_mismatch strips were VERIFIER
# faults, not model faults. Three were spans extracted with the sentence comma captured INSIDE the quote
# marks (American style) -- comma off, they match their cited row verbatim. Two were correct co-citations:
# a sentence citing two rows charged BOTH handles for BOTH clauses' quotes, stripping the handle that
# backed its own clause. Neither fix loosens the match: no fuzzy compare, no extra case folding, and the
# row-text side is normalized identically so a real mismatch still fires.
DV_EV = [
    {"source": "usda_gain_brazil", "date": "2026-03-31",
     "text": "Widespread crop disease across the northern belt cut deliverable supply in the season."},
    {"source": "conab_outlook", "date": "2026-04-15",
     "text": "Planted area expanded by a fifth as producers rotated acreage into the second corn crop."},
]
_DV_SRC = [{"ref": "1", "source": "usda_gain_brazil", "date": "2026-03-31"},
           {"ref": "2", "source": "conab_outlook", "date": "2026-04-15"}]


def test_quote_span_trailing_comma_inside_the_marks_is_not_a_mismatch():
    """(a) The measured extraction fault. The row says '...crop disease across...'; the model writes the
    span with the clause comma inside the closing mark, which is exactly what the style guide asks for."""
    s = _structured('The agency flagged "Widespread crop disease," which cut deliverable supply [1].',
                    [_DV_SRC[0]])
    rep = vf.verify_citations(s, DV_EV, [])
    assert "[1]" in s["tldr"] and rep["stripped"] == 0 and rep["by_rule"] == {}
    # ... and the PRE-FIX comparison is pinned as the defect it was: raw _norm leaves the comma on
    assert vf._norm("Widespread crop disease,") not in vf._norm(DV_EV[0]["text"])
    assert vf._norm_quote("Widespread crop disease,") in vf._norm_quote(DV_EV[0]["text"])


def test_quote_span_terminal_period_and_quote_marks_are_edge_only():
    """The same normalization on the other terminal punctuation, and on BOTH sides -- but strictly at the
    EDGES: an interior comma is still part of the span, so wording and punctuation inside it must match."""
    for span in ("cut deliverable supply in the season.", "cut deliverable supply in the season"):
        s = _structured('The report said "%s" [1].' % span, [_DV_SRC[0]])
        rep = vf.verify_citations(s, DV_EV, [])
        assert "[1]" in s["tldr"] and rep["by_rule"] == {}, span
    assert vf._norm_quote("disease, driven") == "disease, driven"      # interior punctuation untouched


def test_absent_quote_span_still_strips_normalization_is_not_amnesty():
    """(b) A span the cited row does not carry -- verbatim or comma-stripped -- still charges, and a span
    that differs by a WORD is not rescued by the punctuation strip."""
    s = _structured('The agency flagged "yields collapsed by half across the belt" in the note [1].',
                    [_DV_SRC[0]])
    rep = vf.verify_citations(s, DV_EV, [])
    assert "[1]" not in s["tldr"]
    assert rep["stripped"] == 1 and rep["by_rule"] == {"quote_mismatch": 1}
    near = _structured('The agency flagged "Widespread crop failure," which cut supply [1].', [_DV_SRC[0]])
    assert vf.verify_citations(near, DV_EV, [])["by_rule"] == {"quote_mismatch": 1}
    # the pools are the CITED handles' -- a span carried only by an item the sentence never cited is still
    # a mis-attribution (the sentence-level verdict widens the pool set, never the evidence set)
    other = _structured('The report says "Planted area expanded by a fifth" [1].', [_DV_SRC[0]])
    assert vf.verify_citations(other, DV_EV, [])["by_rule"] == {"quote_mismatch": 1}


def test_co_cited_handles_each_backing_their_own_clause_survive():
    """(c) The co-citation over-strip. One sentence, two rows, one quoted clause: the span lives in [1]'s
    row, [2] backs the acreage clause beside it. The old rule charged [2] for a quote it never claimed."""
    sent = ('The note pairs "Widespread crop disease" [1] with acreage that expanded by a fifth into '
            'the second corn crop [2].')
    s = _structured(sent, _DV_SRC)
    rep = vf.verify_citations(s, DV_EV, [])
    assert "[1]" in s["tldr"] and "[2]" in s["tldr"]
    assert rep["checked"] == 2 and rep["stripped"] == 0 and rep["by_rule"] == {}
    # the mechanism, directly: [2]'s pool ALONE fails the span; the sentence's pools together carry it
    assert vf._unbacked_quote(sent, [[DV_EV[1]]]) is not None
    assert vf._unbacked_quote(sent, [[DV_EV[0]], [DV_EV[1]]]) is None


def test_span_absent_from_every_cited_handle_charges_exactly_once():
    """(d) When NO cited pool carries the span the rule still fires -- once for the sentence, with both
    handles dropped together (the number_mismatch whole-sentence precedent: dropped together, charged
    once), never once per handle."""
    s = _structured('The note pairs "yields collapsed by half" [1] with acreage that expanded by a '
                    'fifth into the second corn crop [2].', _DV_SRC)
    rep = vf.verify_citations(s, DV_EV, [])
    assert "[1]" not in s["tldr"] and "[2]" not in s["tldr"]
    assert rep["checked"] == 2 and rep["stripped"] == 1
    assert rep["by_rule"] == {"quote_mismatch": 1}


def test_quote_verdict_outranks_lexical_overlap_as_it_always_did():
    """The per-handle rule ORDER is preserved across the move to a sentence-level verdict: a handle that
    fails both rules is charged quote_mismatch (once), and a handle that fails only the lexical test in a
    sentence whose quote IS backed is still charged no_lexical_overlap."""
    both = _structured('Tariff escalation redirected Chinese buying, "yields collapsed by half" [1].',
                       [_DV_SRC[0]])
    assert vf.verify_citations(both, DV_EV, [])["by_rule"] == {"quote_mismatch": 1}
    mixed = _structured('The note quotes "Widespread crop disease" [1]. Tariff escalation redirected '
                        'Chinese buying toward other origins [2].', _DV_SRC)
    rep = vf.verify_citations(mixed, DV_EV, [])
    assert rep["by_rule"] == {"no_lexical_overlap": 1}                # [1] survives on its backed span
    assert "[1]" in mixed["tldr"] and "[2]" not in mixed["tldr"]


# -- D-DV-1(iii): the LEDGER CASCADE gets its own key ---------------------------------------------------
# One unmatched ledger ref strips its own row AND every prose sentence citing it. The s5 A/B's headline
# "35 fabricated citations" was ~12 distinct sentences off 6 unmatched rows read through this cascade.
# The stripping is unchanged; only the ACCOUNTING is: fabricated_citation counts the defect (a cited
# handle with no such item in the evidence list), ledger_cascade counts its downstream sentences.
def test_unmatched_ledger_ref_keys_its_downstream_sentences_ledger_cascade():
    s = _structured("Disease cut deliverable supply [1]. Acreage expanded by a fifth [1].",
                    [{"ref": "1", "source": "reuters_live_wire", "date": "2026-01-01"}],
                    mechanism="Producers rotated acreage into the second corn crop [1].")
    rep = vf.verify_citations(s, DV_EV, [])
    assert rep["by_rule"].get("fabricated_citation") == 1             # the LEDGER ROW, once
    assert rep["by_rule"].get("ledger_cascade") == 3                  # the three citing sentences
    assert rep["stripped"] == 4                                       # stripping itself is unchanged
    assert s["sources"] == [] and "[1]" not in s["tldr"] and "[1]" not in s["mechanism"]


def test_fabricated_citation_again_means_a_handle_no_item_backs():
    """The rule name is honest again: a resolvable ledger keeps fabricated_citation at zero however many
    sentences cite it, and an undeclared prose handle keeps its own key."""
    ok = _structured("Widespread crop disease cut deliverable supply [1]. Acreage expanded [2].", _DV_SRC)
    rep = vf.verify_citations(ok, DV_EV, [])
    assert rep["by_rule"] == {} and rep["stripped"] == 0
    und = _structured("Freight rates spiked on Panama canal restrictions [9].", [])
    rep2 = vf.verify_citations(und, DV_EV, [])
    assert rep2["by_rule"] == {"undeclared_unsupported": 1}           # never fabricated_citation
    assert "ledger_cascade" not in rep2["by_rule"]


def test_ledger_cascade_audit_entry_names_the_new_rule(monkeypatch):
    """An RCA dump can separate the cascade from the defect without re-parsing prose."""
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    s = _structured("Disease cut deliverable supply [1].",
                    [{"ref": "1", "source": "reuters_live_wire", "date": "2026-01-01"}])
    rep = vf.verify_citations(s, DV_EV, [])
    assert [e["rule"] for e in rep["strip_audit"]] == ["ledger_cascade"]
    assert rep["strip_audit"][0]["field"] == "tldr"


# ======================================================================================================
# 09-23 FIX ROUND, LANE V -- THE BACKED-FACT POOL, THE DERIVED UNIT VOCABULARY, THE BINDING, THE LEDGER.
# Every prose fixture below is VERBATIM from the 09-23 in-VPC re-smoke (`resmoke_0923/answers/*.trace.json`,
# `raw_draft.preverify_*`), the em dash spelled chr(0x2014) so this source stays ASCII; the row values are
# the traces' own `served_rows`. The fact graders classified every charge these sentences took at HEAD a
# verifier false positive (or a writer slip the same-row re-address corrects) -- 0 writer misquotes.
# ======================================================================================================
import copy as _copy                                                            # noqa: E402

_D = chr(0x2014)


def _c(v, unit="", rid=None, table="t", metric="m", rows=None):
    c = {"query": {"table": table, "metric": metric},
         "rows": rows if rows is not None else [{"value": v, "unit": unit}], "status": "ok"}
    if v is not None:
        c["shown"] = [float(v)]
    if rid:
        c["_row_id"] = rid
    return c


def _pad(calls: dict, n: int) -> list:
    return [calls.get(i, {"query": {"metric": "pad"}, "rows": []}) for i in range(1, n + 1)]


def _v(text, calls, *, field="tldr", evidence=None, sources=None, **kw):
    st = {"tldr": text if field == "tldr" else "", "mechanism": text if field == "mechanism" else "",
          "sources": list(sources or [])}
    rep = vf.verify_citations(st, list(evidence or []), _copy.deepcopy(calls), **kw)
    return rep, st[field]


# -- (3) THE UNIT IS WHAT THE ROW SAYS IT IS: cotton's 13 of 13 ------------------------------------------
def _cot(v):
    # the WASDE row prints its own unit; its unit-less DUPLICATE (writer_seam duplicate groups) rides beside
    return _c(v, rows=[{"value": v, "unit": "Million 480 Pound Bales"}, {"value": v, "unit": ""}],
              table="silver_wasde", metric="ending_stocks")


_COTTON = _pad({1: _cot(4.15), 2: _cot(4.0), 3: _cot(13.9), 4: _cot(14.41), 5: _cot(12.3), 6: _cot(11.9),
                14: _cot(3.6), 15: _cot(13.2), 16: _cot(12.3)}, 16)
_COTTON_S = [
    ("The US cotton balance sheet is tightening on the projections we hold: ending stocks fall from 4.15 [N1] "
     "to 3.6 million 480-pound bales [N14] between MY2025/26 and MY2026/27, with production down to 13.2 "
     "[N15] against exports held at 12.3 [N16] " + _D + " that points toward higher prices."),
    ("- Ending stocks: 4 [N2] in MY2024/25, 4.15 [N1] in MY2025/26, 3.6 million 480-pound bales [N14] in "
     "MY2026/27 " + _D + " a steady draw."),
    "- Production: 14.41 [N4], then 13.9 [N3], then 13.2 million 480-pound bales [N15].",
    ("- Exports: 11.9 [N6], 12.3 [N5], 12.3 million 480-pound bales [N16] " + _D + " the export program is "
     "held flat while the crop shrinks, which is what does the tightening."),
]


def test_0923_cotton_the_rows_own_unit_is_never_a_claim_and_all_four_sentences_are_clean():
    """HEAD: 13 of 13 handles charged number_unbacked by the 480 of the rows' own "Million 480 Pound Bales".
    The derived vocabulary reads it off the cited rows (row-granular: the unit-less duplicate contributes
    nothing and voids nothing), and every handle stays."""
    for s in _COTTON_S:
        rep, out = _v(s, _COTTON, field="mechanism")
        assert rep["by_rule"] == {} and rep["stripped"] == 0, s
        assert out == s
    g = vf._grammar_for(_COTTON_S[2], _COTTON)
    assert [v for _a, _b, v in vf._claim_number_spans(vf._HANDLE.sub("", _COTTON_S[2]), units=g)] == \
        [14.41, 13.9, 13.2]


def test_0923_a_unit_masks_only_after_a_figure_and_only_in_phrase_order():
    """V-3 / V-5: "exports of 1000 MT" has no figure in front of the label -- 1000 is still a claim and is
    still charged against a 622.692 row; "3 of 4 cells" is prose, not the garbled label's "tons 3 4"."""
    esr = _pad({2: _c(622.692, "1000 MT", table="silver_esr", metric="weekly_exports_1000mt")}, 2)
    rep, _out = _v("US exports of 1000 MT [N2] were shipped in the week.", esr)
    assert rep["by_rule"] == {"number_mismatch": 1}
    garbled = ("1 Thousand Short2 Tons 3 4",)
    assert [v for _a, _b, v in vf._claim_number_spans("400 1 Thousand Short2 Tons 3 4", units=garbled)] == [400.0]
    assert [v for _a, _b, v in vf._claim_number_spans("400 MT, 3 of 4 cells", units=garbled)] == [400.0, 3.0, 4.0]
    assert [v for _a, _b, v in vf._claim_number_spans("ranged 5900-1000 MT", units=("1000 MT",))] == \
        [5900.0, 1000.0]                                          # a dash is never a label lead (the range hazard)


def test_0923_the_year_rule_reads_the_cited_rows_own_unit():
    """V-7, rice: "net long 1992 contracts [N37]" -- `contracts` is the cited COT row's own unit, so 1992 is a
    claim in it (HEAD read a year and cut the neighbouring 84th to "a level this page could not back").
    HEAD's floor still makes "exports hit 1950 MMT" a claim, and a bare year with no unit is still a year."""
    rice = _pad({37: _c(1992, "contracts", rid="rice|cot"), 38: _c(1.2, "sigma", rid="rice|cot"),
                 39: _c(84, "percentile", rid="rice|cot")}, 39)
    s = ("- Managed money was net long 1992 contracts [N37] as of 15 September 2026, 84th percentile, having "
         "risen four straight weeks;")
    g = vf._grammar_for(s, rice)
    assert [v for _a, _b, v in vf._claim_number_spans(vf._HANDLE.sub("", s), units=g)] == [1992.0, 84.0]
    rep, out = _v(s, rice, field="mechanism")
    assert rep["by_rule"] == {} and "84th percentile [N39]" in out and "1992 contracts [N37]" in out
    assert rep["readdressed"] == [{"from": 37, "to": 39, "field": "mechanism", "numeral": 84.0}]
    assert vf._claim_numbers_in("exports hit 1950 MMT") == [1950.0]
    assert vf._claim_numbers_in("in 1992 the market") == []


#: HEAD's four closed unit / duration sets (verify.py at ee06f19c: `_UNIT_AFTER` :319, `_UL_UNIT` / `_UL_QUAL`
#: :622, `_FIGCUT_UNIT` :934-936, `_DURATION_NOUN` :391), spelled as the words they matched. They live HERE,
#: as the superset pin, and nowhere in verify.py: the live vocabulary is DECLARED DATA (fix-round M2).
_HEAD_UNIT_WORDS = (
    "MMT", "MT", "KT", "kt", "MMbu", "bu", "%", "percent", "ha", "bales", "cwt", "tonnes", "tons",
    "HA", "HEAD", "KG", "LB", "BOXES",
    "percentage point", "percentage points", "pp", "bps", "bp", "tonne", "ton", "bushel", "bushels",
    "USD/bu", "USD", "EUR", "cent", "cents", "acre", "acres", "bale", "head", "contract", "contracts",
    "lot", "lots", "z", "sigma", "deg C", "degC", "ratio", "index", "point", "points", "session", "sessions",
    "day", "days", "week", "weeks", "month", "months", "year", "years",
    "yr", "wk", "quarter", "qtr", "season",
)


def test_0923_the_superset_pin_every_HEAD_unit_word_is_still_recognised():
    """V-4 + fix-round M2: HEAD's closed sets are RETIRED from verify.py (no `_HEAD_*_FLOOR` tuple remains);
    every word they spelled is recognised by the DECLARED vocabulary (cards + tables.yaml's unit / duration
    spellings + the render's period nouns); every render period noun is recognised; and rule (i)'s
    phrase-PREFIX masking covers every unit-label shape HEAD's rule (g) bags exempted."""
    for gone in ("_HEAD_UNIT_FLOOR", "_HEAD_DURATION_FLOOR", "_HEAD_UL_UNIT_FLOOR", "_HEAD_UL_QUAL_FLOOR",
                 "_fold_plural", "_noun_object_splice", "_splice_figure"):
        assert not hasattr(vf, gone), gone
    words = vf._derived_unit_words()
    assert {w.lower() for w in _HEAD_UNIT_WORDS} <= words, sorted({w.lower() for w in _HEAD_UNIT_WORDS} - words)
    from leviathan.graphrag.state import render as _r
    assert set(_r.PERIOD_NOUNS.values()) <= words
    g = vf._unit_grammar(vf._declared_vocab().phrases, ())
    for label in ("(1000 MT)", "1000 MT", "(1000 HA)", "1000 HEAD", "1000 boxes", "(1000 60 KG BAGS)",
                  "60-kg bags", "1000 480 lb. Bales", "480-lb bales", "million 480-lb bales",
                  "COP per 125-kg carga", "per 125-kg carga"):
        assert [v for _a, _b, v in vf._claim_number_spans("stocks 154,947 " + label, units=g)] == [154947.0], label
    # ...and only from a phrase's OWN START (review FATAL-1): a function word inside a card unit never masks
    for s, want in (("Stocks hit 4.1 vs 3 yr ago", [4.1, 3.0]), ("stocks 3.6 vs 5 in MY2025/26", [3.6, 5.0]),
                    ("prices 7.2 per 125 more", [7.2, 125.0]), ("readings 1.4 prior 10 were higher", [1.4, 10.0]),
                    ("1.4 sigma vs 5 yr mean", [1.4])):
        assert [v for _a, _b, v in vf._claim_number_spans(s, units=g)] == want, s


def test_0923_the_frozen_cycle8_view_sees_none_of_it():
    """`_claim_number_spans(s, cycle8=False)` is HEAD's (a)-(d) extractor, byte for byte, on every new shape
    (values read off HEAD ee06f19c)."""
    for s, want in (
            ("ending stocks fall from 4.15 to 3.6 million 480-pound bales between MY2025/26 and MY2026/27",
             [4.15, 3.6, 480.0]),
            ("Managed money was net long 1992 contracts as of 15 September 2026, 84th percentile", [84.0]),
            ("400 1 Thousand Short2 Tons 3 4", [400.0, 1.0, 3.0, 4.0]),
            ("exports of 1000 MT", [1000.0]),
            ("the drought anomaly 0 z, 55th percentile", [0.0, 55.0]),
            ("feed at the 95th, against a 16th-percentile stocks-to-use", [95.0, 16.0]),
            ("a 3-session rally", [3.0]),
            ("a 2-fortnight lag", [2.0]),
            ("exports hit 1950 MMT", [1950.0])):
        assert [v for _a, _b, v in vf._claim_number_spans(s, cycle8=False)] == want, s
        assert [v for _a, _b, v in vf._claim_number_spans(s, cycle8=False, units=("1 Thousand Short2 Tons 3 4",
                                                                                     "Million 480 Pound Bales"))] \
            == want, s
    # the round-2 measured refusal holds: an OBSERVATION unit is rule (h)'s, never rule (f)'s
    assert vf._claim_numbers_in("a 3-session rally [N4]") == [3.0]
    assert vf._claim_numbers_in("its own 250-session rally [N1]") == [250.0]


# -- (5) THE ZERO ARM: cocoa S1 / S5 -----------------------------------------------------------------------
def test_0923_a_zero_written_at_a_known_precision_backs_a_row_that_rounds_to_it():
    cocoa = _pad({26: _c(0.00088532, "z"), 28: _c(55, "percentile")}, 28)
    for s in ("the drought anomaly 0 z [N26], 55th percentile [N28];",
              "- **West African drought anomaly** 0 z, read 2026-07 [N26], acting 31 October 2026 to 30 April 2027;"):
        rep, out = _v(s, cocoa, field="mechanism")
        assert rep["by_rule"] == {} and out == s
    rep, _out = _v("the drought anomaly 0 z [N1];", [_c(0.6, "z")], field="mechanism")
    assert rep["by_rule"] == {"number_mismatch": 1}                 # "0 [N]" vs 0.6 still charged
    assert vf._num_matches([0.0], [0.4], [0]) is False               # the cycle-6 pin: never a 0.4 row
    assert vf._num_matches([0.0], [0.06], [1]) is False
    assert vf._num_matches([0.0], [0.00088532], [0]) is True
    assert vf._num_matches([0.0], [0.00088532]) is False            # no written precision: 0 matches only 0
    assert vf._num_backed(0.0, [0.00088532], dec=0) is True          # the backstop mirrors it


# -- (6) THE NOUN-OBJECT SPLICE: tariff "higher year-on-year vs." ------------------------------------------
_TARIFF = _pad({29: _c(1328.0, "US cents/bushel", table="silver_futures_eod", metric="settle"),
                30: _c(1012.0, "US cents/bushel", table="silver_futures_eod", metric="settle"),
                54: _c(10.719961, "%", table="silver_psd", metric="su_ratio"),
                56: _c(23, "percentile", table="silver_psd", metric="su_ratio"),
                60: _c(2.6038, "USD/bu", table="gold_board_crush", metric="crush_margin_usd_bu"),
                78: _c(6.45, "MMT", table="silver_psd", metric="exports_mt")}, 78)


def test_0923_a_handle_pair_used_as_nouns_binds_no_figure_and_is_served_as_written():
    """The tariff "higher year-on-year [N29] vs [N30]" handles bind no figure (the sentence's only numeral is
    [N56]'s, written straight into it), so neither is charged and the sentence reaches the page AS WRITTEN.
    The noun-object splice that used to print both headline figures into it is RETIRED (review FATAL-5: it
    wrote figures into uncharged prose); nothing is inserted."""
    s = ("this year the same demand loss meets a stocks-to-use ratio at the 23rd percentile [N56], and the "
         "price tape is higher year-on-year [N29] vs [N30].")
    rep, out = _v(s, _TARIFF)
    assert rep["by_rule"] == {} and out == s
    assert "noun_object_spliced" not in rep
    assert rep["repairs"] == [] and rep["repaired"] == 0             # CYCLE-10: nothing was REWRITTEN


def test_fix_0923_uncharged_digit_free_prose_is_never_given_a_figure():
    """Review FATAL-5, the twins by construction: two solitary handles joined by one word at a clause end,
    in prose that makes no numeric claim, are served verbatim (HEAD's bytes) -- no figure is written in."""
    mpob = _pad({1: _c(2628325.0, "tonnes", table="silver_mpob", metric="closing_stocks"),
                 2: _c(1.89, "months of export cover", table="silver_mpob", metric="su_ratio"),
                 3: _c(1328.25, "US cents/bushel", table="silver_futures_eod", metric="settle"),
                 4: _c(1012.0, "US cents/bushel", table="silver_futures_eod", metric="settle")}, 4)
    for s in ("Both palm balance sheets tightened through the summer [N1] and [N2].",
              "Palm stocks are drawing down, per MPOB [N1] and [N2]; soyoil is not.",
              "The soybean contract is above last year [N3] and [N4], while meal is flat.",
              "The tape is higher year on year [N3] vs [N4]."):
        rep, out = _v(s, mpob)
        assert out == s and rep["by_rule"] == {} and "noun_object_spliced" not in rep, s


def test_0923_a_handle_followed_by_more_words_is_not_the_noun_shape_and_is_never_spliced():
    s = ("Price-supportive: the tight stocks-to-use ratio [N54] at high confidence, the crush margin [N60] at "
         "high confidence, and Argentine export policy read on exports of 6.45 MMT [N78] " + _D +
         " also high confidence.")
    rep, out = _v(s, _TARIFF)
    assert "noun_object_spliced" not in rep
    # ...and the word-cited handles are no longer convicted by 6.45, which [N78] backs (the binding rule)
    assert rep["by_rule"] == {} and out == s


def test_0923_the_binding_rule_keeps_the_r5_charge_on_an_adjacent_group():
    """"+0.98 degC and accelerating [N3] [N4]": adjacent handles are ONE group, 0.98 binds to it, and [N4]
    (a different row) is still charged and still rescued off the page -- r5 as shipped."""
    calls = [_c(0.0), _c(0.0), _c(0.98, "degC"), _c(0.47, "degC")]
    rep, out = _v("The ONI anomaly is at +0.98 degC and accelerating [N3] [N4].", calls)
    assert rep["by_rule"] == {"number_mismatch": 1} and "[N3]" in out and "[N4]" not in out


# -- (7) THE MALFORMED HANDLE: corn/wheat's escape ---------------------------------------------------------
def test_0923_a_handle_bracket_carrying_its_gloss_is_split_and_verified():
    corn = _pad({18: _c(93, "percentile"), 40: _c(35.817, "M ha", rid="corn|area"),
                 41: _c(1.9, "sigma", rid="corn|area"), 42: _c(98, "percentile", rid="corn|area")}, 42)
    s = ("Against it, the warm-phase Pacific at the 93rd percentile [N18] is declared in the opposite direction "
         "on corn and on wheat alike, and corn's harvested area reads 35.82 M ha [N42, the 98th percentile of "
         "its own record], declared in the opposite direction at high confidence.")
    rep, out = _v(s, corn)
    assert rep["handles_canonicalised"] == 1 and rep["by_rule"] == {}
    assert "35.82 M ha [N40] [N42], the 98th percentile of its own record" in out
    # a writer's NOTE about a handle is never turned into a citation of it
    note = ("the corpus documents both near the as-of [E31 is area only; the trade and credit items sit in the "
            "same April 2026 rapeseed reporting], and their loss would strand seed supply.")
    assert vf._canonicalise_handles(note) == (note, 0)
    assert vf._canonicalise_handles("[N5, 10, 12] and [N1-N4] and [1980-1990]")[1] == 0


# -- (8) LEDGER IDENTITY: cotton's eleven WASDE lines, rice's E41 --------------------------------------------
_WASDE_2025 = {"source": "usda_wasde", "date": "2025-01-10", "source_key": "w1",
               "text": "For the 2024/25 U.S. cotton balance sheet, production and ending stocks are increased."}
_WASDE_2023 = {"source": "usda_wasde", "date": "2023-09-12", "source_key": "w2",
               "text": "The Government of India has imposed further restrictions on rice exports with an export tax."}


def test_0923_a_ref_the_prose_writes_only_as_N_is_a_number_declaration_before_any_document_match():
    s = "Ending stocks fall from 4.15 [N1] to 3.6 million 480-pound bales [N14]."
    ledger = [{"ref": 1, "source": "USDA WASDE", "date": "2026-09-11"},
              {"ref": 14, "source": "USDA WASDE", "date": "2026-09-11"}]
    rep, _out = _v(s, _COTTON, evidence=[_WASDE_2025], sources=ledger)
    assert rep["resolved"] == {} and rep["by_rule"] == {}        # never re-dated to the 2025 WASDE
    # an integer the prose ALSO writes as [E1] keeps HEAD's order and resolves as the document
    rep2, out2 = _v("Stocks were raised [E1] while ending stocks read 4.15 [N1].", _COTTON,
                    evidence=[_WASDE_2025], sources=[{"ref": 1, "source": "usda_wasde", "date": "2025-01-10"}])
    assert "1" in rep2["resolved"] and "[E1]" in out2


def test_0923_a_mistyped_date_is_corrected_only_when_the_source_names_one_document():
    s = ("USDA raised 2025/26 global beginning stocks primarily for India on higher-than-expected Food "
         "Corporation of India stocks, reported 9 December 2025 [E41].")
    ledger = [{"ref": 41, "source": "USDA WASDE", "date": "2025-12-09"}]
    rep, out = _v(s, [], evidence=[_WASDE_2023, _WASDE_2025], sources=ledger)
    assert "41" not in rep["resolved"]                            # never re-dated to a guess
    assert rep["ledger_ambiguous"] == {"41": {"source": "USDA WASDE", "date": "2025-12-09", "candidates": 2}}
    assert rep["stripped"] == 0 and "[E41]" in out                # counted, kept, not charged
    # ONE same-source document: HEAD's correction stands -- and the date the sentence binds to the handle
    # then contradicts it, so the HANDLE (never the words) goes, counted
    rep1, out1 = _v(s, [], evidence=[_WASDE_2023], sources=ledger)
    assert rep1["corrected"] == 1
    assert rep1["by_rule"] == {"date_contradiction": 1} and "[E41]" not in out1 and "9 December 2025" in out1
    assert "41" not in rep1["resolved"]                           # the footer can never print the 2023 WASDE


def test_0923_a_date_contradiction_is_readdressed_to_the_same_source_item_that_carries_the_date():
    dec = {"source": "usda_wasde", "date": "2025-12-09", "source_key": "w3",
           "text": "USDA raised 2025/26 global beginning stocks primarily for India on Food Corporation stocks."}
    s = ("USDA raised 2025/26 global beginning stocks primarily for India on higher-than-expected Food "
         "Corporation of India stocks, reported 9 December 2025 [E41].")
    # the ledger resolved [E41] to the 2023 item (source + exact date), the sentence dates it 9 December 2025
    rep, out = _v(s, [], evidence=[_WASDE_2023, dec],
                  sources=[{"ref": 41, "source": "usda_wasde", "date": "2023-09-12"}])
    assert rep["resolved"]["41"]["date"] == "2025-12-09" and "[E41]" in out
    assert rep["e_date_readdressed"] == [{"ref": "41", "field": "tldr", "date": "2025-12-09"}]
    # a date the item's own TEXT states (yearless included) is the item's -- never a contradiction
    e4 = {"source": "usda_gain_soybeans", "date": "2025-03-19", "source_key": "g4",
          "text": "China will impose an additional 10 percent tariff on U.S. soybeans starting on March 10."}
    rep4, out4 = _v("China imposed an additional 10 percent tariff on US soybeans effective 10 March 2025 [E4].",
                    [], evidence=[e4], sources=[{"ref": 4, "source": "usda_gain_soybeans", "date": "2025-03-19"}])
    assert rep4["by_rule"] == {} and "[E4]" in out4


# -- (10) THE UNDECLARED [E] RESOLVED POSITIONALLY: cocoa E1/E7/E2 ------------------------------------------
def test_0923_an_undeclared_E_the_menu_holds_at_its_index_is_resolved_for_the_footer():
    ev = [{"source": "icco", "date": "2026-05-29", "source_key": "i1",
           "text": "World stocks-to-grindings ratio of 26.4% for 2023/24 after a 28% stock drop."},
          {"source": "usda_gain_cocoa", "date": "2025-08-22", "source_key": "g2",
           "text": "Prolonged drought conditions in West Africa began in April 2024."}]
    s = "The prior published prints: 26.4% for 2023/24 after a 28% stock drop [E1]."
    rep, out = _v(s, [], evidence=ev)
    assert rep["resolved_undeclared"]["1"]["source"] == "icco" and "[E1]" in out
    assert "2" not in rep["resolved_undeclared"]
    # the menu's item at that index does NOT support the sentence: nothing is resolved (HEAD's prune stands)
    rep2, _out2 = _v("The prior published prints: 26.4% for 2023/24 after a 28% stock drop [E2].", [], evidence=ev)
    assert "resolved_undeclared" not in rep2


def test_0923_numerals_in_E_only_sentences_are_counted_never_charged():
    """OWNER DECISION 13 -- tariff F3: "10 percent on soybeans announced February 2025 [E7]" rides the [E]
    path unchecked; the counter prices the hole, no charge is made."""
    s = ("Beijing placed retaliatory tariffs on US soybeans, reported 19 March 2025 [E7], with 10 to 15 percent "
         "more on US farm goods.")
    rep, out = _v(s, [], evidence=[{"source": "usda_gain", "date": "2025-03-19", "source_key": "g7",
                                     "text": "Beijing has placed retaliatory tariffs on U.S. soybeans."}],
                  sources=[{"ref": 7, "source": "usda_gain", "date": "2025-03-19"}])
    assert rep["e_numerals_unverified"] == 2 and rep["by_rule"] == {} and out == s


# -- (1)/(2) THE POOL AND THE SAME-ROW RE-ADDRESS: soyoil/palm, deep soybeans, cocoa, max -----------------
_SOY = _pad({21: _c(17869.0, "local currency per USD"), 24: _c(5.666910834387694, "%", rid="soyoil|su"),
             25: _c(-1.2, "sigma", rid="soyoil|su"), 26: _c(1, "percentile", rid="soyoil|su"),
             27: _c(95.82, "local currency per USD"),
             42: _c(0.15830973226062853, "z", rid="palm|drought"), 43: _c(0.7, "sigma", rid="palm|drought"),
             44: _c(72, "percentile", rid="palm|drought"),
             54: _c(-0.39, "degC", rid="oni"), 55: _c(-0.6, "sigma", rid="oni"), 56: _c(35, "percentile", rid="oni"),
             66: _c(2.8244879999999997, "MMT", rid="palm|stocks"), 67: _c(94, "percentile", rid="palm|stocks"),
             72: _c(5, "months", table="silver_mpob", metric="closing_stocks_palm_oil_mt_pace_streak")}, 72)
_SOY_POOL = [{"value": 99, "unit": "percentile", "kind": "window_peak_percentile", "row_id": "palm|drought"},
             {"value": 92, "unit": "percentile", "kind": "window_peak_percentile", "row_id": "positioning"},
             {"value": 94, "unit": "percentile", "kind": "percentile", "row_id": "palm|stocks"},
             {"value": 1, "unit": "percentile", "kind": "percentile", "row_id": "soyoil|su"}]
_SOY_TLDR = ("Reading the two sheets side by side, the substitution channel points toward soybean oil carrying "
             "the tighter balance and palm the looser one: Malaysian closing palm stocks sit at 2.82 MMT [N66], "
             "the 94th percentile of their own record and rising five months running [N72], while US soyoil "
             "stocks-to-use reads 5.67 % [N24], the 1st percentile of its own record and falling two marketing "
             "years in a row.")


def test_0923_the_soyoil_tldr_relative_value_call_survives_whole():
    """HEAD KILLED this sentence (number_mismatch on [N72], no cited backer for 94 or 1). The same-row
    re-address hands each percentile its own handle, [N72] binds no figure, and the call reaches the page
    with every handle -- with the pool and without it."""
    for pool in (_SOY_POOL, None):
        rep, out = _v(_SOY_TLDR, _SOY, served_scalars=pool)
        assert rep["by_rule"] == {}, pool
        assert "the 94th percentile [N67] of their own record and rising five months running [N72]" in out
        assert "the 1st percentile [N26] of its own record" in out
        assert "2.82 MMT [N66]" in out and "5.67 % [N24]" in out


def test_0923_the_at_odds_drought_hop_survives_with_the_pool():
    """soyoil/palm: HEAD struck the chain's ONLY at-odds hop ("99" -- the drought window peak -- matched no
    row). The pool backs the peak through the drought row's own identity; "72nd" gets [N44]."""
    s = ("drought [N42] peaked at the 99th percentile in January 2026, now 72nd, declared opposite onto ending "
         "stocks " + _D + " and the readings run against it, which is the honest problem here;")
    rep, out = _v(s, _SOY, field="mechanism", served_scalars=_SOY_POOL)
    assert rep["by_rule"] == {} and rep["pool_backed"] == 1
    assert "peaked at the 99th percentile in January 2026, now 72nd [N44], declared opposite" in out
    rep0, out0 = _v(s, _SOY, field="mechanism")                   # board-off: no pool, HEAD's verdict class
    assert "number_mismatch" in rep0["by_rule"] or "number_unbacked" in rep0["by_rule"]


def test_0923_the_pool_backs_nothing_across_rows_units_or_values():
    """V-1, the adversarial twins of the rescued drought sentence: the peak swapped to (a) another row's
    pool value, (b) the same value under a unit the scalar does not carry, (c) a value in no pool -- each
    is charged again. Rule (2): a row-less scalar backs only a numeral written in its own unit."""
    base = ("drought [N42] peaked at the {} in January 2026, now 72nd, declared opposite onto ending stocks " + _D +
            " and the readings run against it;")
    # (a) 92 is ANOTHER row's peak -- a POOL-only value (a value some served row also carries is backed by
    #     HEAD's own all-rows backstop, which is not the pool's doing and is pinned elsewhere)
    for twin in ("92nd percentile", "99 %", "777th percentile"):
        rep, _out = _v(base.format(twin), _SOY, field="mechanism", served_scalars=_SOY_POOL)
        assert any(k.startswith("number") for k in rep["by_rule"]), twin
    runs = [{"value": 8, "unit": "months", "kind": "run_length", "row_id": None}]
    oni = _pad({1: _c(1.8, "degC")}, 1)
    rep, _o = _v("The Pacific reads +1.8 degC [N1], rising 8 months running.", oni, served_scalars=runs)
    assert rep["by_rule"] == {} and rep["pool_backed"] == 1
    rep, _o = _v("The Pacific reads +1.8 degC [N1], up 8 % on the year.", oni, served_scalars=runs)
    assert rep["by_rule"] == {"number_unbacked": 1}


# -- FIX ROUND (review FATAL-1..5, M3, M5): THE ADVERSARIAL TWINS, AND EVERY ONE ASSERTS WHAT THE PAGE KEPT --
# M5: a twin that only asserts "charged" cannot see a false figure that stays on the page -- kept bare by a
# rescue or kept beside the handle of the row it contradicts. Every twin below asserts the OUTPUT: the false
# figure has left the page, or it carries no handle of a row that does not print it.
def _false_figure_uncited(out: str, figure: str, handles: tuple) -> bool:
    """True when `figure` is absent from `out`, or no handle in `handles` is written straight after it."""
    at = out.find(figure)
    while at >= 0:
        tail = out[at + len(figure):at + len(figure) + 40]
        if any(tail.lstrip().startswith("[N%d]" % h) for h in handles):
            return False
        at = out.find(figure, at + 1)
    return True


def test_fix_0923_fatal1_a_function_word_inside_a_card_unit_never_masks_a_claim():
    """Review FATAL-1: "sigma vs 3 yr mean" / "sigma vs prior 5 yrs" / "COP per 125-kg carga" made ("vs", n),
    ("prior", n), ("per", n) global maskers. A unit label is now the declared phrase written FROM ITS START,
    and the cotton unit-less duplicate row no longer stands the unit gate down (row-granular)."""
    calls = [_c(4.15, rows=[{"value": 4.15, "unit": ""}, {"value": 4.15, "unit": "Million 480 Pound Bales"}],
                table="silver_wasde", metric="ending_stocks"),
             _c(3.6, rows=[{"value": 3.6, "unit": ""}, {"value": 3.6, "unit": "Million 480 Pound Bales"}],
                table="silver_wasde", metric="ending_stocks")]
    for s, gone in (("Ending stocks fall to 3.6 [N2] vs 5 [N1] a year earlier.", "5 [N1]"),
                    ("Ending stocks fall to 3.6 vs 5 a year earlier [N2].", "[N2]"),
                    ("Ending stocks fall to 3.6 [N2], 7 below the prior 10 [N1].", "10 [N1]")):
        rep, out = _v(s, calls, field="mechanism")
        assert any(k.startswith("number") for k in rep["by_rule"]), s
        assert gone not in out, (s, out)                       # the false figure keeps no citation
    # the correct twin is untouched, and the row's own unit is still never a claim
    ok = "Ending stocks fall to 3.6 million 480-pound bales [N2] vs 4.15 [N1] a year earlier."
    rep, out = _v(ok, calls, field="mechanism")
    assert rep["by_rule"] == {} and out == ok


def test_fix_0923_fatal2_a_figure_written_into_a_handle_is_that_handles_claim():
    """Review FATAL-2: a mis-copied REPEATED value binds to the handle it is written into ("figure [N]"),
    whatever its neighbour backs -- the handle of the row it contradicts is charged and leaves the page."""
    def call(v):
        return _c(v, "MMT", table="silver_psd", metric="exports_mt")
    calls = [call(118.0), call(100.0), call(50.0), call(8.8)]
    for s, h in (("Brazil ships 118 MMT [N1] and China imports 118 MMT [N2].", 2),
                 ("US exports are 50 MMT [N3] with ending stocks of 50 MMT [N4].", 4),
                 ("US ending stocks sit at 8.8 MMT [N4], exports at 8.8 MMT [N3].", 3),
                 ("Brazil ships 118 MMT [N1] and China imports 118 MMT too [N2].", 2)):
        rep, out = _v(s, calls)
        assert rep["by_rule"] == {"number_mismatch": 1}, s
        assert "[N%d]" % h not in out, (s, out)                  # the contradicted row's handle is gone


def test_fix_0923_fatal3_readdress_needs_scale_1_and_the_unit_the_writer_wrote():
    """Review FATAL-3: the same-row re-address matched by VALUE through the multi-scale bridge. A figure
    written in a unit its sibling does not carry, or in the cited member's OWN unit (a wrong value on the
    right member), is never re-addressed; the figure never gains a citation it had not."""
    ex = _pad({7: _c(664.8, "1000 MT", rid="ex"), 8: _c(-1.0, "sigma", rid="ex"), 9: _c(13, "percentile", rid="ex"),
               10: _c(2, "percentile", rid="ex", rows=[{"value": 2, "unit": "percentile",
                                                         "stat": "window_peak_percentile"}])}, 10)
    for s, bad in (("Weekly export shipments now reads 13 1000 MT [N7].", ("13 1000 MT", (9, 10))),
                   ("Weekly export shipments now reads 1 1000 MT [N7].", ("1 1000 MT", (8,))),
                   ("Weekly export shipments now reads 664.8 1000 MT [N7], the 2nd percentile [N9] of its "
                    "own record.", ("2nd percentile", (9, 10)))):
        rep, out = _v(s, ex)
        assert "readdressed" not in rep, s
        assert _false_figure_uncited(out, bad[0], bad[1]), (s, out)
    oni = _pad({4: _c(0.98, "degC", rid="la"), 5: _c(1.2, "sigma", rid="la"), 6: _c(82, "percentile", rid="la")}, 6)
    rep, out = _v("The other reading, at 0.98 degC [N4], has held there for 120 months.", oni)
    assert "readdressed" not in rep and "[N5]" not in out and "[N6]" not in out
    # the measured correction still lands: an ORDINAL written into the level handle is the percentile's
    rep, out = _v("Weekly export shipments now reads the 13th [N7].", ex)
    assert rep["readdressed"] == [{"from": 7, "to": 9, "field": "tldr", "numeral": 13.0}] and "13th [N9]" in out


def test_fix_0923_fatal4_the_pool_backs_only_through_the_group_a_figure_binds_to():
    """Review FATAL-4: the pool's row test was SENTENCE-scoped, so in a two-row chain sentence one row's board
    figure backed a numeral written into the OTHER row's clause, and the sibling rescue served it bare. Every
    twin asserts the pool rescues nothing the pool-less cell charges and the false figure keeps no handle."""
    CR, ONI = "soy|crush", "soy|oni"
    calls = _pad({1: _c(2.6038, "USD/bu", rid=CR), 2: _c(1.4, "sigma", rid=CR), 3: _c(92.0, "percentile", rid=CR),
                  4: _c(0.98, "degC", rid=ONI), 5: _c(88.0, "percentile", rid=ONI)}, 5)
    pool = [{"value": 95.6, "unit": "percentile", "kind": "window_peak_percentile", "row_id": CR},
            {"value": 8, "unit": "months", "kind": "run_length", "row_id": CR},
            {"value": 12.4, "unit": "%", "kind": "outcome_move", "row_id": None, "handle": 11}]
    for s, false in (("Crush now reads 2.6 USD/bu [N1], while ONI sits at the 96th percentile [N5].", "96th"),
                     ("Crush reads 2.6 USD/bu [N1] and ONI is at the 96th percentile of its record [N4].", "96th"),
                     ("ONI reads 0.98 degC [N4] and has run warm for 8 months [N4].", "8 months"),
                     ("The crush margin is at its 96th percentile [N1], a record tight crush.", "96th"),
                     ("Crush fell 12.4 % on the year to 2.6 USD/bu [N1].", "12.4")):
        rep, out = _v(s, calls, field="mechanism", served_scalars=pool)
        rep0, out0 = _v(s, calls, field="mechanism")               # the pool-less cell (HEAD's reading)
        assert any(k.startswith("number") for k in rep["by_rule"]), s
        # the pool rescues NOTHING the pool-less cell charges, and the false figure keeps no citation --
        # where HEAD's own number_unbacked remedy serves it bare, it is bare on both cells (integration F-12b)
        assert (rep["by_rule"], out) == (rep0["by_rule"], out0) and "pool_backed" not in rep, (s, out)
        assert _false_figure_uncited(out, false, (1, 2, 3, 4, 5)), (s, out)
    # ...and the figure the row itself printed, in its own clause, is still backed (I-1's shape)
    s = "The crush margin peaked at the 96th percentile in July 2026 and now reads 2.6 USD/bu [N1]."
    rep, out = _v(s, calls, field="mechanism", served_scalars=pool)
    assert rep["by_rule"] == {} and out == s and rep["pool_backed"] == 1


def test_fix_0923_m3_a_percentile_word_never_stands_in_for_the_handles_figure():
    """Review M3: the word "percentile" / "decile" in the binding window no longer counts as a percentile
    handle's own figure. A figure the writer wrote INTO a percentile handle that its level sibling carries is
    re-addressed, and the percentile handle -- whose own figure is written nowhere -- leaves; a handle the
    writer cited for WORDS (the moved figure was not written into it) keeps its citation."""
    ex = _pad({7: _c(664.8, "1000 MT", rid="ex"), 8: _c(-1.0, "sigma", rid="ex"), 9: _c(13, "percentile", rid="ex")}, 9)
    rep, out = _v("Weekly shipments read 664.8 1000 MT [N9], near the bottom decile of the percentile record.", ex)
    assert rep["readdressed"][0]["to"] == 7 and "664.8 1000 MT [N7]" in out and "[N9]" not in out
    cocoa = _pad({14: _c(-0.66815534, "z", rid="wa"), 15: _c(-1.5, "sigma", rid="wa"), 16: _c(6, "percentile", rid="wa")},
                 16)
    rep, out = _v("- West African maximum temperature -0.67 z, read 2026-08, bottom decile [N16].", cocoa)
    assert rep["by_rule"] == {} and "-0.67 z [N14], read 2026-08, bottom decile [N16]" in out


def test_0923_same_row_readdress_moves_a_figure_onto_its_own_member():
    """V-2: deep soybeans "the 68th [N54]" (N54 is the crude z level; 68 is [N56]'s), cocoa "-0.67 z ...
    bottom decile [N16]" (-0.67 is [N14]'s). A figure two members back is ambiguous and left alone."""
    deep = _pad({54: _c(0.507294, "z", rid="crude"), 55: _c(-0.1, "sigma", rid="crude"),
                 56: _c(68, "percentile", rid="crude")}, 56)
    s = ("**The crude-to-crush chain, in hop order.** Crude peaked at the 98th percentile in April 2026 and now "
         "reads the 68th [N54], through 10 September 2026, its lag running to October 2026;")
    pool = [{"value": 98, "unit": "percentile", "kind": "window_peak_percentile", "row_id": "crude"}]
    rep, out = _v(s, deep, field="mechanism", served_scalars=pool)
    assert rep["by_rule"] == {} and "now reads the 68th [N56], through" in out and "[N54]" not in out
    assert rep["readdressed"] == [{"from": 54, "to": 56, "field": "mechanism", "numeral": 68.0}]
    cocoa = _pad({14: _c(-0.66815534, "z", rid="wa|tmax"), 15: _c(-1.5, "sigma", rid="wa|tmax"),
                  16: _c(6, "percentile", rid="wa|tmax")}, 16)
    s2 = ("- **West African maximum temperature** -0.67 z, read 2026-08, bottom decile [N16], acting 31 August "
          "2026 to 28 February 2027.")
    rep2, out2 = _v(s2, cocoa, field="mechanism")
    assert rep2["by_rule"] == {} and "-0.67 z [N14], read 2026-08, bottom decile [N16]" in out2
    amb = _pad({1: _c(2.0, "z", rid="r"), 2: _c(2.0, "sigma", rid="r"), 3: _c(40, "percentile", rid="r")}, 3)
    rep3, out3 = _v("The reading sits at 2.0 on its own window [N3].", amb)
    assert "readdressed" not in rep3 and "[N1]" not in out3 and "[N2]" not in out3


def test_0923_the_cited_rows_own_ordinal_is_its_figure():
    """corn/wheat: "feed at the 95th [N39]" -- a percentile call, its value written as a bare ordinal right in
    front of it; HEAD convicted it by the neighbours' 98 and 16."""
    cw = _pad({39: _c(95, "percentile"), 45: _c(98, "percentile"), 54: _c(16, "percentile")}, 54)
    s = ("Corn's demand side " + _D + " ethanol at the 98th percentile [N45], feed at the 95th [N39], against a "
         "16th-percentile stocks-to-use [N54] " + _D + " is three of the eight conditions the demand-pull pattern "
         "names, at its own threshold, and that leans price-supportive for corn.")
    rep, out = _v(s, cw, field="mechanism")
    assert rep["by_rule"] == {} and out == s


def test_0923_a_board_off_call_passes_the_same_bytes_with_or_without_the_kwarg():
    """I-8 / the byte-identity claim: `served_scalars=None` IS the omitted kwarg -- report and prose."""
    for s, calls in ((_SOY_TLDR, _SOY), (_COTTON_S[0], _COTTON)):
        a = _v(s, calls)
        b = _v(s, calls, served_scalars=None)
        c = _v(s, calls, served_scalars=[])
        assert a == b == c
