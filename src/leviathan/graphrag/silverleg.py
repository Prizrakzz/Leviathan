"""Silver leg v1 — OBSERVED driver state for regime firing (GRAPHRAG_PLAN F4 / section 6 step 8).

Until now regimes fired on a text proxy: "a dated document MENTIONS the driver near the as-of." This
module gives `ground()` a real `silver_lookup(contract, driver_id, asof)` so a driver's state can be
OBSERVED (an anomalous silver value at the as-of vintage), merely DOCUMENTED (text only), or
CONTRADICTED (silver is live and plainly normal -> the driver must NOT fire the regime, whatever the
documents chatter about). Mechanism meets magnitude.

Scope v1 (deliberately narrow — refs the numbers layer serves TODAY, leakage-safe by construction via
numbers.query.build_sql's as-of guards):
  * psd_ending_stock_su_ratio / ending_stocks_su_ratio — ending_stocks/consumption at the PSD release
    vintage visible at asof, z-scored against the prior marketing years AT THAT SAME VINTAGE.
  * fred_fx_macro — origin-currency level z vs its trailing window (BRL default; CNY for DCE/ZCE
    contracts).
  * oni_climate — the ONI anomaly at asof (absolute-band semantics, the meteorological +-0.5).
More driver coverage (heat_stress, drought/precip, positioning) comes from z-scores computed IN SQL
over SILVER SOURCE TABLES (nasa_power, chirps, cot) — the same pattern as _fx below. NEVER read
gold.feature_spine here: the feature layer belongs to the deferred MLOps track (user decision
2026-07-04), and this leg must stay decoupled from it. A ref this module can't serve returns
{live: False} and the DOCUMENTED text semantics stand unchanged.

Verdicts (thresholds in params.yaml serving.silver.thresholds): |z| >= z_thr -> "observed" (fires,
quantitative receipt); |z| <= veto fraction of z_thr -> "normal" (VETOES the driver); in between ->
"inconclusive" (text semantics decide). Every failure -> {live: False}: silver can never break an
answer. Lookups are memoized per (ref, contract, asof) and capped per answer.
"""
from __future__ import annotations

import datetime as _dt

from leviathan.graphrag import params as _pr

_ALIAS = {"ending_stocks_su_ratio": "psd_ending_stock_su_ratio"}
_VETO_FRACTION = 0.5                                   # |z| below this fraction of z_thr = plainly normal


def _thr(ref: str, key: str, default):
    return _pr.get(f"serving.silver.thresholds.{ref}.{key}", default)


def _verdict_z(z: float, z_thr: float) -> str:
    if abs(z) >= z_thr:
        return "observed"
    if abs(z) <= _VETO_FRACTION * z_thr:
        return "normal"
    return "inconclusive"


# ── T1 graded firing (CONVERGENCE_TIER1): the intensity band, derived at the make_silver_lookup seam ──
# NOT at _verdict_z ([SKEPTIC F2]): _oni INLINES its verdict and never calls _verdict_z, so a _verdict_z
# edit would miss ONI entirely. All three handlers flow through make_silver_lookup.lookup, so the band is
# derived THERE, from the z the handler already returned. Intensity is a LABEL on an already-observed
# driver -- it never enters graph.regimes(), so fired/n_active/threshold/proximity are untouched.
# ONI's meteorological |anomaly| boundaries (its `z` is the RAW anomaly, not a sigma -- NEVER band it as
# sigma multiples of the 0.5 threshold). NOAA's 'weak' renders as 'elevated' (an observed driver is never
# 'weak'); 'very strong' renders as 'extreme'. Vocabulary is the register-fence-safe set only.
_ONI_INTENSITY_BANDS = ((2.0, "extreme"), (1.5, "strong"), (1.0, "moderate"), (0.5, "elevated"))


def _intensity(ref: str, z, z_thr) -> str | None:
    """The T1 band for one silver verdict, or None (=> the caller attaches NO key -- absent, not null,
    per [SKEPTIC F1]). su_ratio/fx scale |z| to that ref's OWN z_thr: [z_thr,2*z_thr)=moderate,
    [2*z_thr,3*z_thr)=strong, >=3*z_thr=extreme (an observed driver has |z|>=z_thr, so moderate is the
    floor); oni_climate bands the RAW |anomaly| on 0.5/1.0/1.5/2.0."""
    try:
        a = abs(float(z))
    except (TypeError, ValueError):
        return None
    if ref == "oni_climate":
        for thr, label in _ONI_INTENSITY_BANDS:
            if a >= thr:
                return label
        return None
    try:
        t = float(z_thr)
    except (TypeError, ValueError):
        return None
    if t <= 0 or a < t:
        return None                                    # sub-threshold (normal/inconclusive): unbanded
    if a >= 3 * t:
        return "extreme"
    if a >= 2 * t:
        return "strong"
    return "moderate"


def _z(latest: float, history: list[float]) -> float | None:
    if len(history) < 5:
        return None                                    # too little history to call anything anomalous
    mean = sum(history) / len(history)
    var = sum((x - mean) ** 2 for x in history) / max(1, len(history) - 1)
    if var <= 0:
        return None
    return (latest - mean) / var ** 0.5


def _rows(query_fn, table: str, metric: str, asof: str, *, commodity=None, country=None, agg="series",
          period_start=None, limit=400) -> list[dict]:
    """One PIT-safe read for the firing legs.

    FUTURES_READPATH S1 canary (D-FR-10): UNFLAGGED BY DESIGN, and named here so it reads as a decision
    rather than as a site the threading wave missed. `table` looks caller-supplied but this module has
    exactly THREE callers and each passes a LITERAL -- silver_psd (_su_ratio, twice), silver_fred_fx
    (_fx) and silver_noaa_oni (_oni). None of those cards declares `contract_month_col`, and
    `query._newest_first_applies` keys on exactly that, so the canary could not change one byte of the
    SQL compiled here. Threading it would add a parameter to a firing-leg helper that can never use it.
    Pinned in tests/unit/test_futures_readpath_pins.py: if a fourth caller ever hands this a futures
    card, that pin reds and the kwarg becomes required."""
    from leviathan.graphrag.numbers import query as Q
    spec = Q.NumberQuery(table=table, metric=metric, asof=asof, commodity=commodity, country=country,
                         agg=agg, period_start=period_start, limit=limit)
    return Q.run(spec, query_fn=query_fn)


def _primary_country(contract: str) -> str | None:
    """The contract's primary balance-sheet country (geographies config) — without it a PSD series
    mixes countries per marketing year and the 'latest value' is whichever row happened to come last
    (the bug the 2012-corn live check caught: 0.208 'S/U' that was not any one country's ratio)."""
    try:
        from leviathan.graphrag.numbers import query as Q
        prim = Q._geo(contract).get("_primary")
        return prim[0] if prim else None
    except Exception:  # noqa: BLE001
        return None


def _num(v):
    try:
        f = float(str(v).replace(",", ""))
        return f
    except (TypeError, ValueError):
        return None


def _kd(row: dict) -> str:
    return str(row.get("knowledge_date") or row.get("data_date") or "")[:10]


def _su_ratio(query_fn, contract: str, asof: str) -> dict:
    country = _primary_country(contract)
    if country:                                        # geo gives snake_case; silver_psd stores 'United States'
        country = country.replace("_", " ").title()
    stocks = _rows(query_fn, "silver_psd", "ending_stocks_mt", asof, commodity=contract, country=country)
    cons = _rows(query_fn, "silver_psd", "consumption_mt", asof, commodity=contract, country=country)

    def _by_period(rows):
        out = {}
        for r in rows:
            p = str(r.get("period") or r.get("marketing_year") or "")
            v = _num(r.get("value"))
            if p and v:
                out[p] = (v, _kd(r))
        return out
    s, c = _by_period(stocks), _by_period(cons)
    ratios = {p: (s[p][0] / c[p][0], s[p][1]) for p in s if p in c and c[p][0]}
    if len(ratios) < 6:
        return {"live": False, "reason": "thin_history"}
    window = int(_thr("psd_ending_stock_su_ratio", "window_years", 10))
    recent = sorted(ratios)[-(window + 1):]                        # the regime z is vs the RECENT decade,
    latest_p = recent[-1]                                          # not 50 years of secular level shift
    latest, kd = ratios[latest_p]
    hist = [ratios[p][0] for p in recent[:-1]]
    z = _z(latest, hist)
    if z is None:
        return {"live": False, "reason": "no_z"}
    z_thr = float(_thr("psd_ending_stock_su_ratio", "z", 1.0))
    return {"live": True, "value": round(latest, 4), "unit": "S/U ratio", "z": round(z, 2),
            "threshold": z_thr, "verdict": _verdict_z(z, z_thr), "knowledge_date": kd,
            "detail": f"{country or 'unspecified country'} MY{latest_p} vs {len(hist)} prior years at the same vintage"}


def _fx(query_fn, contract: str, asof: str) -> dict:
    metric = "cny_usd" if contract.endswith(("_dce", "_zce")) else "brl_usd"
    window_days = int(_thr("fred_fx_macro", "window_days", 504))
    start = (_dt.date.fromisoformat(asof[:10]) - _dt.timedelta(days=window_days)).isoformat()
    rows = _rows(query_fn, "silver_fred_fx", metric, asof, period_start=start, limit=800)
    vals = [( _kd(r), _num(r.get("value"))) for r in rows]
    vals = sorted((d, v) for d, v in vals if v)
    if len(vals) < 60:
        return {"live": False, "reason": "thin_history"}
    kd, latest = vals[-1]
    z = _z(latest, [v for _, v in vals[:-1]])
    if z is None:
        return {"live": False, "reason": "no_z"}
    z_thr = float(_thr("fred_fx_macro", "z", 1.5))
    return {"live": True, "value": round(latest, 4), "unit": metric.upper(), "z": round(z, 2),
            "threshold": z_thr, "verdict": _verdict_z(z, z_thr), "knowledge_date": kd,
            "detail": f"vs trailing {window_days}d"}


def _oni(query_fn, contract: str, asof: str) -> dict:
    rows = _rows(query_fn, "silver_noaa_oni", "oni_anom", asof, agg="latest", limit=5)
    if not rows:
        return {"live": False, "reason": "no_rows"}
    v = _num(rows[0].get("value"))
    if v is None:
        return {"live": False, "reason": "null_value"}
    band = float(_thr("oni_climate", "band", 0.5))
    verdict = "observed" if abs(v) >= band else ("normal" if abs(v) <= _VETO_FRACTION * band else "inconclusive")
    return {"live": True, "value": v, "unit": "ONI", "z": v, "threshold": band, "verdict": verdict,
            "knowledge_date": _kd(rows[0]), "detail": "El Nino >= +0.5, La Nina <= -0.5"}


_HANDLERS = {"psd_ending_stock_su_ratio": _su_ratio, "fred_fx_macro": _fx, "oni_climate": _oni}


def servable_refs() -> set[str]:
    return set(_HANDLERS) | set(_ALIAS)


# ── shared vintage cache (cross-turn, default OFF — enable via GRAPHRAG_SILVER_CACHE at deploy) ──────
# The per-turn memo below re-pays every Athena read (~3.5s each, sequential) on EVERY turn — measured as
# the walk's dominant remaining cost (~14s "rest") after the rerank fix. PIT-safety makes caching trivial:
# a HISTORICAL asof reads immutable vintage data -> cache FOREVER; a live/today asof gets a short TTL.
_SHARED: dict[tuple, tuple[dict, float | None]] = {}     # key -> (result, expires_at | None=immortal)
_SHARED_LOCK = None


def _shared_enabled() -> bool:
    import os
    v = os.environ.get("GRAPHRAG_SILVER_CACHE") or str(_pr.get("serving.silver.shared_cache", ""))
    return v.strip().lower() in ("1", "on", "true", "yes")


def _shared_lock():
    global _SHARED_LOCK
    if _SHARED_LOCK is None:
        import threading
        _SHARED_LOCK = threading.Lock()
    return _SHARED_LOCK


def _shared_get(key: tuple):
    if not _shared_enabled():
        return None
    import time
    with _shared_lock():
        hit = _SHARED.get(key)
    if not hit:
        return None
    val, exp = hit
    if exp is not None and time.time() > exp:
        return None
    return val


def _shared_put(key: tuple, out: dict, asof_s: str) -> None:
    if not _shared_enabled():
        return
    import datetime as _dt
    import time
    immortal = bool(asof_s) and asof_s < _dt.date.today().isoformat()   # vintage data is immutable
    exp = None if immortal else time.time() + float(_pr.get("serving.silver.cache_ttl", 900))
    with _shared_lock():
        _SHARED[key] = (out, exp)


def make_silver_lookup(graph, query_fn=None, *, cap: int | None = None, intensity: bool = False):
    """Build the `silver_lookup(contract, driver_id, asof)` callable ground() accepts. Memoized per
    (ref, contract-or-global, asof); at most `cap` silver reads per answer; failures -> {live: False}.
    THREAD-SAFE with single-flight: ground() now prefetches lookups in parallel, so concurrent callers of
    the same key wait for one handler run instead of double-spending the budget on duplicate Athena reads.

    `intensity` (T1, default OFF): attach the graded band as a CONDITIONALLY-ATTACHED key on banded results
    ([SKEPTIC F1] -- never a declared pydantic field, never null; absent when off / no-z / sub-threshold).
    The flag is READ at the answer.py/server seam and threaded HERE as a kwarg (the GRAPHRAG_COMOVE idiom --
    no os.environ read in this module). The memo/shared caches store the RAW handler output, so a shared
    cross-turn cache entry can never leak a band into a flag-off factory."""
    import threading
    cap = cap if cap is not None else int(_pr.get("serving.silver.cap", 8))
    memo: dict[tuple, dict] = {}
    budget = {"left": cap}
    lk = threading.Lock()
    inflight: dict[tuple, threading.Event] = {}

    def _deco(out: dict, ref: str) -> dict:
        """The returned view of a cached/fresh handler result: ref stamped; intensity ONLY when the flag
        is on AND the band derives (flag off => key ABSENT => model_dump() bytes provably unchanged)."""
        res = {**out, "ref": ref}
        if intensity:
            band = _intensity(ref, out.get("z"), out.get("threshold"))
            if band is not None:
                res["intensity"] = band
        return res

    def lookup(contract: str, driver_id: str, asof) -> dict:
        try:
            asof_s = str(asof or "")[:10]
            c = graph.contracts.get(contract)
            drv = next((d for d in (c.drivers if c else []) if d.id == driver_id), None)
            ref = _ALIAS.get(getattr(drv, "silver_ref", None) or "", getattr(drv, "silver_ref", None) or "")
            if not asof_s or drv is None or getattr(drv, "silver_status", "") != "available" \
                    or ref not in _HANDLERS:
                return {"live": False, "ref": ref or None}
            scope = contract if ref == "psd_ending_stock_su_ratio" else (
                contract if ref == "fred_fx_macro" else "_global")
            key = (ref, scope, asof_s)
            while True:
                with lk:
                    if key in memo:
                        return _deco(memo[key], ref)
                    shared = _shared_get(key)
                    if shared is not None:                     # cross-turn hit: no budget, no Athena
                        memo[key] = shared
                        return _deco(shared, ref)
                    ev_wait = inflight.get(key)
                    if ev_wait is None:
                        if budget["left"] <= 0:
                            return {"live": False, "ref": ref, "reason": "capped"}
                        budget["left"] -= 1
                        inflight[key] = threading.Event()
                        break                                  # this caller runs the handler
                ev_wait.wait(timeout=60)                       # another caller is running it — wait + re-check
            try:
                out = _HANDLERS[ref](query_fn, contract, asof_s)
                with lk:
                    memo[key] = out
                _shared_put(key, out, asof_s)
                return _deco(out, ref)
            finally:
                # ALWAYS release waiters — on handler failure they re-loop and one retries (budget-bounded).
                with lk:
                    e = inflight.pop(key, None)
                if e is not None:
                    e.set()
        except Exception:  # noqa: BLE001 — a silver miss must never break the answer
            return {"live": False, "ref": None, "reason": "error"}
    return lookup
