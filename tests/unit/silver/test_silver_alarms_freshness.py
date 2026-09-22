"""SILVER-F082 freshness-audit additions (2026-07-23):
  * the usda_nass family ceiling drops 170 -> 14 (the registry max_lag_days=170 that masked the
    stalled weekly crop_progress producer is corrected via dag_catalog.FRESHNESS_LAG_OVERRIDES);
  * per-TABLE freshness alarms exist for the four burned tables, each fully-specified, uniquely
    named, breaching, at its justified ceiling;
  * the emitted tfvars carry the per-table map and the corrected family ceiling.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from leviathan.silver.dag_catalog import FRESHNESS_LAG_OVERRIDES, build_catalog

_REPO = Path(__file__).resolve().parents[3]
_MOD = _REPO / "jobs" / "observability" / "silver_alarms.py"


@pytest.fixture(scope="module")
def sa():
    spec = importlib.util.spec_from_file_location("silver_alarms", _MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doc(sa):
    return sa.build_document()


class TestUsdaNassCorrection:
    def test_override_targets_crop_progress(self):
        assert FRESHNESS_LAG_OVERRIDES.get("silver_nass_crop_progress") == 14

    def test_family_ceiling_drops_to_14(self):
        # The mask (registry max_lag_days=170 on a weekly cadence) is corrected -> tightest member 14.
        assert build_catalog()["usda_nass"].max_sla_lag_days == 14

    def test_override_only_tightens(self):
        # Applying the override must never LOOSEN a family ceiling vs the raw registry-derived value.
        cat = build_catalog()
        assert cat["usda_nass"].max_sla_lag_days <= 170


class TestPerTableAlarms:
    def test_one_alarm_per_burned_table(self, sa, doc):
        # FENCE 2 leg 3 widens this from the four burned tables to burned + non-registry ARTIFACTS.
        # BURNED_TABLE_FRESHNESS itself is left untouched so the historical four keep meaning what
        # they say; the artifact map is a separate dict merged into the same loop.
        table_alarms = [a for a in doc["alarms"] if a["failure_mode"] == "freshness_sla_breach_table"]
        assert {a["table"] for a in table_alarms} == set(sa.BURNED_TABLE_FRESHNESS) | set(sa.ARTIFACT_FRESHNESS)
        assert len(table_alarms) == 5

    def test_thresholds_and_dimensions(self, sa, doc):
        by_table = {a["table"]: a for a in doc["alarms"] if a["failure_mode"] == "freshness_sla_breach_table"}
        for table, (family, max_lag, _basis) in sa.BURNED_TABLE_FRESHNESS.items():
            a = by_table[table]
            assert a["threshold"] == max_lag
            # Single-dim {Table}: MUST match the poller's {Table} datapoint. A {Table,Family} composite
            # is never emitted (freshness.metric_data_for writes {Table} and {Family} SEPARATELY), so a
            # composite-dimensioned alarm would get no data and, under breaching, page permanently.
            assert a["dimensions"] == {"Table": table}
            assert a["family"] == family  # family is carried as a field (description), not a dimension
            assert a["metric_name"] == "FreshnessLagDays"
            assert a["treat_missing_data"] == "breaching"

    def test_specified_thresholds(self, doc):
        by_table = {a["table"]: a for a in doc["alarms"] if a.get("failure_mode") == "freshness_sla_breach_table"}
        assert by_table["silver_nass_crop_progress"]["threshold"] == 14
        # D-LD (2026-08-18, review wf_31e951c7): STAYS 14. A first fold moved this to 27 by adding
        # the fgis card's 13d publication lag as grace -- a category error: this alarm reads S3
        # WRITE recency and the Thursday fire writes weekly regardless of content lag. The lag
        # guards the card's AS-OF axis; TABLE_CEILING_OVERRIDES pins the poller to the same 14.
        assert by_table["silver_fgis"]["threshold"] == 14
        assert by_table["silver_unica_biweekly_season_history"]["threshold"] == 21
        assert by_table["silver_nass_citrus"]["threshold"] == 400

    def test_per_table_alarms_carry_full_contract(self, sa, doc):
        table_alarms = [a for a in doc["alarms"] if a["failure_mode"] == "freshness_sla_breach_table"]
        for a in table_alarms:
            assert not [k for k in sa.REQUIRED_ALARM_KEYS if k not in a]

    def test_all_alarm_names_unique_incl_per_table(self, doc):
        names = [a["alarm_name"] for a in doc["alarms"]]
        assert len(names) == len(set(names))

    def test_two_burned_tables_share_family_but_not_name(self, doc):
        # crop_progress + citrus are both usda_nass -> the name must key on the TABLE, not the family.
        nass = [a for a in doc["alarms"]
                if a["failure_mode"] == "freshness_sla_breach_table" and a["family"] == "usda_nass"]
        assert len(nass) == 2
        assert len({a["alarm_name"] for a in nass}) == 2


class TestTimelineArtifactAlarm:
    """FENCE 2 leg 3 (incident I-2): the graphrag timeline artifact gets a DAILY freshness clock on
    the EXISTING per-table alarm resource -- no parallel observability system, no module change.

    Every assertion here fails if ARTIFACT_FRESHNESS is dropped or its shape drifts away from what
    `aws_cloudwatch_metric_alarm.freshness_sla_breach_table` (modules/silver_observability/main.tf)
    actually renders. The artifact was built 2026-07-04 and nothing measured its age for 27 days.
    """

    ARTIFACT = "graphrag_timeline_episodes"

    def test_artifact_is_registered_for_freshness(self, sa):
        assert sa.ARTIFACT_FRESHNESS[self.ARTIFACT][0] == "graphrag_evidence"
        assert sa.ARTIFACT_FRESHNESS[self.ARTIFACT][1] == 10          # weekly rebuild + 3d grace
        # The artifact is NOT a burned registry table -- the two maps must stay disjoint, or the
        # historical four stop meaning "the four the 2026-07-23 audit found stale-green".
        assert not set(sa.ARTIFACT_FRESHNESS) & set(sa.BURNED_TABLE_FRESHNESS)

    def test_alarm_exists_with_the_poller_dimension_contract(self, sa, doc):
        by_table = {a["table"]: a for a in doc["alarms"]
                    if a["failure_mode"] == "freshness_sla_breach_table"}
        a = by_table[self.ARTIFACT]
        # Single-dim {Table}: freshness.metric_data_for emits {Table} and {Family} SEPARATELY, so a
        # composite dimension would receive no data and, under breaching, page forever.
        assert a["dimensions"] == {"Table": self.ARTIFACT}
        assert a["metric_name"] == "FreshnessLagDays"
        assert a["metric_namespace"] == "Leviathan/Silver"    # == freshness.METRIC_NAMESPACE
        assert a["threshold"] == 10
        assert a["family"] == "graphrag_evidence"
        # An ABSENT artifact makes the poller emit NO datapoint at all; "breaching" is what turns
        # that silence into a page after one day, which is the I-2 fail-open half.
        assert a["treat_missing_data"] == "breaching"
        assert not [k for k in sa.REQUIRED_ALARM_KEYS if k not in a]

    def test_alarm_name_keys_on_the_table_and_is_unique(self, sa, doc):
        names = [a["alarm_name"] for a in doc["alarms"]]
        assert len(names) == len(set(names))
        by_table = {a["table"]: a for a in doc["alarms"]
                    if a["failure_mode"] == "freshness_sla_breach_table"}
        assert "graphrag-timeline-episodes" in by_table[self.ARTIFACT]["alarm_name"]

    def test_tfvars_carry_the_artifact(self, sa):
        tfm = sa.build_tfvars()["silver_table_freshness_slas"]
        assert tfm[self.ARTIFACT] == {
            "family": "graphrag_evidence",
            "threshold": 10,
            "basis": sa.ARTIFACT_FRESHNESS[self.ARTIFACT][2],
        }

    def test_alarm_matches_the_poll_target(self, sa, doc):
        # The alarm's Table dimension MUST equal the poller's target name, or the alarm watches a
        # metric nothing writes -- hollow-alarm mode, which is the whole reason F082 exists.
        from leviathan.silver.freshness import all_poll_targets, poll_targets
        emitted = {t.table for t in all_poll_targets()}
        assert self.ARTIFACT in emitted
        assert self.ARTIFACT not in {t.table for t in poll_targets()}


class TestTfvars:
    def test_family_ceiling_corrected_in_tfvars(self, sa):
        assert sa.build_tfvars()["silver_freshness_slas"]["usda_nass"] == 14

    def test_table_freshness_map_present(self, sa):
        tfm = sa.build_tfvars()["silver_table_freshness_slas"]
        assert set(tfm) == set(sa.BURNED_TABLE_FRESHNESS) | set(sa.ARTIFACT_FRESHNESS)
        for table, (family, threshold, basis) in {**sa.BURNED_TABLE_FRESHNESS,
                                                  **sa.ARTIFACT_FRESHNESS}.items():
            assert tfm[table] == {"family": family, "threshold": threshold, "basis": basis}

    def test_emitted_tfvars_file_matches(self, sa):
        import json
        path = _REPO / "infra" / "terraform" / "envs" / "dev" / "silver_observability.auto.tfvars.json"
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk == sa.build_tfvars()


# ---------------------------------------------------------------------------
# P6 / P7 -- THE DATA-AXIS ALARMS AND THE POLLER'S OWN CENSUS (2026-09-22 pipeline census).
#
# THE GAP: every alarm class this file emitted before today reads S3 WRITE RECENCY. A producer that
# re-writes a byte-identical object on its fire cadence is therefore GREEN forever while its content
# is dead, and the estate carried 52 alarms on write dates and ZERO on data dates. MEASURED by a
# read-only poll of the live estate on 2026-09-22: silver_sagis_weekly_exports FreshnessLagRatio
# 0.211 (green) beside DataDateAgeRatio 46.263; silver_unica_corn_ethanol 0.430 beside 16.643;
# eleven tables over 1.0 on the data axis against nine on the write axis, and only two of those
# eleven overlapping.
# ---------------------------------------------------------------------------
from leviathan.silver.freshness import (  # noqa: E402
    DATA_DATE_AHEAD_KNOWN,
    STATIC_DATA_TARGETS,
    data_date_alarm_targets,
    data_date_undeclared_tables,
)


class TestDataDateAlarms:
    def test_one_alarm_per_declared_data_axis_target(self, doc):
        alarms = [a for a in doc["alarms"] if a["failure_mode"] == "data_date_age_breach"]
        assert {a["table"] for a in alarms} == set(data_date_alarm_targets())
        assert len(alarms) == len(set(data_date_alarm_targets()))

    def test_the_contract_is_the_ratio_at_one_on_the_pollers_own_dimension(self, doc):
        for a in (a for a in doc["alarms"] if a["failure_mode"] == "data_date_age_breach"):
            # DataDateAgeRatio{Table} single-dim: it must MATCH what the poller emits. The poller
            # writes one {Table} datum and a SEPARATE {Family} datum; a {Table,Family} composite is
            # never written by the poller, so a composite alarm would get no data forever.
            assert a["metric_name"] == "DataDateAgeRatio"
            assert a["dimensions"] == {"Table": a["table"]}
            assert a["metric_namespace"] == "Leviathan/Silver"
            assert a["threshold"] == 1.0
            assert a["comparison_operator"] == "GreaterThanThreshold"
            assert a["statistic"] == "Maximum"
            assert a["period_seconds"] == 86400

    def test_missing_is_not_breaching_here_and_the_blindness_has_its_own_alarm(self, doc):
        # THE ONE DEPARTURE FROM THE FRESHNESS ALARMS' POSTURE, and the reason it is safe. Making
        # ~31 per-table alarms treat_missing_data="breaching" would put every one of them into
        # ALARM on the apply that CREATES them, before the image carrying the emitter ships -- the
        # hazard modules/silver_observability's header names for the pre-emit families, multiplied
        # by thirty-one. Absence is instead alarmed ONCE, precisely.
        breach = [a for a in doc["alarms"] if a["failure_mode"] == "data_date_age_breach"]
        assert breach and all(a["treat_missing_data"] == "notBreaching" for a in breach)
        unread = [a for a in doc["alarms"] if a["failure_mode"] == "data_date_unread"]
        assert len(unread) == 1
        assert unread[0]["metric_name"] == "DataDateUnread"
        assert unread[0]["dimensions"] == {"Reason": "unreadable"}
        assert unread[0]["threshold"] == 0
        assert unread[0]["comparison_operator"] == "GreaterThanThreshold"

    def test_no_alarm_for_an_undeclared_axis(self, doc):
        # An alarm nothing ever feeds is worse than no alarm: it reads as coverage.
        named = {a.get("table") for a in doc["alarms"]
                 if a["failure_mode"] == "data_date_age_breach"}
        assert named.isdisjoint(data_date_undeclared_tables())

    def test_no_alarm_for_a_declared_closed_archive(self, doc):
        # Census threat T8: switching the axis on with no static declarations pages forever on
        # mpoc trade stats (1,025 days) and mpoc exports (996), and "a loud board nobody believes
        # is the failure this whole census is about".
        named = {a.get("table") for a in doc["alarms"]
                 if a["failure_mode"] == "data_date_age_breach"}
        assert named.isdisjoint(STATIC_DATA_TARGETS)

    def test_the_stale_green_class_is_covered(self, doc):
        named = {a.get("table") for a in doc["alarms"]
                 if a["failure_mode"] == "data_date_age_breach"}
        # The five tables the census measured stale-green, minus the two whose contract declares no
        # data axis at all (mpoc_stock_comparison, and unica_biweekly_release_series) -- those are
        # named in freshness.data_date_undeclared_tables() and are a descriptor lane's work.
        assert {"silver_sagis_weekly_exports", "silver_unica_corn_ethanol",
                "silver_unica_biweekly_season_history",
                "silver_unica_monthly_ethanol_sales"} <= named

    def test_the_write_axis_alarm_set_did_not_move(self, doc):
        # ALONGSIDE, NEVER INSTEAD. Not one existing alarm may change shape because a new axis
        # arrived beside it.
        for mode, metric in (("freshness_sla_breach", "FreshnessLagDays"),
                             ("freshness_sla_breach_table", "FreshnessLagDays")):
            group = [a for a in doc["alarms"] if a["failure_mode"] == mode]
            assert group and all(a["metric_name"] == metric for a in group)
            assert all(a["treat_missing_data"] == "breaching" for a in group)

    def test_every_data_date_alarm_carries_the_full_contract(self, sa, doc):
        for a in (a for a in doc["alarms"]
                  if a["failure_mode"] in ("data_date_age_breach", "data_date_unread",
                                           "data_date_ahead", "freshness_targets_polled")):
            for key in sa.REQUIRED_ALARM_KEYS:
                assert key in a, (a["alarm_name"], key)

    def test_all_alarm_names_stay_unique(self, doc):
        names = [a["alarm_name"] for a in doc["alarms"]]
        assert len(names) == len(set(names))


class TestTargetsPolledAlarm:
    def test_it_exists_and_is_generated_from_the_registry(self, sa, doc):
        # P7. MEASURED 2026-09-21: the scheduled poller printed "46 targets" while the repo
        # registry enumerated 53 -- a baked image five weeks behind HEAD, with four contracts
        # unmeasured and a RETIRED surface still polled, and nothing anywhere compared the two.
        got = [a for a in doc["alarms"] if a["failure_mode"] == "freshness_targets_polled"]
        assert len(got) == 1
        a = got[0]
        assert a["metric_name"] == "FreshnessTargetsPolled"
        assert a["dimensions"] == {}
        assert a["comparison_operator"] == "LessThanThreshold"
        assert a["threshold"] == float(sa.build_tfvars()["silver_expected_poll_targets"])

    def test_a_dead_poller_pages(self, doc):
        # No census datapoint == the poller did not run. This is the ONE new alarm that must be
        # "breaching" on missing data, and it is what lets everything else be notBreaching.
        a = [x for x in doc["alarms"] if x["failure_mode"] == "freshness_targets_polled"][0]
        assert a["treat_missing_data"] == "breaching"

    def test_the_threshold_is_never_a_hand_written_literal(self, sa):
        from leviathan.silver.freshness import all_poll_targets
        assert sa.build_tfvars()["silver_expected_poll_targets"] == len(all_poll_targets())


class TestDataDateTfvars:
    def test_the_map_is_emitted_and_matches_the_pure_core(self, sa):
        tfm = sa.build_tfvars()["silver_data_date_slas"]
        expected = {t: v for t, v in data_date_alarm_targets().items()
                    if v[0] not in sa.PRE_PUBLISH_FAMILIES}
        assert set(tfm) == set(expected)
        for table, (family, ceiling, basis) in expected.items():
            assert tfm[table] == {"family": family, "ratio_threshold": 1.0,
                                  "ceiling_days": ceiling, "basis": basis}

    def test_pre_publish_families_are_filtered_exactly_as_the_write_axis_filters_them(self, sa):
        # silver_moex_agro_indices and silver_ams_gtr are registered ahead of their producers and
        # their canonical prefixes are EMPTY (verified by listing, 2026-09-22). An alarm on them
        # would watch an absence somebody deliberately created.
        tfm = sa.build_tfvars()["silver_data_date_slas"]
        assert all(v["family"] not in sa.PRE_PUBLISH_FAMILIES for v in tfm.values())

    def test_the_static_declarations_ride_into_the_applied_variables(self, sa):
        assert sa.build_tfvars()["silver_data_date_static"] == dict(sorted(
            STATIC_DATA_TARGETS.items()))

    def test_the_pre_existing_tfvars_keys_did_not_move(self, sa):
        # Census threat T8's BYTE-IDENTICAL SET at the infrastructure boundary: the new axis adds
        # keys and changes NONE, so no applied alarm attribute moves on the next apply.
        tf = sa.build_tfvars()
        assert set(tf) == {
            "silver_metric_namespace", "silver_batch_families", "silver_freshness_slas",
            "silver_table_freshness_slas", "silver_data_date_slas",
            "silver_expected_poll_targets", "silver_data_date_static",
        }
        assert tf["silver_freshness_slas"]["usda_nass"] == 14


class TestTheForwardStampAlarm:
    """Round 2 / review M3. The blindness class round 1 recorded, never alarmed and never pinned.

    MEASURED 2026-09-22: silver_nass_annual's declared knowledge axis (release_date) holds
    2027-02-01. It therefore publishes no DataDateAgeRatio datapoint, its per-table alarm is
    treat_missing_data="notBreaching" and reads OK forever, and the blindness alarm is scoped to
    Reason=unreadable -- so the table had left the content watch in silence.
    """

    def test_it_exists_on_its_own_reason_dimension(self, doc):
        alarms = [a for a in doc["alarms"] if a["failure_mode"] == "data_date_ahead"]
        assert len(alarms) == 1
        a = alarms[0]
        assert a["metric_name"] == "DataDateUnread"
        assert a["dimensions"] == {"Reason": "ahead"}
        assert a["comparison_operator"] == "GreaterThanThreshold"
        assert a["statistic"] == "Maximum"
        assert a["period_seconds"] == 86400

    def test_the_known_set_is_documented_and_never_excused_by_the_threshold(self, doc):
        # A threshold of len(DATA_DATE_AHEAD_KNOWN) would be round 1's silence wearing a number: it
        # would re-hide nass_annual AND the next forward-stamped contract somebody added.
        a = [x for x in doc["alarms"] if x["failure_mode"] == "data_date_ahead"][0]
        assert a["threshold"] == 0
        assert DATA_DATE_AHEAD_KNOWN, "the known set must not be empty while the finding is open"
        for table in DATA_DATE_AHEAD_KNOWN:
            assert table in a["description"], table
        assert "leak" in a["description"]

    def test_it_is_distinct_from_the_blindness_alarm(self, doc):
        # Two reasons, two alarms, two remedies: UNREADABLE means the estate cannot see the number,
        # AHEAD means it can see it and the number is in the future. One alarm meaning both would
        # be an alarm an operator learns to ignore.
        pair = {a["failure_mode"]: a for a in doc["alarms"]
                if a["failure_mode"] in ("data_date_unread", "data_date_ahead")}
        assert set(pair) == {"data_date_unread", "data_date_ahead"}
        assert pair["data_date_unread"]["dimensions"] != pair["data_date_ahead"]["dimensions"]
        assert pair["data_date_unread"]["alarm_name"] != pair["data_date_ahead"]["alarm_name"]

    def test_absence_of_the_datum_does_not_page_here(self, doc):
        # A missing datum means the poller did not run, which freshness_targets_polled already says
        # once and precisely (it is the one "breaching" alarm in this leg).
        a = [x for x in doc["alarms"] if x["failure_mode"] == "data_date_ahead"][0]
        assert a["treat_missing_data"] == "notBreaching"

    def test_the_alarm_count_moved_by_exactly_one(self, doc):
        by_mode = doc["alarms_by_failure_mode"]
        assert by_mode["data_date_ahead"] == 1
        assert by_mode["data_date_unread"] == 1
        assert by_mode["freshness_targets_polled"] == 1
        # the four pre-existing classes are untouched by round 2
        assert by_mode["batch_job_failed"] == 24
        assert by_mode["freshness_sla_breach"] == 24
        assert by_mode["freshness_sla_breach_table"] == 5
        assert by_mode["value_census_regression"] == 1
