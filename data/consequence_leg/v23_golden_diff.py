"""Name the exact (key, field, path) drift between the banked deep-on golden and a fresh re-run.

L10/F1 discipline: a diff on this bank is allowed ONLY if it is NAMED and measured. This prints the
set of leaf paths that moved, so the re-anchor stands on evidence.

USAGE
    V23_GOLDEN_OUT=<scratch>/fresh.json python data/consequence_leg/v23_golden_deep_bank.py
    python data/consequence_leg/v23_golden_diff.py <scratch>/fresh.json   # FRESH_JSON is REQUIRED

`FRESH_JSON` is any file the producer wrote (V23_GOLDEN_OUT points it anywhere). The comparison is
restricted to the keys the BANK carries, which is exactly the population the pin
tests/unit/test_cascade_walk.py::test_g1d_... asserts: new keys are a superset by construction
whenever the suite gains fixtures, and are never a diff.

data/consequence_leg/v23_golden_deep_on_prebuild.json is the PRE-BUILD (V2-3 phase 2) forced bank,
kept as EVIDENCE for the L10 re-anchor that build measured (build-review minor: it had survived only
in a session scratchpad). Its shape is the older single-`bank` one, so it is not a `bank_native` /
`bank_forced` document and this script does not read it; `json.load(...)["bank_sha256"]` is the
number the build report's `banked_before.forced` names.
"""
import json
import os
import sys

D = os.path.dirname(os.path.abspath(__file__))
BANK = os.path.join(D, "v23_golden_deep_on.json")
FRESH = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("V23_GOLDEN_OUT")
if not FRESH:
    raise SystemExit("usage: v23_golden_diff.py FRESH_JSON  (or set V23_GOLDEN_OUT) -- the rerun file is never a default: "
                     "a byte-duplicate of the bank must not be re-created beside the gate")

old = json.load(open(BANK, encoding="utf-8"))
new = json.load(open(FRESH, encoding="utf-8"))


def leaves(o, pre=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, pre + "." + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, pre + "[" + str(i) + "]")
    else:
        yield pre, o


report = {}
for section in ("native", "forced"):
    ob = old["bank_" + section]
    nb = new["bank_" + section]
    paths_added, paths_removed, paths_changed = {}, {}, {}
    keys_missing = sorted(set(ob) - set(nb))
    keys_extra = sorted(set(nb) - set(ob))
    for k in sorted(set(ob) & set(nb)):
        o_l = dict(leaves(ob[k]))
        n_l = dict(leaves(nb[k]))
        for pth in sorted(set(n_l) - set(o_l)):
            paths_added[pth] = paths_added.get(pth, 0) + 1
        for pth in sorted(set(o_l) - set(n_l)):
            paths_removed[pth] = paths_removed.get(pth, 0) + 1
        for pth in sorted(set(o_l) & set(n_l)):
            if o_l[pth] != n_l[pth]:
                paths_changed.setdefault(pth, []).append((k, o_l[pth], n_l[pth]))
    report[section] = {
        "keys_banked": len(ob), "keys_fresh": len(nb),
        "keys_missing": keys_missing, "n_keys_extra": len(keys_extra),
        "paths_added": paths_added,
        "paths_removed": paths_removed,
        "paths_changed": {p: (len(v), v[0]) for p, v in sorted(paths_changed.items())},
    }
print(json.dumps(report, indent=1, sort_keys=True)[:12000])
