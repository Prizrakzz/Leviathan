"""graphdev — in-memory causal graph primitives (pure, no network/spend)."""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g


def _d(id, **o):
    return cs.Driver(id=id, type=o.pop("type", "hazard"), sign=o.pop("sign", "+"),
                     mechanism=o.pop("mechanism", "m"), **o)


def _coffee() -> cs.CausalContract:
    # cascade: la_nina -> {drought, frost} -> stocks ; biennial is an isolated root
    drivers = [
        _d("la_nina", type="climate_driver"),
        _d("drought", parents=["la_nina"], silver_ref="drought_z", silver_status="available"),
        _d("frost", parents=["la_nina"], silver_ref="frost_event_flag", silver_status="available"),
        _d("stocks", parents=["drought", "frost"], silver_ref="stock", silver_status="available"),
        _d("biennial", silver_ref="biennial_bearing_flag", silver_status="planned"),   # reserved, NOT in registry
    ]
    conv = [cs.ConvergenceSignal(
        name="squeeze", direction="+", requires_any_n_of=2, drivers=["drought", "frost", "stocks"],
        interactions=[cs.Interaction(when=["drought", "frost"], effect="amplifies", note="x"),
                      cs.Interaction(when=["la_nina", "frost"], effect="amplifies", note="y")])]
    inter = [cs.InterCommodityEdge(driver_commodity="robusta_coffee", relation="substitutes_for", sign="-"),
             cs.InterCommodityEdge(driver_commodity="crude_oil_untracked", relation="feedstock_for", sign="+")]
    return cs.CausalContract(contract="arabica_coffee", drivers=drivers, convergence=conv, inter_commodity=inter)


SILVER = {"drought_z", "frost_event_flag", "stock", "price"}   # biennial_bearing_flag absent -> planned, not live


def _graph() -> g.CausalGraph:
    return g.CausalGraph({"arabica_coffee": _coffee(),
                          "robusta_coffee": cs.CausalContract(contract="robusta_coffee", drivers=[_d("viet_dry")])},
                         silver=SILVER)


def test_cascade_ancestors_descendants_roots():
    gr = _graph()
    assert gr.ancestors("arabica_coffee", "stocks") == ["drought", "frost", "la_nina"]   # transitive upstream
    assert gr.descendants("arabica_coffee", "la_nina") == ["drought", "frost", "stocks"]  # transitive downstream
    assert gr.ancestors("arabica_coffee", "la_nina") == []                               # a root has no causes
    assert sorted(gr.roots("arabica_coffee")) == ["biennial", "la_nina"]


def test_regimes_fire_on_threshold_and_interactions():
    gr = _graph()
    none = gr.regimes("arabica_coffee", {"drought"})                  # 1 of 2 -> no fire
    assert none == []
    fired = gr.regimes("arabica_coffee", {"drought", "frost"})        # 2 of 2 -> fire
    assert len(fired) == 1 and fired[0].name == "squeeze" and fired[0].matched == ["drought", "frost"]
    assert len(fired[0].interactions) == 1                            # only drought+frost active (not la_nina+frost)
    fired2 = gr.regimes("arabica_coffee", {"drought", "frost", "la_nina"})
    assert len(fired2[0].interactions) == 2                           # now la_nina+frost also fires
    assert fired2[0].matched == ["drought", "frost"]                  # la_nina is not in the regime's driver set


def test_cross_links_tracked_flag():
    cl = {e["driver_commodity"]: e for e in _graph().cross_links("arabica_coffee")}
    assert cl["robusta_coffee"]["tracked"] is True                   # a loaded contract -> a real hop
    assert cl["crude_oil_untracked"]["tracked"] is False             # not loaded -> context only
    assert cl["robusta_coffee"]["sign"] == "-"


def test_silver_resolution_decoupled_from_mlops():
    gr = _graph()
    assert gr.silver_status("arabica_coffee", "drought") == {"silver_ref": "drought_z",
                                                             "declared": "available", "live": True}
    biennial = gr.silver_status("arabica_coffee", "biennial")
    assert biennial["declared"] == "planned" and biennial["live"] is False   # reserved name, feature not built
    s = gr.silver_summary("arabica_coffee")
    assert s["drivers"] == 5 and s["live"] == 3 and s["planned"] == 1
    assert s["live_ids"] == ["drought", "frost", "stocks"]


def test_to_edge_list_flattens_three_edge_kinds():
    rows = _graph().to_edge_list()
    _COLS = {"source", "source_kind", "edge_type", "target", "target_metric", "sign", "lag",
             "mechanism", "confidence", "silver_ref", "silver_status"}
    assert all(set(r) == _COLS for r in rows)                             # uniform schema
    dt = [r for r in rows if r["source"] == "drought" and r["target"] == "arabica_coffee"]
    assert len(dt) == 1 and dt[0]["edge_type"] == "causes" and dt[0]["sign"] == "+" \
        and dt[0]["target_metric"] == "price" and dt[0]["silver_status"] == "available"   # driver -> target
    pd = [r for r in rows if r["source"] == "la_nina" and r["target"] == "drought"]
    assert len(pd) == 1 and pd[0]["edge_type"] == "drives" and pd[0]["sign"] is None       # parent -> driver, no invented sign
    ic = [r for r in rows if r["source"] == "arabica_coffee" and r["target"] == "robusta_coffee"]
    assert len(ic) == 1 and ic[0]["edge_type"] == "substitutes_for" and ic[0]["sign"] == "-"  # inter-commodity hop


def test_edge_list_honours_target_metric_override():
    c = cs.CausalContract(contract="x", drivers=[_d("yld", sign="-", target_metric="yield")])
    rows = g.CausalGraph({"x": c}, silver=set()).to_edge_list()
    assert rows[0]["target"] == "x" and rows[0]["target_metric"] == "yield" and rows[0]["sign"] == "-"


def test_load_contracts_smoke():
    contracts = g.load_contracts()                                   # real configs/graphrag/causal/*.yaml if present
    for c in contracts.values():
        assert c.driver_ids()
    if "arabica_coffee" in contracts:                                # tolerant: gitignored YAMLs may be absent in CI
        assert g.CausalGraph(contracts).silver_summary("arabica_coffee")["drivers"] > 0


def test_causal_graph_version_stable_and_content_sensitive(tmp_path):
    a = tmp_path / "a.yaml"; b = tmp_path / "b.yaml"
    a.write_text("contract: x\ndrivers: []\n", encoding="utf-8")
    b.write_text("contract: y\ndrivers: []\n", encoding="utf-8")
    paths = [a, b]
    v1 = g.causal_graph_version(paths)
    v2 = g.causal_graph_version(list(reversed(paths)))               # order-independent (sorted internally)
    assert v1 == v2 and len(v1) == 12 and all(c in "0123456789abcdef" for c in v1)
    a.write_text("contract: x\ndrivers: []\n# edited\n", encoding="utf-8")
    assert g.causal_graph_version(paths) != v1                       # a content edit changes the hash
    assert g.causal_graph_version([tmp_path / "missing.yaml"]) == "nograph"


def test_load_stamps_version_and_init_accepts_override():
    gr = g.CausalGraph.load()                                        # real YAMLs locally; empty->'nograph' in CI
    assert isinstance(gr.version, str) and gr.version               # a non-empty identity either way
    gr2 = g.CausalGraph({"x": cs.CausalContract(contract="x", drivers=[_d("d")])}, silver=set(), version="test")
    assert gr2.version == "test"                                     # synthetic graphs pass their own id
