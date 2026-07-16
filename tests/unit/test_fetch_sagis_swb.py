"""Unit tests for the fetch_sagis_swb 404-tolerance helpers.

SAGIS leaves pruned bulletin links in the WordPress page HTML, so they are
re-discovered every run and 404 on download. Mirrors test_fetch_sagis_cec.py /
test_fetch_sagis_weekly.py: a permanent 404 is tolerated (WARN + `missing`
tally); any other failure (5xx/timeout/validation/S3), or a run that discovered
only-dead links, still fails.
"""
from __future__ import annotations

import requests

from jobs.ingest.fetch_sagis_swb import _exit_reason, _is_permanent_404


def _httperr(status: int) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(response=resp)


class TestIsPermanent404:
    def test_404_is_permanent(self):
        assert _is_permanent_404(_httperr(404)) is True

    def test_5xx_is_not_permanent(self):
        assert _is_permanent_404(_httperr(503)) is False

    def test_403_is_not_permanent(self):
        assert _is_permanent_404(_httperr(403)) is False

    def test_httperror_without_response_is_not_permanent(self):
        assert _is_permanent_404(requests.HTTPError()) is False

    def test_timeout_is_not_permanent(self):
        assert _is_permanent_404(requests.Timeout()) is False

    def test_generic_exception_is_not_permanent(self):
        assert _is_permanent_404(RuntimeError("boom")) is False


class TestExitReason:
    def test_clean_run_passes(self):
        assert _exit_reason(uploaded=10, skipped=5, errors=0, missing=0) is None

    def test_observed_recanary_row_passes(self):
        # The exact live run that had been failing: 621 uploaded, 132 skipped, 2 pruned 404s.
        assert _exit_reason(uploaded=621, skipped=132, errors=0, missing=2) is None

    def test_real_error_fails(self):
        assert _exit_reason(uploaded=100, skipped=0, errors=1, missing=0) is not None

    def test_errors_take_priority_over_missing(self):
        assert _exit_reason(uploaded=0, skipped=0, errors=3, missing=5) is not None

    def test_missing_with_uploads_passes(self):
        assert _exit_reason(uploaded=1, skipped=0, errors=0, missing=9) is None

    def test_missing_with_skips_passes(self):
        assert _exit_reason(uploaded=0, skipped=7, errors=0, missing=3) is None

    def test_fully_dead_source_fails(self):
        # Nothing uploaded, nothing skipped, only 404s -> every discovered link is dead.
        assert _exit_reason(uploaded=0, skipped=0, errors=0, missing=4) is not None

    def test_all_zero_is_noop_pass(self):
        assert _exit_reason(uploaded=0, skipped=0, errors=0, missing=0) is None
