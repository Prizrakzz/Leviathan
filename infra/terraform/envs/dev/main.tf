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

locals {
  # Phase D D-W1: name-based ARN for the FAS/api.data.gov key mounted as FAS_API_KEY on the weekly
  # ESR fetch job. The secret leviathan/dev/fas-api-key does NOT exist yet (USER-GATED creation; the
  # value lives in the local .env), so this is CONSTRUCTED, not looked up -- a data source on an
  # absent secret would fail at plan time. ECS/Batch valueFrom resolves the name-based ARN for a
  # same-region secret; the iam GetSecretValue grant widens it with a trailing -* for the random suffix.
  fas_api_key_secret_arn = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:leviathan/dev/fas-api-key"

  # A-W8 MLflow relocation: name-based ARN for the mlflow pg DSN mounted as
  # MLFLOW_BACKEND_STORE_URI on the Fargate tracking server. The secret
  # leviathan/dev/mlflow-backend-dsn is created OUT-OF-BAND at cutover (it holds
  # the db password), so this is CONSTRUCTED, not looked up -- a data source on an
  # absent secret fails at plan time. ECS valueFrom resolves the name-based ARN
  # for a same-region secret; the iam GetSecretValue grant widens it with -*.
  mlflow_backend_dsn_secret_arn = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:leviathan/dev/mlflow-backend-dsn"

  # T2B pattern-records sweep image: the EMBEDDER repo pinned BY DIGEST. Assembled here (not in
  # module.batch) because module.batch is wired to the WORKER repo and the sweep needs the embedder,
  # which already carries leviathan.graphrag + the F015 publisher -- the same reason
  # submit_batch_gold_weather_z pins the embedder. EMPTY until the digest is pinned, which
  # count-gates the jobdef, the scheduler role and the schedule out of existence: the whole T2B
  # cloud leg is a terraform no-op until rollout step 3 content-checks an image.
  pattern_records_image = (
    var.pattern_records_image_digest == ""
    ? ""
    : "${data.aws_ecr_repository.embedder.repository_url}@${var.pattern_records_image_digest}"
  )

  # PRICE_AND_PLAYBOOKS W2: name-based ARN for the Databento key mounted as
  # DATABENTO_API_KEY on the databento fetch job. The secret
  # leviathan/dev/databento-api-key is created OUT-OF-BAND (USER-GATED --
  # futures_eod_databento.json precondition (c); the value is a vendor API key), so
  # this is CONSTRUCTED, not looked up: a data source on an absent secret fails at
  # PLAN time and would block every unrelated apply. ECS/Batch valueFrom resolves the
  # name-based ARN for a same-region secret; the iam GetSecretValue grant widens it
  # with a trailing -* for the Secrets Manager random suffix. Same shape as
  # fas_api_key_secret_arn above.
  databento_api_key_secret_arn = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:leviathan/dev/databento-api-key"
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
  # P3: the daily-digest job's dedicated Scan-scoped role (Scan must NEVER land on the serving-shared role).
  notifications_store_table_arn = module.dynamodb.table_arn
  # D-W1: execution-role GetSecretValue for the weekly ESR fetch's FAS_API_KEY (user-gated secret).
  fas_api_key_secret_arn = local.fas_api_key_secret_arn
  # T2B: execution-role GetSecretValue for the pattern-records sweep's EVIDENCE_PG_DSN mount
  # (the sweep is a pg-only engine replay and refuses to run without it).
  numbers_pg_dsn_secret_arn = data.aws_secretsmanager_secret.pg_dsn.arn
  # W2: execution-role GetSecretValue for the databento fetch's DATABENTO_API_KEY mount.
  databento_api_key_secret_arn = local.databento_api_key_secret_arn
  # SILVER-F014 latch: flipped TRUE under the signed A1-A2 G1+G5.0 grants (2026-07-16) --
  # canonical authority now rests on kms:Sign + gate-first + shadow-first, not the deny.
  silver_canonical_publish_approved = true
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

  # D-PR-2, ADOPTING A LIVE OUT-OF-BAND VALUE (raised 2026-08-04, not by terraform).
  # This is the repo every Batch jobdef family runs, so it takes the whole estate's
  # rebuild burst: 40 jobdef families pin worker digests and a single wave day pushes
  # 8-10 images. At cap 30 the oldest-first rule was eating digests that ACTIVE
  # revisions still pinned (measured 2026-08-04: 39 images held, 47 digests pinned by
  # ACTIVE jobdefs, 3 pinned digests inside the would-be evict set). 100 is ~10 wave
  # days of headroom. Until this line existed, every plan proposed 100 -> 30.
  image_count_cap = 100
}

module "ecr_trainer" {
  source = "../../modules/ecr"

  project_name    = var.project_name
  environment     = var.environment
  repository_name = "leviathan-trainer"
}

# Dedicated source-only EDA image. Apply with -target=module.ecr_eda before
# running scripts/build_push_eda.ps1; never use a full untargeted apply here.
module "ecr_eda" {
  source = "../../modules/ecr"

  project_name    = var.project_name
  environment     = var.environment
  repository_name = "leviathan-eda"

  # D-PR-2, same adoption as module.ecr. The EDA image is rebuilt per analysis run
  # rather than per deploy, so it burns through revisions faster than the worker per
  # active day; it sat at exactly 30/30 when the cap was raised, i.e. every next push
  # was evicting. Until this line existed, every plan proposed 60 -> 30.
  image_count_cap = 60
}

# A-W8 MLflow relocation: ECR repo for the baked MLflow server image (docker/mlflow/Dockerfile,
# pushed by scripts/build_push_mlflow.ps1). Produces leviathan-dev-mlflow -- the default
# container_image of module.mlflow_fargate. Apply this FIRST (-target=module.ecr_mlflow) so the
# image can be pushed before the ECS service pulls it.
# W1c: repo for the browser-producer image (docker/leviathan_browser -- playwright + chromium;
# DCE/Euronext/Bursa producers). Built by scripts/build_push_browser.ps1; the browser jobdef is
# CLI-registered first (publisher-runner precedent) and adopted into terraform with the drift
# reconciliation.
module "ecr_browser" {
  source = "../../modules/ecr"

  project_name    = var.project_name
  environment     = var.environment
  repository_name = "leviathan-browser"
}

module "ecr_mlflow" {
  source = "../../modules/ecr"

  project_name    = var.project_name
  environment     = var.environment
  repository_name = "mlflow"
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
  # D-W1: enables the weekly ESR fetch jobdef (usda_esr_fetch) that mounts FAS_API_KEY.
  fas_api_key_secret_arn = local.fas_api_key_secret_arn

  # T2B pattern-records sweep (plan sec 7 step 5). The jobdef is count-gated on the
  # image ref: EMPTY until the main loop pins the CONTENT-CHECKED digest into
  # var.pattern_records_image_digest, so this whole lane is a terraform no-op until then.
  # The image is the EMBEDDER (it carries leviathan.graphrag + the publisher), NOT the
  # worker repo module.batch otherwise uses -- the same choice submit_batch_gold_weather_z
  # makes, and the reason the ref is passed in whole rather than assembled in the module.
  pattern_records_image        = local.pattern_records_image
  pattern_records_job_role_arn = module.iam.pattern_records_job_role_arn
  numbers_pg_dsn_secret_arn    = data.aws_secretsmanager_secret.pg_dsn.arn
  publish_signer_kms_key_arn   = aws_kms_key.publish_signer.arn

  # PRICE_AND_PLAYBOOKS W1a + W2 -- the two futures_eod chains' three jobdefs
  # (futures-eod-free-fetch, databento-fetch, futures-eod-silver). Registering them
  # only makes the chains RUNNABLE; what ARMS a nightly fire is the
  # dag_schedules.auto.tfvars.json entry, and both descriptors are
  # promote_mode=stop_and_notify (shadow only, empty promote.tasks).
  futures_eod_image_digest = var.futures_eod_image_digest
  # The silver leg is pinned SEPARATELY (live latest-ACTIVE is one build ahead of the
  # fetch legs -- see the variable's comment). Sharing one digest would have
  # re-registered the publishing leg from the older fetch pin.
  futures_eod_silver_image_digest = var.futures_eod_silver_image_digest
  # The SILVER-F014 gated writer: silver_futures_eod is class-A REGISTERED, so its
  # producer needs glue:CreatePartition, which only this role carries.
  silver_publisher_job_role_arn = module.iam.silver_publisher_role_arn
  databento_api_key_secret_arn  = local.databento_api_key_secret_arn

  # D-PR-22: the pink-sheet bronze leg comes off the mutable :latest tag.
  pink_sheet_image_digest = var.pink_sheet_image_digest
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
# REMOVED 2026-07-30 (drift reconciliation): module "mlflow_server" -- the EC2 MLflow.
# MLflow moved to Fargate (module.mlflow_fargate) and the EC2 stack was RETIRED, but the module
# declaration lingered in config while NOTHING of it existed live: verified across the account --
# no instance in any state, no IAM role, no instance profile, no security group, neither managed
# policy. A blanket apply would therefore have RESURRECTED the retired server (9 resources).
# Nothing referenced its outputs (instance_id / private_ip / tracking_uri / airflow_ui_uri);
# envs/dev/outputs.tf reads module.mlflow_fargate[0].tracking_uri instead. var.mlflow_ami_id and
# var.mlflow_root_volume_size_gib are now unused and were removed with it.


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

# Anthropic API key for the serving task (created out of band; mounted on the running service
# since before the 2026-07-30 drift reconciliation wrote it back into config).
data "aws_secretsmanager_secret" "anthropic_api_key" {
  name = "leviathan-dev-anthropic-api-key"
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

data "aws_caller_identity" "current" {}

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

# SILVER-F082 silver pipeline observability (apply-GATED). The alarm set + tfvars are generated by
# jobs/observability/silver_alarms.py; the vars come from silver_observability.auto.tfvars.json. Do
# NOT apply in a blanket `terraform apply` -- apply only via the -target commands in
# reports/silver_readiness/R4_F082_observability/README.md, after the value census + freshness cert
# metrics are being emitted.
module "silver_observability" {
  source = "../../modules/silver_observability"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  alert_topic_arn         = module.alerting.topic_arn
  silver_alert_email      = var.silver_alert_email
  silver_metric_namespace = var.silver_metric_namespace
  silver_batch_families   = var.silver_batch_families
  silver_freshness_slas   = var.silver_freshness_slas
  # Stale-producer wave 2026-07-23: per-TABLE freshness alarms for the 4 burned tables
  # (single-dim {Table} metric from the freshness poller; family rollup rides {Family}).
  silver_table_freshness_slas = var.silver_table_freshness_slas

  # A-W5 step 3: orchestration-plane alarms + the aws.states failure rule. The machine ARN
  # gates the SFN-specific alarms/rule (empty -> they don't create), so this can apply before or
  # after step_functions; the scheduler + Batch-queued-age alarms always apply. The per-family
  # schedules live in the default scheduler group.
  state_machine_arn    = module.step_functions.state_machine_arn
  scheduler_group_name = "default"
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

  # RECONCILED TO LIVE 2026-07-30 (drift). State was pinned at task-def rev 23 while the service
  # ran rev 67, so config had drifted three ways that a blanket apply would have SHIPPED:
  #  - sizing: config set neither cpu nor memory, so the module defaults (2048 / 8192) would have
  #    HALVED the running task and reverted the latency-RCA Phase-0 fix. Live is 4096 / 16384.
  #  - secrets: the task mounts ANTHROPIC_API_KEY alongside EVIDENCE_PG_DSN; without it the
  #    serving container loses its Anthropic credential outright.
  # (The 16 missing env keys + 2 reverted values are reconciled in extra_environment below.)
  cpu    = 4096
  memory = 16384

  extra_secrets = {
    ANTHROPIC_API_KEY = data.aws_secretsmanager_secret.anthropic_api_key.arn
  }
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
    GRAPHRAG_COALESCE_WINDOW     = "4.0"
    GRAPHRAG_COALESCE_QUIESCENCE = "2.5"

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

    # Phase 6.8: grounded query suggester. When on, /v1/suggest builds a data-scoped catalog from the WARM
    # convergence matrix (regimes closest to firing, tracked contracts, answerable metrics + driver lanes) and
    # prompts Haiku in the convexity house style with a hard answerable-only gate -> short, cascade/convergence-
    # framed, news-anchored chips scoped to OUR data. A/B-validated (convexity 2%->88%, answerable 100%,
    # register-clean 100%). Needs GRAPHRAG_CONVERGENCE_WARM=on (catalog reads the warm cache only; cold -> base
    # prompt). Fail-open to the byte-identical base prompt on any error. Rollback = remove the key.
    GRAPHRAG_SUGGEST_CATALOG = "on"
    # ------------------------------------------------------------------------------------------
    # RECONCILED TO LIVE 2026-07-30 (drift). These 16 keys were SET ON THE RUNNING SERVICE (task
    # definition rev 67) but had never been written back into config -- every one arrived through a
    # manual `update-service`, which terraform cannot see because aws_ecs_task_definition re-reads
    # only the revision it created (state was pinned at rev 23). A blanket apply would therefore
    # have registered a task def WITHOUT them and turned off most of the shipped product:
    # co-move, the three cascade legs + transmission, reroute v2, notifications, context attach,
    # convergence intensity, the family facet, the trivial router, cross-commodity LLM detect --
    # plus the two pg settings from the latency RCA (pool 8, the 300s statement timeout that fixed
    # the floor) and the provider pin. GRAPHRAG_COALESCE_{WINDOW,QUIESCENCE} above were likewise
    # corrected 1.5/0.3 -> 4.0/2.5 to match live.
    # ------------------------------------------------------------------------------------------
    EVIDENCE_PG_POOL                 = "8"
    EVIDENCE_PG_STATEMENT_TIMEOUT_MS = "300000"
    GRAPHRAG_PROVIDER                = "anthropic"
    GRAPHRAG_COMOVE                  = "on"
    GRAPHRAG_CONTEXT_ATTACH          = "on"
    GRAPHRAG_CASCADE_CHAIN           = "on"
    GRAPHRAG_CASCADE_PACE_LEG        = "on"
    GRAPHRAG_CASCADE_PRICE_LEG       = "on"
    GRAPHRAG_CASCADE_TRANSMISSION    = "on"
    GRAPHRAG_CONVERGENCE_INTENSITY   = "on"
    GRAPHRAG_FAMILY_FACET            = "on"
    GRAPHRAG_NOTIFICATIONS           = "on"
    GRAPHRAG_REROUTE_V2              = "on"
    GRAPHRAG_ROLLUP_ASYNC            = "off"
    GRAPHRAG_TRIVIAL_ROUTER          = "on"
    GRAPHRAG_XC_LLM_DETECT           = "on"

  }

  # Stage 1: guardrail on, auth off, CORS = localhost (defaults in the module).
  # Stage 4 flips GRAPHRAG_AUTH + COGNITO_* via extra_environment and prod CORS.

  depends_on = [module.serving_alb] # listener must exist before the service registers
}

# REMOVED 2026-07-30 (user-directed: "destroy it, we don't need it"): module "mlflow_fargate".
# It was already count-gated OFF since the 2026-07-26 cost decommission, so it created nothing and
# this removal changes NOTHING live -- state carries no mlflow_fargate resources. It is deleted
# rather than left gated because the gate was a reversible pause and the decision is now permanent.
#
# WHAT THIS GIVES UP, recorded so a future restore is not a surprise: the old block WAS the restore
# path (flip mlflow_enabled -> true and apply). Bringing MLflow back now means restoring this block
# from git history -- modules/mlflow_fargate/ still exists on disk, so it is a revert, not a
# rewrite. The ALB it owned is the reason the module had to be gated rather than partially deleted.
#
# DEPENDENCY WORTH KNOWING: the three training/certification jobdefs talk to MLflow over Cloud Map
# (http://mlflow.leviathan.local:5000), NOT through the deleted ALB. They have had no server to
# reach since 2026-07-26, so this changes nothing for them today -- but if MLflow tracking is ever
# wanted again, they are the consumers that care. The separate module.ecr_mlflow (which still holds
# 6 images) is intentionally NOT touched here.


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


# ---------------------------------------------------------------------------
# P3 morning-brief daily schedule (Phase 8 SECTION III). Ships DISABLED: the
# day-0 digest is a MANUAL submit the user reviews first; flip to ENABLED
# afterwards, then INSPECT the first cron fire (describe-jobs: the submitted
# job must be the ...-notifications jobdef at 1 vCPU/2 GiB — the universal-
# target Input key casing is only verifiable live). The jobdef is CLI-
# registered (jobs/utils/register_notifications_jobdef.py), referenced BY
# NAME; its baked default command/resources/retry make a dropped or miscased
# ContainerOverrides key harmless (the override below is redundant safety).
# ---------------------------------------------------------------------------
resource "aws_iam_role" "notifications_scheduler" {
  name = "${var.project_name}-${var.environment}-notifications-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# USER DIRECTIVE 2026-07-30: every SCHEDULED job submits to the ON-DEMAND queue, never spot.
# leviathan-dev-queue is FARGATE_SPOT -- fine for interruptible backfills, unprofessional for
# anything user-visible or publishing (a spot reclaim mid-run means a missed morning brief or a
# half-fired chain). Name-constructed rather than module.batch.ondemand_job_queue_arn because the
# ondemand queue resource is LIVE but UNIMPORTED (drift task): referencing the module resource
# from a -target'ed apply would force terraform to try to CREATE the already-existing queue.
# Swap to the module output once the drift reconciliation imports it.
locals {
  ondemand_job_queue_arn = "arn:aws:batch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job-queue/${var.project_name}-${var.environment}-queue-ondemand"
}

resource "aws_iam_role_policy" "notifications_scheduler" {
  name = "${var.project_name}-${var.environment}-notifications-scheduler-submit"
  role = aws_iam_role.notifications_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "batch:SubmitJob"
        Resource = [
          local.ondemand_job_queue_arn,
          "arn:aws:batch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job-definition/${var.project_name}-${var.environment}-notifications:*",
          # 2026-07-28 INCIDENT FIX (U2) -- the SAME unversioned-jobdef-ARN defect that killed the
          # pattern-records sweep (see the twin comment on the sweep policy below) has been killing the
          # MORNING BRIEF since the day it was armed. The schedule submits `...-notifications` with NO
          # `:revision` segment, the `:*` pattern above requires that segment, so every 12:00:08Z SubmitJob
          # was AccessDenied. Evidence, two independent ways: CloudTrail lookup-events on SubmitJob
          # (role leviathan-dev-notifications-scheduler, 07-26 and 07-27 12:00:08Z) AND AWS/Scheduler
          # InvocationDroppedCount, which shows a drop EVERY DAY since 2026-07-10 -- the day this schedule
          # flipped to ENABLED. 18 consecutive days, 0 briefs. Keep BOTH lines: `:*` covers a versioned
          # manual submit, the bare one covers the scheduler.
          "arn:aws:batch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job-definition/${var.project_name}-${var.environment}-notifications",
        ]
      },
      {
        # The schedule's dead-letter queue. EventBridge Scheduler writes the dropped event with the
        # SCHEDULE's execution role, so the grant belongs here (SQS needs no resource policy for a
        # same-account IAM principal).
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.notifications_scheduler_dlq.arn
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# W1(a)/U2 -- make a dead schedule ATTRIBUTABLE and NON-SELF-CLEARING.
#
# Correcting the incident write-up while installing the fix: these failures were NOT undetected. The
# group-level alarm `leviathan-dev-scheduler-target-errors` (silver_observability, AWS/Scheduler
# TargetErrorCount > 0, dim ScheduleGroup=default) is live, ENABLED, wired to two SNS topics, and it
# transitioned OK->ALARM->OK on EVERY one of the six failures (07-25/26/27 at 12:01Z and 23:01Z --
# alarm history read 2026-07-28). What failed was ATTRIBUTION and PERSISTENCE:
#   * AWS/Scheduler publishes NO per-schedule dimension (list-metrics: ScheduleGroup is the only one),
#     so the alarm can say "a schedule in the default group errored" and nothing more -- and 20+
#     schedules share that group;
#   * a Sum-over-5-minutes alarm self-clears 15 minutes later, so by morning everything reads OK.
# A DLQ fixes exactly those two things: the dropped event is a DURABLE object naming its own schedule
# and carrying the target input, and it sits in the queue until a human deletes it.
# ---------------------------------------------------------------------------
resource "aws_sqs_queue" "notifications_scheduler_dlq" {
  name                      = "${var.project_name}-${var.environment}-morning-brief-dlq"
  message_retention_seconds = 1209600 # 14 days (SQS max) -- a weekend + a vacation
  sqs_managed_sse_enabled   = true

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_metric_alarm" "notifications_scheduler_dlq_depth" {
  alarm_name        = "${var.project_name}-${var.environment}-morning-brief-dlq-depth"
  alarm_description = "The morning-brief schedule dead-lettered an invocation (target unreachable/denied). The message body names the schedule and carries the SubmitJob input. Drain only after the cause is fixed."
  namespace         = "AWS/SQS"
  metric_name       = "ApproximateNumberOfMessagesVisible"
  dimensions        = { QueueName = aws_sqs_queue.notifications_scheduler_dlq.name }
  statistic         = "Maximum"
  period            = 300
  # UNLIKE the TargetErrorCount alarm this does NOT self-clear: the metric stays > 0 for as long as the
  # message is in the queue, so the alarm holds until someone actually looks.
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [module.alerting.topic_arn]

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_scheduler_schedule" "notifications" {
  name  = "${var.project_name}-${var.environment}-morning-brief"
  state = "ENABLED" # day-0 dry-run reviewed 2026-07-10 (pipeline clean, 0 shocks today); cron live 12:00 UTC

  flexible_time_window {
    mode = "OFF"
  }
  schedule_expression = "cron(0 12 * * ? *)" # 12:00 UTC daily

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:batch:submitJob"
    role_arn = aws_iam_role.notifications_scheduler.arn
    input = jsonencode({
      JobName       = "build-notifications"
      JobQueue      = local.ondemand_job_queue_arn
      JobDefinition = "${var.project_name}-${var.environment}-notifications"
      # Redundant safety — the dedicated jobdef already bakes these as its defaults:
      ContainerOverrides = {
        Command = ["jobs/batch/build_notifications_task.py"]
        ResourceRequirements = [
          { Type = "VCPU", Value = "1" },
          { Type = "MEMORY", Value = "2048" },
        ]
      }
      RetryStrategy = { Attempts = 2 }
    })

    # A dropped invocation now lands somewhere DURABLE. Scheduler treats an AccessDenied from the target
    # as non-retryable and drops it immediately (InvocationDroppedCount == TargetErrorCount == 1/day
    # through the whole outage -- no retry storm), so the event reaches this queue on the first failure
    # with no retry_policy change needed here.
    dead_letter_config {
      arn = aws_sqs_queue.notifications_scheduler_dlq.arn
    }
  }
}


# ---------------------------------------------------------------------------
# Phase D D-W1 / A-W0: weekly USDA ESR ingest schedule. Now codified ENABLED (was
# DISABLED in code while live drifted ENABLED out of band since ~7/14). A-W0 reconciles
# code==live so no future `-target` apply can silently disable the working ingest (the
# #1 landmine). The three original enable prerequisites -- (a) the leviathan/dev/fas-api-key
# secret, (b) the usda_esr_fetch jobdef + execution-role GetSecretValue grant, (c) a
# reviewed weekly dry-probe -- were satisfied out of band (B2 task #103). Fires the fetch
# jobdef every Thursday 14:00 UTC -- ESR publishes ~08:00 ET / 13:00 UTC (fetch_usda_esr.py:45-46).
# The jobdef is terraform-managed (batch module usda_esr_fetch) and referenced BY NAME so
# the schedule tracks the latest active revision; its baked command/sizing make the
# ContainerOverrides below redundant safety (mirrors the morning-brief rationale).
# ---------------------------------------------------------------------------
resource "aws_iam_role" "esr_ingest_scheduler" {
  name = "${var.project_name}-${var.environment}-esr-ingest-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "esr_ingest_scheduler" {
  name = "${var.project_name}-${var.environment}-esr-ingest-scheduler-submit"
  role = aws_iam_role.esr_ingest_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "batch:SubmitJob"
      Resource = [
        local.ondemand_job_queue_arn,
        "arn:aws:batch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job-definition/${var.project_name}-${var.environment}-usda-esr-fetch:*",
      ]
    }]
  })
}

resource "aws_scheduler_schedule" "esr_weekly_ingest" {
  name  = "${var.project_name}-${var.environment}-esr-weekly-ingest"
  state = "ENABLED" # A-W0 drift reconcile: codifies the out-of-band B2 (task #103) enable done ~7/14; live has been ENABLED since. A full apply must NOT revert this -- see docs/private/TF_TARGET_CHECKLIST.md.

  flexible_time_window {
    mode = "OFF"
  }
  schedule_expression = "cron(0 14 ? * THU *)" # Thursdays 14:00 UTC, after ESR publishes (~13:00 UTC)

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:batch:submitJob"
    role_arn = aws_iam_role.esr_ingest_scheduler.arn
    input = jsonencode({
      JobName       = "usda-esr-fetch"
      JobQueue      = local.ondemand_job_queue_arn
      JobDefinition = "${var.project_name}-${var.environment}-usda-esr-fetch"
      # Redundant safety -- the usda_esr_fetch jobdef already bakes this command + sizing:
      ContainerOverrides = {
        Command = ["jobs/ingest/fetch_usda_esr.py", "--mode", "weekly", "--skip-existing-s3"]
        ResourceRequirements = [
          { Type = "VCPU", Value = "0.25" },
          { Type = "MEMORY", Value = "512" },
        ]
      }
      RetryStrategy = { Attempts = 2 }
    })
  }
}

# ---------------------------------------------------------------------------
# T2B pattern-records DAILY SWEEP schedule (T2B_PATTERN_RECORDS_PLAN.md sec 7
# step 5 / D10). Ships state = "DISABLED", by contract, not by accident:
#
#   the day-0 doctrine is ONE MANUAL run first (submit wrapper, dry-run ->
#   shadow -> canonical), a human review of the built records, and only THEN a
#   flip to ENABLED. That is the P3 morning-brief pattern, and the reason it
#   matters more here than there: a ledger row is a PERMANENT record of what the
#   engine decided at T (never recomputed -- plan non-goal 6), so a mis-wired
#   first fire does not just fail, it writes a wrong verdict into history that
#   the write-guard then protects.
#
# The whole block is count-gated on the pinned image digest, so nothing lands
# until rollout step 3.
#
# Cron 23:00 UTC daily: LATE in the UTC day, so every daily/weekly ingest and
# gold rebuild has landed before the replay reads the pg mirror, while still
# safely inside the same UTC day (the task stamps asof = today UTC and REFUSES a
# past-asof daily sweep -- a 00:30 fire would silently record the NEXT day).
#
# The jobdef is terraform-managed and referenced BY NAME so the schedule tracks
# the latest ACTIVE revision; its baked command/sizing make the
# ContainerOverrides below redundant safety (the morning-brief rationale).
# RetryStrategy is deliberately ABSENT: a publishing sweep must not be silently
# re-attempted (a re-run is idempotent, but it should be a deliberate act).
# Rollback at every stage = set state back to "DISABLED" (no redeploy).
# ---------------------------------------------------------------------------
resource "aws_iam_role" "pattern_records_scheduler" {
  count = var.pattern_records_image_digest != "" ? 1 : 0

  name = "${var.project_name}-${var.environment}-pattern-records-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "pattern_records_scheduler" {
  count = var.pattern_records_image_digest != "" ? 1 : 0

  name = "${var.project_name}-${var.environment}-pattern-records-scheduler-submit"
  role = aws_iam_role.pattern_records_scheduler[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "batch:SubmitJob"
        Resource = [
          local.ondemand_job_queue_arn,
          "arn:aws:batch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job-definition/${module.batch.pattern_records_sweep_job_definition_name}:*",
          # 2026-07-28 INCIDENT FIX -- the sweep was ARMED AND SILENTLY DEAD for 3 nights. The schedule
          # submits with the UNVERSIONED jobdef name, and Batch then authorizes against the ARN WITHOUT a
          # `:revision` segment; the `:*` pattern above requires that segment to exist, so every nightly
          # SubmitJob was AccessDenied (CloudTrail 07-26/07-27 23:00:38Z) and, with MaximumRetryAttempts=0
          # and no DLQ, the fire was simply gone. ("Invisible" was the original wording and it is too
          # strong -- re-probed 2026-07-28: the group TargetErrorCount alarm DID fire and self-clear on
          # every one of them. What was missing is attribution and persistence; see the DLQ block below.)
          # iam simulate-principal-policy: `...sweep:2` -> allowed,
          # `...sweep` (bare) -> implicitDeny. The bare ARN below closes exactly that gap. Keep BOTH lines:
          # `:*` covers versioned submits (manual runs pin a revision), the bare one covers the scheduler.
          "arn:aws:batch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job-definition/${module.batch.pattern_records_sweep_job_definition_name}",
        ]
      },
      {
        # DLQ write. A SEPARATE statement on purpose: folding sqs:SendMessage into the Action list above
        # would grant BOTH actions on BOTH resource sets (batch:SubmitJob on the queue is harmless, but
        # sqs:SendMessage on a job-definition ARN is the kind of accidental widening this incident is
        # already about). The write is performed BY THIS ROLE -- Scheduler assumes it to dead-letter.
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.pattern_records_scheduler_dlq[0].arn
      },
    ]
  })
}

resource "aws_sqs_queue" "pattern_records_scheduler_dlq" {
  count = var.pattern_records_image_digest != "" ? 1 : 0

  name                      = "${var.project_name}-${var.environment}-pattern-records-sweep-dlq"
  message_retention_seconds = 1209600 # 14 days (SQS max)
  sqs_managed_sse_enabled   = true

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_metric_alarm" "pattern_records_scheduler_dlq_depth" {
  count = var.pattern_records_image_digest != "" ? 1 : 0

  alarm_name        = "${var.project_name}-${var.environment}-pattern-records-sweep-dlq-depth"
  alarm_description = "The nightly pattern-records sweep was DROPPED before it ever reached Batch (the 07-25/26/27 AccessDenied class). A ledger row is a permanent record of what the engine decided at T, so a missed night is a permanent hole in the as-of grid -- investigate, fix, re-fire with an explicit --asof, and only then drain this queue."
  namespace         = "AWS/SQS"
  metric_name       = "ApproximateNumberOfMessagesVisible"
  dimensions        = { QueueName = aws_sqs_queue.pattern_records_scheduler_dlq[0].name }
  statistic         = "Maximum"
  period            = 300
  # Holds ALARM until the queue is drained -- the property the 5-minute TargetErrorCount alarm lacks
  # (it went OK->ALARM->OK inside 15 minutes on all six failures and read OK by morning).
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [module.alerting.topic_arn]

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# The group-wide drop counter, alarmed for the first time. TargetErrorCount ("the target returned an
# error") is already alarmed in silver_observability; InvocationDroppedCount is the strictly worse event
# -- Scheduler GAVE UP and the fire is gone. Measured over the incident window they were identical
# (1/day each per dead schedule, no retry storm), but they are not the same failure: a target that errors
# and is retried into success never increments this one. Group-scoped because AWS/Scheduler publishes no
# per-schedule dimension (list-metrics, 2026-07-28: ScheduleGroup is the ONLY dimension) -- which is also
# why the DLQs above exist: the dropped event body is the only per-schedule attribution that exists.
# Read before writing this: the counter shows a drop EVERY DAY since 2026-07-10 (25 in July), i.e. the
# morning brief has been dead since it was armed and nobody could tell from the group alarm alone.
resource "aws_cloudwatch_metric_alarm" "scheduler_invocations_dropped" {
  alarm_name          = "${var.project_name}-${var.environment}-scheduler-invocations-dropped"
  alarm_description   = "EventBridge Scheduler DROPPED >0 invocations in the default group (retries exhausted or a non-retryable target error -- e.g. an AccessDenied SubmitJob). The fire is gone; the schedule will not self-heal. Attribution: read the per-schedule DLQs."
  namespace           = "AWS/Scheduler"
  metric_name         = "InvocationDroppedCount"
  dimensions          = { ScheduleGroup = "default" }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [module.alerting.topic_arn]

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_scheduler_schedule" "pattern_records_sweep" {
  count = var.pattern_records_image_digest != "" ? 1 : 0

  name  = "${var.project_name}-${var.environment}-pattern-records-sweep"
  state = "ENABLED" # day-0 SATISFIED 2026-07-25: dry-run -> shadow (543 records reviewed) -> canonical live; user-directed enable

  flexible_time_window {
    mode = "OFF"
  }
  schedule_expression = "cron(0 23 * * ? *)" # 23:00 UTC daily, after the day's ingests land

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:batch:submitJob"
    role_arn = aws_iam_role.pattern_records_scheduler[0].arn
    input = jsonencode({
      JobName       = "pattern-records-sweep"
      JobQueue      = local.ondemand_job_queue_arn
      JobDefinition = module.batch.pattern_records_sweep_job_definition_name
      # Redundant safety -- the jobdef already bakes this command + sizing. NOTE the
      # deliberate absence of --asof: the task defaults to today UTC (a baked date rots).
      ContainerOverrides = {
        Command = ["jobs/batch/pattern_records_sweep_task.py", "--publish-mode", "canonical"]
        ResourceRequirements = [
          { Type = "VCPU", Value = "2" },
          { Type = "MEMORY", Value = "8192" },
        ]
      }
    })

    # EXPLICIT override of the EventBridge Scheduler 185/86400 platform default (the
    # retry-policy trap documented in modules/eventbridge/main.tf). maximum_retry_attempts=0:
    # a failed sweep is re-fired deliberately, never 185 times into a partial publish.
    retry_policy {
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 3600
    }

    # maximum_retry_attempts = 0 means EVERY failure is terminal on the first try -- which is the right
    # call for a publishing job and is exactly why this schedule needed a DLQ more than any other. The
    # 07-25/26/27 fires produced InvocationDroppedCount = 1/night and left NOTHING behind; with this the
    # dropped event (schedule name + the full SubmitJob input) is durable for 14 days.
    dead_letter_config {
      arn = aws_sqs_queue.pattern_records_scheduler_dlq[0].arn
    }
  }
}

# The ONLY canonical-publish authority the sweep holds: kms:Sign on the A-W1 publish-signer
# CMK, which lets the scheduled container self-mint its short-lived PublishApproval
# (publish_guard KMS mode; LEVIATHAN_APPROVAL_MODE=kms + LEVIATHAN_KMS_KEY_ID are set on the
# jobdef). GetPublicKey is the verify half. DELETING THIS ONE RESOURCE is the kill-switch:
# without it --publish-mode canonical fails closed at authorize_publish and the sweep can
# still run dry-run/shadow. Same shape as silver_publisher_kms_sign above.
resource "aws_iam_role_policy" "pattern_records_kms_sign" {
  count = var.pattern_records_image_digest != "" ? 1 : 0

  name = "${var.project_name}-${var.environment}-pattern-records-kms-sign"
  role = module.iam.pattern_records_job_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "PublishSignerKmsSign"
      Effect   = "Allow"
      Action   = ["kms:Sign", "kms:GetPublicKey"]
      Resource = aws_kms_key.publish_signer.arn
    }]
  })
}



# ---------------------------------------------------------------------------
# A-W1 -- R1 KMS-asymmetric runtime publish signer (the A2 fork).
#
# The state machine mints its own short-lived PublishApproval at promote time via
# kms:Sign on this CMK (private key never leaves KMS); verification uses the CACHED
# PUBLIC key, so it needs NO KMS grant and no KMS-holding identity. The two-role
# split (silver-publisher signs, silver-validator has NO KMS) is the SILVER-F014
# provenance -- and that provenance ALREADY EXISTS in module.iam (committed 4b3ec8fa):
# module.iam.aws_iam_role.silver_publisher / .silver_validator, with the exact physical
# names leviathan-dev-silver-{publisher,validator} that the code-side publish guard
# binds to (constants.SILVER_{PUBLISHER,VALIDATOR}_ROLE_NAME).
#
# DIVERGENCE FROM PLAN A-W1 / Section 5 (flagged, deliberate): the plan enumerates NEW
# root-level `aws_iam_role.silver_publisher` + `.silver_validator` because its ground
# truth (line 50) says the F014 roles "do NOT exist in state". They DO exist in CODE
# (module.iam). Creating same-named root roles would collide (EntityAlreadyExists) and
# would NOT be the role the guard checks. So A-W1's only genuinely-new grant -- kms:Sign
# on the CMK -- is attached to the EXISTING F014 publisher role below. The F014 publisher
# already carries s3:GetObject/PutObject on silver/* (+gold/*) via silver_publisher_base,
# and the F014 validator already is S3-read-only with NO KMS -- exactly the plan's asks.
# The F014 canonical-deny (silver_canonical_publish_approved=false) still fences silver/
# writes until approved; that gate is orthogonal to this KMS signing capability.
# ---------------------------------------------------------------------------
resource "aws_kms_key" "publish_signer" {
  description              = "${var.project_name}-${var.environment} R1 publish signer: asymmetric SIGN_VERIFY CMK for scheduled PublishApproval minting (kms:Sign by silver-publisher; verify via cached public key)."
  key_usage                = "SIGN_VERIFY"
  customer_master_key_spec = "ECC_NIST_P256"
  deletion_window_in_days  = 30
  enable_key_rotation      = false # rotation is unsupported for asymmetric CMKs

  # Standard root-enable key policy: IAM policies (the silver-publisher inline kms:Sign
  # below) govern access. Public-key caching (kms:GetPublicKey) is an out-of-band admin/build
  # step; the validator makes NO KMS call at verify time by design.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "EnableIAMPolicies"
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
      Action    = "kms:*"
      Resource  = "*"
    }]
  })

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_kms_alias" "publish_signer" {
  name          = "alias/${var.project_name}-${var.environment}-publish-signer"
  target_key_id = aws_kms_key.publish_signer.key_id
}

# The genuinely-new A-W1 grant: kms:Sign (+ GetPublicKey to self-cache) on the CMK, as an
# INLINE policy on the EXISTING F014 publisher role. Referencing module.iam's role NAME makes
# terraform create/settle that role before this policy, so a -target on THIS resource pulls the
# F014 publisher role into the graph (see the -target notes in the plan handoff).

# The single-task producers (fx et al) re-fetch raw+bronze inside their canonical run;
# those surfaces are non-golden intermediates (regenerable), so the publisher may write them.
# The MLflow bootstrap job (evidence-build jobdef, batch-job-role) writes the backend DSN secret once.
resource "aws_iam_role_policy" "batch_job_mlflow_secret_write" {
  name = "leviathan-dev-batch-job-mlflow-secret-write"
  role = "leviathan-dev-batch-job-role"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "MlflowDsnSecretWrite"
      Effect   = "Allow"
      Action   = ["secretsmanager:CreateSecret", "secretsmanager:PutSecretValue", "secretsmanager:DescribeSecret"]
      Resource = "arn:aws:secretsmanager:us-east-1:668891723125:secret:leviathan/dev/mlflow-backend-dsn-*"
    }]
  })
}

# Wave-3: source-API credentials for the modis (NASA Earthdata) + quandl (Nasdaq Data
# Link) fetchers. Batch injects containerProperties.secrets at container START via the
# EXECUTION role, so the read grant lives there (scoped to exactly these two secrets).
# The values never appear in task defs, logs, or the repo.
resource "aws_iam_role_policy" "batch_exec_wave3_source_secrets" {
  name = "leviathan-dev-batch-exec-wave3-source-secrets"
  role = "leviathan-dev-batch-execution-role"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "Wave3SourceSecretsRead"
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        "arn:aws:secretsmanager:us-east-1:668891723125:secret:leviathan/dev/earthdata-*",
        "arn:aws:secretsmanager:us-east-1:668891723125:secret:leviathan/dev/nasdaq-api-key-*",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "silver_publisher_intermediates" {
  name = "leviathan-dev-silver-publisher-intermediates"
  role = module.iam.silver_publisher_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "RawBronzeIntermediates"
      Effect = "Allow"
      Action = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
      Resource = [
        "arn:aws:s3:::leviathan-dev-shahem-001/raw/*",
        "arn:aws:s3:::leviathan-dev-shahem-001/bronze/*",
        "arn:aws:s3:::leviathan-dev-shahem-001",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "silver_publisher_kms_sign" {
  name = "${var.project_name}-${var.environment}-silver-publisher-kms-sign"
  role = module.iam.silver_publisher_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "PublishSignerKmsSign"
      Effect   = "Allow"
      Action   = ["kms:Sign", "kms:GetPublicKey"]
      Resource = aws_kms_key.publish_signer.arn
    }]
  })
}


# ---------------------------------------------------------------------------
# A-W2 -- SFN platform (ONE parameterized thin-contract machine) + Scheduler.
# step_functions holds the machine + exec role + log group; eventbridge holds the
# per-family schedules (placeholder-EMPTY here; they land in A-W6/A-W7 all DISABLED).
# silver_pipeline_topic_arn is passed as a CONSTRUCTED string (not the module output)
# to break the step_functions<->silver_observability cycle (A-W5 orch alarms depend on
# the machine ARN). The topic name is deterministic == module.silver_observability's.
# ---------------------------------------------------------------------------
module "step_functions" {
  source = "../../modules/step_functions"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  pass_role_arns = [
    module.iam.batch_job_role_arn,
    module.iam.batch_execution_role_arn,
    module.iam.silver_publisher_role_arn,
    module.iam.silver_validator_role_arn,
  ]

  alerts_topic_arn          = module.alerting.topic_arn
  silver_pipeline_topic_arn = "arn:aws:sns:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.project_name}-${var.environment}-silver-pipeline-alerts"

  # A-W7 Wave-3: serialize every phase Map so descriptor array ORDER is honored.
  # Wave-3 introduces ORDERED phases (weather silver: per-source b2s -> compact -> gold;
  # conab fetch: discover -> fetch). At the old MaxConcurrency=4 those raced -- and the
  # weather b2s/gold writers are latest_only DIRECT canonical writes, so the race
  # corrupts canonical before the gate can catch it. All live families' phase tasks are
  # minutes-scale; none rely on intra-phase parallelism for a budget.
  map_max_concurrency = 1
}

module "eventbridge" {
  source = "../../modules/eventbridge"

  project_name      = var.project_name
  environment       = var.environment
  aws_region        = var.aws_region
  state_machine_arn = module.step_functions.state_machine_arn

  # Placeholder-EMPTY: per-family schedules (family -> {cron, input_json}) land in A-W6/A-W7,
  # every one created state="DISABLED".
  schedules = {
    for k, v in var.dag_schedules : k => {
      cron       = v.cron
      enabled    = v.enabled
      input_json = replace(v.input_json, "$${state_machine_arn}", module.step_functions.state_machine_arn)
    }
  }
}

# ---------------------------------------------------------------------------
# SILVER-F082 addendum (2026-07-30, user-approved): the freshness POLLER schedule.
# Discovery that forced this: FreshnessLagDays had ZERO datapoints for ANY family in the 7 days
# before 2026-07-30 -- scripts/silver/freshness_poller.py existed but NOTHING scheduled it, so all
# 26 freshness alarms (treat_missing_data=breaching, by design) had been evaluating an absent
# metric since they were applied. The first manual emit moved 22 families to OK and exposed 4
# genuinely stale ones, which is exactly the signal the layer was built to carry. Daily at 12:30
# UTC; a MISSED day surfaces as missing-data breaching on every family, which is honest -- so no
# DLQ and no retries beyond the scheduler's one delivery (mirrors the sweep's 0-retry reasoning,
# with the opposite conclusion on DLQ because a poller miss self-announces).
# ---------------------------------------------------------------------------
resource "aws_iam_role" "freshness_poller_scheduler" {
  name = "${var.project_name}-${var.environment}-freshness-poller-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_iam_role_policy" "freshness_poller_scheduler" {
  name = "${var.project_name}-${var.environment}-freshness-poller-scheduler"
  role = aws_iam_role.freshness_poller_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "batch:SubmitJob"
      Resource = [
        local.ondemand_job_queue_arn,
        "arn:aws:batch:${var.aws_region}:*:job-definition/${var.project_name}-${var.environment}-raw-ingest-runner*",
      ]
    }]
  })
}

# cloudwatch:PutMetricData for the poller's emit, on the raw-landing job role it runs under.
# Namespace-scoped via the condition key -- the poller writes Leviathan/Silver and nothing else.
resource "aws_iam_role_policy" "batch_job_freshness_put_metric" {
  name = "${var.project_name}-${var.environment}-freshness-put-metric"
  role = module.iam.batch_job_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "cloudwatch:PutMetricData"
      Resource  = "*"
      Condition = { StringEquals = { "cloudwatch:namespace" = "Leviathan/Silver" } }
    }]
  })
}

resource "aws_scheduler_schedule" "freshness_poller" {
  name  = "${var.project_name}-${var.environment}-freshness-poller"
  state = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }
  schedule_expression = "cron(30 12 * * ? *)" # 12:30 UTC daily, after the overnight publish wave

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:batch:submitJob"
    role_arn = aws_iam_role.freshness_poller_scheduler.arn
    input = jsonencode({
      JobName       = "freshness-poller"
      JobQueue      = local.ondemand_job_queue_arn
      JobDefinition = "${var.project_name}-${var.environment}-raw-ingest-runner"
      ContainerOverrides = {
        # INLINE, deliberately: the worker image copies src/ + jobs/ + configs/ + sql/ but NOT
        # scripts/, so ["scripts/silver/freshness_poller.py"] would die at container start -- the
        # exact silently-dead failure the 2026-07-28 sweep incident documents above. The shared
        # logic (poll_targets / newest_last_modified / lag_days / metric_data_for) lives in
        # leviathan.silver.freshness, which IS in the image; this is only the thin emit loop from
        # scripts/silver/freshness_poller.py. If the Dockerfile ever gains COPY scripts/, replace
        # this with the script path and delete the inline form.
        Command = ["-c", join("\n", [
          "import boto3, datetime as dt",
          "from leviathan.silver.freshness import poll_targets, newest_last_modified, lag_days, metric_data_for, METRIC_NAMESPACE",
          "now = dt.datetime.now(dt.timezone.utc)",
          "s3 = boto3.client('s3'); cw = boto3.client('cloudwatch')",
          "md = []",
          "for t in sorted(poll_targets(), key=lambda x: x.table):",
          "    pages = s3.get_paginator('list_objects_v2').paginate(Bucket=t.bucket, Prefix=t.prefix)",
          "    objs = ((o['Key'], o['LastModified']) for page in pages for o in page.get('Contents', []) or [])",
          "    lag = lag_days(newest_last_modified(objs), now)",
          "    if lag is None:",
          "        print('EMPTY ' + t.table)",
          "        continue",
          "    print('%-42s lag_days=%.2f' % (t.table, lag))",
          "    md.extend(metric_data_for(t.table, t.family, lag, timestamp=now))",
          "for i in range(0, len(md), 20):",
          "    cw.put_metric_data(Namespace=METRIC_NAMESPACE, MetricData=md[i:i+20])",
          "print('put %d datapoints' % len(md))",
        ])]
      }
    })
    retry_policy {
      maximum_retry_attempts       = 1
      maximum_event_age_in_seconds = 3600
    }
  }
}
