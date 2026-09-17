"""THE WATCH LIST -- STATE ENGINE DESIGN sec 5.1, and bar **B11**: "every SB-W names a table, a level, a
date or a document; ``next_release`` on a windowed rule returns a window, never a point; a forward
``event_date`` receipt renders with both dates; the kind-2 distance equals threshold minus state to the
printed precision." Sitting S3.

The calendar half of B11 is in ``test_state_calendar.py``; this file is the PRODUCER's half.
"""
import pytest
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import watch as WA
from leviathan.graphrag.state.feeders import state_from_arrays
from leviathan.graphrag.state.lagbands import parse_lag

ASOF = "2026-09-07"

ONI_CONV = {"kind": "abs_bands", "bands": [0.5, 1.0, 1.5, 2.0],
            "labels": ["elevated", "moderate", "strong", "extreme"], "unit": "degC"}
PCT_CONV = {"kind": "percentile_bands", "bands": [10, 90], "labels": ["low", "high"]}


def _months(n, start_year=2010, start_month=1):
    out, y, m = [], start_year, start_month
    for _ in range(n):
        last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
        out.append(f"{y:04d}-{m:02d}-{last:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _row(*, values, conv, ref="oni_climate", table="silver_noaa_oni", contract="soybeans_cbot",
         driver_id="El_Nino", lag="1-2 quarters", receipts=None, loud=True):
    d = _months(len(values))
    st = state_from_arrays(ref, values, d, cadence="monthly", asof=ASOF, unit="degC",
                           narrate_unit="degC", windows={"monthly": 60}, convention=conv,
                           table=table, metric="anom")
    r = B.NodeRow(contract=contract, driver_id=driver_id, lag_band=parse_lag(lag), state=st,
                  receipts=receipts or {"n": 0, "newest_date": None, "oldest_date": None, "top": []})
    r.legs["loud"] = loud
    return r


def _board(rows, *, mode="max", windows=None):
    bd = B.Board(asof=ASOF, mode=mode, knobs=B.board_knobs_of(mode),
                 anchors=(B.Anchor(contract=rows[0].contract, source="named"),))
    bd.rows = list(rows)
    bd.order = tuple(r.key for r in rows)
    bd.windows = dict(windows or {})
    return bd


# ── the closed enum ──────────────────────────────────────────────────────────────────────────────────
def test_the_kind_enum_is_closed_and_every_kind_has_words():
    assert len(WA.WATCH_KINDS) == 5
    assert set(WA.KIND_WORDS) == set(WA.WATCH_KINDS)
    for w in WA.KIND_WORDS.values():
        assert not any(ch.isdigit() for ch in w)


def test_the_render_cap_is_the_tiers_own_line_count():
    assert (WA.render_k("quick"), WA.render_k("deep"), WA.render_k("max")) == (3, 6, 8)
    assert WA.render_k("deep_hp") == 6                    # keyed on the BASE preset, like every table


# ── kind 2: the distance, and it is the ONLY kind that carries a figure ──────────────────────────────
def test_B11_the_kind_2_distance_equals_threshold_minus_state_to_the_printed_precision():
    v = [0.0] * 80 + [0.2, 0.4, 0.6, 0.98]
    cd = WA.convention_distance(_row(values=v, conv=ONI_CONV), conventions={"oni_climate": ONI_CONV})
    assert cd is not None
    assert cd["band"] == 1.0 and cd["label"] == "moderate"
    assert cd["distance"] == pytest.approx(1.0 - 0.98, abs=1e-9)
    assert cd["direction"] == "under" and cd["unit_words"] == "degC"


def test_the_line_measured_to_is_the_NEXT_ONE_IN_THE_READINGS_OWN_DIRECTION():
    """A reading at the ninety-ninth percentile, having crossed the high line, must not be measured
    "eighty-nine points over the LOW line" -- arithmetic on the far side of the record that nobody
    asked for."""
    v = [float(i) for i in range(80)] + [500.0]
    row = _row(values=v, conv=PCT_CONV, ref="mpob_ending_stocks", table="silver_mpob")
    assert WA.convention_distance(row, conventions={"mpob_ending_stocks": PCT_CONV}) is None


def test_the_distance_is_a_REGISTERED_transform_and_re_executes():
    """Sec 5.1 kind 2: "minted ... through a registered ``window_change``-shaped subtraction ...so it is
    a computed figure with a handle"."""
    from leviathan.graphrag.state import transforms as TR
    v = [0.0] * 80 + [0.2, 0.4, 0.6, 0.98]
    cd = WA.convention_distance(_row(values=v, conv=ONI_CONV), conventions={"oni_climate": ONI_CONV})
    assert TR.re_execute_all([cd["derivation"]], cd["inputs"]) == []


def test_a_percentile_line_prints_as_an_ORDINAL_POSITION_and_not_as_points():
    v = [float(i) for i in range(80)] + [40.0]
    row = _row(values=v, conv=PCT_CONV, ref="mpob_ending_stocks", table="silver_mpob")
    cd = WA.convention_distance(row, conventions={"mpob_ending_stocks": PCT_CONV})
    assert cd["band_words"].endswith("percentile") and cd["band_words"].startswith("the ")


def test_a_row_with_no_declared_convention_yields_no_kind_2_row():
    v = [0.0] * 80 + [0.2, 0.4, 0.6, 0.98]
    assert WA.convention_distance(_row(values=v, conv=None), conventions={}) is None


# ── B11: every row names a table, a level, a date or a document ─────────────────────────────────────
def _rows_for_a_board():
    v = [0.0] * 80 + [0.2, 0.4, 0.6, 0.98]
    row = _row(values=v, conv=ONI_CONV,
               receipts={"n": 1, "newest_date": "2026-08-20", "oldest_date": "2026-08-20",
                         "top": [{"date": "2026-08-20", "source": "a ministry",
                                  "event_date": "2026-11-15", "text": "a dated review"}]})
    bd = _board([row], windows={row.key: {"near": "2026-05-31"}})
    return bd, row


def test_B11_every_watch_row_names_a_table_a_level_a_date_or_a_document():
    bd, _row_ = _rows_for_a_board()
    rows = WA.watch_rows(bd, conventions={"oni_climate": ONI_CONV})
    assert rows
    for w in rows:
        assert w["kind"] in WA.WATCH_KINDS
        named = bool(w.get("dates")) or bool(w.get("call")) or "no release rule" in w["what"] \
            or "next session" in w["what"] or "publisher states" in w["what"]
        assert named, w


def test_B11_a_forward_event_date_receipt_renders_with_BOTH_dates():
    """Kind 5 is the only PIT-safe source of forward policy dates in the design: knowledge is the
    PUBLICATION date, and the row prints both."""
    bd, _r = _rows_for_a_board()
    rows = WA.watch_rows(bd, conventions={"oni_climate": ONI_CONV})
    k5 = [w for w in rows if w["kind"] == "policy_date"]
    assert k5 and k5[0]["dates"] == "2026-11-15" and "2026-08-20" in k5[0]["what"]


def test_a_receipt_published_AFTER_the_as_of_is_never_a_forward_date():
    v = [0.0] * 80 + [0.2, 0.4, 0.6, 0.98]
    row = _row(values=v, conv=ONI_CONV,
               receipts={"n": 1, "newest_date": "2026-12-01", "oldest_date": "2026-12-01",
                         "top": [{"date": "2026-12-01", "event_date": "2027-01-01"}]})
    rows = WA.watch_rows(_board([row]), conventions={"oni_climate": ONI_CONV})
    assert not [w for w in rows if w["kind"] == "policy_date"]


def test_the_lag_window_row_prints_the_band_it_was_counted_from():
    bd, _r = _rows_for_a_board()
    rows = WA.watch_rows(bd, conventions={"oni_climate": ONI_CONV})
    k3 = [w for w in rows if w["kind"] == "lag_window"]
    assert k3 and k3[0]["dates"] == "2026-08-31 to 2026-11-30"
    assert "one to two quarters" in k3[0]["what"]


# ── the cap and the interleave ───────────────────────────────────────────────────────────────────────
def test_the_cap_never_eats_a_KIND_because_the_kinds_are_drawn_round_robin():
    """A straight rank walk would fill an eight-row cap with kind-1 rows on a twelve-row loud set and
    the reader would never meet a lag window at all."""
    v = [0.0] * 80 + [0.2, 0.4, 0.6, 0.98]
    rows = [_row(values=v, conv=ONI_CONV, driver_id=f"d{i}") for i in range(12)]
    bd = _board(rows, windows={r.key: {"near": "2026-05-31"} for r in rows})
    got = WA.watch_rows(bd, conventions={"oni_climate": ONI_CONV}, cap=6)
    assert len(got) == 6
    assert len({w["kind"] for w in got}) >= 3


def test_a_FIRED_row_never_sits_behind_a_DECLINED_one_inside_its_own_kind():
    v = [0.0] * 80 + [0.2, 0.4, 0.6, 0.98]
    good = _row(values=v, conv=ONI_CONV, driver_id="good")
    bad = _row(values=v, conv=ONI_CONV, driver_id="bad", table="silver_noaa_iod")  # uncalendared
    bd = _board([bad, good])
    got = [w for w in WA.watch_rows(bd, conventions={"oni_climate": ONI_CONV}, cap=8)
           if w["kind"] == "next_release"]
    assert got[0]["declined"] is None


def test_an_uncalendared_card_is_a_ROW_THAT_SAYS_SO_rather_than_a_missing_line():
    v = [0.0] * 80 + [0.2, 0.4, 0.6, 0.98]
    row = _row(values=v, conv=ONI_CONV, table="silver_noaa_iod")
    got = [w for w in WA.watch_rows(_board([row]), conventions={"oni_climate": ONI_CONV})
           if w["kind"] == "next_release"]
    assert got and got[0]["declined"] == "no_calendar_rule"
    assert got[0]["what"] == "no release rule is declared for this series"


# ── the leg stamp ────────────────────────────────────────────────────────────────────────────────────
def test_the_watch_leg_stamps_fired_declined_or_not_reached_from_its_own_closed_enum():
    bd, _r = _rows_for_a_board()
    assert WA.watch_leg(bd, [])["outcome"] == "not_reached"
    assert WA.watch_leg(bd, [{"kind": "next_release", "declined": None}])["outcome"] == "fired"
    rec = WA.watch_leg(bd, [{"kind": "next_release", "declined": "no_calendar_rule"}])
    assert rec["outcome"] == "declined" and rec["reason"] == "no_calendar_rule"
    for word in WA.WATCH_KINDS:
        pass
    for reason in B.WATCH_REASONS:
        assert B.check_reason("watch", reason) is None


def test_every_rendered_watch_line_is_letters_ISO_dates_and_nothing_else():
    """Sec 5.1's headline rule. The kind-2 row renders in SB-V's form and carries the ONE figure; every
    other kind's digits are ISO dates."""
    import re
    bd, _r = _rows_for_a_board()
    for w in WA.watch_rows(bd, conventions={"oni_climate": ONI_CONV}):
        if w.get("call"):
            continue
        line = R.sb_watch(w)
        stripped = re.sub(r"\d{4}-\d{2}-\d{2}", "", line)
        assert not any(ch.isdigit() for ch in stripped), line


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# S7b -- THE NON-OBVIOUS WATCH LIST (owner ruling 2026-09-11)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def _nb_board(*, mode="deep", values=None, conv=None, loud=True):
    """A one-row board whose reading, run and convention the caller controls."""
    vals = values if values is not None else [0.1] * 60 + [0.6, 0.9, 1.2, 1.6, 1.9, 2.2]
    r = _row(values=vals, conv=conv if conv is not None else ONI_CONV, loud=loud)
    bd = _board([r], mode=mode)
    st = r.state
    bd.windows[r.key] = {"near": "2010-01-31", "reading": st.level_date,
                         "state_date": st.level_date, "knowledge_date": st.knowledge_date,
                         "analog_dates": ()}
    bd.series[st.key.label()] = st
    return bd, r


# -- the closed vocabulary, the ceilings, and the two caps that are NOT WATCH_RENDER_K ---------------
def test_the_nonobvious_enum_is_closed_and_carries_no_calendar_vocabulary():
    from leviathan.graphrag.state import calendar as CAL
    # THE MAP COVERS THE KINDS AND THE DECLARED VARIANTS AND NOTHING ELSE (review round 3, MAJOR 1):
    # a kind whose claim has more than one true shape carries one phrase per shape, and every one of
    # them is a phrase a reader meets, so every one is graded by this test.
    assert set(WA.NONOBVIOUS_KIND_WORDS) == (set(WA.NONOBVIOUS_KINDS)
                                             | set(WA.NONOBVIOUS_VARIANTS))
    assert not (set(WA.NONOBVIOUS_KINDS) & set(WA.NONOBVIOUS_VARIANTS))
    assert not (set(WA.NONOBVIOUS_KINDS) & set(WA.WATCH_KINDS))
    assert "next_release" not in WA.NONOBVIOUS_KINDS, "a scheduled print is banned as a watch ITEM"
    cal = {str(w).lower() for w in
           list(CAL.KIND_WORDS.values()) + list(CAL.RULE_WORDS.values())}
    for words in WA.NONOBVIOUS_KIND_WORDS.values():
        assert not any(ch.isdigit() for ch in words)
        assert str(words).lower() not in cal
        for banned in ("met", "fires"):
            assert banned not in str(words).lower().split()


def test_the_ceilings_are_3_5_7_and_WATCH_RENDER_K_is_UNTOUCHED():
    """THE TWO CAPS ARE TWO CAPS. ``reasoning_modes``' knob table declares ``render_watch`` 3/6/8 and
    two shipped decks assert ``knobs.render_watch == WATCH_RENDER_K[mode]``; editing that constant
    would change deep and max with every flag OFF, which the 09-10 no-cap law forbids outright."""
    assert WA.WATCH_NONOBVIOUS_K == {"quick": 3, "deep": 5, "max": 7}
    assert WA.WATCH_RENDER_K == {"quick": 3, "deep": 6, "max": 8}
    for mode, want in WA.WATCH_NONOBVIOUS_K.items():
        assert WA.nonobvious_k(mode) == want
        assert WA.render_k(mode, B.board_knobs_of(mode)) == WA.WATCH_RENDER_K[mode]
    assert WA.nonobvious_k("deep", 2) == 2, "an explicit cap wins, as it does for the HEAD producer"


def test_the_deep_max_no_cap_law_holds_RENDER_CAPS_is_not_touched():
    """The 09-10 law is read at ``render.render_caps`` / ``rank_cuts`` scope -- neither carries a
    ``watch`` key -- so the watch lane must not appear in either."""
    for mode in ("quick", "deep", "max"):
        assert "watch" not in R.render_caps(mode)
    assert R.rank_cuts(R.render_caps("deep")) is False
    assert R.rank_cuts(R.render_caps("max")) is False


# -- the admission floor ----------------------------------------------------------------------------
def test_the_floor_admits_nothing_and_the_board_prints_ONE_honest_absence_line():
    """O-1/O-2: the ceiling is a CEILING. A board clearing no clause prints one line, never a padded
    list, and ``watch_leg`` stamps the closed word."""
    bd, _r = _nb_board(values=[0.0] * 60 + [0.01, 0.02, 0.01, 0.0, 0.01, 0.0])
    rows = WA.nonobvious_rows(bd, analogs=(), loud_k=16)
    assert len(rows) == 1 and rows[0]["form"] == "absence"
    assert rows[0]["declined"] == "watch_floor_unmet"
    assert B.check_reason("watch", "watch_floor_unmet") is None
    line = R.sb_absence(rows[0]["label"], rows[0]["reason"])
    assert R.classify(line) == ("SB-X",), line
    assert not any(ch.isdigit() for ch in line)
    rec = WA.watch_leg(bd, rows)
    assert rec["outcome"] == "declined" and rec["reason"] == "watch_floor_unmet"


def test_the_ceiling_is_never_padded_from_a_lower_queue():
    """Fewer admitted candidates than the ceiling return FEWER rows, and the partial fill says so."""
    bd, _r = _nb_board()
    rows = WA.nonobvious_rows(bd, analogs=(), loud_k=16)
    noms = [w for w in rows if w.get("form") != "absence"]
    assert 0 < len(noms) <= WA.nonobvious_k("deep") * WA.NOMINATE_MULTIPLE
    if len([w for w in noms if w.get("slot") == "ceiling"]) < WA.nonobvious_k("deep"):
        assert any(w.get("reason") == "watch_nothing_further" for w in rows)


def test_a_PARTIAL_fill_never_denies_the_rows_printed_above_it():
    """THE FIRST CUT REUSED ``watch_floor_unmet``'s SENTENCE under a list that HAD rows, so a block
    closed "nothing forward on this page clears the bar this list sets" immediately after its own
    nominations. The two cases are two closed words and two sentences."""
    full, part = WA.absence_row(), WA.absence_row(partial=True)
    assert full["reason"] == "watch_floor_unmet" and part["reason"] == "watch_nothing_further"
    assert B.check_reason("watch", part["reason"]) is None
    lines = [R.sb_absence(w["label"], w["reason"]) for w in (full, part)]
    assert lines[0] != lines[1]
    assert "nothing further" in lines[1]
    for line in lines:
        assert R.classify(line) == ("SB-X",), line
        assert not any(ch.isdigit() for ch in line)
    # and the coverage instrument's zero-admission probe keys on the FULL line, never the partial one
    assert lines[0].startswith("BOARD ABSENCE a forward item on this page")


def test_the_floor_clauses_are_five_and_the_tail_clause_never_reads_a_convention():
    """O-4: ``T_TAIL`` is band-free so the fifteen convention-less refs can still rank. A row with NO
    convention at all and a decile reading clears the floor on ``record_tail`` alone."""
    assert len(WA.FLOOR_CLAUSES) == 5
    vals = [float(i) for i in range(60)] + [500.0]
    r = _row(values=vals, conv=None, ref="export", table="silver_psd", driver_id="export_pace_lag")
    floor = WA._floor_of(r)
    assert "record_tail" in floor and "past_a_declared_line" not in floor
    assert WA._tail_fraction(r.state) > 0.8


# -- every term is finite on a board of nulls -------------------------------------------------------
def test_every_rank_term_is_a_number_on_a_row_whose_every_measure_is_None():
    """O-6: a ``None`` inside a sort tuple is a TypeError in the middle of a render."""
    r = B.NodeRow(contract="soybeans_cbot", driver_id="El_Nino", lag_band=parse_lag("1-2 quarters"))
    r.legs["loud"] = True
    cand = {"kind": "tail_reading", "driver_id": "El_Nino", "row": r.key,
            "pattern": WA.AMPLIFIER_LEVELS["neutral"], "paths": {}, "fan": {}, "window": {},
            "tail": 0.0, "run_n": 0,
            "floor": ("record_tail",), "far_words": (), "dedupe": ("x", 0)}
    terms = WA.rank_terms(cand, frozenset())
    assert set(terms) >= {"T_NOVELTY", "T_AMPLIFIER", "T_NONLINEAR", "T_TAIL", "T_RUN",
                          "T_PATHS_DEPTH", "T_PATHS_N", "T_BREADTH", "T_WINDOW"}
    cand["terms"] = terms
    key = WA.rank_key(cand)
    assert all(v is not None for v in key)
    assert sorted([key, key]) == [key, key]
    assert len(WA.RANK_TERMS) == 7 and WA.RANK_TIEBREAK[0] == "T_NOVELTY"
    assert WA._run_of(None) == (0, "")
    assert WA._tail_fraction(None) == 0.0
    assert WA._side_word(None) == "on a side this reading does not show"
    assert WA._metric_words(None) == ""


def test_the_rank_tuple_is_the_09_11_RULINGS_OWN_ORDER_and_novelty_is_the_tiebreak():
    """THE FIRST CUT LED WITH ``T_NOVELTY``, which the ruling names as a property of the MEASUREMENT
    and never as a rank position -- and with the term degenerate it demoted ``T_AMPLIFIER`` behind a
    constant and cost ``past_the_line`` and ``tail_reading`` every ceiling slot on all three
    fixtures."""
    assert tuple(WA.RANK_TERMS) == ("T_AMPLIFIER", "T_NONLINEAR", "T_TAIL", "T_RUN", "T_PATHS",
                                    "T_BREADTH", "T_WINDOW")

    def k(**terms):
        # THE BASE IS THE NEUTRAL AMPLIFIER LEVEL (review round 2, MAJOR 3): the term's domain is the
        # three levels the ruling names, and 3 is no longer one of them.
        base = {"T_AMPLIFIER": WA.AMPLIFIER_LEVELS["neutral"], "T_NONLINEAR": 3, "T_TAIL": 0.0,
                "T_RUN": 0, "T_PATHS_DEPTH": 0,
                "T_PATHS_N": 0, "T_BREADTH": 0, "T_WINDOW": WA._NO_WINDOW, "T_NOVELTY": 0}
        base.update(terms)
        return WA.rank_key({"terms": base, "driver_id": "", "kind": ""})

    # T_AMPLIFIER leads: a met pattern with an amplifier line beats EVERY other term, novelty included
    assert k(T_AMPLIFIER=0, T_NOVELTY=0) < k(T_AMPLIFIER=1, T_NOVELTY=99)
    # T_NONLINEAR is INVERTED and sits second: past-the-line outranks approaching, at equal amplifier
    assert k(T_NONLINEAR=0) < k(T_NONLINEAR=2) < k(T_NONLINEAR=3)
    # T_WINDOW is LAST of the ruling's terms, and novelty sits AFTER it -- never before
    assert k(T_WINDOW="2026-01-01", T_NOVELTY=0) < k(T_WINDOW="2026-02-01", T_NOVELTY=99)
    # ... and it still breaks a tie the ruling's terms cannot
    assert k(T_NOVELTY=9) < k(T_NOVELTY=1)


def test_an_empty_board_never_raises_and_stamps_not_reached():
    """O-5: state/'s law #1. An empty loud set produces no candidate and the leg says so."""
    bd = B.Board(asof=ASOF, mode="deep", knobs=B.board_knobs_of("deep"),
                 anchors=(B.Anchor(contract="soybeans_cbot", source="named"),))
    assert WA.nonobvious_candidates(bd, analogs=()) == []
    rows = WA.nonobvious_rows(bd, analogs=(), loud_k=16)
    assert len(rows) == 1 and rows[0]["declined"] == "watch_floor_unmet"
    assert WA.watch_leg(bd, [])["outcome"] == "not_reached"


# -- the dedupe: series key AND declared offset -----------------------------------------------------
def test_the_dedupe_key_is_the_SERIES_KEY_AND_THE_DECLARED_OFFSET():
    """R10: two of El Nino's 34 boards read a six-month-offset series. On the label alone those two are
    the same reading, which they are not; on the driver id alone El Nino and La Nina are two, which
    they are not."""
    a = _row(values=[0.1] * 60 + [2.2], conv=ONI_CONV, driver_id="El_Nino")
    b = _row(values=[0.1] * 60 + [2.2], conv=ONI_CONV, driver_id="La_Nina")
    assert WA._dedupe_key(a) == WA._dedupe_key(b), "one ONI print under two names is ONE reading"
    c = _row(values=[0.1] * 60 + [2.2], conv=ONI_CONV, driver_id="El_Nino_lagged")
    c.state.offset_months = 6
    assert WA._dedupe_key(c) != WA._dedupe_key(a), "a declared offset is a DIFFERENT reading"
    d = B.NodeRow(contract="soybeans_cbot", driver_id="text_only")
    assert WA._dedupe_key(d) == ("#text_only", 0), "a row with no series groups alone"


# -- the bans, enforced at NOMINATION and never at render --------------------------------------------
def test_a_context_only_row_is_never_an_anchor_unless_it_is_the_SUBJECT():
    """O-11 / L-3. The prototype ranked "cot mm positioning -> ICE arabica" THIRD on every soybean
    seat. Amendment 1's exception is ``NodeRow.subject`` and it is the only one."""
    r = _row(values=[float(i) for i in range(60)] + [500.0], conv=PCT_CONV,
             ref="cot_mm_positioning", table="silver_cot", driver_id="cot_mm_positioning")
    r.context_only = True
    bd = _board([r])
    bd.windows[r.key] = {"near": r.state.level_date, "reading": r.state.level_date,
                         "state_date": r.state.level_date, "knowledge_date": None, "analog_dates": ()}
    assert WA.nonobvious_candidates(bd, analogs=()) == [], "refused as an anchor"
    r.subject = True
    assert WA.nonobvious_candidates(bd, analogs=()), "and admitted when the question names it"


def test_no_candidate_is_ever_a_release_calendar_item_and_the_footnote_is_ONE_line():
    """L-1/L-2/P-2: the ban is on the KIND, so the eleven-of-thirty DECLINED release forms are covered
    by construction. The footnote spends no ceiling slot and carries no digit but its ISO dates."""
    import re

    from leviathan.graphrag.state import calendar as CAL
    bd, _r = _nb_board()
    rows = WA.nonobvious_rows(bd, analogs=(), loud_k=16)
    cal_words = set(CAL.RULE_WORDS.values()) | set(CAL.KIND_WORDS.values())
    for w in rows:
        assert w["kind"] not in WA.WATCH_KINDS
        assert not any(c in (w.get("what") or "") for c in cal_words)
    foot = [w for w in rows if w.get("reason") == "release_dates_only"]
    assert len(foot) <= 1
    for w in foot:
        assert w["declined"] == "release_dates_only"
        assert B.check_reason("watch", "release_dates_only") is None
        line = R.sb_absence(w["label"], w["reason"])
        assert R.classify(line) == ("SB-X",), line
        assert not any(ch.isdigit() for ch in re.sub(r"\d{4}-\d{2}-\d{2}", "", line))


def test_a_closed_window_is_never_nominated_and_the_anchor_is_the_READINGS_own_date():
    """R6, and it is the ASSERTION the third ``bd.windows`` key buys: counted from a run start in 2010
    the window closed in 2011; counted from the reading's own date it is open."""
    from leviathan.graphrag.state.walk import projection_window
    bd, r = _nb_board()
    st = r.state
    w_reading = WA._reading_window(bd, r)
    assert w_reading["anchor"] == st.level_date and w_reading["fallback"] == ""
    # THE TWO ANCHORS ARE TWO WINDOWS, and this is the whole of R6. The fixture's run starts in 2010
    # and its reading is five years later; SB-J's window opens from the run start, the watch row's from
    # the reading, and the watch row's is the LATER one -- which is how a 1997 run stopped rendering a
    # 1998 window for a 2026 reading on 10 of the prototype's 60 rows.
    w_run = projection_window(bd.windows[r.key]["near"], r.lag_band)
    assert w_reading["opens"] > w_run["opens"]
    assert w_reading["closes"] > w_run["closes"]
    # BOTH are closed at this as-of on this historic fixture, and a closed window is NEVER nominated:
    # every admitted candidate on this board carries an empty date tail rather than a stale one.
    assert not WA._window_open(w_reading, ASOF) and not WA._window_open(w_run, ASOF)
    for c in WA.nonobvious_candidates(bd, analogs=()):
        assert c["dates"] == "", c["dates"]
    # a window whose reading IS current is open, through the same predicate
    assert WA._window_open({"opens": "2026-08-31", "closes": "2027-02-28", "declined": None}, ASOF)
    bd.windows[r.key].pop("reading")
    w_fallback = WA._reading_window(bd, r)
    assert w_fallback["fallback"] == "level_date", "the declared fallback names itself"
    assert w_fallback["anchor"] == st.level_date
    stale = {"opens": "1998-01-31", "closes": "1998-06-30", "declined": None}
    assert not WA._window_open(stale, ASOF)


# -- the sentence: what the number IS, and which side ------------------------------------------------
def test_the_sentence_says_what_the_number_IS_and_never_a_bare_node_name():
    """R13: the prototype printed "Brazil export tax" over a PSD export VOLUME of 118000000 MMT."""
    r = _row(values=[float(i) for i in range(60)] + [500.0], conv=None, ref="export",
             table="silver_psd", driver_id="Brazil_export_tax")
    r.state.metric = "export_1000mt"
    r.state.narrate_unit = "1000 MT"
    words = WA._metric_words(r.state)
    assert "export" in words
    assert not any(ch.isdigit() for ch in words), "SB-W is a letters-only class"
    r.state.narrate_unit = "MMT"
    r.state.metric = "export"
    assert WA._metric_words(r.state) == "export in MMT"


def test_an_UNSERVED_metric_says_nothing_and_never_a_medallion_CARD_name():
    """THE CARD IS NOT WHAT THE NUMBER IS. The first cut fell back to ``R.table_words(st.table)`` and
    the four-board replay rendered "the figure is psd", "the figure is production livestock" and "the
    figure is gold weather z" -- a storage-tier name on a cocoa page. Saying nothing is a correction,
    not a deletion: every other clause stands and the row still cites its own SB-1 line."""
    r = _row(values=[float(i) for i in range(60)] + [500.0], conv=None, ref="export",
             table="gold_weather_z", driver_id="drought")
    r.state.metric = ""
    assert WA._metric_words(r.state) == ""
    assert R.table_words("gold_weather_z"), "the card name EXISTS -- it is simply not the metric"
    bd = _board([r])
    bd.windows[r.key] = {"near": r.state.level_date, "reading": r.state.level_date,
                         "state_date": r.state.level_date, "knowledge_date": None, "analog_dates": ()}
    for c in WA.nonobvious_candidates(bd, analogs=()):
        assert "the figure is" not in c["what"], c["what"]
        assert "gold weather z" not in c["what"] and " psd" not in c["what"]


def test_the_sentence_SAYS_THE_SIDE_on_a_folded_abs_band():
    """R15: ``_crossed`` folds abs/z bands to |v|, so "0.9 sigma under the severe line" does not say
    which tail. The side comes from the SIGNED reading."""
    lo = _row(values=[0.0] * 60 + [-2.4], conv=ONI_CONV)
    hi = _row(values=[0.0] * 60 + [2.4], conv=ONI_CONV)
    assert WA._side_word(lo.state, kind="abs_bands") == "on the low side"
    assert WA._side_word(hi.state, kind="abs_bands") == "on the high side"


# -- novelty is computed on the sentence, never asserted per kind -------------------------------------
def test_novelty_is_computed_on_the_RENDERED_SENTENCE_and_its_figures():
    """O-14 and the review finding it failed. The first cut read ``driver_id``, ``kind`` and
    ``far_words`` and nothing else, which made it a per-kind constant by construction: 0 of 94
    candidates across the three acceptance fixtures ever scored its top value."""
    vocab = frozenset({"el", "nino", "cbot", "soybeans", "elevated"})
    same = {"label": "El Nino on CBOT soybeans", "dates": "",
            "what": "the reading is past the line the desk convention calls elevated."}
    adds = {"label": "El Nino on CBOT soybeans", "dates": "",
            "what": ("the reading is past the line the desk convention calls elevated, and the "
                     "nearest of them is ICE robusta coffee.")}
    other = {"label": "flash drought on CBOT soybeans", "dates": "",
             "what": "the reading is past the line the desk convention calls elevated."}
    # the sentence that says only what the page already says scores ZERO
    assert WA.novelty(same, vocab) == 0
    # the same sentence naming another market scores MORE, and it is the market it scores for
    assert WA.novelty(adds, vocab) == 3            # ice + robusta + coffee
    # and a subject the page did not lead with scores for the subject
    assert WA.novelty(other, vocab) == 2           # flash + drought
    # A FIGURE IS A TOKEN. "and its figures" is literal: a level the page already prints is not new.
    assert WA.novelty({"label": "x", "what": "the figure is 1.42", "dates": ""},
                      vocab | {"x"}) == 1
    assert WA.novelty({"label": "x", "what": "the figure is 1.42", "dates": ""},
                      vocab | {"x", "1.42"}) == 0


def test_novelty_can_NEVER_be_a_per_kind_constant():
    """THE REVIEW'S OWN FALSIFIER, as a deck case. Every fixed word of the seven sentences is derived
    into :data:`watch._GRAMMAR` from the templates themselves, so a kind's own vocabulary cannot hand
    it a free point -- only the words the BOARD put in the sentence count, and changing the subject
    alone must change the number."""
    assert WA._GRAMMAR and "decile" in WA._GRAMMAR and "hops" in WA._GRAMMAR
    for kind in WA.NONOBVIOUS_KINDS:
        body = WA.NONOBVIOUS_BODIES[kind]
        bare = WA._SLOT_RX.sub(" ", body)
        cand = {"label": "", "dates": "", "what": WA.NONOBVIOUS_CLAUSES["falsifier"].format(
            body=bare, falsifier=WA.NONOBVIOUS_FALSIFIERS[kind])}
        assert WA.novelty(cand, frozenset()) == 0, (kind, WA._content_tokens(cand["what"])
                                                    - WA._GRAMMAR)
    # the SAME kind, two subjects, two numbers -- which a per-kind assertion cannot produce
    a = {"label": "El Nino on CBOT soybeans", "what": "", "dates": ""}
    b = {"label": "Argentina export registration on CBOT soybeans", "what": "", "dates": ""}
    assert WA.novelty(a, frozenset()) != WA.novelty(b, frozenset())


# -- determinism --------------------------------------------------------------------------------------
def test_the_producer_is_pure_and_two_runs_print_the_same_page():
    """A-5: a set iteration or a dict order leaking into the tuple makes one board print two pages."""
    bd, _r = _nb_board()
    a = WA.nonobvious_rows(bd, analogs=(), loud_k=16)
    b = WA.nonobvious_rows(bd, analogs=(), loud_k=16)
    assert ([R.sb_watch(w) if w.get("form") != "absence" else w["label"] for w in a]
            == [R.sb_watch(w) if w.get("form") != "absence" else w["label"] for w in b])


# -- the base rate ------------------------------------------------------------------------------------
def test_the_base_rate_is_two_field_reads_and_declines_BY_NAME():
    """O-7/P-4: the census's ``candidates_by_sigma_band`` re-runs ``likeness`` once per history date per
    seed per band; both integers this needs are already on the stanza and on the row."""
    from leviathan.graphrag.state import analogs as A
    r = _row(values=[0.1] * 60 + [2.2], conv=ONI_CONV)
    r.state.coverage = {"n_obs": 131}
    assert WA.like_state_base_rate({"n_candidates_head": 7}, r) == {"n": 7, "m": 131,
                                                                   "declined": None}
    assert WA.like_state_base_rate({}, r)["declined"] == "no_candidate_count"
    r2 = _row(values=[0.1] * 60 + [2.2], conv=ONI_CONV)
    r2.state.coverage = {}
    assert (WA.like_state_base_rate({"n_candidates_head": 7}, r2)["declined"]
            == "no_observation_count")
    r3 = _row(values=[0.1] * 60 + [2.2], conv=ONI_CONV)
    r3.state.coverage = {"n_obs": 3}
    assert (WA.like_state_base_rate({"n_candidates_head": 7}, r3)["declined"]
            == "candidates_exceed_observations")
    for word in WA.BASE_RATE_DECLINES:
        assert word.isascii() and not any(ch.isdigit() for ch in word)
    # IT LIVES IN THE WATCH LANE'S OWN FILE. `state/analogs.py` carries a co-tenant lane's in-flight
    # work and is NOT this lane's to commit; a producer of this lane's added there could only ship
    # inside `git add state/analogs.py`, which ships that work too.
    assert not hasattr(A, "like_state_base_rate")
    assert not hasattr(A, "BASE_RATE_DECLINES")


def test_R2_the_base_rate_reads_the_RARITY_count_and_NEVER_the_relaxed_pool():
    """**THE WOKEN WATCH ROW** (R3a review round 2, MAJOR 4). Kind 7 fires only on a FIRED analog, and
    the analog declined on five of five 2026-09-16 smoke turns -- so this sentence has never reached a
    reader, and the R3a relaxation is exactly the change that lights it. Had it read the field it used
    to, its FIRST live appearance would have been "three hundred and forty-six like states in four
    hundred and forty observations": a seventy-nine per cent recurrence rate offered to a PM about a
    state the record has actually been in eighteen times.

    THE MEANING THIS READER CONSUMES DID NOT MOVE -- only the field name did. ``n_candidates`` is now the
    pool the selector RANKS (a coverage statement); ``n_candidates_head`` is the count the SHIPPED rule
    admitted (the rarity one), and ``analogs.select_analogs`` computes it as a COUNT that filters
    nothing. The read is FAIL-CLOSED: a stanza carrying only the relaxed pool declines by name rather
    than quietly printing it."""
    r = _row(values=[0.1] * 60 + [2.2], conv=ONI_CONV)
    r.state.coverage = {"n_obs": 440}
    relaxed = {"n_candidates": 346, "n_candidates_raw": 358, "n_candidates_pit": 349,
               "n_candidates_head": 18, "date": "1997-03-31"}
    got = WA.like_state_base_rate(relaxed, r)
    assert got == {"n": 18, "m": 440, "declined": None}
    assert got["n"] / got["m"] < 0.05, "a rarity, not the 79% the ranked pool would have printed"
    # FAIL-CLOSED: the relaxed pool alone is NOT a numerator, and there is no silent fallback.
    no_head = {k: v for k, v in relaxed.items() if k != "n_candidates_head"}
    assert WA.like_state_base_rate(no_head, r)["declined"] == "no_candidate_count"
    # AND A BASE RATE OF ZERO IS NOT A RECURRENCE: the floor clause keeps its HEAD threshold semantics.
    zero = WA.like_state_base_rate({**relaxed, "n_candidates_head": 0}, r)
    assert zero == {"n": 0, "m": 440, "declined": None}
    assert "base_rated_episode" not in WA._floor_of(r, pattern_rows=(), path_n=0, base_rate=zero)
    assert "base_rated_episode" in WA._floor_of(r, pattern_rows=(), path_n=0, base_rate=got)

# -- the 2N nomination and the writer licence ---------------------------------------------------------
def test_every_nomination_carries_a_mechanism_a_backing_row_and_a_falsifier():
    """R16: the board hands the writer 2N candidates and the writer selects."""
    bd, _r = _nb_board(mode="max")
    rows = [w for w in WA.nonobvious_rows(bd, analogs=(), loud_k=16) if w.get("form") != "absence"]
    assert rows
    assert len(rows) <= WA.nonobvious_k("max") * WA.NOMINATE_MULTIPLE
    for w in rows:
        assert w["mechanism"] and w["falsifier"]
        assert "this reads wrong if" in w["what"]
        assert w["row"] and w["floor"] and w["terms"]
        assert w["slot"] in ("ceiling", "nomination")


def test_the_selection_licence_is_a_constant_this_module_exports_and_it_is_prompt_clean():
    """DR-9 / the seam protocol: ``state/narration.py`` owns the mandate and is the REGISTER lane's
    file, so the watch lane exports its clause and the register lane lands the one line."""
    from leviathan.graphrag import register as reg
    c = WA.WATCH_SELECTION_CLAUSE
    assert c.isascii() and len(c) > 200
    assert reg.register_leaks(c) == []
    assert reg.internal_leaks(c) == []
    assert reg.count_flow_words(c) == 0 and reg.count_valuation_words(c) == 0


# -- the rendered row rides SB-W, and NO new row class ships ------------------------------------------
def test_every_nomination_renders_as_SB_W_with_no_digit_but_ISO_dates_and_its_handle():
    import re
    bd, _r = _nb_board(mode="max")
    for w in WA.nonobvious_rows(bd, analogs=(), loud_k=16):
        if w.get("form") == "absence":
            continue
        line = R.sb_watch({**w, "backing_handle": 7})
        assert R.classify(line) == ("SB-W",), (R.classify(line), line)
        assert "[N7]" in line
        bare = re.sub(r"\[[NE]\d+\]", "", re.sub(r"\d{4}-\d{2}-\d{2}", "", line))
        bare = re.sub(r"(?<=[A-Za-z])\d+", "", bare)
        assert not any(ch.isdigit() for ch in bare), line


def test_the_overlay_never_reaches_load_conventions_and_the_base_always_wins():
    """A-3 / P-b: ``state_conventions.yaml``'s ``conventions:`` block feeds ``walk._convention_hit``, a
    TERM of ``rank_key``, so a curation there changes ``bd.order`` on every board-on turn with every
    flag off."""
    from leviathan.graphrag.state.lint import load_conventions
    doc = load_conventions()
    base, overlay = set(doc.get("conventions") or {}), set(doc.get("watch_overlay") or {})
    assert overlay and not (base & overlay), "an overlay entry shadowing a live one is dead config"
    assert set(WA._conventions()) == base, "`_conventions()` is the BASE and only the base"
    assert set(WA.watch_overlay()) == overlay
    for ref, row in (doc.get("watch_overlay") or {}).items():
        assert row["kind"] == "percentile_bands", ref
        assert row["bands"] == [10, 90] and row["labels"] == ["low", "high"], ref
        assert row.get("verified") is None, "declared, not verified -- owner decision 5"


# -- the DESK REGISTER: the block is what the writer copies -------------------------------------------
def test_every_nomination_sentence_is_DESK_REGISTER_CLEAN():
    """THE WRITER COPIES THE BLOCK'S VOCABULARY -- measured 2026-09-11, 195 internal-vocabulary hits
    over nine banked real-seat answers. The first cut of this producer ADDED 41 / 34 / 49 more on the
    three acceptance fixtures ("sit among this board's loudest rows", "the graph places three declared
    upstream paths") while the sibling register lane was landing a lint whose declared target is zero
    and whose remedy is a paid rewrite call. The sentences are written in register HERE, where it is
    free."""
    from leviathan.graphrag import register as reg
    graded = (list(WA.NONOBVIOUS_KIND_WORDS.values()) + list(WA.NONOBVIOUS_BODIES.values())
              + list(WA.NONOBVIOUS_CLAUSES.values()) + list(WA.NONOBVIOUS_MECHANISMS.values())
              + list(WA.NONOBVIOUS_FALSIFIERS.values()) + list(WA._FIXED_PHRASES)
              + [WA.WATCH_SELECTION_CLAUSE])
    for text in graded:
        assert reg.desk_register_hits(text) == [], (reg.desk_register_hits(text), text[:90])
        assert str(text).isascii(), text
    bd, _r = _nb_board(mode="max")
    for w in WA.nonobvious_rows(bd, analogs=(), loud_k=16):
        line = R.sb_watch(w) if w.get("form") != "absence" else ""
        if not line:
            continue
        assert reg.desk_register_hits(line) == [], (reg.desk_register_hits(line), line[:120])


def test_the_seven_kinds_declare_one_mechanism_and_one_falsifier_EACH():
    """One place each, so a kind cannot ship two falsifiers from two call sites -- and so ``_GRAMMAR``
    can derive their words with the bodies'."""
    every = set(WA.NONOBVIOUS_KINDS) | set(WA.NONOBVIOUS_VARIANTS)
    for mapping in (WA.NONOBVIOUS_BODIES, WA.NONOBVIOUS_MECHANISMS, WA.NONOBVIOUS_FALSIFIERS):
        assert set(mapping) == every
    assert len(set(WA.NONOBVIOUS_FALSIFIERS.values())) == len(every)


# -- the footnote is a CALENDAR, and a calendar is chronological ---------------------------------------
def test_the_release_footnote_is_CHRONOLOGICAL_and_says_how_many_it_did_not_print():
    """The first cut printed the dates in LOUD ORDER -- "2026-10-01, 2026-10-05, 2026-09-10, ..." --
    which is a rank the reader cannot see, leaking through a line that reads as a diary; and it cut at
    six with no note, two SB-X lines from a truncation clause that already reads "and n further"."""
    import re
    rows = [_row(values=[0.1] * 60 + [2.2], conv=ONI_CONV, driver_id=f"d{i}",
                 table=t, ref="oni_climate")
            for i, t in enumerate(("silver_noaa_oni", "silver_usda_wasde", "silver_usda_esr",
                                   "silver_mpob", "silver_conab", "silver_usda_nass",
                                   "silver_usda_psd", "silver_abares"))]
    bd = _board(rows)
    foot = WA.release_footnote(bd)
    if foot is None:
        pytest.skip("no calendar rule fires on this fixture's cards")
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", foot["label"])
    assert dates == sorted(dates), foot["label"]
    assert len(dates) <= 6
    if len(dates) == 6:
        # the "and n further" clause is words, never a digit -- SB-X carries ISO dates and nothing else
        bare = re.sub(r"\d{4}-\d{2}-\d{2}", "", foot["label"])
        assert not any(ch.isdigit() for ch in bare), foot["label"]
    assert foot["reason"] == "release_dates_only"


# -- a reach needs more than one market, and a window says whether it has opened ------------------------
def test_a_spillover_needs_TWO_markets_before_it_claims_reach():
    """At ``n >= 1`` a SINGLE far market rendered "a move a desk has to price on markets this page is
    not about" -- measured on the four-board replay, corn's `ethanol demand` took ceiling slot one on a
    fan of one. Reach needs more than one market for the same reason the floor's upstream clause needs
    more than one path."""
    r = _row(values=[0.1] * 60 + [2.2], conv=ONI_CONV)
    bd = _board([r])
    bd.windows[r.key] = {"near": r.state.level_date, "reading": r.state.level_date,
                         "state_date": r.state.level_date, "knowledge_date": None, "analog_dates": ()}
    one = {"contract": r.contract, "driver_id": r.driver_id,
           "far": [{"contract": "malaysian_crude_palm_oil_cme", "sign": "+", "lag_band": r.lag_band,
                    "confidence": "high"}]}
    bd.fan = [one]
    assert not [c for c in WA.nonobvious_candidates(bd, analogs=())
                if c["kind"] == "spillover_reach"]
    two = dict(one)
    two["far"] = list(one["far"]) + [{"contract": "ice_cocoa", "sign": "+",
                                      "lag_band": r.lag_band, "confidence": "low"}]
    bd.fan = [two]
    got = [c for c in WA.nonobvious_candidates(bd, analogs=()) if c["kind"] == "spillover_reach"]
    assert got and "other markets" in got[0]["what"]


def test_the_window_clause_says_whether_it_has_OPENED_and_is_silent_with_no_window():
    """A lag band declared six months out from a CURRENT reading legitimately places its window ahead
    -- b40's ceiling row six printed "2027-02-28 to 2027-08-31" at a 2026-09-07 as-of under words that
    read as a window running now. And a row with NO window at all (a recurrence, whose date tail is a
    past like state) must print no window sentence: keyed on the date alone it wrote "the declared lag
    window ... opens and does not close -- 2024-12-31"."""
    ahead = {"opens": "2027-02-28", "closes": "2027-08-31"}
    now = {"opens": "2026-08-31", "closes": "2026-12-31"}
    assert "opens ahead" in WA._window_clause(ahead, "2027-02-28 to 2027-08-31", ASOF)
    assert "has already opened" in WA._window_clause(now, "2026-08-31 to 2026-12-31", ASOF)
    assert WA._window_clause({}, "2024-12-31", ASOF) == ""
    assert WA._window_clause(now, "", ASOF) == ""


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# S7b REVIEW ROUND 2 (2026-09-11) -- the three majors and the cheap minors
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def _decile_row(ref, *, table="silver_psd", driver_id="export_pace", contract="soybeans_cbot",
                low=False):
    """A loud row whose reading sits in its own record's top (or bottom) decile, with NO convention."""
    vals = ([float(i) for i in range(60)] + [-500.0]) if low else \
           ([float(i) for i in range(60)] + [500.0])
    return _row(values=vals, conv=None, ref=ref, table=table, contract=contract,
                driver_id=driver_id)


def _one_row_board(row, mode="deep"):
    bd = _board([row], mode=mode)
    st = row.state
    bd.windows[row.key] = {"near": st.level_date, "reading": st.level_date,
                           "state_date": st.level_date, "knowledge_date": st.knowledge_date,
                           "analog_dates": ()}
    bd.series[st.key.label()] = st
    return bd


# -- MAJOR 1: the tail sentence may not assert a line fact it has not read ----------------------------
def test_the_tail_sentence_NAMES_the_line_it_crossed_and_never_denies_a_declared_one():
    """MAJOR 1, and it is a CORRECTION rather than a strike. The body ended unconditionally "no desk
    line is declared for this series" on a kind that fires whenever ``record_tail`` is in the floor and
    ``past_a_declared_line`` is not -- which includes every one of the fifteen ``watch_overlay`` refs,
    because every overlay band is [10, 90] and ``TAIL_DECILE`` is 10.0, so clearing the floor IS
    crossing the overlay's own line. MEASURED over the 144 banked census seats: 397 of 706 decile-loud
    rows rendered the false clause (311 overlay-only, 86 base-convention rows failing the "deeper"
    half), and 8 of 20 ceiling rows on the four-board deep replay."""
    ov = WA.watch_overlay()
    assert "export" in ov, "the overlay this lane curated is what makes the clause false"
    r = _decile_row("export")
    bd = _one_row_board(r)
    cands = WA.nonobvious_candidates(bd, analogs=(), overlay=ov)
    tails = [c for c in cands if c["kind"] == "tail_reading"]
    assert tails, "a decile reading on a convention-less ref is the tail kind"
    what = tails[0]["what"]
    assert "no desk line is declared" not in what, what
    # AND THE BOOK IS NAMED (review round 3). This ref's line comes from `watch_overlay`, which is this
    # lane's own curation: calling it "the desk convention" showed the reader a corroborating desk fact
    # that was this producer's own book, and one whose [10, 90] band against a TAIL_DECILE of 10.0 says
    # by arithmetic exactly what the tail already said. 180 of the 196 past-the-line tail sentences on
    # the 108-seat replay were in that position.
    assert "this list's own watch book" in what, what
    assert "the desk convention calls" not in what, what
    assert "one measurement said twice" in what, "the tautology is disclosed, not hidden"
    # the FACT itself, read off the row rather than off the kind, and it now carries its BOOK
    merged = {**WA._conventions(), **ov}
    overlay_only = frozenset(k for k in ov if k not in WA._conventions())
    fact = WA._declared_line(r.state, merged, overlay_refs=overlay_only)
    assert fact == {"declared": True, "label": "high", "crossed": True, "source": "overlay"}
    # a line from the SERVED book keeps the desk sentence, unchanged
    served = WA._declared_line(r.state, merged)
    assert served["source"] == "book" and served["crossed"] is True
    assert "the desk convention calls high" in WA._tail_line_clause(served)


def test_the_tail_sentence_still_says_NO_LINE_where_no_book_declares_one():
    """The clause is not deleted -- it is CHOSEN. A ref neither ``conventions:`` nor ``watch_overlay:``
    carries has no line, and the record's own tail really is the whole fact."""
    ref = "a_ref_no_book_declares"
    assert ref not in WA._conventions() and ref not in WA.watch_overlay()
    r = _decile_row(ref, table="silver_psd", driver_id="mystery_driver")
    cands = WA.nonobvious_candidates(_one_row_board(r), analogs=(), overlay=WA.watch_overlay())
    tails = [c for c in cands if c["kind"] == "tail_reading"]
    assert tails and "no desk line is declared for this series at all" in tails[0]["what"]
    assert WA._declared_line(r.state, WA._conventions())["declared"] is False


def test_a_DECLARED_line_this_page_cannot_place_says_so_rather_than_either_thing():
    """THE THIRD STATE IS NOT A BUG. An ``abs_bands`` line needs the raw level; a board holding a
    percentile and no level knows a line is declared and cannot say which side of it the reading sits
    on. The replay meets exactly this (run #5 banks no level on 320 seats)."""
    r = _decile_row("oni_climate", table="silver_noaa_oni", driver_id="El_Nino")
    assert WA._conventions()["oni_climate"]["kind"] == "abs_bands"
    r.state.level = None
    fact = WA._declared_line(r.state, WA._conventions())
    assert fact["declared"] is True and fact["crossed"] is None and fact["label"] is None
    clause = WA._tail_line_clause(fact)
    assert "cannot place this reading against it" in clause
    assert "no desk line is declared" not in clause


def test_ONE_block_never_names_a_line_and_denies_it_on_the_SAME_overlay_family():
    """THE VERIFIER'S OWN CONTRADICTION PROBE (``scratchpad/s7b_verify/vcontra.py``) as a deck pin: two
    rows of ONE overlay family on one board -- a decile reading that clears the line and a mid-record
    reading -- used to print "no desk line is declared for this series" and "the line the desk
    convention calls high" under one heading."""
    hi = _decile_row("export", driver_id="export_pace")
    mid = _row(values=[float(i) for i in range(60)] + [37.0], conv=None, ref="import",
               table="silver_psd", driver_id="import_pace")
    bd = _board([hi, mid], mode="deep")
    for r in (hi, mid):
        st = r.state
        bd.windows[r.key] = {"near": st.level_date, "reading": st.level_date,
                             "state_date": st.level_date, "knowledge_date": st.knowledge_date,
                             "analog_dates": ()}
        bd.series[st.key.label()] = st
    cands = WA.nonobvious_candidates(bd, analogs=(), overlay=WA.watch_overlay())
    denied = [c for c in cands if "no desk line is declared" in c["what"]]
    named = [c for c in cands if ("the desk convention calls" in c["what"]
                                  or "this list's own watch book" in c["what"])]
    assert not (denied and named), [c["what"][:90] for c in denied + named]


# -- MAJOR 2: the tier ceiling reaches the writer -----------------------------------------------------
def test_the_ceiling_is_VISIBLE_on_every_drawn_row_and_the_licence_binds_the_writer_to_it():
    """MAJOR 2. ``nonobvious_k`` sized the draw and ``_draw`` stamped the pass, and NEITHER reached the
    writer: one "- WATCH ..." shape for both passes and a licence naming no number while illustrating
    with "four ... beat five" -- at Scan, whose ceiling is three. Measured at 6 / 10 / 12-14
    indistinguishable lines against HEAD's 3 / 6 / 8."""
    import re
    bd, _r = _nb_board(mode="max")
    rows = [w for w in WA.nonobvious_rows(bd, analogs=(), loud_k=16) if w.get("form") != "absence"]
    assert rows
    core = [w for w in rows if w["slot"] == "ceiling"]
    alts = [w for w in rows if w["slot"] == "nomination"]
    for group, word in ((core, "core item"), (alts, "alternate")):
        for i, w in enumerate(group, 1):
            assert w["slot_index"] == i and w["slot_size"] == len(group)
            assert w["ceiling"] == WA.nonobvious_k("max")
            line = R.sb_watch(w)
            assert f"({word} {R.words_for_int(i)} of {R.words_for_int(len(group))})" in line, line
            assert R.classify(line) == ("SB-W",), line
    # the mark is WORDS: a letters-only class may not carry "one of five" as digits
    for w in rows:
        bare = re.sub(r"\[[NE]\d+\]", "", re.sub(r"\d{4}-\d{2}-\d{2}", "", R.sb_watch(w)))
        assert not any(ch.isdigit() for ch in re.sub(r"(?<=[A-Za-z])\d+", "", bare))
    # HEAD's five kinds carry no slot and render byte for byte
    for w in WA.watch_rows(bd, analogs=(), loud_k=16):
        assert "slot" not in w and "core item" not in R.sb_watch(w)


def test_the_selection_licence_names_the_ceiling_and_the_per_tier_form_names_the_TIERS_OWN():
    from leviathan.graphrag import register as reg
    c = WA.WATCH_SELECTION_CLAUSE
    assert "core item" in c and "alternate" in c
    for n_words in ("three", "five", "seven"):
        assert n_words in c, n_words
    assert "Four backed items" not in c, "the illustration that suggested four or five at Scan"
    for mode, n in WA.WATCH_NONOBVIOUS_K.items():
        tier = WA.selection_clause(mode)
        assert f"at most {R.words_for_int(n)} items" in tier, (mode, tier)
        assert tier.isascii() and reg.register_leaks(tier) == []
        assert reg.desk_register_hits(tier) == []
    assert WA.selection_clause("deep", 2) != WA.selection_clause("deep")


# -- MAJOR 3: T_AMPLIFIER carries exactly the three levels the ruling names ---------------------------
def test_T_AMPLIFIER_has_THREE_levels_and_an_UNMET_pattern_outranks_nothing():
    """MAJOR 3, and the orchestrator's recorded decision. ``_pattern_facts`` returned 3 for a row in NO
    pattern, so -- on the LEADING term of an ascending lexicographic tuple -- membership of an UNMET
    pattern outranked past-the-line, the tail, the run and path depth. Folding the no-pattern value
    onto the short-pattern value changed the top five on 2 of the 4 deep replay boards."""
    assert WA.AMPLIFIER_LEVELS == {"met_with_amplifier": 0, "met": 1, "neutral": 2}
    assert set(WA.AMPLIFIER_LEVELS.values()) == {0, 1, 2}
    r = B.NodeRow(contract="soybeans_cbot", driver_id="El_Nino", lag_band=parse_lag("1-2 quarters"))
    none_at_all = WA._pattern_facts(None, r, ())
    # `matched` AND `n_matched` AGREE HERE (review round 2, MAJOR 5): the threshold test counts the
    # NAMES, through `render.pattern_count`, and no longer the scalar beside them -- so a fixture whose
    # two halves disagreed (one name, `n_matched: 3`) was grading a shape `walk` never emits.
    _three = ("El_Nino", "filler_1", "filler_2")
    short = WA._pattern_facts(None, r, [{"contract": "soybeans_cbot", "matched": ("El_Nino",),
                                         "n_matched": 1, "threshold": 3, "interactions": ()}])
    met = WA._pattern_facts(None, r, [{"contract": "soybeans_cbot", "matched": _three,
                                       "n_matched": 3, "threshold": 3, "interactions": ()}])
    amp = WA._pattern_facts(None, r, [{"contract": "soybeans_cbot", "matched": _three,
                                       "n_matched": 3, "threshold": 3,
                                       "interactions": ({"rendered": True, "effect": "amplifies"},)}])
    assert none_at_all["rank"] == short["rank"] == WA.AMPLIFIER_LEVELS["neutral"]
    assert met["rank"] == WA.AMPLIFIER_LEVELS["met"]
    assert amp["rank"] == WA.AMPLIFIER_LEVELS["met_with_amplifier"]
    assert none_at_all["member"] is False and short["member"] is True
    # the tuple's own default is the neutral level, so an unstamped candidate cannot sort ahead
    assert WA.rank_key({"terms": {}, "driver_id": "", "kind": ""})[0] == WA.AMPLIFIER_LEVELS["neutral"]

    def k(**t):
        base = {"T_AMPLIFIER": 2, "T_NONLINEAR": 3, "T_TAIL": 0.0, "T_RUN": 0, "T_PATHS_DEPTH": 0,
                "T_PATHS_N": 0, "T_BREADTH": 0, "T_WINDOW": WA._NO_WINDOW, "T_NOVELTY": 0}
        base.update(t)
        return WA.rank_key({"terms": base, "driver_id": "", "kind": ""})

    # a PAST-THE-LINE row in no pattern now outranks a median spillover in an unmet one
    assert k(T_AMPLIFIER=2, T_NONLINEAR=0) < k(T_AMPLIFIER=2, T_NONLINEAR=3, T_TAIL=0.9)
    assert k(T_AMPLIFIER=1) < k(T_AMPLIFIER=2, T_NONLINEAR=0)


# -- minor (a): the sentence carries the fact that admitted the row -----------------------------------
def test_every_nomination_states_the_floor_fact_that_admitted_it():
    """The admission floor is a property of the BACKING ROW, so a kind whose own claim states none of
    ``FLOOR_CLAUSES`` was admitted by a fact the reader never met -- 27 of 44 ceiling rows and 24 of 43
    tail rows on the armed fixtures."""
    assert set(WA.FLOOR_WORDS) == set(WA.FLOOR_CLAUSES)
    bd, _r = _nb_board(mode="max")
    for c in WA.nonobvious_candidates(bd, analogs=(), overlay=WA.watch_overlay()):
        stated = WA.FLOOR_STATED_BY_KIND.get(c["kind"])
        if stated is not None and stated in c["floor"]:
            assert "what admits it here" not in c["what"], c["kind"]
            continue
        assert "what admits it here is that" in c["what"], (c["kind"], c["what"][:120])
        assert WA.FLOOR_WORDS[c["floor"][0]] in c["what"]
    # and the floor words are template words, so they cannot hand a kind a free novelty point
    for words in WA.FLOOR_WORDS.values():
        assert WA._content_tokens(words) <= WA._GRAMMAR


# -- minor (e): the window sentence reads as a SPAN ---------------------------------------------------
def test_the_window_sentence_reads_as_a_SPAN_and_not_as_two_loose_dates():
    ahead = {"opens": "2027-02-28", "closes": "2027-08-31"}
    clause = WA._window_clause(ahead, "2027-02-28 to 2027-08-31", ASOF)
    assert "the span this line ends on" in clause
    assert "closes on these dates" not in clause
    open_ended = WA._window_clause({"opens": "2026-08-31", "closes": None}, "2026-08-31", ASOF)
    assert "does not close" in open_ended


# -- minor (c): the nomination instrument carries its own error floor ---------------------------------
def test_the_nomination_instrument_carries_its_own_ZERO_WRITER_BASELINE():
    """minor (c). Both nomination counters approximate a thing no fence can check, and an arm reading a
    RATE off them needs to know what they return when the writer added nothing and dropped nothing --
    measured on the nine armed cells by scoring each block against its OWN rendered text. Banked as a
    declared constant and carried on the trace beside the counters, so the arm reads against a known
    floor rather than against zero."""
    base = R.NOMINATION_ZERO_WRITER_BASELINE
    assert set(base) >= {"added_at_zero_writer_min", "added_at_zero_writer_max",
                         "used_short_at_zero_writer_min", "used_short_at_zero_writer_max",
                         "cells", "measured"}
    assert base["cells"] == 9
    assert 0 <= base["added_at_zero_writer_min"] <= base["added_at_zero_writer_max"]
    assert 0 <= base["used_short_at_zero_writer_min"] <= base["used_short_at_zero_writer_max"]
    assert base["added_at_zero_writer_max"] > 0, "a floor of zero would be a claim of a perfect count"
    # ABSENT IS NEVER ZERO: a block with no nomination lines returns NO baseline key either, which is
    # what keeps `board_coverage` byte-identical to HEAD's twenty keys with the flag off.
    head_row = [{"role": "watch", "line": "- WATCH the next scheduled print El Nino on CBOT soybeans: x",
                 "tokens": ()}]
    assert R._nomination_coverage(head_row, [], lambda m: False, "2026-09-07") == {}


# -- REVIEW ROUND 3, MAJOR: the partial-fill note may not deny the alternates it sits over -------------
def _capped_board(mode="quick"):
    """Two decile readings of ONE kind on a tier whose kind cap is one: the tight pass takes the first
    and the relaxed pass takes the second, so the core under-fills WITH alternates on the page."""
    a = _decile_row("export", driver_id="export_pace")
    b = _decile_row("import", driver_id="import_pace")
    bd = _board([a, b], mode=mode)
    for r in (a, b):
        st = r.state
        bd.windows[r.key] = {"near": st.level_date, "reading": st.level_date,
                             "state_date": st.level_date, "knowledge_date": st.knowledge_date,
                             "analog_dates": ()}
        bd.series[st.key.label()] = st
    return bd


def test_the_PARTIAL_note_names_THE_CAPS_when_the_page_offers_alternates():
    """REVIEW ROUND 3, MAJOR. ``watch_nothing_further`` says nothing FURTHER cleared the admission bar.
    The producer emitted it whenever the TIGHT pass under-filled -- which is a fact about the
    DISTINCTNESS CAPS -- and MEASURED on the 108-seat d2 replay 36 seats printed it and ALL 36 printed
    it directly under alternates: items that had cleared that very bar and were held back by the
    one-per-reading / one-per-source / third-of-a-kind caps. The note is CORRECTED to the fact, never
    struck: the reader is still told the core is short, and is now told the true reason."""
    bd = _capped_board()
    rows = WA.nonobvious_rows(bd, analogs=(), loud_k=16, overlay=WA.watch_overlay())
    core = [w for w in rows if w.get("slot") == "ceiling"]
    alts = [w for w in rows if w.get("slot") == "nomination"]
    notes = [w for w in rows if w.get("form") == "absence"]
    assert core and alts and len(core) < WA.nonobvious_k("quick")
    note = [w for w in notes if str(w["kind"]).startswith("watch_")]
    assert len(note) == 1 and note[0]["reason"] == "watch_core_capped"
    assert B.check_reason("watch", "watch_core_capped") is None
    line = R.sb_absence(note[0]["label"], note[0]["reason"])
    assert R.classify(line) == ("SB-X",), line
    assert not any(ch.isdigit() for ch in line)
    # it says what actually bounded the core, and points at the items that are on the page
    assert "caps" in line and "alternates" in line
    # and it makes NO claim about the admission bar, which is the sentence that was false
    assert "clears the bar this list sets" not in line
    assert "no weaker item is offered" not in line


def test_an_EXHAUSTED_list_still_says_NOTHING_FURTHER_and_offers_nothing():
    """The other branch, and the reason the first word is kept rather than replaced: a list with no
    further candidates at all is telling the truth when it says so. One admitted reading on a board
    with nothing else to say draws one row, no alternate, and the exhausted word."""
    bd = _one_row_board(_decile_row("a_ref_no_book_declares", table="silver_psd",
                                    driver_id="mystery_driver"))
    rows = WA.nonobvious_rows(bd, analogs=(), loud_k=16, overlay=WA.watch_overlay())
    assert not [w for w in rows if w.get("slot") == "nomination"]
    note = [w for w in rows if str(w["kind"]).startswith("watch_")]
    assert len(note) == 1 and note[0]["reason"] == "watch_nothing_further"
    assert "nothing further" in R.sb_absence(note[0]["label"], note[0]["reason"])
    # the three notes are three sentences: nothing cleared the bar, nothing further did, the caps bound
    sentences = {R.absence_why(w) for w in
                 ("watch_floor_unmet", "watch_nothing_further", "watch_core_capped")}
    assert len(sentences) == 3


# -- REVIEW ROUND 3, minor: a line from this lane's own book says whose book it is ---------------------
def test_a_DRAWN_tail_row_RENDERS_and_NAMES_the_book_its_line_came_from():
    """THE CLAUSE, END TO END THROUGH THE SHIPPED RENDERER, which round 2 proved only on candidates and
    on the census replay (``tail_reading`` is drawn 297 times over the 108 replay seats and ZERO times
    on the three armed fixtures, whose rows all carry served conventions).

    AND IT NAMES ITS BOOK. All fifteen ``watch_overlay`` entries are ``percentile_bands [10, 90]``
    against a ``TAIL_DECILE`` of 10.0, so an overlay ref that cleared ``record_tail`` has crossed the
    overlay's own band BY CONSTRUCTION -- 180 of the 196 past-the-line tail sentences on the replay.
    Calling that "the desk convention" offered the reader a corroborating desk fact that was this
    producer's own, unratified, watch-only curation, invisible to SB-1 and to the cited line."""
    bd = _one_row_board(_decile_row("export", driver_id="export_pace"))
    rows = WA.nonobvious_rows(bd, analogs=(), loud_k=16, overlay=WA.watch_overlay())
    drawn = [w for w in rows if w.get("kind") == "tail_reading"]
    assert drawn, "a decile reading on an overlay ref is the tail kind"
    line = R.sb_watch(drawn[0])
    assert R.classify(line) == ("SB-W",), line
    assert "this list's own watch book" in line and "one measurement said twice" in line
    assert "the desk convention calls" not in line
    # the served book keeps the desk sentence: same fact, different provenance, different words
    served = WA._tail_line_clause({"declared": True, "label": "severe", "crossed": True,
                                   "source": "book"})
    assert "the desk convention calls severe" in served
    assert "watch book" not in served


# -- REVIEW ROUND 3, minor: a threshold of one is not a convergence ------------------------------------
def _pattern_board(threshold, n_matched, mode="deep"):
    """THE MATCHED TUPLE AND ``n_matched`` AGREE (review round 2, MAJOR 5). The first cut set
    ``matched=(r.driver_id,)`` beside ``n_matched=3`` -- a shape ``walk`` never emits, harmless only
    while the threshold test read the SCALAR. It reads the NAMES now, through ``render.pattern_count``,
    so a fixture whose two halves disagree would be grading nothing."""
    bd, r = _nb_board(mode=mode)
    matched = (r.driver_id,) + tuple(f"filler_{i}" for i in range(1, int(n_matched)))
    bd.convergence = [{"contract": r.contract, "name": "policy_shock_spike",
                       "matched": matched, "n_matched": len(matched),
                       "n_declared": max(2, len(matched)),
                       "threshold": threshold, "interactions": ()}]
    return bd, r


def test_a_pattern_whose_declared_threshold_is_ONE_is_never_narrated_as_a_convergence():
    """Nine of the 339 declared patterns on the replay boards declare ``threshold: 1``, where a SINGLE
    driver satisfies the admission floor and lifts ``T_AMPLIFIER`` to its met level (6 rows drawn, 3 of
    them in a core). The pattern is real and the row keeps it -- a strike would delete a fact the graph
    publishes -- but the sentence may not read as convergence to a reader who does not stop to do the
    arithmetic."""
    bd, _r = _pattern_board(1, 1)
    cands = WA.nonobvious_candidates(bd, analogs=(), overlay=WA.watch_overlay())
    one = [c for c in cands if c["kind"] == "convergence_amplified"]
    assert one, "a pattern at its own threshold is the fourth kind"
    assert "threshold is one" in one[0]["what"]
    assert "a single reading satisfies on its own" in one[0]["what"]
    assert "not a set of drivers moving with it" in one[0]["what"]
    bd3, _r3 = _pattern_board(3, 3)
    three = [c for c in WA.nonobvious_candidates(bd3, analogs=(), overlay=WA.watch_overlay())
             if c["kind"] == "convergence_amplified"]
    assert three and "threshold is three" in three[0]["what"]
    assert "a single reading satisfies" not in three[0]["what"], "the clause is keyed on the threshold"
    # and the clause may not teach the pattern words walk bars on a pattern sentence
    from leviathan.graphrag.state import walk as W
    low = WA.NONOBVIOUS_CLAUSES["threshold_one"].lower()
    for bad in W.CONVERGENCE_BANNED_WORDS:
        assert bad not in low.split() and not (" " in bad and bad in low)


# -- REVIEW ROUND 3, minor: the calendar footnote does not vote on the leg's word ----------------------
def test_the_release_FOOTNOTE_never_masks_the_honest_absence_word_on_the_leg():
    """An unexercised path, fixed as one. A board that clears the admission floor with NOTHING but has
    scheduled prints emits two declined rows; the dominant-word sort is ``(-count, word)``, so at one
    each ``release_dates_only`` won on the alphabet and the leg was stamped with the CALENDAR word --
    hiding the very state the 09-11 ruling asked the list to be able to report. 0 of 108 replay seats
    and 0 of 9 armed cells reach it, and no HEAD watch kind is ``release_footnote``, so the flag-off
    histogram cannot move."""
    bd, _r = _nb_board()
    foot = WA.release_footnote(bd)
    assert foot is not None and foot["declined"] == "release_dates_only"
    rec = WA.watch_leg(bd, [WA.absence_row(), foot])
    assert rec["outcome"] == "declined" and rec["reason"] == "watch_floor_unmet"
    # the footnote alone still names itself -- it is excluded from the vote, never dropped
    assert WA.watch_leg(bd, [foot])["reason"] == "release_dates_only"
    # and a HEAD board's declined rows are unaffected: none of them is the footnote
    head = WA.watch_rows(bd, analogs=(), loud_k=16)
    assert all(w["kind"] != "release_footnote" for w in head)


# -- REVIEW ROUND 3, minor: the two term lists are two lists ------------------------------------------
def test_RANK_TERM_KEYS_is_what_the_record_STAMPS_and_RANK_TERMS_is_the_rulings_NAMES():
    """``RANK_TERMS``' docstring counted eight against a tuple of seven and named ``T_PATHS``, which is
    the ruling's ONE word for the pair the record stamps as ``T_PATHS_DEPTH`` / ``T_PATHS_N``. Nothing
    indexes ``cand['terms']`` by it today, so this is a KeyError waiting for its first consumer rather
    than a live defect -- and the key set is now declared and graded."""
    stamped = set(WA.rank_terms({"kind": "tail_reading"}, frozenset()))
    assert set(WA.RANK_TERM_KEYS) == stamped
    assert len(WA.RANK_TERMS) == 7 and "T_NOVELTY" not in WA.RANK_TERMS
    assert "T_PATHS" in WA.RANK_TERMS and "T_PATHS" not in stamped
    assert {"T_PATHS_DEPTH", "T_PATHS_N"} <= stamped
    for name in WA.RANK_TERMS:
        assert name in stamped or name == "T_PATHS"


# -- REVIEW ROUND 3, minor: the licence's ceiling sentence is a BOUND ---------------------------------
def test_the_licence_states_the_core_as_a_BOUND_and_points_at_the_blocks_own_marks():
    """"The core is three items on a Scan, five on an Analysis and seven on a Cascade" is false of every
    block whose ceiling under-fills: 36 of 108 replayed seats drew a SHORTER core (two of seven on
    barley at Cascade) and each printed its own smaller number on every core mark. "KEEP AT MOST"
    already carried the bound; the sentence now carries it too, and points at the only count that is
    true of the list in hand."""
    from leviathan.graphrag import register as reg
    for form in (WA.WATCH_SELECTION_CLAUSE, WA.selection_clause("max"), WA.selection_clause("quick")):
        assert "at most" in form
        assert "how many this list actually drew" in form
        assert form.isascii() and reg.register_leaks(form) == [] and reg.desk_register_hits(form) == []
    assert "The core is at most three items on a Scan" in WA.WATCH_SELECTION_CLAUSE
    assert "at most seven items" in WA.selection_clause("max")
    # the block's own marks are the count the sentence defers to, and they say the drawn size
    bd = _capped_board()
    rows = WA.nonobvious_rows(bd, analogs=(), loud_k=16, overlay=WA.watch_overlay())
    core = [w for w in rows if w.get("slot") == "ceiling"]
    assert core and all(w["slot_size"] == len(core) < WA.nonobvious_k("quick") for w in core)

# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# S7b REVIEW ROUND 3 (2026-09-15) -- the two majors of the second verification
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
Z_CONV = {"kind": "z_bands", "bands": [1.5], "labels": ["elevated"]}


def _line_board(last, *, ref="fishmeal_price_z", table="silver_pink_sheet", conv=None, paths=True):
    """A loud row on a ref whose FILE convention is a magnitude line, with an OPEN window (the kind-3
    gate needs one) and two declared upstream paths (so the floor is cleared by something other than
    the line itself, which is what puts the row on the approaching branch at all)."""
    vals = [100.0 + (i % 11) - 5 for i in range(57)] + list(last)
    r = _row(values=vals, conv=conv or Z_CONV, ref=ref, table=table)
    bd = _board([r])
    bd.windows[r.key] = {"near": "2026-08-31", "reading": "2026-08-31",
                         "state_date": r.state.level_date, "knowledge_date": None,
                         "analog_dates": ()}
    if paths:
        bd.paths = [{"contract": r.contract, "bottom": r.driver_id, "ancestor": "A", "depth": 1},
                    {"contract": r.contract, "bottom": r.driver_id, "ancestor": "Bb", "depth": 3}]
    return r, bd


def _only(bd, kind):
    return [c for c in WA.nonobvious_candidates(bd, analogs=()) if c["kind"] == kind]


# -- MAJOR 1: the run's direction is TESTED against the side of the band the sentence names -----------
def test_the_approaching_sentence_is_TESTED_against_the_bands_own_side():
    """MAJOR 1. ``approaching_line`` printed "its run POINTS AT IT" off the run's LENGTH alone.
    MEASURED on the 144 banked census seats, flag on, through the shipped producer and
    ``render.render_board``: 10 of 42 drawn rows had a run pointing AWAY from the line they named and
    10 of 10 sat in a CORE slot -- BRL FX at a z of -0.617 against an uncrossed |1.5| band, RISING,
    narrated as running at it. A magnitude band's side is the READING's own sign, so a negative
    reading closes on it by falling; the row is corrected and never struck, and the rank credit for a
    run that is not the claim's own is withheld (the 09-15 ruling's own words)."""
    r, bd = _line_board([93.0, 95.0, 97.0])          # z below zero, run RISING -> away from |1.5|
    assert r.state.z["value"] < 0 and r.state.run["direction"] == "up"
    got = _only(bd, "approaching_line")
    assert len(got) == 1
    c = got[0]
    assert c["variant"] == "approaching_line_away" and c["run_toward"] is False
    assert "its run points AWAY from it" in c["what"] and "points at it" not in c["what"]
    assert "running away from it" in c["kind_words"]
    assert c["run_n"] >= 2 and WA.rank_terms(c, frozenset())["T_RUN"] == 0
    # and the same reading with the run on the band's own side keeps the claim AND the credit
    r2, bd2 = _line_board([99.0, 101.0, 103.0])      # z above zero, run RISING -> at |1.5|
    c2 = _only(bd2, "approaching_line")[0]
    assert c2["variant"] == "approaching_line" and c2["run_toward"] is True
    assert "its run points at it" in c2["what"]
    assert WA.rank_terms(c2, frozenset())["T_RUN"] == c2["run_n"] >= 2


def test_a_run_this_page_CANNOT_PLACE_against_the_line_claims_NEITHER_direction():
    """The third state is the point of the repair: a run whose direction this board does not sign
    cannot be called toward or away, and saying so is the honest sentence. Unexercised on the banked
    population (all 42 drawn rows are placeable) and pinned here as one, the way the calendar
    footnote's vote was."""
    r, bd = _line_board([93.0, 95.0, 97.0])
    r.state.run = dict(r.state.run, direction="flat")
    c = _only(bd, "approaching_line")[0]
    assert c["variant"] == "approaching_line_unplaced" and c["run_toward"] is None
    assert "cannot place its run against that line" in c["what"]
    assert "points at it" not in c["what"] and "AWAY" not in c["what"]
    # an UNPLACED run is not a run measured to point the wrong way, so it keeps its own credit
    assert WA.rank_terms(c, frozenset())["T_RUN"] == c["run_n"] >= 2


def test_the_floor_never_calls_a_run_BACK_AT_the_line_still_going_deeper():
    """The other half of MAJOR 1, and the same missing test: ``_floor_of``'s first clause derived
    "the run is still going deeper" from the sign of ``z``, which says nothing about which way a
    ``percentile_bands`` line was crossed -- and on a row with no z at all it admitted BOTH
    directions. MEASURED: 8 of the 34 decidable drawn ``past_the_line`` rows had a run pointing back
    at the line they had crossed, 7 of them CORE. CORRECTED AND NOT DELETED: the reading keeps its
    place on the page under the kind whose claim it does clear."""
    def board(last):
        vals = [100.0 + i for i in range(58)] + list(last)
        r = _row(values=vals, conv=PCT_CONV, ref="mpob_ending_stocks", table="silver_mpob",
                 driver_id="palm_stocks")
        r.state.z = None                     # the banked shape: a psd row with a percentile and no z
        bd = _board([r])
        bd.windows[r.key] = {"near": "2026-08-31", "reading": "2026-08-31",
                             "state_date": r.state.level_date, "knowledge_date": None,
                             "analog_dates": ()}
        return r, bd

    up, bd_up = board([1.0, 2.0, 3.0])       # past the `low` line at the 10th and RISING out of it
    assert up.state.convention["band"] == 10.0 and up.state.run["direction"] == "up"
    assert "past_a_declared_line" not in WA._floor_of(up)
    assert not _only(bd_up, "past_the_line")
    assert _only(bd_up, "tail_reading"), "the row is corrected onto another kind, never deleted"
    down, bd_dn = board([3.0, 2.0, 1.0])     # the convex state: FALLING further under the same line
    assert "past_a_declared_line" in WA._floor_of(down)
    got = _only(bd_dn, "past_the_line")
    assert got and "its run has not turned" in got[0]["what"]


def test_a_VARIANT_carries_its_own_four_strings_and_cannot_be_invented():
    """A variant is a second sentence of ONE kind: the trace, the draw's per-kind cap and
    ``T_NONLINEAR`` keep reading the kind, and the words, the body, the mechanism and the falsifier
    come from the sentence the row actually got."""
    for v, parent in WA.NONOBVIOUS_VARIANTS.items():
        assert parent in WA.NONOBVIOUS_KINDS and v not in WA.NONOBVIOUS_KINDS
        for m in (WA.NONOBVIOUS_BODIES, WA.NONOBVIOUS_KIND_WORDS, WA.NONOBVIOUS_MECHANISMS,
                  WA.NONOBVIOUS_FALSIFIERS):
            assert v in m and str(m[v]).isascii()
    r, bd = _line_board([93.0, 95.0, 97.0])
    with pytest.raises(KeyError):
        WA._cand("approaching_line", r, what="x", dates="", floor=("record_tail",),
                 variant="spillover_reach_unplaced")


# -- MAJOR 2: an ambiguously-signed edge is its own count and never folded into a direction ----------
def _fan_board(near_sign, far):
    r = _row(values=[0.1] * 60 + [2.2], conv=ONI_CONV)
    r.sign = near_sign
    bd = _board([r])
    bd.windows[r.key] = {"near": r.state.level_date, "reading": r.state.level_date,
                         "state_date": r.state.level_date, "knowledge_date": None, "analog_dates": ()}
    bd.fan = [{"contract": r.contract, "driver_id": r.driver_id,
               "far": [{"contract": c, "sign": s, "lag_band": r.lag_band, "confidence": "low"}
                       for c, s in far]}]
    return r, bd


def test_an_AMBIGUOUS_edge_is_counted_ON_ITS_OWN_and_never_folded_into_a_direction():
    """MAJOR 2. ``rows.SIGN_WORDS`` declares THREE signs -- and ``"0"``'s own words are "with no
    committed direction", which its comment calls a different fact that is never folded. The split was
    string equality against the near row's sign, so a ``0`` edge landed in ``same`` when the near row
    was also ``0``. MEASURED over the 144 banked seats: 11 of 430 drawn rows narrated 88 such edges as
    "in the same direction", one of them a CORE item, while the block's own edge line for that row
    said "with no committed direction" two lines away."""
    r, bd = _fan_board("+", [("cocoa", "+"), ("raw_sugar", "-"), ("cotton", "0")])
    c = _only(bd, "spillover_reach")[0]
    assert ("declared on three other markets -- one in the same direction, one in the opposite and "
            "one with no committed direction") in c["what"]
    fan = c["fan"]
    assert fan["same"] + fan["opposite"] + fan["undirected"] + fan["unplaced"] == fan["n"] == 3


def test_a_near_edge_with_NO_committed_direction_PLACES_NOTHING_and_says_so():
    """A split is a COMPARISON and a comparison needs two signed edges. Where this row's own declared
    edge carries no direction there is nothing to place the far ones against -- 11 of the 430 drawn
    rows, every one of them China state reserves, whose own declared edge is ``0``."""
    r, bd = _fan_board("0", [("cocoa", "+"), ("cotton", "0")])
    c = _only(bd, "spillover_reach")[0]
    assert c["variant"] == "spillover_reach_unplaced"
    assert ("declared on two other markets, one of them with a committed direction of their own and "
            "one without") in c["what"]
    assert "cannot place any of them with or against this reading" in c["what"]
    assert "in the same direction" not in c["what"].split("the nearest of them")[0]
    assert c["fan"]["same"] == c["fan"]["opposite"] == 0 and c["fan"]["unplaced"] == 1


# -- REVIEW ROUND 3, minor: the causes are named DEEPEST FIRST ----------------------------------------
def test_the_upstream_causes_are_named_DEEPEST_FIRST():
    """The sentence names its first three causes immediately after "the deepest {depth} hops up", and
    they came back in PATH-ITERATION order: 119 of 256 drawn upstream rows on the banked seats named a
    first cause that is not at the stated depth. Ambiguity rather than falsehood -- the tail's own
    arithmetic always let a reader recover that the list is the whole ancestor set -- and it closes by
    sorting what the reader is shown."""
    r, bd = _line_board([99.0, 101.0, 103.0])
    bd.paths = [{"contract": r.contract, "bottom": r.driver_id, "ancestor": "shallow", "depth": 1},
                {"contract": r.contract, "bottom": r.driver_id, "ancestor": "deepest", "depth": 4},
                {"contract": r.contract, "bottom": r.driver_id, "ancestor": "middle", "depth": 2}]
    facts = WA._paths_on(bd, r)
    assert facts["tops"] == ("deepest", "middle", "shallow") and facts["depth"] == 4
    c = _only(bd, "upstream_convergence")[0]
    assert "the deepest four hops up (deepest, middle" in c["what"]
