"""PSD target mapping config loading and validation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "ml" / "psd_metric_targets.yaml"
)

MAPPING_STATUSES = {"direct", "proxy", "aggregate_proxy", "unmapped", "deferred"}
MAPPING_CONFIDENCE = {"high", "medium", "low", "none"}
REQUIRED_SOURCE_FIELDS = {
    "source_key",
    "target_source",
    "source_table",
    "s3_prefix",
    "source_slug_field",
    "country_field",
    "year_field",
    "release_date_field",
}


@dataclass(frozen=True)
class PSDTargetMetric:
    target_key: str
    target_family: str
    psd_attribute: str
    unit: str
    value_unit: str
    allowed_as_target: bool


@dataclass(frozen=True)
class PSDContractTargetMapping:
    contract_key: str
    target_status: str
    target_source: str
    psd_source_slug: str | None
    psd_commodity: str | None
    mapping_confidence: str
    allowed_as_target: bool
    allowed_as_feature: bool
    allowed_targets: tuple[str, ...]
    target_origins: tuple[dict[str, str], ...]
    note: str

    @property
    def is_trainable_target(self) -> bool:
        return self.allowed_as_target and bool(self.allowed_targets)


@dataclass(frozen=True)
class PSDMetricTargetConfig:
    metrics: dict[str, PSDTargetMetric]
    contract_mappings: dict[str, PSDContractTargetMapping]
    config_sha: str
    raw: dict[str, Any]


def _config_sha(raw: dict[str, Any]) -> str:
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)


def _as_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in (value or []))


def _validate_source(source: dict[str, Any]) -> None:
    missing = REQUIRED_SOURCE_FIELDS - set(source)
    if missing:
        raise ValueError(f"PSD target config source missing fields: {sorted(missing)}")
    if source.get("target_source") != "psd":
        raise ValueError("PSD target config source.target_source must be 'psd'")


def _load_metrics(raw_metrics: list[dict[str, Any]]) -> dict[str, PSDTargetMetric]:
    metrics: dict[str, PSDTargetMetric] = {}
    for item in raw_metrics:
        target_key = str(item.get("target_key") or "")
        if not target_key:
            raise ValueError("PSD target metric missing target_key")
        if target_key in metrics:
            raise ValueError(f"duplicate PSD target metric: {target_key}")
        psd_attribute = str(item.get("psd_attribute") or "")
        if not psd_attribute:
            raise ValueError(f"{target_key}: missing psd_attribute")
        metrics[target_key] = PSDTargetMetric(
            target_key=target_key,
            target_family=str(item.get("target_family") or ""),
            psd_attribute=psd_attribute,
            unit=str(item.get("unit") or ""),
            value_unit=str(item.get("value_unit") or ""),
            allowed_as_target=_as_bool(item.get("allowed_as_target"), True),
        )
    if not metrics:
        raise ValueError("PSD target config has no target_metrics")
    return metrics


def _load_contracts(
    raw_contracts: list[dict[str, Any]],
    *,
    metrics: dict[str, PSDTargetMetric],
    defaults: dict[str, Any],
) -> dict[str, PSDContractTargetMapping]:
    contracts: dict[str, PSDContractTargetMapping] = {}
    metric_keys = set(metrics)
    for item in raw_contracts:
        contract_key = str(item.get("contract_key") or "")
        if not contract_key:
            raise ValueError("PSD contract mapping missing contract_key")
        if contract_key in contracts:
            raise ValueError(f"duplicate PSD contract mapping: {contract_key}")

        status = str(item.get("target_status") or "")
        if status not in MAPPING_STATUSES:
            raise ValueError(
                f"{contract_key}: target_status must be one of {sorted(MAPPING_STATUSES)}"
            )

        confidence = str(item.get("mapping_confidence") or "")
        if confidence not in MAPPING_CONFIDENCE:
            raise ValueError(
                f"{contract_key}: mapping_confidence must be one of {sorted(MAPPING_CONFIDENCE)}"
            )

        allowed_as_target = _as_bool(
            item.get("allowed_as_target"), bool(defaults.get("allowed_as_target", True))
        )
        allowed_as_feature = _as_bool(
            item.get("allowed_as_feature"), bool(defaults.get("allowed_as_feature", True))
        )
        allowed_targets = _as_tuple(item.get("allowed_targets"))
        target_origins = tuple(dict(origin or {}) for origin in (item.get("target_origins") or []))
        note = str(item.get("note") or "").strip()

        unknown_targets = sorted(set(allowed_targets) - metric_keys)
        if unknown_targets:
            raise ValueError(f"{contract_key}: unknown allowed_targets {unknown_targets}")

        if status == "unmapped":
            if allowed_as_target or allowed_targets or target_origins:
                raise ValueError(
                    f"{contract_key}: unmapped rows cannot be trainable or define origins"
                )
            if confidence != "none":
                raise ValueError(f"{contract_key}: unmapped rows require mapping_confidence=none")
            if not note:
                raise ValueError(f"{contract_key}: unmapped rows require note")
        else:
            if not item.get("psd_source_slug"):
                raise ValueError(f"{contract_key}: mapped rows require psd_source_slug")
            if not item.get("psd_commodity"):
                raise ValueError(f"{contract_key}: mapped rows require psd_commodity")
            if allowed_as_target and not allowed_targets:
                raise ValueError(f"{contract_key}: trainable mappings require allowed_targets")
            if allowed_as_target and not target_origins:
                raise ValueError(f"{contract_key}: trainable mappings require target_origins")

        if status in {"proxy", "aggregate_proxy", "deferred"} and not note:
            raise ValueError(f"{contract_key}: {status} mappings require note")

        contracts[contract_key] = PSDContractTargetMapping(
            contract_key=contract_key,
            target_status=status,
            target_source=str(item.get("target_source") or "psd"),
            psd_source_slug=(
                str(item["psd_source_slug"]) if item.get("psd_source_slug") else None
            ),
            psd_commodity=(str(item["psd_commodity"]) if item.get("psd_commodity") else None),
            mapping_confidence=confidence,
            allowed_as_target=allowed_as_target,
            allowed_as_feature=allowed_as_feature,
            allowed_targets=allowed_targets,
            target_origins=target_origins,
            note=note,
        )

    if not contracts:
        raise ValueError("PSD target config has no contract_mappings")
    return contracts


def load_psd_metric_targets(path: str | Path | None = None) -> PSDMetricTargetConfig:
    """Load PSD metric/contract mappings and return validated config metadata."""
    config_path = Path(path) if path is not None else _CONFIG_PATH
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if int(raw.get("schema_version", 0)) != 1:
        raise ValueError(f"unsupported PSD target config schema_version: {raw.get('schema_version')}")
    _validate_source(raw.get("source") or {})
    metrics = _load_metrics(raw.get("target_metrics") or [])
    contracts = _load_contracts(
        raw.get("contract_mappings") or [],
        metrics=metrics,
        defaults=raw.get("defaults") or {},
    )
    return PSDMetricTargetConfig(
        metrics=metrics,
        contract_mappings=contracts,
        config_sha=_config_sha(raw),
        raw=raw,
    )
