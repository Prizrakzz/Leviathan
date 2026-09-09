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
