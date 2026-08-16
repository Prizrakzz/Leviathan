# ---------------------------------------------------------------------------
# SILVER-F082 -- silver pipeline observability + incident contracts (apply-gated).
#
# The alarm SET is generated from the SILVER-F010 registry + the SILVER-F082 DAG catalog by
# jobs/observability/silver_alarms.py, which writes silver_observability.auto.tfvars.json (the two
# maps/lists this module iterates). ONE source of truth -- adding a silver table re-emits the tfvars
# and this module grows an alarm without hand-editing HCL.
#
# Metrics referenced here are emitted by the pipeline itself (the F082 structured-log/EMF contract:
# every producer/publisher/gate event carries environment/table/stage/family/outcome):
#   * Leviathan/Silver  BatchJobFailed{Family}          -- a Batch job in the family reached FAILED
#   * Leviathan/Silver  FreshnessLagDays{Family}        -- freshness certificate lag per family
#   * Leviathan/Silver  ValueCensusHardFailTables       -- SILVER-V001 hard-fail table count (global)
# The EventBridge Batch-failed rule is the crash-safe backstop: if a job dies before emitting its EMF
# metric, the rule still fires from the AWS-native Batch state change.
#
# NOTHING here is applied by the readiness campaign. Apply is user-gated with the -target commands in
# reports/silver_readiness/R4_F082_observability/README.md.
# ---------------------------------------------------------------------------

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  # Effective alarm destination: this module's own silver-pipeline topic (preferred) else the shared
  # module.alerting topic passed in. compact() drops empties so an unset topic == no action (safe).
  # 2026-07-31 RCA (D-D): silver_pipeline was REMOVED from this list. The topic has ZERO
  # subscriptions AND its access policy denies cloudwatch.amazonaws.com, so every alarm action
  # targeting it failed silently -- 79 of 79 publishes across 55 alarms in 15 days. Alarms looked
  # wired and delivered nothing. The topic resource is retained (it is the documented placeholder
  # for a future confirmed silver-pipeline endpoint), it is simply no longer an alarm ACTION.
  # NOT fixed by granting cloudwatch + subscribing: alert_topic_arn already reaches the same
  # inbox, so that would double-deliver every alarm.
  alarm_actions = compact([
    var.alert_topic_arn,
  ])
}

# ---------------------------------------------------------------------------
# SNS topic + subscription PLACEHOLDER for silver-pipeline alerts.
# The email subscription is created only when a non-empty endpoint is supplied; the endpoint must be
# CONFIRMED (click the link) before the alarms are trustworthy. Left empty by default = placeholder.
# ---------------------------------------------------------------------------
resource "aws_sns_topic" "silver_pipeline" {
  name = "${local.name_prefix}-silver-pipeline-alerts"
  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_sns_topic_subscription" "silver_pipeline_email" {
  count     = var.silver_alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.silver_pipeline.arn
  protocol  = "email"
  endpoint  = var.silver_alert_email
}

# ---------------------------------------------------------------------------
# EventBridge -- the glue-job-failed rule extended to AWS Batch.
# Mirrors modules/cloudwatch's aws.glue "Glue Job State Change" rule for aws.batch.
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "batch_job_failed" {
  name        = "${local.name_prefix}-batch-job-failed"
  description = "Fires when any AWS Batch job reaches FAILED state (silver pipeline crash-safe backstop)."

  event_pattern = jsonencode({
    source      = ["aws.batch"]
    detail-type = ["Batch Job State Change"]
    detail = {
      status = ["FAILED"]
    }
  })

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_log_group" "batch_failures" {
  name              = "/leviathan/${var.environment}/batch-job-failures"
  retention_in_days = 90
  tags              = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_log_resource_policy" "eventbridge_batch_failures" {
  policy_name = "${local.name_prefix}-eventbridge-batch-failures"

  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource  = "${aws_cloudwatch_log_group.batch_failures.arn}:*"
    }]
  })
}

resource "aws_cloudwatch_event_target" "batch_failed_to_logs" {
  rule      = aws_cloudwatch_event_rule.batch_job_failed.name
  target_id = "batch-failures-log-group"
  arn       = aws_cloudwatch_log_group.batch_failures.arn
}

# ---------------------------------------------------------------------------
# D-PR-15(i), 2026-08-04 -- THE SNS TARGET INTO THE VOID IS REMOVED.
#
# `leviathan-dev-silver-pipeline-alerts` has ZERO subscriptions (verified live 2026-08-04:
# list-subscriptions-by-topic returns []) and, per the 2026-07-31 D-D RCA in `local.alarm_actions`
# above, its access policy was never reachable by cloudwatch either. This rule's SNS target and the
# `sfn_execution_failed` rule's SNS target were therefore publishing into a void -- which is worse
# than not publishing, because a rule with an SNS target READS AS COVERAGE in the console while
# delivering nothing (the same defect that got the 22 hollow per-family alarms deleted at :192-203).
#
# `batch_failed_to_logs` below is UNTOUCHED and is the live path: it feeds
# /leviathan/dev/batch-job-failures, which both metric filters read. Deleting the SNS target changes
# no metric and no alarm.
#
# The TOPIC and its policy are retained deliberately: they are the ready-made seam for D-ALARM-2
# (incident-key suppression) named in PIPELINE_RELIABILITY_WAVE_PLAN.md section 3(h). To resurrect
# the path, re-add an `aws_cloudwatch_event_target` here AND give the topic a confirmed subscriber
# in the same change -- never one without the other.
# ---------------------------------------------------------------------------

# SNS topic policy so EventBridge may publish (retained with the topic as the D-ALARM-2 seam).
resource "aws_sns_topic_policy" "silver_pipeline" {
  arn = aws_sns_topic.silver_pipeline.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.silver_pipeline.arn
    }]
  })
}

# Crash-safe backstop metric: count EventBridge-captured Batch failures (no per-family dimension --
# the app-emitted BatchJobFailed{Family} below carries the family; this catches a job that dies
# before emitting its own EMF metric).
resource "aws_cloudwatch_log_metric_filter" "batch_failed_backstop" {
  name           = "${local.name_prefix}-batch-failed-backstop"
  log_group_name = aws_cloudwatch_log_group.batch_failures.name
  pattern        = "{ $.detail.status = \"FAILED\" }"

  metric_transformation {
    name          = "BatchJobFailedBackstop"
    namespace     = var.silver_metric_namespace
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "batch_failed_backstop" {
  alarm_name          = "${local.name_prefix}-batch-job-failed-backstop"
  alarm_description   = "An AWS Batch job reached FAILED (EventBridge backstop). Runbook: R4_incident_runbooks.md#batch-job-failed."
  namespace           = var.silver_metric_namespace
  metric_name         = "BatchJobFailedBackstop"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  # 2026-07-31 RCA (D-C): DEMOTED TO METRIC-ONLY. This filter is undimensioned -- it matches EVERY
  # FAILED Batch job in the account, so ad-hoc probes, one-shot backfills and judged eval runs paged
  # the owner exactly as loudly as a broken schedule (275 events / 79 alarm actions in 15 days).
  # Job-level paging at ACCOUNT scope is the wrong altitude. Scheduled work now pages via
  # batch_failed_scheduled below; the raw metric and the 90-day log group are retained for forensics.
  alarm_actions       = []
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# ---------------------------------------------------------------------------
# SCHEDULED-WORK-ONLY failure alarm (2026-07-31 RCA, D-C).
# SFN-launched jobs carry MANAGED_BY_AWS=STARTED_BY_STEP_FUNCTIONS, injected by batch:submitJob.sync.
# The four schedules that target Batch DIRECTLY produce no SFN execution and therefore no such env,
# so they are named explicitly -- without them those four would have NO live alerting at all, since
# their per-family alarms are hollow. Ad-hoc probes and evals match neither arm, which is the point.
# NB: $.detail.startedBy does NOT exist on the Batch Job State Change event (verified by key
# enumeration + test-metric-filter); a filter built on it silences everything.
#
# ---------------------------------------------------------------------------
# D-PR-13, 2026-08-04 -- THE FOUR PREFIX WILDCARDS ARE GONE, AND THE ESR CLAUSE WITH THEM.
#
# The four jobName clauses were PREFIX WILDCARDS (`build-notifications*`, `pattern-records-sweep*`,
# `freshness-poller*`, `usda-esr-fetch*`), so any hand-submitted run named with those prefixes paged
# the owner as though a schedule had failed. Measured in the live 30-day archive, FIVE such names
# already exist: pattern-records-sweep-catchup-2026-07-26, pattern-records-sweep-catchup-2026-07-27,
# pattern-records-acceptance-dryrun-20260728, pattern-records-backfill-today, freshness-poller-smoke.
# They escaped only because the filter was created 2026-07-31, after them.
#
# ROUTE CHOSEN: EXACT NAMES, not a LEVIATHAN_SCHEDULED=1 marker env. Both are supported by the live
# filter grammar; exact names win on three measured grounds:
#   1. The schedule payloads use EXACT JobNames with no UUID suffix -- read live from the schedule
#      inputs (`build-notifications`, `freshness-poller`, `pattern-records-sweep`), so anchoring is
#      sufficient and needs no jobdef or schedule surface at all.
#   2. The marker route's failure mode is FAIL-OPEN. The marker would have to ride
#      ContainerOverrides.Environment on the schedule target, and a mis-cased/dropped
#      ContainerOverrides key is silent (the estate has that comment on the morning-brief schedule
#      for exactly this reason) -- a dropped marker means a REAL scheduled failure stops counting.
#      A wrong exact name fails CLOSED and only for a job we ourselves renamed.
#   3. It is verifiable read-only, today, with `aws logs test-metric-filter`. Done: the three manual
#      probes above and `usda-esr-fetch-backfill` all go from MATCH to NO-MATCH, while the three
#      scheduled names, the MANAGED_BY_AWS arm and six real archived events all still MATCH.
#
# THE `usda-esr-fetch*` CLAUSE IS DELETED, NOT ANCHORED. Its only producer was the direct-submitJob
# schedule `leviathan-dev-esr-weekly-ingest`, removed in the same batch as the duplicate 14:00Z THU
# fire (D-PR-15(iii), see envs/dev/main.tf). ESR now runs only through the SFN family chain, whose
# jobs carry MANAGED_BY_AWS and are matched by the first arm.
#
# STILL OPEN, DELIBERATELY (D-PR-42): the MANAGED_BY_AWS arm matches EVERY job the state machine
# submits, including a hand-started refire execution. Closing that needs the scheduler to inject a
# marker into the SFN input and the machine to pass it into every submitJob container environment --
# generator + step_functions surface, not this filter.
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_log_metric_filter" "batch_failed_scheduled" {
  name           = "${local.name_prefix}-batch-failed-scheduled"
  log_group_name = aws_cloudwatch_log_group.batch_failures.name
  pattern        = "{ ($.detail.status = \"FAILED\") && (($.detail.container.environment[*].name = \"MANAGED_BY_AWS\") || ($.detail.jobName = \"build-notifications\") || ($.detail.jobName = \"pattern-records-sweep\") || ($.detail.jobName = \"freshness-poller\")) }"

  metric_transformation {
    name          = "BatchJobFailedScheduled"
    namespace     = var.silver_metric_namespace
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "batch_failed_scheduled" {
  alarm_name          = "${local.name_prefix}-batch-job-failed-scheduled"
  alarm_description   = "A SCHEDULED Batch job reached FAILED. Ad-hoc probes and evals are excluded BY CONSTRUCTION. Runbook: R4_incident_runbooks.md#batch-job-failed."
  namespace           = var.silver_metric_namespace
  metric_name         = "BatchJobFailedScheduled"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  # D-PR-12 / D-PR-44, 2026-08-04: THIS ONE STAYS ARMED, ON PURPOSE.
  # D-PR-12 demotes both notifier paths to leave `FailNotify` as the single notifier, but FailNotify
  # is reached from Gate and Reconcile ONLY -- the four producer Map states (Fetch/Bronze/Silver/
  # Promote) carry `Retry` and NO `Catch` (modules/step_functions/main.tf). Until those Catch arms
  # are live AND one real producer failure has been observed producing exactly one email, this alarm
  # is the ONLY path by which a class-A/E1/F producer failure reaches the owner. Demoting it now
  # would make the majority of the failure census silent.
  # THE COMPLETING EDIT, when D-PR-44's proof lands: replace the line below with `alarm_actions = []`
  # and nothing else. Section 5.4 of PIPELINE_RELIABILITY_WAVE_PLAN.md forbids doing it before then.
  alarm_actions = local.alarm_actions
  tags          = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# ---------------------------------------------------------------------------
# 2026-07-31 RCA (D-E): the 22 per-family `batch_job_failed` alarms were DELETED.
# They watched the EMF metric BatchJobFailed{Family}, which NOTHING PUBLISHES -- `list-metrics
# --namespace Leviathan/Silver` returns only [BatchJobFailedBackstop, FreshnessLagDays]. With
# treat_missing_data=notBreaching they sat permanently OK, which is worse than absent: it reads as
# coverage. leviathan-dev-batch-job-failed-futures-eod stayed green through all three futures_eod
# failures on 2026-07-30/31 while the family had a 0% success rate.
# NOT replaced with per-family filters: $.detail.jobName is "<family>-<uuid>", so a JSON-selector
# dimension yields UUID-level cardinality, and a real per-family split would need 22 filters with 22
# distinct metric names -- which is not what these alarms watched. batch_failed_scheduled above
# supersedes them at the altitude that actually has a live metric.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Per-family freshness-SLA-breach alarms (poller metric FreshnessLagDays{Family}).
# Threshold is the family's interim ceiling from the DAG catalog (silver_freshness_slas map).
#
# treat_missing_data = BREACHING (freshness-audit flip, 2026-07-23). ORIGINALLY "missing" (A-W5
# step 1b) because NOTHING emitted FreshnessLagDays yet -- with "breaching" the zero-datapoint
# alarms would instant-breach at apply. The audit finding was exactly that this made all 21
# freshness alarms HOLLOW: nothing emitted the metric, so "missing" could never fire, and four
# producers ran stale-green for 6-10 weeks. Now that scripts/silver/freshness_poller.py emits the
# metric on a schedule, "breaching" is correct AND necessary -- a producer that STOPS emitting (the
# exact stall the audit missed) transitions to ALARM after one 1-day evaluation period. See the
# emit-vs-alarm SEQUENCING note: apply this flip only once the poller schedule is live and has put
# at least one datapoint per family (freshness_poller.tf.prepared), else the pre-emit families
# instant-breach the shared topic -- the same reason A-W5 first set "missing".
# ---------------------------------------------------------------------------
#
# D-PR-15(ii), 2026-08-04 -- THE UNWATCHED EMITTERS. The poller publishes FreshnessLagDays for 24
# families (live list-metrics) but this map, generated from the SILVER-F010 registry's BATCH
# families, covers only 22. `model_output` and `pattern_records` emitted daily with NO watcher at
# all. They are added through `var.silver_extra_family_slas` -- a SEPARATE map merged here -- so the
# generated `silver_observability.auto.tfvars.json` is not edited (D-EI-12 holds that file).
# Thresholds are the tables' own declared ceilings from `leviathan.silver.freshness`, read live, not
# invented: model_output/silver_model_predictions = 45d, pattern_records/gold_pattern_records = 3d.
# Measured lag at authoring: 18.79d and 0.56d -> BOTH alarms are green on arrival.
#
# THE THIRD FAMILY, `graphrag_evidence`, IS DELIBERATELY WITHHELD, and the reason is mechanical.
# It emits ZERO datapoints -- verified live 2026-08-04 over a 21-day window on BOTH dimensions
# (Family=graphrag_evidence and Table=graphrag_timeline_episodes). Not a stall: THE POLLER NEVER
# LOOKS AT IT. `graphrag_timeline_episodes` is an `EXTRA_TARGETS` entry in
# `leviathan.silver.freshness`, reachable only through `all_poll_targets()`, and the live poller
# command (the INLINE ContainerOverrides in envs/dev/main.tf) iterates `poll_targets()` --
# registry-pure, EXTRA_TARGETS excluded. With treat_missing_data = "breaching" a family alarm here
# would page on creation and never clear, which is exactly the D-EI-12 hold on
# `silver_table_freshness_slas["graphrag_timeline_episodes"]`; adding the FAMILY alarm would smuggle
# the same permanently-red alarm in through the other map. Arm it when the emitter emits, not before
# -- and note that making it emit is a change to the poller command, not to this module.
resource "aws_cloudwatch_metric_alarm" "freshness_sla_breach" {
  for_each = merge(var.silver_freshness_slas, var.silver_extra_family_slas)

  alarm_name          = "${local.name_prefix}-freshness-sla-breach-${replace(each.key, "_", "-")}"
  alarm_description   = "Family '${each.key}' exceeded its interim freshness ceiling (${each.value}d). Emitted by scripts/silver/freshness_poller.py. Runbook: R4_incident_runbooks.md#freshness-sla-breach."
  namespace           = var.silver_metric_namespace
  metric_name         = "FreshnessLagDays"
  dimensions          = { Family = each.key }
  statistic           = "Maximum"
  period              = 86400
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = each.value
  treat_missing_data  = "breaching"
  # D-SG G3-1, 2026-08-16: DEMOTED TO METRIC-ONLY, superseded by freshness_breach_count below.
  # This alarm's threshold is min() over the family's member ceilings while its statistic is
  # Maximum over the members' lags, so a mixed-cadence family is guaranteed to lie in one
  # direction or the other. leviathan-dev-freshness-sla-breach-weather latched ALARM 2026-07-30
  # and has been unable to signal a NEW stall ever since (CloudWatch notifies on TRANSITION).
  # The metric series is RETAINED for forensics; only the paging moves.
  # THE COMPLETING EDIT, after 7 consecutive green FreshnessBreachCount cycles: delete this
  # resource entirely (and its `for_each` var wiring stays -- freshness_breach_count reads the
  # same maps). ROLLBACK before then: restore `alarm_actions = local.alarm_actions`.
  alarm_actions = []
  tags          = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# ---------------------------------------------------------------------------
# D-SG G3-1, 2026-08-16 -- PER-FAMILY BREACH COUNT. The metric the family alarm should have had.
#
# THE ARTIFACT THIS KILLS, precisely: the alarm above thresholds a family at
# dag_catalog.build_catalog's max_sla_lag_days, which is min() over the family's members ("the
# tightest interim ceiling"), and evaluates it with statistic=Maximum over those same members.
# A mixed-cadence family therefore compares its FASTEST member's ceiling against its SLOWEST
# member's lag and is arithmetically guaranteed to breach. Measured 2026-08-16: `weather`
# carries a 3d ceiling while silver_modis_ndvi (an 8-day composite) sits at 80.74d, so
# leviathan-dev-freshness-sla-breach-weather has been latched ALARM since 2026-07-30 while
# silver_nasa_power / silver_chirps / silver_cpc_soil / gold_weather_z all sat at 0.12-0.14d.
#
# FreshnessBreachCount{Family} is the number of member tables past THEIR OWN declared ceiling
# (jobs/observability/freshness_poller_task.py via leviathan.silver.freshness.breach_counts), so
# > 0 means "at least one member is genuinely late" for annual, biweekly and daily members
# alike. modis does NOT lose coverage: its own 45d table ceiling still counts it the day it is
# truly dead.
#
# for_each is the alarm above's key set MINUS var.silver_breach_count_static_families
# (review M-6) -- 1:1 with the family MAX alarms except for the declared static
# exclusions; no third tfvars surface is created.
# treat_missing_data = "breaching" for the same reason as the alarm above: the poller dying is
# the failure this whole lane exists to catch, and the breach datum is written on EVERY cycle
# (a healthy family emits 0, never nothing).
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "freshness_breach_count" {
  # STATIC families are subtracted (review M-6): model_output's only member is
  # silver_model_predictions, whose writer is STOPPED and whose disposition is the G5
  # STATIC-pending set (owner decision D25) -- a breach-count alarm on it would page
  # continuously from ~2026-08-28 about a table nothing schedules. Remove a family from
  # the exclusion the day it gets a producer again.
  # SEQUENCING (review M-6, run sheet S-E): apply this resource AFTER the G2 catch-ups
  # land -- usda_esr / usda_fgis / unica / weather breach honestly TODAY, and the estate
  # law is never to arm a treat_missing_data=breaching alarm that is already breaching.
  for_each = toset(setsubtract(
    keys(merge(var.silver_freshness_slas, var.silver_extra_family_slas)),
    var.silver_breach_count_static_families,
  ))

  alarm_name          = "${local.name_prefix}-freshness-breach-count-${replace(each.key, "_", "-")}"
  alarm_description   = "Family '${each.key}' has at least one member table past ITS OWN declared freshness ceiling (FreshnessBreachCount{Family}, emitted by jobs/observability/freshness_poller_task.py). Replaces the MAX-over-members read, which compared the family's tightest ceiling against its slowest member. Runbook: R4_incident_runbooks.md#freshness-sla-breach."
  namespace           = var.silver_metric_namespace
  metric_name         = "FreshnessBreachCount"
  dimensions          = { Family = each.key }
  statistic           = "Maximum"
  period              = 86400
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# ---------------------------------------------------------------------------
# Per-TABLE freshness-SLA-breach alarms (poller metric FreshnessLagDays{Table}).
# The four tables the freshness audit found ran stale-green for 6-10 weeks: their FAMILY ceiling
# read the stalest member (statistic=Maximum) against the family's tightest ceiling, so a mixed-
# cadence family hid a stalled fast member. Each gets a precise alarm at its own ceiling. The alarm
# is keyed on Table ALONE so it MATCHES the poller's single-dimension {Table} datapoint:
# freshness.metric_data_for emits one {Table} point and a SEPARATE {Family} point -- a {Table,Family}
# COMPOSITE is never written, so a composite-dimensioned alarm would receive no data and, under
# treat_missing_data=breaching, page permanently while detecting no real stall. The family rollup is
# fed by the dedicated {Family} datapoint, not by this per-table point (each.value.family survives
# only in the alarm_description below). treat_missing_data = breaching for the same reason as the
# family alarms (a stopped producer stops emitting). Inert until var.silver_table_freshness_slas is
# wired from the root (default {}).
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "freshness_sla_breach_table" {
  for_each = var.silver_table_freshness_slas

  alarm_name          = "${local.name_prefix}-freshness-sla-breach-table-${replace(each.key, "_", "-")}"
  alarm_description   = "Table '${each.key}' (${each.value.family}) exceeded its per-table freshness ceiling (${each.value.threshold}d, basis=${each.value.basis}). Emitted by scripts/silver/freshness_poller.py. Runbook: R4_incident_runbooks.md#freshness-sla-breach."
  namespace           = var.silver_metric_namespace
  metric_name         = "FreshnessLagDays"
  dimensions          = { Table = each.key }
  statistic           = "Maximum"
  period              = 86400
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = each.value.threshold
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# ---------------------------------------------------------------------------
# Global value-census-regression alarm (SILVER-V001 metric ValueCensusHardFailTables).
# After R4 every table is census-green, so any hard-fail table is a regression -> page immediately.
#
# D-SG G3-5, 2026-08-16 -- THIS ALARM WAS HOLLOW FROM CREATION UNTIL THIS CHANGE, AND THE
# RESOURCE IS UNTOUCHED BECAUSE THE DEFECT WAS NEVER HERE. Nothing published
# ValueCensusHardFailTables: `list-metrics --namespace Leviathan/Silver` returned no such metric,
# and the only put_metric_data call in the repo was the freshness poller's. With
# treat_missing_data = "notBreaching" it therefore sat OK forever -- its StateReason still read
# "a1a2-delivery-test-reset" from 2026-07-16, four weeks after the fact. Exactly the "reads as
# coverage" defect the D-E RCA deleted 22 alarms for, on the one P1 class in the set.
# THE EMITTER now exists: jobs/audit/silver_rebuild_gate.py::_emit_gate_metrics publishes the
# count of tables whose `value_census` stage went RED, once per gate run. That stage runs on
# BOTH branches for every table of every run, so the coverage is the whole gated estate.
# notBreaching stays correct: the gate publishes on verdict-bearing exits only, and a day with
# no gate run (a weekend for a weekly family) is not a regression.
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "value_census_regression" {
  alarm_name          = "${local.name_prefix}-value-census-regression"
  alarm_description   = "SILVER-V001 reported >0 hard-fail tables (all-NaN / single-vintage / all-constant). Runbook: R4_incident_runbooks.md#value-census-failure-all-nan--collapsed-vintage."
  namespace           = var.silver_metric_namespace
  metric_name         = "ValueCensusHardFailTables"
  statistic           = "Maximum"
  period              = 86400
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# ---------------------------------------------------------------------------
# D-PR-28 / D-SG G3-4 -- THE GATE'S DRIFT-RIDING PASS HAS A DESTINATION.
#
# A gate REFUSAL is exit 1 -> SFN Catch -> FailNotify -> leviathan-dev-alerts. A PASS that rode
# over ANOTHER family's drift (`banner.global_drift > 0`, D-PR-5) is exit 0 BY DESIGN, so until
# this alarm its only trace was a stdout line inside one of 26 daily Batch containers. That is
# the one verdict in the vocabulary with no delivery mechanism.
#
# THE DIMENSION VALUE IS THE GATE'S OWN WORD, "PASS_WITH_DRIFT". The plan calls this class
# YELLOW and the resource keeps that name for continuity with the record, but a CloudWatch
# alarm matches an EXACT dimension value, so the string here must be the one
# jobs/audit/silver_rebuild_gate.py::_emit_gate_metrics writes -- not the prose label.
#
# DIMENSIONED {Verdict} ALONE, not {Family, Verdict}: an alarm needs an exact dimension set, so
# "drift-riding on any family" would otherwise require a SEARCH metric-math expression. The gate
# emits BOTH shapes on the freshness poller's dual-dimension precedent: {Family,Verdict} for
# attribution in the console, {Verdict} for this alarm.
#
# statistic = Sum over a 1-day period: twice in a day is worse than once, and this alarm reports
# the count in its state reason.
# treat_missing_data = notBreaching: the gate emits NOTHING on exits 64/70/71/72 (those are not
# verdicts, D-PR-8), and a quiet day is not a drift-riding pass. Those classes page via
# batch-job-failed-scheduled.
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "gate_verdict_yellow" {
  alarm_name          = "${local.name_prefix}-gate-verdict-yellow"
  alarm_description   = "The silver rebuild gate returned PASS_WITH_DRIFT at least once in the last 24h -- a PASS that promoted while carrying another family's drift (banner.global_drift > 0). It is exit 0 by design (D-PR-5), so this alarm is its only delivery mechanism. Read the WARN lines in the gate container log for the family and the drifting table. Runbook: R4_incident_runbooks.md#gate-yellow."
  namespace           = var.silver_metric_namespace
  metric_name         = "GateVerdict"
  dimensions          = { Verdict = "PASS_WITH_DRIFT" }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# ===========================================================================
# A-W5 step 3 -- ORCHESTRATION-PLANE alarms + the aws.states failure rule.
# The data-plane above catches producers; these catch the pipeline that RUNS
# them (missing from F082, L6 blocker). Same confirmed topic (local.alarm_actions),
# same style. The SFN-specific alarms + the states rule are count-gated on
# var.state_machine_arn so this module still applies standalone before A-W2 wires
# the machine ARN in; the scheduler + Batch-queued-age alarms always apply.
# ===========================================================================

# --- Step Functions execution failures on the thin-contract machine (AWS/States). ---
resource "aws_cloudwatch_metric_alarm" "sfn_executions_failed" {
  count               = var.state_machine_arn == "" ? 0 : 1
  alarm_name          = "${local.name_prefix}-sfn-executions-failed"
  alarm_description   = "The silver thin-contract state machine had >0 FAILED executions (gate FAIL or upstream task failure). Runbook: R4_incident_runbooks.md#sfn-execution-failed."
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = var.state_machine_arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  # 2026-08-04 (D-PR-12, D-ALARM-1): DEMOTED TO METRIC-ONLY. Precedent and reasoning are the D-C
  # backstop demotion at :146-151 above. This alarm fired on the SAME failures as the in-machine
  # `FailNotify` publish (modules/step_functions/main.tf) but carried NEITHER the family name NOR the
  # execution id -- it is a strictly less informative duplicate of a notification the owner already
  # gets. Measured: 24 alarm-path emails since 2026-08-01 against 8 distinct causes.
  # It also double-counts a MANUAL refire execution, which is not a schedule failure at all.
  # WHAT STILL REACHES THE OWNER after this demotion, verified path by path:
  #   * Gate / Reconcile failure         -> Catch States.ALL -> FailNotify -> leviathan-dev-alerts.
  #   * Producer (Batch) failure         -> batch-job-failed-scheduled, deliberately still ARMED.
  #   * Producer (Glue) failure          -> the glue-job-failed alarm added in modules/cloudwatch in
  #                                         this same batch (it had NO metric filter before, so this
  #                                         demotion would otherwise have opened a new silence).
  #   * Execution never STARTS           -> scheduler-target-errors + scheduler-invocations-dropped
  #                                         (both armed) for the fact, and the per-schedule DLQs
  #                                         added in this batch for the attribution.
  #   * TIMED_OUT / ABORTED              -> their own alarms below, deliberately left ARMED (neither
  #                                         reaches FailNotify).
  # RESIDUAL, STATED HONESTLY: an execution that fails BEFORE reaching any Catch and without a Batch
  # or Glue task failure (malformed input, a States.Runtime fault) is now silent. That class is
  # closed by D-PR-44's producer Catch arms, not by this alarm. Rollback = restore
  # `alarm_actions = local.alarm_actions`.
  alarm_actions = []
  tags          = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_metric_alarm" "sfn_executions_aborted" {
  count               = var.state_machine_arn == "" ? 0 : 1
  alarm_name          = "${local.name_prefix}-sfn-executions-aborted"
  alarm_description   = "The silver thin-contract state machine had >0 ABORTED executions (manual stop / drill). Runbook: R4_incident_runbooks.md#sfn-execution-aborted."
  namespace           = "AWS/States"
  metric_name         = "ExecutionsAborted"
  dimensions          = { StateMachineArn = var.state_machine_arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_metric_alarm" "sfn_executions_timed_out" {
  count               = var.state_machine_arn == "" ? 0 : 1
  alarm_name          = "${local.name_prefix}-sfn-executions-timed-out"
  alarm_description   = "The silver thin-contract state machine had >0 TIMED_OUT executions. Runbook: R4_incident_runbooks.md#sfn-execution-timed-out."
  namespace           = "AWS/States"
  metric_name         = "ExecutionsTimedOut"
  dimensions          = { StateMachineArn = var.state_machine_arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# --- EventBridge Scheduler missed/failed invocation (AWS/Scheduler, dim ScheduleGroup). ---
# TargetErrorCount = the scheduler tried to fire but the target (SFN StartExecution) returned
# an error. Keyed on the schedule group (default group holds the per-family schedules).
resource "aws_cloudwatch_metric_alarm" "scheduler_target_errors" {
  alarm_name          = "${local.name_prefix}-scheduler-target-errors"
  alarm_description   = "EventBridge Scheduler reported >0 TargetErrorCount (a schedule fired but StartExecution errored). Runbook: R4_incident_runbooks.md#scheduler-target-error."
  namespace           = "AWS/Scheduler"
  metric_name         = "TargetErrorCount"
  dimensions          = { ScheduleGroup = var.scheduler_group_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# --- Batch queued-job-age. AWS Batch emits NO native queue-age metric, so this alarms on a
# custom metric the pipeline publishes (same EMF contract as FreshnessLagDays). notBreaching so
# it stays quiet until the emitter exists. NOTE: requires a BatchQueuedJobAgeSeconds emitter
# (a small poller / Container Insights) -- flagged as a pending dependency, like the freshness cert. ---
resource "aws_cloudwatch_metric_alarm" "batch_queued_job_age" {
  alarm_name          = "${local.name_prefix}-batch-queued-job-age"
  alarm_description   = "A Batch job has sat in RUNNABLE/PENDING longer than the ceiling (stuck queue / capacity). Runbook: R4_incident_runbooks.md#batch-queued-job-age. Requires the BatchQueuedJobAgeSeconds emitter."
  namespace           = var.silver_metric_namespace
  metric_name         = "BatchQueuedJobAgeSeconds"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.batch_queued_age_threshold_seconds
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# --- aws.states execution-status rule: FAILED/TIMED_OUT/ABORTED on THIS machine.
#
# D-PR-15(i), 2026-08-04: its SNS target is REMOVED (it published into the zero-subscription
# silver-pipeline topic -- see the note at the batch rule above). THE RULE IS RETAINED ON PURPOSE and
# now has ZERO targets: it is the declared seam for D-ALARM-2, and a rule with no targets delivers
# nothing and CLAIMS nothing. Read it as an empty socket, not as coverage -- a target here is what
# would make it a path, and adding one without a confirmed subscriber on the destination is the
# exact defect this change removes. ---
resource "aws_cloudwatch_event_rule" "sfn_execution_failed" {
  count       = var.state_machine_arn == "" ? 0 : 1
  name        = "${local.name_prefix}-sfn-execution-failed"
  description = "Fires on FAILED/TIMED_OUT/ABORTED executions of the silver thin-contract state machine."

  event_pattern = jsonencode({
    source      = ["aws.states"]
    detail-type = ["Step Functions Execution Status Change"]
    detail = {
      status          = ["FAILED", "TIMED_OUT", "ABORTED"]
      stateMachineArn = [var.state_machine_arn]
    }
  })

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

