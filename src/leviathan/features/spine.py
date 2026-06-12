"""Feature-spine assembly: observation grid, computation loop, output validation.

The spine is LONG format — fixed six-column schema regardless of how many
features the registry grows:

    country (str), crop_year (int32), feature (str), value (float64),
    is_label (bool), event_time (date)

one Parquet partition per commodity (``gold/feature_spine/commodity={slug}/``).
Long format keeps the Athena schema permanently stable (adding features never
changes DDL), and the wide pivot for XGBoost training is a millisecond
operation at this grain (~10-15k observations per commodity).

Natural key: ``(country, crop_year, feature)`` within a commodity partition.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from leviathan.common.logging import get_logger
from leviathan.features.calendar import CropCalendar
from leviathan.features.computations import COMPUTATIONS, FeatureContext
from leviathan.features.registry import FeatureRegistry, FeatureSpec
from leviathan.features.visibility import event_time as _event_time

logger = get_logger(__name__)

SPINE_COLUMNS = ["country", "crop_year", "feature", "value", "is_label", "event_time"]
SPINE_NATURAL_KEY = ["country", "crop_year", "feature"]

_GEOGRAPHY_DIR = Path(__file__).resolve().parents[3] / "configs" / "geographies"


def default_calendar(commodity: str) -> CropCalendar:
    """Fallback calendar (Jan-start crop year, prior marketing year) for
    commodities without a crop_calendars.yaml entry.  Stage-window weather
    families never apply to these — only annual/S-D features that need crop
    year arithmetic and an event_time."""
    return CropCalendar(
        commodity=commodity, crop_year_start_month=1, mkt_year_offset=-1,
        stages={}, gdd_window=None,
    )


def load_countries(commodity: str, geography_dir: str | Path | None = None) -> list[str]:
    """Origin countries for a commodity from its geographies YAML.

    Missing geography file -> empty list; the caller decides whether to fall
    back to countries observed in the production data.
    """
    geo_dir = Path(geography_dir) if geography_dir is not None else _GEOGRAPHY_DIR
    path = geo_dir / f"{commodity}_regions.yaml"
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return sorted({
        str(entry["country"])
        for entry in raw.get("regions", [])
        if entry.get("country")
    })


@dataclass
class SpineBuildResult:
    commodity: str
    df: pd.DataFrame
    report: dict
    passed: bool


def build_spine(
    commodity: str,
    crop_years: list[int],
    countries: list[str],
    calendar: CropCalendar,
    registry: FeatureRegistry,
    inputs: dict[str, pd.DataFrame],
) -> SpineBuildResult:
    """Run every applicable registry spec and assemble the validated spine."""
    specs = registry.specs_for(commodity)
    frames: list[pd.DataFrame] = []

    for spec in specs:
        ctx = FeatureContext(
            commodity=commodity,
            crop_years=list(crop_years),
            countries=list(countries),
            calendar=calendar,
            inputs=inputs,
            params=_merge_params(registry.shared_params, spec.params),
        )
        result = COMPUTATIONS[spec.family](ctx, spec)
        if result.empty:
            continue
        result = result.copy()
        result["is_label"] = spec.is_label
        result["_family"] = spec.family
        frames.append(result)

    if frames:
        spine = pd.concat(frames, ignore_index=True)
    else:
        spine = pd.DataFrame(columns=["country", "crop_year", "feature", "value",
                                      "is_label", "_family"])

    spine["crop_year"] = pd.to_numeric(spine["crop_year"], errors="coerce").astype("int32")
    spine["value"] = pd.to_numeric(spine["value"], errors="coerce").astype("float64")
    spine["is_label"] = spine["is_label"].astype(bool)
    spine["event_time"] = spine["crop_year"].map(
        lambda y: _event_time(calendar, int(y))
    )

    report = _validate(spine, specs, commodity)
    spine = (
        spine.drop(columns=["_family"])
        .loc[:, SPINE_COLUMNS]
        .sort_values(SPINE_NATURAL_KEY)
        .reset_index(drop=True)
    )
    return SpineBuildResult(
        commodity=commodity, df=spine, report=report, passed=report["passed"]
    )


def _merge_params(shared: dict, overrides: dict) -> dict:
    """Shallow-merge spec overrides over shared params (per top-level section)."""
    merged = dict(shared)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _validate(spine: pd.DataFrame, specs: list[FeatureSpec], commodity: str) -> dict:
    """Registry-derived output validation in the silver quality-report idiom.

    Hard failures (block the write):
    - duplicate natural keys
    - null country / crop_year / feature
    - values outside the spec's declared value_range (bounds are generous —
      a violation means a computation bug or an upstream data corruption,
      both of which warrant a human look before the spine is consumed)
    """
    hard: dict = {}

    dupes = int(spine.duplicated(subset=SPINE_NATURAL_KEY).sum())
    if dupes:
        hard["duplicate_natural_keys"] = dupes

    null_keys = {
        col: int(spine[col].isna().sum())
        for col in ("country", "crop_year", "feature")
        if int(spine[col].isna().sum())
    }
    if null_keys:
        hard["null_key_values"] = null_keys

    range_violations: dict = {}
    by_family = dict(spine.groupby("_family").groups) if not spine.empty else {}
    for spec in specs:
        if spec.family not in by_family:
            continue
        lo, hi = spec.value_range
        values = spine.loc[by_family[spec.family], "value"].dropna()
        bad = 0
        if lo is not None:
            bad += int((values < lo).sum())
        if hi is not None:
            bad += int((values > hi).sum())
        if bad:
            range_violations[spec.family] = {
                "out_of_range_count": bad,
                "observed_min": float(values.min()),
                "observed_max": float(values.max()),
                "expected_min": lo,
                "expected_max": hi,
            }
    if range_violations:
        hard["range_violations"] = range_violations

    report = {
        "commodity": commodity,
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "row_count": int(len(spine)),
        "feature_count": int(spine["feature"].nunique()) if not spine.empty else 0,
        "label_row_count": int(spine["is_label"].sum()) if not spine.empty else 0,
        "passed": not hard,
        "hard_failures": hard,
    }
    if hard:
        logger.error("Spine validation FAILED for %s: %s", commodity, hard)
    else:
        logger.info(
            "Spine validated for %s: %d rows, %d features",
            commodity, report["row_count"], report["feature_count"],
        )
    return report
