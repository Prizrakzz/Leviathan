"""Deterministic stats tool belt (W3.5) -- PURE descriptive functions over rows already fetched.

WHY THIS EXISTS
    The strip / all-numbers guard forbids the LLM from doing arithmetic: every served magnitude must
    value-check against an injected [N] row. So premium vocabulary -- "96th percentile", "third
    consecutive upward revision", a z-score -- is UNSERVABLE until a deterministic source computes it.
    This module is that source. It generalizes the rv2-fork pattern (compute deterministically, inject
    endpoint + baseline + delta as [N] rows) into an agent-callable surface: the model REQUESTS a
    computation by name and NARRATES the result; it never performs the math itself.

PIT SAFETY IS INHERITED, NEVER RE-ARGUED
    Every function here is pure over its argument sequences. It does NO I/O and NO fetching. The point-
    in-time correctness of the inputs was established when those rows passed the as-of guard at fetch
    time; a stat cannot re-open that question because it can never reach past its arguments. There is no
    filesystem, network, clock, or global state read anywhere in this module -- that structural fact is
    what makes the "PIT is inherited" claim true rather than aspirational.

THE FENCE -- DESCRIPTIVE HISTORY ONLY (enum-enforced)
    STAT_REGISTRY below is the EXHAUSTIVE whitelist and the tool-schema source. Any stat whose name
    matches BANNED_PATTERN (fit|trend|forecast|project|extrapolat|predict) is BANNED BY DESIGN: a
    regression / projection tool is R3's forbidden forward statement wearing a math costume. The
    integrator lints new names against BANNED_PATTERN and against STAT_REGISTRY's frozen key set; this
    module refuses at import time to register a banned name (see the assertion at the bottom).

HONEST DECLINES
    A statistic over too few points fakes precision. Each function declares a documented minimum n and
    returns a decline dict ({"declined": True, "value": None, "reason": ...}) rather than a number when
    the series is empty or too short -- e.g. a percentile over 3 points REFUSES. Minimums are the
    MIN_*_N module constants; they are part of the contract and are pinned by tests.

RETURN CONTRACT
    Success: {"stat": <name>, "declined": False, "value": <primary magnitude>, "n": <int>, ...params}
    Decline: {"stat": <name>, "declined": True,  "value": None,              "n": <int>, "reason": str}
    (extrema is the one shape exception: it carries "min"/"max" instead of a single "value", because it
    yields two magnitudes -- the integrator injects two [N] rows.)

THREE DELIBERATE EXCEPTIONS TO THE Sequence[float] SIGNATURE CONVENTION -- each named, none smuggled
    (1) D-FR-8 (FUTURES_READPATH wave). `unit_compatible()` and its decline builders below take two
    `str | None` unit labels, not a numeric series. That is a knowing departure from "every function here
    takes Sequence[float]". What it does NOT touch is the PURITY claim above: a two-string predicate reads
    no filesystem, no network, no clock and no global state, so "PIT is inherited" stays structurally
    true. The reason it lives HERE and not next to its one caller is AM-3's one-floor-family rule
    (MIN_QUANTILE_N below, and stats.py:53-56's "never a second, laxer constant declared next to the
    consumer"): the unit-compatibility POLICY is a refusal floor, and a second consumer must inherit it
    rather than fork it.
    (2) D-AM-17. `spread()` takes a second, PARALLEL sequence beside its numeric one -- the delivery-month
    LABEL axis -- because it is the only stat here whose two operands are selected BY NAME rather than by
    position. The labels stay strings and are never parsed into dates or ordered: this module holds no
    expiry vocabulary and no calendar. Purity is untouched for the same structural reason as (1).
    (3) RV-READING (2026-08-29). `pair_spread()` takes TWO parallel label axes -- one observation-date
    axis per leg -- because it is the only stat whose two operands come from TWO SEPARATE READS and must
    be joined by observation rather than by position. The labels stay strings and are never parsed into
    dates, never ordered by calendar and never differenced: the join is string equality, and
    chronological order is the CALLER's contract (oldest -> newest, exactly as `streak` requires). This
    module still holds no calendar. Purity is untouched for the same structural reason as (1) and (2).
    (4) RV-REGIONAL (2026-08-29). `rolling_corr()` takes the same two parallel label axes for the same
    join-by-observation reason as (3). Same rules: labels stay strings, never parsed, never ordered by
    calendar; chronological order is the CALLER's contract. Purity untouched.
"""
from __future__ import annotations

import math
import re
from typing import Callable, Sequence

# ---------------------------------------------------------------------------------------------------
# Documented minimum sample sizes (part of the contract; pinned by tests).
# ---------------------------------------------------------------------------------------------------
MIN_STREAK_N = 2          # need >=2 points to observe one period-over-period move
MIN_PERCENTILE_N = 8      # a rank over a handful of points is noise; refuse below this
MIN_ZSCORE_N = 8          # a std over a handful of points is unstable; refuse below this
MIN_WINDOW_CHANGE_N = 2   # need both endpoints
MIN_REVISION_N = 2        # need >=2 vintages to observe one revision
MIN_EXTREMA_N = 1         # a single point trivially is its own min and max
MIN_YOY_N = 2             # need the point `periods` back plus the latest
MIN_QUANTILE_N = MIN_PERCENTILE_N   # OUTCOMES_JOIN AM-3: ONE floor family. A spread over a handful of
#                                     firings fakes the same precision a rank over them does, so the
#                                     outcome join's coverage floor IS this module's refusal floor --
#                                     never a second, laxer constant declared next to the consumer.
MIN_SPREAD_N = MIN_WINDOW_CHANGE_N  # D-AM-17: the SAME floor family, not a second number. A calendar
#                                     spread is a two-ENDPOINT difference across the delivery-month axis
#                                     exactly as window_change is one across the time axis -- both need
#                                     both legs and neither needs a third point, so the constant is
#                                     inherited rather than re-declared one line laxer.
MIN_PAIR_SPREAD_N = MIN_SPREAD_N    # RV-READING (D2 resolution, 2026-08-29; review m4 amendment): the
#                                     CONSTRUCTOR's floor sits BELOW the rank floor -- so the
#                                     ordinal-when-thin rung is REACHABLE -- but at 2, not extrema's 1:
#                                     at a single joined observation the "highest", the "lowest" and the
#                                     latest are ONE number rendered three ways, an ordinal placement
#                                     with nothing to place against (review-reproduced). Two points is
#                                     the thinnest sample at which extrema SAYS anything, which is also
#                                     MIN_SPREAD_N's own two-endpoint logic -- inherited, never a second
#                                     number. The rank and sigma floors are NOT relaxed: percentile /
#                                     zscore keep refusing below 8 at their own call sites.

MIN_CORR_N = MIN_ZSCORE_N           # RV-REGIONAL (2026-08-29). ONE floor family: a correlation
#                                     estimates two means, two spreads AND a covariance, so it cannot
#                                     need FEWER points than a z-score. Floors the JOINED n.
MIN_CORR_WINDOW = MIN_CORR_N        # THE BINDING FLOOR (refute-v1 D9), and it floors the WINDOW LENGTH
#                                     -- the only quantity that decides whether an individual r is
#                                     noise. v1 floored the joined n and the window COUNT, so window=3
#                                     over 65 shared MYs passed every named floor and produced 63
#                                     windows of near-+/-1 noise, then ranked the latest against them.
#                                     The inheritance argument was right; it was applied to the wrong
#                                     variable. Same number, correct variable, a named declined branch.
MIN_CORR_WINDOWS = 1                # one full window is a reading; zero is nothing to read.
MIN_SU_HISTORY_N = MIN_PERCENTILE_N  # D-DA (2026-09-01, design v2 ROW 3). ONE floor family: a
#                                     stocks-to-use standing is a percentile of the leg's own
#                                     marketing-year history, so its history floor IS the rank floor --
#                                     inherited, never a second laxer constant beside the consumer.
MIN_SHARE_N = 1                     # D-DA ROW 9: a share is two parts of ONE observation (one session's
#                                     two crush values); the floor that matters is the parts' own signs,
#                                     policed inside share() itself, not a sample count.

DIRECTIONS = ("up", "down")

# BANNED BY DESIGN: forward-looking / model-fitting stat names. The integrator lints against this; the
# module also refuses to register any matching name (assertion at file end).
BANNED_PATTERN = re.compile(r"fit|trend|forecast|project|extrapolat|predict", re.IGNORECASE)


def is_banned_name(name: str) -> bool:
    """True if `name` is a forward-looking stat forbidden by the descriptive-only fence."""
    return bool(BANNED_PATTERN.search(name or ""))


# ---------------------------------------------------------------------------------------------------
# Internal helpers -- pure, no I/O.
# ---------------------------------------------------------------------------------------------------
def _floats(series: Sequence) -> list[float]:
    """Coerce a sequence to floats. Raises TypeError on any None / non-numeric cell: a stat operates on
    a clean numeric series (the integrator converts Athena's stringified cells before calling)."""
    out: list[float] = []
    for i, v in enumerate(series):
        if v is None or isinstance(v, bool):
            raise TypeError(f"series[{i}] is not numeric: {v!r}")
        try:
            f = float(v)
        except (TypeError, ValueError) as e:
            raise TypeError(f"series[{i}] is not numeric: {v!r}") from e
        if math.isnan(f) or math.isinf(f):
            raise TypeError(f"series[{i}] is not finite: {v!r}")
        out.append(f)
    return out


def _norm_direction(direction: str) -> str:
    d = (direction or "").strip().lower()
    if d not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    return d


def _decline(stat: str, n: int, reason: str, **params) -> dict:
    return {"stat": stat, "declined": True, "value": None, "n": n, "reason": reason, **params}


# ---------------------------------------------------------------------------------------------------
# UNIT COMPATIBILITY (U1 / D-FR-4..8) -- the two-string policy the agent's two-handle stats inherit.
#
# THE DEFECT IT REFUSES. `percentile`/`zscore` take a value from ONE handle and a history from ANOTHER.
# Nothing downstream ever compared their units, so a hard-red-SPRING quote in USD/bushel scored against a
# hard-red-WINTER history in US cents/bushel produced a cited [N] percentile off by a factor of 100 --
# silently, because _STAT_UNIT overwrites the OUTPUT unit to "percentile"/"sigma" before any renderer
# sees it. tables.yaml:970-972 forbids the only mechanism that would make such a comparison right
# ("NEVER FX-converted at ingest or at serving"), so REFUSING is the sole honest completion: this module
# NEVER maps, aliases or converts a unit. Normalization here is strip() + casefold() and nothing else.
#
# THE THREE-STATE RULE (D-FR-5), not an equality test:
#     known vs known, equal      -> COMPATIBLE   (byte-identical to pre-guard behaviour)
#     known vs known, different  -> INCOMPATIBLE (the measured defect)
#     known vs unknown (or "")   -> INCOMPATIBLE (one side proves a unit dimension is in play and the
#                                                 other cannot be shown compatible with it)
#     unknown vs unknown         -> COMPATIBLE   (no unit dimension in play at all -- ~17 of 19 cards
#                                                 declare no unit source, so fail-closed here would be a
#                                                 large unmeasured behaviour change shipped to fix a
#                                                 futures defect)
# A NAIVE EQUALITY TEST IS THE OTHER FAILURE: query.py:779 writes "" on an unresolvable commodity and the
# pattern-records mint hardcodes None, so `"" == ""` and `None == None` would read as compatible and pass
# two unrelated quantities.
#
# SCOPE IS `unit` ONLY THIS WAVE (D-FR-6), and the gap is named, not papered over: `currency` is present
# on every silver_futures_eod row but is NOT carried onto the stat handles. For that table the currency is
# embedded in the override string ("CNY/t" vs "US cents/lb"), so unit equality already catches every
# cross-currency case on the one table where the defect is live. KNOWN LIMITATION: a table that ever
# serves the SAME unit string under two currencies is uncovered until `currency` is lifted onto the four
# handle mint sites (deferred item X2).
#
# TWO CLASSES THIS POLICY STRUCTURALLY CANNOT REACH (D-FR-17; pinned as UNCOVERED, never described as
# closed): (i) a ONE-handle read over mixed-unit rows -- the caller only consults this on a two-handle
# stat, and a unit_col card's mixed rows are sampled from rows[0] alone; (ii) LEVEL vs DELTA -- a
# window_change handle inherits the RAW price unit, so ranking a +5c delta inside a distribution of ~430c
# levels is known == known and COMPUTES. Unit equality is the wrong instrument for (ii).
# ---------------------------------------------------------------------------------------------------
# The decline PROSE, declared as constants so it is registrable and linted rather than an ad-hoc f-string
# built at the call site (D-FR-14 exit (1)). The agent registers these in STAT_DECLINE_TEMPLATES; the
# config_check futures_lite census lints that dict the way it lints FUTURES_DECLINE_TEMPLATES. Every
# string must stay register_leaks / exec_leaks / valuation / flow clean under BOTH the fenced and outlook
# registers, survive sanitize() unchanged, and never call a futures value a "settle".
UNIT_MISMATCH_DECLINE = (
    "the two series are quoted in different units ({a} against {b}), and this lookup never converts "
    "between them -- a rank or z-score across them would compare two different quantities as if they "
    "were one, so no figure is computed")
# The asymmetric leg gets its OWN wording rather than rendering the missing side as "None": the guard
# established that one side cannot be SHOWN compatible, which is a weaker claim than "different units",
# and handing the model the stronger claim would be a false explanation it then narrates.
UNIT_UNKNOWN_DECLINE = (
    "one of the two series is quoted in {known} and the other carries no unit label at all, so they "
    "cannot be shown to be the same quantity, and this lookup never converts between units -- a rank or "
    "z-score across them could put two different quantities on one scale, so no figure is computed")
# EMPTINESS IS A DIFFERENT CONDITION AND IS CHECKED FIRST (see unit_decline's caller). A lookup that
# returned no rows mints unit=None, and a coverage-declined futures read is EXACTLY that shape -- on the
# very path this guard exists to fix. Under the three-state rule known-vs-unknown declines, so without
# the ordering an empty read would be narrated to the reader as a unit mismatch.
EMPTY_SERIES_DECLINE = (
    "the {which} came back with no rows at all, so there is nothing to compute over -- an empty read "
    "(a coverage gap in this lookup), so no figure is computed")
# RV-READING (2026-08-29): pair_spread's three refusal proses, declared as constants beside the family
# above for the same D-FR-14 reason (registrable and lintable, never an ad-hoc f-string). Each must stay
# register_leaks / exec_leaks / valuation / flow clean under BOTH registers and survive sanitize()
# unchanged. The first two are FIXTURE-ONLY under the current Pink-Sheet plumbing (see the guard-tag
# note below) -- kept because pair_spread is a general two-leg constructor and a future non-USD/mt
# source reaches them; dropped branches would fail OPEN there instead.
CURRENCY_MISMATCH_DECLINE = (
    "the two series are quoted in different currencies ({a} against {b}), and this lookup never converts "
    "between them -- both a difference and a ratio across them would carry an exchange rate this platform "
    "does not hold, so no figure is computed")
BOTH_UNITS_REQUIRED_DECLINE = (
    "neither series carries a unit label, so there is no way to tell whether they are the same quantity "
    "or two different ones -- this comparison needs both labels before it can be built, so no figure is "
    "computed")
NONPOSITIVE_DENOMINATOR_DECLINE = (
    "the second series prints a value of zero or less on {k} of the {n} shared observations (first on "
    "{when}), and a ratio across a sign change is not a relative price at all -- dropping those "
    "observations would quietly change the sample every later figure is measured against, so no figure "
    "is computed")
# RV-REGIONAL (2026-08-29): rolling_corr's three refusal proses, same D-FR-14 constant discipline.
CORR_SHORT_WINDOW_DECLINE = (
    "a window of {w} observations is below the {floor} a correlation needs to say anything -- a "
    "correlation over a handful of points swings between the extremes on noise alone, so no figure "
    "is computed")
CORR_FLAT_LEG_DECLINE = (
    "{which} prints the same figure across every one of the {n} shared observations, so it has no "
    "spread to correlate against -- a correlation needs both series to vary, so no figure is computed")
CORR_THIN_DECLINE = (
    "only {n} shared observations are held for these two series, below the {floor} a correlation "
    "needs, so no co-movement figure is computed")
# D-DA (2026-09-01): the derived-arithmetic lane's three refusal proses, same constant discipline.
VINTAGE_SKEW_DECLINE = (
    "the figures this derivation needs were published on different dates ({stamps}), and dividing or "
    "differencing across publication vintages manufactures a number no single release ever printed -- "
    "so no derived figure is computed")
RATIO_DENOMINATOR_DECLINE = (
    "the denominator prints {denom}, and a ratio over a zero-or-negative base is not a proportion of "
    "anything -- so no derived figure is computed")
SHARE_NONPOSITIVE_DECLINE = (
    "a value share needs every part non-negative and their sum positive (got part {part} against a "
    "total of {total}) -- so no derived figure is computed")

UNIT_UNLABELLED = "unlabelled"          # how an absent unit is rendered in a TRACE label, never in prose

# Guard tags stamped on the decline dict so the caller can tell the two conditions apart without matching
# on prose (the trace key rides the unit one ONLY -- an empty read is a coverage gap, not a unit event).
UNIT_GUARD = "unit_mismatch"
EMPTY_GUARD = "empty_series"
# D-AM-17 (S4). The third tag joins the SAME family so the caller keeps telling guards apart by tag rather
# than by prose. Its REASON string is NOT minted here: the shape vocabulary (`contract_month`, session
# aliases, the curve-vs-calendar discriminator) lives in query.py beside the code that mints those aliases,
# and copying it into a second home is what that module's own comment forbids. The caller renders the
# reason there and passes it in, which also keeps this module free of any query import.
CURVE_GUARD = "curve_as_calendar"
# RV-READING (2026-08-29). Three more tags in the SAME family, minted by `pair_spread` below so its
# caller (the cascade RV price reading) and the eval decline counters keep telling guards apart by TAG,
# never by prose. CURRENCY is the coarser axis than unit and is checked FIRST (see pair_spread's branch
# rationale); THIN is the constructor's own overlap floor; DENOMINATOR is the ratio form's zero-crossing
# refusal. Under the current Pink-Sheet plumbing (every leg USD/mt, no currency column) CURRENCY and
# DENOMINATOR are FIXTURE-ONLY -- reachable only through a future non-Pink-Sheet source -- and are
# declared as such (D1), never presented as live behaviour.
CURRENCY_GUARD = "currency_mismatch"
THIN_GUARD = "thin_history"
DENOMINATOR_GUARD = "denominator"
CORR_GUARD = "corr_undefined"       # RV-REGIONAL: rolling_corr's own refusals join the same family.


def _norm_unit(unit) -> str:
    """strip() + casefold(), and NOTHING else. Never a mapping, an alias table or a conversion: see 4.4 /
    tables.yaml:970-972. An absent unit and a blank unit normalize to the same empty string."""
    return (unit or "").strip().casefold()


def unit_compatible(a, b) -> bool:
    """The three-state rule over two `str | None` unit labels. True = the stat may compute.

    ACCEPTED COST, MEASURED AND RATIFIED (D-FR-16): the estate's unit VOCABULARY is not normalized across
    cards, so four dimensionally identical pairs are refused today -- `$/bu` vs `USD/bushel`, `c/lb` vs
    `US cents/lb`, `$/s.t.` vs `USD/short ton`, `$/cwt` vs `USD/cwt` (silver_wasde spellings against
    silver_futures_eod spellings). Those are FALSE declines and they are pinned as such. The fix, if it is
    ever taken, is one spelling per (currency, physical unit) in the CARD CONFIG under a lint -- never a
    runtime alias here."""
    na, nb = _norm_unit(a), _norm_unit(b)
    if not na and not nb:
        return True                     # no unit dimension in play at all
    if not na or not nb:
        return False                    # asymmetric: one side cannot be shown compatible with the other
    return na == nb


def unit_pair_label(a, b) -> str:
    """The two units as ONE trace-safe token. Raw (not normalized) -- a triager needs the spellings that
    were actually minted; an absent unit renders as the UNIT_UNLABELLED word, never as `None`."""
    return f"{a or UNIT_UNLABELLED} vs {b or UNIT_UNLABELLED}"


def unit_decline(stat: str, n: int, a, b) -> dict:
    """The unit-incompatibility refusal, on the SAME _decline contract every other floor in this module
    uses -- so it reaches the model as an honest `declined`, never as an `error` (a malformed call) and
    never as a raise. `n` is the SERIES handle's own length (the sample the stat WOULD have run over):
    this refusal is about the comparison, not about thinness, so `n` must never be read as a floor
    failure -- the reason string carries the cause."""
    known = a if _norm_unit(a) else b
    reason = (UNIT_MISMATCH_DECLINE.format(a=a, b=b) if (_norm_unit(a) and _norm_unit(b))
              else UNIT_UNKNOWN_DECLINE.format(known=known))
    return _decline(stat, n, reason, guard=UNIT_GUARD, units=unit_pair_label(a, b))


def empty_series_decline(stat: str, n: int, which: str) -> dict:
    """The EMPTY-read refusal, which outranks the unit check. `which` names the side that came back
    empty, in reader-facing words."""
    return _decline(stat, n, EMPTY_SERIES_DECLINE.format(which=which), guard=EMPTY_GUARD)


def curve_as_calendar_decline(stat: str, n: int, reason: str) -> dict:
    """S4's refusal on the SAME _decline contract as every other floor here, so an interleaved read reaches
    the model as an honest `declined` (no [N] row minted) rather than as an `error` or a raise. `reason` is
    rendered by the caller from the MEASURED shape -- see CURVE_GUARD above for why it is not built here."""
    return _decline(stat, n, reason, guard=CURVE_GUARD)


def _trailing_run(values: list[float], direction: str) -> int:
    """Count consecutive period-over-period moves in `direction` ending at the latest point. A zero
    change (flat) breaks the run; so does a move in the opposite direction."""
    run = 0
    for i in range(len(values) - 1, 0, -1):
        delta = values[i] - values[i - 1]
        if (direction == "up" and delta > 0) or (direction == "down" and delta < 0):
            run += 1
        else:
            break
    return run


# ---------------------------------------------------------------------------------------------------
# The stats. Each is pure and returns the documented contract dict.
# ---------------------------------------------------------------------------------------------------
def streak(series: Sequence, direction: str) -> dict:
    """Consecutive moves in `direction` ending at the latest observation. series is oldest -> newest."""
    vals = _floats(series)
    direction = _norm_direction(direction)
    n = len(vals)
    if n < MIN_STREAK_N:
        return _decline("streak", n, f"need >={MIN_STREAK_N} points, got {n}", direction=direction)
    run = _trailing_run(vals, direction)
    return {"stat": "streak", "declined": False, "value": run, "n": n,
            "direction": direction, "latest": vals[-1]}


def percentile(value, history: Sequence) -> dict:
    """Midrank percentile (0-100) of `value` within `history`: 100 * (n_below + 0.5*n_equal) / n.
    Order-independent. Refuses below MIN_PERCENTILE_N points."""
    hist = _floats(history)
    x = float(value)
    n = len(hist)
    if n < MIN_PERCENTILE_N:
        return _decline("percentile", n, f"need >={MIN_PERCENTILE_N} points, got {n}", x=x)
    below = sum(1 for h in hist if h < x)
    equal = sum(1 for h in hist if h == x)
    pct = 100.0 * (below + 0.5 * equal) / n
    return {"stat": "percentile", "declined": False, "value": pct, "n": n, "x": x}


def zscore(value, history: Sequence, window: int | None = None) -> dict:
    """Population z-score of `value` against the last `window` points of `history` (all of history when
    window is None). Refuses below MIN_ZSCORE_N points and on zero variance."""
    hist = _floats(history)
    x = float(value)
    if window is not None:
        if window < MIN_ZSCORE_N:
            return _decline("zscore", len(hist), f"window must be >={MIN_ZSCORE_N}, got {window}", x=x)
        if len(hist) < window:
            return _decline("zscore", len(hist),
                            f"history has {len(hist)} points, window needs {window}", x=x, window=window)
        hist = hist[-window:]
    n = len(hist)
    if n < MIN_ZSCORE_N:
        return _decline("zscore", n, f"need >={MIN_ZSCORE_N} points, got {n}", x=x)
    mean = sum(hist) / n
    var = sum((h - mean) ** 2 for h in hist) / n          # population variance (ddof=0)
    std = math.sqrt(var)
    if std == 0.0:
        return _decline("zscore", n, "zero variance in history", x=x, mean=mean, std=std)
    z = (x - mean) / std
    return {"stat": "zscore", "declined": False, "value": z, "n": n,
            "x": x, "window": window if window is not None else n, "mean": mean, "std": std}


def window_change(series: Sequence, t1: int, t2: int) -> dict:
    """Change in `series` between integer indices t1 and t2 (value = series[t2] - series[t1]). pct_change
    is None when the start value is zero. Refuses on empty series or out-of-range indices."""
    vals = _floats(series)
    n = len(vals)
    if n < MIN_WINDOW_CHANGE_N:
        return _decline("window_change", n, f"need >={MIN_WINDOW_CHANGE_N} points, got {n}", t1=t1, t2=t2)
    if not (-n <= t1 < n) or not (-n <= t2 < n):
        return _decline("window_change", n, f"index out of range for n={n}: t1={t1}, t2={t2}", t1=t1, t2=t2)
    start, end = vals[t1], vals[t2]
    delta = end - start
    pct = None if start == 0.0 else 100.0 * delta / start
    return {"stat": "window_change", "declined": False, "value": delta, "n": n,
            "start_val": start, "end_val": end, "pct_change": pct, "t1": t1, "t2": t2}


def ratio(numerator, denominator, *, scale: float = 1.0) -> dict:
    """One governed quotient (D-DA ROW 2: the stocks-to-use division the writer must never do).
    Declines on a zero-or-negative denominator (DENOMINATOR_GUARD) and ECHOES both inputs so the
    caller mints its component rows from the SAME floats it divided -- the derived level and its
    components can never drift apart."""
    num, den = float(numerator), float(denominator)
    for v in (num, den):
        if math.isnan(v) or math.isinf(v):
            raise TypeError(f"ratio input is not finite: {v!r}")
    if den <= 0.0:
        return _decline("ratio", 0, RATIO_DENOMINATOR_DECLINE.format(denom=den),
                        guard=DENOMINATOR_GUARD, numerator=num, denominator=den)
    return {"stat": "ratio", "declined": False, "value": scale * num / den, "n": 1,
            "numerator": num, "denominator": den, "scale": scale}


def share(part, other_parts: Sequence) -> dict:
    """`part` as a fraction of (part + sum(other_parts)), scaled to percent (D-DA ROW 9: the crush
    oil-share). Declines on a negative part or a non-positive total (SHARE_NONPOSITIVE_DECLINE) --
    a NEGATIVE crush MARGIN does not block the share (the share is bounded, the margin is not), but a
    negative product VALUE does. Returns the total beside the value so the caller's line can print
    both from one producer."""
    p = float(part)
    rest = _floats(other_parts)
    total = p + sum(rest)
    if p < 0.0 or any(r < 0.0 for r in rest) or total <= 0.0:
        return _decline("share", 1 + len(rest), SHARE_NONPOSITIVE_DECLINE.format(part=p, total=total),
                        guard=DENOMINATOR_GUARD, part=p, total=total)
    return {"stat": "share", "declined": False, "value": 100.0 * p / total, "n": 1 + len(rest),
            "part": p, "total": total}


def same_vintage(stamps: Sequence) -> tuple[bool, str | None]:
    """The D-DA vintage fence: EXACT knowledge-date STRING equality and nothing else. This module
    holds no calendar and must never learn one (labels are never parsed into dates), so a skew
    'tolerance' is not expressible here -- MAX_VINTAGE_SKEW = 0 is structural, not a discipline.
    FAIL-CLOSED: any empty or None stamp is a False, because a derivation over an unstamped input
    cannot prove its inputs share a release. Returns (ok, the shared stamp or None)."""
    ss = [str(s).strip() if s is not None else "" for s in (stamps or [])]
    if not ss or any(not s for s in ss):
        return (False, None)
    if len(set(ss)) != 1:
        return (False, None)
    return (True, ss[0])


def revision_count(vintage_rows: Sequence, direction: str) -> dict:
    """Consecutive revisions in `direction` across successive vintages of the SAME period. vintage_rows
    is the ordered list of published estimates (oldest vintage -> newest). Refuses below MIN_REVISION_N
    vintages."""
    vals = _floats(vintage_rows)
    direction = _norm_direction(direction)
    n = len(vals)
    if n < MIN_REVISION_N:
        return _decline("revision_count", n, f"need >={MIN_REVISION_N} vintages, got {n}", direction=direction)
    run = _trailing_run(vals, direction)
    return {"stat": "revision_count", "declined": False, "value": run, "n": n,
            "direction": direction, "latest": vals[-1]}


def extrema(series: Sequence) -> dict:
    """Min and max of `series` with first-occurrence indices. Shape exception: carries "min"/"max"
    instead of a single "value" (two magnitudes -> two injected rows). Refuses on empty series."""
    vals = _floats(series)
    n = len(vals)
    if n < MIN_EXTREMA_N:
        d = _decline("extrema", n, f"need >={MIN_EXTREMA_N} points, got {n}")
        d["min"] = None
        d["max"] = None
        return d
    lo = min(vals)
    hi = max(vals)
    return {"stat": "extrema", "declined": False, "value": None, "n": n,
            "min": lo, "max": hi, "argmin": vals.index(lo), "argmax": vals.index(hi)}


def yoy_delta(series: Sequence, periods: int = 1) -> dict:
    """Change between the latest value and the value `periods` observations back (year-over-year: 1 for
    an annual series, 12 for monthly). pct_change is None when the prior value is zero. Refuses when the
    series lacks the point `periods` back."""
    vals = _floats(series)
    n = len(vals)
    if periods < 1:
        return _decline("yoy_delta", n, f"periods must be >=1, got {periods}", periods=periods)
    if n < max(MIN_YOY_N, periods + 1):
        return _decline("yoy_delta", n, f"need >={periods + 1} points for periods={periods}, got {n}",
                        periods=periods)
    latest = vals[-1]
    prior = vals[-1 - periods]
    delta = latest - prior
    pct = None if prior == 0.0 else 100.0 * delta / prior
    return {"stat": "yoy_delta", "declined": False, "value": delta, "n": n,
            "latest": latest, "prior": prior, "pct_change": pct, "periods": periods}


def spread(series: Sequence, expiries: Sequence, near, far) -> dict:
    """D-AM-17. The CARRY / calendar spread between two NAMED delivery months of ONE curve read taken at a
    single as-of: value = series[far] - series[near] (positive = the deferred leg is dearer).

    `expiries` is the delivery-month LABEL axis, parallel to `series` -- index i of one is index i of the
    other. It exists because this is the one stat whose operands are chosen BY NAME, not by position; the
    caller builds both axes in a single pass so the two can never drift apart (a misaligned label would
    subtract the wrong two legs and say nothing).

    NEVER A FRONT-MONTH INFERENCE. The two legs are the ones the caller NAMED, and nothing here derives
    them. The per-expiry price table stores no front-month flag and publishes no open-interest metric, so
    "the front month" is not computable from these rows at all -- a nearest-listed-expiry tie-break wearing
    that name would be the quiet substitution the card's delivery-month doctrine refuses.

    EVERY FAILURE IS A REFUSAL, NEVER A RAISE, because each one is a real thing the model will ask for:
    a month absent from the read; a month on MORE than one row (the rows span several sessions, so this is
    not a curve at one as-of and "the" price of that expiry is not a single number); the same month twice;
    or rows carrying no delivery month at all (a cash reference, or a handle that is itself a derived
    figure). Each reason names what came back so the next call can be the right one."""
    vals = _floats(series)
    labels = [("" if e is None else str(e)).strip() for e in expiries]
    n = len(vals)
    a, b = ("" if near is None else str(near)).strip(), ("" if far is None else str(far)).strip()
    params = {"near": a, "far": b}
    if len(labels) != n:
        return _decline("spread", n, f"the delivery-month axis carries {len(labels)} labels for {n} "
                                     f"values, so a named month cannot be matched to a number", **params)
    if n < MIN_SPREAD_N:
        return _decline("spread", n, f"need >={MIN_SPREAD_N} rows (one per named delivery month), got {n}",
                        **params)
    if not a or not b:
        return _decline("spread", n, "both delivery months must be named -- there is no front-month "
                                     "contract in this lookup to infer one from", **params)
    if a == b:
        return _decline("spread", n, f"both legs name the same delivery month ({a}), which is a "
                                     f"difference of a figure against itself", **params)
    listed = sorted({m for m in labels if m})
    if not listed:
        return _decline("spread", n, "these rows carry no delivery month at all, so this is not a curve "
                                     "read and there are no two legs to difference", **params)
    missing = [m for m in (a, b) if m not in listed]
    if missing:
        return _decline("spread", n, f"{' and '.join(missing)} is not among the delivery months this read "
                                     f"returned ({', '.join(listed)})", **params)
    dupes = [m for m in (a, b) if labels.count(m) > 1]
    if dupes:
        return _decline("spread", n, f"{' and '.join(dupes)} appears on more than one row, so these rows "
                                     f"span several sessions rather than one as-of and each leg has no "
                                     f"single figure", **params)
    near_val, far_val = vals[labels.index(a)], vals[labels.index(b)]
    return {"stat": "spread", "declined": False, "value": far_val - near_val, "n": n,
            "near": a, "far": b, "near_val": near_val, "far_val": far_val}


def pair_spread(series_a: Sequence, dates_a: Sequence, unit_a, series_b: Sequence, dates_b: Sequence,
                unit_b, *, currency_a=None, currency_b=None,
                label_a: str = "the first series", label_b: str = "the second series") -> dict:
    """RV-READING (2026-08-29). The constructed CROSS-SERIES spread history: join two separately-read
    series by observation-date string equality (docstring exception (3)), then difference (units equal --
    the KC-Chi / gold_futures_spreads shape) or ratio (units differ, currencies compatible) each joined
    observation. Returns the WHOLE constructed history (`series`/`dates`, oldest -> newest in series_a's
    given order) so the caller can feed percentile/zscore/streak/extrema over it -- their floors are NOT
    relaxed here (MIN_PAIR_SPREAD_N note above).

    THE ZERO-CROSSING LAW rides the return dict, never the caller's head: a difference-form spread
    genuinely inverts (KC-Chi 2016 and 2023, per the gold_futures_spreads card: "NEVER a percent change
    on a spread -- it crosses zero"), so `pct_change_allowed` is False on a difference and True on a
    ratio of two positive prices (guard 10 enforces positivity).

    WHY THE RATIO IS HONEST WHERE IT IS: a ratio of two SAME-currency prices in different physical units
    carries an unrecoverable but constant positive conversion factor, and percentile / z-score / streak
    direction / percent change are all invariant to a positive constant scaling -- so every statistic the
    caller narrates is exactly the statistic of the true price ratio, though the LEVEL is unquotable
    (`unit: None`; the caller's narration law: never printed with a unit, never called a price). Across
    CURRENCIES that argument dies -- the ratio embeds an FX path this platform does not hold
    (tables.yaml's never-FX-converted law) -- so currency incompatibility REFUSES [CURRENCY_GUARD].

    BRANCH ORDER IS LOAD-BEARING: empty before units (the stats.py:173-179 ordering law -- an empty read
    mints unit=None and must never be narrated as a unit mismatch); currency before units (the coarser,
    PERMANENT blocker names itself rather than hiding behind a fixable spelling); the unit arm here is
    STRICTER than `unit_compatible`'s unknown-vs-unknown=True -- deliberately, and not a fork: that
    laxity has a measured installed-base rationale, while this stat's whole job is to CHOOSE between two
    forms, a choice it cannot make honestly on absent labels (no installed base to preserve).

    Under the current Pink-Sheet plumbing every reachable leg is USD/mt with no currency column, so the
    currency, both-units-absent, ratio and denominator branches are FIXTURE-ONLY today (D1) -- exercised
    by pins, reachable only through a future non-Pink-Sheet source. Every GUARDED failure is a refusal
    on the module's standard _decline contract; a non-numeric or non-finite CELL raises TypeError from
    `_floats` exactly as every other stat here does (the module's clean-series convention -- the caller's
    fail-closed belt owns that class, review m6)."""
    vals_a, vals_b = _floats(series_a), _floats(series_b)
    dl_a = [("" if d is None else str(d)).strip() for d in dates_a]
    dl_b = [("" if d is None else str(d)).strip() for d in dates_b]
    params = {"labels": f"{label_a} vs {label_b}", "units": unit_pair_label(unit_a, unit_b)}
    # 1. EMPTY, either leg -- outranks every unit/currency read (an empty read mints unit=None).
    for vals, which in ((vals_a, label_a), (vals_b, label_b)):
        if not vals:
            d = empty_series_decline("pair_spread", 0, which)
            d.update(params)
            return d
    # 2. AXIS LENGTH mismatch -- a caller-bug shape; a misaligned axis would join the wrong two figures.
    for vals, dl, which in ((vals_a, dl_a, label_a), (vals_b, dl_b, label_b)):
        if len(dl) != len(vals):
            return _decline("pair_spread", len(vals),
                            f"the observation axis of {which} carries {len(dl)} labels for {len(vals)} "
                            f"values, so an observation cannot be matched to a figure", **params)
    # 3. DUPLICATE date on either leg (mirrors spread()'s dupes: "the" figure of that date is not single).
    for dl, which in ((dl_a, label_a), (dl_b, label_b)):
        if len(set(dl)) != len(dl):
            dup = next(d for i, d in enumerate(dl) if d in dl[:i])
            return _decline("pair_spread", len(dl),
                            f"{dup or 'a blank date'} appears on more than one row of {which}, so that "
                            f"observation has no single figure on that leg", **params)
    # 4. SAME SERIES -- a difference of a figure against itself.
    if (label_a or "").strip() == (label_b or "").strip():
        return _decline("pair_spread", len(vals_a),
                        f"both legs name the same series ({label_a}), which is a difference of a figure "
                        f"against itself", **params)
    # 5. CURRENCY -- the coarser, permanent axis, checked before units. unit_compatible IS the policy
    #    (one three-state rule, two axes): None-vs-None reads compatible, which is correct where the
    #    currency lives inside the unit string (USD/mt), and FIXTURE-ONLY otherwise today.
    if not unit_compatible(currency_a, currency_b):
        return _decline("pair_spread", len(vals_a),
                        CURRENCY_MISMATCH_DECLINE.format(a=currency_a or UNIT_UNLABELLED,
                                                         b=currency_b or UNIT_UNLABELLED),
                        guard=CURRENCY_GUARD, **params)
    # 6. UNITS -- both must be KNOWN (stricter than unit_compatible, see docstring).
    known_a, known_b = bool(_norm_unit(unit_a)), bool(_norm_unit(unit_b))
    if not known_a and not known_b:
        return _decline("pair_spread", len(vals_a), BOTH_UNITS_REQUIRED_DECLINE, guard=UNIT_GUARD, **params)
    if known_a != known_b:
        d = unit_decline("pair_spread", len(vals_a), unit_a, unit_b)   # UNIT_UNKNOWN_DECLINE, verbatim reuse
        d.update(params)
        return d
    # 7. JOIN by date-string equality, preserving series_a's given order (chronology is the caller's
    #    contract; this module never orders by calendar).
    b_by = dict(zip(dl_b, vals_b))
    joined = [(d, va, b_by[d]) for d, va in zip(dl_a, vals_a) if d in b_by]
    n = len(joined)
    # 8. The constructor's own floor (MIN_PAIR_SPREAD_N -- the thinnest consumer's, so ordinal-thin lives).
    if n < MIN_PAIR_SPREAD_N:
        return _decline("pair_spread", n,
                        f"need >={MIN_PAIR_SPREAD_N} shared observations, got {n}",
                        guard=THIN_GUARD, **params)
    # 9. FORM.
    if unit_compatible(unit_a, unit_b):
        series = [va - vb for _, va, vb in joined]
        form, unit, pct_ok = "difference", unit_a, False
    else:
        # 10. RATIO ONLY: a non-positive denominator anywhere refuses the WHOLE stat, never a filter --
        #     dropping observations would quietly change the sample every later figure is measured against.
        bad = [(d, vb) for d, _, vb in joined if vb <= 0.0]
        if bad:
            return _decline("pair_spread", n,
                            NONPOSITIVE_DENOMINATOR_DECLINE.format(k=len(bad), n=n, when=bad[0][0]),
                            guard=DENOMINATOR_GUARD, **params)
        series = [va / vb for _, va, vb in joined]
        form, unit, pct_ok = "ratio", None, True
    return {"stat": "pair_spread", "declined": False, "value": series[-1], "n": n,
            "form": form, "unit": unit, "series": series, "dates": [d for d, _, _ in joined],
            "a_latest": joined[-1][1], "b_latest": joined[-1][2],
            "units": unit_pair_label(unit_a, unit_b), "pct_change_allowed": pct_ok}


def rolling_corr(series_a: Sequence, labels_a: Sequence, series_b: Sequence, labels_b: Sequence,
                 window: int, *, label_a: str = "the first series",
                 label_b: str = "the second series") -> dict:
    """RV-REGIONAL (2026-08-29). The trailing-window Pearson correlation between two separately-read
    series, joined by LABEL STRING EQUALITY (the pair_spread join -- docstring exception (4)).
    Chronological order is the CALLER's contract; this module holds no calendar.

    Returns the LATEST window's r as `value` PLUS the whole rolling series so the caller can rank it
    with `percentile` -- reuse, never a second ranking instrument -- AND `disjoint_series` /
    `disjoint_labels` (stride = `window`, anchored at the NEWEST observation): the honest rank basis,
    because overlapping trailing windows share window-1 observations with each neighbour and a rank
    over them evades MIN_PERCENTILE_N's own reason (refute-v1 D14).

    UNITS AND CURRENCIES DO NOT BAR A CORRELATION, and saying so is load-bearing rather than lax: a
    correlation is invariant to any positive affine rescaling of either leg, which is exactly the
    property a DIFFERENCE lacks -- that is why pair_spread refuses on currency and this does not.
    What a correlation across currencies IS NOT is a correlation of the two prices in one money: the
    caller must narrate each series in its OWN unit.

    BRANCH ORDER: empty -> axis-length -> duplicate labels -> same series -> WINDOW-LENGTH floor
    (MIN_CORR_WINDOW -- the binding floor, on the only quantity that decides whether an individual r
    is noise) -> join -> n floor (MIN_CORR_N) -> whole-series flatness -> per-window flatness. A
    window in which EITHER leg has zero variance yields no r: it is EXCLUDED from `series`/`labels`
    together (the two axes never desynchronise) and counted in `flat_windows`; if the LATEST window
    is flat the stat DECLINES rather than reporting an older window's r under a current label. Every
    GUARDED failure is a refusal on the module's standard _decline contract; a non-numeric cell
    raises TypeError from `_floats` (the clean-series convention)."""
    vals_a, vals_b = _floats(series_a), _floats(series_b)
    la = [("" if x is None else str(x)).strip() for x in labels_a]
    lb = [("" if x is None else str(x)).strip() for x in labels_b]
    w = int(window)
    params = {"labels": f"{label_a} vs {label_b}", "window": w}
    for vals, which in ((vals_a, label_a), (vals_b, label_b)):
        if not vals:
            d = empty_series_decline("rolling_corr", 0, which)
            d.update(params)
            return d
    for vals, lab, which in ((vals_a, la, label_a), (vals_b, lb, label_b)):
        if len(lab) != len(vals):
            return _decline("rolling_corr", len(vals),
                            f"the observation axis of {which} carries {len(lab)} labels for "
                            f"{len(vals)} values, so an observation cannot be matched to a figure",
                            **params)
    for lab, which in ((la, label_a), (lb, label_b)):
        if len(set(lab)) != len(lab):
            dup = next(x for i, x in enumerate(lab) if x in lab[:i])
            return _decline("rolling_corr", len(lab),
                            f"{dup or 'a blank label'} appears on more than one row of {which}, so "
                            f"that observation has no single figure on that leg", **params)
    if (label_a or "").strip() == (label_b or "").strip():
        return _decline("rolling_corr", len(vals_a),
                        f"both legs name the same series ({label_a}), which would correlate a series "
                        f"with itself", **params)
    if w < MIN_CORR_WINDOW:
        return _decline("rolling_corr", len(vals_a),
                        CORR_SHORT_WINDOW_DECLINE.format(w=w, floor=MIN_CORR_WINDOW),
                        guard=CORR_GUARD, **params)
    b_by = dict(zip(lb, vals_b))
    joined = [(x, va, b_by[x]) for x, va in zip(la, vals_a) if x in b_by]
    n = len(joined)
    if n < MIN_CORR_N:
        return _decline("rolling_corr", n, CORR_THIN_DECLINE.format(n=n, floor=MIN_CORR_N),
                        guard=CORR_GUARD, **params)
    ja = [v for _, v, _ in joined]
    jb = [v for _, _, v in joined]
    for vals, which in ((ja, label_a), (jb, label_b)):
        if max(vals) == min(vals):
            return _decline("rolling_corr", n, CORR_FLAT_LEG_DECLINE.format(which=which, n=n),
                            guard=CORR_GUARD, **params)

    def _r(sa: list, sb: list) -> float | None:
        m = len(sa)
        ma_, mb_ = sum(sa) / m, sum(sb) / m
        va_ = sum((x - ma_) ** 2 for x in sa)
        vb_ = sum((x - mb_) ** 2 for x in sb)
        if va_ == 0.0 or vb_ == 0.0:
            return None                                            # a flat window has no r
        cov = sum((x - ma_) * (y - mb_) for x, y in zip(sa, sb))
        return cov / math.sqrt(va_ * vb_)

    rs: list = []
    r_labels: list = []
    flat = 0
    for end in range(w - 1, n):
        r = _r(ja[end - w + 1:end + 1], jb[end - w + 1:end + 1])
        if r is None:
            flat += 1
            continue
        rs.append(r)
        r_labels.append(joined[end][0])
    if not rs or r_labels[-1] != joined[-1][0]:
        # the latest window is flat (or every window is): an older r under a current label is a lie
        return _decline("rolling_corr", n,
                        CORR_FLAT_LEG_DECLINE.format(which=f"{label_a} or {label_b}", n=w),
                        guard=CORR_GUARD, flat_windows=flat, **params)
    dis: list = []
    dis_labels: list = []
    end = n - 1
    while end - w + 1 >= 0:
        r = _r(ja[end - w + 1:end + 1], jb[end - w + 1:end + 1])
        if r is not None:
            dis.append(r)
            dis_labels.append(joined[end][0])
        end -= w
    dis.reverse()
    dis_labels.reverse()
    return {"stat": "rolling_corr", "declined": False, "value": rs[-1], "n": n, "window": w,
            "series": rs, "labels": r_labels, "windows": len(rs), "flat_windows": flat,
            "disjoint_series": dis, "disjoint_labels": dis_labels}


def quantiles(series: Sequence, probs: Sequence = (0.5,)) -> dict:
    """Linear-interpolated quantiles of `series` (order-independent). OUTCOMES_JOIN AM-3: the outcome
    join's distributions are DESCRIPTIVE spreads over already-fetched, PIT-clamped rows, and every one
    of them computes here rather than in a caller -- one calculator, one floor family.

    REFUSES below MIN_QUANTILE_N, which is MIN_PERCENTILE_N by definition and not a second number: a
    spread over a handful of firings fakes exactly the precision a rank over the same points fakes.

    DELIBERATELY ABSENT FROM STAT_REGISTRY. That registry is the AGENT TOOL ENUM; this is an ENGINE
    calculator on a deterministic scored path. New agent-callable stats are gated by their own doctrine
    review (AM-3), so widening the enum is never a side effect of adding an engine function. `probs` are
    fractions in [0, 1]; `value` carries the FIRST requested probability so the standard
    {"value": ...} contract still holds, and the full map rides in "quantiles"."""
    vals = _floats(series)
    n = len(vals)
    ps = [float(p) for p in probs]
    if not ps:
        return _decline("quantiles", n, "no probabilities requested", probs=[])
    bad = [p for p in ps if not 0.0 <= p <= 1.0]
    if bad:
        return _decline("quantiles", n, f"probabilities must be in [0, 1], got {bad}", probs=ps)
    if n < MIN_QUANTILE_N:
        return _decline("quantiles", n, f"need >={MIN_QUANTILE_N} points, got {n}", probs=ps)
    ordered = sorted(vals)
    out: dict[str, float] = {}
    for p in ps:
        pos = p * (n - 1)
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        out[f"{p:g}"] = ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)
    return {"stat": "quantiles", "declined": False, "value": out[f"{ps[0]:g}"], "n": n,
            "quantiles": out, "probs": ps}


def sign_agreement(parent_move, child_move, edge_sign) -> dict:
    """CASCADE EPISODE WALK (charter STEP 3): the three-valued verdict on ONE declared hop over ONE
    shared firing window -- 'aligned' when sign(child) == sign(parent) * edge_sign, 'at_odds' when
    exactly opposite, 'undetermined' otherwise. PURE: two floats and a declared sign in, one word
    out. No calendar, no labels, no counts, no thresholds -- the fences that decide WHETHER a pair
    may be compared (currency, realized-interval, tenor, unanimity) live at the seam and must run
    BEFORE this; a pair that fails them never reaches here, so 'undetermined' from THIS function
    means only: the edge declines to declare ('0'/None/non-unanimous handled upstream as sign None)
    or a leg's move is exactly zero.

    DELIBERATELY ABSENT FROM STAT_REGISTRY. That registry is the AGENT TOOL ENUM; this is an ENGINE
    calculator on a deterministic scored path. New agent-callable stats are gated by their own
    doctrine review (AM-3), so widening the enum is never a side effect of adding an engine
    function. RETURN CONTRACT: the standard {"stat", "declined", "value"} shape -- `value` is the
    verdict WORD (the rendered token), never a number, so no copy surface can mistake it for a
    magnitude."""
    try:
        p = float(parent_move)
        c = float(child_move)
    except (TypeError, ValueError):
        return {"stat": "sign_agreement", "declined": False, "value": "undetermined"}
    es = {"+": 1, "-": -1}.get(str(edge_sign or "").strip())
    sp = (p > 0) - (p < 0)
    sc = (c > 0) - (c < 0)
    if es is None or sp == 0 or sc == 0:
        return {"stat": "sign_agreement", "declined": False, "value": "undetermined"}
    return {"stat": "sign_agreement", "declined": False,
            "value": ("aligned" if sc == sp * es else "at_odds")}


# ---------------------------------------------------------------------------------------------------
# ENUM-LOCKED registry -- the tool-schema source. Keys are the frozen public stat names.
# ---------------------------------------------------------------------------------------------------
STAT_REGISTRY: dict[str, Callable[..., dict]] = {
    "streak": streak,
    "percentile": percentile,
    "zscore": zscore,
    "window_change": window_change,
    "revision_count": revision_count,
    "extrema": extrema,
    "yoy_delta": yoy_delta,
    "spread": spread,          # D-AM-17: the one CURVE-axis stat; its two legs are NAMED, never inferred
}

STAT_NAMES = frozenset(STAT_REGISTRY)

# Defensive fence: no registered name may be a forward-looking stat. If this ever fires, someone tried
# to smuggle a projection tool through the descriptive-only surface.
for _name in STAT_REGISTRY:
    assert not is_banned_name(_name), f"banned forward-looking stat name registered: {_name!r}"
del _name
