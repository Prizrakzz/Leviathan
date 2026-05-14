"""Unit tests for leviathan.common.base_jobs argument parsing helpers.

Tests focus on _parse_optional_str and _parse_optional_bool via a minimal
concrete subclass. These helpers use sys.argv directly and are exercised
outside the Glue runtime (no AWS calls needed).
"""
from __future__ import annotations

import sys
from unittest.mock import patch

import pandas as pd
import pytest

from leviathan.common.base_jobs import _BaseGlueJob


class _ConcreteJob(_BaseGlueJob):
    """Minimal concrete subclass to access the protected helper methods."""

    required_glue_args = ["commodity", "bucket", "aws_region"]

    def _make_args(self):
        """Simulate what __init__ does in real subclasses: parse required args."""
        return self._parse_args()


def _with_argv(*args):
    """Context manager that replaces sys.argv with a test argument list."""
    return patch.object(sys, "argv", ["glue_script.py", *args])


class TestParseOptionalStr:
    def test_returns_value_when_present(self):
        with _with_argv("--commodity", "cocoa", "--bucket", "my-bucket",
                        "--aws_region", "us-east-1", "--ingest_date", "2024-06-15"):
            job = _ConcreteJob()
            assert job._parse_optional_str("ingest_date") == "2024-06-15"

    def test_returns_default_when_absent(self):
        with _with_argv("--commodity", "cocoa", "--bucket", "my-bucket",
                        "--aws_region", "us-east-1"):
            job = _ConcreteJob()
            assert job._parse_optional_str("ingest_date", default="2000-01-01") == "2000-01-01"

    def test_empty_string_default(self):
        with _with_argv("--commodity", "cocoa", "--bucket", "b", "--aws_region", "us-east-1"):
            job = _ConcreteJob()
            assert job._parse_optional_str("missing_arg") == ""


class TestParseOptionalBool:
    def test_true_string_returns_true(self):
        with _with_argv("--commodity", "cocoa", "--bucket", "b", "--aws_region", "us-east-1",
                        "--force_overwrite", "true"):
            job = _ConcreteJob()
            assert job._parse_optional_bool("force_overwrite") is True

    def test_false_string_returns_false(self):
        with _with_argv("--commodity", "cocoa", "--bucket", "b", "--aws_region", "us-east-1",
                        "--force_overwrite", "false"):
            job = _ConcreteJob()
            assert job._parse_optional_bool("force_overwrite") is False

    def test_absent_flag_returns_false(self):
        with _with_argv("--commodity", "cocoa", "--bucket", "b", "--aws_region", "us-east-1"):
            job = _ConcreteJob()
            assert job._parse_optional_bool("force_overwrite") is False

    def test_case_insensitive_true(self):
        with _with_argv("--commodity", "cocoa", "--bucket", "b", "--aws_region", "us-east-1",
                        "--force_overwrite", "True"):
            job = _ConcreteJob()
            assert job._parse_optional_bool("force_overwrite") is True
