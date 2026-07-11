"""P9-W0/W1/W2.3 unit tests for the cascade-leg census + pin-realizability lint.

pg is MOCKED throughout (a query_fn is injected). Nothing here touches the live mirror, Athena, or any
AWS/eval job. Covers: verdict classification (FIRES / DECLINES-HONESTLY / DARK country-not-a-psd-title /
probe-error), the Athena source tripwire (pg_query used, Q.athena_query_fn NEVER invoked, Q.STATS empty),
and check_pin_realizability (catches a synthetic true-pin-on-unrealizable query; passes the corrected q6
+ the real v4 fixture)."""
from __future__ import annotations

import types

import pytest

from leviathan.graphrag import config_check as cch
from leviathan.graphrag.numbers import cascade_census as cc
from leviathan.graphrag.numbers import query as Q


def _drv(driver_id: str, silver_ref: str, region):
    return types.SimpleNamespace(id=driver_id, silver_ref=silver_ref, region=region)


# One synthetic contract carrying one leg of every verdict class. All silver_refs are REAL mapped refs
# (export / stock), so casc.map_row resolves them and the census's real _scope/_region_row run unchanged.
_SYNTH = types.SimpleNamespace(
    contract="test_soy",
    drivers=[
        _drv("fires_leg", "export", "Russia"),        # region resolves -> 'Russia' -> pg has rows -> FIRES
        _drv("declines_leg", "export", "Global"),     # 'Global' is unresolved -> SKIP_NODE -> DECLINES
        _drv("dark_leg", "export", "Ukraine"),        # resolves -> 'Ukraine' NOT a title + 0 rows -> DARK
        _drv("probe_err_leg", "stock", None),         # primary rule; pg raises -> probe-error
    ],
)


class _MockPg:
    """A pg_query stand-in that routes by SQL content. Records every call so the test can assert pg_query
    was the ONLY executor."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, sql: str):
        self.calls.append(sql)
        if "DISTINCT" in sql:
            return [{"v": "Russia"}, {"v": "European Union"}, {"v": "United States"}]   # NO 'Ukraine'
        if "ending_stocks_mt" in sql:
            raise RuntimeError("mirror gap: stock table hiccup")                        # probe-error leg
        if "'Ukraine'" in sql:
            return []                                                                   # dark leg: 0 rows
        return [{"value": "1.0"}]                                                        # fires leg: has rows


@pytest.fixture
def _synth_index(monkeypatch):
    monkeypatch.setattr(cc, "_contract_index", lambda: {"test_soy": _SYNTH})
    # keep the census verdict test hermetic -- the fixture-derived per-query block is exercised elsewhere
    monkeypatch.setattr(cc, "_per_query_realizability", lambda: [])


def test_census_verdict_classification(_synth_index):
    mock = _MockPg()
    art = cc.census(asof="2026-02-15", query_fn=mock)
    verdicts = {leg["node_id"]: leg for leg in art["legs"]}

    assert verdicts["fires_leg"]["verdict"] == cc.FIRES
    assert verdicts["fires_leg"]["country"] == "Russia"
    assert verdicts["fires_leg"]["pg_rows"] == 1

    assert verdicts["declines_leg"]["verdict"] == cc.DECLINES
    assert verdicts["declines_leg"]["reason"] == "region-unresolved"
    assert verdicts["declines_leg"]["country"] is None

    assert verdicts["dark_leg"]["verdict"] == cc.DARK
    assert verdicts["dark_leg"]["reason"] == "country-not-a-psd-title"     # the France->EU class
    assert verdicts["dark_leg"]["country"] == "Ukraine"
    assert verdicts["dark_leg"]["pg_rows"] == 0

    assert verdicts["probe_err_leg"]["verdict"] == cc.PROBE_ERROR
    assert "mirror gap" in verdicts["probe_err_leg"]["reason"]

    b = art["banner"]
    assert (b["fires"], b["declines"], b["dark"], b["probe_errors"]) == (1, 1, 1, 1)
    assert b["athena_calls"] == 0
    assert art["per_contract_has_firing_leg"]["test_soy"] is True         # the FIRES leg lifts the rollup


def test_dark_leg_names_table_not_registered(_synth_index, monkeypatch):
    """A table missing from the numbers registry is its OWN sub-reason (review fold) -- never conflated
    with 'uncertified-table' (registered but certified-empty)."""
    class _Reg:
        def get(self, t):
            raise KeyError(t)

    monkeypatch.setattr(cc, "load_registry", lambda: _Reg())
    art = cc.census(asof="2026-02-15", query_fn=_MockPg())
    verdicts = {leg["node_id"]: leg for leg in art["legs"]}
    assert verdicts["dark_leg"]["verdict"] == cc.DARK
    assert verdicts["dark_leg"]["reason"] == "table-not-registered"       # silver_psd is not in _UNCERTIFIED


def test_census_non_zero_exit_on_unwaived_dark(_synth_index):
    art = cc.census(asof="2026-02-15", query_fn=_MockPg())
    dark = cc._unwaived_dark(art)
    assert [leg["node_id"] for leg in dark] == ["dark_leg"]               # the exit-gate forcing function


def test_census_uses_pg_query_never_athena(_synth_index, monkeypatch):
    """Source tripwire: the census must execute EVERY query through the injected pg_query and NEVER touch
    Q.athena_query_fn -- the plan's positive, observable ZERO-Athena guarantee."""
    athena_calls = []
    monkeypatch.setattr(Q, "athena_query_fn", lambda *a, **k: athena_calls.append(1))
    Q.reset_stats()

    mock = _MockPg()
    cc.census(asof="2026-02-15", query_fn=mock)

    assert mock.calls, "pg_query (the injected query_fn) was never invoked"
    assert athena_calls == [], "Q.athena_query_fn was invoked -- Athena fallback leaked into the census"
    assert Q.STATS == [], "Q.STATS populated -- an Athena query executed"


def test_athena_firewall_blocks_invocation_and_dirty_stats():
    """_athena_firewall makes athena_query_fn raise-on-invoke and hard-fails on a non-empty Q.STATS."""
    orig = Q.athena_query_fn
    with pytest.raises(RuntimeError, match="ATHENA TRIPWIRE"):
        with cc._athena_firewall():
            Q.athena_query_fn()                                          # blocked at the source
    assert Q.athena_query_fn is orig                                     # restored in finally

    with pytest.raises(RuntimeError, match="Q.STATS is non-empty"):
        with cc._athena_firewall():
            Q.STATS.append({"planning_ms": 1})                          # a leaked Athena stat -> hard fail
    Q.reset_stats()


# -- W2.3 check_pin_realizability -------------------------------------------------------------------------
def test_query_realizable_per_query_vs_contract():
    # the grounded biodiesel chain is all unmapped -> per-query FALSE even though the contract rolls up TRUE
    grounded = ["biodiesel_mandate", "RFS", "RIN", "blend_mandate", "crude_oil", "soybean_crush_margin"]
    q = {"id": "synth_q6", "contract": "soybean_oil_cbot", "cascade_drivers": grounded,
         "expect": {"cascade_fired": True}}
    assert cc.query_realizable(q) is False
    assert cc.contract_can_any_leg_fire("soybean_oil_cbot") is True       # the wrong-granularity greenlight
    # a query that grounds a mapped export leg IS realizable
    assert cc.query_realizable({"contract": "soybean_oil_cbot", "cascade_drivers": ["export_tax"]}) is True
    # no declaration -> UNKNOWN (None), never the contract rollup (fail-closed; review fold, major)
    assert cc.query_realizable({"contract": "soybean_oil_cbot"}) is None


def test_check_pin_realizability_catches_true_pin_and_passes_corrected(monkeypatch):
    grounded = ["biodiesel_mandate", "RFS"]                               # unmapped -> unrealizable per-query
    fixture = {"queries": [
        {"id": "bad_true_pin", "contract": "soybean_oil_cbot", "cascade_drivers": grounded,
         "expect": {"cascade_fired": True}},                             # ERROR: true pin on unrealizable
        {"id": "corrected_q6", "contract": "soybean_oil_cbot", "cascade_drivers": grounded,
         "expect": {"cascade_fired": False}},                            # OK: false pin on unrealizable
        {"id": "fine_true", "contract": "soybean_oil_cbot", "cascade_drivers": ["export_tax"],
         "expect": {"cascade_fired": True}},                             # OK: realizable + true pin
    ]}
    monkeypatch.setattr(cch, "_load", lambda name: fixture)
    errs = cch.check_pin_realizability()
    assert len(errs) == 1
    assert "bad_true_pin" in errs[0] and "cascade_fired:true" in errs[0]


def test_check_pin_realizability_fails_closed_on_undeclared(monkeypatch):
    """The MAJOR review finding: an undeclared cascade_fired pin must ERROR, never silently fall back to
    the contract rollup (which computes TRUE for soybean_oil_cbot and would greenlight the original q6)."""
    fixture = {"queries": [
        {"id": "undeclared_pin", "contract": "soybean_oil_cbot",
         "expect": {"cascade_fired": True}},                             # NO cascade_drivers declared
    ]}
    monkeypatch.setattr(cch, "_load", lambda name: fixture)
    errs = cch.check_pin_realizability()
    assert len(errs) == 1 and "cascade_drivers" in errs[0] and "fail-closed" in errs[0]


def test_check_pin_realizability_catches_stale_negative(monkeypatch):
    fixture = {"queries": [
        {"id": "stale_neg", "contract": "soybean_oil_cbot", "cascade_drivers": ["export_tax"],
         "expect": {"cascade_fired": False}},                            # ERROR: false pin on a fireable leg
    ]}
    monkeypatch.setattr(cch, "_load", lambda name: fixture)
    errs = cch.check_pin_realizability()
    assert len(errs) == 1 and "stale-negative" in errs[0]


def test_real_v4_fixture_pins_are_clean():
    """The shipped fixture (q6 re-pinned to false + cascade_drivers) passes the lint end-to-end."""
    assert cch.check_pin_realizability() == []
