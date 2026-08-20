"""The EEX dry-bulk freight leg. Hermetic: no network, no AWS, no browser.

Every fixture under ``tests/fixtures/eex_freight/`` was captured LIVE on 2026-08-20 through the
producer's own code path (see that directory's ``capture_notes.md``). The endpoint serves a rolling
~5-trading-day settlement window and no history, so those bytes are UNREPRODUCIBLE -- a test that
needs a different date needs a new live capture on a new day, never a re-fetch.

The facts these tests exist to pin are the ones that would otherwise produce a WRONG NUMBER rather
than an error:

  * **the venue publishes TWO price units.** ``uOM=DAYS`` is USD per day of hire; ``uOM=TN`` is USD
    per tonne of cargo. C3EM settles at 35.71 and P5TC at 19,671 on the same day. A schema that
    assumed "USD/day for time-charter averages" -- which is where this lane started -- files a
    voyage rate as a daily hire rate and nothing downstream can tell;
  * **the two volume series are also two units, and on twelve of sixteen symbols they are
    numerically identical.** ``volume`` is in uOM, ``lotSize`` is in lots; they diverge only on the
    TN routes, by the 1,000-tonne lot;
  * **the settlement date lives INSIDE the payload**, so the raw key is cross-checkable -- unlike
    the Euronext leg, whose page carries no date at all. A mis-keyed object on a forward-only source
    can never be repaired from upstream, which is why the cross-check is fatal;
  * **first capture wins**, and the byte comparison that enforces it needs the landed document to
    render deterministically.

The producer is exercised only through its pure helpers; ``requests`` is never called.
"""
from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest
from leviathan.storage.paths import (
    eex_freight_symbol_prefix,
    raw_eex_freight_divergence_key,
    raw_eex_freight_key,
    silver_eex_freight_key,
)
from leviathan.transforms.bronze_to_silver import eex_freight as S
from leviathan.transforms.raw_to_bronze import eex_freight as T

_REPO = Path(__file__).resolve().parents[2]
_FIX = _REPO / "tests" / "fixtures" / "eex_freight"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FETCH = _load("jobs/ingest/fetch_eex_freight.py", "fetch_eex_freight")

# The five settlement dates the 2026-08-20 capture actually held, and the one it did NOT.
WINDOW_DATES = ["2026-08-13", "2026-08-14", "2026-08-17", "2026-08-18", "2026-08-19"]
LAST = "2026-08-19"


def observation(symbol: str, trade_date: str = LAST) -> bytes:
    return (_FIX / f"settlements_{symbol}_{trade_date}.json").read_bytes()


def wire(symbol: str, maturity: str = "202608") -> dict:
    return json.loads((_FIX / f"chart_eod_{symbol}_{maturity}.json").read_text(encoding="utf-8"))


def scope() -> dict:
    return json.loads((_FIX / "scope_freight_20260820.json").read_text(encoding="utf-8"))


def bronze(symbol: str, trade_date: str = LAST):
    return T.build_bronze(observation(symbol, trade_date), symbol=symbol, trade_date=trade_date)


def silver(symbol: str, trade_date: str = LAST) -> pd.DataFrame:
    return S.transform_eex_freight_bronze_to_silver(bronze(symbol, trade_date)[0])


# ===========================================================================
# The fixture itself -- the census claims every other test leans on
# ===========================================================================
class TestTheCapturedWindow:

    def test_the_window_is_five_trading_days_on_every_symbol(self):
        """The whole design follows from this number. If the venue ever widens the window the
        producer is unchanged, but the resilience budget in the docs is wrong."""
        for symbol in ("P5TC", "C3EM", "LNG1"):
            payload = wire(symbol)
            assert T.settlement_dates(payload) == WINDOW_DATES, symbol

    def test_the_capture_day_itself_is_not_in_the_window(self):
        """Captured ~17:20 UTC on 2026-08-20; EEX settles ~18:30 CET. The envelope's lastUpdate
        already read 2026-08-20 while the newest SETTLEMENT was 2026-08-19 -- which is exactly why
        the producer lands the dates the payload names and never asserts 'today'."""
        payload = wire("P5TC")
        assert payload["lastUpdate"] == "2026-08-20"
        assert "2026-08-20" not in T.settlement_dates(payload)

    def test_the_volume_series_reaches_further_back_than_the_settlement_series(self):
        """The 5-day ceiling is on settlPx specifically, not on the response. Recorded because it is
        the evidence that the ceiling is a deliberate venue policy and not an artefact of the
        request window we happened to send."""
        payload = wire("P5TC")
        volume_dates = sorted(T._series_points(payload, "volume"))
        assert min(volume_dates) < min(T.settlement_dates(payload))

    def test_every_listed_maturity_settles_on_every_window_day(self):
        """84 of 84 on P5TC, all five days -- including 203307, seven years out. This is what
        licenses build_bronze's 'not one row carries a settlement' hard error: on this venue an
        unpriced curve is a shape failure, never an illiquid session."""
        for trade_date in WINDOW_DATES:
            df, stats = bronze("P5TC", trade_date)
            assert len(df) == 84, trade_date
            assert stats["rows_priced"] == 84, trade_date
        assert bronze("P5TC")[0]["contract_month"].max() == "2033-07"


# ===========================================================================
# THE UNIT TRAP -- the two facts that would otherwise be wrong numbers
# ===========================================================================
class TestUnitHonesty:

    def test_the_venue_publishes_two_price_units_not_one(self):
        assert wire("P5TC")["uOM"] == "DAYS"
        assert wire("C3EM")["uOM"] == "TN"

    def test_a_voyage_route_and_a_charter_average_settle_three_orders_apart(self):
        """35.71 USD/tonne beside 19,671 USD/day, same day, same venue, same currency. Filing the
        first as a daily hire rate is the failure this leg is built to prevent."""
        cape = silver("C3EM")
        pana = silver("P5TC")
        front_cape = cape.loc[cape["contract_month"] == "2026-08"].iloc[0]
        front_pana = pana.loc[pana["contract_month"] == "2026-08"].iloc[0]
        assert front_cape["settle_px"] == pytest.approx(35.71)
        assert front_cape["unit"] == "USD/tonne"
        assert front_pana["settle_px"] == pytest.approx(19671.0)
        assert front_pana["unit"] == "USD/day"

    def test_every_dry_bulk_symbol_measured_as_TN_is_a_capesize_voyage_route(self):
        """The three TN symbols are C3/C5/C7 -- named voyage routes, not charter averages. Pinned so
        a future editor cannot 'tidy' them into the DAYS bucket."""
        tn = {s for s, (_, _, uom) in T.MEASURED_FUTURES_SYMBOLS.items() if uom == "TN"}
        assert tn == {"C3EM", "C5EM", "C7EM"}
        for symbol in tn:
            product, route, _ = T.MEASURED_FUTURES_SYMBOLS[symbol]
            assert product == "Capesize"
            assert route in {"C3", "C5", "C7"}

    def test_unit_label_is_built_from_the_pair_not_assumed(self):
        assert S.unit_label("USD", "DAYS") == "USD/day"
        assert S.unit_label("USD", "TN") == "USD/tonne"
        assert S.unit_label("EUR", "DAYS") == "EUR/day"     # currency is read, never assumed

    def test_an_unknown_uom_is_fatal_and_never_passed_through(self):
        with pytest.raises(ValueError, match="unrecognised uOM"):
            S.unit_label("USD", "MT")
        with pytest.raises(ValueError, match="no currency"):
            S.unit_label("", "DAYS")

    def test_an_unknown_uom_kills_the_silver_transform_rather_than_the_row(self):
        df, _ = bronze("P5TC")
        df.loc[0, "uom"] = "MT"
        with pytest.raises(ValueError, match="unrecognised uOM"):
            S.transform_eex_freight_bronze_to_silver(df)


class TestTheVolumeTrap:
    """``volume`` is in uOM and ``lotSize`` is in lots. On every DAYS contract they are numerically
    identical, so twelve of the sixteen symbols give a parser no reason to notice."""

    def test_the_two_series_diverge_by_the_lot_size_on_a_tonne_route(self):
        payload = wire("C3EM")
        vol = T._series_points(payload, "volume")
        lots = T._series_points(payload, "lotSize")
        assert vol == {"2026-08-06": 100000}
        assert lots == {"2026-08-06": 100}
        # 1,000 tonnes per C3 lot -- the whole reason the two columns exist.
        assert vol["2026-08-06"] / lots["2026-08-06"] == 1000

    def test_the_two_series_are_identical_on_a_days_contract(self):
        payload = wire("P5TC")
        assert T._series_points(payload, "volume") == T._series_points(payload, "lotSize")

    def test_bronze_maps_lotSize_to_volume_lots_and_volume_to_volume_uom(self):
        payload = wire("P5TC")
        doc = T.build_observation(symbol="P5TC", trade_date="2026-08-18",
                                  spec={"commodity": "FREIGHT", "pricing": "F", "area": "Freight",
                                        "product": "Panamax", "route": "5TC"},
                                  per_maturity={"202608": payload})
        entry = doc["settlements"][0]
        assert entry["volume_uom"] == T._series_points(payload, "volume")["2026-08-18"]
        assert entry["volume_lots"] == T._series_points(payload, "lotSize")["2026-08-18"]

    def test_silver_publishes_lots_and_not_the_uom_denominated_volume(self):
        """Lots mean the same thing on every contract, so the column is safe to sum across the
        table; the uOM-denominated figure would not be, and stays in bronze."""
        assert "volume_lots" in S.SILVER_COLUMNS
        assert "volume_uom" not in S.SILVER_COLUMNS
        assert "volume_uom" in T.BRONZE_COLUMNS

    def test_an_untraded_maturity_keeps_a_NULL_volume_never_a_zero(self):
        """16 of 84 P5TC maturities traded on 2026-08-19 and the front month was not one of them.
        A synthesised 0.0 would be indistinguishable from a real zero-volume print (INV-4)."""
        df, _ = bronze("P5TC")
        front = df.loc[df["contract_month"] == "2026-08"].iloc[0]
        assert pd.isna(front["volume_lots"])
        assert int(df["volume_lots"].notna().sum()) == 16
        assert int(df["settle_px"].notna().sum()) == 84     # priced but untraded is normal here


# ===========================================================================
# The landed object, and the byte comparison that enforces first-capture-wins
# ===========================================================================
class TestTheLandedObservation:

    def test_the_fixtures_are_byte_identical_to_what_the_producer_would_land(self):
        """The fixture was written by canonical_observation_bytes; re-rendering the parsed document
        must reproduce it exactly. If this fails, every landed object's byte comparison would report
        a false divergence on the next run."""
        for symbol in ("P5TC", "C3EM", "LNG1"):
            blob = observation(symbol)
            assert T.canonical_observation_bytes(json.loads(blob.decode("utf-8"))) == blob, symbol

    def test_the_rendering_is_stable_under_key_order(self):
        doc = json.loads(observation("P5TC").decode("utf-8"))
        shuffled = dict(reversed(list(doc.items())))
        assert T.canonical_observation_bytes(shuffled) == T.canonical_observation_bytes(doc)

    def test_the_document_carries_no_capture_timestamp(self):
        """Deliberate. A timestamp inside the observation would make every re-served window differ
        from its first capture and turn the divergence log into noise; capture provenance lives in
        the raw_meta companion, which is allowed to differ."""
        doc = json.loads(observation("P5TC").decode("utf-8"))
        assert not [k for k in doc if "time" in k.lower() or "captur" in k.lower()]

    def test_build_observation_picks_the_named_date_out_of_the_window(self):
        payload = wire("P5TC")
        spec = {"commodity": "FREIGHT", "pricing": "F", "area": "Freight",
                "product": "Panamax", "route": "5TC"}
        for trade_date in WINDOW_DATES:
            doc = T.build_observation(symbol="P5TC", trade_date=trade_date, spec=spec,
                                      per_maturity={"202608": payload})
            assert doc["trade_date"] == trade_date
            assert doc["settlements"][0]["settle_px"] == \
                T._series_points(payload, "settlPx")[trade_date]

    def test_a_date_with_no_settlement_is_refused_never_landed_empty(self):
        with pytest.raises(ValueError, match="not one live maturity carries a settlement"):
            T.build_observation(symbol="P5TC", trade_date="2026-08-20", spec={},
                                per_maturity={"202608": wire("P5TC")})

    def test_maturities_that_disagree_about_the_unit_are_refused(self):
        """A curve whose unit is ambiguous has no knowable unit, and the wrong pick is a plausible
        wrong number."""
        days, tonnes = wire("P5TC"), dict(wire("C3EM"))
        with pytest.raises(ValueError, match="disagree about the unit"):
            T.build_observation(symbol="P5TC", trade_date=LAST, spec={},
                                per_maturity={"202608": days, "202609": tonnes})


# ===========================================================================
# raw -> bronze
# ===========================================================================
class TestBuildBronze:

    def test_the_flagship_curve_parses_whole(self):
        df, stats = bronze("P5TC")
        assert list(df.columns) == T.BRONZE_COLUMNS
        assert len(df) == 84
        assert stats["currency"] == "USD" and stats["uom"] == "DAYS"
        assert stats["product"] == "Panamax" and stats["route"] == "5TC"
        assert stats["dry_bulk"] is True
        assert set(df["symbol"]) == {"P5TC"}
        assert set(df["trade_date"]) == {pd.Timestamp(LAST).date()}
        assert df["long_name"].iloc[0] == "EEX Baltic Panamax 5TC Freight Future"

    def test_the_tonne_route_parses_and_keeps_its_own_unit(self):
        df, stats = bronze("C3EM")
        assert len(df) == 36
        assert stats["uom"] == "TN"
        assert stats["route"] == "C3"
        assert df["settle_px"].max() < 100      # tonnes, not days -- the shape of the trap

    def test_the_key_and_the_payload_must_agree_about_the_symbol(self):
        with pytest.raises(ValueError, match="the raw key names"):
            T.build_bronze(observation("P5TC"), symbol="S11F", trade_date=LAST)

    def test_the_key_and_the_payload_must_agree_about_the_date(self):
        """The one corruption a forward-only accumulator can never repair from source."""
        with pytest.raises(ValueError, match="the raw key names"):
            T.build_bronze(observation("P5TC"), symbol="P5TC", trade_date="2026-08-18")

    def test_an_unknown_schema_tag_is_refused_rather_than_read_hopefully(self):
        doc = json.loads(observation("P5TC").decode("utf-8"))
        doc["schema"] = "eex_freight_settlements/v2"
        with pytest.raises(ValueError, match="this parser reads"):
            T.build_bronze(T.canonical_observation_bytes(doc), symbol="P5TC", trade_date=LAST)

    def test_a_zero_settlement_document_is_refused(self):
        doc = json.loads(observation("P5TC").decode("utf-8"))
        doc["settlements"] = []
        with pytest.raises(ValueError, match="ZERO settlements"):
            T.build_bronze(T.canonical_observation_bytes(doc), symbol="P5TC", trade_date=LAST)

    def test_a_document_where_nothing_is_priced_is_refused(self):
        doc = json.loads(observation("P5TC").decode("utf-8"))
        for entry in doc["settlements"]:
            entry["settle_px"] = None
        with pytest.raises(ValueError, match="not one of 84 listed maturity"):
            T.build_bronze(T.canonical_observation_bytes(doc), symbol="P5TC", trade_date=LAST)

    def test_a_non_json_object_is_refused_with_its_size(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            T.build_bronze(b"<html>403</html>", symbol="P5TC", trade_date=LAST)
        with pytest.raises(ValueError, match="expected the settlements document"):
            T.build_bronze(b"[]", symbol="P5TC", trade_date=LAST)

    def test_contract_month_decodes_and_fails_closed(self):
        assert T.contract_month("202609") == "2026-09"
        assert T.contract_month("203307") == "2033-07"
        for bad in ("2026-09", "20260901", "202613", "", None, "2026Q3"):
            with pytest.raises(ValueError):
                T.contract_month(bad)

    def test_a_quarter_maturity_is_refused_rather_than_read_as_a_month(self):
        doc = json.loads(observation("P5TC").decode("utf-8"))
        doc["settlements"][0]["maturity"] = "2026Q4"
        with pytest.raises(ValueError, match="not a compact YYYYMM"):
            T.build_bronze(T.canonical_observation_bytes(doc), symbol="P5TC", trade_date=LAST)


# ===========================================================================
# bronze -> silver
# ===========================================================================
class TestBuildSilver:

    def test_the_tidy_shape(self):
        df = silver("P5TC")
        assert list(df.columns) == S.SILVER_COLUMNS
        assert len(df) == 84
        assert set(df["unit"]) == {"USD/day"}
        assert set(df["currency"]) == {"USD"}
        assert set(df["source"]) == {"eex_freight"}
        # the natural key is unique
        assert not df.duplicated(subset=["symbol", "contract_month", "trade_date"]).any()
        # and sorted
        assert list(df["contract_month"]) == sorted(df["contract_month"])

    def test_the_written_non_dry_bulk_refusal_empties_the_frame_without_erroring(self):
        """A refused symbol contributes no partition and no error -- the ESR non-mass-code idiom.
        Raw and bronze keep accumulating it, which is the point: this source has no history
        endpoint, so a scope decision enforced upstream would be irreversible."""
        assert "LNG Route" in T.NON_DRY_BULK_PRODUCTS
        df = silver("LNG1")
        assert len(df) == 0
        assert list(df.columns) == S.SILVER_COLUMNS

    def test_lng_still_reaches_bronze_in_full(self):
        df, stats = bronze("LNG1")
        assert len(df) == 36
        assert stats["dry_bulk"] is False
        assert stats["rows_priced"] == 36

    def test_a_mixed_frame_drops_only_the_refused_rows(self):
        mixed = pd.concat([bronze("P5TC")[0], bronze("LNG1")[0]], ignore_index=True)
        out = S.transform_eex_freight_bronze_to_silver(mixed)
        assert set(out["symbol"]) == {"P5TC"}
        assert len(out) == 84

    def test_an_uncurated_product_is_KEPT_not_dropped(self):
        """A freight future the venue lists must not vanish from the only table anything reads --
        on a source that cannot be re-fetched, a silent silver drop is data loss. It reaches bronze
        with a loud UNIVERSE DRIFT warning and that is the signal to classify it."""
        df, _ = bronze("P5TC")
        df["product"] = "Kamsarmax"
        out = S.transform_eex_freight_bronze_to_silver(df)
        assert len(out) == 84

    def test_missing_required_columns_are_named(self):
        df, _ = bronze("P5TC")
        with pytest.raises(ValueError, match="missing required column"):
            S.transform_eex_freight_bronze_to_silver(df.drop(columns=["uom"]))

    def test_the_boundary_maps_cannot_contradict_each_other(self):
        assert not (set(T.DRY_BULK_PRODUCTS) & set(T.NON_DRY_BULK_PRODUCTS))

    def test_trade_date_survives_as_a_real_date(self):
        df = silver("P5TC")
        assert set(df["trade_date"]) == {pd.Timestamp(LAST).date()}


# ===========================================================================
# The producer: universe enumeration, keys, arguments
# ===========================================================================
class TestUniverseEnumeration:

    def test_the_scope_blob_is_the_widgets_own_selector(self):
        decoded = json.loads(base64.b64decode(FETCH.scope_blob()).decode("utf-8"))
        assert decoded == [{"commodity": "FREIGHT", "pricing": "All", "area": "All",
                            "product": "All", "productSpecific": "All", "maturityType": "All"}]

    def test_the_live_census(self):
        """1,123 freight instruments on 2026-08-20: 806 futures + 317 options, every one of them
        maturityType=Month and area=Freight."""
        records = FETCH.parse_scope(scope())
        assert len(records) == 1123
        assert {r["maturity_type"] for r in records} == {"Month"}
        assert {r["area"] for r in records} == {"Freight"}
        assert {r["commodity"] for r in records} == {"FREIGHT"}
        assert sum(1 for r in records if r["pricing"] == "F") == 806
        assert sum(1 for r in records if r["pricing"] == "O") == 317

    def test_the_header_is_read_by_name_never_by_position(self):
        payload = scope()
        payload["header"] = ["spacer"] + payload["header"]
        payload["data"] = [["x"] + row for row in payload["data"]]
        # inserting a column must NOT shift shortCode into maturity
        records = FETCH.parse_scope(payload)
        assert records[0]["symbol"] == FETCH.parse_scope(scope())[0]["symbol"]

    def test_a_missing_header_column_is_refused_rather_than_read_positionally(self):
        payload = scope()
        payload["header"] = [h for h in payload["header"] if h != "shortCode"]
        with pytest.raises(ValueError, match="missing"):
            FETCH.parse_scope(payload)

    def test_a_ragged_row_is_refused(self):
        payload = scope()
        payload["data"] = [payload["data"][0][:-1]]
        with pytest.raises(ValueError, match="expected"):
            FETCH.parse_scope(payload)

    def test_futures_selection_refuses_options_and_expired_maturities(self):
        records = FETCH.parse_scope(scope())
        grouped = FETCH.select_instruments(records, floor="202608")
        assert set(grouped) == set(T.MEASURED_FUTURES_SYMBOLS)
        assert len(grouped) == 16
        # no option short code survived
        assert not {"O5TM", "OP5M", "OS11"} & set(grouped)
        # the expired 202607 was filtered out of every symbol
        assert all(m >= "202608" for slot in grouped.values() for m in slot["maturities"])
        assert len(grouped["P5TC"]["maturities"]) == 84
        assert grouped["P5TC"]["spec"] == {"commodity": "FREIGHT", "pricing": "F",
                                           "area": "Freight", "product": "Panamax", "route": "5TC"}

    def test_thirteen_of_the_sixteen_futures_are_dry_bulk(self):
        grouped = FETCH.select_instruments(FETCH.parse_scope(scope()), floor="202608")
        dry = {s for s, slot in grouped.items() if T.is_dry_bulk(slot["spec"]["product"])}
        assert len(dry) == 13
        assert set(grouped) - dry == {"LNG1", "LNG2", "LNG3"}

    def test_the_symbol_filter_narrows_without_changing_anything_else(self):
        records = FETCH.parse_scope(scope())
        one = FETCH.select_instruments(records, floor="202608", symbols=["p5tc"])
        assert set(one) == {"P5TC"}
        assert one["P5TC"] == FETCH.select_instruments(records, floor="202608")["P5TC"]

    def test_the_measured_census_matches_the_pinned_drift_detector(self):
        """MEASURED_FUTURES_SYMBOLS is a drift detector, so it must actually describe the capture it
        claims to describe -- otherwise it would warn about reality instead of about drift."""
        grouped = FETCH.select_instruments(FETCH.parse_scope(scope()), floor="202608")
        for symbol, (product, route, _uom) in T.MEASURED_FUTURES_SYMBOLS.items():
            assert grouped[symbol]["spec"]["product"] == product, symbol
            assert grouped[symbol]["spec"]["route"] == route, symbol
        for symbol in ("P5TC", "C3EM", "LNG1"):
            assert wire(symbol)["uOM"] == T.MEASURED_FUTURES_SYMBOLS[symbol][2]

    def test_the_maturity_floor_arithmetic_wraps_the_year(self):
        import datetime as dt
        assert FETCH.min_maturity(dt.date(2026, 8, 20), 1) == "202607"
        assert FETCH.min_maturity(dt.date(2026, 1, 5), 1) == "202512"
        assert FETCH.min_maturity(dt.date(2026, 1, 5), 0) == "202601"
        assert FETCH.min_maturity(dt.date(2026, 3, 1), 14) == "202501"


class TestRequestRecipeAndKeys:

    def test_all_three_headers_are_sent(self):
        """Probed 2026-08-20: a call without Referer returns 403."""
        for header in ("User-Agent", "Origin", "Referer"):
            assert FETCH._HEADERS.get(header), header
        assert FETCH._HEADERS["Origin"] == "https://www.eex.com"
        assert "Mozilla" in FETCH._HEADERS["User-Agent"]

    def test_the_eod_query_is_built_from_the_enumeration_not_from_assumptions(self):
        spec = FETCH.select_instruments(FETCH.parse_scope(scope()),
                                        floor="202608")["P5TC"]["spec"]
        params = FETCH.eod_params(spec, "P5TC", "202609", "2026-07-30", "2026-08-20")
        assert params == {"commodity": "FREIGHT", "pricing": "F", "area": "Freight",
                          "product": "Panamax", "maturity": "202609",
                          "startDate": "2026-07-30", "endDate": "2026-08-20",
                          "shortCode": "P5TC"}
        url = FETCH.eod_url(spec, "P5TC", "202609", "2026-07-30", "2026-08-20")
        assert url.startswith("https://api.eex-group.com/pub/market-data/chart/eod?")
        assert "shortCode=P5TC" in url

    def test_the_raw_key_is_keyed_by_settlement_date_not_capture_date(self):
        assert raw_eex_freight_key("P5TC", "2026-08-19") == (
            "raw/production/source=eex_freight/symbol=P5TC/trade_date=2026-08-19/settlements.json")
        # both date spellings, one key
        assert raw_eex_freight_key("p5tc", "20260819") == raw_eex_freight_key("P5TC", "2026-08-19")

    def test_keys_refuse_a_symbol_or_date_that_could_inject_a_path_segment(self):
        for bad in ("../../etc", "P5TC/x", "", "p", "TOOLONGSYMBOL"):
            with pytest.raises(ValueError):
                raw_eex_freight_key(bad, "2026-08-19")
        for bad in ("2026-8-19", "19-08-2026", "", "today"):
            with pytest.raises(ValueError):
                raw_eex_freight_key("P5TC", bad)

    def test_the_divergence_key_is_a_sibling_of_the_data_plane_not_inside_it(self):
        key = raw_eex_freight_divergence_key("P5TC", "2026-08-19", "20260820T172000Z")
        assert key == ("raw/production/source=eex_freight/_divergence/symbol=P5TC/"
                       "trade_date=2026-08-19/observed_20260820T172000Z.json")
        assert not key.startswith(eex_freight_symbol_prefix("P5TC"))
        # a second disagreement never clobbers the first
        assert key != raw_eex_freight_divergence_key("P5TC", "2026-08-19", "20260821T172000Z")

    def test_the_symbol_prefix_covers_every_landed_date_of_one_symbol(self):
        prefix = eex_freight_symbol_prefix("P5TC")
        for trade_date in WINDOW_DATES:
            assert raw_eex_freight_key("P5TC", trade_date).startswith(prefix)
        assert not raw_eex_freight_key("S11F", LAST).startswith(prefix)

    def test_the_silver_root_is_its_own_and_not_under_silver_production(self):
        """silver/production/ is projected by the long FAOSTAT-shaped silver_production table."""
        assert silver_eex_freight_key() == "silver/eex_freight/part-000.parquet"


class TestProducerArguments:

    def test_the_sleep_floor_cannot_be_argued_below_one_second(self):
        with pytest.raises(ValueError, match="floor"):
            FETCH._Client(sleep_s=0.2)
        assert FETCH._Client(sleep_s=1.0).sleep_s == 1.0

    def test_there_is_no_force_flag(self):
        """An overwrite flag on this leg is a PIT violation with no undo: the bytes it destroys
        cannot be re-fetched from anywhere."""
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), pytest.raises(SystemExit):
            FETCH.main(["--help"])
        helptext = buf.getvalue()
        assert "--force" not in helptext
        assert "--dry-run" in helptext and "--skip-existing" in helptext
        assert "--symbol" in helptext and "--sleep" in helptext

    def test_a_malformed_end_date_is_refused_before_any_request(self):
        with pytest.raises(SystemExit, match="not YYYY-MM-DD"):
            FETCH.main(["--end-date", "20/08/2026", "--dry-run"])

    def test_the_divergence_record_keeps_both_readings_and_names_the_resolution(self):
        first = observation("P5TC")
        served = json.loads(first.decode("utf-8"))
        served["settlements"][0]["settle_px"] = 99999.0
        served_bytes = T.canonical_observation_bytes(served)
        record = json.loads(FETCH.divergence_record(
            "P5TC", LAST, first, served_bytes, "20260821T172000Z", "https://example.invalid"
        ).decode("utf-8"))
        assert record["resolution"] == "kept-as-first"
        assert len(record["changed_maturities"]) == 1
        change = record["changed_maturities"][0]
        assert change["maturity"] == "202608"
        assert change["first_capture"]["settle_px"] == 19671.0
        assert change["re_served"]["settle_px"] == 99999.0
        assert record["first_capture"] and record["re_served"]

    def test_an_unparseable_landed_object_is_itself_recorded_not_swallowed(self):
        record = json.loads(FETCH.divergence_record(
            "P5TC", LAST, b"<html>", observation("P5TC"), "20260821T172000Z", "u"
        ).decode("utf-8"))
        assert record["first_capture"] == {}
        assert len(record["changed_maturities"]) == 84


# ===========================================================================
# The existence probe FAILS CLOSED -- the one path that could destroy a first capture
# ===========================================================================
class TestRawExistsFailsClosed:
    """``raw_exists`` gates the only PUT on the data plane. The estate house idiom answers False on
    ANY head failure, which turns a throttle or an expired credential into "absent" and therefore
    into an overwrite. Everywhere else the overwritten bytes are re-fetchable; here they are not."""

    @staticmethod
    def _client(monkeypatch, exc):
        """Point ``raw_exists`` at a head_object that raises ``exc`` (or returns, if None)."""
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
        self._client(monkeypatch, None)
        assert FETCH.raw_exists("b", "k", "us-east-1") is True

    @pytest.mark.parametrize("code,status", [("404", 404), ("NotFound", 404), ("NoSuchKey", 404)])
    def test_only_a_genuine_404_means_absent(self, monkeypatch, code, status):
        """HeadObject has no body, so botocore spells the missing-key case '404'/'NotFound' rather
        than the 'NoSuchKey' a GetObject would raise. All three are the same fact."""
        self._client(monkeypatch, self._client_error(code, status))
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
        """Fail closed. Aborting the run costs one day out of a five-day recovery budget; treating
        a throttled head as 'absent' costs a settlement that cannot be re-fetched at any price."""
        from botocore.exceptions import ClientError
        self._client(monkeypatch, self._client_error(code, status))
        with pytest.raises(ClientError):
            FETCH.raw_exists("b", "k", "us-east-1")

    def test_a_transient_head_failure_never_reaches_the_PUT(self, monkeypatch):
        """End to end through main(): the head fails transiently on the data key, and the producer
        must land NOTHING on that key and report the run as failed."""
        written = {}
        monkeypatch.setattr(FETCH._Client, "_pace", lambda self: None)
        monkeypatch.setattr(FETCH._Client, "post_scope", lambda self, enc: scope())
        monkeypatch.setattr(FETCH._Client, "get_json",
                            lambda self, path, params: wire(params["shortCode"]))
        monkeypatch.setattr(FETCH, "raw_read", lambda bucket, key, region: b"")

        def _boom(bucket, key, region):
            raise self._client_error("SlowDown", 503)

        monkeypatch.setattr(FETCH, "raw_exists", _boom)
        monkeypatch.setattr(FETCH, "land_bytes",
                            lambda bucket, key, data, **kw: written.__setitem__(key, data))

        assert FETCH.main(TestFirstCaptureWins.ARGV) == FETCH.EXIT_FAILURES
        assert written == {}, "a throttled head must never be read as 'absent' and PUT over"

    def test_an_unanswerable_probe_does_not_let_skip_existing_skip(self, monkeypatch):
        """The --skip-existing probe calls raw_exists outside the per-date guard. A head that
        cannot answer must not be read as 'already landed' either -- it falls through to the full
        fetch, where the per-date guard fails closed and records it."""
        written = {}
        monkeypatch.setattr(FETCH._Client, "_pace", lambda self: None)
        monkeypatch.setattr(FETCH._Client, "post_scope", lambda self, enc: scope())
        monkeypatch.setattr(FETCH._Client, "get_json",
                            lambda self, path, params: wire(params["shortCode"]))
        monkeypatch.setattr(FETCH, "raw_read", lambda bucket, key, region: b"")

        def _boom(bucket, key, region):
            raise self._client_error("SlowDown", 503)

        monkeypatch.setattr(FETCH, "raw_exists", _boom)
        monkeypatch.setattr(FETCH, "land_bytes",
                            lambda bucket, key, data, **kw: written.__setitem__(key, data))

        argv = TestFirstCaptureWins.ARGV + ["--skip-existing"]
        assert FETCH.main(argv) == FETCH.EXIT_FAILURES
        assert written == {}


# ===========================================================================
# --skip-existing under the producer's OWN defaults
# ===========================================================================
class TestSkipExistingUnderDefaults:
    """The reviewer's measured scenario. With ``--lookback-months`` at its DEFAULT of 1 the maturity
    floor is one month below the run, so ``maturities[0]`` is an EXPIRED contract that ``/chart/eod``
    answers with an all-null envelope and an empty series. Probing it yields no dates, the
    "everything already landed" test is vacuously false, and the flag falls through to the full
    806-call fetch -- plus one wasted call per symbol."""

    # An expired maturity as the live endpoint actually answers it (verified 2026-08-20 on
    # P5TC maturity=202607): 200, all-null envelope, empty series.
    EXPIRED = {"lastUpdate": None, "currency": None, "uOM": None, "longName": "", "series": []}

    def test_the_default_floor_really_does_put_an_expired_maturity_first(self):
        """The precondition of the whole finding, measured off the checked-in scope capture."""
        import datetime as dt
        default_floor = FETCH.min_maturity(dt.date(2026, 8, 20), 1)
        assert default_floor == "202607"
        grouped = FETCH.select_instruments(FETCH.parse_scope(scope()), floor=default_floor)
        assert len(grouped) == 16
        expired_first = [s for s, slot in grouped.items() if slot["maturities"][0] == "202607"]
        assert len(expired_first) == 16, "16 of 16 symbols lead with the expired month"

    def test_the_probe_skips_the_expired_month_and_asks_the_front_live_one(self):
        grouped = FETCH.select_instruments(FETCH.parse_scope(scope()), floor="202607")
        for symbol, slot in grouped.items():
            assert FETCH.probe_maturity(slot["maturities"],
                                        current_month="202608") == "202608", symbol

    def test_the_probe_never_invents_a_maturity_and_degrades_to_the_newest_listed(self):
        mats = ["202605", "202606", "202607"]
        # every listed maturity has rolled off -- probe the newest rather than a guaranteed-empty
        # one, and never a month the venue does not list
        assert FETCH.probe_maturity(mats, current_month="202608") == "202607"
        assert FETCH.probe_maturity(mats, current_month="202606") == "202606"

    @staticmethod
    def _harness(monkeypatch, landed):
        """Like TestFirstCaptureWins._harness, but the stub MODELS the expired maturity: anything
        below 202608 answers the all-null envelope the venue really serves."""
        written = {}
        calls = {"get_json": 0, "maturities": []}

        monkeypatch.setattr(FETCH._Client, "_pace", lambda self: None)
        monkeypatch.setattr(FETCH._Client, "post_scope", lambda self, enc: scope())

        def _get_json(self, path, params):
            calls["get_json"] += 1
            calls["maturities"].append(params["maturity"])
            if params["maturity"] < "202608":
                return dict(TestSkipExistingUnderDefaults.EXPIRED)
            return wire(params["shortCode"])

        monkeypatch.setattr(FETCH._Client, "get_json", _get_json)
        monkeypatch.setattr(FETCH, "raw_exists", lambda bucket, key, region: key in landed)
        monkeypatch.setattr(FETCH, "raw_read", lambda bucket, key, region: landed[key])
        monkeypatch.setattr(FETCH, "land_bytes",
                            lambda bucket, key, data, **kw: written.__setitem__(key, data))
        return written, calls

    # NOTE: no --lookback-months. That is the whole point -- these run on the DEFAULTS.
    ARGV = ["--symbol", "P5TC", "--end-date", "2026-08-20",
            "--bucket", "test-bucket", "--aws-region", "us-east-1"]

    def test_skip_existing_actually_skips_under_default_arguments(self, monkeypatch):
        first, seed_calls = self._harness(monkeypatch, {})
        assert FETCH.main(self.ARGV) == FETCH.EXIT_OK
        assert sorted(first) == [raw_eex_freight_key("P5TC", d) for d in WINDOW_DATES]
        # the expired month was requested and served nothing -- it costs a call, it never lands
        assert "202607" in seed_calls["maturities"]

        second, calls = self._harness(monkeypatch, dict(first))
        assert FETCH.main(self.ARGV + ["--skip-existing"]) == FETCH.EXIT_OK
        assert second == {}, "the symbol is fully landed; --skip-existing must skip it"
        assert calls["get_json"] == 1, "ONE probe, not the 85-month curve"
        assert calls["maturities"] == ["202608"], "and the probe must not be the expired month"

    def test_skip_existing_still_falls_through_when_a_date_is_missing(self, monkeypatch):
        first, _ = self._harness(monkeypatch, {})
        FETCH.main(self.ARGV)
        partial = {k: v for k, v in first.items()
                   if not k.endswith(f"trade_date={LAST}/settlements.json")}
        second, calls = self._harness(monkeypatch, partial)
        assert FETCH.main(self.ARGV + ["--skip-existing"]) == FETCH.EXIT_OK
        assert sorted(second) == [raw_eex_freight_key("P5TC", LAST)]
        assert calls["get_json"] > 1


class TestFirstCaptureWins:
    """The law this whole leg exists to enforce, driven through ``main()`` with the network and S3
    stubbed out. A settlement is published once; a re-served window may be compared against what is
    landed and may be logged, but it may NEVER overwrite it, because the bytes it would destroy
    cannot be re-fetched from anywhere."""

    @staticmethod
    def _harness(monkeypatch, landed: dict[str, bytes]):
        """Stub the network and S3. ``landed`` is the pretend bucket, mutated in place so the test
        can assert on exactly which keys were written."""
        written: dict[str, bytes] = {}
        calls = {"get_json": 0}

        monkeypatch.setattr(FETCH._Client, "_pace", lambda self: None)
        monkeypatch.setattr(FETCH._Client, "post_scope", lambda self, enc: scope())

        def _get_json(self, path, params):
            calls["get_json"] += 1
            return wire(params["shortCode"])

        monkeypatch.setattr(FETCH._Client, "get_json", _get_json)
        monkeypatch.setattr(FETCH, "raw_exists",
                            lambda bucket, key, region: key in landed)
        monkeypatch.setattr(FETCH, "raw_read",
                            lambda bucket, key, region: landed[key])

        def _land(bucket, key, data, *, source_url, region, extra=None):
            written[key] = data

        monkeypatch.setattr(FETCH, "land_bytes", _land)
        return written, calls

    # --lookback-months 0 pins the floor at 202608, which is the maturity set the fixture was
    # captured over. The default (1) also requests the EXPIRED 202607, which the live endpoint
    # answers with an empty envelope and the producer skips -- but the stub below cannot model
    # "empty", so leaving it in would add a phantom 85th maturity that exists nowhere.
    ARGV = ["--symbol", "P5TC", "--end-date", "2026-08-20", "--lookback-months", "0",
            "--bucket", "test-bucket", "--aws-region", "us-east-1"]

    def test_an_empty_bucket_lands_one_object_per_settlement_date(self, monkeypatch):
        written, _ = self._harness(monkeypatch, {})
        assert FETCH.main(self.ARGV) == 0
        assert sorted(written) == [raw_eex_freight_key("P5TC", d) for d in WINDOW_DATES]
        # and each landed object is the canonical rendering for THAT date
        for trade_date in WINDOW_DATES:
            df, _ = T.build_bronze(written[raw_eex_freight_key("P5TC", trade_date)],
                                   symbol="P5TC", trade_date=trade_date)
            assert set(df["trade_date"]) == {pd.Timestamp(trade_date).date()}

    def test_the_capture_day_is_never_landed(self, monkeypatch):
        """The producer lands the dates the payload names, never 'today'."""
        written, _ = self._harness(monkeypatch, {})
        FETCH.main(self.ARGV)
        assert raw_eex_freight_key("P5TC", "2026-08-20") not in written

    def test_a_byte_identical_re_serve_writes_nothing_at_all(self, monkeypatch):
        first, _ = self._harness(monkeypatch, {})
        FETCH.main(self.ARGV)
        second, _ = self._harness(monkeypatch, dict(first))
        assert FETCH.main(self.ARGV) == 0
        assert second == {}, "an unchanged window must be a no-op, not a rewrite"

    def test_a_changed_re_serve_is_logged_beside_the_first_capture_never_over_it(self, monkeypatch):
        first, _ = self._harness(monkeypatch, {})
        FETCH.main(self.ARGV)

        # tamper with ONE landed date so the re-served window disagrees with it
        target = raw_eex_freight_key("P5TC", LAST)
        doc = json.loads(first[target].decode("utf-8"))
        doc["settlements"][0]["settle_px"] = 11111.0
        bucket = dict(first)
        bucket[target] = T.canonical_observation_bytes(doc)

        second, _ = self._harness(monkeypatch, bucket)
        # A RESTATEMENT IS NOT A CLEAN RUN. The record is written and the first capture is kept,
        # but the run itself carries the news -- a WARNING in a Batch log is not a control.
        assert FETCH.main(self.ARGV) == FETCH.EXIT_DIVERGENCE

        # the first capture was NOT rewritten ...
        assert target not in second
        assert bucket[target] == T.canonical_observation_bytes(doc)
        # ... and exactly one divergence record landed, under the sibling prefix
        assert len(second) == 1
        dkey = next(iter(second))
        assert dkey.startswith("raw/production/source=eex_freight/_divergence/symbol=P5TC/"
                               f"trade_date={LAST}/observed_")
        record = json.loads(second[dkey].decode("utf-8"))
        assert record["resolution"] == "kept-as-first"
        assert record["changed_maturities"][0]["first_capture"]["settle_px"] == 11111.0
        assert record["changed_maturities"][0]["re_served"]["settle_px"] == 19671.0

    def test_skip_existing_costs_one_probe_and_skips_the_comparison_it_says_it_skips(
            self, monkeypatch):
        first, _ = self._harness(monkeypatch, {})
        FETCH.main(self.ARGV)
        second, calls = self._harness(monkeypatch, dict(first))
        assert FETCH.main(self.ARGV + ["--skip-existing"]) == 0
        assert second == {}
        assert calls["get_json"] == 1, "one front-maturity probe, not the whole 84-month curve"

    def test_skip_existing_still_fetches_when_a_date_is_missing(self, monkeypatch):
        first, _ = self._harness(monkeypatch, {})
        FETCH.main(self.ARGV)
        partial = {k: v for k, v in first.items() if not k.endswith(f"trade_date={LAST}/"
                                                                   "settlements.json")}
        second, calls = self._harness(monkeypatch, partial)
        assert FETCH.main(self.ARGV + ["--skip-existing"]) == 0
        assert sorted(second) == [raw_eex_freight_key("P5TC", LAST)]
        assert calls["get_json"] > 1

    def test_the_exit_codes_are_distinct_and_a_clean_run_is_the_only_zero(self, monkeypatch):
        """Three outcomes, three codes. 2 is reserved for "clean apart from a restatement" so a
        schedule can tell it apart from a fetch failure; both are terminal under the estate's
        producer retry matrix (exit 2 + absent reason -> the mandatory terminal on_reason "*" EXIT
        rule, live-probed on job cb151695), so neither re-runs and re-lands a second record."""
        assert (FETCH.EXIT_OK, FETCH.EXIT_FAILURES, FETCH.EXIT_DIVERGENCE) == (0, 1, 2)

        # clean
        _, _ = self._harness(monkeypatch, {})
        assert FETCH.main(self.ARGV) == FETCH.EXIT_OK

        # a failure still wins over a divergence -- the run genuinely did not complete
        first, _ = self._harness(monkeypatch, {})
        FETCH.main(self.ARGV)
        target = raw_eex_freight_key("P5TC", LAST)
        doc = json.loads(first[target].decode("utf-8"))
        doc["settlements"][0]["settle_px"] = 11111.0
        bucket = dict(first)
        bucket[target] = T.canonical_observation_bytes(doc)
        _, _ = self._harness(monkeypatch, bucket)

        boom = {"n": 0}
        real_land = FETCH.land_bytes

        def _land(bucket_, key, data, **kw):
            boom["n"] += 1
            if boom["n"] == 1:
                raise RuntimeError("simulated upload failure")
            return real_land(bucket_, key, data, **kw)

        monkeypatch.setattr(FETCH, "land_bytes", _land)
        assert FETCH.main(self.ARGV) == FETCH.EXIT_FAILURES

    def test_the_landed_bytes_round_trip_through_bronze_and_silver(self, monkeypatch):
        written, _ = self._harness(monkeypatch, {})
        FETCH.main(self.ARGV)
        blob = written[raw_eex_freight_key("P5TC", LAST)]
        out = S.transform_eex_freight_bronze_to_silver(
            T.build_bronze(blob, symbol="P5TC", trade_date=LAST)[0])
        assert len(out) == 84
        assert set(out["unit"]) == {"USD/day"}


# ===========================================================================
# Registry / DDL coherence -- the writer and the contract must not drift
# ===========================================================================
class TestRegistryContract:

    @staticmethod
    def _contract():
        from leviathan.silver.registry import load_registry
        return load_registry().table("silver_eex_freight")

    def test_the_registry_declares_exactly_what_the_transform_writes_in_order(self):
        contract = self._contract()
        assert [c["name"] for c in contract["physical_columns"]] == S.SILVER_COLUMNS

    def test_the_natural_key_and_value_columns_are_real_columns(self):
        contract = self._contract()
        names = {c["name"] for c in contract["physical_columns"]}
        assert set(contract["natural_key"]) <= names
        assert set(contract["required_nonnull"]) <= names
        assert set(contract["value_columns"]) <= names
        assert contract["natural_key"] == ["symbol", "contract_month", "trade_date"]

    def test_the_freshness_sla_is_the_sources_own_five_day_ceiling(self):
        """Not a preference. Four consecutive missed runs are recoverable, the fifth is not, so an
        alarm at 30 days would fire five weeks after the data was already gone."""
        contract = self._contract()
        assert contract["freshness_sla"] == {"cadence": "daily", "max_lag_days": 5}
        assert contract["freshness_sla"]["max_lag_days"] == T.SETTLEMENT_WINDOW_TRADING_DAYS

    def test_pit_is_the_sources_own_date_with_no_lag(self):
        contract = self._contract()
        assert contract["knowledge_date_col"] == "trade_date"
        assert contract["knowledge_semantics"] == "data_date"
        assert contract["publication_lag_days"] == 0

    def test_the_accumulator_never_declares_an_overwrite_publisher(self):
        assert self._contract()["write_mode"] == "append"

    def test_no_numbers_card_is_claimed_before_proof_of_rows(self):
        """The four-checkmark law: the card flips with the projection wave, not here."""
        contract = self._contract()
        assert contract["consumers"] == "none"
        assert contract["numbers_ref"] is None
        assert contract["cascade_ref"] is None

    def test_the_checked_in_ddl_is_semantically_identical_to_the_registry(self):
        from leviathan.silver import ddl as D
        contract = self._contract()
        hand = (_REPO / "sql" / "athena" / "ddl" / "silver_eex_freight.sql").read_text(
            encoding="utf-8")
        assert D.diff_structured(D.structured_from_contract(contract), D.parse_ddl(hand)) == []

    def test_the_silver_root_matches_the_path_helper(self):
        contract = self._contract()
        assert contract["s3_prefix"] + "/" == silver_eex_freight_key().rsplit("/", 1)[0] + "/"
