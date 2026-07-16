"""Wave-1 regression: the SAGIS CEC silver Batch task must build a LIVE S3 client on the
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

from jobs.batch import sagis_cec_silver_task as task
from leviathan.storage.paths import silver_sagis_cec_key
from tests.unit.silver.conftest import FakeS3

CANONICAL_KEY = silver_sagis_cec_key()


# --------------------------------------------------------------------------- canned silver frame
def _cec_df() -> pd.DataFrame:
    """EXACTLY the ``silver_sagis_cec`` physical columns; the three value columns
    (current_estimate_t, revision_t, revision_surprise) are fully non-null so the 0.5 floor clears.
    """
    return pd.DataFrame({
        "production_year": [2024, 2024],
        "report_month": [2, 5],
        "release_date": ["2024-02-28", "2024-05-27"],
        "season_type": ["summer", "summer"],
        "crop": ["maize", "maize"],
        "scope": ["total", "total"],
        "estimate_number": [1, 2],
        "area_planted_ha": [2_600_000.0, 2_600_000.0],
        "current_estimate_t": [14_000_000.0, 14_500_000.0],
        "prior_estimate_t": [None, 14_000_000.0],
        "prior_year_final_t": [13_000_000.0, 13_000_000.0],
        "revision_t": [200_000.0, 500_000.0],
        "revision_pct": [1.44, 3.57],
        "revision_surprise": [7.69, 11.53],
        "source": ["sagis_cec", "sagis_cec"],
    })


def _wire(monkeypatch):
    """Stub env + loader + transform + the S3 client factory. Returns ``(fake_s3, factory_calls)``."""
    monkeypatch.setattr(task, "load_env", lambda *a, **k: None)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(task, "load_observations", lambda *a, **k: [])   # no S3 read in the loader
    monkeypatch.setattr(task, "transform_sagis_cec", lambda *a, **k: _cec_df())
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
