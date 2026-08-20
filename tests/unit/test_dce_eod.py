"""PRICE_AND_PLAYBOOKS W1c -- the DCE leg. Hermetic: no network, NO BROWSER, no AWS.

Every assertion below runs against the bytes captured live on 2026-07-29 and stored under
``tests/fixtures/w1c/`` (see ``capture_notes.md``): the daily quote body for palm olein and the real
2016 vendor history workbook. Nothing here launches Chromium -- W1c's browser plumbing is validated
by the first Fargate run BY DESIGN, through the ``CHALLENGE_FAILED`` exit code, and a test that
needed a browser would be a test that only ever runs on someone's laptop.

The traps this file pins are the ones that produce a plausible WRONG number rather than an error:

  * the daily fixture is the NOT_READY shape -- tradeDate already rolled to T+1 (20260730) with
    every settle at 0.0 -- so an unguarded parse writes a full board of zero prices dated into the
    FUTURE. It has to raise, and the producer has to skip it without landing anything;
  * ``0`` is the undefined-price sentinel in BOTH payloads and must become NULL, while a ``0``
    volume on an untraded day is a true count and must stay 0;
  * the history header is Chinese and PINNED: drift fails closed rather than silently re-reading
    column 8 as something else. Nothing in this file ever PRINTS that header -- the Windows console
    is cp1252 and a non-ASCII print crashes python -- so comparisons go through :func:`_esc`;
  * ``p1601`` is January 2016 in the 2016 workbook and ``p2608`` is August 2026 in a 2026 capture:
    the century anchor is the payload's own session, never the wall clock.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pandas as pd
import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.storage.paths import (
    dce_variety_prefix,
    raw_dce_daily_key,
    raw_dce_history_key,
)
from leviathan.transforms.raw_to_bronze import czce_eod as CZ
from leviathan.transforms.raw_to_bronze import dce_eod as T

_REPO = Path(__file__).resolve().parents[2]
_FIX = _REPO / "tests" / "fixtures" / "w1c"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TASK = _load("jobs/batch/futures_eod_task.py", "futures_eod_task_dce")
# Importing the PRODUCER is itself a test: playwright is not installed here, and the import must
# still succeed because every playwright import in this wave is lazy.
FETCH = _load("jobs/ingest/fetch_dce_eod.py", "fetch_dce_eod")

DAILY_RAW = (_FIX / "dce_futureData_p.json").read_bytes()
HISTORY_RAW = (_FIX / "dce_history_2016_p.xlsx").read_bytes()

# The workbook's own measurements, from the capture: 2,928 data rows + 1 header.
HISTORY_DATA_ROWS = 2928


def _esc(value) -> str:
    """ASCII-escaped rendering. Every comparison that could surface venue text goes through here so
    a FAILING assertion is still printable on a cp1252 console."""
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def settled_daily(payload: bytes = DAILY_RAW) -> bytes:
    """The fixture, moved forward to its POST-CLOSE state.

    The live capture caught the night session (every settle 0.0). The settled shape is the same
    board with ``settlePrice``/``closePrice`` populated -- which is what the producer will actually
    land -- so it is derived from the real bytes rather than hand-written."""
    obj = json.loads(payload.decode("utf-8"))
    for rec in obj["data"]:
        rec["settlePrice"] = rec["lastPrice"]
        rec["closePrice"] = rec["lastPrice"]
    return json.dumps(obj).encode("utf-8")      # ensure_ascii -> the Chinese msg lands as escapes


def history_workbook(rows, header=None) -> bytes:
    """A synthesized history workbook. Used ONLY to prove the header pin is not vacuous."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(T.HISTORY_HEADER if header is None else header))
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# A verbatim history row (the 2016-01-04 palm-olein front month), commodity-name cell replaced with
# ASCII because that column is never read.
_HISTORY_ROW = ["palm olein", "p1601", "20160104", "4,580", "4,580", "4,456", "4,498", "4,494",
                "4,500", "4", "6", "2,626", "48,926", "-1,792", "118,203,200"]


class FakeS3:
    """get_object / list_objects_v2 over an in-memory ``{key: bytes}`` map."""

    def __init__(self, objects: dict | None = None):
        self.objects = dict(objects or {})

    def get_object(self, *, Bucket, Key):  # noqa: N803 -- boto3 kwarg casing
        if Key not in self.objects:
            raise KeyError(Key)

        class _Body:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

        return {"Body": _Body(self.objects[Key])}

    def list_objects_v2(self, *, Bucket, Prefix, **kw):  # noqa: N803
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}


# ---------------------------------------------------------------------------
class TestVarietyMap:
    def test_it_is_exactly_the_five_dce_contracts_both_ways(self):
        assert T._lint_variety_map() == []
        curated = {s for s, r in FC.CONTRACT_MAP.items() if r["source"] == T.DCE_SOURCE}
        assert set(T.DCE_VARIETY_MAP.values()) == curated and len(curated) == 5

    def test_no_unit_authority_lives_in_the_transform(self):
        """The map carries slugs only; unit/currency/settle_kind/source come from CONTRACT_MAP."""
        for slug in T.DCE_VARIETY_MAP.values():
            rec = FC.contract_for(slug)
            assert rec["unit"] == "CNY/t" and rec["currency"] == "CNY"
            assert rec["settle_kind"] == "settlement" and rec["source"] == "dce"

    def test_both_parsers_emit_the_czce_bronze_shape(self):
        """One bronze shape across the two Chinese legs -- column for column."""
        assert T.BRONZE_COLUMNS == CZ.BRONZE_COLUMNS


# ---------------------------------------------------------------------------
class TestDailyNotReady:
    """THE guard. The fixture was captured mid-night-session, which is the dangerous state."""

    def test_the_fixture_is_the_not_ready_shape(self):
        records, envelope = T.daily_records(DAILY_RAW)
        assert len(records) == 12
        assert envelope["code"] == 200 and envelope["success"] is True
        # tradeDate has ALREADY rolled forward to T+1 while nothing has settled.
        assert {r["tradeDate"] for r in records} == {"20260730"}
        assert all(r["settlePrice"] == 0.0 for r in records)
        assert T.daily_not_ready(records) is True

    def test_parsing_it_is_a_hard_error_not_a_board_of_zeros(self):
        with pytest.raises(ValueError, match="NOT settled"):
            T.parse_dce_daily_json(DAILY_RAW, variety="p")

    def test_an_empty_board_is_not_ready_either(self):
        assert T.daily_not_ready([]) is True

    def test_one_unsettled_contract_among_real_ones_is_a_sentinel_not_a_timing_problem(self):
        obj = json.loads(settled_daily().decode("utf-8"))
        obj["data"][0]["settlePrice"] = 0.0
        payload = json.dumps(obj).encode("utf-8")
        records, _ = T.daily_records(payload)
        assert T.daily_not_ready(records) is False          # the board IS settled
        bronze, stats = T.parse_dce_daily_json(payload, variety="p")
        row = bronze[bronze["raw_symbol"] == "p2608"].iloc[0]
        assert pd.isna(row["settle"])                        # ...and that one cell is NULL
        assert stats["zero_price_cells"] >= 1


# ---------------------------------------------------------------------------
class TestDailyParse:
    @staticmethod
    def _bronze():
        return T.parse_dce_daily_json(settled_daily(), variety="p", as_of_date="2026-07-29")

    def test_every_contract_becomes_one_row_on_the_payloads_own_session(self):
        bronze, stats = self._bronze()
        assert len(bronze) == 12 and stats["contracts"] == 12
        assert set(bronze["leviathan_slug"]) == {"palm_olein_dce"}
        assert set(bronze["root"]) == {"p"}
        # The SESSION is the payload's tradeDate; the CAPTURE date only rides in the stats.
        assert set(bronze["trade_date"]) == {pd.Timestamp("2026-07-30")}
        assert stats["as_of_date"] == "2026-07-29" and stats["trade_date"] == "2026-07-30"
        assert list(bronze.columns) == T.BRONZE_COLUMNS

    def test_the_contract_code_decodes_to_a_delivery_month(self):
        bronze, _ = self._bronze()
        months = dict(zip(bronze["raw_symbol"], bronze["contract_month"]))
        assert months["p2608"] == "2026-08"
        assert months["p2612"] == "2026-12"
        assert months["p2701"] == "2027-01"      # the year rolls, the century does not
        assert months["p2707"] == "2027-07"

    def test_prev_settle_is_the_venues_own_field_and_never_a_computed_lag(self):
        bronze, _ = self._bronze()
        row = bronze[bronze["raw_symbol"] == "p2609"].iloc[0]
        assert row["prev_settle"] == pytest.approx(9349.0)   # preSettlePrice, verbatim
        assert row["open"] == pytest.approx(9400.0)
        assert row["high"] == pytest.approx(9416.0)
        assert row["low"] == pytest.approx(9348.0)
        assert row["volume"] == 127012 and row["open_interest"] == 365988

    def test_the_endpoint_publishes_no_turnover_and_no_oi_change_so_they_are_null(self):
        """NULL by SOURCE, never 0 -- a zero here would be a count this leg invented."""
        bronze, _ = self._bronze()
        assert bronze["turnover"].isna().all()
        assert bronze["oi_change"].isna().all()

    def test_a_body_served_for_another_variety_is_refused(self):
        """The defect this prevents: palm-olein prices landing under the soybean-oil slug."""
        with pytest.raises(ValueError, match="different board"):
            T.parse_dce_daily_json(settled_daily(), variety="y")

    def test_a_refused_envelope_is_a_hard_error(self):
        obj = json.loads(settled_daily().decode("utf-8"))
        obj["success"], obj["code"] = False, 500
        with pytest.raises(ValueError, match="refused the request"):
            T.parse_dce_daily_json(json.dumps(obj).encode("utf-8"), variety="p")

    def test_two_sessions_in_one_body_is_a_hard_error(self):
        obj = json.loads(settled_daily().decode("utf-8"))
        obj["data"][0]["tradeDate"] = "20260729"
        with pytest.raises(ValueError, match="distinct tradeDate"):
            T.parse_dce_daily_json(json.dumps(obj).encode("utf-8"), variety="p")


# ---------------------------------------------------------------------------
class TestHistoryParse:
    """The real 2016 vendor workbook: 188,440 B, one sheet, every cell an inlineStr."""

    @staticmethod
    def _bronze():
        return T.parse_dce_history_xlsx(HISTORY_RAW, variety="p", year=2016)

    def test_the_whole_year_lands_row_for_row(self):
        bronze, stats = self._bronze()
        assert len(bronze) == HISTORY_DATA_ROWS
        assert stats["grid_rows"] == HISTORY_DATA_ROWS + 1      # + the pinned header
        assert stats["rows_kept"] == HISTORY_DATA_ROWS
        assert stats["first_trade_date"] == "2016-01-04"
        assert stats["last_trade_date"] == "2016-12-30"
        assert set(bronze["leviathan_slug"]) == {"palm_olein_dce"}
        assert list(bronze.columns) == T.BRONZE_COLUMNS

    def test_the_spot_check_row_is_verbatim(self):
        """p1601 on 2016-01-04, cell for cell against the workbook -- comma separators stripped,
        nothing scaled, settle NOT the close."""
        bronze, _ = self._bronze()
        row = bronze[(bronze["raw_symbol"] == "p1601")
                     & (bronze["trade_date"] == pd.Timestamp("2016-01-04"))].iloc[0]
        assert row["open"] == pytest.approx(4580.0)
        assert row["high"] == pytest.approx(4580.0)
        assert row["low"] == pytest.approx(4456.0)
        assert row["close"] == pytest.approx(4498.0)
        assert row["prev_settle"] == pytest.approx(4494.0)
        assert row["settle"] == pytest.approx(4500.0)
        assert row["volume"] == 2626
        assert row["open_interest"] == 48926
        assert row["oi_change"] == -1792
        assert row["turnover"] == pytest.approx(118203200.0)
        assert row["contract_month"] == "2016-01"

    def test_an_untraded_day_nulls_the_prices_and_keeps_the_zero_counts(self):
        """p1602 on 2016-01-04: open/high/low print "0" while close and settle are real."""
        bronze, stats = self._bronze()
        row = bronze[(bronze["raw_symbol"] == "p1602")
                     & (bronze["trade_date"] == pd.Timestamp("2016-01-04"))].iloc[0]
        assert pd.isna(row["open"]) and pd.isna(row["high"]) and pd.isna(row["low"])
        assert row["close"] == pytest.approx(4732.0)          # still published
        assert row["settle"] == pytest.approx(4732.0)
        assert row["prev_settle"] == pytest.approx(4726.0)
        # Counts are NOT masked: a zero volume IS the observation that it did not trade.
        assert row["volume"] == 0 and not pd.isna(row["volume"])
        assert row["open_interest"] == 26
        assert stats["zero_price_cells"] > 0

    def test_the_untraded_shape_is_the_majority_of_the_year_and_is_measured(self):
        """1,695 of the 2,928 rows carry a zero open. If that ever silently became 0.0 prices, the
        whole back of the curve would read as a crash."""
        bronze, _ = self._bronze()
        assert int(bronze["open"].isna().sum()) == 1695
        assert int(bronze["settle"].isna().sum()) == 0        # settle always prints

    def test_the_century_anchor_is_the_rows_own_session(self):
        bronze, _ = self._bronze()
        months = set(bronze[bronze["raw_symbol"] == "p1712"]["contract_month"])
        assert months == {"2017-12"}                          # a 2017 contract in the 2016 file
        assert T.resolve_contract_year(16, "2016-01-04") == 2016
        assert T.resolve_contract_year(1, "2099-12-31") == 2101   # across the century, forward
        assert T.resolve_contract_year(99, "2101-01-04") == 2099  # and backward

    def test_every_contract_belongs_to_the_requested_variety(self):
        bronze, _ = self._bronze()
        assert set(bronze["root"]) == {"p"}
        assert all(str(s).startswith("p") for s in bronze["raw_symbol"])


# ---------------------------------------------------------------------------
class TestHeaderPin:
    """Fail-closed on header drift -- and the pin is proven non-vacuous both ways."""

    def test_the_real_workbooks_header_is_the_pinned_one(self):
        grid, sheet = T.read_history_grid(HISTORY_RAW)
        got = tuple(str(c).strip() for c in grid[0])
        assert [_esc(c) for c in got] == [_esc(c) for c in T.HISTORY_HEADER]
        assert len(T.HISTORY_HEADER) == T.HISTORY_COLUMN_COUNT == 15
        assert _esc(sheet)                                     # non-empty, and printable

    def test_the_pinned_header_is_source_ascii(self):
        """The module is read on a cp1252 console; the header lives there as \\u escapes."""
        src = (_REPO / "src" / "leviathan" / "transforms" / "raw_to_bronze"
               / "dce_eod.py").read_bytes()
        assert all(b < 128 for b in src), "dce_eod.py must stay pure ASCII"

    def test_a_renamed_column_fails_closed(self):
        drifted = list(T.HISTORY_HEADER)
        drifted[8] = drifted[8] + "X"            # the SETTLE column, renamed
        with pytest.raises(ValueError, match="header row drifted"):
            T.assert_history_header(drifted)
        with pytest.raises(ValueError, match="header row drifted"):
            T.parse_dce_history_xlsx(history_workbook([_HISTORY_ROW], header=drifted), variety="p")

    def test_a_dropped_column_fails_closed(self):
        with pytest.raises(ValueError, match="header row drifted"):
            T.assert_history_header(list(T.HISTORY_HEADER[:-1]))

    def test_the_drift_message_is_ascii_and_still_shows_the_drift(self):
        drifted = list(T.HISTORY_HEADER)
        drifted[0] = "REPLACED"
        with pytest.raises(ValueError) as err:
            T.assert_history_header(drifted)
        text = str(err.value)
        assert all(ord(c) < 128 for c in text), "the drift message must be cp1252-printable"
        assert "col0" in text and "REPLACED" in text and "\\u" in text

    def test_a_workbook_with_the_pinned_header_parses(self):
        bronze, _ = T.parse_dce_history_xlsx(history_workbook([_HISTORY_ROW]), variety="p")
        assert len(bronze) == 1
        assert bronze.iloc[0]["settle"] == pytest.approx(4500.0)


# ---------------------------------------------------------------------------
class TestTaskWiring:
    """The --source host: unit discovery from the LANDED prefix, and the key-driven dispatch."""

    @staticmethod
    def _objects():
        return {
            raw_dce_history_key("p", 2016): HISTORY_RAW,
            raw_dce_daily_key("p", "2026-07-28"): settled_daily(),
            raw_dce_daily_key("p", "2026-07-29"): settled_daily(),
        }

    def test_history_units_come_first(self):
        """Same reason as CEPEA: the workbook covers days the daily capture also has, and the last
        row wins, so the fresher post-close observation must arrive last."""
        keys = TASK.dce_units(FakeS3(self._objects()), "b")
        assert "/history/" in keys[0]
        assert all("/history/" not in k for k in keys[1:])
        assert keys[1:] == sorted(k for k in self._objects() if "/history/" not in k)

    def test_a_bounded_incremental_run_skips_the_history_workbooks(self):
        keys = TASK.dce_units(FakeS3(self._objects()), "b", since="2026-07-29")
        assert keys == [raw_dce_daily_key("p", "2026-07-29")]

    def test_the_loader_dispatches_on_the_key_never_on_the_bytes(self):
        s3 = FakeS3(self._objects())
        daily, dstats = TASK.load_dce_capture(s3, "b", raw_dce_daily_key("p", "2026-07-29"))
        hist, hstats = TASK.load_dce_capture(s3, "b", raw_dce_history_key("p", 2016))
        assert dstats["kind"] == "daily" and len(daily) == 12
        assert hstats["kind"] == "history" and len(hist) == HISTORY_DATA_ROWS
        assert hstats["year"] == 2016 and hstats["variety"] == "p"

    def test_a_key_with_no_variety_segment_refuses_to_guess(self):
        with pytest.raises(ValueError, match="variety="):
            TASK.load_dce_capture(FakeS3(), "b", "raw/production/source=dce/futureData.json")

    def test_a_missing_object_is_an_honest_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            TASK.load_dce_capture(FakeS3(), "b", raw_dce_daily_key("p", "2026-07-29"))

    def test_the_leg_is_wired_end_to_end_with_its_own_floor_state(self):
        """IMPLEMENTED is not ARMED, and the two must not be conflated. The bronze -> silver half
        landed (``transforms/bronze_to_silver/dce_eod.py``, exercised by
        ``tests/unit/test_dce_eod_silver.py``), so the spec no longer refuses the source -- but the
        per-day row floor stays 0 because only ONE of the five varieties has ever been captured
        live. Any number there would sit somewhere between 'correct' and 'four varieties silently
        missing', which is the F-C trap the JSE floor of 20 was."""
        from leviathan.transforms.bronze_to_silver.dce_eod import build_dce_eod_silver

        spec = TASK.source_spec("dce")
        assert spec.publication_sources == ("dce",)
        assert spec.rows_per_day == 0, "the DCE day floor is unmeasured -- do not guess one"
        assert spec.implemented and spec.todo == ""
        assert TASK._silver_builder("dce") is build_dce_eod_silver

    def test_the_raw_prefixes_are_the_curated_layout(self):
        assert dce_variety_prefix("p") == "raw/production/source=dce/variety=p/"
        assert raw_dce_daily_key("p", "2026-07-29").startswith(dce_variety_prefix("p"))
        assert raw_dce_history_key("p", 2016).endswith("/history/year=2016/p_ftr.xlsx")


# ---------------------------------------------------------------------------
class TestProducer:
    """The fetch job, WITHOUT a browser: argument resolution, the plan, and the exit vocabulary."""

    def test_the_exit_codes_are_distinct_and_meaningful(self):
        assert FETCH.EXIT_NOT_READY == 5
        assert FETCH.EXIT_CHALLENGE_FAILED == 7
        assert FETCH.EXIT_NOT_READY != FETCH.EXIT_CHALLENGE_FAILED

    def test_a_session_can_be_built_without_launching_anything(self):
        """Every playwright import in this wave is LAZY and lives in ``__enter__``: importing this
        producer, and constructing its session, must not start a driver -- which is what lets the
        whole suite run on a machine with no browser installed."""
        from leviathan.ingest.browser_fetch import BrowserSession

        session = BrowserSession(FETCH.DCE_BASE_URL)
        assert session._pw is None and session._browser is None
        assert session.url_for("/dcereport/x") == FETCH.DCE_BASE_URL + "/dcereport/x"
        assert session.url_for("https://elsewhere/x") == "https://elsewhere/x"
        with pytest.raises(RuntimeError, match="not open"):
            _ = session.page

    def test_an_unknown_variety_is_refused_before_anything_else(self):
        with pytest.raises(SystemExit):
            FETCH.resolve_varieties(["p", "zz"])
        assert FETCH.resolve_varieties(None) == sorted(T.DCE_VARIETY_MAP)
        assert FETCH.resolve_varieties(["y", "p", "p"]) == ["p", "y"]

    def test_the_daily_dry_run_prints_the_plan_and_touches_nothing(self, capsys):
        assert FETCH.main(["--mode", "daily", "--as-of-date", "2026-07-29", "--variety", "p",
                           "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert raw_dce_daily_key("p", "2026-07-29") in out
        assert "variety=p" in out and "no browser" in out

    def test_the_history_dry_run_counts_the_units(self, capsys):
        assert FETCH.main(["--mode", "history", "--year-start", "2015", "--year-end", "2016",
                           "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "units     : 10" in out                    # 5 varieties x 2 years
        assert raw_dce_history_key("a", 2015) in out

    def test_an_error_document_never_lands_as_a_workbook(self):
        assert FETCH.looks_like_a_workbook(HISTORY_RAW) is None
        assert FETCH.looks_like_a_workbook(b"<html>challenge</html>") is not None

    def test_the_endpoints_are_the_captured_ones(self):
        assert FETCH.DAILY_PATH.format(variety="p") == \
            "/dcereport/quote/delay/futureData?variety=p"
        assert FETCH.HISTORY_PATH.format(year=2016, variety="p") == \
            "/dcereport/quote/history/download?type=1&year=2016&variety=p"


# ---------------------------------------------------------------------------
class _StubSession:
    """A BrowserSession, as far as ``main()`` can tell. No playwright, no driver, no network.

    ``settle`` is either None (the challenge cleared) or an exception instance to raise from
    ``goto_and_settle``; ``body`` is what an in-page fetch returns."""

    def __init__(self, *, settle=None, body: bytes = b"{}"):
        self._settle = settle
        self._body = body
        self.entered = False

    def __call__(self, base_url, *, headless=True):
        self.base_url = base_url
        return self

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        return None

    def url_for(self, path: str) -> str:
        return "http://www.dce.com.cn" + path

    def goto_and_settle(self, _url, *, ready_check, max_wait_s=90):
        if self._settle is not None:
            raise self._settle

    def fetch_text(self, _path, accept=None):
        return self._body.decode("utf-8")


class TestTheExitCodeTranslations:
    """The two translations the whole wave rests on, exercised through ``main()``.

    Asserting the CONSTANTS (5 and 7) proves only that two integers differ. What the residual-S2
    probe design and the never-land-a-zero-settle-board guard actually promise is that main()
    RETURNS them, and writes nothing when it does."""

    @staticmethod
    def _run(monkeypatch, session, *extra) -> tuple[int, list]:
        written: list = []
        monkeypatch.setattr(FETCH, "BrowserSession", session)
        monkeypatch.setattr(FETCH, "raw_exists", lambda bucket, key, region: False)
        monkeypatch.setattr(FETCH, "land_bytes",
                            lambda *a, **kw: written.append(kw.get("source_url") or a))
        rc = FETCH.main(["--mode", "daily", "--as-of-date", "2026-07-29", "--variety", "p",
                         "--sleep", "0", "--bucket", "b", "--aws-region", "us-east-1", *extra])
        return rc, written

    def test_an_unsettled_challenge_is_rc_7_and_writes_nothing(self, monkeypatch):
        """THE RESIDUAL S2 PROBE. The first Fargate run of this producer IS the answer, so the
        exception has to survive all the way out to an exit code and land no object on the way."""
        from leviathan.ingest.browser_fetch import ChallengeFailed

        rc, written = self._run(monkeypatch,
                                _StubSession(settle=ChallengeFailed("never settled")))
        assert rc == FETCH.EXIT_CHALLENGE_FAILED == 7
        assert written == []

    def test_a_navigation_failure_is_rc_1_and_is_NOT_the_s2_answer(self, monkeypatch):
        """A DNS/egress/TLS failure exiting 7 would read -- to a human skimming CloudWatch and to
        any metric filter on the exit code -- as a NEGATIVE answer to the question the run exists
        to ask. A broken route is not evidence about a WAF."""
        from leviathan.ingest.browser_fetch import NavigationFailed

        rc, written = self._run(monkeypatch,
                                _StubSession(settle=NavigationFailed("net::ERR_NAME_NOT_RESOLVED")))
        assert rc == 1 and rc != FETCH.EXIT_CHALLENGE_FAILED
        assert written == []

    def test_an_all_zero_settle_board_is_rc_5_and_writes_nothing(self, monkeypatch):
        """The night-session shape, verbatim from the fixture: a full, well-formed, entirely
        FICTIONAL board whose tradeDate has already rolled to T+1. Landing it is the defect."""
        rc, written = self._run(monkeypatch, _StubSession(body=DAILY_RAW))
        assert rc == FETCH.EXIT_NOT_READY == 5
        assert written == []

    def test_a_settled_board_lands_and_is_rc_0(self, monkeypatch):
        """The negative control: the same path with settlements present writes exactly one object,
        so the two guards above are refusing a real capture and not an inert one."""
        rc, written = self._run(monkeypatch, _StubSession(body=settled_daily()))
        assert rc == 0 and len(written) == 1


# ---------------------------------------------------------------------------
# The existence probe FAILS CLOSED -- TWO verdicts, one producer
# ---------------------------------------------------------------------------
class _StubHistorySession(_StubSession):
    """``_StubSession`` plus the ``download`` the history mode calls."""

    def __init__(self, *, workbook: bytes = HISTORY_RAW, **kw):
        super().__init__(**kw)
        self._workbook = workbook
        self.downloaded: list[str] = []

    def download(self, path: str) -> bytes:
        self.downloaded.append(path)
        return self._workbook


class _NoBrowser:
    """A BrowserSession that must never be constructed. A run that captured nothing has no
    business paying for a Chromium start, let alone re-clearing the venue's WAF."""

    def __call__(self, *a, **kw):
        raise AssertionError("a run that captured nothing must never launch Chromium")


class TestRawExistsFailsClosed:
    """``raw_exists`` gates every PUT on this leg and is called from BOTH mode loops.

    The recoverability answer DIFFERS BY MODE and the producer records both rather than averaging
    them: ``--mode daily`` is the EEX argument at full strength (``/quote/delay/futureData`` takes
    NO date parameter -- it serves the CURRENT board, which is why the raw key is the capture date),
    while ``--mode history`` is the weaker resume-contract case (the vendor workbooks are
    deterministic per (variety, year) and re-downloadable).

    The call sites sit in the pre-browser selection pass, which makes the exit-0 fall-through the
    real trap: a run whose probes ALL threw would otherwise reach "nothing to fetch -- every
    selected unit is already landed" and exit 0, reporting a run that proved nothing as complete.
    That is the same defect the euronext fix found tonight."""

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

    _AS_OF = "2026-07-29"

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
        """Fail closed. Failing the unit costs a re-fire; on --mode daily, treating a throttled
        head as 'absent' costs a board this endpoint cannot serve again."""
        from botocore.exceptions import ClientError
        self._s3(monkeypatch, lambda _key: self._client_error(code, status))
        with pytest.raises(ClientError):
            FETCH.raw_exists("b", "k", "us-east-1")

    # -- probe_landed: the three-state answer both call sites need ---------------------------
    def test_probe_landed_answers_None_when_the_head_cannot_answer(self, monkeypatch):
        """``None`` is NOT ``False``. Returning False here would put the unit back on the pending
        list and lead it straight to a fetch and a PUT -- the very overwrite being prevented."""
        failures: list[str] = []
        self._s3(monkeypatch, lambda _key: self._client_error("SlowDown", 503))
        assert FETCH.probe_landed("b", "k", "us-east-1", unit="p", failures=failures) is None
        assert failures == ["p: existence probe ClientError"]

    def test_probe_landed_answers_False_only_on_a_real_404(self, monkeypatch):
        failures: list[str] = []
        self._s3(monkeypatch, lambda _key: self._client_error("404", 404))
        assert FETCH.probe_landed("b", "k", "us-east-1", unit="p", failures=failures) is False
        assert failures == []

    # -- --mode daily -----------------------------------------------------------------------
    @staticmethod
    def _drive_daily(monkeypatch, raiser, session, *extra):
        written: list[str] = []
        TestRawExistsFailsClosed._s3(monkeypatch, raiser)
        monkeypatch.setattr(FETCH, "BrowserSession", session)
        monkeypatch.setattr(FETCH, "land_bytes",
                            lambda bucket, key, data, **kw: written.append(key))
        rc = FETCH.main(["--mode", "daily", "--as-of-date", TestRawExistsFailsClosed._AS_OF,
                         "--sleep", "0", "--bucket", "b", "--aws-region", "us-east-1", *extra])
        return rc, written

    def test_daily_a_transient_head_failure_never_reaches_the_PUT(self, monkeypatch):
        """End to end: every probe throttles, so nothing is pending, NOTHING is written, Chromium
        is never launched -- and the run exits 1 rather than taking the "nothing to fetch" exit 0
        that the naive narrowing would have fallen through to."""
        rc, written = self._drive_daily(monkeypatch,
                                        lambda _k: self._client_error("SlowDown", 503),
                                        _NoBrowser())
        assert rc == 1, "an all-probes-threw run must never be reported as 'already landed'"
        assert written == []

    def test_daily_one_unanswerable_probe_never_costs_the_other_varieties(self, monkeypatch):
        """The blocked variety is taken out as a recorded failure -- not fetched, not written --
        while the four whose probe answered 404 are captured. The run still exits 1."""
        blocked = raw_dce_daily_key("p", self._AS_OF)
        rc, written = self._drive_daily(
            monkeypatch,
            lambda key: (self._client_error("ExpiredToken", 400) if key == blocked
                         else self._client_error("404", 404)),
            _StubSession(body=settled_daily()))
        assert rc == 1
        assert blocked not in written, "the unanswerable variety must never be captured"
        assert sorted(written) == sorted(raw_dce_daily_key(v, self._AS_OF)
                                         for v in ("a", "b", "m", "y"))

    def test_daily_the_same_drive_lands_all_five_when_the_head_answers_404(self, monkeypatch):
        """The positive control, so the two tests above cannot pass vacuously."""
        rc, written = self._drive_daily(monkeypatch, lambda _k: self._client_error("404", 404),
                                        _StubSession(body=settled_daily()))
        assert rc == 0
        assert sorted(written) == sorted(raw_dce_daily_key(v, self._AS_OF)
                                         for v in ("a", "b", "m", "p", "y"))

    def test_daily_an_all_landed_window_still_takes_the_clean_exit_0(self, monkeypatch):
        """The "nothing to fetch" path is intact where it is TRUE: heads that answer 'present'
        skip everything, no browser starts, and the run is genuinely clean."""
        rc, written = self._drive_daily(monkeypatch, lambda _k: None, _NoBrowser())
        assert rc == 0 and written == []

    def test_daily_a_probe_failure_outranks_the_retryable_NOT_READY_code(self, monkeypatch):
        """A run that could not read S3 must exit 1, not the retryable 5 -- whatever the boards
        were doing. Here one variety's probe throttles and the rest serve the night-session
        all-zero board, so both conditions are live at once and the S3 fault has to win."""
        blocked = raw_dce_daily_key("p", self._AS_OF)
        rc, written = self._drive_daily(
            monkeypatch,
            lambda key: (self._client_error("SlowDown", 503) if key == blocked
                         else self._client_error("404", 404)),
            _StubSession(body=DAILY_RAW))
        assert rc == 1 and rc != FETCH.EXIT_NOT_READY
        assert written == []

    def test_force_bypasses_the_probe_entirely(self, monkeypatch):
        """PINNED. ``--force`` sets skip_existing=False and the call sites read
        ``if args.skip_existing else False``, so raw_exists is never called on a forced run --
        which is exactly why the always-on lane (``--mode daily --force``) never touched this path
        and why the fix binds the NON-force Batch submissions instead."""
        rc, written = self._drive_daily(monkeypatch,
                                        lambda _k: self._client_error("SlowDown", 503),
                                        _StubSession(body=settled_daily()), "--force")
        assert rc == 0
        assert sorted(written) == sorted(raw_dce_daily_key(v, self._AS_OF)
                                         for v in ("a", "b", "m", "p", "y"))

    # -- --mode history ---------------------------------------------------------------------
    @staticmethod
    def _drive_history(monkeypatch, raiser, session, *extra):
        written: list[str] = []
        TestRawExistsFailsClosed._s3(monkeypatch, raiser)
        monkeypatch.setattr(FETCH, "BrowserSession", session)
        monkeypatch.setattr(FETCH, "land_bytes",
                            lambda bucket, key, data, **kw: written.append(key))
        rc = FETCH.main(["--mode", "history", "--variety", "p",
                         "--year-start", "2016", "--year-end", "2017",
                         "--sleep", "0", "--bucket", "b", "--aws-region", "us-east-1", *extra])
        return rc, written

    def test_history_a_transient_head_failure_never_reaches_the_PUT(self, monkeypatch):
        """The second call site. Same contract: nothing pending, nothing written, no Chromium, and
        exit 1 rather than the "nothing to fetch" exit 0."""
        rc, written = self._drive_history(monkeypatch,
                                          lambda _k: self._client_error("SlowDown", 503),
                                          _NoBrowser())
        assert rc == 1
        assert written == []

    def test_history_one_units_unanswerable_probe_never_costs_the_others(self, monkeypatch):
        blocked = raw_dce_history_key("p", 2016)
        rc, written = self._drive_history(
            monkeypatch,
            lambda key: (self._client_error("InternalError", 500) if key == blocked
                         else self._client_error("404", 404)),
            _StubHistorySession())
        assert rc == 1
        assert written == [raw_dce_history_key("p", 2017)]

    def test_history_the_same_drive_lands_both_when_the_head_answers_404(self, monkeypatch):
        """The positive control for the history call site."""
        rc, written = self._drive_history(monkeypatch, lambda _k: self._client_error("404", 404),
                                          _StubHistorySession())
        assert rc == 0
        assert sorted(written) == [raw_dce_history_key("p", y) for y in (2016, 2017)]
