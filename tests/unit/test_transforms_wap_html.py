"""Unit tests for WAP HTML (Wayback) text extraction — Phase 3 (source C).

Tests cover:
- _find_subpage_urls: sub-page URL discovery from TOC HTML
- extract_wap_html: single-page era, multi-page era, section splitting, schema

All tests use static HTML strings (no HTTP, no S3).
"""
from __future__ import annotations

import pytest
from leviathan.transforms.raw_to_text.wap_html import (
    _find_subpage_urls,
    extract_wap_html,
)

# ---------------------------------------------------------------------------
# _find_subpage_urls — sub-page URL discovery
# ---------------------------------------------------------------------------

_TOC_WITH_SUBPAGES = """
<html>
<body>
<h1>World Agricultural Production - October 1999</h1>
<p>Download: <a href="wap.wk4">Lotus 123</a></p>
<ul>
  <li><a href="wap1.htm">Part 1: Grains &amp; Rice</a></li>
  <li><a href="wap2.htm">Part 2: Oilseeds &amp; Cotton</a></li>
</ul>
</body>
</html>
"""

_TOC_WITHOUT_SUBPAGES = """
<html>
<body>
<h1>World Agricultural Production - March 1997</h1>
<p>WHEAT:  Production outlook favorable in North America.</p>
<p>COARSE GRAINS:  Corn area revised upward in Brazil.</p>
</body>
</html>
"""

_TOC_ABSOLUTE_WAYBACK_URLS = """
<html>
<body>
<a href="https://web.archive.org/web/20010101000000*/http://www.fas.usda.gov/wap/wap1.htm">Part 1</a>
<a href="https://web.archive.org/web/20010101000000*/http://www.fas.usda.gov/wap/wap2.htm">Part 2</a>
</body>
</html>
"""


def test_find_subpage_urls_relative() -> None:
    base = "https://web.archive.org/web/19991015000000*/http://www.fas.usda.gov/wap/wap.html"
    urls = _find_subpage_urls(_TOC_WITH_SUBPAGES, base)
    assert len(urls) == 2
    assert all("wap1.htm" in u or "wap2.htm" in u for u in urls)


def test_find_subpage_urls_order() -> None:
    base = "https://web.archive.org/web/19991015000000*/http://www.fas.usda.gov/wap/wap.html"
    urls = _find_subpage_urls(_TOC_WITH_SUBPAGES, base)
    # wap1.htm should come before wap2.htm
    assert "wap1" in urls[0]
    assert "wap2" in urls[1]


def test_find_subpage_urls_no_links() -> None:
    base = "https://web.archive.org/web/19971001000000*/http://www.fas.usda.gov/wap/wap.html"
    urls = _find_subpage_urls(_TOC_WITHOUT_SUBPAGES, base)
    assert urls == []


def test_find_subpage_urls_deduplication() -> None:
    """Duplicate hrefs should appear only once."""
    toc = """
    <html><body>
      <a href="wap1.htm">Part 1</a>
      <a href="wap1.htm">Part 1 again</a>
      <a href="wap2.htm">Part 2</a>
    </body></html>
    """
    base = "https://web.archive.org/web/20000101000000*/http://www.fas.usda.gov/wap/wap.html"
    urls = _find_subpage_urls(toc, base)
    assert len(urls) == 2


def test_find_subpage_urls_ignores_non_wap_links() -> None:
    toc = """
    <html><body>
      <a href="index.htm">Home</a>
      <a href="wap.wk4">Lotus download</a>
      <a href="wap1.htm">WAP part 1</a>
    </body></html>
    """
    base = "https://web.archive.org/web/20000101000000*/http://www.fas.usda.gov/wap/wap.html"
    urls = _find_subpage_urls(toc, base)
    assert len(urls) == 1


# ---------------------------------------------------------------------------
# extract_wap_html — single-page era (1996–1998)
# ---------------------------------------------------------------------------

_SINGLE_PAGE_HTML = """
<html>
<body>
<h1>World Agricultural Production — September 1997</h1>
<p>WHEAT:  World wheat production for 1997/98 is projected at a record 610 million metric tons.
U.S. wheat production is forecast at 2.48 billion bushels, up slightly from the previous estimate.</p>
<p>COARSE GRAINS:  U.S. corn production is forecast at 9.3 billion bushels.
Global coarse grain output is up from last month.</p>
<p>RICE:  World milled rice production estimated at 380 million metric tons.</p>
</body>
</html>
"""


def test_single_page_source_field() -> None:
    doc = extract_wap_html(
        toc_html=_SINGLE_PAGE_HTML,
        subpage_texts=[],
        raw_key="raw/production/source=usda_wap_html/release_month=1997-09/wap.html",
        release_month="1997-09",
    )
    assert doc["source"] == "usda_wap"


def test_single_page_extraction_method() -> None:
    doc = extract_wap_html(_SINGLE_PAGE_HTML, [], "dummy_key", "1997-09")
    assert doc["extraction_method"] == "beautifulsoup"


def test_single_page_schema_fields() -> None:
    doc = extract_wap_html(_SINGLE_PAGE_HTML, [], "dummy_raw_key", "1997-09")
    assert isinstance(doc["full_text"], str)
    assert isinstance(doc["sections"], list)
    assert isinstance(doc["extracted_at"], str)
    assert len(doc["extracted_at"]) == 20


def test_single_page_full_text_populated() -> None:
    doc = extract_wap_html(_SINGLE_PAGE_HTML, [], "dummy_key", "1997-09")
    assert "wheat" in doc["full_text"].lower() or "WHEAT" in doc["full_text"]


def test_single_page_sections_split() -> None:
    doc = extract_wap_html(_SINGLE_PAGE_HTML, [], "dummy_key", "1997-09")
    names = [s["name"] for s in doc["sections"]]
    assert "wheat" in names
    assert "coarse_grains" in names
    assert "rice" in names


# ---------------------------------------------------------------------------
# extract_wap_html — multi-page era (1999–2002)
# ---------------------------------------------------------------------------

_TOC_HTML = """
<html>
<body>
<h1>World Agricultural Production — October 1999</h1>
<ul>
  <li><a href="wap1.htm">Grains</a></li>
  <li><a href="wap2.htm">Oilseeds</a></li>
</ul>
</body>
</html>
"""

_WAP1_TEXT = (
    "WHEAT:  World wheat production for 1999/2000 is forecast at 591 million metric tons.\n"
    "Russia wheat output revised downward.\n"
    "COARSE GRAINS:  Global corn output increased for South America.\n"
    "RICE:  Global rice consumption slightly above production.\n"
)

_WAP2_TEXT = (
    "OILSEEDS:  World soybean production raised for Argentina and Brazil.\n"
    "COTTON:  World cotton area harvested reduced for Pakistan and India.\n"
)


def test_multipage_subpages_used() -> None:
    doc = extract_wap_html(_TOC_HTML, [_WAP1_TEXT, _WAP2_TEXT], "dummy_key", "1999-10")
    assert "wheat" in doc["full_text"].lower() or "WHEAT" in doc["full_text"]
    assert "soybean" in doc["full_text"].lower() or "OILSEEDS" in doc["full_text"]


def test_multipage_toc_content_excluded() -> None:
    """TOC page content should not appear in full_text when subpages are provided."""
    doc = extract_wap_html(_TOC_HTML, [_WAP1_TEXT, _WAP2_TEXT], "dummy_key", "1999-10")
    # "Grains" is only in the TOC nav link — should NOT appear in subpage text
    # (subpage text is the commodity narrative, not nav HTML)
    # The full_text should be the joined subpage texts
    assert doc["full_text"].strip() == (_WAP1_TEXT + "\n" + _WAP2_TEXT).strip()


def test_multipage_sections_split() -> None:
    doc = extract_wap_html(_TOC_HTML, [_WAP1_TEXT, _WAP2_TEXT], "dummy_key", "1999-10")
    names = [s["name"] for s in doc["sections"]]
    assert "wheat" in names
    assert "coarse_grains" in names
    assert "oilseeds" in names
    assert "cotton" in names


def test_multipage_raw_key_preserved() -> None:
    raw_key = "raw/production/source=usda_wap_html/release_month=1999-10/wap.html"
    doc = extract_wap_html(_TOC_HTML, [_WAP1_TEXT], raw_key, "1999-10")
    assert doc["raw_key"] == raw_key


def test_empty_subpages_fallback_to_toc() -> None:
    """When subpage_texts is empty, full_text is extracted from toc_html."""
    doc = extract_wap_html(_SINGLE_PAGE_HTML, [], "dummy_key", "1997-09")
    assert len(doc["full_text"]) > 0
