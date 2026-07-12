"""SILVER-F060 + F061: the silver-prefix classification + write-block guard.

Loads the guard via file path and checks the classification of the CONAB legacy_orphan surface,
the F061 phantom paths, a stray run-log, a live table root, and an unclassified object.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_GUARD = _REPO / "scripts" / "silver" / "prefix_guard.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("prefix_guard", _GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["prefix_guard"] = mod           # dataclass needs the module registered
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ctx(guard):
    return guard.load_classification(), guard.table_roots()


class TestClassify:
    def test_conab_legacy_orphan_write_block(self, guard, ctx):
        classification, roots = ctx
        v = guard.classify_key(
            "silver/production/source=conab/commodity=arabica_coffee/part-000.parquet",
            classification, roots)
        assert v.classification == "legacy_orphan"
        assert v.violation == "write_block"          # any new object here is blocked
        assert v.package == "SILVER-F060"

    def test_stray_run_log_is_metadata(self, guard, ctx):
        classification, roots = ctx
        v = guard.classify_key("silver/psd/_run_log.json", classification, roots)
        assert v.classification == "metadata" and v.violation is None

    def test_forbidden_calendar_spreads(self, guard, ctx):
        classification, roots = ctx
        v = guard.classify_key("silver/calendar_spreads/x.parquet", classification, roots)
        assert v.classification == "forbidden" and v.violation == "write_block"

    def test_live_table_root_is_ok(self, guard, ctx):
        classification, roots = ctx
        v = guard.classify_key("silver/mpoc_exports_by_country/part-000.parquet", classification, roots)
        assert v.classification == "table" and v.violation is None

    def test_psd_table_object_is_table_not_metadata(self, guard, ctx):
        classification, roots = ctx
        # a real data object in silver_psd is `table`; only the exact _run_log.json is metadata.
        v = guard.classify_key("silver/psd/part-000.parquet", classification, roots)
        assert v.classification == "table"

    def test_unclassified_object_flags(self, guard, ctx):
        classification, roots = ctx
        v = guard.classify_key("silver/some_unknown_prefix/x.parquet", classification, roots)
        assert v.classification == "unclassified" and v.violation == "unclassified"

    def test_out_of_scope_non_silver(self, guard, ctx):
        classification, roots = ctx
        v = guard.classify_key("bronze/whatever/x.parquet", classification, roots)
        assert v.classification == "out_of_scope" and v.violation is None


class TestEvaluateInventory:
    def test_violation_tally(self, guard, ctx):
        classification, roots = ctx
        keys = [
            "silver/mpoc_exports_by_country/part-000.parquet",             # table ok
            "silver/production/source=conab/commodity=robusta_coffee/p.parquet",  # write_block
            "silver/rogue_prefix/x.parquet",                               # unclassified
        ]
        verdicts = guard.evaluate_inventory(keys, classification, roots)
        viol = [v for v in verdicts if v.violation]
        kinds = sorted(v.violation for v in viol)
        assert kinds == ["unclassified", "write_block"]

    def test_run_strict_nonzero_on_violation(self, guard):
        rc = guard.run(["silver/production/source=conab/x.parquet"], strict=True, report=False)
        assert rc == 3

    def test_run_clean_inventory_zero(self, guard):
        rc = guard.run(["silver/mpoc_exports_by_country/part-000.parquet"], strict=True, report=False)
        assert rc == 0
