"""V2-5 F1 GOLDEN BANK -- the $0 baseline the flag-off byte-identity gate (G1) asserts against.

WHY THIS EXISTS. The v3 refute's FATAL: v3's G1 compared "`deep` absent from walk_request" against
"the flag OFF", both of which evaluate `deep_on = bool((walk_request or {}).get("deep"))` to False on
the SAME code path with the SAME inputs. That is a determinism check, not byte-identity, and it can
never fail. The estate law it was meant to hold -- flag-off byte-identity on a leg SERVING AT REV 126
-- needs a baseline captured BEFORE the edits land.

WHICH FUNCTION IT WRAPS, AND WHY THAT MOVED (v4 refute, FATAL 1). v1 of this producer wrapped the
INNER `_cascade_walk_legs` and deep-copied at its return -- BEFORE `_cascade_walk_leg_or_nothing`
(cascade.py:7048-7069) post-processes. That outer wrapper is the one function V2-5 actually edits (the
elapsed-ms stamp, the belt's `payload['deep']`, the trace write), so the inner bank was blind to every
byte of it: re-run at HEAD it recorded `raised: None` on all 89 calls, i.e. the R6 exception belt never
executed and no post-return mutation was ever observed. THIS VERSION WRAPS THE OUTER FUNCTION, and the
suite gained the two fixtures that reach the paths the population lacked -- a RAISING leg (the belt)
and `no_declared_children` (the only root-scope decline taken before child enumeration).

WHAT IT BANKS. Every call to `_cascade_walk_leg_or_nothing` made while
`tests/unit/test_cascade_walk.py` runs (plus, on request, any other suite that drives the leg), keyed
by pytest nodeid + per-test ordinal. Per call it records the rendered `lines` list VERBATIM, the FULL
payload dict including the ORDER of payload['declines'], the `calls` ledger delta the leg appended,
the request dict, and whether the ONE registered trace key came back identical to the returned
payload. Those are the surfaces a served turn can see.

`raised` STAYS IN THE RECORD SHAPE AND IS EXPECTED TO BE None EVERYWHERE. The outer function is the
belt: it does not propagate. The field is kept because a build that made the outer raise would be a
regression the bank must be able to name, and `None` here is a measurement, not an omission.

HOW G1 USES IT. After the build, re-run this script on the V2-5 tree with the flag OFF. Every banked
(nodeid, ordinal) must reproduce lines, payload, calls_delta EXACTLY -- and no payload may carry a
'deep' key. A single mismatch is an unflagged production change on a live leg: revert.

G1 IS A SUITE PIN, NOT A SCRATCHPAD SCRIPT (build-review major L1). The bank lives beside this
producer at data/consequence_leg/v25_golden_head_v2.json, and
tests/unit/test_cascade_walk.py::test_g1_the_flag_off_population_reproduces_the_banked_head_golden
runs this producer and joins the result against it. THE RECURSION IS CLOSED BY A SENTINEL: this
script exports V25_GOLDEN_INNER=1 into the pytest subprocess it spawns, and that pin SKIPS whenever
the sentinel is set -- so the inner run measures the whole suite and never re-enters itself.

$0, offline, no model calls, no AWS. Re-runnable: `python data/consequence_leg/v25_golden_bank.py`.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SUITES = ["tests/unit/test_cascade_walk.py"]
BANK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v25_golden_head_v2.json")
# THE RECURSION SENTINEL: exported into the pytest subprocess below, read by the G1 suite pin, which
# skips itself under it. Without it the pin would spawn a run that spawns a run that spawns a run.
INNER_ENV = "V25_GOLDEN_INNER"

# The plugin is written to a temp file and injected with `-p`; it must not import anything from this
# module (pytest loads it in its own process).
PLUGIN = r'''
import copy, functools, json, os
from leviathan.graphrag.numbers import cascade as cq

_OUT = os.environ["V25_GOLDEN_OUT"]
_REC = []
_CUR = {"nodeid": None, "n": 0}
_ORIG = cq._cascade_walk_leg_or_nothing     # THE OUTER FUNCTION -- refute-v4 fatal 1


def _safe(o):
    """JSON-safe, ORDER-PRESERVING. Sets are sorted (they are unordered by construction); every
    other container keeps its own order, which is the thing under test."""
    if isinstance(o, dict):
        return {str(k): _safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_safe(v) for v in o]
    if isinstance(o, (set, frozenset)):
        return {"__set__": sorted(_safe(v) for v in o)}
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    return {"__repr__": repr(o)}


@functools.wraps(_ORIG)                       # sets __wrapped__, so any inspect.getsource pin
def _wrapped(sg, graph, walk_request, qfn, asof, calls, **kw):    # still reads the REAL function
    _n0 = len(calls)                          # (the suite's :1030 pin reads the INNER, untouched)
    try:
        lines, payload = _ORIG(sg, graph, walk_request, qfn, asof, calls, **kw)
        err = None
    except Exception as e:                    # the belt does not propagate; a raise HERE is itself
        lines, payload, err = None, None, repr(e)         # the regression the bank must be able
        _REC.append({"nodeid": _CUR["nodeid"], "ordinal": _CUR["n"],   # to name
                     "request": _safe(walk_request), "asof": _safe(asof), "base": _n0,
                     "raised": err, "lines": None, "payload": None, "calls_delta": None,
                     "traced_is_payload": None})
        _CUR["n"] += 1
        raise
    try:                                      # the ONE registered trace key, as the turn sees it
        _traced = (sg.trace.get("quantify_cascade_walk") is payload)
    except Exception:                         # noqa: BLE001 -- a traceless sg is a banked state too
        _traced = None
    _REC.append({"nodeid": _CUR["nodeid"], "ordinal": _CUR["n"],
                 "request": _safe(walk_request), "asof": _safe(asof), "base": _n0,
                 "raised": None,
                 "traced_is_payload": _traced,
                 "lines": _safe(copy.deepcopy(lines)),
                 "payload": _safe(copy.deepcopy(payload)),
                 "calls_delta": _safe(copy.deepcopy(list(calls[_n0:])))})
    _CUR["n"] += 1
    return lines, payload


cq._cascade_walk_leg_or_nothing = _wrapped


def pytest_runtest_setup(item):
    _CUR["nodeid"] = item.nodeid.replace("\\", "/")
    _CUR["n"] = 0


def pytest_sessionfinish(session, exitstatus):
    with open(_OUT, "w", encoding="utf-8") as fh:
        json.dump({"exitstatus": int(exitstatus), "records": _REC}, fh,
                  ensure_ascii=False, sort_keys=False)
'''


def main() -> int:
    # A BARE RE-RUN NEVER OVERWRITES THE BANK. `BANK` is the baseline every later run is judged
    # against; re-banking it is a deliberate act (copy the rerun file over it, with a measurement in
    # hand), never a side effect of running this producer.
    out = (os.environ.get("V25_GOLDEN_OUT")
           or os.path.join(os.path.dirname(BANK), "v25_golden_rerun.json"))
    raw = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    raw.close()
    plug = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8")
    plug.write(PLUGIN)
    plug.close()
    env = dict(os.environ, V25_GOLDEN_OUT=raw.name, PYTHONPATH=os.path.join(REPO, "src"))
    env[INNER_ENV] = "1"                      # the G1 pin skips inside this run -- no recursion
    for k in list(env):
        if k.startswith("GRAPHRAG_"):
            env.pop(k)                        # a golden must not carry the runner's env
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
           "-p", os.path.splitext(os.path.basename(plug.name))[0]] + SUITES
    env["PYTHONPATH"] = os.pathsep.join([os.path.dirname(plug.name), env["PYTHONPATH"]])
    proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True)
    tail = (proc.stdout or "")[-3000:] + (proc.stderr or "")[-2000:]
    with open(raw.name, encoding="utf-8") as fh:
        cap = json.load(fh)
    recs = cap["records"]
    # THE BANK IS KEYED, NOT ORDERED: pytest ordering is stable but the key is what G1 joins on.
    bank = {}
    for r in recs:
        bank["%s#%d" % (r["nodeid"], r["ordinal"])] = {
            "request": r["request"], "asof": r["asof"], "raised": r["raised"],
            "traced_is_payload": r["traced_is_payload"],
            "lines": r["lines"], "payload": r["payload"], "calls_delta": r["calls_delta"]}
    body = json.dumps(bank, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    doc = {
        "what": ("V2-5 F1 GOLDEN BANK v2 -- the TREE's _cascade_walk_leg_or_nothing (the OUTER "
                 "function, refute-v4 fatal 1) over every fixture that drives it"),
        "suites": SUITES,
        "pytest_exitstatus": cap["exitstatus"],
        "pytest_tail": tail,
        "n_calls": len(recs),
        "n_keys": len(bank),
        "bank_sha256": sha,
        "how_g1_uses_it": ("re-run this script on the V2-5 tree with GRAPHRAG_CASCADE_DEEP unset; "
                           "every key must reproduce lines/payload/calls_delta exactly and no "
                           "payload may carry a 'deep' key"),
        "bank": bank,
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=False)
    print("wrote %s  calls=%d keys=%d sha256=%s exit=%s"
          % (out, len(recs), len(bank), sha, cap["exitstatus"]))
    os.unlink(raw.name)
    os.unlink(plug.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
