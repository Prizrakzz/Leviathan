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
      "jobs/backfill_raw_nasa_power.py",
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
      "jobs/orchestrate_backfill.py",
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

resource "aws_cloudwatch_log_group" "batch" {
  name              = "/aws/batch/${var.project_name}-${var.environment}"
  retention_in_days = 30

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
