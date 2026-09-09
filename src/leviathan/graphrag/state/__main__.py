"""THE OFFLINE HARNESS -- STATE ENGINE DESIGN sec 11 row S3 ("``state/__main__.py`` -- the offline
harness (ASCII-only stdout, pinned) that renders a Board from fixture arrays") and sec 0.3 (the three
target answers as the acceptance spec). Sitting S3.

WHAT THIS IS. ``python -m leviathan.graphrag.state`` builds the three scenario boards from FIXTURE
ARRAYS on the REAL thirty-six curated DAGs, renders each one through ``state/render.py``, and prints
the block, the slot audit and the per-class row and token measurement. NO pg mirror, NO Athena, NO
network, NO LLM, NO clock: every input is threaded and every as-of is a literal, so a laptop and a
serving container compute the same bytes.

WHY THE REAL GRAPH AND FIXTURE NUMBERS. The bars that matter here are facts about the SHIPPED graph --
that the soybean board reads El Nino as ``-`` over one to two quarters while the palm board reads the
SAME state as ``+`` over two to four (bar B7), that ``crude_oil`` sits two hops upstream of
``board_crush`` (B8), that palm's ``biodiesel_energy_floor`` declares three drivers with a threshold of
two and one ``(crude_oil_price, biodiesel_mandate) amplifies`` interaction (B16). A synthetic graph
would pin the fixture instead of the estate. The NUMBERS are fixtures because the state producer's own
read path is S1's and is graded in-VPC at S4; what this harness grades is the arithmetic ABOVE the read.

THE THREE SCENARIOS, and what each one is the bar for:
  1. ``soybeans_now``   -- "what is the situation on soybeans now? how is it looking 3 months from now?"
     at 2026-09-07, Cascade. The ONI state row with its z, its percentile and its four-month run; the
     edge with its band; the projection placing "3 months" inside the window; the SB-T front settle
     with its one, five, twenty-one and sixty-three session changes and its five-year percentile; the
     ``crude_oil -> soybean_crush_margin -> board_crush`` upstream path; an ONI-crossing analog with its
     outcome over the band and its count in words; a dated watch list.
  2. ``el_nino_fanout`` -- the SAME ONI state from a SOYBEANS-ONLY question. THE QUESTION DOES NOT NAME
     PALM, and palm must surface through the fan-out carrying palm's OWN sign and band. That is
     Amendment 2's bar, held here.
  3. ``b40_event``      -- Indonesia's B40 mandate as a USER-ATTACHED event on the palm board: the dated
     EVENT row projecting forward over its band, the export-levy upstream and the soyoil-substitution
     spillovers, and the flag-series event analog that says plainly there is no numeric event history.

ASCII-ONLY STDOUT is a law here (the Windows console is cp1252); the file itself is UTF-8.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from typing import Optional

from leviathan.graphrag.state import analogs as A
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import narration as N
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import transforms as TR
from leviathan.graphrag.state import walk as W
from leviathan.graphrag.state import watch as WA
from leviathan.graphrag.state.feeders import series_key_for, state_from_arrays
from leviathan.graphrag.state.rows import SeriesKey, StateRow, TapeState, status_word

SCENARIOS: tuple = ("soybeans_now", "el_nino_fanout", "b40_event")

ASOF = "2026-09-07"


# ---------------------------------------------------------------------------------------------------
# DETERMINISTIC FIXTURE ARRAYS -- no randomness, no clock, no file
# ---------------------------------------------------------------------------------------------------
def _lcg(seed: int, n: int) -> list:
    """A pinned linear congruential sequence in ``[-1, 1)``. DETERMINISTIC BY CONSTRUCTION so two runs
    of this harness print identical bytes -- a fixture that moved between runs would make every bar
    below unfalsifiable."""
    x, out = int(seed), []
    for _ in range(n):
        x = (1103515245 * x + 12345) % 2147483648
        out.append((x / 2147483648.0) * 2.0 - 1.0)
    return out


def _month_ends(start_year: int, start_month: int, n: int) -> list:
    out = []
    y, m = start_year, start_month
    for _ in range(n):
        nxt = _dt.date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
        out.append((nxt - _dt.timedelta(days=1)).isoformat())
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _weekly_dates(end: str, n: int) -> list:
    e = _dt.date.fromisoformat(end)
    return [(e - _dt.timedelta(days=7 * i)).isoformat() for i in range(n - 1, -1, -1)]


def _session_dates(end: str, n: int) -> list:
    """Weekday sessions back from ``end``. No venue calendar is read (V1 does not read
    ``venue_holidays.yaml``), so a holiday inside the span is a session this fixture keeps -- stated
    rather than silently modelled."""
    d, out = _dt.date.fromisoformat(end), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= _dt.timedelta(days=1)
    return list(reversed(out))


def _year_ends(end_year: int, n: int) -> list:
    return [f"{y}-12-31" for y in range(end_year - n + 1, end_year + 1)]


def _oni_series() -> tuple:
    """ONI from 1990-01 to 2026-08: a pinned ENSO-shaped cycle with several onsets past the +0.5 degC
    line, and an explicit rising TAIL so the anchor state is the design's own ("printed +0.98 degC and
    has risen in each of the last four months").

    THE TAIL IS OVERWRITTEN RATHER THAN TUNED. A generated series that happened to end at +0.98 with a
    four-month run would be a coincidence this file could not defend; writing the last six values makes
    the anchor state a stated fixture and leaves the HISTORY -- which is what the analog selector reads
    -- procedural."""
    dates = _month_ends(1990, 1, 440)
    noise = _lcg(7, len(dates))
    vals = []
    for i, _d in enumerate(dates):
        # a ~44-month cycle plus a slower ~131-month modulation: several crossings of +0.5 and -0.5
        import math
        base = 1.15 * math.sin(2 * math.pi * i / 44.0) + 0.45 * math.sin(2 * math.pi * i / 131.0)
        vals.append(round(base + 0.18 * noise[i], 2))
    vals[-6:] = [0.42, 0.31, 0.55, 0.74, 0.88, 0.98]
    return vals, dates


def _z_series(seed: int, n: int, dates: list, *, tail=None) -> tuple:
    noise = _lcg(seed, n)
    vals = [round(2.1 * v, 2) for v in noise]
    if tail:
        vals[-len(tail):] = list(tail)
    return vals, dates


#: The refs this harness serves, with the shape each one is served in. A ref ABSENT from this table is
#: not a gap: its row renders as a BOARD ABSENCE with the closed word its read outcome produced, which
#: is exactly what a real board does with the estate's unmapped and planned refs.
def _fixtures() -> dict:
    oni_v, oni_d = _oni_series()
    m_d = oni_d
    w_d = _weekly_dates("2026-09-04", 200)
    s_d = _session_dates("2026-09-04", 320)
    # THE LAST ANNUAL OBSERVATION IS 2025-12-31 AND NOT 2026-12-31. The first cut used the
    # as-of's own year and served a marketing-year row DATED AFTER THE AS-OF -- the fixture
    # would have violated bar B2 in a harness whose whole job is to grade the arithmetic
    # above the read, where no `_guard` is there to refuse it.
    a_d = _year_ends(2025, 20)
    iod_v, _ = _z_series(11, len(m_d), m_d, tail=[0.12, 0.21, 0.33, 0.41])
    dro_v, _ = _z_series(23, len(m_d), m_d, tail=[0.3, 0.45, 0.62, 0.79])
    hea_v, _ = _z_series(31, len(m_d), m_d, tail=[0.2, 0.1, 0.35, 0.62])
    bre_v, _ = _z_series(41, len(m_d), m_d, tail=[0.35, 0.52, 0.68, 0.81])
    crush = [round(0.85 + 0.42 * v, 3) for v in _lcg(53, len(s_d))]
    crush[-4:] = [0.92, 0.96, 1.01, 1.06]
    fx = [round(100.0 + 6.0 * v, 3) for v in _lcg(61, len(s_d))]
    su = [0.081, 0.094, 0.101, 0.088, 0.112, 0.126, 0.104, 0.097, 0.115, 0.131,
          0.122, 0.108, 0.099, 0.118, 0.127, 0.113, 0.106, 0.121, 0.109, 0.117]
    esr = [round(820.0 + 240.0 * v, 1) for v in _lcg(71, len(w_d))]
    esr[-3:] = [742.5, 701.2, 664.8]
    cot = [round(48000.0 + 32000.0 * v, 0) for v in _lcg(83, len(w_d))]
    mpob = [round(1.78 + 0.36 * v, 3) for v in _lcg(97, len(m_d))]
    mpob[-3:] = [1.61, 1.54, 1.47]
    exp_id = [round(28.4 + 4.2 * v, 2) for v in _lcg(103, len(a_d))]
    return {
        "oni_climate": {"values": oni_v, "dates": m_d, "unit": "degC", "narrate_unit": "degC"},
        "iod_climate": {"values": iod_v, "dates": m_d, "unit": "degC", "narrate_unit": "degC"},
        "drought_z": {"values": dro_v, "dates": m_d, "unit": "sigma", "narrate_unit": "sigma"},
        "heat_stress_z": {"values": hea_v, "dates": m_d, "unit": "sigma", "narrate_unit": "sigma"},
        "brent_crude_z": {"values": bre_v, "dates": m_d, "unit": "sigma", "narrate_unit": "sigma"},
        "cbot_board_crush_margin": {"values": crush, "dates": s_d, "unit": "USD/bu",
                                    "narrate_unit": "USD per bushel"},
        "fred_fx_macro": {"values": fx, "dates": s_d, "unit": "index", "narrate_unit": "index"},
        "psd_ending_stock_su_ratio": {"values": su, "dates": a_d, "unit": "ratio",
                                      "narrate_unit": "S/U ratio"},
        "esr_exports": {"values": esr, "dates": w_d, "unit": "1000 MT", "narrate_unit": "1000 MT"},
        "cot_mm_positioning": {"values": cot, "dates": w_d, "unit": "contracts",
                               "narrate_unit": "contracts"},
        "mpob_ending_stocks": {"values": mpob, "dates": m_d, "unit": "MMT", "narrate_unit": "MMT"},
        "export": {"values": exp_id, "dates": a_d, "unit": "MMT", "narrate_unit": "MMT"},
    }


def _benchmark_arrays() -> dict:
    """The monthly BENCHMARK per anchor board -- the World Bank column ``_RV_PRICE_SERIES`` maps per
    slug and leg A fetches it in wave 2 at one read (sec 4.3). Here it is an array, and the seat the
    walk reserved is the one this fills."""
    d = _month_ends(1990, 1, 440)
    soy = [round(340.0 + 120.0 * v, 2) for v in _lcg(131, len(d))]
    palm = [round(760.0 + 260.0 * v, 2) for v in _lcg(137, len(d))]
    return {"soybeans_cbot": {"values": soy, "dates": d, "unit": "USD/t",
                              "label": "the soybean monthly benchmark", "table": "silver_pink_sheet",
                              "metric": "soybeans_usd_t"},
            "malaysian_crude_palm_oil_cme": {"values": palm, "dates": d, "unit": "USD/t",
                                             "label": "the palm monthly benchmark",
                                             "table": "silver_pink_sheet",
                                             "metric": "palm_oil_cpo_usd_t"}}


# ---------------------------------------------------------------------------------------------------
# THE INJECTED SEAMS
# ---------------------------------------------------------------------------------------------------
def _conventions() -> dict:
    from leviathan.graphrag.state.lint import load_conventions
    return dict((load_conventions().get("conventions") or {}))


def fixture_state_fn(asof: str, fixtures: Optional[dict] = None, *, turn_kind: str = ""):
    """``(ref, node) -> (StateRow, reads)`` over the fixture arrays.

    A ref this harness does not serve returns a StateRow carrying ``read_empty:no_fixture_series`` --
    a ROW that says so, never a missing row. That is not a shortcut: it is the same shape the estate's
    own board carries for the fifteen ``planned`` and seven ``declared_available_unserved`` refs on a
    real soybean board, and it is what makes the SB-X half of the block reachable offline."""
    fx = fixtures if fixtures is not None else _fixtures()
    conv = _conventions()

    def _fn(ref, node):
        plan = series_key_for(ref, node, turn_kind=turn_kind)
        if plan.key is None:
            return StateRow(key=SeriesKey(ref=ref), status=plan.status, reads=0), 0
        spec = fx.get(plan.key.ref) or fx.get(ref)
        if spec is None:
            return StateRow(key=plan.key, status="read_empty:no_fixture_series",
                            table=plan.table, metric=plan.metric, cadence=plan.cadence,
                            asof=asof, reads=1), 1
        # THE DECLARED SAME-SERIES OFFSET IS APPLIED TO THE ARRAY, not merely announced on the row.
        # `state_from_arrays` runs the TRANSFORM half only, so it never reaches `series_state`'s
        # `apply_offset` branch -- and the first cut copied `plan.offset_note` onto the row anyway. That
        # printed "El Nino on CME palm oil, NOAA ONI for 2026-08-31: +0.98 degC ... read at a declared
        # six-month offset" with the SOY board's own level, z, run and percentile beside a note claiming
        # a shift nobody performed, which is bar B7's claim ("the palm row's own level, z and run are
        # computed on the shifted series") failing on the fixture that exists to hold it. The slice is
        # `feeders`' own (`values[:-n], dates[:-n]`), and where the history is no longer than the offset
        # the row says the offset was NOT applied, in that producer's own words.
        cadence = plan.cadence or "monthly"
        vals, dates = list(spec["values"]), list(spec["dates"])
        note = plan.offset_note
        n_off = int(plan.offset_months or 0)
        if plan.apply_offset and n_off and cadence == "monthly":
            if len(vals) > n_off:
                vals, dates = vals[:-n_off], dates[:-n_off]
            else:
                note = (f"a declared {n_off}-month offset is NOT applied: the fetched history is "
                        f"{len(vals)} monthly periods, no longer than the offset")
        elif n_off and plan.apply_offset:
            note = (f"a declared {n_off}-month offset is NOT applied on a {cadence} card: the shift "
                    f"is declared in months")
        st = state_from_arrays(
            plan.key.ref, vals, dates, cadence=cadence,
            asof=asof, commodity=plan.key.commodity, country=plan.key.country,
            unit=spec.get("unit", ""), narrate_unit=spec.get("narrate_unit", ""),
            convention=conv.get(plan.key.ref), table=plan.table, metric=plan.metric)
        st.context_only = bool(plan.context_only)
        st.offset_months = n_off
        st.alias_ref = plan.alias_ref
        st.offset_note = note
        st.reads = 1
        return st, 1
    return _fn


def fixture_tape(slug: str, asof: str, *, contract_month: str = "2026-11") -> TapeState:
    """The anchor's SB-T row assembled from a fixture session series.

    IT IS NOT A SECOND PRODUCER. ``feeders.tape_state`` owns the SERVED path -- the front-expiry rule,
    the same-contract filter and the read's own decline words -- and this builder runs only its
    ARITHMETIC HALF (the four same-contract changes and the level's percentile) through the same
    registry entries, on rows this file states. The read half is graded in-VPC at S4."""
    dates = _session_dates("2026-09-04", 320)
    seed = {"soybeans_cbot": 149, "malaysian_crude_palm_oil_cme": 151}.get(slug, 157)
    base = {"soybeans_cbot": 1040.0, "malaysian_crude_palm_oil_cme": 4180.0}.get(slug, 500.0)
    unit = {"soybeans_cbot": "USc/bu", "malaysian_crude_palm_oil_cme": "MYR/t"}.get(slug, "USD/t")
    vals = [round(base * (1.0 + 0.06 * v), 2) for v in _lcg(seed, len(dates))]
    t = TapeState(slug=slug, asof=asof, level=vals[-1], level_date=dates[-1],
                  contract_month=contract_month, unit=unit,
                  coverage={"n_obs": len(vals), "history_start": dates[0], "history_end": dates[-1],
                            "truncated": False},
                  window_note=f"{len(vals)} sessions on {contract_month}, {dates[0]} to {dates[-1]}")
    key = f"{slug}|{contract_month}"
    bundle = {key: {"values": vals, "dates": dates, "unit": unit}}
    for w in (1, 5, 21, 63):
        label = f"{w} {'session' if w == 1 else 'sessions'}"
        ch, rec = TR.run_transform("window_change", bundle, key=key,
                                   params={"t1": -(w + 1), "t2": -1, "window_label": label})
        t.derivation.append(rec)
        t.changes.append({"window": label, "n_periods": w, "declined": ch["declined"],
                          "reason": ch.get("reason"), "from_date": dates[-(w + 1)],
                          "to_date": dates[-1], "delta": ch.get("value"),
                          "pct": ch.get("pct_change")})
    p, rec = TR.run_transform("percentile", bundle, key=key)
    t.derivation.append(rec)
    t.percentile = p
    t.inputs = bundle
    return t


def fixture_benchmark_fn():
    arrays = _benchmark_arrays()

    def _fn(contract):
        return arrays.get(contract)
    return _fn


# ---------------------------------------------------------------------------------------------------
# THE THREE SCENARIOS
# ---------------------------------------------------------------------------------------------------
#: THE EVENT DATE IS INSIDE ITS OWN BAND AT THE AS-OF, deliberately. `biodiesel_mandate` declares a
#: zero-to-two-quarter lag, so an event dated 2026-05-01 has a window open until about 2026-11-01 and the
#: row is LOUD BY CONSTRUCTION (sec 3.2) -- which is the branch scenario 3 exists to exercise. A January
#: date closes the window before the as-of and the row reaches the loud set only through the rank, so the
#: fixture would grade the wrong half of the design.
B40_DATE = "2026-05-01"

#: Scenario 3's receipts. TWO of them exist to hold bar B18: the EVENT itself (event date D, published
#: D + 1) and an ANALYSIS PIECE published D + 30 carrying the SAME event date -- the row must anchor at
#: D and never at D + 30. The third carries an ``event_date`` AFTER the as-of, so it can never anchor and
#: is a kind-5 WATCH candidate instead.
B40_RECEIPTS: tuple = (
    {"date": "2026-05-02", "source": "Indonesia Ministry of Energy", "tier": 1,
     "event_date": B40_DATE, "event_date_precision": "day",
     "text": "the blend mandate moved to a forty percent palm basis on the first of May"},
    {"date": "2026-05-31", "source": "trade press", "tier": 3, "event_date": B40_DATE,
     "event_date_precision": "month",
     "text": "a review of the mandate step and what it does to exportable supply"},
    {"date": "2026-08-20", "source": "Indonesia Ministry of Finance", "tier": 1,
     "event_date": "2026-11-15", "event_date_precision": "day",
     "text": "the levy reference price is reset on a monthly cycle and the next review is dated"},
)


def build_scenario(name: str, *, graph=None) -> dict:
    """Build ONE scenario end to end and return everything the printers and the decks read."""
    from leviathan.graphrag import graph as G
    g = graph if graph is not None else G.CausalGraph(G.load_contracts(), silver=set(),
                                                      version="harness")
    if name == "soybeans_now":
        anchors = W.resolve_anchors(named=("soybeans_cbot",))
        question = ("what is the situation on soybeans now? how is it looking 3 months from now?")
        mode, receipts = "max", {}
    elif name == "el_nino_fanout":
        anchors = W.resolve_anchors(named=("soybeans_cbot",))
        # THE QUESTION DOES NOT NAME PALM. That is the bar: the fan-out has to surface it.
        question = "El Nino is developing: what does it do to soybeans?"
        mode, receipts = "deep", {}
    elif name == "b40_event":
        anchors = W.resolve_anchors(attached_event="malaysian_crude_palm_oil_cme")
        question = "Indonesia raised the biodiesel mandate to B40: what does it do, and to whom?"
        mode = "max"
        receipts = {("malaysian_crude_palm_oil_cme", "biodiesel_mandate"): list(B40_RECEIPTS)}
    else:
        raise KeyError(f"unknown scenario {name!r}; the three are {SCENARIOS}")

    kn = B.board_knobs_of(mode)
    bd = W.walk(graph=g, asof=ASOF, mode=mode, anchors=anchors, question=question,
                state_fn=fixture_state_fn(ASOF), key_fn=None, receipts=receipts,
                knobs=kn, width=2, legb_on=False)

    tape = {slug: fixture_tape(slug, ASOF) for slug in bd.anchor_slugs}
    R.attach_tape(bd, tape, reads_each=0)
    bd.stamp("tape", "fired" if tape else "not_reached")

    ana = A.analog_rows(bd, knobs=kn, benchmark_fn=fixture_benchmark_fn(),
                        receipt_fn=None)
    if name == "b40_event":
        row = bd.row("malaysian_crude_palm_oil_cme", "biodiesel_mandate")
        if row is not None:
            ev = A.event_analogs(row, asof=ASOF, band=row.lag_band)
            ana.append({"contract": row.contract, "driver_id": row.driver_id, "band": row.lag_band,
                        "asof": ASOF, "declined": ev["declined"], "n_candidates": len(ev["dates"]),
                        "floor_year": "the record's own start", "price_dims": 0})
    A.analog_leg(bd, ana)

    wr = WA.watch_rows(bd, analogs=ana)
    WA.watch_leg(bd, wr)

    ages = {}
    for r in bd.rows:
        st = r.state
        if st is None or status_word(st.status) != "ok":
            continue
        c = N.age_clause(st.knowledge_date, bd.asof, st.cadence)
        if c:
            ages[r.key] = c
    rec = N.recency_rows(bd, tape_edge=next((t.level_date for t in tape.values() if t.level_date), ""))
    blk = R.render_board(bd, analogs=ana, watch=wr, recency=rec, age_clauses=ages,
                         anchor_label=", ".join(R.board_label(s) for s in bd.anchor_slugs))
    bd.stamp("render", "fired" if not blk.trips else "declined",
             reason="template_register_trip" if blk.trips else "")
    return {"name": name, "board": bd, "analogs": ana, "watch": wr, "block": blk, "tape": tape,
            "recency": rec, "mode": mode, "question": question, "knobs": kn}


# ---------------------------------------------------------------------------------------------------
# THE SLOT AUDIT (sec 0.3) -- every brace stamped served | absence:<reason> | receipt
# ---------------------------------------------------------------------------------------------------
def slot_audit(ctx: dict) -> list:
    """Every slot of the scenario's target answer, stamped from the BOARD rather than from prose.

    THE STAMP IS DERIVED, NEVER DECLARED. A hand-written "served" beside a slot would be exactly the
    thing the design's own slot audit exists to stop: four slots revision 1 wrote as figures had no
    producer at HEAD, and the only way to know is to ask the built board."""
    bd = ctx["board"]
    out: list = []

    def _row_stamp(slot, contract, driver_id, *, want="series"):
        r = bd.row(contract, driver_id)
        if r is None:
            out.append((slot, "absence:child_uncovered"))
            return None
        st = r.state
        if st is None:
            out.append((slot, f"absence:{r.coverage_tier}"))
            return r
        if status_word(st.status) == "ok":
            out.append((slot, "served" if want == "series" else want))
            return r
        n = (r.receipts or {}).get("n") or 0
        out.append((slot, f"receipt:{n} dated" if n else f"absence:{status_word(st.status)}"))
        return r

    anchor = bd.anchor_slugs[0] if bd.anchor_slugs else ""
    if ctx["name"] in ("soybeans_now", "el_nino_fanout"):
        _row_stamp("ONI state (level, z, percentile, run)", "soybeans_cbot", "El_Nino")
        _row_stamp("balance sheet (the stocks-to-use ratio)", "soybeans_cbot",
                   "psd_ending_stock_su_ratio")
        _row_stamp("weekly export sales", "soybeans_cbot", "export_pace_lag")
        _row_stamp("positioning (context only)", "soybeans_cbot", "cot_mm_positioning")
        _row_stamp("China import tariff", "soybeans_cbot", "China_import_tariff")
        _row_stamp("crude oil (the upstream seed)", "soybeans_cbot", "crude_oil")
        far = [f for e in bd.fan if e["driver_id"] == "El_Nino"
               for f in e["far"] if f["contract"] == "malaysian_crude_palm_oil_cme"]
        out.append(("palm's own sign and band on the same ONI state",
                    f"served:{far[0]['sign']} {far[0]['lag']}" if far else "absence:child_uncovered"))
    if ctx["name"] == "b40_event":
        r = _row_stamp("the B40 EVENT row", "malaysian_crude_palm_oil_cme", "biodiesel_mandate")
        out.append(("the event's own date",
                    f"receipt:{r.event_date}" if (r is not None and r.event_date)
                    else "absence:no_policy_date"))
        _row_stamp("the export levy (upstream)", "malaysian_crude_palm_oil_cme", "CPO_export_levy")
        _row_stamp("MPOB closing stocks", "malaysian_crude_palm_oil_cme", "ending_stocks")
        _row_stamp("crude oil (the convergence member)", "malaysian_crude_palm_oil_cme",
                   "crude_oil_price")
        _row_stamp("the gasoil-palm spread", "malaysian_crude_palm_oil_cme", "gasoil_palm_spread")
        conv = [c for c in bd.convergence if c["name"] == "biodiesel_energy_floor"]
        out.append(("the biodiesel energy floor, as ordering words",
                    f"served:{conv[0]['n_matched']} of {conv[0]['n_declared']}" if conv
                    else "absence:child_uncovered"))
    tp = bd.tape.get(anchor)
    out.append(("the price path (SB-T)",
                "served" if (tp is not None and status_word(tp.status) == "ok")
                else f"absence:{tp.status if tp is not None else 'no_tape_slug'}"))
    fired = [a for a in ctx["analogs"] if not a.get("declined")]
    out.append(("the like-state stanza",
                f"served:{len(fired)} stanzas" if fired
                else f"absence:{(ctx['analogs'][0]['declined'] if ctx['analogs'] else 'no_like_state')}"))
    out.append(("the outcome over the band at both ends",
                "served" if any(o for a in fired for o in (a.get("outcomes") or ())
                                if not o.get("declined")) else "absence:horizon_open"))
    out.append(("the analog's own documents",
                "receipt" if any(a.get("receipts") for a in fired) else "absence:no_receipt"))
    # DATED MEANS CARRYING A DATE. The first cut counted every non-declined watch row as "dated", and
    # the kind-2 rows carry a FIGURE and no date at all -- so "served:8 dated" on scenarios 1 and 3 was
    # really six dated plus two figures. A slot audit that overstates its own stamp is the one thing the
    # audit exists to stop.
    dated = sum(1 for w in ctx["watch"] if not w.get("declined") and (w.get("dates") or ""))
    levels = sum(1 for w in ctx["watch"] if not w.get("declined") and w.get("call"))
    out.append(("the watch list",
                f"served:{dated} dated, {levels} naming a declared level"
                if ctx["watch"] else "absence:no_calendar_rule"))
    out.append(("the recency ledger", "served" if ctx["recency"] else "absence:read_empty"))
    return out


# ---------------------------------------------------------------------------------------------------
# THE MEASUREMENT (sec 7) -- rows and tokens per class
# ---------------------------------------------------------------------------------------------------
def measure(ctx: dict) -> dict:
    """Rows and CHARACTERS-OVER-FOUR per row class, plus the block total.

    CHARS/4 IS THE STATED ESTIMATOR and it is stated because the delta pass found the design's own
    token assumption off by about a factor of two on projection lines. It is an estimator, not a count:
    the arm measures the real thing with the writer's own tokeniser, and this number's job is to make a
    class that has quietly doubled visible before it gets there."""
    blk = ctx["block"]
    per: dict = {}
    for line, classes in zip(blk.lines, blk.classes):
        name = classes[0] if len(classes) == 1 else ("UNCLASSIFIED" if not classes else
                                                     "AMBIGUOUS:" + "/".join(classes))
        e = per.setdefault(name, {"rows": 0, "chars": 0})
        e["rows"] += 1
        e["chars"] += len(line)
    total_chars = sum(len(x) for x in blk.lines) + max(0, len(blk.lines) - 1)
    return {"per_class": per, "rows": len(blk.lines), "chars": total_chars,
            "tokens_est": round(total_chars / 4.0), "calls": len(blk.calls),
            "trips": len(blk.trips)}


# ---------------------------------------------------------------------------------------------------
# THE CLI
# ---------------------------------------------------------------------------------------------------
def _p(s: str = "") -> None:
    """ASCII-ONLY STDOUT BY LAW (the Windows console is cp1252); the files stay UTF-8."""
    sys.stdout.write(str(s).encode("ascii", "backslashreplace").decode("ascii") + "\n")


def print_scenario(ctx: dict, *, show_block: bool = True) -> None:
    bd = ctx["board"]
    _p("=" * 100)
    _p(f"SCENARIO {ctx['name']}  mode={ctx['mode']}  asof={bd.asof}  "
       f"anchors={','.join(bd.anchor_slugs) or 'none'} ({bd.anchor_source})")
    _p(f"QUESTION: {ctx['question']}")
    _p(f"rows={len(bd.rows)}  series={len(bd.series)}  reads={bd.net_reads()}/{bd.declared_cap()}  "
       f"horizon_months={bd.horizon_months}  rectangle={bd.rectangle() or 'closed'}")
    _p("-" * 100)
    if show_block:
        for line in ctx["block"].lines:
            _p(line)
        _p("-" * 100)
    _p("SLOT AUDIT (sec 0.3): every brace stamped served | absence:<reason> | receipt")
    for slot, stamp in slot_audit(ctx):
        _p(f"  {slot:<52} {stamp}")
    _p("-" * 100)
    m = measure(ctx)
    _p(f"MEASUREMENT  rows={m['rows']}  calls={m['calls']}  chars={m['chars']}  "
       f"tokens_est(chars/4)={m['tokens_est']}  register_trips={m['trips']}")
    for name in sorted(m["per_class"]):
        e = m["per_class"][name]
        _p(f"  {name:<16} rows={e['rows']:<4} chars={e['chars']:<6} tokens_est={round(e['chars'] / 4.0)}")
    _p("-" * 100)
    _p("LEGS (sec 6.7)")
    for leg in sorted(bd.legs):
        r = bd.legs[leg]
        _p(f"  {leg:<12} {r['outcome']:<12} {r.get('reason') or ''}")
    _p("")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m leviathan.graphrag.state",
                                 description="the state board's offline harness (no reads, no clock)")
    ap.add_argument("scenario", nargs="?", default="all", choices=("all",) + SCENARIOS)
    ap.add_argument("--no-block", action="store_true", help="print the audits without the block")
    args = ap.parse_args(argv)
    names = SCENARIOS if args.scenario == "all" else (args.scenario,)
    from leviathan.graphrag import graph as G
    g = G.CausalGraph(G.load_contracts(), silver=set(), version="harness")
    rc = 0
    for name in names:
        ctx = build_scenario(name, graph=g)
        print_scenario(ctx, show_block=not args.no_block)
        if ctx["block"].trips:
            rc = 1
        if ctx["board"].rectangle():
            rc = 1
    _p(f"harness: {len(names)} scenario(s), exit {rc}")
    return rc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
