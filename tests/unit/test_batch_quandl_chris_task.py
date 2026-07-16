"""Unit tests for the Quandl CHRIS calendar-spreads silver Batch task (A-W4 CLASS-B retrofit).

STRUCTURAL EXCEPTION: ``silver_calendar_spreads`` has NO F010 registry contract, so the task routes
through ShadowPublisher directly (not the contract-driven ``build_flat_publish``). The shadow-first
INV-6 contract is identical; these tests prove the three modes with injected guard verdicts.
"""
from __future__ import annotations

import pandas as pd
from leviathan.silver.publisher import ManifestState
from leviathan.storage.paths import silver_calendar_spreads_key

from jobs.batch import quandl_chris_task as task
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_BUCKET = "leviathan-test"          # publisher uses the passed bucket (no contract to pin one)
_SENTINEL = b"OLD-CANONICAL-CALENDAR-SPREADS"


def _silver_df() -> pd.DataFrame:
    """One representative calendar-spreads silver row (no registry schema is pinned)."""
    return pd.DataFrame([{
        "date": pd.Timestamp("2012-07-20"), "leviathan_slug": "corn_cbot",
        "settle_c1": 800.0, "settle_c2": 790.0, "settle_c3": 780.0,
        "spread_c1c3": 20.0, "spread_c1c3_z_3yr": 1.5, "contango_flag": 0,
        "source": "quandl_chris",
    }])


def test_dry_run_writes_nothing_but_validates() -> None:
    state = task._publish_calendar_spreads(_silver_df(), dryrun_authorization(), None, _BUCKET,
                                           force_overwrite=True)
    assert state is ManifestState.VALIDATED


def test_shadow_stages_to_shadow_only_and_leaves_canonical_byte_identical() -> None:
    s3 = FakeS3()
    canonical_key = silver_calendar_spreads_key()
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL
    etag_before = s3._etag(_SENTINEL)

    state = task._publish_calendar_spreads(_silver_df(), shadow_authorization(), s3, _BUCKET,
                                           force_overwrite=True)

    assert state is ManifestState.VALIDATED
    assert s3.store[(_BUCKET, canonical_key)] == _SENTINEL
    assert s3._etag(s3.store[(_BUCKET, canonical_key)]) == etag_before
    assert any("_shadow" in k for k in s3.keys())
    for _, key in s3.store:
        if key == canonical_key or "/_manifests/" in key:
            continue
        assert "/_shadow/" in key


def test_canonical_overwrites_the_calendar_spreads_silver_object() -> None:
    s3 = FakeS3()
    canonical_key = silver_calendar_spreads_key()
    s3.store[(_BUCKET, canonical_key)] = _SENTINEL

    state = task._publish_calendar_spreads(_silver_df(), canonical_authorization(), s3, _BUCKET,
                                           force_overwrite=True)

    assert state is ManifestState.CERTIFIED
    assert (_BUCKET, canonical_key) in s3.store
    assert s3.store[(_BUCKET, canonical_key)] != _SENTINEL
