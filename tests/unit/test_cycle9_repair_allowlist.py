"""CYCLE-9 (2026-08-08) -- the repair-eligibility ALLOWLIST, grouped-handle parsing, the [E] orphan prune
and the pre/post-verify attribution boundary.

GATE-6 (commit d108883e, image 68277e92) shipped TWO prose corruptions and both came out of `verify`'s
REPAIR path, on one deck, in one pair of runs:

  COV1 `ab_amb_elnino` (mechanism)  {rule: number_mismatch_repaired, from "1.5", to "0"}
      "does the anomaly continue rising toward the 1.5 degC threshold"
        -> "... rising toward the 0 degC threshold"
      0 degC is ENSO-NEUTRAL. The cycle-8-review MAJOR-5 conditional-threshold fence needs BOTH a
      conditional marker and a comparison preposition; "threshold" supplied the first and `_THRESHOLD_LEAD`
      knew only verbs of CROSSING, so a verb of APPROACHING lost the second clause.

  COV2 `ab_amb_elnino` (tldr)       {rule: number_mismatch_repaired, from "0.98", to "1"}
      "The ONI anomaly is at 0.98 degC" -> "at 1 degC"
      The 1 is `el_nino_flag`, a row whose unit is literally "0/1" -- a boolean spliced into a degC slot.
      The cross-class fence reads `if src_cls and tgt_cls and src_cls != tgt_cls`, so an UNCLASSIFIABLE
      source SKIPPED it entirely: fail-open on the source side.

  ROOT ENABLER (both): `verify._HANDLE` parsed SOLITARY brackets only. The renderer writes GROUPED
      citations, and the tldr sentence's `[N5, N10, N12]` -- which carries the very row that materializes
      0.98 -- was invisible, so `_sibling_backed` could find no backer and a sentence that was correctly
      cited was handed to the repair path as single-handle-mismatched.

Neither corruption was a NEW hole. Each was a shape a DENY-LIST had never been asked about, which is the
structural fact this cycle fixes: eligibility is now an ALLOWLIST and the default is REFUSE.
"""
from __future__ import annotations

import re

from leviathan.graphrag import answer as an
from leviathan.graphrag import verify as vf


def _structured(tldr="", mechanism="", sources=None):
    return {"tldr": tldr, "mechanism": mechanism, "sources": list(sources or [])}


def _call(metric, value, unit=None, table="t"):
    row = {"value": value, **({"unit": unit} if unit else {})}
    return {"query": {"table": table, "metric": metric}, "rows": [row], "shown": [float(value)]}


def _pad(n):
    return [{"query": {"metric": ""}, "rows": []} for _ in range(n)]


# ══ THE TWO GATE-6 CORRUPTIONS, REPLAYED ════════════════════════════════════════════════════════════

COV1_SENT = ("- **ONI trajectory**: does the anomaly continue rising toward the 1.5 °C threshold that "
             "historically coincides with more severe regional impacts, or plateau and fade as it did in "
             "mid-2016 [N4]?")
COV1_CALLS = _pad(3) + [_call("oni_anom", 0.0, "degC", table="gold_weather_z")]

COV2_SENT = ("The ONI anomaly is at 0.98 °C and has risen for five consecutive months [N5, N10, N12], "
             "putting the ENSO signal firmly in El Niño territory [N2] — but at moderate strength, "
             "not the record-strength event of 2015.")
COV2_CALLS = (_pad(1)
              + [_call("el_nino_flag", 1, "0/1", table="gold_weather_z")]        # N2
              + _pad(1)
              + [_call("oni_anom", 0.0, "degC", table="gold_weather_z")]          # N4
              + [_call("oni_anom", 0.98, "degC", table="gold_weather_z")]         # N5
              + _pad(4)
              + [_call("oni_anom_pace_streak", 5, "months", table="gold_weather_z")]   # N10
              + [_call("oni_anom_pace_change", 0.47, "degC", table="gold_weather_z")]  # N11
              + [_call("oni_anom_pace_streak", 5, "months", table="gold_weather_z")])  # N12


def test_gate6_corruption_1_the_approach_threshold_is_never_rewritten():
    """COV1. The charge is real (1.5 is not [N4]'s 0), so the sentence still answers for itself -- but the
    remedy is the fail-closed DROP, never the rewrite. REFUSED BY CLAUSE (c): the widened `_THRESHOLD_LEAD`
    now reads 'toward', and `_COND_CTX` already read 'threshold'. Both halves of MAJOR 5, at last.

    CYCLE-10 (2026-08-08): the CHARGE and the OUTCOME are unchanged and are what this pin now asserts;
    the two clause internals it used to reach into (`_THRESHOLD_LEAD`, `_COND_CTX`) are deleted, because
    the refusal no longer depends on recognising the shape of the sentence at all."""
    assert vf._check_number_handle(COV1_SENT, 4, COV1_CALLS) == "number_mismatch"
    assert vf._num_repair(COV1_SENT, 4, COV1_CALLS) is None
    assert not hasattr(vf, "_THRESHOLD_LEAD") and not hasattr(vf, "_COND_CTX")
    s = _structured(mechanism=COV1_SENT)
    rep = vf.verify_citations(s, [], COV1_CALLS)
    assert "0 °C threshold" not in s["mechanism"] and s["mechanism"] == ""
    assert rep["repaired"] == 0 and rep["repairs"] == []
    assert rep["by_rule"] == {"number_mismatch": 1}


def test_gate6_corruption_1_the_whole_approach_verb_set():
    """The lead set is widened to APPROACH, not to one spelling of it. Every one of these is a threshold the
    prose is reasoning about, and none may be overwritten with the current level."""
    for lead in ("toward the", "towards the", "approaching the", "nearing the", "near the",
                 "up to the", "short of the", "shy of the"):
        sent = f"Watch whether the anomaly keeps rising {lead} 1.5 degC threshold [N1]."
        assert vf._num_repair(sent, 1, [_call("oni_anom", 0.0, "degC")]) is None, lead


def test_gate6_corruption_1_a_bare_approach_is_refused_too_now_cycle10():
    """MAJOR 5's scoping rule kept the descriptive twin repairable so the fence could not over-refuse.
    CYCLE-10 removes the distinction along with the writer: threshold and description get one answer."""
    sent = "The anomaly moved toward 1.5 degC last month [N1]."
    assert vf._num_repair(sent, 1, [_call("oni_anom", 0.9, "degC")]) is None
    s = _structured(mechanism=sent)
    rep = vf.verify_citations(s, [], [_call("oni_anom", 0.9, "degC")])
    assert s["mechanism"] == "" and rep["repairs"] == []


def test_gate6_corruption_2_the_boolean_is_never_spliced_into_a_degC_slot():
    """COV2. TWO independent clauses refuse it, and the FIRST one means the repair path is never reached at
    all: with the group parsed, [N5] materializes 0.98, so `_sibling_backed` is True and the remedy is the
    r5 one -- strip the mis-citing [N2], leave the corroborated figure standing.
    Forced past that, `_num_repair` refuses on clause (a) (two handle tokens in the slot, one of them
    grouped) and on clause (b) (the source class is `flag`, which may never source a repair)."""
    assert vf._check_number_handle(COV2_SENT, 2, COV2_CALLS) == "number_mismatch"
    assert vf._sibling_backed(COV2_SENT, 2, COV2_CALLS) is True          # clause (a)'s predecessor
    assert vf._num_repair(COV2_SENT, 2, COV2_CALLS) is None
    assert not hasattr(vf, "_call_unit_class")            # CYCLE-10: the class fence is gone entirely
    s = _structured(tldr=COV2_SENT)
    rep = vf.verify_citations(s, [], COV2_CALLS)
    assert "at 1 °C" not in s["tldr"] and "0.98 °C" in s["tldr"]   # the figure survives intact
    assert "[N2]" not in s["tldr"] and "[N5, N10, N12]" in s["tldr"]      # only the mis-citation goes
    assert rep["repaired"] == 0 and rep["repairs"] == []
    assert rep["by_rule"] == {"number_mismatch": 1}


# ══ FIX 1 -- REPAIR ELIGIBILITY IS AN ALLOWLIST ═════════════════════════════════════════════════════

def test_allowlist_a_two_solitary_handles_in_one_slot_are_ineligible():
    """(a) Two handles are two candidate sources for one numeral and nothing checks that they agree about
    which row it came from. Even when they DO agree -- the cycle-4 '[N12][N4]' judge fixture -- the slot is
    ambiguous by construction and takes the drop.

    CYCLE-9 REVIEW: the numerals are unsigned and the scale gap is 2.3x so that clause (e) (MAJOR 4) is
    not the thing refusing -- the SOLO control has to repair or this pin proves nothing about (a).

    CYCLE-10: the SOLO control -- the shape clause (a) deliberately still admitted -- is refused as well,
    so this pin no longer separates (a) from the rest. It is kept as the fixture that proves the
    two-handle ambiguity NEVER became repairable at any point in the cycle-4..10 sequence."""
    agree = _pad(3) + [_call("oni_anom", 0.31, "degC")] + _pad(7) + [_call("oni_anom", 0.31, "degC")]
    assert vf._num_repair("Anomalies ran 0.72 degC [N12][N4].", 12, agree) is None
    solo = _pad(3) + [_call("oni_anom", 0.31, "degC")]
    assert vf._num_repair("Anomalies ran 0.72 degC [N4].", 4, solo) is None


def test_allowlist_a_a_grouped_handle_can_never_name_a_repair_source():
    """(a) A grouped token stands in for MANY rows behind ONE marker; it names no single repair source."""
    calls = [_call("oni_anom", 0.06, "degC"), _call("oni_anom", 0.06, "degC")]
    assert vf._num_repair("Anomalies ran -0.72 degC [N1, N2].", 1, calls) is None
    assert vf._num_repair("Anomalies ran -0.72 degC [N1-N2].", 1, calls) is None


def test_allowlist_b_unknown_on_either_side_is_ineligible_fail_closed():
    """(b) THE INVERSION. Unknown used to mean 'no opinion, repair as before'; it now costs eligibility.
    Unknown SOURCE is the door the COV2 corruption came through; unknown TARGET is fenced with it, because
    a class the module cannot name is a class it cannot certify in either direction.

    CYCLE-10: the inversion is complete rather than partial -- the KNOWN-and-EQUAL arm, the one shape
    (b) still admitted, is refused too. Gate-7 is the reason: its corruption held a known, equal pair."""
    known = _call("oni_anom", 2.75, "degC")
    unknown_src = {"query": {"metric": "m"}, "rows": [{"value": 2.75}], "shown": [2.75]}
    assert vf._num_repair("It peaked at +2.47 degC [N1].", 1, [unknown_src]) is None
    assert vf._num_repair("It peaked at +2.47 furlongs [N1].", 1, [known]) is None
    assert vf._num_repair("It peaked at +2.47 degC [N1].", 1, [known]) is None


def test_allowlist_b_cross_class_stays_refused_and_the_flag_class_is_absolute():
    """(b) The cycle-7/8 cross-class refusals are unchanged, and the boolean class is barred OUTRIGHT --
    a 0/1 flag is not a magnitude in any dimension, so it may not even write into another flag slot."""
    pct = _call("oni_anomaly_pct", 18.0, "%")
    assert vf._num_repair("The anomaly reached +0.98 degC [N1].", 1, [pct]) is None
    mass = _call("m", 31.4, "MMT")
    assert vf._num_repair("Cash traded at $4.20 [N1].", 1, [mass]) is None
    flag = _call("el_nino_flag", 1, "0/1")
    assert vf._num_repair("The flag reads 0 flag [N1].", 1, [flag]) is None
    assert vf._num_repair("The anomaly is 0.98 degC [N1].", 1, [flag]) is None


def test_allowlist_b_the_flag_class_no_longer_needs_to_be_readable_at_all_cycle10():
    """Cycle-9 needed the boolean class readable from the ROW's unit, the card and the metric NAME, so a
    flag could not slip through as 'unknown'. CYCLE-10 needs none of it: the row is refused whether or not
    anything can name its class, and the three readers are deleted."""
    for gone in ("_unit_class", "_call_unit_class", "_metric_tell_class", "_registry_unit_class"):
        assert not hasattr(vf, gone), gone
    assert vf._num_repair("The anomaly is 0.98 degC [N1].", 1, [_call("whatever", 1, "0/1")]) is None
    bare = {"query": {"metric": "el_nino_flag"}, "rows": [{"value": 1}], "shown": [1.0]}
    assert vf._num_repair("The anomaly is 0.98 degC [N1].", 1, [bare]) is None


def test_allowlist_d_the_cycle8_fences_all_still_hold():
    """(d) Nothing the earlier cycles closed is reopened: the non-value slot (window length / ordinal /
    percent-of), the MAJOR-4 pre-amendment ambiguity count, the scale word, and the (d2) percent lock."""
    z = _call("urea_usd_mt_zscore_5yr", 0.195159, "sigma")
    assert vf._num_repair("currently below the 5-year mean [N1]", 1, [z]) is None
    assert vf._num_repair("at the 3rd consecutive print [N1]", 1, [z]) is None
    assert vf._num_repair("gas sits at a 5-year z-score of +1.24 sigma [N1]", 1, [z]) is None
    mt = _call("production_cpo_mt", 1629801.0, "MT")
    assert vf._num_repair("roughly 2 percent below the five-year average [N1]", 1, [mt]) is None
    assert vf._num_repair("Ending stocks were 48.2 million MT [N1].", 1,
                          [_call("m", 31400000, "MT")]) is None


def test_allowlist_the_ineligible_path_is_the_honest_drop_never_a_rewrite():
    """Every refusal lands on the SAME fail-closed path with its audit record: the sentence goes, `repaired`
    stays 0, `repairs` stays empty, and the strip is counted under the rule it was charged with. An
    ineligible numeral is never silently left standing and never quietly rewritten."""
    import os
    os.environ["GRAPHRAG_STRIP_AUDIT"] = "on"
    try:
        s = _structured(mechanism="It peaked at +2.47 degC [N1].")
        rep = vf.verify_citations(s, [], [{"query": {"metric": "m"}, "rows": [{"value": 2.75}]}])
    finally:
        os.environ.pop("GRAPHRAG_STRIP_AUDIT", None)
    assert s["mechanism"] == ""
    assert rep["repaired"] == 0 and rep["repairs"] == []
    assert rep["by_rule"] == {"number_mismatch": 1} and rep["stripped"] == 1
    assert [e["rule"] for e in rep["strip_audit"]] == ["number_mismatch"]


def test_allowlist_the_last_repairing_population_is_now_empty_cycle10():
    """THE POPULATION THE ALLOWLIST ADMITTED, MEASURED AND THEN CLOSED. Cycle-9 pinned these six as the
    whole set of repairs that could still fire: source and target classes KNOWN and EQUAL, one solitary
    handle, plausible magnitude and sign. Gate-7's corruption is a member of exactly this set -- z into z,
    one handle, 0.6 vs 0.6267 -- which is why the set is now empty rather than smaller. Every one of the
    six drops, and nothing writes a numeral anywhere."""
    cases = [
        ("It peaked at +2.47 degC [N1].", _call("oni_anom", 2.75, "degC")),
        ("It peaked at +2.47 °C [N1].", _call("oni_anom", 2.75, "degC")),
        ("The metric rose in each of the last 4 months [N1].",
         _call("oni_anomaly_pace_streak", 5, "months")),
        ("gas sits at +1.24 sigma [N1]", _call("gas_zscore_5yr", 0.31, "sigma vs 5-yr mean")),
        ("stocks fell 4.2 percent on the year [N1]", _call("ending_stocks_mt_pct", 5.1, "%")),
        ("Output reached 92000000 MT [N1].", _call("ending_stocks_mt", 88500000, "MT")),
    ]
    for prose, call in cases:
        assert vf._num_repair(prose, 1, [call]) is None, prose


# ══ FIX 2 -- GROUPED / RANGED HANDLE PARSING (amendment 3a) ═════════════════════════════════════════

def test_grouped_handles_are_matched_whole_and_enumerated():
    """The forms the renderer actually writes. HEAD's solitary pattern matched NONE of them."""
    for token, want in (("[N5, N10, N12]", [("N", 5), ("N", 10), ("N", 12)]),
                        ("[N1-N4]", [("N", 1), ("N", 2), ("N", 3), ("N", 4)]),
                        ("[E2, E5]", [("E", 2), ("E", 5)]),
                        ("[N13; N14]", [("N", 13), ("N", 14)]),
                        ("[N3 and N9]", [("N", 3), ("N", 9)]),
                        ("[N5]", [("N", 5)]),
                        ("[E1b]", [("E", 1)]),
                        ("[3]", [("E", 3)])):
        assert vf._HANDLE.fullmatch(token), token
        assert vf._handle_members(token) == want, token


def test_a_bare_bracketed_year_range_is_still_not_a_handle():
    """The safety fence on the widening: a continuation member MUST carry its own N/E prefix. Without that,
    '[1980-1990]' parses as a grouped handle and two magnitudes silently leave claim extraction -- a
    verification LOSS inside an amendment sanctioned as loss-free."""
    for text in ("[1980-1990]", "[2, 3]", "[12/2026]", "[5900-9999]"):
        assert not vf._HANDLE.fullmatch(text), text
    # a bracketed MAGNITUDE range is the case with teeth: both numerals are claims and both must survive
    assert vf._claim_numbers_in(vf._HANDLE.sub("", "ranged [5900-9999] MT")) == [5900.0, 9999.0]
    # ...and the year form keeps the year exemption it always had, through the same substitution
    assert vf._claim_numbers_in(vf._HANDLE.sub("", "the window [1980-1990] held")) == []


def test_a_runaway_range_is_not_expanded():
    """`[N1-N400]` is not a citation. The cap is the renderer's own (`answer._N_RANGE_MAX`), restated."""
    assert vf._handle_members("[N1-N400]") == [("N", 1), ("N", 400)]
    assert vf._handle_members("[N9-N2]") == [("N", 9), ("N", 2)]        # never inverted


def test_sibling_backing_reads_every_grouped_member():
    """The gate-6 root enabler, in miniature: the row that materializes the figure is inside a group."""
    calls = [_call("el_nino_flag", 1, "0/1"), _call("oni_anom", 0.98, "degC"),
             _call("oni_anom_pace_streak", 5, "months")]
    sent = "The anomaly is at 0.98 degC over the run [N2, N3] and remains positive [N1]."
    assert vf._sibling_backed(sent, 1, calls) is True
    # ...and the guard still reads the POOL, not the mere presence of a group
    miss = [_call("el_nino_flag", 1, "0/1"), _call("oni_anom", 0.06, "degC"),
            _call("oni_anom", 0.31, "degC")]
    assert vf._sibling_backed(sent, 1, miss) is False


def test_a_grouped_token_is_never_newly_CHARGEABLE():
    """SCOPE. The amendment is BACKING VISIBILITY ONLY -- strictly error-reducing. A grouped token adds no
    strip, no drop and no `checked` count, so a sentence whose only handles are grouped is left alone even
    when its members would have failed every check."""
    calls = [_call("m", 9.9), _call("m", 8.8)]
    s = _structured(tldr="Exports ran 5.5 MMT [N1, N2] last season.")
    rep = vf.verify_citations(s, [], calls)
    assert s["tldr"] == "Exports ran 5.5 MMT [N1, N2] last season."
    assert rep["checked"] == 0 and rep["stripped"] == 0 and rep["by_rule"] == {}


def test_a_group_cited_numbers_row_keeps_its_ledger_entry():
    """`_kinds` is built over MEMBERS now. An index cited only in grouped form used to be absent from that
    map, so `_is_number_declaration` could not recognize its ledger row and the row stripped as a
    fabricated_citation -- a footer line deleted for the crime of being cited in a group."""
    s = _structured(tldr="Both legs held [N1, N2].",
                    sources=[{"ref": "2", "source": "numbers", "date": ""}])
    rep = vf.verify_citations(s, [], [_call("m", 1.0), _call("m", 2.0)])
    assert s["sources"] == [{"ref": "2", "source": "numbers", "date": ""}]
    assert rep["by_rule"].get("fabricated_citation", 0) == 0


def test_a_group_cited_evidence_item_backs_the_sentences_quoted_span():
    """The quoted-span verdict is a SENTENCE question over every cited pool. A span carried by a
    GROUP-cited source is backed for the sentence, exactly as a solitary co-citation already was."""
    ev = [{"source": "usda_wasde", "date": "2012-08-10",
           "text": "Record soybean and corn prices occurred in July and August 2012 due to the drought."},
          {"source": "usda_gain_corn", "date": "2026-01-01",
           "text": "Chinese corn imports slowed markedly through the marketing year."}]
    prose = ('The record shows "Record soybean and corn prices occurred" in that window [E1, E2] '
             'with imports slowing [E2].')
    s = _structured(tldr=prose, sources=[{"ref": "1", "source": "usda_wasde", "date": "2012-08-10"},
                                         {"ref": "2", "source": "usda_gain_corn", "date": "2026-01-01"}])
    rep = vf.verify_citations(s, ev, [])
    assert rep["by_rule"].get("quote_mismatch", 0) == 0
    assert "[E1, E2]" in s["tldr"]


def test_the_orphan_fragment_reader_now_sees_a_grouped_citation_as_content():
    """`answer._orphan_has_content` asks `verify._HANDLE` whether a fragment carries something a reader
    would LOSE. A fragment whose only citation was grouped read as CONTENTLESS and could be deleted."""
    assert an._orphan_has_content("as the two legs showed [N5, N10, N12]") is True


# ══ FIX 3 -- THE [E] ORPHAN PRUNE ══════════════════════════════════════════════════════════════════

def test_fix3_the_dcw_urea_zscore_both_pass_shape_is_pruned():
    """THE MEASURED SHAPE, pinned exactly. `dcw_urea_zscore` carried [E1] and [E2] in prose while the
    rendered `## Sources` block held [N] rows ONLY -- in BOTH dcw passes, so it is reproducible and not a
    sampling artifact. Every [E] marker on that page was dangling."""
    s = _structured(
        tldr="A USDA GAIN report notes peanuts could displace corn if fertilizer prices rise [E1].",
        mechanism=("Costs fell drastically by MY 2023/24 [E2], and in China corn fertilizer costs rose "
                   "35.8% [E1]."),
        sources=[])                                       # ...no ledger row survived: the shape as shipped
    n = an._prune_orphan_evidence_handles(s, {"resolved": {}})
    assert n == 3
    assert "[E" not in s["tldr"] and "[E" not in s["mechanism"]
    assert s["tldr"] == "A USDA GAIN report notes peanuts could displace corn if fertilizer prices rise."
    assert s["mechanism"] == "Costs fell drastically by MY 2023/24, and in China corn fertilizer costs rose 35.8%."


def test_fix3_an_empty_sources_block_with_live_markers_is_impossible():
    """The invariant, stated as the join it makes total: after the prune, every [E] ref the reader can still
    see has a row in the block the renderer builds from the SAME two inputs."""
    s = _structured(tldr="One leg is receipted [E1] and one is not [E2].",
                    sources=[{"ref": "1", "source": "usda_wasde", "date": "2012-08-10"},
                             {"ref": "2", "source": "ghost_wire", "date": "2026-01-01"}])
    vreport = {"resolved": {"1": {"source": "usda_wasde", "date": "2012-08-10", "snippet": "..."}}}
    assert an._prune_orphan_evidence_handles(s, vreport) == 1
    block = an._cited_sources_block(s, vreport, [])
    prose_refs = set(re.findall(r"\[E(\d+)", s["tldr"] + s["mechanism"]))
    block_refs = set(re.findall(r"^\[(\d+)\]", block, re.M))
    assert prose_refs == {"1"} and prose_refs <= block_refs


def test_fix3_a_grouped_evidence_token_is_narrowed_never_dropped_whole():
    """The [N] rule restated: a group is only as good as its worst member, and the smallest remedy that
    leaves the join total is to keep the members that resolve."""
    s = _structured(tldr="Both windows are documented [E1, E2, E3].",
                    sources=[{"ref": r, "source": "s", "date": ""} for r in ("1", "2", "3")])
    assert an._prune_orphan_evidence_handles(s, {"resolved": {"2": {}}}) == 2
    assert s["tldr"] == "Both windows are documented [E2]."


def test_fix3_the_prune_never_kills_a_sentence_and_never_touches_the_bare_namespace():
    """An [E] handle stands in for NOTHING -- it is an attribution, not a promised figure -- so the token is
    the whole remedy and the prose survives. And the BARE positional `[3]` spelling is out of scope by
    construction: its duplicate-row decision is recorded and deliberately unfixed elsewhere."""
    s = _structured(tldr="The channel is live [E9].", sources=[])
    assert an._prune_orphan_evidence_handles(s, {"resolved": {}}) == 1
    assert s["tldr"] == "The channel is live."
    bare = _structured(tldr="The channel is live [3].", sources=[])
    assert an._prune_orphan_evidence_handles(bare, {"resolved": {}}) == 0
    assert bare["tldr"] == "The channel is live [3]."


def test_fix3_a_total_join_is_a_no_op_and_never_raises():
    """OFF-arm-clean: a turn whose every [E] marker has a row is byte-identical, and a malformed report
    cannot be the thing that breaks an answer."""
    s = _structured(tldr="Documented in the record [E1].",
                    sources=[{"ref": "1", "source": "s", "date": ""}])
    before = dict(s)
    assert an._prune_orphan_evidence_handles(s, {"resolved": {"1": {}}}) == 0
    assert s == before
    assert an._prune_orphan_evidence_handles(None, None) == 0
    assert an._prune_orphan_evidence_handles({"tldr": None}, {"resolved": None}) == 0


# ══ FIX 4 -- THE ATTRIBUTION BOUNDARY ══════════════════════════════════════════════════════════════

def test_fix4_the_two_new_boundaries_ride_the_existing_audit_flag(monkeypatch):
    """ADDITIVE, and on the flag `raw_draft` already uses -- no new switch, no new cost class. Off -> None,
    so the key stays ABSENT rather than null and every unaudited trace is byte-identical."""
    monkeypatch.delenv("GRAPHRAG_STRIP_AUDIT", raising=False)
    assert an.raw_draft_snapshot(preverify_tldr="x", postverify_tldr="y") is None
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    # CYCLE-9 REVIEW, MINOR 9: the boundary keys are EXEMPT from the falsy drop (see the pin below); every
    # other caller's key still disappears when its field is empty.
    assert an.raw_draft_snapshot(preverify_tldr="x", tldr="") == {"preverify_tldr": "x"}
    folded = an._fold_draft({"tldr": "d"}, an.raw_draft_snapshot(postverify_tldr="v"))
    assert folded == {"tldr": "d", "postverify_tldr": "v"}


def test_fix4_both_synthesis_bodies_close_the_interval():
    """The gate-6 adjudicator could not attribute a draft-vs-page numeral diff to the repair path: the next
    capture after `raw_draft` was taken AFTER `_resolve_number_handles`, so verify's rewrites and the handle
    pass's value SPLICES landed in ONE interval (10 surviving-sentence mutations against 2 recorded ops
    across the six gate-6 runs). Both bodies now snapshot on BOTH sides of `verify_citations`, and the
    one-hop body is included for the same reason A4/A4b are: it is the documented rollback lane."""
    import inspect
    for fn in (an._answer_l2, an.answer):                 # the L2 body and the GRAPHRAG_PLANNER=onehop lane
        src = inspect.getsource(fn)
        pre = src.index("preverify_tldr")
        ver = src.index("verify_citations(structured")
        post = src.index("postverify_tldr")
        assert pre < ver < post, fn.__name__
        assert post < src.index("_resolve_number_handles(structured"), fn.__name__


# == CYCLE-9 REVIEW (2026-08-08) -- THE ADVERSARIAL PASS =============================================
# The reviewer BLOCKED the first cut and reproduced every claim below through the shipped code. Three of
# the four fixes were breakable and two broke in the direction the cycle exists to prevent. One pin per
# closed finding, written against the reviewer's own measured shapes.

def test_review_b1_the_threshold_class_is_closed_not_just_its_preposition():
    """BLOCKER 1. Widening `_THRESHOLD_LEAD` closed the ONE SPELLING gate-6 shipped; the reviewer re-ran
    the same corruption with the preposition changed and 9 of 10 rewordings still wrote the row value over
    the stated threshold. A verb whitelist ANDed with a conditional-word list is a DENY-LIST, and clause
    (c) was the only fence standing between this sentence and the rewrite -- src and tgt are both `temp`,
    so (b) passes it. The allowlist question is asked of the SLOT: does the numeral modify a threshold
    NOUN? That holds whether or not the sentence is conditional, and the verb list survives as an OR."""
    row = [_call("oni_anom", 0.0, "degC")]
    for sent in ("if the anomaly climbs to the 1.5 degC threshold [N1], impacts worsen.",
                 "once the ONI settles at 1.5 degC [N1] the event is strong.",
                 "The 1.5 degC threshold [N1] would mark a strong El Nino if reached.",
                 "Watch the 1.5 degC threshold [N1] as the season progresses.",
                 "whether the anomaly holds versus the 1.5 degC threshold [N1].",
                 "The 1.5 degC threshold marks a strong El Nino [N1].",     # no conditional ANYWHERE
                 "the anomaly may reach the 1.5 degC trigger [N1] this winter.",
                 "prices must clear the 1.5 degC barrier [N1].",
                 "the 1.5 degC cutoff [N1] defines a strong event.",
                 "does the anomaly continue rising toward the 1.5 degC threshold [N1]"):
        assert vf._num_repair(sent, 1, row) is None, sent


def test_review_b1_an_ordinary_measurement_is_refused_as_well_cycle10():
    """(c1) had to fence STATED thresholds without swallowing the REPORTED kind, so an ordinary measured
    level stayed repairable. CYCLE-10 stops distinguishing them -- a reported level is exactly the shape
    gate-7 corrupted -- and both forms take the drop."""
    assert vf._num_repair("The anomaly read 0.31 degC [N1].", 1,
                          [_call("oni_anom", 0.98, "degC")]) is None
    assert vf._num_repair("The anomaly is above 0.31 degC [N1].", 1,
                          [_call("oni_anom", 0.98, "degC")]) is None


def test_review_b2_a_resolved_E_form_ledger_ref_is_never_pruned():
    """BLOCKER 2, end-to-end through the real verifier and the real footer builder. The prune's live set
    was keyed on the raw ledger `ref` and probed with the prose's integer -- different namespaces -- so a
    valid, resolved, footer-backed citation was stripped from the reader's page while its `## Sources` row
    stayed. FIX 3's own defect, inverted, minted by FIX 3. Every spelling below is one `verify` codes for
    explicitly and one `_cited_sources_block` renders."""
    ev = [{"source": "usda_wasde", "date": "2012-08-10", "text": "Record prices in 2012.",
           "source_key": "k1"}]
    for spelling in ("E1", "[E1]", "e1", "01", "E01", 1.0, "1", 1, " 1 "):
        s = _structured(tldr='The record shows "Record prices in 2012" here [E1].',
                        sources=[{"ref": spelling, "source": "usda_wasde", "date": "2012-08-10"}])
        rep = vf.verify_citations(s, ev, [])
        assert "[E1]" in s["tldr"], spelling                       # verify kept it
        assert an._prune_orphan_evidence_handles(s, rep) == 0, spelling
        assert "[E1]" in s["tldr"], spelling                       # ...and so does the prune
        assert "USDA WASDE" in an._cited_sources_block(s, rep, []), spelling


def test_review_b2_a_dangling_E_ref_is_still_pruned():
    """The prune must still do its job: a ref the footer cannot answer for leaves the prose. Widening the
    live set to both namespaces can only ever KEEP a marker whose row exists -- it can never mint one."""
    s = _structured(tldr="Costs fell [E1] on the record [E2].",
                    sources=[{"ref": "E1", "source": "usda_wasde", "date": "2012-08-10"}])
    assert an._prune_orphan_evidence_handles(s, {"resolved": {"E1": {}}}) == 1
    assert s["tldr"] == "Costs fell [E1] on the record."


def test_review_m3_an_evidence_handle_beside_the_slot_costs_nothing():
    """MAJOR 3. Clause (a)'s rationale is "two CANDIDATE SOURCES for one numeral"; an [E] handle is an
    ATTRIBUTION and can never source a numeral, so counting it dropped whole sentences written in the
    house style the system prompt asks for. Measured as the third-largest refusal bucket in the reviewer's
    4,000-draft sweep. The verdict must not depend on what is standing NEXT to the [N] handle.

    CYCLE-10: the invariant MAJOR 3 asked for -- that an [E] token beside the slot never changes the
    verdict -- is preserved trivially and totally, because every verdict is now the same verdict. The
    refusal bucket the reviewer measured is moot: no sentence in it was repairable to begin with."""
    solo = [_call("oni_anom", 0.31, "degC")]
    assert vf._num_repair("Anomalies ran 0.72 degC [N1].", 1, solo) is None
    for sent in ("Anomalies ran 0.72 degC [N1], per the CPC bulletin [E2].",
                 "Anomalies ran 0.72 degC [N1] (see the record [3]).",
                 "Anomalies ran 0.72 degC [N1] [E2, E5]."):
        assert vf._num_repair(sent, 1, solo) is None, sent
    pair = solo + [_call("oni_anom", 0.31, "degC")]
    assert vf._num_repair("Anomalies ran 0.72 degC [N1][N2].", 1, pair) is None
    assert vf._num_repair("Anomalies ran 0.72 degC [N1, N2].", 1, pair) is None


def test_review_m3_the_E_arm_is_symmetric_even_when_the_slot_is_refused():
    """The invariant under the finding, stated directly: an [E]/positional token beside the slot never
    changes the verdict, in EITHER direction. (The -0.72/+0.06 fixture the reviewer wrote this against is
    now refused on both arms by clause (e) -- MAJOR 4 -- which is the stricter answer, not a different
    one; what MAJOR 3 asks is that the two arms agree, and they do.)"""
    for calls in ([_call("oni_anom", 0.06, "degC")], [_call("oni_anom", 0.31, "degC")],
                  [_call("soil_temp_c", -18.4, "degC")], [_call("m", 5)]):
        for bare, decorated in ((
                "Anomalies ran -0.72 degC [N1].",
                "Anomalies ran -0.72 degC [N1], per the CPC bulletin [E2]."), (
                "Anomalies ran 0.72 degC [N1].",
                "Per the CPC bulletin [E2], anomalies ran 0.72 degC [N1].")):
            a = vf._num_repair(bare, 1, calls)
            b = vf._num_repair(decorated, 1, calls)
            assert (a is None) == (b is None), (calls, decorated)
            if a is not None:
                assert a[2] == b[2], (calls, decorated)


def test_review_m4_a_same_class_row_orders_off_is_not_a_certified_repair():
    """MAJOR 4. Clause (b) certifies DIMENSION, never PLAUSIBILITY, and after the (b) inversion the class
    fence is the LAST one standing on every repair that still fires -- so the population it admits is
    where the next corruption comes from. All three are the reviewer's measured shapes, all dimensionally
    legal, none a plausible transcription of what the model wrote."""
    assert vf._num_repair("The ONI anomaly is at 0.98 degC [N1].", 1,
                          [_call("soil_temp_c", -18.4, "degC")]) is None          # 19x, sign inverted
    assert vf._num_repair("Stocks changed 2.1 percent [N1].", 1,
                          [_call("stocks_pct_chg", 1629801.0, "%")]) is None      # the gate-5 palm shape
    assert vf._num_repair("The z-score reads 1.2 sigma [N1].", 1,
                          [_call("urea_z", 940.5, "sigma")]) is None              # ~780x
    # ZERO against a magnitude is the degenerate case of the same test -- and a SECOND, independent lock
    # on the shipped COV1 corruption ("1.5" -> "0"), which clause (c) also refuses.
    assert vf._num_repair("The anomaly reads 1.5 degC [N1].", 1,
                          [_call("oni_anom", 0.0, "degC")]) is None


def test_review_m4_the_sign_the_page_carries_must_not_be_contradicted():
    """`_CLAIM_NUM` cannot see a minus, so a repair splices the MAGNITUDE under the sign already on the
    page. When the page's explicit sign and the row's sign disagree, that publishes a figure that is
    neither the model's nor the row's. Agreement -- and a slot with no explicit sign -- still repairs, so
    `test_repair_direction_stays_in_the_prose_sign` is unmoved.

    CYCLE-10: the agreeing-sign arm drops too. A sign that agrees certifies the DIRECTION and says
    nothing about whether the row is the same quantity as the slot -- which is precisely how gate-7's
    signed `*_pace_change` walked into a slot whose own word already carried the direction."""
    assert vf._num_repair("The anomaly read -0.693675 z [N1].", 1,
                          [_call("oni_anom", -2.1035, "sigma")]) is None          # signs agree: still no
    assert vf._num_repair("The anomaly read +0.693675 z [N1].", 1,
                          [_call("oni_anom", -2.1035, "sigma")]) is None          # page says +, row says -
    assert vf._num_repair("The anomaly read -0.693675 z [N1].", 1,
                          [_call("oni_anom", 2.1035, "sigma")]) is None           # page says -, row says +
    # THE OTHER HALF: an unsigned slot fed by a NEGATIVE row used to publish the magnitude alone ("is at
    # 0.98 degC" <- a -18.4 row wrote "18.4"), which cycle-9 closed by carrying the row's own sign into
    # the replacement. CYCLE-10 closes it by writing no replacement.
    assert vf._num_repair("The anomaly read 0.693675 z [N1].", 1,
                          [_call("oni_anom", -2.1035, "sigma")]) is None
    assert not hasattr(vf, "_PROSE_SIGN") and not hasattr(vf, "_REPAIR_MAG_RATIO_MAX")


def test_review_m6_the_prune_leaves_no_residue_the_debris_pass_cannot_close():
    """MEDIUM 6. FIX 3's note asserts `_tidy_handle_debris` closes the frames these removals empty. It does
    for the bracket frame; the reviewer measured three shapes where it does not, all of which reach the
    reader's page: a comma-period, a leading space, and an emptied em-dash aside."""
    for text, want in (("Costs fell [E1], [E2].", "Costs fell."),
                       ("[E1] opens the field.", "opens the field."),
                       ("A dash -- [E1] -- closes it.", "A dash -- closes it."),
                       ("(both referenced qualitatively [E1][E2][E3])", "(both referenced qualitatively)"),
                       ("documented [E1], and the rest", "documented, and the rest")):
        s = _structured(tldr=text)
        an._prune_orphan_evidence_handles(s, {"resolved": {}})
        an._tidy_handle_debris(s)
        assert s["tldr"] == want, (text, s["tldr"])


def test_review_m7_the_prune_moves_the_evidence_citation_pins():
    """MEDIUM 7, pinned as a KNOWN shift rather than discovered at the gate. `eval._cited_evidence` joins
    by scanning prose for the citation id in brackets and an evidence citation's id is the E form
    (`citations.py:1020`), so every marker the prune removes also leaves `min_episodes_cited` /
    `min_episode_sources` / the source-tier pin. The exposure is the DANGLING set and nothing else: a live
    ref is untouched (see the BLOCKER-2 pins)."""
    from leviathan.graphrag import eval as ev
    out = {"structured": {"tldr": "Costs fell [E1] on the record [E2].", "mechanism": ""},
           "citations": [{"id": "E1", "kind": "evidence"}, {"id": "E2", "kind": "evidence"}]}
    assert len(ev._cited_evidence(out)) == 2
    an._prune_orphan_evidence_handles(out["structured"], {"resolved": {}})
    assert ev._cited_evidence(out) == []                 # the declared, measured direction of the shift


def test_review_m8_a_bare_continuation_member_behind_a_prefixed_lead_is_a_handle():
    r"""MEDIUM 8. `verify._HANDLE` required the N/E prefix on EVERY member while `answer._N_HANDLE_RX`
    reads `N?\d+`, so the renderer's own `[N5, 10, 12]` spelling was a handle to the renderer and prose
    here -- `_sibling_backed` could not see the backing member, the r5 rescue could not fire, and the
    sentence was DROPPED WHOLE where the prefixed spelling of the same sentence keeps its figure. The
    LEADING member must still carry the prefix, which is what keeps the year-range hazard closed."""
    assert vf._handle_members("[N5, 10, 12]") == [("N", 5), ("N", 10), ("N", 12)]
    assert vf._handle_members("[N1-4]") == [("N", i) for i in range(1, 5)]
    for hazard in ("[1980-1990]", "[5900-9999]", "[1-4]"):
        assert not vf._HANDLE.fullmatch(hazard), hazard              # a BARE lead still demands prefixes
    # THE MASKING CONSEQUENCE, measured against HEAD: the renderer's own continuation digits stop being
    # read as magnitudes (HEAD: [10.0, 12.0, 14.6]), while the year range is untouched in both.
    assert vf._claim_numbers_in(
        vf._HANDLE.sub("", "The ban ran [N5, 10, 12] and cost 14.6 MMT.")) == [14.6]
    assert vf._claim_numbers_in(
        vf._HANDLE.sub("", "The ban ran [1980-1990] and cost 14.6 MMT.")) == [14.6]
    # the two spellings of ONE sentence now reach the SAME verdict
    calls = [_call("oni_anom", 0.98, "degC")] + _pad(1) + [_call("oni_anom", 0.98, "degC")]
    for tok in ("[N1, N3]", "[N1, 3]"):
        assert vf._sibling_backed(
            "The ONI anomaly is at 0.98 degC " + tok + ", in El Nino territory.", 9, calls) is True, tok


def test_review_minor9_the_boundary_keys_survive_an_emptied_field(monkeypatch):
    """MINOR 9. FIX 4 exists to make the `preverify_* -> postverify_*` interval attributable, and the most
    interesting mutation in it is verify EMPTYING a field. Under the inherited falsy drop that landed as
    an ABSENT key -- indistinguishable from the flag being off, on exactly the case the boundary names."""
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    assert an.raw_draft_snapshot(preverify_tldr="a claim", postverify_tldr="") == {
        "preverify_tldr": "a claim", "postverify_tldr": ""}
    assert an.raw_draft_snapshot(postverify_mechanism=None) == {"postverify_mechanism": ""}
    assert an.raw_draft_snapshot(tldr="", mechanism="") is None      # every other caller: unchanged
