"""Probe and classify UNICADATA download_media.php IDs to find bi-weekly bulletins.

Four sub-commands
-----------------
--classify
    Query the Wayback Machine CDX for all unicadata.com.br/download_media.php
    URLs captured since 2021.  For each URL, HEAD-check the size, then download
    and classify the PDF using pdfplumber.
    Results are written (incrementally) to configs/sources/unica_biweekly_classified.json.

--fill-gaps
    Read classified.json, find gaps between consecutive confirmed bulletins where
    the ID span is larger than *--step*, and probe candidate IDs within those ranges.
    New confirmed bulletins are appended to classified.json.

--cdx-pdfs
    Query the Wayback Machine CDX for all unicadata.com.br/arquivos/pdfs/ direct
    PDF paths captured since 2021.  Download each unique PDF from the live
    unicadata.com.br server and classify it.  Confirmed bulletins are added to
    classified.json with idm = "pdf_{hash[:16]}" (no download_media.php mapping needed).

--export
    Read confirmed=True entries from classified.json and merge them into
    configs/sources/unica_biweekly_manifest.yaml.  Idempotent (deduplicates by idm).
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import re
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TypedDict, cast

import pdfplumber
import yaml

from leviathan.common.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Local TypedDicts
# ---------------------------------------------------------------------------

class _HeadCheckBase(TypedDict):
    ok: bool
    content_length: int


class _HeadCheckResult(_HeadCheckBase, total=False):
    content_type: str
    content_disposition: str
    error: str


class _ClassifyResult(TypedDict):
    is_bulletin: bool
    harvest_year: str | None
    bulletin_num: int | None
    text_snippet: str


class _ClassifiedEntryBase(TypedDict):
    idm: str
    wm_ts: str | None        # None for gap-fill entries
    confirmed: bool
    content_length: int
    harvest_year: str | None
    bulletin_num: int | None
    published_ym: str | None  # None for gap-fill entries
    download_url: str | None  # None for direct-PDF entries (no download_media.php idm)
    pdf_url: str | None


class _ClassifiedEntry(_ClassifiedEntryBase, total=False):
    skip_reason: str
    text_snippet: str
    source: str  # "gap_fill" or "cdx_pdf" for non-CDX-download-media entries


class _ManifestBulletin(TypedDict, total=False):
    harvest_year: str | None
    idm: str
    bulletin_num: int | None
    published_ym: str | None
    pdf_url: str | None
    download_url: str | None


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent.parent
_CLASSIFIED_PATH = _ROOT / "configs" / "sources" / "unica_biweekly_classified.json"
_MANIFEST_PATH = _ROOT / "configs" / "sources" / "unica_biweekly_manifest.yaml"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CDX_API = "https://web.archive.org/cdx/search/cdx"
_DOWNLOAD_BASE = "https://unicadata.com.br/download_media.php?idM="
_UA = "Leviathan-Data-Pipeline/1.0 (research)"

# Real bi-weekly bulletins are 1.5–3 MB.  Reject outside 500 KB – 8 MB.
_MIN_BULLETIN_BYTES = 500_000
_MAX_BULLETIN_BYTES = 8_000_000

_DEFAULT_SLEEP_S = 2.0
_DEFAULT_STEP = 50_000  # probe every N IDs when gap-filling

_SSL_CTX = ssl.create_default_context()

# ---------------------------------------------------------------------------
# PDF classification patterns
# ---------------------------------------------------------------------------

# Any of these in page-1 text confirms a bi-weekly production bulletin.
_BIWEEKLY_PATTERNS = [
    re.compile(r"quinzenal", re.IGNORECASE),
    re.compile(r"bi.?weekly", re.IGNORECASE),
    re.compile(r"fortnightly", re.IGNORECASE),
    re.compile(r"boletim\s+(?:n[o\u00b0\.]?\s*)?\d{2,}", re.IGNORECASE),
    re.compile(r"bulletin\s+(?:no?\.?\s*)?\d{2,}", re.IGNORECASE),
]

_SEASON_RE = re.compile(r"\b(20\d{2}/20\d{2})\b")
_BULLETIN_NUM_RE = re.compile(
    r"(?:boletim|bulletin)\s+(?:n[o\u00b0\.]?\s*)?(\d{3,})", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# CDX query
# ---------------------------------------------------------------------------

def _cdx_query(limit: int = 500) -> list[dict[str, str]]:
    """Return all download_media.php entries from the Wayback Machine CDX."""
    params = urllib.parse.urlencode({
        "url": "unicadata.com.br/download_media.php",
        "matchType": "prefix",
        "output": "json",
        "fl": "timestamp,original",
        "filter": "statuscode:200",
        "collapse": "original",
        "from": "20210101",
        "limit": str(limit),
    })
    api_url = f"{_CDX_API}?{params}"
    logger.info("CDX query: %s", api_url)
    req = urllib.request.Request(api_url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as resp:
        rows = json.loads(resp.read())

    # rows[0] is the header ["timestamp", "original"] — skip it.
    # Deduplicate by idm (CDX collapse=original is case-sensitive; same idM may appear
    # twice if the captured URLs differ in parameter name casing).
    seen_idms: set[str] = set()
    results: list[dict[str, str]] = []
    for row in rows[1:]:
        ts, orig = row[0], row[1]
        m = re.search(r"[?&]idM=(\d+)", orig, re.IGNORECASE)
        if m:
            idm = m.group(1)
            if idm not in seen_idms:
                seen_idms.add(idm)
                results.append({"idm": idm, "wm_ts": ts, "wm_url": orig})

    logger.info("CDX: %d unique download_media.php IDs", len(results))
    return results


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _head_check(idm: str) -> _HeadCheckResult:
    """HEAD request to download_media.php.  Returns size info or error."""
    url = _DOWNLOAD_BASE + idm
    req = urllib.request.Request(url, headers={"User-Agent": _UA}, method="HEAD")
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=15) as resp:
            cl_str = resp.headers.get("Content-Length", "") or ""
            cl = int(cl_str) if cl_str.strip().isdigit() else 0
            return {
                "ok": True,
                "content_length": cl,
                "content_type": resp.headers.get("Content-Type", ""),
                "content_disposition": resp.headers.get("Content-Disposition", ""),
            }
    except Exception as exc:  # noqa: BLE001 — any HTTP error; returns structured error dict so caller can log and continue
        return {"ok": False, "error": str(exc), "content_length": 0}


def _download(idm: str) -> bytes | None:
    """Download a document from download_media.php.  Returns bytes or None."""
    url = _DOWNLOAD_BASE + idm
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=60) as resp:
            data = resp.read()
        return data if data[:4] == b"%PDF" else None
    except Exception as exc:  # noqa: BLE001 — any urllib/SSL error; returns None so caller skips this idm
        logger.debug("Download failed idm=%s: %s", idm, exc)
        return None


# ---------------------------------------------------------------------------
# PDF classification
# ---------------------------------------------------------------------------

def _classify_pdf(pdf_bytes: bytes) -> _ClassifyResult:
    """Inspect page 1 of a PDF and determine if it is a UNICA bi-weekly bulletin.

    Returns a dict with:
      is_bulletin   : bool
      harvest_year  : str | None   e.g. "2023/2024"
      bulletin_num  : int | None
      text_snippet  : str          first 300 chars of extracted text
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = ""
            for pg in pdf.pages[:2]:  # check cover + first data page
                t = pg.extract_text() or ""
                text += t + "\n"
    except Exception as exc:  # noqa: BLE001 — pdfplumber can raise diverse exceptions; returns structured error result
        return {
            "is_bulletin": False,
            "harvest_year": None,
            "bulletin_num": None,
            "text_snippet": f"[pdfplumber error: {exc}]",
        }

    is_bulletin = any(p.search(text) for p in _BIWEEKLY_PATTERNS)

    # Use the FIRST YYYY/YYYY match — the season heading almost always appears
    # before comparison tables that repeat the prior season many times.
    season_matches = _SEASON_RE.findall(text)
    harvest_year = season_matches[0] if season_matches else None

    bnum_match = _BULLETIN_NUM_RE.search(text)
    bulletin_num = int(bnum_match.group(1)) if bnum_match else None

    return {
        "is_bulletin": is_bulletin,
        "harvest_year": harvest_year,
        "bulletin_num": bulletin_num,
        "text_snippet": text[:300].replace("\n", " "),
    }


# ---------------------------------------------------------------------------
# Classified JSON helpers
# ---------------------------------------------------------------------------

def _load_classified() -> list[_ClassifiedEntry]:
    if not _CLASSIFIED_PATH.exists():
        return []
    return json.loads(_CLASSIFIED_PATH.read_text(encoding="utf-8"))


def _save_classified(entries: list[_ClassifiedEntry]) -> None:
    _CLASSIFIED_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Manifest helpers (mirrors fetch_unica_biweekly._save_manifest)
# ---------------------------------------------------------------------------

def _load_manifest() -> list[_ManifestBulletin]:
    raw = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    return (raw.get("bulletins") or []) if raw else []


def _save_manifest(bulletins: list[_ManifestBulletin]) -> None:
    original = _MANIFEST_PATH.read_text(encoding="utf-8")
    header_end = original.find("\nbulletins:")
    header = original[:header_end] if header_end != -1 else original

    lines = [header, "\nbulletins:\n\n"]
    for b in sorted(bulletins, key=lambda x: (x.get("harvest_year") or "", x.get("idm") or "")):
        lines.append(f"  - harvest_year: \"{b['harvest_year']}\"\n")
        lines.append(f"    idm: \"{b['idm']}\"\n")
        lines.append(f"    bulletin_num: {b.get('bulletin_num')}\n")
        lines.append(f"    published_ym: \"{b.get('published_ym') or ''}\"\n")
        pdf_url = b.get("pdf_url")
        lines.append(f"    pdf_url: {repr(pdf_url) if pdf_url else 'null'}\n")
        dl = b.get("download_url")
        lines.append(f"    download_url: {repr(dl) if dl else 'null'}\n")
        lines.append("\n")

    _MANIFEST_PATH.write_text("".join(lines), encoding="utf-8")


def _merge_manifest(
    existing: list[_ManifestBulletin],
    new_entries: list[_ManifestBulletin],
) -> list[_ManifestBulletin]:
    seen = {b["idm"] for b in existing if b.get("idm")}
    merged = list(existing)
    for b in new_entries:
        if b.get("idm") not in seen:
            merged.append(b)
            seen.add(b["idm"])
    return merged


# ---------------------------------------------------------------------------
# Sub-command: --classify
# ---------------------------------------------------------------------------

def cmd_classify(sleep_s: float, cdx_limit: int = 500) -> None:
    """Query WM CDX and classify each download_media.php ID."""
    cdx_entries = _cdx_query(limit=cdx_limit)

    existing = _load_classified()
    existing_idms = {e["idm"] for e in existing}

    todo = [e for e in cdx_entries if e["idm"] not in existing_idms]
    logger.info(
        "Classify: %d CDX IDs total, %d already classified, %d to probe",
        len(cdx_entries), len(existing_idms), len(todo),
    )

    results = list(existing)
    processed_this_run: set[str] = set()  # guard against duplicate CDX entries
    n_confirmed = n_skipped = n_failed = 0

    for i, entry in enumerate(todo):
        idm = entry["idm"]
        if idm in processed_this_run:
            logger.debug("Skipping duplicate CDX entry idm=%s", idm)
            continue
        processed_this_run.add(idm)
        wm_ts = entry["wm_ts"]
        published_ym = f"{wm_ts[:4]}/{wm_ts[4:6]}"  # WM crawl date as proxy

        if i > 0:
            time.sleep(sleep_s)

        # ---- Step 1: HEAD to size-check before full download ----
        head = _head_check(idm)
        if not head["ok"]:
            logger.debug("HEAD failed idm=%s: %s", idm, head.get("error"))
            results.append({
                "idm": idm, "wm_ts": wm_ts, "confirmed": False,
                "skip_reason": f"head_failed: {head.get('error')}",
                "content_length": 0, "harvest_year": None,
                "bulletin_num": None, "published_ym": published_ym,
                "download_url": _DOWNLOAD_BASE + idm, "pdf_url": None,
            })
            n_failed += 1
            _save_classified(results)
            continue

        cl = head["content_length"]
        # cl==0 means server didn't send Content-Length; don't skip on that.
        if cl > 0 and (cl < _MIN_BULLETIN_BYTES or cl > _MAX_BULLETIN_BYTES):
            logger.debug("Skipping idm=%s: Content-Length=%d outside range", idm, cl)
            results.append({
                "idm": idm, "wm_ts": wm_ts, "confirmed": False,
                "skip_reason": f"wrong_size: {cl}",
                "content_length": cl, "harvest_year": None,
                "bulletin_num": None, "published_ym": published_ym,
                "download_url": _DOWNLOAD_BASE + idm, "pdf_url": None,
            })
            n_skipped += 1
            _save_classified(results)
            continue

        # ---- Step 2: Full download + pdfplumber classification ----
        time.sleep(sleep_s)
        pdf_bytes = _download(idm)
        if pdf_bytes is None:
            results.append({
                "idm": idm, "wm_ts": wm_ts, "confirmed": False,
                "skip_reason": "download_failed_or_not_pdf",
                "content_length": cl, "harvest_year": None,
                "bulletin_num": None, "published_ym": published_ym,
                "download_url": _DOWNLOAD_BASE + idm, "pdf_url": None,
            })
            n_failed += 1
            _save_classified(results)
            continue

        meta = _classify_pdf(pdf_bytes)
        is_bulletin = meta["is_bulletin"]
        harvest_year = meta["harvest_year"]

        logger.info(
            "idm=%-12s  %6d KB  confirmed=%-5s  season=%-12s  #%s  [%.60s]",
            idm, len(pdf_bytes) // 1024, is_bulletin,
            harvest_year or "?", meta.get("bulletin_num") or "?",
            meta.get("text_snippet", ""),
        )

        results.append({
            "idm": idm,
            "wm_ts": wm_ts,
            "confirmed": is_bulletin,
            "content_length": len(pdf_bytes),
            "harvest_year": harvest_year,
            "bulletin_num": meta.get("bulletin_num"),
            "published_ym": published_ym,
            "download_url": _DOWNLOAD_BASE + idm,
            "pdf_url": None,
            "text_snippet": meta.get("text_snippet", "")[:200],
        })

        if is_bulletin:
            n_confirmed += 1
        else:
            n_skipped += 1

        _save_classified(results)  # incremental save

    logger.info(
        "Classify done: confirmed=%d  not-bulletin=%d  failed=%d  total_in_file=%d",
        n_confirmed, n_skipped, n_failed, len(results),
    )


# ---------------------------------------------------------------------------
# Sub-command: --fill-gaps
# ---------------------------------------------------------------------------

def cmd_fill_gaps(sleep_s: float, step: int) -> None:
    """Probe ID ranges between confirmed bulletins to find missing ones."""
    entries = _load_classified()
    confirmed = sorted(
        [e for e in entries if e.get("confirmed")],
        key=lambda e: int(e["idm"]),
    )
    existing_idms = {e["idm"] for e in entries}

    if len(confirmed) < 2:
        logger.warning(
            "Need ≥2 confirmed bulletins for gap-filling; have %d. Run --classify first.",
            len(confirmed),
        )
        return

    logger.info(
        "Gap fill: %d confirmed bulletins, ID range %s–%s, step=%d",
        len(confirmed), confirmed[0]["idm"], confirmed[-1]["idm"], step,
    )

    results = list(entries)
    n_new = 0

    for lo, hi in zip(confirmed, confirmed[1:]):
        lo_id = int(lo["idm"])
        hi_id = int(hi["idm"])
        gap = hi_id - lo_id

        if gap <= step:
            continue  # nothing to probe between adjacent IDs

        n_probes = gap // step
        logger.info(
            "Probing gap  %s → %s  (%d IDs, %d probes)",
            lo["idm"], hi["idm"], gap, n_probes,
        )

        for j, probe_id in enumerate(range(lo_id + step, hi_id, step)):
            if j > 0 and j % 25 == 0:
                logger.info("  … probe %d/%d (id=%d)", j, n_probes, probe_id)
            idm_str = str(probe_id)
            if idm_str in existing_idms:
                continue

            time.sleep(sleep_s)
            head = _head_check(idm_str)
            if not head["ok"]:
                continue

            cl = head["content_length"]
            # For gap probing, require a Content-Length header and insist on
            # a tighter size range (real bulletins are 1.5–3.5 MB).
            _FILL_MIN = 1_500_000
            _FILL_MAX = 3_500_000
            if cl == 0 or cl < _FILL_MIN or cl > _FILL_MAX:
                continue

            # Potentially a bulletin — full download.
            logger.info("Gap probe download: idm=%s  %d KB  (downloading…)", idm_str, cl // 1024 if cl else 0)
            time.sleep(sleep_s)
            pdf_bytes = _download(idm_str)
            if pdf_bytes is None:
                continue

            meta = _classify_pdf(pdf_bytes)
            logger.info(
                "Gap hit: idm=%s  %d KB  confirmed=%s  season=%s  #%s",
                idm_str, len(pdf_bytes) // 1024, meta["is_bulletin"],
                meta.get("harvest_year"), meta.get("bulletin_num"),
            )

            entry: _ClassifiedEntry = {
                "idm": idm_str,
                "wm_ts": None,
                "confirmed": meta["is_bulletin"],
                "content_length": len(pdf_bytes),
                "harvest_year": meta.get("harvest_year"),
                "bulletin_num": meta.get("bulletin_num"),
                "published_ym": None,
                "download_url": _DOWNLOAD_BASE + idm_str,
                "pdf_url": None,
                "text_snippet": meta.get("text_snippet", "")[:200],
                "source": "gap_fill",
            }
            results.append(entry)
            existing_idms.add(idm_str)
            if meta["is_bulletin"]:
                n_new += 1

            _save_classified(results)

    logger.info("Gap fill done: %d new confirmed bulletins found", n_new)


# ---------------------------------------------------------------------------
# CDX query for direct PDF paths
# ---------------------------------------------------------------------------

def _cdx_query_pdfs(limit: int = 500) -> list[dict[str, str]]:
    """Return unique direct PDF paths from the Wayback Machine CDX.

    Queries for ``unicadata.com.br/arquivos/pdfs/`` prefix URLs captured since
    2021.  Deduplicates by the 32-char MD5 hash embedded in the path.

    Returns a list of dicts with keys:
      hash        : 32-char hex hash (file identifier)
      pdf_url     : live URL  https://unicadata.com.br/arquivos/pdfs/YYYY/MM/HASH.pdf
      wm_ts       : WM capture timestamp (earliest)
      published_ym: "YYYY/MM" extracted from the URL path
    """
    params = urllib.parse.urlencode({
        "url": "unicadata.com.br/arquivos/pdfs/",
        "matchType": "prefix",
        "output": "json",
        "fl": "timestamp,original",
        "filter": "statuscode:200",
        "collapse": "original",
        "from": "20210101",
        "limit": str(limit),
    })
    api_url = f"{_CDX_API}?{params}"
    logger.info("CDX PDF query: %s", api_url)
    req = urllib.request.Request(api_url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as resp:
        rows = json.loads(resp.read())

    seen_hashes: set[str] = set()
    results: list[dict[str, str]] = []
    for row in rows[1:]:
        ts, orig = row[0], row[1]
        # Expect path like: /arquivos/pdfs/YYYY/MM/HASH32.pdf
        m = re.search(r"/arquivos/pdfs/(\d{4})/(\d{2})/([a-f0-9]{32})\.pdf", orig, re.IGNORECASE)
        if not m:
            continue
        yr, mo, h = m.group(1), m.group(2), m.group(3)
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        results.append({
            "hash": h,
            "pdf_url": f"https://unicadata.com.br/arquivos/pdfs/{yr}/{mo}/{h}.pdf",
            "wm_ts": ts,
            "published_ym": f"{yr}/{mo}",
        })

    logger.info("CDX PDF: %d unique direct PDF paths", len(results))
    return results


# ---------------------------------------------------------------------------
# Sub-command: --cdx-pdfs
# ---------------------------------------------------------------------------

def cmd_cdx_pdfs(sleep_s: float, cdx_limit: int = 500) -> None:
    """Download and classify direct PDF URLs found in the WM CDX."""
    pdf_entries = _cdx_query_pdfs(limit=cdx_limit)

    existing = _load_classified()
    # Keys in classified.json: either numeric idm or "pdf_{hash16}"
    existing_keys: set[str] = {e.get("idm") or "" for e in existing}
    existing_pdf_urls: set[str] = {e.get("pdf_url") or "" for e in existing}

    todo = [
        e for e in pdf_entries
        if ("pdf_" + e["hash"][:16]) not in existing_keys
        and e["pdf_url"] not in existing_pdf_urls
    ]
    logger.info(
        "CDX-PDFs: %d unique PDFs total, %d already seen, %d to probe",
        len(pdf_entries), len(pdf_entries) - len(todo), len(todo),
    )

    results = list(existing)
    n_confirmed = n_skipped = n_failed = 0

    for i, entry in enumerate(todo):
        if i > 0:
            time.sleep(sleep_s)

        pdf_url = entry["pdf_url"]
        hash16 = entry["hash"][:16]
        idm_key = "pdf_" + hash16
        published_ym = entry["published_ym"]

        # Download the PDF directly from the live server.
        req = urllib.request.Request(pdf_url, headers={"User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=60) as resp:
                pdf_bytes = resp.read()
        except Exception as exc:  # noqa: BLE001 — CDX download error; logged and loop continues to next entry
            logger.debug("CDX-PDF download failed %s: %s", pdf_url, exc)
            results.append({
                "idm": idm_key,
                "wm_ts": entry["wm_ts"],
                "confirmed": False,
                "skip_reason": f"download_failed: {exc}",
                "content_length": 0,
                "harvest_year": None,
                "bulletin_num": None,
                "published_ym": published_ym,
                "download_url": None,
                "pdf_url": pdf_url,
                "source": "cdx_pdf",
            })
            n_failed += 1
            _save_classified(results)
            continue

        if not pdf_bytes or pdf_bytes[:4] != b"%PDF":
            logger.debug("CDX-PDF not a PDF: %s", pdf_url)
            results.append({
                "idm": idm_key, "wm_ts": entry["wm_ts"], "confirmed": False,
                "skip_reason": "not_pdf", "content_length": len(pdf_bytes or b""),
                "harvest_year": None, "bulletin_num": None, "published_ym": published_ym,
                "download_url": None, "pdf_url": pdf_url, "source": "cdx_pdf",
            })
            n_failed += 1
            _save_classified(results)
            continue

        size_kb = len(pdf_bytes) // 1024
        meta = _classify_pdf(pdf_bytes)
        is_bulletin = meta["is_bulletin"]
        harvest_year = meta.get("harvest_year")

        logger.info(
            "cdx_pdf %-18s  %5d KB  confirmed=%-5s  season=%-12s  [%.55s]",
            published_ym + "/" + hash16,
            size_kb,
            is_bulletin,
            harvest_year or "?",
            meta.get("text_snippet", ""),
        )

        results.append({
            "idm": idm_key,
            "wm_ts": entry["wm_ts"],
            "confirmed": is_bulletin,
            "content_length": len(pdf_bytes),
            "harvest_year": harvest_year,
            "bulletin_num": meta.get("bulletin_num"),
            "published_ym": published_ym,
            "download_url": None,   # no download_media.php idm known
            "pdf_url": pdf_url,
            "text_snippet": meta.get("text_snippet", "")[:200],
            "source": "cdx_pdf",
        })

        if is_bulletin:
            n_confirmed += 1
        else:
            n_skipped += 1

        _save_classified(results)

    logger.info(
        "CDX-PDFs done: confirmed=%d  not-bulletin=%d  failed=%d  total_in_file=%d",
        n_confirmed, n_skipped, n_failed, len(results),
    )


# ---------------------------------------------------------------------------
# Harvest-year resolution helpers
# ---------------------------------------------------------------------------

# Matches "SAFRA 2025/2026" or "HARVEST 2024/2025" or "S AFRA 2025/2026"
# (pdfplumber sometimes splits ligatures) at the START of a text snippet.
_SEASON_TITLE_RE = re.compile(
    r"(?:S\s?AFRA|H\s?ARVEST|SAFRA|HARVEST)\s+(\d{4}/\d{4})",
    re.IGNORECASE,
)

_PUB_YM_RE = re.compile(r"^(\d{4})/(\d{2})$")


def _harvest_year_from_published_ym(published_ym: str | None) -> str | None:
    """Infer harvest season from publication month.

    UNICA seasons run April–December with closure bulletins in January–March:
    - April–December of year Y  →  "Y/Y+1"
    - January–March of year Y   →  "(Y-1)/Y"
    """
    m = _PUB_YM_RE.match(published_ym or "")
    if not m:
        return None
    yr, mo = int(m.group(1)), int(m.group(2))
    return f"{yr}/{yr + 1}" if mo >= 4 else f"{yr - 1}/{yr}"


def _resolve_harvest_year(entry: _ClassifiedEntry) -> str | None:
    """Return the best harvest_year for a classified entry.

    Priority:
    1. Text-snippet match — title "SAFRA/HARVEST YYYY/YYYY" is authoritative.
    2. For cdx_pdf entries: infer from published_ym (more reliable than the
       most-common-year counter, which is skewed by comparison tables).
    3. Stored harvest_year from _classify_pdf.
    4. Infer from published_ym for any source (last resort).
    """
    snippet = entry.get("text_snippet") or ""
    m = _SEASON_TITLE_RE.search(snippet)
    if m:
        return m.group(1)
    # For CDX direct-PDF entries prefer the URL-path date as ground truth.
    if entry.get("source") == "cdx_pdf":
        hy = _harvest_year_from_published_ym(entry.get("published_ym"))
        if hy:
            return hy
    stored = entry.get("harvest_year")
    if stored:
        return stored
    return _harvest_year_from_published_ym(entry.get("published_ym"))


# ---------------------------------------------------------------------------
# Sub-command: --export
# ---------------------------------------------------------------------------

def cmd_export() -> None:
    """Export confirmed entries from classified.json into the bulletin manifest."""
    entries = _load_classified()
    confirmed = [e for e in entries if e.get("confirmed")]

    if not confirmed:
        logger.warning("classified.json has no confirmed bulletins — nothing to export.")
        return

    # Resolve harvest_year using title-text then stored value then published_ym.
    resolved: list[_ClassifiedEntry] = []
    for e in confirmed:
        hy = _resolve_harvest_year(e)
        if not hy:
            logger.warning("Skipping idm=%s — cannot determine harvest_year", e.get("idm"))
            continue
        if hy != e.get("harvest_year"):
            logger.info(
                "harvest_year corrected: idm=%s  %s → %s  (published_ym=%s)",
                e.get("idm"), e.get("harvest_year"), hy, e.get("published_ym"),
            )
        resolved.append(cast(_ClassifiedEntry, {**e, "harvest_year": hy}))

    manifest = _load_manifest()
    existing_idms = {b["idm"] for b in manifest if b.get("idm")}

    new_bulletins = [
        {
            "harvest_year": e["harvest_year"],
            "idm": e["idm"],
            "bulletin_num": e.get("bulletin_num"),
            "published_ym": e.get("published_ym") or "",
            "pdf_url": e.get("pdf_url"),
            # For direct-PDF entries (idm=pdf_*), download_url is null.
            "download_url": (
                None if (e.get("idm") or "").startswith("pdf_")
                else (e.get("download_url") or (_DOWNLOAD_BASE + e["idm"]))
            ),
        }
        for e in resolved
        if e["idm"] not in existing_idms
    ]

    if not new_bulletins:
        logger.info(
            "All %d confirmed bulletins already in manifest — nothing to add.",
            len(confirmed),
        )
        return

    merged = _merge_manifest(manifest, new_bulletins)
    _save_manifest(merged)
    logger.info(
        "Exported %d new bulletins → manifest now has %d total.",
        len(new_bulletins), len(merged),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--classify",
        action="store_true",
        help="Query WM CDX and classify each download_media.php ID.",
    )
    grp.add_argument(
        "--fill-gaps",
        action="store_true",
        help="Probe ID ranges between confirmed bulletins to find missing ones.",
    )
    grp.add_argument(
        "--cdx-pdfs",
        action="store_true",
        help="Download and classify direct PDF paths from the WM CDX.",
    )
    grp.add_argument(
        "--export",
        action="store_true",
        help="Merge confirmed IDs from classified.json into the manifest YAML.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=_DEFAULT_SLEEP_S,
        metavar="N",
        help=f"Seconds between HTTP requests (default: {_DEFAULT_SLEEP_S}).",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=_DEFAULT_STEP,
        metavar="N",
        help=(
            f"ID probe step size for --fill-gaps (default: {_DEFAULT_STEP}). "
            "Smaller = more thorough but more requests."
        ),
    )
    parser.add_argument(
        "--cdx-limit",
        type=int,
        default=500,
        metavar="N",
        help="Max CDX results to fetch (default: 500).",
    )
    args = parser.parse_args()

    if args.classify:
        cmd_classify(sleep_s=args.sleep_seconds, cdx_limit=args.cdx_limit)
    elif args.fill_gaps:
        cmd_fill_gaps(sleep_s=args.sleep_seconds, step=args.step)
    elif args.cdx_pdfs:
        cmd_cdx_pdfs(sleep_s=args.sleep_seconds, cdx_limit=args.cdx_limit)
    elif args.export:
        cmd_export()


if __name__ == "__main__":
    main()
