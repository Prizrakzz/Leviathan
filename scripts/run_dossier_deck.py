"""D-DR-4 dossier arm runner: execute every row of a dossier deck through dossier.execute and
persist a pseudo-baseline JSON the pairwise judge can read.

Runs INSIDE the eval Batch image (full serving env: pg evidence, Anthropic key, S3). Each deck
row becomes one dossier run (inline, thread=False -- sequential by construction, which is also
the Cohere-quota discipline). The output mirrors the eval baseline shape: per_answer rows carry
the composed body under raw_draft.body_pre_sanitize (the pairwise judge's exact-body rung) plus
the dossier record (plan, sub-query trace, citations) for the deterministic D-DR-4 gates:

  - spine gate: every [E*]/[N*] handle rendered in the body must resolve in the carried pairs
    (computed HERE, deterministically -- never re-discovered by an LLM);
  - strip profile: the synthesis verifier's counts ride the row.

Usage (Batch command):
    python scripts/run_dossier_deck.py --queries /tmp/dossier_v1.yaml \
        --out-s3 s3://<bucket>/graphrag_evidence/eval/baseline_dossier_v1_dossier_<ts>.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time

import yaml

_HANDLE = re.compile(r"\[(?:E|N)\d+\]")


def _mem_store():
    """The in-memory store impl, whatever its class name is (Protocol impls live in store.py)."""
    from leviathan.graphrag import store as st
    for name in dir(st):
        obj = getattr(st, name)
        if isinstance(obj, type) and "memory" in name.lower() and hasattr(obj, "put_item"):
            return obj()
    raise SystemExit("no in-memory store class found in graphrag.store")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", required=True)
    ap.add_argument("--out-s3", required=True)
    args = ap.parse_args()

    from leviathan.common import config
    config.load_env()
    from leviathan.graphrag import dossier
    from leviathan.graphrag import graph as gph

    graph = gph.CausalGraph.load()
    store = _mem_store()

    captured: dict[str, dict] = {}
    orig_land = dossier.land_artifact

    def land_and_capture(store_, job, payload):
        captured[job.id] = payload
        return orig_land(store_, job, payload)

    dossier.land_artifact = land_and_capture

    # Dual-synthesis capture: the sub-queries are the expensive leg (~$1/dossier); the synthesis
    # is one call. Capturing (plan, notes, union) at the primary synthesize lets a SECOND model
    # compose from the IDENTICAL inputs -- a perfectly controlled synthesis-model A/B for the
    # price of one extra call per dossier, with zero rerank contention (one job, sequential).
    synth_inputs: dict[str, tuple] = {}
    orig_synth = dossier.synthesize

    def synth_and_capture(question, asof, plan_data, notes, union, **kw):
        out = orig_synth(question, asof, plan_data, notes, union, **kw)
        synth_inputs[question] = (asof, plan_data, notes, union)
        return out

    dossier.synthesize = synth_and_capture
    ALT_MODEL = "claude-opus-5"

    deck = yaml.safe_load(open(args.queries, encoding="utf-8"))
    rows = deck["queries"] if isinstance(deck, dict) else deck
    per_answer = []
    for q in rows:
        t0 = time.monotonic()
        job = dossier.start(store, {"sub": "eval-lane"}, q["question"], q.get("asof"),
                            graph=graph, thread=False)
        payload = captured.get(job.id) or {}
        body = payload.get("answer") or ""
        pairs = {p.get("handle") for p in (payload.get("citations") or [])}
        rendered = set(_HANDLE.findall(body))
        cv = payload.get("citation_verifier") or {}
        per_answer.append({
            "id": q["id"], "intent": "dossier", "judge": None,
            "status": job.status, "error": job.error,
            "secs": round(time.monotonic() - t0, 1),
            "strips": cv.get("stripped") or 0,
            "handles_checked": cv.get("checked") or 0,
            "claim_count": cv.get("claim_count") or 0,
            "by_rule": cv.get("by_rule") or {},
            # spine gate, deterministic: rendered handles that resolve in NO carried pair
            "spine_violations": sorted(h for h in rendered if h.strip("[]") not in
                                       {str(x).strip("[]") for x in pairs if x}),
            "raw_draft": {**(payload.get("structured") or {}), "body_pre_sanitize": body},
            "dossier": {k: payload.get(k) for k in
                        ("dossier_id", "title", "status", "plan", "sections", "citations",
                         "subquery_trace", "composition_census", "usage")},
        })
        print(f"[dossier] {q['id']}: {job.status} strips={cv.get('stripped')} "
              f"spine_viol={len(per_answer[-1]['spine_violations'])} "
              f"secs={per_answer[-1]['secs']}", flush=True)

        # Second composition from the IDENTICAL notes/union -- the controlled opus-5 arm.
        cap = synth_inputs.get(q["question"])
        if cap and job.status in ("done", "partial"):
            asof2, plan2, notes2, union2 = cap
            t1 = time.monotonic()
            try:
                synth2 = orig_synth(q["question"], asof2, plan2, notes2, union2, model=ALT_MODEL)
                body2 = synth2.get("body") or ""
                cv2 = synth2.get("verifier") or {}
                pairs2 = {str(p.get("handle")).strip("[]") for p in (union2.get("pairs") or [])}
                rendered2 = set(_HANDLE.findall(body2))
                per_answer.append({
                    "id": q["id"] + "__opus5", "intent": "dossier", "judge": None,
                    "status": job.status, "error": None, "synth_model": ALT_MODEL,
                    "secs": round(time.monotonic() - t1, 1),
                    "strips": cv2.get("stripped") or 0,
                    "handles_checked": cv2.get("checked") or 0,
                    "claim_count": cv2.get("claim_count") or 0,
                    "by_rule": cv2.get("by_rule") or {},
                    "spine_violations": sorted(h for h in rendered2
                                               if h.strip("[]") not in pairs2),
                    "raw_draft": {**(synth2.get("structured") or {}),
                                  "body_pre_sanitize": body2},
                    "dossier": {"dossier_id": (captured.get(job.id) or {}).get("dossier_id"),
                                "usage": synth2.get("usage")},
                })
                print(f"[dossier] {q['id']}__opus5: composed strips={cv2.get('stripped')} "
                      f"secs={per_answer[-1]['secs']}", flush=True)
            except (Exception, SystemExit) as e:  # noqa: BLE001 -- the alt arm must never kill the run
                print(f"[dossier] {q['id']}__opus5: FAILED {type(e).__name__}: "
                      f"{str(e)[:150]}", flush=True)

    out = {"kind": "baseline_single", "eval_set": "dossier_v1", "mode": "dossier",
           "judged": False, "model": "dossier-orchestration",
           "provider": "anthropic",
           "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
           "per_answer": per_answer}
    try:
        from leviathan.graphrag.eval import _baseline_git_commit
        out["git_commit"] = _baseline_git_commit()
    except Exception:  # noqa: BLE001 -- the stamp is best-effort outside a git checkout
        pass

    body = json.dumps(out, default=str).encode("utf-8")
    import boto3
    m = re.match(r"s3://([^/]+)/(.+)", args.out_s3)
    boto3.client("s3").put_object(Bucket=m.group(1), Key=m.group(2), Body=body)
    print(f"wrote {args.out_s3} ({len(body)} bytes); "
          f"done={sum(1 for r in per_answer if r['status'] == 'done')}/"
          f"{len(per_answer)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
