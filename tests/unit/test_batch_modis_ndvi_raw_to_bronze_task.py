"""Unit tests for the MODIS NDVI raw->bronze Batch task thin-contract retrofit (A-Wave-3).

The descriptor invokes this task with NO args, so every argument must default:
  * --run_id  -> MAX run_id partition discovered under raw/weather/source=modis_ndvi/
  * --group   -> 'all' (every commodity_group in configs/sources/modis_ndvi.yaml,
                 falling back to the group= partitions present under the run)
  * --bucket / --aws_region -> $LEVIATHAN_BUCKET / $AWS_REGION

These tests exercise the discovery + arg-parsing seams directly with a stubbed
``list_s3_keys`` (no network -- the F002 guard would otherwise fail-close). Single
named-group / explicit-run_id invocation must keep working unchanged.
"""
from __future__ import annotations

import sys

import pytest

from jobs.batch import modis_ndvi_raw_to_bronze_task as task

_RUN_A = "20260401T120000Z"
_RUN_B = "20260524T183717Z"  # chronologically + lexically the later run


def _stub_list(monkeypatch, keys: list[str]) -> None:
    monkeypatch.setattr(task, "list_s3_keys", lambda *a, **k: list(keys))


# -- argparse defaults ----------------------------------------------------------

def test_parse_args_defaults_are_all_optional(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["modis_r2b"])
    args = task._parse_args()
    assert args.run_id is None
    assert args.group == "all"
    assert args.bucket is None
    assert args.aws_region is None
    assert args.force_overwrite is False


def test_parse_args_single_group_invocation_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", [
        "modis_r2b", "--run_id", _RUN_A, "--group", "grains",
        "--bucket", "test-leviathan", "--aws_region", "us-east-1",
        "--force_overwrite", "true",
    ])
    args = task._parse_args()
    assert args.run_id == _RUN_A
    assert args.group == "grains"
    assert args.bucket == "test-leviathan"
    assert args.aws_region == "us-east-1"
    assert args.force_overwrite is True


# -- run_id discovery (MAX partition, fail-closed) ------------------------------

def test_discover_max_run_id_picks_lexical_max(monkeypatch) -> None:
    _stub_list(monkeypatch, [
        f"raw/weather/source=modis_ndvi/run_id={_RUN_A}/group=grains/x.csv",
        f"raw/weather/source=modis_ndvi/run_id={_RUN_B}/group=grains/y.csv",
        f"raw/weather/source=modis_ndvi/run_id={_RUN_A}/group=sugar_oj/z.csv",
    ])
    assert task._discover_max_run_id("test-leviathan", "us-east-1") == _RUN_B


def test_discover_max_run_id_fails_closed_when_empty(monkeypatch) -> None:
    _stub_list(monkeypatch, [])
    with pytest.raises(FileNotFoundError, match="No MODIS raw run_id partitions"):
        task._discover_max_run_id("test-leviathan", "us-east-1")


# -- group resolution ('all' sentinel + fallbacks) ------------------------------

def test_resolve_groups_single_named_group(monkeypatch) -> None:
    # A named group short-circuits: no S3, no config read.
    monkeypatch.setattr(task, "_groups_from_config", lambda: (_ for _ in ()).throw(AssertionError("no config")))
    assert task._resolve_groups("test-leviathan", _RUN_B, "grains", "us-east-1") == ["grains"]


def test_resolve_groups_all_from_config(monkeypatch) -> None:
    monkeypatch.setattr(task, "_groups_from_config",
                        lambda: ["grains", "oilseeds", "rapeseed_softs", "sugar_oj", "palm_africa"])
    groups = task._resolve_groups("test-leviathan", _RUN_B, "all", "us-east-1")
    assert groups == ["grains", "oilseeds", "rapeseed_softs", "sugar_oj", "palm_africa"]


def test_resolve_groups_all_falls_back_to_raw_partitions(monkeypatch) -> None:
    # Config missing -> derive groups from the run's raw group= partitions.
    monkeypatch.setattr(task, "_groups_from_config", lambda: [])
    _stub_list(monkeypatch, [
        f"raw/weather/source=modis_ndvi/run_id={_RUN_B}/group=grains/a.csv",
        f"raw/weather/source=modis_ndvi/run_id={_RUN_B}/group=palm_africa/b.csv",
        f"raw/weather/source=modis_ndvi/run_id={_RUN_B}/group=grains/c.csv",
    ])
    groups = task._resolve_groups("test-leviathan", _RUN_B, "all", "us-east-1")
    assert groups == ["grains", "palm_africa"]  # sorted + de-duped


def test_resolve_groups_all_fails_closed_when_nothing_found(monkeypatch) -> None:
    monkeypatch.setattr(task, "_groups_from_config", lambda: [])
    _stub_list(monkeypatch, [])
    with pytest.raises(FileNotFoundError, match="no groups found"):
        task._resolve_groups("test-leviathan", _RUN_B, "all", "us-east-1")


def test_discover_groups_from_raw_extracts_partition_values(monkeypatch) -> None:
    _stub_list(monkeypatch, [
        f"raw/weather/source=modis_ndvi/run_id={_RUN_B}/group=sugar_oj/a.csv",
        f"raw/weather/source=modis_ndvi/run_id={_RUN_B}/group=oilseeds/b.csv",
    ])
    assert task._discover_groups_from_raw("test-leviathan", _RUN_B, "us-east-1") == ["oilseeds", "sugar_oj"]


# -- config reading (real worktree yaml -- no network) --------------------------

def test_groups_from_config_reads_the_real_source_yaml() -> None:
    # configs/sources/modis_ndvi.yaml ships 5 commodity_groups; the loader must find them.
    groups = task._groups_from_config()
    assert set(groups) == {"grains", "oilseeds", "rapeseed_softs", "sugar_oj", "palm_africa"}
