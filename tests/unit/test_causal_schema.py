"""Causal-ontology schema — pure validation tests (no network/spend)."""
from __future__ import annotations

import pytest
from leviathan.causal import schema as cs
from pydantic import ValidationError


def _contract(**over):
    base = dict(
        contract="arabica_coffee",
        target_metrics=["price"],
        drivers=[
            cs.Driver(id="la_nina", type="climate_driver", sign="+", mechanism="dry Brazil",
                      silver_ref="oni_la_nina_brazil_flag", silver_status="available"),
            cs.Driver(id="brazil_frost", type="hazard", sign="+", mechanism="kills arabica trees",
                      lag="0-2 quarters", edge_type="affects_yield_of", parents=["la_nina"],
                      silver_ref="frost_risk", silver_status="available", confidence="high"),
        ],
        inter_commodity=[cs.InterCommodityEdge(driver_commodity="robusta_coffee",
                                               relation="substitutes_for", sign="-")],
        convergence=[cs.ConvergenceSignal(name="bullish_squeeze", direction="+", requires_any_n_of=2,
                                          drivers=["la_nina", "brazil_frost"],
                                          interactions=[cs.Interaction(when=["brazil_frost", "la_nina"])])],
    )
    base.update(over)
    return cs.CausalContract(**base)


def test_valid_contract_and_views():
    c = _contract()
    assert c.driver_ids() == {"la_nina", "brazil_frost"}
    assert [d.id for d in c.fan_in_drivers()] == ["brazil_frost"]   # has a parent
    assert c.schema_version == cs.SCHEMA_VERSION


def test_roundtrip_dump_load(tmp_path):
    c = _contract()
    p = tmp_path / "arabica_coffee.yaml"
    cs.dump(c, p)
    back = cs.load(p)
    assert back == c                                                # exact round-trip
    assert "silver_status: available" in p.read_text(encoding="utf-8")


def test_self_parent_rejected():
    with pytest.raises(ValidationError):
        cs.Driver(id="x", type="hazard", sign="+", mechanism="m", parents=["x"])


def test_duplicate_driver_ids_rejected():
    with pytest.raises(ValidationError):
        _contract(drivers=[cs.Driver(id="d", type="hazard", sign="+", mechanism="a"),
                           cs.Driver(id="d", type="hazard", sign="-", mechanism="b")])


def test_unknown_parent_rejected():
    with pytest.raises(ValidationError):
        _contract(drivers=[cs.Driver(id="d", type="hazard", sign="+", mechanism="m", parents=["ghost"])],
                  convergence=[])


def test_convergence_unknown_driver_rejected():
    with pytest.raises(ValidationError):
        _contract(convergence=[cs.ConvergenceSignal(name="s", direction="+", requires_any_n_of=1,
                                                    drivers=["ghost"])])


def test_requires_n_within_drivers():
    with pytest.raises(ValidationError):
        cs.ConvergenceSignal(name="s", direction="+", requires_any_n_of=3, drivers=["a", "b"])


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        cs.Driver(id="d", type="hazard", sign="+", mechanism="m", bogus="x")
