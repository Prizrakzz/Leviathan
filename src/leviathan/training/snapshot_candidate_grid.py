"""Batch grid helpers for WASDE snapshot candidate smoke runs."""
from __future__ import annotations

import itertools
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from leviathan.common.config import PROJECT_ROOT, load_yaml

DEFAULT_GRID_CONFIG = PROJECT_ROOT / "configs" / "ml" / "phase_snapshot_candidate_grid.yaml"


def _as_list(value: Any, *, default: Iterable[Any] = ()) -> list[Any]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if item is not None and str(item).strip()]
    return [value]


def _merge(defaults: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(defaults)
    out.update({key: value for key, value in override.items() if value is not None})
    return out


def _compact_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def load_snapshot_candidate_grid_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load and lightly validate the snapshot candidate grid YAML."""
    config = load_yaml(path or DEFAULT_GRID_CONFIG)
    if int(config.get("schema_version", 0)) != 1:
        raise ValueError("snapshot candidate grid requires schema_version: 1")
    if not config.get("hypotheses"):
        raise ValueError("snapshot candidate grid has no hypotheses")
    return config


def _profile_specs(raw: Any) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {"default": {"id": "default", "models": [], "params": {}}}
    specs: dict[str, dict[str, Any]] = {}
    for spec in _as_list(raw):
        if not isinstance(spec, dict) or "id" not in spec:
            raise ValueError(f"invalid model_param_profile spec: {spec!r}")
        specs[str(spec["id"])] = {
            "id": str(spec["id"]),
            "models": _as_list(spec.get("models")),
            "params": dict(spec.get("params", {})),
        }
    return specs


def _profile_allowed(profile: dict[str, Any], model: str) -> bool:
    models = {str(item) for item in _as_list(profile.get("models"))}
    return not models or model in models


def expand_snapshot_candidate_grid(
    config: dict[str, Any],
    *,
    include_hypotheses: Iterable[str] | None = None,
    exclude_hypotheses: Iterable[str] | None = None,
    model_dataset_version: str | None = None,
    source_dataset_version: str | None = None,
    bucket: str = "",
    aws_region: str = "",
) -> list[dict[str, str]]:
    """Expand a snapshot candidate YAML config into AWS Batch parameters."""
    defaults = dict(config.get("defaults", {}) or {})
    profiles = _profile_specs(config.get("model_param_profiles"))
    include = {str(item) for item in include_hypotheses or []}
    exclude = {str(item) for item in exclude_hypotheses or []}
    tasks: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()

    for hypothesis in config.get("hypotheses", []):
        if not isinstance(hypothesis, dict):
            raise ValueError(f"invalid hypothesis entry: {hypothesis!r}")
        hypothesis_id = str(hypothesis.get("id", "")).strip()
        if not hypothesis_id:
            raise ValueError("snapshot hypothesis missing id")
        if include and hypothesis_id not in include:
            continue
        if hypothesis_id in exclude:
            continue

        spec = _merge(defaults, hypothesis)
        selected_profiles = _as_list(spec.get("model_param_profiles"), default=("default",))
        for profile_id in selected_profiles:
            if str(profile_id) not in profiles:
                raise ValueError(f"unknown model_param_profile {profile_id!r}")

        for commodity, feature_set, dataset_key, target_key, model, profile_id in itertools.product(
            _as_list(spec.get("commodities")),
            _as_list(spec.get("feature_sets")),
            _as_list(spec.get("dataset_keys")),
            _as_list(spec.get("target_keys")),
            _as_list(spec.get("models")),
            selected_profiles,
        ):
            profile = profiles[str(profile_id)]
            model_name = str(model)
            if not _profile_allowed(profile, model_name):
                continue
            task = {
                "hypothesis_id": hypothesis_id,
                "commodity": str(commodity),
                "feature_set": str(feature_set),
                "feature_stack": str(spec.get("feature_stack", "auto")),
                "model_dataset_version": str(
                    model_dataset_version or spec.get("model_dataset_version", "latest")
                ),
                "dataset_key": str(dataset_key),
                "target_key": str(target_key),
                "model": model_name,
                "model_param_profile": str(profile_id),
                "model_params_json": _compact_json(dict(profile.get("params", {}))),
                "min_train_years": str(int(spec.get("min_train_years", 10))),
                "min_trainable_annual_groups": str(
                    int(spec.get("min_trainable_annual_groups", 20))
                ),
                "min_event_groups": str(int(spec.get("min_event_groups", 5))),
                "min_non_null_rate": str(float(spec.get("min_non_null_rate", 0.2))),
                "collapse_policy": str(spec.get("collapse_policy", "latest")),
                "source_dataset_version": str(
                    source_dataset_version or spec.get("source_dataset_version", "none")
                ),
                "bucket": bucket,
                "aws_region": aws_region,
            }
            dedupe_key = tuple(task[key] for key in (
                "commodity",
                "feature_set",
                "feature_stack",
                "model_dataset_version",
                "dataset_key",
                "target_key",
                "model",
                "model_param_profile",
                "collapse_policy",
            ))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            tasks.append(task)
    return tasks


def snapshot_candidate_grid_summary(tasks: list[dict[str, str]]) -> dict[str, Any]:
    """Small summary used by submitters and dry-run output."""
    return {
        "task_count": len(tasks),
        "hypotheses": sorted({task["hypothesis_id"] for task in tasks}),
        "commodities": sorted({task["commodity"] for task in tasks}),
        "dataset_keys": sorted({task["dataset_key"] for task in tasks}),
        "feature_sets": sorted({task["feature_set"] for task in tasks}),
        "feature_stacks": sorted({task["feature_stack"] for task in tasks}),
        "models": sorted({task["model"] for task in tasks}),
        "model_param_profiles": sorted({task["model_param_profile"] for task in tasks}),
        "collapse_policies": sorted({task["collapse_policy"] for task in tasks}),
    }
