"""PRICE_AND_PLAYBOOKS W1c -- the Bursa Malaysia FCPO leg. Hermetic: no network, no browser, no AWS.

The fixtures are the VERBATIM live API bodies captured 2026-07-29 through headless Chromium after
the Cloudflare challenge cleared:

  * ``bursa_fcpo_api_sample.json``       -- ``ses=day``   (T),   24 delivery months;
  * ``bursa_fcpo_api_night_sample.json`` -- ``ses=night`` (T+1), 24 delivery months, DIFFERENT
    prices, and NAME cells reading ``FCPO (T+1)``.

Every number asserted below is a real published value. The four facts these tests exist to pin are
the four that would otherwise produce a plausible WRONG NUMBER rather than an error:

  * the payload is 13 POSITIONAL elements with no field names, so the rendered ``thead`` is the
    only self-description and it must fail closed;
  * the OI cell is an ``<a>`` anchor with two hidden ``<div>``s after it -- a blanket tag strip
    yields ``"9,202FCPO/Aug 2026As of "`` and NULLs the open interest on every traded month;
  * the night payload is complete and plausible, so nothing but the NAME label separates it from
    the day session whose settlement is the daily settlement;
  * SETT. PRICE prints for all 24 months, quiet back months included, and LAST DONE is never
    promoted into it.

The producer is exercised only through its pure helpers. Playwright is never imported: the browser
plumbing is validated by the first Fargate run, by design (the CHALLENGE_FAILED exit contract).
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.storage.paths import bursa_code_prefix, raw_bursa_key
from leviathan.transforms.raw_to_bronze import bursa_fcpo as T

_REPO = Path(__file__).resolve().parents[2]
_FIXTURES = _REPO / "tests" / "fixtures" / "w1c"
_DAY = _FIXTURES / "bursa_fcpo_api_sample.json"
_NIGHT = _FIXTURES / "bursa_fcpo_api_night_sample.json"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FETCH = _load("jobs/ingest/fetch_bursa_fcpo.py", "fetch_bursa_fcpo")

_AS_OF = "2026-07-29"

# The rendered header the producer scrapes into the side channel, verbatim from the live page's
# column labels (capture_notes.md, resolved cell-by-cell against the first rendered row).
THEAD = ["NO", "NAME", "MONTH", "OPEN", "BID", "ASK", "LAST DONE", "CHANGE", "HIGH", "LOW", "VOL",
         "OI", "SETT. PRICE"]


def day_body() -> dict:
    return json.loads(_DAY.read_text(encoding="utf-8"))


def night_body() -> dict:
    return json.loads(_NIGHT.read_text(encoding="utf-8"))


def wrapped(body=None, thead=None) -> bytes:
    """The object the PRODUCER lands: the rendered header side channel + the API body."""
    return FETCH.build_raw_object(THEAD if thead is None else thead,
                                  day_body() if body is None else body)


def bronze(payload=None, as_of: str = _AS_OF):
    return T.build_bronze(_DAY.read_bytes() if payload is None else payload,
                          code="FCPO", as_of_date=as_of)


def _row(df, month: str):
    hit = df[df["raw_symbol"] == month]
    assert len(hit) == 1, f"{month} appears {len(hit)} time(s)"
    return hit.iloc[0]


class _StubPage:
    """A playwright page, as far as the producer's pure helpers are concerned. An Exception value
    is RAISED by evaluate -- which is the shape a detached/navigating page has."""

    def __init__(self, value):
        self._value = value

    def evaluate(self, _js):
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


class _StubSession:
    def __init__(self, page):
        self.page = page


def _scrape_failure_session() -> _StubSession:
    """The session shape that makes ``scrape_thead`` return [] -- the producer's own documented
    degrade path, and the input the empty-thead test needs."""
    return _StubSession(_StubPage(RuntimeError("detached")))


# ---------------------------------------------------------------------------
class TestCurveShape:
    def test_twenty_four_delivery_months(self):
        df, stats = bronze()
        assert len(df) == 24 == stats["rows_kept"] == stats["records_total"]
        assert stats["rows_traded"] == 14 and stats["rows_quiet"] == 10

    def test_the_front_month_is_read_cell_for_cell(self):
        """Aug 2026, every published cell. This is the assertion that fails LOUDLY on any column
        shift in a payload that carries no field names at all."""
        row = _row(bronze()[0], "Aug 2026")
        assert row["contract_month"] == "2026-08"
        assert float(row["open"]) == pytest.approx(4534.0)
        assert float(row["bid"]) == pytest.approx(4490.0)
        assert float(row["ask"]) == pytest.approx(4600.0)
        assert float(row["last"]) == pytest.approx(4551.0)
        assert float(row["change"]) == pytest.approx(11.0)
        assert float(row["high"]) == pytest.approx(4570.0)
        assert float(row["low"]) == pytest.approx(4528.0)
        assert int(row["volume"]) == 1_025
        assert int(row["open_interest"]) == 9_202
        assert float(row["settle"]) == pytest.approx(4540.0)

    def test_a_quiet_back_month_is_a_settlement_and_nothing_else(self):
        """Mar 2028: every cell '-', including the OI which is a bare '-' rather than an anchor,
        and a real settlement. These rows are the reason the curve is 24 months and not 14."""
        row = _row(bronze()[0], "Mar 2028")
        assert float(row["settle"]) == pytest.approx(4656.0)
        for field in ("open", "bid", "ask", "last", "change", "high", "low"):
            assert pd.isna(row[field]), field
        assert pd.isna(row["volume"]) and pd.isna(row["open_interest"])

    def test_settle_prints_for_all_twenty_four_months(self):
        df, stats = bronze()
        assert stats["rows_with_settle"] == 24 == int(df["settle"].notna().sum())
        assert float(df["settle"].min()) > 4000.0, "MYR/t, never scaled"

    def test_the_natural_key_is_unique_because_raw_symbol_is_the_month(self):
        """THE DEFECT THIS AVOIDS. The NAME cell is the constant 'FCPO' on all 24 rows, so using it
        as raw_symbol collapses the whole curve onto ONE F2 key."""
        df, _ = bronze()
        assert set(df["code"]) == {"FCPO"}
        assert len(set(df["raw_symbol"])) == 24
        for key in (["leviathan_slug", "contract_month", "trade_date"],
                    ["leviathan_slug", "trade_date", "raw_symbol"]):
            assert df.groupby(key, dropna=False).size().max() == 1

    def test_all_twenty_four_months_decode(self):
        df, _ = bronze()
        assert list(df["contract_month"])[:6] == ["2026-08", "2026-09", "2026-10", "2026-11",
                                                  "2026-12", "2027-01"]
        assert list(df["contract_month"])[-3:] == ["2029-03", "2029-05", "2029-07"]

    def test_contract_month_decode_is_fail_closed(self):
        assert T.contract_month_str("Aug 2026") == "2026-08"
        assert T.contract_month_str("January 2029") == "2029-01"
        for bad in ("Aug", "2026-08", "Zzz 2026", ""):
            with pytest.raises(ValueError):
                T.contract_month_str(bad)


# ---------------------------------------------------------------------------
class TestEmbeddedHtmlCells:
    def test_open_interest_is_the_anchor_text_not_the_cell_text(self):
        """THE DEFECT THIS EXISTS FOR. The OI cell is an anchor followed by two hidden divs; a
        blanket tag strip yields '9,202FCPO/Aug 2026As of' -> NaN, and open interest silently
        vanishes on every traded month (which degrades futures_roll's front-month rule into the
        nearest-month tie-break with no error anywhere)."""
        cell = day_body()["data"][0][11]
        assert T.anchor_text(cell) == "9,202"
        assert T.parse_number(T.anchor_text(cell)) == 9202.0
        assert pd.isna(T.parse_number(T.strip_tags(cell))), "the whole-cell strip is the bug"

    def test_all_three_open_interest_shapes(self):
        """Anchor-wrapped (traded), a bare '-' (quiet), and a bare number (defensive)."""
        rows = day_body()["data"]
        assert T.anchor_text(rows[0][11]) == "9,202"      # anchor
        assert T.anchor_text(rows[15][11]) == "-"          # bare dash, Mar 2028
        assert T.anchor_text("28") == "28"                 # bare number
        assert T.anchor_text(None) == ""
        df, stats = bronze()
        assert stats["rows_with_open_interest"] == 15
        assert int(_row(df, "Jan 2028")["open_interest"]) == 28, "a quiet month can still hold OI"

    def test_the_change_span_is_decoded_and_the_dash_variant_is_null(self):
        rows = day_body()["data"]
        assert T.strip_tags(rows[0][7]) == "+11.0000"
        assert T.parse_number(T.strip_tags(rows[0][7])) == 11.0
        assert T.strip_tags(rows[15][7]) == "-"
        assert pd.isna(T.parse_number(T.strip_tags(rows[15][7])))

    def test_the_name_div_is_decoded(self):
        assert T.strip_tags(day_body()["data"][0][1]) == "FCPO"
        assert T.strip_tags(night_body()["data"][0][1]) == "FCPO (T+1)"

    def test_number_parsing(self):
        assert T.parse_number("4,534.0000") == 4534.0
        assert T.parse_number("-36.0000") == pytest.approx(-36.0)
        assert T.parse_number("+11.0000") == pytest.approx(11.0)
        assert T.parse_number("1,025") == 1025.0
        for token in ("-", "", "  ", None):
            assert pd.isna(T.parse_number(token)), token


# ---------------------------------------------------------------------------
class TestSessionGuard:
    def test_the_night_payload_is_a_hard_error(self):
        """It is COMPLETE and PLAUSIBLE -- 24 months, Aug 2026 settling 4,557 against the day's
        4,540 -- so publishing it as the daily settlement is undetectable downstream."""
        with pytest.raises(ValueError, match=r"AFTER-HOURS"):
            T.build_bronze(_NIGHT.read_bytes(), code="FCPO", as_of_date=_AS_OF)

    def test_the_night_prices_really_do_differ(self):
        """The reason the label guard cannot be softened into a warning."""
        day = T.parse_number(T.strip_tags(day_body()["data"][0][12]))
        night = T.parse_number(T.strip_tags(night_body()["data"][0][12]))
        assert day == pytest.approx(4540.0) and night == pytest.approx(4557.0)
        assert day != night

    def test_one_night_row_in_an_otherwise_day_payload_is_still_refused(self):
        body = day_body()
        body["data"][7][1] = night_body()["data"][7][1]
        with pytest.raises(ValueError, match="AFTER-HOURS"):
            T.build_bronze(body, code="FCPO", as_of_date=_AS_OF)

    def test_another_instrument_in_the_payload_is_refused(self):
        body = day_body()
        body["data"][3][1] = "<div class='stock_change'><span class=\"up\"></span>FPKO</div>"
        with pytest.raises(ValueError, match="misfiled|code selector"):
            T.build_bronze(body, code="FCPO", as_of_date=_AS_OF)

    def test_the_day_session_is_pinned_and_is_not_an_operator_flag(self):
        """There is deliberately NO --ses. An operator who could pass 'night' would land
        after-hours prices under a day key, on a leg with no history to correct it from."""
        assert T.BURSA_DAY_SESSION == "day"
        assert "ses=day" in FETCH.api_path("FCPO")
        with pytest.raises(SystemExit):
            FETCH.main(["--dry-run", "--ses", "night"])


# ---------------------------------------------------------------------------
class TestTheadPinFailsClosed:
    def test_the_wrapped_capture_pins_the_header(self):
        df, stats = bronze(wrapped())
        assert len(df) == 24
        assert stats["thead_checked"] is True
        assert stats["header"] == ["no", "name", "month", "open", "bid", "ask", "last done",
                                   "change", "high", "low", "vol", "oi", "sett price"]

    def test_a_reordered_header_is_a_hard_error(self):
        """A HIGH/LOW swap keeps the count and the vocabulary identical and changes what every
        number MEANS. Position is the whole pin."""
        drifted = list(THEAD)
        drifted[8], drifted[9] = drifted[9], drifted[8]
        with pytest.raises(ValueError, match="drifted"):
            T.build_bronze(wrapped(thead=drifted), code="FCPO", as_of_date=_AS_OF)

    def test_an_inserted_column_is_a_hard_error(self):
        drifted = THEAD[:3] + ["PREV SETT"] + THEAD[3:]
        with pytest.raises(ValueError, match="expected 13"):
            T.build_bronze(wrapped(thead=drifted), code="FCPO", as_of_date=_AS_OF)

    def test_a_renamed_settlement_column_is_a_hard_error(self):
        drifted = list(THEAD)
        drifted[12] = "VWAP"
        with pytest.raises(ValueError, match="drifted"):
            T.build_bronze(wrapped(thead=drifted), code="FCPO", as_of_date=_AS_OF)

    def test_a_cosmetic_rewording_survives(self):
        """'VOL' -> 'VOLUME' and 'SETT. PRICE' -> 'Settlement Price' are the same columns. The pin
        is per-POSITION token sets, so re-wording is survivable and reordering is not."""
        reworded = list(THEAD)
        reworded[10], reworded[12] = "Volume", "Settlement Price"
        df, stats = T.build_bronze(wrapped(thead=reworded), code="FCPO", as_of_date=_AS_OF)
        assert len(df) == 24 and stats["thead_checked"] is True

    def test_a_bare_body_records_that_the_pin_could_not_run(self):
        """The captured fixture predates the side channel. That must be 'unavailable', never
        'passed'."""
        _df, stats = bronze()
        assert stats["thead_checked"] is False and stats["header"] == []

    def test_an_empty_thead_degrades_the_pin_and_never_the_prices(self):
        """THE DEFECT THIS FIXES. ``scrape_thead`` returns [] on ANY page-evaluate failure and the
        producer then lands ``{"thead": [], "api": body}`` -- by design, because a lost PIN must not
        cost a session on a leg whose API serves current prices only and has no re-fetch. Treating
        that [] as a 13-to-0 column DRIFT hard-failed the whole capture, leaving the landed object
        permanently unparseable until code shipped. It is 'unavailable', exactly like a bare body.
        The two halves are joined here on purpose: neither side's test could see this alone."""
        raw = FETCH.build_raw_object(FETCH.scrape_thead(_scrape_failure_session()), day_body())
        assert json.loads(raw.decode("utf-8"))["thead"] == []
        df, stats = T.build_bronze(raw, code="FCPO", as_of_date=_AS_OF)
        assert len(df) == 24 and stats["rows_with_settle"] == 24
        assert stats["thead_checked"] is False and stats["header"] == []

    def test_an_empty_label_row_in_a_multi_row_thead_is_also_unavailable(self):
        df, stats = T.build_bronze(wrapped(thead=[THEAD, []]), code="FCPO", as_of_date=_AS_OF)
        assert len(df) == 24 and stats["thead_checked"] is False

    def test_a_multi_row_thead_uses_the_label_row(self):
        df, stats = T.build_bronze(wrapped(thead=[["FCPO"] * 13, THEAD]),
                                   code="FCPO", as_of_date=_AS_OF)
        assert len(df) == 24 and stats["thead_checked"] is True

    def test_a_short_positional_row_is_a_hard_error(self):
        body = day_body()
        body["data"][2] = body["data"][2][:-1]
        with pytest.raises(ValueError, match="positional map cannot be trusted"):
            T.build_bronze(body, code="FCPO", as_of_date=_AS_OF)

    def test_a_paginated_body_is_a_hard_error(self):
        body = day_body()
        body["data"] = body["data"][:10]
        with pytest.raises(ValueError, match="recordsTotal"):
            T.build_bronze(body, code="FCPO", as_of_date=_AS_OF)

    def test_a_body_with_no_settlement_at_all_is_refused(self):
        body = day_body()
        for rec in body["data"]:
            rec[12] = "-"
        with pytest.raises(ValueError, match="not one of"):
            T.build_bronze(body, code="FCPO", as_of_date=_AS_OF)

    def test_a_malformed_wrapper_is_refused(self):
        with pytest.raises(ValueError, match="no 'api' object"):
            T.build_bronze(json.dumps({"thead": THEAD, "api": None}).encode("utf-8"),
                           code="FCPO", as_of_date=_AS_OF)
        with pytest.raises(ValueError, match="no 'data' array"):
            T.build_bronze({"recordsTotal": 0}, code="FCPO", as_of_date=_AS_OF)


# ---------------------------------------------------------------------------
class TestTheDateComesFromTheKey:
    def test_the_api_publishes_no_date_so_as_of_is_the_session(self):
        for as_of in ("2026-07-29", "2026-08-03"):
            df, stats = bronze(as_of=as_of)
            assert stats["trade_date"] == as_of
            assert set(df["trade_date"]) == {pd.Timestamp(as_of)}

    def test_a_missing_as_of_is_refused_rather_than_guessed(self):
        with pytest.raises(ValueError, match="as_of_date is required"):
            T.build_bronze(_DAY.read_bytes(), code="FCPO", as_of_date="")

    def test_the_body_really_carries_no_date_field(self):
        """The claim the whole as_of doctrine rests on: no date anywhere, so nothing can
        cross-check the key."""
        body = day_body()
        assert sorted(body) == ["data", "recordsFiltered", "recordsTotal"]
        blob = json.dumps(body).lower()
        for token in ("2026-07", "trade_date", "tradedate", "as of 2", "date\":"):
            assert token not in blob, token


# ---------------------------------------------------------------------------
class TestCodeMap:
    def test_the_code_map_is_bound_to_the_contract_map_both_ways(self):
        assert T._lint_code_map() == []
        assert set(T.BURSA_CODE_MAP.values()) == {
            s for s, r in FC.CONTRACT_MAP.items() if r["source"] == "bursa"}

    def test_the_slug_is_the_curated_one_and_the_labels_come_from_the_map(self):
        rec = FC.CONTRACT_MAP["malaysian_crude_palm_oil_cme"]
        assert T.BURSA_CODE_MAP == {"FCPO": "malaysian_crude_palm_oil_cme"}
        assert rec["unit"] == "MYR/t" and rec["currency"] == "MYR"
        assert rec["settle_kind"] == "settlement", "SETT. PRICE, not LAST DONE"
        df, _ = bronze()
        assert set(df["leviathan_slug"]) == {"malaysian_crude_palm_oil_cme"}

    def test_an_unmapped_code_is_refused(self):
        """FPKO / FSOY / FEPO / FPOL are on the venue's selector and are LATER legs."""
        for code in ("FPKO", "FSOY", "FEPO"):
            with pytest.raises(ValueError, match="not one of"):
                T.slug_for_code(code)


# ---------------------------------------------------------------------------
class TestProducer:
    def test_the_api_path_and_the_raw_key(self):
        assert FETCH.api_path("FCPO") == (
            "/api/v1/derivatives_prices/derivatives_prices"
            "?code=FCPO&ses=day&per_page=50&page=1")
        assert FETCH.api_url("FCPO").startswith("https://www.bursamalaysia.com/api/v1/")
        key = raw_bursa_key("FCPO", _AS_OF)
        assert key == ("raw/production/source=bursa/code=FCPO/"
                       "as_of_date=2026-07-29/derivatives_day.json")
        assert key.startswith(bursa_code_prefix("FCPO"))

    def test_the_live_prices_route_is_the_one_that_exists(self):
        """The recon-era /market/derivatives/derivatives_prices is a 404, and a 404 behind a
        challenge reads exactly like a challenge failure."""
        assert FETCH.BURSA_PRICES_PATH == "/market_information/derivatives_prices"

    def test_the_ready_check_needs_both_halves(self):
        """The interstitial swaps the title long before the cookie is usable, so 'the title
        changed' alone fires the API into a 403 and lands a challenge body as prices."""
        assert FETCH.is_challenge_title("Just a moment...") is True
        assert FETCH.is_challenge_title("") is True
        assert FETCH.is_challenge_title(None) is True
        assert FETCH.is_challenge_title("Derivatives Prices | Bursa Malaysia") is False
        probe = FETCH._api_probe_js("FCPO")
        assert "fetch(" in probe and FETCH.api_path("FCPO") in probe
        assert "r.status" in probe

        class _Page:
            def __init__(self, title, status):
                self._t, self._s = title, status

            def title(self):
                return self._t

            def evaluate(self, _js):
                return self._s

        ready = FETCH.challenge_cleared("FCPO")
        assert ready(_Page("Just a moment...", 200)) is False, "title still the interstitial"
        assert ready(_Page("Derivatives Prices", 403)) is False, "cookie not usable yet"
        assert ready(_Page("Derivatives Prices", 200)) is True

    def test_the_payload_sniff_accepts_the_day_and_refuses_the_night(self):
        assert FETCH.looks_like_a_day_payload(day_body(), code="FCPO") is None
        why = FETCH.looks_like_a_day_payload(night_body(), code="FCPO")
        assert why and "AFTER-HOURS" in why
        short = day_body()
        short["data"] = short["data"][:4]
        assert "truncated" in (FETCH.looks_like_a_day_payload(short, code="FCPO") or "")
        assert "not a derivatives_prices response" in (
            FETCH.looks_like_a_day_payload({"recordsTotal": 24}, code="FCPO") or "")

    def test_the_landed_wrapper_round_trips_through_the_transform(self):
        raw = FETCH.build_raw_object(THEAD, day_body())
        assert json.loads(raw.decode("utf-8"))["thead"] == THEAD
        df, stats = T.build_bronze(raw, code="FCPO", as_of_date=_AS_OF)
        assert len(df) == 24 and stats["thead_checked"] is True

    def test_the_thead_scrape_prefers_the_priced_table_and_never_raises(self):
        assert FETCH.scrape_thead(_StubSession(_StubPage(THEAD))) == THEAD
        # A scrape failure degrades the PIN, never the prices: this leg has no history to re-fetch.
        # That the TRANSFORM honours the [] rather than reading it as a drift is pinned in
        # TestTheadPinFailsClosed.
        assert FETCH.scrape_thead(_scrape_failure_session()) == []
        assert "SETT" in FETCH._THEAD_JS and "thead tr" in FETCH._THEAD_JS

    def test_a_backfill_invocation_gets_gate_8_and_not_a_silent_no_op(self):
        """The JSE precedent, for the identical case: no history exists, so an operator or a
        scheduler copying the CZCE/MIAX/DCE invocation must get the plan's gate-8 error."""
        with pytest.raises(NotImplementedError, match="no history"):
            FETCH.main(["--mode", "backfill", "--dry-run"])
        with pytest.raises(NotImplementedError):
            FETCH.refuse_backfill()
        assert FETCH.main(["--mode", "incremental", "--dry-run"]) == 0

    def test_the_flag_spellings_are_the_same_across_the_three_w1c_producers(self, capsys):
        """An operator or a scheduler copying an invocation between dce/euronext/bursa must not get
        an argparse error over a flag NAME. --headful and --headed were the live divergence."""
        producers = (
            (FETCH, ["--dry-run"]),
            (_load("jobs/ingest/fetch_euronext_eod.py", "fetch_euronext_flagcheck"), ["--dry-run"]),
            (_load("jobs/ingest/fetch_dce_eod.py", "fetch_dce_flagcheck"),
             ["--dry-run", "--mode", "daily"]),
        )
        for mod, base in producers:
            for flag in ("--force", "--skip-existing", "--headless", "--headful", "--headed"):
                assert mod.main([*base, flag]) == 0, f"{mod.__name__} rejected {flag}"
        capsys.readouterr()

    def test_the_task_enumeration_bound_is_the_transforms_code_map(self):
        """``futures_eod_task.BURSA_CODES`` duplicates BURSA_CODE_MAP's keys with no import binding
        them (the task imports the map lazily so the two W1c halves can land independently). A code
        added to CONTRACT_MAP would otherwise import-time-force the transform's map to grow while
        ``bursa_units`` silently stopped discovering that code's captures."""
        task = _load("jobs/batch/futures_eod_task.py", "futures_eod_task_bursa")
        assert task.BURSA_CODES == tuple(T.BURSA_CODE_MAP)

    def test_the_dry_run_touches_no_browser_and_no_aws(self, capsys):
        assert FETCH.main(["--dry-run", "--as-of-date", _AS_OF]) == 0
        out = capsys.readouterr().out
        assert FETCH.BURSA_PRICES_PATH in out
        assert "ses=day" in out
        assert raw_bursa_key("FCPO", _AS_OF) in out

    def test_the_challenge_exit_code_is_the_shared_one(self):
        assert FETCH.EXIT_CHALLENGE_FAILED == 7

    def test_the_size_floor_is_wired(self):
        from leviathan.common.constants import MIN_RAW_FILE_SIZES

        assert MIN_RAW_FILE_SIZES["bursa"] == 2_000

    def test_the_fixtures_are_not_mutated_by_any_test(self):
        """The helpers hand out fresh objects, so the mutation tests above cannot leak."""
        assert day_body() == copy.deepcopy(json.loads(_DAY.read_text(encoding="utf-8")))
        assert len(day_body()["data"]) == 24
