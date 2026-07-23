"""SILVER-F082 freshness poller pure core (leviathan.silver.freshness).

The age computation, the canonical-only (shadow/staging) exclusion, the empty-prefix behaviour, and
the poll-target derivation must all be correct against a FAKE S3 listing -- no boto3, no network.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from leviathan.silver.freshness import (
    METRIC_NAME,
    METRIC_NAMESPACE,
    is_excluded_key,
    lag_days,
    metric_data_for,
    newest_last_modified,
    poll_targets,
)
from leviathan.silver.registry import SilverRegistry, load_registry

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def _dt(day: int) -> datetime:
    return datetime(2026, 7, day, tzinfo=timezone.utc)


class TestExclusion:
    def test_canonical_key_not_excluded(self):
        assert is_excluded_key("silver/fgis/commodity=corn/year=2026/part.parquet") is False

    def test_shadow_key_excluded(self):
        assert is_excluded_key("silver/fgis/_shadow/2026/part.parquet") is True

    def test_staging_key_excluded(self):
        assert is_excluded_key("silver/fgis/_staging/part.parquet") is True

    def test_tasks_manifest_excluded(self):
        assert is_excluded_key("silver/fgis/_tasks.json") is True


class TestNewestLastModified:
    def test_picks_max_canonical(self):
        objs = [
            ("silver/fgis/a.parquet", _dt(10)),
            ("silver/fgis/b.parquet", _dt(18)),
            ("silver/fgis/c.parquet", _dt(14)),
        ]
        assert newest_last_modified(objs) == _dt(18)

    def test_shadow_does_not_reset_the_clock(self):
        # A recent SHADOW write must NOT count -- canonical only advanced to day 5.
        objs = [
            ("silver/fgis/canonical.parquet", _dt(5)),
            ("silver/fgis/_shadow/fresh.parquet", _dt(22)),
        ]
        assert newest_last_modified(objs) == _dt(5)

    def test_empty_or_all_excluded_is_none(self):
        assert newest_last_modified([]) is None
        assert newest_last_modified([("silver/fgis/_shadow/x.parquet", _dt(22))]) is None


class TestLagDays:
    def test_none_when_no_data(self):
        assert lag_days(None, NOW) is None

    def test_positive_age(self):
        assert lag_days(_dt(13), NOW) == pytest.approx(10.5, abs=1e-6)  # 13T00 -> 23T12 == 10.5d

    def test_future_object_clamps_to_zero(self):
        assert lag_days(NOW + timedelta(days=2), NOW) == 0.0


class TestMetricData:
    def test_emits_table_and_family_datapoints(self):
        data = metric_data_for("silver_fgis", "usda_fgis", 9.0, timestamp=NOW)
        assert len(data) == 2
        by_dim = {d["Dimensions"][0]["Name"]: d for d in data}
        assert set(by_dim) == {"Table", "Family"}
        assert by_dim["Table"]["Dimensions"][0]["Value"] == "silver_fgis"
        assert by_dim["Family"]["Dimensions"][0]["Value"] == "usda_fgis"
        for d in data:
            assert d["MetricName"] == METRIC_NAME
            assert d["Value"] == 9.0
            assert d["Timestamp"] == NOW


class TestPollTargets:
    def test_skips_tables_without_prefix(self):
        reg = SilverRegistry(
            tables={
                "silver_fgis": {"table_name": "silver_fgis", "s3_bucket": "b", "s3_prefix": "silver/fgis"},
                "silver_cot": {"table_name": "silver_cot"},  # no s3_prefix -> skipped
            },
            schema={},
        )
        targets = poll_targets(reg)
        assert [t.table for t in targets] == ["silver_fgis"]

    def test_prefix_is_normalized_with_trailing_slash(self):
        reg = SilverRegistry(
            tables={"silver_fgis": {"table_name": "silver_fgis", "s3_bucket": "b", "s3_prefix": "silver/fgis"}},
            schema={},
        )
        assert poll_targets(reg)[0].prefix == "silver/fgis/"

    def test_family_resolved_via_dag_catalog(self):
        reg = SilverRegistry(
            tables={
                "silver_nass_crop_progress": {
                    "table_name": "silver_nass_crop_progress", "s3_bucket": "b", "s3_prefix": "silver/nass_crop_progress"
                },
                "gold_weather_z": {"table_name": "gold_weather_z", "s3_bucket": "b", "s3_prefix": "gold/weather_z"},
            },
            schema={},
        )
        fam = {t.table: t.family for t in poll_targets(reg)}
        assert fam == {"silver_nass_crop_progress": "usda_nass", "gold_weather_z": "weather"}

    def test_real_registry_covers_every_prefixed_table(self):
        # Every registry table carries an s3_prefix, so every one is a poll target with a valid family.
        reg = load_registry()
        targets = poll_targets(reg)
        assert len(targets) == len(reg.names())
        assert all(t.prefix.endswith("/") and t.bucket and t.family for t in targets)

    def test_namespace_constant(self):
        assert METRIC_NAMESPACE == "Leviathan/Silver"
