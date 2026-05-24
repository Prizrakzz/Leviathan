"""Unit tests for leviathan.common.batch_submit."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from leviathan.common.batch_submit import submit_batch_jobs, write_run_record

_TASKS: list[dict[str, str]] = [
    {"year": "2023", "commodity": "cocoa"},
    {"year": "2024", "commodity": "corn_cbot"},
]


# ---------------------------------------------------------------------------
# submit_batch_jobs
# ---------------------------------------------------------------------------

class TestSubmitBatchJobs:
    def test_dry_run_returns_all_tasks_without_boto3_call(self) -> None:
        with patch("leviathan.common.batch_submit.boto3") as mock_boto3:
            mock_client = MagicMock()
            mock_boto3.client.return_value = mock_client
            result = submit_batch_jobs(
                tasks=_TASKS,
                job_queue="test-queue",
                job_definition="test-def",
                build_job_name=lambda t: f"job-{t['commodity']}-{t['year']}",
                aws_region="us-east-1",
                dry_run=True,
            )

        mock_client.submit_job.assert_not_called()
        assert len(result) == 2
        assert result[0]["job_name"] == "job-cocoa-2023"
        assert result[0]["job_id"] is None
        assert result[1]["job_name"] == "job-corn_cbot-2024"
        assert result[1]["job_id"] is None

    def test_submit_calls_batch_and_returns_job_ids(self) -> None:
        mock_client = MagicMock()
        mock_client.submit_job.side_effect = [
            {"jobId": "aaaa-1111"},
            {"jobId": "bbbb-2222"},
        ]

        with patch("leviathan.common.batch_submit.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            result = submit_batch_jobs(
                tasks=_TASKS,
                job_queue="test-queue",
                job_definition="test-def",
                build_job_name=lambda t: f"job-{t['commodity']}-{t['year']}",
                aws_region="us-east-1",
                dry_run=False,
            )

        assert mock_client.submit_job.call_count == 2
        first_call_kwargs = mock_client.submit_job.call_args_list[0].kwargs
        assert first_call_kwargs["jobName"] == "job-cocoa-2023"
        assert first_call_kwargs["jobQueue"] == "test-queue"
        assert first_call_kwargs["jobDefinition"] == "test-def"
        assert first_call_kwargs["parameters"] == _TASKS[0]

        assert result[0]["job_id"] == "aaaa-1111"
        assert result[1]["job_id"] == "bbbb-2222"

    def test_submit_passes_task_dict_as_parameters(self) -> None:
        mock_client = MagicMock()
        mock_client.submit_job.return_value = {"jobId": "x"}

        with patch("leviathan.common.batch_submit.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            submit_batch_jobs(
                tasks=[{"year": "2020", "bucket": "my-bucket"}],
                job_queue="q",
                job_definition="d",
                build_job_name=lambda t: "test-job",
                aws_region="eu-west-1",
                dry_run=False,
            )

        _, kwargs = mock_client.submit_job.call_args
        assert kwargs["parameters"] == {"year": "2020", "bucket": "my-bucket"}

    def test_empty_task_list_returns_empty(self) -> None:
        with patch("leviathan.common.batch_submit.boto3"):
            result = submit_batch_jobs(
                tasks=[],
                job_queue="q",
                job_definition="d",
                build_job_name=lambda t: "name",
                aws_region="us-east-1",
                dry_run=False,
            )
        assert result == []


# ---------------------------------------------------------------------------
# write_run_record
# ---------------------------------------------------------------------------

class TestWriteRunRecord:
    def test_creates_file_with_json_content(self, tmp_path: Path) -> None:
        payload = {"run_id": "2024-01-01", "count": 5, "items": ["a", "b"]}
        out = tmp_path / "run.json"
        write_run_record(out, payload)

        assert out.exists()
        loaded = json.loads(out.read_text())
        assert loaded == payload

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        out = tmp_path / "deep" / "nested" / "run.json"
        write_run_record(out, {"x": 1})
        assert out.exists()

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        out = tmp_path / "run.json"
        out.write_text('{"old": true}')
        write_run_record(out, {"new": True})
        assert json.loads(out.read_text()) == {"new": True}
