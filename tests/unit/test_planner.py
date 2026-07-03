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
    # frost evidence is dated 2021-07-20; with asof 2021-08-01 it is WITHIN the recency window -> fires,
    # and the firing carries a per-driver receipt {date, source} (the epistemic basis the block renders).
    gr, sg = _run(tau=0.35, depth=2)
    pl.ground(sg, "frost substitute", gr, retrieve=_retrieve, silver_lookup=_silver, asof="2021-08-01",
              driver_slices={"frost", "el_nino", "drought"})
    frost = next(n for n in sg.nodes if n.id == "frost")
    assert frost.active and frost.evidence and frost.evidence[0]["source"] == "GAIN"   # active = has dated evidence
    fired = {(r["contract"], r["name"]) for r in sg.fired_regimes}
    assert ("arabica", "squeeze") in fired                                     # regime fires deterministically
    r = next(r for r in sg.fired_regimes if r["name"] == "squeeze")
    assert r["basis"]["frost"] == {"date": "2021-07-20", "source": "GAIN"}     # receipt rides with the firing


def test_no_asof_means_no_firing():
    # nothing anchors "now": regime definitions stay structure, never state — zero probes, zero firings.
    gr, sg = _run(tau=0.35, depth=2)
    seen = []

    def spy(q, slice_, *, k, asof=None, near=None):
        seen.append(slice_)
        return _retrieve(q, slice_, k=k)
    pl.ground(sg, "frost substitute", gr, retrieve=spy, silver_lookup=None,
              driver_slices={"frost", "el_nino", "drought"})
    assert sg.fired_regimes == [] and sg.trace["n_probes"] == 0


def test_recency_window_blocks_stale_evidence():
    # el_nino evidence is dated 2015-11-01; at asof 2021-08-01 that is ~6 years stale -> may not fire a
    # regime, even though the prop passes the plain asof guard (this was the July-3 over-firing bug).
    gr, sg = _run(tau=0.35, depth=2)

    def only_old(q, slice_, *, k, asof=None, near=None):
        return _retrieve(q, slice_, k=k) if slice_ == "drivers/el_nino" else []
    pl.ground(sg, "frost substitute", gr, retrieve=only_old, silver_lookup=None, asof="2021-08-01",
              driver_slices={"frost", "el_nino", "drought"})
    assert sg.fired_regimes == []                                   # stale mention is not a documented condition
    pl.ground(sg, "frost substitute", gr, retrieve=only_old, silver_lookup=None, asof="2016-03-01",
              driver_slices={"frost", "el_nino", "drought"})
    assert {(r["contract"], r["name"]) for r in sg.fired_regimes} == {("arabica", "squeeze")}  # near 2015 -> fires


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


def test_named_in_evidence_is_active_for_display_but_never_fires():
    # a driver merely NAME-DROPPED in the contract's evidence keeps its display `active` flag, but a
    # mention is not a documented condition — it must never fire a regime (the judge called this out:
    # "fabricates multi-regime activation from driver tags rather than dated evidence").
    gr, sg = _run(tau=0.0, depth=1, node_budget=10)

    def retrieve(q, slice_, *, k, asof=None, near=None):
        if slice_ == "arabica":
            return [{"date": "2021-07-25", "source": "WASDE", "source_key": "s3://a",
                     "text": "persistent rain damaged cherries; el nino pattern building"}]
        return []
    pl.ground(sg, "q", gr, retrieve=retrieve, silver_lookup=None, asof="2021-08-01", driver_slices={"frost"})
    rain = next(n for n in sg.nodes if n.id == "rain")
    el = next(n for n in sg.nodes if n.id == "el_nino")
    assert rain.active and el.active                                 # named in contract evidence -> display-active
    assert sg.fired_regimes == []                                    # ...but name-drops never fire a regime


# ── WS-1/2/3: regime firing decoupled from the walk + alias map + relevance ranking ──────────────────────
def _graph_with_rain_regime() -> g.CausalGraph:
    """arabica + a 'wet_glut' regime that requires ONLY 'rain' — the driver the walk prunes for a frost query.
    Firing wet_glut therefore proves the regime check is decoupled from which nodes the walk kept."""
    arabica = cs.CausalContract(
        contract="arabica", aliases=["arabica"],
        drivers=[_d("el_nino", "el nino frost", type="climate_driver"),
                 _d("frost", "frost damage", parents=["el_nino"]),
                 _d("rain", "rain only", sign="-", type="climate_driver")],
        convergence=[cs.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=1,
                                          drivers=["frost", "el_nino"]),
                     cs.ConvergenceSignal(name="wet_glut", direction="-", requires_any_n_of=1,
                                          drivers=["rain"])])
    return g.CausalGraph({"arabica": arabica}, silver=set())


def test_regime_fires_via_probe_for_non_walked_driver():
    gr = _graph_with_rain_regime()
    sg = pl.grounded_subgraph("frost substitute", gr, embed=_embed,
                              route_fn=lambda q, graph: ["arabica"], tau=0.35, depth=2)
    assert ("driver", "arabica", "rain") not in _keys(sg)           # 'rain' pruned by tau -> not a walk node

    seen = []

    def retrieve(query, slice_, *, k, asof=None, near=None):
        seen.append((slice_, asof))
        if slice_ == "drivers/rain":
            return [{"date": "2021-06-01", "source": "NOAA", "source_key": "s3://x", "text": "heavy rain"}]
        return []
    pl.ground(sg, "q", gr, retrieve=retrieve, silver_lookup=None, asof="2021-08-01",
              driver_slices={"frost", "el_nino", "rain"})
    fired = {(r["contract"], r["name"]) for r in sg.fired_regimes}
    assert ("arabica", "wet_glut") in fired                         # fired from a driver OUTSIDE the subgraph
    assert ("drivers/rain", "2021-08-01") in seen                   # the probe honored the point-in-time asof
    assert sg.trace["n_probes"] >= 1 and "rain" in sg.trace["regime_basis"]["arabica"]


def test_probe_cap_bounds_slice_probes():
    gr = _graph_with_rain_regime()
    sg = pl.grounded_subgraph("frost substitute", gr, embed=_embed,
                              route_fn=lambda q, graph: ["arabica"], tau=0.35, depth=2)

    def retrieve(query, slice_, *, k, asof=None, near=None):
        if slice_ == "drivers/rain":
            return [{"date": "2021-06-01", "source": "NOAA", "source_key": "s3://x", "text": "heavy rain"}]
        return []
    pl.ground(sg, "q", gr, retrieve=retrieve, silver_lookup=None, asof="2021-08-01", probe_cap=0,
              driver_slices={"frost", "el_nino", "rain"})
    fired = {(r["contract"], r["name"]) for r in sg.fired_regimes}
    assert ("arabica", "wet_glut") not in fired                     # cap 0 -> rain never probed -> cannot fire
    assert sg.trace["n_probes"] == 0


def test_walk_selects_by_relevance_not_yaml_order():
    # arabica lists drivers [el_nino, frost, rain]; for "frost substitute", frost (rel .5) > el_nino (.41).
    # FIFO/YAML order would keep el_nino first; ranked selection keeps FROST under a tight budget.
    gr = _graph()
    sg = pl.grounded_subgraph("frost substitute", gr, embed=_embed,
                              route_fn=lambda q, graph: ["arabica"], tau=0.35, depth=2, node_budget=3)
    keys = _keys(sg)
    assert ("driver", "arabica", "frost") in keys                   # higher-relevance driver won the slot
    assert ("driver", "arabica", "el_nino") not in keys             # lower-relevance driver budget-pruned
    budget_pruned = {tuple(p["key"]) for p in sg.trace["pruned"] if p.get("reason") == "budget"}
    assert ("driver", "arabica", "el_nino") in budget_pruned


def test_alias_map_resolves_dag_ids_to_slices():
    from leviathan.graphrag import evidence as ev
    assert ev.slice_for_driver("heat_stress") == "heat"                     # curated alias
    assert ev.slice_for_driver("ending_stocks_su_ratio") == "wasde_stocks_to_use"
    assert ev.slice_for_driver("cot_mm_positioning") == "cftc_positioning"
    assert ev.slice_for_driver("El_Nino") == "el_nino"                      # case-mismatch alias
    assert ev.slice_for_driver("drought") == "drought"                      # exact-name identity
    assert ev.slice_for_driver("conab_production_revision") is None         # honestly dark (no topical slice)
    backed = ev.backed_dag_ids()
    assert {"heat_stress", "ending_stocks_su_ratio", "El_Nino"} <= backed


def test_l2_block_renders_receipts_never_fired_language():
    from leviathan.graphrag import answer as an
    gr, sg = _run(tau=0.35, depth=2)
    pl.ground(sg, "frost substitute", gr, retrieve=_retrieve, silver_lookup=None, asof="2021-08-01",
              driver_slices={"frost", "el_nino", "drought"})
    text = "\n".join(an._l2_blocks(sg, gr, asof="2021-08-01"))
    assert "CONVERGENCE CONDITIONS DOCUMENTED NEAR THE AS-OF" in text
    assert "frost (GAIN, 2021-07-20)" in text                        # the per-driver receipt, inline
    assert "CONSISTENT WITH" in text and "never describe a regime as 'fired'" in text
    assert "FIRED AT THIS AS-OF" not in text                         # the July-3 over-claim header is gone


def test_l2_block_no_asof_renders_structure_not_state():
    from leviathan.graphrag import answer as an
    gr, sg = _run(tau=0.35, depth=2)
    pl.ground(sg, "frost substitute", gr, retrieve=_retrieve, silver_lookup=None,
              driver_slices={"frost", "el_nino", "drought"})
    text = "\n".join(an._l2_blocks(sg, gr, asof=None))
    assert "not evaluated (no as-of date" in text
    assert "FIRED" not in text
