locals {
  # Extract bucket name from ARN (arn:aws:s3:::bucket-name)
  bucket_name = element(split(":::", var.bucket_arn), 1)
}

data "aws_iam_policy_document" "s3_data_lake_rw" {
  statement {
    sid = "ListDataLakeBucket"

    actions = [
      "s3:ListBucket"
    ]

    resources = [
      var.bucket_arn
    ]
  }

  statement {
    sid = "ReadWriteDataLakeObjects"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]

    resources = [
      "${var.bucket_arn}/*"
    ]
  }
}

resource "aws_iam_policy" "s3_data_lake_rw" {
  name        = "${var.project_name}-${var.environment}-s3-data-lake-rw"
  description = "Read/write access to the Leviathan S3 data lake bucket."
  policy      = data.aws_iam_policy_document.s3_data_lake_rw.json
}

# ---------------------------------------------------------------------------
# Batch execution role — assumed by Fargate to pull ECR images and write logs
# ---------------------------------------------------------------------------

resource "aws_iam_role" "batch_execution_role" {
  name = "${var.project_name}-${var.environment}-batch-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ecs-tasks.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "batch_execution_role_ecs" {
  role       = aws_iam_role.batch_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ---------------------------------------------------------------------------
# Batch job role — assumed by the container code to write to S3
# ---------------------------------------------------------------------------

resource "aws_iam_role" "batch_job_role" {
  name = "${var.project_name}-${var.environment}-batch-job-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ecs-tasks.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "batch_job_role_s3" {
  role       = aws_iam_role.batch_job_role.name
  policy_arn = aws_iam_policy.s3_data_lake_rw.arn
}

# Orchestrator container needs to submit + poll child Batch jobs and trigger Glue.
data "aws_iam_policy_document" "batch_orchestrator" {
  statement {
    sid = "BatchSubmitAndDescribe"
    actions = [
      "batch:SubmitJob",
      "batch:DescribeJobs",
      "batch:TerminateJob",
    ]
    resources = ["*"]
  }

  statement {
    sid = "GlueStartAndDescribe"
    actions = [
      "glue:StartJobRun",
      "glue:GetJobRun",
      "glue:BatchStopJobRun",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "batch_orchestrator" {
  name        = "${var.project_name}-${var.environment}-batch-orchestrator"
  description = "Allows the Batch orchestrator container to submit Batch jobs and trigger Glue runs."
  policy      = data.aws_iam_policy_document.batch_orchestrator.json
}

resource "aws_iam_role_policy_attachment" "batch_job_role_orchestrator" {
  role       = aws_iam_role.batch_job_role.name
  policy_arn = aws_iam_policy.batch_orchestrator.arn
}

# ---------------------------------------------------------------------------
# Bedrock invoke policy — allows Batch containers to call Claude Haiku via
# Amazon Bedrock for the text_to_graphrag extraction pipeline.
# Scoped to the Haiku foundation model in us-east-1 only.
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "batch_job_bedrock" {
  statement {
    sid     = "BedrockInvokeHaiku"
    actions = ["bedrock:InvokeModel"]
    resources = [
      "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
    ]
  }
}

resource "aws_iam_policy" "batch_job_bedrock" {
  name        = "${var.project_name}-${var.environment}-batch-job-bedrock"
  description = "Allows Batch job containers to invoke Claude Haiku via Bedrock (text_to_graphrag)."
  policy      = data.aws_iam_policy_document.batch_job_bedrock.json
}

resource "aws_iam_role_policy_attachment" "batch_job_role_bedrock" {
  role       = aws_iam_role.batch_job_role.name
  policy_arn = aws_iam_policy.batch_job_bedrock.arn
}

# ---------------------------------------------------------------------------
# Glue job role — assumed by Glue Python Shell jobs to read/write S3
# ---------------------------------------------------------------------------

resource "aws_iam_role" "glue_job_role" {
  name = "${var.project_name}-${var.environment}-glue-job-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "glue.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "glue_job_role_glue_service" {
  role       = aws_iam_role.glue_job_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy_attachment" "glue_job_role_s3" {
  role       = aws_iam_role.glue_job_role.name
  policy_arn = aws_iam_policy.s3_data_lake_rw.arn
}

# ---------------------------------------------------------------------------
# Athena + Glue catalog permissions for the Glue job role
# Allows validation scripts running under this role to query Athena and
# manage the leviathan_dev catalog database/tables.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "athena_validation" {
  statement {
    sid = "AthenaQueryExecution"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution",
      "athena:GetWorkGroup",
    ]
    resources = ["*"]
  }

  statement {
    sid = "AthenaResultsS3"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["arn:aws:s3:::${local.bucket_name}/athena-results/*"]
  }

  statement {
    sid = "GlueCatalogAccess"
    actions = [
      "glue:CreateDatabase",
      "glue:GetDatabase",
      "glue:CreateTable",
      "glue:UpdateTable",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartitions",
    ]
    resources = ["*"]
  }

  statement {
    sid = "CloudWatchCustomMetrics"
    actions = [
      "cloudwatch:PutMetricData",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "athena_validation" {
  name        = "${var.project_name}-${var.environment}-athena-validation"
  description = "Allows Glue job role to run Athena queries and manage Glue catalog for pipeline validation."
  policy      = data.aws_iam_policy_document.athena_validation.json
}

resource "aws_iam_role_policy_attachment" "glue_job_role_athena" {
  role       = aws_iam_role.glue_job_role.name
  policy_arn = aws_iam_policy.athena_validation.arn
}