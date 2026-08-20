"""PRICE_AND_PLAYBOOKS W1c -- the Euronext (MATIF) leg. Hermetic: no network, no browser, no AWS.

The fixture ``tests/fixtures/w1c/euronext_ebm_table.html`` is the VERBATIM rendered outerHTML of
``table#future-prices-table`` for EBM-DPAR, captured live 2026-07-29 through headless Chromium (the
table is client-rendered from an AES ``{ct,iv,s}`` payload and exists in NO plain-requests
response). Element structure, attributes and text are the venue's; only the tbody's whitespace runs
were normalized.

Every number asserted below is a real published value. The three facts these tests exist to pin are
the three that would otherwise produce a WRONG NUMBER rather than an error:

  * the ``Ask`` column is ``style="display: none"`` -- PRESENT in the DOM, invisible on screen -- so
    a parser written against the visible 11 columns is off by one from ``Last`` onward and lands the
    Settl. as the Low;
  * the untraded back months are a SECOND ROW SHAPE, not junk: they carry only Bid/Ask/Settl./O.I
    and ``Settl.`` prints for every one of them;
  * the page carries NO DATE, so ``as_of_date`` is the trade date and the transform must refuse to
    invent one.

The producer is exercised only through its pure helpers. Playwright is never imported: the browser
plumbing is validated by the first Fargate run, by design (the CHALLENGE_FAILED exit contract).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.storage.paths import euronext_product_prefix, raw_euronext_key
from leviathan.transforms.raw_to_bronze import euronext_eod as T

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = _REPO / "tests" / "fixtures" / "w1c" / "euronext_ebm_table.html"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FETCH = _load("jobs/ingest/fetch_euronext_eod.py", "fetch_euronext_eod")

_AS_OF = "2026-07-29"


def table_html() -> bytes:
    return _FIXTURE.read_bytes()


def bronze(as_of: str = _AS_OF, product: str = "EBM-DPAR"):
    return T.build_bronze(table_html(), product=product, as_of_date=as_of)


def _row(df, delivery: str):
    hit = df[df["raw_symbol"] == delivery]
    assert len(hit) == 1, f"{delivery} appears {len(hit)} time(s)"
    return hit.iloc[0]


def truncated_to(keep: int, payload: bytes = None) -> bytes:
    """The fixture with only its first ``keep`` body rows.

    This is what a partially rendered tbody, or a venue-side page cut, actually looks like: every
    row present is perfectly well formed and the header is intact. Nothing but a row COUNT can see
    it."""
    text = (table_html() if payload is None else payload).decode("utf-8")
    head, rest = text.split("<tbody>", 1)
    body, tail = rest.split("</tbody>", 1)
    rows = body.split("<tr ")
    kept = rows[0] + "".join("<tr " + r for r in rows[1:1 + keep])
    return (head + "<tbody>" + kept + "</tbody>" + tail).encode("utf-8")


# ---------------------------------------------------------------------------
class TestTableShape:
    def test_twelve_expiries_seven_traded_five_untraded(self):
        df, stats = bronze()
        assert len(df) == 12 == stats["rows_kept"]
        assert stats["rows_traded"] == 7
        assert stats["rows_untraded"] == 5
        assert int(df["traded"].sum()) == 7

    def test_the_front_month_is_read_cell_for_cell(self):
        """Sep 2026, every published cell. This is the assertion that fails LOUDLY if the hidden
        Ask column is dropped and every later index shifts by one."""
        row = _row(bronze()[0], "Sep 2026")
        assert row["contract_month"] == "2026-09"
        assert float(row["bid"]) == pytest.approx(226.50)
        assert float(row["ask"]) == pytest.approx(226.75), "the display:none column IS a column"
        assert float(row["last"]) == pytest.approx(226.50)
        assert row["quote_time"] == "18:31"
        assert float(row["change"]) == pytest.approx(-1.25)
        assert int(row["volume"]) == 41_367
        assert float(row["open"]) == pytest.approx(227.50)
        assert float(row["high"]) == pytest.approx(229.25)
        assert float(row["low"]) == pytest.approx(225.50)
        assert float(row["settle"]) == pytest.approx(227.75)
        assert int(row["open_interest"]) == 201_888

    def test_the_untraded_back_month_carries_a_settlement_and_nothing_else(self):
        """May 2029: data-lasttradesdate="-", every traded field "-", O.I zero -- and a real
        settlement. These rows are the point of keeping the shape, not noise to drop."""
        row = _row(bronze()[0], "May 2029")
        assert bool(row["traded"]) is False
        assert float(row["settle"]) == pytest.approx(228.75)
        assert int(row["open_interest"]) == 0
        assert pd.isna(row["last"]) and pd.isna(row["open"]) and pd.isna(row["high"])
        assert pd.isna(row["low"]) and pd.isna(row["bid"])
        assert row["quote_time"] is None
        assert float(row["ask"]) == pytest.approx(250.00), "the untraded rows still quote an ask"

    def test_settle_prints_for_every_row_including_the_untraded_ones(self):
        df, stats = bronze()
        assert stats["rows_with_settle"] == 12 == int(df["settle"].notna().sum())

    def test_zero_is_a_real_value_here_and_is_never_masked(self):
        """The CZCE/JSE 0-means-no-trade sentinel does NOT apply on this venue: '-' is the sentinel
        and +/- legitimately prints 0.00 on an unchanged month. Masking zero would erase
        observations -- including May 2029's open interest of exactly 0."""
        df, _ = bronze()
        assert float(_row(df, "Sep 2027")["change"]) == 0.0
        assert int(_row(df, "May 2029")["open_interest"]) == 0

    def test_the_traded_flag_comes_from_the_venues_own_attribute(self):
        df, _ = bronze()
        traded = set(df[df["traded"]]["raw_symbol"])
        assert traded == {"Sep 2026", "Dec 2026", "Mar 2027", "May 2027", "Sep 2027", "Dec 2027",
                          "Mar 2028"}

    def test_the_helper_really_does_truncate_the_body_and_nothing_else(self):
        """The negative control for the floor tests below: a 12-row 'truncation' is the fixture."""
        assert truncated_to(12) == table_html()
        df, _ = T.build_bronze(truncated_to(12), product="EBM-DPAR", as_of_date=_AS_OF)
        assert len(df) == 12

    def test_the_natural_key_is_unique(self):
        """raw_symbol is the delivery text, which is the only per-row identity the table publishes.
        A constant symbol would collapse all 12 rows onto one F2 key."""
        df, _ = bronze()
        for key in (["leviathan_slug", "contract_month", "trade_date"],
                    ["leviathan_slug", "trade_date", "raw_symbol"]):
            assert df.groupby(key, dropna=False).size().max() == 1


# ---------------------------------------------------------------------------
class TestDeliveryMonth:
    def test_the_href_is_preferred_over_the_label(self):
        _df, stats = bronze()
        assert stats["delivery_from_href"] == 12 and stats["delivery_from_text"] == 0

    def test_the_md_parameter_is_dd_mm_yyyy(self):
        href = ("/en/product/commodities-futures/EBM-DPAR/instrument?Class_symbol=EBM"
                "&Class_exchange=DPAR&fOrO=F&md=01-09-2026")
        assert T.contract_month_from_href(href) == "2026-09"
        # DD-MM, not MM-DD: 05-2029 is MAY 2029, and reading it the American way lands 2029-05 as
        # 2029-... nothing, or worse, silently as a different month.
        assert T.contract_month_from_href("?md=01-05-2029") == "2029-05"
        assert T.contract_month_from_href("?md=01-12-2028") == "2028-12"
        assert T.contract_month_from_href("/instrument?fOrO=F") is None

    def test_the_anchor_text_is_the_fallback(self):
        assert T.contract_month_from_text("Sep 2026") == "2026-09"
        assert T.contract_month_from_text("March 2028") == "2028-03"
        with pytest.raises(ValueError, match="delivery month"):
            T.contract_month_from_text("Sep")

    def test_the_fallback_is_exercised_when_the_href_is_gone(self):
        payload = table_html().replace(b"&amp;md=", b"&amp;xx=")
        df, stats = T.build_bronze(payload, product="EBM-DPAR", as_of_date=_AS_OF)
        assert stats["delivery_from_text"] == 12 and stats["delivery_from_href"] == 0
        assert list(df["contract_month"])[:2] == ["2026-09", "2026-12"]

    def test_the_two_readings_of_every_row_are_cross_checked(self):
        """Every md value the venue serves is ``01-MM-YYYY``, so the CAPTURE cannot distinguish
        DD-MM from MM-DD: the only evidence for the DD-MM reading is the anchor text beside it. A
        venue that switched to MM-DD-YYYY would decode all 12 rows to month 01 of four distinct
        years, raw_symbol would stay distinct so the F2 key would stay unique, and nothing would
        fail. The text parser is already written, so the check costs one call."""
        _df, stats = bronze()
        assert stats["delivery_cross_checked"] == 12

    def test_a_date_format_flip_is_a_hard_error(self):
        flipped = table_html().replace(b"md=01-09-2026", b"md=09-01-2026")
        with pytest.raises(ValueError, match="anchor text but to"):
            T.build_bronze(flipped, product="EBM-DPAR", as_of_date=_AS_OF)

    def test_a_label_the_text_parser_cannot_read_is_not_evidence_of_a_flip(self):
        """The cross-check must not take the leg down over a re-worded label -- the href stays
        authoritative and a text the parser cannot read simply abstains."""
        relabelled = table_html().replace(b">Sep 2026<", b">Sep-26<")
        df, stats = T.build_bronze(relabelled, product="EBM-DPAR", as_of_date=_AS_OF)
        assert list(df["contract_month"])[0] == "2026-09"
        assert stats["delivery_from_href"] == 12 and stats["delivery_cross_checked"] == 11

    def test_all_twelve_months_decode(self):
        df, _ = bronze()
        assert list(df["contract_month"]) == [
            "2026-09", "2026-12", "2027-03", "2027-05", "2027-09", "2027-12",
            "2028-03", "2028-05", "2028-09", "2028-12", "2029-03", "2029-05"]


# ---------------------------------------------------------------------------
class TestHeaderPinFailsClosed:
    def test_the_pinned_header_is_the_twelve_the_venue_renders(self):
        _df, stats = bronze()
        assert stats["header"] == ["delivery", "bid", "ask", "last", "time", "", "day vol",
                                   "open", "high", "low", "settl", "o i"]
        assert len(T._HEADER_TOKENS) == 12

    def test_dropping_the_hidden_ask_column_is_a_hard_error(self):
        """THE DEFECT THIS PIN EXISTS FOR. Remove the display:none Ask header and the count no
        longer matches -- rather than every later column silently shifting by one."""
        payload = table_html().replace(
            b'<th scope="col" class="text-right sorting_disabled" data-priority="9" rowspan="1" '
            b'colspan="1" style="display: none;">Ask<span class="sort-arrows"></span></th>', b"")
        with pytest.raises(ValueError, match="header cell"):
            T.build_bronze(payload, product="EBM-DPAR", as_of_date=_AS_OF)

    def test_a_renamed_settlement_column_is_a_hard_error(self):
        payload = table_html().replace(b">Settl.<", b">VWAP<")
        with pytest.raises(ValueError, match="drifted"):
            T.build_bronze(payload, product="EBM-DPAR", as_of_date=_AS_OF)

    def test_a_reordered_header_is_a_hard_error(self):
        """A swap keeps the count and the vocabulary identical and changes what every number
        MEANS -- the only defence is that position is pinned."""
        payload = table_html().replace(b">High<", b">TMP<").replace(b">Low<", b">High<") \
                              .replace(b">TMP<", b">Low<")
        with pytest.raises(ValueError, match="drifted"):
            T.build_bronze(payload, product="EBM-DPAR", as_of_date=_AS_OF)

    def test_a_page_without_the_table_is_a_hard_error(self):
        with pytest.raises(ValueError, match="not a rendered quote table"):
            T.build_bronze(b"<html><body><p>loading</p></body></html>",
                           product="EBM-DPAR", as_of_date=_AS_OF)

    def test_an_id_rename_falls_back_to_the_delivery_header_and_still_pins(self):
        payload = table_html().replace(b'id="future-prices-table"', b'id="prices-table-v2"')
        df, _stats = T.build_bronze(payload, product="EBM-DPAR", as_of_date=_AS_OF)
        assert len(df) == 12, "an id rename must not take the leg down; the header pin is the guard"

    def test_a_short_body_row_is_a_hard_error(self):
        """WHY THIS TEST WAS INERT, and why the assertion is UNCHANGED. The fence itself never
        moved: euronext_eod.py has exactly one commit (50a2ec3d) and build_bronze:386-390 still
        raises on `len(cells) != _COLUMN_COUNT`. What moved is the CHECKOUT. The fixture blob is
        stored LF-only, this repo runs core.autocrlf=true, so on a Windows working tree
        euronext_ebm_table.html lands with 183 CRLF line ends -- and the old one-shot
        `.replace(b'...</td>\\n', b"")` matched NOTHING. build_bronze then received the PRISTINE
        fixture, parsed 12 well-formed rows, and never raised: a data-integrity fence asserted by
        a mutation that silently did not happen. The repair is to make the cut line-ending
        agnostic AND to prove the cut bit before asserting on it -- a no-op replace must go RED
        here, never green."""
        cell = b'<td class="text-right">201,888</td>'
        payload = table_html()
        assert payload.count(cell) == 1, "fixture drifted: the day-volume cell this test cuts is gone"
        # Cut the cell AND its own line ending, whichever the checkout produced.
        for eol in (b"\r\n", b"\n"):
            shortened = payload.replace(b"      " + cell + eol, b"", 1)
            if shortened != payload:
                break
        assert shortened != payload, "the short-row mutation did not bite -- the assertion below would be vacuous"
        assert shortened.count(cell) == 0
        with pytest.raises(ValueError, match="positional map cannot be trusted"):
            T.build_bronze(shortened, product="EBM-DPAR", as_of_date=_AS_OF)

    def test_a_table_with_no_settlement_at_all_is_refused(self):
        """A pre-publish capture (before ~18:30 CET) is the shape this catches. The tempting repair
        -- fall back to Last -- would publish a trade as a settlement."""
        df, _ = T.build_bronze(table_html(), product="EBM-DPAR", as_of_date=_AS_OF)
        assert int(df["settle"].notna().sum()) == 12          # the fixture itself is complete
        with pytest.raises(ValueError, match="not one of"):
            T.build_bronze(_strip_every_settlement(table_html()),
                           product="EBM-DPAR", as_of_date=_AS_OF)


def _strip_every_settlement(payload: bytes) -> bytes:
    """Blank the 11th cell of every body row -- a pre-publish capture, structurally."""
    out: list[str] = []
    cells = 0
    for line in payload.decode("utf-8").splitlines(keepends=True):
        if line.strip().startswith("<tr "):
            cells = 0
        if line.strip().startswith("<td"):
            cells += 1
            if cells == 11:
                line = '      <td class="text-right">-</td>\n'
        out.append(line)
    return "".join(out).encode("utf-8")


# ---------------------------------------------------------------------------
class TestTheCompletenessFloor:
    """THE DEFECT THIS CLASS EXISTS FOR. The header pin says what each column MEANS and nothing
    says how many ROWS a complete curve has -- so a partially rendered or venue-truncated table
    landed, parsed cleanly, and published as a COMPLETE curve with no error at any layer."""

    def test_the_measured_counts_are_pinned_per_product(self):
        assert T.EURONEXT_MIN_ROWS == {"EBM-DPAR": 12, "EMA-DPAR": 10, "ECO-DPAR": 10}
        assert T.min_rows_for_product("ebm-dpar") == 12
        assert T.min_rows_for_product("ECO-DPAR") == 10
        # TOTAL for an unmapped product: the producer's sniff must stay callable, and 8 is below the
        # thinnest MATIF curve rather than a guess at a new product's shape.
        assert T.min_rows_for_product("XXX-DPAR") == T.EURONEXT_MIN_ROWS_FALLBACK == 8

    def test_a_product_with_no_measured_floor_is_an_import_time_error(self):
        """The lint is what stops a fourth MATIF product from being added with no row count -- the
        'writes nothing quietly' class, in the one place this leg has no other detector for."""
        assert T._lint_product_map() == []
        original = dict(T.EURONEXT_MIN_ROWS)
        try:
            T.EURONEXT_MIN_ROWS.pop("EMA-DPAR")
            errs = T._lint_product_map()
            assert any("EMA-DPAR" in e and "EURONEXT_MIN_ROWS" in e for e in errs), errs
            T.EURONEXT_MIN_ROWS["EOB-DPAR"] = 9
            assert any("EOB-DPAR" in e for e in T._lint_product_map())
        finally:
            T.EURONEXT_MIN_ROWS.clear()
            T.EURONEXT_MIN_ROWS.update(original)
        assert T._lint_product_map() == []

    def test_a_truncated_table_is_a_hard_error_and_not_a_short_curve(self):
        """3 of 12 rows: every row well formed, the header intact, the settlements real. This is
        the shape that used to yield three bronze rows and no error anywhere."""
        with pytest.raises(ValueError, match="expected at least 12"):
            T.build_bronze(truncated_to(3), product="EBM-DPAR", as_of_date=_AS_OF)

    def test_even_one_missing_expiry_is_refused(self):
        """11 of 12 is the shape a floor set 'a bit below' the measured count would wave through --
        the F-C trap, where the number sits between the correct answer and the bug."""
        with pytest.raises(ValueError, match="expected at least 12"):
            T.build_bronze(truncated_to(11), product="EBM-DPAR", as_of_date=_AS_OF)

    def test_an_empty_tbody_is_refused_rather_than_parsed_to_zero_rows(self):
        """It used to return a 0-row frame with NO exception: the settle guard is `if len(df) and
        settle_rows == 0`, so an empty parse skipped every check there is."""
        with pytest.raises(ValueError, match="ZERO delivery months"):
            T.build_bronze(truncated_to(0), product="EBM-DPAR", as_of_date=_AS_OF)

    def test_the_day_row_floor_alone_could_not_catch_it(self):
        """Why the floor has to be per-PRODUCT and enforced here. The task's per-day silver floor
        for this leg is 24 rows; a 5-row EBM plus a full EMA (10) and ECO (10) is 25 and passes."""
        task = _load("jobs/batch/futures_eod_task.py", "futures_eod_task_euronext")
        assert task._MIN_SILVER_ROWS_PER_DAY_EURONEXT == 24
        assert 5 + T.EURONEXT_MIN_ROWS["EMA-DPAR"] + T.EURONEXT_MIN_ROWS["ECO-DPAR"] > 24

    def test_a_curve_that_GREW_is_never_a_truncation(self):
        """A floor, not an equality: a venue listing a further expiry publishes MORE of the curve."""
        payload = table_html().decode("utf-8")
        head, rest = payload.split("<tbody>", 1)
        body, tail = rest.split("</tbody>", 1)
        first_row = "<tr " + body.split("<tr ", 2)[1]
        grown = (head + "<tbody>" + body + first_row.replace("Sep 2026", "Sep 2030")
                 .replace("md=01-09-2026", "md=01-09-2030") + "</tbody>" + tail)
        df, stats = T.build_bronze(grown.encode("utf-8"), product="EBM-DPAR", as_of_date=_AS_OF)
        assert len(df) == 13 and stats["rows_expected"] == 12


# ---------------------------------------------------------------------------
class TestTheDateComesFromTheKey:
    def test_the_page_publishes_no_date_so_as_of_is_the_session(self):
        for as_of in ("2026-07-29", "2026-08-03"):
            df, stats = bronze(as_of)
            assert stats["trade_date"] == as_of
            assert set(df["trade_date"]) == {pd.Timestamp(as_of)}

    def test_a_missing_as_of_is_refused_rather_than_guessed(self):
        with pytest.raises(ValueError, match="as_of_date is required"):
            T.build_bronze(table_html(), product="EBM-DPAR", as_of_date="")

    def test_the_time_column_is_a_clock_and_is_never_a_date(self):
        df, _ = bronze()
        assert set(df[df["traded"]]["quote_time"]) == {"18:31", "18:32", "18:30", "18:29", "15:27"}
        assert df[~df["traded"]]["quote_time"].isna().all()


# ---------------------------------------------------------------------------
class TestProductMap:
    def test_the_product_map_is_bound_to_the_contract_map_both_ways(self):
        assert T._lint_product_map() == []
        assert set(T.EURONEXT_PRODUCT_MAP.values()) == {
            s for s, r in FC.CONTRACT_MAP.items() if r["source"] == "euronext_matif"}

    def test_the_three_products_are_the_three_matif_slugs(self):
        assert T.EURONEXT_PRODUCT_MAP == {
            "EBM-DPAR": "french_wheat_matif",
            "EMA-DPAR": "french_maize_matif",
            "ECO-DPAR": "french_rapeseed_matif"}
        for slug in T.EURONEXT_PRODUCT_MAP.values():
            rec = FC.CONTRACT_MAP[slug]
            assert rec["unit"] == "EUR/t" and rec["currency"] == "EUR"
            assert rec["settle_kind"] == "settlement", "the SETTL. column, not the Last"

    def test_an_unmapped_product_is_refused(self):
        with pytest.raises(ValueError, match="not one of"):
            T.slug_for_product("EOB-DPAR")
        with pytest.raises(ValueError, match="not one of"):
            T.build_bronze(table_html(), product="XXX-DPAR", as_of_date=_AS_OF)

    def test_the_slug_rides_every_row(self):
        df, _ = bronze()
        assert set(df["leviathan_slug"]) == {"french_wheat_matif"}
        assert set(df["product"]) == {"EBM-DPAR"}


# ---------------------------------------------------------------------------
class TestNumberParsing:
    def test_comma_thousands_and_the_dash_sentinel(self):
        assert T.parse_number("41,367") == 41367.0
        assert T.parse_number("227.75") == pytest.approx(227.75)
        assert T.parse_number("-1.25") == pytest.approx(-1.25)
        assert T.parse_number("0.00") == 0.0
        assert T.parse_number("201,888") == 201888.0
        for token in ("-", "", "  ", "--", "n/a", None):
            assert pd.isna(T.parse_number(token)), token

    def test_a_negative_change_is_a_value_and_a_bare_dash_is_not(self):
        """Both start with '-'. Conflating them turns every down day into a NULL."""
        assert T.parse_number("-1.25") == pytest.approx(-1.25)
        assert pd.isna(T.parse_number("-"))


# ---------------------------------------------------------------------------
class TestProducer:
    def test_the_url_mirrors_the_raw_key(self):
        assert FETCH.product_url("EBM-DPAR") == (
            "https://live.euronext.com/en/product/commodities-futures/EBM-DPAR")
        assert FETCH.product_path("eco-dpar") == "/en/product/commodities-futures/ECO-DPAR"
        key = raw_euronext_key("EBM-DPAR", _AS_OF)
        assert key == ("raw/production/source=euronext/product=EBM-DPAR/"
                       "as_of_date=2026-07-29/table.html")
        assert key.startswith(euronext_product_prefix("EBM-DPAR"))

    def test_the_ready_check_and_the_parse_agree_about_which_table(self):
        """One id, pinned in the transform and used by both the fetch-time ready check and the
        outerHTML grab -- so the producer cannot wait on one element and capture another."""
        assert T.EURONEXT_TABLE_ID == "future-prices-table"
        assert T.EURONEXT_TABLE_ID in FETCH._READY_JS
        assert T.EURONEXT_TABLE_ID in FETCH._OUTER_HTML_JS
        assert "tbody tr" in FETCH._READY_JS, "an empty shell must not count as ready"

    def test_the_ready_check_waits_for_the_whole_curve_not_the_first_row(self):
        """ONE rendered row used to satisfy it. The table fills client-side, so that is a moment in
        a render: the producer would grab a half-filled tbody and land a short curve."""
        assert ">= 12" in FETCH._ready_js(12) and ">= 10" in FETCH._ready_js(10)
        assert FETCH._ready_js(T.min_rows_for_product("EBM-DPAR")) == FETCH._ready_js(12)

        class _Page:
            def __init__(self, rendered):
                self.rendered = rendered

            def evaluate(self, js):
                floor = int(js.rsplit(">=", 1)[1].split(";")[0])
                return self.rendered >= floor

        ready = FETCH.table_is_rendered("EBM-DPAR")
        assert ready(_Page(0)) is False
        assert ready(_Page(1)) is False, "one row is a render in progress, not a table"
        assert ready(_Page(11)) is False
        assert ready(_Page(12)) is True
        assert FETCH.table_is_rendered("EMA-DPAR")(_Page(10)) is True, "EMA lists 10"

    def test_the_capture_sniff_accepts_the_fixture_and_rejects_a_shell(self):
        html = table_html().decode("utf-8")
        assert FETCH.looks_like_a_quote_table(html, "EBM-DPAR") is None
        why = FETCH.looks_like_a_quote_table(
            '<table id="future-prices-table"><thead><tr><th>Settl.</th></tr></thead>'
            "<tbody></tbody></table>", "EBM-DPAR")
        assert why and "never finished populating" in why
        assert "no table" in (FETCH.looks_like_a_quote_table(None, "EBM-DPAR") or "")
        eight = "<tbody>" + "<tr></tr>" * 8 + "</tbody>"
        assert "Settl" in (FETCH.looks_like_a_quote_table(eight, "XXX-DPAR") or "")

    def test_the_capture_sniff_counts_TBODY_rows_and_not_every_tr(self):
        """The old count was ``html.count('<tr')`` over the whole outerHTML, so the header row was
        one of the four it required -- a table that rendered three of twelve expiries passed."""
        assert FETCH.tbody_rows(table_html().decode("utf-8")) == 12
        short = truncated_to(3).decode("utf-8")
        assert short.count("<tr") == 4, "the header row is still there -- that was the bug"
        assert FETCH.tbody_rows(short) == 3
        why = FETCH.looks_like_a_quote_table(short, "EBM-DPAR")
        assert why and "3 tbody <tr>" in why and ">= 12" in why
        assert FETCH.looks_like_a_quote_table(truncated_to(12).decode("utf-8"),
                                              "EBM-DPAR") is None

    def test_the_producer_and_the_transform_share_one_row_floor(self):
        """No second copy of the counts in the producer: it imports the transform's."""
        assert FETCH.min_rows_for_product is T.min_rows_for_product

    def test_the_products_default_to_all_three(self):
        assert FETCH.resolve_products(None) == ["EBM-DPAR", "ECO-DPAR", "EMA-DPAR"]
        assert FETCH.resolve_products(["ebm-dpar", "EBM-DPAR"]) == ["EBM-DPAR"]
        with pytest.raises(SystemExit):
            FETCH.resolve_products(["EOB-DPAR"])

    def test_the_dry_run_touches_no_browser_and_no_aws(self, capsys):
        assert FETCH.main(["--dry-run", "--as-of-date", _AS_OF, "--product", "EBM-DPAR"]) == 0
        out = capsys.readouterr().out
        assert "live.euronext.com/en/product/commodities-futures/EBM-DPAR" in out
        assert raw_euronext_key("EBM-DPAR", _AS_OF) in out

    def test_the_challenge_exit_code_is_the_shared_one(self):
        assert FETCH.EXIT_CHALLENGE_FAILED == 7

    def test_the_size_floor_is_wired(self):
        from leviathan.common.constants import MIN_RAW_FILE_SIZES

        assert MIN_RAW_FILE_SIZES["euronext"] == 2_000

    def test_the_task_enumeration_bound_is_the_transforms_product_map(self):
        """``futures_eod_task.EURONEXT_PRODUCTS`` duplicates EURONEXT_PRODUCT_MAP's keys with no
        import binding them -- the task imports the transform LAZILY so the two halves of W1c could
        land independently. A fourth MATIF product added to CONTRACT_MAP would import-time-force
        the transform's map to grow while ``euronext_units`` silently stopped discovering that
        product's captures: writes nothing, says nothing. The load is call-time here for the same
        reason it is in ``_lazy_bronze`` -- the pin must not reintroduce a wave-order dependency."""
        task = _load("jobs/batch/futures_eod_task.py", "futures_eod_task_euronext")
        assert task.EURONEXT_PRODUCTS == tuple(T.EURONEXT_PRODUCT_MAP)


# ===========================================================================
# The existence probe FAILS CLOSED -- the one path that could destroy a capture
# ===========================================================================
class _StubBrowser:
    """``leviathan.ingest.browser_fetch``, as far as this producer is concerned.

    Playwright is still never imported -- this is the module boundary ``FETCH._browser()`` returns,
    stubbed so the S3 call site can be driven end to end through ``main()``. The browser plumbing
    itself is validated by the first Fargate run, by design."""

    EXIT_CHALLENGE_FAILED = 7

    class ChallengeFailed(Exception):
        pass

    def __init__(self, html: str):
        self._html = html
        self.visited: list[str] = []
        outer = self

        class _Page:
            def evaluate(self, _js):
                return outer._html

        class _Session:
            def __init__(self, _base, headless=True):
                self.page = _Page()

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def goto_and_settle(self, path, ready_check=None, max_wait_s=None):
                outer.visited.append(path)

        self.BrowserSession = _Session


class TestRawExistsFailsClosed:
    """``raw_exists`` gates the only PUT on this leg's raw data plane, and unlike the EEX freight
    leg there is no second fence between it and the write. The estate house idiom answers False on
    ANY head failure, which turns a throttle or an expired credential into "absent" and therefore
    into an overwrite -- of a headless-Chromium snapshot of the venue's CURRENT board, on a page
    that publishes no date and has no history endpoint to re-fetch a past session from."""

    @staticmethod
    def _s3(monkeypatch, raiser):
        """Point ``raw_exists`` at a head_object driven by ``raiser(key)`` -> exception or None."""
        class _S3:
            def head_object(self, **kw):
                exc = raiser(kw["Key"])
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

    ARGV = ["--as-of-date", _AS_OF, "--bucket", "test-bucket", "--aws-region", "us-east-1"]

    def test_a_landed_object_is_reported_present(self, monkeypatch):
        self._s3(monkeypatch, lambda _key: None)
        assert FETCH.raw_exists("b", "k", "us-east-1") is True

    @pytest.mark.parametrize("code,status", [("404", 404), ("NotFound", 404), ("NoSuchKey", 404)])
    def test_only_a_genuine_404_means_absent(self, monkeypatch, code, status):
        """HeadObject has no body, so botocore spells the missing-key case '404'/'NotFound' rather
        than the 'NoSuchKey' a GetObject would raise. All three are the same fact."""
        self._s3(monkeypatch, lambda _key: self._client_error(code, status))
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
        """Fail closed. Failing the product costs a re-fire; treating a throttled head as 'absent'
        costs a session that this venue cannot serve again."""
        from botocore.exceptions import ClientError
        self._s3(monkeypatch, lambda _key: self._client_error(code, status))
        with pytest.raises(ClientError):
            FETCH.raw_exists("b", "k", "us-east-1")

    def test_a_transient_head_failure_never_reaches_the_PUT(self, monkeypatch):
        """End to end through ``main()``: every probe throttles, so the producer must land NOTHING,
        never launch a browser, and report the run as failed -- NOT as 'all products already
        landed', which is the exit-0 path the old swallow-all code could not have reached but the
        naive narrowing would."""
        written = {}
        self._s3(monkeypatch, lambda _key: self._client_error("SlowDown", 503))
        monkeypatch.setattr(FETCH, "land_bytes",
                            lambda bucket, key, data, **kw: written.__setitem__(key, data))
        monkeypatch.setattr(FETCH, "_browser", _no_browser)

        assert FETCH.main(self.ARGV) == 1
        assert written == {}, "a throttled head must never be read as 'absent' and PUT over"

    def test_one_products_unanswerable_probe_never_costs_the_others(self, monkeypatch):
        """The call site is a loop that decides what is owed before Chromium starts. A head that
        cannot answer takes THAT product out as a recorded failure -- it is not fetched and not
        written -- while the products whose probe answered 404 are still captured. The run exits 1
        so the fire is not read as clean."""
        written = {}
        blocked = raw_euronext_key("EBM-DPAR", _AS_OF)
        self._s3(monkeypatch,
                 lambda key: (self._client_error("SlowDown", 503) if key == blocked
                              else self._client_error("404", 404)))
        monkeypatch.setattr(FETCH, "land_bytes",
                            lambda bucket, key, data, **kw: written.__setitem__(key, data))
        stub = _StubBrowser(table_html().decode("utf-8"))
        monkeypatch.setattr(FETCH, "_browser", lambda: stub)

        assert FETCH.main(self.ARGV) == 1
        assert blocked not in written, "the unanswerable product must never be captured"
        assert sorted(written) == [raw_euronext_key(p, _AS_OF)
                                   for p in ("ECO-DPAR", "EMA-DPAR")]
        assert FETCH.product_path("EBM-DPAR") not in stub.visited

    def test_the_same_drive_lands_all_three_when_the_head_answers(self, monkeypatch):
        """The positive control, so the two tests above cannot pass vacuously."""
        written = {}
        self._s3(monkeypatch, lambda _key: self._client_error("404", 404))
        monkeypatch.setattr(FETCH, "land_bytes",
                            lambda bucket, key, data, **kw: written.__setitem__(key, data))
        monkeypatch.setattr(FETCH, "_browser",
                            lambda: _StubBrowser(table_html().decode("utf-8")))

        assert FETCH.main(self.ARGV) == 0
        assert sorted(written) == [raw_euronext_key(p, _AS_OF)
                                   for p in ("EBM-DPAR", "ECO-DPAR", "EMA-DPAR")]


def _no_browser():
    raise AssertionError("a run that captured nothing must never launch Chromium")
