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
def _calls(rows: dict) -> list:
    """number_calls long enough for the highest cited [N] index; a listed index carries exactly ONE row."""
    return [{"query": {"metric": "m"}, "rows": ([{"value": rows[i]}] if i in rows else [])}
            for i in range(1, max(rows) + 1)]


def test_judge_fixture_transcription_fabrications_are_repaired_in_place():
    """The four figures the judge caught, each a single-number/single-row sentence -> the TRUE value lands in
    the prose and the handle stays (it is no longer a mis-citation once the figure is the row's)."""
    cases = [
        ("Anomalies ran -0.72 degC [N12][N4].", _calls({4: 0.06, 12: 0.06}),
         "Anomalies ran -0.06 degC [N12][N4].", 2),
        ("The index sat at -0.693675 z [N14].", _calls({14: -2.1035}),
         "The index sat at -2.1035 z [N14].", 1),
        ("The index sat at -1.78323 z [N15].", _calls({15: -1.4097}),
         "The index sat at -1.4097 z [N15].", 1),
        ("It peaked at +2.47 degC [N1].", _calls({1: 2.75}),
         "It peaked at +2.75 degC [N1].", 1),
    ]
    for prose, calls, want, n_handles in cases:
        s = _structured(prose, [])
        rep = vf.verify_citations(s, [], calls)
        assert s["tldr"] == want, prose
        assert rep["stripped"] == 0, prose                     # a repair is NOT a strip
        assert rep["corrected"] == n_handles, prose
        assert rep["by_rule"].get("number_mismatch_repaired") == n_handles, prose
        assert "number_mismatch" not in rep["by_rule"], prose  # the rule key is not double-charged


def test_repair_direction_stays_in_the_prose_sign():
    """_CLAIM_NUM cannot see a minus, so the row's MAGNITUDE goes in and the sign already on the page stays
    put -- the repair fixes the transcription, it never re-argues the direction."""
    s = _structured("The anomaly read -0.693675 z [N1].", [])
    vf.verify_citations(s, [], _calls({1: -2.1035}))
    assert s["tldr"] == "The anomaly read -2.1035 z [N1]."     # magnitude from the row, minus untouched


def test_repair_audit_entry_names_the_repaired_rule(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    s = _structured("It peaked at +2.47 degC [N1].", [])
    rep = vf.verify_citations(s, [], _calls({1: 2.75}))
    assert [e["rule"] for e in rep["strip_audit"]] == ["number_mismatch_repaired"]
    assert rep["strip_audit"][0]["field"] == "tldr" and "2.47" in rep["strip_audit"][0]["text"]


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


def test_repair_leaves_a_matching_sibling_handle_alone():
    """One claim number, one mismatched handle and one MATCHING handle in the same sentence: the figure is
    repaired and nothing is dropped -- a clean handle never drags its sentence down."""
    s = _structured("The anomaly reached -0.72 degC [N1][N2].", [])
    rep = vf.verify_citations(s, [], _calls({1: 0.06, 2: 0.72}))
    assert s["tldr"] == "The anomaly reached -0.06 degC [N1][N2]."
    assert rep["stripped"] == 0 and rep["corrected"] == 1
    assert rep["by_rule"] == {"number_mismatch_repaired": 1}


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
    """Only the literal 'handle' opts out; a typo, an empty string or an unset var all get the new default."""
    for val in ("failclosed", "on", "", "Handle"):
        monkeypatch.setenv("GRAPHRAG_VERIFY_NUM_MODE", val)
        s = _structured("It peaked at +2.47 degC [N1].", [])
        rep = vf.verify_citations(s, [], _calls({1: 2.75}))
        assert s["tldr"] == "It peaked at +2.75 degC [N1].", val
        assert rep["corrected"] == 1, val


def test_scale_word_refuses_the_repair_and_the_sentence_goes():
    """'48.2 million MT' citing a raw 31400000 row: the numeral is denominated, the row may not be, and
    splicing '31,400,000' next to 'million' would manufacture a THIRD figure -- so no rewrite is attempted
    and the fail-closed default deletes the sentence instead."""
    calls = [{"query": {"metric": "m"}, "rows": [{"value": 31400000}]}]
    s = _structured("Ending stocks were 48.2 million MT [N1]. Prices firmed.", [])
    rep = vf.verify_citations(s, [], calls)
    assert s["tldr"] == "Prices firmed."
    assert rep["by_rule"] == {"number_mismatch": 1} and rep["corrected"] == 0


def test_large_integer_repairs_comma_grouped_never_scientific():
    """A raw production-scale row (88,500,000) repairs as prose, not as 8.85e+07; a large NON-integer value
    that {:g} would render scientifically is refused and the sentence goes."""
    s = _structured("Output reached 92000000 MT [N1].", [])
    rep = vf.verify_citations(s, [], [{"query": {"metric": "m"}, "rows": [{"value": 88500000}]}])
    assert s["tldr"] == "Output reached 88,500,000 MT [N1]."
    assert rep["corrected"] == 1 and rep["by_rule"] == {"number_mismatch_repaired": 1}
    s2 = _structured("Output reached 92000000 MT [N1].", [])
    rep2 = vf.verify_citations(s2, [], [{"query": {"metric": "m"}, "rows": [{"value": 88500000.5}]}])
    assert s2["tldr"] == "" and rep2["by_rule"] == {"number_mismatch": 1}


def test_claim_number_spans_locate_the_token_core_not_its_punctuation():
    """The span-yielding core the repair indexes through: positions are the NUMERAL's, never the sentence
    punctuation _CLAIM_NUM sweeps into the match, and the values agree with the wrapper exactly."""
    s = "exports rose 12. Stocks fell 8."
    assert vf._claim_number_spans(s) == [(13, 15, 12.0), (29, 30, 8.0)]
    assert [v for _a, _b, v in vf._claim_number_spans(s)] == vf._claim_numbers_in(s)
    assert vf._mask_handles("held 5 [N12] MMT") == "held 5       MMT"   # same length, digits neutralised
