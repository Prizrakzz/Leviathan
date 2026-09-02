"""D-DA STEP 10 -- the pool-census instrument (KD10's reader) + the F3 false-join scan. Local, $0.

Reads an arm's REPORT markdown (the rendered artifact) and measures, per answer and deck-wide:

  A. POOL DENSIFICATION (round-1 F5 / round-2 F1): the [N] Sources rows' magnitudes form the pool a
     stray prose numeral could accidentally back against. Measured with the verifier's LIVE predicate
     -- ``_num_backed(v, pool, dec=d)`` with written decimals, NEVER the bare ``dec=None`` form (the
     measured divergence: 12.66 backs a stray integer '13' live and not bare). Three numbers:
     integers 1..100 free-passable; collision share over a DETERMINISTIC log-spaced probe grid
     (declared: 400 points, 10**linspace(-1, 4), dec=2 -- a grid, never a random draw); in-band
     [0.5, 150] pool count.

  B. THE FALSE-JOIN SCAN (round-2 F3's instrument): prose sentences citing >= 2 [N] handles AND a
     relational/derivation verb, with the MAX pairwise [known ...] stamp gap of the cited rows --
     the meal/oil class ("settled at X [N7], which the board values at Y [N2]" across 8 days).

POOL PROXY, DECLARED: the rendered Sources block IS the pool proxy. Orphan-pruned rows are absent
from it, so the proxy UNDERCOUNTS the in-flight pool equally on both arms -- the control-vs-
treatment DELTA (the KD10 gate's actual subject) is unbiased; absolute levels are floors.

    python jobs/utils/dda_pool_census.py --report data/batch_runs/<arm_report>.md
    python jobs/utils/dda_pool_census.py --report <treatment.md> --control <control.md>
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys

sys.path.insert(0, "src")
from leviathan.graphrag.verify import _claim_numbers_with_decimals, _mask_handles, _num_backed  # noqa: E402

_SRC_LINE = re.compile(r"^\[N(\d+)\]\s+(.*?)=\s*([-+]?[\d,]+(?:\.\d+)?)")
_KNOWN = re.compile(r"\[known\s+([0-9]{4}-?[0-9]{2}-?[0-9]{2})\]")
_HANDLE = re.compile(r"\[N(\d+)(?:\]|,)")
_REL_VERB = re.compile(
    r"which the board values|equivalent to|translates? (?:in)?to|implies|works out to|"
    r"divided by|ratio of|per bushel of|net of|derived from|that is,|i\.e\.|=", re.I)
_GRID = [10 ** (-1 + 5 * k / 399) for k in range(400)]


def _sections(md: str) -> dict:
    out = {}
    starts = [(m.start(), m.group(1)) for m in re.finditer(r"^## ((?:rv|dv)_\w+)  \(", md, re.M)]
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(md)
        out[name] = md[pos:end]
    return out


def _census_one(seg: str) -> dict:
    pool: list[float] = []
    stamps: dict[int, str] = {}
    for line in seg.splitlines():
        m = _SRC_LINE.match(line.strip())
        if not m:
            continue
        try:
            pool.append(float(m.group(3).replace(",", "")))
        except ValueError:
            continue
        km = _KNOWN.search(line)
        if km:
            stamps[int(m.group(1))] = km.group(1).replace("-", "")
    free_ints = sum(1 for k in range(1, 101) if pool and _num_backed(float(k), pool, dec=0))
    grid_hits = sum(1 for v in _GRID if pool and _num_backed(v, pool, dec=2))
    inband = sum(1 for v in pool if 0.5 <= abs(v) <= 150.0)
    # the F3 scan over the answer prose (everything before the Sources block)
    body = seg.split("\n## Sources")[0]
    joins = []
    for sent in re.split(r"(?<=[.;])\s+", body):
        handles = [int(h) for h in _HANDLE.findall(sent)]
        if len(set(handles)) < 2 or not _REL_VERB.search(_mask_handles(sent)):
            continue
        ds = [stamps.get(h) for h in set(handles) if stamps.get(h)]
        if len(ds) >= 2:
            gap = max(abs(int(a) - int(b)) for a in ds for b in ds)   # crude day-ish gap on YYYYMMDD
            if gap > 0:
                joins.append({"gap_key": gap, "handles": sorted(set(handles)),
                              "sent": sent.strip()[:180]})
    return {"pool_n": len(pool), "free_ints_1_100": free_ints,
            "grid_collision_share": round(grid_hits / len(_GRID), 4),
            "inband_pool": inband, "false_joins": joins}


def run(report: str) -> dict:
    md = io.open(report, encoding="utf-8").read()
    per = {name: _census_one(seg) for name, seg in _sections(md).items()}
    agg = {
        "answers": len(per),
        "mean_free_ints": round(sum(p["free_ints_1_100"] for p in per.values()) / max(len(per), 1), 2),
        "mean_grid_collision": round(sum(p["grid_collision_share"] for p in per.values())
                                     / max(len(per), 1), 4),
        "max_inband_pool": max((p["inband_pool"] for p in per.values()), default=0),
        "false_join_sentences": sum(len(p["false_joins"]) for p in per.values()),
    }
    return {"report": report, "aggregate": agg, "per_answer": per}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--control", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    res = {"treatment": run(a.report)}
    if a.control:
        res["control"] = run(a.control)
        ta, ca = res["treatment"]["aggregate"], res["control"]["aggregate"]
        res["delta"] = {k: round(ta[k] - ca[k], 4) for k in ta if isinstance(ta[k], (int, float))}
    body = json.dumps(res, indent=1)
    if a.out:
        io.open(a.out, "w", encoding="utf-8").write(body)
        print(f"[artifact] {a.out}")
    print(json.dumps({k: v.get("aggregate", v) if isinstance(v, dict) else v
                      for k, v in res.items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
