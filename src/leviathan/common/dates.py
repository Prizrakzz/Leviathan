from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date


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
