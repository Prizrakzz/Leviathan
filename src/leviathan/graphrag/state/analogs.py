"""ANALOGS BY STATE -- STATE ENGINE DESIGN sec 4 whole (owner ruling 4). Sitting S3.

  4.1 historical state vectors from the arrays ALREADY IN MEMORY -- zero reads
  4.2 likeness on the loud drivers' state vector: no scalar loudness score, no weighted distance
  4.3 the outcome over the lag band at BOTH ENDS -- leg A ships, leg B rides its own rider
  4.4 text receipts EXPLAIN; absence is said plainly, and event analogs come from ``flag_events``
  4.5 the rows render under ``## The record``, never under ``## Episodes``

THE ONE SENTENCE. An analog is a PAST STATE OF THE SAME SERIES chosen by how much its own numbers
looked like today's, and what the record then measured over the band the graph declares -- never a
document that reminded someone of now, and never a forecast.

FIVE PROPERTIES THIS MODULE EXISTS TO MAKE STRUCTURAL:

  1. **SELECTED FROM NUMERIC HISTORY, NOT FROM TEXT** (ruling 4). Candidates are CROSSINGS on the
     series -- the start of a run, or the first observation past a declared desk line -- and the
     distance is arithmetic over ``rolling_zscore``. Receipts EXPLAIN a chosen date; they never choose
     one. The text-episode library stays a receipt producer and its rebuild is retired.
  2. **KNOWABLE AT t.** Every historical state is computed over the PREFIX ``<= t - lag_days`` --
     ``stats.rolling_zscore``'s own prefix walk, then RE-INDEXED onto the knowledge axis by
     :func:`_knowable_indices`, so the vector position dated ``t`` carries the state of the newest
     print that had actually been PUBLISHED by ``t``. A crossing "at t" on MPOB stocks was knowable at
     t + 43 d, so the prefix stops where knowledge did and a past date is never ranked by information
     nobody held then. Every row prints "measured on the record as revised through {asof}" -- the true
     as-known-at-t vintage state is the V1.1 read shape and this label is the honest statement of that
     limit.
  3. **BOTH ENDS OF THE BAND** (sec 4.3). The outcome window is ``[t + 3*min_q, t + 3*max_q]`` months
     over the PARENT driver's declared band -- the only declared number, because a driver's ``lag`` is
     its own lag onto the contract's target metric and the parent-to-child lag is undeclared. A child
     whose parent declares no band says ``lag_undeclared_between_nodes``; a far board uses ITS OWN
     edge's band for the same parent, which is how one like state yields two horizons.
  4. **LIKENESS, NOT RECENCY** (bar B9). Recency breaks ties INSIDE an already-like pool and nowhere
     else, exactly as ``_cw_firings`` preserves it.
  5. **ONE MATCH STILL RENDERS.** The count rides the header in WORDS and is never a floor -- frequency
     floors deny the tail.

NO READS HAPPEN HERE. The monthly benchmark, the tape and the analog receipts arrive through INJECTED
callables whose seats wave 2 already priced (``walk.price_wave2``'s ``analog_benchmark`` /
``analog_receipts`` columns), so this module spends the budget the walk reserved and never opens one.
"""
from __future__ import annotations

from typing import Optional

from leviathan.graphrag.state import transforms as TR
from leviathan.graphrag.state.lagbands import QUARTER_MONTHS, LagBand, parse_lag
from leviathan.graphrag.state.rows import status_word

#: The cascade symbols LEG B reads, declared ONCE so a rename reds at import rather than at serve --
#: ``feeders.CASCADE_IMPORTS``' discipline, applied to the one other place this package reads that file.
#: Leg B is DARK (``GRAPHRAG_STATE_BOARD_ANALOG_TAPE``, D6) and rides behind the P2 span probe, so these
#: names are resolved only when a caller arms it.
CASCADE_ANALOG_IMPORTS: tuple = ("_cw_cell", "_cw_fences", "_cw_verdict_line", "_cw_cell_line",
                                 "CW_SPAN_MAX_DAYS")


#: THE OUTCOME ROW'S OWN DECLINE WORDS BEYOND THE LEG'S (09-24 fix round, CONTRACT K5), declared at their
#: ONE producer (:func:`outcome_over_band`) and seeded by name into the closed-vocabulary lint
#: (``state/lint.py`` clause 9) beside ``board.LEG_REASONS``, so the render owes each a sentence.
#: ``band_inside_one_print``: both ends of the band read the SAME observation of the series -- a band
#: shorter than the series' own cadence (annual Argentine production read at both ends of a two-quarter
#: band printed "moved 0.5 MMT by the time the lag opened and 0.5 MMT by the time it closed" under ONE
#: handle on the tariff page). One print is not two moves; the row declines with the reason.
OUTCOME_DECLINES: tuple = ("band_inside_one_print",)


def check_cascade_analog_imports() -> list:
    """Every name in :data:`CASCADE_ANALOG_IMPORTS` resolves. Returns the missing ones; empty == clean."""
    from leviathan.graphrag.numbers import cascade as casc
    return [n for n in CASCADE_ANALOG_IMPORTS if not hasattr(casc, n)]


# ---------------------------------------------------------------------------------------------------
# 4.1 THE HISTORICAL STATE VECTOR -- arithmetic over an array already fetched
# ---------------------------------------------------------------------------------------------------
def state_history(st, *, window: Optional[int] = None, lag_days: int = 0,
                  want_pct: bool = False) -> dict:
    """``{'dates', 'values', 'z', 'pct', 'window', 'lag_days', 'knowable'}`` -- the state AS KNOWABLE AT
    EACH date.

    ONE registered transform (``rolling_zscore``) over the row's OWN input bundle, so the vector this
    selector ranks against is the same arithmetic the row's printed z came from. ``None`` at a position
    is an honest hole (a prefix too short for the window, or one with no variance) and a candidate at a
    hole is never selected -- a distance against a missing z would rank a date by nothing.

    **THE KNOWLEDGE AXIS (sec 4.1), and it is a MEASURED correction to this module's first cut.** The
    prefix walk ends at ``t`` -- the OBSERVATION date -- and a card published ``lag_days`` later was not
    knowable then. The first cut used ``lag_days`` only as an admissibility filter against the AS-OF, so
    the property this docstring asserted was the one the code lacked: a candidate crossing was scored on
    a distribution containing prints nobody held on the day it is dated by. :func:`_knowable_indices`
    closes it by re-indexing the vector onto the knowledge axis -- position ``i`` carries the state of
    the newest observation whose own date is ``<= dates[i] - lag_days``. With ``lag_days == 0`` the map
    is the identity and this function is exactly what it was.

    **THE MAP ITSELF RIDES ON THE RESULT AS ``knowable`` (round 3, MAJOR B).** ``z`` and ``pct`` are
    re-indexed here; ``values`` is NOT, deliberately -- it is the series' own observations and the run
    and direction components are computed off it by :func:`_direction_at` / :func:`_run_at`. Those two
    read POSITIONS, so unless they are handed the map they read the move INTO observation ``i`` while
    the z beside them is the state knowable at ``dates[i]`` -- one position, two vintages, which is the
    exact defect round 2 closed on the "now" half. Publishing the map closes it on the "then" half at
    one O(n) walk per history instead of one per candidate (:func:`_knowable_map`).

    THE ASYMMETRY IS STATED RATHER THAN HIDDEN: ``z_now`` on the caller's ``dims`` is the ROW's own
    printed z, computed over every observation already published at the as-of, and a past position here
    is computed over every observation already published at ITS date. Both are "what a desk held then",
    which is the comparison sec 4.2 asks for; neither is the as-known-at-t VINTAGE state, which is the
    V1.1 ``collapse=False`` read shape (sec 1.4) and is why every stanza prints "measured on the record
    as revised through {asof}".

    The PERCENTILE vector is LAZY (``want_pct``) and is the same arithmetic ``stats.percentile`` does --
    see :func:`_prefix_percentiles` for why it is not a transform call per observation. It mints NO
    derivation record: the selection is not a printed figure, and the rows the selection produces each
    carry their own record (sec 2.5's rule is about RENDERED figures)."""
    key = st.key.label()
    arrays = (st.inputs or {}).get(key) or {}
    # THE NULL BOUNDARY, BEFORE THE PREFIX WALK (``transforms.dated_pairs``). The mirror renders a NULL
    # cell as ``""`` (``pgnumbers._stringify``), so a served array can carry a blank value or a blank
    # period label; ``float("")`` raises and a blank label rode into ``int(iso[0:4])`` and raised on 140
    # of 144 board runs in the in-VPC S4 pass. Both are dropped HERE, once, because everything below
    # this line places a position on a calendar: the knowledge axis, the candidate's closable window,
    # the cross-cadence join. A DROPPED NULL IS A HOLE, NOT A ZERO -- the observation leaves the array
    # rather than entering it as a value nobody read -- and the count rides on the dict so a stanza can
    # never be shorter than its own history without saying why.
    values, dates, drops = TR.dated_pairs_counted(arrays.get("values"), arrays.get("dates"))
    n_dropped = sum(drops[k] for k in TR.DROP_KINDS) + drops["undated"]
    win = int(window or (st.z or {}).get("window_n") or (st.z or {}).get("window") or 0)
    lag = max(0, int(lag_days or 0))
    # THE COUNT IS THE TOTAL AND THE BREAKDOWN RIDES BESIDE IT. `n_dropped_null` keeps its name and its
    # meaning (every position this history could not carry); `dropped` says WHICH -- a declared NULL, a
    # cell that did not parse (a DEFECT), a flag column, or a reading whose period label could not be
    # placed. `transforms.cell_kind` holds the reason the three are not one number.
    # THE KNOWLEDGE-AXIS MAP RIDES ON THE HISTORY (round 3, MAJOR B). It was a local of this function,
    # so the two components that are NOT re-indexed here -- direction and run, which are read off
    # ``values`` -- had no way to reach it and were read on the OBSERVATION axis at a position whose z
    # and percentile were read on the KNOWLEDGE axis. MEASURED on the one lagged fixture card
    # (``b40_event / drought``, 25 days declared): the direction differed from the one knowable at that
    # position on 292 of 440 positions and the run length on 257. Carrying the map means every reader
    # of this history places a component on the same axis, ONCE, without an O(n) walk per candidate.
    idx = _knowable_indices(dates, lag)
    out = {"dates": dates, "values": values, "z": [None] * len(values), "pct": [None] * len(values),
           "window": win, "lag_days": lag, "n_dropped_null": int(n_dropped),
           "knowable": idx,
           "dropped": {k: int(v) for k, v in drops.items()}}
    if not values:
        return out
    z_raw: list = [None] * len(values)
    if win:
        # THE TRANSFORM RUNS OVER THE CLEANED ARRAY, never ``st.inputs``. Running it over the raw bundle
        # would return a vector as long as the UNCLEANED series, and every index below -- the knowable
        # map, the crossing, the tie-break -- would then read a z belonging to a different observation.
        # The window PARAMETER does not move: the rolling window is still ``win`` periods of the array
        # it is given, which is sec 4.1's own semantics with the holes taken out.
        clean = {key: {"values": values, "dates": dates, "unit": arrays.get("unit") or ""}}
        res, _rec = TR.run_transform("rolling_zscore", clean, key=key, params={"window": win})
        if not res.get("declined"):
            z_raw = list(res.get("series") or [])
    out["z"] = [(None if j is None or j >= len(z_raw) else z_raw[j]) for j in idx]
    if want_pct:
        pct_raw = _prefix_percentiles(values)
        out["pct"] = [(None if j is None else pct_raw[j]) for j in idx]
    return out


def axis_date(label) -> Optional[str]:
    """A period label as the CALENDAR DATE the observation is dated by -- ``None`` when it is not one.

    THE THREE FORMS ``feeders._period_dates`` CAN WRITE, and each maps to the date the LIVE READ dates
    that observation by (sec 1.4, D21): an ISO day rides as itself; a ``year_month`` card's ``YYYY-MM``
    is its MONTH-END, because the card has no date column and ``query._ym_lagged_asof_ym`` admits a data
    month only once ``month_end(M) + lag <= asof``; a bare ``YYYY`` is that year's 31 December.

    WHY THIS FUNCTION EXISTS AT ALL, MEASURED at the S3 re-fix. The knowledge axis compared the RAW
    LABEL against a computed ISO cut, and a raw ``YYYY-MM`` sorts as the month's FIRST instant --
    ``"2026-01" <= "2026-01-31"`` is a prefix comparison and is True. That is precisely the leak D21
    closes on the read side: a data month admitted from the first day it is *about* rather than the day
    it is *published*. The analog history and the live read must place a month on the same day, or the
    lag they each apply is a lag against a different axis."""
    s = str(label or "")[:10]
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s
    if len(s) == 7 and s[4] == "-":
        try:
            return _month_end(int(s[:4]), int(s[5:7]))
        except ValueError:
            return None
    if len(s) == 4 and s.isdigit():
        return "%s-12-31" % s
    return None


def _month_end(year: int, month: int) -> str:
    import datetime as _dt
    return (_dt.date(year + (month // 12), (month % 12) + 1, 1) - _dt.timedelta(days=1)).isoformat()


def _knowable_indices(dates, lag_days: int) -> list:
    """For each position, the index of the newest observation PUBLISHED by that position's own date.

    The card's publication lag is the only thing that separates "the print is dated t" from "anyone
    could read it at t" (sec 1.4). ``lag_days == 0`` returns ``range(n)`` -- the identity -- so a card
    that publishes on its observation date is unaffected, and every deck that states a vector by hand
    keeps the arithmetic it stated.

    BOTH SIDES OF THE COMPARISON GO THROUGH :func:`axis_date`, so a ``year_month`` card's months are
    placed on their month-ENDS -- the same day the live read places them on -- rather than compared as
    raw labels. A label this function cannot place is a HOLE (``None``), never a silently admitted row."""
    n = len(dates)
    if int(lag_days or 0) <= 0:
        return list(range(n))
    import datetime as _dt
    axis = [axis_date(d) for d in dates]
    out: list = []
    j = -1
    for i in range(n):
        if axis[i] is None:
            out.append(None)
            continue
        cut = (_dt.date.fromisoformat(axis[i]) - _dt.timedelta(days=int(lag_days))).isoformat()
        while j + 1 < n and axis[j + 1] is not None and axis[j + 1] <= cut:
            j += 1
        out.append(j if j >= 0 else None)
    return out


def _knowable_map(hist: dict) -> list:
    """The history's knowledge-axis index map, read off the dict or computed ONCE and cached on it.

    THE CACHE IS THE POINT AND NOT AN OPTIMISATION DETAIL. :func:`likeness` runs once per CANDIDATE and
    the relaxed pool is the record itself, so deriving the map inside it would be an O(n) walk per
    candidate per dimension -- O(n^2) on a 440-month card, which is the cost the widening must not buy.
    :func:`state_history` already publishes it as ``knowable``; this function exists for the histories
    the decks, the census and :func:`_price_dimensions` state BY HAND, where the map is absent and the
    honest answer is to derive it from the dict's own ``dates`` and ``lag_days`` rather than to assume
    the identity. With ``lag_days == 0`` it IS the identity, so a hand-stated vector keeps the exact
    arithmetic it stated."""
    dates = hist.get("dates") or ()
    idx = hist.get("knowable")
    lag = int(hist.get("lag_days") or 0)
    # ROUND-3 REVIEW MINOR 4: the cache guard keys on the lag as well as the length, so a history whose
    # ``lag_days`` moved in place can never serve a stale map (unreachable today; the class is closed).
    if isinstance(idx, list) and len(idx) == len(dates) and hist.get("knowable_lag") == lag:
        return idx
    idx = _knowable_indices(dates, lag)
    hist["knowable"] = idx
    hist["knowable_lag"] = lag
    return idx


def _knowable_at(hist: dict, i: Optional[int]) -> Optional[int]:
    """The index of the newest observation KNOWABLE at position ``i`` -- ``None`` where there is none.

    ``None`` is a HOLE and is never silently replaced by ``i``: a position earlier than the card's own
    publication lag had NO reading behind it, and answering with the observation dated there is the
    anachronism this map exists to refuse."""
    if i is None:
        return None
    idx = _knowable_map(hist)
    if i < 0 or i >= len(idx):
        return None
    return idx[i]


def _prefix_percentiles(values) -> list:
    """``stats.percentile`` at EVERY prefix, in one sorted pass -- ``None`` below the module's own floor.

    IT IS THE SAME ARITHMETIC AND NOT A SECOND CALCULATOR: midrank
    ``100 * (below + 0.5 * equal) / n`` over ``values[: i + 1]``, refusing below
    ``stats.MIN_PERCENTILE_N``, which is ``stats.percentile``'s own definition read off the function
    rather than restated. The deck pins the two against each other on a fixture.

    WHY NOT ONE TRANSFORM CALL PER OBSERVATION, which is what the first cut did: that is O(n^2) and it
    MEASURED at 1.94 s for ONE five-thousand-point daily series -- the row cap sec 2.1 sets for a daily
    ref such as ``cbot_board_crush_margin``. ``analog_rows`` builds one vector per seed (five on
    Cascade, so about ten seconds) and :func:`co_loud_analogs` builds one per ANCHOR CONTRACT (thirty-one
    positioning scopes on the amended driver-as-subject anchor, about a minute) -- against sec 7's
    stated "+0 to +4 s pre-writer" for the whole board. This pass is O(n log n) and the vector is LAZY
    besides: only a row whose convention is ``percentile_bands``, and the co-loud decile test, ever ask
    for it."""
    import bisect

    from leviathan.graphrag.numbers import stats as _st
    floor = int(getattr(_st, "MIN_PERCENTILE_N", 8))
    out: list = []
    seen: list = []
    for i, v in enumerate(values):
        x = TR.num_or_none(v)
        if x is None:
            # A CELL WITH NO READING IS A HOLE IN THE VECTOR AND NOT A MEMBER OF THE POPULATION: it is
            # neither ranked nor counted against the floor. The position is KEPT so the vector stays
            # parallel to its own dates -- dropping it here would shift every later rank onto the wrong
            # observation. (`state_history` has already dropped these; this is the guard for a caller
            # that hands a raw array straight in.)
            out.append(None)
            continue
        bisect.insort(seen, x)
        # THE POPULATION IS WHAT WAS ACTUALLY READ, and that is what the floor is a floor ON. ``i + 1``
        # counts the positions walked, holes included, so a prefix of eight positions holding six
        # readings would have passed ``MIN_PERCENTILE_N`` on six -- the refusal floor moving because a
        # cell was blank. ``len(seen)`` is the same number on an array with no holes in it (which is
        # every array ``state_history`` hands in) and the honest one on any other.
        n = len(seen)
        if n < floor:
            out.append(None)
            continue
        below = bisect.bisect_left(seen, x)
        equal = bisect.bisect_right(seen, x) - below
        out.append(100.0 * (below + 0.5 * equal) / n)
    return out


def percentile_vector(hist: dict) -> list:
    """The prefix-percentile vector for a state history, computed ON DEMAND and cached on the dict.

    The lazy half of the fix above: ``state_history`` fills ``pct`` only when its caller declares it
    needs one, and the two callers that do -- a ``percentile_bands`` crossing and the co-loud decile
    test -- come through here so the KNOWLEDGE-AXIS re-index is applied in exactly one place."""
    if any(p is not None for p in (hist.get("pct") or ())):
        return hist["pct"]
    raw = _prefix_percentiles(hist.get("values") or [])
    idx = _knowable_map(hist)
    hist["pct"] = [(None if j is None else raw[j]) for j in idx]
    return hist["pct"]


def _index_on_or_before(dates, t: str) -> Optional[int]:
    """The last observation on or before ``t``. The ONE join between two series on different cadences,
    and it is a floor rather than a nearest match: a monthly ONI read at a weekly date must never
    borrow the print that came AFTER the date being asked about."""
    best = None
    for i, d in enumerate(dates):
        if d and str(d)[:10] <= str(t)[:10]:
            best = i
        else:
            break
    return best


def _window_end(iso, months: int) -> Optional[str]:
    """The END OF THE MONTH ``months`` after ``iso`` -- the resolution a band declared in QUARTERS has.
    ``None`` when the label cannot be placed on the calendar.

    **IT GOES THROUGH :func:`axis_date`, AND THAT IS THE S4 NULL FIX.** The first cut sliced the string
    directly (``int(iso[0:4]), int(iso[5:7])``), which raises on the two labels this package actually
    carries at the edges: the mirror's blank (``""``, a NULL date column rendered by
    ``pgnumbers._stringify``) and the annual card's bare ``YYYY`` (whose ``[5:7]`` slice is empty). Both
    raised ``invalid literal for int() with base 10: ''``. ``axis_date`` is the one calendar in this
    module and it already knows all three label forms, so the window is built on the same day the read
    dates the observation by, and an unplaceable label yields a stated ``None`` rather than a raise.

    THE MONTH IS THE GRAIN AND THE DAY IS NOT, and the first cut got that wrong in the direction that
    LOSES an observation. ``_add_months`` preserves the day: six months after a 2000-11-30 print is
    2001-05-30, and a month-end series' May print (2001-05-31) is one day LATER -- so
    :func:`_index_on_or_before` fell back to APRIL and the "far end" of a one-to-two-quarter band was
    read five months out instead of six. A lag the graph states in quarters resolves to a month, so the
    window's end is that month's end and the month's own print is inside it."""
    placed = axis_date(iso)
    if placed is None:
        return None
    y, m = int(placed[0:4]), int(placed[5:7])
    total = (y * 12 + (m - 1)) + int(months)
    y2, m2 = total // 12, total % 12 + 1
    last = [31, 29 if (y2 % 4 == 0 and (y2 % 100 != 0 or y2 % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m2 - 1]
    return f"{y2:04d}-{m2:02d}-{last:02d}"


def _add_months(iso, months: int) -> Optional[str]:
    """ISO + N months, clamped to the month end. Pure arithmetic; ``walk`` holds the twin and both are
    the ``_cw_first_of_months`` discipline -- this package reads no clock. ``None`` on a label
    :func:`axis_date` cannot place, for :func:`_window_end`'s own reason."""
    placed = axis_date(iso)
    if placed is None:
        return None
    y, m, d = int(placed[0:4]), int(placed[5:7]), int(placed[8:10] or 1)
    total = (y * 12 + (m - 1)) + int(months)
    y2, m2 = total // 12, total % 12 + 1
    last = [31, 29 if (y2 % 4 == 0 and (y2 % 100 != 0 or y2 % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m2 - 1]
    return f"{y2:04d}-{m2:02d}-{min(d, last):02d}"


# ---------------------------------------------------------------------------------------------------
# 4.2 CANDIDATES -- crossings, so one episode yields ONE candidate
# ---------------------------------------------------------------------------------------------------
def crossings(hist: dict, *, convention: Optional[dict] = None, min_run: int = 1,
              any_month: bool = False, min_separation_months: int = 0) -> list:
    """Every CROSSING on this series: the start of a run, or the first observation past a declared desk
    line. Returns ``[{index, date, kind, band}]`` oldest first.

    ONE CANDIDATE PER EPISODE, which is the whole reason the candidate is a crossing and not "every
    month the state was high" (Draft B): a twelve-month El Nino would otherwise contribute twelve
    near-identical candidates and crowd out every other episode in the pool.

    **``any_month`` IS THE R3a RELAXATION (DESIGN C.1) AND IT IS THE DEFAULT OF NOBODY BUT
    :func:`select_analogs`.** The owner's rule is "candidates from ANY month, deduplicated per EPISODE",
    and this branch is the SECOND half of that sentence made exact: **it does not admit every month, it
    admits every EPISODE** -- one candidate at each maximal run's START, plus the first placeable
    position, plus every declared band crossing. MEASURED on the fixture histories that is 222 of 440
    positions on the ONI card and 338 of 440 on a white-noise one, which is the 2/3 a series that turns
    direction at random offers and not the 440 the words "every month" would promise (round 2, minor 1).
    The old
    ``min_run`` rule is what goes with it: comparing a past run's length against the run the series is
    in NOW is a FLOOR, and a floor denies the tail (house doctrine). The run length does not leave the
    selection -- it stays the second term of :func:`select_analogs`' tie-break, where it GRADES instead
    of gating. ``min_run`` survives as an explicit opt-in so the census and the null-boundary decks that
    state a floor by hand keep the arithmetic they stated; nothing in the serving path passes one.

    THE TWO BRANCHES DIFFER BY MORE THAN THE FLOOR, and the difference is the point. ``min_run`` mints a
    candidate only where the DIRECTION changes, so a series that sat flat for thirty months contributes
    nothing at all; ``any_month`` opens an episode at the first placeable position too, so a record whose
    only structure is a flat stretch still offers the reader a date. The convention-band crossings are
    UNTOUCHED in both branches -- a declared desk line is the one candidate rule the desk itself wrote.

    ``min_separation_months`` IS OFF BY DEFAULT AND :func:`select_analogs` LEAVES IT OFF. Thinning the
    pool here would walk the candidates in DATE order and drop the later member of every close pair --
    which is a DELETION of the most-like candidate whenever likeness and recency disagree, i.e. exactly
    the case bar B9 exists for. The same rule applied to the PICKED list runs in DISTANCE order and
    keeps the most-like member of an episode, which is why it lives there and why this knob exists only
    so a caller who wants the other shape can measure it rather than assume it."""
    values, dates = hist["values"], hist["dates"]
    out: list = []
    seen: set = set()

    def _add(i, kind, band=None):
        # A CANDIDATE THIS CALENDAR CANNOT DATE IS NOT A CANDIDATE. Every downstream filter is a
        # statement about the candidate's DATE -- "its outcome window has closed", "it was knowable at
        # t", "it is N months from the last pick" -- so a crossing at an unplaceable label could support
        # none of them, and admitting it is what put ``""`` in front of ``int(iso[0:4])``.
        if i in seen or i <= 0 or i >= len(dates) or axis_date(dates[i]) is None:
            return
        seen.add(i)
        # ``n_merged`` IS ALWAYS PRESENT AND IS ZERO WITH THE THINNING OFF (round 2, minor 5). It used to
        # be minted only by :func:`_merge_close_candidates`, so ``c["n_merged"]`` RAISED on the default
        # pool -- a key whose presence depended on a kwarg nobody passes. Zero is the true answer: no
        # candidate was folded onto this one.
        out.append({"index": i, "date": dates[i], "kind": kind, "band": band, "n_merged": 0})

    prev_sign = 0
    starts: list = []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        sign = 1 if d > 0 else (-1 if d < 0 else 0)
        if sign and sign != prev_sign:
            starts.append(i)
        if sign:
            prev_sign = sign
    band_hits: list = []
    if convention:
        kind = str(convention.get("kind") or "")
        bands = [b for b in (TR.num_or_none(x) for x in (convention.get("bands") or []))
                 if b is not None]
        readings = (percentile_vector(hist) if kind == "percentile_bands" else values)
        for b in bands:
            was = None
            for i, v in enumerate(readings):
                rv = TR.num_or_none(v)
                if rv is None:
                    continue
                now = _past_line(kind, rv, b, bands)
                if was is False and now:
                    band_hits.append((i, b))
                was = now
    if any_month:
        # THE DECLARED DESK LINE IS ADDED FIRST, AND THAT IS "kept as they are" MADE TRUE. ``_add``
        # refuses an index it has already minted, so with the episode starts first a crossing that lands
        # ON a turn would silently lose its ``band_crossing`` kind and its band to an ``episode_start``
        # -- MEASURED on the deck's own two-level fixture, where the one declared crossing vanished from
        # the band list entirely. Under the OLD rule the collision could not arise in the direction that
        # matters, so its order is left exactly where it was below.
        for i, b in band_hits:
            _add(i, "band_crossing", b)
        # THE FIRST PLACEABLE POSITION OPENS THE FIRST EPISODE. ``starts`` records DIRECTION CHANGES, so
        # without this line a record that opens with a flat or monotone stretch has no candidate until
        # its first turn -- and "any month" would then exclude the oldest months in the record, which is
        # the opposite of what the relaxation is for. ``_add``'s own guards still refuse index 0 (it has
        # no preceding observation and therefore no direction, no run and no delta) and any position
        # whose label this calendar cannot place.
        _add(1, "episode_start")
        for i in starts:
            _add(i, "episode_start")
    else:
        floor = max(1, int(min_run))
        for j, i in enumerate(starts):
            end = (starts[j + 1] - 1) if j + 1 < len(starts) else (len(values) - 1)
            if (end - i + 1) >= floor:
                _add(i, "run_start")
        for i, b in band_hits:
            _add(i, "band_crossing", b)
    out.sort(key=lambda c: c["index"])
    if int(min_separation_months or 0) > 0:
        out = _merge_close_candidates(out, int(min_separation_months))
    return out


def _merge_close_candidates(cands: list, months: int) -> list:
    """Candidates closer together than ``months`` COLLAPSE onto the older one, which carries the count.

    It COMPUTES rather than deletes in the only sense available to a date-ordered pass: the survivor
    stamps ``n_merged``, so a caller that thins the pool can still print how many months of one episode
    stood behind the date it shows. :func:`crossings` leaves it off for the reason its docstring gives.
    ``None`` from :func:`_months_between` is NO SEPARATION CONSTRAINT, as it is everywhere else here --
    an exclusion has to be earned by a measurement."""
    out: list = []
    for c in cands:
        if out:
            m = _months_between(out[-1]["date"], c["date"])
            if m is not None and abs(m) < int(months):
                out[-1]["n_merged"] = int(out[-1].get("n_merged") or 0) + 1
                continue
        out.append({**c, "n_merged": int(c.get("n_merged") or 0)})
    return out


def _past_line(kind: str, reading: float, band: float, bands) -> bool:
    """Has ``reading`` crossed ``band`` under the kind's own declared semantics? The same predicate
    ``watch.convention_distance`` asks, kept in one shape so a crossing and a distance can never
    disagree about which side of a line a reading sits on."""
    if kind in ("abs_bands", "z_bands"):
        return abs(reading) >= band
    if kind == "percentile_bands":
        return reading <= band if band < 50 else reading >= band
    if kind == "pace_vs_prior_year":
        lo, hi = (min(bands), max(bands)) if bands else (band, band)
        return reading <= lo if band == lo else reading >= hi
    return False


# ---------------------------------------------------------------------------------------------------
# 4.2 LIKENESS -- an unweighted distance over a WIDENED state vector, and every count a printed FACT
# ---------------------------------------------------------------------------------------------------
#: THE FOUR COMPONENTS OF THE STATE VECTOR (DESIGN C.1), declared once so the coverage the stanza prints
#: names the same four the distance reads, and so a fifth cannot arrive without moving this tuple.
STATE_COMPONENTS: tuple = ("z", "percentile", "direction", "run")

#: THE ONE THAT CARRIES A DISTANCE, and it is ONE because a distance compares a statistic against
#: ITSELF at another date (orchestrator ruling, round 2, MAJOR 1). ``rolling_zscore`` is a FIXED window
#: (sixty months on a monthly card), so ``z_t`` and ``z_now`` are the same statistic at every index and
#: their difference is a distance. :func:`_prefix_percentiles` is a PREFIX midrank -- at index ``i`` the
#: reading is "where this value sits among the first ``i + 1`` observations" -- so its reference
#: population GROWS ALONG THE RECORD (8 at the module's own floor, 440 at the tail of a 440-month card).
#: :func:`_pct_to_z` is the right UNIT conversion and carries no chosen constant, but no unit conversion
#: makes a rank against 33 observations commensurable with a rank against 440, and the first cut MEASURED
#: what that buys: on the ``b40_event`` fixture the flagship max stanza moved from 2020-10-31 to
#: 1992-09-30 (index 32, population 33) on a candidate carrying NO z at all. The percentile stays in
#: :data:`STATE_COMPONENTS`, it is still computed, it is still returned per dimension as ``pct_gap`` --
#: a PRINTED FACT of the stanza -- and it no longer ranks. A DIRECTION and a RUN LENGTH never carried a
#: distance for a different reason: turning "the two directions disagree" into a number of sigmas would
#: require somebody to pick how many, which is the weight sec 14 refuses.
DISTANCE_COMPONENTS: tuple = ("z",)

#: WHICH VECTOR ON A STATE HISTORY EACH NAMED COMPONENT IS READ OFF, declared once so :func:`likeness`
#: and :func:`_record_span` can never disagree about what "observable" means. The two positional
#: components (direction, run) are computed from ``values`` rather than carried as a vector, which is why
#: only the two RANKABLE names appear here.
COMPONENT_VECTOR: dict = {"z": "z", "percentile": "pct"}

#: WHAT AN UNREAD DIMENSION COSTS A CANDIDATE, in sigmas (orchestrator ruling, round 2, the EARLY-DATE
#: RULE). UNKNOWN IS FAR. With the coverage filter struck, a candidate observable on two of five
#: dimensions was averaged over the two it could be read on -- so the OLDEST stretch of every record,
#: where the fewest dimensions have warmed up, won on a denominator rather than on likeness. The rule is
#: a RANK RULE and never a filter: the unread dimensions are charged one sigma each, the denominator is
#: the DECLARED count again, the candidate stays in the pool, and the count rides the row so the stanza
#: can say "like on two of the five dimensions; the three unread count as a sigma apart". A gate deletes;
#: this orders, and every number in it is printed.
UNOBSERVED_SIGMA: float = 1.0

#: The percentile is clamped off 0 and 100 before the quantile, because the normal quantile is infinite
#: at both. ``_prefix_percentiles``' midrank never reaches either on ``n >= 2`` (its maximum is
#: ``100 - 50/n``), so this is a guard on a hand-stated vector and not a correction of the producer.
_PCT_EPS: float = 1e-3


def _pct_to_z(p) -> Optional[float]:
    """A PERCENTILE READ ON THE Z AXIS -- ``NormalDist().inv_cdf``, which is a UNIT CONVERSION and not a
    weight. ``None`` on anything that is not a reading.

    WHY A CONVERSION AT ALL, NOW THAT THE PERCENTILE DOES NOT RANK. The percentile gap is a FACT the
    stanza prints beside the distance, and a fact printed in percentage points beside a figure in sigmas
    invites the reader to add them. Carrying it onto the z axis states both on ONE axis, which is the
    only honest way to print them together -- and it is the conversion that would be required if a
    FIXED-WINDOW percentile ever joined :data:`DISTANCE_COMPONENTS`, so the arithmetic stays where it was
    rather than being deleted and re-derived. Averaging percentage POINTS against sigmas would have let
    the percentile term outweigh the z term by a factor of about twenty-five, which is a weight nobody
    declared."""
    v = TR.num_or_none(p)
    if v is None:
        return None
    from statistics import NormalDist
    q = min(max(float(v) / 100.0, _PCT_EPS), 1.0 - _PCT_EPS)
    return float(NormalDist().inv_cdf(q))


def _direction_at(hist: dict, i: Optional[int]) -> Optional[int]:
    """``+1 / -1 / 0`` -- the series' own direction INTO position ``i``. ``None`` where there is no
    preceding observation to take a direction from, which is an honest hole and never a zero: "it did
    not move" and "there is nothing to have moved from" are different states of the record."""
    vals = hist.get("values") or ()
    if i is None or i <= 0 or i >= len(vals):
        return None
    a, b = TR.num_or_none(vals[i - 1]), TR.num_or_none(vals[i])
    if a is None or b is None:
        return None
    return 1 if b > a else (-1 if b < a else 0)


def _direction_word(d) -> Optional[int]:
    """THE CALLER'S OWN "which way is it moving NOW", as ``+1 / -1 / 0``, or ``None``.

    It reads both spellings the estate carries, because ``StateRow.run`` states a direction in WORDS
    (``feeders``: ``{'direction': 'up'|'down', 'length': n}``) while this module's own
    :func:`_direction_at` states it as a sign. ``None`` is a HOLE and never a zero -- a row whose streak
    declined has no direction to compare, and calling that "flat" would invent an agreement.

    THE HELPER EXISTS BECAUSE THE TAIL READ WENT (round 2, MAJOR 5). ``d_now`` used to be
    ``_direction_at(hist, last)`` -- the last move of the KNOWLEDGE-AXIS vector, which on a lagged card
    is an older print than the row the board is showing. The caller passes what its own row says."""
    if d is None or isinstance(d, bool):
        return None
    if isinstance(d, str):
        w = d.strip().lower()
        return {"up": 1, "rising": 1, "down": -1, "falling": -1, "flat": 0}.get(w)
    n = TR.num_or_none(d)
    if n is None:
        return None
    return 1 if n > 0 else (-1 if n < 0 else 0)


def likeness(candidate_date: str, dims: list) -> Optional[dict]:
    """THE DISTANCE OVER THE WIDENED STATE VECTOR, and every count it produces is a FACT rather than a
    gate (owner doctrine 2026-09-17: STATS GRADE, NEVER GATE). ``None`` ONLY when no dimension carries a
    readable distance component at ``t`` -- existence, which is one of the two filters the doctrine
    leaves hard.

    **AND SINCE ROUND 2, "A READABLE DISTANCE COMPONENT" MEANS A READABLE Z, ON ONE DIMENSION OR MORE.**
    That is a NARROWING of this function's own hard filter and it is stated here as the filter it is,
    not left to be inferred from :data:`DISTANCE_COMPONENTS`. When the prefix percentile was in the
    distance, a candidate inside every dimension's rolling warm-up was still rankable on its percentile;
    with the distance back to the z alone it is not, and this function returns ``None`` for it. The
    module's own rule would have SCORED that candidate at exactly :data:`UNOBSERVED_SIGMA` -- so the
    decline is a CHOICE about comparability (a distance whose every term is the same constant ranks
    nothing) and not an arithmetic necessity. It is COUNTED rather than silent: :func:`select_analogs`
    returns ``n_dropped_unreadable`` -- ``n_candidates_pit`` minus ``n_candidates`` -- and the row
    carries it. MEASURED on the fixture estate: 60, 91 and 91 candidates per 440-month card, the oldest
    stretch of every record.

    **THE DISTANCE IS THE ONE THAT SHIPPED.** Per dimension the gap is the mean of the DISTANCE
    components readable at ``t`` (:data:`DISTANCE_COMPONENTS`, which is the z and only the z -- see that
    tuple for the measurement that took the prefix percentile out of it), and the distance is the mean of
    those per-dimension gaps over THE DECLARED dimensions, with each UNREAD dimension charged
    :data:`UNOBSERVED_SIGMA`. On a pool where every dimension is observable -- which is every pool the
    shipped selector could admit, because it required exactly that -- this is
    ``sum |z_t - z_now| / |dims|`` unchanged, byte for byte.

    **UNKNOWN IS FAR** (orchestrator ruling, round 2). The first cut divided by the OBSERVED count, which
    made a candidate readable on two of five dimensions compete on a two-dimension average against one
    readable on all five -- and since the oldest stretch of a record is where the fewest dimensions have
    warmed up, that is an ANTIQUITY bias wearing a likeness name. Charging the unread dimensions a full
    sigma each ranks them where the reader would: a 2-of-5 candidate whose two observed gaps average 0.04
    scores ``(0.08 + 3.0) / 5 = 0.616`` and sits BELOW a 5-of-5 candidate at 0.3. It is a RANK RULE and
    not a filter -- the candidate stays in the pool, keeps its distance, and the stanza prints both counts.

    **EVERY "NOW" IS THE CALLER'S, AT THE AS-OF VINTAGE** (round 2, MAJOR 5). ``z_now`` was always passed
    in; ``pct_now``, ``dir_now`` and ``run_now`` now are too, and NONE of them is taken from the tail of
    the knowledge-axis vector. The first cut read ``pct_now`` off ``hist['pct'][-1]``, which on a lagged
    card is an OLDER print than the row's own z: measured on ``b40_event / drought`` (a 25-day declared
    lag) the row's ``z_now`` is 0.7581 and the vector's tail is 0.6351 -- 0.123 sigma of pure vintage
    disagreement, against winning distances of 0.011 to 0.065. A dimension whose caller declares no
    ``pct_now`` / ``dir_now`` / ``run_now`` is UNOBSERVED on that component; it never borrows a tail.

    **AND EVERY "THEN" IS READ ON ONE AXIS -- THE KNOWLEDGE AXIS** (round 3, MAJOR B). Round 2 fixed the
    vintage on the ``now`` half of all four components and on the ``then`` half of only two: ``z[i]`` and
    ``pct[i]`` come off vectors ``state_history`` re-indexed, while ``_direction_at`` / ``_run_at`` read
    ``values`` -- the OBSERVATION axis -- at the same ``i``. On a card with a declared publication lag
    those are different observations, so one position carried a knowable z beside a direction into a
    print nobody held at that date: MEASURED on ``b40_event / drought`` (25 days) at 292 of 440 positions
    for the direction and 257 of 440 for the run. Both now read at ``_knowable_at(hist, i)``, which is
    the identity on every zero-lag card and therefore moves no hand-stated vector.

    **THE TWO RULES THAT WENT, and what replaced each.** The SIGN GATE (``agree < ceil(len(dims)/2)`` ->
    ``None``) and the all-dimensions-observable skip in :func:`select_analogs` both DELETED a stanza; the
    estate's own record is that this rule declined on five of five 2026-09-16 smoke turns and the reader
    was handed "no past state on this series is like the present one" beside two rendered windows. Both
    become NUMBERS the stanza prints: ``sign_agree of sign_seen`` ("the state agreed in sign on three of
    five dimensions") and ``dims_seen of dims_declared`` ("like on three of the five dimensions this board
    ranks; the other two have no reading at that date"). A fence that CORRECTS or COMPUTES, never deletes.

    NO WEIGHTS AND NO SCALAR LOUDNESS SCORE (sec 14). Drafts A and D wanted ``1.0/40/3`` and ``2/25/4``
    weightings; a weight is a threshold with a smooth edge, and the whole engine's answer to "which
    driver matters" is that the writer decides, on figures the board prints. :data:`UNOBSERVED_SIGMA` is
    not a weight on a component -- it is what an UNREAD dimension is worth, one sigma, stated and printed.

    Each ``dims`` entry is ``{'id', 'hist', 'z_now'}`` and may carry ``'pct_now'``, ``'dir_now'`` and
    ``'run_now'`` -- the row's own readings at the as-of. THE PERCENTILE IS READ OFF ``hist['pct']`` AND
    IS NEVER MINTED HERE: ``state_history``'s percentile vector is LAZY by design (``want_pct``) because
    it is an O(n log n) pass per dimension, and a selector that built one behind its caller's back would
    both spend that pass on every board and read a state the producer declined to compute. ``analog_rows``
    is the producer that turns it on.

    ``run_gap`` ON THE RESULT IS A MEAN OVER DIMENSIONS and is NOT the tie-break's own term (round 2,
    minor 4): it is the mean of ``|run at t - the dimension's run now|`` over the dimensions that carry
    both, while :func:`select_analogs`' second sort term is ``abs(run_length - run_now)`` on the SEED's
    own run. Three similarly named numbers, two different subjects; a render that prints them as one
    arithmetic prints a falsehood.

    ``per_dim[].id``, like ``dims_order`` and ``record_span``, carries the RAW DRIVER ID. It is an
    INTERNAL key for the lint and the census -- never a page word. ``register.internal_leaks`` is not
    relaxable and :func:`_label` / ``render.humanise`` is the required door."""
    if not dims:
        return None
    total = 0.0
    seen = 0
    agree = sign_seen = 0
    dir_agree = dir_seen = 0
    run_gaps: list = []
    per: list = []
    for dim in dims:
        hist = dim.get("hist") or {}
        # THE VECTORS ARE READ IN PLACE, NEVER COPIED. This function runs once per CANDIDATE and the
        # relaxed pool is the record itself, so a list() of each vector per dimension per candidate is
        # an O(n) copy on the hot path -- the cost the widening must not buy.
        dates = hist.get("dates") or ()
        i = _index_on_or_before(dates, candidate_date)
        parts: list = []
        obs: list = []
        rec: dict = {"id": str(dim.get("id") or ""), "index": i}
        zs = hist.get("z") or ()
        z_t = None if (i is None or i >= len(zs)) else TR.num_or_none(zs[i])
        z_now = TR.num_or_none(dim.get("z_now"))
        if z_t is not None and z_now is not None:
            parts.append(abs(z_t - z_now))
            obs.append("z")
            sign_seen += 1
            if (z_t >= 0) == (z_now >= 0):
                agree += 1
                rec["sign_agree"] = True
            else:
                rec["sign_agree"] = False
        # THE PERCENTILE IS OBSERVED AND PRINTED AND DOES NOT RANK (round 2, MAJOR 1). ``parts`` is the
        # DISTANCE and this gap is not in it; it rides ``per_dim`` as ``pct_gap`` so the stanza can say
        # where the two readings sat in their own records without the rank being decided by a statistic
        # whose reference population grows along the record.
        pcts = hist.get("pct") or ()
        p_t = None if (i is None or i >= len(pcts)) else _pct_to_z(pcts[i])
        p_now = _pct_to_z(dim.get("pct_now"))
        if p_t is not None and p_now is not None:
            obs.append("percentile")
            rec["pct_gap"] = abs(p_t - p_now)
        # THE DIRECTION AND THE RUN ARE READ ON THE KNOWLEDGE AXIS, LIKE THE Z AND THE PERCENTILE
        # (round 3, MAJOR B). ``state_history`` re-indexes only ``z`` and ``pct``; ``values`` stays on
        # the observation axis, so ``_direction_at(hist, i)`` is the move INTO observation ``i`` -- on a
        # lagged card, a move nobody could read on the day position ``i`` is dated by. MEASURED on
        # ``b40_event / drought`` (25 days declared): 292 of 440 positions carried a direction that is
        # not the knowable one and 257 a run length that is not. ``j`` is that position's newest
        # KNOWABLE observation and ``None`` where the record has none, which is a hole and not a zero.
        j = _knowable_at(hist, i)
        d_t, d_now = _direction_at(hist, j), _direction_word(dim.get("dir_now"))
        if d_t is not None and d_now is not None:
            dir_seen += 1
            obs.append("direction")
            if d_t == d_now:
                dir_agree += 1
                rec["dir_agree"] = True
            else:
                rec["dir_agree"] = False
        r_now = TR.num_or_none(dim.get("run_now"))
        if j is not None and r_now is not None:
            gap_run = abs(_run_at(hist, j) - int(r_now))
            run_gaps.append(gap_run)
            obs.append("run")
            rec["run_gap"] = int(gap_run)
        if parts:
            gap = sum(parts) / float(len(parts))
            total += gap
            seen += 1
            rec["gap"] = gap
        rec["observed"] = tuple(obs)
        per.append(rec)
    if seen == 0:
        return None
    declared = max(1, len(dims))
    unread = max(0, len(dims) - seen)
    return {"distance": (total + UNOBSERVED_SIGMA * unread) / float(declared),
            "dims_seen": seen, "dims_declared": len(dims), "dims_unread": unread,
            "unread_sigma": UNOBSERVED_SIGMA,
            "dims_any_seen": sum(1 for r in per if r["observed"]),
            "sign_agree": agree, "sign_seen": sign_seen,
            "dir_agree": dir_agree, "dir_seen": dir_seen,
            "run_gap": (sum(run_gaps) / float(len(run_gaps)) if run_gaps else None),
            "per_dim": tuple(per)}


def _dims_first(dims: list, first_dim: Optional[str]) -> list:
    """``dims`` with the dimension named by ``first_dim`` moved to the front, order otherwise preserved.

    THE CHAIN-FIRST ORDER (DESIGN C.2). The stanza is the THEN for the TOP CHAIN, so the dimension the
    chain's RECEIPT HOP names leads the vector the coverage line enumerates and the header can say which
    dimension the chain is read on. It CANNOT move the distance, and that is deliberate: the distance is
    an unweighted mean, so a reorder is a statement about what the reader is shown FIRST and never about
    what ranks. A ``first_dim`` no dimension carries is a no-op -- the caller is the render half and a
    chain whose hop this board does not rank must not cost the stanza its selection."""
    want = str(first_dim or "")
    if not want:
        return list(dims or ())
    head = [d for d in (dims or ()) if str(d.get("id") or "") == want]
    if not head:
        return list(dims or ())
    return head + [d for d in (dims or ()) if str(d.get("id") or "") != want]


def _record_span(dims: list) -> tuple:
    """Per dimension, the FIRST DATE its own record could be read on -- ``{'id', 'first_date'}``.

    "First observable" means the first position carrying a DISTANCE component (:data:`DISTANCE_COMPONENTS`),
    which is the same readability :func:`likeness` grades a candidate on, so the span and the coverage can
    never disagree about what a dimension could see. **IT MOVED WITH THE DISTANCE** (round 2, MAJOR 1):
    while the prefix percentile ranked, this read "z or percentile" and a 440-month card was first
    observable at its EIGHTH month; with the z alone it is first observable where the rolling window
    fills, which is the same date the coverage count is computed on. Two readings of one word would have
    let the header print a span the distance never used.

    It is the input to the header's correction: a picked date OLDER than some dimensions' records prints
    "this date precedes the record of <n> of the dimensions" rather than being removed -- the measured
    May-2001-under-a-2006-floor defect answered by a SENTENCE instead of a deletion (DESIGN C.4).

    ``id`` IS THE RAW DRIVER ID and is internal (round 2, minor 2): ``register.internal_leaks`` is never
    relaxable, so a render enumerating this tuple goes through :func:`_label` / ``render.humanise``."""
    out: list = []
    for d in (dims or ()):
        hist = d.get("hist") or {}
        dates = hist.get("dates") or ()
        vecs = [(hist.get(COMPONENT_VECTOR[k]) or ()) for k in DISTANCE_COMPONENTS]
        first = None
        for i, dt in enumerate(dates):
            ok = any(i < len(v) and TR.num_or_none(v[i]) is not None for v in vecs)
            if ok and axis_date(dt) is not None:
                first = str(dt)[:10]
                break
        out.append({"id": str(d.get("id") or ""), "first_date": first})
    return tuple(out)


def _precedes_count(span: tuple, date) -> int:
    """How many dimensions' records this date PRECEDES -- the header's correction, as an integer.

    BOTH SIDES GO THROUGH :func:`axis_date`, which is this module's one calendar and its one standing
    lesson: a raw ``year_month`` label sorts as the month's FIRST instant, so a bare string comparison of
    ``"2016-12"`` against ``"2016-12-31"`` calls two names for the same month-end a difference. A
    dimension whose first date cannot be placed is not counted -- a correction has to be earned by a
    measurement, exactly as the separation rule is."""
    t = axis_date(date)
    if t is None:
        return 0
    n = 0
    for r in (span or ()):
        first = axis_date(r.get("first_date"))
        if first is not None and first > t:
            n += 1
    return n


def select_analogs(seed_hist: dict, *, dims: list, asof: str, band: LagBand, analog_k: int,
                   convention: Optional[dict] = None, min_separation_months: int = 12,
                   lag_days: int = 0, min_run: Optional[int] = None,
                   first_dim: Optional[str] = None,
                   crossing_separation_months: int = 0,
                   run_now: Optional[int] = None) -> dict:
    """THE SELECTION (sec 4.2, relaxed per DESIGN C.1). Returns ``{'picked', 'n_candidates', 'declined',
    'detail', 'n_candidates_raw', 'n_candidates_pit', 'n_candidates_head', 'n_dropped_unreadable',
    'dims_order', 'first_dim', 'record_span'}``.

    **THE FOUR COUNTS, AND THEY ARE FOUR BECAUSE THEY ANSWER FOUR QUESTIONS** (round 2, MAJOR 4):

      ``n_candidates_raw``   what :func:`crossings` minted under the RELAXED rule, before any filter;
      ``n_candidates_pit``   how many of those survived the two POINT-IN-TIME filters;
      ``n_candidates``       how many of THOSE carry a readable state -- the pool this selector RANKS,
                             and the number the stanza header describes;
      ``n_candidates_head``  THE RARITY NUMERATOR, and it is HEAD's own: how many candidates the SHIPPED
                             rule would have called like -- minted by its ``run >= <the TAIL of this
                             seed's own vector>`` crossing rule, surviving the same two PIT filters,
                             observable on EVERY declared dimension and agreeing in sign on at least
                             half of them.

    A FIFTH NUMBER RIDES BESIDE THEM AND IT IS A SUBTRACTION, NOT A POOL: ``n_dropped_unreadable`` is
    ``n_candidates_pit - n_candidates``, the candidates the EXISTENCE filter declined because no declared
    dimension carries a readable z at their date (see :func:`likeness` for why that filter narrowed in
    round 2). It is stated so the census closes by arithmetic --
    ``raw = (raw - pit) + n_dropped_unreadable + n_candidates`` -- and so a decline that used to be
    inferable is COUNTED.

    **THE RARITY NUMERATOR'S FLOOR IS HEAD'S OWN TAIL READ AND NOT THE ROW'S ``run_now``** (round 3,
    MAJOR A). The two coincide wherever the row's streak and the vector's tail agree, which is 13 of 13
    dimensions on the clean fixture estate and is NOT general: on the ``mirror_nulls`` estate, where a
    served NULL date drops a position out of this history while the row's streak counted it, the printed
    count moved 57 -> 33, 49 -> 5 and 30 -> 4. A number a PM reads as "N like states in M observations"
    is HEAD's arithmetic END TO END or it is a different statistic wearing HEAD's name; ``run_now`` keeps
    the seats where a "now" belongs -- the tie-break and :func:`likeness` -- and nothing else.

    **AND THE POOL THE PAGE PRINTS IS THE ONE THE PICK IS A MEMBER OF** (round-2 blocker 2). The header
    prints ``n_candidates`` -- the pool this selector RANKS and draws every picked row out of -- and
    ``n_candidates_head`` only as a SECOND, separately named number where the two differ, because
    ``n_candidates_head`` counts candidates observable on EVERY declared dimension and a picked row
    seen on two of three is not one of them: the served ``named_one`` stanza at deep is dated
    2013-06-30 beside a head-admitted set of three whose earliest member is 2023-12-31. Each picked row
    therefore carries ``pool_rank``, its 1-based seat in the ranked pool, so the sentence that says
    which one of that pool this is can be BACKED rather than assumed from the stanza's position.

    ``n_candidates_head`` IS A COUNT AND NEVER A FILTER, and that distinction is the whole of it: not one
    candidate is removed by it, the ranking does not read it, and the pool it counts is a SUBSET of the
    pool this selector picks from -- which is what makes "M OF THEM admitted at the full-coverage floor"
    a true sentence about the number printed beside it and not a second population in disguise. It exists because ``watch.like_state_base_rate`` prints "N like states
    in M observations" to a PM, and under the relaxation the ranked pool is 50%-79% of the record -- a
    number that is a COVERAGE statement and reads as a 79% recurrence rate. The rarity question keeps the
    rarity answer, measured the way the record's own reader measured it last week.

    **THE ONLY HARD FILTERS ARE POINT-IN-TIME AND EXISTENCE** (owner doctrine 2026-09-17). Both PIT
    filters are UNCHANGED, and each is the same arithmetic it was:
      * the candidate must be at least ``max_q`` quarters before the as-of, so its OUTCOME WINDOW HAS
        CLOSED -- a like state whose consequence has not happened yet is not evidence;
      * the candidate's own knowledge must have existed at ``t``: the prefix stops at ``t - lag_days``,
        which is why a crossing "at t" on a card published 43 days later is dated by when it was
        KNOWABLE.
    Beside them stands EXISTENCE -- :func:`likeness` returns ``None`` where no dimension carries a
    readable state at ``t``, and a distance against nothing is not a distance. Since round 2 that reads
    "no dimension carries a readable Z at ``t``", which is a NARROWER filter than it was, and the
    candidates it declines are COUNTED on ``n_dropped_unreadable`` rather than quietly absent. Nothing
    else removes a candidate.

    **WHAT WENT, AND WHY IT IS THE SAME RULING TWICE.** The shipped selector added two more gates and
    both DELETED: the sign gate inside :func:`likeness`, and ``like['dims_seen'] < len(dims)`` here. They
    were measured declining on five of five 2026-09-16 smoke turns -- ``no_like_state`` on every one --
    and the reader got a denial beside two windows the cascade leg printed anyway. Coverage and sign
    agreement are now PRINTED FACTS on the picked row (``dims_seen``, ``dims_declared``, ``sign_agree``,
    ``sign_seen``, ``dir_agree``, ``dir_seen``) and the candidate rule that floored on the present run
    length is gone from :func:`crossings`. Frequency floors deny the tail.

    **RECENCY STAYS THIRD** (bar B9, and DESIGN C.4's first threat). Ties break by RUN-LENGTH DIFFERENCE,
    then by DATE DESCENDING. Widening the pool makes the tie-break matter more, not less, and a pool
    ordered by recency first would be a recency engine wearing a likeness name -- so the order does not
    move, the run length keeps the seat the dropped candidate rule used to hold, and every picked row
    carries ``near_asof`` for the lint that asserts the chosen date is not inside ``min_separation_months``
    of the as-of. ``near_asof`` IS A FLAG AND NEVER A FILTER: the selection states it and the render half
    grades it.

    ``min_separation_months`` between two SELECTED dates is kept exactly, and it is per EPISODE because a
    candidate is now an episode's own start. It runs over the DISTANCE-ordered list, so the member of an
    episode that survives is its most-like one.

    A DECLINE ADDS NO WORD TO ``board.ANALOG_REASONS``. The one word is ``no_like_state`` as it always
    was, and the finer reason rides ``detail`` -- ``no_candidates`` (the record offered none),
    ``window_open`` (every candidate's outcome window is still open, or it was not knowable at t), or
    ``unobservable`` (candidates survived PIT and no dimension could be read at any of their dates).
    The render's closed vocabulary is untouched and ``detail`` is the render half's to spend.

    ``run_now`` IS THE CALLER'S WHERE THE CALLER HAS ONE (round 2, MAJOR 5). ``analog_rows`` passes the
    ROW's own trailing run at the as-of, the same vintage ``z_now`` comes from. Where no caller supplies
    one -- the offline decks and the census, which state a vector by hand and have no row -- the tail of
    the seed's own vector is used and this sentence is the statement of it: a SORT KEY cannot be a hole
    the way an unread component can. THE TERM IT IS COMPARED AGAINST -- ``run_length``, the candidate's
    own run -- IS READ ON THE KNOWLEDGE AXIS (round 3, MAJOR B): it ranks, so it is the run KNOWABLE at
    the candidate's date, and a candidate with nothing knowable behind it scores ``_run_at``'s own
    answer for that, 0."""
    dims = _dims_first(dims, first_dim)
    # HEAD'S OWN FLOOR, DERIVED HEAD'S OWN WAY, AND IT IS NOT THE ROW'S (round 3, MAJOR A). The rarity
    # numerator below is a claim about what the SHIPPED rule admitted, so every term of it must be the
    # shipped rule's -- including the ``min_run`` it minted candidates with, which HEAD took from the
    # TAIL of the seed's own vector and never from a ``StateRow``. Round 2 gave the tie-break the row's
    # run (rightly: it is a "now" and every "now" is the row's) and the head count inherited it by
    # sharing the variable. The clean fixture estate could not see the difference -- row run == tail run
    # on 13 of 13 dimensions -- but the count is hypersensitive to that floor, and on the ``mirror_nulls``
    # estate (the offline stand-in for the shape the pg mirror serves, where a NULL DATE drops a position
    # out of this history while the row's streak still counted it) the two disagree on 3 of 13 and the
    # printed number moved 57 -> 33, 49 -> 5 and 30 -> 4. The two floors are now two names.
    head_run = _run_at(seed_hist, len(seed_hist.get("values") or ()) - 1)
    if run_now is None:
        run_now = head_run
    run_now = int(run_now)
    if min_run is None:
        # ANY MONTH, DEDUPLICATED PER EPISODE. The ``run >= run_now`` rule is the one DESIGN C.1 drops;
        # ``run_now`` survives as the tie-break input below, where it grades instead of gating.
        cands = crossings(seed_hist, convention=convention, any_month=True,
                          min_separation_months=int(crossing_separation_months or 0))
    else:
        cands = crossings(seed_hist, convention=convention, min_run=int(min_run))
    n_raw = len(cands)
    if band.max_q is None:
        horizon = None
    else:
        horizon = int(band.max_q) * QUARTER_MONTHS
    closed: list = []
    for c in cands:
        if horizon is not None:
            far = _window_end(c["date"], horizon)
            # AN UNPLACEABLE CANDIDATE HAS NO CLOSABLE WINDOW. The filter's claim is "this candidate's
            # outcome window has already closed"; a date the calendar cannot read supports no such
            # claim, so the candidate is not admitted -- the same shape the ``lag_days`` branch below
            # already takes for a label ``_add_days`` cannot place.
            if far is None or far > str(asof)[:10]:
                continue
        if lag_days:
            # A LABEL THIS AXIS CANNOT PLACE IS NOT ADMITTED. The filter's claim is "this crossing was
            # KNOWABLE at the as-of"; a date the calendar cannot read supports no such claim, and
            # admitting it would be the filter asserting what it could not check.
            knowable = _add_days(c["date"], int(lag_days))
            if knowable is None or knowable > str(asof)[:10]:
                continue
        closed.append(c)
    n_pit = len(closed)
    # "ALL DIMENSIONS OBSERVABLE AT t" WAS SEC 4.2'S OWN CANDIDATE FILTER AND IT IS STRUCK HERE (DESIGN
    # C.1). Its measured motivation stands -- the scenario-3 stanza printed "the series sat like this in
    # May 2001" one line under "the loud set reaches back to 2006", and the two sentences contradicted
    # each other -- but the remedy was a DELETION where a SENTENCE was owed. What answers it now is
    # ``record_span`` and the ``precedes_dims`` count each picked row carries, so the header states "this
    # date precedes the record of <n> of the dimensions ranked above" and the reader weighs it. A fence
    # that corrects, never one that deletes.
    span = _record_span(dims)
    # THE RARITY NUMERATOR IS COUNTED HERE AND FILTERS NOTHING (round 2, MAJOR 4). ``head_idx`` is the
    # candidate set the SHIPPED rule would have minted -- run starts at least as long as the present run,
    # plus the declared band crossings -- and it is a SUBSET of the relaxed pool by construction (every
    # run start is a direction change and both branches add the same band hits), so intersecting it with
    # the already-scored candidates reproduces HEAD's own ``n_candidates`` exactly, without a second
    # likeness pass and without one candidate leaving the ranking. One O(n) walk per seed. ITS FLOOR IS
    # ``head_run`` AND NOT ``run_now`` (round 3, MAJOR A): HEAD's arithmetic end to end, the tail read
    # included, because a rarity count measured at a different floor is a different number.
    # ROUND-3 REVIEW MINOR 1: HEAD minted its pool at ``run_now if min_run is None else int(min_run)``, so an
    # EXPLICIT floor is HEAD floor too -- only the default falls to the tail read.
    _head_floor = head_run if min_run is None else int(min_run)
    head_idx = {c["index"] for c in crossings(seed_hist, convention=convention, min_run=_head_floor)}
    scored: list = []
    n_head = 0
    for c in closed:
        like = likeness(c["date"], dims)
        if like is None:
            continue
        i = c["index"]
        if (i in head_idx and like["dims_seen"] == len(dims)
                and like["sign_agree"] * 2 >= len(dims)):
            # HEAD's own admission, restated as ARITHMETIC over facts already computed: observable on
            # every declared dimension, and agreeing in sign on at least half (``agree >= ceil(n/2)``,
            # which for integers is ``2 * agree >= n``). It grades nothing and removes nothing.
            n_head += 1
        # THE TIE-BREAK'S OWN "THEN" IS ON THE KNOWLEDGE AXIS TOO (round 3, MAJOR B). ``run_length`` is
        # a RANKING INPUT -- the second sort term below -- and the doctrine is absolute: a state used to
        # rank a candidate at ``t`` is the state KNOWABLE at ``t`` on every component. A position with
        # nothing knowable behind it has no run, and ``_run_at``'s own answer for that is 0.
        j_t = _knowable_at(seed_hist, i)
        run_t = 0 if j_t is None else _run_at(seed_hist, j_t)
        scored.append({**c, **like, "run_length": run_t, "run_now": run_now})
    # ``n_dropped_unreadable`` IS THE EXISTENCE FILTER'S OWN COUNT (round 3, minor). The fifth exit --
    # candidates that survived both PIT filters and carry no readable z on any declared dimension -- was
    # derivable but never stated, and a decline nobody counts is a decline nobody audits. It is the one
    # subtraction between ``n_candidates_pit`` and ``n_candidates``, so the census closes by arithmetic.
    n_unreadable = n_pit - len(scored)
    base = {"n_candidates_raw": n_raw, "n_candidates_pit": n_pit, "n_candidates_head": n_head,
            "n_dropped_unreadable": n_unreadable,
            "dims_declared": len(dims), "first_dim": (str(first_dim) if first_dim else None),
            "dims_order": tuple(str(d.get("id") or "") for d in (dims or ())),
            "record_span": span}
    if not scored:
        # ONE WORD, A FINER REASON BESIDE IT. ``board.ANALOG_REASONS`` gains nothing; ``detail`` is a
        # field on the row and never a colon tail on the stamp, so ``board.DETAIL_REASONS`` is untouched
        # too and the render half owes exactly the sentence it already owes.
        detail = ("no_candidates" if n_raw == 0 else
                  ("window_open" if n_pit == 0 else "unobservable"))
        return {**base, "picked": (), "n_candidates": 0, "declined": "no_like_state",
                "detail": detail}
    scored.sort(key=lambda s: (round(s["distance"], 9), abs(s["run_length"] - run_now),
                               _desc_date(s["date"])))
    picked: list = []
    for _rank, s in enumerate(scored, start=1):
        if len(picked) >= max(0, int(analog_k)):
            break
        # A SEPARATION NOBODY COULD MEASURE EXCLUDES NOTHING (see :func:`_months_between`): ``None``
        # means one of the two dates is unplaceable, and the min-separation rule is an EXCLUSION that
        # has to be earned. Unreachable in practice -- ``crossings`` mints no undatable candidate --
        # and written this way so a future label the calendar cannot read costs a stanza its ORDERING
        # rather than costing the reader the stanza.
        seps = [_months_between(p["date"], s["date"]) for p in picked]
        if any(m is not None and abs(m) < int(min_separation_months) for m in seps):
            continue
        # THE TWO FACTS THE HEADER NEEDS AND THE LINT READS, computed once per PICKED row so no consumer
        # re-derives them from a span it would have to rebuild. ``near_asof`` is bar B9's own tripwire
        # (DESIGN C.4) and it is a FLAG: a widened pool whose tie fell to ``_desc_date`` could otherwise
        # hand the reader "the series sat like this" about a date inside the separation window of today,
        # which is the present state described as its own precedent.
        m_asof = _months_between(s["date"], asof)
        picked.append({**s, "precedes_dims": _precedes_count(span, s["date"]),
                       # WHERE THIS PICK SITS IN THE POOL THE PAGE PRINTS BESIDE IT (round-2 blocker
                       # 2). The header's count is now the RANKED POOL -- the population this row was
                       # drawn from and is a member of -- and the sentence the ruling asks for says
                       # "this one the nearest". That is TRUE of the first pick and FALSE of the
                       # second, which a max-tier stanza pair renders side by side, so the claim rides
                       # on the rank rather than on the shape: 1 is the nearest, anything else is "one
                       # of them". It is the position in `scored`, already sorted by distance here, so
                       # no consumer re-derives an ordering from a distance it would have to re-rank.
                       "pool_rank": int(_rank),
                       # THE FLAG AND ITS FIGURE COME OFF **ONE** ARITHMETIC, and that is why the
                       # distance is stored rather than re-derived. The render half owes the reader
                       # the months where the flag is true (DESIGN C.4's correction, which APPENDS
                       # and never removes), and a second calendar in `render.py` computing the same
                       # gap from the same two strings is one series counted twice in two spellings
                       # -- the failure `axis_date` exists to close, arriving through the other door.
                       # It is `None` exactly where the flag is False for want of a placeable date.
                       "months_to_asof": (None if m_asof is None else abs(int(m_asof))),
                       "near_asof": bool(m_asof is not None
                                         and abs(m_asof) < int(min_separation_months))})
    return {**base, "picked": tuple(picked), "n_candidates": len(scored), "declined": None,
            "detail": None}


def _add_days(iso: str, days: int) -> Optional[str]:
    """The date a candidate dated ``iso`` became KNOWABLE. ``None`` when the label cannot be placed.

    It goes through :func:`axis_date` for the same reason the knowledge axis does: a ``year_month``
    candidate is dated by its MONTH-END, and ``date.fromisoformat("2001-05")`` does not parse at all --
    so the admissibility filter this feeds would have raised on the first ONI candidate the moment the
    ym lag stopped reading as zero."""
    import datetime as _dt
    d = axis_date(iso)
    if d is None:
        return None
    return (_dt.date.fromisoformat(d) + _dt.timedelta(days=int(days))).isoformat()


def _desc_date(s: str) -> tuple:
    return tuple(-ord(c) for c in str(s or ""))


def _months_between(a, b) -> Optional[int]:
    """Whole months from ``a`` to ``b``, or ``None`` when either side cannot be placed on the calendar.

    BOTH SIDES GO THROUGH :func:`axis_date` for :func:`_window_end`'s reason: the raw slice
    ``int(str(a)[5:7])`` is empty on a blank label AND on the annual card's bare ``YYYY``, and both
    raised. The two callers are separation filters and each treats ``None`` as NO SEPARATION
    CONSTRAINT -- an exclusion has to be earned by a measurement, and a separation nobody could measure
    excludes nothing."""
    da, db = axis_date(a), axis_date(b)
    if da is None or db is None:
        return None
    ay, am = int(da[0:4]), int(da[5:7])
    by, bm = int(db[0:4]), int(db[5:7])
    return (by * 12 + bm) - (ay * 12 + am)


def _run_at(hist: dict, i: int) -> int:
    """The run length ending at index ``i`` -- the tie-break input, computed on the same array.

    IT READS ``values`` THE WAY ITS CALLERS GUARD IT (round 2, minor 8): :func:`likeness` takes the
    history as ``dim.get('hist') or {}`` and then asked this function to index ``hist['values']``
    directly. Unreachable today -- the run branch needs a placed index, which needs non-empty ``dates``
    -- and written the same way as every other reader here so a future caller cannot make it a KeyError."""
    vals = hist.get("values") or ()
    if i <= 0 or i >= len(vals):
        return 0
    direction = 1 if vals[i] > vals[i - 1] else (-1 if vals[i] < vals[i - 1] else 0)
    if direction == 0:
        return 0
    n, j = 0, i
    while j > 0 and ((vals[j] > vals[j - 1]) if direction > 0 else (vals[j] < vals[j - 1])):
        n += 1
        j -= 1
    return n


# ---------------------------------------------------------------------------------------------------
# 4.3 THE OUTCOME OVER THE BAND, AT BOTH ENDS -- leg A
# ---------------------------------------------------------------------------------------------------
def known_date_after(obs_date, lag_days: int = 0) -> str:
    """THE DATE AN OBSERVATION COULD BE KNOWN (sec 1.4, D21, restated at the outcome row -- 09-24 K5): the
    observation's own date (a month's END for a ``YYYY-MM`` observation) plus the card's declared
    publication lag in days. ``""`` for a bare-year observation, whose known date the array does not
    carry -- a vintage card's known date is the SERVED vintage's, and printing the year as a known date
    is the "[known 2026]" the max page's footer showed."""
    d = str(obs_date or "").strip()
    if len(d) == 4 and d.isdigit():
        return ""
    if len(d) == 7 and d[4] == "-":
        try:
            end = _month_end(int(d[:4]), int(d[5:7]))
        except (TypeError, ValueError):
            return ""
    elif len(d) >= 10:
        end = d[:10]
    else:
        return ""
    lag = int(lag_days or 0)
    return (_add_days(end, lag) or end) if lag > 0 else end


def outcome_over_band(*, label: str, values, dates, t: str, band: LagBand, asof: str,
                      unit: str = "", table: str = "", metric: str = "", commodity=None,
                      country=None, key: str = "outcome", lag_days: int = 0) -> dict:
    """LEG A (sec 4.3): what ONE consequence series did over the parent's declared band, read at BOTH
    ends. Returns a row the render turns into SB-O, or a row carrying its own closed decline word.

    ZERO READS: ``values`` / ``dates`` are the array already in memory. The window is
    ``[t + 3*min_q, t + 3*max_q]`` MONTHS over the PARENT'S band, and the row says so -- a child's own
    lag is its lag onto the PRICE, not the parent-to-child lag, so the parent's band is the only
    declared number here (doctrine M-4).

    Both endpoints go through the registered ``window_change`` transform against the value at ``t``, so
    "moved X at the near end and Y at the far end" is two re-executable figures rather than a range."""
    base = {"label": label, "unit": unit, "table": table, "metric": metric, "commodity": commodity,
            "country": country, "band": band, "t": t}
    if band.min_q is None:
        return {**base, "declined": "lag_undeclared_between_nodes", "decline_leg": "edge"}
    if band.max_q is None:
        return {**base, "declined": "horizon_open", "decline_leg": "analog"}
    near_date = _window_end(t, int(band.min_q) * QUARTER_MONTHS)
    far_date = _window_end(t, int(band.max_q) * QUARTER_MONTHS)
    if near_date is None or far_date is None:
        # A STATE DATE THE CALENDAR CANNOT PLACE HAS NO WINDOW TO READ AN OUTCOME OVER. The word is the
        # closed vocabulary's own (``board.ANALOG_REASONS``) and renders as "the series carries no
        # observation over that window" -- true of a window that could not be constructed at all.
        return {**base, "declined": "no_tape_rows", "decline_leg": "analog"}
    if far_date > str(asof)[:10]:
        return {**base, "declined": "horizon_open", "decline_leg": "analog"}
    # THE CONSEQUENCE SERIES THROUGH THE SAME BOUNDARY: a blank cell in the benchmark column raised
    # ``could not convert string to float: ''`` here, and an undated observation cannot be located by
    # ``_index_on_or_before`` at either end of the window.
    vs, ds, _n_dropped = TR.dated_pairs(values, dates)
    i0 = _index_on_or_before(ds, t)
    i1 = _index_on_or_before(ds, near_date)
    i2 = _index_on_or_before(ds, far_date)
    # A ZERO-QUARTER NEAR END IS THE STATE'S OWN DATE, AND ITS CHANGE IS ZERO -- not an absence. The
    # first cut declined whenever ``i1 == i0``, which is EVERY row whose parent declares a `0-N
    # quarters` band (484 of the estate's 1,412 declarations, the single commonest band): the near end
    # of "zero to two quarters" IS t, and "it had not moved yet" is the honest reading of that end.
    # Only a band whose FAR end also lands on t (a genuine `0 quarters` point) has no outcome to read.
    if i0 is None or i1 is None or i2 is None or i2 == i0:
        return {**base, "declined": "no_tape_rows", "decline_leg": "analog"}
    # 09-24 (CONTRACT K5): BOTH ENDS ON ONE PRINT IS ONE MOVE, NEVER TWO. Where the band's near and far ends
    # read the SAME observation (the band is shorter than the series' own cadence), the row declines by
    # name rather than printing one annual delta as a move "by the time the lag opened" and again "by the
    # time it closed" under one handle.
    if i1 == i2 and i1 != i0:
        return {**base, "declined": "band_inside_one_print", "decline_leg": "analog"}
    bundle = {key: {"values": vs, "dates": ds, "unit": unit}}
    near, nrec = TR.run_transform("window_change", bundle, key=key,
                                  params={"t1": i0, "t2": i1, "window_label": "the near end"})
    far, frec = TR.run_transform("window_change", bundle, key=key,
                                 params={"t1": i0, "t2": i2, "window_label": "the far end"})
    if near.get("declined") or far.get("declined"):
        return {**base, "declined": "read_truncated", "decline_leg": "analog"}
    return {**base, "declined": None,
            "near_value": near["value"], "far_value": far["value"],
            "near_date": ds[i1], "far_date": ds[i2],
            "from_value": vs[i0], "from_date": ds[i0],
            # K5: THE END OBSERVATION'S DERIVED KNOWN DATE, read by the change row's call.
            "near_known": known_date_after(ds[i1], lag_days),
            "far_known": known_date_after(ds[i2], lag_days),
            "derivation": [nrec, frec], "inputs": bundle}


# ---------------------------------------------------------------------------------------------------
# 4.4 EVENT ANALOGS -- from the flag series, or a row that says there is none
# ---------------------------------------------------------------------------------------------------
def event_analogs(row, *, asof: str, band: Optional[LagBand] = None) -> dict:
    """A ``policy_event`` row's analogs (sec 4.4, doctrine m-8).

    A DATED FLAG SERIES yields its own prior events through ``flag_events`` -- numeric and dated, so
    ruling 4 holds. Every OTHER policy row says, in words, "no numeric event history; prior steps are
    receipts, not analogs" -- because a receipt-selected candidate pool would be text-selected, which is
    the shape ruling 4 retires."""
    st = row.state
    if st is None or status_word(st.status) != "ok" or not st.flag_state:
        return {"contract": row.contract, "driver_id": row.driver_id, "dates": (),
                "declined": "no_numeric_event_history"}
    key = st.key.label()
    arrays = (st.inputs or {}).get(key) or {}
    # A FLAG EVENT IS A DATE, so an undated non-zero cell is not an event this selector can offer: it
    # leaves through the same boundary the state history uses.
    values, dates, _n_dropped = TR.dated_pairs(arrays.get("values"), arrays.get("dates"))
    hz = None if (band is None or band.max_q is None) else int(band.max_q) * QUARTER_MONTHS
    out: list = []
    for i, v in enumerate(values):
        if v == 0.0 or i >= len(dates):
            continue
        d = dates[i]
        if d >= str(asof)[:10]:
            continue
        if hz is not None:
            closes = _window_end(d, hz)
            if closes is None or closes > str(asof)[:10]:
                continue
        out.append(d)
    if not out:
        return {"contract": row.contract, "driver_id": row.driver_id, "dates": (),
                "declined": "no_like_state"}
    # EVERY ADMISSIBLE EVENT RIDES. The first cut returned ``out[:-1] or out`` and so dropped the NEWEST
    # prior event under no stated rule -- on a flag series whose current event is not the last row that
    # discards a genuine analog. The two filters above are the rules: an event dated at or after the
    # as-of is not history, and one whose own band has not closed has no outcome to read.
    return {"contract": row.contract, "driver_id": row.driver_id, "dates": tuple(out),
            "declined": None}


# ---------------------------------------------------------------------------------------------------
# AMENDMENT 1 -- the CO-LOUD analog for a driver-as-subject anchor
# ---------------------------------------------------------------------------------------------------
def co_loud_analogs(bd, driver_id: str, *, k: int = 2, decile: float = 90.0,
                    analog_k: int = 2, benchmark_fn=None) -> dict:
    """The DRIVER-AS-SUBJECT analog (sec 16 Amendment 1): the dates when at least ``k`` of the anchor
    contracts' rows for this driver sat in the top decile AT ONCE, AND each contract's own outcome read
    over ITS OWN declared band.

    WHY IT IS A DIFFERENT SELECTOR. An ordinary analog asks "when did THIS series look like this"; a
    driver anchored as the SUBJECT is a question about a driver that many contracts carry, so the like
    state is a CO-OCCURRENCE across those contracts and the outcome is per contract, over that
    contract's own edge. Positioning's ``context_only`` rule yields here and only here (D18): the R9
    guard's measured reason is positioning narrated as a CAUSE of the anchor's price, which is not what
    a question about positioning is asking.

    **THE OUTCOME HALF IS HALF THE AMENDMENT, and the first cut shipped only the dates.** It returned
    ``per_contract`` as a map of row KEYS and never called :func:`outcome_over_band` at all, so the
    sentence Amendment 1 asks for -- "and each contract's outcome over its OWN lag band" -- had no
    producer. Each entry now carries the contract's own ``band`` and one outcome PER PICKED DATE, read
    exactly as leg A reads one: over that contract's declared band, at both ends, zero reads.

    THE CONSEQUENCE IS THE CONTRACT'S PRICE, which is why ``benchmark_fn`` is the series and not the
    driver's own array. Reading the shared driver again "on the far board" returns the parent's own move
    with another board's name on it -- the defect :func:`_outcomes_for` measures and names. A caller that
    fills no benchmark seat gets an outcome row declining by :func:`outcome_over_band`'s own word rather
    than a figure from the wrong series."""
    per: dict = {}
    for a in bd.anchors:
        row = bd.row(a.contract, driver_id)
        if row is None or row.state is None or status_word(row.state.status) != "ok":
            continue
        hist = state_history(row.state, lag_days=_lag_days_of(row), want_pct=True)
        per[a.contract] = {"row": row, "hist": hist}
    if len(per) < max(1, int(k)):
        return {"driver_id": driver_id, "dates": (), "declined": "no_like_state", "per_contract": {}}
    # ONLY DATES THE CALENDAR CAN PLACE. A co-occurrence is a claim about one DAY across contracts, and
    # an unplaceable label is a day nobody can name -- it would also reach ``_months_between`` below.
    all_dates = sorted({d for v in per.values() for d in v["hist"]["dates"]
                        if d and axis_date(d) is not None})
    hits: list = []
    for d in all_dates:
        if d >= str(bd.asof)[:10]:
            continue
        n = 0
        for v in per.values():
            i = _index_on_or_before(v["hist"]["dates"], d)
            p = None if i is None else TR.num_or_none(percentile_vector(v["hist"])[i])
            if p is not None and p >= float(decile):
                n += 1
        if n >= max(1, int(k)):
            hits.append({"date": d, "n_contracts": n})
    picked: list = []
    for h in sorted(hits, key=lambda x: _desc_date(x["date"])):
        if len(picked) >= max(0, int(analog_k)):
            break
        # ``None`` is NO SEPARATION CONSTRAINT here for :func:`select_analogs`'s stated reason.
        seps = [_months_between(p["date"], h["date"]) for p in picked]
        if any(m is not None and abs(m) < 12 for m in seps):
            continue
        picked.append(h)
    per_contract = _co_loud_outcomes(bd, per, picked, benchmark_fn=benchmark_fn)
    if not picked:
        return {"driver_id": driver_id, "dates": (), "declined": "no_like_state",
                "per_contract": per_contract}
    return {"driver_id": driver_id, "dates": tuple(picked), "declined": None,
            "n_candidates": len(hits), "per_contract": per_contract}


def _co_loud_outcomes(bd, per: dict, picked, *, benchmark_fn=None) -> dict:
    """``{contract: {key, band, outcomes}}`` -- each anchor contract's outcome over ITS OWN band.

    ONE ROW PER PICKED DATE, through the same :func:`outcome_over_band` leg A uses, so a co-loud stanza
    and an ordinary one are read by one calculator and render through one class."""
    out: dict = {}
    for c, v in per.items():
        row = v["row"]
        band = row.lag_band or parse_lag("")
        bm = benchmark_fn(c) if benchmark_fn is not None else None
        rows = tuple(outcome_over_band(
            label=(bm or {}).get("label") or f"the monthly benchmark for {_board(c)}",
            values=(bm or {}).get("values"), dates=(bm or {}).get("dates"),
            t=h["date"], band=band, asof=bd.asof, unit=(bm or {}).get("unit") or "",
            table=(bm or {}).get("table") or "silver_pink_sheet",
            metric=(bm or {}).get("metric") or "", commodity=c, country=None,
            key=f"benchmark:{c}") for h in (picked or ()))
        out[c] = {"key": row.key, "band": band, "outcomes": rows}
    return out


def co_loud_stanzas(bd, co: dict, *, seat: int = 0) -> list:
    """Amendment 1's co-loud result IN THE ORDINARY STANZA SHAPE, so a driver-as-subject board renders
    it through the closed vocabulary it already has: ONE **SB-A** header per co-occurrence date, one
    **SB-O** row per contract over THAT contract's own band, and the tail cut naming what it dropped.

    **THE PRODUCER HAD NO CONSUMER, WHICH IS WHY THIS EXISTS.** :func:`co_loud_analogs` returns a shape
    of its own (``per_contract``, keyed by contract, outcomes parallel to ``dates``), and
    ``render.render_board`` renders ``analogs`` -- a flat list of stanzas. Nothing joined the two, so
    the whole of Amendment 1's driver-as-subject leg computed and then fell on the floor: the anchor
    grammar the owner closed in V1 reached the reader on the anchor half only. The join is an ADAPTER
    and not a second renderer, because a co-loud stanza and an ordinary one are the same two sentences
    over the same calculator -- one like state, and what each declared band then measured.

    **THE HEADER IS A DIFFERENT SENTENCE INSIDE THE SAME CLASS.** SB-A is a CLASS (``^LIKE STATE ``),
    not a template, and the co-loud selector is not the ordinary one: "the series sat like this" would
    misdescribe a CO-OCCURRENCE across boards, which is the false-note class this package corrects
    rather than ships. ``render.sb_analog_header`` reads the ``co_loud`` flag this adapter stamps and
    prints the co-occurrence sentence; both stay letters-plus-year, so the lint's disjointness and its
    digit charge are untouched and no new token enters the vocabulary of 6.2.

    ``contract`` is the LEADING ANCHOR -- the first anchor of ``bd`` that carries the driver -- so the
    render's "the anchor board's own consequence leads" ordering has the board it needs and the stanza
    still spans every contract in its outcome rows. ``seat`` defaults to ZERO because the render orders
    stanzas by the seed's own rank: on a driver-as-subject board the subject IS the question, so its
    like state leads any ordinary stanza the same board also carries."""
    driver_id = str(co.get("driver_id") or "")
    per = dict(co.get("per_contract") or {})
    anchor_order = {a.contract: i for i, a in enumerate(getattr(bd, "anchors", ()) or ())}
    contracts = sorted(per, key=lambda c: (anchor_order.get(c, len(anchor_order)), c))
    lead = contracts[0] if contracts else ""
    rows = [r for r in (bd.row(c, driver_id) for c in contracts) if r is not None]
    floor_year = _coverage_floor([r for r in rows if r.state is not None])
    base = {"contract": lead, "driver_id": driver_id, "asof": bd.asof, "seat": int(seat),
            "co_loud": True, "floor_year": floor_year, "price_dims": 0}
    if co.get("declined") or not co.get("dates"):
        return [{**base, "band": None, "declined": str(co.get("declined") or "no_like_state"),
                 "n_candidates": int(co.get("n_candidates") or 0)}]
    out: list = []
    for i, hit in enumerate(co["dates"]):
        outs: list = []
        for c in contracts:
            got = per[c].get("outcomes") or ()
            if i < len(got):
                outs.append(got[i])
        out.append({**base, "band": (per.get(lead) or {}).get("band"), "date": str(hit["date"]),
                    "distance": 0.0, "kind": "co_loud", "declined": None,
                    "n_candidates": int(co.get("n_candidates") or len(co["dates"])),
                    "n_contracts": int(hit.get("n_contracts") or 0),
                    "outcomes": tuple(outs), "receipts": ()})
    return out


def _lag_days_of(row) -> int:
    """The card's declared publication lag off the row's own state, or zero. ONE accessor, so the
    knowledge axis of :func:`state_history` is fed the same way from every selector.

    **THE ``year_month`` LAG IS THE ONE THE LIVE READ APPLIES (sec 1.4, D21), and this accessor read the
    wrong field.** MEASURED at the S3 re-fix against the live registry: ``silver_noaa_oni`` (ym 36),
    ``silver_noaa_iod`` (45) and ``gold_weather_z`` (7) declare their lag in ``ym_publication_lag_days``
    and leave ``publication_lag_days`` null, so this function returned **0 on all three** -- the three
    ``year_month`` cards the board leans hardest on. The consequence is not a rounding one: with a zero
    lag the analog history scores every candidate crossing on a distribution containing the month's own
    print, which nobody held on the day the candidate is dated by. ONI at a 2001 crossing was ranked
    against a September figure CPC published in December. The board's live read has applied the lag
    since S1 (``query._ym_lagged_asof_ym``); the history it compares against had not.

    ONE FIELD OR THE OTHER, NEVER BOTH: the lint refuses ``ym_publication_lag_days`` on a card that is
    not ``year_month`` (state/lint.py:539), so a declared ym lag IS the card's year_month declaration
    and needs no second semantics field carried onto the row to be read correctly here.

    THE LAG IS PER METRIC, NOT PER CARD (2026-09-11), and the rule lives in ONE place --
    ``registry.metric_lag_override``. The row's OWN stamped ``ym_publication_lag_days`` is passed as the
    default and the registry is consulted for the METRIC OVERRIDE ALONE, never the card default: the
    stamp is what ``feeders._recency`` read this row under, and a card-level fallback would let a
    registry loaded now overrule it. So a card with no per-metric declaration, a fixture row, and a
    table the registry cannot resolve all read exactly what they read before; only a metric carrying
    its own declared lag moves. ``gold_weather_z`` is the card that forced it: ``drought_z`` rides
    CHIRPS month blocks (BOUNDED 11 < lag <= 22 days past month-end by the two 2026-09-11 HEAD reads;
    the card declares 22 plus a 3-day margin, 25 -- the 45 first written here was a misread of those
    same two observations) while its four NASA siblings ride a 3-day daily feed, and one lag on this
    axis has to be wrong for the four or wrong for the fifth."""
    st = getattr(row, "state", None)
    if st is None:
        return 0
    rec = st.recency or {}
    from leviathan.graphrag.numbers import registry as REG
    for v in (REG.metric_lag_override(getattr(st, "table", ""), getattr(st, "metric", ""),
                                      default=rec.get("ym_publication_lag_days")),
              rec.get("publication_lag_days")):
        try:
            v = int(v or 0)
        except (TypeError, ValueError):
            continue
        if v:
            return v
    return 0


# ---------------------------------------------------------------------------------------------------
# THE PRODUCER -- what the render is handed
# ---------------------------------------------------------------------------------------------------
def seed_rows(bd, knobs) -> list:
    """THE ROWS THE ANALOG LEG SEEDS ONE DIMENSION EACH FROM -- the ONE published rule (09-24, CONTRACT K15).

    A row seeds when it is LOUD, carries an ``ok`` state with its own input series and is not
    context-only, taken in ``Board.order`` up to ``knobs.analog_dims``. :func:`analog_rows` selects on
    exactly these rows and ``seam._analog_dims`` reads THIS function, so the two spellings of the declared
    set cannot drift (they were two copies until 09-24, pinned to agree by test_state_seam).

    **ONE SERIES, ONE DIMENSION, ONE SPELLING.** Loudness ranks the UNSIGNED state, so both poles of a
    declared phase pair land loud on ONE ONI print, and the first cut took both as two seeds AND two
    dimensions of the like-state vector -- "three of three dimensions" on the 2024 page was two series with
    ONI counted twice. The seeds fold on the series key (``state.key.label()``), keeping the LOUDEST
    member's id -- the spelling ``seam.dim_for_hop`` already resolves a hop's series to -- so a board with
    no duplicate series seeds byte for byte what it seeded before (B12)."""
    if not knobs or int(getattr(knobs, "analog_dims", 0) or 0) <= 0:
        return []
    order = {key: i for i, key in enumerate(getattr(bd, "order", None) or ())}
    loud = sorted((r for r in (getattr(bd, "rows", None) or ()) if r.legs.get("loud")),
                  key=lambda r: order.get(r.key, len(order)))
    seen: set = set()
    out: list = []
    for r in loud:
        st = r.state
        if st is None or status_word(st.status) != "ok" or r.context_only:
            continue
        try:
            sk = st.key.label()
            if not (st.inputs or {}).get(sk):
                continue
        except Exception:                               # noqa: BLE001 -- a row with no series key seeds nothing
            continue
        if sk in seen:
            continue
        seen.add(sk)
        out.append(r)
        if len(out) >= int(knobs.analog_dims):
            break
    return out


def analog_rows(bd, *, knobs, benchmark_fn=None, receipt_fn=None, price_dims=(),
                conventions: Optional[dict] = None, lag_days_fn=None,
                first_dim: Optional[str] = None) -> list:
    """EVERY analog stanza this board can carry, one per analog DIMENSION (sec 4.2 / 4.3 / 4.4).

    THE SHAPE MATCHES THE PRICER, and that is the join: ``walk._stage2`` reserves
    ``analog_dims * analog_k`` benchmark seats and the same number of receipt candidates capped at
    ``receipt_cap``, so this producer runs ONE selection per top-``analog_dims`` loud row and takes
    ``analog_k`` dates from each. A producer with a different shape would spend seats nobody priced.

    ``benchmark_fn(contract) -> {'values','dates','unit','label','table','metric'}`` and
    ``receipt_fn(contract, driver_id, near) -> [receipt dicts]`` are INJECTED: their reads are the
    wave-2 columns, and a seat the caller does not fill is a stanza that says so rather than one that
    fetches.

    SCAN RUNS NO ANALOGS by budget, not by gap (``analog_dims`` and ``analog_k`` are both zero there),
    and the empty list is the honest result.

    ``first_dim`` IS THE TOP CHAIN'S RECEIPT HOP and it is passed straight through to
    :func:`select_analogs` (DESIGN C.2). It orders the vector the coverage line enumerates and nothing
    else; the caller is the render half and the default is ``None``, so no wired path moves until one
    passes it.

    **THE PERCENTILE VECTOR IS BUILT FOR EVERY SEED NOW, and it is built for the STANZA rather than for
    the RANK.** ``want_pct`` used to be lit only where a ``percentile_bands`` convention needed a band
    crossing. The widened state vector reads it on every seed -- but as a PRINTED FACT: round 2 took the
    prefix percentile out of :data:`DISTANCE_COMPONENTS` because its reference population grows along the
    record (8 to 440) and a rank against 33 observations is not the same statistic as a rank against 440.
    What the reader gets is "where it sat in its own record then, and where it sits now"; what the
    SELECTOR ranks on is the fixed-window z alone. The cost is one ``_prefix_percentiles`` pass per seed
    (O(n log n), ``analog_dims`` of them, measured in this lane's probe), and it is the one place the
    relaxation spends anything at all."""
    if not knobs or int(knobs.analog_dims) <= 0 or int(knobs.analog_k) <= 0:
        return []
    conv_doc = _conventions() if conventions is None else conventions
    order = {key: i for i, key in enumerate(bd.order)}
    seeds = seed_rows(bd, knobs)
    if not seeds:
        return []

    hists: dict = {}
    dims: list = []
    row_runs: dict = {}
    for r in seeds:
        # THE KNOWLEDGE AXIS IS THE CARD'S OWN (sec 4.1). `lag_days_fn` is the injected override the
        # walk uses where it knows the card's declared lag better than the row does; the default reads
        # it off the row the producer already filled.
        lag_r = int(lag_days_fn(r) if lag_days_fn else _lag_days_of(r))
        h = state_history(r.state, lag_days=lag_r, want_pct=True)
        hists[r.key] = h
        z_now = None
        if r.state.z and not r.state.z.get("declined"):
            z_now = TR.num_or_none(r.state.z["value"])
        # EVERY "NOW" COMES OFF THE ROW, AT THE ROW'S OWN VINTAGE (round 2, MAJOR 5) -- not one of them
        # off the tail of the knowledge-axis vector. ``z_now`` always did; ``pct_now``, ``dir_now`` and
        # ``run_now`` now do too, from the three measures ``feeders`` stamped at the as-of. MEASURED on
        # ``b40_event / drought`` (25-day declared lag): the row's z is 0.7581 and the vector's tail is
        # 0.6351, so the two halves of one dimension's state were being read 0.123 sigma apart on
        # distances that decide at 0.011. A measure the row DECLINED is a hole here and never a guess:
        # ``likeness`` reads the component as unobserved rather than borrowing an older print.
        pct_now = None
        if r.state.percentile and not r.state.percentile.get("declined"):
            pct_now = TR.num_or_none(r.state.percentile.get("value"))
        dir_now = run_now_r = None
        if r.state.run and not r.state.run.get("declined"):
            dir_now = r.state.run.get("direction")
            run_now_r = TR.num_or_none(r.state.run.get("length"))
        row_runs[r.key] = run_now_r
        dims.append({"id": r.driver_id, "hist": h, "z_now": z_now, "pct_now": pct_now,
                     "dir_now": dir_now, "run_now": run_now_r, "series_key": r.state.key.label()})
    dims.extend(_price_dimensions(price_dims))
    price_admitted = len(dims) - len(seeds)

    floor_year = _coverage_floor(seeds)
    out: list = []
    for r in seeds:
        band = r.lag_band
        conv = conv_doc.get(r.state.key.ref)
        lag_days = int(lag_days_fn(r) if lag_days_fn else _lag_days_of(r))
        sel = select_analogs(hists[r.key], dims=dims, asof=bd.asof, band=band,
                             analog_k=int(knobs.analog_k), convention=conv, lag_days=lag_days,
                             first_dim=first_dim,
                             run_now=(None if row_runs.get(r.key) is None
                                      else int(row_runs[r.key])))
        seat = order.get(r.key, len(order))
        # THE SELECTION'S OWN COUNTS RIDE EVERY ROW, FIRED OR DECLINED, and they are DATA -- this
        # producer renders nothing. ``dims_declared``/``dims_seen``, ``sign_agree``/``sign_seen``,
        # ``record_span`` and ``precedes_dims`` are the clauses DESIGN C.1 promises the header, and
        # ``n_candidates_raw``/``n_candidates_pit`` are the yield the probe and the arm report read.
        counts = {"n_candidates": sel["n_candidates"],
                  "n_candidates_raw": sel["n_candidates_raw"],
                  "n_candidates_pit": sel["n_candidates_pit"],
                  "n_candidates_head": sel["n_candidates_head"],
                  # THE FIFTH EXIT IS A NUMBER ON THE ROW NOW (round 3, minor). It is
                  # ``n_candidates_pit - n_candidates``: the candidates whose outcome window had closed
                  # and whose print existed, declined because no declared dimension carried a readable z
                  # at their date. Counted, so the decline is auditable rather than inferable.
                  "n_dropped_unreadable": sel["n_dropped_unreadable"],
                  "dims_declared": sel["dims_declared"], "dims_order": sel["dims_order"],
                  "first_dim": sel["first_dim"], "record_span": sel["record_span"],
                  "floor_year": floor_year, "price_dims": price_admitted,
                  # K15: the seed's OWN series, one dimension per series (the fold above)
                  "series_key": r.state.key.label()}
        if sel["declined"]:
            out.append({"contract": r.contract, "driver_id": r.driver_id, "band": band,
                        "asof": bd.asof, "declined": sel["declined"], "seat": seat,
                        "detail": sel.get("detail"), **counts})
            continue
        for pick in sel["picked"]:
            _after = _receipts_after(bd, r, pick["date"], receipt_fn=receipt_fn,
                                     cap=int(knobs.receipt_cap))
            out.append({
                "contract": r.contract, "driver_id": r.driver_id, "band": band, "asof": bd.asof,
                "date": pick["date"], "distance": pick["distance"], "kind": pick["kind"],
                "seat": seat, "declined": None, "detail": None, **counts,
                "dims_seen": pick["dims_seen"], "dims_any_seen": pick["dims_any_seen"],
                "dims_unread": pick["dims_unread"], "unread_sigma": pick["unread_sigma"],
                "sign_agree": pick["sign_agree"], "sign_seen": pick["sign_seen"],
                "dir_agree": pick["dir_agree"], "dir_seen": pick["dir_seen"],
                "run_length": pick["run_length"], "run_now": pick["run_now"],
                "run_gap": pick["run_gap"], "per_dim": pick["per_dim"],
                "precedes_dims": pick["precedes_dims"], "near_asof": pick["near_asof"],
                # THE PICK'S SEAT IN THE POOL THE HEADER COUNTS (round-2 blocker 2), copied by name
                # like every other field on this row: the header may only say "this one the nearest"
                # where the selection measured it so.
                "pool_rank": pick["pool_rank"],
                # THE FLAG'S OWN FIGURE. This dict copies the picked row FIELD BY FIELD rather than
                # splatting it, so a fact the selection computes and this line does not name never
                # reaches a reader -- which is the shape of the whole defect this lane closes.
                "months_to_asof": pick["months_to_asof"],
                "outcomes": tuple(_outcomes_for(bd, r, pick["date"], benchmark_fn=benchmark_fn)),
                "receipts": tuple(_receipts_for(bd, r, pick["date"], receipt_fn=receipt_fn,
                                                cap=int(knobs.receipt_cap))),
                # WHAT THE RECORD SAID **NEXT**, over the same window the outcome row reads the price
                # over. The page prints the COUNT and never the titles; see :func:`_receipts_after`.
                # THE COUNT IS THE WINDOW'S AND THE CARRY IS THE CAP'S (round-2 blocker 3). They are
                # two numbers off ONE walk: `n_receipts_after` is how many dated documents the corpus
                # holds inside `(t, t+band]`, and `receipts_after` is the rows this tier carries --
                # the cut between them is a ROW on the page (`render.render_board`'s analog receipt
                # after cut), never a silently smaller integer wearing the count's sentence.
                "receipts_after": tuple(_after[: int(knobs.receipt_cap)]),
                "n_receipts_after": (None if receipt_fn is None or int(knobs.receipt_cap) <= 0
                                     else len(_after)),
            })
    return out


def _conventions() -> dict:
    from leviathan.graphrag.state.lint import load_conventions
    return dict((load_conventions().get("conventions") or {}))


def _label(node_id: str) -> str:
    """The estate's ONE display vocabulary for a driver id. Every label this module writes reaches a
    reader through ``render.sb_analog_outcome``, and ``register.internal_leaks`` (:836) is never
    relaxable -- a raw id or slug in an outcome label trips it on every fan board the analog touched."""
    from leviathan.graphrag.state.render import humanise
    return humanise(node_id)


def _board(slug: str) -> str:
    from leviathan.graphrag.state.render import board_label
    return board_label(slug)


def _month_words(iso: str) -> str:
    from leviathan.graphrag.state.rows import month_words
    return month_words(iso)


def _price_dimensions(price_dims) -> list:
    """The ADMITTED price dimensions (D25): up to two, beside the driver rows and NEVER ranked against
    them. Each entry is ``{'id','values','dates','window'}`` and is turned into a state vector here on
    the same prefix arithmetic a driver row uses -- "last time the price sat here" is a candidate date
    like any other, and the likeness then asks whether the DRIVERS looked alike too."""
    out: list = []
    for pd in list(price_dims or ())[:2]:
        # THE SAME BOUNDARY AS A DRIVER DIMENSION: a price dimension is ranked by the same prefix
        # arithmetic and joined to a candidate by the same date, so it may not carry a blank either.
        vals, ds, _n_dropped = TR.dated_pairs(pd.get("values"), pd.get("dates"))
        if not vals:
            continue
        key = str(pd.get("id") or "price")
        bundle = {key: {"values": vals, "dates": ds}}
        win = int(pd.get("window") or min(len(vals), 60))
        res, _rec = TR.run_transform("rolling_zscore", bundle, key=key, params={"window": win})
        if res.get("declined"):
            continue
        series = list(res.get("series") or [])
        # THE PRICE DIMENSION CARRIES ITS PERCENTILE TOO, for the reason the seed rows do: it is read by
        # the same prefix arithmetic and it is the component that makes the dimension OBSERVABLE across
        # the stretch where its rolling window is still filling. ``_prefix_percentiles`` is applied
        # directly rather than through :func:`percentile_vector` because a price dimension declares no
        # publication lag -- the knowledge axis is the identity here and re-indexing by zero would be the
        # same vector at one more pass.
        pcts = _prefix_percentiles(vals)
        hist = {"dates": ds, "values": vals, "z": series, "pct": pcts, "window": win, "lag_days": 0}
        last = len(ds) - 1
        # THE THREE OTHER "NOW" READINGS ARE DECLARED HERE AND THEY COME OFF THE TAIL -- which on this
        # dimension IS the as-of vintage, and that is why it is allowed here and refused everywhere else
        # (round 2, MAJOR 5). A price dimension declares NO publication lag, so ``_knowable_indices`` is
        # the identity, the vector's last position is the reading of the as-of itself, and there is no
        # row carrying a second opinion. A seed dimension has both -- a lag and a row -- and takes the
        # row's.
        out.append({"id": key, "z_now": series[-1] if series else None, "hist": hist,
                    "pct_now": next((p for p in reversed(pcts) if p is not None), None),
                    "dir_now": _direction_at(hist, last),
                    "run_now": _run_at(hist, last)})
    return out


def _coverage_floor(seeds) -> str:
    """``max(first_obs over dims)``, PRINTED (sec 4.2). A loud set containing an FX row cannot see 2003
    and the header says so; the number is the floor the whole stanza is honest about."""
    years: list = []
    for r in seeds:
        cov = (r.state.coverage or {})
        d = cov.get("first_obs") or cov.get("history_start") or ""
        if str(d)[:4].isdigit():
            years.append(str(d)[:4])
    return max(years) if years else "the record's own start"


def _bench_read(bd) -> None:
    """ONE analog BENCHMARK read, onto the ledger's own field. A call is counted whether or not the
    producer returns a series, because a read that came back empty is still a read the mirror served --
    the same rule `WaveLedger` keeps for a declined key."""
    try:
        bd.ledger.benchmark_reads += 1
    except Exception:                                   # noqa: BLE001 -- a counter never costs a row
        pass


def _outcomes_for(bd, seed_row, t: str, *, benchmark_fn=None) -> list:
    """The consequence rows for ONE like date: the seed's own CHILDREN on the anchor board, the FAR
    boards that carry the same driver (each over ITS OWN declared band), and the anchor's MONTHLY
    BENCHMARK. Every one is read over the PARENT'S band, and each row says whose band it used."""
    out: list = []
    # **THE MARKET'S OWN PRICE -- THE CALL'S UNITS -- LEADS (09-24, CONTRACT K15 / OWNER DECISION O-7).**
    # The four 09-24 stanzas read their outcome on weather z-scores and on an annual production sheet, and
    # a PM called each "furniture": a like state informs a price call through what the PRICE did after it.
    # The anchor's own same-contract tape (``bd.tape``, the arrays the SB-T read already holds -- ZERO
    # reads) is read over the seed's band from the like date, through the same two-end producer every
    # other outcome takes, and stamped ``call_units``. It is an OUTCOME and never a likeness dimension, so
    # the selection above is untouched. A board carrying no tape for the contract says so by the tape's
    # own word.
    _tp = (getattr(bd, "tape", None) or {}).get(seed_row.contract)
    if _tp is None or status_word(getattr(_tp, "status", "") or "") != "ok":
        out.append({"label": f"the {_board(seed_row.contract)} price", "unit": "", "table":
                    "silver_futures_eod", "metric": "settle", "commodity": seed_row.contract,
                    "country": None, "band": seed_row.lag_band, "t": t, "call_units": True, "tape": True,
                    "declined": ("no_tape_slug" if _tp is None
                                 else status_word(getattr(_tp, "status", "") or "") or "no_tape_rows"),
                    "decline_leg": "analog"})
    else:
        _inp = dict(getattr(_tp, "inputs", None) or {})
        _tk = "%s|%s" % (getattr(_tp, "slug", ""), getattr(_tp, "contract_month", ""))
        _arr = _inp.get(_tk) or (next(iter(_inp.values())) if len(_inp) == 1 else {}) or {}
        _cm = str(getattr(_tp, "contract_month", "") or "")
        _o = outcome_over_band(
            label=(f"the {_board(seed_row.contract)} {_month_words(_cm)} delivery".replace("  ", " ")
                   if _cm else f"the {_board(seed_row.contract)} price"),
            values=_arr.get("values"), dates=_arr.get("dates"), t=t, band=seed_row.lag_band,
            asof=bd.asof, unit=str(getattr(_tp, "unit", "") or ""), table="silver_futures_eod",
            metric="settle change over the band from the like state", commodity=seed_row.contract,
            country=None, key=_tk)
        # ``tape`` marks the TRADED CONTRACT's own settle -- the call's units at their source -- so it leads
        # even the monthly benchmark, which is this market's price but not the contract the call is on.
        out.append(dict(_o, call_units=True, tape=True))
    _clag = 0
    for cid in (seed_row.children or ()):
        child = bd.row(seed_row.contract, cid)
        if child is None or child.state is None or status_word(child.state.status) != "ok":
            continue
        st = child.state
        arrays = (st.inputs or {}).get(st.key.label()) or {}
        try:
            _clag = int(_lag_days_of(child))
        except Exception:                               # noqa: BLE001 -- no lag read is a zero lag
            _clag = 0
        out.append(outcome_over_band(
            label=f"{_label(cid)} on {_board(child.contract)}",
            values=arrays.get("values"), dates=arrays.get("dates"), t=t, band=seed_row.lag_band,
            asof=bd.asof, unit=st.narrate_unit or st.unit or "", table=st.table,
            metric=st.metric, commodity=st.key.commodity, country=st.key.country,
            key=st.key.label(), lag_days=_clag))
    if benchmark_fn is not None:
        # COUNTED (S6 review, major 7). The benchmark read happens OUTSIDE both wave rectangles -- this
        # function runs after wave 2 has closed -- so without its own ledger field a real spend would be
        # invisible to `cascade._cw_turn_spent`, which is the "a real spend read as zero" failure the
        # enumeration exists to prevent and the one S5 had to repair for the composer sub-legs.
        # `Ledger.benchmark_reads` rides `reads_used`, so the walk sees it the day the seam wires a
        # producer. It is 0 on every path today, because no caller wires one.
        _bench_read(bd)
        bm = benchmark_fn(seed_row.contract)
        if bm:
            # THE ANCHOR'S OWN MONTHLY PRICE BENCHMARK IS A PRICE OF THIS MARKET -- the call's units (K15).
            out.append(dict(outcome_over_band(
                label=bm.get("label") or f"the monthly benchmark for {_board(seed_row.contract)}",
                values=bm.get("values"), dates=bm.get("dates"), t=t, band=seed_row.lag_band,
                asof=bd.asof, unit=bm.get("unit") or "", table=bm.get("table") or "silver_pink_sheet",
                metric=bm.get("metric") or "", commodity=seed_row.contract, country=None,
                key="benchmark"), call_units=True))
    # THE FAR BOARDS, EACH OVER **ITS OWN** DECLARED BAND (sec 4.3: "a far board uses ITS edge's band
    # for the same parent"). That is how ONE like state yields two horizons -- the bean window over one
    # to two quarters and the palm window over two to four -- and it is the whole content of scenario 2.
    #
    # WHAT A FAR BOARD'S OUTCOME IS **NOT**: the shared driver's own array read again. A globally-keyed
    # ref (`oni_climate`) is ONE StateRow behind thirty-five rows, so reading it "on the far board"
    # returns the parent's own move with another board's name on it -- MEASURED at this landing as
    # "El Nino on BMF arabica coffee over the band from that state: 0.27 degC at the near end", which is
    # the ONI change, relabelled, on a board where nothing about coffee was read. The far board's
    # CONSEQUENCE is its own price, so the benchmark is the series; where a far board carries a
    # DIFFERENT series key (a scope-keyed far state the wave-2 cap actually bought) that state is the
    # consequence and is read instead.
    seen_far: set = set()
    for e in bd.fan:
        if (e["contract"], e["driver_id"]) != seed_row.key:
            continue
        for f in e["far"]:
            if f["contract"] in seen_far:
                continue
            seen_far.add(f["contract"])
            if benchmark_fn is not None:
                _bench_read(bd)
            bm = benchmark_fn(f["contract"]) if benchmark_fn is not None else None
            if bm:
                out.append(outcome_over_band(
                    label=bm.get("label") or f"the monthly benchmark for {_board(f['contract'])}",
                    values=bm.get("values"), dates=bm.get("dates"), t=t, band=f["lag_band"],
                    asof=bd.asof, unit=bm.get("unit") or "",
                    table=bm.get("table") or "silver_pink_sheet", metric=bm.get("metric") or "",
                    commodity=f["contract"], country=None, key=f"benchmark:{f['contract']}"))
                continue
            sk = f.get("series_key")
            if not sk or sk not in bd.series or sk == seed_row.series_key:
                continue
            st = bd.series[sk]
            arrays = (st.inputs or {}).get(st.key.label()) or {}
            out.append(outcome_over_band(
                label=f"{_label(f['driver_id'])} on {_board(f['contract'])}",
                values=arrays.get("values"), dates=arrays.get("dates"), t=t, band=f["lag_band"],
                asof=bd.asof, unit=st.narrate_unit or st.unit or "", table=st.table,
                metric=st.metric, commodity=st.key.commodity, country=st.key.country,
                key=st.key.label()))
    return out


def _receipts_for(bd, seed_row, t: str, *, receipt_fn=None, cap: int = 0) -> list:
    """The dated documents that EXPLAIN a chosen date (sec 4.4). The retrieval is INJECTED and its
    publication axis is pre-filtered to ``<= t`` -- the second as-of hop's own discipline.

    THE ABSENCE IS THE ROW'S OWN SENTENCE, not a silence: when this returns nothing the stanza carries
    "the corpus holds no dated document explaining this state (the window before it); the figures
    above stand on the series alone",
    which the render adds. There is no count floor anywhere here -- one mechanism-narrating receipt is
    enough, and frequency floors deny the tail."""
    if receipt_fn is None or cap <= 0:
        return []
    # COUNTED (S6 review, major 6): `BoardEvidenceBorrows` is "analog receipt reads on the evidence
    # pool", and it used to publish the RESERVED SEATS instead -- 3 on every fired Analysis board and 5
    # on every fired Cascade board while this branch returned at zero reads, because no caller wires a
    # `receipt_fn`. The borrow is counted HERE, at the one place a borrow happens.
    try:
        bd.ledger.evidence_borrows += 1
    except Exception:                                   # noqa: BLE001 -- a counter never costs a row
        pass
    got = receipt_fn(seed_row.contract, seed_row.driver_id, t) or []
    out: list = []
    for i, r in enumerate(got[:cap], start=1):
        d = str((r.get("date") if isinstance(r, dict) else getattr(r, "date", "")) or "")
        if d and d[:10] > str(t)[:10]:
            continue                                # the publication axis is <= t, always
        out.append({"e": i, "t": int((r.get("tier") if isinstance(r, dict) else 3) or 3),
                    "date": d, "source": r.get("source") if isinstance(r, dict) else "",
                    "text": r.get("text") if isinstance(r, dict) else "",
                    "event_date": r.get("event_date") if isinstance(r, dict) else None})
    return out


def _receipts_after(bd, seed_row, t: str, *, receipt_fn=None, cap: int = 0) -> list:
    """The dated documents that fall inside the window that FOLLOWED a chosen date -- ``(t, t+band]``.

    **IT IS THE OTHER HALF OF SEC 4.4 AND IT IS PIT-SAFE BY CONSTRUCTION.** :func:`_receipts_for`
    filters the publication axis to ``<= t``: documents that EXPLAIN the state. This one takes the
    band's own window forward from ``t`` -- the same window :func:`outcome_over_band` reads the
    consequence over -- because the reader who is shown what the price did next is owed what the record
    SAID next. There is no as-of hop to argue about: :func:`select_analogs` admits a candidate only
    where the far edge of that same band has ALREADY CLOSED against the as-of, so every date this
    window can reach is strictly behind the as-of already. A band with no declared far edge has no
    window and takes none.

    IT COUNTS AND DOES NOT ENUMERATE. The row carries the documents; the page prints the COUNT
    (``render.analog_selection_clauses``), because a document title is retrieved text and SB-A is a
    letters-only class -- and because the board SELECTS rather than enumerating. The rows are kept
    whole so a later sitting that mints an ``[E]`` for them does not have to re-read the pool.

    THE BORROW IS COUNTED WHERE THE BORROW HAPPENS, exactly as :func:`_receipts_for` counts its own:
    ``bd.ledger.evidence_borrows`` is "analog receipt reads on the evidence pool" and a second read of
    the same pool is a second borrow. It is not a READ -- ``Ledger.reads_used`` does not sum it,
    because ``ground()`` has already paid for these propositions and the seam hands them down.

    **IT RETURNS THE WINDOW, NEVER THE CAP** (round-2 blocker 3). This walk used to stop at
    ``len(out) >= cap`` and :func:`analog_rows` published ``len()`` of what it got, so the number the
    page prints as "N dated documents inside the window that followed it" was CONSTANT AT THE CAP
    whatever the corpus held -- measured through the real seam with a pool carrying twelve documents
    inside the forward window: deep printed three against eleven, max printed five against eight, and
    the ordinary fixture pool could not see it because it carries two or three per node. A cap is a CUT
    ROW and never a count. So the window is walked WHOLE here, the caller publishes ``len()`` of it as
    the count and carries only the first ``cap`` rows, and ``render.render_board`` prints the cut as
    its own absence row. ``cap`` still switches the LEG (``receipt_cap`` is zero at quick, which is the
    tier declaring it buys no documents at all) -- it no longer bounds the arithmetic."""
    if receipt_fn is None or cap <= 0:
        return []
    band = getattr(seed_row, "lag_band", None)
    max_q = getattr(band, "max_q", None)
    if max_q is None:
        return []
    far = _window_end(t, int(max_q) * QUARTER_MONTHS)
    if far is None:
        return []
    try:
        bd.ledger.evidence_borrows += 1
    except Exception:                                   # noqa: BLE001 -- a counter never costs a row
        pass
    got = receipt_fn(seed_row.contract, seed_row.driver_id, far) or []
    lo, hi = str(t)[:10], str(far)[:10]
    out: list = []
    for r in got:
        d = str((r.get("date") if isinstance(r, dict) else getattr(r, "date", "")) or "")
        if not d or not (lo < d[:10] <= hi):
            continue                                # (t, t+band], half-open at the like date itself
        out.append({"t": int((r.get("tier") if isinstance(r, dict) else 3) or 3),
                    "date": d, "source": r.get("source") if isinstance(r, dict) else "",
                    "text": r.get("text") if isinstance(r, dict) else "",
                    "event_date": r.get("event_date") if isinstance(r, dict) else None})
    return out


# ---------------------------------------------------------------------------------------------------
# 4.3 LEG B -- the tape, DARK behind GRAPHRAG_STATE_BOARD_ANALOG_TAPE
# ---------------------------------------------------------------------------------------------------
def leg_b_rows(analogs, *, on: bool = False, cell_fn=None, verdict_fn=None, span_max_days=None,
               asof: str = "", edge_sign: str = "") -> list:
    """LEG B (sec 4.3, D6): the same outcome read on the TAPE through ``cascade._cw_cell``, rendered by
    ``_cw_cell_line`` / ``_cw_verdict_line`` BYTE-FOR-BYTE -- functions IMPORTED, never seams edited.

    IT SHIPS DARK AND THIS FUNCTION IS WHY THAT IS A DECISION RATHER THAN A GAP: the plumbing exists,
    is tested against an injected cell producer, and returns an EMPTY list with the rider off. The one
    blocking unknown is the span fence -- ``CW_SPAN_MAX_DAYS`` is 270, r2-certified to about 267 days,
    failures start around 563, and the gap between them is unmeasured, while a two-to-four-quarter band
    is about 365 days. S0 probe P2 re-runs that fence before this arms; if 365 does not close it, the
    window prices the LOWER end of the band and the row says so in words.

    A window past the certified span declines ``span_out_of_band`` BY NAME rather than being read on a
    fence nobody measured."""
    if not on:
        return []
    if cell_fn is None or verdict_fn is None:
        from leviathan.graphrag.numbers import cascade as casc
        cell_fn = cell_fn or getattr(casc, "_cw_cell")
        verdict_fn = verdict_fn or getattr(casc, "_cw_verdict_line")
        span_max_days = span_max_days if span_max_days is not None else getattr(
            casc, "CW_SPAN_MAX_DAYS", 270)
    span_max_days = int(span_max_days or 270)
    out: list = []
    for a in analogs:
        if a.get("declined") or not a.get("date"):
            continue
        band = a["band"]
        if band.min_q is None or band.max_q is None:
            out.append({"contract": a["contract"], "driver_id": a["driver_id"],
                        "declined": "horizon_open"})
            continue
        t1 = _window_end(a["date"], int(band.min_q) * QUARTER_MONTHS)
        t2 = _window_end(a["date"], int(band.max_q) * QUARTER_MONTHS)
        if t1 is None or t2 is None:
            # THE SAME SKIP THE UNDATED ANALOG TAKES at the top of this loop: leg B is a cell over a
            # dated window, and there is no window here to read one over.
            continue
        if _days_between(t1, t2) > span_max_days:
            t2 = _add_days(t1, span_max_days)
            note = ("the window is the lower end of the declared band, because the span the tape read "
                    "certifies is shorter than the band")
        else:
            note = ""
        cell = cell_fn(a["contract"], t1, t2, asof or a["asof"])
        # THE VERDICT IS `stats.sign_agreement` AGAINST THE DECLARED EDGE SIGN, rendered by
        # `_cw_verdict_line` UNCHANGED (functions imported, seams never edited). It is computed only
        # when the cell actually carries both moves: a verdict over a half-read cell would be a
        # direction read off one leg, which is the one thing this row must not do.
        verdict_line = None
        moves = cell if isinstance(cell, dict) else {}
        pm, cm = moves.get("parent_move"), moves.get("child_move")
        if verdict_fn is not None and pm is not None and cm is not None:
            from leviathan.graphrag.numbers import stats as _st
            res = _st.sign_agreement(pm, cm, edge_sign or "+")
            verdict_line = verdict_fn(_label(a["driver_id"]), _board(a["contract"]),
                                      "unreadable" if res.get("declined") else res.get("value"))
        out.append({"contract": a["contract"], "driver_id": a["driver_id"], "span": (t1, t2),
                    "note": note, "cell": cell, "verdict_line": verdict_line,
                    "declined": None if cell else "no_tape_rows"})
    return out


def _days_between(a: str, b: str) -> int:
    import datetime as _dt
    return (_dt.date.fromisoformat(str(b)[:10]) - _dt.date.fromisoformat(str(a)[:10])).days


def _analog_trace_row(a: dict) -> dict:
    """ONE analog row, compact, for the trace (K15): no arrays, no receipts' text -- the facts a census
    needs to read a stanza decision offline."""
    per = a.get("per_dim")
    agree = (sum(1 for r in (per or ()) if (r or {}).get("sign_agree") is True) if per is not None
             else a.get("sign_agree"))
    return {"contract": a.get("contract"), "driver_id": a.get("driver_id"),
            "series_key": a.get("series_key"),
            "date": a.get("date"), "dims_seen": a.get("dims_seen"), "dims_declared": a.get("dims_declared"),
            "agree_n": agree, "decline": a.get("declined"),
            "outcomes": [{"label": o.get("label"), "call_units": bool(o.get("call_units")),
                          "decline": o.get("declined")} for o in (a.get("outcomes") or ())]}


def analog_leg(bd, rows) -> dict:
    """The ``analog`` leg's stamp (sec 6.7). ``not_reached`` when the tier runs no analogs at all --
    Scan's own case, and it is not a decline, because nothing was attempted and no reader is owed a
    sentence about a cut that never happened."""
    # THE ANALOG ROWS RIDE THE BOARD (09-24, CONTRACT K15): one compact entry per selected or declined
    # stanza -- driver, series, date, the dimensions seen, how many AGREE, the decline word -- on the
    # board's own ``analogs`` field, which the seam puts on the ``state_board`` trace. Until now no analog
    # row rode any trace, so "max 10 -> 5" was unreadable (the 09-24 read's instrument gap). The render
    # stamps ``withheld`` / ``rendered`` on these same entries when it decides a stanza.
    try:
        bd.analogs = [_analog_trace_row(a) for a in (rows or ())]
    except Exception:                                   # noqa: BLE001 -- telemetry never costs a leg
        pass
    if not rows:
        return bd.stamp("analog", "not_reached")
    fired = [a for a in rows if not a.get("declined")]
    if fired:
        return bd.stamp("analog", "fired")
    counts: dict = {}
    for a in rows:
        counts[a["declined"]] = counts.get(a["declined"], 0) + 1
    return bd.stamp("analog", "declined",
                    reason=sorted(counts, key=lambda x: (-counts[x], x))[0])
