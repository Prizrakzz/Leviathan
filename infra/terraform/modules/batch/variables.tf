variable "project_name" {
  type        = string
  description = "Project name."
}

variable "environment" {
  type        = string
  description = "Environment name."
}

variable "aws_region" {
  type        = string
  description = "AWS region."
}

variable "max_vcpus" {
  type        = number
  description = "Maximum vCPUs for the Fargate compute environment."
  default     = 16
}

variable "subnet_ids" {
  type        = list(string)
  description = "List of subnet IDs for Fargate tasks (must have outbound internet access)."
}

variable "security_group_ids" {
  type        = list(string)
  description = "List of security group IDs for Fargate tasks."
}

variable "ecr_repository_url" {
  type        = string
  description = "ECR repository URL for the leviathan worker image."
}

variable "batch_execution_role_arn" {
  type        = string
  description = "ARN of the Fargate execution role."
}

variable "batch_job_role_arn" {
  type        = string
  description = "ARN of the Batch job role (used by container code)."
}

variable "leviathan_bucket" {
  type        = string
  description = "S3 bucket name for the data lake."
}

variable "fas_api_key_secret_arn" {
  # Secrets Manager ARN (name-based) for the USDA FAS / api.data.gov key, mounted as FAS_API_KEY on
  # the weekly ESR fetch job (usda_esr_fetch). The secret leviathan/dev/fas-api-key does NOT exist
  # yet -- its creation is USER-GATED (D-W1; value lives in the local .env). The job only launches
  # after the secret is created and the execution role is granted GetSecretValue. Empty = jobdef not created.
  type        = string
  description = "Secrets Manager ARN (name-based) for the USDA FAS key mounted as FAS_API_KEY on the weekly ESR fetch job. Empty = the fetch jobdef is not created (user-gated secret, D-W1)."
  default     = ""
}
