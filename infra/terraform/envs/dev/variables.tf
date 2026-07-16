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
  default     = "latest"
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
