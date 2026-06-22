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
    python -m leviathan.graphrag.batch_extract --minibatch-test # K props/request vs K=1 (cascade-preserving cost test)
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


def _relevant(ch) -> bool:
    """Cheap no-signal filter: skip cover pages, author/credit lists, pure number tables BEFORE the
    expensive Opus call. Compounds with coarser chunking to cut cost."""
    t = ch.proposition
    if len(t) < 40:
        return False
    letters = sum(c.isalpha() for c in t)
    if letters < len(t) * 0.4:                       # mostly digits/punctuation → a table
        return False
    words = t.split()
    if words and sum(w[:1].isupper() for w in words) > len(words) * 0.85:  # ALL-CAPS name/credit list
        return False
    return True


def _chunks_for(s3, key: str, chunker: str, block_chars: int | None = None, *, gate: bool = False):
    doc = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    full = doc.get("full_text") or ""
    if not full.strip():
        return []
    src = _source_of(key)
    kw = dict(full_text=full, source_key=key, source=src, document_date=_doc_date_from(doc, key),
              lang="en", extraction_method=doc.get("extraction_method"),
              doc_id=f"{src}-{_year_of(key)}-{abs(hash(key)) % 10**6:06d}")
    if chunker == "haiku":
        chunks = propositional_chunks(**kw, **({"max_block_chars": block_chars} if block_chars else {}))
    else:
        chunks = chunk_document(**kw, **({"target_chars": block_chars} if block_chars else {}))
    return [c for c in chunks if _relevant(c)] if gate else chunks


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
        try:
            mapped, f1 = ex.to_contracts(ex.parse_extraction(tool_input), chunk,
                                         node_types=node_types, node_members=node_members, edges=edges)
        except Exception as exc:  # noqa: BLE001 — log + skip, never crash retrieval
            fr.validation_failures.append(f"{cid}: parse {type(exc).__name__}")
            continue
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


_SWEEP_SETTINGS = [("propositional", "haiku", None),    # G1 = recall reference (~97/doc)
                   ("det_1500", "deterministic", 1500), # ~30/doc
                   ("det_4000", "deterministic", 4000)] # ~12/doc
_CORPUS_DOCS = 6537


def sweep(s3, client, *, seed: int, n_docs: int) -> None:
    """Run the same doc(s) through 3 chunk granularities; compare edge-recall vs cost to find the knee."""
    keys = sample_3(s3, seed)[:n_docs]
    print(f"sweep over {len(keys)} doc(s): {[_source_of(k) for k in keys]}")
    node_types, node_members, edges = ex.vocab_sets()
    system = ex.build_system_prompt()
    runs = []
    for label, chunker, bc in _SWEEP_SETTINGS:
        manifest, reqs, nch = {}, [], 0
        for key in keys:
            chunks = _chunks_for(s3, key, chunker, bc, gate=True)
            nch += len(chunks)
            for i, ch in enumerate(chunks):
                cid = _custom_id(f"{label}-{ch.chunk_id}")
                prev = chunks[i - 1].proposition if i > 0 else ""
                nxt = chunks[i + 1].proposition if i < len(chunks) - 1 else ""
                reqs.append({"custom_id": cid, "params": {
                    "model": ex.MODEL, "max_tokens": 4096, "system": system,
                    "messages": [{"role": "user", "content": ex.build_user_message(prev, ch.proposition, nxt)}],
                    "tools": [ex.extraction_tool()], "tool_choice": {"type": "tool", "name": "emit_extraction"}}})
                manifest[cid] = ch.model_dump(mode="json")
        bid = client.messages.batches.create(requests=reqs).id
        runs.append({"label": label, "bid": bid, "manifest": manifest, "n_chunks": nch})
        print(f"  submitted {label}: {nch} chunks -> {bid}")

    res = {}
    for run in runs:
        while client.messages.batches.retrieve(run["bid"]).processing_status != "ended":
            time.sleep(30)
        eset, n_rel, n_ent, n_unmapped, in_tok, out_tok = set(), 0, 0, 0, 0, 0
        for r in client.messages.batches.results(run["bid"]):
            if r.result.type != "succeeded":
                continue
            msg = r.result.message
            u = getattr(msg, "usage", None)
            in_tok += getattr(u, "input_tokens", 0)
            out_tok += getattr(u, "output_tokens", 0)
            ti = next((b.input for b in msg.content if getattr(b, "type", None) == "tool_use"), None)
            if ti is None or r.custom_id not in run["manifest"]:
                continue
            ch = Chunk(**run["manifest"][r.custom_id])
            try:
                mapped, fr = ex.to_contracts(ex.parse_extraction(ti), ch, node_types=node_types,
                                             node_members=node_members, edges=edges)
            except Exception:  # noqa: BLE001 — one quirky result must not sink the sweep
                continue
            for rel in mapped["relationships"]:
                eset.add((rel.src_entity, rel.relation_type, rel.dst_entity, rel.metric))
            n_rel += len(mapped["relationships"])
            n_ent += fr.n_entities
            n_unmapped += len(fr.unmapped_entities)
        cost = (in_tok * ex.PRICE_IN + out_tok * ex.PRICE_OUT) * _BATCH_PRICE
        res[run["label"]] = dict(n_chunks=run["n_chunks"], edges=eset, n_rel=n_rel, n_ent=n_ent,
                                 n_unmapped=n_unmapped, cost=cost)
    _write_sweep(res, len(keys))


def _write_sweep(res: dict, n_docs: int) -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    base = res.get("propositional", {}).get("edges", set())
    lines = ["# GraphRAG chunk-granularity sweep", f"\n{n_docs} doc(s). G1 (propositional) = recall reference.\n",
             "| setting | chunks/doc | relationships | unmapped ent | edge-recall vs G1 | $/doc | proj. corpus $ |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for label, _, _ in _SWEEP_SETTINGS:
        r = res.get(label)
        if not r:
            continue
        cpd = r["n_chunks"] / n_docs
        recall = (len(r["edges"] & base) / len(base)) if base else 1.0
        per_doc = r["cost"] / n_docs
        proj = per_doc * _CORPUS_DOCS
        lines.append(f"| {label} | {cpd:.0f} | {r['n_rel']} | {r['n_unmapped']} | {recall:.0%} | "
                     f"${per_doc:.2f} | ${proj:,.0f} |")
    lines += ["\n**Read:** pick the cheapest setting that holds edge-recall (≥~85%) without an unmapped spike.",
              "Projection assumes these (long) docs' chunks/doc; the corpus average is lower, so real cost is",
              "below the table. Caching is OFF (Batch can't cache); the lever here is chunk count.",
              "Runtime: Anthropic Batch (50% off, durable) recommended over sync+cache (~20% cheaper but loses",
              "Batch's output discount + needs RPM/checkpoint infra)."]
    (_OUT / "sweep_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwrote {_OUT / 'sweep_report.md'}")


# ── DECIDER: full-commodity, multi-era, Sonnet-vs-Opus run that sets the go-forward ──────────────
_COMMODITY_MAP = [
    (("cotton",), "cotton"), (("sugar",), "sugar"), (("coffee", "conab", "fnc"), "coffee"),
    (("cocoa",), "cocoa"), (("orange", "_oj"), "orange_juice"), (("rice",), "rice"),
    (("rapeseed", "canola"), "rapeseed"), (("palm", "mpo"), "palm_oil"),
    (("soybean_meal",), "soybean_meal"), (("soybean_oil",), "soybean_oil"), (("soybean",), "soybeans"),
    (("wheat",), "wheat"), (("corn", "maize", "grain"), "corn_grains"),
    (("wasde", "wap"), "multi_sd"), (("wb_cmo", "cmo"), "macro"),
]
_DECIDER_TARGETS = ["usda_gain_cotton_monthly", "usda_gain_sugar_semiannual", "usda_gain_coffee_semiannual",
                    "conab", "fnc", "usda_gain_grain_monthly", "usda_gain_wheat", "usda_gain_corn",
                    "usda_gain_soybeans", "usda_gain_soybean_meal", "usda_gain_soybean_oil",
                    "usda_gain_rice", "usda_gain_rapeseed", "mpoc", "usda_gain_orange_juice",
                    "usda_gain_cocoa", "wb_cmo_outlook"]


def _commodity_of(source: str) -> str:
    s = source.lower()
    for keys, c in _COMMODITY_MAP:
        if any(k in s for k in keys):
            return c
    return "other"


def _era_of(key: str) -> str:
    y = _year_of(key)
    if y == "unknown":
        return "unknown"
    yi = int(y)
    return "ocr_pre95" if yi < 1995 else "old_95_09" if yi < 2010 else "recent_10plus"


def sample_decider(s3, seed: int) -> list[str]:
    by = collections.defaultdict(list)
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX):
        for o in page.get("Contents", []):
            if o["Key"].endswith("document.json"):
                by[_source_of(o["Key"])].append(o["Key"])
    rng = random.Random(seed)
    picked = []
    for src in _DECIDER_TARGETS:                       # one per commodity domain (shorter variants)
        if by.get(src):
            picked.append(rng.choice(by[src]))
    for src in ("usda_wasde", "usda_wap"):             # deliberate old-era / OCR-era picks
        old = sorted((k for k in by.get(src, []) if _year_of(k) != "unknown" and int(_year_of(k)) < 2000),
                     key=_year_of)
        if old:
            picked.append(old[0])
    return picked


_DECIDER_MAX_PER_DOC = 40   # sample enough/doc to reveal coverage+quality without exhaustive cost


def _build_reqs(s3, keys, model, tag, *, chunker="haiku", block_chars=None, lean=False, max_per_doc=None):
    system = ex.build_system_prompt(lean=lean)
    tool = ex.extraction_tool(lean=lean)
    manifest, reqs = {}, []
    for key in keys:
        commodity, era, src = _commodity_of(_source_of(key)), _era_of(key), _source_of(key)
        chunks = _chunks_for(s3, key, chunker, block_chars, gate=True)
        if max_per_doc:
            chunks = chunks[:max_per_doc]
        for i, ch in enumerate(chunks):
            cid = _custom_id(f"{tag}-{ch.chunk_id}")
            prev = chunks[i - 1].proposition if i > 0 else ""
            nxt = chunks[i + 1].proposition if i < len(chunks) - 1 else ""
            reqs.append({"custom_id": cid, "params": {
                "model": model, "max_tokens": 4096, "system": system,
                "messages": [{"role": "user", "content": ex.build_user_message(prev, ch.proposition, nxt)}],
                "tools": [tool], "tool_choice": {"type": "tool", "name": "emit_extraction"}}})
            manifest[cid] = {"chunk": ch.model_dump(mode="json"), "commodity": commodity, "era": era, "source": src}
    return reqs, manifest


def _collect_decider(client, bid, manifest, model):
    nt, nm, edg = ex.vocab_sets()
    pin, pout = ex.price(model)
    o = dict(edges=set(), per=collections.defaultdict(lambda: [0, 0, 0]), etypes=collections.Counter(),
             events=[], ents=collections.Counter(), unmapped=collections.Counter(),
             dangling=0, fails=0, in_tok=0, out_tok=0)
    for r in client.messages.batches.results(bid):
        if r.result.type != "succeeded":
            o["fails"] += 1
            continue
        msg = r.result.message
        u = getattr(msg, "usage", None)
        o["in_tok"] += getattr(u, "input_tokens", 0)
        o["out_tok"] += getattr(u, "output_tokens", 0)
        ti = next((b.input for b in msg.content if getattr(b, "type", None) == "tool_use"), None)
        m = manifest.get(r.custom_id)
        if ti is None or m is None:
            o["fails"] += 1
            continue
        try:
            mapped, fr = ex.to_contracts(ex.parse_extraction(ti), Chunk(**m["chunk"]),
                                         node_types=nt, node_members=nm, edges=edg)
        except Exception:  # noqa: BLE001
            o["fails"] += 1
            continue
        cell = o["per"][(m["commodity"], m["era"])]
        cell[0] += fr.n_entities
        cell[1] += len(mapped["relationships"])
        cell[2] += len(fr.unmapped_entities)
        o["dangling"] += len(fr.dangling_endpoints)
        for label in fr.unmapped_entities:
            o["unmapped"][label] += 1
        for rel in mapped["relationships"]:
            o["edges"].add((rel.src_entity, rel.relation_type, rel.dst_entity, rel.metric))
            o["etypes"][rel.relation_type] += 1
        for e in mapped["entities"]:
            o["ents"][e.entity_id] += 1
        for ev in mapped["events"]:
            o["events"].append(f"{ev.event_type}@{ev.commodity}/{ev.country}")
    o["cost"] = (o["in_tok"] * pin + o["out_tok"] * pout) * _BATCH_PRICE
    return o


def decider(s3, client, *, seed: int) -> None:
    keys = sample_decider(s3, seed)
    print(f"decider: {len(keys)} docs")
    for k in keys:
        print(f"  {_commodity_of(_source_of(k)):14} {_era_of(k):14} {k}")
    sreqs, smani = _build_reqs(s3, keys, ex.SONNET, "son", max_per_doc=_DECIDER_MAX_PER_DOC)
    sbid = client.messages.batches.create(requests=sreqs).id
    ab_keys = keys[:3]
    oreqs, omani = _build_reqs(s3, ab_keys, ex.MODEL, "opu", max_per_doc=_DECIDER_MAX_PER_DOC)
    obid = client.messages.batches.create(requests=oreqs).id
    print(f"submitted sonnet({len(sreqs)})={sbid}  opus_AB({len(oreqs)})={obid}", flush=True)
    for bid in (sbid, obid):
        while client.messages.batches.retrieve(bid).processing_status != "ended":
            time.sleep(30)
    son = _collect_decider(client, sbid, smani, ex.SONNET)
    opu = _collect_decider(client, obid, omani, ex.MODEL)
    son_ab_only, _ = _ab_edges(client, sbid, smani, ab_keys)   # Sonnet edges restricted to the A/B docs
    _decider_report(son, opu, son_ab_only, keys)


def _ab_edges(client, bid, manifest, ab_keys):
    """Sonnet edges restricted to the A/B docs, to compare like-for-like with the Opus A/B batch."""
    ab_src = {_source_of(k) for k in ab_keys}
    nt, nm, edg = ex.vocab_sets()
    eset = set()
    for r in client.messages.batches.results(bid):
        if r.result.type != "succeeded":
            continue
        m = manifest.get(r.custom_id)
        if not m or m["source"] not in ab_src:
            continue
        ti = next((b.input for b in r.result.message.content if getattr(b, "type", None) == "tool_use"), None)
        if ti is None:
            continue
        try:
            mapped, _ = ex.to_contracts(ex.parse_extraction(ti), Chunk(**m["chunk"]),
                                        node_types=nt, node_members=nm, edges=edg)
        except Exception:  # noqa: BLE001
            continue
        for rel in mapped["relationships"]:
            eset.add((rel.src_entity, rel.relation_type, rel.dst_entity, rel.metric))
    return eset, ab_src


def _decider_report(son, opu, son_ab, keys) -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    n_docs = len(keys)
    # model A/B (same 3 docs): overlap both ways
    o_edges = opu["edges"]
    recall_s_vs_o = len(son_ab & o_edges) / len(o_edges) if o_edges else 0
    recall_o_vs_s = len(son_ab & o_edges) / len(son_ab) if son_ab else 0
    # fragmentation
    ev_total, ev_distinct = len(son["events"]), len(set(son["events"]))
    ent_total = sum(son["ents"].values())
    ent_distinct = len(son["ents"])
    L = ["# GraphRAG DECIDER report", f"\n**{n_docs} docs | broad model=Sonnet 4.6 | A/B vs Opus on 3 docs**\n",
         "## Coverage + generalization (Sonnet, per commodity x era)",
         "| commodity | era | entities | edges | unmapped |", "|---|---|---:|---:|---:|"]
    for (com, era), (e, r, u) in sorted(son["per"].items()):
        L.append(f"| {com} | {era} | {e} | {r} | {u} |")
    L += [f"\n- totals: {ent_total} entities ({ent_distinct} distinct), {len(son['edges'])} unique edges, "
          f"{ev_total} events, dangling={son['dangling']}, fails={son['fails']}",
          f"- **cost: Sonnet ${son['cost']:.2f} for {n_docs} docs**  (Opus A/B 3 docs ${opu['cost']:.2f})",
          "\n## Model A/B (same 3 docs)",
          f"- Sonnet edges {len(son_ab)} vs Opus edges {len(o_edges)} | overlap: "
          f"Sonnet recovers {recall_s_vs_o:.0%} of Opus's, Opus recovers {recall_o_vs_s:.0%} of Sonnet's",
          "\n## Fragmentation (Phase-4 normalization scope)",
          f"- events: {ev_total} total -> {ev_distinct} distinct ({ev_total - ev_distinct} dup mentions to canonicalize)",
          f"- entity instances: {ent_total} -> {ent_distinct} distinct (dup-rate {1 - ent_distinct / max(ent_total,1):.0%})",
          "- edge-type distribution: " + ", ".join(f"{t}={n}" for t, n in son["etypes"].most_common()),
          "\n## Top unmapped (per-commodity vocab gaps)"]
    L += [f"- {n}x `{e}`" for e, n in son["unmapped"].most_common(25)] or ["- none"]
    (_OUT / "decider_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L), flush=True)
    print(f"\nwrote {_OUT / 'decider_report.md'}", flush=True)


def dry_decider(s3, *, seed: int) -> None:
    keys = sample_decider(s3, seed)
    sys_chars = len(ex.build_system_prompt())
    by_com, total = collections.Counter(), 0
    for k in keys:
        by_com[_commodity_of(_source_of(k))] += 1
        prop_est = len(_chunks_for(s3, k, "deterministic", 1500, gate=True)) * 10  # propositional ~10x det_1500
        total += min(prop_est, _DECIDER_MAX_PER_DOC)                                # capped per doc
    sp_in, sp_out = ex.price(ex.SONNET)
    est = (total * (sys_chars // 4 + 170) * sp_in + total * 500 * sp_out) * _BATCH_PRICE
    print(f"decider docs ({len(keys)}): {dict(by_com)}")
    print(f"[dry-run] ~{total} chunks (capped {_DECIDER_MAX_PER_DOC}/doc), est Sonnet ${est:.2f} "
          f"+ ~${est * 3 / len(keys):.2f} Opus A/B. No API calls.")


# ── VALIDATION: does det_1000+lean keep propositional's salient edges? (production go/no-go) ──────
# Production config (documented; run via the deferred full extraction, not here):
#   --model sonnet --chunker deterministic --block-chars 1000 --lean  (+ waste gates on)
_VALIDATE_SOURCES = ["usda_gain_cotton_monthly", "usda_gain_grain_monthly", "usda_gain_sugar_semiannual"]


def _sample_validate(s3, seed: int) -> list[str]:
    by = collections.defaultdict(list)
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX):
        for o in page.get("Contents", []):
            if o["Key"].endswith("document.json"):
                by[_source_of(o["Key"])].append(o["Key"])
    rng = random.Random(seed)
    return [rng.choice(by[s]) for s in _VALIDATE_SOURCES if by.get(s)]


def _collect_edges(client, bid, manifest, model):
    nt, nm, edg = ex.vocab_sets()
    pin, pout = ex.price(model)
    eset, in_tok, out_tok = set(), 0, 0
    for r in client.messages.batches.results(bid):
        if r.result.type != "succeeded":
            continue
        u = getattr(r.result.message, "usage", None)
        in_tok += getattr(u, "input_tokens", 0)
        out_tok += getattr(u, "output_tokens", 0)
        ti = next((b.input for b in r.result.message.content if getattr(b, "type", None) == "tool_use"), None)
        m = manifest.get(r.custom_id)
        if ti is None or m is None:
            continue
        try:
            mapped, _ = ex.to_contracts(ex.parse_extraction(ti), Chunk(**m["chunk"]),
                                        node_types=nt, node_members=nm, edges=edg)
        except Exception:  # noqa: BLE001
            continue
        for rel in mapped["relationships"]:
            eset.add((rel.src_entity, rel.relation_type, rel.dst_entity, rel.metric))
    return eset, (in_tok * pin + out_tok * pout) * _BATCH_PRICE


def validate(s3, client, *, seed: int) -> None:
    keys = _sample_validate(s3, seed)
    print(f"validate on {len(keys)} docs: {[_source_of(k) for k in keys]}")
    preqs, pmani = _build_reqs(s3, keys, ex.SONNET, "P", chunker="haiku", lean=True)
    pbid = client.messages.batches.create(requests=preqs).id
    dreqs, dmani = _build_reqs(s3, keys, ex.SONNET, "D", chunker="deterministic", block_chars=1000, lean=True)
    dbid = client.messages.batches.create(requests=dreqs).id
    print(f"submitted P(propositional {len(preqs)})={pbid}  D(det_1000 {len(dreqs)})={dbid}", flush=True)
    for bid in (pbid, dbid):
        while client.messages.batches.retrieve(bid).processing_status != "ended":
            time.sleep(30)
    P, pcost = _collect_edges(client, pbid, pmani, ex.SONNET)
    D, dcost = _collect_edges(client, dbid, dmani, ex.SONNET)
    _validate_report(P, D, pcost, dcost, keys)


def _validate_report(P, D, pcost, dcost, keys) -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    recall = len(D & P) / len(P) if P else 0.0
    fmt = lambda e: f"{e[0]} -{e[1]}({e[3] or '-'})-> {e[2]}"   # noqa: E731
    keyf = lambda e: tuple(str(x) for x in e)                   # noqa: E731 — metric can be None
    missed = [fmt(e) for e in sorted(P - D, key=keyf)]
    extra = [fmt(e) for e in sorted(D - P, key=keyf)]
    L = ["# Chunking validation — det_1000+lean vs propositional (both Sonnet+lean)",
         f"\n{len(keys)} docs: {[_source_of(k) for k in keys]}",
         f"- **P (propositional)** = {len(P)} edges, ${pcost:.2f}",
         f"- **D (det_1000)** = {len(D)} edges, ${dcost:.2f}",
         f"- **edge-recall D vs P = {recall:.0%}**  (corpus would be ~9x cheaper at D granularity)",
         f"\n## Edges P found but D MISSED ({len(missed)}) — judge: salient cascade or footnote?"]
    L += missed or ["- none"]
    L += [f"\n## D-only edges ({len(extra)}) — coarse found, propositional didn't:"]
    L += extra or ["- none"]
    (_OUT / "validation_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L), flush=True)
    print(f"\nwrote {_OUT / 'validation_report.md'}", flush=True)


def dry_validate(s3, *, seed: int) -> None:
    keys = _sample_validate(s3, seed)
    sysl = len(ex.build_system_prompt(lean=True))
    d_ch = sum(len(_chunks_for(s3, k, "deterministic", 1000, gate=True)) for k in keys)
    p_est = d_ch * 10                                      # propositional ~10x det_1000
    sp_in, sp_out = ex.price(ex.SONNET)
    est = ((p_est + d_ch) * (sysl // 4 + 170) * sp_in + (p_est + d_ch) * 450 * sp_out) * _BATCH_PRICE
    print(f"validate docs: {[_source_of(k) for k in keys]}")
    print(f"[dry-run] det_1000 ~{d_ch} chunks + propositional ~{p_est} chunks (both Sonnet+lean), "
          f"est ${est:.2f}. No API calls.")


# ── MINI-BATCH TEST: does K props/request preserve cascades while amortizing the prefix? ──────────
# The prefix (~2.3K lean tok) is re-paid per chunk and is uncacheable in Batch. Sending K propositions
# per request pays it ~1/K×. The risk is that batching degrades extraction (blob-of-props loses edges),
# so the test scores by the END GOAL: cascade-edge recall + multi-hop-chain preservation vs the K=1 arm.
_MINIBATCH_SOURCES = ["usda_gain_soybean_meal", "usda_gain_coffee_semiannual"]  # crush cascade + weather→price
MINIBATCH_MAX_PER_DOC = 120        # bound cost; shared first-N props so every arm sees identical inputs
_PROP_OUT_TOK = 450                # per-proposition output estimate for the dry-run


def _sample_minibatch(s3, seed: int) -> list[str]:
    """2 content-rich docs, different commodity complexes — enough multi-hop narrative to form chains."""
    by = collections.defaultdict(list)
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX):
        for o in page.get("Contents", []):
            if o["Key"].endswith("document.json"):
                by[_source_of(o["Key"])].append(o["Key"])
    rng = random.Random(seed)
    picked = [rng.choice(by[s]) for s in _MINIBATCH_SOURCES if by.get(s)]
    for src, keys in by.items():                       # backfill to 2 distinct sources if a target is absent
        if len(picked) >= 2:
            break
        if all(_source_of(p) != src for p in picked) and keys:
            picked.append(rng.choice(keys))
    return picked[:2]


def _build_minibatch_reqs(chunks_by_key, model, tag, *, k, lean=True):
    """Arm builder. k==1 = the reference path (one request/prop, emit_extraction, prev/next context).
    k>1 = consecutive props grouped into one mini-batch request (emit_minibatch_extraction). The SAME
    pre-chunked props feed every arm, so K is the only variable. manifest[cid] = the group's chunks."""
    system = ex.build_system_prompt(lean=lean)
    manifest, reqs = {}, []
    if k == 1:
        tool = ex.extraction_tool(lean=lean)
        for chunks in chunks_by_key.values():
            for i, ch in enumerate(chunks):
                cid = _custom_id(f"{tag}-{ch.chunk_id}")
                prev = chunks[i - 1].proposition if i > 0 else ""
                nxt = chunks[i + 1].proposition if i < len(chunks) - 1 else ""
                reqs.append({"custom_id": cid, "params": {
                    "model": model, "max_tokens": 4096, "system": system,
                    "messages": [{"role": "user", "content": ex.build_user_message(prev, ch.proposition, nxt)}],
                    "tools": [tool], "tool_choice": {"type": "tool", "name": "emit_extraction"}}})
                manifest[cid] = {"chunks": [ch.model_dump(mode="json")]}
    else:
        tool = ex.minibatch_extraction_tool(lean=lean)
        for chunks in chunks_by_key.values():
            for start in range(0, len(chunks), k):
                grp = chunks[start:start + k]
                prev = chunks[start - 1].proposition if start > 0 else ""
                nxt = chunks[start + k].proposition if start + k < len(chunks) else ""
                cid = _custom_id(f"{tag}-{grp[0].chunk_id}-g{len(grp)}")
                msg = ex.build_minibatch_message([c.proposition for c in grp], prev=prev, next=nxt)
                reqs.append({"custom_id": cid, "params": {
                    "model": model, "max_tokens": 8192, "system": system,
                    "messages": [{"role": "user", "content": msg}],
                    "tools": [tool], "tool_choice": {"type": "tool", "name": "emit_minibatch_extraction"}}})
                manifest[cid] = {"chunks": [c.model_dump(mode="json") for c in grp]}
    return reqs, manifest


def _two_hop_chains(cascade: set) -> set:
    """All a→b→c chains over PROPAGATING edges (shared middle b, a≠c) — the multi-hop scaffolding the
    graph exists to support. A chain = (a, r1, b, r2, c)."""
    by_src = collections.defaultdict(list)
    for (s, rt, d, _m) in cascade:
        by_src[s].append((rt, d))
    chains = set()
    for (s, rt, d, _m) in cascade:
        for (rt2, c) in by_src.get(d, []):
            if c != s:
                chains.add((s, rt, d, rt2, c))
    return chains


def _collect_minibatch(client, bid, manifest, model, k):
    """Map an arm's results → (collapsed) edge set, cascade subset, 2-hop chain set, cost, prop count."""
    nt, nm, edg = ex.vocab_sets()
    pin, pout = ex.price(model)
    rels, in_tok, out_tok, fails, n_props = [], 0, 0, 0, 0
    for r in client.messages.batches.results(bid):
        if r.result.type != "succeeded":
            fails += 1
            continue
        msg = r.result.message
        u = getattr(msg, "usage", None)
        in_tok += getattr(u, "input_tokens", 0)
        out_tok += getattr(u, "output_tokens", 0)
        ti = next((b.input for b in msg.content if getattr(b, "type", None) == "tool_use"), None)
        m = manifest.get(r.custom_id)
        if ti is None or m is None:
            fails += 1
            continue
        chunks = [Chunk(**c) for c in m["chunks"]]
        if k == 1:
            try:
                mapped, _ = ex.to_contracts(ex.parse_extraction(ti), chunks[0],
                                            node_types=nt, node_members=nm, edges=edg)
                rels += mapped["relationships"]
                n_props += 1
            except Exception:  # noqa: BLE001 — one quirky result must not sink the arm
                fails += 1
        else:
            seen = set()
            for idx, x in ex.parse_minibatch(ti):
                if not (1 <= idx <= len(chunks)) or idx in seen:
                    continue
                seen.add(idx)
                try:
                    mapped, _ = ex.to_contracts(x, chunks[idx - 1], node_types=nt, node_members=nm, edges=edg)
                    rels += mapped["relationships"]
                except Exception:  # noqa: BLE001
                    fails += 1
            n_props += len(seen)
            fails += len(chunks) - len(seen)            # propositions the model failed to return
    collapsed = ex.collapse_reference_edges(rels)
    edges = {(r.src_entity, r.relation_type, r.dst_entity, r.metric) for r in collapsed}
    cascade = {e for e in edges if ex._edge_class(e[1]) == "propagating"}
    cost = (in_tok * pin + out_tok * pout) * _BATCH_PRICE
    return dict(edges=edges, cascade=cascade, chains=_two_hop_chains(cascade), cost=cost,
                n_props=n_props, n_reqs=len(manifest), fails=fails)


def _minibatch_report(arms: dict, ref_label: str, keys, ks) -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    fmt_e = lambda e: f"{e[0]} -{e[1]}({e[3] or '-'})-> {e[2]}"        # noqa: E731
    fmt_c = lambda c: f"{c[0]} ={c[1]}=> {c[2]} ={c[3]}=> {c[4]}"      # noqa: E731
    ek = lambda e: tuple(str(x) for x in e)                            # noqa: E731 — metric can be None
    ref = arms[ref_label]
    L = ["# Mini-batch test — does K props/request preserve cascades while amortizing the prefix?",
         f"\n{len(keys)} docs: {[_source_of(k) for k in keys]} | all arms Sonnet+lean+fixes | "
         f"reference = {ref_label}\n",
         "| arm | reqs | props | edges | cascade | chains | cost | $/prop | proj corpus $ | "
         "cascade-recall | chain-recall |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k in ks:
        lab = f"k{k}"
        a = arms.get(lab)
        if not a:
            continue
        dpp = a["cost"] / a["n_props"] if a["n_props"] else 0.0
        proj = (a["cost"] / len(keys)) * _CORPUS_DOCS if keys else 0.0
        is_ref = lab == ref_label
        cr = len(a["cascade"] & ref["cascade"]) / len(ref["cascade"]) if ref["cascade"] else 1.0
        hr = len(a["chains"] & ref["chains"]) / len(ref["chains"]) if ref["chains"] else 1.0
        L.append(f"| {lab}{' (ref)' if is_ref else ''} | {a['n_reqs']} | {a['n_props']} | {len(a['edges'])} | "
                 f"{len(a['cascade'])} | {len(a['chains'])} | ${a['cost']:.2f} | ${dpp:.4f} | ${proj:,.0f} | "
                 f"{'—' if is_ref else f'{cr:.0%}'} | {'—' if is_ref else f'{hr:.0%}'} |")
    for k in [x for x in ks if f"k{x}" != ref_label]:
        a = arms.get(f"k{k}")
        if not a:
            continue
        miss_c = [fmt_e(e) for e in sorted(ref["cascade"] - a["cascade"], key=ek)]
        miss_h = [fmt_c(c) for c in sorted(ref["chains"] - a["chains"], key=ek)]
        L += [f"\n## K={k}: cascade edges the reference found but K={k} MISSED ({len(miss_c)}) — salient or footnote?"]
        L += miss_c or ["- none"]
        L += [f"\n## K={k}: multi-hop chains MISSED ({len(miss_h)}) — the cascade-reasoning loss"]
        L += [f"- {c}" for c in miss_h] or ["- none"]
    L += ["\n**Verdict:** ship mini-batch at the largest K with cascade-recall >=~90% AND chain-recall "
          ">=~90% AND $/prop well below the reference. K=10 -> K=5 fallback; if both fail, keep K=1 and "
          "prioritize the run.",
          "\nLimits: 2 docs, a 2-hop proxy for multi-hop, and K>1 props see batch-mates as context (a real",
          "production property of the mini-batch arm, not matched away)."]
    (_OUT / "minibatch_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L), flush=True)
    print(f"\nwrote {_OUT / 'minibatch_report.md'}", flush=True)


def minibatch_test(s3, client, *, seed: int, ks: list[int]) -> None:
    keys = _sample_minibatch(s3, seed)
    print(f"minibatch test on {len(keys)} docs: {[_source_of(k) for k in keys]} | K={ks}")
    chunks_by_key = {}                                  # chunk ONCE (Haiku) → identical props for every arm
    for key in keys:
        chs = _chunks_for(s3, key, "haiku", gate=True)[:MINIBATCH_MAX_PER_DOC]
        chunks_by_key[key] = chs
        print(f"  {_source_of(key)}: {len(chs)} props (capped {MINIBATCH_MAX_PER_DOC})")
    runs = []
    for k in ks:
        reqs, mani = _build_minibatch_reqs(chunks_by_key, ex.SONNET, f"k{k}", k=k)
        bid = client.messages.batches.create(requests=reqs).id
        runs.append((k, bid, mani))
        print(f"  submitted k{k}: {len(reqs)} requests -> {bid}", flush=True)
    for _, bid, _ in runs:
        while client.messages.batches.retrieve(bid).processing_status != "ended":
            time.sleep(30)
    arms = {f"k{k}": _collect_minibatch(client, bid, mani, ex.SONNET, k) for k, bid, mani in runs}
    _minibatch_report(arms, f"k{min(ks)}", keys, ks)    # smallest K (=1) is the reference


def dry_minibatch(s3, *, seed: int, ks: list[int]) -> None:
    keys = _sample_minibatch(s3, seed)
    sysl = len(ex.build_system_prompt(lean=True))
    props = sum(min(len(_chunks_for(s3, k, "deterministic", 1000, gate=True)) * 10, MINIBATCH_MAX_PER_DOC)
                for k in keys)                          # det proxy ×10 ≈ propositional, capped (no Haiku spend)
    sp_in, sp_out = ex.price(ex.SONNET)
    pre = sysl // 4 + 170                               # lean prefix tokens (system + tool + framing)
    print(f"minibatch docs: {[_source_of(k) for k in keys]} | ~{props} props (det proxy)")
    total = 0.0
    for k in ks:
        n_reqs = props if k == 1 else -(-props // k)    # ceil
        in_tok = n_reqs * pre + props * 40              # prefix per request + ~40 tok/prop text
        out_tok = props * _PROP_OUT_TOK
        c = (in_tok * sp_in + out_tok * sp_out) * _BATCH_PRICE
        total += c
        print(f"  [dry] k{k}: ~{n_reqs} requests, est ${c:.2f}")
    print(f"[dry-run] total est ${total:.2f} (Sonnet+lean, Batch -50%). No API calls.")


def main() -> int:
    ap = argparse.ArgumentParser(description="GraphRAG cloud Batch extraction.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--submit", action="store_true")
    g.add_argument("--retrieve", metavar="BATCH_ID")
    g.add_argument("--run", action="store_true")
    g.add_argument("--diagnose", metavar="BATCH_ID")
    g.add_argument("--sweep", action="store_true", help="chunk-granularity recall-vs-cost experiment")
    g.add_argument("--decider", action="store_true", help="full-commodity, multi-era, Sonnet-vs-Opus run")
    g.add_argument("--validate", action="store_true", help="det_1000+lean vs propositional edge-recall check")
    g.add_argument("--minibatch-test", action="store_true",
                   help="K props/request vs K=1: cascade + multi-hop-chain preservation at lower $/prop")
    ap.add_argument("--dry-run", action="store_true", help="estimate only, no API calls")
    ap.add_argument("--docs", type=int, default=1, help="docs for --sweep")
    ap.add_argument("--ks", default="1,5,10", help="comma-separated K values for --minibatch-test")
    ap.add_argument("--seed", type=int, default=20260621)
    ap.add_argument("--chunker", choices=["haiku", "deterministic"], default="haiku")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()

    ks = [int(x) for x in args.ks.split(",") if x.strip()]
    _load_env()
    s3 = boto3.client("s3", region_name=args.region)
    if args.dry_run:                                   # estimate-only paths need no API client
        if args.minibatch_test:
            dry_minibatch(s3, seed=args.seed, ks=ks)
        else:
            dry = dry_decider if args.decider else dry_validate if args.validate else dry_run
            dry(s3, seed=args.seed)
        return 0
    import anthropic
    client = anthropic.Anthropic(api_key=_api_key())
    if args.minibatch_test:
        minibatch_test(s3, client, seed=args.seed, ks=ks)
    elif args.decider:
        decider(s3, client, seed=args.seed)
    elif args.validate:
        validate(s3, client, seed=args.seed)
    elif args.submit:
        submit(s3, client, seed=args.seed, chunker=args.chunker)
    elif args.retrieve:
        retrieve(s3, client, args.retrieve)
    elif args.diagnose:
        diagnose(s3, client, args.diagnose)
    elif args.sweep:
        sweep(s3, client, seed=args.seed, n_docs=args.docs)
    elif args.run:
        retrieve(s3, client, submit(s3, client, seed=args.seed, chunker=args.chunker))
    else:
        ap.error("choose an action: --submit/--retrieve/--run/--diagnose/--sweep/--decider (or --dry-run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
