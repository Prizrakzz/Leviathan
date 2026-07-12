"""SILVER-F062: the standard job/publisher adoption lint.

Loads the lint via file path (it is a scripts/ tool, not an importable package) and checks the
per-table adoption verdict + the integrity-violation detection.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_LINT = _REPO / "scripts" / "silver" / "f062_adoption_lint.py"


@pytest.fixture(scope="module")
def lint():
    spec = importlib.util.spec_from_file_location("f062_adoption_lint", _LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _contract(**kw):
    base = {
        "table_name": "silver_x",
        "producer": {"status": "producer", "transform": "t.py",
                     "batch_task": "jobs/batch/mpoc_exports_by_country_silver_task.py"},
        "writer_schema_pinned": True,
        "drift_summary": [],
    }
    base.update(kw)
    return base


class TestEvaluateTable:
    def test_lane_ob_producers_are_adopters(self, lint):
        from leviathan.silver.registry import load_registry
        reg = load_registry()
        for name in ["silver_mpoc_exports_by_country", "silver_mpoc_trade_stats_monthly",
                     "silver_mpoc_stock_comparison", "silver_sagis_cec",
                     "silver_sagis_weekly_exports", "silver_mpob", "silver_mpob_annual"]:
            r = lint.evaluate_table(reg.table(name))
            assert r["adopted"], (name, r)
            assert not r["integrity_violation"]

    def test_missing_task_not_adopted(self, lint):
        r = lint.evaluate_table(_contract(
            producer={"status": "producer", "transform": "t.py",
                      "batch_task": "jobs/batch/does_not_exist.py"}))
        assert not r["adopted"] and not r["publisher_adopted"]

    def test_pinned_without_publisher_is_integrity_violation(self, lint):
        # a real bespoke file (no publisher markers) that falsely claims writer_schema_pinned:
        # the lint must flag the dishonest pin as an integrity violation.
        r = lint.evaluate_table(_contract(
            writer_schema_pinned=True,
            producer={"status": "producer", "transform": "t.py",
                      "batch_task": "jobs/ingest/fetch_mpoc.py"}))  # a fetcher, not a publisher route
        assert r["task_exists"] and not r["publisher_adopted"]
        assert r["integrity_violation"] is True and not r["adopted"]

    def test_half_orphan_excluded_from_producers(self, lint):
        r = lint.evaluate_table(_contract(
            producer={"status": "half-orphan", "transform": None, "batch_task": None},
            writer_schema_pinned=False))
        assert r["status"] == "half-orphan" and not r["adopted"]


def test_run_writes_report_and_reports_lane_ob(lint):
    # Non-strict run always returns 0 and writes the report. (A concurrent sibling lane may be
    # mid-adoption, so we do NOT assert the whole tree is violation-free here.)
    rc = lint.run(strict=False)
    assert rc == 0
    out = _REPO / "reports" / "silver_readiness" / "R2R3_producers" / "F062_adoption.json"
    assert out.exists()
    import json
    data = json.loads(out.read_text(encoding="utf-8"))
    adopters = {t["table"] for t in data["tables"] if t["adopted"]}
    assert {"silver_mpoc_exports_by_country", "silver_sagis_cec", "silver_mpob"} <= adopters
    # LANE OB's own tables must have NO integrity violation (honest pins).
    lane_ob = {"silver_mpoc_exports_by_country", "silver_mpoc_trade_stats_monthly",
               "silver_mpoc_stock_comparison", "silver_sagis_cec",
               "silver_sagis_weekly_exports", "silver_mpob", "silver_mpob_annual"}
    for t in data["tables"]:
        if t["table"] in lane_ob:
            assert not t["integrity_violation"], t["table"]
