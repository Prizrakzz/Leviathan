"""Grounded answer orchestrator for graphdev (GRAPHRAG_PLAN v2 Phase 2 WS-3).

Routes a question to a contract (or two), assembles the causal subgraph (drivers / regimes / cross-links /
silver status) + retrieved dated evidence, and a CHEAP serving model (Sonnet by default — Opus built the
brain once, Sonnet serves it) emits a READER-FIRST structured answer via forced tool: a prose TL;DR, a prose
mechanism, a mermaid cascade/convergence diagram ONLY when the question warrants it, and consolidated
citations. `retrieve`/`call` are injectable so tests run without S3/Bedrock/Anthropic."""
from __future__ import annotations

import re

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import graph as gph
from leviathan.graphrag import harvest as hv

SONNET = "claude-sonnet-4-6"

_SYSTEM = (
    "You are a commodities analyst. Answer the question using ONLY the curated causal graph + dated evidence in "
    "the prompt — never invent drivers, signs, numbers, or sources. Emit via emit_answer in this reader-first "
    "structure a portfolio manager can skim:\n"
    "- tldr: 2-4 sentences of PLAIN prose giving the bottom line FIRST (what happened / what drives it, and the "
    "net price direction). Use inline markers [1],[2] for evidence-backed claims.\n"
    "- mechanism: a tight prose explanation of the causal chain / key drivers (state signs as 'raises price (+)' "
    "or 'lowers (-)'); NAME the convergence regime when the question is about a confluence. A brief list is fine; "
    "NO giant tables. Cite [n].\n"
    "- diagram_mermaid: ONLY when the question asks to TRACE a chain (cascade) or describe a CONFLUENCE "
    "(convergence). Emit a small `flowchart LR` (<=8 nodes, put the sign in each label, e.g. "
    "frost[\"frost +\"] --> stocks[\"stocks drain +\"]) ending at a price node. For 'what drives X' / policy / "
    "simple questions, leave it an EMPTY string.\n"
    "- sources: every evidence item you cited as [n], with its source and date.\n"
    "Ground strictly in what is shown; if evidence was provided, cite at least one dated source.")


def route(query: str, graph: gph.CausalGraph) -> list[str]:
    """Contracts whose id/aliases/commodity-token appear in the query (accent/case-insensitive), most-hits first."""
    scored = []
    for cid, c in graph.contracts.items():
        forms = [cid, cid.replace("_", " ")] + list(c.aliases) + cid.split("_")
        m = hv.build_matcher(forms)
        n = len(m.findall(query))
        if n:
            scored.append((n, cid))
    return [cid for _, cid in sorted(scored, reverse=True)]


def _context_block(graph: gph.CausalGraph, contract: str) -> str:
    c = graph.contracts[contract]
    lines = [f"CONTRACT: {contract} (target: {', '.join(c.target_metrics)})", "",
             "DRIVERS (id | sign | lag | live | mechanism):"]
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


def _ev_block(evidence: list[dict]) -> str:
    return "\n".join(f"- ({e['source']}, {e['date']}) {e['text']}" for e in evidence) or "(no evidence retrieved)"


def _prompt(query: str, contracts: list[str], blocks: list[str]) -> str:
    scope = contracts[0] if len(contracts) == 1 else f"{len(contracts)} related contracts {contracts}"
    tail = ("" if len(contracts) == 1 else
            "Multiple related contracts are shown — synthesize the cross-commodity linkage between them.")
    return f"QUESTION: {query}\n\n=== CAUSAL GRAPH + DATED EVIDENCE ({scope}) ===\n" + "\n\n".join(blocks) + f"\n\n{tail}"


def _answer_tool() -> dict:
    s = {"type": "string"}
    return {"name": "emit_answer", "description": "Emit the reader-first structured answer.",
            "input_schema": {"type": "object", "properties": {
                "tldr": s, "mechanism": s, "diagram_mermaid": s,
                "sources": {"type": "array", "items": {"type": "object", "properties": {
                    "ref": {"type": "integer"}, "source": s, "date": s, "note": s}}}},
                "required": ["tldr", "mechanism", "sources"]}}


def _valid_mermaid(s: str | None) -> bool:
    """Cheap well-formedness gate so we never render a broken diagram: a flowchart/graph header, an edge, and
    balanced brackets."""
    s = (s or "").strip()
    return bool(re.match(r"(flowchart|graph)\b", s)) and "-->" in s \
        and s.count("[") == s.count("]") and s.count("(") == s.count(")")


def render(d: dict) -> str:
    """Structured fields -> reader-first markdown (drops the diagram if absent or malformed)."""
    parts = [f"**TL;DR.** {(d.get('tldr') or '').strip()}", "", f"**Why.** {(d.get('mechanism') or '').strip()}"]
    if _valid_mermaid(d.get("diagram_mermaid")):
        parts += ["", "**Cascade / convergence**", "```mermaid", d["diagram_mermaid"].strip(), "```"]
    srcs = d.get("sources") or []
    if srcs:
        parts += ["", "**Sources**"] + [f"[{x.get('ref')}] {x.get('source')} · {x.get('date')} — {x.get('note', '')}"
                                         for x in srcs]
    return "\n".join(parts).strip()


def _call_opus(system: str, user: str, *, model: str, tool: dict) -> dict:
    import anthropic
    from leviathan.graphrag import batch_extract as bx
    client = anthropic.Anthropic(api_key=bx._api_key())
    out, _ = ex.call_opus(client, system, user, model=model, max_tokens=2800, tool=tool)
    return out


def answer(query: str, *, graph: gph.CausalGraph, model: str = SONNET, k: int = 5, asof: str | None = None,
           near: str | None = None, max_contracts: int = 2, retrieve=None, call=None) -> dict:
    """Answer grounded in the graph(s) + dated evidence, structured for a reader. Routes to up to `max_contracts`
    (a soy<->corn question synthesizes both). Returns {answer (markdown), structured, contract(s), evidence, trace}."""
    retrieve = retrieve or ev.retrieve
    call = call or _call_opus
    routed = route(query, graph)
    if not routed:
        return {"answer": "No tracked contract matched this question.", "structured": None, "contract": None,
                "contracts": [], "evidence": [], "model": model, "trace": {"routed": []}}
    contracts = routed[:max_contracts]
    blocks, evidence, ev_ids, regimes = [], [], [], []
    for c in contracts:
        hits = retrieve(query, ev.node_for(c), k=k, asof=asof, near=near)   # variants share a commodity-node slice
        blocks.append(_context_block(graph, c) + f"\n\n--- DATED EVIDENCE for {c} ---\n" + _ev_block(hits))
        evidence += [{**h, "contract": c} for h in hits]
        ev_ids += [h["source_key"] for h in hits]
        regimes += [s.name for s in graph.contracts[c].convergence]
    structured = call(_SYSTEM, _prompt(query, contracts, blocks), model=model, tool=_answer_tool())
    return {"answer": render(structured), "structured": structured, "contract": contracts[0], "contracts": contracts,
            "evidence": evidence, "model": model,
            "trace": {"routed": routed, "contracts": contracts,
                      "n_drivers": sum(len(graph.contracts[c].drivers) for c in contracts), "regimes": regimes,
                      "evidence_ids": ev_ids, "has_diagram": _valid_mermaid(structured.get("diagram_mermaid")),
                      "model": model}}
