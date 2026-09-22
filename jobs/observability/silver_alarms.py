"""SILVER-F082: alarms-as-code -- the CloudWatch alarm definitions for the silver pipeline failure
modes, derived deterministically from the SILVER-F010 registry + the SILVER-F082 DAG catalog.

WHY DERIVE, NOT HAND-WRITE
--------------------------
The plan's F082 requires an alarm per pipeline failure mode with a COMPLETE contract per alarm
(threshold / window / missing-data treatment / severity / owner / on-call destination / dedup key /
retention / tested delivery). Hand-authoring 22 families x N modes of HCL drifts from the registry
the moment a table is added. This module is the SINGLE source: it reads the registry + DAG catalog
and emits (a) a human/CI ``alarm_definitions.json`` the completeness test parses, and (b) a Terraform
``*.auto.tfvars.json`` the ``silver_observability`` module consumes -- so the code and the
infrastructure share one origin and cannot disagree.

THE FAILURE MODES COVERED (alarm classes)
-----------------------------------------
  * ``batch_job_failed``      -- one alarm PER DAG family: a Batch job in that family reached FAILED
                                 (EventBridge Batch Job State Change -> log metric filter -> alarm).
  * ``freshness_sla_breach``  -- one alarm PER family: the poller-emitted ``FreshnessLagDays{Family}``
                                 (scripts/silver/freshness_poller.py) exceeded the family's interim
                                 SLA ceiling (dag_catalog). Now emitted for real -- the metric used to
                                 be hollow (nothing published it), so the alarms could never fire.
  * ``freshness_sla_breach_table`` -- one alarm PER burned table (BURNED_TABLE_FRESHNESS): the poller-
                                 emitted ``FreshnessLagDays{Table}`` exceeded the table's own ceiling.
                                 The precise layer under the coarse per-family alarm (the four tables
                                 that ran stale-green for 6-10 weeks in the freshness audit).
  * ``value_census_regression`` -- one GLOBAL alarm: the census-emitted ``ValueCensusHardFailTables``
                                 rose above 0 (any all-NaN / single-vintage / all-constant regression
                                 after R4 -- the CHIRPS/ESR class the census exists to catch).
  * ``data_date_age_breach``  -- P6, 2026-09-22: one alarm PER poll target with a declared DATA axis:
                                 the poller-emitted ``DataDateAgeRatio{Table}`` exceeded 1.0, i.e.
                                 the table's CONTENT is older than its own ceiling. Every alarm
                                 class above this one reads S3 WRITE recency and is therefore blind
                                 to a producer that re-writes an identical object on its cadence.
  * ``data_date_unread``      -- P6: one GLOBAL alarm: a target whose data axis IS declared could
                                 not be read. This is what lets the per-table alarms above be
                                 notBreaching with no door left open.
  * ``data_date_ahead``       -- P6 round 2, review M3: one GLOBAL alarm: a target's declared
                                 knowledge axis points INTO THE FUTURE, so it publishes no age
                                 datapoint and its notBreaching per-table alarm reads OK while
                                 nothing watches its content -- and a forward-stamped knowledge row
                                 is one guard away from a point-in-time leak. RED ON ARRIVAL by
                                 design: silver_nass_annual reads 2027-02-01 today.
  * ``freshness_targets_polled`` -- P7: one GLOBAL alarm: the poller polled FEWER targets than this
                                 repo's registry declares, i.e. its image is behind HEAD. Measured
                                 2026-09-21: 46 polled against 53 declared, invisible for 5 weeks.
  * ``corpus_fold_liveness`` / ``corpus_fold_wrote_nothing`` / ``wasde_text_errors`` -- round 2,
                                 handed by the text/corpus lane: the monthly fold never fired, the
                                 fold that fired wrote nothing, and a WASDE document raised during
                                 text extraction. DOCUMENTED HERE AND NOT YET APPLIED -- their
                                 metrics have never published (measured 2026-09-22: list-metrics
                                 returns eleven names, none of them Corpus* or Wasde*), so they
                                 are deliberately absent from :func:`build_tfvars` until one fire
                                 emits. See the block that builds them for the exact gate.

Every alarm dict is fully specified (:func:`_alarm`) so the completeness test can assert the F082
contract fields are present and well-typed. Pure + AWS-free + deterministic. ASCII-only stdout.

Usage:
    python jobs/observability/silver_alarms.py                 # print the JSON to stdout
    python jobs/observability/silver_alarms.py --emit-report reports/silver_readiness/R4_F082_observability
    python jobs/observability/silver_alarms.py --emit-tfvars infra/terraform/envs/dev
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from leviathan.silver.dag_catalog import build_catalog  # noqa: E402
from leviathan.silver.freshness import (  # noqa: E402
    CLOUDWATCH_MAX_EVALUATION_SECONDS,
    DATA_DATE_AHEAD_KNOWN,
    DATA_DATE_RATIO_METRIC_NAME,
    DATA_DATE_UNREAD_METRIC_NAME,
    STATIC_DATA_TARGETS,
    TARGETS_POLLED_METRIC_NAME,
    UNREAD_AHEAD,
    UNREAD_UNREADABLE,
    all_poll_targets,
    data_date_alarm_targets,
    ledger_gauge,
    refuse_uncreatable_window,
)
from leviathan.silver.registry import load_registry  # noqa: E402

PROJECT = "leviathan"
ENVIRONMENT = "dev"
METRIC_NAMESPACE = "Leviathan/Silver"

# The severity policy (F082 "route quality/source rejections per a documented severity policy"):
#   P1 = page immediately (query-visible corruption / value regression).
#   P2 = page business hours (a family's pipeline failed / is stale).
SEV_P1 = "P1-page-immediately"
SEV_P2 = "P2-business-hours"

# Required contract keys every alarm dict MUST carry (the completeness test asserts these).
REQUIRED_ALARM_KEYS = (
    "alarm_name", "failure_mode", "family", "metric_namespace", "metric_name", "dimensions",
    "statistic", "period_seconds", "evaluation_periods", "comparison_operator", "threshold",
    "treat_missing_data", "severity", "owner", "oncall_destination", "dedup_key",
    "retention_days", "description",
)

ONCALL_TOPIC = f"{PROJECT}-{ENVIRONMENT}-silver-pipeline-alerts"  # the SNS topic (tf placeholder sub)

# ---------------------------------------------------------------------------
# PER-TABLE freshness alarms (freshness-audit lane, 2026-07-23).
# The per-FAMILY freshness alarm reads its stalest member (statistic=Maximum) against the family's
# TIGHTEST ceiling, so in a mixed-cadence family it either false-fires on a slow member or hides a
# stalled fast member behind the family aggregate. The four tables below each ran stale-green for
# 6-10 weeks; they get a PRECISE per-table alarm (dimensions {Table} -- single-dim, to MATCH the
# poller's {Table} datapoint; a {Table,Family} composite is never emitted so it would get no data)
# at their own ceiling, emitted by scripts/silver/freshness_poller.py (FreshnessLagDays, dim Table).
# Each ceiling is
# justified from the registry freshness_sla:
#   silver_nass_crop_progress            14  cadence=weekly (registry max_lag_days=170 was the MASK;
#                                            corrected via dag_catalog.FRESHNESS_LAG_OVERRIDES too)
#   silver_fgis                          14  cadence=weekly, max_lag_days=null -> weekly default
#   silver_unica_biweekly_season_history 21  biweekly release series; ~1 cycle (14d) + a half-cycle
#                                            grace so a single delayed fortnightly drop is tolerated
#                                            but a missed cycle fires (registry cadence=weekly default
#                                            14 is too tight for the fortnightly cadence)
#   silver_nass_citrus                  400  cadence=annual, max_lag_days=null -> annual default; the
#                                            citrus series is a seasonal/annual NASS product, so 400
#                                            catches a fully-missed annual cycle without false-firing
# Value: (family, max_lag_days, basis-justification).
BURNED_TABLE_FRESHNESS: dict[str, tuple[str, int, str]] = {
    "silver_nass_crop_progress": ("usda_nass", 14, "cadence_default:weekly (registry max_lag_days=170 was the mask)"),
    "silver_fgis": ("usda_fgis", 14, "cadence_default:weekly -- WRITE cadence, deliberately WITHOUT publication-lag grace (D-LD review wf_31e951c7): FreshnessLagDays measures S3 write recency, and the Thursday fire WRITES weekly regardless of the 13d content lag the card declares for its AS-OF guard. Adding the lag here (a first fold tried 27) was a category error that opened a 13d blind window on a just-promoted table; the two numbers protect different things and must not be summed"),
    "silver_unica_biweekly_season_history": ("unica", 21, "biweekly cadence: ~1 cycle (14d) + half-cycle grace"),
    "silver_nass_citrus": ("usda_nass", 400, "cadence_default:annual (seasonal/annual citrus; full-cycle miss)"),
}

# ---------------------------------------------------------------------------
# NON-REGISTRY ARTIFACT freshness alarms (FENCE 2 leg 3, incident I-2, 2026-07-31).
# Same failure_mode / metric / dimension shape as BURNED_TABLE_FRESHNESS above -- deliberately, so
# the emitted alarm_name matches what the EXISTING
# `aws_cloudwatch_metric_alarm.freshness_sla_breach_table` for_each resource renders and NO module
# change is needed. These are NOT registry tables (see leviathan.silver.freshness.EXTRA_TARGETS for
# why putting a GraphRAG serving artifact in the SILVER-F010 registry is a category error); the
# poller reaches them via `all_poll_targets()`.
#   graphrag_timeline_episodes  10  the timeline artifact serving reads. It was built 2026-07-04 and
#                                   nothing measured its age while the prop store it is derived from
#                                   grew ~74%; meanwhile timeline._load() failed OPEN, so an absent
#                                   artifact was indistinguishable from "no episodes". Ceiling is the
#                                   weekly rebuild cadence (cron 0 3 ? * SUN *) + a 3d grace, so ONE
#                                   missed rebuild breaches. treat_missing_data="breaching" means a
#                                   DELETED artifact (empty prefix -> the poller emits no datapoint)
#                                   fires the same alarm after one day.
# Value: (family, max_lag_days, basis-justification).
ARTIFACT_FRESHNESS: dict[str, tuple[str, int, str]] = {
    # D-SG G3 STEP 1 (2026-08-16): this basis string is byte-identical to the APPLIED tfvars row.
    # Commit 835ccf31 hand-edited the GENERATED file, so every regeneration since silently reverted
    # the applied text and test_emitted_tfvars_file_matches_current_registry has been red. Folding
    # the text back here makes the generator the source of truth again -- no applied alarm attribute
    # moves.
    "graphrag_timeline_episodes": (
        "graphrag_evidence", 10,
        "weekly rebuild schedule (cron 0 3 ? * SUN *, ENABLED 2026-08-05) + 3d grace; one missed "
        "RUN breaches. The signal is the run HEARTBEAT (timeline/last_run.json, touched on every "
        "successful run incl. UNCHANGED_SKIP weeks) -- schedule liveness, never content churn; "
        "the artifact itself moves only on a content change (R7.1)",
    ),
}

# ---------------------------------------------------------------------------
# FAMILIES REGISTERED AHEAD OF THEIR PRODUCERS -- excluded from the TFVARS (never from the alarm
# DOCUMENT, which keeps describing the target state).
#
# The per-family freshness alarm runs treat_missing_data = "breaching" (the 2026-07-23 flip: a
# producer that STOPS emitting must page, which is exactly the stall the freshness audit missed for
# 6-10 weeks). scripts/silver/freshness_poller.py emits NO datapoint for an EMPTY canonical prefix,
# and a family whose table has not had its first canonical publish yet has, by construction, an
# empty prefix. So declaring the alarm at registration time means it instant-breaches on the next
# dev apply and pages the shared topic continuously until the producer lands -- the same hazard the
# module's own terraform header names ("else the pre-emit families instant-breach the shared
# topic"), and the reason the flip was sequenced behind the poller in the first place.
#
# The precedent that HID this: gold_pattern_records was also registered ahead of its producer and
# escaped only incidentally, because its family sits in dag_catalog._NON_BACKFILL_FAMILIES and is
# therefore filtered out of the tfvars already. futures_eod IS backfillable, so it needs an explicit
# exclusion. This mirrors readiness_certify.PRE_PUBLISH_PACKAGE, which records the same fact for the
# readiness certificate.
#
# THE REMOVAL TRIGGER IS THE FIRST CANONICAL PUBLISH, NOT THE PRODUCER CODE LANDING. Remove an
# entry the moment its table's first canonical publish lands, then re-emit the tfvars and apply.
#
# `futures_eod` HAS BEEN RELEASED -- 2026-07-29, and the interlock ran its full course rather than
# being waived. The four-step order this comment demanded was executed in order, each step verified
# before the next:
#   (a) land the legs -- W1a producers + W2 Databento, done;
#   (b) run the backfills and promote canonical BY HAND -- czce 34,164 rows / miax 1,554 /
#       cepea 12,922 (the archive's nine-year hole found and filled) / jse 18, plus databento 15/15,
#       every one published from Batch under the publisher role with union gates PASS;
#   (c) flip both chains to `promote_mode: autonomous` so canonical advances nightly -- done in the
#       same change as this line, and it is the step that matters here: the canonical prefix now
#       advances every fire, so `leviathan.silver.freshness` (which reads the newest object mtime
#       under the CANONICAL prefix with `/_shadow/` and `/_staging/` EXCLUDED, and which a shadow
#       publish deliberately never resets) sees a fresh clock nightly instead of re-breaching six
#       days after each manual promote;
#   (d) drop the family here, re-emit the tfvars, apply -- this line.
# The empty-prefix hazard the paragraph above described is therefore GONE: the prefix is populated,
# the poller emits datapoints, and treat_missing_data="breaching" now guards a live series instead
# of an absence. The set stays as an empty frozenset rather than being deleted, because the NEXT
# registered-ahead-of-producer table needs the same interlock -- add it here, and remove it only
# once that table's own (a)-(d) have run.
#
# `moex_agro` IS THAT NEXT TABLE (2026-08-20). silver_moex_agro_indices is registered ahead of its
# producer under the four-checkmark law: the raw fetcher and both transforms exist, no batch task
# does, no jobdef or schedule is armed, and NOT ONE canonical byte has been published -- so its
# canonical prefix is EMPTY, the freshness poller emits no datapoint for it, and a
# treat_missing_data="breaching" freshness alarm would breach on the next apply of any unrelated
# change in envs/dev and page the shared on-call topic continuously. It is `backfillable` (ISS
# serves history, unlike the forward-only minagro/EEX legs), so dag_catalog._NON_BACKFILL_FAMILIES
# would NOT filter it out incidentally the way it does gold_pattern_records -- the exclusion has to
# be explicit, exactly as futures_eod's was.
#
# REMOVAL TRIGGER, unchanged and in this order: (a) rebuild the worker image so it carries
# jobs/ingest/fetch_moex_agro_indices.py; (b) run the backfill cloud-side and promote canonical BY
# HAND; (c) arm the daily schedule at promote_mode=autonomous so the canonical prefix advances; (d)
# THEN drop `moex_agro` here, re-emit the tfvars and apply. Removing it before (b) arms an alarm on
# an absence.
# `ams_gtr` IS THE SECOND (2026-08-20, the wave-close reconciliation), and it is here for exactly
# the reason moex_agro is, reached from the opposite direction. The GTR source is richly
# backfillable -- the SODA datasets serve 1996-01-01..2026-08-19 and the lane measured every span --
# so `backfillable` is True and dag_catalog._NON_BACKFILL_FAMILIES does NOT filter it out the way it
# incidentally covers the two forward-only legs (minagro, eex_freight). But BACKFILLABLE IS NOT
# PUBLISHED: the fetcher and the transform exist, no batch task does, no jobdef or schedule is
# armed, and not one canonical byte is under silver/ams_gtr/ -- so the prefix is empty, the poller
# emits nothing, and treat_missing_data="breaching" would page the shared topic on the next
# unrelated envs/dev apply. The richness of the source is what makes the exclusion necessary rather
# than incidental; it is not an argument against it.
#
# REMOVAL TRIGGER, the same four steps in the same order: (a) write the bronze->silver batch task and
# register its jobdef; (b) run the backfill and promote canonical BY HAND; (c) arm the weekly
# Thursday schedule at promote_mode=autonomous so the canonical prefix advances; (d) THEN drop
# `ams_gtr` here, re-emit the tfvars and apply. Mirrored in readiness_certify.PRE_PUBLISH_PACKAGE.
PRE_PUBLISH_FAMILIES: frozenset = frozenset({"moex_agro", "ams_gtr"})


def _alarm(*, failure_mode: str, family: str, metric_name: str, dimensions: dict,
           statistic: str, period_seconds: int, evaluation_periods: int,
           comparison_operator: str, threshold: float, treat_missing_data: str,
           severity: str, owner: str, dedup_key: str, retention_days: int,
           description: str, table: Optional[str] = None,
           datapoints_to_alarm: Optional[int] = None) -> dict:
    """Build one fully-specified alarm definition (the F082 per-alarm contract).

    ``table`` (when given) makes this a PER-TABLE alarm: the name tail is the table (two burned
    tables share the usda_nass family, so a family-only name would collide) and ``table`` is
    carried as a field for the completeness lint.

    ``datapoints_to_alarm`` (when given) is emitted BESIDE ``evaluation_periods`` for an M-of-N
    alarm. Optional and omitted by default so every alarm dict that existed before it was added is
    byte-identical: CloudWatch defaults it to ``evaluation_periods``, so an alarm that does not say
    it is not changed by this field existing.

    THE WINDOW FENCE (round 3, review M-A). Every alarm minted here is checked against the
    PutMetricAlarm bound BEFORE it can exist as a dict: ``Period x EvaluationPeriods <= 604,800 s``
    (seven days), quoted from botocore's own CloudWatch service model in
    ``freshness.CLOUDWATCH_MAX_EVALUATION_SECONDS``. Round 2 shipped ``corpus_fold_liveness`` at
    86,400 x 35 = 3,024,000 s -- five times the ceiling -- into the document, into a paste-ready
    HCL handed to the owner and into five green unit tests, because nothing between the choice and
    `terraform apply` could say no. This is that no, and it fails CLOSED: the generator REFUSES to
    mint the definition rather than emitting one the API will reject. A refusal is a signal."""
    refuse_uncreatable_window(
        f"alarm {PROJECT}-{ENVIRONMENT}-{failure_mode.replace('_', '-')}-"
        f"{(table or family).replace('_', '-')}",
        period_seconds, evaluation_periods)
    name_tail = (table or family).replace("_", "-")
    alarm = {
        "alarm_name": f"{PROJECT}-{ENVIRONMENT}-{failure_mode.replace('_', '-')}-{name_tail}",
        "failure_mode": failure_mode,
        "family": family,
        "metric_namespace": METRIC_NAMESPACE,
        "metric_name": metric_name,
        "dimensions": dimensions,
        "statistic": statistic,
        "period_seconds": period_seconds,
        "evaluation_periods": evaluation_periods,
        "comparison_operator": comparison_operator,
        "threshold": threshold,
        "treat_missing_data": treat_missing_data,
        "severity": severity,
        "owner": owner,
        "oncall_destination": ONCALL_TOPIC,
        "dedup_key": dedup_key,
        "retention_days": retention_days,
        "description": description,
    }
    if table is not None:
        alarm["table"] = table
    if datapoints_to_alarm is not None:
        alarm["datapoints_to_alarm"] = datapoints_to_alarm
    return alarm


def build_alarms(registry=None) -> list[dict]:
    """The full ordered alarm-definition set derived from the registry + DAG catalog."""
    reg = registry or load_registry()
    catalog = build_catalog(reg)
    alarms: list[dict] = []

    # 1. Per-family Batch-job-failed alarms.
    for key, fam in catalog.items():
        if not fam.backfillable:
            continue  # model_output has no source Batch DAG to fail
        alarms.append(_alarm(
            failure_mode="batch_job_failed",
            family=key,
            metric_name="BatchJobFailed",
            dimensions={"Family": key},
            statistic="Sum",
            period_seconds=300,
            evaluation_periods=1,
            comparison_operator="GreaterThanThreshold",
            threshold=0,
            treat_missing_data="notBreaching",
            severity=SEV_P2,
            owner=fam.owner,
            dedup_key=f"batch-failed/{key}",
            retention_days=90,
            description=(
                f"A Batch job in the {fam.label} family reached FAILED "
                f"(tables: {', '.join(fam.tables)}). Runbook: R4_incident_runbooks.md#batch-job-failed."
            ),
        ))

    # 2. Per-family freshness-SLA-breach alarms (from the certificate's FreshnessLagDays metric).
    for key, fam in catalog.items():
        if not fam.backfillable:
            continue
        alarms.append(_alarm(
            failure_mode="freshness_sla_breach",
            family=key,
            metric_name="FreshnessLagDays",
            dimensions={"Family": key},
            statistic="Maximum",
            period_seconds=86400,
            evaluation_periods=1,
            comparison_operator="GreaterThanThreshold",
            threshold=fam.max_sla_lag_days,
            treat_missing_data="breaching",  # no freshness datapoint == the pipeline stopped == stale
            severity=SEV_P2,
            owner=fam.owner,
            dedup_key=f"freshness/{key}",
            retention_days=90,
            description=(
                f"{fam.label} exceeded its interim freshness ceiling "
                f"({fam.max_sla_lag_days}d, basis={fam.sla_basis}). Emitted by "
                f"scripts/silver/freshness_poller.py (FreshnessLagDays, dim Family). Runbook: "
                f"R4_incident_runbooks.md#freshness-sla-breach."
            ),
        ))

    # 2b. Per-TABLE freshness alarms for the audit's four burned tables (freshness-poller lane).
    # The family alarm above reads the family's stalest member against its tightest ceiling, so a
    # mixed-cadence family hides a stalled fast member; these give a precise per-table ceiling.
    # ARTIFACT_FRESHNESS rides the SAME loop and the same failure_mode on purpose: the emitted
    # alarm_name then matches what the existing for_each terraform resource renders, so leg 3 needs
    # no module change -- the map just gains a key.
    for table, (family, max_lag, basis) in sorted(
            {**BURNED_TABLE_FRESHNESS, **ARTIFACT_FRESHNESS}.items()):
        fam = catalog.get(family)          # tolerates a family absent from the DAG catalog
        owner = fam.owner if fam else "silver-platform"
        label = fam.label if fam else family
        alarms.append(_alarm(
            failure_mode="freshness_sla_breach_table",
            family=family,
            table=table,
            metric_name="FreshnessLagDays",
            dimensions={"Table": table},  # single-dim: MUST match the poller's {Table} datapoint (a
                                          # {Table,Family} composite is never written -> no data ->
                                          # breaching would page permanently). family stays a field.
            statistic="Maximum",
            period_seconds=86400,
            evaluation_periods=1,
            comparison_operator="GreaterThanThreshold",
            threshold=max_lag,
            treat_missing_data="breaching",  # a burned producer STOPS emitting -> must still fire
            severity=SEV_P2,
            owner=owner,
            dedup_key=f"freshness-table/{table}",
            retention_days=90,
            description=(
                f"Table {table} ({label}) exceeded its per-table freshness ceiling "
                f"({max_lag}d, basis={basis}). "
                + ("Ran stale-green 6-10wk pre-audit; " if table in BURNED_TABLE_FRESHNESS
                   else "Non-registry artifact (freshness.EXTRA_TARGETS); ")
                + "emitted by scripts/silver/freshness_poller.py (FreshnessLagDays, dim Table). "
                  "Runbook: R4_incident_runbooks.md#freshness-sla-breach."
            ),
        ))

    # 2c. PER-TABLE DATA-DATE alarms (P6, the 2026-09-22 pipeline census).
    #
    # THE GAP THESE CLOSE, in one sentence: every alarm above this block reads S3 WRITE RECENCY, so
    # a producer that re-writes a byte-identical object on its fire cadence is GREEN forever while
    # its content is dead. MEASURED 2026-09-22 by a read-only poll: silver_sagis_weekly_exports
    # FreshnessLagRatio 0.211 (green) and DataDateAgeRatio 46.26; silver_unica_corn_ethanol 0.430
    # (green) and 16.64. Six of the census's fourteen blockers are that one shape.
    #
    # THRESHOLD 1.0 IS NOT A GUESS, and that matters because silver_rebuild_gate.py's own comment
    # refused to build this alarm until "a week of measured data" was in ("the threshold is set from
    # a week of measured data, not guessed the day the metric is born"). A RATIO needs no such week:
    # the denominator is each table's OWN declared ceiling, so 1.0 means "past the promise this
    # contract already makes" for an annual table and a daily one alike -- the identical argument
    # that justified FreshnessLagRatio's 1.0 in D-PR-14. The DAY metric rides alongside for exactly
    # the distribution reading the gate asked for.
    #
    # treat_missing_data = "notBreaching", and this is the one place this file departs from the
    # freshness alarms' posture ON PURPOSE. Those are "breaching" because a stopped producer stops
    # emitting and must page. Here MISSING means the poller could not READ a data date -- and that
    # absence is already alarmed ONCE, precisely, by data_date_unread below. Making all ~36 of these
    # "breaching" instead would put every one of them into ALARM on the apply that creates them,
    # before the image carrying the emitter ships -- the exact hazard
    # modules/silver_observability's own header names for the pre-emit families, multiplied by
    # thirty-six. Nothing is fail-open: the blindness has its own alarm, an empty prefix keeps the
    # write axis's "breaching" per-table alarm, and a dead poller trips freshness_targets_polled.
    #
    # STATIC_DATA_TARGETS is subtracted inside data_date_alarm_targets(): a genuinely closed archive
    # (mpoc trade stats at 1,025 days, mpoc exports at 996) still EMITS its age every cycle but
    # never pages, because "a loud board nobody believes is the failure this whole census is about".
    for table, (family, ceiling, basis) in sorted(data_date_alarm_targets(reg).items()):
        fam = catalog.get(family)
        owner = fam.owner if fam else "silver-platform"
        label = fam.label if fam else family
        alarms.append(_alarm(
            failure_mode="data_date_age_breach",
            family=family,
            table=table,
            metric_name=DATA_DATE_RATIO_METRIC_NAME,
            dimensions={"Table": table},   # single-dim, matching the poller's {Table} datapoint
            statistic="Maximum",
            period_seconds=86400,
            evaluation_periods=1,
            comparison_operator="GreaterThanThreshold",
            threshold=1.0,
            treat_missing_data="notBreaching",
            severity=SEV_P2,
            owner=owner,
            dedup_key=f"data-date/{table}",
            retention_days=90,
            description=(
                f"Table {table} ({label}) holds DATA older than its own declared ceiling "
                f"({ceiling:.0f}d; {basis}). This is the CONTENT axis, not the write axis: a "
                f"producer that re-writes an identical object every fire reads fresh on "
                f"FreshnessLagDays while this alarm is the one that speaks. Emitted by "
                f"jobs/observability/freshness_poller_task.py (DataDateAgeRatio, dim Table). "
                f"Runbook: R4_incident_runbooks.md#freshness-sla-breach."
            ),
        ))

    # 2d. THE BLINDNESS ALARM (P6). One alarm for the whole class: how many targets whose data axis
    # IS declared could not be read this cycle. This is what lets every per-table alarm above be
    # notBreaching without a single door left open -- an unreadable footer, an absent declared
    # column, a missing pyarrow, a partition value that will not parse, all land here.
    #
    # Reason=unreadable ONLY here; `ahead` gets its OWN alarm at 2d-bis because it carries a
    # different meaning and a different remedy. The remaining reasons are deliberately unalarmed:
    # `static` is a declared closed archive, `undeclared` is a repo fact pinned by name in the unit
    # deck (freshness.data_date_undeclared_tables), `absent` is an empty canonical prefix, which the
    # write axis already treats as a breach, and `disabled` is an operator holding the documented
    # rollback lever down (emitted so that lever is visible, never so it pages).
    alarms.append(_alarm(
        failure_mode="data_date_unread",
        family="_global",
        metric_name=DATA_DATE_UNREAD_METRIC_NAME,
        dimensions={"Reason": UNREAD_UNREADABLE},
        statistic="Maximum",
        period_seconds=86400,
        evaluation_periods=1,
        comparison_operator="GreaterThanThreshold",
        threshold=0,
        treat_missing_data="notBreaching",
        severity=SEV_P2,
        owner="silver-platform",
        dedup_key="data-date-unread/global",
        retention_days=90,
        description=(
            "At least one poll target whose DATA-date axis is DECLARED could not be read this "
            "cycle (unreadable parquet footer, declared column absent from the schema, "
            "unparseable partition value, or pyarrow missing from the image). While this is in "
            "ALARM the per-table data_date_age_breach alarms are blind for that target, which is "
            "why they can safely be notBreaching. Emitted by "
            "jobs/observability/freshness_poller_task.py (DataDateUnread, dim Reason=unreadable)."
        ),
    ))

    # 2d-bis. THE FORWARD-STAMP ALARM (P6 round 2 / adversarial review M3, 2026-09-22).
    #
    # WHAT ROUND 1 SHIPPED AND WHY IT WAS WRONG. A target whose DECLARED knowledge axis reads into
    # the future publishes no DataDateAgeRatio datapoint -- correctly, a future date is not a
    # freshness figure -- and round 1 stopped there. The consequence, MEASURED: silver_nass_annual
    # reads 2027-02-01, 132 days ahead; its per-table alarm is treat_missing_data="notBreaching" and
    # therefore sits OK forever; the blindness alarm above is scoped to Reason=unreadable. So the
    # table left the content watch and NOTHING said so. The recurrence is structural, not exotic:
    # this estate stamps forward vintages by design, so every contract that declares a scheduled
    # RELEASE date as its knowledge axis joins the unwatched set the moment it is declared.
    #
    # WHY IT ALARMS RATHER THAN MERELY COUNTS. A knowledge row stamped in the future is one guard
    # away from a point-in-time LEAK -- the evidence estate's whole contract is that no row whose
    # knowledge date is after the question's as-of may be served -- so this is a finding in its own
    # right, not a gap in a freshness reading.
    #
    # THRESHOLD 0, AND THE KNOWN SET IS NOT EXCUSED. freshness.DATA_DATE_AHEAD_KNOWN documents the
    # one table that reads ahead TODAY with its measured lead and its remedy, and that map is read
    # into this description -- not into the threshold. A threshold of len(KNOWN) would be round 1's
    # silence wearing a number: it would re-hide nass_annual, and it would re-hide the NEXT
    # forward-stamped contract the moment somebody added it to the map. RED ON ARRIVAL IS THE
    # INTENT: it is red because the finding is real and open, and its own description says what
    # closes it.
    #
    # treat_missing_data = "notBreaching": absence of this datum means the poller did not run,
    # which freshness_targets_polled (breaching) already says once and precisely.
    ahead_known = ", ".join(f"{t} ({why})" for t, why in sorted(DATA_DATE_AHEAD_KNOWN.items()))
    alarms.append(_alarm(
        failure_mode="data_date_ahead",
        family="_global",
        metric_name=DATA_DATE_UNREAD_METRIC_NAME,
        dimensions={"Reason": UNREAD_AHEAD},
        statistic="Maximum",
        period_seconds=86400,
        evaluation_periods=1,
        comparison_operator="GreaterThanThreshold",
        threshold=0,
        treat_missing_data="notBreaching",
        severity=SEV_P2,
        owner="silver-platform",
        dedup_key="data-date-ahead/global",
        retention_days=90,
        description=(
            "At least one poll target's DECLARED knowledge axis points INTO THE FUTURE past the "
            "one-day clock-skew tolerance. That target publishes no DataDateAgeRatio datapoint, so "
            "its per-table data_date_age_breach alarm (notBreaching) reads OK while nothing is "
            "watching its content -- and a knowledge row stamped in the future is one guard away "
            "from a point-in-time leak. Remedy: declare a data-PERIOD column on the contract, or "
            "fix the producer that stamped a future date. KNOWN AND OPEN at declaration "
            f"(2026-09-22): {ahead_known or 'none'}. The known set is deliberately NOT excused by "
            "the threshold -- see leviathan.silver.freshness.DATA_DATE_AHEAD_KNOWN. Emitted by "
            "jobs/observability/freshness_poller_task.py (DataDateUnread, dim Reason=ahead)."
        ),
    ))

    # 2e. THE POLLER'S OWN CENSUS (P7). The poller has printed its target count on line 1 of every
    # run since it was built and NOTHING has ever read it. MEASURED 2026-09-21: it printed 46 while
    # the repo registry enumerated 53 -- a baked image five weeks behind HEAD. Four contracts had
    # zero datapoints over a 7-day window and the RETIRED silver_esr surface was still being polled
    # at ratio 2.34, latching leviathan-dev-freshness-breach-count-usda-esr ALARM since 2026-09-04
    # and hiding the leg that actually serves.
    #
    # The threshold is GENERATED from the same registry the poller reads (see build_tfvars), so it
    # can never be a stale literal, and treat_missing_data = "breaching" because a poller that
    # cannot say how many targets it polled is a poller that did not run.
    alarms.append(_alarm(
        failure_mode="freshness_targets_polled",
        family="_global",
        metric_name=TARGETS_POLLED_METRIC_NAME,
        dimensions={},
        statistic="Minimum",
        period_seconds=86400,
        evaluation_periods=1,
        comparison_operator="LessThanThreshold",
        threshold=float(len(all_poll_targets(reg))),
        treat_missing_data="breaching",   # no census datapoint == the poller did not run
        severity=SEV_P2,
        owner="silver-platform",
        dedup_key="targets-polled/global",
        retention_days=90,
        description=(
            f"The freshness poller polled FEWER than the "
            f"{len(all_poll_targets(reg))} targets this repo's registry declares -- i.e. the "
            f"image it runs from carries an OLDER configs/silver/tables than HEAD, and every "
            f"contract added since that image is unmeasured and unalarmed. Emitted by "
            f"jobs/observability/freshness_poller_task.py (FreshnessTargetsPolled, undimensioned); "
            f"the threshold is regenerated from the registry by this file, never hand-set. "
            f"Remedy: repin the jobdef the leviathan-dev-freshness-poller schedule targets onto a "
            f"CURRENT worker image (scripts/ops/repin_jobdef_digest.py)."
        ),
    ))

    # 4. THE TEXT / CORPUS LANE'S LIVENESS ALARMS (handed by lane 5, round 2; the liveness half
    # RE-SHAPED onto a daily age gauge in round 3, review M-A).
    #
    # WHY THEY ARE HERE AND NOT APPLIED YET, stated so nobody reads the gap as an oversight. These
    # three metrics DO NOT EXIST in the account today -- MEASURED 2026-09-22,
    # `list-metrics --namespace Leviathan/Silver` returns eleven names and not one of them starts
    # with Corpus or Wasde -- because the emitters ship inside images whose current pins predate the
    # change. An alarm created against a stream that has never published goes red on the apply that
    # creates it (corpus_fold_liveness is treat_missing_data="breaching"), which is the exact hazard
    # this module's own header names for the pre-publish families. So the DOCUMENT carries them now
    # (this file has always documented the target state; PRE_PUBLISH_FAMILIES is filtered in
    # build_tfvars and only there) and the terraform half waits on one precondition:
    #
    #     commit -> image build + repin -> ONE fire that emits -> `aws cloudwatch list-metrics
    #     --namespace Leviathan/Silver` shows the name -> THEN apply.
    #
    # They are deliberately NOT in build_tfvars: the applied set may not contain an alarm whose
    # metric has never published.
    #
    # ONE NAME IN THE BRIEF IS REFUTED, WITH LANE 5's MEASUREMENT. The spec handed down said
    # `CorpusFoldDocsWritten == 0 -> ALARM`. A fold is a RE-DERIVATION from the chunk cache, not an
    # ingestion, so `docs.written` is 0 BY CONSTRUCTION on a perfect fold: the last real fold's own
    # manifest (write_manifest_rebuild_20260821T212319Z.json, read-only GET 2026-09-22) records
    # docs {"written": 0} beside slices {"commodity": 52, "drivers": 144} and 2,742,847 rows. An
    # alarm on docs.written would have paged on a 4h29m fold that rewrote 196 objects. The metric
    # that counts the work is CorpusFoldSlicesWritten, healthy value 196, and that is what is
    # alarmed here.
    #
    # ROUND 3 -- THE LIVENESS SHAPE THE API ACCEPTS. Round 2 asked "did the monthly fold fire?"
    # with SampleCount(CorpusFoldRuns) over THIRTY-FIVE daily periods. PutMetricAlarm refuses any
    # alarm whose Period x EvaluationPeriods exceeds 604,800 s, so 86,400 x 35 = 3,024,000 s could
    # never have been created: the apply would have failed with a ValidationError on an alarm five
    # unit tests reported as delivered. The question is unchanged and the 35 is unchanged; it is
    # now spent as 35 DAYS OF AGE on a gauge the DAILY poller emits, evaluated once. Two things
    # improve on the way: the alarm CLEARS on the next fold instead of needing 35 clean days, and
    # the reporter no longer has to be the job whose death is being reported.
    fold = ledger_gauge("corpus_fold")
    alarms.append(_alarm(
        failure_mode="corpus_fold_liveness",
        family=fold.family,
        metric_name=fold.metric_name,
        dimensions={"Family": fold.family},
        statistic="Maximum",
        period_seconds=86400,
        evaluation_periods=1,
        datapoints_to_alarm=1,
        comparison_operator="GreaterThanThreshold",
        # READ OFF THE GAUGE DECLARATION, never hand-set here: the number in the alarm and the
        # number the poller prints beside the reading are ONE number (freshness.LEDGER_GAUGES).
        threshold=fold.threshold_days,
        # breaching, and here it means one thing only: the DAILY poller emitted no age at all --
        # the ledger prefix is unreadable or the poller did not run. Silence on a daily gauge is a
        # blindness, never a quiet month, because the gauge does not depend on the fold firing.
        treat_missing_data="breaching",
        severity=SEV_P2,
        owner="graphrag-platform",
        dedup_key="corpus-fold/liveness",
        retention_days=90,
        description=(
            f"The monthly evidence FOLD is more than {fold.threshold_days:.0f} DAYS OLD. THE BOUND "
            f"IS DERIVED, NOT PREFERRED: {fold.basis} This is the alarm for the never-DELIVERED "
            "case: leviathan-dev-batch-job-failed-backstop has zero alarm actions and the "
            "scheduled-failure metric filter matches only MANAGED_BY_AWS or a named jobName list "
            "that does not include corpus-fold, so a fold that is never submitted is invisible "
            f"without this. Emitted DAILY by jobs/observability/freshness_poller_task.py "
            f"({fold.metric_name}, dim Family) as the age of {fold.prefix} -- with "
            f"{fold.fallback_prefix} ({fold.fallback_note}) when the ledger prefix is empty. "
            "MISSING DATA IS BREACHING because the emitter is the daily poller, not the monthly "
            "fold: no datapoint means the poller did not run or could not read the ledger, and "
            "both are blindness. Remedy: submit a fold (or repin the poller), then this clears on "
            "the next cycle."
        ),
    ))
    alarms.append(_alarm(
        failure_mode="corpus_fold_wrote_nothing",
        family="graphrag_evidence",
        metric_name="CorpusFoldSlicesWritten",
        dimensions={"Family": "graphrag_evidence"},
        statistic="Maximum",
        period_seconds=86400,
        evaluation_periods=1,
        datapoints_to_alarm=1,
        comparison_operator="LessThanThreshold",
        threshold=1,
        # notBreaching HERE, and the pair is the reason: liveness is the alarm above's job, so this
        # one must be silent on the ~30 days a month when no fold fires. It speaks only on a day
        # that HAS a datapoint whose value is 0 -- a fold ran and wrote no slice object.
        treat_missing_data="notBreaching",
        severity=SEV_P2,
        owner="graphrag-platform",
        dedup_key="corpus-fold/wrote-nothing",
        retention_days=90,
        description=(
            "A monthly evidence fold FIRED and wrote ZERO slice objects. The healthy value is 196 "
            "(52 commodity + 144 driver slices, measured from the 2026-08-21 fold manifest), and "
            "the task emits 0 on any failed or refused chain, so this is 'the fold ran and did "
            "nothing'. NOT DocsWritten: a fold is a re-derivation from the chunk cache and "
            "docs.written is 0 on a perfect fold. Paired with corpus_fold_liveness, which is the "
            "alarm for a fold that never fired. Emitted by jobs/batch/corpus_fold_task.py "
            "(CorpusFoldSlicesWritten, dim Family)."
        ),
    ))
    # The WASDE text leg stopped exiting 1 on a document-level extraction error (it is the LAST
    # task of a FAIL-FAST silver phase, so one unreadable PDF out of 375 withheld the whole month's
    # canonical publish). The leg is tolerant by exit code and the failure is COUNTED, never
    # swallowed -- so this metric is now the ONLY thing that can see a text failure.
    alarms.append(_alarm(
        failure_mode="wasde_text_errors",
        family="usda_wasde",
        metric_name="WasdeTextErrors",
        dimensions={"Family": "usda_wasde"},
        statistic="Maximum",
        period_seconds=86400,
        evaluation_periods=1,
        datapoints_to_alarm=1,
        # THE NUMBER IS THE LEG'S OWN CONSTANT, SPELLED ONCE THERE: jobs/batch/wasde_text_task.py
        # WASDE_TEXT_ERROR_ALARM_THRESHOLD = 0 (the closing round retired MAX_TOLERATED_DOC_FAILURES
        # = 1: the leg no longer exits 1 on ANY document count -- a DOCUMENT failure is counted,
        # named, RECORDED and tolerated, an INFRA failure exits 1 -- so the exit code no longer
        # sees the first document failure and THIS alarm must: GreaterThanThreshold 0 pages on the
        # FIRST new document failure of a fire). tests/unit/silver/test_silver_alarms.py joins this
        # literal to that constant and the join is MANDATORY (a retired constant reds the deck).
        # Maximum, never Sum: the family fires six times a month and a daily Sum would add two
        # fires' errors together and invent a breach no single fire had.
        comparison_operator="GreaterThanThreshold",
        threshold=0,
        # The family fires only on days 8-13; missing data is the other 25 days and must be silent.
        treat_missing_data="notBreaching",
        severity=SEV_P2,
        owner=catalog["usda_wasde"].owner if "usda_wasde" in catalog else "silver-platform",
        dedup_key="wasde-text/errors",
        retention_days=90,
        description=(
            "A WASDE document raised during text extraction on a single fire (the FIRST one pages). "
            "jobs/batch/wasde_text_task.py no longer exits 1 on a document-level error -- it is "
            "the last task of the FAIL-FAST silver phase, so one unreadable PDF out of 375 used to "
            "withhold the month's canonical WASDE publish -- so this counter is the compensating "
            "detector for that tolerance. THE THRESHOLD IS THE LEG'S OWN CONSTANT: "
            "WASDE_TEXT_ERROR_ALARM_THRESHOLD = 0, so the first new document failure pages while the "
            "leg records it and keeps the month's canonical publish. Infra failures (an S3 throttle) "
            "exit 1 on the leg AND page through wasde_text_infra_errors. Do "
            "NOT alarm WasdeTextDocsWritten == 0: a month whose document is already current writes "
            "0 and that is the correct steady state -- the staleness question is "
            "wasde_text_tip_stale's. Emitted by jobs/batch/wasde_text_task.py (WasdeTextErrors, "
            "dim Family) at the end of EVERY fire, including the failing one."
        ),
    ))
    # THE INFRA CLASS, SEPARATELY (closing round, lane 5 MAJOR-R3-1): a ClientError / BotoCoreError out
    # of the S3 seam exits 1 on the leg (the fire must RE-RUN) AND is counted on its own metric, so the
    # board can tell "a throttle" from "an unreadable PDF" without reading a log. Maximum > 0.
    alarms.append(_alarm(
        failure_mode="wasde_text_infra_errors",
        family="usda_wasde",
        metric_name="WasdeTextInfraErrors",
        dimensions={"Family": "usda_wasde"},
        statistic="Maximum",
        period_seconds=86400,
        evaluation_periods=1,
        datapoints_to_alarm=1,
        comparison_operator="GreaterThanThreshold",
        threshold=0,
        treat_missing_data="notBreaching",
        severity=SEV_P2,
        owner=catalog["usda_wasde"].owner if "usda_wasde" in catalog else "silver-platform",
        dedup_key="wasde-text/infra-errors",
        retention_days=90,
        description=(
            "An INFRA failure (S3 ClientError / BotoCoreError) inside the WASDE text leg on a single "
            "fire. The leg exits 1 on this class -- a throttled release is a document that was never "
            "attempted, so the fire must re-run inside the 8th-13th window -- and this counter is the "
            "board's reading of it, separate from WasdeTextErrors (document failures, tolerated and "
            "recorded). Emitted by jobs/batch/wasde_text_task.py (WasdeTextInfraErrors, dim Family)."
        ),
    ))

    # THE OTHER HALF OF THE TEXT LEG, and the one the error counter cannot see: a chain that
    # never fires raises nothing, writes nothing and counts nothing. Round 3's brief asked for it
    # as "missing data over 40 days", which is 86,400 x 40 = 3,456,000 s and uncreatable; it is the
    # same daily AGE GAUGE as the fold's -- and here the gauge reads the KEY, never the mtime,
    # because the text lane MEASURED the difference: newest object mtime 2026-08-20 (33.2d, GREEN
    # at 40) over a newest release_date partition of 2026-08-12 (41.0d, RED).
    tip = ledger_gauge("wasde_text")
    alarms.append(_alarm(
        failure_mode="wasde_text_tip_stale",
        family=tip.family,
        metric_name=tip.metric_name,
        dimensions={"Family": tip.family},
        statistic="Maximum",
        period_seconds=86400,
        evaluation_periods=1,
        datapoints_to_alarm=1,
        comparison_operator="GreaterThanThreshold",
        threshold=tip.threshold_days,
        # breaching: an unreadable prefix is a blindness, never a quiet month. The emitter is the
        # DAILY poller, so silence here is the poller's silence and not the chain's.
        treat_missing_data="breaching",
        severity=SEV_P2,
        owner=catalog["usda_wasde"].owner if "usda_wasde" in catalog else "silver-platform",
        dedup_key="wasde-text/tip-stale",
        retention_days=90,
        description=(
            f"The WASDE TEXT layer's newest release is more than {tip.threshold_days:.0f} DAYS "
            f"old. THE BOUND IS DERIVED, NOT PREFERRED: {tip.basis} READ FROM THE PARTITION KEY, "
            f"NEVER THE OBJECT MTIME: measured 2026-09-22, the newest mtime under {tip.prefix} is "
            "2026-08-20 (33.2 days, which a mtime gauge would call GREEN) over a newest "
            "release_date of 2026-08-12 (41.0 days) -- a bulk re-write of old documents, i.e. the "
            "write-recency blindness the data axis exists to end. Emitted DAILY by "
            f"jobs/observability/freshness_poller_task.py ({tip.metric_name}, dim Family). "
            "RED ON ARRIVAL IS EXPECTED AND INTENDED: the tip stands at 41 days today and clears "
            "the moment the first fire writes release_date=2026-09-11. Paired with "
            "wasde_text_errors, which sees a fire that ran and failed; this one sees a chain that "
            "never fired at all."
        ),
    ))

    # 3. Global value-census-regression alarm.
    census_owner = catalog.get("usda_esr").owner if "usda_esr" in catalog else "numbers-platform"
    alarms.append(_alarm(
        failure_mode="value_census_regression",
        family="_global",
        metric_name="ValueCensusHardFailTables",
        dimensions={},
        statistic="Maximum",
        period_seconds=86400,
        evaluation_periods=1,
        comparison_operator="GreaterThanThreshold",
        threshold=0,
        treat_missing_data="notBreaching",
        severity=SEV_P1,  # a value regression ships wrong numbers to serving -- page immediately
        owner=census_owner,
        dedup_key="value-census/global",
        retention_days=90,
        description=(
            "The SILVER-V001 value census reported >0 hard-fail tables (all-NaN / single-vintage / "
            "all-constant / sentinel-saturation) -- the CHIRPS/ESR class. After R4 every table is "
            "census-green, so any hard fail is a regression. Runbook: "
            "R4_incident_runbooks.md#value-census-failure-all-nan--collapsed-vintage."
        ),
    ))
    return alarms


def build_document(registry=None) -> dict:
    reg = registry or load_registry()
    catalog = build_catalog(reg)
    alarms = build_alarms(reg)
    by_mode: dict[str, int] = {}
    for a in alarms:
        by_mode[a["failure_mode"]] = by_mode.get(a["failure_mode"], 0) + 1
    return {
        "package": "SILVER-F082",
        "project": PROJECT,
        "environment": ENVIRONMENT,
        "metric_namespace": METRIC_NAMESPACE,
        "oncall_topic": ONCALL_TOPIC,
        "family_count": len(catalog),
        "alarm_count": len(alarms),
        "alarms_by_failure_mode": by_mode,
        "severity_policy": {
            SEV_P1: "page immediately (value-visible corruption / regression)",
            SEV_P2: "page business hours (a family pipeline failed or went stale)",
        },
        "alarms": alarms,
    }


def build_tfvars(registry=None) -> dict:
    """The Terraform variable payload for ``modules/silver_observability`` (one source of truth).

    ``batch_families`` drives the per-family Batch-failed rule+alarm; ``freshness_slas`` maps
    family -> ceiling-days for the per-family freshness alarms; ``table_freshness_slas`` maps
    table -> {family, threshold, basis} for the per-table freshness alarms (the four burned tables).
    All three are pure functions of the registry + DAG catalog, MINUS
    :data:`PRE_PUBLISH_FAMILIES` -- filtered HERE and only here, so ``alarm_definitions.json`` keeps
    documenting the target state while the APPLIED alarms wait for a first canonical publish."""
    reg = registry or load_registry()
    catalog = build_catalog(reg)
    families = [k for k, f in catalog.items()
                if f.backfillable and k not in PRE_PUBLISH_FAMILIES]
    # P6/P7. The DATA-axis map and the poller's own expected census, filtered by the SAME
    # PRE_PUBLISH_FAMILIES rule and for the same reason: silver_moex_agro_indices and
    # silver_ams_gtr are registered ahead of their producers and their canonical prefixes are
    # EMPTY (verified by listing, 2026-09-22), so an alarm on them would watch an absence somebody
    # deliberately created. ``silver_expected_poll_targets`` is a COUNT, not a filter: the poller
    # really does poll those two, so the census must expect them.
    data_date = {
        table: {"family": family, "ratio_threshold": 1.0, "ceiling_days": ceiling, "basis": basis}
        for table, (family, ceiling, basis) in sorted(data_date_alarm_targets(reg).items())
        if family not in PRE_PUBLISH_FAMILIES
    }
    return {
        "silver_metric_namespace": METRIC_NAMESPACE,
        "silver_batch_families": families,
        "silver_freshness_slas": {k: catalog[k].max_sla_lag_days for k in families},
        "silver_table_freshness_slas": {
            table: {"family": family, "threshold": max_lag, "basis": basis}
            for table, (family, max_lag, basis) in sorted(
                {**BURNED_TABLE_FRESHNESS, **ARTIFACT_FRESHNESS}.items())
        },
        "silver_data_date_slas": data_date,
        "silver_expected_poll_targets": len(all_poll_targets(reg)),
        # Recorded in the applied variables so the closed archives the board deliberately does NOT
        # page about are visible to whoever reads the infrastructure, not only to whoever reads
        # leviathan/silver/freshness.py. Terraform consumes it for the alarm descriptions; the
        # EXCLUSION itself already happened above, in data_date_alarm_targets().
        "silver_data_date_static": dict(sorted(STATIC_DATA_TARGETS.items())),
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="SILVER-F082 alarms-as-code emitter")
    ap.add_argument("--emit-report", default=None, help="write alarm_definitions.json under this dir")
    ap.add_argument("--emit-tfvars", default=None, help="write silver_observability.auto.tfvars.json under this dir")
    args = ap.parse_args(argv)

    doc = build_document()
    if args.emit_report:
        out = Path(args.emit_report)
        out.mkdir(parents=True, exist_ok=True)
        (out / "alarm_definitions.json").write_text(
            json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
        print(f"[F082] alarm_definitions.json -> {out} ({doc['alarm_count']} alarms)")
    if args.emit_tfvars:
        out = Path(args.emit_tfvars)
        out.mkdir(parents=True, exist_ok=True)
        (out / "silver_observability.auto.tfvars.json").write_text(
            json.dumps(build_tfvars(), indent=2, sort_keys=True), encoding="utf-8")
        print(f"[F082] silver_observability.auto.tfvars.json -> {out}")
    if not args.emit_report and not args.emit_tfvars:
        print(json.dumps(doc, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
