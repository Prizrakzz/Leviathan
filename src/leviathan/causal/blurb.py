"""W1.5 blurb pipeline — <=15-word plain-English hover tooltips, COMPRESSED from the curated mechanisms.

The map's hover already renders `mechanism` (median 19 words, register-heavy in places); a blurb is a
shorter, jargon-free line for the same edge. This module is the whole draft -> ratify -> apply loop:

    python -m leviathan.causal.blurb --dry-run          # free: target tally + cost estimate + sample prompt
    python -m leviathan.causal.blurb --submit           # BILLED (~$0.15): one Haiku Message-Batches request
    python -m leviathan.causal.blurb --retrieve <bid>   # poll + write pilot/blurb_drafts.json + review .md
    python -m leviathan.causal.blurb --apply            # after HUMAN ratification: archive YAMLs, set blurbs

Design decisions (PHASE8_P1_PLAN.md):
  * PER-TARGET requests (one edge per request, max_tokens=64), NOT per-contract JSON blobs — the mini-batch
    extraction test showed models reorder/drop items in an array; one-request-one-answer can't misalign.
  * custom_id = b{i:05d} + a manifest file (the Batch API id pattern ^[A-Za-z0-9_-]{1,64}$ bans ':', so the
    readable `contract::driver` form is illegal — same convention as evidence_batch).
  * The word cap is enforced at REVIEW + config_check, never silently truncated here: an over-limit draft is
    flagged in the review .md and SKIPPED by --apply unless hand-edited down.
  * --apply is idempotent (re-running sets the same values) and additive-only (cs.dump exclude_none omits
    unset blurbs, so untouched edges leave no YAML churn).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from leviathan.causal import schema as cs
from leviathan.causal import validate as cval

_CAUSAL_DIR = cval._CAUSAL_DIR
_PILOT = cval._OUT
_BATCH_FILE = _PILOT / "blurb_batch.json"          # {bid, manifest} — survives the laptop across submit->retrieve
_DRAFTS_FILE = _PILOT / "blurb_drafts.json"        # the ratification surface
_REVIEW_FILE = _PILOT / "blurb_review.md"

MODEL = "claude-haiku-4-5"
MAX_WORDS = 18   # ratified 2026-07-09: 15 -> 18 (the 16-18w drafts read well; >18 skipped = the truncation band)

_SYSTEM = (
    "You compress causal-mechanism sentences into hover tooltips for a commodity-markets graph UI. "
    f"Rewrite the given mechanism as ONE plain-English fragment of AT MOST {MAX_WORDS} words. "
    "Rules: no underscores, no identifiers, no jargon or internal codes; keep the causal direction; "
    "a sentence fragment is fine; do not add facts that are not in the mechanism. "
    "Output ONLY the tooltip text — no quotes, no preamble."
)


def _targets() -> list[dict]:
    """Every blurb-eligible edge across the 33 YAMLs, in a stable order: drivers first, then inter-commodity.
    An edge qualifies if it has mechanism text to compress and no blurb yet (idempotent re-drafts skip done)."""
    out = []
    for p in sorted(_CAUSAL_DIR.glob("*.yaml")):
        c = cs.load(p)
        for d in c.drivers:
            if d.mechanism and not d.blurb:
                out.append({"contract": c.contract, "kind": "driver", "id": d.id, "mechanism": d.mechanism})
        for e in c.inter_commodity:
            if e.mechanism and not e.blurb:
                out.append({"contract": c.contract, "kind": "inter", "id": e.driver_commodity,
                            "relation": e.relation, "mechanism": e.mechanism})
    return out


def _request(i: int, t: dict) -> dict:
    return {"custom_id": f"b{i:05d}", "params": {
        "model": MODEL, "max_tokens": 64,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": t["mechanism"]}],
    }}


def dry_run() -> int:
    ts = _targets()
    drivers = sum(1 for t in ts if t["kind"] == "driver")
    inter = len(ts) - drivers
    in_tok = sum(len(t["mechanism"].split()) for t in ts) * 1.4 + len(ts) * len(_SYSTEM.split()) * 1.4
    out_tok = len(ts) * 30
    cost = (in_tok / 1e6) * 0.50 + (out_tok / 1e6) * 2.50          # Haiku batch pricing (50% off list)
    print(f"targets: {len(ts)} ({drivers} driver edges + {inter} inter-commodity)")
    print(f"est cost: ${cost:.2f} (input ~{int(in_tok/1000)}K tok, output ~{int(out_tok/1000)}K tok, batch rate)")
    if ts:
        print("sample prompt:")
        print("  SYSTEM: " + _SYSTEM[:120] + "...")
        print("  USER:   " + ts[0]["mechanism"][:120])
    return 0


def submit() -> int:
    import anthropic
    from leviathan.graphrag import batch_extract as bx
    bx._load_env()                                                  # .env -> ANTHROPIC_API (bx reads repo root)
    ts = _targets()
    if not ts:
        print("nothing to draft (all eligible edges already have blurbs)")
        return 0
    requests = [_request(i, t) for i, t in enumerate(ts)]
    manifest = {r["custom_id"]: t for r, t in zip(requests, ts)}
    client = anthropic.Anthropic(api_key=bx._api_key())
    bid = client.messages.batches.create(requests=requests).id
    _PILOT.mkdir(parents=True, exist_ok=True)
    _BATCH_FILE.write_text(json.dumps({"bid": bid, "manifest": manifest}, indent=1), encoding="utf-8")
    print(f"submitted batch {bid} ({len(requests)} requests) -> {_BATCH_FILE}")
    print(f"next: python -m leviathan.causal.blurb --retrieve {bid}")
    return 0


def retrieve(bid: str, poll_s: int = 20) -> int:
    import anthropic
    from leviathan.graphrag import batch_extract as bx
    bx._load_env()
    saved = json.loads(_BATCH_FILE.read_text(encoding="utf-8"))
    if saved.get("bid") != bid:
        print(f"WARNING: {_BATCH_FILE} holds bid {saved.get('bid')}, not {bid} - using its manifest anyway")
    manifest = saved["manifest"]
    client = anthropic.Anthropic(api_key=bx._api_key())
    while True:
        b = client.messages.batches.retrieve(bid)
        if b.processing_status == "ended":
            break
        print(f"  batch {b.processing_status}; polling again in {poll_s}s")
        time.sleep(poll_s)
    drafts, failed = [], 0
    for r in client.messages.batches.results(bid):
        m = manifest.get(r.custom_id)
        if m is None:
            continue
        if getattr(r.result, "type", None) != "succeeded":
            failed += 1
            continue
        text = "".join(bk.text for bk in r.result.message.content if getattr(bk, "type", "") == "text").strip()
        words = len(text.split())
        drafts.append({**m, "blurb": text, "words": words, "over_limit": words > MAX_WORDS})
    drafts.sort(key=lambda d: (d["contract"], d["kind"], d["id"]))
    _DRAFTS_FILE.write_text(json.dumps(drafts, indent=1, ensure_ascii=False), encoding="utf-8")
    over = [d for d in drafts if d["over_limit"]]
    L = ["# Blurb drafts - ratification surface (W1.5)",
         f"\n{len(drafts)} drafts | {len(over)} over the {MAX_WORDS}-word cap (marked, SKIPPED by --apply "
         "unless hand-edited in blurb_drafts.json) | {f} failed requests\n".replace("{f}", str(failed))]
    cur = None
    for d in drafts:
        if d["contract"] != cur:
            cur = d["contract"]
            L.append(f"\n## {cur}\n")
        flag = "  **OVER-LIMIT**" if d["over_limit"] else ""
        L.append(f"- `{d['id']}` ({d['kind']}){flag}\n  - was: {d['mechanism']}\n  - blurb: **{d['blurb']}**")
    _REVIEW_FILE.write_text("\n".join(L), encoding="utf-8")
    print(f"drafts -> {_DRAFTS_FILE}  ({len(drafts)} ok, {len(over)} over-limit, {failed} failed)")
    print(f"review -> {_REVIEW_FILE}")
    return 0


def apply() -> int:
    drafts = json.loads(_DRAFTS_FILE.read_text(encoding="utf-8"))
    by_key = {}
    skipped = 0
    for d in drafts:
        if len(d["blurb"].split()) > MAX_WORDS:                     # re-check: hand-edits may have fixed it
            skipped += 1
            continue
        by_key[(d["contract"], d["kind"], d["id"])] = d["blurb"]
    # safety archive BEFORE any write (git can't help - the dir is gitignored)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    arch = _PILOT / f"blurb_archive_{ts}"
    arch.mkdir(parents=True, exist_ok=True)
    for p in sorted(_CAUSAL_DIR.glob("*.yaml")):
        shutil.copy2(p, arch / p.name)
    applied = 0
    for p in sorted(_CAUSAL_DIR.glob("*.yaml")):
        c = cs.load(p)
        changed = False
        for d in c.drivers:
            b = by_key.get((c.contract, "driver", d.id))
            if b and d.blurb != b:
                d.blurb = b
                changed = True
                applied += 1
        for e in c.inter_commodity:
            b = by_key.get((c.contract, "inter", e.driver_commodity))
            if b and e.blurb != b:
                e.blurb = b
                changed = True
                applied += 1
        if changed:
            c2 = cs.CausalContract.model_validate(c.model_dump())   # revalidate before any byte hits disk
            cs.dump(c2, p)
    print(f"applied {applied} blurbs ({skipped} over-limit skipped); YAML archive -> {arch}")
    print("NEXT: diff-review the apply (every changed line must be an additive 'blurb:' line):")
    print(f"  diff -r {arch} {_CAUSAL_DIR}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Blurb pipeline: draft (Haiku batch) -> ratify -> apply")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--submit", action="store_true")
    g.add_argument("--retrieve", metavar="BID")
    g.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.dry_run:
        return dry_run()
    if a.submit:
        return submit()
    if a.retrieve:
        return retrieve(a.retrieve)
    return apply()


if __name__ == "__main__":
    sys.exit(main())
