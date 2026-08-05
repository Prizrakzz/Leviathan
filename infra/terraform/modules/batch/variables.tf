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

variable "pink_sheet_image_digest" {
  # D-PR-22: the sha256 digest of the WORKER image the world_bank_pink_sheet_bronze
  # jobdef runs. Empty (default) keeps the historical "${var.ecr_repository_url}:latest"
  # behaviour, so no other environment changes shape by adopting this module.
  #
  # WHY THIS FAMILY GETS THE PIN FIRST: pink_sheet_monthly is a promote_mode=AUTONOMOUS
  # chain -- its promote leg re-runs pink_sheet_silver_task.py with --publish-mode
  # canonical under a KMS approval, unattended. Its other three legs (fetch, silver,
  # gate) already run digest-pinned jobdefs, so the bronze leg riding a mutable tag was
  # the one place where "which code published this canonical partition?" had no answer
  # after the fact: :latest is re-pointed by every worker push, including pushes that
  # land BETWEEN the schedule firing and the bronze task starting.
  #
  # Re-pin deliberately (read the digest live, verify the sibling jobdefs agree), the
  # same discipline as futures_eod_image_digest. SILVER-F085 (no :latest-only pushes)
  # is what keeps a pinned digest from being untagged and GC'd out from under this.
  type        = string
  description = "sha256 digest of the worker image the world_bank_pink_sheet_bronze jobdef runs, e.g. 'sha256:abc...'. Empty = fall back to the mutable ':latest' tag (historical behaviour)."
  default     = ""

  validation {
    condition     = var.pink_sheet_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.pink_sheet_image_digest))
    error_message = "pink_sheet_image_digest must be empty or a full 'sha256:<64 hex>' digest -- a TAG is not accepted, since a tag is exactly the mutability this pin exists to remove."
  }
}

variable "worker_fleet_image_digest" {
  # D-PR-7 / D-PR-11 PRECONDITION (post-freeze run sheet section 8, "Latent
  # MUST-NOT-APPLY register"). The sha256 digest of the WORKER image the ten
  # jobdef families listed at local.worker_fleet_image actually run TODAY.
  #
  # Those ten are pinned in terraform state by revision ARN at revisions 1-3, so
  # they emit NO plan line while nothing re-registers them -- which is exactly why
  # they drifted unnoticed. The retry-matrix and timeout work re-registers all ten.
  # Terraform would then mint a new latest-ACTIVE from its own stale definition and
  # revert every one of them from the live digest back to the mutable ":latest",
  # and because the DAGs resolve UNVERSIONED family names to latest-ACTIVE the
  # revert goes live on the very next fire. Adopting the live pin BEFORE the
  # re-registering change lands is the same discipline D-PR-22 applied to Pink
  # Sheet and E6 applied to futures-eod-silver.
  #
  # Re-pin deliberately: read the live digest, confirm all ten agree, then move
  # this default. `python scripts/ops/check_ecr_pinned_digests.py` is the auditor
  # that catches a pin whose manifest has been evicted.
  type        = string
  description = "sha256 digest of the worker image the ten weather/ingest jobdef families run, e.g. 'sha256:abc...'. Empty = fall back to the mutable ':latest' tag (historical behaviour)."
  default     = ""

  validation {
    condition     = var.worker_fleet_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.worker_fleet_image_digest))
    error_message = "worker_fleet_image_digest must be empty or a full 'sha256:<64 hex>' digest -- a TAG is not accepted, since a mutable tag is exactly the revert this pin exists to prevent."
  }
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

variable "futures_eod_silver_image_digest" {
  # THE SILVER LEG'S OWN PIN. Empty (default) = it rides var.futures_eod_image_digest
  # with the two fetch jobdefs, which is the original one-pin-for-the-family shape.
  #
  # It exists because the three jobdefs are NOT always repinned together. Measured
  # 2026-08-04: the two fetch jobdefs were legitimately on 5f0f2aac (tag
  # 20260731T130318 -- the databento incremental-window clamp), while the LIVE
  # futures-eod-silver rev 3 had been moved forward out of band to ea0f9d18 (tag
  # 20260801T131152). With one shared variable, terraform could not describe that
  # reality: any apply would have re-registered the silver jobdef from the fetch
  # digest, minting a new LATEST-ACTIVE revision one image vintage BEHIND live -- and
  # because the DAG resolves the unversioned family name to latest-ACTIVE, that is a
  # silent rollback of the publishing leg, not of a fetch.
  #
  # Family gating is unchanged: futures_eod_image_digest = "" still count-gates all
  # three jobdefs out of existence, whatever this holds.
  type        = string
  description = "sha256 digest override for the futures_eod SILVER jobdef only (the two fetch jobdefs keep futures_eod_image_digest). Empty = share the family digest."
  default     = ""

  validation {
    condition     = var.futures_eod_silver_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.futures_eod_silver_image_digest))
    error_message = "futures_eod_silver_image_digest must be empty or a full 'sha256:<64 hex>' digest -- a TAG is not accepted (same silent-missing-dependency rationale as futures_eod_image_digest)."
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

variable "browser_runner_image" {
  # D-PR-24 follow-up (2026-08-05): the browser-runner jobdef was hand-registered (rev 1) and
  # ABSENT from terraform while the armed nightly futures_eod_free schedule runs its euronext
  # MATIF capture on it -- out-of-band infra on a production path with no timeout and no retry
  # strategy. Adopted with the image pinned BY DIGEST ("<repo>@sha256:...") exactly like
  # pattern_records_image: never a tag, never :latest. The default IS the digest rev 1 runs
  # (b445e016..., verified live before adoption); a rebuild moves this default in the same
  # change that pushes the image, or the apply re-pins the old build -- which is the safe
  # failure, not the silent one.
  type        = string
  description = "Digest-pinned browser image ref for the browser-runner jobdef (playwright/Chromium captures). Empty = jobdef not created."
  default     = "668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-browser@sha256:b445e016b5cef2ec6047e57e8a426fd04a8fd41a864bcf904064c6ec1674ffff"
}
