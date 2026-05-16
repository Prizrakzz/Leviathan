# AWS Batch Processing Framework

> Lessons from the CHIRPS backfill incident — May 16, 2026.
>
> **Root cause**: 1,426 Glue Python Shell jobs submitted across 4 runs (~5,060 total
> `StartJobRun` calls in 48 hours) triggered an AWS account-level "Glue mitigation"
> Health Event with no automatic end date and an **Action required** flag.
> The correct tool — AWS Batch Fargate Spot — was already set up in this project
> for NASA POWER and was simply not used for CHIRPS.

---

## 1. The Incident: What Went Wrong

### Timeline

| Run | Jobs submitted | Outcome | Root cause |
|-----|---------------|---------|------------|
| 1 | 1,426 | Throttled | 100 concurrent `StartJobRun` API calls |
| 2 | 1,426 | ConcurrentRunsExceeded | Orphaned run-1 jobs occupied all 200 DPU slots |
| 3 | 1,426 | 944 ✅ / 482 ❌ | `Task allocated capacity exceeded limit` — not in retry predicate |
| 4 | 782 | 0 ✅ / 782 ❌ | AWS account-level Glue mitigation triggered |
| **Total** | **~5,060** | **AWS Health Event** | Excessive API hammering over 48 hours |

### What was already in the repo (and unused for CHIRPS)

```
infra/terraform/modules/batch/main.tf       ← Fargate Spot compute environment + job queue
infra/terraform/modules/ecr/main.tf         ← container image registry
jobs/submit_batch_backfill_nasa_power.py    ← reference submission script
jobs/backfill_raw_nasa_power.py             ← reference task entrypoint
```

The NASA POWER backfill uses AWS Batch Fargate Spot correctly: one task per
`(commodity, country, region, year)`, submitted in a simple loop, no Glue at all.
The CHIRPS backfill should have followed the exact same pattern from the start.

---

## 2. Service Selection

### Decision flowchart

```
Is this a one-time / historical backfill?
├── YES → Task count > 50?
│         ├── YES → AWS Batch Fargate Spot  ← always preferred
│         └── NO  → EC2 Spot t3.medium (run script directly; cheapest for tiny runs)
└── NO  → Recurring scheduled job?
          ├── YES → Job count per execution ≤ 50?
          │         ├── YES → Glue Python Shell  (apply concurrency rules in §4)
          │         └── NO  → Glue Spark or Batch
          └── NO  → Step Functions + Lambda (tasks < 15 min) or Batch
```

### Summary table

| Workload type | Recommended service | Avoid |
|--------------|--------------------|----|
| One-time historical backfill, > 50 tasks | **AWS Batch Fargate Spot** | Glue Python Shell |
| One-time backfill, ≤ 50 tasks | EC2 Spot or Batch | Glue |
| Daily/weekly incremental ETL, ≤ 50 jobs | Glue Python Shell | Batch (overkill) |
| Heavy SQL transform, Catalog integration | Glue Spark | — |
| Sub-15-min event-driven transform | Lambda | Glue (startup cost) |
| Multi-stage pipeline with dependencies | Step Functions + any above | — |

---

## 3. Cost Comparison

Assumptions: 1,426 tasks, 5-minute average duration, us-east-1.

| Service | Unit rate | 1,426 tasks × 5 min | Notes |
|---------|-----------|---------------------|-------|
| Glue Python Shell 1.0 DPU | $0.44 / DPU-hr | **~$52** | 1-minute minimum billing |
| Glue Python Shell 1.0 DPU (37-min avg) | $0.44 / DPU-hr | **~$387** | If tasks are data-heavy |
| AWS Batch Fargate on-demand (0.25 vCPU / 0.5 GB) | ~$0.012 / task-hr | **~$1.44** | No minimum |
| AWS Batch Fargate **Spot** (0.25 vCPU / 0.5 GB) | ~$0.004 / task-hr | **~$0.48** | ~70% discount |

**Rule of thumb**: if submitting > 50 Glue jobs for a one-time backfill, stop and use
Batch Spot instead. The cost difference is 50–800×.

---

## 4. Pre-Flight Checklist (Required Before Any Large Batch Run)

Before submitting more than 20 jobs or tasks to any AWS service:

- [ ] **Estimate cost** — `task_count × expected_duration_hr × unit_rate`. If > $20, use Batch Spot.
- [ ] **Check quota headroom**
  ```powershell
  aws service-quotas list-service-quotas --service-code glue --region us-east-1 `
    --query "Quotas[?contains(QuotaName,'Python') || contains(QuotaName,'concurrent')].{Name:QuotaName,Value:Value}" `
    --output table
  ```
  Stay at or below **25% of the concurrent-runs quota**.
- [ ] **Scale test** — run 1 task → 10 tasks → 50 tasks. Never jump from 1 to full scale.
- [ ] **Confirm idempotency** — `--skip-existing` / `force_overwrite=false` is the default.
- [ ] **Confirm 0 orphaned jobs** — no prior run's jobs are still in STARTING/RUNNING state.
- [ ] **Set a CloudWatch alarm** on job failure rate before triggering.
- [ ] **Monitor Cost Explorer** hourly during the run.

---

## 5. Concurrency Rules for Glue (When Glue Is the Right Choice)

### Safe operating limits — this account, us-east-1

| Metric | Hard quota | Safe target |
|--------|-----------|-------------|
| Concurrent Python Shell runs | 200 | **≤ 50** |
| `StartJobRun` API call rate | ~5 / sec | **≤ 2 / sec** |
| `ThreadPoolExecutor` `max_workers` for submission | — | **≤ 10** |
| Sliding window size (jobs in-flight) | — | **20** |

### Sliding window pattern — replace bulk submit

```python
# NEVER for > 50 jobs:
with ThreadPoolExecutor(max_workers=20) as pool:
    futures = [pool.submit(start_job, j) for j in all_1426_jobs]  # triggers Health Events

# CORRECT — sliding window:
import time

WINDOW        = 20
POLL_INTERVAL = 30  # seconds

queue    = list(all_jobs)
inflight = {}          # {run_id: job_key}
results  = {}          # {job_key: terminal_state}

while queue or inflight:
    # Fill up to WINDOW
    while queue and len(inflight) < WINDOW:
        job    = queue.pop(0)
        run_id = start_job(job)
        inflight[run_id] = job

    # Poll and drain completed
    for run_id in list(inflight):
        state = get_job_state(run_id)
        if state in {"SUCCEEDED", "FAILED", "ERROR", "TIMEOUT", "STOPPED"}:
            results[inflight.pop(run_id)] = state

    if inflight:
        time.sleep(POLL_INTERVAL)
```

### Fix the `_is_throttle` predicate — add capacity errors

```python
def _is_throttle(exc: BaseException) -> bool:
    if not isinstance(exc, botocore.exceptions.ClientError):
        return False
    code = exc.response["Error"]["Code"]
    msg  = exc.response["Error"]["Message"]
    return code in (
        "ThrottlingException",
        "RequestLimitExceeded",
        "Throttling",
        "ConcurrentRunsExceededException",
    ) or (code == "InvalidInputException" and "capacity" in msg.lower())
```

---

## 6. AWS Batch Usage in This Project

### Existing infrastructure

```
infra/terraform/modules/batch/    ← compute environment (Fargate Spot) + job queue
infra/terraform/modules/ecr/      ← container image repository
```

The compute environment is shared across all batch sources. New backfill sources
only need a new `aws_batch_job_definition` block and a new submission script.

### Tuning knobs

| Parameter | Location | Default | Notes |
|-----------|----------|---------|-------|
| `max_vcpus` | `batch/variables.tf` | 16 | 16 vCPU ÷ 0.25 vCPU/task = 64 concurrent tasks |
| `type` | `batch/main.tf` | `FARGATE_SPOT` | Keep; ~70% savings |
| `resourceRequirements` vCPU | job definition | 0.25 | Increase only for memory-bound tasks |
| `resourceRequirements` MEMORY | job definition | 512 MB | Increase for rasterio / pandas heavy jobs |

For a large backfill (> 500 tasks), temporarily increase `max_vcpus` to 128–256 before
submitting and reduce it again afterwards.

### Adding a new backfill source (e.g., CHIRPS)

1. Add `aws_batch_job_definition` in `infra/terraform/modules/batch/main.tf`
   (copy the `nasa_power_backfill` block, change name, command, and parameters).
2. Write `jobs/submit_batch_backfill_{source}.py`
   (copy `submit_batch_backfill_nasa_power.py`, adjust `build_tasks()`).
3. Write `jobs/{source}_task.py` as the container entrypoint
   (copy `backfill_raw_nasa_power.py` structure).
4. `terraform apply` — the new job definition is added to the existing queue.

---

## 7. Monitoring During Large Runs

Open these before starting any run with > 50 tasks:

1. **AWS Health Dashboard** → "Your account health" → "Open and recent issues"
2. **CloudWatch Logs** → `/aws/batch/job` for task stderr
3. **Cost Explorer** → filter by Service = Glue or Batch, granularity = Hourly
4. **Service Quotas** → AWS Glue → "Python shell job runs concurrently"

Stop and reassess if any of these are true:
- Failure rate > 10% of submitted tasks
- Logs show capacity / quota errors
- Hourly cost exceeds 2× the pre-flight estimate

---

## 8. Requesting a Glue Quota Increase (Do This Proactively)

If planning a large run via Glue, request the increase **before** it is needed
(typically 24–72 hours to process):

```powershell
aws service-quotas request-service-quota-increase `
  --service-code glue `
  --quota-code L-8F9F2B1C `
  --desired-value 500 `
  --region us-east-1
```

Never rely on a quota that has zero headroom at the start of a run.
