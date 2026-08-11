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

  # MOAT_WIDTH P1 (D-MW-4): name-based ARN for the Cohere key mounted as COHERE_API_KEY on
  # the serving task (native rerank lane) and on the evidence/eval jobdef. FLAT name --
  # leviathan-dev-cohere-api-key -- matching the Anthropic key's convention, not the
  # leviathan/dev/* path convention; every vendor key in this estate is created OUT-OF-BAND
  # (this one already exists). Still CONSTRUCTED, not looked up, for the same reason as the
  # three locals above: a data source resolves at PLAN time, so it makes every unrelated
  # apply in this env depend on the secret still existing -- a deleted/rotated-by-recreate
  # secret would block the whole estate's plan instead of just this grant. ECS/Batch
  # valueFrom resolves the name-based ARN for a same-region secret; the iam GetSecretValue
  # grant widens it with a trailing -* for the random suffix (live: ...-gFimH7).
  cohere_api_key_secret_arn = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:leviathan-dev-cohere-api-key"
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
  # D-MW-4: execution-role GetSecretValue for the serving task's + eval jobdef's COHERE_API_KEY
  # mount (one grant, both consumers -- they share this execution role).
  cohere_api_key_secret_arn = local.cohere_api_key_secret_arn
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

  # D-PR-7/D-PR-11 PRECONDITION. Ten families are held in state by revision ARN at
  # revisions 1-3 on ":latest" while live sits 3-5 revisions ahead on one digest.
  # The retry matrices and the four new timeouts RE-REGISTER all ten, so without
  # this they would be reverted to a mutable tag by a batch that is supposed to be
  # about reliability. Adopt the live pin FIRST; see the variable for the roster.
  worker_fleet_image_digest = var.worker_fleet_image_digest

  # D-PR-8/D-PR-37. NON-EMPTY MEANS TERRAFORM TAKES OVER A JOBDEF IT HAS NEVER OWNED:
  # leviathan-dev-silver-gate is live at rev 14 with no terraform resource behind it,
  # so this mints rev 15 -- a transcription of rev 14 plus the retry matrix that
  # retries ONLY exit 72, a 3600 s per-attempt timeout, and tags. Every family's gate
  # runs it on the next fire. See modules/batch/silver_gate.tf and the variable.
  silver_gate_image_digest = var.silver_gate_image_digest
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

  # D-PR-15(ii), 2026-08-04 -- the two families the poller EMITS and the generated tfvars map does
  # not cover, because they are not registry BATCH families. Declared HERE, inline and literal,
  # rather than in silver_observability.auto.tfvars.json: that file is machine-generated by
  # jobs/observability/silver_alarms.py and is under the D-EI-12 hold, so a hand edit would be
  # reverted by the next generator run AND would break the batch's "no .tfvars touched" assertion.
  # Values are the tables' OWN declared ceilings read from leviathan.silver.freshness, not invented:
  #   model_output    -> silver_model_predictions, ceiling 45d. Live lag 18.79d (2026-08-03).
  #   pattern_records -> gold_pattern_records,     ceiling  3d. Live lag  0.56d (2026-08-03).
  # Both are GREEN on arrival, which is the precondition for adding any treat_missing_data=breaching
  # alarm. WATCH ITEM, stated so it is not a surprise: silver_model_predictions has been rising by
  # exactly 1.0 d/day since ~2026-07-16 (nothing is writing it), so this alarm WILL go red around
  # 2026-08-30 unless a model run lands first. That is true signal on a real stall -- it is only
  # noted here so the first email is recognised as the alarm working, not as a new defect.
  silver_extra_family_slas = {
    model_output    = 45
    pattern_records = 3
  }

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
    # CONFIG-OF-RECORD ONLY -- the taskdef half of D-MW-4 ships OUT-OF-BAND (register the new
    # revision FROM the live one via scripts/ops/register_serving_taskdef.py, then
    # update-service --force-new-deployment). Applying this through module.serving would mint a
    # revision from terraform's STALE config and poison every latest-ACTIVE consumer (submit_eval
    # parity, the promote runbook -- both resolve the family by name). This line rides the
    # post-freeze tf batch (task #25), which must re-diff live vs config at execution time.
    COHERE_API_KEY = local.cohere_api_key_secret_arn
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
  #    AMENDED D-MW-4 (MOAT_WIDTH P1): the value flips "bedrock" -> "cohere", the NATIVE Cohere API
  #    (1,000 req/min instead of the account-wide 3/min Bedrock bucket -- the quota was the binding
  #    constraint on walk width). Bedrock stays intact as a one-key rollback ("bedrock"), bge as "bge".
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
    # CONFIG-OF-RECORD ONLY -- ships with the taskdef half of D-MW-4, out-of-band from the live
    # revision (register from live via scripts/ops/register_serving_taskdef.py, never mint from this
    # config). It is written here in the SAME commit as the COHERE_API_KEY secret above because
    # without it the next module.serving apply would silently un-ship P1 back onto the 3/min Bedrock
    # lane. Rides the post-freeze tf batch (task #25), which re-diffs live vs config at execution time.
    GRAPHRAG_RERANK_BACKEND  = "cohere"
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
      # D-PR-38, 2026-08-04 -- THE SUBMIT-TIME `RetryStrategy` OVERRIDE IS REMOVED.
      #
      # It used to read `RetryStrategy = { Attempts = 2 }`. A submit-time RetryStrategy does NOT
      # merge with the job definition's -- SubmitJob REPLACES the jobdef's retryStrategy object
      # wholesale. So this key silently guaranteed that ANY `evaluateOnExit` matrix ever armed on
      # `leviathan-dev-notifications` (D-PR-7/D-PR-37) would never apply on the 12:00Z fire, while
      # D-PR-7's acceptance test (`describe-job-definitions` shows a retryStrategy) still reported
      # GREEN. That is a green-acceptance-over-a-dead-mechanism -- the same shape as the T2b
      # write-guard incident, and the reason the class is worth removing rather than editing.
      #
      # REMOVING IT CHANGES NOTHING TODAY, which is what makes it safe to land unsmoked. Live read
      # 2026-08-04: `leviathan-dev-notifications:2` bakes `{attempts: 2, evaluateOnExit: []}`
      # (jobs/utils/register_notifications_jobdef.py:80), byte-identical in effect to the override
      # it replaced. With the key gone the jobdef's own strategy governs -- so the retry posture is
      # unchanged now, and it becomes CORRECTABLE at the jobdef, which is where D-PR-7/D-PR-39 aim.
      #
      # DO NOT RE-ADD IT to change retry behavior. The knob is the jobdef (that registrar), never
      # the schedule payload. Same rule for the ContainerOverrides above -- those are deliberate
      # redundant safety that mirrors the baked defaults, not a divergent configuration.
      #
      # `leviathan-dev-esr-weekly-ingest`, the OTHER schedule D-PR-38 names, needs no edit: the
      # whole schedule was deleted by D-PR-15(iii) (see the block below) and `list-schedules` at
      # 2026-08-04 confirms it is gone. `leviathan-dev-esr_weekly` (the surviving SFN chain) targets
      # `aws-sdk:sfn:startExecution` and carries no RetryStrategy key at all. This was the last one.
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
# D-PR-15(iii), 2026-08-04 -- THE DUPLICATE 14:00Z THURSDAY ESR FIRE IS REMOVED.
#
# `leviathan-dev-esr-weekly-ingest` (a DIRECT batch:submitJob of the fetch leg) and
# `leviathan-dev-esr_weekly` (the SFN family chain, module.eventbridge + dag_schedules) both fired at
# `cron(0 14 ? * THU *)`, both ENABLED. This block -- the schedule, its role and its policy -- was
# the direct one. It is DELETED, not disabled, and the three findings that decide it are all live
# reads from 2026-08-04, not inference:
#
#   1. IT IS REDUNDANT BY CONSTRUCTION. `configs/silver/dags/esr_weekly.json` phase 1 submits
#      `leviathan-dev-usda-esr-fetch` with the IDENTICAL command
#      (`jobs/ingest/fetch_usda_esr.py --mode weekly --skip-existing-s3`) before bronze and silver.
#      The SFN chain does everything this schedule did, plus the gate and the promote.
#   2. THE SFN CHAIN WORKS. Execution `usda_esr-sched-ef6a6b58-...` at 2026-07-30T14:00Z SUCCEEDED,
#      and six Batch jobs (`usda_esr-*`, `usda_esr-gate-*`, `usda_esr-reconcile-*`) ran under it.
#   3. THIS SCHEDULE HAS NEVER RUN, NOT ONCE. CloudTrail, 2026-07-30T14:00:39Z: role
#      `leviathan-dev-esr-ingest-scheduler`, SubmitJob `usda-esr-fetch` -> **AccessDenied**. It is
#      the SAME unversioned-jobdef-ARN defect that killed the morning brief for 18 days and the
#      pattern-records sweep for 3 nights: the schedule submits the BARE family name and the policy
#      granted only the `:*` (versioned) ARN. The 07-28 fix was applied to those two roles and NOT to
#      this one -- `aws iam get-role-policy` on the live role still shows the `:*` line alone. Zero
#      Batch jobs named `usda-esr-fetch` exist in the account's history.
#
# CONSEQUENCE FOR THE PLAN'S OWN SUSPICION, corrected here rather than carried: section 3(h)(iii)
# reads this duplicate as "very likely implicated in the silver_esr dead leg" through a lease race.
# THAT IS DISCONFIRMED -- a schedule that never submitted a job cannot have raced a lease. The
# `silver_esr` lag (72.11d on 2026-08-03, still climbing 1.0/day) has a different cause: the chain's
# own `chain_shape` is `fetch->bronze(as_of)->silver_esr_compact`, so nothing in it writes the wide
# `silver_esr` table at all, while the gate still lists it. `silver_esr_compact` is 4.93d and
# healthy. That is a chain-shape defect and it belongs to whoever owns the ESR destination work; it
# is NOT fixed, and NOT worsened, by this deletion.
#
# DELETING ALSO DISCHARGES D-PR-15(v) (`esr-weekly-ingest` had `MaximumRetryAttempts: 185` and no
# DLQ) -- there is nothing left to dead-letter. ROLLBACK is `git revert` of this hunk PLUS the bare
# job-definition ARN the policy always needed; restoring it as-is would restore a dead schedule.
# ---------------------------------------------------------------------------

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

  # D-PR-12: the fleet DLQ's depth alarm. All 25 sfn:startExecution schedules had NO dead-letter
  # queue, so a fire that never became an execution left nothing behind and the only signal was two
  # group-scoped, self-clearing AWS/Scheduler alarms that cannot name the family.
  alert_topic_arn = module.alerting.topic_arn

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
# UTC; a MISSED day surfaces as missing-data breaching on every family, which is honest.
#
# D-PR-15(iv) + D-PR-43, 2026-08-04 -- THE "NO DLQ" REASONING IS REVERSED, AND WHY.
# The original note above argued a DLQ was unnecessary "because a poller miss self-announces". It
# does self-announce -- 21 TIMES. All 26 FreshnessLagDays alarms are treat_missing_data=breaching
# (verified live: 26 breaching, 5 currently in ALARM, so 21 currently OK), and they all read ONE
# daily job that has `MaximumRetryAttempts: 1`, no DLQ, and HAS already failed once
# (`freshness-poller-smoke`, exit 1, 2026-07-30T14:34Z). One missed cycle transitions all 21 OK
# alarms to ALARM together: ONE cause, TWENTY-ONE emails -- the largest unmodelled multiplier in the
# estate, and nearly the whole 14-day email budget. "Self-announcing" is exactly the failure mode,
# not the mitigation. The DLQ below makes a DROPPED fire (the case where the alarms are the only
# announcement) durable, attributable and non-self-clearing, so the miss can be seen and re-fired
# BEFORE the 21 alarms roll over at the next evaluation period.
# NOT closed here: the poller's own POSITIVE liveness alarm (the ratified other half of D-PR-43) --
# a DLQ catches a dropped invocation, not a job that starts and dies. That needs an emitter and is
# not an alarm-consolidation item.
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
    Statement = [
      {
        Effect = "Allow"
        Action = "batch:SubmitJob"
        Resource = [
          local.ondemand_job_queue_arn,
          "arn:aws:batch:${var.aws_region}:*:job-definition/${var.project_name}-${var.environment}-raw-ingest-runner*",
        ]
      },
      {
        # DLQ write, as its own statement (see the twin note on the sweep policy: never widen
        # sqs:SendMessage across a job-definition resource set). Scheduler assumes THIS role to
        # dead-letter, so the grant belongs here and SQS needs no resource policy for a same-account
        # principal.
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.freshness_poller_scheduler_dlq.arn
      },
    ]
  })
}

resource "aws_sqs_queue" "freshness_poller_scheduler_dlq" {
  name                      = "${var.project_name}-${var.environment}-freshness-poller-dlq"
  message_retention_seconds = 1209600 # 14 days (SQS max)
  sqs_managed_sse_enabled   = true

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_metric_alarm" "freshness_poller_scheduler_dlq_depth" {
  alarm_name        = "${var.project_name}-${var.environment}-freshness-poller-dlq-depth"
  alarm_description = "The daily freshness poll was DROPPED before it reached Batch. This is the alarm to act on FIRST: 21 currently-OK FreshnessLagDays alarms are treat_missing_data=breaching and all read this one job, so an unremedied miss becomes 21 emails at the next evaluation period. Re-fire the poller, then drain."
  namespace         = "AWS/SQS"
  metric_name       = "ApproximateNumberOfMessagesVisible"
  dimensions        = { QueueName = aws_sqs_queue.freshness_poller_scheduler_dlq.name }
  statistic         = "Maximum"
  # Holds ALARM until drained -- the property the 5-minute group TargetErrorCount alarm lacks.
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [module.alerting.topic_arn]

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
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
        #
        # R7a FIX, 2026-08-04 -- THE INLINE COPY HAD DRIFTED FROM THE SCRIPT IT MIRRORS.
        # This loop called `poll_targets()`, which is REGISTRY-PURE by design (its docstring says so:
        # it is kept registry-pure so the registry-coverage pin in test_freshness_poller.py keeps
        # meaning what it says). The non-registry artifacts live in `EXTRA_TARGETS`, and only
        # `all_poll_targets()` returns both -- which is what scripts/silver/freshness_poller.py:78
        # has called since R7a landed. The inline copy was never updated, so the ONE artifact
        # EXTRA_TARGETS exists for, `graphrag_timeline_episodes`, was never polled.
        #
        # MEASURED before this edit (read-only, 2026-08-04), and this is the whole argument:
        #   FreshnessLagDays Table=graphrag_timeline_episodes  -> 0 datapoints, 07-28..08-04
        #   FreshnessLagDays Family=graphrag_evidence          -> 0 datapoints, same window
        #   FreshnessLagDays Family=usda_esr (control)         -> 4 datapoints, 08-01..08-04
        # The poller runs and emits every day; it simply never had this target in its list. R7a has
        # been carried as "code landed, image stale" -- but the code landed in the SCRIPT, and the
        # real gap is here, in the terraform-owned inline duplicate of that script.
        #
        # WHY getattr AND NOT A PLAIN IMPORT. The poller runs
        # `leviathan-dev-raw-ingest-runner:2`, which is NOT terraform-managed (referenced by bare
        # name; registered out of band) and is pinned to worker sha256:2f3efb7c, pushed
        # 2026-07-29T22:07Z. `all_poll_targets` first exists in commit 6b0b8ff7,
        # 2026-07-31T21:09+03:00 -- TWO DAYS LATER. A plain `from ... import all_poll_targets` on
        # that image is an ImportError at container start, which would take the poller down and with
        # it ALL 26 freshness metrics: a fence that kills the thing it measures. The getattr keeps
        # the 26 alive on the old image, adds the artifact the moment the jobdef is repinned to a
        # current worker digest, and -- because a silent fallback is the failure mode this estate
        # keeps re-learning -- PRINTS which mode it ran in and how many targets it polled.
        #
        # THE REAL FIX IS THE REPIN of leviathan-dev-raw-ingest-runner onto a current worker image;
        # that is an out-of-band jobdef, not terraform's, so it is named here and not done here.
        # Until it happens the log line reads "targets=... mode=registry-only (EXTRA_TARGETS
        # UNAVAILABLE ...)" every day, which is the declaration that keeps this honest.
        #
        # This is also the precondition D-EI-12 holds the R7c alarm on: an alarm with
        # treat_missing_data="breaching" over a metric that has never had a datapoint is a permanent
        # red the moment it applies. Both this line AND the repin must land before that alarm unheld.
        Command = ["-c", join("\n", [
          "import boto3, datetime as dt",
          "from leviathan.silver import freshness as F",
          "from leviathan.silver.freshness import newest_last_modified, lag_days, metric_data_for, METRIC_NAMESPACE",
          "targets_fn = getattr(F, 'all_poll_targets', None)",
          "mode = 'registry+extra' if targets_fn else 'registry-only (EXTRA_TARGETS UNAVAILABLE -- repin leviathan-dev-raw-ingest-runner)'",
          "targets = sorted((targets_fn or F.poll_targets)(), key=lambda x: x.table)",
          "print('freshness poller: targets=%d mode=%s' % (len(targets), mode))",
          "now = dt.datetime.now(dt.timezone.utc)",
          "s3 = boto3.client('s3'); cw = boto3.client('cloudwatch')",
          "md = []",
          "for t in targets:",
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

    # D-PR-15(iv): after that one retry the poll is GONE and 21 breaching alarms are the only
    # announcement. The dropped event now lands somewhere durable that names this schedule.
    dead_letter_config {
      arn = aws_sqs_queue.freshness_poller_scheduler_dlq.arn
    }
  }
}

# ===========================================================================
# LANE 4 -- ARMING. Two scheduled units, BOTH CREATED DISABLED.
#
# They live here, at the end of envs/dev, rather than inside modules/batch or
# modules/iam, for the reason the pattern-records sweep and the freshness poller
# do: a scheduled unit is a role + a jobdef + a queue + a DLQ + an alarm + a
# cron, and splitting it across three modules is how "armed and silently dead"
# happened on 2026-07-25..27. Each unit below reads top to bottom in one place.
#
# TWO RULES BOTH UNITS OBEY, NEITHER OF THEM OPTIONAL:
#
#  1. state = "DISABLED" at creation. The apply that creates a schedule NEVER
#     also arms it. Arming is a second, separately-planned apply that flips one
#     attribute, and it happens only after the EXACT container command has been
#     smoke-tested on the EXACT jobdef and queue (the standing rule; the
#     repin-smoke-pull lesson). Rollback for either unit is the same flip back.
#
#  2. Every submitJob goes to local.ondemand_job_queue_arn, never the SPOT
#     queue leviathan-dev-queue. Standing rule; all four spot-queue failures on
#     the record were hand-submitted, and no schedule in this estate has ever
#     referenced it.
# ===========================================================================

# ---------------------------------------------------------------------------
# D-PR-4 (lane A arming) -- THE WEEKLY ECR PIN AUDIT.
#
# The post-push half of D-PR-4 is already live in scripts/build_push_worker.ps1
# and scripts/build_push_embedder.ps1 (Step 6: POST-PUSH FLEET AUDIT). It fires
# on a PUSH. This is the other half: the fleet also rots with no push at all --
# a jobdef repinned out of band, a lifecycle policy edited, a repo added -- and
# nothing notices until a CannotPullContainerError takes a scheduled family out.
#
# PLAIN MODE ONLY, deliberately: --config-drift goes RED on every pinned digest
# that has no S3 manifest sidecar, and "no sidecar" is the expected BOOTSTRAP
# state (the auditor's own run_config_drift comment says so). Wiring it in would
# red the weekly mail on a healthy estate, and a fence that always fails is a
# fence operators learn to ignore. Revisit when every TOP-revision digest has a
# sidecar and that is MEASURABLY true, not assumed.
#
# The horizon flags are passed EXPLICITLY (--warn-builds 3 --fail-builds 1) so
# this schedule keeps its declared D-PR-30 contract even if the script's own
# defaults are retuned later.
#
# COUNT-GATE: the whole unit hangs off var.ecr_pin_audit_image_digest. Set it
# empty and every resource below disappears -- role, jobdef, scheduler role,
# DLQ, alarm, schedule. Nothing here writes to S3, ECR, Batch or the data lake;
# the six IAM actions are read-only, so deleting the schedule removes the entire
# behaviour and leaves two inert roles.
# ---------------------------------------------------------------------------

locals {
  ecr_pin_audit_enabled = var.ecr_pin_audit_image_digest != "" ? 1 : 0

  # ONE definition of the argv, read by BOTH the jobdef's baked command and the
  # schedule's ContainerOverrides. The override is redundant with the baked
  # command ON PURPOSE (the morning-brief pattern): it is also the string the
  # pre-arm smoke submits, so what is smoked and what fires are literally the
  # same list rather than two hand-copied ones that drift.
  ecr_pin_audit_command = [
    "scripts/ops/check_ecr_pinned_digests.py",
    "--region", var.aws_region,
    "--warn-builds", "3",
    "--fail-builds", "1",
  ]

  ecr_pin_audit_job_definition_name = "${var.project_name}-${var.environment}-ecr-pin-audit"

  # NAME-CONSTRUCTED ARNs, for the same reason local.ondemand_job_queue_arn above is
  # name-constructed rather than read off a module output: so the PLAN IS READABLE.
  #
  # A jobdef whose jobRoleArn references aws_iam_role...arn renders its ENTIRE
  # container_properties as "(known after apply)" -- the image digest, the
  # MANAGED_BY_AWS delivery marker and the 0.5/1024 sizing all vanish from the plan
  # text, and this estate's apply gate is a line-by-line read of that text. There is
  # no ambiguity to trade away: every ARN below is built from the SAME name local the
  # resource itself uses, so the two cannot disagree by a typo. Creation ORDER is
  # preserved by explicit depends_on wherever a constructed ARN replaces a reference.
  ecr_pin_audit_job_role_name = "${var.project_name}-${var.environment}-ecr-pin-audit-job-role"
  ecr_pin_audit_job_role_arn  = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.ecr_pin_audit_job_role_name}"

  ecr_pin_audit_scheduler_role_name = "${var.project_name}-${var.environment}-ecr-pin-audit-scheduler"
  ecr_pin_audit_scheduler_role_arn  = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.ecr_pin_audit_scheduler_role_name}"

  ecr_pin_audit_dlq_name = "${var.project_name}-${var.environment}-ecr-pin-audit-dlq"
  ecr_pin_audit_dlq_arn  = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${local.ecr_pin_audit_dlq_name}"

  ecr_pin_audit_job_definition_arns = [
    # BOTH ARN FORMS -- the 2026-07-25/26/27 incident, verbatim. The schedule submits
    # the UNVERSIONED jobdef name and Batch authorizes against an ARN with NO
    # ":revision" segment, so a ":*"-only grant AccessDenies every single fire. A
    # manual run that pins a revision needs the ":*" form. Keep BOTH; deleting either
    # one re-opens a silent-dead schedule.
    "arn:aws:batch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job-definition/${local.ecr_pin_audit_job_definition_name}",
    "arn:aws:batch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job-definition/${local.ecr_pin_audit_job_definition_name}:*",
  ]
}

# THE P2 HOLE, CLOSED. iam simulate-principal-policy on leviathan-dev-batch-job-role
# (re-run read-only 2026-08-04) returns implicitDeny for ALL SIX actions the plain
# pass needs -- its only Batch grants are SubmitJob/DescribeJobs/TerminateJob. A weekly
# fire on a borrowed embedder jobdef would AccessDeny on the FIRST call
# (describe_job_definitions), traceback and exit non-zero: an IAM hole that reads
# exactly like an ECR outage. Hence a dedicated role, and hence the smoke.
resource "aws_iam_role" "ecr_pin_audit_job" {
  count = local.ecr_pin_audit_enabled

  name = local.ecr_pin_audit_job_role_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_iam_role_policy" "ecr_pin_audit_job" {
  count = local.ecr_pin_audit_enabled

  name = "${var.project_name}-${var.environment}-ecr-pin-audit-read"
  role = aws_iam_role.ecr_pin_audit_job[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      # Resource "*" ON PURPOSE, and it is not laziness:
      #  - the auditor DISCOVERS its repositories from live jobdef images, so a
      #    repo-scoped list turns the day a new repo appears into a denied
      #    GetLifecyclePolicy, which the auditor renders as UNPROVEN (exit 2) --
      #    a self-inflicted weekly false alarm;
      #  - batch:DescribeJobDefinitions and ecs:DescribeTaskDefinition do not
      #    support resource-level permissions AT ALL.
      # Every action here is READ-ONLY. There is no S3 grant: the sidecar fetcher
      # is constructed only under --config-drift, which this unit never passes.
      Action = [
        "ecr:DescribeImages",
        "ecr:GetLifecyclePolicy",
        "batch:DescribeJobDefinitions",
        "ecs:ListServices",
        "ecs:DescribeServices",
        "ecs:DescribeTaskDefinition",
      ]
      Resource = "*"
    }]
  })
}

# A DEDICATED jobdef, not a borrowed one (plan precondition P3).
# leviathan-dev-evidence-build:35 is the TOP embedder jobdef and it is 16 vCPU /
# 122880 MiB with a Ref::-parameterised command, on the shared batch-job-role that
# the internet-facing serving task also assumes. Borrowing it would pay 16 vCPU for
# a ~40-second read-only audit AND widen a role that already fronts the internet.
resource "aws_batch_job_definition" "ecr_pin_audit" {
  count = local.ecr_pin_audit_enabled

  name                  = local.ecr_pin_audit_job_definition_name
  type                  = "container"
  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image   = "${data.aws_ecr_repository.embedder.repository_url}@${var.ecr_pin_audit_image_digest}"
    command = local.ecr_pin_audit_command

    environment = [
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment },
      # DELIVERY (P4). This marker -- not the job NAME -- is what the live
      # leviathan-dev-batch-failed-scheduled metric filter matches today, with no
      # filter edit required. Without it a failed audit pages nobody, because the
      # account-wide batch-job-failed rule targets silver-pipeline-alerts and that
      # topic has zero subscriptions. See var.ecr_pin_audit_scheduled_marker.
      { name = var.ecr_pin_audit_scheduled_marker, value = "scheduler" },
    ]

    resourceRequirements = [
      { type = "VCPU", value = "0.5" },
      { type = "MEMORY", value = "1024" },
    ]

    executionRoleArn = module.iam.batch_execution_role_arn
    # Name-constructed (see the locals block): referencing the role resource would
    # render this whole container_properties as "(known after apply)" and hide the
    # digest, the marker and the sizing from the plan the apply gate reads.
    jobRoleArn = local.ecr_pin_audit_job_role_arn

    networkConfiguration = { assignPublicIp = "ENABLED" }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecr-pin-audit"
      }
    }
  })

  # The dependency the constructed ARN above no longer expresses implicitly. Batch
  # validates jobRoleArn at RegisterJobDefinition, so the role must exist first.
  depends_on = [aws_iam_role.ecr_pin_audit_job]

  # 2 entries, well under the 5-object API cap D-PR-37 trimmed the producer matrix
  # to. Exit 2 is the auditor's OWN "UNPROVEN -- retry, do not repin" verdict (an
  # ECR/Batch call failed, or a lifecycle policy could not be read as a listing-wide
  # count cap), so it is the one exit code worth re-attempting. Exit 1 is a real
  # finding and must NOT be retried into a second identical email.
  retry_strategy {
    attempts = 2
    evaluate_on_exit {
      on_exit_code = "2"
      action       = "RETRY"
    }
    evaluate_on_exit {
      on_reason = "*"
      action    = "EXIT"
    }
  }

  # Measured runtime of the plain pass is ~40 seconds. 900s is 20x headroom and
  # still bounded, so a hung ECR call cannot hold a Fargate task for hours.
  timeout {
    attempt_duration_seconds = 900
  }

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_iam_role" "ecr_pin_audit_scheduler" {
  count = local.ecr_pin_audit_enabled

  name = local.ecr_pin_audit_scheduler_role_name
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

resource "aws_iam_role_policy" "ecr_pin_audit_scheduler" {
  count = local.ecr_pin_audit_enabled

  name = "${var.project_name}-${var.environment}-ecr-pin-audit-scheduler-submit"
  role = aws_iam_role.ecr_pin_audit_scheduler[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "batch:SubmitJob"
        Resource = concat([local.ondemand_job_queue_arn], local.ecr_pin_audit_job_definition_arns)
      },
      {
        # A SEPARATE statement, not a folded Action list: sqs:SendMessage on a
        # job-definition ARN is exactly the accidental widening the sweep's own
        # comment warns about. Scheduler assumes this role to dead-letter.
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = local.ecr_pin_audit_dlq_arn
      },
    ]
  })
}

resource "aws_sqs_queue" "ecr_pin_audit_scheduler_dlq" {
  count = local.ecr_pin_audit_enabled

  name                      = local.ecr_pin_audit_dlq_name
  message_retention_seconds = 1209600 # 14 days (SQS max)
  sqs_managed_sse_enabled   = true

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_cloudwatch_metric_alarm" "ecr_pin_audit_scheduler_dlq_depth" {
  count = local.ecr_pin_audit_enabled

  alarm_name        = "${var.project_name}-${var.environment}-ecr-pin-audit-dlq-depth"
  alarm_description = "The weekly ECR pin audit was DROPPED before it reached Batch. The audit did not run, so NOTHING has been shown about the fleet's pin health this week -- read the dead-lettered event for the SubmitJob input, fix, re-fire by hand, and only then drain this queue."
  namespace         = "AWS/SQS"
  metric_name       = "ApproximateNumberOfMessagesVisible"
  dimensions        = { QueueName = local.ecr_pin_audit_dlq_name }
  statistic         = "Maximum"
  period            = 300
  # Holds ALARM until the queue is drained -- the property the 5-minute group-wide
  # TargetErrorCount alarm lacks (it self-cleared inside 15 minutes on all six of
  # the sweep's failures and read OK by morning).
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [module.alerting.topic_arn]

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_scheduler_schedule" "ecr_pin_audit" {
  count = local.ecr_pin_audit_enabled

  name = "${var.project_name}-${var.environment}-ecr-pin-audit"

  # CREATED DISABLED. Flip to "ENABLED" in a SECOND apply, and only after the
  # Step-4 smoke has passed all four of its acceptance clauses:
  #   1. status SUCCEEDED, exitCode 0 (an AccessDenied traceback means the P2 role
  #      above did not close the hole and the run proves nothing about ECR);
  #   2. the log carries "pinned references audited: N digest pair(s) + M tag
  #      reference(s) across R repo(s)" with R >= 5 -- a run that audited one repo
  #      has silently lost the fleet;
  #   3. the LAST line is the green "OK: every reference resolves, none within the
  #      declared build horizon" -- not merely the absence of a FAIL;
  #   4. the numbers match a laptop run of the same command in the same hour.
  # ENABLED 2026-08-04 after the smoke accept test passed all four points (job 4b25b43b:
  # SUCCEEDED, exit 0, 101 digest pairs across 5 repos, zero MISSING[TOP]/UNPROVEN/IMMINENT,
  # agreement with the same-hour laptop run). First fire MON 05:30Z.
  state = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  # Weekly, 05:30 UTC Monday. Chosen to land BEFORE the week's first heavy fires
  # (08:00Z weather, 14:00Z ESR, 22:30Z CEPEA, 23:00Z sweep) and off the :00 minute
  # every other cron uses, so a red arrives with a full working day of margin. The
  # schedule is UTC; the host renders it 08:30 +03:00 -- do not read the local time
  # as the contract.
  schedule_expression = "cron(30 5 ? * MON *)"

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:batch:submitJob"
    role_arn = local.ecr_pin_audit_scheduler_role_arn

    input = jsonencode({
      JobName  = "ecr-pin-audit"
      JobQueue = local.ondemand_job_queue_arn
      # The UNVERSIONED family name, so the schedule always submits the latest ACTIVE
      # revision -- and the exact string the scheduler role's bare job-definition ARN
      # grant authorizes.
      JobDefinition = local.ecr_pin_audit_job_definition_name
      ContainerOverrides = {
        Command = local.ecr_pin_audit_command
      }
    })

    # EXPLICIT override of the EventBridge Scheduler 185/86400 platform default.
    # 2 retries is safe here in a way it is NOT on the sweep: this job is READ-ONLY,
    # so a retry cannot double-write anything.
    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }

    dead_letter_config {
      arn = local.ecr_pin_audit_dlq_arn
    }
  }

  # The dependencies the constructed ARNs above no longer express implicitly.
  depends_on = [
    aws_iam_role.ecr_pin_audit_scheduler,
    aws_iam_role_policy.ecr_pin_audit_scheduler,
    aws_batch_job_definition.ecr_pin_audit,
    aws_sqs_queue.ecr_pin_audit_scheduler_dlq,
  ]
}

# ---------------------------------------------------------------------------
# R7b -- THE WEEKLY TIMELINE REBUILD.
#
# The graphrag episodes artifact (s3://leviathan-dev-shahem-001/graphrag_evidence/
# timeline/episodes.json) has been a HAND-RUN one-off since it was first built.
# R7a (the poller's EXTRA_TARGETS emission) is landed and live -- freshness.py
# EXTRA_TARGETS carries graphrag_timeline_episodes at prefix
# graphrag_evidence/timeline/ with expected_lag_days 10 -- so the artifact's age
# is now MEASURED. This unit is the cadence that age is measured against.
#
# PROVEN, NOT DESIGNED. Batch job r5-timeline-derive
# (638b80cb-cd2f-43a2-8337-743b534692a2, 2026-08-04) ran argv
# ["-m","leviathan.graphrag.timeline","--run"] on leviathan-dev-silver-gate:12 /
# leviathan-dev-queue-ondemand to exit 0 in 26 seconds. Everything below
# reproduces that run: same queue, same env set, same EVIDENCE_PG_DSN secret
# mount, same sizing. TWO deliberate deltas, both stated rather than implied:
#   (1) ANTHROPIC_API_KEY is NOT mounted -- derive() is documented "free, no LLM",
#       and the import argument below holds;
#   (2) the argv is --run-if-changed, NOT the smoked --run (R7.1; see the command
#       local). The two modes share one code path and differ only in whether an
#       UNCHANGED fingerprint suppresses the write, so the derive/stamp/write
#       behaviour proven by that run is the behaviour this argv reaches -- but the
#       argv itself is UNSMOKED, and precondition (a) below is therefore not yet
#       satisfied by the 08-04 job. Re-smoke on --run-if-changed before arming.
# On (1): timeline.py imports only
# leviathan.graphrag.params at module level and lazily imports
# leviathan.graphrag.pgstore inside derive(), so no Anthropic client is ever
# constructed on this path.
#
# THE R7c ALARM IS NOT HERE, AND THAT IS D-EI-12.
# silver_observability.auto.tfvars.json:52-56 already carries the
# graphrag_timeline_episodes FreshnessLagDays alarm (threshold 10,
# treat_missing_data="breaching", basis "weekly timeline rebuild
# (cron 0 3 ? * SUN *) + 3d grace"). It is held OUT of every batch until this
# schedule is not merely CREATED but ENABLED and has fired -- an alarm calibrated
# to a cadence that is not running breaches permanently ~10 days after the last
# hand-run rebuild, which is the "55 alarms into a void" failure with the sign
# flipped. THE CRON BELOW IS DELIBERATELY THE ONE THAT ALARM'S BASIS STRING NAMES,
# so that when D-EI-12 is lifted the alarm's own justification is true rather than
# aspirational.
#
# BEFORE THIS IS ENABLED -- Gate 3, which R7b re-opens BY DESIGN. The sequencing
# law is ONE rebuild -> ONE full deck re-probe. A weekly rebuild with no
# fingerprint comparison retires that law silently: build_stamp embeds built_at so
# the artifact's BYTES change every week even when the episodes do not, while
# stamp.fingerprint (computed over the episodes body with sort_keys=True,
# excluding built_at) is the stable pin. The rebuild job must compare the new
# fingerprint to the previous run's and emit a distinct token when it MOVES --
# unchanged means log and exit; changed means the deck's "# PROBE" notes are stale
# and somebody must re-probe. That leg is CODE, not terraform, and it is why this
# schedule is created DISABLED and stays that way until it exists.
#
# COUNT-GATE: var.timeline_rebuild_image_digest. Empty removes the whole unit.
# ---------------------------------------------------------------------------

locals {
  timeline_rebuild_enabled = var.timeline_rebuild_image_digest != "" ? 1 : 0

  # ONE definition, read by the jobdef's baked command AND the schedule override
  # AND the pre-arm smoke -- the same three-way identity as the audit unit above.
  #
  # --run-if-changed, NOT --run (R7.1, landed 2026-08-04). This is the leg
  # precondition (b) below names, and the reason it is a flag rather than a
  # separate entrypoint is that the scheduled path and the smoked path must remain
  # the SAME command string. The mode derives, compares the artifact's CONTENT
  # fingerprint (build_stamp hashes the episodes body alone -- built_at is outside
  # it) against the live artifact's, and:
  #   UNCHANGED -> prints TIMELINE_UNCHANGED_SKIP with both fingerprints, writes
  #                NOTHING, exits 0. The artifact keeps its original bytes and its
  #                original built_at, so "bytes moved" still means "episodes moved".
  #   CHANGED   -> writes, then prints TIMELINE_REBUILT_REPROBE_REQUIRED with the
  #                old and new fingerprints -- the deck's "# PROBE" notes are stale
  #                and a human must re-probe.
  # A legacy/absent/unreadable artifact has no fingerprint to compare and is
  # treated as CHANGED, so the first scheduled run against today's unstamped
  # artifact rebuilds rather than skipping forever.
  #
  # Bare `--run` still exists and still always writes; it is the hand-run mode. Had
  # this schedule been armed on it, the weekly rewrite would have moved the bytes
  # every Sunday over identical episodes and retired the ONE-rebuild-ONE-re-probe
  # law by making its signal fire 52 times a year on nothing.
  #
  # OPEN, for the lane that owns the R7c alarm: a SKIPPED rebuild does not move the
  # object's S3 LastModified, which is what the freshness poller measures. Two
  # consecutive unchanged weeks age graphrag_timeline_episodes past the
  # expected_lag_days 10 the held alarm is calibrated to, on a perfectly healthy
  # pipeline. The skip prints that consequence in its own log line; the calibration
  # decision is D-EI-12's to make before the alarm is unheld, not this unit's.
  timeline_rebuild_command = ["-m", "leviathan.graphrag.timeline", "--run-if-changed"]

  timeline_rebuild_job_definition_name = "${var.project_name}-${var.environment}-timeline-rebuild"

  # Name-constructed ARNs, same rationale as the audit unit's locals above: keep the
  # plan text readable, build every ARN from the same name local the resource uses.
  timeline_rebuild_scheduler_role_name = "${var.project_name}-${var.environment}-timeline-rebuild-scheduler"
  timeline_rebuild_scheduler_role_arn  = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.timeline_rebuild_scheduler_role_name}"

  timeline_rebuild_dlq_name = "${var.project_name}-${var.environment}-timeline-rebuild-dlq"
  timeline_rebuild_dlq_arn  = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${local.timeline_rebuild_dlq_name}"

  timeline_rebuild_job_definition_arns = [
    # BOTH ARN FORMS. Same incident, same fix, same reason as the audit unit.
    "arn:aws:batch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job-definition/${local.timeline_rebuild_job_definition_name}",
    "arn:aws:batch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job-definition/${local.timeline_rebuild_job_definition_name}:*",
  ]
}

resource "aws_batch_job_definition" "timeline_rebuild" {
  count = local.timeline_rebuild_enabled

  name                  = local.timeline_rebuild_job_definition_name
  type                  = "container"
  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    # The WORKER image (leviathan.graphrag lives in src/, which the worker COPYs);
    # by digest, and the digest is the one silver-gate:14 / b3-flat-silver:24 /
    # silver-publisher-runner:24 all run today.
    image   = "${module.ecr.repository_url}@${var.timeline_rebuild_image_digest}"
    command = local.timeline_rebuild_command

    # The proven job's environment, verbatim, plus the delivery marker. Carrying
    # the full set rather than a minimised one is deliberate: the smoked
    # configuration and the scheduled configuration must be the same
    # configuration, and EVIDENCE_* defaults that look inert are exactly the kind
    # of thing that turns out to be load-bearing at 03:00 on a Sunday.
    environment = [
      { name = "AWS_REGION", value = var.aws_region },
      { name = "LEVIATHAN_ENV", value = var.environment },
      { name = "LEVIATHAN_BUCKET", value = var.bucket_name },
      { name = "EVIDENCE_S3", value = "s3://${var.bucket_name}/graphrag_evidence" },
      { name = "EVIDENCE_BACKEND", value = "pg" },
      { name = "EVIDENCE_EMBED_BACKEND", value = "bge_local" },
      { name = "EVIDENCE_WORKERS", value = "16" },
      { name = "PYTHONIOENCODING", value = "utf-8" },
      # DELIVERY (P4), same marker and same reason as the audit unit above: a
      # FAILED weekly rebuild reaches the owner ONLY through the
      # batch-failed-scheduled metric filter, which matches on this NAME.
      { name = var.ecr_pin_audit_scheduled_marker, value = "scheduler" },
    ]

    # derive() reads the pg prop store and REFUSES to run without a DSN. Mounted as
    # a SECRET, exactly as the proven run had it -- never as a plaintext env value.
    # The injection is performed by the EXECUTION role, not the job role; that
    # role's GetSecretValue on this secret is an out-of-band grant (see
    # modules/iam/main.tf:78-79, which says so explicitly) and was re-verified
    # read-only 2026-08-04 via iam simulate-principal-policy -> "allowed". It is
    # deliberately NOT codified here: adopting a live out-of-band grant is its own
    # change with its own plan line, not a rider on an arming batch.
    secrets = [
      { name = "EVIDENCE_PG_DSN", valueFrom = data.aws_secretsmanager_secret.pg_dsn.arn },
    ]

    # The proven sizing (the r5-timeline-derive run). "Small" here is relative to
    # evidence-build's 16 vCPU / 122880 MiB; downsizing an OOM-sensitive store read
    # on the strength of a 26-second sample would be a guess, and the routing-pass
    # exit-137 incident is what guessing costs.
    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "8192" },
    ]

    executionRoleArn = module.iam.batch_execution_role_arn
    # The SHARED batch job role, which is what the proven run used and what already
    # carries the S3 write to graphrag_evidence/. A dedicated role here would be an
    # UNSMOKED role, and precondition P2 above is the whole record of what an
    # unsmoked role costs -- an IAM hole that reads like an outage.
    jobRoleArn = module.iam.batch_job_role_arn

    networkConfiguration = { assignPublicIp = "ENABLED" }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/aws/batch/${var.project_name}-${var.environment}"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "timeline-rebuild"
      }
    }
  })

  # NO retry, stated explicitly rather than left to the default. This job REWRITES
  # the served artifact; a silent second attempt is a second rebuild, and a rebuild
  # is the event the deck re-probe law is keyed to. A failed rebuild is re-fired
  # deliberately, by a human, exactly like the pattern-records sweep.
  retry_strategy {
    attempts = 1
  }

  # Measured 26s. 1800s is deep headroom for a store that grows continuously
  # (check_artifact's own docstring says the derive reads grow) while still bounded.
  timeout {
    attempt_duration_seconds = 1800
  }

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_iam_role" "timeline_rebuild_scheduler" {
  count = local.timeline_rebuild_enabled

  name = local.timeline_rebuild_scheduler_role_name
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

resource "aws_iam_role_policy" "timeline_rebuild_scheduler" {
  count = local.timeline_rebuild_enabled

  name = "${var.project_name}-${var.environment}-timeline-rebuild-scheduler-submit"
  role = aws_iam_role.timeline_rebuild_scheduler[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "batch:SubmitJob"
        Resource = concat([local.ondemand_job_queue_arn], local.timeline_rebuild_job_definition_arns)
      },
      {
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = local.timeline_rebuild_dlq_arn
      },
    ]
  })
}

resource "aws_sqs_queue" "timeline_rebuild_scheduler_dlq" {
  count = local.timeline_rebuild_enabled

  name                      = local.timeline_rebuild_dlq_name
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

# THIS IS NOT THE R7c ALARM. R7c is the FreshnessLagDays alarm on the ARTIFACT and
# it stays held out by D-EI-12. This one alarms on the DELIVERY of the schedule --
# a fire that Scheduler dropped before Batch ever saw it. The two fail in opposite
# directions and neither substitutes for the other: a dropped fire with only R7c
# armed would surface ~10 days later as artifact staleness with no attribution,
# and R7c cannot be read at all while it is held.
resource "aws_cloudwatch_metric_alarm" "timeline_rebuild_scheduler_dlq_depth" {
  count = local.timeline_rebuild_enabled

  alarm_name          = "${var.project_name}-${var.environment}-timeline-rebuild-dlq-depth"
  alarm_description   = "The weekly graphrag timeline rebuild was DROPPED before it reached Batch. episodes.json was NOT rebuilt this week, so the served artifact is one cadence staler than the freshness fence assumes. Read the dead-lettered SubmitJob input, fix, re-fire by hand, then drain."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = local.timeline_rebuild_dlq_name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [module.alerting.topic_arn]

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_scheduler_schedule" "timeline_rebuild" {
  count = local.timeline_rebuild_enabled

  name = "${var.project_name}-${var.environment}-timeline-rebuild"

  # ENABLED 2026-08-05 -- both preconditions DISCHARGED, receipts:
  #   (a) the smoke: job 00ca53b0 (exit 0, argv exactly the baked command) printed
  #       TIMELINE_UNCHANGED_SKIP with old==new fingerprint sha256:0ea3a501..., and the
  #       artifact was asserted byte-untouched against the pre-run capture (629,371 B /
  #       125 episodes / built_at 2026-08-04T07:17:53Z). Re-smoked on the heartbeat
  #       image (job timeline-weekly-smoke-2) after the calibration fix below.
  #   (b) the fingerprint-compare leg (R7.1) EXISTS and ran: the skip token IS its
  #       output; the argv is pinned in local.timeline_rebuild_command.
  # PLUS the calibration the first smoke exposed: a healthy skip does not move the
  # artifact's LastModified, so the R7c alarm would have false-fired on ~10 quiet days.
  # timeline.write_heartbeat now touches timeline/last_run.json inside the polled
  # prefix on EVERY successful run -- freshness measures schedule liveness ('one
  # missed run breaches'), never content churn.
  # Rollback = state back to "DISABLED" (no redeploy).
  state = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  # 03:00 UTC Sunday -- THE CRON THE HELD R7c ALARM'S BASIS STRING ALREADY NAMES
  # ("weekly timeline rebuild (cron 0 3 ? * SUN *) + 3d grace; one missed run
  # breaches"). Picking any other cadence would make that alarm's own justification
  # false on the day D-EI-12 is lifted. It is also clear of every other schedule in
  # the estate (23:00 daily sweep, 12:30 daily poller, 05:30 Monday audit), and it
  # lands 9.5h before the Sunday poller reads the prefix, so the week's first
  # datapoint measures a freshly rebuilt artifact.
  schedule_expression = "cron(0 3 ? * SUN *)"

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:batch:submitJob"
    role_arn = local.timeline_rebuild_scheduler_role_arn

    input = jsonencode({
      JobName  = "timeline-rebuild"
      JobQueue = local.ondemand_job_queue_arn
      # The UNVERSIONED family name -- latest ACTIVE at fire time, and the exact
      # string the bare job-definition ARN grant authorizes.
      JobDefinition = local.timeline_rebuild_job_definition_name
      ContainerOverrides = {
        Command = local.timeline_rebuild_command
      }
    })

    # maximum_retry_attempts = 0, the sweep's reasoning and not the audit's: this
    # job WRITES the served artifact, so a delivery retry is a second rebuild. Every
    # failure is terminal on the first try -- which is precisely why the DLQ below
    # is not optional, because a terminal failure otherwise leaves nothing behind.
    retry_policy {
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 3600
    }

    dead_letter_config {
      arn = local.timeline_rebuild_dlq_arn
    }
  }

  # The dependencies the constructed ARNs above no longer express implicitly.
  depends_on = [
    aws_iam_role.timeline_rebuild_scheduler,
    aws_iam_role_policy.timeline_rebuild_scheduler,
    aws_batch_job_definition.timeline_rebuild,
    aws_sqs_queue.timeline_rebuild_scheduler_dlq,
  ]
}
