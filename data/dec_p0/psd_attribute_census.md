# PSD attribute-universe census (L2-0)

Precondition for the projection wave's Lane 3. One S3 GET, tallied in full.

| | |
|---|---|
| Source | `s3://leviathan-dev-shahem-001/bronze/production/source=usda_psd/release_date=2026-08-13/part-000.parquet` |
| ETag | `660f37a2095247b932baad212fe02604` |
| Bytes / last modified | 3,832,026 / 2026-08-13T18:03:07+00:00 |
| Release date used | **2026-08-13** (the requested prefix exists; newest of 8) |
| Rows in object | **2,092,687** |
| Distinct attribute labels | **69** (69 attribute_ids, 109 id x desc x unit triples) |
| Labels served / not served | 11 / **58** |
| Commodity codes | 63 in file, 47 mapped by the producer |
| Countries / MY span | 214 / 1960-2026 |

---

## e. THE D-6 NUMBER (leads, because it decides pg-mirror admission)

Total rows across exactly the declared T1 set -- Crush + the five demand-decomposition
attributes + the three TY attributes:

| Basis | Rows |
|---|---:|
| All commodity codes in the file | 396,200 |
| **Mapped (in-scope) commodity codes -- THE ADMISSION NUMBER** | **394,814** |
| In-scope, after the commodity -> leviathan_slug fan-out | 742,057 |

For scale, the currently-served eight targets on the same bases: **976,138** rows in-scope pre-explode,
**1,684,150** post-explode.

So the T1 payload is **40.4%** of the currently-served footprint pre-explode (**44.1%** post-explode).
The pg footprint is the declared subset -- **not ~1.9M**. 1.9M was never a pg number: it is the
post-commodity-filter row count of the whole bronze object across all 69 attributes.

Which of the two in-scope figures binds depends on whether the mirror is keyed by
`commodity_code` (394,814) or by `leviathan_slug` as silver is (742,057). Nine commodity codes carry
more than one slug (wheat x4, corn x5, soybeans x3, coffee x3, ...), which is the whole fan-out.

---

## a. Row totals -- the plan's arithmetic

| Quantity | Plan | Measured | Verdict |
|---|---:|---:|---|
| Kept by the step-6 attribute filter | 976,138 | **976,138** | CONFIRMED exact |
| Dropped by the step-6 attribute filter | 923,165 | **923,165** | CONFIRMED exact |
| Their sum | 1,899,303 | **1,899,303** | CONFIRMED exact |
| Rows in the object | (implied 1,899,303) | **2,092,687** | **CORRECTED** |
| Rows dropped at step 3 (unmapped commodity) | -- | **193,384** | the missing 193,384 |

The kept/dropped pair is right to the row. What the plan gets wrong is the base: 1,899,303 is
the count AFTER the commodity filter, not the object's size. The object holds 2,092,687 rows;
193,384 of them belong to the 16 commodity codes `_PSD_UNMAPPED_CODES` refuses (animal numbers,
the citrus siblings, the soy 'Local' marketing-year duplicates, and the eight no-node fruit/nut
sheets). That 193,384 matches the producer's own docstring figure for the post-widening discard
(193,384 rows, 9.2%) to the row, so the two independent tallies agree.

The kept figure decomposes as 957,214 rows on the eight target labels plus 18,924 rows the three
slug-keyed remaps pull in (Total Disappearance, Domestic Use, Fresh Dom. Consumption).

---

## b. Area Planted -- the contradiction, settled

**There is no Area Planted attribute in this object, under any spelling.**

**And there was never a contradiction to settle -- the plan mis-read its own source.**
`projection_census.md:931` asserts Area Planted as a column of the 'PSD Data Statistics'
balance-sheet tables printed **inside GAIN attache PDFs**, and the very same sentence states
that those attache numbers are NOT in the PSD bulk file. It never claimed the bulk file carries
the attribute. The 47-label roster and line 931 are both correct; they describe different
objects. Nothing needs to be overturned -- but the plan's framing of this as a doc conflict
should be struck so it is not re-litigated.

The measurement below is still worth banking, because it converts 'the roster does not list it'
into 'the source does not publish it'.

Three independent checks, all negative:

1. No label matches `plant|sown|seeded|sowing|acre` (case-insensitive). Matches: **none**.
2. The only label matching `area` is `Area Harvested` -- one label, one unit.
3. USDA's attribute_id **3** (Area Planted in the PSD attribute dictionary) has **0 rows**;
   it is not among the 69 ids the file carries. The lowest id present is 4, Area Harvested.

The one area attribute measured in full:

| id | label | unit | rows | rows in-scope | commodity codes | countries | MY span | served |
|---:|---|---|---:|---:|---:|---:|---|---|
| 4 | `Area Harvested` | `(1000 HA)` | 63,914 | 63,788 | 17 (16 in-scope) | 179 | 1960-2026 | YES (target) |

**Consequence for the wave:** PSD offers no lever on global planted-vs-harvested area, so no
widening of `_TARGET_ATTRS` can produce one. Any card wanting planted area -- and therefore any
abandonment/loss read taken as planted minus harvested -- needs a different lane entirely: the
GAIN PSD-table parser that `projection_census.md:931` already prices as a new lane. That is a
Lane-3-independent piece of work, and it should be re-filed as such rather than carried as an
attribute-roster question.

---

## Reconciliation with the prior roster (why 69 vs 58 vs 47)

`projection_census.md:15` says "8 of 58 attributes are kept; 923,165 rows are dropped across 47
labels". This census says 69 labels, 11 served, 58 unserved. **Both are right; the bases differ.**

| Figure | Value | Base |
|---|---:|---|
| Labels in the object | **69** | every row, in scope or not |
| Labels carrying at least one IN-SCOPE row | **58** | after the commodity filter -- the prior doc's "58 attributes" |
| ... of those, served | **11** | 8 targets + 3 slug-keyed remaps |
| ... of those, NOT served | **47** | the prior doc's "47 labels" -- exact |
| Labels with ZERO in-scope rows | **11** | invisible to the prior doc; refused at the commodity filter |

The 11 labels the prior roster could not see, because every one of their rows belongs to an
unmapped commodity: `Beef Cows Beg. Stocks`, `Calf Slaughter`, `Commercial Production`, `Cow Slaughter`, `Dairy Cows Beg. Stocks`, `Loss and Residual`, `Non-Comm. Production`, `Sow Beginning Stocks`, `Sow Slaughter`, `Total Slaughter`, `Withdrawal From Market`.

One genuine correction: the prior doc's "8 of 58 kept" undercounts the accepted set. Eleven
labels survive step 6, not eight -- `Total Disappearance`, `Domestic Use` and `Fresh Dom.
Consumption` are remapped to `Domestic Consumption` BEFORE the filter and carry 18,924 rows
between them. An `_PSD_UNMAPPED_ATTRS` roster authored against the "8" figure would wrongly
list those three as refused.

---

## c. Labels NOT served -- all 58

Diff of the measured universe against the producer's accepted set in
`src/leviathan/transforms/bronze_to_silver/usda_psd.py`: `_TARGET_ATTRS` (L486-495, eight labels)
plus the three slug-keyed remap sources (L510-521) that also survive step 6. 11 accepted,
69 measured, **58 unserved**. Spellings below are BYTE-EXACT.

| # | label (byte-exact) | attr id | units | rows | rows in-scope |
|---:|---|---:|---|---:|---:|
| 1 | `Total Distribution` | 178 | `(1000 60 KG BAGS)` `(1000 HEAD)` `(1000 MT CWE)` `(1000 MT)` `(MT)` `1000 480 lb. Bales` | 162,787 | 142,014 |
| 2 | `Total Supply` | 86 | `(1000 60 KG BAGS)` `(1000 HEAD)` `(1000 MT CWE)` `(1000 MT)` `(MT)` `1000 480 lb. Bales` | 162,787 | 142,014 |
| 3 | `Feed Waste Dom. Cons.` | 161 | `(1000 MT)` | 60,518 | 60,140 |
| 4 | `Food Use Dom. Cons.` | 149 | `(1000 MT)` | 60,518 | 60,140 |
| 5 | `Crush` | 7 | `(1000 MT)` | 52,853 | 52,475 |
| 6 | `Industrial Dom. Cons.` | 140 | `(1000 MT)` | 43,698 | 43,446 |
| 7 | `TY Exports` | 113 | `(1000 MT)` | 38,769 | 38,769 |
| 8 | `TY Imp. from U.S.` | 84 | `(1000 MT)` | 38,769 | 38,769 |
| 9 | `TY Imports` | 81 | `(1000 MT)` | 38,769 | 38,769 |
| 10 | `Extr. Rate, 999.9999` | 181 | `(PERCENT)` | 38,138 | 37,886 |
| 11 | `FSI Consumption` | 192 | `(1000 MT)` | 31,153 | 31,153 |
| 12 | `Feed Dom. Consumption` | 130 | `(1000 MT)` | 31,153 | 31,153 |
| 13 | `SME` | 194 | `(1000 MT)` | 19,013 | 18,887 |
| 14 | `Total Use` | 174 | `(1000 MT)` | 10,190 | 10,190 |
| 15 | `Beet Sugar Production` | 30 | `(1000 MT)` | 9,501 | 9,501 |
| 16 | `Cane Sugar Production` | 43 | `(1000 MT)` | 9,501 | 9,501 |
| 17 | `Human Dom. Consumption` | 139 | `(1000 MT)` | 9,501 | 9,501 |
| 18 | `Other Disappearance` | 151 | `(1000 MT)` | 9,501 | 9,501 |
| 19 | `Raw Exports` | 89 | `(1000 MT)` | 9,501 | 9,501 |
| 20 | `Raw Imports` | 64 | `(1000 MT)` | 9,501 | 9,501 |
| 21 | `Refined Exp.(Raw Val)` | 99 | `(1000 MT)` | 9,501 | 9,501 |
| 22 | `Refined Imp.(Raw Val)` | 74 | `(1000 MT)` | 9,501 | 9,501 |
| 23 | `Commercial Production` | 31 | `(MT)` | 8,808 | 0 |
| 24 | `Non-Comm. Production` | 47 | `(MT)` | 8,808 | 0 |
| 25 | `Withdrawal From Market` | 169 | `(MT)` | 8,808 | 0 |
| 26 | `Loss` | 150 | `1000 480 lb. Bales` | 7,777 | 7,777 |
| 27 | `Stocks-to-Use` | 195 | `(PERCENT)` | 7,777 | 7,777 |
| 28 | `Milling Rate (.9999)` | 182 | `(1000 MT)` | 7,616 | 7,616 |
| 29 | `Rough Production` | 54 | `(1000 MT)` | 7,616 | 7,616 |
| 30 | `For Processing` | 132 | `(1000 MT)` | 5,088 | 1,646 |
| 31 | `Loss and Residual` | 172 | `(1000 HEAD)` | 4,836 | 0 |
| 32 | `Total Slaughter` | 117 | `(1000 HEAD)` | 4,836 | 0 |
| 33 | `Arabica Production` | 29 | `(1000 60 KG BAGS)` | 4,616 | 4,616 |
| 34 | `Bean Exports` | 90 | `(1000 60 KG BAGS)` | 4,616 | 4,616 |
| 35 | `Bean Imports` | 58 | `(1000 60 KG BAGS)` | 4,616 | 4,616 |
| 36 | `Other Production` | 56 | `(1000 60 KG BAGS)` | 4,616 | 4,616 |
| 37 | `Roast & Ground Exports` | 107 | `(1000 60 KG BAGS)` | 4,616 | 4,616 |
| 38 | `Roast & Ground Imports` | 75 | `(1000 60 KG BAGS)` | 4,616 | 4,616 |
| 39 | `Robusta Production` | 53 | `(1000 60 KG BAGS)` | 4,616 | 4,616 |
| 40 | `Rst,Ground Dom. Consum` | 141 | `(1000 60 KG BAGS)` | 4,616 | 4,616 |
| 41 | `Soluble Dom. Cons.` | 154 | `(1000 60 KG BAGS)` | 4,616 | 4,616 |
| 42 | `Soluble Exports` | 114 | `(1000 60 KG BAGS)` | 4,616 | 4,616 |
| 43 | `Soluble Imports` | 82 | `(1000 60 KG BAGS)` | 4,616 | 4,616 |
| 44 | `Beef Cows Beg. Stocks` | 25 | `(1000 HEAD)` | 2,655 | 0 |
| 45 | `Calf Slaughter` | 122 | `(1000 HEAD)` | 2,655 | 0 |
| 46 | `Cow Slaughter` | 118 | `(1000 HEAD)` | 2,655 | 0 |
| 47 | `Dairy Cows Beg. Stocks` | 23 | `(1000 HEAD)` | 2,655 | 0 |
| 48 | `Seed to Lint Ratio` | 183 | `(RATIO)` | 2,341 | 2,341 |
| 49 | `Annual % Change Per Cap. Cons.` | 220 | `(PERCENT)` | 2,195 | 2,195 |
| 50 | `Sow Beginning Stocks` | 22 | `(1000 HEAD)` | 2,181 | 0 |
| 51 | `Sow Slaughter` | 121 | `(1000 HEAD)` | 2,181 | 0 |
| 52 | `Catch For Reduction` | 5 | `(1000 MT)` | 2,106 | 2,106 |
| 53 | `Cows In Milk` | 6 | `(1000 HEAD)` | 1,917 | 1,917 |
| 54 | `Cows Milk Production` | 32 | `(1000 MT)` | 1,917 | 1,917 |
| 55 | `Factory Use Consum.` | 147 | `(1000 MT)` | 1,917 | 1,917 |
| 56 | `Feed Use Dom. Consum.` | 158 | `(1000 MT)` | 1,917 | 1,917 |
| 57 | `Fluid Use Dom. Consum.` | 131 | `(1000 MT)` | 1,917 | 1,917 |
| 58 | `Other Milk Production` | 49 | `(1000 MT)` | 1,917 | 1,917 |

The 11 that ARE served, for contrast:

| label (byte-exact) | attr id | role | rows | rows in-scope |
|---|---:|---|---:|---:|
| `Exports` | 88 | target | 162,787 | 142,014 |
| `Imports` | 57 | target | 162,787 | 142,014 |
| `Production` | 28 | target | 162,787 | 142,014 |
| `Beginning Stocks` | 20 | target | 146,974 | 138,451 |
| `Ending Stocks` | 176 | target | 146,974 | 138,451 |
| `Domestic Consumption` | 125 | target | 134,267 | 123,090 |
| `Yield` | 184 | target | 67,518 | 67,392 |
| `Area Harvested` | 4 | target | 63,914 | 63,788 |
| `Total Disappearance` | 126 | remapped -> Domestic Consumption | 9,501 | 9,501 |
| `Domestic Use` | 142 | remapped -> Domestic Consumption | 7,777 | 7,777 |
| `Fresh Dom. Consumption` | 135 | remapped -> Domestic Consumption | 6,406 | 1,646 |

Note that `Total Supply` and `Total Distribution` (162,787 rows each) are the two largest unserved
labels in the file. They are identities, not new information -- supply = beginning stocks +
production + imports -- so they are cheap to recompute and are not part of the T1 ask.

---

## d. The ranked T1 payload -- plan figures confirmed

Every one of the plan's nine row counts is the **in-scope** count and every one is exact.
Spellings are given byte-exact; these become card metric values verbatim.

| slot | label (BYTE-EXACT) | id | unit | plan rows | measured in-scope | verdict | comm. codes (all/in) | countries | MY span |
|---|---|---:|---|---:|---:|---|---|---:|---|
| crush | `Crush` | 7 | `(1000 MT)` | 52,475 | **52,475** | EXACT | 24 / 21 | 159 | 1960-2026 |
| feed_dom_consumption | `Feed Dom. Consumption` | 130 | `(1000 MT)` | 31,153 | **31,153** | EXACT | 8 / 8 | 158 | 1960-2026 |
| fsi_consumption | `FSI Consumption` | 192 | `(1000 MT)` | 31,153 | **31,153** | EXACT | 8 / 8 | 158 | 1960-2026 |
| feed_waste_dom_cons | `Feed Waste Dom. Cons.` | 161 | `(1000 MT)` | 60,140 | **60,140** | EXACT | 27 / 24 | 168 | 1960-2026 |
| food_use_dom_cons | `Food Use Dom. Cons.` | 149 | `(1000 MT)` | 60,140 | **60,140** | EXACT | 27 / 24 | 168 | 1960-2026 |
| industrial_dom_cons | `Industrial Dom. Cons.` | 140 | `(1000 MT)` | 43,446 | **43,446** | EXACT | 19 / 17 | 164 | 1961-2026 |
| ty_exports | `TY Exports` | 113 | `(1000 MT)` | 38,769 | **38,769** | EXACT | 9 / 9 | 163 | 1960-2026 |
| ty_imports | `TY Imports` | 81 | `(1000 MT)` | 38,769 | **38,769** | EXACT | 9 / 9 | 163 | 1960-2026 |
| ty_imp_from_us | `TY Imp. from U.S.` | 84 | `(1000 MT)` | 38,769 | **38,769** | EXACT | 9 / 9 | 163 | 1960-2026 |

Two corrections to the plan's Crush line, both about BASIS rather than about the number:

- **24 commodities is the all-file figure; in-scope it is 21.** `Crush` appears on 24 commodity
  codes, three of which the producer does not map. The 52,475 rows the plan quotes is already the
  in-scope figure, so the plan pairs an in-scope row count with an all-file commodity count.
- 159 countries and MY 1960-2026 hold on both bases -- no correction needed.

The 21 in-scope Crush sheets are the oilseed/meal/oil triples: `Meal, Copra`, `Meal, Cottonseed`, `Meal, Palm Kernel`, `Meal, Peanut`, `Meal, Rapeseed`, `Meal, Soybean`, `Meal, Sunflowerseed`, `Oil, Coconut`, `Oil, Cottonseed`, `Oil, Palm Kernel`, `Oil, Peanut`, `Oil, Rapeseed`, `Oil, Soybean`, `Oil, Sunflowerseed`, `Oilseed, Copra`, `Oilseed, Cottonseed`, `Oilseed, Palm Kernel`, `Oilseed, Peanut`, `Oilseed, Rapeseed`, `Oilseed, Soybean`, `Oilseed, Sunflowerseed`.

`Industrial Dom. Cons.` starts at MY **1961**, one year later than the other eight -- the only
span deviation in the payload.

Per-slot fan-out, if the mirror is slug-keyed:

| slot | pre-explode | post-explode |
|---|---:|---:|
| `Crush` | 52,475 | 71,551 |
| `Feed Dom. Consumption` | 31,153 | 84,759 |
| `FSI Consumption` | 31,153 | 84,759 |
| `Feed Waste Dom. Cons.` | 60,140 | 83,368 |
| `Food Use Dom. Cons.` | 60,140 | 83,368 |
| `Industrial Dom. Cons.` | 43,446 | 57,127 |
| `TY Exports` | 38,769 | 92,375 |
| `TY Imports` | 38,769 | 92,375 |
| `TY Imp. from U.S.` | 38,769 | 92,375 |
| **total** | **394,814** | **742,057** |

---

## f. Percent / ratio attributes -- must stay NATIVE units

The unit-factor guard excludes `(PERCENT)` and `(RATIO)` deliberately: neither has a mass factor,
and the producer's comment records that they only ever ride non-target attributes. Measured, that
is **4** labels:

| label (byte-exact) | id | unit | rows | rows in-scope | value min / median / max |
|---|---:|---|---:|---:|---|
| `Extr. Rate, 999.9999` | 181 | `(PERCENT)` | 38,138 | 37,886 | 0 / 0.38 / 1e+04 |
| `Stocks-to-Use` | 195 | `(PERCENT)` | 7,777 | 7,777 | 0 / 25 / 506.2 |
| `Seed to Lint Ratio` | 183 | `(RATIO)` | 2,341 | 2,341 | 0 / 0 / 1.656e+06 |
| `Annual % Change Per Cap. Cons.` | 220 | `(PERCENT)` | 2,195 | 2,195 | -100 / 1.1 / 482.6 |

### The trap the unit guard does NOT catch

**`Milling Rate (.9999)` (id 182) is a rate carrying `unit_desc = (1000 MT)`.**

7,616 rows, all in-scope, values min 0 / median 6500 / max 7561. A median of 6,500 on a label whose
own name says `.9999` is a rate scaled by 1e4 -- a milling rate of ~0.65, not 6,500 thousand tonnes.

This matters because it is the one rate-like attribute that would sail straight through the
`_UNIT_FACTOR` guard: the guard rejects unknown units, and `(1000 MT)` is known, so admitting
this label would multiply a rate by 1,000 and land a number ~1e7 too large with nothing to trip.
`Extr. Rate, 999.9999` is safe by contrast only because USDA labelled it `(PERCENT)`. If Lane 3
ever widens `_TARGET_ATTRS` beyond the T1 nine, this label needs an explicit refusal keyed on the
ATTRIBUTE, not on the unit. (It is not in the T1 set, so nothing is broken today.)

Two further scale oddities worth a look before any of these is served, neither in the T1 set:

- `Extr. Rate, 999.9999` spans 0 to 1e+04 on `(PERCENT)` -- median 0.38 reads as a fraction while
  the maximum reads as a 1e4-scaled one, so the column is not on a single scale.
- `Seed to Lint Ratio` on `(RATIO)` reaches 1.656e+06, which no ratio should.

### `(1000 HEAD)` is NOT fully fenced by the commodity filter

The producer's inline note at `_UNIT_FACTOR` says `(1000 HEAD)` "is the unit of the two
animal-numbers codes, which `_PSD_UNMAPPED_CODES` refuses". Measured, there is a **third**
carrier: **`Cows In Milk`** (id 6, `(1000 HEAD)`, 1,917 rows) rides `Dairy, Milk, Fluid`, which IS a mapped
commodity -- so all 1,917 of its rows survive step 3 and are stopped only by the step-6 ATTRIBUTE
filter. Of the 16 `(1000 HEAD)` triples, 15 are 0-in-scope as the note describes; this one is not.

Nothing is wrong today -- the attribute filter holds and `Cows In Milk` is not in the T1 set --
but the note misdescribes WHICH fence is load-bearing. If Lane 3 widens `_TARGET_ATTRS` by
editing that set alone, this is the row block that would reach step 7, hit the unknown-unit
`ValueError`, and fail the whole transform rather than being quietly excluded. Worth a comment
correction in the producer so the next reader does not trust the wrong fence.

For completeness, every triple with no `_UNIT_FACTOR` entry (the full set the guard would reject
outright) is **20** triples carrying **52,116** in-scope rows: the four `(PERCENT)`/`(RATIO)` labels
above (50,199 in-scope rows) plus the 16-triple `(1000 HEAD)` block (1,917 in-scope rows, all of them
`Cows In Milk`).

---

## Appendix: the full label roster (69 labels)

Machine-readable form, including the 109 (attribute_id x desc x unit) triples with per-triple
commodity lists, is in `psd_attribute_census.json` alongside this file.

| label (byte-exact) | id(s) | units | rows | in-scope | comm. | countries | MY span | serving role |
|---|---:|---|---:|---:|---:|---:|---|---|
| `Exports` | 88 | `(1000 60 KG BAGS)` `(1000 HEAD)` `(1000 MT CWE)` `(1000 MT)` `(MT)` `1000 480 lb. Bales` | 162,787 | 142,014 | 63 | 214 | 1960-2026 | target |
| `Imports` | 57 | `(1000 60 KG BAGS)` `(1000 HEAD)` `(1000 MT CWE)` `(1000 MT)` `(MT)` `1000 480 lb. Bales` | 162,787 | 142,014 | 63 | 214 | 1960-2026 | target |
| `Production` | 28 | `(1000 60 KG BAGS)` `(1000 HEAD)` `(1000 MT CWE)` `(1000 MT)` `(MT)` `1000 480 lb. Bales` | 162,787 | 142,014 | 63 | 214 | 1960-2026 | target |
| `Total Distribution` | 178 | `(1000 60 KG BAGS)` `(1000 HEAD)` `(1000 MT CWE)` `(1000 MT)` `(MT)` `1000 480 lb. Bales` | 162,787 | 142,014 | 63 | 214 | 1960-2026 | NOT SERVED |
| `Total Supply` | 86 | `(1000 60 KG BAGS)` `(1000 HEAD)` `(1000 MT CWE)` `(1000 MT)` `(MT)` `1000 480 lb. Bales` | 162,787 | 142,014 | 63 | 214 | 1960-2026 | NOT SERVED |
| `Beginning Stocks` | 20 | `(1000 60 KG BAGS)` `(1000 HEAD)` `(1000 MT CWE)` `(1000 MT)` `(MT)` `1000 480 lb. Bales` | 146,974 | 138,451 | 53 | 212 | 1960-2026 | target |
| `Ending Stocks` | 176 | `(1000 60 KG BAGS)` `(1000 HEAD)` `(1000 MT CWE)` `(1000 MT)` `(MT)` `1000 480 lb. Bales` | 146,974 | 138,451 | 53 | 212 | 1960-2026 | target |
| `Domestic Consumption` | 125 | `(1000 60 KG BAGS)` `(1000 MT CWE)` `(1000 MT)` `(MT)` | 134,267 | 123,090 | 54 | 196 | 1960-2026 | target |
| `Yield` | 184 | `(KG/HA)` `(MT/HA)` | 67,518 | 67,392 | 19 | 184 | 1960-2026 | target |
| `Area Harvested` | 4 | `(1000 HA)` | 63,914 | 63,788 | 17 | 179 | 1960-2026 | target |
| `Feed Waste Dom. Cons.` | 161 | `(1000 MT)` | 60,518 | 60,140 | 27 | 168 | 1960-2026 | NOT SERVED |
| `Food Use Dom. Cons.` | 149 | `(1000 MT)` | 60,518 | 60,140 | 27 | 168 | 1960-2026 | NOT SERVED |
| `Crush` | 7 | `(1000 MT)` | 52,853 | 52,475 | 24 | 159 | 1960-2026 | NOT SERVED |
| `Industrial Dom. Cons.` | 140 | `(1000 MT)` | 43,698 | 43,446 | 19 | 164 | 1961-2026 | NOT SERVED |
| `TY Exports` | 113 | `(1000 MT)` | 38,769 | 38,769 | 9 | 163 | 1960-2026 | NOT SERVED |
| `TY Imp. from U.S.` | 84 | `(1000 MT)` | 38,769 | 38,769 | 9 | 163 | 1960-2026 | NOT SERVED |
| `TY Imports` | 81 | `(1000 MT)` | 38,769 | 38,769 | 9 | 163 | 1960-2026 | NOT SERVED |
| `Extr. Rate, 999.9999` | 181 | `(PERCENT)` | 38,138 | 37,886 | 17 | 158 | 1961-2026 | NOT SERVED |
| `FSI Consumption` | 192 | `(1000 MT)` | 31,153 | 31,153 | 8 | 158 | 1960-2026 | NOT SERVED |
| `Feed Dom. Consumption` | 130 | `(1000 MT)` | 31,153 | 31,153 | 8 | 158 | 1960-2026 | NOT SERVED |
| `SME` | 194 | `(1000 MT)` | 19,013 | 18,887 | 9 | 153 | 1961-2026 | NOT SERVED |
| `Total Use` | 174 | `(1000 MT)` | 10,190 | 10,190 | 6 | 103 | 1960-2026 | NOT SERVED |
| `Beet Sugar Production` | 30 | `(1000 MT)` | 9,501 | 9,501 | 1 | 194 | 1960-2026 | NOT SERVED |
| `Cane Sugar Production` | 43 | `(1000 MT)` | 9,501 | 9,501 | 1 | 194 | 1960-2026 | NOT SERVED |
| `Human Dom. Consumption` | 139 | `(1000 MT)` | 9,501 | 9,501 | 1 | 194 | 1960-2026 | NOT SERVED |
| `Other Disappearance` | 151 | `(1000 MT)` | 9,501 | 9,501 | 1 | 194 | 1960-2026 | NOT SERVED |
| `Raw Exports` | 89 | `(1000 MT)` | 9,501 | 9,501 | 1 | 194 | 1960-2026 | NOT SERVED |
| `Raw Imports` | 64 | `(1000 MT)` | 9,501 | 9,501 | 1 | 194 | 1960-2026 | NOT SERVED |
| `Refined Exp.(Raw Val)` | 99 | `(1000 MT)` | 9,501 | 9,501 | 1 | 194 | 1960-2026 | NOT SERVED |
| `Refined Imp.(Raw Val)` | 74 | `(1000 MT)` | 9,501 | 9,501 | 1 | 194 | 1960-2026 | NOT SERVED |
| `Total Disappearance` | 126 | `(1000 MT)` | 9,501 | 9,501 | 1 | 194 | 1960-2026 | remapped -> Domestic Consumption |
| `Commercial Production` | 31 | `(MT)` | 8,808 | 0 | 5 | 97 | 1960-2025 | NOT SERVED |
| `Non-Comm. Production` | 47 | `(MT)` | 8,808 | 0 | 5 | 97 | 1960-2025 | NOT SERVED |
| `Withdrawal From Market` | 169 | `(MT)` | 8,808 | 0 | 5 | 97 | 1960-2025 | NOT SERVED |
| `Domestic Use` | 142 | `1000 480 lb. Bales` | 7,777 | 7,777 | 1 | 135 | 1960-2026 | remapped -> Domestic Consumption |
| `Loss` | 150 | `1000 480 lb. Bales` | 7,777 | 7,777 | 1 | 135 | 1960-2026 | NOT SERVED |
| `Stocks-to-Use` | 195 | `(PERCENT)` | 7,777 | 7,777 | 1 | 135 | 1960-2026 | NOT SERVED |
| `Milling Rate (.9999)` | 182 | `(1000 MT)` | 7,616 | 7,616 | 1 | 138 | 1960-2026 | NOT SERVED |
| `Rough Production` | 54 | `(1000 MT)` | 7,616 | 7,616 | 1 | 138 | 1960-2026 | NOT SERVED |
| `Fresh Dom. Consumption` | 135 | `(1000 MT)` `(MT)` | 6,406 | 1,646 | 5 | 63 | 1960-2025 | remapped -> Domestic Consumption |
| `For Processing` | 132 | `(1000 MT)` | 5,088 | 1,646 | 4 | 54 | 1964-2025 | NOT SERVED |
| `Loss and Residual` | 172 | `(1000 HEAD)` | 4,836 | 0 | 2 | 85 | 1960-2026 | NOT SERVED |
| `Total Slaughter` | 117 | `(1000 HEAD)` | 4,836 | 0 | 2 | 85 | 1960-2026 | NOT SERVED |
| `Arabica Production` | 29 | `(1000 60 KG BAGS)` | 4,616 | 4,616 | 1 | 94 | 1960-2026 | NOT SERVED |
| `Bean Exports` | 90 | `(1000 60 KG BAGS)` | 4,616 | 4,616 | 1 | 94 | 1960-2026 | NOT SERVED |
| `Bean Imports` | 58 | `(1000 60 KG BAGS)` | 4,616 | 4,616 | 1 | 94 | 1960-2026 | NOT SERVED |
| `Other Production` | 56 | `(1000 60 KG BAGS)` | 4,616 | 4,616 | 1 | 94 | 1960-2026 | NOT SERVED |
| `Roast & Ground Exports` | 107 | `(1000 60 KG BAGS)` | 4,616 | 4,616 | 1 | 94 | 1960-2026 | NOT SERVED |
| `Roast & Ground Imports` | 75 | `(1000 60 KG BAGS)` | 4,616 | 4,616 | 1 | 94 | 1960-2026 | NOT SERVED |
| `Robusta Production` | 53 | `(1000 60 KG BAGS)` | 4,616 | 4,616 | 1 | 94 | 1960-2026 | NOT SERVED |
| `Rst,Ground Dom. Consum` | 141 | `(1000 60 KG BAGS)` | 4,616 | 4,616 | 1 | 94 | 1960-2026 | NOT SERVED |
| `Soluble Dom. Cons.` | 154 | `(1000 60 KG BAGS)` | 4,616 | 4,616 | 1 | 94 | 1960-2026 | NOT SERVED |
| `Soluble Exports` | 114 | `(1000 60 KG BAGS)` | 4,616 | 4,616 | 1 | 94 | 1960-2026 | NOT SERVED |
| `Soluble Imports` | 82 | `(1000 60 KG BAGS)` | 4,616 | 4,616 | 1 | 94 | 1960-2026 | NOT SERVED |
| `Beef Cows Beg. Stocks` | 25 | `(1000 HEAD)` | 2,655 | 0 | 1 | 82 | 1960-2026 | NOT SERVED |
| `Calf Slaughter` | 122 | `(1000 HEAD)` | 2,655 | 0 | 1 | 82 | 1960-2026 | NOT SERVED |
| `Cow Slaughter` | 118 | `(1000 HEAD)` | 2,655 | 0 | 1 | 82 | 1960-2026 | NOT SERVED |
| `Dairy Cows Beg. Stocks` | 23 | `(1000 HEAD)` | 2,655 | 0 | 1 | 82 | 1960-2026 | NOT SERVED |
| `Seed to Lint Ratio` | 183 | `(RATIO)` | 2,341 | 2,341 | 1 | 58 | 1966-2026 | NOT SERVED |
| `Annual % Change Per Cap. Cons.` | 220 | `(PERCENT)` | 2,195 | 2,195 | 2 | 76 | 1983-2026 | NOT SERVED |
| `Sow Beginning Stocks` | 22 | `(1000 HEAD)` | 2,181 | 0 | 1 | 76 | 1960-2026 | NOT SERVED |
| `Sow Slaughter` | 121 | `(1000 HEAD)` | 2,181 | 0 | 1 | 76 | 1960-2026 | NOT SERVED |
| `Catch For Reduction` | 5 | `(1000 MT)` | 2,106 | 2,106 | 1 | 52 | 1964-2025 | NOT SERVED |
| `Cows In Milk` | 6 | `(1000 HEAD)` | 1,917 | 1,917 | 1 | 69 | 1964-2026 | NOT SERVED |
| `Cows Milk Production` | 32 | `(1000 MT)` | 1,917 | 1,917 | 1 | 69 | 1964-2026 | NOT SERVED |
| `Factory Use Consum.` | 147 | `(1000 MT)` | 1,917 | 1,917 | 1 | 69 | 1964-2026 | NOT SERVED |
| `Feed Use Dom. Consum.` | 158 | `(1000 MT)` | 1,917 | 1,917 | 1 | 69 | 1964-2026 | NOT SERVED |
| `Fluid Use Dom. Consum.` | 131 | `(1000 MT)` | 1,917 | 1,917 | 1 | 69 | 1964-2026 | NOT SERVED |
| `Other Milk Production` | 49 | `(1000 MT)` | 1,917 | 1,917 | 1 | 69 | 1964-2026 | NOT SERVED |
