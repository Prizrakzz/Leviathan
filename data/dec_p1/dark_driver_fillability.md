# Dark-driver fillability census (dec_p1, X2 corpus) -- 2026-08-21T14:28:01Z

Artifact: `data/dec_p1/dark_driver_fillability.json`. Corpus: 5,936 chunk objects / 1,387,697 props, driver-dark 1,117,010 (80.5%).

**The question.** for each dark DAG driver id: author terms, bind a silver table, or waive honestly -- decided by measurement on all three axes

**Terms are NOT ids.** Derived from each driver's own `evidence_query` / `blurb` / `mechanism` / `region`, >=2 tokens. The genericity ceiling is MEASURED, not chosen: it is the p90 corpus frequency of the 495 multi-token terms `driver_slices.yaml` ALREADY accepts (median 4 props, max 99,863), i.e. **306 props** -- a new term may not be vaguer than the vaguest term the product already lives with. 70 of 3737 candidate terms were dropped that way. A further 27 ids are flagged `concentration_risk` (>60% of their mass on one term) and are withheld from FILLABLE.

| verdict | n |
|---|---:|
| BINDABLE | 67 |
| HONEST-WAIVE | 42 |
| FILLABLE-BY-TERM | 14 |

The two axes are orthogonal -- cross-tab:

| fillable_by_term | bindable_now | n |
|---|---|---:|
| False | False | 42 |
| False | True | 67 |
| True | False | 4 |
| True | True | 10 |

## Every dark id, ranked by driver-dark prop mass

| driver_id | verdict | anchored props | all dark props | anchored terms | top term | share | silver refs |
|---|---|---:|---:|---:|---|---:|---|
| `us_export_pace` | FILLABLE-BY-TERM | 389 | 3253 | 14 | `red winter wheat` | 58% | esr_exports, export |
| `Canada_production` | BINDABLE | 278 | 305 | 19 | `statistics canada` | 84% | wap_nonUS_revision |
| `China_vegoil_demand` | BINDABLE | 270 | 270 | 28 | `food service` | 66% | consumption |
| `flowering` | FILLABLE-BY-TERM | 234 | 429 | 26 | `during april` | 46% | heat_stress_z, nass_crop_progress_ge_z |
| `China_food_demand` | BINDABLE | 224 | 271 | 21 | `food service` | 66% | consumption |
| `replanting_cycle` | FILLABLE-BY-TERM | 205 | 432 | 31 | `west africa` | 34% | area |
| `cercospora_beet` | HONEST-WAIVE | 174 | 182 | 24 | `sugar beet` | 86% | - |
| `area` | FILLABLE-BY-TERM | 170 | 333 | 28 | `planted acreage` | 48% | area |
| `blocking_high` | FILLABLE-BY-TERM | 164 | 277 | 30 | `western canada` | 59% | - |
| `aquaculture_feed_demand` | BINDABLE | 164 | 164 | 28 | `aquaculture feed` | 86% | consumption |
| `GMO_phytosanitary_policy` | FILLABLE-BY-TERM | 161 | 206 | 20 | `import permits` | 47% | - |
| `vernalization_failure` | HONEST-WAIVE | 148 | 2057 | 29 | `red winter wheat` | 92% | - |
| `China_domestic_crop` | FILLABLE-BY-TERM | 147 | 433 | 7 | `northeast china` | 40% | production |
| `export_pace_lag` | FILLABLE-BY-TERM | 143 | 520 | 24 | `ivory coast` | 28% | esr_exports, export |
| `conab_production_revision` | FILLABLE-BY-TERM | 143 | 452 | 17 | `crop forecast` | 53% | conab_production_revision |
| `buffer_stock_release` | FILLABLE-BY-TERM | 127 | 248 | 27 | `buffer stock` | 43% | beginning_stock |
| `Thailand_production` | FILLABLE-BY-TERM | 123 | 205 | 12 | `thai sugar` | 53% | production |
| `biennial_bearing` | FILLABLE-BY-TERM | 108 | 355 | 24 | `west africa` | 42% | - |
| `Vietnam_export_tax_policy` | FILLABLE-BY-TERM | 105 | 332 | 22 | `export restrictions` | 46% | export |
| `FUNCAFE` | FILLABLE-BY-TERM | 105 | 105 | 29 | `coffee financing` | 36% | - |
| `India_ethanol_diversion` | HONEST-WAIVE | 94 | 280 | 26 | `exportable surplus` | 39% | - |
| `export_parity` | BINDABLE | 87 | 143 | 6 | `price falls` | 25% | export |
| `INR_PKR_weakness` | BINDABLE | 79 | 387 | 25 | `world prices` | 45% | fred_fx_macro |
| `corn_rootworm` | HONEST-WAIVE | 72 | 94 | 19 | `reduced yields` | 77% | - |
| `labor_shortage` | HONEST-WAIVE | 72 | 72 | 33 | `labor shortages` | 69% | - |
| `Algeria_tender_specs` | HONEST-WAIVE | 69 | 76 | 35 | `black sea wheat` | 49% | - |
| `leaf_rust` | HONEST-WAIVE | 60 | 174 | 19 | `grain fill` | 40% | - |
| `INR_THB_VND_weakness` | BINDABLE | 56 | 247 | 25 | `world prices` | 70% | fred_fx_macro |
| `stockholding_limit` | HONEST-WAIVE | 52 | 52 | 40 | `price stability` | 85% | - |
| `pre_harvest_sprouting` | HONEST-WAIVE | 50 | 1965 | 24 | `red winter wheat` | 97% | - |
| `domestic_crush_demand` | BINDABLE | 44 | 151 | 12 | `canada canola` | 61% | crush_margin_z |
| `consumption` | BINDABLE | 42 | 368 | 14 | `consumption growth` | 57% | consumption |
| `IOD_positive` | BINDABLE | 42 | 191 | 24 | `west africa` | 78% | iod_climate |
| `wheat_midge` | HONEST-WAIVE | 42 | 49 | 25 | `north dakota` | 86% | - |
| `boll_set` | BINDABLE | 41 | 129 | 20 | `growth stage` | 36% | inseason_weather_dense |
| `aphids` | HONEST-WAIVE | 41 | 49 | 30 | `pest pressure` | 51% | - |
| `canada_rapeseed_import_supply` | BINDABLE | 39 | 481 | 8 | `crush volume` | 34% | import |
| `Argentina_crush_capacity` | BINDABLE | 37 | 57 | 22 | `crush utilization` | 37% | export |
| `aqua_season` | HONEST-WAIVE | 36 | 136 | 26 | `price strength` | 70% | - |
| `CBD` | HONEST-WAIVE | 34 | 106 | 30 | `exportable supply` | 31% | - |
| `PDO` | HONEST-WAIVE | 34 | 34 | 21 | `multi year` | 100% | - |
| `china_rsm_import` | BINDABLE | 33 | 171 | 11 | `imports from canada` | 40% | import |
| `China_soyoil_stocks` | BINDABLE | 30 | 52 | 9 | `chinese ports` | 56% | stock |
| `hessian_fly` | HONEST-WAIVE | 27 | 1931 | 28 | `red winter wheat` | 98% | - |
| `consumption_demand` | BINDABLE | 22 | 211 | 23 | `orange juice consumption` | 52% | consumption |
| `hail` | HONEST-WAIVE | 22 | 83 | 14 | `weather events` | 64% | - |
| `buyer_tender_demand` | BINDABLE | 20 | 266 | 20 | `world prices` | 65% | import |
| `tenderable_collapse` | BINDABLE | 19 | 130 | 18 | `cocoa stocks` | 72% | stock |
| `eu_import_demand` | BINDABLE | 17 | 39 | 16 | `against domestic` | 38% | import |
| `Thailand_white_exports` | BINDABLE | 15 | 49 | 12 | `thailand exports` | 29% | export |
| `septoria` | HONEST-WAIVE | 13 | 240 | 24 | `wet conditions` | 38% | - |
| `shattering` | HONEST-WAIVE | 13 | 26 | 30 | `harvest loss` | 50% | - |
| `china_rapeseed_supply` | BINDABLE | 12 | 229 | 11 | `domestic oilseed` | 40% | production |
| `crush_margin_expansion` | BINDABLE | 11 | 172 | 17 | `crush volume` | 94% | crush_margin_z |
| `import_parity_floor` | HONEST-WAIVE | 11 | 52 | 6 | `import parity` | 42% | - |
| `aflatoxin` | HONEST-WAIVE | 11 | 11 | 22 | `aflatoxin contamination` | 100% | - |
| `GMO_white_policy` | HONEST-WAIVE | 10 | 154 | 18 | `non gmo` | 47% | - |
| `cec_production_revision` | BINDABLE | 10 | 152 | 18 | `larger crop` | 86% | sagis_cec_revision |
| `white_mold` | HONEST-WAIVE | 10 | 10 | 24 | `upper midwest` | 100% | - |
| `abandonment` | BINDABLE | 9 | 263 | 22 | `harvest area` | 77% | area |
| `tan_spot` | HONEST-WAIVE | 8 | 105 | 23 | `wet conditions` | 86% | - |
| `eu_neonic_ban` | HONEST-WAIVE | 8 | 23 | 31 | `area decline` | 65% | - |
| `protein_premium` | HONEST-WAIVE | 7 | 2866 | 4 | `red winter wheat` | 66% | - |
| `refinery_outages` | HONEST-WAIVE | 7 | 12 | 20 | `capacity constraints` | 42% | - |
| `consumption_growth` | BINDABLE | 6 | 327 | 28 | `consumption growth` | 64% | consumption |
| `import_crush_margin` | BINDABLE | 6 | 313 | 15 | `imported soybean` | 60% | crush_margin_z |
| `corn_borer` | HONEST-WAIVE | 6 | 17 | 24 | `european corn` | 65% | - |
| `sudden_death_syndrome` | HONEST-WAIVE | 6 | 13 | 24 | `pod fill` | 31% | - |
| `biennial_on_year` | HONEST-WAIVE | 5 | 208 | 4 | `off year` | 38% | - |
| `biennial_off_year` | HONEST-WAIVE | 5 | 204 | 5 | `off year` | 38% | - |
| `china_rapeseed_import` | BINDABLE | 5 | 144 | 15 | `imports from canada` | 48% | import |
| `tenderable_quality_squeeze` | BINDABLE | 5 | 83 | 18 | `cotton stock` | 87% | ams_cotton_quality |
| `us_export_competition` | BINDABLE | 5 | 70 | 12 | `brazilian exports` | 44% | fgis_export_pace_yoy |
| `import_demand_destination` | BINDABLE | 4 | 169 | 16 | `west africa` | 88% | import |
| `Florida_orange_production` | BINDABLE | 3 | 31 | 13 | `domestic availability` | 68% | nass_citrus_revisions |
| `certified_stocks_decline` | BINDABLE | 3 | 18 | 20 | `stocks decline` | 39% | stock |
| `wheat_streak_mosaic` | HONEST-WAIVE | 3 | 5 | 27 | `mosaic virus` | 60% | - |
| `AMO` | HONEST-WAIVE | 3 | 3 | 37 | `frequency and intensity` | 100% | - |
| `canada_canola_export_pace` | BINDABLE | 2 | 178 | 15 | `canada canola` | 52% | export |
| `soyoil_palm_premium` | BINDABLE | 2 | 118 | 17 | `price sensitive` | 71% | spread |
| `GBP_cross` | BINDABLE | 2 | 84 | 22 | `spread between` | 76% | fred_fx_macro |
| `SAM` | HONEST-WAIVE | 2 | 36 | 19 | `central brazil` | 78% | - |
| `white_food_demand` | BINDABLE | 2 | 11 | 19 | `strong regional` | 46% | consumption |
| `oil_share` | BINDABLE | 2 | 10 | 11 | `oil share` | 80% | crush_margin_z |
| `rapeoil_share` | HONEST-WAIVE | 2 | 10 | 6 | `oil share` | 80% | - |
| `rapeoil_demand` | BINDABLE | 2 | 8 | 11 | `biofuel demand` | 75% | consumption |
| `kc_chi_spread` | BINDABLE | 2 | 6 | 4 | `chicago wheat` | 50% | spread |
| `ear_rot` | HONEST-WAIVE | 1 | 146 | 15 | `grain quality` | 84% | - |
| `stink_bug` | HONEST-WAIVE | 1 | 70 | 13 | `seed quality` | 69% | - |
| `export_parity_floor` | HONEST-WAIVE | 1 | 49 | 12 | `export parity` | 59% | - |
| `regional_import_demand` | BINDABLE | 1 | 32 | 5 | `maize imports` | 88% | export |
| `lodging` | HONEST-WAIVE | 1 | 18 | 19 | `harvest loss` | 72% | - |
| `soybean_crush_margin` | BINDABLE | 1 | 12 | 13 | `supply growth` | 92% | crush_margin_z |
| `biennial_low_cycle` | BINDABLE | 1 | 5 | 13 | `following heavy` | 60% | mpob_fundamentals |
| `NAO` | HONEST-WAIVE | 1 | 4 | 17 | `european winter` | 75% | - |
| `china_rsm_stocks` | BINDABLE | 0 | 387 | 4 | `oilseed crush` | 55% | stock |
| `China_food_use_demand` | BINDABLE | 0 | 205 | 11 | `food grade soybean` | 44% | consumption |
| `canadian_canola_supply` | BINDABLE | 0 | 199 | 4 | `canada canola` | 46% | production |
| `pod_fill` | BINDABLE | 0 | 192 | 14 | `northeast china` | 90% | nass_crop_progress_ge_z |
| `rapeseed_crush_demand` | BINDABLE | 0 | 191 | 12 | `crush volume` | 84% | crush_margin_z |
| `import_parity` | BINDABLE | 0 | 158 | 0 | `local prices` | 49% | import |
| `gray_leaf_spot` | HONEST-WAIVE | 0 | 142 | 12 | `grain fill` | 49% | - |
| `export_pace` | BINDABLE | 0 | 133 | 16 | `export pace` | 59% | esr_exports, export |
| `crush_margin` | BINDABLE | 0 | 111 | 0 | `crush margins` | 73% | crush_margin_z |
| `cbot_corn_price` | BINDABLE | 0 | 109 | 5 | `price parity` | 39% | price |
| `canola_crush_margin` | BINDABLE | 0 | 95 | 0 | `crush margins` | 85% | crush_margin_z |
| `soyoil_olein_premium` | BINDABLE | 0 | 95 | 7 | `price sensitive` | 88% | spread |
| `rapeseed_crush_margin` | BINDABLE | 0 | 89 | 6 | `crush margins` | 91% | crush_margin_z |
| `China_soyoil_supply` | BINDABLE | 0 | 78 | 3 | `crush volumes` | 47% | crush_margin_z |
| `regional_export_demand` | BINDABLE | 0 | 77 | 8 | `export parity levels` | 53% | export |
| `arabica_robusta_spread` | BINDABLE | 0 | 59 | 7 | `price ratio` | 98% | spread |
| `IOD_negative` | BINDABLE | 0 | 55 | 14 | `summer rainfall` | 87% | iod_climate |
| `phytosanitary` | HONEST-WAIVE | 0 | 45 | 18 | `china customs` | 100% | - |
| `cbot_corn_anchor` | BINDABLE | 0 | 30 | 9 | `export parity` | 97% | price |
| `board_crush` | BINDABLE | 0 | 28 | 7 | `oil share` | 29% | crush_margin_z |
| `eu_crush_demand` | BINDABLE | 0 | 25 | 8 | `processing demand` | 52% | crush_margin_z |
| `meal_inventory` | BINDABLE | 0 | 25 | 12 | `crush plants` | 92% | stock |
| `stock` | BINDABLE | 0 | 23 | 16 | `biofuel feedstock` | 65% | stock |
| `cbot_arbitrage` | BINDABLE | 0 | 22 | 5 | `import parity` | 100% | price |
| `arabica_substitution_into_robusta` | BINDABLE | 0 | 14 | 24 | `robusta demand` | 50% | spread |
| `calendar_spread` | BINDABLE | 0 | 13 | 14 | `tight stocks` | 54% | spread |
| `AO` | HONEST-WAIVE | 0 | 10 | 23 | `cold winter` | 60% | - |
| `white_yellow_premium` | BINDABLE | 0 | 2 | 17 | `premium over yellow` | 100% | spread |

## FILLABLE-BY-TERM, with the verbatim text that says so

### `us_export_pace` -- 389 ANCHORED driver-dark props (of 3253 total)

- **anchored terms (14)**: `cotton marketing`, `cotton marketing year`, `esr weekly`, `esr weekly export`, `exports psd`, `kcbt price`, `marketing year exports`, `oil esr`, `soybean oil esr`, `spring wheat esr`, `wheat esr`, `wheat esr weekly`, `winter wheat esr`, `year exports psd`
- all terms kept (22): `cotton marketing`, `exports psd`, `cotton marketing year`, `marketing year exports`, `year exports psd`, `wheat esr`, `esr weekly`, `weekly export`, `sales pace`, `mgex price`, `red spring wheat`, `spring wheat esr`
- dark props by term: {"red winter wheat": 1902, "red spring wheat": 957, "cotton marketing year": 228, "marketing year exports": 107, "cotton marketing": 54, "sales pace": 7, "weekly export": 1, "export sales pace": 1, "weekly export sales": 1}
- top sources: {"usda_wasde": 3466, "usda_gain_grain_monthly": 116, "usda_gain_cotton": 84, "usda_gain_wheat": 84, "wb_cmo_outlook": 71}
- dropped as over-fire: `marketing year`, `ending stocks`, `hard red`, `red spring`, `export sales`, `hard red spring`, `red winter`, `hard red winter`

  > In the Yangtze and Yellow River regions of China, the cotton marketing was markedly slower than the previous year and farm-gate prices were 30 percent lower than the previous year. _(usda_gain_cotton, 2009-04-01; matched `cotton marketing`)_

  > The ADBC president vowed to continue to financially assist domestic cotton marketing in MY08/09 at an ADBC meeting held in January 2008. _(usda_gain_cotton, 2009-04-01; matched `cotton marketing`)_

  > There have been no reliable stocks data for cotton in China since the liberalization of cotton marketing in 1999. _(usda_gain_cotton, 2007-05-03; matched `cotton marketing`)_

### `flowering` -- 234 ANCHORED driver-dark props (of 429 total)

- **anchored terms (26)**: `bloom fruit`, `bloom fruit set`, `critical flowering`, `critical flowering window`, `during april`, `florida sao`, `florida sao paulo`, `flowering sharply`, `flowering window`, `flowering window spring`, `fruit set timing`, `oilseed rape`, `oilseed rape critical`, `orange bloom`, `orange bloom fruit`, `paulo orange`, `paulo orange bloom`, `phenology window`, `rape critical`, `rape critical flowering`, `sao paulo orange`, `set timing`, `set timing phenology`, `sharply reduces`, `timing phenology`, `timing phenology window`
- all terms kept (38): `oilseed rape`, `rape critical`, `critical flowering`, `flowering window`, `window spring`, `spring heat`, `heat moisture`, `moisture sensitivity`, `sensitivity europe`, `oilseed rape critical`, `rape critical flowering`, `critical flowering window`
- dark props by term: {"during april": 195, "fruit set": 147, "moisture stress": 43, "sao paulo orange": 19, "critical flowering": 18, "stress during": 5, "orange bloom": 1, "bloom fruit": 1}
- top sources: {"conab": 128, "usda_gain_grain_monthly": 65, "usda_gain_orange_juice": 65, "usda_wap": 60, "usda_gain_coffee": 55}
- dropped as over-fire: `sao paulo`

  > Average Robusta coffee prices in Brazil during April-July 2019 dropped by 13 percent in the local currency Real (R$ 285.18/bag) compared to the same period in 2018 (R$ 329.65/bag). _(usda_gain_coffee, 2019-11-01; matched `during april`)_

  > Average Robusta coffee prices in Brazil during April-July 2019 dropped by 17 percent in US$ dollars (US$ 73.75/bag) compared to the same period in 2018 (US$ 88.99/bag). _(usda_gain_coffee, 2019-11-01; matched `during april`)_

  > Under the Mexico-Central America FTA, during April and May of each year, if applicable, Mexico will announce through its official channels the import needs for the supply of sugar and the opening of the respective quotas. _(usda_gain_sugar, 2011-12-01; matched `during april`)_

### `replanting_cycle` -- 205 ANCHORED driver-dark props (of 432 total)

- **anchored terms (31)**: `africa cocoa tree`, `age replanting`, `age replanting rehabilitation`, `area reduction`, `area reduction colombia`, `area reduction stumping`, `bearing area reduction`, `brazil coffee renovation`, `cocoa tree`, `cocoa tree age`, `coffee renovation`, `coffee renovation replanting`, `colombia fnc`, `reduction colombia`, `reduction colombia fnc`, `reduction stumping`, `reduction stumping frost`, `rehabilitation yield`, `renovation replanting`, `renovation replanting bearing`, `renovation replanting program`, `replanting bearing`, `replanting bearing area`, `replanting program`, `replanting program bearing`, `replanting rehabilitation`, `replanting rehabilitation yield`, `stumping frost`, `stumping frost recovery`, `tree age`, `tree age replanting`
- all terms kept (39): `coffee renovation`, `renovation replanting`, `replanting program`, `program bearing`, `bearing area`, `area reduction`, `reduction colombia`, `colombia fnc`, `coffee renovation replanting`, `renovation replanting program`, `replanting program bearing`, `program bearing area`
- dark props by term: {"west africa": 148, "replanting program": 91, "bearing area": 62, "area reduction": 59, "coffee renovation": 38, "yield decline": 17, "tree age": 10, "cocoa tree": 7, "africa cocoa": 1}
- top sources: {"usda_gain_coffee": 141, "mpoc": 55, "usda_gain_cotton": 49, "usda_gain_grain_monthly": 26, "usda_gain_soybean_oil": 26}

  > Canadian soybean area reduction in 2020 was primarily due to high global stocks, uncertain market conditions, and several seasons of poor harvests due to dry conditions. _(usda_wap, 2020-11-01; matched `area reduction`)_

  > Fedecafe wants to reduce Colombia's average coffee tree age to 5.5 years. _(usda_gain_coffee, 2000-05-01; matched `tree age`)_

  > There is little domestic public investment in coffee renovation in Guatemala. _(usda_gain_coffee, 2023-05-12; matched `coffee renovation`)_

### `area` -- 170 ANCHORED driver-dark props (of 333 total)

- **anchored terms (28)**: `acreage hrw`, `acreage prospective`, `acreage prospective plantings`, `area seedings`, `area seedings autumn`, `autumn conditions`, `autumn conditions rapeseed`, `barley rotation`, `conditions rapeseed barley`, `dakota montana`, `dakota montana canola`, `kansas oklahoma`, `montana canola`, `montana canola competition`, `oklahoma seedings`, `planted acreage`, `planted acreage hrw`, `planted acreage prospective`, `planted area seedings`, `plantings dakota`, `plantings dakota montana`, `prospective plantings`, `prospective plantings dakota`, `rapeseed barley`, `rapeseed barley rotation`, `seedings autumn`, `seedings autumn conditions`, `wheat planted acreage`
- all terms kept (35): `soft wheat`, `area seedings`, `seedings autumn`, `autumn conditions`, `conditions rapeseed`, `rapeseed barley`, `barley rotation`, `soft wheat planted`, `planted area seedings`, `area seedings autumn`, `seedings autumn conditions`, `autumn conditions rapeseed`
- dark props by term: {"planted acreage": 161, "soft wheat": 121, "winter wheat planted": 36, "wheat planted acreage": 6, "spring wheat planted": 6, "autumn conditions": 3}
- top sources: {"usda_wasde": 227, "usda_gain_wheat": 82, "usda_gain_corn": 58, "usda_gain_grain_monthly": 39, "usda_gain_soybean_meal": 28}
- dropped as over-fire: `wheat planted`, `planted area`, `wheat planted area`

  > Wheat planted acreage in the United States in 1981 was 88.9 million acres. _(usda_wasde, 1983-05-11; matched `wheat planted acreage`)_

  > Corn planted acreage in the United States in 1981 was 84.2 million acres. _(usda_wasde, 1983-05-11; matched `planted acreage`)_

  > Soybeans planted acreage in the United States in 1981 was 67.8 million acres. _(usda_wasde, 1983-05-11; matched `planted acreage`)_

### `blocking_high` -- 164 ANCHORED driver-dark props (of 277 total)

- **anchored terms (30)**: `2021 canola`, `2021 canola crop`, `air outbreak`, `air outbreak brazil`, `america blocking`, `belt heat dome`, `blocking high cold`, `blocking high western`, `blocking ridge`, `blocking ridge corn`, `canada 2021`, `canada 2021 canola`, `coffee frost synoptic`, `cold air outbreak`, `dome blocking`, `dome maize`, `dome yield`, `frost synoptic`, `heat dome`, `heat dome blocking`, `heat dome yield`, `outbreak brazil`, `outbreak brazil coffee`, `ridge corn`, `ridge corn belt`, `south america blocking`, `summer blocking`, `summer blocking ridge`, `western canada`, `western canada 2021`
- all terms kept (37): `america blocking`, `cold air`, `air outbreak`, `outbreak brazil`, `coffee frost`, `frost synoptic`, `south america blocking`, `blocking high cold`, `cold air outbreak`, `air outbreak brazil`, `outbreak brazil coffee`, `brazil coffee frost`
- dark props by term: {"western canada": 163, "corn belt": 109, "cold air": 4, "european summer": 1, "2021 canola": 1}
- top sources: {"usda_gain_wheat": 93, "usda_gain_grain_monthly": 83, "usda_wasde": 66, "usda_wap": 39, "usda_gain_rapeseed": 28}
- dropped as over-fire: `south america`

  > As of October 12, 2017, 88 percent of Canada Western Red Spring (CWRS) wheat would be grade one, the highest quality grade, according to Canadian Grain Commission's western Canada harvest samples. _(usda_gain_grain_monthly, 2017-10-31; matched `western canada`)_

  > As of October 12, 2017, 77 percent of Canada Western Amber Durum (CWAD) wheat would be grade one, the highest quality grade, according to Canadian Grain Commission's western Canada harvest samples. _(usda_gain_grain_monthly, 2017-10-31; matched `western canada`)_

  > In MY 2017/2018, malting barley varieties made up 61 percent of all area seeded to barley in Western Canada. _(usda_gain_grain_monthly, 2017-10-31; matched `western canada`)_

### `GMO_phytosanitary_policy` -- 161 ANCHORED driver-dark props (of 206 total)

- **anchored terms (20)**: `approval phytosanitary`, `approval phytosanitary maize`, `approvals and import`, `determine which suppliers`, `effective import`, `event approvals`, `gmo import approval`, `import approval`, `import approval phytosanitary`, `import permit`, `import permits`, `import permits determine`, `permit rules`, `permits determine`, `reach south`, `reach south africa`, `regulatory approvals`, `rules govern`, `shifting effective`, `suppliers can reach`
- all terms kept (37): `africa gmo`, `gmo import`, `import approval`, `approval phytosanitary`, `phytosanitary maize`, `maize origin`, `south africa gmo`, `africa gmo import`, `gmo import approval`, `import approval phytosanitary`, `approval phytosanitary maize`, `phytosanitary maize origin`
- dark props by term: {"import permits": 97, "import permit": 44, "import parity": 22, "phytosanitary import": 20, "import approval": 15, "effective import": 4, "affecting prices": 3, "regulatory approvals": 1, "event approvals": 1}
- top sources: {"usda_gain_sugar": 71, "usda_gain_grain_monthly": 60, "usda_gain_rice": 36, "usda_gain_soybean_oil": 27, "usda_gain_soybean_meal": 27}

  > Running capacity of Indonesian sugar refineries varies depending on the GOI's issuance of raw sugar import permits. _(usda_gain_sugar, 2021-04-20; matched `import permits`)_

  > The GOI issued import permits for 1.9 million tons of raw sugar for the first semester of 2021 in December 2020 in Indonesia. _(usda_gain_sugar, 2021-04-20; matched `import permits`)_

  > Import permits for the remaining 1.3 million tons of raw sugar for the second semester of 2021 have yet to be issued by the GOI in Indonesia. _(usda_gain_sugar, 2021-04-20; matched `import permits`)_

### `China_domestic_crop` -- 147 ANCHORED driver-dark props (of 433 total)

- **anchored terms (7)**: `china heilongjiang`, `heilongjiang inner`, `heilongjiang non`, `heilongjiang non gmo`, `inner mongolia`, `jilin non`, `mongolia jilin`
- all terms kept (31): `heilongjiang non`, `non gmo`, `gmo soybean`, `front month`, `month price`, `heilongjiang non gmo`, `non gmo soybean`, `gmo soybean production`, `front month price`, `larger northeast`, `northeast soybean`, `harvest increases`
- dark props by term: {"northeast china": 172, "inner mongolia": 145, "non gmo": 73, "imported beans": 23, "non gmo soybean": 12, "northeast soybean": 4, "domestic food grade": 3, "price downward": 2, "gmo soybean": 2, "china heilongjiang": 2, "month price": 1, "harvest increases": 1}
- top sources: {"usda_gain_grain_monthly": 116, "usda_gain_rapeseed": 94, "usda_wap": 83, "usda_gain_soybean_meal": 78, "usda_gain_wheat": 72}
- dropped as over-fire: `soybean harvest`, `food grade`

  > In Inner Mongolia during MY 22/23, soybean production costs increased 12.7 percent compared to MY 21/22. _(usda_gain_soybean_meal, 2023-03-20; matched `inner mongolia`)_

  > In Inner Mongolia during MY 22/23, soybean pesticide costs increased 30.9 percent compared to MY 21/22. _(usda_gain_soybean_meal, 2023-03-20; matched `inner mongolia`)_

  > Inner Mongolia produced 2.45 MMT of soybeans in MY 22/23. _(usda_gain_soybean_meal, 2023-03-20; matched `inner mongolia`)_

### `export_pace_lag` -- 143 ANCHORED driver-dark props (of 520 total)

- **anchored terms (24)**: `arrivals cocoa`, `arrivals cocoa season`, `brazil santos`, `brazil santos coffee`, `cecafe monthly`, `coast cumulative`, `coast cumulative port`, `cumulative port`, `cumulative port arrivals`, `ivory coast`, `ivory coast cumulative`, `lag cecafe`, `lag cecafe monthly`, `pace lag`, `pace lag cecafe`, `pace rouen`, `port arrivals`, `port arrivals cocoa`, `santos coffee`, `santos coffee export`, `season versus prior`, `shipments pace lag`, `versus prior`, `versus prior year`
- all terms kept (35): `brazil santos`, `santos coffee`, `export shipments`, `shipments pace`, `pace lag`, `lag cecafe`, `cecafe monthly`, `brazil santos coffee`, `santos coffee export`, `coffee export shipments`, `export shipments pace`, `shipments pace lag`
- dark props by term: {"ivory coast": 143, "french wheat": 141, "export shipments": 82, "export pace": 79, "coffee export shipments": 46, "cocoa season": 29}
- top sources: {"usda_gain_wheat": 120, "usda_wasde": 79, "usda_gain_coffee": 69, "usda_gain_grain_monthly": 68, "usda_gain_corn": 55}
- dropped as over-fire: `prior year`, `black sea`

  > Approximately 75,000 MT to 100,000 MT of cocoa beans were smuggled from Ivory Coast into Ghana during the 2010/11 season. _(usda_gain_cocoa, 2012-03-15; matched `ivory coast`)_

  > In the past, cocoa beans were smuggled from Ghana to Ivory Coast due to price differences. _(usda_gain_cocoa, 2012-03-15; matched `ivory coast`)_

  > Ghana is the world's second largest exporter of cocoa after Ivory Coast. _(usda_gain_cocoa, 2012-03-15; matched `ivory coast`)_

### `conab_production_revision` -- 143 ANCHORED driver-dark props (of 452 total)

- **anchored terms (17)**: `coffee production estimate`, `conab bean`, `conab bean production`, `conab brazil`, `conab brazil coffee`, `conab corn`, `conab corn production`, `conab soybean`, `conab soybean production`, `estimate revision`, `estimate revision arabica`, `meal export forecasts`, `meal price reaction`, `price reaction`, `production estimate revision`, `production revision surprises`, `revision surprises`
- all terms kept (27): `conab brazil`, `estimate revision`, `revision arabica`, `arabica crop`, `crop forecast`, `conab brazil coffee`, `coffee production estimate`, `production estimate revision`, `estimate revision arabica`, `revision arabica crop`, `arabica crop forecast`, `conab corn`
- dark props by term: {"crop forecast": 240, "coffee production estimate": 135, "arabica crop": 53, "production revision": 13, "meal export forecasts": 7, "brazilian crush": 2, "corn production revision": 1, "estimate revision": 1}
- top sources: {"usda_gain_coffee": 154, "sagis_cec": 110, "usda_wasde": 63, "usda_gain_grain_monthly": 42, "conab": 32}
- dropped as over-fire: `production estimate`, `export forecasts`, `bean production`

  > The Brazilian Institute of Geography and Statistics (IBGE) released a September 2019 coffee production estimate for MY 2019/20 showing production of 3.017 million metric tons of coffee, or 50.3 million 60-kg bags (35.1 million bags for Arabica and 15.2 million for Robusta coffee). _(usda_gain_coffee, 2019-11-01; matched `coffee production estimate`)_

  > ATO/Sao Paulo revised downward its Brazilian coffee production estimate for marketing year 2019/20 (July-June) to 58 million 60-kg bags, green equivalent. _(usda_gain_coffee, 2019-11-01; matched `coffee production estimate`)_

  > In September 2019, CONAB released the third official coffee production estimate for MY 2019/20 at 48.99 million bags (34.47 million bags for Arabica and 14.52 million for Robusta coffee). _(usda_gain_coffee, 2019-11-01; matched `coffee production estimate`)_

### `buffer_stock_release` -- 127 ANCHORED driver-dark props (of 248 total)

- **anchored terms (27)**: `auction release`, `auction release volumes`, `auction releases`, `buffer stock`, `buffer stock auction`, `government rice stock`, `release volumes`, `releases increase`, `releases increase domestic`, `releases increase supply`, `reserve auction`, `reserve auction release`, `rice buffer`, `rice buffer stock`, `rice stock releases`, `sinograin soyoil`, `sinograin soyoil reserve`, `soyoil releases`, `soyoil releases increase`, `soyoil reserve`, `soyoil reserve auction`, `state soyoil`, `state soyoil releases`, `stock auction`, `stock auction releases`, `stock releases`, `stock releases increase`
- all terms kept (31): `rice buffer`, `buffer stock`, `stock auction`, `auction releases`, `rice buffer stock`, `buffer stock auction`, `stock auction releases`, `sinograin soyoil`, `soyoil reserve`, `reserve auction`, `auction release`, `release volumes`
- dark props by term: {"buffer stock": 107, "increase domestic": 66, "rice stock": 49, "government rice stock": 6, "rice buffer stock": 6, "increase domestic supply": 3, "stock releases": 3, "increase supply": 3, "rice buffer": 2, "rice stock releases": 2, "stock auction": 1}
- top sources: {"usda_gain_sugar": 64, "usda_gain_grain_monthly": 58, "usda_gain_cotton": 55, "usda_gain_wheat": 43, "usda_gain_rice": 23}
- dropped as over-fire: `government rice`

  > Since January 2023, India's government held rice stocks have ranged from 31.5 MMT to 67.6 MMT against the prescribed buffer stock norms stipulating rice stocks to range from 7.6 to 13.6 MMT. _(usda_gain_wheat, 2025-04-02; matched `buffer stock`)_

  > As of April 1, 2025, wheat stocks in India are estimated at 10.5 MMT against the desired April 1 Buffer Stock Norm of 7.46 MMT. _(usda_gain_wheat, 2025-04-02; matched `buffer stock`)_

  > India's government wheat stocks target for MY 2025/2026 is 13-15 MMT after meeting food security program commitments and mandatory buffer stock norm of 7.46 MMT. _(usda_gain_wheat, 2025-04-02; matched `buffer stock`)_

### `Thailand_production` -- 123 ANCHORED driver-dark props (of 205 total)

- **anchored terms (12)**: `contractions tighten`, `driven contractions`, `driven contractions tighten`, `drought driven contractions`, `exporter rebounds`, `production swings`, `sugar production swings`, `swings with rainfall`, `thai cane`, `thai cane rainfall`, `thai sugar`, `thai sugar production`
- all terms kept (30): `thailand cane`, `ice sugar`, `thailand cane production`, `thai sugar`, `production swings`, `rainfall shifting`, `shifting global`, `thai sugar production`, `sugar production swings`, `swings with rainfall`, `rainfall shifting global`, `shifting global supply`
- dark props by term: {"thai sugar": 108, "world price": 65, "thai cane": 11, "thailand cane": 8, "ice sugar": 8, "production swings": 3, "rainfall driven": 1, "thai sugar production": 1}
- top sources: {"usda_gain_sugar": 215, "wb_cmo_outlook": 23, "usda_gain_cotton": 12, "usda_gain_coffee": 9, "usda_gain_wheat": 8}
- dropped as over-fire: `cane production`, `export forecast`

  > During January-May 2012, Thai sugar exports increased significantly to 4.5 MMTRV, up 37.3 percent from the same period last year. _(usda_gain_sugar_semiannual, 2012-10-01; matched `thai sugar`)_

  > The new soft loan program for Thai cane growers will be financed by the state-run Cane and Sugar Fund. _(usda_gain_sugar_semiannual, 2012-10-01; matched `thai cane`)_

  > During January-May 2012, Thai sugar exports increased significantly to 4.5 million metric tons raw value, up 37.3 percent from the same period last year. _(usda_gain_sugar_semiannual, 2012-10-01; matched `thai sugar`)_

### `biennial_bearing` -- 108 ANCHORED driver-dark props (of 355 total)

- **anchored terms (24)**: `ambiguous lagged`, `ambiguous lagged supply`, `carryover next`, `carryover next season`, `carryover stress`, `cocoa tree`, `cocoa tree stress`, `lagged supply`, `lagged supply effect`, `lingering effects`, `next season`, `next season yield`, `output carryover`, `output carryover stress`, `output through lingering`, `reduces next`, `reduces next year`, `stress carryover`, `stress carryover next`, `stress reduces next`, `supply effect`, `tree stress`, `tree stress carryover`, `tree stress reduces`
- all terms kept (37): `cocoa tree`, `tree stress`, `stress carryover`, `carryover next`, `next season`, `season yield`, `yield deficit`, `deficit recovery`, `cocoa tree stress`, `tree stress carryover`, `stress carryover next`, `carryover next season`
- dark props by term: {"west africa": 148, "following year": 96, "next season": 92, "cocoa tree": 7, "carryover next": 5, "season yield": 4, "lingering effects": 3, "deficit year": 1, "tree stress": 1}
- top sources: {"usda_gain_cotton": 66, "mpoc": 56, "usda_wasde": 47, "usda_gain_grain_monthly": 34, "usda_gain_sugar": 29}
- dropped as over-fire: `next year`

  > Brazil soybean exports are forecast to recover to 75 million metric tons in the next season following 2018/19. _(usda_gain_soybeans, 2019-04-02; matched `next season`)_

  > Cumulative world soybean oil supply for the next season is set to decline by 1%, mainly because of conditions in China, the EU, and Brazil. _(wb_cmo_outlook, 1997-08-01; matched `next season`)_

  > Larger farmers in Brazil are likely to maintain or only slightly reduce their cotton area, while small and medium farmers may be more likely to switch to alternate crops next season. _(usda_gain_cotton, 2022-05-10; matched `next season`)_

### `Vietnam_export_tax_policy` -- 105 ANCHORED driver-dark props (of 332 total)

- **anchored terms (22)**: `changes reduce`, `changes reduce available`, `coffee export vat`, `export registration`, `export vat`, `export vat refund`, `fob differentials`, `minimum price policy`, `price guidance`, `price policy`, `refund changes`, `refund registration`, `refund registration minimum`, `registration minimum`, `registration minimum price`, `registration vat`, `restrictions and vat`, `vat changes`, `vat changes reduce`, `vat refund`, `vat refund registration`, `vietnamese export registration`
- all terms kept (32): `export vat`, `vat refund`, `refund registration`, `registration minimum`, `price policy`, `vietnam coffee export`, `coffee export vat`, `export vat refund`, `vat refund registration`, `refund registration minimum`, `registration minimum price`, `minimum price policy`
- dark props by term: {"export restrictions": 154, "available supply": 41, "export registration": 41, "exportable supply": 33, "price policy": 28, "export vat refund": 15, "export vat": 14, "vat refund": 5, "changes reduce": 1, "vietnamese export": 1, "vat changes": 1}
- top sources: {"usda_gain_wheat": 96, "usda_gain_cotton": 85, "usda_gain_grain_monthly": 54, "usda_gain_rapeseed": 31, "usda_wasde": 30}
- dropped as over-fire: `vietnam coffee`, `minimum price`

  > Repealing ROEs (export registration requirements/export licenses) in Argentina is expected to lead to farmers immediately increasing area planted to wheat. _(usda_gain_soybean_meal, 2015-04-01; matched `export registration`)_

  > India's FSI wheat consumption over the last three years has stagnated around 90-91 MMT due to government procurement and price policy dominating the domestic wheat market. _(usda_gain_rice, 2020-04-03; matched `price policy`)_

  > Prime Minister Sherif Ismail reversed Egypt's proposed November 2015 policy change and reinstated the original procurement price policy of LE 420 ($53.6) per ardeb or $357/ton. _(usda_gain_wheat, 2016-03-10; matched `price policy`)_

### `FUNCAFE` -- 105 ANCHORED driver-dark props (of 105 total)

- **anchored terms (29)**: `brazil coffee financing`, `brazilian funcafe`, `coffee financing`, `coffee financing retention`, `credit line`, `credit line harvest`, `credit lines`, `crop financing`, `crop financing lets`, `financing lets`, `financing lets producers`, `financing retention`, `financing retention credit`, `funcafe brazil`, `funcafe brazil coffee`, `funcafe crop`, `harvest funding`, `hold beans`, `hold beans off`, `lets producers`, `lets producers hold`, `line harvest`, `line harvest funding`, `lines let`, `price floors`, `producers hold`, `producers hold beans`, `retention credit`, `retention credit line`
- all terms kept (35): `funcafe brazil`, `coffee financing`, `financing retention`, `retention credit`, `credit line`, `line harvest`, `harvest funding`, `funcafe brazil coffee`, `brazil coffee financing`, `coffee financing retention`, `financing retention credit`, `retention credit line`
- dark props by term: {"coffee financing": 38, "credit line": 31, "credit lines": 26, "crop financing": 12, "producers hold": 2, "funcafe crop": 1}
- top sources: {"conab": 43, "usda_gain_coffee": 42, "usda_gain_sugar": 14, "usda_gain_cotton": 13, "usda_gain_corn": 11}

  > BNDES Automatic is a credit line aimed at creating pasture, other animal production projects, and for production of forest products. _(usda_gain_cotton, 2004-05-14; matched `credit line`)_

  > Agribank announced that it would add 3 trillion Vietnam Dong ($182 million) to the available credit line for coffee processors and exporters in the 2008/2009 coffee crop year. _(usda_gain_coffee, 2008-11-01; matched `credit line`)_

  > At the beginning of February 2021, with still five months left in the existing Plano Safra season, 10 of the 19 rural credit lines from the National Bank for Economic and Social Development (BNDES) were closed due to the depletion of resources. _(usda_gain_cotton, 2021-04-01; matched `credit lines`)_

## Flagged `concentration_risk` -- a count that is about a term, not a driver

These cleared the 100-prop floor but more than 60% of the mass sits on ONE term. That is the failure mode this instrument was rebuilt to catch; they are NOT authorable as they stand.

| driver_id | dark props | top term | share | verdict |
|---|---:|---|---:|---|
| `Canada_production` | 305 | `statistics canada` | 84% | BINDABLE |
| `China_vegoil_demand` | 270 | `food service` | 66% | BINDABLE |
| `China_food_demand` | 271 | `food service` | 66% | BINDABLE |
| `cercospora_beet` | 182 | `sugar beet` | 86% | HONEST-WAIVE |
| `aquaculture_feed_demand` | 164 | `aquaculture feed` | 86% | BINDABLE |
| `vernalization_failure` | 2057 | `red winter wheat` | 92% | HONEST-WAIVE |
| `INR_THB_VND_weakness` | 247 | `world prices` | 70% | BINDABLE |
| `pre_harvest_sprouting` | 1965 | `red winter wheat` | 97% | HONEST-WAIVE |
| `domestic_crush_demand` | 151 | `canada canola` | 61% | BINDABLE |
| `IOD_positive` | 191 | `west africa` | 78% | BINDABLE |
| `aqua_season` | 136 | `price strength` | 70% | HONEST-WAIVE |
| `hessian_fly` | 1931 | `red winter wheat` | 98% | HONEST-WAIVE |
| `buyer_tender_demand` | 266 | `world prices` | 65% | BINDABLE |
| `tenderable_collapse` | 130 | `cocoa stocks` | 72% | BINDABLE |
| `crush_margin_expansion` | 172 | `crush volume` | 94% | BINDABLE |
| `cec_production_revision` | 152 | `larger crop` | 86% | BINDABLE |
| `abandonment` | 263 | `harvest area` | 77% | BINDABLE |
| `tan_spot` | 105 | `wet conditions` | 86% | HONEST-WAIVE |
| `protein_premium` | 2866 | `red winter wheat` | 66% | HONEST-WAIVE |
| `consumption_growth` | 327 | `consumption growth` | 64% | BINDABLE |
| `import_crush_margin` | 313 | `imported soybean` | 60% | BINDABLE |
| `import_demand_destination` | 169 | `west africa` | 88% | BINDABLE |
| `soyoil_palm_premium` | 118 | `price sensitive` | 71% | BINDABLE |
| `ear_rot` | 146 | `grain quality` | 84% | HONEST-WAIVE |
| `pod_fill` | 192 | `northeast china` | 90% | BINDABLE |
| `rapeseed_crush_demand` | 191 | `crush volume` | 84% | BINDABLE |
| `crush_margin` | 111 | `crush margins` | 73% | BINDABLE |

## HONEST-WAIVE -- neither axis carries them

| driver_id | dark props | silver statuses | why |
|---|---:|---|---|
| `cercospora_beet` | 182 | planned | 182 driver-dark props but 86% of them come from the single term `sugar beet` -- that is evidence about the term, not about this driver; re-derive terms before authoring anything |
| `vernalization_failure` | 2057 | planned | 2057 driver-dark props but 92% of them come from the single term `red winter wheat` -- that is evidence about the term, not about this driver; re-derive terms before authoring anything |
| `India_ethanol_diversion` | 280 | planned | neither axis: 94 anchored driver-dark props of 280 total (floor 100, 26 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `corn_rootworm` | 94 | planned | neither axis: 72 anchored driver-dark props of 94 total (floor 100, 19 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `labor_shortage` | 72 | planned | neither axis: 72 anchored driver-dark props of 72 total (floor 100, 33 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `Algeria_tender_specs` | 76 | planned | neither axis: 69 anchored driver-dark props of 76 total (floor 100, 35 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `leaf_rust` | 174 | planned | neither axis: 60 anchored driver-dark props of 174 total (floor 100, 19 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `stockholding_limit` | 52 | planned | neither axis: 52 anchored driver-dark props of 52 total (floor 100, 40 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `pre_harvest_sprouting` | 1965 | planned | 1965 driver-dark props but 97% of them come from the single term `red winter wheat` -- that is evidence about the term, not about this driver; re-derive terms before authoring anything |
| `wheat_midge` | 49 | planned | neither axis: 42 anchored driver-dark props of 49 total (floor 100, 25 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `aphids` | 49 | planned | neither axis: 41 anchored driver-dark props of 49 total (floor 100, 30 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `aqua_season` | 136 | planned | 136 driver-dark props but 70% of them come from the single term `price strength` -- that is evidence about the term, not about this driver; re-derive terms before authoring anything |
| `CBD` | 106 | planned | neither axis: 34 anchored driver-dark props of 106 total (floor 100, 30 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `PDO` | 34 | planned | neither axis: 34 anchored driver-dark props of 34 total (floor 100, 21 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `hessian_fly` | 1931 | planned | 1931 driver-dark props but 98% of them come from the single term `red winter wheat` -- that is evidence about the term, not about this driver; re-derive terms before authoring anything |
| `hail` | 83 | planned | neither axis: 22 anchored driver-dark props of 83 total (floor 100, 14 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `septoria` | 240 | planned | neither axis: 13 anchored driver-dark props of 240 total (floor 100, 24 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `shattering` | 26 | planned | neither axis: 13 anchored driver-dark props of 26 total (floor 100, 30 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `import_parity_floor` | 52 | planned | neither axis: 11 anchored driver-dark props of 52 total (floor 100, 6 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `aflatoxin` | 11 | planned | neither axis: 11 anchored driver-dark props of 11 total (floor 100, 22 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `GMO_white_policy` | 154 | planned | neither axis: 10 anchored driver-dark props of 154 total (floor 100, 18 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `white_mold` | 10 | planned | neither axis: 10 anchored driver-dark props of 10 total (floor 100, 24 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `tan_spot` | 105 | planned | 105 driver-dark props but 86% of them come from the single term `wet conditions` -- that is evidence about the term, not about this driver; re-derive terms before authoring anything |
| `eu_neonic_ban` | 23 | planned | neither axis: 8 anchored driver-dark props of 23 total (floor 100, 31 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `protein_premium` | 2866 | planned | 2866 driver-dark props but 66% of them come from the single term `red winter wheat` -- that is evidence about the term, not about this driver; re-derive terms before authoring anything |
| `refinery_outages` | 12 | planned | neither axis: 7 anchored driver-dark props of 12 total (floor 100, 20 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `corn_borer` | 17 | planned | neither axis: 6 anchored driver-dark props of 17 total (floor 100, 24 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `sudden_death_syndrome` | 13 | planned | neither axis: 6 anchored driver-dark props of 13 total (floor 100, 24 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `biennial_on_year` | 208 | planned | neither axis: 5 anchored driver-dark props of 208 total (floor 100, 4 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `biennial_off_year` | 204 | planned | neither axis: 5 anchored driver-dark props of 204 total (floor 100, 5 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `wheat_streak_mosaic` | 5 | planned | neither axis: 3 anchored driver-dark props of 5 total (floor 100, 27 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `AMO` | 3 | planned | neither axis: 3 anchored driver-dark props of 3 total (floor 100, 37 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `SAM` | 36 | planned | neither axis: 2 anchored driver-dark props of 36 total (floor 100, 19 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `rapeoil_share` | 10 | planned | neither axis: 2 anchored driver-dark props of 10 total (floor 100, 6 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `ear_rot` | 146 | planned | 146 driver-dark props but 84% of them come from the single term `grain quality` -- that is evidence about the term, not about this driver; re-derive terms before authoring anything |
| `stink_bug` | 70 | planned | neither axis: 1 anchored driver-dark props of 70 total (floor 100, 13 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `export_parity_floor` | 49 | planned | neither axis: 1 anchored driver-dark props of 49 total (floor 100, 12 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `lodging` | 18 | planned | neither axis: 1 anchored driver-dark props of 18 total (floor 100, 19 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `NAO` | 4 | planned | neither axis: 1 anchored driver-dark props of 4 total (floor 100, 17 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `gray_leaf_spot` | 142 | planned | neither axis: 0 anchored driver-dark props of 142 total (floor 100, 12 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `phytosanitary` | 45 | planned | neither axis: 0 anchored driver-dark props of 45 total (floor 100, 18 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
| `AO` | 10 | planned | neither axis: 0 anchored driver-dark props of 10 total (floor 100, 23 anchored terms) and no instance carries silver_status: available (statuses: planned). Keep the waiver. |
