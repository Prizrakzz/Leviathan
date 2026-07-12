"""Explicit INV-2 writer schemas for the weather trio (SILVER-F046, Milestone R2).

INV-2 doctrine: every silver parquet writer pins an explicit ``pyarrow`` schema at the write step so
pandas/pyarrow dtype inference can never differ across write eras (the ``string`` vs ``large_string``
and int-width drift the R0 baseline flagged, C-ADD-7). Today the weather producers write via
``df.to_parquet(...)`` with inference; this module is the single authority for the exact physical
parquet schema each family writes, so the WIDE nasa_power table and the LONG chirps/cpc_soil tables
can never silently drift their measurement/text types again.

WHY A DEDICATED SCHEMA (not just the registry ``physical_columns``): the registry contract lists only
the DECLARED Glue non-partition columns (11 for nasa_power, 6 for chirps/cpc_soil). The physical
parquet the producers actually write carries the partition-redundant id columns too
(``country``/``region``/``year``/``month`` -- and, for the LONG tables, ``commodity``) because the
downstream gold_weather_z ``_to_long`` seam and the feature extractor melt read those id columns out
of the FRAME, not the S3 path. So the pinned writer schema is the FULL physical parquet schema
(15 cols WIDE, 11 cols LONG), a strict superset of the registry-declared columns. This module
asserts that superset relationship against the loaded registry so the two authorities cannot diverge.

The R0 baseline (``reports/silver_readiness/20260712_p65impl/tables/silver_nasa_power.json``
``physical_sample.arrow_columns``) is the ground truth these schemas mirror EXACTLY -- same names,
same order, same arrow types -- so a rebuild is byte-shape-identical to the live layout.

Pure + AWS-free + ASCII only. ``pyarrow`` is the only dependency.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import pyarrow as pa

# ---------------------------------------------------------------------------
# The pinned physical parquet schemas (INV-2). Order + type EXACT to the R0 baseline.
# ---------------------------------------------------------------------------
# WIDE nasa_power: one row per (commodity[path], country, region, year, month, date); commodity lives
# only in the S3 path (not the parquet), matching the live 15-column layout.
NASA_POWER_WIDE_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("year", pa.int64()),
        ("month", pa.int64()),
        ("day", pa.int64()),
        ("country", pa.string()),
        ("region", pa.string()),
        ("source", pa.string()),
        ("ingest_date", pa.string()),
        ("source_file_name", pa.string()),
        ("temperature_2m_mean_c", pa.float64()),
        ("temperature_2m_max_c", pa.float64()),
        ("temperature_2m_min_c", pa.float64()),
        ("precipitation_mm", pa.float64()),
        ("relative_humidity_2m_pct", pa.float64()),
        ("wind_speed_2m_m_s", pa.float64()),
    ]
)

# LONG chirps / cpc_soil: one row per (commodity, country, region, year, month, date, variable).
# commodity is carried IN the parquet here (the R0 baseline 11-column layout).
_WEATHER_LONG_FIELDS = [
    ("date", pa.date32()),
    ("year", pa.int64()),
    ("month", pa.int64()),
    ("day", pa.int64()),
    ("country", pa.string()),
    ("region", pa.string()),
    ("commodity", pa.string()),
    ("source", pa.string()),
    ("ingest_date", pa.string()),
    ("variable", pa.string()),
    ("value", pa.float64()),
]
CHIRPS_LONG_SCHEMA = pa.schema(_WEATHER_LONG_FIELDS)
CPC_SOIL_LONG_SCHEMA = pa.schema(_WEATHER_LONG_FIELDS)

# The compacted year-grain LONG layout (SILVER-F047). Identical columns to the projected LONG schema:
# compaction merges the 12 monthly files WITHIN a (commodity, year) into one object; country/region/
# month stay physical columns and the ``year=`` path segment survives (the feature-extractor
# _year_from_path dependency). No columns are added or dropped, so gold/extractor reads are unchanged.
CHIRPS_COMPACTED_SCHEMA = CHIRPS_LONG_SCHEMA
CPC_SOIL_COMPACTED_SCHEMA = CPC_SOIL_LONG_SCHEMA
# nasa_power WIDE compaction keeps its 15-column wide schema (already declared above).
NASA_POWER_COMPACTED_SCHEMA = NASA_POWER_WIDE_SCHEMA

SCHEMA_BY_TABLE = {
    "silver_nasa_power": NASA_POWER_WIDE_SCHEMA,
    "silver_chirps": CHIRPS_LONG_SCHEMA,
    "silver_cpc_soil": CPC_SOIL_LONG_SCHEMA,
}


def schema_for(table_name: str) -> pa.Schema:
    """Return the pinned physical parquet schema for one weather table (INV-2)."""
    try:
        return SCHEMA_BY_TABLE[table_name]
    except KeyError as exc:  # noqa: BLE001
        raise KeyError(
            f"no pinned weather writer schema for {table_name!r} "
            f"(known: {sorted(SCHEMA_BY_TABLE)})"
        ) from exc


def enforce_arrow_schema(df: pd.DataFrame, schema: pa.Schema) -> pa.Table:
    """Cast a producer DataFrame to the pinned ``schema`` and return a ``pyarrow.Table`` (INV-2).

    The DataFrame MUST carry every column in ``schema`` (extra columns are dropped, so the WIDE
    producer can hand its full id+measure frame and the partition-only ``commodity`` column is
    stripped for nasa_power). Missing columns raise -- a producer that lost a measurement column
    fails closed rather than writing an inference-typed object. ``date`` is coerced to ``date32``,
    ints to ``int64``, measures to ``float64``, text to ``string`` -- deterministically, every era.
    """
    cols = [f.name for f in schema]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"cannot enforce weather writer schema: DataFrame is missing column(s) {missing} "
            f"(has {sorted(df.columns)})"
        )
    projected = df.loc[:, cols].copy()
    # Coerce date/text explicitly so pandas object columns land as date32/string, not inference.
    for field in schema:
        name = field.name
        if pa.types.is_date(field.type):
            projected[name] = pd.to_datetime(projected[name], errors="coerce").dt.date
        elif pa.types.is_integer(field.type):
            projected[name] = pd.to_numeric(projected[name], errors="coerce").astype("Int64")
        elif pa.types.is_floating(field.type):
            projected[name] = pd.to_numeric(projected[name], errors="coerce").astype("float64")
        elif pa.types.is_string(field.type):
            projected[name] = projected[name].astype("string")
    return pa.Table.from_pandas(projected, schema=schema, preserve_index=False)


def to_parquet_bytes(df: pd.DataFrame, schema: pa.Schema) -> bytes:
    """Serialise ``df`` to snappy parquet bytes under the pinned ``schema`` (the write-through path
    every weather producer/compactor uses instead of ``df.to_parquet`` inference)."""
    import io

    import pyarrow.parquet as pq

    table = enforce_arrow_schema(df, schema)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue()


def assert_covers_registry(table_name: str, contract: dict) -> list[str]:
    """Return violations if the pinned schema does not COVER every registry-declared physical column
    (name + INV-2 target type). The pinned schema may be a strict superset (the partition-redundant
    id columns); it may never DROP a declared column or change its base type. Empty == coherent."""
    schema = schema_for(table_name)
    by_name = {f.name: f.type for f in schema}
    out: list[str] = []
    for col in contract.get("physical_columns", []):
        name = col["name"]
        if name not in by_name:
            out.append(f"{table_name}: pinned schema is missing declared column {name!r}")
            continue
        want = (col.get("target_arrow_type") or "").lower()
        got = by_name[name]
        if not _base_compatible(want, got):
            out.append(
                f"{table_name}.{name}: pinned type {got} incompatible with registry target {want!r}"
            )
    return out


def _base_compatible(target: str, arrow_type: pa.DataType) -> bool:
    if target.startswith("int"):
        return pa.types.is_integer(arrow_type)
    if target.startswith("float") or target.startswith("double") or target.startswith("decimal"):
        return pa.types.is_floating(arrow_type)
    if target.startswith("string") or target.startswith("large_string") or target.startswith("utf8"):
        return pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type)
    if target.startswith("bool"):
        return pa.types.is_boolean(arrow_type)
    if target.startswith("date"):
        return pa.types.is_date(arrow_type)
    if target.startswith("timestamp"):
        return pa.types.is_timestamp(arrow_type)
    return True  # opaque/unknown target -> do not block


# ---------------------------------------------------------------------------
# NASA missing-data sentinels (INV-5 / F021: never let a -999 fill land as a real measure).
# ---------------------------------------------------------------------------
# NASA POWER encodes missing daily values as -999 (and the netCDF fill -999.0 family). A sentinel in
# a measurement column becomes a null (dropped from long, NaN in wide) -- it is NEVER a real reading.
NASA_MISSING_SENTINELS: tuple[float, ...] = (-999.0, -9999.0, -99999.0)


def scrub_sentinels(series: pd.Series, sentinels: tuple[float, ...] = NASA_MISSING_SENTINELS) -> pd.Series:
    """Replace NASA missing-data sentinels with NaN in a numeric measurement series (F021)."""
    numeric = pd.to_numeric(series, errors="coerce")
    mask = pd.Series(False, index=numeric.index)
    for s in sentinels:
        mask = mask | (numeric == s)
    return numeric.mask(mask)


# Accepted raw NASA parameter tokens -> canonical wide measurement columns (F021: an unknown raw
# parameter must fail closed, never be silently melted into a mystery ``variable``).
ACCEPTED_NASA_PARAMS = {
    "t2m": "temperature_2m_mean_c",
    "t2m_max": "temperature_2m_max_c",
    "t2m_min": "temperature_2m_min_c",
    "prectotcorr": "precipitation_mm",
    "rh2m": "relative_humidity_2m_pct",
    "ws2m": "wind_speed_2m_m_s",
}
# solar radiation (allsky_sfc_sw_dwn) is DELIBERATELY excluded from the canonical wide contract: it is
# not a declared silver_nasa_power column and adding it is a separate additive-schema decision (F021).
NASA_EXCLUDED_PARAMS = {"allsky_sfc_sw_dwn": "solar_radiation_mj_m2_day"}

# The canonical ordered WIDE measurement columns (the 6 declared silver_nasa_power measures).
NASA_WIDE_MEASURE_COLS = list(ACCEPTED_NASA_PARAMS.values())
