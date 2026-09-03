"""PRICE_AND_PLAYBOOKS W1c -- the Bursa FCPO bronze -> ``silver_futures_eod`` projection.

The parse half lives in ``tests/unit/test_bursa_fcpo.py``; the fixtures are the same ones, the real
``ses=day`` API body captured live on 2026-07-29 (24 delivery months, 14 traded + 10 quiet) and its
after-hours twin.

What this file pins:

  * SETT. PRICE is the price of record and prints for all 24 months, the quiet back months
    included -- which is why those rows are published at all. LAST DONE is a trade and lands in
    ``close``, never in ``settle``;
  * ``raw_symbol`` is the MONTH label. The NAME cell is the constant string ``FCPO`` on all 24
    rows, so using it would collapse the whole curve onto ONE F2 key;
  * a quiet month's volume is NULL and never 0 -- the venue printed ``"-"`` and this leg invents no
    counts;
  * this is a FORWARD-ACCUMULATION leg with one landed object per session, so nothing is collapsed
    here and a duplicate natural key is a real conflict.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.transforms.bronze_to_silver import bursa_fcpo as S
from leviathan.transforms.raw_to_bronze import bursa_fcpo as T

_REPO = Path(__file__).resolve().parents[2]
_FIXTURES = _REPO / "tests" / "fixtures" / "w1c"
_DAY = _FIXTURES / "bursa_fcpo_api_sample.json"
_NIGHT = _FIXTURES / "bursa_fcpo_api_night_sample.json"
_AS_OF = "2026-07-29"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TASK = _load("jobs/batch/futures_eod_task.py", "futures_eod_task_bursa_silver")

# V2-4 (2026-09-02): the Bursa leg is PARKED (BURSA_CODE_MAP is EMPTY; the palm slug carries the
# CME USD tape). The projection is exercised under the HISTORICAL binding injected into the
# parser's map, this module's derived slug set AND the slug's CONTRACT_MAP record (MYR/t, MYR,
# settlement, bursa -- exactly tests/unit/silver/test_futures_eod_free_chain.py::_inject_bursa,
# so a MYR bulletin frame is never labelled with the CME USD record here; STEP-12 F9). TestParked
# pins the SHIPPED refusal against the map captured BEFORE the fixture runs.
_SLUG = "malaysian_crude_palm_oil_cme"
_HISTORICAL_BURSA_RECORD = {"unit": "MYR/t", "currency": "MYR", "settle_kind": "settlement",
                            "source": "bursa"}
_SHIPPED_CONTRACT_MAP = {slug: dict(rec) for slug, rec in FC.CONTRACT_MAP.items()}


@pytest.fixture(autouse=True)
def _injected_bursa_binding(monkeypatch):
    monkeypatch.setattr(T, "BURSA_CODE_MAP", {"FCPO": _SLUG})
    monkeypatch.setattr(S, "_BURSA_SLUGS", frozenset({_SLUG}))
    monkeypatch.setattr(FC, "CONTRACT_MAP",
                        {**FC.CONTRACT_MAP, _SLUG: dict(_HISTORICAL_BURSA_RECORD)})


def bronze(as_of: str = _AS_OF) -> pd.DataFrame:
    return T.build_bronze(_DAY.read_bytes(), code="FCPO", as_of_date=as_of)[0]


def silver(*frames: pd.DataFrame) -> pd.DataFrame:
    return S.build_bursa_fcpo_silver(pd.concat(list(frames), ignore_index=True))


def _row(df: pd.DataFrame, month: str):
    hit = df[df["raw_symbol"] == month]
    assert len(hit) == 1, f"{month} appears {len(hit)} time(s)"
    return hit.iloc[0]


# ---------------------------------------------------------------------------
class TestTheContractShape:
    def test_the_seventeen_physical_columns_plus_the_two_partition_keys(self):
        out = silver(bronze())
        assert list(out.columns) == FC.SILVER_COLUMNS
        assert len(out) == 24

    def test_the_row_validator_passes(self):
        assert FC.lint_frame(silver(bronze())) == []

    def test_the_labels_are_map_derived_and_never_source_parsed(self):
        # The test's own claim, stated as the map: whatever CONTRACT_MAP says for the slug is what
        # the row carries -- and under the injected HISTORICAL binding that is the Bursa record,
        # asserted LITERALLY: a MYR bulletin is MYR/t in MYR from source bursa, never the palm
        # slug's shipped CME USD record (the SHIPPED leg refuses these rows, see TestParked).
        out = silver(bronze())
        assert FC.contract_for(_SLUG) == _HISTORICAL_BURSA_RECORD
        assert set(out["unit"]) == {"MYR/t"} and set(out["currency"]) == {"MYR"}
        assert set(out["settle_kind"]) == {"settlement"}, "SETT. PRICE, not LAST DONE"
        assert set(out["source"]) == {"bursa"}
        assert set(out["leviathan_slug"]) == {_SLUG}

    def test_every_row_is_a_futures_row_with_a_delivery_month(self):
        out = silver(bronze())
        assert set(out["instrument_kind"]) == {"futures"}
        assert out["contract_month"].notna().all()
        assert list(out["contract_month"])[:3] == ["2026-08", "2026-09", "2026-10"]
        assert list(out["contract_month"])[-1] == "2029-07"

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
        """The API body carries no date field and the endpoint has no date parameter, so the raw
        key's as_of_date= segment is the only session authority -- and it decides the partition."""
        out = silver(bronze(as_of="2026-08-03"))
        assert set(out["trade_date"]) == {pd.Timestamp("2026-08-03")}
        assert set(out["trade_year"]) == {2026}

    def test_an_empty_bronze_frame_is_an_empty_silver_frame_not_an_error(self):
        for empty in (None, pd.DataFrame()):
            out = S.build_bursa_fcpo_silver(empty)
            assert len(out) == 0 and list(out.columns) == FC.SILVER_COLUMNS


# ---------------------------------------------------------------------------
class TestSettlementIsThePriceOfRecord:
    def test_sett_price_prints_for_all_twenty_four_months(self):
        out = silver(bronze())
        assert int(out["settle"].notna().sum()) == 24
        assert float(out["settle"].min()) > 4000.0, "MYR/t, never scaled and never FX-ed"

    def test_the_front_month_is_read_cell_for_cell(self):
        row = _row(silver(bronze()), "Aug 2026")
        assert row["contract_month"] == "2026-08"
        assert float(row["settle"]) == pytest.approx(4540.0)      # SETT. PRICE
        assert float(row["close"]) == pytest.approx(4551.0)       # LAST DONE -- a TRADE
        assert row["settle"] != row["close"]
        assert float(row["open"]) == pytest.approx(4534.0)
        assert float(row["high"]) == pytest.approx(4570.0)
        assert float(row["low"]) == pytest.approx(4528.0)
        assert int(row["volume"]) == 1_025 and int(row["open_interest"]) == 9_202

    def test_last_done_is_never_promoted_into_the_settlement(self):
        b = bronze()
        b.loc[b["raw_symbol"] == "Aug 2026", "settle"] = float("nan")
        row = _row(silver(b), "Aug 2026")
        assert pd.isna(row["settle"])
        assert float(row["close"]) == pytest.approx(4551.0)

    def test_a_quiet_back_month_publishes_a_settlement_and_nothing_else(self):
        """Mar 2028: every traded cell is '-'. The settlement is real and the volume is NULL --
        never 0, which would be a count this leg invented out of the venue's silence."""
        row = _row(silver(bronze()), "Mar 2028")
        assert float(row["settle"]) == pytest.approx(4656.0)
        for col in ("open", "high", "low", "close"):
            assert pd.isna(row[col]), col
        assert pd.isna(row["volume"]) and pd.isna(row["open_interest"])

    def test_open_interest_survives_the_embedded_anchor_decode(self):
        """The OI cell is an anchor followed by two hidden divs, and a whole-cell tag strip NULLs
        it on every traded month. Bronze takes the anchor text; this pins that the number reaches
        the contract column, which is what futures_roll reads."""
        out = silver(bronze())
        assert int(out["open_interest"].notna().sum()) == 15
        assert int(_row(out, "Jan 2028")["open_interest"]) == 28

    def test_the_quote_columns_never_reach_the_contract(self):
        b = bronze()
        for col in ("bid", "ask", "change", "code", "last"):
            assert col in b.columns
        assert set(silver(b).columns).isdisjoint({"bid", "ask", "change", "code", "last"})


# ---------------------------------------------------------------------------
class TestTheMonthIsTheSymbol:
    def test_raw_symbol_is_the_month_label_and_the_f2_key_is_unique(self):
        """THE DEFECT THIS AVOIDS: the NAME cell is the constant 'FCPO' on all 24 rows, so using it
        as raw_symbol collapses the whole curve onto ONE F2 key -- 23 lost months at worst."""
        out = silver(bronze())
        assert len(set(out["raw_symbol"])) == 24
        assert set(out["raw_symbol"]) >= {"Aug 2026", "Mar 2028", "Jul 2029"}
        for key in (["leviathan_slug", "contract_month", "trade_date"],
                    ["leviathan_slug", "trade_date", "raw_symbol"]):
            assert out.groupby(key, dropna=False).size().max() == 1
        TASK.assert_no_duplicates(out)

    def test_the_month_is_carried_verbatim_and_is_never_re_parsed_here(self):
        b = bronze()
        assert list(silver(b)["raw_symbol"]) == list(b["raw_symbol"])


# ---------------------------------------------------------------------------
class TestNoDuplicateCollapse:
    """Forward accumulation: one landed object per session, and trade_date comes from its key. No
    overwritten-in-place portal object (JSE) and no history/daily overlap (DCE, CEPEA)."""

    def test_two_disagreeing_captures_of_one_day_fail_loudly(self):
        b = bronze()
        other = bronze()
        other["settle"] = other["settle"] + 1.0
        out = silver(b, other)
        assert len(out) == 48
        with pytest.raises(ValueError, match="duplicate natural key"):
            TASK.assert_no_duplicates(out)

    def test_the_after_hours_session_never_reaches_this_projection(self):
        """The T+1 body is a COMPLETE, plausible 24-month table with different prices, so the guard
        has to be upstream of the frame -- there is nothing in a bronze row that still says which
        session it came from."""
        with pytest.raises(ValueError, match="AFTER-HOURS"):
            T.build_bronze(_NIGHT.read_bytes(), code="FCPO", as_of_date=_AS_OF)


# ---------------------------------------------------------------------------
class TestRefusals:
    def test_a_slug_this_leg_does_not_own_is_refused(self):
        b = bronze()
        b.loc[0, "leviathan_slug"] = "palm_olein_dce"
        with pytest.raises(ValueError, match="not Bursa contracts"):
            S.build_bursa_fcpo_silver(b)

    def test_a_bronze_frame_missing_a_column_is_refused(self):
        for col in ("settle", "last", "open_interest"):
            with pytest.raises(ValueError, match="missing columns"):
                S.build_bursa_fcpo_silver(bronze().drop(columns=[col]))

    def test_a_null_session_would_orphan_the_partition_and_is_refused(self):
        b = bronze()
        b.loc[0, "trade_date"] = pd.NaT
        with pytest.raises(ValueError, match="trade_year=nan"):
            S.build_bursa_fcpo_silver(b)


# ---------------------------------------------------------------------------
class TestParked:
    """V2-4 (2026-09-02): with the SHIPPED empty map this leg owns NO slug, so a MYR bulletin
    frame can never be labelled with the palm slug's USD record by this projection."""

    def test_the_shipped_leg_refuses_every_frame(self, monkeypatch):
        b = bronze()                                   # parsed under the injected binding
        monkeypatch.setattr(S, "_BURSA_SLUGS", frozenset())
        with pytest.raises(ValueError, match="not Bursa contracts"):
            S.build_bursa_fcpo_silver(b)

    def test_the_shipped_slug_set_is_empty_and_the_palm_record_is_usd(self):
        # The SHIPPED derived set is frozenset(BURSA_CODE_MAP.values()) at import, and the
        # transform's import-time lint binds that map to CONTRACT_MAP's source=='bursa' slugs --
        # so 'no bursa slug in the map' IS 'the shipped set is empty'.
        # ... read from the map captured at import, BEFORE the autouse fixture injected history
        assert not [s for s, r in _SHIPPED_CONTRACT_MAP.items() if r["source"] == "bursa"]
        rec = _SHIPPED_CONTRACT_MAP[_SLUG]
        assert rec["source"] == "databento_glbx_mdp3" and rec["currency"] == "USD"
        assert rec["unit"] == "USD/metric ton"
        # ... and the fixture's injection is exactly the historical record, on the palm slug only
        assert FC.contract_for(_SLUG) == _HISTORICAL_BURSA_RECORD
        assert {s for s, r in FC.CONTRACT_MAP.items()
                if r != _SHIPPED_CONTRACT_MAP.get(s)} == {_SLUG}


# ---------------------------------------------------------------------------
class TestHostWiring:
    def test_the_task_dispatches_this_builder(self):
        assert TASK._silver_builder("bursa") is S.build_bursa_fcpo_silver

    def test_the_leg_is_implemented_and_carries_its_measured_floor(self):
        spec = TASK.source_spec("bursa")
        assert spec.implemented is True and spec.todo == ""
        assert spec.rows_per_day == 20 and spec.rows_per_day_exact is False
        assert spec.publication_sources == ("bursa",)

    def test_a_whole_curve_clears_the_floor_and_a_truncated_one_does_not(self):
        """The floor is 20 against a MEASURED 24 delivery months. per_page=50 covers the curve with
        room to spare, so a short day is the venue paginating on us -- months missing, never a thin
        session (the bronze recordsTotal check is the other half of that same guard)."""
        spec = TASK.source_spec("bursa")
        out = silver(bronze())
        # Under the injected HISTORICAL binding the map-derived source IS the leg's publication
        # source, so the floor's source-equality scope holds with no relabel (STEP-12 F9).
        assert set(out["source"]) == {"bursa"} == set(spec.publication_sources)
        assert TASK.assert_row_floor(out, spec, mode="backfill") == []
        bad = TASK.assert_row_floor(out.head(19), spec, mode="backfill")
        assert bad and "floor >= 20" in bad[0] and _AS_OF in bad[0]

    def test_a_foreign_publication_source_in_the_frame_is_caught_by_the_floor(self):
        out = silver(bronze())
        out.loc[0, "source"] = "miax"
        bad = TASK.assert_row_floor(out, TASK.source_spec("bursa"), mode="backfill")
        assert bad and "foreign publication source" in bad[0]

    def test_build_silver_routes_the_source_through_the_projection(self):
        out = TASK.build_silver([bronze()], source="bursa")
        assert list(out.columns) == FC.SILVER_COLUMNS and len(out) == 24
