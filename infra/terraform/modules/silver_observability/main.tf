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
# treat_missing_data = breaching: no freshness datapoint means the pipeline stopped == stale.
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
  treat_missing_data  = "breaching"
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
