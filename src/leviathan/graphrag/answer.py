"""Grounded answer orchestrator for graphdev (GRAPHRAG_PLAN v2 Phase 2 WS-3).

Routes a question to a contract (or two), assembles the causal subgraph (drivers / regimes / cross-links /
silver status) + retrieved dated evidence, and a CHEAP serving model (Sonnet by default — Opus built the
brain once, Sonnet serves it) emits a READER-FIRST structured answer via forced tool: a prose TL;DR, a prose
mechanism, a mermaid cascade/convergence diagram ONLY when the question warrants it, and consolidated
citations. `retrieve`/`call` are injectable so tests run without S3/Bedrock/Anthropic."""
from __future__ import annotations

import functools
import re

from leviathan.graphrag import citations as cit
from leviathan.graphrag import register as reg
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import graph as gph
from leviathan.graphrag import harvest as hv

# Production retrieval stack — the arm that won the free k=3 A/B (hybrid doubled exact-token recall 2/6->4/6;
# rerank sharpened rank; MMR kept the best source-diversity, guarding against narrowing). Serving uses this by
# default; override `retrieve=` to A/B a different arm. NOTE: rerank runs a bge cross-encoder — on CPU it adds
# real per-query latency, so in production point it at a GPU/hosted reranker (like the bge-m3 embed endpoint).
_RETRIEVAL = {"mode": "hybrid", "rerank": True, "mmr": 0.5, "fairness": 0.3}   # MMR is source-aware (same-source dedup, cross-source keep, balance)

SONNET = "claude-sonnet-4-6"

# Source-trust tiers (lower = more trusted). Retrieval stays source-NEUTRAL; this only orders/labels the OUTPUT.
# Tunable. T1 official balance-sheet/statistical, T2 USDA attaché field reports, T3 producer/industry bodies,
# T4 macro/price commentary.
_SOURCE_TIERS = {1: ("usda_wasde", "usda_fas", "usda_wap"), 2: ("usda_gain",),
                 3: ("fnc", "mpoc", "mpob", "conab"), 4: ("wb_cmo",)}
_TIER_LABEL = {1: "official/balance-sheet", 2: "USDA attache", 3: "producer/industry", 4: "macro outlook"}


def source_tier(source: str) -> int:
    """Map a source name to a trust tier (1=most trusted ... 4=macro commentary); unknown -> 3."""
    s = (source or "").lower()
    for tier in sorted(_SOURCE_TIERS):
        if any(p in s for p in _SOURCE_TIERS[tier]):
            return tier
    return 3

_SYSTEM = (
    "You are a commodities analyst writing for a QUANT RESEARCHER studying how fundamental supply/demand shocks "
    "propagate through balance sheets and WHERE the price response turns CONVEX (buffer exhaustion, tipping "
    "thresholds, regime switches). This is RESEARCH, not a trading desk: do NOT give position sizing, price "
    "targets, or 'how much to trade'. Use ONLY the curated causal graph + dated evidence in the prompt — never "
    "invent drivers, signs, numbers, or sources.\n"
    "GROUNDING DISCIPLINE (critical — you will be judged on this):\n"
    "- APPROVED EDGES ONLY: reason strictly over the driver / inter-commodity / convergence edges SHOWN in the graph. "
    "Do NOT introduce a driver, causal link, or regime that isn't in the prompt; if the question implies a link the "
    "graph lacks, say it is outside the mapped graph rather than inventing it.\n"
    "- CONFIDENCE: each driver is tagged conf=high|medium|low. Present a low-confidence driver as a HYPOTHESIS ('one "
    "lower-confidence channel is ...'), never as an established mechanism; lean on high-confidence edges first.\n"
    "- COMMIT TO A BASE-CASE LEAN. A PM needs a direction: state a net bull/bear/neutral base case and which leg you "
    "expect to dominate and why (a caveat is fine). Do NOT hide behind 'indeterminate/ambiguous' — only decline a lean "
    "when the graph itself gives opposing SAME-confidence drivers with no tiebreaker, and then say exactly that.\n"
    "- REASON ONLY FROM THE GRAPH'S MECHANISM. Explain WHY using the driver's stated sign/lag/edge — do NOT invent a "
    "physical, volumetric, or agronomic rationale the graph doesn't state (e.g. 'meal volume exceeds oil so it falls "
    "more'); if the graph's mechanism doesn't cover it, say so rather than manufacture a justification.\n"
    "- ATTRIBUTION vs CONFIDENCE: a driver's conf tag is NOT a measured historical attribution. 'The graph rates BRL "
    "higher-confidence than El Nino' is legitimate; 'BRL did the heavy lifting historically' is NOT, unless a cited "
    "dated item actually decomposes the two. Say which it is — model-ranked vs evidence-measured.\n"
    "- Distinguish MECHANISM from OBSERVATION. The graph's drivers/signs/regimes are an authoritative MODEL of what "
    "moves price — state them as mechanism ('drought is a bullish driver', 'the squeeze regime needs N of ...'). Do "
    "NOT assert a driver as an OBSERVED current fact ('stocks have collapsed', 'disease is killing trees', 'specs are "
    "long') unless a CITED dated evidence item says so. If it is model-not-observation, phrase it that way.\n"
    "- Be honest about evidence COVERAGE. If the evidence is sparse, single-dated, or doesn't cover the period the "
    "question implies, SAY SO ('the only dated evidence here is from <date>; I can't confirm the current state') "
    "rather than padding with unconfirmed claims.\n"
    "- A real-time 'what is the state TODAY' read needs the live-feature layer, which is NOT in this prompt. If asked "
    "for a current read, give the framework + what to watch and say the live read needs that layer — never fabricate "
    "a current state.\n"
    "- NEVER invent a number, threshold, percentage, or price level. Every figure you state MUST come from a cited "
    "evidence item; if you have no cited number, say 'magnitude not in the evidence' rather than fabricate one (e.g. "
    "do NOT write 'a >15% export lag is bullish' unless a source gives that figure).\n"
    "CONVEXITY & RESEARCH SUBSTANCE: where the question warrants, LOCATE where the response is convex vs roughly "
    "linear and the buffer/threshold that makes it TIP (e.g. a tight stocks-to-use buffer => a supply shock is "
    "convex and right-tailed; a bumper crop is capped by the same low stocks => the skew is asymmetric); name the "
    "WATCH-LIST drivers that confirm it; cite the magnitudes/dates the evidence gives. Frame in the researcher's "
    "lexicon USED CORRECTLY AND ONLY WHEN THE MECHANISM EARNS IT — convex/linear, tail risk (right/left tail), "
    "skew/asymmetry, regime, base rate; a misused 'tail risk' is worse than plain language.\n"
    "OUTPUT REGISTER: reason internally with the graph's signs/driver-ids, but WRITE for the researcher — say "
    "bullish/bearish (or supportive/pressuring), NOT '+/-'; 'the driver is active, confirmed by <dated evidence>', "
    "NOT 'the node fired'; 'the effects compound/offset', NOT 'the leg cancels'; spell out contract names (the "
    "Dalian soybean contract, not soybeans_no_2_dce); NEVER emit internal tokens (conf=, sign=, node, edge, raw "
    "slugs) in the prose.\n"
    "TEMPORAL DISCIPLINE (cascades are about timing): each evidence item shows when it was 'reported <date>' and, "
    "when known, when the 'event <date>' actually occurred — PREFER the event date for sequencing. For a cascade/"
    "convergence question, lay the cited events out as a DATED sequence (earliest trigger -> downstream effect) "
    "using the ACTUAL dates, and state realized lags as concrete deltas ('B40 effective 2023-02 -> palm stock draw "
    "reported 2023-04, ~2 months') rather than vague 'a couple quarters'; compare the realized lag to the graph's "
    "lag prior and flag if it ran fast/slow. Use exact dates, never invent one; if only a report date exists, say so.\n"
    "CROSS-CUTTING DRIVERS: a 'CROSS-CUTTING DRIVER EVIDENCE' block may carry the cascade TRIGGERS (a biodiesel "
    "mandate, a freight spike, an FX move, an El Nino onset) that don't name the commodity but move it via the "
    "graph's driver edges — use them to ground the FIRST link of a cascade and tie each to the driver's silver "
    "measure when the graph names one; keep them as mechanism unless a dated item confirms the magnitude.\n"
    "SOURCE TRUST: each evidence item is tagged [T1]-[T4] by source trust (T1 official balance-sheet WASDE/FAS > "
    "T2 USDA attache GAIN > T3 producer/industry body fnc/mpoc/conab > T4 macro/price outlook wb_cmo). Draw on ALL "
    "tiers for breadth, but in `sources` ORDER citations most-trusted (lowest T) FIRST and note each source's "
    "nature. When sources of DIFFERENT tiers disagree on a fact, FLAG the disagreement — it's signal a PM wants.\n"
    "Emit via emit_answer, reader-first for a PM to skim:\n"
    "- tldr: 2-4 sentences, bottom line FIRST (net price direction + the key driver). Inline [n] for evidence-backed claims.\n"
    "- mechanism: the causal chain / key drivers (sign each in words — 'raises price (bullish)' or 'lowers (bearish)'); NAME the convergence "
    "regime for confluence questions; make clear which claims are MODEL vs CITED observation. Brief list, NO giant tables. Cite [n].\n"
    "- diagram_mermaid: ONLY for a cascade (TRACE a chain) or convergence (CONFLUENCE) question — a small `flowchart LR` "
    "(<=8 nodes, sign in each PLAIN-TEXT label, no emoji, e.g. frost[\"frost +\"] --> stocks[\"stocks drain +\"]) ending "
    "at a price node. For 'what drives X' / policy / simple questions, leave it an EMPTY string.\n"
    "- sources: every [n] you cited, with its source and date.\n"
    "Ground strictly in what is shown; if evidence was provided, cite at least one dated source.")


def route(query: str, graph: gph.CausalGraph) -> list[str]:
    """TIER 1 (lexical): contracts whose id/aliases/commodity-token appear in the query (accent/case-insensitive),
    most-hits first. Fast + precise, but blind to coreference/paraphrase ('a frost in Brazil', 'that contract')."""
    scored = []
    for cid, c in graph.contracts.items():
        forms = [cid, cid.replace("_", " ")] + list(c.aliases) + cid.split("_")
        m = hv.build_matcher(forms)
        n = len(m.findall(query))
        if n:
            scored.append((n, cid))
    return [cid for _, cid in sorted(scored, reverse=True)]


_PROFILE_CACHE: dict = {}


def _contract_profiles(graph: gph.CausalGraph) -> dict[str, str]:
    """A short text profile per contract for semantic routing: id + aliases + its top driver ids."""
    return {cid: f"{cid.replace('_', ' ')} {' '.join(c.aliases)} "
                 f"{' '.join(d.id.replace('_', ' ') for d in c.drivers[:12])}"
            for cid, c in graph.contracts.items()}


def route_semantic(query: str, graph: gph.CausalGraph, *, embed=None, k: int = 2, min_cos: float = 0.35) -> list[str]:
    """TIER 2 (semantic): embed the query (bge-m3) + cosine vs per-contract profiles — catches paraphrase that
    names no commodity ('a frost in Brazil'). Profile vectors are cached per contract set."""
    embed = embed or ev.embed
    profs = _contract_profiles(graph)
    key = tuple(sorted(profs))
    if key not in _PROFILE_CACHE:
        _PROFILE_CACHE[key] = (list(profs), embed(list(profs.values())))
    ids, vecs = _PROFILE_CACHE[key]
    qv = embed([query])[0]
    ranked = sorted(((ev._cosine(qv, v), cid) for cid, v in zip(ids, vecs)), reverse=True)
    return [cid for s, cid in ranked[:k] if s >= min_cos]


def _route_llm_tool() -> dict:
    return {"name": "pick_contracts", "description": "Pick the tracked contract id(s) the question is about.",
            "input_schema": {"type": "object", "properties": {
                "contracts": {"type": "array", "items": {"type": "string"}}}, "required": ["contracts"]}}


def route_llm(query: str, graph: gph.CausalGraph, *, k: int = 2, call=None) -> list[str]:
    """TIER 3 (LLM): a cheap Haiku call resolves coreference/comparison/multi-commodity ('which ag is most
    exposed to the dollar') by mapping the question to ids from the tracked list."""
    call = call or _call_opus
    ids = list(graph.contracts)
    sys = ("Map a commodities question to the tracked futures-contract id(s) it concerns. Resolve coreference and "
           "comparisons. Return ONLY ids from the provided list, the 1-2 most relevant, via pick_contracts.")
    user = f"TRACKED CONTRACTS: {ids}\n\nQUESTION: {query}"
    out = call(sys, user, model=ex.HAIKU, tool=_route_llm_tool())
    return [c for c in (out.get("contracts") or []) if c in graph.contracts][:k]


def route_smart(query: str, graph: gph.CausalGraph, *, embed=None, route_call=None, k: int = 2) -> list[str]:
    """Tiered router: lexical -> semantic -> LLM. Lexical wins when it fires (fast/precise); otherwise fall back
    to semantic (paraphrase), then an LLM call (coreference/comparison)."""
    return (route(query, graph)
            or route_semantic(query, graph, embed=embed, k=k)
            or route_llm(query, graph, k=k, call=route_call))


def _context_block(graph: gph.CausalGraph, contract: str) -> str:
    c = graph.contracts[contract]
    tgt0 = c.target_metrics[0] if c.target_metrics else "price"
    lines = [f"CONTRACT: {contract} (target: {', '.join(c.target_metrics)})", "",
             "DRIVERS (id | sign on target | lag | live | conf | mechanism):"]
    for d in c.drivers:
        live = "live" if graph.silver_status(contract, d.id)["live"] else d.silver_status
        tgt = d.target_metric or tgt0                          # a yield/production driver overrides the price default
        lines.append(f"- {d.id} | {d.sign} on {tgt} | {d.lag or 'n/a'} | {live} | conf={d.confidence} | {d.mechanism}")
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
    def _one(e: dict) -> str:
        head = f"[T{source_tier(e['source'])}] ({e['source']}, reported {e['date']}"
        ev_dt = e.get("event_date")
        if ev_dt and ev_dt != e["date"]:                       # WS-MS6: show WHEN the event happened vs was reported
            head += f"; event {ev_dt}"
        head += ")"
        drv = f" {{driver: {e['driver']}}}" if e.get("driver") else ""   # cross-cutting cascade trigger
        return f"- {head}{drv} {e['text']}"
    return "\n".join(_one(e) for e in evidence) or "(no evidence retrieved)"


_MAX_DRIVER_SLICES = 5
_DRIVER_K = 3


def _active_drivers(query: str, contracts: list[str], graph: gph.CausalGraph) -> list[str]:
    """Driver slices relevant to the query + the routed subgraph's driver mechanisms — so 'what drives cocoa'
    (no driver named) still pulls the cocoa DAG's drivers (harmattan/drought) via their mechanism text."""
    text = query + " " + " ".join(f"{d.id} {d.mechanism}" for c in contracts for d in graph.contracts[c].drivers)
    out: list[str] = []
    for dn in ev.driver_slices_for(text):
        if dn not in out:
            out.append(dn)
    return out[:_MAX_DRIVER_SLICES]


def _driver_evidence(query: str, drivers: list[str], *, k: int, asof, near, retrieve_fn) -> list[dict]:
    """Top-k dated evidence from each active driver slice (evidence/drivers/<driver>.jsonl), tagged with its driver."""
    hits: list[dict] = []
    for dn in drivers:
        for h in retrieve_fn(query, f"drivers/{dn}", k=k, asof=asof, near=near):
            hits.append({**h, "driver": dn})
    return hits


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
    out, _ = ex.call_opus(client, system, user, model=model, max_tokens=4096, tool=tool)   # headroom for cascade+mermaid+sources
    return out


def answer(query: str, *, graph: gph.CausalGraph, model: str = SONNET, k: int = 5, asof: str | None = None,
           near: str | None = None, max_contracts: int = 2, retrieve=None, call=None, route_fn=None,
           driver_retrieve=None, extra_context: str | None = None, extra_number_calls: list | None = None) -> dict:
    """Answer grounded in the graph(s) + dated evidence, structured for a reader. Routes (tiered lexical->semantic->
    LLM) to up to `max_contracts` (a soy<->corn question synthesizes both). Also pulls CROSS-CUTTING DRIVER evidence
    (WS-MS6 — B40/freight/FX/El Nino cascade triggers). Returns {answer (markdown), structured, contract(s),
    evidence, trace}."""
    retrieve = retrieve or functools.partial(ev.retrieve, **_RETRIEVAL)         # serving = the A/B-won hybrid+rerank+mmr stack
    driver_retrieve = driver_retrieve or functools.partial(ev.retrieve, **_RETRIEVAL)   # real slices; tests inject -> no-op
    call = call or _call_opus
    route_fn = route_fn or route_smart
    routed = route_fn(query, graph)
    if not routed:
        return {"answer": "No tracked contract matched this question.", "structured": None, "contract": None,
                "contracts": [], "evidence": [], "model": model, "trace": {"routed": []}}
    # node-diverse selection: siblings share an evidence shard, so a 2nd slot should add a DIFFERENT commodity
    # (a soymeal-vs-soyoil spread -> one meal + one oil, not two oils; a single-commodity Q -> one shard, not two).
    contracts, seen = [], set()
    for c in routed:
        nd = ev.node_for(c)
        if nd not in seen:
            seen.add(nd)
            contracts.append(c)
        if len(contracts) >= max_contracts:
            break
    blocks, evidence, ev_ids, regimes = [], [], [], []
    for c in contracts:
        hits = retrieve(query, ev.node_for(c), k=k, asof=asof, near=near)   # variants share a commodity-node slice
        blocks.append(_context_block(graph, c) + f"\n\n--- DATED EVIDENCE for {c} ---\n" + _ev_block(hits))
        evidence += [{**h, "contract": c} for h in hits]
        ev_ids += [h["source_key"] for h in hits]
        regimes += [s.name for s in graph.contracts[c].convergence]
    # WS-MS6: cross-cutting driver/cascade evidence (the B40/freight/FX/El Nino triggers the commodity slices drop)
    drivers = _active_drivers(query, contracts, graph) if ev.driver_specs() else []
    driver_hits = _driver_evidence(query, drivers, k=_DRIVER_K, asof=asof, near=near, retrieve_fn=driver_retrieve)
    if driver_hits:
        blocks.append("--- CROSS-CUTTING DRIVER EVIDENCE (cascade/convergence triggers; tie to silver) ---\n"
                      + _ev_block(driver_hits))
        evidence += [{**h, "contract": "(driver)"} for h in driver_hits]
    if extra_context:                                              # Phase 5 hybrid: inject silver numbers as context
        blocks.append(extra_context)
    structured = call(_SYSTEM, _prompt(query, contracts, blocks), model=model, tool=_answer_tool())
    # unified provenance footer (Phase 4): document-level, deduped by source_key. Numbers citations join here in
    # the Phase-5 hybrid path; the per-prop page/char slots ride along for the page-citation recovery.
    seen_docs, uniq = set(), []
    for h in evidence:
        sk = h.get("source_key")
        if sk and sk not in seen_docs:
            seen_docs.add(sk)
            uniq.append(h)
    ev_cits = cit.unify(uniq, extra_number_calls)                 # numbers citations (hybrid) join the same footer
    footer = ("\n\n## Sources\n" + cit.render(ev_cits)) if ev_cits else ""
    body = reg.sanitize(render(structured) + footer)              # strip any internal tokens the model leaked into prose
    return {"answer": body, "structured": structured, "contract": contracts[0],
            "contracts": contracts, "citations": [c.model_dump() for c in ev_cits],
            "evidence": evidence, "model": model,
            "trace": {"routed": routed, "contracts": contracts,
                      "n_drivers": sum(len(graph.contracts[c].drivers) for c in contracts), "regimes": regimes,
                      "drivers": drivers, "n_driver_evidence": len(driver_hits),
                      "evidence_ids": ev_ids, "has_diagram": _valid_mermaid(structured.get("diagram_mermaid")),
                      "model": model}}
