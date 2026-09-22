"""SILVER-F082 freshness poller pure core (leviathan.silver.freshness).

The age computation, the canonical-only (shadow/staging) exclusion, the empty-prefix behaviour, and
the poll-target derivation must all be correct against a FAKE S3 listing -- no boto3, no network.

D-PR-14 adds the normalized companion metric ``FreshnessLagRatio = lag / declared ceiling``. Its
tests use a FAKE ceiling wherever the maths is under test, so they pin the arithmetic rather than
today's registry values; the two places that must track the live estate (the per-table declared
ceilings, and the poller actually passing the denominator) are pinned separately and explicitly.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from leviathan.silver.freshness import (
    BREACH_METRIC_NAME,
    EXTRA_TARGETS,
    LEDGER_GAUGES,
    METRIC_NAME,
    METRIC_NAMESPACE,
    RATIO_METRIC_NAME,
    TABLE_CEILING_OVERRIDES,
    all_poll_targets,
    declared_ceiling_days,
    is_excluded_key,
    lag_days,
    lag_ratio,
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


# ---------------------------------------------------------------------------
# D-PR-14: FreshnessLagRatio
# ---------------------------------------------------------------------------
class TestLagRatio:
    """The arithmetic, against a FAKE ceiling -- 1.0 is the universal threshold.

    Five family alarms were permanently ALARM because silver_alarms thresholds a family at
    ``min()`` over its members' ceilings and evaluates it with ``Maximum`` over their lags. The
    ratio normalizes each member against ITS OWN ceiling first, so one threshold serves an annual
    table and a daily one alike.
    """

    FAKE_CEILING = 14.0

    def test_below_ceiling_is_under_one(self):
        assert lag_ratio(7.0, self.FAKE_CEILING) == pytest.approx(0.5)

    def test_exactly_at_ceiling_is_one_and_does_not_breach(self):
        # The threshold is "> 1.0", so a table sitting EXACTLY on its declared ceiling is not a
        # breach -- the ceiling is the last acceptable value, not the first bad one.
        assert lag_ratio(14.0, self.FAKE_CEILING) == 1.0

    def test_over_ceiling_breaches(self):
        assert lag_ratio(21.0, self.FAKE_CEILING) == pytest.approx(1.5)

    def test_one_threshold_serves_every_cadence(self):
        # The whole point: a 64.83d ANNUAL table (ceiling 400) is healthy and a 7.85d table on a
        # 3d ceiling is not -- and the SAME > 1.0 test says so. Under FreshnessLagDays those two
        # need different thresholds, which is why a mixed-cadence family cannot have one.
        assert lag_ratio(64.83, 400.0) < 1.0
        assert lag_ratio(7.85, 3.0) > 1.0

    def test_no_data_yields_no_ratio(self):
        assert lag_ratio(None, self.FAKE_CEILING) is None

    def test_no_declared_ceiling_yields_no_ratio(self):
        assert lag_ratio(9.0, None) is None

    def test_non_positive_ceiling_is_refused_not_divided_by(self):
        # A ZeroDivisionError here would abort the whole poll cycle, and all 26 day-based alarms are
        # treat_missing_data='breaching' -- one bad denominator would page 21 owners at once.
        assert lag_ratio(9.0, 0) is None
        assert lag_ratio(9.0, -3) is None

    def test_zero_lag_is_zero_ratio_not_none(self):
        # A perfectly fresh table must emit 0.0, not fall through the None path (which would look
        # like "no datapoint" -> breaching).
        assert lag_ratio(0.0, self.FAKE_CEILING) == 0.0


class TestDeclaredCeiling:
    """The DENOMINATOR: the table's OWN ceiling, never the family's tightest one."""

    def test_registry_max_lag_days_wins_with_publication_grace(self):
        c = {"table_name": "t_fake", "freshness_sla": {"max_lag_days": 30, "cadence": "weekly"},
             "publication_lag_days": 7}
        assert declared_ceiling_days(c) == 37.0

    def test_cadence_default_when_no_explicit_ceiling(self):
        assert declared_ceiling_days(
            {"table_name": "t_fake", "freshness_sla": {"cadence": "annual"}}) == 400.0
        assert declared_ceiling_days(
            {"table_name": "t_fake", "freshness_sla": {"cadence": "daily"}}) == 3.0

    def test_fallback_when_cadence_unrecorded(self):
        assert declared_ceiling_days({"table_name": "t_fake"}) == 45.0

    def test_audit_override_tightens(self):
        # silver_nass_crop_progress carried registry max_lag_days=170 (~24 weeks), the MASK that let
        # a weekly producer sit stale-green for 6-10 weeks. dag_catalog.FRESHNESS_LAG_OVERRIDES
        # corrects it to 14, and the ratio's denominator must inherit that correction -- otherwise
        # the new metric reintroduces the exact hole the old one had.
        c = {"table_name": "silver_nass_crop_progress",
             "freshness_sla": {"max_lag_days": 170, "cadence": "weekly"}}
        assert declared_ceiling_days(c) == 14.0

    def test_per_table_override_loosens_a_miscalibrated_cadence(self):
        # The fortnightly series the registry records as cadence=weekly. Deriving 14 would score a
        # NORMAL 16-day-old drop at ratio 1.14 and fire the > 1.0 threshold -- the false red D-PR-14
        # exists to remove, reintroduced by its own denominator.
        c = {"table_name": "silver_unica_biweekly_season_history",
             "freshness_sla": {"cadence": "weekly"}}
        assert declared_ceiling_days(c) == 21.0
        assert lag_ratio(16.0, declared_ceiling_days(c)) < 1.0

    def test_every_real_table_gets_a_positive_finite_ceiling(self):
        # No table may reach the emitter without a usable denominator -- a missing one silently
        # demotes that table back to day-only.
        for t in all_poll_targets():
            assert t.expected_lag_days is not None, t.table
            assert t.expected_lag_days > 0, t.table

    def test_declared_ceilings_match_the_per_table_alarms(self):
        # THE LINT for the TABLE_CEILING_OVERRIDES mirror. src/leviathan imports nothing from jobs/
        # (which is not even a package), so the emitter cannot read silver_alarms at run time. This
        # test is the seam instead: silver_alarms is the direction of truth and every per-table /
        # per-artifact declared ceiling must be exactly what the emitter divides by. If either side
        # moves, this is red rather than the denominator being quietly wrong.
        import importlib.util
        from pathlib import Path
        repo = Path(__file__).resolve().parents[3]
        spec = importlib.util.spec_from_file_location(
            "silver_alarms_for_ceilings", repo / "jobs" / "observability" / "silver_alarms.py")
        alarms = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(alarms)

        declared = {**alarms.BURNED_TABLE_FRESHNESS, **alarms.ARTIFACT_FRESHNESS}
        assert declared, "silver_alarms declares no per-table ceilings -- the lint would be vacuous"
        by_table = {t.table: t for t in all_poll_targets()}
        for table, (_family, ceiling, _basis) in declared.items():
            assert table in by_table, f"{table} has a per-table alarm but is not polled"
            assert by_table[table].expected_lag_days == float(ceiling), table

        # ...and no override may exist that the alarm side does not declare (a mirror entry with no
        # counterpart is a second source of truth for nothing).
        assert set(TABLE_CEILING_OVERRIDES) <= set(declared)


class TestRatioMetricData:
    """Rule 1 of the decision: ALONGSIDE, never INSTEAD OF."""

    def test_ratio_is_appended_not_substituted(self):
        data = metric_data_for("silver_fgis", "usda_fgis", 21.0, timestamp=NOW, expected=14.0)
        assert len(data) == 4
        days = [d for d in data if d["MetricName"] == METRIC_NAME]
        ratios = [d for d in data if d["MetricName"] == RATIO_METRIC_NAME]
        assert len(days) == 2 and len(ratios) == 2
        # The day datums are byte-identical to the no-ratio call: a rename or a value change here
        # orphans / moves all 26 live FreshnessLagDays alarms at once.
        assert days == metric_data_for("silver_fgis", "usda_fgis", 21.0, timestamp=NOW)
        assert {d["Dimensions"][0]["Name"] for d in ratios} == {"Table", "Family"}
        for d in ratios:
            assert d["Value"] == pytest.approx(1.5)
            assert d["Timestamp"] == NOW
            assert d["Unit"] == "None"

    def test_ratio_rides_both_dimensions(self):
        # The family datum is the one that matters: it is what statistic=Maximum reads, and it is
        # now a NORMALIZED maximum.
        data = metric_data_for("silver_modis_ndvi", "weather", 7.85, timestamp=NOW, expected=8.0)
        ratios = {d["Dimensions"][0]["Value"]: d
                  for d in data if d["MetricName"] == RATIO_METRIC_NAME}
        assert set(ratios) == {"silver_modis_ndvi", "weather"}
        assert ratios["weather"]["Value"] == pytest.approx(0.98125)

    def test_absent_expected_emits_exactly_the_legacy_payload(self):
        assert metric_data_for("silver_fgis", "usda_fgis", 9.0, timestamp=NOW, expected=None) == \
            metric_data_for("silver_fgis", "usda_fgis", 9.0, timestamp=NOW)

    def test_bad_ceiling_degrades_to_day_only_never_raises(self):
        data = metric_data_for("silver_fgis", "usda_fgis", 9.0, timestamp=NOW, expected=0)
        assert len(data) == 2
        assert all(d["MetricName"] == METRIC_NAME for d in data)

    def test_metric_names_are_distinct(self):
        assert RATIO_METRIC_NAME == "FreshnessLagRatio"
        assert RATIO_METRIC_NAME != METRIC_NAME


class TestPollerPassesTheDenominator:
    """The emitter half is dead if the POLLER never passes ``expected``.

    These are TEXT pins on the source, and text pins are exactly as strong as the string they
    match -- ``"expected=expected" in src`` stays green for a call that is dead, mis-scoped, or
    never reached. They are kept because they name the requirement in one line, but the load-bearing
    coverage is :class:`TestPollerEndToEnd` below, which runs ``main()`` against a fake S3 + a fake
    CloudWatch and reads the datums that ACTUALLY arrive at ``put_metric_data``.

    Repointed 2026-08-16 (D-SG G3-1) at the TASK module: scripts/silver/freshness_poller.py is a
    shim now, so pinning its text would pin an empty file."""

    @staticmethod
    def _src() -> str:
        from pathlib import Path
        repo = Path(__file__).resolve().parents[3]
        return (repo / "jobs" / "observability" / "freshness_poller_task.py").read_text(
            encoding="utf-8")

    def test_script_passes_expected_to_metric_data_for(self):
        assert "expected=expected" in self._src()

    def test_script_reads_the_targets_own_ceiling(self):
        assert "t.expected_lag_days" in self._src()

    def test_script_has_a_rollback_switch(self):
        # Rollback for an ADDITIVE metric is "stop emitting it" -- available without a redeploy.
        assert "--no-ratio" in self._src()

    def test_script_creates_no_alarm(self):
        # Emitter-side ONLY (D-EI-12-adjacent): the poller must never touch an alarm resource.
        src = self._src()
        for forbidden in ("put_metric_alarm", "delete_alarms", "set_alarm_state",
                          "describe_alarms", "put_composite_alarm"):
            assert forbidden not in src


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
        # Every registry table carries an s3_prefix, so every one is a poll target with a valid
        # family -- EXCEPT the retired write surfaces, excluded WITH their story (D-LD Track 2 #1:
        # the dead pre-compact ESR leg was the estate's loudest permanent-red).
        from leviathan.silver.freshness import RETIRED_WRITE_SURFACES
        reg = load_registry()
        targets = poll_targets(reg)
        assert len(targets) == len(reg.names()) - len(RETIRED_WRITE_SURFACES)
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
        # D-SG D12: this target names ONE OBJECT, not a directory -- see the EXTRA_TARGETS
        # comment. The prefix therefore deliberately does NOT end in "/".
        assert t.prefix.endswith("/last_run.json")

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
        # D-SG D12: the HEARTBEAT object, pinned to the writer's OWN constant rather than to a
        # hand-copied literal -- timeline.write_heartbeat puts exactly this key under EVIDENCE_S3.
        from leviathan.graphrag import timeline as tl
        assert t.prefix == prefix.rstrip("/") + "/" + tl._HEARTBEAT

        # ...and the artifact the heartbeat attests to still lives in that same directory.
        assert (prefix.rstrip("/") + "/" + tl._ARTIFACT).startswith(
            prefix.rstrip("/") + "/timeline/")

    def test_poll_targets_stays_registry_pure(self):
        # The registry-coverage pin above (len(targets) == len(reg.names())) must keep meaning what
        # it says, so the extras are NEVER folded into poll_targets itself.
        assert self.ARTIFACT not in {t.table for t in poll_targets()}
        from leviathan.silver.freshness import RETIRED_WRITE_SURFACES
        reg = load_registry()
        assert len(poll_targets(reg)) == len(reg.names()) - len(RETIRED_WRITE_SURFACES)
        assert len(all_poll_targets(reg)) == len(poll_targets(reg)) + len(EXTRA_TARGETS)

    def test_extra_targets_emit_the_same_metric_contract(self):
        t = {x.table: x for x in all_poll_targets()}[self.ARTIFACT]
        data = metric_data_for(t.table, t.family, 27.4, timestamp=NOW)
        by_dim = {d["Dimensions"][0]["Name"]: d for d in data}
        assert by_dim["Table"]["Dimensions"][0]["Value"] == self.ARTIFACT
        assert by_dim["Table"]["MetricName"] == METRIC_NAME

    def test_poller_polls_all_targets_not_just_the_registry(self):
        # The whole leg is dead if the POLLER still calls poll_targets(). Read the source rather
        # than importing it (the module takes argv/boto3 at import-adjacent scope).
        from pathlib import Path
        repo = Path(__file__).resolve().parents[3]
        src = (repo / "jobs" / "observability" / "freshness_poller_task.py").read_text(
            encoding="utf-8")
        assert "targets = all_poll_targets()" in src


# ---------------------------------------------------------------------------
# THE SCRIPT, END TO END (D-PR-14 lane B, 2026-08-04)
#
# WHY THIS EXISTS ON TOP OF EVERYTHING ABOVE. The pure core was fully tested and the poller's use of
# it was pinned only by grepping the script's own text for "expected=expected". That pair proves the
# ratio CAN be computed and that a literal appears in a file -- neither one proves a ratio datum ever
# reaches CloudWatch. The estate's recurring failure is precisely this shape: a fence that reads as
# armed (T2b's write-guard, the freshness alarms themselves, the R7a inline copy) while the emitting
# half is dark. So these tests drive ``main()`` -- real argv, real target derivation, real chunking --
# against a fake S3 listing and a fake CloudWatch, and assert on the datums that ACTUALLY arrive.
# ---------------------------------------------------------------------------
class _FakeS3:
    """A ``list_objects_v2`` paginator over a canned ``{prefix: [(key, last_modified)]}`` listing.

    ``default`` (a ``(suffix, last_modified)`` pair) answers any prefix the test did not name, so a
    whole-estate run can be driven without enumerating 46 prefixes."""

    def __init__(self, listing=None, default=None):
        self._listing = listing or {}
        self._default = default
        self.listed: list[tuple[str, str]] = []

    def get_paginator(self, name):
        assert name == "list_objects_v2", name
        return self

    def paginate(self, Bucket, Prefix):  # noqa: N803 - boto3 kwarg casing
        self.listed.append((Bucket, Prefix))
        objs = self._listing.get(Prefix)
        if objs is None:
            objs = [] if self._default is None else [(Prefix + self._default[0], self._default[1])]
        yield {"Contents": [{"Key": k, "LastModified": lm} for k, lm in objs]}


class _FakeCloudWatch:
    def __init__(self):
        self.puts: list[list[dict]] = []
        self.namespaces: list[str] = []

    def put_metric_data(self, Namespace, MetricData):  # noqa: N803 - boto3 kwarg casing
        self.namespaces.append(Namespace)
        self.puts.append(list(MetricData))

    @property
    def datums(self) -> list[dict]:
        return [d for chunk in self.puts for d in chunk]


class _FakeBoto3:
    def __init__(self, s3, cw):
        self._s3, self._cw = s3, cw
        self.built: list[str] = []

    def client(self, service, **_kw):
        self.built.append(service)
        if service == "s3":
            return self._s3
        if service == "cloudwatch":
            return self._cw
        raise AssertionError(f"poller built an unexpected client: {service}")


@pytest.fixture(scope="module")
def poller():
    """The TASK module, loaded by path. `jobs/` is not an installed package, so importlib by path.

    Repointed 2026-08-16 (D-SG G3-1) from scripts/silver/freshness_poller.py, which is now a
    shim. These tests monkeypatch `boto3` ON THIS MODULE OBJECT, so they must load the module
    that actually builds the clients -- pointing them at the shim would silently test nothing,
    which is the exact shape of the two drifts this move exists to end."""
    import importlib.util
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "freshness_poller_under_test",
        repo / "jobs" / "observability" / "freshness_poller_task.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(poller, monkeypatch, argv, listing=None, default=None):
    """Run ``main(argv)`` with boto3 replaced INSIDE the poller module only. Returns (rc, s3, cw)."""
    s3, cw = _FakeS3(listing, default), _FakeCloudWatch()
    monkeypatch.setattr(poller, "boto3", _FakeBoto3(s3, cw))
    rc = poller.main(argv)
    return rc, s3, cw


def _ago(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


class TestPollerEndToEnd:
    # The two ceilings under test are the live declared ones, pinned to silver_alarms by
    # TestDeclaredCeiling.test_declared_ceilings_match_the_per_table_alarms above.
    FGIS_PREFIX = "silver/fgis/"
    # D-SG D12: the timeline target's list prefix now names the heartbeat OBJECT, so the fake
    # listing is keyed by that full key and the key it yields IS the prefix.
    EPISODES_PREFIX = "graphrag_evidence/timeline/last_run.json"

    def test_ratio_datums_actually_reach_put_metric_data(self, poller, monkeypatch):
        # THE LANE-B ASSERTION. A table WITH a declared ceiling emits FOUR datums, two of them
        # FreshnessLagRatio -- measured at the CloudWatch boundary, not by reading the script.
        rc, _s3, cw = _run(
            poller, monkeypatch, ["--tables", "silver_fgis"],
            listing={self.FGIS_PREFIX: [(self.FGIS_PREFIX + "part.parquet", _ago(7.0))]})
        assert rc == 0
        ratios = [d for d in cw.datums if d["MetricName"] == RATIO_METRIC_NAME]
        days = [d for d in cw.datums if d["MetricName"] == METRIC_NAME]
        assert len(cw.datums) == 4 and len(ratios) == 2 and len(days) == 2
        assert {d["Dimensions"][0]["Value"] for d in ratios} == {"silver_fgis", "usda_fgis"}
        for d in ratios:
            assert d["Value"] == pytest.approx(7.0 / 14.0, abs=1e-3)   # ceiling 14: WRITE cadence,
            #                                            pinned via TABLE_CEILING_OVERRIDES (D-LD:
            #                                            the card's 13d publication lag guards the
            #                                            AS-OF axis, never this write-recency one)
        for d in days:
            assert d["Value"] == pytest.approx(7.0, abs=1e-3)
        assert cw.namespaces == [METRIC_NAMESPACE]

    def test_each_table_is_normalized_by_its_OWN_ceiling(self, poller, monkeypatch):
        # D-PR-14 in one run: two targets with DIFFERENT ages (7d and 5d) and DIFFERENT ceilings
        # (14 and 10) land on the SAME 0.5 ratio. That equality is the property the family-level
        # statistic=Maximum needs and that FreshnessLagDays cannot give it. (fgis's 14 is pinned
        # via TABLE_CEILING_OVERRIDES -- the D-LD card's publication lag must never widen it.)
        rc, _s3, cw = _run(
            poller, monkeypatch,
            ["--tables", "silver_fgis,graphrag_timeline_episodes"],
            listing={
                self.FGIS_PREFIX: [(self.FGIS_PREFIX + "part.parquet", _ago(7.0))],
                self.EPISODES_PREFIX: [(self.EPISODES_PREFIX, _ago(5.0))],
            })
        assert rc == 0
        ratios = {d["Dimensions"][0]["Value"]: d["Value"]
                  for d in cw.datums if d["MetricName"] == RATIO_METRIC_NAME}
        days = {d["Dimensions"][0]["Value"]: d["Value"]
                for d in cw.datums if d["MetricName"] == METRIC_NAME}
        assert set(ratios) == {"silver_fgis", "usda_fgis",
                               "graphrag_timeline_episodes", "graphrag_evidence"}
        assert ratios["silver_fgis"] == pytest.approx(0.5, abs=1e-3)
        assert ratios["graphrag_timeline_episodes"] == pytest.approx(0.5, abs=1e-3)   # 5 / 10
        assert days["silver_fgis"] == pytest.approx(7.0, abs=1e-3)
        assert days["graphrag_timeline_episodes"] == pytest.approx(5.0, abs=1e-3)

    def test_the_non_registry_artifact_is_actually_polled(self, poller, monkeypatch):
        # FENCE 2 leg 3, behaviourally: if the script had kept calling the registry-pure
        # poll_targets(), this --tables filter would select nothing and NOTHING would be listed.
        # This is the R7a datapoint precondition D-EI-12 wants -- the METRIC, never the alarm.
        rc, s3, cw = _run(
            poller, monkeypatch, ["--tables", "graphrag_timeline_episodes"],
            listing={self.EPISODES_PREFIX: [(self.EPISODES_PREFIX, _ago(2.0))]})
        assert rc == 0
        assert s3.listed == [("leviathan-dev-shahem-001", self.EPISODES_PREFIX)]
        assert {d["Dimensions"][0]["Value"] for d in cw.datums} == {
            "graphrag_timeline_episodes", "graphrag_evidence"}

    def test_no_ratio_flag_emits_exactly_the_legacy_payload(self, poller, monkeypatch):
        # The rollback switch is real: two datums, day metric only, no ratio anywhere.
        rc, _s3, cw = _run(
            poller, monkeypatch, ["--tables", "silver_fgis", "--no-ratio"],
            listing={self.FGIS_PREFIX: [(self.FGIS_PREFIX + "part.parquet", _ago(7.0))]})
        assert rc == 0
        assert len(cw.datums) == 2
        assert {d["MetricName"] for d in cw.datums} == {METRIC_NAME}

    def test_dry_run_builds_no_cloudwatch_client_and_puts_nothing(self, poller, monkeypatch):
        rc, _s3, cw = _run(
            poller, monkeypatch, ["--tables", "silver_fgis", "--dry-run"],
            listing={self.FGIS_PREFIX: [(self.FGIS_PREFIX + "part.parquet", _ago(7.0))]})
        assert rc == 0
        assert cw.puts == []

    def test_empty_prefix_emits_no_datapoint(self, poller, monkeypatch):
        # The "canonical surface has no data" path: no datum -> treat_missing_data='breaching'.
        rc, _s3, cw = _run(poller, monkeypatch, ["--tables", "silver_fgis"], listing={})
        assert rc == 0
        assert cw.datums == []

    def test_a_shadow_only_prefix_emits_no_datapoint(self, poller, monkeypatch):
        # The canonical-only rule survives the script's generator plumbing, not just the core's.
        rc, _s3, cw = _run(
            poller, monkeypatch, ["--tables", "silver_fgis"],
            listing={self.FGIS_PREFIX: [(self.FGIS_PREFIX + "_shadow/fresh.parquet", _ago(0.1))]})
        assert rc == 0
        assert cw.datums == []

    def test_every_live_target_emits_a_ratio_and_the_chunking_holds(self, poller, monkeypatch):
        # Whole-estate sweep: no target may silently degrade to day-only (which is what a missing
        # denominator looks like from CloudWatch -- indistinguishable from "this table has no
        # ceiling"). 4 datums x every target, and every request stays inside the put chunk.
        # An UNFILTERED run also carries one FreshnessBreachCount per family (D-SG G3-1).
        # P6 (2026-09-22): run with --no-data-date so this assertion keeps measuring EXACTLY what
        # it was written to measure -- the write axis's shape and its chunking. That the new axis
        # leaves this payload byte-identical is proved separately and at the datum level by
        # TestDataAxisIsAlongsideNeverInstead, which is the stronger statement of the same fact.
        targets = all_poll_targets()
        n = len(targets)
        families = {t.family for t in targets}
        rc, s3, cw = _run(poller, monkeypatch, ["--no-data-date"],
                          listing=_every_gauge_readable(), default=("part.parquet", _ago(1.0)))
        assert rc == 0
        # One LIST per target, PLUS one per ledger gauge (P8). The gauges read a ledger OBJECT or a
        # partition key, never a table prefix, so they are counted here explicitly rather than
        # folded into n.
        assert len(s3.listed) == n + len(LEDGER_GAUGES)
        # THE WRITE-AXIS PAYLOAD, stated as itself rather than as a total (round 2): 4 datums per
        # target plus one breach count per family, and not one byte more.
        assert len([d for d in cw.datums if d["MetricName"] in (METRIC_NAME, RATIO_METRIC_NAME,
                                                                BREACH_METRIC_NAME)]) \
            == 4 * n + len(families)
        # Beside it, two things that are NOT the write axis: FreshnessTargetsPolled (P7) and the
        # one-per-reason DataDateUnread census, which under --no-data-date is how the rollback
        # lever announces itself instead of going dark in silence (review m2).
        # ... and, beside both, ONE age datum per ledger gauge (P8: CorpusFoldAgeDays,
        # CorpusChunkAgeDays -- the liveness of the monthly fold and the weekly chunk pass, carried
        # by the DAILY reporter because a dead job cannot publish its own death).
        assert len(cw.datums) == (4 * n + len(families) + 1 + len(UNREAD_REASONS)
                                  + len(LEDGER_GAUGES))
        assert len([d for d in cw.datums if d["MetricName"] == RATIO_METRIC_NAME]) == 2 * n
        assert all(0 < len(chunk) <= poller._PUT_CHUNK for chunk in cw.puts)
        assert set(cw.namespaces) == {METRIC_NAMESPACE}

    def test_dry_run_reports_the_denominator_and_flags_the_breach(self, poller, monkeypatch, capsys):
        # The operator-visible half: the printed line must name the ceiling it divided by and mark
        # a > 1.0 ratio, because --dry-run is how this is verified before an alarm ever reads it.
        rc, _s3, _cw = _run(
            poller, monkeypatch, ["--tables", "silver_fgis", "--dry-run"],
            listing={self.FGIS_PREFIX: [(self.FGIS_PREFIX + "part.parquet", _ago(28.0))]})
        assert rc == 0
        out = capsys.readouterr().out
        assert "expected=14d" in out
        assert "ratio=2.0" in out
        assert "BREACH" in out
        assert "1 table(s) over 1.0: ['silver_fgis']" in out


class TestManifestExclusion:
    """D-PQ recon V2 (2026-08-07): ShadowPublisher writes its run manifest under the CANONICAL
    root on shadow publishes too, so manifest mtimes were resetting the freshness clock -- six
    tables measured false-green (nass_crop_progress 3.0d reported vs 66.9d true). A manifest is
    bookkeeping, never canonical data."""

    def test_manifest_segment_is_excluded(self):
        from leviathan.silver.freshness import is_excluded_key
        assert is_excluded_key("silver/nass_crop_progress/_manifests/run_20260802.json")
        assert is_excluded_key("silver/fgis/_manifests/2026/run.json")

    def test_canonical_data_keys_still_count(self):
        from leviathan.silver.freshness import is_excluded_key
        assert not is_excluded_key("silver/nass_crop_progress/commodity=corn_cbot/year=2026/part-000.parquet")

    def test_newest_last_modified_ignores_manifest_mtimes(self):
        import datetime as dt
        from leviathan.silver.freshness import newest_last_modified
        old = dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc)
        fresh = dt.datetime(2026, 8, 2, tzinfo=dt.timezone.utc)
        got = newest_last_modified([
            ("silver/t/commodity=c/year=2026/part-000.parquet", old),
            ("silver/t/_manifests/run_20260802.json", fresh),
            ("silver/t/_shadow/commodity=c/year=2026/part-000.parquet", fresh),
        ])
        assert got == old


class TestBreachCount:
    """D-SG G3-1. The family breach-count metric, and the empty-prefix asymmetry."""

    def test_empty_prefix_counts_as_a_breach(self):
        from leviathan.silver.freshness import is_breaching
        assert is_breaching(None, 10.0) is True

    def test_no_ceiling_cannot_breach(self):
        from leviathan.silver.freshness import is_breaching
        assert is_breaching(99.0, None) is False
        assert is_breaching(99.0, 0) is False

    def test_healthy_family_emits_zero_not_nothing(self):
        from leviathan.silver.freshness import breach_counts
        counts = breach_counts([("weather", 0.1, 3.0), ("weather", 80.7, 45.0)])
        assert counts == {"weather": 1}
        assert breach_counts([("cftc", 1.0, 16.0)]) == {"cftc": 0}

    def test_breach_datums_reach_put_metric_data(self, poller, monkeypatch):
        _rc, _s3, cw = _run(poller, monkeypatch, [], default=("part.parquet", _dt(22)))
        names = {d["MetricName"] for d in cw.datums}
        assert "FreshnessBreachCount" in names
        assert "FreshnessLagRatio" in names   # FACT 0-A: this was dark in prod for 3 months
        breach = [d for d in cw.datums if d["MetricName"] == "FreshnessBreachCount"]
        assert all(d["Dimensions"][0]["Name"] == "Family" for d in breach)
        assert all(d["Unit"] == "Count" for d in breach)

    def test_a_filtered_run_suppresses_the_breach_metric(self, poller, monkeypatch, capsys):
        # --tables makes the per-family counts PARTIAL, and a partial count written at this
        # timestamp would overwrite the real one -- so a filtered run emits none and says why.
        rc, _s3, cw = _run(
            poller, monkeypatch, ["--tables", "silver_fgis"],
            listing={"silver/fgis/": [("silver/fgis/part.parquet", _ago(7.0))]})
        assert rc == 0
        assert all(d["MetricName"] != "FreshnessBreachCount" for d in cw.datums)
        assert "[breach] SUPPRESSED" in capsys.readouterr().out

    def test_ratio_is_emitted_alongside_days_on_the_scheduled_path(self, poller, monkeypatch):
        # FACT 0-A as a behaviour, not a text pin: the SCHEDULED (unfiltered) invocation is the one
        # that dropped `expected=` in the terraform copy, so it is the one that must be measured.
        _rc, _s3, cw = _run(poller, monkeypatch, [], default=("part.parquet", _dt(22)))
        n = len(all_poll_targets())
        assert len([d for d in cw.datums if d["MetricName"] == RATIO_METRIC_NAME]) == 2 * n
        assert len([d for d in cw.datums if d["MetricName"] == METRIC_NAME]) == 2 * n


class TestRetiredWriteSurfaces:
    """D-LD Track 2 #1: the ESR alarm inversion, closed. The dead pre-compact leg is excluded
    from polling WITH its story, and the leg that actually serves (esr_compact) still polls."""

    def test_the_dead_esr_leg_is_excluded_and_the_serving_leg_still_polls(self):
        from leviathan.silver.freshness import RETIRED_WRITE_SURFACES, all_poll_targets
        names = {t.table for t in all_poll_targets()}
        assert "silver_esr" in RETIRED_WRITE_SURFACES
        assert "silver_esr" not in names, "the retired leg must not poll (permanent-red noise)"
        assert "silver_esr_compact" in names, "the SERVING leg must keep its own poll target"

    def test_every_retired_entry_names_a_real_registry_table_with_a_reason(self):
        from leviathan.silver.freshness import RETIRED_WRITE_SURFACES
        from leviathan.silver.registry import load_registry
        reg = load_registry()
        for name, reason in RETIRED_WRITE_SURFACES.items():
            assert name in reg.names(), name
            assert len(reason) > 20, "an exclusion without its story is how dead legs get forgotten"


# ---------------------------------------------------------------------------
# P6 / P7 -- THE DATA AXIS AND THE POLLER'S OWN CENSUS (2026-09-22 pipeline census).
#
# WHAT THESE PIN, and why each one fails on HEAD. Before P6 this poller measured S3 OBJECT MTIME
# and nothing else, so a producer re-writing a byte-identical object on its fire cadence read GREEN
# forever while its content was dead. MEASURED against the live estate by a read-only poll on
# 2026-09-22: silver_sagis_weekly_exports FreshnessLagRatio 0.211 (green) and DataDateAgeRatio
# 46.263; silver_unica_corn_ethanol 0.430 (green) and 16.643. The estate carried 52 alarms on write
# dates and ZERO on data dates.
#
# The end-to-end tests further down drive `main()` against a REAL parquet file served through a
# fake S3 that answers `head_object` and RANGED `get_object` -- the same reason the
# TestPollerEndToEnd block above exists: this estate has repeatedly shipped an emitter whose
# consuming half was armed and whose producing half was dark, and a test that reads the SOURCE
# instead of the DATUMS would not have caught either of the two drifts recorded in the poller's own
# header.
# ---------------------------------------------------------------------------
from leviathan.silver.freshness import (  # noqa: E402
    AXIS_COLUMN,
    AXIS_INGEST,
    AXIS_PARTITION,
    AXIS_UNDECLARED,
    DATA_DATE_AHEAD_KNOWN,
    DATA_DATE_METRIC_NAME,
    DATA_DATE_RATIO_METRIC_NAME,
    DATA_DATE_UNREAD_METRIC_NAME,
    PARTITION_SEGMENT_OVERRIDES,
    STATIC_DATA_TARGETS,
    TARGETS_POLLED_METRIC_NAME,
    UNREAD_AHEAD,
    UNREAD_DISABLED,
    UNREAD_REASONS,
    UNREAD_STATIC,
    UNREAD_UNREADABLE,
    coerce_data_date,
    data_age_days,
    data_date_alarm_targets,
    data_date_axis,
    data_date_undeclared_tables,
    data_metric_data_for,
    is_ahead,
    partition_segment_of,
    partition_value,
    scan_prefix,
    targets_polled_metric_data,
    unread_metric_data,
)


def _utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


class TestScanPrefixPreservesTheWriteAxis:
    """scan_prefix is now the ONE pass both axes read. It may not have moved the write axis."""

    LISTING = [
        ("silver/x/part-000.parquet", _utc(2026, 7, 10)),
        ("silver/x/_shadow/part-000.parquet", _utc(2026, 7, 22)),
        ("silver/x/_backup/part-000.parquet", _utc(2026, 7, 21)),
        ("silver/x/part-001.parquet", _utc(2026, 7, 12)),
    ]

    def test_newest_equals_the_legacy_function(self):
        assert scan_prefix(self.LISTING).newest == newest_last_modified(self.LISTING)

    def test_counts_only_canonical_objects(self):
        assert scan_prefix(self.LISTING).canonical_objects == 2

    def test_exclusion_governs_the_data_axis_too(self):
        # A /_shadow/ key may not supply a partition date any more than it may reset the clock --
        # the same rule through the same door, which is the whole point of one pass.
        listing = [("silver/x/_shadow/as_of=20260922/p.parquet", _utc(2026, 9, 22)),
                   ("silver/x/as_of=20240426/p.parquet", _utc(2026, 9, 18))]
        assert scan_prefix(listing, partition_col="as_of").newest_partition_value == "20240426"

    def test_newest_written_is_bounded_and_newest_first(self):
        scan = scan_prefix(self.LISTING, keep_newest=1)
        assert [k for _lm, k in scan.newest_written] == ["silver/x/part-001.parquet"]

    def test_keep_newest_zero_costs_nothing(self):
        assert scan_prefix(self.LISTING).newest_written == ()


class TestPartitionValue:
    def test_reads_a_whole_segment(self):
        assert partition_value("silver/wasde/release_date=2026-09-11/p.parquet",
                               "release_date") == "2026-09-11"

    def test_a_column_never_matches_a_longer_segment_name(self):
        # 'date' must NOT bind to 'as_of_date=' -- a substring match here would silently measure a
        # different column than the contract declares.
        assert partition_value("silver/esr/as_of_date=20260917/p.parquet", "date") is None

    def test_absent_segment_is_none_not_a_guess(self):
        assert partition_value("silver/esr/as_of=20260917/p.parquet", "as_of_date") is None


class TestCoerceDataDate:
    @pytest.mark.parametrize("raw,expected", [
        ("2024-04-26", date(2024, 4, 26)),
        ("2024-04-26 13:04:05", date(2024, 4, 26)),
        ("20260917", date(2026, 9, 17)),
        (20260917, date(2026, 9, 17)),
        ("2026-08", date(2026, 8, 1)),
        (202608, date(2026, 8, 1)),
        (b"2024-04-26", date(2024, 4, 26)),
        (date(2025, 1, 2), date(2025, 1, 2)),
        (datetime(2025, 1, 2, 3, 4, tzinfo=timezone.utc), date(2025, 1, 2)),
    ])
    def test_every_accepted_spelling(self, raw, expected):
        assert coerce_data_date(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "junk", "2026-13-01", True, 3.5, "not-a-date"])
    def test_refuses_rather_than_guesses(self, raw):
        # None is the whole point of the signature: a fallback to "today" would certify a dead
        # table as fresh, and a fallback to the epoch would invent a 20,000-day breach.
        assert coerce_data_date(raw) is None

    def test_a_month_reads_as_its_FIRST_day(self):
        # The last day would make every monthly table up to a full cadence fresher than it is --
        # a fail-open of ~30 days on exactly the 45-day-ceiling tables (MPOB, MPOC, PSD).
        assert coerce_data_date("2026-08") == date(2026, 8, 1)


class TestDataAgeAndAhead:
    NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)

    def test_signed_whole_days(self):
        assert data_age_days(date(2024, 4, 26), self.NOW) == 879.0

    def test_the_census_numbers_reproduce(self):
        # The two readings the 2026-09-22 census had to read parquet by hand to get.
        assert data_age_days(date(2024, 4, 26), self.NOW) / 19.0 == pytest.approx(46.26, abs=0.01)
        assert data_age_days(date(2026, 2, 1), self.NOW) / 14.0 == pytest.approx(16.64, abs=0.01)

    def test_a_future_date_is_negative_not_clamped(self):
        assert data_age_days(date(2027, 2, 1), self.NOW) == -132.0

    def test_is_ahead_tolerates_one_day_of_skew(self):
        assert is_ahead(-1.0) is False
        assert is_ahead(0.0) is False
        assert is_ahead(-132.0) is True

    def test_nothing_read_is_none(self):
        assert data_age_days(None, self.NOW) is None
        assert is_ahead(None) is False


class TestDataDateAxisDeclaration:
    """The axis is DECLARED by the contract. Nothing is sniffed."""

    def test_partition_key_axis(self):
        c = {"knowledge_date_col": "release_date", "knowledge_semantics": "vintage",
             "partition_keys": [{"name": "release_date"}]}
        assert data_date_axis(c) == (AXIS_PARTITION, "release_date")

    def test_physical_column_axis(self):
        c = {"knowledge_date_col": "week_ending_date", "knowledge_semantics": "data_date",
             "partition_keys": []}
        assert data_date_axis(c) == (AXIS_COLUMN, "week_ending_date")

    def test_null_column_is_undeclared(self):
        assert data_date_axis({"knowledge_date_col": None}) == (AXIS_UNDECLARED, None)

    def test_ingest_semantics_is_not_a_data_axis(self):
        # `ingest_date` records WHEN THE ROW WAS WRITTEN. Reading it as a data date would restate
        # FreshnessLagDays under a name that promises the content axis is watched -- worse than not
        # measuring at all. MEASURED 2026-09-22 before this branch existed: silver_production's
        # "data" age read 27d against its own write lag of 27.03d.
        c = {"knowledge_date_col": "ingest_date", "knowledge_semantics": "ingest",
             "partition_keys": []}
        assert data_date_axis(c) == (AXIS_INGEST, "ingest_date")


class TestDataDateAxisOnTheRealRegistry:
    def test_the_stale_green_class_all_declare_a_column_axis(self):
        targets = {t.table: t for t in all_poll_targets()}
        for name, column in [("silver_sagis_weekly_exports", "week_ending_date"),
                             ("silver_unica_corn_ethanol", "fortnight_date"),
                             ("silver_unica_biweekly_season_history", "fortnight_date"),
                             ("silver_unica_monthly_ethanol_sales", "month_date")]:
            assert targets[name].data_date_mode == AXIS_COLUMN
            assert targets[name].data_date_col == column

    def test_the_census_denominators_are_the_declared_ceilings(self):
        targets = {t.table: t for t in all_poll_targets()}
        assert targets["silver_sagis_weekly_exports"].expected_lag_days == 19.0
        assert targets["silver_unica_corn_ethanol"].expected_lag_days == 14.0

    def test_undeclared_list_is_pinned_by_name(self):
        # The repo's own blind list on the DATA axis (null knowledge_date_col, or an INGEST
        # semantics that records the write rather than the period). A contract added with no axis
        # is otherwise invisible in exactly the way silver_psd_attributes was invisible for five
        # weeks. This assertion is MEANT to be edited -- deliberately -- when a lane declares one.
        assert data_date_undeclared_tables() == [
            "gold_pattern_records",
            "gold_weather_z",
            "graphrag_timeline_episodes",
            "silver_chirps",
            "silver_cpc_soil",
            "silver_fnc_colombia_area_department",
            "silver_fred_fx",
            "silver_model_predictions",
            "silver_modis_ndvi",
            "silver_mpob_annual",
            "silver_mpoc_stock_comparison",
            "silver_mpoc_trade_stats_monthly",
            "silver_nasa_power",
            "silver_noaa_iod",
            "silver_noaa_oni",
            "silver_production",
            "silver_unica_annual_state",
            "silver_unica_biweekly_release_series",
            "silver_wap_table01",
        ]

    def test_static_targets_are_real_poll_targets(self):
        # A declared closed archive that names no live target is a rule guarding nothing.
        names = {t.table for t in all_poll_targets()}
        assert set(STATIC_DATA_TARGETS) <= names

    def test_a_static_target_never_earns_an_alarm(self):
        assert set(STATIC_DATA_TARGETS).isdisjoint(data_date_alarm_targets())

    def test_partition_segment_overrides_name_live_partition_axis_targets(self):
        # An override for a table that no longer reads its date from the key is a string nothing
        # checks. MEASURED 2026-09-22: silver_esr_compact declares partition key `as_of_date` while
        # its 272 canonical keys spell the segment `as_of=` -- legal, because a registered-partition
        # table stores the Glue VALUE against an explicit LOCATION, so the two names are
        # independent by design.
        modes = {t.table: t.data_date_mode for t in all_poll_targets()}
        for table in PARTITION_SEGMENT_OVERRIDES:
            assert modes.get(table) == AXIS_PARTITION, table
        assert partition_segment_of("silver_esr_compact", "as_of_date") == "as_of"
        assert partition_segment_of("silver_wasde", "release_date") == "release_date"

    def test_alarm_targets_exclude_undeclared_and_static(self):
        alarmed = data_date_alarm_targets()
        assert set(alarmed).isdisjoint(data_date_undeclared_tables())
        assert "silver_sagis_weekly_exports" in alarmed
        family, ceiling, basis = alarmed["silver_sagis_weekly_exports"]
        assert (family, ceiling) == ("sagis", 19.0)
        assert "week_ending_date" in basis


class TestDataMetricData:
    NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)

    def test_two_datums_without_a_ceiling_four_with(self):
        assert len(data_metric_data_for("t", "f", 10.0, timestamp=self.NOW)) == 2
        assert len(data_metric_data_for("t", "f", 10.0, timestamp=self.NOW, expected=5.0)) == 4

    def test_the_two_dimension_sets_are_single_dim_like_the_write_axis(self):
        data = data_metric_data_for("t", "f", 10.0, timestamp=self.NOW, expected=5.0)
        for d in data:
            assert len(d["Dimensions"]) == 1
        assert {d["Dimensions"][0]["Value"] for d in data} == {"t", "f"}

    def test_it_never_collides_with_the_gate_series_or_the_write_series(self):
        # The gate emits DataDateAgeDays on the COMPOSITE {Table,Family} set into this same
        # namespace. Single-dim here keeps them three distinct series, so neither emitter can
        # overwrite the other -- and an alarm on DataDateAgeRatio{Table} reads the poller alone.
        names = {d["MetricName"]
                 for d in data_metric_data_for("t", "f", 10.0, timestamp=self.NOW, expected=5.0)}
        assert names == {DATA_DATE_METRIC_NAME, DATA_DATE_RATIO_METRIC_NAME}
        assert METRIC_NAME not in names and RATIO_METRIC_NAME not in names

    def test_ratio_is_the_census_arithmetic(self):
        data = data_metric_data_for("silver_sagis_weekly_exports", "sagis", 879.0,
                                    timestamp=self.NOW, expected=19.0)
        ratios = [d["Value"] for d in data if d["MetricName"] == DATA_DATE_RATIO_METRIC_NAME]
        assert ratios == [pytest.approx(46.263, abs=1e-3)] * 2


class TestUnreadAndCensusMetrics:
    NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)

    def test_every_reason_emits_even_at_zero(self):
        # An alarm that only receives a datapoint while it is breaching can never CLEAR -- the same
        # discipline breach_counts applies, for the same reason.
        data = unread_metric_data({UNREAD_UNREADABLE: 2}, timestamp=self.NOW)
        by_reason = {d["Dimensions"][0]["Value"]: d["Value"] for d in data}
        assert by_reason == {"absent": 0.0, "ahead": 0.0, "disabled": 0.0, "static": 0.0,
                             "undeclared": 0.0, "unreadable": 2.0}
        assert {d["MetricName"] for d in data} == {DATA_DATE_UNREAD_METRIC_NAME}

    def test_the_reason_set_is_closed(self):
        # A reason that the poller counts and unread_metric_data does not emit is a tally nobody
        # can see; a reason emitted but never counted is a permanent zero. ONE tuple governs both,
        # and this asserts the emitter really iterates it.
        emitted = [d["Dimensions"][0]["Value"] for d in unread_metric_data({}, timestamp=self.NOW)]
        assert emitted == list(UNREAD_REASONS)
        assert set(UNREAD_REASONS) == {"absent", "ahead", "disabled", "static", "undeclared",
                                       "unreadable"}

    def test_targets_polled_is_undimensioned(self):
        data = targets_polled_metric_data(53, timestamp=self.NOW)
        assert data == [{"MetricName": TARGETS_POLLED_METRIC_NAME, "Timestamp": self.NOW,
                         "Value": 53.0, "Unit": "Count", "Dimensions": []}]


# ---------------------------------------------------------------------------
# P6 END TO END -- the datums that ACTUALLY reach put_metric_data, measured at the CloudWatch
# boundary against a REAL parquet file served through ranged GETs.
#
# Reading the source would not do. This poller's own header records two drifts in one quarter where
# the consuming half was armed and the emitting half was dark, and both were found by reading
# `list-metrics`, not code. So these drive `main()` with a fake S3 that answers `list_objects_v2`,
# `head_object` and `get_object(Range=...)` exactly as S3 does, over bytes pyarrow really wrote.
# ---------------------------------------------------------------------------
import io as _io  # noqa: E402


def _parquet_bytes(column: str, values: list, row_group_size: int = 2) -> bytes:
    """A real single-column parquet file, so the footer statistics under test are pyarrow's own."""
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    buf = _io.BytesIO()
    pq.write_table(pa.table({column: pa.array(values), "v": pa.array([1.0] * len(values))}),
                   buf, row_group_size=row_group_size)
    return buf.getvalue()


class _ObjectStore:
    """`head_object` + ranged `get_object` over an in-memory {key: bytes} map, mixed into _FakeS3.

    A key with no bytes registered raises, exactly as an S3 403/404 would -- that is the path the
    UNREADABLE counter and its alarm exist for, and it has to be exercised, not assumed."""

    def __init__(self, blobs=None):
        self.blobs = dict(blobs or {})
        self.ranges: list[tuple[str, str]] = []

    def head_object(self, Bucket, Key):  # noqa: N803 - boto3 kwarg casing
        if Key not in self.blobs:
            raise KeyError(f"NoSuchKey: {Key}")
        return {"ContentLength": len(self.blobs[Key])}

    def get_object(self, Bucket, Key, Range=None):  # noqa: N803 - boto3 kwarg casing
        if Key not in self.blobs:
            raise KeyError(f"NoSuchKey: {Key}")
        body = self.blobs[Key]
        self.ranges.append((Key, Range or ""))
        if Range:
            start, _, end = Range.replace("bytes=", "").partition("-")
            body = body[int(start):int(end) + 1]
        return {"Body": _io.BytesIO(body)}


class _FakeS3WithObjects(_FakeS3, _ObjectStore):
    def __init__(self, listing=None, default=None, blobs=None):
        _FakeS3.__init__(self, listing, default)
        _ObjectStore.__init__(self, blobs)


def _run_objects(poller, monkeypatch, argv, listing=None, default=None, blobs=None):
    s3 = _FakeS3WithObjects(listing, default, blobs)
    cw = _FakeCloudWatch()
    monkeypatch.setattr(poller, "boto3", _FakeBoto3(s3, cw))
    return poller.main(argv), s3, cw


class TestDataAxisEndToEnd:
    SAGIS_PREFIX = "silver/sagis_weekly_exports/"
    SAGIS_KEY = SAGIS_PREFIX + "part-000.parquet"
    WASDE_PREFIX = "silver/wasde/"

    def test_the_stale_green_table_is_finally_loud(self, poller, monkeypatch):
        # THE WHOLE POINT, in one assertion. The object was written an hour ago, so every write-axis
        # metric reads fresh -- and the bytes hold 2024-04-26. Against the table's own declared
        # 19-day ceiling that is the 46x the 2026-09-22 census had to read parquet by hand to find.
        blobs = {self.SAGIS_KEY: _parquet_bytes("week_ending_date",
                                                ["2024-03-01", "2024-04-26", "2023-11-02"])}
        rc, _s3, cw = _run_objects(
            poller, monkeypatch, ["--tables", "silver_sagis_weekly_exports"],
            listing={self.SAGIS_PREFIX: [(self.SAGIS_KEY, _ago(0.04))]}, blobs=blobs)
        assert rc == 0
        write = {d["Dimensions"][0]["Value"]: d["Value"]
                 for d in cw.datums if d["MetricName"] == RATIO_METRIC_NAME}
        data = {d["Dimensions"][0]["Value"]: d["Value"]
                for d in cw.datums if d["MetricName"] == DATA_DATE_RATIO_METRIC_NAME}
        assert write["silver_sagis_weekly_exports"] < 0.01      # the write axis says GREEN
        assert data["silver_sagis_weekly_exports"] > 40.0       # the data axis says 46x
        assert set(data) == {"silver_sagis_weekly_exports", "sagis"}
        days = [d["Value"] for d in cw.datums if d["MetricName"] == DATA_DATE_METRIC_NAME]
        assert len(days) == 2 and days[0] == days[1] and days[0] > 800

    def test_only_the_footer_is_fetched(self, poller, monkeypatch):
        # The cost bound, measured rather than asserted in prose: pyarrow seeks to the tail, so the
        # bytes fetched are a small fraction of the object and every GET carries a Range header.
        blobs = {self.SAGIS_KEY: _parquet_bytes(
            "week_ending_date", ["2024-04-%02d" % (1 + i % 28) for i in range(20000)],
            row_group_size=5000)}
        rc, s3, _cw = _run_objects(
            poller, monkeypatch, ["--tables", "silver_sagis_weekly_exports"],
            listing={self.SAGIS_PREFIX: [(self.SAGIS_KEY, _ago(1.0))]}, blobs=blobs)
        assert rc == 0
        assert s3.ranges, "the footer read must go through a RANGED get_object"
        assert all(r.startswith("bytes=") for _k, r in s3.ranges)

    def test_a_partition_axis_costs_no_get_at_all(self, poller, monkeypatch):
        # silver_wasde reads release_date straight out of the key: exact, every object, zero GETs.
        today = datetime.now(timezone.utc).date()
        old_day = (today - timedelta(days=40)).isoformat()
        new_day = (today - timedelta(days=9)).isoformat()
        keys = [(self.WASDE_PREFIX + f"release_date={old_day}/p.parquet", _ago(40.0)),
                (self.WASDE_PREFIX + f"release_date={new_day}/p.parquet", _ago(9.0))]
        rc, s3, cw = _run_objects(poller, monkeypatch, ["--tables", "silver_wasde"],
                                  listing={self.WASDE_PREFIX: keys})
        assert rc == 0
        assert s3.ranges == []
        days = {d["Value"] for d in cw.datums if d["MetricName"] == DATA_DATE_METRIC_NAME}
        assert days == {9.0}          # the MAX release_date, read from the KEY, not the mtime

    def test_an_unreadable_footer_never_stops_the_poll(self, poller, monkeypatch):
        # THE FENCE THAT MUST NOT KILL THE THING IT MEASURES. Every write-axis alarm is
        # treat_missing_data="breaching", so one unhandled exception in the data leg would withhold
        # all 26 write-axis metrics and page 21 owners at once. Here the object simply is not
        # fetchable: the write axis is emitted in full and the blindness is COUNTED.
        rc, _s3, cw = _run_objects(
            poller, monkeypatch, ["--tables", "silver_sagis_weekly_exports"],
            listing={self.SAGIS_PREFIX: [(self.SAGIS_KEY, _ago(1.0))]}, blobs={})
        assert rc == 0
        assert len([d for d in cw.datums if d["MetricName"] == METRIC_NAME]) == 2
        assert len([d for d in cw.datums if d["MetricName"] == RATIO_METRIC_NAME]) == 2
        assert [d for d in cw.datums if d["MetricName"] == DATA_DATE_METRIC_NAME] == []

    def test_a_declared_column_absent_from_the_schema_is_unreadable_not_zero(self, poller, monkeypatch):
        blobs = {self.SAGIS_KEY: _parquet_bytes("some_other_column", ["2024-04-26", "2024-03-01"])}
        rc, _s3, cw = _run_objects(
            poller, monkeypatch, ["--tables", "silver_sagis_weekly_exports"],
            listing={self.SAGIS_PREFIX: [(self.SAGIS_KEY, _ago(1.0))]}, blobs=blobs)
        assert rc == 0
        assert [d for d in cw.datums if d["MetricName"] == DATA_DATE_METRIC_NAME] == []

    def test_a_future_data_date_emits_nothing(self, poller, monkeypatch):
        # silver_rebuild_gate's ruling, reached by the same argument: the bytes leading the clock is
        # not evidence of freshness, so the target is neither green nor red. A clamp to zero here
        # would publish DataDateAgeRatio 0.000 off a scheduled future release date -- measured live
        # on silver_nass_annual (release_date 2027-02-01, 132 days ahead) on 2026-09-22.
        blobs = {self.SAGIS_KEY: _parquet_bytes("week_ending_date", ["2027-02-01", "2026-01-01"])}
        rc, _s3, cw = _run_objects(
            poller, monkeypatch, ["--tables", "silver_sagis_weekly_exports"],
            listing={self.SAGIS_PREFIX: [(self.SAGIS_KEY, _ago(1.0))]}, blobs=blobs)
        assert rc == 0
        assert [d for d in cw.datums if d["MetricName"] == DATA_DATE_METRIC_NAME] == []
        assert len([d for d in cw.datums if d["MetricName"] == METRIC_NAME]) == 2

    def test_the_shadow_copy_can_never_supply_the_data_date(self, poller, monkeypatch):
        # The canonical-only rule reaches the new axis through the same door. A /_shadow/ object
        # holding a fresh date must not be footer-read at all.
        shadow = self.SAGIS_PREFIX + "_shadow/part-000.parquet"
        blobs = {self.SAGIS_KEY: _parquet_bytes("week_ending_date", ["2024-04-26", "2024-03-01"]),
                 shadow: _parquet_bytes("week_ending_date", ["2026-09-20", "2026-09-13"])}
        rc, s3, cw = _run_objects(
            poller, monkeypatch, ["--tables", "silver_sagis_weekly_exports"],
            listing={self.SAGIS_PREFIX: [(self.SAGIS_KEY, _ago(5.0)), (shadow, _ago(0.04))]},
            blobs=blobs)
        assert rc == 0
        assert all(key != shadow for key, _r in s3.ranges)
        days = {d["Value"] for d in cw.datums if d["MetricName"] == DATA_DATE_METRIC_NAME}
        assert days and min(days) > 800


class TestDataAxisIsAlongsideNeverInstead:
    """Census threat T8's BYTE-IDENTICAL SET, proved at the CloudWatch boundary."""

    SAGIS_PREFIX = "silver/sagis_weekly_exports/"
    SAGIS_KEY = SAGIS_PREFIX + "part-000.parquet"

    def _write_axis(self, datums):
        return [d for d in datums if d["MetricName"] in (METRIC_NAME, RATIO_METRIC_NAME,
                                                         BREACH_METRIC_NAME)]

    def test_the_write_axis_payload_is_unchanged_by_the_new_axis(self, poller, monkeypatch):
        blobs = {self.SAGIS_KEY: _parquet_bytes("week_ending_date", ["2024-04-26", "2024-03-01"])}
        listing = {self.SAGIS_PREFIX: [(self.SAGIS_KEY, _ago(3.0))]}
        _rc, _s3, on = _run_objects(poller, monkeypatch, ["--tables", "silver_sagis_weekly_exports"],
                                    listing=listing, blobs=blobs)
        _rc, _s3, off = _run_objects(
            poller, monkeypatch,
            ["--tables", "silver_sagis_weekly_exports", "--no-data-date"],
            listing=listing, blobs=blobs)
        a, b = self._write_axis(on.datums), self._write_axis(off.datums)
        assert len(a) == len(b) == 4
        # Timestamp and Value both move with the wall clock between two runs (the lag is measured
        # against `now`), so the SHAPE is compared exactly and the numbers to the millisecond.
        for x, y in zip(a, b):
            assert {k: v for k, v in x.items() if k not in ("Timestamp", "Value")} == \
                   {k: v for k, v in y.items() if k not in ("Timestamp", "Value")}
            assert x["Value"] == pytest.approx(y["Value"], abs=1e-3)

    def test_the_rollback_switch_issues_no_get_at_all(self, poller, monkeypatch):
        blobs = {self.SAGIS_KEY: _parquet_bytes("week_ending_date", ["2024-04-26", "2024-03-01"])}
        _rc, s3, cw = _run_objects(
            poller, monkeypatch,
            ["--tables", "silver_sagis_weekly_exports", "--no-data-date"],
            listing={self.SAGIS_PREFIX: [(self.SAGIS_KEY, _ago(3.0))]}, blobs=blobs)
        assert s3.ranges == []
        assert [d for d in cw.datums
                if d["MetricName"] in (DATA_DATE_METRIC_NAME, DATA_DATE_RATIO_METRIC_NAME,
                                       DATA_DATE_UNREAD_METRIC_NAME)] == []


class TestTargetsPolledCensus:
    """P7: the count the poller has printed since it was built and nothing has ever read."""

    def test_an_unfiltered_run_reports_its_own_target_count(self, poller, monkeypatch):
        n = len(all_poll_targets())
        _rc, _s3, cw = _run(poller, monkeypatch, ["--no-data-date"],
                            default=("part.parquet", _ago(1.0)))
        census = [d for d in cw.datums if d["MetricName"] == TARGETS_POLLED_METRIC_NAME]
        assert len(census) == 1
        assert census[0]["Value"] == float(n)
        assert census[0]["Dimensions"] == []

    def test_a_filtered_run_never_publishes_a_partial_count(self, poller, monkeypatch):
        # A partial count would overwrite the real one at this timestamp and read as a registry that
        # shrank -- the same reason the family breach counts are suppressed under --tables.
        _rc, _s3, cw = _run(poller, monkeypatch, ["--tables", "silver_fgis", "--no-data-date"],
                            default=("part.parquet", _ago(1.0)))
        assert [d for d in cw.datums if d["MetricName"] == TARGETS_POLLED_METRIC_NAME] == []

    def test_the_generated_alarm_threshold_equals_what_an_unfiltered_run_emits(self, poller, monkeypatch):
        # THE PIN THAT MAKES P7 WORK. The alarm generator writes the expected count from the repo
        # registry; the poller emits what its BAKED registry contains. Measured 2026-09-21: the
        # scheduled poller printed 46 while the repo declared 53, and nothing anywhere compared the
        # two for five weeks. If these two ever disagree in-process, the comparison is meaningless.
        import importlib.util
        from pathlib import Path
        repo = Path(__file__).resolve().parents[3]
        spec = importlib.util.spec_from_file_location(
            "silver_alarms_for_census", repo / "jobs" / "observability" / "silver_alarms.py")
        sa = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sa)
        _rc, _s3, cw = _run(poller, monkeypatch, ["--no-data-date"],
                            default=("part.parquet", _ago(1.0)))
        emitted = [d for d in cw.datums if d["MetricName"] == TARGETS_POLLED_METRIC_NAME][0]
        assert emitted["Value"] == float(sa.build_tfvars()["silver_expected_poll_targets"])


# ---------------------------------------------------------------------------
# ROUND 2 (adversarial review, 2026-09-22). THREE CLASSES THAT FAIL ON THE ROUND-1 WORKTREE, not
# only on HEAD -- which is the point: round 1 passed 128 tests while DELETING a live reading and
# leaving a whole blindness class unalarmed, because nothing asserted what reached CloudWatch for
# a STATIC target and nothing asserted that an AHEAD reading had a voice.
# ---------------------------------------------------------------------------
class TestAStaticTargetKeepsItsMeasurement:
    """Review M1. A declared closed archive is excluded from the ALARM and from nothing else.

    MEASURED on the live estate 2026-09-22 13:33Z, round-1 code: all three STATIC_DATA_TARGETS
    printed ``data=STATIC (...)`` with ZERO ``data_age_days=`` beside them and emitted zero
    DataDateAgeDays datums -- and silver_mpoc_exports_by_country declares a real, readable axis
    (``knowledge_date_col: year_ending_date``), so a true reading was being deleted. The entry's own
    removal trigger ("delete it the day the source publishes again") was unobservable as a result.
    """

    MPOC_PREFIX = "silver/mpoc_exports_by_country/"
    MPOC_KEY = MPOC_PREFIX + "part-000.parquet"

    def test_a_static_target_still_emits_its_age(self, poller, monkeypatch):
        blobs = {self.MPOC_KEY: _parquet_bytes("year_ending_date",
                                               ["2023-12-31", "2022-12-31"])}
        rc, _s3, cw = _run_objects(
            poller, monkeypatch, ["--tables", "silver_mpoc_exports_by_country"],
            listing={self.MPOC_PREFIX: [(self.MPOC_KEY, _ago(1.0))]}, blobs=blobs)
        assert rc == 0
        days = [d for d in cw.datums
                if d["MetricName"] == DATA_DATE_METRIC_NAME
                and d["Dimensions"] == [{"Name": "Table",
                                         "Value": "silver_mpoc_exports_by_country"}]]
        assert len(days) == 1, "the closed archive's age must still reach CloudWatch"
        assert days[0]["Value"] > 900          # 2023-12-31 is ~1,000 days back from 2026-09
        # ...AND the exclusion that the entry actually buys is untouched.
        assert "silver_mpoc_exports_by_country" not in data_date_alarm_targets()

    def test_the_static_tag_rides_beside_the_figure_not_instead_of_it(
            self, poller, monkeypatch, capsys):
        blobs = {self.MPOC_KEY: _parquet_bytes("year_ending_date", ["2023-12-31"])}
        rc, _s3, _cw = _run_objects(
            poller, monkeypatch, ["--tables", "silver_mpoc_exports_by_country"],
            listing={self.MPOC_PREFIX: [(self.MPOC_KEY, _ago(1.0))]}, blobs=blobs)
        assert rc == 0
        out = capsys.readouterr().out
        assert "data=STATIC" in out            # the declaration is still on the line
        assert "data_age_days=" in out         # and so is the number round 1 dropped
        assert "declared STATIC: NO alarm" in out
        assert f"static={1}" in out            # counted exactly once, under its own reason

    def test_a_static_target_is_charged_static_and_never_double_counted(
            self, poller, monkeypatch, capsys):
        # Exactly one reason per target: a STATIC target with a null axis is NOT also undeclared,
        # and a STATIC target that reads fine is NOT silently uncounted.
        rc, _s3, _cw = _run_objects(
            poller, monkeypatch,
            ["--tables", "silver_mpoc_exports_by_country,silver_unica_annual_state"],
            listing={self.MPOC_PREFIX: [(self.MPOC_KEY, _ago(1.0)),
                                        ],
                     "silver/unica_annual_state/": [
                         ("silver/unica_annual_state/part-000.parquet", _ago(1.0))]},
            blobs={self.MPOC_KEY: _parquet_bytes("year_ending_date", ["2023-12-31"])})
        assert rc == 0
        out = capsys.readouterr().out
        assert "static=2" in out
        assert "undeclared=0" in out

    def test_a_line_carries_ONE_data_key_so_a_parser_cannot_read_it_two_ways(
            self, poller, monkeypatch, capsys):
        # Review m4. A declared archive whose axis is ALSO undeclared printed two `data=` tokens on
        # one line -- `data=STATIC (...) data=UNDECLARED (...)`. Harmless to a human, ambiguous to
        # anything that parses, and this line is the lane's own evidence surface. The declaration
        # now rides as a bracketed note BESIDE the verdict, never as a second verdict.
        rc, _s3, _cw = _run(
            poller, monkeypatch,
            ["--tables", "silver_mpoc_trade_stats_monthly,silver_unica_annual_state"],
            listing={"silver/mpoc_trade_stats_monthly/": [
                         ("silver/mpoc_trade_stats_monthly/part-000.parquet", _ago(1.0))],
                     "silver/unica_annual_state/": [
                         ("silver/unica_annual_state/part-000.parquet", _ago(1.0))]})
        assert rc == 0
        out = capsys.readouterr().out
        rows = [ln for ln in out.splitlines() if " family=" in ln]
        assert len(rows) == 2, rows
        for ln in rows:
            assert ln.count(" data=") == 1, ln
            assert "[STATIC:" in ln          # the declaration is still on the line
            assert "data=UNDECLARED" in ln   # and so is the verdict

    def test_a_closed_archive_that_cannot_be_read_never_arms_the_blindness_alarm(
            self, poller, monkeypatch, capsys):
        # The read is attempted and the failure is PRINTED, but an archive carrying no per-table
        # alarm creates no blindness to declare -- and Reason=unreadable is the one alarm in this
        # leg that must stay believable.
        rc, _s3, _cw = _run_objects(
            poller, monkeypatch, ["--tables", "silver_mpoc_exports_by_country"],
            listing={self.MPOC_PREFIX: [(self.MPOC_KEY, _ago(1.0))]}, blobs={})
        assert rc == 0
        out = capsys.readouterr().out
        assert "data=UNREADABLE" in out
        assert "unreadable=0" in out
        assert "static=1" in out


class TestAForwardStampedAxisHasAVoice:
    """Review M3. An AHEAD reading publishes no age datapoint AND is alarmed on its own dimension.

    MEASURED 2026-09-22: silver_nass_annual's declared axis (release_date) holds 2027-02-01, 132
    days ahead. Round 1 recorded it and alarmed nothing, and its per-table alarm is
    treat_missing_data="notBreaching", so the table had left the content watch in silence.
    """

    SAGIS_PREFIX = "silver/sagis_weekly_exports/"
    SAGIS_KEY = SAGIS_PREFIX + "part-000.parquet"
    MPOC_PREFIX = "silver/mpoc_exports_by_country/"
    MPOC_KEY = MPOC_PREFIX + "part-000.parquet"

    def test_the_ahead_reason_reaches_cloudwatch_with_a_real_count(self, poller, monkeypatch):
        # The datum, at the CloudWatch boundary -- not the counter, and not the log line. An
        # unfiltered run is required because a partial census may never be published.
        blobs = {self.SAGIS_KEY: _parquet_bytes("week_ending_date", ["2027-02-01", "2026-01-01"])}
        rc, _s3, cw = _run_objects(
            poller, monkeypatch, [],
            listing={self.SAGIS_PREFIX: [(self.SAGIS_KEY, _ago(1.0))]},
            default=("part-000.parquet", _ago(1.0)), blobs=blobs)
        assert rc == 0
        by_reason = {d["Dimensions"][0]["Value"]: d["Value"] for d in cw.datums
                     if d["MetricName"] == DATA_DATE_UNREAD_METRIC_NAME}
        assert by_reason[UNREAD_AHEAD] == 1.0
        # and the forward-stamped target still publishes NO age figure
        assert not [d for d in cw.datums if d["MetricName"] == DATA_DATE_METRIC_NAME
                    and d["Dimensions"] == [{"Name": "Table",
                                             "Value": "silver_sagis_weekly_exports"}]]

    def test_a_staleness_exclusion_never_suppresses_the_leak_guard(self, poller, monkeypatch,
                                                                   capsys):
        # A CLOSED archive stamped in the future is exactly as leaky as a live one, so AHEAD
        # outranks STATIC in the reason precedence.
        blobs = {self.MPOC_KEY: _parquet_bytes("year_ending_date", ["2027-02-01"])}
        rc, _s3, _cw = _run_objects(
            poller, monkeypatch, ["--tables", "silver_mpoc_exports_by_country"],
            listing={self.MPOC_PREFIX: [(self.MPOC_KEY, _ago(1.0))]}, blobs=blobs)
        assert rc == 0
        out = capsys.readouterr().out
        assert "data=AHEAD" in out
        assert "ahead=1" in out
        assert "static=0" in out

    def test_the_known_ahead_set_is_pinned_by_name_and_explains_itself(self):
        # The map documents the alarm's first red; it must never become a threshold. Every key is
        # a live target that DECLARES an axis, and every value carries its measurement and remedy.
        assert list(DATA_DATE_AHEAD_KNOWN) == ["silver_nass_annual"]
        modes = {t.table: t.data_date_mode for t in all_poll_targets()}
        for table, why in DATA_DATE_AHEAD_KNOWN.items():
            assert modes.get(table) not in (None, AXIS_UNDECLARED, AXIS_INGEST), table
            assert "2027-02-01" in why and "Remedy" in why


class TestTheRollbackLeverAnnouncesItself:
    """Review m2. ``--no-data-date`` takes the content axis dark; it may not do so in silence."""

    def test_the_disabled_reason_is_emitted_and_counts_what_went_dark(self, poller, monkeypatch,
                                                                     capsys):
        declared = [t for t in all_poll_targets()
                    if t.data_date_mode not in (AXIS_UNDECLARED, AXIS_INGEST)]
        _rc, _s3, cw = _run(poller, monkeypatch, ["--no-data-date"],
                            default=("part.parquet", _ago(1.0)))
        unread = [d for d in cw.datums if d["MetricName"] == DATA_DATE_UNREAD_METRIC_NAME]
        by_reason = {d["Dimensions"][0]["Value"]: d["Value"] for d in unread}
        assert by_reason[UNREAD_DISABLED] == float(len(declared)) > 0
        assert set(by_reason) == set(UNREAD_REASONS)
        assert "DISABLED by --no-data-date" in capsys.readouterr().out

    def test_the_write_axis_is_still_byte_identical_under_the_lever(self, poller, monkeypatch):
        # The one datum the lever adds is on the DATA-axis metric; the pre-P6 WRITE payload is
        # untouched, which is what census threat T8 actually asked for.
        _rc, _s3, cw = _run(poller, monkeypatch, ["--no-data-date"],
                            default=("part.parquet", _ago(1.0)))
        assert not [d for d in cw.datums
                    if d["MetricName"] in (DATA_DATE_METRIC_NAME, DATA_DATE_RATIO_METRIC_NAME)]
        assert [d for d in cw.datums if d["MetricName"] == DATA_DATE_UNREAD_METRIC_NAME
                and d["Value"] > 0] != []


class TestTheEmittedCountIsPrintedNotDerived:
    """Review m1. Round 1's report said "0 -> 30 targets emitting" off a run that emitted 29."""

    SAGIS_PREFIX = "silver/sagis_weekly_exports/"
    SAGIS_KEY = SAGIS_PREFIX + "part-000.parquet"

    def test_the_printed_figure_equals_the_datums_that_reached_cloudwatch(
            self, poller, monkeypatch, capsys):
        blobs = {self.SAGIS_KEY: _parquet_bytes("week_ending_date", ["2024-04-26", "2024-03-01"])}
        rc, _s3, cw = _run_objects(
            poller, monkeypatch, [],
            listing={self.SAGIS_PREFIX: [(self.SAGIS_KEY, _ago(1.0))]},
            default=("part-000.parquet", _ago(1.0)), blobs=blobs)
        assert rc == 0
        emitted = len({d["Dimensions"][0]["Value"] for d in cw.datums
                       if d["MetricName"] == DATA_DATE_METRIC_NAME
                       and d["Dimensions"][0]["Name"] == "Table"})
        out = capsys.readouterr().out
        line = [ln for ln in out.splitlines() if "target(s) emitted a data date" in ln]
        assert len(line) == 1, out[-2000:]
        assert line[0].split("]")[1].strip().split()[0] == str(emitted)


# ---------------------------------------------------------------------------
# ROUND 3 (adversarial review M-A, 2026-09-22). THE LEDGER LIVENESS GAUGES.
#
# Round 2 asked "did the MONTHLY fold fire?" with an alarm over 35 daily evaluation periods.
# PutMetricAlarm refuses it (Period x EvaluationPeriods <= 604,800 s), so the alarm five green unit
# tests reported as delivered could never have been created. The ruling: liveness of a monthly
# process is a DAILY GAUGE the poller emits. These tests drive main() against a fake S3 and assert
# on the datums that ACTUALLY reach CloudWatch -- the same discipline the data axis is held to,
# because "the emitting half is dark" is this estate's recurring failure and a gauge nobody emits
# is exactly the alarm nobody can create.
# ---------------------------------------------------------------------------
def _every_gauge_readable():
    """A listing that satisfies EVERY declared gauge in its own source mode -- so a whole-estate
    payload assertion counts the gauges it should and does not quietly lose one to an unreadable
    prefix."""
    out = {}
    for g in LEDGER_GAUGES:
        if g.partition_key:
            day = datetime.now(timezone.utc).date().isoformat()
            out[g.prefix] = [(f"{g.prefix}{g.partition_key}={day}/document.json", _ago(1.0))]
        else:
            out[g.prefix] = [(g.prefix, _ago(1.0))]
    return out


def _gauge_by_key(key):
    """The declaration under test, read from the pure core -- never a literal copied into a deck."""
    return {g.key: g for g in LEDGER_GAUGES}[key]


class _RaisingS3(_FakeS3):
    """A listing that raises for ONE prefix -- the blast-radius probe for a telemetry leg."""

    def __init__(self, listing=None, default=None, raise_on=()):
        super().__init__(listing, default)
        self._raise_on = tuple(raise_on)

    def paginate(self, Bucket, Prefix):  # noqa: N803 - boto3 kwarg casing
        if Prefix in self._raise_on:
            self.listed.append((Bucket, Prefix))
            raise RuntimeError("AccessDenied (simulated)")
        yield from super().paginate(Bucket, Prefix)


class TestTheLedgerLivenessGauges:
    FOLD = _gauge_by_key("corpus_fold")
    CHUNK = _gauge_by_key("corpus_chunk")
    TIP = _gauge_by_key("wasde_text")

    def _listing(self, fold_age=None, chunk_age=None, fallback_age=None, tip_age=None,
                 tip_mtime_age=None):
        out = {self.FOLD.prefix: [], self.CHUNK.prefix: [], self.FOLD.fallback_prefix: [],
               self.TIP.prefix: []}
        if fold_age is not None:
            out[self.FOLD.prefix] = [(self.FOLD.prefix, _ago(fold_age))]
        if chunk_age is not None:
            out[self.CHUNK.prefix] = [(self.CHUNK.prefix, _ago(chunk_age))]
        if fallback_age is not None:
            out[self.FOLD.fallback_prefix] = [
                (self.FOLD.fallback_prefix + "20260821T212319Z.json", _ago(fallback_age))]
        if tip_age is not None:
            # the KEY carries the content date; the mtime is deliberately DIFFERENT, because that
            # gap is the whole reason this gauge reads the partition (H-L5-R3-2).
            day = (datetime.now(timezone.utc) - timedelta(days=tip_age)).date().isoformat()
            mtime = _ago(tip_mtime_age if tip_mtime_age is not None else tip_age)
            out[self.TIP.prefix] = [
                (f"{self.TIP.prefix}release_date={day}/document.json", mtime),
                (f"{self.TIP.prefix}release_date={day}/pages/0001.json", mtime)]
        return out

    def _ages(self, cw):
        return {d["MetricName"]: d["Value"] for d in cw.datums
                if d["MetricName"] in {g.metric_name for g in LEDGER_GAUGES}}

    def test_the_declaration_carries_the_bound_and_its_basis(self):
        # The gauge declaration is the ONE place the threshold lives: the generator reads it for
        # the alarm and the poller prints it beside the reading, so the console and the alarm can
        # never disagree about what "too old" means.
        assert [g.key for g in LEDGER_GAUGES] == ["corpus_fold", "corpus_chunk", "wasde_text"]
        assert self.FOLD.metric_name == "CorpusFoldAgeDays"
        assert self.CHUNK.metric_name == "CorpusChunkAgeDays"
        assert self.TIP.metric_name == "WasdeTextAgeDays"
        assert (self.FOLD.threshold_days, self.CHUNK.threshold_days, self.TIP.threshold_days) \
            == (35.0, 10.0, 40.0)
        assert (self.FOLD.family, self.CHUNK.family, self.TIP.family) == \
            ("graphrag_evidence", "graphrag_evidence", "usda_wasde")
        for g in LEDGER_GAUGES:
            assert g.bucket == "leviathan-dev-shahem-001"
            # a ledger gauge names ONE key; a partition gauge names a DIRECTORY of dated keys
            assert g.prefix.endswith(".json" if g.partition_key is None else "/"), g.prefix
            assert "days" in g.basis and g.cadence, g.key
            assert g.alarmed_by, g.key                    # neither half may go orphan
        # the partition-vs-mtime decision is DECLARED per gauge, never assumed
        assert [g.partition_key for g in LEDGER_GAUGES] == [None, None, "release_date"]

    def test_the_prefixes_are_the_producers_OWN_ledger_constants(self):
        # A hand-copied S3 key is how the R7a drift class starts. Both constants live in files this
        # lane does not own, so each is pinned against its producer's source when that source is in
        # the tree -- and the fold gauge additionally carries a FALLBACK, which is what makes it
        # readable at all before the ledger's first write (measured 2026-09-22: graphrag_evidence/
        # fold/ lists EMPTY, eval/write_manifest_rebuild_20260821T212319Z.json does not).
        repo = Path(__file__).resolve().parents[3]
        fold_src = repo / "jobs" / "batch" / "corpus_fold_task.py"
        if fold_src.exists() and "FOLD_LEDGER_SUFFIX" in fold_src.read_text(encoding="utf-8"):
            m = re.search(r'FOLD_LEDGER_SUFFIX\s*=\s*"([^"]+)"',
                          fold_src.read_text(encoding="utf-8"))
            assert m and self.FOLD.prefix.endswith(m.group(1)), (self.FOLD.prefix, m)
        else:                       # the producer's half is not in this tree yet
            assert self.FOLD.fallback_prefix, "the fold gauge would have NO readable source"
        from leviathan.graphrag.corpus_coverage import LEDGER_SUFFIX

        assert self.CHUNK.prefix.endswith(LEDGER_SUFFIX)
        assert self.CHUNK.fallback_prefix is None   # no honest fallback: see the declaration

    def test_an_unfiltered_run_emits_one_age_datum_per_gauge(self, poller, monkeypatch):
        rc, _s3, cw = _run(poller, monkeypatch, ["--no-data-date"],
                           listing=self._listing(fold_age=12.0, chunk_age=3.0, tip_age=5.0),
                           default=("part.parquet", _ago(1.0)))
        assert rc == 0
        ages = self._ages(cw)
        assert set(ages) == {"CorpusFoldAgeDays", "CorpusChunkAgeDays", "WasdeTextAgeDays"}
        assert ages["CorpusFoldAgeDays"] == pytest.approx(12.0, abs=1e-2)
        assert ages["CorpusChunkAgeDays"] == pytest.approx(3.0, abs=1e-2)
        assert ages["WasdeTextAgeDays"] == pytest.approx(5.0, abs=0.51)   # a DATE, not an instant
        by_metric = {g.metric_name: g for g in LEDGER_GAUGES}
        for d in cw.datums:
            if d["MetricName"] in ages:
                assert d["Dimensions"] == [
                    {"Name": "Family", "Value": by_metric[d["MetricName"]].family}]
                assert d["Unit"] == "None"

    def test_the_gauge_crosses_its_OWN_bound_and_the_line_says_so(self, poller, monkeypatch, capsys):
        # 40 days on the fold (bound 35) and 3 on the chunk pass (bound 10): one breach, one not,
        # in the same cycle -- so the line is reading each gauge's own number, not a shared one.
        rc, _s3, cw = _run(poller, monkeypatch, ["--no-data-date"],
                           listing=self._listing(fold_age=40.0, chunk_age=3.0),
                           default=("part.parquet", _ago(1.0)))
        out = capsys.readouterr().out
        assert rc == 0
        assert "CorpusFoldAgeDays=40.0" in out and "LIVENESS-BREACH" in out
        assert "bound=35d" in out and "bound=10d" in out
        chunk_line = [ln for ln in out.splitlines() if "CorpusChunkAgeDays" in ln][0]
        assert "LIVENESS-BREACH" not in chunk_line
        # the BREACH is a reading, never a suppression: the datum is emitted either way
        assert self._ages(cw)["CorpusFoldAgeDays"] == pytest.approx(40.0, abs=1e-2)

    def test_the_fallback_is_read_ONLY_when_the_ledger_prefix_is_empty(self, poller, monkeypatch,
                                                                      capsys):
        # (a) ledger present -> the fallback prefix is never even listed.
        _rc, s3, cw = _run(poller, monkeypatch, ["--no-data-date"],
                           listing=self._listing(fold_age=2.0, chunk_age=1.0, fallback_age=99.0),
                           default=("part.parquet", _ago(1.0)))
        assert self.FOLD.fallback_prefix not in [pfx for _b, pfx in s3.listed]
        assert self._ages(cw)["CorpusFoldAgeDays"] == pytest.approx(2.0, abs=1e-2)
        # (b) ledger empty -> the fallback serves the reading AND the line says which artifact did
        _rc, s3, cw = _run(poller, monkeypatch, ["--no-data-date"],
                           listing=self._listing(chunk_age=1.0, fallback_age=31.9),
                           default=("part.parquet", _ago(1.0)))
        out = capsys.readouterr().out
        assert self.FOLD.fallback_prefix in [pfx for _b, pfx in s3.listed]
        assert self._ages(cw)["CorpusFoldAgeDays"] == pytest.approx(31.9, abs=1e-2)
        assert "[FALLBACK]" in out and "write_manifest_rebuild_20260821T212319Z.json" in out

    def test_an_unreadable_gauge_emits_NOTHING_AND_FABRICATES_NOTHING(self, poller, monkeypatch,
                                                                     capsys):
        # THE FENCE DIRECTION. A 0 would read as "the fold ran today" and a 999 would invent a
        # measurement nobody made. No datum, a printed reason, and the alarm's
        # treat_missing_data=breaching owns the silence -- which is why the alarm may not be
        # applied before one cycle has emitted.
        rc, _s3, cw = _run(poller, monkeypatch, ["--no-data-date"],
                           listing=self._listing(), default=("part.parquet", _ago(1.0)))
        out = capsys.readouterr().out
        assert rc == 0
        assert self._ages(cw) == {}
        assert "CorpusFoldAgeDays UNREADABLE" in out and "CorpusChunkAgeDays UNREADABLE" in out
        assert "no object" in out and "breaching owns this silence" in out

    def test_a_raising_ledger_read_never_takes_the_WRITE_AXIS_down(self, poller, monkeypatch):
        # The blast radius that matters: all 26 write-axis alarms are treat_missing_data=breaching,
        # so one unhandled exception in a telemetry leg would withhold every FreshnessLagDays datum
        # and page 21 owners at once. The gauge fails alone.
        s3 = _RaisingS3(self._listing(chunk_age=1.0), ("part.parquet", _ago(1.0)),
                        raise_on=(self.FOLD.prefix, self.FOLD.fallback_prefix))
        cw = _FakeCloudWatch()
        monkeypatch.setattr(poller, "boto3", _FakeBoto3(s3, cw))
        rc = poller.main(["--no-data-date"])
        assert rc == 0
        assert [d for d in cw.datums if d["MetricName"] == METRIC_NAME], "write axis went dark"
        ages = self._ages(cw)
        assert "CorpusFoldAgeDays" not in ages          # the one that raised
        assert ages["CorpusChunkAgeDays"] == pytest.approx(1.0, abs=1e-2)   # the one beside it

    def test_a_filtered_run_never_publishes_them(self, poller, monkeypatch, capsys):
        # Same rule as FreshnessTargetsPolled and the breach counts: --tables is a spot check of
        # named tables, and an estate-wide gauge emitted from a partial run would overwrite the
        # real one at this timestamp.
        _rc, _s3, cw = _run(poller, monkeypatch,
                            ["--tables", "silver_fgis", "--no-data-date"],
                            listing=self._listing(fold_age=2.0, chunk_age=1.0),
                            default=("part.parquet", _ago(1.0)))
        assert self._ages(cw) == {}
        assert "[ledger] SUPPRESSED" in capsys.readouterr().out

    def test_the_rollback_lever_announces_itself_and_the_alarm_owns_it(self, poller, monkeypatch,
                                                                      capsys):
        # The m2 class, answered up front: a lever that takes an axis dark must say so. This one
        # cannot even be quiet for a day -- both alarms are breaching, so the missing datapoints
        # page. The line says that in as many words.
        _rc, s3, cw = _run(poller, monkeypatch, ["--no-data-date", "--no-ledger-age"],
                           listing=self._listing(fold_age=2.0, chunk_age=1.0),
                           default=("part.parquet", _ago(1.0)))
        out = capsys.readouterr().out
        assert self._ages(cw) == {}
        assert self.FOLD.prefix not in [pfx for _b, pfx in s3.listed]     # no LIST either
        assert "DISABLED by --no-ledger-age" in out and "breaching" in out

    def test_the_gauges_ride_BESIDE_the_write_axis_and_never_in_front_of_it(self, poller,
                                                                           monkeypatch):
        # Census threat T8's rule, applied to the third axis: adding it may not move the payload
        # the 26 applied alarms read. Two runs, one with the gauges and one without, compared at
        # the datum level on the write-axis names only.
        listing = self._listing(fold_age=2.0, chunk_age=1.0)
        _rc, _s3, on = _run(poller, monkeypatch, ["--no-data-date"], listing=listing,
                            default=("part.parquet", _ago(1.0)))
        _rc, _s3, off = _run(poller, monkeypatch, ["--no-data-date", "--no-ledger-age"],
                             listing=listing, default=("part.parquet", _ago(1.0)))
        keys = (METRIC_NAME, RATIO_METRIC_NAME, BREACH_METRIC_NAME)
        a = [d for d in on.datums if d["MetricName"] in keys]
        b = [d for d in off.datums if d["MetricName"] in keys]
        assert len(a) == len(b) > 0
        for x, y in zip(a, b):
            assert {k: v for k, v in x.items() if k not in ("Timestamp", "Value")} == \
                   {k: v for k, v in y.items() if k not in ("Timestamp", "Value")}
            assert x["Value"] == pytest.approx(y["Value"], abs=1e-3)

    def test_the_TIP_gauge_reads_the_PARTITION_and_not_the_MTIME(self, poller, monkeypatch):
        # THE MEASURED BLINDNESS, pinned. Live on 2026-09-22 the WASDE text prefix held 876 objects
        # whose newest mtime was 2026-08-20 (33.2 days -- GREEN at a 40-day bound) over a newest
        # release_date partition of 2026-08-12 (41.0 days -- RED): a bulk re-write of documents
        # whose release dates are months older. An mtime gauge would have called the exact estate
        # state the text lane was opened to end healthy.
        rc, _s3, cw = _run(poller, monkeypatch, ["--no-data-date"],
                           listing=self._listing(tip_age=41.0, tip_mtime_age=33.2),
                           default=("part.parquet", _ago(1.0)))
        assert rc == 0
        age = self._ages(cw)["WasdeTextAgeDays"]
        assert age == pytest.approx(41.0, abs=0.51)      # the DATA date
        assert age > self.TIP.threshold_days             # ... and it breaches, as it must
        assert age != pytest.approx(33.2, abs=0.5)       # NOT the write date

    def test_a_FORWARD_dated_partition_publishes_no_age_at_all(self, poller, monkeypatch, capsys):
        # The data axis's own ruling, carried onto this gauge: a future date is not a freshness
        # figure, so nothing is published -- and because this alarm is breaching, the silence pages
        # instead of reading as a very fresh tip. A clamped 0 would have been the fabrication.
        rc, _s3, cw = _run(poller, monkeypatch, ["--no-data-date"],
                           listing=self._listing(tip_age=-30.0),
                           default=("part.parquet", _ago(1.0)))
        out = capsys.readouterr().out
        assert rc == 0
        assert "WasdeTextAgeDays" not in self._ages(cw)
        assert "AHEAD of the clock" in out

    def test_an_unparseable_partition_is_a_REASON_never_a_guess(self, poller, monkeypatch, capsys):
        rc, _s3, cw = _run(
            poller, monkeypatch, ["--no-data-date"],
            listing={self.TIP.prefix: [(self.TIP.prefix + "release_date=latest/document.json",
                                        _ago(1.0))]},
            default=("part.parquet", _ago(1.0)))
        out = capsys.readouterr().out
        assert rc == 0
        assert "WasdeTextAgeDays" not in self._ages(cw)
        assert "did not parse as a date" in out

    def test_the_gauge_costs_one_LIST_and_NO_GET(self, poller, monkeypatch):
        # The ledger is written once per fire, so LastModified IS the fire's end within seconds:
        # no GetObject, no JSON parse, no schema, no new IAM. (The data axis pays for footer GETs
        # because a parquet's CONTENT date is not its write time; a ledger's is.)
        blobs = {}
        s3 = _FakeS3WithObjects(self._listing(fold_age=2.0, chunk_age=1.0, tip_age=5.0),
                                ("part.parquet", _ago(1.0)), blobs)
        cw = _FakeCloudWatch()
        monkeypatch.setattr(poller, "boto3", _FakeBoto3(s3, cw))
        rc = poller.main(["--no-data-date"])
        assert rc == 0
        assert s3.ranges == []
        assert len(self._ages(cw)) == len(LEDGER_GAUGES)

