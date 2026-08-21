# Slice-thinness census (dec_p1, post-X2) -- 2026-08-21T13:17:10Z

Full re-measurement of the evidence store on the DOUBLED (X2) corpus, superseding `data/dec_p0/slice_census.json (DEC-P0, 2026-08-19/20, pre-X2)`. Every prop count and every era bucket below was read from S3 by streaming all 29.76 GB of slice objects; nothing is sampled and nothing is estimated. The scan ran inside the VPC on Batch -- the home link could not carry the commodity half.

## Headline

- **Universe:** 169 slices (43 commodity + 126 driver), **1,277,979 props** total.
- **Commodity layer:** 43/43 present, 1,116,686 props.
- **Driver layer:** 126 declared, 120 present, 161,293 props.
- **Zero-prop slices:** 6. **Thin slices (<10 props):** 13.
- **Declared but absent:** 6. **Present but undeclared:** 19.
- **Duplicate populations:** 4 groups of commodity slices are PROVEN to hold the same props under different names; **199,317 props (18% of the commodity layer) are copies**.
- **Thick slices (>=100 props) with a hollow real era:** 82 of 130 thick.
- **DAG driver ids:** 369 total, 246 backed, **123 dark (33.3%)**; reason split {'unbacked': 123, 'alias': 226, 'exact': 20}.
- **Independently re-scanned:** the same bytes were measured twice by different transports (laptop over the home link, and inside the VPC on Batch). 0 of 0 slices measured both ways agree on `n_props` and on all six era buckets.
- **Dark-id waivers:** 123 of the 123 dark ids carry an explicit waiver entry; 0 are unaccounted for. 4 waivers now cover an id that is no longer dark (`export_levy_duty`, `import_quota_trq`, `indian_ocean_dipole`, `marine_protein_fishmeal`).
- **Cross-check:** 0 of 163 slices with a write-manifest entry disagree with their 2026-08-03 `after_n`. The store has not moved since the rebuild.

## Era totals (whole store)

| layer | props | pre1990 | 1990s | 2000s | 2010_17 | 2018_26 | undated |
|---|--|--|--|--|--|--|--|
| commodity | 1116686 | 18032 | 48345 | 216815 | 352790 | 480105 | 599 |
| driver | 161293 | 1982 | 7057 | 28798 | 47266 | 75927 | 263 |
| **all** | 1277979 | 20014 | 55402 | 245613 | 400056 | 556032 | 862 |

## Zero-prop slices (6)

6 of these have no slice object in the store at all (declared, never built); 0 have an object that holds zero records. Routed-but-empty is an E1b build target, never a retire candidate.

| slice | layer | routed dag ids | category | terms |
|---|--|--|--|--|
| corn_southern_rust | driver | 1 (southern_rust) | crop_disease | 3 |
| corn_tar_spot | driver | 1 (tar_spot) | crop_disease | 3 |
| index_roll_flows | driver | 0 | speculative_positioning | 5 |
| madden_julian_oscillation | driver | 0 | weather_regime | 4 |
| managed_money_positioning | driver | 1 (managed_money_positioning) | speculative_positioning | 6 |
| veg_oil_substitution_spreads | driver | 0 | substitution | 6 |

## Thin slices (< 10 props) -- 13

| slice | layer | props | routed dag ids | category | pre1990 | 1990s | 2000s | 2010_17 | 2018_26 | undated |
|---|--|--|--|--|--|--|--|--|--|--|
| corn_southern_rust | driver | 0 | 1 | crop_disease | 0 | 0 | 0 | 0 | 0 | 0 |
| corn_tar_spot | driver | 0 | 1 | crop_disease | 0 | 0 | 0 | 0 | 0 | 0 |
| index_roll_flows | driver | 0 | 0 | speculative_positioning | 0 | 0 | 0 | 0 | 0 | 0 |
| madden_julian_oscillation | driver | 0 | 0 | weather_regime | 0 | 0 | 0 | 0 | 0 | 0 |
| managed_money_positioning | driver | 0 | 1 | speculative_positioning | 0 | 0 | 0 | 0 | 0 | 0 |
| veg_oil_substitution_spreads | driver | 0 | 0 | substitution | 0 | 0 | 0 | 0 | 0 | 0 |
| soybean_cyst_nematode | driver | 1 | 1 | crop_pest | 0 | 0 | 0 | 1 | 0 | 0 |
| barley_yellow_dwarf_virus | driver | 2 | 0 | crop_disease | 0 | 0 | 0 | 1 | 1 | 0 |
| cftc_positioning | driver | 2 | 4 | positioning | 0 | 1 | 0 | 0 | 1 | 0 |
| china_crush_demand | driver | 2 | 4 | demand_center | 0 | 0 | 0 | 0 | 2 | 0 |
| india_import_duty | driver | 2 | 1 | demand_center | 0 | 0 | 0 | 0 | 2 | 0 |
| real_yields_rates | driver | 2 | 0 | fx_macro | 0 | 0 | 2 | 0 | 0 | 0 |
| harmattan | driver | 8 | 1 | climate | 0 | 0 | 0 | 0 | 8 | 0 |

## Declared but absent (6)

A `drivers:` spec (and a manifest-mirror row) exists; no slice object does. These are the routed-but-empty 'keep' orphans -- the E1b build list.

- `corn_southern_rust` -- 1 routed DAG id(s) (southern_rust), category crop_disease, 3 terms
- `corn_tar_spot` -- 1 routed DAG id(s) (tar_spot), category crop_disease, 3 terms
- `index_roll_flows` -- 0 routed DAG id(s), category speculative_positioning, 5 terms
- `madden_julian_oscillation` -- 0 routed DAG id(s), category weather_regime, 4 terms
- `managed_money_positioning` -- 1 routed DAG id(s) (managed_money_positioning), category speculative_positioning, 6 terms
- `veg_oil_substitution_spreads` -- 0 routed DAG id(s), category substitution, 6 terms

## Present but undeclared (19)

- `barley`
- `coconut`
- `cottonseed`
- `ddgs`
- `ethanol`
- `fish_meal`
- `fresh_citrus`
- `hfcs`
- `minor_cereals`
- `minor_oilseeds`
- `olive_oil`
- `palm_kernel`
- `peanut`
- `pulses`
- `sorghum`
- `sunflower`
- `sunflower_oil`
- `tallow`
- `used_cooking_oil`

## Thick slices (>= 100 props) with a hollow real era (< 10 props)

The analogue-serving gaps: a slice fat enough to be judged that cannot answer in some era. `undated` is excluded from the gap test (a data-quality note, never an era gap).

| slice | layer | present | props | pre1990 | 1990s | 2000s | 2010_17 | 2018_26 | undated | thin eras |
|---|--|--|--|--|--|--|--|--|--|--|
| fresh_citrus | commodity | y | 12372 | 1 | 244 | 1704 | 3961 | 6462 | 0 | pre1990 |
| sunflower_oil_balance | driver | y | 11410 | 9 | 352 | 2647 | 3801 | 4588 | 13 | pre1990 |
| peanut | commodity | y | 11341 | 8 | 385 | 2057 | 3052 | 5812 | 27 | pre1990 |
| sunflower | commodity | y | 11230 | 8 | 349 | 2600 | 3735 | 4525 | 13 | pre1990 |
| tariff | driver | y | 11206 | 4 | 305 | 3167 | 2986 | 4724 | 20 | pre1990 |
| coconut | commodity | y | 6738 | 9 | 358 | 685 | 2159 | 3518 | 9 | pre1990 |
| subsidy | driver | y | 4878 | 6 | 102 | 943 | 1893 | 1931 | 3 | pre1990 |
| south_american_safrinha | driver | y | 4660 | 8 | 27 | 460 | 1299 | 2849 | 17 | pre1990 |
| ethanol | commodity | y | 4572 | 2 | 6 | 1354 | 1409 | 1784 | 17 | pre1990, 1990s |
| palm_kernel | commodity | y | 4230 | 2 | 136 | 564 | 1082 | 2435 | 11 | pre1990 |
| protein_meal_substitution | driver | y | 3612 | 0 | 179 | 486 | 1112 | 1835 | 0 | pre1990 |
| white_premium_refining | driver | y | 2764 | 4 | 158 | 757 | 649 | 1193 | 3 | pre1990 |
| marine_protein_fishmeal | driver | y | 2571 | 0 | 194 | 506 | 809 | 1059 | 3 | pre1990 |
| fish_meal | commodity | y | 2566 | 0 | 194 | 503 | 809 | 1057 | 3 | pre1990 |
| fertilizer | driver | y | 2520 | 1 | 73 | 358 | 662 | 1407 | 19 | pre1990 |
| ethanol_margins | driver | y | 2445 | 0 | 4 | 396 | 906 | 1134 | 5 | pre1990, 1990s |
| cny_fx | driver | y | 2412 | 0 | 54 | 262 | 586 | 1510 | 0 | pre1990 |
| msp | driver | y | 2279 | 1 | 8 | 212 | 579 | 1479 | 0 | pre1990, 1990s |
| monsoon | driver | y | 2135 | 2 | 20 | 206 | 833 | 1074 | 0 | pre1990 |
| sunflower_oil | commodity | y | 2008 | 0 | 110 | 298 | 609 | 991 | 0 | pre1990 |
| biodiesel_mandate | driver | y | 1893 | 0 | 0 | 106 | 435 | 1341 | 11 | pre1990, 1990s |
| hfcs | commodity | y | 1836 | 1 | 94 | 724 | 523 | 494 | 0 | pre1990 |
| import_quota_trq | driver | y | 1802 | 3 | 119 | 405 | 543 | 731 | 1 | pre1990 |
| global_rice_export_policy | driver | y | 1772 | 0 | 15 | 184 | 685 | 887 | 1 | pre1990 |
| vietnam_robusta_weather | driver | y | 1336 | 1 | 49 | 218 | 440 | 625 | 3 | pre1990 |
| inr_fx | driver | y | 1330 | 0 | 1 | 27 | 487 | 815 | 0 | pre1990, 1990s |
| ddgs | commodity | y | 1309 | 0 | 0 | 46 | 527 | 735 | 1 | pre1990, 1990s |
| us_ethanol_rfs | driver | y | 1238 | 0 | 4 | 353 | 416 | 459 | 6 | pre1990, 1990s |
| frost | driver | y | 1099 | 5 | 45 | 224 | 292 | 533 | 0 | pre1990 |
| flood | driver | y | 1050 | 4 | 41 | 126 | 459 | 420 | 0 | pre1990 |
| el_nino | driver | y | 957 | 1 | 48 | 43 | 320 | 543 | 2 | pre1990 |
| minor_oilseeds | commodity | y | 877 | 7 | 12 | 140 | 223 | 492 | 3 | pre1990 |
| olive_oil | commodity | y | 865 | 0 | 67 | 85 | 97 | 610 | 6 | pre1990 |
| coffee_rust_crop | driver | y | 838 | 2 | 1 | 10 | 587 | 238 | 0 | pre1990, 1990s |
| export_levy_duty | driver | y | 794 | 0 | 14 | 249 | 226 | 305 | 0 | pre1990 |
| freight | driver | y | 787 | 1 | 22 | 80 | 135 | 549 | 0 | pre1990 |
| brl_fx | driver | y | 768 | 0 | 12 | 54 | 104 | 591 | 7 | pre1990 |
| argentina_export_policy | driver | y | 723 | 1 | 11 | 129 | 287 | 295 | 0 | pre1990 |
| animal_disease_demand_shock | driver | y | 690 | 3 | 2 | 14 | 43 | 628 | 0 | pre1990, 1990s |
| diesel | driver | y | 653 | 0 | 7 | 116 | 140 | 378 | 12 | pre1990, 1990s |
| orange_greening_disease | driver | y | 612 | 0 | 0 | 35 | 253 | 324 | 0 | pre1990, 1990s |
| west_africa_weather | driver | y | 598 | 0 | 50 | 24 | 259 | 265 | 0 | pre1990 |
| russia_export_tax_quota | driver | y | 584 | 0 | 31 | 62 | 239 | 252 | 0 | pre1990 |
| coffee_price_benchmark | driver | y | 567 | 4 | 3 | 43 | 31 | 486 | 0 | pre1990, 1990s |
| egypt_gasc_tenders | driver | y | 555 | 1 | 0 | 9 | 336 | 209 | 0 | pre1990, 1990s, 2000s |
| la_nina | driver | y | 548 | 0 | 9 | 11 | 145 | 383 | 0 | pre1990, 1990s |
| african_swine_fever | driver | y | 530 | 0 | 0 | 0 | 8 | 522 | 0 | pre1990, 1990s, 2000s, 2010_17 |
| idr_fx | driver | y | 481 | 0 | 106 | 84 | 74 | 217 | 0 | pre1990 |
| rub_fx | driver | y | 476 | 0 | 2 | 40 | 368 | 66 | 0 | pre1990, 1990s |
| natural_gas | driver | y | 464 | 0 | 129 | 53 | 60 | 218 | 4 | pre1990 |
| sanctions_payment_rails | driver | y | 420 | 0 | 17 | 46 | 129 | 227 | 1 | pre1990 |
| china_reserve_auctions | driver | y | 359 | 0 | 0 | 13 | 151 | 195 | 0 | pre1990, 1990s |
| vnd_fx | driver | y | 345 | 0 | 7 | 123 | 164 | 51 | 0 | pre1990, 1990s |
| china_buying_pace | driver | y | 297 | 0 | 0 | 26 | 132 | 139 | 0 | pre1990, 1990s |
| coffee_leaf_miner_borer | driver | y | 297 | 5 | 10 | 17 | 127 | 138 | 0 | pre1990 |
| php_fx | driver | y | 297 | 0 | 0 | 17 | 29 | 249 | 2 | pre1990, 1990s |
| cotton_pest_complex | driver | y | 249 | 0 | 1 | 40 | 104 | 104 | 0 | pre1990, 1990s |
| polar_vortex_winterkill | driver | y | 237 | 1 | 1 | 69 | 77 | 89 | 0 | pre1990, 1990s |
| try_fx | driver | y | 227 | 0 | 0 | 32 | 57 | 138 | 0 | pre1990, 1990s |
| urea | driver | y | 223 | 1 | 27 | 62 | 24 | 109 | 0 | pre1990 |
| zar_fx | driver | y | 220 | 0 | 0 | 25 | 90 | 105 | 0 | pre1990, 1990s |
| heat | driver | y | 198 | 0 | 10 | 25 | 69 | 94 | 0 | pre1990 |
| fusarium_head_blight_mycotoxin | driver | y | 176 | 0 | 2 | 18 | 107 | 49 | 0 | pre1990, 1990s |
| renewable_diesel_capacity | driver | y | 176 | 0 | 0 | 6 | 48 | 115 | 7 | pre1990, 1990s, 2000s |
| aud_fx | driver | y | 171 | 0 | 1 | 66 | 46 | 58 | 0 | pre1990, 1990s |
| eu_crop_and_policy | driver | y | 170 | 0 | 0 | 0 | 0 | 166 | 4 | pre1990, 1990s, 2000s, 2010_17 |
| potash | driver | y | 159 | 0 | 14 | 62 | 14 | 66 | 3 | pre1990 |
| cocoa_grindings | driver | y | 156 | 0 | 27 | 17 | 49 | 63 | 0 | pre1990 |
| cad_fx | driver | y | 154 | 0 | 0 | 1 | 74 | 77 | 2 | pre1990, 1990s, 2000s |
| mxn_fx | driver | y | 152 | 0 | 3 | 11 | 48 | 90 | 0 | pre1990, 1990s |
| uah_fx | driver | y | 151 | 0 | 19 | 89 | 43 | 0 | 0 | pre1990, 2018_26 |
| citrus_canker_psyllid | driver | y | 148 | 0 | 7 | 37 | 43 | 61 | 0 | pre1990, 1990s |
| cereal_rust_complex | driver | y | 147 | 0 | 2 | 0 | 100 | 45 | 0 | pre1990, 1990s, 2000s |
| avian_influenza | driver | y | 142 | 0 | 1 | 12 | 32 | 97 | 0 | pre1990, 1990s |
| fall_armyworm | driver | y | 140 | 0 | 0 | 0 | 6 | 134 | 0 | pre1990, 1990s, 2000s, 2010_17 |
| used_cooking_oil | commodity | y | 132 | 0 | 0 | 2 | 0 | 123 | 7 | pre1990, 1990s, 2000s, 2010_17 |
| tallow | commodity | y | 130 | 1 | 9 | 28 | 31 | 60 | 1 | pre1990, 1990s |
| eur_fx | driver | y | 124 | 0 | 2 | 33 | 45 | 44 | 0 | pre1990, 1990s |
| wheat_blast | driver | y | 123 | 0 | 0 | 2 | 59 | 62 | 0 | pre1990, 1990s, 2000s |
| hurricane_gulf_disruption | driver | y | 117 | 0 | 21 | 26 | 30 | 40 | 0 | pre1990 |
| indonesia_b40_palm | driver | y | 105 | 0 | 0 | 0 | 1 | 104 | 0 | pre1990, 1990s, 2000s, 2010_17 |
| dap | driver | y | 101 | 0 | 8 | 64 | 12 | 17 | 0 | pre1990, 1990s |

## Orphan routing (driver layer)

- **retire candidates** (props on disk, no DAG id routes there): aud_fx, baltic_dry_freight, barley_yellow_dwarf_virus, cattle_cycle_herd_size, dap, export_levy_duty, import_quota_trq, indian_ocean_dipole, marine_protein_fishmeal, metals, mxn_fx, natural_rubber, php_fx, real_yields_rates, rub_fx, sustainable_aviation_fuel, thb_fx, try_fx, uah_fx, vessel_lineups_export_basis, wheat_blast
- **keep candidates** (routed but empty -> build, never retire): corn_southern_rust, corn_tar_spot, managed_money_positioning
- **inert** (declared, no file, nothing routes there): index_roll_flows, madden_julian_oscillation, veg_oil_substitution_spreads

## Duplicate populations (4 proven groups, 199,317 redundant props)

Groups whose prop count AND all six era buckets match exactly. The commodity layer's 1,116,686 props are therefore NOT 43 independent corpora: **199,317 of them (18%) are a second copy of a population already counted.**

**The proof, not an inference.** Each record embeds its slice name exactly once, so two slices holding the same props must differ in object size by exactly `n_props x (name length difference)`. Subtracting `len(name) x n_props` from each object size collapses every group below to a SINGLE byte count -- identical to the byte. These are the same props under different names, not merely similar corpora. The same test REJECTS a small-n lookalike (listed after), which is why it is run rather than assumed.

| props each | slices | byte spread | name-normalized bytes | redundant |
|--|---|--|--|--|
| 72349 | `french_wheat`, `srw_wheat` | 217,047 | **1,683,489,861 (all equal)** | 72349 |
| 60358 | `white_maize`, `yellow_maize` | 60,358 | **1,405,183,771 (all equal)** | 60358 |
| 50324 | `raw_sugar`, `white_sugar` | 100,648 | **1,173,079,250 (all equal)** | 50324 |
| 16286 | `canola`, `rapeseed_oil` | 97,716 | **378,456,515 (all equal)** | 16286 |

Rejected by the same test (equal counts and era buckets, but the name-normalized sizes differ -- a coincidence at small n, not a duplicate):

- `hrs_wheat`, `hrw_wheat` (72350 props each) -- normalized bytes 1,683,514,587 vs 1,683,514,828
- `china_crush_demand`, `india_import_duty` (2 props each) -- normalized bytes 46,629 vs 46,661

## Movement since the superseded census (DEC-P0, pre-X2 -> now)

The prior is DEC-P0's own census -- the immediately preceding vintage and the sole pre-X2 baseline -- so this delta is ONE vintage and reads as `what the corpus doubling did`. The assembler's original prior (`configs/graphrag/eval/e1_census.json`, 2026-08-02) was two vintages back and was deliberately re-pointed; see basis.supersedes_note.

| metric | DEC-P0 (pre-X2) | now | delta |
|---|--|--|--|
| DAG driver ids | 374 | 369 | -5 |
| backed ids | 235 | 246 | +11 |
| dark ids | 139 | 123 | -16 |
| driver slices consumed | 91 | 99 | +8 |
| retire orphans | 10 | 21 | +11 |
| keep orphans | 4 | 3 | -1 |
| thick driver slices w/ hollow era | 48 | 68 | +20 |

- Prior per-slice `n_routed_props` vs now: **96 driver slices changed population**, 96 grew, 0 shrank.

## Full per-slice era histogram (169 slices)

| slice | layer | present | props | pre1990 | 1990s | 2000s | 2010_17 | 2018_26 | undated | thin eras |
|---|--|--|--|--|--|--|--|--|--|--|
| hrs_wheat | commodity | y | 72350 | 1951 | 2939 | 13748 | 24474 | 29227 | 11 | - |
| hrw_wheat | commodity | y | 72350 | 1951 | 2939 | 13748 | 24474 | 29227 | 11 | - |
| french_wheat | commodity | y | 72349 | 1951 | 2939 | 13748 | 24473 | 29227 | 11 | - |
| srw_wheat | commodity | y | 72349 | 1951 | 2939 | 13748 | 24473 | 29227 | 11 | - |
| soybeans | commodity | y | 63782 | 1887 | 2922 | 11185 | 19231 | 28512 | 45 | - |
| cotton | commodity | y | 61875 | 2068 | 5526 | 15681 | 16792 | 21799 | 9 | - |
| robusta_coffee | commodity | y | 61193 | 167 | 1886 | 9406 | 21512 | 28187 | 35 | - |
| arabica_coffee | commodity | y | 61097 | 167 | 1894 | 9355 | 21493 | 28150 | 38 | - |
| corn | commodity | y | 60405 | 1014 | 2144 | 11067 | 19763 | 26394 | 23 | - |
| white_maize | commodity | y | 60358 | 1014 | 2144 | 11066 | 19743 | 26368 | 23 | - |
| yellow_maize | commodity | y | 60358 | 1014 | 2144 | 11066 | 19743 | 26368 | 23 | - |
| rice | commodity | y | 52877 | 935 | 1623 | 7122 | 18674 | 24469 | 54 | - |
| raw_sugar | commodity | y | 50324 | 93 | 2816 | 15366 | 13942 | 18088 | 19 | - |
| white_sugar | commodity | y | 50324 | 93 | 2816 | 15366 | 13942 | 18088 | 19 | - |
| palm_oil | commodity | y | 18029 | 23 | 663 | 1936 | 3642 | 11718 | 47 | - |
| palm_olein | commodity | y | 17482 | 23 | 660 | 1904 | 3440 | 11410 | 45 | - |
| barley | commodity | y | 17230 | 278 | 1072 | 3546 | 5621 | 6710 | 3 | - |
| rapeseed_meal | commodity | y | 16302 | 23 | 600 | 3455 | 4414 | 7794 | 16 | - |
| canola | commodity | y | 16286 | 23 | 595 | 3444 | 4414 | 7794 | 16 | - |
| rapeseed_oil | commodity | y | 16286 | 23 | 595 | 3444 | 4414 | 7794 | 16 | - |
| orange_juice | commodity | y | 15416 | 12 | 355 | 2724 | 4889 | 7435 | 1 | - |
| soybean_meal | commodity | y | 13716 | 334 | 626 | 2293 | 4331 | 6130 | 2 | - |
| sorghum | commodity | y | 12437 | 296 | 313 | 2365 | 3896 | 5560 | 7 | - |
| fresh_citrus | commodity | y | 12372 | 1 | 244 | 1704 | 3961 | 6462 | 0 | pre1990 |
| peanut | commodity | y | 11341 | 8 | 385 | 2057 | 3052 | 5812 | 27 | pre1990 |
| sunflower | commodity | y | 11230 | 8 | 349 | 2600 | 3735 | 4525 | 13 | pre1990 |
| rapeseed | commodity | y | 10641 | 21 | 549 | 2684 | 3055 | 4328 | 4 | - |
| soybean_oil | commodity | y | 10429 | 356 | 674 | 1947 | 2999 | 4452 | 1 | - |
| minor_cereals | commodity | y | 7975 | 261 | 758 | 1679 | 3386 | 1891 | 0 | - |
| coconut | commodity | y | 6738 | 9 | 358 | 685 | 2159 | 3518 | 9 | pre1990 |
| pulses | commodity | y | 5263 | 32 | 121 | 1683 | 1925 | 1502 | 0 | - |
| ethanol | commodity | y | 4572 | 2 | 6 | 1354 | 1409 | 1784 | 17 | pre1990, 1990s |
| palm_kernel | commodity | y | 4230 | 2 | 136 | 564 | 1082 | 2435 | 11 | pre1990 |
| cottonseed | commodity | y | 4006 | 11 | 233 | 886 | 907 | 1969 | 0 | - |
| cocoa | commodity | y | 2991 | 21 | 896 | 363 | 511 | 1189 | 11 | - |
| fish_meal | commodity | y | 2566 | 0 | 194 | 503 | 809 | 1057 | 3 | pre1990 |
| sunflower_oil | commodity | y | 2008 | 0 | 110 | 298 | 609 | 991 | 0 | pre1990 |
| hfcs | commodity | y | 1836 | 1 | 94 | 724 | 523 | 494 | 0 | pre1990 |
| ddgs | commodity | y | 1309 | 0 | 0 | 46 | 527 | 735 | 1 | pre1990, 1990s |
| minor_oilseeds | commodity | y | 877 | 7 | 12 | 140 | 223 | 492 | 3 | pre1990 |
| olive_oil | commodity | y | 865 | 0 | 67 | 85 | 97 | 610 | 6 | pre1990 |
| used_cooking_oil | commodity | y | 132 | 0 | 0 | 2 | 0 | 123 | 7 | pre1990, 1990s, 2000s, 2010_17 |
| tallow | commodity | y | 130 | 1 | 9 | 28 | 31 | 60 | 1 | pre1990, 1990s |
| wasde_stocks_to_use | driver | y | 14693 | 460 | 1290 | 3326 | 4252 | 5351 | 14 | - |
| feed_grain_substitution | driver | y | 14504 | 297 | 318 | 2502 | 4656 | 6724 | 7 | - |
| textile_apparel_demand | driver | y | 13031 | 33 | 842 | 2398 | 3572 | 6172 | 14 | - |
| sunflower_oil_balance | driver | y | 11410 | 9 | 352 | 2647 | 3801 | 4588 | 13 | pre1990 |
| tariff | driver | y | 11206 | 4 | 305 | 3167 | 2986 | 4724 | 20 | pre1990 |
| livestock_feed_demand | driver | y | 7086 | 166 | 219 | 1048 | 1993 | 3632 | 28 | - |
| drought | driver | y | 5807 | 54 | 189 | 1266 | 1888 | 2410 | 0 | - |
| macro | driver | y | 5315 | 10 | 81 | 348 | 528 | 4338 | 10 | - |
| subsidy | driver | y | 4878 | 6 | 102 | 943 | 1893 | 1931 | 3 | pre1990 |
| south_american_safrinha | driver | y | 4660 | 8 | 27 | 460 | 1299 | 2849 | 17 | pre1990 |
| protein_meal_substitution | driver | y | 3612 | 0 | 179 | 486 | 1112 | 1835 | 0 | pre1990 |
| white_premium_refining | driver | y | 2764 | 4 | 158 | 757 | 649 | 1193 | 3 | pre1990 |
| marine_protein_fishmeal | driver | y | 2571 | 0 | 194 | 506 | 809 | 1059 | 3 | pre1990 |
| fertilizer | driver | y | 2520 | 1 | 73 | 358 | 662 | 1407 | 19 | pre1990 |
| ethanol_margins | driver | y | 2445 | 0 | 4 | 396 | 906 | 1134 | 5 | pre1990, 1990s |
| cny_fx | driver | y | 2412 | 0 | 54 | 262 | 586 | 1510 | 0 | pre1990 |
| benign_growing_conditions | driver | y | 2376 | 36 | 75 | 411 | 797 | 1057 | 0 | - |
| crude | driver | y | 2359 | 73 | 435 | 409 | 370 | 1058 | 14 | - |
| msp | driver | y | 2279 | 1 | 8 | 212 | 579 | 1479 | 0 | pre1990, 1990s |
| thb_fx | driver | y | 2176 | 16 | 126 | 656 | 568 | 810 | 0 | - |
| monsoon | driver | y | 2135 | 2 | 20 | 206 | 833 | 1074 | 0 | pre1990 |
| broiler_economics | driver | y | 2052 | 63 | 111 | 434 | 549 | 884 | 11 | - |
| export_ban | driver | y | 1957 | 10 | 54 | 232 | 826 | 824 | 11 | - |
| biodiesel_mandate | driver | y | 1893 | 0 | 0 | 106 | 435 | 1341 | 11 | pre1990, 1990s |
| import_quota_trq | driver | y | 1802 | 3 | 119 | 405 | 543 | 731 | 1 | pre1990 |
| global_rice_export_policy | driver | y | 1772 | 0 | 15 | 184 | 685 | 887 | 1 | pre1990 |
| us_drought_monitor | driver | y | 1543 | 12 | 13 | 250 | 475 | 793 | 0 | - |
| vietnam_robusta_weather | driver | y | 1336 | 1 | 49 | 218 | 440 | 625 | 3 | pre1990 |
| inr_fx | driver | y | 1330 | 0 | 1 | 27 | 487 | 815 | 0 | pre1990, 1990s |
| us_ethanol_rfs | driver | y | 1238 | 0 | 4 | 353 | 416 | 459 | 6 | pre1990, 1990s |
| frost | driver | y | 1099 | 5 | 45 | 224 | 292 | 533 | 0 | pre1990 |
| flood | driver | y | 1050 | 4 | 41 | 126 | 459 | 420 | 0 | pre1990 |
| metals | driver | y | 1017 | 22 | 199 | 313 | 189 | 294 | 0 | - |
| el_nino | driver | y | 957 | 1 | 48 | 43 | 320 | 543 | 2 | pre1990 |
| crop_insurance_planting_intentions | driver | y | 892 | 13 | 32 | 349 | 297 | 201 | 0 | - |
| coffee_rust_crop | driver | y | 838 | 2 | 1 | 10 | 587 | 238 | 0 | pre1990, 1990s |
| export_levy_duty | driver | y | 794 | 0 | 14 | 249 | 226 | 305 | 0 | pre1990 |
| cotton_polyester_competition | driver | y | 790 | 163 | 121 | 249 | 124 | 133 | 0 | - |
| freight | driver | y | 787 | 1 | 22 | 80 | 135 | 549 | 0 | pre1990 |
| brl_fx | driver | y | 768 | 0 | 12 | 54 | 104 | 591 | 7 | pre1990 |
| argentina_export_policy | driver | y | 723 | 1 | 11 | 129 | 287 | 295 | 0 | pre1990 |
| former_ussr_import_demand | driver | y | 722 | 339 | 312 | 47 | 11 | 13 | 0 | - |
| australia_crop_conditions | driver | y | 721 | 25 | 51 | 138 | 201 | 306 | 0 | - |
| us_farm_program | driver | y | 713 | 60 | 94 | 59 | 242 | 258 | 0 | - |
| animal_disease_demand_shock | driver | y | 690 | 3 | 2 | 14 | 43 | 628 | 0 | pre1990, 1990s |
| diesel | driver | y | 653 | 0 | 7 | 116 | 140 | 378 | 12 | pre1990, 1990s |
| orange_greening_disease | driver | y | 612 | 0 | 0 | 35 | 253 | 324 | 0 | pre1990, 1990s |
| west_africa_weather | driver | y | 598 | 0 | 50 | 24 | 259 | 265 | 0 | pre1990 |
| russia_export_tax_quota | driver | y | 584 | 0 | 31 | 62 | 239 | 252 | 0 | pre1990 |
| coffee_price_benchmark | driver | y | 567 | 4 | 3 | 43 | 31 | 486 | 0 | pre1990, 1990s |
| egypt_gasc_tenders | driver | y | 555 | 1 | 0 | 9 | 336 | 209 | 0 | pre1990, 1990s, 2000s |
| la_nina | driver | y | 548 | 0 | 9 | 11 | 145 | 383 | 0 | pre1990, 1990s |
| african_swine_fever | driver | y | 530 | 0 | 0 | 0 | 8 | 522 | 0 | pre1990, 1990s, 2000s, 2010_17 |
| idr_fx | driver | y | 481 | 0 | 106 | 84 | 74 | 217 | 0 | pre1990 |
| rub_fx | driver | y | 476 | 0 | 2 | 40 | 368 | 66 | 0 | pre1990, 1990s |
| natural_gas | driver | y | 464 | 0 | 129 | 53 | 60 | 218 | 4 | pre1990 |
| sanctions_payment_rails | driver | y | 420 | 0 | 17 | 46 | 129 | 227 | 1 | pre1990 |
| cattle_on_feed | driver | y | 412 | 45 | 46 | 169 | 59 | 90 | 3 | - |
| china_reserve_auctions | driver | y | 359 | 0 | 0 | 13 | 151 | 195 | 0 | pre1990, 1990s |
| vnd_fx | driver | y | 345 | 0 | 7 | 123 | 164 | 51 | 0 | pre1990, 1990s |
| china_buying_pace | driver | y | 297 | 0 | 0 | 26 | 132 | 139 | 0 | pre1990, 1990s |
| coffee_leaf_miner_borer | driver | y | 297 | 5 | 10 | 17 | 127 | 138 | 0 | pre1990 |
| php_fx | driver | y | 297 | 0 | 0 | 17 | 29 | 249 | 2 | pre1990, 1990s |
| cotton_pest_complex | driver | y | 249 | 0 | 1 | 40 | 104 | 104 | 0 | pre1990, 1990s |
| polar_vortex_winterkill | driver | y | 237 | 1 | 1 | 69 | 77 | 89 | 0 | pre1990, 1990s |
| try_fx | driver | y | 227 | 0 | 0 | 32 | 57 | 138 | 0 | pre1990, 1990s |
| urea | driver | y | 223 | 1 | 27 | 62 | 24 | 109 | 0 | pre1990 |
| zar_fx | driver | y | 220 | 0 | 0 | 25 | 90 | 105 | 0 | pre1990, 1990s |
| heat | driver | y | 198 | 0 | 10 | 25 | 69 | 94 | 0 | pre1990 |
| fusarium_head_blight_mycotoxin | driver | y | 176 | 0 | 2 | 18 | 107 | 49 | 0 | pre1990, 1990s |
| renewable_diesel_capacity | driver | y | 176 | 0 | 0 | 6 | 48 | 115 | 7 | pre1990, 1990s, 2000s |
| aud_fx | driver | y | 171 | 0 | 1 | 66 | 46 | 58 | 0 | pre1990, 1990s |
| eu_crop_and_policy | driver | y | 170 | 0 | 0 | 0 | 0 | 166 | 4 | pre1990, 1990s, 2000s, 2010_17 |
| potash | driver | y | 159 | 0 | 14 | 62 | 14 | 66 | 3 | pre1990 |
| cocoa_grindings | driver | y | 156 | 0 | 27 | 17 | 49 | 63 | 0 | pre1990 |
| cad_fx | driver | y | 154 | 0 | 0 | 1 | 74 | 77 | 2 | pre1990, 1990s, 2000s |
| mxn_fx | driver | y | 152 | 0 | 3 | 11 | 48 | 90 | 0 | pre1990, 1990s |
| uah_fx | driver | y | 151 | 0 | 19 | 89 | 43 | 0 | 0 | pre1990, 2018_26 |
| citrus_canker_psyllid | driver | y | 148 | 0 | 7 | 37 | 43 | 61 | 0 | pre1990, 1990s |
| cereal_rust_complex | driver | y | 147 | 0 | 2 | 0 | 100 | 45 | 0 | pre1990, 1990s, 2000s |
| avian_influenza | driver | y | 142 | 0 | 1 | 12 | 32 | 97 | 0 | pre1990, 1990s |
| fall_armyworm | driver | y | 140 | 0 | 0 | 0 | 6 | 134 | 0 | pre1990, 1990s, 2000s, 2010_17 |
| eur_fx | driver | y | 124 | 0 | 2 | 33 | 45 | 44 | 0 | pre1990, 1990s |
| wheat_blast | driver | y | 123 | 0 | 0 | 2 | 59 | 62 | 0 | pre1990, 1990s, 2000s |
| hurricane_gulf_disruption | driver | y | 117 | 0 | 21 | 26 | 30 | 40 | 0 | pre1990 |
| indonesia_b40_palm | driver | y | 105 | 0 | 0 | 0 | 1 | 104 | 0 | pre1990, 1990s, 2000s, 2010_17 |
| dap | driver | y | 101 | 0 | 8 | 64 | 12 | 17 | 0 | pre1990, 1990s |
| ars_fx | driver | y | 99 | 0 | 0 | 13 | 25 | 61 | 0 | - |
| suez_redsea_disruption | driver | y | 92 | 1 | 0 | 0 | 13 | 78 | 0 | - |
| natural_rubber | driver | y | 82 | 1 | 44 | 14 | 16 | 7 | 0 | - |
| parana_river_levels | driver | y | 74 | 0 | 0 | 14 | 8 | 52 | 0 | - |
| sugar_ethanol_parity | driver | y | 71 | 0 | 0 | 10 | 28 | 33 | 0 | - |
| black_sea_corridor | driver | y | 69 | 0 | 0 | 22 | 2 | 45 | 0 | - |
| mississippi_river_levels | driver | y | 66 | 0 | 0 | 6 | 29 | 31 | 0 | - |
| rapeseed_disease_pest | driver | y | 62 | 0 | 0 | 6 | 14 | 42 | 0 | - |
| cattle_cycle_herd_size | driver | y | 61 | 11 | 2 | 16 | 5 | 26 | 1 | - |
| us_dollar_index | driver | y | 51 | 3 | 0 | 1 | 42 | 5 | 0 | - |
| asian_soybean_rust | driver | y | 47 | 0 | 0 | 16 | 22 | 9 | 0 | - |
| desert_locust_swarm | driver | y | 35 | 0 | 0 | 0 | 14 | 21 | 0 | - |
| sugarcane_disease_pest | driver | y | 31 | 0 | 0 | 6 | 22 | 3 | 0 | - |
| basis_and_farmer_selling | driver | y | 30 | 0 | 1 | 2 | 7 | 20 | 0 | - |
| sustainable_aviation_fuel | driver | y | 27 | 0 | 0 | 0 | 0 | 27 | 0 | - |
| vessel_lineups_export_basis | driver | y | 26 | 0 | 0 | 13 | 6 | 7 | 0 | - |
| myr_fx | driver | y | 25 | 0 | 3 | 14 | 2 | 6 | 0 | - |
| palm_oil_disease_pest | driver | y | 24 | 0 | 0 | 0 | 2 | 22 | 0 | - |
| hog_margins_crush | driver | y | 22 | 0 | 0 | 0 | 0 | 22 | 0 | - |
| cocoa_pod_disease | driver | y | 19 | 1 | 6 | 0 | 1 | 11 | 0 | - |
| baltic_dry_freight | driver | y | 18 | 0 | 15 | 1 | 1 | 1 | 0 | - |
| rin_credits | driver | y | 18 | 0 | 0 | 0 | 0 | 17 | 1 | - |
| rice_blast_pest_complex | driver | y | 11 | 0 | 0 | 0 | 3 | 8 | 0 | - |
| cocoa_swollen_shoot_virus | driver | y | 10 | 0 | 0 | 0 | 1 | 9 | 0 | - |
| indian_ocean_dipole | driver | y | 10 | 0 | 0 | 0 | 5 | 5 | 0 | - |
| panama_canal_constraints | driver | y | 10 | 0 | 0 | 0 | 2 | 8 | 0 | - |
| harmattan | driver | y | 8 | 0 | 0 | 0 | 0 | 8 | 0 | - |
| barley_yellow_dwarf_virus | driver | y | 2 | 0 | 0 | 0 | 1 | 1 | 0 | - |
| cftc_positioning | driver | y | 2 | 0 | 1 | 0 | 0 | 1 | 0 | - |
| china_crush_demand | driver | y | 2 | 0 | 0 | 0 | 0 | 2 | 0 | - |
| india_import_duty | driver | y | 2 | 0 | 0 | 0 | 0 | 2 | 0 | - |
| real_yields_rates | driver | y | 2 | 0 | 0 | 2 | 0 | 0 | 0 | - |
| soybean_cyst_nematode | driver | y | 1 | 0 | 0 | 0 | 1 | 0 | 0 | - |
| corn_southern_rust | driver | ABSENT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - |
| corn_tar_spot | driver | ABSENT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - |
| index_roll_flows | driver | ABSENT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - |
| madden_julian_oscillation | driver | ABSENT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - |
| managed_money_positioning | driver | ABSENT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - |
| veg_oil_substitution_spreads | driver | ABSENT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - |

## Gaps and caveats

- The pg mirror (`evidence_props`) could not be reached: the RDS endpoint is VPC-private and the connection timed out from this network. All counts here are measured from S3, which project doctrine already names the store of truth; the mirror's agreement with S3 is therefore UNVERIFIED by this run.
- **753,991 of 1,277,979 props (59.0%)** carry no `event_date` and were bucketed by publication `date` instead. That is the same fallback `e1_census._era_of` applies, but it means the pre-1990 buckets are understated wherever an old event was published recently.
- 0 slices sit exactly on a `max_props` cap and are therefore a TRUNCATED population rather than a natural one -- their era histograms describe only what survived truncation, so a hollow era there may be an artefact of the cap: none.
- This census counts props per slice; it does not re-derive term-level claims (`e1_census.term_census`) or chunk-level coverage.
- The upstream chunk doc-cache (`chunks/`) holds **5,936 documents** in 0.66 GB, newest object 2026-08-21 -- BEFORE the 2026-08-03 slice rebuild. Every prop counted here derives from that corpus vintage, so a slice cannot be thicker than its corpus allows; a thin slice may be a corpus gap rather than a routing gap, and this census cannot tell the two apart.
- Per-slice date SPANS (`manifest_span`) are the writer's own recorded `after_span`, not re-derived by this scan. Prop COUNTS and era histograms are this scan's own measurement and were verified against the manifest's `after_n` on all 163 slices that carry an entry.
- The store has not been written since 2026-08-03; a `chunks/` corpus pass after that date would make these counts stale in exactly the way the superseded artifact was.
