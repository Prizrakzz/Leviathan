"""Silver leg v1 — OBSERVED/DOCUMENTED/CONTRADICTED semantics, all mocked (no Athena, no LLM).

Pins the anomaly math (z + veto zones), ref resolution through the graph (available-only, aliases),
the per-answer cap, failure degradation, the ground() integration (observed receipt fires, normal
VETOES even with dated text evidence), and the PIT invariant (every generated SQL carries the asof).
"""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag import planner as pl
from leviathan.graphrag import silverleg as slv


def _graph(su_status="available"):
    c = cs.CausalContract(
        contract="corn", aliases=[],
        drivers=[cs.Driver(id="ending_stocks_su_ratio", type="fundamental", sign="-", mechanism="tight stocks lift price",
                           silver_ref="psd_ending_stock_su_ratio", silver_status=su_status),
                 cs.Driver(id="el_nino", type="climate_driver", sign="+", mechanism="dries the belt",
                           silver_ref="oni_climate", silver_status="available"),
                 cs.Driver(id="drought", type="hazard", sign="+", mechanism="cuts yield")],
        convergence=[cs.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=2,
                                          drivers=["ending_stocks_su_ratio", "el_nino"])])
    return g.CausalGraph({"corn": c}, silver=set())


def _psd_rows(ratios: dict[str, tuple[float, float]]):
    """rows for (stocks, consumption) series keyed by marketing year."""
    stocks = [{"period": p, "value": s, "knowledge_date": "2012-08-10"} for p, (s, _) in ratios.items()]
    cons = [{"period": p, "value": c, "knowledge_date": "2012-08-10"} for p, (_, c) in ratios.items()]
    return stocks, cons


def _qfn_factory(stocks, cons, oni=None):
    calls = {"sql": []}

    def qfn(sql):
        calls["sql"].append(sql)
        if "ending_stocks_mt" in sql:
            return stocks
        if "consumption_mt" in sql:
            return cons
        if "oni_anom" in sql:
            return oni or []
        return []
    return qfn, calls


def test_su_ratio_anomalous_fires_observed():
    # history oscillating ~0.20 (real variance), latest year 0.08 -> deeply negative z -> observed
    ratios = {f"20{i:02d}": (180.0 if i % 2 else 220.0, 1000.0) for i in range(3, 12)}
    ratios["2012"] = (80.0, 1000.0)
    qfn, calls = _qfn_factory(*_psd_rows(ratios))
    look = slv.make_silver_lookup(_graph(), qfn)
    out = look("corn", "ending_stocks_su_ratio", "2012-08-15")
    assert out["live"] and out["verdict"] == "observed" and out["value"] == 0.08
    assert all("2012-08-15" in s for s in calls["sql"])            # PIT: asof embedded in every SQL


def test_su_ratio_normal_year_is_normal_verdict():
    ratios = {f"20{i:02d}": (180.0 if i % 2 else 220.0, 1000.0) for i in range(3, 12)}
    ratios["2012"] = (200.0, 1000.0)                               # latest at the historical mean
    qfn, _ = _qfn_factory(*_psd_rows(ratios))
    out = slv.make_silver_lookup(_graph(), qfn)("corn", "ending_stocks_su_ratio", "2012-08-15")
    assert out["live"] and out["verdict"] == "normal"


def test_oni_band_semantics():
    qfn, _ = _qfn_factory([], [], oni=[{"value": "1.6", "data_date": "2012-07-31"}])
    out = slv.make_silver_lookup(_graph(), qfn)("corn", "el_nino", "2012-08-15")
    assert out["verdict"] == "observed" and out["value"] == 1.6
    qfn2, _ = _qfn_factory([], [], oni=[{"value": "0.1", "data_date": "2012-07-31"}])
    out2 = slv.make_silver_lookup(_graph(), qfn2)("corn", "el_nino", "2012-08-15")
    assert out2["verdict"] == "normal"


def test_unserved_ref_planned_status_and_no_asof_degrade():
    look = slv.make_silver_lookup(_graph(su_status="planned"), lambda sql: [])
    assert look("corn", "ending_stocks_su_ratio", "2012-08-15")["live"] is False   # planned -> not served
    look2 = slv.make_silver_lookup(_graph(), lambda sql: [])
    assert look2("corn", "drought", "2012-08-15")["live"] is False                  # no handler for ref-less
    assert look2("corn", "el_nino", None)["live"] is False                          # no asof -> no lookup


def test_cap_and_memo_and_error_degrade():
    ratios = {f"20{i:02d}": (200.0, 1000.0) for i in range(3, 13)}
    qfn, calls = _qfn_factory(*_psd_rows(ratios))
    look = slv.make_silver_lookup(_graph(), qfn, cap=1)
    look("corn", "ending_stocks_su_ratio", "2012-08-15")
    n = len(calls["sql"])
    look("corn", "ending_stocks_su_ratio", "2012-08-15")           # memo hit: no new SQL
    assert len(calls["sql"]) == n
    assert look("corn", "el_nino", "2012-08-15")["reason"] == "capped"

    def boom(sql):
        raise RuntimeError("athena down")
    out = slv.make_silver_lookup(_graph(), boom)("corn", "ending_stocks_su_ratio", "2012-08-15")
    assert out["live"] is False                                    # silver never breaks an answer


# ── ground() integration: observed receipt fires; normal VETOES documented chatter ────────────────
def _sg(graph):
    return pl.grounded_subgraph("corn stocks squeeze", graph, embed=lambda xs: [[1.0, 0.0] for _ in xs],
                                route_fn=lambda q, g: ["corn"])


def _dated_retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2012-07-01", "source": "usda_wasde", "source_key": "s3://x", "text": "stocks chatter"}]


def test_ground_observed_receipt_fires_regime():
    graph = _graph()
    def look(cid, did, asof):
        if did == "ending_stocks_su_ratio":
            return {"live": True, "verdict": "observed", "value": 0.08, "unit": "S/U", "z": -2.4,
                    "knowledge_date": "2012-08-10", "ref": "psd_ending_stock_su_ratio", "detail": ""}
        if did == "el_nino":
            return {"live": True, "verdict": "observed", "value": 1.6, "unit": "ONI", "z": 1.6,
                    "knowledge_date": "2012-07-31", "ref": "oni_climate", "detail": ""}
        return {"live": False}
    sg = _sg(graph)
    pl.ground(sg, "corn stocks squeeze", graph, retrieve=_dated_retrieve, silver_lookup=look,
              asof="2012-08-15", driver_slices={"drought"})
    fired = [r for r in sg.fired_regimes if r["name"] == "squeeze"]
    assert fired and fired[0]["basis"]["ending_stocks_su_ratio"]["kind"] == "observed"
    assert fired[0]["basis"]["ending_stocks_su_ratio"]["z"] == -2.4


def test_ground_normal_silver_vetoes_despite_dated_text():
    graph = _graph()
    def look(cid, did, asof):
        return {"live": True, "verdict": "normal", "value": 0.21, "unit": "S/U", "z": 0.2,
                "knowledge_date": "2012-08-10", "ref": "psd_ending_stock_su_ratio", "detail": ""}
    sg = _sg(graph)
    pl.ground(sg, "corn stocks squeeze", graph, retrieve=_dated_retrieve, silver_lookup=look,
              asof="2012-08-15", driver_slices={"ending_stocks_su_ratio", "el_nino"})
    assert not sg.fired_regimes                                    # both drivers vetoed -> nothing fires
    veto = sg.trace["silver_veto"]["corn"]
    assert set(veto) == {"ending_stocks_su_ratio", "el_nino"} and veto["el_nino"]["z"] == 0.2
