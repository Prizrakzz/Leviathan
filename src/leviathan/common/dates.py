from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timezone


@dataclass(frozen=True)
class MonthWindow:
    year: int
    month: int
    start_date: date
    end_date: date

    @property
    def start_yyyymmdd(self) -> str:
        return self.start_date.strftime("%Y%m%d")

    @property
    def end_yyyymmdd(self) -> str:
        return self.end_date.strftime("%Y%m%d")

    @property
    def month_key(self) -> str:
        return f"{self.year}-{self.month:02d}"


def month_windows(start_year: int, end_year: int) -> list[MonthWindow]:
    windows: list[MonthWindow] = []

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            last_day = calendar.monthrange(year, month)[1]

            windows.append(
                MonthWindow(
                    year=year,
                    month=month,
                    start_date=date(year, month, 1),
                    end_date=date(year, month, last_day),
                )
            )

    return windows


def coerce_date(as_of: "str | date | datetime | None") -> date:
    """Coerce an ISO string / date / datetime / None to a plain ``date`` (None -> UTC today).

    UTC, never the local clock: every fence in the ingest chain compares against
    S3 LastModified (UTC), and production passes --asof; the None branch exists for
    local dry-runs, which must not drift a day near midnight in a non-UTC timezone.
    """
    if as_of is None:
        return datetime.now(timezone.utc).date()
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    s = str(as_of).strip().replace("Z", "").replace("z", "")
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return date.fromisoformat(s[:10])


def current_harvest_season(as_of: "str | date | datetime | None" = None) -> str:
    """Return the CURRENT UNICA Centre-South harvest season label ``YYYY/YYYY+1``.

    The milling season is labelled by the calendar year in which crushing starts
    (April). April..December publish that season's bulletins; January..March
    publish the closing bulletins of the season that opened the PRIOR April. It
    auto-advances at the April boundary -- there is no hardcoded year to go stale.
    """
    d = coerce_date(as_of)
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}/{start + 1}"


def harvest_seasons_through(
    first_season: str,
    as_of: "str | date | datetime | None" = None,
) -> list[str]:
    """Every ``YYYY/YYYY+1`` label from *first_season* through the current season inclusive."""
    start = int(str(first_season).split("/")[0])
    end = int(current_harvest_season(as_of).split("/")[0])
    return [f"{y}/{y + 1}" for y in range(start, end + 1)]


def season_start_date(season: str) -> date:
    """First day of the crush for a ``YYYY/YYYY+1`` season label (1 April of the start year)."""
    return date(int(str(season).split("/")[0]), 4, 1)
