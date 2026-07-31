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
    "silver_fgis": ("usda_fgis", 14, "cadence_default:weekly"),
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
    "graphrag_timeline_episodes": (
        "graphrag_evidence", 10,
        "weekly timeline rebuild (cron 0 3 ? * SUN *) + 3d grace; one missed run breaches",
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
PRE_PUBLISH_FAMILIES: frozenset = frozenset()


def _alarm(*, failure_mode: str, family: str, metric_name: str, dimensions: dict,
           statistic: str, period_seconds: int, evaluation_periods: int,
           comparison_operator: str, threshold: float, treat_missing_data: str,
           severity: str, owner: str, dedup_key: str, retention_days: int,
           description: str, table: Optional[str] = None) -> dict:
    """Build one fully-specified alarm definition (the F082 per-alarm contract).

    ``table`` (when given) makes this a PER-TABLE alarm: the name tail is the table (two burned
    tables share the usda_nass family, so a family-only name would collide) and ``table`` is
    carried as a field for the completeness lint."""
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
    return {
        "silver_metric_namespace": METRIC_NAMESPACE,
        "silver_batch_families": families,
        "silver_freshness_slas": {k: catalog[k].max_sla_lag_days for k in families},
        "silver_table_freshness_slas": {
            table: {"family": family, "threshold": max_lag, "basis": basis}
            for table, (family, max_lag, basis) in sorted(
                {**BURNED_TABLE_FRESHNESS, **ARTIFACT_FRESHNESS}.items())
        },
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
