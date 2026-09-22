"""P7 -- the freshness poller's JOBDEF registrar refuses to register a descriptor that cannot run.

WHAT THIS DECK EXISTS FOR (2026-09-22 pipeline census, P7).

``jobs/utils/register_freshness_poller_jobdef.py`` has never been run against the account:
``aws batch describe-job-definitions --job-definition-name leviathan-dev-freshness-poller``
returns ``jobDefinitions: []``. What actually runs the poller is the ENABLED EventBridge schedule
``leviathan-dev-freshness-poller``, which submits to ``leviathan-dev-raw-ingest-runner`` with a
``ContainerOverrides.Command`` naming the module. That is fortunate, because the registrar as
written would have produced a jobdef that cannot run at all:

  * ``jobRoleArn`` names ``leviathan-dev-freshness-poller-job-role``, which this account does not
    have (``aws iam get-role`` -> NoSuchEntity, measured 2026-09-22). A jobdef whose job role
    cannot be assumed fails at RUNTIME, inside a scheduled fire, with no plan-time signal at all.
  * ``image`` is the FLOATING ``:latest`` tag, in an estate whose standing law is that every jobdef
    is digest-pinned ("a digest-pinned jobdef makes a push a NO-OP" exists precisely because the
    pin is the record of what ran).

A paragraph in a docstring asking the next operator to remember both of those is not a fix; it is
the shape of every silent drift this estate has paid for. So the registrar REFUSES, at the moment
of the call, with the reason printed and a non-zero exit -- and it refuses on HEAD today, which is
what makes this a pin rather than a decoration.

ONE DECK, no AWS: ``preflight`` takes its IAM client by injection.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_MOD = _REPO / "jobs" / "utils" / "register_freshness_poller_jobdef.py"

_DIGEST = ("668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-worker"
           "@sha256:46f55987bbfa6ea2f6128b31fdbc46edea6f98b98e08e70cc9df82935d027f89")


@pytest.fixture(scope="module")
def reg():
    spec = importlib.util.spec_from_file_location("register_freshness_poller_jobdef", _MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _IamWithRole:
    def get_role(self, RoleName):  # noqa: N803 - boto3 kwarg casing
        return {"Role": {"RoleName": RoleName}}


class _IamWithoutRole:
    def get_role(self, RoleName):  # noqa: N803 - boto3 kwarg casing
        raise RuntimeError(f"NoSuchEntity: {RoleName}")


class TestPreflightRefusesTheShippedDescriptor:
    def test_head_descriptor_is_refused_for_its_floating_tag(self, reg):
        problems = reg.preflight(reg._CONTAINER, iam=None)
        assert any("DIGEST-PINNED" in p for p in problems), problems

    def test_head_descriptor_is_refused_for_a_role_that_does_not_exist(self, reg):
        problems = reg.preflight(reg._CONTAINER, iam=_IamWithoutRole())
        assert any("does not have" in p for p in problems), problems

    def test_both_reasons_are_reported_together_not_one_at_a_time(self, reg):
        # The estate's own ruling on the resolver gate: a check added one at a time costs a round
        # per defect. Every unmet precondition is listed in ONE refusal.
        assert len(reg.preflight(reg._CONTAINER, iam=_IamWithoutRole())) == 2

    def test_a_digest_pinned_descriptor_with_a_real_role_passes(self, reg):
        container = dict(reg._CONTAINER, image=_DIGEST)
        assert reg.preflight(container, iam=_IamWithRole()) == []

    def test_the_floating_tag_can_be_signed_for_deliberately(self, reg):
        # A refusal that cannot be overridden on purpose becomes a reason to edit the checker.
        assert reg.preflight(reg._CONTAINER, iam=_IamWithRole(),
                             allow_floating_tag=True) == []


class TestRegistrarCli:
    def test_dry_run_prints_the_refusals_and_registers_nothing(self, reg, capsys, monkeypatch):
        monkeypatch.setattr(reg, "boto3", None)      # any AWS call would raise
        assert reg.main(["--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "[preflight] REFUSE" in out
        assert "DIGEST-PINNED" in out

    def test_image_digest_swaps_only_the_reference_never_the_repository(self, reg, capsys,
                                                                        monkeypatch):
        # The standing jobdef law: a repin KEEPS the repository. A worker digest on the embedder
        # repo dies at STARTING with CannotPullContainerError.
        monkeypatch.setattr(reg, "boto3", None)
        digest = "sha256:" + "a" * 64
        assert reg.main(["--dry-run", "--image-digest", digest]) == 0
        out = capsys.readouterr().out
        assert f"leviathan-dev-leviathan-embedder@{digest}" in out
        assert ":latest" not in out

    def test_a_refused_run_exits_non_zero_and_never_calls_register(self, reg, monkeypatch):
        called = []

        class _Batch:
            def register_job_definition(self, **kw):
                called.append(kw)
                raise AssertionError("register_job_definition must not be reached")

        class _Boto:
            def client(self, service, **_kw):
                return _IamWithoutRole() if service == "iam" else _Batch()

        monkeypatch.setattr(reg, "boto3", _Boto())
        assert reg.main([]) == 2
        assert called == []
