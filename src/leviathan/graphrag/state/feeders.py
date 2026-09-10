"""THE BOARD'S TWO FEEDERS -- STATE ENGINE DESIGN sec 2.1 (numeric) and 2.2 (text), sitting S1.

  * :func:`series_state` -- silverleg's read shape WIDENED to every served ``cascade_map`` ref: one
    PIT-guarded read through ``query.run``, one cross-section collapse through the SHIPPED
    ``cascade._pace_series``, the transforms of sec 2.5 over the result, and one :class:`StateRow` out.
  * :func:`tape_state` -- the ANCHOR board's own SB-T price path: one ``silver_futures_eod`` read, the
    front settle named by the shipped roll rule, the four SAME-CONTRACT session changes and the level's
    percentile over the window that read fetched (sec 6.2, D19).
  * :func:`text_state` -- the node's ALREADY-FETCHED receipts, ranked by recency and specificity, with
    the summary a node row carries. ZERO new retrieval in V1 phase 1b (sec 2.2).

WHY NOT INSIDE ``silverleg.py``. Its outputs are consumed by ``planner.ground`` and
``firing.fire_contract`` and pinned by ``tests/unit/test_silverleg.py``; widening ``_HANDLERS`` would
change ``servable_refs()`` and with it WHAT THE HEATMAP FIRES ON. silverleg stays byte-identical (owner
decision 8: no re-point in this arc). This module IMPORTS its cache idioms and treats its three handlers
as reference constructions.

WHY THIS MODULE MAY IMPORT FROM ``cascade.py`` WHILE THE K9 LANE HOLDS IT. Importing a public surface is
a READ, not an edit -- ``cascade_census.py`` does exactly this. The imported-name list is PINNED as
:data:`CASCADE_IMPORTS` and asserted at import time by :func:`check_cascade_imports`, so a rename in that
file reds at IMPORT rather than at serve.

FOUR READ RULES, each measured rather than assumed (sec 2.1):
  1. ``query.run`` DIRECTLY, never ``cascade.fetch_window`` -- which takes no ``limit`` and turns a
     window-less call into a whole-history read. ``silver_fred_fx`` is 5,538 daily rows, 538 over the
     5,000 cap, and under the default ASC order the cap keeps the OLDEST rows: a "now" printed from a
     mid-2024 FX session.
  2. an EXPLICIT ``period_start`` per cadence and an explicit ``limit``, with
     ``futures_newest_first=NEWEST_FIRST_ALL`` so a cap that still bites keeps the NEWEST rows.
  3. ``len(rows) == limit`` is the TRUNCATION DETECTOR and declines ``history_truncated:<limit>`` BY
     NAME -- a silently truncated history is a z against the wrong window.
  4. ``ym_lag=True`` on every board read from day one: a ``year_month`` card admits its data month from
     the month's FIRST DAY otherwise, and the board's reads are its own to correct (sec 1.4, D21).
  5. a declared ``same_series_as`` reads the BASE ref's own metric and shifts THAT array by
     ``offset_months`` -- never the alias's already-lagged column with the shift applied a second time.
     The alias's column IS the base shifted (``oni_lag6 = oni_anom.shift(6)``), so reading it and
     shifting again doubles the lag AND pays a second read of the one series the fold exists to share.
     :func:`_resolve_same_series` owns the rule and the fence that makes it safe, and the memo's READ
     layer (:func:`series_read_key`) is what makes the shared array cost nothing: the alias and its base
     are two STATES of one series, so they miss the state layer by design and hit the read layer.

THE pg REQUIREMENT (sec 2.1). Athena's planning floor is ~2-3 s per query, so a 60-read board on Athena
is a two-minute wall. Board reads go through ``pgnumbers.pg_query`` under the board's OWN counter and
decline ``pool_exhausted`` / ``pg_timeout`` BY NAME -- never through ``query_fn``, whose per-request
Athena fallback re-runs the same series SQL at that floor and logs a warning naming no caller. The
executor is INJECTED (:func:`board_query_fn`, :func:`fixture_query_fn`), so tests, the offline harness
and the censuses need no environment at all.

ASCII-ONLY on anything this package PRINTS (the Windows console is cp1252); the files stay UTF-8.
"""
from __future__ import annotations

import copy
import datetime as _dt
import functools
import math as _math
import os
import threading
import time
from typing import Any, NamedTuple, Optional

from leviathan.graphrag.state import transforms as TR
from leviathan.graphrag.state.rows import (
    COVERAGE_TIERS,
    SIGN_WORDS,
    STATUS_WORDS,
    TAPE_STATUS_WORDS,
    Receipt,
    SeriesKey,
    StateRow,
    TapeState,
    TextState,
    coverage_tier,
    status_word,
)

# ---------------------------------------------------------------------------------------------------
# THE PINNED CASCADE SURFACE (sec 2.1, critic G21)
# ---------------------------------------------------------------------------------------------------
#: Every name this package reads out of ``numbers/cascade.py``. Declared ONCE, here, and asserted at
#: import time: the K9 lane has moved lines inside that file repeatedly, and a rename must red at import
#: rather than at serve. This is a READ of a public surface -- the board edits none of the five held
#: files (``cascade_census.py`` reads the same way, for the same reason).
CASCADE_IMPORTS: tuple[str, ...] = (
    "load_map", "map_row", "load_region_map",     # the map, and the region resolver's own accessor
    "SKIP_NODE", "_scope_ex", "_region_row",      # scope resolution, WITH the resolver's own reason word
    "_pace_series", "_pace_front_expiry",         # the SHIPPED cross-section collapse
    "_PACE_COLLAPSE", "POSITIONING_TABLES",       # the collapse table, and positioning's own roster
)


def check_cascade_imports() -> list[str]:
    """Every name in :data:`CASCADE_IMPORTS` resolves in ``numbers/cascade.py``. Returns the missing
    ones; empty == clean. Run at import (below) and pinned by ``tests/unit/test_state_feeders.py``."""
    from leviathan.graphrag.numbers import cascade as casc
    return [n for n in CASCADE_IMPORTS if not hasattr(casc, n)]


def _casc():
    """The cascade module, imported LAZILY. cascade.py is a large module with its own import graph, and
    this package is imported by lint and by tests that never fetch a row."""
    from leviathan.graphrag.numbers import cascade as casc
    return casc


# ---------------------------------------------------------------------------------------------------
# THE BOARD'S OWN MAP ACCESSOR (sec 2.1 step 1; D23)
# ---------------------------------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def board_map() -> dict:
    """Every ``refs`` row the BOARD may read: the rows live for the cascade PLUS the rows carrying BOTH
    ``deferred: true`` and ``board_read: true``.

    A SECOND READER OF ONE FILE, and the precedent is the estate's own: ``cascade.load_region_map`` exists
    because ``load_map()`` returns the refs block only, "so the region resolver and the config lint cannot
    piggyback it". The same is true here for the opposite reason -- ``load_map`` FILTERS the deferred rows
    by construction ("a row flagged deferred: true is inert: never returned to the seam"), which is
    exactly the property that keeps a board-only row dark to the serving cascade.

    WHY THE PAIR OF KEYS RATHER THAN A PLAIN ROW (D23, and it is measured): a present, non-deferred row
    turns every grounded instance of its ref into a LIVE cascade leg on the first image built from the
    tree, displacing legs under ``cascade.cap: 12`` by walk order -- with no flag, no arm and no golden.
    ``deferred: true`` keeps the cascade blind; ``board_read: true`` is a key only this accessor honours;
    and DROPPING the deferral is a CASCADE change that ships as its own commit under the estate's
    un-defer gate, never inside a board commit."""
    import yaml

    from leviathan.graphrag import extract as ex
    p = ex._CFG / "numbers" / "cascade_map.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    out: dict = {}
    for ref, row in ((doc or {}).get("refs") or {}).items():
        r = row or {}
        if not r.get("deferred") or r.get("board_read"):
            out[ref] = r
    return out


def board_map_row(ref: str) -> Optional[dict]:
    """The board's map row for a ref, or ``None`` -> the row's status is ``unmapped_ref`` at ZERO reads.

    ``cascade.map_row`` is consulted for the LABEL only and KEEPS returning ``None`` for these rows: the
    drop site's ``if row is None`` test, ``cascade_census`` and every ``_load_map`` reader depend on that
    contract, so the board labels ``unmapped_ref`` in its OWN code rather than changing map_row's."""
    return board_map().get(ref or "")


def board_read_refs() -> tuple[str, ...]:
    """The refs the board reads that the CASCADE cannot see -- the dark half of phase 1a, by name."""
    return tuple(sorted(r for r, row in board_map().items() if (row or {}).get("board_read")))


# ---------------------------------------------------------------------------------------------------
# THE CADENCE TABLES (sec 2.1's declared-windows table)
# ---------------------------------------------------------------------------------------------------
#: The CHANGE windows per cadence, in the cadence's own periods. The design's table, verbatim. Every
#: rendered change names its window in the cadence's noun; a window the fetched history cannot fill
#: DECLINES by name and the row prints the declined windows as words.
CADENCE_CHANGE_WINDOWS: dict[str, tuple[int, ...]] = {
    "daily": (1, 5, 21, 63, 252),
    "weekly": (1, 4, 13, 52),
    "weekly_destination": (1, 4, 13, 52),
    "biweekly": (1, 2, 12),
    "monthly": (1, 3, 12),
    "annual": (1, 5),
    "release": (1,),
}

#: The fallback z / percentile history window per cadence, used when ``state_conventions.yaml``'s own
#: ``windows:`` block is not supplied. The CONFIG WINS where it is passed -- the table is a config
#: (sec 2.1) and this is the shape of it, not a second copy of the numbers.
CADENCE_HISTORY_WINDOW: dict[str, int] = {
    "daily": 250,          # sessions -- one trading year (params.yaml serving.stats.futures_z 250)
    "weekly": 156,         # weeks -- three years
    "weekly_destination": 52,   # weeks, AFTER the per-week SUM: a 156-week z at the destination grain
    #                             needs a SQL per-week-SUM branch in build_sql, which is V1.1, never a
    #                             whole-history read. The row prints "52 weeks" and means it.
    "biweekly": 78,        # fortnights -- three seasons
    "monthly": 120,        # months -- the ten-year idiom (silverleg window_years: 10)
    "annual": 10,          # marketing years
    "release": 0,          # revision_count over vintages; NO z
}

#: THE PUBLICATION SLACK per cadence, in the cadence's OWN periods -- the FIFTH read rule, and it was
#: measured rather than reasoned. A read span that EQUALS the history window cannot fill that window:
#: the span is measured from the AS-OF and the newest KNOWABLE period sits a publication lag behind it,
#: so the array comes back short by the lag and the rolling z -- a population z over exactly ``window``
#: points ending at the last point -- declines every turn, for good.
#:
#: MEASURED IN-VPC (board census run #3, job 72fd69e3, the pg mirror at as-of 2026-09-07). ONI's read
#: spanned 120 months and returned 117: 2016-09 to 2026-05, the newest month the mirror carried. The z
#: declined ``history has 117 points, window needs 120`` on all 32 rendered ONI rows, and the row still
#: printed a percentile (floor 8) and a run beside the refusal -- a standing that is refused while two
#: neighbouring measures compute is the tell. 86 rendered rows across 144 board runs carried it, and
#: EVERY ONE sat on a cadence whose span equalled its window: ONI 32, gold_weather_z 25, IOD 12, COT 12,
#: ESR 5. No daily row and no annual row did -- daily reads 5 years for a 250-session window and annual
#: reads the whole history.
#:
#: EACH NUMBER, AND WHAT IT COVERS. The lags are the registry's own declarations, read at this landing:
#:   * monthly 12 -- the MEASURED worst monthly frontier on run #3 was ONI at 2026-05, 4.24 months
#:     behind the as-of, and the worst DECLARED monthly lag is 45 DAYS AFTER MONTH-END (``silver_noaa_iod``
#:     ym_publication_lag_days 45; ``silver_fnc_colombia_monthly`` / ``silver_unica_monthly_ethanol_sales``
#:     publication_lag_days 45), which costs two data months, PLUS a stale mirror: ONI's own lag is 36
#:     days and the mirror still stopped at 2026-05 rather than the PIT-knowable 2026-06, so two more
#:     months. Twelve is that worst case with room, and the cost of the room is rows, not correctness.
#:   * weekly 8 -- worst declared weekly lag 13 days (``silver_fgis``, MEASURED worst case), COT 6; two
#:     weeks of lag plus six of a stale mirror, against a COT frontier measured 1.86 weeks behind the
#:     as-of on run #3.
#:   * weekly_destination 6 -- and this one is a MEASURED CHOICE BETWEEN TWO FAILURES, not a default.
#:     The MEASURED worst frontier on this grain is corn's ESR week 2026-08-06 at as-of 2026-09-07 --
#:     32 days, 4.57 weeks -- so a 4-week slack lands EXACTLY on 52 points for a 52-week window: one
#:     week staler and the standing refuses again. Against that, this grain reads one row per
#:     destination per week and is the only family where the 5,000-row cap is anywhere near: the
#:     destination probe counted ``grain_sorghum`` at 4,293 ESR rows over 52 weeks (707 of headroom,
#:     the tightest series still under the cap), which extrapolates to ~4,789 at 58 weeks (~211 of
#:     headroom) and to ~4,954 at 60 (~46). Six is the widest slack that keeps that headroom in the
#:     hundreds. The asymmetry decides it: a cap that binds is a LOUD, named, self-correcting failure
#:     (``history_truncated:5000`` and the window note rewritten), while a span that binds is silent
#:     and permanent. The durable fix for this grain is the per-week SUM branch in ``build_sql``
#:     (V1.1, already named on ``CADENCE_HISTORY_WINDOW['weekly_destination']``), which removes the
#:     row-count pressure and would let this slack be as generous as monthly's.
#:   * biweekly 4 -- UNICA publishes 14 days after the fortnight (publication_lag_days 14 on both cards):
#:     one fortnight of lag, four of cover.
#:   * daily 10 -- already covered many times over (5 years is ~1,260 sessions against a 250-session
#:     window); the number is declared so the invariant has one rule and no exception.
#:   * annual 1 -- the span is the whole history, so the slack is nominal.
#:   * release 0 -- ``release`` carries NO window (revision counts only), so nothing can be short.
CADENCE_READ_SLACK: dict[str, int] = {
    "daily": 10,               # sessions
    "weekly": 8,               # weeks
    "weekly_destination": 6,   # weeks -- the widest the 5,000-row cap leaves room for on this grain
    "biweekly": 4,             # fortnights
    "monthly": 12,             # months
    "annual": 1,               # marketing years (the span is the whole history anyway)
    "release": 0,              # no window at all
}

#: The READ span per cadence, as (unit, n) -> ``period_start = asof - n units``. ``None`` = read the
#: whole per-(commodity, country) history: a marketing-year card holds ~66 rows, which is nowhere near
#: the cap, and a date bound on a card with no date column prunes nothing anyway.
#:
#: EVERY SPAN EXCEEDS ITS WINDOW BY THAT CADENCE'S SLACK, and :func:`check_read_spans` asserts it at
#: import so the pair can never drift back into equality. The four numbers that MOVED at this landing
#: are monthly 120 -> 132, weekly 156 -> 164, weekly_destination 52 -> 58 and biweekly 78 -> 82
#: fortnights (1,092 -> 1,148 days). ``daily`` and ``annual`` are unchanged and were never short.
CADENCE_READ_SPAN: dict[str, Optional[tuple[str, int]]] = {
    "daily": ("years", 5),                  # ~1,260 sessions for a 250-session window: never short
    "weekly": ("weeks", 156 + 8),
    "weekly_destination": ("weeks", 52 + 6),
    "biweekly": ("days", (78 + 4) * 14),
    "monthly": ("months", 120 + 12),
    "annual": None,                         # the whole history
    "release": None,
}

#: The two DESTINATION-GRAIN cards: one row per destination per week, no world-total code, summed per
#: week by the SHIPPED collapse. Read over 58 weeks -- the window's 52 plus this grain's own 6 weeks of
#: publication slack -- so the per-week rows stay as far under the 5,000 cap as the grain allows.
DESTINATION_GRAIN_TABLES: frozenset[str] = frozenset({"silver_esr", "silver_fgis"})

#: The pink sheet serves its own 5-YEAR z columns; ranking those against a ten-year window would state a
#: window the source did not use. 60 months, and the row says so.
TABLE_HISTORY_WINDOW: dict[str, int] = {"silver_pink_sheet": 60}

#: ``NumberQuery.limit``'s own default, restated as the board's EXPLICIT cap so the truncation detector
#: has a number to compare against rather than a default it inherited.
READ_LIMIT = 5000

#: Periods per year, per cadence -- the ``pace_vs_prior`` parameter. REQUIRED by that leaf: a pace
#: reading whose "prior year" was guessed from the row count is a quiet substitution.
CADENCE_PERIODS_PER_YEAR: dict[str, int] = {
    "daily": 252, "weekly": 52, "weekly_destination": 52, "biweekly": 26, "monthly": 12,
    "annual": 1, "release": 1,
}

#: One period of each cadence, IN DAYS. It is the recency leg's own age-in-periods divisor and it is
#: also what turns a read span declared in one unit into a count of the cadence's OWN periods
#: (:func:`read_span_periods`), which is the only unit the span-vs-window invariant can be stated in.
#: It MOVED here from beside ``_recency`` at the read-span landing: two readers, one cadence table.
CADENCE_DAYS: dict[str, Optional[float]] = {
    "daily": 365.0 / 252.0, "weekly": 7.0, "weekly_destination": 7.0, "biweekly": 14.0,
    "monthly": 365.0 / 12.0, "annual": 365.0, "release": None,
}

#: The days one unit of a READ SPAN is worth. ``CADENCE_READ_SPAN`` declares each span in whatever unit
#: reads naturally for the cadence, and this is the only place that vocabulary is priced.
_SPAN_UNIT_DAYS: dict[str, float] = {"years": 365.0, "months": 365.0 / 12.0, "weeks": 7.0, "days": 1.0}


def read_span_periods(cadence: str, span: Optional[tuple[str, int]] = None) -> Optional[int]:
    """A read span expressed in the CADENCE'S OWN PERIODS. ``None`` == the whole history (unbounded).

    The invariant this exists for cannot be stated in the declared units: ``daily`` declares 5 years and
    is measured against a 250-SESSION window; ``biweekly`` declares 1,148 days and is measured against 82
    FORTNIGHTS. One unit, one comparison, no per-cadence special case at the call site."""
    span = CADENCE_READ_SPAN.get(cadence) if span is None else span
    if not span:
        return None
    unit, n = span
    per = CADENCE_DAYS.get(cadence)
    if not per:
        return None
    return int(_SPAN_UNIT_DAYS.get(str(unit), 1.0) * float(n) / float(per) + 1e-9)


def read_span(cadence: str, window: Optional[int] = None) -> Optional[tuple[str, int]]:
    """The ``(unit, n)`` span a read of this cadence covers, WIDENED where the caller's own window needs
    more than the cadence default does. ``None`` == read the whole history.

    TWO RULES, AND THE SECOND IS THE ONE THE CADENCE TABLE CANNOT KEEP ON ITS OWN. The table above is
    already ``window + slack`` for the cadence's DEFAULT window. But a window is not always the cadence
    default: ``state_conventions.yaml`` lets a series declare its own (``cot_mm_positioning``
    ``history_window: 156``; ``psd_ending_stock_su_ratio`` 10) and ``TABLE_HISTORY_WINDOW`` lets a card
    declare one (``silver_pink_sheet`` 60). Every declared window in the estate today is at or below its
    cadence default, so this branch is a NO-OP on the served path at this landing and the table alone
    carries the fix -- but a series that declared 200 weeks tomorrow would otherwise be read over 164 and
    refuse its own standing for ever, silently, which is the exact defect this landing closes. So the
    span is scaled to whichever window the row will actually be measured over, PLUS that cadence's slack.

    IT ONLY EVER WIDENS. A declared window SHORTER than the cadence default (the pink sheet's 60 months)
    keeps the full 132-month span: a narrower read would save rows nobody is short of and would make the
    span a function of two things instead of one."""
    span = CADENCE_READ_SPAN.get(cadence)
    if span is None:
        return None
    unit, n = span
    have = read_span_periods(cadence, span) or 0
    need = int(window or 0) + int(CADENCE_READ_SLACK.get(cadence, 0))
    if have > 0 and need > have:
        n = int(_math.ceil(float(n) * float(need) / float(have)))
    return (str(unit), int(n))


def check_read_spans(windows: Optional[dict] = None, conventions: Optional[dict] = None) -> list[str]:
    """Every cadence that carries a history window reads a span LONGER than that window by its own
    publication slack. Returns the problems by name; empty == clean.

    IT IS ASSERTED AT IMPORT over the module's own tables (below), and the deck runs it a second time
    with the CONFIG's ``windows:`` block and the per-series ``history_window`` declarations threaded in
    -- the config_check shape, in the one place that can read the config without making this module
    import yaml on every consumer's behalf.

    ``release`` is exempt BY NAME rather than by falling through a zero: it declares no window at all
    (revision counts only), and a cadence that measures nothing cannot be measured over too little."""
    problems: list[str] = []
    for cadence, win in sorted(CADENCE_HISTORY_WINDOW.items()):
        if not win:
            continue                                       # `release`: no window, nothing to fill
        span = CADENCE_READ_SPAN.get(cadence)
        if span is None:
            continue                                       # the whole history is never short
        slack = int(CADENCE_READ_SLACK.get(cadence, -1))
        if slack < 0:
            problems.append(f"cadence {cadence!r} declares a read span and a window but NO slack")
            continue
        have = read_span_periods(cadence, span)
        if have is None:
            problems.append(f"cadence {cadence!r} declares span {span!r} that cannot be priced in "
                            f"its own periods (no CADENCE_DAYS entry)")
            continue
        if have < int(win) + slack:
            problems.append(f"cadence {cadence!r}: read span is {have} periods, window {int(win)} + "
                            f"slack {slack} needs {int(win) + slack}")
    # THE CARD-LEVEL AND SERIES-LEVEL WINDOWS, checked against the span the READ would actually take --
    # `read_span` widens, so this can only fail where the widening itself is unavailable (a cadence with
    # no span at all is exempt above, and a `None` span is unbounded).
    declared: list[tuple[str, str, int]] = []
    for table, win in sorted(TABLE_HISTORY_WINDOW.items()):
        # A CARD OVERRIDE IS CHECKED AGAINST EVERY CADENCE, and that is not laziness: this module does
        # not know a table's cadence without the registry (``cadence_of`` takes a TableSpec), and a
        # window that must hold whatever cadence the card turns out to carry is the stronger claim.
        for cad in sorted(CADENCE_READ_SPAN):
            declared.append((f"table {table!r} on cadence {cad!r}", cad, int(win)))
    for ref, row in sorted((conventions or {}).items()):
        w = (row or {}).get("history_window")
        if w is None:
            continue
        key = str((row or {}).get("history_window_key") or "monthly")
        cad = key if key in CADENCE_READ_SPAN else "monthly"
        declared.append((f"series {ref!r}", cad, int(w)))
    for base in sorted(windows or {}):
        cad = str(base)
        if cad in CADENCE_READ_SPAN:
            declared.append((f"config windows.{base}", cad, int((windows or {})[base])))
    for who, cad, win in declared:
        span = read_span(cad, win)
        if span is None:
            continue
        have = read_span_periods(cad, span)
        slack = int(CADENCE_READ_SLACK.get(cad, 0))
        if have is not None and have < win + slack:
            problems.append(f"{who}: declared window {win} on cadence {cad!r} reads {have} periods, "
                            f"needs {win + slack}")
    return problems


def cadence_of(ts, table: str) -> str:
    """The board's cadence word for a card: ``TableSpec.cadence``, with the destination-grain split of
    ``weekly`` applied. A cadence the board does not know falls back to ``monthly`` and the row says so
    through its ``window_note`` -- an unknown cadence is a config finding, never a silent zero window."""
    c = (getattr(ts, "cadence", "") or "").strip().lower()
    if c == "weekly" and table in DESTINATION_GRAIN_TABLES:
        return "weekly_destination"
    return c if c in CADENCE_CHANGE_WINDOWS else "monthly"


def history_window(cadence: str, table: str, windows: Optional[dict] = None) -> int:
    """The z / percentile window for one card. Order: the card's own override, then the CONFIG's
    ``windows:`` block (state_conventions.yaml), then the cadence table above."""
    if table in TABLE_HISTORY_WINDOW:
        return TABLE_HISTORY_WINDOW[table]
    if windows:
        base = "weekly" if cadence == "weekly_destination" else cadence
        if cadence == "weekly_destination":
            return CADENCE_HISTORY_WINDOW[cadence]        # the destination grain's own 52, never the 156
        if base in windows:
            return int(windows[base])
    return CADENCE_HISTORY_WINDOW.get(cadence, 0)


def _period_start(asof: str, cadence: str, window: Optional[int] = None) -> Optional[str]:
    """``asof - read_span`` as an ISO day, or ``None`` for a whole-history read.

    ``window`` is the window this row will be MEASURED over, and it is threaded rather than looked up
    so the read is bounded by what the caller will actually compute (:func:`read_span`'s second rule)."""
    span = read_span(cadence, window)
    if not span:
        return None
    unit, n = span
    d = _dt.date(int(asof[:4]), int(asof[5:7]), int(asof[8:10]))
    if unit == "years":
        try:
            d = d.replace(year=d.year - n)
        except ValueError:                                # 29 Feb -> 28 Feb; a day, on a five-year span
            d = d.replace(year=d.year - n, day=28)
    elif unit == "months":
        y, m = d.year, d.month - n
        while m <= 0:
            y, m = y - 1, m + 12
        d = _dt.date(y, m, 1)
    elif unit == "weeks":
        d = d - _dt.timedelta(days=7 * n)
    else:
        d = d - _dt.timedelta(days=n)
    return d.isoformat()


# ---------------------------------------------------------------------------------------------------
# THE MEMO (sec 1.1) -- silverleg's key generalised, plus two terms, under an LRU bound.
# ---------------------------------------------------------------------------------------------------
_SHARED: "dict[tuple, tuple[Any, Optional[float]]]" = {}
_ORDER: list = []                                    # insertion order for the LRU eviction
_LOCK = threading.Lock()

#: The bound. silverleg's shared cache holds SCALAR verdicts; this one holds whole ARRAYS, and an eval
#: deck at fixed as-ofs or the offline harness would otherwise grow it without limit -- an immortal
#: entry (a historical as-of) never expires on its own.
STATE_CACHE_MAX = 512


def mirror_epoch() -> str:
    """The MIRROR EPOCH term of the memo key (sec 1.1).

    The pg mirror is a DISPOSABLE derived index rebuilt any time (``load_pg_numbers`` re-loads it), and a
    vintage backfill -- ESR streaming, the pink-sheet vintages flip -- changes WHICH print the collapse
    picks for a PAST as-of. A historical entry is immortal, so without this term one process could serve
    a pre-backfill array forever. MEASURED at this landing: ``load_pg_numbers`` writes no load-manifest
    id, so the epoch is the PROCESS START TIME -- a deploy clears the cache and a backfill does not,
    which is exactly silverleg's own situation (``_SHARED`` is process-local). When the loader gains a
    manifest id this function reads it and the fallback stays as the fallback."""
    return _PROCESS_EPOCH


_PROCESS_EPOCH = f"pid{int(time.time())}"


def state_cache_key(key: SeriesKey, asof_s: str, read_shape: str, params_hash: str,
                    offset_months: int = 0, alias_ref: str = "") -> tuple:
    """``(ref, scope, asof, read_shape, transform_params_hash, mirror_epoch)`` -- silverleg's four terms
    (``make_silver_lookup`` keys on ``(ref, scope, asof_s, shape)``) plus two. A z over 250 sessions and
    a z over 504 days are two different states of one series and must never share an entry.

    ``offset_months`` IS ON THE MEMO KEY THOUGH IT IS NOT ON THE SERIES KEY, and the two facts are
    consistent rather than contradictory. The SERIES key names a READ, and a declared same-series offset
    changes no read -- that is exactly why ``oni_lag_climate`` costs nothing. The MEMO key names a
    computed STATE, and the palm board's state IS different: same array, shifted six months, so a
    different level, a different level date, a different z and a different run. Without this term a
    cache hit would hand the soybean board's ENSO state to the palm board, silently, and immortally on
    a historical as-of.

    ``alias_ref`` IS ON IT FOR THE SAME REASON ONE LAYER DOWN. The entry carries the row's OWN label --
    which ref was ASKED for -- and two alias rows folding onto one base at the same offset would
    otherwise share an entry, so the second reader would be handed the first one's name. The read METRIC
    needs no term of its own: after :func:`_resolve_same_series` it is a pure function of the base ref and
    the resolved region, and both are already on this key."""
    return (key.ref, key.commodity, key.country, key.metric, asof_s, read_shape, params_hash,
            int(offset_months or 0), str(alias_ref or ""), mirror_epoch())


def series_read_key(key: SeriesKey, table: str, metric: str, asof_s: str, cadence: str,
                    read_shape: str, ym_lag: bool, row_filter_sig: str = "",
                    span: Optional[tuple[str, int]] = None) -> tuple:
    """THE MEMO'S READ LAYER -- the key that makes a declared ``same_series_as`` cost what the design says
    it costs (sec 3.6 and sec 2.6 item 1: the palm row is computed "on the SAME memoised array SHIFTED by
    offset_months (zero extra reads)").

    THE DEFECT IT CLOSES, MEASURED WITH A COUNTING EXECUTOR BEFORE IT WAS FIXED. The STATE key above
    separates the palm board's lagged ENSO row from the soybean board's by ``offset_months`` and
    ``alias_ref`` -- correctly, because those are two different STATES of one series. But that miss then
    went straight to the store, so the fold still paid a SECOND physical read of the one series the whole
    dark half of phase 1a exists to share: at as-of 2026-09-08 on the deck's ONI fixture, with
    ``GRAPHRAG_STATE_CACHE=on``, ``oni_climate`` followed by ``oni_lag_climate`` made TWO ``query_fn``
    calls -- both of ``oni_anom``, the fold already reading the right column -- where the design says one.

    So the memo has TWO LAYERS ON ONE STORE, ONE BOUND AND ONE FLAG: a STATE layer keyed by what was
    COMPUTED, and this READ layer keyed by what was FETCHED. Two rows that are different states of ONE
    series -- the fold's alias and its base; a 60-month z and a 120-month z of the same array -- miss the
    state layer and HIT this one, so the second of them reads nothing.

    IT IS NOT THE "SECOND CACHE" SEC 14 PUTS OUT OF V1 SCOPE, and the distinction is structural rather
    than verbal: one store (``_SHARED``), one flag (``GRAPHRAG_STATE_CACHE``), one bound
    (``STATE_CACHE_MAX``), one immortal/TTL rule and one ``cache_clear()`` -- a key NAMESPACE inside the
    memo, not a second mechanism with its own lifecycle. DECLARED DRIFT ALL THE SAME, with its cost: read
    entries share the 512-entry bound with state entries, and each holds the FETCHED ROWS rather than the
    collapsed arrays. The alternative that adds no entry at all -- the alias reading the BASE's state
    entry and deriving from ``inputs`` -- was rejected because ``inputs`` carries values and dates only,
    so the shifted reading would have had to keep the BASE row's ``knowledge_date`` and vintage ``role``:
    the wrong-date half of this same defect, traded for the read-count half.

    IT IS THE SERIES KEY'S OWN SENTENCE IN CODE, and that is why it is keyed on :class:`SeriesKey` rather
    than on the arguments the read was ISSUED with. ``SeriesKey`` is "the unit of STATE, and the unit of
    the READ", and its scope is already NORMALISED BY THE CARD'S AXES (:func:`_scope_for_card`) -- the
    line that lets one ONI read serve 35 boards whose ``_scope_ex`` tuples all differ. Keying this layer
    on the raw ``(commodity, country)`` pair would have shared NOTHING: the palm board asks for
    ``malaysian_crude_palm_oil_cme`` and the soybean board for ``soybeans_cbot`` on a card that carries
    neither axis and filters on neither.

    ``row_filter_sig`` IS THE ONE PLACE THAT NORMALISATION COULD SPAN TWO DIFFERENT SQLs, and it is on
    the key so the sharing can never be wrong. ``query._metric_commodity_filters`` emits per-COMMODITY row
    constraints (``Metric.row_filters``) that survive on a card with NO commodity axis, so two boards
    holding one series key could compile two different WHERE clauses.

    THE CARD THAT MAKES THAT CONCRETE IS ALREADY ON THE BOARD, and it was measured rather than assumed:
    of the 41 registry cards, 11 metrics declare ``row_filters`` and exactly ONE of them sits on an
    axis-less card that a ``cascade_map`` ref reads -- ``cbot_board_crush_margin`` ->
    ``gold_board_crush.crush_margin_usd_bu`` (``commodity_col: null``, ``country_col: null``), keyed for
    five slugs (``soybeans_cbot``, ``soybean_meal_cbot``, ``soybean_oil_cbot``, ``soybeans``,
    ``soy_complex``). Its five entries are the SAME roll-boundary fence (``is_roll_boundary: ['0']``,
    provenance rows kept in the table and never served), so all five compile a BYTE-IDENTICAL SQL
    (measured at as-of 2026-09-08) and all five share one entry -- correctly, which is the point: the
    term splits on what the WHERE clause actually says, not on the slug that was asked for. The day a
    card's filters DIFFER by commodity, the failure direction is an extra read rather than one
    commodity's array served under another's key -- the direction the fold's own fence already chose.

    ``span`` IS ON THE KEY BECAUSE THE READ SPAN IS NO LONGER A FUNCTION OF THE CADENCE ALONE. Since the
    read-span landing, :func:`read_span` widens a cadence's span to cover a window WIDER than the cadence
    default (a per-series ``history_window``), so two rows on one series key, one cadence and one read
    shape can now issue two different ``period_start`` values. Without this term the narrower read would
    be served to the wider row -- a short array under a long window's label, which is the very defect
    this landing closes, re-entering through the memo. Every span on the estate is the cadence default
    today, so the term partitions nothing at this landing and costs one tuple slot."""
    return ("state_read", key.ref, key.commodity, key.country, key.metric, str(table), str(metric),
            str(asof_s or ""), str(cadence or ""), str(read_shape or ""), bool(ym_lag),
            str(row_filter_sig or ""), (None if span is None else (str(span[0]), int(span[1]))),
            mirror_epoch())


def _cache_enabled() -> bool:
    v = os.environ.get("GRAPHRAG_STATE_CACHE", "")
    return v.strip().lower() in ("1", "on", "true", "yes")


def cache_get(key: tuple):
    if not _cache_enabled():
        return None
    with _LOCK:
        hit = _SHARED.get(key)
        if not hit:
            return None
        val, exp = hit
        if exp is not None and time.time() > exp:
            _SHARED.pop(key, None)
            if key in _ORDER:
                _ORDER.remove(key)
            return None
        return val


def cache_put(key: tuple, val, asof_s: str, ttl_s: float = 900.0) -> None:
    """IMMORTAL on a historical as-of, TTL on a live one -- ``silverleg._shared_put``'s own rule
    (``asof_s < today`` -> immortal, else ``serving.silver.cache_ttl`` 900 s) -- under the LRU bound.

    DEEP-COPIED IN AS WELL AS OUT. silverleg's cache stores small immutable verdict dicts and can hand
    the same object around; this one stores whole ARRAYS, and the caller that just built the row is
    about to hand it onward. Copying only on the way OUT leaves the FIRST writer aliasing the entry --
    measured by the pin, which trims the producer's own array in place and then reads the next board's
    row back empty."""
    if not _cache_enabled():
        return
    val = copy.deepcopy(val)
    immortal = bool(asof_s) and asof_s < _dt.date.today().isoformat()
    exp = None if immortal else time.time() + float(ttl_s)
    with _LOCK:
        if key in _SHARED and key in _ORDER:
            _ORDER.remove(key)
        _SHARED[key] = (val, exp)
        _ORDER.append(key)
        while len(_ORDER) > STATE_CACHE_MAX:
            _SHARED.pop(_ORDER.pop(0), None)


def cache_clear() -> None:
    with _LOCK:
        _SHARED.clear()
        _ORDER.clear()


# ---------------------------------------------------------------------------------------------------
# THE EXECUTORS -- injected, never resolved from the environment inside a read.
# ---------------------------------------------------------------------------------------------------
class BoardReadDecline(Exception):
    """A resource decline the board owns and NAMES: ``pool_exhausted`` / ``pg_timeout``. It is not an
    error the answer swallows -- it is a row's status word, so the row keeps its receipts and the ledger
    counts it (``BoardPoolDeclined``). A serving read never pays 3 s of Athena silently."""

    def __init__(self, status: str, detail: str = ""):
        super().__init__(f"{status}: {detail}" if detail else status)
        self.status = status
        self.detail = detail


def board_query_fn():
    """The board's executor: ``pgnumbers.pg_query`` -- the RAISE-ON-FAILURE primitive the census must use
    -- wrapped so a pool wait past ``_NUM_POOL_WAIT_S`` or a statement past ``_NUM_STMT_MS`` declines BY
    NAME. NEVER ``pgnumbers.query_fn``: its per-request Athena fallback re-runs the same series SQL at a
    2-3 s planning floor and logs a warning that names no caller, so a board read would silently become
    the two-minute wall the mirror exists to remove -- and ``_NUM_BORROWS`` is one lane-wide counter, so
    the fallback could not even be attributed to the board afterwards."""
    from leviathan.graphrag.numbers import pgnumbers as pgn

    def _run(sql: str) -> list:
        try:
            return pgn.pg_query(sql)
        except RuntimeError as e:                          # the pool's own exhaustion raise
            if "pool exhausted" in str(e).lower():
                raise BoardReadDecline("pool_exhausted", str(e)[:160]) from None
            raise
        except Exception as e:                             # noqa: BLE001
            msg = str(e).lower()
            if "statement timeout" in msg or "canceling statement" in msg:
                raise BoardReadDecline("pg_timeout", str(e)[:160]) from None
            raise
    return _run


def fixture_query_fn(rows_by_table: dict, *, pit: Optional[dict] = None, ym_lag: bool = True):
    """THE OFFLINE HARNESS PATH (sec 2.1's ``state/__main__`` surface, and every deck that must run with
    no store). Returns an executor that serves canned rows keyed by the TABLE NAME appearing in the
    compiled SQL, so the whole producer -- ``build_sql``'s guard, the collapse, the transforms, the
    derivation records -- runs end to end at zero reads and zero network.

    IT COMPILES THE REAL SQL FIRST, deliberately: a fixture path that skipped ``build_sql`` would skip
    the as-of guard, and a producer proved only on the skipping path proves nothing about the one that
    serves. Use :func:`state_from_arrays` when the intent is to exercise the TRANSFORM half alone.

    ``pit={table: (spec, ts)}`` runs the SQL's OWN ORACLE -- ``query.apply_pit_filter``, "the pure-Python
    reference for the SAME point-in-time semantics build_sql encodes" -- over the canned rows before
    handing them back. A canned executor cannot execute a WHERE clause, so WITHOUT this a fixture would
    serve rows the real guard would have dropped and the harness would quietly prove nothing about
    leakage. WITH it, the offline board is filtered by the same rule the mirror applies, and the PIT pin
    (a row at as-of T never reads a knowledge_date > T) is a real assertion rather than a fixture's
    good manners.

    A KEY MAY NAME A METRIC, and the pin that needs it is the one that proves a same-series fold costs
    ONE read: ``{"silver_noaa_oni:oni_anom": [...], "silver_noaa_oni:oni_lag6": [...]}`` serves DIFFERENT
    arrays for the two columns, so a fixture can no longer make two different reads look like one. A bare
    table name keeps matching every metric, which is what every other deck wants. ``_run.calls`` counts
    the executions, because a claim about read COUNT that nothing counts is the claim this feature exists
    to make falsifiable."""
    def _run(sql: str) -> list:
        from leviathan.graphrag.numbers import query as Q
        _run.calls.append(sql)
        for key, rows in rows_by_table.items():
            table, _, want_metric = str(key).partition(":")
            if table not in sql:
                continue
            if want_metric and f"{want_metric} AS value" not in sql:
                continue
            out = [dict(r) for r in rows]
            pair = (pit or {}).get(key) or (pit or {}).get(table)
            if pair:
                spec, ts = pair
                out = Q.apply_pit_filter(out, spec, ts, ym_lag=ym_lag)
            return out
        return []
    _run.calls = []
    return _run


# ---------------------------------------------------------------------------------------------------
# THE NUMERIC FEEDER (sec 2.1)
# ---------------------------------------------------------------------------------------------------
def _scope_for_card(ts, commodity, country, *, declared_metric: str = "",
                    resolved_metric: str = "", country_rule: str = "") -> tuple[str, str, str]:
    """The series key's scope, NORMALISED BY THE CARD'S AXES (sec 1.1). Returns
    ``(commodity, country, metric)``.

    A card with neither a commodity column nor a country column is ``('_global', '')`` whatever
    ``_scope_ex`` returned -- and that single line is what makes ONE ONI read serve 35 rows in code as it
    does in prose. ``_scope_ex`` hands back the CONTRACT slug and the primary title for ``oni_climate``,
    which declares no country rule at all, so keying on its tuple would mint one ENSO state per board.

    THE METRIC TERM IS THE EXCEPTION THAT MAKES THE RULE SAFE, and it is measured, not defensive:
    ``silver_fred_fx`` is a wide, axis-less card whose GEOGRAPHY lives in the metric name, and
    ``cascade._region_row`` swaps ``brl_usd`` for the resolved region's currency. Without this term every
    board's FX read would share one ``('_global', '')`` entry and a DCE board would be served the
    Brazilian real.

    TWO TRIGGERS, and the second is why the first is not enough. (a) An axis-less card read under
    ``country_rule: region`` -- the metric-swap mechanism itself -- carries its resolved metric ALWAYS,
    including for the region whose currency happens to BE the row's declared default: keying Brazil as
    ``''`` and China as ``'cny_usd'`` would still separate them, but only by accident of which currency
    the map row was written with, and a map edit would silently re-collapse them. (b) Any resolved metric
    that DIFFERS from the declared one carries too, so a future card that swaps metrics by some other
    rule is covered without a second edit here.

    IT IS EMPTY WHERE THE COLLAPSE MUST HOLD. ``oni_lag_climate`` declares ``oni_lag6`` and resolves to
    ``oni_lag6`` under ``country_rule: none``, so neither trigger fires and the row folds onto
    ``oni_climate``'s key exactly as ``same_series_as`` intends -- one ENSO state, one read, two
    readings."""
    ccol = getattr(ts, "commodity_col", None)
    kcol = getattr(ts, "country_col", None)
    axis_less = not ccol and not kcol
    metric_is_scope = bool(resolved_metric) and (
        (axis_less and str(country_rule) == "region")                 # (a) the swap MECHANISM
        or resolved_metric != declared_metric)                        # (b) any actual swap
    m = str(resolved_metric) if metric_is_scope else ""
    if axis_less:
        return ("_global", "", m)
    c = str(commodity) if (ccol and commodity) else ""
    k = str(country) if (kcol and country) else ""
    return (c or "_global", k, m)


class _Fold(NamedTuple):
    """What ``same_series_as`` resolved to, and whether the declared offset may be APPLIED."""
    base_ref: str          # the series key's ref -- the base where the fold held, else the ref itself
    read_row: dict         # the map row whose (table, metric) is actually READ, region-resolved
    src_row: dict          # that row BEFORE the region swap -- the DECLARED metric, for the scope key
    alias_ref: str         # the ref asked for when it differs from base_ref; '' when nothing folded
    apply_offset: bool     # whether offset_months shifts the fetched array
    note: str              # the offset in words, or the reason the fold did not hold


def _resolve_same_series(ref: str, row: dict, row2: dict, node, casc) -> _Fold:
    """THE DECLARED SAME-SERIES FOLD, and the ONE rule it must obey: ``offset_months`` is applied to the
    BASE series' array, so the read is the BASE's metric -- never the alias's own already-shifted column
    with the shift applied a second time (sec 2.6 item 1, sec 3.6).

    THE DEFECT THIS FUNCTION EXISTS TO CLOSE, and it is measured, not hypothetical. The first S1 cut read
    the alias row's OWN metric (``oni_lag_climate`` declares ``metric: oni_lag6``) and THEN shifted the
    result by ``offset_months: 6``. ``bronze_to_silver/noaa_oni.py:125`` defines that column as
    ``df["oni_anom"].shift(n)`` -- the anomaly from six months earlier -- so the palm board's "ENSO state
    now" was ``oni_anom`` from TWELVE months ago while the row, the map row's own note and the design all
    say six. MEASURED at as-of 2026-09-08 on the deck's ONI fixture: TWO query_fn calls (``oni_anom`` and
    ``oni_lag6``), level dates 2026-07 and 2026-01, n_obs 119 and 113 -- against a design that says the
    row "RESOLVES to the same (oni_climate, _global) series key at ONE memoised read" and computes the
    palm reading "on the SAME memoised array SHIFTED by offset_months (zero extra reads)". Neither half
    held. The config's own comment reads ``offset_months`` the OTHER way ("the declared shift the served
    column already carries"), so exactly one of the two readings could ship; this is the design's.

    THE FENCE, and it is the answer to a second finding on the same mechanism. The memo key separates two
    alias rows only by ``offset_months`` and the alias ref, so an alias that resolved to a DIFFERENT
    physical series would serve one metric's array under another's key -- silently, and immortally on a
    historical as-of. The fold therefore holds only when the base row EXISTS, is readable, and declares
    the SAME table and the SAME native unit; otherwise there is no fold at all: the alias keeps its own
    key, reads its own metric, the offset is NOT applied (the alias's column already carries it), and the
    note says which of the two readings the row is under. Failing that way costs one extra read on a
    misconfigured row and can never mislabel an array."""
    declared = int(row2.get("offset_months", 0) or 0)
    base_ref = str(row2.get("same_series_as") or "").strip()
    if not base_ref or base_ref == ref:
        return _Fold(ref, row2, row, "", bool(declared),
                     (f"a declared {declared}-month offset on this ref's own series" if declared else ""))
    base = board_map_row(base_ref)
    if base is None:
        return _Fold(ref, row2, row, "", False,
                     f"declares same_series_as {base_ref!r}, which the board's map accessor does not "
                     f"serve: read as its own series, and the declared offset is the column's own")
    same_table = str(base.get("table") or "") == str(row2.get("table") or "")
    same_unit = str(base.get("native_unit") or "") == str(row2.get("native_unit") or "")
    if not (same_table and same_unit):
        why = "table" if not same_table else "native unit"
        return _Fold(ref, row2, row, "", False,
                     f"declares same_series_as {base_ref!r} on a different {why}: NOT folded, read as "
                     f"its own series, and the declared offset is the column's own")
    read_row = casc._region_row(node, base)            # the BASE row, region-resolved the same way
    return _Fold(base_ref, read_row, base, ref, bool(declared),
                 (f"the same series as {base_ref}, read at a declared {declared}-month offset"
                  if declared else f"the same series as {base_ref}, read at no offset"))


def _parses(v) -> bool:
    """Whether a served cell carries a NUMBER. The collapse's own admission test, restated as a
    predicate so an all-blank frame can be named before the collapse rather than after it."""
    try:
        float(str(v).replace(",", ""))
        return True
    except (TypeError, ValueError):
        return False


def _is_flag_row(ref: str, row: dict) -> bool:
    """A ``*_flag`` ref: its state is ``flag_state``, and z / percentile decline BY NAME (sec 2.1's two
    feeder rules). The narrate_unit is the card's own declaration and the suffix is the DAG's naming
    habit; either is enough, because the two have drifted before."""
    return str(ref).endswith("_flag") or str((row or {}).get("narrate_unit", "")).strip() == "flag"


def _month_end(y: int, m: int) -> str:
    d = _dt.date(y + (m // 12), (m % 12) + 1, 1) - _dt.timedelta(days=1)
    return d.isoformat()


def derive_knowledge_date(ts, row: dict) -> tuple[Optional[str], str]:
    """The row's KNOWLEDGE DATE, DERIVED PER CARD CLASS, and the WORDS that say which derivation ran
    (sec 1.4, D21; anchors F2).

    The store serves a ``knowledge_date`` alias only where the card declares ``knowledge_date_col``, and
    the three ``year_month`` cards the board leans on declare none. So:
      * ``vintage`` cards -> the SERVED ``knowledge_date`` (the vintage the collapse picked);
      * ``data_date`` cards -> the row's own ``data_date`` PLUS ``publication_lag_days`` (pink sheet 40 d,
        MPOB 43 d, COT 6 d, NASS 2 d) -- the row is stamped by its DATA date and is not public until the
        lag has run;
      * ``year_month`` cards -> MONTH-END plus ``ym_publication_lag_days``, printed as "data month
        YYYY-MM, knowable from {ISO}".
    ``None`` with a stated basis when the card gives nothing to derive from -- never a guess, and never
    the as-of standing in for a knowledge date."""
    sem = getattr(ts, "knowledge_semantics", "")
    if sem == "year_month":
        y, m = row.get("year"), row.get("month")
        try:
            y, m = int(y), int(m)
        except (TypeError, ValueError):
            return None, "year_month card with no year/month on the row"
        end = _month_end(y, m)
        lag = getattr(ts, "ym_publication_lag_days", None)
        if not lag:
            return end, f"data month {y:04d}-{m:02d}, month-end {end}; no publication lag declared"
        d = _dt.date.fromisoformat(end) + _dt.timedelta(days=int(lag))
        return d.isoformat(), (f"data month {y:04d}-{m:02d}, knowable from {d.isoformat()} "
                               f"(month-end plus {int(lag)} days)")
    kd = row.get("knowledge_date")
    if sem == "vintage" and kd:
        return str(kd)[:10], "the vintage served at this as-of"
    dd = row.get("data_date") or kd
    if not dd:
        return None, "the card serves neither a knowledge date nor a data date"
    lag = int(getattr(ts, "publication_lag_days", 0) or 0)
    if not lag:
        return str(dd)[:10], "the observation's own date; no publication lag declared"
    # A MALFORMED DATE DECLINES BY NAME RATHER THAN RAISING. A NULL was already safe -- `""` is falsy
    # and `not dd` returns the stated basis above -- but a non-empty label this calendar cannot parse
    # (`"2026-13-01"`, a truncated cell, a stray footnote) reached `date.fromisoformat` unguarded and
    # raised. The walk fences that into a `read_error` row, so the column would be DEMOTED SILENTLY by
    # one bad cell; a stated absence is a sentence the row can print instead.
    try:
        d = _dt.date.fromisoformat(str(dd)[:10]) + _dt.timedelta(days=lag)
    except (TypeError, ValueError):
        return None, (f"the card serves a date this calendar cannot read ({str(dd)[:10]!r}), so a "
                      f"{lag}-day publication lag cannot be applied to it")
    return d.isoformat(), f"observation {str(dd)[:10]} plus a {lag}-day publication lag"


VINTAGE_NOTE = ("read from a table revised in place; the value as known at {asof} is not recoverable "
                "and is shown as revised through {today}")
"""The REPLAY LABEL (sec 1.4, D17). A latest-only, revised-in-place card at a HISTORICAL as-of is
SERVED with this note, never declined. Revision 1 of the design declined those refs' series half at zero
reads; that is a fence that DELETES where a label already exists -- it would have darkened the ENSO state
on 33 boards in every replayed census, every harness render and every backdated question. The row stands,
the label rides, and ``BoardReplayLabelled`` counts it."""

#: The cards whose retention is ``latest-only`` and whose values are revised IN PLACE. The note above
#: rides a row from one of these at a historical as-of.
LATEST_ONLY_CARDS: frozenset[str] = frozenset({"silver_noaa_oni", "silver_noaa_iod"})


class KeyPlan(NamedTuple):
    """WHAT A REF RESOLVES TO AT **ZERO READS** -- the walk's pricing unit (sec 3.3 step 1, sec 3.8).

    THE READ BUDGET IS PRICED BEFORE THE FETCH, and that law has a precondition nobody stated out loud
    until the walk needed it: the pricer must know the SERIES KEY of every row in the anchor DAGs
    before a single row is fetched, because the read count of a turn is the DISTINCT series-key count
    (sec 1.1) and two node rows that fold onto one key must be priced as ONE. Everything that decides a
    key -- the board's map row, ``_scope_ex``'s resolution, ``_region_row``'s metric swap, the
    ``same_series_as`` fold and the card's axes -- is arithmetic over loaded YAML. So the resolution is
    free, and this is it.

    ONE RESOLVER, NOT TWO. :func:`series_state` calls this function and then reads; the walk calls it
    and does not. A second copy of the prologue in ``walk.py`` would be the COMPAT-9 drift class with a
    memo key on the end of it -- a scope resolved one way at pricing time and another way at read time
    would mean the board paid for a key it never fetched and fetched a key it never priced, and the
    rectangle of sec 1.2 would close on the wrong numbers.

    ``key is None`` is the ABSENCE, and ``status`` is the closed word that says which one (sec 1.3):
    ``unmapped_ref``, ``scope_unresolved:<the resolver's own reason>``, ``unmapped_ref:no_registry_card``
    or ``outlook_lane``. Those four rows cost nothing and are never priced -- and they are still ROWS."""

    key: Optional[SeriesKey]
    status: str = "ok"
    table: str = ""
    metric: str = ""
    cadence: str = ""
    context_only: bool = False
    offset_months: int = 0
    alias_ref: str = ""
    offset_note: str = ""
    commodity: str = ""                 # `_scope_ex`'s OWN resolution, before the card-axis normalise
    country: str = ""
    row: Optional[dict] = None          # the board's map row as DECLARED (None only on unmapped_ref)
    row2: Optional[dict] = None         # ...region-resolved (the metric swap applied)
    read_row: Optional[dict] = None     # the row whose (table, metric) is ACTUALLY read, post-fold
    src_row: Optional[dict] = None      # that row BEFORE the region swap -- the declared metric
    ts: Any = None                      # the registry card, or None where the map row names no card
    apply_offset: bool = False          # whether the fold licenses shifting the fetched array


def series_key_for(ref: str, node, *, turn_kind: str = "") -> KeyPlan:
    """``(ref, node) -> KeyPlan`` at ZERO reads. See :class:`KeyPlan` for why this is its own function.

    ``turn_kind`` is here rather than at the read because the OUTLOOK decline is a zero-read fact the
    WALK owns (sec 1.3 / D18): a positioning row on an outlook turn must never be PRICED, and a pricer
    that could not see the lane would buy a read the producer then refuses."""
    casc = _casc()

    row = board_map_row(ref)
    if row is None:
        return KeyPlan(key=None, status="unmapped_ref")

    commodity, country, skip = casc._scope_ex(node, row)
    if country is casc.SKIP_NODE:
        return KeyPlan(key=None, status=f"scope_unresolved:{skip or 'region-unresolved'}",
                       table=row.get("table", ""), metric=row.get("metric", ""), row=row)

    row2 = casc._region_row(node, row)                 # fred_fx: the resolved region's currency picks the metric
    table, metric = row2.get("table", ""), row2.get("metric", "")
    context_only = table in getattr(casc, "POSITIONING_TABLES", frozenset())
    if context_only and str(turn_kind or "").strip().lower() == "outlook":
        # R9's SHIPPED DROP, in the board's own words (cascade.py's quantify skips a POSITIONING_TABLES
        # row on an outlook turn). The word is in the closed enum because the render owes the reader a
        # sentence for it; it is stamped HERE, at ZERO reads, because the turn kind is knowledge the
        # WALK has and the read does not -- the caller passes it or the board never declines this way.
        return KeyPlan(key=None, status="outlook_lane", table=table, metric=metric,
                       context_only=True, commodity=str(commodity or ""), country=str(country or ""),
                       row=row, row2=row2)

    from leviathan.graphrag.numbers.registry import load_registry
    try:
        ts = load_registry().get(table)
    except Exception:                                   # noqa: BLE001 -- a map row naming an unknown card
        return KeyPlan(key=None, status="unmapped_ref:no_registry_card", table=table, metric=metric,
                       context_only=context_only, commodity=str(commodity or ""),
                       country=str(country or ""), row=row, row2=row2)

    # ── THE SAME-SERIES FOLD (sec 2.6 item 1, sec 3.6) ─────────────────────────────────────────────
    fold = _resolve_same_series(ref, row, row2, node, casc)
    read_row, src_row = fold.read_row, fold.src_row
    rtable, rmetric = read_row.get("table", ""), read_row.get("metric", "")
    c, k, mkey = _scope_for_card(ts, commodity, country,
                                 declared_metric=str(src_row.get("metric") or ""),
                                 resolved_metric=rmetric,
                                 country_rule=str(src_row.get("country_rule") or ""))
    return KeyPlan(key=SeriesKey(ref=fold.base_ref, commodity=c, country=k, metric=mkey),
                   status="ok", table=rtable, metric=rmetric, cadence=cadence_of(ts, rtable),
                   context_only=context_only,
                   offset_months=int(row2.get("offset_months", 0) or 0),
                   alias_ref=fold.alias_ref, offset_note=fold.note,
                   commodity=str(commodity or ""), country=str(country or ""),
                   row=row, row2=row2, read_row=read_row, src_row=src_row, ts=ts,
                   apply_offset=fold.apply_offset)


def series_state(ref: str, node, asof: str, *, qfn, windows: Optional[dict] = None,
                 conventions: Optional[dict] = None, newest_first: Any = "all",
                 ym_lag: bool = True, silver_status: str = "none",
                 today: Optional[str] = None, turn_kind: str = "") -> StateRow:
    """ONE series state for ONE ``(ref, resolved scope)`` at ONE as-of. THE HANDLER NEVER RAISES: every
    failure path returns a StateRow carrying a closed ``status`` word and the reads it actually spent
    (``cascade._run_one``'s own contract).

    ``node`` is anything carrying ``.contract`` and ``.prior['region']`` -- the runtime GroundedNode, or
    the census's ``_LegNode`` stand-in. ``windows`` / ``conventions`` are the ``state_conventions.yaml``
    blocks, PASSED IN rather than read here (the config accessor is its own module at its own sitting).

    ``turn_kind`` is the WALK's knowledge, not the read's: ``'outlook'`` declines positioning's series
    half at zero reads by name (``outlook_lane``, sec 1.3 / D18). Empty -- the default -- declines
    nothing, so a caller that does not know the turn kind cannot silently assert a lane.
    """
    # THE ZERO-READ PROLOGUE IS :func:`series_key_for` (sec 3.3 step 1). It was lifted out of this body
    # at S2 rather than copied into the walk, because the pricer and the reader must resolve one ref to
    # ONE key or the budget rectangle closes on numbers nothing fetched. Every early return below is the
    # same return this function made before the lift, in the same order, with the same words.
    casc = _casc()
    plan = series_key_for(ref, node, turn_kind=turn_kind)
    row, row2 = plan.row, plan.row2
    out = StateRow(key=plan.key or SeriesKey(ref=ref), asof=asof, coverage_tier="none_text_only")
    out.table, out.metric = plan.table, plan.metric
    if row2 is not None:
        out.unit = str(row2.get("native_unit", "") or "")
        out.narrate_unit = str(row2.get("narrate_unit", "") or "")
        out.scale = float(row2.get("scale", 1) or 1)
        out.offset_months = plan.offset_months
        out.context_only = plan.context_only
    if plan.key is None:
        out.status = plan.status
        out.coverage_tier = coverage_tier(map_row=row, silver_status=silver_status, status=out.status)
        return out

    commodity, country = plan.commodity, plan.country
    ts, read_row, src_row = plan.ts, plan.read_row, plan.src_row
    base_ref = plan.key.ref
    out.alias_ref, out.offset_note = plan.alias_ref, plan.offset_note
    table, metric = plan.table, plan.metric             # the metric ACTUALLY READ, never the alias's label

    cadence = plan.cadence
    out.cadence = cadence
    win = history_window(cadence, table, windows)
    out.window_note = _window_note(cadence, win)

    # ── THE MEMO (sec 1.1) ──────────────────────────────────────────────────────────────────────────
    # The key is silverleg's `(ref, scope, asof_s, read_shape)` (make_silver_lookup :408) plus the two
    # terms the board needs, and the params hash is computed from the PLAN -- the transform names and
    # parameters this row WILL run -- rather than from the derivations it produced, because a key that
    # can only be built after the read cannot prevent one. The plan is a pure function of the cadence,
    # the declared windows and the convention row, so it is knowable before a single row is fetched.
    conv = (conventions or {}).get(ref) or (conventions or {}).get(base_ref)
    is_flag = _is_flag_row(ref, row2)
    # THE WINDOW THE READ MUST COVER, which is not always the window the row is MEASURED over. `win` is
    # what `zscore` will be handed; a series may ALSO declare its own `history_window` in
    # state_conventions.yaml, and `history_window()` does not consult that row today. The READ takes the
    # wider of the two plus the cadence's slack, so a declared window can never outrun the array fetched
    # for it -- and the measured half of it stays exactly `win`, unchanged by this line.
    read_win = max(int(win or 0), int((conv or {}).get("history_window") or 0))
    phash = TR.params_hash(_transform_plan(cadence, win, is_flag, conv))
    ckey = state_cache_key(out.key, str(asof or "")[:10], _read_shape(newest_first), phash,
                           out.offset_months, out.alias_ref)
    hit = cache_get(ckey)
    if hit is not None:
        # DEEP-COPIED ON THE WAY OUT. The entry holds whole ARRAYS and a consumer that trimmed one in
        # place would poison every later reader of a key that is IMMORTAL on a historical as-of -- the
        # silent, unfalsifiable staleness the read-shape term was added to prevent one layer up.
        return copy.deepcopy(hit)

    try:
        # THROUGH THE MEMO'S READ LAYER, keyed on `out.key` -- the series key IS the read (sec 1.1). A
        # row that missed the STATE layer because it is a different STATE of a series already fetched --
        # the same-series fold's alias, a second transform plan over one array -- pays no read here.
        rows, reads = _shared_read(ts, out.key, table, metric, commodity, country, asof, cadence,
                                   qfn=qfn, newest_first=newest_first, ym_lag=ym_lag,
                                   window=read_win)
    except BoardReadDecline as d:
        out.status = d.status
        out.reads = 1
        out.coverage_tier = coverage_tier(map_row=row, silver_status=silver_status, status=out.status)
        return out
    except Exception as e:                              # noqa: BLE001 -- a read may never break an answer
        # `read_error`, NEVER `read_empty` (design sec 6.7's own series word). The two are different
        # events and the render fronts an empty read with "NO ROWS RETURNED" -- a sentence that would be
        # a false statement about a read that CRASHED. The ledger counts the attempt: a read that raised
        # spent the same slot a declined one did, and a rectangle short by one cannot be closed.
        out.status = "read_error"
        out.reads = 1
        out.recency = {"read_error": str(e)[:160]}
        out.coverage_tier = coverage_tier(map_row=row, silver_status=silver_status, status=out.status)
        return out
    out.reads = reads

    if not rows:
        out.status = "read_empty"
        out.coverage_tier = coverage_tier(map_row=row, silver_status=silver_status, status=out.status)
        return out
    if not any(_parses(r.get("value")) for r in rows):
        # ALL-BLANK IS AN EMPTY READ TOO, and it must not fall through to the collapse -- ``_pace_series``
        # would hand back ``([], None)`` and the row would decline ``undeclared_cross_section``, naming a
        # cross-section defect for a frame that simply carried no numbers. The rule is
        # ``citations.is_empty_read``'s ("zero rows OR rows that are all blank", :338); that function is
        # NOT called here because it takes a CALL RECORD rather than a row list and lives in a file the
        # K9 lane holds -- adopting it means a second pinned cross-lane import surface, which is named in
        # the S1 report as a follow-up rather than taken inside a fixer sitting.
        out.status = "read_empty:all_blank"
        out.reads = reads
        out.coverage_tier = coverage_tier(map_row=row, silver_status=silver_status, status=out.status)
        return out
    truncated = len(rows) >= READ_LIMIT
    values, collapse = casc._pace_series({"rows": rows}, table, commodity=commodity)
    out.collapse = collapse
    if not values:
        # ``_pace_series`` returns ([], None) on a multi-row period whose table declares no collapse:
        # the caller declines the leg WHOLE rather than ever delta-ing two cross-section rows (the
        # measured ESR fixture that narrated '+565 1000 MT from the prior week' against a true weekly
        # change of -45 -- direction inverted, on a real minted [N] row the all-numbers guard validated).
        out.status = "read_empty:undeclared_cross_section"
        out.coverage_tier = coverage_tier(map_row=row, silver_status=silver_status, status=out.status)
        return out

    # THE LABEL AXIS IS BUILT OVER THE ROWS THE COLLAPSE ACTUALLY ADMITTED, and that is a MEASURED
    # correction, not tidying. ``cascade._pace_series`` SKIPS a row whose value does not parse
    # (cascade.py:2408) -- which on the mirror is every NULL cell, rendered ``""`` by
    # ``pgnumbers._stringify`` -- while ``_period_dates`` walked EVERY row and produced one label per
    # row. The two axes then differed in length and the mismatch branch trims the labels from the
    # FRONT, so a null anywhere but the front shifts the whole array by one period. MEASURED on a
    # 140-month ONI frame with ONE blank cell inside the fetched window: 110 of 118 observations came
    # back labelled with the wrong month -- silently, with the level, the z, the percentile, the run
    # and every window change computed against dates they do not belong to. Handing the SAME admission
    # test the collapse uses is what makes the two axes parallel by construction rather than by luck.
    dated_rows = [r for r in rows if _parses(r.get("value"))]
    dates = _period_dates(dated_rows, ts, values, collapse)
    # THE NULL BOUNDARY, ONCE, WHERE THE ARRAY IS BUILT (``transforms.clean_pairs``). ``_pace_series``
    # already drops a row whose value does not parse (cascade.py:2408), so on the served path this drops
    # NOTHING and ``n_null_cells`` is zero; what it does close is the DATE axis, which carries a null
    # wherever the mirror served no date at all. A ``""`` there is what rode into ``int(iso[0:4])`` and
    # raised on 140 of 144 board runs in the S4 in-VPC pass. Cleaning the pair TOGETHER is the point: an
    # array cleaned without its axis is an array whose dates no longer say what its values are values of.
    values, dates, drops = TR.clean_pairs_counted(values, dates)
    n_null_cells = drops["null"]
    if not values:
        # Unreachable behind the all-blank guard above, and stated rather than assumed: a frame that
        # carried no reading is an EMPTY READ by name, never a collapse that ran over nothing.
        out.status = "read_empty:all_blank"
        out.coverage_tier = coverage_tier(map_row=row, silver_status=silver_status, status=out.status)
        return out
    level_row = dated_rows[-1]                         # the served row the LEVEL's own facts come from
    if plan.apply_offset and out.offset_months and cadence == "monthly":
        # THE DECLARED SAME-SERIES OFFSET (cascade_map `offset_months`), applied to the BASE series'
        # array at ZERO extra reads: the palm author's "state now" is ONI six months ago. The projection
        # counts from TODAY's value and both dates print -- the row never lets a reader think the palm
        # board's ENSO state is a different index from the soybean board's. It runs ONLY where
        # `_resolve_same_series` folded the row onto a base it actually read (or where the ref declares
        # an offset on its own series): shifting an alias's already-lagged column would double the lag,
        # which is the defect that function's docstring measures.
        n = int(out.offset_months)
        # ONE ADMITTED ROW PER PERIOD: no collapse ran (and the comparison is against the rows the
        # collapse ADMITTED, so a blank cell no longer makes a parallel frame look collapsed).
        parallel = len(dated_rows) == len(values)
        if len(values) > n:
            values, dates = values[:-n], dates[:-n]
            if parallel:
                # THE ROW-LEVEL FACTS MOVE WITH THE LEVEL. `knowledge_date` and the vintage `role` are
                # read off ONE served row, and until this fix they were read off the NEWEST one while
                # the level printed beside them was six months older. MEASURED on the deck's ONI fixture
                # at as-of 2026-09-08: the palm row printed level_date 2026-01 with knowledge_date
                # 2026-09-05 -- the SOYBEAN row's knowledge date, on the palm row's reading. Both dates
                # print (sec 2.6 item 1), and a knowledge date belonging to a different observation is
                # the wrong one of the two.
                level_row = dated_rows[-(n + 1)]
            else:
                out.offset_note = (f"{out.offset_note}; the knowledge date is the newest served row's -- "
                                   f"a collapsed cross-section has no single row parallel to the "
                                   f"shifted level")
        else:
            # AN OFFSET LONGER THAN THE FETCHED HISTORY IS NOT APPLIED, AND THE ROW SAYS SO. Silently
            # skipping the shift would print an UNSHIFTED level under a note that claims a six-month one
            # -- a wrong figure wearing a right label. Stating the unapplied offset is the same shape the
            # non-monthly branch below already takes.
            out.offset_note = (f"a declared {n}-month offset is NOT applied: the fetched history is "
                               f"{len(values)} monthly periods, no longer than the offset")
    elif out.offset_months and plan.apply_offset and cadence != "monthly":
        # `offset_months` is declared in MONTHS. On a non-monthly cadence the board cannot convert it to
        # the card's own periods without inventing a calendar rule, so it is NOT applied and the row
        # says so -- an unapplied offset stated is a fact; an offset quietly dropped is a wrong level.
        out.offset_note = (f"a declared {int(out.offset_months)}-month offset is NOT applied on a "
                           f"{cadence} card: the shift is declared in months")

    if out.alias_ref and reads == 0:
        # THE FOLD'S OWN LEDGER SENTENCE, on the row rather than in a comment: this row is a second STATE
        # of an array the process had already fetched, so it cost nothing. The claim is measurable from
        # the row (`reads == 0`) and from the executor's call count, which is what makes it falsifiable.
        out.offset_note = (f"{out.offset_note}; the base series was already in memory, so this reading "
                           f"cost no read of its own")
    out.level = values[-1]
    out.level_date = dates[-1] if dates else None
    kd, basis = derive_knowledge_date(ts, level_row)
    out.knowledge_date, out.knowledge_basis = kd, basis
    # THE ALIAS, NOT THE COLUMN NAME. ``query._extras`` surfaces ``provenance_col`` under the alias
    # ``revision_stamp``; reading the card's physical column name off the row would find nothing and the
    # role would be silently None on all nine cards that declare one (the K9-4 fact the vintage-role
    # fence is built on).
    out.role = level_row.get("revision_stamp") or None
    out.coverage = {"first_obs": getattr(ts, "first_obs", None), "n_obs": len(values),
                    "history_start": dates[0] if dates else None,
                    "history_end": dates[-1] if dates else None, "truncated": truncated,
                    # A HOLE IS COUNTED, NEVER SWALLOWED: the number of served cells that carried no
                    # reading and were dropped from the array below (sec 2.1's read rules say an
                    # absence is a fact the row states, not a silence).
                    #
                    # AND AN ABSENCE IS NOT A DEFECT. `dropped_null` counts cells the source declared
                    # NULL; `dropped_unparseable` counts cells that carried something this package
                    # could not read as a number (a stray unit suffix, a footnote marker) and
                    # `dropped_bool` a flag column served as True/False. Folded into one count, a
                    # systematically malformed column reads as a SPARSE one under the word `null` and
                    # the defect is unraisable -- `transforms.cell_kind` holds the whole reason.
                    "dropped_null": int(n_null_cells),
                    "dropped_unparseable": int(drops["unparseable"]),
                    "dropped_bool": int(drops["bool"]),
                    "undated_periods": sum(1 for d in dates if d is None)}

    bundle = {out.key.label(): {"values": values, "dates": dates, "unit": out.unit}}
    bkey = out.key.label()
    derivs: list = []
    if truncated:
        # THE TRUNCATION DETECTOR (sec 2.1 read rule 3). The measures below still run -- refusing to
        # compute is the suppress-not-correct shape this house grades FATAL, and a z over 5,000 fetched
        # periods is a real z -- but the WINDOW NOTE is corrected on the spot, because the honest defect
        # of a truncated read is a figure whose stated window is longer than the array behind it.
        out.status = f"history_truncated:{READ_LIMIT}"
        out.window_note = (f"{out.window_note}; the read came back at its {READ_LIMIT}-row cap, so every "
                           f"measure below ran over the {len(values)} newest periods fetched")

    if is_flag:
        fe, rec = TR.run_transform("flag_events", bundle, key=bkey,
                                   params={"window_periods": max(1, win or 12)})
        derivs.append(rec)
        out.flag_state = (None if fe["declined"] else
                          # ``stats.flag_events`` stringifies its own date axis (``str(d)``), so an
                          # UNDATED event would print the literal word "None" as a date. The null comes
                          # back through the boundary's own coercion instead.
                          {"last_event_date": TR.date_or_none(fe["last_event_date"]),
                           "events_in_window": fe["events_in_window"],
                           "periods_since": fe["periods_since"],
                           "window_periods": fe["window_periods"]})
        out.z = {"declined": True, "reason": "a z over a 0/1 flag series is a base rate, not a sigma"}
        out.percentile = {"declined": True,
                          "reason": "a rank inside a 0/1 flag series is that same base rate"}
    else:
        if win:
            z, rec = TR.run_transform("zscore", bundle, key=bkey, params={"window": win})
            derivs.append(rec)
            out.z = z
            if z.get("declined") and "zero variance" in str(z.get("reason", "")):
                out.status = "zero_variance" if status_word(out.status) == "ok" else out.status
        p, rec = TR.run_transform("percentile", bundle, key=bkey)
        derivs.append(rec)
        out.percentile = p
        for direction in ("up", "down"):
            s, srec = TR.run_transform("streak", bundle, key=bkey, params={"direction": direction})
            derivs.append(srec)
            if not s["declined"] and s["value"] > 0:
                out.run = {"direction": direction, "length": s["value"],
                           "since_date": _since_date(dates, int(s["value"]))}
                break

    for w in CADENCE_CHANGE_WINDOWS.get(cadence, ()):
        label = f"{w} {_period_noun(cadence, w)}"
        ch, rec = TR.run_transform("window_change", bundle, key=bkey,
                                   params={"t1": -(w + 1), "t2": -1, "window_label": label})
        derivs.append(rec)
        out.changes.append({"window": label, "n_periods": w, "declined": ch["declined"],
                            "reason": ch.get("reason"),
                            "from_date": dates[-(w + 1)] if len(dates) > w else None,
                            "to_date": dates[-1] if dates else None,
                            "delta": ch.get("value"), "pct": ch.get("pct_change")})

    if conv:
        out.convention = _convention_label(conv, out, bundle, bkey, derivs)

    if (table in LATEST_ONLY_CARDS or str(getattr(ts, "vintage_retention", "")) == "latest-only"):
        td = today or _today()
        if asof and asof < td:
            out.vintage_note = VINTAGE_NOTE.format(asof=asof, today=td)

    out.recency = _recency(out, asof, ts, cadence)
    out.derivation = derivs
    out.inputs = bundle
    n_obs = len(values)
    if status_word(out.status) == "ok" and n_obs < 8:
        out.status = f"thin_history:{n_obs}"
    out.coverage_tier = coverage_tier(map_row=row, silver_status=silver_status, status=out.status,
                                      n_obs=n_obs)
    cache_put(ckey, out, str(asof or "")[:10])
    return out


def _read_shape(newest_first) -> str:
    """silverleg's own read-shape LABEL (``silverleg._read_shape``), borrowed rather than re-typed: it
    names the ORDERING the rows were fetched under ('asc' / 'nf' / 'nf_all'), and an unknown scope gets
    its own label rather than collapsing into a known one -- which is the entire property the term
    exists to provide."""
    from leviathan.graphrag import silverleg as slv
    return slv._read_shape(newest_first)


def _transform_plan(cadence: str, win: int, is_flag: bool, conv: Optional[dict]) -> list:
    """The transforms this row WILL run, with their parameters -- the input to the memo key's params
    hash (sec 1.1). It mirrors :func:`series_state`'s own order and must be edited WITH it: a plan that
    drifted from what runs would key two different states the same way, and the entry is immortal on a
    historical as-of.

    It is a PLAN, not a record: it carries no ``n`` and no input references, because those depend on the
    read this key exists to avoid."""
    plan: list = []
    if is_flag:
        plan.append({"transform": "flag_events", "params": {"window_periods": max(1, win or 12)}})
    else:
        if win:
            plan.append({"transform": "zscore", "params": {"window": win}})
        plan.append({"transform": "percentile", "params": {}})
        plan.append({"transform": "streak", "params": {"direction": "up"}})
        plan.append({"transform": "streak", "params": {"direction": "down"}})
    for w in CADENCE_CHANGE_WINDOWS.get(cadence, ()):
        plan.append({"transform": "window_change",
                     "params": {"t1": -(w + 1), "t2": -1,
                                "window_label": f"{w} {_period_noun(cadence, w)}"}})
    if conv:
        plan.append({"transform": "regime_flag",
                     "params": {"kind": conv.get("kind"), "bands": list(conv.get("bands") or []),
                                "labels": list(conv.get("labels") or [])}})
        if str(conv.get("kind")) == "pace_vs_prior_year":
            plan.append({"transform": "pace_vs_prior",
                         "params": {"periods_per_year": CADENCE_PERIODS_PER_YEAR.get(cadence, 12)}})
    return plan


def board_spec(table: str, metric: str, commodity, country, asof: str, cadence: str,
               window: Optional[int] = None):
    """THE BOARD'S READ, as one ``NumberQuery`` -- public so a harness, a census and a PIT pin can build
    the SAME spec the feeder builds rather than a plausible-looking neighbour of it.

    ``agg='series'`` with an EXPLICIT ``period_start`` per cadence and an EXPLICIT ``limit``: the two
    things ``cascade.fetch_window`` cannot express, and the reason this reads through ``query.run``
    directly. A window-less series read on ``silver_fred_fx`` is 5,538 rows against a 5,000 cap, and
    under the default ASC order the 538 rows the cap drops are the NEWEST ones.

    ``window`` is OPTIONAL and defaults to the cadence's own: a caller that does not know the window is
    read over the cadence default's span, which is already ``window + slack`` (:data:`CADENCE_READ_SPAN`).
    A caller that DOES know it -- ``series_state``, which computed it before it read -- passes it, and a
    series declaring a window WIDER than its cadence default is read wide enough to fill it."""
    from leviathan.graphrag.numbers import query as Q
    return Q.NumberQuery(table=table, metric=metric, asof=asof,
                         commodity=commodity or None,
                         country=(country if country else None),
                         agg="series", period_start=_period_start(asof, cadence, window),
                         limit=READ_LIMIT)


def _read_series(ts, table, metric, commodity, country, asof, cadence, *, qfn, newest_first, ym_lag,
                 window: Optional[int] = None):
    """ONE read through ``query.run`` -- the ``silverleg._rows`` shape, with an EXPLICIT window and cap."""
    from leviathan.graphrag.numbers import query as Q
    spec = board_spec(table, metric, commodity, country, asof, cadence, window)
    rows = Q.run(spec, query_fn=qfn, futures_newest_first=newest_first, ym_lag=ym_lag)
    return rows, 1


def _row_filter_sig(ts, metric: str, commodity) -> str:
    """The per-commodity ROW CONSTRAINTS this read will compile (``query._metric_commodity_filters``'s own
    inputs), as a stable string. It is the read key's ONE term that is not a function of the series key,
    and :func:`series_read_key` says why it is there."""
    m = (getattr(ts, "metrics", None) or {}).get(str(metric))
    rf = getattr(m, "row_filters", None) if m is not None else None
    if not rf or not commodity:
        return ""
    return repr(sorted((str(c), sorted(str(v) for v in vals))
                       for c, vals in (rf.get(str(commodity)) or {}).items()))


def _shared_read(ts, key: SeriesKey, table, metric, commodity, country, asof, cadence, *, qfn,
                 newest_first, ym_lag, window: Optional[int] = None):
    """ONE physical read per ``(series key, read shape)`` -- :func:`_read_series` behind the memo's READ
    layer (:func:`series_read_key`), which is what makes the same-series fold free.

    Returns ``(rows, reads)`` with ``reads=0`` when the array came back from the memo: that row spent
    nothing and the row that PAID carries the 1, so a board's ledger sums to the PHYSICAL read count
    rather than to its row count. (A STATE-layer hit is a different event and keeps the reads of the row
    it is a copy of -- that entry IS the earlier row, receipts included, and
    ``test_the_memo_serves_the_second_ask_without_a_second_read`` pins it.)

    WITH THE MEMO OFF THIS FUNCTION IS ``_read_series``, byte for byte: ``cache_get`` returns None and
    ``cache_put`` is a no-op, so an unarmed process reads exactly what it read before -- the rollback,
    from the idiom rather than from a promise. The fold's zero-extra-read property is therefore a
    property of the MEMO, exactly as the design's own "one ONI read serves 35 rows" is."""
    rkey = series_read_key(key, table, metric, str(asof or "")[:10], cadence,
                           _read_shape(newest_first), ym_lag, _row_filter_sig(ts, metric, commodity),
                           read_span(cadence, window))
    hit = cache_get(rkey)
    if hit is not None:
        # COPIED OUT as well as in: the entry holds a whole fetched ARRAY and the collapse below is
        # handed these rows -- a consumer that sorted or trimmed them in place would poison every later
        # reader of a key that is IMMORTAL on a historical as-of (``cache_put``'s own measured law).
        return [dict(r) for r in hit], 0
    rows, reads = _read_series(ts, table, metric, commodity, country, asof, cadence,
                               qfn=qfn, newest_first=newest_first, ym_lag=ym_lag, window=window)
    cache_put(rkey, rows, str(asof or "")[:10])
    return rows, reads


def _period_dates(rows: list, ts, values: list, collapse) -> list:
    """The PERIOD axis parallel to the collapsed values -- what each value is a value OF.

    THE ORDER MIRRORS ``cascade._pace_period_key``, deliberately and in the same sequence, because that
    is the key the collapse actually grouped on: a date axis derived by a different rule would label the
    collapsed values with the wrong periods and every change window would name a span it did not
    measure. The one ADDITION is the ``period`` label, ahead of ``knowledge_date``: on a marketing-year
    vintage card (silver_psd and its twenty siblings) every row of one release shares ONE knowledge date,
    so labelling those rows by it would print the release stamp where the reader expects the marketing
    year -- and the marketing year is the thing the value belongs to.

    A collapsed cross-section has ONE value per period, so its axis is the DISTINCT period labels in row
    order. Where the two lengths still disagree -- a card whose period key this function cannot
    reproduce -- the axis is trimmed or padded with a NULL rather than guessed: a blank date on a
    rendered row is visible, and a plausible wrong one is not.

    **THE NULL IS ``None`` AND NOT ``""``, and that is the S4 fix.** The reason above is unchanged; the
    VALUE is. ``pgnumbers._stringify`` renders every NULL cell as the empty string to match Athena, so a
    served row with no date column at all produced ``""`` here, ``""`` rode the array into
    ``analogs._window_end`` and ``int(iso[0:4])`` raised -- MEASURED as
    ``ValueError: invalid literal for int() with base 10: ''`` on 140 of 144 board runs in the in-VPC S4
    pass (job 7a0f90a9). ``None`` is the absence every consumer in this package already tests for; the
    empty string is a string that reaches an int()."""
    out: list = []
    seen: set = set()
    for i, r in enumerate(rows):
        d = None
        for k in ("data_date", "week_ending_date", "date", "report_date"):
            d = TR.date_or_none(r.get(k))
            if d is not None:
                break
        if d is None and TR.date_or_none(r.get("year")) is not None:
            try:
                d = (f"{int(r['year']):04d}-{int(r['month']):02d}"
                     if TR.date_or_none(r.get("month")) is not None else f"{int(r['year']):04d}")
            except (TypeError, ValueError):
                d = TR.date_or_none(r.get("year"))
        if d is None:
            for k in ("period", "knowledge_date", "contract_month"):
                d = TR.date_or_none(r.get(k))
                if d is not None:
                    break
        d = d[:10] if d else None
        if d and d in seen and collapse:
            continue
        seen.add(d)
        out.append(d)
    # ONE ALIGNMENT RULE, and it lives in ``transforms.align_axis`` rather than here. This branch and
    # ``clean_pairs``' own zip disagreed about which end a surplus label comes off (front here, back
    # there); the rule and its two reasons are stated once in that function and both builders take it.
    return TR.align_axis(values, out)


def _since_date(dates: list, run_len: int) -> Optional[str]:
    i = len(dates) - 1 - int(run_len)
    return dates[i] if 0 <= i < len(dates) else (dates[0] if dates else None)


def _period_noun(cadence: str, n: int) -> str:
    noun = {"daily": "session", "weekly": "week", "weekly_destination": "week", "biweekly": "fortnight",
            "monthly": "month", "annual": "marketing year", "release": "release"}.get(cadence, "period")
    return noun if n == 1 else (noun + "s")


def _window_note(cadence: str, win: int) -> str:
    if not win:
        return f"{cadence}: no standing window declared (revision counts only)"
    return f"{win} {_period_noun(cadence, win)}"


def _convention_label(conv: dict, out: StateRow, bundle: dict, bkey: str, derivs: list) -> Optional[dict]:
    """The desk-convention LABEL, ORDERING ONLY (sec 2.4, ruling 1). Which reading a kind is measured on
    is the CONFIG's declaration, read here and never inferred: ``abs_bands`` reads the RAW level (ONI's
    ``z`` is a degC anomaly in the series' own unit, never a sigma -- which is exactly why the config
    keeps that kind separate although the arithmetic agrees with ``z_bands``), ``z_bands`` reads the
    computed z, ``percentile_bands`` reads the computed percentile, and ``pace_vs_prior_year`` reads a
    signed percent against the prior year.

    THE GRADED READING GETS ITS OWN BUNDLE ENTRY, and that is not bookkeeping: a derivation whose input
    reference said "the last value of the series" while the number actually graded was a z would
    RE-EXECUTE TO A DIFFERENT ANSWER -- the one thing a derivation record may never do. So the reading is
    written into the bundle under ``<series key>#<kind>`` and the record points at it, which makes the
    convention label as reproducible as every other figure on the row."""
    kind = str(conv.get("kind") or "")
    bands, labels = conv.get("bands") or [], conv.get("labels") or []
    if kind == "abs_bands":
        value = out.level
    elif kind == "z_bands":
        value = None if not out.z or out.z.get("declined") else out.z.get("value")
    elif kind == "percentile_bands":
        value = None if not out.percentile or out.percentile.get("declined") else out.percentile.get("value")
    elif kind == "pace_vs_prior_year":
        ppy = CADENCE_PERIODS_PER_YEAR.get(out.cadence, 12)
        pace, prec = TR.run_transform("pace_vs_prior", bundle, key=bkey, params={"periods_per_year": ppy})
        derivs.append(prec)
        value = None if pace["declined"] else pace.get("pct_change")
    else:
        return {"label": None, "band": None, "source": conv.get("verified"),
                "declined": f"unknown band kind {kind!r}"}
    value = TR.num_or_none(value)
    if value is None:
        return {"label": None, "band": None, "source": conv.get("verified"),
                "declined": f"{kind} needs a reading this row could not measure"}
    rkey = f"{bkey}#{kind}"
    # THE DATE AXIS CARRIES THE LEVEL'S OWN DATE OR A NULL. It used to carry ``""`` for an undated
    # level, which is a string this package then had to parse; ``regime_flag`` reads only the ``last``
    # selector off ``values`` and never touches this axis, so the null costs the transform nothing and
    # costs the next reader a raise.
    bundle[rkey] = {"values": [float(value)], "dates": [TR.date_or_none(out.level_date)],
                    "unit": out.unit}
    res, rec = TR.run_transform("regime_flag", bundle, key=rkey,
                                params={"kind": kind, "bands": list(bands), "labels": list(labels)})
    derivs.append(rec)
    return {"label": res.get("value"), "band": res.get("band"), "matched": bool(res.get("matched")),
            "kind": kind, "reading": value, "source": conv.get("verified")}


#: Calendar days per period, per cadence -- the ``age_periods`` divisor of sec 1.2's recency block.
#: APPROXIMATE BY CONSTRUCTION and rounded DOWN, which is the safe direction: "at least two months
#: stale" never overstates freshness. A cadence with no standing period (``release``) has no periods to
#: count and the field is None rather than a number nobody can check.
def _recency(out: StateRow, asof: str, ts, cadence: str = "") -> dict:
    age_days = None
    ref_date = out.knowledge_date or out.level_date
    try:
        if ref_date and len(ref_date) >= 10 and asof:
            age_days = (_dt.date.fromisoformat(asof[:10]) - _dt.date.fromisoformat(ref_date[:10])).days
    except ValueError:
        age_days = None
    per = CADENCE_DAYS.get(cadence or out.cadence)
    age_periods = int(age_days // per) if (age_days is not None and per) else None
    return {"age_days": age_days, "age_periods": age_periods, "level_date": out.level_date,
            "knowledge_date": out.knowledge_date,
            "publication_lag_days": int(getattr(ts, "publication_lag_days", 0) or 0),
            "ym_publication_lag_days": getattr(ts, "ym_publication_lag_days", None),
            "next_release": None}          # calendar.next_release() lands with the watch list (S3)


def _today() -> str:
    return _dt.date.today().isoformat()


# ---------------------------------------------------------------------------------------------------
# THE ANCHOR'S TAPE -- SB-T (sec 6.2, D19). ONE read per anchor board.
# ---------------------------------------------------------------------------------------------------
#: The SB-T change windows, in SESSIONS. The daily cadence's own row of sec 2.1's table, minus 252: a
#: 252-session change is a year on ONE delivery month, and no listed contract quotes that long with the
#: liquidity the front carries. Four windows, named in sessions, and every one of them SAME-CONTRACT.
TAPE_CHANGE_SESSIONS: tuple[int, ...] = (1, 5, 21, 63)

#: ``stats.percentile``'s own floor, restated as the tape row's so a rank the population cannot support
#: declines ``percentile_thin:<n>`` BY NAME rather than printing a percentile of four points.
TAPE_MIN_PERCENTILE_N = 8

TAPE_TABLE = "silver_futures_eod"
TAPE_METRIC = "settle"


def tape_state(slug: str, asof: str, *, qfn, newest_first: Any = "all",
               limit: int = READ_LIMIT) -> TapeState:
    """THE ANCHOR BOARD'S OWN PRICE PATH: the dated front settle, the four SAME-CONTRACT session changes
    and the level's percentile over the window this read actually fetched (sec 6.2, D19). ONE mirror
    read. NEVER RAISES -- every failure path is a :data:`TAPE_STATUS_WORDS` word and the reads it spent.

    IT IS THE ANCHOR'S TAPE, NEVER A DRIVER ROW. ``cascade_map.yaml``'s self-reference refusal binds
    DRIVER refs so that no board reads its own price as a driver of itself; this row is the anchor's own
    and is never a fan source, a convergence member or a ranked candidate (D25 admits the percentile as
    an analog DIMENSION, which is a different thing and S3's).

    THE FRONT MONTH IS NAMED BY THE SHIPPED RULE, NEVER GUESSED. ``query.select_front_expiry`` runs
    ``futures_roll.front_month`` under ``ROLL_RULE_VERSION`` and returns ``[]`` -- an honest, reasoned
    absence -- on an unmapped slug, a cash reference, an unlabelled curve row, or a frame whose rows do
    not carry the rule's own input. That empty is this row's ``front_decline``, by name.

    WHY THE SELECTOR IS HANDED THE NEWEST SESSION RATHER THAN THE WHOLE FETCH, and it is a fence rather
    than a convenience: that function fails CLOSED on a multi-session frame (``if not walkback_on and
    len(sessions) > 1: return []``), because "the front expiry" of a frame the front rolled inside is
    ambiguous. Slicing to the newest fetched session (a max over the session axis, deterministic, and
    that session's own date prints on the row) hands it exactly the single-session frame its shipped
    caller hands it. The EXPIRY is still chosen by the rule; only the SESSION is picked here.

    WHY THE CHANGES ARE NOT RUN THROUGH ``cascade._pace_front_expiry``, recorded as drift rather than
    left silent: that collapse declines WHOLE when the selection names more than one delivery month
    across the window -- i.e. whenever the front rolled inside it -- so on any window long enough to hold
    a 63-session change it would decline on nearly every board. The same-contract series here is the
    fetched rows FILTERED to the delivery month the rule already named, which needs no roll rule at all:
    one contract, one month, no splice. The two agree on what a same-contract change means; this one can
    also produce it.

    ONE READ, and the ledger says so. The percentile ranks the level inside THAT read's own window and
    ``window_note`` prints the window in sessions and dates, so the rank can never claim a span it did
    not measure."""
    out = TapeState(slug=str(slug or ""), asof=str(asof or ""))
    try:
        from leviathan.silver import futures_eod_contracts as FC
        floor = FC.PRICE_COVERAGE_START.get(out.slug)
    except Exception:                                   # noqa: BLE001 -- an unreadable roster is a decline
        floor = None
    if floor is None:
        # THE TEN TAPE-LESS BOARDS, by name (bar B19). A board with no per-contract tape has no SB-T row
        # and says so; it never borrows a neighbour's tape and never falls back to the continuous card.
        out.status = "no_tape_slug"
        return out
    out.coverage_start = floor.isoformat() if hasattr(floor, "isoformat") else str(floor)
    if out.asof and out.asof[:10] < out.coverage_start:
        out.status = "pre_coverage"
        return out

    from leviathan.graphrag.numbers import query as Q
    from leviathan.graphrag.numbers.registry import load_registry
    try:
        ts = load_registry().get(TAPE_TABLE)
    except Exception:                                   # noqa: BLE001
        out.status = "read_error"
        return out
    spec = board_spec(TAPE_TABLE, TAPE_METRIC, out.slug, None, out.asof, "daily")
    if limit != READ_LIMIT:
        spec.limit = int(limit)
    try:
        rows = Q.run(spec, query_fn=qfn, futures_newest_first=newest_first, ym_lag=True)
    except BoardReadDecline as d:
        out.status, out.reads = d.status, 1
        return out
    except Exception:                                   # noqa: BLE001 -- a tape read may never break an answer
        out.status, out.reads = "read_error", 1
        return out
    out.reads = 1
    truncated = len(rows) >= int(spec.limit or READ_LIMIT)

    sessions = [d for d in (_session_date(r) for r in rows) if d]
    newest = max(sessions) if sessions else ""
    front = (Q.select_front_expiry([r for r in rows if _session_date(r) == newest], spec, ts)
             if newest else [])
    if not front:
        out.status = "front_decline"
        out.coverage = {"n_obs": len(rows), "history_start": min(sessions) if sessions else None,
                        "history_end": newest or None, "truncated": truncated}
        return out
    f = front[0]
    out.contract_month = str(f.get("contract_month") or "")[:7]
    out.unit = str(f.get("unit") or "")
    out.currency = str(f.get("currency") or "")
    out.settle_kind = str(f.get("settle_kind") or "")
    out.roll_method = str(f.get("roll_method") or "")
    out.roll_rule_version = str(f.get("roll_rule_version") or "")

    # THE SAME-CONTRACT SERIES: the fetched rows for the month the rule named, one value per session.
    by_date: dict = {}
    for r in rows:
        if str(r.get("contract_month") or "")[:7] != out.contract_month:
            continue
        d = _session_date(r)
        if not d or d > newest:
            continue
        try:
            by_date[d] = float(str(r.get("value")).replace(",", ""))
        except (TypeError, ValueError):
            continue
    dates = sorted(by_date)
    values = [by_date[d] for d in dates]
    out.level, out.level_date = (values[-1] if values else None), (dates[-1] if dates else None)
    out.coverage = {"n_obs": len(values), "history_start": dates[0] if dates else None,
                    "history_end": dates[-1] if dates else None, "truncated": truncated}
    out.window_note = (f"{len(values)} sessions on {out.contract_month}"
                       + (f", {dates[0]} to {dates[-1]}" if dates else "")
                       + (f"; the read came back at its {spec.limit}-row cap" if truncated else ""))

    key = f"{out.slug}|{out.contract_month}"
    bundle = {key: {"values": values, "dates": dates, "unit": out.unit}}
    derivs: list = []
    for w in TAPE_CHANGE_SESSIONS:
        label = f"{w} {'session' if w == 1 else 'sessions'}"
        ch, rec = TR.run_transform("window_change", bundle, key=key,
                                   params={"t1": -(w + 1), "t2": -1, "window_label": label})
        derivs.append(rec)
        out.changes.append({"window": label, "n_periods": w, "declined": ch["declined"],
                            "reason": ch.get("reason"),
                            "from_date": dates[-(w + 1)] if len(dates) > w else None,
                            "to_date": dates[-1] if dates else None,
                            "delta": ch.get("value"), "pct": ch.get("pct_change")})
    if len(values) >= TAPE_MIN_PERCENTILE_N:
        p, rec = TR.run_transform("percentile", bundle, key=key)
        derivs.append(rec)
        out.percentile = p
    else:
        # the SHAPE a transform decline carries, so a consumer reads one dict shape whether the leaf
        # ran or the floor refused; NO derivation record, because nothing was computed
        out.percentile = {"stat": "percentile", "declined": True, "value": None,
                          "reason": f"{len(values)} sessions on this contract; a rank needs "
                                    f"{TAPE_MIN_PERCENTILE_N}"}
        out.status = f"percentile_thin:{len(values)}"
    if all(c["declined"] for c in out.changes):
        out.status = f"changes_thin:{len(values)}"
    out.derivation, out.inputs = derivs, bundle
    return out


def _session_date(row: dict) -> str:
    """The session axis of a tape row, in ``query._SESSION_ALIASES``' own priority. Borrowed rather than
    re-typed: query.py MINTS these aliases, and a second copy here would drift the day a card's date
    column changes role -- ``silver_futures_eod`` serves ``trade_date`` as BOTH its date and its
    knowledge date, so ``_extras`` emits ``knowledge_date`` and no ``data_date`` at all, and a
    hand-written ``data_date`` lookup would find nothing on every row of the one card this is for."""
    from leviathan.graphrag.numbers.query import _SESSION_ALIASES
    for a in _SESSION_ALIASES:
        v = (row or {}).get(a)
        if v not in (None, ""):
            return str(v)[:10]
    return ""


# ---------------------------------------------------------------------------------------------------
# THE OFFLINE HARNESS PATH (S1 item g)
# ---------------------------------------------------------------------------------------------------
def state_from_arrays(ref: str, values, dates, *, cadence: str = "monthly", asof: str = "",
                      commodity: str = "_global", country: str = "", unit: str = "",
                      narrate_unit: str = "", scale: float = 1.0, windows: Optional[dict] = None,
                      convention: Optional[dict] = None, is_flag: bool = False,
                      knowledge_date: Optional[str] = None, table: str = "",
                      metric: str = "") -> StateRow:
    """Build a StateRow from FIXTURE ARRAYS -- no store, no SQL, no network.

    THE TRANSFORM HALF ALONE, and that is the point: the decks that grade the board's arithmetic (the
    deterministic bars of sec 10.2) must run on a laptop with no pg mirror, and a bar that can only be
    measured in-VPC is a bar nobody runs. The READ half is exercised separately through
    :func:`fixture_query_fn`, which compiles the real SQL against a canned executor -- between the two,
    every line of the producer is reachable offline.

    It is NOT a second producer: every measure below is the same ``TRANSFORM_REGISTRY`` call
    :func:`series_state` makes, in the same order, writing the same derivation records."""
    key = SeriesKey(ref=ref, commodity=commodity, country=country)
    out = StateRow(key=key, asof=asof, table=table or ref, metric=metric or ref, cadence=cadence,
                   unit=unit, narrate_unit=narrate_unit, scale=scale)
    # THE SAME NULL BOUNDARY THE SERVED PATH TAKES (``transforms.clean_pairs``), and it is not a
    # convenience here: the arrays this builder is handed offline are the MIRROR'S OWN shape in the
    # ``mirror_nulls`` fixture set, where a NULL cell is ``""``. ``[float(v) for v in values]`` raised
    # ``could not convert string to float: ''`` on one blank cell and the walk fenced the whole series
    # into a ``read_error`` row -- a real column silently demoted by one hole.
    vals, ds, drops = TR.clean_pairs_counted(values, dates)
    n_null = drops["null"]
    if not vals:
        # ALL-BLANK IS AN EMPTY READ WITH ITS OWN WORD, the same one ``series_state`` uses, so a
        # fixture column of nulls and a served column of nulls render the same sentence.
        # A COLUMN OF DEFECTS IS NOT A COLUMN OF NULLS, and the qualifier says which. The closed WORD
        # is `read_empty` either way (`status_word` splits at the colon), so every consumer branches
        # exactly as before; what changes is that an all-unparseable column -- a real read of a column
        # this package could not parse a single cell of -- no longer wears the word `blank`.
        out.status = ("read_empty:all_blank" if n_null
                      else ("read_empty:all_unparseable"
                            if (drops["unparseable"] or drops["bool"]) else "read_empty"))
        out.coverage_tier = "series_thin"
        return out
    win = history_window(cadence, table or ref, windows)
    out.window_note = _window_note(cadence, win)
    out.level, out.level_date = vals[-1], ds[-1]
    out.knowledge_date = knowledge_date or (ds[-1] if ds else None)
    out.knowledge_basis = "supplied by the fixture" if knowledge_date else "the observation's own date"
    out.coverage = {"first_obs": None, "n_obs": len(vals), "history_start": ds[0], "history_end": ds[-1],
                    "truncated": False, "dropped_null": int(n_null),
                    "dropped_unparseable": int(drops["unparseable"]),
                    "dropped_bool": int(drops["bool"]),
                    "undated_periods": sum(1 for d in ds if d is None)}
    bundle = {key.label(): {"values": vals, "dates": ds, "unit": unit}}
    bkey = key.label()
    derivs: list = []
    if is_flag:
        fe, rec = TR.run_transform("flag_events", bundle, key=bkey,
                                   params={"window_periods": max(1, win or 12)})
        derivs.append(rec)
        out.flag_state = (None if fe["declined"] else
                          {"last_event_date": fe["last_event_date"],
                           "events_in_window": fe["events_in_window"],
                           "periods_since": fe["periods_since"],
                           "window_periods": fe["window_periods"]})
        out.z = {"declined": True, "reason": "a z over a 0/1 flag series is a base rate, not a sigma"}
        out.percentile = {"declined": True,
                          "reason": "a rank inside a 0/1 flag series is that same base rate"}
    else:
        if win:
            z, rec = TR.run_transform("zscore", bundle, key=bkey, params={"window": win})
            derivs.append(rec)
            out.z = z
        p, rec = TR.run_transform("percentile", bundle, key=bkey)
        derivs.append(rec)
        out.percentile = p
        for direction in ("up", "down"):
            s, srec = TR.run_transform("streak", bundle, key=bkey, params={"direction": direction})
            derivs.append(srec)
            if not s["declined"] and s["value"] > 0:
                out.run = {"direction": direction, "length": s["value"],
                           "since_date": _since_date(ds, int(s["value"]))}
                break
    for w in CADENCE_CHANGE_WINDOWS.get(cadence, ()):
        label = f"{w} {_period_noun(cadence, w)}"
        ch, rec = TR.run_transform("window_change", bundle, key=bkey,
                                   params={"t1": -(w + 1), "t2": -1, "window_label": label})
        derivs.append(rec)
        out.changes.append({"window": label, "n_periods": w, "declined": ch["declined"],
                            "reason": ch.get("reason"),
                            "from_date": ds[-(w + 1)] if len(ds) > w else None, "to_date": ds[-1],
                            "delta": ch.get("value"), "pct": ch.get("pct_change")})
    if convention:
        out.convention = _convention_label(convention, out, bundle, bkey, derivs)
    out.derivation = derivs
    out.inputs = bundle
    if len(vals) < 8:
        out.status = f"thin_history:{len(vals)}"
    out.coverage_tier = coverage_tier(map_row={"table": table or ref}, silver_status="available",
                                      status=out.status, n_obs=len(vals))
    return out


def re_execute_row(row: StateRow) -> list:
    """Re-run every derivation this row carries against the row's OWN input bundle. Returns the
    mismatches by name; empty == every figure on the row reproduces from the rows it was computed from.

    This is the S1 half of the V2 verifier rule (sec 2.5 lint clause 3), and it is a PUBLIC entry point
    rather than a test helper for one reason: the same call is what a board census runs over a rendered
    board, and a proof that only the tests can run is a proof nobody runs in production."""
    return TR.re_execute_all(row.derivation, row.inputs)


# ---------------------------------------------------------------------------------------------------
# THE TEXT FEEDER (sec 2.2) -- a RANK and a ROW, never a retrieval path.
# ---------------------------------------------------------------------------------------------------
#: The rank weights. CONSTANTS, stamped on the trace and never tuned inside a sitting without a panel.
SPECIFICITY_WEIGHT = 0.6
RECENCY_WEIGHT = 0.4
RECENCY_HORIZON_DAYS = 730
NAMED_BONUS = 0.25
TOP_RECEIPTS = 3

_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the to was were with".split())


def _content_tokens(text: str) -> list:
    import re
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in _STOPWORDS and len(t) > 2]


def rank_receipt(receipt: dict, *, evidence_query: str, node_id: str, asof: str,
                 slice_terms=()) -> Receipt:
    """One receipt's rank: ``0.6 * specificity + 0.4 * recency``.

    ``specificity`` is the share of the evidence_query's CONTENT tokens present in the receipt, plus
    0.25 when the node's id (underscores to spaces) or one of its slice's ``driver_slices.yaml`` terms
    appears -- the ``named`` test ``planner.ground`` already runs, borrowed rather than re-invented.
    ``recency`` is ``1 - min(age_days, 730)/730``: a linear decay to a flat floor, so a five-year-old
    prop and a ten-year-old prop rank the same on recency and are separated by what they SAY.

    WHAT THE RANK NEVER DOES (sec 2.2): decide whether a node is on the board -- every node is -- or gate
    a mechanism on a receipt COUNT. One mechanism-narrating receipt is enough; frequency floors deny the
    tail."""
    text = str(receipt.get("text") or "")
    low = text.lower()
    qt = _content_tokens(evidence_query)
    hits = sum(1 for t in set(qt) if t in low)
    spec = (hits / len(set(qt))) if qt else 0.0
    named = (str(node_id or "").replace("_", " ").lower() in low
             or any(str(t).lower() in low for t in (slice_terms or ())))
    if named:
        spec = min(1.0, spec + NAMED_BONUS)
    date = str(receipt.get("date") or "")[:10]
    rec = 0.0
    try:
        if date and asof:
            age = (_dt.date.fromisoformat(asof[:10]) - _dt.date.fromisoformat(date)).days
            rec = 1.0 - (min(max(age, 0), RECENCY_HORIZON_DAYS) / float(RECENCY_HORIZON_DAYS))
    except ValueError:
        rec = 0.0
    return Receipt(date=date, source=str(receipt.get("source") or ""), text=text,
                   specificity=round(spec, 4), recency=round(rec, 4), named=named,
                   rank=round(SPECIFICITY_WEIGHT * spec + RECENCY_WEIGHT * rec, 4))


def text_state(node, *, asof: str, evidence_query: str = "", receipts=None,
               slice_terms=(), fetched: bool = False) -> TextState:
    """The node's TEXT state: its ALREADY-FETCHED receipts, ranked, with the summary a node row carries.

    ZERO NEW RETRIEVAL, and that is a costed decision (sec 2.2, desk_cost F1). Revision 1 of the design
    called ``evidence.retrieve(k=3)`` per unfilled node; under ``EVIDENCE_BACKEND=pg`` that routes to
    ``pgstore.pg_retrieve``, which EMBEDS the query and borrows the EVIDENCE pool -- the pool that owns
    the ~2 s warm fill every turn depends on. So in phase 1b a node the walk reached but ``ground()`` did
    not fill says "no receipt fetched this turn" (``status: no_receipt_fetched``), one instrument in arm
    A; in phase 3 those nodes are handed to ``grounded_subgraph`` as must-admit nodes in their own
    bounded pot and their receipts arrive through ``ground()``'s OWN fill. The only board-initiated
    retrieval in V1 is the counted analog receipt read (S3).

    A node with ZERO receipts is a ROW THAT SAYS SO (``status: no_receipts``), never a silence."""
    recs = list(receipts) if receipts is not None else list(getattr(node, "evidence", None) or [])
    nid = str(getattr(node, "id", "") or "")
    q = evidence_query or str((getattr(node, "prior", None) or {}).get("evidence_query") or "")
    if not recs and not fetched:
        # THE TWO ABSENCES ARE DIFFERENT FACTS AND THE ROW SAYS WHICH. `no_receipts` is the STRONGER
        # claim -- a fill ran over this node and the corpus had nothing -- and only the caller knows
        # whether it ran: `ground()` fills the 5-slice cap of `_active_drivers` and `GroundedNode.evidence`
        # defaults to `[]`, so an empty list alone cannot tell "looked and found none" from "never
        # looked". Unfetched is therefore the DEFAULT reading of an empty list, and `fetched=True` is the
        # caller asserting the fill ran. (The first S1 cut wrote `if recs is None:` after a `or []` that
        # can never produce None -- the branch was unreachable and the word advertised but unusable.)
        return TextState(node_id=nid, n=0, status="no_receipt_fetched")
    ranked = sorted(
        (rank_receipt(r, evidence_query=q, node_id=nid, asof=asof, slice_terms=slice_terms) for r in recs),
        key=lambda r: (-r.rank, r.date, r.source))
    dates = sorted(d for d in (r.date for r in ranked) if d)
    return TextState(node_id=nid, n=len(ranked),
                     newest_date=(dates[-1] if dates else None),
                     oldest_date=(dates[0] if dates else None),
                     top=ranked[:TOP_RECEIPTS],
                     status=("ok" if ranked else "no_receipts"))


# ---------------------------------------------------------------------------------------------------
# THE READ-SPAN PIN, AT IMPORT (the read-span landing)
# ---------------------------------------------------------------------------------------------------
# THIS ONE **DOES** RUN AT IMPORT, and the difference from the cascade-import pin above is the cost of
# running it: `check_cascade_imports` has to import cascade.py and would hand every consumer of this
# package that module's whole graph, while this reads three dicts that are literals in this same file.
# It can therefore only ever fire on an EDIT of those literals -- which is exactly the event it exists
# for. A `raise` and not an `assert`: `python -O` strips an assert, and a fence that a flag can remove
# is not a fence. The message names the cadence and both numbers, so the edit that broke it is the edit
# the traceback describes.
_READ_SPAN_PROBLEMS = check_read_spans()
if _READ_SPAN_PROBLEMS:                                   # pragma: no cover -- fires only on a bad edit
    raise RuntimeError("state/feeders: the read span must exceed the history window by the cadence's "
                       "publication slack -- " + "; ".join(_READ_SPAN_PROBLEMS))

# The import-time pin (sec 2.1, critic G21). It runs on the LINT path, not on import of this module,
# because importing cascade.py here would hand every consumer of this package that module's whole graph.
__all__ = [
    "CASCADE_IMPORTS", "check_cascade_imports", "board_map", "board_map_row", "board_read_refs",
    "series_state", "tape_state", "text_state", "rank_receipt", "state_from_arrays", "re_execute_row",
    "fixture_query_fn", "board_query_fn", "BoardReadDecline", "mirror_epoch", "state_cache_key",
    "series_read_key",
    "cache_get", "cache_put", "cache_clear", "cadence_of", "history_window", "derive_knowledge_date",
    "board_spec", "read_span", "read_span_periods", "check_read_spans", "CADENCE_READ_SLACK",
    "CADENCE_CHANGE_WINDOWS", "CADENCE_HISTORY_WINDOW", "CADENCE_READ_SPAN", "CADENCE_PERIODS_PER_YEAR",
    "CADENCE_DAYS", "DESTINATION_GRAIN_TABLES", "READ_LIMIT", "VINTAGE_NOTE", "LATEST_ONLY_CARDS",
    "STATE_CACHE_MAX", "TAPE_CHANGE_SESSIONS", "TAPE_MIN_PERCENTILE_N", "TAPE_TABLE", "TAPE_METRIC",
]
