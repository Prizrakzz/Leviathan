# MOEX agro indices -- fixture provenance

Captured **2026-08-20** through an **AWS-side probe job**. `iss.moex.com` is reachable ONLY from AWS
(laptop `http=000`, AWS `200`), so these fixtures were assembled on the laptop from the values the
probe measured -- not saved from a live local response.

## Endpoint

```
GET https://iss.moex.com/iss/history/engines/stock/markets/index/securities/{SECID}.json
    ?from=YYYY-MM-DD&till=YYYY-MM-DD[&start=N]
```

## What is MEASURED in these files

| field | status |
|---|---|
| `history.columns` (19 names) | MEASURED, verbatim |
| `BOARDID`, `SECID`, `TRADEDATE`, `CLOSE`, `CURRENCYID` | MEASURED, verbatim |
| every other cell (`SHORTNAME`, `NAME`, `OPEN`, `HIGH`, `LOW`, `VALUE`, `DURATION`, `YIELD`, `DECIMALS`, `CAPITALIZATION`, `DIVISOR`, `TRADINGSESSION`, `VOLUME`, `TRADE_SESSION_DATE`) | **`null` BY CONSTRUCTION** -- the probe reported the column names and the five values above, not the rest. `null` here means "not measured", NOT "ISS served null". |
| `history.cursor` columns `INDEX`/`TOTAL`/`PAGESIZE` | **ASSUMED** -- the probe named the BLOCK (`history.cursor`) but not its columns. These are the standard ISS cursor names. |

## Files

| file | contents |
|---|---|
| `history_WHFOB_2026-08-03_2026-08-19.json` | 13 rows, board `RTSI`, currency `USD` -- the wheat FOB deep-water Black Sea indicative index. Closes 230.1, 229.8, 230.7, 230.4, 230.4, 231.1, 231.5, 231.4, 231.4, 230.2, 229.3, 229.3, 229.3. |
| `history_WHCPT_2026-08-03_2026-08-20.json` | 14 rows, board `AGRO`, currency `RUB` -- the NTB wheat CPT index. Closes 14050, 13991, 13820, 14000, 13792, 13716, 13437, 13437, 13437, 13437, 12491, 11400, 11000, 11000. |
| `history_WH4CPTNOV_empty.json` | The DORMANT index: zero rows, `TOTAL` 0. The security exists; it printed nothing in August 2026. |
| `history_SYNTHETIC_paged_page1.json` / `_page2.json` | **SYNTHETIC.** A two-page cursor walk (`PAGESIZE` 3, `TOTAL` 5) under secid `SYNTH1` -- deliberately not a real MOEX code so nothing here can be mistaken for a measured value. Only the ENVELOPE SHAPE is under test. |
| `history_SYNTHETIC_nocursor_page1.json` | **SYNTHETIC.** The same page with the `history.cursor` block removed, exercising the row-count fallback walk. |

## The four ISS-shape assumptions, each worth ONE cloud-side probe before the backfill fires

1. **The 20th column name.** The probe transcript truncated after `RECALC_DAT`. Not guessed at, not
   present in these fixtures. Harmless -- the parser reads by name -- but re-pin
   `MEASURED_HISTORY_COLUMNS` from the first cloud-side response.
2. **The cursor column names** `INDEX` / `TOTAL` / `PAGESIZE`. If they differ, `next_start` falls
   back to the row-count walk: one extra request per secid, no lost rows.
3. **The page size** (assumed 100). Only sizes the log line and the dry-run estimate; the walk
   advances by the rows it actually received.
4. **`from`/`till` inclusivity** and the ISO date format of `TRADEDATE`. The window is asked wide and
   `TRADEDATE` is read from the payload, so an off-by-one at the window edge costs nothing -- but
   confirm the first landed date matches the first date the venue shows.
