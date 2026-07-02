"""Free retrieval-only A/B for the hybrid / rerank / MMR arms (no LLM, no spend).

For a small probe set with KNOWN distinctive tokens, retrieve top-k with each arm and score deterministically:
exact-token hit@k, rank of the first token-bearing prop, and top-k source diversity — so we can see whether
the lexical (recall), cross-encoder (precision), and MMR (diversity) knobs actually help BEFORE any billed
end-to-end judge run. Loads slices from S3 (memoized) + downloads bge-reranker once; $0.

    EVIDENCE_S3=s3://... python -m leviathan.graphrag.retrieval_ab
"""
from __future__ import annotations

from leviathan.graphrag import evidence as ev

# (query, evidence node, a distinctive token that SHOULD be retrievable). Tokens chosen from the driver-slice
# coverage so they're known-present (safrinha 833, biodiesel 769, tariff 2555, drought 1329, crush, b40).
PROBES = [
    ("Indonesia raised the biodiesel blend to B40", "palm_oil", "b40"),
    ("safrinha second corn crop in Brazil", "corn", "safrinha"),
    ("soybean crush margin economics", "soybeans", "crush"),
    ("biodiesel mandate lifting vegetable oil demand", "soybean_oil", "biodiesel"),
    ("import tariff and duty on grains", "corn", "tariff"),
    ("drought stress in the growing region", "soybeans", "drought"),
    ("ethanol margins and corn grind", "corn", "ethanol"),
    ("palm oil export levy and duty", "palm_oil", "levy"),
]

ARMS = {
    "dense":               {},
    "hybrid":              {"mode": "hybrid"},
    "dense+rerank":        {"rerank": True},
    "hyb+rr+mmr(src-aware)": {"mode": "hybrid", "rerank": True, "mmr": 0.5},                        # default: source-aware
    "hyb+rr+mmr(agnostic)":  {"mode": "hybrid", "rerank": True, "mmr": 0.5, "same_source": False, "fairness": 0.0},
}


def load_probes(path: str) -> list[tuple[str, str, str]]:
    """(question, evidence-node, token) for every token-tagged query in a queries yaml — the retrieval-probe set."""
    import yaml
    qs = (yaml.safe_load(open(path, encoding="utf-8")) or {}).get("queries") or []
    return [(q["question"], ev.node_for(q["contract"]), q["token"].lower()) for q in qs if q.get("token")]


def _hit(rows: list[dict], token: str) -> tuple[int, int]:
    ranks = [i for i, r in enumerate(rows) if token in (r.get("text") or "").lower()]
    return (1 if ranks else 0, (ranks[0] + 1) if ranks else 0)      # (hit@k, 1-indexed first-hit rank or 0)


def run(k: int = 8, probes=None) -> dict:
    ev.CACHE_INDEX = True                                           # slices load once across probes/arms
    res = {arm: {"hits": 0, "ranks": [], "div": []} for arm in ARMS}
    for q, node, tok in (probes or PROBES):
        for arm, kw in ARMS.items():
            rows = ev.retrieve(q, node, k=k, **kw)
            hit, rank = _hit(rows, tok)
            res[arm]["hits"] += hit
            if rank:
                res[arm]["ranks"].append(rank)
            res[arm]["div"].append(len({r["source"] for r in rows}))
    return res


def main() -> int:
    import argparse

    from leviathan.common import config
    ap = argparse.ArgumentParser(description="Free retrieval-only A/B (hybrid/rerank/mmr) — no LLM, no spend.")
    ap.add_argument("--queries", default=None, help="queries yaml; use its token-tagged probes (else the built-in set)")
    ap.add_argument("--k", type=int, default=8)
    args = ap.parse_args()
    config.load_env()
    probes = load_probes(args.queries) if args.queries else PROBES
    n = len(probes)
    res = run(k=args.k, probes=probes)
    print(f"retrieval A/B over {n} probes  (token hit@{args.k} / avg first-rank / avg source-diversity):")
    print(f"{'arm':20s} {'hit':>7s} {'avg_rank':>9s} {'src_div':>8s}")
    for arm, r in res.items():
        avg_rank = (sum(r["ranks"]) / len(r["ranks"])) if r["ranks"] else 0.0
        avg_div = sum(r["div"]) / len(r["div"])
        print(f"{arm:20s} {r['hits']:>4d}/{n:<2d} {avg_rank:>9.1f} {avg_div:>8.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
