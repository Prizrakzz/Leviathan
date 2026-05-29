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

  retry_strategy {
    attempts = 3

    evaluate_on_exit {
      on_exit_code = "137"
      action       = "RETRY"
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
    image = "${var.ecr_repository_url}:latest"

    # Default command — overridden per-task via containerOverrides at submit time.
    command = [
      "jobs/ingest/fetch_usda_wap.py",
      "--skip-existing-s3",
      "--year-from", "2002",
      "--year-to",   "2026",
      "--sleep-seconds", "1.5"
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
        "awslogs-stream-prefix" = "usda-wap-raw-backfill"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600  # 1 h ceiling; each chunk ≈ 3 min
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
    image = "${var.ecr_repository_url}:latest"

    command = [
      "jobs/batch/cpc_soil_to_raw_task.py",
      "--year",       "Ref::year",
      "--variable",   "Ref::variable",
      "--bucket",     "Ref::bucket",
      "--aws_region", "Ref::aws_region"
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
        "awslogs-stream-prefix" = "cpc-soil-to-raw"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 7200  # 2 h ceiling; normal run ~5–10 min
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
    image = "${var.ecr_repository_url}:latest"

    command = [
      "jobs/batch/cpc_raw_to_bronze_task.py",
      "--year",       "Ref::year",
      "--variable",   "Ref::variable",
      "--bucket",     "Ref::bucket",
      "--aws_region", "Ref::aws_region"
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
        "awslogs-stream-prefix" = "cpc-soil-raw-to-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 7200  # 2 h ceiling; normal run ~5–15 min
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
    image = "${var.ecr_repository_url}:latest"

    command = [
      "jobs/batch/cpc_bronze_to_silver_task.py",
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
        "awslogs-stream-prefix" = "cpc-soil-bronze-to-silver"
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
    image = "${var.ecr_repository_url}:latest"

    command = [
      "jobs/batch/modis_ndvi_raw_to_bronze_task.py",
      "--run_id",     "Ref::run_id",
      "--group",      "Ref::group",
      "--bucket",     "Ref::bucket",
      "--aws_region", "Ref::aws_region"
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
        "awslogs-stream-prefix" = "modis-ndvi-raw-to-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 7200  # 2 h ceiling; normal run < 5 min
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
    image = "${var.ecr_repository_url}:latest"

    command = [
      "jobs/batch/modis_ndvi_bronze_to_silver_task.py",
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
        "awslogs-stream-prefix" = "modis-ndvi-bronze-to-silver"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600  # 1 h ceiling; normal run < 5 min
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
    image = "${var.ecr_repository_url}:latest"

    command = ["jobs/batch/psd_task.py"]

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
        "awslogs-stream-prefix" = "usda-psd-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
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
    image = "${var.ecr_repository_url}:latest"

    command = ["jobs/batch/fgis_task.py"]

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
        "awslogs-stream-prefix" = "usda-fgis-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
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
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "world_bank_pink_sheet_bronze" {
  name = "${var.project_name}-${var.environment}-world-bank-pink-sheet-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = "${var.ecr_repository_url}:latest"

    command = ["jobs/batch/pink_sheet_task.py"]

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
        "awslogs-stream-prefix" = "world-bank-pink-sheet-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
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
    image = "${var.ecr_repository_url}:latest"

    command = ["jobs/batch/nass_task.py", "--series", "all"]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION",       value = var.aws_region },
      { name = "LEVIATHAN_ENV",    value = var.environment }
    ]

    # 8.9 M annual rows + 793 K progress rows loaded into object-dtype pandas
    # DataFrames, then 16 concurrent pyarrow Arrow conversions for shard writes.
    # Peak RSS exceeds 8 GiB at 1 vCPU; 2 vCPU + 16 GiB is the next Fargate tier.
    resourceRequirements = [
      { type = "VCPU",   value = "2" },
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
    image = "${var.ecr_repository_url}:latest"

    command = ["jobs/batch/conab_xls_task.py"]

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
        "awslogs-stream-prefix" = "conab-xls-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
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
resource "aws_batch_job_definition" "fnc_excel_bronze" {
  name = "${var.project_name}-${var.environment}-fnc-excel-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = "${var.ecr_repository_url}:latest"

    command = ["jobs/batch/fnc_excel_task.py"]

    environment = [
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "AWS_REGION",       value = var.aws_region },
      { name = "LEVIATHAN_ENV",    value = var.environment }
    ]

    # openpyxl loads the entire workbook object graph at ExcelFile() open
    # time; 1024 MiB is insufficient for the larger FNC bulk Excel files.
    # 0.25 vCPU supports up to 2048 MiB on Fargate.
    resourceRequirements = [
      { type = "VCPU",   value = "0.25" },
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

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Job definition: MPOB BEPI HTML raw → bronze
# Single task reads all HTML keys under raw/production/source=mpob/ and
# writes per-release Parquet (annual summary + monthly tables).
# Sizing: 0.5 vCPU / 1024 MB — Fargate minimum for 0.5 vCPU.
# Timeout: 1 h ceiling; normal run < 5 min.
# ---------------------------------------------------------------------------
resource "aws_batch_job_definition" "mpob_bronze" {
  name = "${var.project_name}-${var.environment}-mpob-bronze"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = "${var.ecr_repository_url}:latest"

    command = ["jobs/batch/mpob_task.py", "--release-type", "all"]

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
        "awslogs-stream-prefix" = "mpob-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
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
    image = "${var.ecr_repository_url}:latest"

    command = ["jobs/batch/unica_task.py"]

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
        "awslogs-stream-prefix" = "unica-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 3600
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

  container_properties = jsonencode({
    image = "${var.ecr_repository_url}:latest"

    command = ["jobs/batch/esr_task.py"]

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
        "awslogs-stream-prefix" = "usda-esr-bronze"
      }
    }
  })

  timeout {
    attempt_duration_seconds = 7200  # 2 h ceiling; 370 JSON files
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
