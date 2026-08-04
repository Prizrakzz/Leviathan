"""SILVER-F082 freshness poller pure core (leviathan.silver.freshness).

The age computation, the canonical-only (shadow/staging) exclusion, the empty-prefix behaviour, and
the poll-target derivation must all be correct against a FAKE S3 listing -- no boto3, no network.

D-PR-14 adds the normalized companion metric ``FreshnessLagRatio = lag / declared ceiling``. Its
tests use a FAKE ceiling wherever the maths is under test, so they pin the arithmetic rather than
today's registry values; the two places that must track the live estate (the per-table declared
ceilings, and the poller actually passing the denominator) are pinned separately and explicitly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from leviathan.silver.freshness import (
    EXTRA_TARGETS,
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
    """The emitter half is dead if the SCRIPT never passes ``expected``.

    These are TEXT pins on the source, and text pins are exactly as strong as the string they
    match -- ``"expected=expected" in src`` stays green for a call that is dead, mis-scoped, or
    never reached. They are kept because they name the requirement in one line, but the load-bearing
    coverage is :class:`TestPollerEndToEnd` below, which runs ``main()`` against a fake S3 + a fake
    CloudWatch and reads the datums that ACTUALLY arrive at ``put_metric_data``."""

    @staticmethod
    def _src() -> str:
        from pathlib import Path
        repo = Path(__file__).resolve().parents[3]
        return (repo / "scripts" / "silver" / "freshness_poller.py").read_text(encoding="utf-8")

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
    """The script, loaded as a module. It is under scripts/ (not a package), so importlib by path."""
    import importlib.util
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "freshness_poller_under_test", repo / "scripts" / "silver" / "freshness_poller.py")
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
    EPISODES_PREFIX = "graphrag_evidence/timeline/"

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
            assert d["Value"] == pytest.approx(7.0 / 14.0, abs=1e-3)   # ceiling 14
        for d in days:
            assert d["Value"] == pytest.approx(7.0, abs=1e-3)
        assert cw.namespaces == [METRIC_NAMESPACE]

    def test_each_table_is_normalized_by_its_OWN_ceiling(self, poller, monkeypatch):
        # D-PR-14 in one run: two targets with DIFFERENT ages (7d and 5d) and DIFFERENT ceilings
        # (14 and 10) land on the SAME 0.5 ratio. That equality is the property the family-level
        # statistic=Maximum needs and that FreshnessLagDays cannot give it.
        rc, _s3, cw = _run(
            poller, monkeypatch,
            ["--tables", "silver_fgis,graphrag_timeline_episodes"],
            listing={
                self.FGIS_PREFIX: [(self.FGIS_PREFIX + "part.parquet", _ago(7.0))],
                self.EPISODES_PREFIX: [(self.EPISODES_PREFIX + "episodes.json", _ago(5.0))],
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
            listing={self.EPISODES_PREFIX: [(self.EPISODES_PREFIX + "episodes.json", _ago(2.0))]})
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
        n = len(all_poll_targets())
        rc, s3, cw = _run(poller, monkeypatch, [], default=("part.parquet", _ago(1.0)))
        assert rc == 0
        assert len(s3.listed) == n
        assert len(cw.datums) == 4 * n
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
