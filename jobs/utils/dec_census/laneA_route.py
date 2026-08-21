"""LANE A pass 1 -- run the PRODUCTION matcher pair over every cached prop, tag routed vs ZERO-ROUTED.

Exact production pair (evidence_batch.rebuild_slices:1438-1450):
    matchers = {n: hv.build_matcher(ev.match_forms(n)) for n in ev.all_nodes()}   # commodity_hit
    ev.driver_slices_for(text)  ->  ev.driver_matchers()                          # driver_hit
    dark-at-birth ("neither") = not commodity_hit and not driver_hit

Optimization that is NOT a semantic change: _Matcher.search(t) == self._rx.search(ex._normalize(t)).
We normalize each prop ONCE and run the same compiled ._rx objects against it. A union regex over all
forms answers "any hit" identically (\\b(alt|...)\\b backtracks through the alternation to satisfy the
trailing \\b), and that equivalence is VERIFIED against the full 137-matcher loop on a 20k sample below.
"""
import io, json, os, random, re, sys, time, collections

sys.path.insert(0, r"C:/Users/User/Desktop/Leviathan/src")
from leviathan.graphrag import evidence as ev, harvest as hv, extract as ex

S = r"C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad"
PROPS = os.path.join(S, "chunk_cache_props.jsonl")

nodes = ev.all_nodes()
node_matchers = {n: hv.build_matcher(ev.match_forms(n)) for n in nodes}
drv_matchers = ev.driver_matchers()
print("nodes=%d driver_slices=%d" % (len(nodes), len(drv_matchers)))

def _union(matchers):
    keys = set()
    for m in matchers.values():
        keys.update(m._idx.keys())
    keys = sorted(keys, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b") if keys else None

NODE_RX = _union(node_matchers)
DRV_RX = _union(drv_matchers)
print("node union forms=%d  driver union forms=%d"
      % (len(set().union(*[set(m._idx) for m in node_matchers.values()])),
         len(set().union(*[set(m._idx) for m in drv_matchers.values()]))))

# ---- load ----
t0 = time.time()
recs = []
with io.open(PROPS, "r", encoding="utf-8") as f:
    for line in f:
        recs.append(json.loads(line))
print("loaded %d props in %.1fs" % (len(recs), time.time() - t0))

# ---- equivalence check: union vs the real 137-matcher loop, 20k random props ----
rnd = random.Random(7)
sample = rnd.sample(recs, 20000)
bad = 0
t0 = time.time()
for p in sample:
    t = p["t"]
    nf = ex._normalize(t)
    truth_c = any(m.search(t) for m in node_matchers.values())
    truth_d = bool(ev.driver_slices_for(t))
    fast_c = NODE_RX.search(nf) is not None
    fast_d = DRV_RX.search(nf) is not None
    if truth_c != fast_c or truth_d != fast_d:
        bad += 1
        if bad <= 5:
            print("MISMATCH", truth_c, fast_c, truth_d, fast_d, t[:120].encode("ascii", "replace").decode())
print("equivalence check: %d/%d mismatches (%.1fs)" % (bad, len(sample), time.time() - t0))
if bad:
    raise SystemExit("union not equivalent -- abort")

# ---- full pass ----
t0 = time.time()
out_zero = io.open(os.path.join(S, "laneA_zero_routed.jsonl"), "w", encoding="utf-8")
counts = collections.Counter()
src_zero = collections.Counter()
src_all = collections.Counter()
nz = 0
for i, p in enumerate(recs):
    nf = ex._normalize(p["t"])
    c = NODE_RX.search(nf) is not None
    d = DRV_RX.search(nf) is not None
    key = ("commodity" if c else "") + ("+driver" if d else "")
    counts["both" if (c and d) else "commodity_only" if c else "driver_only" if d else "neither"] += 1
    src_all[p.get("src") or "?"] += 1
    if not c and not d:
        nz += 1
        src_zero[p.get("src") or "?"] += 1
        p["nf"] = nf
        out_zero.write(json.dumps(p) + "\n")
    if i and i % 50000 == 0:
        print("  %d/%d  zero=%d  %.0fs" % (i, len(recs), nz, time.time() - t0))
out_zero.close()
print("full pass %.1fs" % (time.time() - t0))
print(json.dumps(dict(counts), indent=1))
print("TOTAL", len(recs), "ZERO-ROUTED", nz, "=%.2f%%" % (100.0 * nz / len(recs)))

json.dump({"total": len(recs), "counts": dict(counts),
           "src_all": dict(src_all), "src_zero": dict(src_zero),
           "nodes": nodes, "n_driver_slices": len(drv_matchers)},
          io.open(os.path.join(S, "laneA_route_summary.json"), "w", encoding="utf-8"), indent=1)
print("wrote laneA_zero_routed.jsonl + laneA_route_summary.json")
