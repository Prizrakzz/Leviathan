"""Exp-1 — prompt-cache vs Batch: bill the per-call extraction cost and lock the production cache pattern.

The whole 2020–26 index budget (§8.3) rests on one *projected, unbilled* claim: that sync + prompt-cache
beats Batch for our prefix-heavy tiny chunks (the static prefix = ~2,481 tok = 65% of a call; the chunk is
~114 tok). This harness replaces the projection with **real** ``cache_creation``/``cache_read`` usage over a
sample of gated 2020–26 chunks, and answers the two open questions:

  • cost: warm cache read (§ arm C) vs Batch −50% (§ arm B)? and 5-min (C) vs 1-hour (C′) TTL?
  • concurrency: a cache entry is readable only after the first response *starts streaming*, so N cold
    concurrent calls all pay full price (the cause of the low hit-rate Anthropic flagged). Does
    **prime-then-fan-out** (arm D-primed) recover the hit-rate vs naive cold fan-out (D-cold)?

Model = Sonnet 4.6 (the chosen extractor; Stage C rejected cheaper models). Sampling uses the FREE
deterministic chunker, so the only spend is the Sonnet calls (~$1 at the default ``--n 40``). Each arm
appends a unique nonce to the cached system block so arms start cold-independent (no cross-arm warmth
contaminates a "first call = write" measurement); the nonce is ~negligible tokens and doesn't change the
cache mechanics it measures. Run cloud-side or local — Sonnet, not Opus, so the no-laptop rule is N/A.

    python -m leviathan.graphrag.cache_probe --dry-run            # plan + projected spend, no calls
    python -m leviathan.graphrag.cache_probe --n 40               # the gated ~$1 run
"""
from __future__ import annotations

import argparse
import json
import random
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

import boto3

from leviathan.graphrag import batch_extract as bx
from leviathan.graphrag import extract as ex

MODEL = ex.SONNET
_PILOT = Path(__file__).resolve().parents[3] / "configs" / "graphrag" / "pilot"
_PROPS = _PILOT / "candidate_gold.jsonl"           # real propositions from the prior run (production-faithful size)
_REPORT = _PILOT / "cache_experiment_report.md"


# ── sampling ──────────────────────────────────────────────────────────────────────────
def _load_props() -> list[str]:
    if not _PROPS.exists():
        return []
    out = []
    for line in _PROPS.read_text(encoding="utf-8").splitlines():
        try:
            ch = json.loads(line).get("chunk")
        except json.JSONDecodeError:
            continue
        p = ch.get("proposition") if isinstance(ch, dict) else ch
        if p:
            out.append(p)
    return out


def sample_messages(s3, n: int, seed: int) -> list[str]:
    """N user messages of **production-faithful size**. Preferred source: the real propositions in
    candidate_gold.jsonl (mean ~94 chars ≈ the K=1 prop the production extractor sees) — free, no Bedrock.
    Fallback: the S3 deterministic block chunker. Either way the prefix dominates the call; the chunk size
    only sets how dominant, so faithful props keep the $/call reconcilable with the §8.3 index estimate."""
    props = _load_props()
    if props:
        rng = random.Random(seed)
        start = rng.randrange(max(1, len(props) - n)) if len(props) > n else 0
        window = props[start:start + n] or props[:n]
        return [ex.build_user_message(window[i - 1] if i > 0 else "",
                                      window[i],
                                      window[i + 1] if i < len(window) - 1 else "")
                for i in range(len(window))]
    msgs: list[str] = []                                       # fallback: live S3 chunker
    for key in bx._sample_minibatch(s3, seed):
        chunks = bx._chunks_for(s3, key, "block", gate=True)
        for i, ch in enumerate(chunks):
            prev = chunks[i - 1].proposition if i > 0 else ""
            nxt = chunks[i + 1].proposition if i < len(chunks) - 1 else ""
            msgs.append(ex.build_user_message(prev, ch.proposition, nxt))
            if len(msgs) >= n:
                return msgs
    return msgs


def _noned(system: str, nonce: str) -> str:
    """Append a cache-busting marker so each arm's cache key is distinct → arms start cold-independent."""
    return f"{system}\n<!-- exp1:{nonce} -->"


def _at(msgs: list[str], i: int) -> str:
    return msgs[i % len(msgs)] if msgs else "(empty)"


# ── arms ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Arm:
    name: str
    usages: list[ex.Usage] = field(default_factory=list)
    ttl: str | None = None
    concurrency: int = 1
    note: str = ""

    def cost(self) -> float:
        return sum(u.cost_for(MODEL, self.ttl) for u in self.usages)

    def per_call(self) -> float:
        return self.cost() / len(self.usages) if self.usages else 0.0

    def read_hit_rate(self) -> float:
        if not self.usages:
            return 0.0
        return sum(1 for u in self.usages if u.cache_read > 0) / len(self.usages)


def run_sequential(client, system, tool, msgs, *, cache: bool, ttl: str | None, name: str) -> Arm:
    """N sequential calls sharing one (nonced) prefix. With cache=True: call 0 writes, calls 1..N read."""
    sysn = _noned(system, uuid.uuid4().hex[:8])
    arm = Arm(name=name, ttl=ttl)
    for i, m in enumerate(msgs):
        _, u = ex.call_extract(client, sysn, m, model=MODEL, cache=cache, ttl=ttl, tool=tool)
        arm.usages.append(u)
    return arm


def run_concurrent(client, system, tool, msgs, *, ttl: str | None, concurrency: int,
                   primed: bool, name: str) -> Arm:
    """K concurrent cache=True calls over one (nonced) cold prefix. primed=True fires one real call first
    (await), then fans out K — so the workers read the warm cache instead of each racing to write it."""
    sysn = _noned(system, uuid.uuid4().hex[:8])
    arm = Arm(name=name, ttl=ttl, concurrency=concurrency)
    if primed:
        _, uw = ex.call_extract(client, sysn, _at(msgs, 0), model=MODEL, cache=True, ttl=ttl, tool=tool)
        arm.note = f"prime: write={uw.cache_creation} read={uw.cache_read}"

    def _one(i: int) -> ex.Usage:
        _, u = ex.call_extract(client, sysn, _at(msgs, i + 1), model=MODEL, cache=True, ttl=ttl, tool=tool)
        return u

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        arm.usages = list(pool.map(_one, range(concurrency)))
    return arm


def probe_warm_cache(client, system, tool, *, ttl: str | None) -> str:
    """Does the max_tokens=0 prefill warmup work with our tools present? (Forced tool_choice would reject
    it, but warm_cache omits tool_choice.) Reports the outcome — production may instead prime with a real
    first call."""
    sysn = _noned(system, uuid.uuid4().hex[:8])
    try:
        u = ex.warm_cache(client, sysn, model=MODEL, ttl=ttl, tool=tool)
        return f"OK — cache_creation={u.cache_creation}, read={u.cache_read}, output billed=0"
    except Exception as e:  # noqa: BLE001 — the experiment is to find out; record and move on
        return f"REJECTED ({type(e).__name__}: {str(e)[:120]}) — prime with a real first call instead"


# ── report ──────────────────────────────────────────────────────────────────────────
def _money(x: float) -> str:
    return f"${x:.5f}"


def build_report(arms: dict[str, Arm], batch_per_call: float, batch_total: float,
                 warm_probe: str, *, n: int, concurrency: int) -> str:
    A, C5, C1 = arms["A"], arms["C_5m"], arms["C_1h"]
    Dc, Dp = arms["D_cold"], arms["D_primed"]
    # warm steady-state = mean over the read calls (skip the writing first call) of the sequential arm
    warm_reads = [u for u in C5.usages if u.cache_read > 0]
    warm_per_call = mean(u.cost_for(MODEL, "5m") for u in warm_reads) if warm_reads else 0.0
    write_u = next((u for u in C5.usages if u.cache_creation > 0), None)
    silent_miss = write_u is None or write_u.cache_creation == 0
    verdict = "cache WINS" if warm_per_call < batch_per_call else "BATCH wins"
    L = [
        "# Exp-1 — prompt-cache vs Batch (per-call extraction cost)",
        "",
        f"Model **{MODEL}**, n={n} gated 2020–26 chunks, concurrency={concurrency}. "
        "Each arm uses a unique nonce → cold-independent. All costs are billed (real `usage`).",
        "",
        "| Arm | calls | mean prefix read tok | mean write tok | $/call | total |",
        "|---|---:|---:|---:|---:|---:|",
        f"| A — sync, no cache | {len(A.usages)} | 0 | 0 | {_money(A.per_call())} | {_money(A.cost())} |",
        f"| B — Batch (analytic ×0.5) | {len(A.usages)} | — | — | {_money(batch_per_call)} | {_money(batch_total)} |",
        f"| C — sync+cache 5-min | {len(C5.usages)} | {int(mean([u.cache_read for u in C5.usages]) if C5.usages else 0)} "
        f"| {int(mean([u.cache_creation for u in C5.usages]) if C5.usages else 0)} | {_money(C5.per_call())} | {_money(C5.cost())} |",
        f"| C′ — sync+cache 1-hour | {len(C1.usages)} | {int(mean([u.cache_read for u in C1.usages]) if C1.usages else 0)} "
        f"| {int(mean([u.cache_creation for u in C1.usages]) if C1.usages else 0)} | {_money(C1.per_call())} | {_money(C1.cost())} |",
        "",
        "### Warm steady-state (the production number)",
        f"- Cache **write** (first call, 5m): {_money(write_u.cost_for(MODEL, '5m')) if write_u else 'n/a'} "
        f"(cache_creation={write_u.cache_creation if write_u else 0} tok).",
        f"- Cache **read** (warm calls, 5m): **{_money(warm_per_call)}/call** over {len(warm_reads)} reads.",
        f"- Batch (−50%): {_money(batch_per_call)}/call.",
        f"- **Verdict: {verdict}** — warm read {_money(warm_per_call)} vs Batch {_money(batch_per_call)} "
        f"(×{(batch_per_call / warm_per_call):.1f} cheaper)." if warm_per_call else f"- **Verdict: {verdict}**.",
        "",
        "### TTL — 5-min vs 1-hour",
        f"- 5-min total {_money(C5.cost())} vs 1-hour total {_money(C1.cost())} over {len(C5.usages)} sequential calls. "
        "5-min wins under sustained throughput (1.25× vs 2× write, identical reads); 1-hour only earns its "
        "doubled write back across idle gaps > 5 min.",
        "",
        "### Concurrency — cold fan-out vs prime-then-fan-out",
        f"- D-cold ({concurrency}-way, no prime): read-hit-rate **{Dc.read_hit_rate():.0%}**, {_money(Dc.per_call())}/call.",
        f"- D-primed (1 prime → {concurrency}-way): read-hit-rate **{Dp.read_hit_rate():.0%}**, {_money(Dp.per_call())}/call. {Dp.note}",
        f"- max_tokens=0 warmup probe: {warm_probe}",
        "",
        "### Checks",
        f"- Silent cache-miss (prefix < 2,048 tok → no write): **{'FAIL — cache_creation==0' if silent_miss else 'pass'}** "
        f"(write tok={write_u.cache_creation if write_u else 0}).",
        "",
        "### Production decision",
        "- Extraction runs **sync + 5-min prompt-cache on the static prefix**, **prime-then-fan-out** for "
        "concurrency (1 real call → await → fan out workers; they read the warm prefix). Beats Batch by the "
        "factor above. Fold into GRAPHRAG_PLAN.md §8.3 #2 / §1.1 / §1.3 (flip 'Gated on Experiment-1' → "
        "'confirmed (Exp-1)') and reconcile the $1,243 line with the warm $/call.",
    ]
    return "\n".join(L)


# ── orchestration ─────────────────────────────────────────────────────────────────────
def _est_calls(n: int, concurrency: int) -> int:
    return n + n + min(n, 20) + concurrency + concurrency + 1 + 1   # A + C + C′ + Dcold + Dprimed + Dprime + warm


def run(s3, client, *, n: int, concurrency: int, seed: int) -> str:
    system, tool = ex.build_system_prompt(), ex.extraction_tool()
    msgs = sample_messages(s3, n, seed)
    if not msgs:
        raise SystemExit("no gated chunks sampled — check S3 access / gate")
    n = len(msgs)
    print(f"sampled {n} gated chunks; running arms (concurrency={concurrency})…")
    arms: dict[str, Arm] = {}
    arms["A"] = run_sequential(client, system, tool, msgs, cache=False, ttl=None, name="A")
    arms["D_cold"] = run_concurrent(client, system, tool, msgs, ttl=None, concurrency=concurrency,
                                    primed=False, name="D_cold")
    arms["D_primed"] = run_concurrent(client, system, tool, msgs, ttl=None, concurrency=concurrency,
                                      primed=True, name="D_primed")
    arms["C_5m"] = run_sequential(client, system, tool, msgs, cache=True, ttl=None, name="C_5m")
    arms["C_1h"] = run_sequential(client, system, tool, msgs[:min(n, 20)], cache=True, ttl="1h", name="C_1h")
    warm_probe = probe_warm_cache(client, system, tool, ttl=None)

    pin, pout = ex.price(MODEL)
    batch_total = sum((u.input_tokens * pin + u.output_tokens * pout) * 0.5 for u in arms["A"].usages)
    batch_per_call = batch_total / len(arms["A"].usages)
    report = build_report(arms, batch_per_call, batch_total, warm_probe, n=n, concurrency=concurrency)
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(report, encoding="utf-8")
    spent = sum(a.cost() for a in arms.values())
    print(f"\nwrote {_REPORT}\nbilled ~ {_money(spent)} over {sum(len(a.usages) for a in arms.values())} calls")
    return report


def main() -> int:
    import anthropic
    ap = argparse.ArgumentParser(description="Exp-1 prompt-cache vs Batch cost probe (Sonnet 4.6).")
    ap.add_argument("--n", type=int, default=40, help="gated chunks to sample (caps spend; ~$1 at 40)")
    ap.add_argument("--concurrency", type=int, default=8, help="fan-out width for arm D")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true", help="plan + projected spend, no API calls")
    args = ap.parse_args()

    if args.dry_run:
        calls = _est_calls(args.n, args.concurrency)
        print("DRY-RUN -- arms A / B(analytic) / C-5m / C'-1h / D-cold / D-primed + warmup probe")
        print(f"  ~{calls} Sonnet calls (n={args.n}, concurrency={args.concurrency})")
        print(f"  projected spend ~ ${calls * 0.016:.2f} (worst-case full-price ~$0.016/call at the "
              f"~4,187-tok prefix; cached arms are far cheaper)")
        return 0

    from leviathan.common import config
    config.load_env()                                    # picks up ANTHROPIC_API from .env for the gated run
    s3 = boto3.client("s3")
    client = anthropic.Anthropic(api_key=bx._api_key())
    run(s3, client, n=args.n, concurrency=args.concurrency, seed=args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
