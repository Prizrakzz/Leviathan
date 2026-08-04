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
    Statement = [
      {
        Effect   = "Allow"
        Action   = "states:StartExecution"
        Resource = var.state_machine_arn
      },
      {
        # The fleet DLQ. EventBridge Scheduler dead-letters using the SCHEDULE's execution role, so
        # the grant belongs on this role. A SEPARATE statement, not a widened Action list, for the
        # reason spelled out on the pattern-records sweep policy: sqs:SendMessage must not ride the
        # state-machine resource and states:StartExecution must not ride the queue.
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.schedule_dlq.arn
      },
    ]
  })
}

# ===========================================================================
# D-PR-12 (the execution-never-started gap) + D-PR-15(iv), 2026-08-04.
#
# THE GAP, MEASURED. D-PR-12 demotes the AWS/States ExecutionsFailed alarm on the premise that the
# in-machine FailNotify is the single notifier. That premise is only safe if a fire that never
# BECOMES an execution is still attributable. Live census 2026-08-04 across all 29 schedules in the
# default group: 25 target sfn:startExecution, every one of them retry 3/86400, and NOT ONE HAD A
# DEAD-LETTER QUEUE. The only coverage was the two GROUP-scoped alarms in silver_observability
# (TargetErrorCount, InvocationDroppedCount, both armed, both ScheduleGroup=default). They are real
# -- history shows them transitioning on every one of the 07-25/26/27 failures -- but AWS/Scheduler
# publishes NO per-schedule dimension (list-metrics: ScheduleGroup is the only one), and a
# Sum-over-5-minutes alarm self-clears within 15 minutes. So the estate could say "a schedule in a
# group of 29 errored, some time last night" and nothing more. That is a notification without an
# incident, and it is exactly what killed the morning brief for 18 days and the sweep for 3 nights.
#
# ONE QUEUE FOR THE FLEET, NOT 25. The dropped event body names its own schedule and carries the
# StartExecution input, so attribution comes from the MESSAGE, not from the queue name -- and 25
# queues would mean 25 depth alarms, i.e. 25 emails for one scheduler-wide outage. That is the
# `freshness-poller`-fires-21-alarms multiplier (D-PR-43) rebuilt by hand. One queue, one alarm.
#
# The depth alarm does NOT self-clear: ApproximateNumberOfMessagesVisible stays > 0 until a human
# drains the queue, which is the durability the TargetErrorCount alarm lacks.
# ===========================================================================
resource "aws_sqs_queue" "schedule_dlq" {
  name                      = "${local.name_prefix}-sfn-schedules-dlq"
  message_retention_seconds = 1209600 # 14 days (SQS max) -- a weekend + a vacation
  sqs_managed_sse_enabled   = true

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_metric_alarm" "schedule_dlq_depth" {
  count = var.alert_topic_arn == "" ? 0 : 1

  alarm_name        = "${local.name_prefix}-sfn-schedules-dlq-depth"
  alarm_description = "A per-family EventBridge schedule DROPPED its fire before an execution ever started (retries exhausted, or a non-retryable StartExecution error such as AccessDenied or a throttle). The message body names the schedule and carries the full StartExecution input -- that body is the ONLY per-schedule attribution that exists, because AWS/Scheduler publishes no per-schedule dimension. A dropped fire does not self-heal: re-fire the family deliberately, then drain."
  namespace         = "AWS/SQS"
  metric_name       = "ApproximateNumberOfMessagesVisible"
  dimensions        = { QueueName = aws_sqs_queue.schedule_dlq.name }
  statistic         = "Maximum"
  period            = 300
  # Holds ALARM until the queue is drained -- unlike the 5-minute group TargetErrorCount alarm, which
  # went OK->ALARM->OK inside 15 minutes on all six 07-25/26/27 failures and read OK by morning.
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alert_topic_arn]

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_scheduler_schedule" "family" {
  for_each = var.schedules

  name  = "${local.name_prefix}-${each.key}"
  state = each.value.enabled ? "ENABLED" : var.schedule_state # A-W7 flips per family (G5.x)

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

    # D-PR-12: after those 3 attempts the fire is GONE. Every family now lands its dropped event in
    # the shared DLQ above, durable for 14 days, naming itself.
    dead_letter_config {
      arn = aws_sqs_queue.schedule_dlq.arn
    }
  }
}
