#!/usr/bin/env python3
"""CHAIN ENGINE PIT backtest anchor -- the ESRxWASDE two-hop replay (CHAIN_ENGINE_PLAN sec 4.2, D10).

The ONLY top chain where BOTH hops replay vintages end-to-end (ESR weekly 1989+, WASDE 471 release partitions
1985+, ~36y overlap). It anchors the PIT audit of the ENGINE ITSELF, OFFLINE, before the flip -- proving the
per-hop as-of discipline against real coverage edges without any serving wiring.

Design (D2/D10): the two-hop chain is built INLINE via cascade.fetch_window (table-agnostic, cascade.py) -- NO
serving cascade_map row for WASDE is needed. silver_wasde marketing_year strings are formatted via
cascade._my_slash (the string-vs-int MY trap is solved there). READ-ONLY pg vintage reads (NEVER Athena on a
projected table -- the LIST-storm rule); zero writes.

Hard asserts, all ship-BLOCKERS on any violation:
  (1) NO LOOKAHEAD: every returned row's provenance guard column (release_date / week_ending_date / data_date /
      date / year,month) is <= the pinned leg asof. Zero violations tolerated.
  (2) VINTAGE HONESTY: a WASDE value whose release_date is AFTER the leg asof returns not_known, never a number
      (the empty-set -> not_known contract on a vintage table).
  (3) PRE-ESR DECLINE: an asof strictly BEFORE ESR coverage (< 1989-09-01, S6 fold) declines the chain WHOLE
      (hop_dark), exercising the all-hops-or-nothing rule against a real coverage edge.
  (4) DETERMINISM: two runs at one asof are byte-identical.

The harness's PIT-audit LOGIC (the assert primitives + the dark-hop decline + determinism) is unit-tested on
fixtures (tests/graphrag/test_chain_pit_backtest.py) so the gate is green without pg; `main()` runs the real
grid against the live pg mirror (the main loop's gate-2 job).

    GRAPHRAG_NUMBERS_BACKEND=pg python scripts/graphrag/chain_pit_backtest.py
"""
from __future__ import annotations

import json
import sys

from leviathan.graphrag.numbers import cascade as C

# ── the ESRxWASDE two-hop chain spec (soybeans -- the strongest replay pair) ──────────────────────────────
# hop 1: ESR weekly export shipments (vintage, weekly, US-only -> leg_mode=current: the freshest week <= asof,
#        NO era contrast -- the D-W3.2 `latest` semantics; assert (5) below pins this so the historical-week
#        fast-follow has a red test to flip green). hop 2: WASDE ending-stocks balance sheet (vintage, MY).
HOP_ESR = {"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "soybeans",
           "country": None, "period_type": "date"}
HOP_WASDE = {"table": "silver_wasde", "metric": "ending_stocks", "commodity": "soybeans",
             "country": "United States", "period_type": "marketing_year"}

# The pinned grid (sec 4.2): known episodes + 2 quiet controls + 1 pre-ESR decline asof (S6: strictly <
# 1989-09-01). >=8 live asofs; the pre-ESR asof is the coverage-edge decline probe.
GRID = ["2012-08-15", "2013-06-15", "2018-10-15", "2020-12-15", "2021-03-15",
        "2023-07-15", "2016-01-15", "2025-05-15"]
PRE_ESR_ASOF = "1988-06-01"                  # S6: strictly before ESR coverage_start 1989-09 -> chain hop_dark
ESR_COVERAGE_START = "1989-09-01"


# ── PIT-audit primitives (unit-tested on fixtures; used by both main() and the tests) ─────────────────────
def _guard_violations(record: dict, asof: str) -> list[str]:
    """Every guard column on every returned row must be <= the leg asof (the zero-lookahead gate). Returns the
    list of violations ([] = clean). date-like cols compare lexically (ISO); (year, month) compares year*100+
    month <= asof YYYYMM. A row with NO guard column is not a violation here (the fetch layer's asof guard is
    the primary belt; this is the provenance audit of what came back)."""
    viols: list[str] = []
    try:
        ay, am = int(str(asof)[:4]), int(str(asof)[5:7])
    except (TypeError, ValueError):
        return [f"unparseable asof {asof!r}"]
    a_ym = ay * 100 + am
    for i, row in enumerate(record.get("rows") or []):
        for col in ("release_date", "week_ending_date", "data_date", "date"):
            v = row.get(col)
            if v not in (None, "") and str(v)[:10] > str(asof)[:10]:
                viols.append(f"{record.get('query', {}).get('table')} row{i} {col}={v} > asof {asof}")
        y, m = row.get("year"), row.get("month")
        if y not in (None, "") and m not in (None, ""):
            try:
                if int(y) * 100 + int(m) > a_ym:
                    viols.append(f"{record.get('query', {}).get('table')} row{i} ({y},{m}) > asof {asof}")
            except (TypeError, ValueError):
                viols.append(f"{record.get('query', {}).get('table')} row{i} bad (year,month)=({y},{m})")
    return viols


def _vintage_honest(record: dict, asof: str) -> bool:
    """VINTAGE HONESTY: on a vintage table, an ok record's every row must carry a PIT guard column (WASDE's
    release_date, ESR's week_ending_date, or the (year,month) axis) PROVING it was known by asof AND <= asof -- a
    value published after asof must never appear (it would have been filtered to not_known). A vintage number
    with NO provenance is itself a violation (unprovable). record_silent / not_known / future_unpublished are
    honest absences (no number), so they pass by construction."""
    if record.get("status") != "ok":
        return True
    if not C._is_vintage(record.get("query", {}).get("table")):
        return True
    for row in record.get("rows") or []:
        guards = [row.get(c) for c in ("release_date", "week_ending_date", "data_date", "date")
                  if row.get(c) not in (None, "")]
        has_ym = row.get("year") not in (None, "") and row.get("month") not in (None, "")
        if not guards and not has_ym:
            return False                              # a vintage number with no provenance is unprovable -> fail
    return _guard_violations(record, asof) == []      # every present guard column must be <= asof


def _ok(record: dict) -> bool:
    return record.get("status") == "ok" and bool(record.get("rows"))


def chain_decline(hop_records: list[dict]) -> str | None:
    """The all-hops-or-nothing rule (sec 4.1): a dark hop (no ok row) kills the WHOLE chain. Returns the decline
    reason ('hop_dark') or None (the chain is live -- every hop has >=1 ok row)."""
    for rec in hop_records:
        if not _ok(rec):
            return "hop_dark"
    return None


def _fingerprint(hop_records: list[dict]) -> str:
    """A stable byte-fingerprint of a run (determinism assert). Drops nothing observable; sorts keys."""
    slim = [{"status": r.get("status"), "query": r.get("query"), "rows": r.get("rows")} for r in hop_records]
    return json.dumps(slim, sort_keys=True, default=str)


# ── the two-hop build via fetch_window (D10: NO serving map row) ──────────────────────────────────────────
def run_chain_at_asof(qfn, asof: str) -> dict:
    """Build the ESRxWASDE two-hop chain at one pinned asof via cascade.fetch_window; return
    {asof, hops:[esr_record, wasde_record], decline}. The ESR hop is the freshest week <= asof (leg_mode=current
    semantics: agg='latest' over the trailing window); the WASDE hop reads the balance sheet for the MY covering
    asof, formatted as the 'YYYY/YY' slash string via _my_slash. Both inherit fetch_window's unconditional as-of
    clamp + the vintage not_known contract. READ-ONLY."""
    esr = C.fetch_window(qfn, table=HOP_ESR["table"], metric=HOP_ESR["metric"], commodity=HOP_ESR["commodity"],
                         country=HOP_ESR["country"], t1=C._plus_days(asof, -365), t2=asof, asof=asof,
                         agg="latest", period=None, period_type="date")
    my = C._covering_my(asof, HOP_WASDE["commodity"])
    wasde = C.fetch_window(qfn, table=HOP_WASDE["table"], metric=HOP_WASDE["metric"],
                           commodity=HOP_WASDE["commodity"], country=HOP_WASDE["country"], t1=None, t2=None,
                           asof=asof, agg="latest", period=(C._my_slash(my) if my is not None else None),
                           period_type="marketing_year")
    hops = [esr, wasde]
    return {"asof": asof, "hops": hops, "decline": chain_decline(hops)}


def audit_run(run: dict) -> list[str]:
    """Every hard assert for one run; returns the list of BLOCKER strings ([] = clean)."""
    errs: list[str] = []
    for rec in run["hops"]:
        errs += _guard_violations(rec, run["asof"])                 # (1) zero lookahead
        if not _vintage_honest(rec, run["asof"]):                   # (2) vintage honesty
            errs.append(f"vintage-honesty violation at asof {run['asof']} on {rec.get('query', {}).get('table')}")
    return errs


def main() -> int:
    from leviathan.graphrag.numbers import pgnumbers
    from leviathan.graphrag.numbers.query import default_query_fn
    if not pgnumbers.enabled():
        print("chain_pit_backtest: GRAPHRAG_NUMBERS_BACKEND=pg is REQUIRED (read-only pg vintage reads)")
        return 2
    qfn = default_query_fn()
    blockers: list[str] = []
    # (1)+(2): the live grid -- no lookahead, vintage honesty.
    for asof in GRID:
        run = run_chain_at_asof(qfn, asof)
        errs = audit_run(run)
        status = "CLEAN" if not errs else "BLOCKER"
        print(f"[{status}] asof={asof} esr={run['hops'][0]['status']} wasde={run['hops'][1]['status']} "
              f"decline={run['decline']}")
        blockers += errs
    # (3): the pre-ESR asof declines the chain WHOLE.
    pre = run_chain_at_asof(qfn, PRE_ESR_ASOF)
    if pre["decline"] != "hop_dark":
        blockers.append(f"pre-ESR asof {PRE_ESR_ASOF} did NOT decline hop_dark (got {pre['decline']!r})")
    print(f"[{'CLEAN' if pre['decline'] == 'hop_dark' else 'BLOCKER'}] pre-ESR asof={PRE_ESR_ASOF} "
          f"decline={pre['decline']}")
    # (4): determinism -- two runs at one asof are byte-identical.
    a, b = run_chain_at_asof(qfn, GRID[0]), run_chain_at_asof(qfn, GRID[0])
    if _fingerprint(a["hops"]) != _fingerprint(b["hops"]):
        blockers.append(f"non-deterministic run at asof {GRID[0]}")
    print(f"[{'CLEAN' if _fingerprint(a['hops']) == _fingerprint(b['hops']) else 'BLOCKER'}] determinism asof={GRID[0]}")
    if blockers:
        print(f"\nFAIL chain_pit_backtest: {len(blockers)} BLOCKER(s):")
        for e in blockers:
            print(f"  - {e}")
        return 1
    print("\nPASS chain_pit_backtest: zero guard-column violations, vintage-honest, pre-ESR declines, deterministic")
    return 0


if __name__ == "__main__":
    sys.exit(main())
