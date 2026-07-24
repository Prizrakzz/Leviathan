# T2B pattern-records daily-sweep schedule — tfvars / terraform HAND-ADD notes (AUTHORED, not applied)

Plan sec 7 step 5 (T2B_PATTERN_RECORDS_PLAN.md). The daily engine-replay sweep runs on the A1-A2
EventBridge scheduler estate but as a **standalone `aws_scheduler_schedule` → Batch submitJob** target —
the **P3 morning-brief precedent** (`aws_scheduler_schedule.notifications` in
`infra/terraform/envs/dev/main.tf`), a dedicated scoped role + jobdef, **created DISABLED**. It is NOT a
`gen_sfn_inputs` silver-rebuild SFN family (no fetch/bronze/silver/gate/promote), so it is **not** a
top-level `configs/silver/dags/*.json` descriptor and does **not** ride `dag_schedules.auto.tfvars.json`.

**Why hand-authored, never regenerated:** armed tfvars promotes are hand-authored (co-tenant discipline).
The block below is authored here and **hand-added** by the operator at rollout step 5; `gen_sfn_inputs.py`
neither renders nor validates it.

## Terraform block to hand-add to `infra/terraform/envs/dev/main.tf`

```hcl
# T2B pattern-records daily engine-replay sweep. Ships DISABLED (the P3 morning-brief pattern): one
# manual day-0 sweep the operator reviews first, then flip to ENABLED and inspect the first cron fire.
# Rollback = DISABLE (never touches the GRAPHRAG_PATTERN_RECORDS card flag). The jobdef is registered
# out-of-band and referenced BY NAME (unversioned -> latest ACTIVE revision).
resource "aws_iam_role" "pattern_records_scheduler" {
  name = "${var.project_name}-${var.environment}-pattern-records-scheduler"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "pattern_records_scheduler" {
  name = "${var.project_name}-${var.environment}-pattern-records-scheduler-submit"
  role = aws_iam_role.pattern_records_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "batch:SubmitJob"
      Resource = [
        module.batch.job_queue_arn,
        "arn:aws:batch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:job-definition/${var.project_name}-${var.environment}-pattern-records-sweep:*",
      ]
    }]
  })
}

resource "aws_scheduler_schedule" "pattern_records_daily" {
  name  = "${var.project_name}-${var.environment}-pattern-records-daily"
  state = "DISABLED" # day-0 manual sweep reviewed FIRST; flip to ENABLED after review, then inspect the first fire

  flexible_time_window { mode = "OFF" }
  schedule_expression = "cron(0 9 * * ? *)" # 09:00 UTC daily (after overnight silver families promote)

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:batch:submitJob"
    role_arn = aws_iam_role.pattern_records_scheduler.arn
    input = jsonencode({
      JobName       = "pattern-records-sweep"
      JobQueue      = module.batch.job_queue_arn
      JobDefinition = "${var.project_name}-${var.environment}-pattern-records-sweep"
      ContainerOverrides = {
        Command = ["jobs/batch/pattern_records_sweep_task.py", "--asof", "<aws.scheduler.scheduled-time>", "--publish-mode", "canonical"]
        Environment = [
          { Name = "LEVIATHAN_APPROVAL_MODE", Value = "kms" },
          { Name = "LEVIATHAN_KMS_KEY_ID", Value = "alias/leviathan-dev-publish-signer" },
          { Name = "GRAPHRAG_NUMBERS_BACKEND", Value = "pg" }
        ]
      }
      RetryStrategy = { Attempts = 2 }
    })
  }
}
```

## Rollout (plan sec 7)

1. Register the scoped jobdef `leviathan-dev-pattern-records-sweep` (own role; gold/pattern_records write
   scope only) out-of-band; content-check the image (`inspect.getsource` markers for the sweep
   entrypoint — never trust `:latest`).
2. **Backfill (step 4, ONE-TIME, manual — not scheduled):** `--backfill --publish-mode canonical`
   (provenance=backfill_grid) over the bounded weekly VINTAGED-leg grid. Verify the provenance predicate
   holds (no daily_sweep rows yet). Rollback = delete the backfill partitions (isolated by
   as_of_date + provenance).
3. `terraform apply -target` the two IAM resources + the schedule (DISABLED). Manual day-0 sweep; review.
4. Flip `state = "ENABLED"`; inspect the first cron fire (describe-jobs: the submitted job is the
   pattern-records jobdef). Rollback = DISABLE.

## Sequencing fence (plan sec 8)

The writer/backfill/schedule (steps 1–5) add NO serving surface and may proceed in parallel with the
T2a pace soak. Only the **card flip** (GRAPHRAG_PATTERN_RECORDS=on, a separate serving-rev env change)
is sequenced AFTER the pace soak completes and the chain-engine flips — one flag movement per
measurement window.
