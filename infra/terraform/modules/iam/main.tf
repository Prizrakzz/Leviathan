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
# Bedrock invoke policy — allows Batch containers to call Claude via Amazon
# Bedrock: Haiku (text_to_graphrag chunking) and, since the GraphRAG serving
# provider moved to Bedrock, Sonnet 4.6 + Haiku 4.5 THROUGH the global.
# cross-region inference profiles (providers.py). Profile invocations are
# authorized against BOTH the profile ARN and the foundation-model ARNs in
# whichever region the profile routes to — hence the region-wildcarded FM
# ARNs. Still bedrock:InvokeModel only; no wildcard actions.
# ---------------------------------------------------------------------------
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "batch_job_bedrock" {
  statement {
    sid     = "BedrockInvokeServingModels"
    actions = ["bedrock:InvokeModel"]
    resources = [
      "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5*",
      "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6*",
      "arn:aws:bedrock:us-east-1:${data.aws_caller_identity.current.account_id}:inference-profile/global.anthropic.claude-sonnet-4-6",
      "arn:aws:bedrock:us-east-1:${data.aws_caller_identity.current.account_id}:inference-profile/global.anthropic.claude-haiku-4-5-20251001-v1:0",
    ]
  }

  # Required for Bedrock to auto-subscribe the role to the Anthropic model
  # on first use (resolves AccessDeniedException for aws-marketplace actions).
  statement {
    sid     = "BedrockMarketplaceSubscribe"
    actions = [
      "aws-marketplace:ViewSubscriptions",
      "aws-marketplace:Subscribe",
    ]
    resources = ["*"]
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

# ---------------------------------------------------------------------------
# SageMaker Training role — assumed by SageMaker Training Jobs to read the
# feature matrix, write MLflow artifacts, pull the trainer ECR image, and
# ship logs to CloudWatch.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "sagemaker_training_role" {
  name = "${var.project_name}-${var.environment}-sagemaker-training-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sagemaker.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# Full data lake access — training jobs read feature_matrix + catalog and
# write MLflow artifacts, all within the same bucket.
resource "aws_iam_role_policy_attachment" "sagemaker_training_role_s3" {
  role       = aws_iam_role.sagemaker_training_role.name
  policy_arn = aws_iam_policy.s3_data_lake_rw.arn
}

data "aws_iam_policy_document" "sagemaker_training_ecr_logs" {
  statement {
    sid = "ECRAuthToken"
    actions = [
      "ecr:GetAuthorizationToken",
    ]
    # GetAuthorizationToken is account-level; cannot be scoped to a repo ARN.
    resources = ["*"]
  }

  statement {
    sid = "ECRPullTrainerImage"
    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchCheckLayerAvailability",
    ]
    resources = [var.ecr_trainer_repository_arn]
  }

  statement {
    sid = "CloudWatchTrainingLogs"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:*:*:log-group:/aws/sagemaker/TrainingJobs*"]
  }
}

resource "aws_iam_policy" "sagemaker_training_ecr_logs" {
  name        = "${var.project_name}-${var.environment}-sagemaker-training-ecr-logs"
  description = "SageMaker training role: ECR pull for leviathan-trainer + CloudWatch log delivery."
  policy      = data.aws_iam_policy_document.sagemaker_training_ecr_logs.json
}

resource "aws_iam_role_policy_attachment" "sagemaker_training_role_ecr_logs" {
  role       = aws_iam_role.sagemaker_training_role.name
  policy_arn = aws_iam_policy.sagemaker_training_ecr_logs.arn
}