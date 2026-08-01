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
}

STAT_NAMES = frozenset(STAT_REGISTRY)

# Defensive fence: no registered name may be a forward-looking stat. If this ever fires, someone tried
# to smuggle a projection tool through the descriptive-only surface.
for _name in STAT_REGISTRY:
    assert not is_banned_name(_name), f"banned forward-looking stat name registered: {_name!r}"
del _name
