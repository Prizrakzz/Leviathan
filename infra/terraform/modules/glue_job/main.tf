# ---------------------------------------------------------------------------
# Generic Glue Python Shell job module
#
# Creates:
#   - aws_glue_job  (pythonshell, Glue 3.0, Python 3.9)
#   - aws_s3_object (uploads the script; triggers re-upload on content change)
#
# Log groups are managed by the cloudwatch module to avoid destructive state
# changes to existing CloudWatch resources.
# ---------------------------------------------------------------------------

resource "aws_glue_job" "this" {
  name         = var.job_name
  role_arn     = var.glue_role_arn
  glue_version = "3.0"

  command {
    name            = "pythonshell"
    python_version  = "3.9"
    script_location = "s3://${var.bucket_name}/glue-scripts/${basename(var.script_local_path)}"
  }

  default_arguments = merge(
    {
      "--bucket"              = var.bucket_name
      "--aws_region"          = var.aws_region
      "--enable-job-insights" = "true"
      "--job-language"        = "python"
      "--TempDir"             = "s3://${var.bucket_name}/glue-temp"
      "--extra-py-files"      = "s3://${var.bucket_name}/glue-libs/bootstrap.py"
    },
    var.extra_default_args,
  )

  max_capacity = var.max_capacity

  execution_property {
    max_concurrent_runs = var.max_concurrent_runs
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_object" "script" {
  bucket = var.bucket_name
  key    = "glue-scripts/${basename(var.script_local_path)}"
  source = var.script_local_path
  etag   = filemd5(var.script_local_path)

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
