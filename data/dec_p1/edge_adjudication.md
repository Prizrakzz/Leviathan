# Edge adjudication (dec_p1, post-X2 corpus) -- 2026-08-21T13:36:18Z

Artifact: `data/dec_p1/edge_adjudication.json`. Corpus judged: 5,936 chunk objects / 663,410,438 bytes, newest object 2026-08-21T09:25:37+00:00; 1,387,697 unique props.

**The question.** for every edge the plan's F-A itemization names and every one of graph_walk's 130 structural candidates: AUTHOR, AUTHOR-ON-STRUCTURE, REFUSE, or WAIVE-UNMEASURABLE -- by one rule written down before the numbers were read

**The rule, fixed before the numbers were read.** Precedence: `WAIVE-UNMEASURABLE` (either endpoint < 100 mentions, or not in the vocabulary -- a verdict about the instrument) -> `REFUSE` (>=60 co-mentions but lift < 1.0 AND npmi <= 0, i.e. together LESS than chance) -> `AUTHOR` (>=60 co-mentions, npmi > 0 or lift > 1.5, no shared surface form) -> `AUTHOR-ON-STRUCTURE` (corpus-silent but a declared complex member with slice Jaccard >= 0.50 -- the physical-identity class a zero must not veto) -> `REFUSE-INSUFFICIENT`.

| verdict | F-A named | structural | total |
|---|---:|---:|---:|
| AUTHOR | 13 | 2 | 15 |
| AUTHOR-ON-STRUCTURE | 2 | 2 | 4 |
| REFUSE | 9 | 1 | 10 |
| REFUSE-INSUFFICIENT | 11 | 125 | 136 |
| WAIVE-UNMEASURABLE | 13 | 0 | 13 |

## The one unconfounded X2 measurement

THE ONE UNCONFOUNDED X2 MEASUREMENT. The same endpoint pairs, the same rule, two corpora. Every other delta in this wave is contaminated by the 29 entities that entered the vocabulary since DEC-P0; this one is not, because the pair set is held fixed to what BOTH vintages declare. It is also a LOWER BOUND: the pre-X2 side still includes the stale _raw/ leg that this run drops.

Re-classifying the **979 endpoint pairs both config vintages declare** under the same rule (floor 100, zero band 2) against the pre-X2 and post-X2 corpora: **125 improved, 4 regressed, 850 unchanged.**

| transition | n |
|---|---:|
| `unmeasurable -> unmeasurable` | 320 |
| `supported -> supported` | 306 |
| `dark_in_prop_text_only -> dark_in_prop_text_only` | 209 |
| `dark_in_prop_text_only -> supported` | 53 |
| `unmeasurable -> dark_in_prop_text_only` | 36 |
| `unmeasurable -> supported` | 22 |
| `dark_at_both_levels -> dark_at_both_levels` | 15 |
| `dark_at_both_levels -> dark_in_prop_text_only` | 8 |
| `unmeasurable -> dark_at_both_levels` | 6 |
| `supported -> dark_in_prop_text_only` | 4 |

Regressions (all of them):

- `cocoa ~ flood` supported -> dark_in_prop_text_only (3 -> 1 props)
- `crude_oil ~ robusta_coffee` supported -> dark_in_prop_text_only (4 -> 1 props)
- `drought ~ export_ban` supported -> dark_in_prop_text_only (3 -> 2 props)
- `drought ~ soybean_oil` supported -> dark_in_prop_text_only (4 -> 2 props)

## What the corpus doubling actually fed

29 entities entered the vocabulary between DEC-P0 and this run (coconut, palm_kernel, hfcs, fresh_citrus, ddgs, tallow, used_cooking_oil, cottonseed, peanut, the fx family, ...). A DEC-P0 count of 0 on any of them means THE ENTITY HAD NO SURFACE FORMS, not that the text was silent. Those deltas are labelled `vocabulary` and say nothing about the corpus doubling; only `corpus`-labelled rows are evidence about X2. DEC-P0's N (396,693) also included the stale _raw/ leg this run drops, so raw counts are not subtractable -- lift and npmi are the comparable quantities.

**Corpus-attributable movement** (both endpoints were measurable at DEC-P0, so the delta is the corpus and nothing else) -- top 15 by absolute gain:

| pair | DEC-P0 prop | now | DEC-P0 lift | now lift | verdict |
|---|---:|---:|---:|---:|---|
| `barley ~ wheat` | 903 | 1338 | 0.72 | 0.39 | REFUSE |
| `corn ~ sorghum` | 548 | 977 | 0.99 | 0.47 | REFUSE |
| `barley ~ corn` | 528 | 954 | 0.55 | 0.38 | REFUSE |
| `corn ~ ethanol` | 401 | 820 | 2.66 | 1.91 | AUTHOR |
| `corn ~ livestock_feed_demand` | 578 | 914 | 1.64 | 0.42 | REFUSE |
| `cotton ~ rice` | 172 | 300 | 0.1 | 0.03 | REFUSE |
| `palm_oil ~ palm_olein` | 27 | 132 | 11.88 | 32.27 | AUTHOR |
| `palm_oil ~ sunflower_oil` | 58 | 111 | 1.6 | 4.74 | AUTHOR |
| `soybean_oil ~ sunflower_oil` | 37 | 69 | 1.09 | 0.98 | REFUSE |
| `hrw_wheat ~ srw_wheat` | 11 | 34 | 109.93 | 10.77 | REFUSE-INSUFFICIENT |
| `rapeseed_oil ~ soybean_oil` | 92 | 114 | 2.53 | 2.02 | AUTHOR |
| `protein_meal_substitution ~ soybean_meal` | 193 | 215 | 2.17 | 1.9 | AUTHOR |
| `livestock_feed_demand ~ soybean_meal` | 402 | 420 | 3.67 | 0.7 | REFUSE |
| `canola ~ rapeseed` | 185 | 203 | 2.43 | 6.61 | AUTHOR |
| `corn ~ rapeseed` | 26 | 41 | 0.06 | 0.06 | REFUSE-INSUFFICIENT |

**Vocabulary-attributable** (the entity did not exist at DEC-P0 -- these are NOT X2 results, they are the 29 new vocabulary entities becoming measurable at all):

| pair | now prop | now lift | new endpoint(s) | verdict |
|---|---:|---:|---|---|
| `corn ~ hfcs` | 469 | 2.34 | hfcs | AUTHOR |
| `peanut ~ soybeans` | 321 | 0.38 | peanut | REFUSE |
| `cotton ~ cottonseed` | 273 | 0.71 | cottonseed | REFUSE |
| `palm_kernel ~ palm_oil` | 194 | 4.87 | palm_kernel | AUTHOR |
| `coconut ~ palm_kernel` | 147 | 7.04 | coconut, palm_kernel | AUTHOR |
| `ddgs ~ soybean_meal` | 113 | 3.16 | ddgs | AUTHOR |
| `cotton ~ peanut` | 95 | 0.09 | peanut | REFUSE |
| `fresh_citrus ~ orange_juice` | 76 | 3.25 | fresh_citrus | AUTHOR |
| `ddgs ~ ethanol` | 62 | 15.12 | ddgs | AUTHOR |

**Rows measured through a surface fold** -- the name asked for has no entity of its own, so the row measures a broader entity. Read these with that in mind:

- asked `sunflower_meal ~ soybean_meal`, measured `protein_meal_substitution ~ soybean_meal` ({"a": "surface_fold", "b": "exact"})

## Near misses -- below the floor, strongly associated

Disclosure, not a rule change: the >=60 floor is the INSTRUMENT's, not a fact about these pairs. Each keeps its `REFUSE-INSUFFICIENT` verdict; they are surfaced because they are where a curator should look first.

| pair | prop | expected | lift | npmi | doc | verdict |
|---|---:|---:|---:|---:|---:|---|
| `hrw_wheat ~ srw_wheat` | 34 | 3.2 | 10.77 | 0.224 | 174 | REFUSE-INSUFFICIENT |
| `rapeseed ~ rapeseed_oil` | 58 | 10.1 | 5.73 | 0.173 | 238 | REFUSE-INSUFFICIENT |
| `hfcs ~ raw_sugar` | 37 | 6.6 | 5.58 | 0.163 | 146 | REFUSE-INSUFFICIENT |
| `rapeseed ~ rapeseed_meal` | 53 | 9.8 | 5.39 | 0.166 | 222 | REFUSE-INSUFFICIENT |
| `ddgs ~ livestock_feed_demand` | 53 | 20.7 | 2.56 | 0.092 | 237 | REFUSE-INSUFFICIENT |

## Part 1 -- the F-A named edges

| item | edge | verdict | prop | doc | lift | npmi | a_mentions | b_mentions | Jaccard |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| A | `cattle_cycle_herd_size ~ cattle_beef` | WAIVE-UNMEASURABLE | - | - | - | - | - | - | - |
| A | `cattle_beef ~ broilers_poultry` | WAIVE-UNMEASURABLE | - | - | - | - | - | - | - |
| A | `broilers_poultry ~ livestock_feed_demand` | WAIVE-UNMEASURABLE | - | - | - | - | - | - | - |
| A | `livestock_feed_demand ~ soybean_meal` | REFUSE | 420 | 875 | 0.7 | -0.044 | 21944 | 37883 | None |
| A | `corn ~ livestock_feed_demand` | REFUSE | 914 | 1278 | 0.42 | -0.118 | 137537 | 21944 | None |
| A | `ddgs ~ livestock_feed_demand` | REFUSE-INSUFFICIENT | 53 | 237 | 2.56 | 0.092 | 1311 | 21944 | None |
| A | `dairy ~ livestock_feed_demand` | WAIVE-UNMEASURABLE | - | - | - | - | - | - | - |
| B | `coconut ~ palm_kernel` | AUTHOR | 147 | 169 | 7.04 | 0.213 | 6834 | 4238 | None |
| B | `palm_kernel ~ palm_oil` | AUTHOR | 194 | 326 | 4.87 | 0.178 | 4238 | 13048 | None |
| B | `coconut_oil ~ palm_kernel_oil` | WAIVE-UNMEASURABLE | - | - | - | - | - | - | - |
| C | `cotton ~ cottonseed` | REFUSE | 273 | 467 | 0.71 | -0.04 | 129009 | 4138 | None |
| C | `cottonseed_meal ~ soybean_meal` | WAIVE-UNMEASURABLE | - | - | - | - | - | - | - |
| C | `cottonseed_oil ~ soybean_oil` | WAIVE-UNMEASURABLE | - | - | - | - | - | - | - |
| D | `peanut ~ soybeans` | REFUSE | 321 | 948 | 0.38 | -0.117 | 11720 | 100885 | None |
| D | `cotton ~ peanut` | REFUSE | 95 | 411 | 0.09 | -0.254 | 129009 | 11720 | None |
| D | `peanut_oil ~ soybean_oil` | WAIVE-UNMEASURABLE | - | - | - | - | - | - | - |
| E | `rapeseed ~ rapeseed_oil` | REFUSE-INSUFFICIENT | 58 | 238 | 5.73 | 0.173 | 7000 | 2006 | 0.484 |
| E | `rapeseed ~ rapeseed_meal` | REFUSE-INSUFFICIENT | 53 | 222 | 5.39 | 0.166 | 7000 | 1949 | 0.294 |
| E | `canola ~ rapeseed` | AUTHOR | 203 | 152 | 6.61 | 0.214 | 6091 | 7000 | 0.677 |
| E | `rapeseed_meal ~ soybean_meal` | AUTHOR | 96 | 242 | 1.8 | 0.062 | 1949 | 37883 | None |
| E | `rapeseed_oil ~ soybean_oil` | AUTHOR | 114 | 256 | 2.02 | 0.075 | 2006 | 39070 | None |
| F | `french_wheat ~ hrw_wheat` | AUTHOR-ON-STRUCTURE | 3 | 71 | 0.81 | -0.016 | 1496 | 3431 | 0.679 |
| F | `french_wheat ~ hrs_wheat` | AUTHOR-ON-STRUCTURE | 1 | 114 | 0.22 | -0.107 | 1496 | 4242 | 0.692 |
| F | `hrs_wheat ~ hrw_wheat` | REFUSE-INSUFFICIENT | 21 | 301 | 2.0 | 0.063 | 4242 | 3431 | None |
| F | `hrw_wheat ~ srw_wheat` | REFUSE-INSUFFICIENT | 34 | 174 | 10.77 | 0.224 | 3431 | 1277 | None |
| F | `hrs_wheat ~ srw_wheat` | REFUSE-INSUFFICIENT | 13 | 144 | 3.33 | 0.104 | 4242 | 1277 | None |
| G | `corn ~ ethanol` | AUTHOR | 820 | 583 | 1.91 | 0.087 | 137537 | 4341 | None |
| G | `ddgs ~ ethanol` | AUTHOR | 62 | 101 | 15.12 | 0.271 | 1311 | 4341 | None |
| H | `soybean_oil ~ used_cooking_oil` | REFUSE-INSUFFICIENT | 8 | 24 | 2.15 | 0.064 | 39070 | 132 | None |
| H | `soybean_oil ~ tallow` | REFUSE-INSUFFICIENT | 19 | 54 | 5.15 | 0.146 | 39070 | 131 | None |
| H | `tallow ~ used_cooking_oil` | REFUSE-INSUFFICIENT | 11 | 9 | 882.76 | 0.578 | 131 | 132 | None |
| I | `corn ~ hfcs` | AUTHOR | 469 | 280 | 2.34 | 0.106 | 137537 | 2023 | None |
| I | `hfcs ~ raw_sugar` | REFUSE-INSUFFICIENT | 37 | 146 | 5.58 | 0.163 | 2023 | 4549 | None |
| I | `hfcs ~ white_sugar` | REFUSE-INSUFFICIENT | 13 | 147 | 1.75 | 0.048 | 2023 | 5094 | None |
| J | `fresh_citrus ~ orange_juice` | AUTHOR | 76 | 139 | 3.25 | 0.12 | 12814 | 2534 | None |
| K | `rapeseed_meal ~ soybean_meal` | AUTHOR | 96 | 242 | 1.8 | 0.062 | 1949 | 37883 | None |
| K | `cottonseed_meal ~ soybean_meal` | WAIVE-UNMEASURABLE | - | - | - | - | - | - | - |
| K | `peanut_meal ~ soybean_meal` | WAIVE-UNMEASURABLE | - | - | - | - | - | - | - |
| K | `protein_meal_substitution ~ soybean_meal` | AUTHOR | 215 | 361 | 1.9 | 0.073 | 4156 | 37883 | None |
| K | `palm_kernel_meal ~ soybean_meal` | WAIVE-UNMEASURABLE | - | - | - | - | - | - | - |
| K | `ddgs ~ soybean_meal` | AUTHOR | 113 | 155 | 3.16 | 0.122 | 1311 | 37883 | None |
| K | `flaxseed_meal ~ soybean_meal` | WAIVE-UNMEASURABLE | - | - | - | - | - | - | - |
| K | `sesame_meal ~ soybean_meal` | WAIVE-UNMEASURABLE | - | - | - | - | - | - | - |
| L | `barley ~ wheat` | REFUSE | 1338 | 1435 | 0.39 | -0.134 | 25351 | 186276 | None |
| L | `corn ~ sorghum` | REFUSE | 977 | 1241 | 0.47 | -0.103 | 137537 | 20811 | None |
| L | `barley ~ corn` | REFUSE | 954 | 1235 | 0.38 | -0.133 | 25351 | 137537 | None |
| L | `soybean_oil ~ sunflower_oil` | REFUSE | 69 | 278 | 0.98 | -0.002 | 39070 | 2492 | None |
| L | `palm_oil ~ sunflower_oil` | AUTHOR | 111 | 220 | 4.74 | 0.165 | 13048 | 2492 | None |

### A. livestock demand layer

- **`cattle_cycle_herd_size ~ cattle_beef`** -- WAIVE-UNMEASURABLE. endpoint not in the vocabulary at all (cattle_beef) -- the node must be authored before any edge on it can be measured; this is a verdict about the instrument
- **`cattle_beef ~ broilers_poultry`** -- WAIVE-UNMEASURABLE. endpoint not in the vocabulary at all (cattle_beef, broilers_poultry) -- the node must be authored before any edge on it can be measured; this is a verdict about the instrument
- **`broilers_poultry ~ livestock_feed_demand`** -- WAIVE-UNMEASURABLE. endpoint not in the vocabulary at all (broilers_poultry) -- the node must be authored before any edge on it can be measured; this is a verdict about the instrument
- **`livestock_feed_demand ~ soybean_meal`** -- REFUSE. co-mentioned 420 times but lift 0.70 / npmi -0.044 -- the two appear together LESS than chance. That is an argument about what the edge would mean, not a licence.  _(already edged in the DAGs)_
- **`corn ~ livestock_feed_demand`** -- REFUSE. co-mentioned 914 times but lift 0.42 / npmi -0.118 -- the two appear together LESS than chance. That is an argument about what the edge would mean, not a licence.  _(already edged in the DAGs)_
- **`ddgs ~ livestock_feed_demand`** -- REFUSE-INSUFFICIENT. measurable (min endpoint 1311 mentions) but only 53 prop co-mentions -- below the >=60 author floor, and no complex/identity claim to stand on (Jaccard 0.000).
- **`dairy ~ livestock_feed_demand`** -- WAIVE-UNMEASURABLE. endpoint not in the vocabulary at all (dairy) -- the node must be authored before any edge on it can be measured; this is a verdict about the instrument

### B. lauric complex

- **`coconut ~ palm_kernel`** -- AUTHOR. 147 prop co-mentions (169 doc), lift 7.04, npmi 0.213 -- clears the >=60 floor with positive association and no shared surface form.
- **`palm_kernel ~ palm_oil`** -- AUTHOR. 194 prop co-mentions (326 doc), lift 4.87, npmi 0.178 -- clears the >=60 floor with positive association and no shared surface form.
- **`coconut_oil ~ palm_kernel_oil`** -- WAIVE-UNMEASURABLE. endpoint not in the vocabulary at all (coconut_oil, palm_kernel_oil) -- the node must be authored before any edge on it can be measured; this is a verdict about the instrument

### C. cotton crush

- **`cotton ~ cottonseed`** -- REFUSE. co-mentioned 273 times but lift 0.71 / npmi -0.040 -- the two appear together LESS than chance. That is an argument about what the edge would mean, not a licence.
- **`cottonseed_meal ~ soybean_meal`** -- WAIVE-UNMEASURABLE. endpoint not in the vocabulary at all (cottonseed_meal) -- the node must be authored before any edge on it can be measured; this is a verdict about the instrument
- **`cottonseed_oil ~ soybean_oil`** -- WAIVE-UNMEASURABLE. endpoint not in the vocabulary at all (cottonseed_oil) -- the node must be authored before any edge on it can be measured; this is a verdict about the instrument

### D. peanut complex

- **`peanut ~ soybeans`** -- REFUSE. co-mentioned 321 times but lift 0.38 / npmi -0.117 -- the two appear together LESS than chance. That is an argument about what the edge would mean, not a licence.
- **`cotton ~ peanut`** -- REFUSE. co-mentioned 95 times but lift 0.09 / npmi -0.254 -- the two appear together LESS than chance. That is an argument about what the edge would mean, not a licence.
- **`peanut_oil ~ soybean_oil`** -- WAIVE-UNMEASURABLE. endpoint not in the vocabulary at all (peanut_oil) -- the node must be authored before any edge on it can be measured; this is a verdict about the instrument

### E. rapeseed crush chain

- **`rapeseed ~ rapeseed_oil`** -- REFUSE-INSUFFICIENT. measurable (min endpoint 2006 mentions) but only 58 prop co-mentions -- below the >=60 author floor, and no complex/identity claim to stand on (Jaccard 0.484).
- **`rapeseed ~ rapeseed_meal`** -- REFUSE-INSUFFICIENT. measurable (min endpoint 1949 mentions) but only 53 prop co-mentions -- below the >=60 author floor, and no complex/identity claim to stand on (Jaccard 0.294).
- **`canola ~ rapeseed`** -- AUTHOR. 203 prop co-mentions (152 doc), lift 6.61, npmi 0.214 -- clears the >=60 floor with positive association and no shared surface form.
- **`rapeseed_meal ~ soybean_meal`** -- AUTHOR. 96 prop co-mentions (242 doc), lift 1.8, npmi 0.062 -- clears the >=60 floor with positive association and no shared surface form.  _(already edged in the DAGs)_
- **`rapeseed_oil ~ soybean_oil`** -- AUTHOR. 114 prop co-mentions (256 doc), lift 2.02, npmi 0.075 -- clears the >=60 floor with positive association and no shared surface form.  _(already edged in the DAGs)_

### F. wheat class spreads

- **`french_wheat ~ hrw_wheat`** -- AUTHOR-ON-STRUCTURE. corpus reads 3 prop co-mentions, but the pair is a declared complex member (complex:wheat, group:food_grains, group:grains) with slice Jaccard 0.679 -- a physical-identity / same-complex relationship the text never states in one sentence. The zero must not veto it; the reason belongs in the edge's mechanism text.
- **`french_wheat ~ hrs_wheat`** -- AUTHOR-ON-STRUCTURE. corpus reads 1 prop co-mentions, but the pair is a declared complex member (complex:wheat, group:food_grains, group:grains) with slice Jaccard 0.692 -- a physical-identity / same-complex relationship the text never states in one sentence. The zero must not veto it; the reason belongs in the edge's mechanism text.
- **`hrs_wheat ~ hrw_wheat`** -- REFUSE-INSUFFICIENT. measurable (min endpoint 3431 mentions) but only 21 prop co-mentions -- below the >=60 author floor, and no complex/identity claim to stand on (Jaccard 0.000).  _(already edged in the DAGs)_
- **`hrw_wheat ~ srw_wheat`** -- REFUSE-INSUFFICIENT. measurable (min endpoint 1277 mentions) but only 34 prop co-mentions -- below the >=60 author floor, and no complex/identity claim to stand on (Jaccard 0.000).  _(already edged in the DAGs)_
- **`hrs_wheat ~ srw_wheat`** -- REFUSE-INSUFFICIENT. measurable (min endpoint 1277 mentions) but only 13 prop co-mentions -- below the >=60 author floor, and no complex/identity claim to stand on (Jaccard 0.000).  _(already edged in the DAGs)_

### G. ethanol edges

- **`corn ~ ethanol`** -- AUTHOR. 820 prop co-mentions (583 doc), lift 1.91, npmi 0.087 -- clears the >=60 floor with positive association and no shared surface form.
- **`ddgs ~ ethanol`** -- AUTHOR. 62 prop co-mentions (101 doc), lift 15.12, npmi 0.271 -- clears the >=60 floor with positive association and no shared surface form.

### H. RD feedstock stack

- **`soybean_oil ~ used_cooking_oil`** -- REFUSE-INSUFFICIENT. measurable (min endpoint 132 mentions) but only 8 prop co-mentions -- below the >=60 author floor, and no complex/identity claim to stand on (Jaccard 0.000).
- **`soybean_oil ~ tallow`** -- REFUSE-INSUFFICIENT. measurable (min endpoint 131 mentions) but only 19 prop co-mentions -- below the >=60 author floor, and no complex/identity claim to stand on (Jaccard 0.000).
- **`tallow ~ used_cooking_oil`** -- REFUSE-INSUFFICIENT. measurable (min endpoint 131 mentions) but only 11 prop co-mentions -- below the >=60 author floor, and no complex/identity claim to stand on (Jaccard 0.000).

### I. HFCS bridge

- **`corn ~ hfcs`** -- AUTHOR. 469 prop co-mentions (280 doc), lift 2.34, npmi 0.106 -- clears the >=60 floor with positive association and no shared surface form.
- **`hfcs ~ raw_sugar`** -- REFUSE-INSUFFICIENT. measurable (min endpoint 2023 mentions) but only 37 prop co-mentions -- below the >=60 author floor, and no complex/identity claim to stand on (Jaccard 0.000).
- **`hfcs ~ white_sugar`** -- REFUSE-INSUFFICIENT. measurable (min endpoint 2023 mentions) but only 13 prop co-mentions -- below the >=60 author floor, and no complex/identity claim to stand on (Jaccard 0.000).

### J. fresh citrus diversion

- **`fresh_citrus ~ orange_juice`** -- AUTHOR. 76 prop co-mentions (139 doc), lift 3.25, npmi 0.12 -- clears the >=60 floor with positive association and no shared surface form.

### K. MARA meal basket

- **`rapeseed_meal ~ soybean_meal`** -- AUTHOR. 96 prop co-mentions (242 doc), lift 1.8, npmi 0.062 -- clears the >=60 floor with positive association and no shared surface form.  _(already edged in the DAGs)_
- **`cottonseed_meal ~ soybean_meal`** -- WAIVE-UNMEASURABLE. endpoint not in the vocabulary at all (cottonseed_meal) -- the node must be authored before any edge on it can be measured; this is a verdict about the instrument
- **`peanut_meal ~ soybean_meal`** -- WAIVE-UNMEASURABLE. endpoint not in the vocabulary at all (peanut_meal) -- the node must be authored before any edge on it can be measured; this is a verdict about the instrument
- **`protein_meal_substitution ~ soybean_meal`** -- AUTHOR. 215 prop co-mentions (361 doc), lift 1.9, npmi 0.073 -- clears the >=60 floor with positive association and no shared surface form.  _(already edged in the DAGs)_
- **`palm_kernel_meal ~ soybean_meal`** -- WAIVE-UNMEASURABLE. endpoint not in the vocabulary at all (palm_kernel_meal) -- the node must be authored before any edge on it can be measured; this is a verdict about the instrument
- **`ddgs ~ soybean_meal`** -- AUTHOR. 113 prop co-mentions (155 doc), lift 3.16, npmi 0.122 -- clears the >=60 floor with positive association and no shared surface form.
- **`flaxseed_meal ~ soybean_meal`** -- WAIVE-UNMEASURABLE. endpoint not in the vocabulary at all (flaxseed_meal) -- the node must be authored before any edge on it can be measured; this is a verdict about the instrument
- **`sesame_meal ~ soybean_meal`** -- WAIVE-UNMEASURABLE. endpoint not in the vocabulary at all (sesame_meal) -- the node must be authored before any edge on it can be measured; this is a verdict about the instrument

### L. class DAG blockers

- **`barley ~ wheat`** -- REFUSE. co-mentioned 1338 times but lift 0.39 / npmi -0.134 -- the two appear together LESS than chance. That is an argument about what the edge would mean, not a licence.
- **`corn ~ sorghum`** -- REFUSE. co-mentioned 977 times but lift 0.47 / npmi -0.103 -- the two appear together LESS than chance. That is an argument about what the edge would mean, not a licence.  _(already edged in the DAGs)_
- **`barley ~ corn`** -- REFUSE. co-mentioned 954 times but lift 0.38 / npmi -0.133 -- the two appear together LESS than chance. That is an argument about what the edge would mean, not a licence.  _(already edged in the DAGs)_
- **`soybean_oil ~ sunflower_oil`** -- REFUSE. co-mentioned 69 times but lift 0.98 / npmi -0.002 -- the two appear together LESS than chance. That is an argument about what the edge would mean, not a licence.  _(already edged in the DAGs)_
- **`palm_oil ~ sunflower_oil`** -- AUTHOR. 111 prop co-mentions (220 doc), lift 4.74, npmi 0.165 -- clears the >=60 floor with positive association and no shared surface form.  _(already edged in the DAGs)_

## Part 2 -- the 130 structural candidates, ranked by structural score

| # | pair | score | Jaccard | groups | verdict | prop | lift | npmi |
|---:|---|---:|---:|---|---|---:|---:|---:|
| 1 | `palm_oil ~ palm_olein` | 17.0 | 0.714 | complex:palm_complex, complex:veg_oil_complex | AUTHOR | 132 | 32.27 | 0.375 |
| 2 | `corn ~ palm_oil` | 16.25 | 0.255 | - | REFUSE-INSUFFICIENT | 15 | 0.01 | -0.39 |
| 3 | `french_wheat ~ hrw_wheat` | 15.75 | 0.679 | complex:wheat, group:food_grains | AUTHOR-ON-STRUCTURE | 3 | 0.81 | -0.016 |
| 4 | `french_wheat ~ hrs_wheat` | 15.5 | 0.692 | complex:wheat, group:food_grains | AUTHOR-ON-STRUCTURE | 1 | 0.22 | -0.107 |
| 5 | `rapeseed_meal ~ soybean_oil` | 15.25 | 0.393 | - | REFUSE-INSUFFICIENT | 1 | 0.02 | -0.283 |
| 6 | `rapeseed_oil ~ soybean_meal` | 14.5 | 0.3 | - | REFUSE-INSUFFICIENT | 1 | 0.02 | -0.283 |
| 7 | `canola ~ rapeseed` | 14.25 | 0.677 | complex:rapeseed_complex, group:oilseeds | AUTHOR | 203 | 6.61 | 0.214 |
| 8 | `corn ~ rapeseed_oil` | 12.5 | 0.304 | - | REFUSE-INSUFFICIENT | 3 | 0.02 | -0.321 |
| 9 | `canola ~ rapeseed_oil` | 12.25 | 0.484 | complex:rapeseed_complex | REFUSE-INSUFFICIENT | 11 | 1.25 | 0.019 |
| 10 | `palm_oil ~ rapeseed_meal` | 12.25 | 0.273 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 11 | `hrs_wheat ~ white_maize` | 11.0 | 0.4 | group:food_grains, group:grains | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 12 | `rice ~ white_maize` | 11.0 | 0.48 | group:food_grains, group:grains | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 13 | `srw_wheat ~ white_maize` | 11.0 | 0.364 | group:food_grains, group:grains | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 14 | `hrs_wheat ~ rice` | 10.75 | 0.367 | group:food_grains, group:grains | REFUSE-INSUFFICIENT | 3 | 0.01 | -0.354 |
| 15 | `rice ~ srw_wheat` | 10.75 | 0.333 | group:food_grains, group:grains | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 16 | `canola ~ soybean_meal` | 10.0 | 0.318 | - | REFUSE-INSUFFICIENT | 42 | 0.25 | -0.132 |
| 17 | `hrw_wheat ~ white_maize` | 10.0 | 0.364 | group:food_grains, group:grains | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 18 | `rapeseed ~ rapeseed_oil` | 9.75 | 0.484 | complex:rapeseed_complex | REFUSE-INSUFFICIENT | 58 | 5.73 | 0.173 |
| 19 | `french_wheat ~ white_maize` | 9.75 | 0.379 | group:food_grains, group:grains | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 20 | `hrw_wheat ~ rice` | 9.75 | 0.333 | group:food_grains, group:grains | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 21 | `french_wheat ~ rice` | 9.25 | 0.3 | group:food_grains, group:grains | REFUSE-INSUFFICIENT | 9 | 0.08 | -0.207 |
| 22 | `hrs_wheat ~ yellow_maize` | 8.5 | 0.438 | group:grains | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 23 | `srw_wheat ~ yellow_maize` | 8.5 | 0.4 | group:grains | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 24 | `rice ~ yellow_maize` | 8.25 | 0.464 | group:grains | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 25 | `cotton ~ raw_sugar` | 7.5 | 0.467 | group:soft_commodities | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 26 | `hrw_wheat ~ yellow_maize` | 7.5 | 0.4 | group:grains | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 27 | `cotton ~ white_sugar` | 7.25 | 0.406 | group:soft_commodities | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 28 | `corn ~ rapeseed` | 6.75 | 0.404 | - | REFUSE-INSUFFICIENT | 41 | 0.06 | -0.271 |
| 29 | `french_wheat ~ yellow_maize` | 6.75 | 0.333 | group:grains | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 30 | `hrw_wheat ~ soybeans` | 6.5 | 0.311 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 31 | `rapeseed ~ rapeseed_meal` | 6.5 | 0.294 | complex:rapeseed_complex | REFUSE-INSUFFICIENT | 53 | 5.39 | 0.166 |
| 32 | `arabica_coffee ~ cocoa` | 6.25 | 0.5 | group:tropicals | REFUSE-INSUFFICIENT | 2 | 0.08 | -0.19 |
| 33 | `cocoa ~ robusta_coffee` | 6.25 | 0.5 | group:tropicals | REFUSE-INSUFFICIENT | 7 | 0.49 | -0.059 |
| 34 | `rapeseed ~ soybean_meal` | 6.0 | 0.261 | - | REFUSE-INSUFFICIENT | 30 | 0.16 | -0.172 |
| 35 | `canola ~ yellow_maize` | 6.0 | 0.485 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 36 | `arabica_coffee ~ orange_juice` | 6.0 | 0.5 | group:tropicals | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 37 | `orange_juice ~ robusta_coffee` | 5.75 | 0.44 | group:tropicals | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 38 | `canola ~ white_maize` | 5.5 | 0.452 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 39 | `soybean_meal ~ yellow_maize` | 5.5 | 0.341 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 40 | `canola ~ hrs_wheat` | 5.25 | 0.361 | - | REFUSE-INSUFFICIENT | 10 | 0.54 | -0.052 |
| 41 | `canola ~ srw_wheat` | 5.25 | 0.333 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 42 | `corn ~ palm_olein` | 5.25 | 0.255 | - | REFUSE-INSUFFICIENT | 2 | 0.05 | -0.228 |
| 43 | `cotton ~ rice` | 5.25 | 0.481 | - | REFUSE | 300 | 0.03 | -0.406 |
| 44 | `cotton ~ soybean_meal` | 5.25 | 0.317 | - | REFUSE-INSUFFICIENT | 5 | 0.0 | -0.523 |
| 45 | `cotton ~ soybean_oil` | 5.25 | 0.433 | - | REFUSE-INSUFFICIENT | 3 | 0.0 | -0.544 |
| 46 | `hrs_wheat ~ soybean_meal` | 5.25 | 0.31 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 47 | `palm_olein ~ soybean_meal` | 5.25 | 0.302 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 48 | `soybean_meal ~ srw_wheat` | 5.25 | 0.289 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 49 | `cocoa ~ orange_juice` | 5.25 | 0.346 | group:tropicals | REFUSE-INSUFFICIENT | 4 | 0.79 | -0.018 |
| 50 | `canola ~ rice` | 5.0 | 0.375 | - | REFUSE-INSUFFICIENT | 2 | 0.0 | -0.4 |
| 51 | `cotton ~ srw_wheat` | 5.0 | 0.333 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 52 | `cotton ~ yellow_maize` | 5.0 | 0.364 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 53 | `palm_olein ~ rapeseed_meal` | 5.0 | 0.4 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 54 | `soybean_oil ~ yellow_maize` | 5.0 | 0.375 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 55 | `raw_sugar ~ soybeans` | 5.0 | 0.41 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 56 | `soybeans ~ white_sugar` | 5.0 | 0.4 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 57 | `canola ~ cotton` | 4.75 | 0.297 | - | REFUSE-INSUFFICIENT | 14 | 0.02 | -0.322 |
| 58 | `canola ~ palm_olein` | 4.75 | 0.282 | - | REFUSE-INSUFFICIENT | 1 | 0.52 | -0.046 |
| 59 | `cotton ~ hrs_wheat` | 4.75 | 0.324 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 60 | `french_wheat ~ soybeans` | 4.75 | 0.256 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 61 | `hrs_wheat ~ soybean_oil` | 4.75 | 0.333 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 62 | `rice ~ soybean_meal` | 4.75 | 0.282 | - | REFUSE-INSUFFICIENT | 13 | 0.0 | -0.461 |
| 63 | `rice ~ soybean_oil` | 4.75 | 0.393 | - | REFUSE-INSUFFICIENT | 9 | 0.0 | -0.481 |
| 64 | `soybean_meal ~ white_maize` | 4.75 | 0.275 | - | REFUSE-INSUFFICIENT | 1 | 0.01 | -0.304 |
| 65 | `soybean_oil ~ srw_wheat` | 4.75 | 0.306 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 66 | `raw_sugar ~ soybean_meal` | 4.75 | 0.385 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 67 | `cotton ~ white_maize` | 4.5 | 0.323 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 68 | `palm_olein ~ rapeseed` | 4.5 | 0.25 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 69 | `soybean_oil ~ white_maize` | 4.5 | 0.333 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 70 | `rapeseed ~ yellow_maize` | 4.5 | 0.4 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 71 | `raw_sugar ~ soybean_oil` | 4.5 | 0.483 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 72 | `soybean_meal ~ white_sugar` | 4.5 | 0.341 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 73 | `soybean_oil ~ white_sugar` | 4.5 | 0.467 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 74 | `srw_wheat ~ white_sugar` | 4.5 | 0.4 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 75 | `rapeseed_meal ~ yellow_maize` | 4.25 | 0.281 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 76 | `canola ~ hrw_wheat` | 4.25 | 0.333 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 77 | `canola ~ white_sugar` | 4.25 | 0.361 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 78 | `cotton ~ hrw_wheat` | 4.25 | 0.371 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 79 | `hrs_wheat ~ white_sugar` | 4.25 | 0.394 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 80 | `hrw_wheat ~ soybean_meal` | 4.25 | 0.289 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 81 | `hrw_wheat ~ white_sugar` | 4.25 | 0.361 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 82 | `raw_sugar ~ srw_wheat` | 4.25 | 0.371 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 83 | `cotton ~ rapeseed_meal` | 4.0 | 0.25 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 84 | `rapeseed_meal ~ rice` | 4.0 | 0.286 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 85 | `canola ~ raw_sugar` | 4.0 | 0.333 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 86 | `hrs_wheat ~ raw_sugar` | 4.0 | 0.364 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 87 | `hrw_wheat ~ raw_sugar` | 4.0 | 0.333 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 88 | `palm_oil ~ rice` | 4.0 | 0.4 | - | REFUSE-INSUFFICIENT | 19 | 0.02 | -0.348 |
| 89 | `rapeseed ~ srw_wheat` | 4.0 | 0.3 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 90 | `rapeseed ~ white_maize` | 4.0 | 0.364 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 91 | `raw_sugar ~ rice` | 4.0 | 0.429 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 92 | `raw_sugar ~ yellow_maize` | 4.0 | 0.364 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 93 | `white_sugar ~ yellow_maize` | 4.0 | 0.353 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 94 | `rapeseed_meal ~ white_maize` | 3.75 | 0.233 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 95 | `canola ~ french_wheat` | 3.75 | 0.306 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 96 | `cotton ~ palm_oil` | 3.75 | 0.314 | - | REFUSE-INSUFFICIENT | 6 | 0.0 | -0.43 |
| 97 | `cotton ~ palm_olein` | 3.75 | 0.314 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 98 | `french_wheat ~ soybean_meal` | 3.75 | 0.262 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 99 | `french_wheat ~ white_sugar` | 3.75 | 0.333 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 100 | `hrs_wheat ~ rapeseed` | 3.75 | 0.289 | - | REFUSE-INSUFFICIENT | 3 | 0.14 | -0.151 |
| 101 | `hrw_wheat ~ soybean_oil` | 3.75 | 0.306 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 102 | `palm_oil ~ yellow_maize` | 3.75 | 0.306 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 103 | `rice ~ white_sugar` | 3.75 | 0.367 | - | REFUSE-INSUFFICIENT | 2 | 0.01 | -0.387 |
| 104 | `hrs_wheat ~ rapeseed_meal` | 3.5 | 0.171 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 105 | `rapeseed_meal ~ srw_wheat` | 3.5 | 0.158 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 106 | `cotton ~ rapeseed_oil` | 3.5 | 0.312 | - | REFUSE-INSUFFICIENT | 3 | 0.02 | -0.317 |
| 107 | `french_wheat ~ raw_sugar` | 3.5 | 0.303 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 108 | `hrs_wheat ~ palm_oil` | 3.5 | 0.27 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 109 | `palm_oil ~ srw_wheat` | 3.5 | 0.25 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 110 | `palm_olein ~ rice` | 3.5 | 0.312 | - | REFUSE-INSUFFICIENT | 2 | 0.06 | -0.204 |
| 111 | `rapeseed ~ rice` | 3.5 | 0.294 | - | REFUSE-INSUFFICIENT | 30 | 0.06 | -0.262 |
| 112 | `raw_sugar ~ white_maize` | 3.5 | 0.323 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 113 | `white_maize ~ white_sugar` | 3.5 | 0.312 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 114 | `cotton ~ french_wheat` | 3.25 | 0.265 | - | REFUSE-INSUFFICIENT | 8 | 0.06 | -0.237 |
| 115 | `cotton ~ rapeseed` | 3.25 | 0.231 | - | REFUSE-INSUFFICIENT | 17 | 0.03 | -0.322 |
| 116 | `french_wheat ~ soybean_oil` | 3.25 | 0.273 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 117 | `palm_oil ~ white_maize` | 3.25 | 0.265 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 118 | `palm_olein ~ yellow_maize` | 3.25 | 0.237 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 119 | `rapeseed_oil ~ rice` | 3.25 | 0.31 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 120 | `rapeseed_oil ~ yellow_maize` | 3.25 | 0.265 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 121 | `hrs_wheat ~ palm_olein` | 3.0 | 0.205 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 122 | `palm_olein ~ srw_wheat` | 3.0 | 0.19 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 123 | `rapeseed_meal ~ raw_sugar` | 3.0 | 0.25 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 124 | `rapeseed_meal ~ white_sugar` | 3.0 | 0.242 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 125 | `rapeseed_oil ~ white_maize` | 3.0 | 0.258 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 126 | `hrs_wheat ~ rapeseed_oil` | 2.75 | 0.194 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 127 | `palm_olein ~ white_maize` | 2.75 | 0.194 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 128 | `rapeseed_oil ~ srw_wheat` | 2.75 | 0.179 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 129 | `hrw_wheat ~ rapeseed_meal` | 2.5 | 0.158 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |
| 130 | `french_wheat ~ rapeseed_meal` | 2.25 | 0.147 | - | REFUSE-INSUFFICIENT | 0 | 0.0 | None |

### Structural candidates the corpus AUTHORISES

- **`palm_oil ~ palm_olein`** (AUTHOR) -- 132 prop co-mentions (154 doc), lift 32.27, npmi 0.375 -- clears the >=60 floor with positive association and no shared surface form.
- **`french_wheat ~ hrw_wheat`** (AUTHOR-ON-STRUCTURE) -- corpus reads 3 prop co-mentions, but the pair is a declared complex member (complex:wheat, group:food_grains, group:grains) with slice Jaccard 0.679 -- a physical-identity / same-complex relationship the text never states in one sentence. The zero must not veto it; the reason belongs in the edge's mechanism text.
- **`french_wheat ~ hrs_wheat`** (AUTHOR-ON-STRUCTURE) -- corpus reads 1 prop co-mentions, but the pair is a declared complex member (complex:wheat, group:food_grains, group:grains) with slice Jaccard 0.692 -- a physical-identity / same-complex relationship the text never states in one sentence. The zero must not veto it; the reason belongs in the edge's mechanism text.
- **`canola ~ rapeseed`** (AUTHOR) -- 203 prop co-mentions (152 doc), lift 6.61, npmi 0.214 -- clears the >=60 floor with positive association and no shared surface form.

### Structural candidates the corpus REFUSES

- **`cotton ~ rice`** -- co-mentioned 300 times but lift 0.03 / npmi -0.406 -- the two appear together LESS than chance. That is an argument about what the edge would mean, not a licence.
