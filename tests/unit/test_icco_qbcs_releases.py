"""DATA REPAIRS ICCO-1..4 (2026-09-29): the QBCS page parser and ``silver_icco_cocoa_releases``.

Every pin reads a TRIMMED EXCERPT of a page the estate captured (tests/fixtures/icco/qbcs_excerpt_*;
title, canonical link, publication stamp, intro paragraph, the table and its footnotes -- each proven
to parse to the SAME record as its full page when it was cut), or the two whole August pages already
in the fixtures.  No network, no S3.

WHAT BREAKS WITHOUT THEM
------------------------
* ICCO-2(a): a sign followed by a NO-BREAK SPACE (``+\\xa075``) parsed to nothing and the positional
  rule then shifted every value one column left -- the Feb-2026 +75 surplus was lost.
* ICCO-2(b): the ``prior`` column was the SAME season's previous estimate under the PRIOR season's
  name; season A's own revised column was never read -- the root of ICCO-1.
* ICCO-2(d) + N-2: the publisher mislabelled its own header on May-2023 (both seasons) and Aug-2023
  (season A); the release chain overrules the header.
* ICCO-3: the served row mixed May-2015 production with a Feb-2015 surplus.
* ICCO-4: one row per season hid what was known earlier; the releases table keeps every statement.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.icco_cocoa import (
    RELEASES_ARROW_TYPES,
    RELEASES_COLUMNS,
    SILVER_COLUMNS,
    PageInput,
    build_icco_releases,
    build_icco_silver,
)
from leviathan.transforms.raw_to_bronze import icco_cocoa as qp

_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "icco"
_KEY = "raw/production/source=icco_qbcs_summary/release_date={d}/{leaf}"


def _page(date: str, leaf: str = "page.html", *, name: str | None = None, body: bytes | None = None,
          folder: str | None = None) -> PageInput:
    """A banked page as the silver task reads it: its key, its bytes, its release_date= folder."""
    data = body if body is not None else (_FIXTURES / (name or f"qbcs_excerpt_{date}.html")).read_bytes()
    folder = folder or date
    return PageInput(key=_KEY.format(d=folder, leaf=leaf), body=data, folder_release_date=folder)


def _parse(date: str) -> qp.ParsedPage:
    return qp.parse_qbcs_page((_FIXTURES / f"qbcs_excerpt_{date}.html").read_bytes())


# ---------------------------------------------------------------------------
# The figure: every space separator after a sign, every minus
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("+\xa075", 75.0),             # Feb-2026 surplus -- lost at HEAD
    ("\u2212\xa0492", -492.0),     # MINUS SIGN + NBSP
    ("+\xa0 14", 14.0),            # May-2015 2013/14 -- NBSP and a space
    ("\u2013\xa0 193", -193.0),    # EN DASH + NBSP (May-2014)
    ("+ 49", 49.0),                  # ASCII space (HEAD parsed this one)
    ("- 478", -478.0),
    ("+\u2009366", 366.0),           # THIN SPACE
    ("4\xa0362", 4362.0),          # NBSP thousands separator
    ("4,780", 4780.0),               # comma thousands
    ("1 300", 1300.0),
    ("26.4%", 26.4),
    ("+18.1%", 18.1),
    ("\u2014", None),                # EM DASH alone: "not applicable"
    ("", None),
    ("(thousand tonnes)", None),
])
def test_parse_figure(text, expected):
    assert qp.parse_figure(text) == expected


def test_the_feb_2026_surplus_is_read_with_its_sign():
    """ICCO-2(a): the page prints ``+\\xa075``; HEAD stored no surplus for this release."""
    page = _parse("2026-02-27")
    own = [c for c in page.columns if not c.restated]
    assert [(c.header_season, c.values["surplus_deficit_kt"]) for c in own] == [("2024/25", 75.0)]


# ---------------------------------------------------------------------------
# Column mapping by header cells (colspan AND rowspan), one layout per pin (T-ICCO-2)
# ---------------------------------------------------------------------------
def _layout(page):
    return [(c.header_season, c.kind_text, c.restated) for c in page.columns]


def test_layout_february_prev_revised_then_forecast():
    assert _layout(_parse("2016-02-26")) == [
        ("2014/15", "previous estimates", True), ("2014/15", "revised estimates", False),
        ("2015/16", "forecasts", False)]


def test_layout_may_revised_then_prev_and_revised_forecast():
    assert _layout(_parse("2016-05-31")) == [
        ("2014/15", "revised estimates", False), ("2015/16", "previous forecasts", True),
        ("2015/16", "revised forecasts", False)]


def test_layout_november_2025_kind_folded_into_the_season_cell():
    """The 2025-11-28 header prints "2024/25 Revised estimates" in ONE cell spanning two rows."""
    assert _layout(_parse("2025-11-28")) == [
        ("2023/24", "previous estimates", True), ("2023/24", "revised estimates", False),
        ("2024/25", "revised estimates", False)]


def test_layout_2026_estimates_a_then_prev_and_revised():
    """The 2026 layout: the label cell spans three rows and 2023/24 is printed ONLY as a restatement."""
    assert _layout(_parse("2026-05-29")) == [
        ("2023/24", "estimates", True), ("2024/25", "previous estimates", True),
        ("2024/25", "revised estimates", False)]


def test_the_ratio_row_is_read():
    """N-4: the positional parser matched "grindings" inside "Stocks/Grindings ratio" and skipped it."""
    col = [c for c in _parse("2026-05-29").columns if not c.restated][0]
    assert col.values["stocks_to_grindings_pct"] == 28.5


def test_an_undeclared_row_with_figures_fails_the_page_closed():
    html = """<html><head><title>May 2024 Quarterly Bulletin of Cocoa Statistics</title></head>
      <body><div class="entry-content"><p>Abidjan, 31 May 2024 - The ICCO today releases its revised
      forecasts for the 2023/24 cocoa year. Issue No. 2 - Volume L.</p>
      <table><tr><td>Cocoa year</td><td>2023/24</td></tr><tr><td></td><td>Revised forecasts</td></tr>
      <tr><td>World production</td><td>4 449</td></tr><tr><td>World grindings</td><td>4 852</td></tr>
      <tr><td>Something new</td><td>12</td></tr></table></div></body></html>"""
    page = qp.parse_qbcs_page(html)
    assert page.failure and "undeclared label" in page.failure


# ---------------------------------------------------------------------------
# Identity and release date (T-ICCO-5)
# ---------------------------------------------------------------------------
def test_the_august_2017_page_is_dated_by_its_own_identity_not_its_url():
    """N-3: captured from the November-2019 URL (the canonical link says so), the page is Vol. XLIII
    No. 3, titled August 2017, dated 31 August 2017."""
    page = _parse("2017-08-31")
    assert "november-2019" in page.source_url
    assert (page.bulletin_volume, page.bulletin_issue, page.title_month, page.title_year) == ("XLIII", 3, "august", 2017)
    assert (page.release_date, page.release_date_source) == ("2017-08-31", "dateline")


def test_a_page_with_no_dateline_is_dated_by_its_stamp():
    page = _parse("2008-02-28")
    assert (page.release_date, page.release_date_source) == ("2008-02-28", "publication_stamp")


def test_a_page_with_neither_takes_the_month_end_rung_and_says_so():
    html = """<html><head><title>May 2024 Quarterly Bulletin of Cocoa Statistics</title></head>
      <body><div class="entry-content"><p>The ICCO today releases its revised forecasts for the
      2023/24 cocoa year. Issue No. 2 - Volume L.</p></div></body></html>"""
    page = qp.parse_qbcs_page(html)
    assert (page.release_date, page.release_date_source) == ("2024-05-31", "bulletin_month_fallback")


def test_the_intro_statement_stops_at_the_identity_statement():
    """After "Issue No. 1 - Volume LII" the paragraph names the BULLETIN's cocoa year (2025/26), which
    in 2025-26 is not a data season; only the text before it is the release's statement."""
    assert _parse("2026-02-27").statement_seasons == ["2024/25"]
    assert _parse("2016-05-31").statement_seasons == ["2015/16", "2014/15"]


# ---------------------------------------------------------------------------
# The releases table
# ---------------------------------------------------------------------------
_PATH_2015_16 = ["2016-02-26", "2016-05-31", "2017-02-28", "2017-05-31", "2017-08-31"]


@pytest.fixture(scope="module")
def path_2015_16():
    return build_icco_releases([_page(d) for d in _PATH_2015_16])


def test_the_2015_16_path_reads_forecast_revision_final(path_2015_16):
    """T-ICCO-4 over the captured pages: forecast -> revised forecast -> revised estimates."""
    rel, _ = path_2015_16
    got = [(r.release_date, r.figure_kind, r.production_kt, r.surplus_deficit_kt)
           for r in rel[rel.cocoa_year == "2015/16"].itertuples()]
    assert got == [("2016-02-26", "forecast", 4154.0, -113.0), ("2016-05-31", "revised_forecast", 4039.0, -180.0),
                   ("2017-02-28", "revised_estimate", 3965.0, -196.0), ("2017-05-31", "revised_estimate", 3972.0, -197.0),
                   ("2017-08-31", "revised_estimate", 3981.0, -187.0)]


def test_season_a_s_own_revision_is_a_row(path_2015_16):
    """ICCO-2(b) / ICCO-1: May-2016 column 1 is 2014/15's revised estimate 4,233 -- never read at HEAD."""
    rel, _ = path_2015_16
    row = rel[(rel.release_date == "2016-05-31") & (rel.cocoa_year == "2014/15")].iloc[0]
    assert (row.production_kt, row.figure_kind, row.surplus_deficit_kt) == (4233.0, "revised_estimate", 46.0)


def test_a_restated_column_is_never_a_row(path_2015_16):
    """The a/ column (Feb-2016's "Previous estimates a/" 4,201) is a chain witness, not a statement."""
    rel, _ = path_2015_16
    assert 4201.0 not in set(rel.production_kt)
    assert len(rel) == 2 * len(_PATH_2015_16)


def test_the_silver_carries_each_season_s_latest_whole_row(path_2015_16):
    """ICCO-1: the closed season carries its final captured revision (Aug-2017 3,981/-187), not the
    May-2016 forecast the served table holds (4,039/-180)."""
    rel, _ = path_2015_16
    silver = build_icco_silver(rel).set_index("cocoa_year")
    assert silver.at["2015/16", "production_kt"] == 3981.0
    assert silver.at["2015/16", "surplus_deficit_kt"] == -187.0
    assert silver.at["2015/16", "latest_release_date"] == "2017-08-31"


def test_every_row_carries_its_known_date_and_its_evidence(path_2015_16):
    rel, _ = path_2015_16
    assert list(rel.columns) == RELEASES_COLUMNS
    assert rel.release_date.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()
    assert rel.page_sha256.str.len().eq(64).all()
    assert (rel.parse_version == qp.PARSE_VERSION).all()
    assert rel.page_key.str.contains("release_date=").all()
    assert not rel.duplicated(["release_date", "cocoa_year"]).any()


@pytest.fixture(scope="module")
def year_2023():
    return build_icco_releases([_page(d) for d in ("2023-02-28", "2023-05-31", "2023-08-31", "2023-11-30")])


def test_the_mislabelled_may_2023_header_is_overruled_by_the_chain(year_2023):
    """ICCO-2(d): the May-2023 header prints 2020/2021 | 2021/2022; its "previous forecasts a/"
    column equals Feb-2023's OWN 2022/23 forecast, and its intro paragraph says "revised forecasts for
    the 2022/23 cocoa year".  The witnesses win: 4,980 is 2022/23, 4,818 is 2021/22."""
    rel, log = year_2023
    may = rel[rel.release_date == "2023-05-31"].set_index("cocoa_year")
    assert may.at["2022/23", "production_kt"] == 4980.0 and may.at["2022/23", "header_season"] == "2021/22"
    assert may.at["2021/22", "production_kt"] == 4818.0 and may.at["2021/22", "header_season"] == "2020/21"
    assert "chain" in may.at["2022/23", "season_witnesses"]
    assert {o["release"] for o in log["header_overruled"]} >= {"Vol. XLIX No. 2 (2023-05-31)"}


def test_the_mislabelled_august_2023_season_a_is_overruled(year_2023):
    """N-2: the Aug-2023 header prints season A as 2020/2021; the chain and the intro say 2021/22."""
    rel, log = year_2023
    aug = rel[rel.release_date == "2023-08-31"].set_index("cocoa_year")
    assert aug.at["2021/22", "production_kt"] == 4826.0 and aug.at["2021/22", "header_season"] == "2020/21"
    assert {o["release"] for o in log["header_overruled"]} == {"Vol. XLIX No. 2 (2023-05-31)",
                                                              "Vol. XLIX No. 3 (2023-08-31)"}


def test_no_witness_is_missing_never_a_guess():
    """A page whose header no witness confirms writes its rows MISSING with the reason (T-ICCO-1)."""
    html = (_FIXTURES / "qbcs_excerpt_2016-05-31.html").read_text(encoding="utf-8")
    html = html.replace("for the current 2015/2016 cocoa year", "for the current 2019/2020 cocoa year")
    rel, log = build_icco_releases([_page("2016-05-31", body=html.encode("utf-8"))])
    assert rel.missing_reason.str.startswith("season_unconfirmed").all()
    assert rel.production_kt.isna().all()
    assert log["unconfirmed_releases"]
    with pytest.raises(ValueError, match="no stated row"):
        build_icco_silver(rel)


def test_the_august_2026_withheld_season_is_a_missing_row():
    """T-ICCO-7: the Secretariat withheld 2025/26 in Aug-2026 -- a row, every figure MISSING, known at
    the release date; the stated season is 2024/25 (+37)."""
    rel, _ = build_icco_releases([_page("2026-08-31", name="qbcs_2026-08-31_page.html")])
    got = rel.set_index("cocoa_year")
    assert got.at["2025/26", "missing_reason"] == "withheld" and pd.isna(got.at["2025/26", "production_kt"])
    assert got.at["2024/25", "surplus_deficit_kt"] == 37.0
    assert set(rel.release_date) == {"2026-08-31"}


def test_one_bulletin_filed_twice_is_one_release():
    """T-ICCO-6: the Aug-2025 bulletin sits in folder 2025-08-31 while its dateline is 2025-08-29; a
    re-fetch files it at 2025-08-29.  One identity, one release -- the folder that agrees with the
    dateline -- and the duplicate is listed."""
    pages = [_page("2025-08-31", name="qbcs_2025-08-31_page.html"),
             _page("2025-08-29", name="qbcs_2025-08-31_page.html")]
    rel, log = build_icco_releases(pages)
    assert set(rel.release_date) == {"2025-08-29"}
    assert rel.page_key.str.contains("release_date=2025-08-29/").all()
    assert len(log["duplicate_captures"]) == 1 and log["duplicate_captures"][0]["same_statement"] is True


def test_a_restatement_that_does_not_match_the_bulletin_it_cites_is_listed():
    """T-ICCO-3: Feb-2026's "Previous estimates a/" 2024/25 grindings print 4,604 where Nov-2025 printed
    4,602 -- listed, and the season still confirmed by the header and the intro statement."""
    rel, log = build_icco_releases([_page("2025-11-28"), _page("2026-02-27")])
    feb = rel[rel.release_date == "2026-02-27"].set_index("cocoa_year")
    assert list(feb.index) == ["2024/25"] and feb.at["2024/25", "surplus_deficit_kt"] == 75.0
    assert {(m["release"], m["header_season"]) for m in log["chain_mismatches"]} >= {
        ("Vol. LII No. 1 (2026-02-27)", "2024/25"), ("Vol. LII No. 1 (2026-02-27)", "2023/24")}
    assert {"release_date": "2026-02-27", "cocoa_year": "2023/24"} in log["restated_only"]


def test_the_identity_is_checked_and_a_failure_is_flagged_not_dropped():
    """T-ICCO-8: May-2021 prints 2019/20 production 4,728, grindings 4,671 and a surplus of -10, where
    0.99 x 4,728 - 4,671 = +9.7 -- the row is kept and flagged.  May-2021 does not itself state the
    weight-loss share, so a bulletin that does (Feb-2023, "1% loss in weight") is read beside it."""
    rel, log = build_icco_releases([_page("2021-05-31"), _page("2023-02-28")])
    row = rel[(rel.release_date == "2021-05-31") & (rel.cocoa_year == "2019/20")].iloc[0]
    assert row.weight_loss_source == "stated_in_other_bulletins"
    assert row.identity_status == "exceeds_rounding" and row.identity_gap_kt == pytest.approx(19.72)
    assert row.production_kt == 4728.0
    assert log["identity_exceeds_rounding"] == [{"release_date": "2021-05-31", "cocoa_year": "2019/20",
                                                 "gap_kt": 19.72}]


def test_the_weight_loss_is_the_one_the_bulletins_state():
    """Footnote b/ states "1% loss in weight" on four bulletins; a page that states it uses its own, a
    page that does not borrows the one value every stating bulletin agrees on, and SAYS so."""
    rel, _ = build_icco_releases([_page("2023-02-28"), _page("2023-05-31")])
    by = rel.drop_duplicates("release_date").set_index("release_date")
    assert (by.at["2023-02-28", "weight_loss_pct"], by.at["2023-02-28", "weight_loss_source"]) == (1.0, "stated_on_page")
    assert (by.at["2023-05-31", "weight_loss_pct"], by.at["2023-05-31", "weight_loss_source"]) == (1.0, "stated_in_other_bulletins")
    alone, _ = build_icco_releases([_page("2023-05-31")])
    assert set(alone.weight_loss_source) == {"not_stated"} and set(alone.identity_status) == {"not_computable"}


def test_the_may_2015_row_is_one_release_not_two():
    """ICCO-3: the served 2014/15 row spliced the May-2015 production (4,168) onto the Feb-2015 surplus
    (-17) because May-2015's "\u2013 38" was lost.  Whole rows only: the May-2015 row carries -38."""
    rel, _ = build_icco_releases([_page("2015-02-27"), _page("2015-05-29")])
    silver = build_icco_silver(rel).set_index("cocoa_year")
    assert (silver.at["2014/15", "production_kt"], silver.at["2014/15", "surplus_deficit_kt"]) == (4168.0, -38.0)
    assert abs(4168.0 * 0.99 - silver.at["2014/15", "grindings_kt"] - silver.at["2014/15", "surplus_deficit_kt"]) <= 3


# ---------------------------------------------------------------------------
# The served table from the releases table (shape unchanged; T-ICCO-9)
# ---------------------------------------------------------------------------
def _release_row(release_date, cocoa_year, prod, grind, stocks, surplus, *, source="dateline",
                 volume="L", issue=1, missing=None):
    row = {c: None for c in RELEASES_COLUMNS}
    row.update(release_date=release_date, release_date_source=source, bulletin_volume=volume,
               bulletin_issue=issue, cocoa_year=cocoa_year, production_kt=prod, grindings_kt=grind,
               end_stocks_kt=stocks, surplus_deficit_kt=surplus, missing_reason=missing)
    return row


def test_a_metric_the_latest_release_does_not_print_stays_missing():
    """T-ICCO-9: the latest release's row is taken WHOLE -- a metric it does not print is MISSING, never
    borrowed from an older release (the mechanism of ICCO-3)."""
    rel = pd.DataFrame([_release_row("2015-02-27", "2014/15", 4232.0, 4207.0, 1609.0, -17.0, issue=1),
                        _release_row("2015-05-29", "2014/15", 4168.0, 4164.0, 1570.0, None, issue=2)])
    row = build_icco_silver(rel).iloc[0]
    assert row.latest_release_date == "2015-05-29" and row.production_kt == 4168.0
    assert pd.isna(row.surplus_deficit_kt)


def test_a_withheld_row_never_wins_and_a_fallback_date_never_beats_a_dateline():
    rel = pd.DataFrame([
        _release_row("2026-05-29", "2024/25", 4723.0, 4628.0, 1320.0, 48.0, issue=2),
        _release_row("2026-08-31", "2024/25", None, None, None, None, issue=3, missing="withheld"),
        _release_row("2026-06-30", "2024/25", 1.0, 1.0, 1.0, 1.0, source="bulletin_month_fallback", issue=4),
    ])
    row = build_icco_silver(rel).iloc[0]
    assert (row.latest_release_date, row.production_kt) == ("2026-05-29", 4723.0)


def test_the_served_shape_is_unchanged():
    rel = pd.DataFrame([_release_row("2012-11-30", "2010/11", 4313.0, 3929.0, 1774.0, 341.0),
                        _release_row("2012-11-30", "2011/12", 4052.0, 3921.0, 1864.0, 90.0)])
    silver = build_icco_silver(rel)
    assert list(silver.columns) == SILVER_COLUMNS
    assert not silver.duplicated("cocoa_year").any()
    assert silver.su_ratio.tolist() == pytest.approx([1774.0 / 3929.0, 1864.0 / 3921.0])


def test_the_declared_writer_types_cover_every_column():
    assert set(RELEASES_ARROW_TYPES) == set(RELEASES_COLUMNS)
    assert RELEASES_ARROW_TYPES["bulletin_issue"] == "int64"
    assert RELEASES_ARROW_TYPES["release_date"] == "string"      # the lexical as-of key


def test_the_registry_contract_matches_the_builder_once_it_is_generated():
    """The contract of silver_icco_cocoa_releases is GENERATED by the integrator (never typed here).
    Once the registry holds it, its physical columns must be exactly the builder's, in writer order,
    with the builder's writer types."""
    from leviathan.silver.registry import load_registry
    reg = load_registry()
    if "silver_icco_cocoa_releases" not in set(reg.names()):
        pytest.skip("silver_icco_cocoa_releases is not in the generated registry yet (integrator step)")
    contract = reg.table("silver_icco_cocoa_releases")
    cols = [(c["name"], c["target_arrow_type"]) for c in contract["physical_columns"]]
    assert [n for n, _ in cols] == RELEASES_COLUMNS
    assert {n: t for n, t in cols} == RELEASES_ARROW_TYPES
    assert contract["natural_key"] == ["release_date", "cocoa_year"]
    assert contract["knowledge_date_col"] == "release_date"
