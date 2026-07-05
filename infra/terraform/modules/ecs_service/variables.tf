variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "vpc_id" {
  type        = string
  description = "VPC of the Fargate tasks + RDS (same as the ALB)."
}

variable "subnet_ids" {
  type        = list(string)
  description = "Public subnet IDs for the Fargate task ENIs (assign_public_ip = true, no NAT). Reuses Batch subnets."
}

variable "alb_security_group_id" {
  type        = string
  description = "ALB SG — the only source allowed inbound to the task on container_port."
}

variable "target_group_arn" {
  type        = string
  description = "ALB target group the service registers into."
}

variable "container_image" {
  type        = string
  description = "Full serving image ref, e.g. <acct>.dkr.ecr.<region>.amazonaws.com/leviathan-dev-leviathan-embedder:latest"
}

variable "container_port" {
  type    = number
  default = 8080
}

variable "task_role_arn" {
  type        = string
  description = "ECS task role (app perms: Bedrock + ApplyGuardrail + S3 + Athena). Reuses the Batch job role."
}

variable "execution_role_arn" {
  type        = string
  description = "ECS execution role (ECR pull + CloudWatch Logs + Secrets injection). Reuses the Batch execution role."
}

variable "cpu" {
  type        = number
  description = "Fargate task CPU units. 2048 = 2 vCPU (holds the BGE reranker + causal graph in memory)."
  default     = 2048
}

variable "memory" {
  type        = number
  description = "Fargate task memory (MiB). 8192 = 8 GB."
  default     = 8192
}

variable "ephemeral_storage_gib" {
  type        = number
  description = "Task ephemeral storage. bge-m3 (~4.5 GB) is fetched from HF into /opt/hf at runtime."
  default     = 30
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "min_count" {
  type        = number
  description = "Autoscaling floor. NEVER 0 — a cold task reloads the BGE reranker + graph + warms slices."
  default     = 1
}

variable "max_count" {
  type    = number
  default = 3
}

variable "cpu_target" {
  type        = number
  description = "Target-tracking average CPU %% for autoscaling."
  default     = 60
}

variable "health_check_grace" {
  type        = number
  description = "Seconds ECS waits before health-checking a new task (BGE + graph warmup)."
  default     = 300
}

variable "rds_security_group_id" {
  type        = string
  description = "RDS (leviathan-dev-pg) SG — an ingress rule is added allowing the task SG on 5432."
}

variable "pg_dsn_secret_arn" {
  type        = string
  description = "Secrets Manager ARN of the pg DSN, injected as EVIDENCE_PG_DSN."
}

variable "guardrail_id" {
  type        = string
  description = "Bedrock guardrail id -> GRAPHRAG_GUARDRAIL (serving input pre-filter, on in prod)."
}

variable "guardrail_version" {
  type        = string
  description = "Guardrail version -> GRAPHRAG_GUARDRAIL_VERSION."
  default     = "DRAFT"
}

variable "evidence_backend" {
  type    = string
  default = "pg"
}

variable "graphrag_provider" {
  type    = string
  default = "bedrock"
}

variable "cors_origins" {
  type        = string
  description = "GRAPHRAG_CORS_ORIGINS. Stage 1 = http://localhost:5173; Stage 4 = the prod origin(s)."
  default     = "http://localhost:5173"
}

variable "extra_environment" {
  type        = map(string)
  description = "Additional plain env vars to merge into the container (e.g. GRAPHRAG_AUTH + COGNITO_* in Stage 4)."
  default     = {}
}

variable "leviathan_bucket" {
  type = string
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "tags" {
  type    = map(string)
  default = {}
}
