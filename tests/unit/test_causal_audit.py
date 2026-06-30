"""Curation-audit aggregator — pure tests (no files/network)."""
from __future__ import annotations

from leviathan.causal import audit as au
from leviathan.causal import schema as cs

SILVER = {"frost_risk", "crush_margin_z"}


def _d(id, **o):
    return cs.Driver(id=id, type=o.pop("type", "hazard"), sign=o.pop("sign", "+"),
                     mechanism=o.pop("mechanism", "m"), **o)


def test_audit_contract_flags_every_item():
    c = cs.CausalContract(
        contract="soybean_meal_cbot",
        drivers=[
            _d("frost", silver_ref="frost_risk", silver_status="available"),          # ok
            _d("board_crush", sign="0", silver_ref="crush_margin_z", silver_status="available"),  # 0-sign
            _d("RFS", silver_status="planned"),                                        # planned, no ref
            _d("ASF_hog_herd", silver_status="planned"),                               # planned, no ref
            _d("stale_feat", silver_ref="not_built", silver_status="available"),       # available but not in silver
            _d("vietnam_stock", silver_ref="vn_stock_z", silver_status="planned")],    # planned + named (roadmap)
        inter_commodity=[
            cs.InterCommodityEdge(driver_commodity="soybeans", relation="competes_with", sign="+"),
            cs.InterCommodityEdge(driver_commodity="soybeans", relation="competes_with", sign="-"),  # contradictory
            cs.InterCommodityEdge(driver_commodity="corn", relation="competes_with", sign="0")],     # 0-sign inter
        convergence=[])                                                                # NO convergence

    a = au.audit_contract(c, SILVER)
    assert a["no_convergence"] is True
    assert a["zero_signs"] == ["board_crush"]
    assert a["zero_inter"] == [("corn", "competes_with")]
    assert sorted(a["planned_unnamed"]) == ["ASF_hog_herd", "RFS"]
    assert a["planned_named"] == [("vietnam_stock", "vn_stock_z")]
    assert a["available_not_built"] == [("stale_feat", "not_built")]
    assert a["contradictory_inter"] == [("soybeans", "competes_with")]


def test_report_aggregates_roadmap_and_unnamed():
    c1 = cs.CausalContract(contract="corn_cbot", drivers=[_d("RFS", silver_status="planned"),
                                                          _d("RIN", silver_status="planned")])
    c2 = cs.CausalContract(contract="soybean_oil_cbot", drivers=[_d("RFS", silver_status="planned"),
                                                                _d("biodiesel", silver_ref="biodiesel_z",
                                                                   silver_status="planned")])
    res = {"silver": SILVER, "audits": [au.audit_contract(c1, SILVER), au.audit_contract(c2, SILVER)]}
    rep = au.report(res)
    assert "RFS` x2" in rep                       # unnamed planned recurs across 2 contracts -> one reserved name
    assert "biodiesel_z` x1" in rep               # the one already-named planned feature -> roadmap
    assert "NO convergence" in rep and "corn_cbot, soybean_oil_cbot" in rep
    assert "no special chars".encode("ascii")     # summary is ASCII-safe
    assert au.summary(res).startswith("contracts=2")
