"""W-1 / P-E (projection wave, 2026-08-25): give white_sugar the Brazil cane-belt weather HISTORY.

THE GAP THIS CLOSES. geography.yaml has listed white_sugar under brazil for weeks, but
configs/geographies/white_sugar_regions.yaml carried no Brazil cells until 2026-08-25 -- so the belt's
frost driver ("frost in southern Brazil cane areas") could never fire on the white contract, and the
census waiver said so. The daily fetch does NOT self-heal history: a geography edit yields
FORWARD-ONLY rows, and _frost_flag needs no baseline, so without this step the white_sugar frost
series would have shipped with one month of history and nothing saying so.

THE MECHANISM. raw_sugar's five br_sugar_* cells are BYTE-IDENTICAL coordinates to the cells the
white_sugar geography just gained (that identity is the requirement -- see the geography file's W-1
comment). Their 1981..2026 observations already sit in canonical silver under
silver/weather/source={nasa_power,chirps}/commodity=raw_sugar/year=YYYY/. This script re-partitions
those rows into the commodity=white_sugar objects: ZERO new NASA POWER or CHIRPS calls, zero new
observations -- the same bytes under a second commodity home, exactly like raw_sugar and white_sugar
sharing a CHIRPS tile in the first place.

SAFETY POSTURE (the Wave-R OOM lesson: back up BEFORE touching canonical):
  1. BACKUP: every white_sugar object is copied to _backups/w1_white_sugar_20260825/ first.
  2. IDEMPOTENT: a year whose white frame already carries any br_sugar_ region is SKIPPED (re-runs
     converge; a partial earlier run cannot double-append).
  3. VERIFIED: per (source, year), the rewritten object must hold exactly old_white + raw_brazil
     rows, and the region set must gain exactly the five br_sugar_ cells. Any mismatch RAISES before
     the next object is touched.
  4. CHIRPS carries an in-file `commodity` column -- restamped to white_sugar on the copied rows
     (nasa_power carries none; verified against live schemas 2026-08-25).

Usage:
    python jobs/utils/repartition_white_sugar_brazil_weather.py [--dry-run]
"""
from __future__ import annotations

import argparse
import io
import sys

import boto3
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

BUCKET = "leviathan-dev-shahem-001"
SOURCES = ("nasa_power", "chirps")
YEARS = range(1981, 2027)
BR_REGIONS = ("br_sugar_sao_paulo", "br_sugar_goias", "br_sugar_minas_gerais",
              "br_sugar_parana", "br_sugar_mato_grosso_do_sul")
BACKUP_PREFIX = "_backups/w1_white_sugar_20260825/"


def _key(src: str, com: str, year: int) -> str:
    return f"silver/weather/source={src}/commodity={com}/year={year}/part-000.parquet"


def _read(s3, key: str) -> pa.Table | None:
    try:
        return pq.read_table(io.BytesIO(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()))
    except s3.exceptions.NoSuchKey:
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    s3 = boto3.client("s3")
    merged = skipped = missing = 0
    for src in SOURCES:
        for year in YEARS:
            wkey, rkey = _key(src, "white_sugar", year), _key(src, "raw_sugar", year)
            white, raw = _read(s3, wkey), _read(s3, rkey)
            if white is None or raw is None:
                # a year one side lacks entirely (e.g. the fetch never produced it) is reported,
                # never invented -- the gold re-run's per-basin cell asserts are the downstream check
                print(f"MISSING {src} {year}: white={white is not None} raw={raw is not None}")
                missing += 1
                continue
            have = set(pc.unique(white["region"]).to_pylist())
            if have & set(BR_REGIONS):
                skipped += 1
                continue                                  # idempotency: already merged
            br = raw.filter(pc.is_in(raw["region"], value_set=pa.array(BR_REGIONS)))
            if br.num_rows == 0:
                print(f"MISSING {src} {year}: raw_sugar object holds no br_sugar_ rows")
                missing += 1
                continue
            if "commodity" in br.schema.names:            # chirps: restamp the in-file commodity
                idx = br.schema.get_field_index("commodity")
                br = br.set_column(idx, "commodity",
                                   pa.array(["white_sugar"] * br.num_rows, type=br.schema.field(idx).type))
            out = pa.concat_tables([white, br], promote_options="default")
            want_rows = white.num_rows + br.num_rows
            assert out.num_rows == want_rows
            # assert against the cells THIS source-year actually holds -- early years carry fewer
            # br cells (coverage grew), and inventing the missing ones would be fabrication
            br_have = set(pc.unique(br["region"]).to_pylist())
            got_regions = set(pc.unique(out["region"]).to_pylist())
            assert br_have <= set(BR_REGIONS), f"{src} {year}: unexpected raw regions {br_have - set(BR_REGIONS)}"
            assert got_regions == have | br_have, f"{src} {year}: region set mismatch"
            if br_have != set(BR_REGIONS):
                print(f"NOTE {src} {year}: only {len(br_have)}/5 br cells at source")
            if a.dry_run:
                print(f"DRY {src} {year}: +{br.num_rows} rows -> {want_rows}")
                merged += 1
                continue
            s3.copy_object(Bucket=BUCKET, Key=BACKUP_PREFIX + wkey,
                           CopySource={"Bucket": BUCKET, "Key": wkey})
            buf = io.BytesIO()
            pq.write_table(out, buf, compression="snappy")
            s3.put_object(Bucket=BUCKET, Key=wkey, Body=buf.getvalue())
            back = _read(s3, wkey)
            assert back is not None and back.num_rows == want_rows, f"{src} {year}: readback mismatch"
            merged += 1
            print(f"MERGED {src} {year}: +{br.num_rows} -> {want_rows}")
    print(f"DONE merged={merged} skipped={skipped} missing={missing}")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
