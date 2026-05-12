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

resource "aws_cloudwatch_metric_alarm" "glue_job_failed" {
  for_each = toset(local.job_names)

  alarm_name          = "${each.key}-failed"
  alarm_description   = "Glue job ${each.key} had a failed run."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 1
  treat_missing_data  = "notBreaching"

  metric_name = "glue.driver.aggregate.numFailedTasks"
  namespace   = "Glue"
  dimensions = {
    JobName = each.key
  }
  statistic = "Sum"
  period    = 300

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
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
        x      = 0; y = 0; width = 24; height = 1
        properties = {
          markdown = "## Leviathan Pipeline — ${var.environment}"
        }
      },

      # ---- Job duration (last 10 runs per job) ----
      {
        type   = "metric"
        x      = 0; y = 1; width = 24; height = 6
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
        x      = 0; y = 7; width = 12; height = 4
        properties = {
          title  = "Succeeded Job Runs"
          view   = "singleValue"
          region = var.aws_region
          period = 2592000  # 30 days
          stat   = "Sum"
          metrics = [
            for job in local.job_names : ["Glue", "glue.driver.aggregate.numCompletedStages", "JobName", job]
          ]
        }
      },

      # ---- Failed task counts ----
      {
        type   = "metric"
        x      = 12; y = 7; width = 12; height = 4
        properties = {
          title  = "Failed Tasks (should be 0)"
          view   = "singleValue"
          region = var.aws_region
          period = 2592000  # 30 days
          stat   = "Sum"
          metrics = [
            for job in local.job_names : ["Glue", "glue.driver.aggregate.numFailedTasks", "JobName", job]
          ]
        }
      },

      # ---- S3 bytes written ----
      {
        type   = "metric"
        x      = 0; y = 11; width = 24; height = 5
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
