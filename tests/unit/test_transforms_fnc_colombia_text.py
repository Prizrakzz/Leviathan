"""Unit tests for FNC Colombia PDF raw -> text extraction."""
from __future__ import annotations

import pytest

from leviathan.transforms.raw_to_text.fnc_colombia import (
    classify_fnc_publisher,
    extract_fnc_pdf,
    parse_fnc_publication_date,
)


def test_parse_period_header_with_spanish_month() -> None:
    assert parse_fnc_publication_date("PERIODO: DICIEMBRE 2024") == "2024-12-01"


def test_parse_fnc_informe_header() -> None:
    assert (
        parse_fnc_publication_date("INFORME MENSUAL NOVIEMBRE 2025")
        == "2025-11-01"
    )


def test_parse_exportaciones_header() -> None:
    assert (
        parse_fnc_publication_date("INFORME MENSUAL DE EXPORTACIONES NOVIEMBRE 2025")
        == "2025-11-01"
    )


def test_filename_without_year_does_not_use_upload_date() -> None:
    raw_key = (
        "raw/production/source=fnc/monthly_reports/report_type=cifras/"
        "upload_year=2026/upload_month=03/Informe-mensual-enero-p.pdf"
    )
    assert (
        parse_fnc_publication_date("INFORME MENSUAL ENERO 2023", raw_key)
        == "2023-01-01"
    )


def test_filename_fallback_supports_two_digit_year() -> None:
    raw_key = "raw/production/source=fnc/monthly_reports/report_type=exportaciones/Informe-Expos-Noviembre-25.pdf"
    assert parse_fnc_publication_date("", raw_key) == "2025-11-01"


def test_classifies_fepcafe_cifras() -> None:
    assert classify_fnc_publisher("FEPCAFÉ Reporte Mensual", "cifras") == "fepcafe_reporte_mensual"


def test_classifies_exportaciones() -> None:
    assert classify_fnc_publisher("INFORME MENSUAL DE EXPORTACIONES", "exportaciones") == "fnc_exportaciones"


def test_extract_fnc_informe_skips_cover_and_keeps_narrative(monkeypatch) -> None:
    long_page = "Precio interno y producción. " * 30

    class _FakePage:
        def __init__(self, text: str):
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakePdf:
        pages = [
            _FakePage("INFORME MENSUAL NOVIEMBRE 2025\nTabla de contenido"),
            _FakePage(long_page),
            _FakePage("short chart labels"),
        ]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("pdfplumber.open", lambda *args, **kwargs: _FakePdf())

    result = extract_fnc_pdf(b"fake", "raw/key.pdf", "cifras")

    assert result.publication_date == "2025-11-01"
    assert result.publisher == "fnc_informe_mensual"
    assert result.document["source"] == "fnc"
    assert result.document["sections"][0]["name"] == "fnc_informe_mensual_page_02"
    assert "Precio interno" in result.document["full_text"]
    assert "Tabla de contenido" not in result.document["full_text"]


def test_extract_exportaciones_keeps_resumen_general(monkeypatch) -> None:
    resumen = "Resumen general de exportaciones y principales destinos. " * 8

    class _FakePage:
        def __init__(self, text: str):
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakePdf:
        pages = [
            _FakePage("INFORME MENSUAL DE EXPORTACIONES NOVIEMBRE 2025"),
            _FakePage(resumen),
            _FakePage("axis labels 1 2 3"),
        ]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("pdfplumber.open", lambda *args, **kwargs: _FakePdf())

    result = extract_fnc_pdf(b"fake", "raw/key.pdf", "exportaciones")

    assert result.publisher == "fnc_exportaciones"
    assert result.document["sections"][0]["name"] == "resumen_general"
    assert "principales destinos" in result.document["full_text"]
    assert "axis labels" not in result.document["full_text"]


def test_unparseable_publication_date_raises() -> None:
    with pytest.raises(ValueError, match="Could not parse"):
        parse_fnc_publication_date("no date here", "raw/key.pdf")
