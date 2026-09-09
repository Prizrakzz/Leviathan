"""THE SIBLING SWEEP: one shared partition-body schema pin for all five per-partition producers.

WHAT THIS FILE IS ABOUT. The 2026-09-09 NASS gate RCA found ``jobs/batch/nass_annual_silver_task``
writing every ``(commodity, year)`` object with a bare
``df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")`` and NO schema, so arrow
inferred the type per group and any group with zero non-NA values in a measure column landed as
arrow ``null`` -- physical INT32 with no Statistics struct at all. 475 such column-instances over
1,206 canonical objects; the 322 cottonseed ones refused the usda_nass chain three consecutive
Tuesdays. That commit pinned ONE writer. A grep of ``jobs/batch`` for the same idiom found FOUR
more producers carrying it verbatim -- ``nass_crop_progress``, ``fgis``, ``fnc_colombia`` (three
tables from one writer) and ``modis_ndvi`` -- and this file is the deck for closing all of them
through a single adapter, ``leviathan.silver.flat_producer.encode_partitioned_body``, into which
nass_annual's local ``_body_schema`` was lifted.

WHAT THE PIN DOES NOT CLAIM, measured on the real canonical footers on 2026-09-09 and stated here
so nobody reads this deck as a repair report. All four siblings had ZERO null-typed column
instances at the time of the sweep (280 + 223 + 148 objects read in full, 150 of modis's 10,532
sampled evenly): every value column was already the right type with statistics, and NO census kind
moves on any of them. What kept the arrow-null path shut was a CONVENTION -- each transform coerces
its measures (``.astype("Float64")`` / ``.astype("float64")`` / ``pd.to_numeric``) after the same
``pd.NA`` backfill that produced the nass_annual defect, and nass_annual is precisely the one whose
backfill has no cast after it. The pin replaces that convention with a contract checked at the
write. Re-encoding every one of those real objects through the new code raised nothing and changed
no value.

AWS-free, no network: local parquet round-trips through the real producer functions and the real
tracked contracts.
"""
from __future__ import annotations

import datetime as dt
import importlib
import io

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from leviathan.silver.flat_producer import (
    encode_partitioned_body,
    pa_schema_for_partitioned_body,
)
from leviathan.silver.registry import load_registry
from leviathan.silver.value_census import census_column, file_column_stat

from leviathan.transforms.bronze_to_silver.fnc_colombia import (
    AREA_OUTPUT_COLUMNS,
    EXPORTS_PORT_TYPE_OUTPUT_COLUMNS,
    MONTHLY_OUTPUT_COLUMNS,
)
from leviathan.transforms.bronze_to_silver.usda_fgis import OUTPUT_COLUMNS as FGIS_COLUMNS
from leviathan.transforms.bronze_to_silver.usda_nass_crop_progress import (
    OUTPUT_COLUMNS as CROP_PROGRESS_COLUMNS,
)

# The MODIS silver frame's own column order (``modis_ndvi_bronze_to_silver``'s final projection).
# Spelled out rather than imported because that transform hard-codes the list inline twice; the
# order pin below is what catches a drift between it and the contract.
MODIS_COLUMNS = ["date", "year", "period", "commodity", "country", "region", "latitude",
                 "longitude", "ndvi_raw", "ndvi", "pixel_reliability", "ndvi_z_score",
                 "baseline_mean", "baseline_std", "ingest_date"]

# (registry table, batch module, body columns, a measure column NASS-style absence would empty)
SIBLINGS = [
    ("silver_nass_crop_progress", "jobs.batch.nass_crop_progress_silver_task",
     CROP_PROGRESS_COLUMNS, "pct_harvested"),
    ("silver_fgis", "jobs.batch.fgis_silver_task", FGIS_COLUMNS, "exports_mt_ctd"),
    ("silver_fnc_colombia_monthly", "jobs.batch.fnc_colombia_silver_task",
     MONTHLY_OUTPUT_COLUMNS, "exports_value_usd_m"),
    ("silver_fnc_colombia_area_department", "jobs.batch.fnc_colombia_silver_task",
     AREA_OUTPUT_COLUMNS, "area_ha"),
    ("silver_fnc_colombia_exports_port_type", "jobs.batch.fnc_colombia_silver_task",
     EXPORTS_PORT_TYPE_OUTPUT_COLUMNS, "exports_value_usd"),
    ("silver_modis_ndvi", "jobs.batch.modis_ndvi_bronze_to_silver_task",
     MODIS_COLUMNS, "ndvi_z_score"),
]
IDS = [s[0] for s in SIBLINGS]

_SAMPLE = {
    "string": "x",
    "int64": 7,
    "float64": 1.5,
    "date32[day]": dt.date(2020, 1, 1),
    "bool": True,
    "timestamp[us]": pd.Timestamp("2020-01-01"),
}


def _target_types(contract: dict) -> dict[str, str]:
    out = {c["name"]: c["target_arrow_type"] for c in contract.get("physical_columns", [])}
    for pk in contract.get("partition_keys") or []:
        out.setdefault(pk["name"], "int64" if pk["glue_type"] in ("int", "bigint") else "string")
    return out


def _frame(contract: dict, columns: list[str], rows: int = 6) -> pd.DataFrame:
    """One partition body as a producer hands it over: every declared column, populated."""
    types = _target_types(contract)
    data = {}
    for col in columns:
        token = types[col]
        base = _SAMPLE[token]
        if token == "float64":
            data[col] = [base + i for i in range(rows)]
        elif token == "int64":
            data[col] = [base + i for i in range(rows)]
        elif token == "string":
            data[col] = [f"{col}_{i}" for i in range(rows)]
        else:
            data[col] = [base] * rows
    return pd.DataFrame(data)[columns]


@pytest.fixture(scope="module")
def registry():
    return load_registry()


# ---------------------------------------------------------------------------
# 1. THE DEFECT, and the pin, on every sibling.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("table,module,columns,measure", SIBLINGS, ids=IDS)
def test_the_unpinned_encode_would_write_an_absent_measure_as_arrow_null(
        registry, table, module, columns, measure):
    """Reproduce the ORIGINAL failure on each sibling's own shape, so the fix below is measured
    against the real thing: an object-dtype all-NA column -- what a ``pd.NA`` backfill produces for
    a series the source did not publish for this group -- becomes arrow ``null``, physical INT32,
    with NO Statistics struct."""
    df = _frame(registry.table(table), list(columns))
    df[measure] = pd.NA                                   # the transform's backfill, uncast
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    md = pq.ParquetFile(io.BytesIO(buf.getvalue())).metadata
    names = [md.schema.column(i).name for i in range(md.num_columns)]
    assert md.schema.column(names.index(measure)).physical_type == "INT32"
    assert md.row_group(0).column(names.index(measure)).statistics is None
    stat = file_column_stat(md, measure)
    assert stat is not None and stat.has_stats is False


@pytest.mark.parametrize("table,module,columns,measure", SIBLINGS, ids=IDS)
def test_the_pinned_encode_writes_the_contract_type_with_statistics(
        registry, table, module, columns, measure):
    """The pin, through each task's OWN ``_partition_body`` (the call site the publisher uses), not
    just through the shared helper: the absent measure comes back as the contract's declared type
    with a real, countable ``null_count``."""
    contract = registry.table(table)
    task = importlib.import_module(module)
    df = _frame(contract, list(columns))
    df[measure] = pd.NA
    md = pq.ParquetFile(io.BytesIO(task._partition_body(df, contract))).metadata
    names = [md.schema.column(i).name for i in range(md.num_columns)]
    assert names == list(columns), "the on-disk column ORDER must stay the body's own"
    declared = _target_types(contract)[measure]
    expected_physical = {"float64": "DOUBLE", "int64": "INT64", "string": "BYTE_ARRAY"}[declared]
    assert md.schema.column(names.index(measure)).physical_type == expected_physical
    stat = file_column_stat(md, measure)
    assert stat.has_stats is True
    assert stat.null_count == stat.total_rows == len(df)


@pytest.mark.parametrize("table,module,columns,measure", SIBLINGS, ids=IDS)
def test_the_pin_relabels_the_census_kind_it_does_not_clear_it(
        registry, table, module, columns, measure):
    """The RCA's key finding, carried to the siblings: the pin is a TYPE fix, not a gate fix. An
    absent series is hard BEFORE the pin (stats_unavailable) and hard AFTER it (all_nan). Anyone
    reading this sweep as "the rewrite makes a red go away" is wrong -- what narrates a real absence
    is the registry's ``value_column_absent_groups`` declaration."""
    contract = registry.table(table)
    task = importlib.import_module(module)
    df = _frame(contract, list(columns))
    df[measure] = pd.NA

    unpinned = io.BytesIO()
    df.to_parquet(unpinned, index=False, engine="pyarrow", compression="snappy")
    before = census_column(
        [file_column_stat(pq.ParquetFile(io.BytesIO(unpinned.getvalue())).metadata, measure)],
        measure)
    after = census_column(
        [file_column_stat(pq.ParquetFile(io.BytesIO(task._partition_body(df, contract))).metadata,
                          measure)], measure)
    assert before.files_with_stats == 0 and before.all_nan is True    # stats_unavailable shape
    assert after.files_with_stats == 1 and after.all_nan is True      # all_nan shape -- still hard
    # ...and the fraction the floor reads does NOT move, which is the RCA correction restated.
    assert before.nonnull_fraction == after.nonnull_fraction == 0.0


@pytest.mark.parametrize("table,module,columns,measure", SIBLINGS, ids=IDS)
def test_a_populated_partition_round_trips_every_value(registry, table, module, columns, measure):
    """The pin must be inert where the data was already fine -- which, measured on 2026-09-09, is
    EVERY canonical object of all four siblings."""
    contract = registry.table(table)
    task = importlib.import_module(module)
    df = _frame(contract, list(columns))
    back = pq.read_table(io.BytesIO(task._partition_body(df, contract))).to_pandas()
    assert list(back.columns) == list(columns)
    for col in columns:
        assert back[col].tolist() == df[col].tolist(), col


# ---------------------------------------------------------------------------
# 2. FAIL CLOSED. A pin that silently widens is no pin.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("table,module,columns,measure", SIBLINGS, ids=IDS)
def test_a_body_missing_a_contract_column_refuses_the_write(registry, table, module, columns, measure):
    contract = registry.table(table)
    task = importlib.import_module(module)
    df = _frame(contract, list(columns)).drop(columns=[measure])
    with pytest.raises(ValueError, match=r"missing=\['%s'\]" % measure):
        task._partition_body(df, contract)


@pytest.mark.parametrize("table,module,columns,measure", SIBLINGS, ids=IDS)
def test_an_undeclared_body_column_refuses_the_write(registry, table, module, columns, measure):
    contract = registry.table(table)
    task = importlib.import_module(module)
    df = _frame(contract, list(columns))
    df["surprise_col"] = 1
    with pytest.raises(ValueError, match=r"extra=\['surprise_col'\]"):
        task._partition_body(df, contract)


def test_an_unmapped_partition_key_type_refuses_rather_than_guessing(registry):
    """A projected key that rides in the body is why the flat ``encode_parquet`` cannot be reused;
    a key whose glue type has no mapping must RAISE. Guessing a type is how the defect was born."""
    contract = dict(registry.table("silver_fgis"))
    contract["partition_keys"] = [
        {"name": "leviathan_slug", "glue_type": "string", "projected": True},
        {"name": "marketing_year", "glue_type": "decimal(10,2)", "projected": True},
    ]
    with pytest.raises(ValueError, match="unmapped partition-key glue type"):
        pa_schema_for_partitioned_body(contract, list(FGIS_COLUMNS))


def test_a_path_only_partition_key_is_not_demanded_in_the_body(registry):
    """``commodity`` lives only in the object path for the projected tables; the adapter must not
    demand it in the body (the fnc/crop_progress shape), while ``year`` IS in the body and must be
    typed from ``partition_keys``."""
    contract = registry.table("silver_nass_crop_progress")
    schema = pa_schema_for_partitioned_body(contract, list(CROP_PROGRESS_COLUMNS))
    assert "commodity" not in schema.names
    assert schema.field("year").type == pa.int64()
    assert schema.field("year").nullable is False
    assert schema.names == list(CROP_PROGRESS_COLUMNS)


def test_a_flat_table_needs_no_partition_keys_at_all(registry):
    """``silver_modis_ndvi`` is FLAT: the adapter reduces to the declared physical columns in the
    body's own order, and still fails closed."""
    contract = registry.table("silver_modis_ndvi")
    assert not (contract.get("partition_keys") or [])
    schema = pa_schema_for_partitioned_body(contract, MODIS_COLUMNS)
    assert schema.names == MODIS_COLUMNS


# ---------------------------------------------------------------------------
# 3. ONE adapter, not six copies.
# ---------------------------------------------------------------------------
def test_every_producer_encodes_through_the_one_shared_adapter(registry):
    """nass_annual's ``_body_schema`` was LIFTED into ``pa_schema_for_partitioned_body``; its
    wrapper must still answer identically, or the estate has two implementations again."""
    task = importlib.import_module("jobs.batch.nass_annual_silver_task")
    contract = registry.table("silver_nass_annual")
    body = [c["name"] for c in contract["physical_columns"]]
    body.insert(3, "year")                       # the projected key rides in the body
    assert task._body_schema(contract, body).equals(
        pa_schema_for_partitioned_body(contract, body))


@pytest.mark.parametrize("table,module,columns,measure", SIBLINGS, ids=IDS)
def test_each_task_body_is_byte_identical_to_the_shared_adapter(
        registry, table, module, columns, measure):
    """No sibling may quietly grow its own encode: the task function and the shared adapter must
    produce the SAME bytes for the same frame."""
    contract = registry.table(table)
    task = importlib.import_module(module)
    df = _frame(contract, list(columns))
    assert task._partition_body(df, contract) == encode_partitioned_body(df, contract)


# ---------------------------------------------------------------------------
# 4. The registry says so.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("table", IDS + ["silver_nass_annual"])
def test_the_registry_declares_the_writer_pinned(registry, table):
    assert registry.table(table)["writer_schema_pinned"] is True, (
        "generated from WRITER_SCHEMA_PINNED in scripts/silver/gen_registry_from_baseline.py; the "
        "flag is the truthful statement that the producer passes an explicit schema")
