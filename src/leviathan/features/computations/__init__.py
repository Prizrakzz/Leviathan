"""Computation dispatch table — family name -> pure feature function.

Every function has the signature ``(FeatureContext, FeatureSpec) -> DataFrame``
with result columns ``[country, crop_year, feature, value]``.  The registry
validates at load time that every features.yaml family resolves here.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from leviathan.features.computations.base import FeatureContext
from leviathan.features.computations.capacity import compute_capacity_recovery_index
from leviathan.features.computations.production import (
    compute_faostat_available,
    compute_faostat_labels,
    compute_faostat_production_trend_dev,
    compute_faostat_production_yoy,
)
from leviathan.features.computations.sd_balance import (
    compute_psd_available,
    compute_psd_ending_stock_su_ratio,
    compute_psd_su_ratio_yoy_delta,
    compute_wasde_production_revision,
    compute_wasde_stocks_revision,
)
from leviathan.features.computations.weather_stage import (
    compute_drought_consecutive_days,
    compute_frost_event_flag,
    compute_gdd_accumulated,
    compute_stage_precip_z,
    compute_stage_tmax_anomaly,
    compute_stage_tmin_anomaly,
)

ComputeFn = Callable[..., pd.DataFrame]

COMPUTATIONS: dict[str, ComputeFn] = {
    "stage_precip_z": compute_stage_precip_z,
    "stage_tmax_anomaly": compute_stage_tmax_anomaly,
    "stage_tmin_anomaly": compute_stage_tmin_anomaly,
    "frost_event_flag": compute_frost_event_flag,
    "gdd_accumulated": compute_gdd_accumulated,
    "drought_consecutive_days": compute_drought_consecutive_days,
    "capacity_recovery_index": compute_capacity_recovery_index,
    "faostat_production_yoy": compute_faostat_production_yoy,
    "faostat_production_trend_dev": compute_faostat_production_trend_dev,
    "faostat_available": compute_faostat_available,
    "faostat_labels": compute_faostat_labels,
    "psd_ending_stock_su_ratio": compute_psd_ending_stock_su_ratio,
    "psd_su_ratio_yoy_delta": compute_psd_su_ratio_yoy_delta,
    "wasde_production_revision": compute_wasde_production_revision,
    "wasde_stocks_revision": compute_wasde_stocks_revision,
    "psd_available": compute_psd_available,
}

__all__ = ["COMPUTATIONS", "FeatureContext"]
