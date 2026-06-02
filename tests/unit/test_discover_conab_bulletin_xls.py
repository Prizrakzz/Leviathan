"""Unit tests for CONAB bulletin XLS discovery."""
from __future__ import annotations

from jobs.ingest.discover_conab_bulletin_xls import (
    ConabBulletinXlsEntry,
    build_data_page_url,
    extract_entries_from_html,
    merge_entries,
)


def test_build_data_page_url_uses_conab_survey_slug() -> None:
    url = build_data_page_url(2025, 2)

    assert (
        "2o-levantamento-de-cafe-safra-2025/"
        "tabela-de-dados-estimativas-da-producao-e-colheita/view"
    ) in url


def test_extract_entries_from_html_finds_download_file_link() -> None:
    html = """
    <html><body>
      <p>
        <a href="@@download/file">
          Site_PREVISAO-DE-SAFRA-CAFE-MAI-2025.xls
        </a> - 498 KB
      </p>
    </body></html>
    """

    entries = extract_entries_from_html(
        html,
        safra_year=2025,
        survey_no=2,
        data_page=build_data_page_url(2025, 2),
        discovered_at="2026-06-02T00:00:00+00:00",
    )

    assert len(entries) == 1
    entry = entries[0]
    assert entry.safra_year == 2025
    assert entry.survey_no == 2
    assert entry.filename == "Site_PREVISAO-DE-SAFRA-CAFE-MAI-2025.xls"
    assert entry.file_size_label == "498 KB"
    assert entry.xls_url.endswith(
        "tabela-de-dados-estimativas-da-producao-e-colheita/@@download/file"
    )


def test_extract_entries_deduplicates_and_rejects_non_coffee_xls() -> None:
    html = """
    <html><body>
      <a href="@@download/file/Site_PREVISAO-DE-SAFRA-CAFE-SET-2024.xls">
        Site_PREVISAO-DE-SAFRA-CAFE-SET-2024.xls
      </a>
      <a href="@@download/file/Site_PREVISAO-DE-SAFRA-CAFE-SET-2024.xls">
        Site_PREVISAO-DE-SAFRA-CAFE-SET-2024.xls
      </a>
      <a href="@@download/file/Site_PREVISAO_DE_SAFRA-POR_PRODUTO-SET-2024.xlsx">
        Site_PREVISAO_DE_SAFRA-POR_PRODUTO-SET-2024.xlsx
      </a>
    </body></html>
    """

    entries = extract_entries_from_html(
        html,
        safra_year=2024,
        survey_no=3,
        data_page=build_data_page_url(2024, 3),
        discovered_at="2026-06-02T00:00:00+00:00",
    )

    assert len(entries) == 1
    assert entries[0].filename == "Site_PREVISAO-DE-SAFRA-CAFE-SET-2024.xls"


def test_extract_entries_uses_anchor_text_filename_with_spaces() -> None:
    html = """
    <html><body>
      <p>
        <a href="@@download/file">
          Site_PREVISAO-DE-SAFRA-CAFE-JAN-2025_1 (1).xls
        </a> - 496 KB
      </p>
    </body></html>
    """

    entries = extract_entries_from_html(
        html,
        safra_year=2025,
        survey_no=1,
        data_page=build_data_page_url(2025, 1),
        discovered_at="2026-06-02T00:00:00+00:00",
    )

    assert len(entries) == 1
    assert entries[0].filename == "Site_PREVISAO-DE-SAFRA-CAFE-JAN-2025_1 (1).xls"


def test_merge_entries_preserves_existing_when_live_discovery_missing() -> None:
    existing = ConabBulletinXlsEntry(
        safra_year=2026,
        survey_no=1,
        source_page="source",
        data_page="source",
        xls_url="https://example.com/site_previsao-de-safra-cafe-fev-2026.xls",
        filename="site_previsao-de-safra-cafe-fev-2026.xls",
        file_size_label=None,
        discovered_at="2026-06-01T00:00:00+00:00",
    )
    discovered = ConabBulletinXlsEntry(
        safra_year=2025,
        survey_no=1,
        source_page="source",
        data_page="data",
        xls_url="https://example.com/@@download/file",
        filename="Site_PREVISAO-DE-SAFRA-CAFE-JAN-2025.xls",
        file_size_label="496 KB",
        discovered_at="2026-06-02T00:00:00+00:00",
    )

    merged = merge_entries([discovered], [existing])

    assert [(entry.safra_year, entry.survey_no) for entry in merged] == [(2025, 1), (2026, 1)]
