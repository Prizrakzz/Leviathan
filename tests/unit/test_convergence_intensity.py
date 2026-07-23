"""CONVERGENCE_TIER1 T1 -- graded firing intensity (hermetic: no Athena/LLM/pg; injected qfn/lookups).

Pins: (1) the _intensity band function scaled to each ref's OWN z_thr (su_ratio 1.0 / fx 1.5) and ONI's
meteorological |anomaly| bands (NEVER sigma multiples); (2) the make_silver_lookup seam attaches the key
ONLY flag-on and ONLY on banded results ([SKEPTIC F2] -- the seam covers ONI, which never calls _verdict_z);
(3) no-z / normal / live:False results carry NO key (absent, not null); (4) _driver_row + the ground() basis
forward it present-key-only; (5) the answer receipt renders the "consistent with a <band> anomaly" clause
present-key-only; (6) the [SKEPTIC F1] serialization regression -- DriverSignal/ConvergenceRow model_dump()
bytes are BYTE-EQUAL flag-off (no "intensity":null leak), and flag-on adds the key on banded drivers only;
(7) fired/n_active/threshold/proximity are untouched by the flag (the fire decision never reads intensity).
"""
from __future__ import annotations

import json

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import api_models as M
from leviathan.graphrag import firing as fr
from leviathan.graphrag import graph as g
from leviathan.graphrag import planner as pl
from leviathan.graphrag import silverleg as slv


# -- (1) the band function ------------------------------------------------------------------------------
def test_intensity_su_ratio_scaled_to_z_thr_1():
    ref = "psd_ending_stock_su_ratio"
    assert slv._intensity(ref, 1.0, 1.0) == "moderate"            # the observed floor
    assert slv._intensity(ref, -1.9, 1.0) == "moderate"           # |z|, sign-blind
    assert slv._intensity(ref, 2.0, 1.0) == "strong"
    assert slv._intensity(ref, -2.4, 1.0) == "strong"
    assert slv._intensity(ref, 3.0, 1.0) == "extreme"
    assert slv._intensity(ref, -5.2, 1.0) == "extreme"
    assert slv._intensity(ref, 0.8, 1.0) is None                  # sub-threshold: unbanded


def test_intensity_fx_scaled_to_its_own_z_thr_1_5():
    ref = "fred_fx_macro"
    assert slv._intensity(ref, 1.6, 1.5) == "moderate"            # 1.6 < 2*1.5: NOT strong on fx's scale
    assert slv._intensity(ref, 3.1, 1.5) == "strong"              # [3.0, 4.5)
    assert slv._intensity(ref, 4.6, 1.5) == "extreme"             # >= 4.5
    assert slv._intensity(ref, 1.4, 1.5) is None


def test_intensity_oni_meteorological_bands_never_sigma():
    ref = "oni_climate"
    assert slv._intensity(ref, 0.6, 0.5) == "elevated"            # [0.5, 1.0)
    assert slv._intensity(ref, -1.2, 0.5) == "moderate"           # [1.0, 1.5)
    assert slv._intensity(ref, 1.6, 0.5) == "strong"              # [1.5, 2.0)
    assert slv._intensity(ref, -2.3, 0.5) == "extreme"            # >= 2.0
    assert slv._intensity(ref, 0.3, 0.5) is None                  # below the +-0.5 threshold
    # THE sigma trap: 1.6 is 3.2x the 0.5 threshold -- sigma-multiple banding would call it "extreme".
    # The meteorological band says "strong". Never sigma.
    assert slv._intensity(ref, 1.6, 0.5) != "extreme"


def test_intensity_degrades_on_garbage_never_raises():
    assert slv._intensity("psd_ending_stock_su_ratio", None, 1.0) is None
    assert slv._intensity("psd_ending_stock_su_ratio", "x", 1.0) is None
    assert slv._intensity("psd_ending_stock_su_ratio", 2.0, None) is None
    assert slv._intensity("psd_ending_stock_su_ratio", 2.0, 0) is None
    assert slv._intensity("oni_climate", None, 0.5) is None


# -- (2)/(3) the lookup seam: conditionally-attached, all three handlers covered ------------------------
def _graph(su_status="available"):
    c = cs.CausalContract(
        contract="corn", aliases=[],
        drivers=[cs.Driver(id="ending_stocks_su_ratio", type="fundamental", sign="-", mechanism="m",
                           silver_ref="psd_ending_stock_su_ratio", silver_status=su_status),
                 cs.Driver(id="el_nino", type="climate_driver", sign="+", mechanism="m",
                           silver_ref="oni_climate", silver_status="available"),
                 cs.Driver(id="drought", type="hazard", sign="+", mechanism="m")],
        convergence=[cs.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=2,
                                          drivers=["ending_stocks_su_ratio", "el_nino"])])
    return g.CausalGraph({"corn": c}, silver=set())


def _psd_qfn(ratios: dict):
    stocks = [{"period": p, "value": s, "knowledge_date": "2012-08-10"} for p, (s, _) in ratios.items()]
    cons = [{"period": p, "value": c, "knowledge_date": "2012-08-10"} for p, (_, c) in ratios.items()]

    def qfn(sql):
        if "ending_stocks_mt" in sql:
            return stocks
        if "consumption_mt" in sql:
            return cons
        if "oni_anom" in sql:
            return [{"value": "1.6", "data_date": "2012-07-31"}]
        return []
    return qfn


_ANOM_RATIOS = {f"20{i:02d}": (180.0 if i % 2 else 220.0, 1000.0) for i in range(3, 12)}
_ANOM_RATIOS["2012"] = (80.0, 1000.0)                             # deeply anomalous latest year


def test_lookup_flag_off_attaches_no_key_default():
    look = slv.make_silver_lookup(_graph(), _psd_qfn(_ANOM_RATIOS))
    out = look("corn", "ending_stocks_su_ratio", "2012-08-15")
    assert out["verdict"] == "observed" and "intensity" not in out
    oni = look("corn", "el_nino", "2012-08-15")
    assert oni["verdict"] == "observed" and "intensity" not in oni


def test_lookup_flag_on_bands_su_and_oni_at_the_shared_seam():
    look = slv.make_silver_lookup(_graph(), _psd_qfn(_ANOM_RATIOS), intensity=True)
    out = look("corn", "ending_stocks_su_ratio", "2012-08-15")
    assert out["verdict"] == "observed"
    assert out["intensity"] in ("moderate", "strong", "extreme")  # scaled to su_ratio's own z_thr
    # [F2]: ONI inlines its verdict (never calls _verdict_z) yet STILL gets banded -- the seam covers it.
    oni = look("corn", "el_nino", "2012-08-15")
    assert oni["intensity"] == "strong"                           # |1.6| on 0.5/1.0/1.5/2.0, never sigma
    # memo hit returns the band too (the RAW memo entry stays unbanded; _deco re-derives per return)
    assert look("corn", "el_nino", "2012-08-15")["intensity"] == "strong"


def test_lookup_no_z_and_normal_drivers_stay_unbanded_flag_on():
    look = slv.make_silver_lookup(_graph(), _psd_qfn(_ANOM_RATIOS), intensity=True)
    dead = look("corn", "drought", "2012-08-15")                  # ref-less: live False, no z (silverleg L228)
    assert dead["live"] is False and "intensity" not in dead
    normal = {f"20{i:02d}": (180.0 if i % 2 else 220.0, 1000.0) for i in range(3, 12)}
    normal["2012"] = (200.0, 1000.0)                              # at the mean: verdict normal, |z| < z_thr
    look2 = slv.make_silver_lookup(_graph(), _psd_qfn(normal), intensity=True)
    out = look2("corn", "ending_stocks_su_ratio", "2012-08-15")
    assert out["verdict"] == "normal" and "intensity" not in out


# -- (4) forwarding: _driver_row + the ground() basis, present-key-only ---------------------------------
_SV_BANDED = {"live": True, "verdict": "observed", "z": -2.4, "value": 0.08, "unit": "S/U",
              "ref": "psd_ending_stock_su_ratio", "knowledge_date": "2012-08-10", "intensity": "strong"}
_SV_PLAIN = {"live": True, "verdict": "observed", "z": -2.4, "value": 0.08, "unit": "S/U",
             "ref": "psd_ending_stock_su_ratio", "knowledge_date": "2012-08-10"}


def test_driver_row_forwards_intensity_only_when_present():
    assert fr._driver_row("d", _SV_BANDED)["intensity"] == "strong"
    assert "intensity" not in fr._driver_row("d", _SV_PLAIN)
    assert "intensity" not in fr._driver_row("d", {"live": False})


def _sg(graph):
    return pl.grounded_subgraph("corn stocks squeeze", graph, embed=lambda xs: [[1.0, 0.0] for _ in xs],
                                route_fn=lambda q, g: ["corn"])


def _dated_retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2012-07-01", "source": "usda_wasde", "source_key": "s3://x", "text": "chatter"}]


def _ground(graph, look):
    sg = _sg(graph)
    pl.ground(sg, "corn stocks squeeze", graph, retrieve=_dated_retrieve, silver_lookup=look,
              asof="2012-08-15", driver_slices={"drought"})
    return sg


def _look(sv_su, sv_oni):
    def look(cid, did, asof):
        if did == "ending_stocks_su_ratio":
            return sv_su
        if did == "el_nino":
            return sv_oni
        return {"live": False}
    return look


def test_ground_basis_carries_intensity_only_when_lookup_supplies_it():
    graph = _graph()
    oni = {"live": True, "verdict": "observed", "value": 1.6, "unit": "ONI", "z": 1.6,
           "knowledge_date": "2012-07-31", "ref": "oni_climate", "detail": ""}
    sg_on = _ground(graph, _look(_SV_BANDED, {**oni, "intensity": "strong"}))
    basis = sg_on.fired_regimes[0]["basis"]
    assert basis["ending_stocks_su_ratio"]["intensity"] == "strong"
    sg_off = _ground(graph, _look(_SV_PLAIN, oni))
    basis_off = sg_off.fired_regimes[0]["basis"]
    assert "intensity" not in basis_off["ending_stocks_su_ratio"]
    assert "intensity" not in basis_off["el_nino"]
    # the FIRE decision is identical either way -- intensity is a label, never a count input
    assert len(sg_on.fired_regimes) == len(sg_off.fired_regimes) == 1


# -- (5) the answer receipt clause (answer.py observed receipt; obeys the never-fired doctrine) ---------
def test_receipt_renders_consistent_with_clause_present_key_only():
    graph = _graph()
    oni = {"live": True, "verdict": "observed", "value": 1.6, "unit": "ONI", "z": 1.6,
           "knowledge_date": "2012-07-31", "ref": "oni_climate", "detail": ""}
    sg_on = _ground(graph, _look(_SV_BANDED, {**oni, "intensity": "strong"}))
    _stable, volatile = an._l2_blocks(sg_on, graph, asof="2012-08-15")
    text_on = "\n".join(volatile)
    assert "consistent with a strong anomaly" in text_on
    # doctrine: the block never asserts a regime fired/active/armed/confirmed as live state
    assert "never describe a regime as 'fired'" in text_on
    sg_off = _ground(graph, _look(_SV_PLAIN, oni))
    text_off = "\n".join(an._l2_blocks(sg_off, graph, asof="2012-08-15")[1])
    assert "consistent with a strong anomaly" not in text_off     # absent key -> byte-identical receipt
    assert text_on.replace(", consistent with a strong anomaly", "") == text_off


# -- (6) [SKEPTIC F1] serialization regression: BYTE-equality flag-off; additive key flag-on ------------
def test_driver_signal_model_dump_bytes_unchanged_flag_off():
    row = fr._driver_row("ending_stocks_su_ratio", _SV_PLAIN)
    dumped = M.DriverSignal(**row).model_dump()
    expected = {"id": "ending_stocks_su_ratio", "live": True, "verdict": "observed", "z": -2.4,
                "value": 0.08, "unit": "S/U", "ref": "psd_ending_stock_su_ratio",
                "knowledge_date": "2012-08-10"}
    assert json.dumps(dumped, sort_keys=True, default=str) == json.dumps(expected, sort_keys=True,
                                                                         default=str)
    assert "intensity" not in json.dumps(dumped)                  # NEVER "intensity":null


def test_convergence_row_model_dump_flag_off_vs_on():
    def look_off(cid, did, asof):
        return _SV_PLAIN if did == "ending_stocks_su_ratio" else {"live": False}

    def look_on(cid, did, asof):
        return _SV_BANDED if did == "ending_stocks_su_ratio" else {"live": False}
    graph = _graph()
    off = M.ConvergenceRow(**fr.fire_contract(graph, "corn", "2012-08-15", look_off)).model_dump()
    on = M.ConvergenceRow(**fr.fire_contract(graph, "corn", "2012-08-15", look_on)).model_dump()
    assert "intensity" not in json.dumps(off, default=str)        # flag-off: bytes carry no trace of T1
    by_id_on = {d["id"]: d for d in on["drivers"]}
    assert by_id_on["ending_stocks_su_ratio"]["intensity"] == "strong"   # banded driver: key present
    assert "intensity" not in by_id_on["el_nino"]                 # unbanded driver: key ABSENT, not null
    # (7) the fire decision is byte-identical across the flag
    assert off["regimes"] == on["regimes"]


def test_intensity_flag_helper_default_off_and_on(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_CONVERGENCE_INTENSITY", raising=False)
    assert an._intensity_on() is False
    for v in ("on", "1", "TRUE", "True"):
        monkeypatch.setenv("GRAPHRAG_CONVERGENCE_INTENSITY", v)
        assert an._intensity_on() is True
    for v in ("off", "", "yes", "no"):
        monkeypatch.setenv("GRAPHRAG_CONVERGENCE_INTENSITY", v)
        assert an._intensity_on() is False
