# ---------------------------------------------------------------------------
# ECS Fargate service for the GraphRAG serving API (Phase 4.1).
#
# Same image as the evidence-build worker (leviathan-dev-leviathan-embedder):
# ENTRYPOINT ["python"], run as `-m uvicorn leviathan.graphrag.server:app`.
# EVIDENCE_BACKEND=pg -> respond() serves evidence from RDS pgvector (4-6x warm,
# zero cold-slice load); GRAPHRAG_GUARDRAIL turns the Bedrock input pre-filter on.
# Task runs in the Batch VPC public subnets with assign_public_ip = true so it
# reaches Bedrock/Athena/S3/HuggingFace WITHOUT a ~$33/mo NAT gateway.
# ---------------------------------------------------------------------------

locals {
  name = "${var.project_name}-${var.environment}-serving"

  base_environment = {
    EVIDENCE_BACKEND           = var.evidence_backend
    GRAPHRAG_PROVIDER          = var.graphrag_provider
    GRAPHRAG_GUARDRAIL         = var.guardrail_id
    GRAPHRAG_GUARDRAIL_VERSION = var.guardrail_version
    GRAPHRAG_CORS_ORIGINS      = var.cors_origins
    AWS_REGION                 = var.aws_region
    LEVIATHAN_BUCKET           = var.leviathan_bucket
    LEVIATHAN_ENV              = var.environment
  }

  environment_list = [
    for k, v in merge(local.base_environment, var.extra_environment) : {
      name  = k
      value = tostring(v)
    }
  ]
}

resource "aws_ecs_cluster" "this" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "disabled"
  }

  tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

resource "aws_security_group" "task" {
  name        = "${local.name}-task"
  description = "GraphRAG serving Fargate task: inbound only from the ALB SG; egress open (Bedrock/Athena/S3/HF)."
  vpc_id      = var.vpc_id

  ingress {
    description     = "ALB to task"
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [var.alb_security_group_id]
  }

  egress {
    description = "Task to Bedrock/Athena/S3/HuggingFace/RDS"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name        = "${local.name}-task"
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

# Let the task reach RDS pgvector. The RDS SG today only admits the Batch SG;
# add the serving task SG on 5432 (SG-to-SG, same VPC).
resource "aws_security_group_rule" "rds_from_task" {
  type                     = "ingress"
  description              = "GraphRAG serving task to RDS pgvector"
  security_group_id        = var.rds_security_group_id
  source_security_group_id = aws_security_group.task.id
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${local.name}"
  retention_in_days = var.log_retention_days

  tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

resource "aws_ecs_task_definition" "this" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  runtime_platform {
    cpu_architecture        = "X86_64" # the embedder image is built linux/amd64
    operating_system_family = "LINUX"
  }

  ephemeral_storage {
    size_in_gib = var.ephemeral_storage_gib
  }

  container_definitions = jsonencode([
    {
      name      = "serving"
      image     = var.container_image
      essential = true

      # ENTRYPOINT is `python`; run the ASGI app.
      command = ["-m", "uvicorn", "leviathan.graphrag.server:app", "--host", "0.0.0.0", "--port", tostring(var.container_port)]

      portMappings = [
        { containerPort = var.container_port, protocol = "tcp" }
      ]

      environment = local.environment_list

      secrets = concat(
        [{ name = "EVIDENCE_PG_DSN", valueFrom = var.pg_dsn_secret_arn }],
        [for k, v in var.extra_secrets : { name = k, valueFrom = v }],
      )

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "serving"
        }
      }
    }
  ])

  tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

resource "aws_ecs_service" "this" {
  name            = local.name
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  # BGE reranker + graph load on cold start — don't kill a task before it's ready.
  health_check_grace_period_seconds = var.health_check_grace

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true # public subnet, no NAT
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "serving"
    container_port   = var.container_port
  }

  # Autoscaling owns desired_count after creation.
  lifecycle {
    ignore_changes = [desired_count]
  }

  tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })

  depends_on = [aws_security_group_rule.rds_from_task]
}

# --- Autoscaling: min 1 (never cold), max N, target-tracking on CPU ----------
resource "aws_appautoscaling_target" "this" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.this.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.min_count
  max_capacity       = var.max_count
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "${local.name}-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.this.service_namespace
  resource_id        = aws_appautoscaling_target.this.resource_id
  scalable_dimension = aws_appautoscaling_target.this.scalable_dimension

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = var.cpu_target
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
