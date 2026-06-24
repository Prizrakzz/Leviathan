# Source Certification Report

Generated: `2026-06-24T18:51:20.771632+00:00`

## Status Counts

| Status | Count |
| --- | ---: |
| `deferred` | 6 |
| `diagnostic_only` | 2 |
| `warn` | 27 |

## Feature Source Coverage

- Feature sources: 20
- Missing source contracts: 0
- Extra source contracts: 15

## Sources

| Source | Status | Rows | Date Range | Issues | Warnings |
| --- | --- | ---: | --- | ---: | ---: |
| `production:faostat` | `warn` | 683152 | 1961 to 2024 | 0 | 2 |
| `weather:chirps` | `warn` |  |  | 0 | 3 |
| `weather:nasa_power` | `warn` |  |  | 0 | 3 |
| `weather:modis_ndvi` | `warn` | 165386 | 2000-02-18 to 2026-04-23 | 0 | 2 |
| `weather:cpc_soil` | `warn` |  |  | 0 | 3 |
| `psd` | `warn` | 163707 | 1960-01-01 to 2027-03-10 | 0 | 2 |
| `wasde` | `warn` | 580871 | 1985-01-11 to 2026-05-12 | 0 | 2 |
| `wap_revisions` | `warn` | 95574 | 2006-12 to 2026-05 | 0 | 2 |
| `nass_annual` | `warn` | 14409 | 1866 to 2026 | 0 | 2 |
| `nass_crop_progress` | `warn` | 141714 | 1979-04-22 to 2026-05-17 | 0 | 2 |
| `nass_citrus` | `warn` | 2450 | 2004-01-12 to 2025-07-11 | 0 | 2 |
| `esr` | `warn` |  |  | 0 | 4 |
| `fgis` | `warn` | 111444 | 1983-01-03 to 2026-01-04 | 0 | 2 |
| `sagis_cec` | `warn` | 2071 | 1999-10-20 to 2026-05-07 | 0 | 2 |
| `sagis_deliveries` | `warn` | 2668 |  to 9 - 15 Sep | 0 | 2 |
| `sagis_weekly_exports` | `warn` | 1204 | 01 Apr - 07 Apr 2023 to 9 - 15 Sep | 0 | 2 |
| `conab` | `warn` | 659 | 2023 to 2026 | 0 | 2 |
| `fnc_colombia_monthly` | `warn` | 1360 | 1913-01-01 to 2026-04-01 | 0 | 2 |
| `fnc_colombia_area_department` | `deferred` | 492 | 2002 to 2025 | 0 | 3 |
| `fnc_colombia_exports_port_type` | `deferred` | 2147 | 2017-01-01 to 2026-03-01 | 0 | 3 |
| `mpob` | `warn` | 113 | 2016-12-01 to 2026-04-01 | 0 | 2 |
| `mpoc_exports_by_country` | `deferred` | 1923 | 2008 to 2023 | 0 | 2 |
| `mpoc_stock_comparison` | `deferred` | 311 | 2025 to 2026 | 0 | 2 |
| `mpoc_trade_stats_monthly` | `deferred` | 192 | 2008 to 2023 | 0 | 2 |
| `unica_biweekly` | `warn` | 305 | 2012-04-16 to 2026-02-01 | 0 | 2 |
| `unica_annual_state` | `deferred` | 1107 | 1980_1981 to 2020_2021 | 0 | 2 |
| `icco_cocoa` | `warn` | 15 | 2008-02-28 to 2026-02-27 | 0 | 2 |
| `ams_cotton_quality` | `warn` | 27 | 1986 to 2025 | 0 | 3 |
| `pink_sheet` | `warn` | 796 | 1960-01-01 00:00:00.000 to 2026-04-01 00:00:00.000 | 0 | 2 |
| `fred_fx` | `warn` | 5508 | 2004-12-31 to 2026-06-04 | 0 | 2 |
| `futures_prices` | `diagnostic_only` | 78268 | 1999-09-14 00:00:00.000 to 2026-06-05 00:00:00.000 | 0 | 3 |
| `cot` | `diagnostic_only` | 10806 | 2006-06-13 to 2025-12-30 | 0 | 3 |
| `food_cpi` | `warn` | 264 | 1960 to 2025 | 0 | 2 |
| `oni` | `warn` | 915 | 1950 to 2026 | 0 | 2 |
| `iod` | `warn` | 1873 | 1870-01-01 00:00:00.000 to 2025-12-01 00:00:00.000 | 0 | 2 |

## Next

After this phase is accepted, proceed to Phase 3: preserve and clean the current v2 scratch work before versioning broad legacy gold.
