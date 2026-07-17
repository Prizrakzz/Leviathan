"""Wave-2 regression: the UNICA annual-by-state silver Batch task must expose the CLASS-B
``--publish-mode`` retrofit and route its single FLAT write through the shadow-first publisher.

The pre-retrofit task only accepted ``--bucket/--aws-region/--force-overwrite/--dry-run`` and wrote
canonical directly with ``df.to_parquet(...) + put_object(...)``, so a ``--publish-mode shadow`` canary
crashed argparse with ``unrecognized arguments: --publish-mode shadow`` (the fnc_colombia defect
class). The fix accepts ``--publish-mode {dry-run,shadow,canonical}`` (``--dry-run`` retained as an
alias, ``--force-overwrite`` string-valued for compat) and publishes through
``leviathan.silver.flat_producer.build_flat_publish`` (FLAT strategy -- the contract is
``partition_mode: flat``). This test locks ``main()``:

  * shadow builds EXACTLY one live client and stages the object under ``_shadow/`` (canonical untouched);
  * dry-run (both ``--publish-mode dry-run`` and the legacy ``--dry-run`` alias) builds NO client and
    writes nothing;
  * argparse accepts ``--publish-mode shadow`` and keeps the ``--force-overwrite`` string surface.

Pure/hermetic: an in-memory :class:`FakeS3` and a recording client factory replace all AWS. The
bronze loaders + transform are stubbed so no real bronze/S3/network is touched.
"""
from __future__ import annotations

import sys

import pandas as pd

from jobs.batch import unica_annual_state_task as task
from leviathan.storage.paths import silver_unica_annual_state_key
from tests.unit.silver.conftest import FakeS3

CANONICAL_KEY = silver_unica_annual_state_key()


# --------------------------------------------------------------------------- canned silver frame
def _annual_df() -> pd.DataFrame:
    """EXACTLY the ``silver_unica_annual_state`` physical columns. The three value columns
    (cane_crushed_t, sugar_produced_t, ethanol_total_m3) are fully non-null so the 0.5 floor clears,
    and every ``int64``-contracted column carries plain Python ints so the INV-2 writer schema encodes
    cleanly."""
    return pd.DataFrame({
        "harvest_year": ["2019-20", "2019-20"],
        "state_region": ["Sao Paulo", "South-Central Region"],
        "cane_crushed_t": [500_000, 620_000],
        "sugar_produced_t": [30_000, 41_000],
        "ethanol_total_m3": [22_000, 28_000],
        "ethanol_hydrous_m3": [15_000, 19_000],
        "ethanol_anhydrous_m3": [7_000.0, 9_000.0],
        "source": ["unica", "unica"],
    })


def _wire(monkeypatch):
    """Stub env + bronze loaders + transform + the S3 client factory. Returns ``(fake_s3, calls)``."""
    monkeypatch.setattr(task, "load_env", lambda *a, **k: None)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    # no real S3 read: the loaders are stubbed whole (their content is irrelevant -- transform is stubbed)
    monkeypatch.setattr(task, "_available_harvest_years", lambda *a, **k: ["2019-20"])
    monkeypatch.setattr(task, "_load_all_bronze", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(task, "transform_unica_annual_state", lambda *a, **k: _annual_df())
    s3 = FakeS3()
    calls: list[str] = []

    def _factory(region):
        calls.append(region)
        return s3

    # main() resolves ``get_thread_local_s3_client`` for the PUBLISH client via a call-time import from
    # leviathan.storage.s3, so patch the source-module name (patching the task attribute would not take
    # effect for the call-time import).
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


def test_dry_run_mode_builds_no_client_and_writes_nothing(monkeypatch):
    s3, calls = _wire(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["prog", "--bucket", "leviathan-test",
                                      "--publish-mode", "dry-run"])

    rc = task.main()

    assert rc == 0
    assert calls == []                                # dry-run stages nothing -> no client built
    assert s3.keys() == []                            # nothing written anywhere


def test_legacy_dry_run_flag_is_dry_run_alias(monkeypatch):
    s3, calls = _wire(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["prog", "--bucket", "leviathan-test", "--dry-run"])

    rc = task.main()

    assert rc == 0
    assert calls == []                                # --dry-run == --publish-mode dry-run
    assert s3.keys() == []


def test_argparse_accepts_publish_mode_shadow(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--bucket", "leviathan-test",
                                      "--publish-mode", "shadow"])
    args = task._parse_args()
    assert args.publish_mode == "shadow"
    assert args.bucket == "leviathan-test"
    assert args.force_overwrite is False              # default string "false" -> bool


def test_argparse_keeps_force_overwrite_string_compat(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--bucket", "leviathan-test",
                                      "--publish-mode", "canonical", "--force-overwrite", "true"])
    args = task._parse_args()
    assert args.publish_mode == "canonical"
    assert args.force_overwrite is True               # legacy `--force-overwrite true` still parses
