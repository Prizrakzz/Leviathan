"""contract_check (SILVER-C002) -- the numbers-stack I1 vocabulary + value-populatedness gate.

The semantic registry (the numbers `TableSpec` + the cascade `region_map`) declares strings the serving
SQL/cascade layer FILTERS on -- metric names, commodity slugs, country titles, FX currencies. When one of
those strings is not in the physical DISTINCT vocabulary of the served table the query silently returns 0
rows and the answer loses a number with no error -- the WASDE Title-Case class (`'Ending Stocks'` declared,
physical column is `ending_stocks`), the `drought_z` declared-but-zero-row class, and the France->EU /
Cote d'Ivoire resolved-country class the cascade_census only catches at runtime. This module promotes all of
them to a PRE-SERVE gate.

SCOPE (Attack 3, finding #2 -- CONFIRMED-BROKEN if widened): the **numbers / pg-served tables only** -- the
tall/wide tables that are actually in the RDS mirror (WASDE, ESR->esr_compact, PSD, production, weather-z,
FX, ONI). The ~30 feature-only + flat + projection tables are NOT reachable by the pg mirror and are covered
by the FR-001 footer-derived distinct-vocabulary check instead. The projection-trio member present in the
numbers registry (`silver_nasa_power`) is EXCLUDED here (INV-3 forbids an Athena/pg DISTINCT on a projected
partition column -- the Jul-2026 LIST-storm mechanism); the FR-001 footer path owns it.

MECHANISM (mirrors cascade_census, DRY): every DISTINCT probe rides `cascade_census._distinct_set(table,
col, query_fn)` -- ONE `SELECT DISTINCT` against the **pg mirror** via `query_fn`, which MUST be
`pgnumbers.pg_query` (raise-on-failure), never a fallback closure (a pg hiccup would re-run the DISTINCT as a
full-table Athena scan). Wide-table metric names are checked FREE against the physical Glue/registry column
set (metric NAME == column name on a wide table -- no query). The live run installs the same Athena firewall
cascade_census uses and asserts Q.STATS stays empty end-to-end.

    python -m leviathan.graphrag.numbers.contract_check [--json OUT]   # exits non-zero on any drift

Runs IN-VPC in the SAME pg-mirror Batch job as cascade_census (needs GRAPHRAG_NUMBERS_BACKEND=pg +
EVIDENCE_PG_DSN). The pure check functions are import-only, AWS-free, and callable (the silver_rebuild_gate
Branch-A stage 3 calls `contract_check(query_fn=...)` directly).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from leviathan.graphrag.numbers import cascade as casc
from leviathan.graphrag.numbers import cascade_census as cc
from leviathan.graphrag.numbers.registry import load_registry

# The projection-trio member that lives in the numbers registry. NEVER DISTINCT-probed here (INV-3): the
# FR-001 footer-vocabulary check owns every projected table. Excluding it is what makes the "zero Athena
# against projection tables" acceptance structural rather than a runtime hope.
NUMBERS_PROJECTION_TABLES = frozenset({"silver_nasa_power"})


def _physical(ts) -> str:
    """The served Glue/pg table id (silver_esr serves from silver_esr_compact)."""
    return ts.athena_table or ts.id


def _numbers_table_ids(reg) -> list[str]:
    """The pg-served numbers tables C002 owns -- every registry table minus the projection trio."""
    return [tid for tid in sorted(reg.tables) if tid not in NUMBERS_PROJECTION_TABLES]


# ---------------------------------------------------------------------------
# Default Glue-column source for the wide-table metric check (AWS-free): read the F010 silver registry
# physical columns. metric NAME == column name on a wide table, so this is a free membership test.
# ---------------------------------------------------------------------------
def _f010_column_fn():
    """Build a `physical_table -> set[column]` resolver from the F010 silver registry. Falls back to an
    empty-set resolver if the silver registry is unavailable (then the wide-metric check errs conservatively,
    reporting every metric as unresolved rather than passing vacuously)."""
    try:
        from leviathan.silver import registry as sreg
        silver = sreg.load_registry()
    except Exception:  # noqa: BLE001 -- keep C002 usable even if F010 is mid-edit; fail-closed below
        return lambda _t: set()

    def _cols(physical: str) -> set[str]:
        return silver.columns(physical) if physical in silver.tables else set()

    return _cols


# ---------------------------------------------------------------------------
# Check family 1 -- metric vocabulary (WASDE Title-Case + drought_z zero-row classes).
# ---------------------------------------------------------------------------
def check_metric_vocabulary(reg, *, query_fn, column_fn=None, caches=None) -> list[str]:
    """Every registry-declared metric of every numbers table exists physically:
      * WIDE table (metric == column): the metric is a real physical column (free Glue/registry check).
      * TALL table (metric == row value): the metric is in DISTINCT(metric_col) on the pg mirror -- which is
        both an existence AND a >=1-row assertion (an absent metric == zero rows, the drought_z class)."""
    column_fn = column_fn or _f010_column_fn()
    caches = caches if caches is not None else {}
    errs: list[str] = []
    for tid in _numbers_table_ids(reg):
        ts = reg.get(tid)
        phys = _physical(ts)
        if ts.shape == "wide":
            cols = column_fn(phys)
            for m in ts.metrics:
                if m not in cols:
                    errs.append(f"{tid}: metric column {m!r} is not a physical column of {phys} "
                                f"(declared wide metric absent -- the WASDE Title-Case drift class)")
        else:  # tall
            if not ts.metric_col:
                errs.append(f"{tid}: tall table declares metrics but no metric_col")
                continue
            present = caches.setdefault(("distinct", phys, ts.metric_col),
                                        cc._distinct_set(phys, ts.metric_col, query_fn))
            for m in ts.metrics:
                if m not in present:
                    errs.append(f"{tid}: metric {m!r} not in DISTINCT {ts.metric_col} of {phys} "
                                f"(declared-but-zero-row -- the drought_z class)")
    return errs


# ---------------------------------------------------------------------------
# Leg enumeration reused by the country + slug checks (topology only; DRY with cascade_census).
# ---------------------------------------------------------------------------
def _mapped_legs():
    """Yield (contract, driver_id, row, node, commodity, country) for every MAPPED causal leg, resolving
    scope with the EXACT production helpers cascade_census replays (`map_row`/`_scope`/`_region_row`). country
    is `casc.SKIP_NODE` for an unresolved/compound region (the leg stays qualitative)."""
    for contract, c in sorted(cc._contract_index().items()):
        for d in c.drivers:
            row = casc.map_row(d.silver_ref)
            if row is None:
                continue
            node = cc._LegNode(contract, d.id, d.silver_ref, d.region)
            commodity, country = casc._scope(node, row)
            row2 = casc._region_row(node, row) if country is not casc.SKIP_NODE else row
            yield contract, d.id, row2, node, commodity, country


# ---------------------------------------------------------------------------
# Check family 2 -- country vocabulary (France->EU / Cote d'Ivoire resolved-country class).
# ---------------------------------------------------------------------------
def check_country_vocabulary(reg, *, query_fn, caches=None) -> list[str]:
    """Every country a `country_rule=region` leg RESOLVES to (via region_map) must exist in the DISTINCT
    country set of the numbers table the leg maps to -- the France->EU / Cote d'Ivoire class the cascade
    census catches at runtime, here promoted to a pre-serve gate. Currency-only region legs (fred_fx, no
    country column) and projection tables are skipped."""
    caches = caches if caches is not None else {}
    errs: list[str] = []
    seen: set[tuple] = set()
    for contract, did, row, node, _commodity, country in _mapped_legs():
        if country is casc.SKIP_NODE or country is None:
            continue
        if (row or {}).get("country_rule") != "region":
            continue
        table = (row or {}).get("table")
        if not table or table in NUMBERS_PROJECTION_TABLES:
            continue
        try:
            ts = reg.get(table)
        except Exception:  # noqa: BLE001 -- an unregistered table is check_cascade_map's problem, not C002's
            continue
        ccol = getattr(ts, "country_col", None)
        if not ccol:
            continue  # currency-routed region leg (fred_fx) -- no country vocabulary to assert
        country = str(country)
        key = (table, ccol, country)
        if key in seen:
            continue
        seen.add(key)
        # probe the PHYSICAL table: the leg carries the agent-facing id (silver_esr), which does not
        # exist in the pg mirror -- and on Athena would be the PROJECTED table (the LIST-storm class).
        # Live-caught at the first Branch-A gate fire (BF-W2 step 12.6).
        titles = caches.setdefault(("distinct", _physical(ts), ccol),
                                   cc._distinct_set(_physical(ts), ccol, query_fn))
        if country not in titles:
            errs.append(f"{contract}/{did}: region-resolved country {country!r} not in DISTINCT {ccol} "
                        f"of {table} (region_map resolve target absent -- the France->EU class)")
    return errs


# ---------------------------------------------------------------------------
# Check family 3 -- commodity-slug vocabulary (PSD slug-miss / PSD_SLUG_ALIAS class).
# ---------------------------------------------------------------------------
def check_commodity_slug_vocabulary(reg, *, query_fn, caches=None) -> list[str]:
    """Every commodity slug a mapped leg resolves to must exist in the DISTINCT commodity set of the numbers
    table the leg maps to -- the commodity-slug-miss class (silver_psd tracks no cocoa/orange-juice slug).
    Projection tables and slug-less tables (fred_fx/noaa_oni) are skipped."""
    caches = caches if caches is not None else {}
    errs: list[str] = []
    seen: set[tuple] = set()
    for contract, did, row, node, commodity, country in _mapped_legs():
        if country is casc.SKIP_NODE or commodity is None:
            continue
        table = (row or {}).get("table")
        if not table or table in NUMBERS_PROJECTION_TABLES:
            continue
        try:
            ts = reg.get(table)
        except Exception:  # noqa: BLE001
            continue
        scol = getattr(ts, "commodity_col", None)
        if not scol:
            continue
        commodity = str(commodity)
        if table == "silver_psd" and commodity in casc.PSD_UNSERVED_SLUGS:
            continue                          # declared-unserved (cascade SKIPs these legs at _scope)
        key = (table, scol, commodity)
        if key in seen:
            continue
        seen.add(key)
        # PHYSICAL table, same as the country check above (agent id -> served table).
        slugs = caches.setdefault(("distinct", _physical(ts), scol),
                                  cc._distinct_set(_physical(ts), scol, query_fn))
        if commodity not in slugs:
            errs.append(f"{contract}/{did}: commodity slug {commodity!r} not in DISTINCT {scol} "
                        f"of {table} (commodity-slug-miss -- the PSD_SLUG_ALIAS class)")
    return errs


# ---------------------------------------------------------------------------
# The combined check (callable -- the silver_rebuild_gate Branch-A stage-3 entry point).
# ---------------------------------------------------------------------------
def contract_check(reg=None, *, query_fn, column_fn=None, caches=None) -> list[str]:
    """Run all three vocabulary families against the pg mirror and return the combined, ordered list of
    drift errors (empty == green). `query_fn` MUST be pgnumbers.pg_query (or a test mock); `column_fn`
    defaults to the F010 silver-registry column resolver. `caches` is a per-run DISTINCT-set cache so each
    (table, col) is queried at most once (pass one in to share it with a caller)."""
    reg = reg if reg is not None else load_registry()
    caches = caches if caches is not None else {}
    errs: list[str] = []
    errs += check_metric_vocabulary(reg, query_fn=query_fn, column_fn=column_fn, caches=caches)
    errs += check_country_vocabulary(reg, query_fn=query_fn, caches=caches)
    errs += check_commodity_slug_vocabulary(reg, query_fn=query_fn, caches=caches)
    return errs


def _artifact(errs: list[str], *, distinct_queries: int) -> dict:
    return {
        "check": "contract_check",
        "package": "SILVER-C002",
        "tables_checked": _numbers_table_ids(load_registry()),
        "projection_excluded": sorted(NUMBERS_PROJECTION_TABLES),
        "distinct_queries": distinct_queries,
        "errors": errs,
        "verdict": "PASS" if not errs else "FAIL",
    }


def run_live(out_path=None) -> int:
    """The live pg-mirror run: env asserts + Athena firewall + artifact write + non-zero exit on drift. The
    firewall (reused from cascade_census) makes Q.athena_query_fn raise-on-invoke and asserts Q.STATS empty
    -- the observable ZERO-Athena guarantee (projection tables are never even reached)."""
    from leviathan.graphrag.numbers import pgnumbers
    assert os.environ.get("GRAPHRAG_NUMBERS_BACKEND", "").strip().lower() == "pg", \
        "contract_check requires GRAPHRAG_NUMBERS_BACKEND=pg (pg-mirror-only by construction)"
    assert os.environ.get("EVIDENCE_PG_DSN"), "contract_check requires EVIDENCE_PG_DSN"
    assert pgnumbers.enabled(), "contract_check requires pgnumbers.enabled() (backend=pg + DSN)"
    caches: dict = {}
    with cc._athena_firewall():
        errs = contract_check(query_fn=pgnumbers.pg_query, caches=caches)
    distinct_queries = sum(1 for k in caches if k and k[0] == "distinct")
    artifact = _artifact(errs, distinct_queries=distinct_queries)

    if out_path:
        from pathlib import Path
        dest = Path(out_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(artifact, indent=1), encoding="utf-8")
        print(f"contract_check artifact -> {dest}")

    print(f"contract_check: {len(artifact['tables_checked'])} numbers tables, "
          f"{distinct_queries} DISTINCT probe(s), verdict={artifact['verdict']}")
    if errs:
        print(f"FAIL contract_check: {len(errs)} vocabulary drift(s):")
        for e in errs:
            print(f"  - {e}")
    return 1 if errs else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="contract_check (SILVER-C002): numbers-stack I1 vocabulary gate")
    ap.add_argument("--json", dest="out", default=None, help="artifact output path (optional)")
    a = ap.parse_args(argv)
    return run_live(a.out)


if __name__ == "__main__":
    sys.exit(main())
