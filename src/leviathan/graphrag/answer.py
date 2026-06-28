"""Grounded answer orchestrator for graphdev (GRAPHRAG_PLAN v2 Phase 2 WS-3).

Routes a question to a contract, assembles the causal subgraph (drivers / regimes / cross-links / silver
status) + retrieved dated evidence, and has a CHEAP serving model (Sonnet by default — the authoring/serving
split: Opus built the brain once, Sonnet serves it) compose a grounded answer. Returns the answer + a trace
for the eval. `retrieve`/`chat` are injectable so tests run without S3/Bedrock/Anthropic."""
from __future__ import annotations

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import graph as gph
from leviathan.graphrag import harvest as hv

SONNET = "claude-sonnet-4-6"

_SYSTEM = (
    "You are a commodities analyst answering ONLY from a curated causal graph and dated evidence provided in the "
    "prompt. Ground every claim in the given drivers / convergence regimes / inter-commodity edges / evidence. "
    "State a driver's effect as 'raises price' (+) or 'lowers price' (-). Name a convergence regime when the "
    "question is about a confluence. Cite evidence inline as (source, YYYY-MM). If the graph does not support a "
    "claim, say so plainly rather than inventing. Be concise and specific.")


def route(query: str, graph: gph.CausalGraph) -> list[str]:
    """Contracts whose id/aliases appear in the query (accent/case-insensitive), most-hits first."""
    scored = []
    for cid, c in graph.contracts.items():
        # match the id, its spaced form, aliases, AND the bare commodity tokens ('coffee' -> arabica_coffee)
        forms = [cid, cid.replace("_", " ")] + list(c.aliases) + cid.split("_")
        m = hv.build_matcher(forms)
        n = len(m.findall(query))
        if n:
            scored.append((n, cid))
    return [cid for _, cid in sorted(scored, reverse=True)]


def _context_block(graph: gph.CausalGraph, contract: str) -> str:
    c = graph.contracts[contract]
    lines = [f"CONTRACT: {contract} (target: {', '.join(c.target_metrics)})", "", "DRIVERS (id | sign | lag | live | mechanism):"]
    for d in c.drivers:
        live = "live" if graph.silver_status(contract, d.id)["live"] else d.silver_status
        lines.append(f"- {d.id} | {d.sign} | {d.lag or 'n/a'} | {live} | {d.mechanism}")
    lines.append("\nCONVERGENCE REGIMES (name | direction | needs N of drivers | note):")
    for s in c.convergence:
        lines.append(f"- {s.name} | {s.direction} | {s.requires_any_n_of} of {s.drivers} | {s.note}")
        for it in s.interactions:
            lines.append(f"    interaction: {it.when} -> {it.effect}: {it.note}")
    lines.append("\nINTER-COMMODITY EDGES (commodity | relation | sign | mechanism):")
    for e in c.inter_commodity:
        lines.append(f"- {e.driver_commodity} | {e.relation} | {e.sign} | {e.mechanism}")
    return "\n".join(lines)


def _prompt(query: str, contract: str, ctx: str, evidence: list[dict]) -> str:
    ev_block = "\n".join(f"- ({e['source']}, {e['date']}) {e['text']}" for e in evidence) or "(no evidence retrieved)"
    return (f"QUESTION: {query}\n\n=== CAUSAL GRAPH for {contract} ===\n{ctx}\n\n"
            f"=== DATED EVIDENCE (most relevant) ===\n{ev_block}\n\n"
            "Answer the question using only the graph and evidence above.")


def _chat(system: str, user: str, *, model: str, max_tokens: int = 1500) -> str:
    import anthropic
    from leviathan.graphrag import batch_extract as bx
    client = anthropic.Anthropic(api_key=bx._api_key())
    resp = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                  messages=[{"role": "user", "content": user}],
                                  thinking={"type": "adaptive"})
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


def answer(query: str, *, graph: gph.CausalGraph, model: str = SONNET, k: int = 5, asof: str | None = None,
           retrieve=None, chat=None) -> dict:
    """Answer a question grounded in the graph + dated evidence. Returns {answer, contract, evidence, model, trace}."""
    retrieve = retrieve or ev.retrieve
    chat = chat or _chat
    routed = route(query, graph)
    if not routed:
        return {"answer": "No tracked contract matched this question.", "contract": None,
                "evidence": [], "model": model, "trace": {"routed": []}}
    contract = routed[0]                              # primary contract; multi-contract synthesis is a later step
    ev_hits = retrieve(query, contract, k=k, asof=asof)
    text = chat(_SYSTEM, _prompt(query, contract, _context_block(graph, contract), ev_hits), model=model)
    return {"answer": text, "contract": contract, "evidence": ev_hits, "model": model,
            "trace": {"routed": routed, "contract": contract, "n_drivers": len(graph.contracts[contract].drivers),
                      "regimes": [s.name for s in graph.contracts[contract].convergence],
                      "evidence_ids": [e["source_key"] for e in ev_hits], "model": model}}
