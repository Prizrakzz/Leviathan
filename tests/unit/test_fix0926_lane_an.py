"""LANE AN -- THE 09-26 FIX SITTING (CONTRACT P8 / P10): the like-state admission, per_dim on the trace, and the
watch window off the one C8 producer.

  AN-1 (D7 + the 2024 fact / PM MAJOR) a candidate on or after the seed row's own run start less one period
       is the PRESENT EPISODE, never a like state;
  AN-2 (D6) "sat like this" needs the like reading on the SAME SIDE of the declared line the seed's own label
       reads past -- refused only on a MEASURED reading;
  AN-3 (D5) ONE predicate (``analogs.like_state_admits``) is read by the head count AND the pick, and the
       watch's recurrence item names ``head_nearest`` -- a member of its own count;
  AN-4 (D16) the analog trace row carries ``per_dim`` (id, z_t, z_now, sign_agree), each only where measured;
  AN-5 (D11, watch half) the watch's reading window is ``walk.effect_window``'s, with its anchor, where the
       producer carries ``anchor_date`` -- HEAD's ``projection_window`` otherwise.

THE ARM PINS read the STORE'S OWN ROWS: the tariff turn's three analog seeds (NOAA ONI, PSD China corn
beginning stocks, FAOSTAT US cattle herd), rebuilt through the production producer (``seam._state_fn`` ->
``feeders.series_state`` -> the compiled board SQL) over the silver / gold parquet and fidelity-checked
against the served trace's own ``row_states`` (z, percentile, run, level date: 23 of 23 seeds equal on the
seven deep / max turns, and HEAD's selection reproduced every served pick) -- the lane's drive,
``scratchpad/fix_sitting_0926/an_work/drive_an.py``. The arrays below are those rows verbatim; a case the
builder wrote would prove nothing about the page.
"""
import inspect
import types

import pytest

from leviathan.graphrag.state import analogs as A
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import watch as WA
from leviathan.graphrag.state.feeders import state_from_arrays
from leviathan.graphrag.state.lagbands import parse_lag
from leviathan.graphrag.state.lint import load_conventions

ARM_ASOF = "2026-09-26"

# the tariff turn's seeds, as the store served them at the arm's as-of (2015-09 .. 2026-07 monthly; 1960 .. 2026
# and 1961 .. 2024 annual, contiguous)
_ARM_ONI = [
    2.02, 2.28, 2.45, 2.59, 2.5, 2.21, 1.69, 1.11, 0.57, 0.09, -0.19, -0.34, -0.42, -0.51, -0.49, -0.37, -0.08,
    0.08, 0.27, 0.32, 0.35, 0.32, 0.14, -0.07, -0.23, -0.44, -0.61, -0.76, -0.71, -0.67, -0.55, -0.35, -0.07,
    0.13, 0.2, 0.3, 0.52, 0.82, 1.04, 1.05, 0.99, 0.94, 0.87, 0.82, 0.71, 0.59, 0.38, 0.2, 0.31, 0.51, 0.72,
    0.75, 0.71, 0.66, 0.57, 0.33, 0.04, -0.18, -0.29, -0.43, -0.77, -1.0, -1.11, -1.06, -0.99, -0.85, -0.74,
    -0.56, -0.4, -0.31, -0.35, -0.46, -0.64, -0.77, -0.91, -0.83, -0.76, -0.68, -0.77, -0.86, -0.83, -0.73,
    -0.7, -0.78, -0.87, -0.89, -0.82, -0.7, -0.55, -0.33, -0.11, 0.19, 0.46, 0.73, 1.0, 1.25, 1.5, 1.74, 1.9,
    1.99, 1.84, 1.53, 1.18, 0.77, 0.43, 0.18, 0.06, -0.04, -0.12, -0.19, -0.29, -0.43, -0.46, -0.22, -0.08,
    0.02, -0.04, -0.02, -0.11, -0.26, -0.43, -0.57, -0.61, -0.6, -0.39, -0.21, 0.11, 0.46, 0.95, 1.39, 1.8]
_ARM_CHINA_BS = [
    3389000, 1358000, 5653000, 5514000, 5251000, 4337000, 3321000, 4515000, 5979000, 6085000, 6485000, 8875000,
    10927000, 10981000, 13250000, 17901000, 21326000, 22138000, 22422000, 32749000, 41375000, 42822000,
    41172000, 42723000, 48929000, 55999000, 54099000, 58656000, 66303000, 70646000, 72731000, 82821000,
    88417000, 84534000, 82740000, 87974000, 100093000, 117996000, 106919000, 122877000, 123799000, 102372000,
    84788000, 64981000, 44860000, 36560000, 35260000, 36610000, 36225000, 44220000, 42624000, 43244000,
    55700000, 80880000, 123588000, 172855000, 212017000, 223033000, 222541000, 210179000, 200526000, 205704000,
    209137000, 206023000, 211192000, 191928000, 177148000]
_ARM_CATTLE = [
    97700000, 100369008, 104488000, 107903008, 109000000, 108862000, 108783008, 109371008, 110015008, 112369008,
    114578000, 117862000, 121539008, 127788000, 132028000, 127980000, 122810000, 116375008, 110864000,
    111242000, 114351008, 115444000, 115001008, 113360000, 109582000, 105378000, 102118000, 99622000, 96740000,
    95816000, 96393000, 97556000, 99175900, 100973600, 102785200, 103548200, 101655700, 99744000, 99115000,
    98199000, 97297500, 96723000, 96100000, 94888000, 95018000, 96701504, 96573000, 96034500, 94721000,
    94081200, 92887400, 91160200, 90095200, 88526000, 89143000, 91888000, 93624600, 94298000, 94804701,
    93793300, 93586500, 91788700, 88841000, 87157400]


def _labels_monthly(y, m, n):
    out = []
    for _ in range(n):
        out.append("%04d-%02d" % (y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _arm_rows():
    conv = dict(load_conventions().get("conventions") or {})
    specs = (
        ("soybeans_cbot", "El_Nino", "oni_climate", "1-2 quarters", "silver_noaa_oni", "oni_anom", "monthly",
         "_global", "", "degC", _ARM_ONI, _labels_monthly(2015, 9, len(_ARM_ONI)), 36),
        ("corn_cbot", "China_state_reserves", "beginning_stock_region", "0-2 quarters", "silver_psd",
         "beginning_stocks_mt", "annual", "corn_cbot", "China", "MT", _ARM_CHINA_BS,
         [str(1960 + i) for i in range(len(_ARM_CHINA_BS))], None),
        ("corn_cbot", "cattle_cycle_herd_size", "herd_size_cattle", "4-8 quarters",
         "silver_production_livestock", "live_animals", "annual", "cattle_beef", "United States", "An",
         _ARM_CATTLE, [str(1961 + i) for i in range(len(_ARM_CATTLE))], None),
    )
    rows = []
    for (contract, driver_id, ref, lag, table, metric, cadence, commodity, country, unit, vals, dates,
         ym_lag) in specs:
        st = state_from_arrays(ref, [float(v) for v in vals], dates, cadence=cadence, asof=ARM_ASOF,
                               commodity=commodity, country=country, unit=unit, convention=conv.get(ref),
                               table=table, metric=metric)
        st.recency = dict(st.recency or {}, publication_lag_days=0, ym_publication_lag_days=ym_lag)
        rows.append(B.NodeRow(contract=contract, driver_id=driver_id, lag_band=parse_lag(lag), state=st,
                              legs={"loud": True}))
    return rows


def _arm_board(rows):
    byk = {r.key: r for r in rows}
    return types.SimpleNamespace(rows=rows, order=[r.key for r in rows], asof=ARM_ASOF, tape={}, fan=[],
                                 series={}, anchors=(), analogs=[],
                                 ledger=types.SimpleNamespace(benchmark_reads=0, evidence_borrows=0),
                                 row=lambda c, d: byk.get((c, d)))


def _logged_admits(monkeypatch):
    log = []
    orig = A.like_state_admits

    def _f(cand, **kw):
        got = orig(cand, **kw)
        log.append({"date": cand.get("date"), "reason": got[1], "admitted": got[0],
                    "side_value": cand.get("side_value"), "present_from": kw.get("present_from")})
        return got
    monkeypatch.setattr(A, "like_state_admits", _f)
    return log


# ---------------------------------------------------------------------------------------------------------
# THE ARM: the tariff turn's own rows
# ---------------------------------------------------------------------------------------------------------
def test_ARM_the_rebuilt_seeds_are_the_rows_the_tariff_page_served():
    """The fidelity gate, restated on the deck's copy of the rows: the served trace's own row_states."""
    oni, china, cattle = _arm_rows()
    assert oni.state.z["value"] == pytest.approx(2.426665229537876, abs=1e-12)
    assert oni.state.percentile["value"] == pytest.approx(92.74809160305344, abs=1e-12)
    assert oni.state.run == {"direction": "up", "length": 8, "since_date": "2025-11"}
    assert oni.state.convention["label"] == "strong" and oni.state.convention["band"] == 1.5
    assert china.state.z["value"] == pytest.approx(-2.2074309536158245, abs=1e-12)
    assert china.state.percentile["value"] == pytest.approx(84.32835820895522, abs=1e-12)
    assert (china.state.run["direction"], china.state.run["length"]) == ("down", 2)
    assert cattle.state.z["value"] == pytest.approx(-1.8857155782070762, abs=1e-12)
    assert (cattle.state.run["direction"], cattle.state.run["length"]) == ("down", 5)


def test_ARM_with_the_two_boundaries_off_the_producer_reproduces_the_served_february_2025(monkeypatch):
    """HEAD's selection is the new one with no boundary given -- the served row, exactly: 2025-02, readable
    on two of three dimensions, agreeing on both, thirty-three in the pool, two counted as like states."""
    monkeypatch.setattr(A, "present_from_of", lambda st, hist: None)
    monkeypatch.setattr(A, "side_line_of", lambda st: None)
    rows = A.analog_rows(_arm_board(_arm_rows()), knobs=B.board_knobs_of("deep"))
    oni = rows[0]
    assert (oni["driver_id"], oni["date"], oni["dims_seen"], oni["sign_agree"]) == ("El_Nino", "2025-02", 2, 2)
    assert (oni["n_candidates"], oni["n_candidates_head"]) == (33, 2)
    assert [r["date"] for r in rows] == ["2025-02", "2025", "2005"]         # the served trace's three rows


def test_ARM_D6_D7_february_2025_is_the_other_side_of_the_strong_line_and_the_present_run_is_refused(monkeypatch):
    log = _logged_admits(monkeypatch)
    rows = A.analog_rows(_arm_board(_arm_rows()), knobs=B.board_knobs_of("deep"))
    oni = rows[0]
    assert oni["side_line"] == {"line": 1.5, "label": "strong", "side": "high", "kind": "abs_bands"}
    assert oni["present_from"] == "2025-10"
    assert oni["refused"] == {"present_run": 2, "other_side": 28}
    feb = next(x for x in log if x["date"] == "2025-02")
    # the store's own ONI knowable at February 2025 is on the cool side of zero, let alone of +1.5 degC (D6)
    assert feb["reason"] == "other_side" and feb["side_value"] < 0.0
    assert {x["date"] for x in log if x["reason"] == "present_run" and x["present_from"] == "2025-10"} \
        == {"2025-10", "2025-12"}                                           # the warm run's own months (D7)
    # THE NEW PICK: the 2023-24 warm episode, before the present run and past the same line
    assert oni["date"] == "2024-01"
    jan = next(x for x in log if x["date"] == "2024-01" and x["present_from"] == "2025-10")
    assert jan["reason"] in ("", "not_head") and jan["side_value"] >= 1.5
    # the annual seeds lose the months of their own present run (HEAD's 2025 China pick sat inside it)
    assert rows[1]["date"] == "2010" and rows[1]["refused"] == {"present_run": 3, "other_side": 0}
    assert "side_line" not in rows[1]                                        # no line drawn, no side refusal


def test_ARM_AN3_the_count_and_the_member_come_off_ONE_predicate_so_no_zero_recurrence_prints(monkeypatch):
    log = _logged_admits(monkeypatch)
    bd = _arm_board(_arm_rows())
    rows = A.analog_rows(bd, knobs=B.board_knobs_of("deep"))
    oni = rows[0]
    admitted = [x for x in log if x["admitted"] and x["present_from"] == "2025-10"]
    assert oni["n_candidates_head"] == len(admitted) == 0 and oni["head_nearest"] is None
    base = WA.like_state_base_rate(oni, bd.rows[0])
    assert base["n"] == 0
    assert "base_rated_episode" not in WA._floor_of(bd.rows[0], base_rate=base)


# ---------------------------------------------------------------------------------------------------------
# AN-1 THE PRESENT RUN
# ---------------------------------------------------------------------------------------------------------
def _st(run):
    return types.SimpleNamespace(run=run)


def test_AN1_present_from_is_the_rows_own_run_start_less_ONE_PERIOD_OF_ITS_OWN_RECORD():
    monthly = {"dates": _labels_monthly(2024, 1, 30)}
    assert A.present_from_of(_st({"direction": "up", "length": 8, "since_date": "2025-11"}), monthly) == "2025-10"
    annual = {"dates": [str(y) for y in range(1990, 2027)]}
    assert A.present_from_of(_st({"direction": "down", "length": 2, "since_date": "2024"}), annual) == "2023"
    assert A.present_from_of(_st({"declined": True, "reason": "no run"}), monthly) is None
    assert A.present_from_of(_st(None), monthly) is None
    # a run older than the record the selection reads: the whole record is the present episode
    assert A.present_from_of(_st({"direction": "up", "length": 99, "since_date": "2019-01"}), monthly) == "2019-01"


def test_AN1_a_candidate_ON_OR_AFTER_present_from_is_refused_and_None_excludes_nothing():
    head = {"index": 5, "date": "2025-10", "dims_seen": 3, "sign_agree": 3, "side_value": None}
    assert A.like_state_admits(head, n_dims=3, head_idx={5}, present_from="2025-10", side_line=None) \
        == (False, "present_run")
    assert A.like_state_admits(dict(head, date="2025-09"), n_dims=3, head_idx={5}, present_from="2025-10",
                               side_line=None) == (True, "")
    assert A.like_state_admits(head, n_dims=3, head_idx={5}, present_from=None, side_line=None) == (True, "")


def test_AN1_REJECTED_the_separation_knob_is_not_the_mechanism():
    """The rejected lexical form: raising ``min_separation_months``. Its default is HEAD's twelve."""
    assert inspect.signature(A.select_analogs).parameters["min_separation_months"].default == 12


# ---------------------------------------------------------------------------------------------------------
# AN-2 THE SIDE OF THE SEED'S DECLARED LINE
# ---------------------------------------------------------------------------------------------------------
def _conv(kind, band, reading, label="x", matched=True):
    return types.SimpleNamespace(convention={"kind": kind, "band": band, "reading": reading, "label": label,
                                             "matched": matched})


def test_AN2_the_line_is_read_off_the_rows_own_label_record():
    assert A.side_line_of(_conv("abs_bands", 1.5, 1.8, "strong")) == \
        {"line": 1.5, "label": "strong", "side": "high", "kind": "abs_bands"}
    assert A.side_line_of(_conv("abs_bands", 1.5, -1.8, "strong")) == \
        {"line": -1.5, "label": "strong", "side": "low", "kind": "abs_bands"}
    assert A.side_line_of(_conv("z_bands", 1.0, -1.73, "notable"))["line"] == -1.0
    assert A.side_line_of(_conv("percentile_bands", 10, 3.4, "very tight"))["side"] == "low"
    assert A.side_line_of(_conv("percentile_bands", 90, 99.2, "very ample"))["side"] == "high"
    # no line proven -> None: a reading past NO line, a declined label, a kind the history does not carry
    assert A.side_line_of(_conv("abs_bands", None, 0.3, None, matched=False)) is None
    assert A.side_line_of(types.SimpleNamespace(convention={"declined": "no reading"})) is None
    assert A.side_line_of(_conv("pace_vs_prior_year", 10, 14.0, "ahead")) is None
    assert A.side_line_of(types.SimpleNamespace(convention=None)) is None


def test_AN2_OTHER_SIDE_is_refused_ONLY_on_a_measured_reading():
    line = {"line": 1.5, "label": "strong", "side": "high", "kind": "abs_bands"}
    cand = {"index": 1, "date": "2025-02", "dims_seen": 2, "sign_agree": 2}
    assert A.like_state_admits(dict(cand, side_value=-0.43), n_dims=3, head_idx=set(), present_from=None,
                               side_line=line) == (False, "other_side")
    # unmeasured reading, or no line at all: not refused (the head rule still answers)
    assert A.like_state_admits(dict(cand, side_value=None), n_dims=3, head_idx=set(), present_from=None,
                               side_line=line) == (False, "not_head")
    assert A.like_state_admits(dict(cand, side_value=-0.43), n_dims=3, head_idx=set(), present_from=None,
                               side_line=None) == (False, "not_head")
    # at the line is past it (the label rule is ``>=``)
    assert A.like_state_admits(dict(cand, side_value=1.5, dims_seen=3), n_dims=3, head_idx={1},
                               present_from=None, side_line=line) == (True, "")


def test_AN2_REJECTED_no_series_phase_or_driver_word_in_the_admission():
    """AN-c: the admission reads the conventions book generically -- never an ENSO special case."""
    src = "".join(inspect.getsource(f).lower() for f in (A.side_line_of, A._side_value, A.present_from_of,
                                                         A.like_state_admits))
    code = "\n".join(l.split("#")[0] for l in src.splitlines())
    doc_free = code.replace('"""', "\x00").split("\x00")
    body = "".join(doc_free[0::2])
    for word in ("oni", "nino", "nina", "enso", "phase", "el_", "la_"):
        assert word not in body, word


# ---------------------------------------------------------------------------------------------------------
# AN-3 ONE PREDICATE, AND THE WATCH NAMES A MEMBER OF ITS COUNT
# ---------------------------------------------------------------------------------------------------------
def test_AN3_head_nearest_is_the_FIRST_ADMITTED_member_in_the_SCORED_ORDER(monkeypatch):
    log = _logged_admits(monkeypatch)
    oni, china, cattle = _arm_rows()
    rows = A.analog_rows(_arm_board([china, cattle]), knobs=B.board_knobs_of("max"))
    for r in rows:
        if r.get("declined"):
            continue
        hn = r["head_nearest"]
        pf = r.get("present_from")
        mine = [x for x in log if x["present_from"] == pf]
        admitted = [x["date"] for x in mine if x["admitted"]]
        assert r["n_candidates_head"] == len(admitted)
        assert (hn is None) == (not admitted)
        if hn is not None:
            assert hn["date"] == admitted[0]                  # the log is in the scored order


def test_AN3_the_watch_names_the_MEMBER_as_the_nearest_like_state():
    stanza = {"date": "2025-02", "dims_seen": 2, "dims_declared": 3, "n_candidates_head": 2,
              "head_nearest": {"date": "2023-12", "distance": 0.4, "dims_seen": 3, "agree_n": 3}}
    variant, date, fill = WA._recurrence_member(stanza)
    assert (variant, date, fill) == ("recurrence_like", "2023-12", {})
    body = WA.NONOBVIOUS_BODIES[variant].format(n_like="two", states="states", n_obs="one hundred", date=date)
    assert "the nearest like state dated 2023-12" in body and "2025-02" not in body


def test_AN3_a_count_with_no_member_named_says_the_READING_and_its_coverage():
    stanza = {"date": "2025-02", "dims_seen": 2, "dims_declared": 3, "n_candidates_head": 2, "head_nearest": None}
    variant, date, fill = WA._recurrence_member(stanza)
    assert (variant, date) == ("recurrence_reading", "2025-02")
    body = WA.NONOBVIOUS_BODIES[variant].format(n_like="two", states="states", n_obs="one hundred", date=date,
                                               **fill)
    assert "the nearest reading is dated 2025-02, readable on two of the three dimensions compared" in body
    assert "not one of the like states counted" in body


def test_AN3_a_hand_built_row_keeps_HEADs_sentence_byte_for_byte():
    assert WA._recurrence_member({"date": "2025-02"}) == ("recurrence", "2025-02", {})


def test_AN3_the_two_variants_are_declared_graded_and_carry_their_own_falsifiers():
    from leviathan.graphrag.state import lint as L
    for v in ("recurrence_like", "recurrence_reading"):
        assert WA.NONOBVIOUS_VARIANTS[v] == "recurrence"
        for m in (WA.NONOBVIOUS_KIND_WORDS, WA.NONOBVIOUS_MECHANISMS, WA.NONOBVIOUS_FALSIFIERS,
                  WA.NONOBVIOUS_BODIES):
            assert v in m
        assert not any(ch.isdigit() for ch in WA.NONOBVIOUS_BODIES[v])
    assert L._check_nonobvious_watch() == []


# ---------------------------------------------------------------------------------------------------------
# AN-4 per_dim ON THE TRACE ROW
# ---------------------------------------------------------------------------------------------------------
def test_AN4_the_trace_row_carries_per_dim_each_reading_only_where_measured():
    rows = A.analog_rows(_arm_board(_arm_rows()), knobs=B.board_knobs_of("deep"))
    tr = A._analog_trace_row(rows[0])
    per = {p["id"]: p for p in tr["per_dim"]}
    # the Pacific's own sigma is unread at January 2024 (its 120-month window has not filled on the 131
    # months the board reads), so its entry carries the present reading and nothing it did not measure
    assert set(per["El_Nino"]) == {"id", "z_now"}
    assert set(per["cattle_cycle_herd_size"]) == {"id", "z_t", "z_now", "sign_agree"}
    assert per["China_state_reserves"]["sign_agree"] is False
    assert tr["side_line"]["label"] == "strong" and tr["refused"] == {"present_run": 2, "other_side": 28}
    assert list(tr)[:9] == ["contract", "driver_id", "series_key", "date", "dims_seen", "dims_declared",
                            "agree_n", "decline", "outcomes"]            # HEAD's keys first, in HEAD's order


def test_AN4_a_row_carrying_none_of_the_new_facts_keeps_HEADs_trace_shape():
    tr = A._analog_trace_row({"contract": "c", "driver_id": "d", "date": "2020-01", "outcomes": ()})
    assert list(tr) == ["contract", "driver_id", "series_key", "date", "dims_seen", "dims_declared", "agree_n",
                        "decline", "outcomes"]


# ---------------------------------------------------------------------------------------------------------
# AN-5 THE WATCH WINDOW OFF THE ONE C8 PRODUCER
# ---------------------------------------------------------------------------------------------------------
def _watch_row():
    vals = [0.1] * 60 + [0.6, 0.9, 1.2, 1.6, 1.9, 2.2]
    st = state_from_arrays("oni_climate", vals, _labels_monthly(2021, 3, len(vals)), cadence="monthly",
                           asof="2026-09-07", unit="degC", windows={"monthly": 60}, table="silver_noaa_oni",
                           metric="anom")
    return B.NodeRow(contract="soybeans_cbot", driver_id="El_Nino", lag_band=parse_lag("1-2 quarters"),
                     state=st)


def test_AN5_the_watch_window_is_the_C8_producers_and_carries_its_anchor(monkeypatch):
    from leviathan.graphrag.state import walk as W
    calls = []

    def _ew(band, *, newest, run_start=None, peak=None):
        calls.append((newest, run_start))
        return {"opens": "2026-12-31", "closes": "2027-03-31", "peak_closes": None, "anchor": "reading",
                "anchor_date": newest}
    monkeypatch.setattr(W, "effect_window", _ew)
    r = _watch_row()
    bd = types.SimpleNamespace(windows={r.key: {"reading": "2026-08", "near": "2026-02"}})
    w = WA._reading_window(bd, r)
    assert calls == [("2026-08", None)]                 # anchored on the READING, never the run start
    assert w == {"opens": "2026-12-31", "closes": "2027-03-31", "open_ended": False, "declined": None,
                 "anchor": "reading", "anchor_date": "2026-08", "fallback": ""}


def test_AN5_without_the_producers_anchor_date_the_call_site_is_HEADs(monkeypatch):
    from leviathan.graphrag.state import walk as W
    monkeypatch.setattr(W, "effect_window", lambda band, *, newest, run_start=None, peak=None:
                        {"opens": "x", "closes": "y", "peak_closes": None, "anchor": "reading"})
    r = _watch_row()
    bd = types.SimpleNamespace(windows={r.key: {"reading": "2026-08"}})
    w = WA._reading_window(bd, r)
    assert w == dict(W.projection_window("2026-08", r.lag_band), anchor="2026-08", fallback="")


def test_AN5_the_window_clause_says_its_anchor_in_the_books_words_where_render_has_them(monkeypatch):
    win = {"opens": "2026-12-31", "closes": "2027-03-31", "anchor": "reading", "anchor_date": "2026-08"}
    monkeypatch.setattr(R, "window_anchor_words",
                        lambda anchor, date: "this reading's own date in August 2026" if anchor == "reading" else "",
                        raising=False)
    got = WA._window_clause(win, "2026-12-31 to 2027-03-31", "2026-09-07")
    assert got.startswith(" The declared lag window, counted from this reading's own date in August 2026, "
                          "opens ahead;")
    monkeypatch.delattr(R, "window_anchor_words", raising=False)
    head = WA._window_clause(win, "2026-12-31 to 2027-03-31", "2026-09-07")
    assert head.startswith(" The declared lag window, counted from that reading's own date, opens ahead;")
