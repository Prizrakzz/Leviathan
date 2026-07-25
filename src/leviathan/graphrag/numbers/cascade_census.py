"""Cascade-leg census (Phase 9 W1) -- the offline realizability verifier the resolution chain never had.

The quantified-cascade engine resolves each driver leg through a deterministic chain (mapped `silver_ref`
-> causal node -> `region -> country` -> PSD/FX/ONI title -> windowed fetch), but every break in it goes
SILENTLY DARK, one eval failure at a time (France->EU when silver_psd aggregates EU members under
'European Union'; a leg whose resolved country the table never carries). This module replays that chain
OFFLINE, node-by-node, reusing the EXACT production helpers (`map_row`, `_scope`, `_region_row` from
cascade.py -- imported, never copied, so lint and runtime cannot diverge) and adds the one semantic step
the existing lints do not cover: does the resolved `(table, metric, country)` actually carry >=1 row in
the pg mirror?

    python -m leviathan.graphrag.numbers.cascade_census [--json OUT]   # exits non-zero on any un-waived dark leg

PG-ONLY BY CONSTRUCTION (W0.1). Every probe rides `pgnumbers.pg_query(sql)` -- the RAISE-on-failure
primitive -- NEVER `pgnumbers.query_fn` / `default_query_fn` / `Q.run` (all carry an opaque per-request
Athena fallback: on a pg hiccup they silently re-run the SAME SQL on Athena, and a hand-written whole-table
DISTINCT would become a full-table scan). A mirror gap surfaces as a `probe-error` verdict, never a silent
Athena round-trip. The live run additionally installs an Athena FIREWALL (Q.athena_query_fn made
raise-on-invoke) and asserts Q.STATS stays empty end-to-end -- an observable source-level guarantee, not a
trust-the-closure post-hoc banner.

VERDICTS (one per MAPPED leg -- unmapped drivers are DESIGNED-qualitative and out of census scope):
  FIRES              -- mapped ref, resolvable country, pg_probe returns rows. Can inject a citable [N].
  DECLINES-HONESTLY  -- SKIP_NODE on a compound/prose/unresolved region (the engine stays qualitative and
                        the answer narrates the mechanism without a fake number); or an explicit waiver.
  DARK-WITH-REASON   -- mapped, country RESOLVED, but pg_probe returns ZERO rows: the leg believes it will
                        fire and doesn't. Sub-reasons: country-not-a-psd-title (France->EU), commodity-slug-miss
                        (the PSD_SLUG_ALIAS class), metric-empty-for-country, uncertified-table.
  probe-error        -- the pg_query raised (mirror gap/outage/bad spec). Never retried on Athena.

The per-QUERY realizability functions (`query_realizable`, `driver_fireable`, `contract_can_any_leg_fire`)
are pure map/DAG topology -- NO pg -- and are the source of truth reused by config_check.check_pin_realizability.
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import json
import os
import sys

from leviathan.graphrag.numbers import cascade as casc
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers.registry import load_registry

# Census as-of: the current-leg probe date the v4 cascade fixture pins its current legs at. A whole-history
# existence probe (`agg=latest`, no period) at this asof sees every published vintage.
CENSUS_ASOF_DEFAULT = "2026-02-15"

FIRES = "FIRES"
DECLINES = "DECLINES-HONESTLY"
DARK = "DARK-WITH-REASON"
PROBE_ERROR = "probe-error"

# CANONICAL single source (DRY): config_check.check_cascade_map imports this set so census
# and lint cannot drift. silver_esr REMOVED 2026-07-12 (the D-W5 ESR flip): re-certified against the
# compact serving table (753,062 rows, all 8 checks pass; the sole WARN is the disclosed single-as_of
# snapshot limitation -- per-week vintage is the option-b follow-up). silver_nasa_power REMOVED
# 2026-07-14 (BF-W1): deprojected to registered [commodity, year] partitions (1,426), values census
# GREEN, INV-3 Athena probe 520ms planning / 0B scanned; the weather lane still SERVES from
# gold_weather_z (D-W4) -- removal here just stops branding the table uncertified in census output.
UNCERTIFIED_TABLES = frozenset()
_UNCERTIFIED = UNCERTIFIED_TABLES

# Explicit dark-leg waivers: (contract, node_id) -> one-line justification. A waived leg is reported as
# DECLINES-HONESTLY (the source genuinely has no data for that (country, metric); the engine stays
# qualitative rather than believing it will fire) and does NOT trip the non-zero exit.
# The 2026-07-11 census found exactly 9 dark legs, all on cocoa + frozen_orange_juice; the live probe
# (SELECT DISTINCT leviathan_slug FROM silver_psd WHERE ... cocoa|orange|juice|citrus) returned ZERO
# rows -- USDA PSD tracks neither commodity, so every leg below is honest data absence, not a bug.
# DELETE the relevant waivers if either commodity is ever ingested into silver_psd.
_NO_COCOA = "silver_psd has no cocoa balance sheet (DISTINCT slug probe 2026-07-11)"
_NO_FCOJ = "silver_psd has no orange-juice balance sheet (DISTINCT slug probe 2026-07-11)"
# D-W5 weather flip (2026-07-12): white_sugar's `frost` driver is a Brazil-cane-belt hazard (region
# `Brazil CS` -> Brazil, mechanism "frost in southern Brazil cane areas"), but white_sugar's
# gold_weather_z covers only the refined-sugar regions (China/EU/India/Thailand/US) -- Brazil cane
# weather belongs to RAW_SUGAR (whose frost leg FIRES). Honest per-contract coverage gap, not a bug.
_NO_WHITE_SUGAR_BRAZIL_WX = ("white_sugar gold_weather_z has no Brazil coverage (raw_sugar owns the "
                             "Brazil cane belt); the Brazil-frost hazard fires on raw_sugar, not the "
                             "refined-sugar contract -- gold coverage probe 2026-07-12")
_WAIVERS: dict[tuple[str, str], str] = {
    ("cocoa", "US_section301_tariffs"): _NO_COCOA,
    ("cocoa", "export_pace_lag"): _NO_COCOA,
    ("cocoa", "tenderable_collapse"): _NO_COCOA,
    ("cocoa", "grind_demand"): _NO_COCOA,
    ("cocoa", "demand_destruction"): _NO_COCOA,
    ("frozen_orange_juice", "ending_stocks"): _NO_FCOJ,
    ("frozen_orange_juice", "consumption_demand"): _NO_FCOJ,
    ("frozen_orange_juice", "US_section301_tariffs"): _NO_FCOJ,
    ("frozen_orange_juice", "tenderable_collapse"): _NO_FCOJ,
    ("white_sugar", "frost"): _NO_WHITE_SUGAR_BRAZIL_WX,
}

# The v4 cascade fixture (config_check._CFG mirror -- both resolve configs/graphrag/).
_FIXTURE = "eval_queries_v4_cascade.yaml"


# -- node adapter: the "iterate the causal YAML nodes directly, thread them through map_row/_scope" mode ----
class _LegNode:
    """A minimal stand-in for the runtime GroundedNode carrying exactly what the replayed helpers read:
    `.contract` (_scope), `.id` (node key), `.prior['silver_ref']` (_silver_ref), `.prior['region']`
    (_region_entry). No evidence -> _derive_windows is a no-op in this offline mode; the census's
    realizability signal is scope-resolution + the pg identity probe, not window derivation (there are no
    dated props to cluster when enumerating the causal YAMLs directly)."""

    __slots__ = ("contract", "id", "prior", "evidence")

    def __init__(self, contract: str, driver_id: str, silver_ref: str | None, region: str | None) -> None:
        self.contract = contract
        self.id = driver_id
        self.prior = {"silver_ref": silver_ref, "region": region}
        self.evidence = []


@functools.lru_cache(maxsize=1)
def _contract_index() -> dict:
    """{contract_name: CausalContract} across configs/graphrag/causal/*.yaml. Filename may differ from the
    contract id, so index by the loaded `.contract` (same glob idiom as blurb/_check_region_map)."""
    from leviathan.causal import blurb as bl
    from leviathan.causal import schema as cs
    idx: dict = {}
    for p in sorted(bl._CAUSAL_DIR.glob("*.yaml")):
        try:
            c = cs.load(p)
        except Exception:  # noqa: BLE001 -- a malformed YAML is a separate lint's problem, not the census's
            continue
        idx[c.contract] = c
    return idx


def _driver(contract: str, driver_id: str):
    c = _contract_index().get(contract)
    if c is None:
        return None
    for d in c.drivers:
        if d.id == driver_id:
            return d
    return None


# -- per-QUERY realizability (pure topology; NO pg) -- the q6 catcher, reused by check_pin_realizability ----
def driver_fireable(contract: str, driver_id: str) -> bool:
    """Can THIS driver's leg structurally fire? Mapped ref (map_row not None) AND a resolvable scope
    (_scope does not return SKIP_NODE -- an unresolved/compound region leg stays qualitative). Pure
    map/DAG topology; the pg row-existence half lives in the census, not here."""
    d = _driver(contract, driver_id)
    if d is None:
        return False
    row = casc.map_row(d.silver_ref)
    if row is None:
        return False
    _, country = casc._scope(_LegNode(contract, d.id, d.silver_ref, d.region), row)
    return country is not casc.SKIP_NODE


def contract_can_any_leg_fire(contract: str) -> bool:
    """The per-CONTRACT rollup: does ANY mapped driver on the contract resolve? This is an auditable
    topology fact -- NOT the q6 catcher (soybean_oil_cbot rolls up TRUE via its export/stock/oni/fx legs
    even though the biodiesel QUESTION grounds only unmapped refs)."""
    c = _contract_index().get(contract)
    if c is None:
        return False
    return any(driver_fireable(contract, d.id) for d in c.drivers)


def query_realizable(query: dict) -> bool | None:
    """Per-QUERY realizability. If the query DECLARES its grounded/expected driver set (`cascade_drivers`),
    intersect it with the fireable-mapped set -- "can the QUERY's OWN selected legs fire?" (q6 grounds only
    unmapped biodiesel-chain drivers + a driverless consumption leg -> FALSE, even though its contract's
    rollup is TRUE). With no declaration the per-query answer is UNKNOWN -> **None**, and callers must fail
    CLOSED: the contract rollup is NEVER a silent substitute -- it is exactly the
    granularity that would have greenlit q6's original undeclared `cascade_fired:true` pin."""
    contract = query.get("contract") or ""
    grounded = query.get("cascade_drivers")
    if not grounded:
        return None
    return any(driver_fireable(contract, did) for did in grounded)


# -- pg-only probe primitives (W0.1 / W0.2) ----------------------------------------------------------------
def pg_probe(table: str, metric: str, commodity: str | None, country: str | None, *, asof: str, query_fn):
    """Does the resolved (table, metric, commodity, country) carry >=1 row in the pg mirror at asof? Builds
    the SQL via build_sql (BYTE-IDENTICAL to the runtime path) and executes it via `query_fn` -- which MUST
    be pgnumbers.pg_query (raise-on-failure), never query_fn/default_query_fn (Athena-fallback closures).
    A whole-history existence probe: agg=latest, no period window. Raises on any pg/build failure; the
    caller records that as a probe-error verdict (never a silent Athena retry)."""
    spec = Q.NumberQuery(table=table, metric=metric, asof=asof, commodity=commodity, country=country,
                         agg="latest")
    return query_fn(Q.build_sql(spec))


def _distinct_set(table: str, col: str, query_fn) -> set[str]:
    """One SELECT DISTINCT <col> against the pg mirror via `query_fn` (pg_query) -- NEVER routed through a
    fallback closure, or a pg hiccup would run it as a full-table Athena scan (the ZERO-Athena violation
    W0.2 calls out). One cheap query per (table, col), cached per run."""
    rows = query_fn(f"SELECT DISTINCT {col} AS v FROM {Q.ATHENA_DB}.{table}")
    return {str(r.get("v")) for r in rows if r.get("v") not in (None, "")}


def _dark_reason(table: str, commodity: str | None, country: str | None, ts, caches: dict, query_fn) -> str:
    """Name the sub-reason for a resolved-but-zero-row leg. country-not-a-psd-title (France->EU) is checked
    FIRST -- it is the class the existing table.metric + region-token lints structurally cannot catch.
    The DISTINCT probes hit the PHYSICAL served table (ts.athena_table when it differs from the id --
    silver_esr serves from silver_esr_compact): the raw logical id crashed the T2b backfill on pg with
    UndefinedTable (2026-07-25) because only build_sql resolved the mapping, not this f-string path."""
    phys = getattr(ts, "athena_table", None) or table
    ccol = getattr(ts, "country_col", None)
    if country and ccol:
        titles = caches.setdefault(("title", phys), _distinct_set(phys, ccol, query_fn))
        if country not in titles:
            return "country-not-a-psd-title"
    if table in _UNCERTIFIED:
        return "uncertified-table"
    scol = getattr(ts, "commodity_col", None)
    if commodity and scol:
        slugs = caches.setdefault(("slug", phys), _distinct_set(phys, scol, query_fn))
        if commodity not in slugs:
            return "commodity-slug-miss"
    return "metric-empty-for-country"


# -- the census -------------------------------------------------------------------------------------------
def _leg_record(contract, node_id, silver_ref, table, metric, region, country) -> dict:
    return {"contract": contract, "node_id": node_id, "silver_ref": silver_ref, "table": table,
            "metric": metric, "region": region,
            "country": None if country is None else str(country),
            "verdict": None, "reason": None, "window_count": 0, "pg_rows": None}


def census(*, asof: str = CENSUS_ASOF_DEFAULT, query_fn, cmap=None) -> dict:
    """Enumerate every MAPPED leg across the causal YAMLs, replay map_row/_scope/_region_row, probe the pg
    mirror for row existence, and classify each leg. Returns the artifact dict (W1 'Output artifact'):
    per-leg records + per-contract can_any_leg_fire rollup + per-query realizability + the run banner.
    `query_fn` is injected (pgnumbers.pg_query live; a mock in tests) so this function needs no env and
    never touches Athena."""
    reg = load_registry()
    caches: dict = {}                                            # (kind, table) -> DISTINCT set, one query each
    legs: list[dict] = []
    for contract, c in sorted(_contract_index().items()):
        for d in c.drivers:
            row = casc.map_row(d.silver_ref)
            if row is None:
                continue                                        # unmapped/deferred -> out of census scope
            n = _LegNode(contract, d.id, d.silver_ref, d.region)
            commodity, country = casc._scope(n, row)
            rec = _leg_record(contract, d.id, d.silver_ref, row.get("table"), row.get("metric"),
                              d.region, country)
            waiver = _WAIVERS.get((contract, d.id))
            if waiver:
                rec["verdict"], rec["reason"] = DECLINES, f"waived: {waiver}"
                legs.append(rec)
                continue
            if country is casc.SKIP_NODE:
                rec["country"] = None
                rec["verdict"], rec["reason"] = DECLINES, "region-unresolved"
                legs.append(rec)
                continue
            row2 = casc._region_row(n, row)                     # fred_fx: region currency picks the metric
            table, metric = row2.get("table"), row2.get("metric")
            rec["table"], rec["metric"] = table, metric
            try:
                rows = pg_probe(table, metric, commodity, country, asof=asof, query_fn=query_fn)
            except Exception as e:  # noqa: BLE001 -- record it; NEVER retry on Athena
                rec["verdict"], rec["reason"] = PROBE_ERROR, str(e)[:200]
                legs.append(rec)
                continue
            rec["pg_rows"] = len(rows)
            if rows:
                rec["verdict"] = FIRES
            else:
                ts = None
                try:
                    ts = reg.get(table)
                except Exception:  # noqa: BLE001
                    pass
                rec["verdict"] = DARK
                if ts is not None:
                    rec["reason"] = _dark_reason(table, commodity, country, ts, caches, query_fn)
                else:
                    # distinguish "not in the numbers registry" from "registered but certified-empty"
                    # (a bare-except relabel previously conflated the two and hid the real cause)
                    rec["reason"] = "uncertified-table" if table in _UNCERTIFIED else "table-not-registered"
            legs.append(rec)

    per_contract: dict = {}
    for leg in legs:
        cur = per_contract.get(leg["contract"], False)
        per_contract[leg["contract"]] = cur or (leg["verdict"] == FIRES)

    per_query = _per_query_realizability()
    pairs = pair_census(asof=asof, query_fn=query_fn, cmap=cmap)      # RV-W4.2 (no-op when the map is absent)

    banner = {
        "athena_calls": len(Q.STATS),
        "pg_probes": sum(1 for leg in legs if leg["pg_rows"] is not None),
        "fires": sum(1 for leg in legs if leg["verdict"] == FIRES),
        "declines": sum(1 for leg in legs if leg["verdict"] == DECLINES),
        "dark": sum(1 for leg in legs if leg["verdict"] == DARK),
        "probe_errors": sum(1 for leg in legs if leg["verdict"] == PROBE_ERROR),
        "pairs_fire": sum(1 for p in pairs if p["verdict"] == PAIR_FIRES),
        "pairs_dark": sum(1 for p in pairs if p["verdict"] == PAIR_DARK),
        "pairs_warn": sum(1 for p in pairs if p["warn"]),
    }
    # key renamed from per_contract_can_any_leg_fire: this rollup is pg-FIRES-based, a
    # DIFFERENT fact from the topology-only contract_can_any_leg_fire() function above.
    return {"as_of_date": asof, "legs": legs, "pairs": pairs, "per_contract_has_firing_leg": per_contract,
            "per_query_realizability": per_query, "banner": banner}


def _per_query_realizability() -> list[dict]:
    """Per-query realizability over the v4 fixture's cascade-pinned queries (pure topology). The artifact's
    source-of-truth for check_pin_realizability."""
    from leviathan.graphrag import extract as ex
    import yaml
    p = ex._CFG / _FIXTURE
    if not p.exists():
        return []
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: list[dict] = []
    for q in (doc.get("queries") or []):
        exp = q.get("expect") or {}
        if "cascade_fired" not in exp:
            continue
        out.append({"id": q.get("id"), "contract": q.get("contract"),
                    "pin": bool(exp["cascade_fired"]), "realizable": query_realizable(q)})
    return out


# -- RV-v2 cross-commodity PAIR realizability (Recipe-B World synthesis probe, RV-W4.2) --------------------
# The World stocks-to-use ratio has NO literal country="World" row in silver_psd (S3 parquet probe
# 2026-07-18: 35,220 rows across all 7 candidate slugs, ZERO world-like country values -- the PSD bulk feed
# ships no aggregate row). So `country_rule: world` is SYNTHESIZED Recipe-B:
#   SUM(ending_stocks_mt) / SUM(consumption_mt)  across all countries  per (slug, market_year)
#   over EACH COUNTRY'S OWN LATEST release_date <= asof (the per-country-latest union).
# PSD vintages are DELTAS (probed live 2026-07-20): a monthly release_date carries ONLY the countries whose
# numbers changed, so "one shared vintage" does not exist -- the retired single-vintage rule summed a
# revision SUBSET mislabeled as World (palm MY2024 read 0.00% off one placeholder row). Per-country-latest
# is what group_cols() ROW_NUMBER dedup in Q.build_sql produces AND what the engine's _world_su_ratio sums:
# each row individually PIT-safe, a country's vintages never mixed with each other, the cross-country set
# intentionally spanning releases because that IS "as known at asof".
# A v2 pair FIRES only when BOTH legs' World synthesis is non-empty (a positive summed consumption
# denominator exists at the census as-of) AND -- the double-count guard -- each slug is era-DISJOINT
# AFTER the membership-window dedup (2026-07-20 fix): the engine SUM excludes a member's individual rows
# for marketing years the member sits inside its explicit `casc.EU_MEMBERSHIP` window while an EU-aggregate
# row is present (the aggregate already carries it), so a PSD backfill like the UK's individual MY2016-2019
# rows under the EU-28 aggregate is disjoint BY CONSTRUCTION and no longer darks the pair. The lint stays
# a genuine tripwire for overlaps the dedup cannot resolve -- a member title with NO curated membership
# window (fail-closed) -- and flags those pairs not-realizable + WARN.
PAIR_FIRES = FIRES
PAIR_DARK = DARK
PAIR_DECLINES = DECLINES

# EU aggregate/member titles + membership windows: SINGLE SOURCE in cascade.py (the 2026-07-20 UK-backfill
# fix moved them next to the engine's World SUM, where `eu_member_deduped` applies them at quantify time;
# census imports cascade, so this direction is the only non-circular one). The underscored aliases keep the
# census's public surface stable for tests and callers.
_EU_AGGREGATE_TITLES = casc.EU_AGGREGATE_TITLES
_EU_MEMBER_TITLES = casc.EU_MEMBER_TITLES
_EU_MEMBERSHIP = casc.EU_MEMBERSHIP
_EU_MEMBERSHIP_DEFAULT = casc.EU_MEMBERSHIP_DEFAULT
_in_eu_aggregate = casc._in_eu_aggregate


def _num_first(rows) -> float | None:
    """First row's `value` as a float, else None. The agg=sum World probe returns one summed row."""
    for r in (rows or []):
        v = r.get("value") if isinstance(r, dict) else None
        if v in (None, ""):
            continue
        try:
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            return None
    return None


def _world_synth_nonempty(slug: str, *, asof: str, query_fn) -> bool:
    """Recipe-B EXISTENCE probe for one leg: does the World synthesis have data to divide at asof? Rides
    Q.build_sql BYTE-IDENTICALLY (agg=sum, country=None => sums each country's OWN latest vintage <= asof,
    the per-country-latest union group_cols()'s ROW_NUMBER dedup produces -- the SAME set the engine's
    _world_su_ratio sums since the 2026-07-20 delta-vintage fix). Non-empty with a POSITIVE consumption
    denominator AND a present stocks numerator => the World su_ratio can be synthesized. This EXISTENCE
    verdict is invariant under the engine's membership-window dedup (`casc.eu_member_deduped`): the dedup
    only ever removes member rows when an EU AGGREGATE row with a NUMERIC value sits in the same
    per-country-latest set (a NULL-valued aggregate row never triggers it -- skeptic probe T3, 2026-07-20),
    and that numeric aggregate row itself always joins the SUM -- so wherever this naive probe fires the
    deduped SUM is non-empty too (a contradictory zero-valued aggregate print can still zero the engine's
    denominator, which declines honestly at quantify time; existence is what THIS probe answers). Raises on
    pg failure (the caller records probe-error), never retried on Athena."""
    cons = query_fn(Q.build_sql(Q.NumberQuery(table="silver_psd", metric="consumption_mt", asof=asof,
                                              commodity=slug, country=None, agg="sum")))
    denom = _num_first(cons)
    if not (denom and denom > 0):                                    # no positive world use -> nothing to divide
        return False
    stk = query_fn(Q.build_sql(Q.NumberQuery(table="silver_psd", metric="ending_stocks_mt", asof=asof,
                                             commodity=slug, country=None, agg="sum")))
    return _num_first(stk) is not None


def _psd_year_sets(slug: str, query_fn) -> dict[str, set[int]]:
    """{country: {market_year, ...}} -- the EXACT set of reported consumption years per country, NEVER a
    min/max range. A range collapses a country's GAPS (e.g. UK reported pre-1973 AND again post-Brexit 2020+,
    with an empty 1973-2019 middle) and spuriously spans the aggregate era; the exact set is what the
    membership-aware disjointness lint needs. ONE grouped SELECT via the injected pg_query (NEVER a fallback
    closure: a whole-slug scan on Athena would be a billed scan, the ZERO-Athena W0.2 rule)."""
    sql = (f"SELECT DISTINCT country AS c, market_year AS y "
           f"FROM {Q.ATHENA_DB}.silver_psd WHERE leviathan_slug = {Q._q(slug)} "
           f"AND consumption_mt IS NOT NULL")
    out: dict[str, set[int]] = {}
    for r in (query_fn(sql) or []):
        c = r.get("c")
        try:
            y = int(r.get("y"))
        except (TypeError, ValueError):
            continue
        if c not in (None, ""):
            out.setdefault(str(c), set()).add(y)
    return out


def _era_disjoint(slug: str, *, query_fn) -> tuple[bool, str | None]:
    """The double-count tripwire, verified AFTER the membership-window DEDUP (the 2026-07-20 UK-backfill fix).
    A naive cross-country SUM double-counts a member ONLY in market_years where the member is BOTH reported
    individually AND rolled into the 'European Union'/'EU-*' aggregate. But the World SUM is no longer naive:
    `casc.eu_member_deduped` EXCLUDES a member's individual rows for exactly the years it sits inside its
    EXPLICIT `casc.EU_MEMBERSHIP` window when an aggregate row is present -- so such an overlap (the live case:
    USDA PSD backfilling individual UK rows for MY2016-2019 under the still-EU-28 aggregate) is disjoint BY
    CONSTRUCTION and must NOT dark the pair. What remains a genuine hazard is an overlap the dedup CANNOT
    resolve: a member title with NO explicit membership window (e.g. the pre-EU-15 founders -- France) reported
    individually in aggregate-covered years. The dedup refuses to guess their window (silently dropping them
    could as easily UNDER-count), so that overlap stays (False, warn) -- fail-closed until a window is curated.
    Overlaps OUTSIDE a member's window (post-Brexit UK 2020+, pre-accession states) were never double-counted.
    Uses EXACT reported year sets, never min/max ranges (a range collapses gaps and spuriously spans eras)."""
    sets = _psd_year_sets(slug, query_fn)
    agg_years: set[int] = set()
    for c, ys in sets.items():
        if c in _EU_AGGREGATE_TITLES:
            agg_years |= ys
    if not agg_years:                                              # no aggregate rows -> nothing to double-count
        return True, None
    worst: tuple[int, str] | None = None
    for c, ys in sets.items():
        if c not in _EU_MEMBER_TITLES:
            continue
        clash = sorted(y for y in (ys & agg_years) if _in_eu_aggregate(c, y))
        if not clash:
            continue
        if c in _EU_MEMBERSHIP:
            # Resolved BY CONSTRUCTION: eu_member_deduped excludes this member's rows from every World SUM
            # for precisely these years (explicit window + aggregate present) -- no double count survives.
            continue
        span = clash[-1] - clash[0]
        msg = (f"member '{c}' reported individually in MY[{clash[0]}-{clash[-1]}] while inside the EU "
               f"aggregate with NO explicit membership window -- the SUM dedup cannot resolve it "
               f"(naive world SUM would double-count {slug})")
        if worst is None or span > worst[0]:
            worst = (span, msg)
    if worst:
        return False, worst[1]
    return True, None


def _pair_leg_slug(side) -> str | None:
    """The silver_psd leviathan_slug for a pair leg's side dict, resolved through the SAME PSD_SLUG_ALIAS the
    runtime _scope applies (so the probe reads exactly the runtime slug). None when the side carries no
    contract."""
    contract = (side or {}).get("contract") if isinstance(side, dict) else getattr(side, "contract", None)
    if not contract:
        return None
    return casc.PSD_SLUG_ALIAS.get(contract, contract)


def _pair_verdict(pair, *, asof: str, query_fn) -> dict:
    """Per-PAIR realizability record. FIRES iff BOTH legs' World synthesis is non-empty AND both legs are
    era-disjoint; DECLINES-HONESTLY when a leg has no PSD balance sheet at all (cocoa/FCOJ, PSD_UNSERVED_SLUGS);
    DARK-WITH-REASON when a resolved leg has zero World rows OR fails the disjointness lint; probe-error on a pg
    raise. `warn` carries the disjointness message (surfaced, never silent)."""
    pid = getattr(pair, "id", None)
    legs = [getattr(pair, "side_a", None), getattr(pair, "side_b", None)]
    slugs = [_pair_leg_slug(s) for s in legs]
    rec = {"pair_id": pid, "pair": list(getattr(pair, "pair", ()) or ()), "slugs": slugs,
           "verdict": None, "reason": None, "warn": None}
    if not all(slugs):
        rec["verdict"], rec["reason"] = PAIR_DARK, "unresolved-leg-slug"
        return rec
    unserved = [s for s in slugs if s in casc.PSD_UNSERVED_SLUGS]
    if unserved:
        rec["verdict"], rec["reason"] = PAIR_DECLINES, f"no PSD balance sheet for {unserved[0]}"
        return rec
    try:
        for s in slugs:
            ok, warn = _era_disjoint(s, query_fn=query_fn)
            if not ok:
                rec["verdict"], rec["reason"], rec["warn"] = PAIR_DARK, "era-overlap", warn
                return rec
        for s in slugs:
            if not _world_synth_nonempty(s, asof=asof, query_fn=query_fn):
                rec["verdict"], rec["reason"] = PAIR_DARK, f"world-synth-empty:{s}"
                return rec
    except Exception as e:  # noqa: BLE001 -- record it; NEVER retry on Athena
        rec["verdict"], rec["reason"] = PROBE_ERROR, str(e)[:200]
        return rec
    rec["verdict"] = PAIR_FIRES
    return rec


def _load_complex_map():
    """Lazy, fail-closed load of lane-A's complex_map (may be absent during a parallel build). None ->
    the pair census is a no-op and pair_realizable fails closed."""
    try:
        from leviathan.graphrag.complex_map import load_complex_map
        return load_complex_map()
    except Exception:  # noqa: BLE001 -- map missing/malformed -> no pair pass, never an error
        return None


def pair_census(*, asof: str = CENSUS_ASOF_DEFAULT, query_fn, cmap=None) -> list[dict]:
    """Per-PAIR verdicts over the curated complex_map (material pairs only -- load_complex_map drops the rest).
    Injected query_fn (pg_query live, mock in tests); returns [] when the map is unavailable."""
    cm = cmap if cmap is not None else _load_complex_map()
    if cm is None:
        return []
    return [_pair_verdict(p, asof=asof, query_fn=query_fn) for p in getattr(cm, "pairs", []) or []]


@functools.lru_cache(maxsize=64)
def pair_realizable(pair_id: str) -> bool | None:
    """RUNTIME gate-C + suggester predicate (interface contract): is this curated pair's per-PAIR census
    verdict FIRES? Resolves the default pg query_fn and finds the pair by id. Returns True (FIRES) / False
    (DARK/declines/overlap) / None (pair not found, pg unavailable, or any raise -> callers FAIL CLOSED).
    Memoized per process -- chips + the gate tolerate staleness; the build-time census calls _pair_verdict
    directly with its own injected query_fn, never this cache."""
    try:
        cm = _load_complex_map()
        if cm is None:
            return None
        pair = next((p for p in getattr(cm, "pairs", []) or [] if getattr(p, "id", None) == pair_id), None)
        if pair is None:
            return None
        from leviathan.graphrag.numbers import pgnumbers
        if not pgnumbers.enabled():
            return None
        rec = _pair_verdict(pair, asof=CENSUS_ASOF_DEFAULT, query_fn=pgnumbers.pg_query)
        return rec["verdict"] == PAIR_FIRES
    except Exception:  # noqa: BLE001 -- fail closed, never a 500 on a chip/gate path
        return None


def _unwaived_dark(artifact: dict) -> list[dict]:
    dark = [leg for leg in artifact["legs"] if leg["verdict"] == DARK]
    dark += [p for p in artifact.get("pairs", []) if p["verdict"] == PAIR_DARK]
    return dark


# -- Athena firewall (W0.1 source tripwire) ----------------------------------------------------------------
@contextlib.contextmanager
def _athena_firewall():
    """Hard source-level guarantee that the run is pg-only: Q.athena_query_fn is made raise-on-invoke for
    the whole run, and Q.STATS is asserted EMPTY at the end. If either fires the run aborts loudly -- this
    is the observable guard the plan mandates OVER a post-hoc ATHENA_CALLS==0 banner (which would only read
    0 AFTER an Athena call already executed)."""
    Q.reset_stats()
    orig = Q.athena_query_fn

    def _blocked(*a, **k):
        raise RuntimeError("ATHENA TRIPWIRE: athena_query_fn invoked during a pg-only census run")

    Q.athena_query_fn = _blocked
    try:
        yield
    finally:
        Q.athena_query_fn = orig
    if Q.STATS:
        raise RuntimeError(f"ATHENA TRIPWIRE: Q.STATS is non-empty ({len(Q.STATS)} Athena queries ran)")


# -- CLI --------------------------------------------------------------------------------------------------
def _artifact_path(asof: str):
    """data/cascade_census/as_of_date=<YYYY-MM-DD>/census.json -- timestamped-partition path mirroring the
    E1 census / E4 census --diff archives so a later run can diff against this baseline."""
    from pathlib import Path
    repo = Path(casc.__file__).resolve().parents[4]
    return repo / "data" / "cascade_census" / f"as_of_date={asof}" / "census.json"


def _run_live(asof: str, out_path=None) -> int:
    """The live pg-mirror run: env asserts + Athena firewall + artifact write + non-zero exit on dark."""
    from leviathan.graphrag.numbers import pgnumbers
    assert os.environ.get("GRAPHRAG_NUMBERS_BACKEND", "").strip().lower() == "pg", \
        "cascade_census requires GRAPHRAG_NUMBERS_BACKEND=pg (pg-mirror-only by construction)"
    assert os.environ.get("EVIDENCE_PG_DSN"), "cascade_census requires EVIDENCE_PG_DSN"
    assert pgnumbers.enabled(), "cascade_census requires pgnumbers.enabled() (backend=pg + DSN)"
    with _athena_firewall():
        artifact = census(asof=asof, query_fn=pgnumbers.pg_query)
    b = artifact["banner"]
    assert b["athena_calls"] == 0, f"ATHENA_CALLS banner is {b['athena_calls']}, expected 0"

    from pathlib import Path
    dest = Path(out_path) if out_path else _artifact_path(asof)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(artifact, indent=1), encoding="utf-8")

    print(f"cascade census as-of {asof} -> {dest}")
    print(f"  legs: {len(artifact['legs'])}  fires={b['fires']} declines={b['declines']} "
          f"dark={b['dark']} probe_errors={b['probe_errors']}  ATHENA_CALLS={b['athena_calls']}")
    print(f"  pairs: {len(artifact['pairs'])}  fire={b['pairs_fire']} dark={b['pairs_dark']} warn={b['pairs_warn']}")
    dark = _unwaived_dark(artifact)
    leg_dark = [d for d in dark if "node_id" in d]
    pair_dark = [d for d in dark if "pair_id" in d]
    if leg_dark:
        print(f"FAIL cascade_census: {len(leg_dark)} un-waived DARK-WITH-REASON leg(s):")
        for leg in leg_dark:
            print(f"  - {leg['contract']}/{leg['node_id']} {leg['table']}.{leg['metric']} "
                  f"country={leg['country']} -> {leg['reason']}")
    if pair_dark:
        print(f"FAIL cascade_census: {len(pair_dark)} DARK cross-commodity pair(s):")
        for p in pair_dark:
            print(f"  - pair {p['pair_id']} {p['slugs']} -> {p['reason']}"
                  + (f" [WARN: {p['warn']}]" if p["warn"] else ""))
    if b["probe_errors"]:
        print(f"WARN cascade_census: {b['probe_errors']} probe-error leg(s) (mirror gap -- NOT retried on Athena)")
    return 1 if dark else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cascade-leg census: offline realizability verifier (pg-only)")
    ap.add_argument("--asof", default=CENSUS_ASOF_DEFAULT, help="census as-of date (YYYY-MM-DD)")
    ap.add_argument("--json", dest="out", default=None, help="artifact output path (default: data/cascade_census/...)")
    a = ap.parse_args(argv)
    return _run_live(a.asof, a.out)


if __name__ == "__main__":
    sys.exit(main())
