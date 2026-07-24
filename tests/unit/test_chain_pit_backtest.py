"""CHAIN ENGINE -- the ESRxWASDE PIT backtest harness, unit-tested on FIXTURES (CHAIN_ENGINE_PLAN 4.2, D10).

Tests the harness's PIT-audit LOGIC without pg: the four hard asserts (no-lookahead, vintage-honesty, pre-ESR
hop_dark decline, determinism) exercised on synthetic fetch_window-shaped records + a SQL-text-keyed stub qfn
driving the REAL fetch_window/build_sql path for silver_esr + silver_wasde. main() runs the live grid (gate 2)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_HARNESS = Path(__file__).resolve().parents[2] / "scripts" / "graphrag" / "chain_pit_backtest.py"
_spec = importlib.util.spec_from_file_location("chain_pit_backtest", _HARNESS)
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)


def _wasde(release_date, asof_ok=True):
    return {"query": {"table": "silver_wasde"}, "status": "ok",
            "rows": [{"value": "0.12", "release_date": release_date, "marketing_year": "2012/13"}]}


# ── assert (1): zero lookahead ───────────────────────────────────────────────────────────────────────
def test_guard_violations_flags_future_release_date():
    rec = _wasde("2013-01-01")                                    # release AFTER the asof
    assert B._guard_violations(rec, "2012-08-15")


def test_guard_violations_clean_when_release_before_asof():
    assert B._guard_violations(_wasde("2012-08-10"), "2012-08-15") == []


def test_guard_violations_flags_future_year_month():
    rec = {"query": {"table": "silver_noaa_oni"}, "status": "ok",
           "rows": [{"value": "0.6", "year": 2012, "month": 12}]}   # 2012-12 > asof 2012-08
    assert B._guard_violations(rec, "2012-08-15")


def test_guard_violations_no_guard_col_is_not_a_lookahead():
    rec = {"query": {"table": "silver_x"}, "status": "ok", "rows": [{"value": "1"}]}
    assert B._guard_violations(rec, "2012-08-15") == []


# ── assert (2): vintage honesty ──────────────────────────────────────────────────────────────────────
def test_vintage_dishonest_when_release_after_asof():
    assert not B._vintage_honest(_wasde("2013-01-01"), "2012-08-15")


def test_vintage_honest_when_release_before_asof():
    assert B._vintage_honest(_wasde("2012-08-10"), "2012-08-15")


def test_vintage_number_without_provenance_is_dishonest():
    rec = {"query": {"table": "silver_wasde"}, "status": "ok", "rows": [{"value": "0.12"}]}   # no guard col
    assert not B._vintage_honest(rec, "2012-08-15")


def test_esr_week_ending_date_is_honest_provenance():
    rec = {"query": {"table": "silver_esr"}, "status": "ok",
           "rows": [{"value": "1234.5", "week_ending_date": "2012-08-09"}]}
    assert B._vintage_honest(rec, "2012-08-15")                   # ESR's guard is week_ending_date, not release_date


def test_not_known_record_is_honest_absence():
    assert B._vintage_honest({"query": {"table": "silver_wasde"}, "status": "not_known", "rows": []}, "2012-08-15")


# ── assert (3): all-hops-or-nothing (a dark hop kills the chain) ─────────────────────────────────────
def test_chain_decline_none_when_both_hops_ok():
    ok = {"status": "ok", "rows": [{"value": "1"}]}
    assert B.chain_decline([ok, ok]) is None


def test_chain_decline_hop_dark_when_a_hop_is_empty():
    ok = {"status": "ok", "rows": [{"value": "1"}]}
    dark = {"status": "not_known", "rows": []}
    assert B.chain_decline([ok, dark]) == "hop_dark"
    assert B.chain_decline([dark, ok]) == "hop_dark"


# ── the two-hop build via the REAL fetch_window path + the asserts end-to-end ────────────────────────
def _stub_qfn(*, dark=None, ahead=False):
    def qfn(sql):
        s = sql.lower()
        if dark and dark in s:
            return []
        if "esr" in s:
            we = "2012-09-30" if ahead else "2012-08-09"
            return [{"value": "1234.5", "week_ending_date": we}]
        if "wasde" in s:
            rd = "2013-01-01" if ahead else "2012-08-10"
            return [{"value": "0.12", "release_date": rd, "marketing_year": "2012/13"}]
        return [{"value": "1"}]
    return qfn


def test_run_chain_fires_and_audits_clean():
    run = B.run_chain_at_asof(_stub_qfn(), "2012-08-15")
    assert run["hops"][0]["status"] == "ok" and run["hops"][1]["status"] == "ok"
    assert run["decline"] is None
    assert B.audit_run(run) == []                                # no lookahead, vintage-honest


def test_run_chain_dark_esr_declines_hop_dark():
    assert B.run_chain_at_asof(_stub_qfn(dark="esr"), "2012-08-15")["decline"] == "hop_dark"


def test_run_chain_lookahead_is_a_blocker():
    run = B.run_chain_at_asof(_stub_qfn(ahead=True), "2012-08-15")
    assert B.audit_run(run)                                       # future release_date + week -> blockers


# ── assert (4): determinism ─────────────────────────────────────────────────────────────────────────
def test_two_runs_at_one_asof_are_byte_identical():
    a = B.run_chain_at_asof(_stub_qfn(), "2012-08-15")
    b = B.run_chain_at_asof(_stub_qfn(), "2012-08-15")
    assert B._fingerprint(a["hops"]) == B._fingerprint(b["hops"])


def test_pre_esr_asof_is_strictly_before_coverage():
    # S6 fold: the decline asof must be strictly < 1989-09-01 (else it is pre-1990 but NOT pre-ESR).
    assert B.PRE_ESR_ASOF < B.ESR_COVERAGE_START
    assert B.PRE_ESR_ASOF == "1988-06-01"


def test_grid_has_at_least_eight_live_asofs():
    assert len(B.GRID) >= 8
