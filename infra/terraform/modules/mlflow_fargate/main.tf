# ---------------------------------------------------------------------------
# A-W8 -- MLflow relocation: MLflow tracking server on ECS Fargate.
#
# Replaces the co-hosted EC2 (module.mlflow_server, i-012f869a03d7247fa) so the
# Airflow host can be retired (A-W9) without breaking training. The tracking
# server runs as a single Fargate task (0.5 vCPU / 1 GB) on the EXISTING serving
# ECS cluster (leviathan-dev-serving, created by module.ecs_service). It is
# reached at the stable private DNS name mlflow.leviathan.local:5000 via Cloud
# Map (avoids a ~$16/mo ALB), NOT a load balancer.
#
# Backend store  = Postgres on the existing leviathan-dev-pg (a NEW `mlflow`
#                  database, created out-of-band at cutover). The DSN is injected
#                  as the MLFLOW_BACKEND_STORE_URI env var from Secrets Manager
#                  (leviathan/dev/mlflow-backend-dsn) at container start; the
#                  server command expands it into --backend-store-uri. The DSN
#                  password never appears in code or state.
# Artifact root  = s3://<bucket>/mlflow/artifacts/ (UNCHANGED -- artifacts stay
#                  on S3; only the metadata backend moves. G4: fresh backend).
#
# The task runs in the public Batch subnets with assign_public_ip = true so it
# reaches ghcr.io (image pull), S3, Secrets Manager, and PyPI WITHOUT a NAT
# gateway -- mirroring module.ecs_service.
# ---------------------------------------------------------------------------

locals {
  name = "${var.project_name}-${var.environment}-mlflow"

  artifact_root = "s3://${var.bucket_name}/mlflow/artifacts/"

  # Stable in-VPC endpoint the re-registered training jobdefs point at.
  tracking_uri = "http://${var.service_dns_name}.${var.service_dns_namespace}:${var.container_port}"

  # Name-based secret ARN (mirrors the FAS_API_KEY pattern in envs/dev/main.tf):
  # ECS `secrets` valueFrom resolves the name-based ARN for a same-region secret,
  # while the IAM grant widens it with a trailing -* for the random 6-char suffix.
  backend_dsn_secret_arn_wild = "${var.backend_dsn_secret_arn}-*"

  common_tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

data "aws_vpc" "this" {
  id = var.vpc_id
}

# ---------------------------------------------------------------------------
# Cloud Map -- private DNS namespace + service -> mlflow.leviathan.local.
# If a `leviathan.local` namespace already exists live, swap this resource for a
# `data "aws_service_discovery_dns_namespace"` lookup (see the divergence note).
# ---------------------------------------------------------------------------
resource "aws_service_discovery_private_dns_namespace" "this" {
  name        = var.service_dns_namespace
  description = "Private DNS for Leviathan in-VPC service discovery (MLflow tracking)."
  vpc         = var.vpc_id

  tags = local.common_tags
}

resource "aws_service_discovery_service" "mlflow" {
  name = var.service_dns_name

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.this.id

    dns_records {
      type = "A"
      ttl  = 15
    }

    routing_policy = "MULTIVALUE"
  }

  # ECS reports task health; a single failure deregisters the record.
  health_check_custom_config {
    failure_threshold = 1
  }

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# Security group -- MLflow task. Inbound 5000 from the VPC (training Batch jobs
# resolve mlflow.leviathan.local and connect); egress open (image pull + S3 +
# Secrets Manager + PyPI + Postgres).
# ---------------------------------------------------------------------------
resource "aws_security_group" "task" {
  name        = "${local.name}-task"
  description = "MLflow tracking Fargate task: inbound 5000 from the VPC; egress open."
  vpc_id      = var.vpc_id

  ingress {
    description = "MLflow tracking UI/API from within the VPC"
    from_port   = var.container_port
    to_port     = var.container_port
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.this.cidr_block]
  }

  egress {
    description = "Task to ghcr.io/S3/SecretsManager/PyPI/RDS"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.name}-task" })
}

# Let the task reach RDS pgvector (leviathan-dev-pg). The RDS SG today admits the
# Batch + serving SGs; add the MLflow task SG on 5432 (SG-to-SG, same VPC). This
# is the ONE new ingress rule on sg-0a6f9c8f94beb9f29.
resource "aws_security_group_rule" "rds_from_mlflow_task" {
  type                     = "ingress"
  description              = "MLflow tracking task to RDS (mlflow backend database)"
  security_group_id        = var.rds_security_group_id
  source_security_group_id = aws_security_group.task.id
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
}

# ---------------------------------------------------------------------------
# IAM -- execution role (ECR/ghcr pull is public; CloudWatch Logs; secret
# injection). The `secrets` block valueFrom is resolved by the EXECUTION role.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "execution" {
  name = "${local.name}-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secret" {
  statement {
    sid       = "InjectBackendDsn"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [local.backend_dsn_secret_arn_wild]
  }
}

resource "aws_iam_role_policy" "execution_secret" {
  name   = "${local.name}-execution-secret"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secret.json
}

# ---------------------------------------------------------------------------
# IAM -- task role (app runtime perms): S3 mlflow/* RW + GetSecretValue on the
# backend DSN (per A-W8 step 2; the injection is execution-role side, this grant
# also covers an SDK-side read fallback).
# ---------------------------------------------------------------------------
resource "aws_iam_role" "task" {
  name = "${local.name}-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

data "aws_iam_policy_document" "task" {
  # Mirrors the proven module.mlflow_server S3 grant (List on the bucket, RW on
  # mlflow/* only) so mlflow's list_objects_v2 calls resolve unconditionally.
  statement {
    sid       = "MLflowListBucket"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.bucket_name}"]
  }

  statement {
    sid = "MLflowArtifactsRW"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["arn:aws:s3:::${var.bucket_name}/mlflow/*"]
  }

  statement {
    sid       = "ReadBackendDsn"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [local.backend_dsn_secret_arn_wild]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "${local.name}-task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# ---------------------------------------------------------------------------
# Logs + task definition + service.
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${local.name}"
  retention_in_days = var.log_retention_days

  tags = local.common_tags
}

resource "aws_ecs_task_definition" "this" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "mlflow"
      image     = var.container_image
      essential = true

      # NO command override: the baked image entrypoint (docker/mlflow/Dockerfile) already runs
      # ONLY `mlflow server --backend-store-uri "$MLFLOW_BACKEND_STORE_URI"
      # --default-artifact-root "$MLFLOW_DEFAULT_ARTIFACT_ROOT" --host 0.0.0.0 --port 5000`, with
      # mlflow/psycopg2-binary/boto3/gunicorn baked in. The old runtime `pip install ...` was
      # removed -- it failed and crashlooped the container with no logs.

      portMappings = [
        { containerPort = var.container_port, protocol = "tcp" }
      ]

      environment = [
        { name = "AWS_DEFAULT_REGION", value = var.aws_region },
        { name = "MLFLOW_DEFAULT_ARTIFACT_ROOT", value = local.artifact_root },
      ]

      secrets = [
        { name = "MLFLOW_BACKEND_STORE_URI", valueFrom = var.backend_dsn_secret_arn }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "mlflow"
        }
      }
    }
  ])

  tags = local.common_tags
}

resource "aws_ecs_service" "this" {
  name            = local.name
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true # public subnet, no NAT
  }

  # Cloud Map A-record registration -> mlflow.leviathan.local (in-VPC training jobs).
  service_registries {
    registry_arn = aws_service_discovery_service.mlflow.arn
  }

  # Internet-facing ALB target-group registration (browser access at https://mlflow.<domain>).
  # Registers the task ENI IP into the mlflow target group (target_type = ip). See alb.tf.
  load_balancer {
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = "mlflow"
    container_port   = var.container_port
  }

  # MLflow boots fast, but give the /health check a short grace before the LB can kill a new task.
  health_check_grace_period_seconds = 60

  tags = local.common_tags

  # The listeners + the ALB->task SG rule must exist before the service registers targets.
  depends_on = [
    aws_security_group_rule.rds_from_mlflow_task,
    aws_security_group_rule.task_from_alb,
    aws_lb_listener.http,
    aws_lb_listener.https,
  ]
}
