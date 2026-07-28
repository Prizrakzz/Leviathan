#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W2 / D1 + D5 -- the Databento EOD raw producer.

WHAT IT DOES, IN THE ORDER THE PLAN MANDATES
--------------------------------------------
Per ``(dataset, root, year)``:

  1. **Resolve, free, in TWO steps.** ``stype_in=parent, stype_out=raw_symbol`` is an HTTP 422
     (established by the live smoke, 2026-07-28): the recipe is ``<ROOT>.FUT`` -> instrument_id,
     then instrument_id -> raw_symbol in batches of <= 500. Both calls are free.
  2. **Filter to OUTRIGHTS (F1).** Parent symbology returns butterflies, condors and calendar
     spreads; outrights are 2.4%-24% of the result. Filtering is the difference between $43.24 and
     $140.31 -- i.e. between fitting in the $125 of credits and not. The filter is
     ``transforms.raw_to_bronze.databento_eod.is_outright``: the verified regex AND an exact root
     match, because the bare GLBX regex admitted ``T12Q6`` on a ``ZC`` resolve.
  3. **Assert F-A**: within one ``(root, year)`` every ``raw_symbol`` maps to exactly ONE
     ``instrument_id``. HARD FAIL otherwise -- F2's falsification test and the ohlcv/statistics
     join key both rest on it.
  4. **Persist the resolve verdict** to ``symbology_{root}_{year}.json`` under
     ``raw/production/source=databento/dataset={ds}/root={root}/year={year}/``. It carries the
     per-symbol outright/dropped verdict and the ``dropped_count`` that IS the gate-2 metric -- the
     evidence is written once, at resolve time, never recomputed from an S3 listing later. It is
     also the D2 decade anchor: the resolve year plus each mapping's ``d0``/``d1`` pins ``ZCH6`` to
     2016 rather than 2026 with no reference to ``datetime.now()``.
  5. **Buy by ``raw_symbol`` through the BATCH api**, never through timeseries streaming: batch
     bills once and re-downloads free for 30 days, streaming re-bills every call and has no resume
     (a dropped connection 90% through IFUS costs $34.28 again).
  6. **Download per file** (never the whole-job zip): only the per-file path verifies the sha256
     manifest and resumes by HTTP Range.

MODES
-----
``--mode backfill --root ZC --year 2016``
    One ``(root, year)`` unit, idempotent: an existing raw payload is skipped unless
    ``--force-overwrite``. The unit is per-YEAR because skeptic finding F-A is BINDING -- the
    symbol->instrument_id uniqueness assertion is only meaningful inside one resolve window.
``--mode incremental --since YYYY-MM-DD``
    D5. Re-resolves the CURRENT year, requests ``[since, today+1)`` and lands the payload in the
    same ``year={current}`` prefix under an as-of filename. Measured at $0.016/day for all 15
    roots -- a rounding error, and shaped to slot into ``jobs/batch/futures_eod_task.py``.
``--cost-only``
    THE PRE-BUY GATE. Runs the full resolve + ``metadata.get_cost`` for every requested
    ``(root, year)`` and prints a per-root-per-year and per-DATASET cost table plus a grand total,
    WITHOUT submitting anything. The quote is to-the-cent reproducible because the submit that
    follows reuses the IDENTICAL ``dataset/symbols/schema/stype_in/start/end`` tuple.

    IT FAILS CLOSED, on two conditions, because a gate that only PRINTS a number is not a gate:
    a ZERO dropped-symbol count on any root (the outright filter did not run -- that is the
    $140.31 parent pull), and a grand total above ``--max-usd`` (default 50.00, itself capped at
    the 125.00 credit pool). The per-dataset subtotals exist so the quote can be diffed
    STRUCTURALLY against the plan's GLBX 2.7819 / IFUS 34.2813 / IFEU 6.1793 rather than only in
    aggregate. Under ``--mode incremental`` the quote prices the INCREMENTAL window, not the
    calendar year the payload lands in.

THE KEY
-------
Read from the environment variable ``DATABENTO_API_KEY``, which the ECS agent injects from Secrets
Manager secret ``leviathan/dev/databento-api-key`` (``valueFrom`` on the job definition -- the
FAS_API_KEY pattern, ``infra/terraform/modules/batch/main.tf``). When the variable is absent this
script will fetch that secret directly via ``secretsmanager:GetSecretValue``. It is NEVER logged,
NEVER placed in argv, and never echoed in an error message; ``--secret-id`` names the SECRET, not
the value.

COST DISCIPLINE
---------------
``symbols=None`` means ALL_SYMBOLS to Databento -- that is the $140.31 mistake -- so a ``None`` or
empty symbol list is refused before any billable call. Every billable entry point additionally
passes ``schema`` explicitly (the client defaults to ``trades``, which would price the wrong thing
by three orders of magnitude).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

# Batch invokes tasks by PATH, so `jobs.*` / `leviathan.*` need the repo root importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import (  # noqa: E402
    databento_payload_filename,
    databento_symbology_filename,
    raw_databento_key,
)

# root_years / year_window live in the transform module so the fetch job and the silver task can
# never disagree about the unit set (a unit one skips and the other expects is either a spurious
# failure or silently missing history).
from leviathan.transforms.raw_to_bronze.databento_eod import (  # noqa: E402
    DATASET_SLUGS,
    GLBX,
    ROOT_FIRST_DATE,
    ROOT_MAP,
    partition_symbols,
    root_years,
    year_window,
)

logger = get_logger(__name__)

# The Secrets Manager secret the ECS agent injects as DATABENTO_API_KEY. The NAME is public; the
# value never leaves this process's memory.
DATABENTO_SECRET_ID = "leviathan/dev/databento-api-key"
DATABENTO_KEY_ENV = "DATABENTO_API_KEY"

OHLCV_SCHEMA = "ohlcv-1d"
STATISTICS_SCHEMA = "statistics"
# GLBX statistics is $1.76 for the whole backfill and carries the ONLY real settlements and the
# ONLY open interest in the wave. ICE statistics is $1,696 (IFUS) + $264 (IFEU) -- EXCLUDED.
STATISTICS_DATASETS: frozenset[str] = frozenset({GLBX})

# symbology.resolve documents a 2,000-symbol cap; the orchestrator's live smoke batched step 2 at
# <= 500 and that conservative value is kept deliberately.
RESOLVE_CHUNK = 500
# databento's BentoHttpAPI._post has NO 429/Retry-After handling (only the batch DOWNLOAD path
# does), so every resolve/cost/submit call goes through this caller-side backoff.
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 2.0
POLITE_SLEEP_SECONDS = 0.5


# ---------------------------------------------------------------------------
# key handling
# ---------------------------------------------------------------------------
def load_api_key(secret_id: str = DATABENTO_SECRET_ID, region: str = "us-east-1") -> str:
    """The Databento key. Environment first (the ECS ``valueFrom`` injection), Secrets Manager
    second. NEVER logged, never returned in an exception message."""
    key = (os.environ.get(DATABENTO_KEY_ENV) or "").strip()
    if key:
        # PRESENT, never the length: the log stream is shared and a key length is a free bit of a
        # secret nobody needs. "present" is all an operator can act on anyway.
        logger.info("databento key: taken from env %s (present, value not logged)",
                    DATABENTO_KEY_ENV)
        return key
    import boto3

    logger.info("databento key: env %s absent, reading secret %s", DATABENTO_KEY_ENV, secret_id)
    sm = boto3.client("secretsmanager", region_name=region)
    payload = sm.get_secret_value(SecretId=secret_id)["SecretString"]
    try:
        parsed = json.loads(payload)
        key = str(parsed.get("api_key") or parsed.get(DATABENTO_KEY_ENV) or "").strip()
    except (TypeError, ValueError):
        key = str(payload).strip()
    if not key:
        raise RuntimeError(f"secret {secret_id} carries no usable Databento key (value not logged)")
    return key


def make_client(key: str):
    """A ``databento.Historical`` client. The vendor package is imported lazily and its absence is
    reported as the actionable "rebuild the worker image" error, not an opaque ImportError."""
    try:
        import databento as db
    except ImportError as exc:
        raise SystemExit(
            "the 'databento' package is not installed -- add it to pyproject's [batch] extra and "
            "REBUILD + REPIN the worker image before any cloud run (the yfinance ImportError "
            "silently wrote nothing for six weeks)"
        ) from exc
    return db.Historical(key)


# ---------------------------------------------------------------------------
# retry / windows
# ---------------------------------------------------------------------------
def call_with_backoff(fn, *args, attempts: int = MAX_ATTEMPTS, **kwargs):
    """Retry a Databento call on 429/5xx with exponential backoff. The client does not do this for
    ``_post`` / ``_get``; only the batch file download honours ``Retry-After``."""
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 -- BentoClientError/BentoServerError + transport
            status = getattr(exc, "http_status", None)
            retryable = status is None or status == 429 or (isinstance(status, int) and status >= 500)
            if not retryable or i == attempts - 1:
                raise
            last = exc
            wait = BACKOFF_BASE_SECONDS * (2 ** i)
            logger.warning("databento call failed (status=%s), retrying in %.1fs [%d/%d]",
                           status, wait, i + 1, attempts)
            time.sleep(wait)
    raise last  # pragma: no cover -- unreachable, the loop either returns or raises


def _chunks(seq: list, size: int) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


# ---------------------------------------------------------------------------
# step 1 + step 2: the free two-step resolve
# ---------------------------------------------------------------------------
def resolve_outrights(client, *, dataset: str, root: str, year: int,
                      through: Optional[date] = None) -> dict:
    """The full free discovery for one ``(dataset, root, year)`` + the F-A assertion.

    Returns the artifact persisted as ``symbology_{root}_{year}.json``: the outright set, the
    DROPPED set (gate 2's evidence), the symbol -> instrument_id mapping and the raw responses."""
    start, end = year_window(root, year, through=through)

    # STEP 1 (free): parent -> instrument_id. `<ROOT>.FUT` is upper-cased and validated as a smart
    # symbol by the client; `W.FUT` (the single-character IFEU root) is legal.
    r1 = call_with_backoff(
        client.symbology.resolve, dataset=dataset, symbols=f"{root}.FUT",
        stype_in="parent", stype_out="instrument_id", start_date=start, end_date=end)
    ids = sorted({e["s"] for entries in (r1.get("result") or {}).values()
                  for e in entries if e.get("s")}, key=int)

    # STEP 2 (free): instrument_id -> raw_symbol, batched. An EMPTY symbols list raises inside the
    # client, so the zero-instrument case (e.g. KE before 2013) short-circuits here.
    sym_to_ids: dict[str, set[str]] = {}
    sym_to_intervals: dict[str, list] = {}
    step2: list[dict] = []
    for chunk in _chunks(ids, RESOLVE_CHUNK):
        r2 = call_with_backoff(
            client.symbology.resolve, dataset=dataset, symbols=chunk,
            stype_in="instrument_id", stype_out="raw_symbol", start_date=start, end_date=end)
        step2.append(r2)
        for iid, entries in (r2.get("result") or {}).items():
            for e in entries:
                sym = e.get("s")
                if sym:
                    sym_to_ids.setdefault(sym, set()).add(str(iid))
                    sym_to_intervals.setdefault(sym, []).append(
                        [e.get("d0"), e.get("d1"), str(iid)])
        time.sleep(POLITE_SLEEP_SECONDS)

    outrights, dropped = partition_symbols(sym_to_ids.keys(), root, dataset)

    # F-A, BINDING -- AMENDED 2026-07-28 after the gate fired on real data. GLBX RECYCLES
    # instrument_ids across unrelated products (measured, KE/2021: KEN4 was iid 688493 for
    # Jan-01..Feb-25 and iid 234273 from Jun-30; between KEN4 tenures, 688493 carried an equity
    # option and 234273 a VIX option). A re-listing under a new id on DISJOINT date intervals is
    # fully decodable: every (raw_symbol, date) still has exactly ONE instrument_id, the DBNStore
    # symbology map is interval-scoped (symbology_from_artifact preserves d0/d1), and the
    # ohlcv/statistics join key (instrument_id, date) stays unambiguous. What genuinely breaks
    # the join and F2's dedupe is an OVERLAP -- one symbol on two ids on the SAME date -- so
    # that, exactly, is what refuses the buy. Only the OUTRIGHTS are asserted -- a spread symbol
    # legitimately re-uses ids across the complex and is dropped anyway.
    relisted: dict[str, list] = {}
    for s in outrights:
        ivs = sorted(sym_to_intervals.get(s, []), key=lambda iv: str(iv[0]))
        if len({iv[2] for iv in ivs}) > 1:
            relisted[s] = ivs
        for a, b in zip(ivs, ivs[1:]):
            end_a = a[1] or "9999-12-31"   # an open interval overlaps anything after it
            if str(end_a) > str(b[0]):     # d1 is EXCLUSIVE: d1 == next d0 is adjacency, not overlap
                raise SystemExit(
                    f"F-A VIOLATION {dataset} {root}/{year}: raw_symbol {s} maps to OVERLAPPING "
                    f"instrument_id intervals ({a} vs {b}) -- refusing to buy; the join key and "
                    f"the F2 dedupe rule would both be ambiguous"
                )
    if relisted:
        logger.info(
            "%s %s/%s: %d outright symbol(s) re-listed under a new instrument_id on disjoint "
            "intervals (GLBX id recycling, decodable): %s", dataset, root, year, len(relisted),
            ", ".join(f"{s}->{[iv[2] for iv in relisted[s]]}" for s in sorted(relisted)[:5]))

    artifact = {
        "producer": "jobs/ingest/fetch_databento_eod.py",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "dataset": dataset,
        "dataset_slug": DATASET_SLUGS[dataset],
        "root": root,
        "leviathan_slug": ROOT_MAP[root][1],
        "year": int(year),
        "window": {"start": start, "end_exclusive": end},
        "resolved_instrument_ids": len(ids),
        "resolved_symbols": len(sym_to_ids),
        "outright_count": len(outrights),
        "dropped_count": len(dropped),
        "outright_symbols": outrights,
        "dropped_symbols": dropped,
        "symbol_instrument_ids": {s: sorted(sym_to_ids[s]) for s in outrights},
        # disjoint-interval re-listings (GLBX id recycling) permitted by the amended F-A check;
        # rows of [d0, d1_exclusive, instrument_id] per affected outright. Gate evidence.
        "relisted_symbols": relisted,
        "resolve_step1": r1,
        "resolve_step2": step2,
    }
    logger.info("resolve %s %s/%s: %d instrument_ids -> %d raw symbols -> %d outrights "
                "(%d dropped)", dataset, root, year, len(ids), len(sym_to_ids),
                len(outrights), len(dropped))
    if outrights and not dropped:
        # A zero drop count on ANY root means the filter did not run (gate 2 formulation, which
        # corrects the earlier "zero for GLBX" wording that contradicted F1).
        logger.error("gate-2 PRECONDITION BREACH %s %s/%s: dropped_count is ZERO -- the outright "
                     "filter did not run", dataset, root, year)
    return artifact


# ---------------------------------------------------------------------------
# --cost-only: the pre-buy gate
# ---------------------------------------------------------------------------
def cost_for_unit(client, artifact: dict, schema: str) -> float:
    """``metadata.get_cost`` for one ``(root, year, schema)`` unit, on the EXACT symbols/window the
    submit will use. Free.

    ``schema`` is always passed explicitly (the client default is ``trades``) and ``symbols`` is
    never ``None`` (``None`` means ALL_SYMBOLS -- the $140.31 mistake). ``mode`` is deprecated and
    is not passed; ``stype_out`` is not a parameter of get_cost at all."""
    symbols = list(artifact["outright_symbols"])
    if not symbols:
        return 0.0
    return float(call_with_backoff(
        client.metadata.get_cost,
        dataset=artifact["dataset"], symbols=symbols, schema=schema, stype_in="raw_symbol",
        start=artifact["window"]["start"], end=artifact["window"]["end_exclusive"]))


def build_cost_table(client, units: list[tuple[str, str, int]], *,
                     through: Optional[date] = None,
                     with_statistics: bool = True,
                     window_override: Optional[tuple[str, str]] = None) -> dict:
    """Resolve + price every requested ``(dataset, root, year)``. NO submit, no billable call.

    ``metadata.get_cost`` carries no job-shape parameter -- cost is billable-uncompressed-bytes
    only -- so this per-(root, year) quote is exactly what a per-(root, year) submit will charge.

    ``window_override`` is ``(start, end_exclusive)`` and MUST be passed whenever the caller is
    quoting a narrowed window. Without it an incremental ``--cost-only`` quotes the FULL calendar
    year -- ~250x the measured $0.016/day -- because :func:`resolve_outrights` windows on
    ``year_window`` and the incremental narrowing happens later, in the submit branch. get_cost is
    free, so nothing is billed either way; the printed number is simply not the one the run will
    charge, which is exactly what a pre-buy gate must never do."""
    rows: list[dict] = []
    for dataset, root, year in units:
        art = resolve_outrights(client, dataset=dataset, root=root, year=year, through=through)
        if window_override is not None:
            art["window"] = {"start": window_override[0], "end_exclusive": window_override[1]}
        ohlcv = cost_for_unit(client, art, OHLCV_SCHEMA)
        stats = (cost_for_unit(client, art, STATISTICS_SCHEMA)
                 if with_statistics and dataset in STATISTICS_DATASETS else 0.0)
        rows.append({
            "dataset": dataset, "root": root, "year": int(year),
            "leviathan_slug": art["leviathan_slug"],
            "outrights": art["outright_count"], "dropped": art["dropped_count"],
            "window_start": art["window"]["start"], "window_end_exclusive": art["window"]["end_exclusive"],
            "ohlcv_usd": round(ohlcv, 4), "statistics_usd": round(stats, 4),
            "total_usd": round(ohlcv + stats, 4),
        })
        time.sleep(POLITE_SLEEP_SECONDS)
    grand = round(sum(r["total_usd"] for r in rows), 4)
    by_root: dict[str, float] = {}
    by_dataset: dict[str, float] = {}
    for r in rows:
        by_root[r["root"]] = round(by_root.get(r["root"], 0.0) + r["total_usd"], 4)
        # PER-DATASET subtotals exist so the quote can be diffed STRUCTURALLY against the plan's
        # GLBX 2.7819 / IFUS 34.2813 / IFEU 6.1793 (lines 605-607). A single grand total cannot
        # distinguish "the outright filter ran" from "one dataset silently pulled the parent set".
        by_dataset[r["dataset"]] = round(by_dataset.get(r["dataset"], 0.0) + r["total_usd"], 4)
    return {"rows": rows, "by_root": by_root, "by_dataset": by_dataset,
            "ohlcv_usd": round(sum(r["ohlcv_usd"] for r in rows), 4),
            "statistics_usd": round(sum(r["statistics_usd"] for r in rows), 4),
            "grand_total_usd": grand,
            "zero_drop_roots": sorted({r["root"] for r in rows
                                       if r["outrights"] and not r["dropped"]})}


# The pre-buy budget ceiling. The plan's RECOMMENDED BUY is $45.00 (43.24 ohlcv + 1.76 statistics);
# the naive parent-symbology pull the outright filter exists to prevent is $140.31 and the credit
# pool is $125. DEFAULT_MAX_USD leaves headroom over the recommended buy without admitting anything
# near the parent number; HARD_CEILING_USD is the value --max-usd itself may not exceed, so the
# budget gate cannot be talked past on the command line.
DEFAULT_MAX_USD = 50.0
HARD_CEILING_USD = 125.0


def render_cost_table(table: dict) -> str:
    """ASCII-only cost report (the Windows console is cp1252)."""
    L = ["=== Databento W2 pre-buy cost reproduction (metadata.get_cost; NOTHING submitted) ===",
         "",
         "dataset       root year  outr drop      ohlcv$      stats$      total$",
         "----------------------------------------------------------------------"]
    for r in table["rows"]:
        L.append(f"{r['dataset']:<13s} {r['root']:<4s} {r['year']:<5d} {r['outrights']:<4d} "
                 f"{r['dropped']:<4d} {r['ohlcv_usd']:>11.4f} {r['statistics_usd']:>11.4f} "
                 f"{r['total_usd']:>11.4f}")
    L.append("----------------------------------------------------------------------")
    L.append("per-root totals:")
    for root in sorted(table["by_root"]):
        L.append(f"  {root:<4s} {table['by_root'][root]:>11.4f}")
    L.append("")
    L.append("per-DATASET totals (diff these against the plan: GLBX 2.7819 / IFUS 34.2813 / "
             "IFEU 6.1793):")
    for ds in sorted(table.get("by_dataset") or {}):
        L.append(f"  {ds:<13s} {table['by_dataset'][ds]:>11.4f}")
    L.append("")
    L.append(f"ohlcv-1d subtotal   : {table['ohlcv_usd']:>11.4f}")
    L.append(f"statistics subtotal : {table['statistics_usd']:>11.4f}")
    L.append(f"GRAND TOTAL         : {table['grand_total_usd']:>11.4f}")
    if table["zero_drop_roots"]:
        L.append("")
        L.append("GATE-2 PRECONDITION BREACH -- zero dropped symbols on root(s): "
                 + ", ".join(table["zero_drop_roots"]))
    L.append("")
    L.append("The submit reuses the IDENTICAL dataset/symbols/schema/stype_in/start/end tuple, so "
             "the charge matches this quote to the cent.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# the buy + the download
# ---------------------------------------------------------------------------
def submit_unit(client, artifact: dict, schema: str) -> dict:
    """Submit ONE batch job for one ``(root, year, schema)`` unit. BILLABLE.

    Identical tuple to :func:`cost_for_unit`. ``encoding='dbn'`` + ``compression='zstd'`` keeps the
    symbol mappings inside the payload (``map_symbols`` is a csv/json-only knob) and
    ``split_symbols=False`` keeps one file per unit instead of 50-114."""
    symbols = list(artifact["outright_symbols"])
    if not symbols:
        raise ValueError(f"{artifact['root']}/{artifact['year']}: refusing to submit with NO "
                         f"symbols -- an empty/None symbol set means ALL_SYMBOLS to Databento")
    job = call_with_backoff(
        client.batch.submit_job,
        dataset=artifact["dataset"], symbols=symbols, schema=schema,
        start=artifact["window"]["start"], end=artifact["window"]["end_exclusive"],
        encoding="dbn", compression="zstd",
        stype_in="raw_symbol", stype_out="instrument_id",
        split_duration="none", split_symbols=False, delivery="download")
    logger.info("submitted %s %s/%s %s -> job_id=%s", artifact["dataset"], artifact["root"],
                artifact["year"], schema, job.get("id"))
    return job


def download_job_files(client, job_id: str, out_dir: str) -> list[str]:
    """Download every file of a done job INDIVIDUALLY.

    Per-file is the only path that verifies the sha256 from the job manifest and resumes by HTTP
    Range; the whole-job zip does neither. Re-download is FREE for 30 days, so this is also the
    rollback path -- never re-submit inside the window."""
    files = call_with_backoff(client.batch.list_files, job_id)
    paths: list[str] = []
    for entry in files:
        name = entry["filename"]
        got = call_with_backoff(client.batch.download, job_id, out_dir, filename_to_download=name)
        paths.extend(str(p) for p in got)
    logger.info("downloaded %d file(s) for job %s", len(paths), job_id)
    return paths


# ---------------------------------------------------------------------------
# raw landing
# ---------------------------------------------------------------------------
# The raw filenames are OWNED BY leviathan.storage.paths and shared with jobs/batch/futures_eod_task
# -- the writer and the reader run back to back in one Step Function, so two independent derivations
# is a chain that cannot read the payload it just bought. Re-exported under the local names the
# rest of this module (and its tests) use.
symbology_filename = databento_symbology_filename
payload_filename = databento_payload_filename


def land_bytes(bucket: str, key: str, data: bytes, *, source_label: str, content_type: str,
               region: str, min_size_source: str) -> None:
    """Upload one raw artifact + its ``write_raw_s3_metadata`` companion, after the size floor."""
    from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
    from leviathan.storage.s3 import upload_bytes_to_s3

    check_min_file_size(data, min_size_source, context=key)
    upload_bytes_to_s3(data, bucket, key, region)
    write_raw_s3_metadata(bucket, key, data, source_label, content_type, region)
    logger.info("raw written -> s3://%s/%s (%d bytes)", bucket, key, len(data))


def raw_exists(bucket: str, key: str, region: str) -> bool:
    from leviathan.storage.s3 import get_thread_local_s3_client
    try:
        get_thread_local_s3_client(region).head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001 -- any head failure means "treat as absent"
        return False


# ---------------------------------------------------------------------------
# unit selection
# ---------------------------------------------------------------------------
def select_units(roots: list[str], years: Optional[list[int]], through_year: int
                 ) -> list[tuple[str, str, int]]:
    """``[(dataset, root, year), ...]`` sorted, for the requested roots/years."""
    out: list[tuple[str, str, int]] = []
    for root in roots:
        dataset = ROOT_MAP[root][0]
        candidates = root_years(root, through_year)
        for year in (years if years else candidates):
            if year not in candidates:
                logger.info("skip %s/%s: before the root's first usable year (%s)",
                            root, year, ROOT_FIRST_DATE[root])
                continue
            out.append((dataset, root, int(year)))
    return sorted(out)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s -- %(message)s",
                        stream=sys.stderr)
    ap = argparse.ArgumentParser(description="Databento futures EOD raw producer (W2 / D1 + D5)")
    ap.add_argument("--mode", choices=["backfill", "incremental"], required=True)
    ap.add_argument("--root", action="append", dest="roots", default=None,
                    choices=sorted(ROOT_MAP), help="repeatable; default = all 15")
    ap.add_argument("--year", action="append", type=int, dest="years", default=None,
                    help="repeatable; backfill only. Default = every usable year for the root")
    ap.add_argument("--through-year", type=int, default=None,
                    help="last backfill year (default: the current UTC year)")
    ap.add_argument("--since", default=None,
                    help="incremental mode: inclusive first trade date, YYYY-MM-DD")
    ap.add_argument("--lookback-days", type=int, default=5,
                    help="incremental mode, used when --since is absent: request the last N "
                         "calendar days. The scheduler can only substitute <aws.scheduler.*> "
                         "context attributes, so the scheduled chain passes THIS rather than a "
                         "templated date. 5 matches the registry freshness_sla max_lag_days, and "
                         "re-requesting the overlap costs $0.08 at the measured $0.016/day")
    ap.add_argument("--cost-only", action="store_true",
                    help="resolve + get_cost and print the table; submit NOTHING (the pre-buy gate)")
    ap.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD,
                    help=f"BUDGET CEILING for --cost-only: exit 1 when the grand total exceeds it "
                         f"(default {DEFAULT_MAX_USD:.2f}; may not exceed {HARD_CEILING_USD:.2f}). "
                         f"The recommended buy is $45.00; the naive parent pull the outright filter "
                         f"prevents is $140.31 against $125 of credits, so a gate that only PRINTS "
                         f"the number is not a gate")
    ap.add_argument("--no-statistics", action="store_true",
                    help="skip the GLBX statistics leg (it is $1.76 and load-bearing -- see the "
                         "plan's DO NOT OPTIMIZE AWAY note; this exists for repair runs only)")
    ap.add_argument("--download-dir", default=None,
                    help="local staging dir for batch downloads (default: a temp dir)")
    ap.add_argument("--poll-seconds", type=int, default=30)
    ap.add_argument("--max-wait-seconds", type=int, default=7200)
    ap.add_argument("--force-overwrite", action="store_true")
    ap.add_argument("--secret-id", default=DATABENTO_SECRET_ID,
                    help="Secrets Manager secret NAME holding the key (never the value)")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the units and the S3 keys, then return; no network, no key needed")
    args = ap.parse_args(argv)

    roots = args.roots or sorted(ROOT_MAP)
    through_year = args.through_year or datetime.now(tz=timezone.utc).year
    today = datetime.now(tz=timezone.utc).date()

    if args.mode == "incremental":
        since = (datetime.strptime(args.since, "%Y-%m-%d").date() if args.since
                 else today - timedelta(days=max(1, args.lookback_days)))
        args.since = since.isoformat()
        units = [(ROOT_MAP[r][0], r, since.year) for r in roots]
    else:
        units = select_units(roots, args.years, through_year)
    if not units:
        logger.error("no (root, year) units selected")
        return 1

    if args.dry_run:
        print(f"units: {len(units)}")
        for dataset, root, year in units:
            ds = DATASET_SLUGS[dataset]
            print(f"  {dataset:<13s} {root:<4s} {year}  ->  "
                  f"s3://<bucket>/{raw_databento_key(ds, root, year, symbology_filename(root, year))}")
            print(f"                              "
                  f"s3://<bucket>/{raw_databento_key(ds, root, year, payload_filename(OHLCV_SCHEMA, root, year))}")
            if dataset in STATISTICS_DATASETS and not args.no_statistics:
                print(f"                              "
                      f"s3://<bucket>/{raw_databento_key(ds, root, year, payload_filename(STATISTICS_SCHEMA, root, year))}")
        return 0

    load_env()
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    client = make_client(load_api_key(args.secret_id, aws_region))

    if args.cost_only:
        if args.max_usd > HARD_CEILING_USD:
            logger.error("--max-usd %.2f exceeds the hard ceiling %.2f (the credit pool) -- "
                         "refusing to quote against a ceiling that cannot be honoured",
                         args.max_usd, HARD_CEILING_USD)
            return 1
        # An incremental quote must price the INCREMENTAL window, not the calendar year it lands in.
        override = None
        if args.mode == "incremental":
            override = (args.since, (today + timedelta(days=1)).isoformat())
        table = build_cost_table(client, units, with_statistics=not args.no_statistics,
                                 window_override=override)
        print(render_cost_table(table))
        # Fail-closed: a zero drop count means the outright filter did not run, and buying on that
        # basis is how a $140.31 parent-symbology pull happens.
        if table["zero_drop_roots"]:
            return 1
        if table["grand_total_usd"] > args.max_usd:
            logger.error("BUDGET GATE: grand total $%.4f exceeds --max-usd $%.2f -- refusing. The "
                         "recommended buy is $45.00; $140.31 is the naive parent-symbology pull "
                         "the outright filter exists to prevent",
                         table["grand_total_usd"], args.max_usd)
            print(f"BUDGET GATE FAILED: {table['grand_total_usd']:.4f} > --max-usd {args.max_usd:.2f}")
            return 1
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    import tempfile
    out_dir = args.download_dir or tempfile.mkdtemp(prefix="databento_")

    failures = 0
    for dataset, root, year in units:
        ds = DATASET_SLUGS[dataset]
        try:
            art = resolve_outrights(client, dataset=dataset, root=root, year=year)
            if args.mode == "incremental":
                since = datetime.strptime(args.since, "%Y-%m-%d").date()
                art["window"] = {"start": since.isoformat(),
                                 "end_exclusive": (today + timedelta(days=1)).isoformat()}
                art["mode"] = "incremental"
            as_of = today.strftime("%Y%m%d") if args.mode == "incremental" else None

            sym_key = raw_databento_key(ds, root, year, symbology_filename(root, year))
            land_bytes(bucket, sym_key,
                       json.dumps(art, indent=2, sort_keys=True, ensure_ascii=True).encode("utf-8"),
                       source_label=f"databento symbology.resolve {dataset} {root}.FUT {year}",
                       content_type="application/json", region=aws_region,
                       min_size_source="databento_symbology")
            if not art["outright_symbols"]:
                logger.warning("%s %s/%s: no outrights -- nothing to buy", dataset, root, year)
                continue

            schemas = [OHLCV_SCHEMA]
            if dataset in STATISTICS_DATASETS and not args.no_statistics:
                schemas.append(STATISTICS_SCHEMA)
            for schema in schemas:
                key = raw_databento_key(ds, root, year, payload_filename(schema, root, year, as_of))
                if not args.force_overwrite and raw_exists(bucket, key, aws_region):
                    logger.info("skip %s (raw exists; --force-overwrite to replace)", key)
                    continue
                job = submit_unit(client, art, schema)
                job_id = job["id"]
                paths = wait_and_download(client, job_id, out_dir,
                                          poll_seconds=args.poll_seconds,
                                          max_wait_seconds=args.max_wait_seconds)
                payloads = [p for p in paths if p.endswith(".dbn.zst")]
                if len(payloads) != 1:
                    raise RuntimeError(
                        f"{root}/{year} {schema}: expected exactly ONE .dbn.zst from job {job_id} "
                        f"(split_duration='none'), got {len(payloads)}: {payloads}")
                with open(payloads[0], "rb") as fh:
                    data = fh.read()
                land_bytes(bucket, key, data,
                           source_label=f"databento batch {dataset} {schema} {root} job={job_id}",
                           content_type="application/zstd", region=aws_region,
                           min_size_source="databento")
        except SystemExit:
            raise
        except Exception:  # noqa: BLE001 -- one unit's failure must not abort the rest
            logger.exception("FAILED %s %s/%s", dataset, root, year)
            failures += 1

    logger.info("done -- units=%d failures=%d", len(units), failures)
    return 1 if failures else 0


def wait_and_download(client, job_id: str, out_dir: str, *, poll_seconds: int = 30,
                      max_wait_seconds: int = 7200) -> list[str]:
    """Poll a batch job to ``done``, then download its files individually.

    ``list_jobs`` default filter hides EXPIRED, which is the only client-observable signal that the
    free 30-day re-download window has closed -- so it is polled explicitly here."""
    waited = 0
    while waited <= max_wait_seconds:
        detail = call_with_backoff(client.batch.get_job_details, job_id)
        state = str(detail.get("state", "")).lower()
        if state == "done":
            return download_job_files(client, job_id, out_dir)
        if state == "expired":
            raise RuntimeError(f"job {job_id} is EXPIRED -- the free 30-day re-download window "
                               f"has closed; a re-submit is a NEW charge")
        time.sleep(poll_seconds)
        waited += poll_seconds
    raise TimeoutError(f"job {job_id} did not reach 'done' within {max_wait_seconds}s")


if __name__ == "__main__":
    raise SystemExit(main())
