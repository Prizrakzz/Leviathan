from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# The [eda] extra backs this suite (nbformat/nbclient/jsonschema/matplotlib/IPython ride the
# EDA image, not the base dev env). A dev env without the extra SKIPS loudly instead of
# breaking collection -- the pdfplumber/[batch] precedent (test_pdfpage.py).
for _mod in ("nbformat", "nbclient", "jsonschema", "matplotlib", "IPython"):
    pytest.importorskip(_mod, reason="[eda] extra not installed")

from jobs.batch.silver_eda_task import (
    build_cli_args,
    campaign_prefix,
    validate_campaign_id,
)
from jobs.submit.submit_batch_silver_eda import (
    HEAVY_WEATHER_RESOURCES,
    MAX_CONCURRENCY,
    PILOT_TABLES,
    STANDARD_RESOURCES,
    ResumeSafetyError,
    build_table_tasks,
    default_job_queue,
    resolve_tables,
    silver_table_names,
    submit_with_bounded_monitoring,
    validate_job_definition,
)
from jobs.utils.register_silver_eda_jobdef import build_payload, resolve_image_digest
from jobs.utils.sync_silver_eda_artifacts import (
    NOTEBOOK_SIZE_LIMIT_BYTES,
    PORTABLE_MANIFEST_SIZE_LIMIT_BYTES,
    build_sync_plan,
    sync_artifacts,
)
from leviathan.silver.registry import APPROVED_BUCKET, load_registry


class FakeBatch:
    def __init__(
        self,
        *,
        concurrency_limit: int = MAX_CONCURRENCY,
        terminal_status_by_table: dict[str, str] | None = None,
        running_polls: int = 0,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.describe_calls: list[list[str]] = []
        self.active: dict[str, str] = {}
        self.concurrency_limit = concurrency_limit
        self.terminal_status_by_table = terminal_status_by_table or {}
        self.running_polls = running_polls
        self.max_active = 0
        self.projected_tables = {"silver_chirps", "silver_nasa_power"}

    def submit_job(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(kwargs)
        job_id = f"job-{len(self.calls)}"
        if kwargs["parameters"]["mode"] == "table":
            table = str(kwargs["parameters"]["table"])
            assert len(self.active) < self.concurrency_limit
            if table in self.projected_tables:
                assert not self.projected_tables.intersection(self.active.values())
            self.active[job_id] = table
            self.max_active = max(self.max_active, len(self.active))
        else:
            # Campaign finalization may only be submitted after all table jobs
            # have reached a terminal state.
            assert not self.active
        return {"jobId": job_id}

    def describe_jobs(self, *, jobs: list[str]) -> dict[str, Any]:
        assert set(jobs) == set(self.active)
        self.describe_calls.append(list(jobs))
        if self.running_polls:
            self.running_polls -= 1
            return {"jobs": [{"jobId": job_id, "status": "RUNNING"} for job_id in jobs]}

        described = []
        for job_id in jobs:
            table = self.active.pop(job_id)
            status = self.terminal_status_by_table.get(table, "SUCCEEDED")
            job: dict[str, Any] = {"jobId": job_id, "status": status}
            if status == "FAILED":
                job.update(
                    {
                        "statusReason": "fixture hard failure",
                        "container": {"exitCode": 1},
                    }
                )
            described.append(job)
        return {"jobs": described}


class FakeS3:
    def __init__(self, *, sizes: dict[str, int] | None = None) -> None:
        self.sizes = sizes or {}
        self.heads: list[str] = []
        self.downloads: list[tuple[str, str, str]] = []

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, int]:
        self.heads.append(Key)
        return {"ContentLength": self.sizes.get(Key, 100)}

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        self.downloads.append((bucket, key, filename))
        Path(filename).write_bytes(key.encode("utf-8"))


def test_batch_entrypoint_forces_campaign_namespace_and_silver_layer() -> None:
    assert campaign_prefix("20260717T120000Z_deadbeef") == (
        "eda/silver/campaign_id=20260717T120000Z_deadbeef"
    )
    args = build_cli_args(
        mode="table",
        table="silver_wasde",
        campaign_id="campaign-1",
        bucket=APPROVED_BUCKET,
        aws_region="us-east-1",
    )
    assert args[0] == "table"
    assert args[args.index("--table") + 1] == "silver_wasde"
    assert args[args.index("--output-prefix") + 1] == "eda/silver/campaign_id=campaign-1"
    assert not any("gold/" in token for token in args)

    replay_args = build_cli_args(
        mode="table",
        table="silver_wasde",
        campaign_id="campaign-2",
        replica_campaign_id="campaign-1",
        bucket=APPROVED_BUCKET,
        aws_region="us-east-1",
    )
    assert replay_args[replay_args.index("--replica-campaign-id") + 1] == "campaign-1"

    with pytest.raises(ValueError, match="layer:silver only"):
        build_cli_args(
            mode="table",
            table="gold_weather_z",
            campaign_id="campaign-1",
            bucket=APPROVED_BUCKET,
            aws_region="us-east-1",
        )
    with pytest.raises(ValueError, match="approved canonical bucket"):
        build_cli_args(
            mode="finalize",
            table=None,
            campaign_id="campaign-1",
            bucket="another-bucket",
            aws_region="us-east-1",
        )


@pytest.mark.parametrize("value", ["../escape", "a/b", "a\\b", "", ".."])
def test_campaign_id_rejects_path_traversal(value: str) -> None:
    with pytest.raises(ValueError):
        validate_campaign_id(value)


def test_registry_selection_is_exactly_42_silvers_and_excludes_gold() -> None:
    registry = load_registry()
    names = silver_table_names(registry)
    assert len(names) == 42
    assert "gold_weather_z" not in names
    assert resolve_tables("all", registry) == names
    with pytest.raises(ValueError, match="layer:silver only"):
        resolve_tables("gold_weather_z", registry)


def test_reader_first_pilot_covers_the_approved_eleven_archetypes() -> None:
    registry = load_registry()
    expected = (
        "silver_chirps",
        "silver_nasa_power",
        "silver_futures_prices",
        "silver_nass_annual",
        "silver_mpob",
        "silver_nass_crop_progress",
        "silver_wasde",
        "silver_esr",
        "silver_esr_compact",
        "silver_mpob_annual",
        "silver_model_predictions",
    )
    assert PILOT_TABLES == expected
    assert tuple(resolve_tables("pilot", registry)) == expected
    assert all(registry.table(name)["layer"] == "silver" for name in expected)


def test_job_definition_is_dedicated_standard_profile_without_athena() -> None:
    payload = build_payload()
    container = payload["containerProperties"]
    assert payload["jobDefinitionName"] == "leviathan-dev-silver-eda"
    assert container["image"].endswith("/leviathan-dev-leviathan-eda:latest")
    assert container["resourceRequirements"] == [
        {"type": "VCPU", "value": "2"},
        {"type": "MEMORY", "value": "8192"},
    ]
    assert "jobs/batch/silver_eda_task.py" in container["command"]
    replica_parameter = container["command"].index("--replica-campaign-id")
    assert container["command"][replica_parameter + 1] == "Ref::replica_campaign_id"
    assert payload["parameters"]["replica_campaign_id"] == "none"
    assert container["jobRoleArn"].endswith("role/leviathan-dev-silver-eda")
    environment = {item["name"]: item["value"] for item in container["environment"]}
    assert environment["LEVIATHAN_EDA_FORBID_ATHENA"] == "1"
    assert not any("athena" in str(token).lower() for token in container["command"])


def test_job_definition_supports_an_immutable_ecr_digest() -> None:
    digest = "sha256:" + ("a" * 64)
    payload = build_payload(image_tag="ignored", image_digest=digest)
    assert payload["containerProperties"]["image"].endswith(
        f"/leviathan-dev-leviathan-eda@{digest}"
    )

    class FakeEcr:
        def describe_images(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs == {
                "repositoryName": "leviathan-dev-leviathan-eda",
                "imageIds": [{"imageTag": "git-sha"}],
            }
            return {"imageDetails": [{"imageDigest": digest}]}

    assert (
        resolve_image_digest(
            ecr_client=FakeEcr(),
            repository_name="leviathan-dev-leviathan-eda",
            image_tag="git-sha",
        )
        == digest
    )


def test_submitter_is_failure_independent_bounded_and_skips_failed_finalizer() -> None:
    registry = load_registry()
    names = [
        "silver_chirps",  # projected weather; fixture makes it fail
        "silver_wasde",  # standard
        "silver_nasa_power",  # projected weather; admitted only after CHIRPS terminates
        "silver_esr_compact",  # standard
        "silver_modis_ndvi",  # heavy weather, registered rather than projected
    ]
    tasks = build_table_tasks(
        registry=registry,
        tables=names,
        campaign_id="campaign-1",
        bucket=APPROVED_BUCKET,
        aws_region="us-east-1",
    )
    client = FakeBatch(terminal_status_by_table={"silver_chirps": "FAILED"})
    records = submit_with_bounded_monitoring(
        tasks=tasks,
        job_queue="queue",
        job_definition="jobdef:7",
        max_concurrency=MAX_CONCURRENCY,
        include_finalize=True,
        batch_client=client,
        poll_interval_seconds=0,
    )

    by_table = {record["table"]: record for record in records if record["mode"] == "table"}
    chirps = by_table["silver_chirps"]
    wasde = by_table["silver_wasde"]
    nasa = by_table["silver_nasa_power"]
    modis = by_table["silver_modis_ndvi"]
    assert chirps["resources"] == HEAVY_WEATHER_RESOURCES
    assert wasde["resources"] == STANDARD_RESOURCES
    assert chirps["status"] == "FAILED"
    assert chirps["exit_code"] == 1
    assert nasa["status"] == "SUCCEEDED"
    assert nasa["submission_order"] > chirps["submission_order"]
    assert modis["resources"] == HEAVY_WEATHER_RESOURCES
    assert not tasks[4]["projected_weather"]
    assert client.max_active == MAX_CONCURRENCY
    assert len(client.calls) == 5
    assert all("dependsOn" not in call for call in client.calls)
    assert all(call["parameters"]["mode"] == "table" for call in client.calls)
    assert not any(record["mode"] == "finalize" for record in records)


def test_submitter_polls_nonterminal_jobs_before_releasing_capacity() -> None:
    registry = load_registry()
    names = ["silver_wasde", "silver_esr_compact", "silver_nass_annual"]
    tasks = build_table_tasks(
        registry=registry,
        tables=names,
        campaign_id="campaign-1",
        bucket=APPROVED_BUCKET,
        aws_region="us-east-1",
    )
    client = FakeBatch(concurrency_limit=2, running_polls=1)
    sleeps: list[float] = []
    records = submit_with_bounded_monitoring(
        tasks=tasks,
        job_queue="queue",
        job_definition="jobdef:7",
        max_concurrency=2,
        batch_client=client,
        poll_interval_seconds=3.5,
        sleep_fn=sleeps.append,
    )

    assert client.max_active == 2
    assert sleeps == [3.5]
    assert [record["status"] for record in records] == [
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
    ]
    # The third table is submitted only after the first monitored pair is terminal.
    assert client.calls[2]["parameters"]["table"] == "silver_nass_annual"


def test_real_submit_requires_revision_and_defaults_to_ondemand_queue() -> None:
    assert default_job_queue("leviathan", "dev") == "leviathan-dev-queue-ondemand"
    assert validate_job_definition("leviathan-dev-silver-eda", dry_run=True) == (
        "leviathan-dev-silver-eda"
    )
    with pytest.raises(ValueError, match="explicit job-definition"):
        validate_job_definition("leviathan-dev-silver-eda", dry_run=False)
    assert (
        validate_job_definition("leviathan-dev-silver-eda:17", dry_run=False)
        == "leviathan-dev-silver-eda:17"
    )
    arn = "arn:aws:batch:us-east-1:123456789012:job-definition/leviathan-dev-silver-eda:17"
    assert validate_job_definition(arn, dry_run=False) == arn


def test_successful_campaign_checkpoints_and_submits_one_finalizer() -> None:
    registry = load_registry()
    tasks = build_table_tasks(
        registry=registry,
        tables=["silver_wasde"],
        campaign_id="campaign-1",
        bucket=APPROVED_BUCKET,
        aws_region="us-east-1",
    )
    client = FakeBatch()
    checkpoints: list[list[dict[str, Any]]] = []

    def checkpoint(records: list[dict[str, Any]]) -> None:
        checkpoints.append([dict(record) for record in records])

    records = submit_with_bounded_monitoring(
        tasks=tasks,
        job_queue="queue",
        job_definition="jobdef:7",
        include_finalize=True,
        batch_client=client,
        poll_interval_seconds=0,
        checkpoint_fn=checkpoint,
    )

    assert [call["parameters"]["mode"] for call in client.calls] == [
        "table",
        "finalize",
    ]
    assert records[-1]["mode"] == "finalize"
    assert records[-1]["status"] == "SUBMITTED"
    assert checkpoints[-1][-1]["job_id"] == records[-1]["job_id"]


def test_resume_monitors_recorded_job_and_submits_only_missing_table() -> None:
    registry = load_registry()
    tasks = build_table_tasks(
        registry=registry,
        tables=["silver_wasde", "silver_esr_compact", "silver_nass_annual"],
        campaign_id="campaign-1",
        bucket=APPROVED_BUCKET,
        aws_region="us-east-1",
    )

    def prior_record(
        task: dict[str, Any], *, job_id: str, status: str, order: int
    ) -> dict[str, Any]:
        return {
            "job_name": f"prior-{task['table']}",
            "job_id": job_id,
            "mode": "table",
            "table": task["table"],
            "profile": task["profile"],
            "resources": STANDARD_RESOURCES,
            "projected_weather": task["projected_weather"],
            "depends_on": [],
            "status": status,
            "submission_order": order,
            "parameters": {
                "mode": "table",
                "table": task["table"],
                "campaign_id": task["campaign_id"],
                "bucket": task["bucket"],
                "aws_region": task["aws_region"],
            },
        }

    prior = [
        prior_record(tasks[0], job_id="job-done", status="SUCCEEDED", order=1),
        prior_record(tasks[1], job_id="job-active", status="RUNNING", order=2),
    ]
    client = FakeBatch(concurrency_limit=2)
    client.active["job-active"] = "silver_esr_compact"
    checkpoints: list[list[dict[str, Any]]] = []
    records = submit_with_bounded_monitoring(
        tasks=tasks,
        job_queue="queue",
        job_definition="jobdef:7",
        max_concurrency=2,
        batch_client=client,
        poll_interval_seconds=0,
        checkpoint_fn=lambda value: checkpoints.append([dict(record) for record in value]),
        resume_records=prior,
    )

    assert len(client.calls) == 1
    assert client.calls[0]["parameters"]["table"] == "silver_nass_annual"
    assert {record["table"] for record in records} == {
        "silver_wasde",
        "silver_esr_compact",
        "silver_nass_annual",
    }
    assert all(record["status"] == "SUCCEEDED" for record in records)
    assert all(record["parameters"]["replica_campaign_id"] == "campaign-1" for record in records)
    assert checkpoints


def test_resume_refuses_ambiguous_record_without_job_id() -> None:
    registry = load_registry()
    tasks = build_table_tasks(
        registry=registry,
        tables=["silver_wasde"],
        campaign_id="campaign-1",
        bucket=APPROVED_BUCKET,
        aws_region="us-east-1",
    )
    ambiguous = {
        "mode": "table",
        "table": "silver_wasde",
        "job_id": None,
        "status": "SUBMITTING",
        "parameters": {
            "mode": "table",
            "table": "silver_wasde",
            "campaign_id": "campaign-1",
            "bucket": APPROVED_BUCKET,
            "aws_region": "us-east-1",
        },
    }
    with pytest.raises(ResumeSafetyError, match="without a Batch job ID"):
        submit_with_bounded_monitoring(
            tasks=tasks,
            job_queue="queue",
            job_definition="jobdef:7",
            batch_client=FakeBatch(),
            poll_interval_seconds=0,
            resume_records=[ambiguous],
        )


def test_resume_rejects_legacy_record_missing_prior_replica_binding() -> None:
    registry = load_registry()
    tasks = build_table_tasks(
        registry=registry,
        tables=["silver_wasde"],
        campaign_id="campaign-2",
        replica_campaign_id="campaign-1",
        bucket=APPROVED_BUCKET,
        aws_region="us-east-1",
    )
    legacy_record = {
        "mode": "table",
        "table": "silver_wasde",
        "job_id": "job-active",
        "status": "RUNNING",
        "parameters": {
            "mode": "table",
            "table": "silver_wasde",
            "campaign_id": "campaign-2",
            "bucket": APPROVED_BUCKET,
            "aws_region": "us-east-1",
        },
    }

    with pytest.raises(ResumeSafetyError, match="parameters do not match"):
        submit_with_bounded_monitoring(
            tasks=tasks,
            job_queue="queue",
            job_definition="jobdef:7",
            batch_client=FakeBatch(),
            poll_interval_seconds=0,
            resume_records=[legacy_record],
        )


def test_submitter_propagates_prior_replica_campaign_to_batch() -> None:
    registry = load_registry()
    tasks = build_table_tasks(
        registry=registry,
        tables=["silver_wasde"],
        campaign_id="campaign-2",
        replica_campaign_id="campaign-1",
        bucket=APPROVED_BUCKET,
        aws_region="us-east-1",
    )
    records = submit_with_bounded_monitoring(
        tasks=tasks,
        job_queue="queue",
        job_definition="jobdef",
        dry_run=True,
    )

    assert tasks[0]["replica_campaign_id"] == "campaign-1"
    assert records[0]["parameters"]["campaign_id"] == "campaign-2"
    assert records[0]["parameters"]["replica_campaign_id"] == "campaign-1"


def test_submitter_dry_run_never_needs_an_aws_client() -> None:
    registry = load_registry()
    tasks = build_table_tasks(
        registry=registry,
        tables=["silver_wasde"],
        campaign_id="campaign-1",
        bucket=APPROVED_BUCKET,
        aws_region="us-east-1",
    )
    records = submit_with_bounded_monitoring(
        tasks=tasks,
        job_queue="queue",
        job_definition="jobdef",
        dry_run=True,
    )
    assert records[0]["job_id"] is None
    assert records[0]["status"] == "PLANNED"
    assert records[0]["parameters"]["table"] == "silver_wasde"
    with pytest.raises(ValueError, match="between 1 and 4"):
        submit_with_bounded_monitoring(
            tasks=tasks,
            job_queue="queue",
            job_definition="jobdef",
            max_concurrency=5,
            dry_run=True,
        )
    with pytest.raises(ValueError, match="non-negative"):
        submit_with_bounded_monitoring(
            tasks=tasks,
            job_queue="queue",
            job_definition="jobdef",
            poll_interval_seconds=-1,
            dry_run=True,
        )


def test_sync_plan_only_contains_allowlisted_portable_artifacts(tmp_path: Path) -> None:
    plan = build_sync_plan(
        campaign_id="campaign-1",
        tables=["silver_wasde"],
        destination=tmp_path / "eda",
        include_root=True,
    )
    assert len(plan) == 9
    assert all(item["key"].startswith("eda/silver/campaign_id=campaign-1/") for item in plan)
    assert all("gold/" not in item["key"] for item in plan)
    assert {Path(item["destination"]).name for item in plan} == {
        "silver_wasde_eda.ipynb",
        "spec.yaml",
        "summary.json",
        "manifest.json",
        "feature_candidates.yaml",
        "00_feature_engineering_readiness.ipynb",
        "feature_candidate_catalog.yaml",
        "campaign_manifest.json",
        "_FINALIZE_WRITE_ONCE",
    }
    marker = next(item for item in plan if Path(item["key"]).name == "_FINALIZE_WRITE_ONCE")
    assert marker["validation_only"] is True


def test_sync_preflights_then_downloads_atomically(tmp_path: Path) -> None:
    destination = tmp_path / "eda"
    plan = build_sync_plan(
        campaign_id="campaign-1",
        tables=["silver_wasde"],
        destination=destination,
        include_root=False,
    )
    client = FakeS3()
    sync_artifacts(
        client=client,
        bucket=APPROVED_BUCKET,
        plan=plan,
        validate_artifacts=False,
    )
    assert len(client.heads) == len(plan)
    assert len(client.downloads) == len(plan)
    assert all(Path(item["destination"]).exists() for item in plan)
    assert not list(destination.rglob("*.eda-sync.tmp"))


def test_sync_rejects_oversized_notebook_before_any_download(tmp_path: Path) -> None:
    plan = build_sync_plan(
        campaign_id="campaign-1",
        tables=["silver_wasde"],
        destination=tmp_path / "eda",
        include_root=False,
    )
    notebook_key = next(item["key"] for item in plan if item["is_notebook"])
    client = FakeS3(sizes={notebook_key: NOTEBOOK_SIZE_LIMIT_BYTES + 1})
    with pytest.raises(ValueError, match="exceeds"):
        sync_artifacts(client=client, bucket=APPROVED_BUCKET, plan=plan)
    assert client.downloads == []


def test_sync_rejects_oversized_portable_manifest_before_download(
    tmp_path: Path,
) -> None:
    plan = build_sync_plan(
        campaign_id="campaign-1",
        tables=["silver_wasde"],
        destination=tmp_path / "eda",
        include_root=False,
    )
    manifest_key = next(
        item["key"]
        for item in plan
        if item.get("table") and Path(item["key"]).name == "manifest.json"
    )
    client = FakeS3(sizes={manifest_key: PORTABLE_MANIFEST_SIZE_LIMIT_BYTES + 1})
    with pytest.raises(ValueError, match="portable manifest exceeds"):
        sync_artifacts(client=client, bucket=APPROVED_BUCKET, plan=plan)
    assert client.downloads == []


def test_eda_image_and_build_script_have_a_verified_role_marker() -> None:
    repo = Path(__file__).resolve().parents[2]
    dockerfile = (repo / "docker" / "leviathan_eda" / "Dockerfile").read_text()
    build_script = (repo / "scripts" / "build_push_eda.ps1").read_text()
    pyproject = (repo / "pyproject.toml").read_text()

    assert "leviathan-eda" in dockerfile
    assert 'pip install --no-cache-dir --no-compile -e ".[eda]"' in dockerfile
    assert "$RepoRoot" in build_script
    assert "describe-repositories" in build_script
    assert "Wrong or stale image content" in build_script
    assert "leviathan.eda-source/v1" in build_script
    assert "leviathan.silver-eda-campaign/v2" in build_script
    assert "PORTABLE_MANIFEST_SIZE_LIMIT_BYTES" in build_script
    assert "apply_semantic_assessment" in build_script
    assert "generate_feature_candidates" in build_script
    assert "from leviathan.eda.reader_charts import" in build_script
    assert "SUPPORTED_CHART_TYPES" in build_script
    assert "compute_chart_payloads" in build_script
    assert "render_chart_payload" in build_script
    assert "chart_scope_record" in build_script
    assert "reader_chart_type_count -ne 21" in build_script
    assert "LEVIATHAN_EDA_SOURCE_SHA=$EdaSourceSha" in build_script
    assert "SourceFingerprintOnly" in build_script
    for source_path in (
        "src\\leviathan\\eda",
        "jobs/batch/silver_eda_task.py",
        "jobs/submit/submit_batch_silver_eda.py",
        "jobs/utils/register_silver_eda_jobdef.py",
        "jobs/utils/sync_silver_eda_artifacts.py",
        "jobs/utils/validate_silver_eda_repository.py",
        "docker/leviathan_eda/Dockerfile",
        "scripts/build_push_eda.ps1",
        ".dockerignore",
        "pyproject.toml",
    ):
        assert source_path in build_script
    assert "ARG LEVIATHAN_EDA_SOURCE_SHA=unknown" in dockerfile
    assert "eda_source_sha256" in dockerfile
    assert "io.leviathan.eda.source-sha256" in dockerfile
    assert "LEVIATHAN_EDA_REQUIRE_BUILD_METADATA=1" in dockerfile
    for dependency in (
        "jupyterlab",
        "papermill",
        "nbclient",
        "nbformat",
        "matplotlib",
        "seaborn",
        "scipy",
        "statsmodels",
    ):
        assert f'"{dependency}' in pyproject


def test_eda_readme_documents_pinned_resume_and_replica_replay() -> None:
    repo = Path(__file__).resolve().parents[2]
    readme = (repo / "eda" / "README.md").read_text()

    assert "leviathan-dev-queue-ondemand" in readme
    assert "--job-definition $EdaJobDefinition --resume" in readme
    assert "--replica-campaign-id $ReplicaCampaign" in readme
    assert "falls back to live Silver" in readme
    assert "Never reuse an immutable prefix after a failed or partial run." not in readme
