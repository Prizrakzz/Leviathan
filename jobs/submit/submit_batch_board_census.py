"""Submit THE BOARD CENSUS (design sec 10.1(b), sitting S4) as an in-VPC Batch job.

WHY THIS WRAPPER EXISTS AND WHY IT IS NOT A ONE-LINER. The census must run where the pg mirror is --
in the VPC -- and the jobdef's image PREDATES the census module: it carries `state/**` at the commit
it was built from but not `state/board_census.py`. The in-VPC probe laws (memory
`feedback_invpc_probe_laws`) say what to do about that, and this script is those laws executed:

  1. UPLOAD the module (and nothing else) to `s3://<bucket>/probes/board_census/<ts>/`.
  2. SUBMIT with a SHORT `-c` bootstrap that downloads it and runs it. Batch container overrides
     larger than 8,192 characters fail with NO LOG STREAM, so the override is measured before the
     submit and refused above a stated floor rather than discovered as a silent failure.
  3. WRITE every artifact to S3 as well as to the container's filesystem, because that filesystem is
     ephemeral and an artifact that does not survive the container is an artifact nobody can read.
  4. READ THE EXIT CODE. A census whose exit code nobody read has measured nothing.

THE MODULE RUNS AS A SCRIPT, not as `-m`: `state/board_census.py` is a LEAF (the package imports it
from nowhere), so the container can execute the uploaded file directly from /tmp while every import
inside it resolves against the image's own baked `leviathan` package. That is what keeps the
bootstrap three lines long instead of shipping a shadow package.

    python jobs/submit/submit_batch_board_census.py --dry-run
    python jobs/submit/submit_batch_board_census.py --wait
    python jobs/submit/submit_batch_board_census.py --asof 2026-09-07 --modes quick,deep,max --wait

A SUBMIT IS A PURCHASE, so :func:`annual_handover_open` runs BEFORE any env read and any AWS call and
REFUSES while the one known board-killing defect is still in ``walk`` -- the class that cost the
2026-09-09 pass 140 of 144 board runs. A ``--dry-run`` prints the refusal and continues.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import boto3

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_board_census")

#: The module the image does not have. ONE file: the census is a leaf and imports only the package the
#: image already bakes, so a second upload would be a second thing to keep in sync.
MODULE_REL = "src/leviathan/graphrag/state/board_census.py"

#: Batch's own hard limit on a container override, in characters. The override is measured against it
#: BEFORE the submit because exceeding it fails with no log stream at all -- the failure mode the
#: in-VPC probe laws name by hand.
OVERRIDE_LIMIT = 8192
OVERRIDE_FLOOR = 6000            # refuse well below the cliff; a submit is not the place to find it


def annual_handover_open() -> bool:
    """Is the ONE known board-killing defect still in the image's own ``walk``? (S4 review, MAJOR.)

    THE MEASUREMENT THIS GUARDS AGAINST REPEATING. The 2026-09-09 in-VPC pass (job 7a0f90a9) lost 140
    of 144 board runs -- 35 of 36 boards at ``quick`` alone -- to one raise. Half of it was the null
    boundary and is closed. The other half is a bare marketing-year label (``"2025"``, which
    ``feeders._period_dates`` legitimately writes for the TEN ``date_col``-less annual tables in
    ``configs/graphrag/numbers/tables.yaml``) reaching ``walk._add_months``, whose ``int(iso[5:7])``
    slice is EMPTY on it. ``render`` anchors the SB-J projection on ``st.level_date`` for every
    rendered non-``context_only`` row at every mode, so the raise does not need an analog to fire.

    A SUBMIT IS A PURCHASE. Re-running the census before that one-line hand-over lands buys the same
    35 lost boards a second time, so this is checked HERE, at the door where the money is spent,
    rather than trusted to a runbook. It is a pure import of the repo's own ``walk`` -- no AWS call,
    no clock, no network -- and it is only a proxy for the IMAGE's walk: the two agree exactly when
    the jobdef is repinned past the fix, which is the same precondition every other census re-run has.

    ``--ack-annual-handover`` is the stated escape, for the case where a caller wants the pass anyway
    (a subset that carries no annual card, a probe-only run)."""
    from leviathan.graphrag.state import walk as W
    try:
        W._add_months("2025", 3)
    except ValueError:
        return True
    return False


def bootstrap(bucket: str, prefix: str) -> str:
    """The container's whole command body. Kept to a few hundred characters ON PURPOSE."""
    return (
        "import subprocess,sys,boto3\n"
        f"boto3.client('s3').download_file({bucket!r},{prefix!r}+'board_census.py',"
        "'/tmp/board_census.py')\n"
        "sys.exit(subprocess.call([sys.executable,'/tmp/board_census.py']+sys.argv[1:]))\n"
    )


def census_args(a) -> list:
    """The census CLI's own arguments, forwarded verbatim so the submit record names the exact run."""
    out = ["--asof", a.asof, "--modes", a.modes, "--out", a.container_out]
    if a.s3_out:
        out += ["--s3", a.s3_out]
    if a.contracts:
        out += ["--contracts", a.contracts]
    if a.width:
        out += ["--width", str(a.width)]
    out += ["--alternative-pass", a.alternative_pass]
    if getattr(a, "prior", ""):
        # THE ONLY WAY P5 REACHES A PRIOR VINTAGE IN-VPC: the container runs the census from /tmp,
        # so its repo-relative search finds nothing and every run would otherwise report "no prior
        # vintage existed" forever. Point this at the previous run's probes.json on S3.
        out += ["--prior", a.prior]
    if a.no_probes:
        out += ["--no-probes"]
    if a.no_cascade_census:
        out += ["--no-cascade-census"]
    if a.no_tape:
        out += ["--no-tape"]
    return out


def log_config(client, job_definition: str) -> dict:
    """The jobdef's OWN log configuration, read rather than assumed -- the task's own instruction, and
    the reason a reader of the run record can find the stream without guessing `/aws/batch/job`."""
    try:
        name, _, rev = str(job_definition).partition(":")
        kw = {"jobDefinitionName": name}
        if rev:
            kw = {"jobDefinitions": [job_definition]}
        resp = client.describe_job_definitions(**kw, status="ACTIVE") if not rev else \
            client.describe_job_definitions(jobDefinitions=[job_definition])
        defs = resp.get("jobDefinitions") or []
        if not defs:
            return {}
        props = (defs[0].get("containerProperties") or {})
        return {"revision": defs[0].get("revision"),
                "image": props.get("image"),
                # THE ENTRYPOINT IS THE BOOTSTRAP'S ONE UNVERIFIED ASSUMPTION, so it is READ and
                # PRINTED rather than assumed. The override is `['-c', code] + args`, which reaches
                # the census's argv only if the image's entryPoint is `python` (or a wrapper that
                # forwards to it). Repo precedent uses this exact shape --
                # `scripts/ops/psd_clock_runbook.py:363` and the pink / cpo runbooks -- but on OTHER
                # jobdefs, and `leviathan-dev-graphrag-eval` is defined nowhere in this tree, so the
                # assumption has never been checked against THIS one. `check_entrypoint` below turns
                # the read into a refusal before a submit burns the wall.
                "entryPoint": props.get("entryPoint"),
                "command": props.get("command"),
                "logConfiguration": props.get("logConfiguration") or {},
                "environment": [e.get("name") for e in (props.get("environment") or [])],
                "secrets": [s.get("name") for s in (props.get("secrets") or [])],
                "retryStrategy": defs[0].get("retryStrategy") or {},
                "jobRoleArn": props.get("jobRoleArn")}
    except Exception as exc:                            # noqa: BLE001 -- advisory, never blocking
        logger.warning("could not describe job definition %s: %s", job_definition, exc)
        return {}


def check_entrypoint(jd: dict) -> str:
    """One line about whether the jobdef's own entryPoint can run a ``-c`` bootstrap.

    ADVISORY, NEVER BLOCKING, and it says which of the three cases it is: an entryPoint that ends in
    a python binary is the shape the bootstrap needs; an ABSENT entryPoint means the image's own
    Dockerfile ENTRYPOINT decides and this script cannot see it (the honest answer is "unverified");
    anything else is a jobdef the override would hand ``-c`` to a program that does not take it."""
    ep = jd.get("entryPoint")
    if not jd:
        return "jobdef could not be described -- entryPoint UNKNOWN"
    if not ep:
        return ("jobdef declares NO entryPoint: the image's own ENTRYPOINT applies and this script "
                "cannot read it -- the `-c` bootstrap is UNVERIFIED on this jobdef (repo precedent "
                "says python; the one re-submit allowance is the safety net)")
    head = str(ep[0] if isinstance(ep, list) else ep)
    tail = head.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if tail.startswith("python"):
        return f"jobdef entryPoint {ep} -- the `-c` bootstrap is the right shape"
    return (f"jobdef entryPoint {ep} is NOT a python binary: `-c <code>` would be handed to it "
            f"verbatim. REVIEW the override before submitting")


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()
    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")

    ap = argparse.ArgumentParser(description="Submit the board census (S4) as an in-VPC Batch job")
    ap.add_argument("--asof", default="2026-09-07")
    ap.add_argument("--modes", default="quick,deep,max")
    ap.add_argument("--contracts", default="", help="comma-separated subset (default: all 36)")
    ap.add_argument("--width", type=int, default=2)
    ap.add_argument("--alternative-pass", default="max")
    ap.add_argument("--no-probes", action="store_true")
    ap.add_argument("--no-cascade-census", action="store_true")
    ap.add_argument("--no-tape", action="store_true")
    ap.add_argument("--prior", default="",
                    help="s3:// (or container-local) path to a PREVIOUS run's probes.json, so P5 "
                         "measures the ONI/IOD vintage-to-vintage diff instead of reporting that no "
                         "prior existed")
    ap.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET",
                                                       "leviathan-dev-shahem-001"))
    ap.add_argument("--job-queue", default=f"{project}-{env}-queue-ondemand")
    # rev 12 = the s6 EMBEDDER digest (sha256:98b45c14..., commit a06a3d6c). rev 11 carried the s6 WORKER digest
    # on this jobdef's EMBEDDER repository and died at STARTING with CannotPullContainerError (2026-09-09 20:31Z):
    # graphrag-eval runs the serving/embedder image, so its digest must always be the embedder's, never the worker's.
    ap.add_argument("--job-definition", default=f"{project}-{env}-graphrag-eval:12")
    ap.add_argument("--vcpu", type=int, default=4)
    ap.add_argument("--memory", type=int, default=16384)
    ap.add_argument("--timeout-s", type=int, default=90 * 60,
                    help="the job's own attemptDurationSeconds -- the wall cap, declared to Batch")
    ap.add_argument("--attempts", type=int, default=1,
                    help="the submit's OWN retryStrategy. 1 by default and deliberately: the census "
                         "is deterministic, so a silent second attempt spends the whole wall again "
                         "to reach the same finding")
    ap.add_argument("--container-out", default="/tmp/board_census")
    ap.add_argument("--s3-out", default="",
                    help="s3://... for the artifacts (default: derived under the probe prefix)")
    ap.add_argument("--wait", action="store_true", help="poll to a terminal status and print it")
    ap.add_argument("--poll-s", type=int, default=30)
    ap.add_argument("--ack-annual-handover", action="store_true",
                    help="submit even though walk._add_months still raises on a bare marketing-year "
                         "label (see annual_handover_open) -- the pass will lose every board that "
                         "renders an annual card")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the EXACT upload and submit and do neither")
    a = ap.parse_args()

    # THE PREFLIGHT, BEFORE ANY ENV IS READ AND BEFORE ANY AWS CALL IS MADE. It is not a lint: it is
    # the door the last census walked through to lose 35 of 36 boards.
    if annual_handover_open() and not a.ack_annual_handover:
        msg = (
            "board census REFUSED: the annual bare-year hand-over is still OPEN.\n"
            "  walk._add_months('2025', 3) raises ValueError: invalid literal for int() with "
            "base 10: ''\n"
            "  render.py anchors the SB-J projection on st.level_date, so EVERY board that renders a "
            "date_col-less\n"
            "  annual card (silver_psd, silver_production, silver_nass_annual, silver_icco_cocoa, "
            "...) errors at\n"
            "  EVERY mode, quick included. Job 7a0f90a9 measured 140/144 runs lost to this class.\n"
            "  THE FIX is one line inside walk._add_months: place the label through "
            "analogs.axis_date, exactly as\n"
            "  analogs._window_end does. THE PROOF is\n"
            "    python -m leviathan.graphrag.state.board_census --offline --fixture "
            "mirror_nulls_annual\n"
            "  coming back with zero board errors (it is RED today, by design).\n"
            "  To submit anyway: --ack-annual-handover")
        # A DRY RUN BUYS NOTHING, so it prints the refusal and continues -- blocking it would block the
        # one command that verifies the submit's own shape. A real submit stops here.
        if a.dry_run:
            logger.warning("%s", msg)
        else:
            raise SystemExit(msg)

    aws_region = get_required_env("AWS_REGION")
    ts = utc_now_iso().replace(":", "-").replace("+00-00", "Z")
    prefix = f"probes/board_census/{ts}/"
    if not a.s3_out:
        a.s3_out = f"s3://{a.bucket}/cascade_census/board/{a.asof}"

    module = Path(MODULE_REL)
    if not module.exists():
        raise SystemExit(f"module not found: {module} (run from the repo root)")

    code = bootstrap(a.bucket, prefix)
    command = ["-c", code] + census_args(a)
    overrides = {"command": command,
                 "resourceRequirements": [{"type": "VCPU", "value": str(a.vcpu)},
                                          {"type": "MEMORY", "value": str(a.memory)}]}
    size = len(json.dumps(overrides))
    logger.info("container override: %d chars (Batch limit %d, this script's floor %d)",
                size, OVERRIDE_LIMIT, OVERRIDE_FLOOR)
    if size > OVERRIDE_FLOOR:
        raise SystemExit(f"override is {size} chars, over this script's {OVERRIDE_FLOOR} floor -- "
                         f"a submit over {OVERRIDE_LIMIT} fails with NO log stream; shorten it")

    logger.info("upload   s3://%s/%s%s  <- %s (%d bytes)",
                a.bucket, prefix, module.name, module, module.stat().st_size)
    logger.info("queue    %s", a.job_queue)
    logger.info("job def  %s", a.job_definition)
    logger.info("timeout  %d s", a.timeout_s)
    logger.info("command  python -c <%d-char bootstrap> %s",
                len(code), " ".join(census_args(a)))
    logger.info("bootstrap:\n%s", code)

    if a.dry_run:
        print(json.dumps({"dry_run": True, "bucket": a.bucket, "key": prefix + module.name,
                          "job_queue": a.job_queue, "job_definition": a.job_definition,
                          "containerOverrides": overrides,
                          "retryStrategy": {"attempts": a.attempts},
                          "timeout": {"attemptDurationSeconds": a.timeout_s},
                          "artifacts_s3": a.s3_out,
                          "override_chars": size,
                          "entrypoint_assumption": (
                              "the override is ['-c', <bootstrap>] + args, which reaches the "
                              "census's argv only if the jobdef's entryPoint is python; the real "
                              "submit describes the jobdef and prints entryPoint/command before "
                              "submitting (no AWS call is made in --dry-run)")}, indent=1))
        return 0

    s3 = boto3.client("s3", region_name=aws_region)
    s3.put_object(Bucket=a.bucket, Key=prefix + module.name, Body=module.read_bytes())
    logger.info("uploaded s3://%s/%s%s", a.bucket, prefix, module.name)

    batch = boto3.client("batch", region_name=aws_region)
    jd = log_config(batch, a.job_definition)
    if jd:
        logger.info("jobdef image=%s logConfiguration=%s", jd.get("image"),
                    json.dumps(jd.get("logConfiguration") or {}))
        logger.info("jobdef entryPoint=%s command=%s", jd.get("entryPoint"), jd.get("command"))
        logger.info("ENTRYPOINT CHECK: %s", check_entrypoint(jd))
        declared_attempts = int((jd.get("retryStrategy") or {}).get("attempts") or 1)
        if declared_attempts > 1:
            logger.info("jobdef declares retryStrategy attempts=%d -- this submit OVERRIDES it to "
                        "%d: the census is DETERMINISTIC, so a finding (an open rectangle, a "
                        "register trip, ATHENA_CALLS != 0) would re-run the whole %d-minute wall to "
                        "reach the same finding", declared_attempts, a.attempts, a.timeout_s // 60)
    job_name = f"board-census-{a.asof.replace('-', '')}"
    resp = batch.submit_job(jobName=job_name, jobQueue=a.job_queue,
                            jobDefinition=a.job_definition,
                            containerOverrides=overrides,
                            retryStrategy={"attempts": int(a.attempts)},
                            timeout={"attemptDurationSeconds": int(a.timeout_s)})
    job_id = resp["jobId"]
    logger.info("submitted job_name=%s job_id=%s", job_name, job_id)

    record = {"run_id": ts, "job_name": job_name, "job_id": job_id,
              "job_queue": a.job_queue, "job_definition": a.job_definition,
              "asof": a.asof, "modes": a.modes, "s3_module": f"s3://{a.bucket}/{prefix}{module.name}",
              "s3_artifacts": a.s3_out, "override_chars": size,
              "attempts": a.attempts, "prior": a.prior,
              "entrypoint_check": check_entrypoint(jd),
              "timeout_s": a.timeout_s, "jobdef": jd}
    out = Path("data/batch_runs") / f"board_census_{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=1), encoding="utf-8", newline="\n")
    logger.info("run record -> %s", out)

    if not a.wait:
        print(json.dumps({"job_id": job_id, "s3_artifacts": a.s3_out}, indent=1))
        return 0

    deadline = time.time() + a.timeout_s + 600
    status, reason, stream = "SUBMITTED", None, None
    while time.time() < deadline:
        d = batch.describe_jobs(jobs=[job_id])["jobs"][0]
        status = d.get("status")
        reason = d.get("statusReason")
        stream = ((d.get("container") or {}).get("logStreamName")) or stream
        logger.info("status=%s stream=%s", status, stream)
        if status in ("SUCCEEDED", "FAILED"):
            break
        time.sleep(a.poll_s)
    exit_code = None
    try:
        d = batch.describe_jobs(jobs=[job_id])["jobs"][0]
        exit_code = (d.get("container") or {}).get("exitCode")
    except Exception:                                   # noqa: BLE001
        pass
    print(json.dumps({"job_id": job_id, "status": status, "exit_code": exit_code,
                      "status_reason": reason, "log_stream": stream,
                      "log_group": ((jd.get("logConfiguration") or {}).get("options") or {})
                      .get("awslogs-group", "/aws/batch/job"),
                      "s3_artifacts": a.s3_out}, indent=1))
    return 0 if status == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
