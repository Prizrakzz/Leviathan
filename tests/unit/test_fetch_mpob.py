"""Unit tests for the MPOB BEPI fetcher's soft-miss classification.

Covers the scoped hardening in ``jobs/ingest/fetch_mpob.py``: a monthly_release
month that is not yet published (or has rolled off MPOB's single-slot stat root)
returns HTTP 200 without the ``CRUDE PALM OIL`` table marker.  For a
monthly_release entry this must be a WARNING + soft-miss tally, never a fatal
error that fails an autonomous ingest chain.  Every other failure class stays
fatal.

Pure Python -- no S3/AWS/network.  Only the manifest download of one dead
monthly val1 slot motivated this; the decision logic is fully captured by
``_is_unpublished_month``.
"""
from __future__ import annotations

import requests

from jobs.ingest.fetch_mpob import _ContentValidationMiss, _is_unpublished_month


class TestContentValidationMiss:
    def test_is_an_exception(self) -> None:
        assert issubclass(_ContentValidationMiss, Exception)

    def test_carries_message(self) -> None:
        exc = _ContentValidationMiss("marker absent")
        assert "marker absent" in str(exc)


class TestIsUnpublishedMonth:
    """Only a marker-miss on a monthly_release entry is a soft miss."""

    def test_monthly_marker_miss_is_soft(self) -> None:
        exc = _ContentValidationMiss("'CRUDE PALM OIL' not found")
        assert _is_unpublished_month("monthly_release", exc) is True

    def test_annual_marker_miss_is_fatal(self) -> None:
        # An annual_summary page missing the marker is a real defect, not a
        # not-yet-published month -- must stay fatal.
        exc = _ContentValidationMiss("'CRUDE PALM OIL' not found")
        assert _is_unpublished_month("annual_summary", exc) is False

    def test_overview_pdf_marker_miss_is_fatal(self) -> None:
        exc = _ContentValidationMiss("'CRUDE PALM OIL' not found")
        assert _is_unpublished_month("overview_pdf", exc) is False

    def test_monthly_http_error_is_fatal(self) -> None:
        # A transport error on a monthly entry is NOT a soft miss.
        exc = requests.HTTPError("500 Server Error")
        assert _is_unpublished_month("monthly_release", exc) is False

    def test_monthly_generic_runtime_error_is_fatal(self) -> None:
        # e.g. an S3 upload failure surfacing as a generic exception.
        exc = RuntimeError("upload failed")
        assert _is_unpublished_month("monthly_release", exc) is False
