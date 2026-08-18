"""D-LD (2026-08-18): the silver_food_cpi PIT-anchor pre-step.

WHY THIS FILE EXISTS
--------------------
``silver_food_cpi`` has fed the feature layer since the P65 baseline and could never be read by
the agent, for two measured reasons that are both producer/catalog defects rather than card gaps:

1. **No column could anchor an as-of guard.** The eight physical columns were ``country_iso,
   country_name, year, cpi_yoy_pct, cpi_yoy_z_5yr, cpi_yoy_z_10yr, cpi_available, source`` -- no
   date, no month, no release stamp. ``year_month`` needs a month column; ``data_date`` / ``ingest``
   need a date column to point at; and ``year`` is a bigint, so comparing it to an ISO as-of string
   is a type error on both serving backends. Every lookup raised ``ValueError: table
   silver_food_cpi has no knowledge/date column to anchor the as-of guard``.
2. **The source's own release stamp was fetched and thrown away.** The World Bank DataBank response
   metadata carries ``lastupdated`` (currently ``2026-07-13``) and the bronze parser kept only
   ``pages``.

The remedy is the WIRING WAVE-1 pre-step mechanism (CONAB ``survey_release_date``, SAGIS
``week_ending_date``): the PRODUCER derives ``data_date`` (the year-end observation date) and
``release_date`` (the ``lastupdated`` stamp). These tests pin that derivation, its fail-closed
edges, the no-regression of the eight pre-existing columns, and the catalog leg in the checked-in
DDL -- including the SILVER-F062 widen that landed in the writer and never in the catalog.

AWS-free and network-free: every input here is synthetic response bytes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.world_bank_food_cpi import (
    PIT_COLUMNS,
    SILVER_COLUMNS,
    build_food_cpi_silver,
)
from leviathan.transforms.raw_to_bronze.world_bank_food_cpi import (
    BRONZE_COLUMNS,
    RELEASE_DATE_META_KEY,
    extract_food_cpi_bronze,
    observation_data_date,
    release_date_from_meta,
)

_REPO = Path(__file__).resolve().parents[2]
_DDL = _REPO / "sql" / "athena" / "ddl" / "silver_food_cpi.sql"

# The live release stamp measured on all four raw objects in S3 on 2026-08-18.
_LASTUPDATED = "2026-07-13"

# Years chosen to mirror the real shape: a long run for IND/IDN, a 1993 start for RUS/UKR, and a
# published ABSENCE (value null) that must still carry both anchors.
_YEARS = list(range(1990, 2026))


def _wb_response(iso: str, name: str, *, first_year: int = 1990,
                 lastupdated: object = _LASTUPDATED, drop_lastupdated: bool = False) -> bytes:
    """Synthesise a World Bank DataBank response with the real two-element shape (newest-first)."""
    meta: dict = {"page": 1, "pages": 1, "per_page": 200, "total": len(_YEARS), "sourceid": "2"}
    if not drop_lastupdated:
        meta[RELEASE_DATE_META_KEY] = lastupdated
    records = []
    for i, year in enumerate(reversed(_YEARS)):
        value = None if year < first_year else round(4.0 + (i % 7) * 0.5, 4)
        records.append({
            "indicator": {"id": "FP.CPI.TOTL.ZG", "value": "Inflation, consumer prices (annual %)"},
            "country": {"id": iso[:2], "value": name},
            "countryiso3code": iso,
            "date": str(year),
            "value": value,
            "unit": "", "obs_status": "", "decimal": 1,
        })
    return json.dumps([meta, records]).encode("utf-8")


def _bronze_all() -> list[pd.DataFrame]:
    return [
        extract_food_cpi_bronze(_wb_response("IND", "India"), "IND"),
        extract_food_cpi_bronze(_wb_response("IDN", "Indonesia"), "IDN"),
        extract_food_cpi_bronze(_wb_response("RUS", "Russian Federation", first_year=1993), "RUS"),
        extract_food_cpi_bronze(_wb_response("UKR", "Ukraine", first_year=1993), "UKR"),
    ]


# ---------------------------------------------------------------------------
# The derivation itself.
# ---------------------------------------------------------------------------
def test_observation_data_date_is_the_year_end_of_the_reported_year():
    """data_date is the date the observation is ABOUT, not the date it was published -- a pure
    function of the row's own calendar year, which is why the silver transform may re-derive it."""
    assert observation_data_date(2025) == "2025-12-31"
    assert observation_data_date(1960) == "1960-12-31"
    assert observation_data_date("1993") == "1993-12-31"       # bigint or str, same answer
    with pytest.raises(ValueError):
        observation_data_date(93)


def test_release_date_comes_from_the_sources_own_lastupdated_stamp():
    assert release_date_from_meta({RELEASE_DATE_META_KEY: _LASTUPDATED}, "IND") == _LASTUPDATED
    assert release_date_from_meta({RELEASE_DATE_META_KEY: "  2026-07-13 "}, "IND") == _LASTUPDATED


@pytest.mark.parametrize("meta", [
    {},                                              # the pre-remedy behaviour: stamp discarded
    {RELEASE_DATE_META_KEY: None},
    {RELEASE_DATE_META_KEY: ""},
    {RELEASE_DATE_META_KEY: "2026-07"},              # month precision is not a release date
    {RELEASE_DATE_META_KEY: "13/07/2026"},
    "not-a-dict",
])
def test_release_date_fails_closed_rather_than_guessing(meta):
    """A guessed publication date would let the +195d as-of guard run ahead of any release we can
    actually date -- the one thing the measured lag exists to prevent."""
    with pytest.raises(ValueError) as exc:
        release_date_from_meta(meta, "IND")
    assert RELEASE_DATE_META_KEY in str(exc.value)


# ---------------------------------------------------------------------------
# Bronze parse coverage: BOTH anchors on EVERY row, published absences included.
# ---------------------------------------------------------------------------
def test_bronze_emits_both_anchors_on_every_row_including_published_absences():
    df = extract_food_cpi_bronze(_wb_response("RUS", "Russian Federation", first_year=1993), "RUS")
    assert list(df.columns) == BRONZE_COLUMNS
    assert len(df) == len(_YEARS)
    # 100% parse coverage on both anchors -- these are contract-non-null columns.
    assert int(df["data_date"].notna().sum()) == len(df)
    assert int(df["release_date"].notna().sum()) == len(df)
    # ...while the MEASURE is legitimately null before 1993: a published absence still carries a
    # date. This is the row shape a pre-1993 lookup returns, and it must never read as a zero.
    absent = df[df["year"] < 1993]
    assert len(absent) == 3
    assert absent["cpi_yoy_pct"].isna().all()
    assert absent["data_date"].tolist() == ["1990-12-31", "1991-12-31", "1992-12-31"]
    assert (absent["release_date"] == _LASTUPDATED).all()
    # every row's data_date is its own year-end, and every row carries the one global release.
    assert df["data_date"].tolist() == [f"{y}-12-31" for y in sorted(_YEARS)]
    assert set(df["release_date"]) == {_LASTUPDATED}


def test_bronze_refuses_a_response_it_cannot_date():
    with pytest.raises(ValueError) as exc:
        extract_food_cpi_bronze(_wb_response("IND", "India", drop_lastupdated=True), "IND")
    assert RELEASE_DATE_META_KEY in str(exc.value)


# ---------------------------------------------------------------------------
# Silver: the anchors survive the combine, and nothing else moved.
# ---------------------------------------------------------------------------
def test_silver_carries_both_anchors_in_the_declared_column_order():
    out = build_food_cpi_silver(_bronze_all())
    assert list(out.columns) == SILVER_COLUMNS
    assert SILVER_COLUMNS[-2:] == PIT_COLUMNS        # appended AFTER `source`, a pure suffix
    assert len(out) == 4 * len(_YEARS)
    assert int(out["data_date"].notna().sum()) == len(out)
    assert int(out["release_date"].notna().sum()) == len(out)
    assert set(out["release_date"]) == {_LASTUPDATED}
    # the anchor is per-ROW and agrees with that row's own year on all of them.
    assert (out["data_date"] == out["year"].map(lambda y: f"{y}-12-31")).all()


def test_silver_rederives_data_date_from_year_even_if_bronze_predates_the_prestep():
    """data_date is pure in `year`, so a bronze parquet written before the pre-step still produces
    a correctly-anchored silver row. release_date is NOT derivable and must not be invented."""
    legacy = [d.drop(columns=["data_date"]) for d in _bronze_all()]
    out = build_food_cpi_silver(legacy)
    assert (out["data_date"] == out["year"].map(lambda y: f"{y}-12-31")).all()


def test_silver_refuses_bronze_with_no_release_date():
    legacy = [d.drop(columns=["release_date"]) for d in _bronze_all()]
    with pytest.raises(ValueError) as exc:
        build_food_cpi_silver(legacy)
    assert "release_date" in str(exc.value)


def test_silver_refuses_bronze_whose_release_date_is_null():
    nulled = _bronze_all()
    nulled[0] = nulled[0].assign(release_date=None)
    with pytest.raises(ValueError) as exc:
        build_food_cpi_silver(nulled)
    assert "release_date" in str(exc.value)


def test_the_eight_pre_existing_columns_are_untouched_by_the_prestep():
    """NO-REGRESSION: the anchors are additive. Every legacy column keeps its pre-remedy value,
    including the strictly-prior rolling z-scores (shift(1)+rolling, 5yr/min 3 and 10yr/min 5) and
    the coverage flag's exact identity with `cpi_yoy_pct.notna()`."""
    out = build_food_cpi_silver(_bronze_all())
    legacy = [c for c in SILVER_COLUMNS if c not in PIT_COLUMNS]
    assert legacy == ["country_iso", "country_name", "year", "cpi_yoy_pct", "cpi_yoy_z_5yr",
                      "cpi_yoy_z_10yr", "cpi_available", "source"]
    assert (out["cpi_available"] == out["cpi_yoy_pct"].notna().astype("int8")).all()
    assert set(out["source"]) == {"wb_food_cpi"}
    rus = out[out["country_iso"] == "RUS"].sort_values("year").reset_index(drop=True)
    # first three years are the published absence; the z-scores stay null until 3 / 5 prior
    # observations exist, i.e. they start LATER than the level, exactly as before.
    assert rus.loc[rus["year"] < 1993, "cpi_yoy_z_5yr"].isna().all()
    # 3 strictly-prior observations exist first at 1996 (1993/94/95), 5 first at 1998 -- so a
    # 1993-start country's z lags its level by 3 and 5 years respectively.
    assert int(rus.loc[rus["cpi_yoy_z_5yr"].notna(), "year"].min()) == 1996
    assert int(rus.loc[rus["cpi_yoy_z_10yr"].notna(), "year"].min()) == 1998
    # the z is strictly prior: recomputing it from the shifted rolling window reproduces it.
    s = rus["cpi_yoy_pct"]
    rolled = s.shift(1).rolling(window=5, min_periods=3)
    expected = ((s - rolled.mean()) / rolled.std()).round(4).astype("float32")
    pd.testing.assert_series_equal(rus["cpi_yoy_z_5yr"], expected, check_names=False)


# ---------------------------------------------------------------------------
# The catalog leg: the checked-in DDL is what config_check.check_numbers_schema_pins reads.
# ---------------------------------------------------------------------------
def _ddl_columns() -> dict[str, str]:
    """(column -> declared Athena type) parsed from the column block of the checked-in hand DDL."""
    cols: dict[str, str] = {}
    inside = False
    for raw in _DDL.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not inside:
            if line.upper().startswith("CREATE EXTERNAL TABLE") and line.endswith("("):
                inside = True
            continue
        if line.startswith(")"):
            break
        if not line or line.startswith("--"):
            continue
        parts = line.rstrip(",").split()
        cols[parts[0]] = parts[1].lower()
    return cols


def test_checked_in_ddl_declares_both_pit_anchor_columns():
    """The numbers card anchors date_col / knowledge_date_col on data_date and provenance_col on
    release_date; check_numbers_schema_pins resolves those names against THIS file."""
    cols = _ddl_columns()
    for col in PIT_COLUMNS:
        assert cols.get(col) == "string", (col, cols)


def test_checked_in_ddl_declares_the_full_producer_schema_in_writer_order():
    """The DDL is the catalog face of what the producer writes -- same columns, same order."""
    assert list(_ddl_columns()) == SILVER_COLUMNS


def test_checked_in_ddl_declares_the_widened_measure_types():
    """SILVER-F062 landed in the WRITER (F010 target_arrow_type float64) and never in the CATALOG.
    While the DDL said `float` (Athena `real`) over a DOUBLE parquet, Athena raised HIVE_BAD_DATA
    on every measure column -- i.e. on every metric the card serves except the coverage flag."""
    cols = _ddl_columns()
    for col in ("cpi_yoy_pct", "cpi_yoy_z_5yr", "cpi_yoy_z_10yr"):
        assert cols[col] == "double", (col, cols[col])
    assert cols["cpi_available"] == "bigint"
    assert "float" not in cols.values() and "tinyint" not in cols.values()
