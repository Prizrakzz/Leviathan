"""pg-mirror loader — vintage-layout partitioning (BF-W2 live-proven clash class).

silver_esr_compact post-migration carries as_of_date BOTH as a Glue partition key and as a physical
column inside every parquet body (the pg mirror needs the body column; the directory segment is
`as_of=`). pyarrow dataset-schema unification REJECTS a declared partition field that clashes with a
body column's arrow type (string vs large_string) — so the loader must exclude body-present keys from
the partitioning schema and serve their values from the bodies. These tests pin that pyarrow behavior
locally: if an upgrade changes it, CI learns before prod does.
"""
from __future__ import annotations

import pyarrow as pa
import pyarrow.dataset as pads
import pyarrow.parquet as pq
import pytest


def _write_vintage_tree(tmp_path):
    """commodity={slug}/as_of={date}/part-000.parquet with as_of_date as a large_string BODY column
    (pandas-writer arrow type — the exact live shape)."""
    for slug, vintage, week, val in [
        ("corn_cbot", "20260524", "2026-05-22", 510.0),
        ("corn_cbot", "20260712", "2026-07-02", 640.0),
    ]:
        d = tmp_path / f"commodity={slug}" / f"as_of={vintage}"
        d.mkdir(parents=True)
        t = pa.table({
            "commodity_name": pa.array([slug], pa.large_string()),
            "week_ending_date": pa.array([week], pa.large_string()),
            "weekly_exports_1000mt": pa.array([val], pa.float64()),
            "as_of_date": pa.array([vintage], pa.large_string()),
        })
        pq.write_table(t, d / "part-000.parquet")
    return tmp_path


def test_body_duplicated_partition_key_clashes_when_declared(tmp_path):
    # The ASSUMPTION guard: declaring as_of_date (string) in the partition schema while the bodies
    # carry it as large_string fails dataset-schema unification. If a pyarrow upgrade makes this
    # pass, re-evaluate the loader's exclusion rule before trusting either behavior.
    root = _write_vintage_tree(tmp_path)
    part = pads.partitioning(
        pa.schema([("commodity", pa.string()), ("as_of_date", pa.string())]), flavor="hive")
    with pytest.raises(Exception, match="as_of_date"):
        pads.dataset(str(root), format="parquet", partitioning=part).scanner(
            columns=["as_of_date"]).to_table()


def test_excluding_body_present_key_scans_vintage_layout(tmp_path):
    # The loader's rule: partition schema = Glue keys MINUS body-present keys. The unparsed `as_of=`
    # segment is tolerated; as_of_date values come from the bodies; commodity from the directories.
    root = _write_vintage_tree(tmp_path)
    part = pads.partitioning(pa.schema([("commodity", pa.string())]), flavor="hive")
    ds = pads.dataset(str(root), format="parquet", partitioning=part)
    t = ds.scanner(columns=["commodity", "as_of_date", "weekly_exports_1000mt"]).to_table()
    assert t.num_rows == 2
    assert sorted(set(t["as_of_date"].to_pylist())) == ["20260524", "20260712"]
    assert set(t["commodity"].to_pylist()) == {"corn_cbot"}


def test_hidden_prefixes_ignored_by_discovery(tmp_path):
    # pyarrow's default discovery skips '_'/'.'-prefixed segments — the property that keeps
    # _shadow/ and _manifests/ out of the pg mirror. Pinned here because the loader RELIES on it.
    root = _write_vintage_tree(tmp_path)
    shadow = tmp_path / "_shadow" / "commodity=corn_cbot" / "as_of=20260101"
    shadow.mkdir(parents=True)
    pq.write_table(pa.table({"weekly_exports_1000mt": pa.array([999.0])}),
                   shadow / "part-000.parquet")
    part = pads.partitioning(pa.schema([("commodity", pa.string())]), flavor="hive")
    ds = pads.dataset(str(root), format="parquet", partitioning=part)
    t = ds.scanner(columns=["weekly_exports_1000mt"]).to_table()
    assert t.num_rows == 2 and 999.0 not in t["weekly_exports_1000mt"].to_pylist()
