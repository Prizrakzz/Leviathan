terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

module "s3" {
  source = "../../modules/s3"

  bucket_name  = var.bucket_name
  project_name = var.project_name
  environment  = var.environment
}

module "iam" {
  source = "../../modules/iam"

  project_name               = var.project_name
  environment                = var.environment
  bucket_arn                 = module.s3.bucket_arn
  ecr_trainer_repository_arn = module.ecr_trainer.repository_arn
  # Stage 4: serving task RW on the durable terminal-store + the existing sessions table.
  dynamodb_table_arns = [module.dynamodb.table_arn, data.aws_dynamodb_table.sessions.arn]
}

# Cost tripwires (Jul-2026 S3 LIST storm): daily S3 budget alert + CE anomaly detection -> email.
module "cost_guardrails" {
  source = "../../modules/cost_guardrails"

  project_name = var.project_name
  environment  = var.environment
  alert_email  = "ivanzkarpov@gmail.com"
}

# GraphRAG serving input guardrail (prompt-attack HIGH + high-risk PII, INPUT only).
# Serving enables it via GRAPHRAG_GUARDRAIL=<graphrag_guardrail_id> (default off, fail-open).
module "bedrock_guardrail" {
  source = "../../modules/bedrock_guardrail"

  project_name        = var.project_name
  environment         = var.environment
  batch_job_role_name = module.iam.batch_job_role_name
}

module "ecr" {
  source = "../../modules/ecr"

  project_name    = var.project_name
  environment     = var.environment
  repository_name = "leviathan-worker"
}

module "ecr_trainer" {
  source = "../../modules/ecr"

  project_name    = var.project_name
  environment     = var.environment
  repository_name = "leviathan-trainer"
}

module "batch" {
  source = "../../modules/batch"

  project_name       = var.project_name
  environment        = var.environment
  aws_region         = var.aws_region
  max_vcpus          = var.batch_max_vcpus
  subnet_ids         = var.batch_subnet_ids
  security_group_ids = var.batch_security_group_ids

  ecr_repository_url       = module.ecr.repository_url
  batch_execution_role_arn = module.iam.batch_execution_role_arn
  batch_job_role_arn       = module.iam.batch_job_role_arn
  leviathan_bucket         = var.bucket_name
}

module "glue" {
  source = "../../modules/glue"

  project_name      = var.project_name
  environment       = var.environment
  aws_region        = var.aws_region
  bucket_name       = var.bucket_name
  glue_job_role_arn = module.iam.glue_job_role_arn
}

module "cloudwatch" {
  source = "../../modules/cloudwatch"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  # Stage 5.2 serving observability: dashboard + alarms -> the alerting SNS topic.
  alert_topic_arn  = module.alerting.topic_arn
  alb_arn          = module.serving_alb.alb_arn
  target_group_arn = module.serving_alb.target_group_arn
  ecs_cluster_name = module.serving.cluster_name
  ecs_service_name = module.serving.service_name
  waf_web_acl_name = "${var.project_name}-${var.environment}-serving"
}

module "mlflow_server" {
  source = "../../modules/mlflow_server"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  bucket_name  = var.bucket_name
  # Reuse the first Batch subnet — same VPC, same routing to S3 and SageMaker.
  subnet_id            = var.batch_subnet_ids[0]
  ami_id               = var.mlflow_ami_id
  root_volume_size_gib = var.mlflow_root_volume_size_gib
}

# ---------------------------------------------------------------------------
# Phase 4.1 — GraphRAG serving on ECS Fargate + ALB (EVIDENCE_BACKEND=pg,
# Bedrock guardrail on). Reuses the Batch VPC/subnets (public, no NAT), the
# Batch job/execution roles, the pg DSN secret, and the guardrail from Phase 0.2.
# ---------------------------------------------------------------------------

# VPC derived from the first Batch subnet (tasks + ALB + RDS share this VPC).
data "aws_subnet" "serving" {
  id = var.batch_subnet_ids[0]
}

# pg DSN secret (created out-of-band with the RDS in the pgvector migration).
data "aws_secretsmanager_secret" "pg_dsn" {
  name = "leviathan/dev/evidence-pg-dsn"
}

# The serving image repo (created outside Terraform; image pushed by
# scripts/build_push_embedder.ps1).
data "aws_ecr_repository" "embedder" {
  name = "leviathan-dev-leviathan-embedder"
}

# RDS pgvector — used only to read its security group id, so the serving task
# SG can be granted ingress on 5432.
data "aws_db_instance" "pg" {
  db_instance_identifier = "leviathan-dev-pg"
}

module "serving_alb" {
  source = "../../modules/alb"

  project_name = var.project_name
  environment  = var.environment
  vpc_id       = data.aws_subnet.serving.vpc_id
  subnet_ids   = var.batch_subnet_ids
  admin_cidrs  = var.serving_admin_cidrs

  # Stage 2: HTTPS:443 (wildcard ACM cert) + 80->301->443 redirect.
  # Stage 5 (2026-07-05): public_ingress=true opens 443 (+ the :80 redirect) to 0.0.0.0/0 — the site is
  # public behind Google sign-in + WAF + per-user quota + Bedrock budget. KILL-SWITCH: set false + re-apply
  # `-target=module.serving_alb.aws_security_group.alb` to instantly re-lock to admin_cidrs.
  enable_https    = true
  certificate_arn = var.serving_certificate_arn
  public_ingress  = true
}

# The public hosted zone was created in the console (Namecheap-delegated); reference it, don't manage it.
data "aws_route53_zone" "public" {
  zone_id = var.public_zone_id
}

# api.leviathanconvexity.com -> the serving ALB (HTTPS). Resolves publicly once NS delegation completes.
resource "aws_route53_record" "api" {
  zone_id = data.aws_route53_zone.public.zone_id
  name    = "api.${var.public_domain}"
  type    = "A"

  alias {
    name                   = module.serving_alb.alb_dns_name
    zone_id                = module.serving_alb.alb_zone_id
    evaluate_target_health = true
  }
}

# Stage 3: the Terminal SPA on S3 + CloudFront, served at the apex + www (wildcard cert covers both).
module "spa_hosting" {
  source = "../../modules/spa_hosting"

  project_name        = var.project_name
  environment         = var.environment
  acm_certificate_arn = var.serving_certificate_arn
  aliases             = [var.public_domain, "www.${var.public_domain}"]
}

# apex -> CloudFront (A + AAAA ALIAS; apex can't be a CNAME).
resource "aws_route53_record" "apex" {
  zone_id = data.aws_route53_zone.public.zone_id
  name    = var.public_domain
  type    = "A"

  alias {
    name                   = module.spa_hosting.distribution_domain_name
    zone_id                = module.spa_hosting.distribution_hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "apex_aaaa" {
  zone_id = data.aws_route53_zone.public.zone_id
  name    = var.public_domain
  type    = "AAAA"

  alias {
    name                   = module.spa_hosting.distribution_domain_name
    zone_id                = module.spa_hosting.distribution_hosted_zone_id
    evaluate_target_health = false
  }
}

# www -> CloudFront (ALIAS; replaces the console-created www CNAME to apex).
resource "aws_route53_record" "www" {
  zone_id         = data.aws_route53_zone.public.zone_id
  name            = "www.${var.public_domain}"
  type            = "A"
  allow_overwrite = true

  alias {
    name                   = module.spa_hosting.distribution_domain_name
    zone_id                = module.spa_hosting.distribution_hosted_zone_id
    evaluate_target_health = false
  }
}

# Stage 4: durable terminal store (store.py) + Cognito Google sign-in.
module "dynamodb" {
  source       = "../../modules/dynamodb"
  project_name = var.project_name
  environment  = var.environment
}

# The conversation-memory table (session.py) exists out-of-band; reference it for the IAM grant.
data "aws_dynamodb_table" "sessions" {
  name = "leviathan-dev-graphrag-sessions"
}

module "cognito" {
  source       = "../../modules/cognito"
  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  domain_prefix        = var.cognito_domain_prefix
  google_client_id     = var.google_oauth_client_id
  google_client_secret = var.google_oauth_client_secret

  callback_urls = ["https://${var.public_domain}/auth/callback", "http://localhost:5173/auth/callback"]
  logout_urls   = ["https://${var.public_domain}", "http://localhost:5173"]
}

# Stage 5 (public exposure hardening): alert fan-out + WAF on the ALB.
module "alerting" {
  source       = "../../modules/alerting"
  project_name = var.project_name
  environment  = var.environment
  alert_email  = "ivanzkarpov@gmail.com"
}

# WAFv2: managed groups + rate limits (esp. /v1/respond*). Ships in COUNT mode (blocking_enabled=false);
# flip to true after a 24-48h observation window.
module "waf" {
  source       = "../../modules/wafv2"
  project_name = var.project_name
  environment  = var.environment
  alb_arn      = module.serving_alb.alb_arn
}

module "serving" {
  source = "../../modules/ecs_service"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  vpc_id     = data.aws_subnet.serving.vpc_id
  subnet_ids = var.batch_subnet_ids

  alb_security_group_id = module.serving_alb.alb_security_group_id
  target_group_arn      = module.serving_alb.target_group_arn

  container_image    = "${data.aws_ecr_repository.embedder.repository_url}:${var.serving_image_tag}"
  task_role_arn      = module.iam.batch_job_role_arn
  execution_role_arn = module.iam.batch_execution_role_arn

  rds_security_group_id = tolist(data.aws_db_instance.pg.vpc_security_groups)[0]
  pg_dsn_secret_arn     = data.aws_secretsmanager_secret.pg_dsn.arn
  guardrail_id          = module.bedrock_guardrail.guardrail_id
  leviathan_bucket      = var.bucket_name

  # Stage 5.3 R2 (autoscaling review): cap scale-out at 2. min stays 1 (the BGE S3-cache makes a replacement
  # cheap). We deliberately do NOT add request-count scaling: serving turns are I/O-bound (Bedrock/pg), so the
  # existing CPU target-tracking policy rarely fires and the service effectively stays at 1 — and scaling OUT
  # would split the Cohere managed-rerank quota (3 req/min, account-wide) across tasks, hurting latency. max=2
  # is a CPU-spike safety valve only.
  max_count = 2

  # Stage 1.5 latency fixes (env flips only; rollback = remove the key):
  #  - GRAPHRAG_RERANK_BACKEND: managed Cohere Rerank (coalesced, 1 req/turn — quota is 3/min) replaces the
  #    CPU bge cross-encoder that made the L2 walk ~100s. Rollback = "bge".
  #  - GRAPHRAG_SILVER_CACHE: cross-turn vintage cache for silver Athena reads (~14s of the walk) —
  #    historical asof = immutable vintage -> cached forever; live asof -> 15-min TTL. PIT-safe by design.
  #  - GRAPHRAG_NUMBERS_BACKEND: numbers lookups served from the RDS pg mirror (schema leviathan_dev,
  #    same SQL string as Athena; per-request Athena fallback). Flipped 2026-07-05 after the parity gate
  #    (numbers_pg_parity.md). Rollback = remove the key (default athena).
  #  - GRAPHRAG_CORS_ORIGINS: Stage 3 — the SPA's real origins may call the API. allow_credentials=True
  #    forbids "*", so origins are exact. localhost kept for local dev against the prod API.
  #  - Stage 4: GRAPHRAG_AUTH on -> /v1/respond* + persistence require a valid Cognito ID token (auth.py
  #    verifies iss/aud/exp). GRAPHRAG_STORE=dynamo -> durable terminal-store (shares + per-user threads);
  #    GRAPHRAG_SESSIONS_TABLE -> conversation memory in the existing sessions table (per-user threads).
  #    GRAPHRAG_CONVERGENCE_CACHE -> in-process TTL cache. Rollback for each = remove the key.
  extra_environment = {
    GRAPHRAG_RERANK_BACKEND  = "bedrock"
    GRAPHRAG_SILVER_CACHE    = "on"
    GRAPHRAG_NUMBERS_BACKEND = "pg"
    GRAPHRAG_CORS_ORIGINS    = "https://leviathanconvexity.com,https://www.leviathanconvexity.com"

    GRAPHRAG_AUTH              = "on"
    COGNITO_REGION             = var.aws_region
    COGNITO_USER_POOL_ID       = module.cognito.user_pool_id
    COGNITO_APP_CLIENT_ID      = module.cognito.app_client_id
    GRAPHRAG_STORE             = "dynamo"
    GRAPHRAG_STORE_TABLE       = module.dynamodb.table_name
    GRAPHRAG_SESSIONS_TABLE    = data.aws_dynamodb_table.sessions.name
    GRAPHRAG_CONVERGENCE_CACHE = "on"
    # Stage 5 public hardening: enable the provisioned Bedrock guardrail + per-user daily turn cap (429 over).
    GRAPHRAG_GUARDRAIL  = module.bedrock_guardrail.guardrail_id
    GRAPHRAG_TURN_QUOTA = "50"

    # Stage 5.0/5.4 latency: tighten the rerank coalescer (default 4.0/0.8) — the exact eligible-count already
    # short-circuits, so this only trims the empty-retrieval straggler wait. env-tunable, no rebuild.
    GRAPHRAG_COALESCE_WINDOW     = "1.5"
    GRAPHRAG_COALESCE_QUIESCENCE = "0.3"

    # Stage 5.3 R1 (+ speed follow-up): cold-start cache. On startup the task syncs the bge models from S3 in
    # parallel instead of downloading from HuggingFace; the first task self-seeds. The /v2 prefix holds the
    # LEAN cache (safetensors-only, ~4.5 GB vs the v1 13.7 GB all-formats). Rollback = /models/hf or remove key.
    GRAPHRAG_HF_S3_CACHE = "s3://${var.bucket_name}/models/hf/v2"

    # Phase 5.6 UX: background convergence warmer (live-asof heatmap always hot; lookups route via the pg
    # mirror with per-request Athena fallback) + Haiku thread auto-titles. Rollback for each = remove the key.
    GRAPHRAG_CONVERGENCE_WARM = "on"
    GRAPHRAG_THREAD_TITLES    = "on"

    # Phase 5.8: country-aware live-news search only — a country named with no commodity ("news on India")
    # searches that country instead of generic keywords. Deterministic; affects live turns only. The fuzzy
    # in-thread topic-shift carry-breaker was removed by design (threads are the context boundary). Rollback
    # = remove the key.
    GRAPHRAG_GEO_ROUTING = "on"
  }

  # Stage 1: guardrail on, auth off, CORS = localhost (defaults in the module).
  # Stage 4 flips GRAPHRAG_AUTH + COGNITO_* via extra_environment and prod CORS.

  depends_on = [module.serving_alb] # listener must exist before the service registers
}

# ---------------------------------------------------------------------------
# Monthly cost budget — alerts at 80 % actual and 100 % forecasted.
# Set budget_alert_email in terraform.tfvars to receive emails.
# ---------------------------------------------------------------------------
resource "aws_budgets_budget" "monthly_cost" {
  name         = "${var.project_name}-${var.environment}-monthly-budget"
  budget_type  = "COST"
  limit_amount = "30"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = var.budget_alert_email != "" ? [1] : []
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = 80
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }

  dynamic "notification" {
    for_each = var.budget_alert_email != "" ? [1] : []
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = 100
      threshold_type             = "PERCENTAGE"
      notification_type          = "FORECASTED"
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }
}
