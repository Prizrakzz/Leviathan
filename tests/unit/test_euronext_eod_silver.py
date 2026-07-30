"""PRICE_AND_PLAYBOOKS W1c -- the Euronext/MATIF bronze -> ``silver_futures_eod`` projection.

The parse half lives in ``tests/unit/test_euronext_eod.py``; the fixture is the same one, the real
rendered EBM table outerHTML captured live on 2026-07-29 (12 expiries, 7 traded + 5 untraded).

Two claims carry this file:

  * SETTL. is the price of record and prints on EVERY row, so the five untraded back months publish
    a settlement and nothing else -- they are the reason the deep curve is kept at all. ``Last`` is
    a TRADE and lands in ``close``, never in ``settle``;
  * WHAT EXISTS ON A ROW IS DECIDED BY THE VENUE'S OWN ``traded`` FLAG, never by a value being
    zero. Zero is real on this venue (an unchanged ``+/-``, May 2029's open interest of exactly 0),
    and the verifier's note on the capture is that a row can carry ``change == 0.0`` while ``last``
    is NULL -- a numerically perfect "unchanged" printed on a month that DID NOT TRADE.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.transforms.bronze_to_silver import euronext_eod as S
from leviathan.transforms.raw_to_bronze import euronext_eod as T

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = _REPO / "tests" / "fixtures" / "w1c" / "euronext_ebm_table.html"
_AS_OF = "2026-07-29"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TASK = _load("jobs/batch/futures_eod_task.py", "futures_eod_task_euronext_silver")

# The seven expiries the venue's own data-lasttradesdate attribute marks as traded.
_TRADED = ("Sep 2026", "Dec 2026", "Mar 2027", "May 2027", "Sep 2027", "Dec 2027", "Mar 2028")
_UNTRADED = ("May 2028", "Sep 2028", "Dec 2028", "Mar 2029", "May 2029")


def bronze(product: str = "EBM-DPAR", as_of: str = _AS_OF) -> pd.DataFrame:
    """One product-day of bronze from the LIVE capture.

    All three MATIF products render an identical table with the same id and shape (capture_notes),
    and the leviathan slug comes from the ``product`` argument rather than from the page, so the
    one landed table is what a second product's capture is modelled with here. It is never a claim
    about maize or rapeseed PRICES -- only about the projection, which is product-agnostic."""
    return T.build_bronze(_FIXTURE.read_bytes(), product=product, as_of_date=as_of)[0]


def silver(*frames: pd.DataFrame) -> pd.DataFrame:
    return S.build_euronext_eod_silver(pd.concat(list(frames), ignore_index=True))


def _row(df: pd.DataFrame, delivery: str):
    hit = df[df["raw_symbol"] == delivery]
    assert len(hit) == 1, f"{delivery} appears {len(hit)} time(s)"
    return hit.iloc[0]


# ---------------------------------------------------------------------------
class TestTheContractShape:
    def test_the_seventeen_physical_columns_plus_the_two_partition_keys(self):
        out = silver(bronze())
        assert list(out.columns) == FC.SILVER_COLUMNS
        assert len(out) == 12

    def test_the_row_validator_passes(self):
        assert FC.lint_frame(silver(bronze())) == []

    def test_the_labels_are_map_derived_and_never_source_parsed(self):
        out = silver(bronze())
        assert set(out["unit"]) == {"EUR/t"} and set(out["currency"]) == {"EUR"}
        assert set(out["settle_kind"]) == {"settlement"}, "the SETTL. column, not the Last"
        assert set(out["source"]) == {"euronext_matif"}

    def test_every_row_is_a_futures_row_with_a_delivery_month(self):
        out = silver(bronze())
        assert set(out["instrument_kind"]) == {"futures"}
        assert out["contract_month"].notna().all()
        assert list(out["contract_month"])[:3] == ["2026-09", "2026-12", "2027-03"]

    def test_expiry_date_and_dataset_stay_null(self):
        out = silver(bronze())
        assert out["expiry_date"].isna().all() and out["dataset"].isna().all()

    def test_the_dtypes_are_the_contract_dtypes(self):
        got = {c: str(t) for c, t in silver(bronze()).dtypes.items()}
        assert got["trade_date"] == "datetime64[us]" and got["expiry_date"] == "datetime64[us]"
        assert got["settle"] == got["close"] == "float64"
        assert got["volume"] == got["open_interest"] == "Int64"
        assert got["trade_year"] == "int64"

    def test_the_session_comes_from_the_key_and_so_does_the_partition_year(self):
        """The rendered table publishes a Time and NO date -- the raw key's as_of_date= segment is
        the only session authority this leg has, and it decides the partition."""
        out = silver(bronze(as_of="2026-08-03"))
        assert set(out["trade_date"]) == {pd.Timestamp("2026-08-03")}
        assert set(out["trade_year"]) == {2026}

    def test_an_empty_bronze_frame_is_an_empty_silver_frame_not_an_error(self):
        for empty in (None, pd.DataFrame()):
            out = S.build_euronext_eod_silver(empty)
            assert len(out) == 0 and list(out.columns) == FC.SILVER_COLUMNS


# ---------------------------------------------------------------------------
class TestSettlementIsThePriceOfRecord:
    def test_settle_prints_on_every_row_including_the_untraded_back_months(self):
        out = silver(bronze())
        assert int(out["settle"].notna().sum()) == 12
        for delivery in _UNTRADED:
            assert float(_row(out, delivery)["settle"]) > 0

    def test_the_front_month_carries_the_settlement_and_the_last_separately(self):
        row = _row(silver(bronze()), "Sep 2026")
        assert float(row["settle"]) == pytest.approx(227.75)     # Settl.
        assert float(row["close"]) == pytest.approx(226.50)      # Last -- a TRADE
        assert row["settle"] != row["close"]
        assert float(row["open"]) == pytest.approx(227.50)
        assert float(row["high"]) == pytest.approx(229.25)
        assert float(row["low"]) == pytest.approx(225.50)
        assert int(row["volume"]) == 41_367 and int(row["open_interest"]) == 201_888

    def test_the_last_is_never_promoted_into_the_settlement(self):
        """The tempting repair on a row with no Settl. is to fall back to Last. That would publish
        a trade as a settlement on the one leg whose settle_kind claims otherwise."""
        b = bronze()
        b.loc[b["raw_symbol"] == "Sep 2026", "settle"] = float("nan")
        row = _row(silver(b), "Sep 2026")
        assert pd.isna(row["settle"])
        assert float(row["close"]) == pytest.approx(226.50)


# ---------------------------------------------------------------------------
class TestTheTradedFlagDecidesWhatExists:
    def test_an_untraded_month_publishes_a_settlement_and_an_open_interest_only(self):
        row = _row(silver(bronze()), "May 2028")
        assert float(row["settle"]) == pytest.approx(235.00)
        for col in ("open", "high", "low", "close"):
            assert pd.isna(row[col]), col
        assert pd.isna(row["volume"])
        assert int(row["open_interest"]) == 64

    def test_a_zero_open_interest_on_an_untraded_month_is_a_value_and_is_never_masked(self):
        """May 2029: O.I is exactly 0. Masking it -- or reading the 0 as 'absent' -- would erase a
        true observation on the venue where zero is a real published number."""
        row = _row(silver(bronze()), "May 2029")
        assert int(row["open_interest"]) == 0 and not pd.isna(row["open_interest"])
        assert float(row["settle"]) == pytest.approx(228.75)

    def test_a_change_of_zero_on_an_untraded_month_publishes_nothing_but_the_settlement(self):
        """THE VERIFIER'S NOTE, pinned. A bronze row can carry change == 0.0 with last NULL: a
        numerically perfect 'unchanged' on a month that DID NOT TRADE. No value test can separate
        that from a real flat day -- only the venue's own flag can -- and the +/- column has no
        contract column to land in anyway, so it is dropped rather than carried."""
        b = bronze()
        mask = b["raw_symbol"] == "May 2029"
        b.loc[mask, "change"] = 0.0
        assert bool(b.loc[mask, "traded"].iloc[0]) is False
        assert pd.isna(b.loc[mask, "last"].iloc[0])
        row = _row(silver(b), "May 2029")
        assert "change" not in silver(b).columns
        assert pd.isna(row["close"]) and pd.isna(row["volume"])
        assert float(row["settle"]) == pytest.approx(228.75)

    def test_a_traded_month_whose_flag_is_cleared_loses_its_session_not_its_settlement(self):
        """The mask is the venue's flag and nothing else -- proven non-vacuous by flipping it on a
        row that really did trade."""
        b = bronze()
        b.loc[b["raw_symbol"] == "Sep 2026", "traded"] = False
        row = _row(silver(b), "Sep 2026")
        for col in ("open", "high", "low", "close"):
            assert pd.isna(row[col]), col
        assert pd.isna(row["volume"])
        assert float(row["settle"]) == pytest.approx(227.75)
        assert int(row["open_interest"]) == 201_888

    def test_the_traded_rows_keep_their_whole_session(self):
        out = silver(bronze())
        traded = out[out["close"].notna()]
        assert set(traded["raw_symbol"]) == set(_TRADED)
        assert traded["volume"].notna().all()
        assert traded[["open", "high", "low"]].notna().all().all()

    def test_the_quote_columns_never_reach_the_contract(self):
        """A quote is not a traded or marked level (the JSE bid/offer precedent), and Time is a
        clock label rather than a measure."""
        b = bronze()
        for col in ("bid", "ask", "change", "quote_time", "traded", "product"):
            assert col in b.columns
        assert set(silver(b).columns).isdisjoint(
            {"bid", "ask", "change", "quote_time", "traded", "product"})


# ---------------------------------------------------------------------------
class TestTheThreeProducts:
    def test_three_products_become_three_slugs_and_three_partitions(self):
        out = silver(*[bronze(p) for p in sorted(T.EURONEXT_PRODUCT_MAP)])
        assert set(out["leviathan_slug"]) == set(T.EURONEXT_PRODUCT_MAP.values())
        assert out[FC.PARTITION_COLUMNS].drop_duplicates().shape[0] == 3
        assert FC.lint_frame(out) == []
        TASK.assert_no_duplicates(out)

    def test_a_slug_this_leg_does_not_own_is_refused(self):
        b = bronze()
        b.loc[0, "leviathan_slug"] = "rapeseed_oil_zce"
        with pytest.raises(ValueError, match="not MATIF contracts"):
            S.build_euronext_eod_silver(b)

    def test_a_bronze_frame_missing_a_column_is_refused(self):
        for col in ("settle", "traded", "last"):
            with pytest.raises(ValueError, match="missing columns"):
                S.build_euronext_eod_silver(bronze().drop(columns=[col]))

    def test_a_null_session_would_orphan_the_partition_and_is_refused(self):
        b = bronze()
        b.loc[0, "trade_date"] = pd.NaT
        with pytest.raises(ValueError, match="trade_year=nan"):
            S.build_euronext_eod_silver(b)


# ---------------------------------------------------------------------------
class TestNoDuplicateCollapse:
    """JSE and CEPEA collapse identical re-serves because ONE portal object is overwritten in
    place. Not here: one object per (product, as_of_date), and trade_date comes from that key."""

    def test_the_natural_key_and_the_f2_key_are_unique_on_a_product_day(self):
        out = silver(bronze())
        for key in (["leviathan_slug", "contract_month", "trade_date"],
                    ["leviathan_slug", "trade_date", "raw_symbol"]):
            assert out.groupby(key, dropna=False).size().max() == 1
        TASK.assert_no_duplicates(out)

    def test_two_disagreeing_curves_for_one_product_day_fail_loudly(self):
        """A duplicate natural key on this leg is a REAL conflict -- two curves claiming one
        product-day -- and must reach the uniqueness assertion rather than being deduped away."""
        b = bronze()
        other = bronze()
        other["settle"] = other["settle"] + 1.0
        out = silver(b, other)
        assert len(out) == 24
        with pytest.raises(ValueError, match="duplicate natural key"):
            TASK.assert_no_duplicates(out)


# ---------------------------------------------------------------------------
class TestHostWiring:
    def test_the_task_dispatches_this_builder(self):
        assert TASK._silver_builder("euronext") is S.build_euronext_eod_silver

    def test_the_leg_is_implemented_and_carries_its_measured_floor(self):
        spec = TASK.source_spec("euronext")
        assert spec.implemented is True and spec.todo == ""
        assert spec.rows_per_day == 24 and spec.rows_per_day_exact is False
        assert spec.publication_sources == ("euronext_matif",)

    def test_a_whole_day_clears_the_floor_and_a_single_product_day_does_not(self):
        """WHY THE FLOOR IS 24. The MEASURED day is 32 rows (EBM 12 + EMA 10 + ECO 10) and losing
        ANY ONE of the three products takes it to 20 or 22 -- three independent page renders in one
        run, which is this leg's actual failure mode. The arithmetic is asserted against the pinned
        per-product counts; the mechanical check runs on a frame, where the modelled EMA/ECO
        captures are 12-row copies of the one landed table, so the honest end-to-end case here is
        the single-product day (12 rows)."""
        spec = TASK.source_spec("euronext")
        counts = T.EURONEXT_MIN_ROWS
        assert sum(counts.values()) == 32
        for product in counts:
            assert sum(counts.values()) - counts[product] < spec.rows_per_day

        whole = silver(*[bronze(p) for p in sorted(T.EURONEXT_PRODUCT_MAP)])
        assert TASK.assert_row_floor(whole, spec, mode="backfill") == []
        bad = TASK.assert_row_floor(silver(bronze()), spec, mode="backfill")
        assert bad and "floor >= 24" in bad[0] and _AS_OF in bad[0]

    def test_a_foreign_publication_source_in_the_frame_is_caught_by_the_floor(self):
        """The floor scopes rows by source EQUALITY, never a substring: a leg that wrote someone
        else's source value fails loudly instead of being counted into their day."""
        out = silver(bronze())
        out.loc[0, "source"] = "czce"
        bad = TASK.assert_row_floor(out, TASK.source_spec("euronext"), mode="backfill")
        assert bad and "foreign publication source" in bad[0]

    def test_build_silver_routes_the_source_through_the_projection(self):
        out = TASK.build_silver([bronze()], source="euronext")
        assert list(out.columns) == FC.SILVER_COLUMNS and len(out) == 12
