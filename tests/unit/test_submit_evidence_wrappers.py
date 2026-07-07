"""Unit tests for the P2 W0.4 evidence-maintenance Batch submit wrappers.

These cover the PURE command-builders + the live-prefix refusal guard — the load-bearing logic — without any
real boto3 traffic. The submit-loop itself is the shared, already-tested batch_submit path; what's new here
is (a) the exactly-one-mode flag mapping into the evidence_batch CLI, (b) the `--table` / EVIDENCE_S3
forwarding for the pg loader, and (c) the guard that refuses a `--rebuild-slices` against the LIVE prefix
(a live rebuild clobbers all 24 commodity slices).

Sibling submit wrappers (submit_eval, submit_batch_load_numbers_pg) ship no dedicated unit — mirroring the
donor here means testing the builder functions, as test_batch_submit.py does for submit_batch_train.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# jobs/ is not an importable package (pytest pythonpath = ["src"] only, no jobs/__init__.py — the sibling
# submit tests shell out via subprocess for the same reason). We want the PURE builders in-process, so load
# each wrapper by file path; their top-level `leviathan.*` imports resolve via src/ already on sys.path.
_SUBMIT_DIR = Path(__file__).resolve().parents[2] / "jobs" / "submit"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SUBMIT_DIR / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


maint = _load("submit_batch_evidence_maintenance")
pgload = _load("submit_batch_load_pg_evidence")


# ---------------------------------------------------------------------------
# submit_batch_evidence_maintenance.build_command
# ---------------------------------------------------------------------------

class TestMaintenanceBuildCommand:
    def test_rebuild_slices_command_has_no_nodes(self) -> None:
        cmd = maint.build_command(mode="rebuild-slices")

        assert cmd == ["-m", "leviathan.graphrag.evidence_batch", "--rebuild-slices"]

    def test_rebuild_slices_ignores_nodes(self) -> None:
        # rebuild routes the WHOLE chunks/ cache — --nodes is meaningless and must never be forwarded.
        cmd = maint.build_command(mode="rebuild-slices", nodes="corn,soybeans")

        assert "--nodes" not in cmd

    def test_reroute_default_has_no_nodes(self) -> None:
        cmd = maint.build_command(mode="reroute")

        assert cmd == ["-m", "leviathan.graphrag.evidence_batch", "--reroute"]

    def test_reroute_forwards_nodes(self) -> None:
        cmd = maint.build_command(mode="reroute", nodes="corn,soybeans")

        assert cmd == ["-m", "leviathan.graphrag.evidence_batch", "--reroute",
                       "--nodes", "corn,soybeans"]

    def test_unknown_mode_rejected(self) -> None:
        # Guards against a billed mode (--submit/--run/--fill) sneaking through the "maintenance" verb.
        with pytest.raises(ValueError):
            maint.build_command(mode="submit")


# ---------------------------------------------------------------------------
# submit_batch_evidence_maintenance — live-prefix refusal
# ---------------------------------------------------------------------------

_LIVE = "s3://leviathan-dev-shahem-001/graphrag_evidence"
_SHADOW = "s3://leviathan-dev-shahem-001/graphrag_evidence/shadow_e1b"


def _jobdef_resp(evidence_s3: str | None, *, revision: int = 6) -> dict:
    """A describe_job_definitions payload with one ACTIVE revision baking `evidence_s3` (or no EVIDENCE_S3)."""
    env = [{"name": "AWS_REGION", "value": "us-east-1"}]
    if evidence_s3 is not None:
        env.append({"name": "EVIDENCE_S3", "value": evidence_s3})
    return {"jobDefinitions": [{"revision": revision, "containerProperties": {"environment": env}}]}


class TestLivePrefixRefusal:
    def test_shadow_prefix_is_allowed(self) -> None:
        client = MagicMock()
        client.describe_job_definitions.return_value = _jobdef_resp(_LIVE)
        with patch.object(maint, "boto3") as b:
            b.client.return_value = client
            # No raise = allowed.
            maint.assert_not_live_rebuild(evidence_s3=_SHADOW, job_definition="jd",
                                          aws_region="us-east-1", override=False)

    def test_live_prefix_is_refused(self) -> None:
        client = MagicMock()
        client.describe_job_definitions.return_value = _jobdef_resp(_LIVE)
        with patch.object(maint, "boto3") as b:
            b.client.return_value = client
            with pytest.raises(SystemExit, match="LIVE prefix"):
                maint.assert_not_live_rebuild(evidence_s3=_LIVE, job_definition="jd",
                                              aws_region="us-east-1", override=False)

    def test_live_prefix_trailing_slash_still_refused(self) -> None:
        # The live jobdef bakes it WITHOUT a slash; a caller passing the slashed form must still be caught.
        client = MagicMock()
        client.describe_job_definitions.return_value = _jobdef_resp(_LIVE)
        with patch.object(maint, "boto3") as b:
            b.client.return_value = client
            with pytest.raises(SystemExit, match="LIVE prefix"):
                maint.assert_not_live_rebuild(evidence_s3=_LIVE + "/", job_definition="jd",
                                              aws_region="us-east-1", override=False)

    def test_unreadable_live_value_refuses_by_default(self) -> None:
        # A missing EVIDENCE_S3 in the jobdef must NOT silently disable the guard.
        client = MagicMock()
        client.describe_job_definitions.return_value = _jobdef_resp(None)
        with patch.object(maint, "boto3") as b:
            b.client.return_value = client
            with pytest.raises(SystemExit, match="could not read"):
                maint.assert_not_live_rebuild(evidence_s3=_SHADOW, job_definition="jd",
                                              aws_region="us-east-1", override=False)

    def test_override_skips_check_and_describe(self) -> None:
        # The escape hatch must not even hit boto3 (so it works where describe isn't reachable).
        with patch.object(maint, "boto3") as b:
            maint.assert_not_live_rebuild(evidence_s3=_LIVE, job_definition="jd",
                                          aws_region="us-east-1", override=True)
        b.client.assert_not_called()

    def test_live_prefix_reads_latest_revision(self) -> None:
        client = MagicMock()
        # Two ACTIVE revisions out of order — the guard must key on the LATEST (rev 7 shadow-ified? no: latest wins).
        client.describe_job_definitions.return_value = {"jobDefinitions": [
            {"revision": 5, "containerProperties": {"environment": [{"name": "EVIDENCE_S3", "value": "s3://old/prefix"}]}},
            {"revision": 7, "containerProperties": {"environment": [{"name": "EVIDENCE_S3", "value": _LIVE}]}},
        ]}
        with patch.object(maint, "boto3") as b:
            b.client.return_value = client
            assert maint.live_prefix_from_jobdef("jd", "us-east-1") == _LIVE


# ---------------------------------------------------------------------------
# submit_batch_load_pg_evidence.build_command
# ---------------------------------------------------------------------------

class TestPgLoadBuildCommand:
    def test_all_no_table_matches_bare_loader(self) -> None:
        # Default behaviour must be byte-identical to a laptop `load_pg_evidence.py --all`.
        cmd = pgload.build_command(nodes=None, load_all=True, table=None)

        assert cmd == ["jobs/utils/load_pg_evidence.py", "--all"]

    def test_nodes_forwarded_as_separate_args(self) -> None:
        cmd = pgload.build_command(nodes=["corn", "soybeans", "drivers/el_nino"],
                                   load_all=False, table=None)

        assert cmd == ["jobs/utils/load_pg_evidence.py", "--nodes",
                       "corn", "soybeans", "drivers/el_nino"]

    def test_table_forwarded_when_set(self) -> None:
        cmd = pgload.build_command(nodes=None, load_all=True, table="evidence_props_shadow")

        assert cmd[-2:] == ["--table", "evidence_props_shadow"]

    def test_workers_forwarded_when_set(self) -> None:
        cmd = pgload.build_command(nodes=None, load_all=True, table=None, workers=4)

        assert cmd[-2:] == ["--workers", "4"]

    def test_all_wins_when_both_selected(self) -> None:
        # Defensive: --all/--nodes are mutually exclusive at the CLI, but the builder must prefer --all cleanly.
        cmd = pgload.build_command(nodes=["corn"], load_all=True, table=None)

        assert "--all" in cmd and "--nodes" not in cmd
