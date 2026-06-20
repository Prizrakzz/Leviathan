"""GraphRAG Phase 1 W1 — corpus reconnaissance over the ``text/`` layer.

Read-only, CPU-only (no LLM spend). Profiles what the GraphRAG corpus actually *is* —
document counts + content volume per source, expected language, sparse-source flags, and
candidate entity surface forms — so the entity vocabulary and gold sets (W3/W6) are
*grounded in reality, not invented*. The output is the corpus's composition → treated as
private IP, written to the git-ignored ``docs/graphrag/corpus_profile/``.

    python -m leviathan.graphrag.corpus_recon --sample 8
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import boto3

BUCKET = "leviathan-dev-shahem-001"
TEXT_PREFIX = "text/"
OUT_DIR = Path(__file__).resolve().parents[3] / "docs" / "graphrag" / "corpus_profile"

# Known source → (commodity group, expected original language). Grounds the language router
# and the sparse-commodity check; refined as W3 proceeds.
SOURCE_META = {
    "conab": ("coffee/grains (BR)", "pt"),
    "fnc": ("coffee (CO)", "es"),
    "mpob": ("palm_oil (MY)", "en"),
    "mpoc": ("palm_oil (MY)", "en"),
    "usda_fas_coffee_wmt": ("coffee", "en"),
    "usda_wap": ("grains/oilseeds (world)", "en"),
    "usda_wasde": ("grains/oilseeds (world)", "en"),
    "wb_cmo_outlook": ("macro/prices", "en"),
}
_GAIN_LANG = "en"  # USDA GAIN attaché reports are English regardless of country

_CAP_PHRASE = re.compile(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,2})\b")
_STOP = {"The", "This", "That", "United States", "Source", "Table", "Figure", "Note"}


def _source_of(key: str) -> str:
    m = re.search(r"text/source=([^/]+)/", key)
    return m.group(1) if m else "unknown"


def _expected_lang(source: str) -> str:
    if source.startswith("usda_gain"):
        return _GAIN_LANG
    return SOURCE_META.get(source, ("?", "en"))[1]


def main() -> None:
    ap = argparse.ArgumentParser(description="GraphRAG corpus reconnaissance (W1).")
    ap.add_argument("--sample", type=int, default=8, help="docs sampled per source for content stats")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()
    s3 = boto3.client("s3", region_name=args.region)
    paginator = s3.get_paginator("list_objects_v2")

    # 1) per-source document counts (cheap list calls)
    counts: dict[str, int] = collections.Counter()
    sample_keys: dict[str, list[str]] = collections.defaultdict(list)
    for page in paginator.paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX):
        for o in page.get("Contents", []):
            k = o["Key"]
            if not k.endswith("document.json"):
                continue
            src = _source_of(k)
            counts[src] += 1
            if len(sample_keys[src]) < args.sample:
                sample_keys[src].append(k)

    # 2) sample content per source → length stats + candidate surface forms
    per_source = {}
    surface = collections.Counter()
    for src, keys in sample_keys.items():
        lengths, langs_seen = [], set()
        for k in keys:
            try:
                doc = json.loads(s3.get_object(Bucket=BUCKET, Key=k)["Body"].read())
            except Exception:
                continue
            txt = doc.get("full_text") or ""
            lengths.append(len(txt))
            for ph in _CAP_PHRASE.findall(txt[:20000]):
                if ph not in _STOP and len(ph) > 3:
                    surface[ph] += 1
        per_source[src] = {
            "docs": counts[src],
            "expected_lang": _expected_lang(src),
            "sampled": len(lengths),
            "avg_chars": int(sum(lengths) / len(lengths)) if lengths else 0,
            "commodity_group": (SOURCE_META.get(src, (None, None))[0]
                                or ("gain:" + src.replace("usda_gain_", ""))),
        }

    total_docs = sum(counts.values())
    sparse = sorted([s for s, n in counts.items() if n < 20])
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_documents": total_docs,
        "n_sources": len(counts),
        "sparse_sources_lt20": sparse,
        "per_source": dict(sorted(per_source.items(), key=lambda kv: -kv[1]["docs"])),
        "top_surface_forms": surface.most_common(60),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "corpus_profile.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # human summary
    lines = [f"# GraphRAG corpus profile  ({report['generated_at'][:10]})",
             f"\n**{total_docs} docs across {len(counts)} sources.** "
             f"Sparse (<20 docs): {', '.join(sparse) or 'none'}\n",
             "| source | docs | exp.lang | avg chars (sampled) | commodity group |",
             "|---|---:|---|---:|---|"]
    for s, d in report["per_source"].items():
        lines.append(f"| {s} | {d['docs']} | {d['expected_lang']} | {d['avg_chars']:,} | {d['commodity_group']} |")
    lines.append("\n**Top candidate surface forms (vocab seed):** "
                 + ", ".join(f"{t}({n})" for t, n in report["top_surface_forms"][:40]))
    (OUT_DIR / "corpus_profile.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"total_docs={total_docs}  sources={len(counts)}  sparse={sparse}")
    print(f"wrote {OUT_DIR / 'corpus_profile.md'}")


if __name__ == "__main__":
    main()
