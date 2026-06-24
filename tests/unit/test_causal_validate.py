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
    assert "planned features (MLOps roadmap)" in rep and "vietnam_robusta_stock_z" in rep


def test_coverage_dedups_shared_planned_feature():
    # two planned drivers wired to ONE target feature (e.g. biennial on/off) → listed once, order preserved
    c = _c(drivers=[_d("biennial_off", silver_status="planned", silver_ref="biennial_bearing_flag"),
                    _d("excess_rain", silver_status="planned", silver_ref="excess_rain_z"),
                    _d("biennial_on", sign="-", silver_status="planned", silver_ref="biennial_bearing_flag")])
    assert cv.coverage(c)["planned_features"] == ["biennial_bearing_flag", "excess_rain_z"]
