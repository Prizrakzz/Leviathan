# ===========================================================================
# D-PR-7 / D-PR-37 -- THE PRODUCER RETRY MATRIX, declared ONCE and stamped into
# every job definition below via `dynamic "evaluate_on_exit"`.
#
# WHY A MATRIX AT ALL. Measured 2026-08-04 over 393 Batch jobs on both queues:
# of 67 live jobdef families exactly THREE carried a retryStrategy, and two of
# the three were aimed at the wrong class -- `silver-gate` retried
# CannotPullContainerError (READ AS PERMANENT AT THE TIME: 26/26 samples in 21
# days were digest evictions, and a 3x backoff cannot resurrect a deleted
# manifest -- it only triples the alarm datapoints), and `gain_backfill` (below)
# retried exit 137, i.e. OOM, which is deterministic and needs a RESOURCE change,
# not another attempt.
#
# THE CannotPullContainer READING IS REVERSED AS OF 2026-08-16 (D-SG G1-3) on new
# evidence, and the rule below carries the whole argument. The 2026-08-04 text is
# kept as the record of what was true then, not as a live instruction.
#
# THE 5-OBJECT HARD CAP IS REAL AND IS WHY THIS LIST IS FIVE LONG. Read from the
# live botocore Batch service model (`batch/2016-08-10/service-2.json.gz`,
# `RetryStrategy` shape): "evaluateOnExit: Array of up to 5 objects ...
# **If none of the listed conditions match, then the job is retried.**"
# RegisterJobDefinition REJECTS a sixth entry outright. Two consequences:
#
#   1. The terminal { on_reason = "*", action = "EXIT" } is MANDATORY and spends
#      one of the five. The documented no-match fallback is RETRY, not exit, so
#      dropping the catch-all INVERTS the posture of everything above it. It is
#      also what caps a `attemptDurationSeconds` timeout at ONE attempt --
#      attemptDurationSeconds is PER ATTEMPT, so without the catch-all a hung
#      producer under attempts=3 would hold the 16-vCPU ondemand CE for 3x its
#      timeout, and `leviathan-dev-batch-queued-job-age` watches QUEUE age, not
#      RUN age, so nothing would see it. NEVER TRIM THIS RULE.
#   2. 'Host EC2*' and '*Spot*' are NOT here on purpose. Every schedule is
#      verified on leviathan-dev-queue-ondemand and the standing rule forbids
#      spot, so both are dead weight that would cost two of the five slots.
#
# ResourceInitializationError = RETRY, and the ASM caveat that gates it is
# DISCHARGED FOR THIS MODULE'S BLAST RADIUS BY EVIDENCE, not by assumption. The
# single ResourceInitializationError sample in the estate (modis-fetch, 2026-07-17,
# "unable to retrieve secret from asm: invalid character E ...") is a Secrets
# Manager JSON-parse failure -- deterministic, and it belongs to a jobdef this
# module does not own (modis-fetch is hand-registered, not terraform). The only
# three ASM mounts terraform registers are FAS_API_KEY (usda_esr_fetch),
# EVIDENCE_PG_DSN (pattern_records_sweep) and DATABENTO_API_KEY (databento_fetch),
# and each has SUCCEEDED runs in the current window -- i.e. all three secrets
# provably parse. The caveat therefore remains OPEN only for modis-fetch, which
# is outside this file.
#
# EXIT-1 = EXIT is the load-bearing half of the wave's standard: exit 1 is a
# DECISION (a gate refusal, a floor breach) or a data fault. Re-running it cannot
# change the answer; it can only turn one email into three.
#
# ORDER IS SEMANTIC: AWS evaluates top-down and the FIRST match wins.
# ===========================================================================
locals {
  # attempts is the CEILING, not a promise -- evaluate_on_exit decides. With the
  # matrix below, only ResourceInitializationError and CannotPullContainer ever
  # consume a second attempt.
  producer_retry_attempts = 3

  # Every rule carries all four keys (null where unused) so the list has ONE
  # object type and `dynamic` can address the fields directly.
  producer_retry_rules = [
    # D-SG G1-3 (2026-08-16): RETRY, not EXIT. The exit-pin here was correct when
    # CannotPullContainerError meant PERMANENT digest eviction (26/26 samples in the
    # 21 days to 2026-08-04 were evictions, and a 3x backoff cannot resurrect a
    # deleted manifest). THAT LANDMINE IS DISCHARGED: the ECR cap-100 lifecycle
    # policy plus the weekly leviathan-dev-ecr-pin-audit now hold the pinned digests,
    # and all five in-window CannotPull events (5 scheduled executions + 1 eval,
    # 2026-08-02..08-13) were verified TRANSIENT -- the pinned digest was still
    # present with an unchanged pushedAt after the failure. Cost of being wrong: ONE
    # wasted attempt, after which the pin-audit names the real eviction. Cost of
    # being right: five burned scheduled fires do not happen again. (Class A.)
    { on_exit_code = null, on_reason = null, on_status_reason = "CannotPullContainer*", action = "RETRY" },
    # The one genuinely transient container-start class. (Class B / ENI + ASM init.)
    { on_exit_code = null, on_reason = null, on_status_reason = "ResourceInitializationError*", action = "RETRY" },
    # Deterministic: the job needs more memory, not another attempt. (Class J.)
    #
    # NOTE THE ABSENT LEADING ASTERISK. The ratified matrix wrote this as
    # "*OutOfMemory*", which the API REJECTS -- on_reason/on_status_reason accept
    # "letters, numbers, periods, colons, and white space, and can optionally END
    # with an asterisk". A LEADING wildcard is not a legal glob here (measured:
    # `terraform validate` fails all 40 registrations on it). The anchored form is
    # exact against what AWS actually returns -- live sample, evidence-build rev 32
    # on 2026-08-02: "OutOfMemoryError: container killed due to memory usage".
    # This rule is also fail-SAFE: if the reason text ever changed, the job falls
    # through to the terminal catch-all, which is EXIT anyway.
    { on_exit_code = null, on_reason = "OutOfMemoryError*", on_status_reason = null, action = "EXIT" },
    # A decision or a data fault. (Class D.)
    { on_exit_code = "1", on_reason = null, on_status_reason = null, action = "EXIT" },
    # MANDATORY TERMINAL RULE -- no-match defaults to RETRY. Do not remove.
    { on_exit_code = null, on_reason = "*", on_status_reason = null, action = "EXIT" },
  ]

  # DSG-TAIL F1 -- PROPOSED, THEN CLOSED BY MEASUREMENT THE SAME DAY (2026-08-16). A
  # review lens argued the matrix above leaves a residual: a container that RAN and
  # exited nonzero-but-not-1 with an ABSENT reason would match no rule and fall to
  # Batch's no-match default (RETRY) -- a second pass over a canonical write path on the
  # four self-promote publisher jobdefs. A live probe REFUTED it: job cb151695 on
  # b3-flat-silver (this exact matrix), exit code 2, container reason None, statusReason
  # 'Essential container in task exited' -- terminal after ONE attempt. The terminal
  # on_reason "*" rule catches reason-less exits in practice, so the matrix is already
  # doctrine-complete and a publisher variant would be dead config. Banked for the
  # future: the Batch API ACCEPTS on_exit_code = "*" (probe registration
  # leviathan-dev-f1-probe-throwaway rev 1, accepted then deregistered) -- if a genuine
  # retry-over-write class ever appears, that is the legal widening.

  # --- The weather/ingest worker FLEET pin (post-freeze batch, run sheet section 8) ---
  #
  # Ten jobdef families are held in terraform state at revisions 1-3 on the mutable
  # "${var.ecr_repository_url}:latest" while LIVE latest-ACTIVE sits 3-5 revisions
  # ahead on ONE shared digest. Because state pins them by revision ARN they produce
  # no plan line UNTIL something re-registers them -- and D-PR-7 (retry_strategy) and
  # D-PR-11 (timeouts) re-register every one. Without this pin, the reliability batch
  # would be the thing that silently reverts ten producers to a mutable tag.
  #
  #   chirps-bronze-to-silver, chirps-to-bronze-backfill, conab-xls-bronze,
  #   cpc-soil-bronze-to-silver, cpc-soil-raw-to-bronze, cpc-soil-to-raw,
  #   modis-ndvi-bronze-to-silver, modis-ndvi-raw-to-bronze, nasa-power-backfill,
  #   usda-esr-bronze
  #
  # ONE variable rather than ten: all ten were measured on the IDENTICAL digest
  # (2026-08-04), they were repinned as a fleet by one out-of-band operation, and a
  # ten-way split would add surface with no operational difference today. If a single
  # leg ever needs to diverge, layer a per-jobdef override on top exactly the way
  # var.futures_eod_silver_image_digest does over var.futures_eod_image_digest --
  # without touching the other nine.
  #
  # Empty (default) restores the historical ":latest" behaviour, so no other
  # environment changes shape by adopting this module.
  worker_fleet_image = (
    var.worker_fleet_image_digest == ""
    ? "${var.ecr_repository_url}:latest"
    : "${var.ecr_repository_url}@${var.worker_fleet_image_digest}"
  )
}

resource "aws_batch_compute_environment" "this" {
  compute_environment_name = "${var.project_name}-${var.environment}-fargate"
  type                     = "MANAGED"
  state                    = "ENABLED"

  compute_resources {
    type      = "FARGATE_SPOT"
    max_vcpus = var.max_vcpus

    subnets            = var.subnet_ids
    security_group_ids = var.security_group_ids
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_batch_job_queue" "this" {
  name     = "${var.project_name}-${var.environment}-queue"
  state    = "ENABLED"
  priority = 1

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.this.arn
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_batch_compute_environment" "ondemand" {
  compute_environment_name = "${var.project_name}-${var.environment}-fargate-ondemand"
  type                     = "MANAGED"
  state                    = "ENABLED"

  compute_resources {
    type      = "FARGATE"
    # 16 (was 8): a 16-vCPU evidence rebuild must be placeable, and eval arms shouldn't serialize behind
    # one 8-vCPU slot (2026-07-08 pool-sweep + rebuild-OOM lessons; applied live via
    # update-compute-environment the same day -- this line mirrors that already-live value).
    max_vcpus = min(var.max_vcpus, 16)

    subnets            = var.subnet_ids
    security_group_ids = var.security_group_ids
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_batch_job_queue" "ondemand" {
  name     = "${var.project_name}-${var.environment}-queue-ondemand"
  state    = "ENABLED"
  priority = 1

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.ondemand.arn
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: NASA POWER raw backfill
# Each task handles one (country, region, year) = 12 monthly API calls.
# Parameters are overridden per-task at submission time.
# ---------------------------------------------------------------------------

resource "aws_batch_job_definition" "nasa_power_backfill" {
  name = "${var.project_name}-${var.environment}-nasa-power-backfill"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    commodity  = "cocoa"
    country    = "placeholder_country"
    region     = "placeholder_region"
    start_year = "1981"
    end_year   = "1981"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/ingest/fetch_nasa_power.py",
      "--commodity", "Ref::commodity",
      "--country", "Ref::country",
      "--region", "Ref::region",
      "--start-year", "Ref::start_year",
      "--end-year", "Ref::end_year",
      "--upload",
      "--skip-existing-s3"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.25" },
      { type = "MEMORY", value = "512" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "nasa-power-backfill"
      }
    }
  })

  # D-PR-11: attemptDurationSeconds -- PER ATTEMPT, so the mandatory terminal
  # catch-all in the retry matrix below is what keeps a hung job to ONE attempt.
  timeout {
    attempt_duration_seconds = 3600 # 1 h ceiling; 5 measured runs 312-871 s (2026-07-29..08-04), 4x the max
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts
    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: CHIRPS COG → bronze backfill
# Each task handles one (commodity, year) = 12 months of CHIRPS data.
# Parameters are overridden per-task at submission time.
# ---------------------------------------------------------------------------

resource "aws_batch_job_definition" "chirps_to_bronze_backfill" {
  name = "${var.project_name}-${var.environment}-chirps-to-bronze-backfill"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    commodity  = "corn_cbot"
    year       = "1981"
    bucket     = var.leviathan_bucket
    aws_region = var.aws_region
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/chirps_to_bronze_task.py",
      "--commodity", "Ref::commodity",
      "--year", "Ref::year",
      "--bucket", "Ref::bucket",
      "--aws_region", "Ref::aws_region"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.5" },
      { type = "MEMORY", value = "1024" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "chirps-to-bronze"
      }
    }
  })

  # D-PR-11: attemptDurationSeconds -- PER ATTEMPT, so the mandatory terminal
  # catch-all in the retry matrix below is what keeps a hung job to ONE attempt.
  timeout {
    attempt_duration_seconds = 7200 # 2 h ceiling; 5 measured runs 1349-1397 s, 4x the max is 5588 s so 3600 would be only 2.6x
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts
    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: backfill orchestrator
# Single Fargate task that submits all worker Batch jobs, polls completion,
# then fires Glue raw→bronze and bronze→silver for every commodity.
# One submit-and-forget command — runs for ~36 min, exit code reflects success.
# ---------------------------------------------------------------------------

resource "aws_batch_job_definition" "backfill_orchestrator" {
  name = "${var.project_name}-${var.environment}-backfill-orchestrator"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    start_year  = "1981"
    end_year    = "2024"
    commodities = "all"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/orchestrate/orchestrate_backfill.py",
      "--start-year", "Ref::start_year",
      "--end-year", "Ref::end_year",
      "--commodities", "Ref::commodities"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.5" },
      { type = "MEMORY", value = "1024" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "backfill-orchestrator"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 57600 # 16 h ceiling; actual runtime ~36 min
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: CHIRPS bronze → silver
# One task per commodity.  Reads all bronze Parquet for the commodity,
# applies silver cleaning + melt transform, writes per-partition silver files.
# Skip-existing logic is built into BaseBronzeToSilverJob — safe to re-run.
# ---------------------------------------------------------------------------

resource "aws_batch_job_definition" "chirps_bronze_to_silver" {
  name = "${var.project_name}-${var.environment}-chirps-bronze-to-silver"
  type = "container"

  platform_capabilities = ["FARGATE"]

  # ALIGNMENT TO LIVE rev 6, not a new choice. Live carries a fourth pair
  # (`--force_overwrite Ref::force_overwrite`) that terraform state (rev 1) did
  # not; re-registering from the stale definition would have dropped it. Live
  # declares NO parameters at all, so today its Ref::force_overwrite arrives at
  # the container UNRESOLVED, as the literal string "Ref::force_overwrite" --
  # which base_jobs parses as `(...).lower() == "true"` -> False. Declaring the
  # default explicitly reproduces exactly that effective value while removing the
  # unresolved-token footgun. The SCHEDULED path is unaffected either way:
  # weather_daily's SFN task passes command=["jobs/batch/bronze_to_silver_chirps_task.py"]
  # as a ContainerOverride, which REPLACES the jobdef command.
  parameters = {
    commodity       = "corn_cbot"
    bucket          = var.leviathan_bucket
    aws_region      = var.aws_region
    force_overwrite = "false"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/bronze_to_silver_chirps_task.py",
      "--commodity", "Ref::commodity",
      "--bucket", "Ref::bucket",
      "--aws_region", "Ref::aws_region",
      "--force_overwrite", "Ref::force_overwrite"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "4096" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "chirps-bronze-to-silver"
      }
    }
  })

  # D-PR-11: attemptDurationSeconds -- PER ATTEMPT, so the mandatory terminal
  # catch-all in the retry matrix below is what keeps a hung job to ONE attempt.
  timeout {
    attempt_duration_seconds = 3600 # 1 h ceiling; 5 measured runs 218-318 s, 4x the max
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: SAGIS CEC raw backfill
# 4 tasks run in parallel by jobs/submit/submit_batch_backfill_sagis_cec.py,
# each covering a non-overlapping year range of the ~358-file archive.
# command is overridden per-task via containerOverrides at submit time.
# Sizing: 0.25 vCPU / 512 MB — pure network I/O, no in-memory parsing.
# Timeout: 1 h ceiling; each ~80-120-file chunk completes in ~5-8 min.
# ---------------------------------------------------------------------------

resource "aws_batch_job_definition" "sagis_cec_raw_backfill" {
  name = "${var.project_name}-${var.environment}-sagis-cec-raw-backfill"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/ingest/fetch_sagis_cec.py",
      "--skip-existing-s3"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.25" },
      { type = "MEMORY", value = "512" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "sagis-cec-raw-backfill"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600 # 1 h ceiling; each ~80-120-file chunk runs in ~5-8 min
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: USDA WASDE raw backfill
# 6 tasks run in parallel by jobs/submit/submit_batch_backfill_wasde.py,
# each covering a non-overlapping year range of the 625-entry manifest.
# command is overridden per-task at submission time (containerOverrides).
# Sizing: 0.25 vCPU / 512 MB — pure network I/O, no in-memory parsing.
# Timeout: 1 h ceiling; each ~100-entry chunk completes in ~5-8 min.
# ---------------------------------------------------------------------------

resource "aws_batch_job_definition" "usda_wasde_raw_backfill" {
  name = "${var.project_name}-${var.environment}-usda-wasde-raw-backfill"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.worker_fleet_image

    # Default command — overridden per-task via containerOverrides at submit time.
    command = [
      "jobs/ingest/fetch_usda_wasde.py",
      "--skip-existing-s3",
      "--year-from", "1973",
      "--year-to", "2026"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.25" },
      { type = "MEMORY", value = "512" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "usda-wasde-raw-backfill"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600 # 1 h ceiling; each chunk ~5-8 min
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_cloudwatch_log_group" "batch" {
  name              = "/aws/batch/${var.project_name}-${var.environment}"
  retention_in_days = 30

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: GAIN raw backfill
# One task per commodity (10 total) submitted in parallel by
# jobs/submit/submit_batch_gain_backfill.py.
# Each task: crawl FAS GAIN pages → build manifest → download PDFs → S3.
# command is overridden per-task at submission time (containerOverrides).
# Sizing: 1 vCPU / 2 GB — curl_cffi is single-threaded; memory covers BS4 +
# in-memory PDF bytes (largest GAIN PDFs ~5 MB, 500 records max per commodity).
# Timeout: 6 h ceiling — a full commodity crawl + download is typically 1-3 h.
#
# D-PR-7 BEHAVIOUR CHANGE, stated because it is the one family whose retry posture
# gets STRICTER rather than merely explicit. This jobdef used to carry
# `{attempts: 3, evaluate_on_exit: [{on_exit_code = "137", action = "RETRY"}]}` --
# i.e. it retried OUT-OF-MEMORY kills three times. Exit 137 is deterministic: the
# container asked for more memory than the task had, and the next attempt asks for
# exactly the same amount. Retrying it burns three Fargate slots to reach the same
# answer and triples the alarm datapoints. The fix for an OOM is a resourceRequirements
# change (the evidence-build 8vCPU/16GB tear on 2026-08-02 is the estate's worked
# example), so the shared matrix classifies *OutOfMemory* as EXIT and this family
# now inherits it like every other producer.
# ---------------------------------------------------------------------------

resource "aws_batch_job_definition" "gain_backfill" {
  name = "${var.project_name}-${var.environment}-gain-backfill"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {}

  container_properties = jsonencode({
    image = local.worker_fleet_image

    # Default command — overridden per-task via containerOverrides at submit time.
    command = [
      "jobs/batch/gain_backfill_task.py",
      "--commodity-name", "wheat",
      "--commodity-id", "15",
      "--target-countries", "US,FR,AU,CA,UA,RU,IN,PK,EG,AR,CN,DE,PL,TR",
      "--bucket", "${var.leviathan_bucket}",
      "--aws-region", "${var.aws_region}",
      "--skip-existing-s3",
      "--sleep-seconds", "2"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "1" },
      { type = "MEMORY", value = "2048" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "gain-backfill"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 21600 # 6 h ceiling
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: USDA WAP raw backfill
# 6 parallel tasks submitted by jobs/submit/submit_batch_wap_backfill.py,
# each covering a non-overlapping year range of the 287-entry manifest.
# command is overridden per-task via containerOverrides at submission time.
# Sizing: 0.25 vCPU / 512 MB — direct CDN PDF download; single-threaded.
# Timeout: 1 h ceiling — each year-range chunk (~48 PDFs × 1.5 s sleep) ≈ 3 min.
# ---------------------------------------------------------------------------

resource "aws_batch_job_definition" "usda_wap_raw_backfill" {
  name = "${var.project_name}-${var.environment}-usda-wap-raw-backfill"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.worker_fleet_image

    # Default command — overridden per-task via containerOverrides at submit time.
    command = [
      "jobs/ingest/fetch_usda_wap.py",
      "--skip-existing-s3",
      "--year-from", "2002",
      "--year-to", "2026",
      "--sleep-seconds", "1.5"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.25" },
      { type = "MEMORY", value = "512" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "usda-wap-raw-backfill"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600 # 1 h ceiling; each chunk ≈ 3 min
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: CPC Soil Moisture → raw S3
# One task per year.  Downloads the annual tarball (~85MB) for prior years and
# extracts 365/366 daily GeoTIFFs into S3 raw.  For the current year, downloads
# individual daily files from the live GeoTIFF directory.
# Sizing: 0.5 vCPU / 1024 MB — peak memory ~500 MB (85 MB compressed tarball +
#   extracted TIF bytes).  Valid Fargate pairing.
# Timeout: 2 h ceiling; normal tarball runs complete in ~5–10 min.
# ---------------------------------------------------------------------------

resource "aws_batch_job_definition" "cpc_soil_to_raw" {
  name = "${var.project_name}-${var.environment}-cpc-soil-to-raw"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    year       = "2000"
    variable   = "w"
    bucket     = var.leviathan_bucket
    aws_region = var.aws_region
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/cpc_soil_to_raw_task.py",
      "--year", "Ref::year",
      "--variable", "Ref::variable",
      "--bucket", "Ref::bucket",
      "--aws_region", "Ref::aws_region"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.5" },
      { type = "MEMORY", value = "1024" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "cpc-soil-to-raw"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 7200 # 2 h ceiling; normal run ~5–10 min
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: CPC Soil Moisture raw S3 → bronze
# One task per (commodity, year).  Reads raw GeoTIFFs from S3, extracts
# per-region pixel values, and writes bronze Parquet partitioned by
# (country, region, year, month).  Raw files must exist before this runs.
# Sizing: 0.5 vCPU / 1024 MB — 20 concurrent TIF downloads at 854KB each
#   ≈ 17 MB peak in-flight, plus rasterio arrays.  Valid Fargate pairing.
# ---------------------------------------------------------------------------

resource "aws_batch_job_definition" "cpc_soil_raw_to_bronze" {
  name = "${var.project_name}-${var.environment}-cpc-soil-raw-to-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    year       = "2000"
    variable   = "w"
    bucket     = var.leviathan_bucket
    aws_region = var.aws_region
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/cpc_raw_to_bronze_task.py",
      "--year", "Ref::year",
      "--variable", "Ref::variable",
      "--bucket", "Ref::bucket",
      "--aws_region", "Ref::aws_region"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.5" },
      { type = "MEMORY", value = "1024" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "cpc-soil-raw-to-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 7200 # 2 h ceiling; normal run ~5–15 min
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: CPC Soil Moisture bronze → silver
# 31 commodity tasks run in parallel by jobs/submit/submit_batch_b2s_cpc_soil.py,
# one per commodity.  Each task reads all bronze Parquet for that commodity,
# transforms to long/tidy silver format, and writes partitioned silver Parquet.
# Sizing: 2 vCPU / 4096 MB — same as CHIRPS b2s.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "cpc_soil_bronze_to_silver" {
  name = "${var.project_name}-${var.environment}-cpc-soil-bronze-to-silver"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    commodity  = "corn_cbot"
    bucket     = var.leviathan_bucket
    aws_region = var.aws_region
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/cpc_bronze_to_silver_task.py",
      "--commodity", "Ref::commodity",
      "--bucket", "Ref::bucket",
      "--aws_region", "Ref::aws_region"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "4096" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "cpc-soil-bronze-to-silver"
      }
    }
  })

  # D-PR-11: attemptDurationSeconds -- PER ATTEMPT, so the mandatory terminal
  # catch-all in the retry matrix below is what keeps a hung job to ONE attempt.
  timeout {
    attempt_duration_seconds = 3600 # 1 h ceiling; 5 measured runs 206-249 s, 4x the max
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: MODIS NDVI raw CSV → bronze Parquet
# 5 tasks run in parallel (one per commodity group) submitted by
# jobs/submit/submit_batch_modis_ndvi_r2b.py.
# Each task downloads one AppEEARS results CSV from S3 raw, parses it into
# per-region DataFrames, and writes bronze Parquet partitioned by
# (commodity, country, region, year).
# Sizing: 1 vCPU / 2048 MB — each CSV is ~26 years × up to 131 points
#   × 23 periods = ~78k rows; pandas + pyarrow in-memory.
# Timeout: 2 h ceiling; normal run < 5 min.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "modis_ndvi_raw_to_bronze" {
  name = "${var.project_name}-${var.environment}-modis-ndvi-raw-to-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    run_id     = "placeholder_run_id"
    group      = "grains"
    bucket     = var.leviathan_bucket
    aws_region = var.aws_region
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/modis_ndvi_raw_to_bronze_task.py",
      "--run_id", "Ref::run_id",
      "--group", "Ref::group",
      "--bucket", "Ref::bucket",
      "--aws_region", "Ref::aws_region"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "1" },
      { type = "MEMORY", value = "2048" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "modis-ndvi-raw-to-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 7200 # 2 h ceiling; normal run < 5 min
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: MODIS NDVI bronze Parquet → silver Parquet (z-scores)
# 31 commodity tasks run in parallel submitted by
# jobs/submit/submit_batch_modis_ndvi_b2s.py, one per commodity.
# Each task loads all bronze for the commodity, filters to quality ∈ {0,1},
# computes per-(region, period) z-scores against the 2000–2020 baseline,
# and writes silver Parquet partitioned by (commodity, country, region, year).
# Sizing: 1 vCPU / 2048 MB — full-commodity bronze concat up to ~18k rows +
#   pandas groupby; modest memory footprint.
# Timeout: 1 h ceiling; normal run < 5 min.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "modis_ndvi_bronze_to_silver" {
  name = "${var.project_name}-${var.environment}-modis-ndvi-bronze-to-silver"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    commodity  = "corn_cbot"
    bucket     = var.leviathan_bucket
    aws_region = var.aws_region
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/modis_ndvi_bronze_to_silver_task.py",
      "--commodity", "Ref::commodity",
      "--bucket", "Ref::bucket",
      "--aws_region", "Ref::aws_region"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "1" },
      { type = "MEMORY", value = "2048" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    # D-SG G2-2 / T2 arming (2026-08-16): this jobdef is modis_biweekly's promote_jobdef
    # (self-promotion, forced by test_digest_pinned_producers_must_self_promote once
    # worker_fleet_image_digest pinned the family). An autonomous promote signs a KMS
    # approval, and kms:Sign lives ONLY on the SILVER-F014 silver-publisher role --
    # batch_job_role would AccessDeny on the FIRST unattended canonical write. Same
    # choice, same reason, as futures_eod_silver.
    jobRoleArn       = var.silver_publisher_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "modis-ndvi-bronze-to-silver"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600 # 1 h ceiling; normal run < 5 min
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  # (DSG-TAIL F1 probe, 2026-08-16: reason-less exits ARE terminal under this matrix --
  # job cb151695, exit 2, reason None, one attempt. No publisher variant needed.)
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: USDA PSD raw → bronze
# Single task reads all .zip keys under raw/production/source=usda_psd/,
# extracts the embedded CSV, and writes per-release-date Parquet shards.
# Sizing: 0.5 vCPU / 1024 MB — sequential zip extraction, modest CSV sizes.
# Timeout: 1 h ceiling; normal run < 5 min.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "usda_psd_bronze" {
  name = "${var.project_name}-${var.environment}-usda-psd-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = ["jobs/batch/psd_task.py"]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.5" },
      { type = "MEMORY", value = "1024" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "usda-psd-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: USDA FGIS raw → bronze
# Single task reads per-year grain inspection CSVs under
# raw/production/source=usda_fgis/ and writes per-year Parquet shards.
# Sizing: 0.5 vCPU / 1024 MB — 43 CSV files, ~400 MB total uncompressed.
# Timeout: 1 h ceiling; normal run < 10 min.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "usda_fgis_bronze" {
  name = "${var.project_name}-${var.environment}-usda-fgis-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = ["jobs/batch/fgis_task.py"]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.5" },
      { type = "MEMORY", value = "1024" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "usda-fgis-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: World Bank Pink Sheet raw → bronze
# Single task reads all .xlsx/.xls keys under
# raw/production/source=world_bank_pink_sheet/ and writes per-release Parquet.
# Sizing: 0.25 vCPU / 512 MB — single multi-sheet Excel file per release.
# Timeout: 1 h ceiling; normal run < 5 min.
#
# D-PR-22: THIS ONE IS DIGEST-PINNED (local.pink_sheet_image), unlike its :latest
# neighbours. pink_sheet_monthly is an AUTONOMOUS-promote chain and its other three
# legs (fetch + silver on b3-flat-silver, gate on silver-gate) are already pinned, so
# the bronze leg was the single mutable-tag hop in a path that writes canonical.
# ---------------------------------------------------------------------------
locals {
  # Digest when pinned, ":latest" when not -- so an unpinned environment keeps the
  # historical behaviour instead of losing the jobdef to a count gate. Same assembly
  # shape as local.futures_eod_image below: the repo URL has one source of truth.
  pink_sheet_image = (
    var.pink_sheet_image_digest == ""
    ? "${var.ecr_repository_url}:latest"
    : "${var.ecr_repository_url}@${var.pink_sheet_image_digest}"
  )
}

resource "aws_batch_job_definition" "world_bank_pink_sheet_bronze" {
  name = "${var.project_name}-${var.environment}-world-bank-pink-sheet-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.pink_sheet_image

    command = ["jobs/batch/pink_sheet_task.py"]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.25" },
      { type = "MEMORY", value = "512" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "world-bank-pink-sheet-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: USDA NASS raw → bronze
# Single task streams the large .gz CSV under raw/production/source=usda_nass/
# in 100k-row chunks and writes per-(series, year) Parquet shards.
# Sizing: 1 vCPU / 4096 MB — gz CSV expands to ~3 GB in-memory at peak.
# Timeout: 1 h ceiling; normal run ~10-20 min.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "usda_nass_bronze" {
  name = "${var.project_name}-${var.environment}-usda-nass-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = ["jobs/batch/nass_task.py", "--series", "all"]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    # 8.9 M annual rows + 793 K progress rows loaded into object-dtype pandas
    # DataFrames, then 16 concurrent pyarrow Arrow conversions for shard writes.
    # Peak RSS exceeds 8 GiB at 1 vCPU; 2 vCPU + 16 GiB is the next Fargate tier.
    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "16384" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "usda-nass-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: USDA NASS annual bronze -> silver
# Single task reads annual bronze shards and writes state/national feature
# partitions under silver/nass_annual/.
# Sizing: 1 vCPU / 4096 MB - streams bronze files one at a time and accumulates
# only the small state/national silver result.
# Timeout: 1 h ceiling; normal run expected < 10 min after bronze is populated.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "usda_nass_annual_silver" {
  name = "${var.project_name}-${var.environment}-usda-nass-annual-silver"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    bucket             = var.leviathan_bucket
    aws_region         = var.aws_region
    force_overwrite    = "false"
    bronze_commodities = "all"
    years              = "all"
    workers            = "8"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/nass_annual_silver_task.py",
      "--bucket", "Ref::bucket",
      "--aws-region", "Ref::aws_region",
      "--force-overwrite", "Ref::force_overwrite",
      "--bronze-commodities", "Ref::bronze_commodities",
      "--years", "Ref::years",
      "--workers", "Ref::workers"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "1" },
      { type = "MEMORY", value = "4096" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "usda-nass-annual-silver"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: USDA NASS crop-progress bronze -> silver
# Single task reads weekly crop-progress bronze shards and writes wide weekly
# state/national feature partitions under silver/nass_crop_progress/.
# Sizing: 1 vCPU / 4096 MB - many small bronze files, internally parallelized.
# Timeout: 1 h ceiling; normal run expected < 10 min after bronze is populated.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "usda_nass_crop_progress_silver" {
  name = "${var.project_name}-${var.environment}-usda-nass-crop-progress-silver"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    bucket             = var.leviathan_bucket
    aws_region         = var.aws_region
    force_overwrite    = "false"
    bronze_commodities = "all"
    years              = "all"
    workers            = "8"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/nass_crop_progress_silver_task.py",
      "--bucket", "Ref::bucket",
      "--aws-region", "Ref::aws_region",
      "--force-overwrite", "Ref::force_overwrite",
      "--bronze-commodities", "Ref::bronze_commodities",
      "--years", "Ref::years",
      "--workers", "Ref::workers"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "1" },
      { type = "MEMORY", value = "4096" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "usda-nass-crop-progress-silver"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: CONAB bulletin XLS raw → bronze
# Single task reads all .xls/.xlsx keys under
# raw/production/source=conab/bulletin_xls/ and writes per-safra Parquet.
# Sizing: 0.5 vCPU / 1024 MB — xlrd/openpyxl XLS parsing, small files.
# Timeout: 1 h ceiling; normal run < 5 min.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "conab_xls_bronze" {
  name = "${var.project_name}-${var.environment}-conab-xls-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = ["jobs/batch/conab_xls_task.py"]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.5" },
      { type = "MEMORY", value = "1024" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "conab-xls-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: FNC Colombia Excel raw → bronze
# Single task reads all .xlsx keys under raw/production/source=fnc/bulk/
# and writes one Parquet per series (7 series per file).
# Sizing: 0.25 vCPU / 1024 MB — openpyxl loads the entire workbook object
# graph at ExcelFile() open time; 512 MB is insufficient.
# Timeout: 1 h ceiling; normal run < 5 min.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Job definition: CONAB coffee bronze to silver
# Purpose: pivot Brazil coffee survey XLS bronze into state/national production
#          revision features by safra year, survey number, region, and type.
# Sizing: 0.25 vCPU / 1024 MB, small Excel-derived corpus.
# Timeout: 30 min ceiling; normal run should be much shorter.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "conab_coffee_silver" {
  name = "${var.project_name}-${var.environment}-conab-coffee-silver"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    bucket          = var.leviathan_bucket
    aws_region      = var.aws_region
    force_overwrite = "false"
    years           = "all"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/conab_coffee_silver_task.py",
      "--bucket", "Ref::bucket",
      "--aws-region", "Ref::aws_region",
      "--force-overwrite", "Ref::force_overwrite",
      "--years", "Ref::years"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.25" },
      { type = "MEMORY", value = "1024" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "conab-coffee-silver"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 1800
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_batch_job_definition" "fnc_excel_bronze" {
  name = "${var.project_name}-${var.environment}-fnc-excel-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = ["jobs/batch/fnc_excel_task.py"]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    # openpyxl loads the entire workbook object graph at ExcelFile() open
    # time; 1024 MiB is insufficient for the larger FNC bulk Excel files.
    # 0.25 vCPU supports up to 2048 MiB on Fargate.
    resourceRequirements = [
      { type = "VCPU", value = "0.25" },
      { type = "MEMORY", value = "2048" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "fnc-excel-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: FNC Colombia bronze to silver
# Purpose: pivot Colombian coffee production, price, export, area, and port/type
#          bronze parquet into business-facing silver feature tables.
# Sizing: 0.25 vCPU / 1024 MB, small Excel-derived corpus.
# Timeout: 30 min ceiling; normal run should be much shorter.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "fnc_colombia_silver" {
  name = "${var.project_name}-${var.environment}-fnc-colombia-silver"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    bucket          = var.leviathan_bucket
    aws_region      = var.aws_region
    force_overwrite = "false"
    years           = "all"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/fnc_colombia_silver_task.py",
      "--bucket", "Ref::bucket",
      "--aws-region", "Ref::aws_region",
      "--force-overwrite", "Ref::force_overwrite",
      "--years", "Ref::years"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.25" },
      { type = "MEMORY", value = "1024" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "fnc-colombia-silver"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 1800
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: MPOB BEPI HTML raw to bronze
# Single task reads all HTML keys under raw/production/source=mpob/ and
# writes per-release Parquet (annual summary + monthly tables).
# Sizing: 0.5 vCPU / 1024 MB, Fargate minimum for 0.5 vCPU.
# Timeout: 1 h ceiling; normal run < 5 min.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "mpob_bronze" {
  name = "${var.project_name}-${var.environment}-mpob-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = ["jobs/batch/mpob_task.py", "--release-type", "all"]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.5" },
      { type = "MEMORY", value = "1024" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "mpob-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: UNICA sugarcane HTML raw → bronze
# Single task reads all HTML keys under raw/production/source=unica/ and
# writes per-harvest-year Parquet shards.
# Sizing: 0.5 vCPU / 1024 MB — Fargate minimum for 0.5 vCPU.
# Timeout: 1 h ceiling; normal run < 5 min.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "unica_bronze" {
  name = "${var.project_name}-${var.environment}-unica-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = ["jobs/batch/unica_task.py"]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.5" },
      { type = "MEMORY", value = "1024" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "unica-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: USDA ESR raw → bronze
# Single task reads all .json keys under raw/production/source=usda_esr/
# (370 files across commodity × market_year) and writes per-key Parquet.
# Sizing: 1 vCPU / 2048 MB — 16-thread pool, 370 JSON files up to ~10 MB each.
# Timeout: 2 h ceiling; normal run ~10-20 min.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "usda_esr_bronze" {
  name = "${var.project_name}-${var.environment}-usda-esr-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  # ALIGNMENT TO LIVE rev 5, not a new choice. Terraform state held rev 1
  # (`esr_task.py` bare, 1 vCPU / 2048 MB); the live latest-ACTIVE this family has
  # been running carries `--backfill-as-of` plus 2 vCPU / 4096 MB. Re-registering
  # from the stale definition would have been a silent downgrade of both, so the
  # newer live shape is adopted verbatim. The SCHEDULED path is unaffected either
  # way -- esr_weekly's SFN task passes command=["jobs/batch/esr_task.py"] as a
  # ContainerOverride, which REPLACES the jobdef command; this matters only to
  # ad-hoc submissions that rely on the jobdef's own command + Ref:: parameters.
  parameters = {
    backfill_as_of = "20260524"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = ["jobs/batch/esr_task.py", "--backfill-as-of", "Ref::backfill_as_of"]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "4096" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "usda-esr-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 7200 # 2 h ceiling; 370 JSON files
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: USDA FAS ESR weekly FETCH (api.data.gov -> raw S3)
# Phase D D-W1: the recurring-ingest fix. Runs the existing sequential fetch
# (jobs/ingest/fetch_usda_esr.py --mode weekly) that snapshots the current +
# new-crop marketing year for all 44 ESR commodity codes -- the FULL measured
# source universe since 2026-08-20, widened from the 10 it used to carry -- as an immutable
# as_of={today} object -- so post-backfill weeks actually land instead of the
# data freezing at the 2026-05-24 backfill. Fired weekly by the DISABLED
# EventBridge Scheduler rule ...-esr-weekly-ingest (see envs/dev/main.tf); the
# schedule ENABLE flip is user-gated.
#
# SEQUENTIAL BY CONTRACT: api.data.gov allows 1,000 req/hr per key and this is a
# government server, NOT a CDN -- the fetch NEVER threads (fetch_usda_esr.py:16-17).
# A weekly run is 88 requests (44 codes x current+new-crop MY) at 1.0s sleep, so
# ~3 min -- still an order of magnitude under the hourly key budget.
# Sizing: 0.25 vCPU / 512 MB -- pure network I/O, no in-memory parsing (matches
# the other fetch-family jobdefs: sagis_cec, usda_wasde, usda_wap).
#
# The FAS_API_KEY is mounted from Secrets Manager via `secrets`/valueFrom. The
# secret leviathan/dev/fas-api-key does NOT exist yet -- its creation is
# USER-GATED (the value lives in the local .env; list-secrets today shows only
# anthropic-api-key + the two evidence-pg secrets). This block REFERENCES it by
# ARN pattern only; the execution role's GetSecretValue grant is in the iam
# module (also user-gated on the secret's creation). count-gated on the ARN so
# this jobdef is a no-op until the ARN is wired.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "usda_esr_fetch" {
  count = var.fas_api_key_secret_arn != "" ? 1 : 0

  name = "${var.project_name}-${var.environment}-usda-esr-fetch"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.worker_fleet_image

    # Weekly snapshot: --as-of defaults to today at runtime (the as_of partition
    # key). --skip-existing-s3 makes a re-fire idempotent. Sequential by design.
    command = [
      "jobs/ingest/fetch_usda_esr.py",
      "--mode", "weekly",
      "--skip-existing-s3"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    # FAS_API_KEY injected by the ECS agent from Secrets Manager (never in env/URL/code).
    # USER-GATED: fails at job launch until leviathan/dev/fas-api-key is created.
    secrets = [
      { name = "FAS_API_KEY", valueFrom = var.fas_api_key_secret_arn }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.25" },
      { type = "MEMORY", value = "512" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "usda-esr-fetch"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600 # 1 h ceiling; a weekly run is 88 sequential requests (~3 min)
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: text/ layer → GraphRAG Parquet extraction
# Reads document.json files from text/source={source}/ and calls Claude Haiku
# via Bedrock to extract entities, causal edges, forecasts, and sentiment into
# 4 Parquet tables under graphrag/ on S3.
# One task per (source, year_range): --source usda_wasde --year_from 2000 --year_to 2006
# Sizing: 1 vCPU / 2048 MiB — Bedrock calls are network-bound, not CPU-bound.
# Timeout: 4 h ceiling; a full source backfill (~600 docs) takes ~60 min.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "text_to_graphrag" {
  name = "${var.project_name}-${var.environment}-text-to-graphrag"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    source          = "usda_wasde"
    year_from       = "2000"
    year_to         = "2026"
    force_overwrite = "false"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/text_to_graphrag_task.py",
      "--source", "Ref::source",
      "--year_from", "Ref::year_from",
      "--year_to", "Ref::year_to",
      "--force_overwrite", "Ref::force_overwrite"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "1" },
      { type = "MEMORY", value = "2048" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "text-to-graphrag"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 14400 # 4 h ceiling
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: USDA FGIS export inspections bronze → silver
# One task per invocation; reads CY bronze Parquets for requested marketing
# years, applies weekly-aggregation transform, writes per-(slug, MY) silver.
# Sizing: 1 vCPU / 4096 MB — 52k+ rows in-memory, 8 parallel workers.
# Timeout: 1 h ceiling; full-history run (~40 MYs × 5 slugs) < 10 min.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "fgis_silver" {
  name = "${var.project_name}-${var.environment}-fgis-silver"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    bucket          = var.leviathan_bucket
    aws_region      = var.aws_region
    force_overwrite = "false"
    marketing_years = "all"
    slugs           = "all"
    workers         = "8"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/fgis_silver_task.py",
      "--bucket", "Ref::bucket",
      "--aws-region", "Ref::aws_region",
      "--force-overwrite", "Ref::force_overwrite",
      "--marketing-years", "Ref::marketing_years",
      "--slugs", "Ref::slugs",
      "--workers", "Ref::workers"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "1" },
      { type = "MEMORY", value = "4096" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    # D-SG G2-2 / T2 arming (2026-08-16): this jobdef is fgis's promote_jobdef
    # (self-promotion, forced by test_digest_pinned_producers_must_self_promote --
    # fgis-silver rides local.worker_fleet_image, a digest pin). An autonomous promote
    # signs a KMS approval, and kms:Sign lives ONLY on the SILVER-F014 silver-publisher
    # role -- batch_job_role would AccessDeny on the FIRST unattended canonical write.
    # Same choice, same reason, as futures_eod_silver and modis_ndvi_bronze_to_silver.
    jobRoleArn       = var.silver_publisher_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "fgis-silver"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_batch_job_definition" "mpob_silver" {
  name = "${var.project_name}-${var.environment}-mpob-silver"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    bucket          = var.leviathan_bucket
    aws_region      = var.aws_region
    force_overwrite = "false"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/mpob_silver_task.py",
      "--bucket", "Ref::bucket",
      "--aws-region", "Ref::aws_region",
      "--force-overwrite", "Ref::force_overwrite"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "1" },
      { type = "MEMORY", value = "2048" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    # DSG-TAIL A1 (2026-08-16): this jobdef is mpob's promote_jobdef (self-promotion --
    # it rides local.worker_fleet_image, a digest pin, and since the A1 fold it hosts BOTH
    # mpob silver legs). An autonomous promote signs a KMS approval, and kms:Sign lives
    # ONLY on the SILVER-F014 silver-publisher role -- batch_job_role would AccessDeny on
    # the FIRST unattended canonical write. Same choice, same reason, as futures_eod_silver,
    # modis_ndvi_bronze_to_silver and fgis_silver. The pre-start-only retry matrix STAYS
    # (probe-amended: CannotPull*/ResourceInit* retries never ran the write path; the
    # T2-armed self-promote jobdefs keep the identical matrix).
    jobRoleArn       = var.silver_publisher_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "mpob-silver"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 1800
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: MPOB overview PDFs → text/ (Phase 1, 2010–2016)
# ---------------------------------------------------------------------------

resource "aws_batch_job_definition" "mpob_overview_text" {
  name = "${var.project_name}-${var.environment}-mpob-overview-text"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    bucket          = var.leviathan_bucket
    aws_region      = var.aws_region
    force_overwrite = "false"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/mpob_overview_text_task.py",
      "--bucket", "Ref::bucket",
      "--aws-region", "Ref::aws_region",
      "--force-overwrite", "Ref::force_overwrite"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.5" },
      { type = "MEMORY", value = "1024" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "mpob-overview-text"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: MPOB overview PDFs → bronze/ (Phase 2, 2010–2016)
# ---------------------------------------------------------------------------

resource "aws_batch_job_definition" "mpob_overview_bronze" {
  name = "${var.project_name}-${var.environment}-mpob-overview-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    bucket          = var.leviathan_bucket
    aws_region      = var.aws_region
    force_overwrite = "false"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/mpob_overview_bronze_task.py",
      "--bucket", "Ref::bucket",
      "--aws-region", "Ref::aws_region",
      "--force-overwrite", "Ref::force_overwrite"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.5" },
      { type = "MEMORY", value = "1024" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "mpob-overview-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: MPOB overview_pdf bronze → annual silver — FOLDED AWAY
# (DSG-TAIL A1, 2026-08-16). mpob_annual_silver was spec-identical to mpob_silver
# (image, exec role, network, 1 vCPU/2048) and the SFN thin contract overrides the
# command per task, so the annual silver leg now runs on leviathan-dev-mpob-silver.
# The fold is what lets the family self-promote through a SCALAR promote_jobdef —
# the arity lint (gen_sfn_inputs lint_descriptor: own == {pj}) stays untouched and
# load-bearing. The KNOWN-RED walkthrough lives in test_gen_sfn_inputs.py (rewritten
# to the closed state in the same change). jobs/batch/mpob_annual_silver_task.py is
# unaffected — the task file lives on; only the jobdef died.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Job definition: silver/* → gold/feature_spine (long-format training matrix)
# 31 commodity tasks run in parallel submitted by
# jobs/submit/submit_batch_feature_spine.py, one per commodity.
# Each task reads weather, FAOSTAT, and PSD silver inputs, builds the
# point-in-time-correct feature spine, and writes one Parquet partition +
# a run manifest with input fingerprints, params hash, and git SHA.
# Sizing: 1 vCPU / 2048 MB — pandas groupby + rolling over silver inputs;
#   peak RSS ~500 MB per commodity; 2048 MiB gives 4x headroom.
# Timeout: 30 min ceiling; normal run < 5 min per commodity.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "feature_spine" {
  name = "${var.project_name}-${var.environment}-feature-spine"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    commodity                   = "corn_cbot"
    bucket                      = var.leviathan_bucket
    aws_region                  = var.aws_region
    start_crop_year             = "1981"
    end_crop_year               = "2026"
    workers                     = "4"
    source_year_min             = "none"
    source_year_max             = "none"
    dataset_version             = "none"
    write_versioned             = "false"
    versioned_only              = "false"
    fail_if_version_exists      = "true"
    skip_existing_versioned     = "false"
    write_dataset_artifacts     = "true"
    source_certification_report = "none"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/feature_spine_task.py",
      "--commodity", "Ref::commodity",
      "--bucket", "Ref::bucket",
      "--aws-region", "Ref::aws_region",
      "--start-crop-year", "Ref::start_crop_year",
      "--end-crop-year", "Ref::end_crop_year",
      "--workers", "Ref::workers",
      "--source-year-min", "Ref::source_year_min",
      "--source-year-max", "Ref::source_year_max",
      "--dataset-version", "Ref::dataset_version",
      "--write-versioned", "Ref::write_versioned",
      "--versioned-only", "Ref::versioned_only",
      "--fail-if-version-exists", "Ref::fail_if_version_exists",
      "--skip-existing-versioned", "Ref::skip_existing_versioned",
      "--write-dataset-artifacts", "Ref::write_dataset_artifacts",
      "--source-certification-report", "Ref::source_certification_report",
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "4" },
      { type = "MEMORY", value = "16384" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "feature-spine"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 7200 # 2 h ceiling
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: versioned gold matrices -> model-ready target/matrix datasets
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "model_ready_datasets" {
  name = "${var.project_name}-${var.environment}-model-ready-datasets"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    bucket                  = var.leviathan_bucket
    aws_region              = var.aws_region
    source_dataset_version  = "none"
    model_dataset_version   = "none"
    target_source           = "psd"
    psd_source_key          = "silver/psd/part-000.parquet"
    commodities             = "all"
    target_keys             = "none"
    snapshot_mode           = "false"
    snapshot_stages         = "none"
    as_of_date              = "none"
    compatible_feature_sets = "none"
    workers                 = "8"
    skip_existing_versioned = "false"
    force_overwrite         = "false"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/build_model_ready_datasets.py",
      "--bucket", "Ref::bucket",
      "--aws-region", "Ref::aws_region",
      "--target-source", "Ref::target_source",
      "--psd-source-key", "Ref::psd_source_key",
      "--source-dataset-version", "Ref::source_dataset_version",
      "--model-dataset-version", "Ref::model_dataset_version",
      "--commodities", "Ref::commodities",
      "--target-keys", "Ref::target_keys",
      "--snapshot-mode", "Ref::snapshot_mode",
      "--snapshot-stages", "Ref::snapshot_stages",
      "--as-of-date", "Ref::as_of_date",
      "--compatible-feature-sets", "Ref::compatible_feature_sets",
      "--workers", "Ref::workers",
      "--skip-existing-versioned", "Ref::skip_existing_versioned",
      "--force-overwrite", "Ref::force_overwrite",
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "8192" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "model-ready-datasets"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_batch_job_definition" "unica_annual_state" {
  name = "${var.project_name}-${var.environment}-unica-annual-state"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {
    bucket          = var.leviathan_bucket
    aws_region      = var.aws_region
    force_overwrite = "false"
  }

  container_properties = jsonencode({
    image = local.worker_fleet_image

    command = [
      "jobs/batch/unica_annual_state_task.py",
      "--bucket", "Ref::bucket",
      "--aws-region", "Ref::aws_region",
      "--force-overwrite", "Ref::force_overwrite"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.5" },
      # DSG-TAIL A2 review fold: 1024 -> 2048. The A2 fold makes this jobdef host the
      # biweekly leg too, which previously ran on b3-flat-silver's 4096 MB -- and the
      # day-0 bridge ran on publisher-runner, so the biweekly task had NEVER executed at
      # 1024 MB. Sizing a fold target to its new tenant set is part of the fold, not a
      # second variable (the annual leg's own 1024-proven footprint is unaffected by
      # headroom). 0.5 vCPU supports up to 4 GB on Fargate; 2048 = 4-6x the estimated
      # biweekly peak (KB-scale tables, pandas over small bronze parquets).
      { type = "MEMORY", value = "2048" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    # DSG-TAIL A2 (2026-08-16): this jobdef is unica's promote_jobdef (self-promotion --
    # it rides local.worker_fleet_image, a digest pin, and since the A2 fold it hosts BOTH
    # unica silver legs: annual/state AND biweekly, commands overridden per task by the
    # SFN). An autonomous promote signs a KMS approval; kms:Sign lives ONLY on the
    # SILVER-F014 silver-publisher role. Same choice, same reason, as futures_eod_silver,
    # modis_ndvi_bronze_to_silver, fgis_silver and mpob_silver. NOTE the digest fence
    # (test_digest_pinned_producers_must_self_promote) had this family's exposure MASKED
    # for weeks behind mpob's alphabetically-earlier red -- the arming surfaced it.
    jobRoleArn       = var.silver_publisher_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "unica-annual-state"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 900
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: T2B pattern-records ledger sweep
# (docs/private/T2B_PATTERN_RECORDS_PLAN.md sec 7 step 5 / D10; the P3
# morning-brief pattern: own scoped role, own jobdef, schedule created DISABLED,
# ONE manual day-0 run, ENABLE only after review.)
#
# Runs jobs/batch/pattern_records_sweep_task.py: the DAILY engine replay over the
# mapped (driver_or_chain, contract) catalog at asof=today, recording each pair's
# fired/declined verdict into gold_pattern_records (~600 rows/day, plan F3). The
# one-time backfill grid is the SAME jobdef with --backfill appended by the
# submit wrapper (jobs/submit/submit_batch_pattern_records_sweep.py), never a
# second jobdef.
#
# FOUR non-obvious wiring facts, each load-bearing:
#
#  1. IMAGE = the EMBEDDER image, pinned BY DIGEST (var.pattern_records_image is
#     "<repo>@sha256:..."; the digest is CONTENT-CHECKED before it is pinned --
#     never :latest, the d9b2e10e stale-tag lesson). count-gated on the variable,
#     so this jobdef does not exist until the digest is pinned.
#  2. NO --asof IN THE BAKED COMMAND. The task defaults asof to today UTC, and it
#     REFUSES a non-backfill sweep at a past asof (a daily_sweep row must be
#     written at its OWN asof). A baked date would rot on the first fire and a
#     Ref:: parameter default would rot silently; omission is the only correct
#     form for a scheduled daily job.
#  3. GRAPHRAG_NUMBERS_BACKEND=pg + EVIDENCE_PG_DSN are MANDATORY, not
#     decoration: the sweep asserts both at startup and exits otherwise. Without
#     the pg seam the quantify path is DEAD and every fired=false verdict is an
#     ARTIFACT (the 2026-07-23 phantom-regression lesson) -- which would poison
#     the ledger permanently, since a recorded verdict is never recomputed.
#  4. GRAPHRAG_ENGINE_VERSION = the pinned image ref. The engine_version
#     WRITE-GUARD (plan sec 2.3 / F1) is what stops a re-run under bumped code
#     from silently rewriting a past verdict -- and the task resolves that stamp
#     from env FIRST, falling back to a git SHA that does not exist inside the
#     container (it would degrade to "unknown" and collapse the code axis of the
#     guard). Injecting the image ref makes the stamp exact and immutable.
#
# Canonical publish authority is NOT in this jobdef: --publish-mode canonical
# still needs a signed approval, minted at runtime via kms:Sign on the A-W1
# publish-signer CMK (LEVIATHAN_APPROVAL_MODE=kms + LEVIATHAN_KMS_KEY_ID below).
# Revoking that ONE root-level grant leaves the sweep able to run dry-run/shadow
# and nothing more -- the kill-switch.
#
# Sizing: 2 vCPU / 8 GiB -- ~600 pg probes + a parquet write per partition, the
# same shape the submit wrapper has always sized for. Timeout 3 h covers the
# daily sweep with a wide margin; the one-time backfill grid (~156 asofs) passes
# a longer per-attempt timeout at submit time rather than inflating the daily
# ceiling. NO RE-ATTEMPT ON A PUBLISHING JOB: a publisher must not be silently
# re-attempted into a partial second publish -- a failed sweep is re-fired
# deliberately (the same-asof re-run is idempotent under the write-guard).
# D-PR-7 STATUS (corrected D-SG review m-3, 2026-08-16): this jobdef carries NO
# retry_strategy AT ALL, deliberately -- it does not consume the shared
# producer_retry_rules local, so nothing here retries on ANY class, including the
# pre-start ones (ResourceInitializationError / CannotPullContainer). Batch's
# default for a jobdef without a retryStrategy is attempts=1: every failure
# terminates on the first attempt. Admitting the pre-start classes to publishers
# is owner decision D17 (declined for now) and would be its own reviewed change
# plus a rewrite of the pinning doctrine test.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "pattern_records_sweep" {
  count = var.pattern_records_image != "" ? 1 : 0

  name = "${var.project_name}-${var.environment}-pattern-records-sweep"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = var.pattern_records_image

    # Daily sweep at asof=today (see fact 2). --backfill / --dry-run / a different
    # --publish-mode arrive as containerOverrides.command from the submit wrapper.
    command = [
      "jobs/batch/pattern_records_sweep_task.py",
      "--publish-mode", "canonical"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment },
      # the quantify seam (fact 3) -- the task asserts this exact value
      { name = "GRAPHRAG_NUMBERS_BACKEND", value = "pg" },
      # the write-guard's code axis (fact 4)
      { name = "GRAPHRAG_ENGINE_VERSION", value = var.pattern_records_image },
      # runtime self-mint of the PublishApproval (A-W1); inert unless the job is
      # run with --publish-mode canonical AND the role holds kms:Sign.
      { name = "LEVIATHAN_APPROVAL_MODE", value = "kms" },
      { name = "LEVIATHAN_KMS_KEY_ID", value = var.publish_signer_kms_key_arn }
    ]

    # EVIDENCE_PG_DSN injected by the ECS agent from Secrets Manager under the
    # EXECUTION role (never a plaintext env, never in the task def).
    secrets = [
      { name = "EVIDENCE_PG_DSN", valueFrom = var.numbers_pg_dsn_secret_arn }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "8192" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    # DEDICATED scoped role -- NOT batch_job_role (that one is reused by the
    # internet-facing serving task).
    jobRoleArn = var.pattern_records_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "pattern-records-sweep"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 10800 # 3 h ceiling; a daily sweep is ~600 pg probes
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  # T2b DOCTRINE EXCLUSION (sitting-2 skeptic, 2026-08-04): this jobdef PUBLISHES. The
  # D-PR-7 matrix is deliberately NOT stamped here -- a retried publisher re-runs its
  # write path, and the write-guard doctrine wants refusals surfaced, never re-driven.
  # (ResourceInitializationError precedes any write and WOULD be retry-safe; ratify that
  # nuance separately before narrowing this exclusion.) Pinned by the no-retry-on-a-
  # publishing-job doctrine test in test_futures_eod_cloud_legs.py.

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ===========================================================================
# PRICE_AND_PLAYBOOKS W1a + W2 -- the two futures_eod chains' job definitions.
#
# configs/silver/dags/futures_eod_free.json     -> fetch: futures-eod-free-fetch
#                                                  silver: futures-eod-silver
# configs/silver/dags/futures_eod_databento.json-> fetch: databento-fetch
#                                                  silver: futures-eod-silver  (SHARED)
#
# THE IMAGE IS PINNED BY DIGEST, NOT :latest. Every other jobdef in this module
# still rides "${var.ecr_repository_url}:latest" for historical reasons; these three
# do not, and the reason is specific to this family: `databento` and `xlrd` are the
# two runtime dependencies whose ABSENCE is SILENT (the yfinance ImportError wrote
# nothing for six weeks with no freshness alarm, and fetch_databento_eod.make_client
# turns that class of failure into an explicit "rebuild + repin" SystemExit). A digest
# says exactly which build was verified to carry them. It is the same discipline as
# pattern_records_sweep above, and the SILVER-F085 datestamp-tag rule
# (scripts/build_push_worker.ps1) is what keeps the pinned digest from being GC'd.
#
# ALL THREE ARE COUNT-GATED so an unpinned/unprovisioned lane is a terraform no-op
# rather than a jobdef that fails at 22:30 UTC on the first armed cron.
#
# NOT ARMED BY THIS FILE. Registering a jobdef only makes the chain RUNNABLE; what
# actually fires it is the dag_schedules.auto.tfvars.json entry (implementer B).
# Both descriptors also carry promote_mode = stop_and_notify, so the machine
# publishes SHADOW ONLY and promote.tasks renders EMPTY -- nothing here can write a
# canonical partition on a schedule.
# ===========================================================================

locals {
  # "<worker repo>@sha256:..." -- assembled here rather than passed in whole (the
  # pattern_records shape) because these three run the WORKER image the module is
  # already wired to, so there is exactly one source of truth for the repo URL.
  futures_eod_image = (
    var.futures_eod_image_digest == ""
    ? ""
    : "${var.ecr_repository_url}@${var.futures_eod_image_digest}"
  )

  # The SILVER leg may be pinned one build ahead of (or behind) the fetch legs -- see
  # var.futures_eod_silver_image_digest. Empty override = share the family digest, so
  # the default shape is still one pin for all three. The FAMILY gate stays
  # local.futures_eod_image: an empty family digest still means "none of the three".
  futures_eod_silver_image = (
    var.futures_eod_silver_image_digest == ""
    ? local.futures_eod_image
    : "${var.ecr_repository_url}@${var.futures_eod_silver_image_digest}"
  )

  # The publish-signer CMK by ALIAS, not ARN. This is the string every ARMED chain's
  # promote task already sends (dag_schedules.auto.tfvars.json: LEVIATHAN_KMS_KEY_ID =
  # "alias/leviathan-dev-publish-signer"), and it is identical to
  # aws_kms_alias.publish_signer.name in envs/dev. Alias over ARN so a CMK
  # re-key does not silently strand every baked jobdef. kms:Sign resolves an
  # "alias/<name>" KeyId natively.
  publish_signer_alias = "alias/${var.project_name}-${var.environment}-publish-signer"
}

# ---------------------------------------------------------------------------
# Job definition: futures_eod FREE-venue fetch (raw landing, four producers)
#
# ONE jobdef, FOUR legs. czce / jse / cepea / miax all land raw/ + raw_meta/ with
# the same shape, the same role and the same sizing, and the state machine supplies
# each leg's own containerOverrides.command -- so four jobdefs would be four copies
# of one thing that drift apart.
#
# NO SECRETS BLOCK, DELIBERATELY. All four venues are unauthenticated public GETs
# (futures_eod_free.json: "NO SECRETS: every one of these four venues is an
# unauthenticated public GET"). A secrets block here would be an inert lie that the
# next reader has to disprove.
#
# ROLE = batch_job_role, the raw-landing role every other fetch-family jobdef uses
# (sagis_cec_raw_backfill, usda_wasde_raw_backfill, cpc_soil_to_raw, usda_esr_fetch).
# These producers write raw/ and raw_meta/ and NOTHING under silver/ -- the publisher
# role is for the silver leg below and would be a needless widening here.
#
# Sizing 1 vCPU / 2048 MB: the legs are network-bound, but JSE and the CEPEA archive
# both open .xls through xlrd in memory (xlrd>=2.0 is a CORE pyproject dependency, NOT
# a [batch] extra, so it needs no rebuild -- futures_eod_free.json precondition (c)).
#
# The BAKED command is the CZCE leg (the flagship, and the only one whose
# --mode/--lookback-days shape is the generic one). Every scheduled invocation
# overrides it; a bare re-fire of the jobdef therefore re-runs an idempotent
# 5-day CZCE incremental, which is the least surprising possible default.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "futures_eod_free_fetch" {
  count = local.futures_eod_image != "" ? 1 : 0

  name = "${var.project_name}-${var.environment}-futures-eod-free-fetch"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.futures_eod_image

    command = [
      "jobs/ingest/fetch_czce_eod.py",
      "--mode", "incremental",
      "--lookback-days", "5"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "1" },
      { type = "MEMORY", value = "2048" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "futures-eod-free-fetch"
      }
    }
  })

  timeout {
    # 1 h ceiling. The longest leg is a 5-session CZCE incremental (5 small GETs +
    # polite sleeps); JSE/CEPEA are single objects. A leg that has not finished in an
    # hour is stuck on a venue, not slow.
    attempt_duration_seconds = 3600
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: futures_eod DATABENTO fetch (raw DBN landing)
#
# Separate from the free-venue jobdef for exactly one reason: this leg carries a
# SECRET. Folding it into futures-eod-free-fetch would mount DATABENTO_API_KEY into
# four containers that have no use for it.
#
# DATABENTO_API_KEY is injected by the ECS agent from Secrets Manager under the
# EXECUTION role (the usda_esr_fetch shape). The producer reads env FIRST and only
# falls back to a boto3 get_secret_value under the JOB role, so the valueFrom mount is
# what keeps the job role free of any secretsmanager grant. count-gated on the ARN:
# futures_eod_databento.json precondition (c) -- "provision the
# leviathan/dev/databento-api-key secret + the execution-role GetSecretValue grant" --
# is USER-GATED, and a jobdef that exists before the secret does would fail at
# container START (a much less legible failure than not existing).
#
# The vendor `databento` package lives in pyproject's [batch] extra, which the worker
# image installs. That is precisely what the digest pin above certifies: the pinned
# build is a post-databento-pin image, so precondition (d) is discharged BY THE PIN.
#
# Sizing 1 vCPU / 2048 MB -- submit, poll, download, land. The DBN payloads stream to
# a temp dir and are landed per file; nothing is held whole in memory.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "databento_fetch" {
  count = local.futures_eod_image != "" && var.databento_api_key_secret_arn != "" ? 1 : 0

  name = "${var.project_name}-${var.environment}-databento-fetch"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.futures_eod_image

    # --mode is REQUIRED by the producer's parser, so it is baked (an unparameterized
    # re-fire must not die in argparse). The scheduled invocation sends the same
    # command via containerOverrides.
    command = [
      "jobs/ingest/fetch_databento_eod.py",
      "--mode", "incremental",
      "--lookback-days", "5"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment }
    ]

    # Never a plaintext env, never in the task def, never in the log stream (the
    # producer logs "present", not the value, and never its length).
    secrets = [
      { name = "DATABENTO_API_KEY", valueFrom = var.databento_api_key_secret_arn }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "1" },
      { type = "MEMORY", value = "2048" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "databento-fetch"
      }
    }
  })

  timeout {
    # 4 h ceiling, chosen ABOVE the producer's own per-unit wait so the in-process
    # TimeoutError ("job <id> did not reach 'done' within 7200s") is what an operator
    # sees, not an opaque Batch kill. wait_and_download's max_wait_seconds default is
    # 7200 PER submitted batch job; 14400 leaves room for a couple of units.
    attempt_duration_seconds = 14400
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  retry_strategy {
    attempts = local.producer_retry_attempts

    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: silver_futures_eod producer -- SHARED BY BOTH CHAINS
#
# jobs/batch/futures_eod_task.py is ONE --source-dispatched task over ONE table with
# ONE contract, one partition scheme and one merge rule, so it is ONE jobdef: the free
# chain sends --source czce|jse|cepea|miax and the Databento chain sends the default.
#
# ROLE = silver-publisher, and this is NOT optional. silver_futures_eod is a class-A
# REGISTERED-partition table: publishing it calls glue:CreatePartition/
# BatchCreatePartition, which lives on silver_publisher_base and NOT on
# batch_job_role. The shadow leg writes silver/<table>/_shadow/... -- still under the
# publisher's silver/* grant -- and leviathan.silver.freshness excludes "/_shadow/"
# from the canonical clock by design, so a shadow write neither needs nor gets any
# extra authority.
#
# THE KMS PAIR IS PRESENT BUT INERT UNDER THE SCHEDULE. Both descriptors declare
# auth_mode=kms; publish_guard mints its short-lived PublishApproval from
# LEVIATHAN_APPROVAL_MODE + LEVIATHAN_KMS_KEY_ID. Baking them means a HUMAN promote --
# the whole point of promote_mode=stop_and_notify, which renders promote.tasks EMPTY --
# can re-run the identical command with --publish-mode canonical on this jobdef and
# needs no env plumbing at the console. It changes nothing about a scheduled fire:
# the baked command below is --publish-mode shadow, and the state machine's silver
# phase always overrides with --publish-mode shadow too.
#
#   NOTE FOR THE PROMOTE FLIP: when either chain flips to promote_mode=autonomous,
#   scripts/silver/gen_sfn_inputs.py renders the canonical re-run against
#   PROMOTE_RUNNER_JOBDEF = "leviathan-dev-silver-publisher-runner", NOT this jobdef,
#   and carries the KMS pair in task.env. So the runner must also be able to run
#   futures_eod_task.py. The pair baked here is the manual-promote path, not the
#   machine's.
#
# Sizing 1 vCPU / 4096 MB: an incremental run holds five days of one source but stages
# the whole (leviathan_slug, trade_year) object and UNIONS it with the existing
# canonical partition before publishing -- a trade_year, not a lookback window, is the
# in-memory unit. Same shape as fgis_silver (and the since-folded mpob_annual_silver).
#
# NO RE-ATTEMPT ON A PUBLISHING JOB: a publisher must never be silently re-attempted
# into a partial second publish. A failed silver task is re-fired deliberately (the run
# is idempotent under skip_existing=false + the canonical union).
# D-PR-7 STATUS (corrected D-SG review m-3, 2026-08-16): this jobdef carries NO
# retry_strategy AT ALL, deliberately -- it does not consume the shared producer_retry_rules
# local (T2b publisher-doctrine exclusion, pinned by test_futures_eod_cloud_legs.py). Batch's
# default is attempts=1: every failure, pre-start classes included, terminates on the first
# attempt. Admitting ResourceInitializationError/CannotPullContainer here is owner decision
# D17 (declined for now); it would rewrite the doctrine test, never delete it.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "futures_eod_silver" {
  count = local.futures_eod_image != "" && var.silver_publisher_job_role_arn != "" ? 1 : 0

  name = "${var.project_name}-${var.environment}-futures-eod-silver"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    # NOT local.futures_eod_image -- this leg carries its own pin (the fetch legs and
    # the publisher have been repinned independently more than once). ALIGNMENT RULE:
    # this value must equal the image on the LIVE latest-ACTIVE revision of
    # leviathan-dev-futures-eod-silver unless the repin is the deliberate point of the
    # change; terraform re-registering it from a stale digest is a rollback of the
    # publishing leg that nothing else in the plan would name.
    image = local.futures_eod_silver_image

    # The Databento chain's silver command verbatim (--source defaults to databento).
    # --publish-mode shadow is baked ON PURPOSE: an un-overridden fire must never be
    # able to touch canonical. The free chain overrides with --source czce|jse|cepea|miax.
    command = [
      "jobs/batch/futures_eod_task.py",
      "--mode", "incremental",
      "--lookback-days", "5",
      "--publish-mode", "shadow"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment },
      # auth_mode=kms (both descriptors). Inert unless the job is run with
      # --publish-mode canonical AND the role holds kms:Sign -- deleting the
      # silver_publisher_kms_sign grant in envs/dev is the kill-switch.
      { name = "LEVIATHAN_APPROVAL_MODE", value = "kms" },
      { name = "LEVIATHAN_KMS_KEY_ID", value = local.publish_signer_alias }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "1" },
      { type = "MEMORY", value = "4096" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    # The GATED writer (SILVER-F014). NOT batch_job_role: that role is reused by the
    # internet-facing serving task and holds no Glue partition authority anyway.
    jobRoleArn = var.silver_publisher_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "futures-eod-silver"
      }
    }
  })

  timeout {
    # 2 h ceiling. A five-day incremental for one source is minutes; the ceiling is
    # sized for the trade_year union + registered-partition publish on the widest
    # source (databento, ~10 roots), with margin.
    attempt_duration_seconds = 7200
  }

  # D-PR-7 / D-PR-37: the shared producer retry matrix (5 rules = the API cap).
  # Declared once at the top of this file; see that comment before changing anything.
  # T2b DOCTRINE EXCLUSION (sitting-2 skeptic, 2026-08-04): this jobdef PUBLISHES. The
  # D-PR-7 matrix is deliberately NOT stamped here -- a retried publisher re-runs its
  # write path, and the write-guard doctrine wants refusals surfaced, never re-driven.
  # (ResourceInitializationError precedes any write and WOULD be retry-safe; ratify that
  # nuance separately before narrowing this exclusion.) Pinned by the no-retry-on-a-
  # publishing-job doctrine test in test_futures_eod_cloud_legs.py.

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: browser-runner (playwright/Chromium page captures)
#
# ADOPTED 2026-08-05 (D-PR-24 follow-up): hand-registered rev 1 predates this block; the euronext
# MATIF capture leg of the ARMED futures_eod_free schedule (22:30Z MON-FRI) runs here because the
# worker image carries no browser. Mirrors rev 1 byte-for-byte (role/env/sizing/network/baked
# command) so the adoption is an ALIGNMENT, plus the two things rev 1 lacked:
#   - timeout 900s: captures measure 2-5 min; a hung Chromium render must die inside the fire,
#     not stall until the SFN gives up.
#   - the shared producer retry matrix: this is a raw-landing PRODUCER, not a publisher. The
#     fetch's own exit vocabulary maps cleanly onto it -- exit 7 (ChallengeFailed: the table
#     never rendered) and exit 1 (per-product failure) both fall to EXIT via the exit-code rule
#     and the terminal catch-all; only infra-class starts retry.
# ROLE = batch_job_role (raw landing only -- never the publisher role; the silver leg that
# follows in the same execution runs on the digest-pinned futures-eod-silver jobdef).
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "browser_runner" {
  count = var.browser_runner_image != "" ? 1 : 0

  name = "${var.project_name}-${var.environment}-browser-runner"
  type = "container"

  platform_capabilities = ["FARGATE"]

  deregister_on_new_revision = true

  container_properties = jsonencode({
    image = var.browser_runner_image

    command = ["-c", "print('override me')"]

    environment = [
      { name = "PYTHONPATH", value = "/app/src" },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket }
    ]

    jobRoleArn       = var.batch_job_role_arn
    executionRoleArn = var.batch_execution_role_arn

    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "4096" }
    ]

    networkConfiguration = { assignPublicIp = "ENABLED" }
    fargatePlatformConfiguration = { platformVersion = "LATEST" }
  })

  timeout {
    attempt_duration_seconds = 900
  }

  retry_strategy {
    attempts = local.producer_retry_attempts
    dynamic "evaluate_on_exit" {
      for_each = local.producer_retry_rules
      content {
        action           = evaluate_on_exit.value.action
        on_exit_code     = evaluate_on_exit.value.on_exit_code
        on_reason        = evaluate_on_exit.value.on_reason
        on_status_reason = evaluate_on_exit.value.on_status_reason
      }
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: USDA PSD bronze -> silver  (D-SG G1-1)
#
# WHY A DEDICATED JOBDEF. jobs/batch/psd_silver_task.py is the only leg in the estate that
# concatenates EVERY bronze release snapshot into one pandas frame. MEASURED 2026-08-16
# against the 8 live bronze partitions (30,536,582 bytes of parquet on S3): 16,735,546 rows,
# 2,518 MiB resident after load, PEAK RSS 8,685-9,997 MiB inside
# transform_psd_bronze_to_silver (concat :292 -> drop_duplicates :400 -> pivot_table :405).
# leviathan-dev-b3-flat-silver is 1 vCPU / 4096 MB and is SHARED with the fred, world_bank,
# nass, ams, icco, mpoc, sagis and cftc legs -- exactly the wrong place to put 16 GB.
# Live proof of the failure: Batch job 213aaaa7-bd2e-4fdc-b11c-3c40cdac66be (2026-08-13
# 18:04:21Z), "OutOfMemoryError: container killed due to memory usage", exit 137 at 31 s.
#
# 2 vCPU / 16384 MB is the Fargate MAXIMUM at 2 vCPU and gives 1.65x over the measured peak.
# IT IS NOT A PERMANENT ANSWER, and the arithmetic is written down so the next person does
# not have to re-derive it: fetch_usda_psd.py:121 stamps release_date=TODAY and this schedule
# fires on days 8-13, so bronze gains ~6 partitions a month and the peak grows ~1.2 GiB per
# partition. The G1-1b bounded-input rider in psd_silver_task._load_bronze (drop bronze
# partitions whose RAW zip ETag duplicates a newer one -- 6 of the 8 live partitions are two
# byte-identical vendor downloads) is what keeps this inside 16 GB past September.
#
# THIS JOBDEF PUBLISHES AND SELF-PROMOTES, WHICH IS WHY IT CARRIES THE PUBLISHER ROLE:
#   1. the promote leg re-runs the SAME transform with --publish-mode canonical, so it OOMs
#      on silver-publisher-runner's 1 vCPU / 4096 MB exactly like the shadow leg did --
#      repointing only the silver leg leaves the canonical write broken;
#   2. tests/unit/silver/test_gen_sfn_inputs.py::test_digest_pinned_producers_must_self_promote
#      requires any DIGEST-PINNED silver jobdef to be its family's promote_jobdef, and a
#      self-promote calls kms:Sign, which lives ONLY on module.iam.silver_publisher_role
#      (envs/dev/main.tf aws_iam_role_policy.silver_publisher_kms_sign). Same shape as
#      futures_eod_silver above.
#
# NO retry matrix, deliberately: the publishing-job doctrine that futures_eod_silver and
# pattern_records_sweep already carry. A retried publisher re-runs its write path.
# ---------------------------------------------------------------------------
locals {
  psd_silver_image = (
    var.psd_silver_image_digest == ""
    ? "${var.ecr_repository_url}:latest"
    : "${var.ecr_repository_url}@${var.psd_silver_image_digest}"
  )
}

resource "aws_batch_job_definition" "psd_silver" {
  count = var.silver_publisher_job_role_arn == "" ? 0 : 1

  name = "${var.project_name}-${var.environment}-psd-silver"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = local.psd_silver_image

    # Module form ([m]) because psd_silver_task does a defensive `jobs.*` import. The state
    # machine overrides this on every fire with the descriptor's command plus the stage's
    # --publish-mode, so the baked list is the MANUAL-run default, never the scheduled one --
    # and it is baked as `shadow` so an un-overridden fire can never touch canonical.
    command = [
      "-m", "jobs.batch.psd_silver_task",
      "--force-overwrite",
      "--publish-mode", "shadow"
    ]

    # The UNION of what the two legs carry today: b3-flat-silver:24 (AWS_REGION,
    # LEVIATHAN_BUCKET) plus silver-publisher-runner:24's PYTHONPATH, plus the KMS pair
    # futures_eod_silver bakes (inert unless the job is run with --publish-mode canonical).
    # LEVIATHAN_ENV is deliberately ABSENT: neither live leg sets it, and this change is
    # allowed to move memory, not environment.
    environment = [
      { name = "PYTHONPATH", value = "/app/src" },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "LEVIATHAN_APPROVAL_MODE", value = "kms" },
      { name = "LEVIATHAN_KMS_KEY_ID", value = local.publish_signer_alias }
    ]

    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "16384" }
    ]

    executionRoleArn = var.batch_execution_role_arn
    # The GATED writer (SILVER-F014), not batch_job_role -- see the header's point 2.
    jobRoleArn = var.silver_publisher_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "psd-silver"
      }
    }
  })

  timeout {
    # 1 h. The measured transform is ~4 min of CPU on 8 partitions; the ceiling covers load,
    # pivot and the shadow->validate->promote publish with wide margin. attemptDurationSeconds
    # is PER ATTEMPT and this jobdef has no retry, so 3600 s is also the whole-job ceiling.
    attempt_duration_seconds = 3600
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
