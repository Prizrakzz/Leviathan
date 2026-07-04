"""Silver-only convergence firing for the terminal read endpoints (build-plan P1.3/P1.4).

`fire_contract()` answers "which convergence regimes are supported at an as-of, by OBSERVED silver values"
— the deterministic, no-LLM, no-retrieval signal the Convergence heatmap (design §4.8) and the per-contract
convexity gauges (§4.4) render. It mirrors the SILVER-FIRST branch of `planner._basis`: a driver observed
ANOMALOUS at the as-of vintage counts toward firing; a driver observed NORMAL is VETOED (documented chatter
can't fire a regime the observed data contradicts). It reuses `graph.regimes()` for the threshold logic, so
the heatmap can never disagree with the answer path on silver-observed firing.

This is a deliberate SUBSET of the full answer-path firing, which ALSO fires on dated TEXT evidence when
silver is inconclusive. That extra leg needs per-driver retrieval (expensive over 31 contracts) and is
omitted here; the heatmap's honest framing is "where convexity is building, by observed fundamentals".
"""
from __future__ import annotations

from leviathan.graphrag import graph as gph


def _driver_row(did: str, sv: dict) -> dict:
    """Normalize a `silver_lookup` result into the driver row the gauge/heatmap shows (design §4.4)."""
    return {"id": did, "live": bool(sv.get("live")), "verdict": sv.get("verdict"),
            "z": sv.get("z"), "value": sv.get("value"), "unit": sv.get("unit", ""),
            "ref": sv.get("ref"), "knowledge_date": sv.get("knowledge_date", "")}


def fire_contract(graph: gph.CausalGraph, contract: str, asof: str, silver_lookup) -> dict:
    """Fire `contract`'s convergence regimes on OBSERVED silver values at `asof`.

    Returns {contract, regimes[], drivers[]}: each regime carries {name, direction, matched, threshold,
    fired, n_active, proximity} (proximity = n_active/threshold, capped at 1.0, for heatmap shading);
    each driver carries its silver verdict/value. `silver_lookup(contract, driver_id, asof)` is the only
    I/O (memoized + capped by `silverleg.make_silver_lookup`). An unknown contract raises KeyError — the
    route maps that to 404.
    """
    c = graph.contracts[contract]                                     # KeyError -> 404 at the route boundary
    required = sorted({d for s in c.convergence for d in s.drivers})
    active: list[str] = []
    drivers: list[dict] = []
    for did in required:
        sv = silver_lookup(contract, did, asof) or {}
        if sv.get("live") and sv.get("verdict") == "observed":        # OBSERVED anomaly -> counts toward firing
            active.append(did)                                        # (NORMAL is implicitly vetoed: never added)
        drivers.append(_driver_row(did, sv))

    fired_names = {fr.name for fr in graph.regimes(contract, active)}  # graph.regimes = the shared threshold authority
    regimes: list[dict] = []
    for s in c.convergence:
        matched = [d for d in s.drivers if d in active]
        fired = s.name in fired_names
        thr = s.requires_any_n_of or 1
        regimes.append({"name": s.name, "direction": s.direction, "matched": matched,
                        "threshold": s.requires_any_n_of, "fired": fired, "n_active": len(matched),
                        "proximity": round(min(1.0, len(matched) / thr), 3)})
    regimes.sort(key=lambda r: (not r["fired"], -r["proximity"]))      # fired first, then closest-to-firing
    return {"contract": contract, "regimes": regimes, "drivers": drivers}


def convergence_matrix(graph: gph.CausalGraph, asof: str, silver_lookup) -> list[dict]:
    """`fire_contract` fanned over every loaded contract — the 31-row Convergence heatmap (design §4.8).
    Deterministic; the silver reads are memoized/capped in the shared `silver_lookup`."""
    return [fire_contract(graph, cid, asof, silver_lookup) for cid in sorted(graph.contracts)]
