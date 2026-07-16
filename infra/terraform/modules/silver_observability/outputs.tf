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

# --- A-W5 step 3: orchestration-plane alarms -------------------------------
output "orchestration_alarm_names" {
  value = concat(
    [for a in aws_cloudwatch_metric_alarm.sfn_executions_failed : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.sfn_executions_aborted : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.sfn_executions_timed_out : a.alarm_name],
    [aws_cloudwatch_metric_alarm.scheduler_target_errors.alarm_name],
    [aws_cloudwatch_metric_alarm.batch_queued_job_age.alarm_name],
  )
  description = "Orchestration-plane alarm names (SFN failed/aborted/timed-out, scheduler target-errors, Batch queued-age)."
}

output "sfn_execution_failed_rule_arn" {
  value       = one(aws_cloudwatch_event_rule.sfn_execution_failed[*].arn)
  description = "aws.states FAILED/TIMED_OUT/ABORTED EventBridge rule ARN (null until state_machine_arn is wired)."
}
