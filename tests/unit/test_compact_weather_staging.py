"""A-Wave-3 compact_weather_silver staging read + retire (SILVER-F047 coherence).

compact now reads the coarse canonical ``commodity=<c>/year=<y>/`` objects UNION the per-source b2s
month-grain under ``_staging/``, merges within-year, publishes the coarse ``[commodity, year]`` object
canonically, and (canonical mode only, after CERTIFIED) RETIRES the staging months it consumed. Only
years carrying NEW staging are recompacted (bounded daily cost); canonical-only years are left alone.
Shadow/dry-run never retires (the canonical promote leg still needs staging).

These tests stub the S3/publisher seams -- no network, no real publish.
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

import jobs.batch.compact_weather_silver_task as compact
from leviathan.silver.publisher import ManifestState

_CANONICAL = [
    "silver/weather/source=chirps/commodity=arabica_coffee/year=2025/part-000.parquet",
    "silver/weather/source=chirps/commodity=arabica_coffee/year=2026/part-000.parquet",
]
_STAGING = [
    "silver/weather/source=chirps/_staging/commodity=arabica_coffee/country=brazil/region=br_x/year=2026/month=06/part-000.parquet",
    "silver/weather/source=chirps/_staging/commodity=arabica_coffee/country=brazil/region=br_x/year=2026/month=07/part-000.parquet",
]


class _FakeS3:
    def __init__(self):
        self.deleted: list[str] = []

    def delete_object(self, Bucket, Key):  # noqa: N803 -- boto3 kwargs
        self.deleted.append(Key)


class _FakePublisher:
    last_staged = None

    def __init__(self, state, **kw):
        self._state = state

    def run(self, staged):
        _FakePublisher.last_staged = list(staged)
        return SimpleNamespace(state=self._state)


def _wire(monkeypatch, publish_state):
    def fake_list(bucket, prefix, suffix=None, aws_region=None):
        return list(_STAGING) if "/_staging/" in prefix else list(_CANONICAL)

    fake_s3 = _FakeS3()
    monkeypatch.setattr(compact, "list_s3_keys", fake_list)
    monkeypatch.setattr(compact, "_read_frame", lambda *a, **k: pd.DataFrame({"value": [1.0]}))
    monkeypatch.setattr(compact, "compact_partition", lambda frames, table: pd.concat(frames, ignore_index=True))
    monkeypatch.setattr(compact, "compacted_bytes", lambda df, table: b"x")
    monkeypatch.setattr(compact, "get_thread_local_s3_client", lambda *a, **k: fake_s3)
    monkeypatch.setattr(compact, "ShadowPublisher",
                        lambda **kw: _FakePublisher(publish_state, **kw))
    return fake_s3


def test_compact_recompacts_only_staged_years_and_retires_in_canonical(monkeypatch):
    fake_s3 = _wire(monkeypatch, ManifestState.CERTIFIED)
    auth = SimpleNamespace(may_mutate_canonical=True, mode=SimpleNamespace(value="canonical"))
    res = compact._compact_one_commodity(
        "B", "chirps", "silver_chirps", "arabica_coffee", "us-east-1", auth, glue_client=object(),
    )
    # ONLY 2026 (the year carrying staging) is recompacted; 2025 (canonical-only) is left untouched.
    staged = _FakePublisher.last_staged
    assert [s.canonical_key for s in staged] == [
        "silver/weather/source=chirps/commodity=arabica_coffee/year=2026/part-000.parquet"
    ]
    # The 2026 unit merged canonical(2026) + BOTH staging months (2 frames + 1 canonical frame).
    assert res["units"] == 1
    # Canonical + CERTIFIED -> the consumed staging months are retired.
    assert set(fake_s3.deleted) == set(_STAGING)
    assert res["staging_retired"] == 2


def test_compact_shadow_mode_does_not_retire_staging(monkeypatch):
    fake_s3 = _wire(monkeypatch, ManifestState.VALIDATED)
    auth = SimpleNamespace(may_mutate_canonical=False, mode=SimpleNamespace(value="shadow"))
    res = compact._compact_one_commodity(
        "B", "chirps", "silver_chirps", "arabica_coffee", "us-east-1", auth, glue_client=None,
    )
    assert fake_s3.deleted == []            # shadow leaves staging for the canonical promote leg
    assert res["staging_retired"] == 0


def test_compact_empty_when_no_silver_at_all(monkeypatch):
    monkeypatch.setattr(compact, "list_s3_keys", lambda *a, **k: [])
    auth = SimpleNamespace(may_mutate_canonical=True, mode=SimpleNamespace(value="canonical"))
    res = compact._compact_one_commodity(
        "B", "chirps", "silver_chirps", "arabica_coffee", "us-east-1", auth, glue_client=object(),
    )
    assert res["state"] == "empty" and res["units"] == 0


def test_retire_staging_is_best_effort(monkeypatch):
    class _FlakyS3:
        def __init__(self):
            self.deleted = []

        def delete_object(self, Bucket, Key):  # noqa: N803
            if Key.endswith("month=07/part-000.parquet"):
                raise RuntimeError("access denied")
            self.deleted.append(Key)

    s3 = _FlakyS3()
    retired = compact._retire_staging(s3, "B", list(_STAGING))
    # The reachable one is deleted; the failing one is logged (not fatal) and skipped.
    assert retired == 1 and s3.deleted == [_STAGING[0]]
