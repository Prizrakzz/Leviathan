"""Discover CONAB coffee bulletin XLS files and refresh the raw-download manifest.

CONAB exposes structured coffee production spreadsheets on per-survey data pages:

    .../{survey}o-levantamento-de-cafe-safra-{year}/
        tabela-de-dados-estimativas-da-producao-e-colheita/view

This script discovers the XLS/XLSX links for the official 2023-2026 pages that
are still available on gov.br and writes ``data/conab/conab_bulletin_excels.json``.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_OUTPUT = _PROJECT_ROOT / "data" / "conab" / "conab_bulletin_excels.json"
_BASE_URL = (
    "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/"
    "safras/safra-de-cafe"
)
_DEFAULT_TARGET_SURVEYS: dict[int, tuple[int, ...]] = {
    2023: (1, 2, 3, 4),
    2024: (2, 3, 4),
    2025: (1, 2, 3, 4),
    2026: (1, 2),
}
_XLS_RE = re.compile(r"\.xlsx?(?:$|[\s?#/])", re.IGNORECASE)
_COFFEE_XLS_RE = re.compile(
    r"previsao[-_ ]de[-_ ]safra[-_ ]cafe.*\.xlsx?",
    re.IGNORECASE,
)
_SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?\s*(?:KB|MB))", re.IGNORECASE)


@dataclass(frozen=True)
class ConabBulletinXlsEntry:
    safra_year: int
    survey_no: int
    source_page: str
    data_page: str
    xls_url: str
    filename: str
    file_size_label: str | None
    discovered_at: str


def _survey_slug(safra_year: int, survey_no: int) -> str:
    return f"{survey_no}o-levantamento-de-cafe-safra-{safra_year}"


def build_data_page_url(safra_year: int, survey_no: int) -> str:
    slug = _survey_slug(safra_year, survey_no)
    return f"{_BASE_URL}/{slug}/tabela-de-dados-estimativas-da-producao-e-colheita/view"


def build_source_page_url(safra_year: int, survey_no: int) -> str:
    return f"{_BASE_URL}/{_survey_slug(safra_year, survey_no)}"


def _filename_from_url(url: str) -> str:
    path = unquote(urlparse(url).path.rstrip("/"))
    if "/@@download/file/" in path:
        return path.rsplit("/@@download/file/", 1)[-1]
    return path.rsplit("/", 1)[-1]


def _filename_from_anchor_text(anchor_text: str) -> str | None:
    if not re.search(r"previsao.*cafe", anchor_text, re.IGNORECASE):
        return None
    match = re.search(r"([^\r\n<>]+?\.xlsx?)", anchor_text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _normalise_filename(value: str) -> str:
    return unquote(value).replace("_", "-").lower()


def _is_coffee_xls(anchor_text: str, href: str, filename: str) -> bool:
    haystack = " ".join(
        _normalise_filename(part)
        for part in (anchor_text, href, filename)
        if part
    )
    return bool(_XLS_RE.search(haystack) and _COFFEE_XLS_RE.search(haystack))


def extract_entries_from_html(
    html: str,
    *,
    safra_year: int,
    survey_no: int,
    data_page: str,
    discovered_at: str,
) -> list[ConabBulletinXlsEntry]:
    """Extract CONAB coffee XLS links from one official data page."""
    soup = BeautifulSoup(html, "html.parser")
    source_page = build_source_page_url(safra_year, survey_no)
    entries: list[ConabBulletinXlsEntry] = []
    seen_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", "")).strip()
        xls_url = urljoin(data_page, href)
        filename = _filename_from_url(xls_url)
        anchor_text = anchor.get_text(" ", strip=True)
        if not _XLS_RE.search(filename):
            filename = _filename_from_anchor_text(anchor_text) or filename
        if not _is_coffee_xls(anchor_text, href, filename):
            continue
        if xls_url in seen_urls:
            continue

        surrounding_text = ""
        if anchor.parent is not None:
            surrounding_text = anchor.parent.get_text(" ", strip=True)
        match = _SIZE_RE.search(surrounding_text)

        entries.append(
            ConabBulletinXlsEntry(
                safra_year=safra_year,
                survey_no=survey_no,
                source_page=source_page,
                data_page=data_page,
                xls_url=xls_url,
                filename=filename,
                file_size_label=match.group(1) if match else None,
                discovered_at=discovered_at,
            )
        )
        seen_urls.add(xls_url)

    return entries


def _target_surveys_from_args(args: argparse.Namespace) -> dict[int, tuple[int, ...]]:
    if args.years is None and args.surveys is None:
        return _DEFAULT_TARGET_SURVEYS

    years = (
        sorted(_DEFAULT_TARGET_SURVEYS)
        if args.years is None
        else [int(item.strip()) for item in args.years.split(",") if item.strip()]
    )
    surveys = (
        (1, 2, 3, 4)
        if args.surveys is None
        else tuple(int(item.strip()) for item in args.surveys.split(",") if item.strip())
    )
    return {year: surveys for year in years}


def discover_entries(
    *,
    target_surveys: dict[int, tuple[int, ...]],
    timeout_seconds: int,
) -> list[ConabBulletinXlsEntry]:
    session = curl_requests.Session(impersonate="chrome124")
    discovered_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    entries: list[ConabBulletinXlsEntry] = []

    for safra_year in sorted(target_surveys):
        for survey_no in target_surveys[safra_year]:
            data_page = build_data_page_url(safra_year, survey_no)
            logger.info("Discovering CONAB XLS safra=%d survey=%d", safra_year, survey_no)
            try:
                response = session.get(data_page, timeout=timeout_seconds, allow_redirects=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("CONAB discovery request failed page=%s: %s", data_page, exc)
                continue

            if response.status_code == 404:
                logger.info("CONAB data page not found: %s", data_page)
                continue
            try:
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                logger.warning("CONAB discovery HTTP error page=%s: %s", data_page, exc)
                continue

            page_entries = extract_entries_from_html(
                response.text,
                safra_year=safra_year,
                survey_no=survey_no,
                data_page=data_page,
                discovered_at=discovered_at,
            )
            if not page_entries:
                logger.warning("No CONAB coffee XLS links found page=%s", data_page)
            entries.extend(page_entries)

    deduped: dict[tuple[int, int, str], ConabBulletinXlsEntry] = {}
    for entry in entries:
        deduped[(entry.safra_year, entry.survey_no, entry.xls_url)] = entry
    return sorted(deduped.values(), key=lambda e: (e.safra_year, e.survey_no, e.filename))


def write_manifest(entries: list[ConabBulletinXlsEntry], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(entry) for entry in entries]
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _entries_from_existing_manifest(
    manifest_path: Path,
    discovered_at: str,
) -> list[ConabBulletinXlsEntry]:
    if not manifest_path.exists():
        return []
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries: list[ConabBulletinXlsEntry] = []
    for item in payload:
        xls_url = str(item["xls_url"])
        entries.append(
            ConabBulletinXlsEntry(
                safra_year=int(item["safra_year"]),
                survey_no=int(item["survey_no"]),
                source_page=str(item.get("source_page") or ""),
                data_page=str(item.get("data_page") or item.get("source_page") or ""),
                xls_url=xls_url,
                filename=str(item.get("filename") or _filename_from_url(xls_url)),
                file_size_label=item.get("file_size_label"),
                discovered_at=str(item.get("discovered_at") or discovered_at),
            )
        )
    return entries


def merge_entries(
    discovered: list[ConabBulletinXlsEntry],
    existing: list[ConabBulletinXlsEntry],
) -> list[ConabBulletinXlsEntry]:
    merged: dict[tuple[int, int], ConabBulletinXlsEntry] = {
        (entry.safra_year, entry.survey_no): entry
        for entry in existing
    }
    for entry in discovered:
        merged[(entry.safra_year, entry.survey_no)] = entry
    return sorted(merged.values(), key=lambda e: (e.safra_year, e.survey_no, e.filename))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    parser = argparse.ArgumentParser(description="Discover CONAB coffee bulletin XLS URLs.")
    parser.add_argument("--years", default=None, help="Comma-separated safra years.")
    parser.add_argument("--surveys", default=None, help="Comma-separated survey numbers.")
    parser.add_argument("--output", default=str(_DEFAULT_OUTPUT))
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-preserve-existing",
        action="store_true",
        help="Do not carry forward already-known manifest entries missing from live pages.",
    )
    args = parser.parse_args()

    entries = discover_entries(
        target_surveys=_target_surveys_from_args(args),
        timeout_seconds=args.timeout_seconds,
    )

    if not args.no_preserve_existing:
        discovered_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        entries = merge_entries(
            entries,
            _entries_from_existing_manifest(Path(args.output), discovered_at),
        )

    logger.info("Discovered %d CONAB coffee XLS file(s)", len(entries))
    for entry in entries:
        logger.info(
            "CONAB XLS safra=%d survey=%d filename=%s",
            entry.safra_year,
            entry.survey_no,
            entry.filename,
        )

    if args.dry_run:
        print(json.dumps([asdict(entry) for entry in entries], ensure_ascii=False, indent=2))
        return

    write_manifest(entries, Path(args.output))
    logger.info("Wrote manifest: %s", args.output)

    # Chain handoff (Wave-3 RCA): on AWS Batch the downstream fetch task runs in a
    # DIFFERENT container, so a container-local manifest is invisible to it. When the
    # thin-contract env is present (LEVIATHAN_BUCKET), mirror the manifest to S3 --
    # fail CLOSED on an upload error (a silently-missing manifest would freeze the
    # DAG on stale surveys, the exact failure the descriptor note warns about). Local
    # runs without the env keep the old local-only behavior.
    import os as _os

    bucket = _os.environ.get("LEVIATHAN_BUCKET")
    if bucket:
        _upload_manifest_s3(bucket, S3_MANIFEST_KEY, Path(args.output).read_bytes())
        logger.info("Mirrored manifest to s3://%s/%s", bucket, S3_MANIFEST_KEY)
    else:
        logger.info("LEVIATHAN_BUCKET unset -- local-only manifest (no S3 mirror)")


# S3 mirror key for the cross-container discover->fetch handoff. Deliberately OUTSIDE
# raw/production/source=conab/bulletin_xls/ -- conab_xls_task lists that prefix with NO
# suffix filter and would try to parse the manifest JSON as a bulletin.
S3_MANIFEST_KEY = "raw/production/source=conab/discovery/conab_bulletin_excels.json"


def _upload_manifest_s3(bucket: str, key: str, data: bytes) -> None:
    """put_object seam (monkeypatched in tests; boto3 imported lazily)."""
    import boto3

    boto3.client("s3").put_object(
        Bucket=bucket, Key=key, Body=data, ContentType="application/json"
    )


if __name__ == "__main__":
    main()
