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

variable "pattern_records_image" {
  # T2B (plan sec 7 step 3/5): the EMBEDDER image pinned BY DIGEST
  # ("<repo>@sha256:..."), CONTENT-CHECKED before pinning -- never a tag, never
  # :latest (the d9b2e10e stale-:latest lesson). Doubles as the jobdef's
  # GRAPHRAG_ENGINE_VERSION stamp, which is the code axis of the write-guard.
  # Empty (default) = the sweep jobdef is NOT created; the main loop pins the
  # real digest at rollout step 3.
  type        = string
  description = "Digest-pinned embedder image ref for the pattern-records sweep jobdef. Empty = jobdef not created (digest pinned at rollout step 3, after the content check)."
  default     = ""
}

variable "pattern_records_job_role_arn" {
  type        = string
  description = "ARN of the DEDICATED pattern-records sweep job role (writes ONLY gold/pattern_records/*). Never the shared batch_job_role, which the serving task reuses."
  default     = ""
}

variable "numbers_pg_dsn_secret_arn" {
  type        = string
  description = "Secrets Manager ARN of the numbers/evidence pg DSN, injected as EVIDENCE_PG_DSN on the pattern-records sweep jobdef. The sweep is pg-only by construction and refuses to run without it."
  default     = ""
}

variable "publish_signer_kms_key_arn" {
  type        = string
  description = "ARN of the A-W1 publish-signer CMK. Set as LEVIATHAN_KMS_KEY_ID so a scheduled canonical publish can self-mint its short-lived PublishApproval (inert without the kms:Sign grant on the job role)."
  default     = ""
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
