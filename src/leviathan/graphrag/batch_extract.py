"""GraphRAG cloud extraction — Anthropic Message Batches API (laptop-independent, durable).

Two-stage, provider-split pipeline (per the design):
  1. Haiku (Bedrock) propositional chunking — inline at submit (cents, seconds for a few docs).
  2. Opus 4.8 (Anthropic Batch API) entity-edge extraction — server-side, async, ~50% cheaper.

The long Opus stage runs on Anthropic's servers: submit, the laptop can close, results persist 29 days.
Output is the FULL grounded-truth graph (all five contract tables, with provenance) → S3 `graphragv2/`.

    python -m leviathan.graphrag.batch_extract --dry-run        # pick 3 docs + estimate, no spend
    python -m leviathan.graphrag.batch_extract --submit         # chunk + persist + create batch, exit
    python -m leviathan.graphrag.batch_extract --retrieve <id>  # poll + fetch + write full records
    python -m leviathan.graphrag.batch_extract --run            # submit then poll inline
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
import time
from pathlib import Path

import boto3

from leviathan.graphrag import extract as ex
from leviathan.graphrag.chunking import chunk_document, propositional_chunks
from leviathan.graphrag.contracts import Chunk
from leviathan.graphrag.corpus_recon import BUCKET, TEXT_PREFIX, _source_of

_REPO = Path(__file__).resolve().parents[3]
_OUT = _REPO / "configs" / "graphrag" / "pilot"
_PREFIX = "graphragv2"
_TABLES = ("chunks", "entities", "relationships", "events", "quantitative_claims")
_BATCH_PRICE = 0.5  # Batch API = 50% of standard token price


# ── secrets ────────────────────────────────────────────────────────────────────────
def _load_env() -> None:
    f = _REPO / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _api_key() -> str:
    key = os.environ.get("ANTHROPIC_API") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API not found in environment or .env")
    return key


# ── doc metadata helpers ─────────────────────────────────────────────────────────
def _year_of(key: str) -> str:
    for pat in (r"crop_year=(\d{4})", r"year=(\d{4})", r"(20\d{2})", r"(19\d{2})"):
        m = re.search(pat, key)
        if m:
            return m.group(1)
    return "unknown"


_DOMAIN = [
    (("cocoa", "coffee", "sugar", "cotton", "orange", "conab", "fnc"), "softs"),
    (("palm", "mpob", "mpoc", "soybean_oil", "soybean_meal", "soybeans", "oilseed", "rapeseed"), "oilseeds"),
    (("wheat", "corn", "maize", "rice", "grain", "wasde", "wap"), "grains"),
]


def _domain_of(source: str) -> str:
    s = source.lower()
    for keys, dom in _DOMAIN:
        if any(k in s for k in keys):
            return dom
    return "macro"


def _custom_id(chunk_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", chunk_id)[:64]


def _doc_date_from(doc: dict, key: str):
    from leviathan.graphrag.pilot import _doc_date   # reuse the date parser
    return _doc_date(doc, key)


# ── sampling: 3 docs, 3 distinct years, 3 distinct domains (>=1 softs) ─────────────
def sample_3(s3, seed: int) -> list[str]:
    cand: list[tuple[str, str, str, str]] = []   # (source, year, domain, key)
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX):
        for o in page.get("Contents", []):
            k = o["Key"]
            if k.endswith("document.json"):
                src = _source_of(k)
                cand.append((src, _year_of(k), _domain_of(src), k))
    random.Random(seed).shuffle(cand)
    picked: list[str] = []
    years: set[str] = set()
    for want in ("softs", "grains", "oilseeds"):     # one of each, distinct year, softs guaranteed
        for src, yr, dom, k in cand:
            if dom == want and yr not in years and yr != "unknown" and k not in picked:
                picked.append(k)
                years.add(yr)
                break
    for src, yr, dom, k in cand:                      # backfill to 3 if a bucket was empty
        if len(picked) >= 3:
            break
        if yr not in years and k not in picked:
            picked.append(k)
            years.add(yr)
    return picked[:3]


# ── S3 io ──────────────────────────────────────────────────────────────────────────
def _put_jsonl(s3, key: str, records: list[dict]) -> None:
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in records).encode("utf-8")
    s3.put_object(Bucket=BUCKET, Key=key, Body=body)


def _chunks_for(s3, key: str, chunker: str):
    doc = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    full = doc.get("full_text") or ""
    if not full.strip():
        return []
    src = _source_of(key)
    kw = dict(full_text=full, source_key=key, source=src, document_date=_doc_date_from(doc, key),
              lang="en", extraction_method=doc.get("extraction_method"),
              doc_id=f"{src}-{_year_of(key)}-{abs(hash(key)) % 10**6:06d}")
    return propositional_chunks(**kw) if chunker == "haiku" else chunk_document(**kw)


# ── modes ───────────────────────────────────────────────────────────────────────────
def submit(s3, anthropic_client, *, seed: int, chunker: str) -> str:
    keys = sample_3(s3, seed)
    print(f"docs: {[(_source_of(k), _year_of(k), _domain_of(_source_of(k))) for k in keys]}")
    system = ex.build_system_prompt()
    requests, manifest, chunk_rows = [], {}, []
    for key in keys:
        chunks = _chunks_for(s3, key, chunker)
        for i, ch in enumerate(chunks):
            cid = _custom_id(ch.chunk_id)
            prev = chunks[i - 1].proposition if i > 0 else ""
            nxt = chunks[i + 1].proposition if i < len(chunks) - 1 else ""
            requests.append({"custom_id": cid, "params": {
                "model": ex.MODEL, "max_tokens": 4096,
                # NO prompt caching in Batch: measured (msgbatch_…ERLJM) that concurrent batch requests
                # mostly WRITE the cache (2× premium) rather than read it (0.1×) → caching RAISED cost
                # by ~$1.85. The cost lever for the corpus run is chunk granularity, not caching.
                "system": system,
                "messages": [{"role": "user", "content": ex.build_user_message(prev, ch.proposition, nxt)}],
                "tools": [ex.extraction_tool()], "tool_choice": {"type": "tool", "name": "emit_extraction"}}})
            manifest[cid] = ch.model_dump(mode="json")
            chunk_rows.append((ch.source, _year_of(key), ch.model_dump(mode="json")))
    if not requests:
        raise SystemExit("no chunks produced — aborting")

    batch = anthropic_client.messages.batches.create(requests=requests)
    bid = batch.id
    # persist chunks (grounded provenance) + manifest + batch id BEFORE Opus runs → laptop can close
    for (src, yr, _), grp in _group(chunk_rows):
        _put_jsonl(s3, f"{_PREFIX}/chunks/source={src}/year={yr}/part-{bid}.jsonl", [r for *_, r in grp])
    s3.put_object(Bucket=BUCKET, Key=f"{_PREFIX}/_batches/{bid}/manifest.json",
                  Body=json.dumps(manifest).encode("utf-8"))
    _OUT.mkdir(parents=True, exist_ok=True)
    (_OUT / f"batch_{bid}.json").write_text(json.dumps({"batch_id": bid, "n_requests": len(requests),
                                                        "manifest": manifest}), encoding="utf-8")
    print(f"submitted batch {bid} ({len(requests)} requests). chunks persisted to s3://{BUCKET}/{_PREFIX}/chunks/")
    print(f"retrieve later with:  python -m leviathan.graphrag.batch_extract --retrieve {bid}")
    return bid


def _group(rows):
    g = collections.defaultdict(list)
    for src, yr, r in rows:
        g[(src, yr, None)].append((src, yr, r))
    return g.items()


def _load_manifest(s3, bid: str) -> dict:
    local = _OUT / f"batch_{bid}.json"
    if local.exists():
        return json.loads(local.read_text(encoding="utf-8"))["manifest"]
    obj = s3.get_object(Bucket=BUCKET, Key=f"{_PREFIX}/_batches/{bid}/manifest.json")
    return json.loads(obj["Body"].read())


def retrieve(s3, anthropic_client, bid: str) -> None:
    manifest = _load_manifest(s3, bid)
    while True:
        b = anthropic_client.messages.batches.retrieve(bid)
        if b.processing_status == "ended":
            break
        print(f"  status={b.processing_status} ...")
        time.sleep(30)

    node_types, node_members, edges = ex.vocab_sets()
    tables = {t: collections.defaultdict(list) for t in _TABLES}
    candidates, fr = [], ex.Friction()
    in_tok = out_tok = cache_read = cache_write = 0
    for result in anthropic_client.messages.batches.results(bid):
        cid = result.custom_id
        if result.result.type != "succeeded":
            fr.validation_failures.append(f"{cid}: {result.result.type}")
            continue
        msg = result.result.message
        u = getattr(msg, "usage", None)
        in_tok += getattr(u, "input_tokens", 0)
        out_tok += getattr(u, "output_tokens", 0)
        cache_read += getattr(u, "cache_read_input_tokens", 0) or 0
        cache_write += getattr(u, "cache_creation_input_tokens", 0) or 0
        tool_input = next((b.input for b in msg.content if getattr(b, "type", None) == "tool_use"), None)
        if tool_input is None or cid not in manifest:
            fr.validation_failures.append(f"{cid}: no tool_use / unknown id")
            continue
        chunk = Chunk(**manifest[cid])
        mapped, f1 = ex.to_contracts(ex.parse_extraction(tool_input), chunk,
                                     node_types=node_types, node_members=node_members, edges=edges)
        _merge_friction(fr, f1)
        recs = ex.full_records(mapped, chunk)
        yr = _year_of(chunk.source_key)
        for t in _TABLES:
            tables[t][(chunk.source, yr)].extend(recs[t])
        if mapped["entities"] or mapped["relationships"]:
            candidates.append(ex.candidate_gold(mapped, chunk))

    for t in _TABLES:
        if t == "chunks":
            continue   # already written at submit
        for (src, yr), rows in tables[t].items():
            if rows:
                _put_jsonl(s3, f"{_PREFIX}/{t}/source={src}/year={yr}/part-{bid}.jsonl", rows)
    # Batch (×0.5) pricing; 1h cache write = 2× input, read = 0.1× input
    cost = (in_tok * ex.PRICE_IN + cache_write * ex.PRICE_IN * 2 + cache_read * ex.PRICE_IN * 0.1
            + out_tok * ex.PRICE_OUT) * _BATCH_PRICE
    usage = {"input_tokens": in_tok, "output_tokens": out_tok,
             "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write}
    _write_reports(bid, tables, candidates, fr, cost, usage)
    print(f"retrieved {bid}: "
          f"{sum(len(v) for v in tables['relationships'].values())} relationships, "
          f"{sum(len(v) for v in tables['entities'].values())} entities, ${cost:.2f} "
          f"(cache_read={cache_read:,} cache_write={cache_write:,}). "
          f"full graph → s3://{BUCKET}/{_PREFIX}/  reports → {_OUT}")


def diagnose(s3, anthropic_client, bid: str) -> None:
    """Re-retrieve a finished batch and explain WHY records failed to_contracts — esp. whether the
    Metric enum is too narrow for what Opus actually emits. Read-only; results persist 29 days."""
    from datetime import date
    from typing import get_args
    from leviathan.graphrag.contracts import Event, Metric, QuantitativeClaim
    valid = set(get_args(Metric))

    b = anthropic_client.messages.batches.retrieve(bid)
    if b.processing_status != "ended":
        print(f"batch {bid} not ended ({b.processing_status})")
        return
    metrics, fails, rels = collections.Counter(), collections.Counter(), collections.Counter()
    n = 0
    for result in anthropic_client.messages.batches.results(bid):
        if result.result.type != "succeeded":
            fails[f"batch:{result.result.type}"] += 1
            continue
        ti = next((bl.input for bl in result.result.message.content
                   if getattr(bl, "type", None) == "tool_use"), None)
        if ti is None:
            fails["no_tool_use"] += 1
            continue
        n += 1
        x = ex.parse_extraction(ti)
        for c in x.quantitative_claims:
            metrics[c.metric] += 1
            try:
                QuantitativeClaim(claim_id="d", chunk_id="d", entity_id=c.entity, metric=c.metric,
                                  value=c.value, unit=c.unit, period=c.period or "unknown",
                                  direction=(c.direction if c.direction in ("+", "-", "0") else "0"),
                                  document_date=date(2020, 1, 1))
            except Exception:  # noqa: BLE001
                fails[f"claim_metric:{c.metric}" if c.metric not in valid else "claim:other"] += 1
        for ev in x.events:
            try:
                Event(event_id="d", event_type=ev.event_type, commodity=ev.commodity, country=ev.country,
                      season_or_date="unknown", description=ev.description, document_date=date(2020, 1, 1))
            except Exception as e:  # noqa: BLE001
                fails[f"event:{str(e).splitlines()[0][:48]}"] += 1
        for r in x.relationships:
            rels[r.relation_type] += 1
    print(f"parsed {n} succeeded results")
    print(f"valid Metric enum: {sorted(valid)}")
    print(f"\nFAILURE TALLY:\n  " + "\n  ".join(f"{v:>3}x {k}" for k, v in fails.most_common(30)))
    print(f"\nMETRICS Opus emitted:\n  " + "\n  ".join(f"{v:>3}x {k}" for k, v in metrics.most_common(25)))
    print(f"\nRELATION TYPES emitted:\n  " + "\n  ".join(f"{v:>3}x {k}" for k, v in rels.most_common(30)))


def _merge_friction(agg: ex.Friction, f: ex.Friction) -> None:
    agg.unmapped_relations += f.unmapped_relations
    agg.unmapped_entities += f.unmapped_entities
    agg.validation_failures += f.validation_failures
    agg.causal_without_marker += f.causal_without_marker
    agg.n_entities += f.n_entities
    agg.n_relationships += f.n_relationships


def _write_reports(bid, tables, candidates, fr, cost, usage) -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    (_OUT / "candidate_gold.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in candidates), encoding="utf-8")
    (_OUT / "cost_log.json").write_text(json.dumps({
        "batch_id": bid, "model": ex.MODEL, **usage, "cost_usd": round(cost, 4),
        "table_counts": {t: sum(len(v) for v in tables[t].values()) for t in _TABLES}},
        indent=2), encoding="utf-8")
    rel_lines = [f"- {n}x `{r}`" for r, n in collections.Counter(fr.unmapped_relations).most_common(20)]
    ent_lines = [f"- {n}x `{e}`" for e, n in collections.Counter(fr.unmapped_entities).most_common(20)]
    dang_lines = [f"- {n}x `{d}`" for d, n in collections.Counter(fr.dangling_endpoints).most_common(15)]
    table_lines = [f"| {t} | {sum(len(v) for v in tables[t].values())} |" for t in _TABLES]
    cached = usage.get("cache_read_input_tokens", 0)
    lines = [
        f"# GraphRAG v0.4 grounded-truth extraction ({bid})",
        f"\n**${cost:.2f} | {ex.MODEL} (Batch) | cache_read={cached:,} tok | s3://{BUCKET}/{_PREFIX}/**\n",
        "| table | rows |", "|---|---:|",
        *table_lines,
        f"\n- unmapped relationships (taxonomy too tight?): {len(fr.unmapped_relations)}",
        f"- unmapped entities (would-be new nodes): {len(fr.unmapped_entities)}",
        f"- dangling edge endpoints (non-canonical src/dst): {len(fr.dangling_endpoints)}",
        f"- causal links without a marker: {fr.causal_without_marker}",
        f"- contract-validation / non-succeeded: {len(fr.validation_failures)}",
        "\n## Top unmapped relationships", *(rel_lines or ["- none"]),
        "\n## Top unmapped entities", *(ent_lines or ["- none"]),
        "\n## Top dangling endpoints", *(dang_lines or ["- none"]),
    ]
    (_OUT / "friction_report.md").write_text("\n".join(lines), encoding="utf-8")


def dry_run(s3, *, seed: int) -> None:
    keys = sample_3(s3, seed)
    print(f"docs: {[(_source_of(k), _year_of(k), _domain_of(_source_of(k))) for k in keys]}")
    sys_chars = len(ex.build_system_prompt())
    total = est_in = 0
    for k in keys:
        for ch in _chunks_for(s3, k, "deterministic"):   # free estimate (no Haiku/Opus spend)
            total += 1
            est_in += (sys_chars + len(ch.proposition) + 400) // 4
    est = (est_in * ex.PRICE_IN + total * 700 * ex.PRICE_OUT) * _BATCH_PRICE
    print(f"[dry-run] ~{total} chunks (deterministic proxy), est Batch cost ${est:.2f}. No API calls.")


def main() -> int:
    ap = argparse.ArgumentParser(description="GraphRAG cloud Batch extraction (3 docs x 3 years).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--submit", action="store_true")
    g.add_argument("--retrieve", metavar="BATCH_ID")
    g.add_argument("--run", action="store_true")
    g.add_argument("--diagnose", metavar="BATCH_ID")
    ap.add_argument("--seed", type=int, default=20260621)
    ap.add_argument("--chunker", choices=["haiku", "deterministic"], default="haiku")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()

    _load_env()
    s3 = boto3.client("s3", region_name=args.region)
    if args.dry_run:
        dry_run(s3, seed=args.seed)
        return 0
    import anthropic
    client = anthropic.Anthropic(api_key=_api_key())
    if args.submit:
        submit(s3, client, seed=args.seed, chunker=args.chunker)
    elif args.retrieve:
        retrieve(s3, client, args.retrieve)
    elif args.diagnose:
        diagnose(s3, client, args.diagnose)
    else:
        retrieve(s3, client, submit(s3, client, seed=args.seed, chunker=args.chunker))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
