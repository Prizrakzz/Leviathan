# ---------------------------------------------------------------------------
# Glue jobs — each job is managed by the generic glue_job child module.
#
# WARNING: Replacing the four aws_glue_job resources with module calls changes
# the Terraform resource addresses from e.g.
#   module.glue.aws_glue_job.raw_to_bronze_nasa_power
# to
#   module.glue.module.raw_to_bronze_nasa_power.aws_glue_job.this
#
# Terraform will plan a destroy + create for each job (same AWS names, so the
# actual Glue job names are preserved). Apply when no jobs are scheduled.
# Run `terraform state mv` before apply to avoid the brief downtime if needed.
# ---------------------------------------------------------------------------

locals {
  scripts_dir = "${path.module}/../../../../jobs/glue"
}

# ---------------------------------------------------------------------------
# raw → bronze: NASA POWER
# ---------------------------------------------------------------------------

module "raw_to_bronze_nasa_power" {
  source = "../glue_job"

  job_name          = "${var.project_name}-${var.environment}-raw-to-bronze-nasa-power"
  script_local_path = "${local.scripts_dir}/raw_to_bronze_nasa_power.py"
  bucket_name       = var.bucket_name
  glue_role_arn     = var.glue_job_role_arn
  aws_region        = var.aws_region
  project_name      = var.project_name
  environment       = var.environment

  extra_default_args = {
    "--ingest_date" = formatdate("YYYY-MM-DD", timestamp())
  }
}

# ---------------------------------------------------------------------------
# raw → bronze: FAOSTAT
# ---------------------------------------------------------------------------

module "raw_to_bronze_faostat" {
  source = "../glue_job"

  job_name          = "${var.project_name}-${var.environment}-raw-to-bronze-faostat"
  script_local_path = "${local.scripts_dir}/raw_to_bronze_faostat.py"
  bucket_name       = var.bucket_name
  glue_role_arn     = var.glue_job_role_arn
  aws_region        = var.aws_region
  project_name      = var.project_name
  environment       = var.environment

  extra_default_args = {
    "--ingest_date" = formatdate("YYYY-MM-DD", timestamp())
    "--s3_raw_key"  = "raw/production/source=faostat/commodity=cocoa/Production_Crops_Livestock_E_All_Data_Normalized.zip"
  }
}

# ---------------------------------------------------------------------------
# bronze → silver: NASA POWER
# ---------------------------------------------------------------------------

module "bronze_to_silver_nasa_power" {
  source = "../glue_job"

  job_name          = "${var.project_name}-${var.environment}-bronze-to-silver-nasa-power"
  script_local_path = "${local.scripts_dir}/bronze_to_silver_nasa_power.py"
  bucket_name       = var.bucket_name
  glue_role_arn     = var.glue_job_role_arn
  aws_region        = var.aws_region
  project_name      = var.project_name
  environment       = var.environment
}

# ---------------------------------------------------------------------------
# bronze → silver: FAOSTAT
# ---------------------------------------------------------------------------

module "bronze_to_silver_faostat" {
  source = "../glue_job"

  job_name          = "${var.project_name}-${var.environment}-bronze-to-silver-faostat"
  script_local_path = "${local.scripts_dir}/bronze_to_silver_faostat.py"
  bucket_name       = var.bucket_name
  glue_role_arn     = var.glue_job_role_arn
  aws_region        = var.aws_region
  project_name      = var.project_name
  environment       = var.environment
}

# ---------------------------------------------------------------------------
# raw → bronze: USDA FAS ESR
# ---------------------------------------------------------------------------

module "raw_to_bronze_usda_esr" {
  source = "../glue_job"

  job_name          = "${var.project_name}-${var.environment}-raw-to-bronze-usda-esr"
  script_local_path = "${local.scripts_dir}/raw_to_bronze_usda_esr.py"
  bucket_name       = var.bucket_name
  glue_role_arn     = var.glue_job_role_arn
  aws_region        = var.aws_region
  project_name      = var.project_name
  environment       = var.environment

  extra_default_args = {
    "--ingest_date" = formatdate("YYYY-MM-DD", timestamp())
  }
}

# ---------------------------------------------------------------------------
# S3: leviathan wheel and bootstrap helper
# (script uploads handled inside each glue_job module)
# ---------------------------------------------------------------------------

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

resource "aws_s3_object" "glue_bootstrap" {
  bucket = var.bucket_name
  key    = "glue-libs/bootstrap.py"
  source = "${path.module}/../../../../jobs/glue/bootstrap.py"
  etag   = filemd5("${path.module}/../../../../jobs/glue/bootstrap.py")

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

