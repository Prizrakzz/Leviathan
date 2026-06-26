"""Validate checked-in Athena DDLs against the live Glue catalog.

This is intentionally metadata-only: it does not scan S3 data and it does not
run Athena queries.  It answers the catalog hygiene questions that tend to rot:

* Does every checked-in DDL point to a live Glue table?
* Does every live Glue table have a checked-in DDL?
* Do locations, columns, and partition keys still match?

Usage:
    python jobs/utils/validate_athena_ddl_drift.py
    python jobs/utils/validate_athena_ddl_drift.py --database leviathan_dev
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import boto3


_DDL_DIR = Path(__file__).resolve().parents[2] / "sql" / "athena" / "ddl"
_CREATE_RE = re.compile(
    r"CREATE\s+EXTERNAL\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:(?P<db>\w+)\.)?(?P<table>\w+)",
    re.IGNORECASE,
)
_LOCATION_RE = re.compile(r"LOCATION\s+'(?P<location>[^']+)'", re.IGNORECASE)
_PARTITION_RE = re.compile(r"PARTITIONED\s+BY\s*\((?P<body>.*?)\)", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class DdlTable:
    path: Path
    name: str
    location: str | None
    columns: tuple[tuple[str, str], ...]
    partitions: tuple[tuple[str, str], ...]


def _strip_comments(sql: str) -> str:
    lines: list[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line.split("--", 1)[0])
    return "\n".join(lines)


def _find_matching_paren(sql: str, open_idx: int) -> int:
    depth = 0
    in_quote = False
    for idx in range(open_idx, len(sql)):
        ch = sql[idx]
        if ch == "'":
            in_quote = not in_quote
        if in_quote:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return idx
    raise ValueError("unbalanced CREATE TABLE column list")


def _split_top_level_commas(body: str) -> list[str]:
    parts: list[str] = []
    start = 0
    angle_depth = 0
    paren_depth = 0
    for idx, ch in enumerate(body):
        if ch == "<":
            angle_depth += 1
        elif ch == ">":
            angle_depth = max(0, angle_depth - 1)
        elif ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "," and angle_depth == 0 and paren_depth == 0:
            parts.append(body[start:idx].strip())
            start = idx + 1
    tail = body[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_columns(body: str) -> tuple[tuple[str, str], ...]:
    cols: list[tuple[str, str]] = []
    for item in _split_top_level_commas(body):
        tokens = item.split(None, 1)
        if len(tokens) != 2:
            continue
        name = tokens[0].strip("`")
        typ = _normal_type(tokens[1])
        cols.append((name, typ))
    return tuple(cols)


def _normal_type(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().rstrip(",").lower())


def _normal_location(value: str | None) -> str | None:
    if value is None:
        return None
    return value.rstrip("/")


def _parse_ddl(path: Path) -> DdlTable:
    raw = path.read_text(encoding="utf-8")
    sql = _strip_comments(raw)
    create = _CREATE_RE.search(sql)
    if create is None:
        raise ValueError(f"{path}: CREATE EXTERNAL TABLE not found")

    open_idx = sql.find("(", create.end())
    close_idx = _find_matching_paren(sql, open_idx)
    columns = _parse_columns(sql[open_idx + 1 : close_idx])

    part_match = _PARTITION_RE.search(sql, close_idx)
    partitions = _parse_columns(part_match.group("body")) if part_match else tuple()

    loc_match = _LOCATION_RE.search(sql, close_idx)
    return DdlTable(
        path=path,
        name=create.group("table"),
        location=_normal_location(loc_match.group("location") if loc_match else None),
        columns=columns,
        partitions=partitions,
    )


def _glue_tables(database: str, region: str) -> dict[str, dict]:
    client = boto3.client("glue", region_name=region)
    tables: dict[str, dict] = {}
    token: str | None = None
    while True:
        kwargs = {"DatabaseName": database}
        if token:
            kwargs["NextToken"] = token
        resp = client.get_tables(**kwargs)
        for table in resp["TableList"]:
            tables[table["Name"]] = table
        token = resp.get("NextToken")
        if not token:
            return tables


def _glue_columns(table: dict) -> tuple[tuple[str, str], ...]:
    return tuple(
        (col["Name"], _normal_type(col["Type"]))
        for col in table["StorageDescriptor"].get("Columns", [])
    )


def _glue_partitions(table: dict) -> tuple[tuple[str, str], ...]:
    return tuple((part["Name"], _normal_type(part["Type"])) for part in table.get("PartitionKeys", []))


def validate(
    database: str,
    region: str,
    ddl_dir: Path = _DDL_DIR,
    *,
    skip_deep_compare_prefixes: tuple[str, ...] = ("graphrag_",),
) -> list[str]:
    ddls = [_parse_ddl(path) for path in sorted(ddl_dir.glob("*.sql"))]
    ddl_by_name = {ddl.name: ddl for ddl in ddls}
    glue_by_name = _glue_tables(database, region)

    errors: list[str] = []
    for name in sorted(set(ddl_by_name) - set(glue_by_name)):
        errors.append(f"DDL without Glue table: {name} ({ddl_by_name[name].path})")
    for name in sorted(set(glue_by_name) - set(ddl_by_name)):
        errors.append(f"Glue table without checked-in DDL: {name}")

    for name in sorted(set(ddl_by_name) & set(glue_by_name)):
        if any(name.startswith(prefix) for prefix in skip_deep_compare_prefixes):
            continue
        ddl = ddl_by_name[name]
        glue = glue_by_name[name]
        glue_location = _normal_location(glue["StorageDescriptor"].get("Location"))
        if ddl.location != glue_location:
            errors.append(f"{name}: location mismatch DDL={ddl.location!r} Glue={glue_location!r}")
        glue_cols = _glue_columns(glue)
        if ddl.columns != glue_cols:
            errors.append(f"{name}: column schema mismatch")
        glue_parts = _glue_partitions(glue)
        if ddl.partitions != glue_parts:
            errors.append(f"{name}: partition schema mismatch")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="leviathan_dev")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--ddl-dir", type=Path, default=_DDL_DIR)
    parser.add_argument(
        "--include-graphrag",
        action="store_true",
        help="also deep-compare graphrag_* table schemas and locations",
    )
    args = parser.parse_args()

    skip_prefixes = tuple() if args.include_graphrag else ("graphrag_",)
    errors = validate(
        args.database,
        args.region,
        args.ddl_dir,
        skip_deep_compare_prefixes=skip_prefixes,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    suffix = "" if args.include_graphrag else " (deep compare skipped for graphrag_*)"
    print(f"OK: {args.ddl_dir} matches Glue database {args.database}{suffix}.")


if __name__ == "__main__":
    main()
