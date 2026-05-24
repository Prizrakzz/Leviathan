"""Integration tests for batch job submission flow.

Tests submit_batch_jobs + write_run_record working together,
using MagicMock for the AWS Batch client (moto[batch] not installed).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from leviathan.common.batch_submit import BatchJobRecord, submit_batch_jobs, write_run_record


def _make_mock_batch_client(job_ids: list[str]) -> MagicMock:
    """Return a mock boto3 batch client that returns sequential job IDs."""
    mock_client = MagicMock()
    mock_client.submit_job.side_effect = [
        {"jobId": jid} for jid in job_ids
    ]
    return mock_client


class TestSubmitBatchJobs:
    def test_returns_one_record_per_task(self):
        tasks = [
            {"commodity": "cocoa", "year": "2020"},
            {"commodity": "corn_cbot", "year": "2020"},
        ]
        mock_client = _make_mock_batch_client(["job-001", "job-002"])

        with patch("leviathan.common.batch_submit.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            records = submit_batch_jobs(
                tasks=tasks,
                job_queue="leviathan-queue",
                job_definition="leviathan-job:1",
                build_job_name=lambda t: f"test-{t['commodity']}-{t['year']}",
                aws_region="us-east-1",
            )

        assert len(records) == 2

    def test_job_ids_populated_in_records(self):
        tasks = [{"commodity": "cocoa", "year": "2020"}]
        mock_client = _make_mock_batch_client(["job-abc"])

        with patch("leviathan.common.batch_submit.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            records = submit_batch_jobs(
                tasks=tasks,
                job_queue="leviathan-queue",
                job_definition="leviathan-job:1",
                build_job_name=lambda t: f"test-{t['commodity']}",
                aws_region="us-east-1",
            )

        assert records[0]["job_id"] == "job-abc"

    def test_dry_run_returns_none_job_ids(self):
        tasks = [
            {"commodity": "cocoa", "year": "2020"},
            {"commodity": "corn_cbot", "year": "2021"},
        ]
        with patch("leviathan.common.batch_submit.boto3") as mock_boto3:
            records = submit_batch_jobs(
                tasks=tasks,
                job_queue="leviathan-queue",
                job_definition="leviathan-job:1",
                build_job_name=lambda t: f"test-{t['commodity']}",
                aws_region="us-east-1",
                dry_run=True,
            )
        # Batch API should NOT be called in dry_run mode
        mock_boto3.client.return_value.submit_job.assert_not_called()
        assert all(r["job_id"] is None for r in records)

    def test_job_names_built_correctly(self):
        tasks = [{"commodity": "cocoa", "year": "2020"}]
        mock_client = _make_mock_batch_client(["job-xyz"])

        with patch("leviathan.common.batch_submit.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            records = submit_batch_jobs(
                tasks=tasks,
                job_queue="q",
                job_definition="jd:1",
                build_job_name=lambda t: f"ingest-{t['commodity']}-{t['year']}",
                aws_region="us-east-1",
            )

        assert records[0]["job_name"] == "ingest-cocoa-2020"

    def test_parameters_preserved_in_record(self):
        task = {"commodity": "cocoa", "year": "2020", "region": "gh_main"}
        mock_client = _make_mock_batch_client(["job-1"])

        with patch("leviathan.common.batch_submit.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            records = submit_batch_jobs(
                tasks=[task],
                job_queue="q",
                job_definition="jd:1",
                build_job_name=lambda t: "name",
                aws_region="us-east-1",
            )

        assert records[0]["parameters"] == task


class TestWriteRunRecord:
    def test_creates_json_file(self, tmp_path):
        path = tmp_path / "runs" / "run_001.json"
        write_run_record(path, {"status": "ok", "job_count": 3})
        assert path.exists()

    def test_content_is_valid_json(self, tmp_path):
        path = tmp_path / "run.json"
        write_run_record(path, {"status": "ok", "job_count": 3})
        content = json.loads(path.read_text())
        assert content["status"] == "ok"
        assert content["job_count"] == 3

    def test_creates_parent_directories(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "run.json"
        write_run_record(deep, {"x": 1})
        assert deep.exists()


class TestSubmitAndRecord:
    """Integration: submit → write run record with job IDs."""

    def test_full_flow_run_record_contains_job_ids(self, tmp_path):
        tasks = [
            {"commodity": "cocoa", "year": "2020"},
            {"commodity": "corn_cbot", "year": "2020"},
        ]
        mock_client = _make_mock_batch_client(["job-001", "job-002"])

        with patch("leviathan.common.batch_submit.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            records = submit_batch_jobs(
                tasks=tasks,
                job_queue="q",
                job_definition="jd:1",
                build_job_name=lambda t: f"{t['commodity']}-{t['year']}",
                aws_region="us-east-1",
            )

        run_record = {
            "job_count": len(records),
            "job_ids": [r["job_id"] for r in records],
        }
        record_path = tmp_path / "run.json"
        write_run_record(record_path, run_record)

        loaded = json.loads(record_path.read_text())
        assert loaded["job_count"] == 2
        assert "job-001" in loaded["job_ids"]
        assert "job-002" in loaded["job_ids"]
