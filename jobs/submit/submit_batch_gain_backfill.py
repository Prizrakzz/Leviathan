"""Submit GAIN backfill as 10 parallel AWS Batch Fargate tasks (one per commodity).

All 10 run concurrently — crawl + manifest + S3 upload inside each container.

Usage
-----
    python jobs/submit/submit_batch_gain_backfill.py
    python jobs/submit/submit_batch_gain_backfill.py --commodities wheat corn soybeans
    python jobs/submit/submit_batch_gain_backfill.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import boto3

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_gain_backfill")

# ---------------------------------------------------------------------------
# Commodity definitions
# ---------------------------------------------------------------------------

COMMODITIES: list[dict] = [
    {"name": "wheat",       "commodity_id": "15",    "countries": "FR,AU,CA,UA,RU,IN,PK,EG,AR,CN,DE,PL,TR"},
    {"name": "corn",        "commodity_id": "14",    "countries": "BR,AR,CN,UA,FR,ZA,MX,PH,NG"},
    # Historical depth: commodity IDs 15/14 only tag recent uploads; title-filter crawl recovers 2005-2025
    {"name": "wheat_historical", "source_name": "wheat", "commodity_id": None, "countries": "FR,AU,CA,UA,RU,IN,PK,EG,AR,CN,DE,PL,TR", "title_filter": "grain and feed annual", "start_year": 2000, "end_year": 2026},
    {"name": "corn_historical",  "source_name": "corn",  "commodity_id": None, "countries": "BR,AR,CN,UA,FR,ZA,MX,PH,NG",           "title_filter": "grain and feed annual", "start_year": 2000, "end_year": 2026},
    {"name": "soybeans",    "commodity_id": "27",    "countries": "BR,AR,CN,PY,BO,IN,UA"},
    # Historical depth: date-scoped crawl 2000-2026 recovers all years
    {"name": "soybeans_historical",     "source_name": "soybeans",    "commodity_id": None, "countries": "BR,AR,CN,PY,BO,IN,UA",                            "title_filter": "oilseeds and products annual", "start_year": 2000, "end_year": 2026},
    {"name": "soybean_oil_historical",  "source_name": "soybean_oil", "commodity_id": None, "countries": "AR,BR,US,CN,IN,ID,PH,VN,PY,MY,MX,TH,DE,NL",     "title_filter": "oilseeds and products annual", "start_year": 2000, "end_year": 2026},
    {"name": "soybean_meal_historical", "source_name": "soybean_meal","commodity_id": None, "countries": "US,AR,BR,CN,IN,ID,PH,VN,TH,MX,DE,NL,PY,BD,KR,JP","title_filter": "oilseeds and products annual", "start_year": 2000, "end_year": 2026},
    {"name": "palm_oil",    "commodity_id": "13023", "countries": "ID,TH,CO,NG,CM,GH"},
    # Malaysia KL posts under commodity_id=27 (oilseeds) — NOT under 13023; probe confirmed this
    {"name": "palm_oil_my", "source_name": "palm_oil", "commodity_id": "27", "countries": "MY", "title_filter": "oilseeds"},
    # Historical depth: commodity_id=13023 only tags recent uploads; title-filter crawl recovers 2000-2026
    {"name": "palm_oil_historical", "source_name": "palm_oil", "commodity_id": None, "countries": "ID,MY,TH,CO,NG,CM,GH", "title_filter": "oilseeds and products annual", "start_year": 2000, "end_year": 2026},
    {"name": "sugar",       "commodity_id": "34",    "countries": "BR,IN,TH,AU,CO,MX,ID,PH,EC"},
    {"name": "cotton",      "commodity_id": "6",     "countries": "US,IN,CN,BR,AU,PK,UZ"},
    {"name": "rapeseed",    "commodity_id": "28",    "countries": "CA,AU,FR,CN,DE,UA,PL"},
    # Historical depth: date-scoped crawl 2000-2026 recovers all years
    {"name": "rapeseed_historical", "source_name": "rapeseed", "commodity_id": None, "countries": "CA,AU,FR,CN,DE,UA,PL", "title_filter": "oilseeds and products annual", "start_year": 2000, "end_year": 2026},
    {"name": "rice",        "commodity_id": "16",    "countries": "TH,VN,IN,CN,ID,PK"},
    # Historical depth: date-scoped crawl 2000-2026 recovers all years
    {"name": "rice_historical", "source_name": "rice", "commodity_id": None, "countries": "TH,VN,IN,CN,ID,PK", "title_filter": "grain and feed annual", "start_year": 2000, "end_year": 2026},
    # Soybean oil: commodity_id 13022 is too granular (rarely tagged); use general oilseeds ID 27 + title filter
    {"name": "soybean_oil",  "commodity_id": "27", "countries": "AR,BR,US,CN,IN,ID,PH,VN,PY,MY,MX,TH,DE,NL,BD,PK,EG,CO,PE", "title_filter": "oilseeds"},
    # Soybean meal: commodity_id 13021 is too granular (rarely tagged); use general oilseeds ID 27 + title filter
    {"name": "soybean_meal", "commodity_id": "27", "countries": "US,AR,BR,CN,IN,ID,PH,VN,TH,MX,DE,NL,PY,BD,KR,JP,EG,CO",   "title_filter": "oilseeds"},
    # OJ / citrus: 13014 is wrong (generic catchall) — use title-filter on all GAIN reports
    {"name": "orange_juice", "commodity_id": None,    "countries": "BR,US,MX,ZA,AR,TR,EG,IN,CN,ES,NG,AU,PK", "title_filter": "citrus", "max_empty_pages": 2000},
    # Cocoa has no FAS taxonomy ID — uses title-filter; needs many pages to find scattered reports
    {"name": "cocoa",        "commodity_id": None,    "countries": "CI,GH,CM,NG,ID,EC,PE,BR,DO,MX,IN,DE,NL", "title_filter": "cocoa", "max_empty_pages": 2000},
    # Coffee: no FAS taxonomy ID — title-filter across 14 origin countries (matches fetch_gain_coffee.py)
    {"name": "coffee",            "commodity_id": None, "countries": "BR,CO,VN,ET,ID,HN,GT,PE,MX,UG,IN,TZ,KE,CI", "title_filter": "coffee annual", "max_empty_pages": 2000},
    {"name": "coffee_historical", "source_name": "coffee", "commodity_id": None, "countries": "BR,CO,VN,ET,ID,HN,GT,PE,MX,UG,IN,TZ,KE,CI", "title_filter": "coffee annual", "start_year": 2000, "end_year": 2026},
    # Phase 3: cocoa historical — title-filter date-scoped crawl 2000–2026
    # countries match the regular cocoa job; DE/NL omitted (processors, not origin attachés)
    {"name": "cocoa_historical", "source_name": "cocoa", "commodity_id": None,
     "countries": "CI,GH,CM,NG,ID,EC,PE,BR,DO,MX,IN",
     "title_filter": "cocoa annual", "start_year": 2000, "end_year": 2026},
    # Phase 3: orange juice (citrus) historical — title-filter date-scoped crawl 2000–2026
    {"name": "orange_juice_historical", "source_name": "orange_juice", "commodity_id": None,
     "countries": "BR,US,MX,ZA,AR,TR,EG,IN,CN,ES,NG,AU,PK",
     "title_filter": "citrus annual", "start_year": 2000, "end_year": 2026},
    # Phase 4: Grain and Feed Update — within-year monthly/quarterly grain updates
    # Year-split into two jobs (2000–2012 / 2013–2026) to halve crawl time (~33 min each)
    {"name": "grain_monthly_a", "source_name": "grain_monthly", "commodity_id": None,
     "countries": "US,FR,AU,CA,UA,RU,IN,PK,EG,AR,CN,DE,PL,TR,BR,ZA,TH,VN,PH,NG",
     "title_filter": "grain and feed update", "start_year": 2000, "end_year": 2012, "workers": 8},
    {"name": "grain_monthly_b", "source_name": "grain_monthly", "commodity_id": None,
     "countries": "US,FR,AU,CA,UA,RU,IN,PK,EG,AR,CN,DE,PL,TR,BR,ZA,TH,VN,PH,NG",
     "title_filter": "grain and feed update", "start_year": 2013, "end_year": 2026, "workers": 8},
    # Phase 4: Oilseeds and Products Semi-Annual
    {"name": "oilseeds_semiannual", "source_name": "oilseeds_semiannual", "commodity_id": None,
     "countries": "BR,AR,US,CN,IN,ID,MY,TH,PY,BO,UA,CA,AU,FR,DE,NL",
     "title_filter": "oilseeds and products semi-annual", "start_year": 2005, "end_year": 2026, "workers": 8},
    # Phase 4: Sugar Semi-Annual (confirmed in S3: SUGAR_SEMI-ANNUAL_...)
    {"name": "sugar_semiannual", "source_name": "sugar_semiannual", "commodity_id": None,
     "countries": "BR,IN,TH,AU,CO,MX,ID,PH,EC,PK,ZA,CN",
     "title_filter": "sugar semi-annual", "start_year": 2000, "end_year": 2026, "workers": 4},
    # Phase 4: Cotton and Products Update — within-year monthly/quarterly cotton updates
    # Year-split into two jobs to halve crawl time
    {"name": "cotton_monthly_a", "source_name": "cotton_monthly", "commodity_id": None,
     "countries": "US,IN,CN,BR,AU,PK,UZ,TR",
     "title_filter": "cotton and products update", "start_year": 2000, "end_year": 2012, "workers": 8},
    {"name": "cotton_monthly_b", "source_name": "cotton_monthly", "commodity_id": None,
     "countries": "US,IN,CN,BR,AU,PK,UZ,TR",
     "title_filter": "cotton and products update", "start_year": 2013, "end_year": 2026, "workers": 8},
    # Phase 4: Coffee Semi-Annual (confirmed: Coffee_Semi-annual_... in S3)
    {"name": "coffee_semiannual", "source_name": "coffee_semiannual", "commodity_id": None,
     "countries": "BR,CO,VN,ET,ID,HN,GT,PE,MX,UG,IN,TZ,KE,CI,CM",
     "title_filter": "coffee semi-annual", "start_year": 2000, "end_year": 2026, "workers": 4},
    # Phase 4: Cocoa Semi-Annual (confirmed: Cocoa_Semi-Annual_... in S3)
    {"name": "cocoa_semiannual", "source_name": "cocoa_semiannual", "commodity_id": None,
     "countries": "CI,GH,CM,NG,ID,EC,PE,BR,DO",
     "title_filter": "cocoa semi-annual", "start_year": 2000, "end_year": 2026, "workers": 4},
]


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def submit_tasks(
    commodities: list[dict],
    job_queue: str,
    job_definition: str,
    bucket: str,
    aws_region: str,
    sleep_seconds: str,
    dry_run: bool,
) -> list[dict]:
    client = boto3.client("batch", region_name=aws_region)
    submitted: list[dict] = []

    for c in commodities:
        job_name = f"gain-backfill-{c['name'].replace('_', '-')}"

        # Build command override — Batch parameters don't support optional args cleanly,
        # so we use containerOverrides.command to pass the full arg list.
        command = [
            "jobs/batch/gain_backfill_task.py",
            "--commodity-name", c.get("source_name", c["name"]),
            "--target-countries", c["countries"],
            "--bucket", bucket,
            "--aws-region", aws_region,
            "--skip-existing-s3",
            "--sleep-seconds", sleep_seconds,
        ]
        if c.get("commodity_id") is not None:
            command += ["--commodity-id", str(c["commodity_id"])]
        if c.get("title_filter"):
            command += ["--title-filter", c["title_filter"]]
        if c.get("max_empty_pages"):
            command += ["--max-empty-pages", str(c["max_empty_pages"])]
        if c.get("start_year") is not None:
            command += ["--start-year", str(c["start_year"])]
        if c.get("end_year") is not None:
            command += ["--end-year", str(c["end_year"])]
        if c.get("workers", 1) > 1:
            command += ["--upload-workers", str(c["workers"])]

        if dry_run:
            logger.info("[DRY RUN] Would submit: %s  cmd=%s", job_name, command)
            submitted.append({"job_name": job_name, "job_id": None, "commodity": c["name"]})
            continue

        response = client.submit_job(
            jobName=job_name,
            jobQueue=job_queue,
            jobDefinition=job_definition,
            containerOverrides={"command": command},
        )
        job_id = response["jobId"]
        logger.info("Submitted  job_name=%s  job_id=%s", job_name, job_id)
        submitted.append({"job_name": job_name, "job_id": job_id, "commodity": c["name"]})

    return submitted


def save_run_record(submitted: list[dict], commodities: list[dict]) -> None:
    run_id = utc_now_iso().replace(":", "-")
    output_dir = Path("data/batch_runs")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"gain_backfill_{run_id}.json"
    payload = {
        "run_id": run_id,
        "source": "usda_gain",
        "commodities": [c["name"] for c in commodities],
        "task_count": len(submitted),
        "tasks": submitted,
    }
    output_path.write_text(json.dumps(payload, indent=2))
    logger.info("Run record saved to %s", output_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()

    env     = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    batch_queue   = f"{project}-{env}-queue"
    job_definition = f"{project}-{env}-gain-backfill"

    parser = argparse.ArgumentParser(
        description="Submit GAIN backfill as 10 parallel Batch Fargate tasks."
    )
    parser.add_argument(
        "--commodities",
        nargs="+",
        metavar="NAME",
        default=None,
        help="Subset of commodity names to submit (default: all 10).",
    )
    parser.add_argument(
        "--sleep-seconds",
        default="2",
        help="Seconds between PDF downloads inside each task (default: 2).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    commodities = COMMODITIES
    if args.commodities:
        names = {c["name"] for c in COMMODITIES}
        unknown = set(args.commodities) - names
        if unknown:
            raise SystemExit(f"Unknown commodities: {unknown}")
        commodities = [c for c in COMMODITIES if c["name"] in args.commodities]

    logger.info(
        "Submitting %d GAIN backfill tasks to queue=%s  job_def=%s",
        len(commodities), batch_queue, job_definition,
    )

    submitted = submit_tasks(
        commodities=commodities,
        job_queue=batch_queue,
        job_definition=job_definition,
        bucket=bucket,
        aws_region=aws_region,
        sleep_seconds=args.sleep_seconds,
        dry_run=args.dry_run,
    )

    save_run_record(submitted, commodities)

    if not args.dry_run:
        logger.info("All %d tasks submitted. Monitor at:", len(submitted))
        logger.info(
            "  https://%s.console.aws.amazon.com/batch/home?region=%s#jobs",
            aws_region, aws_region,
        )


if __name__ == "__main__":
    main()
