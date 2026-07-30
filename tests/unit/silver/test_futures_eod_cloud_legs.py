"""PRICE_AND_PLAYBOOKS W1a + W2 CLOUD LEGS: a terraform shape lint over the three futures_eod
Batch job definitions, cross-checked against the two DAG descriptors that reference them.

These are the checks that fail LOUDLY at author time instead of quietly at 22:30 UTC on the first
armed cron. The failure modes they pin are all ones this repo has already paid for:

  * cross-artifact NAME render: each descriptor's jobdef pin must equal the name terraform renders.
    A wrong name dies at SubmitJob with ClientException (the BF-W2 D1 lesson) -- and because
    gen_sfn_inputs._unversion strips the descriptors' ":1", the NAME is the whole contract.
  * the image must be DIGEST-pinned, never a tag: `databento` ([batch] extra) and `xlrd` (core)
    are the two deps whose absence is SILENT at ingest -- yfinance was missing from [batch] for
    six weeks and every run wrote nothing under no freshness alarm.
  * the four free legs must carry NO secrets (all four venues are unauthenticated public GETs);
    the Databento leg must carry exactly one, mounted valueFrom under the EXECUTION role.
  * the silver jobdef must run as the SILVER-F014 publisher, because silver_futures_eod is
    class-A REGISTERED and glue:CreatePartition lives only on that role -- and its baked command
    must be --publish-mode shadow, so an un-overridden fire cannot touch canonical.
  * every one of the three must be count-gated, so an unpinned/unprovisioned lane is a terraform
    no-op rather than a jobdef that fails at container START.

AWS-free + terraform-free: the tf checks are text-shape asserts over the committed HCL (the repo
has no HCL parser dependency, and `terraform validate` is the author-time gate), read through a
brace-matching block extractor that also proves the blocks are balanced. Same construction as
tests/unit/test_pattern_records_cloud_legs.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_TF = _REPO / "infra" / "terraform"
_BATCH_TF = _TF / "modules" / "batch" / "main.tf"
_BATCH_VARS_TF = _TF / "modules" / "batch" / "variables.tf"
_BATCH_OUT_TF = _TF / "modules" / "batch" / "outputs.tf"
_IAM_TF = _TF / "modules" / "iam" / "main.tf"
_DEV_TF = _TF / "envs" / "dev" / "main.tf"
_DEV_VARS_TF = _TF / "envs" / "dev" / "variables.tf"
_DAGS = _REPO / "configs" / "silver" / "dags"

# terraform renders every name from these two root variables (envs/dev/variables.tf defaults).
_PROJECT, _ENV = "leviathan", "dev"


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
    """Return the `statement { ... }` block carrying `sid = "<sid_value>"`."""
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


def _unversion(jobdef: str) -> str:
    """gen_sfn_inputs._unversion: strip a trailing ':N' so the schedule tracks the latest ACTIVE
    revision. Reimplemented here so the test does not depend on scripts/ import mechanics."""
    head, sep, tail = jobdef.rpartition(":")
    return head if (sep and tail.isdigit()) else jobdef


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
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
def free_desc() -> dict:
    return json.loads((_DAGS / "futures_eod_free.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def databento_desc() -> dict:
    return json.loads((_DAGS / "futures_eod_databento.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def free_fetch(batch_tf) -> str:
    return _block(batch_tf, 'resource "aws_batch_job_definition" "futures_eod_free_fetch"')


@pytest.fixture(scope="module")
def databento_fetch(batch_tf) -> str:
    return _block(batch_tf, 'resource "aws_batch_job_definition" "databento_fetch"')


@pytest.fixture(scope="module")
def silver(batch_tf) -> str:
    return _block(batch_tf, 'resource "aws_batch_job_definition" "futures_eod_silver"')


def _tasks(desc: dict, phase: str) -> list[dict]:
    for ph in desc["phases"]:
        if ph["name"] == phase:
            return ph["tasks"]
    raise AssertionError(f"descriptor has no {phase!r} phase")


# ---------------------------------------------------------------------------
# The cross-artifact render check: descriptor pin == the name terraform renders.
# ---------------------------------------------------------------------------
class TestNamesMatchTheDescriptors:
    def test_free_fetch_name(self, free_fetch, free_desc):
        declared = 'name = "${var.project_name}-${var.environment}-futures-eod-free-fetch"'
        assert declared in free_fetch
        rendered = _render(declared).split('"')[1]
        assert rendered == "leviathan-dev-futures-eod-free-fetch"
        pins = {_unversion(t["jobdef"]) for t in _tasks(free_desc, "fetch")}
        assert pins == {rendered}, "all four free legs share ONE fetch jobdef"

    def test_databento_fetch_name(self, databento_fetch, databento_desc):
        declared = 'name = "${var.project_name}-${var.environment}-databento-fetch"'
        assert declared in databento_fetch
        rendered = _render(declared).split('"')[1]
        assert rendered == "leviathan-dev-databento-fetch"
        pins = {_unversion(t["jobdef"]) for t in _tasks(databento_desc, "fetch")}
        assert pins == {rendered}

    def test_silver_name_is_shared_by_both_chains(self, silver, free_desc, databento_desc):
        declared = 'name = "${var.project_name}-${var.environment}-futures-eod-silver"'
        assert declared in silver
        rendered = _render(declared).split('"')[1]
        assert rendered == "leviathan-dev-futures-eod-silver"
        pins = {_unversion(t["jobdef"]) for t in _tasks(free_desc, "silver")}
        pins |= {_unversion(t["jobdef"]) for t in _tasks(databento_desc, "silver")}
        assert pins == {rendered}, "ONE table, ONE contract, ONE silver jobdef"

    def test_the_module_exports_those_names_for_the_tfvars_author(self):
        out = _BATCH_OUT_TF.read_text(encoding="utf-8")
        for stem in ("futures_eod_free_fetch", "databento_fetch", "futures_eod_silver"):
            assert f'output "{stem}_job_definition_name"' in out
            assert f'output "{stem}_job_definition_arn"' in out

    def test_every_baked_command_points_at_a_file_that_exists(self, free_fetch, databento_fetch,
                                                              silver):
        for jobdef in (free_fetch, databento_fetch, silver):
            cmd = _block(jobdef, "command = [")
            script = re.search(r'"(jobs/[^"]+\.py)"', cmd).group(1)
            assert (_REPO / script).exists(), f"baked command names a missing script: {script}"

    def test_every_descriptor_command_points_at_a_file_that_exists(self, free_desc,
                                                                   databento_desc):
        for desc in (free_desc, databento_desc):
            for phase in ("fetch", "silver"):
                for t in _tasks(desc, phase):
                    assert (_REPO / t["command"][0]).exists()


# ---------------------------------------------------------------------------
# The image pin -- the SILENT-missing-dependency guard.
# ---------------------------------------------------------------------------
class TestImageIsDigestPinned:
    def test_all_three_run_the_digest_pinned_local_never_a_tag(self, free_fetch, databento_fetch,
                                                               silver):
        for jobdef in (free_fetch, databento_fetch, silver):
            assert "image = local.futures_eod_image" in jobdef
            assert ":latest" not in jobdef

    def test_the_local_is_repo_at_digest(self, batch_tf):
        loc = _block(batch_tf, "locals {")
        assert '"${var.ecr_repository_url}@${var.futures_eod_image_digest}"' in loc

    def test_module_variable_refuses_a_tag(self):
        var = _block(_BATCH_VARS_TF.read_text(encoding="utf-8"),
                     'variable "futures_eod_image_digest"')
        assert 'regex("^sha256:[0-9a-f]{64}$", var.futures_eod_image_digest)' in var

    def test_root_default_is_a_full_digest(self):
        var = _block(_DEV_VARS_TF.read_text(encoding="utf-8"),
                     'variable "futures_eod_image_digest"')
        default = re.search(r'default\s+=\s+"([^"]*)"', var).group(1)
        # empty is a legitimate gate-off; anything else must be a full digest.
        assert default == "" or re.fullmatch(r"sha256:[0-9a-f]{64}", default), default
        assert 'regex("^sha256:[0-9a-f]{64}$"' in var


# ---------------------------------------------------------------------------
# Count gates: an unpinned / unprovisioned lane is a NO-OP, not a broken jobdef.
# ---------------------------------------------------------------------------
class TestCountGates:
    def test_free_fetch_gated_on_the_image(self, free_fetch):
        assert 'count = local.futures_eod_image != "" ? 1 : 0' in free_fetch

    def test_databento_fetch_gated_on_image_and_secret(self, databento_fetch):
        assert ('count = local.futures_eod_image != "" && '
                'var.databento_api_key_secret_arn != "" ? 1 : 0') in databento_fetch

    def test_silver_gated_on_image_and_publisher_role(self, silver):
        assert ('count = local.futures_eod_image != "" && '
                'var.silver_publisher_job_role_arn != "" ? 1 : 0') in silver


# ---------------------------------------------------------------------------
# Roles + secrets.
# ---------------------------------------------------------------------------
class TestFreeFetchJobdef:
    def test_no_secrets_block_at_all(self, free_fetch, free_desc):
        # the descriptor states it: every one of the four venues is a public GET.
        assert "secrets" not in free_fetch
        assert "NO SECRETS" in free_desc["notes"]

    def test_raw_landing_role_not_the_publisher(self, free_fetch):
        assert "jobRoleArn       = var.batch_job_role_arn" in free_fetch
        assert "silver_publisher_job_role_arn" not in free_fetch

    def test_sizing(self, free_fetch):
        assert '{ type = "VCPU", value = "1" }' in free_fetch
        assert '{ type = "MEMORY", value = "2048" }' in free_fetch

    def test_no_kms_env_on_a_non_publishing_job(self, free_fetch):
        assert "LEVIATHAN_APPROVAL_MODE" not in free_fetch
        assert "LEVIATHAN_KMS_KEY_ID" not in free_fetch


class TestDatabentoFetchJobdef:
    def test_key_is_mounted_valuefrom_never_a_plaintext_env(self, databento_fetch):
        assert ('{ name = "DATABENTO_API_KEY", '
                'valueFrom = var.databento_api_key_secret_arn }') in databento_fetch
        env = _block(databento_fetch, "environment = [")
        assert "DATABENTO_API_KEY" not in env

    def test_mode_is_baked_because_the_parser_requires_it(self, databento_fetch):
        cmd = _block(databento_fetch, "command = [")
        assert '"--mode", "incremental"' in cmd

    def test_raw_landing_role(self, databento_fetch):
        assert "jobRoleArn       = var.batch_job_role_arn" in databento_fetch

    def test_execution_role_carries_the_getsecretvalue_grant(self, iam_tf):
        doc = _block(iam_tf, 'data "aws_iam_policy_document" "batch_execution_databento_secret"')
        stmt = _statement(doc, "ReadDatabentoApiKeySecret")
        assert 'actions   = ["secretsmanager:GetSecretValue"]' in stmt
        # scoped to the one secret; the trailing -* matches the SM random suffix.
        assert 'resources = ["${var.databento_api_key_secret_arn}-*"]' in stmt
        attach = _block(iam_tf,
                        'resource "aws_iam_role_policy_attachment" '
                        '"batch_execution_role_databento_secret"')
        assert "aws_iam_role.batch_execution_role.name" in attach
        assert "batch_job_role" not in attach


class TestSilverJobdef:
    def test_runs_as_the_gated_publisher_not_the_shared_role(self, silver):
        assert "jobRoleArn = var.silver_publisher_job_role_arn" in silver
        assert "var.batch_job_role_arn" not in silver

    def test_baked_command_is_shadow_never_canonical(self, silver):
        cmd = _block(silver, "command = [")
        assert '"--publish-mode", "shadow"' in cmd
        assert "canonical" not in cmd

    def test_kms_pair_is_wired_for_a_manual_promote(self, silver):
        assert '{ name = "LEVIATHAN_APPROVAL_MODE", value = "kms" }' in silver
        assert '{ name = "LEVIATHAN_KMS_KEY_ID", value = local.publish_signer_alias }' in silver

    def test_the_alias_is_the_one_every_armed_promote_task_already_sends(self, batch_tf):
        loc = _block(batch_tf, "locals {")
        declared = 'publish_signer_alias = "alias/${var.project_name}-${var.environment}-publish-signer"'
        assert declared in loc
        assert _render(declared).split('"')[1] == "alias/leviathan-dev-publish-signer"

    def test_sizing(self, silver):
        assert '{ type = "VCPU", value = "1" }' in silver
        assert '{ type = "MEMORY", value = "4096" }' in silver

    def test_no_retry_strategy_on_a_publishing_job(self, silver):
        assert "retry_strategy" not in silver


# ---------------------------------------------------------------------------
# envs/dev wiring.
# ---------------------------------------------------------------------------
class TestDevWiring:
    def test_module_batch_receives_all_three_inputs(self, dev_tf):
        mod = _block(dev_tf, 'module "batch" {')
        assert "futures_eod_image_digest = var.futures_eod_image_digest" in mod
        assert "silver_publisher_job_role_arn = module.iam.silver_publisher_role_arn" in mod
        assert "databento_api_key_secret_arn  = local.databento_api_key_secret_arn" in mod

    def test_module_iam_receives_the_databento_secret_arn(self, dev_tf):
        mod = _block(dev_tf, 'module "iam" {')
        assert "databento_api_key_secret_arn = local.databento_api_key_secret_arn" in mod

    def test_secret_arn_is_constructed_not_looked_up(self, dev_tf):
        # a data source on an absent, user-gated secret fails at PLAN time and would block
        # every unrelated apply -- the fas_api_key_secret_arn precedent.
        loc = _block(dev_tf, "locals {")
        assert "secret:leviathan/dev/databento-api-key" in loc
        assert 'data "aws_secretsmanager_secret" "databento' not in dev_tf


# ---------------------------------------------------------------------------
# The arming contract these jobdefs sit under (descriptor-side, checked here so the
# terraform author cannot arm anything by accident).
# ---------------------------------------------------------------------------
class TestArmingContract:
    def test_both_chains_are_armed_and_still_publish_shadow_first(self, free_desc, databento_desc):
        """ARMED 2026-07-29, after the interlock in silver_alarms.PRE_PUBLISH_FAMILIES ran its full
        course (legs -> backfills -> hand-promoted canonical -> union gates PASS -> this flip).

        Autonomous does NOT mean a silver task writes canonical. It means the PROMOTE phase is
        populated, and promote runs only behind the gate; the silver phase still stages SHADOW.
        That distinction IS the shadow-first architecture, so it is asserted rather than assumed --
        a change that makes any silver task write canonical directly fails here."""
        for desc in (free_desc, databento_desc):
            assert desc["promote_mode"] == "autonomous"
            assert desc["auth_mode"] == "kms"
            assert desc["publish_class"] == "A (registered)"

    def test_the_two_chains_keep_separate_rolling_baselines(self, free_desc, databento_desc):
        a, b = free_desc["gate_baseline_uri"], databento_desc["gate_baseline_uri"]
        assert a != b
        # the SUPERSEDED family-level seed must never be consulted by either.
        assert not a.endswith("rolling/futures_eod/census.json")
        assert not b.endswith("rolling/futures_eod/census.json")

    def test_crons_avoid_the_yfinance_23_00_slot(self, free_desc, databento_desc):
        for desc in (free_desc, databento_desc):
            assert "cron(0 23 " not in desc["cron"]
