"""Fetch MODIS NDVI data via the NASA AppEEARS API.

Reads all 31 geography configs in parallel, splits coordinates into 5 commodity
groups, submits 5 AppEEARS point-sample tasks (saturating the per-account
concurrency limit), then polls and streams: each group is downloaded and
uploaded to S3 immediately as it reaches ``done`` — no group waits for slower
ones.

Processing timeline
-------------------
  Phase 1  Setup + parallel config reads     < 5 s
  Phase 2  Sequential task submission        < 30 s
  Phase 3–5  Polling + streaming download    15–45 min
             (groups stream to S3 as they complete)

A crash-resilient checkpoint is written to data/batch_runs/ immediately after
task submission so that task IDs are never lost.

Usage
-----
    python jobs/ingest/fetch_modis_ndvi.py
    python jobs/ingest/fetch_modis_ndvi.py --dry-run
    python jobs/ingest/fetch_modis_ndvi.py --end-date 2020-12-31
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from datetime import timedelta

from leviathan.common.config import get_required_env, load_env, load_yaml
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso
from leviathan.storage.s3 import download_s3_json, list_s3_keys, upload_bytes_to_s3

logger = get_logger("fetch_modis_ndvi")

_BASE_URL = "https://appeears.earthdatacloud.nasa.gov/api"

_RAW_PREFIX = "raw/weather/source=modis_ndvi/"
_TASKS_FILENAME = "_tasks.json"
# Re-attach horizon: NASA task handles older than this are not worth probing (the
# biweekly cadence has lapped them and AppEEARS bundles expire), and a recorded
# end_date this far from the requested one is a different catch-up window.
_REATTACH_MAX_AGE_DAYS = 14
# AppEEARS task statuses that are still pollable/downloadable server-side.
_ALIVE_STATUSES = frozenset({"queued", "pending", "processing", "done"})

# MOD13Q1 is a 16-day composite; one period of overlap protects the window seam.
_COMPOSITE_PERIOD_DAYS = 16
# First MOD13Q1 composite ever published -- the full-history window start.
_FULL_HISTORY_START = "02-18-2000"

# ── module-level token state ──────────────────────────────────────────────────

_token: str = ""


def _login(user: str, password: str) -> None:
    """POST /login (Basic Auth) → store bearer token in module state."""
    global _token
    logger.info("Logging in to AppEEARS…")
    r = requests.post(
        f"{_BASE_URL}/login",
        auth=(user, password),
        headers={"Content-Length": "0"},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    _token = data["token"]
    logger.info("Token acquired, expires %s", data["expiration"])


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token}"}


# ── rate-limit-aware GET ──────────────────────────────────────────────────────

def _api_get(path: str, user: str, password: str, **kwargs) -> requests.Response:
    """GET an AppEEARS API endpoint with automatic 403-refresh, 429-backoff,
    and transient network-error retry."""
    backoff = 60
    for attempt in range(8):
        try:
            r = requests.get(
                f"{_BASE_URL}{path}",
                headers=_auth_headers(),
                timeout=30,
                **kwargs,
            )
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as exc:
            wait = min(30 * 2 ** attempt, 300)
            logger.warning(
                "Network error on attempt %d (%s), retrying in %ds…",
                attempt + 1, exc, wait,
            )
            time.sleep(wait)
            continue
        if r.status_code in (401, 403):
            logger.warning("Token rejected (HTTP %d), refreshing…", r.status_code)
            _login(user, password)
            continue
        if r.status_code == 429:
            logger.warning("Rate-limited (HTTP 429), sleeping %ds before retry…", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
            continue
        return r
    raise RuntimeError(f"_api_get: exhausted retries for {path}")


# ── geography loading (parallel) ─────────────────────────────────────────────

def _load_one_geography(commodity: str) -> tuple[str, list[dict]]:
    """Return (commodity, [{region, country, latitude, longitude}])."""
    cfg = load_yaml(f"configs/geographies/{commodity}_regions.yaml")
    rows: list[dict] = []
    for region_block in cfg.get("regions", []):
        country = region_block["country"]
        for loc in region_block.get("locations", []):
            rows.append({
                "region": loc["region"],
                "country": country,
                "latitude": float(loc["latitude"]),
                "longitude": float(loc["longitude"]),
            })
    return commodity, rows


def _load_all_geographies(commodities: list[str]) -> dict[str, list[dict]]:
    """Load all 31 geography configs concurrently."""
    result: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=32) as pool:
        futures = {pool.submit(_load_one_geography, c): c for c in commodities}
        for fut in as_completed(futures):
            commodity, rows = fut.result()
            result[commodity] = rows
            logger.debug("Loaded %d locations for %s", len(rows), commodity)
    return result


# ── coordinate assembly ───────────────────────────────────────────────────────

def _build_group_coords(
    commodity_groups: dict[str, list[str]],
    geo_data: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """Assemble AppEEARS coordinate objects per group.

    Each coordinate: {id, category, latitude, longitude}
    id=region_name, category=commodity — these are echoed back in the CSV so
    the raw-to-bronze task can reconstruct the full mapping without any extra
    lookup at download time.
    """
    group_coords: dict[str, list[dict]] = {}
    for group, commodities in commodity_groups.items():
        coords: list[dict] = []
        for commodity in commodities:
            for loc in geo_data.get(commodity, []):
                coords.append({
                    "id": loc["region"],
                    "category": commodity,
                    "latitude": loc["latitude"],
                    "longitude": loc["longitude"],
                })
        group_coords[group] = coords
        logger.info(
            "Group %-22s → %3d coordinates (%d commodities)",
            group, len(coords), len(commodities),
        )
    return group_coords


# ── task submission ───────────────────────────────────────────────────────────

def _submit_one_task(
    group: str,
    coords: list[dict],
    end_date_appeears: str,
    product: str,
    layers: dict[str, str],
    run_id: str,
    user: str,
    password: str,
    start_date_appeears: str = _FULL_HISTORY_START,
) -> str:
    """Submit one AppEEARS point task; return task_id."""
    payload = {
        "task_type": "point",
        "task_name": f"leviathan_modis_ndvi_{group}_{run_id}",
        "params": {
            "dates": [{"startDate": start_date_appeears, "endDate": end_date_appeears}],
            "layers": [
                {"product": product, "layer": layers["ndvi"]},
                {"product": product, "layer": layers["quality"]},
            ],
            "coordinates": coords,
            "output": {
                "format": {"type": "csv"},
                "projection": {"type": "geographic"},
            },
        },
    }
    backoff = 60
    for attempt in range(3):
        r = requests.post(
            f"{_BASE_URL}/task",
            json=payload,
            headers=_auth_headers(),
            timeout=30,
        )
        if r.status_code == 429:
            logger.warning("Rate-limited on submit, sleeping %ds…", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
            continue
        if r.status_code in (401, 403):
            logger.warning("Token rejected on submit (HTTP %d), refreshing…", r.status_code)
            _login(user, password)
            continue
        r.raise_for_status()
        task_id: str = r.json()["task_id"]
        logger.info("Submitted group=%-22s → task_id=%s", group, task_id)
        return task_id
    raise RuntimeError(f"Failed to submit task for group={group} after retries")


# ── polling ───────────────────────────────────────────────────────────────────

def _poll_and_stream(
    task_ids: dict[str, str],
    user: str,
    password: str,
    run_id: str,
    bucket: str,
    aws_region: str,
    already_done: dict[str, str] | None = None,
) -> dict[str, str]:
    """Poll all tasks and immediately download+upload each group as it completes.

    Uses producer-consumer parallelism: the poll loop is the producer; a
    ThreadPoolExecutor is the consumer.  As soon as a group transitions to
    ``done`` its download+upload is submitted to the pool, so no group sits
    idle waiting for slower groups to finish.

    ``already_done`` maps group → s3_key for groups whose upload was confirmed
    in a previous run.  Those groups are skipped entirely (no re-download).

    Returns {group: s3_key} for all groups.
    """
    progress_path = Path("data/batch_runs") / f"modis_ndvi_progress_{run_id}.json"

    # Seed with any groups already uploaded in a prior (crashed) run
    s3_keys: dict[str, str] = dict(already_done or {})
    pending: dict[str, str] = {
        g: tid for g, tid in task_ids.items() if g not in s3_keys
    }
    if s3_keys:
        logger.info(
            "Skipping %d already-uploaded group(s): %s",
            len(s3_keys), ", ".join(s3_keys),
        )
    round_num = 0

    # Up to 5 concurrent download+upload workers (one per group)
    with ThreadPoolExecutor(max_workers=5) as pool:
        upload_futures: dict = {}  # future → group

        while pending or upload_futures:
            # ── poll remaining tasks ──────────────────────────────────────────
            if pending:
                round_num += 1
                logger.info(
                    "─── Poll round %d (%d groups pending) ───",
                    round_num, len(pending),
                )
                done_this_round: list[str] = []

                for group, task_id in list(pending.items()):
                    r = _api_get(f"/task/{task_id}", user, password)
                    r.raise_for_status()
                    task = r.json()
                    status: str = task.get("status", "unknown")

                    if status == "done":
                        logger.info("  ✓ %-22s DONE — queuing download+upload", group)
                        done_this_round.append(group)
                    elif status == "error":
                        err = task.get("error") or task.get("params", {})
                        raise RuntimeError(
                            f"AppEEARS task failed: group={group} "
                            f"task_id={task_id} error={err}"
                        )
                    else:
                        logger.info("  · %-22s %s", group, status)

                    time.sleep(0.5)  # gap between per-task status requests

                for group in done_this_round:
                    task_id = pending.pop(group)
                    fut = pool.submit(
                        _download_and_upload_one,
                        group, task_id, user, password, run_id, bucket, aws_region,
                    )
                    upload_futures[fut] = group

            # ── collect any finished upload futures ───────────────────────────
            finished = [f for f in upload_futures if f.done()]
            for fut in finished:
                group = upload_futures.pop(fut)
                s3_keys[group] = fut.result()
                # ── microbatch checkpoint: persist after every successful upload ──
                progress_path.parent.mkdir(parents=True, exist_ok=True)
                progress_path.write_text(json.dumps(s3_keys, indent=2))
                logger.info(
                    "Progress saved (%d/%d groups done) → %s",
                    len(s3_keys), len(task_ids), progress_path,
                )

            if pending:
                n_uploading = len(upload_futures)
                suffix = f" ({n_uploading} group(s) uploading in background)" if n_uploading else ""
                logger.info("Sleeping 60 s…  (%d groups still processing)%s", len(pending), suffix)
                time.sleep(60)
            elif upload_futures:
                # All tasks done; wait briefly for uploads to finish
                logger.info("All tasks done — waiting for %d upload(s) to finish…", len(upload_futures))
                time.sleep(5)

    return s3_keys


def _download_and_upload_one(
    group: str,
    task_id: str,
    user: str,
    password: str,
    run_id: str,
    bucket: str,
    aws_region: str,
) -> str:
    """Download the results CSV for *group* and immediately upload to S3.

    Returns the S3 key.
    """
    group_name, file_name, csv_bytes = _download_one_csv(group, task_id, user, password)
    key = f"raw/weather/source=modis_ndvi/run_id={run_id}/group={group}/{file_name}"
    upload_bytes_to_s3(csv_bytes, bucket, key, aws_region)
    logger.info("✓ Uploaded group=%-22s → s3://%s/%s", group, bucket, key)
    return key


# ── CSV download (parallel) ───────────────────────────────────────────────────

def _download_one_csv(
    group: str,
    task_id: str,
    user: str,
    password: str,
) -> tuple[str, str, bytes]:
    """Download the results CSV for one completed task.

    Returns (group, file_name, csv_bytes).

    GET /bundle/{task_id}         — list files, find the results CSV
    GET /bundle/{task_id}/{file_id} — 302 → presigned S3 URL → bytes
    The actual data transfer goes directly to/from AWS S3, so there is
    no AppEEARS rate limit on the download itself.
    """
    # List bundle files
    r = _api_get(f"/bundle/{task_id}", user, password)
    r.raise_for_status()
    files: list[dict] = r.json()["files"]

    # Pick the results CSV (one per task)
    csv_meta = next(
        (f for f in files if f["file_type"] == "csv" and "results" in f["file_name"]),
        None,
    )
    if csv_meta is None:
        names = [f["file_name"] for f in files]
        raise RuntimeError(
            f"No results CSV in bundle for group={group} task_id={task_id}. "
            f"Files present: {names}"
        )

    file_id: str = csv_meta["file_id"]
    file_name: str = csv_meta["file_name"]
    expected_sha256: str = csv_meta["sha256"]
    size_mb: float = csv_meta["file_size"] / 1_000_000

    logger.info("Downloading %-50s (%.1f MB)…", file_name, size_mb)

    # Download: AppEEARS endpoint redirects (302) to a presigned S3 URL.
    # requests follows the redirect automatically; the actual bytes come from S3.
    backoff = 30
    for attempt in range(3):
        dl = requests.get(
            f"{_BASE_URL}/bundle/{task_id}/{file_id}",
            headers=_auth_headers(),
            allow_redirects=True,
            timeout=300,
        )
        if dl.status_code == 429:
            logger.warning("Rate-limited on download, sleeping %ds…", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)
            continue
        if dl.status_code in (401, 403):
            logger.warning("Token rejected on download, refreshing…")
            _login(user, password)
            continue
        dl.raise_for_status()
        break
    else:
        raise RuntimeError(f"Download failed for group={group} after retries")

    csv_bytes: bytes = dl.content

    # Verify SHA-256 checksum
    actual_sha256 = hashlib.sha256(csv_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"SHA-256 mismatch for {file_name}: "
            f"expected={expected_sha256} actual={actual_sha256}"
        )

    logger.info("✓ Downloaded %-50s (%d bytes, checksum OK)", file_name, len(csv_bytes))
    return group, file_name, csv_bytes


# ── run record ────────────────────────────────────────────────────────────────

def _save_run_record(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    logger.info("Run record saved → %s", path)


# ── S3 task checkpoint + re-attach ───────────────────────────────────────────

def _tasks_json_key(run_id: str) -> str:
    return f"{_RAW_PREFIX}run_id={run_id}/{_TASKS_FILENAME}"


def _persist_tasks_record(record: dict, bucket: str, aws_region: str) -> None:
    """Mirror the submit checkpoint to S3 so a FRESH container can re-attach.

    The local data/batch_runs/ checkpoint dies with the container (Batch/Fargate),
    which forced every restart to resubmit at the back of NASA's queue -- observed
    6-45h server-side for the 5-group request (May 24 2026 run: first group
    5h45m, last 45h). Best-effort: an upload failure only costs the re-attach
    option for this run, never the run itself."""
    key = _tasks_json_key(record["run_id"])
    try:
        upload_bytes_to_s3(
            json.dumps(record, indent=2).encode("utf-8"), bucket, key, aws_region
        )
        logger.info("Task checkpoint mirrored -> s3://%s/%s", bucket, key)
    except Exception as exc:  # noqa: BLE001 — checkpoint mirror is best-effort
        logger.warning(
            "Could not mirror task checkpoint to S3 (%s: %s) -- re-attach will be "
            "unavailable if this container dies.", type(exc).__name__, exc,
        )


def _derive_delta_start(bucket: str, aws_region: str, requested_end: date) -> str | None:
    """MM-DD-YYYY AppEEARS window start for a DELTA fetch, or None for full history.

    Every historical run requested the full 02-18-2000 -> today window, making
    NASA re-extract ~26 years x ~23 composites x hundreds of coordinates each
    time (a major driver of the observed 6-45h server-side wait). The delta
    start is derived from the newest COMPLETED raw run (>=1 group CSV): its
    checkpoint-recorded end_date when available (exact), else its run_id UTC
    stamp (pre-checkpoint runs -- equal to the submit-day default end_date),
    minus one 16-day composite period of overlap. Fail-soft: any surprise
    returns None and the fetch falls back to full history.
    """
    try:
        csv_keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=".csv", aws_region=aws_region)
        completed = sorted({
            k.split("run_id=")[1].split("/")[0]
            for k in csv_keys if "run_id=" in k and "/group=" in k
        })
        if not completed:
            return None
        latest = completed[-1]
        try:
            rec = download_s3_json(bucket, _tasks_json_key(latest), aws_region)
            last_end = datetime.strptime(rec["end_date"], "%Y-%m-%d").date()
        except Exception:  # noqa: BLE001 — pre-checkpoint runs have no _tasks.json
            last_end = datetime.strptime(latest, "%Y%m%dT%H%M%SZ").date()
        start = last_end - timedelta(days=_COMPOSITE_PERIOD_DAYS)
        if start >= requested_end:
            start = requested_end - timedelta(days=_COMPOSITE_PERIOD_DAYS)
        logger.info(
            "DELTA window: last completed run %s (data through ~%s) -> startDate %s",
            latest, last_end.isoformat(), start.isoformat(),
        )
        return start.strftime("%m-%d-%Y")
    except Exception as exc:  # noqa: BLE001 — optimization must never block the fetch
        logger.warning(
            "Delta-window probe failed (%s: %s) -- falling back to FULL-HISTORY fetch.",
            type(exc).__name__, str(exc)[:200],
        )
        return None


def _probe_task_alive(task_id: str, user: str, password: str) -> bool:
    """True iff the AppEEARS task still exists server-side in a pollable state."""
    try:
        r = _api_get(f"/task/{task_id}", user, password)
        if r.status_code != 200:
            return False
        return str(r.json().get("status", "")).lower() in _ALIVE_STATUSES
    except Exception:  # noqa: BLE001 — an unprobeable task is treated as dead
        return False


def _find_reattachable_run(
    bucket: str,
    aws_region: str,
    requested_end: date,
    user: str,
    password: str,
    requested_start: date | None = None,
) -> dict | None:
    """Most-recent incomplete run whose NASA tasks are still worth re-attaching to.

    Fail-soft by design: any surprise (S3 hiccup, malformed checkpoint, API
    refusal) logs a warning and returns None so the primary fresh-submit path is
    never blocked. Returns ``{run_id, record, alive_task_ids, dead_groups,
    already_done}`` or None.
    """
    try:
        keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=_TASKS_FILENAME, aws_region=aws_region)
        if not keys:
            return None
        # run_id is a sortable UTC timestamp -> lexically newest == most recent run
        key = sorted(keys)[-1]
        run_id = key.split("run_id=")[1].split("/")[0]
        submitted = datetime.strptime(run_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - submitted).days
        if age_days > _REATTACH_MAX_AGE_DAYS:
            logger.info("Newest task checkpoint (run_id=%s) is %dd old -- fresh submit.", run_id, age_days)
            return None
        record = download_s3_json(bucket, key, aws_region)
        rec_end = datetime.strptime(record["end_date"], "%Y-%m-%d").date()
        if abs((requested_end - rec_end).days) > _REATTACH_MAX_AGE_DAYS:
            logger.info(
                "run_id=%s window end %s too far from requested %s -- fresh submit.",
                run_id, record["end_date"], requested_end.isoformat(),
            )
            return None
        if requested_start is not None:
            # Manual --start-date backfill: the checkpoint's window must COVER the
            # requested start or re-attaching would silently narrow the backfill.
            # Pre-delta checkpoints carry no start_date == full history == covers all.
            rec_start_iso = record.get("start_date")
            rec_start = (
                datetime.strptime(rec_start_iso, "%Y-%m-%d").date()
                if rec_start_iso else date(2000, 2, 18)
            )
            if rec_start > requested_start:
                logger.info(
                    "run_id=%s window starts %s, narrower than requested %s -- fresh submit.",
                    run_id, rec_start.isoformat(), requested_start.isoformat(),
                )
                return None
        task_ids: dict[str, str] = record["task_ids_by_group"]
        uploaded = list_s3_keys(bucket, f"{_RAW_PREFIX}run_id={run_id}/", suffix=".csv", aws_region=aws_region)
        already_done: dict[str, str] = {}
        for k in uploaded:
            if "/group=" in k:
                already_done[k.split("/group=")[1].split("/")[0]] = k
        pending = {g: t for g, t in task_ids.items() if g not in already_done}
        if not pending:
            logger.info("run_id=%s is already fully uploaded -- fresh submit.", run_id)
            return None
        alive: dict[str, str] = {}
        dead: list[str] = []
        for group, task_id in pending.items():
            if _probe_task_alive(task_id, user, password):
                alive[group] = task_id
            else:
                dead.append(group)
        if not alive:
            logger.info("run_id=%s has no live NASA tasks left -- fresh submit.", run_id)
            return None
        logger.info(
            "RE-ATTACH run_id=%s: %d live task(s) [%s], %d group(s) already uploaded, "
            "%d dead (will resubmit under the same run)",
            run_id, len(alive), ", ".join(sorted(alive)), len(already_done), len(dead),
        )
        return {
            "run_id": run_id,
            "record": record,
            "alive_task_ids": alive,
            "dead_groups": dead,
            "already_done": already_done,
        }
    except Exception as exc:  # noqa: BLE001 — resilience feature must never block the fresh path
        logger.warning(
            "Re-attach scan failed (%s: %s) -- falling back to fresh submit.",
            type(exc).__name__, str(exc)[:200],
        )
        return None


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Fetch MODIS NDVI via AppEEARS and upload raw CSVs to S3."
    )
    parser.add_argument(
        "--end-date",
        default=date.today().strftime("%Y-%m-%d"),
        help="Latest observation date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help=(
            "Earliest observation date in YYYY-MM-DD format. Default: DELTA window "
            "derived from the newest completed run minus one 16-day composite period "
            "(full history 2000-02-18 when no prior run exists). Pass an explicit "
            "date for manual backfills."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print group coordinate counts without submitting anything",
    )
    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="Resume a previous run by reading its checkpoint JSON; skips task submission",
    )
    parser.add_argument(
        "--no-reattach",
        action="store_true",
        help="Skip the S3 _tasks.json scan and always submit fresh AppEEARS tasks",
    )
    args = parser.parse_args()

    load_env()
    user = get_required_env("EARTHDATA_USER")
    password = get_required_env("EARTHDATA_PASSWORD")

    if not args.dry_run:
        bucket = get_required_env("LEVIATHAN_BUCKET")
        aws_region = get_required_env("AWS_REGION")

    # Convert end date from YYYY-MM-DD to MM-DD-YYYY (AppEEARS format)
    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    end_date_appeears = end_dt.strftime("%m-%d-%Y")

    # Load source config and geography data
    source_cfg = load_yaml("configs/sources/modis_ndvi.yaml")
    product: str = source_cfg["product"]
    layers: dict[str, str] = source_cfg["layers"]
    commodity_groups: dict[str, list[str]] = source_cfg["commodity_groups"]

    all_commodities = [c for group in commodity_groups.values() for c in group]
    logger.info("Loading geographies for %d commodities in parallel…", len(all_commodities))
    geo_data = _load_all_geographies(all_commodities)

    group_coords = _build_group_coords(commodity_groups, geo_data)
    total_coords = sum(len(v) for v in group_coords.values())
    logger.info("Total coordinates across all groups: %d", total_coords)

    if args.dry_run:
        logger.info("[DRY-RUN] Would submit %d AppEEARS tasks:", len(group_coords))
        for group, coords in group_coords.items():
            logger.info("  group=%-22s  %d coordinates", group, len(coords))
        logger.info(
            "[DRY-RUN] Date range: %s -> %s",
            args.start_date or "<delta-probe at runtime>", end_date_appeears,
        )
        return

    # ── Resolve the fetch window start (manual override > delta probe > full) ─
    if args.start_date:
        requested_start: date | None = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        start_date_appeears = requested_start.strftime("%m-%d-%Y")
        logger.info("Manual start date: %s", args.start_date)
    else:
        requested_start = None
        start_date_appeears = _derive_delta_start(bucket, aws_region, end_dt)
        if start_date_appeears is None:
            start_date_appeears = _FULL_HISTORY_START
            logger.info(
                "No completed prior run found -- FULL-HISTORY fetch (2000-02-18 -> %s).",
                args.end_date,
            )
    start_date_iso = datetime.strptime(start_date_appeears, "%m-%d-%Y").date().isoformat()

    already_done: dict[str, str] = {}
    if args.resume:
        # ── Resume mode: load task IDs from checkpoint, skip submission ─────
        checkpoint_path = Path("data/batch_runs") / f"modis_ndvi_submit_{args.resume}.json"
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")
        checkpoint = json.loads(checkpoint_path.read_text())
        run_id = checkpoint["run_id"]
        task_ids = checkpoint["task_ids_by_group"]
        submit_record = checkpoint
        logger.info("Resuming run_id=%s with %d existing tasks", run_id, len(task_ids))
        for group, tid in task_ids.items():
            logger.info("  %-22s → %s", group, tid)
        # Load per-group upload progress if a previous run completed some groups
        progress_path = Path("data/batch_runs") / f"modis_ndvi_progress_{run_id}.json"
        if progress_path.exists():
            already_done = json.loads(progress_path.read_text())
            logger.info(
                "Found progress file: %d group(s) already uploaded — %s",
                len(already_done), ", ".join(already_done),
            )
        _login(user, password)
    else:
        _login(user, password)
        # ── Auto re-attach: a fresh container inherits in-flight NASA tasks ──
        # from a crashed/restarted run instead of resubmitting at the back of
        # the queue. --no-reattach forces a clean submit.
        reattach = None if args.no_reattach else _find_reattachable_run(
            bucket, aws_region, end_dt, user, password, requested_start,
        )
        if reattach is not None:
            run_id = reattach["run_id"]
            task_ids = dict(reattach["alive_task_ids"])
            already_done = reattach["already_done"]
            # Dead-group resubmits reuse the CHECKPOINT's window so every group of
            # the run covers the same date range (pre-delta checkpoints = full history).
            rec_start_iso = reattach["record"].get("start_date")
            rec_start_appeears = (
                datetime.strptime(rec_start_iso, "%Y-%m-%d").strftime("%m-%d-%Y")
                if rec_start_iso else _FULL_HISTORY_START
            )
            for group in reattach["dead_groups"]:
                if group not in group_coords:
                    logger.warning(
                        "Dead group %s from run_id=%s no longer in config -- skipping.",
                        group, run_id,
                    )
                    continue
                task_ids[group] = _submit_one_task(
                    group=group,
                    coords=group_coords[group],
                    end_date_appeears=end_date_appeears,
                    product=product,
                    layers=layers,
                    run_id=run_id,
                    user=user,
                    password=password,
                    start_date_appeears=rec_start_appeears,
                )
                time.sleep(2)  # rate-limit guard between POSTs
            submit_record = {
                **reattach["record"],
                "task_ids_by_group": task_ids,
                "reattached_at": utc_now_iso(),
            }
            _save_run_record(
                Path("data/batch_runs") / f"modis_ndvi_submit_{run_id}.json",
                submit_record,
            )
            _persist_tasks_record(submit_record, bucket, aws_region)
        else:
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            logger.info("run_id=%s", run_id)

            # ── Phase 2: submit tasks sequentially (2 s gap to avoid 429 burst) ─
            task_ids = {}
            for i, (group, coords) in enumerate(group_coords.items()):
                task_id = _submit_one_task(
                    group=group,
                    coords=coords,
                    end_date_appeears=end_date_appeears,
                    product=product,
                    layers=layers,
                    run_id=run_id,
                    user=user,
                    password=password,
                    start_date_appeears=start_date_appeears,
                )
                task_ids[group] = task_id
                if i < len(group_coords) - 1:
                    time.sleep(2)  # rate-limit guard between POSTs

            # Checkpoint — write task IDs immediately so a crash doesn't lose them
            submit_record = {
                "run_id": run_id,
                "source": "modis_ndvi",
                "stage": "fetch",
                "submitted_at": utc_now_iso(),
                "start_date": start_date_iso,
                "end_date": args.end_date,
                "total_coordinates": total_coords,
                "task_ids_by_group": task_ids,
            }
            _save_run_record(
                Path("data/batch_runs") / f"modis_ndvi_submit_{run_id}.json",
                submit_record,
            )
            _persist_tasks_record(submit_record, bucket, aws_region)

    # ── Phase 3–5: poll + stream download+upload as each group completes ──────
    logger.info("Polling AppEEARS for task completion (15–45 min expected)…")
    logger.info("Each group will be downloaded and uploaded to S3 as soon as it is ready.")
    s3_keys = _poll_and_stream(task_ids, user, password, run_id, bucket, aws_region, already_done)

    # ── Phase 6: final run record ─────────────────────────────────────────────
    final_record: dict = {
        **submit_record,
        "completed_at": utc_now_iso(),
        "s3_keys_by_group": s3_keys,
    }
    _save_run_record(
        Path("data/batch_runs") / f"modis_ndvi_fetch_{run_id}.json",
        final_record,
    )

    logger.info(
        "Done. run_id=%s | %d CSVs uploaded to s3://%s/raw/weather/source=modis_ndvi/run_id=%s/",
        run_id, len(s3_keys), bucket, run_id,
    )


if __name__ == "__main__":
    main()
