"""ICCO cocoa-statistics HTML -> text/ layer transform.

Handles the International Cocoa Organization (ICCO) news-release pages that were
scraped from ``icco.org`` and stored in S3 as ``page.html`` (NOT PDFs -- see the
"Format note" below).  Two ICCO sources share one WordPress layout and are both
handled by this reader:

* ``source=icco_qbcs_summary`` -- the Quarterly Bulletin of Cocoa Statistics
  (QBCS) summary release.  97 raw objects = 49 ``page.html`` + 48 JSON sidecars
  (one release lacks a sidecar).  Partitioned by ``release_date=YYYY-MM-DD``.
* ``source=icco_ewg_stocks`` -- the annual Expert Working Group on Stocks
  (EWG-S) world-cocoa-bean-stocks release.  Partitioned by ``season=YYYY-YY``
  (NO ``release_date`` in the key -- see date derivation below).

Format note (spec correction)
-----------------------------
The TRACK B plan described these as "97 QBCS *PDFs* ... extraction_method
'pdfplumber'".  The censused raw layer contains no PDFs -- the objects are
scraped HTML pages (``page.html``).  Extraction is therefore BeautifulSoup,
identical to ``wap_html.py``, and ``extraction_method`` is ``"beautifulsoup"``.

Page layout
-----------
Every ICCO release page is an Enfold/WordPress post.  The article body lives in
a single ``div.entry-content`` element; the site chrome (breadcrumb nav, the
"Latest News" sidebar that links to *future* bulletins, the post-meta author
timeline, contact footer) is all OUTSIDE that element.  Reading only
``div.entry-content`` therefore drops the future-news sidebar cleanly -- a PIT
requirement, since a 2008 bulletin's page also lists 2026 headlines.

Body structure (both sources), in document order:
  1. headline    -- the ``h1`` post title ("August 2017 Quarterly Bulletin ...")
  2. intro       -- dateline + "The ICCO today releases ..." paragraph
  3. summary     -- the numeric supply/demand (QBCS) or stocks (EWG) table
  4. notes       -- the a/ b/ ... footnotes block
  5. commentary  -- the descriptive prose ("This issue of the Bulletin ...",
                    or the EWG "The EWG-S estimates ..." paragraph)
A trailing ordering/contact boilerplate block is stripped.

PIT date
--------
Each text doc's stamp must be the bulletin's own PUBLICATION date, never ingest
time.  ``publication_date()`` derives it deterministically:
  * QBCS: from the ``release_date=YYYY-MM-DD`` key partition (authoritative).
  * EWG:  the key carries only ``season=``; the pub date is parsed from the
          "Abidjan, DD Month YYYY" dateline in the article body.
The transform itself carries no date field in ``document.json`` (the schema has
none -- the writer stamps the output partition), matching the house pattern.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from leviathan.transforms.raw_to_text.schema import DocumentJson, Section

# The article body container.  Present on every ICCO release page; everything
# outside it is site chrome (including the future-news sidebar).
_CONTENT_SELECTOR = "entry-content"

# Section anchors.  Each marks the START of a named body segment; text before
# the first anchor is the "intro".  Anchors are matched at line-start so a
# stray in-paragraph mention does not trigger a spurious split.
_SUMMARY_RE = re.compile(r"(?mi)^\s*(Summary of\b|LOCATION OF\b)")
_NOTES_RE = re.compile(r"(?mi)^\s*Notes\b")
_COMMENTARY_RE = re.compile(
    r"(?mi)^\s*(This issue of the Bulletin\b|The EWG-S estimates\b)"
)

# Trailing ordering / contact boilerplate -- everything from the earliest of
# these markers to end-of-body is dropped.
_FOOTER_RE = re.compile(
    r"(?mi)^\s*(Copies of the Quarterly Bulletin\b"
    r"|For more information, please contact\b)"
)

# EWG dateline, e.g. "Abidjan, 22 January 2026".  QBCS always has a
# release_date key so this fallback is exercised only for EWG.
_DATELINE_RE = re.compile(
    r"[A-Za-z][A-Za-z .'-]*,\s+(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{4})"
)
_RELEASE_DATE_KEY_RE = re.compile(r"release_date=(\d{4}-\d{2}-\d{2})")
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _clean(text: str) -> str:
    """Collapse whitespace runs so extracted prose is compact but line-faithful."""
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_footer(body: str) -> str:
    """Drop the trailing ordering/contact boilerplate block, if present."""
    m = _FOOTER_RE.search(body)
    if m:
        return body[: m.start()].rstrip()
    return body


def _split_bulletin(body: str) -> list[Section]:
    """Split the cleaned article body into named ICCO bulletin sections.

    Returns ``intro`` / ``summary`` / ``notes`` / ``commentary`` for whichever
    anchors are present, in document order.  If no anchor is found (an ICCO
    layout this reader has not seen) the whole body is returned as one
    ``summary`` section so retrieval always has content -- mirroring the
    single-section fallback used by ``gain_pdf`` / ``mpob_pdf``.
    """
    markers: list[tuple[int, str]] = []
    for name, rx in (
        ("summary", _SUMMARY_RE),
        ("notes", _NOTES_RE),
        ("commentary", _COMMENTARY_RE),
    ):
        m = rx.search(body)
        if m:
            markers.append((m.start(), name))
    markers.sort()

    if not markers:
        return [Section(name="summary", text=body)] if body else []

    sections: list[Section] = []
    intro = body[: markers[0][0]].strip()
    if intro:
        sections.append(Section(name="intro", text=intro))
    for i, (pos, name) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else len(body)
        seg = body[pos:end].strip()
        if seg:
            sections.append(Section(name=name, text=seg))
    return sections


def _extract_body(soup: BeautifulSoup) -> tuple[str, str]:
    """Return ``(headline, body)`` from the article container.

    ``headline`` is the ``h1`` post title (empty string if absent); ``body`` is
    the cleaned, footer-stripped ``div.entry-content`` text (empty string if the
    container is absent -- the caller then emits an empty doc rather than
    leaking site chrome).
    """
    h1 = soup.find("h1", class_=re.compile(r"entry-title", re.I)) or soup.find("h1")
    headline = h1.get_text(" ", strip=True) if h1 else ""

    container = soup.find("div", class_=_CONTENT_SELECTOR)
    if container is None:
        return headline, ""

    body = _clean(container.get_text("\n", strip=True))
    body = _strip_footer(body)
    return headline, body


def extract_icco_qbcs(
    html_bytes: bytes,
    raw_key: str,
    source_name: str,
) -> DocumentJson:
    """Extract narrative text from an ICCO QBCS or EWG-S release page.

    Reads ``div.entry-content`` (dropping the future-news sidebar and contact
    footer), captures the ``h1`` headline, and splits the body into named
    bulletin sections.  Works for both ``icco_qbcs_summary`` and
    ``icco_ewg_stocks`` -- they share the WordPress layout.

    Args:
        html_bytes:  Raw ``page.html`` bytes from S3 (BeautifulSoup detects the
                     UTF-8 charset from the page's meta tag).
        raw_key:     S3 key of the source ``page.html`` (stored for lineage).
        source_name: Source identifier, e.g. ``"icco_qbcs_summary"`` or
                     ``"icco_ewg_stocks"`` (the raw ``source=`` partition value).

    Returns:
        A :class:`DocumentJson` with ``extraction_method="beautifulsoup"`` and
        a ``headline`` section followed by the split body sections.  When the
        article container is missing, ``sections`` is ``[]`` and ``full_text``
        is ``""``.
    """
    soup = BeautifulSoup(html_bytes, "html.parser")
    headline, body = _extract_body(soup)

    sections: list[Section] = []
    if headline:
        sections.append(Section(name="headline", text=headline))
    sections.extend(_split_bulletin(body))

    if headline and body:
        full_text = headline + "\n\n" + body
    else:
        full_text = (headline or body).strip()

    return DocumentJson(
        source=source_name,
        raw_key=raw_key,
        extraction_method="beautifulsoup",
        extracted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sections=sections,
        full_text=full_text,
    )


def publication_date(raw_key: str, full_text: str | None = None) -> str:
    """Derive the bulletin's own publication date (``YYYY-MM-DD``) for PIT stamping.

    Resolution order (deterministic):
      1. ``release_date=YYYY-MM-DD`` in *raw_key* -- the QBCS partition, and the
         authoritative source whenever present.
      2. The "Abidjan, DD Month YYYY" dateline in *full_text* -- the EWG-S path,
         whose key carries only ``season=`` and no release date.

    Args:
        raw_key:   S3 key of the source page.
        full_text: Extracted article text (required only for the EWG dateline
                   fallback; pass the ``full_text`` from :func:`extract_icco_qbcs`).

    Returns:
        The publication date as ``YYYY-MM-DD``.

    Raises:
        ValueError: If neither a ``release_date`` key nor a parseable dateline
                    is found -- the caller must not stamp an ingest-time date.
    """
    m = _RELEASE_DATE_KEY_RE.search(raw_key)
    if m:
        return m.group(1)

    if full_text:
        d = _DATELINE_RE.search(full_text)
        if d:
            day = int(d.group(1))
            month = _MONTHS[d.group(2).lower()]
            year = int(d.group(3))
            return "%04d-%02d-%02d" % (year, month, day)

    raise ValueError(
        "cannot derive publication date: no release_date= in key %r and no "
        "'Abidjan, DD Month YYYY' dateline in body" % raw_key
    )
