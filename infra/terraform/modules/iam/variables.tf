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

variable "dynamodb_table_arns" {
  type        = list(string)
  description = "DynamoDB table ARNs the serving task role may read/write (terminal-store + graphrag-sessions). Empty = no grant (Stage-4 opt-in)."
  default     = []
}
variable "notifications_store_table_arn" {
  type        = string
  description = "Terminal-store table ARN for the P3 notifications job's dedicated Scan-scoped role. Empty = role not created."
  default     = ""
}

variable "fas_api_key_secret_arn" {
  type        = string
  description = "Secrets Manager ARN (name-based) for the USDA FAS key mounted as FAS_API_KEY on the weekly ESR fetch job. Grants the batch EXECUTION role GetSecretValue so the ECS agent can inject the secret. The secret is user-gated (created later, D-W1); empty = no grant."
  default     = ""
}
