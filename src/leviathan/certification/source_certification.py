"""Certify silver/data sources before they enter MLflow-ready gold datasets."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ACTIVE_CONTRACT_STATUSES = {"core", "certified_driver", "diagnostic_only", "deferred"}
FINAL_STATUSES = {"pass", "warn", "diagnostic_only", "blocked", "deferred"}


class SourceCertificationError(Exception):
    """Raised when source-certification configuration is invalid."""


@dataclass(frozen=True)
class SourceContract:
    """One source contract from ``configs/datasets/source_contracts.yaml``."""

    source_key: str
    title: str
    glue_table: str | None
    s3_prefix: str | None
    status: str
    grain: str
    required_columns: tuple[str, ...] = ()
    natural_key: tuple[str, ...] = ()
    date_columns: tuple[str, ...] = ()
    availability_columns: tuple[str, ...] = ()
    expected_min_rows: int | None = None
    duplicate_check: str = "full"
    athena_mode: str = "full"
    duplicate_skip_reason: str | None = None
    limitation: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_deferred(self) -> bool:
        return self.status == "deferred"

    @property
    def is_diagnostic_only(self) -> bool:
        return self.status == "diagnostic_only"

    @property
    def is_core_like(self) -> bool:
        return self.status in {"core", "certified_driver"}


@dataclass(frozen=True)
class SourceObservation:
    """Observed state for a source, normally collected from S3, Glue, and Athena."""

    s3_prefix_exists: bool | None = None
    glue_table_exists: bool | None = None
    table_location: str | None = None
    columns: tuple[str, ...] = ()
    partition_keys: tuple[str, ...] = ()
    row_count: int | None = None
    min_date: str | None = None
    max_date: str | None = None
    duplicate_key_count: int | None = None
    athena_query_ids: tuple[str, ...] = ()
    athena_error: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def available_columns(self) -> set[str]:
        return set(self.columns) | set(self.partition_keys)


@dataclass(frozen=True)
class Waiver:
    """Explicit waiver for a known limitation or issue."""

    source_key: str
    issue_code: str
    reason: str
    expires_on: str | None = None


@dataclass(frozen=True)
class CertificationResult:
    """Certification result for one source."""

    source_key: str
    title: str
    status: str
    contract_status: str
    glue_table: str | None
    s3_prefix: str | None
    row_count: int | None
    min_date: str | None
    max_date: str | None
    checks: dict[str, str]
    issues: tuple[dict[str, str], ...]
    warnings: tuple[dict[str, str], ...]
    waivers: tuple[dict[str, str], ...]
    observed_columns: tuple[str, ...]
    observed_partition_keys: tuple[str, ...]
    athena_query_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "title": self.title,
            "status": self.status,
            "contract_status": self.contract_status,
            "glue_table": self.glue_table,
            "s3_prefix": self.s3_prefix,
            "row_count": self.row_count,
            "min_date": self.min_date,
            "max_date": self.max_date,
            "checks": self.checks,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
            "waivers": list(self.waivers),
            "observed_columns": list(self.observed_columns),
            "observed_partition_keys": list(self.observed_partition_keys),
            "athena_query_ids": list(self.athena_query_ids),
        }


@dataclass(frozen=True)
class CertificationReport:
    """Full source certification report."""

    generated_at: str
    contracts_sha256: str
    feature_registry_sha256: str | None
    results: tuple[CertificationResult, ...]
    feature_source_coverage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return {
            "generated_at": self.generated_at,
            "contracts_sha256": self.contracts_sha256,
            "feature_registry_sha256": self.feature_registry_sha256,
            "status_counts": counts,
            "feature_source_coverage": self.feature_source_coverage,
            "results": [result.to_dict() for result in self.results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def load_source_contracts(path: str | Path) -> tuple[SourceContract, ...]:
    """Load and validate source contracts."""

    contract_path = Path(path)
    raw = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    sources = raw.get("sources")
    if not isinstance(sources, list):
        raise SourceCertificationError("source contracts must contain a 'sources' list")

    out: list[SourceContract] = []
    seen: set[str] = set()
    for index, item in enumerate(sources):
        if not isinstance(item, dict):
            raise SourceCertificationError(f"sources[{index}] must be a mapping")
        source_key = str(item.get("source_key") or "").strip()
        if not source_key:
            raise SourceCertificationError(f"sources[{index}] missing source_key")
        if source_key in seen:
            raise SourceCertificationError(f"duplicate source_key: {source_key}")
        seen.add(source_key)
        status = str(item.get("status") or "").strip()
        if status not in ACTIVE_CONTRACT_STATUSES:
            raise SourceCertificationError(
                f"{source_key}: status '{status}' must be one of "
                f"{sorted(ACTIVE_CONTRACT_STATUSES)}"
            )
        duplicate_check = str(item.get("duplicate_check") or "full").strip()
        if duplicate_check not in {"full", "skip"}:
            raise SourceCertificationError(
                f"{source_key}: duplicate_check must be 'full' or 'skip'"
            )
        athena_mode = str(item.get("athena_mode") or "full").strip()
        if athena_mode not in {"full", "metadata_only"}:
            raise SourceCertificationError(
                f"{source_key}: athena_mode must be 'full' or 'metadata_only'"
            )
        out.append(
            SourceContract(
                source_key=source_key,
                title=str(item.get("title") or source_key),
                glue_table=item.get("glue_table"),
                s3_prefix=item.get("s3_prefix"),
                status=status,
                grain=str(item.get("grain") or ""),
                required_columns=_tuple(item.get("required_columns")),
                natural_key=_tuple(item.get("natural_key")),
                date_columns=_tuple(item.get("date_columns")),
                availability_columns=_tuple(item.get("availability_columns")),
                expected_min_rows=(
                    None
                    if item.get("expected_min_rows") is None
                    else int(item["expected_min_rows"])
                ),
                duplicate_check=duplicate_check,
                athena_mode=athena_mode,
                duplicate_skip_reason=item.get("duplicate_skip_reason"),
                limitation=item.get("limitation"),
                raw=dict(item),
            )
        )
    return tuple(out)


def load_waivers(path: str | Path | None) -> tuple[Waiver, ...]:
    """Load optional source certification waivers."""

    if path is None:
        return ()
    waiver_path = Path(path)
    if not waiver_path.exists():
        return ()
    raw = yaml.safe_load(waiver_path.read_text(encoding="utf-8")) or {}
    items = raw.get("waivers", [])
    out: list[Waiver] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise SourceCertificationError(f"waivers[{index}] must be a mapping")
        out.append(
            Waiver(
                source_key=str(item["source_key"]),
                issue_code=str(item["issue_code"]),
                reason=str(item["reason"]),
                expires_on=item.get("expires_on"),
            )
        )
    return tuple(out)


def _issue(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _waiver_dict(waiver: Waiver) -> dict[str, str]:
    out = {
        "source_key": waiver.source_key,
        "issue_code": waiver.issue_code,
        "reason": waiver.reason,
    }
    if waiver.expires_on:
        out["expires_on"] = waiver.expires_on
    return out


def certify_contract(
    contract: SourceContract,
    observation: SourceObservation,
    waivers: tuple[Waiver, ...] = (),
) -> CertificationResult:
    """Evaluate one contract against observed source state."""

    checks: dict[str, str] = {}
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    waiver_map = {
        waiver.issue_code: waiver
        for waiver in waivers
        if waiver.source_key == contract.source_key
    }
    applied_waivers: list[dict[str, str]] = []

    def add_issue(code: str, message: str) -> None:
        if code in waiver_map:
            applied_waivers.append(_waiver_dict(waiver_map[code]))
            warnings.append(_issue(code, f"WAIVED: {message}"))
        else:
            issues.append(_issue(code, message))

    if contract.s3_prefix:
        if observation.s3_prefix_exists is True:
            checks["s3_prefix"] = "pass"
        elif observation.s3_prefix_exists is False:
            checks["s3_prefix"] = "fail"
            add_issue("missing_s3_prefix", f"S3 prefix not found: {contract.s3_prefix}")
        else:
            checks["s3_prefix"] = "not_checked"
            warnings.append(_issue("s3_prefix_not_checked", "S3 prefix was not checked"))

    if contract.glue_table:
        if observation.glue_table_exists is True:
            checks["glue_table"] = "pass"
        elif observation.glue_table_exists is False:
            checks["glue_table"] = "fail"
            add_issue("missing_glue_table", f"Glue table not found: {contract.glue_table}")
        else:
            checks["glue_table"] = "not_checked"
            warnings.append(_issue("glue_table_not_checked", "Glue table was not checked"))

    available_columns = observation.available_columns
    missing_required = sorted(set(contract.required_columns) - available_columns)
    if missing_required:
        checks["required_columns"] = "fail"
        add_issue("missing_required_columns", f"Missing columns: {missing_required}")
    else:
        checks["required_columns"] = "pass"

    missing_key = sorted(set(contract.natural_key) - available_columns)
    if missing_key:
        checks["natural_key_columns"] = "fail"
        add_issue("missing_natural_key_columns", f"Missing key columns: {missing_key}")
    elif contract.natural_key:
        checks["natural_key_columns"] = "pass"
    else:
        checks["natural_key_columns"] = "not_declared"
        warnings.append(_issue("natural_key_not_declared", "No natural key declared"))

    date_columns_present = [col for col in contract.date_columns if col in available_columns]
    if contract.date_columns and date_columns_present:
        checks["date_columns"] = "pass"
    elif contract.date_columns:
        checks["date_columns"] = "fail"
        add_issue("missing_date_columns", f"No declared date columns present: {contract.date_columns}")
    else:
        checks["date_columns"] = "not_declared"
        warnings.append(_issue("date_columns_not_declared", "No date columns declared"))

    availability_present = [
        col for col in contract.availability_columns if col in available_columns
    ]
    if contract.availability_columns and availability_present:
        checks["availability_columns"] = "pass"
    elif contract.availability_columns:
        checks["availability_columns"] = "warn"
        warnings.append(
            _issue(
                "missing_availability_columns",
                f"No declared availability columns present: {contract.availability_columns}",
            )
        )
    else:
        checks["availability_columns"] = "not_declared"
        warnings.append(
            _issue("availability_columns_not_declared", "No availability columns declared")
        )

    if observation.athena_error:
        checks["athena"] = "fail"
        add_issue("athena_error", observation.athena_error)
    elif observation.row_count is None:
        checks["row_count"] = "not_checked"
        warnings.append(_issue("row_count_not_checked", "Athena row count was not checked"))
    else:
        checks["row_count"] = "pass"
        if (
            contract.expected_min_rows is not None
            and observation.row_count < contract.expected_min_rows
        ):
            checks["row_count"] = "fail"
            add_issue(
                "row_count_below_minimum",
                f"Row count {observation.row_count} < {contract.expected_min_rows}",
            )

    if contract.duplicate_check == "skip":
        checks["duplicate_keys"] = "skipped"
        warnings.append(
            _issue(
                "duplicate_check_skipped",
                contract.duplicate_skip_reason or "Duplicate check intentionally skipped",
            )
        )
    elif observation.duplicate_key_count is None:
        checks["duplicate_keys"] = "not_checked"
        warnings.append(
            _issue("duplicate_keys_not_checked", "Natural-key duplicate count was not checked")
        )
    elif observation.duplicate_key_count > 0:
        checks["duplicate_keys"] = "fail"
        add_issue(
            "duplicate_keys",
            f"Found {observation.duplicate_key_count} duplicate natural keys",
        )
    else:
        checks["duplicate_keys"] = "pass"

    if contract.limitation:
        warnings.append(_issue("known_limitation", contract.limitation))

    for note in observation.notes:
        warnings.append(_issue("observation_note", note))

    if contract.is_deferred:
        final_status = "deferred"
    elif issues:
        final_status = "blocked"
    elif contract.is_diagnostic_only:
        final_status = "diagnostic_only"
    elif warnings:
        final_status = "warn"
    else:
        final_status = "pass"

    if final_status not in FINAL_STATUSES:
        raise AssertionError(f"invalid final status: {final_status}")

    return CertificationResult(
        source_key=contract.source_key,
        title=contract.title,
        status=final_status,
        contract_status=contract.status,
        glue_table=contract.glue_table,
        s3_prefix=contract.s3_prefix,
        row_count=observation.row_count,
        min_date=observation.min_date,
        max_date=observation.max_date,
        checks=checks,
        issues=tuple(issues),
        warnings=tuple(warnings),
        waivers=tuple(applied_waivers),
        observed_columns=tuple(sorted(observation.columns)),
        observed_partition_keys=tuple(sorted(observation.partition_keys)),
        athena_query_ids=observation.athena_query_ids,
    )


def feature_source_coverage(
    features_path: str | Path,
    contracts: tuple[SourceContract, ...],
) -> dict[str, Any]:
    """Return feature-registry source coverage by certification contracts."""

    path = Path(features_path)
    raw_specs = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(raw_specs, list):
        raise SourceCertificationError("features.yaml must be a list")
    feature_sources = sorted(
        {str(source) for spec in raw_specs for source in spec.get("sources", [])}
    )
    contract_sources = sorted(contract.source_key for contract in contracts)
    feature_set = set(feature_sources)
    contract_set = set(contract_sources)

    families_by_missing_source: dict[str, list[str]] = {}
    for spec in raw_specs:
        family = str(spec.get("family"))
        for source in spec.get("sources", []):
            if source not in contract_set:
                families_by_missing_source.setdefault(str(source), []).append(family)

    text = path.read_text(encoding="utf-8")
    return {
        "feature_registry_path": str(path),
        "feature_registry_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "feature_sources": feature_sources,
        "contract_sources": contract_sources,
        "missing_contract_sources": sorted(feature_set - contract_set),
        "unused_contract_sources": sorted(contract_set - feature_set),
        "families_by_missing_source": families_by_missing_source,
    }


def build_report(
    contracts: tuple[SourceContract, ...],
    results: tuple[CertificationResult, ...],
    contracts_text: str,
    coverage: dict[str, Any],
) -> CertificationReport:
    """Build a deterministic report object."""

    return CertificationReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        contracts_sha256=hashlib.sha256(contracts_text.encode("utf-8")).hexdigest(),
        feature_registry_sha256=coverage.get("feature_registry_sha256"),
        results=results,
        feature_source_coverage=coverage,
    )


def report_to_markdown(report: CertificationReport) -> str:
    """Render a concise human-readable certification report."""

    data = report.to_dict()
    lines = [
        "# Source Certification Report",
        "",
        f"Generated: `{data['generated_at']}`",
        "",
        "## Status Counts",
        "",
        "| Status | Count |",
        "| --- | ---: |",
    ]
    for status, count in sorted(data["status_counts"].items()):
        lines.append(f"| `{status}` | {count} |")

    coverage = data["feature_source_coverage"]
    lines.extend(
        [
            "",
            "## Feature Source Coverage",
            "",
            f"- Feature sources: {len(coverage['feature_sources'])}",
            f"- Missing source contracts: {len(coverage['missing_contract_sources'])}",
            f"- Extra source contracts: {len(coverage['unused_contract_sources'])}",
        ]
    )
    if coverage["missing_contract_sources"]:
        lines.append(
            "- Missing: " + ", ".join(f"`{item}`" for item in coverage["missing_contract_sources"])
        )

    lines.extend(
        [
            "",
            "## Sources",
            "",
            "| Source | Status | Rows | Date Range | Issues | Warnings |",
            "| --- | --- | ---: | --- | ---: | ---: |",
        ]
    )
    for result in data["results"]:
        date_range = ""
        if result["min_date"] or result["max_date"]:
            date_range = f"{result['min_date'] or ''} to {result['max_date'] or ''}"
        lines.append(
            "| "
            f"`{result['source_key']}` | "
            f"`{result['status']}` | "
            f"{'' if result['row_count'] is None else result['row_count']} | "
            f"{date_range} | "
            f"{len(result['issues'])} | "
            f"{len(result['warnings'])} |"
        )

    lines.extend(
        [
            "",
            "## Next",
            "",
            "After this phase is accepted, proceed to Phase 3: preserve and clean the current v2 scratch work before versioning broad legacy gold.",
            "",
        ]
    )
    return "\n".join(lines)
