variable "project_name" {
  type        = string
  description = "Project name."
}

variable "environment" {
  type        = string
  description = "Environment name."
}

variable "bucket_arn" {
  type        = string
  description = "S3 bucket ARN."
}

variable "ecr_trainer_repository_arn" {
  type        = string
  description = "ARN of the leviathan-trainer ECR repository. Grants the SageMaker training role pull access."
}