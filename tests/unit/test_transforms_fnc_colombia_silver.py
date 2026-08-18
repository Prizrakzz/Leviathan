"""Unit tests for FNC Colombia bronze -> silver transforms."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.fnc_colombia import (
    AREA_OUTPUT_COLUMNS,
    EXPORTS_PORT_TYPE_OUTPUT_COLUMNS,
    MONTHLY_OUTPUT_COLUMNS,
    transform_fnc_colombia_area_department,
    transform_fnc_colombia_bronze_to_silver,
    transform_fnc_colombia_monthly,
)


def _monthly_series(value: float, series_name: str, unit: str = "unit") -> pd.DataFrame:
    return pd.DataFrame([
        {
            "series_name": series_name,
            "year": 2024,
            "month": 1,
            "date": date(2024, 1, 1),
            "value": value,
            "unit": unit,
            "source": "fnc_excel",
        }
    ])


def _bronze_series() -> dict[str, pd.DataFrame]:
    return {
        "produccion_mensual": _monthly_series(700.0, "produccion_mensual"),
        "precio_ex_dock_mensual": _monthly_series(310.5, "precio_ex_dock_mensual"),
        "precio_interno_mensual": _monthly_series(1_950_000.0, "precio_interno_mensual"),
        "exportaciones_total_volumen": _monthly_series(925.0, "exportaciones_total_volumen"),
        "exportaciones_total_valor": _monthly_series(363.3, "exportaciones_total_valor"),
        "area_departamento": pd.DataFrame([
            {
                "series_name": "area_departamento",
                "year": 2024,
                "department_raw": "Nariño",
                "department": "narino",
                "area_1000_ha": 35.2,
                # D-LD Tranche 2 P0: the bronze PIT stamp extract_fnc_excel writes onto every
                # series. The silver area table used to drop it, which left the table with NO
                # knowledge column at all.
                "ingest_date": "2026-06-02",
            }
        ]),
        "exportaciones_puerto_tipo": pd.DataFrame([
            {
                "series_name": "exportaciones_puerto_tipo",
                "year": 2024,
                "month": 1,
                "date": date(2024, 1, 1),
                "port_raw": "Aerp. El Dorado",
                "port": "aerp_el_dorado",
                "coffee_type_raw": "Café Verde",
                "coffee_type": "cafe_verde",
                "exports_bags_60kg": 84.0,
                "exports_value_usd": 60776.73,
            }
        ]),
    }


def test_monthly_silver_pivots_and_converts_units() -> None:
    monthly = transform_fnc_colombia_monthly(_bronze_series())
    assert list(monthly.columns) == MONTHLY_OUTPUT_COLUMNS
    assert len(monthly) == 1
    row = monthly.iloc[0]
    assert row["leviathan_slug"] == "arabica_coffee"
    assert row["country"] == "colombia"
    assert row["production_bags_60kg"] == pytest.approx(700_000.0)
    assert row["exports_bags_60kg"] == pytest.approx(925_000.0)
    assert row["exports_value_usd_m"] == pytest.approx(363.3)
    assert row["ex_dock_price_usd_cents_per_lb"] == pytest.approx(310.5)
    assert row["internal_price_cop_per_125kg"] == pytest.approx(1_950_000.0)


def test_area_department_silver_normalizes_and_converts_area() -> None:
    area = transform_fnc_colombia_area_department(_bronze_series()["area_departamento"])
    assert list(area.columns) == AREA_OUTPUT_COLUMNS
    row = area.iloc[0]
    assert row["leviathan_slug"] == "arabica_coffee"
    assert row["department"] == "narino"
    assert row["area_ha"] == pytest.approx(35_200.0)


def test_exports_port_type_silver_outputs_expected_columns() -> None:
    silver = transform_fnc_colombia_bronze_to_silver(_bronze_series())
    exports = silver.exports_port_type
    assert list(exports.columns) == EXPORTS_PORT_TYPE_OUTPUT_COLUMNS
    row = exports.iloc[0]
    assert row["port"] == "aerp_el_dorado"
    assert row["coffee_type"] == "cafe_verde"
    assert row["exports_bags_60kg"] == pytest.approx(84.0)
    assert row["exports_value_usd"] == pytest.approx(60776.73)


def test_conflicting_duplicate_monthly_metric_raises() -> None:
    duplicate = pd.concat([
        _monthly_series(700.0, "produccion_mensual"),
        _monthly_series(701.0, "produccion_mensual"),
    ])
    with pytest.raises(ValueError, match="conflicting duplicate"):
        transform_fnc_colombia_monthly({"produccion_mensual": duplicate})


# =============================================================================================
# D-LD Tranche 2 (2026-08-18) P0 -- the PIT anchor on silver_fnc_colombia_area_department.
#
# The table physically carried leviathan_slug/country/department/department_raw/year/area_ha/
# source and NOTHING date-shaped, so the numbers read-path could not build an as-of guard at all:
# query._guard raises "has no knowledge/date column to anchor the as-of guard" on EVERY lookup,
# and the year_month fallback is unreachable (year exists, month does not). Anchoring on the int
# `year` was rejected -- it would CAST a PROJECTED partition column (the Jul-2026 LIST-storm
# non-sargable pattern) and LEAK, making year Y citable from 1 January of year Y.
#
# Measured 2026-08-18 against the canonical parquet (24 objects,
# s3://leviathan-dev-shahem-001/silver/fnc_colombia/area_department/): 492 rows, 23 departments,
# years 2002..2025, national 2025 = 833,059.14 ha. The matching bronze object carries
# ingest_date = '2026-06-02' on 492/492 rows -- the stamp exists upstream and was simply dropped.
# =============================================================================================

def test_area_department_carries_the_bronze_ingest_stamp() -> None:
    """THE FIX: ingest_date survives bronze->silver, as ISO TEXT.

    The guard compares it as a string (CAST(ingest_date AS varchar) <= '<asof>'), so the column
    must be text -- a date/timestamp physical type would not match the `ingest_date string` the
    Glue catalog declares."""
    area = transform_fnc_colombia_area_department(_bronze_series()["area_departamento"])
    assert "ingest_date" in area.columns
    assert area["ingest_date"].tolist() == ["2026-06-02"]
    assert all(isinstance(v, str) for v in area["ingest_date"])
    assert area["ingest_date"].notna().all()


def test_area_output_columns_pin_the_pit_anchor_last() -> None:
    """The column list is the writer schema. ingest_date is appended LAST so the Glue migration
    stays a pure additive ADD COLUMNS against the existing catalog order."""
    assert AREA_OUTPUT_COLUMNS == [
        "leviathan_slug", "country", "department", "department_raw",
        "year", "area_ha", "source", "ingest_date",
    ]


def test_area_bronze_without_ingest_date_is_refused() -> None:
    """Fail LOUD, not fail-closed-and-silent: a silver table written with a null knowledge column
    withholds every row from every as-of read and is indistinguishable from an empty table."""
    stampless = _bronze_series()["area_departamento"].drop(columns=["ingest_date"])
    with pytest.raises(ValueError, match="missing columns"):
        transform_fnc_colombia_area_department(stampless)


def test_area_blank_ingest_stamp_is_refused() -> None:
    present_but_empty = _bronze_series()["area_departamento"].assign(ingest_date="   ")
    with pytest.raises(ValueError, match="no ingest_date"):
        transform_fnc_colombia_area_department(present_but_empty)

    null_stamp = _bronze_series()["area_departamento"].assign(ingest_date=None)
    with pytest.raises(ValueError, match="no ingest_date"):
        transform_fnc_colombia_area_department(null_stamp)


def test_area_pit_anchor_does_not_leak_into_the_fnc_siblings() -> None:
    """NO-REGRESSION: the two carded fnc siblings (monthly, exports_port_type) are ALREADY
    PIT-anchored on their own `date` column and are already mirrored/served. Their writer schemas
    must be byte-for-byte what they were -- this change is one table wide."""
    assert MONTHLY_OUTPUT_COLUMNS == [
        "leviathan_slug", "country", "year", "month", "date",
        "production_bags_60kg", "ex_dock_price_usd_cents_per_lb",
        "internal_price_cop_per_125kg", "exports_bags_60kg", "exports_value_usd_m", "source",
    ]
    assert EXPORTS_PORT_TYPE_OUTPUT_COLUMNS == [
        "leviathan_slug", "country", "year", "month", "date", "port", "port_raw",
        "coffee_type", "coffee_type_raw", "exports_bags_60kg", "exports_value_usd", "source",
    ]
    assert "ingest_date" not in MONTHLY_OUTPUT_COLUMNS
    assert "ingest_date" not in EXPORTS_PORT_TYPE_OUTPUT_COLUMNS

    silver = transform_fnc_colombia_bronze_to_silver(_bronze_series())
    assert list(silver.monthly.columns) == MONTHLY_OUTPUT_COLUMNS
    assert list(silver.exports_port_type.columns) == EXPORTS_PORT_TYPE_OUTPUT_COLUMNS
    assert list(silver.area_department.columns) == AREA_OUTPUT_COLUMNS


def test_area_empty_frame_still_declares_the_pit_anchor() -> None:
    """An empty publish must not silently drop the column from the parquet schema."""
    empty = _bronze_series()["area_departamento"].iloc[0:0]
    area = transform_fnc_colombia_area_department(empty)
    assert list(area.columns) == AREA_OUTPUT_COLUMNS
    assert area.empty


# ---------------------------------------------------------------------------
# The checked-in DDL is the pinned truth config_check.check_numbers_schema_pins reads.
# ---------------------------------------------------------------------------
_DDL_DIR = Path(__file__).resolve().parents[2] / "sql" / "athena" / "ddl"


def _ddl(table: str) -> str:
    return (_DDL_DIR / f"{table}.sql").read_text(encoding="utf-8")


def test_area_ddl_declares_the_pit_anchor() -> None:
    """card knowledge_date_col: ingest_date resolves in the checked-in DDL, else every numbers
    lookup dies COLUMN_NOT_FOUND (the silver_nasa_power incident this pin was born from)."""
    text = _ddl("silver_fnc_colombia_area_department")
    assert re.search(r"^\s+ingest_date\s+string\s*$", text, re.MULTILINE)
    # additive: every pre-existing catalog column survives, and the partition keys are untouched.
    for col in ("leviathan_slug", "country", "department", "department_raw", "area_ha", "source"):
        assert re.search(rf"^\s+{col}\s+\w+,?\s*$", text, re.MULTILINE), col
    assert "PARTITIONED BY (commodity string, year int)" in text
    assert "'projection.enabled' = 'true'" in text
    assert "'projection.commodity.values' = 'arabica_coffee'" in text


def test_area_ddl_column_order_matches_the_writer() -> None:
    """The parquet body order and the catalog order agree: ingest_date is LAST in both, so the
    Glue migration is ADD COLUMNS and never a DROP+CREATE reorder."""
    text = _ddl("silver_fnc_colombia_area_department")
    body = text.split("CREATE EXTERNAL TABLE IF NOT EXISTS silver_fnc_colombia_area_department (")[1]
    body = body.split(")")[0]
    cols = [ln.strip().split()[0].rstrip(",") for ln in body.strip().splitlines() if ln.strip()]
    assert cols == ["leviathan_slug", "country", "department", "department_raw",
                    "area_ha", "source", "ingest_date"]
    # the writer emits the same order plus the in-file `year` partition key.
    assert [c for c in AREA_OUTPUT_COLUMNS if c != "year"] == cols


def test_fnc_sibling_ddls_are_untouched_by_this_change() -> None:
    """NO-REGRESSION: only the area table's catalog moves. A stray ingest_date on a sibling would
    mean a Glue migration nobody planned."""
    for table in ("silver_fnc_colombia_monthly", "silver_fnc_colombia_exports_port_type"):
        assert "ingest_date" not in _ddl(table), table


# ---------------------------------------------------------------------------
# The gated catalog migration is an ARTIFACT, not a sentence in a report: the orchestrator
# applies it, and these assertions are what keep it agreeing with the two things it has to
# agree with -- the checked-in DDL and the producer's column list.
# ---------------------------------------------------------------------------
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "sql" / "athena" / "migrations" / "silver"
    / "20260818T000000Z_silver_fnc_colombia_area_department_ingest_date_additive.json"
)


def _migration() -> dict:
    import json

    return json.loads(_MIGRATION_PATH.read_text(encoding="utf-8"))


def test_area_migration_manifest_matches_the_ddl_and_the_writer() -> None:
    m = _migration()
    assert m["table"] == "silver_fnc_colombia_area_department"
    assert m["change_type"] == "additive_update"
    assert m["added_columns"] == [{"name": "ingest_date", "glue_type": "string"}]
    # the ONE column the ALTER adds is the ONE column the writer gained and the DDL declares.
    assert m["apply_sql"] == (
        "ALTER TABLE leviathan_dev.silver_fnc_colombia_area_department "
        "ADD COLUMNS (ingest_date string);"
    )
    assert AREA_OUTPUT_COLUMNS[-1] == m["added_columns"][0]["name"]
    assert re.search(r"^\s+ingest_date\s+string\s*$",
                     _ddl("silver_fnc_colombia_area_department"), re.MULTILINE)


def test_area_migration_is_gated_and_not_yet_applied() -> None:
    """The repo LEADS live Glue by this column on purpose. `applied: true` in the checked-in
    artifact would be a claim about AWS that this test run cannot see -- the orchestrator flips it
    after the apply, never the implementer."""
    m = _migration()
    assert m["gated"] is True
    assert m["applied"] is False
    assert m["database"] == "leviathan_dev"


def test_area_migration_names_the_producer_and_forbids_a_bronze_refetch() -> None:
    """The stamp's TRUTH lives in bronze. Re-running raw->bronze would overwrite 2026-06-02 with
    today's date and silently move every row's knowledge time forward -- a leak, not a refresh."""
    m = _migration()
    assert "fnc_colombia_silver_task.py" in m["producer"]
    assert "do NOT re-run the raw->bronze fetch" in m["derivation"]
    assert "492/492" in m["derivation"]          # measured coverage, not asserted coverage


def test_area_migration_keeps_the_projection_out_of_scope() -> None:
    """INV-3: an additive ADD COLUMNS, never a DROP+CREATE that could reshape a projected table."""
    m = _migration()
    assert "ADD COLUMNS" in m["apply_sql"]
    assert "DROP" not in m["apply_sql"].upper()
    mechanism = m["mechanism"]
    assert "(commodity string, year int)" in mechanism and "UNTOUCHED" in mechanism
    assert "must never become one (INV-3)" in mechanism
    # ...and the DDL the migration lands against still declares exactly that projected shape.
    text = _ddl("silver_fnc_colombia_area_department")
    assert "PARTITIONED BY (commodity string, year int)" in text
    assert "'projection.enabled' = 'true'" in text


def test_area_writer_covers_every_contracted_physical_column() -> None:
    """The F010 contract is generator-owned and is regenerated by the orchestrator AFTER the
    producer re-run, so this asserts the invariant that holds on BOTH sides of that regeneration:
    every contracted column is produced, `year` rides in the body as the partition key, and
    ingest_date is the only other extra (it becomes contracted once F010 is regenerated)."""
    from leviathan.silver.registry import load_registry

    contract = load_registry().table("silver_fnc_colombia_area_department")
    contract_cols = {c["name"] for c in contract["physical_columns"]}
    assert contract_cols <= set(AREA_OUTPUT_COLUMNS)
    extras = set(AREA_OUTPUT_COLUMNS) - contract_cols
    assert "year" in extras
    assert extras <= {"year", "ingest_date"}
    assert "ingest_date" in AREA_OUTPUT_COLUMNS
