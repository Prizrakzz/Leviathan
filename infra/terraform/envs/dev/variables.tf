variable "aws_region" {
  type        = string
  description = "AWS region."
  default     = "us-east-1"
}

variable "project_name" {
  type        = string
  description = "Project name."
  default     = "leviathan"
}

variable "environment" {
  type        = string
  description = "Environment name."
  default     = "dev"
}

variable "bucket_name" {
  type        = string
  description = "Globally unique S3 bucket name."
}

variable "batch_max_vcpus" {
  type        = number
  description = "Maximum vCPUs for the Batch Fargate compute environment."
  default     = 16
}

variable "batch_subnet_ids" {
  type        = list(string)
  description = "Subnet IDs for Fargate tasks (default VPC public subnets)."
}

variable "batch_security_group_ids" {
  type        = list(string)
  description = "Security group IDs for Fargate tasks."
}

variable "mlflow_ami_id" {
  type        = string
  description = "Pinned AMI for the adopted dev MLflow/Airflow EC2 instance."
  default     = "ami-0521cb2d60cfbb1a6"
}

variable "mlflow_root_volume_size_gib" {
  type        = number
  description = "Current root volume size for the adopted MLflow/Airflow host."
  default     = 10
}

variable "budget_alert_email" {
  type        = string
  description = "Email address for monthly cost budget alerts. Leave empty to disable email notifications."
  default     = ""
}

# --- Phase 4: GraphRAG serving (ECS Fargate + ALB) --------------------------

variable "serving_admin_cidrs" {
  type        = list(string)
  description = <<-EOT
    CIDRs allowed inbound to the serving ALB. Stage 1 (private validation) MUST lock this to
    your IP, e.g. ["203.0.113.4/32"] — supply at apply time (-var or tfvars). Stage 4 opens it
    to 0.0.0.0/0 once Cognito + HTTPS front it. No default: an unset value is a mistake here.
  EOT
}

variable "serving_image_tag" {
  type        = string
  description = "Tag of the leviathan-dev-leviathan-embedder serving image the task runs."
  # PINNED 2026-07-30 (drift reconciliation), was "latest". The running service is on digest
  # sha256:00fcd043... = tag 20260725rev72, while :latest had moved on to sha256:6717f599...
  # (tag 20260728d785af30). A default of "latest" therefore meant any apply touching the task
  # definition would have silently DEPLOYED A DIFFERENT, UNVALIDATED IMAGE. A serving image is
  # promoted deliberately, so the default now names the promoted build; bump it when you promote.
  # DEPLOYED 2026-07-31: the W3 flip build (commit d5aa7353 + the D7 pg mirror). Previous pin was
  # 20260725rev72 = digest 00fcd043, which predates the whitelist flip -- serving could not answer a
  # delivery-month or curve ask on that image no matter what the config said.
  # DEPLOYED 2026-08-19: the unica-splice build (commit 38dc5f0c, registry 36 cards / 34 visible,
  # release_series refused on a measured PIT leak). Hand-registered as serving taskdef rev 104 on
  # digest sha256:74813e92a7dc...; canary three tells passed (rollout, startedAt > push, exact
  # digest). This pin follows that promotion so a later apply re-derives the same image.
  # D-EC WAVE CLOSE 2026-08-20 (rev 108): 20260820T231837 = sha256:c9b341ca..., built at 1734e8fe
  # -- the doubled evidence store (1,277,979 props, swap live), the 38-card registry (minagro
  # Ukraine exports, crush, unica, PSD 63 slugs, pink sheet 76 metrics), the NASS wheat + MATIF
  # answer flips, and the floored-uncovered decline honesty. Taskdef 108 registered copy-from-
  # deployed-107 (image-only change); canary three tells PASSED (rollout COMPLETED, startedAt
  # 23:22:05+03 > push 23:18, exact digest).
  default     = "20260820T231837"
}

# Stage 2: the ACM wildcard cert (leviathanconvexity.com + *) created in the console. us-east-1.
variable "serving_certificate_arn" {
  type        = string
  description = "ACM cert ARN for the ALB HTTPS:443 listener + CloudFront (wildcard covers apex/www/api/auth)."
  default     = "arn:aws:acm:us-east-1:668891723125:certificate/650c1f63-a62c-4ceb-a197-010cd1305635"
}

variable "public_domain" {
  type        = string
  description = "The public apex domain (Route53 zone Z01445327V6FBPHBK9AX, console-created)."
  default     = "leviathanconvexity.com"
}

variable "public_zone_id" {
  type        = string
  description = "Route53 hosted zone id for public_domain (console-created; referenced, not managed)."
  default     = "Z01445327V6FBPHBK9AX"
}

# Stage 4: Google federated sign-in via Cognito. Secrets live ONLY in the gitignored terraform.tfvars
# (state is also gitignored) — never in a committed file. Empty defaults so Dynamo/IAM can apply before
# these are supplied; the Cognito apply is gated on them being set.
variable "google_oauth_client_id" {
  type        = string
  description = "Google Cloud OAuth 2.0 web client id (set in terraform.tfvars)."
  default     = ""
}

variable "google_oauth_client_secret" {
  type        = string
  description = "Google Cloud OAuth 2.0 web client secret (set in terraform.tfvars)."
  sensitive   = true
  default     = ""
}

variable "cognito_domain_prefix" {
  type        = string
  description = "Cognito hosted-UI domain prefix -> https://<prefix>.auth.<region>.amazoncognito.com."
  default     = "leviathan-terminal"
}


# ---------------------------------------------------------------------------
# SILVER-F082 observability (apply-gated). These three are populated from
# silver_observability.auto.tfvars.json, emitted by:
#     python jobs/observability/silver_alarms.py --emit-tfvars infra/terraform/envs/dev
# Regenerate whenever a silver table is added so the alarm set stays complete.
# ---------------------------------------------------------------------------
variable "silver_metric_namespace" {
  type        = string
  description = "CloudWatch namespace for app-emitted silver pipeline metrics."
  default     = "Leviathan/Silver"
}

variable "silver_batch_families" {
  type        = list(string)
  description = "DAG-catalog family keys with a source Batch DAG (per-family Batch-failed alarms)."
  default     = []
}

variable "silver_freshness_slas" {
  type        = map(number)
  description = "family_key -> interim freshness ceiling (days) for freshness-SLA-breach alarms."
  default     = {}
}

variable "silver_table_freshness_slas" {
  type = map(object({
    family    = string
    threshold = number
    basis     = string
  }))
  description = "table_name -> {family, threshold, basis} for PER-TABLE freshness alarms (the four audit-burned tables). From silver_observability.auto.tfvars.json. Wire into module.silver_observability (see freshness_poller.tf.prepared) to render the per-table alarms."
  default     = {}
}

variable "silver_alert_email" {
  type        = string
  description = "Email for the silver-pipeline SNS subscription placeholder ('' = no subscription)."
  default     = ""
}

variable "dag_schedules" {
  type = map(object({
    cron       = string
    enabled    = bool
    input_json = string
  }))
  default     = {}
  description = "Per-family DAG schedules rendered by gen_sfn_inputs --render-schedule (dag_schedules.auto.tfvars.json)."
}

# --- T2B pattern-records ledger (docs/private/T2B_PATTERN_RECORDS_PLAN.md) ---

variable "pattern_records_image_digest" {
  # The sha256 digest of the CONTENT-CHECKED embedder image that carries the sweep
  # entrypoint (rollout step 3: docker run + inspect.getsource markers -- never trust a
  # tag, the d9b2e10e stale-:latest lesson). Empty (default) count-gates the ENTIRE T2B
  # cloud leg out of existence: no jobdef, no scheduler role, no schedule, no kms:Sign
  # grant. The main loop pins the real digest; keep the value in the "sha256:..." form.
  type        = string
  description = "sha256 digest of the content-checked embedder image for the pattern-records sweep jobdef, e.g. 'sha256:abc...'. Empty = the whole T2B cloud leg is not created."
  default     = ""

  validation {
    condition     = var.pattern_records_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.pattern_records_image_digest))
    error_message = "pattern_records_image_digest must be empty or a full 'sha256:<64 hex>' digest (a TAG is not accepted: the ledger's engine_version stamp and the stale-image guard both depend on the digest)."
  }
}

# --- PRICE_AND_PLAYBOOKS W1a + W2: the two futures_eod chains ---------------

variable "futures_eod_image_digest" {
  # The WORKER image the three futures_eod jobdefs run, pinned BY DIGEST.
  #
  # DEFAULTED IN THE REPO, not left to the gitignored tfvars, for the same reason
  # mlflow_enabled's default lives here: a fresh checkout must reproduce the wiring
  # that is actually live. The value is the 20260729w1c build (worker repo
  # leviathan-dev-leviathan-worker; commit 50a2ec3d), which is the build that carries
  # BOTH pyproject deps this family fails silently without -- `databento` from the
  # [batch] extra (futures_eod_databento.json precondition (d)) and core `xlrd>=2.0`
  # for the JSE / CEPEA-archive .xls readers (futures_eod_free.json precondition (c)).
  # Pinning the digest is what discharges precondition (d): the pin IS the repin.
  #
  # Re-pin whenever the worker image is rebuilt for this family; SILVER-F085
  # (scripts/build_push_worker.ps1 never pushes :latest-only) is what keeps the
  # referenced digest from being untagged and GC'd out from under the jobdefs.
  # Empty count-gates all three jobdefs out of existence.
  type        = string
  description = "sha256 digest of the worker image the futures_eod fetch + silver jobdefs run. Empty = none of the three futures_eod jobdefs are created."
  # 2026-07-31: repinned to tag 20260731T130318, which carries the databento incremental-window
  # clamp. The previous digest (2f3efb7c, tag 20260729w1c) 422'd 15/15 units on every fire --
  # fetch_databento_eod.py overwrote the clamped window with `today + 1`, one day past the vendor's
  # available end, on the only path that submits.
  default     = "sha256:5f0f2aacd23dbcc1dcb05056b6dc9b6d3fd84f0b8720d8a99500085b1e37e4cb"

  validation {
    condition     = var.futures_eod_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.futures_eod_image_digest))
    error_message = "futures_eod_image_digest must be empty or a full 'sha256:<64 hex>' digest (a TAG is not accepted)."
  }
}

variable "futures_eod_silver_image_digest" {
  # THE SILVER LEG ONLY. The two FETCH jobdefs stay on futures_eod_image_digest above.
  #
  # RECONCILED TO LIVE 2026-08-04. leviathan-dev-futures-eod-silver's latest-ACTIVE
  # revision (rev 3) runs tag 20260801T131152, one build NEWER than the 20260731T130318
  # the fetch legs are pinned to; the silver leg was repinned out of band and the fetch
  # legs deliberately were not. Terraform holds the three jobdefs as phantom-creates
  # (absent from state, present in AWS), so with a single shared digest the next apply
  # would have registered a new latest-ACTIVE silver revision carrying the OLDER image
  # -- and the DAG resolves the family name to latest-ACTIVE, so the publishing leg
  # would have rolled back one vintage with nothing in the plan saying so.
  #
  # Empty = share futures_eod_image_digest. Keep this equal to the live latest-ACTIVE
  # image unless a repin is the deliberate point of the change:
  #   aws batch describe-job-definitions --job-definition-name leviathan-dev-futures-eod-silver \
  #     --status ACTIVE --query 'reverse(sort_by(jobDefinitions,&revision))[0].containerProperties.image'
  type        = string
  description = "sha256 digest override for the futures_eod SILVER jobdef only. Empty = share futures_eod_image_digest with the two fetch jobdefs."
  default     = "sha256:ea0f9d1815d6226c25f1bc0ca99f5fc78f5efa8b7512c2d7c7b113c29eec6a30"

  validation {
    condition     = var.futures_eod_silver_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.futures_eod_silver_image_digest))
    error_message = "futures_eod_silver_image_digest must be empty or a full 'sha256:<64 hex>' digest (a TAG is not accepted)."
  }
}

# --- D-PR-22: the pink-sheet bronze leg comes off :latest -------------------

variable "pink_sheet_image_digest" {
  # The WORKER image leviathan-dev-world-bank-pink-sheet-bronze runs, pinned BY DIGEST.
  #
  # pink_sheet_monthly (cron(0 16 4 * ? *)) is a promote_mode=AUTONOMOUS chain: its
  # promote leg re-runs pink_sheet_silver_task.py with --publish-mode canonical under a
  # KMS approval, unattended. Its fetch and silver legs run leviathan-dev-b3-flat-silver
  # and its gate runs leviathan-dev-silver-gate -- BOTH already digest-pinned. The
  # bronze leg's ":latest" was therefore the only mutable hop in a path that writes a
  # canonical partition without a human in the loop, and ":latest" is re-pointed by
  # every worker push -- including a push that lands between the schedule firing and
  # the bronze task pulling.
  #
  # VALUE = what ':latest' resolved to at 2026-08-04T11:40Z: tag 20260804T132111,
  # pushed 2026-08-04T10:21Z. Verified byte-consistent with the rest of the chain --
  # b3-flat-silver rev 24, silver-gate rev 14 and silver-publisher-runner rev 24 all
  # run this exact digest -- so pinning here makes all four legs of the chain one image
  # instead of three-plus-a-coin-flip.
  #
  # Re-pin deliberately after a worker rebuild the pink-sheet path needs:
  #   aws ecr describe-images --repository-name leviathan-dev-leviathan-worker \
  #     --image-ids imageTag=latest --query 'imageDetails[0].imageDigest'
  # Empty = fall back to the mutable ':latest' (historical behaviour).
  type        = string
  description = "sha256 digest of the worker image the world_bank_pink_sheet_bronze jobdef runs. Empty = the mutable ':latest' tag."
  # D-SG S-C repin 2026-08-16: cf50c051 = the worker build carrying the pink_sheet
  # --skip-existing-s3 restore + release-recency fence (G2-1c). The pin-collision law:
  # the task change and this digest move ride the SAME change or an apply reverts the fix.
  default     = "sha256:53db13d53bfb3b5066d92100930f56ee98c1cca309d692be5b6d88cbb18847d2"

  validation {
    condition     = var.pink_sheet_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.pink_sheet_image_digest))
    error_message = "pink_sheet_image_digest must be empty or a full 'sha256:<64 hex>' digest (a TAG is not accepted -- a tag is the mutability this pin removes)."
  }
}

variable "psd_silver_image_digest" {
  # The WORKER image leviathan-dev-psd-silver runs (D-SG G1-1, the OOM fix).
  #
  # VALUE = the digest the LIVE latest-ACTIVE leviathan-dev-b3-flat-silver (rev 24) and
  # leviathan-dev-silver-publisher-runner (rev 24) BOTH run today -- ECR tag 20260804T132111,
  # pushed 2026-08-04T13:21:41Z, verified by describe-job-definitions on 2026-08-16. It is
  # DELIBERATELY NOT var.worker_fleet_image_digest (sha256:02e1fde4..., tag 20260805T173909)
  # and DELIBERATELY NOT ':latest' (sha256:c808ccfb..., tag 20260808T181848).
  #
  # THE STANDING LAW: a worker-fleet digest move rides ONE change, alone (the futures
  # read-path record -- gate-side parity stayed NON-CITABLE until the fleet rebuilt past
  # e8aa7857 with the tf digest moved in the same change). This change moves MEMORY. If it
  # also moved the PSD silver code forward one or two builds, a green first fire would not be
  # citable as proof the OOM fix worked and a red one would not be attributable. Re-pin in its
  # own change, after the first green fire.
  type        = string
  description = "sha256 digest of the worker image the dedicated psd-silver jobdef runs. Empty = the mutable ':latest' tag."
  default     = "sha256:e8aa7857a2e1b3b0258fa7258803a60d608a1209cf3b02042220da2094bf4b7f"

  validation {
    condition     = var.psd_silver_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.psd_silver_image_digest))
    error_message = "psd_silver_image_digest must be empty or a full 'sha256:<64 hex>' digest (a TAG is not accepted)."
  }
}

# --- D-PR-7/D-PR-11 PRECONDITION: the ten-family worker fleet pin ----------

variable "worker_fleet_image_digest" {
  # THE REVERT THIS EXISTS TO PREVENT (post-freeze run sheet section 8, verbatim):
  # "any change that re-registers them -- D-PR-11 touches exactly four of them and
  # D-PR-7 touches 39 of 40 -- will mint a new latest-ACTIVE from terraform's stale
  # definition and revert worker@sha256:e11d45fb... -> worker:latest on all ten."
  #
  # Ten jobdef families are pinned in state BY REVISION ARN at revisions 1-3, so they
  # emit no plan line while nothing re-registers them. Live latest-ACTIVE has moved
  # 3-5 revisions ahead on every one, onto a single shared digest. The retry-matrix
  # and timeout work re-registers all ten, which is precisely the trigger section 8
  # warned about. Adopting the live pin BEFORE that change lands is the E6/D-PR-22
  # template.
  #
  # VALUE = what all ten latest-ACTIVE revisions run, read live 2026-08-04:
  #   chirps-bronze-to-silver rev 6, chirps-to-bronze-backfill rev 4,
  #   conab-xls-bronze rev 4, cpc-soil-bronze-to-silver rev 4,
  #   cpc-soil-raw-to-bronze rev 5, cpc-soil-to-raw rev 4,
  #   modis-ndvi-bronze-to-silver rev 4, modis-ndvi-raw-to-bronze rev 4,
  #   nasa-power-backfill rev 6, usda-esr-bronze rev 5
  # -- all ten on sha256:e11d45fb..., tag 20260802T004739, pushed 2026-08-02T01:05Z,
  # verified still present via ecr:BatchGetImage (39 of 100 manifests in the repo).
  #
  # THIS IS DELIBERATELY *NOT* ':latest'. As of 2026-08-04T~13:21Z ':latest' resolves
  # to sha256:e8aa7857... (the pink-sheet pin). Moving these ten onto it would be an
  # unreviewed image bump of ten producers riding inside a reliability batch --
  # exactly the class of silent change this wave exists to stop. Bump the fleet
  # deliberately, in its own change, after the auditor has run.
  type        = string
  description = "sha256 digest of the worker image the ten weather/ingest jobdef families run. Empty = fall back to ':latest' (which would REVERT all ten -- see the comment)."
  # D-SG S-C DELIBERATE FLEET BUMP 2026-08-16 (the 'own change, after the auditor' this
  # variable's comment demands): 53db13d5 = the D-SG worker build (ingest fences, unica/
  # fgis fixes + endpoint-ceiling fence, wasde discovery+quarantine, season floors, gate
  # metrics, poller task, straddle + declared ICE lag). Full suite green; two adversarial
  # review passes folded. (The first D-SG push, cf50c051, was CORRUPT -- double-gzipped
  # OCI blobs -- caught by the poller smoke BEFORE any schedule moved; never armed.)
  # D-LD TRANCHE-2 DELIBERATE FLEET BUMP 2026-08-18 (#1, 14:17Z): e1fe1d82 = the tranche-2
  # landing build (six PIT-anchor producer transforms + fetch_mpob --refresh-manifest + unica
  # wayback leg). b3-flat-silver rev 29 + silver-publisher-runner rev 28 rode it; the mpob
  # HAND_ARMED hold released against it. All eight producer fires + gates ran on it same day.
  # D-LD TRANCHE-2 DELIBERATE FLEET BUMP 2026-08-18 (#2, 18:18Z): 69de00d2 = the SPLICE build
  # (commit 490ba6f1): six-card contracts baked (33 cards), food_cpi CURATION widen (its
  # producer fails closed on the old contract), mpoc un-hide, nass_crop_progress pct_emerged
  # floor 0.08 -> 0.05 (per-partition census). b3-flat-silver rev 30, silver-publisher-runner
  # rev 29 AND silver-gate rev 22 hand-registered on it the same hour -- the gate ride is the
  # point: the floor lives in the image-baked contract, so the weekly nass family gate unreds
  # only on this digest. Pin moves in the SAME change per this file's standing law.
  # UNICA PRODUCER-FIX FLEET BUMP 2026-08-19: bb2d4726 = commit 717bba03 (five measured unica
  # silver-transform defects repaired: history-page shift detection, release_series row unshift,
  # pt-BR 1000x separator repair, season-calendar date bijection, monthly-sales value-first
  # dedup) ON TOP of 38dc5f0c (three unica cards + the sales external_* min_nonnull override at
  # 0.12 -- the gate ride again: WITHOUT the gate jobdef on this digest, the newly-populated
  # sales columns red the family on the old baked floor). unica-bronze/b3-flat-silver/
  # unica-annual-state/silver-gate/silver-publisher-runner repinned together (register JSONs in
  # the session scratchpad; owner-run per the local permission gate).
  # OVERNIGHT BUMP 2026-08-20: 554968e7 = the D14 WASDE full-parse + PSD-widening + board_crush
  # build (e437eff7). wasde-bronze-modern repin JSON prepared for the owner; the remaining silver
  # families repin with the post-X2 mini-wave fire.
  # DEC NOW-LANES FLEET BUMP 2026-08-20 (#2, 14:13Z): c5f7900a = commit c4ebbf23 (ESR 44-code
  # universe + 21 new mass-unit slugs + non-mass written skip -- WITHOUT this digest the widened
  # weekly fetch would collapse 21 codes into commodity=unknown, the dec-now-lanes review's
  # blocking find; NASS annual wheat repair 0->6,582 rows proven by replay; PSD/FCOJ card flips).
  # Post-push auditor CLEAN. usda-esr-fetch / esr-bronze-to-silver / usda-nass-bronze /
  # usda-nass-annual-silver hand-repin via owner (register JSONs in the session scratchpad);
  # the ten fleet families adopt on the next apply per this file's standing law.
  default     = "sha256:c5f7900a5c0dd686b0d9bc773de8eebab1851bf845421f248c5a81ebd93aa5fa"

  validation {
    condition     = var.worker_fleet_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.worker_fleet_image_digest))
    error_message = "worker_fleet_image_digest must be empty or a full 'sha256:<64 hex>' digest (a TAG is not accepted -- a tag is the mutability this pin removes)."
  }
}

# --- D-PR-8/D-PR-37: the silver-gate jobdef ADOPTION ----------------------

variable "silver_gate_image_digest" {
  # THE WORKER IMAGE `leviathan-dev-silver-gate` RUNS -- and, by being non-empty,
  # THE SWITCH THAT MAKES TERRAFORM MANAGE THAT JOBDEF FOR THE FIRST TIME.
  #
  # READ THIS BEFORE APPLYING. The gate jobdef is not in state and never has been:
  # 14 live revisions, every one hand-registered with `aws batch
  # register-job-definition`, no committed script (register_evidence_jobdef.py is a
  # different family). Applying `module.batch.aws_batch_job_definition.silver_gate`
  # REGISTERS REVISION 15, and because the DAG inputs name the family unversioned,
  # rev 15 is what every family's [Gate] and [Reconcile] submits on the next fire.
  # The resource body is a field-by-field transcription of live rev 14 plus exactly
  # three additions -- the D-PR-8 retry matrix, a 3600 s per-attempt timeout, and
  # three tags. Read modules/batch/silver_gate.tf top-to-bottom before applying, and
  # diff the planned container_properties against live rev 14; the whole design
  # rests on rev 15 being rev 14 in every field that runs.
  #
  # VALUE = what live rev 14 runs TODAY (tag 20260804T132111, pushed 2026-08-04T10:21Z),
  # which is also var.pink_sheet_image_digest and the digest b3-flat-silver rev 24 and
  # silver-publisher-runner rev 24 run. Alignment to live, NOT a repin: this variable
  # must never be used to bump the gate's image as a side effect of a retry change.
  #   aws batch describe-job-definitions --job-definition-name leviathan-dev-silver-gate \
  #     --status ACTIVE --query 'reverse(sort_by(jobDefinitions,&revision))[0].containerProperties.image'
  #
  # EMPTY = terraform does not manage the gate jobdef at all (count 0, no plan line).
  # There is deliberately no ':latest' fallback: the gate is the job whose entire
  # purpose is to refuse a rebuild, so "which image judged this promote?" must always
  # have an answer (incident I-1).
  type        = string
  description = "sha256 digest of the worker image the silver-gate jobdef runs. Empty = terraform does not manage the gate jobdef (no ':latest' fallback for the gate)."
  # D-SG S-C repin 2026-08-16: cf50c051 bakes the season floors (G1-5), the ESR
  # vintage_waiver (G1-6 PATH A) and the GateVerdict/ValueCensusHardFailTables
  # emitters (G3-4) into the gate. timeline_rebuild's identical old digest below is
  # DELIBERATELY NOT moved (the fleet-digest law: one intended move per variable).
  default     = "sha256:53db13d53bfb3b5066d92100930f56ee98c1cca309d692be5b6d88cbb18847d2"

  validation {
    condition     = var.silver_gate_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.silver_gate_image_digest))
    error_message = "silver_gate_image_digest must be empty or a full 'sha256:<64 hex>' digest -- a TAG is never accepted for the gate."
  }
}

# --- D-PR-4 (lane A arming): the weekly ECR pin auditor -------------------

variable "ecr_pin_audit_image_digest" {
  # The EMBEDDER image the weekly fleet audit runs, pinned BY DIGEST.
  #
  # WHY THE EMBEDDER AND NOT THE WORKER (plan precondition P1, re-verified 2026-08-04):
  # docker/leviathan_worker/Dockerfile COPYs src/ jobs/ configs/ sql/ and NOT scripts/.
  # docker/leviathan_embedder/Dockerfile:43 is the only one with `COPY scripts/ ./scripts/`,
  # so scripts/ops/check_ecr_pinned_digests.py exists ONLY in the embedder image. A weekly
  # schedule on any worker-image jobdef could not run this script at all.
  #
  # WHY BY DIGEST AND NOT ':latest': the digest must be at or after fc2e1a32 (the D-PR-3
  # auditor rebuild) or the schedule quietly runs the PRE-REPAIR auditor, which reports
  # "FAIL: 1" for a 19-family outage -- worse than no schedule at all.
  #
  # VALUE = what ':latest' resolved to at 2026-08-04T14:15Z (tag 20260804T171437, pushed
  # 2026-08-04T14:15:23Z). Its S3 manifest sidecar carries
  # git_commit dbdf41c81420d7f7be42d076db381a6c7baa9a75, and `git merge-base --is-ancestor`
  # confirms dbdf41c8 CONTAINS fc2e1a32 (auditor rebuild) and 24fe0f53. The plan text names
  # the older 5247cf77 digest; :latest moved at 14:15Z and this pin follows live rather than
  # the document -- both carry the repaired auditor, this one is the current build.
  #
  # Re-pin deliberately after an embedder rebuild:
  #   aws ecr describe-images --repository-name leviathan-dev-leviathan-embedder \
  #     --image-ids imageTag=latest --query 'imageDetails[0].imageDigest'
  # Empty = the whole weekly-audit unit (role, jobdef, scheduler role, DLQ, alarm, schedule)
  # count-gates out of existence. That is the kill-switch and the bootstrap state.
  # RE-PINNED 2026-08-19 after the unica-splice embedder rebuild (commit 38dc5f0c): :latest =
  # tag 20260819T021949, manifest sidecar written by build_push_embedder.ps1 on push. The prior
  # pin (4c71250b, 2026-08-04) stays pullable -- this repo carries no lifecycle policy.
  type        = string
  description = "sha256 digest of the EMBEDDER image the weekly ECR pin audit runs. Empty = the whole D-PR-4 weekly unit is not created."
  # RE-PINNED 2026-08-19 (#2): rev-105 build (commit 19d30450 -- the three D-EC P0 graph fixes
  # + the unica card-notes repair record). Canary three tells passed on taskdef 105.
  # RE-PINNED 2026-08-19 (#3): the pre-X2 batch build (commit db18565c -- six preconditions +
  # routing curation). evidence-build jobdef rev 79 registered on it the same hour (owner-run).
  # RE-PINNED 2026-08-20: the overnight batch build (commits 78c911dd..e437eff7 -- D13/D14,
  # temperature pin, Wave 1c routing, XC-2/XC-5 merge, numbers mini-wave). Serving 107 canaried.
  default     = "sha256:915f8426c8c16a392add983e7fd0e0630741dc12fbd0646541ae1d44b30bdbb5"

  validation {
    condition     = var.ecr_pin_audit_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.ecr_pin_audit_image_digest))
    error_message = "ecr_pin_audit_image_digest must be empty or a full 'sha256:<64 hex>' digest (a TAG is not accepted -- a tag would let a later push swap the auditor under the schedule)."
  }
}

variable "ecr_pin_audit_scheduled_marker" {
  # DELIVERY, OR THE WEEKLY FIRE IS SILENT (plan precondition P4).
  #
  # A FAILED Batch job pages the owner only through the metric filter
  # leviathan-dev-batch-failed-scheduled on /leviathan/dev/batch-job-failures. Re-read live
  # 2026-08-04, its pattern is:
  #   { ($.detail.status = "FAILED") && (($.detail.container.environment[*].name = "MANAGED_BY_AWS")
  #     || ($.detail.jobName = "build-notifications*") || ($.detail.jobName = "pattern-records-sweep*")
  #     || ($.detail.jobName = "freshness-poller*") || ($.detail.jobName = "usda-esr-fetch*")) }
  # The account-wide batch-job-failed rule is NOT a delivery path -- it targets
  # silver-pipeline-alerts, which has ZERO subscriptions. So a jobdef named ecr-pin-audit with
  # no marker alarms NOWHERE: D-PR-28's "no delivery mechanism" defect, repeated.
  #
  # This variable exists so the marker NAME is a single declared value rather than a string
  # buried in a jobdef. If D-PR-13 lands and renames the marker to LEVIATHAN_SCHEDULED, change
  # it HERE and both new jobdefs follow. Verify against live before enabling either schedule:
  #   aws logs describe-metric-filters --log-group-name /leviathan/dev/batch-job-failures \
  #     --query "metricFilters[].filterPattern"
  type        = string
  description = "Environment-variable NAME that the live batch-failed-scheduled metric filter matches. Changing this must be done in lockstep with that filter."
  default     = "MANAGED_BY_AWS"
}

# --- R7b: the weekly timeline rebuild ---------------------------------------

variable "timeline_rebuild_image_digest" {
  # The WORKER image the weekly graphrag timeline rebuild runs, pinned BY DIGEST.
  #
  # PROVEN, NOT CHOSEN. `python -m leviathan.graphrag.timeline --run` was run to completion on
  # 2026-08-04 as Batch job `r5-timeline-derive` (638b80cb-cd2f-43a2-8337-743b534692a2) on
  # leviathan-dev-silver-gate:12 / leviathan-dev-queue-ondemand: exit 0 in 26 seconds, argv
  # exactly ["-m","leviathan.graphrag.timeline","--run"], with EVIDENCE_PG_DSN mounted from
  # Secrets Manager. This unit reproduces that run as a schedule.
  #
  # VALUE = the worker digest that is BOTH ':latest' today AND what the live latest-ACTIVE
  # leviathan-dev-silver-gate (rev 14), b3-flat-silver (rev 24) and silver-publisher-runner
  # (rev 24) all run -- i.e. the same image the post-freeze batch pinned the pink-sheet chain
  # to. The rebuild therefore runs the same build as the gate that audits everything else.
  # (The proven run's image was the older 51f6b670; e8aa7857 is strictly newer on the same
  # branch and is what the estate runs now, so this is alignment-to-live, not a repin.)
  #
  # Empty = the whole R7b unit (jobdef, scheduler role, DLQ, alarm, schedule) count-gates out
  # of existence.
  type        = string
  description = "sha256 digest of the worker image the weekly timeline rebuild runs. Empty = the whole R7b unit is not created."
  default     = "sha256:02e1fde47acd054512abfc33306d5a7d070ebe6c5e3c3f3a4cd9dfbd05545c53"

  validation {
    condition     = var.timeline_rebuild_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.timeline_rebuild_image_digest))
    error_message = "timeline_rebuild_image_digest must be empty or a full 'sha256:<64 hex>' digest (a TAG is not accepted)."
  }
}

# MLflow tracking server (module.mlflow_fargate). DEFAULT FALSE since 2026-07-26: the server was
# decommissioned for cost (see the module block in main.tf). The default lives HERE, in the repo, rather
# than in the gitignored tfvars -- otherwise a fresh checkout would default it back ON and quietly restart
# the ~$16-18/mo ALB. Set true (or -var mlflow_enabled=true) to bring the whole stack back.
variable "mlflow_enabled" {
  type        = bool
  default     = false
  description = "Create the MLflow Fargate stack (service + ALB + Route53 + Cognito client). Off = decommissioned."
}

# --- D-LD Q5 (2026-08-18): the metering-exempt subject list ------------------
variable "serving_meter_exempt_subs" {
  # GRAPHRAG_METER_EXEMPT_SUBS on the serving container: comma-separated Cognito subs
  # exempt from credit metering (OPS-3, the owner's own account). The VALUE lives in the
  # gitignored terraform.tfvars -- a sub is an account identifier and this repo is PUBLIC.
  # Empty default keeps a fresh clone valid; the config-of-record fold (envs/dev/main.tf,
  # CR-3) reads it so a tf re-derivation of the serving env no longer drops the key.
  type      = string
  default   = ""
  sensitive = true
}
