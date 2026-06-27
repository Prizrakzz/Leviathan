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

output "backfill_orchestrator_job_definition_arn" {
  value       = module.batch.backfill_orchestrator_job_definition_arn
  description = "ARN of the backfill orchestrator Batch job definition."
}

output "nasa_power_backfill_job_definition_arn" {
  value       = module.batch.nasa_power_backfill_job_definition_arn
  description = "ARN of the NASA POWER backfill Batch job definition."
}

output "usda_nass_annual_silver_job_definition_arn" {
  value       = module.batch.usda_nass_annual_silver_job_definition_arn
  description = "ARN of the USDA NASS annual bronze Parquet -> silver Parquet job definition."
}

output "usda_nass_crop_progress_silver_job_definition_arn" {
  value       = module.batch.usda_nass_crop_progress_silver_job_definition_arn
  description = "ARN of the USDA NASS crop-progress bronze Parquet -> silver Parquet job definition."
}

output "glue_raw_to_bronze_nasa_power_job" {
  value       = module.glue.raw_to_bronze_nasa_power_job_name
  description = "Glue job: raw → bronze NASA POWER."
}

output "glue_raw_to_bronze_faostat_job" {
  value       = module.glue.raw_to_bronze_faostat_job_name
  description = "Glue job: raw → bronze FAOSTAT."
}

output "glue_bronze_to_silver_nasa_power_job" {
  value       = module.glue.bronze_to_silver_nasa_power_job_name
  description = "Glue job: bronze → silver NASA POWER."
}

output "glue_bronze_to_silver_faostat_job" {
  value       = module.glue.bronze_to_silver_faostat_job_name
  description = "Glue job: bronze → silver FAOSTAT."
}

output "ecr_trainer_repository_url" {
  value       = module.ecr_trainer.repository_url
  description = "ECR repository URL for the leviathan-trainer image."
}

output "mlflow_instance_id" {
  value       = module.mlflow_server.instance_id
  description = "EC2 instance ID of the MLflow tracking server (use with SSM port-forward)."
}

output "mlflow_tracking_uri" {
  value       = module.mlflow_server.tracking_uri
  description = "MLFLOW_TRACKING_URI — set this in SageMaker Training Jobs and Batch containers."
}

output "sagemaker_training_role_arn" {
  value       = module.iam.sagemaker_training_role_arn
  description = "IAM role ARN to pass as RoleArn when submitting SageMaker Training Jobs."
}
