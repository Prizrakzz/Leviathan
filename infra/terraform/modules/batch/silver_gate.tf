# ===========================================================================
# THE SILVER GATE JOB DEFINITION -- D-PR-8's retry contract, and the adoption
# of the last un-owned resource on the promote path.
#
# WHY THIS IS A SEPARATE FILE AND NOT A BLOCK IN main.tf: it was authored in the
# same sitting as the D-PR-7/D-PR-11 pass over the other 40 jobdefs, by a
# different lane. Terraform merges every *.tf in a module directory, so keeping
# this unit in its own file makes the two changes reviewable apart and removes
# any chance of one lane's whole-file write landing on top of the other's.
#
# ---------------------------------------------------------------------------
# THIS RESOURCE DOES NOT EXIST IN STATE TODAY. READ THIS BEFORE APPLYING.
# ---------------------------------------------------------------------------
# `leviathan-dev-silver-gate` is the jobdef EVERY family's [Gate] and [Reconcile]
# state submits (`configs/silver/dags/_rendered/*.input.json` -> `$.gate.jobdef`),
# and it has never been in terraform. It exists LIVE at revision 14 with a
# 14-revision history, every one registered by a hand-typed
# `aws batch register-job-definition` -- there is no committed script for it
# either (jobs/utils/register_evidence_jobdef.py registers a DIFFERENT family:
# name `evidence-build`, the embedder repo, 16 vCPU / 122880 MiB, with
# `parameters` defaults).
#
# So this block is an ADOPTION, and applying it REGISTERS REVISION 15, which the
# schedules pick up on the next fire because the DAG inputs resolve UNVERSIONED
# family names to latest-ACTIVE. The content below was transcribed field-by-field
# from live rev 14 (read-only `describe-job-definitions`, 2026-08-04) so that
# rev 15 is rev 14 plus exactly three deliberate additions:
#
#   1. `retry_strategy`  -- D-PR-8 / D-PR-37 (see the block for the whole argument)
#   2. `timeout`         -- D-PR-11; live rev 14 has NO attemptDurationSeconds at all
#   3. `tags`            -- live rev 14 carries none; three tags, no runtime effect
#
# EVERYTHING ELSE IS A TRANSCRIPTION AND MUST MATCH LIVE REV 14 EXACTLY: the image
# digest, the `Ref::`-parameterised command, both roles, all nine environment
# entries, BOTH SECRETS, 2 vCPU / 8192 MiB, public IP, platform version. The
# secrets are the sharp edge -- terraform sends exactly what is declared, so an
# omitted `secrets` block would register a rev 15 with no EVIDENCE_PG_DSN and
# every Branch-A stage would silently degrade to the offline/skip posture on the
# next fire. They are declared below, resolved BY NAME (this repo is public), the
# same discipline register_evidence_jobdef.py uses.
#
# TO DEFER THE ADOPTION: leave `silver_gate_image_digest` empty (count -> 0, no
# plan line at all), or simply omit this resource from the apply's `-target` list.
# Deferring costs nothing except that the gate keeps today's wrong retry rule.
# ===========================================================================

variable "silver_gate_image_digest" {
  # The sha256 digest of the WORKER image `leviathan-dev-silver-gate` runs.
  #
  # NO ":latest" FALLBACK, deliberately -- unlike every other jobdef in this module.
  # The gate is the one job whose whole purpose is to refuse a rebuild, and the I-1
  # incident (a container whose baked configs/silver/tables/ predated the ask) is the
  # reason `image_stamp.preflight` exists. A mutable tag on THIS jobdef would mean the
  # image that judged a promote cannot be named after the fact. Empty therefore means
  # "do not manage this jobdef", not "use :latest".
  type        = string
  description = "sha256 digest of the worker image the silver-gate jobdef runs, e.g. 'sha256:abc...'. Empty = terraform does not manage the gate jobdef at all (count 0) -- there is no ':latest' fallback for the gate."
  default     = ""

  validation {
    condition     = var.silver_gate_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.silver_gate_image_digest))
    error_message = "silver_gate_image_digest must be empty or a full 'sha256:<64 hex>' digest -- a TAG is never accepted for the gate."
  }
}

# Secret ARNs are resolved BY NAME so the random suffix stays out of this PUBLIC
# repo -- the rule register_evidence_jobdef.py:46-49 states in its own comment.
# Read-only lookups; they resolve at plan time and never mutate anything.
data "aws_secretsmanager_secret" "silver_gate_anthropic" {
  count = var.silver_gate_image_digest == "" ? 0 : 1
  name  = "${var.project_name}-${var.environment}-anthropic-api-key"
}

data "aws_secretsmanager_secret" "silver_gate_evidence_pg_dsn" {
  count = var.silver_gate_image_digest == "" ? 0 : 1
  name  = "${var.project_name}/${var.environment}/evidence-pg-dsn"
}

resource "aws_batch_job_definition" "silver_gate" {
  count = var.silver_gate_image_digest == "" ? 0 : 1

  name = "${var.project_name}-${var.environment}-silver-gate"
  type = "container"

  platform_capabilities = ["FARGATE"]

  container_properties = jsonencode({
    image = "${var.ecr_repository_url}@${var.silver_gate_image_digest}"

    # TRANSCRIBED FROM LIVE REV 14, `Ref::` tokens and all. It reads wrong and it is
    # right: this jobdef was cloned from evidence-build and its baked command is never
    # the one that runs. [Gate] and [Reconcile] both send ContainerOverrides.Command
    # (`modules/step_functions/main.tf`: "$.gate.command" / the advance_rolling_census
    # States.Array), so the baked list is dead weight that must NOT be "corrected" here
    # -- changing it changes nothing at runtime and loses the transcription property
    # that makes rev 15 auditable against rev 14. Note there are no `parameters`
    # defaults (live rev 14 has `parameters: {}`), so a submit WITHOUT an override
    # would fail to resolve Ref:: -- which is exactly today's behaviour, unchanged.
    command = [
      "jobs/batch/build_evidence_task.py",
      "--nodes", "Ref::nodes",
      "--n-docs", "Ref::n_docs",
      "--workers", "Ref::workers",
      "--skip-existing", "Ref::skip_existing",
      "--drivers", "Ref::drivers",
      "--chunk-provider", "Ref::chunk_provider",
    ]

    environment = [
      { name = "AWS_REGION", value = var.aws_region },
      { name = "EVIDENCE_S3", value = "s3://${var.leviathan_bucket}/graphrag_evidence" },
      { name = "LEVIATHAN_BUCKET", value = var.leviathan_bucket },
      { name = "LEVIATHAN_ENV", value = var.environment },
      { name = "PYTHONIOENCODING", value = "utf-8" },
      { name = "EVIDENCE_EMBED_BACKEND", value = "bge_local" },
      { name = "EVIDENCE_BACKEND", value = "pg" },
      { name = "GRAPHRAG_SESSIONS_TABLE", value = "${var.project_name}-${var.environment}-graphrag-sessions" },
      { name = "EVIDENCE_WORKERS", value = "16" },
    ]

    # NOT OPTIONAL. EVIDENCE_PG_DSN is how the gate reaches the pg mirror; without it
    # every Branch-A table takes the offline path and the gate stops proving the thing
    # it exists to prove. ANTHROPIC_API_KEY is inherited from the evidence-build clone.
    secrets = [
      { name = "ANTHROPIC_API_KEY", valueFrom = data.aws_secretsmanager_secret.silver_gate_anthropic[0].arn },
      { name = "EVIDENCE_PG_DSN", valueFrom = data.aws_secretsmanager_secret.silver_gate_evidence_pg_dsn[0].arn },
    ]

    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "8192" },
    ]

    executionRoleArn = var.batch_execution_role_arn
    jobRoleArn       = var.batch_job_role_arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    fargatePlatformConfiguration = {
      platformVersion = "LATEST"
    }
  })

  # D-PR-11. Live rev 14 has NO timeout: a hung gate holds the 16-vCPU ondemand queue
  # indefinitely and `leviathan-dev-batch-queued-job-age` cannot see it (that alarm
  # watches QUEUE age, not RUN age). Observed gate runtime is ~2.5 min, so 3600 s is a
  # ~24x ceiling. PER ATTEMPT: with attempts 2 the worst case is 2 h, and only for the
  # one class that retries.
  timeout {
    attempt_duration_seconds = 3600
  }

  # -------------------------------------------------------------------------
  # D-PR-8 + D-PR-37: THE GATE MATRIX. Three rules, and every one of them earns
  # its slot against an API cap of FIVE.
  #
  #   {72 -> RETRY}  the ONLY retryable outcome the gate can produce. 72 is
  #                  BaselineFetchError -- a transient S3 GET of the rolling
  #                  baseline census. Retrying it re-reads S3; it can never turn a
  #                  refusal into a promote, because a refusal is exit 1 and exit 1
  #                  is not in this list.
  #   {ResourceInitializationError* -> RETRY}  the container never became the gate
  #                  (ENI / ASM init). Nothing was judged, so a second attempt is
  #                  free of attribution risk.
  #   {'*' -> EXIT}  MANDATORY AND NON-NEGOTIABLE. A no-match in evaluateOnExit
  #                  defaults to **RETRY**, so deleting this line silently arms a
  #                  retry on EVERY failure class including a verdict FAIL -- the
  #                  one thing a gate must never do.
  #
  # WHAT THIS REPLACES (live rev 14, and it is aimed at the wrong class):
  #   {attempts: 3, [{CannotPullContainer* -> RETRY}, {Host EC2* -> RETRY}, {* -> EXIT}]}
  # All 26 CannotPull events in 21 days of the archive are PERMANENT digest
  # evictions; three of those digests still read as `missing[old-rev]` in the
  # auditor today. Retrying them 3x cannot succeed -- it only triples the alarm
  # datapoints. `Host EC2*` is dead weight on a Fargate ondemand queue. Both go.
  #
  # CannotPullContainer is NOT listed below: it falls through to the terminal
  # catch-all, which EXITs. That is the D-PR-37 trim, not an omission.
  #
  # attempts 2 (not 3): only one class retries, and it retries once.
  #
  # THIS JOBDEF ALSO CARRIES [Reconcile] (`$.gate.jobdef` is reused for
  # `jobs.audit.advance_rolling_census`), so the matrix was checked against that
  # entry point too: advance_rolling_census returns ONLY 0 or 1, so the 72 rule can
  # never fire for it and its exit 1 falls to the catch-all -- one attempt, no
  # retry of a failed baseline roll-forward. Verified by reading its returns, not
  # assumed.
  #
  # PAIRED WITH CODE. This matrix is only sound because jobs/audit/silver_rebuild_gate.py
  # no longer returns 1 for five different outcomes (D-PR-8: 1 refusal / 64 usage /
  # 70 internal crash / 71 image-config fence / 72 baseline fetch).
  # `tests/unit/test_gate_exit_vocabulary.py` pins this block against those constants,
  # so the two cannot drift apart.
  # -------------------------------------------------------------------------
  retry_strategy {
    attempts = 2

    evaluate_on_exit {
      action           = "RETRY"
      on_exit_code     = "72"
      on_reason        = null
      on_status_reason = null
    }

    evaluate_on_exit {
      action           = "RETRY"
      on_exit_code     = null
      on_reason        = null
      on_status_reason = "ResourceInitializationError*"
    }

    # MANDATORY TERMINAL RULE -- no-match defaults to RETRY. Do not remove.
    evaluate_on_exit {
      action           = "EXIT"
      on_exit_code     = null
      on_reason        = "*"
      on_status_reason = null
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
