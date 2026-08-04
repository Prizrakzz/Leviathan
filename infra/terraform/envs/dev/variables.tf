variable "aws_region" {
  type        = string
  description = "AWS region."
  default     = "us-east-1"
}

variable "project_name" {
  type        = string
  description = "Project name."
  default     = "leviathan"
}

variable "environment" {
  type        = string
  description = "Environment name."
  default     = "dev"
}

variable "bucket_name" {
  type        = string
  description = "Globally unique S3 bucket name."
}

variable "batch_max_vcpus" {
  type        = number
  description = "Maximum vCPUs for the Batch Fargate compute environment."
  default     = 16
}

variable "batch_subnet_ids" {
  type        = list(string)
  description = "Subnet IDs for Fargate tasks (default VPC public subnets)."
}

variable "batch_security_group_ids" {
  type        = list(string)
  description = "Security group IDs for Fargate tasks."
}

variable "mlflow_ami_id" {
  type        = string
  description = "Pinned AMI for the adopted dev MLflow/Airflow EC2 instance."
  default     = "ami-0521cb2d60cfbb1a6"
}

variable "mlflow_root_volume_size_gib" {
  type        = number
  description = "Current root volume size for the adopted MLflow/Airflow host."
  default     = 10
}

variable "budget_alert_email" {
  type        = string
  description = "Email address for monthly cost budget alerts. Leave empty to disable email notifications."
  default     = ""
}

# --- Phase 4: GraphRAG serving (ECS Fargate + ALB) --------------------------

variable "serving_admin_cidrs" {
  type        = list(string)
  description = <<-EOT
    CIDRs allowed inbound to the serving ALB. Stage 1 (private validation) MUST lock this to
    your IP, e.g. ["203.0.113.4/32"] — supply at apply time (-var or tfvars). Stage 4 opens it
    to 0.0.0.0/0 once Cognito + HTTPS front it. No default: an unset value is a mistake here.
  EOT
}

variable "serving_image_tag" {
  type        = string
  description = "Tag of the leviathan-dev-leviathan-embedder serving image the task runs."
  # PINNED 2026-07-30 (drift reconciliation), was "latest". The running service is on digest
  # sha256:00fcd043... = tag 20260725rev72, while :latest had moved on to sha256:6717f599...
  # (tag 20260728d785af30). A default of "latest" therefore meant any apply touching the task
  # definition would have silently DEPLOYED A DIFFERENT, UNVALIDATED IMAGE. A serving image is
  # promoted deliberately, so the default now names the promoted build; bump it when you promote.
  # DEPLOYED 2026-07-31: the W3 flip build (commit d5aa7353 + the D7 pg mirror). Previous pin was
  # 20260725rev72 = digest 00fcd043, which predates the whitelist flip -- serving could not answer a
  # delivery-month or curve ask on that image no matter what the config said.
  default     = "20260731w3flip"
}

# Stage 2: the ACM wildcard cert (leviathanconvexity.com + *) created in the console. us-east-1.
variable "serving_certificate_arn" {
  type        = string
  description = "ACM cert ARN for the ALB HTTPS:443 listener + CloudFront (wildcard covers apex/www/api/auth)."
  default     = "arn:aws:acm:us-east-1:668891723125:certificate/650c1f63-a62c-4ceb-a197-010cd1305635"
}

variable "public_domain" {
  type        = string
  description = "The public apex domain (Route53 zone Z01445327V6FBPHBK9AX, console-created)."
  default     = "leviathanconvexity.com"
}

variable "public_zone_id" {
  type        = string
  description = "Route53 hosted zone id for public_domain (console-created; referenced, not managed)."
  default     = "Z01445327V6FBPHBK9AX"
}

# Stage 4: Google federated sign-in via Cognito. Secrets live ONLY in the gitignored terraform.tfvars
# (state is also gitignored) — never in a committed file. Empty defaults so Dynamo/IAM can apply before
# these are supplied; the Cognito apply is gated on them being set.
variable "google_oauth_client_id" {
  type        = string
  description = "Google Cloud OAuth 2.0 web client id (set in terraform.tfvars)."
  default     = ""
}

variable "google_oauth_client_secret" {
  type        = string
  description = "Google Cloud OAuth 2.0 web client secret (set in terraform.tfvars)."
  sensitive   = true
  default     = ""
}

variable "cognito_domain_prefix" {
  type        = string
  description = "Cognito hosted-UI domain prefix -> https://<prefix>.auth.<region>.amazoncognito.com."
  default     = "leviathan-terminal"
}


# ---------------------------------------------------------------------------
# SILVER-F082 observability (apply-gated). These three are populated from
# silver_observability.auto.tfvars.json, emitted by:
#     python jobs/observability/silver_alarms.py --emit-tfvars infra/terraform/envs/dev
# Regenerate whenever a silver table is added so the alarm set stays complete.
# ---------------------------------------------------------------------------
variable "silver_metric_namespace" {
  type        = string
  description = "CloudWatch namespace for app-emitted silver pipeline metrics."
  default     = "Leviathan/Silver"
}

variable "silver_batch_families" {
  type        = list(string)
  description = "DAG-catalog family keys with a source Batch DAG (per-family Batch-failed alarms)."
  default     = []
}

variable "silver_freshness_slas" {
  type        = map(number)
  description = "family_key -> interim freshness ceiling (days) for freshness-SLA-breach alarms."
  default     = {}
}

variable "silver_table_freshness_slas" {
  type = map(object({
    family    = string
    threshold = number
    basis     = string
  }))
  description = "table_name -> {family, threshold, basis} for PER-TABLE freshness alarms (the four audit-burned tables). From silver_observability.auto.tfvars.json. Wire into module.silver_observability (see freshness_poller.tf.prepared) to render the per-table alarms."
  default     = {}
}

variable "silver_alert_email" {
  type        = string
  description = "Email for the silver-pipeline SNS subscription placeholder ('' = no subscription)."
  default     = ""
}

variable "dag_schedules" {
  type = map(object({
    cron       = string
    enabled    = bool
    input_json = string
  }))
  default     = {}
  description = "Per-family DAG schedules rendered by gen_sfn_inputs --render-schedule (dag_schedules.auto.tfvars.json)."
}

# --- T2B pattern-records ledger (docs/private/T2B_PATTERN_RECORDS_PLAN.md) ---

variable "pattern_records_image_digest" {
  # The sha256 digest of the CONTENT-CHECKED embedder image that carries the sweep
  # entrypoint (rollout step 3: docker run + inspect.getsource markers -- never trust a
  # tag, the d9b2e10e stale-:latest lesson). Empty (default) count-gates the ENTIRE T2B
  # cloud leg out of existence: no jobdef, no scheduler role, no schedule, no kms:Sign
  # grant. The main loop pins the real digest; keep the value in the "sha256:..." form.
  type        = string
  description = "sha256 digest of the content-checked embedder image for the pattern-records sweep jobdef, e.g. 'sha256:abc...'. Empty = the whole T2B cloud leg is not created."
  default     = ""

  validation {
    condition     = var.pattern_records_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.pattern_records_image_digest))
    error_message = "pattern_records_image_digest must be empty or a full 'sha256:<64 hex>' digest (a TAG is not accepted: the ledger's engine_version stamp and the stale-image guard both depend on the digest)."
  }
}

# --- PRICE_AND_PLAYBOOKS W1a + W2: the two futures_eod chains ---------------

variable "futures_eod_image_digest" {
  # The WORKER image the three futures_eod jobdefs run, pinned BY DIGEST.
  #
  # DEFAULTED IN THE REPO, not left to the gitignored tfvars, for the same reason
  # mlflow_enabled's default lives here: a fresh checkout must reproduce the wiring
  # that is actually live. The value is the 20260729w1c build (worker repo
  # leviathan-dev-leviathan-worker; commit 50a2ec3d), which is the build that carries
  # BOTH pyproject deps this family fails silently without -- `databento` from the
  # [batch] extra (futures_eod_databento.json precondition (d)) and core `xlrd>=2.0`
  # for the JSE / CEPEA-archive .xls readers (futures_eod_free.json precondition (c)).
  # Pinning the digest is what discharges precondition (d): the pin IS the repin.
  #
  # Re-pin whenever the worker image is rebuilt for this family; SILVER-F085
  # (scripts/build_push_worker.ps1 never pushes :latest-only) is what keeps the
  # referenced digest from being untagged and GC'd out from under the jobdefs.
  # Empty count-gates all three jobdefs out of existence.
  type        = string
  description = "sha256 digest of the worker image the futures_eod fetch + silver jobdefs run. Empty = none of the three futures_eod jobdefs are created."
  # 2026-07-31: repinned to tag 20260731T130318, which carries the databento incremental-window
  # clamp. The previous digest (2f3efb7c, tag 20260729w1c) 422'd 15/15 units on every fire --
  # fetch_databento_eod.py overwrote the clamped window with `today + 1`, one day past the vendor's
  # available end, on the only path that submits.
  default     = "sha256:5f0f2aacd23dbcc1dcb05056b6dc9b6d3fd84f0b8720d8a99500085b1e37e4cb"

  validation {
    condition     = var.futures_eod_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.futures_eod_image_digest))
    error_message = "futures_eod_image_digest must be empty or a full 'sha256:<64 hex>' digest (a TAG is not accepted)."
  }
}

variable "futures_eod_silver_image_digest" {
  # THE SILVER LEG ONLY. The two FETCH jobdefs stay on futures_eod_image_digest above.
  #
  # RECONCILED TO LIVE 2026-08-04. leviathan-dev-futures-eod-silver's latest-ACTIVE
  # revision (rev 3) runs tag 20260801T131152, one build NEWER than the 20260731T130318
  # the fetch legs are pinned to; the silver leg was repinned out of band and the fetch
  # legs deliberately were not. Terraform holds the three jobdefs as phantom-creates
  # (absent from state, present in AWS), so with a single shared digest the next apply
  # would have registered a new latest-ACTIVE silver revision carrying the OLDER image
  # -- and the DAG resolves the family name to latest-ACTIVE, so the publishing leg
  # would have rolled back one vintage with nothing in the plan saying so.
  #
  # Empty = share futures_eod_image_digest. Keep this equal to the live latest-ACTIVE
  # image unless a repin is the deliberate point of the change:
  #   aws batch describe-job-definitions --job-definition-name leviathan-dev-futures-eod-silver \
  #     --status ACTIVE --query 'reverse(sort_by(jobDefinitions,&revision))[0].containerProperties.image'
  type        = string
  description = "sha256 digest override for the futures_eod SILVER jobdef only. Empty = share futures_eod_image_digest with the two fetch jobdefs."
  default     = "sha256:ea0f9d1815d6226c25f1bc0ca99f5fc78f5efa8b7512c2d7c7b113c29eec6a30"

  validation {
    condition     = var.futures_eod_silver_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.futures_eod_silver_image_digest))
    error_message = "futures_eod_silver_image_digest must be empty or a full 'sha256:<64 hex>' digest (a TAG is not accepted)."
  }
}

# --- D-PR-22: the pink-sheet bronze leg comes off :latest -------------------

variable "pink_sheet_image_digest" {
  # The WORKER image leviathan-dev-world-bank-pink-sheet-bronze runs, pinned BY DIGEST.
  #
  # pink_sheet_monthly (cron(0 16 4 * ? *)) is a promote_mode=AUTONOMOUS chain: its
  # promote leg re-runs pink_sheet_silver_task.py with --publish-mode canonical under a
  # KMS approval, unattended. Its fetch and silver legs run leviathan-dev-b3-flat-silver
  # and its gate runs leviathan-dev-silver-gate -- BOTH already digest-pinned. The
  # bronze leg's ":latest" was therefore the only mutable hop in a path that writes a
  # canonical partition without a human in the loop, and ":latest" is re-pointed by
  # every worker push -- including a push that lands between the schedule firing and
  # the bronze task pulling.
  #
  # VALUE = what ':latest' resolved to at 2026-08-04T11:40Z: tag 20260804T132111,
  # pushed 2026-08-04T10:21Z. Verified byte-consistent with the rest of the chain --
  # b3-flat-silver rev 24, silver-gate rev 14 and silver-publisher-runner rev 24 all
  # run this exact digest -- so pinning here makes all four legs of the chain one image
  # instead of three-plus-a-coin-flip.
  #
  # Re-pin deliberately after a worker rebuild the pink-sheet path needs:
  #   aws ecr describe-images --repository-name leviathan-dev-leviathan-worker \
  #     --image-ids imageTag=latest --query 'imageDetails[0].imageDigest'
  # Empty = fall back to the mutable ':latest' (historical behaviour).
  type        = string
  description = "sha256 digest of the worker image the world_bank_pink_sheet_bronze jobdef runs. Empty = the mutable ':latest' tag."
  default     = "sha256:e8aa7857a2e1b3b0258fa7258803a60d608a1209cf3b02042220da2094bf4b7f"

  validation {
    condition     = var.pink_sheet_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.pink_sheet_image_digest))
    error_message = "pink_sheet_image_digest must be empty or a full 'sha256:<64 hex>' digest (a TAG is not accepted -- a tag is the mutability this pin removes)."
  }
}

# MLflow tracking server (module.mlflow_fargate). DEFAULT FALSE since 2026-07-26: the server was
# decommissioned for cost (see the module block in main.tf). The default lives HERE, in the repo, rather
# than in the gitignored tfvars -- otherwise a fresh checkout would default it back ON and quietly restart
# the ~$16-18/mo ALB. Set true (or -var mlflow_enabled=true) to bring the whole stack back.
variable "mlflow_enabled" {
  type        = bool
  default     = false
  description = "Create the MLflow Fargate stack (service + ALB + Route53 + Cognito client). Off = decommissioned."
}
