# ---------------------------------------------------------------------------
# A-W2 -- ONE parameterized thin-contract silver state machine (Standard).
# Everything family-specific arrives via the per-family execution INPUT; this
# module hardcodes NO family, jobdef, queue, table, or command.
# ---------------------------------------------------------------------------

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
  description = "AWS region (used to build the .sync managed-rule ARN)."
  default     = "us-east-1"
}

variable "pass_role_arns" {
  type        = list(string)
  description = <<-EOT
    Role ARNs the states execution role may iam:PassRole -- the four thin-contract
    roles: batch-job-role, batch-execution-role, silver-publisher, silver-validator
    (plan A-W2 step 1). Batch/Glue bake the role in the jobdef/job, but PassRole is
    granted for jobdef (re)registration + defensive parity with the plan enumeration.
  EOT
  default     = []
}

variable "alerts_topic_arn" {
  type        = string
  description = "Shared leviathan-dev-alerts SNS topic ARN. The [FailNotify] state publishes here (plan state shape line 91)."
}

variable "silver_pipeline_topic_arn" {
  type        = string
  description = <<-EOT
    The module.silver_observability silver-pipeline SNS topic ARN, granted on the
    exec role's sns:Publish (Section 5 A-W2). Passed as a CONSTRUCTED string (not a
    module.silver_observability output) to break the step_functions<->silver_observability
    dependency cycle (silver_observability's A-W5 orchestration alarms depend on this
    machine's ARN). IAM policies do not require the referenced ARN to exist at plan time.
  EOT
}

variable "map_max_concurrency" {
  type        = number
  description = "MaxConcurrency for the Fetch/Bronze/Silver/Promote Map states (weather silver is 4-wide)."
  default     = 4
}

variable "log_retention_days" {
  type        = number
  description = "Retention for the SFN vended-log group."
  default     = 90
}
