"""W7: the `_shadow/` + `_manifests/` fence on the pg-mirror loader -- the 2x miscount hazard.

The F015 publisher stages every object under `<root>/_shadow/` before promoting it and persists run
manifests under `<root>/_manifests/`, so a table root holds a byte-identical twin of every canonical
object under the SAME prefix. `gold/pattern_records/` is the live case: 156 canonical `as_of_date=`
objects + 156 shadow copies + 3 manifests. A prefix scan that does not exclude them reads 312 files /
78,312 rows instead of 156 / 39,156 -- exactly 2x, silently. That matters here specifically because
`load_pg_numbers` builds the pg mirror the serving numbers lane reads: a doubled denominator turns
"fired on 9 of 156 sweeps" into a confidently-delivered wrong number.

These pins are hermetic (a real parquet layout in tmp_path + a fake S3 pager); no AWS, no Glue, no pg.
"""
from __future__ import annotations

import pyarrow as pa
import pyarrow.dataset as pads
import pyarrow.parquet as pq
import pytest

lpn = pytest.importorskip("jobs.utils.load_pg_numbers", reason="loader imports leviathan.common")


def _ledger_layout(root, *, manifests: bool = True):
    """A miniature gold/pattern_records/: 2 canonical partitions + their shadow twins (+ manifests)."""
    tbl = pa.table({"contract": ["corn_cbot"], "fired": [1]})
    for rel in ("as_of_date=2026-07-25/pattern_records.parquet",
                "as_of_date=2026-07-26/pattern_records.parquet",
                "_shadow/as_of_date=2026-07-25/pattern_records.parquet",
                "_shadow/as_of_date=2026-07-26/pattern_records.parquet"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(tbl, p)
    if manifests:
        (root / "_manifests").mkdir(parents=True, exist_ok=True)
        (root / "_manifests" / "run.json").write_text('{"run_id": "x"}')
    return pads.partitioning(pa.schema([("as_of_date", pa.string())]), flavor="hive")


def test_hidden_prefixes_constant_covers_shadow_and_manifests():
    assert set(lpn._HIDDEN_PREFIXES) == {"_", "."}
    for d in ("_shadow", "_manifests", "_staging"):
        assert d.startswith(tuple(lpn._HIDDEN_PREFIXES))


def test_fenced_scan_reads_canonical_only_and_unfenced_doubles(tmp_path):
    """The hazard and the fence, side by side, on a real dataset scan."""
    root = tmp_path / "pattern_records"
    part = _ledger_layout(root, manifests=False)      # manifests off: the UNFENCED read must not just die

    fenced = pads.dataset(str(root), format="parquet", partitioning=part,
                          ignore_prefixes=lpn._HIDDEN_PREFIXES)
    assert len(fenced.files) == 2 and fenced.count_rows() == 2

    unfenced = pads.dataset(str(root), format="parquet", partitioning=part, ignore_prefixes=[])
    assert len(unfenced.files) == 4 and unfenced.count_rows() == 4      # EXACTLY 2x, no error, no warning
    assert any("_shadow" in f for f in unfenced.files)


def test_manifests_break_an_unfenced_scan_outright(tmp_path):
    """The other half of the hazard: `_manifests/*.json` is not parquet, so dropping the fence is not
    merely a miscount on some layouts -- it is a hard failure on this one."""
    root = tmp_path / "pattern_records"
    part = _ledger_layout(root, manifests=True)
    assert pads.dataset(str(root), format="parquet", partitioning=part,
                        ignore_prefixes=lpn._HIDDEN_PREFIXES).count_rows() == 2
    with pytest.raises(pa.lib.ArrowInvalid):
        pads.dataset(str(root), format="parquet", partitioning=part, ignore_prefixes=[])


def test_probe_body_columns_skips_shadow_and_manifest_keys(monkeypatch):
    """The RAW-LIST reader, where boto3 offers no default protection at all. It must reach past both
    hidden trees to the first CANONICAL parquet -- not schema-probe the shadow twin."""
    import boto3

    keys = ["gold/pattern_records/_manifests/run.json",
            "gold/pattern_records/_shadow/as_of_date=2026-07-25/pattern_records.parquet",
            "gold/pattern_records/as_of_date=2026-07-25/pattern_records.parquet"]

    class _Pager:
        def paginate(self, **kw):
            assert kw["Prefix"] == "gold/pattern_records/"
            return [{"Contents": [{"Key": k} for k in keys]}]

    class _S3:
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return _Pager()

    probed: list[str] = []

    def fake_dataset(uri, **kw):
        probed.append(uri)
        class _D:  # noqa: E306
            schema = pa.schema([("contract", pa.string())])
        return _D()

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _S3())
    monkeypatch.setattr(pads, "dataset", fake_dataset)

    cols = lpn._probe_body_columns("s3://leviathan-dev-shahem-001/gold/pattern_records")
    assert cols == {"contract"}
    assert probed == ["s3://leviathan-dev-shahem-001/gold/pattern_records/"
                      "as_of_date=2026-07-25/pattern_records.parquet"]
    assert not any("_shadow" in u or "_manifests" in u for u in probed)


def test_both_dataset_openers_pass_the_fence():
    """`load_table` builds its dataset twice (default read, then the Glue-derived unified retry). Both
    must carry the fence -- a fence on one branch only is a fence that fails exactly when a schema
    divergence sends the loader down the other one."""
    import inspect
    src = inspect.getsource(lpn.load_table)
    opens = [ln for ln in src.splitlines() if "pads.dataset(" in ln]
    assert len(opens) == 2, f"dataset open sites changed ({len(opens)}); re-check the W7 fence"
    assert src.count("ignore_prefixes=_HIDDEN_PREFIXES") == 2
