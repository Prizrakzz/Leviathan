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

# --- PRICE_AND_PLAYBOOKS W1a + W2: the two futures_eod chains ---------------

variable "futures_eod_image_digest" {
  # The sha256 digest of the WORKER image the futures_eod jobdefs run, assembled in
  # the module against var.ecr_repository_url (same repo, unlike pattern_records'
  # embedder). NOT a tag: `databento` and `xlrd` are the two runtime deps whose
  # absence is SILENT at ingest (the yfinance ImportError wrote nothing for six weeks
  # under no freshness alarm), so the pin is what certifies which build carries them.
  # Empty count-gates ALL THREE futures_eod jobdefs out of existence.
  type        = string
  description = "sha256 digest of the worker image the futures_eod fetch + silver jobdefs run, e.g. 'sha256:abc...'. Empty = none of the three futures_eod jobdefs are created."
  default     = ""

  validation {
    condition     = var.futures_eod_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.futures_eod_image_digest))
    error_message = "futures_eod_image_digest must be empty or a full 'sha256:<64 hex>' digest -- a TAG is not accepted (the silent-missing-dependency class of failure this pin exists to prevent is exactly what a moving tag reintroduces)."
  }
}

variable "silver_publisher_job_role_arn" {
  # module.iam.silver_publisher_role_arn -- the SILVER-F014 gated writer. Required by
  # the futures_eod silver jobdef because silver_futures_eod is a class-A REGISTERED-
  # partition table: publishing calls glue:CreatePartition/BatchCreatePartition, which
  # lives on silver_publisher_base and NOT on the shared batch_job_role.
  type        = string
  description = "ARN of the SILVER-F014 silver-publisher role (the gated writer) used as jobRoleArn by the futures_eod silver jobdef. Empty = that jobdef is not created."
  default     = ""
}

variable "databento_api_key_secret_arn" {
  # Secrets Manager ARN (name-based) for leviathan/dev/databento-api-key, mounted as
  # DATABENTO_API_KEY on the Databento fetch job. The secret's creation is USER-GATED
  # (futures_eod_databento.json precondition (c)); count-gated so the jobdef does not
  # exist -- and therefore cannot fail at container START -- until the ARN is wired.
  type        = string
  description = "Secrets Manager ARN (name-based) for the Databento key mounted as DATABENTO_API_KEY on the databento fetch job. Empty = that fetch jobdef is not created (user-gated secret)."
  default     = ""
}
