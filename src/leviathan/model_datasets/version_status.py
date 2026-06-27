"""Status registry for immutable model-ready dataset versions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "ml" / "model_dataset_versions.yaml"
)

DEFAULT_STATUS = "unknown"
ACTIVE_STATUS = "active"
NON_DEFAULT_STATUSES = {"legacy", "deprecated", "archived_reference", "blocked", "unknown"}


@dataclass(frozen=True)
class ModelDatasetVersionStatus:
    """Version-level governance metadata for a model-ready dataset."""

    dataset_version: str
    status: str
    default_discovery_allowed: bool
    target_source: str = ""
    dataset_keys: tuple[str, ...] = ()
    source_gold_dataset_version: str = ""
    scope: str = ""
    commodity_count: int | None = None
    matrix_count: int | None = None
    target_count: int | None = None
    legacy_reason: str = ""
    replaced_by: str = ""
    default_priority: int = 0
    notes: str = ""

    @property
    def is_active(self) -> bool:
        return self.status == ACTIVE_STATUS

    @property
    def is_legacy_like(self) -> bool:
        return self.status in NON_DEFAULT_STATUSES

    def as_tags(self) -> dict[str, str]:
        tags = {
            "model_dataset_status": self.status,
            "model_dataset_default_discovery_allowed": str(
                self.default_discovery_allowed
            ).lower(),
        }
        for key, value in (
            ("model_dataset_scope", self.scope),
            ("model_dataset_target_source", self.target_source),
            ("model_dataset_replaced_by", self.replaced_by),
            ("model_dataset_legacy_reason", self.legacy_reason),
        ):
            if value:
                tags[key] = str(value)
        return tags


@dataclass(frozen=True)
class ModelDatasetVersionRegistry:
    """Loaded model dataset version status registry."""

    versions: dict[str, ModelDatasetVersionStatus]
    raw: dict[str, Any]

    def get(self, dataset_version: str) -> ModelDatasetVersionStatus:
        if dataset_version in self.versions:
            return self.versions[dataset_version]
        return ModelDatasetVersionStatus(
            dataset_version=str(dataset_version),
            status=str(self.raw.get("defaults", {}).get("default_status") or DEFAULT_STATUS),
            default_discovery_allowed=False,
            notes="Version is not listed in configs/ml/model_dataset_versions.yaml.",
        )

    def select_default(
        self,
        *,
        target_source: str | None = None,
        dataset_key: str | None = None,
    ) -> ModelDatasetVersionStatus:
        candidates = [
            version for version in self.versions.values()
            if version.default_discovery_allowed and version.is_active
        ]
        if target_source:
            candidates = [
                version for version in candidates
                if version.target_source == target_source
            ]
        if dataset_key:
            candidates = [
                version for version in candidates
                if dataset_key in version.dataset_keys
            ]
        if not candidates:
            detail = []
            if target_source:
                detail.append(f"target_source={target_source}")
            if dataset_key:
                detail.append(f"dataset_key={dataset_key}")
            suffix = f" for {' '.join(detail)}" if detail else ""
            raise ValueError(f"no active model-ready dataset version{suffix}")
        return sorted(
            candidates,
            key=lambda item: (item.default_priority, item.dataset_version),
            reverse=True,
        )[0]


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def _load_entry(item: dict[str, Any]) -> ModelDatasetVersionStatus:
    dataset_version = str(item.get("dataset_version") or "").strip()
    if not dataset_version:
        raise ValueError("model dataset status entry missing dataset_version")
    dataset_keys = tuple(str(value) for value in (item.get("dataset_keys") or ()))
    return ModelDatasetVersionStatus(
        dataset_version=dataset_version,
        status=str(item.get("status") or DEFAULT_STATUS),
        default_discovery_allowed=_as_bool(item.get("default_discovery_allowed")),
        target_source=str(item.get("target_source") or ""),
        dataset_keys=dataset_keys,
        source_gold_dataset_version=str(item.get("source_gold_dataset_version") or ""),
        scope=str(item.get("scope") or ""),
        commodity_count=_as_int(item.get("commodity_count")),
        matrix_count=_as_int(item.get("matrix_count")),
        target_count=_as_int(item.get("target_count")),
        legacy_reason=str(item.get("legacy_reason") or ""),
        replaced_by=str(item.get("replaced_by") or ""),
        default_priority=int(item.get("default_priority") or 0),
        notes=str(item.get("notes") or ""),
    )


def load_model_dataset_version_registry(
    path: str | Path | None = None,
) -> ModelDatasetVersionRegistry:
    """Load model-ready dataset version statuses."""
    cfg_path = Path(path) if path is not None else _CONFIG_PATH
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if int(raw.get("schema_version", 0)) != 1:
        raise ValueError(
            f"unsupported model dataset version schema_version: {raw.get('schema_version')}"
        )
    versions: dict[str, ModelDatasetVersionStatus] = {}
    for item in raw.get("versions") or []:
        loaded = _load_entry(item or {})
        if loaded.dataset_version in versions:
            raise ValueError(f"duplicate model dataset version: {loaded.dataset_version}")
        versions[loaded.dataset_version] = loaded
    return ModelDatasetVersionRegistry(versions=versions, raw=raw)


def get_model_dataset_version_status(
    dataset_version: str,
    *,
    registry: ModelDatasetVersionRegistry | None = None,
) -> ModelDatasetVersionStatus:
    """Return status metadata for a version, or an unknown placeholder."""
    reg = registry or load_model_dataset_version_registry()
    return reg.get(dataset_version)
