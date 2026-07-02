"""L2 grounded-subgraph walk (WS-1) — pure traversal, fake embed, no S3/Athena/LLM.

The point of these tests: the WALK is deterministic and auditable. We watch it keep the query-relevant hops
(seed -> driver fan-in -> tracked cross-commodity neighbour), prune the irrelevant ones by the TAU gate, respect
depth + node_budget, and emit a valid cascade mermaid from the graph itself.
"""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import graph as g
from leviathan.graphrag import planner as pl

# fake bge: a text -> multi-hot over these keywords; cosine = keyword overlap (deterministic, no model).
_KW = ["frost", "substitute", "drought", "rain", "climate", "el", "nino", "damage", "demand"]


def _embed(texts):
    return [[1.0 if kw in t.lower() else 0.0 for kw in _KW] for t in texts]


def _d(id, mech, **o):
    return cs.Driver(id=id, type=o.pop("type", "hazard"), sign=o.pop("sign", "+"), mechanism=mech, **o)


def _graph() -> g.CausalGraph:
    arabica = cs.CausalContract(
        contract="arabica", aliases=["arabica"],
        drivers=[_d("el_nino", "el nino frost", type="climate_driver"),
                 _d("frost", "frost damage", parents=["el_nino"], silver_ref="frost_z", silver_status="available"),
                 _d("rain", "rain only", sign="-", type="climate_driver")],
        convergence=[cs.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=1,
                                          drivers=["frost", "el_nino"])],
        inter_commodity=[cs.InterCommodityEdge(driver_commodity="robusta", relation="substitutes_for",
                                               sign="-", mechanism="substitute demand")])
    robusta = cs.CausalContract(contract="robusta", drivers=[_d("drought", "drought")])
    return g.CausalGraph({"arabica": arabica, "robusta": robusta}, silver=set())


def _retrieve(query, slice_, *, k, asof=None, near=None):
    props = {
        "drivers/frost": [{"date": "2021-07-20", "source": "GAIN", "source_key": "s3://f", "text": "July frost hit"}],
        "drivers/el_nino": [{"date": "2015-11-01", "source": "NOAA", "source_key": "s3://e", "text": "El Nino strong"}],
        "arabica": [{"date": "2021-07-25", "source": "WASDE", "source_key": "s3://a", "text": "arabica stocks"}],
        "robusta": [{"date": "2021-07-25", "source": "WASDE", "source_key": "s3://r", "text": "robusta note"}],
    }
    return props.get(slice_, [])[:k]


def _silver(contract, driver_id, asof):
    return {"ref": "frost_z", "value": 2.1, "unit": "z", "knowledge_date": "2021-07-01", "live": True}


def _run(**kw):
    gr = _graph()
    return gr, pl.grounded_subgraph("frost substitute", gr, embed=_embed,
                                    route_fn=lambda q, graph: ["arabica"], **kw)


def _keys(sg):
    return {n.key for n in sg.nodes}


def test_walk_keeps_relevant_prunes_irrelevant():
    _, sg = _run(tau=0.35, depth=2)
    assert _keys(sg) == {("contract", "arabica", "arabica"), ("driver", "arabica", "frost"),
                         ("driver", "arabica", "el_nino"), ("contract", "robusta", "robusta")}
    pruned = {tuple(p["key"]) for p in sg.trace["pruned"]}
    assert ("driver", "arabica", "rain") in pruned            # irrelevant driver gated out
    assert ("driver", "robusta", "drought") in pruned         # irrelevant NEIGHBOUR driver gated out at depth 2
    assert sg.seeds == ["arabica"]


def test_cross_commodity_hop_is_taken():
    _, sg = _run(tau=0.35, depth=2)
    rob = next(n for n in sg.nodes if n.key == ("contract", "robusta", "robusta"))
    assert rob.depth == 1 and rob.via_edge["relation"] == "substitutes_for"   # reached via the substitution edge


def test_cross_hop_not_starved_by_driver_breadth():
    # tight budget + tau=0 (all drivers relevant): the tracked cross-commodity hop must still be reached,
    # because hops get frontier priority over a contract's own driver fan-in (L2's headline feature).
    _, sg = _run(tau=0.0, depth=2, node_budget=2)
    assert ("contract", "robusta", "robusta") in _keys(sg)


def test_depth_cap_blocks_second_hop_neighbour_drivers():
    _, sg = _run(tau=0.35, depth=1)                            # robusta kept (d1) but its drivers never expanded
    assert ("contract", "robusta", "robusta") in _keys(sg)
    assert not any(n.contract == "robusta" and n.kind == "driver" for n in sg.nodes)


def test_node_budget_caps_kept():
    _, sg = _run(tau=0.0, depth=2, node_budget=2)              # tau=0 keeps everything -> budget is the only limit
    assert len(sg.nodes) == 2


def test_prior_leg_filled_from_dag():
    _, sg = _run(tau=0.35, depth=2)
    frost = next(n for n in sg.nodes if n.id == "frost")
    assert frost.prior["sign"] == "+" and frost.prior["mechanism"] == "frost damage"
    assert frost.relevance >= 0.35 and frost.evidence == [] and frost.silver is None   # I/O legs not filled yet (WS-1)


def test_mermaid_is_valid_and_from_graph():
    _, sg = _run(tau=0.35, depth=2)
    assert sg.mermaid.startswith("flowchart LR") and an._valid_mermaid(sg.mermaid)
    assert "-->" in sg.mermaid and "frost +" in sg.mermaid                     # driver label w/ its sign
    assert "substitutes_for" in sg.mermaid                                     # the cross-commodity hop edge


def test_ground_fires_convergence_from_active_drivers():
    gr, sg = _run(tau=0.35, depth=2)
    pl.ground(sg, "frost substitute", gr, retrieve=_retrieve, silver_lookup=_silver,
              driver_slices={"frost", "el_nino", "drought"})
    frost = next(n for n in sg.nodes if n.id == "frost")
    assert frost.active and frost.evidence and frost.evidence[0]["source"] == "GAIN"   # active = has dated evidence
    fired = {(r["contract"], r["name"]) for r in sg.fired_regimes}
    assert ("arabica", "squeeze") in fired                                     # regime fires deterministically


def test_ground_silver_leg_via_injected_lookup():
    gr, sg = _run(tau=0.35, depth=2)
    pl.ground(sg, "q", gr, retrieve=_retrieve, silver_lookup=_silver, driver_slices={"frost", "el_nino", "drought"})
    frost = next(n for n in sg.nodes if n.id == "frost")
    el = next(n for n in sg.nodes if n.id == "el_nino")
    assert frost.silver["value"] == 2.1 and frost.silver["live"]               # driver w/ silver_ref gets grounded
    assert el.silver is None                                                    # no silver_ref -> skipped, not invented


def test_ground_dedups_and_caps_evidence():
    gr, sg = _run(tau=0.35, depth=2)
    pl.ground(sg, "q", gr, retrieve=_retrieve, silver_lookup=None, evidence_cap=2,
              driver_slices={"frost", "el_nino", "drought"})
    assert sg.trace["n_evidence"] == 2                                          # 4 props retrieved, capped to 2


def test_edge_category_map():
    assert pl.edge_category("crushed_into") == "transformation"      # accounting identity
    assert pl.edge_category("substitutes_for") == "market_structure"
    assert pl.edge_category("causes") == "causal" and pl.edge_category("") == "causal"


def test_ground_skips_unbacked_drivers_no_empty_fetch():
    gr, sg = _run(tau=0.0, depth=2, node_budget=10)                  # keeps rain too
    fetched = []

    def spy_retrieve(q, slice_, *, k, asof=None, near=None):
        fetched.append(slice_)
        return _retrieve(q, slice_, k=k)
    pl.ground(sg, "q", gr, retrieve=spy_retrieve, silver_lookup=None, driver_slices={"frost", "el_nino"})
    assert "drivers/rain" not in fetched                             # unbacked driver -> prior-only, no fetch
    assert "drivers/frost" in fetched


def test_active_via_contract_evidence_mention():
    # a driver with NO slice still counts ACTIVE when the contract's own evidence names it (v1 fired 0 regimes)
    gr, sg = _run(tau=0.0, depth=1, node_budget=10)

    def retrieve(q, slice_, *, k, asof=None, near=None):
        if slice_ == "arabica":
            return [{"date": "2021-07-25", "source": "WASDE", "source_key": "s3://a",
                     "text": "persistent rain damaged cherries; el nino pattern building"}]
        return []
    pl.ground(sg, "q", gr, retrieve=retrieve, silver_lookup=None, driver_slices={"frost"})
    rain = next(n for n in sg.nodes if n.id == "rain")
    el = next(n for n in sg.nodes if n.id == "el_nino")
    assert rain.active and el.active                                 # named in contract evidence -> active
    assert ("arabica", "squeeze") in {(r["contract"], r["name"]) for r in sg.fired_regimes}
