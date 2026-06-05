# Leviathan — Desired State
> Authoritative vision document. Update when strategy evolves.
> Companion to currentstate.md — tracks where we're going, not where we are.
> Last updated: June 2, 2026 (updated from full S3 audit)

---

## Strategic Objective

Build a commodity market-neutral trading system that generates production-informed
mispricing signals across 31 agricultural commodities.

**The thesis in one sentence:** Forecast what production will be this season at the
country level, find every historical year where production was at that level, observe
what price did in those environments, and identify when current price has not yet
adjusted to what the fundamentals imply.

This is not directional macro trading ("corn goes up"). It is:
- **Spread / dispersion**: relative value between related contracts
  (arabica/robusta, CBOT corn/Campinas corn, CBOT soy/DCE soy) where
  country-level origin stress diverges
- **Fundamental mispricing**: when the current price has not yet converged to
  what similar production environments implied historically

The system fuses two layers:
1. **Quantitative**: weather + production data → ML production forecast →
   historical analogue lookup → mispricing signal
2. **Qualitative**: analyst reports + crop surveys → GraphRAG knowledge graph →
   standalone research intelligence layer that enables consequence chain traversal,
   relative value analysis, analyst accuracy calibration, counterfactual conditioning,
   narrative shift detection, and cross-source consensus scoring. This is not a passive
   context provider for the quant model — it is a primary research interface that answers
   questions no structured data system can answer.

Price data is required for the analogue lookup (Phase 2). All of Phase 1 — the
production forecasting model, feature engineering, and GraphRAG indexing — is
buildable now without it.

---

## The 31 Commodities

**Grains**: corn_cbot, campinas_corn_reference_bmf, french_wheat_matif,
french_maize_matif, hard_red_winter_wheat_kcbt, hard_red_spring_wheat_mgex,
soft_red_winter_wheat_cbot, rough_rice_cbot, south_african_white_maize_jse,
south_african_yellow_maize_jse

**Oilseeds**: soybeans_cbot, soybean_meal_cbot, soybean_oil_cbot,
soybeans_no_1_dce, soybeans_no_2_dce, soybean_meal_dce, soybean_oil_dce,
french_rapeseed_matif, canola_ice, rapeseed_oil_zce, rapeseed_meal_zce,
malaysian_crude_palm_oil_cme, palm_olein_dce

**Softs**: arabica_coffee, brazilian_arabica_coffee, robusta_coffee, cotton,
raw_sugar, white_sugar, frozen_orange_juice, cocoa

---

## ML Prediction Framework

### What We Are Modeling

**Target**: `production_quantity` and `yield` at `country × commodity × crop_year` grain.
`area_harvested` as a secondary target where planting decisions are modeled separately
(input costs, farmer switching, policy mandates).

We are NOT predicting price. We predict production and compare it against historical
production-price pairs to generate a mispricing z-score (Phase 2).

**The structural insight behind the spread signal**: shared features across commodity
models make the spread tradeable without price data. When arabica and robusta share the
same ENSO feature but diverge on their origin-specific CHIRPS and CONAB signals, the
*difference* in their Tier 1 stress scores is the spread driver. Tier 3 captures what
Tier 1 already computed — it just needs price data to size the position. The features
are designed to be asymmetric: one leg of each spread pair fires without the other in
typical years. When both legs fire simultaneously, spread conviction collapses and the
anomaly detection layer flags it.

---

### Feature Taxonomy

Three layers of features, universal to commodity-specific:

```
Universal (all 31 commodities)
  └── Group (grains / oilseeds / softs)
        └── Commodity-specific (per contract or origin)
              └── Anomaly detectors (binary flags + severity scores, stage-aware)
```

---

#### Annual Crops vs Perennial Tree Crops — Productive Capacity Design Rule

**This distinction changes how climate risk features must be structured.**

Annual crops (corn, wheat, soybeans, cotton, sugar, rice) reset every season:
```
plant → grow → harvest → field resets
```
If one season is bad, the farmer replants next year. Productive capacity is fully
restored by definition at the start of each crop year. A single feature value per
season is sufficient — there is no carry-forward of capacity damage.

Tree crops (arabica coffee, robusta coffee, cocoa, palm oil, FCOJ citrus) do not
reset:
```
plant tree → wait years for full production → tree survives many seasons
→ flowering/cherry development repeats annually on the same tree
→ damage to wood or cambium persists across years
```
For tree crops, productive capacity is a **stock variable** that changes slowly.
A severe frost, sustained disease pressure, or extreme heat that kills productive
wood does not recover in one season — it takes 3-7 years depending on the event
severity and whether replanting is required.  This means:

1. **Event-year features are not enough.** A binary frost flag that fires in 2021
   and is zero in 2022-2024 understates the persistent production suppression from
   a frost that killed productive branches.  The model must carry forward a
   **capacity recovery index** that decays as the orchard recovers.

2. **Frost severity tiers must distinguish cherry-kill from wood-kill.** A -2°C
   event kills cherries (one season impact). A -5°C event kills productive branches
   (3-season recovery). A -8°C event kills trees to the rootstock (5-year recovery
   requiring replanting).  All three trigger the same `brazil_frost_event_flag` but
   have categorically different production consequences.

3. **Sustained disease pressure accumulates across seasons.** Black pod for cocoa,
   leaf rust for arabica — high-pressure seasons kill trees, not just reduce annual
   yield.  A rolling multi-season cumulative index captures the accumulated tree
   mortality that a single-season risk composite misses.

**All features below are computable from existing silver data (NASA POWER Tmin
and CHIRPS back to 1981).  No new data sources required.**

---

#### Crop-Stage-Aware Feature Design

**All weather features are anchored to biological crop stages, not calendar months.**

The model target is crop-year production — but the predictive features must be
built from the crop's biological calendar, not raw monthly aggregates.  The same
weather shock has completely different yield consequences depending on which stage
it falls in:

```
planting → emergence → vegetative → critical reproductive stage → grain/fruit fill → maturity → harvest
```

A -2σ moisture anomaly during silking/pollination for corn reduces yield by a
different magnitude than the same anomaly during vegetative growth.  A raw
"Jul–Aug rainfall z-score" averages across both stages and loses the distinction.
Stage-split features let the model learn stage-specific sensitivities — which is
what agronomists have known for decades.

**SHAP interpretability benefit**: stage-split features produce directly
actionable attribution.  "Silking heat stress contributed -0.6" is a statement a
commodity analyst can verify against GAIN reports and NASS crop condition data.
"Jul–Aug z-score contributed -0.4" is not.

**Implementation rule**: every `chirps_precip_z`, `nasa_tmax_anomaly`, and
`drought_consecutive_days` feature is computed over a **named phenological window**,
not a raw calendar range.  The window label encodes the crop stage, not the month.

Example — US corn (Iowa/Illinois/Indiana/Nebraska growing region):

| Stage-aware feature | Window | Replaces |
|---|---|---|
| `us_corn_planting_z` | May 1 – May 31 | — |
| `us_corn_vegetative_z` | Jun 1 – Jun 30 | Merged into generic `us_corn_belt_z` |
| `us_corn_silking_grainf_z` | Jul 1 – Aug 31 | Merged into generic `us_corn_belt_z` |
| `us_silking_heat_stress` | Jul tasseling/silking (existing) | ✓ already stage-aware |

The single `us_corn_belt_z` (May–Aug aggregate) is **replaced** by three stage
features.  Total feature count increases by 2 per region per commodity; model
architecture is unchanged.

**Anomaly detectors are also stage-aware**: the `crop_progress_3sigma_tail_event`
flag fires separately per crop stage — a tail stress event during pollination is
categorically different from one during vegetative growth and the model should
treat them as distinct binary signals.  Each fires its own binary flag + severity
score, all passed into the same Tier 1 model.

**Phenological window definitions** (stored in `configs/sources/crop_calendars.yaml`,
consumed by the feature engineering pipeline):

| Commodity | Region | Planting | Critical reproductive | Grain/fruit fill | Harvest |
|---|---|---|---|---|---|
| corn_cbot | Iowa/IL/IN/NE | May | Jul (silking) | Aug | Sep–Oct |
| soybeans_cbot | Iowa/IL/IN/MN | May | Aug (pod fill) | Aug–Sep | Oct |
| soft_red_winter_wheat | IL/OH/IN | Oct (planting) | Apr–May (jointing) | May–Jun | Jun–Jul |
| arabica_coffee | Minas Gerais | — | Aug–Oct (flowering) | Nov–Mar | May–Sep |
| arabica_coffee | Minas Gerais | — | Jun–Jul (frost risk) | — | — |
| robusta_coffee | Tay Nguyen | — | Apr–Jun (cherry set) | Jul–Sep | Oct–Jan |
| raw_sugar | Brazil CS | Apr (crush start) | — | Apr–Nov | Apr–Nov |
| malaysian_crude_palm_oil | Sabah/Sarawak | — | Year-round (ONI lag 9mo) | — | — |
| canola_ice | SK/AB/MB | May | Jul (pod fill) | Jul–Aug | Aug–Sep |
| south_african_white_maize | Free State/NW | Oct–Dec | Jan–Feb | Feb–Mar | Mar–Apr |

Window definitions shift by latitude and year; the crop calendar YAML stores the
median onset date and the ±2-week uncertainty band used when computing z-score
windows.  The feature engineering pipeline resolves `{stage_window}` labels to
actual date ranges at materialisation time using this lookup.

---

#### Crop Year vs Marketing Year — Alignment Rule

**These are two different timelines and must never be conflated.**

**Crop year** (biological) — the growing season from planting to harvest.
Used as the primary index for Tier 1 origin stress models and as the training
observation key.  Weather features, CONAB surveys, NASS surveys, and NDVI are
all anchored to the crop year.

**Marketing year** (commercial) — the accounting period during which the
harvested crop is sold, exported, and consumed.  PSD, WASDE, WAP, and ESR data
are all in marketing years.  For US corn, the marketing year starts September 1
(after harvest) and ends August 31 the following year.

**The alignment problem**: for US corn, crop year 2024 (planted May, harvested
Oct) feeds into marketing year 2024/25 (Sep 2024 – Aug 2025).  If the feature
engineering pipeline naively joins PSD marketing year 2024/25 data to the
crop year 2024 training observation, it introduces look-ahead bias — that S/U
ratio wasn't known at planting time.  The correct join uses the **prior marketing
year's** S/U ratio (2023/24), which was available before May 2024 planting.

**Alignment rule for feature matrix construction:**

```
For each (commodity, crop_year) training observation:

  Tier 1 features  (weather, CONAB, NASS, NDVI)
    → indexed by crop_year directly
    → feature window = crop stage dates within that crop_year

  Tier 2 S/D features  (PSD su_ratio, WASDE revisions, WAP)
    → join to marketing_year = crop_year_to_mkt_year[commodity][crop_year]
    → use only the vintage available at the START of the growing season
      (i.e. the marketing year that was in-progress or just completed
       when planting decisions were made — never the marketing year
       that begins at harvest)
```

**Commodity-specific crop_year → marketing_year mapping**
(stored in `configs/sources/crop_calendars.yaml` alongside stage windows):

| Commodity | Crop year label | Marketing year label | MKT year for S/D features | Rationale |
|---|---|---|---|---|
| corn_cbot | 2024 (May–Oct) | 2024/25 (Sep–Aug) | 2023/24 | Prior MKT year S/U available at planting (May) |
| soybeans_cbot | 2024 (May–Oct) | 2024/25 (Sep–Aug) | 2023/24 | Same as corn |
| soft_red_winter_wheat | 2024/25 (Oct–Jul) | 2024/25 (Jun–May) | 2023/24 | Prior MKT year S/U available at Oct planting |
| arabica_coffee | 2024/25 (Apr–Mar) | 2024/25 | 2023/24 | Prior MKT year available at Apr flowering window |
| robusta_coffee | 2024 (calendar) | 2024/25 (Oct–Sep) | 2023/24 | Same logic |
| raw_sugar | 2024/25 (Apr–Mar) | 2024/25 | 2023/24 | Prior MKT year available at Apr crush start |
| malaysian_crude_palm_oil | 2024 (calendar) | 2024 (calendar) | 2023 | Aligned calendar years |
| south_african_white_maize | 2024/25 (Oct–Mar) | 2024/25 | 2023/24 | Prior MKT year available at Oct planting |
| canola_ice | 2024 (May–Sep) | 2024/25 (Aug–Jul) | 2023/24 | Prior MKT year available at May planting |

**WASDE revision features are an exception** — they are always point-in-time
and inherently look-ahead-safe by construction.  `wasde_production_revision`
for marketing year 2024/25 at release month M = current_estimate(M) −
prior_estimate(M−1).  Each revision is only available after the WASDE release
date and is stored with its exact release date in PSD silver.  No alignment
correction needed; the `as_of` snapshot already enforces point-in-time
correctness.

**Walk-forward CV enforcement**: the fold boundary is set on `crop_year`.
All feature joins use the mapping above.  The SageMaker Feature Store
point-in-time retrieval API is called with `event_time = crop_year_start_date`
to prevent any future-vintage PSD or WASDE data from leaking into training.

---

**Universal features** — every model uses these:

| Feature | Source | Computation |
|---------|--------|-------------|
| `chirps_precip_z_{region}_{stage}` | silver_weather | Precipitation z-score vs. 30yr norm for a **named phenological stage window** (not a raw calendar range) |
| `nasa_tmax_anomaly_{region}_{stage}` | silver_weather | Daily Tmax deviation from 30yr baseline within the stage window |
| `nasa_tmin_anomaly_{region}_{stage}` | silver_weather | Daily Tmin deviation (frost detection) within the stage window |
| `drought_consecutive_days_{region}_{stage}` | CHIRPS | Consecutive below-20th-percentile days within the stage window |
| `modis_ndvi_z_{region}` | MODIS MOD13A1 bronze | 16-day NDVI composite z-score vs. 2000–2020 crop-calendar baseline per growing region |
| `cpc_soil_moisture_z_{region}` | NOAA CPC bronze | Soil moisture percentile anomaly vs. 1981–2010 climatology; captures pre-season deficit/surplus |
| `faostat_production_trend_dev` | silver_production | Deviation from 10yr linear trend (structural baseline) |
| `faostat_production_yoy` | silver_production | Year-over-year change (momentum) |
| `psd_ending_stock_su_ratio` | silver_sd_balance | Ending stocks / consumption — amplifier for weather signal |
| `psd_su_ratio_yoy_delta` | silver_sd_balance | Su_ratio minus prior year (direction of S/D tightening) |
| `psd_export_flow_z` | silver_sd_balance | Export volumes vs. 5yr seasonal norm — surge signals flush supply or competitive pricing |
| `psd_import_flow_z` | silver_sd_balance | Import volumes vs. 5yr seasonal norm — surge signals domestic deficit coverage; directionally opposite to export surge |
| `crush_margin_index` | Pink Sheet silver | ✅ **Phase 2A complete** — soybeans, soybean_oil, soybean_meal all in silver/pink_sheet (796 rows, 1960–present). Crush margin = (soybean_oil_usd_t + soybean_meal_usd_t blended) − soybeans_usd_t. Computable in feature engineering. |
| `soyoil_palm_premium_z` | Pink Sheet silver | ✅ **Phase 2A complete** — soybean_oil_usd_t and palm_oil_cpo_usd_t both in silver/pink_sheet. |
| `wasde_production_revision` | silver_sd_balance | Current − prior month WASDE production estimate |
| `wasde_stocks_revision` | silver_sd_balance | Current − prior month WASDE ending stocks estimate |
| `wap_nonUS_production_revision` | WAP bronze | Month-over-month change in non-US production estimate |
| `enso_oni_3month_avg` | NOAA ONI (public) | 3-month avg Ocean Niño Index; El Niño >+0.5, La Niña <−0.5 |
| `input_cost_urea_z` | Pink Sheet bronze | Urea price vs. 5yr avg — raw price signal only; economic exposure is commodity- and region-specific (see fertilizer intensity features below) |
| `input_cost_dap_z` | Pink Sheet bronze | DAP price vs. 5yr avg — same caveat |
| `nitrogen_cost_intensity_{commodity}_{region}` | Pink Sheet + crop_calendars.yaml | `urea_z × N_application_rate_index[commodity][region][production_system]` — scales the raw urea signal by the crop's actual nitrogen exposure. High-yield irrigated corn Iowa = 1.0 (reference); rainfed SA maize = 0.35; arabica coffee = 0.05; palm oil = 0.02. Stored as static scalars in `configs/sources/crop_calendars.yaml`. |
| `phosphorus_cost_intensity_{commodity}` | Pink Sheet + crop_calendars.yaml | `dap_z × P_application_rate_index[commodity]` — same scaling for phosphorus; most relevant for wheat, soybeans, canola |
| `crude_oil_brent_z` | EIA / Pink Sheet bronze | Brent crude z-score vs. 5yr avg; drives ethanol demand (corn, sugar) and biodiesel demand (canola, rapeseed, soy oil) |

**Fertilizer intensity design note**: `input_cost_urea_z` and `input_cost_dap_z`
are retained as universal features because they carry a global commodity-market
signal (fertilizer supply shocks affect all crops to some degree).  The
`nitrogen_cost_intensity` and `phosphorus_cost_intensity` features are
**commodity-specific** and replace the raw z-score as the primary input-cost
signal for each model.  XGBoost will see both; SHAP attribution on the
intensity-scaled version is directly interpretable as "$/ha economic pressure."

Fertilizer sensitivity hierarchy by commodity group:

| Sensitivity | Commodities | Application rate note |
|---|---|---|
| **High** | corn (all), wheat (all), rapeseed/canola | 150–220 kg N/ha irrigated; 60–80 kg N/ha rainfed |
| **Medium** | soybeans (N-fixing, but P/K sensitive), sunflower, cotton, raw_sugar | Partial N-fixing or different nutrient timing |
| **Low** | arabica_coffee, robusta_coffee, cocoa | Perennial; multi-year management cycle; short-run urea price insensitive |
| **Near-zero** | malaysian_crude_palm_oil | Perennial tree crop; NPK regime differs entirely from annual row crops |

The `N_application_rate_index` scalars are agronomic constants, not time-series
data — they encode typical practice for the production system dominant in that
region.  They live in `crop_calendars.yaml` alongside the phenological windows
and the crop_year → marketing_year mapping.

**Group-level features:**

*Grains (corn, wheat, soybeans, rice, SA maize)*
| Feature | Source | Computation |
|---------|--------|-------------|
| `fgis_export_pace_z` | AMS Inspections bronze | US cumulative season-to-date export volume vs. USDA forecast pace |
| `fgis_export_weekly_anomaly` | AMS Inspections bronze | Single-week volume vs. 4yr same-week median (off-season surge detector) |
| `esr_commitments_pace_z` | USDA FAS ESR bronze | US cumulative season-to-date export commitments vs. USDA forecast pace (leading; includes unshipped sales) |
| `esr_new_crop_sales_z` | USDA FAS ESR bronze | New-crop forward sales vs. 4yr same-week median; detects early demand surge before FGIS can confirm |
| `psd_corn_soy_area_ratio` | silver_sd_balance | Planted area corn/soy ratio vs. 10yr avg (substitution proxy) |

*Oilseeds (soybeans, rapeseed, canola, palm oil)*
| Feature | Source | Computation |
|---------|--------|-------------|
| `crush_margin_index` | Pink Sheet bronze | (oil + meal blended price) − bean price; when wide → demand pull on beans |
| `soyoil_palm_premium_z` | Pink Sheet bronze | Soybean oil − palm olein spread vs. 3yr avg; substitution trigger above $100/t |
| `biodiesel_mandate_indicator` | Manual config YAML | Binary flag for major mandate changes (Indonesia B35, EU RED III); hand-coded |

*Softs (coffee, cocoa, cotton, sugar, OJ)*
| Feature | Source | Computation |
|---------|--------|-------------|
| `export_registration_z` | ICO/FNC/ICCO bronze | Export registrations vs. seasonal norm; leading indicator for shipments |

---

### Data Coverage and Training Window

#### Prediction Cadence

Two update frequencies:

- **Weekly (in-season)**: Crop Progress, FGIS inspections, UNICA biweekly, MPOB monthly trigger a Tier 1 refresh during the critical growing window.
- **Monthly (off-season)**: WASDE, PSD, Pink Sheet drive Tier 2 balance sheet updates on WASDE release day (~10th of each month).

The **target variable is annual** (`production_quantity` per crop year). Higher-frequency inputs are aggregated into growing-season summary statistics — one row per `country × commodity × crop_year`:

| Raw cadence | Aggregation into annual training feature |
|-------------|------------------------------------------|
| Daily CHIRPS / POWER | Growing-window z-score (e.g., "Apr–Jun rainfall z" = one scalar per crop year) |
| Weekly Crop Progress | Min GE% in season; week of fastest decline; first week below 60% threshold |
| Monthly WASDE | Revision value at marketing-year months 2, 5, and 8 (three lagged snapshots) |
| Bimonthly CONAB | Final survey revision + consecutive-revision streak count |
| Weekly FGIS | Cumulative pace z-score at marketing-year weeks 8, 16, and 24 |
| Weekly ESR | Commitments pace z-score at marketing-year weeks 8, 16, and 24; new-crop forward sales z at week 1 of new-crop window |
| Biweekly UNICA | ATR z-score at fortnights 4 and 8; ethanol mix ratio at fortnight 6 |
| Monthly MPOB | M-o-M z-score at months 3, 6, and 9 of calendar year |

#### Source Coverage

| Source | Raw cadence | Coverage | Notes |
|--------|-------------|----------|-------|
| FAOSTAT QCL | Annual | 1961–2023 | Longest baseline; 10yr trend anchor |
| USDA PSD | Annual / mktg year | ~1960–present | ✅ Silver; Full S/U ratio history |
| NOAA ONI | Monthly | 1950–present | ✅ **Silver complete** — raw/weather/source=noaa_oni/oni.ascii.txt + bronze + silver/weather/source=noaa_oni/part-000.parquet (915 rows, 1950–present). `enso_oni_3month_avg` universal feature unblocked. |
| World Bank Pink Sheet | Monthly | 1960–present | ✅ Silver; Input costs + price history |
| CHIRPS v3 | Daily | **1981–present** | Hard lower bound for all weather features |
| NASA POWER | Daily | **1981–present** | Same lower bound as CHIRPS |
| MODIS NDVI (MOD13A1) | 16-day composite | **2000–present** | ✅ Silver (9,723 files); ~26 seasons; 500m pre-computed NDVI |
| NOAA CPC Soil Moisture | Daily | **1948–present** | ✅ Silver (133,774 files); ~78 seasons; model-derived (leaky bucket), 0.5° |
| WASDE (digital PDF) | Monthly | **2000–present** | ✅ text layer extracted (pdfplumber); bronze structured parse pending |
| WASDE (TXT) | Monthly | **1995–1999** | ✅ text layer extracted (plain parse); 5 additional years |
| WASDE (scanned PDF) | Monthly | 1973–1994 | ✅ Textract OCR complete; text layer extracted; 22 additional years |
| WAP Table 01 (bronze) | Monthly | **2002–present** | ✅ pdfplumber Table 01 bronze complete; 247 files; ✅ Silver (`silver/wap_table01/part-000.parquet` + `silver/wap_table01_revisions/part-000.parquet`); `wap_nonUS_production_revision` feature ready |
| WAP (pre-2002 text) | Monthly | **1988–2001** | ✅ text layer only (pdfplumber); no Table 01 format exists in this era; GraphRAG only |
| NASS Crop Progress | Weekly (in-season) | **1986–present** | ✅ Silver (279 files, `silver/nass_crop_progress/`); US crops: corn_cbot, soybeans_cbot, cotton, SRW/HRS wheat, rough_rice_cbot; 1979–2025 |
| FGIS Export Inspections | Weekly | **1983–present** | ~43 seasons; gold-standard physical volumes; ✅ Bronze (43 Parquet files by CY); ✅ Silver (`silver/fgis/` by leviathan_slug × marketing_year; corn_cbot, soybeans_cbot, SRW/HRW/HRS wheat; 1982/83–2024/25) |
| USDA FAS ESR | Weekly | **~1990–present** | ✅ Raw (370), ✅ Bronze (740), ✅ Silver (370, `silver/production/source=usda_esr/`); ~36 seasons; forward commitments; Thursday DAG live |
| ICCO Grindings | Quarterly | ~1980–present | ~45 years; cocoa only |
| FNC Colombia | Monthly | **1956–present** (production); 2002–present (area) | ✅ Silver (148 files, `silver/fnc_colombia/`); monthly 1913–2026, area_department 2002–2025, exports_port_type 2017–2026 |
| NASS Citrus Monthly | Monthly | **1996–present** | ~29 seasons; FCOJ only |
| UNICA (annual totals) | Annual per season | **1980/81–2020/21** | **41 seasons**; ✅ Bronze (S3, 41 harvest years × HTML); ✅ Silver (`silver/unica_annual_state/part-000.parquet` — 1,107 rows, 27 state/region rows × 41 seasons, 8 cols) |
| UNICA (biweekly, in-season) | Biweekly | **2022/23–present** | 3 seasons ⚠; 2021/22 permanently unavailable |
| CONAB surveys | Bimonthly (~5/season) | **2005–present** | ~20 marketing years; config `historical_depth: 2005` |
| MPOB (HTML monthly) | Monthly | **2017–present** | ~9 years; full Sabah/Sarawak regional detail; ~4 OOS seasons with 5yr min train; ✅ Bronze (annual_summary 2017–2026, 10 files); ✅ Silver (`silver/mpob/part-000.parquet`) |
| MPOB (overview PDFs) | Annual summary | **2010–present** | ~16 years; national totals only, no monthly detail; ~6 OOS seasons for annual features; ✅ Bronze (overview_pdf 2011–2016, 6 files); ✅ Silver (`silver/mpob_annual/part-000.parquet`); ✅ Text layer (2010–2016) |
| AMS Cotton Classing | Weekly (in-season) | **1986–present** | Annual quality PDFs ingested; weekly tenderable % files not yet |
| SAGIS CEC (crop estimate) | Bimonthly | **1999–present** | ~27 seasons ✓; 374 files in S3; WordPress archive fully ingested |
| SAGIS Weekly Deliveries (maize) | Weekly | **2006/07–present** | ~20 seasons ✓; 2006/07 is the practical start of structured weekly deliveries files |

#### Missing Values

All sources contribute `NaN` for any crop year where data is unavailable — whether the source didn't exist yet, had a structural gap, or reporting was delayed. **No imputation is applied.** XGBoost learns the optimal branch direction for `NaN` at each split natively. Imputing with median/mode would inject signal from known values into years where data was genuinely absent, which introduces look-ahead bias when the gap falls inside the backtest window.

For the most critical commodity-specific features, add a companion binary `{source}_available` flag (e.g., `conab_available`, `mpob_monthly_available`). This gives the model an explicit signal that missingness is structural rather than inferring it from the NaN pattern alone.

#### Look-Ahead Bias Prevention

All statistics used to construct features must be computable using **only data available at the point-in-time being forecast**. Violations are subtle:

| Feature type | Risk | Rule |
|-------------|------|------|
| CHIRPS / POWER z-scores | Full-sample mean contaminates past years with future observations | Use fixed **1981–2010 WMO climatological baseline** — a published standard, not recomputed from the training set |
| FGIS / WASDE / CONAB revision z-scores | Baseline includes future revisions if computed globally | **Expanding-window only**: mean/std of all years ≤ T at fold time T |
| Seasonal norms (e.g., FGIS 4yr same-week median) | Future seasons inflate the "normal" level | Re-derive inside each walk-forward fold using years ≤ T only |
| Feature scaling / standardization | `StandardScaler` fit on full dataset leaks future variance into past | Fit scaler **inside** each walk-forward fold on training years; apply to test year |
| WASDE revision (current − prior month) | Point-in-time by construction | Safe as-is |
| CONAB revision streak | Point-in-time by construction | Safe as-is |

```python
for fold_end_year in range(min_train_end, max_year):
    train = df[df.crop_year <= fold_end_year]
    test  = df[df.crop_year == fold_end_year + 1]

    # ALL transformers fitted on train only — never touch test year
    scaler.fit(train[features])
    expanding_baselines = train[revision_cols].agg(["mean", "std"])

    X_train = transform(train, scaler, expanding_baselines)
    X_test  = transform(test,  scaler, expanding_baselines)  # train-fitted params only

    model.fit(X_train, train[target])
    preds[fold_end_year + 1] = model.predict(X_test)
```

#### Walk-Forward CV Feasibility

The constraint is not missingness (handled natively by XGBoost) but how many **complete OOS seasons** exist to validate each commodity's key features:

| Commodity | Key commodity-specific feature | Available from | OOS seasons (5yr min train) |
|-----------|-------------------------------|----------------|-----------------------------|
| corn_cbot / soybeans / wheat | NASS GE%, FGIS pace z | 1986 / 1983 | ~26 ✓ |
| raw_sugar | UNICA annual totals (silver) | **1980/81** | **~36 ✓** |
| frozen_orange_juice | NASS Citrus revision surprise | 1996 | ~24 ✓ |
| arabica_coffee | CONAB revision surprise | 2005 | ~15 ✓ |
| palm_oil | MPOB monthly HTML (Sabah/Sarawak) | 2017 | ~4 ⚠ (monthly features); ~6 ⚠ (annual features via overview PDFs) |
| south_african_maize | SAGIS CEC | 1999 | **~21 ✓** — archive fully ingested; previously recorded as 2022 (ingestion-start date, not data-start date) |
| south_african_maize | SAGIS Weekly maize deliveries | 2006/07 | **~14 ✓** — 2006/07 is earliest structured weekly file; previously recorded as 2022 |
| raw_sugar (in-season signals) | UNICA biweekly ATR / ethanol mix | 2022/23 | insufficient ⚠⚠ — complete biweekly seasons: 2022/23 (3 files), 2023/24 (9), 2024/25 (17), 2025/26 (18); 2021/22 permanently missing |

Features marked ⚠⚠ are included for **real-time inference only**. Their SHAP attributions should not be cited as validated predictors until sufficient backtest history accumulates (~2027 for UNICA biweekly).

**Note**: SAGIS was previously flagged ⚠⚠ based on ingestion-start date (2022). S3 audit confirmed the full archive is ingested: CEC back to 1999 (374 files), weekly maize deliveries back to 2006/07. SAGIS is now fully sufficient for walk-forward CV.

---

### Per-Commodity Feature Specifications

---

#### Coffee — arabica_coffee / brazilian_arabica_coffee / robusta_coffee

**Origins modeled**: Brazil (Minas Gerais, São Paulo, Espírito Santo, Bahia, Rondônia),
Colombia (Huila, Nariño, Antioquia), Ethiopia (Sidama, Yirgacheffe), Vietnam (Tay Nguyen),
Indonesia (North Sumatra), Honduras, Guatemala, Uganda

| Feature | arabica | br_arabica | robusta | Source | Notes |
|---------|:-------:|:----------:|:-------:|--------|-------|
| `biennial_cycle_phase_brazil` | ✓ | ✓ | — | CONAB lagged production | Binary on/off year; strongest single feature for Brazilian arabica |
| `flowering_stress_brasil` | ✓ | ✓ | — | CHIRPS Aug–Oct Brazil | Flowering window moisture deficit → yield miss at next harvest |
| `brazil_frost_event_flag` | ✓ | ✓ | — | NASA POWER Tmin | Tmin < 4°C in Sul de Minas / Cerrado Mineiro, June–July window — binary event detector |
| `brazil_frost_severity_score` | ✓ | ✓ | — | NASA POWER Tmin | Continuous severity: `max(0, 4 − Tmin_min) × frost_duration_hours / 24`. Encodes how far below 4°C and for how long. Thresholds: < −2°C = cherry kill (1 season); < −5°C = branch kill (3 seasons); < −8°C = tree/rootstock kill (5 seasons). Computable from existing NASA POWER silver (1981–present). |
| `brazil_frost_capacity_recovery` | ✓ | ✓ | — | NASA POWER Tmin (computed) | Decaying productive capacity suppression index. Carries forward the impact of past frost events weighted by severity and decay rate per damage tier. `recovery[t] = Σ_{k=1}^{6} severity_score[t-k] × exp(−k / recovery_horizon[tier[t-k]])` where recovery_horizon = {cherry_kill: 1, branch_kill: 3, tree_kill: 5}. Zero in years with no recent frosts. Near 1.0 in 1995–1999 (post-1994 severe frost). Near 0.3–0.5 in 2022–2024 (post-2021 frost). Computable from NASA POWER silver back to 1981 — no new data required. |
| `conab_revision_surprise` | ✓ | ✓ | — | CONAB bronze | Survey N − survey N−1; highest-conviction Brazil coffee feature |
| `conab_revision_streak` | ✓ | ✓ | — | CONAB bronze | ≥3 consecutive revisions same direction = high-conviction signal |
| `fnc_export_pace_z` | ✓ | — | — | FNC Excel bronze | Colombia monthly exports vs. seasonal norm |
| `colombia_flowering_chirps` | ✓ | — | — | CHIRPS | Main crop Apr–Jun + mid-crop Nov–Jan flowering stress |
| `leaf_rust_risk_composite` | ✓ | ✓ | — | CHIRPS + POWER | Temp 15–25°C × humidity >80% = *hemileia vastatrix* pressure proxy |
| `vietnam_wet_season_z` | — | — | ✓ | CHIRPS Tay Nguyen | Apr–Sep rainfall z-score; cherry-set window |
| `vietnam_harvest_rain_flag` | — | — | ✓ | CHIRPS + POWER | Oct–Dec excess moisture → fungal risk during cherry development |
| `enso_oni_vietnam_lag6` | — | — | ✓ | NOAA ONI | ONI lagged 6mo; El Niño → drought risk in Tay Nguyen |
| `indonesia_sumatra_chirps` | — | — | ✓ | CHIRPS | North Sumatra (Lake Toba region) stress |
| ⚠ `brl_usd_pct_change_90d` | ✓ | ✓ | — | FRED | ✅ **Phase 2B complete** — silver/fred_fx/part-000.parquet (5,508 rows, 2005–present). brl_usd_pct_change_90d computable. BRL depreciation → coffee exporters delay shipments → reduced near-term physical availability. |

**Spread signal (arabica/robusta)**: `conab_revision_surprise` + `brazil_frost_event_flag`
diverging from `vietnam_wet_season_z` + `enso_oni_vietnam_lag6` is the primary driver.
When ENSO fires simultaneously for both (La Niña → Brazil dry flowering, El Niño → Vietnam
drought), the multi-origin anomaly detector flags low spread conviction.

---

#### Cocoa — cocoa

**Origins**: Côte d'Ivoire (42%), Ghana (17%), Indonesia (13%), Ecuador, Brazil, Cameroon

| Feature | Source | Notes |
|---------|--------|-------|
| `harmattan_intensity_index` | CHIRPS + POWER | NE dry wind intensity Nov–Feb in Côte d'Ivoire; pod desiccation and flower kill during main-crop set |
| `black_pod_risk_composite` | CHIRPS + POWER | Temp 18–26°C × humidity >90% in Oct–Feb main crop → *Phytophthora* pressure proxy — single-season signal |
| `cocoa_blackpod_cumulative_3yr` | CHIRPS + POWER (computed) | Rolling 3-season sum of `black_pod_risk_composite`. Sustained high-pressure seasons kill trees, not just reduce annual yield — accumulated tree mortality suppresses productive capacity for years beyond the high-pressure episode. `cumulative[t] = Σ_{k=0}^{2} black_pod_risk_composite[t-k]`. Computable from existing CHIRPS + NASA POWER silver back to 1981 — no new data required. |
| `west_africa_main_crop_z` | CHIRPS | Sep–Jan rainfall z-score, southern Côte d'Ivoire latitudes |
| `west_africa_mid_crop_z` | CHIRPS | Apr–Jun rainfall z-score (lighter crop but margin-sensitive) |
| `icco_grindings_trend_dev` | ICCO bronze | Quarterly grindings vs. 3yr trend; demand side unique to cocoa |
| ⚠ `grindings_eu_z` | ICCO bronze | **Phase 3 — ICCO QBCS JSON has world totals only; EU breakdown requires ICCO PDF bulletin table extraction (not yet built). World grindings trend (`icco_grindings_trend_dev`) is computable now and provides the primary cocoa demand signal.** |
| `enso_westAfrica_lag9` | NOAA ONI | El Niño 9mo lag → dry harmattan → yield shock; most reliable ENSO-crop link after palm oil |
| `indonesia_sulawesi_chirps` | CHIRPS | Sulawesi region stress |

**Key insight**: Cocoa is the only commodity where demand (grindings) is as important as
supply. A supply shock on tight grindings = exponential price response. A supply shock on
weak grindings = muted. The model always evaluates both legs of the balance sheet. The
`icco_grindings_trend_dev` feature has no analogue in any other commodity model.

---

#### Cotton — cotton

**Origins**: USA (Delta, Southeast, Plains), India (Maharashtra, Gujarat), China (Xinjiang),
Brazil (Mato Grosso), Pakistan

| Feature | Source | Notes |
|---------|--------|-------|
| `nass_ge_pct_cotton` | silver_crop_progress | Weekly GE% during square/boll development (Jun–Sep) |
| `nass_ge_surprise_cotton` | silver_crop_progress | Current week vs. 5yr same-week average |
| `degree_days_accumulated` | NASA POWER | Heat unit accumulation from planting; predicts harvest calendar shift |
| `cotton_tenderable_pct` | AMS Cotton bronze | Share meeting CBOT delivery spec (color, staple). **Annual only** — computable from AMS Annual Quality silver (one value per season, 1986–2025). Weekly in-season version requires AMS weekly classing files which are not accessible. |
| ~~`micronaire_pct_premium_grade`~~ | ~~AMS Cotton bronze~~ | **REMOVED** — requires AMS weekly classing data which does not exist in any accessible format. No viable data path. |
| `india_monsoon_onset_lag` | CHIRPS + IMD proxy | Days of delay from normal June 1 onset; each week late → ~3% India yield drag |
| `india_kharif_chirps_z` | CHIRPS | Jun–Sep rainfall z-score for Gujarat/Maharashtra |
| `brazil_cerrado_cotton_z` | CHIRPS | Dec–Feb Mato Grosso cotton stress window |
| `us_abandonment_rate_z` | NASS bronze | Harvested/planted area ratio vs. 5yr avg; financial abandonment signal |
| ~~`fgis_cotton_export_z`~~ | ~~AMS Inspections bronze~~ | **REMOVED** — FGIS silver covers corn, soybeans, and wheat only. Cotton inspection data is not in the FGIS backfill files ingested. No viable data path without a separate USDA cotton inspections ingest. |

**Key anomaly**: Micronaire outside 3.5–4.9 → non-tenderable. Tenderable supply can
fall 15–25% even in a normal yield year. Model production AND tenderable fraction
separately — they can diverge dramatically in drought years that produce short-staple,
high-micronaire cotton.

---

#### Raw Sugar / White Sugar — raw_sugar / white_sugar

**Origins**: Brazil CS region, Brazil NE, India (Maharashtra, Uttar Pradesh), Thailand, Australia, EU

| Feature | Source | Notes |
|---------|--------|-------|
| `unica_tch_weekly` | UNICA bronze | Tonnes of cane per hectare (in-season yield indicator) |
| `unica_atr_weekly` | UNICA bronze | Recoverable sugar content; declines with cold/drought stress |
| `unica_ethanol_sugar_mix` | UNICA bronze | Flex-mill allocation to ethanol vs. crystal sugar; shifts export balance |
| `unica_cumulative_vs_prior_yr` | UNICA bronze | Season-to-date cane crushed vs. same date prior year; pace signal |
| `brazil_cs_crush_window_z` | CHIRPS | Apr–Nov Brazil CS rainfall; excess rain delays crushing → pace shortfall |
| `india_monsoon_sugar_z` | CHIRPS | Jun–Oct Maharashtra/UP; monsoon quality drives crushing volume Dec–Apr |
| `brazil_cane_atr_stress` | NASA POWER | Tmax > 35°C in Feb–Mar during sugar accumulation phase → ATR drop |
| ⚠ `white_raw_premium_z` | Pink Sheet bronze | ✅ **Phase 2A complete** — raw_sugar_world_usd_t in silver/pink_sheet. White − raw price premium vs. 5yr avg; refinery availability signal. |
| `thailand_harvest_window_z` | CHIRPS Thailand | Nov–Mar wet-season residual; wet soils delay cane transport |
| ⚠ `ethanol_sugar_parity_ratio` | UNICA bronze + Pink Sheet | ✅ **Phase 2A complete** — UNICA bronze has ethanol price; raw_sugar_world_usd_t now in silver/pink_sheet. Hydrous ethanol / raw sugar price ratio; >0.70 → mills pivot to ethanol. |

**Unique feature — ethanol-sugar parity flip**: When Brazilian hydrous ethanol > 70% of
raw sugar parity (BRL-adjusted), flex mills pivot to ethanol mid-season. Raw sugar export
volume drops even with normal cane crush. `ethanol_sugar_parity_ratio` captures this
within-season demand switch before it appears in UNICA monthly summaries.

**White/raw spread**: `white_raw_premium_z` divergence signals refinery margin squeeze.
Extreme raw discount (white premium > historical 90th pct) = refinery capacity shortage;
sell raw/buy white. Both contracts share all other features — the premium z-score is the
only asymmetric signal.

---

#### Corn — corn_cbot / campinas_corn_reference_bmf / french_maize_matif

**Origins**: USA (Iowa, Illinois, Indiana, Nebraska), Brazil 1st crop (RS, SC, PR),
Brazil safrinha / 2nd crop (Mato Grosso, Goiás, PR), Argentina (Córdoba, Santa Fe),
France/EU (northern France, Germany)

| Feature | CBOT | Campinas | FR maize | Source | Notes |
|---------|:----:|:--------:|:--------:|--------|-------|
| `nass_ge_pct_corn` | ✓ | — | — | silver_crop_progress | Weekly GE% Jun–Sep |
| `us_silking_heat_stress` | ✓ | — | — | NASA POWER | Degree-days > 32°C during tasseling/silking (Jul); most yield-sensitive US window |
| `us_corn_planting_z` | ✓ | — | — | CHIRPS IA/IL/IN/NE | May precipitation z-score (planting stage) |
| `us_corn_vegetative_z` | ✓ | — | — | CHIRPS IA/IL/IN/NE | Jun precipitation z-score (vegetative stage) |
| `us_corn_silking_grainf_z` | ✓ | — | — | CHIRPS IA/IL/IN/NE | Jul–Aug precipitation z-score (silking + grain fill) — replaces generic May–Aug aggregate |
| `brazil_safrinha_plant_delay` | — | ✓ | — | CHIRPS + CONAB | Days of delay from ideal Oct–Dec planting window; yield penalty per week |
| `brazil_safrinha_z` | — | ✓ | — | CHIRPS MT/GO/PR | Feb–May growing season stress |
| ⚠ `brl_usd_pct_change_90d` | — | ✓ | — | FRED | ✅ **Phase 2B complete** — brl_usd_pct_change_90d in silver/fred_fx. BRL depreciation → Brazilian farmers withhold corn sales → artificial tightness in global corn basis. |
| `argentina_pampas_z` | ✓ | — | — | CHIRPS Córdoba/SF | Nov–Feb z-score; Argentina = #3 corn exporter |
| `france_spring_frost_flag` | — | — | ✓ | NASA POWER | Tmin < 0°C in Apr–May (emergence → frost kill) |
| `france_summer_heat_drought` | — | — | ✓ | CHIRPS + POWER | Jun–Aug heat + drought composite (2003/2022-style event) |
| `fgis_corn_export_z` | ✓ | — | — | AMS Inspections bronze | US cumulative corn export pace vs. USDA forecast |
| `sagis_sa_maize_delivery_z` | — | — | — | SAGIS Weekly bronze | SA maize producer deliveries vs. seasonal norm |
| `corn_soy_planted_ratio` | ✓ | — | — | NASS bronze | Area ratio vs. 10yr avg; substitution signal |

**Spread signal (CBOT/Campinas)**: `us_corn_silking_grainf_z` + `nass_ge_pct_corn` diverging
from `brazil_safrinha_plant_delay` + `brazil_safrinha_z` drives the spread.
`brl_usd_pct_change_90d` amplifies or dampens the basis move — BRL depreciation encourages
Brazilian farmers to hold corn (inflating USD-denominated revenue), reducing near-term
export availability and tightening the basis. Spread widens when US stress fires; narrows
when Brazil safrinha delay fires (Brazil will export less, taking pressure off CBOT).

---

#### South African Maize — south_african_white_maize_jse / south_african_yellow_maize_jse

**Origins**: South Africa (Free State, North West, Mpumalanga, Limpopo)

| Feature | white | yellow | Source | Notes |
|---------|:-----:|:------:|--------|-------|
| `sagis_weekly_deliveries_z` | ✓ | ✓ | SAGIS Weekly bronze | Producer deliveries vs. seasonal norm |
| `sagis_cec_production_revision` | ✓ | ✓ | SAGIS CEC bronze | Monthly SA crop estimate revision (SA WASDE equivalent) |
| `sa_summer_rainfall_z` | ✓ | ✓ | CHIRPS | Nov–Mar Free State/NW; SA maize is dryland summer-rainfall crop |
| `sa_planting_window_z` | ✓ | ✓ | CHIRPS | Oct–Dec planting window moisture; delayed planting = yield loss |
| `sa_export_pace_z` | ✓ | ✓ | SAGIS Weekly bronze | Cumulative SA export registrations vs. seasonal norm |
| ⚠ `white_yellow_spread_z` | ✓ | ✓ | JSE price data | **Phase 2 — requires JSE white/yellow maize futures price data. SAGIS has production/delivery data but not JSE prices. No viable data path until price series ingested.** |

**Unique quality spread**: White maize = human food (mealie meal, staple); yellow = feed
(poultry/pig). In drought years, food-security buying pushes white maize premium to extreme
levels. Both contracts share all origin weather features — the `white_yellow_spread_z` is the
only asymmetric signal. SAGIS CEC is the SA WASDE; its revision surprise is the Tier 2 driver.

---

#### Soybeans / Meal / Oil — soybeans_cbot / soybeans_no_1_dce / soybeans_no_2_dce / soybean_meal_cbot/dce / soybean_oil_cbot/dce

**Origins**: USA (Iowa, Illinois, Indiana, Minnesota), Brazil (Mato Grosso, Paraná, RS, GO),
Argentina (Buenos Aires, Córdoba, Santa Fe, Entre Ríos)

| Feature | US | Brazil | Argentina | Source | Notes |
|---------|:--:|:------:|:---------:|--------|-------|
| `nass_ge_pct_soy` | ✓ | — | — | silver_crop_progress | Weekly GE% Jul–Sep |
| `us_pod_fill_stress` | ✓ | — | — | NASA POWER | Heat units > 30°C in Aug pod-fill; most yield-sensitive US soy window |
| `brazil_mato_grosso_z` | — | ✓ | — | CHIRPS | Nov–Mar planting/growing season |
| `brazil_parana_rs_z` | — | ✓ | — | CHIRPS | Dec–Mar southern Brazil; La Niña = drought risk for PR/RS |
| `la_nina_brazil_flag` | — | ✓ | — | NOAA ONI | ONI < −0.5 in Dec–Feb → dry PR/RS soy; strongest ENSO-soy link |
| `argentina_pampas_nov_mar_z` | — | — | ✓ | CHIRPS Córdoba/BA | Nov–Mar z-score |
| `argentina_la_nina_flag` | — | — | ✓ | NOAA ONI | La Niña → dry Pampas; 2008/2012/2018/2022 precedents |
| `fgis_soy_export_z` | ✓ | — | — | AMS Inspections bronze | Cumulative US soy export pace vs. USDA forecast |
| `brazil_harvest_port_delay` | — | ✓ | — | CHIRPS Santos/Paranaguá | Jan–Mar excess rainfall → road deterioration → export delay → basis widens |
| ⚠ `crush_margin_us` | ✓ | — | — | Pink Sheet bronze | ✅ **Phase 2A complete** — soybeans_usd_t, soybean_oil_usd_t, soybean_meal_usd_t in silver/pink_sheet. (meal + oil blended) − bean price; demand pull. |
| ⚠ `crush_margin_china_proxy` | — | ✓ | ✓ | Pink Sheet bronze | ✅ **Phase 2A complete** — soybeans_usd_t, soybean_oil_usd_t, soybean_meal_usd_t in silver/pink_sheet. Chinese crush margin proxy = blended (oil+meal) − bean price. Drives Argentine/Brazilian import demand. |
| ⚠ `ars_usd_pct_change_90d` | — | — | ✓ | FRED / BCRA | ✅ **Phase 2B complete** — ars_usd_pct_change_90d in silver/fred_fx (2005–2022; NaN during 2019-present capital controls when official rate was frozen — expected gap). Mechanism: devaluation → farmers withhold beans → artificial supply tightness. |
| ⚠ `brl_usd_pct_change_90d` | — | ✓ | — | FRED | ✅ **Phase 2B complete** — brl_usd_pct_change_90d in silver/fred_fx. BRL depreciation → farmers hold ~30% of annual crop → drives CBOT/Paranaguá basis. |

**Argentine withheld supply mechanism**: Argentina is the #1 global soy meal exporter (~50% of
trade). When ARS is depreciating rapidly, Argentine farmers treat on-farm grain silos as a
USD savings account and delay sales. This creates artificial tightness in CBOT soybeans and
CME soy meal that is NOT explained by weather or FAOSTAT production data. The mechanism
reverses in discrete, volume-heavy windows when the government offers preferential FX rates
("Soy Dollar" windows). `ars_usd_pct_change_90d` captures the incentive to withhold;
a sharp negative reversal (peso stabilizes / appreciates) is the unlock signal.

**Three-leg spread architecture** (CBOT/DCE arbitrage): Compare `brazil_mato_grosso_z` +
`brazil_harvest_port_delay` vs. `nass_ge_pct_soy` + `us_pod_fill_stress`. Brazil stress →
DCE tightens; US clean → CBOT/DCE spread narrows (US premium collapses). `crush_margin_china_proxy`
is the common factor that can widen both contracts simultaneously — when it fires, spread
conviction drops and the multi-origin detector should flag it.

---

#### Palm Oil — malaysian_crude_palm_oil_cme / palm_olein_dce

**Origins**: Malaysia (Sabah, Sarawak, Peninsular), Indonesia (Sumatra, Kalimantan)

| Feature | Source | Notes |
|---------|--------|-------|
| `mpob_production_mom_z` | MPOB bronze | Monthly production vs. same month 3yr avg |
| `mpob_stocks_z` | MPOB bronze | End-month stocks vs. 3yr same-month avg |
| `mpob_exports_mom_z` | MPOB bronze | Monthly exports vs. seasonal norm |
| `mpob_ffb_yield` | MPOB bronze | Fresh fruit bunch yield per hectare; early yield alert |
| `enso_oni_palm_lag9` | NOAA ONI | **ONI lagged 9 months → Sabah/Sarawak yield impact; strongest and most mechanistically reliable ENSO-crop link in the entire dataset** |
| `sabah_sarawak_chirps_z` | CHIRPS | Monthly rainfall z-score; excess = flood damage; deficit = drought stress |
| `indonesia_kalimantan_chirps` | CHIRPS | Kalimantan rainfall; Indonesia = 55% of world production |
| `biodiesel_b35_consumption_adj` | Manual config YAML | Indonesia B35 mandate domestic consumption adjustment; hand-coded policy step |
| `soyoil_palm_premium_z` | Pink Sheet bronze | Soyoil − palm olein premium vs. 3yr avg; > $100/t = substitution trigger |
| ⚠ `mpoc_competitive_price_ratio` | MPOC bronze | ✅ **Superseded by Phase 2A** — palm_oil_cpo_usd_t and soybean_oil_usd_t now in silver/pink_sheet. `soyoil_palm_premium_z` from Pink Sheet covers the competitive price signal; dedicated MPOC bronze not needed. |

**Most predictable ENSO response in the model universe**: El Niño reduces rainfall in
Borneo 9 months before yield impact appears in MPOB data. The chain is:
ONI > +0.5 → Sabah/Sarawak CHIRPS anomaly → MPOB FFB yield drop → MPOB production miss.
Each stage is observable before the next. When El Niño onset is confirmed, publish the
expected MPOB yield hit before MPOB reports it — this is the palm oil model's edge.

---

#### Wheat — soft_red_winter_cbot / hard_red_winter_kcbt / hard_red_spring_mgex / french_wheat_matif

**Origins**: USA (Kansas/OK/TX = HRW; Dakotas/MN = HRS; IL/OH/IN = SRW),
France/EU (northern France, Germany, Poland), Russia (Krasnodar, Rostov), Ukraine

| Feature | SRW | HRW | HRS | FR wheat | Source | Notes |
|---------|:---:|:---:|:---:|:--------:|--------|-------|
| `nass_ge_pct_winter_wheat` | ✓ | ✓ | — | — | silver_crop_progress | Weekly GE% Mar–Jun |
| `nass_ge_pct_spring_wheat` | — | — | ✓ | — | silver_crop_progress | Weekly GE% Jun–Aug |
| `us_winter_wheat_dormancy_z` | ✓ | ✓ | — | — | CHIRPS | Oct–Feb soil moisture at dormancy entry |
| `us_winter_wheat_jointing_z` | ✓ | ✓ | — | — | CHIRPS | Mar–Apr jointing/heading critical window |
| `us_spring_wheat_z` | — | — | ✓ | — | CHIRPS Dakotas/MN | Jun–Aug moisture; ND spring wheat is high-protein |
| `france_heading_z` | — | — | — | ✓ | CHIRPS N.France | Apr–Jun heading/grain fill z-score |
| `france_harvest_quality_flag` | — | — | — | ✓ | CHIRPS + POWER | Excess rain at harvest (Jul) → Hagberg falling number failure → milling wheat reclassified as feed (-$40/t) |
| `black_sea_chirps_z` | ✓ | ✓ | ✓ | ✓ | CHIRPS Krasnodar/Rostov | Apr–Jun; Russia = #1 wheat exporter; all wheat contracts react |
| `russia_export_quota_flag` | ✓ | ✓ | — | ✓ | Manual config YAML | Binary; Russian export quota/ban; hand-coded from policy announcements |
| `fgis_wheat_export_z` | ✓ | ✓ | ✓ | — | AMS Inspections bronze | US cumulative wheat export pace vs. USDA forecast |
| ⚠ `hardwheat_softwheat_premium_z` | ✓ | ✓ | — | ✓ | Pink Sheet bronze | ✅ **Phase 2A complete** — wheat_us_hrw_usd_t and wheat_us_srw_usd_t in silver/pink_sheet. HRW − SRW protein premium vs. 3yr avg. |

**French wheat unique mechanism** (`france_harvest_quality_flag`): France exports ~30% of its
crop. In wet-harvest years, a significant share reclassifies from milling to feed wheat — a
$30–60/t discount. This event moves MATIF independent of any yield change and diverges MATIF
from CBOT, creating a temporary basis trade opportunity. The flag is the asymmetric signal.

---

#### Rapeseed / Canola — french_rapeseed_matif / canola_ice / rapeseed_oil_zce / rapeseed_meal_zce

**Origins**: France/EU (France, Germany, Poland, Ukraine), Canada (Saskatchewan, Alberta, Manitoba),
China (Yangtze basin)

| Feature | MATIF | ICE | ZCE | Source | Notes |
|---------|:-----:|:---:|:---:|--------|-------|
| `france_rapeseed_winter_z` | ✓ | — | — | CHIRPS N.France | Oct–Feb winter establishment moisture |
| `france_rapeseed_flowering_z` | ✓ | — | — | CHIRPS + POWER | Apr–May flowering; frost at −3°C kills flowers (no second chance) |
| `eu_pollen_beetle_risk` | ✓ | — | — | NASA POWER | Spring temp accumulation > 8°C base; pollen beetle emergence timing (crop damage proxy) |
| `canada_canola_z` | — | ✓ | — | CHIRPS SK/AB/MB | Jun–Aug pod-fill moisture |
| `canada_canola_heat_dome_flag` | — | ✓ | — | NASA POWER | **Tmax > 35°C for ≥3 consecutive days in Jul; binary extreme-event flag** (2021: −35% yield in one month) |
| `canada_harvest_quality_z` | — | ✓ | — | CHIRPS Sep–Oct | Late-season moisture; wet harvest → green seed → grade downgrade |
| `china_rapeseed_yangtze_z` | — | — | ✓ | CHIRPS | Winter crop Feb–May flowering window |
| `eu_biodiesel_demand_flag` | ✓ | — | ✓ | Manual config YAML | EU RED III mandate level; rapeseed oil = ~60% of EU biodiesel feedstock |
| ⚠ `crush_margin_rapeseed_eu` | ✓ | — | — | Pink Sheet bronze | ✅ **Phase 2A complete** — rapeseed_oil_usd_t in silver/pink_sheet (from 2002). EU crush margin; drives processor demand for seed. |

**Canada heat dome — tail risk design**: The 2021 event cut Canadian canola yield by 35%
in ~30 days. Standard z-scores do not adequately represent a 6σ temperature event.
`canada_canola_heat_dome_flag` is a dedicated binary + severity score for this specific
tail event pattern. Combined with `canada_canola_z` it gives the model both the continuous
moisture signal and the discrete extreme-heat signal independently.

---

#### Frozen Orange Juice — frozen_orange_juice

**Origins**: Florida (Indian River, Ridge, Interior districts), Brazil (São Paulo state)

| Feature | Source | Notes |
|---------|--------|-------|
| `nass_citrus_forecast_revision` | NASS Citrus bronze | Monthly NASS Florida citrus forecast Oct–Jul |
| `nass_citrus_vs_prior_month` | NASS Citrus bronze | Current month − prior month (revision surprise) |
| `florida_frost_event_flag` | NASA POWER | Tmin < −2°C in Indian River / Ridge region Dec–Feb; single most price-moving event in FCOJ |
| `florida_hurricane_wind_index` | NASA POWER wind | Max sustained wind within 100km of citrus counties Aug–Oct |
| `hlb_cumulative_index` | NASS Citrus bronze | Huanglongbing (citrus greening) cumulative infection rate; structural long-term yield decline |
| `florida_summer_z` | CHIRPS FL | Jun–Sep rainfall (tree health during non-harvest stress season) |
| `brazil_sp_citrus_z` | CHIRPS | Oct–Feb SP state window (Brazil OJ ≈ 35% of world supply) |

**Structural note**: HLB has reduced Florida production structurally since 2007.
`hlb_cumulative_index` is a downward-sloping baseline suppressor — the model
distinguishes structural decline (HLB) from cyclical variation (weather/frost).
Without this the model will persistently over-forecast Florida production.

---

#### Rice — rough_rice_cbot

**Origins**: USA (Arkansas, Louisiana, Missouri), Thailand (Central Plain / Chao Phraya),
Vietnam (Mekong delta), India (Punjab, Andhra Pradesh)

| Feature | Source | Notes |
|---------|--------|-------|
| `us_rice_z` | CHIRPS AR/LA/MO | Apr–Aug planting/growing window |
| `thailand_chirps_z` | CHIRPS Chao Phraya | May–Oct wet season |
| `mekong_delta_chirps_z` | CHIRPS | Nov–Mar dry-season crop + May–Oct wet-season crop |
| `enso_seasia_rice_lag3` | NOAA ONI | El Niño → reduced SE Asian monsoon; 3mo lag to crop impact |
| `india_rice_monsoon_z` | CHIRPS Punjab/AP | Jun–Sep z-score |
| `india_export_policy_flag` | Manual config YAML | India export ban/restrictions (2023, 2024 precedents); hand-coded binary |
| `wap_rice_production_revision` | WAP bronze | Month-over-month non-US rice production estimate |

---

### Anomaly Detection Layer

Standard regression features capture average behavior. These detectors catch non-linear,
rare-event, and timing-gap signals that move markets most. Each fires a **binary flag +
severity score** — both passed as features into the Tier 2 model.

| Detector | Trigger | Commodity | Why it matters |
|----------|---------|-----------|----------------|
| **Off-season export surge** | FGIS weekly volume > 2σ above 4yr same-week median during historically low-export weeks | corn, soy, wheat | Demand pull not yet in WASDE; market found substitute before USDA acknowledged it |
| **Weather–WASDE divergence** | CHIRPS stress z > 1.5 for 4+ consecutive weeks AND WASDE revision = 0 | all grains | Timing gap: stress hasn't propagated to official estimate → front-run window |
| **CONAB revision direction flip** | Previous 2 surveys revised direction X; current survey reverses | arabica | Extremely rare; confirms production floor or ceiling |
| **Biennial cycle phase mismatch** | Current CONAB cumulative trajectory inconsistent with expected on/off year phase | arabica | Market frequently mis-prices Brazil biennial cycle; CONAB surveys resolve mid-season |
| **Multi-origin simultaneous stress** | Tier 1 stress scores fire for ≥2 independent major origins in same commodity | all | Global supply shock vs. local stress: both spread legs move together → reduce spread conviction |
| **Harvest-failure export no-show** | CHIRPS showed growing-season stress; current export pace running at or above prior year | all grains | Production damage may have been overestimated or compensated; fade the bearish narrative |
| ⚠ **BRL devaluation × export surge** | BRL/USD depreciates >10% in 60 days AND FGIS/FNC exports surge simultaneously | soy, coffee, sugar | ✅ **Phase 2B complete** — brl_usd_pct_change_90d in silver/fred_fx. FX-driven surge not fundamental demand; export pace z-score is distorted by currency. |
| **ENSO onset early warning** | ONI crosses ±0.5 for first time in current season | palm (9mo), cocoa (6mo), robusta coffee (6mo), Brazil soy (4mo) | Start the lagged yield impact forecast chain at confirmed ENSO onset |
| **Crop Progress 3σ tail event** | NASS GE% falls below lowest same-week reading in last 10 seasons | corn, soy, wheat, cotton | Statistically unprecedented stress; standard z-scores underweight tail severity |
| **Tenderable supply collapse** | AMS cotton tenderable % < 55% (vs. 72% historical avg) | cotton | Deliverable supply much tighter than production implies; CBOT spec squeeze risk |
| **Ethanol-sugar parity flip** | Brazil hydrous ethanol / raw sugar ratio crosses 0.70 threshold | raw_sugar | Flex mills pivot to ethanol mid-season; raw sugar export volume drops |
| **ENSO-to-palm lag tracker** | 9-month countdown from confirmed ONI onset to expected MPOB yield impact | palm oil | Most mechanistically reliable crop impact in dataset; publish expected yield hit before MPOB reports it |
| **French wheat quality reclassification** | Excess rain flag + Tmax < 20°C during Jul harvest window in northern France | french_wheat | Milling → feed reclassification collapses quality premium; MATIF moves before official quality data |
| **Crush margin extreme expansion** | Crush margin index > 99th pct of trailing 5yr | soy, rapeseed | Processors compete aggressively for beans → unexpected demand pull on raw beans |
| **Canada heat dome** | Tmax > 35°C for ≥3 consecutive days in SK/AB during Jul | canola_ice | 2021 precedent: −35% yield in one month; binary extreme far outside normal z-score range |

---

### Three-Tier Model Architecture

```
Tier 1 — Origin Stress Models  (country × commodity × crop_year)
  Input:   Universal weather features (CHIRPS z-scores, NASA POWER anomalies)
           + Commodity-specific features (see per-commodity specs above)
           + Anomaly detection flags (binary + severity scores)
  Output:  origin_stress_score   (0–1 probability of below-trend production)
           production_forecast   (quantity estimate with 80% confidence interval)
           area_forecast         (separates yield shock from area abandonment)
  Model:   XGBoost + walk-forward cross-validation (min 5yr out-of-sample window)
  SHAP:    Feature contribution per origin per week → interpretable driver
           e.g. "Brazil arabica: 62% flowering moisture, 28% biennial phase, 10% ENSO"

Tier 2 — S/D Balance Sheet Models  (commodity contract × marketing year)
  Input:   Aggregated Tier 1 origin_stress_scores (all origins for that commodity)
           USDA PSD S/U ratio + revision delta
           WASDE production + stocks revision surprise
           Export pace anomaly z-score (FGIS / FNC / MPOB / SAGIS)
           Commodity-specific Tier 2 features (grindings, tenderable %, ethanol mix)
           Anomaly detection flags from relevant detectors
  Output:  ending_stock_forecast
           su_ratio_forecast
           su_ratio_surprise  (forecast − USDA PSD consensus)
  Model:   XGBoost; fewer observations (marketing-year grain) → heavier regularization

Tier 3 — Spread Signal Models  (Phase 2; requires price data)
  Input:   Tier 2 su_ratio_surprise for each spread leg
           Leg-specific Tier 1 origin_stress_scores (those that differ between legs)
           FX cross rate (BRL/USD, EUR/USD, CNY/USD, ARS/USD)
           COT net managed money z-score per contract (disaggregated, 2006–present)
           Spread z-score vs. historical (current spread / rolling 3yr std)
           calendar_spread_z_{commodity}_{tenor} — front/deferred spread z-score conditioned
             on S/U ratio quintile and marketing-year week (same-commodity term structure signal;
             computed separately from intercommodity spread pairs below)
  Output:  spread_signal     — z-score of current spread vs. fundamental fair value
           spread_conviction — continuous score [0, 1] replacing the binary 0/1 flag.
                               Captures partial multi-origin events correctly:
                               conviction = 1 − min(stress_leg_A, stress_leg_B) / max(stress_leg_A, stress_leg_B)
                               where stress_leg = Tier 1 origin_stress_score for the
                               dominant origin of each spread leg.
                               Pure asymmetric stress (one leg only) → conviction near 1.
                               Equal bilateral stress → conviction near 0.
                               Partial bilateral stress (one leg >> other) → intermediate.
                               The binary flag (fire on ONE leg only) is too coarse:
                               La Niña stressing arabica at 0.8 and robusta at 0.3 still
                               produces a spread trade with moderate conviction (~0.63),
                               not zero conviction. Gates position sizing continuously
                               rather than switching between full-size and no-trade.
  Calendar spread note: calendar spread signals are generated independently of intercommodity
    pairs — they are single-commodity, time-spread signals. Tight S/U ratio → convenience
    yield dominates → backwardation. Ample stocks → carry cost dominates → contango.
    Signal = (current_tenor_spread − median_spread_at_this_su_quintile_and_week) / std.
```

---

### Spread Pairs (Enhanced)

| Pair | Leg A | Leg B | Primary driver | Asymmetric signal |
|------|-------|-------|----------------|-------------------|
| 1 | arabica_coffee | robusta_coffee | Brazil biennial + CONAB vs. Vietnam CHIRPS + ONI lag | Biennial mismatch fires on arabica only |
| 2 | corn_cbot | campinas_corn_reference_bmf | US Corn Belt z + GE% vs. Brazil safrinha delay | Safrinha delay fires; US GE% normal |
| 3 | soybeans_cbot | soybeans_no_1_dce | US pod-fill stress vs. Brazil MT harvest + port delay | La Niña: Brazil stress → US premium collapses |
| 4 | soybean_oil_cbot | malaysian_crude_palm_oil_cme | Soyoil/palm premium z + ENSO lag on palm | El Niño onset: palm will stress in 9mo; soyoil unaffected |
| 5 | french_rapeseed_matif | canola_ice | EU flowering frost vs. Canada heat dome flag | Heat dome is binary tail; MATIF immune |
| 6 | south_african_white_maize_jse | south_african_yellow_maize_jse | Shared SA CHIRPS; white/yellow premium = food-security bid | Same origin; premium z-score is the only asymmetric signal |
| 7 | raw_sugar | white_sugar | Shared cane supply; white/raw premium = refinery gap | Ethanol parity flip fires only on raw leg |
| 8 | arabica_coffee | french_wheat_matif | ENSO: La Niña → Brazil coffee dry AND Black Sea drought simultaneously | Cross-commodity ENSO correlation — multi-origin detector fires; low conviction; watch carefully |

### Calendar Spread Pairs (Phase 2 — same-commodity term structure)

Signal construction: `calendar_spread_z = (F_near − F_deferred) − E[spread | su_quintile, mkt_yr_week]` / σ.
S/U ratio quintile is the primary conditioning variable — the same `psd_ending_stock_su_ratio`
feature computed in Tier 1. No structural cost-of-carry model required; analogue lookup
conditioned on S/U quintile and marketing-year week is sufficient.

| Pair | Near contract | Deferred contract | S/U driver | Backwardation condition |
|------|--------------|------------------|------------|------------------------|
| C1 | corn_cbot Dec | corn_cbot Mar | CBOT corn S/U ratio | S/U < 10% → strong backwardation; export-demand acceleration amplifies |
| C2 | soybeans_cbot Nov | soybeans_cbot Jan | CBOT soy S/U ratio | Tight old-crop vs. new-crop at harvest; pod-fill stress widens premium |
| C3 | soft_red_winter_wheat_cbot Dec | soft_red_winter_wheat_cbot Mar | US wheat S/U ratio | Winter wheat carries structural contango unless global stocks tighten |
| C4 | arabica_coffee Mar | arabica_coffee May | ICE arabica certified stocks / S/U | Biennial off-year tightens nearby; certified stocks draw the trigger |
| C5 | raw_sugar Mar | raw_sugar May | Global sugar S/U ratio | Thai/Indian production deficit → near-term supply squeeze |
| C6 | cocoa Mar | cocoa May | Global cocoa S/U ratio + grindings | Mid-crop arrival pace vs. near-term grinding demand |

Note: Euronext (MATIF wheat/corn/rapeseed), DCE (soy), JSE (SA maize), and BMF (Campinas corn)
calendar spreads are deferred to Phase 2 backtest validation — add if intercommodity spread
model confirms meaningful residual after cross-exchange spread signals are accounted for.

---

### Analogue Lookup Engine (Phase 2)

```
For each commodity at time T:
  production_forecast_T
    → query silver.production_history where
        abs(production − production_forecast_T) / production_forecast_T < 0.10
    → retrieve (year_i, price_at_production_i) for each analogue year i
    → weight each analogue by:
         w_su     = similarity(su_ratio_T, su_ratio_i)      — tight-stock years more relevant
         w_enso   = match(enso_phase_T, enso_phase_i)       — same ENSO phase analogues
         w_bienn  = match(biennial_phase_T, biennial_phase_i) — arabica only
    → weighted_price_distribution = percentile(price × w, [10, 25, 50, 75, 90])
    → mispricing_z = (current_price − median) / std(weighted_price_distribution)
```

Weighted analogues outperform naive ±10% lookup: a drought year on tight stocks is not
comparable to a drought year on ample stocks even if production quantities are identical.
The S/U ratio weight is the single most important weighting dimension.

Requires `silver.price_series` table that does not exist yet.

---

## Full Data Source Registry

### Weather (complete)

| Source | Coverage | Format | Status | Layer |
|--------|---------|--------|--------|-------|
| NASA POWER | All 31 commodities × all regions, daily, 1981–present | JSON | ✅ Silver | weather |
| CHIRPS v3 | All 31 commodities × all regions, daily, 1981–present | COG | ✅ Silver | weather |
| **MODIS NDVI (MOD13A1)** | All crop growing regions, 16-day composites, 2000–present | HDF4 | ✅ Silver (9,723 files) | **✅ Complete. `silver/weather/source=modis_ndvi/` — 500m 16-day composites 2000–present; crop-calendar-aligned z-score vs. 2000–2020 baseline. Complements CHIRPS: precipitation input vs. vegetation response.** |
| **NOAA CPC Soil Moisture** | Global 0.5° grid, daily, 1948–present | GrADS binary | ✅ Silver (133,774 files) | **✅ Complete. `silver/weather/source=cpc_soil/` — daily 0.5° global grid 1948–present. Leaky-bucket model-derived. Enables soil moisture features for all historical growing seasons. Captures pre-season deficit not visible in CHIRPS.** |

### Production & S/D — Structured (numerical ML features primary)

| Source | Coverage | Format | Status | Notes |
|--------|---------|--------|--------|-------|
| FAOSTAT QCL | All 31 commodities, 188 countries, 1961–2023 | ZIP/CSV | ✅ Silver | Annual production baseline |
| **USDA PSD** | All 31 commodities, 1960s–present | Bulk CSV | ✅ Raw, ✅ Bronze, ✅ Silver | **✅ Complete. `silver/psd/part-000.parquet` — 144,012 rows; all 31 commodities × all countries × market_year × wasde_release_month; columns include `su_ratio`, `su_ratio_yoy_delta`, `production_mt_revision`, `ending_stocks_mt_revision`, `consumption_mt_revision`. `wasde_production_revision` + `wasde_stocks_revision` features ready.** |
| **USDA NASS QuickStats** | US domestic: corn, soy, wheat, cotton, citrus; weekly + annual | API/JSON | ✅ Raw, ✅ Silver (annual + Crop Progress) | **✅ Complete for both annual + Crop Progress. Annual stats: `silver/nass_annual/` (corn_cbot, soybeans_cbot, cotton, rough_rice_cbot, canola_ice). Crop Progress GE%: `silver/nass_crop_progress/` — 279 files by commodity × year (corn_cbot 1979–2025, soybeans_cbot, cotton, SRW wheat, HRS wheat, rough_rice_cbot).** |
| **WASDE** | All commodities, monthly revision, 1973–present | CSV + PDF + TXT | ✅ Raw (616 files, 1973–2026), ✅ Text layer, ❌ Bronze structured parse | **P1. Text layer complete (all 3 eras). Three format eras: (1) 1973–1994 scanned PDF → Textract OCR complete; (2) 1995–1999 TXT → plain parse complete; (3) 2000–present digital PDF → pdfplumber complete. Bronze structured parse (`wasde_production_revision`, `wasde_stocks_revision` revision-delta features) pending.** |
| SAGIS SWB (South Africa) | SA weekly grain S&D bulletin; PDFs, 2011-present (~746 files) | PDF | ✅ Raw, ❌ Bronze | P2. Weekly S&D summary. Textract bronze pending. |
| SAGIS Weekly Data (South Africa) | SA weekly producer deliveries + imp/exp; 2003-present (138 files) | Excel/XLS | ✅ Raw, ❌ Bronze | P2. Weekly grain flows by crop. |
| **SAGIS / CEC (South Africa)** | White/yellow maize, wheat, soy, sunflower; monthly during season | Excel + PDF | ✅ Raw (374 files, 1999–2026), ❌ Bronze | **P2. Raw archive ingested (PDF/DOC/XLS mix, filenames `CEC-YYYY-MM-[Summer/Winter].ext`). SA equivalent of WASDE. Required for JSE contracts. Bronze parse (pdfplumber + Textract for .doc) pending.** |
| CONAB bulletins | Brazil coffee; arabica + conilon by state; 4–5 surveys/season | PDF | ✅ Raw, ✅ Text layer (55 docs, pdfplumber, `text/source=conab/crop_year={y}/survey={n}/document.json`), ❌ Bronze | P1. Revision surprise = highest-conviction coffee feature. |
| CONAB bulletin XLS | Brazil coffee; per-bulletin Excel | XLS | ✅ Raw, ✅ Bronze (13 files, `bronze/production/source=conab_xls/`), ✅ Silver (`silver/conab_coffee/` — arabica + robusta 2023–2026, 8 files; `silver/production/source=conab/` — 26 files) | ✅ Bronze + recent-season silver complete. |
| UNICA production/milling | Brazil CS sugarcane; 41 seasons 1980/81–2020/21 | HTML | ✅ Raw, ✅ Bronze, ✅ Silver | Silver: `silver/unica_annual_state/part-000.parquet` (1,107 rows × 8 cols; harvest_year, state_region, cane_crushed_t, sugar_produced_t, ethanol_total_m3, ethanol_hydrous_m3, ethanol_anhydrous_m3, source). Batch job: `leviathan-dev-unica-annual-state:1`. |
| UNICA bi-weekly | Brazil CS in-season bulletins | PDF | 🔄 Raw partial, ❌ Bronze | P3. Intra-season production pace. |
| MPOB BEPI | Malaysia CPO; monthly + annual | HTML/PDF | ✅ Raw, ✅ Bronze, ✅ Silver | Bronze: annual_summary 2017–2026 (10 files) + overview_pdf 2011–2016 (6 files). Silver: `silver/mpob/part-000.parquet` (monthly 2017–present) + `silver/mpob_annual/part-000.parquet` (annual 2011–2016). Text layer: 2010–2016 (GraphRAG). |
| MPOC | Malaysia palm trade stats, competitive prices | HTML | ✅ Raw, ❌ Bronze | P3. Trade flow + price comparison. |
| FNC Colombia bulk Excel | Colombia coffee; production + exports, 1913–present | XLSX | ✅ Raw, ✅ Bronze (7 files, `bronze/production/source=fnc_excel/`), ✅ Silver (`silver/fnc_colombia/` — monthly 1913–2026, area_department 2002–2025, exports_port_type 2017–2026; 148 files) | ✅ Complete. `fnc_export_pace_z` feature ready. |
| FNC Colombia monthly PDFs | Colombia coffee monthly reports | PDF | 🔄 Raw partial, ❌ Bronze | P3. GraphRAG secondary. |
| **USDA AMS Cotton Classing** | US cotton; weekly bales classed, tenderable %, quality | Data files | ✅ Raw (annual quality PDFs, 27 seasons 1986–2025), ❌ Bronze | **P2. Annual Quality Report fully ingested. Weekly classing data files (tenderable %) not yet ingested.** |
| **USDA NASS Citrus Forecast** | Florida citrus; monthly forecast Oct–Jul | PDF | ✅ Raw (372 files), ❌ Bronze | **P2. Raw backfilled. pdfplumber bronze + silver pending. Required for frozen_orange_juice.** |
| **ICCO Cocoa Bulletins** | Global cocoa; production, grindings, stocks, quarterly | PDF/HTML | ✅ Raw (104 files — 95 QBCS quarterly bulletins + 9 EWG stocks), ❌ Bronze, ❌ Text | **P2. Raw archive ingested. pdfplumber bronze + text extraction pending. Quarterly grindings (demand) equally important as production for cocoa.** |
| **USDA AMS Export Inspections** | US grain/oilseed weekly export volumes inspected at ports; 1983–present | TXT/CSV | ✅ Raw (43 files, CY1983–CY2025), ✅ Bronze, ✅ Silver | Bronze: 43 Parquet files by CY (1983–2025). Silver: `silver/fgis/` partitioned by leviathan_slug × marketing_year; corn_cbot, soybeans_cbot, SRW/HRW/HRS wheat; 1982/83–2024/25. Weekly DAG live (`fgis_weekly_ingest_dag.py`, Thursdays noon UTC). |
| **USDA FAS Export Sales Reporting (ESR)** | US grain/oilseed/cotton weekly export commitments (shipped + unshipped); ~1990–present | CSV | ✅ Raw (370 files), ✅ Bronze (740 files, by commodity_code × market_year × as_of snapshot), ✅ Silver (370 files, `silver/production/source=usda_esr/`) | **✅ Complete. `esr_commitments_pace_z` + `esr_new_crop_sales_z` features ready. Point-in-time snapshots preserved via `as_of` partition (20260524, 20260528). Thursday DAG live alongside FGIS.** |
| **World Bank Pink Sheet** | Global commodity prices + fertilizer/energy input costs (urea, DAP, natural gas); monthly + annual, 1960–present | Excel | ✅ Raw (1 file, 2026M05), ✅ Bronze, ✅ Silver | **✅ Complete. `silver/pink_sheet/part-000.parquet` — 796 rows, 1960–present; columns: urea, DAP, potash, natural_gas_us, natural_gas_eu, phosphate_rock, blended_npk_index + 5yr rolling z-scores for each. `input_cost_urea_z` + `input_cost_dap_z` features ready. Monthly DAG active. ⚠ Note: Brent crude NOT in this silver — separate EIA ingest needed for `crude_oil_brent_z` universal feature.** |

### Production & S/D — Qualitative (GraphRAG primary)

| Source | Coverage | Format | Status | Notes |
|--------|---------|--------|--------|-------|
| USDA FAS Coffee WMT | Global coffee S/D; biannual, 47 reports ingested | PDF | ✅ Raw, ✅ Text layer (47 docs, `text/source=usda_fas_coffee_wmt/`), ❌ Bronze (structured tables) | P1. Text layer complete (GraphRAG-ready). Structured table bronze pending for ML features. |
| **USDA GAIN Coffee/Crop Reports** | Country coffee/crop annual + semi-annual | PDF | ✅ Raw (33 archive prefixes across 15 commodity groups, 3,689 total files), ✅ Text layer (5,120 docs, all 15 groups), ❌ Bronze (structured tables) | **✅ Text layer complete — GraphRAG corpus ready. Doc counts by group: cotton 888, sugar 801, coffee 645, grain_monthly 645, soybean_meal 260, cotton_monthly 226, wheat 214, orange_juice 179, corn 167, sugar_semiannual 159, soybean_oil 133, soybeans 127, rice 120, coffee_semiannual 86, rapeseed 83, palm_oil 73, cocoa 21. GraphRAG indexing is the immediate next step.** |
| **WASDE Narrative** | All commodities, monthly | PDF narrative | ✅ Text layer (616 docs, `text/source=usda_wasde/`) | **✅ Text layer complete. 616 WASDE text extractions (1973–2026, all 3 format eras: Textract OCR 1973–1994, plain parse 1995–1999, pdfplumber 2000–present). GraphRAG-ready. Pairs with `silver/psd/` revision deltas.** |
| **World Agricultural Production (WAP)** | All major crops, monthly, non-US focus | PDF | ✅ Raw (448 files), ✅ Text layer (448 files), ✅ Bronze Table 01 (247 files, 2002–2026), ✅ Silver | **✅ Complete. `silver/wap_table01/part-000.parquet` + `silver/wap_table01_revisions/part-000.parquet`. Text layer complete (GraphRAG). Table 01 bronze complete 2002–2026. Pre-2002 (1988–2001, source=b): text layer only — no Table 01 format exists in that era.** |
| **World Bank Commodity Markets Outlook** | Global macro + fertilizer + energy + food market analysis; quarterly, 2012–present | PDF | ✅ Raw (146 files), ❌ Text layer | **P3. Raw archive ingested. Text extraction pending. GraphRAG macro overlay — structural price moves via energy/fertilizer costs, climate policy, global demand shocks. Pairs with `silver/pink_sheet/` structured data.** |

### Price & Positioning (Phase 2 — deferred)

| Source | Notes |
|--------|-------|
| Futures price series (CBOT, ICE, Euronext, DCE, JSE, BMF) | Required for analogue lookup target variable. **Ingest multiple contract expirations per commodity** (not just front month) — calendar spread signals require front + at least 2 deferred tenors per contract. |
| **CFTC COT reports** | ✅ Raw (20 files, `raw/production/source=cftc_cot/`), ✅ Bronze (10 Parquets, `bronze/production/source=cftc_cot/year=*/part-000.parquet`), ✅ Silver (`silver/cot/part-000.parquet`, 10,806 rows, 12 slugs, 2006-06-13–2025-12-30). Disaggregated futures-only. `mm_net_z_3yr` and `mm_pct_oi_z_3yr` computed via 156-week rolling window per commodity. |
| Exchange rates (BRL/USD, EUR/USD, CNY/USD) | Basis spread component |
| CEPEA/Esalq spot prices | Brazilian domestic coffee + sugar spot reference |

---

## Extraction Methods by Source Type

| Format | Tool | Notes |
|--------|------|-------|
| Structured CSV / API | `requests` + `pandas` parser | USDA PSD, NASS, WASDE CSV |
| Excel | `openpyxl` / `pandas.read_excel` | SAGIS/CEC, FNC, CONAB XLS |
| HTML tables | `BeautifulSoup` + `pandas.read_html` | UNICA, MPOB, MPOC |
| PDFs — consistent tables | `pdfplumber` | CONAB, NASS Citrus, AMS Cotton |
| PDFs — mixed layout | `pdfplumber` first; Textract fallback for scanned | WASDE narrative, WMT, GAIN, WAP |
| PDFs — charts | Claude vision API (Bedrock) | ~$0.001/chart; do tables first |
| PDFs — narrative paragraphs | `pdfplumber` text extraction → `paragraphs.jsonl` | Input to GraphRAG indexing |
| **PDFs — scanned paper** (no text layer) | Textract `DetectDocumentText` → page filter → `paragraphs.jsonl` | WASDE 1973–1994 (~$63) only. Pre-2002 WAP archive.org PDFs are digital (pdfplumber text extraction confirmed) — Textract not needed. All other PDF sources also have digital text layers. |

All PDF/HTML extraction runs as **AWS Batch Fargate tasks** (never Glue —
CPU/memory bound, task count too high).

---

## Source Priority Notes

- **USDA PSD** — the single most important new addition. Free bulk CSV, all commodities,
  decades of S/D history. Bootstraps ML feature engineering immediately while WMT PDF
  extraction is being built. The ending stocks/use ratio is the best structural anchor for
  the production-vs-historical-price lookup.

- **USDA NASS QuickStats** — the "Crop Progress Good/Excellent %" weekly series is the
  most-watched leading indicator for US corn and soy during growing season. It is a
  weather-proxy signal that complements CHIRPS directly and moves futures.

- **WASDE** — most market-moving scheduled report in commodities, released second Friday
  monthly. The revision delta (this month vs. prior month) is the WASDE surprise feature,
  same pattern as CONAB. **Critical**: WASDE release date alignment must be enforced in
  Feature Store to prevent lookahead bias. Point-in-time retrieval is the solution.

- **SAGIS / CEC** — the South African equivalent of WASDE. CEC publishes monthly crop
  estimates January–October. White maize (food staple) and yellow maize (feed) frequently
  diverge — they are genuinely different spread legs for the JSE contracts.

- **USDA GAIN** — written by USDA FAS country attachés. Contains local intelligence not
  in any structured dataset: leaf rust pressure in Colombia, dry weather in Cerrado
  Mineiro, Vietnamese frost, Ethiopian El Niño impact, policy export quotas. The Coffee
  Annual series (June–September each year) sets USDA's country production assumptions.

- **USDA AMS Cotton Classing** — tenderable percentage is critical for cotton. CBOT
  cotton contract has strict deliverable spec (staple length, micronaire, color, leaf
  grade). If a significant portion of US cotton fails spec, deliverable supply is tighter
  than total production suggests. Weekly during season (August–March).

- **USDA NASS Citrus** — Florida is ~25% of global FCOJ supply. NASS revisions during
  season move FCOJ futures directly. Monthly October–July, consistent pdfplumber tables.

- **ICCO** — quarterly grinding data (demand-side consumption) is as important as
  production for cocoa. Grindings below trend = demand destruction = bearish regardless
  of supply. Data back to 1960 for some series.

- **USDA AMS Export Inspections** — the most important grain/oilseed high-frequency
  signal missing from the original plan. USDA publishes actual weekly inspection volumes
  at export elevators (corn, soybeans, wheat, sorghum, barley). Cumulative season-to-date
  pace vs. USDA export forecast is watched by every grain desk — it is the most direct
  real-time measure of whether export demand is matching USDA assumptions. The point-in-
  time snapshot (WA_GR101.txt) is critical for preventing lookahead bias: ingest both the
  historical archive and the weekly file as separate ingestion runs. P1 alongside WASDE.

- **USDA FAS Export Sales Reporting (ESR)** — the leading complement to FGIS. ESR
  reports forward export commitments (both shipped and unshipped outstanding sales),
  published every Thursday morning alongside FGIS. Where FGIS measures what physically
  left the elevator, ESR measures what has already been sold — typically 4–8 weeks ahead
  of physical shipment. A large China purchase of US corn appears in ESR weeks before
  FGIS can confirm it. The `esr_commitments_pace_z` feature (cumulative season-to-date
  commitments vs. USDA export forecast pace) and `esr_new_crop_sales_z` (forward sales
  for the next marketing year vs. 4yr same-week median) together provide a demand-side
  leading indicator that FGIS alone cannot. Free CSV from USDA FAS apps.fas.usda.gov.
  P1 alongside FGIS; ingest job mirrors the FGIS pattern.

- **MODIS NDVI (MOD13A1)** — satellite vegetation index over all crop growing regions.
  Where CHIRPS measures precipitation input, NDVI measures the vegetation response —
  capturing the integrated effect of rainfall, heat stress, pest pressure, and soil
  moisture state. The MOD13A1 product (16-day composites, 500m, 2000–present) is a
  pre-computed NDVI value, requiring no band arithmetic. Available on AWS S3 us-east-1
  via the AWS Open Data Registry (no egress cost from Batch jobs). Pipeline architecture
  mirrors CHIRPS: download HDF4 tiles for each region's bounding box, apply crop mask,
  aggregate to region-level z-score vs. 2000–2020 crop-calendar baseline. P2 — natural
  extension of the CHIRPS pipeline once that is fully operational.

- **NOAA CPC Soil Moisture** — model-derived daily soil moisture at 0.5° global grid,
  1948–present. The 1948–present depth is the decisive advantage: every historical
  growing season in the training set gets a soil moisture feature, enabling the model
  to distinguish drought years with pre-existing soil deficit (double-stress) from drought
  years with wet antecedent conditions. Open FTP, no authentication. GrADS binary format
  (readable with Python struct). At crop-reporting-district scale, 0.5° (~55km) is
  adequate. Feature: `cpc_soil_moisture_z_{region}` — growing-season soil moisture
  percentile anomaly vs. 1981–2010 WMO climatological baseline. P2 alongside MODIS NDVI.

- **CFTC COT (Commitment of Traders)** — underweighted in the original plan. For a
  spread trading system, speculative net positioning is a required Tier 3 feature. The
  disaggregated COT (managed money, commercials, swap dealers) is more actionable than
  the legacy report. Signal is contrarian at extremes: managed money at a 3-year net long
  z-score above 2σ has documented mean-reversion tendency in agricultural futures. Ingest
  alongside price series in P8; feature engineering adds the rolling z-score per
  contract. Free CSV, all CBOT/ICE/CME ag contracts, disaggregated data back to 2006.

- **World Bank Pink Sheet** — input costs (urea, DAP, natural gas, crude oil) are a
  leading indicator for planting decisions and therefore area harvested. High fertilizer
  costs → farmer margin compression → reduced input application → yield drag or area
  switch to lower-input crops. Monthly Excel, free, 1960s–present. Adds a macro cost
  layer that no other source in the plan provides. Most relevant for corn, wheat, and
  rapeseed where N-fertilizer is a major cost input.

- **World Bank Commodity Markets Outlook** — quarterly PDF with cross-commodity
  analysis covering food, energy, fertilizer, and metals. Most useful for GraphRAG as a
  macro context layer explaining structural price moves that production models alone
  cannot capture (e.g., 2022 fertilizer shock, Russia-Ukraine grain corridor disruption,
  El Niño food price cascades). P3 priority — ingest PDFs raw in P2, index in P5 after
  WASDE, CONAB, and GAIN are already in the corpus.

---

## Layer Architecture

### Layer 0: Data Foundation (Medallion)

```
Raw (S3) → Bronze (S3, Parquet + paragraphs.jsonl) → Silver (S3, Parquet, Athena)
```

**Bronze outputs per source type:**
- Structured sources → `{source}_production.parquet` with clean schema
- PDF/HTML → `{source}_tables.parquet` (ML features) + `{source}_paragraphs.jsonl`
  (GraphRAG input)
- Revision sources (CONAB, WASDE) → append `_revision_surprise` column (delta vs. prior)

**Silver schema (standardized across all production sources):**
All production silver tables share:
`country, commodity, source, marketing_year, variable, value, unit, is_revision,
survey_number, ingest_date`

**Athena tables to add** (partition projection, matching existing pattern):

| Table | Status | Source |
|-------|--------|--------|
| `silver_weather` | ✅ Exists | NASA POWER + CHIRPS |
| `silver_production` | ✅ Exists | FAOSTAT |
| `silver_sd_balance` | 🔄 Parquet exists (`silver/psd/part-000.parquet`, 144k rows), Athena registration pending | USDA PSD |
| `silver_crop_progress` | 🔄 Parquet exists (`silver/nass_crop_progress/`, 279 files), Athena registration pending | NASS Crop Progress |
| `silver_model_predictions` | ❌ Needed | Daily Batch inference output |
| `silver_shap_values` | ❌ Needed | Daily SHAP output |
| `silver_price_series` | ❌ Phase 2 | Futures exchanges |

---

### Layer 1: Feature Engineering

Runs as Glue Python Shell jobs (for scheduled/incremental) or Batch Fargate tasks
(for heavy backfills). Writes to SageMaker Feature Store offline.

**Feature groups (one FeatureGroup per commodity tier):**

| Feature | Source table | Computation |
|---------|-------------|-------------|
| `chirps_precip_z_{region}_{lag_weeks}` | silver_weather | Rolling z-score vs. 30yr seasonal norm |
| `nasa_temp_anomaly_{region}` | silver_weather | Deviation from 30yr baseline |
| `frost_event_flag_{region}` | silver_weather | Tmin < 0°C in frost-sensitive areas |
| `gdd_accumulated_{region}_{window}` | silver_weather | Growing Degree Days: `max(0, (T_max + T_min)/2 − T_base)` summed over the growing window. T_base and T_max cap are crop-specific (corn: base 10°C, cap 30°C; wheat: base 0–5°C, cap 25°C; soy: base 10°C, cap 30°C; cotton: base 15.5°C, cap 37°C). Inputs `temperature_2m_max_c` and `temperature_2m_min_c` are in silver_weather (NASA POWER). **Not pre-computed in silver — must be derived here in feature engineering with per-commodity T_base and T_max_cap.** |
| `drought_consecutive_days_{region}` | silver_weather + CHIRPS | Consecutive below-20th-percentile days |
| `nass_crop_progress_ge_pct` | silver_crop_progress | Good/Excellent % for week |
| `nass_crop_progress_surprise` | silver_crop_progress | Current week vs. 5yr avg same week |
| `faostat_production_yoy` | silver_production | Year-over-year change |
| `faostat_production_trend_dev` | silver_production | Deviation from 10yr linear trend |
| `psd_ending_stock_su_ratio` | silver_sd_balance | ending_stocks / consumption |
| `psd_su_ratio_yoy_delta` | silver_sd_balance | su_ratio minus prior year su_ratio |
| `wasde_production_revision` | silver_sd_balance | Current minus prior month WASDE |
| `wasde_stocks_revision` | silver_sd_balance | Current minus prior month WASDE |
| `conab_revision_surprise` | silver_production (CONAB) | survey_N minus survey_{N-1} |
| `conab_revision_streak` | silver_production (CONAB) | Consecutive revisions in same direction |
| `export_pace_z_{month}` | AMS Export Inspections bronze (US grains) + FNC / MPOB / SAGIS bronze | Z-score vs. seasonal norm; US corn/soy/wheat sourced from weekly AMS inspection data |
| `cotton_tenderable_pct` | AMS Cotton bronze | Share meeting CBOT delivery spec — **annual only** (one value per season from AMS Quality silver; weekly version not available) |
| `icco_grindings_trend_dev` | ICCO bronze | Grindings vs. 3yr trend — ✅ computable from ICCO QBCS silver world totals |
| `cot_net_managed_money_z_{commodity}` | CFTC COT disaggregated | ✅ **Silver ready** — `silver/cot/part-000.parquet`. 10,806 rows, 12 slugs (corn, soy complex ×3, wheat ×3, coffee, cocoa, cotton, sugar, rough rice), 2006–2025, weekly. `mm_net_z_3yr` = z-score of managed money net long vs. 156-wk rolling window per commodity; contrarian signal at ±2σ. Also `mm_pct_oi_z_3yr` for cross-commodity comparison. |
| ⚠ `crush_margin_index` | Pink Sheet bronze | ✅ Phase 2A complete — soybeans, soybean_oil, soybean_meal in silver/pink_sheet. |
| ⚠ `soyoil_palm_premium_z` | Pink Sheet bronze | ✅ Phase 2A complete — soybean_oil_usd_t and palm_oil_cpo_usd_t in silver/pink_sheet. |
| ⚠ `ars_usd_pct_change_90d` | FRED | ✅ Phase 2B complete — ars_usd_pct_change_90d in silver/fred_fx (2005–2022; gaps during ARS capital controls as expected). |
| ⚠ `brl_usd_pct_change_90d` | FRED | ✅ Phase 2B complete — brl_usd_pct_change_90d in silver/fred_fx (5,488 non-null rows, 2005–present). |

**Point-in-time discipline**: Feature Store offline retrieval API ensures features are
fetched as-of the prediction date, not the ingestion date. This prevents lookahead from
WASDE, CONAB, and other time-sensitive releases — the single most important safeguard in
the training pipeline.

---

### Layer 2: MLOps Stack

#### SageMaker Components

| Component | Use | Rationale |
|-----------|-----|-----------|
| ✅ Feature Store (offline only) | Yes | Point-in-time correct features; S3-backed; Glue catalog integration; ~$1/yr |
| ✅ Model Registry | Yes | Version + approval workflow for 31+ model artifacts; free |
| ✅ Clarify | Yes (when ready for prod ops) | Drift detection; start with evidently first (free, same capability) |
| ❌ Async Inference | No | Wrong abstraction; endpoints cost $37+/mo idle; Batch Fargate runs 31 predictions in <10 min for pennies |
| ❌ Training Jobs | No | Datasets too small; Batch Fargate is cheaper and already in stack |
| ❌ SageMaker Pipelines | No | Overkill; EventBridge + Batch + Step Functions handles it |
| ❌ Online Feature Store | No | Only needed for real-time inference, which is not in scope |

#### Training Pipeline

Triggered by: EventBridge on WASDE release dates + weekly fallback cron.

```
EventBridge trigger
  → Batch Fargate: training task (per commodity)
    1. Read features from SageMaker Feature Store (point-in-time as-of training cutoff)
    2. Assemble training set: align feature vintage to crop_year label
    3. Train XGBoost (SHAP-compatible) with walk-forward cross-validation
    4. Evaluate: RMSE, directional accuracy, out-of-sample R²
    5. Register in SageMaker Model Registry:
         metadata: training_date, feature_vintage, eval_metrics, commodity
         status: Pending → auto-approve if RMSE improvement > threshold
                         AND no feature drift flagged
    6. Save training-time feature distribution snapshot to S3 (for drift baseline)
```

#### Daily Inference Pipeline

EventBridge cron: 05:00 UTC.

```
Batch Fargate: inference task
  1. Fetch approved model URI from SageMaker Model Registry per commodity
  2. Load model artifact from S3
  3. Read features from Feature Store (as-of yesterday close)
  4. predict() → production_forecast + confidence interval
  5. shap.TreeExplainer() locally → shap_values per feature
  6. Write predictions.parquet + shap_values.parquet to S3
  7. Glue sync to silver.model_predictions + silver.shap_values
  8. Compute signal: production_forecast vs. PSD/WASDE consensus → surprise
```

#### Monthly Drift Monitoring

Start with `evidently` on Batch Fargate (zero new service, free). Migrate to
SageMaker Clarify Processing Job when managed CloudWatch integration is needed.

```
Batch Fargate: drift task (1st of month)
  1. Load training-time feature distribution snapshot
  2. Load last 30 days of inference feature distributions
  3. Run evidently ColumnDriftReport + DataQualityReport
  4. If drift > threshold: publish SNS alert → set model status to Pending
  5. Write drift_report_{YYYYMM}.html to S3
```

---

### Layer 3: GraphRAG Knowledge Graph

#### Research Capability — Why This Exists

GraphRAG is the primary research interface of the system. The quantitative model tells
you a signal fired. GraphRAG tells you *why you believe it*, *how convicted to be*, and
*how to explain it to an investment committee*. It is a temporal knowledge graph over the
full document corpus — every GAIN report, every CONAB survey, every WASDE commentary,
every WAP bulletin — that can be queried with natural language and returns structured,
evidence-based answers with citations woven in.

The capability is organized into six research modes, each answering questions that are
impossible to answer from structured data alone.

---

##### 1 — Relative Value Research (Cross-Commodity Causal Edges)

*"Arabica and robusta are both stressed. Does the spread widen or compress when both
origins are simultaneously stressed — and which leg moves first?"*

Vector search returns documents about stress. Only the graph tells you the temporal
ordering: which origin's stress was reported first, which was confirmed by multiple
independent sources, and whether the market historically treated simultaneous stress as
compounding or offsetting. The cross-commodity causal edge — "Brazil arabica stress drove
arabica/robusta spread widening in seasons X, Y, Z but not in season W because Vietnamese
robusta was also stressed" — is the thing the graph captures that no spreadsheet can.

Representative questions:
- In years where Brazilian arabica was below trend but Vietnamese robusta was above trend,
  did the spread move proportionally to the supply differential — or did one leg dominate?
- For the vegetable oil complex (palm, soy oil, canola, rapeseed): when one origin
  tightens, what is the documented substitution sequence? Which importer countries switch
  first, which last, and what price premium was required to trigger switching?
- When the corn/soy area ratio deviates from its 10-year average, does the eventual
  production balance resolve through planted area adjustment, yield adjustment, or both?
  Does the answer differ between El Niño and La Niña years?

---

##### 2 — Consequence Chain Traversal (Multi-Hop Causal Reasoning)

*"Brazil CS sugar production runs 6 MMT below UNICA's April forecast. Walk me through
every documented downstream consequence."*

The answer includes: ethanol parity flip timing, Indian export policy response, Thai
forward selling behavior, white/raw spread repricing, and what typically happened to the
EU beet sugar campaign in the following year — with citations at each hop and documented
lag times between steps.

The graph encodes these consequence chains as directed edges with temporal offsets. A
query engine can traverse them to produce a full propagation sequence rather than a
single-step answer.

Representative questions:
- When an Indonesian palm oil biodiesel mandate increases, trace the full vegetable oil
  complex repricing: who benefits first — Malaysian CPO producers or Argentine soy oil
  crushers? Who gets hurt? What is the typical sequencing and lag at each step?
- A La Niña develops in Q3. Trace the full 18-month agricultural complex sequence: which
  crops are hit in the first 6 months, which suffer carry-on effects in months 7-12, and
  which actually benefit from the redistribution of rainfall patterns?
- Ukraine wheat export disruption — second order: which importers panic-buy and from which
  alternative origins? Third order: does the substitute origin draw down its own carry-in
  stocks, affecting the following season? Fourth order: does reduced wheat availability
  drive feed grain substitution that tightens corn stocks-to-use?

---

##### 3 — Counterfactual Conditioning

*"Show me every historical year where Brazilian arabica had flowering-season stress
comparable to current levels — but the final production outcome was NOT a downgrade.
What structural differences separated those years from the ones where stress translated
into a miss?"*

This question requires three things simultaneously: finding historical analogues (feature
similarity), knowing the outcome (FAOSTAT final), and understanding *why the causal chain
broke* — which requires the documented analyst commentary from that specific season
explaining what compensated for the stress. No structured data system can provide the
third piece. The graph stores both the chains that fired AND the chains that did not, with
citations for why, enabling genuine counterfactual reasoning.

Representative questions:
- In how many historical La Niña events did the Vietnam → robusta stress link fail to
  activate despite ENSO conditions being present? What did GAIN reports say was different
  about those seasons?
- When USDA WASDE revised US corn production down in August, the expected export pace
  slowdown failed to materialize in ~40% of cases. What factors — documented at the time —
  separated the cases where FGIS confirmed the downgrade from the cases where export pace
  held up?
- Has arabica ever recovered from a comparable flowering-stress season? What structural
  factors (biennial phase, carryover stocks, substitution availability) were present in
  the recovery years that were absent in the miss years?

---

##### 4 — Analyst Accuracy Calibration

*"Across the full history of GAIN country attaché reports for Brazil coffee, at what point
in the season do the reports become directionally reliable? How accurate are July reports
vs. October reports in predicting the final CONAB outcome?"*

No commercial intelligence service has ever systematically calibrated analyst accuracy
against realized outcomes across 30+ years of reports. This capability is built by
creating a link between each report's forecast at time T and the final FAOSTAT or CONAB
outcome at T+12 months. Accuracy scores compound over time — each new season adds to the
calibration set and makes the next query more reliable.

Representative questions:
- Which source — country attaché reports, CONAB survey, or WASDE — has historically been
  the earliest reliable indicator of a Brazilian arabica production miss? By how many
  months does the most accurate source lead the official confirmation?
- When multiple sources simultaneously held contradictory views on India sugar production,
  what was the eventual outcome distribution? Is consensus or dissent more predictive?
- Has there ever been a case where analyst intelligence flagged supply stress 3+ months
  before weather data confirmed it? In those cases, were the analysts right?

---

##### 5 — Narrative Tone Escalation (Qualitative Leading Indicator)

*"Detect all historical episodes where analyst tone on a specific commodity-country pair
shifted from neutral to concerned across three or more consecutive monthly reports —
before any quantitative signal confirmed stress. How often did this narrative escalation
precede a WASDE downgrade, and what was the lead time?"*

This signal exists only in the text corpus. The quantitative data showed nothing yet.
Four consecutive attaché reports used progressively more cautious language about a
developing situation. That tone shift — extracted, time-stamped, and stored as a graph
node with edge weights reflecting escalation velocity — is a legitimate leading indicator
that no structured dataset captures.

The graph also enables the inverse: *de-escalation detection*. When analyst language
transitions from concern back to neutral across consecutive reports, that is a documented
signal that the stress event resolved before official data confirmed it.

---

##### 6 — Point-in-Time Research (Look-Ahead Bias Prevention)

*"As of October 2021, what had been documented about Brazilian arabica flowering-season
stress? Show me only information that existed at that date."*

Every node and edge in the graph carries a `document_date` timestamp. Any query can be
time-gated to return only information that was published before a given date — the
qualitative equivalent of the quantitative model's walk-forward cross-validation. This is
how you backtest a qualitative thesis without look-ahead bias: the graph answers the
question as it would have been answered by an analyst sitting at that date with only the
information available to them at the time.

This also enables: *"In the 2021 Brazil arabica stress episode, at what point did evidence
cross a threshold of multiple independent confirmations — and how much earlier was that
than the first official production revision?"*

---

##### Summary: What GraphRAG Enables vs. Structured Data

| Research Question Type | Structured Silver | GraphRAG |
|----------------------|-------------------|---------|
| Relative value — which leg moves first? | ❌ | ✓ temporal ordering of documented evidence |
| Consequence chain — what happens downstream? | ❌ | ✓ multi-hop with citations + lag times |
| Counterfactual — when did the chain break and why? | ❌ | ✓ chains that fired AND chains that didn't |
| Analyst accuracy — who is reliable at what horizon? | ❌ | ✓ forecast vs. FAOSTAT/CONAB outcome links |
| Tone escalation — is stress emerging before numbers move? | ❌ | ✓ sentiment trend over consecutive reports |
| Point-in-time — what was knowable on date X? | ✓ (structured) | ✓ (qualitative, same guarantee) |
| Causal chain — what is the documented mechanism? | ❌ | ✓ directed edges with source citations |
| Cross-source consensus — do independent sources agree? | ❌ | ✓ node confluence scoring |

---

#### Entity Vocabulary (build first)

`configs/sources/entity_vocabulary.yaml` — canonical names + aliases across EN/PT/ES.
The vocabulary is the single most important input to the GraphRAG system: it constrains
what the extraction LLM is allowed to extract, preventing thousands of near-duplicate
entity nodes that fragment the graph.  Design it before writing any extraction code.

```yaml
entity_types:
  commodity:          # arabica_coffee, robusta_coffee, white_maize, palm_oil ...
  country_origin:     # Brazil, Colombia, Vietnam, Côte_d'Ivoire, Malaysia ...
  region:             # Minas_Gerais, Tay_Nguyen, Free_State, Sabah, Sarawak ...
  organization:       # CONAB, USDA_FAS, ICO, ICCO, MPOB, FNC, SAGIS, UNICA ...
  weather_event:      # frost, drought, El_Niño, La_Niña, harmattan, flood ...
  disease:            # leaf_rust, HLB, black_pod, CBD, witches_broom ...
  policy_event:       # export_ban, biodiesel_mandate, DMO, FUNCAFE, Soy_Dollar ...
  price_relationship: # arabica_robusta_spread, white_raw_premium, soyoil_palm_premium
  market_signal:      # flowering_stress, biennial_cycle, withheld_supply,
                      # tenderable_collapse, crush_margin_expansion ...

relationship_types:
  - causes             # directed causal link with optional lag
  - precedes           # temporal ordering
  - contradicts        # conflicting analyst views
  - confirms           # cross-source corroboration
  - affects_yield_of   # weather/disease → production impact
  - cited_by           # source attribution

aliases:              # normalise multi-lingual + abbreviation variants
  Minas_Gerais:       ["MG", "Sul de Minas", "Cerrado Mineiro", "Minas"]
  El_Niño:            ["ENSO positive", "El Nino", "ONI > 0.5"]
  La_Niña:            ["ENSO negative", "La Nina", "ONI < -0.5"]
  leaf_rust:          ["hemileia vastatrix", "ferrugem", "roya"]
  CONAB:              ["Companhia Nacional de Abastecimento"]
  # ... full alias list in the YAML file
```

#### Chunking Strategy — LLM-based Propositional Chunking

**Do not use fixed-token sliding windows.**  A 512-token window is agnostic to whether
those tokens contain one dense causal proposition or five disconnected observations.
A 2-sentence fertilizer-price-to-crop-switching chain may be the most signal-dense
content in a document; a fixed chunker buries it inside unrelated context, diluting
what the extraction LLM sees.

**Use propositional chunking** (formalised in the Dense X Retrieval paper, 2023):
pass each document page to an LLM asking it to decompose the text into atomic
propositions — self-contained statements that each express one complete idea — then
group related propositions into coherent chunks.  This produces variable-length chunks
that reflect semantic density:

```
Chunk A (1 sentence — high density, complete causal proposition):
  "Rising urea prices in 2021-22 caused Colombian smallholders to reduce nitrogen
   applications, driving a structural yield decline of ~8% independent of weather."

Chunk B (4 sentences — narrative context, only coherent as a unit):
  "Brazilian arabica production in 2021 entered its off-year of the biennial cycle
   following the record 2020 on-year harvest.  CONAB's first survey in January
   forecast 48.8 million bags, but consecutive frost events in June reduced Sul de
   Minas output significantly.  By the fourth survey the estimate had been revised
   down to 33.4 million bags — a 32% downward revision across four consecutive
   surveys, the largest since 2014."
```

**Model**: `gpt-4o-mini` (OpenAI API).  The `microsoft/graphrag` library calls OpenAI
natively; using it with Bedrock requires a compatibility shim (LiteLLM or Bedrock
Converse API).  For chunking — a one-time offline operation — OpenAI is used directly.
For production query-time inference (LangGraph synthesiser) Claude on Bedrock is used
to keep everything inside the AWS IAM data plane.

**Cost estimate** (full corpus, one-time):
- Propositional chunking: ~146,000 pages × $0.00015 = ~$22
- Entity + relationship extraction: ~$7 (on resulting chunks)
- Total indexing: **~$29 one-time**  (re-run monthly only for new documents)

**Rollout order** — validate before full spend:
1. Index high-value subset first (CONAB 55 + WMT 47 + GAIN coffee 645 + WASDE 616
   = 1,363 docs, ~$5) → validate extraction quality, tune prompts
2. Index remaining corpus once quality is confirmed (~$24)

#### Indexing Pipeline (Batch Fargate, runs once then monthly on new documents)

```
S3: document.json files from text/ layer
  │
  ├─ Stage 1: Propositional Chunking  [gpt-4o-mini, OpenAI API]
  │     Input:  full document text (page by page)
  │     Prompt: "Decompose into atomic propositions, group related ones into chunks.
  │              Each chunk must be a complete, self-contained semantic unit."
  │     Output: variable-length chunks (1–6 sentences each)
  │     Cost:   ~$22 one-time for full corpus
  │
  ├─ Stage 2: Entity + Relationship Extraction  [gpt-4o-mini, OpenAI API]
  │     Input:  each chunk + entity_vocabulary.yaml constraints
  │     Prompt: "Extract ONLY entities matching these types: [vocabulary].
  │              Normalise to canonical names using these aliases: [aliases].
  │              Extract ONLY causal, temporal, or confirmatory relationships.
  │              Do not extract generic descriptive relationships."
  │     Output per chunk: {entities: [], relationships: [], source_citation: {}}
  │     Cost:   ~$7 one-time for full corpus
  │
  ├─ Stage 3: Graph Assembly  [CPU, no LLM]
  │     Nodes = entities (deduplicated via vocabulary — "MG" → Minas_Gerais)
  │     Edges = relationships + co-occurrence weights + temporal offsets
  │     Each node carries: document_date (for point-in-time time-gating)
  │     Each edge carries: source_citation, relation_type, confidence
  │
  ├─ Stage 4: Local Search Index  [CPU, no LLM]  ← PRIMARY
  │     Dense vector index over entity embeddings (Bedrock Titan Embeddings, $0.0001/1K)
  │     Enables: entity neighbourhood retrieval at query time
  │     Covers: all 6 research modes in desiredstate.md
  │
  └─ Stage 5: Community Detection + Global Search  [optional, deferred]
        Leiden community detection (leidenalg, CPU, free)
        Community report summarisation (Claude Sonnet, ~$7.50 for 500 communities)
        Enables: corpus-wide thematic synthesis queries
        Rationale for deferral: all 6 defined research modes are entity-anchored
        (local search). Global search adds thematic synthesis but is not required
        for the primary PM workflow. Implement after local search is validated.

S3 artifacts:
  chunks.parquet              — chunk_id × text × source_citation × document_date
  entities.parquet            — entity × type × canonical_name × mention_count
  relationships.parquet       — (entity_a, entity_b, relation_type, weight,
                                  temporal_offset_months, sources[])
  entity_embeddings.parquet   — entity × embedding_vector  (for local search)
  # community artifacts added in Stage 5 when built
```

**Library**: Microsoft `graphrag` open-source as the foundation — implements chunking,
extraction, graph assembly, and local/global search with built-in OpenAI integration.
Override the default chunker with the propositional chunking strategy above.

**Search modes**:
- **Local search** (implement first): entity → neighbourhood traversal → source chunks
  → cited answer.  Covers all 6 research modes.  Fast, precise, grounded.
- **Global search** (implement later): community reports → thematic synthesis.
  For corpus-wide questions with no entity anchor.  Slower, broader.

#### Document Corpus — Full Inventory (All 4 Tiers)

All sources feed the GraphRAG pipeline. Tier 4 = irreplaceable local intelligence not
available in any structured form; Tier 1 = historical completeness. Only two scanned
sources require Textract OCR (~$104 one-time total); every other PDF source has a
digital text layer and uses `pdfplumber` at $0 OCR cost.

| Tier | Source | Docs | ~Useful Pages | Extraction | OCR Cost |
|------|--------|------|--------------|------------|----------|
| **4** | USDA GAIN (33 archive prefixes, 15 commodity groups) | 3,689 PDFs | ~21,900 | `pdfplumber` | $0 |
| **4** | CONAB Crop Surveys | 55 PDFs | ~1,100 | `pdfplumber` ✅ Text layer complete | $0 |
| **4** | WB CMO Outlook | 146 PDFs | ~2,450 | `pdfplumber` | $0 |
| **4** | USDA FAS Coffee WMT | 47 PDFs | ~660 | `pdfplumber` | $0 |
| **3** | WASDE Digital (2000–present) | 314 PDFs | ~8,500 | `pdfplumber` | $0 |
| **3** | **WASDE Scanned (1973–1994)** | **251 PDFs** | **~5,600** | **Textract OCR → filter** | **~$63** |
| **3** | WASDE TXT (1995–1999) | 60 TXTs | 60 files | `regex` / string | $0 |
| **3** | WAP Direct (2002–present) | 285 PDFs | ~6,300 | `pdfplumber` | $0 |
| **3** | **WAP archive.org (pre-2002)** | **163 PDFs** | **~3,450** | **Textract OCR → filter** | **~$41** |
| **3** | WAP Wayback HTML (1996–2002) | 67 HTML | ~90 equiv | `BeautifulSoup` | $0 |
| **3** | NASS Citrus Monthly Forecasts | 289 PDFs | ~3,500 | `pdfplumber` | $0 |
| **3** | SAGIS SWB Weekly Bulletins | 132 PDFs | ~920 | `pdfplumber` | $0 |
| **3** | UNICA Biweekly PDFs | 49 PDFs | ~340 | `pdfplumber` | $0 |
| **3** | UNICA Historical HTML | 41 HTML | ~41 equiv | `Playwright` + `BeautifulSoup` | $0 |
| **3** | MPOB Annual Stats HTML | 10 HTML | ~10 equiv | `BeautifulSoup` | $0 |
| **3** | MPOC Trade Stats HTML | 17 HTML | ~17 equiv | `BeautifulSoup` | $0 |
| **2** | NASS Citrus Annual/Summary | 54 PDFs | ~2,600 | `pdfplumber` | $0 |
| **2** | FNC Reports PDF | 56 PDFs | ~620 | `pdfplumber` | $0 |
| **2** | MPOC Market Highlights | 342 HTML | ~550 equiv | `BeautifulSoup` | $0 |
| **2** | USDA AMS Cotton Annual Quality | 14 PDFs | ~280 | `pdfplumber` | $0 |
| **2** | SAGIS CEC Crop Estimates | 3 PDFs | ~22 | `pdfplumber` | $0 |
| **2** | MPOB Overview PDFs | 7 PDFs | ~42 | `pdfplumber` | $0 |
| **1** | NASS Citrus Maturity/Freeze | 31 PDFs | ~149 | `pdfplumber` | $0 |
| **—** | ICCO Quarterly Bulletins | TBD | TBD | `pdfplumber` (digital) | $0 |

**Total (currently manifested): ~4,921 docs, ~49,500 useful pages, ~$104 one-time OCR**

> GAIN is the largest single source (3,689 reports across 33 archive prefixes / 15 commodity groups, ~22K
> pages). Full backfill for all prefixes completed via AWS Batch on 2026-05-22.

#### Page Filtering Strategy

The filter pipeline differs between digital sources (text already available) and scanned
sources (text locked in image). The principle: **never pay Textract for a page you could
have rejected for free**.

---

##### Digital PDF + HTML path (pdfplumber / BeautifulSoup)

All filters run on extracted text before writing `paragraphs.jsonl`.

**Stage 1 — Blank page detection** (universal):
```python
text = page.extract_text() or ""
if len(text.strip()) < 50:
    continue  # blank or near-blank — separator, image-only, or header-only
```

**Stage 2 — Cover/TOC pages by index** (skip before text inspection):

| Source | Skip page indices | Reason |
|--------|------------------|--------|
| WB CMO Outlook | 0, 1 | Copyright page + table of contents |
| NASS Citrus Annual/Summary | 0, 1 | Cover + table of contents |
| USDA AMS Cotton Annual | 0, 1 | Cover + table of contents |
| USDA GAIN | *none* | Page 0 header contains country, commodity, date, attaché name — critical for entity extraction |
| All others | *none* | Rely on Stage 3 pattern detection only |

**Stage 3 — Boilerplate section detection** (skip page if any pattern matches):
```python
SKIP_GLOBAL = [
    r"usda is an equal opportunity provider",
    r"to file a program discrimination complaint",
    r"conversion factors used in this report",
    r"\b1 metric ton\s*=\s*[\d.]+ (short tons|bushels)",
]

SKIP_BY_SOURCE = {
    "usda_wasde": [
        r"^\s*explanatory notes",           # methodology section, identical every issue
        r"world supply and use estimates",  # statistical summary appendix — data is in CSV
    ],
    "usda_gain": [
        r"usda foreign agricultural service\s*[\r\n]*$",  # last-page contact footer
    ],
    "usda_nass_citrus": [
        r"^\s*(appendix [a-z]|survey methodology|glossary of terms)",
    ],
    "usda_wap": [
        r"^\s*(conversion factors|unit conversion)",
    ],
    "wb_cmo_outlook": [
        r"^\s*statistical annex",  # price tables — Pink Sheet Excel covers these
    ],
    "usda_nass_citrus_annual": [
        r"^\s*(appendix|survey design|methodology)",
    ],
}
```

**HTML sources** — strip structural noise before chunking:
```python
for tag in soup.find_all(["nav", "header", "footer", "aside", "script", "style"]):
    tag.decompose()
# MPOC Market Highlights: keep only the article body
article = soup.find("article") or soup.find(class_="entry-content")
text = (article or soup).get_text(separator="\n", strip=True)
```

---

##### Scanned PDF path (Textract — WASDE 1973–1994 and WAP archive.org only)

Textract costs $0.01/page. Pre-filters run on the **page image** before any API call;
post-filters run on the returned text. Never send a page to Textract that a free check
could have rejected.

**Pre-filter 1 — Skip by index** (before Textract):
- WASDE: skip page index 0 (cover image, identical across all issues)
- WAP archive.org: skip page index 0 (cover)
- Any other known structural positions confirmed during a one-time sample review

**Pre-filter 2 — Image blank detection** (before Textract):
```python
import fitz  # PyMuPDF
from PIL import Image, ImageStat

def is_blank_page(fitz_page, dpi: int = 72) -> bool:
    pix = fitz_page.get_pixmap(dpi=dpi)  # low-res is sufficient for blank detection
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    stat = ImageStat.Stat(img.convert("L"))
    return stat.stddev[0] < 8  # near-zero variance = blank or near-blank page

if is_blank_page(page):
    continue  # free rejection — do not call Textract
```

**Post-filter — Boilerplate patterns** (after Textract, unavoidable for scanned):
Reconstruct text from Textract `LINE` blocks in reading order, then apply `SKIP_GLOBAL`
and the relevant `SKIP_BY_SOURCE` patterns (same dicts as the digital path). These
affect a small fraction of pages (~10%) so wasted OCR cost is minor.

Output format (`paragraphs.jsonl`) is identical to the digital path — downstream
GraphRAG indexing is source-agnostic regardless of whether text came from pdfplumber
or Textract.

---

### Layer 4: Query Orchestration (LangGraph Agent + FastAPI)

**FastAPI service** on Fargate (1 vCPU, 2GB, always-on in dev, ~$35/month):
- Server-Sent Events (SSE) for streaming responses to UI
- Reasoning trace per query stored in S3 (audit trail + future training data)
- Per-request timeout: 30s total; individual node timeout: 10s

**LangGraph agent nodes:**

| Node | Model | Purpose |
|------|-------|---------|
| PLANNER | Claude Haiku | Decompose query, classify retrieval types, build execution plan |
| SQL AGENT | Claude Haiku | Write + execute Athena SQL across silver.* tables |
| SHAP EXPLAINER | Claude Haiku | Fetch current SHAP breakdown, format top features with context |
| ANALOGUE FINDER | Claude Haiku | Query historical production-at-current-forecast-level (Phase 2) |
| GRAPHRAG LOCAL | Graph search | Entity neighborhood retrieval |
| GRAPHRAG GLOBAL | Graph search | Community synthesis for broad thematic questions |
| MCP TOOLS | Claude Haiku | Live news / weather alerts (Phase 3) |
| SYNTHESIZER | Claude Sonnet | Final answer with cited sources, streamed via SSE |
| ERROR HANDLER | — | Catches node failures, returns partial answer, logs to CloudWatch |

---

#### Managed Services — Bedrock Prompt Management + Guardrails

**The principle**: use Bedrock managed services where they solve the problem better
than custom code can.  Write custom code only where no managed service reaches.

---

##### Bedrock Prompt Management (all LLM nodes)

Every system prompt and user prompt template is stored in **Bedrock Prompt Management**
as a versioned resource, not hardcoded in Python.  Each LangGraph node references a
prompt by ARN (`promptId:version`).

Benefits:
- Prompt iteration without code deployment or Docker rebuild — publish a new version,
  nodes pick it up on next invocation
- Full version history and rollback
- A/B testing at the prompt level (directly feeds the Prompt Gallery capability)
- Model parameters (temperature, max_tokens, top_p) stored alongside the prompt,
  not scattered across the codebase

```python
# Every node calls prompts by ARN, never hardcodes strings
response = bedrock.invoke_model(
    modelId="anthropic.claude-3-haiku-20240307-v1:0",
    promptArn="arn:aws:bedrock:us-east-1::prompt/PLANNER_PROMPT:3",
    promptVariables={"query": user_query, "context": retrieved_context},
    guardrailIdentifier=GUARDRAIL_ID,   # attached to every call — see below
    guardrailVersion="DRAFT",
)
```

---

##### Bedrock Guardrails (every Bedrock API call)

A single **Bedrock Guardrail** resource is configured once and attached to every
Bedrock API call via `guardrailIdentifier`.  It runs transparently on both the input
(user query) and the output (model response) without any custom code.

What the Guardrail handles — replacing all custom security code:

| Concern | Custom code approach (replaced) | Bedrock Guardrails |
|---|---|---|
| Prompt injection / jailbreak | Regex pattern list | Native attack filter, production-hardened by AWS |
| Investment advice prohibition | Topic deny list in code | Configured topic policy — "deny responses that constitute investment advice" |
| Grounding validation | Manual citation check in Python | Contextual grounding check — response must be supported by retrieved context |
| PII redaction | Custom strip function | Built-in PII detection + redaction across 30+ entity types |
| Harmful content | None | Content filters (hate, violence, misconduct) |
| Word/phrase blocks | None | Configurable word filters |

```python
# Guardrail is defined once in Terraform / CDK:
guardrail = bedrock.create_guardrail(
    name="leviathan-agent-guardrail",
    topicPoliciesConfig={
        "topicsConfig": [{
            "name": "InvestmentAdvice",
            "definition": "Responses that constitute specific investment, trading, "
                          "or financial advice for the user",
            "type": "DENY",
        }]
    },
    contentPolicyConfig={...},          # harmful content thresholds
    sensitiveInformationPolicyConfig={  # PII types to redact
        "piiEntitiesConfig": [{"type": "EMAIL", "action": "ANONYMIZE"}, ...]
    },
    contextualGroundingPolicyConfig={
        "filtersConfig": [{
            "type": "GROUNDING",
            "threshold": 0.7,           # answer must be 70%+ grounded in context
        }]
    },
)
GUARDRAIL_ID = guardrail["guardrailId"]
```

**System prompt integrity**: LangGraph session state carries a `system_prompt_hash`
initialised at session start.  Bedrock Guardrails detects prompt override attempts
at the API level; the hash provides a secondary application-level check that logs
and terminates any session where state-level injection is attempted.

---

#### Structured Output Schemas (Pydantic — custom code, no managed service covers this)

JSON schema enforcement on LLM outputs is not handled by any Bedrock managed service.
Every LLM node uses Claude's `tool_use` structured output mode — the model must
populate the tool's input schema and cannot return free text.  Each response is
validated with a Pydantic model before passing downstream.

```python
class PlannerOutput(BaseModel):
    query_intent: Literal["production_forecast", "consequence_chain",
                          "counterfactual", "analyst_accuracy",
                          "tone_escalation", "point_in_time", "general"]
    retrieval_modes: list[Literal["sql", "graphrag_local", "shap",
                                   "analogue", "mcp"]]
    target_entities: list[str]        # e.g. ["Brazil", "arabica_coffee", "2021"]
    time_gate_date: str | None        # ISO date for point-in-time queries
    confidence: float                 # 0–1, model self-assessed plan quality

class SqlAgentOutput(BaseModel):
    sql_query: str
    tables_used: list[str]            # validated against ALLOWED_TABLES before execution
    query_intent: str

class GraphragLocalOutput(BaseModel):
    entities_found: list[str]
    relevant_chunk_ids: list[str]
    citations: list[dict]             # {source, document_date, page}
    retrieval_confidence: float

class ShapExplainerOutput(BaseModel):
    commodity: str
    top_features: list[dict]          # {feature_name, shap_value, direction}
    forecast_value: float
    forecast_confidence_interval: dict  # {low_80, high_80}

class SynthesizerOutput(BaseModel):
    answer: str
    citations: list[dict]             # {source, document_date, excerpt}
    confidence: Literal["high", "medium", "low", "insufficient_evidence"]
    caveats: list[str]                # known limitations of this answer
```

---

#### Retry + Graceful Degradation (custom code — no managed service covers this)

```python
def call_with_validation(
    prompt_arn: str,
    prompt_variables: dict,
    output_schema: type[BaseModel],
    node_name: str,
    max_retries: int = 1,
) -> BaseModel:
    for attempt in range(max_retries + 1):
        response = bedrock.invoke_model(
            promptArn=prompt_arn,
            promptVariables=prompt_variables,
            guardrailIdentifier=GUARDRAIL_ID,
            guardrailVersion="DRAFT",
        )
        try:
            return output_schema.model_validate_json(
                response.tool_calls[0]["input"]
            )
        except (ValidationError, IndexError, KeyError) as e:
            if attempt < max_retries:
                # Re-prompt once with the specific validation error
                prompt_variables["_validation_error"] = str(e)
            else:
                logger.error("node=%s validation_failed attempts=%d error=%s",
                             node_name, max_retries + 1, e)
                cloudwatch.put_metric_data(
                    Namespace="Leviathan/Agent",
                    MetricData=[{"MetricName": f"{node_name}ValidationFailure",
                                 "Value": 1, "Unit": "Count"}]
                )
                raise NodeValidationError(node_name, str(e))
```

**LangGraph error routing**: every node has a conditional edge:
- On success → next planned node
- On `NodeValidationError` → ERROR_HANDLER node
- ERROR_HANDLER returns partial context assembled so far with an explicit
  `"[partial answer — {node} failed]"` prefix rather than hanging or returning empty

---

#### SQL Safety (custom code — no managed service validates LLM-generated SQL)

```python
ALLOWED_TABLES = {
    "silver_weather", "silver_production", "silver_sd_balance",
    "silver_crop_progress", "silver_model_predictions", "silver_shap_values",
    "silver_psd", "silver_nass_citrus", "silver_fgis", "silver_esr", ...
}
FORBIDDEN_KEYWORDS = {"drop", "delete", "insert", "update", "create",
                       "alter", "truncate", "grant", "revoke"}

def validate_sql(query: str, tables_used: list[str]) -> None:
    lower = query.lower()
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", lower):
            raise SqlSafetyError(f"Forbidden keyword: {kw}")
    for table in tables_used:
        if table not in ALLOWED_TABLES:
            raise SqlSafetyError(f"Table not in allowlist: {table}")
    if "cross join" in lower and " on " not in lower:
        raise SqlSafetyError("Unbounded CROSS JOIN rejected")
```

SQL validation failure re-prompts once with the error before routing to ERROR_HANDLER.
SELECT-only enforcement means a hallucinated `DROP TABLE` never reaches Athena.

---

**Trusted domains** (MCP TOOLS — allowlist before passing external content to LLM):
`fas.usda.gov`, `ers.usda.gov`, `nass.usda.gov`, `ico.org`, `icco.org`,
`fao.org`, `conab.gov.br`, `federaciondecafeteros.org`, `inmet.gov.br`,
`reuters.com`, `bloomberg.com`, `mpob.gov.my`, `sagis.org.za`, `dalrrd.gov.za`,
`cepea.esalq.usp.br`

**Estimated per-query cost**: ~$0.02 (Haiku routing + Sonnet synthesis)

---

#### Langfuse — Agent Observability, Experimentation, and Evaluation

Langfuse is the observability and experiment-tracking layer for the agent system,
serving the same role that MLflow serves for the ML layer.  MLflow's mental model
(discrete training runs with scalar metrics) does not fit agent invocations, which
are hierarchical call trees spanning multiple nodes, each with their own latency,
token count, cost, and input/output.  Langfuse is built for exactly this shape.

**Integration** — one callback, zero node-level changes:
```python
from langfuse.callback import CallbackHandler

langfuse_handler = CallbackHandler(
    public_key="...",
    secret_key="...",
    session_id=session_id,
    user_id=user_id,
)
# Every LangGraph node is automatically captured as a span
result = graph.invoke(
    {"query": user_query},
    config={"callbacks": [langfuse_handler]},
)
```

**What Langfuse provides:**

**Tracing** — every LangGraph node execution is captured as a span in a
hierarchical trace.  The PLANNER span shows which retrieval modes it chose and
which entities it targeted.  The SQL AGENT span shows the generated SQL and the
Athena result set.  The SYNTHESIZER span shows what context it received and what
it produced.  When something goes wrong — wrong entity retrieved, bad SQL generated,
hallucinated citation, Guardrail block — the exact failing node is visible with its
full input/output.  Debugging agent failures without this is guesswork.

Every span records the following latency and throughput metrics, aggregated in
Langfuse dashboards across all traces:

| Metric | Definition | Why it matters |
|--------|------------|----------------|
| **TTFT** (Time to First Token) | Wall-clock ms from request sent to first SSE token received | Primary UX signal — PM perceives the system as slow if TTFT > 1.5s even if total latency is acceptable |
| **TPS** (Tokens Per Second) | Output tokens ÷ generation time | Throughput of the SYNTHESIZER node; degrades under concurrent load |
| **Total latency** | End-to-end ms from query receipt to stream close | SLA target: p50 < 5s, p95 < 12s for a complete cited answer |
| **Node latency** | Per-span ms for each LangGraph node | Identifies which node is the bottleneck (typically GRAPHRAG LOCAL or SQL AGENT waiting on Athena) |
| **Token counts** | Prompt tokens + completion tokens per span | Cost attribution per node, per query type |

Percentile targets tracked in Langfuse and mirrored to CloudWatch:

```
TTFT:          p50 < 800ms    p95 < 2s
TPS:           p50 > 30 tok/s  (Haiku streaming baseline)
Total latency: p50 < 5s       p95 < 12s
Node latency:  PLANNER p95 < 1s
               SQL AGENT p95 < 4s  (Athena cold start included)
               GRAPHRAG LOCAL p95 < 2s
               SYNTHESIZER p95 < 6s
```

Percentile degradation beyond p95 thresholds → CloudWatch alarm → SNS alert.
TTFT is the most PM-visible metric and should be monitored continuously; a TTFT
regression is often the first signal of a Bedrock throughput issue before total
latency degrades.

**Prompt versioning and experimentation** — Langfuse has prompt management that
integrates with its evaluation harness.  Two versions of the PLANNER prompt can be
A/B tested on the standardised evaluation dataset, with output quality scored
automatically.  The winner is promoted; the loser is archived with its trace history.
Division of responsibility with Bedrock Prompt Management: Langfuse for
experimentation and iteration during development; Bedrock Prompt Management for
production serving once a prompt version is validated.

**Evaluation datasets** — the 30–50 standardised test prompts (covering all six
research modes) live in Langfuse as a dataset.  Each item has an input query,
expected output characteristics, and scoring criteria (entity recall, citation
accuracy, grounding score, schema compliance, latency).  Running an evaluation
produces aggregated metrics per node and per query type — the systematic harness
that would otherwise be built manually on top of MLflow.

**Human annotation** — individual traces can be flagged for review and scored by a
human analyst.  Over time this builds a labelled corpus of good and bad agent
responses — directly becoming the RLHF training data referenced in the S3 reasoning
trace store (Layer 4 FastAPI).  The annotation interface is built into Langfuse;
no separate tooling needed.

**User feedback loop** — thumbs up/down on responses in the React dashboard routes
the signal to Langfuse and tags the corresponding trace.  Over time this accumulates
a labelled corpus of which answers the PM actually found useful, distinct from
analyst-labelled quality scores.  Both signals are available for prompt tuning.

**Division with MLflow:**

| Concern | Tool |
|---|---|
| ML model training experiments, hyperparameter search, feature set comparison | MLflow |
| ML model artifacts, versioning, registry, canary deployment | MLflow + SageMaker Model Registry |
| Model comparison study (Haiku vs Sonnet vs quantized) — agent layer | Langfuse evaluation runs |
| Agent prompt A/B testing, iteration, version promotion | Langfuse |
| Agent call traces, per-node latency, token costs, error root-cause | Langfuse |
| Standardised evaluation dataset, aggregated quality metrics | Langfuse |
| Human annotation of agent responses, RLHF data accumulation | Langfuse |
| User feedback (thumbs up/down) linked to traces | Langfuse |

**Cost**: generous free tier (50K observations/month); self-hosted option available
on a single Fargate container if traces must stay inside the AWS account.

---

#### Evaluation Regression Gating in CI (GitHub Actions)

The Langfuse evaluation dataset runs automatically as part of the GitHub Actions
CI pipeline on every PR that touches agent code, prompt ARNs, or LangGraph node
logic.  This is the agent-layer equivalent of pytest gating ML code changes —
a prompt change that silently degrades grounding or a code change that regresses
TTFT ships nothing until the evaluation passes.

**CI flow:**

```
PR opened (changes to: jobs/agent/*, configs/prompts/*, langfuse dataset)
  │
  ├─ Existing gates (unchanged):
  │    pytest + mypy + Docker build → ECR → Batch job definition update
  │
  └─ Agent evaluation gate (new):
       GitHub Actions: run_agent_eval.yml
         1. Checkout PR branch
         2. Pull the 30–50 standardised test prompts from Langfuse dataset
         3. Run each prompt against the PR branch agent
            (spins up ephemeral FastAPI container pointing at dev bucket)
         4. Log all traces + metrics to Langfuse under run_id=pr-{number}
         5. Fetch baseline metrics from main branch (stored in Langfuse)
         6. Compare on regression thresholds:
              TTFT p95          regression > 20%  → FAIL
              grounding score   drops below 0.70  → FAIL
              schema compliance drops below 0.95  → FAIL
              entity recall     drops below 0.80  → FAIL
              total cost/query  regression > 30%  → WARN (not blocking)
         7. Post comparison table as PR comment
         8. If any FAIL threshold breached → CI status = failed → merge blocked
         9. On merge to main → update baseline metrics in Langfuse

```

**PR comment format** (posted automatically by the action):

```
## Agent Evaluation Results — PR #142 vs main

| Metric              | main (baseline) | PR #142  | Delta    | Status |
|---------------------|-----------------|----------|----------|--------|
| TTFT p50            | 620ms           | 590ms    | -4.8%    | ✅     |
| TTFT p95            | 1,840ms         | 2,210ms  | +20.1%   | ❌ FAIL|
| Grounding score     | 0.81            | 0.79     | -2.5%    | ✅     |
| Schema compliance   | 0.97            | 0.97     | 0.0%     | ✅     |
| Entity recall       | 0.84            | 0.82     | -2.4%    | ✅     |
| Cost / query        | $0.019          | $0.021   | +10.5%   | ⚠️ WARN|

❌ 1 threshold breached — merge blocked.
Full trace comparison: https://cloud.langfuse.com/project/.../runs/pr-142
```

**Baseline management**: on every merge to main, the action updates the stored
baseline metrics in Langfuse.  Baselines only move forward — a merge that improves
TTFT p95 raises the bar for the next PR.

**Scope of the gate**: not every PR triggers the full evaluation.  Path filters
limit it to changes that could affect agent behaviour:
```yaml
on:
  pull_request:
    paths:
      - "jobs/agent/**"
      - "src/leviathan/agent/**"
      - "configs/prompts/**"
      - "configs/sources/entity_vocabulary.yaml"
```
Infrastructure-only PRs (Terraform, Dockerfile, silver transforms) skip the
evaluation gate and run only the standard pytest + mypy + build checks.

### Layer 5: React / TypeScript Chat UI

**Core components:**

| Component | Description |
|-----------|-------------|
| Chat panel | Streaming SSE, markdown rendering, message history |
| Source citations | PDF/bulletin references linked to raw S3 key + page |
| SHAP waterfall | Recharts inline showing feature contributions per prediction |
| Production forecast | Current forecast vs. historical range + PSD consensus band |
| Fundamental alerts | Active anomaly flags (CONAB revision outlier, WASDE surprise, export pace, NASS crop condition) |
| Spread monitor table | All active spread signals, z-scores, directional conviction |
| Analogue lookup (Phase 2) | "Last time production was at this level: [years] → price did: [range]" |
| Prompt gallery | Curated queries for common analytical tasks |

**Deployment:** S3 + CloudFront static site.

---

### Layer 6: Operations + Monitoring

**Data quality (CloudWatch + SNS):**
- Last successful ingest timestamp per source (16+ sources)
- File count vs. expected (e.g., 31 monthly CHIRPS tasks completed?)
- Silver DQ report failures (existing `run_silver_quality_checks`)
- WASDE release date monitoring (alert if not ingested within 2h of scheduled release)

**Model monitoring:**
- Monthly feature distribution drift vs. training snapshot (evidently → Clarify)
- Prediction drift: distribution of `production_forecast` vs. training distribution
- Rolling 90-day directional accuracy vs. training-period accuracy
- Alert threshold: any metric outside 2σ of training baseline → model set to Pending

**Backtesting framework (Phase 2, requires price data):**
- Walk-forward validation: train on years N−k through N−1, predict year N
- Spread-level P&L: signal × realized spread return
- Slippage + transaction cost modeling
- Maximum drawdown, Sharpe ratio, per-commodity attribution

---

## Build Phases

| Phase | Deliverable | Unlocks |
|-------|------------|---------|
| **P0** | USDA PSD bronze + silver (`silver_sd_balance` Athena table) + USDA NASS QuickStats bronze + silver (`silver_crop_progress` Athena table) | S/U ratio + Crop Progress features available. **Raw ingestion for both already complete as of May 20.** |
| **P1** | CONAB bronze transform (pdfplumber, revision tables) + WASDE ingestion (CSV structured + PDF narrative) + USDA AMS Export Inspections bronze + silver | Revision surprise features for coffee + all commodities; WASDE narrative in GraphRAG corpus; `export_pace_z` feature live for US corn/soy/wheat |
| **P2** | WMT bronze (S/D tables + paragraphs) + SAGIS/CEC + FNC Excel + MPOB bronze + ICCO + USDA GAIN + AMS Cotton (weekly classing files, tenderable %) + NASS Citrus + World Bank Pink Sheet (raw ingest + bronze) + World Bank CMO Outlook (raw PDF ingest only) | Full feature set for all 31 commodities; GraphRAG corpus substantially complete. Input cost features available. CMO Outlook PDFs staged for P5 indexing. AMS Cotton Annual Quality PDFs (1986–2025) already in S3. |
| **P3** | Feature engineering pipeline → SageMaker Feature Store (offline); all feature groups defined and populated | Point-in-time correct features stored; lookahead bias protection in place |
| **P4** | Tier 1 origin stress models + Tier 2 S/D models (arabica proof of concept first) + Model Registry | First working production forecasts; daily inference pipeline running |
| **P5** | Entity vocabulary YAML + GraphRAG indexing pipeline (CONAB + WMT + WASDE corpus first) | Knowledge graph queryable; GraphRAG global/local search functional |
| **P6** | LangGraph agent + FastAPI/Fargate + SSE | Query orchestration layer functional end-to-end |
| **P7** | React/TS chat UI MVP (chat + SHAP waterfall + citations + alerts panel) | User-facing product |
| **P8** | Price data ingestion (futures + FX) + CFTC COT disaggregated ingestion + analogue lookup engine | Mispricing z-score signal; `cot_net_managed_money_z` contrarian positioning features live for all Tier 3 spread pairs |
| **P9** | Tier 3 spread signal models | Full spread trading signals; system purpose fulfilled |
| **P10** | Drift monitoring (evidently on Batch → migrate to Clarify) + data quality dashboard | Production operations |
| **P11** | MCP news tools + INMET weather alerts | Live context layer for the agent |
| **P12** | Backtesting framework + walk-forward validation | Signal validation and Sharpe attribution |
| **P13** | Prod Terraform environment + remaining commodity coverage gaps | Production-ready deployment |

---

## Monthly Cost Model (Dev)

| Component | Est. Cost |
|-----------|-----------|
| S3 (~500GB) | $12 |
| Glue (daily weather, monthly FAOSTAT + feature jobs) | $8 |
| Batch Fargate (inference + backfills + training + drift) | $15 |
| SageMaker Feature Store offline (S3 + Glue catalog) | ~$1 |
| SageMaker Model Registry | $0 |
| Athena queries | $3 |
| FastAPI on Fargate (always-on) | $35 |
| Bedrock (Claude Haiku GraphRAG + queries; Sonnet synthesis) | $10–20 |
| CloudWatch + SNS | $5 |
| **Total dev** | **~$90–100/month** |

No SageMaker inference endpoints. No persistent vector database. No RDS.
All graph artifacts in S3 Parquet, loaded into memory at query time via Athena.

---

## Future Work

Items that are architecturally understood, commercially valuable, and have a clear
implementation path — but are explicitly out of scope for the current build due to
licensed data requirements, compute budget, or backtest history constraints.

---

### Licensed Price Data: DCE and JSE Contracts

Leviathan's current price data layer covers 12 US/ICE contracts (yfinance, free) and
6 additional European/Asian contracts (Euronext rapeseed, Bursa Malaysia palm oil,
ICE London robusta coffee and white sugar, B3 arabica coffee — scraped via
Investing.com internal API, research-grade).

**The following 5 contracts require a commercial data license for production use:**

| Contract | Exchange | Why it matters |
|----------|----------|----------------|
| Soybean Meal futures | DCE (Dalian) | China crushes ~30% of global soy; DCE price leads CBOT in tight-stock regimes |
| Soybean Oil futures | DCE (Dalian) | Chinese vegetable oil balance; biodiesel mandate proxy |
| No.1 Soybeans futures | DCE (Dalian) | Domestic China bean price; import parity calculation |
| White Maize futures | JSE/SAFEX | Southern African food-security commodity; white/yellow premium = food-security bid |
| Yellow Maize futures | JSE/SAFEX | SA feedgrain; shares all SAGIS weather features with white maize |

Neither DCE nor JSE exposes historical individual delivery month data through any free
Western aggregator. DCE data requires a terminal subscription (Wind, Bloomberg) or a
direct DCE data partnership. JSE/SAFEX data requires a JSE data license or a South
African broker datafeed.

**Statement for production deployment**: "We have the global contracts; the Chinese
domestic (DCE) and South African (JSE/SAFEX) contracts require a data license, scoped
for P13 production deployment. All model architecture and features for these contracts
are designed and documented — the data gap is the only blocker."

**Impact on current build**: The intercommodity spread pairs involving DCE (Pair 3:
soybeans_cbot / soybeans_no_1_dce) and JSE (Pair 6: SA white maize / yellow maize)
are architecturally complete — Tier 1/2 features are built from SAGIS and CHIRPS.
Calendar spread pairs for DCE/JSE contracts are deferred pending licensed data.
All other 26 contracts are unaffected.

---

### Government Intervention Risk: Country-Level Food CPI

The current system uses manually-coded binary flags for export policy interventions
(`india_export_policy_flag`, `russia_export_quota_flag`, `indonesia_biodiesel_flag`).
These are reactive — they are coded after the restriction is announced.

A dynamic intervention risk feature is possible and would make the flags predictive:

**Mechanism**: High domestic food CPI in a major producing country → government
faces political pressure to restrict exports to suppress domestic prices → physical
supply exits the global market → price spike in the affected commodity.

Documented historical precedents:
- **India** (wheat, 2022): domestic CPI-food running >8% YoY → sudden wheat export ban May 2022
- **India** (rice, 2023): domestic food inflation → broken rice export ban + non-basmati rice ban
- **Indonesia** (CPO, 2022): domestic cooking oil shortage → palm oil export ban April–May 2022
- **Russia** (wheat, recurring 2022–2024): domestic bread price protection → export quota/floor price regime
- **Argentina** (soy complex, recurring): capital control tightening → farmer silo-bag withholding incentive intensifies

**Proposed features** (all scoped for Phase 3):

| Feature | Mechanism | Countries |
|---------|-----------|-----------|
| `food_cpi_yoy_z_{country}` | Domestic food CPI YoY % vs. 5yr rolling z-score | India, Russia, Indonesia, Ukraine, Argentina |
| `food_cpi_intervention_risk_{country}` | Binary: food_cpi_yoy_z > 1.5σ AND production_miss flag active | Same |

When `food_cpi_intervention_risk_india = 1`, it raises the probability that the
`india_export_policy_flag` fires within the next 60–90 days — before the announcement,
not after. This converts a lagging indicator into a leading one.

**Replaces**: manually-coded binary flags in `configs/sources/policy_flags.yaml` for
the countries above. Manual flags remain as ground truth for the historical training
labels; the CPI feature becomes the predictive input.

**Free data source**: World Bank DataBank API (`api.worldbank.org/v2/country/{iso}/indicator/FP.CPI.TOTL.ZG`)
covers CPI-food by country in JSON, no API key required, annual and quarterly, back
to 1970s for most countries. Monthly granularity requires IMF IFS or OECD.Stat
(both free with registration). FRED carries US CPI-food and several OECD-derived
country series.

**Why soil pH is NOT in this list**: Soil pH is a static variable on annual timescales
(managed by farmers over multi-year liming cycles) and has zero marginal predictive
value for inter-annual crop yield variation. The long-run yield potential effects of
soil quality are already captured in `faostat_production_trend_dev`. SoilGrids (ISRIC)
offers free global 250m soil pH data, but adding it would not improve model accuracy
for the prediction targets Leviathan uses.

---

### Individual Delivery Month History (Calendar Spread Backtesting)

yfinance and Investing.com both provide continuous front-month contracts only.
Historical individual delivery months (e.g., ZCZ22.CBT, KC H23.NYB) are deleted
from free aggregators after contract expiry.

**Blocker for**: Calendar spread pairs C1–C6 walk-forward backtesting. The current
build can generate live spread snapshots from active deferred months, but cannot
backtest the calendar spread signal over a meaningful historical window.

**Solution**: Quandl CHRIS dataset (Nasdaq Data Link). CHRIS/CME_C1, C2, C3 provide
first, second, and third nearby continuous roll-adjusted series for all CBOT/ICE
contracts, back to the 1960s for grains. Free tier (50 calls/day) is sufficient for
a one-time historical backfill of 12 contracts × 3 tenors = 36 series. Scoped for P8.

---

### Non-US Exchange Calendar Spreads

Euronext MATIF (wheat, corn, rapeseed), Bursa Malaysia/DCE (palm olein), JSE (SA maize),
and B3/BMF (campinas corn, arabica) calendar spreads are documented in the spread pairs
table but deferred pending:
1. Individual delivery month history (see above)
2. Licensed data for DCE and JSE (see above)
3. Confirmation that intercommodity spread models leave meaningful residual
   unexplained — add only if cross-exchange spread signals are insufficient

---

### MODIS NDVI Active Fire / Deforestation Layer

MODIS MOD14A1 active fire product (500m, daily) combined with Hansen Global Forest
Change (annual deforestation rate) for key growing regions. Value: Brazilian Cerrado
deforestation pace correlates with area expansion for soy and corn; Sumatra/Kalimantan
fire season correlates with palm yield stress via smoke-induced radiation deficit.
Both datasets are free (NASA EARTHDATA). Scoped for P4 model refinement once Tier 1
baseline is established.

---

### IOD (Indian Ocean Dipole) and MJO (Madden-Julian Oscillation)

ONI (ENSO) is already in silver. The IOD and MJO provide independent, orthogonal
climate forcing not captured by ONI:
- **IOD**: positive IOD → East African drought (Ethiopia arabica origin stress) → negative IOD → Australia/SE Asia flooding (rice, palm). NOAA publishes the Dipole Mode Index (DMI) free monthly.
- **MJO**: 30–90 day intraseasonal oscillation; drives active/break monsoon phases in India and SE Asia on sub-seasonal timescales. CPC publishes the RMM index free weekly.

Both are free. IOD is a one-session ingest (same pattern as ONI). MJO adds sub-seasonal
resolution to rice, cotton, and palm oil models. Scoped for P4 model refinement.
