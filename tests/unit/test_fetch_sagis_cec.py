"""Unit tests for SAGIS CEC fetch error classification / run gating.

Focus: a permanently-pruned historical report (e.g. ``CEC-Aug-2020.pdf`` or
``CEC-2002-11-Winter.doc``) is still linked from the WordPress page and 404s on
every run.  It must be tolerated as ``missing`` instead of failing the whole
fetch, while every other failure stays fatal.  Mirrors the round-1
``fetch_sagis_weekly`` gating contract.
"""
from __future__ import annotations

import requests

from jobs.ingest.fetch_sagis_cec import _exit_reason, _is_permanent_404


def _http_error(status: int) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(f"{status} error", response=resp)


# ---------------------------------------------------------------------------
# _is_permanent_404
# ---------------------------------------------------------------------------

def test_is_permanent_404_true_for_404() -> None:
    assert _is_permanent_404(_http_error(404)) is True


def test_is_permanent_404_false_for_5xx() -> None:
    assert _is_permanent_404(_http_error(500)) is False
    assert _is_permanent_404(_http_error(503)) is False


def test_is_permanent_404_false_for_other_4xx() -> None:
    assert _is_permanent_404(_http_error(403)) is False


def test_is_permanent_404_false_when_no_response_attached() -> None:
    # A bare HTTPError with no response (defensive) must not be treated as 404.
    assert _is_permanent_404(requests.HTTPError("boom")) is False


def test_is_permanent_404_false_for_timeout_and_validation() -> None:
    # 5xx/timeout/validation/S3 stay fatal, never tolerated as missing.
    assert _is_permanent_404(requests.Timeout("timed out")) is False
    assert _is_permanent_404(RuntimeError("Expected PDF magic")) is False
    assert _is_permanent_404(OSError("S3 upload failed")) is False


# ---------------------------------------------------------------------------
# _exit_reason
# ---------------------------------------------------------------------------

def test_exit_reason_none_on_clean_run() -> None:
    assert _exit_reason(uploaded=5, skipped=0, errors=0, missing=0) is None


def test_exit_reason_fails_on_real_errors() -> None:
    reason = _exit_reason(uploaded=3, skipped=0, errors=2, missing=0)
    assert reason is not None
    assert "2 report(s) failed" in reason


def test_exit_reason_none_when_missing_but_uploads_happened() -> None:
    # The observed recanary run: 437 uploaded, 3 skipped, 2 pruned 404 links.
    # Must stay green instead of exiting 1.
    assert _exit_reason(uploaded=437, skipped=3, errors=0, missing=2) is None


def test_exit_reason_none_when_missing_but_skips_preserve_signal() -> None:
    # Steady state: all good reports already in the manifest (skipped), only the
    # pruned links 404.  Not a dead source -> green.
    assert _exit_reason(uploaded=0, skipped=440, errors=0, missing=2) is None


def test_exit_reason_fails_when_source_fully_dead() -> None:
    # Nothing uploaded, nothing skipped, only 404s: never look green.
    reason = _exit_reason(uploaded=0, skipped=0, errors=0, missing=2)
    assert reason is not None
    assert "404" in reason


def test_exit_reason_errors_take_priority_over_dead_source() -> None:
    reason = _exit_reason(uploaded=0, skipped=0, errors=1, missing=1)
    assert reason is not None
    assert "1 report(s) failed" in reason


def test_exit_reason_none_when_all_zero() -> None:
    # Degenerate no-op (e.g. --limit 0) is not a failure by itself.
    assert _exit_reason(uploaded=0, skipped=0, errors=0, missing=0) is None
