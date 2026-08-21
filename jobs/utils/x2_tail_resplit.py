"""The X2 truncated-window RETRY TAIL — the (A)-batch item (i) runner (2026-08-21).

THE TAIL, MEASURED (write_manifest_retrieve_20260820T073402Z.json): exactly 2,062 of 16,437 X2
windows were billed and produced NO props even after the inline one-shot split retry — 2,054
truncated at the 4,096 ceiling (BOTH halves failed too), 8 unparseable-twice. 440 docs, 86%
usda_wasde — the dense-table class. The ratified decision rule (truncated>25% fired) authorizes
an 8,192 output ceiling FOR THIS TAIL ONLY; evidence_batch._MAX_OUTPUT_TOKENS stays 4,096 for
every standing pass (its :41 comment's cost-shape argument still holds at the 13k-request scale).

WHY THIS FILE EXISTS: evidence_batch has NO mode that consumes a retrieve manifest's lost ids
(--no-retry-lost is the opposite lever), and its --retrieve path lands props through
_write_doc_cache, a WHOLESALE per-doc overwrite — running it against a tail batch would either
refuse (G1a vintage guard: today's chunk_version != the X2 vintage) or, with --rechunk, DESTROY
the 348,441 cached props on the 440 docs. So this runner submits fresh requests itself and lands
the recovered props through a MERGE writer (prior + new-by-text top-up — exactly the F11 "pure
ADDITION" class the guard deliberately does not flag).

ID LAW: custom_id = the ORIGINAL window cid, unsplit, so props mint as `{cid}#{i}` — the exact
ids the window would have produced in X2. Verified against a live doc that the lost cids' id
namespace is unoccupied; a merge cannot collide.

VINTAGE LAW: recovered props are stamped with the ORIGINAL X2 vintage (--pin-vintage
aa123a122f12-20260820), keeping each of the 440 docs single-vintage — the invariant G1a asserts.
The trade (recorded here, decided by the orchestrator 2026-08-21): the stamp names the corpus
vintage the props belong to, not the calendar day they were minted; the run manifest carries the
true minting date.

NEVER run `--retrieve <this batch's id>`: the saved _batches manifest is loud about it, and the
G1a guard would fence a bare attempt, but --rechunk would not survive the mistake. Merge here.

Usage (laptop; EVIDENCE_S3 is REQUIRED and NOT in .env — the silent-wrong-store footgun):
    $env:EVIDENCE_S3 = 's3://leviathan-dev-shahem-001/graphrag_evidence'
    python jobs/utils/x2_tail_resplit.py --submit --probe          # 20 windows (10 longest + 10 random)
    python jobs/utils/x2_tail_resplit.py --report <bid>            # states + out-token histogram, no writes
    python jobs/utils/x2_tail_resplit.py --submit                  # all 2,062 windows @ 8192
    python jobs/utils/x2_tail_resplit.py --merge <bid> --pin-vintage aa123a122f12-20260820
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import statistics
import sys
import time
from pathlib import Path

from leviathan.common import config

config.load_env()

from leviathan.graphrag import batch_extract as bx    # noqa: E402  (_api_key)
from leviathan.graphrag import chunking as ch         # noqa: E402  (_PROP_SYSTEM, _parse_event_date)
from leviathan.graphrag import evidence as ev         # noqa: E402  (load_index/_evid_write/_evid_s3)
from leviathan.graphrag import evidence_batch as eb   # noqa: E402  (classify/_locate_span/_doc_cache_node/BatchTally)
from leviathan.graphrag import extract as ex          # noqa: E402  (HAIKU)
from leviathan.graphrag import write_guard as wg      # noqa: E402  (RunManifest)

_REPO = Path(__file__).resolve().parents[2]
_WM = _REPO / ".tmp" / "x2tail" / "wm_retrieve.json"
_BLOCKS = _REPO / ".tmp" / "x2tail" / "blocks.json"
_BACKUP_PREFIX = "chunks_backup_20260821/"
_X2_VINTAGE = "aa123a122f12-20260820"


def _require_evidence_s3() -> str:
    base = ev._evid_s3()
    if not base:
        raise SystemExit("EVIDENCE_S3 is not set. Refusing: _cached_hashes/_evid_write would fall back to "
                         "the (empty) local store and the merge would land where nobody reads. Set "
                         "EVIDENCE_S3=s3://leviathan-dev-shahem-001/graphrag_evidence and re-run.")
    return base


def _load_tail() -> tuple[dict, dict]:
    """(lost: cid -> state, blocks: cid -> block meta) — restricted to the lost set, fail-closed."""
    if not _WM.exists() or not _BLOCKS.exists():
        raise SystemExit(f"tail inputs missing: fetch wm_retrieve.json + blocks.json into {_WM.parent} first "
                         "(s3://.../graphrag_evidence/eval/write_manifest_retrieve_20260820T073402Z.json and "
                         "s3://.../graphrag_evidence/_batches/msgbatch_01RFbRUEraQoXnTos43riMuH.json)")
    lost = json.loads(_WM.read_text(encoding="utf-8"))["extraction"]["windows"]["lost_custom_ids"]
    blocks_all = json.loads(_BLOCKS.read_text(encoding="utf-8"))["manifest"]
    missing = [c for c in lost if c not in blocks_all]
    if missing:
        raise SystemExit(f"{len(missing)} lost cids missing from the block manifest (first: {missing[:3]}) "
                         "-- wrong blocks.json?")
    if len(lost) != 2062:
        raise SystemExit(f"expected exactly 2,062 lost cids, found {len(lost)} -- wrong manifest?")
    return lost, {c: blocks_all[c] for c in lost}


def _probe_sample(lost: dict, blocks: dict, n: int = 20) -> list[str]:
    """10 longest windows (the hardest — if THEY clear at 8192, the class clears) + 10 seeded-random."""
    by_len = sorted(lost, key=lambda c: -len(blocks[c].get("block_text") or ""))
    longest = by_len[: n // 2]
    rest = [c for c in sorted(lost) if c not in set(longest)]
    rng = random.Random(0)
    return longest + rng.sample(rest, n - len(longest))


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=bx._api_key())


def cmd_submit(args) -> int:
    _require_evidence_s3()
    lost, blocks = _load_tail()
    cids = sorted(lost)
    if args.probe:
        cids = _probe_sample(lost, blocks)
    elif args.limit:
        cids = cids[: args.limit]
    blank = [c for c in cids if not (blocks[c].get("block_text") or "").strip()]
    if blank:                                              # m7: a blank content string 400s the whole create
        print(f"  skipping {len(blank)} blank-text window(s): {blank[:5]}")
        cids = [c for c in cids if c not in set(blank)]
    if args.split:
        # THE RATIFIED SHAPE (probed 2026-08-21: unsplit@8192 recovered only 6/20 -- 13 windows still hit
        # the ceiling, median out-tokens 8,192; halves at ~2.5k chars fit). Reuses _retry_requests VERBATIM
        # (truncated -> two halves under {cid}_x{j}, unparseable -> as-is), then re-stamps the ceiling.
        sub_lost = {c: lost[c] for c in cids}
        reqs, man = eb._retry_requests(blocks, sub_lost)
        for r in reqs:
            r["params"]["max_tokens"] = args.max_tokens
        submit_manifest = man
    else:
        reqs = [{"custom_id": cid, "params": {
            "model": ex.HAIKU, "max_tokens": args.max_tokens, "temperature": 0, "system": ch._PROP_SYSTEM,
            "messages": [{"role": "user", "content": blocks[cid]["block_text"]}]}} for cid in cids]
        submit_manifest = {c: blocks[c] for c in cids}
    chars = sum(len(blocks[c]["block_text"] or "") for c in cids)
    # m6: dense-table class runs ~2.6 chars/tok (not the 3.32 corpus mean); _PROP_SYSTEM ~390 tok
    est_in = chars / 2.6 / 1e6 * 0.50 + len(cids) * 390 / 1e6 * 0.50
    est_out_lo = len(cids) * 4096 / 1e6 * 2.50            # floor over the truncated class (>4,096 out-tok each)
    est_out_hi = len(cids) * args.max_tokens / 1e6 * 2.50
    ceiling = est_in + est_out_hi
    print(f"submit: {len(reqs)} windows ({'PROBE' if args.probe else 'FULL'}) @ max_tokens={args.max_tokens}")
    print(f"  input {chars:,} chars; floor ${est_in + est_out_lo:.2f}  CEILING ${ceiling:.2f} "
          f"(Haiku batch $0.50/$2.50 per MTok)")
    if args.dry_run:
        print("  [DRY RUN] nothing submitted")
        return 0
    # THE EXPOSURE LAW (2026-08-21, the -$50 repeat): a billed submit REFUSES unless the caller
    # acknowledges a number >= the CEILING (requests x max_tokens at the out-rate, not a demand
    # estimate). The ceiling is what the balance must survive; "realistic" numbers killed the key
    # twice. Probes under $2 are exempt.
    if ceiling > 2.0 and (args.acknowledge_exposure_usd is None or args.acknowledge_exposure_usd < ceiling):
        raise SystemExit(f"REFUSING submit: ceiling exposure ${ceiling:.2f} not acknowledged. Re-run with "
                         f"--acknowledge-exposure-usd {ceiling:.0f} AFTER checking it against the console "
                         "balance (the balance must survive the CEILING, not the estimate) -- and never "
                         "run two billed batches concurrently: read this one's realized bill first.")
    bid = _client().messages.batches.create(requests=reqs).id
    eb._save_manifest(bid, {"batch_id": bid, "manifest": submit_manifest, "doclist": True,
                            "x2_tail": True, "max_tokens": args.max_tokens, "probe": bool(args.probe),
                            "split": bool(args.split),
                            "note": "DO NOT run --retrieve on this batch: it would wholesale-overwrite the "
                                    "440 tail docs' chunk caches. Merge with jobs/utils/x2_tail_resplit.py "
                                    "--merge instead."})
    rec = {"bid": bid, "n": len(cids), "max_tokens": args.max_tokens, "probe": bool(args.probe),
           "submitted_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    rp = _WM.parent / f"submit_{bid}.json"
    rp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    print(f"submitted batch {bid} ({len(reqs)} windows)  [record: {rp}]")
    print(f"  report with:  python jobs/utils/x2_tail_resplit.py --report {bid}")
    if args.probe:                                         # M2: a probe is NEVER merged -- report-only. Merging
        print("  probe batches are REPORT-ONLY: never merge a probe (its cids re-run in the full batch, and a "
              "double merge can mint duplicate {cid}#{idx} ids under nondeterministic regeneration)")
    else:
        print(f"  merge with:   python jobs/utils/x2_tail_resplit.py --merge {bid} --pin-vintage {_X2_VINTAGE}")
    return 0


def _wait_ended(client, bid: str, poll_s: int) -> None:
    while True:
        b = client.messages.batches.retrieve(bid)
        if b.processing_status == "ended":
            return
        rc = b.request_counts
        print(f"  batch {bid}: {b.processing_status} (ok={rc.succeeded} err={rc.errored} "
              f"exp={rc.expired} processing={rc.processing})", flush=True)
        time.sleep(poll_s)


def _classified(client, bid: str, blocks: dict):
    """Yield (cid, state, items, out_tokens) for every result belonging to this tail batch."""
    for r in client.messages.batches.results(bid):
        if r.custom_id not in blocks:
            continue
        state, items = eb._classify_result(r)
        out_tok = None
        try:
            out_tok = r.result.message.usage.output_tokens
        except AttributeError:                             # failed results carry no message
            pass
        yield r.custom_id, state, items, out_tok


def cmd_report(args) -> int:
    _require_evidence_s3()
    payload = eb._load_manifest_full(args.report)
    blocks = payload["manifest"]
    client = _client()
    _wait_ended(client, args.report, args.poll_s)
    states: collections.Counter = collections.Counter()
    toks: list[int] = []
    residual: list[str] = []
    seen: set = set()
    n_props = 0
    for cid, state, items, out_tok in _classified(client, args.report, blocks):
        seen.add(cid)
        states[state] += 1
        if out_tok is not None:
            toks.append(out_tok)
        if state == "ok":
            n_props += sum(1 for it in items if (it.get("proposition") or "").strip())
        elif state in ("truncated", "unparseable", "failed"):
            residual.append(cid)
    no_result = len(blocks) - len(seen)                    # m3: a window that never returned is a loss too
    print(f"report {args.report}: {dict(states)}  props~{n_props}  no_result={no_result}")
    if toks:
        print(f"  out-tokens: n={len(toks)} mean={statistics.mean(toks):.0f} "
              f"median={statistics.median(toks):.0f} max={max(toks)} "
              f">4096: {sum(1 for t in toks if t > 4096)}  at-ceiling(>=8100): "
              f"{sum(1 for t in toks if t >= 8100)}")
    if residual:
        print(f"  residual ({len(residual)}): {sorted(residual)[:20]}{' ...' if len(residual) > 20 else ''}")
    ok = states.get("ok", 0)
    if states.get("empty_legitimate"):                     # m4: for windows that overflowed 4,096 out-tok, an
        print(f"  empty_legitimate: {states['empty_legitimate']} (SUSPECT for this population -- these "
              f"windows previously overflowed the ceiling; a genuine [] is a regression smell, not recovery)")
    total = len(blocks)
    print(f"  recovery (ok only): {ok}/{total} = {ok / max(total, 1):.1%}")
    return 0


def _backup_hashes() -> set:
    """md5 names present under the backup prefix (paginated LIST, same idiom as _cached_hashes)."""
    import boto3
    bkt, prefix = ev._parse_s3(_require_evidence_s3().rstrip("/") + "/" + _BACKUP_PREFIX)
    out: set = set()
    for p in boto3.client("s3").get_paginator("list_objects_v2").paginate(Bucket=bkt, Prefix=prefix):
        out |= {o["Key"].rsplit("/", 1)[-1][:-6] for o in p.get("Contents", []) if o["Key"].endswith(".jsonl")}
    return out


def cmd_merge(args) -> int:
    _require_evidence_s3()
    pin = args.pin_vintage
    if pin != _X2_VINTAGE:                                 # m2: a typo'd pin should fail BEFORE the poll
        raise SystemExit(f"--pin-vintage {pin!r} != the X2 vintage {_X2_VINTAGE!r} -- refusing")
    backup = _backup_hashes()
    if not backup:
        raise SystemExit(f"refusing to merge: backup prefix {_BACKUP_PREFIX} is empty/absent and bucket "
                         "versioning is Suspended. Run the chunks/ backup sync first.")
    payload = eb._load_manifest_full(args.merge)
    if payload.get("probe"):
        raise SystemExit("that batch is a PROBE: report-only, never merged (its cids re-run in the full "
                         "batch; a double merge can mint duplicate ids)")
    if payload.get("split"):
        raise SystemExit("this merge handles UNSPLIT batches only ({cid}#{idx} minting); a split batch "
                         "needs the half-reassembly path -- not implemented until a split run is chosen")
    blocks = payload["manifest"]
    client = _client()
    _wait_ended(client, args.merge, args.poll_s)

    tally = eb.BatchTally(windows_submitted=len(blocks), label="x2_tail")
    props_by_doc: dict[str, list[dict]] = {}
    seen_cids: set = set()
    for cid, state, items, _out in _classified(client, args.merge, blocks):
        seen_cids.add(cid)
        tally.note(state)
        if state in ("truncated", "unparseable", "failed"):
            tally.note_lost(cid, state)
            continue
        m = blocks[cid]
        block_text, block_start, block_end = m.get("block_text"), m.get("block_start"), m.get("block_end")
        cursor = 0
        i = 0
        for item in items:
            idx, i = i, i + 1                              # advance on EVERY item -- mirrors retrieve()
            prop = (item.get("proposition") or "").strip()
            if not prop:
                continue
            ev_dt, ev_prec = ch._parse_event_date(item.get("event_date"), item.get("event_date_precision"))
            span = (item.get("verbatim_span") or "").strip()
            cstart, cend, okind, cursor = eb._locate_span(span or prop, block_text, block_start,
                                                          block_end, cursor)
            base = {"date": m["date"], "source": m["source"], "source_key": m["source_key"], "text": prop,
                    "event_date": str(ev_dt) if ev_dt else None, "event_date_precision": ev_prec,
                    "char_start": cstart, "char_end": cend, "offset_kind": okind, "chunk_version": pin,
                    "date_kind": m.get("date_kind"), "date_layout": m.get("date_layout")}
            props_by_doc.setdefault(m["source_key"], []).append({"id": f"{cid}#{idx}", **base})
            tally.props_emitted += 1
    for cid in blocks:                                     # m3: a window that never returned is a loss too
        if cid not in seen_cids:
            tally.note("failed")
            tally.note_lost(cid, "no_result")
    tally.report()
    if not props_by_doc:                                   # m11: an all-failed merge must not look successful
        raise SystemExit("refusing: the batch recovered ZERO props -- nothing to merge, no manifest written")

    # MERGE, fail-closed. Three doc classes (M1): (a) prior cached at exactly the pinned vintage -> text-dedup
    # top-up; (b) NO chunks/ object at all (11 of the 440 tail docs are all-lost: every window of the doc is
    # in the tail, so X2 never wrote them) -> a pure fill, nothing to lose; (c) object EXISTS but the read
    # came back empty or off-vintage -> offender, whole merge refuses.
    cached = eb._cached_hashes()
    offenders: list[str] = []
    plans: dict[str, tuple[list, int]] = {}
    fills = 0
    for sk in sorted(props_by_doc):
        node_md5 = eb._doc_cache_node(sk).split("/")[-1]
        safe = str(sk).encode("ascii", "backslashreplace").decode("ascii")   # m5: one key is non-ASCII
        prior = eb._read_doc_cache(sk)
        if not prior and node_md5 not in cached:
            prior, seen = [], set()                        # class (b): a NEW doc -- a fill, never a re-chunk
            fills += 1
        else:
            pv = {p.get("chunk_version") for p in prior}
            if not prior or pv != {pin}:                   # class (c): empty read / wrong vintage
                offenders.append(f"{safe} (prior={len(prior)} vintages={sorted(str(v) for v in pv)})")
                continue
            if node_md5 not in backup:                     # m1: every doc we top up must be recoverable
                offenders.append(f"{safe} (prior cached but MISSING from {_BACKUP_PREFIX})")
                continue
            seen = {p["text"] for p in prior}
        # M2: same-id-DIFFERENT-text = a true collision (a cid merged before, regenerated differently).
        # Same-id-same-text is the idempotent re-merge case and passes (text-dedup drops it below).
        prior_by_id = {p.get("id"): p.get("text") for p in prior}
        clash = sorted({p["id"] for p in props_by_doc[sk]
                        if p["id"] in prior_by_id and prior_by_id[p["id"]] != p["text"]})
        if clash:
            offenders.append(f"{safe}: {len(clash)} incoming id(s) already in prior with DIFFERENT text "
                             f"(first {clash[:3]}) -- a cid was merged before and regenerated differently")
            continue
        add, new_seen = [], set()
        for p in props_by_doc[sk]:
            if p["text"] in seen or p["text"] in new_seen:
                continue
            new_seen.add(p["text"])
            add.append(p)
        plans[sk] = (prior + add, len(add))
    if offenders:
        raise SystemExit("refusing the WHOLE merge (nothing written): "
                         f"{len(offenders)} offender doc(s) -- " + "; ".join(offenders[:5]))
    if args.dry_run:
        print(f"[DRY RUN] would top-up {len(plans) - fills} docs + fill {fills} new docs with "
              f"{sum(n for _, n in plans.values())} props (dedup-by-text applied)")
        return 0

    # M3: the write loop is crash-safe -- whatever lands is recorded even if a mid-loop write throws.
    done: dict[str, int] = {}
    err: Exception | None = None
    try:
        for sk, (merged, n_add) in plans.items():
            ev._evid_write(eb._doc_cache_node(sk), "\n".join(json.dumps(p) for p in merged))
            done[sk] = n_add
    except Exception as exc:                               # noqa: BLE001 -- re-raised after the manifest lands
        err = exc
    n_added = sum(done.values())
    print(f"merged: +{n_added} props across {len(done)} docs ({fills} new-doc fills; vintage {pin})")

    manifest = wg.RunManifest("x2_tail", chunk_version=pin)
    manifest.record_extraction({"windows": tally.summary()})
    manifest.record_docs(written=len(done), overwritten=len(done) - fills,
                         vintage_transitions={f"{pin} -> {pin}": max(len(done) - fills, 0)},
                         per_doc_delta=dict(done))
    if tally.lost():
        manifest.warnings.append(f"x2_tail residual: {tally.lost()} window(s) still lost at "
                                 f"max_tokens={payload.get('max_tokens')} -- named in lost_custom_ids; "
                                 "a further round is a NEW decision, not an automatic retry")
    if err is not None:
        manifest.warnings.append(f"MERGE INTERRUPTED after {len(done)}/{len(plans)} docs: "
                                 f"{type(err).__name__}: "
                                 + str(err).encode("ascii", "backslashreplace").decode("ascii")[:200]
                                 + " -- a re-merge of the same bid is idempotent (dedup-by-text + id fence)")
    out = manifest.flush()
    print(f"run manifest: {out}")
    if err is not None:
        raise err
    print("NOTE: these props reach serving only at the next wave's ONE --rebuild-slices + pg reload.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="X2 retry tail: submit/report/merge the 2,062 lost windows @ 8192")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--submit", action="store_true")
    mode.add_argument("--report", metavar="BID")
    mode.add_argument("--merge", metavar="BID")
    ap.add_argument("--probe", action="store_true", help="submit only the 20-window probe (10 longest + 10 random)")
    ap.add_argument("--split", action="store_true", help="submit halves via eb._retry_requests (fallback shape)")
    ap.add_argument("--limit", type=int, default=None, help="submit only the first N (sorted) lost cids")
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--acknowledge-exposure-usd", type=float, default=None,
                    help="REQUIRED for any billed submit with ceiling > $2: the acknowledged worst-case "
                         "dollar exposure (must be >= the computed ceiling; check the balance first)")
    ap.add_argument("--pin-vintage", default=None, help=f"REQUIRED for --merge (the X2 vintage: {_X2_VINTAGE})")
    ap.add_argument("--poll-s", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.submit:
        return cmd_submit(args)
    if args.report is not None:
        return cmd_report(args)
    if not args.pin_vintage:
        raise SystemExit("--merge requires --pin-vintage (the vintage decision is explicit, never a default)")
    return cmd_merge(args)


if __name__ == "__main__":
    sys.exit(main())
