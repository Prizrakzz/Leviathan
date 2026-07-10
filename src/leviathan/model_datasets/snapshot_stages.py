"""Snapshot-stage policies for model-ready datasets."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from leviathan.features.calendar import CropCalendar

_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "ml" / "snapshot_stages.yaml"
)


@dataclass(frozen=True)
class SnapshotStage:
    """A named model-ready as-of-date rule."""

    stage_id: str
    rule: str
    days: int = 0
    description: str = ""


@dataclass(frozen=True)
class SnapshotStageConfig:
    """Validated snapshot-stage config and provenance."""

    stages: tuple[SnapshotStage, ...]
    default_dataset_key: str
    snapshot_policy: str
    config_sha: str
    raw: dict[str, Any]


def _config_sha(raw: dict[str, Any]) -> str:
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_snapshot_stage_config(path: str | Path | None = None) -> SnapshotStageConfig:
    """Load and validate named snapshot stages."""
    cfg_path = Path(path) if path is not None else _CONFIG_PATH
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if int(raw.get("schema_version", 0)) != 1:
        raise ValueError(
            f"unsupported snapshot stage schema_version: {raw.get('schema_version')}"
        )

    defaults = raw.get("defaults") or {}
    default_dataset_key = str(defaults.get("dataset_key") or "").strip()
    snapshot_policy = str(defaults.get("snapshot_policy") or "").strip()
    if not default_dataset_key:
        raise ValueError("snapshot stage defaults.dataset_key is required")
    if not snapshot_policy:
        raise ValueError("snapshot stage defaults.snapshot_policy is required")

    stages: list[SnapshotStage] = []
    seen: set[str] = set()
    for item in raw.get("stages") or []:
        stage_id = str(item.get("id") or "").strip()
        rule = str(item.get("rule") or "").strip()
        if not stage_id:
            raise ValueError("snapshot stage missing id")
        if stage_id in seen:
            raise ValueError(f"duplicate snapshot stage: {stage_id}")
        if rule not in {
            "crop_year_start",
            "crop_year_start_plus_days",
            "crop_year_end_minus_days",
            "crop_year_end_plus_days",
        }:
            raise ValueError(f"{stage_id}: unsupported snapshot rule {rule!r}")
        days = int(item.get("days") or 0)
        if rule == "crop_year_start" and days:
            raise ValueError(f"{stage_id}: crop_year_start cannot define days")
        if rule != "crop_year_start" and days < 0:
            raise ValueError(f"{stage_id}: days must be non-negative")
        stages.append(
            SnapshotStage(
                stage_id=stage_id,
                rule=rule,
                days=days,
                description=str(item.get("description") or ""),
            )
        )
        seen.add(stage_id)

    if not stages:
        raise ValueError("snapshot stage config must define at least one stage")
    return SnapshotStageConfig(
        stages=tuple(stages),
        default_dataset_key=default_dataset_key,
        snapshot_policy=snapshot_policy,
        config_sha=_config_sha(raw),
        raw=raw,
    )


def _date_for_stage(calendar: CropCalendar, crop_year: int, stage: SnapshotStage) -> date:
    if stage.rule == "crop_year_start":
        return calendar.crop_year_start(crop_year)
    if stage.rule == "crop_year_start_plus_days":
        return calendar.crop_year_start(crop_year) + timedelta(days=stage.days)
    if stage.rule == "crop_year_end_minus_days":
        return calendar.crop_year_end(crop_year) - timedelta(days=stage.days)
    if stage.rule == "crop_year_end_plus_days":
        return calendar.crop_year_end(crop_year) + timedelta(days=stage.days)
    raise ValueError(f"unsupported snapshot rule {stage.rule!r}")


def resolve_snapshot_dates(
    *,
    calendar: CropCalendar,
    crop_years: list[int] | tuple[int, ...] | set[int],
    config: SnapshotStageConfig | None = None,
    stage_ids: tuple[str, ...] = (),
    as_of_date: str | date | pd.Timestamp | None = None,
    include_named_stages: bool = True,
) -> pd.DataFrame:
    """Resolve named and explicit snapshots to a compact frame."""
    cfg = config or load_snapshot_stage_config()
    requested = set(stage_ids)
    selected = []
    if include_named_stages:
        selected = [
            stage for stage in cfg.stages
            if not requested or stage.stage_id in requested
        ]
    unknown = requested - {stage.stage_id for stage in cfg.stages}
    if unknown:
        raise ValueError(f"unknown snapshot stages: {sorted(unknown)}")

    rows: list[dict[str, object]] = []
    for crop_year in sorted({int(year) for year in crop_years}):
        for stage in selected:
            rows.append({
                "crop_year": crop_year,
                "snapshot_stage": stage.stage_id,
                "as_of_date": _date_for_stage(calendar, crop_year, stage),
                "snapshot_policy": cfg.snapshot_policy,
            })
        if as_of_date is not None:
            rows.append({
                "crop_year": crop_year,
                "snapshot_stage": "explicit_as_of",
                "as_of_date": pd.Timestamp(as_of_date).date(),
                "snapshot_policy": "explicit_as_of_date",
            })

    return pd.DataFrame(
        rows,
        columns=["crop_year", "snapshot_stage", "as_of_date", "snapshot_policy"],
    )
