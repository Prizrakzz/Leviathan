# EEX dry-bulk freight -- fixture capture notes

Every file in this directory was captured LIVE from the Amman laptop on **2026-08-20** through the
producer's own code path (`jobs/ingest/fetch_eex_freight.py`: `post_scope` -> `parse_scope` ->
`select_instruments` -> `fetch_symbol` -> `build_observation` -> `canonical_observation_bytes`), so
the fixtures are exactly what the job lands, not a hand-written approximation. **157 HTTP calls,
1.05 s apart, single-threaded.** Nothing was written to S3.

This is the only capture that will ever exist for these dates. The endpoint serves a rolling
~5-trading-day settlement window and no history, so **these bytes are unreproducible** -- if a test
needs a different date, it needs a new live capture on a new day, not a re-fetch of these.

## Request recipe (all three headers are mandatory)

```
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36
Origin:     https://www.eex.com
Referer:    https://www.eex.com/
```

A call without `Referer` returns 403 (recon 1d-iv, re-confirmed 2026-08-20).

## Files

| file | what it is |
|---|---|
| `scope_freight_20260820.json` | the VERBATIM `POST https://api.eex-group.com/pub/customise-widget/filter-data-with-scope?data=<b64>` response for `commodity=FREIGHT`. **HTTP 201** (not 200 -- this POST-as-query idiom answers Created). 19-column header, **1,123 instrument rows, 23 products**. |
| `chart_eod_{SYMBOL}_202608.json` | the VERBATIM `GET /pub/market-data/chart/eod` wire response for one (symbol, front maturity), window `2026-07-30 .. 2026-08-20`. |
| `settlements_{SYMBOL}_{DATE}.json` | the ASSEMBLED raw object -- byte-identical to what `fetch_eex_freight` would land at `raw/production/source=eex_freight/symbol={SYMBOL}/trade_date={DATE}/settlements.json`. |

## What the window actually contained

Requested `startDate=2026-07-30&endDate=2026-08-20`. Every symbol returned **exactly five**
`settlPx` points, and the same five for all of them:

    2026-08-13, 2026-08-14, 2026-08-17, 2026-08-18, 2026-08-19

Note what is NOT there: **2026-08-20**, the day of capture. EEX settles ~18:30 CET and the probe ran
~17:20 UTC; the envelope's `lastUpdate` field read `2026-08-20` while the newest settlement was
`2026-08-19`. That is why the producer never asserts "today" and lands only the dates the payload
names.

Note also what the SAME responses carry on the `volume` series: points back to **2026-07-30**, ~15
sessions further than `settlPx`. The five-day ceiling is on the settlement series specifically, and
it does not move when the request window widens (recon measured `startDate=2025-01-01` -> still 5).

## The three symbols, and why these three

| symbol | product / route | maturities >= 202608 | settled | currency | uOM | front settle 2026-08-19 |
|---|---|---|---|---|---|---|
| `P5TC` | Panamax 5TC | 84 | **84 / 84** | USD | `DAYS` | 202608 = **19,671** (USD/day) |
| `C3EM` | Capesize C3 | 36 | **36 / 36** | USD | **`TN`** | 202608 = **35.71** (USD/tonne) |
| `LNG1` | LNG Route BLNG1 174 | 36 | **36 / 36** | USD | `DAYS` | 202608 = **58,375** (USD/day) |

* **P5TC** is the flagship grain-freight instrument and proves the density claim the transform's
  completeness check rests on: **every listed maturity settles every trading day**, out to 203307,
  84 of 84, on all five window days. The far months are illiquid (16 of 84 traded on 2026-08-19)
  but they are all *settled*.
* **C3EM** is the unit counter-example. It is a Capesize **voyage** route quoted in **USD per
  tonne**, not USD per day. Its front settlement is `35.71` beside P5TC's `19671`. A schema that
  hard-coded "USD/day for time-charter averages" -- which is what the lane started from -- would
  file that 35.71 as a daily hire rate with nothing downstream able to detect it. Three of the
  thirteen dry-bulk futures are `TN`: **C3EM, C5EM, C7EM**.
* **LNG1** is the written non-dry-bulk refusal. It is fetched into raw (source fidelity on a source
  with no history endpoint) and dropped by the silver transform with a log line.

## `volume` and `lotSize` are TWO UNITS, and on most contracts they look like one

This is the trap in this leg, and `chart_eod_C3EM_202608.json` is the only file here that catches it.

The `/chart/eod` envelope carries three series: `settlPx`, `volume` and `lotSize`. On every `DAYS`
contract the last two are numerically **identical** point for point (a lot is one day), so twelve of
the sixteen symbols give a parser no reason to think they mean different things. They do:

    chart_eod_C3EM_202608.json   volume  [["2026-08-06", 100000]]
                                 lotSize [["2026-08-06",    100]]

A factor of 1,000 -- the C3 contract's 1,000-tonne lot. `volume` is the traded quantity in the
contract's own **uOM** (tonnes here, days on a charter average); `lotSize` is the same quantity in
**lots**.

That is not an inference from one data point. It is what the venue's own widget does with them
(`eds.eex-group.com/widgets/pub/lib/v1/templates/customized-solution/marketDataHubTemplate.html`):

```js
if (obj.uOM !== undefined && obj.uOM !== '') { ...chart.volumeUnit = obj.uOM; }
...volumeSeriesYaxisTitleOptions.text = ...chart.volumeUnit;   // the `volume` axis is titled uOM
```

with a `lotsSwitchLabel: 'Lots'` toggle that swaps the `lotSize` series in and re-titles the axis.

So bronze carries `volume_uom` (from `volume`) and `volume_lots` (from `lotSize`), and silver
publishes only `volume_lots`, the one volume unit that means the same thing on every contract.

**Where the divergent point is NOT:** `2026-08-06` is outside the settlement window
(`2026-08-13..2026-08-19`), so it appears in no `settlements_*.json`. The assembled documents show
`volume_uom == volume_lots` on all 780 of their settlement rows. The wire fixture is the evidence;
keep it.

Volume is also genuinely sparse -- only maturities that TRADED on a given day carry a point (16 of
84 on P5TC 2026-08-19, and the front month 202608 was not one of them; C3EM traded on none of the
five days). Those nulls are real absences and are kept NULL, never synthesised as 0.0 (INV-4).

## Universe census (from `scope_freight_20260820.json`)

1,123 `commodity=FREIGHT` instruments, 23 products:

* **16 futures** (`pricing=F`): 13 dry bulk + 3 LNG Route.
  * Capesize: `C3EM` (C3), `C5EM` (C5), `C7EM` (C7), `CPTM` (5TC), `C5TM` (5TC 182)
  * Panamax: `P5TC` (5TC), `PE8M` (P1E_82), `PF8M` (P2E_82), `PG8M` (P3E_82), `PREM` (P6)
  * Supramax: `S11F` (11TC), `SPTM` (10TC)
  * Handysize: `H7TC` (7TC)
  * LNG Route: `LNG1`, `LNG2`, `LNG3` (BLNG1/2/3 174)
* **7 options** (`pricing=O`, 317 instrument rows): `O5TM`, `OC05`, `OCPM`, `OH7C`, `OP5M`,
  `OPSM`, `OS11` -- refused at the fetch boundary.

Every one of the 1,123 rows has `maturityType = Month` and `area = Freight`.

**Expired maturities are still listed.** `P5TC maturity=202607` was in the scope response on
2026-08-20 and `chart/eod` answered it with HTTP 200 and an all-null envelope
(`lastUpdate: null, currency: null, uOM: null, longName: ""`) and empty series. That is why the
producer filters by `--lookback-months` instead of probing, and why an empty series is a skip rather
than an error.

## Licence posture (unchanged from the recon; do not re-derive it here)

EEX Group DataSource is a licensed commercial product and its General Conditions PDF could not be
text-extracted from this machine (**PARKED-FOR-HOME**, recon 1d-iv). Until those clauses are read,
this leg is **fetchable for internal signal, not clearly redistributable** -- the same posture the
already-live Euronext leg operates under. The `raw_meta` companion carries that note with every
landed object.
