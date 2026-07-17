"""WAP Wayback HTML → text/ layer transform (Phase 3, source C).

Handles the 1996–2002 WAP circulars that were published as HTML on fas.usda.gov
and are only available via the Wayback Machine.  The raw TOC page is stored in
S3 under ``raw/production/source=usda_wap_html/``.

Report structure by era:
- 1996–1998: Single-page HTML — the stored ``wap.html`` IS the full report.
  No sub-page links to follow.
- 1999–2002: Multi-page HTML — ``wap.html`` is a TOC that links to
  ``wap1.htm`` / ``wap2.htm`` sub-pages hosted on the Wayback Machine.
  Sub-pages are NOT stored in S3; they must be fetched at runtime.

HTML layout is navigation-only — ``<table>`` elements contain no production
data.  All data is in plain ``<p>`` or bare text nodes within sub-pages.
Text is extracted with BeautifulSoup ``get_text()``.

Commodity sections are split on the same headings as WASDE/WAP PDFs.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from leviathan.transforms.raw_to_text.schema import DocumentJson
from leviathan.transforms.raw_to_text.wasde_digital import _split_sections

# Wayback Machine CDX base — sub-page URLs found in TOC pages are relative
# archive.org paths; we rebase them against this prefix when needed.
_WAYBACK_BASE = "https://web.archive.org"

# Commodity section regex (same as WASDE digital / WAP PDF).
_SECTION_RE = re.compile(
    r"(?m)^(WHEAT|COARSE GRAINS|RICE|OILSEEDS|COTTON|SUGAR):"
)


def _find_subpage_urls(toc_html: str, base_url: str) -> list[str]:
    """Return absolute Wayback URLs for WAP sub-pages linked from a TOC page.

    Looks for ``<a href>`` links whose target filename matches ``wap*.htm``
    (e.g. ``wap1.htm``, ``wap2.htm``).  Returns an empty list for 1996–1998
    single-page reports that have no such links.

    Args:
        toc_html: Raw HTML content of the TOC / ``wap.html`` page.
        base_url: Absolute URL of the TOC page, used to resolve relative hrefs
                  (e.g. ``https://web.archive.org/web/19991201000000*/...``).
    """
    soup = BeautifulSoup(toc_html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        # Match links like "wap1.htm", "../wap2.htm", absolute wayback paths
        basename = href.split("/")[-1].split("?")[0].lower()
        if re.match(r"wap\d+\.htm$", basename):
            abs_url = urljoin(base_url, href)
            if abs_url not in seen:
                seen.add(abs_url)
                urls.append(abs_url)

    return urls


def _html_to_text(html: str) -> str:
    """Extract plain text from an HTML string using BeautifulSoup."""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n").strip()


def extract_wap_html(
    toc_html: str,
    subpage_texts: list[str],
    raw_key: str,
    release_month: str,
) -> DocumentJson:
    """Build a :class:`DocumentJson` from a WAP HTML report.

    For single-page reports (1996–1998) pass an empty ``subpage_texts`` list;
    the full text is extracted directly from ``toc_html``.

    For multi-page reports (1999–2002), ``subpage_texts`` contains the
    text content of each sub-page (``wap1.htm``, ``wap2.htm``) already
    fetched from the Wayback Machine.

    Args:
        toc_html:       Raw HTML of the stored ``wap.html`` TOC page.
        subpage_texts:  List of plain-text strings, one per sub-page fetched.
                        Pass ``[]`` for single-page era reports.
        raw_key:        S3 key of the stored ``wap.html`` (lineage).
        release_month:  YYYY-MM string.
    """
    if subpage_texts:
        # Multi-page era: sub-pages contain all content.
        full_text = "\n".join(subpage_texts).strip()
    else:
        # Single-page era: TOC page IS the report.
        full_text = _html_to_text(toc_html)

    sections = _split_sections(full_text)

    return DocumentJson(
        source="usda_wap",
        raw_key=raw_key,
        extraction_method="beautifulsoup",
        extracted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sections=sections,
        full_text=full_text,
    )
