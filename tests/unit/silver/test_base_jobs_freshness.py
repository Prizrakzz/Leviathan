"""SILVER-V002 -- freshness-aware skip-existing (base_jobs.py:338-356 hazard fix).

The pure selector must: write new partitions, skip fresh existing ones, REFRESH an
existing silver partition whose bronze is newer (the CHIRPS silent-decline), and stay
a no-op on a benign rerun (AV-12).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from leviathan.storage.base_jobs import select_partitions_to_write

T0 = datetime(2026, 5, 16, tzinfo=timezone.utc)
T1 = datetime(2026, 6, 16, tzinfo=timezone.utc)  # newer bronze re-ingest


def _key(kd):
    return f"silver/x/{kd['p']}.parquet"


def _parts(*names):
    return [({"p": n}, f"df_{n}") for n in names]


def test_new_partition_is_written():
    parts = _parts("a", "b")
    to_write, skipped, stale = select_partitions_to_write(parts, {}, T1, _key)
    assert {kd["p"] for kd, _ in to_write} == {"a", "b"}
    assert skipped == 0 and stale == []


def test_fresh_existing_is_skipped():
    parts = _parts("a")
    existing = {"silver/x/a.parquet": T1}  # silver == bronze max -> fresh
    to_write, skipped, stale = select_partitions_to_write(parts, existing, T1, _key)
    assert to_write == []
    assert skipped == 1 and stale == []


def test_stale_silver_is_refreshed():
    # CHIRPS class: silver object older (T0) than the newest bronze (T1) -> refresh.
    parts = _parts("a")
    existing = {"silver/x/a.parquet": T0}
    to_write, skipped, stale = select_partitions_to_write(parts, existing, T1, _key)
    assert {kd["p"] for kd, _ in to_write} == {"a"}
    assert stale == ["silver/x/a.parquet"]
    assert skipped == 0


def test_benign_rerun_is_noop():
    # AV-12: bronze not newer than silver -> nothing rewritten.
    parts = _parts("a", "b")
    existing = {"silver/x/a.parquet": T1, "silver/x/b.parquet": T1}
    to_write, skipped, stale = select_partitions_to_write(parts, existing, T1, _key)
    assert to_write == []
    assert skipped == 2 and stale == []


def test_mixed_new_stale_fresh():
    parts = _parts("new", "stale", "fresh")
    existing = {
        "silver/x/stale.parquet": T0,
        "silver/x/fresh.parquet": T1,
    }
    to_write, skipped, stale = select_partitions_to_write(parts, existing, T1, _key)
    assert {kd["p"] for kd, _ in to_write} == {"new", "stale"}
    assert stale == ["silver/x/stale.parquet"]
    assert skipped == 1


def test_none_bronze_mtime_falls_back_to_skip_existing():
    # If bronze mtime is unknown, existing partitions are skipped (no false refresh).
    parts = _parts("a")
    existing = {"silver/x/a.parquet": T0}
    to_write, skipped, stale = select_partitions_to_write(parts, existing, None, _key)
    assert to_write == []
    assert skipped == 1 and stale == []
