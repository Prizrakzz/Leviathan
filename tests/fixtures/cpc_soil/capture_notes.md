# CPC SOIL MOISTURE -- LIVE CAPTURE NOTES, 2026-09-11 ~09:20Z (plain HTTPS GET/HEAD)

Captured live from the public NOAA CPC Leaky Bucket FTP-over-HTTPS root while repairing the
`cpc-soil-to-raw` 404 (the trailing-month self-heal reaching for a current-year annual tarball
that does not exist). Everything below is MEASURED, not inferred.

Base: `https://ftp.cpc.ncep.noaa.gov/wd51yf/global_daily/`

## The two directories have DISJOINT domains

| directory   | carries                                  | measured |
|-------------|------------------------------------------|----------|
| `clim/`     | annual tarballs for **closed years only** | `w.2000.tif.tar.gz` .. `w.2025.tif.tar.gz` plus `w.40ym.tif.tar.gz` -- 27 objects, nothing for 2026 |
| `GeoTIFF/`  | the **current year's** dailies            | 1,512 anchors = 6 variables (e, p, r, swe, t, w) x 252 days, every one of them 2026 |

There is no day for which both paths exist, so for the current year the daily GeoTIFF is the ONLY
source and for a closed year the tarball is the only source.

HEAD results at 09:30Z on 2026-09-11:

    clim/w.2026.tif.tar.gz        -> 404
    clim/w.2025.tif.tar.gz        -> 200   Content-Length 86,244,454   Last-Modified Tue, 03 Mar 2026 23:03:20 GMT
    GeoTIFF/w.20260909.tif        -> 200   Content-Length    874,976   Last-Modified Thu, 10 Sep 2026 17:53:44 GMT
    GeoTIFF/w.20260910.tif        -> 404   (day 09-10 had not published yet)

## The GeoTIFF directory is NOT a rolling window within the calendar year

`w` runs `w.20260101.tif` .. `w.20260909.tif` -- 252 consecutive days, **no interior gap**. Nothing
rolls off within the year. The 2026-08-22 comment in `cpc_soil_to_raw_task.py` that justified the
current-year tarball fallback ("the live dir is a ROLLING window") is measurably false; the daily
path already re-attempts every listed day on every run, so a within-year raw hole self-heals from
the daily path alone.

## Publication lag = 2 days at the 08:00Z fire

CPC publishes day D at about 17:53Z on D+1 (see the `Last-Modified` above, and `w.20260910.tif`
still 404 at 09:30Z on 09-11). The `weather_daily` DAG fires at 08:00Z, so at run time on day T the
newest published day is T-2, never T-1. Confirmed across sixteen consecutive raw objects:
`date=20260830` ingested 09-01, `20260901` -> 09-03, `20260905` -> 09-07, `20260909` -> 09-11.

## Payload equivalence across the seam

The per-day artifact is identical whichever path produced it -- both key on the same
`{v}.YYYYMMDD.tif` basename, and a single-band 720x360 EPSG:4326 GeoTIFF is 874,976 bytes either
way: raw `date=20251231` (tarball-sourced, `source_url` = `clim/w.2025.tif.tar.gz`) = 874,976 B;
raw `date=20260909` (daily-sourced) = 874,976 B; live `GeoTIFF/w.20260909.tif` Content-Length =
874,976.

## The fixture files beside this note

- `geotiff_index.sample.html` (2,770 B, 31 lines) -- a VERBATIM trim of the live `GeoTIFF/` index
  (199,623 B). Header and footer kept whole; the 1,512 file rows cut to 17 real rows chosen to
  carry every case the parser must get right: two variables (`e` x 3 days proves the variable
  filter, `w` x 14), a month boundary (`w.20260829` .. `w.20260901`), and the publication tip
  (`w.20260909`). Every retained byte is as served -- no line was edited or synthesised. Cases the
  live index cannot supply (a foreign year, a malformed stem) are built inline in the tests and
  labelled there as synthetic.
- `clim_index.sample.html` (4,236 B) -- the live `clim/` index, kept WHOLE. It is the evidence that
  clim/ stops at 2025.

No GeoTIFF bytes were downloaded for these fixtures: the existing deck already synthesises
single-band GeoTIFFs in memory via `rasterio.MemoryFile` and tarballs via `tarfile`
(`tests/unit/test_cpc_soil_ingestion.py`).
