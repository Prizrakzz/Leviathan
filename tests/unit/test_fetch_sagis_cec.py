"""Unit tests for SAGIS CEC fetch error classification / run gating.

Focus: a permanently-pruned historical report (e.g. ``CEC-Aug-2020.pdf`` or
``CEC-2002-11-Winter.doc``) is still linked from the WordPress page and 404s on
every run.  It must be tolerated as ``missing`` instead of failing the whole
fetch, while every other failure stays fatal.  Mirrors the round-1
``fetch_sagis_weekly`` gating contract.
"""
from __future__ import annotations

import socket
import threading

import pytest
import requests

from jobs.ingest.fetch_sagis_cec import (
    _RETRY_STATUS_FORCELIST,
    _RETRY_TOTAL,
    _build_session,
    _exit_reason,
    _is_permanent_404,
)


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


# ---------------------------------------------------------------------------
# _build_session -- transport retry
#
# Regression cover for 2026-07-31: www.sagis.org.za dropped the connection
# mid-transfer on 2-4 random files out of ~440 sequential GETs.  With a bare
# requests.Session (one shot per file) each drop incremented `errors`, and
# _exit_reason fails the run on ANY non-404 error -- so two dropped packets
# killed a 25-minute fetch, twice, before the third attempt came back clean.
# ---------------------------------------------------------------------------

class _FlakyServer:
    """Localhost HTTP server that closes the first *drops* connections without
    responding -- reproducing ``RemoteDisconnected`` exactly, then serves 200."""

    def __init__(self, drops: int) -> None:
        self.drops = drops
        self.hits = 0
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/CEC-1999-12.pdf"

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:  # closed by stop()
                return
            self.hits += 1
            try:
                conn.recv(65535)
                if self.hits <= self.drops:
                    continue  # close with no response -> RemoteDisconnected
                body = b"%PDF-1.4 fake"
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\nConnection: close\r\n\r\n"
                    + body
                )
            finally:
                conn.close()

    def stop(self) -> None:
        self._sock.close()


@pytest.fixture()
def flaky_server():
    servers: list[_FlakyServer] = []

    def _make(drops: int) -> _FlakyServer:
        s = _FlakyServer(drops)
        servers.append(s)
        return s

    yield _make
    for s in servers:
        s.stop()


def test_bare_session_dies_on_a_single_dropped_connection(flaky_server) -> None:
    """The pre-fix behaviour, pinned so the regression is unambiguous."""
    srv = flaky_server(1)
    bare = requests.Session()
    with pytest.raises(requests.exceptions.ConnectionError):
        bare.get(srv.url, timeout=10)
    assert srv.hits == 1  # exactly one shot, then the run would go red


def test_build_session_retries_a_dropped_connection(flaky_server) -> None:
    """The fix: the same drop is retried in-process and the GET succeeds."""
    srv = flaky_server(1)
    resp = _build_session().get(srv.url, timeout=10)
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")
    assert srv.hits == 2  # dropped once, retried once, served


def test_build_session_gives_up_after_the_retry_budget(flaky_server) -> None:
    """Retries are bounded -- an endlessly-dropping host still fails the run."""
    srv = flaky_server(_RETRY_TOTAL + 5)
    session = _build_session()
    session.get_adapter("http://").max_retries.backoff_factor = 0  # keep the test fast
    with pytest.raises(requests.exceptions.ConnectionError):
        session.get(srv.url, timeout=10)
    assert srv.hits == _RETRY_TOTAL + 1  # initial attempt + _RETRY_TOTAL retries


def test_build_session_sets_the_user_agent() -> None:
    assert "Mozilla/5.0" in _build_session().headers["User-Agent"]


def test_build_session_mounts_retry_on_both_schemes() -> None:
    session = _build_session()
    for scheme in ("https://", "http://"):
        retry = session.get_adapter(scheme).max_retries
        assert retry.total == _RETRY_TOTAL
        assert retry.connect == _RETRY_TOTAL
        assert retry.read == _RETRY_TOTAL


def test_build_session_retries_get_and_leaves_404_alone() -> None:
    """A pruned link must NOT be retried: 404 stays a first-response HTTPError
    so _is_permanent_404 keeps tallying it as `missing` (2 per run today)."""
    retry = _build_session().get_adapter("https://").max_retries
    assert "GET" in retry.allowed_methods
    assert 404 not in _RETRY_STATUS_FORCELIST
    assert 403 not in _RETRY_STATUS_FORCELIST
    assert set(_RETRY_STATUS_FORCELIST) == {429, 500, 502, 503, 504}


def test_build_session_defers_status_raising_to_requests() -> None:
    """raise_on_status=False keeps the response (and therefore .status_code)
    attached to the HTTPError that raise_for_status() raises -- which is the
    object _is_permanent_404 inspects."""
    assert _build_session().get_adapter("https://").max_retries.raise_on_status is False
