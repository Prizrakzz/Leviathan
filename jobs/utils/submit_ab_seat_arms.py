"""The (A)-batch item (iv) MODEL-SEAT A/Bs — cloud submitter for the two arms (2026-08-21).

THE PAIR (freeze-block seat map, code-verified):
  arm (a) numbers agent  claude-haiku-4-5 -> claude-sonnet-5   (agent.py:2283 `model: str = HAIKU`;
          NO env override exists — the seat is unreachable from the eval CLI, so the arm rides an
          in-process shim wrapping na.answer_numbers)
  arm (b) dispatch       claude-sonnet-4-6 -> claude-sonnet-5  (dispatch.py:658 reads
          GRAPHRAG_DISPATCH_MODEL — but the env var ALONE is a NULL ARM: `_temp_kw` pins
          temperature=0, Sonnet 5 400s on temperature (probed 2026-08-21: "`temperature` is
          deprecated for this model"), dispatch.py:678 swallows the error into _FALLBACK and the
          run silently measures the LEGACY LEXICAL CLASSIFIER. The shim patches _temp_kw to {} —
          a DECLARED D18 deviation (Sonnet 5 has no sampling surface, so temperature-0 dispatch is
          unrepresentable) — and wraps plan_turn with a fallback counter so a broken arm is LOUD.)

BOTH probes run 2026-08-21 (~$0.01): temperature=0 400s; forced-tool without temperature PASSES;
thinking={"type":"disabled"} PASSES. Arm (a) forces thinking disabled on the numbers lane only
(matches Haiku's no-thinking behaviour = single-variable; leaves the 1,500-token budget real;
scoped via a client proxy so the frozen claude-opus-4-8 judge on the SHARED eval client is
untouched).

CONTROL: one plain submit_eval run of the same deck serves BOTH arms (the D-AM paired-baseline
economics). The arms' argv MATCHES the control's container command byte-for-byte; the only
variable is the shim. All three runs: jobdef leviathan-dev-evidence-build:81 (wave-close image
c9b341ca), queue ondemand, 8 vCPU/32 GiB, env {GRAPHRAG_REROUTE_V2=on, GRAPHRAG_NUMBERS_BACKEND=pg}
(+ GRAPHRAG_DISPATCH_MODEL on arm b). Run the three SEQUENTIALLY — never in parallel.

    python jobs/utils/submit_ab_seat_arms.py --control [--dry-run]
    python jobs/utils/submit_ab_seat_arms.py --arm a   [--dry-run]
    python jobs/utils/submit_ab_seat_arms.py --arm b   [--dry-run]

ARM IDENTITY: the baseline artifacts all stamp model=claude-sonnet-4-6 (the synth seat) and a
clean git sha — the ONLY distinguisher is the ts. This submitter writes data/batch_runs/
ab_seat_<arm>_<ts>.json as the out-of-band ts->arm map; do not lose it.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import boto3

from leviathan.common.config import get_required_env, load_env

_DECK = "configs/graphrag/eval_queries_newcap30.yaml"
_ARGV = ["eval", "--run", "--model", "claude-sonnet-4-6", "--k", "5", "--queries", _DECK,
         "--via-orchestrator", "--judge", "--judge-model", "claude-opus-4-8"]
_JOBDEF = "leviathan-dev-evidence-build:81"            # pinned: the wave-close image c9b341ca
_QUEUE = "leviathan-dev-queue-ondemand"
_ENV = {"GRAPHRAG_REROUTE_V2": "on", "GRAPHRAG_NUMBERS_BACKEND": "pg"}

_SHIM_A = f"""
import sys, functools
sys.argv = {_ARGV!r}
AB_MODEL = "claude-sonnet-5"
class _MsgProxy:
    def __init__(self, inner, extra): self._i, self._x = inner, extra
    def create(self, **kw):
        kw.update(self._x); return self._i.create(**kw)
class _ClientProxy:
    def __init__(self, inner, extra):
        object.__setattr__(self, "_i", inner)
        object.__setattr__(self, "messages", _MsgProxy(inner.messages, extra))
    def __getattr__(self, n): return getattr(self._i, n)
from leviathan.graphrag.numbers import agent as na
_orig = na.answer_numbers
@functools.wraps(_orig)
def _patched(question, asof, **kw):
    kw["model"] = AB_MODEL
    c = kw.get("client")
    if c is not None:
        kw["client"] = _ClientProxy(c, {{"thinking": {{"type": "disabled"}}}})
    return _orig(question, asof, **kw)
na.answer_numbers = _patched
print("AB SHIM ARM-A: numbers seat -> " + AB_MODEL + ", thinking disabled, max_tokens 1500 (unchanged)", flush=True)
from leviathan.graphrag import eval as gev
raise SystemExit(gev.main())
"""

_SHIM_B = f"""
import sys, os
sys.argv = {_ARGV!r}
assert os.environ.get("GRAPHRAG_DISPATCH_MODEL") == "claude-sonnet-5", "arm-b env var missing"
assert os.environ.get("GRAPHRAG_DISPATCH", "llm") != "rules", "dispatch disabled -- arm void"
from leviathan.graphrag import dispatch as dsp
dsp._temp_kw = lambda call: {{}}      # DECLARED D18 DEVIATION: sonnet-5 has NO sampling surface
_pt = dsp.plan_turn
_n = {{"plans": 0, "fallbacks": 0}}
def _counted(*a, **k):
    p = _pt(*a, **k); _n["plans"] += 1
    if p.fallback:
        _n["fallbacks"] += 1
        print("!! DISPATCH FALLBACK " + str(_n["fallbacks"]) + "/" + str(_n["plans"])
              + " -- ARM INVALID IF THIS PERSISTS", flush=True)
    else:
        print("dispatch plan " + str(_n["plans"]) + " ok", flush=True)
    return p
dsp.plan_turn = _counted
print("AB SHIM ARM-B: dispatch seat -> claude-sonnet-5, temperature UNPINNED, fallbacks counted", flush=True)
from leviathan.graphrag import eval as gev
raise SystemExit(gev.main())
"""


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="Submit the model-seat A/B control or an arm (SEQUENTIAL, never parallel)")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--control", action="store_true")
    grp.add_argument("--arm", choices=["a", "b"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.control:
        raise SystemExit("submit the control through the standard wrapper so its run record and env match "
                         "the estate convention:\n  python jobs/submit/submit_eval.py --queries " + _DECK +
                         " --judge --via-orchestrator --env GRAPHRAG_NUMBERS_BACKEND=pg "
                         "--queue " + _QUEUE)

    arm = args.arm
    code = _SHIM_A if arm == "a" else _SHIM_B
    env = dict(_ENV)
    if arm == "b":
        env["GRAPHRAG_DISPATCH_MODEL"] = "claude-sonnet-5"
    overrides = {
        "command": ["-c", code],
        "resourceRequirements": [{"type": "VCPU", "value": "8"}, {"type": "MEMORY", "value": "32768"}],
        "environment": [{"name": k, "value": v} for k, v in sorted(env.items())],
    }
    name = f"ab-seat-arm-{arm}-newcap30"
    print(f"jobdef={_JOBDEF} queue={_QUEUE} env={env}")
    print(f"command: python -c <shim-{arm}, {len(code)} chars> ; argv inside: {' '.join(_ARGV)}")
    if args.dry_run:
        print(f"[DRY RUN] would submit {name}")
        return
    client = boto3.client("batch", region_name=get_required_env("AWS_REGION"))
    resp = client.submit_job(jobName=name, jobQueue=_QUEUE, jobDefinition=_JOBDEF,
                             containerOverrides=overrides)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    rec = {"arm": arm, "job_id": resp["jobId"], "job_name": name, "jobdef": _JOBDEF,
           "deck": _DECK, "env": env, "submitted_utc": ts,
           "seat": ("numbers agent.py:2283 haiku-4-5 -> sonnet-5, thinking disabled" if arm == "a"
                    else "dispatch.py:658 sonnet-4-6 -> sonnet-5 via env, _temp_kw patched (D18 deviation)")}
    out = Path("data/batch_runs") / f"ab_seat_arm_{arm}_{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    print(f"Submitted {name}  job_id={resp['jobId']}  [record: {out}]")


if __name__ == "__main__":
    main()
