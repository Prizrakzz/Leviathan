"""Unit tests for UNICA bi-weekly fetch error classification / run gating.

Focus: a permanently-pruned historical bulletin returns a *soft 404* -- an
HTTP 200 whose body is either a sub-minimum CMS placeholder PDF or a non-PDF
Wayback snapshot-selection page.  It lives in the hand/Wayback-curated
manifest, is re-fetched on every run, never uploads or enters the skip path,
and therefore re-fails forever.  It must be tolerated as ``missing`` instead of
failing the whole fetch, while every other failure (network/5xx, S3, generic
validation, unexpected) stays fatal.

Regression origin: the ``unica-w2canary`` run exited ``uploaded=0 skipped=268
errors=8`` -- all 8 "errors" were soft-404s ("PDF too small" x6, "Response is
not a PDF" x2).  ``_is_pruned_source`` / ``_exit_reason`` existed but were never
wired into ``main()``, so soft-404s were miscounted as fatal validation errors.
Mirrors the SAGIS ``fetch_sagis_cec`` gating contract.
"""
from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from jobs.ingest import fetch_unica_biweekly as mod
from jobs.ingest.fetch_unica_biweekly import (
    _download_pdf,
    _exit_reason,
    _is_pruned_source,
    _PrunedSourceError,
)


class _FakeHTTPResponse:
    """Minimal stand-in for the object returned by ``urllib.request.urlopen``.

    Supports the context-manager + ``.read()`` protocol that ``_download_pdf``
    relies on, so no real network call is made.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._data


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, data: bytes) -> None:
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: _FakeHTTPResponse(data)
    )


# ---------------------------------------------------------------------------
# _is_pruned_source
# ---------------------------------------------------------------------------

def test_is_pruned_source_true_for_pruned_error() -> None:
    assert _is_pruned_source(_PrunedSourceError("soft 404")) is True


def test_is_pruned_source_false_for_network_error() -> None:
    # urllib network/5xx transport errors stay fatal, never tolerated.
    assert _is_pruned_source(urllib.error.URLError("connection reset")) is False


def test_is_pruned_source_false_for_generic_runtime_error() -> None:
    # A non-pruned RuntimeError (some other validation failure) stays fatal.
    assert _is_pruned_source(RuntimeError("unexpected validation")) is False


def test_is_pruned_source_false_for_s3_and_unexpected() -> None:
    assert _is_pruned_source(OSError("S3 upload failed")) is False
    assert _is_pruned_source(Exception("boom")) is False


# ---------------------------------------------------------------------------
# _download_pdf soft-404 classification (the exact two observed failure modes)
# ---------------------------------------------------------------------------

def test_download_pdf_too_small_raises_pruned(monkeypatch: pytest.MonkeyPatch) -> None:
    # Valid %PDF header but under _MIN_PDF_BYTES -> CMS placeholder "error page".
    # Reproduces "PDF too small (29,730 bytes) ... likely an error page".
    small_pdf = mod._PDF_MAGIC + b"-1.4\n" + b"0" * 1_000
    assert len(small_pdf) < mod._MIN_PDF_BYTES
    _patch_urlopen(monkeypatch, small_pdf)
    with pytest.raises(_PrunedSourceError):
        _download_pdf("https://unicadata.com.br/arquivos/pdfs/2014/08/x.pdf")


def test_download_pdf_non_pdf_raises_pruned(monkeypatch: pytest.MonkeyPatch) -> None:
    # Non-PDF body (Wayback snapshot-selection HTML) -> "Response is not a PDF".
    html = b"<!DOCTYPE html><html><body>Wayback snapshot picker</body></html>"
    _patch_urlopen(monkeypatch, html)
    with pytest.raises(_PrunedSourceError):
        _download_pdf("https://web.archive.org/web/2017/http://x/y.pdf")


def test_download_pdf_soft_404s_classify_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Both observed failure modes must be classified pruned (-> missing tally),
    # never fatal.  This is the classification the main() loop relies on.
    for body in (
        mod._PDF_MAGIC + b"-1.4\n" + b"0" * 1_000,          # too small
        b"<html>not a pdf</html>",                           # missing %PDF header
    ):
        _patch_urlopen(monkeypatch, body)
        try:
            _download_pdf("https://example/x.pdf")
        except Exception as exc:  # noqa: BLE001 -- asserting classification below
            assert _is_pruned_source(exc) is True
        else:  # pragma: no cover - defensive
            pytest.fail("expected _PrunedSourceError, none raised")


def test_download_pdf_valid_returns_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    # A real, large-enough PDF returns its bytes and does NOT raise.
    good_pdf = mod._PDF_MAGIC + b"-1.7\n" + b"0" * mod._MIN_PDF_BYTES
    _patch_urlopen(monkeypatch, good_pdf)
    assert _download_pdf("https://unicadata.com.br/download_media.php?idM=1") == good_pdf


# ---------------------------------------------------------------------------
# _exit_reason
# ---------------------------------------------------------------------------

def test_exit_reason_none_on_clean_run() -> None:
    assert _exit_reason(uploaded=5, skipped=0, errors=0, missing=0) is None


def test_exit_reason_fails_on_real_errors() -> None:
    reason = _exit_reason(uploaded=3, skipped=0, errors=2, missing=0)
    assert reason is not None
    assert "2 bulletin(s) failed" in reason


def test_exit_reason_none_when_missing_but_uploads_happened() -> None:
    # Attempt-1 shape of the canary: 1 uploaded, 267 skipped, 8 pruned soft-404s.
    # Must stay green instead of exiting 1.
    assert _exit_reason(uploaded=1, skipped=267, errors=0, missing=8) is None


def test_exit_reason_none_when_missing_but_skips_preserve_signal() -> None:
    # Steady state / final canary attempt: everything already in S3 (skipped),
    # only the 8 pruned links soft-404.  Not a dead source -> green.
    assert _exit_reason(uploaded=0, skipped=268, errors=0, missing=8) is None


def test_exit_reason_fails_when_source_fully_dead() -> None:
    # Nothing uploaded, nothing skipped, only pruned links: never look green.
    reason = _exit_reason(uploaded=0, skipped=0, errors=0, missing=8)
    assert reason is not None
    assert "pruned/missing" in reason


def test_exit_reason_errors_take_priority_over_dead_source() -> None:
    reason = _exit_reason(uploaded=0, skipped=0, errors=1, missing=1)
    assert reason is not None
    assert "1 bulletin(s) failed" in reason


def test_exit_reason_none_when_all_zero() -> None:
    # Degenerate no-op (e.g. no target bulletins) is not a failure by itself.
    assert _exit_reason(uploaded=0, skipped=0, errors=0, missing=0) is None
