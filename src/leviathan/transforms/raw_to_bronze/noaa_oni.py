"""Bronze transform for the NOAA CPC Oceanic Nino Index (ONI) ascii file (SILVER-F057).

Parses the whitespace-delimited ``oni.ascii.txt`` file published by NOAA CPC at:
    https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt

This producer is built FROM SCRATCH (C-WRONG-8 full orphan): ``silver_noaa_oni`` was
consumed everywhere (``silverleg.py``, ``numbers/agent.py``, ``macro_climate.py``) but
produced by nothing in the tracked estate. The source, grain, columns and every derived
value in this module were reverse-engineered from the live physical silver parquet
(``silver/weather/source=noaa_oni/part-000.parquet``, 915 rows, 1950-01..2026-03) plus the
registry contract; see ``docs/adr/ADR-002-noaa-oni-source.md`` for the source decision.

File format
-----------
A one-line header, then one row per overlapping 3-month season (12 rows/year), 1950-present::

     SEAS  YR   TOTAL   ANOM
      DJF 1950  24.72  -1.53
      JFM 1950  25.17  -1.34
      ...
      MAM 2026  28.08   0.51

Columns: ``SEAS`` the 3-month season label (DJF..NDJ), ``YR`` the year, ``TOTAL`` the
absolute Nino-3.4 SST (degC), ``ANOM`` the ONI anomaly (degC, the 3-month running SST
anomaly). ANOM is published to two decimals -- this is the *unrounded* ONI, not the
one-decimal figure shown on the CPC website table.

What is the ONI?
----------------
The Oceanic Nino Index is NOAA's canonical ENSO state: the 3-month running mean of the
ERSSTv5 SST anomaly in the Nino-3.4 region (5N-5S, 120W-170W). An El Nino event is
classified when the ONI is >= +0.5 degC and a La Nina when it is <= -0.5 degC. The IOD
(``noaa_iod``) is the orthogonal Indian-Ocean driver; ONI is the Pacific one.

Season -> month convention
--------------------------
Each overlapping 3-month season is stamped to its CENTER month so the table is one row per
(year, month): DJF -> Jan(1), JFM -> Feb(2), FMA -> Mar(3), MAM -> Apr(4), AMJ -> May(5),
MJJ -> Jun(6), JJA -> Jul(7), JAS -> Aug(8), ASO -> Sep(9), SON -> Oct(10), OND -> Nov(11),
NDJ -> Dec(12). Verified against the live silver (season/month agree 1:1 across all 915 rows).

Missing-value handling (INV-4)
------------------------------
The ONI file publishes only completed seasons, so it has no sentinel rows in practice. This
parser still guards defensively: an unparseable ANOM stays ``None`` (never synthesized as
zero) so the absent-measure-stays-null invariant holds if NOAA ever ships a placeholder.

THE VINTAGE CAPTURE OF BOTH ENSO INDEX FILES (data repairs 0929, lane ENSO; ENSO-1 + ENSO-2)
--------------------------------------------------------------------------------------------
``extract_oni_bronze`` above is UNCHANGED and still feeds ``silver_noaa_oni`` (one row per season,
the legacy index, latest revision only). Everything below it serves the NEW table
``silver_noaa_enso_vintages`` and never touches the served one:

* NOAA made the RELATIVE ONI its official ENSO index from 2026-02-01 (NWS PNS 26-05, issued
  2026-01-13) and keeps the legacy file "for users that require that continuity". The two files
  differ in shape (RONI has no TOTAL column; the legacy parser above raises on it), so each file is
  read by :func:`parse_enso_index_text` against ITS OWN declared header and fails closed on any other.
* NOAA rewrites both files in place every month and restates history (measured on the saved captures:
  883 of 917 legacy seasons changed between the 2026-07-26 and 2026-09-07 captures; 868 of 917 RONI
  seasons between 2026-07-21 and 2026-08-20). A vintage is therefore a CAPTURE, identified by the
  sha256 of its decoded text and dated by a publisher clock -- the origin's HTTP ``Last-Modified``,
  or an archive's record of it, or the archive's verified capture instant (an upper bound: late is
  safe) -- NEVER by our fetch time. A live body without ``Last-Modified`` is kept as evidence under the
  ``undated`` clock and is never put in the table.
* The index identity is the file's URL (:func:`index_id_for_url`), never a display name; which index
  is OFFICIAL, and from when, is the publisher's statement held verbatim in
  :data:`ENSO_STATUS_STATEMENTS`, from which the dates are EXTRACTED by code and pinned by a deck
  against the saved statement text.
"""
from __future__ import annotations

import gzip
import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Mapping, Optional
from urllib.parse import urlparse

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# The 12 overlapping 3-month ONI seasons, each mapped to its CENTER month (1-12).
SEASON_TO_MONTH: dict[str, int] = {
    "DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
    "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12,
}

# A defensive missing sentinel: any value at/below this is treated as absent. The live ONI
# file uses no sentinel, but NOAA sibling files (e.g. detrend.nino34) use -99.9 / -9999.
_MISSING_SENTINEL = -99.0

# A data row is three whitespace-separated numeric-ish fields after a 3-letter season token.
_DATA_ROW_RE = re.compile(r"^\s*([A-Z]{3})\s+(\d{4})\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*$")

BRONZE_COLUMNS: list[str] = [
    "year",
    "month",
    "season",
    "oni_total",
    "oni_anom",
    "source",
]


def extract_oni_bronze(raw_bytes: bytes) -> pd.DataFrame:
    """Parse the NOAA CPC ONI ascii file into a long-format bronze DataFrame.

    Args:
        raw_bytes: Raw bytes of ``oni.ascii.txt`` from S3 (or an HTTP fetch).

    Returns:
        DataFrame with columns :data:`BRONZE_COLUMNS`, one row per (year, month), sorted
        chronologically. ``oni_total`` / ``oni_anom`` are ``NaN`` for any sentinel row.

    Raises:
        ValueError: If no parseable data rows are found, or a season token is unrecognized.
    """
    text = raw_bytes.decode("utf-8", errors="replace")
    lines = text.strip().splitlines()

    records: list[dict] = []
    skipped = 0
    for line in lines:
        m = _DATA_ROW_RE.match(line)
        if not m:
            # Header (" SEAS  YR   TOTAL   ANOM") and any stray footer line.
            skipped += 1
            continue
        season, year_s, total_s, anom_s = m.group(1), m.group(2), m.group(3), m.group(4)
        if season not in SEASON_TO_MONTH:
            raise ValueError(f"ONI bronze: unrecognized season token {season!r}")
        year = int(year_s)
        total = _parse_measure(total_s)
        anom = _parse_measure(anom_s)
        records.append({
            "year": year,
            "month": SEASON_TO_MONTH[season],
            "season": season,
            "oni_total": total,
            "oni_anom": anom,
        })

    if not records:
        raise ValueError("ONI bronze: no parseable rows found -- file may be malformed or empty")

    df = pd.DataFrame(records)
    df["source"] = "noaa_oni"
    df = (
        df[BRONZE_COLUMNS]
        .sort_values(["year", "month"])
        .reset_index(drop=True)
    )

    non_null = int(df["oni_anom"].notna().sum())
    logger.info(
        "ONI bronze: %d rows parsed  non-null_anom=%d  years=%d-%d  (skipped %d header/footer lines)",
        len(df), non_null, int(df["year"].min()), int(df["year"].max()), skipped,
    )
    return df


def _parse_measure(token: str):
    try:
        val = float(token)
    except (TypeError, ValueError):
        return None
    return None if val <= _MISSING_SENTINEL else val


# ===========================================================================
# THE VINTAGE CAPTURE (data repairs 0929, lane ENSO). Pure: no network, no S3, no clock.
# ===========================================================================

@dataclass(frozen=True)
class EnsoIndexFile:
    """One NOAA CPC ENSO index file: its URL (the identity) and the header it publishes.

    ``header`` is the file's own first line split on whitespace. The parser refuses a body whose
    header differs, so a publisher that changes a file's shape (the RONI file has no TOTAL column)
    is a counted refusal, never a silent mis-read of columns."""

    url: str
    header: tuple[str, ...]


ONI_LEGACY_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
RONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt"

# The two files NOAA publishes for the 3-month ENSO index. The legacy URL is the one this module's
# ``extract_oni_bronze`` has always read (jobs/ingest/fetch_noaa_oni.py `_ONI_URL`); the RONI URL is
# the one NWS PNS 26-05 names ("The following is a text file of the RONI: <url>"). The monthly
# Rnino34.ascii.txt is a DIFFERENT, monthly series and is deliberately NOT one of these files.
ENSO_INDEX_FILES: tuple[EnsoIndexFile, ...] = (
    EnsoIndexFile(ONI_LEGACY_URL, ("SEAS", "YR", "TOTAL", "ANOM")),
    EnsoIndexFile(RONI_URL, ("SEAS", "YR", "ANOM")),
)


def index_id_for_url(url: str) -> str:
    """The index identity, derived from the file's URL and nothing else.

    ``<first host label that is not 'www'>_<file name without '.txt', dots to underscores, lower>``:
    ``https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt`` -> ``cpc_oni_ascii`` and
    ``.../RONI.ascii.txt`` -> ``cpc_roni_ascii``. A display name ("ONI", "Relative ONI") is never the
    identity: the publisher renamed the index once already."""
    parsed = urlparse(url)
    labels = [lab for lab in (parsed.hostname or "").split(".") if lab and lab != "www"]
    name = parsed.path.rsplit("/", 1)[-1]
    if not labels or not name:
        raise ValueError(f"ENSO index URL has no host label or file name: {url!r}")
    if name.lower().endswith(".txt"):
        name = name[: -len(".txt")]
    return f"{labels[0]}_{name.replace('.', '_').lower()}"


def _index_files_by_id(files: tuple[EnsoIndexFile, ...] = ENSO_INDEX_FILES) -> dict[str, EnsoIndexFile]:
    out: dict[str, EnsoIndexFile] = {}
    for f in files:
        iid = index_id_for_url(f.url)
        if iid in out:
            raise ValueError(f"two ENSO index files derive one index_id {iid!r}")
        out[iid] = f
    return out


ENSO_INDEX_FILES_BY_ID: dict[str, EnsoIndexFile] = _index_files_by_id()


def decode_capture_body(body: bytes) -> bytes:
    """The text bytes of a capture: gunzipped when the body starts with the gzip magic bytes.

    Seven of the eleven saved archive captures are gzip bytes served under a ``.txt`` name with no
    Content-Encoding; the decision is the body's own magic number, never its name or a header."""
    if body[:2] == b"\x1f\x8b":
        return gzip.decompress(body)
    return body


def content_sha256(body: bytes) -> str:
    """The vintage identity: sha256 of the DECODED text (one content in two encodings is one vintage)."""
    return hashlib.sha256(decode_capture_body(body)).hexdigest()


def parse_enso_index_text(text_bytes: bytes, header: tuple[str, ...]) -> pd.DataFrame:
    """Parse one ENSO index file against ITS OWN declared header; fail closed on anything else.

    Returns ``season, year, month, anom`` in file order (one row per season, month = the CENTRE
    month through the ONE :data:`SEASON_TO_MONTH`, year = ``YR`` as printed). Raises ``ValueError``
    on: a header other than ``header``; a data line whose field count differs from the header's; an
    unknown season token; a non-integer year; a duplicate season; a gap or reversal between
    consecutive seasons (the files are contiguous from DJF 1950, so a hole is a malformed body, and a
    season shifted by one shows up here rather than in a served figure). ``ANOM`` goes through the
    same :func:`_parse_measure` as the legacy parser (a sentinel stays NaN, never 0)."""
    text = text_bytes.decode("utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("ENSO index file is empty")
    got_header = tuple(lines[0].split())
    if got_header != tuple(header):
        raise ValueError(f"ENSO index header {got_header!r} is not the declared {tuple(header)!r}")
    i_seas, i_yr, i_anom = header.index("SEAS"), header.index("YR"), header.index("ANOM")
    records: list[dict] = []
    prev_ordinal: Optional[int] = None
    for lineno, line in enumerate(lines[1:], start=2):
        parts = line.split()
        if len(parts) != len(header):
            raise ValueError(f"line {lineno}: {len(parts)} fields where the header has {len(header)}")
        season = parts[i_seas]
        if season not in SEASON_TO_MONTH:
            raise ValueError(f"line {lineno}: unknown season token {season!r}")
        if not parts[i_yr].isdigit():
            raise ValueError(f"line {lineno}: year {parts[i_yr]!r} is not an integer")
        year, month = int(parts[i_yr]), SEASON_TO_MONTH[season]
        ordinal = year * 12 + month
        if prev_ordinal is not None and ordinal != prev_ordinal + 1:
            raise ValueError(f"line {lineno}: {season} {year} does not follow the previous season")
        prev_ordinal = ordinal
        anom = _parse_measure(parts[i_anom])
        records.append({"season": season, "year": year, "month": month,
                         "anom": float("nan") if anom is None else float(anom)})
    if not records:
        raise ValueError("ENSO index file has a header and no data rows")
    return pd.DataFrame.from_records(records, columns=["season", "year", "month", "anom"])


def season_end_month(year: int, month: int) -> tuple[int, int]:
    """(year, month) of the LAST month of the 3-month season centred on (year, month)."""
    return (year + 1, 1) if month == 12 else (year, month + 1)


# --- the capture clock ---------------------------------------------------------------------------
# A vintage's date is when the PUBLISHER's file is evidenced to have carried that content, read from
# a publisher clock, never from ours. The rungs, strongest first:
CLOCK_ORIGIN_LAST_MODIFIED = "origin_last_modified"                  # NOAA's own Last-Modified, live
CLOCK_ARCHIVE_ORIGIN_LAST_MODIFIED = "archive_origin_last_modified"  # NOAA's Last-Modified as an archive recorded it
CLOCK_ARCHIVE_CAPTURE = "archive_capture"                            # the archive's verified capture instant (upper bound)
CLOCK_UNDATED = "undated"                                            # a live body with no Last-Modified: evidence, never dated
DATED_CLOCKS: tuple[str, ...] = (CLOCK_ORIGIN_LAST_MODIFIED, CLOCK_ARCHIVE_ORIGIN_LAST_MODIFIED,
                                 CLOCK_ARCHIVE_CAPTURE)
ARCHIVE_ORIGIN_LAST_MODIFIED_HEADER = "X-Archive-Orig-Last-Modified"

# The raw capture root. OUTSIDE ``raw/weather/source=noaa_oni/`` (whose one object the served producer
# overwrites every month) and not a string-prefix of it or of any sibling, so no LIST of the served
# prefix can swallow a capture and no capture LIST can swallow the served object.
ENSO_CAPTURE_PREFIX = "raw/weather/source=noaa_cpc_enso_captures/"
_STAMP_FMT = "%Y%m%dT%H%M%SZ"
_CAPTURE_KEY_RE = re.compile(
    r"^" + re.escape(ENSO_CAPTURE_PREFIX)
    + r"index_id=(?P<index_id>[a-z0-9_]+)/clock=(?P<clock>[a-z_]+)/evidence=(?P<evidence>\d{8}T\d{6}Z|none)"
    r"/sha256=(?P<sha>[0-9a-f]{64})\.txt$")


@dataclass(frozen=True)
class EnsoCapture:
    """One held body of one ENSO index file, with the publisher clock that dates it.

    ``body`` is the bytes AS HELD (an archive body may be gzip); ``sha256`` is the decoded content's."""

    index_id: str
    source_url: str
    clock: str
    evidence_utc: Optional[datetime]
    sha256: str
    body: bytes

    @property
    def key(self) -> str:
        return enso_capture_key(self.index_id, self.clock, self.evidence_utc, self.sha256)


def enso_capture_key(index_id: str, clock: str, evidence_utc: Optional[datetime], sha256: str) -> str:
    """The raw key of one capture. It CARRIES the clock, so the date survives the loss of any sidecar,
    and it carries the content digest, so one content under one clock instant is one object (a
    re-capture of an unchanged file is a no-op, never an overwrite)."""
    if clock not in DATED_CLOCKS + (CLOCK_UNDATED,):
        raise ValueError(f"unknown capture clock {clock!r}")
    if (evidence_utc is None) != (clock == CLOCK_UNDATED):
        raise ValueError(f"clock {clock!r} and evidence {evidence_utc!r} disagree")
    stamp = "none" if evidence_utc is None else evidence_utc.astimezone(timezone.utc).strftime(_STAMP_FMT)
    return (f"{ENSO_CAPTURE_PREFIX}index_id={index_id}/clock={clock}/evidence={stamp}"
            f"/sha256={sha256}.txt")


def parse_enso_capture_key(key: str) -> dict:
    """``{index_id, clock, evidence_utc, sha256}`` from a capture key; ``ValueError`` if it is not one."""
    m = _CAPTURE_KEY_RE.match(key)
    if not m:
        raise ValueError(f"not an ENSO capture key: {key!r}")
    ev = m.group("evidence")
    evidence = None if ev == "none" else datetime.strptime(ev, _STAMP_FMT).replace(tzinfo=timezone.utc)
    return {"index_id": m.group("index_id"), "clock": m.group("clock"), "evidence_utc": evidence,
            "sha256": m.group("sha")}


def capture_from_held_object(key: str, body: bytes) -> EnsoCapture:
    """Rebuild a capture from its raw key and its bytes (the vintages builder's input)."""
    k = parse_enso_capture_key(key)
    index_file = ENSO_INDEX_FILES_BY_ID.get(k["index_id"])
    url = index_file.url if index_file is not None else ""
    return EnsoCapture(index_id=k["index_id"], source_url=url, clock=k["clock"],
                       evidence_utc=k["evidence_utc"], sha256=k["sha256"], body=body)


def _http_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    for k, v in (headers or {}).items():
        if str(k).lower() == name.lower():
            return v
    return None


def capture_from_origin(url: str, headers: Mapping[str, str], body: bytes) -> EnsoCapture:
    """A body fetched from NOAA itself: dated by NOAA's ``Last-Modified``, else ``undated``.

    When a ``Content-Length`` is present on an un-encoded response it must equal the body's length (a
    truncated body is refused, never banked as a vintage). Under a ``Content-Encoding`` the header counts
    the ENCODED bytes while ``body`` is the decoded one, so the comparison would be meaningless there."""
    cl = _header(headers, "Content-Length")
    encoding = (_header(headers, "Content-Encoding") or "identity").strip().lower()
    if (encoding == "identity" and cl is not None and str(cl).strip().isdigit()
            and int(cl) != len(body)):
        raise ValueError(f"{url}: Content-Length {cl} but the body is {len(body)} bytes")
    lm = _http_date(_header(headers, "Last-Modified"))
    clock = CLOCK_ORIGIN_LAST_MODIFIED if lm is not None else CLOCK_UNDATED
    return EnsoCapture(index_id=index_id_for_url(url), source_url=url, clock=clock, evidence_utc=lm,
                       sha256=content_sha256(body), body=body)


def capture_from_archive(url: str, served_ts14: str, headers: Mapping[str, str], body: bytes) -> EnsoCapture:
    """A body replayed from a web archive, whose SERVED capture instant is ``served_ts14``.

    The caller verifies ``served_ts14`` against the replay itself (a requested timestamp is a request,
    not a guarantee). NOAA's own Last-Modified, when the archive recorded it
    (``X-Archive-Orig-Last-Modified``) and it is not later than the capture, dates the vintage;
    otherwise the capture instant does -- an UPPER bound on when the content was known. The archive's
    OWN Last-Modified header is the crawl's and is never read."""
    captured = datetime.strptime(served_ts14, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    origin_lm = _http_date(_header(headers, ARCHIVE_ORIGIN_LAST_MODIFIED_HEADER))
    if origin_lm is not None and origin_lm <= captured:
        clock, evidence = CLOCK_ARCHIVE_ORIGIN_LAST_MODIFIED, origin_lm
    else:
        clock, evidence = CLOCK_ARCHIVE_CAPTURE, captured
    return EnsoCapture(index_id=index_id_for_url(url), source_url=url, clock=clock, evidence_utc=evidence,
                       sha256=content_sha256(body), body=body)


# --- which index is OFFICIAL, from the publisher's own words ------------------------------------------

@dataclass(frozen=True)
class IndexStatusStatement:
    """A publisher statement that changes which ENSO index is official, held VERBATIM.

    The dates are never typed: :func:`statement_effective_date` and :func:`statement_issued_date`
    extract them from ``effective_quote`` and ``issued_line``, and a deck pins that every quote is a
    verbatim passage of the saved statement (tests/fixtures/noaa_oni/pns26-05_excerpt.txt)."""

    statement_id: str
    statement_url: str
    issued_line: str              # the statement's own dateline, verbatim
    effective_quote: str          # the sentence carrying "effective <Month> <d>, <yyyy>", verbatim
    becomes_official_url: str     # the file the statement makes official
    becomes_quote: str            # the statement's words naming that file, verbatim
    ceases_official_url: str      # the file that stops being official on the same date
    ceases_quote: str             # the statement's words about it, verbatim


ENSO_STATUS_STATEMENTS: tuple[IndexStatusStatement, ...] = (
    IndexStatusStatement(
        statement_id="NWS PNS 26-05",
        statement_url="https://www.weather.gov/media/notification/pdf_2026/pns26-05_Relative_ONI.pdf",
        issued_line="240 PM EST Tue Jan 13, 2026",
        effective_quote=(
            "The National Centers for Environmental Prediction (NCEP) Climate Prediction Center (CPC) "
            "informs the public of the shift to a Relative Oceanic Niño Index for the official "
            "monitoring and prediction of the El Niño-Southern Oscillation (ENSO) phenomenon, "
            "effective February 1, 2026."),
        becomes_official_url=RONI_URL,
        becomes_quote=("The following is a text file of the RONI: "
                       "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt"),
        ceases_official_url=ONI_LEGACY_URL,
        ceases_quote=("Importantly, the legacy Niño 3.4 and Oceanic Niño Index files will continue "
                      "to be updated for users that require that continuity."),
    ),
)

_MONTHS = {m: i for i, m in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"), start=1)}
_EFFECTIVE_RE = re.compile(r"effective (?P<mon>[A-Z][a-z]+) (?P<day>\d{1,2}), (?P<year>\d{4})")
_ISSUED_RE = re.compile(r"(?P<mon>[A-Z][a-z]{2}) (?P<day>\d{1,2}), (?P<year>\d{4})\s*$")


def statement_effective_date(stmt: IndexStatusStatement) -> date:
    """The date the statement takes effect, read from its own sentence (fails closed if absent)."""
    found = _EFFECTIVE_RE.findall(stmt.effective_quote)
    if len(found) != 1 or found[0][0] not in _MONTHS:
        raise ValueError(f"{stmt.statement_id}: no single 'effective <Month> <d>, <yyyy>' in its quote")
    mon, day, year = found[0]
    return date(int(year), _MONTHS[mon], int(day))


def statement_issued_date(stmt: IndexStatusStatement) -> date:
    """The statement's issue date, read from its own dateline ('... Tue Jan 13, 2026')."""
    m = _ISSUED_RE.search(stmt.issued_line)
    abbrev = {name[:3]: num for name, num in _MONTHS.items()}
    if not m or m.group("mon") not in abbrev:
        raise ValueError(f"{stmt.statement_id}: dateline {stmt.issued_line!r} carries no date")
    return date(int(m.group("year")), abbrev[m.group("mon")], int(m.group("day")))


@dataclass(frozen=True)
class OfficialWindow:
    """When an index is the official one: ``[official_from, official_until)``, dates as 'YYYY-MM-DD'.

    ``official_until`` is the FIRST day the index is no longer official (the successor's
    ``official_from``), so the windows of a predecessor and its successor meet with no gap and no
    overlap. ``None`` = no publisher statement held for that bound (never guessed)."""

    official_from: Optional[str]
    official_until: Optional[str]
    official_statement: Optional[str]


def official_windows(statements: tuple[IndexStatusStatement, ...] = ENSO_STATUS_STATEMENTS,
                     files: tuple[EnsoIndexFile, ...] = ENSO_INDEX_FILES) -> dict[str, OfficialWindow]:
    """``{index_id: OfficialWindow}`` for every declared index file, from the statements alone."""
    bounds: dict[str, dict] = {index_id_for_url(f.url): {"from": None, "until": None, "notes": []}
                               for f in files}
    for stmt in sorted(statements, key=statement_effective_date):
        eff = statement_effective_date(stmt).isoformat()
        cite = f"{stmt.statement_id} issued {statement_issued_date(stmt).isoformat()} ({stmt.statement_url})"
        for url, side in ((stmt.becomes_official_url, "from"), (stmt.ceases_official_url, "until")):
            iid = index_id_for_url(url)
            if iid not in bounds:
                raise ValueError(f"{stmt.statement_id} names {url!r}, which is not a declared index file")
            if bounds[iid][side] is not None:
                raise ValueError(f"{iid}: two statements set official_{side}")
            bounds[iid][side] = eff
            bounds[iid]["notes"].append(f"official_{side} {eff}: {cite}")
    out: dict[str, OfficialWindow] = {}
    for iid, b in bounds.items():
        notes = list(b["notes"])
        if b["from"] is None:
            notes.append("official_from: no publisher statement held")
        if b["until"] is None:
            notes.append("official_until: none (official at the newest statement held)")
        out[iid] = OfficialWindow(b["from"], b["until"], "; ".join(notes))
    return out
