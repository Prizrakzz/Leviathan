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
from leviathan.features.computations.macro_climate import (
    compute_cot_mm_positioning,
    compute_fred_fx,
    compute_iod_climate,
    compute_oni_climate,
    compute_oni_lag,
    compute_pink_sheet_input_costs,
)
from leviathan.features.computations.production import (
    compute_faostat_available,
    compute_faostat_labels,
    compute_faostat_production_trend_dev,
    compute_faostat_production_yoy,
)
from leviathan.features.computations.sd_balance import (
    compute_crush_margin_z,
    compute_mpob_fundamentals,
    compute_psd_available,
    compute_psd_ending_stock_su_ratio,
    compute_psd_su_ratio_yoy_delta,
    compute_wap_nonUS_production_revision,
)
from leviathan.features.computations.crop_progress import compute_nass_crop_progress_ge_z
from leviathan.features.computations.esr_exports import compute_esr_exports
from leviathan.features.computations.trade_flows import (
    compute_conab_production_revision,
    compute_fgis_export_pace_yoy,
    compute_sagis_cec_revision,
    compute_sagis_deliveries_z,
)
from leviathan.features.computations.weather_stage import (
    compute_cpc_soil_z,
    compute_drought_z,
    compute_frost_event_flag,
    compute_gdd_z,
    compute_heat_stress_z,
    compute_modis_ndvi_z,
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
    "gdd_z": compute_gdd_z,
    "heat_stress_z": compute_heat_stress_z,
    "drought_z": compute_drought_z,
    "cpc_soil_z": compute_cpc_soil_z,
    "modis_ndvi_z": compute_modis_ndvi_z,
    "capacity_recovery_index": compute_capacity_recovery_index,
    "faostat_production_yoy": compute_faostat_production_yoy,
    "faostat_production_trend_dev": compute_faostat_production_trend_dev,
    "faostat_available": compute_faostat_available,
    "faostat_labels": compute_faostat_labels,
    "psd_ending_stock_su_ratio": compute_psd_ending_stock_su_ratio,
    "crush_margin_z": compute_crush_margin_z,
    "mpob_fundamentals": compute_mpob_fundamentals,
    "wap_nonUS_revision": compute_wap_nonUS_production_revision,
    "psd_su_ratio_yoy_delta": compute_psd_su_ratio_yoy_delta,
    "psd_available": compute_psd_available,
    "oni_climate": compute_oni_climate,
    "oni_lag_climate": compute_oni_lag,
    "iod_climate": compute_iod_climate,
    "cot_mm_positioning": compute_cot_mm_positioning,
    "fred_fx_macro": compute_fred_fx,
    "pink_sheet_input_costs": compute_pink_sheet_input_costs,
    "conab_production_revision": compute_conab_production_revision,
    "fgis_export_pace_yoy": compute_fgis_export_pace_yoy,
    "sagis_deliveries_z": compute_sagis_deliveries_z,
    "sagis_cec_revision": compute_sagis_cec_revision,
    "esr_exports": compute_esr_exports,
    "nass_crop_progress_ge_z": compute_nass_crop_progress_ge_z,
}

__all__ = ["COMPUTATIONS", "FeatureContext"]
