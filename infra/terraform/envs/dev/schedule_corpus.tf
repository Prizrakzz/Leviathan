# ---------------------------------------------------------------------------
# THE CORPUS LANE'S TWO SCHEDULES -- the weekly chunk pass and the monthly fold.
#
# WHY THIS FILE EXISTS. jobs/batch/corpus_ingest_task.py and
# jobs/batch/corpus_fold_task.py were BOTH BUILT, both unit-pinned, and both
# reachable by NOTHING. Measured 2026-09-22: all 30 EventBridge Scheduler
# schedules and all 4 EventBridge rules were listed and NONE targets
# leviathan-dev-evidence-build. The consequence is not abstract -- every one of
# the 52 commodity and 144 driver evidence slices the writer cites carries
# LastModified 2026-08-21, the newest object under graphrag_evidence/chunks/ was
# written 2026-08-21T09:25:37Z, and on a turn asked today the writer has exactly
# ONE dated document from the last 90 days on the flagship markets. Palm oil,
# palm olein, arabica and robusta stop at 2026-05-20; cocoa at 2026-05-29.
#
# THESE ARE DIRECT batch:submitJob SCHEDULES, not thin-contract SFN executions,
# for the same reason leviathan-dev-timeline-rebuild is: there is no family, no
# gate table and no promote leg here. The shape below is timeline_rebuild's,
# resource for resource -- scoped scheduler role, own DLQ, DLQ-depth alarm,
# retry_policy, flexible_time_window OFF -- because that unit is the estate's
# proven pattern for "a Batch job on a clock".
#
# NOTHING IN THIS FILE IS GENERATOR-OWNED. dag_schedules.auto.tfvars.json is
# rendered by scripts/silver/gen_dag_schedules_tfvars.py from the DAG
# descriptors and must never be hand-edited; the corpus lane has no descriptor,
# so its schedules are hand-authored HCL and live here, apart, where that is
# visible.
#
# THE JOB DEFINITION IS NOT TERRAFORM-MANAGED. leviathan-dev-evidence-build is
# registered by jobs/utils/register_evidence_jobdef.py (rev 136 on embedder
# digest 69288b99 = tag 20260916-seams-serving, 16 vCPU / 122,880 MB, secrets
# ANTHROPIC_API_KEY + EVIDENCE_PG_DSN + COHERE_API_KEY, EVIDENCE_S3 baked to
# s3://leviathan-dev-shahem-001/graphrag_evidence). Both ARN forms are granted
# below and the schedules name it UNVERSIONED so a repin is picked up at the
# next fire with no terraform change.
# ---------------------------------------------------------------------------

locals {
  corpus_job_definition_name = "${var.project_name}-${var.environment}-evidence-build"

  corpus_job_definition_arns = [
    # BOTH ARN FORMS, the estate's standing lesson: SubmitJob with an
    # unversioned name is authorized by the BARE job-definition ARN, and the
    # revision-qualified form is what appears in the event once Batch resolves
    # it. Granting one and not the other is an AccessDenied at fire time.
    "arn:aws:batch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job-definition/${local.corpus_job_definition_name}",
    "arn:aws:batch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job-definition/${local.corpus_job_definition_name}:*",
  ]

  # ---- THE TWO FROZEN COMMANDS -------------------------------------------
  # A schedule's Input is frozen at apply time: EventBridge stores it verbatim
  # and nothing runtime-valued is expressible in it, which is exactly why both
  # wrappers exist and why every runtime decision lives INSIDE them. These two
  # lists are the commands their own docstrings prescribe, and
  # tests/unit/test_corpus_schedule.py reads them back OUT of this file and
  # parses them with the wrappers' own argparse, so an edit here that the
  # wrapper could not accept fails a deck instead of a 04:00Z fire.

  # Caps: --max-docs 200 and --max-usd 5 bound the HAIKU tokens; the fire's
  # dominant cost is Fargate wall-clock on a jobdef whose own timeout is None,
  # and THAT is bounded by --poll-budget-seconds 5400 (90 min = $1.77 at the
  # baked 16 vCPU / 122,880 MB) plus the AttemptDurationSeconds below.
  corpus_chunk_command = [
    "jobs/batch/corpus_ingest_task.py",
    "--stage", "chunk",
    "--max-docs", "200",
    "--max-usd", "5",
    "--poll-budget-seconds", "5400",
  ]

  # --i-know-this-is-live IS LOAD-BEARING AND IS NOT A LOOSENING. Measured at
  # HEAD: corpus_fold_task.main runs GUARD 1 (assert_not_live_rebuild) against
  # the jobdef's own baked EVIDENCE_S3, and outside a dry run it RE-RAISES. The
  # fold's declared prefix IS that baked prefix -- the fold exists to rebuild
  # the live store -- so without this flag the scheduled fold would exit nonzero
  # on its first fire and on every fire after it, forever. The guards that
  # actually protect the store are untouched and all three still bind: the
  # pre-rebuild backup to graphrag_evidence/_backup_pre_corpuslane_<YYYYMMDD>/
  # is taken FIRST and VERIFIED BY OBJECT COUNT (a partial copy refuses the
  # fold), --no-backup together with --i-know-this-is-live is refused outright,
  # there is NO --allow-churn flag on this task at all so the write guard's
  # refusal is terminal, and --census-baseline is mandatory because without an
  # explicit baseline the e1_census --diff gate resolves nothing and PASSES
  # SILENTLY. The pg legs (--with-pg-load / --with-pg-swap) are deliberately
  # ABSENT: R3 stays the operator's for its first three cycles, so a fold moves
  # S3 and the served pg mirror does not move until a human runs the blue-green
  # load and swap. That is the design's intent and it is stated here so nobody
  # reads a green fold as a moved answer.
  #
  # --census-baseline NAMES A KEY THE FOLD ITSELF ROLLS, AND THAT IS THE ONLY
  # REASON THIS FROZEN STRING IS SAFE. A Scheduler Input is frozen at apply
  # time, so without a roll every monthly fold forever diffs against ONE object
  # (written 2026-08-02T00:36:09Z) that nothing in the account refreshes:
  # `e1_census --diff` is read-only and never calls write(), and no schedule
  # runs a plain census. The gate's teeth are population_drops at a 10% floor
  # measured against THE BASELINE'S value, and this lane exists to make the
  # store grow -- so a slice that doubles could later lose half of everything
  # ingested since August, still sit above the August number, and the fold
  # would exit GREEN. Since 2026-09-22 `corpus_fold_task.chain_steps` ends with
  # a plain `e1_census` WRITE that runs only after the lint, the rebuild and the
  # gate all returned 0 (run_chain stops at the first nonzero: NO ROLL ON RED),
  # write() archives the prior copy to eval/e1_census_<UTC>.json before
  # overwriting, GUARD 4 refuses a LIVE fold whose declared baseline is not the
  # key it rolls, and a post-condition HEAD turns a green chain RED if the
  # object did not move. The URI below must therefore stay EXACTLY
  # <the jobdef's baked EVIDENCE_S3>/eval/e1_census.json -- editing it to any
  # other key re-opens the frozen-snapshot defect and the fold will refuse at
  # its first fire rather than pretend.
  #
  # THE FOLD IS ALSO INSTRUMENTED NOW: every fire writes
  # graphrag_evidence/fold/last_run.json and PUTs CorpusFoldRuns /
  # CorpusFoldSlicesWritten / CorpusFoldFailures to Leviathan/Silver
  # (Family=graphrag_evidence). The two alarms over them belong to lane 7's
  # generator and are NOT declared here; the spec, its calibration (35 days for
  # a MONTHLY cadence, never 10) and the apply ORDER (image + repin + one
  # emitting fire BEFORE any breaching alarm) are in HANDOFF_L5_text_corpus.md.
  corpus_fold_command = [
    "jobs/batch/corpus_fold_task.py",
    "--stage", "fold",
    "--evidence-s3", "s3://leviathan-dev-shahem-001/graphrag_evidence",
    "--i-know-this-is-live",
    "--census-baseline", "s3://leviathan-dev-shahem-001/graphrag_evidence/eval/e1_census.json",
  ]

  corpus_chunk_schedule_role_name = "${var.project_name}-${var.environment}-corpus-chunk-scheduler"
  corpus_chunk_schedule_role_arn  = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.corpus_chunk_schedule_role_name}"
  corpus_chunk_dlq_name           = "${var.project_name}-${var.environment}-corpus-chunk-dlq"
  corpus_chunk_dlq_arn            = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${local.corpus_chunk_dlq_name}"

  corpus_fold_schedule_role_name = "${var.project_name}-${var.environment}-corpus-fold-scheduler"
  corpus_fold_schedule_role_arn  = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.corpus_fold_schedule_role_name}"
  corpus_fold_dlq_name           = "${var.project_name}-${var.environment}-corpus-fold-dlq"
  corpus_fold_dlq_arn            = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${local.corpus_fold_dlq_name}"
}

# ---------------------------------------------------------------------------
# THE WEEKLY CHUNK PASS
# ---------------------------------------------------------------------------

resource "aws_iam_role" "corpus_chunk_scheduler" {
  name = local.corpus_chunk_schedule_role_name
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

# ONE ROLE PER SCHEDULE, never a borrowed one: a scheduler role's SubmitJob
# grant is RESOURCE-SCOPED to the job definitions named in it, and the estate
# has already paid for a borrowed role once -- it fails at FIRE time, not at
# apply time, so the schedule looks armed and the job never exists.
resource "aws_iam_role_policy" "corpus_chunk_scheduler" {
  name = "${var.project_name}-${var.environment}-corpus-chunk-scheduler-submit"
  role = aws_iam_role.corpus_chunk_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "batch:SubmitJob"
        Resource = concat([local.ondemand_job_queue_arn], local.corpus_job_definition_arns)
      },
      {
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = local.corpus_chunk_dlq_arn
      },
    ]
  })
}

resource "aws_sqs_queue" "corpus_chunk_dlq" {
  name                      = local.corpus_chunk_dlq_name
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_metric_alarm" "corpus_chunk_dlq_depth" {
  alarm_name          = "${var.project_name}-${var.environment}-corpus-chunk-dlq-depth"
  alarm_description   = "The weekly corpus chunk pass was DROPPED before it reached Batch. Nothing new was chunked this week, so next month's fold will re-derive the same store and the writer's newest citable document does not move. Read the dead-lettered SubmitJob input, fix, re-fire by hand, then drain."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = local.corpus_chunk_dlq_name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [module.alerting.topic_arn]

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_scheduler_schedule" "corpus_chunk" {
  name = "${var.project_name}-${var.environment}-corpus-chunk"

  state = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  # 04:00 UTC Sunday, NOT the 03:00 the design sketch named.
  # leviathan-dev-timeline-rebuild already holds cron(0 3 ? * SUN *) and is
  # ENABLED; putting a 16 vCPU / 120 GB Fargate job on the same queue at the
  # same minute makes the chunk pass wait for capacity while its own 5400 s
  # poll budget is already running. One hour later is clear of it, clear of the
  # 23:00 daily sweep and the 05:30 Monday audit, and lands 8.5 h before the
  # 12:30Z freshness poller, so the week's first reading measures a store this
  # fire has already touched.
  schedule_expression = "cron(0 4 ? * SUN *)"

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:batch:submitJob"
    role_arn = local.corpus_chunk_schedule_role_arn

    input = jsonencode({
      JobName       = "corpus-chunk"
      JobQueue      = local.ondemand_job_queue_arn
      JobDefinition = local.corpus_job_definition_name
      ContainerOverrides = {
        Command = local.corpus_chunk_command
      }
      # THE MONEY FENCE OF LAST RESORT. The jobdef's own timeout is None and
      # `retrieve` polls in an unbounded while-loop, so a wedged Anthropic batch
      # against the 24 h Batch SLA is a $28.35 bill for ONE fire at the baked
      # $1.1812/h. The wrapper's --poll-budget-seconds 5400 is the real fence
      # (it parks the batch id in the ledger and the NEXT week's fire drains it
      # before submitting anything new); this is the fence for the case where
      # the wrapper itself is the thing that is stuck. 9000 s = 2.5 h = $2.95.
      Timeout = { AttemptDurationSeconds = 9000 }
    })

    # maximum_retry_attempts = 0. This fire SUBMITS A BILLED ANTHROPIC BATCH,
    # and a delivery retry is a second submission whose id the first fire's
    # ledger has already claimed. Every failure is terminal on the first try,
    # which is exactly why the DLQ is not optional.
    retry_policy {
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 3600
    }

    dead_letter_config {
      arn = local.corpus_chunk_dlq_arn
    }
  }

  depends_on = [
    aws_iam_role.corpus_chunk_scheduler,
    aws_iam_role_policy.corpus_chunk_scheduler,
    aws_sqs_queue.corpus_chunk_dlq,
  ]
}

# ---------------------------------------------------------------------------
# THE MONTHLY FOLD
# ---------------------------------------------------------------------------

resource "aws_iam_role" "corpus_fold_scheduler" {
  name = local.corpus_fold_schedule_role_name
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

resource "aws_iam_role_policy" "corpus_fold_scheduler" {
  name = "${var.project_name}-${var.environment}-corpus-fold-scheduler-submit"
  role = aws_iam_role.corpus_fold_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "batch:SubmitJob"
        Resource = concat([local.ondemand_job_queue_arn], local.corpus_job_definition_arns)
      },
      {
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = local.corpus_fold_dlq_arn
      },
    ]
  })
}

resource "aws_sqs_queue" "corpus_fold_dlq" {
  name                      = local.corpus_fold_dlq_name
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_metric_alarm" "corpus_fold_dlq_depth" {
  alarm_name          = "${var.project_name}-${var.environment}-corpus-fold-dlq-depth"
  alarm_description   = "The monthly corpus fold was DROPPED before it reached Batch. The 52 commodity and 144 driver slices were NOT re-derived this month, so everything the weekly chunk pass ingested since the last fold is in chunks/ and in no slice the writer can read. Read the dead-lettered SubmitJob input, fix, re-fire by hand, then drain."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = local.corpus_fold_dlq_name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [module.alerting.topic_arn]

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_scheduler_schedule" "corpus_fold" {
  name = "${var.project_name}-${var.environment}-corpus-fold"

  state = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  # THE 22nd AT 08:00 UTC, and the date is derived, not chosen.
  #
  # The design sketch said "the 2nd of the month, after the WASDE and WAP text
  # phases have run". Those two clauses contradict each other and the second one
  # is the real constraint: wasde_monthly fires cron(0 18 8-13 * ? *) and wap
  # fires cron(0 18 12-14 * ? *), so the month's text does not exist until the
  # 14th at 18:00Z at the earliest-possible-latest. A fold on the 2nd would
  # therefore always fold the PREVIOUS month's WASDE and the served corpus would
  # sit between 21 and 51 days behind its own source against the lane's declared
  # 35-day CorpusServedLagDays ceiling.
  #
  # Text must also be CHUNKED before a fold can see it, and chunking is the
  # Sunday pass above. Worst case the 14th is a Sunday, whose 04:00Z pass runs
  # 14 hours BEFORE that day's 18:00Z WAP text, so the month's text is first
  # chunked on the 21st. The 22nd is the first date that is after the month's
  # chunk pass in every calendar.
  #
  # 08:00Z rather than 04:00Z for the once-in-seven-months case where the 22nd
  # IS a Sunday: the fold READS chunks/ while the chunk pass WRITES it, and a
  # slice built from a half-written cache is a silent under-count. The chunk
  # pass cannot outlive 04:00Z + 5400 s of poll + retrieve, so 08:00Z clears it
  # with better than two hours of slack.
  schedule_expression = "cron(0 8 22 * ? *)"

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:batch:submitJob"
    role_arn = local.corpus_fold_schedule_role_arn

    input = jsonencode({
      JobName       = "corpus-fold"
      JobQueue      = local.ondemand_job_queue_arn
      JobDefinition = local.corpus_job_definition_name
      ContainerOverrides = {
        Command = local.corpus_fold_command
      }
      # The 2026-08-21 live rebuild ran 16:54:25Z -> 21:23:19Z = 4 h 29 m. 8 h
      # is that with margin for a grown corpus and is a hard stop on a fold that
      # wedges: 28,800 s = $9.45 at the baked rate, against an unbounded bill on
      # a jobdef whose own timeout is None.
      Timeout = { AttemptDurationSeconds = 28800 }
    })

    # maximum_retry_attempts = 0, and here it matters more than anywhere else in
    # the estate: this job REWRITES all 196 slice objects in place. A delivery
    # retry is a second rebuild racing the first over the same keys.
    retry_policy {
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 3600
    }

    dead_letter_config {
      arn = local.corpus_fold_dlq_arn
    }
  }

  depends_on = [
    aws_iam_role.corpus_fold_scheduler,
    aws_iam_role_policy.corpus_fold_scheduler,
    aws_sqs_queue.corpus_fold_dlq,
  ]
}

# ---------------------------------------------------------------------------
# THE ONE ALARM THAT CAN BE GREEN TODAY -- schedule LIVENESS on the corpus
# family's own metric stream.
#
# The two DLQ alarms above catch a fire Scheduler dropped. They cannot catch a
# fire that reached Batch and then did nothing, and that is the failure this
# lane actually has to fear: before 2026-09-22 the graphrag_evidence freshness
# family read 1.395 d GREEN with a 41-day-stale corpus, because its ONE
# registered member is the weekly TIMELINE rebuild's heartbeat and not the store
# at all.
#
# jobs/batch/corpus_ingest_task.py now PUTs the four family-rolled datums at the
# same commit point as coverage/ledger.json, on EVERY outcome that reaches a
# ledger -- the quiet ones (NOTHING_TO_DO, NO_CANDIDATES, ALL_CACHED) included.
# So a datapoint means "a fire ran and recorded what it found" and no datapoint
# means "no fire recorded anything".
#
# WHY THE FOUR CONTRACT CEILINGS ARE NOT ARMED HERE. CorpusChunkLagDaysMax <= 7,
# CorpusFetchLagDaysMax <= 7 and CorpusCoverageBreachCount == 0 are MAXIMA and a
# MINIMUM over every scored source, and raw/production/source=usda_gain_* has
# not been written since 2026-05-21 because nothing schedules the GAIN fetch and
# that fetch is gated on the owner's curl_cffi ruling for fas.usda.gov. All
# three would therefore be RED on the day they were applied and would stay red
# for reasons no operator on this pager can act on -- which is precisely the
# permanently-red-on-purpose class the alarm-hygiene fix exists to REMOVE, not
# to add to. They are held, with a named prerequisite, and the numbers are in
# the ledger on S3 and on the CloudWatch stream where a human can read them.
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "corpus_lane_liveness" {
  alarm_name        = "${var.project_name}-${var.environment}-corpus-lane-liveness"
  alarm_description = "The corpus lane has not reported in more than 10 DAYS: the newest coverage/ledger.json under the evidence store is older than one missed weekly chunk pass. The evidence store the writer cites is frozen wherever the last successful fold left it and NOTHING else in the estate measures it -- the graphrag_evidence freshness family points at the timeline rebuild's heartbeat, not at the slices. Emitted DAILY by jobs/observability/freshness_poller_task.py (CorpusChunkAgeDays, dim Family) as the age of graphrag_evidence/coverage/ledger.json; see leviathan.silver.freshness.LEDGER_GAUGES for the declaration and the basis. Check the corpus-chunk schedule, then /aws/batch/leviathan-dev for the evidence-build stream."
  namespace         = "Leviathan/Silver"
  metric_name       = "CorpusChunkAgeDays"
  dimensions        = { Family = "graphrag_evidence" }

  # ROUND 3, 2026-09-22 -- RE-SHAPED, BECAUSE THE ROUND-2 SHAPE COULD NOT BE CREATED.
  #
  # This alarm asked "did a fire report in the last 10 days?" as SampleCount over TEN DAILY
  # PERIODS. PutMetricAlarm refuses it: botocore's own CloudWatch service model says "An alarm's
  # total current evaluation period can be no longer than seven days, so Period multiplied by
  # EvaluationPeriods can't be more than 604,800 seconds", and 86,400 x 10 = 864,000 s. The
  # resource sat inside a 52-add plan handed to the owner, so `terraform apply` would have failed
  # on it -- and the whole apply with it. Corroborated against the live account the same day: of
  # 75 metric alarms the MAXIMUM Period x EvaluationPeriods is 86,400, because nothing longer can
  # exist.
  #
  # The QUESTION and the 10 are unchanged. The 10 is now spent as TEN DAYS OF AGE on a gauge the
  # DAILY freshness poller emits from this lane's own ledger, evaluated ONCE: 86,400 x 1 = 86,400 s,
  # inside the bound by a factor of seven. Calibration is the one this alarm already carried -- a
  # healthy weekly cadence leaves at most 6 consecutive quiet days, so 10 days of age is ONE missed
  # fire and can never be a healthy week -- and it no longer depends on daily period boundaries, so
  # a fire that slips a few hours across a UTC midnight can no longer read as a missed week.
  #
  # WHY THE POLLER AND NOT THIS LANE'S OWN METRIC. A job can only emit while it runs, so "it did
  # not run" is the one datapoint a dead chunk pass cannot publish. A daily gauge inverts that: the
  # reporter is alive every day and the NUMBER carries the silence. It is also why the age is read
  # from coverage/ledger.json and NOT from the newest object under chunks/ -- those are written
  # only when a pass finds NEW work, so their mtime answers "when did the corpus last GROW", never
  # "when did the pass last RUN".
  statistic           = "Maximum"
  period              = 86400
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 10

  # breaching, and on a DAILY gauge it now means exactly one thing: the poller published no age at
  # all -- it did not run, or it could not read the ledger prefix. Silence is a blindness, never a
  # quiet week.
  #
  # THE APPLY GATE, unchanged from the one this lane declared for its own metrics and MEASURED
  # 2026-09-22: `aws cloudwatch list-metrics --namespace Leviathan/Silver` returns eleven names and
  # CorpusChunkAgeDays is not among them, because graphrag_evidence/coverage/ lists EMPTY -- the
  # chunk pass's ledger ships in an image whose pin predates it. Created against a stream that has
  # never published, a breaching alarm is RED on the apply that creates it. ORDER: commit -> image
  # build + repin (both the evidence-build image that writes the ledger and the worker image the
  # freshness poller runs from) -> one chunk fire -> one poller cycle -> list-metrics shows the
  # name -> THEN apply this resource.
  treat_missing_data = "breaching"
  alarm_actions      = [module.alerting.topic_arn]

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}
