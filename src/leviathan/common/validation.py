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
