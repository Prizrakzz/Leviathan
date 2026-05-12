output "job_queue_arn" {
  value       = aws_batch_job_queue.this.arn
  description = "ARN of the shared Batch job queue."
}

output "job_queue_name" {
  value       = aws_batch_job_queue.this.name
  description = "Name of the shared Batch job queue."
}

output "nasa_power_backfill_job_definition_arn" {
  value       = aws_batch_job_definition.nasa_power_backfill.arn
  description = "ARN of the NASA POWER backfill job definition."
}

output "log_group_name" {
  value       = aws_cloudwatch_log_group.batch.name
  description = "CloudWatch log group for Batch jobs."
}
