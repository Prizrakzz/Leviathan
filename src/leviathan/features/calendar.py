"""Crop calendars: crop-year date arithmetic and phenological stage windows.

Loads ``configs/features/crop_calendars.yaml`` and resolves month-based stage
windows to absolute date ranges per crop year, handling windows that cross the
calendar-year boundary (e.g. arabica grain_fill Nov–Mar).

Crop-year convention
--------------------
Integer ``crop_year`` N spans ``[date(N, start_month, 1), date(N+1, start_month, 1))``.
A stage month is resolved to its first occurrence on/after the crop-year start,
so every stage window falls inside the 12-month crop-year span.
"""
from __future__ import annotations

import calendar as _stdlib_calendar
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

# Repo-root configs directory (jobs run from a checkout / Docker image of the repo).
_DEFAULT_CONFIG = (
    Path(__file__).resolve().parents[3] / "configs" / "features" / "crop_calendars.yaml"
)


@dataclass(frozen=True)
class StageWindow:
    """A phenological stage resolved to absolute dates within one crop year."""
    stage: str
    start_date: date
    end_date: date  # inclusive


@dataclass(frozen=True)
class CropCalendar:
    """Calendar for one commodity."""
    commodity: str
    crop_year_start_month: int
    mkt_year_offset: int
    stages: dict[str, tuple[int, int]] = field(default_factory=dict)
    gdd_window: tuple[str, str] | None = None

    def crop_year_start(self, crop_year: int) -> date:
        return date(crop_year, self.crop_year_start_month, 1)

    def crop_year_end(self, crop_year: int) -> date:
        """Inclusive last day of the crop year."""
        nxt = self.crop_year_start(crop_year + 1)
        return _prev_day(nxt)

    def stage_window(self, stage: str, crop_year: int) -> StageWindow:
        """Resolve *stage* to absolute dates within *crop_year*.

        Each stage month maps to its first occurrence on/after the crop-year
        start date.  A window whose start month falls later in the crop year
        than its end month (e.g. harvest Oct–Jan for a Jan-start crop year)
        crosses the calendar-year boundary and ends in the following year.
        """
        if stage not in self.stages:
            raise KeyError(f"{self.commodity}: unknown stage '{stage}'")
        start_month, end_month = self.stages[stage]

        start_year = self._year_of_month(start_month, crop_year)
        end_year = self._year_of_month(end_month, crop_year)
        # Cross-year window: end month occurs before start month within the
        # crop year ordering -> push the end into the following calendar year.
        if (end_year, end_month) < (start_year, start_month):
            end_year += 1

        last_day = _stdlib_calendar.monthrange(end_year, end_month)[1]
        return StageWindow(
            stage=stage,
            start_date=date(start_year, start_month, 1),
            end_date=date(end_year, end_month, last_day),
        )

    def gdd_dates(self, crop_year: int) -> tuple[date, date] | None:
        """Absolute (start, end) of the GDD accumulation window, if defined."""
        if not self.gdd_window:
            return None
        first = self.stage_window(self.gdd_window[0], crop_year)
        last = self.stage_window(self.gdd_window[1], crop_year)
        return first.start_date, last.end_date

    def _year_of_month(self, month: int, crop_year: int) -> int:
        """Calendar year of *month*'s first occurrence on/after crop-year start."""
        if month >= self.crop_year_start_month:
            return crop_year
        return crop_year + 1


def _prev_day(d: date) -> date:
    from datetime import timedelta
    return d - timedelta(days=1)


def load_crop_calendars(path: str | Path | None = None) -> dict[str, CropCalendar]:
    """Load all crop calendars; returns ``{commodity: CropCalendar}``."""
    cfg_path = Path(path) if path is not None else _DEFAULT_CONFIG
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    calendars: dict[str, CropCalendar] = {}
    for commodity, spec in raw.items():
        start_month = int(spec["crop_year_start_month"])
        if not 1 <= start_month <= 12:
            raise ValueError(f"{commodity}: crop_year_start_month must be 1-12, got {start_month}")

        stages: dict[str, tuple[int, int]] = {}
        for name, window in (spec.get("stages") or {}).items():
            if len(window) != 2 or not all(1 <= int(m) <= 12 for m in window):
                raise ValueError(f"{commodity}: stage '{name}' window must be [1-12, 1-12]")
            stages[name] = (int(window[0]), int(window[1]))

        gdd_window: tuple[str, str] | None = None
        if spec.get("gdd_window"):
            first, last = spec["gdd_window"]
            for s in (first, last):
                if s not in stages:
                    raise ValueError(f"{commodity}: gdd_window stage '{s}' not in stages")
            gdd_window = (first, last)

        calendars[commodity] = CropCalendar(
            commodity=commodity,
            crop_year_start_month=start_month,
            mkt_year_offset=int(spec.get("mkt_year_offset", -1)),
            stages=stages,
            gdd_window=gdd_window,
        )
    return calendars
