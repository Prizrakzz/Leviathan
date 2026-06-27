from __future__ import annotations

import pandas as pd

from leviathan.features.calendar import CropCalendar
from leviathan.model_datasets.snapshot_stages import (
    load_snapshot_stage_config,
    resolve_snapshot_dates,
)


def _calendar() -> CropCalendar:
    return CropCalendar(
        commodity="corn_cbot",
        crop_year_start_month=5,
        mkt_year_offset=-1,
        stages={},
        gdd_window=None,
    )


def test_resolve_named_snapshot_stage_dates() -> None:
    cfg = load_snapshot_stage_config()

    snapshots = resolve_snapshot_dates(
        calendar=_calendar(),
        crop_years=[2024],
        config=cfg,
        stage_ids=("preseason", "midseason"),
    )

    by_stage = snapshots.set_index("snapshot_stage")
    assert by_stage.loc["preseason", "as_of_date"].isoformat() == "2024-05-01"
    assert by_stage.loc["midseason", "as_of_date"].isoformat() == "2024-07-30"
    assert by_stage.loc["preseason", "snapshot_policy"] == "named_stages_v1"


def test_resolve_explicit_as_of_date_without_named_stages() -> None:
    snapshots = resolve_snapshot_dates(
        calendar=_calendar(),
        crop_years=[2024, 2025],
        as_of_date="2026-06-01",
        include_named_stages=False,
    )

    assert snapshots["snapshot_stage"].tolist() == ["explicit_as_of", "explicit_as_of"]
    assert snapshots["as_of_date"].tolist() == [
        pd.Timestamp("2026-06-01").date(),
        pd.Timestamp("2026-06-01").date(),
    ]
    assert snapshots["snapshot_policy"].eq("explicit_as_of_date").all()
