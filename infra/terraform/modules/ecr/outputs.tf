output "repository_url" {
  value       = aws_ecr_repository.this.repository_url
  description = "ECR repository URL (used as Docker image base in Batch job definitions)."
}

output "repository_arn" {
  value       = aws_ecr_repository.this.arn
  description = "ECR repository ARN."
}
