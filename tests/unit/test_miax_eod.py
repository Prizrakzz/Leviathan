"""PRICE_AND_PLAYBOOKS W1b -- the MIAX Futures (ex-MGEX) HRSW leg. Hermetic: no network, no AWS.

The fixture is the VERBATIM live payload (fetched 2026-07-28 and re-read 2026-07-29: HTTP 200,
``text/csv``, 6,676 B, 76 lines) reduced to the 7 outrights plus a representative slice of the 68
option rows. Every number below is a real published settlement.

The two facts this file exists to pin are the two that would otherwise produce a wrong number
rather than an error:

  * the file publishes DOLLARS per bushel (``7.0250``), not CBOT cents (~430) -- a factor of 100,
    and the label moves to the data rather than the data being scaled to the label;
  * options and outrights share one file, and the discriminator is structural, not a prefix.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import miax_daily_filename, miax_year_prefix, raw_miax_key
from leviathan.transforms.bronze_to_silver import miax_eod as S
from leviathan.transforms.raw_to_bronze import miax_eod as T

_REPO = Path(__file__).resolve().parents[2]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TASK = _load("jobs/batch/futures_eod_task.py", "futures_eod_task_miax")
FETCH = _load("jobs/ingest/fetch_miax_eod.py", "fetch_miax_eod")

_HEADER = ('"Trade_Date","Instrument","Prev_Settle","Open","High","Low","Settle","Change",'
           '"Last_Update_DateTime"')
# The 7 outrights of 2026-07-28, verbatim. H/K/N/U/Z across two years -- the complete listed cycle.
_OUTRIGHTS = [
    '"7/28/26","MWEH7","7.4400","7.4325","7.4400","7.3650","7.4100","-0.0300","7/28/2026 2:35:30 PM"',
    '"7/28/26","MWEK7","7.5375","7.4825","7.5300","7.4600","7.5000","-0.0375","7/28/2026 2:35:30 PM"',
    '"7/28/26","MWEN7","7.5550","7.5200","7.5200","7.5200","7.5075","-0.0475","7/28/2026 2:35:30 PM"',
    '"7/28/26","MWEU6","7.0625","7.0400","7.0600","6.9550","7.0250","-0.0375","7/28/2026 2:35:30 PM"',
    '"7/28/26","MWEU7","7.4450","7.3800","7.4425","7.3800","7.4350","-0.0100","7/28/2026 2:35:30 PM"',
    '"7/28/26","MWEZ6","7.2850","7.2950","7.2950","7.1950","7.2525","-0.0325","7/28/2026 2:35:30 PM"',
    '"7/28/26","MWEZ7","7.4575","7.4075","7.4250","7.4075","7.4475","-0.0100","7/28/2026 2:35:30 PM"',
]
# Option rows, verbatim. Note the EMPTY (never zero) Open/High/Low and the space in the token.
_OPTIONS = [
    '"7/28/26","OMWH7 C6.50","1.14000","","","","1.10375","-0.03625","7/28/2026 2:35:30 PM"',
    '"7/28/26","OMWH7 C7.00","0.84500","","","","0.80875","-0.03625","7/28/2026 2:35:30 PM"',
    '"7/28/26","OMWU6 P7.00","0.12500","","","","0.13250","0.00750","7/28/2026 2:35:30 PM"',
    '"7/28/26","OMWZ6 C7.50","0.21000","","","","0.19875","-0.01125","7/28/2026 2:35:30 PM"',
]


def settlement_csv(date: str = "7/28/26", *, outrights=None, options=None) -> bytes:
    rows = list(_OUTRIGHTS if outrights is None else outrights)
    rows += list(_OPTIONS if options is None else options)
    rows = [r.replace('"7/28/26"', f'"{date}"', 1) for r in rows]
    return ("\r\n".join([_HEADER] + rows) + "\r\n").encode("utf-8")


# ---------------------------------------------------------------------------
class TestOutrightFilter:
    def test_seven_outrights_out_of_seventy_five_rows(self):
        bronze, stats = T.build_miax_bronze(settlement_csv(), trade_date="2026-07-28")
        assert stats["rows_kept"] == 7 == len(bronze)
        assert stats["option_rows"] == len(_OPTIONS)
        assert stats["roots_seen"] == ["MWE"]
        assert sorted(bronze["raw_symbol"]) == ["MWEH7", "MWEK7", "MWEN7", "MWEU6", "MWEU7",
                                                "MWEZ6", "MWEZ7"]

    def test_the_discriminator_is_structural_not_a_prefix(self):
        """The option roots are OMWH / OMWU / OMWZ. An 'MW' prefix test catches all 68 of them and
        lands strike rows as if they were delivery months."""
        assert T.is_outright("MWEU6") is True
        for token in ("OMWH7 C6.50", "OMWU6 P7.00", "MWEU", "MWEU66", "", "MWE U6"):
            assert T.is_outright(token) is False, token
        assert all(t.startswith("MW") or t.startswith("OMW") for t in ("MWEU6", "OMWH7"))

    def test_the_delivery_cycle_matches_the_curated_tuple(self):
        """_cycle_eligible FILTERS ROWS OUT, so a listed month absent from the curated cycle would
        vanish from front_month with no error at all."""
        from leviathan.silver import futures_roll as FR

        bronze, _ = T.build_miax_bronze(settlement_csv(), trade_date="2026-07-28")
        listed = sorted({int(m.split("-")[1]) for m in bronze["contract_month"]})
        assert listed == sorted(FR.delivery_cycle_for("hard_red_spring_wheat_mgex"))
        assert listed == [3, 5, 7, 9, 12]

    def test_the_root_map_is_bound_to_the_contract_map_both_ways(self):
        assert T._lint_root_map() == []
        assert set(T.MIAX_ROOT_MAP.values()) == {
            s for s, r in FC.CONTRACT_MAP.items() if r["source"] == "miax"}


class TestDecadeAnchor:
    def test_the_single_year_digit_is_anchored_on_the_file_date(self):
        assert T.contract_month_str("U", "6", "2026-07-28") == "2026-09"
        assert T.contract_month_str("Z", "7", "2026-07-28") == "2027-12"
        assert T.contract_month_str("U", "6", "2016-07-28") == "2016-09"

    def test_a_re_run_decades_later_decodes_identically(self):
        for anchor in ("2026-01-02", "2026-07-28", "2026-12-30"):
            assert T.contract_month_str("U", "6", anchor) == "2026-09"

    def test_the_decade_boundary(self):
        assert T.resolve_contract_year(0, "2029-12-20") == 2030
        assert T.resolve_contract_year(9, "2030-01-05") == 2029

    def test_the_two_digit_trade_date(self):
        assert T.resolve_trade_date("7/28/26") == "2026-07-28"
        assert T.resolve_trade_date("12/1/25") == "2025-12-01"
        assert T.resolve_trade_date("7/28/2026") == "2026-07-28"
        with pytest.raises(ValueError, match="M/D/YY"):
            T.resolve_trade_date("2026-07-28")

    def test_a_misfiled_object_is_a_hard_error(self):
        with pytest.raises(ValueError, match="misfiled"):
            T.build_miax_bronze(settlement_csv(), trade_date="2026-07-27")

    def test_a_changed_header_refuses_the_name_based_map(self):
        payload = settlement_csv().replace(b'"Settle"', b'"SettlementPrice"')
        with pytest.raises(ValueError, match="missing column"):
            T.build_miax_bronze(payload, trade_date="2026-07-28")


# ---------------------------------------------------------------------------
class TestSilverProjection:
    @staticmethod
    def _silver(date: str = "2026-07-28"):
        stamp = f"{pd.Timestamp(date).month}/{pd.Timestamp(date).day}/{pd.Timestamp(date).year % 100:02d}"
        bronze, _ = T.build_miax_bronze(settlement_csv(stamp), trade_date=date)
        return S.build_miax_eod_silver(bronze)

    def test_shape_and_labels(self):
        df = self._silver()
        assert list(df.columns) == FC.SILVER_COLUMNS
        assert set(df["instrument_kind"]) == {"futures"}
        assert set(df["settle_kind"]) == {"settlement"}, "a TRUE settlement, unlike the ICE legs"
        assert set(df["source"]) == {"miax"}
        assert set(df["currency"]) == {"USD"}
        assert df["contract_month"].notna().all()
        assert df["expiry_date"].isna().all() and df["dataset"].isna().all()

    def test_the_unit_is_dollars_per_bushel_and_the_value_is_never_scaled(self):
        """THE UNIT DECISION. MIAX publishes 7.0250 where CBOT publishes ~430 for the same grain:
        dollars, not cents, a factor of 100 apart. Source-faithful wins, so the VOCABULARY widened
        (the CAD/t canola precedent) and the number stayed exactly as published."""
        df = self._silver()
        assert set(df["unit"]) == {"USD/bushel"}
        sep = df[df["raw_symbol"] == "MWEU6"].iloc[0]
        assert float(sep["settle"]) == pytest.approx(7.0250), "NEVER 702.50"
        assert 1.0 < float(df["settle"].max()) < 20.0

    def test_the_unit_three_way_bind_is_green(self):
        """map == tracked lint constant == the numbers card, all three."""
        from leviathan.graphrag.config_check import (
            _FUTURES_EOD_UNIT_OVERRIDES,
            check_futures_eod,
        )

        assert FC.CONTRACT_MAP["hard_red_spring_wheat_mgex"]["unit"] == "USD/bushel"
        assert _FUTURES_EOD_UNIT_OVERRIDES["hard_red_spring_wheat_mgex"] == "USD/bushel"
        assert "USD/bushel" in FC.UNITS
        assert check_futures_eod() == []

    def test_volume_and_open_interest_are_null_by_source(self):
        """This file carries neither; they live in a separate PDF that is not part of this leg.
        CZCE and JSE both publish both, so this is the one free leg where the delivery-cycle roll
        rule IS the rule rather than a degraded fallback."""
        from leviathan.silver import futures_roll as FR

        df = self._silver()
        assert df["volume"].isna().all() and df["open_interest"].isna().all()
        assert FR.roll_method_for("hard_red_spring_wheat_mgex") == FR.METHOD_DELIVERY_CYCLE

    def test_close_is_null_and_settle_is_not_laundered_into_it(self):
        df = self._silver()
        assert df["close"].isna().all()
        assert df["open"].notna().all() and df["high"].notna().all()

    def test_the_labels_come_from_the_map_not_from_here(self):
        assert FC.lint_frame(self._silver()) == []

    def test_an_alien_slug_is_refused(self):
        bronze, _ = T.build_miax_bronze(settlement_csv(), trade_date="2026-07-28")
        bronze.loc[0, "leviathan_slug"] = "corn_cbot"
        with pytest.raises(ValueError, match="not MIAX contracts"):
            S.build_miax_eod_silver(bronze)

    def test_the_publish_route_passes_the_row_validator(self):
        from leviathan.silver.flat_producer import authorize_for_contract
        from leviathan.silver.partitioned_producer import build_partitioned_publish

        df = self._silver()
        contract = load_registry().table("silver_futures_eod")
        plan = build_partitioned_publish(
            df=df, contract=contract,
            auth=authorize_for_contract(contract, publish_mode="dry-run", env={}),
            job="futures_eod_miax", partition_cols=TASK._PARTITION_COLS,
            s3_client=None, row_validator=FC.lint_frame)
        assert plan.row_count == 7 and plan.partition_count == 1


# ---------------------------------------------------------------------------
class TestRowFloorAndDispatch:
    def test_the_floor_counts_outrights_not_file_rows(self):
        """The file is 75 rows and yields 7. A floor read against file rows would pass a leg that
        wrote nothing."""
        spec = TASK._SOURCE_SPECS["miax"]
        df = TestSilverProjection._silver()
        assert len(df) == 7 and spec.rows_per_day == 6
        assert TASK.assert_row_floor(df, spec) == []
        bad = TASK.assert_row_floor(df.iloc[:5], spec)
        assert len(bad) == 1 and ">= 6" in bad[0]

    def test_the_leg_is_wired_into_the_host(self):
        assert TASK._SOURCE_SPECS["miax"].implemented is True
        assert TASK._silver_builder("miax") is S.build_miax_eod_silver
        assert TASK._SOURCE_SPECS["miax"].job == "futures_eod_miax"
        assert TASK._SOURCE_SPECS["miax"].preflight_imports == ()


# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, status: int, content: bytes = b""):
        self.status_code = status
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


class TestProducer:
    def test_the_url_mirrors_the_raw_key(self):
        import datetime as dt

        day = dt.date(2026, 7, 28)
        assert FETCH.miax_url(day) == (
            "https://www.miaxglobal.com/sites/default/files/mgex/daily-settlement/"
            "Public_Daily_Settlement_File_2026-07-28.csv")
        key = raw_miax_key(day.isoformat())
        assert key.endswith("trade_date=20260728/Public_Daily_Settlement_File_2026-07-28.csv")
        assert key.startswith(miax_year_prefix(2026))
        assert miax_daily_filename("20260728") == "Public_Daily_Settlement_File_2026-07-28.csv"

    def test_the_csv_horizon_is_a_wall_this_job_refuses_to_walk_past(self):
        """Four pre-boundary dates were probed and all return a 63,668-byte Drupal 404 page. The
        PDF tier below it is a table extraction and is OUT OF SCOPE for this wave."""
        assert T.MIAX_CSV_FIRST_TRADE_DATE == "2025-09-09"
        assert T.MIAX_PDF_FIRST_TRADE_DATE == "2023-06-01"
        ns = FETCH.argparse.Namespace(mode="backfill", start="2025-09-08", end=None,
                                      lookback_days=5)
        with pytest.raises(SystemExit, match="PDF ONLY|horizon"):
            FETCH.resolve_window(ns)

    def test_the_backfill_window_defaults_to_the_csv_horizon(self):
        ns = FETCH.argparse.Namespace(mode="backfill", start=None, end="2025-09-11",
                                      lookback_days=5)
        start, end = FETCH.resolve_window(ns)
        assert start.isoformat() == T.MIAX_CSV_FIRST_TRADE_DATE
        assert len(list(FETCH.daterange(start, end))) == 3

    def test_a_404_day_is_an_absence_not_an_error(self, monkeypatch):
        import datetime as dt

        monkeypatch.setattr(FETCH.requests, "get", lambda url, timeout=None: _Resp(404))
        assert FETCH.fetch_day(dt.date(2026, 7, 26)) is None

    def test_a_200_settlement_file_is_landed_verbatim(self, monkeypatch):
        import datetime as dt

        payload = settlement_csv()
        monkeypatch.setattr(FETCH.requests, "get", lambda url, timeout=None: _Resp(200, payload))
        assert FETCH.fetch_day(dt.date(2026, 7, 28)) is payload
        assert FETCH.looks_like_a_settlement_file(payload, dt.date(2026, 7, 28)) is None

    def test_a_drupal_error_page_is_not_a_settlement_file(self):
        import datetime as dt

        why = FETCH.looks_like_a_settlement_file(b"<html>404</html>" * 500, dt.date(2026, 7, 28))
        assert why and "not a settlement CSV" in why

    def test_the_venue_serving_another_session_is_caught(self):
        import datetime as dt

        why = FETCH.looks_like_a_settlement_file(settlement_csv("7/27/26"),
                                                 dt.date(2026, 7, 28))
        assert why and "another session" in why

    def test_no_custom_headers_are_sent(self, monkeypatch):
        """Probe P1a passed CLEAN on the default python-requests UA. Adding one would turn a
        working request into an untested one."""
        seen = {}

        def _get(url, timeout=None, **kw):
            seen.update(kw)
            return _Resp(200, settlement_csv())

        import datetime as dt

        monkeypatch.setattr(FETCH.requests, "get", _get)
        FETCH.fetch_day(dt.date(2026, 7, 28))
        assert "headers" not in seen

    def test_the_size_floor_is_wired(self):
        from leviathan.common.constants import MIN_RAW_FILE_SIZES

        assert MIN_RAW_FILE_SIZES["miax"] == 1_000
