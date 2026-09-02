"""CASCADE EPISODE WALK -- the K0(a)-failure substrate census. $0, local, S3-read-only.

THE FINDING THIS MEASURES (sitting 0, 2026-09-01): K0 half (a) failed 0/18 -- every shipping
root's OWN timeline windows are either a GAP_DAYS=90 mega-blob (corn: 1991-11-12..2026-09-01,
n=2306 -- monthly WASDE cadence never leaves a 90-day gap, so the modern era is ONE cluster) or
ancient pre-coverage windows. The v3 design's firing substrate (the root node's own post-coverage
episode windows) DOES NOT EXIST on dense commodity slices.

THE QUESTION: does a viable substrate exist anywhere in the artifact -- sharp (span <= 1460d),
modern (start >= 2010-06-06, the modal board floor), corroborated (n >= 2 at asof) windows --
and which nodes carry them? Split by whether the node resolves to a tape board (J4's own
_episode_slug) or is a driver slice. This decides whether a DRIVER-WINDOW-FIRED walk (price the
hop's two boards over the driver event's window) has measured legs before any redesign sitting.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

sys.path.insert(0, "src")

ASOF = "2026-09-01"
MODERN_FLOOR = "2010-06-06"      # the modal PRICE_COVERAGE_START on the shipping boards
SHARP_MAX_DAYS = 1460            # cascade.EPISODE_SPAN_MAX_DAYS -- beyond it nothing can price
MIN_N = 2                        # timeline.MIN_PROPS, the corroboration floor


def _days(iso):
    return dt.date.fromisoformat(str(iso)[:10]).toordinal()


def main() -> int:
    os.environ["GRAPHRAG_TIMELINE"] = "on"
    from leviathan.graphrag import timeline as TL
    from leviathan.graphrag.numbers import cascade as C
    art = TL._load()
    asof_d = dt.date.fromisoformat(ASOF)
    out = {"census": "cw_substrate", "asof": ASOF, "modern_floor": MODERN_FLOOR,
           "sharp_max_days": SHARP_MAX_DAYS, "min_n": MIN_N,
           "timeline_status": {k: TL.load_status().get(k) for k in ("state", "n_nodes")},
           "nodes": {}}
    n_nodes = n_board = n_driver = 0
    for node in sorted(art):
        eps = []
        for ep in art.get(node) or []:
            vis = [d for d in ep.get("dates") or []
                   if dt.date.fromisoformat(str(d)[:10]) <= asof_d]
            if len(vis) < MIN_N:
                continue
            start, end = str(vis[0]), str(vis[-1])
            span = _days(end) - _days(start)
            if start >= MODERN_FLOOR and span <= SHARP_MAX_DAYS:
                eps.append({"start": start, "end": end, "n": len(vis), "span_days": span})
        if not eps:
            continue
        eps.sort(key=lambda e: e["end"], reverse=True)
        slug = C._episode_slug(node)
        out["nodes"][node] = {"slug": slug, "n_sharp_modern": len(eps), "windows": eps[:6]}
        n_nodes += 1
        if slug:
            n_board += 1
        else:
            n_driver += 1
    out["summary"] = {
        "nodes_with_sharp_modern_windows": n_nodes,
        "board_resolvable_nodes": n_board,
        "driver_nodes": n_driver,
        "total_sharp_modern_windows": sum(v["n_sharp_modern"] for v in out["nodes"].values()),
    }
    dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                       "data", "batch_runs", f"cw_substrate_census_{ASOF.replace('-', '')}.json")
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps(out["summary"], indent=1))
    board_nodes = sorted(k for k, v in out["nodes"].items() if v["slug"])
    print("board-resolvable nodes with sharp modern windows:", board_nodes)
    drivers = sorted(((v["n_sharp_modern"], k) for k, v in out["nodes"].items() if not v["slug"]),
                     reverse=True)
    print("top driver nodes:", [(k, n) for n, k in drivers[:20]])
    print("banked", dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
