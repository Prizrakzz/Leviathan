locals {
  script_base = "s3://${var.bucket_name}/glue-scripts"
  temp_dir    = "s3://${var.bucket_name}/glue-temp"

  glue_scripts = {
    "raw_to_bronze_nasa_power"    = "${path.module}/../../../../jobs/glue/raw_to_bronze_nasa_power.py"
    "raw_to_bronze_faostat"       = "${path.module}/../../../../jobs/glue/raw_to_bronze_faostat.py"
    "bronze_to_silver_nasa_power" = "${path.module}/../../../../jobs/glue/bronze_to_silver_nasa_power.py"
    "bronze_to_silver_faostat"    = "${path.module}/../../../../jobs/glue/bronze_to_silver_faostat.py"
  }

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

  max_capacity = 1.0

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

  max_capacity = 1.0

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

  max_capacity = 1.0

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

  max_capacity = 1.0

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
# S3 objects: Glue scripts + leviathan wheel
# etag = filemd5 ensures re-upload whenever the source file changes.
# ---------------------------------------------------------------------------

resource "aws_s3_object" "glue_scripts" {
  for_each = local.glue_scripts

  bucket = var.bucket_name
  key    = "glue-scripts/${each.key}.py"
  source = each.value
  etag   = filemd5(each.value)

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_object" "leviathan_whl" {
  bucket = var.bucket_name
  key    = "glue-libs/leviathan-0.1.0-py3-none-any.whl"
  source = "${path.module}/../../../../dist/leviathan-0.1.0-py3-none-any.whl"
  etag   = filemd5("${path.module}/../../../../dist/leviathan-0.1.0-py3-none-any.whl")

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
