"""scripts/ops/repin_jobdef_digest.py -- a repin copies the live revision VERBATIM.

Hermetic: a fake Batch client, no AWS. Every rule the tool carries has a passing case and a
refusing case, because a helper that cannot refuse is a helper that will one day sign for a
descriptor nobody read.

THE INCIDENT THIS EXISTS FOR (C-M2). ``leviathan-dev-esr-bronze-to-silver`` OOM'd at 4 GB on the
10.5M-row all-vintage concat on 2026-09-03 and was bumped to 12,288 MiB (rev 8). It is NOT
terraform-managed, so the repin that carries a new image is a hand ``register-job-definition`` --
and ``jobs/submit/submit_batch_b2s_esr.py`` still hardcodes ``MEMORY: "4096"`` for that exact
jobdef. A descriptor rebuilt from constants silently reverts the envelope; a descriptor COPIED
from the live revision cannot.
"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TOOL = _REPO / "scripts" / "ops" / "repin_jobdef_digest.py"

OLD_DIGEST = "sha256:" + "c5f7900a" * 8
NEW_DIGEST = "sha256:" + "abcdef01" * 8
IMAGE = "668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-worker"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("repin_jobdef_digest", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _live(name="leviathan-dev-esr-bronze-to-silver", revision=8, memory="12288", vcpu="2") -> dict:
    """The shape describe_job_definitions actually returns for the live rev 8 (measured
    2026-09-04: 2 vCPU / 12,288 MiB), including the read-only fields register rejects."""
    return {
        "jobDefinitionName": name,
        "jobDefinitionArn": f"arn:aws:batch:us-east-1:668891723125:job-definition/{name}:{revision}",
        "revision": revision,
        "status": "ACTIVE",
        "type": "container",
        "containerOrchestrationType": "ECS",
        "platformCapabilities": ["FARGATE"],
        "parameters": {"vintage_mode": "all"},
        "containerProperties": {
            "image": f"{IMAGE}@{OLD_DIGEST}",
            "command": ["jobs/batch/bronze_to_silver_esr_task.py"],
            "jobRoleArn": "arn:aws:iam::668891723125:role/leviathan-dev-batch-job-role",
            "executionRoleArn": "arn:aws:iam::668891723125:role/leviathan-dev-batch-execution-role",
            "resourceRequirements": [{"type": "VCPU", "value": vcpu},
                                     {"type": "MEMORY", "value": memory}],
            "environment": [{"name": "LEVIATHAN_BUCKET", "value": "leviathan-dev-shahem-001"}],
            "networkConfiguration": {"assignPublicIp": "ENABLED"},
        },
    }


class FakeBatch:
    """describe/register with the real revision semantics: register bumps the highest ACTIVE."""

    def __init__(self, revisions):
        self.revisions = [copy.deepcopy(r) for r in revisions]
        self.registered: list[dict] = []
        self.mangle = None            # optional: rewrite the payload the way a bad helper would

    def describe_job_definitions(self, jobDefinitionName, status):  # noqa: N803
        return {"jobDefinitions": [copy.deepcopy(r) for r in self.revisions
                                   if r["jobDefinitionName"] == jobDefinitionName
                                   and r["status"] == status]}

    def register_job_definition(self, **payload):
        self.registered.append(copy.deepcopy(payload))
        stored = copy.deepcopy(payload)
        if self.mangle:
            self.mangle(stored)
        top = max((r["revision"] for r in self.revisions
                   if r["jobDefinitionName"] == payload["jobDefinitionName"]), default=0)
        stored.update({"revision": top + 1, "status": "ACTIVE",
                       "containerOrchestrationType": "ECS",
                       "jobDefinitionArn": "arn:aws:batch:us-east-1:668891723125:job-definition/"
                                           f"{payload['jobDefinitionName']}:{top + 1}"})
        self.revisions.append(stored)
        return {"jobDefinitionName": payload["jobDefinitionName"], "revision": top + 1}


class TestPlan:
    def test_only_the_image_moves(self, tool):
        payload, changes = tool.plan_repin(_live(), NEW_DIGEST)
        assert payload["containerProperties"]["image"] == f"{IMAGE}@{NEW_DIGEST}"
        assert changes == [f"containerProperties.image: {OLD_DIGEST} -> {NEW_DIGEST}"]

    def test_the_repository_is_preserved_not_reconstructed(self, tool):
        payload, _ = tool.plan_repin(_live(), NEW_DIGEST)
        assert payload["containerProperties"]["image"].split("@")[0] == IMAGE

    def test_every_other_field_is_copied_verbatim(self, tool):
        live = _live()
        payload, _ = tool.plan_repin(live, NEW_DIGEST)
        for field in ("parameters", "platformCapabilities", "type"):
            assert payload[field] == live[field]
        container = payload["containerProperties"]
        for field in ("command", "jobRoleArn", "executionRoleArn", "environment",
                      "networkConfiguration", "resourceRequirements"):
            assert container[field] == live["containerProperties"][field]

    def test_the_read_only_fields_are_stripped(self, tool):
        payload, _ = tool.plan_repin(_live(), NEW_DIGEST)
        for field in tool.READ_ONLY_FIELDS:
            assert field not in payload, field

    def test_the_memory_bump_survives_the_copy(self, tool):
        """The whole point: 12,288 MiB is not re-authored, it is carried."""
        payload, _ = tool.plan_repin(_live(memory="12288"), NEW_DIGEST)
        assert tool.resource_map(payload) == {"VCPU": "2", "MEMORY": "12288"}

    @pytest.mark.parametrize("bad", ["", "latest", "sha256:deadbeef", "SHA256:" + "a" * 64,
                                     "abc" * 25])
    def test_a_malformed_digest_is_refused(self, tool, bad):
        with pytest.raises(tool.RepinRefusal, match="sha256"):
            tool.plan_repin(_live(), bad)

    def test_a_jobdef_with_no_container_image_is_refused(self, tool):
        live = _live()
        live["containerProperties"].pop("image")
        with pytest.raises(tool.RepinRefusal, match="no containerProperties.image"):
            tool.plan_repin(live, NEW_DIGEST)


class TestEnvelopeAssertion:
    def test_the_expected_envelope_passes(self, tool):
        tool.assert_envelope(_live(), "2", "12288")

    def test_a_reverted_memory_is_refused_by_name(self, tool):
        """The submit_batch_b2s_esr.py failure mode, caught before anything is registered."""
        with pytest.raises(tool.RepinRefusal, match="MEMORY is '4096'"):
            tool.assert_envelope(_live(memory="4096"), "2", "12288")

    def test_a_reverted_vcpu_is_refused(self, tool):
        with pytest.raises(tool.RepinRefusal, match="VCPU is '1'"):
            tool.assert_envelope(_live(vcpu="1"), "2", "12288")

    def test_no_expectation_is_no_assertion(self, tool):
        tool.assert_envelope(_live(memory="4096"), None, None)


class TestRepin:
    def test_dry_run_registers_nothing(self, tool, capsys):
        batch = FakeBatch([_live()])
        out = tool.repin(batch, "leviathan-dev-esr-bronze-to-silver", NEW_DIGEST,
                         expect_vcpu="2", expect_memory="12288")
        assert batch.registered == []
        assert out["applied"] is False
        assert "DRY RUN" in capsys.readouterr().out

    def test_apply_registers_one_new_revision_and_reads_it_back(self, tool, capsys):
        batch = FakeBatch([_live(revision=8)])
        out = tool.repin(batch, "leviathan-dev-esr-bronze-to-silver", NEW_DIGEST,
                         expect_vcpu="2", expect_memory="12288", apply=True)
        assert len(batch.registered) == 1
        assert out["new_revision"] == 9 and out["live_revision"] == 8
        assert out["resources"] == {"VCPU": "2", "MEMORY": "12288"}
        assert "NEW REVISION       : 9" in capsys.readouterr().out

    def test_it_copies_the_HIGHEST_active_revision(self, tool):
        batch = FakeBatch([_live(revision=6), _live(revision=8)])
        out = tool.repin(batch, "leviathan-dev-esr-bronze-to-silver", NEW_DIGEST, apply=True)
        assert out["live_revision"] == 8 and out["new_revision"] == 9

    def test_a_post_registration_envelope_drift_is_refused(self, tool):
        """A repin is only real when the NEW REVISION is read back from AWS -- the estate's
        digest-pinned-jobdef law. If what came back is not what was sent, the tool refuses to
        confirm rather than printing a success line."""
        batch = FakeBatch([_live()])

        def shrink(stored):
            stored["containerProperties"]["resourceRequirements"] = [
                {"type": "VCPU", "value": "2"}, {"type": "MEMORY", "value": "4096"}]

        batch.mangle = shrink
        with pytest.raises(tool.RepinRefusal, match="REFUSING TO CONFIRM"):
            tool.repin(batch, "leviathan-dev-esr-bronze-to-silver", NEW_DIGEST, apply=True)

    def test_no_active_revision_is_refused(self, tool):
        with pytest.raises(tool.RepinRefusal, match="no ACTIVE revision"):
            tool.repin(FakeBatch([]), "leviathan-dev-esr-bronze-to-silver", NEW_DIGEST)


def test_the_module_never_authors_resource_requirements():
    """A source-level pin on the ABSENCE that makes this tool safe: no hardcoded MiB anywhere.
    The only memory numbers in the file are in prose (the measured live envelopes) and in the
    --expect-* flags the operator supplies."""
    src = _TOOL.read_text(encoding="utf-8")
    assert '"type": "MEMORY"' not in src
    assert '"type": "VCPU"' not in src
    assert "resourceRequirements" in src, "it must still READ them to assert they are preserved"
