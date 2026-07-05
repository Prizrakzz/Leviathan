"""GraphRAG extraction PILOT — run Opus 4.8 over a stratified sample of real docs.

Goal: de-risk the vocab/contracts against real text, emit ~100-200 CANDIDATE gold examples for human
review, and MEASURE coercion/drop rates (the "too deterministic?" question). Synchronous Messages API
(fast feedback), NOT Batch. Spends real money — run ``--dry-run`` first to preview the cost.

    python -m leviathan.graphrag.pilot --dry-run
    python -m leviathan.graphrag.pilot --max-docs 25 --cost-cap 15

Outputs → git-ignored ``configs/graphrag/pilot/`` (private). Code is public; the IP it reads + writes
stays ignored.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
import time
from datetime import date
from pathlib import Path

import boto3
import yaml

from leviathan.graphrag import extract as ex
from leviathan.graphrag.chunking import chunk_document
from leviathan.graphrag.corpus_recon import BUCKET, TEXT_PREFIX, _expected_lang, _source_of

_CFG = Path(__file__).resolve().parents[3] / "configs" / "graphrag"
_OUT = _CFG / "pilot"
_REPO = Path(__file__).resolve().parents[3]
# multilingual + thin-coverage sources we deliberately want represented
_PRIORITY = ("conab", "fnc", "mpob", "usda_wasde", "usda_wap")
_EST_OUT_TOKENS = 700  # assumed output/chunk for the dry-run estimate


# ── secrets + vocab sets ──────────────────────────────────────────────────────────
def _load_env() -> None:
    f = _REPO / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _api_key() -> str:
    key = os.environ.get("ANTHROPIC_API") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API not found in environment or .env")
    return key


def _vocab_sets() -> tuple[set[str], set[str], set[str]]:
    v = yaml.safe_load((_CFG / "entity_vocabulary.yaml").read_text(encoding="utf-8"))
    node_types = set(v.get("nodes", {}).keys())
    node_members = {t for terms in v.get("nodes", {}).values() if terms for t in terms}
    edges = set(v.get("edges", {}).keys())
    return node_types, node_members, edges


# ── sampling (reuse corpus_recon's S3 list pattern) ───────────────────────────────
def _doc_date(doc: dict, key: str) -> date:
    for field in ("document_date", "date", "published"):
        val = doc.get(field)
        if isinstance(val, str):
            m = re.search(r"(\d{4})[-/](\d{2})[-/](\d{2})", val)
            if m:
                return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"(\d{4})[-/](\d{2})[-/](\d{2})", key) or re.search(r"\b(20\d{2})\b", key)
    if m and len(m.groups()) == 3:
        return date(int(m[1]), int(m[2]), int(m[3]))
    if m:
        return date(int(m[1]), 1, 1)
    return date(2024, 1, 1)


def sample_keys(s3, max_docs: int, seed: int) -> list[str]:
    by_source: dict[str, list[str]] = collections.defaultdict(list)
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX):
        for o in page.get("Contents", []):
            k = o["Key"]
            if k.endswith("document.json"):
                by_source[_source_of(k)].append(k)
    rng = random.Random(seed)
    for keys in by_source.values():
        rng.shuffle(keys)
    # priority sources first, then the rest — round-robin one per source per pass
    order = [s for s in _PRIORITY if s in by_source] + [s for s in sorted(by_source) if s not in _PRIORITY]
    picked: list[str] = []
    pos = {s: 0 for s in order}
    while len(picked) < max_docs and any(pos[s] < len(by_source[s]) for s in order):
        for s in order:
            if pos[s] < len(by_source[s]):
                picked.append(by_source[s][pos[s]])
                pos[s] += 1
                if len(picked) >= max_docs:
                    break
    return picked


# ── per-doc work ──────────────────────────────────────────────────────────────────
def _chunks_for(s3, key: str, max_chunks_per_doc: int):
    doc = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    full = doc.get("full_text") or ""
    if not full.strip():
        return []
    src = _source_of(key)
    chunks = chunk_document(
        full_text=full, source_key=key, source=src, document_date=_doc_date(doc, key),
        lang=_expected_lang(src), extraction_method=doc.get("extraction_method"),
        doc_id=f"{src}-{abs(hash(key)) % 10**8:08d}")
    return chunks[:max_chunks_per_doc]


def _candidate_record(chunk, mapped: dict) -> dict:
    return {
        "id": chunk.chunk_id, "source": chunk.source, "doc": chunk.source_key,
        "chunk": chunk.proposition[:1200],
        "entities": [{"id": e.entity_id, "type": e.type} for e in mapped["entities"]],
        "edges": [{"src": r.src_entity, "rel": r.relation_type, "sign": r.sign,
                   "dst": r.dst_entity, "metric": r.metric, "evidence_class": r.evidence_class}
                  for r in mapped["relationships"]],
        "quant": [{"metric": q.metric, "value": q.value, "unit": q.unit, "direction": q.direction}
                  for q in mapped["quantitative_claims"]],
    }


# ── main ───────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="GraphRAG Opus extraction pilot.")
    ap.add_argument("--max-docs", type=int, default=25)
    ap.add_argument("--max-chunks", type=int, default=400, help="global chunk cap (cost guard)")
    ap.add_argument("--max-chunks-per-doc", type=int, default=20)
    ap.add_argument("--cost-cap", type=float, default=15.0, help="hard $ stop")
    ap.add_argument("--dry-run", action="store_true", help="sample+chunk+estimate cost; NO API calls")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--seed", type=int, default=20260620)
    args = ap.parse_args()

    _load_env()
    s3 = boto3.client("s3", region_name=args.region)
    keys = sample_keys(s3, args.max_docs, args.seed)
    by_src = collections.Counter(_source_of(k) for k in keys)
    print(f"sampled {len(keys)} docs across {len(by_src)} sources: {dict(by_src)}")

    system = ex.build_system_prompt()
    sys_chars = len(system)

    # ---- DRY RUN: estimate only ----
    if args.dry_run:
        total_chunks = est_in = 0
        for k in keys:
            for ch in _chunks_for(s3, k, args.max_chunks_per_doc):
                total_chunks += 1
                est_in += (sys_chars + len(ch.proposition) + 400) // 4   # +neighbors ≈ 400 chars
        total_chunks = min(total_chunks, args.max_chunks)
        est_cost = est_in * ex.PRICE_IN + total_chunks * _EST_OUT_TOKENS * ex.PRICE_OUT
        print(f"[dry-run] ~{total_chunks} chunks, ~{est_in:,} input tokens + "
              f"~{total_chunks * _EST_OUT_TOKENS:,} output tokens -> est ${est_cost:,.2f} "
              f"(cap ${args.cost_cap}). No API calls made.")
        return 0

    # ---- REAL RUN ----
    import anthropic  # noqa: PLC0415 — only needed for the paid path
    from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

    client = anthropic.Anthropic(api_key=_api_key())
    node_types, node_members, edges = _vocab_sets()

    @retry(retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError,
                                          anthropic.APIConnectionError)),
           wait=wait_exponential(multiplier=2, min=2, max=30), stop=stop_after_attempt(4))
    def _extract(user: str):
        return ex.call_opus(client, system, user)

    candidates: list[dict] = []
    agg = ex.Friction()
    cost_log: list[dict] = []
    used = collections.Counter()
    spent = 0.0
    n_chunks = 0
    stop = False

    for k in keys:
        if stop:
            break
        chunks = _chunks_for(s3, k, args.max_chunks_per_doc)
        doc_cost = doc_in = doc_out = 0
        for i, ch in enumerate(chunks):
            if n_chunks >= args.max_chunks or spent >= args.cost_cap:
                stop = True
                break
            prev = chunks[i - 1].proposition if i > 0 else ""
            nxt = chunks[i + 1].proposition if i < len(chunks) - 1 else ""
            user = ex.build_user_message(prev, ch.proposition, nxt)
            try:
                tool_input, usage = _extract(user)
                x = ex.parse_extraction(tool_input)
            except Exception as exc:                       # noqa: BLE001 — log + skip, never crash
                agg.validation_failures.append(f"{ch.chunk_id}: {type(exc).__name__}")
                continue
            mapped, fr = ex.to_contracts(x, ch, node_types=node_types,
                                         node_members=node_members, edges=edges)
            # aggregate friction
            agg.unmapped_relations += fr.unmapped_relations
            agg.unmapped_entities += fr.unmapped_entities
            agg.validation_failures += fr.validation_failures
            agg.causal_without_marker += fr.causal_without_marker
            agg.n_entities += fr.n_entities
            agg.n_relationships += fr.n_relationships
            used[ch.source] += 1
            if mapped["entities"] or mapped["relationships"]:
                candidates.append(_candidate_record(ch, mapped))
            doc_in += usage.input_tokens
            doc_out += usage.output_tokens
            doc_cost += usage.cost
            spent += usage.cost
            n_chunks += 1
            time.sleep(0.3)                                # stay polite to Tier-1 RPM
        cost_log.append({"doc": k, "chunks": len(chunks), "input_tokens": doc_in,
                         "output_tokens": doc_out, "cost_usd": round(doc_cost, 4)})

    _write_reports(candidates, agg, cost_log, spent, n_chunks, dict(used))
    print(f"done: {n_chunks} chunks, {len(candidates)} candidate examples, ${spent:.2f} spent. "
          f"reports → {_OUT}")
    return 0


def _write_reports(candidates, agg, cost_log, spent, n_chunks, by_source) -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    (_OUT / "extraction.candidates.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in candidates), encoding="utf-8")
    (_OUT / "cost_log.json").write_text(json.dumps(
        {"model": ex.MODEL, "total_cost_usd": round(spent, 4), "chunks": n_chunks,
         "per_doc": cost_log}, indent=2), encoding="utf-8")

    rel_top = collections.Counter(agg.unmapped_relations).most_common(25)
    ent_top = collections.Counter(agg.unmapped_entities).most_common(25)
    dens_e = agg.n_entities / n_chunks if n_chunks else 0
    dens_r = agg.n_relationships / n_chunks if n_chunks else 0
    density = dens_e + dens_r
    dens_flag = ("HIGH - retrieval-noise risk" if density > 12
                 else "ok" if density > 1 else "LOW - under-extraction")
    rel_lines = [f"- {n}x `{r}`" for r, n in rel_top] or ["- none"]
    ent_lines = [f"- {n}x `{e}`" for e, n in ent_top] or ["- none"]
    lines = [
        "# GraphRAG pilot - friction report",
        f"\n**{n_chunks} chunks | ${spent:.2f} | model {ex.MODEL}**\n",
        f"- mapped entities: **{agg.n_entities}** ({dens_e:.1f}/chunk) | "
        f"mapped relationships: **{agg.n_relationships}** ({dens_r:.1f}/chunk)",
        f"- **density** {density:.1f} graph elements/chunk ({dens_flag})",
        f"- **unmapped relationships** (taxonomy too tight?): {len(agg.unmapped_relations)}",
        f"- **unmapped entities** (would-be new nodes): {len(agg.unmapped_entities)}",
        f"- **causal links without a marker** (dropped by the strict rule): {agg.causal_without_marker}",
        f"- contract-validation failures: {len(agg.validation_failures)}",
        f"- by source: {by_source}",
        "\n## Top unmapped relationships (candidate new edge types / coercion)",
        *rel_lines,
        "\n## Top unmapped entities (candidate new nodes)",
        *ent_lines,
        "\n## Read me",
        "High unmapped-relationship counts => the closed edge taxonomy is dropping real multi-hop "
        "links (loosen or grow it). High density => tighten extraction precision before the full run. "
        "These candidates are NOT gold until a human validates them.",
    ]
    (_OUT / "friction_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
