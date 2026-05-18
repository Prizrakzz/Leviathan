"""Shared types for the leviathan pipeline.

Import these instead of repeating inline TypedDict / Literal definitions
across modules.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict

# ProcessResult is the return type used by base_jobs worker methods.
# "success" = written, "skipped" = already existed, "failed" = dead-lettered.
ProcessResult = tuple[Literal["success", "failed", "skipped"], str]

# A single geographic sampling location loaded from a commodity's regions YAML.
class Region(TypedDict):
    country: str
    region: str
    latitude: float
    longitude: float

# Type alias for an S3 object key string.
BronzeKey = str
SilverKey = str

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client  # noqa: F401 — used only by type checkers
