"""V2-RETRIEVAL SLICE 1 -- THE BRIDGE QUERY: the build's pin suite (no pg, no AWS, no LLM, no network).

THE DEFECT, read from `planner._fill` on 2026-09-11: the walk admits a far CONTRACT node by
cos(question, the ADMITTING EDGE'S MECHANISM) -- THE GRAPH DECIDES WHICH NODES -- but INSIDE that node the
propositions are ordered by cosine + BM25 + rerank against the USER'S QUESTION. A corn question therefore
ranks a soybean node's sentences by their likeness to 'corn'. Measured on the real bge embedder over the
real stored slices: for `contract:soybeans_cbot` reached from `corn_cbot` via `competes_with`, the shipped
question-ranked top-8 overlaps the mechanism-ranked top-8 in 1 of 8.

THE V1 SLICE (population WIDENED by the orchestrator ruling of 2026-09-15 07:10Z -- the bridge exists for
the MULTI-HOP case): EVERY NON-SEED RETRIEVING NODE reads with the text the walk SCORED TO ADMIT IT,
VERBATIM, on all three legs at once --
  * a hop CONTRACT with `n.via_edge["mechanism"]`, the admitting edge's sentence;
  * a DRIVER at depth 1 or 2 with `graph.driver(n.contract, n.id).mechanism`, its OWN mechanism, because a
    driver is enqueued with `via=None` and carries no edge -- reading `via_edge["mechanism"]` alone would
    have selected ZERO drivers, and the depth-2 drivers OF a hop contract (MEASURED 26 of the 149-node
    bridgeable population on the recon max walk, against 12 hop contracts and 111 depth-1 drivers) ARE the
    multi-hop chain in this graph, since the D-MW-13 hop fence keeps contract depth at 0/1.
The SEED keeps the question. THE HONEST CLAIM: the question chooses the path, the path writes the query.

WHAT THIS FILE PINS, one test per row of the threat table (scratchpad/bridge_query/THREAT_MODEL.md):

  DARKNESS      the kwarg defaults False; `ground()` reads NO environment; the env var alone changes
                nothing; the OFF arm's retrieve call is the shipped call and stamps NO trace key
  POPULATION    hop contracts AND drivers at depth 1 and 2 bridge; the seed does not, and a PRIOR-ONLY
                node (no backing id / no slice) is outside it entirely -- neither in the denominator nor
                in the fallback tally, and never warmed
  THE TEXT      the admitting mechanism VERBATIM, to ALL THREE LEGS (vector, BM25/tsquery, rerank query),
                because `ev._Q_CACHE` keys on `(backend, text)` and any normalisation turns a free memo
                read into a paid embed per node
  FALLBACKS     no via_edge / unreadable driver / empty mechanism / a kind with no admitting text / the
                BEDROCK rerank lane -> the question, and COUNTED, every one of them
  THE RECEIPT   EVERY driver is bridged, regime-required or not, on as-of turns too (R-13, 2026-09-15 --
                a `regime_receipt` fence stood here and was removed). The firing leg reuses a driver's
                KEPT ROWS as its receipt, so a bridged driver's receipt is its BRIDGE-RANKED rows: the
                regime outcomes MAY move and are pinned to MOVE WITH THE ROWS, never pinned equal
  EC-2          a bridge node is counted OUT of the `wants` census and takes its OWN borrow with the
                BRIDGE qv and the BRIDGE tsquery -- sharing the question-fetched batch would demote the
                bridge to a re-ORDER inside the question's top-fetch_k, which is the defect, not the fix
  THE WARM      one embed per DISTINCT bridge, zero when the map is empty
  THE DISPATCH  `GRAPHRAG_RERANK_GROUP_WORKERS` (R-14): default 4 = the HEAD constant, env > params,
                clamped to [1, 32], and widening it changes no output row
  INVARIANTS    the walk, `eligible`, k, the slices, `walk_shape` and the RETRIEVAL PLAN (node count and
                per-node (slice, k, asof, near), at the EC-2 wants census and at `take`) are EQUAL across
                arms; `n_evidence <= evidence_cap`; the tracekeys tail is untouched

EVERY TEST SETS `GRAPHRAG_BRIDGE_QUERY` (or the kwarg) EXPLICITLY AND NEVER RELIES ON AMBIENT ENV --
`tests/unit/test_dam_modes.py::test_walk_and_ground_kwargs_are_untouched_on_standard_and_dark` asserts an
EXACT kwarg set on the `pl.ground` call and would FAIL if this deck leaked the flag into the process env.
"""
from __future__ import annotations

import collections
import functools
import inspect
import re
import threading
import time

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as g
from leviathan.graphrag import pgstore as pg
from leviathan.graphrag import planner as pl
from leviathan.graphrag import rankers as rk

# ══ THE FIXTURE GRAPH ════════════════════════════════════════════════════════════════════════════════
# alpha (the seed) declares two TRACKED inter-commodity edges. beta declares one onward, so a depth-2 hop
# contract exists too (the hop fence only arms under `per_seed_budget`, which this deck never passes).
QUESTION = "frost substitute"
MECH_AB = "frost substitute acreage ratio"          # alpha -> beta
MECH_AC = "frost substitute demand"                 # alpha -> gamma
MECH_BD = "frost acreage damage"                    # beta  -> delta (depth 2)
# THE DRIVER MECHANISMS -- the text `planner._relevance` scores to ADMIT each driver, and therefore the
# text that writes its query. `shift` hangs off BETA, so at depth 2 it is a DRIVER OF A HOP CONTRACT:
# the multi-hop chain, which in this graph exists in the driver layer and not the contract layer.
MECH_FROST = "frost damage"                         # alpha's own driver (depth 1)
MECH_ACRE = "substitute acreage damage"             # alpha's own driver (depth 1)
MECH_RATIO = "frost substitute ratio"               # alpha's own driver (depth 1)
MECH_SHIFT = "frost substitute acreage shift"       # BETA's driver -> depth 2 under `onward`

_KW = ["frost", "substitute", "acreage", "ratio", "drought", "rain", "climate", "nino", "damage", "demand"]


def _embed(texts, **k):
    """A deterministic keyword-indicator embedder: distinct texts get distinct vectors, so a bridge qv and
    a question qv are DIFFERENT objects a recording double can tell apart."""
    return [[1.0 if kw in t.lower() else 0.0 for kw in _KW] for t in texts]


def _d(id_, mech, **o):
    return cs.Driver(id=id_, type=o.pop("type", "hazard"), sign=o.pop("sign", "+"), mechanism=mech, **o)


def _edge(target, mech, relation="competes_with"):
    return cs.InterCommodityEdge(driver_commodity=target, relation=relation, sign="+", mechanism=mech,
                                 lag="1-3 quarters")


def _graph(*, mech_ab: str = MECH_AB, mech_ac: str = MECH_AC, onward: bool = False,
           converge=(), mech_frost: str = MECH_FROST) -> g.CausalGraph:
    alpha = cs.CausalContract(
        contract="alpha", aliases=["alpha"],
        # three drivers clear tau, one ("rain only") does not -- so the walk's own tau still bites and the
        # driver population is more than one node
        drivers=[_d("frost", mech_frost), _d("acreage", MECH_ACRE),
                 _d("ratio", MECH_RATIO), _d("rain", "rain only", sign="-")],
        inter_commodity=[_edge("beta", mech_ab), _edge("gamma", mech_ac)],
        # THE FIRING RECEIPT'S INPUT: a convergence signal names the drivers whose KEPT ROWS the regime leg
        # reuses as its receipt -- which, with the flag on, are BRIDGE-RANKED rows (R-13). Empty by default,
        # so most of this deck runs with no firing leg at all.
        convergence=[cs.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=1,
                                          drivers=list(converge))] if converge else [])
    beta = cs.CausalContract(
        contract="beta", aliases=["beta"],
        drivers=[_d("demand", "demand rises"), _d("shift", MECH_SHIFT)],
        inter_commodity=([_edge("delta", MECH_BD)] if onward else []))
    gamma = cs.CausalContract(contract="gamma", aliases=["gamma"], drivers=[_d("drought", "drought damage")])
    out = {"alpha": alpha, "beta": beta, "gamma": gamma}
    if onward:
        out["delta"] = cs.CausalContract(contract="delta", aliases=["delta"],
                                         drivers=[_d("nino", "el nino climate")])
    return g.CausalGraph(out, silver=set())


_DRIVERS = {"frost", "acreage", "ratio", "rain", "demand", "drought", "nino", "shift"}
# The three drivers of ALPHA that clear tau on the default fixture, with the text that admits each.
_D1_BRIDGES = {"drivers/frost": MECH_FROST, "drivers/acreage": MECH_ACRE, "drivers/ratio": MECH_RATIO}


def _sg(gr, *, depth: int = 1, tau: float = 0.35, seeds=("alpha",), **kw):
    return pl.grounded_subgraph(QUESTION, gr, embed=_embed, route_fn=lambda q, graph: list(seeds),
                                tau=tau, depth=depth, **kw)


class _Recorder:
    """A hermetic fake retriever that does NOT accept `candidates=` -- the injected-double contract. It
    records the QUERY TEXT it was handed, which is the whole of what this lane changes."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, query, slice_, *, k, asof=None, near=None):
        self.calls.append({"query": query, "slice": slice_, "k": k, "asof": asof, "near": near})
        return [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{slice_}",
                 "text": f"{slice_} row"}]

    def by_slice(self) -> dict:
        return {c["slice"]: c["query"] for c in self.calls}


def _ground(gr, sg, rec, **kw):
    pl.ground(sg, QUESTION, gr, retrieve=rec, silver_lookup=None, driver_slices=set(_DRIVERS),
              probe_cap=0, **kw)
    return sg


def _run(*, bridge: bool, gr=None, sg=None, depth: int = 1, tau: float = 0.35, seeds=("alpha",), **kw):
    gr = gr or _graph()
    sg = sg if sg is not None else _sg(gr, depth=depth, tau=tau, seeds=seeds)
    rec = _Recorder()
    _ground(gr, sg, rec, bridge_query=bridge, **kw)
    return sg, rec


def _spy_bridges(monkeypatch) -> list:
    """Capture the `bridges=` tuple handed to every `_parallel_fill` -- i.e. the WARM population, which
    must be the DISTINCT applied bridges and nothing else."""
    seen: list = []
    real = pl._parallel_fill
    monkeypatch.setattr(pl, "_parallel_fill",
                        lambda *a, **k: (seen.append(k.get("bridges")), real(*a, **k))[1])
    return seen


@pytest.fixture(autouse=True)
def _never_ambient(monkeypatch):
    """THE TRIPWIRE THIS DECK MUST NOT TRIP. `test_dam_modes.py:624` asserts an EXACT kwarg set on the
    serving `pl.ground(...)` call; an ambient `GRAPHRAG_BRIDGE_QUERY` in the test process would arm the
    answer seam and fail it. Every test here passes the kwarg, or sets the env for ONE assertion."""
    monkeypatch.delenv("GRAPHRAG_BRIDGE_QUERY", raising=False)
    monkeypatch.delenv("GRAPHRAG_EVIDENCE_BATCH", raising=False)
    monkeypatch.delenv("EVIDENCE_BACKEND", raising=False)
    monkeypatch.delenv("GRAPHRAG_RERANK_BACKEND", raising=False)
    # R-14's knob, for the same reason: an ambient width would make the "default IS the HEAD constant"
    # pin read whatever the shell happened to carry, which is the one thing that pin exists to deny.
    monkeypatch.delenv("GRAPHRAG_RERANK_GROUP_WORKERS", raising=False)


# ══ DARKNESS: I-4, P-1, P-9, and the flag-off shipped call ═══════════════════════════════════════════
def test_the_kwarg_ships_false_and_ground_reads_no_environment_for_it(monkeypatch):
    """I-4 + P-1. The tree is DARK BY CONSTRUCTION: the kwarg defaults False, and `ground()` contains no
    read of the env var at all -- `answer._answer_l2` reads it ONCE per turn and threads the bool, so a
    taskdef flip between the walk and the fill cannot split a turn. SETTING THE ENV ALONE MUST DO NOTHING
    (this is the property that survives SEAM_PATCH_B landing in answer.py)."""
    assert inspect.signature(pl.ground).parameters["bridge_query"].default is False
    # NO LINE OF THIS MODULE BOTH NAMES THE VAR AND READS AN ENVIRONMENT (the docstrings name it; the
    # code never reads it). The behavioural half below is the pin that survives the seam landing.
    assert not [ln for ln in inspect.getsource(pl).splitlines()
                if "GRAPHRAG_BRIDGE_QUERY" in ln and "environ" in ln]
    monkeypatch.setenv("GRAPHRAG_BRIDGE_QUERY", "1")
    _sg_, rec = _run(bridge=False)                                # the kwarg is what arms it, never the env
    assert rec.calls and {c["query"] for c in rec.calls} == {QUESTION}
    assert "bridge_query" not in _sg_.trace


def test_flag_off_is_the_shipped_call_and_stamps_no_trace_key():
    """BYTE-IDENTICAL SET rows 2 and 5, at the seam: with the kwarg at its default every node is handed
    the QUESTION with EXACTLY the four shipped keyword arguments and no `candidates`, and NO
    `bridge_query` key exists on the trace. The OFF arm can RECONSTRUCT the denominator from what every
    walk already stamps (`eligible` minus the seeds' own legs, with `walk_shape.hop_contracts` naming its
    CONTRACT half), which is why stamping nothing here costs the arms nothing -- threat P-9, a deliberate
    deviation from D-GD-1's both-polarities precedent."""
    sg, rec = _run(bridge=False)
    assert rec.calls and all(set(c) == {"query", "slice", "k", "asof", "near"} for c in rec.calls)
    assert {c["query"] for c in rec.calls} == {QUESTION}
    assert "bridge_query" not in sg.trace
    assert sg.trace["walk_shape"]["hop_contracts"] == 2           # the population the ON arm will bridge


# ══ THE ITEM: the hop contract retrieves with its admitting edge's mechanism ══════════════════════════
def test_a_hop_contract_retrieves_with_the_admitting_edge_mechanism_verbatim():
    """THE WHOLE POINT. beta was admitted by cos(question, MECH_AB); it now READS with MECH_AB. gamma
    likewise with its own edge. The seed reads with the question."""
    sg, rec = _run(bridge=True)
    by = rec.by_slice()
    assert by["alpha"] == QUESTION                                # the seed IS the question's market
    assert by["beta"] == MECH_AB
    assert by["gamma"] == MECH_AC
    # the widened population: two hop contracts + the three depth-1 drivers that cleared tau
    assert sg.trace["bridge_query"] == {"nodes": 5, "applied": 5, "distinct": 5, "fallback": {}}


def test_a_driver_reads_with_its_own_admitting_mechanism_not_with_the_question():
    """THE RULING OF 2026-09-15, AND THE HALF THE FIRST BUILD LEFT ON THE QUESTION. A driver is enqueued
    with `via=None` and carries NO edge, so `via_edge["mechanism"]` selects ZERO drivers -- the admitting
    text for a driver is the DRIVER'S OWN mechanism, which is literally the string the walk's `_relevance`
    scored to admit it (`rel = _relevance(qv, graph.driver(cid, id_).mechanism, ...)`). That is what it
    now reads with."""
    gr = _graph()
    sg, rec = _run(bridge=True, gr=gr)
    by = rec.by_slice()
    assert {k: v for k, v in by.items() if k.startswith("drivers/")} == _D1_BRIDGES
    for did, mech in (("frost", MECH_FROST), ("acreage", MECH_ACRE), ("ratio", MECH_RATIO)):
        assert gr.driver("alpha", did).mechanism == mech           # the walk scored THIS string
    assert sg.trace["bridge_query"]["applied"] == 5


def test_a_depth_two_driver_of_a_hop_contract_bridges_and_that_is_the_multi_hop_chain():
    """THE MULTI-HOP CASE, WHICH IS WHY THE POPULATION WAS WIDENED. The D-MW-13 hop fence keeps CONTRACT
    depth at 0 or 1, so the chain the defect statement describes (LNG -> fertilizer -> corn -> wheat ->
    x -> y) does not exist in the contract layer at all: it exists as DRIVERS OF A HOP CONTRACT at depth
    2 -- MEASURED 26 of the 149-node bridgeable population on the recon max walk (tier_census_bge.json:
    189 kept, 152 retrieving, 12 hop contracts + 111 depth-1 drivers + 26 depth-2 drivers). `shift` is
    beta's driver, reached only through the
    alpha->beta edge, and on a corn-shaped question it is exactly the node whose sentences were being
    ranked by a word from two hops away."""
    gr = _graph(onward=True)
    sg, rec = _run(bridge=True, gr=gr, depth=2)
    shift = next(n for n in sg.nodes if n.kind == "driver" and n.id == "shift")
    assert (shift.depth, shift.contract) == (2, "beta")
    assert rec.by_slice()["drivers/shift"] == MECH_SHIFT
    assert rec.by_slice()["delta"] == MECH_BD                      # the depth-2 hop CONTRACT, too
    assert rec.by_slice()["alpha"] == QUESTION                     # and only the seed keeps the question
    assert sum(1 for c in rec.calls if c["query"] == QUESTION) == 1


def test_the_bridge_text_is_the_mechanism_byte_for_byte():
    """O-8 + surprise 1. No trim, no prefix, no lowercasing, no token cap. `ev._Q_CACHE` keys on
    `(backend, text)` and `planner._relevance` already embedded this exact string during the walk, so any
    normalisation here would turn a free memo read into a PAID embed per node, silently -- and the vector
    leg and the rerank leg would stop scoring the same string."""
    mech = "  Corn and soybeans compete for the same U.S. acreage; frost substitute acreage ratio.  "
    drv = "  Frost at pollination; frost damage.  "
    gr = _graph(mech_ab=mech, mech_frost=drv)
    sg, rec = _run(bridge=True, gr=gr)
    assert rec.by_slice()["beta"] == mech                         # including its leading/trailing spaces
    assert rec.by_slice()["drivers/frost"] == drv                 # and the driver half, the same way
    assert sg.trace["bridge_query"]["applied"] == 5


def test_a_depth_two_hop_contract_bridges_too_with_its_own_admitting_edge():
    """THE PREDICATE IS `depth > 0`, NOT `depth == 1`. On the seed-scaled serving presets the D-MW-13 hop
    fence drops `d+1 >= 2` hop contracts, so today's population is exactly the depth-1 hops -- but the
    fence arms only under `per_seed_budget`, and the rule must not silently depend on it."""
    gr = _graph(onward=True)
    sg, rec = _run(bridge=True, gr=gr, depth=2)
    d = {n.contract: n.depth for n in sg.nodes if n.kind == "contract"}
    assert d == {"alpha": 0, "beta": 1, "gamma": 1, "delta": 2}
    assert rec.by_slice()["delta"] == MECH_BD
    assert sg.trace["bridge_query"]["nodes"] == len(rec.calls) - 1  # every retrieving node but the seed


# ══ POPULATION: O-5, O-6 ═════════════════════════════════════════════════════════════════════════════
def test_seeds_are_outside_the_population_and_never_land_in_the_fallback_tally():
    """O-5. A seed contract node carries NO `via_edge` -- it was never admitted by an edge. If the
    predicate tested `kind == 'contract'` alone it would fall into the `no_via_edge` branch and the
    FALLBACK TALLY would read as a defect on every turn. The depth test comes FIRST, so a seed is neither
    in the denominator nor in the tally."""
    sg, rec = _run(bridge=True)
    seeds = [n for n in sg.nodes if n.depth == 0]
    assert seeds and all(n.via_edge is None for n in seeds)
    assert rec.by_slice()["alpha"] == QUESTION
    bq = sg.trace["bridge_query"]
    assert bq["nodes"] == len(rec.calls) - len(seeds)             # every retrieving node but the seeds
    assert sg.trace["walk_shape"]["hop_contracts"] == 2           # the CONTRACT half of that denominator
    assert bq["fallback"] == {}


def test_a_prior_only_driver_is_outside_the_population_entirely(monkeypatch):
    """THE DENOMINATOR IS THE RETRIEVING POPULATION. A driver with no backing id or no slice is a
    prior-only node: `_fill_slice` returns None and it issues NO fetch at all, so there is nothing to
    re-rank. Tallying it would inflate `nodes`, and WARMING its mechanism would be a paid embed for a
    fetch that never happens (MEASURED: 37 of the 189 nodes kept on the recon max walk are exactly this --
    189 kept, 152 retrieving, tier_census_bge.json)."""
    gr = _graph()
    sg = _sg(gr)
    rec = _Recorder()
    warmed = _spy_bridges(monkeypatch)
    # `ratio` keeps its node but loses its backing id -> prior-only
    pl.ground(sg, QUESTION, gr, retrieve=rec, silver_lookup=None,
              driver_slices=set(_DRIVERS) - {"ratio"}, probe_cap=0, bridge_query=True)
    assert "drivers/ratio" not in rec.by_slice()                  # it never retrieved
    bq = sg.trace["bridge_query"]
    assert bq["nodes"] == 4 and bq["applied"] == 4 and bq["fallback"] == {}
    assert warmed and MECH_RATIO not in warmed[-1]                # and it was never WARMED either
    assert set(warmed[-1]) == {MECH_AB, MECH_AC, MECH_FROST, MECH_ACRE}


# ══ FALLBACKS: O-1, O-2, O-3, A-2 ════════════════════════════════════════════════════════════════════
def test_a_hop_with_no_via_edge_falls_back_to_the_question_and_is_counted():
    """O-1. `(n.via_edge or {})` is `{}` and `.get('mechanism')` is None -- a naive `str(...)` would rank
    the node against the literal word 'None'. Defensive today (every admission path builds a `via` dict),
    pinned anyway: a new admission source is one commit away."""
    gr = _graph()
    sg = pl.Subgraph(seeds=["alpha"], nodes=[
        pl.GroundedNode(kind="contract", id="alpha", contract="alpha", depth=0, relevance=1.0),
        pl.GroundedNode(kind="contract", id="beta", contract="beta", depth=1, relevance=0.7, via_edge=None)])
    rec = _Recorder()
    _ground(gr, sg, rec, bridge_query=True)
    assert rec.by_slice() == {"alpha": QUESTION, "beta": QUESTION}
    assert sg.trace["bridge_query"] == {"nodes": 1, "applied": 0, "distinct": 0,
                                        "fallback": {"no_via_edge": 1}}


@pytest.mark.parametrize("mech", ["", "   ", "\n\t "])
def test_an_empty_or_whitespace_mechanism_falls_back_to_the_question_and_is_counted(mech):
    """O-2. An empty tsquery is `to_tsquery('simple','')` and an empty vector leg embeds the empty string.

    REACHABILITY, stated: `_relevance` returns 0.0 WITHOUT embedding on empty text, so a COSINE-admitted
    hop with a blank mechanism is pruned by tau -- this path is live exactly where tau cannot prune it,
    i.e. the tau-exempt cascade slot (`_cascade_plan` sorts a 0.0 row last but does not drop it). Driven
    here with `tau=0.0`, which is the same arithmetic without needing a slot."""
    gr = _graph(mech_ab=mech, mech_frost=mech)
    sg, rec = _run(bridge=True, gr=gr, tau=0.0)
    assert rec.by_slice()["beta"] == QUESTION                     # the hop CONTRACT half
    assert rec.by_slice()["drivers/frost"] == QUESTION            # and the DRIVER half, same reason
    assert rec.by_slice()["gamma"] == MECH_AC                     # its sibling still bridges
    bq = sg.trace["bridge_query"]
    assert bq["fallback"] == {"empty_mechanism": 2}
    assert bq["applied"] == bq["nodes"] - 2


# THE CASCADE SLOT ITSELF -- the admission path R-10 named, driven rather than argued (review MINOR, round
# 2: the case above reaches the same BRANCH through `tau=0.0`, which is the same arithmetic but not the
# same admission). `zeta` declares `alpha` as a driver_commodity with a BLANK mechanism, so
# `graph.rev_cross_links("alpha")` offers it, `_cascade_plan` scores it 0.0 and -- being tau-EXEMPT --
# BUYS it anyway while a slot remains. That is the one live path on which a blank admitting text reaches
# `_bridge_of` on a shipped preset (`max_cc1` carries one slot).
def _cascade_graph(mech_zeta: str = "") -> g.CausalGraph:
    base = _graph()
    out = dict(base.contracts)
    out["zeta"] = cs.CausalContract(contract="zeta", aliases=["zeta"], drivers=[_d("nino", "el nino climate")],
                                    inter_commodity=[_edge("alpha", mech_zeta)])
    return g.CausalGraph(out, silver=set())


def _cascade_slot_run(*, bridge: bool, mech_zeta: str = ""):
    gr = _cascade_graph(mech_zeta)
    sg = _sg(gr, cascade_contract_slots=1)
    rec = _Recorder()
    _ground(gr, sg, rec, bridge_query=bridge)
    return sg, rec


def test_a_cascade_slot_hop_with_a_blank_mechanism_keeps_the_question_and_is_counted():
    """R-10's ACTUAL ADMISSION PATH, with the slot spent. The bought node is a depth-1 CONTRACT carrying a
    `via_edge` whose `reason` is `cascade_downstream_contract` and whose `mechanism` is the empty string --
    it is INSIDE the population (`ev.node_for('zeta')` resolves, so it retrieves), it keeps the question,
    and it is counted `empty_mechanism`. Its siblings bridge around it, and the same slot with a NON-blank
    mechanism bridges on that mechanism, which is what makes the first half a property of the TEXT rather
    than of the cascade."""
    sg, rec = _cascade_slot_run(bridge=True)
    by = rec.by_slice()
    assert by["zeta"] == QUESTION                                  # the paid foreign block, un-bridged
    assert by["beta"] == MECH_AB and by["drivers/frost"] == MECH_FROST
    bq = sg.trace["bridge_query"]
    assert bq["fallback"] == {"empty_mechanism": 1}
    assert bq["nodes"] == bq["applied"] + 1
    # the same slot, a real mechanism: the cascade hop bridges like every other hop
    sg2, rec2 = _cascade_slot_run(bridge=True, mech_zeta=MECH_BD)
    assert rec2.by_slice()["zeta"] == MECH_BD
    assert sg2.trace["bridge_query"]["fallback"] == {}


def test_a_driver_whose_mechanism_cannot_be_read_falls_back_to_the_question_and_is_counted():
    """THE DRIVER MIRROR OF O-1. A hop contract's missing text is `no_via_edge`; a driver's is a graph
    lookup that RAISES (an id the DAG no longer carries, a contract renamed under it -- the estate has a
    string-identity-join precedent for exactly this). It must take the question and be COUNTED, never
    become a `None` the embedder is handed."""
    gr = _graph()
    sg = _sg(gr)                                                   # the walk scores BEFORE the break
    real_driver = gr.driver

    def _boom(cid, did):
        if did == "acreage":
            raise KeyError(did)
        return real_driver(cid, did)

    gr.driver = _boom
    rec = _Recorder()
    _ground(gr, sg, rec, bridge_query=True)
    assert rec.by_slice()["drivers/acreage"] == QUESTION
    assert rec.by_slice()["drivers/frost"] == MECH_FROST           # its siblings are untouched
    assert sg.trace["bridge_query"]["fallback"] == {"no_driver_mechanism": 1}


def test_a_node_kind_the_predicate_cannot_read_keeps_the_question_and_is_counted():
    """THE UNCOUNTED-None BRANCH, CLOSED (review MINOR, 2026-09-15). `GroundedNode.kind` is
    {contract, driver} today, so `_bridge_of`'s `else` was unreachable -- and it returned None WITHOUT
    counting, which made the stamp's arithmetic (`nodes == applied + sum(fallback)`) true by accident of
    an enum rather than by construction. A third kind IS in the population the moment `_fill_slice` gives
    it a slice, and it does: `_slice_of` tests `n.kind == "contract"` and sends EVERYTHING ELSE down the
    `slice_path(n.id)` branch, so a future kind retrieves (here as `drivers/<id>`, the injected-slice
    form) while `_bridge_of` has no admitting text for it. It must keep the question AND be counted.
    Driven by mutating a kept node's kind AFTER the walk -- the only way to reach a kind the walk cannot
    yet produce."""
    gr = _graph()
    sg = _sg(gr)
    for n in sg.nodes:
        if n.kind == "contract" and n.depth == 1:
            n.kind = "future_kind"                                 # a kind this predicate cannot read
    rec = _Recorder()
    _ground(gr, sg, rec, bridge_query=True)
    bq = sg.trace["bridge_query"]
    assert bq["fallback"].get("unknown_kind") == 2                 # beta and gamma
    by = rec.by_slice()
    assert by["drivers/beta"] == QUESTION and by["drivers/gamma"] == QUESTION   # they DID retrieve
    assert by["drivers/frost"] == MECH_FROST                       # the driver half is untouched
    assert bq["nodes"] == bq["applied"] + sum(bq["fallback"].values())


# ══ THE FIRING RECEIPT: no fence, and the honest claim pinned in its place (R-13) ════════════════════
# `planner.ground`'s regime leg pre-seeds its probe cache from each driver node's KEPT ROWS --
# `probe_cache[(cid, did)] = _recent(n.evidence)` -- so bridging a regime-required driver makes its firing
# receipt BRIDGE-RANKED, and `n_probes` / `regime_basis` / `silver_veto` / `fired_regimes` may move.
#
# A FENCE HELD THOSE FOUR ON THE QUESTION UNTIL 2026-09-15 AND WAS REMOVED, because it did not buy what it
# charged for: `_dedup_and_cap` sits BETWEEN the fill the fence protected and the leg it protected for, and
# spends ONE GLOBAL budget attributing each prop to the SHALLOWEST node -- so a BRIDGED SIBLING moved the
# fenced driver's kept rows anyway. MEASURED on the real graph topology with cross-node dedup live,
# 13 OF 36 lane shapes moved `regime_basis` with the fence in place (review/rev2_fence_lane_sweep.out),
# while the fence was deleting the bridge from 33-42% of the driver population -- the multi-hop chain the
# widening was ordered for included.
#
# THIS DECK'S `_Recorder` CANNOT SEE THAT MECHANISM (it returns a source_key unique per slice, so cross-node
# dedup can never fire) -- which is exactly why the four counts are NO LONGER PINNED EQUAL here. What is
# pinned instead is the DIRECTION: `_DatedRecorder` makes the row a node keeps depend on the query text, so
# the receipt is asserted to FOLLOW THE BRIDGE rather than asserted to stay still.
_ASOF = "2021-08-01"


def _firing_run(*, bridge: bool, converge=("frost", "rain"), asof=_ASOF, probe_cap: int = 8, rec=None):
    gr = _graph(converge=converge)
    sg = _sg(gr)
    rec = rec if rec is not None else _Recorder()
    pl.ground(sg, QUESTION, gr, retrieve=rec, silver_lookup=None, driver_slices=set(_DRIVERS),
              asof=asof, probe_cap=probe_cap, bridge_query=bridge)
    return sg, rec


class _DatedRecorder(_Recorder):
    """A retriever whose ROW DATE depends on the QUERY -- the minimum a hermetic double needs in order to
    make "the receipt follows the rows" observable. The question's row is dated later than the bridge's, so
    a receipt that moved really did come from the bridge-ranked fetch and not from a re-ordering."""

    def __call__(self, query, slice_, *, k, asof=None, near=None):
        self.calls.append({"query": query, "slice": slice_, "k": k, "asof": asof, "near": near})
        d = "2021-07-25" if query == QUESTION else "2021-07-10"
        return [{"date": d, "source": "GAIN", "source_key": f"s3://{slice_}", "text": f"{slice_} row"}]


def test_a_regime_required_driver_is_bridged_like_every_other_driver(monkeypatch):
    """R-13, THE DELETION UNDONE. `frost` is named by alpha's convergence signal, so the firing loop reads
    `probe_cache[("alpha", "frost")]` and the pre-seed fills it from `frost`'s own kept rows. It is bridged
    ANYWAY: `fallback` is EMPTY, the whole population is applied, and the vocabulary no longer contains the
    word. Asserted on an AS-OF turn with a live probe budget -- the exact condition the fence armed on."""
    sg, rec = _firing_run(bridge=True)
    by = rec.by_slice()
    assert by["drivers/frost"] == MECH_FROST                       # the formerly fenced driver
    assert by["drivers/acreage"] == MECH_ACRE
    assert by["drivers/ratio"] == MECH_RATIO
    assert by["beta"] == MECH_AB
    bq = sg.trace["bridge_query"]
    assert bq["fallback"] == {} and bq["applied"] == bq["nodes"] == 5
    # THE VOCABULARY ITSELF, read off the module: five reasons, and `regime_receipt` is not one of them.
    # Pinned as a SET rather than as an absence so a sixth reason added without a pin is caught too.
    assert set(re.findall(r'_bump\(_bq_fallback, "([a-z_]+)"\)', inspect.getsource(pl))) == {
        "rerank_lane_bedrock", "no_via_edge", "no_driver_mechanism", "unknown_kind", "empty_mechanism"}


@pytest.mark.parametrize("asof", [None, "not-a-date", "2021-13-45", _ASOF])
def test_the_bridge_population_no_longer_depends_on_the_as_of_at_all(asof):
    """THE AS-OF WAS THE FENCE'S ONLY ARMING CONDITION, so with the fence gone it decides nothing about
    WHICH nodes bridge -- a dead firing leg (None / unparseable) and a live one give the same population.
    Kept as a parametrize over the same three inputs the fence's own gate was pinned on, so the removal is
    covered on exactly the cases that used to distinguish it, plus the live one."""
    sg, rec = _firing_run(bridge=True, asof=asof)
    assert rec.by_slice()["drivers/frost"] == MECH_FROST
    bq = sg.trace["bridge_query"]
    assert bq["fallback"] == {} and bq["applied"] == 5


def test_the_firing_receipt_follows_the_bridged_rows_and_that_is_the_whole_claim():
    """THE HONEST CLAIM, PINNED AS A MOVEMENT (R-13). A bridged driver's firing receipt IS its bridge-ranked
    rows -- one retrieval, no second row set, no extra borrow. With a query-dependent retriever the receipt
    for `frost` moves 2021-07-25 -> 2021-07-10 across the arms, i.e. it came from the BRIDGE fetch. The
    four regime outcomes are NOT asserted equal anywhere in this deck any more; they are measured off vs on
    over 36 real lane shapes and three fixtures in MEASURED.md section 8."""
    off_sg, off_rec = _firing_run(bridge=False, converge=("frost",), rec=_DatedRecorder())
    on_sg, on_rec = _firing_run(bridge=True, converge=("frost",), rec=_DatedRecorder())
    assert {c["query"] for c in off_rec.calls} == {QUESTION}       # the control really was question-only
    assert on_rec.by_slice()["drivers/frost"] == MECH_FROST        # and the ON arm really did bridge it
    assert off_sg.trace["regime_basis"]["alpha"]["frost"]["date"] == "2021-07-25"
    assert on_sg.trace["regime_basis"]["alpha"]["frost"]["date"] == "2021-07-10"
    # ...AND IT COST NOTHING EXTRA: the same one call per node on both arms, same slice, same k, same
    # as-of. The receipt changed because the ROWS changed, not because a second fetch was issued.
    assert len(off_rec.calls) == len(on_rec.calls)
    assert (collections.Counter((c["slice"], c["k"], c["asof"], c["near"]) for c in off_rec.calls)
            == collections.Counter((c["slice"], c["k"], c["asof"], c["near"]) for c in on_rec.calls))
    assert off_sg.trace["n_probes"] == on_sg.trace["n_probes"] == 0   # both receipts came from kept rows


def test_the_probe_leg_itself_keeps_the_question_on_both_arms():
    """A PROBE IS AN EXISTENCE CHECK, NOT A RANKING. It is keyed `(contract, driver)` and SHARED across
    the nodes that need it, so it has no single admitting edge to write its query -- and its result is a
    pinned count. The bridge touches `_fill` and nothing else; `probe_retrieve` is a separate callable
    that never sees the map."""
    seen: list = []
    gr = _graph(converge=("rain",))      # `rain` is tau-pruned: no node, no pre-seed, a REAL probe
    sg = _sg(gr)
    pl.ground(sg, QUESTION, gr, retrieve=_Recorder(), silver_lookup=None, driver_slices=set(_DRIVERS),
              asof=_ASOF, probe_cap=8, bridge_query=True,
              probe_retrieve=lambda q, sp, **kw: (seen.append((q, sp)), [])[1])
    assert seen and {q for q, _sp in seen} == {QUESTION}


def test_two_hops_sharing_one_mechanism_collapse_distinct_but_not_applied():
    """O-3. Byte-identical mechanism strings on two edges: ONE rerank group and ONE `_Q_CACHE` entry serve
    both, which is correct -- so the counter must make the collapse VISIBLE rather than the code prevent
    it. Measured 0 of 12 on the real deep/max walks; the COUNTER is what is pinned, not the absence."""
    gr = _graph(mech_ab=MECH_AB, mech_ac=MECH_AB, mech_frost=MECH_AB)
    sg, rec = _run(bridge=True, gr=gr)
    assert rec.by_slice()["beta"] == rec.by_slice()["gamma"] == MECH_AB
    assert rec.by_slice()["drivers/frost"] == MECH_AB              # across the KINDS, too
    bq = sg.trace["bridge_query"]
    assert bq["applied"] == 5 and bq["distinct"] == 3 and bq["distinct"] <= bq["applied"]


@pytest.mark.parametrize("backend,armed", [("bedrock", False), ("cohere", True), ("bge", True),
                                           ("BEDROCK", True)])
def test_the_bridge_refuses_to_arm_on_the_bedrock_rerank_lane(monkeypatch, backend, armed):
    """A-2, THE LARGEST THREAT IN THE INSTRUMENT AND THE ONE THE BRIEF DID NOT NAME.

    `rankers._RerankCoalescer._fire` groups a drained batch BY QUERY STRING, so per-node bridges turn ONE
    query group into `1 + distinct bridges` -- MEASURED on the real embedder, 1 -> 80 distinct query
    strings on a deep walk and 1 -> 148 on max (tier_census_bge.json, re-measured with the regime fence
    removed -- the fenced figures were 1 -> 54 and 1 -> 96); REQUESTS are bounded PER DRAIN, and
    the drain holds up to `planner.MAX_FILL_POOL` = 64 callers on this lane -- `_parallel_fill` widens its
    pool to 64 exactly when `_rerank_backend()` is managed (MEASURED: 82 eligible nodes -> 64 workers,
    152 -> 64). So up to 64 groups per drain, dispatched `rk._coalesce_group_workers()` at a time
    (THREAT_MODEL 8.4). The earlier bound in this docstring said 8 and was 8x too small.
    On the native cohere lane that is latency (quality beats latency, owner doctrine). On the BEDROCK
    ROLLBACK lane it is a cliff: 3 req/min, L-11512E58, Adjustable=FALSE, and `_fire` dispatches groups
    SEQUENTIALLY there because packing is cohere-only -- ~5.7 minutes of serialized requests, every member
    blowing the 90 s `_COALESCE_MEMBER_WAIT` and falling back to bge at 13.88 s per 60-doc pool.

    So the fence lives IN CODE, at a seam this module already reads, where a taskdef edit cannot forget
    it. `_rerank_backend()` lowercases its own read, so the "BEDROCK" row here arms only because the
    monkeypatch bypasses that normalisation -- it pins that the comparison is against the function's
    OUTPUT, not against a raw environment string this module would have to normalise a second time."""
    monkeypatch.setattr(rk, "_rerank_backend", lambda: backend)
    sg, rec = _run(bridge=True)
    bq = sg.trace["bridge_query"]
    if armed:
        assert rec.by_slice()["beta"] == MECH_AB
        assert rec.by_slice()["drivers/frost"] == MECH_FROST
        assert bq["applied"] == 5 and bq["fallback"] == {}
    else:
        assert {c["query"] for c in rec.calls} == {QUESTION}       # CONTRACTS AND DRIVERS ALIKE
        assert bq["nodes"] == 5 and bq["applied"] == 0
        assert bq["fallback"] == {"rerank_lane_bedrock": 5}


def test_an_unreadable_rerank_lane_fails_open_to_the_bridge(monkeypatch):
    """The fence itself must not become a new way to break a walk: an import or read that RAISES leaves
    the bridge armed (the lane it would have refused is one specific string, not 'anything unknown')."""
    def _boom():
        raise RuntimeError("no params")
    monkeypatch.setattr(rk, "_rerank_backend", _boom)
    sg, rec = _run(bridge=True)
    assert rec.by_slice()["beta"] == MECH_AB
    assert sg.trace["bridge_query"]["applied"] == 5


# ══ THE PATH THAT WRITES THE QUERY: O-4, P-2 ═════════════════════════════════════════════════════════
def test_the_recorded_path_writes_the_query_and_two_runs_agree():
    """O-4 + surprise 8 + P-2. A node reachable from TWO seeds keeps the via_edge of whichever parent the
    QUESTION-RANKED WAVE ORDER reached it with first (`visited` is stamped at first encounter,
    planner.py's scoring loop). So the honest claim is 'THE QUESTION CHOOSES THE PATH, THE PATH WRITES THE
    QUERY' -- not 'the question never touches far-node ranking'. What is pinned: the bridge is the edge
    ACTUALLY RECORDED ON THE NODE, and it is DETERMINISTIC across runs."""
    epsilon = cs.CausalContract(contract="epsilon", aliases=["epsilon"],
                                drivers=[_d("rain", "rain only", sign="-")],
                                inter_commodity=[_edge("beta", "frost substitute ratio drought")])
    gr = _graph()
    gr = g.CausalGraph({**gr.contracts, "epsilon": epsilon}, silver=set())
    seen = []
    for _ in range(2):
        sg, rec = _run(bridge=True, gr=gr, seeds=("alpha", "epsilon"))
        beta = next(n for n in sg.nodes if n.contract == "beta" and n.depth == 1)
        assert rec.by_slice()["beta"] == (beta.via_edge or {})["mechanism"]
        seen.append((rec.by_slice()["beta"], tuple(sorted(rec.by_slice()))))
    assert seen[0] == seen[1]                                     # deterministic given (query, embedder)


def test_the_bridge_survives_a_cleared_query_memo():
    """P-2. `ev._Q_CACHE` is an OPTIMISATION, never a decision: clearing it between runs cannot change a
    single row or a single query string."""
    first = _run(bridge=True)[1].by_slice()
    ev._Q_CACHE.clear()
    assert _run(bridge=True)[1].by_slice() == first


# ══ ALL THREE LEGS TAKE THE BRIDGE: the flat path, end to end ════════════════════════════════════════
def test_the_same_bridge_text_reaches_the_vector_leg_the_bm25_leg_and_the_rerank_query(monkeypatch):
    """THE BRIEF'S CENTRAL CLAIM, PROVEN THROUGH THE REAL `ev.retrieve` RATHER THAN ASSERTED: one
    positional argument feeds the embedding, `rankers.hybrid_candidates` (the lexical leg) and
    `rankers.rerank_scores` (the rerank QUERY FIELD). This is also the evidence that `evidence.py` and
    `pgstore.py` need NO seam change -- the bridge reaches `_tsquery` through the shipped signature."""
    seen: dict = {"embed": [], "hybrid": [], "rerank": []}
    recs = [{"date": "2021-07-20", "source": "GAIN", "source_key": "s3://x", "text": "frost damage row",
             "vector": _embed(["frost damage"])[0], "backend": None},
            {"date": "2021-07-21", "source": "GAIN", "source_key": "s3://y", "text": "acreage ratio row",
             "vector": _embed(["acreage ratio"])[0], "backend": None}]
    real_embed = ev.embed

    def _spy_embed(texts, **k):
        if len(texts) == 1:
            seen["embed"].append(texts[0])
        return _embed(texts)

    monkeypatch.setattr(ev, "embed", _spy_embed)
    monkeypatch.setattr(rk, "hybrid_candidates",
                        lambda q, node, allr, asof, dense, fk: (seen["hybrid"].append(q), dense[:fk])[1])
    monkeypatch.setattr(rk, "rerank_scores",
                        lambda q, texts: (seen["rerank"].append(q), [1.0] * len(texts))[1])
    retr = functools.partial(ev.retrieve, records=recs, mode="hybrid", rerank=True, mmr=0.0)
    gr = _graph()
    sg = _sg(gr)
    pl.ground(sg, QUESTION, gr, retrieve=retr, silver_lookup=None, driver_slices=set(_DRIVERS),
              probe_cap=0, bridge_query=True)
    assert real_embed is not ev.embed                             # the spy really is installed
    for leg in ("embed", "hybrid", "rerank"):
        assert MECH_AB in seen[leg], leg                          # the hop CONTRACT's bridge, this leg
        assert MECH_FROST in seen[leg], leg                       # the DRIVER's bridge, the same leg
        assert QUESTION in seen[leg], leg                         # and the seed still reached it
    assert sg.trace["bridge_query"]["applied"] == 5


# ══ EC-2: A-1, the one real leak channel ═════════════════════════════════════════════════════════════
QV_Q = _embed([QUESTION])[0]


@pytest.fixture()
def wired(monkeypatch):
    """The serving shape with the two pg leaves faked: `fetch_candidates_batch` returns a sentinel map and
    `fetch_candidates` (the PER-NODE borrow a bridge node takes) RECORDS the `(qv, query_text)` it was
    handed -- which is exactly the pair `_tsquery` and the dense CTE are built from."""
    monkeypatch.setenv("GRAPHRAG_EVIDENCE_BATCH", "1")
    monkeypatch.setenv("EVIDENCE_BACKEND", "pg")
    monkeypatch.setattr(ev, "embed", lambda t, **k: _embed(t))
    seen: dict = {"batch": [], "own": []}

    def fake_batch(qv, qt, nodes, **kw):
        seen["batch"].append({"qv": list(qv), "query_text": qt, "nodes": list(nodes), **kw})
        return {n: [{"node": n, "id": f"{n}-0", "vector": QV_Q, "date": "2021-07-20", "source": "GAIN",
                     "source_key": f"s3://{n}", "text": f"{n} row"}] for n in nodes}

    def fake_fetch(qv, qt, node, *, asof=None, fetch_k=60, hybrid=True, conn=None, with_vectors=True,
                   candidates=None, _force_exact=False):
        if candidates is not None:
            return list(candidates)
        seen["own"].append({"qv": list(qv), "query_text": qt, "node": node, "fetch_k": fetch_k,
                            "hybrid": hybrid, "with_vectors": with_vectors, "asof": asof,
                            "tsq": pg._tsquery(qt), "n_tokens": len(dict.fromkeys(rk.tokenize(qt)))})
        return [{"node": node, "id": f"{node}-own", "vector": QV_Q, "date": "2021-07-20", "source": "GAIN",
                 "source_key": f"s3://{node}", "text": f"{node} own row"}]

    monkeypatch.setattr(pg, "fetch_candidates_batch", fake_batch)
    monkeypatch.setattr(pg, "fetch_candidates", fake_fetch)
    monkeypatch.setattr(rk, "rerank_scores", lambda q, texts: [1.0] * len(texts))
    return seen


def _wired_ground(*, bridge: bool, node_for=None, monkeypatch=None):
    retr = functools.partial(ev.retrieve, mode="hybrid", rerank=True, mmr=0.5, fairness=0.3)
    gr = _graph()
    if node_for is not None:
        monkeypatch.setattr(ev, "node_for", node_for)
    sg = _sg(gr)
    pl.ground(sg, QUESTION, gr, retrieve=retr, silver_lookup=None, driver_slices=set(_DRIVERS),
              probe_cap=0, bridge_query=bridge)
    return sg


def test_the_wants_census_counts_a_bridge_node_out_and_the_question_node_in(wired, monkeypatch):
    """A-1, THE LEAK CHANNEL, AT THE `wants` END -- and it is not hypothetical: on the measured deep/max
    walks `wants['soybeans'] == 2`, because the seed `soybeans` (question) and the hop `soybeans_cbot`
    (bridge) resolve to ONE slice. Here `node_for` is faked to reproduce exactly that.

    Over-counting leaves a slice's rows resident past their last consumer (~34-42 KB/row of live heap;
    the estate has an OOM-tore-the-store precedent). Under-counting drops rows a consumer still wants. So
    the census must use the SAME predicate `_fill` reads."""
    shared = lambda c: "alpha" if c in ("alpha", "beta") else c   # noqa: E731
    plans: dict = {}
    real = pl._Prefetch

    class _Spy(real):                                            # capture the plan the census produced
        def __init__(self, fetch, slices, wants, *, chunk):
            plans.setdefault("wants", dict(wants))
            plans.setdefault("slices", list(slices))
            super().__init__(fetch, slices, wants, chunk=chunk)
            plans["handle"] = self

    monkeypatch.setattr(pl, "_Prefetch", _Spy)
    _wired_ground(bridge=False, node_for=shared, monkeypatch=monkeypatch)
    off_wants, off_handle = plans.pop("wants"), plans.pop("handle")
    plans.clear()
    _wired_ground(bridge=True, node_for=shared, monkeypatch=monkeypatch)
    on_wants, on_handle = plans["wants"], plans["handle"]
    assert off_wants["alpha"] == 2                               # seed + hop share one slice, both take()
    assert on_wants["alpha"] == 1                                # the bridge node is counted OUT
    assert off_wants["gamma"] == 1 and "gamma" not in on_wants   # a bridge-only slice is not planned at all
    assert any(k.startswith("drivers/") for k in off_wants)      # and the DRIVER half, the same way:
    assert not any(k.startswith("drivers/") for k in on_wants)   # every bridged driver is counted out too
    assert on_wants == {"alpha": 1}                              # only the SEED still reads the batch
    for h in (off_handle, on_handle):                            # residency: nothing survives the fill
        assert h._ready == {} and h._want == {} and h._closed is True


def test_the_bridge_node_takes_its_own_borrow_with_the_bridge_vector_and_the_bridge_tsquery(wired):
    """A-1 AT THE `take` END. The EC-2 batch is fetched with the QUESTION's vector and the QUESTION's
    tsquery, so a bridge node taking from it would be re-scoring a candidate set THE QUESTION SELECTED --
    a re-ORDER inside the question's top-`fetch_k`, which is precisely the defect ('it only orders
    sentences inside a node the graph has already chosen'), not the fix. The dense leg's SELECTION has to
    move, not just its order. THE PRICE, stated rather than hidden: +1 pool borrow per bridge node."""
    sg = _wired_ground(bridge=True)
    batch = wired["batch"]
    assert batch and all(b["query_text"] == QUESTION for b in batch)
    assert all(b["qv"] == QV_Q for b in batch)
    assert "beta" not in sum((b["nodes"] for b in batch), [])     # never even planned for the batch
    own = {o["node"]: o for o in wired["own"]}
    assert set(own) == {"beta", "gamma", "drivers/frost", "drivers/acreage", "drivers/ratio"}
    for node, mech in (("beta", MECH_AB), ("drivers/frost", MECH_FROST)):   # a CONTRACT and a DRIVER
        assert own[node]["query_text"] == mech
        assert own[node]["qv"] == _embed([mech])[0] != QV_Q
        assert own[node]["tsq"] == pg._tsquery(mech) != pg._tsquery(QUESTION)
    assert sg.trace["bridge_query"]["applied"] == 5
    # O-9: the RECALL KNOBS do not move. `pgstore._tsquery` ORs every token, so a longer bridge is a
    # WIDER lexical net than the question, not a narrower one -- it can dilute the leg, never starve it,
    # because `fetch_k` is the bound and `fetch_k` is unchanged. Same for hybrid/with_vectors/asof: the
    # bridge changes the QUERY TEXT and nothing else about how the candidate set is sized or shaped.
    for o in own.values():
        assert (o["fetch_k"], o["hybrid"], o["with_vectors"], o["asof"]) ==                (int(ev._FETCH_K), True, True, None)
    assert own["beta"]["n_tokens"] >= len(dict.fromkeys(rk.tokenize(QUESTION)))


def test_flag_off_the_prefetch_plan_is_the_shipped_plan_and_nobody_borrows(wired):
    """BYTE-IDENTICAL SET row 1. With the kwarg at its default the `wants` dict, the slice list and every
    `fetch_candidates_batch` tuple are the shipped ones, and NO node takes its own borrow."""
    sg = _wired_ground(bridge=False)
    assert wired["own"] == []                                    # every node served by the batch
    nodes = sum((b["nodes"] for b in wired["batch"]), [])
    want = [ev.node_for(n.contract) if n.kind == "contract" else f"drivers/{n.id}" for n in sg.nodes]
    assert sorted(nodes) == sorted(set(want)) and len(nodes) == len(set(nodes))
    assert all(b["query_text"] == QUESTION and b["qv"] == QV_Q for b in wired["batch"])


def test_the_three_ec2_gates_are_unmoved_by_the_new_parameter(monkeypatch):
    """The `bridged` parameter is additive and defaults to an empty frozenset: every pre-existing caller
    and every gate behaves exactly as it did (the EC-2 deck calls this function positionally)."""
    gr = _graph()
    sg = _sg(gr)
    fs = lambda n: "alpha"                                        # noqa: E731
    monkeypatch.setenv("EVIDENCE_BACKEND", "pg")
    monkeypatch.setenv("GRAPHRAG_EVIDENCE_BATCH", "0")
    assert pl._ec2_prefetch(sg, "q", None, ev.retrieve, fs) is None
    monkeypatch.setenv("GRAPHRAG_EVIDENCE_BATCH", "1")
    assert pl._ec2_prefetch(sg, "q", None, _Recorder(), fs) is None
    monkeypatch.setenv("EVIDENCE_BACKEND", "flat")
    assert pl._ec2_prefetch(sg, "q", None, ev.retrieve, fs) is None


# ══ THE EMBED WARM: byte-identical set row 6, and O-7 ════════════════════════════════════════════════
def test_the_warm_embeds_each_distinct_bridge_once_and_nothing_when_the_map_is_empty(monkeypatch):
    """BYTE-IDENTICAL SET row 6. `bridges=()` -- the default and the whole flag-off path -- leaves the
    loop body unreached, so the OFF arm's embed-call count is HEAD's exactly. On the ON arm it is one
    warm per DISTINCT bridge, which in serving is normally a `_Q_CACHE` HIT costing zero network calls:
    `planner._relevance` already pushed that exact mechanism through `ev.embed` during the walk."""
    calls: list = []
    monkeypatch.setattr(ev, "embed", lambda t, **k: (calls.append(list(t)), _embed(t))[1])
    monkeypatch.setattr(pl, "_WALK_WORKERS", 4)
    pl._parallel_fill([1, 2, 3], lambda n: None, QUESTION, ev.retrieve)
    assert calls == [[QUESTION]]
    calls.clear()
    pl._parallel_fill([1, 2, 3], lambda n: None, QUESTION, ev.retrieve, bridges=(MECH_AB, MECH_AC))
    assert calls == [[QUESTION], [MECH_AB], [MECH_AC]]


def test_the_ground_seam_hands_the_warm_the_distinct_bridges_deduped(monkeypatch):
    """The caller dedupes: two hops sharing one mechanism warm it ONCE."""
    seen = _spy_bridges(monkeypatch)
    _run(bridge=False)
    assert seen[-1] == ()
    _run(bridge=True, gr=_graph(mech_ab=MECH_AB, mech_ac=MECH_AB, mech_frost=MECH_AB))
    assert seen[-1].count(MECH_AB) == 1                            # three nodes, ONE warm
    assert set(seen[-1]) == {MECH_AB, MECH_ACRE, MECH_RATIO} and len(seen[-1]) == 3
    _run(bridge=True)
    assert len(seen[-1]) == len(set(seen[-1])) == 5


def test_a_failing_bridge_warm_is_swallowed_and_the_node_still_retrieves(monkeypatch):
    """O-7. The warm is best-effort, exactly as the shipped query warm is. What the bridge must NOT do is
    become MORE fail-open than the shipped path: the RETRIEVE call itself is not wrapped by this lane, so
    a real embedder outage still fails the turn the way a question-embed failure does today, instead of
    being hidden behind a fallback the counter would then lie about."""
    monkeypatch.setattr(pl, "_WALK_WORKERS", 4)

    def _boom(texts, **k):
        if texts and texts[0] != QUESTION:
            raise RuntimeError("bridge embed down")
        return _embed(texts)

    monkeypatch.setattr(ev, "embed", _boom)
    sg, rec = _run(bridge=True)
    assert rec.by_slice()["beta"] == MECH_AB                       # the fill went ahead
    assert sg.trace["bridge_query"]["fallback"] == {}              # and claimed NO fallback that did not happen


def test_a_raising_bridge_node_propagates_exactly_as_a_raising_question_node_does(monkeypatch):
    """P-3. THE BRIDGE ADDS NO NEW SWALLOW. A node that dies inside the fill pool re-raises through
    `_parallel_fill.fn_` and kills the turn, exactly as a question node's failure does today -- because
    a retrieval outage that quietly became a thinner answer is worse than a failed turn.

    The coalescer's promise-retraction leg (`rerank_unexpect` in that same handler) is NOT exercised
    here and could not be: `_parallel_fill` only hints when the retriever IS `ev.retrieve`, and a
    hermetic double never is ("retracting a promise nobody made is a quota lie"). That leg is pinned
    where it belongs, on the real retriever, by
    tests/unit/test_serving_latency.py::test_parallel_fill_retracts_the_hint_when_a_node_raises -- and
    it is UNCHANGED by this lane, which adds no handler of its own."""
    monkeypatch.setattr(pl, "_WALK_WORKERS", 4)

    class _Boom(_Recorder):
        def __init__(self, on_bridge: bool):
            super().__init__()
            self._on_bridge = on_bridge

        def __call__(self, query, slice_, **kw):
            if (query != QUESTION) is self._on_bridge:             # exactly one node dies, either way
                raise RuntimeError("retriever down")
            return super().__call__(query, slice_, **kw)

    gr = _graph()
    with pytest.raises(RuntimeError, match="retriever down"):      # the BRIDGE node dies, flag on
        _ground(gr, _sg(gr), _Boom(True), bridge_query=True)
    # THE MIRROR IMAGE, which is the whole claim: the same failure reached through the QUESTION path with
    # the flag OFF kills the turn in exactly the same way. The bridge adds no handler and no new swallow.
    with pytest.raises(RuntimeError, match="retriever down"):
        _ground(gr, _sg(gr), _Boom(False), bridge_query=False)


# ══ THE COUNTS THAT MAY NOT MOVE: P-4, P-5, P-7, and the walk itself ═════════════════════════════════
# NARROWED BY R-13. `driver_legs`, `n_probes`, `silver_veto`, `regime_basis`, `fired_regimes` and `active`
# CAME OUT of this list when the regime fence was removed: the firing leg reads a bridged driver's
# bridge-ranked rows, so those outcomes are a RESULT of the arm and are reported off vs on rather than
# pinned. What remains is the RETRIEVAL PLAN and the walk that produced it -- the half the bridge is not
# allowed to touch, and the half `_Recorder` can honestly speak to.
_P4 = ("walk_shape",)


def test_every_count_in_the_p4_list_is_equal_across_the_two_arms(monkeypatch):
    """P-4, THE EC-2-GUARD ASSERTION IN ITS FINAL FORM: the bridge changes ORDER and TEXT inside a node,
    NEVER how many nodes retrieve or how many rows each is allowed. `grounded_subgraph` never sees the
    flag, so the whole walk is equal by construction -- and asserted anyway (the S7 STOP precedent: a
    brief that did not name what must stay byte-identical got the deep tier capped).

    THE RETRIEVE-CALL COMPARISON IS MADE TWICE, ON PURPOSE, because `_Recorder.calls` is an APPEND list
    and `_parallel_fill` appends in worker-COMPLETION order, which is not a plan fact (a review measured
    an ordered form of this assertion red in 1 run of 8 -- the flake is in the ASSERTION, never in the
    invariant: the MULTISET held in 30 of 30 hermetic paired runs and in 36 real-topology lane shapes):

      * at the SHIPPED width (`_WALK_WORKERS` untouched) the claim is a MULTISET -- the set of
        (slice, k, asof, near) tuples with multiplicity, which is exactly what "no node moved, no k
        moved" means and is what a concurrent fill can honestly promise;
      * pinned to ONE worker, where completion order IS plan order, the stronger ORDERED claim is made
        too -- so a bridge that re-ordered the fill plan itself would still be caught."""
    off_sg, off_rec = _run(bridge=False)
    on_sg, on_rec = _run(bridge=True)
    assert [list(n.key) for n in off_sg.nodes] == [list(n.key) for n in on_sg.nodes]
    assert off_sg.seeds == on_sg.seeds and off_sg.mermaid == on_sg.mermaid
    for key in _P4:
        assert off_sg.trace.get(key) == on_sg.trace.get(key), key
    # THE WALK, which the flag structurally cannot reach. `active`, `fired_regimes`, `driver_legs`,
    # `n_probes`, `silver_veto` and `regime_basis` are DELIBERATELY ABSENT from both lists (R-13): they are
    # outcomes of the FILL, they would be equal here only because this fixture's retriever is row-stable,
    # and a pin that can only ever pass is the vacuity the round-2 review named.
    for key in ("kept", "pruned", "visited", "budget", "params", "cascade_closure"):
        assert off_sg.trace.get(key) == on_sg.trace.get(key), key

    def _plan(rec):
        return [(c["slice"], c["k"], c["asof"], c["near"]) for c in rec.calls]

    # `eligible`, the SLICE each node reads and k per node: one call per node, same slice, same k
    assert collections.Counter(_plan(off_rec)) == collections.Counter(_plan(on_rec))
    assert len(off_rec.calls) == len(on_rec.calls)                 # one call per node, both arms
    monkeypatch.setattr(pl, "_WALK_WORKERS", 1)                    # completion order == plan order
    _, off1 = _run(bridge=False)
    _, on1 = _run(bridge=True)
    assert _plan(off1) == _plan(on1)
    assert collections.Counter(_plan(off1)) == collections.Counter(_plan(off_rec))   # and it is the SAME
    assert collections.Counter(_plan(on1)) == collections.Counter(_plan(on_rec))     # plan at either width


def test_the_stamp_arithmetic_is_closed_on_every_shape_of_this_deck(monkeypatch):
    """THE CLOSED WORD, PINNED AS ARITHMETIC AND NOT ONLY AS PER-CASE DICTS (review MINOR, 2026-09-15).
    Every other test here asserts a `fallback` dict it already knows; none of them asserted the IDENTITY
    that makes "fail open, closed word" mean anything: `nodes == applied + sum(fallback.values())`, i.e.
    every member of the denominator is either applied or counted BY REASON, with no third outcome. It
    held before only because `GroundedNode.kind` happened to be {contract, driver}; now it holds because
    `_bridge_of` counts every None it returns. Driven over every shape this deck builds -- each of the
    five fallback reasons, the multi-hop depth-2 shape, the prior-only shape and the plain arm."""
    def _check(sg, label):
        bq = sg.trace["bridge_query"]
        assert bq["nodes"] == bq["applied"] + sum(bq["fallback"].values()), (label, bq)
        assert bq["distinct"] <= bq["applied"], (label, bq)
        assert all(v > 0 for v in bq["fallback"].values()), (label, bq)   # no zero-valued reason
        return bq

    _check(_run(bridge=True)[0], "plain")
    _check(_run(bridge=True, gr=_graph(onward=True), depth=2)[0], "multi-hop depth 2")
    _check(_run(bridge=True, gr=_graph(mech_ab="", mech_frost="   "), tau=0.0)[0], "empty_mechanism")
    _check(_cascade_slot_run(bridge=True)[0], "empty_mechanism via a cascade slot")
    _check(_firing_run(bridge=True)[0], "an as-of turn with a live convergence signal")
    # prior-only: `ratio` keeps its node and loses its backing id
    gr = _graph()
    sg_p = _sg(gr)
    pl.ground(sg_p, QUESTION, gr, retrieve=_Recorder(), silver_lookup=None,
              driver_slices=set(_DRIVERS) - {"ratio"}, probe_cap=0, bridge_query=True)
    _check(sg_p, "prior-only")
    # an unreadable driver, and the bedrock lane, and an unknown kind
    gr_b = _graph()
    sg_b = _sg(gr_b)
    real_driver = gr_b.driver
    gr_b.driver = lambda cid, did: (_ for _ in ()).throw(KeyError(did)) if did == "acreage" \
        else real_driver(cid, did)
    _check(_ground(gr_b, sg_b, _Recorder(), bridge_query=True), "no_driver_mechanism")
    monkeypatch.setattr(rk, "_rerank_backend", lambda: "bedrock")
    assert _check(_run(bridge=True)[0], "rerank_lane_bedrock")["applied"] == 0
    monkeypatch.setattr(rk, "_rerank_backend", lambda: "cohere")
    gr_k = _graph()
    sg_k = _sg(gr_k)
    for n in sg_k.nodes:
        if n.kind == "contract" and n.depth == 1:
            n.kind = "future_kind"
    _check(_ground(gr_k, sg_k, _Recorder(), bridge_query=True), "unknown_kind")


def test_the_flag_cannot_reach_the_walk_or_the_state_block_because_it_is_a_ground_kwarg():
    """P-4 + P-6, BY CONSTRUCTION AND ASSERTED ANYWAY (the S7 STOP precedent). `grounded_subgraph` has no
    such parameter, so every walk-shape number is equal before any assertion is made; and the STATE BLOCK
    is built in `answer.py` from `state/**` BEFORE `pl.ground` is called at all, in a module this lane
    does not import and does not edit -- `planner` has no import of `leviathan.graphrag.state` anywhere."""
    assert "bridge_query" not in inspect.signature(pl.grounded_subgraph).parameters
    src = inspect.getsource(pl)
    assert "graphrag.state" not in src and "graphrag import state" not in src


def test_the_credit_metering_stamp_is_present_and_identical_on_both_arms():
    """P-7. `server._WALK_STAMP = 'walk_shape'` decides whether a turn is BILLED, and it is stamped in
    `grounded_subgraph`, upstream of the flag."""
    off_sg, _ = _run(bridge=False)
    on_sg, _ = _run(bridge=True)
    assert off_sg.trace["walk_shape"] and off_sg.trace["walk_shape"] == on_sg.trace["walk_shape"]


def test_n_evidence_is_bounded_by_the_cap_and_every_node_keeps_at_least_one_row():
    """P-5, THE BOUNDED HALF of what may move. Per-node row identity and order MOVE (the point), and so
    do the post-dedup kept counts -- the cross-node dedup is order-dependent and the seed claims a shared
    slice's rows first. What may NOT move is the bound: the cap still binds, and `_structural_floor`'s
    rescued row still rescues."""
    for bridge in (False, True):
        sg, _ = _run(bridge=bridge, evidence_cap=3)
        assert sg.trace["n_evidence"] <= 3
        assert sum(len(n.evidence or []) for n in sg.nodes) == sg.trace["n_evidence"]
    for bridge in (False, True):
        sg, _ = _run(bridge=bridge)
        assert all(n.evidence for n in sg.nodes if n.kind == "contract")


# ══ R-14: THE CONCURRENT RERANK DISPATCH KNOB ════════════════════════════════════════════════════════
# The bridge turns ONE query group per drain into up to one group PER NODE, and `planner._parallel_fill`
# widens its pool to MAX_FILL_POOL (64) exactly when this managed lane is live -- so a deep/max drain can
# hold 64 groups and `_fire_concurrent` dispatches them `_coalesce_group_workers()` at a time:
# ceil(64/4) = 16 sequential waves at the shipped default, ceil(64/16) = 4 at the arm's setting, against a
# 90 s `_COALESCE_MEMBER_WAIT` with one live cohere request measured at 19,900 ms. The knob is DARK by
# default -- it resolves to the HEAD constant with nothing set, so the OFF arm and every existing deck
# dispatch exactly as they did.
def _grp_entry(q: str, docs: list[str]) -> dict:
    return {"q": q, "texts": docs, "ev": threading.Event(), "scores": None, "err": None}


def test_the_group_worker_knob_defaults_to_the_head_constant_and_env_beats_params(monkeypatch):
    """THE DEFAULT, THE ORDER AND THE BOUNDS, in one place. With nothing set the resolver returns the HEAD
    constant, which is what makes this knob dark; params move it; an env value beats params; and the whole
    range is clamped to [1, 32] so a taskdef can neither serialize the lane to death nor burst past the
    native key's 1,000/min. A non-numeric value takes the CODE default -- `_COALESCE_GROUP_WORKERS`, NOT
    the params value -- rather than raising: every other serving knob in this module would `int('banana')`
    straight into a broken turn, and the one number that is always the shipped, reviewed dispatch is the
    constant. One predictable answer for any unreadable input, whatever params happens to say."""
    monkeypatch.delenv("GRAPHRAG_RERANK_GROUP_WORKERS", raising=False)
    assert rk._coalesce_group_workers() == rk._COALESCE_GROUP_WORKERS == 4
    monkeypatch.setattr(rk._pr, "get", lambda key, default=None: 7 if "rerank_group_workers" in key else default)
    assert rk._coalesce_group_workers() == 7                       # params move it...
    monkeypatch.setenv("GRAPHRAG_RERANK_GROUP_WORKERS", "16")
    assert rk._coalesce_group_workers() == 16                      # ...and the env beats params
    for raw, want in (("1", 1), ("0", 1), ("-5", 1), ("32", 32), ("33", 32), ("999", 32),
                      ("banana", rk._COALESCE_GROUP_WORKERS), ("", 7), (" 8 ", 8)):
        monkeypatch.setenv("GRAPHRAG_RERANK_GROUP_WORKERS", raw)
        assert rk._coalesce_group_workers() == want, raw


def test_widening_the_group_dispatch_changes_no_output_row(monkeypatch):
    """4 -> 16 CHANGES WHEN REQUESTS ARE MADE, NEVER WHAT COMES BACK. Driven through the REAL `_fire` on a
    private coalescer with a stubbed vendor leaf: 16 distinct query groups, dispatched at both widths.
    Every caller's score slice is identical, the request CONTENTS are identical as a multiset, and the
    observed in-flight peak really did move -- so this is a pin of invariance under a knob that demonstrably
    did something, not a pin of a no-op."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")

    def _drive(width: int):
        monkeypatch.setenv("GRAPHRAG_RERANK_GROUP_WORKERS", str(width))
        coal = rk._RerankCoalescer()
        live, peak, seen, lock = [], [0], [], threading.Lock()

        def _fake(q, docs):
            with lock:
                live.append(1)
                peak[0] = max(peak[0], len(live))
                seen.append((q, tuple(docs)))
            time.sleep(0.1)
            with lock:
                live.pop()
            return [float(len(q) * 100 + i) for i in range(len(docs))]

        monkeypatch.setattr(rk, "_cohere_rerank_call", _fake)
        entries = [_grp_entry(f"query number {i}", [f"doc {i}.{j}" for j in range(3)]) for i in range(16)]
        coal._fire(entries)
        assert [e["err"] for e in entries] == [None] * 16
        return [e["scores"] for e in entries], sorted(seen), peak[0]

    s4, req4, peak4 = _drive(4)
    s16, req16, peak16 = _drive(16)
    assert s4 == s16                                               # the rows do not move
    assert req4 == req16                                           # nor do the requests' contents
    assert 1 < peak4 <= 4 < peak16 <= 16                           # and the width really was the width


def test_the_trace_key_is_unregistered_so_another_lanes_tail_pin_is_untouched():
    """SURPRISE 5 / I-7. `tests/unit/test_cascade_walk.py` pins the registry's TAIL, and an UNREGISTERED
    `sg.trace` key is sufficient for everything this lane needs: `answer._answer_l2` spreads `sg.trace`
    wholesale into the result, so it reaches the serving result, the SSE and the $0 harness.

    LANE F, 2026-09-17 -- THE COLUMN LANDED AND THIS PIN DID NOT MOVE, WHICH IS THE POINT. The original
    docstring said "the eval COLUMN, if ever wanted, is a later commit that moves the `[-1]` pin with
    it". It was wanted (BRIDGE_VERDICT.md: the 09-16 in-VPC smoke lit the flag on all five turns and no
    artefact carried one number about it), and the column was built on the `numbers_budget`
    ABSENT-WHEN-OFF SPLAT instead of on the registry -- so this key is still unregistered, an OFF row
    still has no `bridge_query` key at all, and registering it would still have put a permanent
    `"bridge_query": null` column on every control row of every deck forever. The `[-1]` ANCHOR moved
    for other commits in the same sitting (the cost census appended three keys and lane E's writer
    seam a fourth), so the tail is
    asserted here by NAME rather than by index: what this test defends is the ABSENCE, not the
    neighbour.

    ROUND-2 REVIEW m5 -- AND NOW IT REALLY IS. The sentence above said "by NAME rather than by index"
    and the line beneath it was `TRACE_RECORD_KEYS[-1] == "writer_seam"`: a NEW negative-index tail pin
    in the one file whose stated remedy was to stop keeping one, which the NEXT append would red
    exactly as the last append red the seven files before it. The three assertions below are what this
    test means -- the ABSENCE of `bridge_query`, and the presence of the two keys that DID land -- and
    no append, anywhere, can move any of them."""
    from leviathan.graphrag import tracekeys
    assert "bridge_query" not in tracekeys.TRACE_RECORD_KEYS
    assert "writer_seam" in tracekeys.TRACE_RECORD_KEYS            # lane E's key DID land, by NAME
    assert "state_board" in tracekeys.TRACE_RECORD_KEYS            # ...and the old anchor is still there
    sg, _ = _run(bridge=True)
    assert "bridge_query" in sg.trace                              # and it is on the trace regardless


def test_the_stamp_reaches_the_per_answer_record_on_the_on_arm_and_the_off_row_is_unchanged():
    """LANE F (2026-09-17) -- THE RECEIPT THE ARM READS, AND THE BYTE-IDENTITY PIN BESIDE IT.

    THE DEFECT (BRIDGE_VERDICT.md, measured on the 2026-09-16 in-VPC pre-arm smoke): every submit
    logged `5 of 5 declared treatment flag(s) lit` including `GRAPHRAG_BRIDGE_QUERY=on`, the bridge
    PROVABLY ran on the deep turn (a 2,405 ms fill cannot contain 6,999 ms of rerank latency at the
    concurrency ONE query string permits), and `'bridge_query' in row` was False on 5 of 5 baseline
    rows -- no `applied`, no `distinct`, no `fallback` breakdown, and no way to tell whether one of the
    max turn's twenty depth-2 drivers was bridged at all.

    THE SECOND HALF IS THE ASSERTION THAT WOULD HAVE FAILED UNDER REGISTRATION, and it is the whole
    reason the splat was chosen: a registered key emits `None`, a splat emits nothing."""
    from leviathan.graphrag import eval as ev_mod
    stamp = {"nodes": 31, "applied": 29, "distinct": 27, "fallback": {"empty_mechanism": 2}}
    on = ev_mod._per_answer_record({"q": {"id": "x"}, "out": {"trace": {"bridge_query": stamp}}}, "single")
    assert on["bridge_query"] == stamp
    off = ev_mod._per_answer_record({"q": {"id": "x"}, "out": {"trace": {}}}, "single")
    assert "bridge_query" not in off                               # ABSENT, not None -- the byte pin
    assert "bridge_query" not in ev_mod._per_answer_record({"q": {"id": "x"}, "out": {}}, "single")


def test_the_state_report_prints_one_bridge_line_and_a_deck_with_no_stamp_prints_nothing():
    """LANE F (2026-09-17). ABSENT IS NEVER ZERO, in the panel too: a deck where no turn stamped the key
    renders NO bridge line, because "0 bridged nodes" and "the flag was off" are different facts and
    only one of them is a result. `fallback` is merged BY REASON rather than summed -- the reasons are a
    closed set and one total would hide a lane-parity failure (`rerank_lane_bedrock`) inside a data gap
    (`empty_mechanism`)."""
    from leviathan.graphrag import eval as ev_mod
    rows = [{"out": {"trace": {"bridge_query": {"nodes": 31, "applied": 29, "distinct": 27,
                                                "fallback": {"empty_mechanism": 2}}}}},
            {"out": {"trace": {"bridge_query": {"nodes": 51, "applied": 51, "distinct": 44,
                                                "fallback": {}}}}}]
    L = ev_mod.state_report(rows)
    bl = [x for x in L if "BRIDGE QUERY" in x]
    assert len(bl) == 1
    assert "non-seed retrieving nodes 82" in bl[0] and "BRIDGED 80" in bl[0]
    assert "distinct admitting texts 71" in bl[0] and "empty_mechanism" in bl[0]
    assert "over 2 of 2 turn(s)" in bl[0]
    # a deck with a bridge and NO board takes a header that does not promise a board line (ruling R5)
    assert L[0].startswith("## Bridge query")
    assert not any("board turns" in x for x in L)
    # NO STAMP ANYWHERE -> the panel does not exist at all, so a banked flag-off report is HEAD's
    assert ev_mod.state_report([{"out": {"trace": {}}}, {"out": {}}]) == []
    # ...and a turn that fell back on EVERY node still prints, with the reasons named
    only = [x for x in ev_mod.state_report([{"out": {"trace": {"bridge_query": {
        "nodes": 4, "applied": 0, "distinct": 0,
        "fallback": {"no_driver_mechanism": 3, "rerank_lane_bedrock": 1}}}}}]) if "BRIDGED" in x]
    assert len(only) == 1
    assert "BRIDGED 0 (0%)" in only[0] and "rerank_lane_bedrock" in only[0]
    # a turn that bridged EVERY node says so in words rather than printing an empty fallback dict
    _all = [x for x in ev_mod.state_report([{"out": {"trace": {"bridge_query": {
        "nodes": 9, "applied": 9, "distinct": 9, "fallback": {}}}}}]) if "BRIDGED" in x]
    assert "NO fallback on any turn" in _all[0] and "BRIDGED 9 (100%)" in _all[0]
