"""Semi-automated curation pass — pure tests (no files/network)."""
from __future__ import annotations

from leviathan.causal import curate as cu
from leviathan.causal import schema as cs

SILVER = {"frost_risk"}


def _d(id, **o):
    return cs.Driver(id=id, type=o.pop("type", "hazard"), sign=o.pop("sign", "+"),
                     mechanism=o.pop("mechanism", "m"), **o)


def test_sign_map_takes_modal_nonzero():
    c1 = cs.CausalContract(contract="a", drivers=[_d("drought", sign="+"), _d("usd", sign="-")])
    c2 = cs.CausalContract(contract="b", drivers=[_d("drought", sign="+"), _d("usd", sign="+")])
    sm = cu.sign_map([c1, c2])
    assert sm["drought"] == "+"            # +,+ -> +
    assert sm["usd"] in ("+", "-")         # tie broken deterministically by Counter


def test_reserve_name_suffix_by_type():
    assert cu.reserve_name(_d("blocking_high", type="hazard")) == "blocking_high_flag"
    assert cu.reserve_name(_d("EUDR", type="policy_event")) == "eudr_flag"
    assert cu.reserve_name(_d("crush_margin", type="instrument")) == "crush_margin_z"


def test_reserve_name_does_not_oversingularize():
    # the matcher key singularizes ('basis'->basi); a reserved NAME must not (or the roadmap is ugly/wrong)
    assert cu.reserve_name(_d("basis", type="instrument")) == "basis_z"
    assert cu.reserve_name(_d("excess_rain", type="hazard")) == "excess_rain_flag"
    assert cu.reserve_name(_d("freight_logistics", type="instrument")) == "freight_logistics_z"


def test_curate_contract_applies_c1_c2_c3():
    signs = {"board_crush": "-"}                       # sibling-borrow source for the lone 0-sign
    c = cs.CausalContract(contract="soybean_meal_cbot", drivers=[
        _d("frost", silver_ref="frost_risk", silver_status="available"),               # ok, untouched
        _d("stale", silver_ref="not_built", silver_status="available"),                # C1 -> planned
        _d("RFS", type="policy_event", silver_status="planned"),                        # C2 -> rfs_flag
        _d("board_crush", sign="0", type="instrument", silver_status="planned"),        # C2 + C3
        _d("mystery", sign="0")])                                                       # C3 residual (no sibling)
    c2, log = cu.curate_contract(c, signs, SILVER)
    by = {d.id: d for d in c2.drivers}
    assert by["stale"].silver_status == "planned" and log["flips"] == ["stale"]
    assert by["RFS"].silver_ref == "rfs_flag"
    assert by["board_crush"].silver_ref == "board_crush_z" and by["board_crush"].sign == "-"  # named + borrowed
    assert by["mystery"].sign == "0" and log["residual_zero"] == ["mystery"]          # unresolved, not dropped
    assert by["frost"].silver_ref == "frost_risk"                                     # available+in-silver untouched


def test_run_builds_roadmap_and_report():
    c1 = cs.CausalContract(contract="corn_cbot", drivers=[_d("RFS", type="policy_event", silver_status="planned")])
    c2 = cs.CausalContract(contract="soybean_oil_cbot", drivers=[_d("RFS", type="policy_event", silver_status="planned")])
    res = cu.run([], apply=False) if False else {
        "logs": [cu.curate_contract(c1, {}, SILVER)[1], cu.curate_contract(c2, {}, SILVER)[1]],
        "roadmap": {}, "signs": {}, "silver": SILVER}
    # rebuild roadmap the way run() does
    for log in res["logs"]:
        for _id, ref in log["named"]:
            res["roadmap"].setdefault(ref, set()).add(log["contract"])
    assert res["roadmap"]["rfs_flag"] == {"corn_cbot", "soybean_oil_cbot"}            # one slug, two contracts
    rep = cu.report(res)
    assert "MLOps feature roadmap" in rep and "rfs_flag` <- 2 contract(s)" in rep
