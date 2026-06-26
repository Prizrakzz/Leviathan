"""Target-definition loading for model-ready datasets."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "ml" / "target_definitions.yaml"
)


@dataclass(frozen=True)
class TargetDefinition:
    target_key: str
    dataset_key: str
    title: str
    label_column: str
    actual_column: str
    target_unit: str
    target_type: str
    horizon: str
    grain: tuple[str, ...]
    as_of_rule: str
    min_history_years: int
    baselines: tuple[str, ...]
    compatible_feature_sets: tuple[str, ...]
    target_compatibility: tuple[str, ...]
    allowed_commodities: tuple[str, ...]

    def allows_commodity(self, commodity: str) -> bool:
        return not self.allowed_commodities or commodity in self.allowed_commodities


def _as_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in (value or []))


def _config_sha(raw: dict) -> str:
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_target_definitions(
    path: str | Path | None = None,
) -> tuple[list[TargetDefinition], str, dict]:
    """Load target definitions, config SHA, and raw metadata.

    Defaults are merged into every target definition.  The SHA is logged in
    model-ready manifests so a dataset can be traced back to the exact target
    config used to build it.
    """
    config_path = Path(path) if path is not None else _CONFIG_PATH
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults") or {}
    definitions: list[TargetDefinition] = []
    seen: set[str] = set()

    for item in raw.get("target_definitions", []):
        merged = {**defaults, **(item or {})}
        target_key = str(merged["target_key"])
        if target_key in seen:
            raise ValueError(f"duplicate target_key: {target_key}")
        seen.add(target_key)
        definitions.append(TargetDefinition(
            target_key=target_key,
            dataset_key=str(merged["dataset_key"]),
            title=str(merged.get("title", target_key)),
            label_column=str(merged["label_column"]),
            actual_column=str(merged.get("actual_column", target_key)),
            target_unit=str(merged.get("target_unit", "")),
            target_type=str(merged.get("target_type", "trailing_trend_pct_anomaly")),
            horizon=str(merged.get("horizon", "")),
            grain=_as_tuple(merged.get("grain")),
            as_of_rule=str(merged.get("as_of_rule", "")),
            min_history_years=int(merged.get("min_history_years", 5)),
            baselines=_as_tuple(merged.get("baselines")),
            compatible_feature_sets=_as_tuple(merged.get("compatible_feature_sets")),
            target_compatibility=_as_tuple(merged.get("target_compatibility")),
            allowed_commodities=_as_tuple(merged.get("allowed_commodities")),
        ))

    if not definitions:
        raise ValueError(f"target config has no target_definitions: {config_path}")
    return definitions, _config_sha(raw), raw


def default_source_dataset_version(raw_config: dict) -> str | None:
    defaults = raw_config.get("defaults") or {}
    version = defaults.get("source_dataset_version")
    return str(version) if version else None
