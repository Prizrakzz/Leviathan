"""T2B pattern-records CLOUD LEGS: the submit wrapper's render/pins + a terraform shape lint.

These are the checks that fail LOUDLY at author time instead of quietly at 23:00 UTC on the first
armed cron. A pattern-records row is a PERMANENT record of what the engine decided at T -- never
recomputed with later data or later code (plan non-goal 6) -- so a mis-wired sweep does not merely
fail, it writes a wrong verdict into history that the write-guard then faithfully protects. Hence:

  * cross-artifact NAME render: the wrapper's jobdef pin must equal the name terraform renders
    (a wrong name dies at submit time with ClientException, the BF-W2 D1 lesson);
  * the wrapper must never register a jobdef (terraform owns it; two owners = a silent revert);
  * the jobdef must carry the pg seam, the engine_version stamp, and the DEDICATED role;
  * the baked command must NOT pin --asof (a date would rot; the task stamps today UTC);
  * the schedule must stay ARMED (it shipped DISABLED by day-0 doctrine -- one manual run, reviewed, THEN
    armed -- and the doctrine was satisfied on 2026-07-25, so the pin now guards the armed state);
  * the IAM grant must be write-scoped to the ledger prefix and append-only (deletes denied).

AWS-free + terraform-free: the tf checks are text-shape asserts over the committed HCL (the repo has
no HCL parser dependency, and `terraform validate` is the author-time gate), read through a
brace-matching block extractor that also proves the blocks are balanced.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TF = _REPO / "infra" / "terraform"
_BATCH_TF = _TF / "modules" / "batch" / "main.tf"
_IAM_TF = _TF / "modules" / "iam" / "main.tf"
_DEV_TF = _TF / "envs" / "dev" / "main.tf"
_DEV_VARS_TF = _TF / "envs" / "dev" / "variables.tf"

# terraform renders every name from these two root variables (envs/dev/terraform.tfvars).
_PROJECT, _ENV = "leviathan", "dev"


def _load_submit(name: str):
    """jobs/ is not an importable package (pytest pythonpath = ['src']); load by file path -- the
    test_submit_evidence_wrappers.py / test_submit_esr_weekly_promote.py convention."""
    spec = importlib.util.spec_from_file_location(name, _REPO / "jobs" / "submit" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sub = _load_submit("submit_batch_pattern_records_sweep")


def _block(text: str, header: str) -> str:
    """Return the HCL block whose opening line contains `header`, by brace matching. Raises if the
    header is absent or the braces do not balance -- the shape lint half of these tests."""
    start = text.index(header)
    depth, i = 0, start
    while True:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
        if i >= len(text):
            raise AssertionError(f"unbalanced braces after {header!r}")


def _statement(policy_doc: str, sid_value: str) -> str:
    """Return the `statement { ... }` block carrying `sid = "<sid_value>"`. Spacing-insensitive (the
    fmt alignment inside a statement varies with its longest key)."""
    needle, pos = f'"{sid_value}"', 0
    while True:
        pos = policy_doc.find("statement {", pos)
        if pos < 0:
            raise AssertionError(f"no statement carries sid {sid_value!r}")
        block = _block(policy_doc[pos:], "statement {")
        if needle in block:
            return block
        pos += 1


def _render(hcl_string: str) -> str:
    return hcl_string.replace("${var.project_name}", _PROJECT).replace("${var.environment}", _ENV)


@pytest.fixture(scope="module")
def batch_tf() -> str:
    return _BATCH_TF.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def iam_tf() -> str:
    return _IAM_TF.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dev_tf() -> str:
    return _DEV_TF.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def jobdef(batch_tf) -> str:
    return _block(batch_tf, 'resource "aws_batch_job_definition" "pattern_records_sweep"')


@pytest.fixture(scope="module")
def schedule(dev_tf) -> str:
    return _block(dev_tf, 'resource "aws_scheduler_schedule" "pattern_records_sweep"')


# ---------------------------------------------------------------------------
# Submit wrapper: pins + the render of the command it will actually send.
# ---------------------------------------------------------------------------
class TestWrapperPins:
    def test_jobdef_name_matches_the_name_terraform_renders(self, jobdef):
        # the cross-artifact render check: wrapper pin == tf-rendered name, not a hopeful literal.
        declared = 'name = "${var.project_name}-${var.environment}-pattern-records-sweep"'
        assert declared in jobdef
        assert _render(declared) == f'name = "{sub._JOB_DEF_NAME}"'
        assert sub._JOB_DEF_NAME == "leviathan-dev-pattern-records-sweep"

    def test_image_is_digest_pinned_never_a_tag(self):
        assert "@sha256:" in sub._ECR_IMAGE
        assert ":latest" not in sub._ECR_IMAGE
        # the placeholder is still in place; when it is filled the guard below must stay honest.
        assert sub._IMAGE_DIGEST_PLACEHOLDER in sub._ECR_IMAGE or sub._ECR_IMAGE.count("@sha256:") == 1

    def test_wrapper_never_registers_a_job_definition(self):
        src = (_REPO / "jobs" / "submit" / "submit_batch_pattern_records_sweep.py").read_text(
            encoding="utf-8")
        # terraform owns the jobdef; a wrapper-registered revision is reverted by the next apply.
        assert "register_job_definition" not in src
        assert "describe_job_definitions" in src

    def test_queue_and_task_path_pins(self):
        assert sub._JOB_QUEUE == "leviathan-dev-queue"
        assert sub._TASK_PATH == "jobs/batch/pattern_records_sweep_task.py"
        assert (_REPO / sub._TASK_PATH).exists()


class TestBuildCommand:
    def test_daily_command_omits_asof(self):
        cmd = sub.build_command(publish_mode="canonical")
        assert cmd == [sub._TASK_PATH, "--publish-mode", "canonical"]
        assert "--asof" not in cmd  # the task stamps today UTC; a pinned date rots

    def test_backfill_command_carries_the_grid_flags(self):
        cmd = sub.build_command(backfill=True, backfill_years=5, asof="2026-07-24",
                                publish_mode="shadow")
        assert cmd[0] == sub._TASK_PATH
        assert cmd[cmd.index("--asof") + 1] == "2026-07-24"          # the grid END
        assert "--backfill" in cmd
        assert cmd[cmd.index("--backfill-years") + 1] == "5"
        assert cmd[cmd.index("--publish-mode") + 1] == "shadow"

    def test_build_only_passes_the_tasks_own_dry_run(self):
        assert sub.build_command(build_only=True)[-1] == "--dry-run"
        assert "--dry-run" not in sub.build_command()

    def test_kinds_and_shadow_prefix_pass_through(self):
        cmd = sub.build_command(kinds="pace,chain", shadow_prefix="gold/pattern_records/_shadow")
        assert cmd[cmd.index("--kinds") + 1] == "pace,chain"
        assert cmd[cmd.index("--shadow-prefix") + 1] == "gold/pattern_records/_shadow"

    def test_default_publish_mode_is_dry_run(self):
        assert sub.build_command()[-2:] == ["--publish-mode", "dry-run"]


class TestJobdefPreSubmitContract:
    def _ok(self) -> dict:
        return {
            "image": sub._ECR_IMAGE,
            "jobRoleArn": "arn:aws:iam::668891723125:role/leviathan-dev-pattern-records-job-role",
            "environment": [{"name": "GRAPHRAG_NUMBERS_BACKEND", "value": "pg"},
                            {"name": "GRAPHRAG_ENGINE_VERSION", "value": sub._ECR_IMAGE}],
            "secrets": [{"name": "EVIDENCE_PG_DSN", "valueFrom": "arn:...:evidence-pg-dsn"}],
        }

    def test_conforming_jobdef_has_no_problems(self):
        assert sub.check_jobdef_contract(self._ok()) == []

    def test_dead_quantify_seam_is_caught_before_submit(self):
        props = self._ok()
        props["environment"] = [e for e in props["environment"]
                                if e["name"] != "GRAPHRAG_NUMBERS_BACKEND"]
        problems = sub.check_jobdef_contract(props)
        assert any("GRAPHRAG_NUMBERS_BACKEND" in p for p in problems)

    def test_missing_dsn_secret_is_caught(self):
        props = self._ok()
        props["secrets"] = []
        assert any("EVIDENCE_PG_DSN" in p for p in sub.check_jobdef_contract(props))

    def test_missing_engine_version_collapses_the_write_guard_and_is_caught(self):
        props = self._ok()
        props["environment"] = [e for e in props["environment"]
                                if e["name"] != "GRAPHRAG_ENGINE_VERSION"]
        assert any("GRAPHRAG_ENGINE_VERSION" in p for p in sub.check_jobdef_contract(props))

    def test_shared_serving_role_is_rejected(self):
        props = self._ok()
        props["jobRoleArn"] = "arn:aws:iam::668891723125:role/leviathan-dev-batch-job-role"
        assert any("batch-job-role" in p for p in sub.check_jobdef_contract(props))

    def test_unpinned_image_is_rejected(self):
        props = self._ok()
        props["image"] = "668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-embedder:latest"
        assert any("pinned digest" in p for p in sub.check_jobdef_contract(props))


# ---------------------------------------------------------------------------
# Terraform shape lint (text asserts over the committed HCL).
# ---------------------------------------------------------------------------
class TestJobdefTerraform:
    def test_jobdef_is_count_gated_on_the_pinned_image(self, jobdef):
        assert 'count = var.pattern_records_image != "" ? 1 : 0' in jobdef
        assert "image = var.pattern_records_image" in jobdef

    def test_baked_command_pins_no_asof(self, jobdef):
        cmd = _block(jobdef, "command = [")
        assert "pattern_records_sweep_task.py" in cmd
        assert "--asof" not in cmd
        assert "--publish-mode" in cmd

    def test_pg_seam_and_engine_version_are_wired(self, jobdef):
        assert '{ name = "GRAPHRAG_NUMBERS_BACKEND", value = "pg" }' in jobdef
        assert '{ name = "GRAPHRAG_ENGINE_VERSION", value = var.pattern_records_image }' in jobdef
        assert '{ name = "EVIDENCE_PG_DSN", valueFrom = var.numbers_pg_dsn_secret_arn }' in jobdef

    def test_uses_the_dedicated_role_not_the_shared_one(self, jobdef):
        assert "jobRoleArn = var.pattern_records_job_role_arn" in jobdef
        assert "var.batch_job_role_arn" not in jobdef

    def test_no_retry_strategy_on_a_publishing_job(self, jobdef):
        assert "retry_strategy" not in jobdef


class TestScheduleTerraform:
    def test_schedule_state_matches_the_standing_owner_decision(self, schedule):
        # THIS PIN HAS FLIPPED TWICE, both times on owner word, and it guards WHICHEVER decision
        # stands -- never a direction. History: shipped DISABLED by day-0 doctrine; ARMED 2026-07-25
        # after the reviewed day-0 run (dry-run -> shadow, 543 records reviewed -> canonical ->
        # 156-partition backfill; user-directed, ee78c276) -- the pin then guarded ENABLED so a
        # stray revert could not silently stop the ledger. PAUSED 2026-08-18 (D-LD Q2,
        # owner-ratified, applied live): the writer had fired daily for weeks while
        # GRAPHRAG_PATTERN_RECORDS stayed off serving and the failed gate's vintage floor needs
        # >=20 ESR vintages (months away at weekly cadence) -- daily Batch spend, zero serving
        # return. The pin now guards DISABLED so a stray re-arm cannot silently resume the spend;
        # the ratified re-enable path is the FLAG ARMING + this schedule in one reviewed change
        # when the vintage floor is reachable (the rationale block sits on the resource itself).
        assert 'state = "DISABLED"' in schedule
        assert 'state = "ENABLED"' not in schedule

    def test_schedule_is_count_gated_on_the_digest(self, schedule):
        assert 'count = var.pattern_records_image_digest != "" ? 1 : 0' in schedule

    def test_daily_cron_stays_inside_the_utc_day(self, schedule):
        # a fire after 00:00 UTC would stamp the NEXT day's asof; the expression must be daily.
        assert 'schedule_expression = "cron(0 23 * * ? *)"' in schedule

    def test_explicit_retry_policy_overrides_the_185_platform_default(self, schedule):
        assert "maximum_retry_attempts       = 0" in schedule

    def test_container_override_matches_the_baked_command(self, schedule, jobdef):
        # the override is redundant SAFETY, so it must not diverge from what the jobdef bakes.
        assert 'Command = ["jobs/batch/pattern_records_sweep_task.py", "--publish-mode", "canonical"]' \
            in schedule
        assert '"--publish-mode", "canonical"' in jobdef

    def test_scheduler_role_may_only_submit_this_jobdef(self, dev_tf):
        policy = _block(dev_tf, 'resource "aws_iam_role_policy" "pattern_records_scheduler"')
        assert 'Action = "batch:SubmitJob"' in policy
        assert "pattern_records_sweep_job_definition_name" in policy


class TestIamGrantTerraform:
    def test_writes_are_confined_to_the_ledger_prefix(self, iam_tf):
        doc = _block(iam_tf, 'data "aws_iam_policy_document" "pattern_records_job"')
        rw = _statement(doc, "PatternRecordsLedgerReadWrite")
        assert 'resources = ["${var.bucket_arn}/gold/pattern_records/*"]' in rw
        assert "s3:PutObject" in rw
        # the read-only source statement must NOT grant a write on silver/ or the whole of gold/.
        src = _statement(doc, "ReadSilverAndGoldSources")
        assert "s3:PutObject" not in src

    def test_ledger_is_append_only_deletes_denied(self, iam_tf):
        doc = _block(iam_tf, 'data "aws_iam_policy_document" "pattern_records_job"')
        deny_s3 = _statement(doc, "DenyEveryS3DeleteLedgerIsAppendOnly")
        assert '"Deny"' in deny_s3
        assert "s3:DeleteObject" in deny_s3
        deny_glue = _statement(doc, "DenyGlueTableMutationAndPartitionDeletion")
        assert '"Deny"' in deny_glue
        for action in ("glue:DeleteTable", "glue:DeletePartition", "glue:UpdateTable"):
            assert action in deny_glue

    def test_glue_grant_is_scoped_to_the_one_ledger_table(self, iam_tf):
        doc = _block(iam_tf, 'data "aws_iam_policy_document" "pattern_records_job"')
        glue = _statement(doc, "GlueLedgerPartitionOps")
        assert "local.glue_pattern_records_table_arn" in glue
        assert "local.glue_tables_arn" not in glue  # never the table/<db>/* wildcard
        # exactly the calls the F013 REGISTERED strategy makes.
        for action in ("glue:GetTable", "glue:GetPartition", "glue:CreatePartition",
                       "glue:UpdatePartition"):
            assert action in glue

    def test_role_is_dedicated_and_assumable_by_ecs_tasks(self, iam_tf):
        role = _block(iam_tf, 'resource "aws_iam_role" "pattern_records_job"')
        assert '"${var.project_name}-${var.environment}-pattern-records-job-role"' in role
        assert "ecs-tasks.amazonaws.com" in role

    def test_dsn_secret_grant_lands_on_the_execution_role(self, iam_tf):
        attach = _block(iam_tf,
                        'resource "aws_iam_role_policy_attachment" "batch_execution_role_numbers_pg_dsn"')
        assert "aws_iam_role.batch_execution_role.name" in attach
        assert 'count      = var.numbers_pg_dsn_secret_arn != "" ? 1 : 0' in attach


class TestRootWiring:
    def test_digest_variable_rejects_a_tag(self, ):
        var = _block(_DEV_VARS_TF.read_text(encoding="utf-8"),
                     'variable "pattern_records_image_digest"')
        assert 'default     = ""' in var
        assert "^sha256:[0-9a-f]{64}$" in var

    def test_image_is_assembled_from_the_embedder_repo(self, dev_tf):
        assert "data.aws_ecr_repository.embedder.repository_url}@${var.pattern_records_image_digest}" \
            in dev_tf

    def test_module_batch_receives_the_dedicated_role_and_dsn(self, dev_tf):
        mod = _block(dev_tf, 'module "batch" {')
        assert "pattern_records_job_role_arn = module.iam.pattern_records_job_role_arn" in mod
        assert "numbers_pg_dsn_secret_arn    = data.aws_secretsmanager_secret.pg_dsn.arn" in mod
        assert "publish_signer_kms_key_arn   = aws_kms_key.publish_signer.arn" in mod

    def test_canonical_authority_is_one_revocable_kms_grant(self, dev_tf):
        grant = _block(dev_tf, 'resource "aws_iam_role_policy" "pattern_records_kms_sign"')
        assert 'Action   = ["kms:Sign", "kms:GetPublicKey"]' in grant
        assert "Resource = aws_kms_key.publish_signer.arn" in grant
        assert "role = module.iam.pattern_records_job_role_name" in grant
