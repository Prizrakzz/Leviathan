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
  alarm_actions       = compact([var.alert_topic_arn]) # module.alerting SNS (Stage 5.2); empty -> no action

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

# ---------------------------------------------------------------------------
# Serving observability (Stage 5.2, public exposure). The ALB + ECS + WAF
# dashboard and the alarms that page module.alerting's SNS. All gated on the
# serving identifiers being passed (envs/dev), so the module stays valid when
# they aren't. The WAF panel is the count->block transition watch.
# ---------------------------------------------------------------------------
locals {
  serving_obs = var.alb_arn != "" && var.ecs_cluster_name != ""
  # CloudWatch dimension VALUES are the ARN suffixes (app/<name>/<id>, targetgroup/<name>/<id>).
  alb_lb_dim = try(regex("loadbalancer/(.+)$", var.alb_arn)[0], "")
  alb_tg_dim = try(regex("(targetgroup/.+)$", var.target_group_arn)[0], "")
}

resource "aws_cloudwatch_dashboard" "serving" {
  count          = local.serving_obs ? 1 : 0
  dashboard_name = "${var.project_name}-${var.environment}-serving"

  dashboard_body = jsonencode({
    widgets = [
      {
        type       = "text"
        x          = 0
        y          = 0
        width      = 24
        height     = 1
        properties = { markdown = "## Leviathan Serving - ${var.environment}  |  ALB / ECS / WAF" }
      },
      {
        type   = "metric"
        x      = 0
        y      = 1
        width  = 12
        height = 6
        properties = {
          title  = "ALB requests + target 5xx"
          view   = "timeSeries"
          region = var.aws_region
          period = 60
          stat   = "Sum"
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", local.alb_lb_dim],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", local.alb_lb_dim, { color = "#d62728" }],
            ["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", local.alb_lb_dim, { color = "#ff7f0e" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 1
        width  = 12
        height = 6
        properties = {
          title  = "Target response time (p95, s)"
          view   = "timeSeries"
          region = var.aws_region
          period = 60
          stat   = "p95"
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", local.alb_lb_dim],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 7
        width  = 12
        height = 6
        properties = {
          title  = "Target health (hosts)"
          view   = "timeSeries"
          region = var.aws_region
          period = 60
          stat   = "Average"
          metrics = [
            ["AWS/ApplicationELB", "HealthyHostCount", "TargetGroup", local.alb_tg_dim, "LoadBalancer", local.alb_lb_dim, { color = "#2ca02c" }],
            ["AWS/ApplicationELB", "UnHealthyHostCount", "TargetGroup", local.alb_tg_dim, "LoadBalancer", local.alb_lb_dim, { color = "#d62728" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 7
        width  = 12
        height = 6
        properties = {
          title  = "ECS CPU / Memory (%)"
          view   = "timeSeries"
          region = var.aws_region
          period = 60
          stat   = "Average"
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", var.ecs_service_name],
            ["AWS/ECS", "MemoryUtilization", "ClusterName", var.ecs_cluster_name, "ServiceName", var.ecs_service_name],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 13
        width  = 24
        height = 6
        properties = {
          title  = "WAF allowed / counted / blocked (count->block watch)"
          view   = "timeSeries"
          region = var.aws_region
          period = 300
          stat   = "Sum"
          metrics = [
            ["AWS/WAFV2", "AllowedRequests", "WebACL", var.waf_web_acl_name, "Region", var.aws_region, "Rule", "ALL", { color = "#2ca02c" }],
            ["AWS/WAFV2", "CountedRequests", "WebACL", var.waf_web_acl_name, "Region", var.aws_region, "Rule", "ALL", { color = "#ff7f0e" }],
            ["AWS/WAFV2", "BlockedRequests", "WebACL", var.waf_web_acl_name, "Region", var.aws_region, "Rule", "ALL", { color = "#d62728" }],
          ]
        }
      },
      # ---- Stage 5.3 R3: per-turn app metrics from EMF (namespace Leviathan/Serving), emitted to stdout by
      #      orchestrator.respond and auto-extracted by CloudWatch Logs. Aggregate (no-dimension) series. ----
      {
        type   = "metric"
        x      = 0
        y      = 19
        width  = 12
        height = 6
        properties = {
          title  = "Turn latency (p50 / p95, ms) - EMF"
          view   = "timeSeries"
          region = var.aws_region
          period = 300
          metrics = [
            ["Leviathan/Serving", "TurnLatencyMs", { stat = "p50", color = "#1f77b4", label = "p50" }],
            ["Leviathan/Serving", "TurnLatencyMs", { stat = "p95", color = "#d62728", label = "p95" }],
            ["Leviathan/Serving", "MsFill", { stat = "Average", color = "#9467bd", label = "fill avg" }],
            ["Leviathan/Serving", "MsRest", { stat = "Average", color = "#8c564b", label = "rest avg" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 19
        width  = 12
        height = 6
        properties = {
          title  = "Citation strips / turn (quality signal) + turns"
          view   = "timeSeries"
          region = var.aws_region
          period = 300
          metrics = [
            ["Leviathan/Serving", "StripCount", { stat = "Sum", color = "#ff7f0e", label = "strips (sum)" }],
            ["Leviathan/Serving", "TurnLatencyMs", { stat = "SampleCount", color = "#2ca02c", label = "turns" }],
          ]
        }
      },
    ]
  })
}

# Target 5xx: the ECS task is erroring on real requests.
resource "aws_cloudwatch_metric_alarm" "serving_target_5xx" {
  count               = local.serving_obs ? 1 : 0
  alarm_name          = "${var.project_name}-${var.environment}-serving-target-5xx"
  alarm_description   = "Serving ALB target 5xx elevated (>10/5min) - the ECS task is erroring."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = local.alb_lb_dim }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 10
  treat_missing_data  = "notBreaching"
  alarm_actions       = compact([var.alert_topic_arn])
  ok_actions          = compact([var.alert_topic_arn])
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# Unhealthy host: the single serving task is failing health checks / down (min=1, so this is an outage).
resource "aws_cloudwatch_metric_alarm" "serving_unhealthy_host" {
  count               = local.serving_obs ? 1 : 0
  alarm_name          = "${var.project_name}-${var.environment}-serving-unhealthy-host"
  alarm_description   = "Serving ALB reports an unhealthy target for 3min - the task is down or failing /healthz."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  dimensions          = { TargetGroup = local.alb_tg_dim, LoadBalancer = local.alb_lb_dim }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = compact([var.alert_topic_arn])
  ok_actions          = compact([var.alert_topic_arn])
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# CPU pressure: sustained >85% (CPU target-tracking scales toward max=2, so a sustained breach means the
# safety valve is saturated — investigate rather than scale further; scaling out splits the Cohere quota).
resource "aws_cloudwatch_metric_alarm" "serving_cpu_high" {
  count               = local.serving_obs ? 1 : 0
  alarm_name          = "${var.project_name}-${var.environment}-serving-cpu-high"
  alarm_description   = "Serving ECS CPU >85% for 15min - capacity pressure (CPU autoscaling min=1/max=2)."
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  dimensions          = { ClusterName = var.ecs_cluster_name, ServiceName = var.ecs_service_name }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  comparison_operator = "GreaterThanThreshold"
  threshold           = 85
  treat_missing_data  = "notBreaching"
  alarm_actions       = compact([var.alert_topic_arn])
  tags                = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}
