"""SILVER-F082 freshness poller pure core (leviathan.silver.freshness).

The age computation, the canonical-only (shadow/staging) exclusion, the empty-prefix behaviour, and
the poll-target derivation must all be correct against a FAKE S3 listing -- no boto3, no network.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from leviathan.silver.freshness import (
    EXTRA_TARGETS,
    METRIC_NAME,
    METRIC_NAMESPACE,
    all_poll_targets,
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

    def test_backup_key_excluded(self):
        # R7.2 (D-EI-12): a backup copy is not canonical data, anywhere in the tree.
        assert is_excluded_key("silver/fgis/_backup/2026/part.parquet") is True
        assert is_excluded_key(
            "graphrag_evidence/timeline/_backup/episodes_20260704_prerebuild.json"
        ) is True

    def test_backup_substring_in_a_filename_is_still_canonical(self):
        # Segment-scoped, not substring-scoped: only a real ``_backup/`` DIRECTORY is excluded.
        assert is_excluded_key("silver/fgis/backup_notes.parquet") is False
        assert is_excluded_key("silver/fgis/_backup_2026.parquet") is False


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

    def test_backup_does_not_reset_the_clock(self):
        # R7.2 (D-EI-12), MEASURED incident: the polled prefix graphrag_evidence/timeline/ already
        # held _backup/episodes_20260704_prerebuild.json, so a pre-rebuild BACKUP copy -- newer than
        # every live key and written WITHOUT any rebuild -- was resetting the artifact's measured
        # age and made the FreshnessLagDays fence fail OPEN. The live key still sets the age.
        objs = [
            ("graphrag_evidence/timeline/episodes.json", _dt(4)),
            ("graphrag_evidence/timeline/stamp.json", _dt(3)),
            ("graphrag_evidence/timeline/_backup/episodes_20260704_prerebuild.json", _dt(31)),
        ]
        assert newest_last_modified(objs) == _dt(4)

    def test_backup_only_prefix_reads_as_no_canonical_data(self):
        # The other half of the same fence: once the live artifact is DELETED, a lingering backup
        # must NOT keep a datapoint flowing (silver_alarms.py relies on the empty-prefix -> no
        # datapoint -> treat_missing_data='breaching' path to fire on a deleted artifact).
        objs = [("graphrag_evidence/timeline/_backup/episodes_20260704_prerebuild.json", _dt(31))]
        assert newest_last_modified(objs) is None

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


class TestExtraTargets:
    """FENCE 2 leg 3 (incident I-2, 2026-07-31).

    s3://leviathan-dev-shahem-001/graphrag_evidence/timeline/episodes.json was built 2026-07-04 and
    NOTHING measured its age for 27 days while the prop store it is derived from grew ~74%. It is
    not a registry table, so ``poll_targets`` could never see it -- and registering it in the
    SILVER-F010 registry would be a category error (``load_registry`` also feeds build_catalog, DDL
    generation, the value census and readiness certification). It rides alongside instead, on the
    SAME metric/alarm/schedule machinery.
    """

    ARTIFACT = "graphrag_timeline_episodes"

    def test_timeline_artifact_is_an_extra_target(self):
        by_table = {t.table: t for t in all_poll_targets()}
        assert self.ARTIFACT in by_table
        t = by_table[self.ARTIFACT]
        assert t.family == "graphrag_evidence"
        assert t.prefix.endswith("/")

    def test_bucket_and_prefix_match_the_evidence_jobdef(self):
        # The single source of truth for where the artifact actually lands: the evidence-build job
        # definition's EVIDENCE_S3, which timeline.write_artifact reads. If that constant moves and
        # EXTRA_TARGETS does not, the poller lists an empty prefix and pages forever -- so pin them
        # to each other rather than to a hand-copied literal.
        import importlib.util
        from pathlib import Path
        repo = Path(__file__).resolve().parents[3]
        spec = importlib.util.spec_from_file_location(
            "register_evidence_jobdef", repo / "jobs" / "utils" / "register_evidence_jobdef.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        bucket, _, prefix = mod._EVIDENCE_S3[len("s3://"):].partition("/")

        t = {x.table: x for x in all_poll_targets()}[self.ARTIFACT]
        assert t.bucket == bucket
        assert t.prefix == prefix.rstrip("/") + "/timeline/"

        # ...and that prefix is exactly where write_artifact puts the object.
        from leviathan.graphrag import timeline as tl
        assert (prefix.rstrip("/") + "/" + tl._ARTIFACT).startswith(t.prefix)

    def test_poll_targets_stays_registry_pure(self):
        # The registry-coverage pin above (len(targets) == len(reg.names())) must keep meaning what
        # it says, so the extras are NEVER folded into poll_targets itself.
        assert self.ARTIFACT not in {t.table for t in poll_targets()}
        reg = load_registry()
        assert len(poll_targets(reg)) == len(reg.names())
        assert len(all_poll_targets(reg)) == len(poll_targets(reg)) + len(EXTRA_TARGETS)

    def test_extra_targets_emit_the_same_metric_contract(self):
        t = {x.table: x for x in all_poll_targets()}[self.ARTIFACT]
        data = metric_data_for(t.table, t.family, 27.4, timestamp=NOW)
        by_dim = {d["Dimensions"][0]["Name"]: d for d in data}
        assert by_dim["Table"]["Dimensions"][0]["Value"] == self.ARTIFACT
        assert by_dim["Table"]["MetricName"] == METRIC_NAME

    def test_poller_polls_all_targets_not_just_the_registry(self):
        # The whole leg is dead if the SCRIPT still calls poll_targets(). Read the source rather
        # than importing it (the module takes argv/boto3 at import-adjacent scope).
        from pathlib import Path
        repo = Path(__file__).resolve().parents[3]
        src = (repo / "scripts" / "silver" / "freshness_poller.py").read_text(encoding="utf-8")
        assert "targets = all_poll_targets()" in src
