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

variable "numbers_pg_dsn_secret_arn" {
  type        = string
  description = "T2B: Secrets Manager ARN of the numbers/evidence pg DSN mounted as EVIDENCE_PG_DSN on the pattern-records sweep jobdef. Grants the batch EXECUTION role GetSecretValue (Batch injects secrets under the execution role, not the job role). Empty = no grant."
  default     = ""
}

# SILVER-F014 (R1) — two fail-closed flags on the gated publisher role. Both DEFAULT
# to the safe posture (canonical silver/ denied, repair off). Flipping either is a
# governed, signed-approval action (see reports/silver_readiness/R1_F014_iam_gate.md).
variable "silver_canonical_publish_approved" {
  type        = bool
  description = "SILVER-F014: when false (default) an EXPLICIT DENY on canonical silver/ writes (S3 + Glue silver_* mutation) is attached to the publisher role. A signed approval flips this to true to drop the deny. NEVER default-true."
  default     = false
}

variable "publisher_repair_enabled" {
  type        = bool
  description = "SILVER-F014: gates the publisher's UpdatePartition/Delete/prune 'repair' capability (a flag, not a separate role). Default false = no repair grant. Even when true, the canonical silver/ deny still applies until silver_canonical_publish_approved."
  default     = false
}
