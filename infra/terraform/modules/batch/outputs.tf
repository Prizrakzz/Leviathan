output "backfill_orchestrator_job_definition_arn" {
  value       = aws_batch_job_definition.backfill_orchestrator.arn
  description = "ARN of the backfill orchestrator Batch job definition."
}

output "job_queue_arn" {
  value       = aws_batch_job_queue.this.arn
  description = "ARN of the shared Batch job queue."
}

output "job_queue_name" {
  value       = aws_batch_job_queue.this.name
  description = "Name of the shared Batch job queue."
}

output "chirps_to_bronze_backfill_job_definition_arn" {
  value       = aws_batch_job_definition.chirps_to_bronze_backfill.arn
  description = "ARN of the CHIRPS COG → bronze backfill job definition."
}

output "nasa_power_backfill_job_definition_arn" {
  value       = aws_batch_job_definition.nasa_power_backfill.arn
  description = "ARN of the NASA POWER backfill job definition."
}

output "log_group_name" {
  value       = aws_cloudwatch_log_group.batch.name
  description = "CloudWatch log group for Batch jobs."
}
