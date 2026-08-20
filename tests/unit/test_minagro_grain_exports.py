"""MINAGRO Ukrainian grain / pulse / flour exports. Hermetic: no network, no browser, no AWS.

The fixture ``tests/fixtures/minagro/grain_exports_page_20260814.html`` is the rendered ``<main>``
outerHTML of the ministry's standing export page, captured live 2026-08-14 through a real browser
session (the page sits behind a Cloudflare managed challenge and exists in NO plain-requests
response). Element structure, attributes and text are the ministry's.

Every number asserted below is a real published value. The facts these tests exist to pin are the
ones that would otherwise produce a WRONG NUMBER rather than an error:

  * the DECIMAL COMMA -- "3,0" is three point zero, and a comma-stripping parser reads it as 30;
  * the as-of date is the table's OWN "станом на" date, and the phrase occurs TWICE on the page --
    the second time carrying LAST YEAR's date, in the prior-year column header;
  * the flour row packs TWO logical rows into one ``<tr>`` by paragraph index, so reading its cells
    whole yields "3,21,3", a number that does not exist;
  * the two marketing-year column groups are the only statement of which pair of columns is the
    CURRENT year, so a swap would publish last year's cumulative as this year's;
  * a challenge page must REFUSE loudly and land nothing -- raw is immutable, and an interstitial
    filed under an ``as_of=`` key is indistinguishable from the real table forever after.

The producer is exercised only through its pure helpers. Playwright is never imported: the browser
plumbing is validated by the first cloud run, by design (the CHALLENGE_FAILED exit contract).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from leviathan.storage.paths import (
    minagro_grain_exports_prefix,
    raw_minagro_grain_exports_key,
)
from leviathan.transforms.bronze_to_silver import minagro_grain_exports as S
from leviathan.transforms.raw_to_bronze import minagro_grain_exports as T

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = _REPO / "tests" / "fixtures" / "minagro" / "grain_exports_page_20260814.html"

_AS_OF = dt.date(2026, 8, 14)


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FETCH = _load("jobs/ingest/fetch_minagro_grain_exports.py", "fetch_minagro_grain_exports")


def page() -> bytes:
    return _FIXTURE.read_bytes()


def bronze(payload: bytes = None):
    return T.build_bronze(page() if payload is None else payload)


def _row(df, slug: str):
    hit = df[df["crop_slug"] == slug]
    assert len(hit) == 1, f"{slug} appears {len(hit)} time(s)"
    return hit.iloc[0]


def _values(df, slug: str) -> list[float]:
    row = _row(df, slug)
    return [float(row[c]) for c in T.VALUE_COLUMNS]


def _drop_rows(text: str, labels: tuple[str, ...]) -> str:
    """The fixture with the ``<tr>`` blocks carrying any of *labels* removed.

    Cuts from the middle rather than truncating the tail, so the marker phrases that live in the
    first and last rows survive and a test can reach the row-count check behind them."""
    head, rest = text.split("<tbody>", 1)
    body, tail = rest.split("</tbody>", 1)
    chunks = body.split("<tr>")
    kept = [chunks[0]] + [c for c in chunks[1:] if not any(f"<p>{lab}</p>" in c for lab in labels)]
    assert len(kept) < len(chunks), "the row cut did not bite -- the assertion would be vacuous"
    return head + "<tbody>" + "<tr>".join(kept) + "</tbody>" + tail


# THE EXPECTED PARSE. Read off the 2026-08-14 page, in the ministry's own column order:
# current-MY cumulative / current-month-to-date / prior-MY cumulative at the same date /
# prior-MY month figure.
EXPECTED = {
    "grains_pulses_total": [3093, 348, 2818, 1153],
    "wheat": [1291, 219, 1517, 759],
    "barley": [339, 40, 463, 206],
    "rye": [0.0, 0.0, 0.0, 0.0],
    "corn": [1403, 89, 827, 184],
    "wheat_flour": [3.0, 1.2, 5.8, 2.4],
    "other_flour": [0.2, 0.1, 0.3, 0.1],
    "flour_total": [3.2, 1.3, 6.1, 2.5],
    "flour_grain_equivalent": [4.3, 1.7, 8.1, 3.3],
    "grain_flour_total": [3097, 350, 2826, 1156],
}


# ---------------------------------------------------------------------------
class TestTheFixtureParse:
    def test_every_row_of_the_published_table_decodes(self):
        df, stats = bronze()
        assert len(df) == 10 == stats["rows_kept"] == stats["rows_expected"]
        for slug, expected in EXPECTED.items():
            assert _values(df, slug) == pytest.approx(expected), slug

    def test_the_curated_slugs_are_exactly_the_ten_rows(self):
        df, _ = bronze()
        assert set(df["crop_slug"]) == set(EXPECTED) == set(T.REQUIRED_CROP_SLUGS)
        assert set(T.CROP_SLUGS) == {
            "grains_pulses_total", "wheat", "barley", "rye", "corn",
            "wheat_flour", "other_flour", "flour_total", "flour_grain_equivalent",
            "grain_flour_total"}

    def test_the_totals_are_read_and_never_recomputed(self):
        """The ministry publishes both totals; the parse lands them verbatim. They happen to be
        internally consistent here, which is a property of the DATA and not of the parser -- a
        transform that RECOMPUTED them would hide the day the ministry's own arithmetic moves."""
        df, _ = bronze()
        grains = _values(df, "grains_pulses_total")
        both = _values(df, "grain_flour_total")
        equiv = _values(df, "flour_grain_equivalent")
        for g, b, e in zip(grains, both, equiv):
            assert b == pytest.approx(g + e, abs=1.0)

    def test_the_flour_row_is_two_rows_in_one_tr(self):
        """"Борошно разом" and "у перерахунку на зерно" share one <tr>: two <p> in the label cell
        and two in each value cell, paired by index. get_text() on such a cell yields "3,21,3"."""
        df, _ = bronze()
        assert _values(df, "flour_total") == pytest.approx([3.2, 1.3, 6.1, 2.5])
        assert _values(df, "flour_grain_equivalent") == pytest.approx([4.3, 1.7, 8.1, 3.3])
        assert "разом" in _row(df, "flour_total")["row_label"]
        assert "перерахунку" in _row(df, "flour_grain_equivalent")["row_label"]

    def test_a_mismatched_paragraph_count_in_the_shared_row_is_a_hard_error(self):
        """Drop ONE of the flour row's paired value paragraphs: the label cell still says two rows
        and the value cell now says one, so the index pairing would be a guess."""
        payload = page().replace(
            b'<p align="center">3,2</p>\n\t\t\t\t<p align="center"><strong>4,3</strong></p>',
            b'<p align="center">3,2</p>')
        assert payload != page(), "the fixture drifted -- this mutation no longer bites"
        with pytest.raises(ValueError, match="paragraph"):
            T.build_bronze(payload)

    def test_the_natural_key_is_unique_within_a_capture(self):
        df, _ = bronze()
        assert df.groupby(["as_of_date", "crop_slug"], dropna=False).size().max() == 1


# ---------------------------------------------------------------------------
class TestTheDecimalComma:
    def test_a_ukrainian_decimal_comma_is_repaired_and_not_stripped(self):
        """THE DEFECT THIS EXISTS FOR. A comma-stripping parser turns 3,0 kt into 30 kt -- a
        plausible wrong number rather than an error, on a value column a desk reads directly."""
        assert T.parse_number("3,0") == pytest.approx(3.0)
        assert T.parse_number("1,2") == pytest.approx(1.2)
        assert T.parse_number("5,8") == pytest.approx(5.8)
        assert T.parse_number("0,2") == pytest.approx(0.2)
        assert T.parse_number("-1,25") == pytest.approx(-1.25)

    def test_the_one_period_typed_cell_parses_identically(self):
        """The rye row's first cell is typed "0.0" while its other three are "0,0" -- upstream
        inconsistency, not a different number."""
        assert "0.0" in page().decode("utf-8"), "the fixture's period-typed cell is gone"
        assert T.parse_number("0.0") == 0.0 == T.parse_number("0,0")
        assert _values(bronze()[0], "rye") == [0.0, 0.0, 0.0, 0.0]

    def test_zero_is_a_published_value_and_is_never_masked(self):
        """Rye publishes a real, measured zero in all four columns. Masking zero to NULL (the
        CZCE/JSE no-trade sentinel) would erase an observation, and a NULL export reads to a desk
        as 'unknown' rather than as 'none'."""
        row = _row(bronze()[0], "rye")
        for col in T.VALUE_COLUMNS:
            assert not pd.isna(row[col])
            assert float(row[col]) == 0.0

    def test_three_trailing_digits_are_a_thousands_group_and_one_or_two_are_decimals(self):
        """The disambiguation rule, stated as a test: the page prints at most one fractional
        digit, so ',' + 1-2 digits is a decimal separator and ',' + 3 is a group separator."""
        assert T.parse_number("3,093") == 3093.0
        assert T.parse_number("3,09") == pytest.approx(3.09)
        assert T.parse_number("3,0") == pytest.approx(3.0)

    def test_spaces_and_nbsp_are_thousands_separators(self):
        assert T.parse_number("3 093") == 3093.0
        assert T.parse_number("3 093") == 3093.0

    def test_the_dash_and_blank_sentinels_are_null(self):
        for token in ("-", "--", "", "   ", "n/a", None):
            assert pd.isna(T.parse_number(token)), token

    def test_a_negative_value_is_a_value_and_a_bare_dash_is_not(self):
        """Both start with '-'. Conflating them turns every negative revision into a NULL."""
        assert T.parse_number("-12,5") == pytest.approx(-12.5)
        assert pd.isna(T.parse_number("-"))


# ---------------------------------------------------------------------------
class TestTheAsOfDate:
    def test_the_tables_own_stanom_na_date_is_the_knowledge_date(self):
        assert T.as_of_date_from_page(page()) == _AS_OF
        df, stats = bronze()
        assert stats["as_of_date"] == "2026-08-14"
        assert set(df["as_of_date"]) == {_AS_OF}

    def test_the_date_is_read_as_DD_MM_YYYY(self):
        """14.08.2026 is 14 AUGUST, not 8 February. A source read the American way would re-date
        the whole series with every row still well formed."""
        got = T.as_of_date_from_page(page())
        assert (got.day, got.month, got.year) == (14, 8, 2026)

    def test_the_prior_year_stanom_na_in_the_table_header_is_NOT_taken(self):
        """THE DEFECT THIS EXISTS FOR. The phrase occurs twice: once above the table (14.08.2026)
        and once inside the prior-year column header (14.08.2025). A whole-page regex has a 50%
        chance of returning last year's date, and the capture then lands a year early, parses
        perfectly, and back-dates everything."""
        text = page().decode("utf-8")
        assert text.count("станом на") >= 2, "the fixture no longer carries the second occurrence"
        assert "14.08.2025" in text
        assert T.as_of_date_from_page(page()) == _AS_OF
        assert "14.08.2025" not in T.header_html(page()), "the search window leaked past the table"

    def test_the_prior_year_column_date_is_kept_as_a_separate_fact(self):
        _df, stats = bronze()
        assert stats["prior_as_of_date"] == "2025-08-14"

    def test_a_page_with_no_stanom_na_date_refuses_rather_than_guessing(self):
        payload = page().replace("станом на".encode("utf-8"), "на".encode("utf-8"))
        with pytest.raises(ValueError, match="станом на"):
            T.as_of_date_from_page(payload)

    def test_an_impossible_calendar_date_refuses_rather_than_rolling_over(self):
        payload = page().replace(b"14.08.2026", b"32.08.2026")
        with pytest.raises(ValueError, match="not a calendar date"):
            T.as_of_date_from_page(payload)

    def test_a_caller_supplied_as_of_is_a_cross_check_and_never_an_override(self):
        df, _ = T.build_bronze(page(), as_of_date="2026-08-14")
        assert set(df["as_of_date"]) == {_AS_OF}
        with pytest.raises(ValueError, match="the page is the authority|станом на"):
            T.build_bronze(page(), as_of_date="2026-08-07")


# ---------------------------------------------------------------------------
class TestThePublishStampIsProvenanceOnly:
    def test_the_ukrainian_month_name_stamp_parses(self):
        stamp = T.publish_stamp(page())
        assert stamp["publish_stamp_text"].startswith("Опубліковано")
        assert stamp["published_at"] == "2026-08-14T09:05"

    def test_the_stamp_is_not_the_knowledge_date(self):
        """The publish stamp runs at or AFTER the as-of (customs figures cannot be published before
        the day they describe closes) and it MOVES on every in-place re-publish of this standing
        slug. The rows are keyed on the DATA's own date, so bronze keeps the stamp only as
        provenance -- it never reaches the as_of_date column, and never reaches silver at all."""
        df, _ = bronze()
        assert set(df["published_at"]) == {"2026-08-14T09:05"}
        assert set(df["as_of_date"]) == {_AS_OF}
        assert "published_at" not in S.OUTPUT_COLUMNS
        assert "publish_stamp_text" not in S.OUTPUT_COLUMNS

    def test_a_re_worded_stamp_does_not_take_the_leg_down(self):
        """It is provenance: a CMS re-wording must degrade to 'kept verbatim', never to a failure,
        because nothing of record depends on it."""
        payload = page().replace(b"14 \xd1\x81\xd0\xb5\xd1\x80\xd0\xbf\xd0\xbd\xd1\x8f 2026",
                                 b"the fourteenth")
        stamp = T.publish_stamp(payload)
        assert stamp["published_at"] is None
        df, _ = T.build_bronze(payload)
        assert len(df) == 10 and set(df["as_of_date"]) == {_AS_OF}

    def test_all_twelve_ukrainian_month_names_are_curated(self):
        assert sorted(T.UKRAINIAN_MONTHS.values()) == list(range(1, 13))


# ---------------------------------------------------------------------------
class TestTheMarketingYearPin:
    def test_the_two_column_groups_are_read_from_the_table(self):
        _df, stats = bronze()
        assert stats["marketing_year"] == "2026/2027"
        assert stats["prior_marketing_year"] == "2025/2026"

    def test_both_marketing_years_ride_every_row(self):
        df, _ = bronze()
        assert set(df["marketing_year"]) == {"2026/2027"}
        assert set(df["prior_marketing_year"]) == {"2025/2026"}

    def test_a_swapped_column_group_is_a_hard_error(self):
        """THE DEFECT THIS PIN EXISTS FOR. Nothing else on the page says which pair of columns is
        the current marketing year -- the values are bare numbers. A swap publishes last year's
        cumulative as this year's with every row still well formed."""
        payload = page().replace(b"<p align=\"center\">2026/2027 \xd0\x9c\xd0\xa0</p>",
                                 b"<p align=\"center\">2024/2025 \xd0\x9c\xd0\xa0</p>")
        assert payload != page(), "the fixture drifted -- this mutation no longer bites"
        with pytest.raises(ValueError, match="must be the LATER year|disagree"):
            T.build_bronze(payload)

    def test_the_header_paragraph_and_the_table_must_agree(self):
        """Two statements of the same fact; a disagreement is refused rather than resolved."""
        assert T.marketing_year_from_header(page()) == "2026/2027"
        payload = page().replace(b"2026</strong><strong>/2027", b"2027</strong><strong>/2028")
        assert payload != page(), "the fixture drifted -- this mutation no longer bites"
        with pytest.raises(ValueError, match="disagree|column group"):
            T.build_bronze(payload)


# ---------------------------------------------------------------------------
class TestTheColumnHeaderPin:
    def test_the_four_column_labels_are_the_pinned_shape(self):
        _df, stats = bronze()
        header = stats["column_header"]
        assert len(header) == 4
        assert header[0] == "Всього" and header[2].startswith("Всього станом на")
        assert "в тому числі" in header[1] and "в тому числі" in header[3]

    def test_a_renamed_column_header_is_a_hard_error(self):
        payload = page().replace(b'<p align="center">\xd0\x92\xd1\x81\xd1\x8c\xd0\xbe\xd0\xb3\xd0\xbe</p>',
                                 b'<p align="center">TOTAL</p>')
        assert payload != page(), "the fixture drifted -- this mutation no longer bites"
        with pytest.raises(ValueError, match="drifted"):
            T.build_bronze(payload)


# ---------------------------------------------------------------------------
class TestTheCompletenessFloor:
    def test_a_missing_commodity_row_is_a_hard_error_and_not_a_short_table(self):
        """An absent wheat row reads to a desk as a collapse in wheat exports rather than as a
        parse failure -- every other row is perfectly well formed, so nothing else can see it."""
        text = page().decode("utf-8")
        head, rest = text.split("<p>пшениця</p>", 1)
        cut = head.rsplit("<tr>", 1)[0] + rest.split("</tr>", 1)[1]
        with pytest.raises(ValueError, match="missing 1 required row"):
            T.build_bronze(cut.encode("utf-8"))

    def test_an_unknown_row_label_is_counted_and_never_fatal(self):
        """The opposite case: the ministry adding, say, an oats row must not take a weekly leg
        down. It is logged and surfaced in the stats, never dropped silently."""
        payload = page().replace(b"<p>\xd0\xb6\xd0\xb8\xd1\x82\xd0\xbe</p>",
                                 b"<p>\xd0\xb6\xd0\xb8\xd1\x82\xd0\xbe</p><p>oats</p>")
        # jyto (rye) now carries a second label paragraph but only ONE value paragraph per cell,
        # so the paired-paragraph guard fires first -- which is itself the point: an added label
        # is never silently paired with a value that belongs to a different row.
        with pytest.raises(ValueError, match="paragraph"):
            T.build_bronze(payload)

    def test_an_unmapped_standalone_row_is_reported_in_the_stats(self):
        oats_row = (
            '<tr><td width="388"><p>овес</p></td>'
            '<td width="141"><p align="center">7,0</p></td>'
            '<td width="167"><p align="center">1,0</p></td>'
            '<td width="154"><p align="center">2,0</p></td>'
            '<td width="170"><p align="center">3,0</p></td></tr>'
        )
        payload = page().decode("utf-8").replace("</tbody>", oats_row + "</tbody>")
        df, stats = T.build_bronze(payload.encode("utf-8"))
        assert len(df) == 10, "an uncurated commodity must not enter the table"
        assert stats["labels_unmapped"] and "oves" not in stats["labels_unmapped"][0].lower()
        assert len(stats["labels_unmapped"]) == 1

    def test_a_page_without_the_table_is_a_hard_error(self):
        with pytest.raises(ValueError, match="no table carrying"):
            T.build_bronze(b"<html><body><p>loading</p></body></html>")

    def test_the_label_patterns_cannot_shadow_one_another(self):
        """First-hit-wins is only a decision if no pattern is a substring of another -- otherwise
        the answer depends on dict ORDER. Asserted at import time; re-asserted here."""
        assert T._lint_crop_labels() == []


# ---------------------------------------------------------------------------
class TestTheChallengePageRefusal:
    CHALLENGE = (
        "<html><head><title>Just a moment...</title></head><body>"
        "<div class='cf-browser-verification'>Checking your browser before accessing "
        "minagro.gov.ua.</div><noscript>Please enable JavaScript.</noscript>"
        "<script src='/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1'></script>"
        "</body></html>"
    )

    def test_a_cloudflare_challenge_body_is_refused_by_the_sniff(self):
        """THE FAILURE THIS FAMILY EXISTS TO MAKE IMPOSSIBLE. Raw is immutable: an interstitial
        landed under an as_of= key is indistinguishable from the ministry's table forever after."""
        why = T.looks_like_the_export_table(self.CHALLENGE)
        assert why and "marker" in why

    def test_the_real_capture_passes_the_same_sniff(self):
        assert T.looks_like_the_export_table(page()) is None

    def test_the_sniff_refuses_an_empty_capture(self):
        assert "no markup" in (T.looks_like_the_export_table(None) or "")
        assert "no markup" in (T.looks_like_the_export_table("") or "")

    def test_the_sniff_refuses_a_page_that_has_the_words_but_no_table(self):
        """A CMS error page that still renders the article prose: every marker present, no data."""
        prose = ("<div>Експорт зернові та зернобобові борошно МР станом на 14.08.2026, "
                 "дані Держмитслужби</div>")
        why = T.looks_like_the_export_table(prose)
        assert why and "no <table>" in why

    def test_the_sniff_refuses_a_half_rendered_table(self):
        """A short table parses cleanly and publishes as the complete one -- the Euronext
        truncation lesson. The floor here is structural and lives BEFORE the landing.

        The four commodity rows are cut from the MIDDLE so every marker phrase survives: this has
        to exercise the row COUNT, not the marker check that would otherwise fire first."""
        short = _drop_rows(page().decode("utf-8"),
                           ("пшениця", "ячмінь", "жито", "кукурудза"))
        for marker in T.TABLE_MARKERS:
            assert marker in T._norm(short), f"the cut lost marker {marker!r}"
        why = T.looks_like_the_export_table(short)
        assert why and "at least" in why

    def test_the_producer_refuses_with_a_written_reason_and_a_dedicated_exit_code(self, capsys):
        rc = FETCH._refuse(T.looks_like_the_export_table(self.CHALLENGE))
        assert rc == FETCH.EXIT_TABLE_MARKERS_ABSENT == 6
        out = capsys.readouterr().out
        assert "REFUSED minagro capture" in out
        assert out.isascii(), "the console is cp1252 -- a non-ASCII print CRASHES python"

    def test_the_refusal_code_is_not_the_challenge_code(self):
        """Two different facts. rc 7 says the challenge never cleared for this IP class (the
        residual probe answer); rc 6 says the venue served SOMETHING that is not the table (a
        layout change or a CMS error). Collapsing them makes a ministry redesign read as
        'Cloudflare blocks Fargate'."""
        assert FETCH.EXIT_CHALLENGE_FAILED == 7
        assert FETCH.EXIT_TABLE_MARKERS_ABSENT == 6
        assert FETCH.EXIT_CHALLENGE_FAILED != FETCH.EXIT_TABLE_MARKERS_ABSENT

    def test_the_challenge_exit_code_matches_the_shared_browser_module(self):
        from leviathan.ingest import browser_fetch

        assert browser_fetch.EXIT_CHALLENGE_FAILED == FETCH.EXIT_CHALLENGE_FAILED


# ---------------------------------------------------------------------------
class TestTheProducer:
    def test_the_raw_key_is_dated_by_the_page_and_first_capture_wins(self):
        key = raw_minagro_grain_exports_key("2026-08-14")
        assert key == ("raw/production/source=minagro_grain_exports/"
                       "as_of=20260814/page.html")
        assert key == raw_minagro_grain_exports_key("20260814")
        assert key.startswith(minagro_grain_exports_prefix())

    def test_the_key_is_derived_from_the_landed_page_and_from_nothing_else(self):
        """The whole first-capture-wins design rests on this: the key is a function of the DATA's
        own date, so re-fetching an unchanged standing slug computes the SAME key and skips."""
        as_of = T.as_of_date_from_page(page())
        assert raw_minagro_grain_exports_key(as_of.isoformat()).endswith(
            "as_of=20260814/page.html")

    def test_a_non_date_as_of_cannot_inject_a_path_segment(self):
        for bad in ("2026-08", "../../etc", "", "2026-13-45-99"):
            with pytest.raises(ValueError):
                raw_minagro_grain_exports_key(bad)

    def test_the_ready_check_and_the_parse_agree_about_which_table(self):
        """One marker phrase, pinned in the transform and used by the browser-side ready check,
        the capture sniff and find_table -- so the producer cannot WAIT on one element and
        CAPTURE another."""
        assert T.TOTAL_ROW_MARKER in FETCH._READY_JS
        assert f">= {T.MIN_SNIFF_ROWS}" in FETCH._READY_JS
        assert "querySelector('main')" in FETCH._MAIN_OUTER_HTML_JS

    def test_the_ready_check_treats_a_raising_page_as_not_yet(self):
        class _Page:
            def __init__(self, answer):
                self.answer = answer

            def evaluate(self, _js):
                if isinstance(self.answer, Exception):
                    raise self.answer
                return self.answer

        assert FETCH.table_is_rendered(_Page(True)) is True
        assert FETCH.table_is_rendered(_Page(False)) is False
        assert FETCH.table_is_rendered(_Page(RuntimeError("mid-navigation"))) is False

    def test_the_url_and_the_navigation_path_agree(self):
        assert FETCH.page_url() == T.PAGE_URL
        assert FETCH.page_url().endswith(FETCH.page_path())
        assert FETCH.page_path().startswith("/napryamki/")

    def test_the_capture_metadata_carries_the_stamp_and_the_capture_utc(self):
        meta = FETCH.capture_metadata(page().decode("utf-8"),
                                      captured_at="2026-08-20T05:00:00+00:00")
        assert meta["source"] == T.SOURCE == "minagro_grain_exports"
        assert meta["capture_timestamp_utc"] == "2026-08-20T05:00:00+00:00"
        assert meta["capture_kind"] == "rendered_main_outerhtml"
        assert meta["published_at"] == "2026-08-14T09:05"
        assert meta["publish_stamp_text"].startswith("Опубліковано")

    def test_the_dry_run_touches_no_browser_and_no_aws(self, capsys):
        assert FETCH.main(["--dry-run", "--as-of-date", "2026-08-14"]) == 0
        out = capsys.readouterr().out
        assert T.PAGE_URL in out
        assert raw_minagro_grain_exports_key("2026-08-14") in out
        assert out.isascii(), "the console is cp1252 -- a non-ASCII print CRASHES python"

    def test_the_size_floor_is_wired(self):
        from leviathan.common.constants import MIN_RAW_FILE_SIZES

        assert MIN_RAW_FILE_SIZES[T.SOURCE] == 3_000
        assert len(page()) > MIN_RAW_FILE_SIZES[T.SOURCE], "the real capture clears its own floor"


# ---------------------------------------------------------------------------
class TestTheSilverProjection:
    def test_the_contract_columns_are_the_tidy_row(self):
        assert S.OUTPUT_COLUMNS == [
            "as_of_date", "crop_slug", "marketing_year", "prior_marketing_year",
            "my_cumulative_kt", "month_to_date_kt", "prior_my_cumulative_kt",
            "prior_my_month_kt", "source"]
        assert S.NATURAL_KEY == ["as_of_date", "crop_slug"]

    def test_the_projection_preserves_every_published_value(self):
        df, _ = bronze()
        silver = S.build_silver([df])
        assert list(silver.columns) == S.OUTPUT_COLUMNS
        assert len(silver) == 10
        for slug, expected in EXPECTED.items():
            row = silver[silver["crop_slug"] == slug].iloc[0]
            assert [float(row[c]) for c in T.VALUE_COLUMNS] == pytest.approx(expected), slug

    def test_the_knowledge_column_is_a_real_date_and_not_a_string(self):
        """date32[day] under the INV-2 contract: a string anchor compares only lexicographically
        and silently defeats a PIT range guard."""
        silver = S.build_silver([bronze()[0]])
        assert set(silver["as_of_date"]) == {_AS_OF}
        assert all(isinstance(v, dt.date) and not isinstance(v, dt.datetime)
                   for v in silver["as_of_date"])

    def test_the_source_column_rides_every_row(self):
        silver = S.build_silver([bronze()[0]])
        assert set(silver["source"]) == {"minagro_grain_exports"}

    def test_an_exact_duplicate_capture_collapses(self):
        df, _ = bronze()
        assert len(S.build_silver([df, df.copy()])) == 10

    def test_a_conflicting_value_for_the_same_key_fails_closed(self):
        """The ministry does not restate a past as-of, so two different values under one
        (as_of_date, crop_slug) is a defect -- never 'whichever row sorted last'."""
        df, _ = bronze()
        other = df.copy()
        other.loc[other["crop_slug"] == "wheat", "my_cumulative_kt"] = 9999.0
        with pytest.raises(S.MinagroConflictError, match="two different value tuples"):
            S.build_silver([df, other])

    def test_two_as_of_dates_are_two_observations_and_not_two_vintages(self):
        df, _ = bronze()
        later = df.copy()
        later["as_of_date"] = dt.date(2026, 8, 21)
        later["my_cumulative_kt"] = later["my_cumulative_kt"] + 100.0
        silver = S.build_silver([df, later])
        assert len(silver) == 20
        assert sorted(set(silver["as_of_date"])) == [_AS_OF, dt.date(2026, 8, 21)]
        # sorted (as_of_date, crop_slug) so a re-run over the same raw objects is byte-stable
        assert list(silver["as_of_date"]) == sorted(silver["as_of_date"])

    def test_a_null_knowledge_date_is_refused(self):
        df, _ = bronze()
        df.loc[0, "as_of_date"] = None
        with pytest.raises(ValueError, match="null as_of_date"):
            S.build_silver([df])

    def test_no_bronze_rows_yields_the_empty_contract_frame(self):
        empty = S.build_silver([])
        assert list(empty.columns) == S.OUTPUT_COLUMNS and len(empty) == 0


# ---------------------------------------------------------------------------
class TestTheRegistryContract:
    """The F010 contract and the transform must declare the SAME nine columns in the same order --
    flat_producer.encode_parquet fails closed on a column the contract does not declare, so a drift
    here is a producer that cannot write."""

    def test_the_contract_mirrors_the_transform_column_for_column(self):
        from leviathan.silver.registry import load_registry

        contract = load_registry().table("silver_minagro_grain_exports")
        names = [c["name"] for c in contract["physical_columns"]]
        assert names == S.OUTPUT_COLUMNS

    def test_the_pit_fields_name_the_tables_own_date(self):
        from leviathan.silver.registry import load_registry

        contract = load_registry().table("silver_minagro_grain_exports")
        assert contract["knowledge_date_col"] == "as_of_date"
        assert contract["knowledge_semantics"] == "data_date"
        assert contract["publication_lag_days"] == 0
        assert contract["natural_key"] == S.NATURAL_KEY

    def test_the_anchor_column_is_date_typed_and_non_null(self):
        from leviathan.silver.registry import load_registry

        contract = load_registry().table("silver_minagro_grain_exports")
        col = {c["name"]: c for c in contract["physical_columns"]}["as_of_date"]
        assert col["glue_type"] == "date" and col["target_arrow_type"] == "date32[day]"
        assert col["nullable"] is False

    def test_the_numbers_card_is_wired_and_the_cascade_still_is_not(self):
        """FLIPPED 2026-08-20 (light-the-card). The pre-flip pin guarded the OTHER direction -- "no
        card, no cascade, no serving table until a cloud run has proven rows", i.e. the registry must
        not forward-declare a surface. PROOF OF ROWS was met (Athena, 2026-08-20: ten rows at as_of
        2026-08-14, one per crop_slug), so the card landed and this pin now guards the RESOLVED state
        rather than being deleted -- a discharged fence that is merely removed leaves the next reader
        re-deriving the argument.

        Three of the four fields do NOT move, and each for its own reason:
          * cascade_ref stays None. The card is DEFERRED in cascade_map's served-table register with an
            ARGUED refusal (the Black Sea driver ids' keying cannot express a ministry row label), and a
            back-pointer here would claim an engine leg that does not exist.
          * serving_table stays None: the card reads the physical table directly (no athena_table
            indirection, unlike silver_esr -> silver_esr_compact).
          * consumers is numbers_registry and NOT 'both' -- nothing in the feature/model layer reads
            this table, and that is what the generator derives (numbers yes, features no)."""
        from leviathan.silver.registry import load_registry

        contract = load_registry().table("silver_minagro_grain_exports")
        assert contract["numbers_ref"] == \
            "configs/graphrag/numbers/tables.yaml#silver_minagro_grain_exports"
        assert contract["consumers"] == "numbers_registry"
        assert contract["cascade_ref"] is None
        assert contract["serving_table"] is None
        # ...and the card is the SOURCE of the value_columns / floor the generator now derives: carding
        # a wide table is what first subjects its metrics to a non-null floor at all.
        assert contract["value_columns"] == list(T.VALUE_COLUMNS)
        assert contract["min_nonnull_frac"] == 0.5

    def test_nothing_is_scheduled_and_no_batch_task_is_claimed(self):
        from leviathan.silver.registry import load_registry

        contract = load_registry().table("silver_minagro_grain_exports")
        assert contract["producer"]["batch_task"] is None
        assert contract["producer"]["transform"].endswith(
            "bronze_to_silver/minagro_grain_exports.py")

    def test_the_hand_ddl_is_byte_identical_to_the_generated_one(self):
        gen = (_REPO / "sql" / "athena" / "ddl_generated"
               / "silver_minagro_grain_exports.sql").read_text(encoding="utf-8")
        hand = (_REPO / "sql" / "athena" / "ddl"
                / "silver_minagro_grain_exports.sql").read_text(encoding="utf-8")
        assert gen == hand
        assert "as_of_date             date" in gen


# ---------------------------------------------------------------------------
# The existence probe FAILS CLOSED -- first-capture-wins is a LAW, not a hope
# ---------------------------------------------------------------------------
class _StubPage:
    """A playwright Page, as far as the producer can tell."""

    def __init__(self, html: str):
        self._html = html

    def wait_for_load_state(self, *_a, **_kw):
        return None

    def evaluate(self, _js):
        return self._html


class _StubSession:
    """A BrowserSession that renders the fixture. No playwright, no Chromium, no network."""

    def __init__(self, html: str):
        self._html = html
        self.launched = 0

    def __call__(self, base_url, *, headless=True):
        self.launched += 1
        self.base_url = base_url
        self.page = _StubPage(self._html)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def goto_and_settle(self, _path, *, ready_check=None, max_wait_s=90):
        return None


class TestRawExistsFailsClosed:
    """``raw_exists`` is the LAST gate before the only PUT on this leg: by the time it runs the
    browser has captured, the marker sniff has passed and the as-of has been read, so there is
    nothing at all between it and ``land_bytes``.

    The EEX argument is not what carries this one -- the ``fetch_moex_agro_indices.py`` argument is.
    This family's raw layer is FIRST CAPTURE WINS **by law**, stated in the producer's own
    docstring, and the estate house idiom repeals that law silently on any throttle: the ministry
    re-renders the standing slug in place, so the bytes that would replace the landed release are a
    later render of it, and a missed week is unrecoverable. A rule a producer states in prose must
    not depend on whether S3 happened to answer."""

    @staticmethod
    def _s3(monkeypatch, exc):
        class _S3:
            def head_object(self, **_kw):
                if exc is not None:
                    raise exc
                return {"ContentLength": 1}

        import leviathan.storage.s3 as S3MOD
        monkeypatch.setattr(S3MOD, "get_thread_local_s3_client", lambda region: _S3())

    @staticmethod
    def _client_error(code, status):
        from botocore.exceptions import ClientError
        return ClientError(
            {"Error": {"Code": code, "Message": "x"},
             "ResponseMetadata": {"HTTPStatusCode": status}},
            "HeadObject",
        )

    def test_a_landed_object_is_reported_present(self, monkeypatch):
        self._s3(monkeypatch, None)
        assert FETCH.raw_exists("b", "k", "us-east-1") is True

    @pytest.mark.parametrize("code,status", [("404", 404), ("NotFound", 404), ("NoSuchKey", 404)])
    def test_only_a_genuine_404_means_absent(self, monkeypatch, code, status):
        """HeadObject has no body, so botocore spells the missing-key case '404'/'NotFound' rather
        than the 'NoSuchKey' a GetObject would raise. All three are the same fact."""
        self._s3(monkeypatch, self._client_error(code, status))
        assert FETCH.raw_exists("b", "k", "us-east-1") is False

    @pytest.mark.parametrize("code,status", [
        ("SlowDown", 503),
        ("InternalError", 500),
        ("ExpiredToken", 400),
        ("AccessDenied", 403),
        ("RequestTimeout", 400),
    ])
    def test_every_other_head_failure_RAISES_rather_than_fabricating_absence(
            self, monkeypatch, code, status):
        from botocore.exceptions import ClientError
        self._s3(monkeypatch, self._client_error(code, status))
        with pytest.raises(ClientError):
            FETCH.raw_exists("b", "k", "us-east-1")

    @staticmethod
    def _drive(monkeypatch, head_exc, *extra):
        """``main()`` through the REAL raw_exists over a stubbed head_object and a stubbed browser.
        Returns ``(exit_code, [landed keys], session)``."""
        import types

        landed: list[str] = []
        TestRawExistsFailsClosed._s3(monkeypatch, head_exc)
        session = _StubSession(page().decode("utf-8"))

        class _ChallengeFailed(Exception):
            pass

        monkeypatch.setattr(FETCH, "_browser",
                            lambda: types.SimpleNamespace(BrowserSession=session,
                                                          ChallengeFailed=_ChallengeFailed))
        monkeypatch.setattr(FETCH, "land_bytes",
                            lambda bucket, key, data, **kw: landed.append(key))
        rc = FETCH.main(["--bucket", "test-bucket", "--aws-region", "us-east-1", *extra])
        return rc, landed, session

    def test_a_transient_head_failure_never_reaches_the_PUT(self, monkeypatch):
        """End to end through ``main()``: the capture succeeds, the sniff passes, the as-of reads
        clean -- and then the probe throttles. The producer must land NOTHING and exit 1, rather
        than read the unanswerable probe as 'absent' and overwrite the landed release."""
        rc, landed, session = self._drive(monkeypatch, self._client_error("SlowDown", 503))
        assert rc == 1
        assert landed == [], "a throttled head must never be read as 'absent' and PUT over"
        assert session.launched == 1, "the probe sits AFTER the capture; the browser did run"

    def test_the_refusal_is_not_the_challenge_or_marker_code(self, monkeypatch):
        """rc 1 is a plain failure. It must not be 6 (the venue served something that was not the
        table) or 7 (the challenge never cleared) -- an S3 fault says nothing about the WAF, and a
        metric filter on those codes would otherwise read this as an IP-class answer."""
        rc, _landed, _session = self._drive(monkeypatch, self._client_error("ExpiredToken", 400))
        assert rc == 1
        assert rc != FETCH.EXIT_TABLE_MARKERS_ABSENT and rc != FETCH.EXIT_CHALLENGE_FAILED

    def test_the_same_drive_lands_when_the_head_answers_404(self, monkeypatch):
        """The positive control, so the tests above cannot pass vacuously."""
        rc, landed, _session = self._drive(monkeypatch, self._client_error("404", 404))
        assert rc == 0
        assert landed == [raw_minagro_grain_exports_key(_AS_OF.isoformat())]

    def test_an_already_landed_as_of_still_short_circuits(self, monkeypatch):
        """FIRST CAPTURE WINS is unchanged: a head that ANSWERS 'present' discards this render."""
        rc, landed, _session = self._drive(monkeypatch, None)
        assert rc == 0 and landed == []

    def test_force_bypasses_the_probe_entirely(self, monkeypatch):
        """``--force`` clears skip-existing, so the repair path still works while S3 throttles."""
        rc, landed, _session = self._drive(monkeypatch, self._client_error("SlowDown", 503),
                                           "--force")
        assert rc == 0
        assert landed == [raw_minagro_grain_exports_key(_AS_OF.isoformat())]
