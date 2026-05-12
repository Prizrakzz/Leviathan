"""Shared Athena helpers for pipeline validation scripts.

All SQL queries execute inside AWS (Athena), co-located with S3.
Only result rows (KBs) are returned to the caller — no data is downloaded.

Usage:
    from athena_utils import ensure_catalog, run_query, ATHENA_DB

    athena = ensure_catalog(commodity="cocoa", countries=[...], regions=[...])
    rows = run_query(athena, "SELECT COUNT(*) AS n FROM leviathan_dev.silver_weather")
    print(rows[0]["n"])
"""
from __future__ import annotations

import os
import time

import boto3

# ---------------------------------------------------------------------------
# Constants — can be overridden via env vars
# ---------------------------------------------------------------------------

ATHENA_DB = "leviathan_dev"
BUCKET = os.environ.get("LEVIATHAN_BUCKET", "leviathan-dev-shahem-001")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
ATHENA_RESULTS = f"s3://{BUCKET}/athena-results/"

COMMODITY = "cocoa"
WEATHER_START_YEAR = 1981
WEATHER_END_YEAR = 2024
FAOSTAT_START_YEAR = 1961
FAOSTAT_END_YEAR = 2023


# ---------------------------------------------------------------------------
# Core query runner
# ---------------------------------------------------------------------------

def run_query(client, sql: str, database: str | None = ATHENA_DB) -> list[dict]:
    """Submit an Athena query, poll until done, return all rows as list[dict].

    The query runs entirely inside AWS — only the result set is returned over
    the wire. For aggregation queries this is KBs, not MBs.
    """
    kwargs: dict = {
        "QueryString": sql,
        "ResultConfiguration": {"OutputLocation": ATHENA_RESULTS},
    }
    if database:
        kwargs["QueryExecutionContext"] = {"Database": database}

    qid = client.start_query_execution(**kwargs)["QueryExecutionId"]

    while True:
        resp = client.get_query_execution(QueryExecutionId=qid)
        state = resp["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = resp["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(
                f"Athena {state}: {reason}\n"
                f"QueryExecutionId: {qid}\n"
                f"SQL (first 500 chars): {sql[:500]}"
            )
        time.sleep(2)

    rows: list[dict] = []
    headers: list[str] | None = None
    first_page = True
    next_token: str | None = None

    while True:
        req: dict = {"QueryExecutionId": qid, "MaxResults": 1000}
        if next_token:
            req["NextToken"] = next_token

        resp = client.get_query_results(**req)

        # Column names come from ResultSetMetadata, present on every page.
        if headers is None:
            headers = [
                col["Name"]
                for col in resp["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]
            ]

        page_rows = resp["ResultSet"]["Rows"]
        # First page includes a header row at index 0 — skip it.
        start = 1 if first_page else 0
        first_page = False

        for row in page_rows[start:]:
            rows.append(
                {headers[i]: col.get("VarCharValue", "") for i, col in enumerate(row["Data"])}
            )

        next_token = resp.get("NextToken")
        if not next_token:
            break

    return rows


# ---------------------------------------------------------------------------
# Catalog bootstrap
# ---------------------------------------------------------------------------

def ensure_catalog(
    commodity: str,
    countries: list[str],
    regions: list[str],
) -> boto3.client:
    """Create the Glue database and external tables if they don't exist.

    Tables use partition projection so Athena always resolves S3 paths from
    metadata — no crawler and no MSCK REPAIR TABLE ever needed.

    Returns a configured Athena boto3 client ready for validation queries.
    """
    glue = boto3.client("glue", region_name=AWS_REGION)
    athena = boto3.client("athena", region_name=AWS_REGION)

    # ---- Glue database ----
    try:
        glue.get_database(Name=ATHENA_DB)
    except glue.exceptions.EntityNotFoundException:
        glue.create_database(
            DatabaseInput={
                "Name": ATHENA_DB,
                "Description": "Leviathan data lake — managed by athena_utils",
            }
        )
        print(f"  [catalog] Created Glue database: {ATHENA_DB}")

    # ---- silver_weather ----
    country_enum = ",".join(countries)
    region_enum = ",".join(regions)
    weather_base = f"s3://{BUCKET}/silver/weather/source=nasa_power/commodity={commodity}/"
    weather_template = (
        weather_base
        + "country=${country}/region=${region}/year=${year}/month=${month}"
    )

    run_query(
        athena,
        f"""
CREATE EXTERNAL TABLE IF NOT EXISTS {ATHENA_DB}.silver_weather (
    date                       DATE,
    day                        INT,
    commodity                  STRING,
    source                     STRING,
    ingest_date                STRING,
    source_file_name           STRING,
    temperature_2m_mean_c      DOUBLE,
    temperature_2m_max_c       DOUBLE,
    temperature_2m_min_c       DOUBLE,
    precipitation_mm           DOUBLE,
    relative_humidity_2m_pct   DOUBLE,
    wind_speed_2m_m_s          DOUBLE,
    solar_radiation_mj_m2_day  DOUBLE
)
PARTITIONED BY (country STRING, region STRING, year INT, month INT)
STORED AS PARQUET
LOCATION '{weather_base}'
TBLPROPERTIES (
    'projection.enabled'        = 'true',
    'projection.country.type'   = 'enum',
    'projection.country.values' = '{country_enum}',
    'projection.region.type'    = 'enum',
    'projection.region.values'  = '{region_enum}',
    'projection.year.type'      = 'integer',
    'projection.year.range'     = '{WEATHER_START_YEAR},{WEATHER_END_YEAR}',
    'projection.month.type'     = 'integer',
    'projection.month.range'    = '1,12',
    'projection.month.digits'   = '2',
    'storage.location.template' = '{weather_template}'
)
""",
        database=None,
    )

    # ---- silver_production ----
    prod_base = f"s3://{BUCKET}/silver/production/commodity={commodity}/"
    prod_template = prod_base + "year=${year}"

    run_query(
        athena,
        f"""
CREATE EXTERNAL TABLE IF NOT EXISTS {ATHENA_DB}.silver_production (
    country          STRING,
    country_key      STRING,
    commodity        STRING,
    metric           STRING,
    unit             STRING,
    value            DOUBLE,
    flag             STRING,
    is_official      BOOLEAN,
    note             STRING,
    source           STRING,
    dataset          STRING,
    ingest_date      STRING,
    source_file_name STRING
)
PARTITIONED BY (year INT)
STORED AS PARQUET
LOCATION '{prod_base}'
TBLPROPERTIES (
    'projection.enabled'        = 'true',
    'projection.year.type'      = 'integer',
    'projection.year.range'     = '{FAOSTAT_START_YEAR},{FAOSTAT_END_YEAR}',
    'storage.location.template' = '{prod_template}'
)
""",
        database=None,
    )

    print(
        f"  [catalog] Tables ready: {ATHENA_DB}.silver_weather,"
        f" {ATHENA_DB}.silver_production"
    )
    return athena
