"""W1.5 per-slice precision spot-audit — the misfiling detector token-recall can't provide.

Token/edge recall answers "is enough on-topic evidence PRESENT?"; it is silent on the dual failure —
props a slightly-over-firing driver term dragged into a slice they don't belong in. This harness samples
a handful of props from each target driver slice and asks a cheap topical-relevance judge, one prop at a
time, "does this proposition belong in slice <name>? yes/no + reason", then tabulates per-slice PRECISION
(fraction judged yes). Low precision on a slice == an over-firing `terms` phrase (the misfiling class the
P3 prevention doctrine's write-side audit is meant to catch, W1.5).

Reuses batch_extract.py's decider scaffolding (the Anthropic Message Batches submit/collect + manifest
pattern; reports to configs/graphrag/pilot/). Deliberately additive/opt-in: a NEW module invoked by hand
or by a pass wrapper — it changes no serving path and spends nothing until you drop --dry-run.

    python -m leviathan.graphrag.slice_audit --dry-run --slices el_nino,freight   # plan + cost, no spend
    python -m leviathan.graphrag.slice_audit --slices el_nino,freight             # submit + collect + report

Sampling is ONE ev.load_index read per slice (no per-prop S3, no LIST — the July LIST-storm rule). The
judge is a plain YES/NO first-line prompt (no tool schema tokens), defaulting to the cheapest model.
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex

_REPO = Path(__file__).resolve().parents[3]
_OUT = _REPO / "configs" / "graphrag" / "pilot"          # same report sink as batch_extract's decider
_BATCH_PRICE = 0.5                                        # Anthropic Batch API = 50% of standard token price
JUDGE_MODEL = ex.HAIKU                                    # a yes/no topical judge — the cheapest model suffices
_DEFAULT_K = 10                                           # props sampled per slice (the plan's "~10/slice")
_DEFAULT_SEED = 20260707
_JUDGE_MAX_TOKENS = 256                                   # verdict word + a one-sentence reason
_JUDGE_OUT_TOK = 48                                       # per-request output estimate for the dry-run


# ── slice loading + sampling (one read per slice; no per-prop S3) ─────────────────────────────────
def _slice_node(slice_name: str) -> str:
    """The ev index node backing a driver slice — evidence/drivers/<slice>.jsonl (write_driver_slices)."""
    return f"drivers/{slice_name}"


def load_slice_props(slice_name: str) -> list[dict]:
    """All stored props for a driver slice via ONE ev.load_index (S3/local GET, never a LIST or per-prop
    fetch). Returns [] for a slice with no jsonl (a wired-but-unbuilt slice) — the caller skips it."""
    return ev.load_index(_slice_node(slice_name))


def sample_props(records: list[dict], *, k: int = _DEFAULT_K, seed: int = _DEFAULT_SEED) -> list[dict]:
    """A deterministic sample of <=k prop records. Fewer than k present -> all of them (in stored order);
    otherwise a seeded random.sample so a re-run audits the same props (reproducible precision)."""
    if len(records) <= k:
        return list(records)
    return random.Random(seed).sample(records, k)


# ── the topical-relevance judge (plain YES/NO first line — no tool, cheapest tokens) ───────────────
def build_judge_system() -> str:
    """System prompt for the misfiling judge. Forces a machine-parseable first line (YES/NO) so the
    collector never has to interpret prose to score precision."""
    return ("You are a strict data-curation auditor for a commodity causal-evidence store. Each evidence "
            "slice collects propositions about ONE causal-driver theme. You are given a slice name (the "
            "driver theme) and a single proposition that was filed into that slice. Decide whether the "
            "proposition is genuinely ABOUT that driver theme (topically on-slice), not merely adjacent or "
            "coincidentally sharing a word. Answer on the FIRST line with exactly one word: YES or NO. On "
            "the SECOND line give a one-sentence reason. YES = the proposition belongs in this slice; "
            "NO = it was misfiled.")


def build_judge_user(slice_name: str, prop_text: str, *, terms: list | None = None) -> str:
    """User message for one prop. The slice name appears verbatim (the request builder's contract) and,
    when available, the slice's topical `terms` give the judge the theme definition rather than guessing
    it from the name alone."""
    lines = [f"Slice name: {slice_name}", f"Driver theme: {slice_name.replace('_', ' ')}"]
    if terms:
        lines.append("Topical terms defining this slice: " + ", ".join(str(t) for t in list(terms)[:12]))
    lines += ["", "Proposition under audit:", f'"{prop_text}"', "",
              f"Does this proposition belong in the '{slice_name}' slice? Answer YES or NO, then a reason."]
    return "\n".join(lines)


def _cid(n: int, slice_name: str) -> str:
    """A batch custom_id: globally-indexed (n guarantees uniqueness) + slice tag, sanitized to the API's
    [A-Za-z0-9_-]{1,64}."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", f"js{n:04d}-{slice_name}")[:64]


def build_requests(sampled_by_slice: dict, *, model: str = JUDGE_MODEL,
                   terms_by_slice: dict | None = None) -> tuple[list[dict], dict]:
    """One Batch request per sampled prop (no forced tool — a plain YES/NO judge). Returns (requests,
    manifest); manifest[custom_id] = {slice, text, source_key, id} so the collector can attribute each
    verdict back to its slice and surface misfiled props with provenance."""
    system = build_judge_system()
    requests: list[dict] = []
    manifest: dict = {}
    n = 0
    for slice_name in sorted(sampled_by_slice):
        terms = (terms_by_slice or {}).get(slice_name)
        for rec in sampled_by_slice[slice_name]:
            text = rec.get("text", "")
            cid = _cid(n, slice_name)
            requests.append({"custom_id": cid, "params": {
                "model": model, "max_tokens": _JUDGE_MAX_TOKENS, "system": system,
                "messages": [{"role": "user", "content": build_judge_user(slice_name, text, terms=terms)}]}})
            manifest[cid] = {"slice": slice_name, "text": text,
                             "source_key": rec.get("source_key"), "id": rec.get("id")}
            n += 1
    return requests, manifest


# ── verdict parsing + collection ──────────────────────────────────────────────────────────────────
def _message_text(message) -> str:
    """Concatenate the text blocks of a batch result message (attr-style SDK blocks or dict blocks)."""
    parts = []
    for b in getattr(message, "content", None) or []:
        if getattr(b, "type", None) == "text":
            parts.append(getattr(b, "text", "") or "")
        elif isinstance(b, dict) and b.get("type") == "text":
            parts.append(b.get("text", "") or "")
    return "\n".join(parts)


def _verdict_of(message) -> "bool | None":
    """True/False from the first non-empty line's lead token (YES/NO); None when the model didn't lead with
    a verdict (counted as a parse failure, never silently scored)."""
    for line in _message_text(message).splitlines():
        w = line.strip().lstrip("*#->_ ").strip()
        if not w:
            continue
        tok = w.split()[0].strip(".:,;)(-\"'").lower()
        if tok.startswith("yes"):
            return True
        if tok.startswith("no"):
            return False
        return None
    return None


def _reason_of(message) -> str:
    """The judge's stated reason: the tail of the verdict line plus any following lines, for the misfiled
    report (why a NO prop doesn't belong)."""
    lines = [ln.strip() for ln in _message_text(message).splitlines() if ln.strip()]
    if not lines:
        return ""
    rest = lines[1:]
    head_tail = lines[0].split(None, 1)
    if len(head_tail) > 1:
        rest = [head_tail[1]] + rest
    return " ".join(rest).strip(" :-\t")


def collect_precision(client, bid: str, manifest: dict, *, model: str = JUDGE_MODEL) -> dict:
    """Tabulate per-slice precision from a finished judge batch. precision = on-slice YES / parseable
    verdicts for that slice; unparseable/non-succeeded results are tallied as n_fail (never scored).
    Returns {slices: {name: {n_judged, n_yes, precision, misfiled}}, cost_usd, n_fail, in_tok, out_tok}."""
    pin, pout = ex.price(model)
    per: dict = {}                                        # slice -> {n, n_yes, misfiled}
    in_tok = out_tok = n_fail = 0
    for r in client.messages.batches.results(bid):
        m = manifest.get(getattr(r, "custom_id", None))
        if r.result.type != "succeeded" or m is None:
            n_fail += 1
            continue
        msg = r.result.message
        u = getattr(msg, "usage", None)
        in_tok += getattr(u, "input_tokens", 0) or 0
        out_tok += getattr(u, "output_tokens", 0) or 0
        slot = per.setdefault(m["slice"], {"n": 0, "n_yes": 0, "misfiled": []})
        verdict = _verdict_of(msg)
        if verdict is None:                              # model didn't answer YES/NO -> unscored friction
            n_fail += 1
            continue
        slot["n"] += 1
        if verdict:
            slot["n_yes"] += 1
        else:
            slot["misfiled"].append({"text": (m.get("text") or "")[:240],
                                     "source_key": m.get("source_key"),
                                     "reason": _reason_of(msg)[:240]})
    slices = {name: {"n_judged": d["n"], "n_yes": d["n_yes"],
                     "precision": (d["n_yes"] / d["n"] if d["n"] else None),
                     "misfiled": d["misfiled"]}
              for name, d in per.items()}
    cost = (in_tok * pin + out_tok * pout) * _BATCH_PRICE
    return {"slices": slices, "cost_usd": cost, "n_fail": n_fail,
            "in_tok": in_tok, "out_tok": out_tok, "model": model}


# ── cost estimate + dry-run ────────────────────────────────────────────────────────────────────────
def estimate_cost(sampled_by_slice: dict, *, model: str = JUDGE_MODEL,
                  terms_by_slice: dict | None = None) -> dict:
    """A chars/4 token proxy over the ACTUAL prompts that would be sent (system reused across requests),
    times Batch (-50%) pricing. No API calls — the number the dry-run reports."""
    pin, pout = ex.price(model)
    sys_tok = len(build_judge_system()) // 4
    n_props = in_tok = 0
    for slice_name, recs in sampled_by_slice.items():
        terms = (terms_by_slice or {}).get(slice_name)
        for rec in recs:
            in_tok += sys_tok + len(build_judge_user(slice_name, rec.get("text", ""), terms=terms)) // 4
            n_props += 1
    out_tok = n_props * _JUDGE_OUT_TOK
    est = (in_tok * pin + out_tok * pout) * _BATCH_PRICE
    return {"n_slices": len(sampled_by_slice), "n_props": n_props, "est_usd": est,
            "model": model, "in_tok": in_tok, "out_tok": out_tok}


def dry_run(sampled_by_slice: dict, *, model: str = JUDGE_MODEL, k: int = _DEFAULT_K,
            terms_by_slice: dict | None = None) -> dict:
    """Print the plan (per-slice sample counts) + estimated cost and submit NOTHING. Stdout is ASCII-only
    (Windows cp1252). Returns the estimate dict."""
    est = estimate_cost(sampled_by_slice, model=model, terms_by_slice=terms_by_slice)
    print(f"[dry-run] slice precision spot-audit plan (model={model}, <= {k} props/slice):")
    for name in sorted(sampled_by_slice):
        print(f"  {name}: {len(sampled_by_slice[name])} props sampled")
    print(f"[dry-run] {est['n_slices']} slices, {est['n_props']} props, est Batch cost "
          f"${est['est_usd']:.4f} ({model}). No API calls; nothing submitted.")
    return est


# ── reporting ────────────────────────────────────────────────────────────────────────────────────
def _put_report_s3(bid: str) -> None:
    """Mirror the pilot/ reports to S3 eval/ when EVIDENCE_S3 is set (the e0_harness put_object idiom)."""
    base = ev._evid_s3()
    if not base:
        return
    import boto3
    b = k = None
    for fname in ("slice_precision.json", "slice_precision_report.md"):
        b, k = ev._parse_s3(base.rstrip("/") + f"/eval/{fname}")
        boto3.client("s3").put_object(Bucket=b, Key=k, Body=(_OUT / fname).read_bytes())
    if b:
        print(f"  reports -> s3://{b}/eval/ (slice_precision.json + .md)", flush=True)


def write_report(result: dict, *, bid: str, model: str, write_s3: bool = True) -> None:
    """Write the per-slice precision report (json + markdown) to configs/graphrag/pilot/ and, if
    EVIDENCE_S3 is set, mirror to S3 eval/. Slices are ordered WORST precision first (the misfiling
    signal). Report files are UTF-8 (prop text may be PT/ES/FR); stdout stays ASCII."""
    _OUT.mkdir(parents=True, exist_ok=True)
    slices = result["slices"]
    ordered = sorted(slices.items(),
                     key=lambda kv: (kv[1]["precision"] if kv[1]["precision"] is not None else 1.0, kv[0]))
    (_OUT / "slice_precision.json").write_text(json.dumps({
        "batch_id": bid, "model": model, "cost_usd": round(result.get("cost_usd", 0.0), 4),
        "n_fail": result.get("n_fail", 0), "slices": slices}, indent=2, ensure_ascii=False), encoding="utf-8")

    L = [f"# Slice precision spot-audit ({bid})",
         f"\n**model={model} (Batch) | ${result.get('cost_usd', 0.0):.4f} | {len(slices)} slices | "
         f"{result.get('n_fail', 0)} unparseable/failed**\n",
         "| slice | judged | on-slice | precision |", "|---|---:|---:|---:|"]
    for name, d in ordered:
        prec = "n/a" if d["precision"] is None else f"{d['precision']:.0%}"
        L.append(f"| {name} | {d['n_judged']} | {d['n_yes']} | {prec} |")
    L.append("\n## Misfiled props (judge said NO) — candidate over-firing terms")
    misfiled = [(name, mis) for name, d in ordered for mis in d["misfiled"]]
    for name, mis in misfiled:
        L += [f"- **{name}**: {mis.get('reason', '')}",
              f"  - prop: {mis.get('text', '')}",
              f"  - src: {mis.get('source_key', '')}"]
    if not misfiled:
        L.append("- none (every sampled prop judged on-slice)")
    (_OUT / "slice_precision_report.md").write_text("\n".join(L), encoding="utf-8")

    if write_s3:
        _put_report_s3(bid)
    print(f"audit {bid}: {len(slices)} slices judged, ${result.get('cost_usd', 0.0):.4f}. report -> {_OUT}",
          flush=True)
    if ordered and ordered[0][1]["precision"] is not None:
        w_name, w = ordered[0]
        print(f"  lowest precision: {w_name} at {w['precision']:.0%} "
              f"({w['n_yes']}/{w['n_judged']} on-slice)", flush=True)


# ── orchestration ────────────────────────────────────────────────────────────────────────────────
def _gather_samples(slices: list, *, k: int, seed: int) -> dict:
    """{slice -> sampled records}. ONE ev.load_index per slice (no LIST, no per-prop S3); empty slices are
    reported and skipped rather than emitting empty batch requests."""
    sampled: dict = {}
    for name in slices:
        picked = sample_props(load_slice_props(name), k=k, seed=seed)
        if picked:
            sampled[name] = picked
        else:
            print(f"[skip] slice {name}: no props found -- not audited", flush=True)
    return sampled


def audit(client, slices: list, *, k: int = _DEFAULT_K, seed: int = _DEFAULT_SEED,
          model: str = JUDGE_MODEL, terms_by_slice: dict | None = None,
          write_s3: bool = True, poll_secs: int = 30) -> dict:
    """Full flow: sample -> ONE judge batch over all slices -> poll -> collect precision -> write report.
    One batch (not one per slice) keeps the submit cheap; the manifest re-attributes per slice."""
    sampled = _gather_samples(slices, k=k, seed=seed)
    if not sampled:
        raise SystemExit("no props sampled from any target slice -- nothing to audit")
    reqs, manifest = build_requests(sampled, model=model, terms_by_slice=terms_by_slice)
    bid = client.messages.batches.create(requests=reqs).id
    print(f"submitted judge batch {bid}: {len(reqs)} requests over {len(sampled)} slices", flush=True)
    while client.messages.batches.retrieve(bid).processing_status != "ended":
        print("  batch running ...", flush=True)
        time.sleep(poll_secs)
    result = collect_precision(client, bid, manifest, model=model)
    result["batch_id"] = bid
    write_report(result, bid=bid, model=model, write_s3=write_s3)
    return result


def _resolve_slices(arg: "str | None") -> list:
    """--slices csv, else every driver slice from the specs (a clean checkout with no causal dir has no
    specs -> empty -> caller requires an explicit --slices)."""
    if arg:
        return [s.strip() for s in arg.split(",") if s.strip()]
    try:
        return sorted(ev.driver_specs().keys())
    except Exception:  # noqa: BLE001 -- no private configs present; require explicit --slices
        return []


def _terms_for(slices: list) -> "dict | None":
    """Best-effort {slice -> topical terms} to sharpen the judge prompt; None when specs are unavailable."""
    try:
        specs = ev.driver_specs()
    except Exception:  # noqa: BLE001
        return None
    return {s: ((specs.get(s) or {}).get("terms") or None) for s in slices}


def main(argv: "list | None" = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="W1.5 per-slice precision spot-audit (topical-relevance judge, Anthropic Batch).")
    ap.add_argument("--slices", default=None,
                    help="comma-separated driver-slice names (default: all driver slices)")
    ap.add_argument("--k", type=int, default=_DEFAULT_K, help="props sampled per slice (<=)")
    ap.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    ap.add_argument("--model", default=JUDGE_MODEL)
    ap.add_argument("--dry-run", action="store_true", help="print the plan + estimated cost; submit nothing")
    ap.add_argument("--no-s3", action="store_true", help="skip the S3 eval/ report upload")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args(argv)

    # reuse the decider's .env + api-key scaffolding (batch_extract._load_env / _api_key)
    from leviathan.graphrag import batch_extract as bx
    bx._load_env()
    slices = _resolve_slices(args.slices)
    if not slices:
        raise SystemExit("no target slices -- pass --slices (no driver specs found for the default)")
    terms_by_slice = _terms_for(slices)

    if args.dry_run:
        sampled = _gather_samples(slices, k=args.k, seed=args.seed)
        if not sampled:
            print("[dry-run] no props sampled from any target slice. No API calls; nothing submitted.")
            return 0
        dry_run(sampled, model=args.model, k=args.k, terms_by_slice=terms_by_slice)
        return 0

    import anthropic
    client = anthropic.Anthropic(api_key=bx._api_key())
    audit(client, slices, k=args.k, seed=args.seed, model=args.model,
          terms_by_slice=terms_by_slice, write_s3=not args.no_s3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
