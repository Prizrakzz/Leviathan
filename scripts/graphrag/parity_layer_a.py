"""D-MW-8 LAYER A -- score-level Bedrock-vs-native-Cohere rerank parity, retrieval-free (~$0.10).

The question this answers, and ONLY this: does `_cohere_rerank_call` rank the same (query, docs)
the same way `_bedrock_rerank_call` does? Same model on both sides (cohere rerank-v3.5), so the
EXPECTATION is near-1.0 agreement; the gate exists to catch a silent model-version or score-
normalization skew before it changes which evidence reaches the reader. No retrieval, no LLM, no
walk -- the two leaves are called DIRECTLY.

PRE-COMMITTED PASS (printed against results every run, never re-derived after seeing them):
    mean Kendall tau >= 0.90  AND  mean top-10 overlap >= 0.90  AND  batch invariance <= 1e-6.

STEP-0 RUNS FIRST AND CAN STOP THE RUN. One 200-doc and one 600-doc bedrock probe assert
`len(response.results) == len(docs)`. This exists because the abort rule below MUST NOT be armed on
an undocumented API cap: if Bedrock caps results at, say, 100, then every >=200-doc probe returns a
mostly-floored score vector, the parity numbers measure the TRUNCATION, and a wave-pausing "gate
failure" would actually be a fact about the API that nobody had written down. A short count here is
reported as a DISCOVERED FACT (exit 3), not as a failure.

STEP-0 CANNOT GO THROUGH THE LEAF, AND THAT IS THE POINT. `_bedrock_rerank_call` floors unreturned
indices to 0.0 and returns len(docs) scores, so `len(leaf_result) == len(docs)` is VACUOUSLY true
no matter what the API returned. So step-0 issues its own raw `bedrock-agent-runtime.rerank`
request (same shape as the leaf's) and reads `len(resp["results"])` directly. In the arms, where
the shipped leaf IS the thing under measurement, a short count is detected by its own signature:
an EXACT 0.0 score is the leaf's floor sentinel. A genuine 0.0 from a float relevance model is not
distinguishable from a floored index -- and both are equally disqualifying, because either way the
vector being compared is not a ranking -- so any exact 0.0 aborts.

ABORT (exit 2) ON ANY EXCEPTION FROM EITHER LEAF. A parity run that degrades measures a mixture:
one throttled Bedrock call that silently fell back, or one retried Cohere call, and the tau being
reported is between "cohere" and "cohere plus something else". There is no partial-credit path.

BEDROCK ARM FENCING. The Bedrock rerank quota is 3 req/min and it is ACCOUNT-WIDE -- live serving
sits on the same bucket. An unfenced probe arm degrades production to a cold bge fallback AND has
its own calls throttled by production traffic, tripping its own abort. So: the run refuses to
start outside the 02:00-05:00 UTC window without --accept-degradation, paces at <= 2 req/min with
+-15% jitter, and builds a DEDICATED client with retries mode=standard / max_attempts=1 (adaptive's
client-side rate limiter would distort the pacing this arm depends on). The native arm is
free-running (1,000 req/min).

CLIENT OVERRIDE, STATED AS A DEVIATION. `_bedrock_rerank_call` takes no client argument; it uses a
module-level client built lazily with `mode=adaptive`. Env tuning can reach max_attempts but NOT
the retries MODE. So the dedicated client is installed into `rankers._bedrock_rerank_client` for
the DURATION of the arm and the previous value is restored on exit -- a scoped override, never a
permanent mutation of another importer's process state.

PROBES: 8 queries x doc-set sizes 10/60/200 = 24. Doc pools come from --probes (a JSON file:
[{"query": str, "docs": [str, ...]}, ...]) or are generated from the live evidence store when
EVIDENCE_S3 / EVIDENCE_BACKEND=pg is present. Neither -> a clear refusal, never invented text.

Exit codes: 0 = PASS; 1 = FAIL (a threshold or the invariance assertion missed) or a usage/config
refusal; 2 = ABORT (a leaf raised, or a floored score vector -- the run measured a mixture and is
reporting nothing); 3 = STEP-0 short count (an API result cap is a FACT; re-scope and re-run).
argparse itself also exits 2 on a malformed command line; the ABORT lines are unmistakable.

ASCII-only stdout (cp1252 console). The Cohere key is read but NEVER printed.

Usage:
    python scripts/graphrag/parity_layer_a.py --self-test                  # metrics only, no AWS
    python scripts/graphrag/parity_layer_a.py --probes probes.json --dry-run
    python scripts/graphrag/parity_layer_a.py --probes probes.json --step0-only
    python scripts/graphrag/parity_layer_a.py --probes probes.json --json out/layer_a.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
import time
from contextlib import contextmanager
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# PRE-COMMITTED, and deliberately module-level constants rather than flags with these defaults:
# a threshold that can be relaxed from the command line after seeing the numbers is not
# pre-committed. --thresholds exists only to TIGHTEN them in a later wave.
TAU_FLOOR = 0.90
OVERLAP_FLOOR = 0.90
INVARIANCE_TOL = 1e-6

DEFAULT_SIZES = (10, 60, 200)
DEFAULT_STEP0_SIZES = (200, 600)
DEFAULT_DECK = "configs/graphrag/eval_queries_contracts_ab_v1.yaml"
# 2 req/min against an account-wide 3/min bucket that live serving shares. The third slot is left
# to production ON PURPOSE.
DEFAULT_RPM = 2.0
JITTER = 0.15
OFF_HOURS_UTC = (2, 5)          # [start, end) -- the stated degradation window


# ==========================================================================================
# METRICS -- pure, no deps, --self-test'able. scipy is NOT a dependency of this estate and a
# parity gate must not acquire one; tau-a is 12 lines of arithmetic.
# ==========================================================================================
def kendall_tau_a(x, y) -> float:
    """Kendall's tau-a over two score vectors, O(n^2), exact.

    tau-a (NOT tau-b) on purpose: tau-b divides by a tie-corrected denominator, which INFLATES
    agreement exactly when one arm has produced a tie-heavy vector -- and a tie-heavy vector is the
    signature of the truncation this gate is built to catch. tau-a's denominator is the full pair
    count, so ties are neutral pairs that drag the coefficient DOWN. If the two arms disagree
    because one of them stopped ranking, this number must fall.
    """
    n = len(x)
    if n != len(y):
        raise ValueError("kendall_tau_a: length mismatch %d vs %d" % (n, len(y)))
    if n < 2:
        return 1.0
    num = 0
    for i in range(n - 1):
        xi, yi = x[i], y[i]
        for j in range(i + 1, n):
            a = xi - x[j]
            b = yi - y[j]
            if a > 0 and b > 0 or a < 0 and b < 0:
                num += 1
            elif a > 0 and b < 0 or a < 0 and b > 0:
                num -= 1
            # equal on either side == a tied pair == 0, counted in the denominator below
    return num / (n * (n - 1) / 2.0)


def top_k_indices(scores, k: int) -> list[int]:
    """The k highest-scoring doc indices. Ties break by ORIGINAL INDEX ascending on both arms, so a
    tie never manufactures a disagreement the models did not have."""
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    return order[:k]


def top_k_overlap(a, b, k: int = 10) -> tuple[float, int, bool]:
    """-> (overlap fraction, effective k, vacuous?).

    VACUOUS IS REPORTED, NOT HIDDEN. When a probe has <= k docs both "top-k" sets are the whole
    doc set and the overlap is 1.0 by construction -- it measures nothing. The 10-doc probe size is
    exactly that case, so a mean over all 24 probes would carry 8 free 1.0s. The flag lets the
    summary state the honest denominator."""
    eff = min(k, len(a), len(b))
    if eff <= 0:
        return 1.0, 0, True
    sa, sb = set(top_k_indices(a, eff)), set(top_k_indices(b, eff))
    return len(sa & sb) / float(eff), eff, eff >= max(len(a), len(b))


def max_abs_diff(a, b) -> float:
    if len(a) != len(b):
        raise ValueError("max_abs_diff: length mismatch %d vs %d" % (len(a), len(b)))
    return max((abs(p - q) for p, q in zip(a, b)), default=0.0)


def floored(scores) -> int:
    """Count of EXACT 0.0 scores == the leaf's unreturned-index floor sentinel (see the module
    docstring for why a genuine 0.0 is treated identically)."""
    return sum(1 for s in scores if s == 0.0)


# ==========================================================================================
# PROBES
# ==========================================================================================
class Probe:
    __slots__ = ("pid", "query", "docs", "size", "pool")

    def __init__(self, pid: str, query: str, docs: list[str], pool: str):
        self.pid = pid
        self.query = query
        self.docs = docs
        self.size = len(docs)
        self.pool = pool


def load_pools(path: str) -> list[dict]:
    """--probes file -> [{"query":..., "docs":[...]}]. Each entry is a doc POOL; the harness slices
    it into the configured sizes, so the same file drives 10/60/200 without repeating text."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise SystemExit("--probes %s: expected a non-empty JSON list of "
                         '{"query": str, "docs": [str]}' % path)
    pools = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or "query" not in item or "docs" not in item:
            raise SystemExit('--probes %s entry %d: needs "query" and "docs"' % (path, i))
        docs = [str(d) for d in item["docs"] if str(d).strip()]
        pools.append({"query": str(item["query"]), "docs": docs,
                      "id": str(item.get("id") or "q%d" % (i + 1))})
    return pools


def _node_texts(node: str, cap: int, seed: int) -> list[str]:
    """Real evidence text for one node, from whichever store this process is pointed at.

    Deterministic given (node, cap, seed): a seeded sample over a stably-ordered read, so a re-run
    measures the SAME probes. A prefix slice would draw the whole pool from one document."""
    texts: list[str] = []
    if os.environ.get("EVIDENCE_BACKEND") == "pg":
        from leviathan.graphrag import pgstore
        conn = pgstore.connect()
        table = pgstore.table_name()
        with conn.cursor() as cur:
            cur.execute("SELECT text FROM %s WHERE node = %%s ORDER BY id LIMIT %%s" % table,
                        (node, cap * 10))
            texts = [r[0] for r in cur.fetchall() if r and r[0]]
    else:
        from leviathan.graphrag import evidence
        texts = [r.get("text") or "" for r in evidence.load_index(node)]
    texts = [t for t in dict.fromkeys(t.strip() for t in texts) if t]
    if len(texts) <= cap:
        return texts
    return random.Random(seed).sample(texts, cap)


def pools_from_evidence(deck: str, n_queries: int, cap: int, seed: int) -> list[dict]:
    """Deck rows -> (question, that contract's evidence slice). The deck is the contracts_ab
    covenant deck by default, so Layer A's docs are the SAME corpus Layer B will answer over."""
    if not (os.environ.get("EVIDENCE_S3") or os.environ.get("EVIDENCE_BACKEND") == "pg"):
        raise SystemExit(
            "no probe source: pass --probes <file>, or point this process at the evidence store "
            "(EVIDENCE_S3=s3://... , or EVIDENCE_BACKEND=pg with EVIDENCE_PG_DSN). This harness "
            "will not invent document text -- a parity number measured over synthetic docs is not "
            "a statement about the corpus the reader sees.")
    import yaml
    from leviathan.graphrag import evidence

    path = Path(deck)
    if not path.is_absolute():
        path = _REPO_ROOT / deck
    rows = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("queries") or []
    pools: list[dict] = []
    for row in rows:
        if len(pools) >= n_queries:
            break
        contract = row.get("contract")
        question = row.get("question")
        if not (contract and question):
            continue
        try:
            node = evidence.node_for(contract)
            docs = _node_texts(node, cap, seed)
        except Exception as exc:  # noqa: BLE001 -- a thin/absent slice skips its row, loudly
            print("  skip %s (%s): %s: %s" % (row.get("id"), contract, type(exc).__name__,
                                              str(exc)[:120]))
            continue
        if not docs:
            print("  skip %s (%s): node %s has no props" % (row.get("id"), contract, node))
            continue
        pools.append({"query": question, "docs": docs, "id": str(row.get("id") or contract)})
    if len(pools) < n_queries:
        print("WARN: %d pool(s) built from %s, %d requested -- the probe count below is the "
              "REAL denominator" % (len(pools), deck, n_queries))
    return pools


def expand(pools: list[dict], sizes) -> list[Probe]:
    """Pools x sizes -> probes. A pool shorter than a requested size is a REFUSAL, not a silent
    downsize: quietly scoring 137 docs and labelling the row '200' is how a gate stops measuring
    what its own report says it measured."""
    short = [(p["id"], len(p["docs"])) for p in pools if len(p["docs"]) < max(sizes)]
    if short:
        raise SystemExit("these pools are shorter than the largest requested size (%d): %s"
                         % (max(sizes), ", ".join("%s=%d" % s for s in short)))
    out = []
    for p in pools:
        for n in sizes:
            out.append(Probe("%s@%d" % (p["id"], n), p["query"], list(p["docs"][:n]), p["id"]))
    return out


# ==========================================================================================
# ARMS
# ==========================================================================================
class Pacer:
    """Minimum spacing between calls, with +-JITTER on the interval.

    Jitter is not cosmetic: an exactly-periodic 30 s probe train against a shared token bucket
    beats against live serving's own cadence. The pacer sleeps only for the REMAINING gap, so the
    time a call itself takes is credited against the interval."""

    def __init__(self, rpm: float, seed: int = 0):
        self.interval = 60.0 / rpm if rpm > 0 else 0.0
        self.rng = random.Random(seed)
        self.last = 0.0
        self.slept = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        target = self.interval * (1.0 + self.rng.uniform(-JITTER, JITTER))
        gap = target - (time.monotonic() - self.last) if self.last else 0.0
        if gap > 0:
            time.sleep(gap)
            self.slept += gap
        self.last = time.monotonic()


def _rankers():
    """Import the shipped leaves. src/ is added to sys.path only if the package is not installed."""
    try:
        from leviathan.graphrag import rankers
    except ImportError:
        sys.path.insert(0, str(_REPO_ROOT / "src"))
        from leviathan.graphrag import rankers
    return rankers


def leaf(name: str):
    rk = _rankers()
    fn = getattr(rk, name, None)
    if fn is None:
        raise SystemExit("leviathan.graphrag.rankers has no %s -- D-MW-2 has not landed yet. Layer "
                         "A cannot measure a leaf that does not exist." % name)
    return fn


def probe_client(region: str):
    """The DEDICATED bedrock-agent-runtime client for this harness.

    mode=standard + max_attempts=1: adaptive's client-side rate limiter reshapes request timing,
    and this arm's whole validity rests on ITS pacing being the pacing. max_attempts=1 also makes
    the abort rule real -- a retried throttle would otherwise be absorbed and the run would report
    parity for a call that had already been rate-limited once."""
    import boto3
    from botocore.config import Config
    return boto3.client("bedrock-agent-runtime", region_name=region,
                        config=Config(retries={"mode": "standard", "max_attempts": 1}))


@contextmanager
def bedrock_client_override(client):
    """Install `client` as the leaf's client for the duration, then restore. See the module
    docstring: the leaf takes no client argument and env cannot reach the retries MODE, so a scoped
    override is the only way to measure the SHIPPED leaf under the fencing this arm requires."""
    rk = _rankers()
    prev = getattr(rk, "_bedrock_rerank_client", None)
    rk._bedrock_rerank_client = client
    try:
        yield
    finally:
        rk._bedrock_rerank_client = prev


def raw_bedrock_rerank(client, model_arn: str, query: str, docs: list[str],
                       max_chars: int) -> tuple[list[float], int]:
    """ONE raw rerank request, mirroring `_bedrock_rerank_call`'s body, returning the RESPONSE's
    result count alongside the aligned scores. This is step-0's whole reason to exist: the leaf
    cannot report a short count because it floors it away."""
    q = (((query or "").strip()) or " ")[:max_chars]
    chunk = [(((t or "").strip()) or " ")[:max_chars] for t in docs]
    resp = client.rerank(
        queries=[{"type": "TEXT", "textQuery": {"text": q}}],
        sources=[{"type": "INLINE", "inlineDocumentSource": {"type": "TEXT",
                                                             "textDocument": {"text": d}}}
                 for d in chunk],
        rerankingConfiguration={
            "type": "BEDROCK_RERANKING_MODEL",
            "bedrockRerankingConfiguration": {
                "numberOfResults": len(chunk),
                "modelConfiguration": {"modelArn": model_arn},
            },
        },
    )
    results = resp.get("results", []) or []
    scores = [0.0] * len(chunk)
    for r in results:
        i = r.get("index")
        if isinstance(i, int) and 0 <= i < len(scores):
            scores[i] = float(r.get("relevanceScore", 0.0))
    return scores, len(results)


def cohere_key_present() -> bool:
    """The D-MW-3 dual-name read (.env carries COHERE_API, the ECS secret mounts COHERE_API_KEY).
    Presence only -- the value is never returned, logged, or written to the report."""
    return bool(os.environ.get("COHERE_API") or os.environ.get("COHERE_API_KEY"))


class Abort(Exception):
    """A leaf raised, or returned a vector that is not a ranking. Never caught into a partial run."""


def call_arm(fn, arm: str, probe_id: str, query: str, docs: list[str], pacer=None) -> list[float]:
    if pacer is not None:
        pacer.wait()
    try:
        scores = list(fn(query, docs))
    except Exception as exc:  # noqa: BLE001 -- deliberately total; see Abort
        raise Abort("%s arm raised on %s (%d docs): %s: %s"
                    % (arm, probe_id, len(docs), type(exc).__name__, str(exc)[:200])) from exc
    # SIGNATURE PARITY (the D-DR stub-lied-signature lesson): a leaf that returns the wrong length
    # is a defect to surface here, not a shape to coerce.
    if len(scores) != len(docs):
        raise Abort("%s arm returned %d scores for %d docs on %s -- the leaf contract is broken"
                    % (arm, len(scores), len(docs), probe_id))
    n_floored = floored(scores)
    if n_floored:
        raise Abort("%s arm returned %d exact-0.0 score(s) of %d on %s -- that is the short-count "
                    "floor sentinel, so this vector is a truncation, not a ranking"
                    % (arm, n_floored, len(scores), probe_id))
    return scores


# ==========================================================================================
# RUN
# ==========================================================================================
def step0(client, model_arn: str, max_chars: int, query: str, docs_pool: list[str], sizes,
          pacer) -> dict:
    """The fact-finder. Returns {"ok": bool, "checks": [...]}; a short count is a FACT, not a fail.

    Uses a REAL probe query and real pooled docs: a result cap could in principle depend on the
    request, and a synthetic request would establish the fact for a request nobody makes."""
    checks = []
    for n in sizes:
        docs = list(docs_pool[:n])
        padded = 0
        while len(docs) < n:
            # Only ever reached when the corpus itself is thin. Pads are MARKED in the report so
            # "600 docs" is never read as "600 real evidence props".
            docs.append("padding document %d for the result-count fact-finder" % len(docs))
            padded += 1
        pacer.wait()
        try:
            _scores, n_results = raw_bedrock_rerank(client, model_arn, query, docs, max_chars)
        except Exception as exc:  # noqa: BLE001
            raise Abort("step-0 raised at %d docs: %s: %s"
                        % (n, type(exc).__name__, str(exc)[:200])) from exc
        checks.append({"docs": n, "results": n_results, "padded": padded,
                       "ok": n_results == n})
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def invariance_targets(probes, chunk: int, limit: int) -> list:
    """Which probes get re-scored in chunks. ONE definition, read by both the up-front cost
    estimate and the run itself -- two copies of this rule is how a printed estimate stops
    describing the run it precedes."""
    eligible = [p for p in probes if p.size >= chunk * 2]
    return eligible[:max(0, limit)]


def invariance_call_count(probes, chunk: int, limit: int) -> int:
    """Extra PACED bedrock calls the invariance check costs (the cohere side is free-running)."""
    return sum((p.size + chunk - 1) // chunk for p in invariance_targets(probes, chunk, limit))


def measure(probes, bed_fn, coh_fn, pacer, *, invariance_probes: int, chunk: int) -> dict:
    """Both arms over every probe + the batch-invariance check. Raises Abort; never degrades."""
    rows = []
    inv = []
    targets = {id(p) for p in invariance_targets(probes, chunk, invariance_probes)}
    for probe in probes:
        b = call_arm(bed_fn, "bedrock", probe.pid, probe.query, probe.docs, pacer=pacer)
        c = call_arm(coh_fn, "cohere", probe.pid, probe.query, probe.docs, pacer=None)
        ov, eff_k, vacuous = top_k_overlap(b, c, 10)
        rows.append({"probe": probe.pid, "pool": probe.pool, "docs": probe.size,
                     "tau": kendall_tau_a(b, c), "top10_overlap": ov, "overlap_k": eff_k,
                     "overlap_vacuous": vacuous})
        # BATCH INVARIANCE, LIVE. The coalescer's entire licence is that cross-encoder scoring is
        # pointwise, so batching across nodes is SCORE-IDENTICAL (rankers.py:148). D-MW-7 pins that
        # against a stub; this pins it against the real APIs, on the size that matters.
        if id(probe) in targets:
            parts_b: list[float] = []
            parts_c: list[float] = []
            for lo in range(0, probe.size, chunk):
                sl = probe.docs[lo:lo + chunk]
                pid = "%s[%d:%d]" % (probe.pid, lo, lo + len(sl))
                parts_b += call_arm(bed_fn, "bedrock", pid, probe.query, sl, pacer=pacer)
                parts_c += call_arm(coh_fn, "cohere", pid, probe.query, sl, pacer=None)
            inv.append({"probe": probe.pid, "docs": probe.size, "chunk": chunk,
                        "bedrock_max_abs_diff": max_abs_diff(b, parts_b),
                        "cohere_max_abs_diff": max_abs_diff(c, parts_c)})
    return {"probes": rows, "invariance": inv}


def summarize(measured: dict) -> dict:
    rows = measured["probes"]
    inv = measured["invariance"]
    taus = [r["tau"] for r in rows]
    ovs = [r["top10_overlap"] for r in rows]
    real_ovs = [r["top10_overlap"] for r in rows if not r["overlap_vacuous"]]
    worst = max((max(i["bedrock_max_abs_diff"], i["cohere_max_abs_diff"]) for i in inv),
                default=0.0)
    mean_tau = sum(taus) / len(taus) if taus else 0.0
    mean_ov = sum(ovs) / len(ovs) if ovs else 0.0
    out = {
        "n_probes": len(rows),
        "mean_tau": mean_tau,
        "min_tau": min(taus) if taus else 0.0,
        "mean_top10_overlap": mean_ov,
        # The honest cut: probes whose doc count exceeds 10, i.e. where a top-10 set is a CHOICE.
        "mean_top10_overlap_nonvacuous": (sum(real_ovs) / len(real_ovs)) if real_ovs else None,
        "n_nonvacuous_overlap": len(real_ovs),
        "min_top10_overlap": min(ovs) if ovs else 0.0,
        "batch_invariance_worst_abs_diff": worst,
        "batch_invariance_ok": bool(inv) and worst <= INVARIANCE_TOL,
        "batch_invariance_measured": len(inv),
        "thresholds": {"tau": TAU_FLOOR, "top10_overlap": OVERLAP_FLOOR,
                       "invariance_abs": INVARIANCE_TOL},
    }
    out["tau_pass"] = out["mean_tau"] >= TAU_FLOOR
    # Diff-review catch (the D-CC vacuous-pin class): the 10-doc probes score top-10 overlap 1.0 BY
    # CONSTRUCTION (a top-10 of a 10-doc list is the whole list, whatever the order), which would let the
    # 16 real probes average 0.85 and still 'pass' a 0.90 floor over all 24. The GATED number is the
    # non-vacuous mean; the all-probe mean stays reported-but-ungated.
    out["overlap_pass"] = (out["mean_top10_overlap_nonvacuous"] is not None
                          and out["mean_top10_overlap_nonvacuous"] >= OVERLAP_FLOOR)
    out["pass"] = bool(out["tau_pass"] and out["overlap_pass"] and out["batch_invariance_ok"])
    return out


def render(report: dict) -> list[str]:
    s = report["summary"]
    out = ["", "LAYER A -- bedrock vs cohere rerank parity", ""]
    by_size: dict = {}
    for r in report["probes"]:
        b = by_size.setdefault(r["docs"], [])
        b.append(r)
    out.append("  %-8s %-7s %-9s %-9s %s" % ("docs", "probes", "mean_tau", "min_tau", "mean_top10"))
    out.append("  " + "-" * 52)
    for n in sorted(by_size):
        rows = by_size[n]
        taus = [r["tau"] for r in rows]
        ovs = [r["top10_overlap"] for r in rows]
        note = "  (top-10 vacuous: probe has <= 10 docs)" if all(r["overlap_vacuous"]
                                                                for r in rows) else ""
        out.append("  %-8d %-7d %-9.4f %-9.4f %.4f%s"
                   % (n, len(rows), sum(taus) / len(taus), min(taus), sum(ovs) / len(ovs), note))
    out.append("")
    for i in report.get("invariance") or []:
        out.append("  batch invariance %s: whole vs %d-doc chunks -- bedrock max|d|=%.3e, "
                   "cohere max|d|=%.3e (tol %.0e)"
                   % (i["probe"], i["chunk"], i["bedrock_max_abs_diff"],
                      i["cohere_max_abs_diff"], INVARIANCE_TOL))
    if not report.get("invariance"):
        out.append("  batch invariance: NOT MEASURED -- no probe was large enough to chunk")
    out.append("")
    out.append("  PRE-COMMITTED  %-27s: %8.4f  %s"
               % ("mean tau >= %.2f" % TAU_FLOOR, s["mean_tau"],
                  "PASS" if s["tau_pass"] else "FAIL"))
    _nv = s["mean_top10_overlap_nonvacuous"]
    out.append("  PRE-COMMITTED  %-27s: %8s  %s"
               % ("top-10 overlap >= %.2f" % OVERLAP_FLOOR,
                  ("%.4f" % _nv) if _nv is not None else "n/a",
                  "PASS" if s["overlap_pass"] else "FAIL"))
    out.append("                 (GATED on the %d non-vacuous probe(s); all-probe mean %.4f is "
               "reported, not gated -- <=10-doc probes overlap 1.0 by construction)"
               % (s["n_nonvacuous_overlap"], s["mean_top10_overlap"]))
    out.append("  PRE-COMMITTED  %-27s: %8.3e  %s"
               % ("batch invariance <= %.0e" % INVARIANCE_TOL,
                  s["batch_invariance_worst_abs_diff"],
                  "PASS" if s["batch_invariance_ok"] else "FAIL"))
    out.append("")
    out.append("  LAYER A: %s" % ("PASS" if s["pass"] else "FAIL"))
    if not s["pass"]:
        out.append("  TERMINATION RULE (pre-committed): ONE diagnosis cycle is permitted -- this "
                   "is deterministic arithmetic, not a measurement window. A second failure means "
                   "serving STAYS on bedrock, the result is recorded, and the wave pauses.")
    return out


def self_test() -> int:
    """The instrument checks itself before it is used to judge anything."""
    fails = []

    def eq(label, got, want, tol=1e-12):
        if abs(got - want) > tol:
            fails.append("%s: got %r want %r" % (label, got, want))

    eq("identical", kendall_tau_a([3.0, 2.0, 1.0], [3.0, 2.0, 1.0]), 1.0)
    eq("reversed", kendall_tau_a([3.0, 2.0, 1.0], [1.0, 2.0, 3.0]), -1.0)
    eq("monotone-transform", kendall_tau_a([1.0, 2.0, 3.0, 4.0], [0.1, 0.4, 0.5, 0.9]), 1.0)
    # one swapped adjacent pair out of 6 pairs -> (5-1)/6
    eq("one-swap", kendall_tau_a([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 4.0, 3.0]), 4.0 / 6.0)
    # all-tied second vector: every pair is neutral -> tau-a 0.0 (tau-b would report 1.0/NaN)
    eq("all-tied", kendall_tau_a([1.0, 2.0, 3.0], [7.0, 7.0, 7.0]), 0.0)
    eq("singleton", kendall_tau_a([1.0], [9.0]), 1.0)

    ov, k, vac = top_k_overlap([5.0, 4.0, 3.0], [3.0, 4.0, 5.0], 10)
    eq("overlap-vacuous", ov, 1.0)
    if not vac or k != 3:
        fails.append("overlap-vacuous flags: k=%r vacuous=%r" % (k, vac))
    a = [float(i) for i in range(20)]                  # top-10 = indices 19..10
    b = [float(i) for i in range(20)]
    b[10], b[0] = 0.0, 10.0                            # index 10 falls out, index 0 comes in
    ov, k, vac = top_k_overlap(a, b, 10)
    eq("overlap-9of10", ov, 0.9)
    if vac or k != 10:
        fails.append("overlap-9of10 flags: k=%r vacuous=%r" % (k, vac))
    if top_k_indices([1.0, 1.0, 1.0], 2) != [0, 1]:
        fails.append("tie-break is not index-ascending")
    eq("max_abs_diff", max_abs_diff([1.0, 2.0], [1.0, 2.5]), 0.5)
    if floored([0.1, 0.0, 0.2]) != 1:
        fails.append("floored() miscounts the 0.0 sentinel")

    p = expand([{"id": "q", "query": "Q", "docs": [str(i) for i in range(200)]}], (10, 60, 200))
    if [x.size for x in p] != [10, 60, 200] or p[0].pid != "q@10":
        fails.append("expand() shape: %r" % [x.pid for x in p])

    for line in fails:
        print("  FAIL " + line)
    print("self-test: %d check(s) failed" % len(fails) if fails else "self-test: OK")
    return 1 if fails else 0


def _write_report(report: dict, path: str) -> None:
    """EVERY report write goes through here (diff-review catch: the ABORT and step-0-short paths wrote
    without creating the parent dir, so a missing out/ turned exit 2/3 -- the codes the termination rule
    branches on -- into an unhandled FileNotFoundError exit 1, destroying the record on exactly the paths
    that needed it)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probes", help='JSON file: [{"query": str, "docs": [str, ...]}, ...]. Each '
                                     "entry is a doc POOL, sliced into --sizes.")
    ap.add_argument("--deck", default=DEFAULT_DECK,
                    help="deck to draw queries from when generating pools from the evidence store")
    ap.add_argument("--queries", type=int, default=8, help="pools to build (default 8)")
    ap.add_argument("--sizes", default=",".join(str(n) for n in DEFAULT_SIZES))
    ap.add_argument("--step0-sizes", default=",".join(str(n) for n in DEFAULT_STEP0_SIZES))
    ap.add_argument("--chunk", type=int, default=None,
                    help="batch-invariance split size. Default: max(sizes)//4, so re-scoping --sizes "
                         "below a discovered result cap keeps invariance measurable (diff-review "
                         "catch: a fixed 50 made sizes under 100 silently unmeasurable, and "
                         "unmeasurable was scored as FAIL)")
    ap.add_argument("--invariance-probes", type=int, default=1,
                    help="how many large probes to re-score in chunks (each costs 2x --chunk "
                         "extra PACED bedrock calls)")
    ap.add_argument("--rpm", type=float, default=DEFAULT_RPM,
                    help="bedrock arm pacing, requests/min (the quota is 3/min ACCOUNT-WIDE and "
                         "live serving shares it)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--json", dest="json_out", help="write the full report here")
    ap.add_argument("--step0-only", action="store_true",
                    help="run the result-count fact-finder and stop (2 bedrock calls)")
    ap.add_argument("--accept-degradation", action="store_true",
                    help="run the bedrock arm OUTSIDE 02:00-05:00 UTC, accepting that live "
                         "serving degrades to bge for the duration")
    ap.add_argument("--dry-run", action="store_true",
                    help="build probes, print the plan and the cost/wall-clock estimate, call "
                         "nothing")
    ap.add_argument("--self-test", action="store_true",
                    help="verify the metric implementations and exit (no AWS, no key)")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    sizes = tuple(int(x) for x in args.sizes.split(",") if x.strip())
    step0_sizes = tuple(int(x) for x in args.step0_sizes.split(",") if x.strip())
    pool_cap = max(sizes + step0_sizes)
    if args.chunk is None:
        args.chunk = max(1, max(sizes) // 4)               # derived, so --sizes re-scopes stay measurable

    # ---- probes ------------------------------------------------------------------------
    if args.probes:
        pools = load_pools(args.probes)
        source = "file:%s" % args.probes
    else:
        pools = pools_from_evidence(args.deck, args.queries, pool_cap, args.seed)
        source = "evidence:%s" % ("pg" if os.environ.get("EVIDENCE_BACKEND") == "pg" else "s3")
    if not pools:
        raise SystemExit("no probe pools were built -- nothing to measure")
    probes = expand(pools, sizes)
    step0_pool = [d for p in pools for d in p["docs"]]

    n_inv_calls = invariance_call_count(probes, args.chunk, args.invariance_probes)
    n_inv = len(invariance_targets(probes, args.chunk, args.invariance_probes))
    bedrock_calls = len(probes) + len(step0_sizes) + n_inv_calls
    est_min = bedrock_calls * (60.0 / args.rpm) / 60.0 if args.rpm > 0 else 0.0

    print("probe source : %s (%d pool(s) x sizes %s -> %d probes)"
          % (source, len(pools), ",".join(str(n) for n in sizes), len(probes)))
    print("bedrock calls: %d (step-0 %d + probes %d + invariance %d over %d probe(s)) at <= "
          "%.1f/min with +-%d%% jitter -> ~%.0f min"
          % (bedrock_calls, len(step0_sizes), len(probes), n_inv_calls, n_inv, args.rpm,
             int(JITTER * 100), est_min))
    print("cohere calls : %d (free-running; 1,000 req/min)" % (len(probes) + n_inv_calls))
    print("thresholds   : mean tau >= %.2f, mean top-10 overlap >= %.2f, batch invariance <= %.0e"
          % (TAU_FLOOR, OVERLAP_FLOOR, INVARIANCE_TOL))

    if args.dry_run:
        print("")
        print("DRY RUN -- no API call was made.")
        return 0

    # ---- fencing -----------------------------------------------------------------------
    # Derived from the timestamp, never hand-labelled (the estate law: this laptop renders +03:00).
    now = dt.datetime.now(dt.timezone.utc)
    in_window = OFF_HOURS_UTC[0] <= now.hour < OFF_HOURS_UTC[1]
    if in_window:
        print("window       : %s UTC is inside the %02d:00-%02d:00 off-hours window; live serving "
              "may still degrade to bge while this runs (stated and accepted)"
              % (now.strftime("%Y-%m-%dT%H:%M:%SZ"), *OFF_HOURS_UTC))
    elif args.accept_degradation:
        print("window       : %s UTC is OUTSIDE %02d:00-%02d:00; --accept-degradation given, so "
              "live serving degrading to a COLD bge fallback for ~%.0f min is accepted"
              % (now.strftime("%Y-%m-%dT%H:%M:%SZ"), *OFF_HOURS_UTC, est_min))
    else:
        raise SystemExit(
            "REFUSING: it is %s UTC and the bedrock arm shares a 3/min ACCOUNT-WIDE quota with "
            "live serving. Outside %02d:00-%02d:00 UTC this run degrades production to a cold bge "
            "fallback for ~%.0f min AND has its own calls throttled by production traffic, which "
            "trips its own abort rule. Re-run in the window, or pass --accept-degradation to state "
            "that you accept it." % (now.strftime("%Y-%m-%dT%H:%M:%SZ"), OFF_HOURS_UTC[0],
                                     OFF_HOURS_UTC[1], est_min))

    # ---- key pre-flight (before a single billed bedrock call) --------------------------
    try:
        from leviathan.common import config as _cfg
        _cfg.load_env()
    except Exception:  # noqa: BLE001 -- cloud runtimes have no .env; env vars are already set
        pass
    if not cohere_key_present():
        raise SystemExit("no cohere key: set COHERE_API (local .env) or COHERE_API_KEY (the ECS "
                         "secret name). Refusing BEFORE spending the bedrock arm -- a keyless run "
                         "would abort halfway and bill the expensive side for nothing.")

    rk = _rankers()
    bed_fn = leaf("_bedrock_rerank_call")
    coh_fn = leaf("_cohere_rerank_call")
    # Diff-review catch: resolve BOTH models through the SAME env > params > code-default precedence the
    # leaves use, so the report records the model actually scored. (The first cut read a rankers
    # attribute that does not exist -- _DEFAULT_RERANK_MODEL_COHERE vs the real
    # _DEFAULT_COHERE_RERANK_MODEL -- and skipped the params layer, which is image-baked and private.)
    max_chars = 2000
    try:
        from leviathan.graphrag import params as _pr
        max_chars = int(_pr.get("serving.retrieval.rerank_max_chars", 2000))
        model_arn = (os.environ.get("GRAPHRAG_RERANK_MODEL")
                     or _pr.get("serving.retrieval.rerank_model",
                                getattr(rk, "_DEFAULT_RERANK_MODEL", "")))
        cohere_model = (os.environ.get("GRAPHRAG_RERANK_MODEL_COHERE")
                        or _pr.get("serving.retrieval.rerank_model_cohere",
                                   getattr(rk, "_DEFAULT_COHERE_RERANK_MODEL", "rerank-v3.5")))
    except Exception:  # noqa: BLE001
        model_arn = (os.environ.get("GRAPHRAG_RERANK_MODEL")
                     or getattr(rk, "_DEFAULT_RERANK_MODEL", ""))
        cohere_model = (os.environ.get("GRAPHRAG_RERANK_MODEL_COHERE")
                        or getattr(rk, "_DEFAULT_COHERE_RERANK_MODEL", "rerank-v3.5"))

    pacer = Pacer(args.rpm, seed=args.seed)
    client = probe_client(args.region)
    started = time.time()
    report: dict = {
        "run": {
            "started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "probe_source": source, "sizes": list(sizes), "n_probes": len(probes),
            "bedrock_model": model_arn, "cohere_model": cohere_model,
            "rpm": args.rpm, "jitter": JITTER, "seed": args.seed,
            "off_hours_window_utc": list(OFF_HOURS_UTC), "in_window": in_window,
            "region": args.region, "rerank_max_chars": max_chars,
        },
    }

    # ---- STEP-0: the fact, first -------------------------------------------------------
    try:
        # No client override here ON PURPOSE: step-0 does not go through the leaf (it cannot -- the
        # leaf floors the very count step-0 exists to read), so it drives `client` directly.
        s0 = step0(client, model_arn, max_chars, pools[0]["query"], step0_pool, step0_sizes, pacer)
    except Abort as exc:
        print("")
        print("ABORT: %s" % exc)
        report["abort"] = str(exc)
        if args.json_out:
            _write_report(report, args.json_out)           # an aborted fact-finder still leaves a record
        return 2
    report["step0"] = s0
    print("")
    for c in s0["checks"]:
        print("  step-0 %4d docs -> %4d results  %s%s"
              % (c["docs"], c["results"], "OK" if c["ok"] else "SHORT",
                 "  (%d padding doc(s): the corpus pool was thinner than this size)" % c["padded"]
                 if c["padded"] else ""))
    if not s0["ok"]:
        cap = min(c["results"] for c in s0["checks"] if not c["ok"])
        print("")
        print("STOP -- STEP-0 SHORT COUNT. Bedrock returned at most %d results for a larger doc "
              "set. This is a DISCOVERED API FACT, not a gate failure: with a result cap in play, "
              "every probe above it scores a mostly-floored vector and Layer A would measure the "
              "truncation and call it parity. Record the cap, re-scope --sizes below it (--chunk "
              "re-derives itself from the new sizes), and re-run. Do NOT arm the abort rule "
              "against it." % cap)
        if args.json_out:
            _write_report(report, args.json_out)
        return 3
    if args.step0_only:
        print("")
        print("--step0-only: the result-count fact is established; the arms were not run.")
        if args.json_out:
            _write_report(report, args.json_out)
        return 0

    # ---- the arms ----------------------------------------------------------------------
    try:
        with bedrock_client_override(client):
            measured = measure(probes, bed_fn, coh_fn, pacer,
                               invariance_probes=args.invariance_probes, chunk=args.chunk)
    except Abort as exc:
        print("")
        print("ABORT: %s" % exc)
        print("       Nothing is reported. A run that degraded on either arm measures a MIXTURE, "
              "and a mixture reported as parity is exactly what this gate exists to prevent.")
        if args.json_out:
            report["abort"] = str(exc)
            _write_report(report, args.json_out)
        return 2

    report.update(measured)
    report["summary"] = summarize(measured)
    report["run"]["wall_clock_s"] = round(time.time() - started, 1)
    report["run"]["paced_sleep_s"] = round(pacer.slept, 1)
    for line in render(report):
        print(line)
    if args.json_out:
        _write_report(report, args.json_out)
        print("")
        print("report: %s" % args.json_out)
    s = report["summary"]
    if not s["batch_invariance_measured"]:
        # Diff-review catch: unmeasurable is NOT the same verdict as failed -- a probe set with no
        # chunkable member must not print the TERMINATION RULE for a reason that has nothing to do
        # with parity. Distinct exit code; the operator widens --sizes or lowers --chunk.
        print("")
        print("BATCH INVARIANCE: NOT MEASURED (no probe >= 2x chunk=%d). Widen --sizes or lower "
              "--chunk; this is exit 4, NOT a parity FAIL." % args.chunk)
        return 4
    return 0 if s["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
