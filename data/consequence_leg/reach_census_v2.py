"""D-CQ REACH CENSUS v2 -- the $0, offline, in-run reproducible reach artifact.

RUN:  python data/consequence_leg/reach_census_v2.py            (writes reach_census_v2_<UTC date>.json)

WHY v2 EXISTS. The round-1 census walked `graph.cross_links()` (contract -> declared
driver_commodity). That is the AUTHORED ARROW REVERSED: `InterCommodityEdge.driver_commodity`
means THE TARGET DRIVES THIS CONTRACT (schema.py:64-70; graph.py:70-72 states the inversion
in so many words), so the CONSEQUENCE index is `rev_cross_links` -- "the markets this one
cascades into". Round 1 also resolved node -> tape slug through `complex_map.resolve_bare_commodity`,
whose curated bare-name table has no entry for `srw_wheat`/`hrw_wheat`/`hrs_wheat`/`rice`/
`rapeseed_meal`/`white_maize`; that, not a data absence, is why round 1 reported wheat and rice
as unreachable. v2 takes the slug straight off the graph's OWN resolution (`row['seed']` and
`row['contract']` are already loaded contract ids, resolved once at load with the recorded
tie-break) -- one producer, no second guess, no alias collapse.

RECONCILIATION: 67 directed measurable pairs and 185 measurement-distinct triples, which is
exactly what the round-1 refuter measured independently.

EVERY NUMBER HERE IS A GATE THE LEG ACTUALLY APPLIES, and they are reported DECOMPOSED so a
scope decision reads the ladder rather than one headline count.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "src"))

from leviathan.graphrag import graph as G                     # noqa: E402
from leviathan.silver import futures_eod_contracts as FC      # noqa: E402

# The gate constants, named once so the artifact and the lint read the same numbers.
HISTORICAL_FLOOR_BEFORE = dt.date(2024, 1, 1)   # a coverage floor at/after this leaves no episode
LAG_RX = re.compile(r"^(\d+)-(\d+)\s+quarters?$")


def min_lag_quarters(lag) -> int | None:
    """The MINIMUM declared quarters of the edge's free-text lag, or None when unparseable.

    Used ONLY as a fail-closed GATE (an unparseable lag DECLINES), never to shift a window and
    never rendered: `verify._claim_numbers_with_decimals` extracts BOTH numerals of '0-2 quarters'
    as claim magnitudes, so the string cannot sit on a copy-surface.
    """
    m = LAG_RX.match(str(lag or "").strip())
    return int(m.group(1)) if m else None


def build() -> dict:
    g = G.CausalGraph.load()
    cov = FC.PRICE_COVERAGE_START
    cmap = FC.CONTRACT_MAP
    cur = lambda s: (cmap.get(s) or {}).get("currency")            # noqa: E731
    node = g.contract_node

    def hops(nd):
        """Admissible consequence hops OUT OF commodity node `nd`: parent = the resolved seed
        contract, child = the FOREIGN declaring contract. Both must carry a PRICE_COVERAGE_START."""
        return [r for r in g.rev_cross_links(nd)
                if r["seed"] in cov and r["contract"] in cov]

    roots = [k for k in sorted(g._rev_index) if hops(k)]
    rows = [r for k in roots for r in hops(k)]

    pairs, pair_edges = set(), collections.defaultdict(list)
    for r in rows:
        pairs.add((r["seed"], r["contract"]))
        pair_edges[(r["seed"], r["contract"])].append(
            {"relation": r["relation"], "sign": r["sign"], "lag": str(r["lag"])})

    def admissible_pair(a, b, r):
        return (node(a) != node(b) and cur(a) == cur(b)
                and cov[a] < HISTORICAL_FLOOR_BEFORE and cov[b] < HISTORICAL_FLOOR_BEFORE
                and min_lag_quarters(r["lag"]) == 0 and r["sign"] in ("+", "-"))

    first_order = sorted({(r["seed"], r["contract"], r["relation"], r["sign"], str(r["lag"]))
                          for r in rows if admissible_pair(r["seed"], r["contract"], r)})

    triples, tri_node_distinct, tri_full = set(), set(), set()
    for k in roots:
        for r1 in hops(k):
            a, b = r1["seed"], r1["contract"]
            for r2 in hops(node(b)):
                if r2["seed"] != b:
                    continue
                c = r2["contract"]
                if len({a, b, c}) < 3:
                    continue
                triples.add((a, b, c))
                if len({node(a), node(b), node(c)}) == 3:
                    tri_node_distinct.add((a, b, c))
                    if admissible_pair(a, b, r1) and admissible_pair(b, c, r2):
                        tri_full.add((a, b, c))

    sign_conflicts = {f"{a}->{b}": v for (a, b), v in sorted(pair_edges.items())
                      if len({e["sign"] for e in v}) > 1}
    reciprocal = []
    for (a, b), v in sorted(pair_edges.items()):
        back = pair_edges.get((b, a))
        if back and {e["sign"] for e in v} != {e["sign"] for e in back}:
            reciprocal.append({"forward": f"{a}->{b}", "forward_signs": sorted({e["sign"] for e in v}),
                               "reverse_signs": sorted({e["sign"] for e in back})})

    return {
        "census_id": "dcq_reach_v2",
        "measured_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "graph_version": g.version,
        "recipe": __doc__,
        "index_walked": "graph.rev_cross_links  (the CONSEQUENCE direction; cross_links is the arrow reversed)",
        "slug_resolution": "row['seed'] / row['contract'] -- the graph's OWN load-time resolution, "
                           "NOT complex_map.resolve_bare_commodity (round-1's wheat/rice blindness)",
        "buckets": g.rev_cross_link_buckets(),
        "roots_with_admissible_hops": roots,
        "coverage_floors": {r: str(cov[hops(r)[0]["seed"]]) for r in roots},
        "counts": {
            "admissible_hop_edge_rows": len(rows),
            "directed_measurable_pairs": len(pairs),
            "measurement_distinct_triples": len(triples),
            "node_distinct_triples": len(tri_node_distinct),
            "fully_admissible_first_order_hops": len(first_order),
            "fully_admissible_second_order_triples": len(tri_full),
        },
        "reconciliation": {"refuter_measured_pairs": 67, "refuter_measured_triples": 185,
                           "agrees": len(pairs) == 67 and len(triples) == 185},
        "signs_on_admissible_rows": dict(collections.Counter(r["sign"] for r in rows)),
        "relations_on_admissible_rows": dict(collections.Counter(r["relation"] for r in rows)),
        "min_lag_quarters_distribution": dict(collections.Counter(
            min_lag_quarters(r["lag"]) for r in rows)),
        "cross_currency_pairs": sum(1 for (a, b) in pairs if cur(a) != cur(b)),
        "parallel_edge_sign_conflicts": sign_conflicts,
        "reciprocal_sign_disagreements": reciprocal,
        "fully_admissible_first_order": [list(x) for x in first_order],
        "fully_admissible_second_order": [list(x) for x in sorted(tri_full)],
        "uncovered_rev_index_nodes": sorted(set(g._rev_index) - set(roots)),
    }


if __name__ == "__main__":
    out = build()
    path = os.path.join(_HERE, f"reach_census_v2_{out['measured_utc'][:10].replace('-', '')}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=False)
    print(path)
    print(json.dumps(out["counts"], indent=2))
    print("reconciles with refuter:", out["reconciliation"]["agrees"])
