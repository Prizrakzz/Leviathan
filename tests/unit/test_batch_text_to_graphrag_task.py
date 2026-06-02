"""Unit tests for text_to_graphrag task helpers."""
from __future__ import annotations

from jobs.batch.text_to_graphrag_task import _parse_year_month


def test_parse_year_month_supports_fnc_publication_date_key() -> None:
    key = (
        "text/source=fnc/monthly_reports/report_type=cifras/"
        "publisher=fnc_informe_mensual/publication_date=2025-11-01/document.json"
    )

    assert _parse_year_month(key) == (2025, 11)
