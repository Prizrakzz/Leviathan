variable "project_name" {
  type        = string
  description = "Project name (e.g. leviathan)."
}

variable "environment" {
  type        = string
  description = "Environment name (e.g. dev)."
}

variable "aws_region" {
  type        = string
  description = "AWS region."
  default     = "us-east-1"
}

variable "alert_topic_arn" {
  type        = string
  description = "Shared module.alerting SNS topic ARN (fallback alarm destination). Empty = rely only on the silver-pipeline topic."
  default     = ""
}

variable "silver_alert_email" {
  type        = string
  description = "Email for the silver-pipeline SNS subscription placeholder. Empty (default) = no subscription created; the topic still exists for EventBridge + alarms."
  default     = ""
}

variable "silver_metric_namespace" {
  type        = string
  description = "CloudWatch namespace for the app-emitted silver pipeline metrics. From silver_observability.auto.tfvars.json (jobs/observability/silver_alarms.py)."
  default     = "Leviathan/Silver"
}

variable "silver_batch_families" {
  type        = list(string)
  description = "DAG-catalog family keys that carry a source Batch DAG (per-family Batch-failed alarm). From silver_observability.auto.tfvars.json."
  default     = []
}

variable "silver_freshness_slas" {
  type        = map(number)
  description = "family_key -> interim freshness ceiling (days) for the freshness-SLA-breach alarms. From silver_observability.auto.tfvars.json."
  default     = {}
}

variable "silver_extra_family_slas" {
  type        = map(number)
  description = <<-EOT
    D-PR-15(ii). family_key -> freshness ceiling (days) for families the poller EMITS but the
    generated `silver_freshness_slas` map does not cover, because they are not registry BATCH
    families. HAND-WIRED FROM THE ROOT, deliberately NOT written into
    silver_observability.auto.tfvars.json -- that file is generated and is under the D-EI-12 hold.
    Merged over `silver_freshness_slas` in the freshness_sla_breach for_each, so a key that later
    appears in the generated map simply takes the generated value.
    ONLY add a family here whose datapoints you have verified EXIST: these alarms are
    treat_missing_data = "breaching", so a family that emits nothing pages on creation forever.
  EOT
  default     = {}
}

variable "silver_breach_count_static_families" {
  type        = list(string)
  description = <<-EOT
    D-SG G3-1 / review M-6. Families SUBTRACTED from the freshness_breach_count for_each
    because every member is deliberately unscheduled/static, so a breach-count alarm would
    page continuously about a table nothing produces. Current: model_output (only member
    silver_model_predictions -- writer STOPPED, partitions pruned 2026-07-14, disposition is
    the G5 STATIC-pending set / owner decision D25). Remove a family the day it regains a
    producer; the FreshnessBreachCount METRIC keeps emitting for it either way.
  EOT
  default     = ["model_output"]
}

variable "silver_table_freshness_slas" {
  type = map(object({
    family    = string
    threshold = number
    basis     = string
  }))
  description = <<-EOT
    table_name -> {family, threshold(days), basis} for the PER-TABLE freshness-SLA-breach alarms
    (the four tables the freshness audit found ran stale-green for 6-10 weeks: their FAMILY ceiling
    was too loose to catch a per-table stall). Emitted into silver_observability.auto.tfvars.json by
    jobs/observability/silver_alarms.py (BURNED_TABLE_FRESHNESS). Empty default = no per-table alarms.
  EOT
  default     = {}
}

# --- A-W5 step 3: orchestration-plane alarm inputs -------------------------
variable "state_machine_arn" {
  type        = string
  description = <<-EOT
    ARN of the silver thin-contract state machine (module.step_functions). Drives the
    AWS/States ExecutionsFailed/Aborted/TimedOut alarms + the aws.states failure rule,
    all count-gated on this being non-empty so the module still applies before A-W2
    wires the machine in. Empty (default) = no SFN-specific alarms/rule.
  EOT
  default     = ""
}

variable "scheduler_group_name" {
  type        = string
  description = "EventBridge Scheduler group holding the per-family schedules -- the ScheduleGroup dimension for the TargetErrorCount alarm. Default group unless a named group is created."
  default     = "default"
}

variable "batch_queued_age_threshold_seconds" {
  type        = number
  description = "Ceiling (seconds) for the Batch queued-job-age alarm (custom metric BatchQueuedJobAgeSeconds)."
  default     = 3600
}

# --- P6 / P7, 2026-09-22: THE DATA (CONTENT) AXIS -------------------------------------------
# Every variable above this line feeds an alarm that reads S3 WRITE recency. A producer that
# re-writes a byte-identical object on its fire cadence is GREEN on all of them forever while its
# CONTENT is dead -- MEASURED on this estate 2026-09-22: silver_sagis_weekly_exports read
# FreshnessLagRatio 0.211 (green) beside a DataDateAgeRatio of 46.263, and eleven tables breach on
# the content axis with seven of them green on every write-axis alarm in the account.
#
# All three are GENERATED into silver_observability.auto.tfvars.json by
#     python jobs/observability/silver_alarms.py --emit-tfvars infra/terraform/envs/dev
# from leviathan.silver.freshness, and are under the D-EI-12 generated-file hold: NEVER hand-edit
# the tfvars, edit the registry contract or the generator and re-run it. Every default is the inert
# one, so the module applies unchanged in an environment that has not wired them.
variable "silver_data_date_slas" {
  type = map(object({
    family          = string
    ratio_threshold = number
    ceiling_days    = number
    basis           = string
  }))
  description = <<-EOT
    table_name -> the DATA-axis alarm contract {family, ratio_threshold, ceiling_days, basis} for
    the per-table data_date_age_breach alarms (poller metric DataDateAgeRatio{Table}).
    ratio_threshold is 1.0 for every entry by construction: the denominator is the TABLE'S OWN
    declared ceiling, so 1.0 means "past the promise this contract already makes" for an annual
    table and a daily one alike -- the same argument that justified FreshnessLagRatio's 1.0 in
    D-PR-14, which is why this needs no week of measured data first.
    Generated from freshness.data_date_alarm_targets(), which admits a table only when it is
    polled, DECLARES a knowledge axis, and is not named in freshness.STATIC_DATA_TARGETS.
    Empty default = no data-date alarms.
  EOT
  default     = {}
}

variable "silver_expected_poll_targets" {
  type        = number
  description = <<-EOT
    How many targets the REPO registry declares the freshness poller should poll -- the threshold
    of the freshness_targets_polled alarm, and the one alarm in this module that pages on ABSENCE
    of the data axis. MEASURED 2026-09-21: the poller emitted 46 while the repo enumerated 53,
    because the image it runs from carried a configs/silver/tables five weeks behind HEAD; four
    contracts were unmeasured and a RETIRED surface was still polled, invisible for five weeks.
    GENERATED from the same registry the poller reads, so it can never be a stale literal.
    0 (default) disables the census alarm.
  EOT
  default     = 0
}

variable "silver_data_date_static" {
  type        = map(string)
  description = <<-EOT
    table_name -> why its source is CLOSED (census threat T8). These targets are EXCLUDED FROM THE
    ALARM and from nothing else: the poller still READS a declared axis on them and still emits
    DataDateAgeDays/DataDateAgeRatio tagged static every cycle, which is what makes each entry's
    own removal trigger -- "delete it the day the source publishes again" -- observable at all.
    (Round 1 of this change suppressed the emission too, which deleted a live reading on
    silver_mpoc_exports_by_country and made the exit condition invisible; adversarial review M1.)
    Consumed here for the disjointness PRECONDITION on data_date_age_breach and for the operator
    note on data_date_unread -- never as a filter, because the filter already happened in the
    generator. Empty default = no declared archives.
  EOT
  default     = {}
}

variable "silver_lane_alarms" {
  type = map(object({
    alarm_name          = string
    metric_name         = string
    dimensions          = map(string)
    statistic           = string
    period              = number
    evaluation_periods  = number
    datapoints_to_alarm = number
    comparison_operator = string
    threshold           = number
    treat_missing_data  = string
    description         = string
  }))
  description = <<-EOT
    failure_mode -> the fully specified alarm for the TEXT / CORPUS LANE (corpus_fold_liveness,
    corpus_fold_wrote_nothing, wasde_text_errors, wasde_text_infra_errors). Generated by
    jobs/observability/silver_alarms.py --emit-tfvars from the alarm DOCUMENT, and an entry is
    present ONLY when the account's own metric census (silver_published_metrics.json, written by
    --census-published-metrics) lists the alarm's (metric, dimensions) stream -- an alarm on a
    stream that never published goes red on the apply that creates it. Never hand-edit; re-run
    the generator. Empty default = no lane alarms.
  EOT
  default     = {}
}
