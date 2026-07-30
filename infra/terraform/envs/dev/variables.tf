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
  default     = "20260725rev72"
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
  default     = "sha256:2f3efb7caf513541eabbe671b2d2ff7028292459190bf4e093c3d4da0a79a0a7"

  validation {
    condition     = var.futures_eod_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.futures_eod_image_digest))
    error_message = "futures_eod_image_digest must be empty or a full 'sha256:<64 hex>' digest (a TAG is not accepted)."
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
