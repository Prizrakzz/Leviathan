"""GraphRAG extraction-model bake-off (Stage C) — Sonnet 4.6 vs Bedrock Kimi-K2.5 vs Qwen3-32B.

Runs all three on the CLEANED K=1 pipeline over IDENTICAL chunks (sync + multithreaded, backoff) to
produce a cost-quality frontier → pick the production extraction model. Sonnet (Anthropic Messages) is the
silver reference; Kimi/Qwen run via Bedrock Converse forced tool use. Only the model varies — same docs,
same lean prompt + hygiene, same `to_contracts` guards. Output → configs/graphrag/pilot/bakeoff_report.md.

    python -m leviathan.graphrag.bakeoff --bakeoff --dry-run   # est cost, no calls
    python -m leviathan.graphrag.bakeoff --bakeoff             # gated ~$3-4 run
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import random
import threading
import time

import boto3

from leviathan.graphrag import batch_extract as bx
from leviathan.graphrag import extract as ex
from leviathan.graphrag.corpus_recon import _source_of

_OUT = bx._OUT
_CORPUS_PROPS = 1_700_000          # ~263 propositional chunks/doc x 6,537 docs (ungated upper bound)

# (label, provider, model_id) — Sonnet via Anthropic (proven forced-tool path; its Bedrock id is
# INFERENCE_PROFILE-only and unverified); Kimi/Qwen via Bedrock Converse (ON_DEMAND, us-east-1).
EXTRACTORS = [
    ("sonnet", "anthropic", ex.SONNET),
    ("kimi", "bedrock", "moonshotai.kimi-k2.5"),
    ("qwen", "bedrock", "qwen.qwen3-32b-v1:0"),
]
# per-1M (input, output) USD — Sonnet Anthropic; Kimi/Qwen Bedrock (Stage B pricing page).
PRICES = {"sonnet": (3.0, 15.0), "kimi": (0.60, 3.00), "qwen": (0.1545, 0.618)}
_REGION = "us-east-1"
_MAX_PER_DOC = 60
_WORKERS = 6
_PROP_OUT_TOK = 450
_THROTTLE = ("throttl", "toomanyrequests", "429", "ratelimit", "overloaded", "serviceunavailable")


# ── adapters ─────────────────────────────────────────────────────────────────────
def _converse_toolspec() -> dict:
    """Wrap the lean emit_extraction tool as a Bedrock Converse toolSpec."""
    t = ex.extraction_tool(lean=True)
    return {"toolSpec": {"name": t["name"], "description": t["description"],
                         "inputSchema": {"json": t["input_schema"]}}}


def converse_extract(rt, model_id, system, user, *, max_tokens=4096):
    """Bedrock Converse forced-tool extraction → (tool_input_dict | None, in_tok, out_tok)."""
    resp = rt.converse(
        modelId=model_id,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        toolConfig={"tools": [_converse_toolspec()], "toolChoice": {"tool": {"name": "emit_extraction"}}},
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
    )
    blocks = resp["output"]["message"]["content"]
    ti = next((b["toolUse"]["input"] for b in blocks if "toolUse" in b), None)
    u = resp.get("usage", {}) or {}
    return ti, u.get("inputTokens", 0), u.get("outputTokens", 0)


def _with_backoff(fn, *, tries=5, base=1.5):
    """Retry on throttling with exponential backoff + jitter; re-raise anything else (or final throttle)."""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if any(t in (type(e).__name__ + str(e)).lower() for t in _THROTTLE) and i < tries - 1:
                time.sleep(base ** i + random.random())
                continue
            raise
    raise last  # pragma: no cover


def _extract(provider, model_id, anthro, rt, system, user):
    if provider == "anthropic":
        ti, usage = ex.call_opus(anthro, system, user, model=model_id, tool=ex.extraction_tool(lean=True))
        return ti, usage.input_tokens, usage.output_tokens
    return converse_extract(rt, model_id, system, user)


# ── runner ───────────────────────────────────────────────────────────────────────
def _blank():
    return {"rels": [], "ok": 0, "schema_fail": 0, "throttle": 0, "in": 0, "out": 0,
            "self_loops": 0, "dropped_instrument": 0, "yield_metric_fixed": 0}


def bakeoff(s3, anthro, rt, *, seed, max_per_doc, workers):
    keys = bx._sample_minibatch(s3, seed)
    print(f"bake-off on {len(keys)} docs: {[_source_of(k) for k in keys]} | models={[e[0] for e in EXTRACTORS]}")
    system = ex.build_system_prompt(lean=True)
    nt, nm, edg = ex.vocab_sets()
    chunks = []                                          # (chunk, user_message) — chunked ONCE, shared by all
    for key in keys:
        cs = bx._chunks_for(s3, key, "haiku", gate=True)[:max_per_doc]
        for i, ch in enumerate(cs):
            prev = cs[i - 1].proposition if i > 0 else ""
            nxt = cs[i + 1].proposition if i < len(cs) - 1 else ""
            chunks.append((ch, ex.build_user_message(prev, ch.proposition, nxt)))
    print(f"  {len(chunks)} chunks x {len(EXTRACTORS)} models = {len(chunks) * len(EXTRACTORS)} calls", flush=True)

    res = {lab: _blank() for lab, _, _ in EXTRACTORS}
    lock = threading.Lock()

    def task(label, provider, model_id, ch, msg):
        try:
            ti, itok, otok = _with_backoff(lambda: _extract(provider, model_id, anthro, rt, system, msg))
        except Exception:  # noqa: BLE001 — backoff exhausted / hard error
            with lock:
                res[label]["throttle"] += 1
            return
        if ti is None:
            with lock:
                res[label]["schema_fail"] += 1
            return
        try:
            mapped, fr = ex.to_contracts(ex.parse_extraction(ti), ch, node_types=nt, node_members=nm, edges=edg)
        except Exception:  # noqa: BLE001
            with lock:
                res[label]["schema_fail"] += 1
            return
        with lock:
            r = res[label]
            r["ok"] += 1
            r["in"] += itok
            r["out"] += otok
            r["rels"] += mapped["relationships"]
            r["self_loops"] += fr.self_loops
            r["dropped_instrument"] += fr.dropped_instrument
            r["yield_metric_fixed"] += fr.yield_metric_fixed

    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(task, lab, prov, mid, ch, msg)
                for lab, prov, mid in EXTRACTORS for ch, msg in chunks]
        for f in cf.as_completed(futs):
            f.result()
    _bakeoff_report(res, keys, len(chunks))


def _derive(r, label):
    """Edge/cascade/chain sets + cost for one model's accumulated relationships."""
    collapsed = ex.collapse_reference_edges(r["rels"])
    edges = {(x.src_entity, x.relation_type, x.dst_entity, x.metric) for x in collapsed}
    cascade = {e for e in edges if ex._edge_class(e[1]) == "propagating"}
    prov = collections.defaultdict(set)
    for x in collapsed:
        if x.sources:
            s0 = x.sources[0]
            d = s0.document_date.isoformat() if getattr(s0, "document_date", None) else "?"
            prov[(x.src_entity, x.relation_type, x.dst_entity)].add((s0.source, d))
    chains = bx._two_hop_chains(cascade, prov)
    pin, pout = PRICES[label]
    return dict(edges=edges, cascade=cascade, chains=chains, cost=(r["in"] * pin + r["out"] * pout) / 1e6)


def _bakeoff_report(res, keys, n_chunks):
    _OUT.mkdir(parents=True, exist_ok=True)
    der = {lab: _derive(res[lab], lab) for lab, _, _ in EXTRACTORS}
    ref = der["sonnet"]
    rec = lambda a, b: (len(a & b) / len(b)) if b else 1.0       # noqa: E731 — recall of a vs ref b
    prec = lambda a, b: (len(a & b) / len(a)) if a else 1.0      # noqa: E731 — a's overlap with ref
    fmt = lambda e: f"{e[0]} -{e[1]}({e[3] or '-'})-> {e[2]}"    # noqa: E731
    ek = lambda e: tuple(str(x) for x in e)                      # noqa: E731
    L = ["# Stage C — extraction-model bake-off (cost-quality frontier)",
         f"\n{len(keys)} docs, {n_chunks} chunks/model, K=1, cleaned pipeline | reference = sonnet\n",
         "| model | adherence | edges | cascade | chains | self_loop | instr | $/prop | proj corpus $ | "
         "casc-recall | casc-prec | chain-recall |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for lab, _, _ in EXTRACTORS:
        r, d = res[lab], der[lab]
        adh = r["ok"] / (r["ok"] + r["schema_fail"]) if (r["ok"] + r["schema_fail"]) else 0.0
        dpp = d["cost"] / r["ok"] if r["ok"] else 0.0
        is_ref = lab == "sonnet"
        cr, pr, ch = rec(d["cascade"], ref["cascade"]), prec(d["cascade"], ref["cascade"]), rec(d["chains"], ref["chains"])
        L.append(f"| {lab}{' (ref)' if is_ref else ''} | {adh:.0%} | {len(d['edges'])} | {len(d['cascade'])} | "
                 f"{len(d['chains'])} | {r['self_loops']} | {r['dropped_instrument']} | ${dpp:.5f} | "
                 f"${dpp * _CORPUS_PROPS:,.0f} | {'—' if is_ref else f'{cr:.0%}'} | {'—' if is_ref else f'{pr:.0%}'} | "
                 f"{'—' if is_ref else f'{ch:.0%}'} |")
    L += ["\n- throttle/hard failures: " + ", ".join(f"{lab}={res[lab]['throttle']}" for lab, _, _ in EXTRACTORS),
          "\n**Read:** cheapest model holding **cascade-recall AND chain-recall ≥ ~85%** at **high adherence** wins.",
          "casc-prec < 100% = edges the model found that Sonnet didn't — *genuine extra OR hallucination* (eyeball below).",
          "Projection = $/prop × ~1.7M corpus props (K=1 propositional, ungated upper bound)."]
    for lab, _, _ in EXTRACTORS:
        if lab == "sonnet":
            continue
        d = der[lab]
        extra = [fmt(e) for e in sorted(d["cascade"] - ref["cascade"], key=ek)][:12]
        missed = [fmt(e) for e in sorted(ref["cascade"] - d["cascade"], key=ek)][:12]
        L += [f"\n## {lab}: cascade edges it ADDED vs Sonnet ({len(d['cascade'] - ref['cascade'])}) — extra find or hallucination?"]
        L += extra or ["- none"]
        L += [f"\n## {lab}: Sonnet cascade edges it MISSED ({len(ref['cascade'] - d['cascade'])})"]
        L += missed or ["- none"]
    (_OUT / "bakeoff_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L), flush=True)
    print(f"\nwrote {_OUT / 'bakeoff_report.md'}", flush=True)


def dry_bakeoff(s3, *, seed, max_per_doc):
    keys = bx._sample_minibatch(s3, seed)
    sysl = len(ex.build_system_prompt(lean=True))
    n = sum(min(len(bx._chunks_for(s3, k, "deterministic", 1000, gate=True)) * 10, max_per_doc) for k in keys)
    pre = sysl // 4 + 170
    print(f"bake-off docs: {[_source_of(k) for k in keys]} | ~{n} chunks/model (det proxy)")
    total = 0.0
    for lab, _, _ in EXTRACTORS:
        pin, pout = PRICES[lab]
        c = (n * (pre + 40) * pin + n * _PROP_OUT_TOK * pout) / 1e6
        total += c
        print(f"  [dry] {lab}: ~{n} calls, est ${c:.2f}")
    print(f"[dry-run] total est ${total:.2f} (sync, no Batch discount). No API calls.")


def main() -> int:
    ap = argparse.ArgumentParser(description="GraphRAG Stage-C model bake-off.")
    ap.add_argument("--bakeoff", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="estimate only, no API calls")
    ap.add_argument("--seed", type=int, default=20260621)
    ap.add_argument("--max-per-doc", type=int, default=_MAX_PER_DOC)
    ap.add_argument("--workers", type=int, default=_WORKERS)
    ap.add_argument("--region", default=_REGION)
    args = ap.parse_args()

    bx._load_env()
    s3 = boto3.client("s3", region_name=args.region)
    if args.dry_run:
        dry_bakeoff(s3, seed=args.seed, max_per_doc=args.max_per_doc)
        return 0
    if not args.bakeoff:
        ap.error("choose --bakeoff (optionally with --dry-run)")
    import anthropic
    anthro = anthropic.Anthropic(api_key=bx._api_key())
    rt = boto3.client("bedrock-runtime", region_name=args.region)
    bakeoff(s3, anthro, rt, seed=args.seed, max_per_doc=args.max_per_doc, workers=args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
