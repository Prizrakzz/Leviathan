#!/usr/bin/env python
"""D-LD Track U -- UNICA bi-weekly CONTENT REPAIR: land the missing 2026/2027 bulletins from Wayback.

WHY THIS JOB EXISTS
-------------------
unica biweekly silver content ends at fortnight 2026-02-01.  The Apr..Aug 2026 bulletins (the
open 2026/2027 season) were never captured, and they cannot be re-fetched from the origin:
UNICADATA's listing page (``listagem.php?idMn=63``) is fully JS-rendered and serves EXACTLY ONE
bulletin -- the current one -- with no archive and no harvest-year select (measured on the
2026-08-12 fire: "found 1 download_media.php links").  Once a fortnight rolls over, the previous
bulletin is simply gone from the portal.

The recorded backfill route is therefore the Wayback Machine's CDX index.  This job is the
CDX-pinned half of the repair; ``jobs/ingest/fetch_unica_biweekly.py`` keeps owning the live
current-bulletin path and ``jobs/ingest/discover_unica_wayback.py`` keeps owning manifest
reconnaissance (report-only, no downloads).  This job is the one that LANDS BYTES.

A WAYBACK TIMESTAMP IS A REQUEST, NOT A GUARANTEE
--------------------------------------------------
``/web/{ts}id_/{url}`` does not 404 on an unmatched timestamp -- it 200s with the NEAREST
capture, and those bytes then wear the requested timestamp in the raw key forever (the CEPEA
nine-year hole, W1a 2026-07-29).  So every capture here is PINNED from the CDX index and the
SERVED capture is read back off the response and compared; drift is REFUSED, never landed.  The
law and its two helpers live in ``leviathan.common.wayback``.

WHAT "THE WINDOW" MEANS
-----------------------
``--from``/``--to`` bound the PUBLICATION month (the ``/arquivos/pdfs/YYYY/MM/`` segment of the
bulletin URL), not the capture date.  Publication is what decides the season label and therefore
the S3 partition; capture date is an accident of when the crawler happened to visit (the April
2026 bulletin was captured in May).  Default window: 2026-04-01 .. today, i.e. exactly the
2026/2027 season to date.

SEASON LABELLING
----------------
By PUBLICATION MONTH, via ``leviathan.common.unica_bulletins.season_for_publication`` -- the
same rule ``_extract_current_bulletin`` now applies, and the same rule that idm=32820684 was
mislabelled against.  A capture's own URL is the evidence; nothing here takes a season from a
caller, a loop variable or an existing key.

S3 LAYOUT (the normal raw layout -- nothing bespoke)
----------------------------------------------------
    raw/production/source=unica_biweekly/harvest_year={YYYY_YYYY}/idm=pdf_{hash}/report.pdf
    raw_meta/<that key>_meta.json      (carries wayback_capture_ts + cdx_digest, see below)

IDEMPOTENCE IS CONTENT-AWARE, NOT EXISTENCE-BASED
--------------------------------------------------
Two tiers, because existence-based skipping is the exact defect this wave is repairing:
  tier 1 (pre-download, cheap): the companion metadata already records THIS capture
        (``wayback_capture_ts`` + ``cdx_digest`` both match the pin) -> skip, no HTTP.
  tier 2 (post-download):       the landed object's ``sha256`` equals the fresh bytes' sha256
        -> skip the PUT.  Re-uploading identical bytes would bump LastModified and force a
        pointless bronze rebuild through the staleness fence.
``--force`` overrides both.

Usage
-----
    # what would be pinned and landed -- no downloads, no writes
    python jobs/ingest/backfill_unica_wayback.py --dry-run

    # the repair itself (default window = the open season)
    python jobs/ingest/backfill_unica_wayback.py

    # an explicit window, and record the captures in the bulletin manifest
    python jobs/ingest/backfill_unica_wayback.py --from 2026-04-01 --to 2026-08-18 \
        --update-manifest
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests  # noqa: E402
from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.dates import coerce_date  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.common.unica_bulletins import (  # noqa: E402
    MIN_PDF_BYTES,
    PDF_MAGIC,
    parse_pdf_url,
    relabel_reason,
    season_for_publication,
)
from leviathan.common.wayback import capture_drift, replay_url, served_capture_ts  # noqa: E402
from leviathan.storage.paths import unica_biweekly_raw_key  # noqa: E402

logger = get_logger("backfill_unica_wayback")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent / "configs" / "sources" / "unica_biweekly_manifest.yaml"
)

# Bounded, one query per calendar year the window spans.  A single wildcard across all years
# reliably times out on the CDX API (the lesson already baked into discover_unica_wayback.py).
_CDX_YEAR_TMPL = (
    "https://web.archive.org/cdx/search/cdx"
    "?url=unicadata.com.br/arquivos/pdfs/{year}/*"
    "&output=json"
    "&fl=timestamp,original,digest,statuscode,mimetype"
    "&filter=statuscode:200"
    "&collapse=digest"
    "&limit={limit}"
)

_CDX_TIMEOUT_S = 90
_CDX_LIMIT = 2000
_SLEEP_BETWEEN_CDX_S = 1.5
_DOWNLOAD_TIMEOUT_S = 120
_SLEEP_BETWEEN_DOWNLOADS_S = 2.5
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 10
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

_CONTENT_TYPE = "application/pdf"
_USER_AGENT = "Leviathan-UNICA-Backfill/1.0 (research; non-commercial)"

_DEFAULT_FROM = "2026-04-01"


# ---------------------------------------------------------------------------
# HTTP seam (single place tests monkeypatch; nothing else in this module calls the network)
# ---------------------------------------------------------------------------

def _http_get(url: str, *, timeout: int) -> "requests.Response":
    """GET with bounded retries on the transient statuses Wayback actually returns."""
    backoff = _BACKOFF_SECONDS
    last_error: Optional[Exception] = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=timeout)
            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                logger.warning(
                    "wayback returned HTTP %d (attempt %d/%d) -- retrying in %ds: %s",
                    resp.status_code, attempt, _MAX_ATTEMPTS, backoff, url,
                )
            else:
                resp.raise_for_status()
                return resp
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= _MAX_ATTEMPTS:
                break
            logger.warning(
                "wayback fetch failed (attempt %d/%d): %s -- retrying in %ds",
                attempt, _MAX_ATTEMPTS, exc, backoff,
            )
        time.sleep(backoff)
        backoff *= 2
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"failed to fetch {url} after {_MAX_ATTEMPTS} attempts")


# ---------------------------------------------------------------------------
# Phase A -- CDX index: pin captures that provably EXIST
# ---------------------------------------------------------------------------

def cdx_digest(payload: bytes) -> str:
    """The CDX ``digest`` form of *payload*: unpadded base32 of its SHA-1."""
    return base64.b32encode(hashlib.sha1(payload).digest()).decode("ascii").rstrip("=")


def _window_years(window_from: date, window_to: date) -> list[int]:
    return list(range(window_from.year, window_to.year + 1))


def fetch_cdx_rows(years: list[int], *, limit: int = _CDX_LIMIT) -> list[dict[str, Any]]:
    """CDX rows for unicadata bulletin PDFs published in *years* (one bounded query per year)."""
    rows: list[dict[str, Any]] = []
    for i, year in enumerate(years):
        url = _CDX_YEAR_TMPL.format(year=year, limit=limit)
        if i:
            time.sleep(_SLEEP_BETWEEN_CDX_S)
        logger.info("CDX %d: %s", year, url)
        try:
            data = json.loads(_http_get(url, timeout=_CDX_TIMEOUT_S).content)
        except Exception as exc:  # noqa: BLE001 -- one dead year must not sink the window
            logger.error("CDX %d: ERROR -- %s", year, exc)
            continue
        if not data or len(data) <= 1:
            logger.info("CDX %d: 0 rows", year)
            continue
        fields = data[0]
        year_rows = [dict(zip(fields, row)) for row in data[1:]]
        logger.info("CDX %d: %d rows", year, len(year_rows))
        rows.extend(year_rows)
    return rows


def pin_captures(
    rows: list[dict[str, Any]],
    window_from: date,
    window_to: date,
) -> list[dict[str, Any]]:
    """Turn raw CDX rows into PINNED capture records inside the PUBLICATION window.

    Pure -- no network, no clock.  One pin per distinct bulletin (``pdf_hash``); when a URL has
    several captures the NEWEST is pinned, because a re-capture of the same URL is UNICA
    replacing the file and the later bytes are the ones of record.
    """
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        original = row.get("original") or ""
        info = parse_pdf_url(original)
        if not info:
            continue
        published = date(info["pub_year"], info["pub_month"], 1)
        # Month granularity: a bulletin published in the window's first/last month counts.
        if published < window_from.replace(day=1) or published > window_to.replace(day=1):
            continue
        ts = str(row.get("timestamp") or "")
        if len(ts) != 14 or not ts.isdigit():
            continue
        pin = {
            **info,
            "timestamp": ts,
            "digest": row.get("digest") or "",
            "original": original,
            "replay_url": replay_url(ts, original),
            "s3_key": unica_biweekly_raw_key(info["harvest_year"], info["idm"]),
        }
        prior = best.get(info["pdf_hash"])
        if prior is None or pin["timestamp"] > prior["timestamp"]:
            best[info["pdf_hash"]] = pin
    return sorted(best.values(), key=lambda p: (p["published_ym"], p["timestamp"]))


# ---------------------------------------------------------------------------
# Phase B -- download, then VERIFY the served capture against the pin
# ---------------------------------------------------------------------------

def verify_payload(
    pin: dict[str, Any],
    payload: bytes,
    served: Optional[str],
    *,
    strict_digest: bool = False,
) -> Optional[str]:
    """``None`` when these bytes may be landed under *pin*'s provenance, else the refusal reason.

    Three checks, in the order that makes the cheapest true statement first:

      1. CAPTURE DRIFT (hard).  The estate law: an unmatched timestamp 200s with the NEAREST
         capture.  If the response does not name the pinned capture, these bytes belong to some
         other day and must not wear this key.
      2. PAYLOAD SHAPE (hard).  Wayback serves an HTML "not archived" placeholder with HTTP 200,
         and UNICADATA's CMS serves a sub-minimum stand-in PDF for a pruned bulletin -- so the
         %PDF magic and the size floor are the real presence tests, not the status code.
      3. CDX DIGEST (soft by default, hard under --strict-digest).  The CDX ``digest`` column is
         documented as unpadded base32 of the payload SHA-1, and ``cdx_digest`` recomputes
         exactly that.  It is SOFT by default on purpose: this equality has never been MEASURED
         in this repo (revisit records and transfer encodings are known to complicate it), and
         an unverified assumption must not be able to block a repair on its first ever run.  A
         mismatch is logged loudly and recorded in the raw metadata either way; once a real run
         shows the digests matching, flip the default.
    """
    drift = capture_drift(pin["timestamp"], served, what="these bulletin bytes")
    if drift:
        return drift
    if not payload.startswith(PDF_MAGIC):
        return (
            f"the response is not a PDF (first bytes {payload[:16]!r}) -- wayback served its "
            f"HTML placeholder, so capture {pin['timestamp']} does not hold this bulletin"
        )
    if len(payload) < MIN_PDF_BYTES:
        return (
            f"PDF too small ({len(payload):,} bytes, floor {MIN_PDF_BYTES:,}) -- a pruned/error "
            f"stand-in, not a bulletin"
        )
    pinned_digest = str(pin.get("digest") or "")
    if pinned_digest:
        actual = cdx_digest(payload)
        if actual != pinned_digest:
            message = (
                f"CDX digest mismatch: index pinned {pinned_digest}, payload hashes to {actual}"
            )
            if strict_digest:
                return message + " -- refused under --strict-digest"
            logger.warning("%s -- landing anyway (digest check is soft by default)", message)
    return None


def download_capture(pin: dict[str, Any]) -> tuple[bytes, Optional[str]]:
    """The archived bytes AND the capture timestamp Wayback actually served."""
    resp = _http_get(pin["replay_url"], timeout=_DOWNLOAD_TIMEOUT_S)
    return resp.content, served_capture_ts(resp)


# ---------------------------------------------------------------------------
# Content-aware skip
# ---------------------------------------------------------------------------

def _read_raw_meta(s3_client: Any, bucket: str, s3_key: str) -> Optional[dict[str, Any]]:
    try:
        body = s3_client.get_object(Bucket=bucket, Key=f"raw_meta/{s3_key}_meta.json")["Body"].read()
        return json.loads(body)
    except Exception:  # noqa: BLE001 -- absent / unreadable metadata both mean "unknown"
        return None


def capture_already_landed(meta: Optional[dict[str, Any]], pin: dict[str, Any]) -> bool:
    """Tier-1 skip: the companion metadata records THIS EXACT capture.

    Existence of the object is deliberately NOT sufficient -- that predicate is the defect this
    wave repairs.  Both the pinned capture timestamp AND the pinned CDX digest must match, so a
    re-captured (replaced) bulletin re-lands instead of being skipped forever.
    """
    if not meta:
        return False
    if str(meta.get("wayback_capture_ts") or "") != str(pin["timestamp"]):
        return False
    pinned_digest = str(pin.get("digest") or "")
    if not pinned_digest:
        return False
    return str(meta.get("cdx_digest") or "") == pinned_digest


def payload_unchanged(meta: Optional[dict[str, Any]], payload: bytes) -> bool:
    """Tier-2 skip: the landed object already holds byte-identical content."""
    if not meta:
        return False
    return str(meta.get("sha256") or "") == hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Manifest append (same shape discover_unica_wayback.py writes)
# ---------------------------------------------------------------------------

_YAML_ENTRY_TMPL = """\
  - harvest_year: "{harvest_year}"
    idm: "{idm}"
    bulletin_num: None
    published_ym: "{published_ym}"
    pdf_url: '{pdf_url}'
    download_url: null
"""


def append_to_manifest(pins: list[dict[str, Any]], manifest_path: Path = _MANIFEST_PATH) -> int:
    """Append pinned captures the manifest does not already carry.  Returns rows added.

    ``pdf_url`` is written as the PINNED REPLAY URL, not the origin URL: the origin prunes
    bulletins the moment the next fortnight publishes, so the replay URL is the only address
    that reproduces these exact bytes.
    """
    original = manifest_path.read_text(encoding="utf-8")
    fresh = [p for p in pins if f'idm: "{p["idm"]}"' not in original]
    if not fresh:
        return 0
    blocks = [
        _YAML_ENTRY_TMPL.format(
            harvest_year=p["harvest_year"],
            idm=p["idm"],
            published_ym=p["published_ym"],
            pdf_url=p["replay_url"],
        )
        for p in sorted(fresh, key=lambda x: (x["harvest_year"], x["published_ym"]))
    ]
    manifest_path.write_text(original.rstrip() + "\n" + "".join(blocks), encoding="utf-8")
    return len(fresh)


# ---------------------------------------------------------------------------
# Run gating -- a backfill that lands nothing must never look green
# ---------------------------------------------------------------------------

def exit_reason(
    landed: int,
    skipped: int,
    rejected: int,
    errors: int,
    candidates: int,
    *,
    allow_empty: bool = False,
) -> Optional[str]:
    """A SystemExit message when the run must fail, else ``None``.

    Mirrors ``fetch_unica_biweekly._exit_reason`` in spirit: the whole point of this wave is that
    a leg which achieves nothing must not exit 0.  ZERO CANDIDATES is the shape that matters --
    the archive simply may not hold the fortnights we need, and that is a finding to surface,
    not a success to log.
    """
    if errors:
        return f"{errors} capture(s) failed -- see logs above."
    if rejected and not landed and not skipped:
        return (
            f"{rejected} capture(s) REFUSED (drift/placeholder) and nothing landed -- "
            "the pins are wrong or the captures are placeholders; re-pin from the CDX index."
        )
    if candidates == 0 and not allow_empty:
        return (
            "ZERO CANDIDATES: the CDX index holds no bulletin captures published inside the "
            "window. The gap is NOT recoverable from the archive for this window -- widen it, "
            "or accept the hole explicitly with --allow-empty rather than exiting green."
        )
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill UNICA bi-weekly bulletins from CDX-pinned Wayback captures into raw S3. "
            "The window bounds the PUBLICATION month, not the capture date."
        )
    )
    parser.add_argument(
        "--from", dest="window_from", default=_DEFAULT_FROM,
        help=f"First publication month to backfill, ISO date (default: {_DEFAULT_FROM}).",
    )
    parser.add_argument(
        "--to", dest="window_to", default=None,
        help="Last publication month to backfill, ISO date (default: today).",
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Query the CDX index and print the pinned captures + target keys; no downloads, no writes.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-download and re-upload even when the landed object already holds this capture.",
    )
    parser.add_argument(
        "--strict-digest", action="store_true",
        help="Refuse a payload whose SHA-1 does not match the CDX digest (default: warn only).",
    )
    parser.add_argument(
        "--update-manifest", action="store_true",
        help="Append the pinned captures to configs/sources/unica_biweekly_manifest.yaml.",
    )
    parser.add_argument(
        "--allow-empty", action="store_true",
        help="Exit 0 when the window holds no captures (default: refuse -- a no-op must not look green).",
    )
    parser.add_argument("--limit", type=int, default=0, help="Process at most N captures (smoke tests).")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    args = _parse_args(argv)

    window_from = coerce_date(args.window_from)
    window_to = coerce_date(args.window_to)
    if window_to < window_from:
        raise SystemExit(f"--to {window_to} precedes --from {window_from}")

    seasons = sorted({
        season_for_publication(window_from.year, window_from.month),
        season_for_publication(window_to.year, window_to.month),
    })
    logger.info(
        "UNICA wayback backfill  publication window %s .. %s  (seasons touched: %s)",
        window_from, window_to, ", ".join(seasons),
    )

    # -- Phase A: pin ------------------------------------------------------
    rows = fetch_cdx_rows(_window_years(window_from, window_to))
    pins = pin_captures(rows, window_from, window_to)
    if args.limit:
        pins = pins[: args.limit]

    logger.info("CDX rows=%d  pinned captures in window=%d", len(rows), len(pins))
    for pin in pins:
        note = relabel_reason(pin["idm"], pin["harvest_year"])
        if note:
            logger.warning(note)
        logger.info(
            "  PIN  published=%s  capture=%s  digest=%s  -> %s",
            pin["published_ym"], pin["timestamp"], pin["digest"] or "(none)", pin["s3_key"],
        )

    if args.dry_run:
        print(f"pinned captures in window {window_from} .. {window_to}: {len(pins)}")
        for pin in pins:
            print(f"  published {pin['published_ym']}  season {pin['harvest_year']}")
            print(f"    capture : {pin['timestamp']}  digest {pin['digest'] or '(none)'}")
            print(f"    replay  : {pin['replay_url']}")
            print(f"    s3 key  : {pin['s3_key']}")
        print("(dry-run -- no downloads, no S3 writes)")
        reason = exit_reason(0, 0, 0, 0, len(pins), allow_empty=args.allow_empty)
        if reason:
            logger.error(reason)
            return 1
        return 0

    # -- Phase B: land -----------------------------------------------------
    load_env()
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    from leviathan.storage.raw_metadata import write_raw_s3_metadata
    from leviathan.storage.s3 import get_thread_local_s3_client, upload_bytes_to_s3

    s3_client = get_thread_local_s3_client(aws_region)

    landed = skipped = rejected = errors = 0
    for i, pin in enumerate(pins):
        meta = _read_raw_meta(s3_client, bucket, pin["s3_key"])
        if not args.force and capture_already_landed(meta, pin):
            logger.info("skip (capture already landed)  %s", pin["s3_key"])
            skipped += 1
            continue
        if i:
            time.sleep(_SLEEP_BETWEEN_DOWNLOADS_S)
        try:
            payload, served = download_capture(pin)
            bad = verify_payload(pin, payload, served, strict_digest=args.strict_digest)
            if bad:
                logger.error("REFUSED %s: %s", pin["replay_url"], bad)
                rejected += 1
                continue
            if not args.force and payload_unchanged(meta, payload):
                logger.info("skip (byte-identical to what is already landed)  %s", pin["s3_key"])
                skipped += 1
                continue
            upload_bytes_to_s3(payload, bucket, pin["s3_key"], aws_region)
            write_raw_s3_metadata(
                bucket, pin["s3_key"], payload, pin["replay_url"], _CONTENT_TYPE, aws_region,
                extra={
                    "wayback_capture_ts": pin["timestamp"],
                    "wayback_served_capture_ts": served,
                    "cdx_digest": pin["digest"],
                    "cdx_payload_digest": cdx_digest(payload),
                    "origin_url": pin["original"],
                    "published_ym": pin["published_ym"],
                    "harvest_year": pin["harvest_year"],
                    "backfill_job": "backfill_unica_wayback",
                },
            )
            logger.info(
                "landed  published=%s  capture=%s  (%.1f MB) -> s3://%s/%s",
                pin["published_ym"], pin["timestamp"], len(payload) / 1_048_576,
                bucket, pin["s3_key"],
            )
            landed += 1
        except Exception:  # noqa: BLE001 -- counted and logged; the window keeps going
            logger.exception("FAILED capture %s (%s)", pin["timestamp"], pin["replay_url"])
            errors += 1

    if args.update_manifest and landed:
        added = append_to_manifest(pins)
        logger.info("manifest: appended %d row(s) to %s", added, _MANIFEST_PATH.name)

    logger.info(
        "Done  landed=%d  skipped=%d  refused=%d  errors=%d  (candidates=%d)",
        landed, skipped, rejected, errors, len(pins),
    )
    reason = exit_reason(landed, skipped, rejected, errors, len(pins), allow_empty=args.allow_empty)
    if reason:
        logger.error(reason)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
