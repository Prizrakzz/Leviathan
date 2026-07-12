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

output "notifications_job_role_arn" {
  value       = length(aws_iam_role.notifications_job) > 0 ? aws_iam_role.notifications_job[0].arn : ""
  description = "P3 notifications job role (dedicated, Scan-scoped; the dedicated jobdef's jobRoleArn)."
}

# SILVER-F014 (R1) two-role separation.
output "silver_validator_role_arn" {
  value       = aws_iam_role.silver_validator.arn
  description = "SILVER-F014 read-only validator role ARN (jobRoleArn for the F016 validation job)."
}

output "silver_validator_role_name" {
  value       = aws_iam_role.silver_validator.name
  description = "SILVER-F014 read-only validator role NAME (== constants.SILVER_VALIDATOR_ROLE_NAME)."
}

output "silver_publisher_role_arn" {
  value       = aws_iam_role.silver_publisher.arn
  description = "SILVER-F014 gated deployer/publisher role ARN (canonical writes fenced by the approval flag + a signed publish_guard approval)."
}

output "silver_publisher_role_name" {
  value       = aws_iam_role.silver_publisher.name
  description = "SILVER-F014 gated publisher role NAME (== constants.SILVER_PUBLISHER_ROLE_NAME; matched by publish_guard's canonical role-ARN pattern)."
}
