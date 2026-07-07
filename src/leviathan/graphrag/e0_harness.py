"""E0/E3 sparsity-attribution harness (Phase 7 P0.2).

Buckets every SPARSE production answer (a persisted turn that cited zero dated documents) into the
cause its evidence starved on:

  dark_routing     -- the routed contract has driver legs the planner drops as prior-only (unbacked
                      dag id = alias-map gap, or no slice file) — the planner._fill predicate. FREE
                      to fix (E1 alias/terms + reroute).
  unchunked_doc    -- corpus docs covering the routed contract were never chunked into the evidence
                      store (the E4 heavy-pass target).
  genuine_absence  -- routing + chunk coverage exist; there is simply no dated evidence to cite.

STATIC-FIRST + ZERO-LLM: classification is a pure function of the DAG + driver_slices.yaml alias map
+ the chunks/ doc cache, at CONTRACT granularity (the walked-subset view comes from the instrumented
`trace.driver_legs` when a turn is re-answered — the optional sampled re-run lane, Bedrock-billed).
Run E0 BEFORE any E1 change (the before-snapshot); re-run after E1 and after E4 — the deltas are the
per-fix attribution (adversarial-teardown CRITICAL #2: measure before you erase the signal).

Honesty label: stored turns pin their own graph_version; a driver dark TODAY may not have been dark
when the turn ran. The snapshot is labeled `as_of_current_config` and mismatched turns are flagged,
never silently mixed.

The Store abstraction can only Query a KNOWN user pk — enumerating every persisted turn needs the raw
paginated DynamoDB Scan below (the one capability the PIT-firewalled store deliberately lacks).

    python -m leviathan.graphrag.e0_harness --dry-run          # static-only, zero model calls, $0
"""
from __future__ import annotations

import json
import os

KEEP_INTENTS = ("reasoning", "hybrid", "live")     # numbers_only/refused legitimately cite no documents


# ── turn enumeration (raw Scan — the store has no cross-user query) ─────────────────────────────────
def enumerate_turns(db, table: str) -> list[dict]:
    """Every persisted turn across all users: paginated Scan filtered to sk beginswith 'turn#'.
    Returns the sanitized turn dicts (+ _user/_sk) — evidence/trace were never persisted (PIT firewall),
    which is exactly why attribution must re-derive instead of reading the store."""
    out: list[dict] = []
    kw = dict(TableName=table, FilterExpression="begins_with(sk, :t)",
              ExpressionAttributeValues={":t": {"S": "turn#"}})
    while True:
        page = db.scan(**kw)
        for it in page.get("Items") or []:
            try:
                body = json.loads(it["body"]["S"])
            except Exception:  # noqa: BLE001 — a malformed item must not kill the sweep
                continue
            body["_user"] = str(it.get("pk", {}).get("S", ""))[len("user#"):]
            body["_sk"] = it.get("sk", {}).get("S", "")
            out.append(body)
        lek = page.get("LastEvaluatedKey")
        if not lek:
            return out
        kw["ExclusiveStartKey"] = lek


def keep(turn: dict) -> bool:
    """Reasoning-class turns only: numbers_only returns evidence:[] by construction and `refused`
    never retrieves — their zero-source records are expected, not sparsity."""
    return (turn.get("intent") or "") in KEEP_INTENTS


def evidence_source_count(turn: dict) -> int:
    """Cited DOCUMENT sources only. A hybrid turn whose citations are all numbers-kind has zero
    document receipts but is not evidence-sparse in the numbers dimension — count by kind (a missing
    kind is treated as evidence: old records predate the kind field)."""
    return sum(1 for s in (turn.get("sources") or []) if (s or {}).get("kind", "evidence") == "evidence")


def is_sparse(turn: dict) -> bool:
    return evidence_source_count(turn) == 0


# ── static classification (pure function of current configs) ────────────────────────────────────────
def dark_legs(contract: str, graph, *, backed: set, slice_for) -> list[dict]:
    """Every driver leg of `contract` the planner would drop as prior-only, with the sub-condition:
    `unbacked_id` (alias-map gap) vs `no_slice` — they have different E1 fixes (planner.py _fill)."""
    c = graph.contracts.get(contract)
    if c is None:
        return []
    legs = []
    for d in c.drivers:
        unbacked = d.id not in backed
        no_slice = slice_for(d.id) is None
        if unbacked or no_slice:
            legs.append({"id": d.id, "reason": "unbacked_id" if unbacked else "no_slice"})
    return legs


def classify(turn: dict, graph, *, backed: set, slice_for, uncached_count_fn=None,
             current_graph_version: str | None = None) -> dict:
    """One sparse turn -> its attribution record. Buckets are assigned dominant-first: dark routing
    (free to fix) beats unchunked (costs the heavy pass) beats genuine absence."""
    contract = turn.get("contract") or next(iter(turn.get("contracts") or []), None)
    rec = {"user": turn.get("_user"), "sk": turn.get("_sk"), "ts": turn.get("ts"),
           "asof": turn.get("asof"), "intent": turn.get("intent"), "contract": contract,
           "n_evidence_sources": evidence_source_count(turn),
           "graph_version_match": (current_graph_version is None
                                   or turn.get("graph_version") == current_graph_version)}
    if not contract:
        rec.update({"klass": "unroutable", "dark_driver_legs": [], "n_uncached_docs": None})
        return rec
    legs = dark_legs(contract, graph, backed=backed, slice_for=slice_for)
    uncached = uncached_count_fn(contract) if uncached_count_fn else None
    rec["dark_driver_legs"] = legs
    rec["n_uncached_docs"] = uncached
    if legs:
        rec["klass"] = "dark_routing"
    elif uncached:
        rec["klass"] = "unchunked_doc"
    elif uncached is None:
        rec["klass"] = "coverage_unknown"          # no corpus listing available — never silently 'absence'
    else:
        rec["klass"] = "genuine_absence"
    return rec


def snapshot(turns: list[dict], graph, *, backed: set, slice_for, uncached_count_fn=None,
             corpus_fingerprint: str | None = None, label: str = "E0") -> dict:
    """The persisted attribution artifact. Re-run the identical snapshot after E1 / after E4 — the
    bucket deltas are the per-fix ROI measurement."""
    kept = [t for t in turns if keep(t)]
    sparse = [t for t in kept if is_sparse(t)]
    gv = getattr(graph, "version", None)
    per = [classify(t, graph, backed=backed, slice_for=slice_for,
                    uncached_count_fn=uncached_count_fn, current_graph_version=gv) for t in sparse]
    counts: dict[str, int] = {}
    for p in per:
        counts[p["klass"]] = counts.get(p["klass"], 0) + 1
    return {"snapshot": label, "basis": "as_of_current_config",
            "graph_version": gv, "corpus_fingerprint": corpus_fingerprint,
            "n_turns_scanned": len(turns), "n_kept": len(kept), "n_sparse": len(sparse),
            "n_graph_version_mismatch": sum(1 for p in per if not p["graph_version_match"]),
            "attribution": counts, "per_turn": per}


# ── serving wiring (one-time cached corpus listings; no per-turn LISTs) ─────────────────────────────
def make_uncached_count_fn():
    """{contract -> count of never-chunked corpus docs among its covering sources}. ONE text/ LIST +
    ONE chunks/ LIST (both cached here) — never a per-turn listing (the July LIST-storm cost class)."""
    import hashlib

    import boto3

    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag import evidence_batch as evb
    from leviathan.graphrag.corpus_recon import BUCKET, TEXT_PREFIX, _source_of
    s3 = boto3.client("s3")
    keys = [o["Key"] for p in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX)
            for o in p.get("Contents", []) if o["Key"].endswith("document.json")]
    cached = evb._cached_hashes()
    unc_by_src: dict[str, int] = {}
    for k in keys:
        if hashlib.md5(k.encode("utf-8")).hexdigest() not in cached:
            s = _source_of(k)
            unc_by_src[s] = unc_by_src.get(s, 0) + 1
    all_src = {_source_of(k) for k in keys}
    memo: dict[str, int] = {}

    def fn(contract: str) -> int:
        if contract not in memo:
            cov = ev.covering_sources(contract, all_src)
            memo[contract] = sum(unc_by_src.get(s, 0) for s in cov)
        return memo[contract]
    return fn


def main() -> int:  # pragma: no cover — CLI glue; the pieces above are unit-tested
    import argparse

    import boto3

    from leviathan.graphrag import eval as gev
    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag import graph as gph
    ap = argparse.ArgumentParser(description="E0/E3 sparsity-attribution snapshot (static, $0)")
    ap.add_argument("--table", default=os.environ.get("GRAPHRAG_STORE_TABLE", "leviathan-dev-terminal-store"))
    ap.add_argument("--label", default="E0")
    ap.add_argument("--dry-run", action="store_true", help="skip the corpus LIST (no unchunked counts)")
    ap.add_argument("--out", default=None, help="output json path (default configs/graphrag/eval/)")
    args = ap.parse_args()

    graph = gph.CausalGraph.load()
    turns = enumerate_turns(boto3.client("dynamodb"), args.table)
    print(f"scanned {len(turns)} persisted turns from {args.table}")
    ucf = None if args.dry_run else make_uncached_count_fn()
    snap = snapshot(turns, graph, backed=ev.backed_dag_ids(), slice_for=ev.slice_for_driver,
                    uncached_count_fn=ucf, corpus_fingerprint=gev.corpus_fingerprint(), label=args.label)
    from leviathan.graphrag import extract as ex
    out = args.out or (ex._CFG / "eval" / f"{args.label.lower()}_snapshot_{snap['graph_version']}.json")
    from pathlib import Path
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(snap, indent=2), encoding="utf-8")
    s3uri = ev._evid_s3()
    if s3uri:
        import boto3 as _b
        b, k = ev._parse_s3(s3uri.rstrip("/") + f"/eval/{Path(str(out)).name}")
        _b.client("s3").put_object(Bucket=b, Key=k, Body=Path(out).read_bytes())
        print(f"  snapshot -> s3://{b}/{k}")
    print(f"kept {snap['n_kept']} reasoning-class turns; sparse {snap['n_sparse']}; "
          f"attribution {snap['attribution']}")
    print(f"snapshot -> {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
