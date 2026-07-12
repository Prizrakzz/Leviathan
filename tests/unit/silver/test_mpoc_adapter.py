"""SILVER-F052: the shared MPOC source/versioning + HTML-normalization adapter.

Pure Python -- no S3/AWS. Covers source-page versioning (append-only, dedup on content hash),
source-faithful table parsing + identity, country/oil-type/number/month normalization, and the
layout drift diagnostics.
"""
from __future__ import annotations

import pytest

from leviathan.silver.mpoc.adapter import (
    diagnose_table_drift,
    find_table,
    merge_version_log,
    normalize_country,
    normalize_oil_type,
    parse_month,
    parse_number,
    parse_tables,
    version_page,
)


# --------------------------------------------------------------------------- versioning
class TestSourceVersioning:
    def test_content_hash_stable(self):
        a = version_page(html=b"<p>x</p>", release_type="sc", source_url="u", as_of_date="2026-05-01")
        b = version_page(html=b"<p>x</p>", release_type="sc", source_url="u", as_of_date="2026-06-01")
        assert a.content_sha256 == b.content_sha256  # same bytes -> same hash

    def test_bad_as_of_rejected(self):
        with pytest.raises(ValueError):
            version_page(html=b"x", release_type="sc", source_url="u", as_of_date="05/2026")

    def test_merge_is_append_only_dedup_on_content(self):
        v1 = version_page(html=b"A", release_type="sc", source_url="u", as_of_date="2026-05-01")
        v1b = version_page(html=b"A", release_type="sc", source_url="u", as_of_date="2026-06-01")
        v2 = version_page(html=b"B", release_type="sc", source_url="u", as_of_date="2026-06-01")
        log = merge_version_log([], [v1, v1b, v2])
        assert len(log) == 2                                   # v1b (same content as v1) dropped
        # prior evidence survives when a newer version is added later
        log2 = merge_version_log(log, [v2])
        assert len(log2) == 2 and log2[0]["content_sha256"] == v1.content_sha256

    def test_different_release_type_not_deduped(self):
        a = version_page(html=b"A", release_type="sc", source_url="u", as_of_date="2026-05-01")
        b = version_page(html=b"A", release_type="cp", source_url="u", as_of_date="2026-05-01")
        assert len(merge_version_log([], [a, b])) == 2


# --------------------------------------------------------------------------- table parsing
_HTML = """
<h3>Exports to Major Countries</h3>
<table><tr><th>Country</th><th>2023</th></tr>
<tr><td>China</td><td>2,500,000</td></tr></table>
<h3>Monthly Palm Oil Exports</h3>
<table><caption>Monthly totals</caption><tr><th>Month</th><th>Exports</th></tr>
<tr><td>Jan</td><td>1,000</td></tr></table>
"""


class TestParseTables:
    def test_two_tables_with_identity(self):
        tables = parse_tables(_HTML)
        assert len(tables) == 2
        assert "exports to major countries" in tables[0].identity.lower()
        assert tables[0].header == ("Country", "2023")

    def test_caption_is_identity(self):
        tables = parse_tables(_HTML)
        assert tables[1].caption == "Monthly totals"

    def test_find_table_by_identity(self):
        tables = parse_tables(_HTML)
        t = find_table(tables, "monthly")
        assert t is not None and t.header[0] == "Month"

    def test_nbsp_collapsed(self):
        t = parse_tables("<table><tr><td>a  b</td></tr></table>")[0]
        assert t.header == ("a b",)


# --------------------------------------------------------------------------- normalization
class TestNormalization:
    @pytest.mark.parametrize("raw,expect", [
        ("China", "china"), ("P.R. China", "china"), ("U.S.A.", "usa"),
        ("European Union", "eu"), ("Viet Nam", "vietnam"), ("Turkiye", "turkey"),
        ("Unknownland", None), ("", None),
    ])
    def test_country(self, raw, expect):
        assert normalize_country(raw) == expect

    @pytest.mark.parametrize("raw,expect", [
        ("Palm", "palm_oil"), ("Crude Palm Oil", "palm_oil"), ("SBO", "soybean_oil"),
        ("Soyabean Oil", "soybean_oil"), ("Sunflower", "sunflower_oil"),
        ("Rapeseed", "rapeseed_oil"), ("Canola", "rapeseed_oil"), ("mystery", None),
    ])
    def test_oil_type(self, raw, expect):
        assert normalize_oil_type(raw) == expect

    @pytest.mark.parametrize("raw,expect", [
        ("1,234,567", 1234567.0), ("  12.5 ", 12.5), ("(500)", -500.0),
        ("n.a.", None), ("-", None), ("", None), ("2,500 tonnes", 2500.0),
    ])
    def test_number(self, raw, expect):
        assert parse_number(raw) == expect

    @pytest.mark.parametrize("raw,expect", [
        ("Jan", 1), ("JANUARY", 1), ("Dec", 12), ("03", 3), ("13", None), ("foo", None),
    ])
    def test_month(self, raw, expect):
        assert parse_month(raw) == expect


# --------------------------------------------------------------------------- drift diagnostics
class TestDrift:
    def test_missing_table(self):
        d = diagnose_table_drift(None, expected_identity_substr="stock")
        assert d and d[0].kind == "missing_table"

    def test_identity_changed(self):
        t = parse_tables("<h3>Something Else</h3><table><tr><th>Country</th></tr></table>")[0]
        d = diagnose_table_drift(t, expected_identity_substr="ending stocks",
                                 expected_columns=["Country"])
        assert any(f.kind == "identity_changed" for f in d)

    def test_missing_column(self):
        t = parse_tables("<h3>Ending Stocks</h3><table><tr><th>Region</th></tr></table>")[0]
        d = diagnose_table_drift(t, expected_identity_substr="ending stocks",
                                 expected_columns=["Country"])
        assert any(f.kind == "missing_column" for f in d)

    def test_clean_layout_no_findings(self):
        t = parse_tables("<h3>Ending Stocks</h3><table><tr><th>Country</th><th>Nov 2024</th></tr></table>")[0]
        assert diagnose_table_drift(t, expected_identity_substr="ending stocks",
                                    expected_columns=["Country"]) == []
