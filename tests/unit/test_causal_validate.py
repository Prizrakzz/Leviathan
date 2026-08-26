"""Causal-ontology validator — pure tests (mocked reference surfaces, no network)."""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.causal import validate as cv

NODES = {"arabica_coffee", "robusta_coffee", "soybeans"}
EDGES = {"causes", "affects_yield_of", "substitutes_for"}
SILVER = {"frost_risk", "oni_la_nina_brazil_flag", "price"}


def _d(id, **o):
    return cs.Driver(id=id, type=o.pop("type", "hazard"), sign=o.pop("sign", "+"),
                     mechanism=o.pop("mechanism", "m"), **o)


def _c(**o):
    return cs.CausalContract(contract="arabica_coffee", **o)


def test_cycle_detection():
    a = _d("a", parents=["b"]); b = _d("b", parents=["a"])
    assert cv._cycle_node([a, b]) in {"a", "b"}
    assert cv._cycle_node([_d("a"), _d("b", parents=["a"])]) is None    # DAG, no cycle


def test_check_hard_errors():
    c = _c(drivers=[_d("a", parents=["b"]), _d("b", parents=["a"])],
           inter_commodity=[cs.InterCommodityEdge(driver_commodity="ghost", relation="substitutes_for", sign="-")])
    errs, _ = cv.check(c, nodes=NODES, edges=EDGES, silver=SILVER)
    assert any("cycle" in e for e in errs)
    assert any("non-node 'ghost'" in e for e in errs)


def test_check_soft_warnings():
    c = _c(drivers=[_d("frost", silver_ref="frost_risk", silver_status="available"),         # ok
                    _d("x", silver_ref="not_built_yet", silver_status="available")])          # should warn
    errs, warns = cv.check(c, nodes=NODES, edges=EDGES, silver=SILVER)
    assert errs == []                                                  # no hard errors
    assert any("not_built_yet" in w and "planned" in w for w in warns)
    assert any("no convergence" in w for w in warns)


def test_coverage_and_report():
    c = _c(drivers=[_d("la_nina", silver_status="available", silver_ref="oni_la_nina_brazil_flag"),
                    _d("frost", parents=["la_nina"], silver_status="planned", silver_ref="vietnam_robusta_stock_z")],
           convergence=[cs.ConvergenceSignal(name="s", direction="+", requires_any_n_of=1, drivers=["frost"])])
    cov = cv.coverage(c)
    assert cov == {"drivers": 2, "fan_out_roots": 1, "fan_in": 1, "inter_commodity": 0,
                   "convergence": 1, "silver": {"available": 1, "planned": 1},
                   "planned_features": ["vietnam_robusta_stock_z"]}
    rep = cv.report(c)
    # the label retired "MLOps roadmap" on 2026-08-27 (owner word: that layer is never coming);
    # a planned ref is an unserved INSTRUMENT whose discharge is a cascade row or a new source.
    assert "planned instruments (unserved refs)" in rep and "vietnam_robusta_stock_z" in rep


def test_coverage_dedups_shared_planned_feature():
    # two planned drivers wired to ONE target feature (e.g. biennial on/off) → listed once, order preserved
    c = _c(drivers=[_d("biennial_off", silver_status="planned", silver_ref="biennial_bearing_flag"),
                    _d("excess_rain", silver_status="planned", silver_ref="excess_rain_z"),
                    _d("biennial_on", sign="-", silver_status="planned", silver_ref="biennial_bearing_flag")])
    assert cv.coverage(c)["planned_features"] == ["biennial_bearing_flag", "excess_rain_z"]


def test_canon_target_resolves_plural_and_contract_ids():
    targets = {"soybeans", "corn", "corn_cbot", "palm_oil"}
    idx = cv.canon_index(targets)
    assert cv.canon_target("soybeans", targets, idx) == "soybeans"        # exact
    assert cv.canon_target("soybean", targets, idx) == "soybeans"         # singular -> plural
    assert cv.canon_target("soybean_cbot", targets, idx) == "corn_cbot" or \
           cv.canon_target("corn_cbot", targets, idx) == "corn_cbot"      # contract id accepted as-is
    assert cv.canon_target("Soybeans", targets, idx) == "soybeans"        # case/accent-insensitive
    assert cv.canon_target("apple_juice", targets, idx) is None           # genuinely untracked


def test_intercommodity_targets_includes_contracts_and_members(monkeypatch):
    monkeypatch.setattr(cv, "_vocab_nodes_edges", lambda: ({"arabica_coffee"}, set()))
    h = {"contracts": {"corn_cbot": {"node": "corn"}, "soybean_oil_cbot": {"node": "soybean_oil"}},
         "complexes": {"veg_oil_complex": ["soybean_oil", "palm_oil", "sunflower_oil"]},
         "context_commodities": ["fish_meal"]}
    t = cv.intercommodity_targets(h)
    assert {"arabica_coffee", "corn_cbot", "corn", "soybean_oil_cbot", "soybean_oil",
            "palm_oil", "sunflower_oil", "fish_meal"} <= t


def test_check_flags_duplicate_intercommodity_and_convergence():
    c = _c(drivers=[_d("a")],
           inter_commodity=[cs.InterCommodityEdge(driver_commodity="robusta_coffee", relation="substitutes_for", sign="-"),
                            cs.InterCommodityEdge(driver_commodity="robusta_coffee", relation="substitutes_for", sign="+")],
           convergence=[cs.ConvergenceSignal(name="dup", direction="+", requires_any_n_of=1, drivers=["a"]),
                        cs.ConvergenceSignal(name="dup", direction="-", requires_any_n_of=1, drivers=["a"])])
    errs, _ = cv.check(c, nodes=NODES, edges=EDGES, silver=SILVER)
    assert any("duplicate inter_commodity" in e for e in errs)
    assert any("duplicate convergence" in e for e in errs)


def test_check_accepts_contract_id_inter_edge():
    # a cross-contract relative-value edge (soybeans -> corn_cbot) must NOT be flagged a non-node
    targets = {"arabica_coffee", "corn_cbot", "soybeans"}
    c = _c(inter_commodity=[cs.InterCommodityEdge(driver_commodity="corn_cbot", relation="competes_with", sign="-")])
    errs, _ = cv.check(c, nodes=targets, edges=EDGES, silver=SILVER)
    assert not any("non-node" in e for e in errs)
