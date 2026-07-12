output "silver_pipeline_topic_arn" {
  value       = aws_sns_topic.silver_pipeline.arn
  description = "SNS topic ARN for silver-pipeline alarms + the EventBridge Batch-failed rule."
}

output "batch_job_failed_rule_arn" {
  value       = aws_cloudwatch_event_rule.batch_job_failed.arn
  description = "EventBridge rule ARN for AWS Batch FAILED state changes (the glue-job-failed rule extended to Batch)."
}

output "batch_failed_alarm_names" {
  value       = [for a in aws_cloudwatch_metric_alarm.batch_job_failed : a.alarm_name]
  description = "Per-family Batch-job-failed alarm names."
}

output "freshness_alarm_names" {
  value       = [for a in aws_cloudwatch_metric_alarm.freshness_sla_breach : a.alarm_name]
  description = "Per-family freshness-SLA-breach alarm names."
}

output "value_census_alarm_name" {
  value       = aws_cloudwatch_metric_alarm.value_census_regression.alarm_name
  description = "The global value-census-regression alarm name."
}
