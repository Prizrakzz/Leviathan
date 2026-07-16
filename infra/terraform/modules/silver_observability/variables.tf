variable "project_name" {
  type        = string
  description = "Project name (e.g. leviathan)."
}

variable "environment" {
  type        = string
  description = "Environment name (e.g. dev)."
}

variable "aws_region" {
  type        = string
  description = "AWS region."
  default     = "us-east-1"
}

variable "alert_topic_arn" {
  type        = string
  description = "Shared module.alerting SNS topic ARN (fallback alarm destination). Empty = rely only on the silver-pipeline topic."
  default     = ""
}

variable "silver_alert_email" {
  type        = string
  description = "Email for the silver-pipeline SNS subscription placeholder. Empty (default) = no subscription created; the topic still exists for EventBridge + alarms."
  default     = ""
}

variable "silver_metric_namespace" {
  type        = string
  description = "CloudWatch namespace for the app-emitted silver pipeline metrics. From silver_observability.auto.tfvars.json (jobs/observability/silver_alarms.py)."
  default     = "Leviathan/Silver"
}

variable "silver_batch_families" {
  type        = list(string)
  description = "DAG-catalog family keys that carry a source Batch DAG (per-family Batch-failed alarm). From silver_observability.auto.tfvars.json."
  default     = []
}

variable "silver_freshness_slas" {
  type        = map(number)
  description = "family_key -> interim freshness ceiling (days) for the freshness-SLA-breach alarms. From silver_observability.auto.tfvars.json."
  default     = {}
}

# --- A-W5 step 3: orchestration-plane alarm inputs -------------------------
variable "state_machine_arn" {
  type        = string
  description = <<-EOT
    ARN of the silver thin-contract state machine (module.step_functions). Drives the
    AWS/States ExecutionsFailed/Aborted/TimedOut alarms + the aws.states failure rule,
    all count-gated on this being non-empty so the module still applies before A-W2
    wires the machine in. Empty (default) = no SFN-specific alarms/rule.
  EOT
  default     = ""
}

variable "scheduler_group_name" {
  type        = string
  description = "EventBridge Scheduler group holding the per-family schedules -- the ScheduleGroup dimension for the TargetErrorCount alarm. Default group unless a named group is created."
  default     = "default"
}

variable "batch_queued_age_threshold_seconds" {
  type        = number
  description = "Ceiling (seconds) for the Batch queued-job-age alarm (custom metric BatchQueuedJobAgeSeconds)."
  default     = 3600
}
