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
import time  # D-XT P3: resolve_xc_open meters its probe wall-time; the round-4 refuter caught the
#              missing import turning EVERY open turn into a swallowed-NameError decline.

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
def _cascade_width(n: int) -> int:
    """Executor width for the cascade's pg waves: min(serving.cascade.workers, pool, n).

    DECOUPLED from _POOL_SIZE (2026-08-25, the capacity refuter's precondition for ANY pool raise):
    width=pool was honest when the pool was 4 -- ceil(N/4) serial rounds either way -- but the pool
    is a SHARED per-process resource sized for CONCURRENT TURNS, and deriving a single turn's fan-out
    from it inverts that: at pool 24 one turn's prewarm went 24-wide, drained every slot, and starved
    its sibling rows into `pg_pool_exhausted` (measured 2026-08-25, the A/B L arm -- opus-turn overlap
    made the collision window real). A turn's width is now its OWN bounded knob; the pool stays the
    turn-concurrency budget. Default 4 = the old pool-4 behavior, byte-identical to pre-raise widths.

    The knob rides PARAMS (`serving.cascade.workers`), the TRANSMISSION_CAP channel above -- the
    wedge-day version read a GRAPHRAG_CASCADE_WORKERS environment variable inside this module, which
    the SKEPTIC F3 doctrine test forbids (config enters the engine at the answer.py seam or via
    params, never as an engine-owned environment read), and which nothing anywhere ever set.
    Corrected 2026-08-25, caught by that test on the projection wave's first full-suite sweep.
    """
    from leviathan.graphrag.pgstore import _POOL_SIZE
    try:
        w = int(_pr.get("serving.cascade.workers", 4) or 4)
    except (TypeError, ValueError):
        w = 4
    return max(1, min(w, _POOL_SIZE, n))


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
                 agg="series", period=None, period_type="date",
                 futures_newest_first: bool | str = False) -> dict:
    """One deterministic PIT-safe windowed lookup -> a call-record {query, rows, status}.

    PER-LEG asof pinning is the CALLER's responsibility (quantify): a historical/era leg passes
    asof=window_end (already clamped to <= session_asof in _derive_windows, R3); the CURRENT 'rhyme' leg
    passes asof=session_asof with the CURRENT period. This fn NEVER computes today.

    GRACEFUL DEGRADATION (R6): EVERY failure path -- a NumberQuery/build_sql validation error (bad metric,
    malformed MY, a country that fails _canon_country), a pg/Athena outage, a timeout -- returns a
    call-record with status='error' and rows=[]. It NEVER raises, so _run_one / pool.map / the seam cannot
    unwind the reasoning turn.

    `futures_newest_first` is the FUTURES_READPATH S1 canary (D-FR-10), threaded from
    `answer._futures_newest_first_on()` down quantify -> _run_one -> here as an ARGUMENT -- NEVER an env
    read inside cascade.py (the pace/price_request/episode_outcomes discipline). That discipline is
    ENFORCED, not merely written down: test_transmission_chain scans this file's SOURCE for the env-access
    tokens, so even naming one in a comment reds the suite -- which is why this paragraph says "env read"
    and not the call it is naming. Default False -> Q.run compiles the byte-identical ASC total order it
    compiled before the wave. This is the GENERIC seam: `table` is a caller-supplied value, so a node whose
    silver_ref maps to silver_futures_eod reaches the futures series branch through THIS function."""
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
        rows = Q.run(spec, query_fn=qfn, futures_newest_first=futures_newest_first)
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

# THE TWO PSD SURFACES (projection wave Lane 3, L2-5, 2026-08-25). One source object, two shapes: the wide
# card pivots eight attributes into MT-denominated COLUMNS, the long companion keeps every published line
# with the metric as a VALUE of an `attribute` column and the value in USDA's OWN unit. Named here, beside
# the other PSD identity constants, because both the declared-unserved fence below and the World synthesis
# 1,700 lines down have to mean the same two cards -- a second literal in either place is how the fence and
# the reader drift apart.
_PSD_TABLE = "silver_psd"
_PSD_ATTR_TABLE = "silver_psd_attributes"
PSD_TABLES = frozenset({_PSD_TABLE, _PSD_ATTR_TABLE})

# Contracts with NO series in silver_psd AT ALL (DISTINCT leviathan_slug, C002-verified 2026-07-15):
# USDA PSD carries no cocoa balance sheet -- that is ICCO territory. A quantify against it can only ever
# return 0 rows -- declare the absence so the leg SKIPs honestly at _scope and the C002 slug check reads
# it as KNOWN-UNSERVED rather than drift.
#
# D-EC XC-7 FLIP (2026-08-20): frozen_orange_juice LEFT this fence. It was here because PSD's commodity
# map admitted 13 codes and code 585100 (Orange Juice) was not one of them -- an INGESTION absence wearing
# a source absence's clothes. The 13 -> 47 widening (commit e437eff7) bound 585100 to the contract slug,
# and the fence stayed armed on purpose until the cloud re-run proved rows rather than intentions: that
# re-run landed 2026-08-20 10:01 and FCOJ now carries 746 rows across 25 countries in the live object
# (data/dec_p0/projection_census.json, silver_psd commodity-code family). The flip condition written into
# tests/unit/test_psd_slug_map_widening.py is met, so the FCOJ psd legs un-SKIP and read real rows.
# `cocoa` is NOT the same shape and stays: it is not among the 63 slugs the table carries, and no widening
# can mint it, because USDA does not publish a cocoa balance sheet.
PSD_UNSERVED_SLUGS = frozenset({"cocoa"})

# Contracts with NO series in silver_cot AT ALL: CFTC covers only US-cleared contracts, and
# configs/sources/cftc_cot.yaml `not_covered:` is the authoritative declaration (MATIF/DCE/ZCE/JSE/
# BMF/ICE-Canada/IFEU venues). The D1 context lane (2026-08-01) made cot legs live estate-wide, and the
# first Branch-A gate fire (2026-08-03) red EVERY family on the six such legs that exist -- mapped,
# forever zero-row. Same treatment as PSD_UNSERVED_SLUGS above: the leg SKIPs honestly at _scope
# (identical rendered outcome to the zero-row decline it produced anyway) and the slug check reads
# it as KNOWN-UNSERVED rather than drift.
#
# D-PR-6: the set is DERIVED from that yaml, never transcribed. The two fences have DIFFERENT kinds of
# truth and must not be given one mechanism -- PSD's source of truth is the TABLE (a DISTINCT
# leviathan_slug probe, C002-verified), so it stays a frozenset above; COT's source of truth is a config
# file that already exists, so a second hand-kept copy of it is pure drift surface. It drifted inside two
# days: the SECOND Branch-A fire (2026-08-04, gate rev 12) found the transcription short by three -- the
# LONDON legs (IFEU is outside CFTC jurisdiction) and frozen_orange_juice, which was claimed-covered with
# an oi_approx of "verify" that nobody ever verified and which never landed a row.
#
# The FALLBACK below is used ONLY when the yaml is missing or unreadable, and it fails OPEN to the last
# MEASURED set rather than to an empty fence: an empty fence un-SKIPs every cot leg at once and hands the
# gate a fresh estate-wide red, which is the exact incident this fence exists to end. It is a disaster
# floor, never a second source of truth -- tests/unit/test_unserved_fence_lint.py pins it to the yaml.
_COT_NOT_COVERED_FALLBACK = frozenset({
    "french_wheat_matif", "french_rapeseed_matif", "french_maize_matif",
    "canola_ice",
    "soybeans_no_1_dce", "soybeans_no_2_dce", "soybean_meal_dce", "soybean_oil_dce", "palm_olein_dce",
    "rapeseed_meal_zce", "rapeseed_oil_zce",
    "south_african_white_maize_jse", "south_african_yellow_maize_jse",
    "campinas_corn_reference_bmf", "brazilian_arabica_coffee",
    "robusta_coffee", "white_sugar", "frozen_orange_juice",
})


def _cot_yaml_path():
    """configs/sources/cftc_cot.yaml, resolved off the SAME repo root load_map() uses (`ex._CFG` is
    configs/graphrag) so the image layout is described in exactly one place. Its own function so a test
    can point the reader at a missing/mangled file and exercise the fallback."""
    from leviathan.graphrag import extract as ex

    return ex._CFG.parent / "sources" / "cftc_cot.yaml"


def _scan_not_covered(text: str) -> frozenset[str]:
    """The `not_covered:` block of cftc_cot.yaml as a slug set, by LINE SCAN rather than safe_load: the
    file's CSV `schema:` block carries `Key:{type: int, ...}` flow tokens the YAML scanner rejects, so
    the whole document does NOT parse (verified 2026-08-04: ScannerError at :127, "mapping values are
    not allowed here"). The block itself is plain `- slug  # comment` lines; a comment-only line stays
    inside the block (the frozen_orange_juice entry wraps its rationale onto two of them) and the next
    non-comment, non-item line -- the following top-level key -- ends it."""
    slugs, in_block = set(), False
    for line in text.splitlines():
        if line.startswith("not_covered:"):
            in_block = True
            continue
        if not in_block:
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            slugs.add(stripped[2:].split("#", 1)[0].strip())
        elif stripped and not stripped.startswith("#"):
            break
    return frozenset(s for s in slugs if s)


@functools.lru_cache(maxsize=1)
def _cot_unserved_derived() -> frozenset[str]:
    """The yaml read itself, cached for the process (the load_map idiom): one file read at FIRST USE,
    never at import. Any read failure -- absent configs/, truncated file, an empty block -- falls back
    to `_COT_NOT_COVERED_FALLBACK` and says so at WARNING (stderr by default, so it is visible in a
    serving log and in the gate's job log without any logging config).

    Callers use `cot_unserved_slugs()`, which is this plus the override seam below."""
    import logging

    try:
        p = _cot_yaml_path()
        slugs = _scan_not_covered(p.read_text(encoding="utf-8"))
        if slugs:
            return slugs
        why = f"{p}: not_covered block absent or empty"
    except Exception as e:  # noqa: BLE001 -- a fence that raises is worse than a fence that is stale
        why = f"{type(e).__name__}: {e}"
    logging.getLogger(__name__).warning(
        "cot unserved fence: cftc_cot.yaml unreadable (%s) -- FALLING BACK to the frozen %d-slug set "
        "measured 2026-08-04; a cot venue added to the yaml since then is NOT fenced",
        why, len(_COT_NOT_COVERED_FALLBACK))
    return _COT_NOT_COVERED_FALLBACK


# The documented test seam: set this (monkeypatch-friendly -- it is a REAL global, so the undo
# restores None and leaves no shadow entry) to force the fence for one test.
_COT_UNSERVED_OVERRIDE = None


def cot_unserved_slugs() -> frozenset[str]:
    """THE ONE READER of the fence -- for `_scope` below, for `contract_check.py:197` (through the
    module attribute), and for tests.

    WHY THE `globals()` LOOKUP, WHICH IS OTHERWISE ODD-LOOKING. `COT_UNSERVED_SLUGS` is served by the
    PEP-562 `__getattr__` hook below, and a module `__getattr__` is consulted ONLY when normal lookup
    fails -- it is NOT consulted for a bare global read inside this module. So the obvious test move,
    `monkeypatch.setattr(cascade, "COT_UNSERVED_SLUGS", {...})` (the same style
    tests/unit/test_contract_check.py already uses on `_mapped_legs` and `_distinct_set`), used to put
    the estate in a SPLIT BRAIN: contract_check saw the patched set, `_scope` saw the yaml's, and the
    resulting test passed for the wrong reason. Measured before this seam existed: 1 slug for
    contract_check, 18 for `_scope`, on the same interpreter at the same moment.

    Reading `globals()` here makes an explicitly-SET module attribute win for EVERY reader, so the two
    can no longer disagree. It weakens nothing about the derivation: the name is absent from
    `__dict__` unless somebody assigned it, so the normal path is the yaml read, once, cached.

    The SANCTIONED patch point is `_COT_UNSERVED_OVERRIDE` (a real module global, so monkeypatch's
    undo restores None cleanly and leaves no shadow). Patching `COT_UNSERVED_SLUGS` directly also
    works, but note what monkeypatch's undo does: it `setattr`s the pre-patch VALUE back, which
    writes a real `__dict__` entry that shadows `__getattr__` for the rest of the interpreter. The
    value is correct, so nothing goes wrong -- but a later `cache_clear()` or repointed
    `_cot_yaml_path` will not be picked up. Call `reset_cot_fence()` if you need that.
    """
    override = _COT_UNSERVED_OVERRIDE
    if override is None:
        override = globals().get("COT_UNSERVED_SLUGS")
    if override is not None:
        return override if isinstance(override, frozenset) else frozenset(override)
    return _cot_unserved_derived()


# `cot_unserved_slugs.cache_clear()` is the idiom callers and tests already use; keep it working now
# that the cache lives one level down.
cot_unserved_slugs.cache_clear = _cot_unserved_derived.cache_clear
cot_unserved_slugs.cache_info = _cot_unserved_derived.cache_info


def reset_cot_fence() -> None:
    """Drop every override AND the cached read, returning the fence to "derive from the yaml".

    Exists because a module attribute, once assigned, shadows `__getattr__` permanently -- including
    the assignment pytest's monkeypatch makes when it UNDOES a patch of `COT_UNSERVED_SLUGS`. Calling
    this in a teardown makes the fence honest again for the rest of the process.
    """
    globals().pop("COT_UNSERVED_SLUGS", None)
    globals()["_COT_UNSERVED_OVERRIDE"] = None
    _cot_unserved_derived.cache_clear()


def __getattr__(name: str):
    """PEP-562 module hook so `cascade.COT_UNSERVED_SLUGS` keeps working as a plain frozenset for its
    readers (contract_check.py:197 and the tests) while the VALUE is derived lazily. A module-level
    assignment would have to read the file at import time, and cascade is imported by serving, by every
    gate stage and by the test collector -- the read belongs at first use, behind the cache.

    This hook is only reached while nobody has ASSIGNED the name; once assigned, normal lookup wins and
    `cot_unserved_slugs()` honours the same assignment, so both readers stay in agreement either way."""
    if name == "COT_UNSERVED_SLUGS":
        return cot_unserved_slugs()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    """Entry-driven metric picks for region-ruled rows; every other row passes through unchanged.

    (1) fred_fx currency pick (RF-2): a country_rule=region row on silver_fred_fx swaps its metric to
    the resolved region's '<currency>_usd' (the ars_usd/brl_usd fold-forward fix). A resolved region
    WITHOUT a currency never reaches here (SKIP_NODE in _scope).
    (2) W-5 FROST BASIN SWAP (2026-08-25): at aggregate grain the frost FLAG is renamed to a SHARE by
    design (weather_z: 'a share must never wear the flag's name'), so a frost leg resolving to a
    region_map entry declaring `basin: true` reads `frost_event_share` -- the flag has ZERO rows on a
    basin surface (the Lane-2 census's three dark legs, the repaired instrument's first live catch).
    The unit trio moves WITH the metric: a share narrated on the flag's spec would print 0.18 as if
    it were an event bit."""
    if (row or {}).get("country_rule") != "region":
        return row
    if (row or {}).get("table") == "silver_fred_fx":
        cur = (_region_entry(n) or {}).get("currency")
        return {**row, "metric": f"{cur}_usd"} if cur else row
    if (row or {}).get("table") == "gold_weather_z" and (row or {}).get("metric") == "frost_event_flag":
        if (_region_entry(n) or {}).get("basin"):
            return {**row, "metric": "frost_event_share",
                    "native_unit": "share of member cells", "narrate_unit": "%", "scale": 100}
    return row


def _driver_token(n) -> str:
    """The node's raw driver region token ('' when absent) -- the same read _region_entry makes, split
    out so the W0-7 fence and the resolver share one accessor and cannot diverge on the None-prior edge."""
    try:
        return ((getattr(n, "prior", None) or {}).get("region") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _table_spec(table):
    """THE registry read for every engine question about a card's declared shape: the TableSpec, or None
    when the registry cannot answer -- an unregistered card (the long PSD companion before its own change
    lands) or a load failure. Uncached ON PURPOSE: _registry() is the cached layer, and a second cache here
    would hold stale verdicts across test monkeypatches and config reloads."""
    if not table:
        return None
    try:
        return _registry().get(table)
    except Exception:  # noqa: BLE001 -- an unknown table is a DECLINE, never a raise inside a leg
        return None


def _table_shape(table) -> str | None:
    """The card's declared SQL shape ('wide' = metric IS a column | 'tall' = metric is a VALUE of the
    metric column), or None when no card answers for `table`. Callers treat None as "cannot know how this
    metric is spelled" and decline rather than guessing (L2-5)."""
    return getattr(_table_spec(table), "shape", None)


def _table_has_country(table) -> bool:
    """Does the table declare a country axis (TableSpec.country_col)? Drives the no-geography-primary
    skip: on a per-country table an unfiltered query is mixed-country garbage; on a country-less table
    country=None is the only honest scope. Registry-lookup failure reads as country-less (legacy
    behavior) -- the census re-derives this with a live registry, so the lint half stays fail-closed."""
    return bool(getattr(_table_spec(table), "country_col", None))


def _scope_ex(n, row) -> tuple:
    """_scope plus the WHY: (commodity, country, skip_reason). skip_reason is None whenever the leg
    resolves, else one of the census's decline classes -- the single undifferentiated 'region-unresolved'
    string mislabelled 37 of 260 declines (14%: unserved-slug and fx-no-currency legs reported as token
    misses) and made the projection wave's own before/after diff uninterpretable (W0-1)."""
    commodity = getattr(n, "contract", None)
    commodity = PSD_SLUG_ALIAS.get(commodity, commodity)
    # PER-ROW commodity aliasing (GN-2 W2.2 gate find, 2026-08-22): a table whose commodity axis is
    # the SOURCE's own code (silver_sagis_cec stores crop codes white_maize/yellow_maize) can never
    # match a CONTRACT slug (south_african_white_maize_jse), and the GLOBAL alias map above is the
    # wrong tool -- it would re-key the contract's every OTHER leg (psd, spreads) too. The row's own
    # `commodity_aliases: {contract_slug: table_code}` re-keys ONLY the legs that ride this row;
    # validated fail-closed by config_check.check_cascade_map.
    commodity = ((row or {}).get("commodity_aliases") or {}).get(commodity, commodity)
    # THE KEYING KNOB (2026-08-26): a FIXED per-row commodity. `commodity: <slug>` REPLACES the
    # resolved slug for EVERY leg that rides this row, so a ref can read a NON-CONTRACT commodity --
    # a herd count under commodity=cattle_beef on a corn or meal board. This closes the wall
    # cascade_map's minagro refusal block spent its ground (1) on ("commodity=contract slug" with no
    # translation knob -- the wall the cattle_beef/fishmeal GN-1 bindings hit, both shipping
    # silver_status: planned for it); that block is REWRITTEN by the same sitting to rest on its two
    # surviving grounds, so this comment names the wall rather than quoting a line that no longer
    # exists. It is a DIFFERENT MECHANISM from commodity_aliases above and
    # the two are lint-exclusive per row: aliases are a PER-CONTRACT RENAME with a silent fallback
    # (`.get(commodity, commodity)`), so a contract absent from the alias map keys through as itself
    # -- correct when the row's job is to translate each board's own slug into the source's own code
    # (sagis crop codes, the ESR sorghum name), and a silent MISS when the row's job is to read one
    # commodity nobody's contract is named after. A fixed override cannot miss: there is no contract
    # key to match, so a second board acquiring the ref reads the same series rather than its own
    # slug and a zero-row leg.
    # IT LANDS HERE, ABOVE THE FENCES, ON PURPOSE: the PSD/COT declared-unserved tests below must read
    # the OVERRIDDEN slug -- a fixed `cocoa`/`fish_meal` override has to meet the same source-absence
    # fence a contract slug meets, or the fence would grade the wrong commodity.
    # THE GEOGRAPHY TRAP (R3, MEASURED before this knob shipped): configs/geographies/*_regions.yaml is
    # named for CONTRACT slugs only, so _primary_title(<override>) is None for every override slug
    # (measured: 'cattle_beef' -> None while 'corn_cbot' -> 'United States'), and a country_rule
    # `primary` row would lose the contract's real geography HERE and then decline
    # `no-geography-primary` at the fence below -- a false decline wearing a fence's clothes. Hence
    # check_cascade_map requires an override row to declare country_rule EXPLICITLY as `region` or
    # `none`; `primary` and the absent default are build failures, not judgement calls.
    fixed_commodity = (row or {}).get("commodity")
    if fixed_commodity:
        commodity = fixed_commodity
    # BOTH PSD surfaces (L2-5): the fence is about the SOURCE, not about a shape. USDA publishes no cocoa
    # balance sheet at all, so the long companion is exactly as empty of cocoa as the wide card is -- a
    # table-literal fence would have let an attribute-axis cocoa leg compile and fetch its way to the same
    # zero rows, and the census would have read that as drift instead of as the declared absence it is.
    if (row or {}).get("table") in PSD_TABLES and commodity in PSD_UNSERVED_SLUGS:
        return commodity, SKIP_NODE, "psd-unserved-slug"   # declared-unserved: PSD has no series for this contract
    if (row or {}).get("table") == "silver_cot" and commodity in cot_unserved_slugs():
        return commodity, SKIP_NODE, "cot-unserved-slug"   # declared-unserved: cftc_cot.yaml lists it not_covered
    rule = (row or {}).get("country_rule", "primary")
    if rule == "none":
        return commodity, None, None
    if rule == "region":
        entry = _region_entry(n)
        if not entry:
            return commodity, SKIP_NODE, "region-token-unresolved"
        if (row or {}).get("table") == "silver_fred_fx":
            return (commodity, None, None) if entry.get("currency") \
                else (commodity, SKIP_NODE, "fx-no-currency")
        country = entry.get("country")
        return (commodity, country, None) if country \
            else (commodity, SKIP_NODE, "region-entry-no-country")
    # W0-7 GLOBAL MIS-SCOPE FENCE (D-9, 2026-08-25): a Global/global driver token on a primary-ruled
    # row was silently answered with the CONTRACT's primary country -- french_wheat_matif's *global*
    # ending stocks cited European Union, raw_sugar's Brazil, robusta's Vietnam (12 census legs). A row
    # that declares `global_token: skip` declines instead; re-keying a genuinely-national token to its
    # nation is DAG work (the FX-5 shape), never a resolver guess. Per-row by D-7: never a region_map token.
    if (row or {}).get("global_token") == "skip" and _driver_token(n) in ("Global", "global"):
        return commodity, SKIP_NODE, "global-token-fenced"
    title = _primary_title(commodity)
    # W0-7 companion (census find + owner word, 2026-08-25): CONTEXT commodities (barley, sorghum,
    # sunflower_oil) carry no geography entry BY DESIGN -- _primary_title is None. On a table WITH a
    # country column, country=None compiles to an UNFILTERED per-country query, and agg=latest then
    # serves whichever country's row sorts last (8 census legs FIRED so, pg_rows 2666-4265 = the whole
    # multi-country surface). Same law as rrv1 2c: decline beats an arbitrary country's number. Tables
    # without a country axis (fx/oni/mpob) keep country=None -- there is nothing to mis-scope.
    if title is None and _table_has_country((row or {}).get("table")):
        return commodity, SKIP_NODE, "no-geography-primary"
    return commodity, title, None


def _scope(n, row) -> tuple:
    """commodity = the node's contract (aliased to the silver slug where they differ); country per the
    map row's country_rule, in the TABLE's surface form — silver_psd stores 'United States' while geo
    gives 'united_states' (the silverleg precedent; both mismatches W0-caught: every PSD leg died).
    country_rule: none -> no country; primary -> the contract's primary country (default); region -> the
    DRIVER's own region token via region_map (F1/RF-2 -- primary quantified the US series under a
    Russia/China leg), with SKIP_NODE when the token does not resolve. silver_fred_fx has no country
    column: a resolved region needs a currency (metric pick, _region_row) or the leg is not honest.
    Thin wrapper over _scope_ex -- the runtime path drops the reason, the census keeps it."""
    commodity, country, _ = _scope_ex(n, row)
    return commodity, country


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
    # silver_cot's door is the R9 CONTEXT LANE further down (D1, 2026-08-01) -- a fetched past-tense
    # context leg, never an engine lane. positioning_context_violations() is the shape that reaches
    # this grain at all; before D1 the entry below had no door and the weekly-COT pace leg never ran.
    "silver_cot": "week", "silver_esr": "week",
    "silver_pink_sheet": "month", "silver_mpob": "month", "gold_weather_z": "month",
    "silver_noaa_oni": "month",
    "silver_fred_fx": "day",
    # GN-2 W1.4 (2026-08-22): FGIS weekly export INSPECTIONS -- the SHIPMENTS half of the US export
    # program (silver_esr is the SALES half). Grain mirrors ESR's: per destination x week, sum-collapsed
    # to the national weekly flow. This entry is only legal TOGETHER with the _PACE_PERIOD_KEY_EXTRA
    # row below -- without it the entry alone ships the exact fabrication the collapse exists to prevent
    # (the recon's R1 FATAL; see the registry's own comment).
    "silver_fgis": "week",
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
# front_month_v2, fenced by config_check.check_futures_roll) and is CALLED here, never re-derived.
_PACE_COLLAPSE = {"silver_esr": "sum", "gold_weather_z": "mean", "silver_futures_eod": "front_expiry",
                  "silver_fgis": "sum"}   # W1.4: national weekly inspections = sum across destinations
                  #                         (the ESR flow-total doctrine; whole MT, never a price)
_PACE_COLLAPSE_KINDS: frozenset[str] = frozenset({"sum", "mean", "front_expiry"})
# PRICE TABLES (F-E lint): a table whose served value IS a price. `sum`/`mean` are FORBIDDEN as the
# collapse kind for any of these -- the aggregate of a price cross-section is not a price anyone quotes.
# An EXPLICIT documented set rather than a registry derivation, for three reasons, all load-bearing:
#   (1) load_registry() DROPS whitelist-absent tables (registry.WHITELIST_ABSENT_DEFAULT), so
#       silver_futures_eod -- the exact table F-E is about -- is INVISIBLE to a registry-derived set
#       today: the fence would fail OPEN for the whole pre-flip window it exists to cover;
#   (2) config_check.PRICE_TABLES cannot be reused -- importing config_check from here is a cycle, and
#       its semantics differ from this fence's: since the R4 price-context amendment (2026-08-26) a
#       member MAY carry a cascade_map row through the narrow context door (PRICE_CONTEXT_TABLES /
#       price_context_violations below), while THIS set bans sum/mean pace collapse regardless;
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
# alias, not the silver column: query._extras surfaces `contract_month` as of W3.1 item 3 (landed
# 2026-07-29), so a row that carries no expiry alias at all is a genuinely unlabelled row and the
# selection fails CLOSED -- honest absence -- rather than picking an arbitrary one. Nothing here puts
# silver_futures_eod into PACE_TABLES: that is item 16, still gated on the parity soak.
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


# ── GN-2 W1.1 NARRATION (2026-08-22): the basin calm/tail vocabulary ────────────────────────────────
# The owner directive, verbatim: "it shouldn't decline, what the hell does that mean to a user ...
# we're not spitting out code, we're talking to analysts." The basin rows (weather_z._basin_rows) give
# the engine real reads for multi-country belts; these two pieces give the reads an ANALYST'S VOICE:
# a magnitude word on the mean line ("near normal" -- calm weather is information, never silence), and
# the TAIL RIDER -- one sibling read of `<metric>_tail_share` (share of member cells at >= +2 sigma)
# so a calm mean can still say "but a fifth of the belt is in the tail". Non-basin countries carry NO
# tail metric -> record_silent -> no line: fail-closed by construction, zero basin detection needed.
# _BASIN_TAIL_METRICS mirrors weather_z.Z_METRICS (fence-tested equal, never imported at runtime --
# serving must not couple to a transform module's import graph).
_WEATHER_Z_TABLE = "gold_weather_z"
_BASIN_TAIL_METRICS: frozenset[str] = frozenset(
    {"tmax_anomaly", "gdd_z", "heat_stress_z", "drought_z"})
_TAIL_SUFFIX = "_tail_share"


def _metric_display(row: dict) -> str:
    """The ANALYST name for a map row's metric on model-facing lines -- the table_label sibling
    (A1/F21 closed raw table ids on this surface; the owner's word 2026-08-22 closes METRIC ids:
    internal names never reach prose). Resolution: the registry card's Metric.label, else the slug
    (an unlabeled metric renders exactly as before -- the fence tightens family-by-family). The
    machine identity always survives in the [N] call's query dict and the series tag."""
    try:
        from leviathan.graphrag.numbers.registry import load_registry
        m = load_registry().get(row.get("table")).metrics.get(row.get("metric"))
        if m is not None and getattr(m, "label", ""):
            return m.label
    except Exception:  # noqa: BLE001 -- an unregistered table's line must render, never raise
        pass
    return str(row.get("metric"))


def _z_word(v: float) -> str:
    """The magnitude word for a weather z read. NEUTRAL and magnitude-only on purpose: 'high drought_z'
    is dry stress but 'high tmax_anomaly' in winter can be benign -- direction words would need
    per-metric per-season semantics this seam does not own. Past-tense register-safe."""
    a = abs(v)
    if a < 1.0:
        return "near normal"
    if a < 2.0:
        return "notably above normal" if v > 0 else "notably below normal"
    return "extreme (>= 2 sigma above normal)" if v > 0 else "extreme (>= 2 sigma below normal)"


def _pace_grain(row) -> str | None:
    """The pace grain word for a map row, or None (=> NO pace leg): annual/MY grain, event flags, and any
    table outside the pace-capable inventory all decline structurally."""
    if (row or {}).get("period_type") == "marketing_year":
        return None                                               # annual/MY: never a sub-annual window
    if (row or {}).get("narrate_unit") == "flag":
        return None                                               # event flag: recency is T2b, not pace
    return PACE_TABLES.get((row or {}).get("table"))


# -- R9 CONTEXT LANE (D1, ratified 2026-08-01): the positioning door, deliberately narrow ------------
# PACE_TABLES["silver_cot"] above was built with NO DOOR. R9 banned silver_cot from cascade_map outright
# and quantify() drops any node whose map_row() is None, so the weekly-COT pace engine has never been
# reachable. D1 splits the two things that blanket ban conflated -- positioning FETCHED and narrated
# past-tense as CONTEXT (admitted) and positioning as an ENGINE ref that may drive a fork or a regime
# (still banned, still build-failing) -- which is the split the registry's own prose already drew
# (tables.yaml: "levels + z, past tense; it NEVER drives a forecast or a fork").
#
# The lane is decided STRUCTURALLY, off fields a map row already carries. No new config surface, no
# marker anyone can forget to write, and every clause names the code path it closes:
#   * leg_mode: current -- an era-legged node reaches _era_delta -> _divergence, which IS the cross-era
#     fork. A positioning ref with era legs is a fork ref by construction.
#   * period_type: date -- the marketing-year fan (_my_span) is that same fork's window machinery, and
#     positioning is a dated weekly observation, never a marketing-year quantity.
#   * metric outside _TRADE_METRICS -- a trade metric is what seeds an RF-3 reroute PAIR (the OTHER
#     fork; see _pairable, defined with the pairing block below).
#   * narrate_unit != "flag" -- a 0/1 flag row is a REGIME MARKER (el_nino_flag/la_nina_flag), not an
#     observed level.
#   * a sub-annual pace grain -- without one the leg is structurally dead and the door is decorative.
# ONE definition, read twice: the fail-closed engine gate in quantify() below, and config_check's
# amended R9 at BUILD time (the lint_pace_collapse/check_pace_collapse bind idiom), so the lint and the
# runtime can never disagree about what "context" means. The chain/complex/transmission half of R9 is
# the lint's alone: those maps name a cascade_map ref BY NAME, which is a name-level ban, not a shape.
# OUTCOMES_JOIN D-OJ-18: `gold_cot_outcomes` joins the fence the day its lane exists, not the day its
# rows do. It is the J6 card -- the COT-keyed subset of the outcomes builder's output -- and it is in
# here for one reason: every leg of this fence keys on the TABLE ID, so a positioning-derived number
# served from a table OUTSIDE the set satisfies R9's letter while vacating the context-shape rule, the
# never-a-chain-hop ban and the never-a-relative-value-leg ban at once (skeptic F11). The id is defined
# below beside the leg that reads it; it is named as a literal here so this constant stays a plain
# frozenset of ids, which is what config_check's drift pin compares.
POSITIONING_TABLES: frozenset[str] = frozenset({"silver_cot", "gold_cot_outcomes"})
# The narration addendum the block carries when a context leg actually rendered. Phrased POSITIVELY and
# MEASURED: it names no flow idiom, because the surest way to put "crowded"/"stretched" into a draft is
# to write it into the prompt as a prohibition -- the r3 arm already emitted a residual flow idiom on
# the positioning row with ZERO cot rows in the panel, so this leg must not hand that sentence a
# vocabulary as well as a number. tests/unit/test_register_corpus.py pins count_flow_words() == 0 on
# this exact string, so an edit that smuggles the register back in fails the standing corpus.
POSITIONING_CONTEXT_ADDENDUM = (
    "POSITIONING CONTEXT: the managed-money rows above are OBSERVED weekly figures, each dated by its "
    "own report date. Narrate them as history in the past tense, keep every figure on the [N] handle "
    "and the series it was measured on, and state nothing about what positioning will do next -- this "
    "record holds no forward positioning claim and none may be read out of it.")


def positioning_context_violations(row: dict) -> list[str]:
    """Why `row` is NOT the narrow past-tense CONTEXT leg R9 admits -- an EMPTY list means it is. Only
    ever consulted for a POSITIONING_TABLES row; every other table is none of this rule's business.
    Pure and never raises: an unreadable row reads as a violation (fail-closed), never as an exception."""
    try:
        bad: list[str] = []
        if (row or {}).get("leg_mode") != "current":
            bad.append("leg_mode is not 'current' -- era legs are the cross-era FORK backbone")
        if (row or {}).get("period_type") != "date":
            bad.append(f"period_type {(row or {}).get('period_type')!r} is not 'date' -- positioning is a "
                       f"dated weekly observation, never a marketing-year fork window")
        if (row or {}).get("metric") in _TRADE_METRICS:
            bad.append(f"metric {(row or {}).get('metric')!r} seeds an RF-3 reroute PAIR (the other fork)")
        if (row or {}).get("narrate_unit") == "flag":
            bad.append("narrate_unit 'flag' is a REGIME MARKER, not an observed level")
        if _pace_grain(row) is None:
            bad.append("no sub-annual pace grain -- the context leg would be structurally dead")
        return bad
    except Exception:  # noqa: BLE001 -- a gate/lint predicate must never raise on an odd row
        return ["unreadable map row"]


# ── R4 PRICE-CONTEXT LANE (the Option C amendment, owner adjudication 2026-08-26) ──────────────────
# The R9/D1 shape applied to the price fence: a price table enters the engine ONLY through the narrow
# current-only context door. THE SHARED SHAPE LIVES HERE, exactly like positioning_context_violations
# above, because config_check may import this module and this module may not import config_check
# (cycle) -- one function, one register, so the build lint and the runtime belt in quantify() cannot
# drift (the review of 2026-08-26 refuted the lint-only first cut on precisely this: cascade_map is
# GITIGNORED config baked into images, so a map the lint never saw can reach a serving container).
# The DOCTRINE RECORD for the register's membership (what is admitted, what is fenced permanently and
# why, what waits for its own sitting) lives beside R4 in config_check.py -- this is the object, that
# is the adjudication.
PRICE_CONTEXT_TABLES: tuple = ("silver_pink_sheet",)   # == config_check.PRICE_TABLES, drift-pinned by test

PRICE_CONTEXT_METRICS: frozenset = frozenset({
    # the 9 input-cost levels (fertilizer + energy)
    "urea_usd_mt", "dap_usd_mt", "potassium_usd_mt", "phosphate_rock_usd_mt", "tsp_usd_mt",
    "blended_npk_index", "natural_gas_us_usd_mmbtu", "natural_gas_eu_usd_mmbtu", "brent_crude_usd_bbl",
    # the marine-protein ration input (the metric this amendment was adjudicated on)
    "fish_meal_usd_t",
    # ...and the 10 stored z twins, one per level (card doctrine: the stretch measure is a second METRIC)
    "urea_usd_mt_zscore_5yr", "dap_usd_mt_zscore_5yr", "potassium_usd_mt_zscore_5yr",
    "phosphate_rock_usd_mt_zscore_5yr", "tsp_usd_mt_zscore_5yr", "blended_npk_index_zscore_5yr",
    "natural_gas_us_usd_mmbtu_zscore_5yr", "natural_gas_eu_usd_mmbtu_zscore_5yr",
    "brent_crude_usd_bbl_zscore_5yr", "fish_meal_usd_t_zscore_5yr",
})


def price_context_violations(row: dict) -> list[str]:
    """Why `row` is NOT the narrow current-only CONTEXT leg the R4 amendment admits -- an EMPTY list
    means it is. Only ever consulted for a PRICE_CONTEXT_TABLES row; every other table is none of this
    rule's business. SIX terms (the review of 2026-08-26 added period_type and agg after proving the
    four-term first cut failed OPEN on a marketing-year fork window and on an agg=mean collapse):
      * metric in PRICE_CONTEXT_METRICS -- the register: input costs + fish_meal + their z twins;
        every estate-target benchmark stays fenced on SELF-REFERENCE (the adjudication in
        config_check.py's R4 block);
      * leg_mode 'current' -- era legs are the cross-era FORK backbone, and the pink sheet is
        LATEST-ONLY with retroactive WB revisions (the C-2 era vector);
      * period_type 'date' -- a monthly dated observation, never a marketing-year fork window (the R9
        term, borrowed for the same reason it exists there);
      * agg 'latest' -- the context leg is THE current standardized reading; a sum/mean over a price
        history is a number nobody quotes (cascade's own _PRICE_COLLAPSE_BANNED doctrine, which scopes
        only pace collapse and so cannot cover this);
      * country_rule 'none' -- the card is wide and flat (no commodity_col, no country_col); the
        metric IS the series;
      * narrate_unit != 'flag' -- a 0/1 row is a REGIME MARKER, and a price may never mint one.
    C-2's OTHER vector -- a historical-asof replay serving today's revision as if known then -- is a
    per-TURN condition no row shape can express: quantify()'s `price_replay` kwarg (resolved at the
    answer.py seam, the outlook discipline) closes it in the belt below.
    Pure and never raises: an unreadable row reads as a violation (fail-closed)."""
    try:
        bad: list[str] = []
        metric = (row or {}).get("metric")
        if metric not in PRICE_CONTEXT_METRICS:
            bad.append(f"metric {metric!r} is not in PRICE_CONTEXT_METRICS -- the register admits input "
                       f"costs + fish_meal (and their z twins) only; every estate-target benchmark stays "
                       f"fenced (self-reference), and the rest of the card is undecided")
        if (row or {}).get("leg_mode") != "current":
            bad.append("leg_mode is not 'current' -- the pink sheet is LATEST-ONLY with retroactive WB "
                       "revisions and no as-of replay, so an era/replay leg is dishonest by construction "
                       "(and era legs are the cross-era FORK backbone)")
        if (row or {}).get("period_type") != "date":
            bad.append(f"period_type {(row or {}).get('period_type')!r} is not 'date' -- a monthly dated "
                       f"observation, never a marketing-year fork window")
        if (row or {}).get("agg") != "latest":
            # NO DEFAULT (2026-08-27, the fertilizer/energy sitting's hazards sweep): this term used to
            # read row.get("agg", "latest") while _node_specs' current leg reads row.get("agg", "series")
            # -- so an OMITTED agg linted green and then compiled a 365-day SERIES collapse over a price
            # history, the exact defect this term refuses, arriving through the default disagreement
            # rather than a declaration. An omitted agg is now a violation: `agg: latest` is written
            # explicitly on every price-context row (all eight donors do).
            bad.append(f"agg {(row or {}).get('agg')!r} is not 'latest' -- a sum/mean over a price history "
                       f"is a number nobody quotes (and an OMITTED agg compiles as 'series', so it must "
                       f"be declared)")
        if (row or {}).get("country_rule") != "none":
            bad.append(f"country_rule {(row or {}).get('country_rule')!r} is not 'none' -- the card is wide "
                       f"and flat (no commodity_col, no country_col); the metric IS the series")
        if (row or {}).get("narrate_unit") == "flag":
            bad.append("narrate_unit 'flag' is a REGIME MARKER, not an observed price")
        return bad
    except Exception:  # noqa: BLE001 -- a gate/lint predicate must never raise on an odd row
        return ["unreadable map row"]


def _positioning_rendered(records: list, kept: list) -> bool:
    """True when at least one POSITIONING context leg actually produced a row this turn. An honest
    absence renders no line, so it earns no addendum either (the E-STREAK-NODATA idiom)."""
    keys = {g["key"] for g in kept if ((g or {}).get("row") or {}).get("table") in POSITIONING_TABLES}
    if not keys:
        return False
    return any(r.get("node_key") in keys and r.get("status") == "ok" and (r.get("rows") or [])
               for r in records)


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
    # W1.1 basin TAIL rider: one sibling `<metric>_tail_share` read beside the CURRENT weather-z leg.
    # Only basin rows carry the metric, so a non-basin country returns record_silent -> no line ever.
    if asof and row.get("table") == _WEATHER_Z_TABLE and row.get("metric") in _BASIN_TAIL_METRICS:
        specs.append({**base, "metric": f"{row['metric']}{_TAIL_SUFFIX}", "leg": ("tail", None),
                      "era_idx": None, "my": None, "t1": _plus_days(asof, -365), "t2": asof,
                      "asof": asof, "agg": "latest", "period": None})
    return specs


def _run_one(qfn, spec: dict, *, futures_newest_first: bool | str = False) -> dict:
    """Unpack a spec and fetch; NEVER raises (a malformed spec returns an error record, R6).

    `futures_newest_first` (S1 canary) rides straight through to fetch_window; default False keeps every
    existing call byte-identical, including the two-positional-arg lambdas in the pool.map waves."""
    try:
        rec = fetch_window(qfn, table=spec["table"], metric=spec["metric"], commodity=spec["commodity"],
                           country=spec["country"], t1=spec["t1"], t2=spec["t2"], asof=spec["asof"],
                           agg=spec["agg"], period=spec["period"], period_type=spec["period_type"],
                           futures_newest_first=futures_newest_first)
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
# The block's one header string, extracted so the two return paths below cannot render it differently.
# BYTE-IDENTICAL to the literal it replaced -- the prompt prefix is a cached surface.
_BLOCK_HEADER = "OBSERVED CASCADE NUMBERS (as-known at each leg's asof; the record then vs now):\n"


def _episode_leg_or_nothing(sg, qfn, asof, calls: list, *, futures_newest_first: bool | str = False) -> tuple:
    """Run the J4 episode leg and write its trace; `([], [])` on any failure. R6 belt at the ONE place
    both `quantify` return paths reach it, so an outcomes failure degrades to the absence branch the
    episodes persona already treats as normal, and never to a broken turn.

    The trace key is written whenever the leg produced ANY record -- including a turn where every window
    declined. That is deliberate: for this leg a decline is the expected answer, so `fired == bool(key)`
    would be the wrong reading and an absent key must mean "the leg did not run".

    `futures_newest_first` (S1 canary) rides through to the tape reads. It is threaded HERE rather than
    read here for the same reason the flag itself exists at ONE seam: this helper has two call sites in
    quantify (the all-dark early return and the post-engine append) and a flag read at each would be two
    reads that can disagree within one turn."""
    try:
        lines, trace = _episode_outcome_legs(sg, qfn, asof, calls, len(calls),
                                             futures_newest_first=futures_newest_first)
    except Exception:  # noqa: BLE001 -- R6: never break the v1 answer
        return [], []
    if trace:
        try:
            sg.trace["quantify_episode_outcomes"] = trace
        except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
            pass
    return lines, trace


def quantify(sg, graph, *, qfn, asof, near, extra_number_calls: list, xc_request: dict | None = None,
             comove: bool = False, price_request: dict | None = None, pace: bool = False,
             chain: bool = False, transmission: bool = False, outlook: bool = False,
             headline: bool = False, episode_outcomes: bool = False,
             cot_outcomes: bool = False, futures_newest_first: bool | str = False,
             price_replay: bool = False, rv_reading: bool = False,
             rv_regional: bool = False, derived_arith: bool = False,
             cascade_walk: dict | None = None,
             extreme_locator: dict | None = None,
             extrema_own_date: bool = False) -> tuple:
    """Select grounded nodes with mapped refs, derive analogue-era windows from their dated props, build
    per-node leg GROUPS (era legs + a current rhyme leg), detect cross-country REROUTE pairs (RF-3:
    natural two-node pairs + the synthesized primary-country beneficiary), cap on WHOLE pair-atomic
    UNITS, fan the specs concurrently over the pg pool, PRE-SCALE + inject citable [N] rows (continuing
    the N-count), compute CROSS-ERA deltas + the divergence flag + the cross-country REROUTE (RF-4), and
    return (prompt_block, trace_list, reroute_trace). extra_number_calls is appended IN PLACE.

    `outlook` and `headline` are the two flags read at the answer.py quantify SEAM and threaded here as
    ARGUMENTS (the pace/price_request discipline -- NEVER an env read inside cascade.py), see the R9 gate
    and _set_headline below. `price_replay` (the R4 amendment, 2026-08-26) is the SAME idiom for the
    price-context lane's per-turn half: resolved at the answer seam as "this turn's asof is historical",
    it drops every PRICE_CONTEXT_TABLES leg -- the pink sheet is latest-only with retroactive revisions,
    so at a historical asof the leg would serve today's revision as if known then (the archaeology's C-2
    replay vector, which no row shape can express). Default False = byte-identical. `episode_outcomes` (OUTCOMES_JOIN J4) and `cot_outcomes` (J6) follow the
    same omit-when-off idiom: both default False, so a call that does not pass them is byte-identical.
    `rv_reading` (RV-READING, 2026-08-29) is the SAME idiom once more: read at answer._rv_reading_on()
    and threaded to _run_xc as `reading`, with `price_replay` riding beside it as that leg's replay belt
    (a historical-asof turn drops the reading whole -- C-2). An rv_reading-less call is byte-identical.

    `futures_newest_first` (FUTURES_READPATH S1, D-FR-10) is the SAME idiom for the SAME reason, one layer
    lower: read at `answer._futures_newest_first_on()` and threaded here, so this module still performs no
    env read of any kind. It reaches every read below that can compile a FUTURES SERIES -- the cascade leg
    wave (_run_one -> fetch_window), the price pair, the vertical chain engine, and the J4 tape reads --
    and, by construction, NOT the reads whose table is a compile-time constant with no `contract_month_col`:

      * `_psd_component_rows` -> fetch_window(table=_PSD_TABLE | _PSD_ATTR_TABLE), reached through
        _world_su_ratio / _world_attribute_total / _leg_world_deltas from the RV2 + transmission engines;
      * `_cot_outcome_read`  -> fetch_window(table=COT_OUTCOME_TABLE = "gold_cot_outcomes").

    Those two are UNFLAGGED BY DESIGN, on the same footing as numbers_parity/cascade_census: their table is
    a module constant in this file (L2-5 made the PSD surface a kwarg, so it is the two PSD cards rather
    than one literal -- the pin moved with it), `_newest_first_applies` keys on `ts.contract_month_col`,
    and no card any of them can name declares one -- so a threaded flag could not change one byte of their
    SQL, and a five-deep signature change through the PSD chain would buy churn instead of coverage. It is
    a MEASURED omission, not an assumed one: test_futures_readpath_pins pins that every card those sites
    can reach carries no contract_month_col, so the day one grows a delivery-month axis the pin reds and
    this paragraph is what gets read.

    `extreme_locator` (D-XL, E32) is the SAME omit-when-off idiom once more, and it is a REQUEST DICT
    rather than a bool because the leg's whole input is the planner's resolved intent -- board,
    direction, kind, scope, since -- resolved at the ORCHESTRATOR and threaded here as an ARGUMENT. This
    module performs NO env read and NO classification of any kind; absent -> byte-identical, and an
    injected quantify fake written against the older signature stays valid. It is appended LAST at BOTH
    return sites for the walk's own stated reason (it runs after every other engine, so each existing
    line keeps its byte position) and at BOTH because the leg owns NO groups -- its input is a request
    dict, not a grounded node -- so it must not die on the early return.
    Never raises (R6 -- the seam also belts it)."""
    _set_headline(headline)
    groups = []
    dark = 0                                                      # A6 DarkRefNodes: grounded, ref unmapped
    for n in _select_nodes(sg, graph):
        ref = _silver_ref(n)
        row = map_row(ref)
        if row is None:
            # A6: THE metric this whole lane exists to measure -- the walk grounded a driver that DECLARES
            # a series and the map had none for it (160 dark refs against 16 mapped). Counted at the ONE
            # drop site that means "dark ref". Two things deliberately excluded: a node with NO silver_ref
            # at all (a contract node, or a driver that never claimed a series -- there is nothing to be
            # dark ABOUT, and counting them would make the metric a walk-size proxy), and the chain-hop
            # map_row miss in _chain_resolve_hop, which is CONFIG DRIFT on an authored chain that
            # check_chain_map already fails the build on.
            if ref:
                dark += 1
            continue                                              # unmapped OR deferred -> stays qualitative
        # R9 CONTEXT LANE (D1), BOTH halves. (a) a positioning table enters the engine ONLY through the
        # narrow past-tense context door -- config_check fails the BUILD on a mis-shaped row and this is
        # the runtime belt, so a hand-edited or monkeypatched map can never widen the door either.
        # (b) D1's OUTLOOK CARVE-OUT, which is not a shape rule and cannot be one: "do NOT proceed on the
        # outlook lane". register.py:689-694 releases the FLOW fence by design under OUTLOOK, and
        # rep_outlook_r3.md:397 measured a residual "crowded long" on the target row with ZERO cot rows in
        # the panel -- handing that sentence a dated number is exactly what D1 refused. The context leg is
        # therefore FENCED-lane only. Fail-closed on both: any violation, or an outlook turn, and the node
        # stays qualitative, exactly as it does today.
        if row.get("table") in POSITIONING_TABLES and (outlook or positioning_context_violations(row)):
            continue
        # R4 PRICE-CONTEXT LANE (the Option C amendment, 2026-08-26), the SAME both-halves shape:
        # (a) the runtime belt -- config_check fails the BUILD on a mis-shaped or unregistered row,
        # and this line means a hand-edited or monkeypatched map cannot widen the door either (the
        # map is gitignored config baked into images; a tree the lint never ran on can reach a
        # container, which is why the review refuted the lint-only first cut); (b) `price_replay`,
        # the per-turn half no row shape can express -- at a historical asof the latest-only,
        # retroactively-revised pink sheet would serve today's revision as if known then (C-2), so
        # a replay turn keeps every price-context node qualitative. Fail-closed on both.
        if row.get("table") in PRICE_CONTEXT_TABLES and (price_replay or price_context_violations(row)):
            continue
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
    # A6 (F3): stamped on EVERY quantifying turn, zero included -- the reader
    # (orchestrator._emf -> DarkRefNodes) treats an ABSENT key as "this turn never quantified" and a 0 as a
    # real measurement, so the write must happen BEFORE the all-dark early return below. A turn with 6
    # grounded drivers and 6 unmapped refs is the exact shape the counter exists to make visible, and it
    # takes that early return.
    try:
        sg.trace["quantify_dark_refs"] = dark
        # WALK-CHARTER A2 (the uncounted base wave): stamped 0 HERE -- before the all-dark early
        # return, the quantify_dark_refs discipline verbatim -- then OVERWRITTEN with the wave's real
        # spec count after the fan below. One key, present on every quantifying turn, zero included;
        # ABSENT still means "this turn never quantified", never "zero reads".
        sg.trace["quantify_wave_reads"] = 0
    except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
        pass
    if not groups and not chain and not transmission:
        # OUTCOMES_JOIN J4: the episode leg owns NO groups -- its windows come from the trace
        # answer._l2_blocks already stamped -- so it must not die on this early return. That would kill it
        # on exactly the turns it serves: a thin walk with dated episodes and no mapped silver ref is the
        # modal episodes turn, and a leg that only ran when the cascade also fired would be a leg whose
        # coverage tracked something unrelated to episodes. Flag off -> the kwarg is absent -> this branch
        # is byte-identical to today (no read, no line, no trace key).
        e_lines: list = []
        if episode_outcomes:
            e_lines = _episode_leg_or_nothing(sg, qfn, asof, extra_number_calls,
                                              futures_newest_first=futures_newest_first)[0]
        # CASCADE EPISODE WALK: like J4, the leg owns NO groups (its firings come off the trace
        # answer._l2_blocks already stamped) so it must not die on this early return -- the v3
        # refute named exactly this branch as the modal episodes turn. Runs AFTER J4 so the A4
        # dedup gate reads a key J4 has already written. Kwarg absent -> byte-identical.
        if cascade_walk:
            e_lines = e_lines + _cascade_walk_leg_or_nothing(
                sg, graph, cascade_walk, qfn, asof, extra_number_calls,
                futures_newest_first=futures_newest_first)[0]
        # D-XL: like J4 and the walk, the locator owns NO groups -- its input is the planner's resolved
        # request dict -- so it must not die on this early return either. Kwarg absent -> byte-identical.
        if extreme_locator:
            e_lines = e_lines + _extreme_locator_leg_or_nothing(
                sg, graph, extreme_locator, qfn, asof, extra_number_calls,
                futures_newest_first=futures_newest_first)[0]
        if e_lines:
            return _BLOCK_HEADER + "\n".join(e_lines), [], []
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
    # ONE wave; executor width via _cascade_width -- a single turn's fan-out must never drain the
    # SHARED pool (the 2026-08-25 wedge; see the helper's docstring).
    from concurrent.futures import ThreadPoolExecutor

    width = _cascade_width(len(flat))
    with ThreadPoolExecutor(max_workers=width) as pool:
        records = list(pool.map(                                     # order preserved; _run_one never raises
            lambda s: _run_one(qfn, s, futures_newest_first=futures_newest_first), flat))
    try:
        # A2: the wave's REAL spec count (every flat spec ran exactly one _run_one read). This is the
        # single largest read producer on a quantifying turn and was invisible to any ceiling before.
        sg.trace["quantify_wave_reads"] = len(flat)
    except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
        pass
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
    # W1.1 basin tail lines: ungated -- the spec only exists for gold_weather_z z-rows, and only basin
    # surfaces return rows, so the blast radius is the basin nodes by construction; the serving deploy
    # is the rollout gate and the judged deck is the judge.
    t_lines, t_trace = _tail_legs(records, kept, len(extra_number_calls), extra_number_calls)
    if t_trace:
        try:
            sg.trace["quantify_basin_tail"] = t_trace
        except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
            pass
        block_lines = block_lines + t_lines
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
        # RV-READING: `rv_reading` (answer.py-threaded, the [F3] idiom) and quantify's own price_replay
        # ride down as arguments -- both default False, so an rv_reading-less call is byte-identical.
        _xc_base = len(extra_number_calls)                        # A3: the fork's calls-delta baseline
        xc_lines, xc_trace = _run_xc(xc_request, sg, graph, groups, qfn, asof, near, extra_number_calls,
                                     comove=comove, reading=rv_reading, replay=price_replay,
                                     rv_regional=rv_regional, derived_arith=derived_arith,
                                     extrema_own_date=extrema_own_date)
        if xc_trace:
            # A3 (walk charter): the fired fork's spend, measured as the calls-delta at fork exit --
            # the adjudicated proxy (the RV sub-legs count their own `fetches` beside it). This is
            # what lets a turn ceiling read RV2/comove instead of declining `turn_spend_unknown` on
            # exactly the cross-commodity turns a consequence leg fires on.
            xc_trace["net_reads"] = len(extra_number_calls) - _xc_base
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
                                       extra_number_calls, len(extra_number_calls),
                                       futures_newest_first=futures_newest_first)
        if p_trace and p_trace.get("price_leg"):
            try:
                sg.trace["quantify_price_leg"] = p_trace
            except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
                pass
            block_lines = block_lines + p_lines
        elif p_trace:
            # A2/v3 STEP 2(4): a POST-FETCH pair-atomic decline now returns a payload (price_leg:
            # False + net_reads) so the two spent fetches are countable. Routed on the discriminator
            # to an UNREGISTERED key -- the quantify_chain_decline / quantify_transmission_decline
            # sibling shape -- so eval's `price_leg_fired` (bool of the FIRED key) is byte-unchanged.
            try:
                sg.trace["quantify_price_leg_decline"] = p_trace
            except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
                pass
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
        c_lines, c_trace, c_decline = _chain_legs(sg, graph, kept, records, qfn, asof, near,
                                                  extra_number_calls,
                                                  futures_newest_first=futures_newest_first)
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
    # OUTCOMES JOIN J4 -- the EPISODE MAGNITUDE leg. Gated ONLY by the answer.py-threaded
    # `episode_outcomes` kwarg (GRAPHRAG_EPISODE_OUTCOMES is read at that seam, never here -- the
    # pace/price_request discipline). Flag off -> the kwarg is absent -> no read, no line, no trace key,
    # byte-identical. It runs AFTER every other engine so each existing line keeps its byte position, and
    # it needs no groups of its own: its windows come from `sg.trace['episodes_injected']`, which
    # answer._l2_blocks stamped BEFORE this call. On FIRE the engine writes its own trace key (the
    # xc/pace idiom: fired == bool(key)); a turn where every window declined still writes the key,
    # because a recorded decline is the whole point of a leg whose normal answer is an absence.
    if episode_outcomes:
        block_lines = block_lines + _episode_leg_or_nothing(
            sg, qfn, asof, extra_number_calls, futures_newest_first=futures_newest_first)[0]
    # CASCADE EPISODE WALK: AFTER the J4 call, and the ordering is load-bearing rather than
    # cosmetic -- the A4 dedup gate reads `quantify_episode_outcomes`, which J4 writes above.
    # Kwarg absent -> no read, no line, no trace key, byte-identical.
    if cascade_walk:
        block_lines = block_lines + _cascade_walk_leg_or_nothing(
            sg, graph, cascade_walk, qfn, asof, extra_number_calls,
            futures_newest_first=futures_newest_first)[0]
    # D-XL: the LOCATOR, appended LAST so every existing line keeps its byte position. Kwarg absent ->
    # no read, no line, no trace key, byte-identical.
    if extreme_locator:
        block_lines = block_lines + _extreme_locator_leg_or_nothing(
            sg, graph, extreme_locator, qfn, asof, extra_number_calls,
            futures_newest_first=futures_newest_first)[0]
    # OUTCOMES JOIN J6 -- the COT OUTCOME PAIRING, CONTEXT LANE ONLY (D-OJ-17/18). Gated on the threaded
    # `cot_outcomes` kwarg AND on `not outlook` AND on a positioning context leg having actually
    # rendered. All three, because D1's ratified text is a SPLIT and the half most easily dropped is the
    # OUTLOOK carve-out: under OUTLOOK register.py releases the flow fence by design, so a cited,
    # arrow-free conditional-performance sentence returns False from `_is_banned_sentence` -- which is
    # why D-OJ-17 picks option (a) and holds the ref out of outlook turns ENTIRELY rather than trying to
    # phrase its way past a fence that is down.
    if cot_outcomes and not outlook:
        try:
            c_lines, c_trace = _cot_outcome_legs(records, kept, len(extra_number_calls),
                                                 extra_number_calls, qfn=qfn, asof=asof)
            if c_trace:
                try:
                    sg.trace["quantify_cot_outcomes"] = c_trace
                except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
                    pass
            if c_lines:
                block_lines = block_lines + c_lines + [COT_OUTCOME_ADDENDUM]
        except Exception:  # noqa: BLE001 -- R6: never break the v1 answer
            pass
    # R9 CONTEXT-LANE ADDENDUM (D1): when a positioning context leg actually rendered, ONE narration line
    # rides the block so the prose stays what the leg is -- dated observed history. Appended LAST, after
    # every engine's lines: it says "the managed-money rows above", and at its old position (right after
    # the pace block) the reroute/xc/price-leg/chain rows still followed it, so "above" named a set the
    # reader could not delimit. Only ever appended on a leg that actually produced a row.
    if _positioning_rendered(records, kept):
        block_lines = block_lines + [POSITIONING_CONTEXT_ADDENDUM]
    block = (_BLOCK_HEADER + "\n".join(block_lines)) if block_lines else None
    return block, trace, r_trace


# ── fork engine + ratio normalizer (B-S4) ────────────────────────────────────────────────────────────
# A2b FLAG (GRAPHRAG_CASCADE_HEADLINE). A2b's own rule: "Ship behind its own flag, defaulting to today's
# behaviour ... A detector loosening/tightening moves strip_rate on every deck, so it must be
# independently revertible from A2a." OFF (the default) is byte-identical to pre-A2b: every level line,
# every `shown` binding, every pre-scale and EVERY cross-era delta/divergence magnitude reads rows[0].
#
# WHY A MODULE FLAG AND NOT A KWARG. `_headline_row` is reached from `_float_val` / `_scaled_val` /
# `_prescaled` and thence from ~10 formatters and the era/divergence engines; threading a bool through
# all of them would be a signature change per formatter for a value that is CONSTANT within a process
# (it is env-derived at the answer.py seam, so two concurrent turns can never disagree about it).
# This module still performs NO env read of any kind -- test_transmission_chain's
# `test_engine_never_reads_the_env_and_never_mints_a_threshold` scans this file's SOURCE for the tokens,
# so even naming them in a comment reds it, and that strictness is the point. quantify() sets this from
# its `headline` kwarg, so the ENGINE is gated by the ARGUMENT and a mis-plumbed enable cannot fire it.
# Every fetch runs on the pool BEFORE any formatter, so no worker thread ever reads it.
_HEADLINE_ON = False


def _set_headline(on: bool) -> None:
    """Bind the A2b headline rule for this process from quantify()'s threaded `headline` kwarg."""
    global _HEADLINE_ON
    _HEADLINE_ON = bool(on)


def _headline_row(rec) -> dict | None:
    """The ONE row a level line stands for: the FRESHEST observation on the record, picked with the SAME
    chronology key the CITATION side uses (citations._row_order_key) -- never rows[0].

    A2b RESIDUAL RCA (2026-08-01). A marketing-year leg fetches agg='latest' (one row), but a
    date/year_month ERA leg fetches agg='series' (_node_specs:609) -- a Jan-Jun ONI leg carries six
    monthly rows -- and rows[0] is the OLDEST print. The panel line headlined rows[0] while EVERY
    citation-side projection of that same call headlines max(rows) instead: the reader's `## Sources`
    block (answer.py:1313 -> :1480 -> citations.from_number:104) and the judge's OBSERVED-NUMBERS panel,
    which sees cascade rows ONLY as kind=number citations (eval.py:1464-1476). On pb_seasonality_aware
    the panel printed the Jan-2012 ONI (-0.72) and the Jun-2012 ONI (0.06) went to the judge under the
    SAME handle, so a FAITHFUL transcription was scored as a fabricated figure -- and `shown`, bound to
    the printed value, agreed with the model and correctly did not charge it. The leak was never an
    unbound append site: it was two headlines for one handle. Single-row records (every MY leg, every
    synthetic) are untouched by construction.

    FLAG-OFF (the default) returns rows[0] -- today's behaviour, byte-identical -- so A2b is revertible
    without touching A2a. See _HEADLINE_ON above."""
    rows = (rec or {}).get("rows") or []
    if not rows:
        return None
    if not _HEADLINE_ON:
        return rows[0]
    try:
        from leviathan.graphrag.citations import _row_order_key
        return max(rows, key=_row_order_key)
    except Exception:  # noqa: BLE001 -- an unorderable row must degrade, never break the cascade
        return rows[0]


def _float_val(rec) -> float | None:
    """FLOAT-CAST the HEADLINE row's value (R9: Q.run returns values as STRINGS -- '0.36'*100 repeats the
    string). Reading the headline row rather than rows[0] is what keeps the printed figure, the `shown`
    binding, the injected row and the citation label on ONE observation (_headline_row)."""
    src = _headline_row(rec)
    if src is None:
        return None
    try:
        return float(str(src.get("value")).replace(",", ""))
    except (TypeError, ValueError):
        return None


_GUARD_COLS = ("release_date", "week_ending_date", "data_date", "date", "year", "month")

# CYCLE-5 (2026-08-07) VINTAGE-2: the AS-KNOWN columns a SYNTHETIC row must inherit from the row it was
# derived FROM. `_GUARD_COLS` above is the PIT-backtest's provenance set and rides `_provenance`, a nested
# key nothing on the render path reads: `citations.from_number` takes its `[known ...]` stamp off the ROW
# ITSELF (`knowledge_date`/`data_date`, plus the year_month fallback added this cycle). So every derived
# leg -- PSD `*_delta` / `*_pct` / `*_era_diff`, the T2a pace rows, the SEAM-B farm-price pair -- shipped
# to the reader with no vintage at all, while the un-suffixed read of the SAME table stamped correctly.
# Measured on gate-2 (both passes, same families): e.g. "[N15] USDA PSD ending_stocks_mt_delta ... MY2024 =
# -0.479 MMT" with no stamp, directly under "[N14] ... ending_stocks_mt ... [known 2025-03-10]".
# THE DATE IS INHERITED, NEVER MINTED: it is copied off the source row whose value produced the derivation,
# so a synthetic row can only ever be as-known as the observation behind it. `year`/`month` ride too, so a
# derived leg over a year_month table (ONI/IOD/gold_weather_z) inherits the same fallback identity the
# fetched row renders with.
_VINTAGE_COLS = ("knowledge_date", "data_date", "year", "month")


def _row_vintage(src: dict | None) -> dict:
    """The as-known columns present on `src`, as a dict to splat onto a synthetic row ({} when it has
    none -- then the synthetic row renders exactly as it did before, which is the honest outcome for a
    source row that carries no date either)."""
    return {k: (src or {})[k] for k in _VINTAGE_COLS if (src or {}).get(k) not in (None, "")}


# ── CYCLE-5 FIX-CYCLE-2 (2026-08-07) VINTAGE-2b: ONE endpoint rule for BOTH synthetic mint sites ───────
# THE MEASURED DEFECT (fix-cycle-2 review, blocker 3). `_delta_call` read `rows[0]` and `_pace_synth` read
# `rows[-1]`, i.e. the two synthetic mint sites encoded OPPOSITE answers to the same question -- "which row
# is the later endpoint this derived value is as-known at". That disagreement was tolerable while the row
# only fed the machine-side `_provenance`; VINTAGE-2 promotes it to the READER-FACING `[known ...]` stamp,
# and on a date/year_month ERA leg (agg='series', the six-monthly-row shape `_headline_row`'s own A2b RCA
# documents) `rows[0]` is the OLDEST print. A Jan..Jun 2012 ONI leg therefore rendered its Jun-minus-Jan
# delta as `[known 2012-01]` -- a date at which the delta could not have been computed. Previously those
# rows carried NO stamp (honest silence); a false stamp is the wrong side of the one-sided rule this file
# states everywhere ("a missed warning, never a false one").
#
# WHY THIS IS NOT `_headline_row`, and that distinction is the whole of the fix. `_headline_row` is
# KILL-SWITCHED (`_HEADLINE_ON` / GRAPHRAG_CASCADE_HEADLINE, DEFAULT-OFF) and returns `rows[0]` when off,
# so routing the two mint sites through it would have left the false January stamp in place in every
# production configuration shipped to date -- a no-op dressed as a fix. The A2b switch governs WHICH ROW A
# LEVEL LINE PRINTS; it has nothing to say about which observation a DERIVED row is as-known at. The
# ordering rule is `_headline_row`'s (citations._row_order_key, the same key the citation side uses, so the
# two never disagree about chronology) applied UNCONDITIONALLY here.
# ONE-SIDED BY CONSTRUCTION: the endpoint is the FRESHEST row of the record the derivation spans, so a
# synthetic row can only ever claim to be known LATER than its inputs, never earlier -- the direction that
# can cost a staleness clause, never a PIT leak.
def _endpoint_row(rec) -> dict:
    """The LATER endpoint of the window a synthetic row is derived over: the freshest row on the record by
    `citations._row_order_key`. `{}` for a rowless record (then `_row_vintage` contributes nothing and the
    synthetic row renders exactly as it did pre-CYCLE-5). Never raises -- an unorderable row set degrades
    to `_headline_row`'s answer, which is what every other reader of this record already sees."""
    rows = (rec or {}).get("rows") or []
    if not rows:
        return {}
    try:
        from leviathan.graphrag.citations import _row_order_key
        # ROW POSITION IS THE FINAL TIEBREAKER, and it is load-bearing for the pace twin. `_row_order_key`
        # spans (data_date, year, month, period, knowledge_date) ONLY: a series keyed on `week_ending_date`
        # alone -- every ESR pace leg -- ties on ALL of them, and bare `max()` returns the FIRST maximal
        # element, i.e. rows[0]. `_pace_synth` has always read rows[-1] and is right to; folding position in
        # keeps that answer byte-identical for an un-keyed ASC series while the keyed series (the ONI/IOD era
        # legs this fix is for) still resolves by chronology.
        return max(enumerate(rows), key=lambda t: (_row_order_key(t[1]), t[0]))[1]
    except Exception:  # noqa: BLE001
        return _headline_row(rec) or rows[0]


def _scaled_val(rec: dict, row: dict) -> float | None:
    """The HEADLINE row PRE-SCALED to narrate_unit -- the ONE magnitude a level line prints. Shared by the
    formatters and by the `shown` binding so the printed figure and the recorded figure cannot drift."""
    v = _float_val(rec)
    return None if v is None else v * float(row.get("scale", 1) or 1)


def _shown(call: dict, *values) -> dict:
    """Bind the magnitudes a reader LINE actually prints to the call record its [N] handle indexes, and
    return the call (so an append site stays one expression).

    W4 A/B RCA (2026-08-01): the verifier pooled EVERY row of the cited call, but an era-window call holds
    the whole window (a Jan-Jun ONI leg carries ~6 monthly rows) while its line prints ONE endpoint. A model
    that quoted a member row -- -0.693675 is a real row value, not an invention -- and narrated it as the
    window's headline stat matched the pool and cleared: all four measured fabrications on
    pb_seasonality_aware were never charged. `shown` is the panel's own testimony about what it displayed.
    Values only, never strings; ONE physical line's magnitudes, including a rendered integer count.
    WHICH endpoint a windowed line prints is _headline_row's contract -- binding here is only honest while
    the line, the injected row and the citation label all name that same observation."""
    vals = [float(v) for v in values if v is not None]
    if vals:
        call["shown"] = vals
    return call


def _prescaled(rec: dict, row: dict, n: int) -> dict:
    """Deep-copy the call-record with the HEADLINE row PRE-SCALED to narrate_unit (the ratio normalizer:
    su_ratio 0.36 -> 36.0/'%'), carrying that row's PIT guard-column provenance forward (R10) so the
    pinned-asof backtest can check it. The scaled row is the one _headline_row picks -- i.e. the one
    citations.from_number will headline -- so a windowed leg can never publish a SCALED figure on the
    line and a RAW one in the Sources block. Position is preserved: the window stays chronological."""
    import copy
    out = copy.deepcopy(rec)
    v = _float_val(rec)
    scale = float(row.get("scale", 1) or 1)
    src = _headline_row(rec)
    if v is not None and src is not None and out.get("rows"):
        i = next((k for k, r in enumerate(rec.get("rows") or []) if r is src), 0)
        tgt = out["rows"][i]
        tgt["value"] = v * scale
        tgt["unit"] = row.get("narrate_unit") or tgt.get("unit")
        prov = {k: src.get(k) for k in _GUARD_COLS if src.get(k) is not None}
        if prov:
            tgt["_provenance"] = prov
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
    src = _endpoint_row(rec)                                  # VINTAGE-2b: the LATER endpoint, never rows[0]
    prov = {k: src.get(k) for k in _GUARD_COLS if src.get(k) is not None}
    unit = "%" if kind == "pct" else (row.get("narrate_unit") or "")
    q = {**(rec.get("query") or {}), "metric": f"{row.get('metric')}_{kind}"}
    if period is not None:
        q["period"] = period
    return {"query": q,
            # CYCLE-5 VINTAGE-2: the LATER endpoint's own as-known columns ride the ROW, not only the
            # nested `_provenance` -- that is the key `citations.from_number` reads for the [known] stamp.
            "rows": [{"value": round(delta, 4), "unit": unit, **_row_vintage(src),
                      **({"_provenance": prov} if prov else {})}],
            "status": "ok"}


def _pace_synth(rec: dict, row: dict, value, n: int, *, kind: str, unit: str) -> dict:
    """T2a: a synthetic pace call-record (twin of _delta_call) so a narrated pace fact IS a row value
    (citable + value-checkable by the all-numbers guard). Provenance = the LATEST point's guard columns
    (ASC series -> rows[-1]): the pace fact is as-known at the newest observation."""
    src = _endpoint_row(rec)                                  # VINTAGE-2b: the SAME rule as `_delta_call`

    prov = {k: src.get(k) for k in _GUARD_COLS if src.get(k) is not None}
    q = {**(rec.get("query") or {}), "metric": f"{row.get('metric')}_{kind}"}
    return {"query": q,                                       # CYCLE-5 VINTAGE-2, the pace twin
            "rows": [{"value": value, "unit": unit, **_row_vintage(src),
                      **({"_provenance": prov} if prov else {})}],
            "status": "ok"}


# GN-2 W1.4 (2026-08-22): PER-TABLE extra period-key aliases. A table whose date_col IS its
# knowledge_date_col surfaces ONLY `knowledge_date` in query._extras (the dedup at _extras' data_date
# branch), so the legacy alias list below misses every live row and the key falls to ("_row", idx) --
# EVERY ROW ITS OWN PERIOD -- and the cross-section collapse silently never groups: on a
# per-destination table the "pace" delta is then destinationB-minus-destinationA inside one week, a
# fabrication wearing a real [N] row (the recon's R1 FATAL: the naive PACE_TABLES entry alone ships
# it). Scoped PER TABLE rather than adding knowledge_date to the legacy list: on silver_cot /
# silver_pink_sheet / silver_mpob the ("_row", idx) branch is load-bearing and pinned (_pace_row_date's
# docstring records that deliberate exclusion) -- those tables are one row per period BY GRAIN, and
# this registry must never widen behavior it cannot see the grain of.
_PACE_PERIOD_KEY_EXTRA: dict[str, tuple[str, ...]] = {
    "silver_fgis": ("knowledge_date",),   # date_col == knowledge_date_col == week_ending_date
}


def _pace_period_key(rr: dict, idx: int, extra: tuple[str, ...] = ()):
    """The row's PERIOD identity for the T2a cross-section collapse: the chronological data-axis alias
    (data_date) or the raw silver column names test fixtures/guard-cols carry, else (year, month) for
    year_month tables, else the row's own index -- a keyless single-grain table keeps the legacy
    one-row-one-period behavior exactly. ``extra`` (W1.4) prepends TABLE-SCOPED aliases from
    _PACE_PERIOD_KEY_EXTRA -- never widen the shared list for one table's schema."""
    for k in (*extra, "data_date", "week_ending_date", "date", "report_date"):
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
    futures_roll.front_month (ROLL_RULE_VERSION front_month_v2) -- selection first, delta across dates
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
        legacy_lane_front convention) wearing front_month_v2's name. BOTH-SIDED on purpose: an
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
        k = _pace_period_key(rr, i, _PACE_PERIOD_KEY_EXTRA.get(table, ()))
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


def _tail_legs(records: list, kept: list, base: int, calls: list) -> tuple:
    """W1.1: render the basin TAIL lines off the leg=('tail',*) sibling records -- one [N] line per
    basin weather-z node quoting the RAW share (0-1, the row's own value; the engine never multiplies).
    A silent/error/empty tail record renders NOTHING (non-basin countries have no tail metric by
    construction -- honest absence, the pace-leg discipline). Appends [N] calls IN PLACE (synthetic
    rows are cap-free). Returns (lines, trace); trace non-empty IFF at least one tail line rendered."""
    rows_by_key = {g["specs"][0]["node_key"]: g["row"] for g in kept if g.get("specs")}
    lines, trace = [], []
    n = base
    for r in records:
        leg = r.get("leg") or ()
        if not leg or leg[0] != "tail" or r.get("status") != "ok" or not (r.get("rows") or []):
            continue
        row = rows_by_key.get(r.get("node_key"))
        if row is None:
            continue
        share = _float_val(r)
        if share is None:
            continue
        tail_metric = f"{row.get('metric')}{_TAIL_SUFFIX}"
        # the call rides the record itself (a REAL fetched row) under a %-unit synthetic row: the
        # su_ratio ratio-normalizer precedent (stored 0.36 -> served 36 '%'), so the line quotes an
        # ANALYST figure ("18.2 %") that still value-checks against the pre-scaled headline row.
        # Figures AND plain language together, per the owner's word -- never one without the other.
        srow = {**row, "metric": tail_metric, "narrate_unit": "%", "scale": 100}
        n += 1
        calls.append(_shown(_prescaled(r, srow, n), _scaled_val(r, srow)))
        pct = _scaled_val(r, srow)
        q = r.get("query") or {}
        lines.append(f"- [N{n}] share of the basin's cells at or beyond +2 sigma in "
                     f"{_metric_display(row)} (as-of {q.get('asof')}): {pct:g} %" + _series_tag(q, srow))
        trace.append({"node": r.get("node_key"), "metric": tail_metric,
                      "share": round(share, 4)})
    return lines, trace


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
            calls.append(_shown(_pace_synth(r, row, d, n, kind="pace_change", unit=unit), d))
            lines.append(f"- [N{n}] change in {_metric_display(row)} from the prior {grain} "
                         f"({gnoun} pace): {d:+g} {unit}".rstrip() + _series_tag(r.get("query"), row))
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
                # the streak line renders the run as a DIGIT ("in each of the last 3 weeks") -> a magnitude
                calls.append(_shown(_pace_synth(r, row, run, n, kind="pace_streak", unit=f"{grain}s"), run))
                word = "rose" if direction == "up" else "fell"
                lines.append(f"- [N{n}] {_metric_display(row)} {word} in each of the last {run} {grain}s"
                             + _series_tag(r.get("query"), row))
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
    narration ('rose ~18% [N4]') value-checks against a real row (P9/D-B2).

    ``change_rule: absolute`` (GN-2 W1.3, 2026-08-22) suppresses the pct row ENTIRELY for refs whose
    metric is a SPREAD that crosses zero: percent-of-a-near-zero-base asserts absurd magnitudes (the
    measured board-crush consecutive-session trap is +10,086%), and a sign flip makes the ratio's sign
    meaningless too. The absolute delta row -- which already ships beside every pct row -- is the honest
    change for such metrics, in the metric's own unit. One gate here covers BOTH emission sites
    (_assemble and the chain hop renderer); validated fail-closed by config_check.check_cascade_map."""
    if str(row.get("change_rule") or "") == "absolute":
        return None
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


def _fmt_era_diff(row: dict, d: float, n: int, *, period: str, q: dict | None = None) -> str:
    return (f"- [N{n}] cross-era change in {_metric_display(row)} ({period}): "
            f"{d:+g} {row.get('narrate_unit') or ''}".rstrip() + _series_tag(q, row))


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
        elif leg[0] == "tail":
            grp["tail"] = r          # W1.1: consumed by _tail_legs only -- same quarantine as pace (a
            #                          share in an era bucket would poison _era_delta with a 0-1 value)
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


def _table_label(table) -> str:
    """display.table_label, fail-soft (A1). Imported lazily and belted so a display-registry problem can
    never take the cascade down -- an unresolvable label degrades to the de-underscored id, never to a
    raise and never to the raw `silver_*` token."""
    if not table:
        return ""
    try:
        from leviathan.graphrag import display as dp
        return dp.table_label(str(table)) or ""
    except Exception:  # noqa: BLE001 -- a label lookup must degrade, never break the panel
        return str(table).replace("silver_", "").replace("gold_", "").replace("_", " ").upper()


def _contract_seg(contract_month) -> str:
    """The delivery-month segment of the series tag, in the NON-year-month render form ('2024M03').

    Fail-soft to "" -- an unresolvable month drops its own segment and every other segment is unchanged,
    which is the same degradation `_table_label` takes. One call site for the format (`outcomes.
    contract_token`), so the tag and any other renderer of a delivery month cannot disagree."""
    if contract_month in (None, ""):
        return ""
    try:
        from leviathan.graphrag.numbers import outcomes as OC
        return OC.contract_token(str(contract_month)) or ""
    except Exception:  # noqa: BLE001 -- a tag segment must degrade, never break the panel
        return ""


def _series_tag(q: dict | None, row: dict | None = None) -> str:
    """The SCOPE suffix every reader-facing [N] row line ends with:
    ' [series: <commodity>; country: <country>; contract: <DELIVERY MONTH>; table: <SOURCE LABEL>]'.

    OUTCOMES_JOIN D-OJ-5: the CONTRACT segment is the fourth, and it is reader-facing rather than debug.
    The outcomes join measures a move on ONE surviving delivery month, and that contract is the FRONT
    month in only 25.5-31.7% of anchors (per-anchor divergence from the front chain: median 1.2-2.5pp,
    p90 4.6-7.2pp -- the same order as the move being claimed), so a survivor-basis move rendered without
    its delivery month is a scope mis-attribution of exactly the class this tag exists to stop. It sits
    in the TAG rather than in the line body because answer.py's SCOPE paragraph trains the reader that
    the tag names what the figure was measured on -- and that paragraph is amended in the same edit.

    IT IS SOURCED FROM A KEY NO OTHER TABLE CARRIES, so every existing line is byte-identical: the
    comprehension below drops any segment whose value is None/"", and only a contract-scoped query dict
    ever sets `contract_month`. The token is rendered through `outcomes.contract_token` -- '2024-03'
    becomes '2024M03' -- because `eval._YM_RX` matches a bare year-month and `eval._line_targets` is
    two-tier with NO fallback by design: an episode bullet that leaked 'contract: 2024-03' would be
    scored as enumerating a window the engine never injected, redding `episode_magnitude_or_absence`
    and `min_episode_lines` together. The M form cannot match that regex at all, so the class is removed
    rather than bounded.

    W4 A/B (2026-07-31): the rendered line named the metric, the period and the as-of but never the SERIES the
    figure was measured on, so rows keyed to a contract slug (soft_red_winter_wheat_cbot) came back narrated as
    "Russia", "Ukraine" and "US total" -- four scope mis-attributions the citation verifier cannot catch,
    because every FIGURE was transcribed correctly. Country comes off the query _scope() already resolved.
    An absent field drops its own segment (never the literal "None"); all absent -> no tag.

    A1's ONE non-optional constraint (SKEPTIC F21): the source is emitted as `dp.table_label` ('USDA PSD',
    'COT', 'NOAA IOD'), NEVER the raw `silver_*` id. _fmt_line feeds _prompt_parts, i.e. the MODEL's
    copy-surface, and executed against HEAD `reg.internal_leaks` does not match `silver_psd` while the
    sibling markers `silver_ref`/`silver_status` ARE fenced -- so a bare table id is an internal identifier
    on a transcribable surface with no detector behind it. The reader-facing ledger
    (citations.from_number) has always rendered the source label; this closes the gap between what the
    MODEL sees and what the LEDGER already knew."""
    q = q or {}
    parts = [f"{lbl}: {v}" for lbl, v in (("series", q.get("commodity")),
                                          ("country", q.get("country")),
                                          ("contract", _contract_seg(q.get("contract_month"))),
                                          ("table", _table_label((row or {}).get("table") or q.get("table"))))
             if v not in (None, "")]
    return f" [{'; '.join(parts)}]" if parts else ""


def _fmt_line(rec: dict, row: dict, n: int, *, era) -> str:
    sv = _scaled_val(rec, row)                            # the SAME float the append site binds as `shown`
    val = f"{sv:g}" if sv is not None else "?"
    unit = row.get("narrate_unit") or ""
    q = rec.get("query") or {}
    tag = _era_label(era, row)
    # W1.1: the calm word -- a weather-z read carries its magnitude in ANALYST vocabulary ("near
    # normal" beats a bare 0.03 to a reader; calm weather is information, never silence). Words only,
    # no figures, so the verifier's number discipline is untouched.
    word = ""
    if row.get("table") == _WEATHER_Z_TABLE and row.get("metric") in _BASIN_TAIL_METRICS \
            and sv is not None:
        word = f" ({_z_word(sv)})"
    return (f"- [N{n}] {q.get('commodity')} {_metric_display(row)} {q.get('period') or ''} ({tag}, "
            f"as-of {q.get('asof')}): {val} {unit}".rstrip() + word + _series_tag(q, row))


def _fmt_delta(row: dict, d: float, n: int, *, era, q: dict | None = None) -> str:
    return (f"- [N{n}] change within the {_era_label(era, row)} in {_metric_display(row)}: "
            f"{d:+g} {row.get('narrate_unit') or ''}".rstrip() + _series_tag(q, row))


def _fmt_pct(row: dict, pct: float, n: int, *, era, q: dict | None = None) -> str:
    return (f"- [N{n}] change within the {_era_label(era, row)} in {_metric_display(row)}: {pct:+g} %"
            + _series_tag(q, row))


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
                calls.append(_shown(_prescaled(r, row, n), _scaled_val(r, row)))
                lines.append(_fmt_line(r, row, n, era=i))
            for r in recs:
                if r.get("status") and r["status"] != "ok":
                    lines.append(_fmt_absence(r))
            d = _era_delta(oks, row)
            if d is not None:
                era_deltas[i] = d
                n += 1
                calls.append(_shown(_delta_call(oks[-1], row, d, n, kind="delta"), d))
                lines.append(_fmt_delta(row, d, n, era=i, q=oks[-1].get("query")))
                pct = _pct_change(oks, row)
                if pct is not None:
                    n += 1
                    calls.append(_shown(_delta_call(oks[-1], row, pct, n, kind="pct"), pct))
                    lines.append(_fmt_pct(row, pct, n, era=i, q=oks[-1].get("query")))
        if cur and cur.get("status") == "ok" and (cur.get("rows") or []):
            n += 1
            calls.append(_shown(_prescaled(cur, row, n), _scaled_val(cur, row)))
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
                calls.append(_shown(_delta_call(later_rec, row, diff, n, kind="era_diff",
                                                period=period_lbl), diff))
                lines.append(_fmt_era_diff(row, diff, n, period=period_lbl, q=later_rec.get("query")))
            lines.append(f"DIVERGENCE on {_metric_display(row)}: {a:+g} vs {b:+g} "
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

# ── THE PSD ATTRIBUTE AXIS (projection wave Lane 3, L2-5, 2026-08-25) ───────────────────────────────
# The two surfaces are named at PSD_TABLES (top of file). Which spelling a component takes is a property of
# the TABLE, not of the caller, so the engine reads the registry's declared `shape` rather than carrying a
# second literal anywhere below.
#
# Wide COLUMN -> the USDA attribute label the long companion stores, byte-exact from the L2-0 census
# (data/dec_p0/psd_attribute_census.json, bulk object release_date=2026-08-13). The spellings are pinned as
# a literal set in tests/unit/test_psd_attribute_axis.py, not read from the artifact at import time.
_PSD_ATTR_OF_COLUMN: dict[str, str] = {
    "beginning_stocks_mt":   "Beginning Stocks",
    "ending_stocks_mt":      "Ending Stocks",
    "production_mt":         "Production",
    "exports_mt":            "Exports",
    "imports_mt":            "Imports",
    "area_harvested_1000ha": "Area Harvested",
    "yield_mt_ha":           "Yield",
    "consumption_mt":        "Domestic Consumption",   # SLUG-DEPENDENT -- see _PSD_CONSUMPTION_ATTR_BY_SLUG
}

# THE CONSUMPTION COMPONENT IS THE ONE THAT IS NOT A RENAME. The wide producer NORMALISES three source
# labels onto 'Domestic Consumption' for its pivot (census meta.producer_remap_sources, 2026-08-13); the
# long companion emits USDA's OWN label, because a table where one label spans four attribute_ids cannot be
# joined to the source's key. A single-label map would therefore compile `attribute = 'Domestic
# Consumption'` for sugar, cotton and fresh citrus and return a SILENT ZERO ROW -- the silver_wasde
# Title-Case class of bug, landing on the denominator of the World stocks-to-use ratio.
_PSD_CONSUMPTION_ATTR_BY_SLUG: dict[str, str] = {
    "raw_sugar":    "Total Disappearance",
    "white_sugar":  "Total Disappearance",
    "cotton":       "Domestic Use",
    "fresh_citrus": "Fresh Dom. Consumption",
}


def _psd_attr_label(component: str, slug: str) -> str:
    """The long companion's own spelling of a balance-sheet `component` for `slug`: USDA's native attribute
    label for a wide silver_psd COLUMN, or the component unchanged when it already IS such a label (so a
    leg may name 'Crush' or 'TY Exports' directly -- attributes the wide card has no column for). NEVER a
    guess: `_psd_component_rows` refuses any label the tall card does not declare.

    THE SLUG-AWARE REMAP FIRES ON BOTH SPELLINGS (Lane-3 review): the docstring above invites callers to
    name attributes directly, so 'Domestic Consumption' arriving AS the native label must remap for
    sugar/cotton/citrus exactly as the wide column name does -- code 612000 never publishes 'Domestic
    Consumption', so the un-remapped label is a None for raw_sugar dressed as a decline."""
    if component == _XC_SU_USE:
        return _PSD_CONSUMPTION_ATTR_BY_SLUG.get(slug, _PSD_ATTR_OF_COLUMN[_XC_SU_USE])
    label = _PSD_ATTR_OF_COLUMN.get(component, component)
    if label == _PSD_ATTR_OF_COLUMN[_XC_SU_USE]:
        return _PSD_CONSUMPTION_ATTR_BY_SLUG.get(slug, label)
    return label


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


def _psd_component_rows(qfn, slug: str, metric: str, my: int, asof, *, table: str = _PSD_TABLE) -> list:
    """PIT-safe per-country rows for a PSD component at (slug, MY), as-known at asof: country=None
    -> every country's latest vintage <= asof, via the SAME keyed fetch_window path a cascade leg uses (same
    as-of guard, same sargable-partition discipline). Never raises (fetch_window degrades to rows=[]).

    SHAPE-KEYED, not table-keyed (L2-5): `metric` is spelled the way the REGISTRY says `table` spells it --
    a wide COLUMN on silver_psd, a VALUE of the metric column on the long companion. The tall branch adds
    the one fence the wide branch never needed: a metric the tall card does not DECLARE is refused HERE,
    before any SQL, because build_sql would happily compile `attribute = 'ending_stocks_mt'` and hand back
    a silent zero row -- indistinguishable from "not published" and the exact shape of the silver_wasde
    Title-Case bug, which returned zero rows for every WASDE lookup for months. A table with no card at all
    (the companion before its own change lands) has shape None and takes neither branch: fetch_window
    compiles against an unregistered table, returns status='error' with rows=[], and the leg declines.

    S1 canary: UNFLAGGED BY DESIGN (see quantify's docstring). Both tables this function can reach declare
    no `contract_month_col`, so `_newest_first_applies` is False for every spec it can build -- passing the
    FUTURES canary down the five-deep PSD chain could not change one byte of SQL. Pinned in
    test_futures_readpath_pins, so the omission is measured rather than assumed.

    D-AM-18: under the ESTATE-WIDE token that structural argument no longer holds (the scope stops keying
    on `contract_month_col`), so this stays unthreaded as a DECISION. The read is scoped to one marketing
    year (`period=my`, `period_type='marketing_year'`), which is what bounds it: a single MY across every
    country is orders of magnitude under the 5000 cap, so which end the cap keeps is unobservable here."""
    if _table_shape(table) == "tall":
        ts = _table_spec(table)
        if metric not in (getattr(ts, "metrics", None) or {}):
            return []                                   # undeclared attribute -> decline, never a 0-row SQL
    rec = fetch_window(qfn, table=table, metric=metric, commodity=slug, country=None,
                       t1=None, t2=None, asof=asof, agg="series", period=my, period_type="marketing_year")
    return rec.get("rows") or []


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


def _world_sum(rows: list, my: int) -> tuple | None:
    """THE World synthesis, once: (total, n_summed, max_release, unit) over the per-country-latest union for
    one component at one marketing year, with the EU membership-window dedup applied. Hoisted out of
    `_world_su_ratio` (L2-5) so the wide ratio and any attribute-axis total share ONE arithmetic and cannot
    drift apart on dedup, on latest-wins, or on the freshness stamp.

    NATIVE-UNIT GUARD, the tall table's own hazard: the long companion carries the value in USDA's unit with
    a `unit` column beside it, so one (slug, attribute, MY) set can legitimately span '(1000 MT)' and
    '(MT)'. Adding those is a MANUFACTURED number, so a set carrying more than one distinct unit is REFUSED
    (None) rather than summed. Inert on silver_psd, whose card declares no unit column: its rows carry no
    `unit` extra at all, the unit set is empty, and the returned unit is None -- byte-identical to the
    nested `_sum_latest` this replaces.

    Returns None when the set cannot be summed honestly; (0.0, 0, None, unit) is a legitimate empty sum and
    stays the caller's decision to decline."""
    latest = _latest_per_country(rows)
    # aggregate_present demands a NUMERIC aggregate value, not mere row presence: a NULL-valued EU row
    # carries NO member tonnage, so deduping against it would DROP the member from the sum outright
    # (skeptic probe T3, 2026-07-20) -- and split the engine from the census existence probe, whose
    # SQL sum(value) ignores NULLs and keeps the member.
    agg_present = any(str(c) in EU_AGGREGATE_TITLES and _as_float(r.get("value")) is not None
                      for c, (r, _rd) in latest.items())
    tot, n, mx, units = 0.0, 0, None, set()
    for c, (r, rd) in latest.items():
        if eu_member_deduped(c, my, aggregate_present=agg_present):
            continue                                        # inside the EU aggregate this MY: already counted
        v = _as_float(r.get("value"))
        if v is None:
            continue
        u = str(r.get("unit") or "").strip()
        if u:
            units.add(u)
        tot, n = tot + v, n + 1
        if mx is None or rd > mx:
            mx = rd
    if len(units) > 1:
        return None                                         # mixed native units: never added, always refused
    return tot, n, mx, (next(iter(units)) if units else None)


def _world_attribute_total(qfn, slug: str, attribute: str, my: int, asof,
                           *, table: str = _PSD_ATTR_TABLE) -> tuple | None:
    """The World synthesis on the ATTRIBUTE axis: the per-country-latest SUM of one NATIVE PSD attribute
    ('Crush', 'Feed Dom. Consumption', 'TY Exports', ...) at (slug, MY) as known at asof, in that
    attribute's own unit. Same arithmetic as the su_ratio components by construction (`_world_sum`), same
    EU dedup, same freshness stamp -- and the same honest declines: an undeclared attribute, an
    unregistered card, an empty set or a mixed-unit set all return None rather than a number.

    Returns (total, unit, release_date, n_countries). The unit RIDES the total because this table converts
    nothing: a total with its unit dropped is the (1000 HEAD)/(1000 MT) collision waiting to happen."""
    rows = _psd_component_rows(qfn, slug, _psd_attr_label(attribute, slug), my, asof, table=table)
    got = _world_sum(rows, my) if rows else None
    if got is None:
        return None
    tot, n, rd, unit = got
    return (tot, unit, rd, n) if n else None


def _world_su_ratio(qfn, slug: str, my: int, asof, *, table: str = _PSD_TABLE) -> tuple | None:
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

    SURFACE-AWARE (L2-5): the two components are named as the WIDE card's columns and re-spelled by
    `_psd_attr_label` when the surface being read is TALL, so the same ratio is computable on either PSD
    table without a second copy of this arithmetic. The consumption component is the one that is not a
    rename -- sugar, cotton and fresh citrus keep USDA's own label on the long companion -- which is why
    the re-spelling is slug-aware rather than a single-string swap. The ratio itself is UNIT-FREE (a
    quotient of two sums in one unit), so the tall path additionally demands that the numerator and
    denominator carry the SAME native unit; different units mean the quotient is not a stocks-to-use ratio
    at all, and the leg declines rather than printing one.

    Returns (ratio_pct, release_date, n_countries) or None (missing component / empty sum / zero use /
    mixed or mismatched native units -> the leg declines honestly). release_date is the MAX release across
    the summed rows -- an as-of FRESHNESS STAMP for the citation, NOT a claim that every summed row came
    from that vintage."""
    tall = _table_shape(table) == "tall"
    stocks = _psd_attr_label(_XC_SU_STOCKS, slug) if tall else _XC_SU_STOCKS
    use = _psd_attr_label(_XC_SU_USE, slug) if tall else _XC_SU_USE
    st = _psd_component_rows(qfn, slug, stocks, my, asof, table=table)
    us = _psd_component_rows(qfn, slug, use, my, asof, table=table)
    if not st or not us:
        return None
    s, u = _world_sum(st, my), _world_sum(us, my)
    if s is None or u is None:
        return None
    s_tot, s_n, s_rd, s_unit = s
    u_tot, u_n, u_rd, u_unit = u
    if s_n == 0 or u_n == 0 or u_tot == 0 or s_unit != u_unit:
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
    # RV roster phase 3 (2026-08-29): canola_ice's PSD sheet (2226000) is the world RAPESEED aggregate
    # (fanned with french_rapeseed_matif) -- the wheat rule's C20 class on the second aggregate. Without
    # this the label rendered 'world canola ice' (the _ice suffix was also missing from the strip list).
    if s == "canola_ice":
        return "world rapeseed (incl. canola)"
    for suf in ("_cbot", "_cme", "_zce", "_dce", "_matif", "_ice"):
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


def _xc_frame(pair_row, sg, *, open_ask: bool = False) -> str:
    """The narration frame directive, selected BY COMPLEX (RV-W2.4). soy_crush takes the joint-product path
    (a co-move is not a story; only DEMAND divergence opposes -- oil_share stays qualitative prose, there is no
    crush_margin_z serving metric); feed_grain narrates generically unless its shared_event route-matched this
    turn (C20); substitution complexes narrate the second-balance-sheet substitution.

    D-XT F2 (2026-08-29): on an OPEN ask the soy_crush DEMAND claim is dropped UNCONDITIONALLY -- the user
    asked 'what else is affected', not 'did demand shift the crush', and asserting a demand shift onto an
    acreage/supply question is the sign-identity class. NOT gated on _shared_event_matched: MEASURED INERT
    (on the banked cc1_r1 admissions that matcher returns True for board_crush 14/14 and
    soybean_crush_margin 14/14 -- a 14/14 matcher is not a gate)."""
    complex_name = str(getattr(pair_row, "complex_name", "") or "")
    # RV roster phase 3 (2026-08-29): the crush branch is a SET -- rape_crush (the three ratified rape
    # rows) takes the same joint-product frame; a literal-name match would have dropped it through to
    # the substitution frame AND lost the D-XT F2 open-ask guard on exactly the class it exists for.
    if complex_name in ("soy_crush", "rape_crush"):
        if open_ask:
            return ("the shock reached the second leg of the crush; meal and oil are JOINT products "
                    "co-produced on the supply side, and the record here does not say which side moved")
        return ("the crush shifted toward one product on DEMAND (meal and oil are JOINT products co-produced on "
                "the supply side, so a co-move is not a relative-value story; only a demand divergence opposes)")
    if complex_name == "feed_grain":
        if _shared_event_matched(sg, getattr(pair_row, "shared_event", None)):
            return "the relative feed-grain balance shifted (feed-ration substitution)"
        return "the relative feed-grain balance shifted"        # generic: no runtime signal for WHICH edge (C20)
    # RV-REGIONAL (2026-08-29): a SET, the rape_crush lesson verbatim -- a literal-name match would
    # drop a new origins complex through to the substitution frame AND lose the open-ask guard.
    if complex_name in ("milling_wheat_origins",):
        if open_ask:
            return ("the shock reached a second ORIGIN's balance sheet; the record here does not say "
                    "which origin won the business")
        return ("export business moved between two ORIGINS of the same grain: one region's balance "
                "sheet tightened as the other's loosened (origin-share reallocation, not a "
                "substitution)")
    return "the shock reached a second balance sheet; one tightened as the other loosened (substitution)"


_XC_METRIC_WORLD = "su_ratio_world"          # the HEAD literal, named once (RV-REGIONAL B4)


def _xc_call(commodity: str, value: float, my: int, asof, *, unit: str = "%",
             metric: str = _XC_METRIC_WORLD, country: str | None = None) -> dict:
    """A synthetic call-record so a narrated v2 su_ratio/delta magnitude IS a citable, value-checkable row (the
    _delta_call discipline; both legs' rows are injected so the all-numbers strip guard backs every magnitude).
    No _provenance -- a World figure is a cross-country synthesis, not one source row.

    RV-REGIONAL (2026-08-29): two ADDITIVE keyword-only params. `country` is added to the query dict
    ONLY when not None, so the World path's dict is BYTE-IDENTICAL (no new key, same metric id); a
    regional row carries its pinned scope so citations and the series tag tell the truth (refute-v1
    D3: _series_tag reads q['country'] verbatim)."""
    q = {"commodity": commodity, "metric": metric,
         "period": (f"MY{my}" if my is not None else None), "asof": asof}
    if country is not None:
        q["country"] = country
    return {"query": q, "rows": [{"value": round(float(value), 4), "unit": unit}], "status": "ok"}


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
        # ONE line carries all three magnitudes, so the [N{handle}] endpoint call is `shown` all three; the
        # baseline/delta calls are single-row synthetics (no line of their own) and need no binding.
        calls.append(_shown(_xc_call(cmdty, p_hi, my_hi, asof),   # the endpoint the [N{handle}] line cites
                            p_hi, p_lo, d))
        n += 1
        calls.append(_xc_call(cmdty, p_lo, my_lo, asof))        # the baseline (backs the '(vs MY.. ..%)' term)
        n += 1
        calls.append(_xc_call(cmdty, d, my_hi, asof, unit="pp"))    # the delta (backs the '..pp' term)
        # World is SYNTHESIZED from per-country silver_psd rows (_world_su_ratio), so the scope tag states the
        # basis explicitly -- a World ratio narrated as one country is the exact mis-attribution class.
        lines.append(f"- [N{handle}] {lbl} stocks-to-use MY{my_hi}: {p_hi:g}% "
                     f"(vs MY{my_lo} {p_lo:g}%, {d:+g}pp over the window)"
                     + _series_tag({"commodity": cmdty, "country": "World", "table": "silver_psd"}))
    return lines, ((mya0, pa0, mya1, pa1), (myb0, pb0, myb1, pb1))


def _xc_fork_scan(da_by: dict, db_by: dict) -> tuple:
    """(divergence_era_idx, comove_era_idx) over the INDEX-ALIGNED eras. The two-pass sign rule and its
    absolute first-fire priority, extracted from _reroute_xc's loop VERBATIM (RV-REGIONAL, 2026-08-29):
    opposite-sign wins and returns immediately; a flat leg (sign 0) is neither; the FIRST same-sign era
    is recorded and only reported after the scan proves no era diverged. PURE -- no strings, no calls
    list, no rendering. Shared by the World and the regional forks so the SIGN/PRIORITY rule (the
    cardinal class) cannot fork. The RENDERING is deliberately duplicated per fork, with this note:
    two string producers that drift produce two wrong labels, which the C20/scope pins catch; two SIGN
    producers that drift produce a correct-looking inverted verdict, which nothing catches."""
    comove_idx = None
    for i in sorted(set(da_by) & set(db_by)):                   # index-aligned eras: same era_idx on both legs
        sa, sb = _sign(da_by[i]["d"]), _sign(db_by[i]["d"])
        if sa == 0 or sb == 0:
            continue                                            # a flat/no-delta leg -> never a co-move (honest)
        if sa == sb:                                            # a TRUE same-sign co-move (both real moves)
            if comove_idx is None:
                comove_idx = i                                  # record the FIRST; render only if no era diverges
            continue
        return i, comove_idx                                    # first divergence: absolute first-fire priority
    return None, comove_idx


def _reroute_xc(pair_row, source: str, target: str, focus_windows: list, qfn, asof,
                calls: list, base: int, sg, comove: bool = False, *, open_ask: bool = False) -> tuple:
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
    div_idx, comove_idx = _xc_fork_scan(da_by, db_by)           # RV-REGIONAL: the ONE sign/priority scan
    if div_idx is not None:
        A, B = da_by[div_idx], db_by[div_idx]
        # OPPOSITE-SIGN divergence -- the RV fork. First-fire priority: render + return here (byte-identical).
        lines, ((mya0, pa0, mya1, pa1), (myb0, pb0, myb1, pb1)) = _xc_leg_lines(
            la, source, A, lb, target, B, calls, base, asof)
        window = f"MY{mya0}-MY{mya1}"
        lines.append(
            f"CROSS-COMMODITY on su_ratio: {la} {pa1:g}% ({A['d']:+g}pp) vs {lb} {pb1:g}% ({B['d']:+g}pp) "
            f"over {window} -- {_xc_frame(pair_row, sg, open_ask=open_ask)}; "
            f"each World balance sheet aggregates DIFFERING local "
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
            *, comove: bool = False, reading: bool = False, replay: bool = False,
            rv_regional: bool = False, derived_arith: bool = False,
            extrema_own_date: bool = False) -> tuple:
    """Resolve the curated pair + the focus window, then run the ratio-delta fork. Returns (block_lines,
    fired_trace) -- ([], None) on ANY decline/failure so v2 NEVER breaks the v1 answer (fail-closed). `comove`
    ([SKEPTIC F3], threaded from the answer.py seam, never an env read) rides into _reroute_xc: when True a
    pure same-sign complex-wide move may render (its OWN CO-MOVE marker); opposite-sign output is unaffected.

    RV-READING (2026-08-29): `reading` (answer.py-threaded from GRAPHRAG_RV_READING, same [F3] idiom)
    renders the directional price leg AFTER a pair fires -- it never chooses a pair (the D-XT seam owns
    pair choice) and never rides the transmission composer's per-link calls (one reading per turn, two
    fetches). `replay` is quantify's own price_replay belt threaded down unchanged: a historical-asof
    turn drops the leg whole (the pink sheet is latest-only with retroactive revisions -- C-2). Both
    default False -> flag-off is byte-identical. Declines stamp fired['price_reading_decline'] (the
    xc_open_decline shape: a counted decline beats a silent one -- eval's rv_reading counters read it);
    a leg-local register-fence trip additionally stamps sg.trace['quantify_rv_reading_fenced']."""
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
        # D-XT N12: open_ask via the omit-when-off idiom -- passing the kwarg unconditionally would raise
        # TypeError through that same stub and an open-ask turn would decline INVISIBLY. Load-bearing, not
        # cosmetic (pinned through the stub itself).
        _oa = {"open_ask": True} if (xc_request or {}).get("trigger") in _OPEN_TRIGGERS else {}
        # RV-REGIONAL dispatch (fail-closed, contract-keyed). A regional pair with the flag OFF falls
        # to _reroute_xc, whose _xc_sides_ok requires country_rule == 'world' on both sides -> ([],
        # None) -- combined with the contextual tier, flag-off is inert twice over by construction.
        _regional = False
        if rv_regional:
            try:
                from leviathan.graphrag import complex_map as _xcm
                _regional = (_xcm.pair_is_regional(pair_row)
                             and _xc_sides_ok_regional(pair_row, source, target))
            except Exception:  # noqa: BLE001
                _regional = False
        if _regional:
            block, fired, _rdec = _reroute_xc_regional(pair_row, source, target, windows, qfn, asof,
                                                       calls, len(calls), sg, comove, **_oa)
            if _rdec and not fired:
                # E3: the decline channel -- a non-firing regional fork has no fired dict to stamp,
                # so the tag rides its own trace key (the xc_open_decline shape, four-outcome census)
                try:
                    sg.trace["xc_regional_decline"] = {"reason": _rdec}
                except Exception:  # noqa: BLE001
                    pass
        else:
            block, fired = _reroute_xc(pair_row, source, target, windows, qfn, asof, calls,
                                       len(calls), sg, comove, **_oa)
        if fired:
            # RV2 W2 tier telemetry (D7, S2-2): the fired trace records the DETECTING tier HERE, after the
            # call -- _reroute_xc has no xc_request in scope. A 3-key request (legacy/injected) reads None;
            # the engine itself still consumes only pair_id/source/target, so the key rides inert.
            fired["detect_tier"] = (xc_request or {}).get("detect_tier")
            # D-XT M3: the trigger path rides beside it -- absent on every legacy/named request, so the
            # fired dict is byte-identical when the open lane never ran.
            if (xc_request or {}).get("trigger"):
                fired["trigger"] = xc_request.get("trigger")
            # RV-READING: renders AFTER the pair fired, gated ONLY by the threaded kwargs (fail-closed
            # inside). The fence trip is the one decline that also writes a top-level trace key -- the
            # register discipline's own visibility rule (belt (a) of _RV_READING_BANNED_RX).
            # D-DA LANE 1 (design v2, seam step): the balance-standing block renders BEFORE the price
            # reading (balance sheets first, then price standing -- the reading's own render order),
            # gated ONLY by the threaded kwarg and the roster; fail-closed inside su_standing.
            if derived_arith:
                try:
                    from leviathan.graphrag.numbers import derived as _dv
                    # DV_LANE_CAP = 1 IS ENFORCED HERE: exactly one derived producer per turn --
                    # the WASDE balance-standing when both slugs are rostered, ELSE the crush share
                    # on a soy-trio pair, else a counted roster decline. Never both (F5's pool law).
                    d_lines: list = []
                    d_calls: list = []
                    d_trace: dict | None = None
                    if source in _dv._DV_WASDE_LEGS and target in _dv._DV_WASDE_LEGS:
                        d_lines, d_calls, d_trace = _dv.su_standing(
                            fetch_window, qfn, source, target, asof, len(calls),
                            extrema_own_date=extrema_own_date)
                    elif {source, target} <= _dv._DV_CRUSH_TRIO:
                        d_lines, d_calls, d_trace = _dv.crush_share(
                            fetch_window, qfn, asof, len(calls))
                    else:
                        d_trace = {"decline": "su_no_roster"}
                    if d_lines:
                        calls.extend(d_calls)
                        block = block + d_lines
                        fired["derived_arith"] = d_trace
                    elif d_trace:
                        fired["derived_arith_decline"] = d_trace.get("decline") or "error"
                        if str(d_trace.get("decline") or "").endswith("copy_surface"):
                            try:
                                sg.trace["quantify_derived_fenced"] = True
                            except Exception:  # noqa: BLE001 -- traceless sg never breaks the answer
                                pass
                except Exception:  # noqa: BLE001 -- the lane must never break the fired fork
                    fired["derived_arith_decline"] = "error"
            if reading:
                if replay:
                    fired["price_reading_decline"] = "replay"
                else:
                    p_lines, p_trace = _rv_price_reading(pair_row, source, target, fired, qfn, asof,
                                                         calls, len(calls), windows,
                                                         regional=_regional, derived=derived_arith,
                                                         extrema_own_date=extrema_own_date)
                    if p_lines:
                        block = block + p_lines
                        fired["price_reading"] = p_trace
                    elif p_trace:
                        fired["price_reading_decline"] = p_trace.get("decline") or "error"
                        if p_trace.get("decline") == "fenced":
                            try:
                                sg.trace["quantify_rv_reading_fenced"] = True
                            except Exception:  # noqa: BLE001 -- a traceless sg must never break the answer
                                pass
            elif _regional:
                # F1.1 (refute-v1 D13): GRAPHRAG_RV_REGIONAL alone gives no price leg -- the verdict
                # is OMITTED with a counted reason, never narrated as UNRESOLVED (which would tell
                # the reader the data was inconclusive when the leg simply never ran).
                fired["rv_regional_price_leg"] = "reading_flag_off"
        return block, fired
    except Exception:  # noqa: BLE001
        return [], None


# ── D-XT: the deferred OPEN-ASK bind (owner directive 2, 2026-08-29) ─────────────────────────────────
XC_OPEN_PROBE_CAP = 4        # `pair_realizable` is a LIVE pg probe behind lru_cache(maxsize=64)
#                              (cascade_census -> _pair_verdict(pgnumbers.pg_query)). NOT pure and NOT
#                              free. MEASURED-INERT (N11): the largest candidate set any curated source
#                              has is 4 (soybean_oil_cbot), so the cap can never truncate today. It
#                              exists so a roster growth cannot silently uncap the probe count. NOTE the
#                              divergence from the shipped gate's first-True loop (P23): the resolver
#                              probes up to CAP candidates to rank them; the gate stopped at the first.
XC_OPEN_DECLINES = ("no_focus", "focus_not_paired", "no_realizable", "crush_not_traversed", "error")
_OPEN_TRIGGERS = ("open_walk_graph", "open_walk_idorder")


def _xc_walk_focus(sg, graph) -> str | None:
    """THE TURN'S FOCUS CONTRACT: the first walk seed that is a graph contract. NOT A NEW RULE -- it is
    the expression answer.py's F2 price leg already uses to bind focus_contract, reused deliberately
    (two focus rules that could disagree is the defect; a unit pin asserts the two agree). sg.seeds is
    planner._seed_contracts in ROUTE ORDER -- on a planner turn that is the DISPATCH PLANNER'S OWN
    centrality ordering under its NAMED ANCHORS rule, not a lexical hit count and not the alphabet.
    MULTI-SEED TURNS: the head wins and the rest are RECORDED, never ranked -- scanning down for a seed
    that happens to sit in a curated pair would let the PAIR ROSTER choose the source (the alphabet
    defect wearing the walk's clothes); what the other seeds are worth is measured for free instead
    (first_paired_seed in the decline/rank record). HONEST COST, measured: the head can be a GENERIC
    contract id ('corn'/'soybeans', distinct ids from corn_cbot/soybeans_cbot, in ZERO curated pairs)
    when the planner named the generic first; those turns decline focus_not_paired -- a ROSTER finding,
    reported as one (P7). Never raises."""
    try:
        return next((c for c in (getattr(sg, "seeds", None) or [])
                     if c in getattr(graph, "contracts", {})), None)
    except Exception:  # noqa: BLE001
        return None


def _xc_walk_index(sg, source: str) -> dict:
    """{contract_id -> {"relevance": float, "relations": set, "tracked": bool}} over the CONTRACT nodes
    THIS walk admitted. `relations` holds the relation of the edge the walk TRAVERSED OUT OF `source` to
    reach this contract (planner stamps via_edge = {**e, "_from": cid, ...}).
    N5 (round-3 refuter, ADOPTED AS THE EXCLUSION): a D-MW-28 CASCADE SLOT also stamps _from, relation
    AND tracked: True (planner.py:689-696) -- and that edge is traversed in REVERSE (the foreign
    contract declared the seed as ITS driver), so counting it would score `traversed` on the opposite
    direction from the one this key measures. EXCLUDED by reason == REASON_DOWNSTREAM_CONTRACT.
    Measured bite on the frozen deck: ZERO -- excluded for correctness, not for effect.
    M2: the relation set is a UNION and the per-pair match is explicit at the call site -- no
    max((rank, relevance, relation)) string compare (that picked the surviving relation LEXICALLY where
    a node carries two: mcpo->soybean_oil carries substitutes_for AND competes_with). `tracked` is
    RECORDED, never RANKED (every non-seed contract arrives through the cross_links wave, which already
    gates on e["tracked"] -- the test was decorative). Never raises."""
    from leviathan.graphrag.planner import REASON_DOWNSTREAM_CONTRACT
    out: dict = {}
    for n in (getattr(sg, "nodes", None) or []):
        if getattr(n, "kind", None) != "contract":
            continue
        cid = getattr(n, "id", None)
        if not cid:
            continue
        ve = getattr(n, "via_edge", None) or {}
        rel = (str(ve.get("relation") or "")
               if (ve.get("_from") == source and ve.get("reason") != REASON_DOWNSTREAM_CONTRACT) else "")
        e = out.setdefault(cid, {"relevance": 0.0, "relations": set(), "tracked": False})
        e["relevance"] = max(e["relevance"], float(getattr(n, "relevance", 0.0) or 0.0))
        e["tracked"] = e["tracked"] or (ve.get("tracked") is True)
        if rel:
            e["relations"].add(rel)
    return out


def _xc_open_rank(rank, ids: list, by_id: dict, source: str, sg) -> list:
    """[(pair_id, other_leg, stamp), ...] best first, over the REALIZABLE candidate ids (P11: written
    plainly -- `by_id` maps pair_id -> pair row, `other` is complex_map.pair_other).

    idorder: the shipped PAIR_CAP=1 rule applied to a source the GRAPH chose -- curated-id order. Never
    empty when ids is non-empty, so crush_not_traversed is unreachable on this path (M1 by construction).
    graph (SHIPS DARK): the walk ranks -- traversed = 1 iff the walk traversed THIS PAIR'S OWN relation
    out of source to the partner (explicit per-pair match, M2); a crushed_into candidate whose crush edge
    was not traversed is DROPPED (m4: a crush relation is an accounting identity, true without dated
    evidence); sort (-traversed, -relevance, pair_id). M1: crush_only is computed over the candidate set
    BEFORE the loop -- when the walk lights nothing and the set is not all-crush, fall back to idorder
    stamped fallback=id_order (a reorder failure is never a decline)."""
    from leviathan.graphrag import complex_map as cm
    idorder = []
    for pid in ids:
        other = cm.pair_other(by_id[pid], source)
        if other:
            idorder.append((pid, other, {"rank": "idorder"}))
    if rank != "graph":
        return idorder
    idx = _xc_walk_index(sg, source)
    crush_only = all(str(getattr(by_id[p], "relation", "") or "") == "crushed_into" for p, _, _ in idorder)
    rows = []
    for pid, other, _ in idorder:
        prel = str(getattr(by_id[pid], "relation", "") or "")
        traversed = 1 if (prel and prel in idx.get(other, {}).get("relations", ())) else 0
        if prel == "crushed_into" and not traversed:
            continue
        rel_score = float(idx.get(other, {}).get("relevance", 0.0) or 0.0)
        rows.append((pid, other, {"rank": "graph", "traversed": traversed,
                                  "relevance": round(rel_score, 6)}))
    rows.sort(key=lambda r: (-r[2]["traversed"], -r[2]["relevance"], r[0]))
    if rows and any(r[2]["traversed"] for r in rows):
        return rows
    if crush_only:
        return []
    return [(pid, other, dict(stamp, rank="graph", fallback="id_order"))
            for pid, other, stamp in idorder]


def resolve_xc_open(xc_request: dict, sg, graph) -> tuple:
    """THE DEFERRED OPEN-ASK BIND (owner directive 2, 2026-08-29). The orchestrator DETECTED the ask and
    withheld SOURCE; this binds SOURCE to the walk's own focus, takes that source's curated MATERIAL
    census-realizable pairs, and picks one. Returns (resolved_request | None, decline_dict | None) --
    never a bare None. A request without `defer` rides through IDENTICAL (the `is` object): that is how
    every NAMED ask, every legacy request and every flag-off turn bypasses this function untouched.
    IT CANNOT FIRE A TURN THE DETECTOR DID NOT LICENSE, and it cannot reach a market outside the curated
    roster: SOURCE comes from the walk, the PARTNER comes from complex_map, and every candidate must pass
    the per-pair census. Never raises (a resolver failure degrades to no fork, never a 500)."""
    try:
        if not isinstance(xc_request, dict) or xc_request.get("defer") != "walk":
            return (xc_request, None)
        req = dict(xc_request)
        source = _xc_walk_focus(sg, graph)
        _seeds = [c for c in (getattr(sg, "seeds", None) or []) if c in getattr(graph, "contracts", {})]
        if not source:
            return (None, {"reason": "no_focus", "n_seeds": len(_seeds)})
        from leviathan.graphrag import complex_map as cm
        try:
            pairs = list(getattr(cm.load_complex_map(), "pairs", []) or [])
        except Exception:  # noqa: BLE001 -- a map-load failure is a decline, never a raise
            pairs = []
        cands = sorted((p for p in pairs if source in cm.pair_slugs(p)), key=lambda p: p.id)
        _alt = next((c for c in _seeds if any(c in cm.pair_slugs(p) for p in pairs)), None)
        _base = {"focus": source, "n_seeds": len(_seeds), "focus_paired": bool(cands),
                 "first_paired_seed": _alt, "n_pairs": len(cands)}
        if not cands:
            return (None, dict(_base, reason="focus_not_paired"))
        _t0, ids, probes = time.perf_counter(), [], 0
        by_id = {p.id: p for p in cands}
        for p in cands:
            if probes >= XC_OPEN_PROBE_CAP:
                break
            probes += 1
            if _xmit_pair_realizable(p.id) and cm.pair_other(p, source):
                ids.append(p.id)
        _base |= {"n_realizable": len(ids), "probes": probes,
                  "probe_ms": int((time.perf_counter() - _t0) * 1000),
                  "capped": probes >= XC_OPEN_PROBE_CAP < len(cands)}
        if not ids:
            return (None, dict(_base, reason="no_realizable"))
        rows = _xc_open_rank(req.get("rank"), ids, by_id, source, sg)
        if not rows:
            return (None, dict(_base, reason="crush_not_traversed"))
        pid, other, stamp = rows[0]
        out = {k: v for k, v in req.items() if k not in ("defer", "rank")}
        out["pair_id"], out["source_slug"], out["target_slug"] = pid, source, other
        out["trigger"] = "open_walk_graph" if req.get("rank") == "graph" else "open_walk_idorder"
        out["xc_open_rank"] = dict(_base, pair_id=pid, target=other, **stamp)
        return (out, None)
    except Exception:  # noqa: BLE001 -- degrade to no fork, never a 500, never a guess
        return (None, {"reason": "error"})


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


def _price_call(commodity: str, region: str, value: float, my_label: str, asof, *, unit: str,
                src_row: dict | None = None) -> dict:
    """A synthetic silver_wasde call-record so a narrated farm-price LEVEL IS a citable, value-checkable [N]
    row (the _xc_call discipline). [SKEPTIC F6]: `unit` is an EXPLICIT param sourced from the FETCHED row's
    _apply_unit_overrides value (rows[0]['unit']), NEVER narrate_unit -- confining the unit fallback to the two
    price-leg call sites so _fmt_line/_delta_call stay UNTOUCHED. `table` rides the query so the citation
    locator carries table=silver_wasde (the eval price_cited / unit_present filter keys on it).

    CYCLE-5 VINTAGE-2: `src_row` is the FETCHED WASDE row this level was read off (the same row `unit`
    comes from), and its `release_date` -> `knowledge_date` alias is copied onto the synthetic row. WASDE
    is a vintage table -- the un-suffixed agent read of it stamps `[known 2026-07-10]` -- so a farm-price
    pair rendering the SAME table with no vintage at all was the sharpest form of the measured defect: the
    reader could not tell whether the pair was as-known or as-revised. Omitted -> byte-identical."""
    return {"query": {"table": "silver_wasde", "metric": "avg_farm_price", "commodity": commodity,
                      "country": region, "period": f"MY{my_label}", "asof": asof},
            "rows": [{"value": round(float(value), 4), "unit": unit, **_row_vintage(src_row)}],
            "status": "ok"}


def _price_pair(price_request: dict, sg, graph, groups: list, qfn, asof, near, calls: list, base: int,
                *, futures_newest_first: bool | str = False) -> tuple:
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
        recs = [_run_one(qfn, s, futures_newest_first=futures_newest_first)   # 2 fetches at SESSION asof
                for s in specs]                                              # (settled actual)
        # Pair-atomic declines AFTER the two fetches return a PAYLOAD (walk charter A2 / v3 STEP
        # 2(4)): the spend happened and must be countable. `price_leg: False` is the discriminator
        # the seam routes on; the pre-fetch declines above stay bare `([], None)` -- no attempt,
        # zero-trace turns stay zero-trace.
        if any(r.get("status") != "ok" for r in recs):
            return [], {"price_leg": False, "net_reads": 2, "reason": "endpoint_not_ok"}
        p_a, p_b = _float_val(recs[0]), _float_val(recs[1])
        if p_a is None or p_b is None:
            return [], {"price_leg": False, "net_reads": 2, "reason": "endpoint_unreadable"}
        # the _apply_unit_overrides fetched unit (F6), read off the SAME row _float_val took the level from
        # (agg='latest' makes these single-row today; keeping value and unit on one row is what stops a
        # future multi-row WASDE fetch from printing one MY's number under another MY's unit)
        # CYCLE-5 VINTAGE-2: the SAME headline rows carry the release_date the citation must stamp, so
        # they are bound here rather than re-picked -- unit and vintage can then never come off two rows.
        r_a, r_b = _headline_row(recs[0]) or {}, _headline_row(recs[1]) or {}
        u_a = r_a.get("unit") or ""
        u_b = r_b.get("unit") or ""
        lab_a, lab_b = _my_slash(my_a), _my_slash(my_b)
        reg_a, reg_b = _farm_region(commodity, my_a), _farm_region(commodity, my_b)
        n = base
        n += 1
        h_a = n
        c_a = _shown(_price_call(commodity, reg_a, p_a, lab_a, asof, unit=u_a,    # [N{h_a}] baseline-MY level
                                 src_row=r_a),
                     p_a)                                  # the line prints _fmt_price(p_a) at 2 dp; the
        calls.append(c_a)                                  # verifier's 1pct tolerance covers the rounding
        n += 1
        h_b = n
        c_b = _shown(_price_call(commodity, reg_b, p_b, lab_b, asof, unit=u_b,    # [N{h_b}] event-MY level
                                 src_row=r_b),
                     p_b)
        calls.append(c_b)
        # A3: the discipline rides the READER-FACING handle, not only the model directive below. The
        # PRICE-RESPONSE tail already said "survey-based ... NOT a futures settle" -- but that is an
        # instruction to the synthesizer, text the reader never sees, and 7 measured row-runs (notably
        # ol_ctrl_mechanism_backward, pb_wheat_blacksea_shock) read the pair as an UNDISCLOSED substitute
        # for the CBOT level the question asked about. Every line that prints the level now says what the
        # level IS. SUPPRESSION stays DEFERRED: hiding the pair on a front-month ask returns those rows to
        # silence, and it waits on a working futures anchor (P1).
        label = (f"US {commodity} USDA season-average farm price"
                 + (" (all classes)" if commodity == "wheat" else "")
                 + ", marketing-year (survey actual; not a futures settle)")
        verb = "rose from" if p_b >= p_a else "fell from"         # direction is prose; the level is the [N] row
        lines = [
            f"- [N{h_a}] {label} MY{lab_a}: {_fmt_price(p_a, u_a)}" + _series_tag(c_a["query"]),
            f"- [N{h_b}] {label} MY{lab_b}: {_fmt_price(p_b, u_b)}" + _series_tag(c_b["query"]),
            (f"PRICE-RESPONSE on avg_farm_price: {label} {verb} {_fmt_price(p_a, u_a)} [N{h_a}] (MY{lab_a}) "
             f"to {_fmt_price(p_b, u_b)} [N{h_b}] (MY{lab_b}) -- the settled USDA season-average farm price "
             f"(survey-based, revision_stamp actual at the session as-of; NOT a futures settle, NOT a forecast); "
             f"render under '## The record', the level is the [N] row and the direction is prose."),
        ]
        fired = {"price_leg": True, "focus": focus, "commodity": commodity, "unit": (u_a or u_b),
                 "my_lo": lab_a, "p_lo": round(p_a, 4), "my_hi": lab_b, "p_hi": round(p_b, 4),
                 "net_reads": 2}                                  # A2: the literal two fetches above
        return lines, fired
    except Exception:  # noqa: BLE001 -- fail-closed: a price-leg failure must never break the v1 answer
        return [], {"price_leg": False, "reason": "error"}        # spend UNKNOWN, said so (review D4):
        #                                                           DELIBERATELY no net_reads -- the seam
        #                                                           routes this to the decline key and the
        #                                                           missing counter makes the walk decline
        #                                                           turn_spend_unknown; a bare None left
        #                                                           "unknown" indistinguishable from
        #                                                           "never ran" and 2 paid reads scored 0


# ── RV-READING: the directional price leg on a FIRED cross-commodity pair (2026-08-29) ────────────────
# The pair's price standing (constructed spread history + rank/sigma/streak) set beside the balance-sheet
# divergence the fork already rendered, with a deterministic three-valued alignment verdict -- an OBSERVED
# reading, never a forecast (the R3 / BANNED_PATTERN doctrine; the leg-local fence below is belt three).
# SEAM: renders in _run_xc AFTER _reroute_xc returns `fired` -- it never chooses a pair (the D-XT seam owns
# pair choice), and _reroute_xc stays byte-identical (its comove positional-stub and the transmission
# composer's direct per-link calls both forbid touching it; the reading deliberately does NOT ride
# transmission links -- one reading per turn, two fetches, POST-CAP). Gated ONLY by the answer.py-threaded
# `rv_reading` kwarg (GRAPHRAG_RV_READING read THERE, never here -- the [F3]/pace discipline), and dropped
# whole on any historical-asof turn via the SAME price_replay belt the R4 context lane rides (the pink
# sheet is latest-only with retroactive WB revisions -- C-2). R4 GOVERNANCE: this is a SYNTHESIZED leg (no
# map row for either R4 half to inspect), so config_check's R4c term binds _RV_PRICE_TABLE +
# _RV_PRICE_SERIES to an explicit allow-list -- the fence gets no silent door beside it (the SEAM-B gap,
# closed). The section-6 owner ask (a `price_relative` R4 lane) governs the FLAG flip; the build is dark
# and correct either way.
_RV_PRICE_TABLE = "silver_pink_sheet"
_RV_PRICE_MONTHS = 60          # the card's OWN 5-year z window (tables.yaml zscore_5yr twins) -- one
#                                window family, never a second number declared here.
# slug -> (pink-sheet metric, reader label). The label names the COMMODITY, never the contract (the
# _xc_label rule); every ABSENCE is an honest decline and each is written down -- silence is not admission:
#   palm_olein_dce      -- the WB carries CPO, not olein; a CPO price under an olein label is the
#                          undisclosed-substitute class (the A3 defect at _price_pair)
#   white_sugar         -- the WB carries raw world/EU/US sugar, no white-sugar series
#   barley, sorghum     -- WB DISCONTINUED both after 2020-08; a windowed read to a 2026 asof returns a
#                          2020 number wearing a current label (the card's own trap (1))
#   canola_ice, french_rapeseed_matif, rapeseed_meal_zce -- no canola/rapeseed SEED and no rapeseed meal
#                          on the card (only rapeseed OIL)
#   every JSE / MATIF / CEPEA / DCE-grade slug -- no WB world benchmark corresponds
_RV_PRICE_SERIES = {
    "soybean_oil_cbot":             ("soybean_oil_usd_t",     "world soybean oil"),
    "soybean_oil_dce":              ("soybean_oil_usd_t",     "world soybean oil"),
    "malaysian_crude_palm_oil_cme": ("palm_oil_cpo_usd_t",    "world crude palm oil"),
    "rapeseed_oil_zce":             ("rapeseed_oil_usd_t",    "world rapeseed oil"),
    "soybean_meal_cbot":            ("soybean_meal_usd_t",    "world soybean meal"),
    "soybean_meal_dce":             ("soybean_meal_usd_t",    "world soybean meal"),
    "soybeans_cbot":                ("soybeans_usd_t",        "world soybeans"),
    "corn_cbot":                    ("maize_usd_t",           "world maize (US Gulf)"),
    "soft_red_winter_wheat_cbot":   ("wheat_us_srw_usd_t",    "US soft red winter wheat"),
    "hard_red_winter_wheat_kcbt":   ("wheat_us_hrw_usd_t",    "US hard red winter wheat"),
    "sunflower_oil":                ("sunflower_oil_usd_t",   "world sunflower oil"),
    "arabica_coffee":               ("coffee_arabica_usd_t",  "world arabica coffee"),
    "robusta_coffee":               ("coffee_robusta_usd_t",  "world robusta coffee"),
    "raw_sugar":                    ("raw_sugar_world_usd_t", "world raw sugar"),
    "cotton":                       ("cotton_a_index_usd_t",  "the Cotton A Index"),
    "rough_rice_cbot":              ("rice_thai_5pct_usd_t",  "Thai 5% broken white rice"),
    "cocoa":                        ("cocoa_usd_t",           "world cocoa"),
}
# D6 (C20 on the PRICE leg): where the balance-sheet label (_xc_label) and the price label name DIFFERENT
# aggregates, the directive says so out loud -- the not-the-same-aggregate sentence, per leg. Without it
# the reading is the C20 class the estate calls cardinal (an all-class number narrated as one class).
_RV_C20_NOTES = {
    "soft_red_winter_wheat_cbot":  "all-class world wheat on its balance-sheet row, while this price is "
                                   "the US soft red winter benchmark specifically",
    "hard_red_winter_wheat_kcbt":  "all-class world wheat on its balance-sheet row, while this price is "
                                   "the US hard red winter benchmark specifically",
    "corn_cbot":                   "world corn on its balance-sheet row, while this price is the US Gulf "
                                   "maize benchmark specifically",
    "rough_rice_cbot":             "world rough rice on its balance-sheet row, while this price is the "
                                   "Thai 5% broken white export benchmark specifically",
    "cotton":                      "world cotton on its balance-sheet row, while this price is the Cotton "
                                   "A Index specifically",
}
# The leg-local forward-modal fence (belt (a) of three; the pace_register_ok precedent). Bare
# narrow/widen/rose/fell are NOT fenced -- honest past-tense observation (fencing the bare stem is the
# squeez\w* collision register.py already learned); what is fenced is the FORWARD modal + the valuation
# adjectives + the trade framing. One hit drops the whole block.
_RV_READING_BANNED_RX = re.compile(
    r"\b(should|will|would|ought to|is likely to|expects?|expected|due to|set to|poised to|primed to)\s+"
    r"(re)?(narrow|widen|converge|diverge|revert|normalis\w*|normaliz\w*|close|mean[- ]revert)\w*\b"
    r"|\bmean[- ]reversion\b|\bcloses? the gap\b"
    r"|\b(too|historically) (wide|narrow|cheap|rich|expensive)\b"
    r"|\bconvergence (trade|play|setup)\b", re.I)
_RV_WINDOW_RX = re.compile(r"^MY(\d{4})-MY(\d{4})$")   # D3: mya0 is NOT in the fired interface; it is
#                                                       recovered by this PINNED parse of fired['window']
#                                                       (f"MY{mya0}-MY{mya1}") -- the alternative (adding
#                                                       myA0 to the dict) breaks the _reroute_xc-unchanged
#                                                       promise. A parse miss omits the verdict, honestly.


def _months_back(asof, n: int) -> str:
    """`asof` minus `n` months, as a first-of-month ISO date -- pure string arithmetic on the SUPPLIED
    asof (the _covering_my idiom: this module reads no clock)."""
    y, m = int(str(asof)[:4]), int(str(asof)[5:7])
    tot = y * 12 + (m - 1) - int(n)
    return f"{tot // 12:04d}-{tot % 12 + 1:02d}-01"


def _rv_price_series(qfn, metric: str, asof) -> dict:
    """ONE windowed pink-sheet read: the trailing _RV_PRICE_MONTHS months to `asof`. The pink sheet is
    WIDE and FLAT -- no commodity_col, no country_col, the metric IS the series -- so both are None. PIT
    is the fetch_window stack's (t2 clamp + the card's publication_lag_days as-of guard + data_date
    semantics); the replay belt is applied ABOVE this call, at the _run_xc gate."""
    return fetch_window(qfn, table=_RV_PRICE_TABLE, metric=metric, commodity=None, country=None,
                        t1=_months_back(asof, _RV_PRICE_MONTHS), t2=asof, asof=asof,
                        agg="series", period=None, period_type="date")


def _rv_axes(rec: dict, card_metric) -> tuple:
    """(values, dates, unit) off a pink-sheet series call-record, oldest -> newest as fetched (ASC total
    order). Rows missing a parseable value or a date are skipped -- the join is by date, so a dateless
    row can never be joined honestly. Unit: the fetched row's own (the F6 rule), card unit as fallback.

    THE ROW'S DATE KEY IS `knowledge_date` (measured 2026-08-29, the treatment-arm RCA): query._extras
    surfaces the DP-5-normalized date under the knowledge alias for silver_pink_sheet
    (knowledge_date_col == date), and the row carries NO `unit` key at all -- the first arm's fixtures
    invented both, so every cloud row declined empty_series while the suite was green. The fixture
    shape is now pinned to the REAL keys."""
    vals, dates, unit = [], [], ""
    for r in (rec.get("rows") or []):
        d = str(r.get("date") or r.get("data_date") or r.get("knowledge_date") or "")[:10]
        try:
            v = float(str(r.get("value")).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if not d:
            continue
        vals.append(v)
        dates.append(d)
        if not unit and r.get("unit"):
            unit = str(r.get("unit"))
    if not unit:
        unit = str(getattr(card_metric, "unit", None) or "")
    return vals, dates, unit


def _rv_call(metric: str, tag: str, value, period: str, asof, *, unit: str,
             date: str | None = None) -> dict:
    """A synthetic pink-sheet call-record so a narrated reading magnitude IS a citable, value-checkable
    [N] row (the _xc_call/_price_call discipline). `tag` is the READER-FACING series expression riding
    the query's commodity slot ('world crude palm oil', 'world soybean oil minus world crude palm oil')
    so _series_tag renders '[series: <tag>; table: <pink-sheet label>]' -- the W4 A/B scope discipline.
    THE RAW METRIC ID NEVER RIDES THE TAG: `register.internal_leaks` matches the *_usd_t vocabulary on
    the model's copy-surface (measured -- the design's own template leaked it; the pin caught it), so
    the id stays machine-side in `metric` for the locator while the tag speaks reader words (the A1/F21
    table_label rule, applied to the series axis). Derived rows carry EXPLICIT unit strings (D5: eval's
    unit_present pin covers every valued citation on this table) and the latest observation's date
    (one-sided: derived-later-than-inputs, the _endpoint_row doctrine)."""
    row: dict = {"value": value, "unit": unit}
    if date:
        row["knowledge_date"] = date        # the REAL pink-sheet row key (measured 2026-08-29): the
        #                                     DP-5 date surfaces as knowledge_date, and it is the key
        #                                     citations.from_number stamps [known ...] from
    return {"query": {"table": _RV_PRICE_TABLE, "metric": metric, "commodity": tag,
                      "country": None, "period": period, "asof": asof},
            "rows": [row], "status": "ok"}


def _rv_ordinal(p: float) -> str:
    """41.0 -> '41st' (reader-facing rank token; the ROW stores the same rounded integer, so the printed
    figure and the injected figure are one number, never a 1%-tolerance gamble on a small rank)."""
    i = int(round(p))
    if 10 <= i % 100 <= 20:
        return f"{i}th"
    return f"{i}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(i % 10, 'th') }"


def _rv_era_bounds(fired: dict, source: str, windows: list | None):
    """(w_lo_ym, w_hi_ym) -- the fired era's OWN CALENDAR month bounds, recovered exactly as the
    landed verdict recovers them (_RV_WINDOW_RX parse matched back through _my_span(w, source)).
    Leg-symmetric by construction (the F1 fix); None on any miss."""
    m = _RV_WINDOW_RX.match(str(fired.get("window") or ""))
    if not (m and windows):
        return None
    want = list(range(int(m.group(1)), int(m.group(2)) + 1))
    era = next((w for w in windows if _my_span(w, source) == want), None)
    if era is None:
        return None
    asof_d = str(fired.get("asof") or "")[:10]
    hi = str(era[1])[:10]
    return (str(era[0])[:7], (min(hi, asof_d) if asof_d else hi)[:7])


def _rv_one_sided_rung(source: str, target: str, fired: dict, qfn, asof, calls: list, base: int,
                       windows: list | None, *, missing: str, reason: str) -> tuple:
    """REGIONAL one-sided price rung (design B4.2 + the OWNER AMENDMENT 2026-08-29): the MAPPED leg
    renders its own level + own percentile + its own per-leg verdict (fundamentals direction vs its
    OWN price direction -- no FX anywhere in that comparison); the ABSENT leg speaks its OWN settle
    in its OWN currency when silver_futures_eod holds it (_RV_EOD_LEVEL -- one front-expiry read; a
    front-month HISTORY needs the per-session roll only gold_futures_spreads precomputes, so the
    level renders and the history honestly does not); then the MEASURED per-slug absence sentence
    for the comparable history. NO cross-leg price figure exists in this rung by construction --
    the cross-currency comparison stays refused with its reason named. Reached ONLY with
    regional=True (LOCK 1). Never raises past the caller's belt."""
    from leviathan.graphrag.numbers import stats as st
    ma = _RV_PRICE_SERIES.get(source) or _RV_PRICE_SERIES.get(target)
    mapped = source if _RV_PRICE_SERIES.get(source) else target
    try:
        declared = getattr(_registry().get(_RV_PRICE_TABLE), "metrics", None) or {}
    except Exception:  # noqa: BLE001
        declared = {}
    if not ma or ma[0] not in declared:                 # refute-v2 E5: the declared gate applies HERE too
        return [], {"decline": "no_metric_map"}
    rec = _rv_price_series(qfn, ma[0], asof)
    fetches = 1
    if rec.get("status") != "ok":
        return [], {"decline": "empty_series", "fetches": fetches}
    vals, dts, unit = _rv_axes(rec, declared.get(ma[0]))
    if not vals:
        return [], {"decline": "empty_series", "fetches": fetches}
    lbl = ma[1]
    local: list = []
    lines: list = []
    n = base
    ym = dts[-1][:7]
    n += 1
    local.append(_shown(_rv_call(ma[0], lbl, round(vals[-1], 4), f"{dts[-1]}..{dts[-1]}", asof,
                                 unit=unit or "unlabelled", date=dts[-1]), vals[-1]))
    lines.append(f"- [N{n}] {lbl}, monthly benchmark price {ym}: {vals[-1]:.2f} "
                 f"{unit}".rstrip() + _series_tag(local[-1]["query"]))
    pc = st.percentile(vals[-1], vals)
    if not pc.get("declined"):
        n += 1
        pv = int(round(pc["value"]))
        local.append(_shown(_rv_call(ma[0], lbl, pv, f"{dts[0]}..{dts[-1]}", asof,
                                     unit="percentile", date=dts[-1]), pv, pc["n"]))
        lines.append(f"- [N{n}] where {lbl}'s own price stands within its {pc['n']}-month span to "
                     f"{ym}: {_rv_ordinal(pv)} percentile" + _series_tag(local[-1]["query"]))
    # the per-leg verdict: the MAPPED leg's own fundamentals delta vs its OWN price change
    d_leg = fired.get("dA") if mapped == fired.get("commodityA") else fired.get("dB")
    bounds = _rv_era_bounds({**fired, "asof": asof}, source, windows)
    change = _rv_leg_window_change(vals, dts, bounds[0], bounds[1]) if bounds else None
    leg_verdict = _regional_leg_verdict(d_leg, change)
    # OWNER AMENDMENT: the absent board's OWN settle, own currency -- an observed fact, no FX
    eod = _RV_EOD_LEVEL.get(missing)
    eod_rendered = False
    if eod is not None:
        fetches += 1
        erec = fetch_window(qfn, table=_RV_EOD_TABLE, metric=eod[0], commodity=missing,
                            country=None, t1=None, t2=None, asof=asof, agg="front_expiry",
                            period=None, period_type="date")
        erow = _headline_row(erec) or {}
        try:
            ev = float(str(erow.get("value")).replace(",", ""))
        except (TypeError, ValueError):
            ev = None
        if erec.get("status") == "ok" and ev is not None:
            eu_unit = str(erow.get("unit") or "")
            n += 1
            # a READER-facing synthetic (the _rv_call law: the raw contract slug in a tag fires
            # register.internal_leaks -- pin-caught twice now); the machine metric/table ride the
            # locator; the session date is the row's `knowledge_date` (the REAL front_expiry row
            # shape, measured 2026-08-29 -- there is no trade_date key); `contract_month` rides the
            # query so the tag names the DELIVERY MONTH (D-OJ-5: a survivor-basis level without its
            # delivery month is a scope mis-attribution).
            syn = {"query": {"table": _RV_EOD_TABLE, "metric": eod[0], "commodity": eod[1],
                             "country": None, "period": None, "asof": asof,
                             "contract_month": erow.get("contract_month")},
                   "rows": [{k: v for k, v in {"value": round(ev, 4), "unit": eu_unit,
                                               "knowledge_date": (erow.get("knowledge_date")
                                                                  or erow.get("trade_date"))}.items()
                             if v not in (None, "")}],
                   "status": "ok"}
            local.append(_shown(syn, ev))
            lines.append(f"- [N{n}] {eod[1]}, front-month settle (its own currency, latest session): "
                         f"{ev:.2f} {eu_unit}".rstrip() + _series_tag(syn["query"]))
            eod_rendered = True
    vw = _RV_VERDICT_WORD.get(leg_verdict, "UNRESOLVED")
    lines.append(
        f"VERDICT ({vw}) on the {lbl} leg: its own balance-sheet move is set against its OWN price "
        f"move only. The pair verdict is ONE-SIDED: {reason}."
        + (f" The {eod[1]}'s own settle is shown above in its own currency; no cross-currency "
           f"comparison is made between the two boards -- a difference needs one unit and a ratio "
           f"would carry an exchange rate this platform does not hold." if eod_rendered else
           " No cross-currency comparison is made between the two boards.")
        + " These are the sources' own published figures -- not exchange settles re-based, not a "
          "board level for the other contract. Render under '## Cross-commodity', after the "
          "balance-sheet rows, as an OBSERVED standing: no statement is made about where either "
          "price goes next.")
    if _RV_REGIONAL_BANNED_RX.search("\n".join(lines)):
        return [], {"decline": "fenced"}
    calls.extend(local)
    return lines, {"form": None, "rung": "one_sided", "alignment": leg_verdict,
                   "pair_verdict": "one_sided", "n": 0, "metric_a": ma[0], "fetches": fetches,
                   "absent_leg": missing, "shown_leg": mapped, "eod_level": eod_rendered,
                   "rows": len(local)}


def _rv_price_reading(pair_row, source: str, target: str, fired: dict, qfn, asof,
                      calls: list, base: int, windows: list | None = None, *,
                      regional: bool = False, derived: bool = False,
                      extrema_own_date: bool = False) -> tuple:
    """The reading composer. Returns (lines, trace) on render; ([], {'decline': tag}) on any honest
    decline; ([], None) only on a shape so broken there is nothing to record. Synthetic rows are built
    LOCALLY and appended to `calls` only after the leg-local fence passes -- a fenced drop must leave no
    orphan [N] rows behind. A = `source` ALWAYS (the orientation law: _reroute_xc labels legs off
    source/target, so dA and the spread must be measured on the same leg or the verdict silently
    inverts -- pinned both ways).

    REVIEW ROUND 1 (2026-08-29, wf_64ebc032) folded, four confirmed findings:
    * F1 (the cardinal class): the verdict's price window is the fired ERA's OWN CALENDAR DATES
      (recovered from `windows` by matching `_my_span` against the fired MY string), NEVER an MY
      reconstruction from `_my_start(source)` -- the two legs' MY calendars differ (corn 9 vs SRW 6),
      so an MY-rebuilt clip followed the leg the user happened to name and the SAME facts produced
      OPPOSITE verdicts across orientations. Era dates are leg-symmetric by construction.
    * M3: a coverage floor -- the era must sit INSIDE the price history's own envelope, or the
      verdict is omitted; a point count alone let 'the window they share' describe months the price
      series never held.
    * M4: a CO-MOVE turn DECLINES the reading outright. The co-move block's own directive is
      'su_ratio percentages only'; appending a price-relative verdict under that marker put two
      contradicting directives in one block. (Supersedes the earlier own-marker ruling -- measured
      conflict beats the plan.)
    * M1/M2: derived rows carry PLAIN-WORD metric tokens and span-form periods -- `query.metric`
      reaches the reader through citations.from_number's fallback, and a bare 'YYYY-MM' period gets
      MY-prefixed by citations._period_label (the documented MYMY class). Never raises."""
    try:
        from leviathan.graphrag.numbers import stats as st
        if fired.get("comove"):
            return [], {"decline": "comove"}
        ma, mb = _RV_PRICE_SERIES.get(source), _RV_PRICE_SERIES.get(target)
        if ma is None and mb is None:
            return [], {"decline": "no_metric_map"}     # zero-mapped: unchanged (refute-v2 E18 pins it)
        if ma is None or mb is None:
            if not regional:                            # LOCK 1 (refute-v1 D1): World pairs are UNTOUCHED
                return [], {"decline": "no_metric_map"}  # -- HEAD behaviour, byte-identical; three landed
            #                                              pairs decline through this exact branch
            missing = target if mb is None else source
            reason = _RV_PRICE_ABSENCE.get(missing)
            if reason is None:                          # LOCK 2: never a fabricated absence reason
                return [], {"decline": "no_absence_reason"}
            return _rv_one_sided_rung(source, target, fired, qfn, asof, calls, base, windows,
                                      missing=missing, reason=reason)
        try:
            declared = getattr(_registry().get(_RV_PRICE_TABLE), "metrics", None) or {}
        except Exception:  # noqa: BLE001
            declared = {}
        if ma[0] not in declared or mb[0] not in declared:
            return [], {"decline": "no_metric_map"}     # undeclared attribute -> decline, never a 0-row SQL
        ra = _rv_price_series(qfn, ma[0], asof)
        rb = _rv_price_series(qfn, mb[0], asof)
        if ra.get("status") != "ok" or rb.get("status") != "ok":
            return [], {"decline": "empty_series"}
        va, da, ua = _rv_axes(ra, declared.get(ma[0]))
        vb, db, ub = _rv_axes(rb, declared.get(mb[0]))
        if not va or not vb:
            return [], {"decline": "empty_series"}
        la, lb = ma[1], mb[1]
        ps = st.pair_spread(va, da, ua, vb, db, ub, label_a=la, label_b=lb)
        if ps.get("declined"):
            # m2: a structural (shape) decline carries no guard tag by design in stats; it is a
            # data-shape refusal, never an exception -- "error" is reserved for the except below.
            guard = ps.get("guard") or "shape"
            if guard not in (st.UNIT_GUARD, st.CURRENCY_GUARD, st.DENOMINATOR_GUARD):
                return [], {"decline": guard}
            # level_only rung (FIXTURE-ONLY under Pink-Sheet plumbing -- every leg USD/mt): the two legs
            # read ONE AT A TIME, each its own level + own rank, and the spread's absence is said in the
            # refusal's own words.
            local: list = []
            lines: list = []
            n = base
            for lbl, met, vals, dts, unit in ((la, ma[0], va, da, ua), (lb, mb[0], vb, db, ub)):
                n += 1
                ym = dts[-1][:7]
                local.append(_shown(_rv_call(met, lbl, round(vals[-1], 4), f"{dts[-1]}..{dts[-1]}", asof,
                                             unit=unit or "unlabelled", date=dts[-1]), vals[-1]))
                lines.append(f"- [N{n}] {lbl}, monthly benchmark price {ym}: {vals[-1]:.2f} "
                             f"{unit}".rstrip() + _series_tag(local[-1]["query"]))
                pc = st.percentile(vals[-1], vals)
                if not pc.get("declined"):
                    n += 1
                    pv = int(round(pc["value"]))
                    local.append(_shown(_rv_call(met, lbl, pv, f"{dts[0]}..{dts[-1]}", asof,
                                                 unit="percentile", date=dts[-1]),
                                        pv, pc["n"]))
                    lines.append(f"- [N{n}] where {lbl}'s own price stands within its {pc['n']}-month "
                                 f"span to {ym}: {_rv_ordinal(pv)} percentile"
                                 + _series_tag(local[-1]["query"]))
            lines.append(f"PRICE-RELATIVE declined: {ps.get('reason')} -- the two legs are read one at a "
                         f"time above and no spread between them is computed. These are World Bank monthly "
                         f"cash benchmark AVERAGES, as published at the current WB release -- not exchange "
                         f"settles, not a board level for either contract. Render under "
                         f"'## Cross-commodity', after the balance-sheet rows, as an OBSERVED standing: "
                         f"no statement is made about where either price goes next.")
            if _RV_READING_BANNED_RX.search("\n".join(lines)):
                return [], {"decline": "fenced"}
            calls.extend(local)
            return lines, {"form": None, "rung": "level_only", "alignment": "undetermined",
                           "n": 0, "metric_a": ma[0], "metric_b": mb[0], "fetches": 2,
                           "decline_guard": guard}
        # -- constructed history in hand ------------------------------------------------------------
        n_join = int(ps["n"])
        series, dates = ps["series"], ps["dates"]
        form = ps["form"]
        ym = dates[-1][:7]
        span = f"{dates[0]}..{dates[-1]}"                  # M2: span-form period -- never a bare YYYY-MM
        obs = f"{dates[-1]}..{dates[-1]}"                  #     (citations._period_label MY-prefixes those)
        pair_word = "spread" if form == "difference" else "ratio"
        sunit = (ps.get("unit") or "") if form == "difference" else "ratio"
        joiner = "minus" if form == "difference" else "over"
        expr_tag = f"{la} {joiner} {lb}"                   # reader-side (the series tag)
        # M1: the derived rows' metric tokens are PLAIN WORDS -- citations.from_number renders
        # query.metric through _metric_display_name, whose fallback is the raw string, so a *_usd_t
        # expression there reaches the reader's Sources block and fires internal_leaks (review-executed).
        # The true metric ids ride the trace (metric_a/metric_b below), never a rendered surface.
        m_spread = f"monthly benchmark {pair_word}"
        fmtv = (lambda v: f"{v:.2f}x") if form == "ratio" else \
               (lambda v: f"{v:+.2f} {sunit}".rstrip())    # m7: one rendering per family, everywhere
        local = []
        lines = []
        n = base
        # the two leg levels (each leg's own [N] level row -- the only place its own magnitude prints;
        # their metric ids ARE declared card metrics, so from_number renders the card label -- clean)
        for lbl, met, latest, unit, dt in ((la, ma[0], ps["a_latest"], ua, dates[-1]),
                                           (lb, mb[0], ps["b_latest"], ub, dates[-1])):
            n += 1
            local.append(_shown(_rv_call(met, lbl, round(float(latest), 4), obs, asof,
                                         unit=unit, date=dt), latest))
            lines.append(f"- [N{n}] {lbl}, monthly benchmark price {ym}: {float(latest):.2f} "
                         f"{unit}".rstrip() + _series_tag(local[-1]["query"]))
        # ── D-DA LANE 2 (design v2 ROWS 6-7; dark -- `derived` defaults False and the prod call site
        #    does not pass it): each leg's OWN standing beside its level, closing the confirmed R5
        #    asymmetry (the full rung printed levels with no rank while level_only and the one-sided
        #    rung both rank). SAMPLE = the leg's UNJOINED series (refute m1: the joined subsample
        #    would hand one leg two different percentiles depending on which rung fired -- the
        #    two-headlines class across rungs of one function). ZERO added fetches.
        _dv_att: dict = {}
        _dv_eod_fetches = 0
        if derived:
            for lbl, vals, dts in ((la, va, da), (lb, vb, db)):
                pc = st.percentile(vals[-1], vals)
                if not pc.get("declined"):
                    pv = int(round(pc["value"]))
                    n += 1
                    local.append(_shown(_rv_call("monthly benchmark percentile", lbl, pv,
                                                 f"{dts[0]}..{dts[-1]}", asof, unit="percentile",
                                                 date=dts[-1]), pv, pc["n"]))
                    lines.append(f"- [N{n}] where {lbl}'s own price stands within its "
                                 f"{pc['n']}-month span to {dts[-1][:7]}: {_rv_ordinal(pv)} "
                                 f"percentile" + _series_tag(local[-1]["query"]))
                zs = st.zscore(vals[-1], vals)
                if not zs.get("declined"):
                    zl = round(float(zs["value"]), 2)
                    n += 1
                    local.append(_shown(_rv_call("monthly benchmark sigma", lbl, zl,
                                                 f"{dts[0]}..{dts[-1]}", asof,
                                                 unit="sigma vs the window mean",
                                                 date=dts[-1]), zl))
                    lines.append(f"- [N{n}] {lbl}'s own price against its own window average: "
                                 f"{zl:+.2f} sigma" + _series_tag(local[-1]["query"]))
                    _dv_att[lbl] = (zl, n)
            # D-DA lane 2b (owner-ratified fresh levels): each mapped leg's OWN front-month settle,
            # own currency/unit -- the one-sided rung's EOD idiom verbatim (reader synthetic, the
            # contract_month on the query, knowledge_date row key, NO conversion of anything).
            for slug, lbl in ((source, la), (target, lb)):
                eodf = _RV_EOD_FRESH.get(slug)
                if eodf is None:
                    continue
                _dv_eod_fetches += 1
                erec = fetch_window(qfn, table=_RV_EOD_TABLE, metric=eodf[0], commodity=slug,
                                    country=None, t1=None, t2=None, asof=asof, agg="front_expiry",
                                    period=None, period_type="date")
                erow = _headline_row(erec) or {}
                try:
                    ev = float(str(erow.get("value")).replace(",", ""))
                except (TypeError, ValueError):
                    ev = None
                if erec.get("status") == "ok" and ev is not None:
                    eu_unit = str(erow.get("unit") or "")
                    n += 1
                    syn = {"query": {"table": _RV_EOD_TABLE, "metric": eodf[0], "commodity": eodf[1],
                                     "country": None, "period": None, "asof": asof,
                                     "contract_month": erow.get("contract_month")},
                           "rows": [{k: v for k, v in {"value": round(ev, 4), "unit": eu_unit,
                                                       "knowledge_date": (erow.get("knowledge_date")
                                                                          or erow.get("trade_date"))
                                                       }.items() if v not in (None, "")}],
                           "status": "ok"}
                    local.append(_shown(syn, ev))
                    lines.append(f"- [N{n}] {eodf[1]}, front-month settle (its own currency, latest "
                                 f"session): {ev:.2f} {eu_unit}".rstrip()
                                 + _series_tag(syn["query"]))
        # the spread/ratio level (2 dp stored == 2 dp printed: a near-zero spread must not gamble on the
        # verifier's 1% tolerance)
        sp2 = round(float(ps["value"]), 2)
        n += 1
        h_sp = n
        local.append(_shown(_rv_call(m_spread, expr_tag, sp2, obs, asof, unit=sunit,
                                     date=dates[-1]), sp2))
        if form == "difference":
            lines.append(f"- [N{h_sp}] {la} {joiner} {lb}, monthly benchmark spread {ym}: {sp2:+.2f} "
                         f"{sunit}".rstrip() + _series_tag(local[-1]["query"]))
        else:
            lines.append(f"- [N{h_sp}] {la} relative to {lb}, monthly benchmark ratio {ym}: {sp2:.2f}x"
                         + _series_tag(local[-1]["query"]))
        rung = "full"
        rank_bits = []
        if n_join >= st.MIN_PERCENTILE_N:
            pc = st.percentile(ps["value"], series)
            zs = st.zscore(ps["value"], series)
            up, down = st.streak(series, "up"), st.streak(series, "down")
            pv = int(round(pc["value"]))
            n += 1
            h_pc = n
            local.append(_shown(_rv_call(f"{pair_word} percentile", expr_tag, pv, span, asof,
                                         unit="percentile", date=dates[-1]),
                                pv, n_join))
            # K1 RCA (2026-09-01, audited pair 101703Z/103129Z): a FREE-standing window-length numeral
            # on the writer's copy-surface ("of the prior 58 months") has no backing row, so the P9-B
            # all-numbers guard stripped the reading's own payoff sentence. The hyphenated "{n}-month"
            # form is the extractor's duration-modifier exemption (measured surviving in the same
            # corpus) -- every copy-surface handed to the writer MUST use it.
            lines.append(f"- [N{h_pc}] where that {pair_word} stands within its own {n_join}-month span "
                         f"to {ym}: {_rv_ordinal(pv)} percentile" + _series_tag(local[-1]["query"]))
            rank_bits.append(f"the {_rv_ordinal(pv)} percentile of the {n_join}-month window to {ym} "
                             f"[N{h_pc}]")
            if zs.get("declined"):
                rung = "no_sigma"
                rank_bits.append(f"every month of that {n_join}-month window prints the same "
                                 f"{pair_word}, so no sigma is computed")
            else:
                z2 = round(float(zs["value"]), 2)
                n += 1
                h_z = n
                local.append(_shown(_rv_call(f"{pair_word} sigma", expr_tag, z2, span, asof,
                                             unit="sigma vs the window mean",
                                             date=dates[-1]), z2))
                lines.append(f"- [N{h_z}] that {pair_word} against its own window average: {z2:+.2f} sigma"
                             + _series_tag(local[-1]["query"]))
                rank_bits.append(f"{z2:+.2f} sigma against that window's own average [N{h_z}]")
            run, word = (up["value"], "rises") if (up.get("value") or 0) > 0 else \
                        (down.get("value") or 0, "falls")
            if run:
                n += 1
                h_st = n
                local.append(_shown(_rv_call(f"{pair_word} streak", expr_tag, int(run), span, asof,
                                             unit="consecutive months",
                                             date=dates[-1]), int(run)))
                lines.append(f"- [N{h_st}] consecutive monthly {word} in that {pair_word} ending {ym}: "
                             f"{int(run)}" + _series_tag(local[-1]["query"]))
                # K1 pair #2 (2026-09-01, 113447Z): the streak clause is DECOUPLED from the payoff
                # rank_bits. The writer respells a small count as a word ("after two consecutive
                # monthly rises [N]") even under the TRANSCRIPTION directive, and that one handle's
                # per-handle mismatch then deletes the WHOLE payoff sentence (percentile+sigma+level).
                # The streak stays a block row above; if the writer narrates it and respells, only
                # its own garnish sentence dies -- the payoff survives.
        else:
            # ordinal_thin: 2 <= n_join < 8 -- the estate's ordinal-when-thin instrument. extrema, never
            # a rank the floor refuses.
            rung = "ordinal_thin"
            ex = st.extrema(series)
            hi2, lo2 = round(float(ex["max"]), 2), round(float(ex["min"]), 2)
            # THE EXTREMA CLOCK, REPAIRED BEHIND ITS OWN FLAG (GRAPHRAG_EXTREMA_OWN_DATE, read at the
            # answer seam and threaded DOWN as an argument -- this module reads no env). `stats.extrema`
            # already computes `argmin`/`argmax` and NOTHING has ever read them, so both rows here have
            # always been stamped with `dates[-1]`, the SERIES END: an extrema_max row for a 2022 peak
            # asserts the peak was observed on a date it was not, which is a vintage-law defect on a
            # LIVE serving surface. When the flag is ON the row carries THE EXTREME'S OWN date, taken
            # from the SAME axis the value axis was built from and by the SAME drop rule -- `dates` is
            # built beside `series` in one pass, so the indices are aligned by construction. When the
            # axis is NOT aligned the site DECLINES and counts, rather than guessing. WHEN OFF:
            # byte-identical to today, which is what keeps the locator's own arm from measuring this.
            _ex_hi_d = _ex_lo_d = dates[-1]
            if extrema_own_date:
                _ai, _bi = ex.get("argmax"), ex.get("argmin")
                if (isinstance(_ai, int) and isinstance(_bi, int) and len(dates) == len(series)
                        and 0 <= _ai < len(dates) and 0 <= _bi < len(dates)):
                    _ex_hi_d, _ex_lo_d = dates[_ai], dates[_bi]
                else:
                    fired.setdefault("extrema_own_date_declines", []).append(
                        {"site": "rv_reading_ordinal_thin", "reason": "extrema_axis_unavailable"})
            n += 1
            h_hi = n
            local.append(_shown(_rv_call(f"{pair_word} extreme", expr_tag, hi2, span, asof, unit=sunit,
                                         date=_ex_hi_d), hi2, n_join))
            lines.append(f"- [N{h_hi}] the highest {pair_word} across the {n_join}-month history held: "
                         f"{fmtv(hi2)}" + _series_tag(local[-1]["query"]))
            n += 1
            h_lo = n
            local.append(_shown(_rv_call(f"{pair_word} extreme", expr_tag, lo2, span, asof, unit=sunit,
                                         date=_ex_lo_d), lo2, n_join))
            lines.append(f"- [N{h_lo}] the lowest {pair_word} across the {n_join}-month history held: "
                         f"{fmtv(lo2)}" + _series_tag(local[-1]["query"]))
            rank_bits.append(f"the held history for this pair is only a {n_join}-month span, below the "
                             f"{st.MIN_PERCENTILE_N}-month floor a rank or a sigma needs, so the "
                             f"{pair_word} is placed ORDINALLY against the months held -- the highest is "
                             f"{fmtv(hi2)} [N{h_hi}] and the lowest {fmtv(lo2)} [N{h_lo}] -- and no "
                             f"percentile and no z-score is computed")
        # D-DA LANE 2 attribution clause (ROW 7): ENGINE-named, never writer-derived, and never an
        # arithmetic identity (refute M3 -- no dSpread==dA-dB claim anywhere). The leg with the
        # larger own-history |sigma| carries the move; inside DV_ATTRIB_MARGIN neither leg is named.
        # Digits on both sigmas, each backed by its own [N] handle's shown pool -- verifier-proof.
        if derived and len(_dv_att) == 2:
            from leviathan.graphrag.numbers.derived import DV_ATTRIB_MARGIN
            (_al, (_az, _ah)), (_bl, (_bz, _bh)) = list(_dv_att.items())
            if abs(_az - _bz) > DV_ATTRIB_MARGIN:
                if abs(_az) >= abs(_bz):
                    _r, _o = (_al, _az, _ah), (_bl, _bz, _bh)
                else:
                    _r, _o = (_bl, _bz, _bh), (_al, _az, _ah)
                rank_bits.append(f"the move sits on {_r[0]} -- its own price at {_r[1]:+.2f} sigma "
                                 f"[N{_r[2]}] against {_o[0]} at {_o[1]:+.2f} sigma [N{_o[2]}]")
            else:
                rank_bits.append("both legs stand at similar points in their own histories, so "
                                 "neither leg is named as carrying the move")
        # -- the alignment verdict (F1 fix: the price window is the fired ERA's OWN CALENDAR DATES,
        #    leg-symmetric by construction -- the fired MY string is matched back to its era via
        #    _my_span(w, source), which reproduces exactly the string _reroute_xc minted. The sign flip
        #    happens EXACTLY once, at rel_tight's named negation -- su_ratio is a LOOSENESS measure, so
        #    A tightening RELATIVE to B means dA - dB < 0, while the spread RISING means A got dearer
        #    relative to B; swapping the legs negates BOTH terms, so the verdict word cannot move) ----
        verdict = "undetermined"
        set_against = ""
        m = _RV_WINDOW_RX.match(str(fired.get("window") or ""))
        d_a, d_b = fired.get("dA"), fired.get("dB")
        era = None
        if m and windows:
            my_span_want = list(range(int(m.group(1)), int(m.group(2)) + 1))
            era = next((w for w in windows
                        if _my_span(w, source) == my_span_want), None)
        if era is not None and d_a is not None and d_b is not None:
            w_lo = str(era[0])[:7]
            w_hi = min(str(era[1])[:10], str(asof)[:10])[:7]
            # M3 coverage floor: the era must sit INSIDE the price history's envelope -- a direction
            # asserted over months the series never held is the claim, falsified.
            if dates[0][:7] <= w_lo and w_hi <= dates[-1][:7]:
                clipped = [v for v, dt in zip(series, dates) if w_lo <= dt[:7] <= w_hi]
                if len(clipped) >= 2:
                    sc = clipped[-1] - clipped[0]
                    rel_tight = -(float(d_a) - float(d_b))   # > 0 <=> A TIGHTENED relative to B
                    if _sign(rel_tight) != 0 and _sign(sc) != 0:
                        verdict = "aligned" if _sign(rel_tight) == _sign(sc) else "at_odds"
                        va_word = "TIGHTENED" if float(d_a) < 0 else "LOOSENED"
                        vb_word = "TIGHTENED" if float(d_b) < 0 else "LOOSENED"
                        sc_word = "rose" if sc > 0 else "fell"
                        agree = ("the SAME direction" if verdict == "aligned" else "OPPOSITE directions")
                        # m5: WORDS ONLY here -- the pp figures already stand above with their own [N]
                        # handles, and a re-printed rounded twin (no handle, second spelling) was the
                        # two-headlines class.
                        set_against = (
                            f" Set against the balance sheets above: over {fired.get('window')} {la}'s "
                            f"stocks-to-use {va_word} while {lb}'s {vb_word} (the figures stand in the "
                            f"rows above), and the {pair_word} {sc_word} over that era's own months -- "
                            f"the fundamental gap and the price {pair_word} moved in {agree} over that "
                            f"era.")
        # -- the directive paragraph ----------------------------------------------------------------
        if form == "difference":
            level_clause = (f"{la} stands {abs(sp2):.2f} {sunit} {'over' if sp2 >= 0 else 'under'} "
                            f"{lb} [N{h_sp}]")
            what_it_is = (f"the figure is a {pair_word} in the shared unit and is never a level of "
                          f"either commodity")
        else:
            level_clause = f"{la} stands at {sp2:.2f} times {lb} [N{h_sp}]"
            what_it_is = ("the two series are quoted in different units, so this is a RATIO and not a "
                          "difference: a scale-free relative reading whose rank and sigma are exactly "
                          "those of the underlying relative price, and it is never quotable as a price "
                          "of either commodity in any unit")
        notes = [f"{_RV_C20_NOTES[s]}" for s in (source, target) if s in _RV_C20_NOTES]
        c20 = ("" if not notes
               else " NOTE -- not the same aggregate: " + "; and ".join(notes) + ".")
        lines.append(
            f"PRICE-RELATIVE on the monthly benchmark {pair_word}: {level_clause} -- "
            + "; ".join(rank_bits) + f".{set_against} These are World Bank monthly cash benchmark "
            f"AVERAGES, as published at the current WB release -- not exchange settles, not a board "
            f"level for either contract; {what_it_is}.{c20} Render under '## Cross-commodity', after "
            f"the balance-sheet rows, as an OBSERVED standing: no statement is made about where the "
            f"{pair_word} goes next. TRANSCRIPTION: copy every figure in this block as DIGITS exactly "
            f"as printed -- the consecutive-months count and the hyphenated N-month window form "
            f"included; a count respelled in words or a window length written as a bare number fails "
            f"the citation verifier and deletes the sentence it sits in.")
        if _RV_READING_BANNED_RX.search("\n".join(lines)):
            return [], {"decline": "fenced"}
        calls.extend(local)
        return lines, {"form": form, "rung": rung, "alignment": verdict, "n": n_join,
                       "metric_a": ma[0], "metric_b": mb[0], "fetches": 2 + _dv_eod_fetches,
                       "rows": len(local), "window": fired.get("window")}
    except Exception:  # noqa: BLE001 -- fail-closed: the reading must never break the fired fork
        return [], {"decline": "error"}


# ── RV-REGIONAL: the same-commodity cross-BOARD fork at REGIONAL scope (2026-08-29) ──────────────────
# Design: data/batch_runs/regional_rv_sitting/design_v2_20260829.md (SOUND-WITH-FIXES + the E-fix
# charter in docs/private/DXT_RV_CONTINUATION.md sec 4a) + the OWNER AMENDMENT (the EU leg speaks its
# own price in its own currency; only the CROSS-currency comparison stays refused). Flag:
# GRAPHRAG_RV_REGIONAL, read at the answer seam ONLY, threaded as the omit-when-off `rv_regional`
# kwarg. The pair row ships CONTEXTUAL (the loader hides it), so flag-off is inert twice over.
from collections import namedtuple as _namedtuple

_XcMetricSpec = _namedtuple("_XcMetricSpec",
                            ("key", "word", "unit", "sep", "delta_unit", "metric_id", "scale"))
_P4_SCALE: float | None = 100.0      # MEASURED (probe P4, data/batch_runs/rv_regional_probe_20260829
#                                      .json): the native silver_psd.su_ratio column IS the raw
#                                      ending_stocks/consumption ratio (implied_scale 1.0 on all six
#                                      probed cells, both scopes) -- so the narrate-% scale is 100,
#                                      the SAME family as the World path's psd_ending_stock_su_ratio
#                                      scale:100. Pinned against the banked probe cells. A None here
#                                      SKIPS the su_ratio metric at render (fail-closed).
_XC_REGIONAL_METRICS = (             # ORDERED; the census curates which become ROWS (design B3)
    _XcMetricSpec(key="su_ratio", word="stocks-to-use", unit="%", sep="", delta_unit="pp",
                  metric_id="su_ratio_regional", scale=_P4_SCALE),
    _XcMetricSpec(key="exports_mt", word="exports", unit="MMT", sep=" ", delta_unit="MMT",
                  metric_id="exports_regional", scale=1e-6),
)
_XC_REGIONAL_FETCH_CAP = 4           # 2 metrics x 2 legs; a breach DECLINES the block (never truncates)
XC_REGIONAL_METRIC_CAP = 2
XC_REGIONAL_MAX_ROWS_INJECTED = 18   # 4 lines x 3 rows + corr + corr-rank + US price level + US price
#                                      pct + MATIF own-currency level + its session row = 18 (the
#                                      owner amendment adds the EOD pair; the D-DV-1 namespace law)
XC_REGIONAL_DECLINES = ("not_regional_pair", "scope_unresolved", "no_history", "thin_history",
                        "composition_break", "projection_undeclared", "c20_missing", "cap",
                        "fenced", "error")
from leviathan.graphrag.numbers.stats import MIN_CORR_N as _MIN_CORR_N  # noqa: E402 -- pure leaf,
#                                             no cycle; ONE floor family (the census-proven-corr law)
MIN_REGIONAL_MY_N = _MIN_CORR_N              # census floor == the corr floor == 8
XC_REGIONAL_CORR_WINDOW = _MIN_CORR_N        # window == the floor -> >=8 shared MYs guarantees >=1 window
_XC_SCOPE_WORDS = {"United States": "US", "European Union": "EU", "France": "France",
                   "Brazil": "Brazil", "Vietnam": "Vietnam", "Thailand": "Thailand"}
# ONE producer for the regional label (refute-v2 E7): the map holds the slug's AGGREGATE word; the
# renderer prepends the pinned scope word. NO string surgery on _xc_label (two producers drift).
_XC_LABEL_REGIONAL = {
    "hard_red_winter_wheat_kcbt": "wheat (all classes)",
    "soft_red_winter_wheat_cbot": "wheat (all classes)",
    "french_wheat_matif": "wheat (all classes)",
}
# The C20 clause per (slug, country) -- MANDATORY, doubled; a block that cannot render both declines
# c20_missing. "This is the single most likely way this feature lies." (design E4)
_XC_REGIONAL_C20_NOTES = {
    ("hard_red_winter_wheat_kcbt", "United States"):
        "ALL-CLASS US wheat on its balance-sheet row, while the Kansas City board is the hard red "
        "winter contract specifically",
    ("soft_red_winter_wheat_cbot", "United States"):
        "ALL-CLASS US wheat on its balance-sheet row, while the Chicago board is the soft red "
        "winter contract specifically",
    ("french_wheat_matif", "European Union"):
        "the ALL-CLASS European Union aggregate on its balance-sheet row, while the MATIF board is "
        "the French milling-wheat contract specifically, and France is not separable on this sheet",
}
# Belt (a) delta over the landed reading fence: the ACTUAL cross-currency failure mode -- a model
# converting one board into the other's money to compare. Bare comparatives stay un-regexed (the
# squeez lesson); the STRUCTURAL fence is that no cross-leg price figure exists on a cross-currency
# pair at all.
_RV_REGIONAL_BANNED_RX = re.compile(
    _RV_READING_BANNED_RX.pattern
    + r"|\b(in (dollar|euro)[- ]terms|converted (to|into) (dollars|euros|usd|eur)"
      r"|dollar[- ]equivalent|euro[- ]equivalent|fx[- ]adjusted"
      r"|at (the )?(current |prevailing )?exchange rate)\b", re.I)
# Per-slug MEASURED absence reasons for the COMPARABLE-history half (refute-v1 D1: never one
# wheat-shaped constant -- three landed World pairs decline through the same seam and must keep
# their own honest reasons). The MATIF entry speaks to the missing marketing-year-grain HISTORY;
# the board's own LEVEL renders regardless (the owner amendment, _RV_EOD_LEVEL below).
_RV_MATIF_EOD_FIRST_OBS = "2026-08-06"   # tables.yaml "measured first banked trade date";
#                                          RE-MEASURED by probe P8 before the census pin banks.
_RV_PRICE_ABSENCE = {
    "french_wheat_matif": (
        "No comparable price HISTORY is held for the MATIF milling-wheat contract at this grain: "
        "the World Bank publishes no European milling-wheat benchmark, and this estate's own "
        "per-delivery-month record for that contract begins " + _RV_MATIF_EOD_FIRST_OBS + " -- no "
        "single delivery month spans the marketing-year window this comparison is measured over"),
    "sorghum": (
        "No comparable price history is held for sorghum: the World Bank discontinued its sorghum "
        "benchmark after 2020-08, so a read to this as-of would return a 2020 figure under a "
        "current label"),
    "barley": (
        "No comparable price history is held for barley: the World Bank discontinued its barley "
        "benchmark after 2020-08"),
    "canola_ice": (
        "No comparable price history is held for canola: the World Bank carries rapeseed OIL but "
        "no rapeseed or canola SEED benchmark"),
    "french_rapeseed_matif": (
        "No comparable price history is held for the MATIF rapeseed contract: the World Bank "
        "carries no rapeseed SEED benchmark"),
    "rapeseed_meal_zce": (
        "No comparable price history is held for rapeseed meal: the World Bank carries no "
        "rapeseed-meal benchmark"),
    "white_sugar": (
        "No comparable price history is held for white sugar: the World Bank carries raw world, EU "
        "and US sugar, and no white-sugar series"),
    "palm_olein_dce": (
        "No comparable price history is held for palm olein: the World Bank carries crude palm "
        "oil, not olein; a CPO price under an olein label would be an undisclosed substitute"),
}
# The two frozen price-scope sets (design B4.3, used by config_check step 9): a WORLD composite may
# never sit on a REGIONAL side (printing a world price against a regional sheet is the scope
# mismatch one level up from C20); an ORIGIN benchmark is admitted IFF its origin equals the pin.
# maize_usd_t stays in the world set DELIBERATELY pending its own adjudication (refute-v2 E14
# recorded the misfile question; fail-closed keeps it banned on a regional side either way).
_RV_PRICE_WORLD_BENCHMARKS = frozenset({
    "soybean_oil_usd_t", "palm_oil_cpo_usd_t", "rapeseed_oil_usd_t", "soybean_meal_usd_t",
    "soybeans_usd_t", "maize_usd_t", "sunflower_oil_usd_t", "coffee_arabica_usd_t",
    "coffee_robusta_usd_t", "raw_sugar_world_usd_t", "cotton_a_index_usd_t", "cocoa_usd_t"})
_RV_PRICE_ORIGIN = {
    "wheat_us_srw_usd_t": "United States",
    "wheat_us_hrw_usd_t": "United States",
    "rice_thai_5pct_usd_t": "Thailand"}
# OWNER AMENDMENT (2026-08-29): the board's OWN settle, in its OWN currency, from silver_futures_eod
# -- an observed fact needing no FX. Front-expiry latest-session read (ONE fetch; a front-month
# HISTORY would need a per-session roll this estate precomputes only in gold_futures_spreads, so the
# level renders and the history honestly does not -- self-healing via that gold lane, never here).
# R4c: this is a SYNTHESIZED price surface -> registered in config_check.SYNTHESIZED_PRICE_LEG_ALLOW
# ("silver_futures_eod": settle) in the SAME change (the adjudication R4c exists to force).
_RV_EOD_LEVEL = {
    "french_wheat_matif": ("settle", "the MATIF milling-wheat contract"),
}
# D-DA lane 2b (OWNER-RATIFIED 2026-09-01, "ship native-unit fresh levels"): each fired leg's OWN
# front-month settle in its OWN currency/unit -- an observed fact needing no conversion layer (the
# price-audit law stands: nothing here converts anything; the CROSS-unit spread stays the monthly
# benchmark's). Roster = the P5-measured silver_futures_eod coverage (8 slugs; palm has no futures
# card and stays honestly absent). Rides the reading's `derived` branch only; +1 fetch per mapped
# leg. Same R4c register entry as _RV_EOD_LEVEL ("silver_futures_eod": settle).
# DOCKET DISCHARGED (V2-3 law L8, 2026-09-04): the "palm has no futures card" clause above is now
# HISTORY -- the CME USD backfill went canonical at D9 (116,228 rows, 11 partitions, floor
# 2016-08-01) and rev 126 serves it, so the docketed row lands here off the same silver_futures_eod
# coverage every other row came from. ITS OWN CURRENCY IS USD, like every other row on this roster:
# nothing here converts anything, and the reader label is display._contract_label's own spelling.
_RV_EOD_FRESH = {
    "corn_cbot": ("settle", "the CBOT corn contract"),
    "soft_red_winter_wheat_cbot": ("settle", "the CBOT soft red winter wheat contract"),
    "hard_red_winter_wheat_kcbt": ("settle", "the KCBT hard red winter wheat contract"),
    "soybeans_cbot": ("settle", "the CBOT soybean contract"),
    "soybean_oil_cbot": ("settle", "the CBOT soybean oil contract"),
    "soybean_meal_cbot": ("settle", "the CBOT soybean meal contract"),
    "canola_ice": ("settle", "the ICE canola contract"),
    "french_wheat_matif": ("settle", "the MATIF milling-wheat contract"),
    "malaysian_crude_palm_oil_cme": ("settle", "CME palm oil"),
}
_RV_EOD_TABLE = "silver_futures_eod"


def _eu_composition_breaks() -> tuple:
    """The accession/exit marketing years, COMPUTED from EU_MEMBERSHIP -- never a second hand-kept
    list (refute-v1 D20: v1 declared a literal and asserted the derivation; the pin now sits on the
    VALUE as a regression tripwire on EU_MEMBERSHIP, not as a second source of truth)."""
    ys = {my for (my, _x) in EU_MEMBERSHIP.values()}
    ys |= {x for (_a, x) in EU_MEMBERSHIP.values() if x is not None}
    return tuple(sorted(ys))


def _composition_break(country: str, my0: int, my1: int):
    """The FIRST membership break strictly inside (my0, my1] for an EU-aggregate scope, else None.
    Non-EU scopes return None (the US has no analogue). Pure; no I/O."""
    if country not in EU_AGGREGATE_TITLES:
        return None
    for y in _eu_composition_breaks():
        if my0 < y <= my1:
            return y
    return None


def _settled_my_ceiling(slug: str, asof) -> int | None:
    """The newest marketing year that has ENDED at asof, per the LEG'S OWN MY calendar:
    _covering_my(asof, slug) - 1. Pure; reads no clock. (refute-v1 D8: with period=None/agg=series
    the vintage partition emits NO market_year band, so the series carries USDA's current
    PROJECTION MY -- a forecast that must neither ride a correlation nor ride a delta row
    undeclared.)"""
    my = _covering_my(str(asof)[:10], slug)
    return None if my is None else my - 1


def _xc_sides_ok_regional(pair_row, source: str, target: str) -> bool:
    """Fail-closed regional gate, the _xc_sides_ok sibling (refute-v1 D2). Requires:
    materiality_tier == 'material'; the two SIDE CONTRACTS are exactly {source, target} (a set
    compare -- route()'s hit-count sort can yield either order); the two side contracts are
    DISTINCT; both sides country_rule == 'regional' with a non-empty country; and the two countries
    DIFFER. Never raises."""
    try:
        from leviathan.graphrag import complex_map as xcm
        if getattr(pair_row, "materiality_tier", None) != "material":
            return False
        sides = [dict(getattr(pair_row, "side_a", None) or {}),
                 dict(getattr(pair_row, "side_b", None) or {})]
        contracts = [s.get("contract") or "" for s in sides]
        if len(set(contracts)) != 2 or set(contracts) != {source, target}:
            return False
        if not xcm.pair_is_regional(pair_row):
            return False
        countries = [s.get("country") or "" for s in sides]
        return all(countries) and countries[0] != countries[1]
    except Exception:  # noqa: BLE001
        return False


def _xc_regional_scope(pair_row, slug: str):
    """(country, scope_word) for the leg whose CONTRACT equals `slug` -- resolved through
    complex_map.side_by_contract, NEVER by side ordinal (refute-v1 D2: a positional read would stamp
    'United States' on the MATIF leg of a swapped request -- the cardinal class, invisible to every
    value check because both figures transcribe correctly). None when the slug is not a side
    contract or carries no pinned country."""
    try:
        from leviathan.graphrag import complex_map as xcm
        side = xcm.side_by_contract(pair_row, slug)
        if not side:
            return None
        country = side.get("country") or None
        if not country:
            return None
        return (country, _XC_SCOPE_WORDS.get(country, country))
    except Exception:  # noqa: BLE001
        return None


def _xc_label_regional(slug: str, scope_word: str) -> str:
    """'US wheat (all classes)' -- the ONE producer (refute-v2 E7): the aggregate word comes off
    _XC_LABEL_REGIONAL (lint-required per authored regional slug), the scope word off the pinned
    map. Never string surgery on _xc_label."""
    return f"{scope_word} {_XC_LABEL_REGIONAL.get(slug, slug.replace('_', ' '))}"


def _regional_series(qfn, slug: str, country: str, metric: str, asof) -> tuple:
    """(values, MY-int labels, unit) for ONE (slug, country, metric) -- the WHOLE reported history in
    ONE read: fetch_window(period=None, period_type='marketing_year', agg='series'). _window_kwargs
    binds a marketing_year leg as period-only (t1/t2 IGNORED), which is why a windowed MY read does
    not exist and the World path loops per-MY. `country` is passed LITERALLY -- never
    _PSD_COUNTRY_FOLD-folded: the pin IS the scope (lint step 7.4). Rows are SORTED by the `period`
    extra rather than trusting fetch order (a defensive improvement over _rv_axes, pinned)."""
    rec = fetch_window(qfn, table=_PSD_TABLE, metric=metric, commodity=slug, country=country,
                       t1=None, t2=None, asof=asof, agg="series", period=None,
                       period_type="marketing_year")
    if rec.get("status") != "ok":
        return [], [], ""
    rows = []
    unit = ""
    for r in (rec.get("rows") or []):
        try:
            my = int(str(r.get("period") or r.get("market_year") or "").strip() or "x")
        except ValueError:
            continue
        try:
            v = float(str(r.get("value")).replace(",", ""))
        except (TypeError, ValueError):
            continue
        rows.append((my, v))
        if not unit and r.get("unit"):
            unit = str(r.get("unit"))
    rows.sort(key=lambda t: t[0])
    return [v for _, v in rows], [my for my, _ in rows], unit


def _leg_regional_deltas(slug: str, spec, windows: list, series_vals: list, series_mys: list) -> dict:
    """Mirrors _leg_world_deltas' return shape EXACTLY -- {era_idx: {'d': delta, 'a': (my, val, rd),
    'b': (my, val, rd)}} -- so _xc_fork_scan consumes it unchanged. The era -> MY mapping stays
    _my_span(w, slug), byte-identical to the World path, which keeps fired['window'] parseable by
    _RV_WINDOW_RX and matchable back to its era by _my_span (the landed F1 fix). ONLY the VALUE
    lookup changes: an index into the one-shot series, never a per-MY fetch."""
    by_my = dict(zip(series_mys, series_vals))
    scale = float(spec.scale)
    out: dict = {}
    for i, w in enumerate(windows or []):
        pts = [(my, by_my[my] * scale, None) for my in _my_span(w, slug) if my in by_my]
        if len(pts) >= 2:
            a, b = pts[0], pts[-1]
            out[i] = {"d": b[1] - a[1], "a": a, "b": b}
    return out


def _fmt_reg(v: float, spec) -> str:
    """'34.2%' / '19.6 MMT' -- the value in the spec's own unit word, sep off the spec (what makes
    MMT renderable at all; the World producer's baked '%' could not say it)."""
    return f"{v:g}{spec.sep}{spec.unit}"


def _xc_regional_leg_lines(legs: list, specs: list, calls: list, base: int, asof,
                           ceiling_by_slug: dict) -> tuple:
    """FORKED from _xc_leg_lines (refute-v1 D3/D16: the World producer hardcodes country='World',
    metric=su_ratio_world and the %/pp format -- parameterizing six render points would put the
    shipped World render at risk for a convenience, so the STRING half is duplicated and the SIGN
    half is shared via _xc_fork_scan). Metric-major loop: per (metric, leg) ONE reader line + THREE
    citable rows (endpoint + baseline + delta) -- the [N] stride is 3, each line's handle the FIRST
    of its three (B4.1). Every injected row carries country=<pinned scope> and metric=<spec id>.
    `legs` = [(label, slug, country, deltas_by_metric_key)]. Returns (lines, projection_flag)."""
    n = base
    lines: list = []
    projection = False
    for spec in specs:
        for (lbl, slug, country, by_metric) in legs:
            A = by_metric.get(spec.key)
            if not A:
                continue
            (my_lo, p_lo, _r0), (my_hi, p_hi, _r1) = A["a"], A["b"]
            n += 1
            handle = n
            calls.append(_shown(_xc_call(lbl, p_hi, my_hi, asof, unit=spec.unit,
                                         metric=spec.metric_id, country=country),
                                p_hi, p_lo, A["d"]))
            n += 1
            calls.append(_xc_call(lbl, p_lo, my_lo, asof, unit=spec.unit,
                                  metric=spec.metric_id, country=country))
            n += 1
            calls.append(_xc_call(lbl, A["d"], my_hi, asof, unit=spec.delta_unit,
                                  metric=spec.metric_id, country=country))
            proj = ""
            ceil = ceiling_by_slug.get(slug)
            if ceil is not None and my_hi > ceil:
                # D8: an unsettled era MY renders its MANDATORY declared clause (or the block declines
                # projection_undeclared at the caller -- the clause is minted here so it cannot be lost)
                proj = (f" -- MY{my_hi} is USDA's current projection for a marketing year that has "
                        f"not ended, not a settled figure")
                projection = True
            lines.append(f"- [N{handle}] {lbl} {spec.word} MY{my_hi}: {_fmt_reg(p_hi, spec)} "
                         f"(vs MY{my_lo} {_fmt_reg(p_lo, spec)}, "
                         f"{A['d']:+g}{spec.sep}{spec.delta_unit} over the window){proj}"
                         + _series_tag({"commodity": lbl, "country": country, "table": _PSD_TABLE}))
    return lines, projection


_RV_VERDICT_WORD = {"aligned": "ALIGNED", "at_odds": "TENSION", "undetermined": "UNRESOLVED"}
#   trace values stay the LANDED enum {aligned, at_odds, undetermined} (refute-v2 E8: `one_sided` is
#   a PAIR-verdict value, carried on rv_regional_verdict; the per-leg values never widen the enum).


def _rv_leg_window_change(vals: list, dates: list, w_lo: str, w_hi: str):
    """The mapped leg's OWN within-era price change, computed on the series ALREADY FETCHED for its
    level and percentile. w_lo/w_hi are the fired era's OWN CALENDAR month bounds (the F1
    leg-symmetry fix, reused unchanged). The M3 COVERAGE FLOOR rides here verbatim: the era must sit
    INSIDE the price history's envelope or None -- a direction asserted over months the series never
    held is the claim, falsified. Fewer than 2 clipped points -> None. NEVER a cross-leg quantity."""
    if not vals or not dates:
        return None
    if not (dates[0][:7] <= w_lo and w_hi <= dates[-1][:7]):
        return None
    clipped = [v for v, dt in zip(vals, dates) if w_lo <= dt[:7] <= w_hi]
    if len(clipped) < 2:
        return None
    return clipped[-1] - clipped[0]


def _regional_leg_verdict(d_leg, price_change) -> str:
    """A NEW INSTRUMENT, not a reuse (refute-v1 D6). The landed verdict negates the RELATIVE
    -(dA - dB) against a SPREAD change; this negates ONE leg's own fundamental delta against THAT
    leg's own price change. Same sign discipline -- the flip happens EXACTLY once, at the named
    negation, because su_ratio is a LOOSENESS measure -- but a different quantity, pinned as its own
    instrument on both leg orders. The None tests precede _sign (refute-v1 D17: _sign raises on
    None)."""
    if price_change is None or d_leg is None:
        return "undetermined"
    f = _sign(-float(d_leg))                       # > 0 <=> this leg's own sheet TIGHTENED
    p = _sign(float(price_change))
    if f == 0 or p == 0:
        return "undetermined"
    return "aligned" if f == p else "at_odds"


def _reroute_xc_regional(pair_row, source: str, target: str, focus_windows: list, qfn, asof,
                         calls: list, base: int, sg, comove: bool = False, *,
                         open_ask: bool = False) -> tuple:
    """The REGIONAL fork: same _xc_fork_scan sign law, its own render (scoped tags, per-metric specs,
    the C20 clauses, the composition fence). Returns (block_lines, fired, decline_tag) -- the THIRD
    element is the E3 decline channel (a non-firing fork has no fired dict to stamp); the caller
    stamps it without entering the fired body. Rows extend `calls` ONLY after the fence passes.
    Never raises."""
    try:
        if not _xc_sides_ok_regional(pair_row, source, target):
            return [], None, "not_regional_pair"
        scope_a = _xc_regional_scope(pair_row, source)
        scope_b = _xc_regional_scope(pair_row, target)
        if not scope_a or not scope_b:
            return [], None, "scope_unresolved"
        (country_a, word_a), (country_b, word_b) = scope_a, scope_b
        if (source, country_a) not in _XC_REGIONAL_C20_NOTES \
                or (target, country_b) not in _XC_REGIONAL_C20_NOTES \
                or source not in _XC_LABEL_REGIONAL or target not in _XC_LABEL_REGIONAL:
            return [], None, "c20_missing"          # E4: the single most likely way this feature lies
        la = _xc_label_regional(source, word_a)
        lb = _xc_label_regional(target, word_b)
        specs = [s for s in _XC_REGIONAL_METRICS if s.scale is not None][:XC_REGIONAL_METRIC_CAP]
        if not specs:
            return [], None, "no_history"           # P4 unbanked -> su_ratio dark; nothing renders
        # -- the 4 reads (2 metrics x 2 legs), ONE fetch each; deltas + corr ride the SAME reads ----
        series: dict = {}
        fetches = 0
        for spec in specs:
            for slug, country in ((source, country_a), (target, country_b)):
                fetches += 1
                if fetches > _XC_REGIONAL_FETCH_CAP:
                    return [], None, "cap"
                metric = "su_ratio" if spec.key == "su_ratio" else spec.key
                series[(spec.key, slug)] = _regional_series(qfn, slug, country, metric, asof)
        su = specs[0]
        va, mya, _ua = series.get((su.key, source), ([], [], ""))
        vb, myb, _ub = series.get((su.key, target), ([], [], ""))
        if not va or not vb:
            return [], None, "no_history"
        shared = sorted(set(mya) & set(myb))
        if len(shared) < MIN_REGIONAL_MY_N:
            return [], None, "thin_history"
        legs = []
        for slug, country, lbl in ((source, country_a, la), (target, country_b, lb)):
            by_metric = {}
            for spec in specs:
                vals, mys, _u = series.get((spec.key, slug), ([], [], ""))
                if vals:
                    by_metric[spec.key] = _leg_regional_deltas(slug, spec, focus_windows, vals, mys)
            legs.append((lbl, slug, country, by_metric))
        da_by = legs[0][3].get(su.key) or {}
        db_by = legs[1][3].get(su.key) or {}
        div_idx, comove_idx = _xc_fork_scan(da_by, db_by)
        idx = div_idx if div_idx is not None else (comove_idx if comove else None)
        if idx is None:
            return [], None, "no_history"           # no divergent (or renderable co-move) era: honest
        era_legs = [(lbl, slug, country, {k: v[idx] for k, v in bm.items() if idx in v})
                    for (lbl, slug, country, bm) in legs]
        ceilings = {source: _settled_my_ceiling(source, asof),
                    target: _settled_my_ceiling(target, asof)}
        local: list = []
        lines, projection = _xc_regional_leg_lines(era_legs, specs, local, base, asof, ceilings)
        A, B = da_by[idx], db_by[idx]
        (mya0, pa0, _), (mya1, pa1, _) = A["a"], A["b"]
        (_myb0, pb0, _), (_myb1, pb1, _) = B["a"], B["b"]
        window = f"MY{mya0}-MY{mya1}"
        # -- the rolling co-movement row + its (non-overlapping) rank, on the PROJECTION-CLAMPED set --
        from leviathan.graphrag.numbers import stats as st
        ceil_pair = min(c for c in ceilings.values() if c is not None) if any(
            c is not None for c in ceilings.values()) else None
        clamped = 0
        cva, cmya, cvb, cmyb = va, mya, vb, myb
        if ceil_pair is not None:
            cva = [v for v, m in zip(va, mya) if m <= ceil_pair]
            cmya = [m for m in mya if m <= ceil_pair]
            cvb = [v for v, m in zip(vb, myb) if m <= ceil_pair]
            cmyb = [m for m in myb if m <= ceil_pair]
            clamped = len(shared) - len(set(cmya) & set(cmyb))
        corr = st.rolling_corr(cva, [str(m) for m in cmya], cvb, [str(m) for m in cmyb],
                               XC_REGIONAL_CORR_WINDOW, label_a=la, label_b=lb)
        n = base + len(local)
        corr_bits = []
        corr_decline = corr.get("guard") if corr.get("declined") else None
        rank_decline = None
        if not corr.get("declined"):
            c2 = round(float(corr["value"]), 2)
            n += 1
            h_c = n
            local.append(_shown(_xc_call(f"{la} vs {lb}", c2, int(corr["labels"][-1]), asof,
                                         unit="correlation", metric="su_ratio_regional_corr",
                                         country=f"{country_a} and {country_b}"), c2,
                                int(corr["window"])))
            lines.append(f"- [N{h_c}] rolling {corr['window']}-marketing-year correlation between "
                         f"the two regions' stocks-to-use, ending MY{corr['labels'][-1]}: {c2:+.2f}"
                         + _series_tag({"commodity": f"{la} vs {lb}",
                                        "country": f"{country_a} and {country_b}",
                                        "table": _PSD_TABLE}))
            corr_bits.append(f"the two regions' stocks-to-use co-move at {c2:+.2f} over the trailing "
                             f"{corr['window']}-marketing-year window [N{h_c}]")
            dis = corr.get("disjoint_series") or []
            if len(dis) >= st.MIN_PERCENTILE_N:
                pc = st.percentile(corr["value"], dis)
                if not pc.get("declined"):
                    pv = int(round(pc["value"]))
                    n += 1
                    h_r = n
                    local.append(_shown(_xc_call(f"{la} vs {lb}", pv, int(corr["labels"][-1]), asof,
                                                 unit="percentile", metric="su_ratio_regional_corr",
                                                 country=f"{country_a} and {country_b}"),
                                        pv, len(dis)))
                    lines.append(f"- [N{h_r}] where that correlation stands within its own "
                                 f"{len(dis)} NON-OVERLAPPING windows: {_rv_ordinal(pv)} percentile"
                                 + _series_tag({"commodity": f"{la} vs {lb}",
                                                "table": _PSD_TABLE}))
                    corr_bits.append(f"the {_rv_ordinal(pv)} percentile of its {len(dis)} "
                                     f"non-overlapping windows [N{h_r}]")
            else:
                rank_decline = f"disjoint_windows:{len(dis)}"   # expected below a ~64-MY shared span
        # -- composition fence (A4): a membership break inside the era window is DECLARED, never
        #    silent and never a silent drop --
        comp_break = _composition_break(country_b, mya0, mya1) or _composition_break(
            country_a, mya0, mya1)
        comp_clause = ""
        if comp_break:
            comp_clause = (f" The EU aggregate's own membership changed at MY{comp_break} inside "
                           f"this window, so part of this change is composition and not balance "
                           f"sheet.")
        frame = _xc_frame(pair_row, sg, open_ask=open_ask)
        note_a = _XC_REGIONAL_C20_NOTES[(source, country_a)]
        note_b = _XC_REGIONAL_C20_NOTES[(target, country_b)]
        marker_line = (
            f"CROSS-BOARD on stocks-to-use: {la} {pa1:g}% ({A['d']:+g}pp) vs {lb} {pb1:g}% "
            f"({B['d']:+g}pp) over {window} -- {frame}; each balance sheet is its REGION'S OWN "
            f"aggregate at the marketing-year grain, not a shared calendar and not a world total; "
            f"no cross-currency price comparison is made anywhere in this block. "
            + ("; ".join(corr_bits) + ". " if corr_bits else "")
            + f"NOTE -- not the same aggregate: {note_a}; and {note_b}.{comp_clause} "
            f"Render under '## Cross-commodity', labeled BY REGION, after any world rows.")
        lines.append(marker_line)
        if projection:
            if "not a settled figure" not in "\n".join(lines):
                return [], None, "projection_undeclared"
        if len(local) > XC_REGIONAL_MAX_ROWS_INJECTED:
            return [], None, "cap"                  # declines WHOLE -- a half-scorecard reads complete
        if _RV_REGIONAL_BANNED_RX.search("\n".join(lines)):
            return [], None, "fenced"
        calls.extend(local)
        fired = {"pair_id": getattr(pair_row, "id", None),
                 "complex": getattr(pair_row, "complex_name", None),
                 "commodityA": source, "dA": round(A["d"], 4), "su_ratio_A": round(pa1, 4),
                 "myA": mya1, "commodityB": target, "dB": round(B["d"], 4),
                 "su_ratio_B": round(pb1, 4), "myB": _myb1, "window": window,
                 "reroute_v2": True, "regional": True,
                 "scope_a": country_a, "scope_b": country_b,
                 "regional_rows": len(local), "regional_fetches": fetches,
                 "regional_my_n": len(shared), "projection_my": projection,
                 "projection_clamped": clamped,
                 "composition_break": bool(comp_break)}
        if comove_idx is not None and div_idx is None:
            fired["comove"] = True
        if corr_decline:
            fired["corr_decline"] = corr_decline
        if rank_decline:
            fired["corr_rank_decline"] = rank_decline
        return lines, fired, None
    except Exception:  # noqa: BLE001 -- fail-closed: the regional fork must never break the v1 answer
        return [], None, "error"


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
    sv = _scaled_val(rec, row)                            # the SAME float the append site binds as `shown`
    val = f"{sv:g}" if sv is not None else "?"
    unit = row.get("narrate_unit") or ""
    q = rec.get("query") or {}
    period = "current" if current else (q.get("period") or "")
    return (f"- [N{n}] {label} {q.get('commodity') or ''} {_metric_display(row)} {period} "
            f"(as-of {q.get('asof')}): {val} {unit}".rstrip() + _series_tag(q, row))


def _chain_fmt_delta(row: dict, d: float, n: int, *, label: str, q: dict | None = None) -> str:
    return (f"- [N{n}] {label} change within the anchor window in {_metric_display(row)}: "
            f"{d:+g} {row.get('narrate_unit') or ''}".rstrip() + _series_tag(q, row))


def _chain_fmt_pct(row: dict, pct: float, n: int, *, label: str, q: dict | None = None) -> str:
    return (f"- [N{n}] {label} change within the anchor window in {_metric_display(row)}: {pct:+g} %"
            + _series_tag(q, row))


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


def _chain_legs(sg, graph, kept: list, records: list, qfn, asof, near, calls: list,
                *, futures_newest_first: bool | str = False) -> tuple:
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
            return [], None, {"chain_id": focus_rows[0].get("id"), "reason": "root_not_grounded",
                              "net_reads": 0}
        selected_id = selected.get("id")
        hops = selected.get("hops") or []
        # ── per-hop resolution (sec 2.1) + the DOWNSTREAM-ONLY grain guard (sec 2.2(3), S5) ──
        resolved = []
        prev_rank = None
        for i, hop in enumerate(hops):
            res = _chain_resolve_hop(graph, focus, hop, eras, asof, root_node, is_root=(i == 0))
            if res is None:
                return [], None, {"chain_id": selected_id, "reason": "error", "hop": i, "net_reads": 0}
            identity, specs, meta = res
            rank = _GRAIN_RANK.get(meta["period_type"], 0)
            if prev_rank is not None and rank < prev_rank:         # finer than its parent: spread-MY-over-months
                return [], None, {"chain_id": selected_id, "reason": "error", "hop": i, "net_reads": 0}
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
            return [], None, {"chain_id": selected_id, "reason": "degenerate",   # cascade already serves it)
                              "net_reads": 0}
        # ── cap (sec 3.4): reuse-before-fetch, CHAIN_CAP NET, cap-ATOMIC (never a truncated chain) ──
        reuse: dict = {}
        for rec in records or []:
            reuse.setdefault(_chain_rec_key(rec), rec)             # a reused spec costs 0 against CHAIN_CAP
        all_specs = [s for d in distinct for s in d["specs"]]
        need = [s for s in all_specs if _chain_spec_key(s) not in reuse]
        if len(need) > CHAIN_CAP:
            return [], None, {"chain_id": selected_id, "reason": "cap", "net": len(need),
                              "net_reads": 0}                      # declined BEFORE fetching; `net` = the ask
        # ── fetch the misses in ONE pool wave (the R5 shape); reuse consumes prior records ──
        fetched: dict = {}
        if need:
            from concurrent.futures import ThreadPoolExecutor

            width = _cascade_width(len(need))
            with ThreadPoolExecutor(max_workers=width) as pool:
                for s, rec in zip(need, pool.map(
                        lambda sp: _run_one(qfn, sp, futures_newest_first=futures_newest_first), need)):
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
                                  "hop": d["idxs"][0], "node": " / ".join(d["names"]),
                                  "net_reads": len(need)}          # POST-fetch decline: the wave was paid
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
                    calls.append(_shown(_prescaled(r, row, n), _scaled_val(r, row)))
                    lines.append(_chain_fmt_line(r, row, n, label=label))
                dlt = _era_delta(oks, row)                         # WITHIN-hop delta ONLY (no cross-hop math, 4.1)
                if dlt is not None:
                    delta_val = dlt
                    n += 1
                    calls.append(_shown(_delta_call(oks[-1], row, dlt, n, kind="delta"), dlt))
                    lines.append(_chain_fmt_delta(row, dlt, n, label=label, q=oks[-1].get("query")))
                    pct = _pct_change(oks, row)
                    if pct is not None:
                        n += 1
                        calls.append(_shown(_delta_call(oks[-1], row, pct, n, kind="pct"), pct))
                        lines.append(_chain_fmt_pct(row, pct, n, label=label, q=oks[-1].get("query")))
            if cur is not None and cur.get("status") == "ok" and (cur.get("rows") or []):
                statuses["current"] = "ok"
                n += 1
                calls.append(_shown(_prescaled(cur, row, n), _scaled_val(cur, row)))
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
                 "hops": hop_trace, "n_rows": len(calls) - base,    # honest post-fence count (== n-base when clean)
                 "net_reads": len(need)}                            # A2/v3 STEP 2(2): the fetch wave's real cost
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
     "link_comove",                                                               # + the ONE horizontal reason
     # D-XT a5.4 (2026-08-29): on an OPEN ask the PAIR wins and the transmission composer is suppressed
     # BEFORE selection (the guard sits above _xmit_select, which picks by FILE ORDER -- the alphabet
     # defect in another costume). A reasoned decline, never a silent absence, so the T2b ledger reads it.
     "open_ask_pair_precedence"})


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


def _xmit_stamp_reads(payload: dict, mqfn) -> dict:
    """A2 (walk charter): stamp the memo's distinct round-trip count on a post-prewarm payload.
    A None mqfn (the default-backend path -- `_xmit_memo_qfn(None)` passes through) leaves the key
    ABSENT: an unmeasurable spend must read as UNKNOWN downstream (the turn ceiling declines on it),
    never as a number, and raising here would convert a fired chain into an error decline."""
    if mqfn is not None and payload is not None:
        payload["net_reads"] = len(mqfn.memo)
    return payload


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

    width = _cascade_width(len(keys))
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
    volunteered on the analyst's own initiative.

    D-XT N2 (2026-08-29): a DEFERRED request is inert here. Round 3 claimed structural inertness from
    omitting source_slug; that was FALSE -- this function falls back to the walk's focus seed, precisely
    the contract the deferred request is waiting to be bound to, so the deferral would have routed itself
    down trigger 2 with the composer's file-order selection. One line closes it; the a5.4 precedence
    guard stops being the only belt."""
    if (xc_request or {}).get("defer"):
        return None
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
        # D-XT a5.4: on an OPEN ask the PAIR wins -- suppress the composer BEFORE selection (which picks
        # by FILE ORDER, the alphabet defect in another costume; and _xmit_focus carries zero information
        # about an open ask). chain_id None deliberately (N10): no chain was selected, but the T2b ledger
        # reads a uniform decline shape. _xmit_fired stays False, so _run_xc still runs. NOTE (P22): both
        # measurement arms pin transmission OFF, so this guard's only validation is its unit pin.
        if (xc_request or {}).get("trigger") in _OPEN_TRIGGERS:
            return [], None, {"chain_id": None, "reason": "open_ask_pair_precedence",
                              "trigger": xc_request.get("trigger"), "net_reads": 0}
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
            return [], None, {"chain_id": selected_id, "reason": "cap", "yielded_to": "quantify_chain",
                              "net_reads": 0}
        if _xmit_degenerate(links):
            return [], None, {"chain_id": selected_id, "reason": "degenerate", "net_reads": 0}
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
            return [], None, {"chain_id": selected_id, "reason": "root_not_grounded", "net_reads": 0}
        # ── cap: priced BEFORE any fetch, ATOMIC (3.3 control-2) ──
        keys = _xmit_su_keys(links, windows)
        net = 2 * len(keys)                                       # 2 PSD components per World su_ratio synthesis
        if net > TRANSMISSION_CAP:
            return [], None, {"chain_id": selected_id, "reason": "cap", "net": net,
                              "net_reads": 0}                     # declined BEFORE the prewarm; `net` = the ask
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
            # D-XT F2 belt-and-braces: the a5.4 guard makes an open ask unreachable here, but link 2 of
            # xmit_palm_soyoil_meal is soymeal_soyoil_crush (complex soy_crush) -- the frame guard is
            # threaded anyway (omit-when-off, N12's stub discipline).
            _oa = {"open_ask": True} if (xc_request or {}).get("trigger") in _OPEN_TRIGGERS else {}
            blk, fired = _reroute_xc(prow, src, tgt, windows, mqfn, asof, calls, len(calls), sg, comove,
                                     **_oa)
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
                return [], None, _xmit_stamp_reads(               # POST-prewarm: the memo's distinct round-trips
                    {"chain_id": selected_id, "reason": reason, "link": i}, mqfn)
            link_trace.append(entry)
            stopped_at, stop_reason = i, reason
            break
        n_rendered = sum(1 for e in link_trace if e.get("rendered") in ("divergence", "comove"))
        if not n_rendered:
            calls[base:] = []                                     # defensive: nothing rendered -> no orphans
            return [], None, _xmit_stamp_reads(
                {"chain_id": selected_id, "reason": "degenerate"}, mqfn)
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
            return [], None, _xmit_stamp_reads(
                {"chain_id": selected_id, "reason": "error", "detail": "register_fence"}, mqfn)
        fired_trace = _xmit_stamp_reads(                          # A2/v3 STEP 2(1): `.memo` is the honest
            {"chain_id": selected_id, "focus": focus, "window": window_lbl,   # round-trip counter
             "links": link_trace, "n_rows": len(calls) - base}, mqfn)
        if stopped_at is not None:
            fired_trace["stopped_at"], fired_trace["stop_reason"] = stopped_at, stop_reason
        return lines, fired_trace, None
    except Exception as e:  # noqa: BLE001 -- fail-closed: never break the v1 answer
        return [], None, ({"chain_id": selected_id, "reason": "error", "detail": type(e).__name__[:40]}
                          if selected_id else None)


# == OUTCOMES JOIN -- THE TWO SERVING CONSUMERS (J4 episode magnitude, J6 COT outcome pairing) =======
#
# Both legs read the SAME computation -- `numbers.outcomes`, which owns the survivor basis, the PIT
# clamp and the decline vocabulary. Nothing here re-derives a move, a basis or a boundary; this file
# owns only the SEAM (which windows to ask about, how many reads that is worth, and what the rendered
# line says). That split is the F-L discipline `futures_roll` exists to enforce, one level up again.
#
# WHY J4 COMPUTES AT QUERY TIME AND J5's TABLE DOES NOT (plan item 40b / 98(d)). Episode windows are
# derived from the timeline artifact, and the artifact is REBUILT -- so a stored episode-span row is
# stale the moment it is, and a deck pin naming a literal span goes red for the right reason at the
# wrong time. `gold_futures_outcomes` therefore stores NO episode-derived row, and this leg asks the
# tape live. The 5,000-row `agg='series'` cap does not bind here because the deep read is
# DELIVERY-MONTH SCOPED (~1 row/session); an unscoped curve read is 3.7-12.9 rows/session (max 19 on
# soymeal) and WOULD truncate silently on a multi-year span -- so the reads below are scoped, capped,
# and a saturated read DECLINES rather than measuring across a hole.
_TAPE_TABLE = "silver_futures_eod"
_TAPE_METRIC = "settle"

# THE PER-TURN BUDGET, and every number in it is a bound rather than a preference.
EPISODE_OUTCOME_MAX_WINDOWS = 3      # priced windows ATTEMPTED per turn (2 reads each, plus the lazy
#                                      tape-edge re-ask below that sets reads=3 on a PENDING span -- so
#                                      <= 9 reads, not 6; the old "<= 6" was the source of the
#                                      walk-ceiling double count (V2-5, 2026-09-04).
#                                      timeline.MAX_PER_NODE is 4 and a walk grounds several nodes, so
#                                      an unbudgeted leg would fan tens of reads onto the serve path.
EPISODE_OUTCOME_CANDIDATES = 3       # delivery months carried into the deep read. Chosen as the nearest
#                                      eligible expiries whose month is at or after the span end, which
#                                      is where a surviving contract must live (a contract's last print
#                                      lands only 7-20 days into its own delivery month).
EPISODE_TAPE_ROW_CAP = 2500          # per read. Saturation DECLINES: `agg='series'` truncates the
#                                      NEWEST rows, i.e. exactly the endpoint, so a full read is the
#                                      only honest one (J3b).
EPISODE_SPAN_MAX_DAYS = 1460         # 4 years. Beyond the measured maximum forward tenor (3.96y on
#                                      GLBX, 0.96y on CZCE) NO single contract can span the window, so
#                                      the decline is arithmetic and costs zero reads.

# The decline reasons this SEAM owns. Everything else comes back from `outcomes` itself, so the two
# vocabularies never overlap: a reason here means "the seam would not ask", a reason there means "the
# join was asked and answered no".
EP_DECLINE_UNRESOLVED_NODE = "unresolved_node"       # a driver node has no price series at all
EP_DECLINE_SPAN_TOO_LONG = "span_exceeds_contract_life"
EP_DECLINE_NO_TAPE = "no_tape_rows"
EP_DECLINE_READ_TRUNCATED = "read_truncated"
EP_DECLINE_BUDGET = "budget_exhausted"


def _iso_days(iso) -> int:
    """An ISO date as a day ordinal -- span arithmetic without a datetime import at every call site."""
    import datetime as _dt
    return _dt.date.fromisoformat(str(iso)[:10]).toordinal()


def _iso_shift(iso, days: int) -> str:
    import datetime as _dt
    return (_dt.date.fromisoformat(str(iso)[:10]) + _dt.timedelta(days=int(days))).isoformat()


def _episode_slug(node) -> str | None:
    """An episode NODE -> a tape slug, or None. RESOLVE-OR-DECLINE, never a guess (plan item 68).

    Episode nodes are graph names -- `arabica_coffee`, `corn`, `cotton`, `drivers/african_swine_fever`
    -- and only some are tape slugs. `futures_eod_contracts.coverage_start_for` RAISES on an unmapped
    slug and never returns a permissive default, so a driver node must be turned away HERE, with the
    absence phrase the episodes persona already specifies, rather than reaching the join as an error.

    Order: an exact contract slug wins, then the curated bare-name table (`complex_map`, which is where
    `corn -> corn_cbot` is already decided once, including the ambiguous names it deliberately refuses).
    The loaded set handed to that resolver is the CONTRACT MAP itself, so this never loads the causal
    graph and never resolves to a name the tape has no record for."""
    n = str(node or "").strip().lower().split("/")[-1]
    if not n:
        return None
    try:
        from leviathan.silver import futures_eod_contracts as FC
        if n in FC.CONTRACT_MAP:
            return n
        from leviathan.graphrag import complex_map as cxm
        got = cxm.resolve_bare_commodity(n, loaded=frozenset(FC.CONTRACT_MAP))
        return got if got in FC.CONTRACT_MAP else None
    except Exception:  # noqa: BLE001 -- an unresolvable node is a DECLINE, never an exception
        return None


def _tape_read(qfn, *, slug: str, t1: str, t2: str, asof, contract_months=None,
               futures_newest_first: bool | str = False) -> tuple:
    """ONE bounded `silver_futures_eod` read -> `(rows, saturated)`. NEVER raises.

    `contract_months` compiles to the card's delivery-month IN(...) filter, which is what keeps the deep
    read at ~1 row/session/expiry. `saturated` is True when the read came back at the row cap: the
    compile is `ORDER BY <chronological ASC> ... LIMIT n`, so a truncated read loses the NEWEST sessions
    -- the endpoint half of every move -- and the caller must decline rather than measure.

    `futures_newest_first` is the S1 canary (D-FR-10), threaded from `answer._futures_newest_first_on()`
    down quantify -> _episode_leg_or_nothing -> _episode_outcome_legs -> here. THIS IS THE ONE READ IN
    THIS FILE THAT IS UNCONDITIONALLY FUTURES: `_TAPE_TABLE` is silver_futures_eod, `agg='series'`, so
    `_newest_first_applies` is True the moment the kwarg is True and the truncation direction above
    INVERTS -- a saturated read then loses the OLDEST sessions instead. `saturated` is unchanged as a
    decline either way (Q.run re-sorts the rows back to ascending before the caller sees them, so the
    frame builder and the `>= EPISODE_TAPE_ROW_CAP` compare are both flag-agnostic), which is why the
    canary can flip here without moving what a truncated window is allowed to claim."""
    try:
        spec = Q.NumberQuery(table=_TAPE_TABLE, metric=_TAPE_METRIC, asof=asof, commodity=str(slug),
                             country=None, agg="series", period_start=t1, period_end=t2,
                             limit=EPISODE_TAPE_ROW_CAP,
                             contract_month=(",".join(contract_months) if contract_months else None))
        rows = Q.run(spec, query_fn=qfn, futures_newest_first=futures_newest_first) or []
    except Exception:  # noqa: BLE001 -- a bad/slow lookup must NEVER kill the reasoning turn (R6)
        return [], False
    return rows, len(rows) >= EPISODE_TAPE_ROW_CAP


def _tape_frame(slug: str, *row_sets):
    """The fetched rows as the frame `numbers.outcomes` consumes: `leviathan_slug, trade_date,
    contract_month, settle, unit, currency, settle_kind`.

    The serving alias is `knowledge_date` (physically `trade_date`, DP-5-normalized by `query._sel_date`)
    -- code written against `data_date`, `period` or `date` reads None here and would measure nothing
    while looking like it measured something. De-duplicated on the natural key because the two reads
    OVERLAP by construction (both cover the anchor window)."""
    import pandas as pd

    cols = ["leviathan_slug", "trade_date", "contract_month", "settle", "unit", "currency",
            "settle_kind"]
    recs = []
    for rows in row_sets:
        for r in rows or []:
            kd = (r or {}).get("knowledge_date")
            if not kd:
                continue
            cm = (r or {}).get("contract_month")
            recs.append({"leviathan_slug": str(slug), "trade_date": str(kd)[:10],
                         "contract_month": (None if cm in (None, "") else str(cm)),
                         "settle": (r or {}).get("value"), "unit": (r or {}).get("unit"),
                         "currency": (r or {}).get("currency"),
                         "settle_kind": (r or {}).get("settle_kind")})
    if not recs:
        return pd.DataFrame(columns=cols)
    frame = pd.DataFrame(recs, columns=cols)
    return frame.drop_duplicates(subset=["leviathan_slug", "trade_date", "contract_month"],
                                 keep="last").reset_index(drop=True)


def _episode_candidates(rows: list, span_end, *, floor_months: int = 0) -> list:
    """The delivery months the deep read is scoped to: the nearest expiries at or after the span end.

    A contract's last print lands 7-20 days into its OWN delivery month, so a contract that survives
    `t2 + survive_days` has a delivery month at or after `t2`'s. Taking the nearest few of those, rather
    than the whole curve, is what keeps the deep read inside the row cap on a long span.

    `floor_months` is the slug's `futures_roll.FORWARD_MONTH_FLOOR` (0 for all but the averaging
    boards) and it SHIFTS the window rather than narrowing it: without the shift a floored slug's
    three candidates would be [X, X+1, X+2] of which the selector can only ever take X+floor and up,
    so the usable margin would SHRINK WITH THE FLOOR (two months at the shipped floor of 1, one at 2,
    none at 3) -- and a single missing settlement row would then decline the window as
    `no_spanning_contract` on a board that priced fine. Shifting keeps the margin at three whatever
    the floor is. floor 0 reproduces `span_end[:7]` byte for byte.

    THE COST, STATED: if all of them fail the survival test while a FARTHER expiry would have passed,
    this window declines where the tape held an answer. Option D selects the NEAREST surviving contract,
    so a farther one can never change a window that DOES resolve -- the bound only ever costs coverage,
    never correctness, and the decline is visible in the trace."""
    k = int(str(span_end)[5:7]) - 1 + int(floor_months)
    want = f"{int(str(span_end)[:4]) + k // 12:04d}-{k % 12 + 1:02d}"
    months = sorted({str((r or {}).get("contract_month"))
                     for r in rows or [] if (r or {}).get("contract_month")})
    return [m for m in months if m >= want][:EPISODE_OUTCOME_CANDIDATES]


def _episode_outcome_call(slug: str, res: dict, span: str, asof) -> dict:
    """The synthetic call-record the [N] handle indexes -- a real row value, so the figure is citable and
    value-checkable by the all-numbers guard exactly like every other engine row.

    `query.period` is the MONTH-token span the model was shown (the label eval matches on), never the
    day-grain window (which is what was MEASURED and which the trace carries). `contract_month` on the
    query is what raises the fourth `_series_tag` segment. `_provenance` carries the ENDPOINT date under
    the `date` guard-column key so the pinned-asof leakage backtest has a day-grained stamp to read
    instead of the bare `year` a futures row would otherwise carry -- and that stamp is now actually
    READ: `eval._pit_clean` takes the first present of
    `release_date | knowledge_date | data_date | week_ending_date | date` (D-OJ-7(b)), where it
    previously read `release_date` alone and was therefore a no-op on every non-vintage card."""
    end = res.get("endpoint_date")
    row = {"value": round(float(res.get("move_pct")), 4), "unit": "%",
           "knowledge_date": end, "contract_month": res.get("contract_month_used"),
           "settle_kind": res.get("settle_kind"), "currency": res.get("currency")}
    if end:
        row["_provenance"] = {"date": end}
    return {"query": {"table": _TAPE_TABLE, "metric": "settle_change_pct", "commodity": slug,
                      "country": None, "period": span, "asof": asof,
                      "contract_month": res.get("contract_month_used")},
            "rows": [row], "status": "ok"}


def _episode_outcome_line(n: int, slug: str, res: dict, span: str, asof) -> str:
    """The injected line. ONE figure, on ONE physical line, with its handle and its scope tag.

    It states a CHANGE ACROSS THE WINDOW on ONE named contract and nothing else -- no direction word, no
    cause, no adjective. The episode bullet the model writes pairs it with a receipt clause, and the
    persona paragraph forbids joining the two with a causal verb; a line that already implied the link
    would make that instruction unenforceable."""
    pct = round(float(res.get("move_pct")), 4)
    q = {"commodity": slug, "country": None, "contract_month": res.get("contract_month_used"),
         "table": _TAPE_TABLE}
    return (f"- [N{n}] {slug} settle change across the episode window {span} "
            f"(one delivery month held at both ends, as-of {asof}): {pct:+g} %" + _series_tag(q))


def _episode_outcome_legs(sg, qfn, asof, calls: list, base: int, *,
                          futures_newest_first: bool | str = False) -> tuple:
    """J4 -- price the injected episode windows. Returns `(lines, trace)`; NEVER raises.

    `futures_newest_first` is the S1 canary, threaded from `answer._futures_newest_first_on()` and passed
    to ALL THREE `_tape_read` calls below -- the curve read, the deep read and the LAZY edge read. All
    three or none: the edge read exists to re-measure the slug's tape edge with the SAME shape the deep
    read used, so a flag that reached two of the three would compare a newest-first frame against an
    oldest-first edge and could flip a PENDING verdict on ordering alone.

    THE WINDOWS ARE READ LIVE, from `sg.trace['episodes_injected']` as `_l2_blocks` stamped it this
    turn. Nothing is cached and no span is baked anywhere: the artifact-wave interlock is that episode
    windows MOVE when the timeline artifact is rebuilt, so a leg holding its own copy of a window would
    price a window the model was never shown. The MATCHING label is the `[:7]` month token (what
    `eval._line_targets` compares); the MEASURED window is the DAY-GRAIN pair beside it (D-OJ-16) --
    expanding the month token to month-end would price up to 30 days past the as-of.

    EVERY DECLINE IS RECORDED, and most cost no read at all: an unresolved node, a span longer than any
    contract lives, a window below the per-slug coverage floor, a window whose end is inside the
    survival margin. That is the point -- `answer._SYSTEM_EPISODES` calls the absence the NORMAL case,
    so a leg that never declined would be a leg that fabricated.

    THE PER-SLUG HALF OF THE CLAMP IS MEASURED FROM THE FETCHED FRAME, and that is conservative on
    purpose. The deep read runs to `t2 + survive_days + lookback`, so the frame's own max trade_date
    stands in for the slug's tape edge: a slug whose tape genuinely stops inside the survival margin
    yields a PENDING verdict, which is the correct per-slug answer (a global edge would push the 15
    Databento slugs, which end 2026-07-27, onto four sessions the 7 free legs have and they do not).
    The failure direction is a FALSE pending, and it needs a tape gap wider than the 14-day read tail --
    beyond the measured maximum gap of 11 days (CZCE, Chinese New Year / Golden Week)."""
    from leviathan.graphrag.numbers import outcomes as OC
    from leviathan.silver import futures_roll as FR

    lines: list = []
    trace: list = []
    try:
        recs = list((getattr(sg, "trace", None) or {}).get("episodes_injected") or [])
    except Exception:  # noqa: BLE001 -- a traceless sg simply has no episodes to price
        return [], []
    if not recs or not asof:
        return [], []
    empty = _tape_frame("", [])
    budget = EPISODE_OUTCOME_MAX_WINDOWS
    n = base
    for rec in recs:
        node = str((rec or {}).get("node") or "")
        slug = _episode_slug(node)
        for w in ((rec or {}).get("windows") or []):
            span = str((w or {}).get("span") or "")
            t1, t2 = str((w or {}).get("start") or ""), str((w or {}).get("end") or "")
            entry = {"node": node, "slug": slug, "span": span, "start": t1, "end": t2,
                     "status": None, "reason": None,
                     "reads": 0}                                  # A2/v3 STEP 2(5): READ, never inferred --
            #                                                       every entry minted with 0, set at the
            #                                                       actual read sites below (a reason->cost
            #                                                       map is what K7's wording forbids)
            try:
                span_days = _iso_days(t2) - _iso_days(t1)
            except (TypeError, ValueError):
                # A window with no readable day grain is not a window. RECORDED rather than skipped:
                # this leg's whole discipline is that an absence has a reason, and a silently dropped
                # window is indistinguishable from one that was measured and came back empty.
                entry.update(status="declined", reason="unparseable_window")
                trace.append(entry)
                continue
            if slug is None:
                entry.update(status="declined", reason=EP_DECLINE_UNRESOLVED_NODE)
                trace.append(entry)
                continue
            if span_days > EPISODE_SPAN_MAX_DAYS:
                entry.update(status="declined", reason=EP_DECLINE_SPAN_TOO_LONG)
                trace.append(entry)
                continue
            # THE DRY RUN. `span_outcome` over an EMPTY frame answers every question that does not need
            # the tape -- inversion, the per-contract coverage floor, and the as-of half of the clamp --
            # and it answers them through the SAME engine, so this pre-check can never disagree with the
            # real one. Only a window that gets past it is worth two reads.
            dry = OC.span_outcome(empty, slug=slug, span_start=t1, span_end=t2, asof=asof,
                                  event_key=node, tape_edge=None)
            dry_status = str(dry.get("status") or "")
            dry_reason = dry.get("decline_reason")
            if dry_status == OC.STATUS_PENDING:
                entry.update(status="pending", reason="horizon_open",
                             readable_on=_iso_shift(t2, OC.SURVIVE_DAYS))
                trace.append(entry)
                continue
            if dry_reason and dry_reason != OC.DECLINE_NO_ANCHOR_SESSION:
                entry.update(status="declined", reason=dry_reason)
                trace.append(entry)
                continue
            if budget <= 0:
                entry.update(status="declined", reason=EP_DECLINE_BUDGET)
                trace.append(entry)
                continue
            budget -= 1
            lo = _iso_shift(t1, -OC.OUTCOME_LOOKBACK_DAYS)
            hi = _iso_shift(t2, OC.SURVIVE_DAYS + OC.OUTCOME_LOOKBACK_DAYS)
            curve, sat_a = _tape_read(qfn, slug=slug, t1=lo, t2=t1, asof=asof,
                                      futures_newest_first=futures_newest_first)
            months = _episode_candidates(curve, t2, floor_months=FR.forward_month_floor(slug))
            deep, sat_b = _tape_read(qfn, slug=slug, t1=lo, t2=hi, asof=asof,
                                     contract_months=months or None,
                                     futures_newest_first=futures_newest_first)
            entry["reads"] = 2                                    # curve + deep, both paid by here
            if sat_a or sat_b:
                entry.update(status="declined", reason=EP_DECLINE_READ_TRUNCATED)
                trace.append(entry)
                continue
            tape = _tape_frame(slug, curve, deep)
            if not len(tape):
                entry.update(status="declined", reason=EP_DECLINE_NO_TAPE)
                trace.append(entry)
                continue
            res = OC.span_outcome(tape, slug=slug, span_start=t1, span_end=t2, asof=asof,
                                  event_key=node)
            status = str(res.get("status") or "")
            if status == OC.STATUS_PENDING:
                # THE EDGE MEASURED FROM THIS FRAME IS DELIVERY-MONTH-SCOPED, and that conflates two
                # different facts. The dry run above already cleared the AS-OF half of the clamp
                # (`t2 + survive_days <= asof - lag`), so a PENDING verdict here can come from ONE place
                # only: the per-slug tape edge, which `tape_edges` measured over rows restricted to the
                # <=3 candidate delivery months. If every candidate's last print falls before
                # `t2 + survive_days` while the SLUG's tape runs on, the honest answer is
                # `no_spanning_contract` -- a COVERAGE fact -- and "pending" states a TIMING one
                # instead. Same conflation class as the guard inversion, one layer up.
                # So measure the slug's real edge and ask again. The read is UNSCOPED but tiny
                # (`[t2, hi]` is survive_days + lookback = 19 days, ~3.7-12.9 rows/session, an order
                # under the cap) and it is LAZY -- it fires only in the ambiguous branch, which needs
                # every candidate month to have stopped printing. A saturated or empty edge read leaves
                # the conservative PENDING verdict exactly as it was.
                edge_rows, sat_c = _tape_read(qfn, slug=slug, t1=t2, t2=hi, asof=asof,
                                              futures_newest_first=futures_newest_first)
                entry["reads"] = 3                                # + the lazy edge re-ask
                edge_frame = _tape_frame(slug, edge_rows)
                edge = (OC.tape_edges(edge_frame) or {}).get(str(slug)) if len(edge_frame) else None
                entry["slug_tape_edge"] = str(edge) if edge else None
                if edge is not None and not sat_c:
                    res = OC.span_outcome(tape, slug=slug, span_start=t1, span_end=t2, asof=asof,
                                          event_key=node, tape_edge=edge)
                    status = str(res.get("status") or "")
            if status != OC.STATUS_CLOSED or res.get("move_pct") is None:
                entry.update(status=("pending" if status == OC.STATUS_PENDING else "declined"),
                             reason=res.get("decline_reason") or status or "no_move")
                trace.append(entry)
                continue
            n += 1
            pct = round(float(res["move_pct"]), 4)
            calls.append(_shown(_episode_outcome_call(slug, res, span, asof), pct))
            lines.append(_episode_outcome_line(n, slug, res, span, asof))
            entry.update(status="closed", reason=None, move_pct=pct,
                         contract_month=res.get("contract_month_used"), basis=res.get("basis"),
                         anchor_date=res.get("anchor_date"), endpoint_date=res.get("endpoint_date"),
                         realized_sessions=res.get("realized_sessions"), handle=f"N{n}")
            trace.append(entry)
    return lines, trace


# ══ CASCADE EPISODE WALK (charter v4: amendments A1-A6 + both refute adjudications) ═════════════════
#
# WHAT IT IS. The graph's own consequence render: on a root-focused turn, price the root board AND
# the boards the graph DECLARES it cascades into over the SAME dated driver-event firing window,
# then read the declared sign against the two observed moves (stats.sign_agreement -- a WORD, never
# a number). A6: the firing windows are the root TREE'S driver-slice episodes, read from the turn's
# own `episodes_injected` -- the interlock: never a window the model was not shown. First order is
# the modal render (owner Q2); one firing renders, labeled (owner Q3 -- frequency floors deny the
# tail). Every absence is DECLARED with a counted reason; the writer transcribes, never derives.
#
# WHAT IT NEVER DOES: no pooled rung, no tally, no ratio, no threshold word, no lag glyph, no
# forward vocabulary; the relation token is ORIENTATION-FREE (the directional claim rides the SIGN
# and the parent/child order of the two cells, never the token); firing selection reads RECENCY
# only, never an outcome (MAJOR-5).
CW_READS_PER_CELL = 3       # curve + deep + the reserved lazy tape-edge re-ask (J4's own shape)
CW_MAX_FIRINGS = 2          # depth-in-time bound (taken only when exactly ONE child is admissible)
CW_MAX_CHILDREN = 3         # breadth bound; every un-priced admissible child is NAMED (K2)
CW_CAP = 12                 # 1 root + 3 children at ONE firing = 4 cells x 3 reads = 12; or
#                             (1 root + 1 child) x 2 firings x 3 = 12. BREADTH IS DEFAULT; the
#                             deep-vs-wide rule is deterministic and outcome-independent (below).
CW_TURN_CEILING = 60        # against the MEASURED turn spend (_cw_turn_spent) -- the bound is
#                             a RUNAWAY TRIPWIRE, never a ration (owner doctrine: quality beats
#                             latency, a budget must never bind on a legitimate shape).
#                             ARITHMETIC, CORRECTED (V2-5, 2026-09-04): the round-3 refute's "~44"
#                             ALREADY CONTAINED the walk's own CW_CAP=12, so "44 + 12 = 56 < 60"
#                             double-counted the walk. The ENUMERATED pre-walk worst is
#                             CW_PREWALK_MEASURED_WORST = 65 (its six terms are listed there); the
#                             MEASURED worst is 25, over the five reached turns of the 2026-09-02
#                             arm (13 / 14 / 19 / 25 / 25), so 25 + CW_CAP 12 = 37 of 60. THREE of
#                             the six terms are config-driven, so NO identity is pinned over 65 --
#                             config_check clause (x) recomputes it at call time and WARNs.
#                             THE COUNTER DOCTRINE this ceiling rides on: a producer's read count is
#                             only exactly as good as the landed counters, which is why an unmeasured
#                             fired producer declines the leg (never read as zero). SCOPE (review
#                             D3): the ceiling binds the PRE-WALK producers; J6 runs AFTER the
#                             walk and spends up to COT_OUTCOME_MAX_ROWS closed reads plus one
#                             read per declining horizon OUTSIDE this bound -- its per-entry
#                             `reads` counters make that spend measurable post-hoc (K7's arm
#                             clause reads them), and bounding J6's own fan is J6's docket.
CW_SPAN_MIN_DAYS = 45       # r2-calibrated (cw_probe_fence_r2_20260901): excludes the 22-day n=2
#                             microstructure window class; keeps the measured real events (62/67d).
CW_SPAN_MAX_DAYS = 270      # r2-CERTIFIED: every 242-267d selected window closed cleanly; the
#                             measured failures start at 563d. The single-contract basis's real
#                             reach -- NOT J4's 1460d contract-life bound; each keeps its own name.

# -- V2-5 DEEP REGIME: a SECOND set of constants, none of it read unless walk_request carries `deep`
#    (V2-5's own key) or `xccy` (V2-3's, which lifts children on the SAME seam). The regime is
#    selected ONCE at `deep_on` inside the leg; every belt then reads a LOCAL, never a global, so a
#    flag-off turn evaluates the same comparisons on the same numbers it does today.
CW_DEEP_MAX_CHILDREN = 6      # the ENGINE ladder's measured max out-degree today is 4 (corn_cbot);
#                               6 is the max the ladder reaches with V2-3's cross-currency gate at
#                               _cw_admissible_children lifted -- corn_cbot gains french_wheat_matif
#                               and south_african_white_maize_jse (v25_v4_remeasure_20260903.json).
#                               config_check clause (ix) calls the SHIPPED ladder, so it tracks the
#                               engine and ERRORS above this number.
CW_DEEP_CAP = 27              # = (1 root + 6 children + 1 grand + 1 great) x CW_READS_PER_CELL.
#                               Sized on the UNION of both branches even though the shipped switch
#                               makes breadth and depth mutually exclusive, PRECISELY so the cap can
#                               never bind on a legitimate shape -- hence NO trim ladder anywhere in
#                               this design. Worst shape the shipped graph reaches: 15 reads
#                               (corn_cbot, five cells, every child paid), 12 under the cap.
CW_DEEP_MAX_ORDER = 3         # the shipped graph's TERMINAL depth, MEASURED: palm has no
#                               node-distinct fourth hop (v25_ladder_20260903_palm.json). IT BINDS
#                               (build-review minor): the leg makes `cw_order_max - 1` next-hop
#                               calls in a LOOP over _CW_HOP_LEVELS -- one off (order max 2), two
#                               under deep -- so this is the depth bound itself, never a stamped
#                               literal beside two hand-written calls. Raising it past
#                               1 + len(_CW_HOP_LEVELS) needs a fourth ledger level and is pinned.
CW_FREE_ALLOWANCE = 2         # THE BELT'S TRUE TEST, stated as the belt spells it: the runtime width
#                               belt bounds TOTAL rendered width at `cw_children + this` (8 on the
#                               shipped constants) and declines the excess by name -- it does NOT
#                               count the free riders separately, so three ZERO-READ (pre_coverage)
#                               children can ride against an allowance of 2 whenever the paid budget
#                               is under-spent (build-refute minor C1, MEASURED: 5 priced + 3 free =
#                               8 rendered, belt silent). The allowance is HEADROOM ON THE TOTAL.
#                               The belt is a tripwire against UNLINTED curation: configs/graphrag is
#                               gitignored and rides the image tar, so a sixth child can reach a
#                               serving image the lint never ran against.
CW_PREWALK_MEASURED_WORST = 65  # the six pre-walk terms ENUMERATED: CASCADE_CAP 12 + CHAIN_CAP 12 +
#                               TRANSMISSION_CAP 18 + the price leg's 2 + J4's 9
#                               (EPISODE_OUTCOME_MAX_WINDOWS 3 x the 3-read lazy tape-edge re-ask) +
#                               the standalone xc fork's 12, which is a CALLS DELTA (the
#                               `xc_trace["net_reads"]` assignment) and not a fetch cap. THREE terms
#                               are config-driven, so NO identity is pinned over this number;
#                               config_check clause (x) recomputes and WARNs. MEASURED worst: 25.
CW_DEEP_TURN_CEILING = 80     # = 44 (the pre-walk allowance the shipped test pin already carries)
#                               + CW_DEEP_CAP 27 + CW_CONTEXT_CAP 2 + a 7-read FX allowance for
#                               V2-3 (one FX read per non-root cell on the 8-cell union shape leaves
#                               7 covering the 7 non-root cells exactly). A LITERAL WITH A MEASURED
#                               NOTE, never a derivation -- and it BINDS if the enumerated 65 ever
#                               materialises (65 + 27 + 2 = 94 > 80): fail-closed, counted as
#                               turn_budget_spent, never silent. It bounds the board plan AND, since
#                               the V2-3 fix pass, the RIDER SLACK: `_cw_slack` reads the regime's
#                               own ceiling, so the 7 reserved here are actually reachable (they
#                               were not, and config_check's NOTE said they were).
_CW_ORDER_WORDS = {1: "first", 2: "second", 3: "third"}    # read via .get(order_n, "third"): a
#                               KeyError here would be swallowed by the wrapper belt into a silent
#                               whole-block 'declined', the worst possible failure mode for a label.
_CW_HOP_LEVELS = ("grand", "great")       # THE NEXT-HOP VOCABULARY, and the loop bound: the leg makes
#                               `min(cw_order_max - 1, len(this))` calls to _cw_next_hop, and the
#                               per-level ledger is ("child",) + this. CW_DEEP_MAX_ORDER and this
#                               tuple move together (pinned: CW_DEEP_MAX_ORDER - 1 == len(this)).
#                               THE REACHABLE SPLIT, stated ONCE and here (build-review minor L9):
#                               the WIDTH half touches ONE of the three corn_cbot-rooted deck rows --
#                               the other two are composer-narrated or render at zero extra reads --
#                               and the DEPTH half is the palm chain. That sentence is the arm's
#                               expectation; nothing else in this estate restates it.
_CW_DEEP_DECLINES = ("no_next_hop",)      # what the engine emits into payload['declines'] at scope
#                               grand/great. ONE reason, not six: `order_cap` is dead (cw_order_max
#                               is CW_DEEP_MAX_ORDER whenever deep_on), the two `*_not_priced_budget`
#                               reasons died with the trim ladder, and `ancestor_pre_coverage` died
#                               with the transitive-free rule (refute-v4 major-1: on the shipped
#                               graph the coverage floors are non-decreasing down the only chain, so
#                               a free ancestor implies every descendant free and the rule saved
#                               ZERO reads while deleting declared absence rows).
_CW_HOP_CANDIDATE_REASONS = ("child_uncovered", "node_cycle", "cross_currency", "sign_undeclared",
                             "sign_not_unanimous", "lag_gate", "relation_unmapped",
                             "blurb_not_unanimous", "not_kept_subgraph")
#                               THE NINE SILENT per-candidate rejections of the hop-2/hop-3 ladder,
#                               recorded ONLY in payload['deep']['hop_candidates']. A SEPARATE
#                               vocabulary from _CW_DEEP_DECLINES so the decline census stays a
#                               decline census. `composer_narrated_pair` is in NEITHER tuple: it is
#                               the one candidate outcome that ALSO reaches payload['declines'], at
#                               scope 'child' ON THE HOP-2 CALL, byte-verbatim (the shipped quirk,
#                               pinned AS a quirk). On the HOP-3 call -- new code, unreachable with
#                               the flag off -- it carries scope 'great', so the child-scope census
#                               can never name a slug that was never in children_declared
#                               (build-refute minor: the scope is the LEVEL, not the quirk).
#                               Two more child-scope reasons live outside both tuples by the same
#                               rule: `child_not_priced_budget` (shipped) and `width_belt` (V2-5).

# -- V2-1 CONTEXT CELL: a RIDER on the walk (GRAPHRAG_CASCADE_CONTEXT threads INSIDE walk_request as
#    `context`/`replay`, built at the answer.py seam beside focus_contract; this module reads no env).
#    ONE non-verdicted row beside a firing whose RESOLVED SLICE has a curated pink-sheet series, read at
#    the TURN's asof in ONE fetch, its ONE clock on the line = the World Bank release stamp. Flag-off is
#    byte-identical by construction: no `kind` key, no payload['context'], the marker bytes unchanged.
CW_CONTEXT_CAP = 2            # one read per cell x one cell per firing x CW_MAX_FIRINGS -> 2, OUTSIDE
#                               CW_CAP. BINDS ONLY THE DEPTH-IN-TIME SHAPE: breadth/grandchild truncate
#                               firings[:1], so the live bound on every root the rider fires on today is
#                               1 (the lint pins == CW_MAX_FIRINGS).
CW_CONTEXT_READS_PER_CELL = 1
CW_CONTEXT_MIN_OBS = 3        # a COVERAGE floor, never a path guarantee: the printed magnitude is
#                               last/first over two endpoints; three in-window prints make 'from X
#                               through Y' name a run. THE ONE ZERO-COST FLOOR (refute m2): the exact
#                               first-of-month COUNT over [t1, min(t2, asof - the CARD's
#                               publication_lag_days)] -- the lag is read off the card at the call, never
#                               a second constant here. For the record: the shortest interval that can
#                               hold three first-of-month prints is 59 days (Feb 1..Apr 1, non-leap) and
#                               91 days guarantees three, so a span test would be redundant with the
#                               count -- which is why there is no CW_CONTEXT_MIN_SPAN_DAYS.
CW_CONTEXT_TOKEN = "] CONTEXT "        # ROW-1C's class token right after the handle; minted ONCE here.
#                                        The answer-seam gate keys on the ROW SHAPE below (refute M2: the
#                                        bare token is ten characters a retrieved heading can carry).
CW_CONTEXT_LINE_RX = re.compile(r"^- \[N\d+" + re.escape(CW_CONTEXT_TOKEN), re.M)
#                                        ^ the SINGLE producer of the gate shape: built from the token,
#                                          read by `answer._cascade_context_block_on` (the CW_MARKER_PREFIX
#                                          law -- producer and gate cannot drift if they build from one string).
CW_CONTEXT_WORDS_PREFIX = "CONSEQUENCE CONTEXT "
_CW_CONTEXT_TABLE = "silver_pink_sheet"
_CW_CONTEXT_UNIT_FMT = "percent change in {unit}"     # the card's declared unit rides inside, verbatim
_CW_CONTEXT_SERIES = {        # RESOLVED SLICE -> (card metric, READER label); keyed on the slice the shipped
#                               resolver returns, never node_token (broiler_economics <- poultry_expansion AND
#                               broiler_margins, subgraph-order dependent). v1 map = the card's EXISTING consumer
#                               naming (config_check.check_cascade_context clause (c) pins each slice name
#                               VERBATIM in its metric's desc; that desc is ALSO the licence for the marker's
#                               'a market the firing names' clause -- refute m7). avian_influenza is NOT mapped
#                               -- an owner curation decision (its desc edit is a live prompt change);
#                               cattle_on_feed / livestock_feed_demand / african_swine_fever unmapped, each for
#                               a measured reason (design v1/v2 record). PRE-ARM GATE (refute M4): KC0b (does a
#                               mapped slice WIN position 1 on a covered root) is RE-RUN against the artifact
#                               that will actually serve the arm before any arm fires -- the map is asof-fragile
#                               by construction (one live window today).
    "broiler_economics":      ("chicken_usd_t", "world chicken"),
    "cattle_cycle_herd_size": ("beef_usd_t",    "world beef"),
}
_CW_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
              "September", "October", "November", "December")
_CW_RELEASE_STAMP_RX = re.compile(r"^\d{4}M\d{2}$")   # the WB stamp's ONE shape ('2026M08'); any other declines
# The counted decline vocabulary (all trace-only; no CONSEQUENCE ABSENCE line is ever minted for a
# context cell because no header promises one). `mixed_release_stamp` is UNREACHABLE under the card's
# constant global stamp (DP-2: latest_release_ym is one value for the whole table) and is kept as a belt;
# `error` is the per-firing exception belt (refute M1) -- the CELL declines, the walk block ships.
_CW_CONTEXT_DECLINES = ("unmapped_slice", "replay", "root_declined", "budget_cap", "context_cap",
                        "grain_thin", "empty_series", "read_error", "no_release_stamp",
                        "mixed_release_stamp", "stamp_shape", "no_unit", "no_move", "render_fence",
                        "error")

# -- V2-3 CROSS-CURRENCY RIDER (GRAPHRAG_CASCADE_XCCY, threaded INSIDE walk_request as `xccy`; this
#    module reads no env). THE RULE, unchanged through three refutes: admit a cross-currency hop iff
#    EXACTLY ONE side is USD and the FX card holds <ccy>_usd; NEVER construct a cross rate; every
#    figure stays in its OWN settlement currency; the verdict is stats.sign_agreement over two
#    own-currency percent moves; the exchange rate is ONE cited row over the FIRING WINDOW itself.
#    The rider LIFTS children, so it selects the V2-5 DEEP REGIME by the same `deep_on` union above
#    -- V2-3 mints NO cap pair and NO trim ladder of its own (the constants law).
CW_XCCY_USD = "USD"
CW_FX_CAP = 3                 # distinct crosses priced per TURN, OUTSIDE the board cap (the
#                               CW_CONTEXT_CAP shape). MEASURED: the widest root carries exactly 3
#                               distinct crosses among its admitted children (CAD, CNY, EUR); every
#                               other root carries 2, 1 or 0.
CW_FX_READS_PER_CELL = 1
CW_FX_MIN_OBS = 2             # two dated prints ARE the clock. The context cell's 3 is a MONTHLY
#                               grain floor and does not transfer -- MEASURED 42 to 186 daily prints
#                               per banked firing window, so this floor never binds on a real firing.
CW_FX_TOKEN = "] EXCHANGE RATE "       # ROW-1X's class token right after the handle; minted ONCE here.
CW_FX_LINE_RX = re.compile(r"^- \[N\d+" + re.escape(CW_FX_TOKEN), re.M)
#                                        ^ LINT-ONLY (clause (xii)). The answer-seam gate keys on
#                                          CW_XCCY_CLAUSE_MARK instead, because a hop whose FX cell
#                                          declined renders WORDS AND NO ROW -- a row-shape regex
#                                          would miss exactly the case the mandate must still cover.
CW_FX_WORDS_PREFIX = "CONSEQUENCE CURRENCY "
# THE HOP HEADER'S OWN CURRENCY CLAUSE, minted ONCE: the MARK is what the seam gate greps for, the
# CLAUSE is what the producer renders (the CW_MARKER_PREFIX law -- one string, so producer and gate
# cannot drift). It exists ONLY on a hop whose child cell CLOSED, so the mandate can never ship
# demanding a figure for a hop that has none (the W4-D3 shape).
CW_XCCY_CLAUSE_MARK = "; each board is priced in its own settlement currency here, "
CW_XCCY_CLAUSE = CW_XCCY_CLAUSE_MARK + "{a} and {b}, and no exchange rate is applied to either figure."
_CW_FX_TABLE = "silver_fred_fx"
_CW_FX_UNIT_FMT = "percent change in {unit}"
#                               ^ the READER LABEL rides inside this, NEVER the card's unit string:
#                                 citations.py prints a call row's unit on the RENDERED citation
#                                 label (and falls back to the CARD's unit when the row carries
#                                 none), so an unset unit would put the card's own machine-shaped
#                                 'CNY per USD (ECB via Frankfurter)' string on a page.
_CW_FX_CROSS = {              # non-USD currency -> (card metric, READER label). The map DEFINES
    "CNY": ("cny_usd", "Chinese yuan per US dollar"),          # admissibility (clause (xii) reads it
    "CAD": ("cad_usd", "Canadian dollars per US dollar"),      # one-directionally: a stale entry
    "EUR": ("eur_usd", "euros per US dollar"),                 # errors, a missing one is structurally
    "ZAR": ("zar_usd", "South African rand per US dollar"),    # unreachable).
}
_CW_CURRENCY_WORD = {         # WORDS on every reader surface, never ISO codes. EXACTLY the
    "USD": "US dollars",      # currencies of _CW_BOARD_LABEL boards (clause (xi) pins both
    "CNY": "Chinese yuan",    # directions): BRL is absent because both BRL boards are cash indices
    "CAD": "Canadian dollars",  # and carry no label; MYR is absent because V2-4 re-keyed palm to
    "EUR": "euros",           # the CME USD tape.
    "ZAR": "South African rand",
}
_CW_FX_DECLINES = ("replay", "fx_cap", "budget_cap", "no_card", "no_metric", "cache_declined",
                   "read_error", "empty_series", "grain_thin", "no_unit", "no_move", "render_fence",
                   "block_fenced", "error")
_CW_FX_PRE_ADMIT = ("replay", "fx_cap", "budget_cap", "no_card", "no_metric", "cache_declined")
#   'read_error' is deliberately NOT here: it is the POST-read name minted at the paying site (a paid
#   read that came back status=error), so counting it pre-admit made the pre-admit identity FALSE on
#   exactly that path (fix re-review major 1, MEASURED). Rungs 6/6b carry their own pre-read names.
#                               ^ the FIVE rungs that decline BEFORE a read is paid ('cache_declined'
#                                 is rung 2's zero-read arm). Named as a tuple so the FX rectangle is
#                                 auditable from the artifact alone:
#                                 fx_planned == fx_admitted + fx_cache_hits + |pre-admit declines|,
#                                 and the simpler total fx_planned == fx_rendered + fx_cache_hits +
#                                 |declines| holds on EVERY path including the exception belt and
#                                 the whole-block register fence ('block_fenced', which is a BELT
#                                 TRIP and therefore in the full tuple only -- those cells WERE
#                                 admitted and paid, so counting them pre-admit would double them).
#                                 THE CONSUMER (build-review minor): the suite's closure pin
#                                 test_every_fx_decline_reason_is_named_in_the_tuple runs every
#                                 xccy fixture in the group and asserts each reason it observes is a
#                                 member of this tuple -- the 'declines are NAMED and COUNTED' law
#                                 is enforced there, not merely documented here.

# Orientation-free relation phrases (v3 remedy (b)): each phrase reads identically under (A, B)
# and (B, A); config_check's directional-verb lint holds it. An unmapped relation DECLINES.
_CW_RELATION_WORDS = {
    "competes_with": "compete for the same demand",
    "substitutes_for": "stand in for one another in the same use",
    "crushed_into": "are joined by the same crush",
    "correlates_with": "move together in the record",
    "leads_lags": "the record places a lead-lag between them",
}

# Reader label per slug the walk can put on a surface (resolve-or-decline, never a raw slug on a
# reader line, letters-only). EVERY VALUE IS display._contract_label's OWN SPELLING, and the lint
# pins that equality (STEP-12 review D9: a second board vocabulary put two names on one page and a
# display label in the machine locator killed the chart; ONE vocabulary, display owns it). The
# roster covers the shipping hops PLUS every covered root that clears the seed gate
# (hard_red_spring_wheat_mgex -- review D1's reproduced KeyError root).
_CW_BOARD_LABEL = {
    "corn_cbot": "CBOT corn",
    "hard_red_winter_wheat_kcbt": "KCBT hrw wheat",
    "soft_red_winter_wheat_cbot": "CBOT srw wheat",
    "soybeans_cbot": "CBOT soybeans",
    "soybean_meal_cbot": "CBOT soybean meal",
    "soybean_oil_cbot": "CBOT soybean oil",
    # V2-4: the CME USD palm calendar future, covered from its PROVISIONAL 2016-08-01 floor. The
    # label is display._contract_label's own spelling (hierarchy {node palm_oil, exchange CME});
    # the tenor floor that keeps its cells off a still-accruing average lives in futures_roll.
    "malaysian_crude_palm_oil_cme": "CME palm oil",
    "arabica_coffee": "ICE arabica coffee",
    "robusta_coffee": "ICE robusta coffee",
    "raw_sugar": "ICE raw sugar",
    "white_sugar": "ICE white sugar",
    "rapeseed_oil_zce": "ZCE rapeseed oil",
    "rapeseed_meal_zce": "ZCE rapeseed meal",
    "hard_red_spring_wheat_mgex": "MGEX hrs wheat",
    # engine-reachable roots whose hops decline at the CHILD gates (cross-currency mostly) --
    # labeled so the decline is the honest child reason, never root_unlabeled (the lint decides
    # the roster; an unlisted covered root is a lint error, not a serve-time surprise).
    "canola_ice": "ICE canola",
    "french_rapeseed_matif": "MATIF rapeseed",
    "french_wheat_matif": "MATIF french wheat",
    "rough_rice_cbot": "CBOT rice",
    "south_african_white_maize_jse": "JSE white maize",
    # V2-3: COUPLED to the cross-currency gate, not optional -- the widened ladder makes this slug
    # an engine-reachable hop surface (corn_cbot->south_african_yellow_maize_jse), and clause (i)
    # errors in the MISSING direction without it and as a STALE row without the gate edit.
    "south_african_yellow_maize_jse": "JSE yellow maize",
}

_CW_LAG_RX = re.compile(r"^(\d+)-(\d+)\s+quarters?$")

# The honest WHY of every walk absence -- observation words only, no numerals, no direction verbs.
_CW_ABSENCE_WHY = {
    "child_uncovered": "the record carries no board price history for that market",
    "cross_currency": "the two boards settle in different currencies, so no shared read is taken",
    # V2-3 admission-scope reasons (trace-only, per the dict header: they mint no ROW 4) plus the
    # one CELL-side verdict reason. Observation words only, numeral-free, direction-verb-free.
    "cross_currency_no_pair_rate":
        "the record carries no exchange rate between those two settlement currencies",
    "cross_currency_unmapped": "the record carries no settlement currency for that board",
    "cash_index_board": "that board settles on a cash index with no delivery month",
    "fx_flips_sign": "the exchange rate moved further than the board priced in it over this window, "
                     "and it moved the same way, so no direction is read",
    "sign_not_unanimous": "the declared relations disagree on direction, so no direction is read",
    "sign_undeclared": "the declared relation does not commit to a direction here",
    "lag_gate": "the declared response horizon is longer than a single firing window",
    "relation_unmapped": "the declared relation has no phrase in the curated register",
    "blurb_not_unanimous": "the curated descriptions of this pair disagree",
    "node_cycle": "the path folds back onto the same market",
    "composer_narrated_pair": "another engine already narrates this pair on this turn",
    "child_not_priced_budget": "the read budget covers the markets above only",
    "j4_budget_deferred": "the episode leg already declined this window on its own budget",
    "j4_owns_window": "the episode leg already carries this window's move for that market",
    "horizon_open": "the horizon on this window has not closed yet, so no move is measured here",
    # the CELL-side reasons a reader can actually see (review minor: the OC decline enum and the
    # seam's own read declines reach ROW 4; the ADMISSION reasons above ride the trace only except
    # child_uncovered/composer_narrated_pair, which both surfaces share).
    "read_truncated": "the tape read for this window overflows its bound, so no move is measured",
    "no_tape_rows": "the tape carries no rows for this market over this window",
    "no_move": "the record does not close a move for this market over this window",
    "unmapped_slug": "the record carries no board price history for that market",
    "pre_coverage": "this window predates that board's own price history",
    "coverage_straddle": "this window straddles the start of that board's price history",
    "no_anchor_session": "no usable session opens this window on that board",
    "no_surviving_contract": "no single delivery month lives across this window on that board",
    "no_endpoint_session": "that board has no session at this window's close",
    "bad_endpoint_price": "the closing print on that board is unusable",
    "no_spanning_contract": "no single delivery month spans this window on that board",
    "span_inverted": "this window's dates are inverted, so nothing is measured",
    "span_exceeds_contract_life": "no single delivery month can span a window this long",
}


def _cw_min_lag_quarters(lag):
    """The MINIMUM declared quarters of an edge's free-text lag, or None when unparseable. A GATE
    only (unparseable DECLINES); never rendered -- both numerals of '0-2 quarters' extract as claim
    magnitudes under the verifier, so the string can never sit on a copy surface."""
    m = _CW_LAG_RX.match(str(lag or "").strip())
    return int(m.group(1)) if m else None


def _cw_currency(slug: str):
    try:
        from leviathan.silver import futures_eod_contracts as FC
        return (FC.CONTRACT_MAP.get(slug) or {}).get("currency")
    except Exception:  # noqa: BLE001 -- an unknown slug reads as no currency -> the gate declines
        return None


def _cw_cash_index(slug: str) -> bool:
    """V2-3: does this board settle on a CASH INDEX (futures_eod_contracts' own `settle_kind`)?
    `_cw_currency`'s idiom with the OPPOSITE failure direction -- unknown REFUSES (returns True),
    because a cash-index board carries contract_month NULL by design, so `_cw_fences` returns
    tenor_ok False on every pair it touches and the hop could only ever render a cell that can
    never verdict.

    THE ORDERING LAW (v1 refute F1, MEASURED): this test runs BEFORE the FX-column test in the
    admission ladder or it is dead code -- the only cash-index boards in the estate are
    brazilian_arabica_coffee and campinas_corn_reference_bmf, both BRL, and BRL has no
    `_CW_FX_CROSS` entry, so an FX-first order mis-buckets those two hops (7/0 under the wrong
    order, 5/2 under this one)."""
    try:
        from leviathan.silver import futures_eod_contracts as FC
        row = FC.CONTRACT_MAP.get(slug)
        if not row:
            return True                    # no declared board -> no settle kind -> REFUSE
        return str(row.get("settle_kind") or "") == "cash_index"
    except Exception:  # noqa: BLE001 -- unreadable map -> refuse
        return True


def _cw_fx_metric(cur_a, cur_b):
    """V2-3: the (card metric, READER label) pair for a cross, or None when the pair is not
    admissible. Admissible iff the two currencies DIFFER, both are truthy, EXACTLY ONE is USD, and
    the card carries a column for the other. NO cross rate is ever constructed."""
    if not cur_a or not cur_b or cur_a == cur_b:
        return None
    if (cur_a == CW_XCCY_USD) == (cur_b == CW_XCCY_USD):
        return None                                   # both USD (impossible here) or neither
    other = cur_b if cur_a == CW_XCCY_USD else cur_a
    return _CW_FX_CROSS.get(other)


def _cw_currency_words(cur) -> str:
    """V2-3: the reader WORD for a settlement currency -- never an ISO code on a reader surface."""
    return _CW_CURRENCY_WORD.get(str(cur or ""), "")


def _cw_kept_contracts(sg) -> set:
    """Hop-2 membership: the `_xc_walk_index` iteration shape with the relevance read DELIBERATELY
    omitted -- membership is read, rank is never read (A1)."""
    try:
        return {n.id for n in (getattr(sg, "nodes", None) or [])
                if getattr(n, "kind", None) == "contract" and getattr(n, "id", None)}
    except Exception:  # noqa: BLE001
        return set()


def _cw_j4_index(sg) -> dict:
    """A4: keyed on (the slug J4 actually PRICED, span token) so child cells never collide by
    construction; only the ROOT cell consults it. Never raises on a traceless sg."""
    try:
        entries = (getattr(sg, "trace", None) or {}).get("quantify_episode_outcomes") or []
        return {(str(e.get("slug")), str(e.get("span"))): e for e in entries
                if isinstance(e, dict) and e.get("slug")}
    except Exception:  # noqa: BLE001
        return {}


def _cw_narrated_pairs(sg) -> set:
    """K3 extended (refute-v3 major-2): the market pairs OTHER engines narrate this turn -- the
    transmission composer's links AND the RV2/comove fork's pair. A name-vocabulary miss here
    fails OPEN (the pair renders twice rather than the walk over-declining); the arm's K3 clause
    measures exactly that."""
    tr = getattr(sg, "trace", None) or {}
    pairs: set = set()
    # per-source belts (review minor): one malformed host must not erase the pairs the OTHER
    # engine supplied -- a single try around both loops failed open for both at once.
    try:
        for lk in (tr.get("quantify_transmission") or {}).get("links") or []:
            try:
                s, t = str(lk.get("source") or ""), str(lk.get("target") or "")
                if s and t:
                    pairs.add(frozenset((s, t)))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    for key in ("quantify_reroute_v2", "quantify_comove"):
        try:
            d = tr.get(key) or {}
            s, t = str(d.get("commodityA") or ""), str(d.get("commodityB") or "")
            if s and t:
                pairs.add(frozenset((s, t)))
        except Exception:  # noqa: BLE001
            continue
    return pairs


def _cw_turn_spent(sg):
    """THE ENUMERATION (A2/K7), written in ONE place: the walk's ceiling binds on exactly the
    producers that spend BEFORE the walk runs -- the base wave, the two chain engines (fired AND
    declined), the price leg (fired AND declined), the RV2/comove fork, and J4's entry list.
    J6 is DELIBERATELY OUTSIDE the set (STEP-12 review D3, confirmed): quantify calls the walk
    ABOVE `_cot_outcome_legs`, so J6's key is structurally absent here and an enumerated term
    that can never be read would make the claimed set a fiction; J6's own post-walk spend is
    bounded beside CW_TURN_CEILING's comment instead. Returns the summed reads, or None when ANY
    present payload in the set carries no counter -- ABSENT IS NEVER ZERO; the caller declines
    `turn_spend_unknown` (the fail-closed direction the round-3 refute demanded)."""
    tr = getattr(sg, "trace", None) or {}
    wave = tr.get("quantify_wave_reads")
    if not isinstance(wave, int):
        return None                                   # stamped 0-included on every quantifying turn
    total = wave
    for key in ("quantify_transmission", "quantify_transmission_decline",
                "quantify_chain", "quantify_chain_decline",
                "quantify_price_leg", "quantify_price_leg_decline",
                "quantify_reroute_v2", "quantify_comove"):
        p = tr.get(key)
        if not p:
            continue
        nr = p.get("net_reads") if isinstance(p, dict) else None
        if not isinstance(nr, int):
            return None
        total += nr
    for e in tr.get("quantify_episode_outcomes") or []:
        r = (e or {}).get("reads")
        if not isinstance(r, int):
            return None
        total += r
    return total


def _cw_firings(sg, graph, root: str, cov_start: str) -> tuple:
    """A6.1 as adjudicated: the root TREE'S driver windows, read from the turn's own
    `episodes_injected` (the interlock -- never a window the model was not shown), each firing
    KEYED AND LABELLED by the RESOLVED SLICE via the SHIPPED `ev.slice_for_driver` (refute M1/M3:
    38 slices are reached by more than one tree id, including semantic opposites, and a hand map
    would be a fourth copy of a shipped resolver). Dedupe by (start, end); recency sort here,
    selection at the caller. Returns (firings, grounded_slices)."""
    try:
        recs = list((getattr(sg, "trace", None) or {}).get("episodes_injected") or [])
    except Exception:  # noqa: BLE001 -- a traceless sg simply has no firings
        return [], []
    c = (getattr(graph, "contracts", None) or {}).get(root) if graph is not None else None
    tree = {str(d.id) for d in (getattr(c, "drivers", None) or [])}
    if not recs or not tree:
        return [], []
    from leviathan.graphrag import evidence as _ev    # lazy: the _xmit_pair_realizable idiom
    firings, seen, grounded = [], set(), []
    for rec in recs:
        nid = str((rec or {}).get("node") or "")
        if nid not in tree:
            continue
        try:
            sl = _ev.slice_for_driver(nid)
        except Exception:  # noqa: BLE001 -- an unresolvable driver cannot have been injected
            sl = None
        if not sl:
            continue
        if sl not in grounded:
            grounded.append(sl)
        for w in (rec or {}).get("windows") or []:
            t1, t2 = str((w or {}).get("start") or ""), str((w or {}).get("end") or "")
            try:
                span_days = _iso_days(t2) - _iso_days(t1)
            except (TypeError, ValueError):
                continue                              # an unreadable window is not a firing
            if not (CW_SPAN_MIN_DAYS <= span_days <= CW_SPAN_MAX_DAYS):
                continue
            if t1 < cov_start or (t1, t2) in seen:
                continue
            seen.add((t1, t2))
            firings.append({"start": t1, "end": t2,
                            "span": str((w or {}).get("span") or f"{t1[:7]}..{t2[:7]}"),
                            "span_days": span_days, "slice": sl,
                            "node_token": nid})       # M4: the injected line's OWN token, verbatim
    firings.sort(key=lambda f: (f["end"], f["start"]), reverse=True)   # MAJOR-5: recency only
    # one window per VISIBLE clock (review minor): two day-grain windows sharing a month-span
    # token would put two magnitudes for one board under one rendered window; the later one drops.
    seen_tok: set = set()
    firings = [f for f in firings
               if not (f["span"] in seen_tok or seen_tok.add(f["span"]))]
    return firings, grounded


def _cw_slice_label(sl: str) -> str:
    """The reader label for a firing slice -- display's own vocabulary, plain-words fallback."""
    try:
        from leviathan.graphrag import display as dp
        return dp.node_label(sl, "driver")
    except Exception:  # noqa: BLE001
        return str(sl).replace("_", " ")


def _cw_cell(qfn, slug: str, t1: str, t2: str, span_tok: str, asof, *,
             futures_newest_first: bool | str = False) -> tuple:
    """ONE cell, the J4 pricing sequence VERBATIM (dry run -> curve -> candidates -> deep ->
    saturation decline -> frame -> span_outcome -> the lazy PENDING edge re-ask). Returns
    (record, reads); the record carries the raw outcome dict under '_res' for the call mint and
    the caller pops it before tracing."""
    from leviathan.graphrag.numbers import outcomes as OC
    from leviathan.silver import futures_roll as FR
    rec = {"slug": slug, "span": span_tok, "status": None, "reason": None, "reads": 0}
    dry = OC.span_outcome(_tape_frame("", []), slug=slug, span_start=t1, span_end=t2, asof=asof,
                          event_key="cascade_walk", tape_edge=None)
    if str(dry.get("status") or "") == OC.STATUS_PENDING:
        rec.update(status="pending", reason="horizon_open")
        return rec, 0
    dr = dry.get("decline_reason")
    if dr and dr != OC.DECLINE_NO_ANCHOR_SESSION:
        rec.update(status="declined", reason=dr)
        return rec, 0
    lo = _iso_shift(t1, -OC.OUTCOME_LOOKBACK_DAYS)
    hi = _iso_shift(t2, OC.SURVIVE_DAYS + OC.OUTCOME_LOOKBACK_DAYS)
    curve, sat_a = _tape_read(qfn, slug=slug, t1=lo, t2=t1, asof=asof,
                              futures_newest_first=futures_newest_first)
    months = _episode_candidates(curve, t2, floor_months=FR.forward_month_floor(slug))
    deep, sat_b = _tape_read(qfn, slug=slug, t1=lo, t2=hi, asof=asof,
                             contract_months=months or None,
                             futures_newest_first=futures_newest_first)
    rec["reads"] = 2
    if sat_a or sat_b:
        rec.update(status="declined", reason=EP_DECLINE_READ_TRUNCATED)
        return rec, 2
    tape = _tape_frame(slug, curve, deep)
    if not len(tape):
        rec.update(status="declined", reason=EP_DECLINE_NO_TAPE)
        return rec, 2
    res = OC.span_outcome(tape, slug=slug, span_start=t1, span_end=t2, asof=asof,
                          event_key="cascade_walk")
    if str(res.get("status") or "") == OC.STATUS_PENDING:
        edge_rows, sat_c = _tape_read(qfn, slug=slug, t1=t2, t2=hi, asof=asof,
                                      futures_newest_first=futures_newest_first)
        rec["reads"] = 3
        ef = _tape_frame(slug, edge_rows)
        edge = (OC.tape_edges(ef) or {}).get(str(slug)) if len(ef) else None
        if edge is not None and not sat_c:
            res = OC.span_outcome(tape, slug=slug, span_start=t1, span_end=t2, asof=asof,
                                  event_key="cascade_walk", tape_edge=edge)
    st = str(res.get("status") or "")
    if st != OC.STATUS_CLOSED or res.get("move_pct") is None:
        rec.update(status=("pending" if st == OC.STATUS_PENDING else "declined"),
                   reason=res.get("decline_reason") or st or "no_move")
        return rec, rec["reads"]
    rec.update(status="closed", move_pct=round(float(res["move_pct"]), 4),
               anchor_date=str(res.get("anchor_date")), endpoint_date=str(res.get("endpoint_date")),
               contract_month=str(res.get("contract_month_used")), _res=res)
    return rec, rec["reads"]


def _cw_fences(rec_a: dict, rec_b: dict, span_days: int) -> tuple:
    """MAJOR-8, constants from the banked K0 artifacts: the realized-interval fence
    (|d_anchor| + |d_endpoint| <= min(7 days, a tenth of the span)) and the tenor fence
    (same-or-adjacent delivery month). Returns (interval_ok, tenor_ok)."""
    d_anchor = abs(_iso_days(rec_a["anchor_date"]) - _iso_days(rec_b["anchor_date"]))
    d_end = abs(_iso_days(rec_a["endpoint_date"]) - _iso_days(rec_b["endpoint_date"]))
    ri = (d_anchor + d_end) <= min(7.0, 0.10 * span_days)

    def _mk(ym):
        s = str(ym or "")[:7]
        try:
            return int(s[:4]) * 12 + int(s[5:7])
        except (TypeError, ValueError):
            return None

    ma, mb = _mk(rec_a.get("contract_month")), _mk(rec_b.get("contract_month"))
    return ri, (ma is not None and mb is not None and abs(ma - mb) <= 1)


# -- WINDOW-AGE DATING (the V2-5 K8 panel follow-up, 2026-09-04) -------------------------------------
CW_WINDOW_AGE_MONTHS = 12
#   ^ THE THRESHOLD, minted ONCE and read by the renderer below and by nothing else. A firing window
#     whose END trails the as-of by MORE than this many WHOLE months is DATED on its own row instead
#     of being left to read as a current observation. MEASURED TRIGGER: the V2-5 panel read a 2015
#     firing window as the present state of the market -- the window token on the row ('2015-01..
#     2015-06') is a scope, and nothing on the line said how far behind the as-of that scope sat.
#     TWELVE, and the reason is stated rather than assumed: one full crop year is the shortest gap
#     after which every board on this page has rolled its delivery month at least once, so a reader
#     who takes such a row as current is wrong about a DIFFERENT CONTRACT, not merely about a staler
#     print of the same one. The mandate half lives in `answer._SYSTEM_CASCADE_WALK_MANDATE`.
#     REACH, stated as a limit (review MIN-2, 2026-09-04): the note renders on BOARD rows only (ROW-1,
#     root and child -- the two `_cw_cell_line` call sites). The FX row (ROW-1X, `_cw_fx_line`) and the
#     context row (ROW-1C, `_cw_context_line`) already print their own first and last dates, so on a
#     deep + xccy block the reader meets one row class dated by this clause and two dated by their own
#     printed endpoints; the mandate's conditional wording covers exactly the rows that carry it.


def _cw_window_age_note(t_end, asof) -> str | None:
    """The ROW-1 window-age clause, or None when the window is fresh enough or either date is
    unreadable. Pure string/int arithmetic on two ISO dates (the `_cw_first_of_months` idiom -- this
    module reads no clock, so a fixture and a serving turn date the same window identically).

    THE ORTHOGRAPHY IS LOAD-BEARING, and it is `_cw_min_lag_quarters`' hazard read the other way. A
    bare 'N years before this as-of' copied into prose extracts as a CLAIM MAGNITUDE under
    `verify._claim_number_spans`: 'before' is a `_DUR_STOP`, so the space spelling earns no duration
    exemption, and the all-numbers guard would then strip the writer's own dating sentence as
    number_unbacked -- the exact class the verifier's own note records ('10 days before the as-of
    date' is a charged claim by design). The hyphen compound with a `_STAT_HEAD` noun ('5-year span')
    clears BOTH cycle-8 spellings, so this clause can be copied verbatim into a handled sentence and
    survive. The noun is 'span' and NOT 'gap' for a second reason: the walk mandate forbids the
    writer to derive a gap between two rows, and a row that printed the word would be teaching the
    idiom it fences.

    THE UNIT SWITCHES AT TWO YEARS AND THE YEAR COUNT IS FLOORED, both stated rather than assumed.
    Below 24 whole months the span reads in months, so the first year past the threshold is not
    rounded away to a bare '1-year'; at or above it the span reads in floored years, which can only
    UNDERSTATE the age by less than one year and never overstate it -- the safe direction for a
    clause a writer will copy as a fact."""
    e, a = str(t_end or "")[:10], str(asof or "")[:10]
    try:
        ey, em, ed = int(e[0:4]), int(e[5:7]), int(e[8:10])
        ay, am, ad = int(a[0:4]), int(a[5:7]), int(a[8:10])
    except (TypeError, ValueError):
        return None                                   # an unreadable date DECLINES, never guesses
    months = (ay * 12 + am) - (ey * 12 + em)
    if ad < ed:
        months -= 1                                   # a partial month is not a whole one
    if months <= CW_WINDOW_AGE_MONTHS:
        return None                                   # inside the threshold, or the window is ahead
    n, unit = (months // 12, "year") if months >= 24 else (months, "month")
    return f"window ended {e}, {n}-{unit} span to this as-of"


def _cw_cell_line(n: int, slug: str, rec: dict, asof, *, age_note: str | None = None) -> str:
    """ROW 1 -- the J4 cell template VERBATIM with the curated board label in the query (v3 minor:
    the call record is the producer; tag and ledger read the same string the model sees).

    `age_note` is `_cw_window_age_note`'s clause, threaded from the render loop and None everywhere
    it does not apply -- so a row without one is BYTE-IDENTICAL to the shipped template, which is
    what makes the flag-off golden hold across this change."""
    label = _CW_BOARD_LABEL[slug]
    q = {"commodity": label, "country": None, "contract_month": rec.get("contract_month"),
         "table": _TAPE_TABLE}
    aged = f"; {age_note}" if age_note else ""
    return (f"- [N{n}] {label} settle change across the episode window {rec['span']} "
            f"(one delivery month held at both ends, as-of {asof}{aged}): {rec['move_pct']:+g} %"
            + _series_tag(q))


def _cw_call(slug: str, rec: dict, asof) -> dict:
    """The synthetic call record the [N] handle indexes -- `_episode_outcome_call` VERBATIM, the
    raw slug in query.commodity exactly as J4 keeps it (review D9, confirmed: a display label in
    the query poisons the citations LOCATOR -- the /v1/series chart params read loc.commodity
    unresolved -- and mints a second board vocabulary in the Sources ledger. The READER line keeps
    display's label through `_cw_cell_line`'s own tag dict; the machine identity stays machine)."""
    return _episode_outcome_call(slug, rec["_res"], rec["span"], asof)


def _cw_hop_header(label_a: str, label_b: str, phrases: list, blurb: str, firing_label: str,
                   *, xccy: tuple | None = None) -> str:
    """ROW 3 -- keyed on the PAIR: the union of orientation-free relation phrases + ONE blurb +
    the firing clause in WORDS. `firing_label` is the INJECTED EPISODES LINE'S OWN NODE TOKEN
    verbatim (M4 as adjudicated -- one window, one spelling on both surfaces; the caller falls
    back to the display slice label only when the injected token carries a digit, which the
    register fence would otherwise drop the block over). The window token itself rides the ROW-1
    templates only, so this line stays letters-only under the numeral scan."""
    rel = "; ".join(phrases)
    tail = f" -- {blurb}" if blurb else ""
    base = (f"CONSEQUENCE HOP {label_a} and {label_b}: the graph records these markets "
            f"{rel}{tail}; measured over the {firing_label} firing window, whose dated span rides "
            f"the rows for this hop")
    # V2-3: the SPLIT keeps the flag-off literal byte-exact -- `xccy` None returns exactly the
    # shipped string. The clause exists ONLY on a CLOSED child cell (the caller's own gate), so the
    # seam gate that keys on CW_XCCY_CLAUSE_MARK can never arm on a figure-less hop.
    if not xccy:
        return base + "."
    return base + CW_XCCY_CLAUSE.format(a=_cw_currency_words(xccy[0]), b=_cw_currency_words(xccy[1]))


def _cw_verdict_line(label_a: str, label_b: str, verdict: str, *, xccy: tuple | None = None,
                     reason: str | None = None) -> str:
    """ROW 2 -- the three-valued read, letters only, no handles (a handle digit here would be a
    numeral outside a ROW-1 template). In-sample clause ON the line (MAJOR-12).

    V2-3: a FOURTH mid-variant, taken first when `reason` is 'fx_flips_sign'; and a currency tail
    on every cross-currency hop. THE TAIL IS REWORDED, NEVER DOUBLED, ON THAT FOURTH VARIANT
    (v3 refute major-5, MEASURED on the rendered bytes): the shipped tail says the direction IS
    read on each board's own-currency move, which contradicts a mid that has just said no direction
    was read at all -- under a mandate to state the READ in the block's own terms. On that branch
    the tail states the currencies and claims no direction."""
    if reason == "fx_flips_sign":
        mid = ("the exchange rate between the two settlement currencies moved further over this "
               "window than the board priced in it did, and it moved the same way, so the record "
               "declines to read a direction on this firing -- state that plainly")
    elif verdict == "aligned":
        mid = "the declared relation held on this firing"
    elif verdict == "at_odds":
        mid = "the two moves sat at odds with the declared relation on this firing"
    else:
        mid = "the record declines to read a direction on this firing -- state that plainly"
    base = (f"CONSEQUENCE READ {label_a} and {label_b}: {mid}; the moves above are the record, "
            f"in-sample on the named window only, never extended beyond it")
    if not xccy:
        return base + "."
    wa, wb = _cw_currency_words(xccy[0]), _cw_currency_words(xccy[1])
    if reason == "fx_flips_sign":
        return base + f"; each figure above stays a move inside its own settlement currency, {wa} and {wb}."
    return (base + "; the direction is read on each board's own-currency move, so the exchange-rate "
            f"move between {wa} and {wb} over this window sits inside that comparison and is not "
            "removed from it.")


def _cw_absence(label: str, reason: str) -> str:
    """ROW 4 -- an absence in words, its reason from the counted vocabulary."""
    why = _CW_ABSENCE_WHY.get(reason, "the record does not carry a measurable read here")
    return f"CONSEQUENCE ABSENCE {label}: {why}."


# -- V2-1 CONTEXT CELL helpers ----------------------------------------------------------------------
def _cw_first_of_months(t1: str, t_end: str) -> list:
    """Every first-of-month ISO date d with t1 <= d <= t_end -- pure string/int arithmetic (the
    _months_back idiom; no clock)."""
    y, m = int(t1[:4]), int(t1[5:7])
    out: list = []
    while True:
        d = f"{y:04d}-{m:02d}-01"
        if d > t_end:
            break
        if d >= t1:
            out.append(d)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _cw_context_rec(sl: str, span_tok: str) -> dict:
    """The context cell's record, minted by the CALLER before the read so the per-firing exception
    belt (refute M1) can still count a read that was paid before a later step raised."""
    metric, label = _CW_CONTEXT_SERIES[sl]
    return {"kind": "context", "slice": sl, "metric": metric, "label": label, "span": span_tok,
            "status": None, "reason": None, "reads": 0}


def _cw_context_cell(qfn, rec: dict, t1: str, t2: str, asof, *, lag_days: int, card_metric,
                     futures_newest_first: bool | str = False) -> dict:
    """ONE context cell, mutating and returning `rec`: the zero-cost coverage floor -> ONE fetch_window
    at the TURN's asof -> _rv_axes (the measured row shape: date under knowledge_date, NO unit key, card
    unit fallback) -> in-window clip -> grain -> stamp (ONE clock) -> move. `rec['reads']` is set at the
    paying site, never inferred. The caller's belt catches anything this raises."""
    metric = rec["metric"]
    t_end = min(t2, _iso_shift(asof, -int(lag_days or 0)))
    if len(_cw_first_of_months(t1, t_end)) < CW_CONTEXT_MIN_OBS:
        rec.update(status="declined", reason="grain_thin")             # A6.2: arithmetic, $0
        return rec
    # futures_newest_first threads like the board cells; harmless either way -- Q.run re-sorts a
    # newest-first series back to chronological before any consumer sees it.
    r = fetch_window(qfn, table=_CW_CONTEXT_TABLE, metric=metric, commodity=None, country=None,
                     t1=t1, t2=t2, asof=asof, agg="series", period=None, period_type="date",
                     futures_newest_first=futures_newest_first)
    rec["reads"] = CW_CONTEXT_READS_PER_CELL                              # counted at the paying site
    if r.get("status") == "error":
        rec.update(status="declined", reason="read_error")
        return rec
    if r.get("status") != "ok":
        rec.update(status="declined", reason="empty_series")
        return rec
    vals, dates, unit = _rv_axes(r, card_metric)
    keep = [(v, d) for v, d in zip(vals, dates) if t1 <= d <= t2]        # belt: never a row outside the window
    if len(keep) < CW_CONTEXT_MIN_OBS:
        rec.update(status="declined", reason="grain_thin")
        return rec
    # the ONE clock: every returned row must carry the WB release stamp (refute m3: absent is never
    # zero, PER ROW -- a partially stamped series declines rather than borrowing its neighbours' stamp).
    stamps = [str((x or {}).get("revision_stamp") or "").strip() for x in (r.get("rows") or [])]
    if not stamps or any(not s for s in stamps):
        rec.update(status="declined", reason="no_release_stamp")
        return rec
    if len(set(stamps)) != 1:
        rec.update(status="declined", reason="mixed_release_stamp")     # two clocks -> no line
        return rec
    stamp = stamps[0]
    if not _CW_RELEASE_STAMP_RX.match(stamp):
        rec.update(status="declined", reason="stamp_shape")
        return rec
    if not str(unit or "").strip():
        rec.update(status="declined", reason="no_unit")                 # refute m9: a unit is a ROW fact
        return rec
    first, last = keep[0][0], keep[-1][0]
    if not first:
        rec.update(status="declined", reason="no_move")
        return rec
    rec.update(status="closed", move_pct=round((last / first - 1.0) * 100.0, 4), n_obs=len(keep),
               first_date=keep[0][1], last_date=keep[-1][1],
               first_month=_CW_MONTHS[int(keep[0][1][5:7]) - 1],
               last_month=_CW_MONTHS[int(keep[-1][1][5:7]) - 1],
               unit=str(unit), revision_stamp=stamp)
    return rec


def _cw_context_line(n: int, rec: dict) -> str:
    """ROW-1C: the class token right after the handle; the window token = SCOPE, the returned months =
    BASIS, the release stamp = CLOCK (no as-of on this line -- one clock). 'cash benchmark price', never
    'settle' (the card's own first note)."""
    q = {"commodity": rec["label"], "country": None, "table": _CW_CONTEXT_TABLE}
    return (f"- [N{n}{CW_CONTEXT_TOKEN}{rec['label']} monthly cash benchmark price measured on the monthly "
            f"prints from {rec['first_month']} through {rec['last_month']} inside the episode window "
            f"{rec['span']} (per the World Bank release {rec['revision_stamp']}): {rec['move_pct']:+g} %"
            + _series_tag(q))


def _cw_context_words(rec: dict) -> str:
    """ROW-2C: standalone, letters only -- no hop possessive, no comparison invitation."""
    return (f"{CW_CONTEXT_WORDS_PREFIX}{rec['label']}: this row is not part of any hop's read and carries "
            f"no direction of its own; it is the monthly world cash average the World Bank publishes for "
            f"that market, at its current published revision of the months the row names, placed beside "
            f"the walk for scope only.")


def _cw_context_call(rec: dict, asof) -> dict:
    """The synthetic call the [N] handle indexes: READER-WORD metric (the _rv_call idiom -- never the card
    id, so the ledger never says 'chicken price = a percent'); the release stamp and the machine metric
    ride the ROW (`source_metric`, which citations.from_number copies onto the LOCATOR so a drill-down can
    draw the level series the percent was computed on -- refute M5); the stamp's one RENDERING is the line."""
    call = _rv_call("monthly benchmark change", rec["label"], rec["move_pct"], rec["span"], asof,
                    unit=_CW_CONTEXT_UNIT_FMT.format(unit=rec["unit"]), date=rec["last_date"])
    call["rows"][0]["revision_stamp"] = rec["revision_stamp"]
    call["rows"][0]["source_metric"] = rec["metric"]
    return call


# -- V2-3 FX CELL helpers ---------------------------------------------------------------------------
def _cw_fx_rec(metric: str, label: str, cur_a, cur_b, span_tok: str) -> dict:
    """The FX cell's record, minted by the CALLER before the read so the belt can still count a read
    that was paid before a later step raised (the `_cw_context_rec` idiom)."""
    return {"kind": "fx", "metric": metric, "label": label, "cross": f"{cur_a}>{cur_b}",
            "cur_a": cur_a, "cur_b": cur_b, "span": span_tok,
            "status": None, "reason": None, "reads": 0}


def _cw_fx_cell(qfn, rec: dict, t1: str, t2: str, asof, *, card_metric,
                futures_newest_first: bool | str = False) -> dict:
    """ONE exchange-rate cell, mutating and returning `rec`: ONE fetch_window over THE FIRING WINDOW
    ITSELF [t1, t2] -> `_rv_axes` -> in-window clip -> obs floor -> unit -> move.

    WHY THE FIRING WINDOW AND NOT EITHER BOARD'S REALIZED ANCHOR..ENDPOINT: `_cw_fences` already
    bounds each board's realized interval to within min(7 days, a tenth of the span) of the window
    (MEASURED on 158 cross pairs: d_anchor in {0,1,3}, d_end in {0,1,2,3}, max sum 3), and a
    board-keyed basis would make the SAME pair read differently depending on which board is root --
    and 7 of the 19 undirected pairs render in both directions.

    NO REVISION-STAMP BLOCK: the card is date-typed under `knowledge_semantics: data_date` and
    carries no revision stamp, so the two returned print dates ARE the clock and both are named on
    the line. That is NOT a claim that the series is never revised -- the card records that the
    newer crosses were FILL-FORWARD BACKFILLED across the full history, which is precisely why the
    caller's ladder declines `replay` on a historical-asof turn before any read is paid.

    The magnitude is (last/first - 1) * 100 over the returned prints. NO RATE MULTIPLIES ANY PRICE
    ANYWHERE: this row is an observed rate on its own handle, and nothing converts anything."""
    r = fetch_window(qfn, table=_CW_FX_TABLE, metric=rec["metric"], commodity=None, country=None,
                     t1=t1, t2=t2, asof=asof, agg="series", period=None, period_type="date",
                     futures_newest_first=futures_newest_first)
    rec["reads"] = CW_FX_READS_PER_CELL                              # counted at the paying site
    if r.get("status") == "error":
        rec.update(status="declined", reason="read_error")
        return rec
    if r.get("status") != "ok":
        rec.update(status="declined", reason="empty_series")
        return rec
    vals, dates, unit = _rv_axes(r, card_metric)
    keep = [(v, d) for v, d in zip(vals, dates) if t1 <= d <= t2]    # belt: never a row outside the window
    if len(keep) < CW_FX_MIN_OBS:
        rec.update(status="declined", reason="grain_thin")
        return rec
    if not str(unit or "").strip():
        rec.update(status="declined", reason="no_unit")
        return rec
    first, last = keep[0][0], keep[-1][0]
    if not first:
        rec.update(status="declined", reason="no_move")
        return rec
    rec.update(status="closed", move_pct=round((last / first - 1.0) * 100.0, 4), n_obs=len(keep),
               first_date=keep[0][1], last_date=keep[-1][1], unit=str(unit))
    return rec


def _cw_fx_line(n: int, rec: dict) -> str:
    """ROW-1X: the class token right after the handle; the window token = SCOPE, the two returned
    print dates = the ONE clock (no as-of on this line). The reader LABEL is the series axis."""
    q = {"commodity": rec["label"], "country": None, "table": _CW_FX_TABLE}
    return (f"- [N{n}{CW_FX_TOKEN}{rec['label']} measured on the exchange-rate prints from "
            f"{rec['first_date']} through {rec['last_date']} inside the episode window "
            f"{rec['span']}: {rec['move_pct']:+g} %" + _series_tag(q))


def _cw_fx_words(rec: dict) -> str:
    """ROW-2X, PRICED: standalone, letters only. It states what the row is and what it is not."""
    return (f"{CW_FX_WORDS_PREFIX}{_cw_currency_words(rec['cur_a'])} and "
            f"{_cw_currency_words(rec['cur_b'])}: the row above is the exchange rate between those "
            f"two settlement currencies over the same window, carried as a dated fact on its own "
            f"handle; each board figure on this hop stays a move inside the currency its own row "
            f"names.")


def _cw_fx_words_unpriced(cur_a, cur_b) -> str:
    """ROW-2X, UNPRICED: the words ride FREE at zero reads whenever the FX cell did not close."""
    return (f"{CW_FX_WORDS_PREFIX}{_cw_currency_words(cur_a)} and {_cw_currency_words(cur_b)}: the "
            f"two boards on this hop settle in those currencies, and the rate between them is named "
            f"here in words only and is not priced on this page; each board figure stays a move "
            f"inside the currency its own row names.")


def _cw_fx_call(rec: dict, asof) -> dict:
    """The synthetic call the [N] handle indexes. THE UNIT IS BUILT FROM THE READER LABEL, never
    from `rec['unit']` (the card's own string): citations reads a call row's unit onto the RENDERED
    citation label and falls back to the CARD's unit when the row carries none, so an unset or
    card-shaped unit puts a raw provenance string in front of the reader. `_rv_call` hard-codes the
    pink-sheet table, so the table and the machine metric are overridden here -- the metric rides
    the ROW as `source_metric`, which citations.from_number copies onto the LOCATOR.

    THE PERIOD IS THE READ'S OWN FIRST..LAST PRINT DATES, not the firing window's month token, and
    that is the V2-3 K8 panel's own docket (engine label, one-liner). MEASURED on the arm: the writer
    wrote 'over 2025-12-31 to 2026-04-30' about this row while the row's `## Sources` label read
    '2025-12..2026-05 ... (latest available 2026-04-30; as-of 2026-07-31)' -- precision that was TRUE
    (they are the walk's own window bounds) but that the cited label did not carry, so it scored as
    an arm-attributable stop claim on both seats. Both dates already ride the ROW-1X line; this puts
    them on the LABEL, where a reader checking the citation meets them. The shape is the estate's own
    default -- `cascade._period_label` renders every ordinary windowed call as `t1..t2` at day grain
    -- so `citations._period_label` passes it through untouched (it carries '..') and the locator
    re-runs a span the reader can see. It is deliberately NOT the board rows' month token: those
    carry the month span BECAUSE that is what their own line shows the model, and this line shows
    the print dates."""
    call = _rv_call("exchange rate change", rec["label"], rec["move_pct"],
                    f"{rec['first_date']}..{rec['last_date']}", asof,
                    unit=_CW_FX_UNIT_FMT.format(unit=rec["label"]), date=rec["last_date"])
    call["query"]["table"] = _CW_FX_TABLE
    call["rows"][0]["source_metric"] = rec["metric"]
    return call


def _cw_board_row_closed(cells: list) -> bool:
    """The dormant-clause guard's predicate: does at least one BOARD cell close? A context cell is never
    the row that licenses a marker -- a block whose only magnitude is a chicken price ships NOTHING.
    V2-3: an FX row is never that row either -- an exchange rate is not a board."""
    return any(c.get("status") == "closed" and c.get("kind") not in ("context", "fx")
               for c in cells or [])


# THE MARKER PREFIX, minted ONCE and read by BOTH the producer (`_cw_marker`) and the answer-seam
# gate (`answer._cascade_walk_block_on`) -- the tl.LINE_PREFIX discipline: a persona MANDATE may
# ship only when the assembled volatile prompt actually carries a walk block (W4-D3's +10-
# hallucination lesson), and producer and gate cannot drift apart if they build from one string.
CW_MARKER_PREFIX = "CASCADE EPISODE WALK ("
# V2-5: minted ONCE from the prefix, so the producer's marker and answer.py's deep-mandate row gate
# build from ONE string and cannot drift. NOT a copied literal: the marker head is assembled by an
# f-string below, so the ASSEMBLED value appears nowhere in this file -- which is why its source pin
# is on the construction expression on the next line and never on the assembled string.
CW_THIRD_ORDER_MARKER = CW_MARKER_PREFIX + "third order)"


def _cw_marker(order: str, context: bool = False, fx: bool = False) -> str:
    """ROW 5 -- the fixed no-conclusion marker: the transcription discipline, the order label
    (K3), the episodes-sourcing clause (v3 remedy (h)) and its A6/M4 extension (one window, the
    same window, both surfaces). V2-1: with `context` the OPENING clause is conditional (a block
    carrying a CONTEXT row never states a universal it then retracts) and ONE sentence is appended --
    COUNT-FREE (review F1, 2026-09-02: the depth-in-time shape renders one context pair PER FIRING up
    to CW_CONTEXT_CAP, so the sentence names no row count; 'each' is per row);
    context=False is byte-identical to the pre-rider literal (pinned). The appended sentence's
    'a market the firing names' is LICENSED by the card itself: the mapped metric's desc names the
    slice as its consumer (chicken_usd_t: 'the demand-side output price behind broiler_economics';
    beef_usd_t: '... behind cattle_cycle_herd_size'), and check_cascade_context clause (c) pins that
    naming VERBATIM -- it is the one relation the block asserts, and the card asserts it first."""
    head = ("the [N] rows above are observed records on the same dated firing window, one series per row"
            if context else
            "the rows above are observed settle changes on the same dated firing window, one board per row")
    tail = (" Rows marked CONTEXT are monthly cash averages for a market the firing names, not board "
            "settle changes -- transcribe each with its own handle and read it against nothing."
            if context else "")
    # V2-5: ONE clause keyed on the THIRD-order label only, assembled after the main body and BEFORE
    # the context tail, so the first/second and context strings stay byte-for-byte the pinned
    # literals. It states the honest thing about a deeper ladder: the A6 interlock selected the
    # window for a THIRD market's episode, so each hop is a pairwise coincidence test on an exogenous
    # window -- a virtue (no cherry-picking) and NOT evidence of transmission along the chain.
    third = (" Each row above is a coincidence test between two boards over a window an unrelated "
             "market's episode defined; the chain across them is the reader's inference, never the "
             "engine's." if order == "third" else "")
    # V2-3: ONE COUNT-FREE sentence, appended LAST, only when an exchange-rate row actually rendered.
    # `fx=False` is byte-identical to both shipped literals (pinned).
    fxt = (" Rows marked EXCHANGE RATE are the rate between two settlement currencies over the same "
           "window -- transcribe each with its own handle, and never convert, rebase or net any "
           "board figure with it." if fx else "")
    return (f"{CW_MARKER_PREFIX}{order} order): {head}; each hop's read is stated beside "
            f"it, in-sample on the named window only. Cite the [N] rows verbatim; never derive a "
            f"ratio, a spread, a lag or any magnitude the rows do not print; direction beyond the "
            f"stated read is the analyst's, never the engine's. Do not mint a new episodes-section "
            f"bullet from a consequence row -- the enumeration stays the episodes mandate's, and "
            f"the firing window named here is the same dated window that section enumerates."
            + third + tail + fxt)


_CW_SPAN_TOKEN_RX = re.compile(r"\d{4}-\d{2}\.\.\d{4}-\d{2}")


def _cw_register_fence(lines: list) -> bool:
    """The `_xmit_register_fence` shape (atomic, whole-block, rows rolled back by the caller) PLUS
    the walk's two scans: every digit-bearing line is a ROW-1 cell template (K5 -- zero counts,
    zero lag numerals, zero date glyphs anywhere else), and every ROW-1 line carries exactly ONE
    dated window token (one clock per line)."""
    from leviathan.graphrag import register as reg
    for ln in lines or []:
        if not (pace_register_ok(ln) and reg.count_valuation_words(ln) == 0
                and reg.count_flow_words(ln) == 0):
            return False
        if ln.startswith("- [N"):
            if len(_CW_SPAN_TOKEN_RX.findall(ln)) != 1:
                return False
        elif any(ch.isdigit() for ch in ln):
            return False
    return True


def _cw_free(cov, slug: str, firing: dict) -> bool:
    """V2-5, THE ONE FREE TEST -- there is no second predicate anywhere in this leg. A leg whose
    board history starts AFTER the firing start is declined `pre_coverage` inside the render loop for
    ZERO reads; this is that same string comparison, hoisted so the PLAN can know it before any read.
    Outcome-independent and knowable before any read (MAJOR-5 clean)."""
    return str(cov[slug]) > str(firing["start"])


def _cw_admissible_children(graph, cov, node, root: str, *, xccy: bool = False) -> tuple:
    """The HOP-1 ladder, lifted VERBATIM out of `_cascade_walk_legs` so config_check clause (ix) can
    census the engine's OWN out-degree instead of a second implementation that can drift.

    Returns `(admissible, declines, root_decline)`, where `root_decline` is None,
    'focus_not_node_seed' or 'no_declared_children' -- the THIRD return arm carries the two root-scope
    returns that live inside the lifted range. `node` is `graph.contract_node`, BOUND AT THE CALL SITE
    (refute-v4 major-0: it used to be assigned inside this range and is still needed after it).
    `declines` is the child-scope decline list in the SAME order the shipped loop appended it.

    V2-3: `xccy` LIFTS the currency gate into a LADDER whose ORDER IS LOAD-BEARING (v1 refute F1).
    With `xccy` False the gate is the pre-rider two lines, byte for byte, at zero reads. With it
    True: cash-index FIRST (both cash-index boards are BRL and BRL has no FX column, so an
    FX-first order makes that branch dead code and mis-buckets two hops -- 7/0 wrong, 5/2 right),
    then the FX column, then ADMIT carrying `xccy=(cur_root, cur_child)` and `fx=<card metric>` on
    the record. EVERY BRANCH IS PRE-READ. `cross_currency` is RE-SCOPED, never deleted: it stays
    the flag-off reason and stays true for any future board whose currency has no column."""
    declines: list = []

    def _dec(reason, child):
        declines.append({"scope": "child", "reason": reason, "child": child})

    rows = [r for r in (graph.rev_cross_links(root) if graph is not None else [])]
    if rows and any(str(r.get("seed")) != root for r in rows):
        # graph.py files every row of a node under ONE canonical seed, so this is all-or-nothing:
        # a covered non-canonical focus must DECLINE, never silently walk another contract's edges.
        return [], declines, "focus_not_node_seed"
    if not rows:
        return [], declines, "no_declared_children"
    # ── children: A1 union (the graph's declaration IS the admission), gated BEFORE any read ──
    by_child: dict = {}
    for r in rows:
        by_child.setdefault(str(r.get("contract")), []).append(r)
    admissible: list = []
    for child in sorted(by_child):
        crows = by_child[child]
        if child not in cov:
            _dec("child_uncovered", child)
            continue
        if node(child) == node(root):
            _dec("node_cycle", child)
            continue
        cur_r, cur_c = _cw_currency(root), _cw_currency(child)
        _x, _fx = None, None
        if cur_r != cur_c:
            if not xccy:
                _dec("cross_currency", child)          # the pre-rider bytes, exactly, zero reads
                continue
            if _cw_cash_index(child) or _cw_cash_index(root):
                _dec("cash_index_board", child)        # FIRST: see the docstring's ordering law
                continue
            _fx = _cw_fx_metric(cur_r, cur_c)
            if _fx is None:
                _dec(("cross_currency_unmapped" if not (cur_r and cur_c)
                      else "cross_currency_no_pair_rate"), child)
                continue
            _x = (cur_r, cur_c)
        signs = {str(r.get("sign")) for r in crows}
        if signs - {"+", "-"}:
            _dec(("sign_undeclared" if signs <= {"0", "None", ""} else
                  "sign_not_unanimous"), child)
            continue
        if len(signs) != 1:
            _dec("sign_not_unanimous", child)
            continue
        if any(_cw_min_lag_quarters(r.get("lag")) != 0 for r in crows):
            _dec("lag_gate", child)
            continue
        rels = sorted({str(r.get("relation")) for r in crows})
        if any(rel not in _CW_RELATION_WORDS for rel in rels):
            _dec("relation_unmapped", child)
            continue
        blurbs = sorted({str(r.get("blurb") or "").strip() for r in crows} - {""})
        if len(blurbs) > 1:
            _dec("blurb_not_unanimous", child)
            continue
        if child not in _CW_BOARD_LABEL:
            _dec("child_uncovered", child)
            continue
        admissible.append({"child": child, "sign": signs.pop(), "relations": rels,
                           "blurb": (blurbs[0] if blurbs else ""), "xccy": _x, "fx": _fx})
    return admissible, declines, None


def _cw_next_hop(graph, cov, node, keep, narrated, parent: str, path_nodes: set, payload: dict, *,
                 level: str = "grand", verbose: bool = False):
    """The NEXT-HOP ladder, lifted VERBATIM out of `_cascade_walk_legs` and generalised over the path
    so ONE implementation serves hop 2 and hop 3. Returns the qualifying hop dict
    {child, sign, relations, blurb, parent} or None.

    IT TAKES `payload` AS THE DECLINE SINK so the off-path byte-identity claim is achievable rather
    than argued: ON THE HOP-2 CALL (`level` 'grand' -- the only call the off path makes) it appends
    EXACTLY the dict the shipped loop appends, {"scope": "child", "reason":
    "composer_narrated_pair", "child": g2}, scope 'child' VERBATIM (the shipped quirk, preserved not
    tidied), in the same iteration order and nothing else. ON THE HOP-3 CALL -- new code, reachable
    only under deep -- the same decline carries scope 'great', because a GREAT candidate was never a
    child and the child-scope census must stay a child-scope census (build-refute minor).
    Under `verbose` (deep only) it ALSO records the per-candidate rejections
    in payload['deep']['hop_candidates'] as {level, child, reason} over _CW_HOP_CANDIDATE_REASONS --
    NEVER in payload['declines'], so the decline census stays comparable across regimes.

    The node-distinctness test generalises from `len({node(root), node(child), node(g2)}) == 3` to
    `len(path_nodes | {node(g2)}) == len(path_nodes) + 1`: the same test with the same result on the
    three-node call, and the right test on the four-node one."""
    def _cand(child, reason):
        if verbose:
            payload["deep"]["hop_candidates"].append({"level": level, "child": child,
                                                      "reason": reason})

    g_rows: dict = {}
    for r2 in (graph.rev_cross_links(parent) if graph is not None else []):
        if str(r2.get("seed")) == parent:
            g_rows.setdefault(str(r2.get("contract")), []).append(r2)
    for g2 in sorted(g_rows):                         # ascending id, first QUALIFYING group wins
        rows2 = g_rows[g2]
        # the SAME per-pair unanimity ladder hop 1 runs (review minor: a first-row-wins read
        # here could mint a verdict off a declaration hop 1 would refuse as non-unanimous)
        signs2 = {str(r.get("sign")) for r in rows2}
        rels2 = sorted({str(r.get("relation")) for r in rows2})
        blurbs2 = sorted({str(r.get("blurb") or "").strip() for r in rows2} - {""})
        if frozenset((parent, g2)) in narrated:
            # review D8: the grandchild hop was the ONE pair-narrating surface the K3 check
            # missed -- and the sole live second-order shape IS the fork's own crush pair.
            # THE SCOPE IS THE LEVEL, and 'grand' keeps the shipped quirk's word 'child': the
            # hop-2 call is the only one the off path makes, so this expression is byte-identical
            # off, while the hop-3 call stops filing GREAT candidates under child scope.
            payload["declines"].append({"scope": ("child" if level == "grand" else level),
                                        "reason": "composer_narrated_pair", "child": g2})
            continue
        # THE SAME `and` chain, decomposed into named tests in the SAME ORDER with the SAME
        # disjunction, so the RETURN value is unchanged and the nine names become recordable.
        if g2 not in keep:
            _cand(g2, "not_kept_subgraph")
            continue
        if g2 not in cov or g2 not in _CW_BOARD_LABEL:
            _cand(g2, "child_uncovered")
            continue
        if not (signs2 <= {"+", "-"}):
            _cand(g2, ("sign_undeclared" if signs2 <= {"0", "None", ""} else "sign_not_unanimous"))
            continue
        if len(signs2) != 1:
            _cand(g2, "sign_not_unanimous")
            continue
        if not all(_cw_min_lag_quarters(r.get("lag")) == 0 for r in rows2):
            _cand(g2, "lag_gate")
            continue
        if not all(rel in _CW_RELATION_WORDS for rel in rels2):
            _cand(g2, "relation_unmapped")
            continue
        if len(blurbs2) > 1:
            _cand(g2, "blurb_not_unanimous")
            continue
        if _cw_currency(g2) != _cw_currency(parent):
            _cand(g2, "cross_currency")
            continue
        if len(path_nodes | {node(g2)}) != len(path_nodes) + 1:
            _cand(g2, "node_cycle")
            continue
        return {"child": g2, "sign": sorted(signs2)[0], "relations": rels2,
                "blurb": (blurbs2[0] if blurbs2 else ""), "parent": parent}
    return None


def _cw_order_n(root: str, rendered_pairs, closed) -> int:
    """V2-5 THE ORDER NUMBER -- the ONE expression, lifted so the engine and its pin read the SAME
    lines (build-review minor: a test that re-implements both formulas proves them equal to each
    other and to nothing in the engine).

    DEPTH IN EDGES, NEVER IN NODES: a breadth turn with two children rendered FROM THE ROOT is depth
    2 by node count and FIRST order by hop count.

    AND IT WALKS THE CHAIN OF **CLOSED** CELLS, NOT THE RENDERED HEADERS (build-refute major B4,
    MEASURED: a chain whose CHILD cell declined `no_tape_rows` under a priced grand and great still
    read 'third order', shipped the third-order marker, and so shipped the deep mandate -- which
    instructs the writer to state each hop 'with its own handle and its own read as printed' when
    hop 1 printed an absence line and nothing else. That is precisely the class-(a) gloss surface
    the mandate exists to close, made louder by depth.) A HOLE anywhere in the chain -- a declined
    cell, a free pre_coverage absence -- caps the label at the last CLOSED hop, because a hop with
    no printed read is a hop the reader cannot check. `closed` is the set of slugs whose cell closed
    (context cells are never in it: a context row is not a hop).

    The root seeds `depth` at 1 whether or not it closed on a given firing -- no pair can render
    under a declined root anyway, so the seed is a floor, not a claim."""
    depth = {root: 1}
    for (p, c) in rendered_pairs:
        if p in depth and c in closed:
            depth[c] = max(depth.get(c, 0), depth[p] + 1)
    return max(1, max(depth.values()) - 1)


def _cascade_walk_legs(sg, graph, walk_request: dict, qfn, asof, calls: list, base: int, *,
                       futures_newest_first: bool | str = False) -> tuple:
    """The leg proper. Returns `(lines, payload)` -- payload ALWAYS a dict once the leg ran (the
    J4 precedent: `outcome` in {fired, declined, fenced}; an ABSENT trace key means the leg did
    not run, never that it declined). NEVER raises past the wrapper's belt.

    THE DEEP-VS-WIDE RULE (refute-v3 major-3, resolved deterministically, outcome-independent):
    more than one admissible child -> BREADTH at the single most recent firing (up to
    CW_MAX_CHILDREN cells + the root); exactly one child WITH an admissible grandchild ->
    depth-in-graph at one firing (three cells, SECOND ORDER); exactly one child, no grandchild ->
    depth-in-time (two firings, two cells each). Every shape prices <= CW_CAP reads."""
    payload: dict = {"outcome": "declined", "root": None, "order": "first", "path": [],
                     "firings": [], "cells": [], "declines": [],
                     "children_declared": 0, "children_priced": 0, "children_named": 0,
                     "grounded_tree_slices": [], "net_reads": 0}

    def _decline(scope, reason, **kw):
        payload["declines"].append(dict({"scope": scope, "reason": reason}, **kw))
        if scope == "root":
            _deep_stamp_hops()                        # V2-5 (refute-v4 fatal 2): EVERY root-scope
        return [], payload                            # decline carries a closed rectangle

    root = str((walk_request or {}).get("focus_contract") or "")
    # V2-1 rider: the flag is read at the answer.py seam and threaded INSIDE the request dict (never
    # here); `replay` is the SAME already-resolved historical-asof bool the seam built as _pr_kw.
    context_on = bool((walk_request or {}).get("context"))
    replay_on = bool((walk_request or {}).get("replay"))
    # -- V2-5 DEEP REGIME, selected ONCE and read as LOCALS everywhere below. The union with V2-3's
    #    `xccy` is minted NOW so V2-3 lands one seam key instead of re-cutting four selection lines;
    #    nothing sets `xccy` in this build (pinned at the answer.py seam), so the union is measurably
    #    inert and the flag-off path is the shipped path on the shipped globals.
    # V2-3 CROSS-CURRENCY RIDER: its own bool, read from the SAME request dict. `xccy_on` gates the
    # currency ladder, the FX cell, the currency words and the seam clause; `deep_on` gates the
    # breadth/cap regime -- and THE ENGINE ITSELF enforces xccy => deep on the line below (v3 refute
    # major-3: the implication used to live only at the answer.py seam, so any request built without
    # that seam -- a unit fixture, a future caller -- would have run the rider at CW_MAX_CHILDREN=3
    # and silently dropped lifted children with no decline naming the loss).
    xccy_on = bool((walk_request or {}).get("xccy"))
    deep_on = bool((walk_request or {}).get("deep") or (walk_request or {}).get("xccy"))
    cw_children = CW_DEEP_MAX_CHILDREN if deep_on else CW_MAX_CHILDREN
    cw_cap = CW_DEEP_CAP if deep_on else CW_CAP
    cw_ceiling = CW_DEEP_TURN_CEILING if deep_on else CW_TURN_CEILING
    cw_order_max = CW_DEEP_MAX_ORDER if deep_on else 2
    cw_free_allow = CW_FREE_ALLOWANCE     # build-refute minor: the width belt is the ONE budget that
    #                                       read a MODULE GLOBAL where every other reads a regime
    #                                       LOCAL selected here. Not regime-split today (the belt is
    #                                       deep-only), but the pattern is the law, so it is a local.
    # every name the stamp closure reads must exist before the FIRST root-scope decline below.
    # V2-3 (L9): the two next-hop legs are collected in ONE DICT keyed by the _CW_HOP_LEVELS
    # vocabulary, so the ledger stamp's zip and the render loop's absent-dispatch both READ that
    # dict instead of re-spelling 'grand'/'great' at two more sites.
    hop_legs: dict = {L: None for L in _CW_HOP_LEVELS}
    free_set: set = set()
    admissible: list = []
    same_ccy: list = []
    if deep_on:                                       # omit-when-off (the payload['context']
        payload["deep"] = {"cap": cw_cap, "ceiling": cw_ceiling,   # precedent): NO new key ever
                           "max_children": cw_children,            # appears in an off-run payload
                           "max_order": cw_order_max,
                           "free_allowance": cw_free_allow,
                           "reads_per_cell": CW_READS_PER_CELL,   # so the arm's PLAN bar
                           #                   (cells_planned x this) needs no second copy of the
                           #                   constant in eval.py -- L3 / refute-v4 fatal 3
                           "cells_planned": None, "paid_cells": None,   # every PRE-enumeration plan
                           "order_n": None,             # field is None, never 0. elapsed_ms is the
                           # V2-3 (L9): the depth the PAGE SHOWED, beside the depth the closed
                           # cells earned -- `order_n` walks CLOSED cells only, so a hole caps it,
                           # and an arm comparing cw_order across regimes needs both numbers.
                           "order_n_rendered": None,
                           "elapsed_ms": None,          # ONE NONDETERMINISTIC FIELD in this payload
                           #                   (a wall clock, stamped by the wrapper): EXCLUDE IT
                           #                   from every byte comparison of a flag-ON artifact --
                           #                   no two runs of the same turn agree on it.
                           "hops": {L: {"declared": 0, "priced": 0, "named": 0, "free": 0,
                                        "absent": 0}
                                    for L in ("child",) + _CW_HOP_LEVELS},
                           "hop_candidates": []}

    def _deep_stamp_hops(priced=()):
        """L2 / refute-v4 fatal 2: the per-level rectangle is stamped at EVERY early return, not only
        at the end of the render loop -- otherwise a root-scope decline with k free children reads
        {declared 0, priced 0, named 0, free k} and the invariant `declared == priced + named + free`
        is FALSE (0 == k) on exactly the states the counters exist to describe. The hop-1 row mirrors
        the shipped ledger by construction; grand/great are NAMED when they were declared and never
        rendered (declared - free, priced 0). `absent` counts RENDERED cells only, so it is 0 on every
        pre-render return -- which is why `declared == priced + named + free + absent` also holds
        there."""
        if not deep_on:
            return
        hops = payload["deep"]["hops"]
        kids = {a["child"] for a in admissible}
        hops["child"].update(declared=payload["children_declared"],
                             priced=payload["children_priced"],
                             named=payload["children_named"],
                             free=len(free_set & kids))
        for lvl in _CW_HOP_LEVELS:                # the vocabulary, never a re-spelling (V2-3 L9:
            leg = hop_legs[lvl]                   # ONE collection, read by key)
            row = hops[lvl]
            dec = 1 if leg is not None else 0
            fre = 1 if (leg is not None and leg["child"] in free_set) else 0
            pri = 1 if (leg is not None and leg["child"] in priced) else 0
            # a FREE leg can never be priced (it declines pre_coverage on every selected firing),
            # so `dec - fre - pri` is never negative and the rectangle is exact, never clamped.
            row.update(declared=dec, priced=pri, named=dec - fre - pri, free=fre)

    def _name_unpriced_children():
        """K2 (review D5) under both regimes: a root-scope decline AFTER enumeration NAMES the
        children, never loses them -- and under the deep regime a FREE child is rendered-not-priced,
        so it is counted `free`, never `named`. free_set is EMPTY with the flag off, so this is
        `payload["children_named"] += len(admissible)` arithmetic for arithmetic."""
        payload["children_named"] += len(admissible) - len(free_set
                                                           & {a["child"] for a in admissible})

    if context_on:                                    # omit-when-off: stamped ONLY under the rider,
        payload["context"] = {"planned": None, "admitted": 0, "rendered": 0, "reads": 0,  # and EARLY,
                              "cap": CW_CONTEXT_CAP, "board_reads_planned": None,         # so a root-
                              "declines": [], "slices": None}                             # scope decline
    #                                                   carries the ledger. planned/slices stay None
    #                                                   until the firing enumeration has happened
    #                                                   (review F2: a PRE-enumeration decline never
    #                                                   says "zero were planned"), board_reads_planned
    #                                                   until the board plan exists -- absent is
    #                                                   never zero.
    if xccy_on:                                       # V2-3: the SAME omit-when-off shape, stamped
        payload["xccy"] = {"rendered": 0, "pairs": [], "fx_planned": 0,   # EARLY so a root-scope
                           "fx_admitted": 0, "fx_rendered": 0,           # decline still carries a
                           "fx_reads": 0, "fx_cache_hits": 0,            # closed rectangle.
                           "fx_flips_sign": 0, "fx_unpriced_verdicts": 0,
                           "fx_gate_checked": 0,     # K0c's DENOMINATOR: hops that passed BOTH
                           #                           board fences AND held a closed FX cell, i.e.
                           #                           the hops on which the flip test actually ran
                           "cap": CW_FX_CAP, "declines": []}
    payload["root"] = root or None
    if not root:
        return _decline("root", "no_focus")
    try:
        from leviathan.silver import futures_eod_contracts as FC
        cov = FC.PRICE_COVERAGE_START
    except Exception:  # noqa: BLE001
        return _decline("root", "error")
    if root not in cov and graph is not None and graph.contract_node(root) == root:
        # THE BASE-CONTRACT FOCUS (sitting-3 arm finding, 2026-09-02): the focus-first seed on two
        # corn rows was the BASE yaml contract `corn` -- a loaded contract NAMED AS ITS OWN NODE,
        # uncovered, that duplicates its priced twin's declarations (every rev row is seeded
        # corn_cbot). It is the node's own twin, not another board, so the walk re-roots on the
        # node's canonical PRICED seed. This is NOT the alias-collapse class the seed gate below
        # refuses (french_maize_matif is a different board on a different currency and is not
        # named as its node) -- the `contract_node(root) == root` test is exactly that boundary.
        seeds = {str(r.get("seed")) for r in graph.rev_cross_links(root)}
        if len(seeds) == 1 and next(iter(seeds)) in cov:
            payload["focus_base_contract"] = root
            root = next(iter(seeds))
            payload["root"] = root
    if root not in cov:
        return _decline("root", "root_uncovered")
    if root not in _CW_BOARD_LABEL:
        # review D1 (reproduced KeyError on hard_red_spring_wheat_mgex before its label landed):
        # an unlabeled root DECLINES with a name, zero reads -- never an error payload.
        return _decline("root", "root_unlabeled")
    # ── children: A1 union (the graph's declaration IS the admission), gated BEFORE any read ──
    # `node` is bound HERE, at the call site, because the ladder needs it and so does every hop below
    # (refute-v4 major-0). `graph is None` is reachable -- it declines `no_declared_children` inside
    # the helper on empty rows -- so the binding is guarded rather than assumed.
    node = graph.contract_node if graph is not None else None
    admissible, _adm_decl, _root_decl = _cw_admissible_children(graph, cov, node, root,
                                                                xccy=xccy_on)
    if _root_decl is not None:
        return _decline("root", _root_decl)
    payload["declines"].extend(_adm_decl)
    payload["children_declared"] = len(admissible)
    if not admissible:
        payload["outcome"] = "declined"
        _deep_stamp_hops()
        return [], payload
    narrated = _cw_narrated_pairs(sg)
    kept_admissible = []
    for a in admissible:
        if frozenset((root, a["child"])) in narrated:
            _decline("child", "composer_narrated_pair", child=a["child"])
            payload["children_named"] += 1
        else:
            kept_admissible.append(a)
    admissible = kept_admissible
    if not admissible:
        payload["outcome"] = "declined"
        _deep_stamp_hops()
        return [], payload
    if not deep_on:
        # THE SHIPPED WIDTH TRUNCATION, byte-verbatim and in its shipped POSITION (above the firing
        # enumeration), so payload['declines'] keeps its exact order off. Under deep the selection
        # moves below the shape switch, where `firings` is final and the free set can be built.
        named_budget = admissible[CW_MAX_CHILDREN:]
        admissible = admissible[:CW_MAX_CHILDREN]
        for a in named_budget:
            _decline("child", "child_not_priced_budget", child=a["child"])
            payload["children_named"] += 1
    # ── firings (A6) ──
    firings, grounded = _cw_firings(sg, graph, root, str(cov[root]))
    payload["grounded_tree_slices"] = grounded
    if not firings:
        # THE ONE BELT THAT PRECEDES THE DEEP SELECTION: under deep it names the UNTRUNCATED set and
        # off the truncated-plus-already-named set -- the SAME children and the SAME total -- and
        # free is 0 here because no firing exists to classify a leg against.
        _name_unpriced_children()
        return _decline("root", "no_firing_window")
    # ── the deep-vs-wide shape (deterministic; see the docstring) ──
    # THE SWITCH READS THE SAME-CURRENCY ADMISSIBLE COUNT, NOT len(admissible) -- V2-3's law, minted
    # here so V2-3 inherits it rather than re-deciding it. Byte-identical TODAY in both regimes: the
    # hop-1 ladder declines every cross-currency child before `admissible.append`, so
    # same_ccy_n == len(admissible) by construction. When V2-3 starts admitting FX children, this
    # keeps the switch's MEANING (an FX rider must not silently flip a breadth turn into a depth one).
    same_ccy_n = sum(1 for a in admissible if _cw_currency(a["child"]) == _cw_currency(root))
    if same_ccy_n == 1:
        # THE DEPTH CHILD IS THE UNIQUE SAME-CURRENCY MEMBER, never the list's first element
        # (refute-v4 major-2): today they are the same element, and this is the seam V2-3 inherits --
        # with FX children admitted, the first member could be an FX board while the chain must run
        # off the same-currency one. SHAPE 2's paid_cells is stated over len(admissible) for exactly
        # the same reason: the render loop prices every admissible child plus grand plus great.
        child = next(a["child"] for a in admissible
                     if _cw_currency(a["child"]) == _cw_currency(root))
        keep = _cw_kept_contracts(sg)
        # THE DEPTH BOUND IS THIS LOOP (build-review minor: cw_order_max used to be read only to
        # stamp payload['deep']['max_order'] while the real bound was "there are two hand-written
        # calls"). `cw_order_max - 1` next-hop calls -- ONE off (order max 2: the shipped single
        # 'grand' call at verbose=deep_on, byte for byte) and TWO under deep -- capped at the
        # _CW_HOP_LEVELS vocabulary, which is the set of ledger levels that exist. Each miss is
        # NAMED AND COUNTED at its own level and the walk stops there: the hop-2 miss used to record
        # NOTHING while the symmetric hop-3 miss was named, which made eval's cw_hop2_declines
        # structurally always [] -- an unfalsifiable arm column (build-refute major-3). Zero reads:
        # every test in the ladder is a graph read.
        _hop_parent, _hop_path = child, {node(root), node(child)}
        for _hop_i in range(min(max(0, cw_order_max - 1), len(_CW_HOP_LEVELS))):
            _lvl = _CW_HOP_LEVELS[_hop_i]
            _hop = _cw_next_hop(graph, cov, node, keep, narrated, _hop_parent, _hop_path, payload,
                                level=_lvl, verbose=deep_on)
            hop_legs[_lvl] = _hop                     # V2-3 L9: ONE dispatch, keyed by the level
            if _hop is None:
                if deep_on:
                    _decline(_lvl, "no_next_hop")     # append side-effect only (the :6772 idiom)
                break                                 # off: no decline, no second call -- as shipped
            # the SAME ladder once more, seeded at the hop just found, under exactly the same gates
            # -- including node-distinctness across the WHOLE path (four distinct nodes at hop 3).
            _hop_parent = _hop["child"]
            _hop_path = _hop_path | {node(_hop_parent)}
    # THE ONE-FIRING RULE, V2-3-CORRECTED (build-refute major-2, MEASURED): the depth-in-time shape
    # exists ONLY for the root whose spine is a SINGLE same-currency child, so the test is `!= 1`,
    # never `> 1`. `same_ccy_n == 0` was structurally unreachable before the rider (the hop-1 ladder
    # declined every cross-currency child, so the count equalled len(admissible) and an empty
    # admissible set had already returned); with lifted children admitted it is LIVE -- a root whose
    # only children are lifted (rapeseed_meal_zce, french_wheat_matif today) fell through to two
    # firings, and on firing 2 the per-firing legs are `same_ccy` == [], so the engine paid a second
    # root cell and rendered a bare ROW-1 that no hop, read or absence ever referred to.
    if same_ccy_n != 1 or hop_legs["grand"] is not None:
        firings = firings[:1]
    else:
        firings = firings[:CW_MAX_FIRINGS]
    payload["firings"] = [{"span": f["span"], "slice": f["slice"], "start": f["start"],
                           "end": f["end"], "span_days": f["span_days"],
                           "node_token": f.get("node_token")} for f in firings]
    if deep_on:
        # ── V2-5: THE FREE SET, THEN THE PAID-CELL SELECTION ────────────────────────────────────
        # ONE predicate (_cw_free), ONE aggregation, over ALL legs at EVERY level -- children, grand
        # and great together -- which is what makes a free hop-3 cell expressible at all. A leg is
        # FREE FOR THE WALK iff `_cw_free` holds on EVERY selected firing. THE DIRECTION THAT COSTS:
        # a child free on ONE of two firings is NOT free, so it books a paid cell on both even though
        # the render loop spends nothing on the firing where it is free. That OVER-reserves at most
        # CW_READS_PER_CELL on the depth-in-time shape and can never over-spend; paid_cells is a
        # PLAN, payload['net_reads'] stays the honest spend. THE ROOT IS NEVER FREE by construction
        # (firings are enumerated against the root's own coverage), so no predicate is needed for it.
        # THERE IS NO TRANSITIVE RULE: on the shipped graph the coverage floors are non-decreasing
        # down the only chain, so a free ancestor implies every descendant free (refute-v4 major-1)
        # and the rule would only have deleted declared absence rows.
        _legs_all = ([{"child": a["child"], "parent": root} for a in admissible]
                     + [L for L in (hop_legs[k] for k in _CW_HOP_LEVELS) if L is not None])
        free_set = {L["child"] for L in _legs_all
                    if all(_cw_free(cov, L["child"], f) for f in firings)}
        # THE PAID-CELL SELECTION, in the existing ascending-slug order, one pass. A FREE child rides
        # without booking a cell -- the whole point of the rule is that paid slots stop being spent
        # on absences. A dropped child is POPPED from `admissible` (`admissible = kept`), so
        # cells_planned really falls and the belts cannot double-count it.
        kept, dropped, paid_n = [], [], 0
        for a in admissible:
            if a["child"] in free_set:
                kept.append(a)
            elif paid_n < cw_children:
                kept.append(a)
                paid_n += 1
            else:
                dropped.append(a)
        for a in dropped:
            _decline("child", "child_not_priced_budget", child=a["child"])
            payload["children_named"] += 1
        # THE ONE RUNTIME WIDTH BELT (refute-v4 major-3). Free children ride OUTSIDE the paid budget,
        # so rendered width = |free kept| + |paid kept| has no fail-closed bound of its own; clause
        # (ix) is a CI lint and configs/graphrag is gitignored and rides the image tar, so a curation
        # edit can mint an extra child on a serving image the lint never ran against. The excess --
        # lowest-ranked, i.e. last in ascending-slug order -- is declined BY NAME and counted.
        # Unreachable on the shipped graph (measured max out-degree 4 << 6 + 2). IT BOUNDS THE TOTAL
        # RENDERED WIDTH at `cw_children + cw_free_allow`, and does NOT count the free riders
        # separately -- so the allowance is headroom on the total, exactly as CW_FREE_ALLOWANCE now
        # says. BOTH terms are regime LOCALS (build-refute minor: this was the one belt reading a
        # module global).
        _over = len(kept) - (cw_children + cw_free_allow)
        if _over > 0:
            belted, kept = kept[-_over:], kept[:-_over]
            for a in belted:
                _decline("child", "width_belt", child=a["child"])
                payload["children_named"] += 1
        admissible = kept
    # V2-3 (L5), THE PER-FIRING LEGS SOURCE: the LIFTED (cross-currency) children ride the depth
    # shape's FIRST firing; the same-currency spine, and its next hops when there are any, ride
    # EVERY firing. MEASURED as the only configuration with zero same-currency loss, zero next-hop
    # loss AND zero second-firing loss -- 'ride every firing' re-creates the very second-firing loss
    # the switch exists to stop, and 'decline by name' costs two reachable-today lifted hops. The
    # switch itself already reads the SAME-CURRENCY COUNT (V2-5 minted `same_ccy_n` for exactly this
    # inheritance); this is the same predicate as a LIST, taken AFTER the paid-cell selection so it
    # names the children that actually survived. Flag-off and xccy-off it EQUALS `admissible`
    # element for element in the same order (every record carries xccy None), so both the plan and
    # the render loop reduce to the shipped expressions.
    same_ccy = [a for a in admissible if not a.get("xccy")]
    # ONE POPULATION FOR BOTH READERS (build-review minor, adopted): the shape switch above runs
    # BEFORE the paid-cell selection -- it has to, because `free_set` is defined over the SELECTED
    # firings -- so it reads the PRE-belt count while the per-firing legs read this POST-belt list.
    # THE POPULATION THAT DECIDES THE SHAPE IS THIS ONE, `same_ccy`: the switch's verdict is re-taken
    # here against the children that actually survived the paid-cell selection and the width belt,
    # under the SAME predicate (`!= 1`), and the stamped plan is truncated with it so the artifact
    # and the render loop can never disagree about how many firings ran. Xccy-off it is INERT --
    # `same_ccy` is `admissible`, and two firings imply a single admissible child that no budget can
    # drop -- so the deep golden does not move. Nothing downstream of this line has read `firings`
    # yet (the context plan, the ceiling test and `paid_cells` all follow).
    if len(firings) > 1 and len(same_ccy) != 1:
        firings = firings[:1]
        payload["firings"] = payload["firings"][:1]
    if context_on:
        # V2-1 (review F2): the context PLAN is stamped from the enumeration the moment it exists --
        # BEFORE the ceiling tests -- so a root-scope decline below can never report "zero were
        # planned" about a mapped firing it lost; on such a decline every mapped firing is recorded
        # as root_declined, so the ledger's rectangle (planned == rendered + declines) still closes.
        payload["context"]["slices"] = [f["slice"] for f in firings if f["slice"] in _CW_CONTEXT_SERIES]
        payload["context"]["planned"] = len(payload["context"]["slices"])

    def _ctx_root_declined():
        if context_on:
            for f in firings:
                if f["slice"] in _CW_CONTEXT_SERIES:
                    payload["context"]["declines"].append({"slice": f["slice"], "span": f["span"],
                                                           "reason": "root_declined"})
    # ── the turn ceiling, MEASURED, before any read (A2/K7) ──
    spent = _cw_turn_spent(sg)
    payload["turn_spent_before"] = spent
    if spent is None:
        _name_unpriced_children()
        _ctx_root_declined()
        return _decline("root", "turn_spend_unknown")
    if deep_on:
        # THE PAID PLAN, WRITTEN OUT: one root cell per firing, plus every KEPT child that is not
        # free, plus the grand and the great when they exist and are not free. grand/great exist only
        # on the one-firing shape, so the per-firing sum is exact on all three shapes. Stated over
        # len(admissible) -- SHAPE 2 prices 1 + |admissible| + grand + great, which is 4 today and
        # stays correct the day V2-3 admits an FX sibling beside the depth child.
        paid_cells = sum((1
                          + sum(1 for a in (admissible if _fi == 0 else same_ccy)
                                if a["child"] not in free_set)
                          + sum(1 for k in _CW_HOP_LEVELS
                                if hop_legs[k] is not None
                                and hop_legs[k]["child"] not in free_set))
                         for _fi, _f in enumerate(firings))
        cells_planned = paid_cells
        payload["deep"]["cells_planned"] = cells_planned
        payload["deep"]["paid_cells"] = paid_cells
    else:
        cells_planned = sum(1 + len(admissible)
                            + (1 if hop_legs["grand"] is not None else 0) for _ in firings)
    if cells_planned * CW_READS_PER_CELL > cw_cap:
        # the review's belt: the shape rules above keep every plan at or under the cap today, so
        # this is unreachable -- until a future knob change; then it DECLINES, never over-spends.
        _name_unpriced_children()
        _ctx_root_declined()
        return _decline("root", "cap")
    if spent + cells_planned * CW_READS_PER_CELL > cw_ceiling:
        _name_unpriced_children()
        _ctx_root_declined()
        return _decline("root", "turn_budget_spent")
    # V2-1 SUBORDINATE ADMISSION (F2 as adjudicated): the board test above keeps its bytes; a context
    # cell spends only SLACK -- admitted per firing iff spent + board_reads + admitted + 1 <=
    # CW_TURN_CEILING, else the CELL declines budget_cap and the block ships. board_reads is the PLAN
    # (outcome-independent, known before any read -- MAJOR-5 clean) and is stamped (refute m6) so a
    # budget_cap decline is auditable from the artifact without re-deriving the shape.
    # THE 60-vs-80 ASYMMETRY IS GONE (build-refute minor + build-review minor, both adopted): the
    # slack test now reads THE REGIME'S OWN CEILING, `cw_ceiling` -- 80 under deep/xccy, 60 off --
    # the same number the board plan was admitted against two lines up. It read the bare 60 in both
    # regimes, which made the 7 reads CW_DEEP_TURN_CEILING reserves for the riders inside 80
    # (44 pre-walk + CW_DEEP_CAP 27 + CW_CONTEXT_CAP 2 + 7) STRUCTURALLY UNREACHABLE: a wide deep
    # plan starved every rider cell as budget_cap while config_check's NOTE said otherwise. V2-3
    # makes the deep regime the FX rider's unconditional state (xccy => deep), so that was no longer
    # an edge case but the default. The precedence is unchanged -- the board block still outranks
    # both riders, a starved cell is still COUNTED as budget_cap and never silent -- and the riders'
    # own caps (CW_CONTEXT_CAP 2, CW_FX_CAP 3) still bind well inside the 7.
    board_reads = cells_planned * CW_READS_PER_CELL
    ctx_admitted = 0
    ctx_rendered = 0
    fx_admitted = 0
    fx_rendered = 0
    fx_cache_hits = 0

    def _cw_slack() -> int:
        """V2-3 (L3): the ceiling left after the board PLAN and every RIDER read already admitted --
        the ONE arithmetic BOTH riders call, so the context cell and the FX cell can never
        double-spend it (MEASURED on the v1 draft: 58/60 then 59/61). Arithmetically identical to
        the shipped context test whenever fx_admitted is 0 AND the regime is off, which is every
        flag-off turn, so the rewrite of that test below is behaviour-preserving off. It reads
        `cw_ceiling`, THE REGIME'S OWN CEILING -- the same number the board plan two lines up was
        admitted against -- so the rider allowance the deep ceiling was sized to carry is actually
        reachable (see the note above)."""
        return cw_ceiling - (spent + board_reads + ctx_admitted + fx_admitted)
    _ctx_lag, _ctx_declared = 0, None
    _fx_declared = None
    if xccy_on:
        # the FX card is hoisted ONCE PER TURN beside the context one: an unreadable registry
        # declines every FX cell as read_error and never raises.
        try:
            _fx_declared = getattr(_registry().get(_CW_FX_TABLE), "metrics", None) or {}
        except Exception:  # noqa: BLE001 -- an unreadable card declines every cell, never raises
            _fx_declared = None
    if context_on:
        payload["context"]["board_reads_planned"] = board_reads   # planned/slices: stamped at enumeration
        try:
            _ctx_ts = _registry().get(_CW_CONTEXT_TABLE)
            _ctx_lag = int(getattr(_ctx_ts, "publication_lag_days", 0) or 0)
            _ctx_declared = getattr(_ctx_ts, "metrics", None) or {}
        except Exception:  # noqa: BLE001 -- an unreadable card declines every cell as read_error, never raises
            _ctx_lag, _ctx_declared = 0, None
    # ── measurement + render ──
    from leviathan.graphrag.numbers import stats as _st
    j4 = _cw_j4_index(sg)
    lines: list = []
    n = base
    reads_spent = 0
    priced_children: set = set()
    rendered_pairs: list = []
    # V2-3 (L3, rung 2): the FX read cache is per TURN, not per firing -- 'one read per distinct
    # cross per turn' is literal. The key carries the SPAN as well as the cross so a future shape
    # change can never serve one window's rate under another window's handle; today every FX cell in
    # a turn belongs to firing 1 (the lifted children ride it), so the span term is a belt, not a cost.
    fx_by_cross: dict = {}
    # V2-3 (build-refute major-1): the (cross, span) of every FX cell that actually RENDERED, in
    # render order. `len(fx_rendered_keys) == fx_rendered` is the invariant -- the render belt's
    # rollback truncates this list back to `_r0` by the same token -- and the whole-block rollbacks
    # below turn it into one NAMED decline per rendered cell, so the FX rectangle closes on the
    # fenced path too. Without it a fenced block reported fx_planned 1 / fx_rendered 0 / declines []
    # with a read genuinely paid and named by nothing.
    fx_rendered_keys: list = []
    for _fi, f in enumerate(firings):
        t1, t2, span_tok, span_days = f["start"], f["end"], f["span"], f["span_days"]
        # M4 as adjudicated: the firing label is the INJECTED LINE'S OWN NODE TOKEN verbatim --
        # one window, one spelling on both surfaces; the display slice label is the fallback ONLY
        # when the token carries a digit (two live ids do; the fence would drop the block).
        tok = str(f.get("node_token") or "")
        firing_lab = tok if (tok and not any(ch.isdigit() for ch in tok)) \
            else _cw_slice_label(f["slice"])
        # WINDOW-AGE DATING, computed ONCE per firing (both boards on a hop share the window) and
        # GATED ON THE REGIME. The gate is a DECLARED LIMIT, not a preference: this is a V2-5-lane
        # remedy for a defect the DEEP panel measured, and the walk's first law is flag-off
        # byte-identity -- an ungated note would move every board row of every flag-off turn, which
        # is precisely what G1 exists to refuse, on a leg whose rollback (rev 126) is the off regime.
        # Under the SHIPPED serving state (GRAPHRAG_CASCADE_DEEP=on since rev 127) every served walk
        # row carries it, so no reader loses the dating; the rollback keeps today's bytes exactly.
        age_note = _cw_window_age_note(t2, asof) if deep_on else None
        j4_hit = j4.get((root, span_tok))
        if j4_hit is not None and str(j4_hit.get("status")) == "closed":
            # review D6 (confirmed): verdicting off a magnitude the BLOCK does not carry handed
            # the writer an uncitable read, and J4's handle cannot ride a non-ROW-1 line under the
            # numeral fence. So a closed J4 hit DEFERS the firing -- no double-price (K11), no
            # uncited verdict; the handle rides the trace and the absence names the fact. A4's
            # cite-the-handle clause is charter-corrected as measured-impossible.
            root_rec = {"slug": root, "span": span_tok, "status": "declined",
                        "reason": "j4_owns_window", "reads": 0,
                        "j4_handle": str(j4_hit.get("handle") or "")}
        elif j4_hit is not None and str(j4_hit.get("reason")) in (EP_DECLINE_BUDGET,
                                                                  EP_DECLINE_READ_TRUNCATED):
            # refute-v3 major-5: J4's OWN budget/saturation declines are honoured, never re-spent.
            root_rec = {"slug": root, "span": span_tok, "status": "declined",
                        "reason": "j4_budget_deferred", "reads": 0}
        else:
            root_rec, rr = _cw_cell(qfn, root, t1, t2, span_tok, asof,
                                    futures_newest_first=futures_newest_first)
            reads_spent += rr
        if root_rec["status"] == "closed" and root_rec.get("_res") is not None:
            n += 1
            calls.append(_shown(_cw_call(root, root_rec, asof), root_rec["move_pct"]))
            root_rec["handle"] = f"N{n}"
            lines.append(_cw_cell_line(n, root, root_rec, asof, age_note=age_note))
        payload["cells"].append({k: v for k, v in root_rec.items() if k != "_res"})
        if root_rec["status"] != "closed":
            lines.append(_cw_absence(_CW_BOARD_LABEL[root],
                                     str(root_rec.get("reason") or "no_move")))
            if context_on and f["slice"] in _CW_CONTEXT_SERIES:
                # a declined-root firing emits NO context row (the cell rides only a closed root)
                payload["context"]["declines"].append({"slice": f["slice"], "span": span_tok,
                                                       "reason": "root_declined"})
            continue
        # V2-5: the great leg joins on the SAME terms as the grand. Nothing else in the render loop
        # changes -- `parent = a.get("parent") or root` already resolves it, the parent_rec scan finds
        # the grand cell (appended below before the great leg is processed), `_cw_fences` applies the
        # SAME interval and tenor tests, a fence failure forces 'undetermined' (K4) and the row still
        # ships, and the whole-block register fence stays atomic with caller rollback.
        legs = (list(admissible if (not deep_on or _fi == 0) else same_ccy)
                + [L for L in (hop_legs[k] for k in _CW_HOP_LEVELS) if L is not None])
        for a in legs:
            child = a["child"]
            parent = a.get("parent") or root
            parent_rec = root_rec
            if parent != root:
                parent_rec = next((c for c in payload["cells"]
                                   if c.get("slug") == parent and c.get("span") == span_tok
                                   and c.get("status") == "closed"), None)
            if _cw_free(cov, child, f):
                # review minor: a firing that predates the CHILD's own board history declines
                # arithmetically -- A6.2's zero-read discipline; span_outcome would only say the
                # same thing after two paid reads.
                # THE ONE PREDICATE (build-review major): this used to spell `str(cov[child]) > t1`
                # inline while _cw_free's docstring claimed "there is no second predicate anywhere in
                # this leg". They agreed only because t1 IS f["start"]; if either side were ever
                # tightened a child would stay in free_set, contribute 0 to paid_cells and then be
                # PRICED -- realized reads above the plan the cap belt approved, the one thing
                # CW_DEEP_CAP exists to prevent. Byte-identical today, off regime included.
                crec, cr = {"slug": child, "span": span_tok, "status": "declined",
                            "reason": "pre_coverage", "reads": 0}, 0
            else:
                crec, cr = _cw_cell(qfn, child, t1, t2, span_tok, asof,
                                    futures_newest_first=futures_newest_first)
            reads_spent += cr
            phrases = [_CW_RELATION_WORDS[rel] for rel in a["relations"]]
            rendered_pairs.append((parent, child))
            # V2-3 (M7): the currency clause -- and therefore the seam literal the persona gate
            # greps for -- exists ONLY on a CLOSED cell, so the mandate can never ship demanding a
            # figure for a hop that printed an absence (the W4-D3 shape).
            _cl = (crec["status"] == "closed" and crec.get("_res") is not None)
            _x = (a.get("xccy") if (xccy_on and _cl) else None)
            lines.append(_cw_hop_header(_CW_BOARD_LABEL[parent], _CW_BOARD_LABEL[child],
                                        phrases, a["blurb"], firing_lab, xccy=_x))
            if _cl:
                n += 1
                calls.append(_shown(_cw_call(child, crec, asof), crec["move_pct"]))
                crec["handle"] = f"N{n}"
                lines.append(_cw_cell_line(n, child, crec, asof, age_note=age_note))
                priced_children.add(child)
                # -- V2-3 BELT A: THE FX ADMISSION LADDER, SEVEN RUNGS IN ONE ORDER, READ ONLY --
                # It appends NO line, mints no handle and needs no rollback; the whole rung set is
                # wrapped in one belt whose handler declines the record by name. `fxrec` is set to
                # None IMMEDIATELY BEFORE the try (v3 refute major-4: a name reused across the leg
                # would otherwise leave the PREVIOUS hop's rate bound and feed another hop's
                # exchange-rate move into this hop's verdict -- the leaked-name class).
                fxrec = None
                _fx_minted = False
                _fx_dec = None
                try:
                    if _x:                                    # rung 1, ENTRY: a same-currency hop
                        #                                       mints nothing and counts nothing
                        payload["xccy"]["fx_planned"] += 1
                        _ck = (a["fx"], span_tok)
                        if _ck in fx_by_cross:                # rung 2, CACHE: one read per distinct
                            fxrec = fx_by_cross[_ck]          #   cross per turn, zero reads here
                            if str(fxrec.get("status")) == "closed":
                                fx_cache_hits += 1
                                payload["xccy"]["fx_cache_hits"] = fx_cache_hits
                            else:
                                # A CACHE HIT ON A DECLINED RATE IS NOT A FREE PASS (build-refute
                                # minor, adopted). The cache is written in rung 7 BEFORE the status
                                # test, so a second hop on a cross whose first read declined
                                # (grain_thin / no_unit / no_move / read_error) -- or whose render
                                # was fenced -- used to count `fx_cache_hits` and NOTHING ELSE,
                                # under-counting by one per extra hop the population that shipped
                                # with no priced rate on the page. It now DECLINES BY NAME at zero
                                # reads, and 'cache_declined' is a PRE-ADMIT reason, so both
                                # rectangles still close: it takes the cache hit's place in the
                                # first and joins |declines| in the second.
                                _fx_dec = "cache_declined"
                        elif replay_on:                       # rung 3: the card's newer crosses were
                            _fx_dec = "replay"                #   FILL-FORWARD BACKFILLED, so a
                            #                                     historical as-of would read rows
                            #                                     that did not exist then. 0 reads.
                        elif fx_admitted >= CW_FX_CAP:        # rung 4
                            _fx_dec = "fx_cap"
                        elif _cw_slack() < 1:                 # rung 5: the ONE slack arithmetic
                            _fx_dec = "budget_cap"
                        elif _fx_declared is None:            # rung 6: an unreadable card
                            _fx_dec = "no_card"               #   (pre-read; 'read_error' is the
                            #                                     POST-read name at the paying site)
                        elif a["fx"][0] not in _fx_declared:  # rung 6b: a READABLE card that does
                            #                                   NOT declare the mapped column. All
                            #                                   four _CW_FX_CROSS metrics exist on
                            #                                   the live card today, so this is
                            #                                   latent -- but without it rung 7
                            #                                   pays a read and hands _cw_fx_cell a
                            #                                   card_metric of None, spending
                            #                                   CW_FX_CAP on a cell that can only
                            #                                   error. The ladder DECLINES BY NAME,
                            #                                   pre-read, at zero cost (build-refute
                            #                                   minor, adopted).
                            _fx_dec = "no_metric"
                        else:                                 # rung 7, ADMIT
                            fx_admitted += 1
                            payload["xccy"]["fx_admitted"] = fx_admitted
                            fxrec = _cw_fx_rec(a["fx"][0], a["fx"][1], _x[0], _x[1], span_tok)
                            _fx_minted = True                 # the record is minted BEFORE the read
                            _cw_fx_cell(qfn, fxrec, t1, t2, asof,
                                        card_metric=_fx_declared.get(fxrec["metric"]),
                                        futures_newest_first=futures_newest_first)
                            fx_by_cross[_ck] = fxrec
                            if fxrec["status"] != "closed":
                                _fx_dec = str(fxrec.get("reason") or "no_move")
                except Exception:  # noqa: BLE001 -- the FX cell declines, the walk block ships
                    _fx_dec = "error"
                    if fxrec is not None and fxrec.get("status") != "closed":
                        fxrec.update(status="declined", reason="error")
                if _fx_minted and fxrec is not None:
                    _xr = int(fxrec.get("reads") or 0)        # paid iff the fetch returned
                    reads_spent += _xr
                    payload["xccy"]["fx_reads"] += _xr
                if _fx_dec and _x:
                    payload["xccy"]["declines"].append({"cross": f"{_x[0]}>{_x[1]}",
                                                        "span": span_tok, "reason": _fx_dec})
                if parent_rec is None:
                    lines.append(_cw_verdict_line(_CW_BOARD_LABEL[parent],
                                                  _CW_BOARD_LABEL[child], "undetermined",
                                                  xccy=_x))
                else:
                    ri_ok, tenor_ok = _cw_fences(parent_rec, crec, span_days)
                    crec["interval_ok"], crec["tenor_ok"] = ri_ok, tenor_ok
                    # V2-3 (L4) THE DOMINANCE GATE, the TRUE sign-flip predicate. A board priced in
                    # <ccy> is worth P/X in USD, so its USD move carries the sign of
                    # (m_local - m_fx): the own-currency and common-denomination signs differ IFF
                    # the rate moved FURTHER **and** THE SAME WAY. The USD leg is invariant, so only
                    # the NON-USD leg can flip -- and it is read off the admissible record's OWN
                    # root currency (`_x[0]`), never off a loop variable that may be stale.
                    # MEASURED on 142 verdictable cross window-pairs: the co-signed predicate fires
                    # 4 times and matches the redenominated ground truth 142 of 142; the bare
                    # magnitude test fires 20, of which 16 are false positives.
                    _nonusd = (parent_rec if (_x and _x[0] != CW_XCCY_USD) else crec)
                    _vr = None
                    if not (ri_ok and tenor_ok):
                        verdict = "undetermined"      # K4: a fence-failed pair NEVER verdicts
                    elif (_x and fxrec is not None and fxrec.get("status") == "closed"
                          and abs(fxrec["move_pct"]) > abs(_nonusd["move_pct"])
                          and (fxrec["move_pct"] > 0) == (_nonusd["move_pct"] > 0)):
                        verdict, _vr = "undetermined", "fx_flips_sign"
                        payload["xccy"]["fx_flips_sign"] += 1
                        payload["xccy"]["fx_gate_checked"] += 1
                    else:
                        if _x:
                            if fxrec is not None and fxrec.get("status") == "closed":
                                payload["xccy"]["fx_gate_checked"] += 1
                            else:
                                # DECLARED LIMIT (owner decision #4): with no closed FX cell the
                                # engine holds no flip input and still reads the two own-currency
                                # signs -- the sign test is currency-free by construction and both
                                # currencies are named on the page. The population is COUNTED so it
                                # is readable from every artifact row.
                                payload["xccy"]["fx_unpriced_verdicts"] += 1
                        verdict = _st.sign_agreement(parent_rec["move_pct"], crec["move_pct"],
                                                     a["sign"])["value"]
                    crec["verdict"] = verdict
                    if _vr is not None:
                        crec["verdict_reason"] = _vr
                    lines.append(_cw_verdict_line(_CW_BOARD_LABEL[parent],
                                                  _CW_BOARD_LABEL[child], verdict,
                                                  xccy=_x, reason=_vr))
                # -- V2-3 BELT B: RENDER, with its marks captured IMMEDIATELY AFTER the verdict
                # append so a raised render trims ONLY its own lines and its own call and can never
                # orphan the child ROW-1, its handle or its verdict (the D2 orphan-call class).
                if _x:
                    _n0, _c0, _l0, _r0 = n, len(calls), len(lines), fx_rendered
                    try:
                        if _fx_minted and fxrec is not None and fxrec.get("status") == "closed":
                            l1, l2 = _cw_fx_line(n + 1, fxrec), _cw_fx_words(fxrec)
                            if _cw_register_fence([l1, l2]):   # the PAIR is atomic and pre-fenced
                                calls.append(_shown(_cw_fx_call(fxrec, asof), fxrec["move_pct"]))
                                n += 1
                                fxrec["handle"] = f"N{n}"
                                lines.extend([l1, l2])
                                fx_rendered += 1
                                fx_rendered_keys.append((f"{_x[0]}>{_x[1]}", span_tok))
                                payload["xccy"]["fx_rendered"] = fx_rendered
                            else:
                                fxrec.update(status="declined", reason="render_fence")
                                payload["xccy"]["declines"].append(
                                    {"cross": f"{_x[0]}>{_x[1]}", "span": span_tok,
                                     "reason": "render_fence"})
                        elif not (fxrec is not None and fxrec.get("status") == "closed"):
                            # no priced rate anywhere on this page for this cross: the words ride
                            # FREE, letters-only, at zero reads. A CACHE HIT on a cross that IS
                            # priced adds nothing here -- the rate already sits on the page once,
                            # under its own handle, and this hop's header and read lines name both
                            # currencies unconditionally.
                            lines.append(_cw_fx_words_unpriced(_x[0], _x[1]))
                    except Exception:  # noqa: BLE001 -- the render declines, the block ships
                        n = _n0
                        calls[_c0:] = []
                        lines[_l0:] = []
                        fx_rendered = _r0
                        fx_rendered_keys[_r0:] = []           # len(...) == fx_rendered, restored
                        payload["xccy"]["fx_rendered"] = _r0
                        if fxrec is not None:
                            fxrec.pop("handle", None)
                            fxrec.update(status="declined", reason="error")
                        payload["xccy"]["declines"].append({"cross": f"{_x[0]}>{_x[1]}",
                                                            "span": span_tok, "reason": "error"})
                    payload["xccy"]["rendered"] += 1
                    payload["xccy"]["pairs"].append(f"{_x[0]}>{_x[1]}")
                    if _fx_minted and fxrec is not None:
                        payload["cells"].append(dict(fxrec))
            else:
                lines.append(_cw_absence(_CW_BOARD_LABEL[child],
                                         str(crec.get("reason") or "no_move")))
            payload["cells"].append({k: v for k, v in crec.items() if k != "_res"})
            if deep_on and crec["status"] == "declined" and crec.get("reason") == "pre_coverage":
                # `absent` counts RENDERED pre_coverage CELLS, and is deliberately NOT a rectangle
                # term: on the two-firing shape one free LEG renders TWO absences, so absent can
                # exceed free. It is the diagnostic that makes the over-reservation visible.
                payload["deep"]["hops"][next((k for k in _CW_HOP_LEVELS if a is hop_legs[k]),
                                             "child")]["absent"] += 1
        if context_on:
            # -- V2-1 CONTEXT CELL: one non-verdicted pair per admitted firing, AFTER the firing's
            # child rows (reached only when the root cell closed). THE WHOLE EMISSION IS BELTED
            # (refute M1): an exception here declines the CELL with reason 'error', rolls back its own
            # call/lines/handle, counts a read that was actually paid, and the walk block ships
            # unchanged -- a rider may never cost the walk its block.
            _cd = payload["context"]["declines"]
            _n0, _c0, _l0, _r0 = n, len(calls), len(lines), ctx_rendered
            xrec = None
            try:
                if f["slice"] not in _CW_CONTEXT_SERIES:
                    _cd.append({"slice": f["slice"], "span": span_tok, "reason": "unmapped_slice"})
                elif replay_on:
                    # the C-2 belt on the card's own 'no true as-of replay' declaration: COUNTED,
                    # zero reads, never silenced by the seam
                    _cd.append({"slice": f["slice"], "span": span_tok, "reason": "replay"})
                elif ctx_admitted >= CW_CONTEXT_CAP:
                    _cd.append({"slice": f["slice"], "span": span_tok, "reason": "context_cap"})
                elif _cw_slack() < 1:                 # V2-3 (L3): the ONE slack arithmetic, which
                    #                                      is where this rider now SEES the FX reads
                    _cd.append({"slice": f["slice"], "span": span_tok, "reason": "budget_cap"})
                elif _ctx_declared is None:
                    _cd.append({"slice": f["slice"], "span": span_tok, "reason": "read_error"})
                else:
                    ctx_admitted += 1
                    payload["context"]["admitted"] = ctx_admitted
                    xrec = _cw_context_rec(f["slice"], span_tok)
                    _cw_context_cell(qfn, xrec, t1, t2, asof, lag_days=_ctx_lag,
                                     card_metric=_ctx_declared.get(xrec["metric"]),
                                     futures_newest_first=futures_newest_first)
                    if xrec["status"] == "closed":
                        l1, l2 = _cw_context_line(n + 1, xrec), _cw_context_words(xrec)
                        if _cw_register_fence([l1, l2]):      # the PAIR is atomic and pre-fenced
                            xcall = _shown(_cw_context_call(xrec, asof), xrec["move_pct"])
                            n += 1
                            calls.append(xcall)
                            xrec["handle"] = f"N{n}"
                            lines.extend([l1, l2])
                            ctx_rendered += 1
                            payload["context"]["rendered"] = ctx_rendered
                        else:
                            xrec.update(status="declined", reason="render_fence")
                            _cd.append({"slice": f["slice"], "span": span_tok,
                                        "reason": "render_fence"})
                    elif xrec.get("reason"):
                        _cd.append({"slice": f["slice"], "span": span_tok, "reason": xrec["reason"]})
            except Exception:  # noqa: BLE001 -- the rider's OWN belt: the cell declines, the walk ships
                n = _n0
                calls[_c0:] = []
                lines[_l0:] = []
                ctx_rendered = _r0
                payload["context"]["rendered"] = _r0
                if xrec is None:
                    xrec = {"kind": "context", "slice": f["slice"], "span": span_tok,
                            "status": None, "reason": None, "reads": 0}
                xrec.pop("handle", None)
                xrec.update(status="declined", reason="error")
                _cd.append({"slice": f["slice"], "span": span_tok, "reason": "error"})
            if xrec is not None:
                xr = int(xrec.get("reads") or 0)                  # paid iff the fetch returned
                reads_spent += xr
                payload["context"]["reads"] += xr
                payload["cells"].append(dict(xrec))
    payload["children_priced"] = len(priced_children & {a["child"] for a in admissible})
    if deep_on:
        # a FREE child is rendered-not-priced: it is counted `free`, never `named`, so the rectangle
        # reads declared == priced + named + free instead of declared == priced + named.
        payload["children_named"] += sum(1 for a in admissible
                                         if a["child"] not in priced_children
                                         and a["child"] not in free_set)
    else:
        payload["children_named"] += sum(1 for a in admissible
                                         if a["child"] not in priced_children)
    _deep_stamp_hops(priced_children)                 # the per-level rectangle, on the render path
    payload["net_reads"] = reads_spent
    # K3 ORDER HONESTY (review D7, confirmed): order and path derive from what was RENDERED --
    # the hop headers actually emitted -- never from admission or pricing, so the marker, the
    # trace and the page can never disagree about the depth the reader was shown.
    seen_m: list = [root]
    for (_p, c) in rendered_pairs:
        if c not in seen_m:
            seen_m.append(c)
    payload["path"] = seen_m
    if deep_on:
        # THE ORDER LABEL IS `_cw_order_n`, THE ONE LIFTED EXPRESSION -- edges not nodes, and over
        # the chain of CLOSED cells so a HOLE (a declined hop, a free pre_coverage absence) caps the
        # label at the last hop that actually printed a read. See that helper for the measured B4
        # shape this closes. `.get(order_n, "third")` rather than `[order_n]` -- a KeyError here
        # would be swallowed by the wrapper belt into a silent whole-block 'declined', the worst
        # possible failure mode for a label. `payload["path"]` above is UNCHANGED: it is the
        # RENDERED chain, absences included, because the page really did show those rows.
        # V2-3 (build-review minor): the kind filter is the SAME one `_cw_board_row_closed` and both
        # eval cell filters carry -- ('context', 'fx'). An FX cell carries no `slug` key at all, so
        # the un-widened form seeded a bare None into a membership set the order label reads.
        # Harmless on today's rendered_pairs (always slug strings); it was the one place the new
        # kind was missed, and a set that can hold None is not a set of slugs.
        _closed = {c.get("slug") for c in payload["cells"]
                   if c.get("kind") not in ("context", "fx") and c.get("status") == "closed"}
        order_n = _cw_order_n(root, rendered_pairs, _closed)
        payload["deep"]["order_n"] = order_n
        # V2-3 (L9): the depth the PAGE SHOWED, from the SAME lifted expression with the rendered
        # children standing in for the closed ones. `order_n` is the honest label (a hole caps it);
        # this one says how far the rendered chain ran, so an arm comparing cw_order across regimes
        # can tell "the chain was short" from "a cell in the chain declined".
        payload["deep"]["order_n_rendered"] = _cw_order_n(root, rendered_pairs,
                                                          {c for (_p, c) in rendered_pairs})
        payload["order"] = _CW_ORDER_WORDS.get(order_n, "third")
    else:
        payload["order"] = "second" if any(p != root for (p, _c) in rendered_pairs) else "first"
    def _fx_block_fenced():
        """V2-3 (build-refute major-1, MEASURED): A WHOLE-BLOCK ROLLBACK NAMES THE FX CELLS IT DROPS.
        `fx_rendered` goes to zero with the block, so ONE decline per cell that had RENDERED -- its
        own cross, its own span, in render order -- is exactly what keeps
        fx_planned == fx_rendered + fx_cache_hits + |declines| true on the fenced path. Before this,
        a fenced block reported fx_planned 1 / fx_rendered 0 / declines [] with an FX read genuinely
        paid and named by nothing. Called at ALL THREE whole-block returns: only the register fence
        is reachable with fx_rendered > 0 (a rendered FX cell implies a closed board child, hence a
        closed board row and a non-empty `lines`), and the other two are covered anyway so the
        rectangle is STRUCTURAL on every path rather than argued from reachability."""
        for _fx_cross, _fx_span in fx_rendered_keys:
            payload["xccy"]["declines"].append({"cross": _fx_cross, "span": _fx_span,
                                                "reason": "block_fenced"})
    if not _cw_board_row_closed(payload["cells"]):
        # review minor: a block with zero [N] rows must not ship a marker claiming rows -- the
        # dormant-clause discipline. The absences stay in the trace; the block stays unshipped.
        # V2-1: the predicate KIND-FILTERS context cells (a context cell is never the row that
        # licenses a marker); unreachable under the emit-after-closed-root placement, kept as the belt.
        payload["outcome"] = "declined"
        calls[base:] = []
        if context_on:
            payload["context"]["rendered"] = 0
        if xccy_on:
            _fx_block_fenced()
            payload["xccy"].update(rendered=0, fx_rendered=0, pairs=[])
        return [], payload
    if not lines:
        payload["outcome"] = "declined"
        # V2-3: the THIRD early return. `lines` empty implies no hop header was ever appended,
        # hence zero lifted hops rendered and a ledger already at zero -- MEASURED-UNREACHABLE and
        # reset anyway, because the cost is one line and the failure mode is an eval mirror scoring
        # a page that shipped nothing.
        if xccy_on:
            _fx_block_fenced()
            payload["xccy"].update(rendered=0, fx_rendered=0, pairs=[])
        return [], payload
    # V2-1: the marker's opening clause is conditional under a rendered context row; the no-context
    # call is the pre-rider call, byte for byte.
    # V2-3: BOTH branches of the conditional expression carry `fx=` or the sentence is silently
    # dropped on context-bearing blocks. fx=False is byte-identical to both shipped literals.
    lines.append(_cw_marker(payload["order"], context=True, fx=bool(fx_rendered)) if ctx_rendered
                 else _cw_marker(payload["order"], fx=bool(fx_rendered)))
    if not _cw_register_fence(lines):
        calls[base:] = []                             # ATOMIC: the whole block drops, rows rolled
        payload["outcome"] = "fenced"                 # back, and the trip is a counted outcome
        payload["cells"] = [dict(c, handle=None) for c in payload["cells"]]
        if context_on:
            payload["context"]["rendered"] = 0
        if xccy_on:
            _fx_block_fenced()
            payload["xccy"].update(rendered=0, fx_rendered=0, pairs=[])
        if deep_on:
            # THE DEEP LEDGER ZEROES WITH THE BLOCK (build-refute minor B5, MEASURED: a fenced
            # third-order block still projected order_n 3, paid_cells 4, plan_reads 12 and a hop-3
            # verdict, so an analyst filtering on cw_hop3_verdict counted a block nobody read). The
            # context rider already zeroes its own `rendered` here; this is the same sentence for
            # the board ledger. The PLAN fields go None (absent is never zero -- there is no plan
            # for a block that did not ship) and the priced/absent terms go to zero with `named`
            # taking them, so the per-level rectangle still closes. cap/ceiling/max_* stay: they
            # are config echoes, not claims about a shipped block.
            payload["deep"]["order_n"] = None
            payload["deep"]["order_n_rendered"] = None
            payload["deep"]["cells_planned"] = None
            payload["deep"]["paid_cells"] = None
            for _row in payload["deep"]["hops"].values():
                _row.update(priced=0, absent=0,
                            named=_row["declared"] - _row["free"])
            # ... and the TOP-LEVEL ledger folds the same way, or eval's hop-1 mirror
            # (children_priced == hops.child.priced) contradicts itself on exactly this row
            # (post-fix re-review M1, measured). K2 still holds: declared is untouched.
            payload["children_named"] = int(payload.get("children_named") or 0) + int(payload.get("children_priced") or 0)
            payload["children_priced"] = 0
        return [], payload
    payload["outcome"] = "fired"
    return lines, payload


def _cascade_walk_leg_or_nothing(sg, graph, walk_request: dict, qfn, asof, calls: list, *,
                                 futures_newest_first: bool | str = False) -> tuple:
    """R6 belt at the one place both quantify return paths reach it (the `_episode_leg_or_nothing`
    precedent). Writes the ONE registered trace key whenever the leg RAN -- `outcome` carries
    fired/declined/fenced, so an absent key means 'did not run', never 'declined'."""
    _b = len(calls)
    _t0 = time.perf_counter()                         # V2-5: the WALK-SCOPED clock (the probe_ms
    #                                                   idiom). timing_ms.quantify is the whole
    #                                                   quantify measure -- 251 / 3,066 / 13,675 ms
    #                                                   on three identically shaped 6-read walks, a
    #                                                   54x spread no larger n can separate -- so
    #                                                   G10 needs its own. This wrapper is the ONE
    #                                                   place every return path reaches.
    try:
        lines, payload = _cascade_walk_legs(sg, graph, walk_request, qfn, asof, calls, _b,
                                            futures_newest_first=futures_newest_first)
    except Exception:  # noqa: BLE001 -- fail-closed: the walk must never break the v1 answer
        calls[_b:] = []                               # review D2: the belt rolls the LEDGER back
        #                                               too -- an orphan call record would widen
        #                                               the verifier's acceptance pool (the W4
        #                                               class) and stretch the [N] index range
        lines, payload = [], {"outcome": "declined",
                              "declines": [{"scope": "root", "reason": "error"}]}
        if bool((walk_request or {}).get("deep") or (walk_request or {}).get("xccy")):
            # THE BELT MUST CARRY THE REGIME, or a treatment error row projects cw_deep_on False and
            # is read as a control row. The REQUEST is the only thing it can trust after an
            # exception. Flag off -> no 'deep' key -> this dict is byte-identical to today's.
            # IT CARRIES NO 'hops' KEY, deliberately: eval projects cw_deep_identity_ok as None here
            # rather than the vacuous True that `all()` over an empty dict returns, and reads the
            # state off cw_deep_error instead (build-refute major-2).
            payload["deep"] = {"error": True}
        if bool((walk_request or {}).get("xccy")):
            # ...AND THE SAME SENTENCE FOR THE CROSS-CURRENCY REGIME (build-refute major-3,
            # MEASURED). Under the flip GRAPHRAG_CASCADE_DEEP stays OFF and `deep` is set by
            # `xccy`, so a belt row that stamped only `deep` was INDISTINGUISHABLE from a
            # deep-only CONTROL row: eval's cw_xccy_on reads `"xccy" in _cw`, which was False.
            # Same shape, same reason, same fail-closed dict -- and eval projects a
            # cw_xccy_error companion beside cw_deep_error. Flag off -> no 'xccy' key.
            payload["xccy"] = {"error": True}
    if isinstance(payload, dict) and "deep" in payload:
        # THE ONE NONDETERMINISTIC FIELD IN THE WHOLE PAYLOAD. Two runs of the same turn agree on
        # every other byte and never on this one, so EXCLUDE elapsed_ms from every byte comparison
        # of a flag-ON artifact (the flag-OFF golden never sees it: there is no 'deep' key off).
        payload["deep"]["elapsed_ms"] = int((time.perf_counter() - _t0) * 1000)
    if payload is not None:
        try:
            sg.trace["quantify_cascade_walk"] = payload
        except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
            pass
    return lines, payload


# -- J6: THE COT OUTCOME PAIRING, CONTEXT LANE ONLY (D-OJ-17 / D-OJ-18) -----------------------------
#
# WHAT IT IS. "What positioning did, and what price did after" -- PAST TENSE, BOTH CLAUSES, two dated
# records placed side by side. It never renders forward guidance and it never feeds an engine.
#
# WHY IT IS ITS OWN TABLE ID, AND WHY THAT ID IS IN THE FENCE (D-OJ-18, skeptic F11 -- the most
# consequential finding of that pass). Every leg of the positioning fence keys on the TABLE ID:
# `positioning_context_violations` at lint AND at runtime, the chain_map/complex_map/transmission_map
# bans, the R7b unit whitelist. R7b (config_check.py) requires every `silver_cot` metric's unit to be a
# contracts/pct-of-OI level or a z family, so a "% move over N days" unit CANNOT hang off the silver_cot
# card -- true, and the conclusion the first draft drew from it was the dangerous one. Routing the
# outcome to a table OUTSIDE `POSITIONING_TABLES` would satisfy R9's letter while vacating the
# context-shape rule, the never-a-chain-hop ban and the never-a-relative-value-leg ban all at once.
# "Registers nothing new under silver_cot" is not a fence, it is an EXIT from one. So the lane gets its
# own registered id and that id goes INTO the fence, in BOTH constants -- config_check's drift pin fails
# the build if only one moves, which is the cheapest available proof the fence actually grips it.
#
# WHY THE OUTLOOK CARVE-OUT IS A GATE AND NOT A SENTENCE (D-OJ-17). Under OUTLOOK, register.py places
# `_VALUATION_PHRASES`, `_FLOW_PHRASES`, `_PERSISTENCE` and both Lane-B arms inside `if not outlook:`,
# so a cited, arrow-free sentence -- "across the 47 times managed-money net length exceeded +1.5z,
# front-month corn rose a median 8.2% over the next 90 days [N7]" -- returns False from
# `_is_banned_sentence` and ships as a setup. That sentence is a conditional PERFORMANCE statistic, and
# no phrasing rule inside it can be load-bearing on a lane where the fence around it is down. D1's own
# text offers two options; this picks (a): the ref is not reached at all on an outlook turn. (b) --
# restoring a flow bound under OUTLOOK for positioning sentences -- is a register-doctrine change that
# D1 says needs its own decision, and this is not the place to smuggle it in.
COT_OUTCOME_TABLE = "gold_cot_outcomes"
COT_OUTCOME_METRIC = "move_pct"
COT_OUTCOME_MAX_ROWS = 4             # one turn, one slug's horizon family at most
COT_OUTCOME_ENDPOINT_MARGIN_DAYS = 21   # the read window's right slack: the horizon CLOSE is the data
#                                         axis and the realized endpoint is the last session on or
#                                         before it, so the window must reach past the nominal close.

# The narration line the block carries when a pairing actually rendered. It is the J6 twin of
# POSITIONING_CONTEXT_ADDENDUM and it is written to the same standard: PHRASED POSITIVELY, naming no
# flow idiom, because the surest way to put "crowded"/"stretched" into a draft is to write it into the
# prompt as a prohibition. What it adds over C1's addendum is the ONE thing this leg makes possible and
# therefore the one thing it must refuse: a causal or performance reading of two records that merely sit
# beside each other. tests/unit/test_register_corpus.py pins this exact object -- not a copy of it -- at
# zero raw flow hits, with forward-looking rewrites of it pinned as MUST_FLAG.
COT_OUTCOME_ADDENDUM = (
    "POSITIONING AND PRICE, AS TWO SEPARATE RECORDS: the rows above place a dated managed-money "
    "observation beside what ONE delivery month's settle did across the window that followed it. Both "
    "are past-tense record. Narrate them as two dated facts on their own [N] handles, each on the "
    "series and delivery month its tag names. This engine holds NO measurement that one of them "
    "produced the other, so do not write the second as an outcome of the first, do not describe either "
    "as having worked or paid, and state nothing about what either will do next.")


def _cot_event_date(rec: dict):
    """The dated report the pairing is anchored on -- the NEWEST observation the positioning leg read.

    The serving alias is `knowledge_date` (silver_cot's `_extras` is exactly that one key). The raw
    column names are read as fallbacks for the same reason `_pace_period_key` reads them: fixtures and
    guard-column frames carry the physical name, and a leg that silently found None here would anchor
    the pairing on nothing while looking anchored."""
    rows = (rec or {}).get("rows") or []
    best = None
    for r in rows:
        for k in ("knowledge_date", "report_date", "data_date", "date"):
            v = (r or {}).get(k)
            if v not in (None, ""):
                s = str(v)[:10]
                if best is None or s > best:
                    best = s
                break
    return best


def _cot_outcome_read(qfn, *, slug: str, event_date: str, horizon_days: int, asof) -> list:
    """The ONE read site for the J6 card. Returns the matching outcome ROWS, or [] -- never raises.

    THE READ IS AGAINST `gold_cot_outcomes`, DELIBERATELY, and it is the whole of D-OJ-18: the fence
    grips a table id, so the row a reader sees paired with positioning must come from a card that is
    inside the fence. Reading the same move off `silver_futures_eod` and rendering it beside a
    positioning line would be the fence EXIT this item exists to refuse, however identical the number.

    IT IS FAIL-CLOSED IN THREE PLACES, and each is a precondition rather than a bug:
      * the card is not registered until the builder wave lands, so `fetch_window` returns `error` and
        this returns [] -- the leg is inert, not wrong;
      * a row is kept only when its PERIOD equals the event date. The card's `period_col` is
        `event_date` while its guard/data axis is the row's readable date, so the window below is on the
        CLOSE axis and the event is matched on the period alias, never inferred from the window;
      * a row is kept only when it names THIS horizon. A card that does not surface `horizon_days`
        yields no rows at all, which is the correct direction: three horizons collapsed into one line
        would be a distribution wearing a single number's clothes.

    AND IT IS CENSUS-SHAPED, WHICH IS THE POINT OF THIS PARAGRAPH (adversarial finding 3). The compiled
    guard (`readable_date <= asof - 6`) is D-OJ-14-safe only when the reader's asof EQUALS the build's:
    the builder writes `pending` only for horizons open at ITS asof, so at any earlier pinned asof a row
    the build wrote `closed` is dropped by the guard and no pending row exists in its place -- and an
    empty guarded read is `record_silent`, i.e. `citations._empty_label`'s COVERAGE-GAP string, for what
    is purely a TIMING fact. That is the judged-30 RCA inversion item 48a exists to close, arriving
    through the guard. So this site never lets the guard's silence speak:
      (1) it ASKS THE CLAMP FIRST (`OC.pending_state` at the reader's asof) and returns [] with the
          pending verdict already established by the caller's dry run -- no read is even issued;
      (2) every row it does get back is RE-CLAMPED (`OC.clamp_row`) against the reader's asof from the
          row's own stored tape edge, so a row materialized `closed` by a later build cannot be read as
          a number here; a re-clamped row carries `status='pending'` and no move, and the caller's
          closed-only filter then reports `not_closed` rather than rendering a stale magnitude.
    `pattern_records.po_census_sql` is the same discipline in SQL (the boundary is a CASE, not a WHERE,
    so pending rows stay in the denominator). Any future agent-facing read of these tables inherits it."""
    from leviathan.graphrag.numbers import outcomes as OC

    if OC.pending_state(str(event_date)[:10], int(horizon_days), asof, None):
        # A TIMING fact, decided by the clamp rather than by an empty result set.
        return []
    hi = _iso_shift(event_date, int(horizon_days) + COT_OUTCOME_ENDPOINT_MARGIN_DAYS)
    # S1 canary: UNFLAGGED BY DESIGN (see quantify's docstring). COT_OUTCOME_TABLE is a module constant
    # ('gold_cot_outcomes') whose card declares no `contract_month_col` -- and per the paragraph above,
    # this site reading silver_futures_eod would be the D-OJ-18 fence exit, not a threading gap. So the
    # canary is structurally inapplicable here, and test_futures_readpath_pins pins that it stays so.
    # D-AM-18: the estate-wide token drops the `contract_month_col` key, so "inapplicable" becomes a
    # DECISION here -- bounded by the read itself, which is one slug over a horizon-length date window
    # (t1..t2 below) and cannot approach the row cap the token exists to re-aim.
    rec = fetch_window(qfn, table=COT_OUTCOME_TABLE, metric=COT_OUTCOME_METRIC, commodity=str(slug),
                       country=None, t1=str(event_date)[:10], t2=hi, asof=asof, agg="series",
                       period=None, period_type="date")
    if (rec or {}).get("status") != "ok":
        return []
    out = []
    for r in (rec.get("rows") or []):
        if str((r or {}).get("period") or "")[:10] != str(event_date)[:10]:
            continue
        try:
            if int((r or {}).get("horizon_days")) != int(horizon_days):
                continue
        except (TypeError, ValueError):
            continue
        row = dict(r)
        row.setdefault("event_date", str(event_date)[:10])
        row.setdefault("status", OC.STATUS_CLOSED)
        try:
            row = OC.clamp_row(row, asof, row.get("tape_edge_date"))
        except (TypeError, ValueError):
            # An unparseable event date/horizon on the row is not a licence to serve it unclamped.
            continue
        out.append(row)
    return out


def _cot_coverage_start(slug: str):
    """The per-slug price-coverage floor, as an ISO string or None. Item 89: EVERY J6 output states its
    own start date, because the two series start in different places -- MGEX positioning runs from
    2014-03-25 while its tape starts 2025-09-09, so eleven years of its COT history has no priced
    outcome at all and a reader shown one number and no floor cannot tell that."""
    try:
        from leviathan.silver import futures_eod_contracts as FC
        return FC.coverage_start_for(str(slug)).isoformat()
    except Exception:  # noqa: BLE001 -- an unmapped slug has no floor to state; the caller declines
        return None


def _cot_outcome_call(slug: str, row: dict, *, event_date: str, horizon_days: int, asof,
                      value: float) -> dict:
    """The synthetic call-record behind a J6 [N] handle. `period` is the EVENT..CLOSE span in the
    engine's own `a..b` glyph (never an arrow: `register._DERIV_OUTPUT` reads '->' as derived output and
    voids the citation exemption under OUTLOOK -- and although this leg never runs on an outlook turn,
    the label travels into the Sources ledger, which does)."""
    end = (row or {}).get("knowledge_date") or (row or {}).get("endpoint_date")
    r = {"value": round(float(value), 4), "unit": "%", "knowledge_date": end,
         "contract_month": (row or {}).get("contract_month_used") or (row or {}).get("contract_month"),
         "currency": (row or {}).get("currency"), "settle_kind": (row or {}).get("settle_kind")}
    if end:
        r["_provenance"] = {"date": str(end)[:10]}
    return {"query": {"table": COT_OUTCOME_TABLE, "metric": f"settle_change_pct_{int(horizon_days)}d",
                      "commodity": slug, "country": None,
                      "period": f"{str(event_date)[:10]}..{_iso_shift(event_date, horizon_days)}",
                      "asof": asof, "contract_month": r["contract_month"]},
            "rows": [r], "status": "ok"}


def cot_outcome_line(n: int, slug: str, *, event_date: str, horizon_days: int, value: float,
                     contract_month=None, coverage_start=None) -> str:
    """The rendered pairing line. PUBLIC because the standing register corpus pins it directly: a line
    the corpus can only reach through a live engine run is a line the corpus stops pinning the day the
    engine changes shape.

    THE PHRASING RULE, and it is the item's whole point: this states a LEVEL OF RECORD and a MOVE OF
    RECORD, in the past tense, joined by nothing. "the regime made +12%" is forbidden -- and so is every
    quieter form of it ("delivered", "returned", "was followed by a rally", "worked"), because each one
    turns a coincidence of dates into a performance claim the record does not carry. What the line says
    is: on this report date, and across the window that followed, this one contract's settle changed by
    this much."""
    q = {"commodity": slug, "country": None, "contract_month": contract_month,
         "table": COT_OUTCOME_TABLE}
    floor = f", record begins {coverage_start}" if coverage_start else ""
    return (f"- [N{n}] {slug} settle change across the {int(horizon_days)} days after the "
            f"{str(event_date)[:10]} positioning report date (one delivery month held at both ends"
            f"{floor}): {round(float(value), 4):+g} %" + _series_tag(q))


def _cot_outcome_legs(records: list, kept: list, base: int, calls: list, *, qfn, asof) -> tuple:
    """J6 -- pair the rendered positioning context with what the tape did after. `(lines, trace)`.

    THE LANE IS THE ONE C1 BUILT, not a new one. The leg runs only when a positioning context leg
    ACTUALLY RENDERED this turn (`_positioning_rendered`), which means the row passed
    `positioning_context_violations` at the engine gate and passed the amended R9 at build time. An
    honest positioning absence renders no line, so it earns no pairing either -- the E-STREAK-NODATA
    idiom, and the reason this leg can never introduce positioning to a turn that had none.

    The OUTLOOK half of the gate is the CALLER's (`quantify` runs this only on a fenced turn) AND is
    structurally guaranteed here anyway: on an outlook turn `quantify` drops every POSITIONING_TABLES
    node before it ever reaches a spec, so `_positioning_rendered` is False and this returns empty. Two
    independent reasons for the same refusal, which is what D-OJ-17 asked for."""
    from leviathan.graphrag.numbers import outcomes as OC

    if not _positioning_rendered(records, kept):
        return [], []
    lines: list = []
    trace: list = []
    n = base
    empty = _tape_frame("", [])
    by_key = {g["key"]: g for g in kept if (g.get("row") or {}).get("table") in POSITIONING_TABLES}
    seen: set = set()
    for rec in records:
        g = by_key.get(rec.get("node_key"))
        if g is None or rec.get("status") != "ok" or not (rec.get("rows") or []):
            continue
        slug = str(g.get("commodity") or "")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        event_date = _cot_event_date(rec)
        if not event_date:
            trace.append({"slug": slug, "status": "declined", "reason": "undated_positioning_row",
                          "reads": 0})
            continue
        floor = _cot_coverage_start(slug)
        for h in OC.HORIZON_DAYS:
            if len(lines) >= COT_OUTCOME_MAX_ROWS:
                break
            entry = {"slug": slug, "event_date": event_date, "horizon_days": int(h),
                     "coverage_start": floor, "status": None, "reason": None,
                     "reads": 0}                                  # A2: J6's read, counted at the read site
            # THE DRY RUN, the same shape J4 uses: `anchored_outcome` over an EMPTY frame answers every
            # question that does not need the tape -- the horizon family, the per-contract coverage
            # floor, and the as-of half of the clamp -- through the SAME engine, so the pre-check and
            # the real read can never disagree. This is where a pre-2025 MGEX anchor declines on
            # coverage rather than coming back as a number: its tape floor is 2025-09-09 while its COT
            # history starts 2014-03-25, so `covers()` returns legacy/straddle for eleven years of it.
            dry = OC.anchored_outcome(empty, slug=slug, event_key="cot", event_date=event_date,
                                      horizon_days=int(h), asof=asof, tape_edge=None)
            d_status, d_reason = str(dry.get("status") or ""), dry.get("decline_reason")
            if d_status == OC.STATUS_PENDING:
                entry.update(status="pending", reason="horizon_open",
                             horizon_close_date=dry.get("horizon_close_date"))
                trace.append(entry)
                continue
            if d_reason and d_reason != OC.DECLINE_NO_ANCHOR_SESSION:
                entry.update(status="declined", reason=d_reason)
                trace.append(entry)
                continue
            rows = _cot_outcome_read(qfn, slug=slug, event_date=event_date, horizon_days=int(h),
                                     asof=asof)
            entry["reads"] = 1                                    # the one gold_cot_outcomes read, paid
            row = next((r for r in rows if str((r or {}).get("status") or "closed")
                        == OC.STATUS_CLOSED), None)
            if row is None:
                entry.update(status="declined",
                             reason=("no_outcome_row" if not rows else "not_closed"))
                trace.append(entry)
                continue
            try:
                val = float(str(row.get("value")).replace(",", ""))
            except (TypeError, ValueError):
                entry.update(status="declined", reason="unreadable_value")
                trace.append(entry)
                continue
            cm = row.get("contract_month_used") or row.get("contract_month")
            n += 1
            calls.append(_shown(_cot_outcome_call(slug, row, event_date=event_date, horizon_days=int(h),
                                                  asof=asof, value=val), round(val, 4)))
            lines.append(cot_outcome_line(n, slug, event_date=event_date, horizon_days=int(h),
                                          value=val, contract_month=cm, coverage_start=floor))
            entry.update(status="closed", reason=None, move_pct=round(val, 4),
                         contract_month=cm, handle=f"N{n}")
            trace.append(entry)
    return lines, trace



# ══ D-XL: THE PRICE-EXTREME LOCATOR (E31) ═══════════════════════════════════════════════════════════
#
# WHAT IT IS. "When was this board's own price highest (or lowest), and what was it then" -- a SELECTION
# over ONE board's own tape that returns a DATED ROW WHOLE. Two kinds and one alias, one product:
#
#   extreme           -- the tape-wide superlative. ROW A over the whole PIT-guarded tape, plus ROW B
#                        over the trailing XL_RECENT_DAYS window, suppressed when its located date
#                        equals ROW A's (`recent_equals_alltime`) and NOT READ AT ALL when the plan's
#                        scope is 'all_time' (`scope_all_time_no_row_b` -- a suppression BEFORE the
#                        read, which is the whole cost saving and is why the branch sits above run()).
#   windowed_extreme  -- the same superlative from a floor the ASK ITSELF names. ROW W is ROW A WITH A
#                        LOWER BOUND (`period_start`) -- ZERO new SQL -- routed through the SHIPPED
#                        `futures_eod_contracts.covers()` with PARSED dates; plus ROW A as the tape
#                        anchor, suppressed when ROW A's located date falls INSIDE the window
#                        (`window_contains_alltime`), on which suppression ROW W's line gains ONE
#                        engine clause naming the tape's own span.
#   the THRESHOLD ALIAS -- "has it ever been above X" IS that board's extreme, asked with a comparison
#                        the reader will make. It is an ALIAS, not a kind: the stated level enters NO
#                        field, NO row, NO payload and NO rendered line, because its product would be a
#                        comparison against a magnitude the engine NEVER READ and NEVER VALIDATED FOR
#                        UNITS. There is no field for it, on purpose.
#
# THE FOUR MEMBERSHIP CLAUSES, ALL OF THEM OR IT IS NOT IN THIS FAMILY: (i) it reads
# silver_futures_eod.settle for EXACTLY ONE `leviathan_slug` (ten currencies share this table with NO FX
# anywhere); (ii) it SELECTS rows rather than aggregating them, so the row returns WHOLE with its own
# trade_date, contract_month, settle_kind and currency; (iii) its product is a DATE plus a LEVEL on that
# date; (iv) every magnitude it renders is one the READ produced, or a QUERY PARAMETER the read used (a
# floor the ask named). Nothing on a line is computed from two served figures.
#
# WHAT IT IS NOT, AND WHY THE LINE CARRIES NO COUNT. The rendered superlative is fenced by the row's own
# MEASURED SPAN and nothing else: a population count on the line is charged `number_unbacked` by the
# shipped verifier (measured, both kinds), so `_n` rides the trace payload and the eval column instead.
# It is not a RANGE (two magnitudes as one product) and not a DISTANCE (arithmetic between two served
# figures); both stay out of scope.
#
# THE WALK IS NOT READ AND NOT TOUCHED. `_CW_BOARD_LABEL`, `_cw_register_fence`, `CW_MARKER_PREFIX` and
# `check_cascade_walk` are untouched: deriving this roster from the walk's would make a WALK CURATION
# CHANGE silently change which questions the locator answers, and would leave boards with real tape
# unreachable for no stated reason.

XL_TABLE = "silver_futures_eod"
XL_SOURCE_METRIC = "settle"          # the CARD metric, read by config_check's synthesized-price fold
XL_METRIC = "located price extreme"  # the READER-WORD metric on the citation label -- a string NO card
#                                      declares, and deliberately KIND-FREE: metric='settle' degrades to
#                                      the bare machine token on a session-close row, because
#                                      `citations._kind_conflict` correctly refuses the card's
#                                      "settlement price" label there. A kind-free phrasing means
#                                      `_kind_conflict` can never fire on the locator's metric at all.

XL_CAP = 2                    # ROW A + ONE windowed row. Never three: the alias saves a read, it never
#                               buys one, and no branch in this leg reads a third.
# FIX-PASS (review major 1 / refute major 2, MEASURED): "no branch reads a third" was a CLAIM, and it was
# FALSE. A windowed ask whose ROW W missed (or whose window was too thin) set `kind = "extreme"`, and
# control then FELL INTO the ROW B branch and spent a THIRD read -- reproduced with a counting qfn at
# reads == 3, outcome 'fired'. TWO FENCES CLOSE IT, and they close different halves:
#   (a) `row_b_allowed`, LATCHED FROM THE KIND AT ENTRY, before the windowed block can mutate it. This is
#       the PRODUCT half: a trailing-window row is a scope the windowed ask never named, so a fallback
#       must ship the whole-record row ALONE (which is also what the rendered note now says, singular).
#   (b) `pay["reads"] < XL_CAP` on the ROW B branch. This is the BUDGET half, and it is deliberately
#       REDUNDANT with (a) -- the ceiling is stated in CODE at the one site that could ever breach it,
#       instead of only in this comment. With (a) in place `reads` is always 1 here; the conjunct is the
#       second fence, and `pay['reads'] <= XL_CAP` is pinned on every fixture in the leg's own suite.
XL_RECENT_DAYS = 730          # the trailing window that defines "the most recent high" (G0b-calibrated)
XL_MIN_HOP_DAYS = 45          # below this the second hop is DEGENERATE -- two clocks that are one clock
XL_DRIVER_FAN = 3             # grounded driver slices the hop may take episodes on, before the root
XL_EV_K = 5                   # the hop's ONE retrieval's k
XL_MIN_WINDOW_DAYS = 180      # the SHORTEST window `windowed_extreme` will accept, in CALENDAR days: a
#                               "since last month" window makes "highest" vacuous, and a FUTURE floor
#                               fails this clause too (it is a single `since <= asof - N` compare).

XL_MIN_WINDOW_ROWS = None
"""D-XL windowed kind -- ROW W's OWN population floor, DENOMINATED IN THE UNIT IT IS CHARGED ON.

`no_rows_in_window` fires only on ZERO prints and XL_MIN_WINDOW_DAYS is measured on the DECLARED
CALENDAR window, not on the served data -- so a stalled board could yield "the highest corn settle since
2026-01" over two prints, rendered as a fact. ROW W therefore carries its own gate, evaluated on ROW W's
OWN measured `_n`.

THE UNIT, STATED FIRST: `_n` is `COUNT(settle) OVER ()` computed AFTER the WHERE, so on ROW W it counts
PRICED EXPIRY-ROWS inside the window -- a union-of-expiries count, NOT a session count. A floor derived
from sessions and charged on rows is meaningless.

THE COMPARATOR IS `<`, and a window whose `_n` EQUALS the floor SERVES. That is the fail-open direction
on the boundary, chosen deliberately: a budget must never bind on a legitimate shape, and this floor's
whole purpose is the degenerate case, which is strictly below it.

THE RULE, WHICH IS A RULE AND NOT A NUMBER:
    XL_MIN_WINDOW_ROWS := max(2, floor(XL_MIN_WINDOW_SESSIONS x D_min))
      D_min = the MINIMUM over the roster of a board's measured PRICED EXPIRY-ROWS PER PRICED SESSION on
              the served tape (G0b's second clause emits both numbers, so the ratio is a division of two
              numbers it already has); XL_MIN_WINDOW_SESSIONS = 10, two trading weeks.
IT SHIPS PENDING G0b AND CARRIES NO CANDIDATE DEFAULT -- there is no number here to mistake for a
decision. `None` is the honest value until G0b runs, and `answer._xl_kinds_served()` REFUSES to arm the
windowed sub-flag while it is None (the K32 kill, enforced rather than remembered). The shortest window
this kind accepts is 180 calendar days, ~124 trading sessions, i.e. ~124 x D_min priced rows against a
floor of ~10 x D_min -- a 12.4x margin in the SAME unit on the SAME board -- so it cannot bind on a
legitimate window once it is set."""
XL_MIN_WINDOW_SESSIONS = 10   # the rule's other half, named here so G0b sets ONE number, not two

XL_BLOCK_SHA256 = "b8c32b17f63e26afb8eaec37ea72da3271a8bce5af88cf97a39e71cf57995f5b"
"""THE MEASURED PLANNER BLOCK'S sha256, with THIS roster substituted -- the pin that makes the freeze
real, asserted by `config_check.check_extreme_locator` clause (10) against `dispatch._xl_block`'s own
render. It lives HERE, beside the roster it is a hash OF, because the roster is part of the measurement:
a board joining the roster changes the enum the block renders, and therefore changes this sha.

WHY A FREEZE AT ALL. One author cannot write both a prompt and its held-out set -- the gate then grades
the prompt against its own answer key -- so the block is frozen, the held-out asks are authored BLIND to
it, and the graded pass is a ONE-SHOT measurement of a frozen artefact. AN EDIT VOIDS THE FREEZE AND
CONSUMES THE HELD-OUT SET: a new block needs a new held-out file authored blind to it, and a fresh
billed run. Re-hashing this constant to make a lint pass is the exact move it exists to refuse."""

XL_KINDS = ("extreme", "windowed_extreme")
"""THE ONE LITERAL. The planner enum, the validator's `_K_SERVED`, the probe's own read and this engine's
branches are all minted from it, so a CUT kind is ABSENT by construction rather than by a runtime check.
There is no "threshold" member and no "level_analog" member: both cuts are STRUCTURAL."""

XL_DENY_SLUGS = frozenset({
    # CME settlement MARKS on a zero-volume board financially settled to the MONTHLY AVERAGE of the
    # Bursa third-forward FCPO settlement: a date inside its own delivery month is a running average,
    # not a traded price, so "when was it highest" has no traded answer (card note).
    "malaysian_crude_palm_oil_cme",
    # Acknowledged IFEU priced-leg contamination on the card's own note.
    "robusta_coffee", "white_sugar",
})
# The two CEPEA CASH references are excluded STRUCTURALLY rather than by a second hand-kept list:
# `contract_month` is NULL for exactly those two BY DESIGN, the card's three-part quote is mandatory, and
# `futures_eod_contracts.CASH_INDEX_SLUGS` is the shipped set that names them -- so the roster derives
# their absence from the PRODUCER'S OWN discriminator.

XL_BOARD_LABEL = {
    "arabica_coffee": "ICE arabica coffee",
    "canola_ice": "ICE canola",
    "cocoa": "ICE cocoa",
    "corn_cbot": "CBOT corn",
    "cotton": "ICE cotton",
    "frozen_orange_juice": "ICE orange juice",
    "hard_red_winter_wheat_kcbt": "KCBT hrw wheat",
    "rapeseed_meal_zce": "ZCE rapeseed meal",
    "rapeseed_oil_zce": "ZCE rapeseed oil",
    "raw_sugar": "ICE raw sugar",
    "rough_rice_cbot": "CBOT rice",
    "soft_red_winter_wheat_cbot": "CBOT srw wheat",
    "soybean_meal_cbot": "CBOT soybean meal",
    "soybean_oil_cbot": "CBOT soybean oil",
    "soybeans_cbot": "CBOT soybeans",
}
"""THE ROSTER, A LITERAL -- the `_CW_BOARD_LABEL` precedent, and a literal for a MEASURED reason.

A dict BUILT from `display._contract_label` cannot be LINTED against it (the check is then a tautology),
and `display._contract_label` falls back to `slug.replace("_", " ")` for a slug the image-side hierarchy
does not map -- a DE-UNDERSCORED SLUG, which `register.internal_leaks` does NOT catch (measured: the raw
slug IS caught, the de-underscored form is not). The reader LINE renders THIS label, so hierarchy drift
in a gitignored config fails the LINT instead of reaching a reader, and `check_extreme_locator` binds the
literal against the producer BOTH WAYS plus a de-underscored-slug refusal.

ADMISSION: every slug in `futures_eod_contracts.PRICE_COVERAGE_START` that is (a) not in XL_DENY_SLUGS,
(b) not in `futures_eod_contracts.CASH_INDEX_SLUGS`, and (c) clears the ROSTER GATE
(`query.XL_ROSTER_MIN_SPAN_DAYS`). 26 mapped slugs -> 15 serve; the 11 exclusions are ENUMERATED by the
lint so the boundary is visible rather than silent."""

XL_BOARD_SLUGS = tuple(XL_BOARD_LABEL)

# THE DECLINE VOCABULARY. Every string is `register_leaks` / `exec_leaks` clean and `sanitize()`-stable,
# and `check_extreme_locator` clause (5) asserts it. Most are TRACE-ONLY (they name a counted outcome);
# the two that RENDER are marked, and they render as their own words-only sentence beside the rows.
XL_DECLINE_TEMPLATES = {
    # -- dispatch / roster scope ---------------------------------------------------------------------
    "board_unresolved": "no single exchange board was identified for this question",
    "deny_listed": "this board's prints are not a traded price this leg will call a record",
    "label_unresolved": "this board has no settled reader name, so no line is rendered for it",
    # -- card / axis scope ---------------------------------------------------------------------------
    # THESE THREE ARE THE READ LAYER'S OWN REFUSALS, SURFACED RATHER THAN SWALLOWED (refute minor 7), and
    # each one is CLASSIFIED BY THE NAME ITS RAISER STAMPS rather than by a substring of its message
    # (re-review NEW 3 -- see `XL_READ_ERROR_REASONS`). `_xl_read` used to catch every raise and report
    # `no_rows`, which is absence credited as a coverage fact inside the counter that exists to make the
    # boundary visible; the leg's suite now drives all four shipped raises through `_xl_read_reason` and
    # reads each name back, so no name is credited by absence and none is credited to the wrong fact.
    # `month_only_card` IS THE NAME THE SUBSTRING TABLE COULD NOT STATE: a `year_month` card carries no
    # release stamp AND no per-observation date, so filing it as `vintage_card` told the reader the
    # opposite of what the raise says. `extrema_axis_unavailable` has THREE producers and one reader
    # sentence -- `_extreme_window`'s missing `date_col`, `build_sql`'s missing chronological column, and
    # the extrema-clock rider at the derived lane's ordinal-when-thin rung.
    "vintage_card": "this source records a release stamp rather than an observation date",
    "month_only_card": "this source records whole months rather than dated observations",
    "extrema_axis_unavailable": "this source carries no observation date to place an extreme on",
    # -- tape scope ----------------------------------------------------------------------------------
    "no_rows": "no priced print was returned for this board at this cutoff",
    "tape_too_short": "this board's record is too short to carry a superlative",
    "recent_window_straddle": ("the recent window reaches back past the start of the record this board "
                               "is served from"),
    # -- suppressions (counted on the same axis as declines) ------------------------------------------
    "recent_equals_alltime": "the recent high and the whole-record high are the same print",
    "scope_all_time_no_row_b": "the question asks across the whole record, so no recent window is read",
    "window_contains_alltime": "the whole-record high falls inside the window the question named",
    # -- windowed scope ------------------------------------------------------------------------------
    # ALL FIVE OF THESE RENDER (refute major 4). Every one of them DROPS THE FLOOR THE ASK NAMED and
    # substitutes the whole-record row, and until this fix only `window_straddles_coverage` told the
    # reader so: on the other four the WHOLE-TAPE row shipped with `since=None`, the mandate's "echo the
    # starting point the question gave" clause was vacuous, and a compliant writer answered "the highest
    # since 2020" with the 2012 tape-wide high. They now render a PRICE EXTREME NOTE on the straddle's
    # own pattern -- see `XL_RENDERED_DECLINES` and `_xl_notes`.
    "since_unparseable": "the starting point named in the question is not a date this leg can read",
    "window_too_short": "the window named is too short for a superlative to say anything",
    "window_straddles_coverage": ("the record this board is served from begins later than the starting "
                                  "point named"),
    "no_rows_in_window": "no priced print falls inside the window named",
    "window_too_thin": "too few priced prints fall inside the window named to call one of them a record",
    # THE FALLBACK'S OWN SUPPRESSION, NAMED AND COUNTED (review major 1 / minor 2). On any windowed ->
    # extreme fallback the trailing recency window is a scope the ask never named, so ROW B is not read;
    # `scope_all_time_no_row_b` is the precedent -- a suppression counted on the decline axis.
    "window_fallback_no_row_b": ("the question named a starting point, so no trailing recent window is "
                                 "read beside the whole-record one"),
    # ...and the ROW B MISS, which is a DIFFERENT FACT from `no_rows_in_window` above (review minor 1):
    # that one says the ASK'S OWN named window was empty, this one says the ENGINE'S trailing recency
    # window was. One name for two facts made the closed decline census unable to separate them.
    "no_rows_in_recent_window": "no priced print falls inside the recent window this leg reads",
    # -- hop scope -----------------------------------------------------------------------------------
    "hop_degenerate": "the located date is too close to this question's cutoff to recount separately",
    "timeline_off": "dated windows are not being read on this turn",
    # -- belt ----------------------------------------------------------------------------------------
    "fenced": "the rendered block did not clear its own reader fence",
    "error": "this leg did not complete",
}

XL_RENDERED_DECLINES = ("window_straddles_coverage", "since_unparseable", "window_too_short",
                        "no_rows_in_window", "window_too_thin")
"""THE DECLINES THAT REACH THE READER, as their own words-only sentence beside the rows.

EXACTLY THE FIVE WINDOWED FALLBACKS, and the membership rule is a rule rather than a taste: a decline
RENDERS iff it changed the SCOPE of the figure the reader is about to be shown. All five drop the floor
the ask named and substitute the whole-record row; every other name in the vocabulary either declines the
leg outright (nothing renders) or suppresses a row the ask never asked for, and narrating those would
tell a reader about a row that is not there.

AT MOST ONE FIRES PER TURN by construction -- the windowed block is one if/elif chain and each branch
exits it -- so the note is singular, and with the ROW B latch above the block it heads is singular too."""

XL_SCOPE_NOTE_TAIL = "The figure below is the whole-record one."
"""THE ONE SENTENCE THAT MAKES THE SCOPE SUBSTITUTION VISIBLE, appended to every fallback note.

It is what makes the guarantee TOTAL rather than per-reason: a windowed ask that falls to the whole-record
row ALWAYS renders a note, and when the reason is not one a reader can act on (a read that RAISED) this
sentence ships ALONE -- the reader is told the scope moved without being handed an internal failure. It
is SINGULAR because the ROW B latch guarantees exactly one row below it."""

# THE VOCABULARIES ARE BUILT FROM THE SHIPPED SOURCES, NEVER HAND-SPELLED. The print-kind slot is an
# alternation over `citations._SETTLE_KIND_WORDS.values()` (4 measured); the unit slot over the card's
# own `unit_overrides.values()` (11 distinct, including 'BRL/60-kg bag'); the board slot over
# XL_BOARD_LABEL's values (15). A NULL contract_month can never reach the template because the two
# cash-index slugs are off-roster BY CONSTRUCTION.


def _xl_kind_words() -> list:
    from leviathan.graphrag import citations as _cit
    return sorted(set(_cit._SETTLE_KIND_WORDS.values()))


def _xl_unit_words() -> list:
    try:
        from leviathan.graphrag.numbers.registry import load_registry
        ov = getattr(load_registry().get(XL_TABLE).metrics.get(XL_SOURCE_METRIC),
                     "unit_overrides", None) or {}
        return sorted({str(u) for u in ov.values() if str(u or "").strip()})
    except Exception:  # noqa: BLE001 -- a registry problem must never take the module import down
        return []


def _xl_alt(words) -> str:
    return "|".join(re.escape(w) for w in words) or r"(?!)"


_XL_KIND_ALT = _xl_alt(_xl_kind_words())
_XL_UNIT_ALT = _xl_alt(_xl_unit_words())
_XL_LABEL_ALT = _xl_alt(sorted(XL_BOARD_LABEL.values(), key=len, reverse=True))
_XL_SINCE_TOKEN = r"\d{4}(?:-\d{2}(?:-\d{2})?)?"

XL_ROW_LINE_RX = re.compile(r"^- \[N\d+\] (?:" + _XL_LABEL_ALT + r") settle (?:high|low)\b", re.M)
"""THE SEAM MARKER -- A ROW SHAPE, NEVER A BARE TOKEN, and that is mandatory rather than stylistic:
retrieved evidence text is rendered RAW with its newlines into the volatile prompt, so a bare marker
token is something a retrieved numbered heading can carry (the measured V2-1 refute M2). Minted ONCE
here and read by the producer AND by `answer._extreme_locator_block_on`. The label alternation is built
from the LITERAL roster, so the marker cannot drift with a hierarchy edit."""

_XL_ROW_RX = re.compile(
    r"^- \[N\d+\] (?:" + _XL_LABEL_ALT + r") settle (?:high|low)"
    r"(?: since " + _XL_SINCE_TOKEN + r")?"
    r" on \d{4}-\d{2}-\d{2}: [-+]?[\d,]+(?:\.\d+)? (?:" + _XL_UNIT_ALT + r")"
    r", delivery \d{4}M\d{2}, (?:" + _XL_KIND_ALT + r")"
    r"; (?:highest|lowest) across every delivery month listed"
    r", read from \d{4}-\d{2}-\d{2} to \d{4}-\d{2}-\d{2}"
    r"(?:; the whole-record span for this board runs from \d{4}-\d{2}-\d{2} to \d{4}-\d{2}-\d{2})?"
    r" \[series: [^\[\]]+\]\.$")
"""THE FULL TEMPLATE, fullmatched per row. A POSITIONAL GRAMMAR, and it is a DECLARED DEVIATION from the
walk's one-clock-per-line rule WITH ITS REASON: `_cw_register_fence` requires exactly ONE dated window
token per row, which a located-extreme row cannot satisfy -- it must carry the SESSION date (its citation
clock), the DELIVERY month (the card's mandatory three-part quote) and the READ SPAN (the superlative's
own fence). Binding every date on the line to a NAMED ROLE BY ITS SLOT is strictly stronger than "there
is exactly one of them"."""

XL_HOP_PREFIX = "AT THAT TIME for "
XL_HOP_TOKEN = "[XLHOP]"           # minted ONCE, here
XL_HOP_LINE_RX = re.compile(r"^" + re.escape(XL_HOP_PREFIX) + re.escape(XL_HOP_TOKEN)
                            + r" [^:\n]+, \d{4}-\d{2}\.\.\d{4}-\d{2}: ", re.M)
"""THE HOP'S OWN ROW SHAPE -- the `CW_CONTEXT_LINE_RX` discipline verbatim: the prefix, a MINTED TOKEN in
brackets, a node label from the resolver's own vocabulary, and a dated window token. A bare prefix would
match a retrieved chunk that happens to open with those words ("AT THAT TIME for corn, the 2012 drought
was severe."), which is the same class the walk's context gate hardened against."""

# -- M5: THE SUPERLATIVE COUNTER'S VOCABULARY (read by answer.py's arm-constant counter) ---------------
# A sentence is CONVICTED iff it matches the superlative pattern and NOT the span pattern. The counter
# ships on BOTH arms and CHANGES NO BYTE; the whole-sentence REMOVAL is a LATER commit with its own flag
# and its own arm (the extrema-clock precedent), because the class the removal reaches is provably NOT
# empty on the control arm -- a treatment-gated strip would make the arm compare two different render
# passes instead of two blocks.
_XL_SUPERLATIVE_RX = re.compile(
    r"all[- ]time|on record|its record|record (?:high|low)s?|the full (?:record|history)"
    r"|(?:highest|lowest|widest|biggest) ever|ever (?:printed|traded|settled|reached|seen)", re.I)
_XL_SPAN_CLAUSE_RX = re.compile(
    r"\d{4}-\d{2}-\d{2}\s*(?:to|\.\.|-)\s*\d{4}-\d{2}-\d{2}"      # a date-to-date range
    r"|\b\d{4}\s*(?:to|\.\.|-)\s*\d{4}\b"                          # a year-to-year range
    r"|in\s[\d,]+\spriced prints"                                  # the population form
    r"|\bsince\s\d{4}", re.I)                                      # an explicit floor

# -- K27c: THE THRESHOLD ALIAS'S OWN COUNTERS' VOCABULARIES (read by eval.py, scoped to LOCATOR-CITED
# sentences there exactly as the mandate's clauses are scoped to locator rows here) -------------------
# THE ALIAS IS THE WHOLE REASON THESE EXIST. "Has corn ever been above 800" IS that board's extreme,
# asked with a comparison the reader will make -- and the engine NEVER READ the 800, never validated its
# units and has no field for it. Two failure shapes follow, and both are prose-only, so the mandate bans
# them (K27b) and these count them (K27c):
#   xl_threshold_echo    -- the stated level is ECHOED as a figure beside the located row's [N] handle,
#                           where it reads as something the engine served. Counted in eval against the
#                           SERVED row values at scale 1 (`verify._num_backed`), so a correctly
#                           transcribed served figure is never charged and only an unserved magnitude is.
#   xl_threshold_verdict -- the yes/no ANSWER TO THE COMPARISON is stated as the engine's own verdict.
#                           The engine compared nothing; the reader makes the comparison.
_XL_VERDICT_RX = re.compile(
    r"^\s*(?:yes|no)\b"                                            # a bare verdict opening the sentence
    r"|\bit (?:has|has not|hasn't|had|never has)\b"
    r"|\b(?:has|have|had)\s(?:never|not|indeed)?\s*(?:been|traded|settled|printed|closed|gone|risen"
    r"|fallen)\s(?:above|below|over|under|through|past|beyond)\b"
    r"|\bnever (?:been|traded|settled|printed|closed|reached|exceeded)\b"
    r"|\b(?:the answer is|so yes|so no)\b", re.I)
# xl_window_duration_gloss -- the mandate's "echo that starting point exactly as the row writes it, and
# never restate it as a length of time" clause, counted. A row that names a FLOOR ("since 2020") restated
# as a SPAN ("over the past five years") is a different claim: the floor is the ask's own calendar point,
# the span is arithmetic against today that this engine never did.
_XL_DURATION_RX = re.compile(
    r"\b(?:in|over|across|during|for|through|within)\s+the\s+(?:last|past|previous|preceding)\s+"
    r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|few|several)\s+"
    r"(?:day|week|month|quarter|year|decade)s?\b"
    r"|\b(?:the\s+)?(?:last|past)\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven"
    r"|twelve)[- ](?:day|week|month|quarter|year|decade)s?\b", re.I)


def _xl_fmt(v) -> str:
    """ONE FORMATTER, and it is `citations._fmt` ITSELF rather than a copy of it -- the drift class is
    removed instead of linted. (A hand `f'{v:,.1f}'` in an early probe emitted '11,722.0' where the leg
    emits '11,722'; the lint still pins the equality on a fixed probe set so a future divergence is a
    build failure rather than a rendering surprise.)"""
    from leviathan.graphrag import citations as _cit
    return _cit._fmt(v)


def _xl_span_days(row: dict) -> int | None:
    a, b = str(row.get("_span_start") or "")[:10], str(row.get("_span_end") or "")[:10]
    if len(a) != 10 or len(b) != 10:
        return None
    try:
        return _iso_days(b) - _iso_days(a)
    except (TypeError, ValueError):
        return None


def _xl_row_line(n: int, slug: str, row: dict, *, direction: str, since: str | None = None,
                 tape_span: tuple | None = None) -> str:
    """THE READER LINE. The BOARD LABEL comes from the LITERAL and rides its OWN tag dict, so
    `_series_tag` renders 'series: CBOT soybean meal' while the CALL RECORD keeps the RAW SLUG in
    `query.commodity` -- the `_cw_call` law verbatim: a display label in the query poisons the citations
    LOCATOR, because the /v1/series chart params read `loc.commodity` unresolved.

    NO POPULATION COUNT ON THE LINE. The SPAN alone carries the superlative's fence; a rendered count is
    charged `number_unbacked` by the shipped verifier (measured on both kinds), so `_n` rides the trace
    payload and the `xl_n_prints` eval column instead."""
    from leviathan.graphrag import citations as _cit
    label = XL_BOARD_LABEL[slug]
    word = "high" if direction == "max" else "low"
    sup = "highest" if direction == "max" else "lowest"
    cm = _contract_seg(row.get("contract_month"))
    q = {"commodity": label, "country": None, "contract_month": row.get("contract_month"),
         "table": XL_TABLE}
    since_clause = f" since {since}" if since else ""
    tape_clause = ""
    if tape_span:
        tape_clause = (f"; the whole-record span for this board runs from {tape_span[0]} to "
                       f"{tape_span[1]}")
    return (f"- [N{n}] {label} settle {word}{since_clause} on {str(row.get('knowledge_date'))[:10]}: "
            f"{_xl_fmt(row.get('value'))} {row.get('unit') or ''}, delivery {cm}, "
            f"{_cit._print_kind(row)}; {sup} across every delivery month listed, read from "
            f"{str(row.get('_span_start'))[:10]} to {str(row.get('_span_end'))[:10]}{tape_clause}"
            + _series_tag(q) + ".")


def _xl_call(slug: str, row: dict, asof) -> dict:
    """The synthetic call-record the [N] handle indexes -- the `_episode_outcome_call` shape.

    THE CLOCKS, ONE PER SURFACE, AND NEVER CONFLATED. `query.asof` is THE TURN'S AS-OF, full stop: it is
    the cutoff the read actually used, so the span the line states, the locator and `eval._pit_clean` all
    agree by construction and a drill-down reproduces the same row. The OBSERVATION's date rides twice --
    as `knowledge_date` (so `citations._row_known_date` stamps `[known <D>]` with no render change) and
    as `located_extreme` (which suppresses the false staleness clause and mints `locator.located_date`).

    IT IS BUILT FROM THE POST-run() ROW, never from the compiled SELECT: `_apply_unit_overrides` stamps
    `r['unit']` after the fetch, and a row without it renders '= 554.4 (exchange settlement, USD)' --
    the unit gone and the currency promoted into the tag list."""
    d = str(row.get("knowledge_date"))[:10]
    r = {"value": row.get("value"), "unit": row.get("unit"),
         "knowledge_date": d, "contract_month": row.get("contract_month"),
         "settle_kind": row.get("settle_kind"), "currency": row.get("currency"),
         "source_metric": XL_SOURCE_METRIC,   # the CARD metric, so a client can draw the level series
         "located_extreme": d,                # the OBSERVATION's date (E28 suppression + E29 rider)
         "_provenance": {"date": d}}
    return {"query": {"table": XL_TABLE, "metric": XL_METRIC, "commodity": slug, "country": None,
                      "period": None, "asof": asof, "contract_month": row.get("contract_month")},
            "rows": [r], "status": "ok"}


class _XlReadFailure:
    """THE THIRD STATE OF A READ, and it exists because two of them were being reported as one.

    `_xl_read` swallowed EVERY exception and returned None, and the caller then declined `no_rows`, whose
    reader sentence is "no priced print was returned for this board at this cutoff" -- so a throttled
    Athena, a dead pool or a card-axis refusal was COUNTED AND WORDED AS A COVERAGE FACT (refute major 6,
    reproduced with a qfn raising RuntimeError('athena throttled'): declines == ['no_rows']). That
    corrupts the decline census the "declines are named and counted" law exists to make trustworthy, and
    it reads as a tape gap in every eval artifact.

    An EMPTY result still returns None (no rows is a real, different fact). A RAISE returns THIS, carrying
    the classified reason, and every call site branches on it BEFORE the emptiness test."""

    __slots__ = ("reason",)

    def __init__(self, reason: str):
        self.reason = reason


XL_READ_ERROR_REASONS = ("vintage_card", "month_only_card", "extrema_axis_unavailable")
"""THE CLOSED SET OF NAMES A READ REFUSAL MAY CARRY -- the card-axis boundaries the SHIPPED query layer
raises, each of which has its own reader sentence in `XL_DECLINE_TEMPLATES`. Anything else is `error`.

WHY THIS IS A NAME LIST AND NO LONGER A SUBSTRING TABLE (re-review NEW FINDING 3, MEASURED). It shipped
as `(("release stamp", "vintage_card"), ("extrema_axis_unavailable", "extrema_axis_unavailable"))` and
classified by scanning the exception's MESSAGE. `build_sql`'s extreme branch raises FOUR distinct
messages, not two, and the `year_month` one -- "...declares knowledge_semantics='year_month', which
carries no release stamp and no per-observation date at all -- an extreme cannot be DATED on it" --
CONTAINS the substring "release stamp" while SAYING the card has none. It was therefore filed as
`vintage_card`, whose reader sentence is "this source records a release stamp rather than an observation
date": the exact opposite of the raise. A prose message is written for a human and a reword silently
demotes a named boundary -- which is the same "a named boundary credited by absence" shape refute minor 7
was raised about. The query layer now STAMPS its own name on the exception (`query._extreme_refusal`,
`query.XL_REFUSAL_ATTR`) and this classifier reads that attribute alone.

FOUR RAISES, THREE NAMES. `year_month` -> `month_only_card` (minted here); the vintage refusal ->
`vintage_card`; and BOTH axis refusals -- `_extreme_window`'s missing `date_col` and `build_sql`'s
missing chronological column -- -> `extrema_axis_unavailable`, which is the same fact stated at two
rungs and already the one-name-two-producers case its template documents."""


def _xl_read_reason(exc) -> str:
    """Classify a read failure into the decline vocabulary, on the EXPLICIT MARKER the raiser stamped.

    Anything without a marker -- an Athena outage, a dead pool, a bug -- is `error`, an honest 'this leg
    did not complete' and never a coverage claim. The marker is checked against the CLOSED set, so a
    name the vocabulary does not carry cannot reach the decline census through a stray attribute."""
    reason = getattr(exc, Q.XL_REFUSAL_ATTR, None)
    return reason if reason in XL_READ_ERROR_REASONS else "error"


def _xl_read(qfn, *, slug: str, asof, agg: str, period_start: str | None = None,
             futures_newest_first: bool | str = False):
    """ONE bounded extreme-row read -> the single row, None for NO ROWS, or `_XlReadFailure` for a RAISE.
    NEVER raises.

    ROW A is SLUG-PRUNED, ALL YEARS (the only partition terms are the slug equality and the as-of year
    bound); ROW W / ROW B carry a floor-year bound as well and ARE year-pruned. `spec.limit` is ignored
    by construction on this branch -- `LIMIT 1` cannot truncate."""
    try:
        spec = Q.NumberQuery(table=XL_TABLE, metric=XL_SOURCE_METRIC, asof=asof, commodity=str(slug),
                             country=None, agg=agg, period_start=period_start)
        rows = Q.run(spec, query_fn=qfn, futures_newest_first=futures_newest_first) or []
    except Exception as e:  # noqa: BLE001 -- a bad or slow lookup must NEVER kill the reasoning turn (R6)
        return _XlReadFailure(_xl_read_reason(e))
    return rows[0] if rows else None


def _xl_parse_since(s) -> object:
    """A REAL PARSE, not a shape test. The validator's regex fullmatches '2026-13' and '2026-06-31' and
    `date.fromisoformat` raises on both, so this wraps the parse and the caller COUNTS the failure rather
    than trusting a regex to have validated a calendar. Measured: '2020' -> 2020-01-01, '2020-02' ->
    2020-02-01, '2020-02-29' -> a real leap day; '2021-02-29', '2026-13', '2026-06-31' -> None."""
    import datetime as _dt
    t = str(s or "").strip()
    if len(t) == 4:
        t += "-01-01"
    elif len(t) == 7:
        t += "-01"
    try:
        return _dt.date.fromisoformat(t)
    except (TypeError, ValueError):
        return None


def _xl_register_fence(lines: list) -> bool:
    """HALF ONE of the fence -- WHOLE-BLOCK ATOMIC and NEVER RELAXABLE: every line must satisfy
    `pace_register_ok` AND zero valuation words AND zero flow words AND an EMPTY `internal_leaks`. Any
    failure drops the WHOLE block and the caller rolls `calls[base:] = []` (the W4 orphan-call class).

    HALF TWO is PER-ROW and lives at the append site, because per-row dropping is only safe under
    FENCE-BEFORE-MINT: candidates are built PURE, fenced individually, and survivors are numbered AT
    APPEND TIME -- so no handle is ever orphaned or renumbered."""
    from leviathan.graphrag import register as reg
    for ln in lines or []:
        if not (pace_register_ok(ln) and reg.count_valuation_words(ln) == 0
                and reg.count_flow_words(ln) == 0 and not reg.internal_leaks(ln)):
            return False
    return True


def _xl_locate(qfn, request: dict, asof, *, futures_newest_first: bool | str = False) -> tuple:
    """THE SELECTION HALF: resolve the request into (candidates, payload). PURE of the ledger -- it mints
    no [N] handle and appends to no call list; the caller fences and numbers.

    Each candidate is `{"slug", "row", "direction", "since", "tape_span"}`. `payload` is the leg's ONE
    registered trace key's body: `kind` rides INSIDE it, as `outcome` does, so `tracekeys` gains nothing
    beyond the two appends this commit makes."""
    from leviathan.silver import futures_eod_contracts as _fc

    slug = str((request or {}).get("board") or "")
    direction = str((request or {}).get("direction") or "")
    kind = str((request or {}).get("kind") or "extreme")
    scope = (request or {}).get("scope")
    since = (request or {}).get("since")
    # THE ALIAS SCOPE RULE, ON THE EXPECTATION SIDE AS WELL AS THE EMISSION SIDE (refute minor 3). The
    # v4.1 fatal is closed in `dispatch._validate`, which FORCES `xl_scope` to None on `windowed_extreme`
    # -- and this engine relied on that by COMMENT. Measured: calling `_xl_locate` directly with
    # kind='windowed_extreme', scope='all_time' and an empty ROW W left the request's scope live, so
    # `scope_all_time_no_row_b` fired after the fallback. The family amendment required the rule on BOTH
    # sides; here it is, one line, at the top, before any branch can read it.
    if kind == "windowed_extreme":
        scope = None
    # `kind` MUTATES on a windowed fallback (that is the design: the kind falls to extreme, never to
    # nothing), so the ASK's own kind is preserved here for the artifact. `eval.xl_kind_exact` compares
    # the PLANNER's kind against THIS, never against the mutated one -- otherwise a legitimate straddle
    # scored a planner mismatch and an arm gating that column at 1.0 failed on every straddle turn
    # (refute minor 2, measured).
    pay: dict = {"outcome": "declined", "kind": kind, "kind_requested": kind, "board": slug,
                 "direction": direction, "scope": scope, "since": since, "reads": 0,
                 "rows_fenced": 0, "declines": []}

    def _decl(reason: str, **kw):
        pay["declines"].append({"reason": reason, **kw})
        return [], pay

    # THE DENY/CASH TEST RUNS FIRST, AND THE ORDER IS THE DIAGNOSTIC. A deny-listed or cash-reference
    # slug is ALSO off-roster by construction, so a roster-membership test placed first would report
    # every one of them as `board_unresolved` and the named reason would be structurally unreachable --
    # absence credited as a pass, in the counter that exists to make the exclusion visible.
    if slug in XL_DENY_SLUGS or slug in _fc.CASH_INDEX_SLUGS:
        return _decl("deny_listed", board=slug)
    if slug not in XL_BOARD_LABEL:
        return _decl("board_unresolved", board=slug)
    if direction not in ("max", "min"):
        return _decl("board_unresolved", board=slug)
    label = XL_BOARD_LABEL[slug]
    if not label or label == slug.replace("_", " "):
        # A DE-UNDERSCORED SLUG IS THE ONE LEAK SHAPE `register.internal_leaks` DOES NOT CATCH, which is
        # why the roster is a literal and why this is a serve-time decline as well as a lint failure.
        return _decl("label_unresolved", board=slug)
    pay["label"] = label
    agg = "max_row" if direction == "max" else "min_row"

    # -- ROW A: the tape-wide read, ALWAYS, and the ONLY row the TAPE GATE is evaluated on -------------
    row_a = _xl_read(qfn, slug=slug, asof=asof, agg=agg, futures_newest_first=futures_newest_first)
    pay["reads"] += 1
    if isinstance(row_a, _XlReadFailure):
        # A RAISE IS NOT A TAPE GAP. The read is still CHARGED (it may have been billed) and the reason
        # is the read layer's own, never `no_rows`.
        return _decl(row_a.reason, board=slug, at="row_a")
    if not row_a or row_a.get("value") is None or not row_a.get("knowledge_date"):
        return _decl("no_rows", board=slug)
    n_prints = int(row_a.get("_n") or 0)
    span_days = _xl_span_days(row_a)
    # THE TWO FLOORS, RECORDED SIDE BY SIDE AND NEVER CONFLATED. `span_start` is the MEASURED first
    # priced print on the served tape -- the fact the row's own line states. `coverage_floor` is the
    # shipped map's declared floor for the same board, carried here as a CROSS-CHECK ONLY: it is never
    # rendered and never substituted, so a disagreement between the map and the tape is visible in the
    # artifact instead of silently deciding what a reader is told.
    try:
        _cov_floor = str(_fc.coverage_start_for(slug))
    except Exception:  # noqa: BLE001 -- an unmapped floor is a missing cross-check, never a raise
        _cov_floor = None
    pay.update({"n_prints": n_prints, "span_start": str(row_a.get("_span_start"))[:10],
                "span_end": str(row_a.get("_span_end"))[:10], "coverage_floor": _cov_floor,
                "located_date": str(row_a.get("knowledge_date"))[:10],
                "value": row_a.get("value"), "unit": row_a.get("unit"),
                "contract_month": row_a.get("contract_month"),
                "settle_kind": row_a.get("settle_kind"), "currency": row_a.get("currency")})
    # GATE 2, THE ROW GATE -- ROW A ONLY, and its verdict governs the WHOLE leg. Applied per row it
    # would decline the trailing window on EVERY board by construction (that window IS XL_RECENT_DAYS,
    # measured 728 days against a 1095-day floor). Both rows come off one tape; the tape is admitted
    # once. Each windowed read gets its OWN named floor on its OWN measured population instead.
    if n_prints < Q.XL_MIN_TAPE_ROWS or (span_days is not None
                                         and span_days < Q.XL_MIN_TAPE_SPAN_DAYS):
        return _decl("tape_too_short", board=slug, rows=n_prints, span_days=span_days)

    cands = [{"slug": slug, "row": row_a, "direction": direction, "since": None, "tape_span": None}]

    # THE ROW B LATCH, TAKEN BEFORE THE WINDOWED BLOCK CAN MOVE `kind` (review major 1 / refute major 2).
    # `kind` falls to "extreme" on five windowed declines; without this latch that fall re-entered the
    # ROW B branch below and spent a THIRD read past XL_CAP, and rendered a trailing-window row the ask
    # never asked for under a note whose wording is singular. The ask's OWN kind decides, once.
    row_b_allowed = (kind == "extreme")

    if kind == "windowed_extreme":
        # -- ROW W: ROW A WITH A LOWER BOUND. ZERO new SQL, ONE parsed call to the SHIPPED router. ----
        since_d = _xl_parse_since(since)
        if since_d is None:
            pay["declines"].append({"reason": "since_unparseable", "since": since})
            pay["kind"] = kind = "extreme"           # the kind FALLS to extreme, never to nothing
        else:
            import datetime as _dt
            asof_d = _dt.date.fromisoformat(str(asof)[:10])
            if (asof_d - since_d).days < XL_MIN_WINDOW_DAYS:
                pay["declines"].append({"reason": "window_too_short", "since": str(since_d),
                                        "min_days": XL_MIN_WINDOW_DAYS})
                pay["kind"] = kind = "extreme"
            elif _fc.covers(slug, since_d, asof_d) != "serve":
                # THE ARGUMENTS ARE `datetime.date`, NOT ISO STRINGS: `covers` coerces a datetime and
                # does NOTHING to a str, and both bounds meet a `datetime.date` floor -- an ISO string
                # raises TypeError. A SINGLE `!= "serve"` decline, so `straddle` AND any future fourth
                # verdict fail CLOSED to one counted name; the `legacy` verdict is unreachable from
                # THIS caller because the roster gate guarantees floor <= asof - 1095 < asof.
                pay["declines"].append({"reason": "window_straddles_coverage",
                                        "floor": str(_fc.coverage_start_for(slug)),
                                        "since": str(since_d)})
                pay["kind"] = kind = "extreme"
            else:
                row_w = _xl_read(qfn, slug=slug, asof=asof, agg=agg,
                                 period_start=since_d.isoformat(),
                                 futures_newest_first=futures_newest_first)
                pay["reads"] += 1
                if isinstance(row_w, _XlReadFailure):
                    # AGAIN: a raise is not an empty window. The kind still falls to extreme (the
                    # whole-record row is already in hand and is the honest substitute), but the counted
                    # name says the read failed rather than that the window was empty.
                    pay["declines"].append({"reason": row_w.reason, "at": "row_w"})
                    pay["kind"] = kind = "extreme"
                elif not row_w or row_w.get("value") is None or not row_w.get("knowledge_date"):
                    pay["declines"].append({"reason": "no_rows_in_window", "since": str(since_d)})
                    pay["kind"] = kind = "extreme"
                elif XL_MIN_WINDOW_ROWS is not None and int(row_w.get("_n") or 0) < XL_MIN_WINDOW_ROWS:
                    # THE COMPARATOR IS `<`: a window whose `_n` EQUALS the floor SERVES.
                    pay["declines"].append({"reason": "window_too_thin",
                                            "n": int(row_w.get("_n") or 0),
                                            "floor": XL_MIN_WINDOW_ROWS})
                    pay["kind"] = kind = "extreme"
                else:
                    pay["window_n_prints"] = int(row_w.get("_n") or 0)
                    pay["window_located_date"] = str(row_w.get("knowledge_date"))[:10]
                    a_in = (str(row_a.get("knowledge_date"))[:10] >= since_d.isoformat())
                    if a_in:
                        # ROW A's located date falls INSIDE the window: the anchor would restate the
                        # windowed row, so it is SUPPRESSED and ROW W's line names the tape's own span.
                        pay["declines"].append({"reason": "window_contains_alltime"})
                        cands = [{"slug": slug, "row": row_w, "direction": direction,
                                  "since": str(since), "tape_span": (pay["span_start"],
                                                                     pay["span_end"])}]
                    else:
                        cands.insert(0, {"slug": slug, "row": row_w, "direction": direction,
                                         "since": str(since), "tape_span": None})
    if kind == "extreme" and not row_b_allowed:
        # THE LATCH FIRING: a windowed ask that FELL to extreme. The trailing recency window is a scope
        # this ask never named, so it is not read and the suppression is COUNTED -- and the rendered note
        # above it, which says "the figure below is the whole-record one", stays singular and true.
        pay["declines"].append({"reason": "window_fallback_no_row_b"})
    elif kind == "extreme" and pay["reads"] < XL_CAP:
        # -- ROW B: the trailing window, and THE ALIAS'S ONE BRANCH ------------------------------------
        # THE `pay["reads"] < XL_CAP` CONJUNCT IS THE BUDGET FENCE, and it is deliberately redundant with
        # the latch: the ceiling is now stated in CODE at the one site that could ever breach it.
        # THE SUPPRESSION IS BEFORE THE READ, NOT AFTER IT. That is the entire cost saving, and it is
        # why the branch sits ABOVE the run() call rather than beside the render: a post-read suppression
        # would pass an output-only assertion while still spending the read. It is SCOPED TO THE EXTREME
        # KIND by construction -- `_validate` forces `xl_scope` to None on `windowed_extreme`, so a
        # floor-named ask can never route here and be served the whole-tape row.
        if scope == "all_time":
            pay["declines"].append({"reason": "scope_all_time_no_row_b"})
        else:
            lo = _iso_shift(str(asof)[:10], -int(XL_RECENT_DAYS))
            import datetime as _dt
            try:
                verdict = _fc.covers(slug, _dt.date.fromisoformat(lo),
                                     _dt.date.fromisoformat(str(asof)[:10]))
            except Exception:  # noqa: BLE001 -- an unmapped floor is a decline, never a raise
                verdict = "straddle"
            if verdict != "serve":
                # STRUCTURALLY INERT ON TODAY'S ROSTER and it says so here rather than pretending to be
                # exercised: the latest roster floor is 2018-12-24, so at XL_RECENT_DAYS=730 every board
                # returns "serve"; the branch becomes reachable only above ~2,808 days. It is KEPT
                # because G0b may move the window and a roster addition with a young tape would make it
                # live.
                pay["declines"].append({"reason": "recent_window_straddle", "window_start": lo})
            else:
                row_b = _xl_read(qfn, slug=slug, asof=asof, agg=agg, period_start=lo,
                                 futures_newest_first=futures_newest_first)
                pay["reads"] += 1
                if isinstance(row_b, _XlReadFailure):
                    pay["declines"].append({"reason": row_b.reason, "at": "row_b"})
                elif not row_b or row_b.get("value") is None or not row_b.get("knowledge_date"):
                    # ITS OWN NAME, never `no_rows_in_window`: THIS window is the engine's trailing
                    # recency one, and the ask's named window is a different fact under a different name.
                    pay["declines"].append({"reason": "no_rows_in_recent_window", "window_start": lo})
                elif (str(row_b.get("knowledge_date"))[:10]
                      == str(row_a.get("knowledge_date"))[:10]):
                    pay["declines"].append({"reason": "recent_equals_alltime"})
                else:
                    pay["recent"] = {"located_date": str(row_b.get("knowledge_date"))[:10],
                                     "value": row_b.get("value"),
                                     "n_prints": int(row_b.get("_n") or 0),
                                     "span_start": str(row_b.get("_span_start"))[:10],
                                     "span_end": str(row_b.get("_span_end"))[:10]}
                    cands.append({"slug": slug, "row": row_b, "direction": direction,
                                  "since": None, "tape_span": None})
    return cands, pay


def _xl_notes(pay: dict) -> list:
    """THE RENDERED PRICE EXTREME NOTE -- zero or one, never more (refute major 4).

    IT RENDERS ON EVERY WINDOWED FALLBACK AND ON NOTHING ELSE, and the test is the PAYLOAD'S OWN pair of
    kinds: the ask asked for `windowed_extreme` and the engine served `extreme`. That is exactly the state
    in which the floor the ask named was dropped and the whole-record row substituted for it -- the state
    that used to ship silently on four of its five reasons, leaving the mandate's "echo the starting point
    the question gave" clause vacuous and a compliant writer answering "the highest since 2020" with a
    2012 tape-wide high.

    THE REASON CLAUSE IS THE DECLINE'S OWN TEMPLATE, words-only, and the ONLY magnitude any note carries
    is the straddle's coverage floor -- a date the shipped map produced, on the same footing as the row's
    own measured span. No count, no window length, no echo of the ask's own text: the `since` the planner
    emitted is MODEL-AUTHORED and never re-enters a model-facing surface through this leg."""
    if str(pay.get("kind_requested") or "") != "windowed_extreme" or pay.get("kind") != "extreme":
        return []
    label = pay.get("label") or ""
    named = [d for d in (pay.get("declines") or []) if d.get("reason") in XL_RENDERED_DECLINES]
    # A REASON WITH NO READER SENTENCE FALLS BACK TO THE SCOPE SENTENCE ALONE rather than raising: a
    # KeyError here would be caught by the leg's belt and cost the reader the WHOLE block, rows included,
    # over a vocabulary edit. The lint's clause (12) is what catches that edit; this is the fail-soft.
    body = XL_DECLINE_TEMPLATES.get(named[0]["reason"]) if named else None
    if not body:
        return [f"PRICE EXTREME NOTE {label}: {XL_SCOPE_NOTE_TAIL}"]
    d = named[0]
    floor = (f" ({d.get('floor')})"
             if d["reason"] == "window_straddles_coverage" and d.get("floor") else "")
    return [f"PRICE EXTREME NOTE {label}: {body}{floor}. {XL_SCOPE_NOTE_TAIL}"]


def _extreme_locator_legs(sg, graph, request: dict, qfn, asof, calls: list, base: int, *,
                          futures_newest_first: bool | str = False) -> tuple:
    """THE LEG. Returns `(lines, payload)`; the belt above it never lets it raise past the wrapper.

    FENCE-BEFORE-MINT, in order: locate -> build every candidate line PURE against a PROVISIONAL handle
    number -> run the WHOLE-BLOCK register half -> then, per row, fullmatch `_XL_ROW_RX` and append the
    survivors IN ORDER, numbering AT APPEND TIME. A block whose every row drops ships NOTHING, marker
    included (the walk's row-less-no-marker law), and the RENUMBERED shipped string is re-checked, not
    merely the candidate."""
    cands, pay = _xl_locate(qfn, request, asof, futures_newest_first=futures_newest_first)
    if not cands:
        return [], pay
    notes = _xl_notes(pay)
    # HALF ONE, WHOLE-BLOCK ATOMIC, on the PROVISIONAL render (numbering cannot change a register verdict
    # -- the scans read words, not handles -- so a provisional pass is a real pass).
    probe = notes + [_xl_row_line(base + 1 + i, c["slug"], c["row"], direction=c["direction"],
                                  since=c["since"], tape_span=c["tape_span"])
                     for i, c in enumerate(cands)]
    if not _xl_register_fence(probe):
        pay["outcome"] = "fenced"
        pay["rows_fenced"] = len(cands)
        return [], pay
    lines = list(notes)
    for c in cands:
        n = len(calls) + 1
        ln = _xl_row_line(n, c["slug"], c["row"], direction=c["direction"], since=c["since"],
                          tape_span=c["tape_span"])
        if not _XL_ROW_RX.fullmatch(ln):
            pay["rows_fenced"] += 1
            continue                                  # HALF TWO: THAT row alone drops; no handle moves
        calls.append(_shown(_xl_call(c["slug"], c["row"], asof), c["row"].get("value")))
        lines.append(ln)
    if not any(ln.startswith("- [N") for ln in lines):
        pay["outcome"] = "declined"
        return [], pay                                # row-less -> NOTHING ships, the note included
    pay["outcome"] = "fired"
    pay["rendered"] = sum(1 for ln in lines if ln.startswith("- [N"))
    return lines, pay


def _extreme_locator_leg_or_nothing(sg, graph, request: dict, qfn, asof, calls: list, *,
                                    futures_newest_first: bool | str = False) -> tuple:
    """R6 belt at the ONE place both quantify return paths reach it (the `_episode_leg_or_nothing`
    precedent). Writes the leg's ONE registered trace key whenever the leg RAN -- `outcome` carries
    fired/declined/fenced, so an ABSENT key means "did not run", never "declined". A DISPATCH decline is
    recorded on `decided['extreme_locator']` instead, and this module never writes it."""
    _b = len(calls)
    try:
        lines, payload = _extreme_locator_legs(sg, graph, request, qfn, asof, calls, _b,
                                               futures_newest_first=futures_newest_first)
    except Exception:  # noqa: BLE001 -- fail-closed: the locator must never break the v1 answer
        calls[_b:] = []                # the belt rolls the LEDGER back too -- an orphan call record
        #                                would widen the verifier's acceptance pool (the W4 class)
        lines = []
        # THE ERROR PATH IS DELIBERATELY UNSTAMPED ON `reads`, and that is the `_cw_turn_spent` doctrine
        # rather than an omission: this branch cannot know how many reads the raising call had already
        # spent, and stamping 0 would let an UNKNOWN decline CREDIT the turn's ceiling. Absent is the
        # honest value; a consumer that reads it as 0 is reading a fact that was never measured.
        _k = str((request or {}).get("kind") or "extreme")
        payload = {"outcome": "declined", "kind": _k, "kind_requested": _k,
                   "board": (request or {}).get("board"), "rows_fenced": 0,
                   "declines": [{"reason": "error"}]}
    if payload is not None:
        try:
            sg.trace["quantify_extreme_locator"] = payload
        except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
            pass
    return lines, payload
