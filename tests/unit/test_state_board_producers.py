"""LANE D -- THE BOARD'S PRODUCERS: WHAT THE BLOCK HANDS THE WRITER (the 2026-09-16 pre-arm smoke).

Every pin here is anchored on a DEFECT A GRADER READ IN A SERVED ANSWER, not on a design opinion, and
every one of them rides ``GRAPHRAG_STATE_BOARD`` / ``GRAPHRAG_WATCH_NONOBVIOUS`` by construction: this
whole package renders nothing at all with the board off, so a flag-off turn is HEAD byte for byte.

  (a) QUORUM DOUBLE-COUNT -- the deep answer said board crush and the crush margin were one reading and
      then counted BOTH into a two-driver pattern quorum.
  (b) THE ENSO PHASE READER -- a palm supply-squeeze story built on ONI -0.39 degC, a COOL-phase number.
  (c) THE PALM ONI ROW STALE BY SIX MONTHS -- "MY2026-01 = -0.39 degC (latest available 2026-03-08)"
      against the soybean board's "MY2026-07 = 1.8 degC" at the SAME as-of, off the same table.
  (d) DRIVER NAME vs ROW LABEL -- "Argentine export tax sits at 6.65 MMT" over a PSD EXPORTS row.
  (f) WATCH NOMINATIONS CARRY THE CLOCK -- the PM graders found no scheduled catalyst anywhere.
  (g) BoardAnalogs = 0 on all five turns, with no honest absence line where the LEG declined.
  (h) ONE SERIES, ONE CURRENT VALUE -- the US drought anomaly served twice, at 0.6 z and 2.24909 z.
  (i) THE WATCH ADMISSION FLOOR vs THE HORIZON -- an ANNUAL series as watch item one on a 3-month turn.
  (k) the word ANALOGUE reused on a page that said no past state is like the present one.

The ONI fixtures below are ``test_state_feeders``' own (imported, never re-typed): one fixture, one
oracle, so a producer change cannot be green here and red there.
"""
import pytest
from leviathan.graphrag.state import feeders as F
from leviathan.graphrag.state import lint as L
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import watch as WA
from leviathan.graphrag.state.board import NodeRow

from tests.unit.test_state_feeders import _Node, _oni_rows, _pit_qfn

_CONV = {"oni_climate": {"kind": "abs_bands", "bands": [0.5, 1.0, 1.5, 2.0],
                         "labels": ["elevated", "moderate", "strong", "extreme"], "unit": "degC"}}
_ASOF = "2026-09-08"


@pytest.fixture(scope="module")
def oni_pair():
    """THE PIN THE LANE BRIEF ASKS FOR BY NAME: the newest ONI served on BOTH DAGs at ONE as-of.

    ``oni_climate`` is the soybean DAG's read and ``oni_lag_climate`` is the palm DAG's -- one series,
    one physical read, two readings, and the palm one is deliberately six months back because that is
    the palm author's DECLARED effect lag. The defect was never the shift; it was that the row said
    only "latest available", which a reader takes for data latency."""
    F.cache_clear()
    rows = _oni_rows()
    bean = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), _ASOF,
                          qfn=_pit_qfn(rows, _ASOF), windows={"monthly": 120},
                          silver_status="available", conventions=_CONV)
    palm = F.series_state("oni_lag_climate",
                          _Node("malaysian_crude_palm_oil_cme", "El_Nino", "oni_lag_climate"), _ASOF,
                          qfn=_pit_qfn(rows, _ASOF, commodity="malaysian_crude_palm_oil_cme"),
                          windows={"monthly": 120}, silver_status="available", conventions=_CONV)
    return bean, palm


# ── (c) THE NEWEST KNOWABLE READING IS SERVED, AND THE LAG IS NAMED AS AN EFFECT LAG ────────────────
def test_c_the_lagged_palm_row_serves_the_NEWEST_KNOWABLE_reading_of_the_same_series(oni_pair):
    """MEASURED ON TWO SERVED QUICK TURNS: the palm board printed "NOAA ONI ... MY2026-01 = -0.39 degC
    (latest available 2026-03-08)" while the soybean board at the same as-of printed MY2026-07 = 1.8
    degC off the SAME table, and the writer built a palm supply-squeeze on the cool number.

    THE LEVEL DOES NOT MOVE -- correcting, never deleting. The row keeps its declared six-month
    reading, its own knowledge date and its own standing, and the producer banks the PRE-SHIFT newest
    row beside it so the render can serve both and say which is which."""
    bean, palm = oni_pair
    assert bean.status == "ok" and palm.status == "ok"
    assert palm.key == bean.key, "one series, one key"
    assert palm.offset_months == 6 and bean.offset_months == 0
    # the SHIFTED level is untouched
    assert palm.level_date != bean.level_date
    # ...and the newest knowable reading of that same series rides the row
    cur = palm.recency
    assert cur["current_level"] == bean.level, "the palm row must serve the BEAN board's newest number"
    assert cur["current_level_date"] == bean.level_date
    assert cur["current_knowledge_date"] == bean.knowledge_date
    assert cur["offset_periods"] == 6
    # A ROW WITH NO OFFSET BANKS NOTHING: the key is additive and its absence is the HEAD shape
    assert "current_level" not in bean.recency and "offset_periods" not in bean.recency


def test_c_the_rendered_palm_row_names_the_lag_as_an_EFFECT_lag_and_mints_the_current_reading(oni_pair):
    """"latest available 2026-03-08" reads as DATA LATENCY. The declared shift is this market's own
    effect lag, and the newest reading takes its OWN handle so a writer that prints it prints a backed
    figure."""
    bean, palm = oni_pair
    row = NodeRow(contract="malaysian_crude_palm_oil_cme", driver_id="El_Nino", state=palm, sign="+")
    line, calls = R.sb_state(1, row, asof=_ASOF)
    # RE-BANKED 09-23 FIX ROUND -- CONTRACT C1 identity words (09-23 recon soyoil_palm L2; BUILD_R sec 7 W-1): the
    # declared six-month EFFECT lag now rides the row's own identity instead of a separate sentence.
    # RE-BANKED 09-24 FIX ROUND 2 -- CONTRACT K2 (DM1, BUILD_R sec 2): the period at its own precision moved
    # into the FIGURE TOKEN the writer copies; the offset stays in the row's own name.
    assert ("the tropical Pacific sea-surface temperature anomaly, read six months back -- the "
            "reading whose declared lag lands now, on CME palm oil (NOAA ONI), read here for El Nino:") in line
    assert "degC, January 2026;" in line, line
    assert "[N4] the newest knowable reading of the same series is" in line
    assert str(bean.level_date) in line
    assert len(calls) == 4, "level, z, percentile and the newest knowable reading"
    assert calls[-1]["shown"] == [pytest.approx(bean.level)]
    assert R.classify(line) == ("SB-1",), "the class token is untouched"
    # the BEAN row says none of it -- no offset, no clause, three handles
    bline, bcalls = R.sb_state(1, NodeRow(contract="soybeans_cbot", driver_id="El_Nino",
                                          state=bean, sign="-"), asof=_ASOF)
    assert "effect lag" not in bline and "newest knowable reading" not in bline
    assert len(bcalls) == 3


def test_c_an_offset_that_was_NOT_applied_never_claims_an_effect_lag():
    """The producer writes ONE literal on both refusal branches and the render reads it. A row whose
    shift was skipped carries an UNSHIFTED level, so telling a reader its date is an effect lag would
    be a wrong sentence under a right-looking clause."""
    assert F.OFFSET_NOT_APPLIED == "is NOT applied"

    class _St:
        offset_months, offset_note, recency = 6, "", {}
    st = _St()
    assert R._offset_applied(st) is True                       # applied: the note carries no refusal
    st.offset_note = f"a declared 6-month offset {F.OFFSET_NOT_APPLIED}: the fetched history is 4"
    assert R._offset_applied(st) is False
    st.offset_months = 0
    assert R._offset_applied(st) is False


# ── (b) THE PHASE IN FORCE ──────────────────────────────────────────────────────────────────────────
def test_b_the_phase_verdict_reads_the_CONVENTIONS_OWN_band_and_never_a_second_number():
    warm = R.phase_in_force("silver_noaa_oni", "oni_anom", 1.8)      # the SOYBEAN turn's reading
    cool = R.phase_in_force("silver_noaa_oni", "oni_anom", -0.67)
    inside = R.phase_in_force("silver_noaa_oni", "oni_anom", -0.39)  # the PALM turn's reading
    assert warm["driver"] == "El_Nino" and warm["in_force"] is True
    assert cool["driver"] == "La_Nina" and cool["in_force"] is True
    # AND THE SHARPEST READING OF THE SMOKE IS HERE: the palm turn's -0.39 degC is NOT a cool phase at
    # all -- it sits INSIDE the publisher's own 0.5 degC line, so NEITHER phase was in force, and the
    # served page narrated a palm supply story off a neutral number.
    assert inside["in_force"] is False
    assert warm["band"] == L.load_conventions()["conventions"]["oni_climate"]["bands"][0]
    # the IOD pair rides the same mechanism off its OWN convention row
    iod = R.phase_in_force("silver_noaa_iod", "dmi_value", 0.41)
    assert iod["driver"] == "IOD_positive" and iod["band"] == 0.4
    # and an undeclared series is left alone -- this module never guesses which way an index signs
    assert R.phase_in_force("silver_psd", "su_ratio", 0.12) == {}


def test_b_the_join_line_states_the_phase_and_THIS_markets_sign_for_it():
    """"opposite signs on each board by phase" reached a served corn page with no ENSO driver admitted
    at all. The block now says which phase the reading IS and what this market declares for it."""
    ph = {"words": "the cool phase", "other_words": "the warm phase", "in_force": True,
          "live_name": "La Nina", "live_sign": "in the same direction",
          "other_name": "El Nino", "other_sign": "in the opposite direction"}
    line = R.sb_phase_pair(["El Nino", "La Nina"], "CME palm oil", opposed=True, phase=ph)
    assert "The phase in force at this reading is the cool phase" in line
    assert "the graph declares La Nina in the same direction" in line
    assert "El Nino states what CME palm oil would carry in the warm phase" in line
    assert not any(ch.isdigit() for ch in line), "SB-JOIN is letters-only"
    assert R.classify(line) == ("SB-JOIN",)


# ── (a) THE QUORUM COUNTS DISTINCT SERIES ───────────────────────────────────────────────────────────
def _pattern(**kw):
    base = dict(name="crush_demand_pull", contract="soybeans_cbot", direction="", threshold=2,
                drivers=("board_crush", "soybean_crush_margin", "crude_oil"),
                matched=("board_crush", "soybean_crush_margin", "crude_oil"), n_matched=3,
                matched_measured=("board_crush", "soybean_crush_margin", "crude_oil"),
                matched_unmeasured=(), n_declared=7, loud_k=24, n_with_band=0, interactions=())
    base.update(kw)
    return base


def test_a_a_pattern_counts_DISTINCT_SERIES_and_names_the_alias_it_folded():
    """VERBATIM FROM THE SERVED DEEP ANSWER: "note these two are one series read under two names -- one
    reading, not two", and two sentences later "the crush-led demand-pull pattern has three of its
    drivers among the loudest readings against a threshold of two". One reading cleared a two-driver
    quorum on its own.

    THE THRESHOLD IS THE GRAPH'S AND IS NOT RE-CURATED: the fold can only ever move a pattern towards
    SHORT OF its number, never past it."""
    series_of = {"board_crush": ("gold_board_crush:crush_margin_usd_bu", "medium"),
                 "soybean_crush_margin": ("gold_board_crush:crush_margin_usd_bu", "high"),
                 "crude_oil": ("silver_pink_sheet:brent", "medium")}
    folded = R.sb_convergence(_pattern(), series_of=series_of)
    assert "two of the seven conditions it names are showing here" in folded
    assert "soybean crush margin and board crush are one reading and count once here" in folded
    # the HIGHER-CONFIDENCE name is the one kept, and the alias is still named
    assert "(soybean crush margin and crude oil, each with its own [N] z)" in folded
    # with NO map the row counts as HEAD did -- the fold is additive, never a silent re-count
    unfolded = R.sb_convergence(_pattern())
    assert "three of the seven conditions it names are showing here" in unfolded
    assert "are one reading and count once here" not in unfolded


def test_a_the_quorum_row_carries_no_firing_claim_and_no_internal_vocabulary():
    """``walk.CONVERGENCE_BANNED_WORDS`` puts FIRING with ``firing.fire_contract``: a board that says a
    pattern is "in force" has minted a verdict by arithmetic. Lane A asked for exactly that verdict and
    it is REFUSED here -- what lands is the register half, which is what the PM lens actually charged
    ("This is scoring machinery quoted verbatim")."""
    from leviathan.graphrag.state.walk import CONVERGENCE_BANNED_WORDS
    short = R.sb_convergence(_pattern(threshold=5))
    met = R.sb_convergence(_pattern(threshold=2))
    for line in (short, met):
        low = line.lower()
        for banned in CONVERGENCE_BANNED_WORDS:
            assert banned not in low, banned
        for lingo in ("loudest rows", "declared drivers", "the pattern's own threshold", "in force"):
            assert lingo not in low, lingo
    assert "the count here is short of that number" in short
    assert "the count here is at or past that number" in met


def test_a_the_non_opposed_join_stops_saying_the_false_sentence_and_names_the_alias():
    line = R.sb_phase_pair(["board crush", "soybean crush margin"], "CBOT soybeans", opposed=False,
                           keep="soybean crush margin", alias=("board crush",))
    assert "phases of one series and not separate readings" not in line
    assert "one piece of evidence and not two" in line
    assert "read it under soybean crush margin" in line and "board crush" in line
    assert "alias" in line


# ── (d) THE ROW'S OWN LABEL BESIDE THE DRIVER NAME ──────────────────────────────────────────────────
def test_d_the_reading_words_book_is_COMPLETE_over_the_board_map_and_fails_soft():
    """A POLICY NODE ON A VOLUME COLUMN reached a fund PM as a policy figure. The words are DECLARED
    (the S8 docket's own remedy) because the S7 derivation from the column name made 28 of 43 rows
    worse; an UNDECLARED metric prints no clause at all, which is why the lint must be the completeness
    check rather than the producer."""
    assert L._check_reading_words() == []
    assert R.reading_words("silver_psd", "exports_mt") == "exports"
    # RE-BANKED 09-23 FIX ROUND -- C10 reading words (09-23 recon max F1, the series named after its driver; BUILD_T
    # R2): the book now names the series the drought card actually measures.
    assert R.reading_words("gold_weather_z", "drought_z") == "the longest dry-day run in the month, as a z-score"
    assert R.reading_words("silver_fred_fx", "myr_usd")        # the card-wide default
    assert R.reading_words("silver_psd", "no_such_metric") == ""
    assert R.reading_words("", "") == ""


def test_d_the_state_line_names_the_reading_only_where_it_ADDS_something(oni_pair):
    """The clause is skipped where the driver's own name already IS the reading -- the S7 revert's
    measured failure was a line that read correctly gaining a redundant word."""
    _, palm = oni_pair
    tax = NodeRow(contract="soybeans_cbot", driver_id="Argentina_export_tax", state=palm, sign="-")
    line, _ = R.sb_state(1, tax, asof=_ASOF)
    # RE-BANKED 09-23 FIX ROUND -- CONTRACT C1 identity words (09-23 recon lane-R defect 1; BUILD_R sec 7 W-1): the
    # "the reading is <words>" clause is gone -- the SB-1 head STARTS with the series words and carries the driver
    # as routing.
    # RE-BANKED 09-24 FIX ROUND 2 -- CONTRACT K2 (DM1): the period rides the figure token, not the head.
    assert line.startswith("- [N1] the tropical Pacific sea-surface temperature anomaly, read six months back")
    assert "degC, January 2026;" in line, line
    assert "on CBOT soybeans (NOAA ONI), read here for Argentina export tax:" in line
    # a driver whose reader label IS the reading says nothing twice
    assert R._norm_words("the crush") == R._norm_words("Crush") == "crush"
    assert R._norm_words("exports") != R._norm_words("Argentina export tax")


def test_d_the_watch_sentence_takes_the_same_book_and_keeps_its_fallback():
    """"the figure is oni anom in degC" / "drought z in sigma" / "crush margin usd bu" -- one book, two
    consumers. A metric the book does not declare keeps the humanised column, so nothing that reads
    correctly today loses its words."""
    class _St:
        table, metric, narrate_unit, unit = "gold_weather_z", "drought_z", "sigma", ""
    # RE-BANKED 09-23 FIX ROUND -- C10 reading words (09-23 recon max F1; BUILD_T R2): the same book, one consumer on.
    assert WA._metric_words(_St()) == "the longest dry-day run in the month, as a z-score in sigma"

    class _Other:
        table, metric, narrate_unit, unit = "silver_unknown", "some_column", "", ""
    assert WA._metric_words(_Other()) == "some column"


# ── (f) + (i) THE CLOCK ON A NOMINATION, AND THE HORIZON IT MUST RESOLVE INSIDE ─────────────────────
class _Bd:
    def __init__(self, rows, asof="2026-09-07", horizon_months=3):
        self.rows, self.asof, self.horizon_months = rows, asof, horizon_months


class _S:
    def __init__(self, table, cadence):
        self.table, self.cadence = table, cadence


def _row(driver_id, table, cadence):
    """A NodeRow whose ``key`` is its own ``(contract, driver_id)`` property -- never assigned."""
    return NodeRow(contract="soybeans_cbot", driver_id=driver_id, state=_S(table, cadence))


def test_f_every_nomination_that_has_a_scheduled_print_carries_it_as_a_FIELD():
    """The PM graders found NO scheduled catalyst on five served answers -- no 09-30 Grain Stocks, no
    10-09 WASDE, no weekly export sales -- because the dates were named once in a footnote two of the
    five answers explicitly dismissed ("are not watch items"). The BAN on calendar-only nominations is
    untouched: nothing new is nominated, and an admitted row gains its own next print."""
    row = _row("d", "silver_esr", "weekly")
    cands = [{"kind": "past_the_line", "row": row.key, "what": "x", "declined": None}]
    WA.stamp_release_clock(_Bd([row]), cands)
    assert cands[0].get("next_print"), "an ESR row has a weekly rule and must carry its date"
    assert cands[0].get("horizon_miss") is None
    line = R.sb_watch({"kind_words": "k", "label": "l", "what": "x",
                       "next_print": cands[0]["next_print"]})
    assert line.endswith("; next print " + cands[0]["next_print"])
    assert R.classify(line) == ("SB-W",)


def test_i_a_nomination_whose_CADENCE_outruns_the_horizon_is_MARKED_and_never_struck():
    """MEASURED ON THE DEEP TURN: PSD beginning stocks MY2026 -- an ANNUAL series -- was watch item ONE
    carrying "this reads wrong if the next print returns the series to the middle of its own record",
    on a THREE-MONTH question. Its publisher re-prints monthly, so a calendar-only test passes it; the
    SERIES cannot move until the next marketing year."""
    annual = _row("a", "silver_psd", "annual")
    weekly = _row("w", "silver_esr", "weekly")
    cands = [{"kind": "recurrence", "row": annual.key, "what": "x", "declined": None},
             {"kind": "past_the_line", "row": weekly.key, "what": "x", "declined": None}]
    WA.stamp_release_clock(_Bd([annual, weekly]), cands)
    assert cands[0]["horizon_miss"] == "cadence"
    assert cands[1].get("horizon_miss") is None
    # a turn that asked for NO horizon has no bound to miss
    cands2 = [{"kind": "recurrence", "row": annual.key, "what": "x", "declined": None}]
    WA.stamp_release_clock(_Bd([annual], horizon_months=None), cands2)
    assert cands2[0].get("horizon_miss") is None
    # the row is MARKED, never struck: the claim and its falsifier both survive
    line = R.sb_watch({"kind_words": "k", "label": "l", "what": "the claim; reads wrong if X",
                       "horizon_miss": "cadence", "next_print": "2026-09-09"})
    assert "the claim; reads wrong if X" in line
    # REVIEW ROUND 2, MAJOR 6: THE FALSE HALF IS GONE. "it cannot turn inside that horizon whatever the
    # publisher's calendar says" is untrue of `silver_psd`, a marketing-year VINTAGE card USDA
    # re-estimates every month -- the smoke's own deep turn carries PSD rows at knowledge date
    # 2026-09-11 against a 2026-09-16 as-of. What the clause says now is what is true and what a PM
    # acts on: the scheduled print (from release_calendar.yaml), what that print does to the number,
    # and which reading on this page can turn inside the horizon.
    assert "cannot turn inside that horizon whatever the publisher's calendar says" not in line
    assert "its next scheduled print is 2026-09-09" in line
    assert "RESTATES the period already reported rather than opening a new one" in line
    assert "the figure can be revised inside the horizon" in line
    # ...AND THE CLOCK IS NOT PRINTED TWICE (MAJOR 7): the note carries the date, so the bare
    # "; next print <date>" tail is suppressed on a row that carries a note.
    assert line.count("2026-09-09") == 1 and "; next print" not in line


def test_i_the_horizon_NOTE_follows_the_rows_OWN_DATED_TAIL_and_never_orphans_it():
    """REVIEW ROUND 2, MAJOR 7, measured on round 1's own artefact. The note was spliced into the BODY,
    before ``tail``, and the row rendered "... watch a faster series on the same mechanism instead
    -- 2024-12-31; next print 2026-09-09": the LIKE-STATE date orphaned onto the end of the note's
    advice, where it reads as the date OF that advice, and a bare print date two days after the as-of
    following a note that had just denied any checkable print inside the horizon."""
    w = {"kind_words": "a state the record has been in before", "label": "l",
         "what": "the record has been in a state like this one before", "dates": "2024-12-31",
         "horizon_miss": "cadence", "next_print": "2026-09-09"}
    line = R.sb_watch(w)
    assert " -- 2024-12-31 NOTE: " in line, line
    assert line.index("-- 2024-12-31") < line.index("NOTE:"), "the date belongs to the ROW, not the note"
    # with NO note the row is HEAD's shape exactly: body, tail, clock -- in that order
    plain = R.sb_watch({k: v for k, v in w.items() if k != "horizon_miss"})
    assert plain.endswith(" -- 2024-12-31; next print 2026-09-09")


def test_i_the_two_horizon_causes_are_two_sentences_and_the_render_reads_the_producers():
    assert set(WA.HORIZON_MISS_CLAUSES) == {"print", "cadence"}
    for cause in ("print", "cadence"):
        # the render reads the PRODUCER and never a second spelling of it
        assert (R._horizon_miss_clause(cause, next_print="2026-09-09", faster="X")
                == WA.horizon_miss_clause(cause, next_print="2026-09-09", faster="X"))
        # the TEMPLATE carries no digit; the only digits a rendered clause can carry are the ISO date
        # the calendar supplied, which SB-W already carries as itself.
        assert not any(ch.isdigit() for ch in WA.HORIZON_MISS_CLAUSES[cause])
        undated = WA.horizon_miss_clause(cause)
        assert WA.HORIZON_PRINT_WORDS["undated"] in undated
        assert WA.HORIZON_FASTER_FALLBACK in undated
        assert not any(ch.isdigit() for ch in undated)
    assert (WA.horizon_miss_clause("not-a-cause", next_print="2026-09-09")
            == WA.horizon_miss_clause("print", next_print="2026-09-09"))


# ── (g) + (k) THE HONEST ABSENCE, AND THE WORD "EPISODE" ────────────────────────────────────────────
def test_g_and_k_the_like_state_absence_is_a_ROW_and_it_hands_over_the_word_EPISODE():
    """``BoardAnalogs = 0`` on all five served turns; where the LEG declined before a stanza was built
    the section printed NOTHING. And the deep page declared no past state is like the present one and
    then wrote "on the 2011 analogue window" -- the writer had no other word for a dated window."""
    line = R.sb_analog_leg_absence("no_like_state")
    assert line.startswith("BOARD ABSENCE a like state on this page: ")
    assert "no past state on this series is like this one under the likeness rule" in line
    assert "this page carries no analogue and no base rate drawn from one" in line
    assert "is an EPISODE -- a stretch of the record named by its dates" in line
    assert R.classify(line) == ("SB-X",)
    assert not any(ch.isdigit() for ch in line), "SB-X is letters and ISO dates only"
    nr = R.sb_analog_leg_absence("", not_reached=True)
    assert "the like-state leg was not entered on this turn" in nr


# ── (h) ONE SERIES, ONE CURRENT VALUE ───────────────────────────────────────────────────────────────
def test_h_the_header_states_that_every_state_figure_is_a_LEVEL_on_its_own_date():
    """The deep page served the US drought anomaly twice and called both current: "0.6 z [N44]" (the
    MY2026-07 monthly LEVEL, this block's own row) and "2.24909 z [N82]" (a 2025-09..2026-09 window
    statistic from the cascade's episode leg), both footnoted "newest shown". The block cannot police a
    figure it did not mint, so it states its own contract once, where the reader meets it first."""
    from leviathan.graphrag.state import __main__ as H
    head = H.build_scenario("soybeans_now")["block"].lines[0]
    assert R.classify(head) == ("SB-H",)
    assert "is that reading's LEVEL on the date the line names" in head
    assert "a window statistic and is never a second current value of the same series" in head


# ── (j) THE FAN IN WORDS, WITH THE NEAREST MARKETS NAMED ────────────────────────────────────────────
def test_j_the_fan_names_its_SUBJECT_and_the_nearest_markets_in_the_watch_lanes_own_order():
    """"declared on twenty-three other markets, twenty-two in the same direction" read to the PM lens
    as scoring machinery: a count with no subject and no market to look at next."""
    from leviathan.graphrag.state.lagbands import parse_lag
    far = [{"contract": "palm_olein_dce", "sign": "+", "confidence": "high",
            "lag_band": parse_lag("1-2 quarters")},
           {"contract": "soybean_oil_cbot", "sign": "+", "confidence": "high",
            "lag_band": parse_lag("2-4 quarters")},
           {"contract": "corn_cbot", "sign": "-", "confidence": "low", "lag_band": None},
           {"contract": "cotton_ice", "sign": "+", "confidence": "medium", "lag_band": None}]
    entry = {"contract": "soybeans_cbot", "driver_id": "crude_oil", "far": far}
    line = R.sb_fan(entry)
    assert line.startswith("- crude oil is a shared driver across four other markets")
    assert "The nearest two to this question are DCE palm olein and CBOT soybean oil" in line
    assert R.classify(line) == ("SB-F",)
    # THE TWO "NEAREST" PRODUCERS MUST AGREE -- one page may not name two different nearest markets
    assert R.nearest_far_names(entry, k=1) == [R.board_label(WA._nearest_far({"far": far})["contract"])]
    # a two- or three-market fan already names them all and says nothing twice
    assert "The nearest" not in R.sb_fan({"contract": "c", "driver_id": "d", "far": far[:2]})


# ── THE FLAG-OFF PROPERTY, STATED WHERE A REVIEWER LOOKS FOR IT ─────────────────────────────────────
def test_every_lane_D_change_rides_the_board_flag_by_construction():
    """THE BYTE-IDENTICAL SET. Not one line of ``state/`` renders on a turn where the board did not
    fire: ``answer.py`` builds the block only under ``_state_board_on()`` and the watch draw only under
    ``_watch_nonobvious_on()``. The proof this deck can carry is that the package reads NO environment
    of its own -- so there is no third path by which a lane D edit could reach a flag-off byte."""
    import ast
    import pathlib
    root = pathlib.Path(R.__file__).parent
    reads: dict = {}
    #: The offline census and the offline harness are TOOLS, not serving producers: neither is on any
    #: import path a turn takes. ``board_census`` reads the numbers backend so a census run can be
    #: pointed at the mirror, which is a fact about a script and never about a rendered byte.
    _tools = {"board_census.py", "__main__.py"}
    for path in sorted(p for p in root.glob("*.py") if p.name not in _tools):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [n.value for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and n.value.startswith("GRAPHRAG_")]
        if names:
            reads[path.name] = sorted(set(names))
    # EXACTLY ONE environment name is a STRING CONSTANT anywhere in this package, and it is a
    # PERFORMANCE knob (the memo store), never a flag. The four treatment flags are read at the ANSWER
    # seam and threaded in as kwargs -- which is what makes "flag off = HEAD bytes" a property of the
    # architecture rather than of any one edit. A second name appearing here is a lane D change that
    # could reach a flag-off byte, and this pin is where it fails.
    assert reads == {"feeders.py": ["GRAPHRAG_STATE_CACHE"]}, reads


def test_the_state_board_lint_is_green_including_the_two_new_clauses():
    assert L._check_reading_words() == []
    assert L._check_phase_pairs() == []
    assert L.check_state_board() == []


# ===================================================================================================
# ROUND-2 REVIEW: THE TEN MAJORS. Every pin below quotes the defect off round 1's OWN rendered artefact
# (scratchpad/prearm_fix_r1/D/AFTER_blocks.txt) or off a served answer, never off a design opinion.
# ===================================================================================================
_B40_FX = ["IDR USD", "INR USD", "MYR USD"]
_B40_POLICY = ["CPO export levy", "DMO", "export ban"]


def test_M1_the_non_opposed_join_COUNTS_THE_NAMES_IT_PRINTS():
    """AFTER_blocks.txt:334, the b40 fixture, a real curated DAG: "BOARD JOIN CPO export levy, DMO and
    export ban on CME palm oil: ... They are TWO NAMES for ONE reading ... read it under export ban and
    treat CPO export levy and DMO as aliases of that name". Three names, "two names"."""
    line = R.sb_phase_pair(_B40_POLICY, "CME palm oil", opposed=False, keep="export ban",
                           alias=("CPO export levy", "DMO"))
    assert "They are three names for ONE reading" in line
    assert "one piece of evidence and not three" in line
    assert "two names" not in line and "and not two" not in line
    assert R.classify(line) == ("SB-JOIN",)
    assert not any(ch.isdigit() for ch in line), "SB-JOIN is letters-only"
    # the TWO-name case is untouched, word for word
    two = R.sb_phase_pair(["board crush", "soybean crush margin"], "CBOT soybeans", opposed=False,
                          keep="soybean crush margin", alias=("board crush",))
    assert "They are two names for ONE reading" in two and "not two:" in two


def test_M2_the_undeclared_opposed_join_COUNTS_THE_LINKS_IT_PRINTS():
    """AFTER_blocks.txt:335: "BOARD JOIN IDR USD, INR USD and MYR USD ... that is one reading TWO
    DECLARED LINKS disagree about, not two readings." Three rows, three declared edges."""
    line = R.sb_phase_pair(_B40_FX, "CME palm oil", opposed=True, keep="IDR USD", keep_tied=True)
    assert "one reading three declared links disagree about, not three readings" in line
    assert "two declared links" not in line
    assert R.classify(line) == ("SB-JOIN",)


def test_M3_a_TIED_undeclared_fold_names_the_tie_and_issues_NO_instruction():
    """AFTER_blocks.txt:335 again: "Read it under IDR USD where a direction is needed." All three FX
    rows are declared at medium, so the keep broke ALPHABETICALLY and the page instructed the writer to
    read a shared FX reading on a MALAYSIAN palm board under the Indonesian rupiah. HEAD offered no such
    instruction at all."""
    tied = R.sb_phase_pair(_B40_FX, "CME palm oil", opposed=True, keep="IDR USD", keep_tied=True)
    assert "Read it under IDR USD" not in tied
    assert "declares them at the same confidence" in tied
    assert "does not offer one" in tied
    # where one link IS strictly the highest-confidence one it is named AS THAT, and not as a
    # preference this page invented -- the fact is the graph's, never the tie-breaker's
    ranked = R.sb_phase_pair(_B40_FX, "CME palm oil", opposed=True, keep="MYR USD", keep_tied=False)
    assert "MYR USD is the one of them the graph declares at the highest confidence" in ranked
    assert "same confidence" not in ranked


def test_M4_the_TWO_FOLDS_AGREE_because_they_read_the_same_two_facts():
    """THE BUILD REPORT CLAIMED THEY COULD NOT DISAGREE AND THEY COULD. `sb_phase_pair` required a
    DECLARED pair or SIGN AGREEMENT before saying "one reading"; `_series_fold` folded on the series key
    ALONE. On a board where a pattern matches two of a sign-contradictory group the JOIN line said "this
    page cannot reconcile them" and the quorum said "X and Y are one reading and count once here"."""
    # (1) A SIGN-CONTRADICTORY GROUP: the JOIN refuses to call it a phase pair, and so does the quorum.
    smap = {"IDR_USD": {"key": "silver_fred_fx:idr", "confidence": "medium", "sign": "-", "phase": {}},
            "MYR_USD": {"key": "silver_fred_fx:idr", "confidence": "medium", "sign": "+", "phase": {}}}
    fold = R._series_fold(["IDR_USD", "MYR_USD"], smap)
    assert [g[2] for g in fold["groups"]] == ["unreconciled"]
    line = R.sb_convergence(_pattern(name="demand_pull_substitution", contract="palm_cme",
                                     matched=("IDR_USD", "MYR_USD"),
                                     matched_measured=("IDR_USD", "MYR_USD"), n_matched=2,
                                     n_declared=3, threshold=2), series_of=smap)
    assert "are one reading the graph signs differently here, and count once" in line
    assert "are one reading and count once here" not in line, "the ALIAS words are a DIFFERENT claim"
    # (2) A DECLARED PHASE PAIR reads as phases on BOTH lines, never as an alias of one another
    pf = R.phase_in_force("silver_noaa_oni", "oni_anom", 0.2)          # inside the line: none in force
    pmap = {"El_Nino": {"key": "silver_noaa_oni:oni_anom", "confidence": "medium", "sign": "-",
                        "phase": pf},
            "La_Nina": {"key": "silver_noaa_oni:oni_anom", "confidence": "high", "sign": "+",
                        "phase": pf}}
    assert R.fold_relation(["El_Nino", "La_Nina"], pmap) == "phase"
    enso = R.sb_convergence(_pattern(name="bullish_supply_squeeze", contract="palm_cme",
                                     matched=("El_Nino", "La_Nina"),
                                     matched_measured=("El_Nino", "La_Nina"), n_matched=2,
                                     n_declared=6, threshold=3), series_of=pmap)
    assert "are two phases of one reading and count once here" in enso
    # (3) AND THE PLAIN ALIAS CASE IS UNTOUCHED
    amap = {"board_crush": {"key": "gold_board_crush:m", "confidence": "medium", "sign": "+",
                            "phase": {}},
            "soybean_crush_margin": {"key": "gold_board_crush:m", "confidence": "high", "sign": "+",
                                     "phase": {}}}
    assert R.fold_relation(["board_crush", "soybean_crush_margin"], amap) == "alias"


def test_M5_ONE_PAGE_ONE_PATTERN_ONE_COUNT_on_the_b40_fixture():
    """MEASURED BY THE REVIEWER ON THE b40 FIXTURE, both lines on one page and both reachable on arm A's
    treatment cell (the board and watch flags ride together):

      quorum: "policy-shock spike ... ONE OF THE TWO conditions it names is showing here (export ban);
               export ban and DMO are one reading and count once here"
      watch:  "this reading is one of TWO OF THE TWO drivers the pattern policy-shock spike declares
               that are moving furthest from their own records here"

    The watch producer read ``pr['n_matched']`` and never saw the fold at all."""
    from leviathan.graphrag.state import __main__ as H
    ctx = H.build_scenario("b40_event")
    bd, ana = ctx["board"], ctx["analogs"]
    quorum = [l for l in ctx["block"].lines if l.startswith("- policy-shock spike")]
    assert quorum, "the b40 fixture must carry the policy-shock quorum row"
    rows = WA.nonobvious_rows(bd, analogs=ana)
    watch = [w for w in rows if w.get("kind") == "convergence_amplified"
             and "policy-shock spike" in str(w.get("what") or "")]
    assert watch, "and its watch nomination"
    # ONE fold clause, in ONE spelling, on both
    fold_words = "export ban and DMO are one reading and count once here"
    assert fold_words in quorum[0] and fold_words in watch[0]["what"]
    # ONE count: the quorum says ONE condition is showing; the watch no longer says two drivers are
    assert "one of the two conditions it names is showing here" in quorum[0]
    assert "the ONLY one of the two drivers" in watch[0]["what"]
    assert "one of two of the two drivers" not in watch[0]["what"]
    # ...and the producer both read is the one producer
    assert R.pattern_count(
        [c for c in bd.convergence if c["name"] == "policy_shock_spike"][0],
        R.series_by_driver(bd))["n_distinct"] == 1


def test_M8_the_palm_ONI_row_reaches_the_RENDERED_BOARD_through_the_PRODUCER(oni_pair):
    """THE FIXTURE MUST REACH THE PRODUCER, NOT A HAND RE-IMPLEMENTATION. ``state/__main__.py`` (not
    lane D's file) re-implements ``feeders``' offset slice by hand, so the harness's ONI rows carry no
    ``recency['current_level']`` and round 1's new handle had NEVER been rendered on a board by
    anything. This pin puts the PRODUCER's own state on the b40 board and renders it.

    MEASURED, the ONI row before -> after: the harness's hand slice served 2026-02-28 with no
    newest-knowable figure at all; the producer serves level_date 2026-01 (the declared six-month
    effect lag) PLUS ``[N] the newest knowable reading of the same series is -1.4 degC for 2026-07``."""
    from leviathan.graphrag.state import __main__ as H
    from leviathan.graphrag.state import narration as N
    from leviathan.graphrag.state.rows import status_word
    _bean, palm = oni_pair
    ctx = H.build_scenario("b40_event")
    bd, ana = ctx["board"], ctx["analogs"]
    for r in bd.rows:
        if r.contract == "malaysian_crude_palm_oil_cme" and r.driver_id in ("El_Nino", "La_Nina"):
            r.state = palm
    ages = {r.key: N.age_clause(r.state.knowledge_date, bd.asof, r.state.cadence)
            for r in bd.rows if r.state is not None and status_word(r.state.status) == "ok"
            and N.age_clause(r.state.knowledge_date, bd.asof, r.state.cadence)}
    blk = R.render_board(bd, analogs=ana, watch=ctx["watch"], recency=N.recency_rows(bd, tape_edge=""),
                         age_clauses=ages,
                         anchor_label=", ".join(R.board_label(s) for s in bd.anchor_slugs))
    # RE-BANKED 09-23 FIX ROUND -- CONTRACT C1 identity words (09-23 recon soyoil_palm L2; BUILD_R sec 7 W-1): the SB-1
    # head names the SERIES first and routes the driver ("..., on CME palm oil (NOAA ONI), read here for El Nino"),
    # the shifted period prints as "<Month YYYY>", and the effect lag rides the identity.
    oni = [l for l in blk.lines if l.startswith("- [N") and "on CME palm oil (NOAA ONI), read here for El Nino" in l]
    assert oni, "the palm ONI state row must render"
    # RE-BANKED 09-24 FIX ROUND 2 -- CONTRACT K2 (DM1): the producer's own shifted period rides the figure token.
    assert "degC, January 2026;" in oni[0], "the DATE, after: the producer's own shifted period"
    assert "read six months back -- the reading whose declared lag lands now" in oni[0]
    assert "the newest knowable reading of the same series is -1.4 degC for 2026-07" in oni[0]
    assert R.classify(oni[0]) == ("SB-1",)
    # MINOR 6: the second figure of a two-sided series keeps the SIGN the level above carries
    assert "is -1.4 degC" in oni[0] and "is 1.4 degC" not in oni[0]


def test_M10_the_phase_verdict_is_read_off_the_NEWEST_KNOWABLE_level(oni_pair):
    """AFTER_blocks.txt:337 -- "The phase in force AT THIS READING is the cool phase" -- was computed
    from ``_rows[0].state.level``, the SIX-MONTH-SHIFTED number. On the producer's own palm row the two
    readings sit on OPPOSITE sides of the publisher's line: the shifted level is +0.764 degC (WARM) and
    the newest knowable reading is -1.4 degC (COOL). Round 1 would have declared the WARM phase in force
    on a page whose own newest figure is cool."""
    _bean, palm = oni_pair
    assert palm.level > 0 and palm.recency["current_level"] < 0, "the fixture must straddle the line"
    old = R.phase_in_force(palm.table, palm.metric, palm.level)          # round 1's rule
    new = R.phase_for_state(palm)                                        # this landing's
    assert old["driver"] == "El_Nino" and old["in_force"] is True
    assert new["driver"] == "La_Nina" and new["in_force"] is True, "the VERDICT FLIPS"
    assert new["current"] is True and new["offset_periods"] == 6
    lvl, current = R.phase_reading(palm)
    assert current is True and lvl == palm.recency["current_level"]
    # and the LINE says which reading it read the phase off, and what the dated one above it is
    ph = {"words": "the cool phase", "other_words": "the warm phase", "in_force": True,
          "live_name": "La Nina", "live_sign": "in the opposite direction", "other_name": "El Nino",
          "other_sign": "in the same direction", "current": True, "offset_periods": 6,
          "cadence": "monthly"}
    line = R.sb_phase_pair(["El Nino", "La Nina"], "CME palm oil", opposed=True, phase=ph)
    assert "The phase in force at the newest knowable reading of this series is the cool phase" in line
    assert ("The dated reading above sits six months back on this market's own declared effect lag, so "
            "whichever phase IT sits in is not the phase in force now.") in line
    assert not any(ch.isdigit() for ch in line), "SB-JOIN is letters-only"
    # a row with NO applied offset says "at this reading", exactly as it did
    plain = dict(ph, current=False, offset_periods=0)
    assert "The phase in force at this reading is the cool phase" in R.sb_phase_pair(
        ["El Nino", "La Nina"], "CME palm oil", opposed=True, phase=plain)


def test_M10_the_quorum_does_NOT_COUNT_THE_OPPOSITE_PHASE_on_the_b40_fixture():
    """AFTER_blocks.txt:337 declared the COOL phase in force and :368, fifteen lines below, counted
    ``El Nino`` into "five of the six conditions it names are showing here" -- the exact story the smoke
    charged ("the writer built a palm supply-squeeze on a cool number"). Loudness ranks the UNSIGNED
    state, so both members of a phase pair land loud on one reading."""
    from leviathan.graphrag.state import __main__ as H
    lines = H.build_scenario("b40_event")["block"].lines
    squeeze = [l for l in lines if l.startswith("- supply squeeze")]
    join = [l for l in lines if l.startswith("BOARD JOIN El Nino and La Nina")]
    assert squeeze and join
    assert "the cool phase" in join[0], "the fixture's ONI reading is cool"
    assert "four of the six conditions it names are showing here" in squeeze[0]
    assert "five of the six" not in squeeze[0]
    # THE NAME IS NEVER STRUCK -- it is stated, with the reason
    assert ("El Nino names the phase opposite the one in force on that reading, so it is not counted "
            "here") in squeeze[0]
    # and the SAME rule on the IOD pair, the other way round
    over = [l for l in lines if l.startswith("- oversupply")]
    assert over and "IOD negative names the phase opposite the one in force" in over[0]


def test_M9_showing_here_is_said_only_of_the_rows_that_WERE_READ():
    """AFTER_blocks.txt:71: "trade-war demand loss ... FOUR OF THE FOUR conditions it names ARE SHOWING
    HERE (export pace lag, with its own [N] z); three of them carry no series read here (China import
    tariff, section301 tariffs and China state reserves)". HEAD's "sit among this board's loudest rows"
    was a claim about RANK and survived that arithmetic; "are showing" is a claim about OBSERVATION."""
    row = _pattern(name="bearish_trade_war", contract="soybeans_cbot", n_declared=4, threshold=2,
                   matched=("export_pace_lag", "China_import_tariff", "section301_tariffs",
                            "China_state_reserves"), n_matched=4,
                   matched_measured=("export_pace_lag",),
                   matched_unmeasured=("China_import_tariff", "section301_tariffs",
                                       "China_state_reserves"))
    line = R.sb_convergence(row)
    assert "one of the four conditions it names is showing here (export pace lag" in line
    assert "four of the four conditions it names are showing here" not in line
    # EVERY NAME STILL REACHES THE READER and the TOTAL -- the threshold's own number -- is stated
    for n in ("China import tariff", "section301 tariffs", "China state reserves"):
        assert n in line
    assert "three more are named by the pattern with no series read here" in line
    # RE-ANCHORED (review round 3, NEW-2): "are ON THIS PAGE" was false of a board carrying a
    # phase-opposed member, which is on the page and deliberately not in this number. The number is
    # the quorum's and did not move; the VERB now says which number it is.
    assert "so four of the four are counted here" in line
    assert "it asks for two, so the count here is at or past that number" in line
    assert R.classify(line) == ("SB-C",), "the class token survives the rewording"
    # a pattern with NOTHING read says so and never says "showing"
    none_read = R.sb_convergence(_pattern(matched_measured=(), n_matched=3,
                                          matched_unmeasured=("a", "b", "c"), n_declared=3))
    assert "none of the three conditions it names is showing here" in none_read
    assert "all three are named by the pattern with no series read here" in none_read
    assert R.classify(none_read) == ("SB-C",)


def test_DOCKET12_the_three_largest_moves_are_FIRST_in_the_block_one_line_each():
    """ROUND-2 DOCKET item 12. ``coverage.missed.loud`` named the loudest rows the writer never used on
    three of five served turns (max: N30/N45/N48). The state rows ARE rank-ordered, but each is followed
    by its own edge and projection lines, so the top three reach a reader as nine interleaved lines with
    no mark saying which three lead."""
    from leviathan.graphrag.state import __main__ as H
    for name in H.SCENARIOS:
        blk = H.build_scenario(name)["block"]
        lead = [(i, l) for i, l in enumerate(blk.lines) if l.startswith("LARGEST MOVE ")]
        assert len(lead) == R.LEAD_ROWS == 3, (name, lead)
        assert [i for i, _l in lead] == [1, 2, 3], (name, "first in the block, after the header")
        subjects = []
        for _i, line in lead:
            assert R.classify(line) == ("SB-LEAD",), line
            assert not any(ch.isdigit() for ch in line), "SB-LEAD is letters-only and mints no handle"
            assert "its figures are on its own state line below" in line
            subjects.append(line.split(": ", 1)[1].split(";")[0].split(",")[0])
        assert len(set(subjects)) == 3, (name, subjects)


def test_DOCKET12_the_lead_is_FOLDED_and_names_what_the_other_folds_name():
    """A PHASE TWIN IS ONE READING. Loudness is phase-blind, so El Nino and La Nina both land loud on
    one ONI print and an unfolded lead would have spent two of its three lines on it -- the very double
    count the SB-JOIN line below corrects and ``board_coverage``'s own denominator folds. And on the b40
    policy group the lead names ``export ban``, the name the JOIN line tells the reader to use."""
    from leviathan.graphrag.state import __main__ as H
    sb = [l for l in H.build_scenario("soybeans_now")["block"].lines if l.startswith("LARGEST MOVE ")]
    assert any("El Nino on CBOT soybeans" in l for l in sb)
    assert not any("La Nina" in l for l in sb), "one ONI reading, one lead line"
    b40 = H.build_scenario("b40_event")["block"]
    leads = [l for l in b40.lines if l.startswith("LARGEST MOVE ")]
    join = [l for l in b40.lines if l.startswith("BOARD JOIN CPO export levy")]
    assert join and "read it under export ban" in join[0]
    assert any("export ban on CME palm oil" in l for l in leads)
    assert not any("CPO export levy" in l or "DMO on CME palm oil" in l for l in leads)


def test_DOCKET12_coverage_grades_the_three_the_block_LEADS_with():
    """"coverage.missed.loud must be EMPTY for those three or the mandate names the omission" -- so the
    three get their own numerator. A page that cites them reads three of three; a page that cites
    nothing names all three, and that list is what the mandate is told to explain."""
    from leviathan.graphrag.state import __main__ as H
    ctx = H.build_scenario("soybeans_now")
    blk = ctx["block"]
    cov_none = R.board_coverage(ctx["board"], "nothing in particular", n_start=1, calls=blk.calls)
    assert cov_none["loud_lead_rows"] == 3 and cov_none["loud_lead_referenced"] == 0
    assert len(cov_none["missed"]["loud_top3"]) == 3
    assert set(cov_none["missed"]["loud_top3"]) <= set(cov_none["missed"]["loud"])
    # the block scored against ITS OWN text names every lead row
    cov_self = R.board_coverage(ctx["board"], blk.text(), n_start=1, calls=blk.calls)
    assert cov_self["loud_lead_referenced"] == 3
    assert cov_self["missed"]["loud_top3"] == ()


def test_MINOR5_the_offset_flag_is_the_PRODUCERS_OWN_BOOLEAN_and_not_a_string_search(oni_pair):
    """The "ONE literal" contract had FOUR writers and two of them omit the literal: a ``_Fold`` refusal
    (base ref absent from the board map, or a different table / native unit) sets ``apply_offset=False``
    and writes a note carrying neither ``OFFSET_NOT_APPLIED`` nor a shift, so the row would have told a
    reader its date is an effect lag over an UNSHIFTED level."""
    _bean, palm = oni_pair
    assert palm.recency["offset_applied"] is True
    assert R._offset_applied(palm) is True

    class _St:
        offset_months, offset_note, recency = 6, "", {}
    st = _St()
    assert R._offset_applied(st) is True                        # the legacy fallback still answers
    st.offset_note = f"a declared 6-month offset {F.OFFSET_NOT_APPLIED}: the fetched history is 4"
    assert R._offset_applied(st) is False
    # THE HOLE THE OLD CONTRACT LEFT: a refusal note with NEITHER the literal NOR a shift
    st.offset_note = "the base ref is not on this board's map, so no shift was attempted"
    assert R._offset_applied(st) is True, "this is the defect the boolean closes"
    st.recency = {"offset_applied": False}
    assert R._offset_applied(st) is False, "...and the producer's own flag closes it"


# === ADVERSARIAL REVIEW ROUND 3 -- THE SIX THE ROUND-2 FIX INTRODUCED =================================
# Every pin below reproduces the REVIEWER'S OWN measurement first and then asserts the correction, and
# the ones that touch a rendered surface read the REAL thirty-six-DAG scenarios, never a hand fixture.
def _r3_boards():
    """The three offline scenarios, built once per session (the reviewer's own configuration)."""
    from leviathan.graphrag.state import __main__ as H
    if not getattr(_r3_boards, "_memo", None):
        _r3_boards._memo = {n: H.build_scenario(n) for n in H.SCENARIOS}
    return _r3_boards._memo


def _r3_watch_lines():
    out = []
    for ctx in _r3_boards().values():
        for w in WA.nonobvious_rows(ctx["board"], analogs=ctx["analogs"]):
            if w.get("kind_words"):
                out.append(R.sb_watch(w))
    return out


def test_NEW1_the_watch_draw_carries_ZERO_desk_register_hits_on_the_SHIPPED_instrument():
    """REVIEW ROUND 3, NEW-1 -- A MEASURED REGRESSION ON THE SURFACE THE ARM SERVES.

    ``register.desk_register_hits`` over the 37 non-obvious watch lines of the three scenarios read
    ZERO after round 1 and THREE after round 2, all of them ('the graph', 'carries and the graph does
    not na') and all from ONE clause the round-2 fix added to ``_faster_series_words``. That is the
    SHIPPED instrument -- the one S7b's mandate exists to drive to zero (51 -> 5 at source) -- and the
    round-2 report's refutation of review minor 8 asserted the opposite in as many words.

    The replacement is ``DESK_REGISTER_TOKENS``' OWN column for the token, so the lint and the block
    teach one vocabulary. THE PIN IS ON THE DRAW AND NOT ON THE BLOCK, because reading only the block
    is exactly how the regression shipped."""
    from leviathan.graphrag import register as REG
    lines = _r3_watch_lines()
    assert len(lines) >= 30, len(lines)                 # the draw is really there
    hits = [h for line in lines for h in REG.desk_register_hits(line)]
    assert hits == [], hits
    # and the clause that charged is still a SENTENCE about the same two facts, not a deletion
    notes = [l for l in lines if "the reading on this page that can turn inside the horizon is" in l]
    assert notes, "the faster-series clause still renders"
    for n in notes:
        assert "the graph" not in n
        assert "condition of the same" in n


def test_NEW2_the_count_and_the_ENUMERATION_agree_on_the_b40_oversupply_row():
    """REVIEW ROUND 3, NEW-2 -- "SO FOUR OF THE FIVE ARE ON THIS PAGE" ON A PAGE THAT CARRIES FIVE.

    Rendered on the b40 board, verbatim: "two of the five conditions it names are showing here (La Nina
    and ending stocks ...); IOD negative names the phase opposite the one in force on that reading, so
    IT IS NOT COUNTED HERE; two more are named by the pattern with no series read here (export pace lag
    and USD index), so four of the five ARE ON THIS PAGE". The fifth, IOD negative, is on the page --
    the sentence prints its reading one clause earlier and the board renders its SB-1 row with handles.

    ``n_distinct`` IS THE QUORUM'S NUMBER AND IT DOES NOT MOVE (it under-claims, the only safe direction
    for a quorum, and the threshold reads it). What moves is the VERB, and the two clauses now add up:
    four counted plus one not counted is five."""
    ctx = _r3_boards()["b40_event"]
    line = [l for l in ctx["block"].lines if l.startswith("- oversupply")]
    assert line, "the b40 oversupply quorum row"
    line = line[0]
    # 09-25 RE-BANK (lane W, W-2 / N4 -- THE PATTERN QUORUM IS TAIL-AWARE): the oversupply pattern is
    # price-pressuring and names MPOB ending stocks, declared `-`, so it asks for HIGH stocks; the b40
    # fixture's stocks read on the LOW side of their record, so the walk states them AGAINST the pattern
    # (`against`) and no longer counts them -- HEAD counted "two of the five ... showing (La Nina and ending
    # stocks)" and "four of the five". The phase-opposed member (IOD negative) and the two unread members are
    # HEAD's. THE SENTENCE NAMED FOUR OF THE FIVE until the render printed the walk's `against`.
    # 09-25 CLOSE-OUT RE-BANK (lane RW, RW-1 = R-W2, VERIFY MAJOR-1): the render now reads `against` /
    # `unsided`, so the fifth condition is STATED by name with its reason, after the phase-opposed clause --
    # "one of them reads in the tail opposite the one the pattern names (Malaysian closing palm oil stocks,
    # read here for ending stocks), so it counts against the pattern here". THE COUNT DID NOT MOVE (three of
    # the five counted); the sentence now names all five: one showing + one phase-opposed + one against + two
    # unread.
    assert "so three of the five are counted here" in line
    assert "are on this page" not in line
    assert "one of the five conditions it names is showing here" in line
    assert "so it is not counted here" in line
    assert "two more are named by the pattern with no series read here" in line
    assert ("; one of them reads in the tail opposite the one the pattern names (Malaysian closing palm oil "
            "stocks, read here for ending stocks), so it counts against the pattern here; two more") in line
    for name in ("read here for La Nina", "IOD negative", "read here for ending stocks", "export pace lag",
                 "USD index"):
        assert name in line, name
    _ov = next(c for c in ctx["board"].convergence
               if c["name"] == "bearish_oversupply" and c["contract"] == "malaysian_crude_palm_oil_cme")
    assert _ov["against"] == ("ending_stocks",) and _ov["unsided"] == ()
    assert (len(_ov["matched"]) + len(_ov["against"]) + len(_ov["unsided"])) == _ov["n_declared"]
    assert R.classify(line) == ("SB-C",)
    # ONE PAGE, ONE PATTERN, ONE COUNT: the watch sentence carries the same number under the same verb
    watch = [R.sb_watch(w) for w in WA.nonobvious_rows(ctx["board"], analogs=ctx["analogs"])
             if w.get("kind_words") and "oversupply" in str(w.get("what") or "")]
    assert watch and any("of the five counted here" in w for w in watch), watch
    assert not any(" in all" in w for w in watch)


def test_NEW3_the_quorum_hole_clause_EXCLUDES_a_driver_whose_reading_this_block_prints():
    """REVIEW ROUND 3, NEW-3 -- "NONE OF THOSE DRIVERS HAS A SERIES READ HERE" BESIDE ONE'S OWN READING.

    The reviewer's own reproduction (``prearm_fix_r2/RVD/rv_quorum_holes.py``, case A), re-typed here
    verbatim: a pattern whose ONLY series-bearing driver is the out-of-force member of a declared phase
    pair. ``sb_convergence``'s ``else`` arm hardcoded the parenthetical for ``n_measured == 0``, and
    after MAJOR 10 ``n_measured == 0`` no longer means "nothing was read": the next clause in the SAME
    sentence names the driver and states its reading. The parenthetical now reads off
    ``n_phase_opposed``. Reachable on any board where a pattern's only measured driver is the opposed
    member of a declared pair -- the estate declares ``El_Nino`` on 35 DAGs and ``IOD_positive`` on 18.
    """
    ph = {"driver": "IOD_positive", "other_driver": "IOD_negative", "in_force": True,
          "live_name": "IOD positive", "words": "the positive phase", "other_name": "IOD negative",
          "other_words": "the negative phase", "current": False, "current_date": "",
          "offset_periods": 0, "cadence": "monthly"}
    smap = {"IOD_negative": {"key": "iod|_global|", "confidence": "high", "sign": "positive",
                             "phase": ph},
            "ending_stocks": {"key": "mpob|stocks|", "confidence": "high", "sign": "negative",
                              "phase": {}}}
    row = {"name": "oversupply", "contract": "malaysian_crude_palm_oil_cme", "n_declared": 3,
           "threshold": 2, "n_with_band": 0, "matched": ["IOD_negative", "area"],
           "matched_measured": ["IOD_negative"], "matched_unmeasured": ["area"]}
    line = R.sb_convergence(row, series_of=smap)
    assert R.pattern_count(row, smap)["n_phase_opposed"] == 1
    assert "none of those drivers has a series read here)" not in line, "the false absence"
    assert "none of those drivers has a series read here in the phase the pattern names" in line
    # the reading the block prints is still named, with its reason, and nothing was deleted
    assert "IOD negative names the phase opposite the one in force" in line
    assert R.classify(line) == ("SB-C",), "the class token survives"
    # AND THE UNOPPOSED CASE IS UNTOUCHED, word for word
    plain = R.sb_convergence(dict(row, matched=["a", "b", "c"], matched_measured=[],
                                  matched_unmeasured=["a", "b", "c"]), series_of={})
    assert ("none of the three conditions it names is showing here (none of those drivers has a "
            "series read here)") in plain


def test_NEW4_ONE_SERIES_GROUP_PRINTS_ONE_KEPT_NAME_EVERYWHERE_ON_THE_PAGE():
    """REVIEW ROUND 3, NEW-4 -- THE "CAN NEVER NAME ONE READING THREE WAYS" CLAIM WAS FALSE.

    The reviewer's reproduction (``prearm_fix_r2/RVD/rv_names.py``): one series key, three names, A at
    HIGH and B and C at MEDIUM, and a pattern matching only B and C. The JOIN chose its kept name over
    the WHOLE group and the quorum over the pattern's MATCHED SUBSET, so the page said "read it under
    EXPORT BAN" and, fifteen lines down, "(CPO levy, with its own [N] z)". ``group_keep`` is now the one
    rule and the one population for the lead, the JOIN and the quorum.

    AND MAJOR 3's RULING SURVIVES IT. Where the members TIE and their signs disagree the JOIN says, in
    words, that this page has no ground for preferring a name -- so the producer offers none and the
    quorum keeps the name the pattern matched. Without that clause the b40 substitution-demand-pull row
    renamed a matched MYR USD to IDR USD: the Indonesian rupiah as the reading of a Malaysian palm
    board, which is the exact defect round 2 closed."""
    smap = {"export_ban": {"key": "psd|export|ID", "confidence": "high", "sign": "positive",
                           "phase": {}},
            "DMO": {"key": "psd|export|ID", "confidence": "medium", "sign": "positive", "phase": {}},
            "CPO_levy": {"key": "psd|export|ID", "confidence": "medium", "sign": "positive",
                         "phase": {}}}
    row = {"name": "policy-shock spike", "contract": "malaysian_crude_palm_oil_cme", "n_declared": 2,
           "threshold": 1, "n_with_band": 0, "matched": ["DMO", "CPO_levy"],
           "matched_measured": ["DMO", "CPO_levy"], "matched_unmeasured": []}
    join = R.sb_phase_pair(["CPO export levy", "DMO", "export ban"], "CME palm oil", opposed=False,
                           keep="export ban", alias=("CPO export levy", "DMO"))
    quorum = R.sb_convergence(row, series_of=smap)
    assert "read it under export ban" in join
    assert "(export ban, with its own [N] z)" in quorum, quorum
    assert "(CPO levy, with its own [N] z)" not in quorum, "round 2's second name"
    # nothing is deleted: every name the pattern matched still reaches the reader, folded once
    for n in ("export ban", "CPO levy", "DMO"):
        assert n in quorum
    assert R.pattern_count(row, smap)["n_measured"] == 1, "the count does not move"
    # the ONE rule, read three ways
    assert R.group_keep(smap, "psd|export|ID") == "export_ban"
    # THE TIE: signs disagree and the confidences tie -> the producer offers no name under `strict`
    fx = {"IDR_USD": {"key": "fx|usd|", "confidence": "medium", "sign": "-", "phase": {}},
          "INR_USD": {"key": "fx|usd|", "confidence": "medium", "sign": "-", "phase": {}},
          "MYR_USD": {"key": "fx|usd|", "confidence": "medium", "sign": "+", "phase": {}}}
    assert R.group_keep(fx, "fx|usd|", strict=True) == ""
    assert R.group_keep(fx, "fx|usd|") == "IDR_USD", "the un-strict caller still gets a name"
    fxrow = {"name": "substitution demand pull", "contract": "malaysian_crude_palm_oil_cme",
             "n_declared": 3, "threshold": 2, "n_with_band": 0,
             "matched": ["MYR_USD", "import_tariff"], "matched_measured": ["MYR_USD"],
             "matched_unmeasured": ["import_tariff"]}
    assert "(MYR USD, with its own [N] z)" in R.sb_convergence(fxrow, series_of=fx)


def test_NEW5_a_PHASE_OPPOSED_row_loses_its_MEMBERSHIP_and_keeps_its_RANK_TERM():
    """REVIEW ROUND 3, NEW-5 -- M10b's BLAST RADIUS, AND THE SHIPPED COMMENT THAT DENIED IT.

    ``_pattern_facts`` ``continue``d over the whole row, under a comment promising it "keeps every other
    claim it can make (it is still loud, still past its line, STILL A SPILLOVER SOURCE)". ``pat['rank']``
    is ``T_AMPLIFIER``, the FIRST term of ``rank_key``, and it is stamped on EVERY candidate the row
    produces -- so refusing membership demoted the row's SPILLOVER, TAIL and LINE candidates too.

    MEASURED by the reviewer as an exact set difference of the drawn (kind, row) pairs on b40: El Nino
    left the draw ENTIRELY, including ``spillover_reach`` -- "this same reading is declared on N other
    markets" is true of El Nino whichever phase is in force. The refusal is now scoped to the
    MEMBERSHIP; the rank term is the floor over every pattern that NAMES the row."""
    ctx = _r3_boards()["b40_event"]
    bd, ana = ctx["board"], ctx["analogs"]
    drawn = {(w.get("kind"), w.get("row")) for w in WA.nonobvious_rows(bd, analogs=ana)}
    # RE-BANKED 09-24 FIX ROUND 2 -- CONTRACT K26 (DM1, BUILD_R sec 2): "the same reading" is ONE series and a
    # declared phase pair states it for the POLE IN FORCE (lane W's `pole_in_force` stamp) -- the ONI reach is
    # still drawn, on the in-force pole's row, and never demoted by the refused membership below.
    _pole = next(e.get("pole_in_force") for e in bd.fan if e.get("contract") == "malaysian_crude_palm_oil_cme"
                 and e.get("driver_id") == "El_Nino")
    assert _pole in ("El_Nino", "La_Nina"), _pole
    assert ("spillover_reach", ("malaysian_crude_palm_oil_cme", _pole)) in drawn, sorted(
        str(d) for d in drawn)
    # ...and the MEMBERSHIP is still refused, which is what MAJOR 10 bought
    assert ("convergence_amplified", ("malaysian_crude_palm_oil_cme", "El_Nino")) not in drawn
    row = next(r for r in bd.rows
               if r.contract == "malaysian_crude_palm_oil_cme" and r.driver_id == "El_Nino")
    pat = WA._pattern_facts(bd, row, list(bd.convergence), R.series_by_driver(bd))
    assert pat["member"] is False and pat["row"] is None, pat
    assert pat["rank"] < WA.AMPLIFIER_LEVELS["neutral"], (
        "the rank term the row earned from a pattern that NAMES it: %s" % pat["rank"])


def test_NEW6_the_horizon_NOTE_names_the_JOINs_KEPT_NAME_and_not_the_alias_it_forbids():
    """REVIEW ROUND 3, NEW-6 -- THE NOTE POINTED AT THE ALIAS THE SAME PAGE FORBIDS.

    Rendered on ``soybeans_now``: the block's SB-JOIN line says "read it under SOYBEAN CRUSH MARGIN and
    treat BOARD CRUSH as that name's alias, counted once wherever this page counts", and all three
    horizon notes on the same page said "the reading on this page that can turn inside the horizon is
    BOARD CRUSH". ``_faster_series_words`` was a THIRD name-picker: it picked a ROW, never a READING.

    The grain printed beside the name is that name's OWN row, so the note cannot name one reading and
    date another."""
    ctx = _r3_boards()["soybeans_now"]
    lines = [R.sb_watch(w) for w in WA.nonobvious_rows(ctx["board"], analogs=ctx["analogs"])
             if w.get("kind_words")]
    notes = [l for l in lines if "the reading on this page that can turn inside the horizon is" in l]
    assert notes, "the three horizon notes"
    join = [l for l in ctx["block"].lines
            if l.startswith("BOARD JOIN") and "soybean crush margin" in l]
    assert join and "read it under soybean crush margin" in join[0]
    for n in notes:
        assert "is soybean crush margin on CBOT soybeans" in n, n
        assert "is board crush on CBOT soybeans" not in n
        assert "which prints every session" in n, "the grain is the kept name's own row"


def test_NEW_ONELINER_the_recency_max_is_taken_over_NORMALISED_DATES_walk_1964():
    """THE ONE-LINER HANDED TO THIS LANE (``walk.py:1964-1965``), and lane A's measured defect.

    ``"20260904" > "2026-09-14"`` as strings, because ``-`` (0x2D) sorts below ``0`` (0x30), so an ESR
    row's undashed stamp won a lexical ``max`` it should have lost and the served ledger sentence stated
    a ten-day-old date as the newest. A print-side fix spells the WRONG date correctly.
    ``narration.iso_date`` is lane A's ONE producer and is the only normaliser in the path."""
    import inspect

    from leviathan.graphrag.state import narration as N
    from leviathan.graphrag.state import walk as W
    assert "20260904" > "2026-09-14", "the defect, in one line"
    assert N.iso_date("20260904") < N.iso_date("2026-09-14"), "and the producer that closes it"
    src = inspect.getsource(W)
    assert 'bd.recency["numbers"] = max((_iso_date(' in src, "the max is over normalised dates"
    assert 'bd.recency["text"] = max((_iso_date(' in src
    assert "def _iso_date" not in src, "no second normaliser is written here"
    # ...and the value the board banks IS the normalised max on every scenario
    for name, ctx in _r3_boards().items():
        bd = ctx["board"]
        want = max((N.iso_date(st.knowledge_date) or "" for st in bd.series.values()), default="")
        assert bd.recency["numbers"] == want, (name, bd.recency["numbers"], want)


def test_NEW_ONELINER_the_SB_L_sample_is_the_line_the_class_ACTUALLY_RENDERS_lint_762():
    """THE SECOND ONE-LINER: ``lint``'s SB-L sample carried the RETIRED wording.

    "the newest knowledge date on a number row is ..." is what ``narration.recency_rows`` replaced in
    pre-arm round 1 -- the block's only source of ``knowledge date`` and of three ``row`` charges on the
    five served bodies, and the exact phrasing the desk-register mandate beside it bans. A lint's sample
    is the sentence the file holds up as the class's example; holding up a retired one teaches the
    retired vocabulary."""
    import inspect
    src = inspect.getsource(L)
    assert "the newest knowledge date on a number row is" not in src, "the retired wording"
    assert "the newest number here is known" in src, "the wording the class renders"
    assert L.check_state_board() == []
    # the sample is the LINE, taken off a real board
    ctx = _r3_boards()["soybeans_now"]
    rendered = [l for l in ctx["block"].lines if l.startswith("RECENCY numbers:")]
    assert rendered and "the newest number here is known" in rendered[0]
    assert "knowledge date" not in rendered[0]
    assert R.classify(rendered[0]) == ("SB-L",)


# === THE 09-25 CLOSE-OUT, LANE RW -- RW-1 (VERIFY MAJOR-1): THE RENDER HALF OF THE TAIL-AWARE QUORUM =====
@pytest.fixture(scope="module")
def shipped_graph():
    from leviathan.graphrag import graph as G
    return G.CausalGraph(G.load_contracts(), silver=set(), version="test")


def _rw1_cocoa(graph):
    """The 09-25 cocoa page's own three loud conditions of the West Africa deficit squeeze, with the trace's
    served readings (`state_board.row_states`): harmattan on the West Africa max-temperature anomaly (-1.23 z,
    the 6th percentile: COOL), drought on the dry-day run (-1.49 z, the 3rd percentile: WET), and the unread
    export-pace lag."""
    from leviathan.graphrag.state import board as B
    from leviathan.graphrag.state import walk as W
    from leviathan.graphrag.state.rows import SeriesKey, StateRow

    def _st(ref, metric, level, z, pct):
        return StateRow(key=SeriesKey(ref=ref, commodity="cocoa", country="West Africa"), status="ok",
                        coverage_tier="series", table="gold_weather_z", metric=metric, cadence="monthly",
                        unit="z", narrate_unit="z", level=level, level_date="2026-08",
                        z={"value": z, "window_n": 120}, percentile={"value": pct, "n": 120})

    def _row(did, st=None):
        d = next(x for x in graph.contracts["cocoa"].drivers if x.id == did)
        r = W._node_row(graph, "cocoa", d)
        if st is not None:
            r.state, r.series_key = st, st.key.label()
        r.legs["loud"] = True
        return r
    rows = [_row("harmattan", _st("stage_tmax_anomaly", "tmax_anomaly", -0.668, -1.23, 6.4)),
            _row("drought", _st("drought_z", "drought_z", -0.918, -1.49, 3.4)),
            _row("export_pace_lag")]
    bd = B.Board(asof="2026-09-24", mode="deep")
    bd.rows = rows
    read = {r.driver_id for r in rows if r.state is not None}
    conv = W.convergence_rows(graph, "cocoa", {r.driver_id for r in rows}, loud_k=12, band_ids=set(),
                              measured_ids=read, sides={r.driver_id: W.row_side(r) for r in rows
                                                        if r.driver_id in read})
    return bd, next(c for c in conv if c["name"] == "west_africa_deficit_squeeze")


def test_RW1_the_COCOA_SQUEEZE_row_never_denies_a_read_series_and_names_both_against_readings(shipped_graph):
    """VERIFY MAJOR-1, THE ROUND'S HEADLINE FATAL ON THE PAGE: with lane W's side-aware quorum and HEAD's
    render, the cocoa row printed "none of the six conditions it names is showing here (none of those
    drivers has a series read here); all one are named by the pattern with no series read here (export
    pace lag)" -- FALSE for harmattan and drought, both read here ([N14] / [N20]), and neither named. The
    render now reads the walk's `against` / `unsided`: the parenthetical denies a read series only where
    nothing was read, each against reading is NAMED with its series identity and RT-3's side words (the
    page's own `condition_names` map), and the n=1 unread form is English. THE COUNT DOES NOT MOVE."""
    from leviathan.graphrag import register as REG
    bd, row = _rw1_cocoa(shipped_graph)
    assert row["against"] == ("harmattan", "drought") and row["matched_unmeasured"] == ("export_pace_lag",)
    names = R.condition_names(bd)
    line = R.sb_convergence(row, series_of=R.series_by_driver(bd),
                            names_of={d: w for (c, d), w in names.items() if c == "cocoa"})
    assert "has a series read here" not in line, line
    assert ("none of the six conditions it names is showing here (none of them reads in the tail the "
            "pattern names)") in line, line
    assert ("; two of them read in the tail opposite the one the pattern names (the maximum-temperature "
            "anomaly for West Africa, read here for harmattan, which reads on the low side (cooler than usual) "
            "and the longest dry-day run in the month, as a z-score for West Africa, read here for drought, "
            "which reads on the low side (shorter dry spells than usual, so wetter)), so they count against "
            "the pattern here") in line, line
    assert "; the one counted here is named by the pattern with no series read here (export pace lag)" in line
    assert "all one are" not in line
    assert "it asks for three, so the count here is short of that number" in line
    # THE COUNT IS THE WALK'S, UNCHANGED BY THE WORDS: the same row without the two keys counts the same
    bare = {k: v for k, v in row.items() if k not in ("against", "unsided")}
    assert R.pattern_count(row, R.series_by_driver(bd))["n_distinct"] == 1
    assert R.pattern_count(bare, R.series_by_driver(bd))["n_distinct"] == 1
    assert R.classify(line) == ("SB-C",) and R.register_hits(line) == []
    assert REG.desk_register_hits(line) == [], REG.desk_register_hits(line)
    # the amplifier over harmattan x drought keeps its rank claim and says which side they sit on
    amp = next(i for i in row["interactions"] if set(i["when"]) == {"harmattan", "drought"})
    a = R.sb_amplifier("cocoa", amp)
    assert ("are all among the largest moves here; harmattan and drought read on the side opposite the one "
            "the pattern names; the graph records the effect as") in a, a
    assert R.classify(a) == ("SB-M",) and R.register_hits(a) == []


def test_RW1_every_clause_reads_its_own_key_and_a_row_without_them_is_HEADs_byte_for_byte():
    """The four clauses of BUILD_W sec 6, each off its own list, in the render's own idiom (a count in words,
    the names in parentheses, the reason after) -- and the rows the walk did not side (`sides=None`, every
    board-off and every deck row) render exactly as before, keys absent OR empty."""
    from leviathan.graphrag import register as REG
    base = _pattern(name="bearish_trade_war", contract="soybeans_cbot", threshold=2, n_declared=4,
                    matched=("China_state_reserves",), n_matched=1, matched_measured=(),
                    matched_unmeasured=("China_state_reserves",))
    head = R.sb_convergence(base)
    assert R.sb_convergence(dict(base, against=(), unsided=())) == head, "empty lists are HEAD's row"
    assert ("none of the four conditions it names is showing here (none of those drivers has a series "
            "read here); the one counted here is named by the pattern with no series read here (China state "
            "reserves)") in head
    # (1)+(2) one reading on the other side: the parenthetical changes, the reading is named, singular
    one = R.sb_convergence(dict(base, against=("export_pace_lag",)),
                           names_of={"export_pace_lag": "US weekly exports, read here for export pace lag"})
    assert "(none of them reads in the tail the pattern names)" in one
    assert ("; one of them reads in the tail opposite the one the pattern names (US weekly exports, read here "
            "for export pace lag), so it counts against the pattern here") in one
    # no map: the driver's own words, never a raw id
    assert "(export pace lag), so it counts against" in R.sb_convergence(dict(base, against=("export_pace_lag",)))
    # (3) unsided -- a `0`-signed driver, or a reading in no tail -- stated, never counted
    uns = R.sb_convergence(dict(base, unsided=("eurusd_fx", "sagis_deliveries")))
    assert ("; two of them carry no committed direction for this pattern in the driver model, or sit in the "
            "middle of their own records (eurusd fx and sagis deliveries), so they are not counted here") in uns
    assert "(none of them reads in the tail the pattern names)" in uns
    # with a condition SHOWING, the lead is untouched and the clause still rides after the fold's
    shown = _pattern(name="bearish_glut", contract="soybeans_cbot", threshold=3, n_declared=5,
                     matched=("area",), n_matched=1, matched_measured=("area",), matched_unmeasured=(),
                     against=("psd_ending_stock_su_ratio",))
    s = R.sb_convergence(shown)
    assert "one of the five conditions it names is showing here (area, with its own [N] z)" in s
    assert "; one of them reads in the tail opposite the one the pattern names (psd ending stock su ratio)" in s
    # the phase-only case keeps NEW-3's true words (no against / unsided): pinned there, re-read here
    ph = {"driver": "IOD_positive", "other_driver": "IOD_negative", "in_force": True}
    smap = {"IOD_negative": {"key": "iod|_global|", "confidence": "high", "sign": "positive", "phase": ph}}
    phase_only = R.sb_convergence({"name": "oversupply", "contract": "malaysian_crude_palm_oil_cme",
                                   "n_declared": 3, "threshold": 2, "n_with_band": 0,
                                   "matched": ["IOD_negative"], "matched_measured": ["IOD_negative"],
                                   "matched_unmeasured": []}, series_of=smap)
    assert "none of those drivers has a series read here in the phase the pattern names" in phase_only
    # (4) the amplifier: HEAD's row where `against` is absent or empty
    inter = {"when": ("crude_oil_price", "biodiesel_mandate"), "effect": "amplifies", "note": "",
             "unmeasured": ("biodiesel_mandate",)}
    assert R.sb_amplifier("malaysian_crude_palm_oil_cme", inter) == R.sb_amplifier(
        "malaysian_crude_palm_oil_cme", dict(inter, against=()))
    one_side = R.sb_amplifier("malaysian_crude_palm_oil_cme", dict(inter, against=("crude_oil_price",)))
    assert "largest moves here; crude oil price reads on the side opposite the one the pattern names;" in one_side
    for l in (one, uns, s):
        assert R.register_hits(l) == [] and REG.desk_register_hits(l) == [], (l, REG.desk_register_hits(l))
    # the amplifier's own "the graph records" is HEAD's and outside this clause; the clause adds no hit
    assert [h[0] for h in REG.desk_register_hits(one_side)] == [h[0] for h in REG.desk_register_hits(
        R.sb_amplifier("malaysian_crude_palm_oil_cme", inter))] == ["the graph"]
    assert R.register_hits(one_side) == []


def test_N8R_MINOR_A_the_unsided_clause_names_the_model_through_the_desk_tables_ONE_reader(monkeypatch):
    """VERIFY_CLOSEOUT MINOR-A (the 09-25 N8 restore): RW-1's unsided clause TYPED the desk table's replacement
    for "the graph" as a literal -- a second copy of one declared vocabulary item (`register.DESK_REGISTER_TOKENS`,
    the MINOR-7 class). It now reads the phrase through the table's ONE reader, `register.desk_phrase`, the idiom
    of AT-4's `answer._desk_fork_words`: the phrase appears nowhere in render.py's source, the printed bytes
    are unchanged, and a table that teaches another phrase moves the clause with no second edit."""
    import inspect
    from leviathan.graphrag import register as REG
    phrase = REG.desk_phrase("the graph", 1)
    assert phrase == "the driver model", "the table's own column: the printed bytes do not move"
    assert phrase.lower() not in inspect.getsource(R).lower(), "a second typed copy of the desk table's phrase"
    base = _pattern(name="bearish_trade_war", contract="soybeans_cbot", threshold=2, n_declared=4,
                    matched=("China_state_reserves",), n_matched=1, matched_measured=(),
                    matched_unmeasured=("China_state_reserves",))
    one = R.sb_convergence(dict(base, unsided=("eurusd_fx",)))
    assert ("; one of them carries no committed direction for this pattern in the driver model, or sits in the "
            "middle of its own record (eurusd fx), so it is not counted here") in one, one
    # THE PHRASE COMES FROM THE REGISTER: re-declare the table's column and the clause follows
    taught = tuple((n, p, ("the mechanism, the causal map" if n == "the graph" else r))
                   for n, p, r in REG.DESK_REGISTER_TOKENS)
    monkeypatch.setattr(REG, "DESK_REGISTER_TOKENS", taught)
    moved = R.sb_convergence(dict(base, unsided=("eurusd_fx",)))
    assert "for this pattern in the causal map, or sits" in moved and phrase not in moved, moved
    assert moved.replace("the causal map", phrase) == one
