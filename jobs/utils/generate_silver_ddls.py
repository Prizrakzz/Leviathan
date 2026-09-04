"""DEPRECATED (SILVER-F011): legacy first-parquet Athena DDL generator -- constrained, not the
authority.

The registry-driven generator ``scripts/silver/generate_ddls_from_registry.py`` (rendering via
``leviathan.silver.ddl`` from the SILVER-F010 registry) is now the sole DDL authority. This script
inferred a table's schema from the FIRST parquet object under a prefix and emitted a FLAT
(no ``PARTITIONED BY``) DDL. That first-file inference is exactly the hazard F011 retires: a flat
first-file-derived DDL applied over a PROJECTED or REGISTERED table (e.g. ``silver_nass_crop_progress``
is projected; ``silver_esr``/``silver_wasde`` are registered) would strip the partition projection /
registered partitions and re-open the Jul-2026 S3 LIST-storm surface.

This module is kept only for the handful of legacy gold ML inspection tables the F010 registry does
NOT cover. It is now HARD-CONSTRAINED:

* it REFUSES to emit a DDL for any table the SILVER-F010 registry marks ``projected`` or
  ``registered`` -- it can never flatten one (:func:`_protected_tables`);
* writing requires an explicit ``--write`` (a bare run no longer clobbers ``sql/athena/ddl/``);
* prefer the registry generator for everything it covers.

    python jobs/utils/generate_silver_ddls.py            # dry-run: report what it WOULD do
    python jobs/utils/generate_silver_ddls.py --write    # write the (flat-only) legacy DDLs
    python jobs/utils/generate_silver_ddls.py --write --create   # also CREATE in Athena
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import boto3
import pyarrow.parquet as pq

_BUCKET = "leviathan-dev-shahem-001"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DDL_DIR = _REPO_ROOT / "sql" / "athena" / "ddl"

# table_name -> s3 prefix.  Only sources without a hand-written DDL.
_SOURCES = {
    # commodity-agnostic market / macro / fundamentals
    "silver_cot": "silver/cot/",
    "silver_fred_fx": "silver/fred_fx/",
    "silver_futures_prices": "silver/futures_prices/",
    "silver_pink_sheet": "silver/pink_sheet/",
    # PINK SHEET VINTAGES lane (a): a FLAT sibling, so this legacy generator can legally see it
    # (_protected_tables refuses only projected/registered contracts). The DDL actually checked in
    # was rendered by the F011 registry generator, which is AWS-free and is the authority; the entry
    # is here so a legacy sweep does not silently omit the table -- and so
    # config_check.check_numbers_schema_pins has a DDL to pin the card against when the card lands,
    # instead of printing "no DDL file -- skipped".
    "silver_pink_sheet_vintages": "silver/pink_sheet_vintages/",
    "silver_psd": "silver/psd/",
    "silver_wap_table01": "silver/wap_table01/",
    "silver_wap_table01_revisions": "silver/wap_table01_revisions/",
    "silver_food_cpi": "silver/food_cpi/",
    # climate teleconnections
    "silver_noaa_oni": "silver/weather/source=noaa_oni/",
    "silver_noaa_iod": "silver/weather/source=noaa_iod/",
    "silver_modis_ndvi": "silver/weather/source=modis_ndvi/",
    # South Africa grain
    "silver_sagis_cec": "silver/sagis_cec/",
    "silver_sagis_weekly_deliveries": "silver/sagis_weekly_deliveries/",
    "silver_sagis_weekly_exports": "silver/sagis_weekly_exports/",
    # production / origin
    "silver_conab_coffee": "silver/conab_coffee/",
    "silver_nass_crop_progress": "silver/nass_crop_progress/",
    "silver_nass_citrus": "silver/nass_citrus/",
    "silver_icco_cocoa": "silver/icco_cocoa/",
    # Malaysian palm council
    "silver_mpoc_exports_by_country": "silver/mpoc_exports_by_country/",
    "silver_mpoc_stock_comparison": "silver/mpoc_stock_comparison/",
    "silver_mpoc_trade_stats_monthly": "silver/mpoc_trade_stats_monthly/",
    # UNICA sugar/ethanol (Brazil)
    "silver_unica_biweekly_season_history": "silver/unica_biweekly_season_history/",
    "silver_unica_corn_ethanol": "silver/unica_corn_ethanol/",
    "silver_unica_monthly_ethanol_sales": "silver/unica_monthly_ethanol_sales/",
    # gold ML layer
    "gold_feature_catalog": "gold/feature_catalog/",
    "gold_training_windows": "gold/training_windows/",
}

_TYPE_MAP = {
    "large_string": "string", "string": "string", "bool": "boolean",
    "double": "double", "float": "float",
    "int64": "bigint", "int32": "int", "int16": "smallint", "int8": "tinyint",
    "date32[day]": "date", "null": "string",
}


def _athena_type(arrow_type: str) -> str:
    t = arrow_type.lower()
    if t.startswith("timestamp"):
        return "timestamp"
    return _TYPE_MAP.get(t, "string")


def _first_parquet(s3, prefix: str) -> str | None:
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=_BUCKET, Prefix=prefix):
        for o in page.get("Contents", []):
            if o["Key"].endswith(".parquet") and o["Size"] > 0:
                return o["Key"]
    return None


def _ddl_for(s3, table: str, prefix: str) -> str | None:
    key = _first_parquet(s3, prefix)
    if not key:
        return None
    schema = pq.read_schema(io.BytesIO(s3.get_object(Bucket=_BUCKET, Key=key)["Body"].read()))
    cols = [(n, _athena_type(str(t))) for n, t in zip(schema.names, schema.types)]
    width = max(len(n) for n, _ in cols)
    lines = ",\n".join(f"    {n.ljust(width)} {t}" for n, t in cols)
    return (
        f"-- GENERATED by jobs/utils/generate_silver_ddls.py from the live parquet schema.\n"
        f"-- Flat table over {prefix} (hive partition keys are also in-file).\n"
        f"CREATE EXTERNAL TABLE IF NOT EXISTS {table} (\n{lines}\n)\n"
        f"STORED AS PARQUET\n"
        f"LOCATION 's3://{_BUCKET}/{prefix}'\n"
        f"TBLPROPERTIES ('parquet.compression' = 'SNAPPY');\n"
    )


def _protected_tables() -> dict[str, str]:
    """``{table: partition_mode}`` for every SILVER-F010 table that is NOT flat.

    A first-file-derived flat DDL must never be written for one of these (F011 step 4). AWS-free.
    Returns ``{}`` if the registry cannot be imported, so the legacy path still refuses nothing it
    used to serve -- but the in-list guard below is belt-and-suspenders on top.
    """
    try:
        sys.path.insert(0, str(_REPO_ROOT / "src"))
        from leviathan.silver.registry import load_registry
    except Exception:
        return {}
    reg = load_registry()
    return {
        name: reg.table(name)["partition_mode"]
        for name in reg.names()
        if reg.table(name)["partition_mode"] != "flat"
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="DEPRECATED legacy DDL generator; see module docstring.")
    ap.add_argument("--write", action="store_true", help="actually write the DDL files (else dry-run)")
    ap.add_argument("--create", action="store_true", help="also CREATE the tables in Athena")
    args = ap.parse_args()

    print("DEPRECATED: prefer scripts/silver/generate_ddls_from_registry.py (SILVER-F011).")
    protected = _protected_tables()

    # HARD GUARD (F011 step 4): a projected/registered table can never be flattened here.
    refused = sorted(t for t in _SOURCES if t in protected)
    for t in refused:
        print(f"  REFUSED {t}: registry marks it '{protected[t]}'; use the registry generator "
              f"(never a flat first-file DDL).")
    allowed = [t for t in _SOURCES if t not in protected]

    if not args.write:
        # Dry-run is plan-only -- no S3 read, no prod access.
        for table in allowed:
            print(f"  would write {table}.sql (dry-run; pass --write)")
        print(f"\n{len(allowed)} legacy DDL(s) would be written (dry-run); "
              f"{len(refused)} refused (non-flat).")
        return

    s3 = boto3.client("s3", region_name="us-east-1")
    written = []
    for table in allowed:
        ddl = _ddl_for(s3, table, _SOURCES[table])
        if ddl is None:
            print(f"  {table}: no parquet at {_SOURCES[table]} — skipped")
            continue
        (_DDL_DIR / f"{table}.sql").write_text(ddl, encoding="utf-8")
        print(f"  wrote {table}.sql")
        written.append((table, ddl))

    if args.create:
        sys.path.insert(0, str(_REPO_ROOT))
        from jobs.run_athena_ddl import _DATABASE, _run_query
        athena = boto3.client("athena", region_name="us-east-1")
        for table, ddl in written:
            ok, msg = _run_query(athena, ddl, database=_DATABASE)
            print(f"  CREATE {table}: {'OK' if ok else msg}")

    print(f"\n{len(written)} legacy DDL(s) written; {len(refused)} refused (non-flat).")


if __name__ == "__main__":
    main()
