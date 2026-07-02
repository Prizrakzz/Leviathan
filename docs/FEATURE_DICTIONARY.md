# Feature Spine — Column & Transformation Dictionary

The authoritative reference for `gold_feature_spine` (and its wide pivot
`gold/feature_matrix`): what every column is, the exact transformation applied,
and the point-in-time rule that governs it. Generated features are defined in
`configs/features/features.yaml`; the maths lives in
`src/leviathan/features/computations/`.

---

## 1. Spine schema (long format)

`gold_feature_spine` is **long**: one row per `(commodity, country, crop_year, feature)`.
The schema is fixed — adding features never changes it.

| Column | Type | Meaning |
|---|---|---|
| `commodity` | string (partition) | Futures-contract slug, e.g. `corn_cbot`, `arabica_coffee`. |
| `country` | string | Producing country, pipeline convention (`united_states`, `brazil`). Macro/global signals are broadcast to every country in the commodity's geography. |
| `crop_year` | int | The marketing/crop year the observation describes. Defined by `configs/features/crop_calendars.yaml` (`crop_year_start_month`). |
| `feature` | string | Feature name — see §4. Pattern: `family[_region[_stage]]`. |
| `value` | double | The feature value. NaN means **structural missingness** (data did not exist), never 0 — XGBoost/LightGBM learn the NaN split. |
| `is_label` | boolean | `true` for training targets (the `label_*` features); never served as a model input. |
| `event_time` | date | The date this value is *first knowable* — the crop-year start. Enforces point-in-time correctness for training/serving. |

The **wide** `gold/feature_matrix/commodity={slug}/` is the spine pivoted to one
row per `(country, crop_year)` with every feature as its own column (plus the
`label_*` columns) — the direct training input. Its column set is per-commodity
(it only carries that commodity's regions/stages); the full inventory is
`gold_feature_catalog`.

---

## 2. Transformations used everywhere

- **`trailing_baseline_z` (anti-leakage z-score).** `z[Y] = (x[Y] − mean(x[Y−w..Y−1])) / std(x[Y−w..Y−1])`. The baseline is the prior `window_years` (default 30, `min_years` 10) **excluding year Y** — a trailing window, *never* a fixed climatology, so no future leaks into the past. Zero-variance or too-few-priors → NaN. Defined in `computations/base.py`.
- **Stage windowing.** Weather features aggregate only over a crop's agronomic stage window (`planting`, `flowering`/`silking`, `grain_fill`, `harvest`, `frost_risk`) from `crop_calendars.yaml`. A stage whose window has not fully elapsed by the last observation is emitted as NaN, not a partial aggregate.
- **Visibility (point-in-time) classes** (`computations/visibility.py`):
  - `crop_year_direct` — in-season data within crop year Y (weather).
  - `prior_history` — only data strictly before crop year Y (macro/positioning).
  - `prior_marketing_year` — the PSD/estimate vintage known at the crop-year start (the balance sheet actually visible at planting).
- **Naming.** `family_<region>` (one per origin region) or `family_<region>_<stage>` (per region × stage). Region-less signals (macro, S/D) emit a bare `family` name.

---

## 3. Labels (training targets, `is_label = true`)

| Feature | Source | Transformation |
|---|---|---|
| `label_production_quantity` | FAOSTAT (`silver/production`) | The crop year's own production (tonnes). The thing to forecast. |
| `label_area_harvested` | FAOSTAT | Harvested area (ha) for the crop year. |
| `label_yield` | FAOSTAT | Yield (t/ha). |

FAOSTAT country names are reconciled to the pipeline convention at read
(`united_states_of_america → united_states`, `viet_nam → vietnam`, etc.), so
US-only contracts get labels. Labels run 1981–2024 (FAOSTAT lags ~1–2 yr); 2025/26
rows are inference rows (features, no label).

---

## 4. Feature families

### 4a. Weather / climate — `crop_year_direct`, per region (× stage)

| Feature | Source (silver) | Transformation |
|---|---|---|
| `chirps_precip_z_<region>_<stage>` | `weather/source=chirps` (`precipitation_mm`) | Stage-mean daily precip, `trailing_baseline_z`. Range ±15. |
| `nasa_tmax_anomaly_<region>_<stage>` | `weather/source=nasa_power` (`temperature_2m_max_c`) | Stage-mean Tmax, `trailing_baseline_z`. Range ±15. |
| `nasa_tmin_anomaly_<region>_<stage>` | `nasa_power` (`temperature_2m_min_c`) | Stage-mean Tmin, `trailing_baseline_z`. Range ±15. |
| `gdd_z_<region>` | `nasa_power` (tmax+tmin) | Growing Degree Days over the GDD window: `Σ max(0, (min(Tmax,cap)+max(Tmin,base))/2 − base)`, per-crop base/cap (`feature_params.gdd`), then `trailing_baseline_z`. Range ±15. |
| `heat_stress_z_<region>` | `nasa_power` (tmax) | Count of days `Tmax > threshold` (corn/soy 35 °C, wheat 32 °C) over the GDD window, `trailing_baseline_z`. Captures critical-stage heat extremes that capped GDD and means miss. Range ±15. |
| `drought_z_<region>_<stage>` | `chirps` | Longest consecutive run of "dry" days (daily precip below the 20th percentile of the same stage's trailing climatology), then `trailing_baseline_z` of the annual run length. Range ±15. |
| `cpc_soil_z_<region>_<stage>` | `weather/source=cpc_soil` (`soil_moisture_mm`) | Stage-mean soil moisture, `trailing_baseline_z`. Range ±15. |
| `modis_ndvi_z_<region>_<stage>` | `weather/source=modis_ndvi` (`ndvi_z_score`) | Stage-mean of the **pre-computed** MODIS NDVI z-score (vs. its own MODIS climatology) — *not* re-normalized. Range ±15. |
| `frost_event_flag_<region>` | `nasa_power` (tmin) | 1 if `Tmin < 0 °C` anywhere in the frost-risk window, else 0. Early 1 allowed (a frost is a fact); early 0 suppressed to NaN. |
| `capacity_recovery_index_<region>` | `nasa_power` (tmin) | Tree-crops only (coffee). Multi-year productive-wood recovery after a severe frost: `1 − (severity/3)·0.5^(Δt/half_life)`, carrying frost damage forward across crop years. `prior_history`. Range [0,1]. |
| `capacity_lookback_truncated_<region>` | derived | 1 when the recovery lookback is shorter than `2×half_life` of available history (early-year reliability flag). |

### 4b. Production — FAOSTAT, `prior_history`, region-less

| Feature | Transformation |
|---|---|
| `faostat_production_yoy` | Year-over-year fractional change in production, prior years only. Range [−1, 10]. |
| `faostat_production_trend_dev` | Deviation of production from a rolling linear trend (`trend_years` 10, `trend_min_years` 5), as a fraction of trend. Range [−1, 10]. |
| `faostat_available` | 1 if a FAOSTAT vintage exists for the country/year, else 0. |

### 4c. Supply-demand balance — `prior_marketing_year` (the vintage visible at planting)

| Feature | Source | Transformation |
|---|---|---|
| `psd_ending_stock_su_ratio` | USDA PSD (`silver/psd`) | Stock-to-use ratio (ending stocks ÷ consumption) from the PSD vintage known at crop-year start. Range [−1, 20] (residual S/U can dip slightly negative). |
| `psd_su_ratio_yoy_delta` | PSD | Year-over-year change in the S/U ratio. Range [−20, 20]. |
| `psd_available` | PSD | 1 if a point-in-time PSD vintage exists, else 0. |
| `wap_nonUS_production_revision_z` | WAP Table 01 revisions (`silver/wap_table01_revisions`) | Latest non-US (`total_foreign`) month-on-month production-estimate revision before crop-year start, `trailing_baseline_z`. Range ±10. |
| `mpob_production_z` / `mpob_exports_z` / `mpob_su_ratio_z` | MPOB (`silver/mpob`) | Palm only. Prior crop year's annual CPO production / palm-oil exports / end-of-year S/U, each `trailing_baseline_z` (window 10, min 5 — short history). Range ±10. |
| `crush_margin_z` | `silver/futures_prices` | Soy complex only. Board crush margin `$/bu = 0.022·meal($/t) + 0.11·oil(¢/lb) − 0.01·beans(¢/bu)`, latest value before crop-year start, `trailing_baseline_z`. A demand-side driver (high margin → more crush → tighter bean stocks). `prior_history`. Range ±10. |

### 4d. Macro / climate teleconnection — `prior_history`, region-less

| Feature | Source | Transformation |
|---|---|---|
| `oni_anom_prior` | NOAA ONI (`weather/source=noaa_oni`) | ENSO ONI anomaly (°C) at the month before crop-year start. |
| `oni_el_nino_flag` / `oni_la_nina_flag` | ONI | ENSO phase flags (1/0) at that month. |
| `oni_lag3_prior` / `oni_lag6_prior` | ONI | ONI at a 3- / 6-month lag (crop impact trails the SST anomaly). |
| `oni_la_nina_brazil_flag` / `oni_la_nina_argentina_flag` | ONI | Origin-specific La Niña flags, routed to Brazil- / Argentina-origin commodities. |
| `iod_dmi_prior` | NOAA IOD (`weather/source=noaa_iod`) | Indian Ocean Dipole 3-month-average DMI at the month before crop-year start. |
| `pink_sheet_npk_z` / `pink_sheet_dap_z` / `pink_sheet_urea_z` | World Bank Pink Sheet (`silver/pink_sheet`) | Fertilizer 5-yr z-scores (blended NPK index / DAP / urea) at the latest month before crop-year start (input-cost / planting-economics signal). Range ±10. |
| `pink_sheet_energy_z` | Pink Sheet | Brent crude 5-yr z-score (energy / freight proxy). Range ±10. |
| `brl_fx_pct_90d` / `cny_fx_pct_90d` | FRED FX (`silver/fred_fx`) | BRL/USD or CNY/USD 90-day % change at the latest trading day before crop-year start. BRL → Brazil exporters (coffee, sugar, soy); CNY → China importers (soy, corn, palm). Range ±40. |
| `cot_mm_net_z` / `cot_mm_pct_oi_z` | CFTC COT (`silver/cot`) | Managed-money net position (and % of open interest) 3-yr z-score from the last report before crop-year start — speculative positioning context. Range ±5. |

### 4e. Trade pace / crop condition / regional estimates

| Feature | Source | Visibility | Transformation |
|---|---|---|---|
| `esr_outstanding_sales_z` / `esr_net_commitment_z` / `esr_export_pace_z` | USDA FAS ESR (`silver/esr`) | `prior_history` | US forward export-commitment z-scores (outstanding sales, net commitments, shipment pace) — leading demand signal incl. unshipped sales. |
| `fgis_export_pace_yoy` | USDA FGIS (`silver/fgis`) | `prior_history` | US cumulative export-inspection pace vs. prior year. Range [−1, 5]. |
| `nass_ge_pct_z` | USDA NASS crop progress (`silver/nass_crop_progress`) | `crop_year_direct` | National season-average % Good+Excellent (mean across reporting states per week, then across weeks), `trailing_baseline_z`. Only the in-progress current season is completeness-gated. Range ±10. |
| `sagis_delivery_z` | SAGIS weekly (`silver/sagis_weekly_deliveries`) | `prior_history` | SA maize. End-of-season (`z_vs_3yr_avg`, already normalized) progressive-delivery z for the prior marketing year. Range ±10. |
| `sagis_cec_revision_surprise` | SAGIS CEC (`silver/sagis_cec`) | `prior_marketing_year` | SA maize. Crop Estimates Committee production-revision surprise (`revision_surprise`, pre-normalized) from the latest release before crop-year start. Range ±3. |
| `conab_production_revision_bags` | CONAB (`silver/conab_coffee`) | `prior_marketing_year` | Brazil coffee. CONAB production-revision (thousand bags) from the latest survey before crop-year start. |

---

## 5. Tiers & windows

`configs/features/feature_tiers.yaml` groups families into data-era tiers
(`fundamentals` ~1981 → `climate` ~1990 → `trade_condition` ~1994 → `full` ~2009);
`gold_training_windows` records, per `(commodity, tier)`, the supervised window
and the `dense_start_year`. A training run selects a tier, not a column list.

## 6. Source tables (Athena)

Every silver source has an inspection table in the `leviathan_dev` Athena
database (see `sql/athena/ddl/`), e.g. `silver_psd`, `silver_fred_fx`,
`silver_pink_sheet`, `silver_noaa_oni`, `silver_futures_prices`. The long
`gold_feature_spine` and per-run `silver_model_predictions` are the primary
analysis tables.


## ESR marketing-year convention (pinned 2026-07-03)

`silver_esr.market_year` is the **FAS END-year label**: corn/soybeans MY Sep-2023..Aug-2024 = `2024`
(PSD labels the same year `2023`). Boundaries differ per class: wheat Jun..Jun, soybean oil Oct..Oct.
`esr_*` features therefore select programmes by **week dates, never label arithmetic**: for crop year Y,
the latest programme whose `max(week_ending_date) < crop_year_start(Y)` (the freshest COMPLETED programme
known at planting). Pinned by tests/unit/test_features_computations_esr.py (label-shift invariance +
leakage guard). Silver keeps only the LATEST as_of snapshot per MY — no true ESR vintages exist; never
derive esr_*_revision features from it. See docs/ML_EXPERIMENT_DATA_AUDIT_REPORT.md sections 3.1 / 3.10.
