locals {
  job_names = [
    "${var.project_name}-${var.environment}-raw-to-bronze-nasa-power",
    "${var.project_name}-${var.environment}-raw-to-bronze-faostat",
    "${var.project_name}-${var.environment}-bronze-to-silver-nasa-power",
    "${var.project_name}-${var.environment}-bronze-to-silver-faostat",
  ]
}

# ---------------------------------------------------------------------------
# Log groups — Glue writes here automatically; we manage lifecycle
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "glue_jobs" {
  for_each = toset(local.job_names)

  name              = "/aws/glue/jobs/${each.key}"
  retention_in_days = 30

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Alarms — fire when any Glue job run fails
# EventBridge publishes a glue.jobrunstate metric; we use the
# aws/glue SucceededJobRunCount and FailedJobRunCount metrics that
# Glue Job Insights emits (enabled via --enable-job-insights = true).
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "glue_job_failed" {
  name        = "${var.project_name}-${var.environment}-glue-job-failed"
  description = "Fires when any Glue job run reaches FAILED state."

  event_pattern = jsonencode({
    source      = ["aws.glue"]
    detail-type = ["Glue Job State Change"]
    detail = {
      state = ["FAILED"]
    }
  })

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_log_group" "glue_failures" {
  name              = "/leviathan/${var.environment}/glue-job-failures"
  retention_in_days = 90

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_log_resource_policy" "eventbridge_glue_failures" {
  policy_name = "${var.project_name}-${var.environment}-eventbridge-glue-failures"

  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource  = "${aws_cloudwatch_log_group.glue_failures.arn}:*"
    }]
  })
}

resource "aws_cloudwatch_event_target" "glue_failed_to_logs" {
  rule      = aws_cloudwatch_event_rule.glue_job_failed.name
  target_id = "glue-failures-log-group"
  arn       = aws_cloudwatch_log_group.glue_failures.arn
}

# ---------------------------------------------------------------------------
# Dead-letter metric filter + alarm
# Matches logger.warning("Dead-lettered %s → %s", ...) in dead_letter.py.
# A Glue job can exit SUCCEEDED while having dead-lettered individual files,
# so job-level EventBridge rules won't catch these — metric filters will.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "dead_letter" {
  for_each = toset(local.job_names)

  name           = "${var.project_name}-${var.environment}-dead-letter-${replace(each.key, "${var.project_name}-${var.environment}-", "")}"
  log_group_name = "/aws/glue/jobs/${each.key}"
  pattern        = "\"Dead-lettered\""

  metric_transformation {
    name          = "DeadLetterCount"
    namespace     = "Leviathan/${var.environment}"
    value         = "1"
    default_value = "0"
  }

  depends_on = [aws_cloudwatch_log_group.glue_jobs]
}

resource "aws_cloudwatch_metric_alarm" "dead_letter" {
  alarm_name          = "${var.project_name}-${var.environment}-dead-letter-detected"
  alarm_description   = "One or more files were dead-lettered during a Glue job run. Check s3://leviathan-${var.environment}-shahem-001/dead_letter/ for details."
  metric_name         = "DeadLetterCount"
  namespace           = "Leviathan/${var.environment}"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = []  # wire to aws_sns_topic.leviathan_alerts.arn when SNS is configured

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# ---------------------------------------------------------------------------
# Dashboard — job duration, success/failure counts per job
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "pipeline" {
  dashboard_name = "${var.project_name}-${var.environment}-pipeline"

  dashboard_body = jsonencode({
    widgets = [
      # ---- Header ----
      {
        type   = "text"
        x      = 0
        y      = 0
        width  = 24
        height = 1
        properties = {
          markdown = "## Leviathan Pipeline — ${var.environment}"
        }
      },

      # ---- Job duration ----
      {
        type   = "metric"
        x      = 0
        y      = 1
        width  = 24
        height = 6
        properties = {
          title  = "Glue Job Duration (seconds)"
          view   = "timeSeries"
          region = var.aws_region
          period = 300
          stat   = "Maximum"
          metrics = [
            for job in local.job_names : ["Glue", "glue.driver.executorRunTime", "JobName", job]
          ]
        }
      },

      # ---- Success counts ----
      {
        type   = "metric"
        x      = 0
        y      = 7
        width  = 12
        height = 4
        properties = {
          title  = "Succeeded Job Runs"
          view   = "singleValue"
          region = var.aws_region
          period = 2592000
          stat   = "Sum"
          metrics = [
            for job in local.job_names : ["Glue", "glue.driver.aggregate.numCompletedStages", "JobName", job]
          ]
        }
      },

      # ---- Failed task counts ----
      {
        type   = "metric"
        x      = 12
        y      = 7
        width  = 12
        height = 4
        properties = {
          title  = "Failed Tasks (should be 0)"
          view   = "singleValue"
          region = var.aws_region
          period = 2592000
          stat   = "Sum"
          metrics = [
            for job in local.job_names : ["Glue", "glue.driver.aggregate.numFailedTasks", "JobName", job]
          ]
        }
      },

      # ---- S3 bytes written ----
      {
        type   = "metric"
        x      = 0
        y      = 11
        width  = 24
        height = 5
        properties = {
          title  = "S3 Bytes Written per Job Run"
          view   = "timeSeries"
          region = var.aws_region
          period = 300
          stat   = "Sum"
          metrics = [
            for job in local.job_names : ["Glue", "glue.driver.aggregate.bytesWritten", "JobName", job]
          ]
        }
      }
    ]
  })
}
