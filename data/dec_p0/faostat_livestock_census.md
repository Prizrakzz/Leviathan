# FAOSTAT QCL element x item x unit census — FAO-2 (Lane 5)

**Instrument** `jobs/utils/faostat_element_item_census.py` (committed beside this file)
**Object** `data/raw/production/faostat/qcl/Production_Crops_Livestock_E_All_Data_(Normalized).zip`
— the tracked 2026-05-11 release, the same object the crop-half backfill runs off.
**Cost** one local stream, no network, no AWS, $0. **Rows read** 4,209,110.
**Machine-readable** `data/dec_p0/faostat_livestock_census.json`.

Every literal in `configs/sources/faostat_item_map.yaml`'s livestock block,
`transforms/raw_to_bronze/faostat_qcl.TARGET_ELEMENTS`,
`transforms/bronze_to_silver/faostat_production.METRIC_UNITS` and
`tests/unit/test_faostat_livestock_axis.py` cites THIS artifact. Nothing below is inferred.

---

## 1. The element universe — the bronze gate can now be the whole of it

| element | rows | units printed (rows) |
|---|---:|---|
| Production | 1,643,611 | `t` 1,625,403 · `1000 No` 18,208 |
| Area harvested | 893,484 | `ha` 893,484 |
| Yield | 839,819 | `kg/ha` 823,058 · `No/An` 16,761 |
| **Producing Animals/Slaughtered** | **313,081** | `An` 261,580 · `1000 An` 51,501 |
| **Yield/Carcass Weight** | **262,197** | `kg/An` 181,253 · `g/An` 80,944 |
| **Stocks** | **180,294** | `An` 117,255 · `1000 An` 53,845 · `No` 9,194 |
| **Milk Animals** | **45,801** | `An` 45,801 |
| **Laying** | **30,823** | `1000 An` 30,823 |
| **total** | **4,209,110** | = the whole file, exactly |

The eight sum to the file. That is the finding that lets `TARGET_ELEMENTS` stop being "the three
the crop half needed" and become the complete live universe: after this change no element can be
dropped at the bronze gate again.

**The livestock five = 832,196 rows.** The plan's headline figure, re-measured and EXACT, and its
five per-element numbers are exact too. Recorded as *measured*, no longer *plan-inferred*.

**Two legend names carry ZERO rows** — `Extraction Rate` (element 5423) and `Prod Popultn`
(5314/5319). The legend declares 10 names across 20 element codes; 8 are live. Dead legend keys are
the same tell the four dead pre-2022 flags gave (`F` / `Fc` / `Im` / `*`), and they are refused in
writing at `faostat_qcl._REFUSED_LEGEND_ELEMENTS` rather than left as an absence.

## 2. The item axis — measured, admitted and parked

All spans are 1961–2024. "areas" = distinct FAOSTAT Area strings.

### Admitted (4 slugs, 80,654 rows)

| slug | FAO item | element | unit | rows | areas |
|---|---|---|---|---:|---:|
| `cattle_beef` | `Cattle` | Stocks | `An` | 13,831 | 238 |
| `hogs` | `Swine / pigs` | Stocks | `An` | 12,824 | 219 |
| `broilers_poultry` | `Chickens` | Stocks | **`1000 An`** | 13,932 | 240 |
| `milk_fluid` | `Raw milk of cattle` | Milk Animals | `An` | 13,360 | 231 |
| `milk_fluid` | `Raw milk of cattle` | Production | `t` | 13,359 | 231 |
| `milk_fluid` | `Raw milk of cattle` | Yield/Carcass Weight | `kg/An` | 13,348 | 231 |

**The 1000x trap, measured:** `live_animals` carries `An` for cattle and pigs and `1000 An` for
chickens. Only the row's own `unit` column distinguishes them.

**Two of the plan's item strings were wrong** and both would have died in the cloud on
"No rows found": the release prints `Swine / pigs` (not "Pigs") and `Hen eggs in shell, fresh`
(not "Hen eggs in shell"). Caught here, against the release's own `ItemCodes` legend member.

### Parked, with the number that makes each park honest

| item | rows | areas | why parked |
|---|---:|---:|---|
| `Sheep` | 12,994 (Stocks) | 225 | no hierarchy node, no PSD slug |
| `Goats` | 13,350 (Stocks) | 233 | no hierarchy node, no PSD slug |
| `Hen eggs in shell, fresh` | 69,051 (4 elements) | 240 | three independent reasons — see §3 |
| `Meat of cattle with the bone, fresh or chilled` | 41,541 | 239 | slaughter axis; no slug left |
| `Meat of chickens, fresh or chilled` | 41,920 | 240 | slaughter axis; no slug left |
| `Meat of pig with the bone, fresh or chilled` | 38,491 | 220 | slaughter axis; no slug left |

## 3. The hen-egg collision — the measurement that turns a plan line into a refusal

The plan pairs `Chickens` **and** `Hen eggs in shell, fresh` under `broilers_poultry`. Measured, it
cannot be done, and one-item-per-slug is only the first of three reasons:

* Element `Production` prints this item in **two units on the same key** — `t` (13,869 rows) and
  `1000 No` (13,941). Of its **14,009** distinct (Area, Year) pairs, **13,801 carry BOTH**. Both map
  to the one governed metric `production_quantity`, and `silver_production`'s natural key is
  (country_key, metric, year) with **no unit**, so every one of those 13,801 keys is a value
  conflict and `_resolve_duplicates_or_raise` stops the Glue run.
* Element `Yield` prints it in `No/An` (eggs per bird) against the crop card's declared
  `yield [kg/ha]`; `Yield/Carcass Weight` prints an EGG weight in `g/An`.
* No second key exists: `broilers_poultry` already carries `Chickens`, and a duplicate YAML key is
  last-wins **silently** — it would replace the flock series, not widen it.

**Do not "fix" this by adding `unit` to the natural key.** That would make the admission pass
silently with two rows per key and disarm the conflict detector for every other user of the table.
The open question is a value-scale decision (which unit the estate serves), not a key.

**The whole-file answer, and it is the strongest form of this finding:** of the **724** distinct
(item, element) pairs in all 301 items, **exactly two** carry more than one unit —
`Hen eggs in shell, fresh || Production` and `Eggs from other birds in shell, fresh, n.e.c. ||
Production`, both `{t, 1000 No}`. So the one-unit-per-(item, element) assumption
`silver_production`'s natural key has always rested on is measured-true for 722 of 724 pairs, has
never been checked before, and breaks on exactly the item the plan asked to admit.

## 4. What this discharges, and what it does not

`silver_production` becomes the estate's **only** source of herd size. `silver_psd` carries
`cattle_beef` / `hogs` / `broilers_poultry` as balance sheets in metric tonnes and **refuses the
head-count axis by name** — `_PSD_UNMAPPED_CODES` declines code 11000 ("Animal Numbers, Cattle",
34,515 rows) and 13000 ("Animal Numbers, Swine", 23,991) because "a head count has no home in an
all-tonnes schema … Reopen by giving the schema a head-count column pair, not by adding a factor".
`silver_production.unit` is a free string with `unit_col: unit` on the card: it **is** that home.

It also puts endpoints under the completion wave's two **WAIVE-UNMEASURABLE** verdicts
(`cattle_cycle_herd_size`, `livestock_feed_demand`), which were adjudicated unmeasurable "for the
single reason that the endpoints did not exist". Discharging a verdict about the instrument is not
the same as re-measuring the association — that re-measure is the honest next step, not a claim
this census makes.

**NOT discharged:** the slaughter axis (`Producing Animals/Slaughtered`, 313,081 rows) and the egg
axis stay dark, by the parks in §2/§3. `Sheep` and `Goats` stay dark for want of a node.
