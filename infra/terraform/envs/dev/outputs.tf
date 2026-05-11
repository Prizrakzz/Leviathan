output "bucket_name" {
  value = module.s3.bucket_name
}

output "bucket_arn" {
  value = module.s3.bucket_arn
}

output "s3_rw_policy_arn" {
  value = module.iam.s3_rw_policy_arn
}

output "ecr_repository_url" {
  value       = module.ecr.repository_url
  description = "ECR repository URL for the leviathan worker image."
}

output "batch_job_queue_name" {
  value       = module.batch.job_queue_name
  description = "Name of the Batch job queue."
}

output "nasa_power_backfill_job_definition_arn" {
  value       = module.batch.nasa_power_backfill_job_definition_arn
  description = "ARN of the NASA POWER backfill Batch job definition."
}

