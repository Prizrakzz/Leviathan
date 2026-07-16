"""Wave-1 regression: the SAGIS weekly-exports silver Batch task must build a LIVE S3 client on the
shadow/canonical publish path.

The ``s3_client=None`` defect (hard-wired into ``build_flat_publish`` calls, correct only for
dry-run) bit two producer families: a ``--publish-mode shadow`` run reached the publisher's staging
loop and crashed with ``'NoneType' object has no attribute 'put_object'``. The fix builds the client
conditionally (``None if dry-run else get_thread_local_s3_client``); this test locks ``main()``:

  * shadow builds EXACTLY one live client and stages under ``_shadow/`` (canonical untouched);
  * dry-run builds NO client (nothing written);
  * argparse accepts ``--publish-mode shadow``.

Pure/hermetic: an in-memory :class:`FakeS3` and a recording client factory replace all AWS. The
loader + transform are stubbed so no real bronze/S3/network is touched.
"""
from __future__ import annotations

import sys

import pandas as pd

from jobs.batch import sagis_weekly_exports_silver_task as task
from leviathan.storage.paths import silver_sagis_weekly_key
from tests.unit.silver.conftest import FakeS3

CANONICAL_KEY = silver_sagis_weekly_key("exports")


# --------------------------------------------------------------------------- canned silver frame
def _weekly_df() -> pd.DataFrame:
    """EXACTLY the ``silver_sagis_weekly_exports`` physical columns; the three value columns
    (prog_exports_mt, pct_of_prior_yr, z_vs_3yr_avg) are fully non-null so the 0.5 floor clears.
    """
    return pd.DataFrame({
        "season": ["2023-24", "2023-24"],
        "crop": ["maize", "maize"],
        "week_number": [10, 11],
        "week_ending": ["2023-12-08", "2023-12-15"],
        "prog_exports_mt": [125_000.0, 138_000.0],
        "pct_of_prior_yr": [104.5, 110.2],
        "z_vs_3yr_avg": [0.42, 0.61],
        "source": ["sagis_weekly", "sagis_weekly"],
    })


def _wire(monkeypatch):
    """Stub env + loader + transform + the S3 client factory. Returns ``(fake_s3, factory_calls)``."""
    monkeypatch.setattr(task, "load_env", lambda *a, **k: None)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(task, "load_rows", lambda *a, **k: [])           # no S3 read in the loader
    monkeypatch.setattr(task, "transform_weekly_exports", lambda *a, **k: _weekly_df())
    s3 = FakeS3()
    calls: list[str] = []

    def _factory(region):
        calls.append(region)
        return s3

    # main() resolves ``get_thread_local_s3_client`` via a call-time import from leviathan.storage.s3,
    # so patch the source-module name (patching the task attribute would not take effect).
    monkeypatch.setattr("leviathan.storage.s3.get_thread_local_s3_client", _factory)
    return s3, calls


def test_shadow_builds_one_live_client_and_stages_to_shadow(monkeypatch):
    s3, calls = _wire(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["prog", "--bucket", "leviathan-test",
                                      "--publish-mode", "shadow"])

    rc = task.main()

    assert rc == 0
    assert calls == ["us-east-1"]                     # exactly one live client, for the publish
    keys = s3.keys()
    assert any("_shadow" in k for k in keys)          # object staged shadow-first
    assert CANONICAL_KEY not in keys                  # canonical untouched in shadow mode


def test_dry_run_builds_no_client_and_writes_nothing(monkeypatch):
    s3, calls = _wire(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["prog", "--bucket", "leviathan-test",
                                      "--publish-mode", "dry-run"])

    rc = task.main()

    assert rc == 0
    assert calls == []                                # dry-run stages nothing -> no client built
    assert s3.keys() == []                            # nothing written anywhere


def test_argparse_accepts_publish_mode_shadow(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--bucket", "leviathan-test",
                                      "--publish-mode", "shadow"])
    args = task._parse_args()
    assert args.publish_mode == "shadow"
    assert args.bucket == "leviathan-test"


# ------------------------------------------------------------------ live-bronze loader mapping
def _live_bronze_df() -> pd.DataFrame:
    """EXACTLY the governed bronze imp_exp_progressive schema (SB-F042 b2s parser output).
    The first live Wave-1 canary caught the loader mapping fixture-only keys
    (prog_exports_mt / is_total) that do not exist here -> all-null value column ->
    publisher non-null floor fail. Both flows present so the exports filter is exercised."""
    return pd.DataFrame({
        "season": ["2010-11"] * 4,
        "dataset": ["imp_exp_progressive"] * 4,
        "crop": ["wheat"] * 4,
        "grade": ["total"] * 4,
        "flow_type": ["imports", "exports", "imports", "exports"],
        "week_number": [1, 1, 2, 2],
        "week_ending": ["2 - 8 Oct 2010", "2 - 8 Oct 2010", "9 - 15 Oct", "9 - 15 Oct"],
        "weekly_mt": [62479.0, 3573.0, 38829.0, 4100.0],
        "prog_total_mt": [62479.0, 3573.0, 101308.0, 7673.0],
        "source": ["sagis_weekly"] * 4,
    })


def test_load_rows_maps_live_bronze_schema_and_filters_to_exports(monkeypatch):
    df = _live_bronze_df()
    monkeypatch.setattr("leviathan.storage.s3.get_thread_local_s3_client", lambda r: object())
    monkeypatch.setattr("leviathan.storage.s3.list_s3_keys",
                        lambda *a, **k: ["bronze/.../part-000.parquet"])
    import io as _io
    buf = _io.BytesIO(); df.to_parquet(buf)
    monkeypatch.setattr("leviathan.storage.s3.s3_download_with_retry",
                        lambda *a, **k: buf.getvalue())

    rows = task.load_rows("bucket", "us-east-1")
    # imports rows dropped; exports rows mapped with a REAL prog value
    assert len(rows) == 2
    assert all(r.prog_exports_mt is not None for r in rows)
    assert [r.prog_exports_mt for r in rows] == [3573.0, 7673.0]
    assert all(r.is_total for r in rows)  # grade == 'total'


def test_row_to_export_reads_prog_total_mt_and_grade(monkeypatch):
    rec = _live_bronze_df().to_dict("records")[1]  # the exports row
    row = task._row_to_export(rec)
    assert row.prog_exports_mt == 3573.0
    assert row.is_total is True
    assert row.season == "2010-11" and row.crop == "wheat" and row.week_number == 1
