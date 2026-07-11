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

# 0 rows at the 2026-06-24 source certification. CANONICAL single source (review fold, DRY):
# config_check.check_cascade_map imports this set so census and lint cannot drift.
UNCERTIFIED_TABLES = frozenset({"silver_esr", "silver_nasa_power"})
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
    CLOSED (review fold, major): the contract rollup is NEVER a silent substitute -- it is exactly the
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
    FIRST -- it is the class the existing table.metric + region-token lints structurally cannot catch."""
    ccol = getattr(ts, "country_col", None)
    if country and ccol:
        titles = caches.setdefault(("title", table), _distinct_set(table, ccol, query_fn))
        if country not in titles:
            return "country-not-a-psd-title"
    if table in _UNCERTIFIED:
        return "uncertified-table"
    scol = getattr(ts, "commodity_col", None)
    if commodity and scol:
        slugs = caches.setdefault(("slug", table), _distinct_set(table, scol, query_fn))
        if commodity not in slugs:
            return "commodity-slug-miss"
    return "metric-empty-for-country"


# -- the census -------------------------------------------------------------------------------------------
def _leg_record(contract, node_id, silver_ref, table, metric, region, country) -> dict:
    return {"contract": contract, "node_id": node_id, "silver_ref": silver_ref, "table": table,
            "metric": metric, "region": region,
            "country": None if country is None else str(country),
            "verdict": None, "reason": None, "window_count": 0, "pg_rows": None}


def census(*, asof: str = CENSUS_ASOF_DEFAULT, query_fn) -> dict:
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
                    # (review fold: a bare-except relabel conflated the two and hid the real cause)
                    rec["reason"] = "uncertified-table" if table in _UNCERTIFIED else "table-not-registered"
            legs.append(rec)

    per_contract: dict = {}
    for leg in legs:
        cur = per_contract.get(leg["contract"], False)
        per_contract[leg["contract"]] = cur or (leg["verdict"] == FIRES)

    per_query = _per_query_realizability()

    banner = {
        "athena_calls": len(Q.STATS),
        "pg_probes": sum(1 for leg in legs if leg["pg_rows"] is not None),
        "fires": sum(1 for leg in legs if leg["verdict"] == FIRES),
        "declines": sum(1 for leg in legs if leg["verdict"] == DECLINES),
        "dark": sum(1 for leg in legs if leg["verdict"] == DARK),
        "probe_errors": sum(1 for leg in legs if leg["verdict"] == PROBE_ERROR),
    }
    # key renamed from per_contract_can_any_leg_fire (review fold): this rollup is pg-FIRES-based, a
    # DIFFERENT fact from the topology-only contract_can_any_leg_fire() function above.
    return {"as_of_date": asof, "legs": legs, "per_contract_has_firing_leg": per_contract,
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


def _unwaived_dark(artifact: dict) -> list[dict]:
    return [leg for leg in artifact["legs"] if leg["verdict"] == DARK]


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
    dark = _unwaived_dark(artifact)
    if dark:
        print(f"FAIL cascade_census: {len(dark)} un-waived DARK-WITH-REASON leg(s):")
        for leg in dark:
            print(f"  - {leg['contract']}/{leg['node_id']} {leg['table']}.{leg['metric']} "
                  f"country={leg['country']} -> {leg['reason']}")
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
