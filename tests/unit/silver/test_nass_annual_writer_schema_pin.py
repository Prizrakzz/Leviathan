"""NASS GATE RCA (2026-09-09), A2: the ``silver_nass_annual`` writer's INV-2 schema pin.

THE DEFECT, MEASURED. ``jobs/batch/nass_annual_silver_task._partition_body`` wrote every
``(commodity, year)`` object with a bare ``df.to_parquet(engine="pyarrow")`` and NO schema
argument, deliberately bypassing ``leviathan.silver.flat_producer`` -- whose
``pa_schema_from_contract`` docstring exists to prevent exactly this ("pinning it means an all-null
measure column can never silently become arrow ``null``"). Arrow therefore INFERRED the type per
group, and a group holding zero non-NA values in a measure column was written as arrow ``null``:
physical INT32 with no Statistics struct at all. A full footer scan of every canonical object
(1,206 files, 26,081 rows, 2026-09-09) found 475 such column-instances across seven commodities --
311 of ``area_planted_ha``, 162 of ``yield_t_ha``, 2 of ``production_mt`` -- of which the 322
cottonseed yield/planted-area instances made the V001 census raise KIND_STATS_UNAVAILABLE and
refused the usda_nass chain three consecutive Tuesdays (2026-08-25 / 09-01 / 09-08).

WHAT THIS FILE PINS, and what it deliberately does not claim. The pin is a TYPE fix, not the gate
fix: a double all-null column trips KIND_ALL_NAN where an arrow-null one tripped
KIND_STATS_UNAVAILABLE, and both are hard. The registry's ``value_column_absent_groups``
declaration (``test_value_census.py``) is what narrates cottonseed's absence; this pin is what
stops the census being blind to the column's physical TYPE.

A CORRECTION TO THE RCA, measured here rather than inherited. The RCA predicted the pin would also
"kill the ``area_planted_ha`` sampler landmine (a null-typed file contributes rows-but-no-nulls to
the fraction)". It does not, and ``test_the_pin_does_not_move_any_nonnull_fraction`` proves it:
``file_column_stat`` skips a ``None`` statistics object, so a null-typed file books its rows into
``total_rows`` with ``effective_nonnull`` 0 -- and after the pin the SAME file is an all-null double
that books its rows with ``effective_nonnull`` 0 again. What the pin actually retires is the
STATS_UNAVAILABLE COIN-FLIP (a group hard-fails or not depending on whether its 3-file sample
happens to include one double-typed file) and it makes ``null_count`` honest. The floor risk the RCA
measured beside it -- corn 0.7259, cotton 0.76, rice 0.6667 against a 0.5 floor, margins that are a
sampling accident -- is untouched by this pin and stays on the docket.

AWS-free, no network: local parquet round-trips through the real writer function plus the tracked
contract. The live canonical bytes do NOT change until an owner-gated ``--force-overwrite`` rewrite
runs; these tests pin the CODE that rewrite will use.
"""
from __future__ import annotations

import importlib
import io

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from leviathan.silver.registry import load_registry
from leviathan.silver.value_census import (
    KIND_ALL_NAN,
    KIND_STATS_UNAVAILABLE,
    apply_absent_group_waiver,
    census_column,
    evaluate_gate,
    file_column_stat,
)

task = importlib.import_module("jobs.batch.nass_annual_silver_task")

_TABLE = "silver_nass_annual"
_BODY = ["leviathan_slug", "country", "state", "year", "marketing_year", "area_planted_ha",
         "area_harvested_ha", "yield_t_ha", "production_mt", "area_planted_cv_pct",
         "area_harvested_cv_pct", "yield_cv_pct", "production_cv_pct", "source", "release_date"]


@pytest.fixture(scope="module")
def contract() -> dict:
    return load_registry().table(_TABLE)


def _cottonseed_frame(rows: int = 12) -> pd.DataFrame:
    """One cottonseed partition as the transform hands it over: the measure columns NASS never
    publishes for this slug arrive as ``pd.NA`` on an OBJECT column, because
    ``usda_nass_annual.py`` backfills any OUTPUT_COLUMNS entry the shard omitted. That object dtype
    is what arrow inferred as ``null``."""
    df = pd.DataFrame({
        "leviathan_slug": ["cottonseed"] * rows,
        "country": ["US"] * rows,
        "state": [f"STATE_{i}" for i in range(rows)],
        "year": [1866] * rows,
        "marketing_year": [1866] * rows,
        "production_mt": [16329.32532 + i for i in range(rows)],
        "source": ["usda_nass"] * rows,
        "release_date": ["1867-02-01"] * rows,
    })
    for col in ("area_planted_ha", "area_harvested_ha", "yield_t_ha", "area_planted_cv_pct",
                "area_harvested_cv_pct", "yield_cv_pct", "production_cv_pct"):
        df[col] = pd.NA                       # the transform's own backfill -> object dtype
    return df[_BODY]


def _footer(body: bytes):
    return pq.ParquetFile(io.BytesIO(body)).metadata


def _types(md) -> dict[str, str]:
    return {md.schema.column(i).name: md.schema.column(i).physical_type
            for i in range(md.num_columns)}


# ---------------------------------------------------------------------------
# 1. THE DEFECT, reproduced through the exact call the writer used to make.
# ---------------------------------------------------------------------------
def test_the_unpinned_encode_is_what_produced_a_column_with_no_statistics():
    """Pin the OLD behaviour so the fix below is measured against the real failure. This is the
    literal line that shipped: ``df.to_parquet(buf, index=False, engine="pyarrow", ...)``."""
    buf = io.BytesIO()
    _cottonseed_frame().to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    md = _footer(buf.getvalue())
    # the two columns the gate refused on, exactly as the live footer reads them
    assert _types(md)["yield_t_ha"] == "INT32"          # arrow `null` on disk
    assert _types(md)["area_planted_ha"] == "INT32"
    assert md.row_group(0).column(
        [md.schema.column(i).name for i in range(md.num_columns)].index("yield_t_ha")
    ).statistics is None                                 # NO Statistics struct at all
    stat = file_column_stat(md, "yield_t_ha")
    assert stat is not None and stat.has_stats is False


# ---------------------------------------------------------------------------
# 2. THE PIN.
# ---------------------------------------------------------------------------
def test_the_pinned_encode_writes_the_contract_type_with_real_statistics(contract):
    md = _footer(task._partition_body(_cottonseed_frame(), contract))
    types = _types(md)
    # every declared measure is the contract's float64 -> DOUBLE, whatever the data holds
    for col in ("area_planted_ha", "area_harvested_ha", "yield_t_ha", "production_mt"):
        assert types[col] == "DOUBLE", (col, types[col])
    names = [md.schema.column(i).name for i in range(md.num_columns)]
    assert names == _BODY                                # on-disk column ORDER is unchanged
    for col in ("yield_t_ha", "area_planted_ha"):
        stat = file_column_stat(md, col)
        assert stat.has_stats is True                    # ...and the footer now CARRIES statistics
        assert stat.null_count == stat.total_rows == 12   # an honest, countable, all-null column
    # the partition key that rides in the body keeps its type and its NOT NULL
    assert types["year"] == "INT64"
    assert md.schema.column(names.index("year")).name == "year"


def test_the_pin_moves_the_census_kind_from_stats_unavailable_to_all_nan(contract):
    """The RCA's key finding, pinned: rewriting under the schema does NOT make the red go away, it
    RELABELS it. Anyone who reads this pin as 'the rewrite fixes the gate' is wrong, and the
    declaration is what actually clears it -- for BOTH shapes."""
    vc = list(contract["value_columns"])
    floor = contract["min_nonnull_frac"]
    decl = contract["value_column_absent_groups"]

    old = io.BytesIO()
    _cottonseed_frame().to_parquet(old, index=False, engine="pyarrow", compression="snappy")
    for body, expected in ((old.getvalue(), KIND_STATS_UNAVAILABLE),
                           (task._partition_body(_cottonseed_frame(), contract), KIND_ALL_NAN)):
        md = _footer(body)
        cen = {c: census_column([file_column_stat(md, c)], c) for c in vc}
        rows = evaluate_gate(_TABLE, cen, vc, floor)
        absent = {r.column: r.kind for r in rows}
        assert absent.get("yield_t_ha") == expected and absent.get("area_planted_ha") == expected
        # BOTH shapes are hard without the declaration, and BOTH are demoted with it.
        kept, warned = apply_absent_group_waiver(rows, "commodity=cottonseed", decl, vc)
        assert kept == [] and len(warned) == 3
        # ...and neither is demoted for a group nobody declared.
        assert len(apply_absent_group_waiver(rows, "commodity=corn_cbot", decl, vc)[0]) == 3


def test_the_pin_does_not_move_any_nonnull_fraction(contract):
    """THE RCA CORRECTION, measured. Two files of one commodity -- an early-era partition where the
    column is arrow `null` and a modern one where it is a populated double -- is exactly the corn
    `area_planted_ha` shape. Re-encoding under the pin leaves `nonnull_fraction` IDENTICAL, because
    an all-null column contributes zero `effective_nonnull` whether it is arrow-null (statistics
    skipped) or a typed double (null_count == total_rows). Only `files_with_stats` and `null_count`
    move -- which is the whole benefit and the whole limit of the pin.

    Verified against the real objects too (commodity=corn_cbot year=1866 + year=2026,
    area_planted_ha): 0.569767 before, 0.569767 after; files_with_stats 1/2 -> 2/2;
    null_count 1 -> 37."""
    col = "area_planted_ha"
    early = _cottonseed_frame(rows=36)                       # column all-NA -> arrow null
    modern = _cottonseed_frame(rows=50)
    modern[col] = [float(i) for i in range(49)] + [None]      # one honest null, 49 real values

    def frac(bodies):
        mds = [_footer(b) for b in bodies]
        c = census_column([file_column_stat(md, col) for md in mds], col)
        return round(c.nonnull_fraction, 6), c.files_with_stats, c.null_count

    def unpinned(df):
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        return buf.getvalue()

    before = frac([unpinned(early), unpinned(modern)])
    after = frac([task._partition_body(early, contract), task._partition_body(modern, contract)])
    assert before[0] == after[0] == round(49 / 86, 6), (before, after)   # THE FRACTION DOES NOT MOVE
    assert before[1:] == (1, 1) and after[1:] == (2, 37)                 # stats + nulls become honest


def test_a_populated_partition_round_trips_unchanged(contract):
    """The pin must be inert where the data was already fine -- 1,204 of the 1,206 canonical objects
    write ``production_mt`` as a real double today and must keep every value."""
    df = _cottonseed_frame()
    df["yield_t_ha"] = [0.5 + i / 10 for i in range(len(df))]
    back = pq.read_table(io.BytesIO(task._partition_body(df, contract))).to_pandas()
    assert back["yield_t_ha"].tolist() == df["yield_t_ha"].tolist()
    assert back["production_mt"].tolist() == df["production_mt"].tolist()
    assert back["state"].tolist() == df["state"].tolist()
    assert list(back.columns) == _BODY


# ---------------------------------------------------------------------------
# 3. FAIL CLOSED. A pinned writer that silently widens is no pin at all.
# ---------------------------------------------------------------------------
def test_a_body_missing_a_contract_column_refuses_the_write(contract):
    df = _cottonseed_frame().drop(columns=["production_mt"])
    with pytest.raises(ValueError, match=r"missing=\['production_mt'\]"):
        task._partition_body(df, contract)


def test_an_undeclared_body_column_refuses_the_write(contract):
    df = _cottonseed_frame()
    df["surprise_col"] = 1
    with pytest.raises(ValueError, match=r"extra=\['surprise_col'\]"):
        task._partition_body(df, contract)


def test_a_null_in_a_not_null_contract_column_refuses_the_write(contract):
    """``state`` is the one body column the contract marks nullable=False. Measured over all 1,206
    canonical objects it carries ZERO nulls, so the pin cannot refuse the live rewrite -- but the
    day it would, it must refuse rather than write a silently-widened object."""
    df = _cottonseed_frame()
    df.loc[0, "state"] = None
    with pytest.raises(Exception):
        task._partition_body(df, contract)


def test_an_unmapped_partition_key_type_refuses_rather_than_guessing(contract):
    """The body carries the projected ``year`` key, which is why the flat ``encode_parquet`` cannot
    be used verbatim. A key whose glue type this module has no mapping for must RAISE -- guessing a
    partition key's type is how the original defect was born."""
    c = dict(contract)
    c["partition_keys"] = [{"name": "commodity", "glue_type": "string", "projected": True},
                           {"name": "year", "glue_type": "decimal(10,2)", "projected": True}]
    with pytest.raises(ValueError, match="unmapped partition-key glue type"):
        task._body_schema(c, _BODY)


# ---------------------------------------------------------------------------
# 4. The declaration side of the pin: the registry says the writer is pinned.
# ---------------------------------------------------------------------------
def test_the_registry_declares_the_writer_pinned(contract):
    assert contract["writer_schema_pinned"] is True, (
        "the flag is the truthful statement that _partition_body passes an explicit schema; it is "
        "generated from WRITER_SCHEMA_PINNED in gen_registry_from_baseline.py")


def test_the_schema_is_built_from_the_contract_not_from_the_data(contract):
    """The whole point: the fields come from ``target_arrow_type``, so an all-NA frame and a fully
    populated one produce the BYTE-IDENTICAL schema."""
    empty = _cottonseed_frame()
    full = _cottonseed_frame()
    for col in ("area_planted_ha", "area_harvested_ha", "yield_t_ha"):
        full[col] = 1.0
    assert task._body_schema(contract, _BODY).equals(task._body_schema(contract, _BODY))
    a = pq.read_schema(io.BytesIO(task._partition_body(empty, contract)))
    b = pq.read_schema(io.BytesIO(task._partition_body(full, contract)))
    assert a.remove_metadata().equals(b.remove_metadata())
    assert a.field("yield_t_ha").type == pa.float64()
