"""Run the full GAIN backfill pipeline for all non-coffee commodities in sequence.

Each commodity:  crawl → build_manifest → fetch_gain (--skip-existing-s3)

Usage
-----
    python jobs/ingest/run_gain_backfill_all.py
    python jobs/ingest/run_gain_backfill_all.py --commodities wheat corn  # subset
    python jobs/ingest/run_gain_backfill_all.py --dry-run                 # manifest only
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
_PYTHON = sys.executable

# Priority order + crawl parameters for each commodity
COMMODITIES: list[dict] = [
    {
        "name": "wheat",
        "commodity_id": 15,
        "countries": "US,FR,AU,CA,UA,RU,IN,PK,EG,AR,CN,DE,PL,TR",
    },
    {
        "name": "corn",
        "commodity_id": 14,
        "countries": "US,BR,AR,CN,UA,FR,ZA,MX,PH,NG",
    },
    {
        "name": "soybeans",
        "commodity_id": 27,
        "countries": "BR,US,AR,CN,PY,BO,IN,UA",
    },
    {
        "name": "palm_oil",
        "commodity_id": 13023,
        "countries": "MY,ID,TH,CO,NG,CM,GH",
    },
    {
        "name": "sugar",
        "commodity_id": 34,
        "countries": "BR,IN,TH,AU,CO,MX,ID,PH,EC",
    },
    {
        "name": "cotton",
        "commodity_id": 6,
        "countries": "US,IN,CN,BR,AU,PK,UZ",
    },
    {
        "name": "rapeseed",
        "commodity_id": 28,
        "countries": "CA,AU,FR,CN,DE,UA,PL",
    },
    {
        "name": "rice",
        "commodity_id": 16,
        "countries": "TH,VN,IN,CN,US,PK",
    },
    {
        "name": "soybean_oil",
        "commodity_id": 13022,
        "countries": "BR,US,AR,CN",
    },
    {
        "name": "cocoa",
        "commodity_id": None,    # no FAS taxonomy ID; uses dedicated probe
        "countries": "CI,GH,CM,ID,NG,EC,PE",
    },
]


def _run(cmd: list[str], label: str) -> int:
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"  $ {' '.join(cmd)}")
    print(f"{'='*70}")
    result = subprocess.run(cmd, cwd=str(_ROOT))
    return result.returncode


def run_commodity(cfg: dict, dry_run: bool, sleep_seconds: float) -> bool:
    name = cfg["name"]
    crawl_out = _ROOT / "scratch" / "gain" / f"crawl_{name}.jsonl"
    source_name = f"usda_gain_{name}"

    # ── 1. Crawl ──────────────────────────────────────────────────────────
    if name == "cocoa":
        crawl_cmd = [
            _PYTHON, str(_ROOT / "scratch" / "gain" / "probe_gain_cocoa.py"),
            "--output", str(crawl_out),
            "--sleep-listing", "1.5",
            "--sleep-landing", "1.0",
        ]
    else:
        crawl_cmd = [
            _PYTHON, str(_ROOT / "scratch" / "gain" / "probe_gain_http.py"),
            "--commodity-id", str(cfg["commodity_id"]),
            "--target-countries", cfg["countries"],
            "--output", str(crawl_out),
            "--sleep-listing", "1.5",
            "--sleep-landing", "1.0",
        ]

    rc = _run(crawl_cmd, f"[{name}] CRAWL")
    if rc != 0:
        print(f"\n[ERROR] Crawl failed for {name} (exit {rc}) — skipping.")
        return False

    # ── 2. Build manifest ─────────────────────────────────────────────────
    manifest_cmd = [
        _PYTHON, str(_ROOT / "scratch" / "gain" / "build_manifest.py"),
        "--source-name", source_name,
        "--input", str(crawl_out),
    ]
    rc = _run(manifest_cmd, f"[{name}] BUILD MANIFEST")
    if rc != 0:
        print(f"\n[ERROR] Manifest failed for {name} (exit {rc}) — skipping fetch.")
        return False

    if dry_run:
        print(f"\n[{name}] --dry-run: skipping fetch_gain.")
        return True

    # ── 3. Fetch + S3 upload ──────────────────────────────────────────────
    fetch_cmd = [
        _PYTHON, str(_ROOT / "jobs" / "ingest" / "fetch_gain.py"),
        "--source", source_name,
        "--skip-existing-s3",
        "--sleep-seconds", str(sleep_seconds),
    ]
    rc = _run(fetch_cmd, f"[{name}] FETCH + S3")
    if rc != 0:
        print(f"\n[ERROR] Fetch failed for {name} (exit {rc}).")
        return False

    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GAIN backfill for all commodities.")
    parser.add_argument(
        "--commodities",
        nargs="+",
        metavar="NAME",
        default=None,
        help="Run only these commodity names (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Crawl + build manifest only; skip S3 upload.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=2.0,
        help="Sleep between PDF downloads in fetch_gain (default: 2.0).",
    )
    parser.add_argument(
        "--start-from",
        metavar="NAME",
        default=None,
        help="Skip commodities before NAME in the priority list (resume support).",
    )
    args = parser.parse_args()

    commodities = COMMODITIES
    if args.start_from:
        names = [c["name"] for c in commodities]
        if args.start_from not in names:
            print(f"ERROR: --start-from '{args.start_from}' not in commodity list: {names}")
            raise SystemExit(1)
        idx = names.index(args.start_from)
        commodities = commodities[idx:]
        print(f"Resuming from: {args.start_from} ({len(commodities)} remaining)")

    if args.commodities:
        commodities = [c for c in commodities if c["name"] in args.commodities]
        if not commodities:
            print(f"ERROR: none of {args.commodities} matched known commodity names.")
            raise SystemExit(1)

    print(f"GAIN Multi-Commodity Backfill - {len(commodities)} commodities")
    print(f"Order: {', '.join(c['name'] for c in commodities)}")
    if args.dry_run:
        print("Mode: DRY RUN (crawl + manifest only)")
    print()

    results: dict[str, bool] = {}
    t0 = time.time()
    for cfg in commodities:
        t1 = time.time()
        ok = run_commodity(cfg, dry_run=args.dry_run, sleep_seconds=args.sleep_seconds)
        elapsed = time.time() - t1
        results[cfg["name"]] = ok
        status = "[OK]" if ok else "[FAIL]"
        print(f"\n{status} {cfg['name']} completed in {elapsed/60:.1f} min")

    total = time.time() - t0
    print(f"\n{'='*70}")
    print(f"GAIN Backfill Complete - total {total/60:.1f} min")
    print(f"{'='*70}")
    for name, ok in results.items():
        print(f"  {'[OK]' if ok else '[FAIL]'}  {name}")

    failed = [n for n, ok in results.items() if not ok]
    if failed:
        print(f"\nFailed: {failed}")
        print(f"Re-run with: --start-from {failed[0]}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
