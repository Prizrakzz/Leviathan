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
  description = "MLflow server image. Baked ECR image (docker/mlflow/Dockerfile) with mlflow==3.14.0 + psycopg2-binary + boto3 + gunicorn -- NOTHING is pip-installed at boot (the old ghcr.io runtime-pip crashlooped with no logs)."
  default     = "668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-mlflow:latest"
}

variable "container_port" {
  type        = number
  description = "MLflow tracking server port."
  default     = 5000
}

variable "cpu" {
  type        = number
  description = "Fargate task CPU units. 512 = 0.5 vCPU."
  default     = 1024
}

variable "memory" {
  type        = number
  description = "Fargate task memory (MiB). 1024 = 1 GB."
  default     = 2048
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

# ---------------------------------------------------------------------------
# Internet-facing authenticated endpoint (Problem 2). An ALB fronts the task so
# the user opens https://mlflow.<public_domain> in a browser and signs in with
# their EXISTING Cognito/Google account (the same pool the serving app uses).
# Kill-switch: mlflow_public_https=false -> HTTP:80 ALB locked to mlflow_admin_cidrs
# (no Cognito), for the fallback documented when an HTTPS/Cognito fact is missing.
# ---------------------------------------------------------------------------
variable "mlflow_public_https" {
  type        = bool
  description = "true = internet-facing HTTPS:443 ALB with authenticate-cognito (default). false = HTTP:80 ALB locked to mlflow_admin_cidrs, no auth (fallback)."
  default     = true
}

variable "mlflow_subdomain" {
  type        = string
  description = "Subdomain label for the MLflow endpoint -> <subdomain>.<public_domain> (covered by the *.<public_domain> wildcard cert)."
  default     = "mlflow"
}

variable "public_domain" {
  type        = string
  description = "Public apex domain (leviathanconvexity.com). The endpoint is <mlflow_subdomain>.<public_domain>."
}

variable "public_zone_id" {
  type        = string
  description = "Route53 public hosted zone id for public_domain (the mlflow alias A record is added to it)."
}

variable "certificate_arn" {
  type        = string
  description = "ACM cert ARN for the HTTPS:443 listener. Must have a SAN covering <mlflow_subdomain>.<public_domain> (the serving *.<domain> wildcard does)."
  default     = ""
}

variable "cognito_user_pool_id" {
  type        = string
  description = "EXISTING Cognito user pool id (module.cognito.user_pool_id). A dedicated ALB app client is created in it."
  default     = ""
}

variable "cognito_user_pool_arn" {
  type        = string
  description = "ARN of the same Cognito user pool (for the ALB authenticate-cognito action)."
  default     = ""
}

variable "cognito_user_pool_domain" {
  type        = string
  description = "Cognito hosted-UI domain PREFIX (module.cognito.domain_prefix, e.g. leviathan-terminal) the ALB redirects to."
  default     = ""
}

variable "mlflow_admin_cidrs" {
  type        = list(string)
  description = "Fallback (mlflow_public_https=false) ALB ingress allow-list. Default the dormant serving_admin_cidrs. Ignored in the HTTPS+Cognito path (world can reach 443, Cognito gates)."
  default     = []
}
