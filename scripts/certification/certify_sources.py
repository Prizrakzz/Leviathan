"""Certify existing silver sources for MLflow experiment readiness."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.certification.source_certification import (  # noqa: E402
    SourceContract,
    SourceObservation,
    build_report,
    certify_contract,
    feature_source_coverage,
    load_source_contracts,
    load_waivers,
    report_to_markdown,
)


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def table_ref(database: str, table: str) -> str:
    return f"{quote_ident(database)}.{quote_ident(table)}"


def parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"not an S3 URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def s3_prefix_exists(s3, uri: str) -> bool:
    bucket, prefix = parse_s3_uri(uri)
    response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
    return response.get("KeyCount", 0) > 0


def run_athena(athena, sql: str, database: str, output_location: str) -> tuple[str, list[dict]]:
    response = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": database},
        ResultConfiguration={"OutputLocation": output_location},
    )
    query_id = response["QueryExecutionId"]
    while True:
        execution = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
        state = execution["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in {"FAILED", "CANCELLED"}:
            reason = execution["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena {state}: {reason}; query_id={query_id}")
        time.sleep(2)

    rows: list[dict] = []
    headers: list[str] | None = None
    next_token: str | None = None
    first_page = True
    while True:
        request = {"QueryExecutionId": query_id, "MaxResults": 1000}
        if next_token:
            request["NextToken"] = next_token
        result = athena.get_query_results(**request)
        if headers is None:
            headers = [
                item["Name"]
                for item in result["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]
            ]
        start = 1 if first_page else 0
        first_page = False
        for row in result["ResultSet"]["Rows"][start:]:
            data = row.get("Data", [])
            rows.append(
                {
                    headers[index]: (
                        data[index].get("VarCharValue", "") if index < len(data) else ""
                    )
                    for index in range(len(headers))
                }
            )
        next_token = result.get("NextToken")
        if not next_token:
            return query_id, rows


def first_present(values: tuple[str, ...], available: set[str]) -> str | None:
    for value in values:
        if value in available:
            return value
    return None


def collect_observation(
    contract: SourceContract,
    *,
    glue,
    s3,
    athena,
    database: str,
    athena_output: str,
    skip_athena: bool,
    skip_duplicate_checks: bool,
) -> SourceObservation:
    """Collect live AWS observations for one source contract."""

    s3_exists = None
    if contract.s3_prefix:
        s3_exists = s3_prefix_exists(s3, contract.s3_prefix)

    table_exists = None
    table_location = None
    columns: tuple[str, ...] = ()
    partition_keys: tuple[str, ...] = ()
    try:
        if contract.glue_table:
            table = glue.get_table(DatabaseName=database, Name=contract.glue_table)["Table"]
            table_exists = True
            table_location = table["StorageDescriptor"].get("Location")
            columns = tuple(
                item["Name"] for item in table["StorageDescriptor"].get("Columns", [])
            )
            partition_keys = tuple(item["Name"] for item in table.get("PartitionKeys", []))
    except glue.exceptions.EntityNotFoundException:
        table_exists = False

    metadata_only = contract.athena_mode == "metadata_only"
    if skip_athena or metadata_only or not contract.glue_table or not table_exists:
        notes = []
        if skip_athena:
            notes.append("Athena checks skipped")
        if metadata_only:
            notes.append("Athena checks skipped by source contract athena_mode=metadata_only")
        return SourceObservation(
            s3_prefix_exists=s3_exists,
            glue_table_exists=table_exists,
            table_location=table_location,
            columns=columns,
            partition_keys=partition_keys,
            notes=tuple(notes),
        )

    query_ids: list[str] = []
    row_count: int | None = None
    min_date: str | None = None
    max_date: str | None = None
    duplicate_key_count: int | None = None
    try:
        available = set(columns) | set(partition_keys)
        date_col = first_present(contract.date_columns, available)
        select_parts = ["count(*) AS row_count"]
        if date_col:
            quoted = quote_ident(date_col)
            select_parts.extend([f"min({quoted}) AS min_date", f"max({quoted}) AS max_date"])
        count_sql = (
            "SELECT "
            + ", ".join(select_parts)
            + f" FROM {table_ref(database, contract.glue_table)}"
        )
        qid, rows = run_athena(athena, count_sql, database, athena_output)
        query_ids.append(qid)
        if rows:
            row_count = int(rows[0].get("row_count") or 0)
            min_date = rows[0].get("min_date") or None
            max_date = rows[0].get("max_date") or None

        can_duplicate_check = (
            contract.duplicate_check == "full"
            and not skip_duplicate_checks
            and contract.natural_key
            and set(contract.natural_key).issubset(available)
        )
        if can_duplicate_check:
            key_cols = ", ".join(quote_ident(col) for col in contract.natural_key)
            duplicate_sql = f"""
                SELECT count(*) AS duplicate_key_count
                FROM (
                    SELECT {key_cols}
                    FROM {table_ref(database, contract.glue_table)}
                    GROUP BY {key_cols}
                    HAVING count(*) > 1
                )
            """
            qid, rows = run_athena(athena, duplicate_sql, database, athena_output)
            query_ids.append(qid)
            duplicate_key_count = int(rows[0].get("duplicate_key_count") or 0) if rows else 0
    except Exception as exc:  # noqa: BLE001 - report the source error as data
        return SourceObservation(
            s3_prefix_exists=s3_exists,
            glue_table_exists=table_exists,
            table_location=table_location,
            columns=columns,
            partition_keys=partition_keys,
            row_count=row_count,
            min_date=min_date,
            max_date=max_date,
            duplicate_key_count=duplicate_key_count,
            athena_query_ids=tuple(query_ids),
            athena_error=str(exc),
        )

    notes: list[str] = []
    if skip_duplicate_checks and contract.duplicate_check == "full":
        notes.append("Exact duplicate checks skipped by CLI flag")
    return SourceObservation(
        s3_prefix_exists=s3_exists,
        glue_table_exists=table_exists,
        table_location=table_location,
        columns=columns,
        partition_keys=partition_keys,
        row_count=row_count,
        min_date=min_date,
        max_date=max_date,
        duplicate_key_count=duplicate_key_count,
        athena_query_ids=tuple(query_ids),
        notes=tuple(notes),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contracts",
        type=Path,
        default=Path("configs/datasets/source_contracts.yaml"),
    )
    parser.add_argument(
        "--features",
        type=Path,
        default=Path("configs/features/features.yaml"),
    )
    parser.add_argument("--waivers", type=Path)
    parser.add_argument("--database", default="leviathan_dev")
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument(
        "--athena-output",
        default="s3://leviathan-dev-shahem-001/athena-results/source-certification/",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emit-md", action="store_true")
    parser.add_argument("--skip-athena", action="store_true")
    parser.add_argument("--skip-duplicate-checks", action="store_true")
    parser.add_argument(
        "--source",
        action="append",
        help="Limit to a source_key. Can be supplied multiple times.",
    )
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()

    contracts_text = args.contracts.read_text(encoding="utf-8")
    contracts = load_source_contracts(args.contracts)
    if args.source:
        selected = set(args.source)
        contracts = tuple(contract for contract in contracts if contract.source_key in selected)
        missing = selected - {contract.source_key for contract in contracts}
        if missing:
            raise SystemExit(f"unknown source(s): {sorted(missing)}")

    waivers = load_waivers(args.waivers)
    coverage = feature_source_coverage(args.features, contracts)

    glue = boto3.client("glue", region_name=args.aws_region)
    s3 = boto3.client("s3", region_name=args.aws_region)
    athena = boto3.client("athena", region_name=args.aws_region)

    results = []
    for contract in contracts:
        observation = collect_observation(
            contract,
            glue=glue,
            s3=s3,
            athena=athena,
            database=args.database,
            athena_output=args.athena_output,
            skip_athena=args.skip_athena,
            skip_duplicate_checks=args.skip_duplicate_checks,
        )
        results.append(certify_contract(contract, observation, waivers))

    report = build_report(
        contracts=contracts,
        results=tuple(results),
        contracts_text=contracts_text,
        coverage=coverage,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.to_json() + "\n", encoding="utf-8")
    if args.emit_md:
        args.output.with_suffix(".md").write_text(report_to_markdown(report), encoding="utf-8")

    data = report.to_dict()
    print(json.dumps({
        "output": str(args.output),
        "status_counts": data["status_counts"],
        "missing_contract_sources": coverage["missing_contract_sources"],
    }, indent=2))

    if coverage["missing_contract_sources"]:
        raise SystemExit(2)
    if args.fail_on_blocked and any(result.status == "blocked" for result in results):
        raise SystemExit(3)


if __name__ == "__main__":
    main()
