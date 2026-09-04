"""V2-3 DEEP-ON / XCCY-OFF GOLDEN BANK -- the second byte-identity baseline, banked BEFORE the
cross-currency build lands (law L10).

WHY A SECOND GOLDEN. V2-5's G1 bank (v25_golden_bank.py -> v25_golden_head_v2.json, sha e0dc1e5d)
holds ONE law: with the deep flag OFF the leg is byte-identical to rev-126 serving. It says nothing
about the DEEP regime -- and V2-3 lands INSIDE that regime: it refactors the three budget
inequalities into one `_cw_slack` helper, re-collects the hop ledger as a dict keyed by
_CW_HOP_LEVELS, and threads a new request key through the same selection line. Every one of those
edits can move a deep-on turn while leaving every flag-off turn alone, and nothing in the estate
would notice.

WHAT IT WRAPS. The OUTER `_cascade_walk_leg_or_nothing` -- the same function the V2-5 producer wraps,
for the same reason (V2-5 refute-v4 fatal 1): the elapsed-ms stamp, the belt's `payload['deep']` and
the trace write all live in the outer function, and the inner one is blind to them.

TWO PASSES, BECAUSE NEITHER ONE ALONE IS THE REGIME.

  PASS A -- NATIVE (`bank_native`). The suite runs exactly as it stands, GREEN, and every call whose
  own fixture asked for `deep` is banked. These are the shapes V2-5 authored deliberately: breadth on
  four children, the third-order chain, the free cell, the width belt, the hop-3 verdict rows, the
  closed rectangle on every root-scope decline. Nothing is perturbed, so nothing is truncated, and
  the pass must be GREEN -- that is gated.

  PASS B -- FORCED (`bank_forced`). The wrapper copies each request and sets `deep` when the fixture
  did not, so the WHOLE fixture population is measured under the regime prod takes when
  GRAPHRAG_CASCADE_DEEP=on: under that flag every served turn is a deep turn, the odd shapes
  included -- root declines, the palm free leg, the fenced block, the price-replay belt, the
  exception belt, the context rider. Forcing makes the suite's flag-off assertions fail (15 reds at
  HEAD 1085f03d) and a failing test stops making calls, so pass B is a SUBSET of the population by
  construction and pass A is what covers the shapes it truncates away. Pass B's exitstatus is
  RECORDED AND NOT GATED; its determinism is what matters, and that is verified by re-running (two
  runs at HEAD produced the same forced sha).

XCCY IS EXCLUDED FROM BOTH BANKS BY CONSTRUCTION. A request that already carries `xccy` is passed
through UNTOUCHED and then DROPPED (its key is listed in `excluded_xccy_keys`). The cross-currency
path is the one path V2-3 is allowed to change; a golden that banked it would be a golden that had
to be re-banked, which is not a gate.

THE ONE ERASED FIELD. `payload['deep']['elapsed_ms']` is a wall clock -- no two runs agree on it, and
cascade.py says so at the stamp. It is replaced by a KIND TOKEN ("__INT_MS__" / "__NONE__"), never
popped: a build that stopped stamping it, or started stamping None, is a real change and this bank
must be able to name it.

HOW THE GATE USES IT. After the V2-3 build, re-run this script. Every banked (nodeid, ordinal) in
BOTH banks must reproduce lines / payload / calls_delta / the ORDER of payload['declines'] exactly.
The pin is
tests/unit/test_cascade_walk.py::test_g1d_the_deep_on_xccy_off_population_reproduces_the_banked_deep_golden.
A diff is not automatically a regression -- law L9 deliberately ADDS
payload['deep']['order_n_rendered'] to this regime -- but a diff must be NAMED, measured, and the
bank re-anchored on that measurement, never waved through. The pin prints the drifted (key, field)
pairs so the re-anchor has evidence to stand on.

RECURSION IS CLOSED BY THE V2-5 SENTINEL, reused verbatim: this script exports V25_GOLDEN_INNER=1
into both pytest subprocesses, and BOTH golden pins skip under it.

COST: two full runs of the cascade-walk suite, ~2 minutes each, $0, offline, no model calls, no AWS.
Re-runnable: `python data/consequence_leg/v23_golden_deep_bank.py`.
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
BANK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v23_golden_deep_on.json")
# The V2-5 recursion sentinel, REUSED (law L10: "the V25_GOLDEN_INNER sentinel idiom"). One name for
# one fact -- "this pytest process is a golden producer's own subprocess" -- read by both pins.
INNER_ENV = "V25_GOLDEN_INNER"

PLUGIN = r'''
import copy, functools, json, os
from leviathan.graphrag.numbers import cascade as cq

_OUT = os.environ["V23_GOLDEN_OUT"]
_FORCE = os.environ.get("V23_GOLDEN_FORCE") == "1"     # pass B; pass A perturbs nothing
_REC = []
_CUR = {"nodeid": None, "n": 0}
_ORIG = cq._cascade_walk_leg_or_nothing     # THE OUTER FUNCTION (V2-5 refute-v4 fatal 1)


def _safe(o):
    """JSON-safe, ORDER-PRESERVING. Sets are sorted (unordered by construction); every other
    container keeps its own order, which is the thing under test."""
    if isinstance(o, dict):
        return {str(k): _safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_safe(v) for v in o]
    if isinstance(o, (set, frozenset)):
        return {"__set__": sorted(_safe(v) for v in o)}
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    return {"__repr__": repr(o)}


def _erase_clock(safe_payload):
    """The ONE nondeterministic field, erased to a KIND TOKEN -- never popped, so a build that
    stopped stamping it (or started stamping None) still shows up as a diff."""
    if isinstance(safe_payload, dict) and isinstance(safe_payload.get("deep"), dict):
        d = safe_payload["deep"]
        if "elapsed_ms" in d:
            v = d["elapsed_ms"]
            if v is None:
                d["elapsed_ms"] = "__NONE__"
            elif isinstance(v, bool):
                d["elapsed_ms"] = "__BOOL__"
            elif isinstance(v, int):
                d["elapsed_ms"] = "__INT_MS__"
            elif isinstance(v, float):
                d["elapsed_ms"] = "__FLOAT_MS__"
            else:
                d["elapsed_ms"] = "__OTHER__"
    return safe_payload


@functools.wraps(_ORIG)                       # sets __wrapped__, so any inspect.getsource pin
def _wrapped(sg, graph, walk_request, qfn, asof, calls, **kw):    # still reads the REAL function
    req, forced, xccy = walk_request, False, False
    if isinstance(walk_request, dict):
        xccy = bool(walk_request.get("xccy"))
        if _FORCE and not xccy and not walk_request.get("deep"):
            req = dict(walk_request)          # a COPY: the fixture's own dict is never mutated
            req["deep"] = True                # THE FORCING -- the regime prod takes under the flag
            forced = True
    _n0 = len(calls)
    try:
        lines, payload = _ORIG(sg, graph, req, qfn, asof, calls, **kw)
    except Exception as e:                    # the belt does not propagate; a raise HERE is itself
        _REC.append({"nodeid": _CUR["nodeid"], "ordinal": _CUR["n"],   # the regression to name
                     "request": _safe(req), "asof": _safe(asof), "base": _n0,
                     "forced": forced, "xccy": xccy, "raised": repr(e),
                     "lines": None, "payload": None, "calls_delta": None,
                     "traced_is_payload": None})
        _CUR["n"] += 1
        raise
    try:                                      # the ONE registered trace key, as the turn sees it
        _traced = (sg.trace.get("quantify_cascade_walk") is payload)
    except Exception:                         # noqa: BLE001 -- a traceless sg is a banked state too
        _traced = None
    _REC.append({"nodeid": _CUR["nodeid"], "ordinal": _CUR["n"],
                 "request": _safe(req), "asof": _safe(asof), "base": _n0,
                 "forced": forced, "xccy": xccy, "raised": None,
                 "traced_is_payload": _traced,
                 "lines": _safe(copy.deepcopy(lines)),
                 "payload": _erase_clock(_safe(copy.deepcopy(payload))),
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


def _run_pass(force: bool) -> dict:
    """One pytest run under the recording plugin. `force` selects pass B."""
    raw = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    raw.close()
    plug = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8")
    plug.write(PLUGIN)
    plug.close()
    env = dict(os.environ, V23_GOLDEN_OUT=raw.name, V23_GOLDEN_FORCE=("1" if force else "0"),
               PYTHONPATH=os.path.join(REPO, "src"))
    env[INNER_ENV] = "1"                      # both golden pins skip inside this run -- no recursion
    for k in list(env):
        if k.startswith("GRAPHRAG_"):
            env.pop(k)                        # a golden must not carry the runner's env; the regime
            #                                   comes from the REQUEST KEY, which is where the engine
            #                                   reads it (the seam owns the env, never cascade.py)
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
           "-p", os.path.splitext(os.path.basename(plug.name))[0]] + SUITES
    env["PYTHONPATH"] = os.pathsep.join([os.path.dirname(plug.name), env["PYTHONPATH"]])
    proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True)
    tail = (proc.stdout or "")[-3000:] + (proc.stderr or "")[-2000:]
    with open(raw.name, encoding="utf-8") as fh:
        cap = json.load(fh)
    os.unlink(raw.name)
    os.unlink(plug.name)
    return {"exitstatus": cap["exitstatus"], "records": cap["records"], "tail": tail}


def _fold(records: list, force: bool) -> tuple:
    """Records -> (bank, excluded_xccy_keys). PASS A keeps only the calls whose OWN fixture asked
    for deep; PASS B keeps every non-xccy call (all of which are deep by construction)."""
    bank, excluded = {}, []
    for r in records:
        key = "%s#%d" % (r["nodeid"], r["ordinal"])
        if r["xccy"]:                         # the one path V2-3 is allowed to change
            excluded.append(key)
            continue
        if not force and not (r["request"] or {}).get("deep"):
            continue                          # pass A: off-regime calls are G1's business, not this
        bank[key] = {
            "request": r["request"], "asof": r["asof"], "raised": r["raised"],
            "forced": r["forced"], "traced_is_payload": r["traced_is_payload"],
            "lines": r["lines"], "payload": r["payload"], "calls_delta": r["calls_delta"]}
    return bank, excluded


def _sha(bank: dict) -> str:
    return hashlib.sha256(json.dumps(bank, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def main() -> int:
    # A BARE RE-RUN NEVER OVERWRITES THE BANK (the V2-5 producer's law, kept): `BANK` is the
    # baseline every later run is judged against; re-banking it is a deliberate act, taken with a
    # measurement in hand, never a side effect of running this producer.
    out = (os.environ.get("V23_GOLDEN_OUT")
           or os.path.join(os.path.dirname(BANK), "v23_golden_deep_rerun.json"))
    a = _run_pass(force=False)
    b = _run_pass(force=True)
    bank_a, excl_a = _fold(a["records"], force=False)
    bank_b, excl_b = _fold(b["records"], force=True)
    sha_a, sha_b = _sha(bank_a), _sha(bank_b)
    doc = {
        "what": ("V2-3 DEEP-ON / XCCY-OFF GOLDEN -- the OUTER _cascade_walk_leg_or_nothing under the "
                 "deep regime, twice: NATIVE (the fixtures' own deep calls, green run) and FORCED "
                 "(every non-xccy call re-asked with deep=True). xccy requests excluded from both; "
                 "elapsed_ms erased to a kind token."),
        "suites": SUITES,
        "native": {"pytest_exitstatus": a["exitstatus"], "pytest_tail": a["tail"],
                   "n_calls": len(a["records"]), "n_keys": len(bank_a),
                   "excluded_xccy_keys": excl_a, "bank_sha256": sha_a},
        "forced": {"pytest_exitstatus": b["exitstatus"], "pytest_tail": b["tail"],
                   "n_calls": len(b["records"]), "n_keys": len(bank_b),
                   "n_forced": sum(1 for v in bank_b.values() if v["forced"]),
                   "n_native_deep": sum(1 for v in bank_b.values() if not v["forced"]),
                   "excluded_xccy_keys": excl_b, "bank_sha256": sha_b},
        "gates": {
            "native_pass_must_be_green": True,
            "forced_pass_exitstatus_is_recorded_not_gated": True,
            "how": ("re-run this script on the V2-3 tree; every banked key in BOTH banks must "
                    "reproduce lines/payload/calls_delta exactly, and any diff must be named and "
                    "the bank re-anchored on that measurement (law L9 adds "
                    "payload['deep']['order_n_rendered'] to this regime on purpose)")},
        "bank_native": bank_a,
        "bank_forced": bank_b,
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=False)
    print("wrote %s" % out)
    print("  native: calls=%d keys=%d xccy_excluded=%d exit=%s sha256=%s"
          % (len(a["records"]), len(bank_a), len(excl_a), a["exitstatus"], sha_a))
    print("  forced: calls=%d keys=%d (forced=%d native=%d) xccy_excluded=%d exit=%s sha256=%s"
          % (len(b["records"]), len(bank_b), doc["forced"]["n_forced"],
             doc["forced"]["n_native_deep"], len(excl_b), b["exitstatus"], sha_b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
