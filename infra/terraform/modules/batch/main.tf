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
    image = "${var.ecr_repository_url}:latest"

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
    image = "${var.ecr_repository_url}:latest"

    command = [
      "jobs/batch/chirps_to_bronze_task.py",
      "--commodity",  "Ref::commodity",
      "--year",       "Ref::year",
      "--bucket",     "Ref::bucket",
      "--aws_region", "Ref::aws_region"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET",             value = var.leviathan_bucket },
      { name = "AWS_REGION",                   value = var.aws_region },
      { name = "LEVIATHAN_ENV",                value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU",   value = "0.5" },
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
    image = "${var.ecr_repository_url}:latest"

    command = [
      "jobs/orchestrate/orchestrate_backfill.py",
      "--start-year",  "Ref::start_year",
      "--end-year",    "Ref::end_year",
      "--commodities", "Ref::commodities"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION",       value = var.aws_region },
      { name = "LEVIATHAN_ENV",    value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU",   value = "0.5" },
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
    attempt_duration_seconds = 57600  # 16 h ceiling; actual runtime ~36 min
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

  parameters = {
    commodity  = "corn_cbot"
    bucket     = var.leviathan_bucket
    aws_region = var.aws_region
  }

  container_properties = jsonencode({
    image = "${var.ecr_repository_url}:latest"

    command = [
      "jobs/batch/bronze_to_silver_chirps_task.py",
      "--commodity",  "Ref::commodity",
      "--bucket",     "Ref::bucket",
      "--aws_region", "Ref::aws_region"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION",       value = var.aws_region },
      { name = "LEVIATHAN_ENV",    value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU",   value = "2" },
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
    image = "${var.ecr_repository_url}:latest"

    command = [
      "jobs/ingest/fetch_sagis_cec.py",
      "--skip-existing-s3"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION",       value = var.aws_region },
      { name = "LEVIATHAN_ENV",    value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU",   value = "0.25" },
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
    attempt_duration_seconds = 3600  # 1 h ceiling; each ~80-120-file chunk runs in ~5-8 min
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
    image = "${var.ecr_repository_url}:latest"

    # Default command — overridden per-task via containerOverrides at submit time.
    command = [
      "jobs/ingest/fetch_usda_wasde.py",
      "--skip-existing-s3",
      "--year-from", "1973",
      "--year-to",   "2026"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION",       value = var.aws_region },
      { name = "LEVIATHAN_ENV",    value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU",   value = "0.25" },
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
    attempt_duration_seconds = 3600  # 1 h ceiling; each chunk ~5-8 min
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
# ---------------------------------------------------------------------------

resource "aws_batch_job_definition" "gain_backfill" {
  name = "${var.project_name}-${var.environment}-gain-backfill"
  type = "container"

  platform_capabilities = ["FARGATE"]

  parameters = {}

  container_properties = jsonencode({
    image = "${var.ecr_repository_url}:latest"

    # Default command — overridden per-task via containerOverrides at submit time.
    command = [
      "jobs/batch/gain_backfill_task.py",
      "--commodity-name", "wheat",
      "--commodity-id",   "15",
      "--target-countries", "US,FR,AU,CA,UA,RU,IN,PK,EG,AR,CN,DE,PL,TR",
      "--bucket", "${var.leviathan_bucket}",
      "--aws-region", "${var.aws_region}",
      "--skip-existing-s3",
      "--sleep-seconds", "2"
    ]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION",       value = var.aws_region },
      { name = "LEVIATHAN_ENV",    value = var.environment }
    ]

    resourceRequirements = [
      { type = "VCPU",   value = "1" },
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
    attempt_duration_seconds = 21600  # 6 h ceiling
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
