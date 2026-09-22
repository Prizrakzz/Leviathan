"""THE MIRROR LOAD GETS A JOB DEFINITION THAT LOADS, AND A SCHEDULE THAT FIRES IT.

Pins for census B1/P1 (2026-09-22). Every test here fails on HEAD, where neither
``jobs/utils/register_pg_numbers_loader_jobdef.py`` nor
``infra/terraform/envs/dev/schedule_pg_numbers_load.tf`` exists.

WHAT WAS MEASURED, and why the registrar could not simply be copied from its sibling:
  * ``leviathan-dev-pg-numbers-loader`` has TWO ACTIVE revisions and has NEVER LOADED ANYTHING --
    both carry the placeholder command ``['-c', "print('override me')"]``, both run under
    ``leviathan-dev-silver-publisher`` (the PUBLISH role), both are 2 vCPU / 8 GB, and its only two
    CloudWatch streams are dated 2026-07-31. Every real load ran through
    ``leviathan-dev-evidence-build`` under ``leviathan-dev-batch-job-role``.
  * A schedule firing the placeholder would SUCCEED, exit 0 and load nothing -- a green fire that
    did nothing, which is the ICCO/MPOC class. So the jobdef must carry the REAL command before the
    schedule is applied, and the terraform must carry NO command of its own.
  * ``leviathan-dev-leviathan-worker``'s ``latest`` tag points at a 2026-08-27 image while the
    repository's newest is 20260916-seams -- so the ``:latest`` idiom that register_evidence_jobdef
    uses would have been a silent 26-day ROLLBACK here.

AWS-free: constants, fake clients and a text read of the terraform.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

reg_mod = importlib.import_module("jobs.utils.register_pg_numbers_loader_jobdef")
loader = importlib.import_module("jobs.utils.load_pg_numbers")

_TF = (Path(__file__).resolve().parents[2] / "infra" / "terraform" / "envs" / "dev"
       / "schedule_pg_numbers_load.tf")


def _tf_code() -> str:
    """The terraform with its full-line comments removed.

    The comments in that file NAME the things the code must not do -- "NO ContainerOverrides",
    "never ``leviathan-dev-silver-publisher``", the sibling roles it is modelled on -- so a test that
    greps the raw text would fail on the prose that explains the rule. Assert against the CODE."""
    return "\n".join(ln for ln in _TF.read_text(encoding="utf-8").splitlines()
                     if not ln.lstrip().startswith("#"))


# --- the job definition ----------------------------------------------------------------------

def test_the_command_is_the_real_loader_and_carries_no_table_subset():
    """No ``--tables`` IS the P1 set: load_pg_numbers' argparse default is ``",".join(P1_TABLES)``.
    A subset baked into the jobdef would silently shrink the nightly mirror the day a table was
    added to P1_TABLES."""
    assert reg_mod._COMMAND == ["jobs/utils/load_pg_numbers.py"]
    assert not any(a.startswith("--tables") for a in reg_mod._COMMAND)
    # the script the command names must exist, spelled exactly as the image lays it out under /app
    assert (Path(__file__).resolve().parents[2] / reg_mod._COMMAND[0]).is_file()


def test_the_job_role_is_the_one_the_real_loads_ran_under():
    """``leviathan-dev-batch-job-role``, never ``leviathan-dev-silver-publisher``. A load has no
    business holding publish authority, and the publisher role was on revisions 1-2 only because
    nothing had ever exercised them."""
    assert reg_mod._JOB_ROLE == "leviathan-dev-batch-job-role"
    assert "silver-publisher" not in reg_mod._CONTAINER["jobRoleArn"]


def test_the_image_family_is_the_worker_repository():
    """"A jobdef REPIN keeps the repository" -- a cross-family digest dies at STARTING with
    CannotPullContainerError and no log stream (measured 2026-09-09). Both live revisions of this
    jobdef are on the WORKER repo, so that is the family, even though the sibling registrar this
    file is modelled on targets the EMBEDDER repo."""
    assert reg_mod._REPO == "leviathan-dev-leviathan-worker"


def test_the_registrar_refuses_a_cross_family_repin():
    class _Batch:
        def describe_job_definitions(self, **_kw):
            return {"jobDefinitions": [{
                "revision": 2,
                "containerProperties": {
                    "image": "668891723125.dkr.ecr.us-east-1.amazonaws.com/"
                             "leviathan-dev-leviathan-embedder@sha256:deadbeef"},
            }]}

    with pytest.raises(SystemExit) as e:
        reg_mod._assert_repository_family(_Batch())
    assert "CannotPullContainerError" in str(e.value)


def test_the_default_image_is_the_live_digest_and_never_the_latest_tag():
    """THE MEASUREMENT: on 2026-09-22 the worker repo's ``latest`` tag pointed at sha256:91104375
    pushed 2026-08-27, while the newest image was sha256:46f55987 / 20260916-seams -- the digest the
    live revision already carries. A registrar that resolved ``:latest`` would have pinned a 26-day-
    old, five-builds-behind worker and called it a repin. So the default moves the COMMAND, the
    ROLE, the SIZE, the TIMEOUT and the RETRY rules, and leaves the image exactly where it is."""
    live = ("668891723125.dkr.ecr.us-east-1.amazonaws.com/"
            "leviathan-dev-leviathan-worker@sha256:46f55987")

    class _Pager:
        def paginate(self, **_kw):
            return [{"imageDetails": [
                {"imageDigest": "sha256:46f55987", "imageTags": ["20260916-seams"],
                 "imagePushedAt": 200},
                {"imageDigest": "sha256:91104375", "imageTags": ["latest"], "imagePushedAt": 100},
            ]}]

    class _Ecr:
        def get_paginator(self, _name):
            return _Pager()

        def describe_images(self, **kw):
            tag = kw["imageIds"][0]["imageTag"]
            return {"imageDetails": [{"imageDigest": {"latest": "sha256:91104375",
                                                      "20260916-seams": "sha256:46f55987"}[tag]}]}

    digest, notes = reg_mod._resolve_image(_Ecr(), live, None)
    assert digest == "sha256:46f55987"
    assert any("UNCHANGED" in n for n in notes)
    # ...and asking for the stale tag explicitly is legal, but it SAYS SO.
    digest, notes = reg_mod._resolve_image(_Ecr(), live, "latest")
    assert digest == "sha256:91104375"
    assert any("NOT the repository's newest image" in n for n in notes)


def test_the_retry_rules_cover_the_pre_start_class_only_and_end_in_a_terminal_exit():
    """The failure this exists for was measured on 2026-09-21: ``StatusReason: "Rate limit exceeded
    while preparing network interface..."`` with ``ExitCode: None`` -- the container never ran.

    It must stay this narrow because this job DROPs and re-CREATEs every mirrored table: a retry of
    a job that actually STARTED would re-run that write path, which is the T2b publisher exclusion.
    Batch takes the FIRST matching rule, so the terminal EXIT must be LAST and nothing may follow
    it."""
    rs = reg_mod._RETRY_STRATEGY
    assert rs["attempts"] == 2
    rules = rs["evaluateOnExit"]
    assert [r["action"] for r in rules] == ["RETRY", "RETRY", "RETRY", "EXIT"]
    assert {r["onStatusReason"] for r in rules[:3]} == {
        "CannotPullContainer*", "ResourceInitializationError*", "Rate limit exceeded*"}
    assert rules[-1] == {"onStatusReason": "*", "action": "EXIT"}
    # no rule may key on an exit code: an exit code means the container RAN.
    assert not any("onExitCode" in r for r in rules)


def test_the_size_and_timeout_are_the_measured_ones():
    rr = {d["type"]: d["value"] for d in reg_mod._CONTAINER["resourceRequirements"]}
    assert rr == {"VCPU": "4", "MEMORY": "16384"}
    assert reg_mod._TIMEOUT_SECONDS == 7200


def test_the_dsn_secret_and_the_serving_backend_ride_the_jobdef():
    """The loader exits 1 without EVIDENCE_PG_DSN ("run in-VPC via the Batch submit"), so the
    secret is a property of the job definition and not of a submission."""
    assert reg_mod._PG_DSN_SECRET_NAME == "leviathan/dev/evidence-pg-dsn"
    env = {e["name"]: e["value"] for e in reg_mod._CONTAINER["environment"]}
    assert env["GRAPHRAG_NUMBERS_BACKEND"] == "pg"
    assert env["PYTHONUNBUFFERED"] == "1", "a load nobody can watch live cannot be watched end to end"


# --- the schedule ------------------------------------------------------------------------------

def test_the_schedule_file_exists_and_names_the_resources_the_owner_hand_targets():
    """O6 plans with ``-target=aws_scheduler_schedule.pg_numbers_loader
    -target=aws_iam_role.pg_numbers_loader_scheduler``. A renamed resource makes that line silently
    plan nothing."""
    tf = _tf_code()
    assert 'resource "aws_scheduler_schedule" "pg_numbers_loader"' in tf
    assert 'resource "aws_iam_role" "pg_numbers_loader_scheduler"' in tf
    assert 'resource "aws_sqs_queue" "pg_numbers_loader_scheduler_dlq"' in tf


def test_the_schedule_fires_at_2345z_on_the_on_demand_queue():
    """SPOT is forbidden for a schedule (standing law) and doubly so here: a reclamation mid-COPY
    kills a 17M-row rebuild."""
    tf = _tf_code()
    assert 'schedule_expression = "cron(45 23 * * ? *)"' in tf
    assert "local.ondemand_job_queue_arn" in tf
    assert "queue-spot" not in tf


def test_the_schedule_carries_no_command_of_its_own():
    """The command lives in ONE place: the job definition. An override here would put it in two,
    which is the drift class the freshness poller's inline-python block cost this estate twice."""
    tf = _tf_code()
    assert "ContainerOverrides" not in tf
    assert "load_pg_numbers.py" not in tf
    # the target names the jobdef family UNVERSIONED, so a repin needs no terraform
    assert 'JobDefinition = "${var.project_name}-${var.environment}-pg-numbers-loader"' in tf


def test_the_schedule_has_its_own_scoped_role_and_never_borrows_one():
    """Scheduler roles are RESOURCE-SCOPED per jobdef in this estate; a borrowed role AccessDenies at
    fire time, and a fire-time AccessDenied is invisible until somebody notices the job never
    existed."""
    tf = _tf_code()
    # EXACTLY ONE role_arn in the whole unit, and it is this unit's own role. A borrowed one would
    # show up here as a second (or different) reference.
    role_arns = [ln.strip() for ln in tf.splitlines() if ln.strip().startswith("role_arn")]
    assert role_arns == ["role_arn = aws_iam_role.pg_numbers_loader_scheduler.arn"], role_arns
    assert "job-definition/${var.project_name}-${var.environment}-pg-numbers-loader*" in tf
    # the DLQ grant is its OWN statement, never folded into the SubmitJob action list
    assert tf.count('Action   = "sqs:SendMessage"') == 1
    assert tf.count('Action = "batch:SubmitJob"') == 1


def test_the_schedule_takes_zero_scheduler_retries():
    """Scheduler delivery is at-least-once, so a retry can submit the job TWICE, and two concurrent
    17M-row DROP+CREATE+COPY runs would contend for the RDS instance the serving pool shares (the
    2026-07-22 rev-51 pool death). Same call the pattern-records sweep makes, for the same reason: a
    write path takes no scheduler retries, and the DLQ + the parity tip leg announce the miss."""
    tf = _tf_code()
    assert "maximum_retry_attempts       = 0" in tf
    assert "dead_letter_config" in tf


# --- the submit wrapper, so the new jobdef can be SMOKED the way the real loads ran -------------

def test_the_submit_wrapper_keeps_its_default_path_byte_for_byte(monkeypatch, capsys):
    """THE BYTE-IDENTICAL SET for the submit change. With no flags the wrapper must still name
    ``leviathan-dev-evidence-build`` and still send the 2 vCPU / 8192 MB override -- that is where
    the 2026-09-10 full load and the 2026-09-17 MPOB reload actually ran, and a submit path that has
    worked twice is not something to improve on the way to fixing something else."""
    sub = importlib.import_module("jobs.submit.submit_batch_load_numbers_pg")
    captured = {}
    monkeypatch.setattr("sys.argv", ["submit", "--dry-run"])
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(sub, "logger", type("L", (), {
        "info": staticmethod(lambda msg, *a: captured.setdefault("lines", []).append(msg % a
                                                                                    if a else msg))})())
    sub.main()
    joined = " ".join(captured["lines"])
    assert "job_def=leviathan-dev-evidence-build" in joined
    assert "python jobs/utils/load_pg_numbers.py" in joined


def test_the_submit_wrapper_does_not_shrink_a_purpose_built_jobdef(monkeypatch):
    """An unasked-for ``resourceRequirements`` override would silently put the 4 vCPU / 16 GB
    scheduled loader back on the placeholder revision's 2 vCPU. Unspecified sizing on a NON-default
    jobdef must send no override at all; an explicit --vcpu still wins."""
    import argparse

    sub = importlib.import_module("jobs.submit.submit_batch_load_numbers_pg")
    src = __import__("inspect").getsource(sub.main)
    # the sentinel defaults are the mechanism -- assert them rather than the prose
    assert 'ap.add_argument("--vcpu", type=int, default=None)' in src
    assert 'ap.add_argument("--memory", type=int, default=None)' in src
    assert 'if args.vcpu or args.memory or job_definition == default_jobdef:' in src
    assert 'ap.add_argument("--job-definition"' in src
    del argparse


# --- the roster the whole thing loads ----------------------------------------------------------

def test_one_p1_entry_per_physical_table():
    """The loader's own rule, previously a comment only: "NOTE one P1 entry per PHYSICAL -- a second
    entry on the same physical would DROP+CREATE over the first's load". Two cards on one physical
    (silver_production / silver_production_livestock) is exactly the shape that would break it."""
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    physicals: dict[str, list[str]] = {}
    for tid in loader.P1_TABLES:
        ts = reg.tables.get(tid)
        if ts is None:
            continue
        physicals.setdefault(ts.athena_table or ts.id, []).append(tid)
    dups = {p: t for p, t in physicals.items() if len(t) > 1}
    assert dups == {}, f"one physical, two P1 entries -- the second DROPs the first: {dups}"
    assert len(loader.P1_TABLES) == len(set(loader.P1_TABLES)) == 39


def test_a_failed_scheduled_load_reaches_the_alarm_that_pages():
    """2026-09-22 review MAJOR-1 (D-PR-28's 'no delivery mechanism', a third sighting): the only failure
    metric filter whose alarm carries an SNS action matches MANAGED_BY_AWS in the container environment
    or a three-name jobName allowlist this job is not on. A nightly load that fails without the marker
    restores the census's B1 state (a stale mirror) with nobody told, so the marker is part of the fix."""
    env = {e["name"]: e["value"] for e in reg_mod._CONTAINER["environment"]}
    assert env.get("MANAGED_BY_AWS") == "scheduler", env
