"""Schema validation for raw payloads.

Schemas are stored as YAML files inside the ``leviathan.schemas`` package so they
are included in the installed wheel and available inside AWS Glue at runtime.

Usage
-----
    from leviathan.common.validation import load_schema, validate_raw_json, SchemaValidationError

    schema = load_schema("nasa_power")
    try:
        validate_raw_json(payload, schema, context=raw_key)
    except SchemaValidationError as exc:
        write_dead_letter(...)
"""
from __future__ import annotations

import importlib.resources as pkg_resources
import sys
from typing import Any

if sys.version_info >= (3, 10):
    from typing import TypeAlias
else:
    from typing_extensions import TypeAlias

import pandas as pd
import yaml

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

SchemaDict: TypeAlias = dict[str, Any]


class SchemaValidationError(Exception):
    """Raised when a raw payload does not conform to the expected schema."""


def load_schema(source: str) -> SchemaDict:
    """Load the YAML schema definition for *source* from the leviathan.schemas package.

    Args:
        source: Source identifier, e.g. ``"nasa_power"`` or ``"faostat_qcl"``.

    Returns:
        Parsed schema dictionary.

    Raises:
        SchemaValidationError: If no schema file exists for the given source.
    """
    schema_file = f"{source}.yaml"
    try:
        text = (
            pkg_resources.files("leviathan.schemas")
            .joinpath(schema_file)
            .read_text(encoding="utf-8")
        )
        return yaml.safe_load(text)
    except (FileNotFoundError, TypeError) as exc:
        raise SchemaValidationError(
            f"No schema defined for source '{source}' — expected file: {schema_file}"
        ) from exc


def validate_raw_json(
    payload: SchemaDict,
    schema: SchemaDict,
    context: str = "",
) -> None:
    """Validate a NASA POWER-style JSON payload against *schema*.

    Checks that the required_path exists and all required_parameters are present.

    Raises:
        SchemaValidationError: On first structural violation found.
    """
    prefix = f"[{context}] " if context else ""

    required_path: str = schema.get("required_path", "")
    if required_path:
        node: object = payload
        for part in required_path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise SchemaValidationError(
                    f"{prefix}Missing required path '{required_path}' in payload"
                )
            node = node[part]

        # node is now the parameter block (e.g. properties.parameter)
        actual_params = set(node.keys()) if isinstance(node, dict) else set()
        for param in schema.get("required_parameters", []):
            if param not in actual_params:
                raise SchemaValidationError(
                    f"{prefix}Missing required parameter '{param}' under '{required_path}'. "
                    f"Found: {sorted(actual_params)}"
                )


def validate_raw_df(
    df: pd.DataFrame,
    schema: SchemaDict,
    context: str = "",
) -> None:
    """Validate a FAOSTAT-style DataFrame against *schema*.

    Checks that all required_columns are present (case-insensitive).

    Raises:
        SchemaValidationError: If any required column is missing.
    """
    prefix = f"[{context}] " if context else ""
    actual_cols_lower = {c.lower() for c in df.columns}

    missing = [
        col for col in schema.get("required_columns", [])
        if col.lower() not in actual_cols_lower
    ]
    if missing:
        raise SchemaValidationError(
            f"{prefix}Missing required columns: {missing}. "
            f"Found columns: {sorted(df.columns.tolist())}"
        )


def validate_bronze_df(
    df: pd.DataFrame,
    schema: SchemaDict,
    source: str = "",
    context: str = "",
) -> dict:
    """Validate a bronze DataFrame against *schema*.

    Runs four checks in order:

    1. **Row count** — raises if ``len(df) == 0``.
    2. **Required columns** — raises if any column listed in
       ``schema["required_columns"]`` is absent (case-insensitive match).
    3. **Schema drift** — logs WARNING for unexpected new columns; raises for
       missing expected columns (already covered in step 2).
    4. **Year range** — logs WARNING for rows whose year falls outside
       ``[schema["min_year"], current_year + 1]``.
    5. **Null counts** — logs INFO for every column that has any null values
       (informational only; does not fail).

    Args:
        df:      Bronze DataFrame to validate.
        schema:  Schema dict loaded via :func:`load_schema`.
        source:  Source identifier used in log messages.
        context: Optional human-readable label for error messages.

    Returns:
        Metadata dict with keys ``null_counts``, ``new_columns``, ``year_range``.

    Raises:
        SchemaValidationError: On hard structural failures (empty df, missing cols).
    """
    import datetime  # noqa: PLC0415 — stdlib, lazy to keep module startup fast

    prefix = f"[{context}] " if context else ""

    # 1. Row count
    if len(df) == 0:
        raise SchemaValidationError(f"{prefix}Bronze DataFrame is empty (0 rows).")

    # 2. Required columns (case-insensitive)
    required = schema.get("required_columns", [])
    actual_lower = {c.lower(): c for c in df.columns}
    missing = [col for col in required if col.lower() not in actual_lower]
    if missing:
        raise SchemaValidationError(
            f"{prefix}Missing required bronze columns: {missing}. "
            f"Found: {sorted(df.columns.tolist())}"
        )

    # 3. Schema drift — new columns that are not in the schema
    required_lower = {c.lower() for c in required}
    new_cols = [c for c in df.columns if c.lower() not in required_lower]
    if new_cols:
        logger.warning(
            "%sBronze schema drift for source '%s': unexpected new columns %s",
            prefix, source, new_cols,
        )

    # 4. Year range check
    year_range: dict = {"min": None, "max": None}
    year_col = schema.get("year_col")
    min_year = schema.get("min_year", 1960)
    current_year = datetime.date.today().year
    if year_col and year_col in df.columns:
        years = pd.to_numeric(df[year_col], errors="coerce").dropna()
        if not years.empty:
            year_range["min"] = int(years.min())
            year_range["max"] = int(years.max())
            out_of_range = int(((years < min_year) | (years > current_year + 1)).sum())
            if out_of_range:
                logger.warning(
                    "%s%d rows have year outside expected range [%d, %d] for source '%s'",
                    prefix, out_of_range, min_year, current_year + 1, source,
                )

    # 5. Null counts (informational)
    null_counts = {
        col: int(df[col].isna().sum())
        for col in df.columns
        if df[col].isna().any()
    }
    for col, count in null_counts.items():
        logger.info(
            "%sNull count for '%s': %d / %d (%.1f%%)",
            prefix, col, count, len(df), 100.0 * count / len(df),
        )

    return {
        "null_counts": null_counts,
        "new_columns": new_cols,
        "year_range": year_range,
    }
