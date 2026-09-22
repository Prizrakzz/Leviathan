# ===========================================================================================
# THE NIGHTLY pg MIRROR LOAD -- census 2026-09-22 blocker B1, permanent fix P1.
#
# WHAT IS WRONG TODAY, MEASURED. `leviathan-dev-serving:133` runs with
# GRAPHRAG_NUMBERS_BACKEND=pg, so EVERY served number in the estate comes out of the RDS
# mirror. That mirror was last loaded in full on 2026-09-10 ("DONE: 16964478 rows", job
# bb79a6e8, 13:22:02..13:27:57 -- under six minutes), and the only load since was a single
# table on 2026-09-17 ("DONE: 117 rows across silver_mpob"). Nineteen of the thirty-nine
# mirrored tables have canonical writes AFTER that full load. And NOTHING SCHEDULES IT:
# `scheduler:ListSchedules` returns 30 schedules and not one of them names the loader, on its
# target ARN or anywhere in its input.
#
# The engine does not lie about this -- the forced-asof guard stamps the OLD vintage honestly
# -- which is precisely why it is the census's largest single finding: a September question
# gets an August answer with an August knowledge date, and a reader grading on merit reads
# that as a stale ENGINE rather than as a stale MIRROR.
#
# WHY THIS IS THE PERMANENT FIX AND NOT A HAND FIRE. The recurrence it prevents is "the serve
# path is as fresh as the last time somebody remembered", which is the state the estate has
# been in since the pg flip. A hand load moves the tip once and freezes in the same place the
# next day; this removes the hand step entirely. (The stronger end-state -- a pg-load phase
# after each DAG's promote -- is the same change one level deeper, and it needs the DAG
# generator, which this file deliberately does not touch.)
#
# ITS VERIFICATION, and it is machine-read rather than remembered: the 23:45Z fire is observed
# to SUCCEED, and then `jobs/utils/numbers_parity.py`'s NEW tip leg -- one MAX(knowledge axis)
# per table, run on Athena AND on pg and diffed -- goes green. That leg is what makes this
# schedule honest end to end, and it closes the one hole this file cannot close by itself:
# until the registrar below runs, the LIVE revision of the target jobdef carries the
# placeholder command `['-c', "print('override me')"]`, so a fire against it would SUCCEED,
# exit 0, and load NOTHING. A green fire that did nothing is the ICCO/MPOC class. The tip leg
# is what catches it, because the tips would not move.
#
# ORDER OF OPERATIONS (and it is not optional):
#   1. ORCHESTRATOR: python jobs/utils/register_pg_numbers_loader_jobdef.py
#      -- registers a NEW revision of leviathan-dev-pg-numbers-loader carrying the REAL command
#      (`jobs/utils/load_pg_numbers.py`, no --tables = the full P1 set), the
#      leviathan-dev-batch-job-role the real loads actually ran under, the EVIDENCE_PG_DSN
#      secret, 4 vCPU / 16 GB, a 7,200 s timeout and a PRE-START-ONLY retry rule.
#   2. OWNER: terraform plan / apply (O6 / O7). The schedule targets the jobdef by its
#      UNVERSIONED name, so it always submits the newest ACTIVE revision -- which is why step 1
#      must come first, and why a later repin needs no terraform at all.
#   3. Watch the first 23:45Z fire end to end (threat model T4), then run the parity gate.
# ===========================================================================================

# --- the scheduler role -------------------------------------------------------------------
# ITS OWN ROLE, SCOPED TO THIS JOBDEF. Scheduler roles are RESOURCE-SCOPED per jobdef in this
# estate: a borrowed role AccessDenies at fire time, and a fire-time AccessDenied is invisible
# until somebody notices the job never existed. Modelled on
# aws_iam_role.freshness_poller_scheduler above -- same trust policy, same two-statement shape.
resource "aws_iam_role" "pg_numbers_loader_scheduler" {
  name = "${var.project_name}-${var.environment}-pg-numbers-loader-scheduler"
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

resource "aws_iam_role_policy" "pg_numbers_loader_scheduler" {
  name = "${var.project_name}-${var.environment}-pg-numbers-loader-scheduler"
  role = aws_iam_role.pg_numbers_loader_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "batch:SubmitJob"
        Resource = [
          # THE ON-DEMAND QUEUE, AND ONLY IT. leviathan-dev-queue-ondemand is the non-Spot
          # queue: a Spot reclamation mid-COPY would leave the loader dead in the middle of a
          # 17M-row rebuild, and scheduled jobs ride the on-demand queue by standing law.
          local.ondemand_job_queue_arn,
          # The jobdef family, wildcarded across revisions so a repin needs no IAM change --
          # the same spelling the freshness poller's grant uses for raw-ingest-runner.
          "arn:aws:batch:${var.aws_region}:*:job-definition/${var.project_name}-${var.environment}-pg-numbers-loader*",
        ]
      },
      {
        # DLQ write as its OWN statement, never folded into the Action list above. Folding it
        # would grant sqs:SendMessage across a job-definition resource set, which is the
        # accidental widening the sweep and poller policies each call out by name.
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.pg_numbers_loader_scheduler_dlq.arn
      },
    ]
  })
}

# --- the DLQ and its alarm ----------------------------------------------------------------
resource "aws_sqs_queue" "pg_numbers_loader_scheduler_dlq" {
  name                      = "${var.project_name}-${var.environment}-pg-numbers-loader-dlq"
  message_retention_seconds = 1209600 # 14 days (SQS max)
  sqs_managed_sse_enabled   = true

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_metric_alarm" "pg_numbers_loader_scheduler_dlq_depth" {
  alarm_name        = "${var.project_name}-${var.environment}-pg-numbers-loader-dlq-depth"
  alarm_description = "The nightly pg MIRROR LOAD was DROPPED before it reached Batch. Serving reads numbers from that mirror (GRAPHRAG_NUMBERS_BACKEND=pg on leviathan-dev-serving), so an unremedied miss means every served number is a day older than canonical while the engine reports the old vintage honestly and reads as stale. Re-fire jobs/submit/submit_batch_load_numbers_pg.py, then run the parity gate and confirm its tip leg is green, then drain."
  namespace         = "AWS/SQS"
  metric_name       = "ApproximateNumberOfMessagesVisible"
  dimensions        = { QueueName = aws_sqs_queue.pg_numbers_loader_scheduler_dlq.name }
  statistic         = "Maximum"
  # Holds ALARM until drained -- the property the 5-minute group TargetErrorCount alarm lacks.
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [module.alerting.topic_arn]

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# --- the schedule -------------------------------------------------------------------------
resource "aws_scheduler_schedule" "pg_numbers_loader" {
  name  = "${var.project_name}-${var.environment}-pg-numbers-load"
  state = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  # 23:45 UTC daily. The slot is chosen, not convenient:
  #   * AFTER the day's ingests and promotes have landed -- the 14:00Z ESR publish, the 22:30Z
  #     CEPEA/free futures chain and the 23:00Z sweep slot all sit earlier, so the load mirrors
  #     canonical AS IT WILL BE READ tomorrow rather than a half-finished evening;
  #   * BEFORE the next morning's first heavy fire (08:00Z weather), leaving more than eight
  #     hours of margin for a red to be seen and re-fired by hand before any gate reads the
  #     mirror;
  #   * off the :00 minute every other cron uses, so the RDS instance the serving pool shares is
  #     not taking a 17M-row rebuild at the same instant as somebody else's job.
  # The expression is UTC. The host renders it 02:45 +03:00 the NEXT day -- do not read the
  # local time as the contract (and never hand-label the weekday; derive it from the date).
  schedule_expression = "cron(45 23 * * ? *)"

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:batch:submitJob"
    role_arn = aws_iam_role.pg_numbers_loader_scheduler.arn

    input = jsonencode({
      JobName  = "pg-numbers-load-scheduled"
      JobQueue = local.ondemand_job_queue_arn
      # THE UNVERSIONED FAMILY NAME, so the schedule always submits the newest ACTIVE revision
      # and a future repin needs no terraform -- and the exact string the role's grant above
      # authorises.
      JobDefinition = "${var.project_name}-${var.environment}-pg-numbers-loader"
      # NO ContainerOverrides, DELIBERATELY. The jobdef carries the real command. An override
      # here would put the command in TWO places, which is the drift class that cost this estate
      # twice on the freshness poller's inline-python block (R7a, 2026-08-04: a hand-transcribed
      # copy called poll_targets() where the file had moved to all_poll_targets(), and one
      # artifact emitted nothing for seven days; D-SG, 2026-08-16: the same block dropped
      # `expected=` and FreshnessLagRatio was never emitted in production at all). Terraform holds
      # no command for this unit, and there is exactly one place to read what it runs:
      # jobs/utils/register_pg_numbers_loader_jobdef.py.
    })

    # EXPLICIT override of the EventBridge Scheduler 185/86400 platform default (the retry-policy
    # trap documented in modules/eventbridge/main.tf).
    #
    # ZERO RETRIES, and this is the same call the pattern-records sweep makes for the same reason:
    # this is a WRITE path. Scheduler delivery is at-least-once, so a retry can submit the job
    # TWICE, and two concurrent full loads would put a second 17M-row DROP+CREATE+COPY on the RDS
    # instance the serving pool shares -- the 2026-07-22 rev-51 pool death is what that looks like
    # when it goes wrong. (The pg side itself would survive it: load_table does DROP+CREATE+COPY
    # inside ONE transaction and pg DDL is transactional, so readers keep the old rows until
    # commit. The objection is contention, not corruption.)
    #
    # The cost of the opposite choice is bounded and DOUBLY ANNOUNCED: a dropped invocation lands
    # in the DLQ below (alarmed, and it holds ALARM until drained), the next morning's parity run
    # goes TIP-STALE and red, and the following night's fire re-loads everything from canonical
    # with no backfill to arrange. A missed night self-heals; a doubled load during the DAG window
    # does not.
    retry_policy {
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 3600
    }

    dead_letter_config {
      arn = aws_sqs_queue.pg_numbers_loader_scheduler_dlq.arn
    }
  }

  depends_on = [
    aws_iam_role.pg_numbers_loader_scheduler,
    aws_iam_role_policy.pg_numbers_loader_scheduler,
    aws_sqs_queue.pg_numbers_loader_scheduler_dlq,
  ]
}
