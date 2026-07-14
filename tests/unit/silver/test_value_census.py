"""SILVER-V001 -- canonical value census unit tests.

Builds synthetic local parquet files (no AWS -- the F002 conftest guard is happy)
and drives the pure footer-statistics census + gate. Covers: all-NaN failure,
single-vintage (ESR-collapse) failure, a healthy pass, sentinel saturation, and the
floor-calibration case that must NOT false-fail a legitimately-sparse source.
"""
from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from leviathan.silver.value_census import (
    KIND_ALL_NAN,
    KIND_NONNULL_BELOW_FLOOR,
    KIND_SENTINEL_SATURATED,
    KIND_SINGLE_VINTAGE,
    census_column,
    build_table_result,
    evaluate_gate,
    evaluate_warnings,
    file_column_stat,
)


def _write(tmp_path, name, table: pa.Table):
    path = tmp_path / name
    pq.write_table(table, path)
    return pq.read_metadata(path)


def _stat(metadata, column):
    return file_column_stat(metadata, column)


# ---------------------------------------------------------------------------
# The module makes no Athena/AWS call (INV-3 structural tripwire).
# ---------------------------------------------------------------------------
def test_module_has_no_athena_or_boto_dependency():
    import leviathan.silver.value_census as vc

    src = __import__("inspect").getsource(vc).lower()
    # no AWS client construction and no Athena query call anywhere in the module.
    assert "import boto3" not in src
    assert "start_query_execution" not in src
    assert 'client("athena"' not in src and "client('athena'" not in src


# ---------------------------------------------------------------------------
# all-NaN detection (the CHIRPS class).
# ---------------------------------------------------------------------------
def test_all_nan_float_column_fails(tmp_path):
    # A float column that is entirely null -> parquet writes null_count == num_rows,
    # has_min_max False -> the census reads effective non-null 0.
    tbl = pa.table({"value": pa.array([None, None, None, None], type=pa.float64())})
    md = _write(tmp_path, "allnan.parquet", tbl)

    census = census_column([_stat(md, "value")], "value")
    assert census.all_nan is True
    assert census.nonnull_fraction == 0.0

    rows = evaluate_gate("t", {"value": census}, ["value"], 0.5)
    assert len(rows) == 1
    assert rows[0].kind == KIND_ALL_NAN


def test_all_nan_via_float_nan_values(tmp_path):
    # NaN stored as an actual float value (not null): parquet excludes NaN from
    # min/max so has_min_max is False -> still detected as effectively all-missing.
    tbl = pa.table({"value": pa.array([float("nan")] * 6, type=pa.float64())})
    md = _write(tmp_path, "nan.parquet", tbl)
    stat = _stat(md, "value")
    # null_count is 0 (NaN is not null) but has_min_max is False.
    assert stat.null_count == 0
    assert stat.has_min_max is False
    census = census_column([stat], "value")
    assert census.all_nan is True


# ---------------------------------------------------------------------------
# non-null floor breach (partial nulls).
# ---------------------------------------------------------------------------
def test_below_floor_fails(tmp_path):
    tbl = pa.table({"value": pa.array([1.0, None, None, None], type=pa.float64())})  # 25% non-null
    md = _write(tmp_path, "sparse.parquet", tbl)
    census = census_column([_stat(md, "value")], "value")
    assert census.nonnull_fraction == pytest.approx(0.25)
    rows = evaluate_gate("t", {"value": census}, ["value"], 0.5)
    assert [r.kind for r in rows] == [KIND_NONNULL_BELOW_FLOOR]


def test_above_floor_passes(tmp_path):
    tbl = pa.table({"value": pa.array([1.0, 2.0, 3.0, None], type=pa.float64())})  # 75% non-null
    md = _write(tmp_path, "ok.parquet", tbl)
    census = census_column([_stat(md, "value")], "value")
    assert census.nonnull_fraction == pytest.approx(0.75)
    assert evaluate_gate("t", {"value": census}, ["value"], 0.5) == []


# ---------------------------------------------------------------------------
# single-vintage / vintage-adequacy (the ESR class).
# ---------------------------------------------------------------------------
def test_single_vintage_fails(tmp_path):
    # one commodity partition, a single as_of value.
    a = pa.table({"as_of_date": pa.array(["20260528"] * 100)})
    b = pa.table({"as_of_date": pa.array(["20260528"] * 80)})
    mds = [_write(tmp_path, "a.parquet", a), _write(tmp_path, "b.parquet", b)]
    census = census_column([_stat(m, "as_of_date") for m in mds], "as_of_date")
    assert census.distinct_lower_bound == 1

    rows = evaluate_gate(
        "silver_esr_compact", {"as_of_date": census}, [], 0.5,
        knowledge_date_col="as_of_date", knowledge_census=census,
    )
    assert [r.kind for r in rows] == [KIND_SINGLE_VINTAGE]


def test_single_vintage_waiver_demotes_to_warn(tmp_path):
    """BF-W2 rider 6: a declared vintage_waiver DEMOTES the single_vintage hard row to a WARN that
    names the approval; every other kind stays hard; no waiver -> unchanged (evaluate_gate itself
    never consults the waiver, so the gate cannot be quietly disarmed)."""
    from leviathan.silver.value_census import apply_vintage_waiver

    a = pa.table({"ingest_date": pa.array(["2026-01-20"] * 100)})
    md = _write(tmp_path, "a.parquet", a)
    census = census_column([_stat(md, "ingest_date")], "ingest_date")
    rows = evaluate_gate(
        "silver_production", {"ingest_date": census}, [], 0.5,
        knowledge_date_col="ingest_date", knowledge_census=census,
    )
    assert [r.kind for r in rows] == [KIND_SINGLE_VINTAGE]      # the gate itself stays strict

    waiver = {"reason": "annual latest-only source; second vintage structurally impossible",
              "approved": "2026-07-15 BF-W2 rider 6 (user gate)"}
    kept, waived = apply_vintage_waiver(rows, waiver)
    assert kept == []                                            # hard-fail cleared...
    assert len(waived) == 1 and waived[0].kind == KIND_SINGLE_VINTAGE
    assert "WAIVED (2026-07-15 BF-W2 rider 6 (user gate))" in waived[0].detail  # ...but never silent

    kept_no, waived_no = apply_vintage_waiver(rows, None)        # no waiver -> nothing changes
    assert kept_no == rows and waived_no == []


def test_live_registry_carries_the_faostat_waiver():
    # the tracked contract (rider 6) validates against the strict schema and reaches consumers.
    from leviathan.silver.registry import load_registry as load_silver
    reg = load_silver()
    w = reg.tables["silver_production"].get("vintage_waiver")
    assert w and "FAOSTAT" in w["reason"] and "rider 6" in w["approved"]


def test_multi_vintage_passes(tmp_path):
    a = pa.table({"as_of_date": pa.array(["20260521"] * 50)})
    b = pa.table({"as_of_date": pa.array(["20260528"] * 50)})
    mds = [_write(tmp_path, "a.parquet", a), _write(tmp_path, "b.parquet", b)]
    census = census_column([_stat(m, "as_of_date") for m in mds], "as_of_date")
    assert census.distinct_lower_bound == 2
    rows = evaluate_gate(
        "t", {"as_of_date": census}, [], 0.5,
        knowledge_date_col="as_of_date", knowledge_census=census,
    )
    assert rows == []


# ---------------------------------------------------------------------------
# sentinel saturation is a hard fail; a benign constant is only a warning.
# ---------------------------------------------------------------------------
def test_sentinel_saturation_hard_fails(tmp_path):
    tbl = pa.table({"value": pa.array([-999.0] * 20, type=pa.float64())})
    md = _write(tmp_path, "sentinel.parquet", tbl)
    census = census_column([_stat(md, "value")], "value")
    assert census.sentinel_saturated is True
    rows = evaluate_gate("t", {"value": census}, ["value"], 0.5)
    assert [r.kind for r in rows] == [KIND_SENTINEL_SATURATED]


def test_benign_constant_is_warning_not_gate(tmp_path):
    # A legitimately-thin partition: one distinct non-sentinel value. Must NOT hard-fail
    # (OP-8/AV-11 calibration: the WASDE 1987 scanned release).
    tbl = pa.table({"estimate": pa.array([4.3] * 10, type=pa.float64())})
    md = _write(tmp_path, "thin.parquet", tbl)
    census = census_column([_stat(md, "estimate")], "estimate")
    assert census.all_constant is True
    assert evaluate_gate("t", {"estimate": census}, ["estimate"], 0.5) == []
    warns = evaluate_warnings("t", {"estimate": census}, ["estimate"])
    assert len(warns) == 1


# ---------------------------------------------------------------------------
# end-to-end table result serialisation + gate wiring.
# ---------------------------------------------------------------------------
def test_build_table_result_shape(tmp_path):
    good = pa.table({"value": pa.array([1.0, 2.0, 3.0]), "as_of_date": pa.array(["a", "b", "c"])})
    md = _write(tmp_path, "g.parquet", good)
    census = {
        "value": census_column([_stat(md, "value")], "value"),
        "as_of_date": census_column([_stat(md, "as_of_date")], "as_of_date"),
    }
    result = build_table_result(
        "silver_demo",
        partition_mode="flat",
        value_columns=["value"],
        min_nonnull_frac=0.5,
        knowledge_date_col="as_of_date",
        vintage_retention="per-vintage",
        census_by_column=census,
        files_sampled=1,
        sample_strategy="flat: 1 group",
    )
    assert result.passed is True
    d = result.to_dict()
    assert d["athena_queries_issued"] == 0
    assert d["package"] == "SILVER-V001"
    assert d["mechanism"] == "parquet_footer_statistics"
    assert "value" in d["columns"]


# ------------------------------------------------------- control-plane exclusion (BF-W1 hygiene)
def test_census_walker_skips_hidden_control_plane_segments():
    """The F015 publisher stages under <root>/_shadow/ and writes <root>/_manifests/; the
    census must never sample those as data groups (Hive hidden-path convention)."""
    import importlib.util
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "value_census_job", repo / "jobs" / "audit" / "value_census.py")
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)  # type: ignore[union-attr]

    assert job._is_hidden("_shadow/")
    assert job._is_hidden("silver/weather/source=chirps/_shadow/commodity=cocoa/part-000.parquet")
    assert job._is_hidden("_manifests/silver_chirps-cocoa.json")
    assert job._is_hidden(".hidden/part.parquet")
    assert not job._is_hidden("commodity=cocoa/")
    assert not job._is_hidden("silver/weather/source=chirps/commodity=cocoa/year=1981/part-000.parquet")
