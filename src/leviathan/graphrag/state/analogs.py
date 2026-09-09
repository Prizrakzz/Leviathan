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

import math
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


def check_cascade_analog_imports() -> list:
    """Every name in :data:`CASCADE_ANALOG_IMPORTS` resolves. Returns the missing ones; empty == clean."""
    from leviathan.graphrag.numbers import cascade as casc
    return [n for n in CASCADE_ANALOG_IMPORTS if not hasattr(casc, n)]


# ---------------------------------------------------------------------------------------------------
# 4.1 THE HISTORICAL STATE VECTOR -- arithmetic over an array already fetched
# ---------------------------------------------------------------------------------------------------
def state_history(st, *, window: Optional[int] = None, lag_days: int = 0,
                  want_pct: bool = False) -> dict:
    """``{'dates', 'values', 'z', 'pct', 'window', 'lag_days'}`` -- the state AS KNOWABLE AT EACH date.

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
    values = [float(v) for v in (arrays.get("values") or [])]
    dates = [str(d) for d in (arrays.get("dates") or [])]
    win = int(window or (st.z or {}).get("window_n") or (st.z or {}).get("window") or 0)
    lag = max(0, int(lag_days or 0))
    out = {"dates": dates, "values": values, "z": [None] * len(values), "pct": [None] * len(values),
           "window": win, "lag_days": lag}
    if not values:
        return out
    z_raw: list = [None] * len(values)
    if win:
        res, _rec = TR.run_transform("rolling_zscore", st.inputs, key=key, params={"window": win})
        if not res.get("declined"):
            z_raw = list(res.get("series") or [])
    idx = _knowable_indices(dates, lag)
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
        x = float(v)
        bisect.insort(seen, x)
        n = i + 1
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
    idx = _knowable_indices(hist.get("dates") or [], int(hist.get("lag_days") or 0))
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


def _window_end(iso: str, months: int) -> str:
    """The END OF THE MONTH ``months`` after ``iso`` -- the resolution a band declared in QUARTERS has.

    THE MONTH IS THE GRAIN AND THE DAY IS NOT, and the first cut got that wrong in the direction that
    LOSES an observation. ``_add_months`` preserves the day: six months after a 2000-11-30 print is
    2001-05-30, and a month-end series' May print (2001-05-31) is one day LATER -- so
    :func:`_index_on_or_before` fell back to APRIL and the "far end" of a one-to-two-quarter band was
    read five months out instead of six. A lag the graph states in quarters resolves to a month, so the
    window's end is that month's end and the month's own print is inside it."""
    y, m = int(iso[0:4]), int(iso[5:7])
    total = (y * 12 + (m - 1)) + int(months)
    y2, m2 = total // 12, total % 12 + 1
    last = [31, 29 if (y2 % 4 == 0 and (y2 % 100 != 0 or y2 % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m2 - 1]
    return f"{y2:04d}-{m2:02d}-{last:02d}"


def _add_months(iso: str, months: int) -> str:
    """ISO + N months, clamped to the month end. Pure arithmetic; ``walk`` holds the twin and both are
    the ``_cw_first_of_months`` discipline -- this package reads no clock."""
    y, m, d = int(iso[0:4]), int(iso[5:7]), int(iso[8:10] or 1)
    total = (y * 12 + (m - 1)) + int(months)
    y2, m2 = total // 12, total % 12 + 1
    last = [31, 29 if (y2 % 4 == 0 and (y2 % 100 != 0 or y2 % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m2 - 1]
    return f"{y2:04d}-{m2:02d}-{min(d, last):02d}"


# ---------------------------------------------------------------------------------------------------
# 4.2 CANDIDATES -- crossings, so one episode yields ONE candidate
# ---------------------------------------------------------------------------------------------------
def crossings(hist: dict, *, convention: Optional[dict] = None, min_run: int = 1) -> list:
    """Every CROSSING on this series: the start of a run, or the first observation past a declared desk
    line. Returns ``[{index, date, kind, band}]`` oldest first.

    ONE CANDIDATE PER EPISODE, which is the whole reason the candidate is a crossing and not "every
    month the state was high" (Draft B): a twelve-month El Nino would otherwise contribute twelve
    near-identical candidates and crowd out every other episode in the pool.

    ``min_run`` IS THE RUN-START RULE AND IT IS A COMPARISON TO NOW, NEVER A THRESHOLD. A bare "start of
    a run" on a real monthly series fires every two or three months -- MEASURED at this landing as one
    hundred and ninety-five candidates on a four-hundred-and-forty-month ONI fixture, which is not "one
    episode, one candidate" by any reading. The rule that restores it without curating anything is the
    PRESENT STATE'S OWN run length: a past run counts as a candidate when it ran at least as long as the
    run the series is in NOW. That is a statement about likeness (the thing being selected for), not a
    number somebody chose, and it moves with the board rather than with a config."""
    values, dates = hist["values"], hist["dates"]
    out: list = []
    seen: set = set()

    def _add(i, kind, band=None):
        if i in seen or i <= 0 or i >= len(dates):
            return
        seen.add(i)
        out.append({"index": i, "date": dates[i], "kind": kind, "band": band})

    prev_sign = 0
    starts: list = []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        sign = 1 if d > 0 else (-1 if d < 0 else 0)
        if sign and sign != prev_sign:
            starts.append(i)
        if sign:
            prev_sign = sign
    floor = max(1, int(min_run))
    for j, i in enumerate(starts):
        end = (starts[j + 1] - 1) if j + 1 < len(starts) else (len(values) - 1)
        if (end - i + 1) >= floor:
            _add(i, "run_start")
    if convention:
        kind = str(convention.get("kind") or "")
        bands = [float(b) for b in (convention.get("bands") or [])]
        readings = (percentile_vector(hist) if kind == "percentile_bands" else values)
        for b in bands:
            was = None
            for i, v in enumerate(readings):
                if v is None:
                    continue
                now = _past_line(kind, float(v), b, bands)
                if was is False and now:
                    _add(i, "band_crossing", b)
                was = now
    out.sort(key=lambda c: c["index"])
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
# 4.2 LIKENESS -- an unweighted distance with a sign gate
# ---------------------------------------------------------------------------------------------------
def _ceil_half(n: int) -> int:
    return int(math.ceil(max(0, int(n)) / 2.0))


def likeness(candidate_date: str, dims: list) -> Optional[dict]:
    """``sum over dims |z_t - z_now| / |dims|`` with a SIGN-AGREEMENT GATE on at least half the
    dimensions (sec 4.2). ``None`` when the gate fails or no dimension is observable at ``t``.

    NO WEIGHTS AND NO SCALAR LOUDNESS SCORE (sec 14). Drafts A and D wanted ``1.0/40/3`` and ``2/25/4``
    weightings; a weight is a threshold with a smooth edge, and the whole engine's answer to "which
    driver matters" is that the writer decides, on figures the board prints.

    Each ``dims`` entry is ``{'id', 'hist', 'z_now'}``; a dimension whose z is missing at ``t`` (an
    honest hole) is skipped for the DISTANCE and counts against the gate's denominator, so a candidate
    observable on one dimension out of five cannot win on one number."""
    if not dims:
        return None
    gaps: list = []
    agree = 0
    seen = 0
    for dim in dims:
        hist = dim["hist"]
        i = _index_on_or_before(hist["dates"], candidate_date)
        z_t = None if i is None else hist["z"][i]
        z_now = dim.get("z_now")
        if z_t is None or z_now is None:
            continue
        seen += 1
        gaps.append(abs(float(z_t) - float(z_now)))
        if (float(z_t) >= 0) == (float(z_now) >= 0):
            agree += 1
    if not gaps or agree < _ceil_half(len(dims)):
        return None
    # THE DENOMINATOR IS ``|dims|``, WHICH IS SEC 4.2'S OWN (``sum over dims |z_t - z_now| / |dims|``).
    # Dividing by the OBSERVED count instead made a candidate observable on two of five dimensions
    # arithmetically closer than one observable on all five with the same total gap -- harmless under
    # :func:`select_analogs`, which additionally requires every dimension to be observable, and wrong
    # for any other caller. One rule, one denominator.
    return {"distance": sum(gaps) / float(len(dims)), "dims_seen": seen, "sign_agree": agree,
            "dims_declared": len(dims)}


def select_analogs(seed_hist: dict, *, dims: list, asof: str, band: LagBand, analog_k: int,
                   convention: Optional[dict] = None, min_separation_months: int = 12,
                   lag_days: int = 0, min_run: Optional[int] = None) -> dict:
    """THE SELECTION (sec 4.2). Returns ``{'picked', 'n_candidates', 'declined'}``.

    THE FILTERS, in order and each with its reason:
      * the candidate must be at least ``max_q`` quarters before the as-of, so its OUTCOME WINDOW HAS
        CLOSED -- a like state whose consequence has not happened yet is not evidence;
      * the candidate's own knowledge must have existed at ``t``: the prefix stops at ``t - lag_days``,
        which is why a crossing "at t" on a card published 43 days later is dated by when it was
        KNOWABLE;
      * the likeness gate of :func:`likeness`;
      * at least ``min_separation_months`` between two SELECTED dates, so one long episode does not
        occupy the whole stanza list.

    TIES BREAK BY RUN-LENGTH DIFFERENCE, THEN BY DATE DESCENDING -- recency ONLY inside an already-like
    pool (bar B9). A pool ordered by recency first would be a recency engine wearing a likeness name."""
    run_now = _run_at(seed_hist, len(seed_hist["values"]) - 1)
    cands = crossings(seed_hist, convention=convention,
                      min_run=(run_now if min_run is None else int(min_run)))
    if band.max_q is None:
        horizon = None
    else:
        horizon = int(band.max_q) * QUARTER_MONTHS
    closed: list = []
    for c in cands:
        if horizon is not None:
            far = _window_end(c["date"], horizon)
            if far > str(asof)[:10]:
                continue
        if lag_days:
            # A LABEL THIS AXIS CANNOT PLACE IS NOT ADMITTED. The filter's claim is "this crossing was
            # KNOWABLE at the as-of"; a date the calendar cannot read supports no such claim, and
            # admitting it would be the filter asserting what it could not check.
            knowable = _add_days(c["date"], int(lag_days))
            if knowable is None or knowable > str(asof)[:10]:
                continue
        closed.append(c)
    # "ALL DIMENSIONS OBSERVABLE AT t" IS ONE OF SEC 4.2'S OWN CANDIDATE FILTERS, and it is what makes
    # the header's coverage floor TRUE rather than decorative. MEASURED at this landing: the scenario-3
    # stanza printed "the series sat like this in May 2001" one line under "the loud set reaches back to
    # 2006" -- the sign gate needs only half the dimensions to AGREE, so a date before the newest
    # dimension's first observation could still be selected and the two sentences contradicted each
    # other. Observability is a different question from agreement and gets its own filter.
    scored: list = []
    observable = 0
    for c in closed:
        like = likeness(c["date"], dims)
        if like is None:
            continue
        if like["dims_seen"] < len(dims):
            continue
        observable += 1
        i = c["index"]
        run_t = _run_at(seed_hist, i)
        scored.append({**c, **like, "run_length": run_t})
    if not scored:
        return {"picked": (), "n_candidates": observable, "declined": "no_like_state"}
    scored.sort(key=lambda s: (round(s["distance"], 9), abs(s["run_length"] - run_now),
                               _desc_date(s["date"])))
    picked: list = []
    for s in scored:
        if len(picked) >= max(0, int(analog_k)):
            break
        if any(abs(_months_between(p["date"], s["date"])) < int(min_separation_months)
               for p in picked):
            continue
        picked.append(s)
    return {"picked": tuple(picked), "n_candidates": observable, "declined": None}


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


def _months_between(a: str, b: str) -> int:
    ay, am = int(str(a)[0:4]), int(str(a)[5:7])
    by, bm = int(str(b)[0:4]), int(str(b)[5:7])
    return (by * 12 + bm) - (ay * 12 + am)


def _run_at(hist: dict, i: int) -> int:
    """The run length ending at index ``i`` -- the tie-break input, computed on the same array."""
    vals = hist["values"]
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
def outcome_over_band(*, label: str, values, dates, t: str, band: LagBand, asof: str,
                      unit: str = "", table: str = "", metric: str = "", commodity=None,
                      country=None, key: str = "outcome") -> dict:
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
    if far_date > str(asof)[:10]:
        return {**base, "declined": "horizon_open", "decline_leg": "analog"}
    ds = [str(d) for d in (dates or [])]
    vs = [float(v) for v in (values or [])]
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
    values = [float(v) for v in (arrays.get("values") or [])]
    dates = [str(d) for d in (arrays.get("dates") or [])]
    hz = None if (band is None or band.max_q is None) else int(band.max_q) * QUARTER_MONTHS
    out: list = []
    for i, v in enumerate(values):
        if v == 0.0 or i >= len(dates):
            continue
        d = dates[i]
        if d >= str(asof)[:10]:
            continue
        if hz is not None and _window_end(d, hz) > str(asof)[:10]:
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
    all_dates = sorted({d for v in per.values() for d in v["hist"]["dates"] if d})
    hits: list = []
    for d in all_dates:
        if d >= str(bd.asof)[:10]:
            continue
        n = 0
        for v in per.values():
            i = _index_on_or_before(v["hist"]["dates"], d)
            p = None if i is None else percentile_vector(v["hist"])[i]
            if p is not None and float(p) >= float(decile):
                n += 1
        if n >= max(1, int(k)):
            hits.append({"date": d, "n_contracts": n})
    picked: list = []
    for h in sorted(hits, key=lambda x: _desc_date(x["date"])):
        if len(picked) >= max(0, int(analog_k)):
            break
        if any(abs(_months_between(p["date"], h["date"])) < 12 for p in picked):
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
    and needs no second semantics field carried onto the row to be read correctly here."""
    st = getattr(row, "state", None)
    if st is None:
        return 0
    rec = st.recency or {}
    for field in ("ym_publication_lag_days", "publication_lag_days"):
        try:
            v = int(rec.get(field) or 0)
        except (TypeError, ValueError):
            continue
        if v:
            return v
    return 0


# ---------------------------------------------------------------------------------------------------
# THE PRODUCER -- what the render is handed
# ---------------------------------------------------------------------------------------------------
def analog_rows(bd, *, knobs, benchmark_fn=None, receipt_fn=None, price_dims=(),
                conventions: Optional[dict] = None, lag_days_fn=None) -> list:
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
    and the empty list is the honest result."""
    if not knobs or int(knobs.analog_dims) <= 0 or int(knobs.analog_k) <= 0:
        return []
    conv_doc = _conventions() if conventions is None else conventions
    order = {key: i for i, key in enumerate(bd.order)}
    loud = sorted((r for r in bd.rows if r.legs.get("loud")),
                  key=lambda r: order.get(r.key, len(order)))
    numeric = [r for r in loud
               if r.state is not None and status_word(r.state.status) == "ok"
               and not r.context_only and (r.state.inputs or {}).get(r.state.key.label())]
    seeds = numeric[: int(knobs.analog_dims)]
    if not seeds:
        return []

    hists: dict = {}
    dims: list = []
    for r in seeds:
        # THE KNOWLEDGE AXIS IS THE CARD'S OWN (sec 4.1). `lag_days_fn` is the injected override the
        # walk uses where it knows the card's declared lag better than the row does; the default reads
        # it off the row the producer already filled.
        lag_r = int(lag_days_fn(r) if lag_days_fn else _lag_days_of(r))
        h = state_history(r.state, lag_days=lag_r,
                          want_pct=(str((conv_doc.get(r.state.key.ref) or {}).get("kind") or "")
                                    == "percentile_bands"))
        hists[r.key] = h
        z_now = None
        if r.state.z and not r.state.z.get("declined"):
            z_now = float(r.state.z["value"])
        dims.append({"id": r.driver_id, "hist": h, "z_now": z_now})
    dims.extend(_price_dimensions(price_dims))
    price_admitted = len(dims) - len(seeds)

    floor_year = _coverage_floor(seeds)
    out: list = []
    for r in seeds:
        band = r.lag_band
        conv = conv_doc.get(r.state.key.ref)
        lag_days = int(lag_days_fn(r) if lag_days_fn else _lag_days_of(r))
        sel = select_analogs(hists[r.key], dims=dims, asof=bd.asof, band=band,
                             analog_k=int(knobs.analog_k), convention=conv, lag_days=lag_days)
        seat = order.get(r.key, len(order))
        if sel["declined"]:
            out.append({"contract": r.contract, "driver_id": r.driver_id, "band": band,
                        "asof": bd.asof, "declined": sel["declined"], "seat": seat,
                        "n_candidates": sel["n_candidates"], "floor_year": floor_year,
                        "price_dims": price_admitted})
            continue
        for pick in sel["picked"]:
            out.append({
                "contract": r.contract, "driver_id": r.driver_id, "band": band, "asof": bd.asof,
                "date": pick["date"], "distance": pick["distance"], "kind": pick["kind"],
                "seat": seat,
                "n_candidates": sel["n_candidates"], "floor_year": floor_year,
                "price_dims": price_admitted, "declined": None,
                "outcomes": tuple(_outcomes_for(bd, r, pick["date"], benchmark_fn=benchmark_fn)),
                "receipts": tuple(_receipts_for(bd, r, pick["date"], receipt_fn=receipt_fn,
                                                cap=int(knobs.receipt_cap))),
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


def _price_dimensions(price_dims) -> list:
    """The ADMITTED price dimensions (D25): up to two, beside the driver rows and NEVER ranked against
    them. Each entry is ``{'id','values','dates','window'}`` and is turned into a state vector here on
    the same prefix arithmetic a driver row uses -- "last time the price sat here" is a candidate date
    like any other, and the likeness then asks whether the DRIVERS looked alike too."""
    out: list = []
    for pd in list(price_dims or ())[:2]:
        vals = [float(v) for v in (pd.get("values") or [])]
        ds = [str(d) for d in (pd.get("dates") or [])]
        if not vals:
            continue
        key = str(pd.get("id") or "price")
        bundle = {key: {"values": vals, "dates": ds}}
        win = int(pd.get("window") or min(len(vals), 60))
        res, _rec = TR.run_transform("rolling_zscore", bundle, key=key, params={"window": win})
        if res.get("declined"):
            continue
        series = list(res.get("series") or [])
        out.append({"id": key, "z_now": series[-1] if series else None,
                    "hist": {"dates": ds, "values": vals, "z": series,
                             "pct": [None] * len(vals), "window": win}})
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


def _outcomes_for(bd, seed_row, t: str, *, benchmark_fn=None) -> list:
    """The consequence rows for ONE like date: the seed's own CHILDREN on the anchor board, the FAR
    boards that carry the same driver (each over ITS OWN declared band), and the anchor's MONTHLY
    BENCHMARK. Every one is read over the PARENT'S band, and each row says whose band it used."""
    out: list = []
    for cid in (seed_row.children or ()):
        child = bd.row(seed_row.contract, cid)
        if child is None or child.state is None or status_word(child.state.status) != "ok":
            continue
        st = child.state
        arrays = (st.inputs or {}).get(st.key.label()) or {}
        out.append(outcome_over_band(
            label=f"{_label(cid)} on {_board(child.contract)}",
            values=arrays.get("values"), dates=arrays.get("dates"), t=t, band=seed_row.lag_band,
            asof=bd.asof, unit=st.narrate_unit or st.unit or "", table=st.table,
            metric=st.metric, commodity=st.key.commodity, country=st.key.country,
            key=st.key.label()))
    if benchmark_fn is not None:
        bm = benchmark_fn(seed_row.contract)
        if bm:
            out.append(outcome_over_band(
                label=bm.get("label") or f"the monthly benchmark for {_board(seed_row.contract)}",
                values=bm.get("values"), dates=bm.get("dates"), t=t, band=seed_row.lag_band,
                asof=bd.asof, unit=bm.get("unit") or "", table=bm.get("table") or "silver_pink_sheet",
                metric=bm.get("metric") or "", commodity=seed_row.contract, country=None,
                key="benchmark"))
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
    "the corpus holds no dated document for this window; the figures above stand on the series alone",
    which the render adds. There is no count floor anywhere here -- one mechanism-narrating receipt is
    enough, and frequency floors deny the tail."""
    if receipt_fn is None or cap <= 0:
        return []
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


def analog_leg(bd, rows) -> dict:
    """The ``analog`` leg's stamp (sec 6.7). ``not_reached`` when the tier runs no analogs at all --
    Scan's own case, and it is not a decline, because nothing was attempted and no reader is owed a
    sentence about a cut that never happened."""
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
