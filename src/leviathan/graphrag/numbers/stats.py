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

TWO DELIBERATE EXCEPTIONS TO THE Sequence[float] SIGNATURE CONVENTION -- both named, neither smuggled
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
