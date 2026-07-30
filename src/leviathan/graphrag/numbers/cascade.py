"""Deterministic quantified-cascade lookups (Phase 9-B).

When the L2 walk grounds a reasoning turn, this module fetches the relevant silver metric in the analogue-era
window (as-known THEN) AND at the session as-of, so the mentor can narrate the record with CITABLE [N] rows.
All SQL rides numbers.query.NumberQuery + build_sql -> it inherits the unconditional as-of guard AND the
sargable-partition discipline (never CAST a projected partition column -- the Jul-2026 $134 LIST storm) by
construction. No LLM anywhere: table/metric come from cascade_map.yaml, the windows from the walk's own
clustered prop/event dates. Kill switch GRAPHRAG_CASCADE_QUANT (checked at the answer.py seam, not here).

LEG MODEL (verify round R1/R2): a node's legs are ERA legs (one per derived analogue-era window, each fanning
>=2 marketing years so a WITHIN-ERA delta exists) plus ONE CURRENT "rhyme" leg (the CURRENT period at the
SESSION as-of -- never the historical window re-run at a new as-of, which would fetch a vintage revision).
The DIVERGENCE fork is CROSS-ERA within one node; the REROUTE fork (RF-3/RF-4) is CROSS-COUNTRY within one
contract: two trade legs over ONE shared anchor window whose within-era deltas OPPOSE (Russia exports down,
US exports up -- the flow found a new door).
"""
from __future__ import annotations

import functools
import re

from leviathan.graphrag import params as _pr
from leviathan.graphrag.numbers import query as Q

CASCADE_CAP = int(_pr.get("serving.cascade.cap", 12))            # own budget, separate from serving.silver.cap
CHAIN_CAP = int(_pr.get("serving.cascade.chain.cap", 12))        # chain engine's OWN net-fetch budget (D5): chains
#                                                                  never eat the per-node cascade's cap, nor vice versa
# The HORIZONTAL transmission engine's OWN net-fetch budget (TRANSMISSION_CHAIN_PLAN 3.3 control-2 / D5, fold-pass
# finding 3). NOT a shared counter: the ratified vertical CHAIN_CAP above is standalone and stays untouched, so the
# two chain engines are budget-INDEPENDENT (and under the D11 mutual exclusion at most one of them fires per turn,
# which makes a combined counter redundant anyway). Overflow -> ATOMIC decline (`cap`), never a truncated chain.
TRANSMISSION_CAP = int(_pr.get("serving.cascade.transmission.cap", 18))
TRANSMISSION_DEPTH_CAP = 2                                       # links per chain, v1 (D1): 3-4 link paths deferred


# ── the map (B-S2) ───────────────────────────────────────────────────────────────────────────────────
@functools.lru_cache(maxsize=1)
def load_map() -> dict:
    """{silver_ref: {table, metric, agg, period_type, native_unit, narrate_unit, scale, country_rule}}.
    lru_cached; a row flagged `deferred: true` (uncertified/empty source, e.g. ESR) is inert: never returned
    to the seam, so map_row() -> None -> the hop stays qualitative (no record_silent on a dead table)."""
    import yaml

    from leviathan.graphrag import extract as ex  # ex._CFG = configs/graphrag (registry convention)
    p = ex._CFG / "numbers" / "cascade_map.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return {ref: row for ref, row in ((doc or {}).get("refs") or {}).items() if not (row or {}).get("deferred")}


def map_row(silver_ref: str) -> dict | None:
    """The map row for a driver's silver_ref, or None (-> the hop stays qualitative)."""
    return load_map().get(silver_ref or "")


@functools.lru_cache(maxsize=1)
def load_region_map() -> dict:
    """The cascade_map.yaml TOP-LEVEL `region_map` block: {"resolve": {token: {country, currency}},
    "unresolved": [token, ...]}. Needs its OWN accessor -- load_map() returns the refs block only (rrv1 2b),
    so the region resolver and the config lint cannot piggyback it."""
    import yaml

    from leviathan.graphrag import extract as ex
    p = ex._CFG / "numbers" / "cascade_map.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return (doc or {}).get("region_map") or {}


@functools.lru_cache(maxsize=1)
def load_chain_map() -> list:
    """The curated `configs/graphrag/numbers/chain_map.yaml` `chains:` list, FILE ORDER preserved (the engine
    selects the FIRST focus-matching row -- deterministic). Each chain: {id, contracts:[...], hops:[{node, ref,
    country?}], terminal?}. A row flagged `deferred: true` is inert (skipped, mirroring load_map). Schema/loader
    ONLY here -- the file CONTENT + the config_check `check_chain_map` lint are the chain_map curation surface
    (TRACKED, like cascade_map, cascade_map.yaml:7-8). Missing file -> [] (the chain engine no-ops)."""
    import yaml

    from leviathan.graphrag import extract as ex
    p = ex._CFG / "numbers" / "chain_map.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return [c for c in ((doc or {}).get("chains") or []) if not (c or {}).get("deferred")]


def _transmission_row_ok(chain) -> bool:
    """The FAIL-CLOSED structural rules for one transmission_map row (TRANSMISSION_CHAIN_PLAN D1). Applied by
    the loader so a config drift can NEVER reach the composer (the load_complex_map `material` precedent, where
    an unratified row simply does not load):
      * 2..TRANSMISSION_DEPTH_CAP links -- the v1 depth cap; a 1-link "chain" is just an RV2 pair, which the
        pair engine already serves;
      * every link carries a non-empty pair_id/source/target, and source != target;
      * consecutive links share EXACTLY one node: links[i].target == links[i+1].source (the hub);
      * the node sequence is SIMPLE (no repeated slug) -- a revisited node is a walk, not a chain.
    Never raises (a malformed row is a dropped row, not an exception at import time)."""
    try:
        links = (chain or {}).get("links") or []
        if not (2 <= len(links) <= TRANSMISSION_DEPTH_CAP) or not str((chain or {}).get("id") or ""):
            return False
        nodes: list = []
        for i, lk in enumerate(links):
            src, tgt = (lk or {}).get("source"), (lk or {}).get("target")
            if not ((lk or {}).get("pair_id") and src and tgt) or src == tgt:
                return False
            if i and links[i - 1].get("target") != src:               # the shared hub, exactly one node
                return False
            if not i:
                nodes.append(src)
            nodes.append(tgt)
        return len(set(nodes)) == len(nodes)                          # simple path (no repeated node)
    except Exception:  # noqa: BLE001
        return False


@functools.lru_cache(maxsize=1)
def load_transmission_map() -> list:
    """The curated `configs/graphrag/numbers/transmission_map.yaml` `chains:` list, FILE ORDER preserved (the
    composer first-fires the FIRST focus-matching row -- deterministic), mirroring load_chain_map. Each chain:
    {id, links: [{pair_id, source, target, nature}]}. `nature` is the per-link EXPECTATION HINT only -- never a
    gate and never a forced render (D9 + the fold-pass HIGH finding: the RV2 fork is purely SIGN-driven, so the
    engine renders the OBSERVED per-window sign, co-move or divergence, whichever the record shows).

    A row flagged `deferred: true` is inert, and a row failing `_transmission_row_ok` is DROPPED (fail-closed).
    Schema/loader ONLY here -- the file CONTENT is the curation surface (TRACKED, like chain_map.yaml).
    Missing file -> [] (the composer no-ops)."""
    import yaml

    from leviathan.graphrag import extract as ex
    p = ex._CFG / "numbers" / "transmission_map.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return [c for c in ((doc or {}).get("chains") or [])
            if not (c or {}).get("deferred") and _transmission_row_ok(c)]


# ── marketing-year boundaries (P8: a naive int(date[:4]) picks the WRONG MY for an Aug wheat event) ──
# Per-commodity-family MY start month. The covering market_year is the year the MY STARTS: an Aug-2010 date
# under a Jun-May wheat year is MY2010 (started Jun-2010); a Mar-2010 date is MY2009.
MY_START_MONTH = {
    "wheat": 6, "french_wheat_matif": 6, "kc_wheat": 6, "spring_wheat_mgex": 6,
    "corn": 9, "soybeans": 9, "soybean_oil_cbot": 10, "soybean_meal_cbot": 10,
    "raw_sugar": 10, "white_sugar": 10, "arabica_coffee": 10, "robusta_coffee": 10,
    "cotton": 8, "rough_rice": 8, "cocoa": 10,
    # reroute-v2 veg-oil legs (WINDOW SCOPING only -- consistent with silver derivation, never a reader-facing
    # calendar claim). Palm = Oct (10), NOT the plan body's Nov: USDA GAIN prints "Market Year Begins Oct" for
    # BOTH Indonesia and Malaysia (2026-07-18 probe P2, refuting the draft's 11). Rapeseed-oil = Oct (10), the
    # ZCE-home (China) convention.
    "malaysian_crude_palm_oil_cme": 10, "rapeseed_oil_zce": 10,
}
_MY_DEFAULT_START = 9                                             # USDA split-year default (Sep-Aug family)


def _my_start(commodity: str) -> int:
    c = (commodity or "").lower()
    if c in MY_START_MONTH:
        return MY_START_MONTH[c]
    for key, m in MY_START_MONTH.items():                         # family match: 'kc_wheat_kcbt' -> wheat
        if key in c:
            return m
    return _MY_DEFAULT_START


def _covering_my(date: str, commodity: str) -> int | None:
    """Deterministic per-commodity marketing-year for an ISO date (the MY that CONTAINS it)."""
    try:
        y, m = int(str(date)[:4]), int(str(date)[5:7])
    except (TypeError, ValueError):
        return None
    return y if m >= _my_start(commodity) else y - 1


def _my_span(window: tuple, commodity: str) -> list[int]:
    """ORDERED market_year ints the episode spans (>=1; >=2 when it crosses an MY boundary), so the era leg
    can fan >=2 MY specs and a within-era delta exists (R2). Widened by one MY when the span is a single
    year, so even a tight episode yields a delta pair."""
    a = _covering_my(window[0], commodity)
    b = _covering_my(window[1], commodity)
    if a is None or b is None:
        return []
    lo, hi = min(a, b), max(a, b)
    if lo == hi:
        lo = lo - 1                                               # widen backward: prior-MY baseline vs event MY
    return list(range(lo, hi + 1))


def _my_slash(my: int) -> str:
    """int START-year MY -> the source's 'YYYY/YY' marketing_year label (silver_wasde stores the slash form,
    e.g. 2011 -> '2011/12', 2009 -> '2009/10', 1999 -> '1999/00'). silver_wasde.period_sql_type=string, so the
    bare int a PSD (period_sql_type=int) leg passes would compile to marketing_year='2011' and match ZERO rows
    -- the SEAM-B price leg is the first cascade leg on a string-MY table, so it formats explicitly (B-S2)."""
    return f"{int(my)}/{(int(my) + 1) % 100:02d}"


# ── one PIT-safe windowed lookup (B-S1) ──────────────────────────────────────────────────────────────
def _status(rows: list, *, vintage: bool) -> str:
    """ok | record_silent (no rows in range) | not_known (vintage, value not yet published as-of)."""
    if rows:
        return "ok"
    return "not_known" if vintage else "record_silent"


def _period_label(t1, t2, period, period_type: str) -> str | None:
    """A CLEAN human window token for the citation label (citations.from_number reads query['period'])."""
    if period_type == "marketing_year":
        return f"MY{period}" if period is not None else None
    if t1 and t2:
        return f"{t1}..{t2}"
    return None


def _window_kwargs(period_type: str, t1, t2, period) -> dict:
    if period_type == "marketing_year":
        return {"period": str(period) if period is not None else None}   # NumberQuery.period is str-typed
    return {"period_start": t1, "period_end": t2}                 # date + year_month both bind period_start/end


def _query_dict(table, metric, commodity, country, t1, t2, asof, period, period_type) -> dict:
    return {"table": table, "metric": metric, "commodity": commodity, "country": country,
            "period": _period_label(t1, t2, period, period_type), "asof": asof}


@functools.lru_cache(maxsize=1)
def _registry():
    from leviathan.graphrag.numbers.registry import load_registry
    return load_registry()


def _is_vintage(table: str) -> bool:
    try:
        return _registry().get(table).knowledge_semantics == "vintage"
    except Exception:  # noqa: BLE001
        return False


def fetch_window(qfn, *, table, metric, commodity, country, t1, t2, asof,
                 agg="series", period=None, period_type="date") -> dict:
    """One deterministic PIT-safe windowed lookup -> a call-record {query, rows, status}.

    PER-LEG asof pinning is the CALLER's responsibility (quantify): a historical/era leg passes
    asof=window_end (already clamped to <= session_asof in _derive_windows, R3); the CURRENT 'rhyme' leg
    passes asof=session_asof with the CURRENT period. This fn NEVER computes today.

    GRACEFUL DEGRADATION (R6): EVERY failure path -- a NumberQuery/build_sql validation error (bad metric,
    malformed MY, a country that fails _canon_country), a pg/Athena outage, a timeout -- returns a
    call-record with status='error' and rows=[]. It NEVER raises, so _run_one / pool.map / the seam cannot
    unwind the reasoning turn."""
    # window clamp: SECONDARY belt only (R3). The PRIMARY future-guidance clamp lives in _derive_windows,
    # which bounds window_end to min(episode_end, session_asof) BEFORE it becomes this leg's asof.
    t2c = min(t2, asof) if (t2 and asof) else t2
    q = _query_dict(table, metric, commodity, country, t1, t2c, asof, period, period_type)
    if t1 and t2c and str(t1) > str(t2c):
        return {"query": q, "rows": [], "status": "future_unpublished"}
    try:
        vintage = _is_vintage(table)
        kw = _window_kwargs(period_type, t1, t2c, period)
        spec = Q.NumberQuery(table=table, metric=metric, asof=asof, commodity=commodity,
                             country=country, agg=agg, **kw)
        rows = Q.run(spec, query_fn=qfn)
    except Exception as e:  # noqa: BLE001 -- a bad/slow lookup must NEVER kill the reasoning turn
        return {"query": q, "rows": [], "status": "error", "error": str(e)[:200]}
    return {"query": q, "rows": rows, "status": _status(rows, vintage=vintage)}


# ── node selection + window derivation (B-S3 helpers; none may raise) ───────────────────────────────
def _silver_ref(n) -> str | None:
    try:
        return (getattr(n, "prior", None) or {}).get("silver_ref")
    except Exception:  # noqa: BLE001
        return None


def _select_nodes(sg, graph) -> list:
    """Bounded, deterministic selection: every grounded node that carries a mapped silver_ref, focus-first.
    Dedupe by node key; order = walk order (relevance-ranked upstream)."""
    try:
        nodes = list(getattr(sg, "nodes", None) or [])
    except Exception:  # noqa: BLE001
        return []
    seen, out = set(), []
    for n in nodes:
        # id FIRST: the production GroundedNode has .id and NEITHER .node nor .driver (F0/RF-1 -- keying on
        # the absent attrs collapsed every prod node to (contract, None); the depth-0 contract seed claimed
        # the slot and evicted every driver, so the cascade was entirely dark on real topology).
        key = (getattr(n, "contract", None),
               getattr(n, "id", None) or getattr(n, "node", None) or getattr(n, "driver", None))
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def _derive_windows(n, near, asof) -> list[tuple]:
    """Analogue-era windows from the node's own dated props: cluster event/report dates into episodes,
    keep the 1-2 nearest `near` (else the densest), widen ~1 quarter past the event, and CLAMP each end to
    min(end, asof) (R3 -- a forward-guidance event_date can date an episode past the session cutoff; this
    derive-side clamp is the PRIMARY PIT guard). Returns a list of (start, end); empty-span episodes drop."""
    try:
        from leviathan.graphrag import timeline as tl
        from leviathan.graphrag.answer import _usable_date
        dates = [d for e in (getattr(n, "evidence", None) or [])
                 for d in [_usable_date(e.get("event_date")) or _usable_date(e.get("date"))] if d]
        if not dates:
            return []
        eps = tl.cluster(dates, 90)
        if near:                                                  # nearest the analogue anchor first
            eps.sort(key=lambda ep: abs(int(str(ep["start"])[:4]) - int(str(near)[:4])))
        else:                                                     # else densest episodes first
            eps.sort(key=lambda ep: -len(ep.get("dates") or []))
        out = []
        for ep in eps[:2]:
            start, end = str(ep["start"]), str(ep["end"])
            end = _plus_days(end, 90)                             # widen: the balance-sheet print lags the event
            if asof:
                end = min(end, str(asof))                         # R3 PRIMARY clamp
            if start <= end:
                out.append((start, end))
        return out
    except Exception:  # noqa: BLE001
        return []


def _plus_days(iso: str, days: int) -> str:
    try:
        import datetime as _dt
        return (_dt.date.fromisoformat(iso[:10]) + _dt.timedelta(days=days)).isoformat()
    except (TypeError, ValueError):
        return iso


# silver_psd keys balance sheets by EXCHANGE slug (verified via DISTINCT leviathan_slug, the W0 probe):
# the graph's reference contracts have no PSD row under their own slug and every leg read not_known —
# silently, by design of the degrade path. The numbers AGENT dodges this because its prompt mandates
# exchange slugs; the cascade bypasses the agent, so it aliases here.
PSD_SLUG_ALIAS = {"corn": "corn_cbot", "soybeans": "soybeans_cbot"}

# Contracts with NO series in silver_psd AT ALL (DISTINCT leviathan_slug, C002-verified 2026-07-15):
# USDA PSD carries no cocoa balance sheet (ICCO territory) and no frozen-orange-juice series. A
# quantify against them can only ever return 0 rows -- declare the absence so the leg SKIPs
# honestly at _scope and the C002 slug check reads it as KNOWN-UNSERVED rather than drift.
PSD_UNSERVED_SLUGS = frozenset({"cocoa", "frozen_orange_juice"})


# _scope's country slot for a region-ruled leg that CANNOT honestly resolve to one table country
# (compound/prose/missing region token): quantify must SKIP the node whole -- country=None on a PSD trade
# ref is mixed-country garbage, and falling back to the contract primary stamps the WRONG country's numbers
# on a foreign-region leg with country=<primary> in the [N] citation (rrv1 2c).
SKIP_NODE = object()


def _region_entry(n) -> dict | None:
    """region_map resolve entry for the node's driver region token; None = unresolvable (compound/prose/
    missing). Exact-token match only -- splitting compounds is RF-3 pairing work, never a resolver guess."""
    try:
        tok = ((getattr(n, "prior", None) or {}).get("region") or "").strip()
    except Exception:  # noqa: BLE001
        return None
    if not tok:
        return None
    return (load_region_map().get("resolve") or {}).get(tok)


# PSD aggregates EU members under 'European Union' -- a member-state primary (the matif contracts' geo
# primary is France) reads 0 PSD rows and the leg dies not_known (Stage-1 RCA q11: the reroute
# beneficiary declined on exactly this, with the pair silently un-fireable).
# 'Cote Divoire' (cocoa's geo primary, apostrophe lost in title-casing) vs PSD's "Cote d'Ivoire" is
# the same class -- census-caught 2026-07-11 (country-not-a-psd-title x3), fold validated against the
# live DISTINCT-title probe.
_PSD_COUNTRY_FOLD = {"France": "European Union", "Cote Divoire": "Cote d'Ivoire"}


def _primary_title(commodity) -> str | None:
    """The contract's primary balance-sheet country in the TABLE surface form ('united_states' ->
    'United States'), EU members folded to 'European Union' (PSD's aggregation level); None when no
    geography primary exists (callers degrade, never guess)."""
    try:
        from leviathan.graphrag import silverleg as slv
        country = slv._primary_country(commodity)
        if not country:
            return None
        titled = country.replace("_", " ").title()
        return _PSD_COUNTRY_FOLD.get(titled, titled)
    except Exception:  # noqa: BLE001
        return None


def _region_row(n, row) -> dict:
    """fred_fx currency pick (RF-2): a country_rule=region row on silver_fred_fx swaps its metric to the
    resolved region's '<currency>_usd' (the ars_usd/brl_usd fold-forward fix). Every other row passes
    through unchanged. A resolved region WITHOUT a currency never reaches here (SKIP_NODE in _scope)."""
    if (row or {}).get("country_rule") != "region" or (row or {}).get("table") != "silver_fred_fx":
        return row
    cur = (_region_entry(n) or {}).get("currency")
    return {**row, "metric": f"{cur}_usd"} if cur else row


def _scope(n, row) -> tuple:
    """commodity = the node's contract (aliased to the silver slug where they differ); country per the
    map row's country_rule, in the TABLE's surface form — silver_psd stores 'United States' while geo
    gives 'united_states' (the silverleg precedent; both mismatches W0-caught: every PSD leg died).
    country_rule: none -> no country; primary -> the contract's primary country (default); region -> the
    DRIVER's own region token via region_map (F1/RF-2 -- primary quantified the US series under a
    Russia/China leg), with SKIP_NODE when the token does not resolve. silver_fred_fx has no country
    column: a resolved region needs a currency (metric pick, _region_row) or the leg is not honest."""
    commodity = getattr(n, "contract", None)
    commodity = PSD_SLUG_ALIAS.get(commodity, commodity)
    if (row or {}).get("table") == "silver_psd" and commodity in PSD_UNSERVED_SLUGS:
        return commodity, SKIP_NODE          # declared-unserved: PSD has no series for this contract
    rule = (row or {}).get("country_rule", "primary")
    if rule == "none":
        return commodity, None
    if rule == "region":
        entry = _region_entry(n)
        if not entry:
            return commodity, SKIP_NODE
        if (row or {}).get("table") == "silver_fred_fx":
            return commodity, (None if entry.get("currency") else SKIP_NODE)
        country = entry.get("country")
        return commodity, (country if country else SKIP_NODE)
    return commodity, _primary_title(commodity)


# ── T2a (CONVERGENCE_TIER1) pace-leg inventory: SUB-ANNUAL chronological grains ONLY ─────────────────
# tables.yaml grains, plan-ratified: weekly/daily/monthly tables can honestly carry a streak/window_change
# pace claim. Annual/MY tables (silver_psd, silver_wasde, silver_production, silver_sagis_cec,
# silver_icco_cocoa) are ABSENT by design -- they must NEVER be handed a sub-annual window (YoY is a
# different, existing surface). Event flags (frost_event_flag, narrate_unit=flag) get nothing: "pace" on a
# binary flag is crossing-recency, which is the deferred T2b ledger, not a window_change.
# silver_futures_prices is EXCLUDED despite its daily grain (skeptic fold 2026-07-23): the card is
# levels_only -- build_sql RAISES on any series/window read (PIT-unsafe across roll splices), so a pace
# spec there could only ever produce status=error, never a row. Re-add only if v1.5 lifts levels_only.
PACE_TABLES = {
    "silver_cot": "week", "silver_esr": "week",
    "silver_pink_sheet": "month", "silver_mpob": "month", "gold_weather_z": "month",
    "silver_noaa_oni": "month",
    "silver_fred_fx": "day",
}
# T2a CROSS-SECTION COLLAPSE (skeptic fold, pre-flip blocker): two pace tables return MULTIPLE rows per
# period under agg=series -- silver_esr is per DESTINATION x week (no country column even exists to
# filter) and gold_weather_z per REGION x month (region is not a query filter in v1). A flat
# vals[-1]-vals[-2] there deltas two destinations/regions inside ONE period, not two periods (probe: an
# ESR fixture narrated '+565 1000 MT from the prior week' vs the true weekly change -45 -- direction
# inverted -- riding a real minted [N] row the all-numbers guard validates). _pace_legs therefore
# collapses to ONE value per period BEFORE any stats primitive runs: sum for a flow total across
# destinations (the tables.yaml v1 doctrine: "v1 returns the TOTAL across destinations"), mean for a
# regional-average anomaly (the silver_nasa_power v1 aggregate-across-regions precedent). A multi-row
# period on a table NOT declared here declines the pace leg whole (honest absence, the E-STREAK-NODATA
# idiom) -- never a cross-sectional delta. Every other pace table is one-row-per-period by grain.
#
# PRICE_AND_PLAYBOOKS W3.3 item 17 / skeptic F-E: a THIRD kind, "front_expiry". A per-delivery-month
# price table is multi-row-per-period BY CONSTRUCTION (one row per listed expiry per session), and BOTH
# existing kinds are actively WRONG on a curve -- summing Dec+Mar+May settles is meaningless, and the mean
# across a curve is a different, unnamed series that would look entirely plausible in prose. The collapse
# a curve needs is a SELECTION KEYED ON ANOTHER COLUMN, not an aggregation over the period's values:
# select the FRONT expiry by the named, versioned query-time rule FIRST, then delta across DATES. That
# rule lives in exactly one place (leviathan.silver.futures_roll.front_month, ROLL_RULE_VERSION
# front_month_v1, fenced by config_check.check_futures_roll) and is CALLED here, never re-derived.
_PACE_COLLAPSE = {"silver_esr": "sum", "gold_weather_z": "mean", "silver_futures_eod": "front_expiry"}
_PACE_COLLAPSE_KINDS: frozenset[str] = frozenset({"sum", "mean", "front_expiry"})
# PRICE TABLES (F-E lint): a table whose served value IS a price. `sum`/`mean` are FORBIDDEN as the
# collapse kind for any of these -- the aggregate of a price cross-section is not a price anyone quotes.
# An EXPLICIT documented set rather than a registry derivation, for three reasons, all load-bearing:
#   (1) load_registry() DROPS whitelist-absent tables (registry.WHITELIST_ABSENT_DEFAULT), so
#       silver_futures_eod -- the exact table F-E is about -- is INVISIBLE to a registry-derived set
#       today: the fence would fail OPEN for the whole pre-flip window it exists to cover;
#   (2) config_check.PRICE_TABLES (the R4 "never feeds an engine" set) cannot be reused -- importing
#       config_check from here is a cycle, and its semantics are the opposite of this fence's (a pace
#       leg REQUIRES a cascade_map row, which R4 forbids for its members);
#   (3) price-ness is not a registry field -- there is no clean per-table signal to read.
# lint_pace_collapse() adds a registry-derived DRIFT BELT on top, so a price table nobody added here
# still cannot acquire a sum/mean collapse.
_PRICE_TABLES: frozenset[str] = frozenset({
    "silver_futures_eod",       # per-delivery-month EOD settles (W1.0)
    "silver_futures_prices",    # the yfinance continuous front-month close (levels_only, retiring)
    "silver_pink_sheet",        # World Bank monthly commodity prices (config_check.PRICE_TABLES' member)
})
_PRICE_COLLAPSE_BANNED: frozenset[str] = frozenset({"sum", "mean"})
# MULTI-EXPIRY tables: table -> the ROW ALIAS carrying the delivery month ('YYYY-MM'). Membership is the
# assertion "rows on this table are per delivery month", which has two consequences, both enforced:
# the front_expiry collapse is MANDATORY here (a declaration of any other kind, or none, declines the
# pace leg whole), and the selection needs this column threaded down to it. NOTE the alias is the QUERY
# alias, not the silver column: query._extras does not surface contract_month yet (W3.1 item 3), so the
# selection fails CLOSED -- honest absence -- until that lands.
_PACE_EXPIRY_COL = {"silver_futures_eod": "contract_month"}
_PACE_WINDOW_DAYS = {"day": 21, "week": 70, "month": 220}         # enough points for a run; never a year-crawl
_PACE_GRAIN_NOUN = {"day": "daily", "week": "weekly", "month": "monthly"}
# The T2a register fence for ENGINE-emitted pace prose: the present-continuous/momentum class is BANNED on
# this surface (accelerating/decelerating/momentum/gaining steam/picking up/slowing). These are grep-absent
# from register.py's global lexicons BY DESIGN (fencing them globally would strip honest ag prose like
# "demand is slowing"); the fence therefore lives HERE, on the only surface that could mint them.
_PACE_BANNED_RX = re.compile(
    r"\b(acceler\w*|deceler\w*|momentum|gaining steam|picking up|slowing)\b", re.I)


def pace_register_ok(text: str) -> bool:
    """True when a pace line carries none of the banned momentum-class words (past-tense observed only)."""
    return not _PACE_BANNED_RX.search(text or "")


# A metric NAME that is a price, and a unit shaped like CURRENCY-per-quantity ("USD/metric ton",
# "US cents/bushel", "CNY/t", "$/bu"). Together they are the registry-derived DRIFT BELT under
# lint_pace_collapse -- deliberately conservative, and only ever consulted for tables that already
# declare a collapse kind, so the scan is bounded by _PACE_COLLAPSE and can never fail a table that
# has no pace collapse at all.
_PRICE_METRIC_RX = re.compile(r"(?:^|_)(price|prices|settle|settlement|close|quote)(?:$|_)", re.I)
_PRICE_UNIT_RX = re.compile(
    r"(?:\bUSD|\bEUR|\bCNY|\bBRL|\bZAR|\bMYR|\bCAD|\bGBP|\bJPY|\bCHF|\bAUD|\bINR|cents|\$)\s*/", re.I)


def _looks_like_price_table(ts) -> bool:
    """Registry-derived price-ness for the drift belt: a served metric NAMED like a price, or carrying a
    currency-per-quantity unit (card unit or any per-commodity unit_override). Never raises."""
    try:
        for mname, m in (getattr(ts, "metrics", None) or {}).items():
            if _PRICE_METRIC_RX.search(str(mname)):
                return True
            units = [getattr(m, "unit", None) or ""]
            units += list((getattr(m, "unit_overrides", None) or {}).values())
            if any(_PRICE_UNIT_RX.search(str(u)) for u in units):
                return True
    except Exception:  # noqa: BLE001 -- a lint belt must never raise on an odd card
        return False
    return False


def lint_pace_collapse() -> list[str]:
    """Structural problems with the pace-collapse declarations (pure; config_check.check_pace_collapse
    binds it). Skeptic F-E, W3.3 item 17 -- four clauses:

      (1) every declared kind is one of _PACE_COLLAPSE_KINDS;
      (2) THE F-E LINT -- no PRICE table declares `sum` or `mean`. Summing Dec+Mar+May settles is
          meaningless and the mean across a curve is a different, unnamed series that reads as plausible
          prose; both would ride a real minted [N] handle the all-numbers guard validates as correct;
      (3) the same, for a table the REGISTRY says looks like a price table but that nobody added to
          _PRICE_TABLES (the drift belt -- note it cannot see whitelist-absent cards, which is exactly
          why clause (2) works off an explicit set);
      (4) front_expiry <-> _PACE_EXPIRY_COL is a BOTH-WAYS bind: the selection needs the delivery-month
          alias threaded to it, and a table declared per-expiry must not collapse any other way."""
    errs: list[str] = []
    for table, kind in sorted(_PACE_COLLAPSE.items()):
        if kind not in _PACE_COLLAPSE_KINDS:
            errs.append(f"_PACE_COLLAPSE {table!r}: unknown collapse kind {kind!r} "
                        f"(legal: {sorted(_PACE_COLLAPSE_KINDS)})")
            continue
        if kind in _PRICE_COLLAPSE_BANNED and table in _PRICE_TABLES:
            errs.append(f"_PACE_COLLAPSE {table!r}: {kind!r} is FORBIDDEN on a price table (F-E) -- the "
                        f"sum of a curve is meaningless and its mean is an unnamed series; a per-expiry "
                        f"price table collapses by 'front_expiry' (select the front expiry by the named "
                        f"query-time rule FIRST, then delta across dates)")
        if kind == "front_expiry" and not str(_PACE_EXPIRY_COL.get(table) or "").strip():
            errs.append(f"_PACE_COLLAPSE {table!r}: 'front_expiry' but no delivery-month alias in "
                        f"_PACE_EXPIRY_COL -- the selection has no column to key on and would decline "
                        f"every leg silently")
    # (3) the registry drift belt -- bounded by _PACE_COLLAPSE, never a whole-registry scan.
    try:
        from leviathan.graphrag.numbers.registry import load_registry
        tables = load_registry().tables
    except Exception:  # noqa: BLE001 -- a registry problem is another lint's failure, not this one's
        tables = {}
    for table, kind in sorted(_PACE_COLLAPSE.items()):
        if kind not in _PRICE_COLLAPSE_BANNED or table in _PRICE_TABLES:
            continue
        ts = tables.get(table)
        if ts is not None and _looks_like_price_table(ts):
            errs.append(f"_PACE_COLLAPSE {table!r}: {kind!r} on a table the registry card reads as a PRICE "
                        f"table (priced metric or currency-per-quantity unit) -- either it is not a price "
                        f"table and the card is wrong, or it is and F-E forbids {kind!r} here")
    for table in sorted(_PACE_EXPIRY_COL):
        if _PACE_COLLAPSE.get(table) != "front_expiry":
            errs.append(f"_PACE_EXPIRY_COL {table!r}: declared per-delivery-month but its _PACE_COLLAPSE "
                        f"kind is {_PACE_COLLAPSE.get(table)!r} -- a per-expiry table has exactly one "
                        f"honest collapse, and any other declaration declines the pace leg whole")
    return errs


def _pace_grain(row) -> str | None:
    """The pace grain word for a map row, or None (=> NO pace leg): annual/MY grain, event flags, and any
    table outside the pace-capable inventory all decline structurally."""
    if (row or {}).get("period_type") == "marketing_year":
        return None                                               # annual/MY: never a sub-annual window
    if (row or {}).get("narrate_unit") == "flag":
        return None                                               # event flag: recency is T2b, not pace
    return PACE_TABLES.get((row or {}).get("table"))


def _node_specs(n, row, commodity, country, eras, asof, *, pace: bool = False) -> list[dict]:
    """The node's spec list: per era window, >=2 MY specs (marketing_year) or one windowed spec (date/ym);
    plus ONE CURRENT rhyme spec (R1: the CURRENT period at the SESSION asof, never the era window re-run).
    `pace` (T2a, default OFF -- flag-threaded from quantify, never an env read): pace-capable sub-annual
    tables ALSO get ONE trailing-window series spec (leg=('pace', None)) beside the current leg."""
    if not commodity:
        return []
    # id FIRST (RF-1, same re-key as _select_nodes): the group/spec key must be distinct per driver or
    # _group_by_node interleaves drivers' MYs and _era_delta computes cross-driver garbage.
    base = {"node_key": (commodity,
                         getattr(n, "id", None) or getattr(n, "node", None) or getattr(n, "driver", None)),
            "table": row["table"], "metric": row["metric"], "commodity": commodity, "country": country,
            "period_type": row.get("period_type", "date")}
    specs: list[dict] = []
    # ESR is shallow/US-only/weekly -- a terrible analogue backbone; `leg_mode: current` emits the fresh
    # rhyme leg ONLY, never an era leg (D-W3.2, the "era-legs-stay-PSD" guard). The default (no leg_mode)
    # preserves PSD's era+current behavior exactly.
    if row.get("leg_mode") != "current":
        for i, (t1, t2) in enumerate(eras):
            if base["period_type"] == "marketing_year":
                for my in _my_span((t1, t2), commodity):
                    specs.append({**base, "leg": ("era", i), "era_idx": i, "my": my, "t1": None, "t2": None,
                                  "asof": t2, "agg": row.get("agg", "latest"), "period": my})
            else:
                specs.append({**base, "leg": ("era", i), "era_idx": i, "my": None, "t1": t1, "t2": t2,
                              "asof": t2, "agg": "series", "period": None})
    if asof:                                                      # the CURRENT rhyme leg (R1)
        if base["period_type"] == "marketing_year":
            cur_my = _covering_my(asof, commodity)
            if cur_my is not None:
                specs.append({**base, "leg": ("current", None), "era_idx": None, "my": cur_my,
                              "t1": None, "t2": None, "asof": asof, "agg": "latest", "period": cur_my})
        else:
            specs.append({**base, "leg": ("current", None), "era_idx": None, "my": None,
                          "t1": _plus_days(asof, -365), "t2": asof, "asof": asof,
                          "agg": row.get("agg", "series"),      # D-W3.2/C2: ESR pace -> 'latest' (the freshest
                          #                                       week <= asof); default 'series' keeps PSD
                          #                                       date legs (fred_fx) unchanged
                          "period": None})
    if pace and asof and _pace_grain(row) is not None:            # T2a: ONE trailing sub-annual series spec
        days = _PACE_WINDOW_DAYS[_pace_grain(row)]                # (flag off -> this block never runs ->
        specs.append({**base, "leg": ("pace", None), "era_idx": None, "my": None,   # byte-identical specs)
                      "t1": _plus_days(asof, -days), "t2": asof, "asof": asof,
                      "agg": "series", "period": None})
    return specs


def _run_one(qfn, spec: dict) -> dict:
    """Unpack a spec and fetch; NEVER raises (a malformed spec returns an error record, R6)."""
    try:
        rec = fetch_window(qfn, table=spec["table"], metric=spec["metric"], commodity=spec["commodity"],
                           country=spec["country"], t1=spec["t1"], t2=spec["t2"], asof=spec["asof"],
                           agg=spec["agg"], period=spec["period"], period_type=spec["period_type"])
    except Exception as e:  # noqa: BLE001
        rec = {"query": {}, "rows": [], "status": "error", "error": str(e)[:200]}
    rec["node_key"] = spec.get("node_key")
    rec["leg"] = spec.get("leg")
    rec["era_idx"] = spec.get("era_idx")
    rec["my"] = spec.get("my")
    return rec


# ── RF-3: cross-country pairing + the synthesized beneficiary leg ───────────────────────────────────
_TRADE_METRICS = {"exports_mt", "imports_mt"}


def _pairable(g: dict) -> bool:
    """A group can seed a reroute pair only on a PSD trade metric with ONE resolved country string
    (fx/oni legs carry country=None -- nothing to diverge on)."""
    return (g["row"].get("metric") in _TRADE_METRICS
            and isinstance(g.get("country"), str) and bool(g["country"]))


def _family_pair(ma, mb) -> bool:
    """export-vs-export (one flow, two doors) or the export+import complement (supply leaving one door,
    arriving at another); import-vs-import is not a reroute shape."""
    return (ma == mb == "exports_mt") or ({ma, mb} == {"exports_mt", "imports_mt"})


def _shared_eras(ga: dict, gb: dict) -> list:
    """(era_idx_a, era_idx_b, my_span) matches where both groups' era windows cover the IDENTICAL MY span:
    the sign compare is only honest over ONE shared anchor window (never two independently derived eras)."""
    out = []
    for ia, wa in enumerate(ga.get("eras") or []):
        sa = _my_span(wa, ga["commodity"])
        if not sa:
            continue
        for ib, wb in enumerate(gb.get("eras") or []):
            if sa == _my_span(wb, gb["commodity"]):
                out.append((ia, ib, sa))
                break
    return out


def _beneficiary(g: dict) -> dict | None:
    """The synthesized BENEFICIARY leg for a foreign-country SHOCK: the contract PRIMARY country fetched
    over the SHOCK node's own era windows (the (country, anchor-window) fetch -- 2-3 era specs, never a
    full node with its own current leg). node_key = (commodity, n.id, country) MUST differ from the
    shock's 2-tuple key (rrv1 3c): a shared key would interleave the two countries' rows in
    _group_by_node and _era_delta would compute mixed-country garbage. None when the shock already
    resolves to the primary, or no primary exists."""
    primary = _primary_title(g["commodity"])
    if not primary or primary == g["country"]:
        return None
    n = g["node"]
    nid = getattr(n, "id", None) or getattr(n, "node", None) or getattr(n, "driver", None)
    bkey = (g["commodity"], nid, primary)
    specs = [{**s, "node_key": bkey}
             for s in _node_specs(n, g["row"], g["commodity"], primary, g["eras"], None)]
    if not specs:
        return None
    return {"node": n, "row": g["row"], "specs": specs, "key": bkey, "commodity": g["commodity"],
            "contract": g["contract"], "country": primary, "eras": g["eras"]}


def _pair_entry(ga: dict, gb: dict, eras: list) -> dict:
    return {"a_key": ga["key"], "b_key": gb["key"], "contract": ga["contract"],
            "countryA": ga["country"], "countryB": gb["country"],
            "metricA": ga["row"].get("metric"), "metricB": gb["row"].get("metric"),
            "row": ga["row"], "eras": eras}


def _pair_units(groups: list) -> tuple:
    """(cap_units, candidate_pairs). NATURAL pairs: two grounded trade groups on one contract slug with
    DIFFERENT resolved countries, a reroute metric family, and >=1 shared-MY-span era -- paired as-is, no
    synthesis. A lone foreign-country shock synthesizes the primary-country beneficiary (_beneficiary),
    which travels INSIDE the shock's cap unit so the cap keeps both or drops both (pair-atomic: a shock
    kept without its beneficiary could never fire and its specs would be spent for nothing)."""
    pairs, paired = [], set()
    for i, ga in enumerate(groups):
        if not _pairable(ga):
            continue
        for gb in groups[i + 1:]:
            if (not _pairable(gb) or gb["commodity"] != ga["commodity"]
                    or gb["country"] == ga["country"]
                    or not _family_pair(ga["row"].get("metric"), gb["row"].get("metric"))):
                continue
            eras = _shared_eras(ga, gb)
            if not eras:
                continue
            pairs.append(_pair_entry(ga, gb, eras))
            paired.update((id(ga), id(gb)))
    units = []
    for g in groups:
        unit = [g]
        if _pairable(g) and id(g) not in paired:
            ben = _beneficiary(g)
            if ben is not None:
                unit.append(ben)
                # beneficiary eras ARE the shock's eras: idx aligns 1:1 by construction
                ben_eras = [(i, i, sp) for i, w in enumerate(g["eras"])
                            for sp in [_my_span(w, g["commodity"])] if sp]
                pairs.append(_pair_entry(g, ben, ben_eras))
        units.append(unit)
    return units, pairs


# ── the orchestration (B-S3) ─────────────────────────────────────────────────────────────────────────
def quantify(sg, graph, *, qfn, asof, near, extra_number_calls: list, xc_request: dict | None = None,
             comove: bool = False, price_request: dict | None = None, pace: bool = False,
             chain: bool = False, transmission: bool = False) -> tuple:
    """Select grounded nodes with mapped refs, derive analogue-era windows from their dated props, build
    per-node leg GROUPS (era legs + a current rhyme leg), detect cross-country REROUTE pairs (RF-3:
    natural two-node pairs + the synthesized primary-country beneficiary), cap on WHOLE pair-atomic
    UNITS, fan the specs concurrently over the pg pool, PRE-SCALE + inject citable [N] rows (continuing
    the N-count), compute CROSS-ERA deltas + the divergence flag + the cross-country REROUTE (RF-4), and
    return (prompt_block, trace_list, reroute_trace). extra_number_calls is appended IN PLACE.
    Never raises (R6 -- the seam also belts it)."""
    groups = []
    for n in _select_nodes(sg, graph):
        row = map_row(_silver_ref(n))
        if row is None:
            continue                                              # unmapped OR deferred -> stays qualitative
        eras = _derive_windows(n, near, asof)
        # T2a P4 (live-wiring fix): a `leg_mode: current` pace-capable node (esr_exports) never USES era
        # windows, yet the gate below demanded them -- and its driver (export_pace) is a WAIVERED
        # numbers-lane id with NO text slice, so ground() leaves it prior-only, _derive_windows returns
        # [], and the node died HERE before _node_specs ever saw the pace kwarg (the P1-probe outcome (c):
        # quantify_pace absent while the cascade fired on evidence-backed nodes). Fixture tests hand nodes
        # dated evidence, which is why they passed. Gated on `pace` so the flag-off path (and every
        # era-legged table) is byte-identical to today.
        if not eras and not (pace and row.get("leg_mode") == "current" and _pace_grain(row) is not None):
            continue
        commodity, country = _scope(n, row)
        if country is SKIP_NODE:
            continue                                              # unresolved region leg -> stays qualitative
        row = _region_row(n, row)                                 # fred_fx: region currency picks the metric
        specs = _node_specs(n, row, commodity, country, eras, asof, pace=pace)
        if specs:
            groups.append({"node": n, "row": row, "specs": specs, "key": specs[0]["node_key"],
                           "commodity": commodity, "contract": getattr(n, "contract", None),
                           "country": country, "eras": eras})
    if not groups and not chain and not transmission:
        return None, [], []                                       # both flags False -> byte-identical early
        #                                                           return; either chain engine runs over empty
        #                                                           groups (their grounding checks are their own:
        #                                                           the vertical roots on the walk, the horizontal
        #                                                           derives its anchor from the source node)
    units, pairs = _pair_units(groups)
    # CAP ON WHOLE NODES (P7/F5): a node never loses a leg to truncation; drop trailing nodes whole.
    # A unit = one node OR a shock+beneficiary pair (RF-3, ATOMIC): keep both or drop both -- a shock kept
    # without its beneficiary can never fire the reroute.
    kept, used = [], 0
    for unit in units:
        cost = sum(len(g["specs"]) for g in unit)
        if used + cost > CASCADE_CAP and kept:
            break
        kept.extend(unit)
        used += cost
    kept_keys = {g["key"] for g in kept}
    pairs = [p for p in pairs if p["a_key"] in kept_keys and p["b_key"] in kept_keys]
    flat = [s for g in kept for s in g["specs"]]
    # ONE wave, executor width = the pg CONNECTION POOL (R5): 12 workers over a 4-conn pool would be
    # ceil(N/4) serial rounds anyway -- width=pool is the honest (and equally fast) shape.
    from concurrent.futures import ThreadPoolExecutor

    from leviathan.graphrag.pgstore import _POOL_SIZE
    width = max(1, min(_POOL_SIZE, len(flat)))
    with ThreadPoolExecutor(max_workers=width) as pool:
        records = list(pool.map(lambda s: _run_one(qfn, s), flat))   # order preserved; _run_one never raises
    base = len(extra_number_calls)
    block_lines, trace, era_deltas = _assemble(records, kept, base, extra_number_calls)
    # T2a pace legs (CONVERGENCE_TIER1): gated ONLY by the answer.py-threaded `pace` kwarg
    # (GRAPHRAG_CASCADE_PACE_LEG is read at that seam, never here -- the price_request/xc discipline).
    # pace False -> no pace spec ever existed -> records carry no pace legs -> byte-identical. On FIRE the
    # engine writes quantify_pace ITSELF (pace_fired == bool(trace key)); an honest decline leaves it absent.
    if pace:
        p_lines, p_trace = _pace_legs(records, kept, len(extra_number_calls), extra_number_calls)
        if p_trace:
            try:
                sg.trace["quantify_pace"] = p_trace
            except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
                pass
            block_lines = block_lines + p_lines
    r_lines, r_trace = _reroute(pairs, era_deltas)
    block_lines = block_lines + r_lines
    # RV-W2: the cross-COMMODITY relative-value fork, gated ONLY by the orchestrator-threaded xc_request (the
    # env flag is checked at the answer.py seam). xc_request None -> this branch is inert and everything below
    # is byte-identical to v1. On FIRE the engine WRITES the trace key itself (C11: quantify_reroute_v2
    # non-empty == fired) and appends its BY-COMMODITY block; a decline/failure leaves the key absent.
    # [SKEPTIC F5] The transmission ENGINE runs first (its LINES still append at the chain-engines position
    # below, so the flag-off path and the line ORDER are byte-identical to before): when the composer FIRES,
    # its link-1 render IS this exact xc pair (the RV2 fence selects the curated row matching the ask), so the
    # standalone render below would narrate the same pair TWICE with duplicate [N] rows. Fired -> standalone
    # skipped; DECLINED or flag-off -> the standalone renders exactly as today (no lost fork).
    _xmit_fired = False
    _xmit_lines: list = []
    if transmission:
        try:
            _chain_already = bool((getattr(sg, "trace", None) or {}).get("quantify_chain"))
        except Exception:  # noqa: BLE001 -- a traceless sg reads as "the vertical engine has not fired"
            _chain_already = False
        _xmit_lines, x_trace, x_decline = _transmission_legs(sg, graph, groups, xc_request, qfn, asof, near,
                                                             extra_number_calls, comove=comove,
                                                             chain_fired=_chain_already)
        if x_trace:
            try:
                sg.trace["quantify_transmission"] = x_trace
            except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
                pass
            _xmit_fired = True
        elif x_decline:
            try:
                sg.trace["quantify_transmission_decline"] = x_decline
            except Exception:  # noqa: BLE001
                pass
    if xc_request and not _xmit_fired:
        xc_lines, xc_trace = _run_xc(xc_request, sg, graph, groups, qfn, asof, near, extra_number_calls,
                                     comove=comove)
        if xc_trace:
            # [SKEPTIC F3] The fired dict carries its own discriminator: a co-move sets comove:True (and omits
            # reroute_v2), so it routes to the NEW quantify_comove key and NEVER pollutes quantify_reroute_v2
            # (which eval reads as reroute_v2_pairs -- the rv2 NEGATIVE pins assert it empty).
            try:
                key = "quantify_comove" if xc_trace.get("comove") else "quantify_reroute_v2"
                sg.trace[key] = xc_trace
            except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
                pass
            block_lines = block_lines + xc_lines
    # SEAM B (F2 price-response): the settled US farm-price consequence pair for the FOCUS contract, gated ONLY
    # by the answer.py-threaded price_request (GRAPHRAG_CASCADE_PRICE_LEG is read at that seam, never here --
    # [F3]/xc_request discipline). price_request None -> inert, everything above byte-identical. POST-CAP + POST-
    # _assemble: the 2 fetches never enter the CASCADE_CAP truncation, so the cap can never split the pair. On
    # FIRE the engine WRITES quantify_price_leg itself (twin of the xc seam) and appends its '## The record' block.
    if price_request:
        p_lines, p_trace = _price_pair(price_request, sg, graph, groups, qfn, asof, near,
                                       extra_number_calls, len(extra_number_calls))
        if p_trace:
            try:
                sg.trace["quantify_price_leg"] = p_trace
            except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
                pass
            block_lines = block_lines + p_lines
    # THE TWO CHAIN ENGINES, both purely APPENDED after every other engine's lines so each existing line keeps
    # its byte position -- flag-off is byte-identical AND the flag-on diff is additive-only.
    #
    # VERTICAL CHAIN ENGINE (multi-hop quantified cascade WITHIN one contract): gated ONLY by the answer.py-
    # threaded `chain` kwarg (GRAPHRAG_CASCADE_CHAIN read THERE, never here -- the [F3]/pace discipline). On
    # FIRE the engine WRITES quantify_chain itself (fired == bool(trace key)); an attempted-and-declined chain
    # writes quantify_chain_decline (D7); no match -> BOTH keys absent (zero-cost turns).
    #
    # HORIZONTAL TRANSMISSION ENGINE (cross-commodity RV2 pair chain): the ENGINE ran ABOVE (before the
    # standalone RV2 render -- [SKEPTIC F5] dedup: a fired composer subsumes the standalone pair), but its
    # LINES append HERE so the rendered engine order is unchanged. D11 mutual exclusion holds in BOTH
    # directions -- (a) `chain_fired` carried the literal record that the vertical engine already fired THIS
    # turn (it yields, `cap`/yielded_to, before any fetch), and (b) when the composer fired, the vertical one
    # is not run at all below. So a turn RENDERS at most ONE chain engine. [SKEPTIC] The budgets are
    # engine-INDEPENDENT, not mutually exclusive in COST: a transmission chain that prewarms and then DECLINES
    # (dark/thin/co-move head link) has already spent up to TRANSMISSION_CAP, and the vertical engine still
    # runs below and may spend up to CHAIN_CAP -- a declined-transmission turn is the one shape where the two
    # budgets sum (<=30 net fetches). Gated ONLY by the answer.py-threaded `transmission` kwarg
    # (GRAPHRAG_CASCADE_TRANSMISSION read THERE, never here -- the [F3]/chain discipline) AND, inside the
    # engine, by an explicit `xc_request` (the RV2 fence: never volunteered). On FIRE the engine WROTE
    # quantify_transmission above; attempted-and-declined wrote quantify_transmission_decline; no attempt ->
    # BOTH keys absent (zero-cost turns stay zero-trace).
    block_lines = block_lines + _xmit_lines
    if chain and not _xmit_fired:                                 # D11: at most ONE chain engine per turn
        c_lines, c_trace, c_decline = _chain_legs(sg, graph, kept, records, qfn, asof, near, extra_number_calls)
        if c_trace:
            try:
                sg.trace["quantify_chain"] = c_trace
            except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
                pass
        elif c_decline:
            try:
                sg.trace["quantify_chain_decline"] = c_decline
            except Exception:  # noqa: BLE001
                pass
        block_lines = block_lines + c_lines
    block = ("OBSERVED CASCADE NUMBERS (as-known at each leg's asof; the record then vs now):\n"
             + "\n".join(block_lines)) if block_lines else None
    return block, trace, r_trace


# ── fork engine + ratio normalizer (B-S4) ────────────────────────────────────────────────────────────
def _float_val(rec) -> float | None:
    """FLOAT-CAST a row value (R9: Q.run returns values as STRINGS -- '0.36'*100 repeats the string)."""
    rows = rec.get("rows") or []
    if not rows:
        return None
    try:
        return float(str(rows[0].get("value")).replace(",", ""))
    except (TypeError, ValueError):
        return None


_GUARD_COLS = ("release_date", "week_ending_date", "data_date", "date", "year", "month")


def _prescaled(rec: dict, row: dict, n: int) -> dict:
    """Deep-copy the call-record with rows[0] PRE-SCALED to narrate_unit (the ratio normalizer: su_ratio
    0.36 -> 36.0/'%'), carrying the source row's PIT guard-column provenance forward (R10) so the
    pinned-asof backtest can check it."""
    import copy
    out = copy.deepcopy(rec)
    v = _float_val(rec)
    scale = float(row.get("scale", 1) or 1)
    if v is not None and out.get("rows"):
        out["rows"][0]["value"] = v * scale
        out["rows"][0]["unit"] = row.get("narrate_unit") or out["rows"][0].get("unit")
        src = (rec.get("rows") or [{}])[0]
        prov = {k: src.get(k) for k in _GUARD_COLS if src.get(k) is not None}
        if prov:
            out["rows"][0]["_provenance"] = prov
    out.pop("node_key", None)
    out.pop("leg", None)
    out.pop("era_idx", None)
    out.pop("my", None)
    return out


def _delta_call(rec: dict, row: dict, delta: float, n: int, *, kind: str, period=None) -> dict:
    """A synthetic call-record so a narrated delta IS a row value (citable + value-checkable). Stamps the
    LATER endpoint's guard-column provenance (R10) -- the delta is as-known at the later leg's asof.
    `period` overrides the inherited leg period label (F2: an era_diff row spans TWO eras, so it carries a
    'MY<a>->MY<b>' span label, not the single later-leg period)."""
    src = (rec.get("rows") or [{}])[0]
    prov = {k: src.get(k) for k in _GUARD_COLS if src.get(k) is not None}
    unit = "%" if kind == "pct" else (row.get("narrate_unit") or "")
    q = {**(rec.get("query") or {}), "metric": f"{row.get('metric')}_{kind}"}
    if period is not None:
        q["period"] = period
    return {"query": q,
            "rows": [{"value": round(delta, 4), "unit": unit, **({"_provenance": prov} if prov else {})}],
            "status": "ok"}


def _pace_synth(rec: dict, row: dict, value, n: int, *, kind: str, unit: str) -> dict:
    """T2a: a synthetic pace call-record (twin of _delta_call) so a narrated pace fact IS a row value
    (citable + value-checkable by the all-numbers guard). Provenance = the LATEST point's guard columns
    (ASC series -> rows[-1]): the pace fact is as-known at the newest observation."""
    src = (rec.get("rows") or [{}])[-1]
    prov = {k: src.get(k) for k in _GUARD_COLS if src.get(k) is not None}
    q = {**(rec.get("query") or {}), "metric": f"{row.get('metric')}_{kind}"}
    return {"query": q,
            "rows": [{"value": value, "unit": unit, **({"_provenance": prov} if prov else {})}],
            "status": "ok"}


def _pace_period_key(rr: dict, idx: int):
    """The row's PERIOD identity for the T2a cross-section collapse: the chronological data-axis alias
    (data_date) or the raw silver column names test fixtures/guard-cols carry, else (year, month) for
    year_month tables, else the row's own index -- a keyless single-grain table keeps the legacy
    one-row-one-period behavior exactly."""
    for k in ("data_date", "week_ending_date", "date", "report_date"):
        v = rr.get(k)
        if v not in (None, ""):
            return str(v)
    y, m = rr.get("year"), rr.get("month")
    if y not in (None, "") and m not in (None, ""):
        return (str(y), str(m))
    return ("_row", idx)


def _pace_collapse_kind(table) -> str | None:
    """The LEGAL collapse kind declared for `table`, or None (=> a multi-row period declines the leg).

    The runtime twin of lint_pace_collapse: an illegal declaration -- an unknown kind, or sum/mean on a
    PRICE table (F-E) -- resolves to None here rather than being applied, so the fence holds even on a
    build that never ran config_check. Fail-closed: None means honest absence, never a cross-section
    delta."""
    kind = _PACE_COLLAPSE.get(table)
    if kind is None or kind not in _PACE_COLLAPSE_KINDS:
        return None
    if table in _PRICE_TABLES and kind in _PRICE_COLLAPSE_BANNED:
        return None                                           # F-E: the aggregate of a curve is not a price
    return kind


def _pace_row_date(rr: dict) -> str | None:
    """The row's TRADE/DATA date for the front_expiry selection, or None. Widened past _pace_period_key's
    aliases by exactly one: `knowledge_date`. silver_futures_eod's date_col IS its knowledge_date_col
    (trade_date), so query._extras surfaces ONLY `knowledge_date` and _pace_period_key would fall through
    to its ("_row", idx) legacy branch -- which on a per-expiry table means EVERY ROW ITS OWN PERIOD, i.e.
    exactly the two-expiries delta F-E describes. Used ONLY on this path; the legacy key is untouched (it
    is load-bearing for silver_cot / silver_pink_sheet / silver_mpob, whose rows also carry only
    knowledge_date and ARE one row per period by grain)."""
    for k in ("data_date", "trade_date", "date", "knowledge_date", "week_ending_date", "report_date"):
        v = rr.get(k)
        if v not in (None, ""):
            return str(v)[:10]
    return None


def _pace_front_expiry(r: dict, expiry_col, commodity) -> tuple[list[float], str | None]:
    """W3.3 item 17 / F-E: ONE value per TRADE DATE, taken from the FRONT expiry as named by
    futures_roll.front_month (ROLL_RULE_VERSION front_month_v1) -- selection first, delta across dates
    after. Returns ([], None) on ANY incompleteness, which declines the pace leg whole.

    It declines rather than approximating in six cases, all of them the same principle -- the named rule
    must be RUN, never emulated:
      * no expiry alias threaded, or a row missing its delivery month (an unlabeled curve row is
        unattributable, and W3.1 item 3 has not surfaced `contract_month` yet);
      * no resolvable trade date on a row;
      * an unmapped slug, or a CASH INDEX (roll method 'none'): "front month" is not a question that can
        be asked of a CEPEA cash reference;
      * the rule's OWN INPUT is absent ON ANY CANDIDATE ROW -- front-by-OI/volume slugs whose rows carry
        no open_interest / volume value. front_month would fill the missing metric with -1 and silently
        fall through to its nearest-month tie-break, i.e. a DIFFERENT, unnamed rule (precisely the
        legacy_lane_front convention) wearing front_month_v1's name. BOTH-SIDED on purpose: an
        all-missing frame is the obvious case, but a PARTIAL one is the dangerous one -- with OI printed
        on some expiries and not others, whichever expiry happened to carry a print wins by default.
        The precondition is ASKED of futures_roll.front_month_inputs_present rather than restated here:
        which column a method reads is the rule module's contract (METHOD_METRIC_COL), and a second
        copy of it here would drift the moment DCE moves to front-by-volume -- F-L in miniature, and
        invisible to the config_check source fence, which only scans for a second IMPLEMENTATION.
        The served card is settle-ONLY, so the all-missing case is the live state today for every
        GLBX / CZCE / JSE / ICE slug; the delivery-cycle slugs (Bursa, MIAX, Euronext/MATIF, DCE) need
        no metric and select honestly now;
      * the selection returning nothing (every candidate expiry already in delivery / off-cycle);
      * the selection naming MORE THAN ONE delivery month across the window -- i.e. the front month
        ROLLED inside it. "Front expiry first, then delta across dates" is only PIT-safe while both
        endpoints are the SAME contract: a delta spanning a roll is a SPLICE, which is the exact
        contamination `levels_only` fences on the continuous sibling table, and it is also the
        remaining route by which a missing print on the true front month (that row skipped, the next
        expiry selected for that date alone) could still produce a cross-expiry delta. Roll/continuous
        are out of scope for this table by ratified design -- an adjusted series would be a separate
        gold_futures_continuous carrying its own roll_policy_version -- so the honest answer across a
        roll is no pace leg, not a spliced one.

    The value rides the frame's `settle` column: front_month never interprets it, it only carries it
    through the selection, and silver_futures_eod's served metric IS settle."""
    rows = r.get("rows") or []
    slug = commodity or (r.get("query") or {}).get("commodity")
    if not rows or not expiry_col or not slug:
        return [], None
    recs: list[dict] = []
    for rr in rows:
        cm = rr.get(expiry_col)
        dt = _pace_row_date(rr)
        if cm in (None, "") or not dt:
            return [], None                                   # unlabeled expiry / undated row: decline whole
        try:
            v = float(str(rr.get("value")).replace(",", ""))
        except (TypeError, ValueError):
            continue                                          # no numeric observation -> not a candidate
        if v != v:                                            # NaN is not an observation either
            continue
        recs.append({"leviathan_slug": str(slug), "trade_date": dt, "contract_month": str(cm)[:7],
                     "settle": v, "volume": rr.get("volume"), "open_interest": rr.get("open_interest")})
    if not recs:
        return [], None
    try:
        import pandas as pd

        from leviathan.silver import futures_roll as FR
        method = FR.roll_method_for(str(slug))                 # the ONE rule module -- never re-derived here
        if method == FR.METHOD_NONE:
            return [], None                                   # cash reference: no delivery-month axis at all
        frame = pd.DataFrame(recs)
        if not FR.front_month_inputs_present(frame):           # the rule's OWN input contract, asked of
            return [], None                                    # the rule module -- never restated here
        out = FR.front_month(frame)
    except Exception:  # noqa: BLE001 -- a pace leg must NEVER kill the reasoning turn (R6)
        return [], None
    if out is None or len(out) == 0:
        return [], None
    if len(set(out["contract_month"].tolist())) != 1:
        return [], None                                        # the front month ROLLED: a splice, not a delta
    vals: list[float] = []
    for v in out["settle"].tolist():                           # front_month sorts (slug, trade_date) ASC
        try:
            f = float(v)
        except (TypeError, ValueError):
            return [], None                                    # a selected row with no value: decline whole
        if f != f:
            return [], None
        vals.append(f)
    return vals, "front_expiry"


def _pace_series(r: dict, table, *, expiry_col=None, commodity=None) -> tuple[list[float], str | None]:
    """(one value per PERIOD in row order, collapse-mode-used-or-None) for a pace record. Rows arrive
    period-ascending (_total_order sorts the chronological alias first). Cross-sectional rows (>1 row in
    one period) collapse per _PACE_COLLAPSE -- sum (flow across ESR destinations), mean (z across
    weather regions), or, on a per-delivery-month PRICE table, the front_expiry SELECTION (W3.3 item 17);
    a multi-row period on an UNDECLARED table returns ([], None): the caller declines the leg whole rather
    than ever delta-ing two cross-section rows.

    `expiry_col` / `commodity` are the front_expiry SELECTION's two inputs, threaded here because the
    collapse cannot be expressed over the period's values alone (F-E: it is a selection keyed on another
    column). Both DEFAULT to what every caller would pass anyway -- the table's declared delivery-month
    alias and the record's own query commodity -- so a positional two-arg call behaves identically."""
    collapse = _pace_collapse_kind(table)
    if table in _PACE_EXPIRY_COL and collapse != "front_expiry":
        return [], None                                       # a per-expiry table has ONE honest collapse
    if collapse == "front_expiry":
        return _pace_front_expiry(r, expiry_col or _PACE_EXPIRY_COL.get(table), commodity)
    order: list = []
    periods: dict = {}
    for i, rr in enumerate(r.get("rows") or []):
        try:
            v = float(str(rr.get("value")).replace(",", ""))
        except (TypeError, ValueError):
            continue
        k = _pace_period_key(rr, i)
        if k not in periods:
            order.append(k)
            periods[k] = []
        periods[k].append(v)
    multi = any(len(periods[k]) > 1 for k in order)
    if multi and collapse is None:
        return [], None                                       # undeclared cross-section: honest decline
    vals: list[float] = []
    for k in order:
        vs = periods[k]
        if len(vs) == 1:
            vals.append(vs[0])
        elif collapse == "sum":
            vals.append(sum(vs))
        else:                                                 # collapse == "mean"
            vals.append(sum(vs) / len(vs))
    return vals, (collapse if multi else None)


def _pace_legs(records: list, kept: list, base: int, calls: list) -> tuple:
    """T2a: deterministic streak/window_change rows off the leg=('pace',*) series records (stats.py
    primitives -- the engine never does free-form math), computed over the PER-PERIOD collapsed series
    (_pace_series: ESR destination-sum / weather region-mean; an undeclared cross-section declines --
    the skeptic fold). PAST-TENSE register-safe lines only (rose/fell/
    'change from the prior week'); each [N] line carries exactly ONE figure (handle discipline). <2 points
    -> honest absence: no line, no call, no trace (the E-STREAK-NODATA lesson). Appends [N] calls IN PLACE
    (synthetic rows are cap-free, like every delta row). Returns (lines, trace); trace non-empty IFF at
    least one pace row was emitted -- quantify writes sg.trace['quantify_pace'] only then."""
    from leviathan.graphrag.numbers import stats as st
    rows_by_key = {g["specs"][0]["node_key"]: g["row"] for g in kept if g.get("specs")}
    lines, trace = [], []
    n = base
    for r in records:
        leg = r.get("leg") or ()
        if not leg or leg[0] != "pace" or r.get("status") != "ok":
            continue
        row = rows_by_key.get(r.get("node_key"))
        grain = _pace_grain(row) if row else None
        if grain is None:
            continue
        # PER-PERIOD collapse FIRST (the cross-section fold): ESR destinations sum, weather regions mean,
        # a per-delivery-month price table's FRONT-EXPIRY selection (W3.3 item 17, keyed on the table's
        # declared delivery-month alias and the record's own commodity); an undeclared multi-row period
        # returns ([], None) and the leg declines whole -- vals[-1]-vals[-2] below is only ever a
        # PERIOD-over-PERIOD delta on ONE series, never destinationB-destinationA and never DecB-MarA.
        # Called POSITIONALLY on purpose: _pace_series' two selection kwargs default to exactly what this
        # site would pass, so pattern_records_sweep_task.classify_pace_decline -- which replays this gate
        # positionally and cannot drift-check what it does not pass -- agrees by construction (F6).
        vals, collapsed = _pace_series(r, row.get("table"))
        if len(vals) < st.MIN_STREAK_N:
            continue                                              # <2 periods: no pace claim, no fabricated row
        scale = float(row.get("scale", 1) or 1)
        unit = row.get("narrate_unit") or ""
        gnoun = _PACE_GRAIN_NOUN[grain]
        key = r.get("node_key")
        entry = {"node_key": list(key) if isinstance(key, tuple) else key,
                 "table": row.get("table"), "metric": row.get("metric"), "grain": grain,
                 "n_points": len(vals), "streak": None, "window_change": None}
        if collapsed:                                             # conditionally-attached (absent, not null):
            entry["collapse"] = collapsed                         # a cross-section was actually merged
        emitted = False
        wc = st.window_change(vals, -2, -1)                       # latest point vs the prior point
        if not wc.get("declined"):
            d = round(wc["value"] * scale, 4)
            entry["window_change"] = d
            n += 1
            calls.append(_pace_synth(r, row, d, n, kind="pace_change", unit=unit))
            lines.append(f"- [N{n}] change in {row.get('metric')} from the prior {grain} "
                         f"({gnoun} pace): {d:+g} {unit}".rstrip())
            emitted = True
        last_delta = vals[-1] - vals[-2]
        if last_delta != 0:
            direction = "up" if last_delta > 0 else "down"
            sk = st.streak(vals, direction)
            run = 0 if sk.get("declined") else int(sk["value"])
            if run >= 2:                                          # a 1-period move is just the change row
                entry["streak"] = run
                entry["streak_direction"] = direction
                n += 1
                calls.append(_pace_synth(r, row, run, n, kind="pace_streak", unit=f"{grain}s"))
                word = "rose" if direction == "up" else "fell"
                lines.append(f"- [N{n}] {row.get('metric')} {word} in each of the last {run} {grain}s")
                emitted = True
        if emitted:
            trace.append(entry)
    lines = [ln for ln in lines if pace_register_ok(ln)]          # belt: the momentum-class fence, by design
    return lines, trace


def _era_delta(oks: list, row: dict) -> float | None:
    """last_MY_level - first_MY_level over >=2 ordered ok rows (pre-scale applied here for consistency);
    None when <2 usable rows (no within-era delta claimable -> that era cannot seed a fork)."""
    vals = [v for v in (_float_val(r) for r in oks) if v is not None]
    if len(vals) < 2:
        return None
    scale = float(row.get("scale", 1) or 1)
    return (vals[-1] - vals[0]) * scale


def _pct_change(oks: list, row: dict) -> float | None:
    """100*(last-first)/first over the era's ok rows -- injected ALONGSIDE the absolute delta so a percent
    narration ('rose ~18% [N4]') value-checks against a real row (P9/D-B2)."""
    vals = [v for v in (_float_val(r) for r in oks) if v is not None]
    if len(vals) < 2 or vals[0] == 0:
        return None
    return round(100.0 * (vals[-1] - vals[0]) / abs(vals[0]), 2)


def _sign(x: float) -> int:
    return 0 if x == 0 else (1 if x > 0 else -1)


def _divergence(era_deltas: dict, eras: dict, cur: dict | None, row: dict) -> tuple:
    """(divergence?, a, b) -- R2 CROSS-ERA: two eras' within-era deltas; else one era's delta vs the
    era-end -> current level change. Never claims a fork without two comparable signed changes."""
    ds = [era_deltas[i] for i in sorted(era_deltas)]
    if len(ds) >= 2:
        a, b = ds[0], ds[1]
        return (_sign(a) != _sign(b) and _sign(a) != 0 and _sign(b) != 0), a, b
    if len(ds) == 1 and cur and cur.get("status") == "ok":
        cur_v = _float_val(cur)
        last_era = max(eras, key=lambda i: i)
        era_oks = [r for r in eras[last_era] if r.get("status") == "ok"]
        end_v = _float_val(era_oks[-1]) if era_oks else None
        if cur_v is not None and end_v is not None:
            scale = float(row.get("scale", 1) or 1)
            b = (cur_v - end_v) * scale
            a = ds[0]
            return (_sign(a) != _sign(b) and _sign(a) != 0 and _sign(b) != 0), a, b
    return False, 0.0, 0.0


def _endpoint_ok(recs: list) -> dict | None:
    """The LAST (latest-MY / latest-window) ok endpoint record of an era's leg rows, or None."""
    oks = [r for r in (recs or []) if r.get("status") == "ok" and (r.get("rows") or [])]
    return oks[-1] if oks else None


def _endpoint_sortkey(rec: dict) -> str:
    """A chronological sort key for an endpoint record -- the MY int (zero-padded) or the leg's window/asof."""
    my = rec.get("my")
    if my is not None:
        return f"{int(my):04d}"
    q = rec.get("query") or {}
    return str(q.get("asof") or q.get("period") or "")


def _endpoint_label(rec: dict) -> str:
    """The clean human period token for an endpoint ('MY2021' / a date window / 'current')."""
    my = rec.get("my")
    if my is not None:
        return f"MY{my}"
    q = rec.get("query") or {}
    return str(q.get("period") or q.get("asof") or "?")


def _cross_era_diff(era_deltas: dict, eras: dict, cur: dict | None, row: dict) -> tuple | None:
    """(diff_prescaled, period_label, later_rec) -- the CROSS-ERA endpoint LEVEL difference the narration
    cites as a 'gain above the <MY> baseline' (F2 class-1 fix). Two-era -> later era endpoint minus earlier
    era endpoint (an ENDPOINT-LEVEL fact, distinct from the within-era deltas a/b the DIVERGENCE line shows);
    one-era+current -> current level minus the era-end level, sign-identical to _divergence's b BY
    CONSTRUCTION (semantic order, no sortkey swap). The label reads earlier->later and the
    sign is later-minus-baseline. None when either endpoint is missing (the divergence line still renders;
    only the citable row is skipped)."""
    keys = sorted(era_deltas)
    if len(keys) >= 2:
        ea, eb = _endpoint_ok(eras.get(keys[0])), _endpoint_ok(eras.get(keys[1]))
        if ea is None or eb is None:
            return None
        if _endpoint_sortkey(eb) < _endpoint_sortkey(ea):   # two same-key-type era endpoints: order by time
            ea, eb = eb, ea
    elif len(keys) == 1 and cur and cur.get("status") == "ok" and (cur.get("rows") or []):
        last_era = max(eras, key=lambda i: i)
        ea, eb = _endpoint_ok(eras.get(last_era)), cur
        if ea is None:
            return None
        # SEMANTIC order is fixed here -- era endpoint = baseline, current = later -- so the sign is
        # identical to _divergence's b (cur - era_end) BY CONSTRUCTION. No sortkey swap: mixed MY-vs-asof
        # key types could compare current below the era key and silently NEGATE the injected diff.
    else:
        return None
    va, vb = _float_val(ea), _float_val(eb)
    if va is None or vb is None:
        return None
    scale = float(row.get("scale", 1) or 1)
    return (vb - va) * scale, f"{_endpoint_label(ea)}->{_endpoint_label(eb)}", eb


def _fmt_era_diff(row: dict, d: float, n: int, *, period: str) -> str:
    return (f"- [N{n}] cross-era change in {row.get('metric')} ({period}): "
            f"{d:+g} {row.get('narrate_unit') or ''}".rstrip())


def _group_by_node(records: list, kept: list) -> dict:
    """Regroup the flat record list by node_key: era records bucketed by era_idx (ordered by MY), the
    current record separate; each node carries its map row."""
    rows_by_key = {}
    for g in kept:
        key = g["specs"][0]["node_key"] if g["specs"] else None
        if key is not None:
            rows_by_key[key] = g["row"]
    out: dict = {}
    for r in records:
        key = r.get("node_key")
        if key not in rows_by_key:
            continue
        grp = out.setdefault(key, {"row": rows_by_key[key], "eras": {}, "current": None})
        leg = r.get("leg") or ("era", 0)
        if leg[0] == "current":
            grp["current"] = r
        elif leg[0] == "pace":
            grp["pace"] = r          # T2a: consumed by _pace_legs only -- NEVER an era bucket (a pace
            #                          series in era 0 would poison _era_delta with sub-annual points)
        else:
            grp["eras"].setdefault(r.get("era_idx") or 0, []).append(r)
    for grp in out.values():
        for i in grp["eras"]:
            grp["eras"][i].sort(key=lambda r: (r.get("my") is None, r.get("my")))
    return out


def _era_label(era, row: dict | None = None) -> str:
    """Clause B' (thin-turn honesty fix): a HUMAN era label so the render never emits a bare 'era0'/'era1'
    integer. The bare index reads to the model as an uncited claim magnitude, gets mirrored verbatim into
    prose ('(era 0)', 'within-era0 change'), and the verifier then strips the sentence's otherwise-verbatim
    [N] handles with it (the Row-3 false-strip). Emit a marketing-year span when the row carries one, else
    the ordinal words 'earlier era'/'later era' -- never a bare 'era{int}'."""
    if era == "current":
        return "current"
    my = (row or {}).get("my_span") or (row or {}).get("period")
    if my:
        return str(my)
    try:
        idx = int(era)
    except (TypeError, ValueError):
        return "earlier era"
    return "earlier era" if idx == 0 else "later era"


def _fmt_line(rec: dict, row: dict, n: int, *, era) -> str:
    v = _float_val(rec)
    scale = float(row.get("scale", 1) or 1)
    val = f"{v * scale:g}" if v is not None else "?"
    unit = row.get("narrate_unit") or ""
    q = rec.get("query") or {}
    tag = _era_label(era, row)
    return (f"- [N{n}] {q.get('commodity')} {row.get('metric')} {q.get('period') or ''} ({tag}, "
            f"as-of {q.get('asof')}): {val} {unit}".rstrip())


def _fmt_delta(row: dict, d: float, n: int, *, era) -> str:
    return (f"- [N{n}] change within the {_era_label(era, row)} in {row.get('metric')}: "
            f"{d:+g} {row.get('narrate_unit') or ''}".rstrip())


def _fmt_pct(row: dict, pct: float, n: int, *, era) -> str:
    return f"- [N{n}] change within the {_era_label(era, row)} in {row.get('metric')}: {pct:+g} %"


def _fmt_absence(rec: dict) -> str:
    q = rec.get("query") or {}
    what = f"{q.get('commodity')} {q.get('metric')} {q.get('period') or ''}".strip()
    status = rec.get("status")
    if status == "future_unpublished":
        return f"- {what}: not yet in effect as of {q.get('asof')}"
    if status == "not_known":
        return f"- {what}: (vintage not yet published as of {q.get('asof')})"
    if status == "error":
        return f"- {what}: (record unavailable for this hop)"
    return f"- {what}: (record silent for that era)"


def _assemble(records: list, kept: list, base: int, calls: list) -> tuple:
    """Pre-scale + inject endpoint/delta/%-change [N] rows (continue-count), compute per-node CROSS-ERA
    deltas, set the divergence flag on opposite signs, render block lines + trace. Appends to `calls`
    IN PLACE; synthetic delta rows are free (they do not count against CASCADE_CAP). Returns
    (lines, trace, era_deltas_by_key) -- deltas keyed {node_key: {era_idx: delta}} feed the RF-4 reroute
    pass (one caller: quantify)."""
    lines, trace = [], []
    deltas_by_key: dict = {}
    by_node = _group_by_node(records, kept)
    n = base
    for key, grp in by_node.items():
        row = grp["row"]
        eras = grp["eras"]
        cur = grp.get("current")
        era_deltas: dict = {}
        for i, recs in sorted(eras.items()):
            oks = [r for r in recs if r.get("status") == "ok" and (r.get("rows") or [])]
            for r in oks:                                         # inject each MY endpoint level (pre-scaled)
                n += 1
                calls.append(_prescaled(r, row, n))
                lines.append(_fmt_line(r, row, n, era=i))
            for r in recs:
                if r.get("status") and r["status"] != "ok":
                    lines.append(_fmt_absence(r))
            d = _era_delta(oks, row)
            if d is not None:
                era_deltas[i] = d
                n += 1
                calls.append(_delta_call(oks[-1], row, d, n, kind="delta"))
                lines.append(_fmt_delta(row, d, n, era=i))
                pct = _pct_change(oks, row)
                if pct is not None:
                    n += 1
                    calls.append(_delta_call(oks[-1], row, pct, n, kind="pct"))
                    lines.append(_fmt_pct(row, pct, n, era=i))
        if cur and cur.get("status") == "ok" and (cur.get("rows") or []):
            n += 1
            calls.append(_prescaled(cur, row, n))
            lines.append(_fmt_line(cur, row, n, era="current"))
        elif cur:
            lines.append(_fmt_absence(cur))
        div, a, b = _divergence(era_deltas, eras, cur, row)
        if div:
            # F2: inject the CROSS-ERA endpoint difference as a citable [N] row (the 'gain above the MY<yy>
            # baseline' magnitude the engine computes across eras but never injected -- the narration read
            # uncitable). Post-cap like every other delta row (no CASCADE_CAP effect); only when div fired
            # (no row bloat on same-sign nodes). The handle rides ONLY the cross-era line whose value the
            # row actually backs -- NOT the DIVERGENCE line, whose visible numbers are the within-era
            # deltas a/b: a model echoing '+4 vs -4 [Nx]' against an endpoint-diff row of +2 would strip
            # as number_mismatch, reintroducing the exact strip F2 exists to prevent.
            ced = _cross_era_diff(era_deltas, eras, cur, row)
            if ced is not None:
                diff, period_lbl, later_rec = ced
                n += 1
                calls.append(_delta_call(later_rec, row, diff, n, kind="era_diff", period=period_lbl))
                lines.append(_fmt_era_diff(row, diff, n, period=period_lbl))
            lines.append(f"DIVERGENCE on {row.get('metric')}: {a:+g} vs {b:+g} "
                         f"({row.get('narrate_unit') or ''}) "
                         f"-- render '## Where the record disagrees' and show BOTH eras; do not blend.")
        trace.append({"node_key": list(key) if isinstance(key, tuple) else key, "metric": row.get("metric"),
                      "era_statuses": {i: [r.get("status") for r in recs] for i, recs in eras.items()},
                      "current_status": (cur or {}).get("status"), "divergence": div})
        deltas_by_key[key] = era_deltas
    return lines, trace, deltas_by_key


def _reroute(pairs: list, deltas_by_key: dict) -> tuple:
    """RF-4: the cross-country fork. For each candidate pair, compare the two legs' within-era deltas
    over each SHARED anchor window; fire IFF both deltas exist and their signs OPPOSE. A leg whose era
    rows did not resolve (the probe-pinned foreign vintage lag: not_known until the next PSD release;
    record_silent; <2 ok rows) has NO delta -> the pair DECLINES -- honest absence, never a guessed fork.
    FIRED pairs only reach the trace: a same-sign pair records NOTHING (a recorded candidate would
    legitimize a hallucinated heading at the eval fork gate). Both legs' delta rows are already injected
    via _delta_call by _assemble (the beneficiary is a full kept group), so both narrated magnitudes
    value-check against the all-numbers guard."""
    lines, trace = [], []
    for p in pairs:
        da_by = deltas_by_key.get(p["a_key"]) or {}
        db_by = deltas_by_key.get(p["b_key"]) or {}
        metric = p["metricA"] if p["metricA"] == p["metricB"] else f"{p['metricA']}/{p['metricB']}"
        unit = p["row"].get("narrate_unit") or ""
        for ia, ib, span in p["eras"]:
            da, db = da_by.get(ia), db_by.get(ib)
            if da is None or db is None or _sign(da) == 0 or _sign(db) == 0 or _sign(da) == _sign(db):
                continue
            window = f"MY{span[0]}-MY{span[-1]}"
            lines.append(f"REROUTE on {metric}: {p['countryA']} {da:+g} vs {p['countryB']} {db:+g} "
                         f"({unit}) over {window} -- render '## Where the record disagrees' and show "
                         f"BOTH legs BY COUNTRY; the flow rerouted, do not blend.")
            trace.append({"contract": p["contract"], "metric": metric, "countryA": p["countryA"],
                          "dA": da, "countryB": p["countryB"], "dB": db, "window": window,
                          "reroute": True})
    return lines, trace


# ── RV-W2: cross-COMMODITY relative-value fork (reroute v2) ─────────────────────────────────────────────
# One event, two commodities, opposing balance-sheet legs: whose World stocks-to-use tightens RELATIVE to
# whose -- measured on su_ratio, WORLD basis, each leg on its OWN marketing year. The cross-COMMODITY cousin
# of _reroute's cross-COUNTRY fork ("the flow found a new door" -> "the shock found a second balance sheet").
# NOT a trading system (no long/short/spread/basis/price): the engine NEVER reads price/feature tables
# (the D1/D6 fence; crush_margin_z was struck -- C19). The engine is gated ONLY by the xc_request kwarg the
# orchestrator threads at the answer.py seam (the env flag is checked THERE, never here -- cascade's own
# discipline): xc_request None => this whole path is inert and the v1 return is byte-identical.
#
# World is SYNTHESIZED, not fetched: silver_psd has NO literal country="World" row (the 2026-07-18 probe P1
# refuted the plan body's assumption). su_ratio-World == Recipe-B total-use synthesis:
# SUM(ending_stocks_mt)/SUM(consumption_mt) over EACH COUNTRY'S OWN LATEST release_date <= asof (the
# per-country-latest union -- PSD vintages are DELTAS, so no single shared vintage exists; see
# _world_su_ratio), pre-scaled x100 to narrate '%'.
_XC_SU_STOCKS = "ending_stocks_mt"
_XC_SU_USE = "consumption_mt"

# ── EU membership-window dedup (the 2026-07-20 UK-backfill fix; SINGLE SOURCE, census imports these) ────
# USDA PSD backfills INDIVIDUAL member rows for marketing years the EU aggregate ALSO covers (live case:
# 'United Kingdom' rows for MY2016-2019 while the EU-28 aggregate for those same MYs still includes the UK).
# A naive cross-country World SUM would double-count such a member. The ratified design (REROUTE_V2_RV_PLAN
# addendum): membership WINDOWS make the SUM disjoint BY CONSTRUCTION -- a member's individual rows are
# EXCLUDED from the World SUM for exactly the marketing years the member is inside the EU aggregate (the
# aggregate row already carries its tonnage). These tables lived in cascade_census; they moved HERE so the
# engine SUM (`_world_su_ratio`) and the census lint (`_era_disjoint`) read ONE table and cannot drift
# (census imports cascade; the reverse import would be circular).
EU_AGGREGATE_TITLES = frozenset({"European Union", "EU-15", "EU-27", "EU-28"})
# Historically-tracked EU member-state titles (silver_psd surface form). Not exhaustive of every micro-state
# -- it is a double-count TRIPWIRE, and the members that actually carry veg-oil/grain balance sheets are the
# ones that could overlap an aggregate row. Both spellings of the pre-reunification German title are kept.
EU_MEMBER_TITLES = frozenset({
    "France", "Germany", "Germany, West", "W. Germany", "West Germany", "Italy", "Spain",
    "United Kingdom", "Netherlands", "Poland", "Romania", "Belgium-Luxembourg", "Belgium", "Luxembourg",
    "Denmark", "Ireland", "Greece", "Portugal", "Hungary", "Czech Republic", "Slovakia", "Austria",
    "Sweden", "Finland", "Bulgaria", "Croatia", "Lithuania", "Latvia", "Estonia", "Slovenia", "Cyprus",
    "Malta",
})
# EU (and predecessor EEC/EC) membership as PSD market-year WINDOWS: a member's balance sheet is rolled INTO
# the 'European Union'/'EU-*' aggregate ONLY for accession_my <= market_year < exit_my (exit EXCLUSIVE, None
# = still a member). OUTSIDE that window a country reported individually is NOT double-counted: (a) post-Brexit
# UK, reported separately from MY2020/21 while the EU aggregate (now sans UK) continues; (b) accession states
# reported individually BEFORE they joined. Members ABSENT from this dict (the pre-EU-15 founders) are NEVER
# deduped by `eu_member_deduped` -- an actual overlap for them stays a census DARK (fail-closed), because
# silently guessing their window could just as easily UNDER-count.
EU_MEMBERSHIP: dict[str, tuple[int, int | None]] = {
    "United Kingdom": (1973, 2020),          # left the EU; PSD reports it separately from MY2020/21
    "Ireland": (1973, None), "Denmark": (1973, None),
    "Greece": (1981, None),
    "Spain": (1986, None), "Portugal": (1986, None),
    "Austria": (1995, None), "Sweden": (1995, None), "Finland": (1995, None),
    "Poland": (2004, None), "Czech Republic": (2004, None), "Slovakia": (2004, None),
    "Hungary": (2004, None), "Slovenia": (2004, None), "Estonia": (2004, None),
    "Latvia": (2004, None), "Lithuania": (2004, None), "Cyprus": (2004, None), "Malta": (2004, None),
    "Bulgaria": (2007, None), "Romania": (2007, None),
    "Croatia": (2013, None),
}
EU_MEMBERSHIP_DEFAULT = (0, None)


def _in_eu_aggregate(country: str, year: int) -> bool:
    """Is `country`'s tonnage rolled into the EU aggregate in market-year `year`? (accession<=year<exit).
    Unlisted members default to "always inside" -- the CONSERVATIVE reading the census lint wants (flags a
    genuine future double count); the dedup itself never trusts this default (see eu_member_deduped)."""
    acc, ex = EU_MEMBERSHIP.get(country, EU_MEMBERSHIP_DEFAULT)
    return year >= acc and (ex is None or year < ex)


def eu_member_deduped(country, my, *, aggregate_present: bool) -> bool:
    """THE dedup rule, shared by the engine World SUM and the census lint's reasoning: must `country`'s
    INDIVIDUAL row be EXCLUDED from a World-basis SUM for marketing year `my`? True iff an EU aggregate row
    is present in the same per-country-latest set (it already carries the member -- without one, exclusion
    would UNDER-count, e.g. pre-1991 eras where members are reported ONLY individually) AND the member
    has an EXPLICIT membership window it is inside for `my`. A member title WITHOUT an explicit window entry
    is never deduped here -- the census era-overlap lint DARKs such an overlap instead (fail-closed)."""
    if not aggregate_present or country is None or my is None:
        return False
    c = str(country)
    if c not in EU_MEMBERSHIP:                                  # no curated window -> never silently dropped
        return False
    acc, ex = EU_MEMBERSHIP[c]
    y = int(my)
    return y >= acc and (ex is None or y < ex)


def _as_float(v) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _release_of(row: dict) -> str | None:
    """The PSD publication vintage of a fetched row: silver stores it as 'release_date', Q.run's SELECT aliases
    it to 'knowledge_date' -- read either so per-country-latest selection works on live rows AND test fixtures."""
    for k in ("release_date", "knowledge_date"):
        v = (row or {}).get(k)
        if v:
            return str(v)
    return None


def _psd_component_rows(qfn, slug: str, metric: str, my: int, asof) -> list:
    """PIT-safe per-country rows for a WIDE-PSD component metric at (slug, MY), as-known at asof: country=None
    -> every country's latest vintage <= asof, via the SAME keyed fetch_window path a cascade leg uses (same
    as-of guard, same sargable-partition discipline). Never raises (fetch_window degrades to rows=[])."""
    rec = fetch_window(qfn, table="silver_psd", metric=metric, commodity=slug, country=None,
                       t1=None, t2=None, asof=asof, agg="series", period=my, period_type="marketing_year")
    return rec.get("rows") or []


def _world_su_ratio(qfn, slug: str, my: int, asof) -> tuple | None:
    """Recipe-B World stocks-to-use for (slug, MY) as a pre-scaled '%': SUM(ending_stocks_mt)/SUM(consumption_mt)
    over EACH COUNTRY'S OWN LATEST vintage <= asof (the per-country-latest union; no literal country='World'
    row exists), with the EU membership-window DEDUP: when an EU aggregate title is present in the
    per-country-latest set for a metric, a member's individual row is EXCLUDED for marketing years the member
    is inside the aggregate per EU_MEMBERSHIP (the aggregate already carries it -- the backfilled-UK
    double-count fix).

    WHY per-country-latest, NOT a single release_date (the 2026-07-20 delta-vintage fix): the addendum-P1
    rule ("sum only rows at the single latest release_date; NEVER sum across vintages") assumed PSD releases
    are FULL-MATRIX -- every country reprinted each month. They are not: PSD vintages are DELTAS, each
    monthly release_date carries ONLY the countries whose numbers changed (probed live 2026-07-20 on
    malaysian_crude_palm_oil_cme MY2024 ending_stocks_mt: releases carried n=30, 40, 5, 2, then a single
    zero 'Other' placeholder row). Under the old rows-at-max-release lock every output was a revision
    SUBSET mislabeled as World (palm MY2024 read 0.00% from that one placeholder row; MY2023 read Ecuador
    alone). World-as-known-at-asof = each country's OWN latest row <= asof: every row is individually
    PIT-safe, a country's vintages are never mixed WITH EACH OTHER, and the cross-country set INTENTIONALLY
    spans release dates -- that is exactly what "as known now" means. This is also the arithmetic the census
    existence probe already runs (_world_synth_nonempty rides build_sql agg=sum/country=None, which sums the
    same per-country-latest set), so engine and census are coherent by construction.

    Returns (ratio_pct, release_date, n_countries) or None (missing component / empty sum / zero use -> the
    leg declines honestly). release_date is the MAX release across the summed rows -- an as-of FRESHNESS
    STAMP for the citation, NOT a claim that every summed row came from that vintage."""
    st = _psd_component_rows(qfn, slug, _XC_SU_STOCKS, my, asof)
    us = _psd_component_rows(qfn, slug, _XC_SU_USE, my, asof)
    if not st or not us:
        return None

    def _latest_per_country(rows: list) -> dict:
        """{country: (row, release)} -- each country's OWN latest stamped vintage. The live SQL already
        collapses to one row per country (ROW_NUMBER over group_cols ORDER BY release_date DESC, _rn=1), so
        this is a pass-through there; an injected qfn (tests, cache wrappers) may hand back raw multi-vintage
        rows, so latest-wins is enforced here too. Unstamped rows (no release) drop -- fail closed, mirroring
        apply_pit_filter's NULL-knowledge-date rule. First-seen wins a same-release tie (idempotent)."""
        best: dict = {}
        for r in rows:
            c, rd = r.get("country"), _release_of(r)
            if c is None or rd is None:
                continue
            prev = best.get(c)
            if prev is None or rd > prev[1]:
                best[c] = (r, rd)
        return best

    def _sum_latest(rows: list) -> tuple:
        latest = _latest_per_country(rows)
        # aggregate_present demands a NUMERIC aggregate value, not mere row presence: a NULL-valued EU row
        # carries NO member tonnage, so deduping against it would DROP the member from the sum outright
        # (skeptic probe T3, 2026-07-20) -- and split the engine from the census existence probe, whose
        # SQL sum(value) ignores NULLs and keeps the member.
        agg_present = any(str(c) in EU_AGGREGATE_TITLES and _as_float(r.get("value")) is not None
                          for c, (r, _rd) in latest.items())
        tot, n, mx = 0.0, 0, None
        for c, (r, rd) in latest.items():
            if eu_member_deduped(c, my, aggregate_present=agg_present):
                continue                                        # inside the EU aggregate this MY: already counted
            v = _as_float(r.get("value"))
            if v is None:
                continue
            tot, n = tot + v, n + 1
            if mx is None or rd > mx:
                mx = rd
        return tot, n, mx

    s_tot, s_n, s_rd = _sum_latest(st)
    u_tot, u_n, u_rd = _sum_latest(us)
    if s_n == 0 or u_n == 0 or u_tot == 0:
        return None
    rd = max(x for x in (s_rd, u_rd) if x is not None)           # freshness stamp over the summed set
    return (100.0 * s_tot / u_tot, rd, min(s_n, u_n))


def _leg_world_deltas(qfn, slug: str, windows: list, asof) -> dict:
    """Per focus-window index: the WITHIN-window World su_ratio change (last-MY % minus first-MY %) computed on
    the LEG'S OWN marketing year (index-aligned eras, C4: each leg its own MY span, keyed by era_idx so the
    two legs align regardless of MY-int divergence -- NOT _shared_eras, which returns EMPTY on differing MY
    starts, engine F4). Only an era with >=2 resolved World ratios yields a delta; else the era declines.
    Returns {era_idx: {'d': delta_pp, 'a': (my, pct, rd), 'b': (my, pct, rd)}}."""
    out: dict = {}
    for i, w in enumerate(windows or []):
        pts = []
        for my in _my_span(w, slug):                            # widened to >=2 MYs so a within-era delta exists
            wr = _world_su_ratio(qfn, slug, my, asof)
            if wr is not None:
                pts.append((my, wr[0], wr[1]))
        if len(pts) >= 2:
            a, b = pts[0], pts[-1]
            out[i] = {"d": b[1] - a[1], "a": a, "b": b}
    return out


def _xc_label(slug: str) -> str:
    """A reader-facing World-basis commodity label. soft_red_winter_wheat_cbot fans to PSD code 410000 = the
    ALL-CLASS wheat aggregate at World, so it is labeled 'world wheat (all classes)', never 'soft red winter'
    (C20 -- never misrepresent an all-wheat number as SRW)."""
    s = (slug or "").lower()
    if "wheat" in s:
        return "world wheat (all classes)"
    for suf in ("_cbot", "_cme", "_zce", "_dce", "_matif"):
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    return "world " + s.replace("_", " ")


def _shared_event_matched(sg, shared_event) -> bool:
    """True IFF the pair's curated shared_event driver was route-matched in THIS turn's walk. C20 mitigation for
    feed_grain: the engine has NO other runtime signal for WHICH curated edge (feed substitution vs export/
    acreage) drove the divergence, so absent a match it narrates GENERICALLY. Best-effort + exception-safe --
    a miss just yields the generic frame, never a raise."""
    tok = str(shared_event or "").strip().lower()
    if not tok:
        return False
    try:
        for n in getattr(sg, "nodes", None) or []:
            if tok in str(getattr(n, "id", "") or "").lower():
                return True
            prior = getattr(n, "prior", None) or {}
            if any(tok in str(v).lower() for v in prior.values()):
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _xc_frame(pair_row, sg) -> str:
    """The narration frame directive, selected BY COMPLEX (RV-W2.4). soy_crush takes the joint-product path
    (a co-move is not a story; only DEMAND divergence opposes -- oil_share stays qualitative prose, there is no
    crush_margin_z serving metric); feed_grain narrates generically unless its shared_event route-matched this
    turn (C20); substitution complexes narrate the second-balance-sheet substitution."""
    complex_name = str(getattr(pair_row, "complex_name", "") or "")
    if complex_name == "soy_crush":
        return ("the crush shifted toward one product on DEMAND (meal and oil are JOINT products co-produced on "
                "the supply side, so a co-move is not a relative-value story; only a demand divergence opposes)")
    if complex_name == "feed_grain":
        if _shared_event_matched(sg, getattr(pair_row, "shared_event", None)):
            return "the relative feed-grain balance shifted (feed-ration substitution)"
        return "the relative feed-grain balance shifted"        # generic: no runtime signal for WHICH edge (C20)
    return "the shock reached a second balance sheet; one tightened as the other loosened (substitution)"


def _xc_call(commodity: str, value: float, my: int, asof, *, unit: str = "%") -> dict:
    """A synthetic call-record so a narrated v2 su_ratio/delta magnitude IS a citable, value-checkable row (the
    _delta_call discipline; both legs' rows are injected so the all-numbers strip guard backs every magnitude).
    No _provenance -- a World figure is a cross-country synthesis, not one source row."""
    return {"query": {"commodity": commodity, "metric": "su_ratio_world",
                      "period": (f"MY{my}" if my is not None else None), "asof": asof},
            "rows": [{"value": round(float(value), 4), "unit": unit}], "status": "ok"}


def _xc_sides_ok(pair_row, source: str, target: str) -> bool:
    """Fail-closed guard: the pair is `material` AND both curated legs are su_ratio-World sides whose contracts
    are EXACTLY {source, target}. Any drift (wrong tier, a leg off the pair, a non-world country_rule) declines
    the whole fork -- never a guessed comparison."""
    try:
        if getattr(pair_row, "materiality_tier", None) != "material":
            return False
        sides = [getattr(pair_row, "side_a", None) or {}, getattr(pair_row, "side_b", None) or {}]
        if {(s.get("contract") or "") for s in sides} != {source, target}:
            return False
        return all((s.get("country_rule") or "") == "world" for s in sides)
    except Exception:  # noqa: BLE001
        return False


def _xc_leg_lines(la, source, A, lb, target, B, calls: list, base: int, asof) -> tuple:
    """The per-leg composite [N] line shape shared by the divergence (opposite-sign) and co-move (same-sign)
    renders. For each leg it emits one reader line and injects THREE citable rows -- endpoint + baseline +
    delta -- so every narrated magnitude value-checks against the all-numbers guard (the RV-W3.2 discipline).
    Returns (lines, ((mya0,pa0,mya1,pa1),(myb0,pb0,myb1,pb1))) -- the caller builds its own marker line + trace
    from the endpoints. BYTE-IDENTICAL to the historical inline loop: the divergence output must not shift."""
    (mya0, pa0, _rda0), (mya1, pa1, _rda1) = A["a"], A["b"]
    (myb0, pb0, _rdb0), (myb1, pb1, _rdb1) = B["a"], B["b"]
    n = base
    lines: list = []
    for (lbl, cmdty, my_lo, p_lo, my_hi, p_hi, d) in (
            (la, source, mya0, pa0, mya1, pa1, A["d"]),
            (lb, target, myb0, pb0, myb1, pb1, B["d"])):
        n += 1
        handle = n
        calls.append(_xc_call(cmdty, p_hi, my_hi, asof))        # the endpoint the [N{handle}] line cites
        n += 1
        calls.append(_xc_call(cmdty, p_lo, my_lo, asof))        # the baseline (backs the '(vs MY.. ..%)' term)
        n += 1
        calls.append(_xc_call(cmdty, d, my_hi, asof, unit="pp"))    # the delta (backs the '..pp' term)
        lines.append(f"- [N{handle}] {lbl} stocks-to-use MY{my_hi}: {p_hi:g}% "
                     f"(vs MY{my_lo} {p_lo:g}%, {d:+g}pp over the window)")
    return lines, ((mya0, pa0, mya1, pa1), (myb0, pb0, myb1, pb1))


def _reroute_xc(pair_row, source: str, target: str, focus_windows: list, qfn, asof,
                calls: list, base: int, sg, comove: bool = False) -> tuple:
    """The ratio-delta fork, labeled BY COMMODITY (RV-W2.3). BOTH legs are SYNTHESIZED World su_ratio legs over
    the SAME focus-window eras (Invariant 4 -- the shared window is FORCED, no second walk, no sibling
    retrieval), each on its OWN marketing year (C4).

    [SKEPTIC F1 -- HIGH] TWO-PASS. Opposite-sign (DIVERGENCE) candidates keep ABSOLUTE first-fire priority: the
    loop scans ALL index-aligned eras and the FIRST era whose within-window signs OPPOSE (one tightens while the
    other loosens -- the reused _reroute L852 sign test) fires the divergence fork and returns immediately
    (PAIR_CAP=1), BYTE-IDENTICAL to the pre-co-move engine. A same-sign co-move is only NOTED during the scan and
    rendered AFTER the scan proves NO era diverged -- so a lower-idx co-move can never PREEMPT a divergence that
    renders today. The co-move render exists ONLY when `comove` is True (the kwarg the answer.py/orchestrator
    seam threads from GRAPHRAG_COMOVE -- [SKEPTIC F3], NEVER an env read here); when False the same-sign eras
    drop exactly as before, so opposite-sign output is byte-identical flag-off AND flag-on. A flat/no-delta leg
    (sign 0) is neither divergence nor co-move -> honest continue. A missing within-window delta on EITHER leg
    excludes that era from the intersection (never reaches this loop). On fire, inject both legs' endpoint +
    baseline + delta [N] rows (value-checkable) and return (block_lines, fired_trace); ([], None) otherwise. The
    co-move render uses its OWN CO-MOVE marker -> '## Complex-wide move' (never '## Cross-commodity', which
    asserts a relative-value divergence and licenses price-direction -- both FALSE for a co-move). Never raises."""
    if not _xc_sides_ok(pair_row, source, target):
        return [], None
    da_by = _leg_world_deltas(qfn, source, focus_windows, asof)
    db_by = _leg_world_deltas(qfn, target, focus_windows, asof)
    la, lb = _xc_label(source), _xc_label(target)
    comove_idx = None                                           # first true same-sign era, deferred to pass 2
    for i in sorted(set(da_by) & set(db_by)):                   # index-aligned eras: same era_idx on both legs
        A, B = da_by[i], db_by[i]
        sa, sb = _sign(A["d"]), _sign(B["d"])
        if sa == 0 or sb == 0:
            continue                                            # a flat/no-delta leg -> never a co-move (honest)
        if sa == sb:                                            # a TRUE same-sign co-move (both real moves)
            if comove_idx is None:
                comove_idx = i                                  # record the FIRST; render only if no era diverges
            continue
        # OPPOSITE-SIGN divergence -- the RV fork. First-fire priority: render + return here (byte-identical).
        lines, ((mya0, pa0, mya1, pa1), (myb0, pb0, myb1, pb1)) = _xc_leg_lines(
            la, source, A, lb, target, B, calls, base, asof)
        window = f"MY{mya0}-MY{mya1}"
        lines.append(
            f"CROSS-COMMODITY on su_ratio: {la} {pa1:g}% ({A['d']:+g}pp) vs {lb} {pb1:g}% ({B['d']:+g}pp) "
            f"over {window} -- {_xc_frame(pair_row, sg)}; each World balance sheet aggregates DIFFERING local "
            f"marketing years, so the comparison holds at the marketing-year grain, not a shared calendar; "
            f"render '## Cross-commodity', labeled BY COMMODITY.")
        fired = {"pair_id": getattr(pair_row, "id", None), "complex": getattr(pair_row, "complex_name", None),
                 "commodityA": source, "dA": round(A["d"], 4), "su_ratio_A": round(pa1, 4), "myA": mya1,
                 "commodityB": target, "dB": round(B["d"], 4), "su_ratio_B": round(pb1, 4), "myB": myb1,
                 "window": window, "reroute_v2": True}
        return lines, fired
    # PASS 2 -- co-move. No era diverged. Render the FIRST same-sign co-move ONLY when the flag is on, in its OWN
    # '## Complex-wide move' section via the CO-MOVE marker.
    if comove and comove_idx is not None:
        A, B = da_by[comove_idx], db_by[comove_idx]
        lines, ((mya0, pa0, mya1, pa1), (myb0, pb0, myb1, pb1)) = _xc_leg_lines(
            la, source, A, lb, target, B, calls, base, asof)
        window = f"MY{mya0}-MY{mya1}"
        verb = "tightened" if _sign(A["d"]) < 0 else "loosened"    # SAFE frame word (in no lexicon); same sign
        # SAFEST frame text (the plan's literal shape): su_ratio percentages + tightened/loosened only, NO
        # valuation adjectives, NO price-direction -- a complex-wide move, not a relative-value divergence.
        lines.append(
            f"CO-MOVE on su_ratio: both {la} and {lb} {verb} (stocks-to-use {pa0:g}%->{pa1:g}% and "
            f"{pb0:g}%->{pb1:g}%) -- a complex-wide move, not a relative-value divergence, over {window}; each "
            f"World balance sheet aggregates DIFFERING local marketing years, so the comparison holds at the "
            f"marketing-year grain, not a shared calendar; render '## Complex-wide move', labeled BY COMMODITY "
            f"on su_ratio percentages only.")
        fired = {"pair_id": getattr(pair_row, "id", None), "complex": getattr(pair_row, "complex_name", None),
                 "commodityA": source, "dA": round(A["d"], 4), "su_ratio_A": round(pa1, 4), "myA": mya1,
                 "commodityB": target, "dB": round(B["d"], 4), "su_ratio_B": round(pb1, 4), "myB": myb1,
                 "window": window, "comove": True}
        return lines, fired
    return [], None


def _slug_match(a, b) -> bool:
    if not a or not b:
        return False
    a, b = str(a), str(b)
    return a == b or PSD_SLUG_ALIAS.get(a, a) == b or a == PSD_SLUG_ALIAS.get(b, b)


def _xc_focus_windows(sg, graph, groups: list, source: str, near, asof) -> list:
    """The FOCUS event's own derived era windows -- reused for BOTH v2 legs so the shared window is FORCED by
    construction (Invariant 4; no second _derive_windows). Prefer an already-built focus group's eras; else
    derive from the grounded source node directly (the source may be grounded without a mapped su_ratio ref)."""
    for g in groups or []:
        # skip era-less groups (a pace-on `leg_mode: current` node carries eras=[] by design -- P4): an
        # empty match here would silently shadow a later era-bearing group for the same slug.
        if _slug_match(g.get("commodity"), source) and g.get("eras"):
            return g["eras"]
    try:
        for n in _select_nodes(sg, graph):
            c = getattr(n, "contract", None)
            if _slug_match(c, source):
                w = _derive_windows(n, near, asof)
                if w:
                    return w
    except Exception:  # noqa: BLE001
        return []
    return []


def _load_pair_row(pair_id: str):
    """The curated complex_map pair (lane A's load_complex_map()); None on any failure (missing file, unknown
    id, a non-material row the loader dropped) -> the fork declines. Imported lazily so the engine never hard-
    depends on the v2 config existing."""
    try:
        from leviathan.graphrag.complex_map import load_complex_map
        cm = load_complex_map()
        for p in getattr(cm, "pairs", None) or []:
            if getattr(p, "id", None) == pair_id:
                return p
    except Exception:  # noqa: BLE001
        return None
    return None


def _run_xc(xc_request: dict, sg, graph, groups: list, qfn, asof, near, calls: list,
            *, comove: bool = False) -> tuple:
    """Resolve the curated pair + the focus window, then run the ratio-delta fork. Returns (block_lines,
    fired_trace) -- ([], None) on ANY decline/failure so v2 NEVER breaks the v1 answer (fail-closed). `comove`
    ([SKEPTIC F3], threaded from the answer.py seam, never an env read) rides into _reroute_xc: when True a
    pure same-sign complex-wide move may render (its OWN CO-MOVE marker); opposite-sign output is unaffected."""
    try:
        pair_id = (xc_request or {}).get("pair_id")
        source = (xc_request or {}).get("source_slug")
        target = (xc_request or {}).get("target_slug")
        if not (pair_id and source and target) or source == target:
            return [], None
        pair_row = _load_pair_row(pair_id)
        if pair_row is None:
            return [], None
        windows = _xc_focus_windows(sg, graph, groups, source, near, asof)
        if not windows:
            return [], None
        # comove passed POSITIONALLY (not keyword): the gate-test stub replaces _reroute_xc with a lambda that
        # only accepts positional *a, so a keyword here would raise -> fail-closed swallow. Positional rides in.
        block, fired = _reroute_xc(pair_row, source, target, windows, qfn, asof, calls, len(calls), sg, comove)
        if fired:
            # RV2 W2 tier telemetry (D7, S2-2): the fired trace records the DETECTING tier HERE, after the
            # call -- _reroute_xc has no xc_request in scope. A 3-key request (legacy/injected) reads None;
            # the engine itself still consumes only pair_id/source/target, so the key rides inert.
            fired["detect_tier"] = (xc_request or {}).get("detect_tier")
        return block, fired
    except Exception:  # noqa: BLE001
        return [], None


# ── SEAM B: F2 price-response leg (Alternative B) ─────────────────────────────────────────────────────
# A settled US season-average FARM-price pair ($X -> $Y) for the FOCUS contract over its analogue marketing
# years, synthesized PARALLEL to _run_xc (its own [N] minting via the _xc_call pattern), NOT a _node_specs
# leg mode. Bypasses _cross_era_diff/_divergence BY CONSTRUCTION: no driver carries silver_ref=price_response,
# so the focus node never enters groups/kept/flat/_assemble -- the pair is minted inline here, exactly the
# _reroute_xc precedent. Fetched at the SESSION asof so the vintage-collapse returns the realized ACTUAL, not
# the as-known-then PROJECTION an era-leg asof (window-end) would return (SEAM_B_LEG_SPEC section 1/6.8).

# focus-contract -> BARE WASDE commodity for avg_farm_price. avg_farm_price is keyed by bare commodity + region
# (tables.yaml), NOT the PSD exchange slug. All-class wheat: SRW/KC/spring all map to 'wheat' (a single
# all-class series -- never labeled SRW, the _xc_label all-class rule). soybean_oil_cbot/soybean_meal_cbot are
# ABSENT (Decatur MARKET price, not farm-gate); coffee/cocoa/sugar and every non-US contract are ABSENT (no US
# farm series) -> _farm_wasde returns None -> the leg declines honestly.
_PRICE_FOCUS_WASDE = {
    "corn": "corn", "corn_cbot": "corn",
    "soybeans": "soybeans", "soybeans_cbot": "soybeans",
    "soft_red_winter_wheat_cbot": "wheat", "hard_red_winter_wheat_kcbt": "wheat",
    "hard_red_spring_wheat_mgex": "wheat",
    "rough_rice_cbot": "rice", "rough_rice": "rice",
    "cotton": "cotton",
}


def _farm_wasde(focus_contract: str) -> str | None:
    """The BARE WASDE commodity for avg_farm_price, or None (-> NO price leg: an honest decline for a market-
    price contract like soybean_oil/meal, a non-US contract, or any non-farm-gate slug)."""
    return _PRICE_FOCUS_WASDE.get((focus_contract or "").strip().lower())


def _farm_region(commodity: str, my: int) -> str:
    """The avg_farm_price region for (commodity, MY). Cotton's US farm price lives under region 'u_s_cotton'
    before the 2011-09 break and 'united_states' after (tables.yaml -- a REAL split). The metric's row_filter
    already WIDENS the SQL to region IN ('u_s_cotton','united_states'), so this governs the per-MY CITATION
    attribution, not the scope. Every other commodity: united_states."""
    if commodity == "cotton" and my is not None and int(my) < 2011:
        return "u_s_cotton"
    return "united_states"


def _fmt_price(value: float, unit: str) -> str:
    """Reader-facing price token: '$/bu'->'$3.60/bu', '$/cwt'->'$14.40/cwt', 'c/lb'->'68.09c/lb'; blank/other
    -> '<val> <unit>'. The numeral value-checks against the injected row within verify._num_backed's 1%
    tolerance, so 2-dp display over a 4-dp stored value is safe."""
    s = f"{value:.2f}"
    u = (unit or "").strip()
    if u.startswith("$/"):
        return f"${s}/{u[2:]}"
    if u == "c/lb":
        return f"{s}c/lb"
    return f"{s} {u}".strip()


def _price_call(commodity: str, region: str, value: float, my_label: str, asof, *, unit: str) -> dict:
    """A synthetic silver_wasde call-record so a narrated farm-price LEVEL IS a citable, value-checkable [N]
    row (the _xc_call discipline). [SKEPTIC F6]: `unit` is an EXPLICIT param sourced from the FETCHED row's
    _apply_unit_overrides value (rows[0]['unit']), NEVER narrate_unit -- confining the unit fallback to the two
    price-leg call sites so _fmt_line/_delta_call stay UNTOUCHED. `table` rides the query so the citation
    locator carries table=silver_wasde (the eval price_cited / unit_present filter keys on it)."""
    return {"query": {"table": "silver_wasde", "metric": "avg_farm_price", "commodity": commodity,
                      "country": region, "period": f"MY{my_label}", "asof": asof},
            "rows": [{"value": round(float(value), 4), "unit": unit}], "status": "ok"}


def _price_pair(price_request: dict, sg, graph, groups: list, qfn, asof, near, calls: list, base: int) -> tuple:
    """SEAM B synthesis. The settled US farm-price consequence pair for the FOCUS contract over its nearest
    analogue-era window's MY span. Returns (block_lines, fired) -- ([], None) on ANY honest decline: no map
    (market-price/non-US slug), no derived focus window, <2 MYs, or either endpoint not status=='ok' (PAIR-
    ATOMIC -- both settle or the whole pair declines, the _beneficiary keep-both-or-drop-both discipline at
    fetch time). At most ONE pair, the single focus contract, <=2 extra fetches (it cannot multiply across
    nodes). SESSION asof on both specs -> vintage-collapse returns the realized ACTUAL. Never raises (fail-
    closed: a price-leg failure must never break the v1 answer)."""
    try:
        focus = (price_request or {}).get("focus_contract")
        if not focus:
            return [], None
        commodity = _farm_wasde(focus)
        if commodity is None:
            return [], None                                       # market-price / non-US / non-farm slug: NO leg
        windows = _xc_focus_windows(sg, graph, groups, focus, near, asof)   # Invariant-4 shared window, no 2nd walk
        if not windows:
            return [], None
        span = _my_span(windows[0], focus)                        # nearest window; focus slug -> correct MY_START
        if len(span) < 2:
            return [], None
        my_a, my_b = span[0], span[-1]
        specs = []
        for my in (my_a, my_b):
            specs.append({"table": "silver_wasde", "metric": "avg_farm_price", "commodity": commodity,
                          "country": _farm_region(commodity, my), "period_type": "marketing_year", "my": my,
                          "period": _my_slash(my), "agg": "latest", "asof": asof, "t1": None, "t2": None,
                          "node_key": None, "leg": ("price", None), "era_idx": None})
        recs = [_run_one(qfn, s) for s in specs]                  # 2 fetches at SESSION asof (settled actual)
        if any(r.get("status") != "ok" for r in recs):
            return [], None                                       # pair-atomic: both settle or the pair declines
        p_a, p_b = _float_val(recs[0]), _float_val(recs[1])
        if p_a is None or p_b is None:
            return [], None
        u_a = ((recs[0].get("rows") or [{}])[0].get("unit")) or ""   # the _apply_unit_overrides fetched unit (F6)
        u_b = ((recs[1].get("rows") or [{}])[0].get("unit")) or ""
        lab_a, lab_b = _my_slash(my_a), _my_slash(my_b)
        reg_a, reg_b = _farm_region(commodity, my_a), _farm_region(commodity, my_b)
        n = base
        n += 1
        h_a = n
        calls.append(_price_call(commodity, reg_a, p_a, lab_a, asof, unit=u_a))   # [N{h_a}] baseline-MY level
        n += 1
        h_b = n
        calls.append(_price_call(commodity, reg_b, p_b, lab_b, asof, unit=u_b))   # [N{h_b}] event-MY level
        label = "US wheat farm price (all classes)" if commodity == "wheat" else f"US {commodity} farm price"
        verb = "rose from" if p_b >= p_a else "fell from"         # direction is prose; the level is the [N] row
        lines = [
            f"- [N{h_a}] {label} MY{lab_a}: {_fmt_price(p_a, u_a)}",
            f"- [N{h_b}] {label} MY{lab_b}: {_fmt_price(p_b, u_b)}",
            (f"PRICE-RESPONSE on avg_farm_price: {label} {verb} {_fmt_price(p_a, u_a)} [N{h_a}] (MY{lab_a}) "
             f"to {_fmt_price(p_b, u_b)} [N{h_b}] (MY{lab_b}) -- the settled USDA season-average farm price "
             f"(survey-based, revision_stamp actual at the session as-of; NOT a futures settle, NOT a forecast); "
             f"render under '## The record', the level is the [N] row and the direction is prose."),
        ]
        fired = {"price_leg": True, "focus": focus, "commodity": commodity, "unit": (u_a or u_b),
                 "my_lo": lab_a, "p_lo": round(p_a, 4), "my_hi": lab_b, "p_hi": round(p_b, 4)}
        return lines, fired
    except Exception:  # noqa: BLE001 -- fail-closed: a price-leg failure must never break the v1 answer
        return [], None


# ── CHAIN ENGINE v1: multi-hop quantified cascade (a REAL [N] at every hop) ────────────────────────────
# ONE curated causal chain (La_Nina -> safrinha -> su_ratio) walked hop-by-hop: ONE anchor window derived at
# the ROOT (sec 2.2), re-expressed per hop in that hop's own period grammar, EACH hop fetched through the SAME
# fetch_window machinery (PIT + sargable-partition discipline inherited by construction), ALL-HOPS-OR-NOTHING,
# rendered as one chain block with per-hop [N] rows + a no-conclusion marker the model interprets. Doctrine
# (non-negotiable): determinism owns ARITHMETIC + OBSERVATION only; the model interprets. NO minted thresholds,
# NO templated conclusions, NO CROSS-HOP arithmetic (WITHIN-hop deltas only -- sec 4.1); a dark hop kills the
# CHAIN (honest reasoned decline). Gated ONLY by the answer.py-threaded `chain` kwarg (GRAPHRAG_CASCADE_CHAIN
# read THERE, never here -- the [F3]/pace discipline). Register FENCES on emitted lines are sec 5.1 (a separate
# surface -- applied at the marked seam below).
_CHAIN_DECLINE_REASONS = frozenset(
    {"root_not_grounded", "hop_dark", "hop_thin", "degenerate", "cap", "error"})  # the sec 5.2 enum
# Grain rank for the DOWNSTREAM-ONLY alignment rule (sec 2.2(3), S5 fold): a hop may not be FINER-grained than
# its parent. Sub-annual (year_month/date) = 0, annual (marketing_year) = 1. v1 admits year_month roots ->
# year_month|MY descendants AND annual roots (skeleton `area`) -> MY. A MY -> year_month step (spread an MY over
# months) is the ONE genuinely hard alignment the plan DEFERS -> the chain declines rather than half-solve it.
_GRAIN_RANK = {"year_month": 0, "date": 0, "marketing_year": 1}


def _accent_fold(s) -> str:
    """NFKD accent-fold -- the census/evidence `fold` idiom (sec 3.2): La_Nina <-> La_Niña match on BOTH
    sides (chain_map names AND walk/DAG ids). Shares evidence.fold's ONE implementation (lazy import; sys.modules
    caches it, so per-call cost is a dict lookup). Fail-open to the raw string so a fold error never hides a
    literal match."""
    try:
        from leviathan.graphrag.evidence import fold
        return fold(str(s if s is not None else ""))
    except Exception:  # noqa: BLE001
        return str(s if s is not None else "")


def _fold_eq(a, b) -> bool:
    return _accent_fold(a) == _accent_fold(b)


def _chain_root_node(sg, graph, contract, node_name):
    """The grounded WALK node for a chain's ROOT hop: contract match + ACCENT-FOLDED id match (sec 3.2 -- the
    ENSO root is accented in 8/14 v1 DAGs; a literal match would leave accented-contract roots permanently
    unmatched while the lint stayed green). None when no such node was grounded this walk."""
    want = _accent_fold(node_name)
    for n in _select_nodes(sg, graph):
        if _fold_eq(getattr(n, "contract", None), contract) and _accent_fold(getattr(n, "id", None)) == want:
            return n
    return None


def _chain_driver_id(graph, contract, node_name):
    """The DAG driver id in `contract` whose ACCENT-FOLDED form matches the chain hop's node name (sec 3.2:
    per-hop lookups fold BOTH sides too). None when absent (the config_check lint guarantees presence; runtime
    stays defensive). Used to read a downstream hop's region token off the DAG (the hop is not a walk node)."""
    try:
        drivers = graph.contracts[contract].drivers
    except Exception:  # noqa: BLE001
        return None
    want = _accent_fold(node_name)
    for d in drivers:
        if _accent_fold(getattr(d, "id", None)) == want:
            return getattr(d, "id", None)
    return None


def _chain_hop_node(graph, contract, node_name, ref, root_node, *, is_root):
    """The node object `_scope`/`_node_specs` key off for a hop. ROOT hop -> the REAL grounded node (its region
    token + evidence ride along). DOWNSTREAM hop -> a SYNTHETIC node carrying the DAG driver's region token, so
    `_scope` runs IDENTICALLY to a per-node leg (country_rule=region hops like drought_z resolve their country
    from it). The node_key is overridden per hop by the caller (the _beneficiary idiom, cascade.py:506-508)."""
    if is_root:
        return root_node
    from types import SimpleNamespace
    did = _chain_driver_id(graph, contract, node_name)
    region = None
    if did is not None:
        try:
            region = getattr(graph.driver(contract, did), "region", None)
        except Exception:  # noqa: BLE001
            region = None
    return SimpleNamespace(contract=contract, id=node_name,
                           prior={"silver_ref": ref, "region": region}, evidence=[])


def _chain_resolve_hop(graph, contract, hop, eras, asof, root_node, *, is_root) -> tuple | None:
    """Resolve one chain hop to (identity, specs, meta) reusing the PROVEN per-node pieces (sec 2.1):
      * table/metric/agg/period/scale/narrate_unit come from the hop's cascade_map REF row (map_row) -- the
        chain names a REF, never a raw table (D2);
      * commodity = the chain contract via PSD_SLUG_ALIAS;
      * country = the explicit `country:` PIN (a PSD title, _PSD_COUNTRY_FOLD-folded) when present -- the
        safrinha class whose GEOGRAPHY is the chain's semantics, overriding the ref's default -- ELSE the ref's
        country_rule via _scope;
      * periods = _node_specs over the SHARED anchor `eras` (sec 2.2) with a chain-owned node_key.
    Returns None on any honest resolution failure (unmapped ref / SKIP_NODE region / no commodity / no specs)
    -> the caller declines the chain whole (reason `error`). `identity` = (table, metric, commodity, country,
    period_type) is the degenerate-guard key (sec 2.3)."""
    ref = (hop or {}).get("ref")
    row = map_row(ref)
    if row is None:
        return None                                                # unmapped/deferred ref: config drift
    node = _chain_hop_node(graph, contract, (hop or {}).get("node"), ref, root_node, is_root=is_root)
    commodity, country = _scope(node, row)
    if country is SKIP_NODE:
        return None                                                # region token cannot resolve -> honest fail
    pin = (hop or {}).get("country")
    if pin:                                                         # the safrinha-class PIN wins over the rule
        country = _PSD_COUNTRY_FOLD.get(pin, pin)
    if not commodity:
        return None
    row = _region_row(node, row)                                   # fred_fx region-currency metric pick (no-op else)
    nid = getattr(node, "id", None)
    nkey = ("__chain__", contract, ref, nid)
    specs = [{**s, "node_key": nkey}
             for s in _node_specs(node, row, commodity, country, eras, asof)]
    if not specs:
        return None
    identity = (row.get("table"), row.get("metric"), commodity, country, row.get("period_type", "date"))
    meta = {"node": (hop or {}).get("node"), "ref": ref, "row": row, "commodity": commodity, "country": country,
            "table": row.get("table"), "metric": row.get("metric"), "period_type": row.get("period_type", "date")}
    return identity, specs, meta


def _chain_spec_key(spec) -> tuple:
    """The fetch-identity key for reuse-before-fetch (sec 3.4): mirrors fetch_window's OWN query dict (incl its
    t2 -> min(t2, asof) clamp), so a chain spec that EXACTLY matches an already-run record this turn consumes it
    (typical for the ROOT hop, whose node is grounded and usually kept) instead of re-fetching."""
    t2, asof = spec.get("t2"), spec.get("asof")
    t2c = min(t2, asof) if (t2 and asof) else t2
    q = _query_dict(spec["table"], spec["metric"], spec["commodity"], spec["country"],
                    spec.get("t1"), t2c, asof, spec.get("period"), spec.get("period_type", "date"))
    return (q["table"], q["metric"], q["commodity"], q["country"], q["period"], q["asof"])


def _chain_rec_key(rec) -> tuple:
    q = rec.get("query") or {}
    return (q.get("table"), q.get("metric"), q.get("commodity"), q.get("country"), q.get("period"), q.get("asof"))


def _chain_hop_label(hop_no: int, n_hops: int, names: list, meta: dict) -> str:
    """The per-line hop marker: '(chain hop 2/3: safrinha -> Brazil production_mt)'. Collapsed hops show BOTH
    DAG names joined (sec 2.3). No direction verb / threshold word (register-clean by construction)."""
    who = " / ".join(names)
    loc = (str(meta.get("country")) + " ") if meta.get("country") else ""
    return f"(chain hop {hop_no}/{n_hops}: {who} -> {loc}{meta.get('metric') or ''})".replace("  ", " ")


def _chain_fmt_line(rec: dict, row: dict, n: int, *, label: str, current: bool = False) -> str:
    """Endpoint LEVEL line, hop-marked (the _fmt_line shape prefixed with the hop ordinal, sec 3.3); one figure
    per line (the handle discipline). The value re-scales the RAW record (narrate_unit), matching the injected
    _prescaled row exactly (the _assemble contract)."""
    v = _float_val(rec)
    scale = float(row.get("scale", 1) or 1)
    val = f"{v * scale:g}" if v is not None else "?"
    unit = row.get("narrate_unit") or ""
    q = rec.get("query") or {}
    period = "current" if current else (q.get("period") or "")
    return (f"- [N{n}] {label} {q.get('commodity') or ''} {row.get('metric')} {period} "
            f"(as-of {q.get('asof')}): {val} {unit}".rstrip())


def _chain_fmt_delta(row: dict, d: float, n: int, *, label: str) -> str:
    return (f"- [N{n}] {label} change within the anchor window in {row.get('metric')}: "
            f"{d:+g} {row.get('narrate_unit') or ''}".rstrip())


def _chain_fmt_pct(row: dict, pct: float, n: int, *, label: str) -> str:
    return f"- [N{n}] {label} change within the anchor window in {row.get('metric')}: {pct:+g} %"


def _chain_register_fence(lines: list, calls: list, base: int) -> list:
    """CHAIN_ENGINE sec 5.1 register fences (writer B), applied at BUILD time to the ENGINE-emitted chain lines
    -- before any line reaches the prompt, fail-closed. Three fences:

      1. MOMENTUM class (pace_register_ok / _PACE_BANNED_RX): the present-continuous/momentum lexicon
         (accelerating/decelerating/momentum/gaining steam/picking up/slowing) is grep-absent from register.py's
         global lexicons BY DESIGN, so the fence lives HERE, on the only surface that could mint it -- reused
         verbatim from the pace leg.
      2. VALUATION/FLOW class (reg.count_valuation_words + reg.count_flow_words, the DP-6 counters) over EVERY
         engine-built chain line, the marker included -- a belt on top of the template being clean by
         construction.
      3. NO-CONCLUSION template: the marker (_chain_marker) + the _chain_fmt_* lines are register-clean by
         construction; a unit test asserts every literal passes all three fences.

    A line failing fence 1 OR 2 is DROPPED together with its [N] handle. Because the chain renders LAST in
    quantify (answer.py appends chain lines after every sibling), the chain's handles are the HIGHEST-numbered
    calls of the turn -- calls[base:] -- so a dropped handle is removed and the surviving chain handles +
    their calls are RENUMBERED contiguously from base+1 with ZERO effect on any lower (non-chain) handle. No
    orphan handle survives; the grounding ledger count (len(calls)) stays honest. In the NORMAL path nothing
    drops and both `lines` and `calls` are byte-identical (the fence is the belt against a future template
    drift, not a live filter)."""
    from leviathan.graphrag import register as reg

    def _clean(text: str) -> bool:
        return (pace_register_ok(text)
                and reg.count_valuation_words(text) == 0 and reg.count_flow_words(text) == 0)

    kept = [ln for ln in lines if _clean(ln)]
    if len(kept) == len(lines):
        return lines                                              # nothing dropped -> byte-identical, calls untouched
    tail = calls[base:]                                           # the chain's own handle block (renders last)
    surviving, out_lines = [], []
    new_no = base
    for ln in kept:
        m = re.search(r"\[N(\d+)\]", ln)
        if m is None:                                             # a handle-less line (the marker): keep as-is
            out_lines.append(ln)
            continue
        old = int(m.group(1))
        idx = old - 1 - base                                     # this handle's call position within the tail
        if 0 <= idx < len(tail):
            surviving.append(tail[idx])
            new_no += 1
            out_lines.append(ln.replace(f"[N{old}]", f"[N{new_no}]", 1))
        # a line whose handle is out of the chain's own range is left untouched (defensive; never happens v1)
    calls[base:] = surviving
    return out_lines


def _chain_marker(path: str, window: str) -> str:
    """The FIXED no-conclusion marker (sec 5.1 literal): names the path + the shared anchor window + the render
    directive. NO price-direction verb, NO therefore/so/implies, NO threshold word -- the anti-fake-precision
    line applied to the chain surface. The [N] LEVELS + within-hop CHANGES are the record; direction /
    attribution / any price read are explicitly the analyst's interpretation, NEVER the engine's."""
    return (f"QUANTIFIED CHAIN {path} over {window}: each hop above is an observed record on the SHARED anchor "
            f"window; narrate the mechanism hop by hop, citing each hop's [N] rows; levels and changes are the "
            f"record -- direction, attribution, and any price read are the analyst's interpretation.")


def _chain_legs(sg, graph, kept: list, records: list, qfn, asof, near, calls: list) -> tuple:
    """The chain engine (secs 2-4). Returns (lines, fired_trace, decline_trace):
      * (lines, {...}, None) -> quantify writes sg.trace['quantify_chain'] (fired == bool(trace key));
      * ([], None, {...})    -> quantify writes sg.trace['quantify_chain_decline'] (attempted-and-declined, D7);
      * ([], None, None)     -> NO chain matched the focus: zero trace, zero cost (both keys absent).
    Never raises (fail-closed -- a chain failure must NEVER break the v1 answer; the seam belts it too)."""
    selected_id = None
    try:
        chains = load_chain_map()
        if not chains:
            return [], None, None
        focus = next((c for c in (getattr(sg, "seeds", None) or []) if c in getattr(graph, "contracts", {})), None)
        if focus is None:
            return [], None, None
        # focus-matching chains, FILE ORDER (deterministic); contracts are ASCII slugs, folded defensively.
        focus_rows = [c for c in chains
                      if any(_fold_eq(focus, x) for x in ((c or {}).get("contracts") or []))]
        if not focus_rows:
            return [], None, None                                  # no attempt: zero trace, zero cost
        # AT MOST ONE chain/turn (PAIR_CAP=1 precedent). Among focus rows whose ROOT is grounded THIS walk with a
        # non-empty anchor window (sec 3.2), select the one whose HOP NODES are the MOST grounded this walk -- the
        # question-dependent-grounding norm (sec 3.2 / D8) carried past the root. Root grounding ALONE is
        # ambiguous when same-focus chains share a root: enso_drought (2-hop) and the coffee CONTROL (3-hop) both
        # root on La_Nina for arabica, so a file-order-only pick let the SHORTER row permanently shadow the deeper
        # one (chain_coffee_control_pos min_chain_hops_cited:3 unsatisfiable, gate 4 fails). Coverage lets a
        # question that NAMES the full mechanism reach the deeper chain; FILE ORDER breaks ties (deterministic --
        # strictly-greater keeps the first). No threshold minted -- a pure count over the deterministic walk,
        # ACCENT-FOLDED on both sides like _chain_root_node (sec 3.2).
        grounded = {_accent_fold(getattr(n, "id", None)) for n in _select_nodes(sg, graph)
                    if _fold_eq(getattr(n, "contract", None), focus)}
        selected, root_node, eras, best_key = None, None, None, (-1, -1)
        for c in focus_rows:
            hops0 = (c or {}).get("hops") or []
            if not hops0:
                continue
            rn = _chain_root_node(sg, graph, focus, (hops0[0] or {}).get("node"))
            if rn is None:
                continue
            w = _derive_windows(rn, near, asof)                    # THE ONE anchor (root's own dated evidence, R3)
            if not w:
                # ANCHOR FALLBACK (minideck RCA 2026-07-24, wheat skeleton): a waiver-dark ROOT node
                # (driver_slices deferred, e.g. bare 'area') carries no dated evidence, so the skeleton
                # silently died and the NEXT focus row fired a CLIMATE chain into an ACREAGE question
                # (the model rightly cited none of it -- min_chain_hops_cited 0/2). Derive THE ONE anchor
                # from the first DOWNSTREAM hop node grounded with dated evidence this walk (same single
                # window, same R3 clamp); every hop still resolves its own values at that window.
                for hp in hops0[1:]:
                    dn = _chain_root_node(sg, graph, focus, (hp or {}).get("node"))
                    if dn is not None:
                        w = _derive_windows(dn, near, asof)
                        if w:
                            break
                if not w:
                    continue
            cov = sum(1 for hp in hops0 if _accent_fold((hp or {}).get("node")) in grounded)
            # tie-break by DEPTH after coverage (minideck RCA 2026-07-24, coffee control): when the
            # walk grounds no su node, the 3-hop control ties the 2-hop enso_drought prefix at cov=2
            # and file order let the SHORTER chain permanently shadow the deeper one -- the exact
            # failure the coverage pick was written to fix, half-fixed. Depth is honest here because
            # the deeper row CONTAINS the shorter as its prefix; file order still breaks exact ties.
            key = (cov, len(hops0))
            if key > best_key:                                     # strictly-greater -> FIRST (file order) wins ties
                selected, root_node, eras, best_key = c, rn, w, key
        if selected is None:                                       # a row matched the focus but no grounded root
            return [], None, {"chain_id": focus_rows[0].get("id"), "reason": "root_not_grounded"}
        selected_id = selected.get("id")
        hops = selected.get("hops") or []
        # ── per-hop resolution (sec 2.1) + the DOWNSTREAM-ONLY grain guard (sec 2.2(3), S5) ──
        resolved = []
        prev_rank = None
        for i, hop in enumerate(hops):
            res = _chain_resolve_hop(graph, focus, hop, eras, asof, root_node, is_root=(i == 0))
            if res is None:
                return [], None, {"chain_id": selected_id, "reason": "error", "hop": i}
            identity, specs, meta = res
            rank = _GRAIN_RANK.get(meta["period_type"], 0)
            if prev_rank is not None and rank < prev_rank:         # finer than its parent: spread-MY-over-months
                return [], None, {"chain_id": selected_id, "reason": "error", "hop": i}
            prev_rank = rank
            resolved.append({"idx": i, "identity": identity, "specs": specs, "meta": meta})
        # ── degenerate-hop guard (sec 2.3): COLLAPSE consecutive identical-identity hops; decline if <2 distinct ──
        distinct: list = []
        for r in resolved:
            if distinct and distinct[-1]["identity"] == r["identity"]:
                distinct[-1]["idxs"].append(r["idx"])              # consecutive same series -> one quantified hop
                distinct[-1]["names"].append(r["meta"]["node"])
            else:
                distinct.append({"identity": r["identity"], "specs": r["specs"], "meta": r["meta"],
                                 "idxs": [r["idx"]], "names": [r["meta"]["node"]]})
        if len(distinct) < 2:                                      # a 1-series "chain" is just a node (per-node
            return [], None, {"chain_id": selected_id, "reason": "degenerate"}   # cascade already serves it)
        # ── cap (sec 3.4): reuse-before-fetch, CHAIN_CAP NET, cap-ATOMIC (never a truncated chain) ──
        reuse: dict = {}
        for rec in records or []:
            reuse.setdefault(_chain_rec_key(rec), rec)             # a reused spec costs 0 against CHAIN_CAP
        all_specs = [s for d in distinct for s in d["specs"]]
        need = [s for s in all_specs if _chain_spec_key(s) not in reuse]
        if len(need) > CHAIN_CAP:
            return [], None, {"chain_id": selected_id, "reason": "cap", "net": len(need)}
        # ── fetch the misses in ONE pool wave (the R5 shape); reuse consumes prior records ──
        fetched: dict = {}
        if need:
            from concurrent.futures import ThreadPoolExecutor

            from leviathan.graphrag.pgstore import _POOL_SIZE
            width = max(1, min(_POOL_SIZE, len(need)))
            with ThreadPoolExecutor(max_workers=width) as pool:
                for s, rec in zip(need, pool.map(lambda sp: _run_one(qfn, sp), need)):
                    fetched[id(s)] = rec

        def _rec_for(spec):
            k = _chain_spec_key(spec)
            return reuse[k] if k in reuse else fetched.get(id(spec))

        # ── PASS 1: gather each distinct hop's records + DARK-HOP check BEFORE any injection (sec 4.1) ──
        # A dark hop (zero ok endpoint across era+current) kills the CHAIN; a declined chain injects ZERO [N]
        # rows -> no orphan handles, the ledger count stays honest.
        hop_recs: list = []
        for d in distinct:
            eras_b: dict = {}
            cur = None
            for s in d["specs"]:
                r = _rec_for(s)
                if r is None:
                    continue
                leg = s.get("leg") or ("era", 0)
                if leg[0] == "current":
                    cur = r
                elif leg[0] == "era":
                    eras_b.setdefault(s.get("era_idx") or 0, []).append((s, r))
            for i in eras_b:                                       # order each era by MY for a stable within-hop delta
                eras_b[i].sort(key=lambda sr: (sr[0].get("my") is None, sr[0].get("my")))
            ok_any = any(r.get("status") == "ok" and (r.get("rows") or [])
                         for pairs in eras_b.values() for (_s, r) in pairs)
            ok_cur = cur is not None and cur.get("status") == "ok" and bool(cur.get("rows"))
            if not (ok_any or ok_cur):
                return [], None, {"chain_id": selected_id, "reason": "hop_dark",
                                  "hop": d["idxs"][0], "node": " / ".join(d["names"])}
            hop_recs.append({"d": d, "eras": eras_b, "cur": cur})
        # ── PASS 2: inject [N] rows (continue-count) + render (all hops confirmed live) ──
        lines: list = []
        hop_trace: list = []
        base = len(calls)                                          # continue the turn's handle count (sec 3.3)
        n = base
        n_hops = len(hop_recs)
        for hop_no, hr in enumerate(hop_recs, start=1):
            d, eras_b, cur = hr["d"], hr["eras"], hr["cur"]
            row = d["meta"]["row"]
            label = _chain_hop_label(hop_no, n_hops, d["names"], d["meta"])
            statuses: dict = {}
            delta_val = None
            for i in sorted(eras_b):
                pairs = eras_b[i]
                statuses[i] = [r.get("status") for (_s, r) in pairs]
                oks = [r for (_s, r) in pairs if r.get("status") == "ok" and (r.get("rows") or [])]
                for r in oks:                                      # each MY endpoint LEVEL (pre-scaled, R10 prov)
                    n += 1
                    calls.append(_prescaled(r, row, n))
                    lines.append(_chain_fmt_line(r, row, n, label=label))
                dlt = _era_delta(oks, row)                         # WITHIN-hop delta ONLY (no cross-hop math, 4.1)
                if dlt is not None:
                    delta_val = dlt
                    n += 1
                    calls.append(_delta_call(oks[-1], row, dlt, n, kind="delta"))
                    lines.append(_chain_fmt_delta(row, dlt, n, label=label))
                    pct = _pct_change(oks, row)
                    if pct is not None:
                        n += 1
                        calls.append(_delta_call(oks[-1], row, pct, n, kind="pct"))
                        lines.append(_chain_fmt_pct(row, pct, n, label=label))
            if cur is not None and cur.get("status") == "ok" and (cur.get("rows") or []):
                statuses["current"] = "ok"
                n += 1
                calls.append(_prescaled(cur, row, n))
                lines.append(_chain_fmt_line(cur, row, n, label=label, current=True))
            elif cur is not None:
                statuses["current"] = cur.get("status")
            entry = {"hop": d["idxs"][0], "node": " / ".join(d["names"]), "ref": d["meta"]["ref"],
                     "table": d["meta"]["table"], "metric": d["meta"]["metric"], "country": d["meta"]["country"],
                     "leg_statuses": statuses, "delta": (round(delta_val, 4) if delta_val is not None else None)}
            hop_trace.append(entry)
            for extra in d["idxs"][1:]:                            # the collapsed originals (sec 2.3 record)
                hop_trace.append({"hop": extra, "collapsed_into": d["idxs"][0]})
        window_lbl = f"{eras[0][0]}..{eras[0][1]}"                 # the anchor window, stated once (sec 4.1)
        path = " -> ".join(" / ".join(hr["d"]["names"]) for hr in hop_recs)
        lines.append(_chain_marker(path, window_lbl))
        # sec 5.1 register fences (writer B): applied to `lines` HERE, the emitting surface, before the prompt.
        # Drops any register-tripping line + its handle and renumbers the chain tail; byte-identical when clean.
        lines = _chain_register_fence(lines, calls, base)
        fired = {"chain_id": selected_id, "contract": focus, "window": window_lbl,
                 "hops": hop_trace, "n_rows": len(calls) - base}    # honest post-fence count (== n-base when clean)
        return lines, fired, None
    except Exception as e:  # noqa: BLE001 -- fail-closed: never break the v1 answer
        return [], None, ({"chain_id": selected_id, "reason": "error", "detail": type(e).__name__[:40]}
                          if selected_id else None)


# ── HORIZONTAL TRANSMISSION CHAIN (TRANSMISSION_CHAIN_PLAN.md D1-D12) ────────────────────────────────
# The COMPOSITION layer over the RV2 pair engine: palm -> soyoil -> meal ACROSS commodities, folding the
# EXISTING _reroute_xc fork per link (2.2 -- reused VERBATIM, never re-implemented) over ONE anchor window.
# Distinct from the VERTICAL chain engine above (driver -> production -> su_ratio WITHIN one contract's DAG):
# the two engines share the decline-reason VOCABULARY (D7) and nothing else -- separate caps (D5/fold-pass 3),
# separate trace keys (D6), separate flags, and AT MOST ONE of them fires per turn (D11).
#
# DOCTRINE the engine encodes, restated because every branch below serves it:
#   * determinism owns ARITHMETIC AND OBSERVATION, the model interprets: NO minted threshold, no pass-through
#     ratio, no elasticity, no crush margin, no cents-per-link, and NEVER a cross-link quantity (2.2/2.5);
#   * per-link nature is an EXPECTATION, the OBSERVED SIGN decides (1.5): the map's `nature` is a hint that
#     rides the trace, never a gate -- a crush link DIVERGES when its legs oppose and a vegoil link CO-MOVES
#     when they agree, and BOTH render honestly;
#   * a dark / co-moving link TRUNCATES the chain to a narrative handoff (2.4/D4) -- "reached soyoil, not yet
#     meal" is the PAYOFF, not a hidden failure -- and nothing downstream is ever imputed;
#   * never volunteered: the fork inherits the RV2 fence (an explicit cross-commodity ask only, i.e. an
#     `xc_request` from the detector), so the composer declines outright without one.
_XMIT_DECLINE_REASONS = frozenset(
    {"root_not_grounded", "hop_dark", "hop_thin", "degenerate", "cap", "error",   # the vertical enum, VERBATIM
     "link_comove"})                                                              # + the ONE horizontal reason


def _xmit_pair_realizable(pair_id: str) -> bool:
    """The per-PAIR census gate (D1: every link must be a material CENSUS-REALIZABLE pair). Lazily imported so
    the composer never hard-depends on the census module; ANY non-True verdict -- False (dark / era-overlap /
    unserved leg) or None (uncurated, pg unavailable, or any raise) -- declines the link, per the
    cascade_census.pair_realizable interface contract ("callers FAIL CLOSED")."""
    try:
        from leviathan.graphrag.numbers import cascade_census as cc
        return cc.pair_realizable(pair_id) is True
    except Exception:  # noqa: BLE001
        return False


def _xmit_memo_qfn(qfn):
    """The HOT MEMO the two-phase composer runs on (3.3 control-3 / fold-pass finding 5). Keyed on the SQL TEXT
    -- the single argument Q.run hands a query_fn -- so PHASE 2 can call `_reroute_xc` -> `_leg_world_deltas`
    VERBATIM (a serial nested for-loop, unchanged) and still issue ZERO new pg round-trips: every
    `_world_su_ratio` it asks for was already warmed by the pooled PHASE 1. Verbatim reuse is preserved; the
    parallelism lives entirely in the prewarm.

    A None qfn (the default-backend path) passes through untouched -- wrapping it would change backend
    selection, and serving always injects one. `.memo` is exposed as the honest round-trip counter."""
    if qfn is None:
        return None
    memo: dict = {}

    def _q(sql):
        if sql in memo:
            return memo[sql]
        rows = qfn(sql)
        memo[sql] = rows
        return rows

    _q.memo = memo
    return _q


def _xmit_su_keys(links: list, windows: list) -> list:
    """PHASE-1 work list: every DISTINCT (slug, marketing_year) World su_ratio the chain's links will need on
    the shared anchor window, deduped ACROSS links -- which is the whole point of the hub memo (3.3: soyoil's
    su_ratio serves BOTH the palm-soyoil link and the soyoil-meal link, and SBO is the cut vertex of nearly
    every curated path). Each key costs exactly TWO component fetches (_XC_SU_STOCKS + _XC_SU_USE), which is
    how the composer prices the chain against TRANSMISSION_CAP BEFORE paying anything. Sorted -> deterministic."""
    keys = set()
    for lk in links or []:
        for slug in ((lk or {}).get("source"), (lk or {}).get("target")):
            if not slug:
                continue
            for w in windows or []:
                for my in _my_span(w, slug):
                    keys.add((slug, my))
    return sorted(keys)


def _xmit_prewarm(qfn, keys: list, asof) -> None:
    """PHASE 1 (the ONLY parallel step, 3.3 control-3): fetch every distinct World su_ratio the chain needs in
    ONE ThreadPoolExecutor wave at the pg CONNECTION-POOL width, filling the memo. Wall-clock here is bounded
    by ROUNDS (ceil(n / pool width)), not by the raw fetch sum -- the naive verbatim-serial shape would pay
    ~12-24 cold serial fetches on a 2-link chain, which is exactly why the prewarm is load-bearing."""
    if not keys:
        return
    from concurrent.futures import ThreadPoolExecutor

    from leviathan.graphrag.pgstore import _POOL_SIZE
    width = max(1, min(_POOL_SIZE, len(keys)))
    with ThreadPoolExecutor(max_workers=width) as pool:
        list(pool.map(lambda k: _world_su_ratio(qfn, k[0], k[1], asof), keys))


def _xmit_link_reason(qfn, source: str, target: str, windows: list, asof) -> str:
    """CLASSIFY a link that did NOT render, for the decline/handoff trace ONLY -- it renders nothing and
    decides nothing (the fork already ran; this reads the SAME memo-hot deltas to LABEL the honest truncation).
    Without it the `link_comove` reason could not exist and an honest same-sign handoff would be indistinguish-
    able from a dark link in the T2b ledger. Costs zero pg round-trips (phase-1 memo hits).

      * `hop_dark`   -- no shared era with >=2 resolved World ratios on BOTH legs (2.4's dark link);
      * `link_comove`-- a shared era whose legs move the SAME way: the honest hub handoff that ends the
                        divergence chain (D4). Reported whether or not the co-move RENDERED (the co-move render
                        needs GRAPHRAG_COMOVE; the ledger stays honest either way);
      * `hop_thin`   -- every shared era has a FLAT leg (sign 0): neither divergence nor co-move.
    An opposite-sign era cannot reach here -- `_reroute_xc` gives divergence absolute first-fire."""
    da_by = _leg_world_deltas(qfn, source, windows, asof)
    db_by = _leg_world_deltas(qfn, target, windows, asof)
    inter = sorted(set(da_by) & set(db_by))
    if not inter:
        return "hop_dark"
    for i in inter:
        sa, sb = _sign(da_by[i]["d"]), _sign(db_by[i]["d"])
        if sa != 0 and sa == sb:
            return "link_comove"
    return "hop_thin"


def _xmit_link_header(i: int, n: int, source: str, target: str, pair_id) -> str:
    """The per-link ordinal header (2.2: each link's rows render under a marker PREFIXED with the link ordinal).
    Deliberately a SEPARATE line rather than a rewrite of the RV2 template, so `_reroute_xc`'s own literals stay
    byte-identical ("reused verbatim per link"). Naming only -- no direction verb, no valuation adjective, no
    threshold word."""
    return f"TRANSMISSION LINK {i}/{n}: {_xc_label(source)} -> {_xc_label(target)} ({pair_id})"


# The honest WHY of a truncation, per decline reason -- observation only, never a conclusion and never a
# price-direction verb. `link_comove` is the reached-not-yet payoff, so it reads as a RECORD, not a failure.
_XMIT_HANDOFF_WHY = {
    "link_comove": "that link is a same-sign complex-wide move over this window, not a relative-value divergence",
    "hop_dark": "that link has no resolved World stocks-to-use pair on this window",
    "hop_thin": "one side of that link has no within-window change on this window",
}


def _xmit_handoff(i: int, n: int, source: str, target: str, reason: str) -> str:
    """The truncation-to-narrative HANDOFF (2.4/D4): the already-rendered upstream links STAY, the downstream
    becomes prose. Never impute; never render a downstream link off an un-rendered upstream. This sentence IS
    the "reached X, not yet Y" payoff -- stated as an observation, with no price-direction verb and no
    conclusion of any kind."""
    why = _XMIT_HANDOFF_WHY.get(reason, "that link is not quantifiable on this window")
    return (f"TRANSMISSION HANDOFF at link {i}/{n} ({_xc_label(source)} -> {_xc_label(target)}): {why}, so the "
            f"chain is quantified through the link(s) above ONLY; narrate the remainder as a qualitative "
            f"handoff and say plainly that the record does not carry it -- never bridge it with arithmetic.")


def _xmit_marker(path: str, window: str) -> str:
    """The FIXED no-conclusion chain marker (5.1 literal): names the path + the shared anchor window + the
    render directive. NO price-direction verb, NO therefore/implies, NO threshold word. The [N] LEVELS and
    WITHIN-link changes are the record; direction and any price read are explicitly the analyst's, never the
    engine's -- and a co-moving link is named as a complex-wide move, never as a relative-value divergence."""
    return (f"TRANSMISSION CHAIN {path} over {window}: each link above is an observed cross-commodity record on "
            f"the SHARED anchor window; where a link is a co-move it is a complex-wide move, NOT a "
            f"relative-value divergence; narrate the mechanism link by link, citing each link's [N] rows; "
            f"levels and changes are the record -- direction and any price read are the analyst's "
            f"interpretation.")


def _xmit_register_fence(lines: list) -> bool:
    """5.1 register fences on EVERY engine-built transmission line, at BUILD time, fail-closed -- the momentum
    class (pace_register_ok) + the DP-6 valuation/flow counters, the same three the vertical chain fence runs.
    True iff every line is clean.

    ATOMIC by design, and NOT the vertical `_chain_register_fence`: that one drops a tripping line and RENUMBERS
    the tail, which is sound only where each line owns exactly ONE call. An RV2 leg line cites one handle but
    injects THREE calls (endpoint + baseline + delta, `_xc_leg_lines`), so renumbering here would corrupt the
    surviving handles. A trip therefore declines the WHOLE chain with its rows rolled back -- also the honest
    outcome, since these templates are clean by construction and a trip means template DRIFT, not an accident."""
    from leviathan.graphrag import register as reg
    return all(pace_register_ok(ln) and reg.count_valuation_words(ln) == 0 and reg.count_flow_words(ln) == 0
               for ln in lines or [])


def _xmit_focus(sg, graph, xc_request: dict) -> str | None:
    """The chain HEAD the selector matches on (2.1/D8). PRIMARY = the RV2 detector's own SOURCE slug (trigger 1,
    the "how far did the palm squeeze travel through soyoil into meal?" multi-hop ask); FALLBACK = the walk's
    focus contract (trigger 2, "the walk is already standing in the complex"). BOTH triggers are gated by the
    RV2 detector upstream -- the caller declines outright without an `xc_request` -- so the fork is NEVER
    volunteered on the analyst's own initiative."""
    src = (xc_request or {}).get("source_slug")
    if src:
        return str(src)
    try:
        return next((c for c in (getattr(sg, "seeds", None) or []) if c in getattr(graph, "contracts", {})), None)
    except Exception:  # noqa: BLE001
        return None


def _xmit_select(chains: list, focus: str) -> tuple:
    """FIRST-FIRE selection, PAIR_CAP=1 generalized (2.1): AT MOST ONE transmission chain per turn -- the
    FILE-ORDER-first row whose HEAD-link source == focus AND whose EVERY link is a material, sides-matching,
    census-realizable pair. Returns (chain, [pair_row, ...]) or (None, None) -> no attempt, no trace, zero cost.
    Never auto-derived from the graph: the composer walks ONLY curated rows (the 22-path minting fence)."""
    for c in chains or []:
        links = (c or {}).get("links") or []
        if not links or not _slug_match((links[0] or {}).get("source"), focus):
            continue
        rows = [_load_pair_row((lk or {}).get("pair_id")) for lk in links]
        if any(r is None for r in rows):
            continue                                              # uncurated / non-material / map missing
        if not all(_xc_sides_ok(r, lk.get("source"), lk.get("target")) for r, lk in zip(rows, links)):
            continue                                              # leg drift -> never a guessed comparison
        if not all(_xmit_pair_realizable(lk.get("pair_id")) for lk in links):
            continue                                              # per-PAIR census verdict, fail-closed
        return c, rows
    return None, None


def _xmit_degenerate(links: list) -> bool:
    """The degenerate guard (3.2, carried verbatim from the vertical enum): consecutive links resolving to the
    IDENTICAL (slug, metric, country=World, period) identity collapse to one -- every link here is the same
    su_ratio/World/anchor-window shape, so the identity IS the unordered slug pair (PSD-alias resolved). A chain
    left with <2 distinct links is just an RV2 pair, which the pair engine already serves."""
    idents: list = []
    for lk in links or []:
        a = PSD_SLUG_ALIAS.get((lk or {}).get("source"), (lk or {}).get("source"))
        b = PSD_SLUG_ALIAS.get((lk or {}).get("target"), (lk or {}).get("target"))
        ident = frozenset((a, b))
        if not idents or idents[-1] != ident:
            idents.append(ident)
    return len(idents) < 2


def _transmission_legs(sg, graph, groups: list, xc_request: dict | None, qfn, asof, near, calls: list,
                       *, comove: bool = False, chain_fired: bool = False) -> tuple:
    """The horizontal transmission composer (secs 2-5). Returns (lines, fired_trace, decline_trace):
      * (lines, {...}, None) -> quantify writes sg.trace['quantify_transmission'] (fired == bool(key));
      * ([], None, {...})    -> quantify writes sg.trace['quantify_transmission_decline'] (attempted-and-
                                declined, 3.1/D7 -- one bounded dict, no [N] impact, no prompt impact);
      * ([], None, None)     -> NO attempt (no cross-commodity ask, or no curated+realizable row for the focus):
                                BOTH keys absent, zero cost -- zero-trace turns stay zero-trace.

    The fired trace (3.1): {chain_id, focus, window, links: [{link, pair_id, source, target, nature (the map
    HINT), observed, rendered, dA?, dB?}], n_rows, stopped_at?, stop_reason?}.

    D11 MUTUAL EXCLUSION, both directions: `chain_fired` (the seam reads sg.trace['quantify_chain'] -- the
    literal record that the vertical engine fired THIS turn) makes the horizontal yield to the ratified,
    earlier-shipping engine, declining `cap` with `yielded_to` traced; and when THIS engine fires, the seam does
    not run the vertical one. So the two chain budgets never sum, and a turn carries at most one chain engine.

    Never raises (fail-closed -- a transmission failure must NEVER break the v1 answer; the seam belts it too)."""
    selected_id = None
    try:
        if not xc_request:                                        # the RV2 fence: never volunteered
            return [], None, None
        chains = load_transmission_map()
        if not chains:
            return [], None, None
        focus = _xmit_focus(sg, graph, xc_request)
        if not focus:
            return [], None, None
        selected, pair_rows = _xmit_select(chains, focus)
        if selected is None:
            return [], None, None                                 # no attempt: zero trace, zero cost
        selected_id = selected.get("id")
        links = selected.get("links") or []
        if chain_fired:                                           # D11: the vertical engine already fired
            return [], None, {"chain_id": selected_id, "reason": "cap", "yielded_to": "quantify_chain"}
        if _xmit_degenerate(links):
            return [], None, {"chain_id": selected_id, "reason": "degenerate"}
        # ── ONE anchor window from the ROOT source node's own evidence (2.3), FORCED on every link ──
        # Every horizontal link is PSD marketing-year, so there is NO cross-grain alignment problem; the window
        # end is <= session asof by the R3 derive-side clamp. `_xc_focus_windows` is the same Invariant-4
        # shared-window forcing the pair engine already applies to its two legs -- extended to the shared hub.
        # [SKEPTIC] The `[:1]` makes 2.3's singular LITERAL. `_derive_windows` returns `eps[:2]` -- typically an
        # ANALOGUE era PLUS the current rhyme, whose MYs are disjoint -- and carrying both breaks the section two
        # ways: (a) the flagship prices at 3 slugs x 4 MYs x 2 components = net 24 > TRANSMISSION_CAP 18, an
        # ATOMIC `cap` decline on the COMMONEST real window shape (3.3's own arithmetic sizes the cap for ~3
        # World su_ratios, i.e. ONE window); and (b) `_reroute_xc` first-fires per link INDEPENDENTLY, so link 1
        # could fire on the analogue era while link 2 fires on the current one -- and `_xmit_marker` would then
        # narrate two DIFFERENT eras as "the SHARED anchor window". One anchor, forced on every link.
        windows = _xc_focus_windows(sg, graph, groups, links[0].get("source"), near, asof)[:1]
        if not windows:
            return [], None, {"chain_id": selected_id, "reason": "root_not_grounded"}
        # ── cap: priced BEFORE any fetch, ATOMIC (3.3 control-2) ──
        keys = _xmit_su_keys(links, windows)
        net = 2 * len(keys)                                       # 2 PSD components per World su_ratio synthesis
        if net > TRANSMISSION_CAP:
            return [], None, {"chain_id": selected_id, "reason": "cap", "net": net}
        mqfn = _xmit_memo_qfn(qfn)
        _xmit_prewarm(mqfn, keys, asof)                           # PHASE 1 -- the only parallel step
        # ── PHASE 2: `_reroute_xc` VERBATIM per link over the hot memo (zero new pg round-trips) ──
        base = len(calls)
        n_links = len(links)
        lines: list = []
        link_trace: list = []
        window_lbl = None
        stopped_at, stop_reason = None, None
        for i, (lk, prow) in enumerate(zip(links, pair_rows), start=1):
            src, tgt = lk.get("source"), lk.get("target")
            # `comove` rides in POSITIONALLY, exactly as _run_xc passes it (a gate-test stub replaces
            # _reroute_xc with a positional-only lambda). Threaded from the seam, never read from env here.
            blk, fired = _reroute_xc(prow, src, tgt, windows, mqfn, asof, calls, len(calls), sg, comove)
            entry = {"link": i, "pair_id": lk.get("pair_id"), "source": src, "target": tgt,
                     "nature": lk.get("nature")}                  # `nature` = the map HINT, next to the record
            if fired:
                observed = "comove" if fired.get("comove") else "divergence"
                entry.update({"observed": observed, "rendered": observed,
                              "dA": fired.get("dA"), "dB": fired.get("dB")})
                link_trace.append(entry)
                lines.append(_xmit_link_header(i, n_links, src, tgt, lk.get("pair_id")))
                lines.extend(blk)
                window_lbl = window_lbl or fired.get("window")
                if observed == "comove":
                    # D4: a co-move at ANY hub (vegoil OR crush) ends the DIVERGENCE chain -- an honest handoff,
                    # not a failure. Its own '## Complex-wide move' render stays; downstream is never imputed.
                    stopped_at, stop_reason = i, "link_comove"
                    break
                continue
            # No render. Classify the honest truncation (memo-hot, zero fetches).
            reason = _xmit_link_reason(mqfn, src, tgt, windows, asof)
            entry.update({"observed": reason, "rendered": "truncated"})
            if not link_trace:
                # 2.4: a chain whose HEAD link is dark declines WHOLE -- nothing reader-facing, ZERO [N] rows
                # (the mentor answers qualitatively, as today). The belt keeps the handle ledger honest.
                calls[base:] = []
                return [], None, {"chain_id": selected_id, "reason": reason, "link": i}
            link_trace.append(entry)
            stopped_at, stop_reason = i, reason
            break
        n_rendered = sum(1 for e in link_trace if e.get("rendered") in ("divergence", "comove"))
        if not n_rendered:
            calls[base:] = []                                     # defensive: nothing rendered -> no orphans
            return [], None, {"chain_id": selected_id, "reason": "degenerate"}
        # The HANDOFF names the FIRST link the chain does NOT quantify: the link that declined (rendered
        # 'truncated'), or -- when a co-move at a hub ENDED the divergence chain (D4) -- the one after it.
        # A co-move on the LAST link leaves nothing downstream, so no handoff prints (both links rendered).
        if stopped_at is not None:
            unq = stopped_at + 1 if stop_reason == "link_comove" else stopped_at
            if unq <= n_links:
                nxt = links[unq - 1]
                lines.append(_xmit_handoff(unq, n_links, nxt.get("source"), nxt.get("target"), stop_reason))
        # The path names the QUANTIFIED span only -- never a node the chain did not reach (2.4).
        path = " -> ".join([_xc_label(links[0].get("source"))]
                           + [_xc_label(links[k].get("target")) for k in range(n_rendered)])
        window_lbl = window_lbl or f"{windows[0][0]}..{windows[0][1]}"
        lines.append(_xmit_marker(path, window_lbl))
        if not _xmit_register_fence(lines):                       # 5.1 fences, ATOMIC + rows rolled back
            calls[base:] = []
            return [], None, {"chain_id": selected_id, "reason": "error", "detail": "register_fence"}
        fired_trace = {"chain_id": selected_id, "focus": focus, "window": window_lbl,
                       "links": link_trace, "n_rows": len(calls) - base}
        if stopped_at is not None:
            fired_trace["stopped_at"], fired_trace["stop_reason"] = stopped_at, stop_reason
        return lines, fired_trace, None
    except Exception as e:  # noqa: BLE001 -- fail-closed: never break the v1 answer
        return [], None, ({"chain_id": selected_id, "reason": "error", "detail": type(e).__name__[:40]}
                          if selected_id else None)
