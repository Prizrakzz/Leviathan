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

from leviathan.graphrag import params as _pr
from leviathan.graphrag.numbers import query as Q

CASCADE_CAP = int(_pr.get("serving.cascade.cap", 12))            # own budget, separate from serving.silver.cap


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


def _node_specs(n, row, commodity, country, eras, asof) -> list[dict]:
    """The node's spec list: per era window, >=2 MY specs (marketing_year) or one windowed spec (date/ym);
    plus ONE CURRENT rhyme spec (R1: the CURRENT period at the SESSION asof, never the era window re-run)."""
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
             comove: bool = False) -> tuple:
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
        if not eras:
            continue
        commodity, country = _scope(n, row)
        if country is SKIP_NODE:
            continue                                              # unresolved region leg -> stays qualitative
        row = _region_row(n, row)                                 # fred_fx: region currency picks the metric
        specs = _node_specs(n, row, commodity, country, eras, asof)
        if specs:
            groups.append({"node": n, "row": row, "specs": specs, "key": specs[0]["node_key"],
                           "commodity": commodity, "contract": getattr(n, "contract", None),
                           "country": country, "eras": eras})
    if not groups:
        return None, [], []
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
    r_lines, r_trace = _reroute(pairs, era_deltas)
    block_lines = block_lines + r_lines
    # RV-W2: the cross-COMMODITY relative-value fork, gated ONLY by the orchestrator-threaded xc_request (the
    # env flag is checked at the answer.py seam). xc_request None -> this branch is inert and everything below
    # is byte-identical to v1. On FIRE the engine WRITES the trace key itself (C11: quantify_reroute_v2
    # non-empty == fired) and appends its BY-COMMODITY block; a decline/failure leaves the key absent.
    if xc_request:
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
        if _slug_match(g.get("commodity"), source):
            return g.get("eras") or []
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
