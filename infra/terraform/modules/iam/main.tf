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
# Secrets Manager read for the execution role (Phase D D-W1). The weekly ESR
# fetch job (batch module usda_esr_fetch) mounts FAS_API_KEY via secrets/valueFrom;
# the ECS agent that injects it runs under the EXECUTION role, so the grant lands
# here, NOT on the job role. Scoped to the FAS secret ARN (trailing -* matches the
# Secrets Manager random 6-char suffix). count-gated: no grant until the ARN is
# wired. USER-GATED: the secret leviathan/dev/fas-api-key does not exist yet; this
# codifies the grant the way the batch_job_role Athena grant at :297 codified an
# earlier out-of-band CLI grant. (The existing EVIDENCE_PG_DSN serving mount still
# relies on an out-of-band GetSecretValue grant -- not reconciled here.)
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "batch_execution_fas_secret" {
  count = var.fas_api_key_secret_arn != "" ? 1 : 0
  statement {
    sid       = "ReadFasApiKeySecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["${var.fas_api_key_secret_arn}-*"]
  }
}

resource "aws_iam_policy" "batch_execution_fas_secret" {
  count       = var.fas_api_key_secret_arn != "" ? 1 : 0
  name        = "${var.project_name}-${var.environment}-batch-execution-fas-secret"
  description = "Lets the Batch/ECS execution role inject the FAS_API_KEY secret into the weekly ESR fetch task."
  policy      = data.aws_iam_policy_document.batch_execution_fas_secret[0].json
}

resource "aws_iam_role_policy_attachment" "batch_execution_role_fas_secret" {
  count      = var.fas_api_key_secret_arn != "" ? 1 : 0
  role       = aws_iam_role.batch_execution_role.name
  policy_arn = aws_iam_policy.batch_execution_fas_secret[0].arn
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
    sid = "BedrockInvokeServingModels"
    # InvokeModelWithResponseStream added for the streamed note synthesis (serving_call_stream) — the UI
    # renders the note token-by-token instead of blocking ~53s on the full completion.
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [
      "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5*",
      "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6*",
      "arn:aws:bedrock:us-east-1:${data.aws_caller_identity.current.account_id}:inference-profile/global.anthropic.claude-sonnet-4-6",
      "arn:aws:bedrock:us-east-1:${data.aws_caller_identity.current.account_id}:inference-profile/global.anthropic.claude-haiku-4-5-20251001-v1:0",
    ]
  }

  # Managed Cohere Rerank (bedrock-agent-runtime Rerank) — replaces the CPU bge cross-encoder in serving
  # (rankers._bedrock_rerank_scores). Cuts the L2 walk's ~100s CPU rerank to sub-second.
  # NOTE: bedrock:Rerank does NOT authorize against the foundation-model ARN the way InvokeModel does — a
  # model-scoped resource yields AccessDenied — so the action is granted on "*" (a read-only scoring call);
  # InvokeModel stays scoped to the rerank model.
  statement {
    sid       = "BedrockRerank"
    actions   = ["bedrock:Rerank"]
    resources = ["*"]
  }

  statement {
    sid       = "BedrockRerankInvokeModel"
    actions   = ["bedrock:InvokeModel"]
    resources = ["arn:aws:bedrock:*::foundation-model/cohere.rerank-v3-5*"]
  }

  # Required for Bedrock to auto-subscribe the role to the Anthropic model
  # on first use (resolves AccessDeniedException for aws-marketplace actions).
  statement {
    sid = "BedrockMarketplaceSubscribe"
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

# The GraphRAG serving ECS task reuses the Batch job role and hits Athena via the
# numbers agent + the /v1/series and /v1/convergence endpoints. Codify that here
# so serving no longer depends on an out-of-band (CLI-added) Athena grant.
resource "aws_iam_role_policy_attachment" "batch_job_role_athena" {
  role       = aws_iam_role.batch_job_role.name
  policy_arn = aws_iam_policy.athena_validation.arn
}

# Stage 4: the serving task's store.py (durable terminal-store) + session.py (graphrag-sessions) read/write.
# Gated on table ARNs being passed (empty list = no policy, so this stays a no-op until Stage 4).
data "aws_iam_policy_document" "terminal_dynamodb" {
  count = length(var.dynamodb_table_arns) > 0 ? 1 : 0
  statement {
    sid = "TerminalStoreRW"
    actions = [
      "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
      "dynamodb:Query", "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem",
    ]
    resources = var.dynamodb_table_arns
  }
}

resource "aws_iam_policy" "terminal_dynamodb" {
  count       = length(var.dynamodb_table_arns) > 0 ? 1 : 0
  name        = "${var.project_name}-${var.environment}-terminal-dynamodb-rw"
  description = "Serving task RW on the terminal-store + graphrag-sessions DynamoDB tables."
  policy      = data.aws_iam_policy_document.terminal_dynamodb[0].json
}

resource "aws_iam_role_policy_attachment" "batch_job_role_dynamodb" {
  count      = length(var.dynamodb_table_arns) > 0 ? 1 : 0
  role       = aws_iam_role.batch_job_role.name
  policy_arn = aws_iam_policy.terminal_dynamodb[0].arn
}

# ---------------------------------------------------------------------------
# P3 notifications job role — DEDICATED (Phase 8 SECTION III). The daily
# morning-brief job must enumerate user profiles (dynamodb:Scan), but the
# internet-facing serving ECS task REUSES batch_job_role — so Scan must NEVER
# land on the shared terminal_dynamodb policy (a serving-side compromise would
# gain cross-user reads of every profile/thread/notification). This role holds
# Scan scoped to the ONE store table; serving keeps batch_job_role without it.
# Reuses the shared non-dynamo grants (S3 for the live_events snapshot, Bedrock
# for the Haiku extraction) via the same managed policies.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "notifications_job" {
  count = var.notifications_store_table_arn != "" ? 1 : 0
  name  = "${var.project_name}-${var.environment}-notifications-job-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

data "aws_iam_policy_document" "notifications_dynamo" {
  count = var.notifications_store_table_arn != "" ? 1 : 0
  statement {
    sid = "NotificationsStoreScanRW"
    actions = [
      "dynamodb:Scan", # profile enumeration — the ONE grant serving must never hold
      "dynamodb:Query", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
    ]
    resources = [var.notifications_store_table_arn] # the store table ONLY (not sessions)
  }
}

resource "aws_iam_policy" "notifications_dynamo" {
  count       = var.notifications_store_table_arn != "" ? 1 : 0
  name        = "${var.project_name}-${var.environment}-notifications-dynamo"
  description = "P3 daily-digest job: Scan-scoped RW on the terminal-store table only."
  policy      = data.aws_iam_policy_document.notifications_dynamo[0].json
}

resource "aws_iam_role_policy_attachment" "notifications_job_dynamo" {
  count      = var.notifications_store_table_arn != "" ? 1 : 0
  role       = aws_iam_role.notifications_job[0].name
  policy_arn = aws_iam_policy.notifications_dynamo[0].arn
}

resource "aws_iam_role_policy_attachment" "notifications_job_s3" {
  count      = var.notifications_store_table_arn != "" ? 1 : 0
  role       = aws_iam_role.notifications_job[0].name
  policy_arn = aws_iam_policy.s3_data_lake_rw.arn # nf.snapshot -> graphrag_evidence/live_events/
}

resource "aws_iam_role_policy_attachment" "notifications_job_bedrock" {
  count      = var.notifications_store_table_arn != "" ? 1 : 0
  role       = aws_iam_role.notifications_job[0].name
  policy_arn = aws_iam_policy.batch_job_bedrock.arn # enum-locked Haiku extraction (bedrock lane)
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

# ===========================================================================
# SILVER-F014 (Milestone R1) — two-role validator / publisher separation.
#
# Replaces the original's five overweight roles (C-BETTER-3) with exactly two
# silver-readiness identities, and keeps table-mutation OFF the serving/general
# Batch roles by design (a follow-up hardening item — see R1_F014_iam_gate.md —
# strips glue:CreateTable/UpdateTable from the shared athena-validation policy;
# not done here because serving reuses that policy for GetTable/GetPartitions).
#
#   * validator  — READ-ONLY. Glue catalog reads, S3 object/version + Inventory
#                  reads, Athena RESULTS inspection (NO StartQueryExecution — the
#                  validator uses parquet footers, never Athena, so it can never
#                  trip the projection-table LIST storm / INV-3).
#   * publisher  — the single gated deployer. Base grant: GetTable/GetPartition(s)
#                  + Create/BatchCreatePartition on the approved dev DB, and
#                  S3 Get/Put/List on silver/ + gold/. TWO fail-closed flags gate
#                  the rest, both DEFAULT-DENY:
#                    - var.silver_canonical_publish_approved (default false):
#                      while false an EXPLICIT DENY on canonical silver/ writes
#                      (S3 + Glue partition/table mutation on silver_* tables) is
#                      attached; a signed approval flips the flag to drop it.
#                    - var.publisher_repair_enabled (default false): the
#                      UpdatePartition / Delete / prune "repair" capability is a
#                      FLAG (not a separate role) — attached only when true.
#
# Role NAMES are the single source of truth shared with the code-side publish
# guard: leviathan.common.constants.SILVER_{VALIDATOR,PUBLISHER}_ROLE_NAME are
# built as "leviathan-dev-silver-{validator,publisher}" == the names below.
# ===========================================================================

data "aws_region" "current" {}

locals {
  # Approved Glue database ("leviathan_dev") + the canonical catalog/table ARNs.
  glue_database_name = "${var.project_name}_${var.environment}"
  glue_catalog_arn   = "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:catalog"
  glue_database_arn  = "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:database/${local.glue_database_name}"
  glue_tables_arn    = "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${local.glue_database_name}/*"
  # The canonical silver_* tables whose mutation is denied until the approval flips.
  glue_silver_tables_arn = "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${local.glue_database_name}/silver_*"
}

# ---------------------------------------------------------------------------
# Validator role — READ-ONLY (assumed by the F016 validation Batch/Fargate job;
# CI-OIDC trust is layered on in F016, not here).
# ---------------------------------------------------------------------------
resource "aws_iam_role" "silver_validator" {
  name = "${var.project_name}-${var.environment}-silver-validator"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Role        = "silver-validator"
  }
}

data "aws_iam_policy_document" "silver_validator" {
  # Glue catalog — read every shape the validator reconciles (columns/types/
  # locations/table-properties/partitions/versions), never mutate.
  statement {
    sid = "GlueCatalogReadOnly"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetTableVersion",
      "glue:GetTableVersions",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:BatchGetPartition",
      "glue:GetCatalogImportStatus",
    ]
    resources = ["*"]
  }

  # S3 — read objects + parquet footers + object VERSIONS + S3 Inventory config
  # and its report objects. No Put/Delete anywhere.
  statement {
    sid = "S3ReadObjectsAndVersions"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = ["${var.bucket_arn}/*"]
  }

  statement {
    sid = "S3ListAndInspectBucket"
    actions = [
      "s3:ListBucket",
      "s3:ListBucketVersions",
      "s3:GetBucketVersioning",
      "s3:GetBucketLocation",
      "s3:GetInventoryConfiguration",
    ]
    resources = [var.bucket_arn]
  }

  # Athena — RESULTS inspection ONLY. No StartQueryExecution: the validator
  # fingerprints parquet footers and MUST NOT enumerate projection tables (INV-3).
  statement {
    sid = "AthenaResultsInspectOnly"
    actions = [
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:ListQueryExecutions",
      "athena:GetWorkGroup",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "silver_validator" {
  name        = "${var.project_name}-${var.environment}-silver-validator"
  description = "SILVER-F014 read-only validator: Glue catalog + S3 object/version/inventory + Athena-results inspection. No mutation, no StartQueryExecution."
  policy      = data.aws_iam_policy_document.silver_validator.json
}

resource "aws_iam_role_policy_attachment" "silver_validator" {
  role       = aws_iam_role.silver_validator.name
  policy_arn = aws_iam_policy.silver_validator.arn
}

# ---------------------------------------------------------------------------
# Publisher / deployer role — the single GATED writer.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "silver_publisher" {
  name = "${var.project_name}-${var.environment}-silver-publisher"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Role        = "silver-publisher"
  }
}

# Base grant — Glue GetTable/GetPartition(s) + CreatePartition/BatchCreatePartition
# on the approved dev database, and S3 Get/Put/List on silver/ + gold/. This does
# NOT include UpdatePartition/Delete (that is the repair flag) and is neutralised
# for silver/ by the default-attached deny below until the approval flag flips.
data "aws_iam_policy_document" "silver_publisher_base" {
  statement {
    sid = "GlueGetAndCreatePartitions"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:BatchGetPartition",
      "glue:CreatePartition",
      "glue:BatchCreatePartition",
    ]
    resources = [
      local.glue_catalog_arn,
      local.glue_database_arn,
      local.glue_tables_arn,
    ]
  }

  statement {
    sid = "S3ReadWriteApprovedPrefixes"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [
      "${var.bucket_arn}/silver/*",
      "${var.bucket_arn}/gold/*",
    ]
  }

  statement {
    sid       = "S3ListApprovedPrefixes"
    actions   = ["s3:ListBucket"]
    resources = [var.bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["silver/*", "gold/*"]
    }
  }
}

resource "aws_iam_policy" "silver_publisher_base" {
  name        = "${var.project_name}-${var.environment}-silver-publisher-base"
  description = "SILVER-F014 publisher base grant: Glue Get + Create/BatchCreatePartition on the approved dev DB + S3 Get/Put/List on silver/ + gold/."
  policy      = data.aws_iam_policy_document.silver_publisher_base.json
}

resource "aws_iam_role_policy_attachment" "silver_publisher_base" {
  role       = aws_iam_role.silver_publisher.name
  policy_arn = aws_iam_policy.silver_publisher_base.arn
}

# EXPLICIT DENY on canonical silver/ roots — attached by DEFAULT (approval flag
# false) and dropped only when a signed approval flips
# var.silver_canonical_publish_approved to true. An explicit Deny overrides the
# base Allow, so the publisher can create partitions on gold/ + non-silver tables
# but is refused every silver/ mutation until approved.
data "aws_iam_policy_document" "silver_publisher_canonical_deny" {
  count = var.silver_canonical_publish_approved ? 0 : 1

  statement {
    sid       = "DenySilverS3WritesUntilApproved"
    effect    = "Deny"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${var.bucket_arn}/silver/*"]
  }

  statement {
    sid    = "DenySilverGlueMutationUntilApproved"
    effect = "Deny"
    actions = [
      "glue:CreatePartition",
      "glue:BatchCreatePartition",
      "glue:UpdatePartition",
      "glue:DeletePartition",
      "glue:BatchDeletePartition",
      "glue:UpdateTable",
      "glue:DeleteTable",
    ]
    resources = [local.glue_silver_tables_arn]
  }
}

resource "aws_iam_policy" "silver_publisher_canonical_deny" {
  count       = var.silver_canonical_publish_approved ? 0 : 1
  name        = "${var.project_name}-${var.environment}-silver-publisher-canonical-deny"
  description = "SILVER-F014 explicit deny on canonical silver/ writes until a signed approval flips silver_canonical_publish_approved."
  policy      = data.aws_iam_policy_document.silver_publisher_canonical_deny[0].json
}

resource "aws_iam_role_policy_attachment" "silver_publisher_canonical_deny" {
  count      = var.silver_canonical_publish_approved ? 0 : 1
  role       = aws_iam_role.silver_publisher.name
  policy_arn = aws_iam_policy.silver_publisher_canonical_deny[0].arn
}

# REPAIR flag — UpdatePartition / Delete / prune collapsed into a flag (NOT a
# separate role, C-BETTER-3). Attached only when var.publisher_repair_enabled.
# Even when enabled, the canonical-deny above still fences silver/ until approved.
data "aws_iam_policy_document" "silver_publisher_repair" {
  count = var.publisher_repair_enabled ? 1 : 0

  statement {
    sid = "GlueRepairPartitions"
    actions = [
      "glue:UpdatePartition",
      "glue:DeletePartition",
      "glue:BatchDeletePartition",
    ]
    resources = [
      local.glue_catalog_arn,
      local.glue_database_arn,
      local.glue_tables_arn,
    ]
  }

  statement {
    sid       = "S3PruneApprovedPrefixes"
    actions   = ["s3:DeleteObject"]
    resources = ["${var.bucket_arn}/gold/*", "${var.bucket_arn}/silver/*"]
  }
}

resource "aws_iam_policy" "silver_publisher_repair" {
  count       = var.publisher_repair_enabled ? 1 : 0
  name        = "${var.project_name}-${var.environment}-silver-publisher-repair"
  description = "SILVER-F014 gated repair capability: Glue UpdatePartition/Delete + S3 prune. Attached only when publisher_repair_enabled."
  policy      = data.aws_iam_policy_document.silver_publisher_repair[0].json
}

resource "aws_iam_role_policy_attachment" "silver_publisher_repair" {
  count      = var.publisher_repair_enabled ? 1 : 0
  role       = aws_iam_role.silver_publisher.name
  policy_arn = aws_iam_policy.silver_publisher_repair[0].arn
}