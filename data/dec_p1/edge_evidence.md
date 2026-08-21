# Edge evidence audit -- what the CORPUS says about the causal DAG edges

Generated 2026-08-21T13:09:35Z | artifact: `data/dec_p1/edge_evidence.json`

## Headline

- **2,634 DAG edge rows** across 33 `configs/graphrag/causal/*.yaml` collapse to **1008 distinct unordered endpoint pairs** (co-mention is symmetric).
- Corpus: **1,387,697 unique chunks** over **5,927 source documents**; mean chunk length **97.4 chars** -- these are sentence-scale props, so a same-chunk co-mention is a SAME-SENTENCE test.
- **389 of 1008 pairs (38%) are corpus-supported** (>2 same-chunk co-mentions).
- **292 pairs are prop-dark** (<= 2 same-chunk co-mentions with both endpoints above the 100-mention floor); of those **25 are dark at the DOCUMENT level too** -- the two endpoints never share a source document at all.
- **327 pairs are unmeasurable**: at least one endpoint is mentioned fewer than 100 times in the whole corpus. A zero there means nothing.
- **108 DAG driver ids have no surface form at all** and could not be tested. Every one of them is already declared in `driver_slices.yaml` waivers (`unmapped_all_waivered = True`) -- so this is a known, recorded gap, not a new one.
- The corpus co-mentions **7,948 distinct entity pairs** in the same chunk and **23,600** in the same document. **2,835 co-mentioned pairs have no DAG edge** once country/region/organization endpoints are set aside (7,416 including them).
- **44 entities carry ZERO DAG edges** despite real corpus presence -- the largest being `grains` (31,015 mentions), `minor_cereals` (13,011 mentions), `oilseeds` (12,857 mentions).
- **15 existing edge endpoints are never mentioned once** in 1,387,697 chunks: `arabica_robusta_spread`, `biennial_off_year`, `biennial_on_year`, `board_crush`, `corn_southern_rust`, `corn_tar_spot`, `crush_margin_expansion`, `export_pace_lag`, `flowering_stress`, `iod_negative`, `iod_positive`, `managed_money_positioning`, `replanting_cycle`, `soyoil_palm_premium`, `tenderable_collapse`.

## Method (and what it is NOT)

- Matcher semantics **copied from production** (`leviathan.graphrag.harvest._Matcher` + `extract._normalize`): NFKD->ascii, `[\s_-]+` -> space, lowercase, `\b` word boundaries, longest-first alternation. **1108 surface forms** over **297 of 298 entities**.
- Surface forms come from `entity_vocabulary.yaml` (nodes + aliases) and the `driver_slices.yaml` per-slice term lists. Slice NAMES were deliberately not added as surface forms -- the config keeps terms specific on purpose ("heat wave", not bare "heat").
- 8 config aliases blocked because they normalize to ordinary English words: `don`, `eu`, `mg`, `minas`, `mot`, `real`, `sap`, `us`.
- 51 pairs share a surface form outright (e.g. `protein_meal_substitution` lists "rapeseed meal"); their "co-mentions" are one string firing twice, so they are excluded from the new-edge list and flagged everywhere else.
- **pg was preferred and is unreachable.** pg (evidence_props) stays PREFERRED-but-unreachable: EVIDENCE_PG_DSN is not set in this env at all and the RDS DSN is VPC-private. Note the two live numbers do NOT reconcile and should not be forced to: pg holds 1,277,979 props (from write_manifest_rebuild_20260820T180701Z) while chunks/ now holds ~1.37M -- the gap is the 2026-08-21 x2 tail merge, which has not been rebuilt into pg.
- **No sampling.** NO sampling. All 1,387,697 unique chunks in the live store were matched (1,387,697 lines scanned before dedup).
- Co-mention is **association, not causation**. This audit ranks review candidates; it does not mint or retire edges.

## (a) NEW-edge candidates -- co-mentioned, no edge

Ranked within the shapes the DAGs actually encode. `lift` = observed / expected-if-independent; `npmi` normalizes it to [-1, 1].

### Driver x commodity (the `driver -> contract` shape) -- top 20 by same-chunk co-mention

| node A | node B | same-chunk | same-doc | A seen | B seen | lift | npmi |
|---|---|---|---|---|---|---|---|
| wasde_stocks_to_use | wheat | 19732 | 1227 | 101850 | 186276 | 1.44 | 0.086 |
| grains | wasde_stocks_to_use | 5186 | 856 | 31015 | 101850 | 2.28 | 0.147 |
| oilseeds | wasde_stocks_to_use | 2117 | 556 | 12857 | 101850 | 2.24 | 0.125 |
| vegetable_oils | wasde_stocks_to_use | 2085 | 373 | 11083 | 101850 | 2.56 | 0.145 |
| barley | wasde_stocks_to_use | 1056 | 806 | 25351 | 101850 | 0.57 | -0.079 |
| drought | wheat | 1030 | 1412 | 10793 | 186276 | 0.71 | -0.047 |
| sorghum | wasde_stocks_to_use | 1026 | 718 | 20811 | 101850 | 0.67 | -0.055 |
| import_tariff | wheat | 1005 | 1006 | 11805 | 186276 | 0.63 | -0.063 |
| minor_cereals | wasde_stocks_to_use | 824 | 586 | 13011 | 101850 | 0.86 | -0.02 |
| cotton | safrinha | 782 | 502 | 129009 | 7380 | 1.14 | 0.017 |
| drought | hfcs | 680 | 236 | 10793 | 2023 | 43.22 | 0.494 |
| wheat | wheat_corn_spread | 671 | 1358 | 186276 | 22740 | 0.22 | -0.198 |
| msp | wheat | 577 | 192 | 2393 | 186276 | 1.8 | 0.075 |
| feed_grains | wasde_stocks_to_use | 562 | 317 | 8188 | 101850 | 0.94 | -0.009 |
| cny_fx | corn | 440 | 149 | 2416 | 137537 | 1.84 | 0.076 |
| minor_cereals | wheat_corn_spread | 436 | 683 | 13011 | 22740 | 2.04 | 0.089 |
| thb_fx | white_sugar | 436 | 70 | 2488 | 5094 | 47.74 | 0.479 |
| corn | subsidy | 424 | 606 | 137537 | 4888 | 0.88 | -0.016 |
| rice | west_africa_weather | 423 | 114 | 99522 | 613 | 9.62 | 0.28 |
| cny_fx | wheat | 407 | 120 | 2416 | 186276 | 1.25 | 0.028 |

### Commodity x commodity (the `inter_commodity` shape) -- top 15

| node A | node B | same-chunk | same-doc | A seen | B seen | lift | npmi |
|---|---|---|---|---|---|---|---|
| hrs_wheat | wheat | 1380 | 574 | 4242 | 186276 | 2.42 | 0.128 |
| barley | wheat | 1338 | 1435 | 25351 | 186276 | 0.39 | -0.134 |
| hrw_wheat | wheat | 1294 | 381 | 3431 | 186276 | 2.81 | 0.148 |
| srw_wheat | wheat | 1160 | 224 | 1277 | 186276 | 6.77 | 0.27 |
| corn | ethanol | 820 | 583 | 137537 | 4341 | 1.91 | 0.087 |
| barley | minor_cereals | 682 | 765 | 25351 | 13011 | 2.87 | 0.138 |
| barley | sorghum | 607 | 902 | 25351 | 20811 | 1.6 | 0.06 |
| corn | minor_cereals | 539 | 821 | 137537 | 13011 | 0.42 | -0.111 |
| corn | grains | 539 | 1160 | 137537 | 31015 | 0.18 | -0.222 |
| corn | hfcs | 469 | 280 | 137537 | 2023 | 2.34 | 0.106 |
| grains | wheat | 455 | 1162 | 31015 | 186276 | 0.11 | -0.276 |
| soybeans | sunflower | 453 | 957 | 100885 | 9652 | 0.65 | -0.055 |
| minor_cereals | sorghum | 428 | 596 | 13011 | 20811 | 2.19 | 0.097 |
| minor_cereals | wheat | 387 | 828 | 13011 | 186276 | 0.22 | -0.184 |
| grains | oilseeds | 371 | 566 | 31015 | 12857 | 1.29 | 0.031 |

### Driver x driver (the `parents` / convergence shape) -- top 15

| node A | node B | same-chunk | same-doc | A seen | B seen | lift | npmi |
|---|---|---|---|---|---|---|---|
| wasde_stocks_to_use | wheat_corn_spread | 1021 | 842 | 101850 | 22740 | 0.61 | -0.068 |
| import_quota_trq | import_tariff | 951 | 494 | 1826 | 11805 | 61.22 | 0.565 |
| subsidy | textile_apparel_demand | 583 | 252 | 4888 | 15270 | 10.84 | 0.307 |
| import_tariff | quota | 533 | 587 | 11805 | 1793 | 34.94 | 0.452 |
| cny_fx | subsidy | 426 | 173 | 2416 | 4888 | 50.06 | 0.484 |
| global_rice_export_policy | wasde_stocks_to_use | 344 | 439 | 5324 | 101850 | 0.88 | -0.015 |
| inr_fx | msp | 318 | 170 | 1447 | 2393 | 127.44 | 0.578 |
| subsidy | us_farm_program | 265 | 102 | 4888 | 1049 | 71.72 | 0.499 |
| livestock_feed_demand | wheat_corn_spread | 252 | 861 | 21944 | 22740 | 0.7 | -0.041 |
| textile_apparel_demand | us_farm_program | 235 | 112 | 15270 | 1049 | 20.36 | 0.347 |
| fertilizer | subsidy | 218 | 303 | 2483 | 4888 | 24.93 | 0.367 |
| import_tariff | textile_apparel_demand | 217 | 383 | 11805 | 15270 | 1.67 | 0.059 |
| cny_fx | textile_apparel_demand | 207 | 127 | 2416 | 15270 | 7.79 | 0.233 |
| import_tariff | wheat_corn_spread | 177 | 695 | 11805 | 22740 | 0.91 | -0.01 |
| broiler_economics | wasde_stocks_to_use | 176 | 549 | 8849 | 101850 | 0.27 | -0.146 |

### Strongest association regardless of shape -- top 20 by npmi (min 60 same-chunk co-mentions)

This is the list to read if you want *mechanism* candidates rather than *frequency*: high npmi means the two names appear together far more than their solo rates predict.

| node A | node B | same-chunk | same-doc | A seen | B seen | lift | npmi |
|---|---|---|---|---|---|---|---|
| aluminium | copper | 60 | 103 | 364 | 417 | 548.54 | 0.628 |
| vietnam_robusta_weather | vnd_fx | 94 | 43 | 1341 | 345 | 281.95 | 0.588 |
| inr_fx | msp | 318 | 170 | 1447 | 2393 | 127.44 | 0.578 |
| import_quota_trq | import_tariff | 951 | 494 | 1826 | 11805 | 61.22 | 0.565 |
| biodiesel | diesel | 110 | 107 | 1761 | 604 | 143.51 | 0.526 |
| ethanol | us_ethanol_rfs | 261 | 366 | 4341 | 1080 | 77.25 | 0.507 |
| subsidy | us_farm_program | 265 | 102 | 4888 | 1049 | 71.72 | 0.499 |
| drought | hfcs | 680 | 236 | 10793 | 2023 | 43.22 | 0.494 |
| cny_fx | subsidy | 426 | 173 | 2416 | 4888 | 50.06 | 0.484 |
| thb_fx | white_sugar | 436 | 70 | 2488 | 5094 | 47.74 | 0.479 |
| import_tariff | quota | 533 | 587 | 11805 | 1793 | 34.94 | 0.452 |
| ethanol | ethanol_margins | 307 | 411 | 4341 | 2285 | 42.95 | 0.447 |
| php_fx | white_raw_premium | 63 | 17 | 372 | 3654 | 64.32 | 0.416 |
| fresh_citrus | zar_fx | 114 | 17 | 12814 | 256 | 48.23 | 0.412 |
| cny_fx | msp | 162 | 49 | 2416 | 2393 | 38.88 | 0.404 |
| raw_sugar | white_raw_premium | 316 | 406 | 4549 | 3654 | 26.38 | 0.39 |
| php_fx | white_sugar | 63 | 19 | 372 | 5094 | 46.14 | 0.383 |
| raw_sugar | thb_fx | 223 | 73 | 4549 | 2488 | 27.34 | 0.379 |
| palm_oil | palm_olein | 132 | 154 | 13048 | 435 | 32.27 | 0.375 |
| import_quota_trq | quota | 87 | 339 | 1826 | 1793 | 36.88 | 0.373 |

### Out of DAG scope (country / region / organization endpoints)

25 shown of 4,581. These are origin anchors and attribution sources, not causal-DAG nodes -- listed for completeness, not as edge proposals.

| node A | node B | same-chunk | same-doc | A seen | B seen | lift | npmi |
|---|---|---|---|---|---|---|---|
| cotton | india | 15862 | 1112 | 129009 | 64819 | 2.63 | 0.216 |
| china | cotton | 14509 | 1248 | 87454 | 129009 | 1.78 | 0.127 |
| united_states | wasde_stocks_to_use | 12339 | 1501 | 106704 | 101850 | 1.58 | 0.096 |
| corn | south_africa | 11778 | 918 | 137537 | 32047 | 3.71 | 0.275 |
| cotton | united_states | 11189 | 1087 | 129009 | 106704 | 1.13 | 0.025 |
| china | corn | 10668 | 1482 | 87454 | 137537 | 1.23 | 0.043 |
| brazil | soybeans | 10499 | 1260 | 58864 | 100885 | 2.45 | 0.184 |
| rice | united_states | 10427 | 1168 | 99522 | 106704 | 1.36 | 0.063 |
| china | wheat | 10306 | 1327 | 87454 | 186276 | 0.88 | -0.027 |
| united_states | wheat | 9967 | 1261 | 106704 | 186276 | 0.7 | -0.073 |

### Verbatim corpus evidence (integrity check)

Every pair in the three shape tables above has up to 3 real chunks recorded in the JSON under `a_new_edge_candidates.verbatim_examples` (36 pairs). A sample, so the ranking can be checked rather than trusted:

- **corn | ethanol** -- `usda_gain_corn` 2015-03-18: "Large quantities of U.S. grown corn are used as an ethanol feedstock, resulting in expansion of Mexico's DDGS imports."
- **inr_fx | msp** -- `usda_gain_sugar` 2020-05-01: "The Union Cabinet decided that the Fair and Remunerative Price (FRP) for sugarcane in India in MY 2019/20 will remain unchanged at INR 275/quintal."

## (b) UNSUPPORTED existing edges -- edge exists, ~zero co-mention

**Candidates for REVIEW, not deletion.** Ranked by surprise: `expected` is how many same-chunk co-mentions the two endpoints would produce by chance alone at their observed solo frequencies. A zero against a large expectation is the signal; a zero against `expected = 0.4` is nothing. `same-doc` is the mitigator -- if it is large, the pair does co-occur in documents and only the single-sentence statement is missing.

Full ranked list: **292 pairs** in the JSON. Top 25 here.

| node A | node B | same-chunk | same-doc | expected | DAG rows | edge type | in DAGs |
|---|---|---|---|---|---|---|---|
| australia_crop_conditions | corn | 0 | 413 | 580.5 | 1 | correlates_with | french_maize_matif |
| corn | raw_sugar | 2 | 214 | 450.9 | 1 | competes_with | raw_sugar |
| wheat | yellow_maize | 0 | 156 | 369.4 | 1 | substitutes_for | south_african_yellow_maize_jse |
| wheat | white_maize | 0 | 157 | 363.4 | 1 | substitutes_for | south_african_white_maize_jse |
| subsidy | wasde_stocks_to_use | 2 | 469 | 358.8 | 3 | causes | cotton, raw_sugar, white_sugar |
| corn | hrw_wheat | 2 | 378 | 340.1 | 1 | competes_with | hard_red_winter_wheat_kcbt |
| drought | soybean_oil | 2 | 653 | 303.9 | 3 | affects_yield_of | soybean_oil_cbot, soybean_oil_dce |
| wasde_stocks_to_use | yellow_maize | 0 | 3 | 202 | 1 | causes | south_african_yellow_maize_jse |
| wasde_stocks_to_use | white_maize | 0 | 3 | 198.7 | 1 | causes | south_african_white_maize_jse |
| ethanol_margins | wasde_stocks_to_use | 1 | 354 | 167.7 | 1 | causes | campinas_corn_reference_bmf |
| monsoon | wasde_stocks_to_use | 0 | 223 | 157.7 | 1 | causes | rough_rice_cbot |
| soybeans | srw_wheat | 0 | 184 | 92.8 | 1 | competes_with | soft_red_winter_wheat_cbot |
| frost | wasde_stocks_to_use | 0 | 193 | 89 | 3 | causes | arabica_coffee, brazilian_arabica_coffee... |
| us_ethanol_rfs | wasde_stocks_to_use | 1 | 236 | 79.3 | 2 | causes | corn, corn_cbot |
| soybeans | us_ethanol_rfs | 0 | 138 | 78.5 | 2 | causes | soybeans, soybeans_cbot |
| brl_fx | wasde_stocks_to_use | 0 | 79 | 75.2 | 1 | amplifies | robusta_coffee |
| favorable_rainfall | soybean_oil | 0 | 240 | 71.4 | 1 | affects_yield_of | soybean_oil_dce |
| favorable_rainfall | soybean_meal | 0 | 272 | 69.3 | 2 | affects_yield_of | soybean_meal_cbot, soybean_meal_dce |
| export_tax | wasde_stocks_to_use | 0 | 91 | 52.2 | 1 | causes | soybean_oil_cbot |
| hrw_wheat | sorghum | 0 | 342 | 51.5 | 1 | competes_with | hard_red_winter_wheat_kcbt |
| corn | natural_gas | 2 | 70 | 51.1 | 4 | causes | campinas_corn_reference_bmf, corn, corn_... |
| hlb | wasde_stocks_to_use | 0 | 13 | 43.6 | 2 | causes | frozen_orange_juice |
| african_swine_fever | wasde_stocks_to_use | 0 | 76 | 39 | 1 | causes | soybeans_no_2_dce |
| frost | soybean_meal | 0 | 79 | 33.1 | 2 | affects_yield_of | soybean_meal_cbot, soybean_meal_dce |
| palm_olein | soybeans | 0 | 80 | 31.6 | 1 | correlates_with | palm_olein_dce |

### Why the top rows are dark (authored mechanism, verbatim from the DAG)

- **australia_crop_conditions <-> corn** (`correlates_with`, expected 580.5, observed 0): "Higher crop condition ratings (e.g. FranceAgriMer/MARS) imply better yields and pressure price as the season progresses...."
- **corn <-> raw_sugar** (`competes_with`, expected 450.9, observed 2): "In Brazil, corn ethanol expansion can substitute for cane ethanol at the margin, freeing cane for sugar; conversely high corn prices favor cane ethanol, indirectly linking sugar mix decisions to corn economics...."
- **wheat <-> yellow_maize** (`substitutes_for`, expected 369.4, observed 0): "Cheap feed wheat substitutes for yellow maize in SA poultry/feedlot rations when the wheat-maize spread compresses, easing maize feed demand...."
- **wheat <-> white_maize** (`substitutes_for`, expected 363.4, observed 0): "Cheap feed wheat substitutes for yellow maize in livestock rations, indirectly easing maize demand and the white-yellow premium when wheat is price-competitive...."
- **subsidy <-> wasde_stocks_to_use** (`causes`, expected 358.8, observed 2): "A higher global sugar stocks-to-use ratio signals an ample balance-sheet cushion, dampening price; tightening S/U is bullish for the #5...."
- **corn <-> hrw_wheat** (`competes_with`, expected 340.1, observed 2): "Wheat and corn compete for feed-ration demand; higher corn prices pull feed wheat demand and lift the wheat-corn spread floor, supporting HRW...."

The pattern is consistent: the highest-surprise dark edges are **deliberately-authored two-hop mechanisms** (palm -> soyoil -> oil share of crush -> meal; corn ethanol -> cane freed for sugar). A single-sentence corpus will never state those. That is a limitation of the TEST, and it is the reason this list is a review queue rather than a delete list.

### Dark at BOTH levels (25 pairs) -- endpoints never share a document

The stronger claim. Note every one has a small `expected`, so none of these is statistically surprising on its own -- they are thin-endpoint edges (JSE maize, orange juice, HRS wheat) more than wrong ones.

| node A | node B | same-chunk | same-doc | expected | DAG rows | edge type | in DAGs |
|---|---|---|---|---|---|---|---|
| import_tariff | yellow_maize | 0 | 0 | 23.4 | 1 | restricts | south_african_yellow_maize_jse |
| import_tariff | white_maize | 0 | 0 | 23 | 1 | restricts | south_african_white_maize_jse |
| fertilizer | yellow_maize | 0 | 0 | 4.9 | 1 | causes | south_african_yellow_maize_jse |
| hrs_wheat | leaf_rust | 0 | 0 | 2.8 | 1 | affects_yield_of | hard_red_spring_wheat_mgex |
| frost | yellow_maize | 0 | 0 | 2.4 | 1 | affects_yield_of | south_african_yellow_maize_jse |
| former_ussr_import_demand | yellow_maize | 0 | 0 | 2 | 1 | causes | south_african_yellow_maize_jse |
| el_nino | white_maize | 0 | 0 | 1.9 | 1 | teleconnects_to | south_african_white_maize_jse |
| el_nino | yellow_maize | 0 | 0 | 1.9 | 1 | teleconnects_to | south_african_yellow_maize_jse |
| panamax_freight | white_maize | 0 | 0 | 1.6 | 1 | disrupts | south_african_white_maize_jse |
| panamax_freight | yellow_maize | 0 | 0 | 1.6 | 1 | disrupts | south_african_yellow_maize_jse |
| la_nina | white_maize | 0 | 0 | 1.1 | 1 | teleconnects_to | south_african_white_maize_jse |
| la_nina | yellow_maize | 0 | 0 | 1.1 | 1 | teleconnects_to | south_african_yellow_maize_jse |
| natural_gas | yellow_maize | 0 | 0 | 1 | 1 | causes | south_african_yellow_maize_jse |
| eu_crop_and_policy | white_sugar | 0 | 0 | 0.6 | 1 | produces | white_sugar |
| white_maize | zar_fx | 0 | 0 | 0.5 | 1 | causes | south_african_white_maize_jse |

### Unmeasurable (327 pairs)

At least one endpoint falls below the 100-mention floor. This is the single largest bucket -- **32% of all DAG pairs cannot be judged by this corpus at all.** Top 10 by how many DAG rows ride on them:

| node A | node B | same-chunk | same-doc | expected | DAG rows | edge type | in DAGs |
|---|---|---|---|---|---|---|---|
| flowering_stress | heat_stress | 0 | 0 | 0 | 15 | amplifies, causes | 14 DAGs |
| drought | flowering_stress | 0 | 0 | 0 | 13 | causes | 12 DAGs |
| cftc_positioning | wasde_stocks_to_use | 0 | 2 | 0.1 | 13 | amplifies, causes | 9 DAGs |
| drought | managed_money_positioning | 0 | 0 | 0 | 12 | amplifies, causes | 6 DAGs |
| cftc_positioning | tenderable_collapse | 0 | 0 | 0 | 11 | amplifies, causes | 8 DAGs |
| drought | iod_positive | 0 | 0 | 0 | 10 | causes | 9 DAGs |
| panamax_freight | port_closure | 0 | 0 | 0 | 9 | amplifies, causes | 8 DAGs |
| export_pace_lag | port_closure | 0 | 0 | 0 | 8 | amplifies, causes | 6 DAGs |
| export_pace_lag | withheld_supply | 0 | 0 | 0 | 8 | amplifies, causes | 7 DAGs |
| rin_credits | us_ethanol_rfs | 18 | 7 | 0 | 8 | amplifies, causes | 4 DAGs |

## (c) Structural findings that fall out of the same measurement

### 44 entities carry ZERO DAG edges despite real corpus presence

These are not "weak edges" -- they have no edge at all, in any of the 33 DAGs, in either direction. Sorted by corpus mentions.

| entity | kind | corpus mentions | in docs | strongest corpus partner | co-mentions |
|---|---|---|---|---|---|
| grains | commodity_group | 31,015 | 1,396 | united_states | 6,132 |
| minor_cereals | commodity | 13,011 | 851 | united_states | 3,938 |
| oilseeds | commodity_group | 12,857 | 885 | united_states | 3,458 |
| fresh_citrus | commodity | 12,814 | 201 | argentina | 1,841 |
| peanut | commodity | 11,720 | 1,000 | china | 1,823 |
| vegetable_oils | commodity_group | 11,083 | 550 | united_states | 3,399 |
| sunflower | commodity | 9,652 | 1,042 | sunflower_oil_balance | 4,659 |
| feed_grains | commodity_group | 8,188 | 386 | united_states | 1,531 |
| coconut | commodity | 6,834 | 336 | philippines | 1,680 |
| pulses | commodity | 5,430 | 745 | south_africa | 1,217 |
| palm_kernel | commodity | 4,238 | 352 | indonesia | 950 |
| cottonseed | commodity | 4,138 | 549 | china | 702 |
| marine_protein_fishmeal | substitution | 2,609 | 228 | fish_meal | 2,604 |
| fish_meal | commodity | 2,604 | 228 | marine_protein_fishmeal | 2,604 |
| thb_fx | macro | 2,488 | 207 | thailand | 1,903 |
| hfcs | commodity | 2,023 | 301 | mexico | 1,428 |
| import_quota_trq | policy | 1,826 | 550 | import_tariff | 951 |
| quota | policy_event | 1,793 | 686 | import_tariff | 533 |
| biodiesel | commodity | 1,761 | 419 | biodiesel_mandate | 1,736 |
| ddgs | commodity | 1,311 | 288 | ethanol_margins | 1,238 |
| ideal_conditions | beneficial_weather | 1,218 | 815 | favorable_rainfall | 1,218 |
| metals | macro_context | 1,091 | 148 | aluminium | 364 |
| minor_oilseeds | commodity | 894 | 248 | china | 328 |
| olive_oil | commodity | 865 | 73 | australia | 306 |
| export_levy_duty | policy | 804 | 296 | levy | 510 |
| levy | policy_event | 510 | 189 | export_levy_duty | 510 |
| steel | metal | 505 | 103 | japan | 117 |
| rub_fx | macro | 476 | 57 | russia | 223 |
| copper | metal | 417 | 118 | metals | 336 |
| php_fx | macro | 372 | 46 | philippines | 145 |
| aluminium | metal | 364 | 115 | metals | 364 |
| try_fx | macro | 227 | 63 | turkey | 83 |
| mxn_fx | macro | 202 | 47 | mexico | 86 |
| nickel | metal | 184 | 101 | metals | 184 |
| aud_fx | macro | 171 | 67 | cotton | 20 |
| uah_fx | macro | 151 | 30 | ukraine | 90 |
| iron_ore | metal | 150 | 99 | metals | 150 |
| food_grains | commodity_group | 149 | 62 | india | 79 |
| adequate_moisture | beneficial_weather | 143 | 106 | wheat | 33 |
| zinc | metal | 136 | 91 | metals | 136 |
| used_cooking_oil | commodity | 132 | 29 | biodiesel_mandate | 31 |
| dap | fertilizer | 132 | 88 | fertilizer | 12 |
| tallow | commodity | 131 | 72 | biodiesel_mandate | 25 |
| oilseed_meals | commodity_group | 103 | 51 | vietnam | 35 |

The ones that matter most, ranked by the corpus mass sitting behind a node with no edge at all:

- **`grains`** (commodity_group) -- 31,015 mentions across 1,396 documents, DAG degree 0. Its strongest corpus partner is `united_states` at 6,132 same-chunk co-mentions.
- **`minor_cereals`** (commodity) -- 13,011 mentions across 851 documents, DAG degree 0. Its strongest corpus partner is `united_states` at 3,938 same-chunk co-mentions.
- **`oilseeds`** (commodity_group) -- 12,857 mentions across 885 documents, DAG degree 0. Its strongest corpus partner is `united_states` at 3,458 same-chunk co-mentions.
- **`fresh_citrus`** (commodity) -- 12,814 mentions across 201 documents, DAG degree 0. Its strongest corpus partner is `argentina` at 1,841 same-chunk co-mentions.
- **`peanut`** (commodity) -- 11,720 mentions across 1,000 documents, DAG degree 0. Its strongest corpus partner is `china` at 1,823 same-chunk co-mentions.
- **`vegetable_oils`** (commodity_group) -- 11,083 mentions across 550 documents, DAG degree 0. Its strongest corpus partner is `united_states` at 3,399 same-chunk co-mentions.

See `data/dec_p1/edge_adjudication.md` for the verdict on each named edge -- this table is the evidence, not the decision.

### The corpus names the parent concept; the DAGs hang edges off the class nodes

| commodity node | DAG degree | corpus mentions |
|---|---|---|
| wheat | 7 | 186,276 |
| corn | 63 | 137,537 |
| cotton | 26 | 129,009 |
| soybeans | 59 | 100,885 |
| rice | 25 | 99,522 |
| soybean_oil | 36 | 39,070 |
| soybean_meal | 42 | 37,883 |
| grains | 0 | 31,015 |
| barley | 1 | 25,351 |
| sorghum | 2 | 20,811 |
| palm_oil | 37 | 13,048 |
| minor_cereals | 0 | 13,011 |
| arabica_coffee | 30 | 12,960 |
| oilseeds | 0 | 12,857 |
| fresh_citrus | 0 | 12,814 |
| peanut | 0 | 11,720 |

`wheat` carries 7 DAG pairs on 186,276 mentions, while its class members carry `srw_wheat` 34 pairs on 1,277 mentions; `hrw_wheat` 31 pairs on 3,431 mentions; `hrs_wheat` 30 pairs on 4,242 mentions. This is by DESIGN -- `commodity_hierarchy.yaml` makes `wheat` the un-expanded concept and expands it to class members -- but it is also the single biggest reason this audit cannot measure the wheat complex: the text says "wheat", the edges say "srw_wheat".

### Thin endpoints that block measurement

These entities are each below the 100-mention floor and between them make 327 DAG pairs unjudgeable. Top 15:

| entity | kind | corpus mentions | DAG pairs made unmeasurable | has surface forms |
|---|---|---|---|---|
| export_pace_lag | state_marker | 0 | 33 | True |
| us_dollar_index | fx_macro | 52 | 24 | True |
| tenderable_collapse | state_marker | 0 | 23 | True |
| cftc_positioning | positioning | 2 | 22 | True |
| iod_positive | climate_driver | 0 | 22 | True |
| black_sea_corridor | logistics_chokepoint | 69 | 19 | True |
| flowering_stress | state_marker | 0 | 17 | True |
| withheld_supply | cash_market | 30 | 17 | True |
| managed_money_positioning | speculative_positioning | 0 | 16 | True |
| soybean_crush_margin | instrument | 2 | 15 | True |
| china_crush_demand | demand_center | 2 | 14 | True |
| port_closure | policy_event | 1 | 10 | True |
| replanting_cycle | state_marker | 0 | 10 | True |
| iod_negative | climate_driver | 0 | 9 | True |
| sugar_ethanol_parity | instrument | 77 | 8 | True |

This independently confirms the CONTENT DEBT note already written into `driver_slices.yaml`: `managed_money_positioning` (0 corpus mentions, blocks 14 pairs) and `cftc_positioning` (blocks 22) are named there as slices reachable from 11 and 20 contracts while holding zero and one props respectively. The state_marker family -- `export_pace_lag` (31 pairs), `tenderable_collapse` (23), `withheld_supply` (17), `flowering_stress` (17), `replanting_cycle` (10) -- is the other half: these are minted concepts with no corpus surface form at all.

## Best-supported existing edges (positive control)

The audit is not systematically blind: the top-supported edges are the ones a desk would name first.

| node A | node B | same-chunk | same-doc | expected | DAG rows | edge type | in DAGs |
|---|---|---|---|---|---|---|---|
| cotton | wasde_stocks_to_use | 12716 | 929 | 9468.6 | 1 | causes | 1 DAGs |
| corn | wasde_stocks_to_use | 12433 | 1383 | 10094.5 | 4 | causes | 4 DAGs |
| cotton | textile_apparel_demand | 9907 | 728 | 1419.6 | 2 | causes, restricts | 1 DAGs |
| rice | wasde_stocks_to_use | 9091 | 1139 | 7304.4 | 1 | causes | 1 DAGs |
| broiler_economics | livestock_feed_demand | 8844 | 649 | 139.9 | 1 | causes | 1 DAGs |
| soybeans | wasde_stocks_to_use | 8531 | 1062 | 7404.5 | 5 | causes | 4 DAGs |
| white_raw_premium | white_sugar | 3654 | 495 | 13.4 | 1 | causes | 1 DAGs |
| soybean_oil | wasde_stocks_to_use | 3111 | 734 | 2867.5 | 2 | causes | 2 DAGs |
| soybean_meal | wasde_stocks_to_use | 2194 | 794 | 2780.4 | 2 | causes | 2 DAGs |
| protein_meal_substitution | rapeseed_meal | 1949 | 250 | 5.8 | 2 | correlates_with, substitutes_f | 1 DAGs |
| corn | wheat | 1831 | 2050 | 18462.1 | 4 | substitutes_for | 4 DAGs |
| corn | soybeans | 1673 | 1867 | 9998.9 | 7 | competes_with | 7 DAGs |
| corn | wheat_corn_spread | 1492 | 1504 | 2253.8 | 4 | substitutes_for | 4 DAGs |
| cotton | cotton_polyester_competition | 1426 | 505 | 144.1 | 2 | causes, substitutes_for | 1 DAGs |
| arabica_coffee | robusta_coffee | 1424 | 492 | 67.2 | 3 | substitutes_for | 3 DAGs |

## Corpus coverage by commodity slice

| slice | chunks with >=1 vocab hit |
|---|---|

## Gaps and caveats

1. **pg was unreachable** (VPC-internal); the flat S3 slices carry the same props, so this is a route change, not a data change.
2. **Sentence-scale co-mention.** Mean chunk is 97.4 chars. Any mechanism that spans two sentences is invisible at prop level; the document level is reported alongside for exactly this reason.
3. **327 of 1008 pairs are unmeasurable** and **108 DAG driver ids have no surface form**, all already waivered. Roughly half the DAG cannot be audited from text until those endpoints get surface forms.
4. **Co-mention is not causation.** A high-lift pair (import_tariff x quota) can just be two words that live in the same policy sentence.
5. **51 degenerate pairs** share a surface form; excluded from new candidates, flagged elsewhere. Nested forms (e.g. "feed wheat" inside a wheat_corn_spread term list) are flagged, not dropped.
6. **Directionality and sign were not tested.** Co-mention is symmetric; nothing here says which way an edge points or whether the authored sign is right.
