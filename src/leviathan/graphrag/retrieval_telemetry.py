"""Retrieval telemetry (Phase 7 P3 / W1.4) — the COUNT-ONLY runtime signal that closes the
`routed + consumed` cell of the prevention doctrine (P3 plan L79): "in a slice a DAG id reaches;
retrieved when relevant -> watched by retrieval telemetry".

The stranding forensics had no way to tell a slice that is wired-but-never-retrieved (an E1b build
target that IS reachable) apart from one that is structurally unreachable (dead corpus nothing routes
to). The census (`e1_census`) answers reachability STATICALLY; this module adds the RUNTIME half — which
reachable slices actually surface evidence when queries fire — so the join classifies every slice into
{unreachable | reachable-never-asked | used}.

PIT FIREWALL — this module is count-only by CONSTRUCTION. `record()` reads exactly three scalar fields
off each driver leg — the slice PATH, the `dark` flag, and whether `n_evidence > 0` — and NEVER the
evidence text, the prop dates, the sources, or any other content. The in-memory counter is a
`{slice -> {legs, retrieved, dark}}` map of PLAIN INTS; the flushed JSON carries only those ints. There
is no code path by which a proposition string reaches durable storage from here (the `test_pit_*` tests
pin this). This is the same firewall the answer trace already respects (the trace is never persisted);
telemetry is the ONE aggregate that leaves the process, and it leaves as counts.

HOT-PATH DISCIPLINE — `record()` is called once per reasoning/hybrid turn from `planner.ground()` and is a
pure in-memory increment under a lock: no I/O, no S3, no LIST (the July $134 LIST-storm rule). Durable
emission is a SEPARATE, periodic `flush()` — it writes ONE count-only object to
`<EVIDENCE_S3>/eval/retrieval_counts/<UTC>.json` (plus a local mirror) and is a no-op when EVIDENCE_S3 is
unset (local dev keeps counts in memory only; the sink is S3 by decision D7).

Numbers-only turns never reach `ground()` (they route through the numbers agent, which builds no
driver legs), so recording every leg here is already reasoning/hybrid-only — no explicit intent gate is
needed, mirroring E0's numbers-exclusion by construction.

    from leviathan.graphrag import retrieval_telemetry as rt
    rt.record(sg.trace["driver_legs"])     # per-turn, in-memory (planner.ground hook)
    rt.flush()                             # periodic, -> S3 eval/retrieval_counts/<UTC>.json
    rt.triage(rt.snapshot(), census_doc)   # join with e1_census.json -> per-slice state
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex

_OUT = ex._CFG / "eval"                                    # local mirror root (configs/graphrag/eval/), census precedent
_DRIVERS_PREFIX = "drivers/"                               # driver-leg slice paths carry it; census keys do not

# In-process counter: slice-name (census-canonical, i.e. WITHOUT the drivers/ prefix) -> {legs, retrieved,
# dark}, all ints. Guarded by a lock because serving answers turns concurrently (FastAPI) even though each
# record() call is a single main-thread increment after the parallel fill has joined.
_LOCK = threading.Lock()
_COUNTS: dict[str, dict[str, int]] = {}

# The three count fields kept per slice (order = the flushed/rolled-up column order):
#   legs      -- times this slice appeared as a driver leg (denominator for a retrieval rate)
#   retrieved -- times the leg carried dated evidence (n_evidence > 0) -> the slice was USED
#   dark      -- times the leg was dark (unbacked id or no slice file) -> reached but not grounded
_FIELDS = ("legs", "retrieved", "dark")

# Triage buckets (P3 plan L135): the census x counts join classification.
STATE_USED = "used"                                        # retrieved >= 1 in the window
STATE_NEVER = "reachable-never-asked"                      # a DAG id routes here, but no evidence surfaced
STATE_UNREACHABLE = "unreachable"                          # nothing routes here (dead corpus / inert spec)


# ── record: the in-memory, count-only, hot-path increment ─────────────────────────────────────────────
def record(driver_legs) -> None:
    """Fold one turn's `driver_legs` (the planner trace list) into the in-memory per-slice counter.

    Reads ONLY {slice, dark, n_evidence} off each leg — never text (the PIT firewall). Legs with no slice
    (slice is None: an unbacked id or no slice file in serving) have no per-slice key to increment; they
    are the dark-at-birth tally's business (W1.2), not this counter's, so they are skipped here. A dark
    leg WITH a slice (the hermetic-test shape, where the id IS its slice path) still increments `legs` and
    `dark`. Never raises: callers guard it too, but a telemetry bug must never perturb an answer."""
    if not driver_legs:
        return
    with _LOCK:
        for leg in driver_legs:
            slice_ = leg.get("slice")
            if not slice_:
                continue
            key = slice_[len(_DRIVERS_PREFIX):] if slice_.startswith(_DRIVERS_PREFIX) else slice_
            c = _COUNTS.get(key)
            if c is None:
                c = _COUNTS[key] = {"legs": 0, "retrieved": 0, "dark": 0}
            c["legs"] += 1
            if leg.get("dark"):
                c["dark"] += 1
            if (leg.get("n_evidence") or 0) > 0:                   # dark legs never fetch -> n_evidence 0, so
                c["retrieved"] += 1                                # retrieved and dark are mutually exclusive
    # NB: no return of the counter — snapshot() is the only read accessor (keeps callers from mutating it).


def snapshot() -> dict[str, dict[str, int]]:
    """A deep copy of the current per-slice counter (safe to serialize / pass to triage while record()
    keeps running). Values are plain-int dicts; there are no text fields to leak."""
    with _LOCK:
        return {k: dict(v) for k, v in _COUNTS.items()}


def reset() -> None:
    """Clear the in-memory counter (called after a successful flush; also the test-isolation hook)."""
    with _LOCK:
        _COUNTS.clear()


# ── flush: the periodic, count-only durable emission (S3 sink, D7) ────────────────────────────────────
def _doc(counts: dict[str, dict[str, int]], generated_utc: str) -> dict:
    """The count-only flush artifact. `totals` rolls the per-slice ints; there is NO evidence field by
    construction (the PIT firewall). Kept a pure function of (counts, timestamp) so it is trivially
    testable and so the S3 body and the local mirror are byte-identical."""
    totals = {f: 0 for f in _FIELDS}
    for c in counts.values():
        for f in _FIELDS:
            totals[f] += int(c.get(f, 0))
    return {"kind": "retrieval_counts", "generated_utc": generated_utc,
            "n_slices": len(counts), "totals": totals, "counts": counts}


def flush(*, now: Optional[datetime] = None) -> Optional[Path]:
    """Snapshot the counter and write ONE count-only JSON to `<EVIDENCE_S3>/eval/retrieval_counts/<UTC>.json`
    plus a local mirror under configs/graphrag/eval/retrieval_counts/, then reset the counter so windows
    are independent. NO-OP (returns None, keeps the counter) when EVIDENCE_S3 is unset or the counter is
    empty — the sink is S3 by decision D7; local dev never accumulates a disk trail. Returns the local
    mirror path on a successful flush. `now` is injectable for a deterministic filename in tests."""
    s3uri = ev._evid_s3()
    if not s3uri:
        return None                                        # sink is S3; no EVIDENCE_S3 -> keep counts in memory
    counts = snapshot()
    if not counts:
        return None                                        # nothing to emit; don't spam empty artifacts
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")                 # filename-safe UTC; the ISO form rides inside the doc
    body = json.dumps(_doc(counts, now.isoformat()), indent=2)

    local = _OUT / "retrieval_counts" / f"{stamp}.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(body, encoding="utf-8")

    import boto3
    b, k = ev._parse_s3(s3uri.rstrip("/") + f"/eval/retrieval_counts/{stamp}.json")
    boto3.client("s3").put_object(Bucket=b, Key=k, Body=body.encode("utf-8"))
    print(f"  retrieval_counts -> s3://{b}/{k} ({_doc(counts, '')['n_slices']} slices)")   # ASCII-only stdout
    reset()
    return local


# ── reporter: the census x counts triage ──────────────────────────────────────────────────────────────
def triage(counts: dict[str, dict[str, int]], census: dict) -> dict:
    """Join the per-slice counts with an e1_census doc (its `slices` block) and classify each slice:

      used                  -- retrieved >= 1 in the counts (the slice actually surfaced dated evidence)
      reachable-never-asked -- a DAG id routes here (census n_dag_ids >= 1) but retrieved == 0 (a keep-
                               orphan / thin CONSUMED slice the E4 top-up should prioritise; the W0 sizing
                               report's 'wired but inert' set lives here)
      unreachable           -- nothing routes here (n_dag_ids == 0): a retire-orphan (props, no consumer)
                               or an inert spec — no query can reach it, so counts never matter

    `counts` is the snapshot()/flush-doc `counts` mapping (slice -> int fields). The universe is the UNION
    of census slice names and counter keys, so a counter key the census does not know (retrieved -> used,
    else unreachable) is still classified rather than dropped. Pure + hermetic: no I/O."""
    cmeta = {s["slice"]: s for s in census.get("slices", [])}
    out: list[dict] = []
    for name in sorted(set(cmeta) | set(counts)):
        c = counts.get(name, {})
        legs = int(c.get("legs", 0))
        retrieved = int(c.get("retrieved", 0))
        dark = int(c.get("dark", 0))
        meta = cmeta.get(name)
        n_ids = int(meta["n_dag_ids"]) if meta else 0
        n_props = int(meta["n_routed_props"]) if meta else 0
        if retrieved > 0:
            state = STATE_USED
        elif n_ids >= 1:
            state = STATE_NEVER
        else:
            state = STATE_UNREACHABLE
        out.append({"slice": name, "state": state, "n_dag_ids": n_ids, "n_routed_props": n_props,
                    "legs": legs, "retrieved": retrieved, "dark": dark})
    by_state: dict[str, int] = {}
    for r in out:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    return {"kind": "retrieval_triage", "by_state": by_state, "slices": out}
