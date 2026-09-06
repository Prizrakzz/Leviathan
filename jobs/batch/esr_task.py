"""USDA FAS Export Sales Reporting (ESR) raw -> bronze Batch task.

Processes raw ESR JSON files from S3 raw/ and writes per-(commodity, year,
as_of_date) bronze Parquets.

Key design
----------
Two raw key shapes exist:

  Backfill  raw/production/source=usda_esr/
                commodity_code={code}/market_year={year}/all_countries.json
  Weekly    raw/production/source=usda_esr/
                commodity_code={code}/market_year={year}/as_of={YYYYMMDD}/all_countries.json

THE VINTAGE LAW (C-F1, 2026-09-04)
----------------------------------
A bronze partition's ``as_of`` comes from the RAW KEY, or from the raw object's
``raw_meta`` sidecar -- **never from today's date**.  ``silver_esr_compact`` is
the per-week point-in-time surface (INV-3); a vintage stamped "today" onto an
undated payload is a point-in-time that never existed, and it is indistinguishable
downstream from a real one.

Resolution order, one implementation (:func:`resolve_as_of`):

  1. the key's own ``as_of=YYYYMMDD`` segment      -> provenance ``raw_key``
  2. an EXPLICIT ``--backfill-as-of YYYYMMDD``     -> provenance ``operator``
  3. ``raw_meta/<raw_key>_meta.json``'s ``download_timestamp`` date, i.e. the day
     the bytes were actually fetched                -> provenance ``raw_meta``
  4. nothing  -> the key is REFUSED (counted, logged, never written)

Undated (backfill-shaped) raw keys are OUT OF SCOPE unless ``--include-backfill``
is passed.  MEASURED 2026-09-04 on ``s3://leviathan-dev-shahem-001``: the raw
prefix holds 1,901 JSON objects, of which 446 carry an ``as_of=`` segment and
1,455 do not.  Before this law the undated 1,455 were admitted by every run and
stamped with the run date, so a scheduled weekly fire minted a whole fabricated
vintage; now the default run touches only the 446 dated keys.

S3 key structure
----------------
  Bronze: bronze/production/source=usda_esr/
              commodity_code={code}/
              market_year={year}/
              as_of={YYYYMMDD}/
              part-000.parquet

Targeted re-bronze (``--as-of-min``)
------------------------------------
Bronze is strictly INCREMENTAL: ``_process`` returns ``"skipped"`` whenever the
bronze key already exists and ``--force-overwrite`` was not passed, and the
scheduled chain passes no ``--force-overwrite``.  So a transform change reaches
FUTURE as_of partitions only; vintages already bronzed by the old transform keep
the old column set forever.

A blanket ``--force-overwrite`` is the wrong tool for that: it would rewrite the
ENTIRE bronze history purely to add all-NULL columns to raw payloads that never
carried the fields.  So ``--force-overwrite`` REQUIRES ``--as-of-min``: there is
no default bound, because a default bound is a default that selects everything.
``--as-of-min YYYYMMDD`` narrows the rewrite to the vintages whose RAW actually
carries the new fields -- a bound that is MEASURED, never assumed.  For the
SILVER-F030 BF-W2 net-commitment five that measurement is
``jobs/utils/esr_netcommitment_raw_census.py``, which read all 446 dated raw
objects on 2026-09-04 and found every one of the 12 as_of vintages carrying all
five keys, so the bound is the earliest vintage raw holds:

    python jobs/batch/esr_task.py --force-overwrite --as-of-min 20260712

The bound is judged on the key's OWN ``as_of=`` segment.  An undated key has no
vintage to compare, so it is DROPPED from a bounded run (counted as
``dropped_undated=``) unless the operator both passes ``--include-backfill`` and
declares the vintage with ``--backfill-as-of``; the combination without the
declaration is refused rather than silently judged on a fetched-per-key date.

Read the terminal line: ``written=0`` means the filter matched nothing and any
measurement downstream of the run is vacuous; ``refused=`` counts admitted keys
whose vintage could not be resolved honestly.

Usage
-----
    python jobs/batch/esr_task.py [--bucket B] [--aws-region R]

Targeted re-bronze of the vintages that carry a newly-promoted field:
    python jobs/batch/esr_task.py --force-overwrite --as-of-min 20260712

Backfill (undated) keys, dated from their raw_meta sidecars:
    python jobs/batch/esr_task.py --include-backfill

Smoke test (first 5 files):
    python jobs/batch/esr_task.py --limit 5
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_esr_key, parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.usda_esr import transform_esr_json_to_bronze

logger = get_logger("esr_task")

_RAW_PREFIX = "raw/production/source=usda_esr/"
# The raw_meta sidecar the fetcher writes next to every raw object
# (leviathan.storage.raw_metadata.write_raw_s3_metadata): raw_meta/<raw_key>_meta.json.
_RAW_META_PREFIX = "raw_meta/"
_WORKERS = 16

# Matches the as_of partition in a weekly raw key, e.g. "as_of=20260522"
_AS_OF_RE = re.compile(r"as_of=(\d{8})")
# The leading YYYY-MM-DD of the sidecar's ISO-8601 download_timestamp, e.g. "2026-07-12T13:02:44Z".
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _bronze_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _validate_yyyymmdd(value: str, flag: str) -> str:
    """FAIL-CLOSED on a date-shaped CLI argument.

    A malformed bound must stop the run, never match nothing: a silently-empty
    match looks exactly like "the filter worked and there was nothing to do", and
    the operator's next action is to read ``written=`` and decide whether the
    measurement downstream is real.  The empty string is included -- it is the
    one shell/JSON form that yields a zero-length argument.
    """
    if not (len(value) == 8 and value.isdigit()):
        raise ValueError(
            f"{flag} must be YYYYMMDD (8 digits), got {value!r}. Refusing to run: an unparseable "
            "bound would silently select the wrong key set and look like a clean no-op."
        )
    return value


def _as_of_from_raw_key(raw_key: str) -> str | None:
    """The ``YYYYMMDD`` vintage the RAW KEY ITSELF carries, or ``None``.

    Weekly keys carry it in their ``as_of=`` partition.  Backfill keys carry no
    vintage at all -- and ``None`` is the honest answer, never today's date.
    """
    m = _AS_OF_RE.search(raw_key)
    return m.group(1) if m else None


def _as_of_from_raw_meta(s3_client, bucket: str, raw_key: str) -> str | None:
    """The ``YYYYMMDD`` the raw_meta sidecar records the bytes were FETCHED on.

    ``leviathan.storage.raw_metadata.write_raw_s3_metadata`` writes
    ``raw_meta/<raw_key>_meta.json`` beside every raw object with a
    ``download_timestamp``.  For an undated payload that fetch date is the only
    honest vintage there is: it is what was knowable when the bytes landed.

    Best-effort by construction -- the sidecar write is itself best-effort, so a
    missing or unparseable sidecar returns ``None`` and the caller REFUSES the
    key rather than inventing a date.
    """
    meta_key = f"{_RAW_META_PREFIX}{raw_key}_meta.json"
    try:
        body = s3_client.get_object(Bucket=bucket, Key=meta_key)["Body"].read()
        stamp = json.loads(body).get("download_timestamp")
    except Exception:  # noqa: BLE001 -- a missing/garbled sidecar is a refusal, not a crash
        return None
    if not isinstance(stamp, str):
        return None
    m = _ISO_DATE_RE.match(stamp)
    return f"{m.group(1)}{m.group(2)}{m.group(3)}" if m else None


def resolve_as_of(
    raw_key: str, s3_client, bucket: str, backfill_as_of: str | None
) -> tuple[str | None, str]:
    """Return ``(as_of_YYYYMMDD, provenance)`` for a raw key -- THE VINTAGE LAW.

    Provenance is one of ``raw_key`` / ``operator`` / ``raw_meta``, or
    ``unresolvable`` with a ``None`` date.  There is deliberately no
    today's-date branch: see the module docstring.
    """
    own = _as_of_from_raw_key(raw_key)
    if own is not None:
        return own, "raw_key"
    if backfill_as_of is not None:
        return backfill_as_of, "operator"
    stamped = _as_of_from_raw_meta(s3_client, bucket, raw_key)
    if stamped is not None:
        return stamped, "raw_meta"
    return None, "unresolvable"


def _filter_by_as_of_min(
    raw_keys: list[str],
    as_of_min: str | None,
    *,
    include_backfill: bool = False,
    backfill_as_of: str | None = None,
) -> tuple[list[str], int]:
    """Keep the raw keys whose OWN as_of is >= *as_of_min*; return ``(kept, dropped_undated)``.

    Zero-padded ``YYYYMMDD`` sorts lexicographically the way it sorts
    chronologically, so a string compare is the whole test.

    An UNDATED key has no vintage to compare and is dropped -- counted, not
    silently swept in.  Admitting it on a fallback date is the C-F1 defect: with
    a today's-date fallback every one of the 1,455 undated raw objects satisfies
    any bound, so a flag advertised as narrowing the rewrite opened it to the
    whole history.  ``include_backfill`` + an EXPLICIT ``backfill_as_of`` is the
    only way in, because that is the only way the operator has declared a vintage
    the bound can honestly be judged against.
    """
    if as_of_min is None:
        return raw_keys, 0
    _validate_yyyymmdd(as_of_min, "--as-of-min")
    admit_undated = include_backfill and backfill_as_of is not None
    kept: list[str] = []
    dropped_undated = 0
    for key in raw_keys:
        as_of = _as_of_from_raw_key(key)
        if as_of is None:
            if not admit_undated:
                dropped_undated += 1
                continue
            as_of = backfill_as_of
        if as_of >= as_of_min:
            kept.append(key)
    return kept, dropped_undated


def select_raw_keys(raw_keys: list[str], args) -> list[str]:
    """Every CLI-level selection rule, in ONE seam so main()'s gates are testable.

    Order: the force/bound covenant, then the undated-key admission gate, then the
    vintage bound, then ``--limit``.  Raises ``ValueError`` on any refusal.
    """
    if args.force_overwrite and args.as_of_min is None:
        raise ValueError(
            "--force-overwrite requires --as-of-min: an unbounded forced rewrite would re-bronze "
            "the ENTIRE history to add all-NULL columns to payloads that never carried the "
            "fields. Name the vintage bound (e.g. --as-of-min 20260712)."
        )
    if args.backfill_as_of is not None:
        _validate_yyyymmdd(args.backfill_as_of, "--backfill-as-of")

    if not args.include_backfill:
        dated = [k for k in raw_keys if _as_of_from_raw_key(k) is not None]
        undated = len(raw_keys) - len(dated)
        if undated:
            logger.warning(
                "skipped %d undated raw key(s) (no as_of= segment): a bronze partition's as_of "
                "comes from the raw key or the raw_meta sidecar, NEVER from today's date. Pass "
                "--include-backfill to admit them.", undated,
            )
        raw_keys = dated
    elif args.as_of_min is not None and args.backfill_as_of is None:
        raise ValueError(
            "--include-backfill with --as-of-min requires an explicit --backfill-as-of: an "
            "undated key carries no vintage, so a bound cannot judge it. Declare the vintage or "
            "drop --include-backfill."
        )

    if args.as_of_min is not None:
        before = len(raw_keys)
        raw_keys, dropped_undated = _filter_by_as_of_min(
            raw_keys, args.as_of_min,
            include_backfill=args.include_backfill, backfill_as_of=args.backfill_as_of,
        )
        logger.info(
            "as-of-min=%s  selected=%d of %d raw key(s)  (dropped=%d, of which undated=%d)",
            args.as_of_min, len(raw_keys), before, before - len(raw_keys), dropped_undated,
        )

    if args.limit:
        raw_keys = raw_keys[: args.limit]
    return raw_keys


def _process(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    backfill_as_of: str | None,
    ingest_date: str,
) -> tuple[str, str]:
    s3 = get_thread_local_s3_client(aws_region)

    commodity_code_str = parse_hive_key(raw_key, "commodity_code")
    market_year_str = parse_hive_key(raw_key, "market_year")

    if not commodity_code_str or not market_year_str:
        logger.warning("Could not parse commodity_code/market_year from key: %s", raw_key)
        return "error", raw_key

    try:
        commodity_code = int(commodity_code_str)
        market_year = int(market_year_str)
    except ValueError:
        logger.warning("Non-integer commodity_code/market_year in key: %s", raw_key)
        return "error", raw_key

    as_of_date, provenance = resolve_as_of(raw_key, s3, bucket, backfill_as_of)
    if as_of_date is None:
        # THE VINTAGE LAW: no key segment, no operator declaration, no sidecar -> no honest as_of.
        # Refusing costs one payload; stamping today's date mints a point-in-time that never
        # existed in the surface whose entire purpose is point-in-time honesty.
        logger.debug("no resolvable as_of for %s -- refused (INV-3)", raw_key)
        return "refused", raw_key
    if provenance != "raw_key":
        logger.debug("as_of=%s for %s resolved from %s", as_of_date, raw_key, provenance)
    b_key = bronze_esr_key(commodity_code, market_year, as_of_date)

    if not force_overwrite and _bronze_exists(s3, bucket, b_key):
        return "skipped", raw_key

    try:
        raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return "error", raw_key

    try:
        df = transform_esr_json_to_bronze(
            raw_bytes,
            commodity_code=commodity_code,
            market_year=market_year,
            as_of_date=as_of_date,
            ingest_date=ingest_date,
        )
    except (ValueError, Exception) as exc:  # noqa: BLE001
        logger.error("ESR transform failed  key=%s: %s", raw_key, exc)
        return "error", raw_key

    try:
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        s3.put_object(
            Bucket=bucket,
            Key=b_key,
            Body=buf.getvalue(),
            ContentType="application/octet-stream",
        )
        logger.info(
            "bronze written  commodity=%d  year=%d  as_of=%s  rows=%d  %s",
            commodity_code, market_year, as_of_date, len(df), b_key,
        )
        return "written", raw_key
    except Exception as exc:  # noqa: BLE001
        logger.error("Parquet write failed  key=%s: %s", raw_key, exc)
        return "error", raw_key


def build_parser() -> argparse.ArgumentParser:
    """The CLI surface, factored out so the refusal gates are testable without AWS."""
    parser = argparse.ArgumentParser(description="USDA ESR raw -> bronze")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true",
                        help="Rewrite bronze objects that already exist. REQUIRES --as-of-min.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap the number of raw keys processed (smoke test)")
    parser.add_argument(
        "--include-backfill",
        action="store_true",
        dest="include_backfill",
        help="Admit UNDATED raw keys (no as_of= partition). Their bronze as_of is then taken from "
             "an explicit --backfill-as-of, else from the raw_meta sidecar's download_timestamp; "
             "a key with neither is REFUSED. Never today's date.",
    )
    parser.add_argument(
        "--backfill-as-of",
        default=None,
        dest="backfill_as_of",
        help="YYYYMMDD vintage to DECLARE for undated keys. No default: an undated key's as_of "
             "comes from the raw_meta sidecar when this is absent, never from the run date.",
    )
    parser.add_argument(
        "--as-of-min",
        default=None,
        dest="as_of_min",
        help="YYYYMMDD lower bound: process only raw keys whose OWN as_of is >= this. Required by "
             "--force-overwrite, so a targeted re-bronze can never widen into the whole history.",
    )
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )

    load_env()

    args = build_parser().parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    today = datetime.now(timezone.utc)
    # NOTE the absence: there is no today's-date fallback for backfill_as_of. today is the INGEST
    # date (when this run read the bytes), never the VINTAGE (when the bytes were knowable).
    backfill_as_of = args.backfill_as_of
    ingest_date = today.date().isoformat()

    raw_keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=".json", aws_region=aws_region)
    raw_keys.sort()

    logger.info(
        "ESR task  bucket=%s  raw_keys=%d  force=%s  include_backfill=%s  backfill_as_of=%s  "
        "as_of_min=%s",
        bucket, len(raw_keys), args.force_overwrite, args.include_backfill,
        backfill_as_of, args.as_of_min,
    )

    try:
        raw_keys = select_raw_keys(raw_keys, args)
    except ValueError as exc:
        logger.error("REFUSING: %s", exc)
        sys.exit(2)

    start = datetime.now(timezone.utc)
    written = skipped = errors = refused = 0

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {
            pool.submit(
                _process,
                key,
                bucket,
                aws_region,
                args.force_overwrite,
                backfill_as_of,
                ingest_date,
            ): key
            for key in raw_keys
        }
        refused_samples: list[str] = []
        for fut in as_completed(futures):
            try:
                status, key = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error: %s", exc)
                errors += 1
                continue
            if status == "written":
                written += 1
            elif status == "skipped":
                skipped += 1
            elif status == "refused":
                refused += 1
                if len(refused_samples) < 3:
                    refused_samples.append(key)
            else:
                errors += 1

    if refused:
        logger.warning(
            "REFUSED %d admitted key(s) with no resolvable as_of (no as_of= segment, no "
            "--backfill-as-of, no raw_meta sidecar). Nothing was written for them: a bronze "
            "partition's as_of never comes from today's date. Sample: %s",
            refused, ", ".join(refused_samples),
        )

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  written=%d  skipped=%d  refused=%d  errors=%d  elapsed=%.1fs",
        written, skipped, refused, errors, elapsed,
    )

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
