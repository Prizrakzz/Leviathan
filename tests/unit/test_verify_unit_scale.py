"""D-DA UNIT-SCALE (2026-09-04) -- the claim extractor's rule (g), pinned end to end.

THE DEFECT THIS FILE EXISTS FOR, measured on arm da-arm-CONTROL (7 answers,
`data/batch_runs/da_baseline_control_20260904T141206Z.json`, field `strip_audit`): 33 of the 35
`number_unbacked` charges were sentences that TRANSCRIBE A SERVED ROW'S OWN UNIT LABEL. The PSD
ATTRIBUTES row prints `= 154,947 (1000 MT)`; the model quoted it verbatim; the extractor returned
`[154947.0, 1000.0, 161297.0, 1000.0]`, found no served row equal to 1000 (it is the UNIT, not a
quantity), and charged the sentence. Live in production on serving rev 128.

The pins are in three bands, and all three are load-bearing together:
  * THE FIX -- the measured sentence takes ZERO number_unbacked charges against its two served rows;
  * THE FENCE -- a fabricated figure in the SAME sentence still strips, and a bare '1000' in prose with
    no figure in front of it still strips;
  * THE FREEZE -- every other extraction rule (year, range tail, letter-glued code, date day, ordinal,
    duration modifier) returns exactly what it returned before this amendment;
  * THE REVIEW'S FENCES (2026-09-04 FIX_THEN_SHIP -> shipped tightened): the exempted numeral is a BARE
    digit run, a label is consumed whole and never anchors, the vocabulary is the rendered corpus and
    nothing wider, the frozen flag's off-view did not move -- and the two residuals the review named
    (a mis-transcribed scale; strip -> harder strip) are pinned in the open rather than described away.
"""
from __future__ import annotations

from leviathan.graphrag import verify as vf

# The two served rows the measured sentence cites. The label the row PRINTS is "(1000 MT)"; the row's
# VALUE is the bare figure, which is precisely why 1000 can never be backed and must never be charged.
_ROW_N21 = {"query": {"table": "silver_psd_attributes", "metric": "Feed Dom. Consumption",
                      "commodity": "corn"},
            "rows": [{"value": "154947", "unit": "(1000 MT)", "knowledge_date": "2026-08-12"}]}
_ROW_N22 = {"query": {"table": "silver_psd_attributes", "metric": "Feed Dom. Consumption",
                      "commodity": "corn"},
            "rows": [{"value": "161297", "unit": "(1000 MT)", "knowledge_date": "2026-08-12"}]}


def _calls(n21=_ROW_N21, n22=_ROW_N22):
    """22 injected calls so [N21]/[N22] are in range; every other slot is a real but empty call."""
    calls = [{"query": {"table": "silver_psd", "metric": "ending_stocks_mt"}, "rows": []}
             for _ in range(22)]
    calls[20] = n21
    calls[21] = n22
    return calls


def _structured(tldr, mechanism=""):
    return {"tldr": tldr, "mechanism": mechanism, "sources": []}


SENT = ("US corn feed use is 154,947 (1000 MT) for MY2026 against 161,297 (1000 MT) "
        "for MY2025 [N21][N22]")


# -- BAND 1: THE FIX ---------------------------------------------------------------------------------

def test_served_unit_label_is_not_a_claim_numeral():
    """The extractor's own verdict on the measured sentence: two figures, no 1000."""
    assert vf._claim_numbers_in(vf._HANDLE.sub("", SENT)) == [154947.0, 161297.0]


def test_measured_sentence_takes_zero_strips_against_its_served_rows():
    """THE PIN. Both handles survive and no rule fires -- the whole defect, closed."""
    s = _structured(SENT)
    rep = vf.verify_citations(s, [], _calls())
    assert rep["by_rule"].get("number_unbacked", 0) == 0
    assert rep["stripped"] == 0
    assert "[N21]" in s["tldr"] and "[N22]" in s["tldr"]
    assert "154,947 (1000 MT)" in s["tldr"] and "161,297 (1000 MT)" in s["tldr"]


def test_no_parenthesis_spelling_is_the_same_rule():
    """The ESR lane writes the label bare -- '-83.476 1000 MT' -- and the row is the weekly change."""
    calls = [{"query": {"table": "silver_esr", "metric": "changes_1000mt"},
              "rows": [{"value": "-83.476", "unit": "1000 MT"}]}]
    s = _structured("Weekly meal export pace changed by -83.476 1000 MT from the prior week [N1].")
    rep = vf.verify_citations(s, [], calls)
    assert rep["stripped"] == 0 and "[N1]" in s["tldr"]


def test_zero_valued_row_with_a_scale_label_survives():
    """'0 1000 MT' -- the F8 materialized-zero doctrine and the unit scale in ONE sentence."""
    calls = [{"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt"},
              "rows": [{"value": "0", "unit": "1000 MT"}]}]
    s = _structured("Weekly soyoil exports read 0 1000 MT on the window [N1].")
    rep = vf.verify_citations(s, [], calls)
    assert rep["stripped"] == 0 and "[N1]" in s["tldr"]


# -- BAND 2: THE FENCE -------------------------------------------------------------------------------

def test_fabricated_figure_in_the_same_shape_still_strips():
    """The label is exempt; the FIGURE never is. 199,997 matches no served row and must be charged."""
    bad = SENT.replace("161,297", "199,997")
    assert vf._claim_numbers_in(vf._HANDLE.sub("", bad)) == [154947.0, 199997.0]
    s = _structured(bad)
    rep = vf.verify_citations(s, [], _calls())
    assert rep["by_rule"].get("number_unbacked", 0) >= 1
    assert "[N21]" not in s["tldr"] and "[N22]" not in s["tldr"]


def test_bare_thousand_in_prose_with_no_figure_in_front_still_strips():
    """'about 1000 tonnes' has a unit word after it and NO figure before it -- still a claim, and the
    sentence still dies. The remedy is the fail-closed number_mismatch drop (1000 disagrees with the
    only served row), which is the STRONGEST of the two strips this class can take."""
    assert vf._claim_numbers_in("the cargo was about 1000 tonnes") == [1000.0]
    calls = [{"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt"},
              "rows": [{"value": "42.5", "unit": "1000 MT"}]}]
    s = _structured("The cargo was about 1000 tonnes [N1].")
    rep = vf.verify_citations(s, [], calls)
    assert rep["stripped"] == 1 and "1000 tonnes" not in s["tldr"]


def test_a_bare_thousand_beside_a_real_label_is_the_only_one_charged():
    """The discriminating pin: ONE sentence, TWO '1000's. The first is the served row's own label and
    is exempt; the second is prose and is charged number_unbacked. Only the second can strip."""
    calls = [{"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt"},
              "rows": [{"value": "42.5", "unit": "1000 MT"}]}]
    sent = "Exports were 42.5 (1000 MT) and the cargo was about 1000 tonnes [N1]."
    assert vf._claim_numbers_in(vf._HANDLE.sub("", sent)) == [42.5, 1000.0]
    s = _structured(sent)
    rep = vf.verify_citations(s, [], calls)
    assert rep["by_rule"].get("number_unbacked", 0) == 1 and "[N1]" not in s["tldr"]


def test_a_comma_separated_list_is_not_a_unit_label():
    """The lead refuses a comma: the second figure of a list is a FIGURE, never a label's scale."""
    got = vf._claim_numbers_in("Crush rose: 62,196 (1000 MT), 66,546 (1000 MT), 72,257 (1000 MT).")
    assert got == [62196.0, 66546.0, 72257.0]


def test_the_hyphenated_range_hazard_stays_closed():
    """`_RANGE_TAIL`'s recorded hazard: a dash lead would exempt 9999 in 'ranged 5900-9999 MT'."""
    assert vf._claim_numbers_in("prices ranged 5900-9999 MT over the window") == [5900.0, 9999.0]


def test_a_second_magnitude_after_a_unit_word_is_still_a_claim():
    """'432,342,000 MT, ending stocks 49,401,000 MT' -- both are figures, neither is a scale."""
    got = vf._claim_numbers_in("Corn: production 432,342,000 MT, ending stocks 49,401,000 MT")
    assert got == [432342000.0, 49401000.0]


# -- BAND 3: THE SHAPES, ENUMERATED FROM WHAT THE ESTATE RENDERS --------------------------------------

def test_every_rendered_label_shape_that_carries_a_numeral():
    """Read off `citations._metric_unit`'s registry lookup and the PSD long table's verbatim
    `unit_desc`. Each entry is (prose, the claim magnitudes that remain)."""
    cases = [
        ("area harvested 35,700 (1000 HA)", [35700.0]),
        ("the fresh-citrus read is 12,345 1000 boxes on the window", [12345.0]),
        ("arabica 1,234 1000 60-kg bags", [1234.0]),
        ("area 1,234 1000 ha", [1234.0]),
        ("carcass output 1,200 (1000 MT CWE)", [1200.0]),
        ("the herd is 1,917 (1000 HEAD)", [1917.0]),
        ("arabica production 42,300 (1000 60 KG BAGS)", [42300.0]),
        ("cotton use 7,777 1000 480 lb. Bales", [7777.0]),
        ("coffee stocks of 12,345 60-kg bags", [12345.0]),
        ("the inside quote is 2,450,000 COP per 125-kg carga", [2450000.0]),
        ("world output 26.5 MMT (cotton: million 480-lb bales)", [26.5]),
    ]
    for prose, want in cases:
        assert vf._claim_numbers_in(prose) == want, prose


def test_labels_deliberately_not_covered_stay_charged():
    """Stated rather than quietly left out. '32nds' wears an ordinal suffix (cycle-8 rule (e)'s class)
    and '0/1' carries no unit word at all, so neither earns rule (g)."""
    assert vf._claim_numbers_in("the staple reads 35 32nds of an inch") == [35.0, 32.0]
    assert vf._claim_numbers_in("the regime flag is 1 0/1") == [1.0, 0.0, 1.0]


# -- BAND 3b: THE FREEZE -- every other extraction rule, byte for byte ---------------------------------

def test_the_other_six_rules_are_untouched():
    frozen = [
        ("in January 2026 stocks were 5,000 MT", [5000.0]),          # (a) bare year
        ("exports hit 1950 MMT", [1950.0]),                          # (a) unit-suffixed year is a claim
        ("the 1998-99 crop", []),                                    # (b) year-range tail
        ("the B40 mandate on CO2", []),                              # (c) letter-glued code
        ("as of 25 July 2026 the read is 12.5 MT", [12.5]),          # (d) date day
        ("at the 85th percentile", [85.0]),                          # (e) percentile carve-out
        ("at the 3rd consecutive month", []),                        # (e) ordinal
        ("below the 5-year mean", []),                               # (f) duration modifier
        ("prices have risen for 5 months in a row", [5.0]),          # (f) head position stays a claim
        ("roughly 2 percent below the average", [2.0]),              # percent slots untouched
        ("Ending stocks were 31.4 million MT", [31.4]),              # the word scale was never a numeral
    ]
    for prose, want in frozen:
        assert vf._claim_numbers_in(prose) == want, prose


def test_bare_digit_verdict_is_unchanged_by_the_amendment():
    """Rule (g) can never empty a sentence of claims -- it requires an ACCEPTED figure in front of it --
    so the D-HP-12 lint's verdict on a label-bearing sentence is exactly what it was."""
    assert vf.bare_digit_verdict("Feed use is 154,947 (1000 MT).") == "bare_digit"
    assert vf.bare_digit_verdict("Feed use is 154,947 (1000 MT) [E4].") == "e_cited"
    assert vf.bare_digit_verdict("Feed use fell on the month.") is None


# -- BAND 4: THE REVIEW'S FENCES (2026-09-04) ----------------------------------------------------------

def test_major1_the_exempted_numeral_must_be_a_bare_digit_run():
    """A FORMATTED figure is never a scale, so the lead can no longer bridge two real figures."""
    cases = [
        ("Exports 154,947 MT 161,297 MT", [154947.0, 161297.0]),
        ("Exports were 42.5 (999,999 MT)", [42.5, 999999.0]),
        ("freight was 45 USD per 1,250 MT", [45.0, 1250.0]),
        ("production 432,342,000 MT 49,401,000 MT", [432342000.0, 49401000.0]),
        ("yields of 3.5 t per 1.2 ha", [3.5, 1.2]),
    ]
    for prose, want in cases:
        assert vf._claim_numbers_in(prose) == want, prose


def test_minor5_an_exempted_token_never_anchors_and_a_label_is_two_tokens_at_most():
    """One accepted figure shields the label grammar's own reach and nothing beyond it: only the bare
    run directly before the unit word reads as a scale, and a consumed label's second token is skipped,
    never anchored."""
    got = vf._claim_numbers_in("US corn feed use is 154,947 1000 777777 888888 MT")
    assert got == [154947.0, 1000.0, 777777.0], got
    got = vf._claim_numbers_in("arabica production 42,300 (1000 60 KG BAGS) and 55 more")
    assert got == [42300.0, 55.0], got


def test_minor3_the_vocabulary_is_the_rendered_corpus_and_nothing_wider():
    """Words the first cut admitted and no label prints no longer bridge a figure to a bare token."""
    cases = [
        ("stocks 154947 short 999 tons", [154947.0, 999.0]),
        ("price 450 USD 1234 MT", [450.0, 1234.0]),
        ("the spread was 12 t 3456 MT", [12.0, 3456.0]),
        ("index 100 val 555 MT", [100.0, 555.0]),
    ]
    for prose, want in cases:
        assert vf._claim_numbers_in(prose) == want, prose


def test_major2_the_mis_transcribed_scale_residual_is_stated_not_hidden():
    """A wrong SCALE in a label is caught by NOTHING in this module today -- 9999 is exempted exactly as
    1000 is, and `quote_mismatch` reads QUOTED spans only. This pin holds the residual in the open: it
    goes red the day the unit-vocabulary gate at the charge site lands, and that day it is rewritten."""
    assert vf._claim_numbers_in("US corn feed use is 154,947 (9999 MT)") == [154947.0]
    calls = [{"query": {"table": "silver_psd_attributes", "metric": "Feed Dom. Consumption"},
              "rows": [{"value": "154947", "unit": "(1000 MT)"}]}]
    s = _structured("US corn feed use is 154,947 (9999 MT) [N1].")
    rep = vf.verify_citations(s, [], calls)
    assert rep["stripped"] == 0 and "[N1]" in s["tldr"]


def test_minor4_strip_becomes_harder_strip_when_the_label_was_the_only_match():
    """The third transition, recorded: against a served row whose VALUE is 1000, HEAD read the label's
    scale as the sentence's one match and charged the fabricated 42.5 as number_unbacked (handle gone,
    sentence kept); the rule reads no match and the sentence dies as number_mismatch. The 'match' was a
    scale coinciding with a row value, so the harder strip is the honest one."""
    calls = [{"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt"},
              "rows": [{"value": "1000", "unit": "1000 MT"}]}]
    s = _structured("The pace was 42.5 (1000 MT) on the window [N1].")
    rep = vf.verify_citations(s, [], calls)
    assert rep["by_rule"].get("number_mismatch", 0) == 1
    assert rep["by_rule"].get("number_unbacked", 0) == 0
    assert "42.5" not in s["tldr"]


def test_minor7_the_frozen_flags_off_view_did_not_move():
    """`cycle8=False` is HEAD's (a)-(d) view; rule (g) rides under the same flag."""
    off = [v for _, _, v in vf._claim_number_spans("feed use at 154,947 (1000 MT)", cycle8=False)]
    assert off == [154947.0, 1000.0]
    on = [v for _, _, v in vf._claim_number_spans("feed use at 154,947 (1000 MT)")]
    assert on == [154947.0]
