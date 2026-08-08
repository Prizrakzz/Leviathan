"""CYCLE-10 (2026-08-08) -- THE TERMINATION BRANCH, EXECUTED, AND THE TWO FOOTER DEFECTS BEHIND IT.

FIX 1. `verify` no longer rewrites prose. The pre-decision the wave recorded fires on the gate-7 record:
three repair ops across gates 6-7, three corrupted sentences, the last of them through a CLEAN pass of
all four cycle-9 allowlist clauses. The capability is deleted, not re-fenced.

    gate-6 COV1  "rising toward the 1.5 degC threshold [N4]"          -> "toward the 0 degC threshold"
    gate-6 COV2  "The ONI anomaly is at 0.98 degC ... [N5,N10,N12]"   -> "is at 1 degC"   (a 0/1 flag)
    gate-7 KC    "roughly 0.6 z higher [N3]"                          -> "roughly -0.6267 z higher [N3]"

The third is dispositive. ONE solitary [N] handle; BOTH unit classes known and EQUAL (`drought_z_pace_
change` reads `index` from its metric tell, the slot reads `index` from the word "z"); no threshold noun,
no conditional lead; 0.6 vs 0.6267 is inside one order of magnitude with no contradicted sign. Every
clause passed, and the sentence was still corrupted -- the slot's own word "higher" already carried the
direction the row's SIGNED delta carried again, so the "equal class" the fence certified was an agreement
of unit LABELS across two different quantities. A fence that reads labels cannot see that, which is why
no fifth clause was admissible.

FIX 2 + FIX 3. Gate-7 `ab_out_cotton` shipped prose citing [E] ids the footer never emitted, on BOTH
covenant passes, with `strips` 0, `by_rule` {}, `evidence_orphans_pruned` absent and the scaffold
declined -- so no verifier strip, no prune and no scaffold produced it. The rows were EMITTED and then
DELETED by the body-wide `reg.sanitize` pass, which on an OUTLOOK turn removes any sentence carrying an
unbacked level and takes that sentence's terminating newline with it. Hence BOTH observed shapes from one
mechanism: a whole row vanishing (the row-skip) and two rows welded onto one line (the separator bug).
"""
from __future__ import annotations

from leviathan.graphrag import answer as an
from leviathan.graphrag import register as reg
from leviathan.graphrag import verify as vf


def _structured(tldr="", mechanism="", sources=None):
    return {"tldr": tldr, "mechanism": mechanism, "sources": list(sources or [])}


def _call(metric, value, unit=None, table="t"):
    row = {"value": value, **({"unit": unit} if unit else {})}
    return {"query": {"table": table, "metric": metric}, "rows": [row], "shown": [float(value)]}


def _pad(n):
    return [{"query": {"metric": ""}, "rows": []} for _ in range(n)]


# ══ FIX 1 -- THE THREE RECORDED CORRUPTION SHAPES, REPLAYED THROUGH SHIPPED CODE ════════════════════

GATE6_COV1 = ("- **ONI trajectory**: does the anomaly continue rising toward the 1.5 °C threshold that "
              "historically coincides with more severe regional impacts, or plateau and fade as it did in "
              "mid-2016 [N4]?")
GATE6_COV1_CALLS = _pad(3) + [_call("oni_anom", 0.0, "degC", table="gold_weather_z")]

GATE6_COV2 = ("The ONI anomaly is at 0.98 °C and has risen for five consecutive months [N5, N10, N12], "
              "putting the ENSO signal firmly in El Niño territory [N2] — but at moderate strength.")
GATE6_COV2_CALLS = (_pad(1)
                    + [_call("el_nino_flag", 1, "0/1", table="gold_weather_z")]              # N2
                    + _pad(1)
                    + [_call("oni_anom", 0.0, "degC", table="gold_weather_z")]               # N4
                    + [_call("oni_anom", 0.98, "degC", table="gold_weather_z")]              # N5
                    + _pad(4)
                    + [_call("oni_anom_pace_streak", 5, "months", table="gold_weather_z")]   # N10
                    + [_call("oni_anom_pace_change", 0.47, "degC", table="gold_weather_z")]  # N11
                    + [_call("oni_anom_pace_streak", 5, "months", table="gold_weather_z")])  # N12

# gate-7 cov1 `ab_mech_kc_spread`, mechanism, reproduced from the recorded draft and served rows.
# The op the run recorded: {"field": "mechanism", "rule": "number_mismatch_repaired",
#                           "from": "0.6", "to": "-0.6267"}
GATE7_KC = ("The drought-z score for the HRW belt most recently reads 0.940889 z [N2], an elevated "
            "positive reading confirming above-normal dryness. One month prior the reading was roughly "
            "0.6 z higher [N3], meaning the pace of drying moderated, though the level remains in stress "
            "territory. A prior episode around mid-2003 showed a drought-z of 1.08449 z [N1], broadly "
            "comparable in magnitude.")
GATE7_KC_CALLS = [
    _call("drought_z", 1.08449, table="gold_weather_z"),                    # N1
    _call("drought_z", 0.940889, table="gold_weather_z"),                   # N2
    _call("drought_z_pace_change", -0.6267, table="gold_weather_z"),        # N3
]


def _no_mutation(src: str, out: str) -> bool:
    """`out` is `src` with characters DELETED and nothing else -- the strongest statement of 'the verifier
    wrote nothing'. A rewrite fails this even when the replacement is short."""
    i = 0
    for ch in out:
        j = src.find(ch, i)
        if j < 0:
            return False
        i = j + 1
    return True


def test_gate7_kc_spread_ships_unmutated_or_drops_honestly():
    """THE OP THAT ENDED THE REPAIR PATH, END TO END THROUGH SHIPPED CODE. The verdict, stated: the
    sentence takes the honest fail-closed DROP -- the whole "One month prior ..." sentence leaves the page
    and the two correctly-cited sentences around it survive intact. It is never rewritten."""
    s = _structured(mechanism=GATE7_KC)
    rep = vf.verify_citations(s, [], GATE7_KC_CALLS)
    assert "-0.6267" not in s["mechanism"]                       # the corruption cannot be minted
    assert "One month prior" not in s["mechanism"]               # ...the sentence took the drop
    assert "0.940889 z [N2]" in s["mechanism"] and "1.08449 z [N1]" in s["mechanism"]
    assert _no_mutation(GATE7_KC, s["mechanism"])
    assert rep["repaired"] == 0 and rep["repairs"] == []
    assert rep["by_rule"] == {"number_mismatch": 1} and rep["stripped"] == 1
    # the CHARGE denominators are the gate-7 ones, unmoved: three handles checked, three sentences
    assert rep["checked"] == 3 and rep["claim_count"] == 3


def test_gate6_cov1_the_approach_threshold_drops_and_is_never_rewritten():
    """COV1. The charge is real (1.5 is not [N4]'s 0) and the remedy is the drop. `0 degC` -- ENSO-neutral
    -- can no longer reach the page by any route."""
    s = _structured(mechanism=GATE6_COV1)
    rep = vf.verify_citations(s, [], GATE6_COV1_CALLS)
    assert "0 °C threshold" not in s["mechanism"] and s["mechanism"] == ""
    assert _no_mutation(GATE6_COV1, s["mechanism"])
    assert rep["repaired"] == 0 and rep["repairs"] == []
    assert rep["by_rule"] == {"number_mismatch": 1}


def test_gate6_cov2_the_flag_row_reaches_nothing_and_the_figure_survives():
    """COV2. The r5 sibling rescue still fires (the grouped `[N5, N10, N12]` materializes 0.98), so this
    one SHIPS INTACT WITH THE MIS-CITING HANDLE STRIPPED -- the third possible honest outcome, and the
    best one. `1 degC` is unreachable in either case."""
    s = _structured(tldr=GATE6_COV2)
    rep = vf.verify_citations(s, [], GATE6_COV2_CALLS)
    assert "at 1 °C" not in s["tldr"] and "0.98 °C" in s["tldr"]
    assert "[N2]" not in s["tldr"] and "[N5, N10, N12]" in s["tldr"]
    assert _no_mutation(GATE6_COV2, s["tldr"])
    assert rep["repaired"] == 0 and rep["repairs"] == []


def test_every_corruption_shape_is_deletion_only_under_both_num_modes(monkeypatch):
    """All three shapes, under the fail-closed default AND under the documented `=handle` rollback: the
    output is always the input minus characters. There is no env value that restores a writer."""
    for mode in (None, "handle", "failclosed", ""):
        for src, calls, fld in ((GATE6_COV1, GATE6_COV1_CALLS, "mechanism"),
                                (GATE6_COV2, GATE6_COV2_CALLS, "tldr"),
                                (GATE7_KC, GATE7_KC_CALLS, "mechanism")):
            if mode is None:
                monkeypatch.delenv("GRAPHRAG_VERIFY_NUM_MODE", raising=False)
            else:
                monkeypatch.setenv("GRAPHRAG_VERIFY_NUM_MODE", mode)
            s = _structured(**{fld: src})
            rep = vf.verify_citations(s, [], calls)
            assert _no_mutation(src, s[fld]), (mode, fld)
            assert rep["repaired"] == 0 and rep["repairs"] == [], (mode, fld)


# ══ FIX 1 -- THE CARRIERS SURVIVE THE DELETION (artifact schema stability for gate-8) ═══════════════

def test_the_repair_carriers_are_still_present_and_always_empty():
    """`repaired` / `repairs` are NOT deleted with the behaviour. Gate-8 must diff against gate-7's
    artifacts, `eval.verifier_panel` prints the repair count, and the orchestrator reads the report as a
    dict -- so the fields stay, unconditional, and now always read 0 / []."""
    for prose, calls in (("Nothing numeric here at all.", []),
                         ("It peaked at +2.47 degC [N1].", [_call("m", 2.75, "degC")]),
                         (GATE7_KC, GATE7_KC_CALLS)):
        rep = vf.verify_citations(_structured(mechanism=prose), [], calls)
        assert "repaired" in rep and "repairs" in rep
        assert rep["repaired"] == 0 and rep["repairs"] == []
        assert "number_mismatch_repaired" not in rep["by_rule"]


def test_the_repair_only_fence_machinery_is_gone_not_merely_unreachable():
    """A loaded fence with no caller is what a later cycle re-arms by accident. Everything that existed
    ONLY to answer 'may a row value be written into this slot' is removed from the module."""
    for gone in ("_UNIT_CLASSES", "_UNIT_OF", "_UNIT_TAIL", "_unit_class", "_unit_class_lead",
                 "_registry_unit_class", "_METRIC_TELL", "_metric_tell_class", "_call_unit_class",
                 "_sentence_unit_class", "_NON_VALUE_SLOT", "_PCT_METRIC", "_REPAIR_MAG_RATIO_MAX",
                 "_LEAD_WINDOW", "_PROSE_SIGN", "_COND_CTX", "_THRESHOLD_LEAD", "_THRESHOLD_NOUN",
                 "_SCALE_WORD", "_COUNT_METRIC"):
        assert not hasattr(vf, gone), gone


def test_what_is_shared_with_charging_and_minting_STAYS():
    """The mandate's other half. The sibling rescue, grouped-handle parsing, the reader-precision match
    and the cycle-8 duration/ordinal exemptions are charge-side and untouched."""
    for kept in ("_handle_members", "_mask_handles", "_sibling_backed", "_reader_precision_match",
                 "_claim_number_spans", "_mismatch_pool", "_num_matches", "_num_backed", "_HANDLE"):
        assert hasattr(vf, kept), kept
    assert vf._handle_members("[N5, 10, 12]") == [("N", 5), ("N", 10), ("N", 12)]   # cycle-9 3a
    assert vf._reader_precision_match(0.31, 0.30632, 2) is True                     # cycle-6
    assert [v for _a, _b, v in vf._claim_number_spans("below the 5-year mean")] == []  # cycle-8 (f)
    assert [v for _a, _b, v in vf._claim_number_spans("at the 85th percentile")] == [85.0]  # (e) carve-out


def test_the_charge_is_untouched_only_the_remedy_moved():
    """Denominator parity in miniature: the SAME sentences are convicted, with the same rule key, the same
    `checked` and the same `claim_count`. What used to be a silent `number_mismatch_repaired` is now a
    counted `number_mismatch` strip -- which is the anti-laundering direction, not a new charge."""
    calls = [_call("m", 2.75, "degC")]
    prose = "Stocks held steady. It peaked at +2.47 degC [N1]. Prices firmed."
    rep = vf.verify_citations(_structured(mechanism=prose), [], calls)
    assert rep["claim_count"] == 3 and rep["checked"] == 1
    assert rep["stripped"] == 1 and rep["by_rule"] == {"number_mismatch": 1}
    # a sentence whose figure MATCHES is untouched in every respect
    ok = _structured(mechanism="It peaked at +2.75 degC [N1].")
    rep_ok = vf.verify_citations(ok, [], calls)
    assert ok["mechanism"] == "It peaked at +2.75 degC [N1]."
    assert rep_ok["by_rule"] == {} and rep_ok["stripped"] == 0


# ══ FIX 2 -- THE FOOTER EMITS THE ROW, AND A ROW IS ONE LINE ════════════════════════════════════════
#
# The `ab_out_cotton` shape, pinned from the gate-7 artifacts: the prose cites [E1]..[E7] and the WASDE
# row's snippet is corpus prose quoting a price level, which the OUTLOOK register refuses.

_COTTON_TLDR = ("Futures market data projects prices remaining below the 10-year average through "
                "MY 2025/26 [E1].")
_COTTON_MECH = ("Trade sources indicated prices were unlikely to breach the MSP floor [E2]. A rise of "
                "just over 44 percent to $1.33 per pound [E3] has since unwound. Cotton prices were "
                "described as under pressure in a World Bank outlook [E4]. India's consumption was "
                "revised down by 800,000 bales [E5]. India's MSP was set 5 percent above the prior "
                "year [E6]. Reduced planting intentions followed [E7].")
_COTTON_SOURCES = [{"ref": i, "source": "s%d" % i, "date": "2020-01-01"} for i in (1, 2, 3, 4, 6)]
_COTTON_RESOLVED = {
    "1": {"source": "usda_gain_rapeseed", "date": "2025-04-02",
          "snippet": "Futures market data suggests that cotton prices will remain below the "
                     "10-year average beyond the MY 2025/26 harvest."},
    "2": {"source": "usda_gain_cotton", "date": "2022-09-07",
          "snippet": "Trade sources indicate that cotton prices are unlikely to fall below the "
                     "minimum support price (MSP) in MY 2022/2023."},
    "3": {"source": "usda_wasde", "date": "2014-01-01",
          "snippet": "U.S. cotton prices are forecast at 78 cents per pound, a rise of 44 percent "
                     "to 1.33 dollars."},
    "4": {"source": "wb_cmo_outlook", "date": "2013-10-01",
          "snippet": "Cotton prices have been under pressure."},
    "6": {"source": "usda_gain_cotton", "date": "2020-06-30",
          "snippet": "The MSP increase for cotton for India's marketing season 2020-21 represents a "
                     "five percent increase from the 2019 MSP prices."},
}


def _cotton(mr):
    d = _structured(_COTTON_TLDR, _COTTON_MECH, _COTTON_SOURCES)
    v = {"enabled": True, "resolved": dict(_COTTON_RESOLVED)}
    pruned = an._prune_orphan_evidence_handles(d, v, market_register=mr)
    block = an._cited_sources_block(d, v, [], market_register=mr)
    body = reg.sanitize(d["tldr"] + " " + d["mechanism"] + block, market_register=mr)
    return d, pruned, block, body


def test_fix2_a_resolved_row_survives_the_outlook_register_that_used_to_delete_it():
    """[E3]'s snippet is a WASDE price forecast: the OUTLOOK register refuses that sentence, and BEFORE
    this fix the refusal took the whole footer ROW with it, leaving `[E3]` dangling in the prose. The row
    is now emitted -- head first, snippet pre-cleared at row scope -- and the marker is answerable."""
    _d, _pruned, block, body = _cotton(reg.OUTLOOK)
    rows = [ln for ln in body.split("\n") if ln.startswith("[")]
    assert any(ln.startswith("[3] USDA WASDE (2014-01-01)") for ln in rows)
    assert not any("78 cents per pound" in ln for ln in rows)     # the LEVEL is still refused
    assert sorted(ln[1] for ln in rows) == ["1", "2", "3", "4", "6"]
    assert "## Sources" in block


def test_fix2_the_separator_bug_two_rows_never_share_a_line():
    """The adjudicator's shape, byte-exact from gate-7 cov2:
        "[3] USDA WASDE (2014-01-01): U.S. [4] World Bank Commodity Markets Outlook (2013-10-01): ..."
    `register._SENT_KEEP` captures `[.!?;]\\s+`, so a dropped unit took the row's terminating newline with
    it. Rows are newline-separated regardless of snippet content, now on two independent counts: nothing
    of a row is left for the body pass to drop, and a dropped unit leaves its newlines behind."""
    for mr in (reg.FENCED, reg.OUTLOOK):
        _d, _pruned, _block, body = _cotton(mr)
        for ln in body.split("\n"):
            assert ln.count("] ") <= 1 or not ln.startswith("["), (mr, ln)
            assert "U.S. [4]" not in ln, (mr, ln)


def test_fix2_a_snippet_carrying_newlines_still_renders_as_one_line():
    """A 140-char snippet is raw corpus text and may contain line breaks of its own; a row that spans two
    lines is the same defect from the other direction."""
    d = _structured("cited [E1].", "", [{"ref": 1, "source": "s", "date": "2020-01-01"}])
    v = {"enabled": True, "resolved": {"1": {"source": "usda_wasde", "date": "2014-01-01",
                                             "snippet": "Line one\nline two\n\nline three"}}}
    block = an._cited_sources_block(d, v, [])
    rows = [ln for ln in block.split("\n") if ln.startswith("[")]
    # CYCLE-10-AMEND (2026-08-08), REVIEW MINOR 4: the row now TERMINATES itself (trailing "."), so no
    # sentence splitter of the `([.!?;]\s+)` family can fuse it with the row below. One line, one unit.
    assert rows == ["[1] USDA WASDE (2014-01-01): Line one line two line three."]


def test_fix2_a_row_whose_snippet_is_entirely_refused_keeps_its_attribution():
    """The row is NOT its snippet. When nothing of the quoted text may be shown, the reader still gets the
    source and the date -- which is what a marker click needs -- rather than nothing at all."""
    d = _structured("cited [E1].", "", [{"ref": 1, "source": "s", "date": "2020-01-01"}])
    v = {"enabled": True, "resolved": {"1": {"source": "usda_wasde", "date": "2014-01-01",
                                             "snippet": "Prices are forecast at 78 cents per pound."}}}
    block = an._cited_sources_block(d, v, [], market_register=reg.OUTLOOK)
    assert "[1] USDA WASDE (2014-01-01)" in block and "78 cents" not in block
    assert an._prune_orphan_evidence_handles(d, v, market_register=reg.OUTLOOK) == 0
    assert "[E1]" in d["tldr"]


def test_fix2_the_register_gate_itself_is_not_relaxed():
    """The banned sentence is still refused wherever it appears -- the fix moves what its refusal COSTS,
    never what is refused. `register_leaks` on the assembled body stays empty."""
    _d, _pruned, _block, body = _cotton(reg.OUTLOOK)
    assert reg.register_leaks(body) == []
    assert "78 cents per pound" not in body


def test_fix2_a_dropped_prose_sentence_leaves_its_line_break_behind():
    """The structural backstop in `register._strip_banned_sentences`, stated on its own: dropping a unit
    removes its TEXT, never the line structure around it. Whitespace only -- no strip decision moves."""
    src = "The record holds.\nPrices are forecast at 78 cents per pound.\nThe next line stands.\n"
    out = reg.sanitize(src, market_register=reg.OUTLOOK)
    assert "78 cents" not in out
    assert "The record holds." in out and "The next line stands." in out
    assert "holds. The next" not in out                       # the weld this pin exists to forbid


# ══ FIX 3 -- THE PRUNE'S AUTHORITY IS THE RENDERED FOOTER ══════════════════════════════════════════

def test_fix3_evidence_exists_the_row_is_emitted_and_the_marker_is_KEPT():
    """ORDER: FIX 2 runs first. Every ref whose evidence resolved gets a row -- including [E3], whose row
    the register used to delete -- so no marker for a resolvable source is pruned on either register."""
    for mr in (reg.FENCED, reg.OUTLOOK):
        d, pruned, block, _body = _cotton(mr)
        for ref in ("1", "2", "3", "4", "6"):
            assert ("[E%s]" % ref) in (d["tldr"] + d["mechanism"]), (mr, ref)
            assert ("[%s] " % ref) in block, (mr, ref)
        assert pruned == 2, mr                                # [E5] and [E7] only -- see below


def test_fix3_evidence_genuinely_absent_the_marker_is_PRUNED():
    """The backstop, unchanged in kind: [E5] and [E7] have no ledger entry at all, so the footer can never
    answer for them and they leave the page. A sentence is never killed -- only the token goes."""
    d, pruned, block, _body = _cotton(reg.OUTLOOK)
    assert pruned == 2
    assert "[E5]" not in d["mechanism"] and "[E7]" not in d["mechanism"]
    assert "revised down by 800,000 bales." in d["mechanism"]     # the sentence survives, minus the token
    assert "Reduced planting intentions followed." in d["mechanism"]
    assert "[5] " not in block and "[7] " not in block


def test_fix3_the_prune_reads_the_EMISSION_decision_not_a_parallel_rule():
    """The cycle-9 gap, closed: `live` is now `_emitted_evidence_refs`, which IS `_cited_sources_block`'s
    row walk. A ref that resolves but is skipped for ANY reason the emitter has (an [N]-namespace ref, a
    duplicate) is pruned, because the reader gets no row for it either way."""
    d = _structured("a [E1] b [E2].", "",
                    [{"ref": "N1", "source": "s", "date": "2020-01-01"},   # numbers namespace: no doc row
                     {"ref": 2, "source": "s", "date": "2020-01-01"}])
    v = {"enabled": True, "resolved": {"N1": {"source": "x", "date": "d", "snippet": "y"},
                                       "2": {"source": "usda_wasde", "date": "2014-01-01",
                                             "snippet": "A plain sentence."}}}
    assert an._emitted_evidence_refs(d, v) == {"2"}
    assert an._prune_orphan_evidence_handles(d, v) == 1
    assert d["tldr"] == "a b [E2]." and "[E1]" not in d["tldr"]


def test_fix3_the_two_key_rule_from_cycle9_blocker2_still_holds():
    """An E-form / zero-padded / float ledger `ref` keys the FOOTER while the prose keys on the digit.
    Both keys are still held, so a resolved, footer-backed citation is never pruned."""
    for spelling in ("E1", "e1", "01", "E01", 1.0, "1", 1):
        d = _structured("cited [E1].", "", [{"ref": spelling, "source": "s", "date": "2020-01-01"}])
        key = str(spelling).strip().strip("[]")
        v = {"enabled": True, "resolved": {key: {"source": "usda_wasde", "date": "2014-01-01",
                                                 "snippet": "A plain sentence."}}}
        assert an._prune_orphan_evidence_handles(d, v) == 0, spelling
        assert "[E1]" in d["tldr"], spelling


def test_fix3_a_grouped_E_token_is_narrowed_never_dropped_whole():
    """Every conservative property of the cycle-9 prune rides the new authority unchanged."""
    d = _structured("both [E2, E5] here.", "", [{"ref": 2, "source": "s", "date": "2020-01-01"}])
    v = {"enabled": True, "resolved": {"2": {"source": "usda_wasde", "date": "2014-01-01",
                                             "snippet": "A plain sentence."}}}
    assert an._prune_orphan_evidence_handles(d, v) == 1
    assert d["tldr"] == "both [E2] here."


# == CYCLE-10-AMEND (2026-08-08) -- THE FOOTER IS NOT PART OF THE REGISTER'S TEXT ====================
#
# THE REVIEW'S TWO MAJORS, ONE ROOT. FIX 2 pre-cleared each row's SNIPPET and then still handed the
# ASSEMBLED footer to the body-wide `reg.sanitize`. The one interaction that survived is not about
# snippets at all: `register._CIT_HANDLE` is `\[[EN]\d+\]` (register.py:283) so a row's own "[10]" is not
# a citation, and `register._level_tokens` (register.py:434) takes any token of >= 2 integer digits, so
# "[10]" READS AS AN UNBACKED PRICE LEVEL. On an OUTLOOK turn every row with ref >= 10 was deleted with a
# perfectly clean snippet -- and with it the "## Sources" heading when it was the last row standing.
# Measured before the amendment: 12 clean rows in, refs 1-9 out; 37.5% of rows lost on a 4,000-footer
# sweep; and the [E] prune (whose authority IS the emission decision) kept every marker, so markers
# [E10]+ resolved to nothing.
# THE REMEDY IS STRUCTURAL: the footer is assembled from row-scope-cleared rows and appended AFTER the
# body pass, so the register never sees it. Marker-as-level, row-head deletion, row fusion and the
# separator weld are all unreachable BY CONSTRUCTION.

_AMEND_SNIP = "Ending stocks rise on the month."


def _amend_doc(n, first=1, snippet=None, vary=False):
    """A ledger of `n` CLEAN document sources, refs `first`..`first+n-1`, each cited once in the tldr."""
    refs = [str(i) for i in range(first, first + n)]
    d = _structured("A claim " + "".join("[E%s]" % r for r in refs) + ".", "",
                    [{"ref": int(r), "source": "s", "date": "2020-01-01"} for r in refs])
    v = {"enabled": True,
         "resolved": {r: {"source": "usda_wasde", "date": "2014-01-01",
                          "snippet": ("Ending stocks rise in month %s." % r) if vary
                                     else (snippet or _AMEND_SNIP)} for r in refs}}
    return refs, d, v


def _served(d, v, mr):
    """The production assembly, spelled EXACTLY as both call sites now spell it (answer.py L2 body and
    one-hop body): prune -> footer from pre-cleared rows -> body-wide sanitize -> APPEND the footer."""
    pruned = an._prune_orphan_evidence_handles(d, v, market_register=mr)
    footer = an._cited_sources_block(d, v, [], market_register=mr)
    return pruned, reg.sanitize(an.render(d, include_ledger=False), market_register=mr) + footer


def _rows_reaching(body, refs):
    import re
    return [r for r in refs if re.search(r"(?m)^\[" + re.escape(r) + r"\]", body)]


def test_amend_major1_a_row_whose_ref_is_ten_reaches_the_reader_on_an_outlook_turn():
    """The minimal reproducer, inverted into a pin: ONE source, a snippet with no level in it at all, an
    outlook turn. ref 9 always survived; ref 10 was deleted by its own marker."""
    for ref in (9, 10, 11, 47, 100):
        refs, d, v = _amend_doc(1, first=ref)
        pruned, body = _served(d, v, reg.OUTLOOK)
        assert pruned == 0, ref
        assert _rows_reaching(body, refs) == refs, ref
        assert "## Sources" in body, ref                       # the heading went with the last row
        assert _AMEND_SNIP in body, ref                        # ...and the clean snippet is intact


def test_amend_major1_the_root_cause_is_pinned_the_body_pass_would_still_delete_the_row():
    """WHY the assembly order is load-bearing, stated on the mechanism rather than on the outcome: hand
    the SAME pre-cleared row to the body-wide pass and it is still deleted, because the deleter reads the
    row's own marker as a level. This pin fails the moment anyone puts the footer back inside sanitize."""
    _refs, d, v = _amend_doc(1, first=10)
    footer = an._cited_sources_block(d, v, [], market_register=reg.OUTLOOK)
    assert "[10] " in footer                                    # emitted, clean, one line
    through_the_body_pass = reg.sanitize(footer, market_register=reg.OUTLOOK)
    assert "[10] " not in through_the_body_pass                 # ...and deleted if the pass ever sees it
    assert reg._level_tokens("[10] USDA WASDE (2014-01-01).") == ["10"]
    assert reg._level_tokens("[9] USDA WASDE (2014-01-01).") == []


def test_amend_major2_twelve_clean_sources_every_row_reaches_and_every_marker_resolves():
    """THE [E] PRUNE'S AUTHORITY GAP, CLOSED BY THE SAME CHANGE. The prune keeps a marker when the
    emitter emits a row; the reader received the marker and not the row. Both directions, one page."""
    refs, d, v = _amend_doc(12)
    pruned, body = _served(d, v, reg.OUTLOOK)
    assert pruned == 0
    assert _rows_reaching(body, refs) == refs                   # all 12 rows reach the reader
    assert [r for r in refs if ("[E%s]" % r) in d["tldr"]] == refs   # ...and all 12 markers still resolve
    assert body.count("## Sources") == 1


def test_amend_the_register_gate_is_still_not_relaxed_by_the_new_assembly():
    """The footer bypasses the BODY pass, never the register: `_source_row_snippet` runs the identical
    instrument at row scope and is now the ONLY gate the footer gets. The banned level is still refused
    -- from a row whose ref is 10, which is the row the old order could not even keep."""
    _refs, d, v = _amend_doc(1, first=10,
                             snippet="U.S. cotton prices are forecast at 78 cents per pound.")
    _pruned, body = _served(d, v, reg.OUTLOOK)
    assert "[10] USDA WASDE (2014-01-01)" in body               # the ATTRIBUTION reaches the reader
    assert "78 cents per pound" not in body                     # the LEVEL does not
    assert reg.register_leaks(body) == []


def test_amend_minor4_every_rendered_row_terminates_itself():
    """A head-only row carried no sentence terminator, so ANY `([.!?;]\\s+)` splitter fused it with the
    row below and one banned neighbour took a good attribution with it. Nine head-only rows, nine units."""
    _refs, d, v = _amend_doc(9, snippet="78")                   # a bare numeral: nothing may be shown
    rows = [row for _r, row in an._document_source_rows(d, v, market_register=reg.OUTLOOK)]
    assert rows == ["[%d] USDA WASDE (2014-01-01)." % i for i in range(1, 10)]
    units = [u for u in reg._SENT_KEEP.split("\n".join(rows))[::2] if u.strip()]
    assert len(units) == 9                                      # one unit per row -- no fusion


def test_amend_minor4_a_head_only_row_can_no_longer_take_its_neighbour_down():
    """The harm the terminator removes, stated end to end on the shape that produced it: a refused-snippet
    row followed by a good one. Both rows reach the reader, on both registers."""
    for mr in (reg.FENCED, reg.OUTLOOK):
        d = _structured("a [E1] b [E2].", "", [{"ref": 1, "source": "s", "date": "2020-01-01"},
                                               {"ref": 2, "source": "s", "date": "2020-01-01"}])
        v = {"enabled": True,
             "resolved": {"1": {"source": "usda_wasde", "date": "2014-01-01", "snippet": "78"},
                          "2": {"source": "usda_wasde", "date": "2014-01-01",
                                "snippet": "Mill use is projected marginally higher."}}}
        _pruned, body = _served(d, v, mr)
        assert _rows_reaching(body, ["1", "2"]) == ["1", "2"], mr
        assert "Mill use is projected marginally higher." in body, mr


def test_amend_minor3_the_second_row_walk_costs_no_second_register_pass():
    """REVIEW MINOR 3, the register budget. The walk runs twice per turn by design (see below); what is
    removed is the DUPLICATED WORK -- one `reg.sanitize` per distinct snippet per process, not per walk."""
    an._row_snippet_cleared.cache_clear()
    _refs, d, v = _amend_doc(12, vary=True)                     # 12 DISTINCT snippets
    an._emitted_evidence_refs(d, v, market_register=reg.OUTLOOK)          # walk 1 (the prune's)
    first = an._row_snippet_cleared.cache_info().misses
    an._cited_sources_block(d, v, [], market_register=reg.OUTLOOK)        # walk 2 (the render's)
    assert first == 12
    assert an._row_snippet_cleared.cache_info().misses == 12     # walk 2 sanitized nothing


def test_amend_minor3_the_second_walk_is_still_FRESH_and_that_is_why_it_is_a_walk():
    """WHY the two readers do NOT share one precomputed walk. `_maybe_scaffold_episodes` APPENDS to
    `structured['sources']` and rebinds `verifier['resolved']` (answer.py:3324) BETWEEN the prune
    (answer.py:2139) and the render (answer.py:2177). A walk cached at prune time and replayed at render
    time would drop every synthesized episode-receipt row while its [E] marker stayed on the page."""
    _refs, d, v = _amend_doc(2)
    an._prune_orphan_evidence_handles(d, v, market_register=reg.OUTLOOK)
    d["sources"].append({"ref": 99, "source": "s", "date": "2020-01-01"})       # the scaffold's mint
    v["resolved"]["99"] = {"source": "usda_wasde", "date": "2014-01-01", "snippet": _AMEND_SNIP}
    block = an._cited_sources_block(d, v, [], market_register=reg.OUTLOOK)
    assert "[99] USDA WASDE (2014-01-01)" in block


def test_amend_the_off_arm_footer_still_rides_INSIDE_the_body_pass():
    """CONTAINMENT, on BOTH synthesis paths. Only the validated, row-cleared block moved out of the
    sanitize input. The legacy two-list footer (GRAPHRAG_VERIFY=off) is not row-cleared, so it must keep
    its body-wide pass -- and the OFF arm's bytes must not move at all."""
    import inspect
    for fn in (an._answer_l2, an.answer):
        src = inspect.getsource(fn)
        assert "_sanitize_in = render(structured) + footer" in src
        assert "body = reg.sanitize(_sanitize_in, market_register=_mr) + _footer" in src
