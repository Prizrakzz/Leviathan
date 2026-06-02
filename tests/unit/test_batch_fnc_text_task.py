"""Unit tests for the FNC text Batch task helpers."""
from __future__ import annotations

from unittest.mock import MagicMock

from jobs.batch import fnc_text_task as task
from leviathan.transforms.raw_to_text.fnc_colombia import FncTextExtraction


def test_select_keys_filters_report_type_and_pdf_suffix() -> None:
    keys = [
        "raw/production/source=fnc/monthly_reports/report_type=cifras/upload_year=2026/upload_month=03/a.pdf",
        "raw/production/source=fnc/monthly_reports/report_type=exportaciones/upload_year=2026/upload_month=03/b.pdf",
        "raw/production/source=fnc/monthly_reports/report_type=cifras/upload_year=2026/upload_month=03/c.txt",
    ]

    selected = task._select_keys(keys, report_type="cifras")

    assert selected == [keys[0]]


def test_process_one_writes_expected_text_key(monkeypatch) -> None:
    raw_key = (
        "raw/production/source=fnc/monthly_reports/report_type=cifras/"
        "upload_year=2026/upload_month=03/Informe-mensual-Noviembre-2025-p.pdf"
    )
    s3 = MagicMock()
    written: list[str] = []

    monkeypatch.setattr(task, "get_thread_local_s3_client", lambda _region: s3)
    monkeypatch.setattr(task, "s3_download_with_retry", lambda *_args, **_kwargs: b"pdf")
    monkeypatch.setattr(task, "document_exists", lambda *_args, **_kwargs: False)

    def fake_extract(_raw_bytes: bytes, _raw_key: str, _report_type: str) -> FncTextExtraction:
        return FncTextExtraction(
            publication_date="2025-11-01",
            publisher="fnc_informe_mensual",
            document={
                "source": "fnc",
                "raw_key": raw_key,
                "extraction_method": "pdfplumber",
                "extracted_at": "2026-06-02T00:00:00Z",
                "sections": [{"name": "summary", "text": "hello"}],
                "full_text": "hello",
            },
        )

    def fake_write(_s3, _bucket, key, _doc) -> None:
        written.append(key)

    monkeypatch.setattr(task, "extract_fnc_pdf", fake_extract)
    monkeypatch.setattr(task, "write_document", fake_write)

    status, text_key = task._process_one(raw_key, "bucket", "us-east-1", False)

    assert status == "written"
    assert text_key == written[0]
    assert text_key == (
        "text/source=fnc/monthly_reports/report_type=cifras/"
        "publisher=fnc_informe_mensual/publication_date=2025-11-01/document.json"
    )


def test_process_one_skips_existing_document(monkeypatch) -> None:
    raw_key = (
        "raw/production/source=fnc/monthly_reports/report_type=exportaciones/"
        "upload_year=2026/upload_month=03/Informe-Expos-Noviembre-25.pdf"
    )

    monkeypatch.setattr(task, "get_thread_local_s3_client", lambda _region: MagicMock())
    monkeypatch.setattr(task, "s3_download_with_retry", lambda *_args, **_kwargs: b"pdf")
    monkeypatch.setattr(task, "document_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        task,
        "extract_fnc_pdf",
        lambda *_args, **_kwargs: FncTextExtraction(
            publication_date="2025-11-01",
            publisher="fnc_exportaciones",
            document={
                "source": "fnc",
                "raw_key": raw_key,
                "extraction_method": "pdfplumber",
                "extracted_at": "2026-06-02T00:00:00Z",
                "sections": [],
                "full_text": "hello",
            },
        ),
    )

    status, text_key = task._process_one(raw_key, "bucket", "us-east-1", False)

    assert status == "skipped"
    assert "publication_date=2025-11-01" in text_key
