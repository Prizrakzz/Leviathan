# ===========================================================================
# A-W2 step 2 -- per-family EventBridge Scheduler schedules targeting the SFN
# startExecution universal target, + the scheduler role (states:StartExecution).
#
# RETRY-POLICY TRAP (plan A-W2 step 3 / L3): the live esr + morning-brief
# schedules OMIT retry_policy, so they inherit the EventBridge Scheduler PLATFORM
# DEFAULT of maximum_retry_attempts=185 / maximum_event_age_in_seconds=86400 --
# 185 is NOT a copied value, it is what you re-inherit if you forget the block.
# EVERY schedule here therefore authors an EXPLICIT retry_policy{3, 86400}.
# ===========================================================================

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

resource "aws_iam_role" "sfn_scheduler" {
  name = "${local.name_prefix}-sfn-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_iam_role_policy" "sfn_scheduler_start" {
  name = "${local.name_prefix}-sfn-scheduler-start"
  role = aws_iam_role.sfn_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "states:StartExecution"
      Resource = var.state_machine_arn
    }]
  })
}

resource "aws_scheduler_schedule" "family" {
  for_each = var.schedules

  name  = "${local.name_prefix}-${each.key}"
  state = var.schedule_state # DISABLED by contract; A-W7 flips per wave

  flexible_time_window {
    mode = "OFF"
  }
  schedule_expression = each.value.cron

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:sfn:startExecution"
    role_arn = aws_iam_role.sfn_scheduler.arn
    input    = each.value.input_json # full StartExecution body incl. the ExecutionName idempotency token

    # EXPLICIT override of the 185/86400 platform default (see header).
    retry_policy {
      maximum_retry_attempts       = 3
      maximum_event_age_in_seconds = 86400
    }
  }
}
