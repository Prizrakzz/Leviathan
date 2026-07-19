"""Unit tests for ICCO QBCS / EWG-S HTML text extraction.

Tests cover:
- extract_icco_qbcs: schema fields, headline capture, section split, footer
  strip, future-news-sidebar exclusion (PIT), missing-container fallback.
- publication_date: release_date key path (QBCS) + dateline fallback (EWG),
  and the ValueError guard against ingest-time stamping.

Synthetic fixtures reproduce the real ICCO Enfold/WordPress layout. A final
opt-in test smoke-extracts real S3 docs; it is skipped unless
LEVIATHAN_ICCO_SMOKE=1 (and boto3 + network are available).
"""
from __future__ import annotations

import json
import os

import pytest

from leviathan.transforms.raw_to_text.icco_qbcs import (
    extract_icco_qbcs,
    publication_date,
)

# ---------------------------------------------------------------------------
# Synthetic fixtures -- mirror the real div.entry-content layout, plus the
# out-of-band "Latest News" sidebar that links to FUTURE bulletins.
# ---------------------------------------------------------------------------

_QBCS_HTML = """\
<html><head><meta charset="UTF-8">
<title>August 2017 Quarterly Bulletin of Cocoa Statistics - ICCO</title></head>
<body>
  <nav class="avia-menu"><a href="/">Home</a><a href="/news/">News</a></nav>
  <article class="post-entry post-9233">
    <h1 class="entry-title">August 2017 Quarterly Bulletin of Cocoa Statistics</h1>
    <div class="entry-content">
      <p>Abidjan, 31 August 2017. The International Cocoa Organization today
      releases its revised forecasts for the current 2016/2017 cocoa year.</p>
      <p>Summary of revised forecasts and estimates</p>
      <table><tr><td>World production</td><td>4 700</td></tr>
      <tr><td>World grindings</td><td>4 282</td></tr></table>
      <p>Notes:</p>
      <p>a/ Estimates published in Quarterly Bulletin of Cocoa Statistics.</p>
      <p>This issue of the Bulletin contains the Secretariat's revised forecasts
      for the 2016/2017 cocoa year, including comments on crop and demand
      prospects in the leading countries for the current season.</p>
      <p>Copies of the Quarterly Bulletin of Cocoa Statistics can be ordered
      from the ICCO Secretariat at the address below:</p>
      <p>International Cocoa Organization, ICCO Building, Abidjan.
      E-mail: info@icco.org</p>
    </div>
  </article>
  <aside class="sidebar">
    <h3>Latest News</h3>
    <a href="/may-2026-qbcs/">May 2026 Quarterly Bulletin of Cocoa Statistics</a>
    <a href="/feb-2026-qbcs/">February 2026 Quarterly Bulletin of Cocoa Statistics</a>
  </aside>
</body></html>
"""

_EWG_HTML = """\
<html><head><meta charset="UTF-8">
<title>World cocoa bean stocks for the 2024/25 season - ICCO</title></head>
<body>
  <article class="post-entry">
    <h1 class="entry-title">World cocoa bean stocks for the 2024/25 season</h1>
    <div class="entry-content">
      <p>Abidjan, 22 January 2026. The ICCO Expert Working Group on Stocks
      (EWG-S) met today to review the level of world cocoa bean stocks.</p>
      <p>LOCATION OF THE ESTIMATED AND IDENTIFIED COCOA BEAN STOCKS</p>
      <table><tr><td>Total identified stocks</td><td>902</td></tr></table>
      <p>Notes:</p>
      <p>a/ Importing countries include Belgium, France, Germany.</p>
      <p>The EWG-S estimates an increase in stocks of between 70,000 and 90,000
      tonnes aggregated between Brazil, Japan, Turkey and South-East Asia.</p>
      <p>For more information, please contact Carlos Follana, ICCO.
      E-mail: Carlos.Follana@icco.org</p>
    </div>
  </article>
</body></html>
"""

_QBCS_KEY = (
    "raw/production/source=icco_qbcs_summary/"
    "release_date=2017-08-31/page.html"
)
_EWG_KEY = (
    "raw/production/source=icco_ewg_stocks/season=2024-25/page.html"
)


# ---------------------------------------------------------------------------
# extract_icco_qbcs -- schema
# ---------------------------------------------------------------------------

def test_schema_fields() -> None:
    doc = extract_icco_qbcs(_QBCS_HTML.encode("utf-8"), _QBCS_KEY, "icco_qbcs_summary")
    assert doc["source"] == "icco_qbcs_summary"
    assert doc["raw_key"] == _QBCS_KEY
    assert doc["extraction_method"] == "beautifulsoup"
    assert isinstance(doc["extracted_at"], str)
    assert len(doc["extracted_at"]) == 20  # YYYY-MM-DDTHH:MM:SSZ
    assert isinstance(doc["sections"], list)
    assert isinstance(doc["full_text"], str)
    assert len(doc["full_text"]) > 0
    # document.json round-trips as compact JSON (writer contract).
    json.dumps(doc, ensure_ascii=False)


def test_headline_section_first() -> None:
    doc = extract_icco_qbcs(_QBCS_HTML.encode("utf-8"), _QBCS_KEY, "icco_qbcs_summary")
    assert doc["sections"][0]["name"] == "headline"
    assert doc["sections"][0]["text"] == (
        "August 2017 Quarterly Bulletin of Cocoa Statistics"
    )
    assert doc["full_text"].startswith(
        "August 2017 Quarterly Bulletin of Cocoa Statistics"
    )


# ---------------------------------------------------------------------------
# extract_icco_qbcs -- section split
# ---------------------------------------------------------------------------

def test_qbcs_section_split() -> None:
    doc = extract_icco_qbcs(_QBCS_HTML.encode("utf-8"), _QBCS_KEY, "icco_qbcs_summary")
    names = [s["name"] for s in doc["sections"]]
    assert names == ["headline", "intro", "summary", "notes", "commentary"]

    by_name = {s["name"]: s["text"] for s in doc["sections"]}
    assert "today\n      releases" in by_name["intro"] or "today" in by_name["intro"]
    assert by_name["summary"].startswith("Summary of revised forecasts")
    assert "World production" in by_name["summary"]
    assert by_name["notes"].startswith("Notes")
    assert by_name["commentary"].startswith("This issue of the Bulletin")
    assert "demand\n      prospects" in by_name["commentary"] or "demand" in by_name["commentary"]


def test_ewg_section_split() -> None:
    doc = extract_icco_qbcs(_EWG_HTML.encode("utf-8"), _EWG_KEY, "icco_ewg_stocks")
    names = [s["name"] for s in doc["sections"]]
    assert names == ["headline", "intro", "summary", "notes", "commentary"]
    by_name = {s["name"]: s["text"] for s in doc["sections"]}
    assert by_name["summary"].startswith("LOCATION OF THE ESTIMATED")
    assert by_name["commentary"].startswith("The EWG-S estimates")


def test_fallback_single_summary_when_no_anchors() -> None:
    """A layout with no known anchor yields one 'summary' section (never [])."""
    html = (
        '<html><body><article><h1 class="entry-title">Cocoa Market Report</h1>'
        '<div class="entry-content"><p>Prices firmed on tight near-term supply '
        "as grinding demand held up through the quarter.</p></div>"
        "</article></body></html>"
    )
    doc = extract_icco_qbcs(html.encode("utf-8"), _QBCS_KEY, "icco_qbcs_summary")
    names = [s["name"] for s in doc["sections"]]
    assert names == ["headline", "summary"]
    assert "grinding demand" in doc["sections"][1]["text"]


# ---------------------------------------------------------------------------
# extract_icco_qbcs -- footer strip + PIT sidebar exclusion
# ---------------------------------------------------------------------------

def test_footer_contact_stripped() -> None:
    doc = extract_icco_qbcs(_QBCS_HTML.encode("utf-8"), _QBCS_KEY, "icco_qbcs_summary")
    assert "Copies of the Quarterly Bulletin" not in doc["full_text"]
    assert "info@icco.org" not in doc["full_text"]


def test_ewg_footer_contact_stripped_keeps_commentary() -> None:
    doc = extract_icco_qbcs(_EWG_HTML.encode("utf-8"), _EWG_KEY, "icco_ewg_stocks")
    assert "For more information" not in doc["full_text"]
    assert "Carlos.Follana@icco.org" not in doc["full_text"]
    # The substantive EWG estimate sentence (before the contact block) survives.
    assert "The EWG-S estimates an increase" in doc["full_text"]


def test_future_news_sidebar_excluded_pit() -> None:
    """The 'Latest News' sidebar links to FUTURE bulletins -- must not leak.

    A 2017 bulletin's page lists 2026 headlines; reading only entry-content
    keeps the PIT firewall intact at the text level.
    """
    doc = extract_icco_qbcs(_QBCS_HTML.encode("utf-8"), _QBCS_KEY, "icco_qbcs_summary")
    assert "2026" not in doc["full_text"]
    assert "Latest News" not in doc["full_text"]


def test_missing_container_yields_empty_doc() -> None:
    """No entry-content -> empty doc, never a full-page dump of site chrome."""
    html = (
        "<html><body><nav>Home News</nav>"
        '<aside><h3>Latest News</h3><a href="/x">May 2026 Bulletin</a></aside>'
        "</body></html>"
    )
    doc = extract_icco_qbcs(html.encode("utf-8"), _QBCS_KEY, "icco_qbcs_summary")
    assert doc["sections"] == []
    assert doc["full_text"] == ""


# ---------------------------------------------------------------------------
# publication_date -- PIT derivation
# ---------------------------------------------------------------------------

def test_publication_date_from_release_key() -> None:
    assert publication_date(_QBCS_KEY) == "2017-08-31"


def test_publication_date_release_key_beats_dateline() -> None:
    """When the key carries release_date, it wins even if a dateline exists."""
    body = "Abidjan, 01 January 2000. Something."
    assert publication_date(_QBCS_KEY, body) == "2017-08-31"


def test_publication_date_ewg_dateline_fallback() -> None:
    doc = extract_icco_qbcs(_EWG_HTML.encode("utf-8"), _EWG_KEY, "icco_ewg_stocks")
    assert publication_date(_EWG_KEY, doc["full_text"]) == "2026-01-22"


def test_publication_date_raises_without_source() -> None:
    with pytest.raises(ValueError):
        publication_date("raw/production/source=icco_ewg_stocks/season=2024-25/page.html")


# ---------------------------------------------------------------------------
# Opt-in real-doc smoke (offline by default)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("LEVIATHAN_ICCO_SMOKE") != "1",
    reason="set LEVIATHAN_ICCO_SMOKE=1 to smoke real S3 ICCO docs",
)
def test_real_doc_smoke() -> None:  # pragma: no cover - network/creds gated
    import boto3

    bucket = "leviathan-dev-shahem-001"
    s3 = boto3.client("s3")
    cases = [
        (
            "raw/production/source=icco_qbcs_summary/"
            "release_date=2008-02-28/page.html",
            "icco_qbcs_summary",
            "2008-02-28",
        ),
        (
            "raw/production/source=icco_qbcs_summary/"
            "release_date=2017-08-31/page.html",
            "icco_qbcs_summary",
            "2017-08-31",
        ),
        (
            "raw/production/source=icco_ewg_stocks/season=2024-25/page.html",
            "icco_ewg_stocks",
            "2026-01-22",
        ),
    ]
    for key, source, expected_date in cases:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        doc = extract_icco_qbcs(body, key, source)
        assert doc["extraction_method"] == "beautifulsoup"
        assert doc["source"] == source
        assert len(doc["full_text"]) > 500
        assert doc["sections"][0]["name"] == "headline"
        # Cocoa-domain content present.
        assert "cocoa" in doc["full_text"].lower()
        # No future-news leak past the bulletin's own year.
        assert "Latest News" not in doc["full_text"]
        assert publication_date(key, doc["full_text"]) == expected_date
