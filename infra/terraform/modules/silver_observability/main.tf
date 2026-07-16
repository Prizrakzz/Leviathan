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
  alarm_actions = compact([
    aws_sns_topic.silver_pipeline.arn,
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

resource "aws_cloudwatch_event_target" "batch_failed_to_sns" {
  rule      = aws_cloudwatch_event_rule.batch_job_failed.name
  target_id = "batch-failures-sns"
  arn       = aws_sns_topic.silver_pipeline.arn
}

# SNS topic policy so EventBridge may publish the Batch-failed event.
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
  alarm_actions       = local.alarm_actions
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# ---------------------------------------------------------------------------
# Per-family Batch-job-failed alarms (app-emitted EMF metric BatchJobFailed{Family}).
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "batch_job_failed" {
  for_each = toset(var.silver_batch_families)

  alarm_name          = "${local.name_prefix}-batch-job-failed-${replace(each.key, "_", "-")}"
  alarm_description   = "A Batch job in the '${each.key}' family reached FAILED. Runbook: R4_incident_runbooks.md#batch-job-failed."
  namespace           = var.silver_metric_namespace
  metric_name         = "BatchJobFailed"
  dimensions          = { Family = each.key }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# ---------------------------------------------------------------------------
# Per-family freshness-SLA-breach alarms (certificate metric FreshnessLagDays{Family}).
# Threshold is the family's interim ceiling from the DAG catalog (silver_freshness_slas map).
#
# treat_missing_data = MISSING (A-W5 step 1b): a newly-created BREACHING alarm with zero
# datapoints transitions to ALARM within one 1-day evaluation period (period=86400,
# evaluation_periods=1). A-W5 applies BEFORE any producer emits FreshnessLagDays (critical
# path A-W5 -> A-W7), so with "breaching" all 21 freshness alarms would INSTANT-BREACH and
# email the shared topic at apply. With "missing" they sit INSUFFICIENT_DATA (no alarm_actions
# fire on INSUFFICIENT_DATA) until each family's wave activates and emits a real datapoint.
# A stopped pipeline is still caught by batch_job_failed + the EventBridge backstop + the
# orchestration-plane SFN/scheduler alarms -- NOT by freshness-on-missing. batch_job_failed and
# value_census are already notBreaching, so ONLY this freshness set needed the flip.
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "freshness_sla_breach" {
  for_each = var.silver_freshness_slas

  alarm_name          = "${local.name_prefix}-freshness-sla-breach-${replace(each.key, "_", "-")}"
  alarm_description   = "Family '${each.key}' exceeded its interim freshness ceiling (${each.value}d). Runbook: R4_incident_runbooks.md#freshness-sla-breach."
  namespace           = var.silver_metric_namespace
  metric_name         = "FreshnessLagDays"
  dimensions          = { Family = each.key }
  statistic           = "Maximum"
  period              = 86400
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = each.value
  treat_missing_data  = "missing"
  alarm_actions       = local.alarm_actions
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# ---------------------------------------------------------------------------
# Global value-census-regression alarm (SILVER-V001 metric ValueCensusHardFailTables).
# After R4 every table is census-green, so any hard-fail table is a regression -> page immediately.
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
  alarm_actions       = local.alarm_actions
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
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

# --- aws.states execution-status rule: FAILED/TIMED_OUT/ABORTED on THIS machine -> silver-pipeline topic.
# Belt-and-suspenders alongside the AWS/States alarms; the topic policy already allows
# events.amazonaws.com:Publish (aws_sns_topic_policy.silver_pipeline above). ---
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

resource "aws_cloudwatch_event_target" "sfn_execution_failed_to_sns" {
  count     = var.state_machine_arn == "" ? 0 : 1
  rule      = aws_cloudwatch_event_rule.sfn_execution_failed[0].name
  target_id = "sfn-execution-failed-sns"
  arn       = aws_sns_topic.silver_pipeline.arn
}
