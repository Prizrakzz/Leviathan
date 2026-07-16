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

variable "bucket_name" {
  type        = string
  description = "S3 bucket holding the mlflow/ prefix (artifacts under mlflow/artifacts/)."
}

variable "vpc_id" {
  type        = string
  description = "VPC of the Fargate task + RDS + Cloud Map namespace (same VPC as serving/Batch)."
}

variable "subnet_ids" {
  type        = list(string)
  description = "Public subnet IDs for the task ENI (assign_public_ip = true, no NAT). Reuses the Batch subnets."
}

variable "cluster_arn" {
  type        = string
  description = "ARN of the EXISTING serving ECS cluster (leviathan-dev-serving) the MLflow service runs on."
}

variable "rds_security_group_id" {
  type        = string
  description = "RDS (leviathan-dev-pg) SG. One ingress rule is added admitting the task SG on 5432."
}

variable "backend_dsn_secret_arn" {
  type        = string
  description = <<-EOT
    Name-based Secrets Manager ARN of the mlflow pg DSN (leviathan/dev/mlflow-backend-dsn),
    injected as MLFLOW_BACKEND_STORE_URI. The secret is created out-of-band at cutover (it holds
    the db password); the IAM grant appends -* internally for the random suffix.
  EOT
}

variable "container_image" {
  type        = string
  description = "MLflow server image. Public upstream by default; a custom ECR image bundling psycopg2 may be substituted (then the pip bootstrap is a no-op)."
  default     = "ghcr.io/mlflow/mlflow:v2.22.0"
}

variable "container_port" {
  type        = number
  description = "MLflow tracking server port."
  default     = 5000
}

variable "cpu" {
  type        = number
  description = "Fargate task CPU units. 512 = 0.5 vCPU."
  default     = 512
}

variable "memory" {
  type        = number
  description = "Fargate task memory (MiB). 1024 = 1 GB."
  default     = 1024
}

variable "service_dns_namespace" {
  type        = string
  description = "Cloud Map private DNS namespace."
  default     = "leviathan.local"
}

variable "service_dns_name" {
  type        = string
  description = "Cloud Map service name -> <name>.<namespace>."
  default     = "mlflow"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "tags" {
  type    = map(string)
  default = {}
}
