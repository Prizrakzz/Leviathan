"""Silver-only convergence firing (build-plan P1.3/P1.4) — pure, no I/O beyond the injected lookup."""
from __future__ import annotations

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import firing as fr
from leviathan.graphrag import graph as g


def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica"],
        drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="m"),
                 cs.Driver(id="drought", type="hazard", sign="+", mechanism="m"),
                 cs.Driver(id="low_stocks", type="hazard", sign="+", mechanism="m")],
        convergence=[cs.ConvergenceSignal(name="bullish_supply_squeeze", direction="+",
                                          requires_any_n_of=2, drivers=["frost", "drought", "low_stocks"])])
    return g.CausalGraph({"arabica_coffee": coffee}, silver=set())


def _lookup(observed=(), normal=()):
    def lk(contract, did, asof):
        if did in observed:
            return {"live": True, "verdict": "observed", "z": -2.1, "value": 0.09, "unit": "ratio",
                    "ref": "psd_ending_stock_su_ratio", "knowledge_date": "2021-07-10"}
        if did in normal:
            return {"live": True, "verdict": "normal", "z": 0.1, "value": 0.31, "unit": "ratio", "ref": "su"}
        return {"live": False, "ref": None}
    return lk


def test_fire_contract_fires_when_threshold_met():
    out = fr.fire_contract(_graph(), "arabica_coffee", "2021-07-20", _lookup(observed=("frost", "low_stocks")))
    reg = {r["name"]: r for r in out["regimes"]}
    assert reg["bullish_supply_squeeze"]["fired"] is True
    assert reg["bullish_supply_squeeze"]["n_active"] == 2 and reg["bullish_supply_squeeze"]["proximity"] == 1.0
    d = {x["id"]: x for x in out["drivers"]}
    assert d["frost"]["verdict"] == "observed" and d["drought"]["live"] is False        # unresolved driver -> not live


def test_fire_contract_near_but_not_fired():
    out = fr.fire_contract(_graph(), "arabica_coffee", "2021-07-20", _lookup(observed=("frost",)))
    reg = {r["name"]: r for r in out["regimes"]}
    assert reg["bullish_supply_squeeze"]["fired"] is False
    assert reg["bullish_supply_squeeze"]["proximity"] == 0.5                              # 1 of 2 required


def test_fire_contract_vetoes_normal_observed():
    # frost observed anomalous; drought + low_stocks observed NORMAL -> only frost counts, no fire
    out = fr.fire_contract(_graph(), "arabica_coffee", "2021-07-20",
                           _lookup(observed=("frost",), normal=("drought", "low_stocks")))
    reg = {r["name"]: r for r in out["regimes"]}
    assert reg["bullish_supply_squeeze"]["fired"] is False and reg["bullish_supply_squeeze"]["n_active"] == 1


def test_fired_set_matches_graph_regimes_authority():
    """Parity: fire_contract's fired set == graph.regimes() on the same OBSERVED-active drivers, so the
    heatmap never disagrees with the answer path's threshold logic."""
    gr = _graph()
    out = fr.fire_contract(gr, "arabica_coffee", "2021-07-20", _lookup(observed=("frost", "drought")))
    fired = {r["name"] for r in out["regimes"] if r["fired"]}
    authority = {x.name for x in gr.regimes("arabica_coffee", ["frost", "drought"])}
    assert fired == authority and "bullish_supply_squeeze" in fired


def test_convergence_matrix_covers_all_contracts():
    gr = _graph()
    m = fr.convergence_matrix(gr, "2021-07-20", _lookup(observed=("frost", "low_stocks")))
    assert len(m) == len(gr.contracts) and m[0]["contract"] == "arabica_coffee"


def test_unknown_contract_raises_keyerror():
    with pytest.raises(KeyError):
        fr.fire_contract(_graph(), "nope", "2021-07-20", _lookup())
