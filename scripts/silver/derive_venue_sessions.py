#!/usr/bin/env python
"""LANE A / A-1b -- CANDIDATE no-settlement dates for configs/silver/venue_holidays.yaml.

READ-ONLY. No write, no Athena, no Glue: single-column parquet reads off the canonical
silver_futures_eod prefix, the census discipline. It RESOLVES NOTHING -- it prints CANDIDATES and
hands every one of them to a human.

WHAT IT PRINTS. For one databento dataset and a range of years: the weekday dates in each year on
which ALL of that dataset's roots published ZERO canonical rows. A dataset-wide zero is what a
venue closure looks like from the tape; a single root at zero is a thin book or a dead leg and is
NOT a candidate, which is why the intersection is taken across roots rather than the union.

WHY THERE IS NO FREQUENCY FLOOR, AND WHY THAT IS DELIBERATE. It is tempting to rank candidates by
"absent in >= N of the banked years" and print only those. That screen DENIES THE TAIL: a
once-in-a-decade closure -- a state funeral, a national day of mourning, an exchange outage day the
venue then declared a non-settlement day -- appears in exactly one year and is exactly the entry a
recurrence screen would drop. This estate's law is that frequency screens are only for
hypothesis-free candidate generation, and that a NAMED mechanism needs a narrating pin, not a
count. So every candidate is printed, the recurrence count is shown as INFORMATION beside it, and
the human decides. The rule for the human is short:

  * a candidate recurring on a describable rule (e.g. "the last Monday of August") is a holiday
    candidate -- confirm it against the venue's PUBLISHED calendar, then write it with basis
    `published+tape`;
  * a candidate appearing in exactly one year may be a VENDOR OUTAGE rather than a closure --
    confirm it against the published calendar before writing anything;
  * a candidate that cannot be confirmed is LEFT OUT. An unwritten candidate is carried by the
    one-holiday margin; a wrongly written one costs a day of detector sensitivity.

USAGE
    python scripts/silver/derive_venue_sessions.py --dataset IFEU.IMPACT --years 2019-2025
    python scripts/silver/derive_venue_sessions.py --dataset GLBX.MDP3 --years 2024-2025 \
        --bucket leviathan-dev-shahem-001

COST: 16 slugs x <= 17 years of single-column parquet reads, well under 1 GB -- under $0.05 of
egress from a laptop and $0 in-VPC.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from leviathan.transforms.raw_to_bronze.databento_eod import ROOT_MAP  # noqa: E402

DATASETS = sorted({ds for ds, _slug in ROOT_MAP.values()})


def parse_years(text: str) -> list[int]:
    """``'2019-2025'`` or ``'2024'`` or ``'2019,2021-2022'`` -> a sorted list of years."""
    years: set[int] = set()
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            lo_i, hi_i = int(lo), int(hi)
            if hi_i < lo_i:
                raise ValueError(f"{part!r} runs backwards")
            years.update(range(lo_i, hi_i + 1))
        else:
            years.add(int(part))
    if not years:
        raise ValueError("no years requested")
    return sorted(years)


def weekdays_in(year: int) -> list[str]:
    """Every Mon-Fri ISO date in ``year`` -- the same domain the session floor counts over."""
    out: list[str] = []
    day = date(year, 1, 1)
    while day.year == year:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def candidate_dates(sessions_by_year: dict[int, set[str]],
                    years: list[int]) -> dict[str, list[int]]:
    """``{candidate ISO date: [years it was absent in]}`` -- EVERY candidate, no floor.

    ``sessions_by_year`` maps a year to the ISO dates on which the dataset published at least one
    canonical row for at least one of its roots. A weekday of that year not in that set is a
    candidate. There is deliberately no minimum recurrence: see the module docstring. Years with NO
    banked sessions at all are skipped entirely -- an unbanked year would otherwise nominate every
    weekday in it, which is noise, not a candidate.
    """
    out: dict[str, list[int]] = {}
    for year in years:
        seen = sessions_by_year.get(year) or set()
        if not seen:
            continue
        for day in weekdays_in(year):
            if day not in seen:
                out.setdefault(day, []).append(year)
    return {day: sorted(set(hits)) for day, hits in sorted(out.items())}


def _sessions_from_s3(bucket: str, dataset: str, years: list[int], region: str) -> dict[int, set]:
    """Trade dates present in canonical silver for this dataset's slugs, per year.

    Imported lazily and touched only when the script is actually run against a bucket, so the pure
    helpers above stay importable (and testable) with no AWS in the room at all.
    """
    import io

    import pandas as pd
    from leviathan.silver.registry import load_registry
    from leviathan.storage.s3 import get_thread_local_s3_client

    slugs = sorted({slug for root, (ds, slug) in ROOT_MAP.items() if ds == dataset})
    # A-R5. This read `load_registry()["silver_futures_eod"]` and died on the first invocation that
    # named a bucket: SilverRegistry is a FROZEN DATACLASS with .table(name) and no __getitem__
    # (src/leviathan/silver/registry.py), so every real run raised
    # `TypeError: 'SilverRegistry' object is not subscriptable` here, BEFORE the first S3 call. The
    # three pins this script had all exercised parse_years / weekdays_in / candidate_dates, and the
    # recorded --help and missing-bucket runs both returned above this line -- the measurement
    # covered everything except the part that runs. _sessions_from_s3 now has its own end-to-end
    # pin against a fake pager (tests/unit/silver/test_venue_holidays.py::TestDeriveVenueSessions).
    table = load_registry().table("silver_futures_eod")
    root_prefix = str(table["s3_root"]).split("/", 3)[-1].rstrip("/")
    s3 = get_thread_local_s3_client(region)
    by_year: dict[int, set] = {}
    for slug in slugs:
        for year in years:
            prefix = f"{root_prefix}/leviathan_slug={slug}/trade_year={year}/"
            token = None
            while True:
                kw = {"Bucket": bucket, "Prefix": prefix}
                if token:
                    kw["ContinuationToken"] = token
                page = s3.list_objects_v2(**kw)
                for obj in page.get("Contents", []) or []:
                    if not obj["Key"].endswith(".parquet"):
                        continue
                    body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
                    col = pd.read_parquet(io.BytesIO(body), columns=["trade_date"])
                    days = pd.to_datetime(col["trade_date"]).dt.strftime("%Y-%m-%d")
                    by_year.setdefault(year, set()).update(days.tolist())
                if not page.get("IsTruncated"):
                    break
                token = page.get("NextContinuationToken")
    return by_year


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", required=True, choices=DATASETS)
    ap.add_argument("--years", required=True,
                    help="a year, a range ('2019-2025'), or a comma list")
    ap.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET", ""))
    ap.add_argument("--aws-region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = ap.parse_args(argv)

    years = parse_years(args.years)
    if not args.bucket:
        print("ERROR: --bucket (or LEVIATHAN_BUCKET) is required -- this script reads the banked "
              "canonical tape and asserts nothing without it")
        return 2
    sessions = _sessions_from_s3(args.bucket, args.dataset, years, args.aws_region)
    banked = sorted(y for y in years if sessions.get(y))
    unbanked = sorted(y for y in years if not sessions.get(y))
    cands = candidate_dates(sessions, years)

    print(f"dataset      {args.dataset}")
    print(f"roots        {sorted(r for r, (ds, _s) in ROOT_MAP.items() if ds == args.dataset)}")
    print(f"years banked {banked}")
    if unbanked:
        print(f"years EMPTY  {unbanked}  (skipped: an unbanked year nominates every weekday)")
    print(f"candidates   {len(cands)} weekday date(s) with ZERO rows across ALL roots")
    print("")
    print("NOTHING BELOW IS AN ANSWER. Confirm each against the venue's published calendar, then")
    print("write it into configs/silver/venue_holidays.yaml with a NAME and a BASIS, or leave it")
    print("out. There is no frequency floor here on purpose: a once-in-a-decade closure appears in")
    print("exactly one year, and a recurrence screen would deny exactly that tail.")
    print("")
    print(f"{'candidate':<12} {'n_years':>7}  years absent")
    for day, hits in cands.items():
        print(f"{day:<12} {len(hits):>7}  {hits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
