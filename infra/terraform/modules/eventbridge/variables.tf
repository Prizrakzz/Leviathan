# ---------------------------------------------------------------------------
# A-W2 step 2 -- per-family EventBridge Scheduler -> SFN startExecution.
# Every net-new schedule ships state="DISABLED" (like the two live schedules)
# and carries an EXPLICIT retry_policy (see main.tf for the 185-default trap).
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
  description = "AWS region."
  default     = "us-east-1"
}

variable "alert_topic_arn" {
  type        = string
  description = <<-EOT
    SNS topic that receives the fleet DLQ depth alarm (module.alerting). Empty (default) = the DLQ
    and the dead_letter_config are still created -- the dropped event is still DURABLE and still
    attributable -- but nobody is told, so leave it empty only for a standalone/apply-order run.
  EOT
  default     = ""
}

variable "state_machine_arn" {
  type        = string
  description = "ARN of the silver thin-contract state machine. Grants states:StartExecution to the scheduler role."
}

variable "schedules" {
  type = map(object({
    cron       = string
    input_json = string
    enabled    = optional(bool, false) # A-W7 per-family enable (G5.x gates); false = born DISABLED
  }))
  default     = {}
  description = <<-EOT
    Per-family schedule map: family_key -> { cron, input_json }.

      cron       = the schedule_expression, e.g. "cron(0 18 ? * MON-FRI *)".
      input_json = the FULL aws-sdk:sfn:startExecution request body as a JSON string:
                     {"StateMachineArn":"<arn>",
                      "Input":"<stringified per-family execution payload>",
                      "Name":"<ExecutionName idempotency token>"}
                   ExecutionName idempotency (plan A-W2 step 2: an at-least-once
                   double-fire of the same logical interval is rejected
                   ExecutionAlreadyExists) is baked HERE by the A-W6 generator --
                   this module passes input_json through verbatim.

    Placeholder-EMPTY by default; per-family schedules land in A-W6/A-W7. Every
    entry is created state="DISABLED"; A-W7 flips state per wave [USER GATE].
  EOT
}

variable "schedule_state" {
  type        = string
  description = "State for ALL schedules in this module. DISABLED by contract (A-W7 enables per wave, per family, out of band)."
  default     = "DISABLED"
}
