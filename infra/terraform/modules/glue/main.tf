locals {
  script_base = "s3://${var.bucket_name}/glue-scripts"
  temp_dir    = "s3://${var.bucket_name}/glue-temp"

  common_default_args = {
    "--bucket"              = var.bucket_name
    "--aws_region"          = var.aws_region
    "--commodity"           = "cocoa"
    "--enable-job-insights" = "true"
    "--job-language"        = "python"
    "--TempDir"             = local.temp_dir
  }
}

# ---------------------------------------------------------------------------
# raw → bronze: NASA POWER
# ---------------------------------------------------------------------------

resource "aws_glue_job" "raw_to_bronze_nasa_power" {
  name         = "${var.project_name}-${var.environment}-raw-to-bronze-nasa-power"
  role_arn     = var.glue_job_role_arn
  glue_version = "3.0"

  command {
    name            = "pythonshell"
    python_version  = "3.9"
    script_location = "${local.script_base}/raw_to_bronze_nasa_power.py"
  }

  default_arguments = merge(local.common_default_args, {
    "--ingest_date" = formatdate("YYYY-MM-DD", timestamp())
  })

  max_capacity = 0.0625

  execution_property {
    max_concurrent_runs = 1
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# raw → bronze: FAOSTAT
# ---------------------------------------------------------------------------

resource "aws_glue_job" "raw_to_bronze_faostat" {
  name         = "${var.project_name}-${var.environment}-raw-to-bronze-faostat"
  role_arn     = var.glue_job_role_arn
  glue_version = "3.0"

  command {
    name            = "pythonshell"
    python_version  = "3.9"
    script_location = "${local.script_base}/raw_to_bronze_faostat.py"
  }

  default_arguments = merge(local.common_default_args, {
    "--ingest_date" = formatdate("YYYY-MM-DD", timestamp())
    "--s3_raw_key"  = "raw/production/source=faostat/commodity=cocoa/Production_Crops_Livestock_E_All_Data_Normalized.zip"
  })

  max_capacity = 0.0625

  execution_property {
    max_concurrent_runs = 1
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# bronze → silver: NASA POWER
# ---------------------------------------------------------------------------

resource "aws_glue_job" "bronze_to_silver_nasa_power" {
  name         = "${var.project_name}-${var.environment}-bronze-to-silver-nasa-power"
  role_arn     = var.glue_job_role_arn
  glue_version = "3.0"

  command {
    name            = "pythonshell"
    python_version  = "3.9"
    script_location = "${local.script_base}/bronze_to_silver_nasa_power.py"
  }

  default_arguments = local.common_default_args

  max_capacity = 0.0625

  execution_property {
    max_concurrent_runs = 1
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# bronze → silver: FAOSTAT
# ---------------------------------------------------------------------------

resource "aws_glue_job" "bronze_to_silver_faostat" {
  name         = "${var.project_name}-${var.environment}-bronze-to-silver-faostat"
  role_arn     = var.glue_job_role_arn
  glue_version = "3.0"

  command {
    name            = "pythonshell"
    python_version  = "3.9"
    script_location = "${local.script_base}/bronze_to_silver_faostat.py"
  }

  default_arguments = local.common_default_args

  max_capacity = 0.0625

  execution_property {
    max_concurrent_runs = 1
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
