output "s3_rw_policy_arn" {
  value = aws_iam_policy.s3_data_lake_rw.arn
}

output "batch_execution_role_arn" {
  value       = aws_iam_role.batch_execution_role.arn
  description = "ARN of the Fargate execution role (pulls ECR image, writes CloudWatch logs)."
}

output "batch_job_role_arn" {
  value       = aws_iam_role.batch_job_role.arn
  description = "ARN of the Batch job role (container code uses this to access S3)."
}

output "glue_job_role_arn" {
  value       = aws_iam_role.glue_job_role.arn
  description = "ARN of the Glue job role (Glue Python Shell jobs use this to access S3)."
}

output "sagemaker_training_role_arn" {
  value       = aws_iam_role.sagemaker_training_role.arn
  description = "ARN of the SageMaker training role (passed as RoleArn in CreateTrainingJob calls)."
}
output "batch_job_role_name" {
  value       = aws_iam_role.batch_job_role.name
  description = "Role NAME (for policy attachments in sibling modules, e.g. the Bedrock guardrail)."
}
