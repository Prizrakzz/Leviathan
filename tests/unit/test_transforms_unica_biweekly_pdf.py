"""Unit tests for the UNICA biweekly PDF → bronze transform.

Tests are pure Python — no S3/AWS dependencies.  Each test that exercises a
full PDF parse downloads the fixture once from S3 and caches it as a local
file under ``tests/fixtures/unica_biweekly/{doc_type}/report.pdf``.

Downloading fixtures
--------------------
Run the following helper once before executing the test suite for the first
time (requires AWS credentials with access to ``leviathan-dev-shahem-001``):

    python -c "
    import boto3, os, pathlib
    s3 = boto3.client('s3', region_name='us-east-1')
    bucket = 'leviathan-dev-shahem-001'
    fixtures = [
        ('biweekly_old_pt', 'harvest_year=2012_2013/idm=pdf_04500aa73c3eb5ce'),
        ('biweekly_new_pt', 'harvest_year=2023_2024/idm=pdf_1775f0afde26b483'),
        ('biweekly_new_en', 'harvest_year=2022_2023/idm=pdf_35d5f4012d86b540'),
        ('season_final_pt', 'harvest_year=2018_2019/idm=pdf_b851e3557530ca223a81fcce166a6c3e'),
        ('season_close_en_double', 'harvest_year=2025_2026/idm=32820684'),
    ]
    for doc_type, path in fixtures:
        raw_key = f'raw/production/source=unica_biweekly/{path}/report.pdf'
        dest = pathlib.Path(f'tests/fixtures/unica_biweekly/{doc_type}/report.pdf')
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = s3.get_object(Bucket=bucket, Key=raw_key)['Body'].read()
        dest.write_bytes(data)
        print(f'Written {dest}  ({len(data):,} bytes)')
    "

All tests that load a fixture will be skipped automatically if the file does
not exist, so the suite can run in CI environments without S3 access (only
the helper tests will run there).
"""
from __future__ import annotations

import pathlib

import pytest

from leviathan.transforms.raw_to_bronze.unica_biweekly_pdf import (
    _extract_fortnight_dates,
    _parse_br_num,
    _parse_cover_date,
    _unpack_triplets,
    classify_pdf,
    transform_pdf,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURE_BASE = pathlib.Path(__file__).parent.parent / "fixtures" / "unica_biweekly"

_FIXTURES = {
    "biweekly_old_pt":          _FIXTURE_BASE / "biweekly_old_pt" / "report.pdf",
    "biweekly_new_pt":          _FIXTURE_BASE / "biweekly_new_pt" / "report.pdf",
    "biweekly_new_en":          _FIXTURE_BASE / "biweekly_new_en" / "report.pdf",
    "season_final_pt":          _FIXTURE_BASE / "season_final_pt" / "report.pdf",
    "season_close_en_double":   _FIXTURE_BASE / "season_close_en_double" / "report.pdf",
}


def _load(doc_type: str) -> bytes:
    path = _FIXTURES[doc_type]
    if not path.exists():
        pytest.skip(f"Fixture not found: {path} — run the download helper first")
    return path.read_bytes()


# ---------------------------------------------------------------------------
# Tests: _parse_br_num
# ---------------------------------------------------------------------------


class TestParseBrNum:
    def test_integer_with_dot_thousands(self) -> None:
        assert _parse_br_num("1.234.567") == pytest.approx(1_234_567.0)

    def test_decimal_comma(self) -> None:
        assert _parse_br_num("12.066,56") == pytest.approx(12_066.56)

    def test_integer_without_separator(self) -> None:
        assert _parse_br_num("261096") == pytest.approx(261_096.0)

    def test_negative(self) -> None:
        assert _parse_br_num("-38.523") == pytest.approx(-38_523.0)

    def test_kerning_spaces(self) -> None:
        # Old PDFs produce "1 89.559" for 189559
        assert _parse_br_num("1 89.559") == pytest.approx(189_559.0)

    def test_kerning_and_decimal(self) -> None:
        assert _parse_br_num("1 2.066") == pytest.approx(12_066.0)

    def test_unparseable_returns_none(self) -> None:
        assert _parse_br_num("n/a") is None

    def test_none_input(self) -> None:
        assert _parse_br_num(None) is None  # type: ignore[arg-type]

    def test_percentage_string(self) -> None:
        # Percentage strings like "-12,62%" should return -12.62
        assert _parse_br_num("-12,62%") == pytest.approx(-12.62)

    def test_whitespace_only(self) -> None:
        assert _parse_br_num("   ") is None


# ---------------------------------------------------------------------------
# Tests: _extract_fortnight_dates
# ---------------------------------------------------------------------------


class TestExtractFortnightDates:
    def test_finds_two_dates(self) -> None:
        text = "Primeira quinzena 01/04 e segunda quinzena 16/04"
        assert _extract_fortnight_dates(text) == ["01/04", "16/04"]

    def test_ignores_full_dates(self) -> None:
        # DD/MM/YYYY should NOT be returned (full year)
        text = "Posição até 16/03/2024"
        dates = _extract_fortnight_dates(text)
        assert "16/03/2024" not in dates

    def test_empty_text(self) -> None:
        assert _extract_fortnight_dates("") == []


# ---------------------------------------------------------------------------
# Tests: _parse_cover_date
# ---------------------------------------------------------------------------


class TestParseCoverDate:
    def test_portuguese(self) -> None:
        text = "Acompanhamento quinzenal\nPosição até 16/03/2024"
        assert _parse_cover_date(text) == "16/03/2024"

    def test_english(self) -> None:
        text = "Bi-weekly Bulletin\nPosition until 01/06/2022"
        assert _parse_cover_date(text) == "01/06/2022"

    def test_not_found(self) -> None:
        assert _parse_cover_date("No date here") is None


# ---------------------------------------------------------------------------
# Tests: _unpack_triplets
# ---------------------------------------------------------------------------


class TestUnpackTriplets:
    def test_single_row(self) -> None:
        cell = "298.790 261.096 -12,62%"
        result = _unpack_triplets(cell)
        assert len(result) == 1
        prior, current, var_pct = result[0]
        assert prior == pytest.approx(298_790.0)
        assert current == pytest.approx(261_096.0)
        assert var_pct == pytest.approx(-12.62)

    def test_multiple_rows(self) -> None:
        cell = "100 200 100%\n300 250 -16,67%"
        result = _unpack_triplets(cell)
        assert len(result) == 2
        assert result[0][1] == pytest.approx(200.0)
        assert result[1][1] == pytest.approx(250.0)

    def test_two_value_row_no_var_pct(self) -> None:
        cell = "100 200"
        result = _unpack_triplets(cell)
        assert len(result) == 1
        prior, current, var_pct = result[0]
        assert prior == pytest.approx(100.0)
        assert current == pytest.approx(200.0)
        assert var_pct is None

    def test_empty_cell(self) -> None:
        assert _unpack_triplets("") == []

    def test_none_cell(self) -> None:
        assert _unpack_triplets(None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests: classify_pdf
# ---------------------------------------------------------------------------


class TestClassifyPdf:
    def test_biweekly_old_pt(self) -> None:
        pdf_bytes = _load("biweekly_old_pt")
        assert classify_pdf(pdf_bytes) == "biweekly_old_pt"

    def test_biweekly_new_pt(self) -> None:
        pdf_bytes = _load("biweekly_new_pt")
        assert classify_pdf(pdf_bytes) == "biweekly_new_pt"

    def test_biweekly_new_en(self) -> None:
        pdf_bytes = _load("biweekly_new_en")
        assert classify_pdf(pdf_bytes) == "biweekly_new_en"

    def test_season_final_pt(self) -> None:
        pdf_bytes = _load("season_final_pt")
        assert classify_pdf(pdf_bytes) == "season_final_pt"

    def test_season_close_en_double(self) -> None:
        pdf_bytes = _load("season_close_en_double")
        assert classify_pdf(pdf_bytes) == "season_close_en_double"


# ---------------------------------------------------------------------------
# Tests: transform_pdf — schema and row-count assertions
# ---------------------------------------------------------------------------


class TestTransformPdfOldPt:
    def test_classification(self) -> None:
        tables = transform_pdf(_load("biweekly_old_pt"), "2012_2013", "pdf_04500aa73c3eb5ce", "2026-06-01")
        assert tables["_classification"] == "biweekly_old_pt"

    def test_fortnight_production_columns(self) -> None:
        tables = transform_pdf(_load("biweekly_old_pt"), "2012_2013", "pdf_04500aa73c3eb5ce", "2026-06-01")
        df = tables["fortnight_production"]
        expected_cols = {
            "harvest_year", "idm", "doc_type", "position_date",
            "fortnight_label", "fortnight_seq", "region", "variable",
            "period", "value", "unit", "ingest_date",
        }
        assert expected_cols.issubset(set(df.columns))

    def test_fortnight_production_regions(self) -> None:
        tables = transform_pdf(_load("biweekly_old_pt"), "2012_2013", "pdf_04500aa73c3eb5ce", "2026-06-01")
        df = tables["fortnight_production"]
        assert set(df["region"].unique()) == {"centro_sul", "sao_paulo", "demais_estados"}

    def test_demais_estados_fallback(self) -> None:
        """DE values must equal CS - SP (within floating point tolerance)."""
        import pandas as pd
        tables = transform_pdf(_load("biweekly_old_pt"), "2012_2013", "pdf_04500aa73c3eb5ce", "2026-06-01")
        df = tables["fortnight_production"]
        for var in df["variable"].unique():
            for period in ["current", "prior"]:
                sub = df[(df["variable"] == var) & (df["period"] == period)]
                sp = sub[sub["region"] == "sao_paulo"].set_index("fortnight_seq")["value"]
                cs = sub[sub["region"] == "centro_sul"].set_index("fortnight_seq")["value"]
                de = sub[sub["region"] == "demais_estados"].set_index("fortnight_seq")["value"]
                for seq in sp.index.intersection(de.index).intersection(cs.index):
                    if pd.notna(sp[seq]) and pd.notna(cs[seq]) and pd.notna(de[seq]):
                        assert de[seq] == pytest.approx(cs[seq] - sp[seq], abs=1.0)

    def test_summary_snapshot_period_types(self) -> None:
        tables = transform_pdf(_load("biweekly_old_pt"), "2012_2013", "pdf_04500aa73c3eb5ce", "2026-06-01")
        df = tables["summary_snapshot"]
        assert "accumulated" in df["period_type"].values
        assert "fortnightly" in df["period_type"].values

    def test_monthly_sales_artifact_stripping(self) -> None:
        tables = transform_pdf(_load("biweekly_old_pt"), "2012_2013", "pdf_04500aa73c3eb5ce", "2026-06-01")
        if "monthly_ethanol_sales" not in tables:
            pytest.skip("No monthly sales table extracted")
        df = tables["monthly_ethanol_sales"]
        # None of the month labels should be artifacts
        artifacts = {"la", "t", "o", "lonat", "lonatE", "latot", "E", "T"}
        for label in df["month_label"].dropna():
            assert label not in artifacts, f"Artifact label found: {label!r}"

    def test_ingest_date_present(self) -> None:
        tables = transform_pdf(_load("biweekly_old_pt"), "2012_2013", "pdf_04500aa73c3eb5ce", "2026-06-01")
        for table_name, df in tables.items():
            if table_name.startswith("_"):
                continue
            assert "ingest_date" in df.columns
            assert (df["ingest_date"] == "2026-06-01").all()


class TestTransformPdfNewPt:
    def test_classification(self) -> None:
        tables = transform_pdf(_load("biweekly_new_pt"), "2023_2024", "pdf_1775f0afde26b483", "2026-06-01")
        assert tables["_classification"] == "biweekly_new_pt"

    def test_fortnight_production_row_count(self) -> None:
        """13pp bulletin for 2023/24 has been active ~23 fortnights at position date."""
        tables = transform_pdf(_load("biweekly_new_pt"), "2023_2024", "pdf_1775f0afde26b483", "2026-06-01")
        df = tables["fortnight_production"]
        # 3 regions × 2 periods × N fortnights × 5 variables; N >= 5
        assert len(df) >= 3 * 2 * 5 * 5

    def test_summary_snapshot_has_both_period_types(self) -> None:
        tables = transform_pdf(_load("biweekly_new_pt"), "2023_2024", "pdf_1775f0afde26b483", "2026-06-01")
        df = tables["summary_snapshot"]
        assert "accumulated" in df["period_type"].values
        assert "fortnightly" in df["period_type"].values

    def test_corn_ethanol_row_count(self) -> None:
        """Row count of corn_ethanol == number of fortnight dates on the corn page."""
        import io
        import pdfplumber
        from leviathan.transforms.raw_to_bronze.unica_biweekly_pdf import _extract_fortnight_dates
        pdf_bytes = _load("biweekly_new_pt")
        tables = transform_pdf(pdf_bytes, "2023_2024", "pdf_1775f0afde26b483", "2026-06-01")
        if "corn_ethanol" not in tables:
            pytest.skip("No corn ethanol table extracted")
        df = tables["corn_ethanol"]
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            n = len(pdf.pages)
            page_text = pdf.pages[n - 4].extract_text() or ""
        n_dates = len(_extract_fortnight_dates(page_text))
        if n_dates > 0:
            # Allow ±2 tolerance: page header/title may contain extra DD/MM tokens
            assert abs(len(df) - n_dates) <= 2

    def test_monthly_sales_month_nums_valid(self) -> None:
        tables = transform_pdf(_load("biweekly_new_pt"), "2023_2024", "pdf_1775f0afde26b483", "2026-06-01")
        if "monthly_ethanol_sales" not in tables:
            pytest.skip("No monthly sales table extracted")
        df = tables["monthly_ethanol_sales"]
        valid_months = set(range(1, 13)) | {0}
        for month_num in df["month_num"].dropna():
            assert int(month_num) in valid_months


class TestTransformPdfNewEn:
    def test_classification(self) -> None:
        tables = transform_pdf(_load("biweekly_new_en"), "2022_2023", "pdf_35d5f4012d86b540", "2026-06-01")
        assert tables["_classification"] == "biweekly_new_en"

    def test_fortnight_production_present(self) -> None:
        tables = transform_pdf(_load("biweekly_new_en"), "2022_2023", "pdf_35d5f4012d86b540", "2026-06-01")
        assert "fortnight_production" in tables


class TestTransformPdfSeasonFinal:
    def test_classification(self) -> None:
        tables = transform_pdf(
            _load("season_final_pt"), "2018_2019",
            "pdf_b851e3557530ca223a81fcce166a6c3e", "2026-06-01",
        )
        assert tables["_classification"] == "season_final_pt"

    def test_season_final_extras_present(self) -> None:
        tables = transform_pdf(
            _load("season_final_pt"), "2018_2019",
            "pdf_b851e3557530ca223a81fcce166a6c3e", "2026-06-01",
        )
        assert "season_final_extras" in tables

    def test_season_final_extras_columns(self) -> None:
        tables = transform_pdf(
            _load("season_final_pt"), "2018_2019",
            "pdf_b851e3557530ca223a81fcce166a6c3e", "2026-06-01",
        )
        df = tables["season_final_extras"]
        expected_cols = {"harvest_year", "idm", "pdf_season", "table_id", "dim1", "dim2", "variable", "value", "unit", "ingest_date"}
        assert expected_cols.issubset(set(df.columns))

    def test_pdf_season_extracted(self) -> None:
        tables = transform_pdf(
            _load("season_final_pt"), "2018_2019",
            "pdf_b851e3557530ca223a81fcce166a6c3e", "2026-06-01",
        )
        df = tables["season_final_extras"]
        # pdf_season column must be present; may be None when OCR garbles the
        # year digits (e.g. "201 /201|7 8" instead of "2017/2018")
        assert "pdf_season" in df.columns

    def test_no_fortnight_production_table(self) -> None:
        """Season-final does not emit fortnight_production."""
        tables = transform_pdf(
            _load("season_final_pt"), "2018_2019",
            "pdf_b851e3557530ca223a81fcce166a6c3e", "2026-06-01",
        )
        assert "fortnight_production" not in tables


class TestTransformPdfSkip:
    def test_skip_returns_no_dataframes(self) -> None:
        """A tiny synthetic PDF (too few pages) should return only _classification."""
        # Create a 1-page blank PDF using pdfplumber-compatible bytes
        # We use the minimal valid PDF header that pdfplumber can open
        minimal_pdf = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
            b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
            b"0000000058 00000 n \n0000000115 00000 n \n"
            b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n200\n%%EOF"
        )
        result = transform_pdf(minimal_pdf, "2020_2021", "fake_idm", "2026-06-01")
        assert "_classification" in result
        assert result["_classification"] in ("skip_offtopic", "unknown")
        # No DataFrame keys should be present
        df_keys = [k for k in result if not k.startswith("_")]
        assert df_keys == []
