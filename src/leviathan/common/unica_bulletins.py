"""UNICA bi-weekly bulletin identity: the publication-month season rule + the mislabel quarantine.

This module is the single definition of record for two things that three separate layers of the
unica chain (fetch, wayback backfill, bronze) each used to answer for themselves:

  1. WHICH SEASON A BULLETIN BELONGS TO.  The rule is the publication month, never the caller's
     loop variable and never the S3 key it happens to be sitting under.
  2. WHICH BULLETINS CARRY A KNOWN-WRONG SEASON LABEL, and what the right one is.

--------------------------------------------------------------------------------------------
THE FULL STORY OF idm=32820684 -- the one mislabelled bulletin that poisoned the whole chain
--------------------------------------------------------------------------------------------
The UNICADATA portal serves exactly ONE bulletin at a time and keeps no archive.  On the
2026-08-12 scheduled fire the biweekly leg logged "Discovery found no new bulletins" and
"Downloading 0 bulletin(s)" and exited 0, while silver content sat frozen at fortnight
2026-02-01.  RCA (D-SG G2-1(a-iii)) traced all of it to a single row:

    configs/sources/unica_biweekly_manifest.yaml
        harvest_year: "2025/2026"   idm: "32820684"   published_ym: "2026/04"

A bulletin published 2026/04 is the FIRST fortnight of season 2026/2027 by this project's own
rule (April opens the crush).  It wore "2025/2026" because
``fetch_unica_biweekly._extract_current_bulletin(page, year)`` applied the publication-month
inference ONLY when the caller passed ``year=None`` -- a caller-supplied loop year silently
overrode the evidence.  The consequences ran every Wednesday, in this order:

    1. ``existing_idms`` contained 32820684, so the ONE bulletin the portal displays was
       reported "already known"                       -> "Discovery found no new bulletins."
    2. the season-scoped download filter kept only rows whose harvest_year was in
       ["2026/2027"]; the manifest held ZERO such rows -> "Downloading 0 bulletin(s)".
    3. ``_exit_reason(0, 0, 0, 0)`` returned None      -> exit 0, green, forever.

And a data-correctness rider on top of the no-op: the April-2026 bulletin physically landed at
``raw/production/source=unica_biweekly/harvest_year=2025_2026/idm=32820684/report.pdf`` and the
silver transform resolved its "DD/04" fortnight labels against harvest_year 2025_2026, i.e. to
April 2025 -- folding a 2026/2027 bulletin into the 2025/2026 season.

WHAT IS ALREADY FIXED, AND WHAT THIS MAP STILL CARRIES.  The manifest row was relabelled to
"2026/2027" and ``_extract_current_bulletin`` now lets the published month beat the loop year,
so the FETCH layer no longer mints the mislabel.  What remains is the object already on disk:
the raw PDF still sits under ``harvest_year=2025_2026`` and moving it is owner decision D22,
not an ingest-code decision.  Bronze derives harvest_year from that hive key, so without a
relabel it would keep re-minting the wrong season downstream from the wrong path.

``SEASON_RELABELS`` is therefore a QUARANTINE MAP, not a workaround: it names the bulletins
whose recorded label is known-wrong, records the label they were written under so a relabel is
auditable, and states the evidence (the published month) that settles it.  Both the fetch layer
(manifest rows) and the bronze layer (hive keys) consult it, so the correction cannot be
applied in one place and forgotten in the other.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from leviathan.common.dates import current_harvest_season

# ---------------------------------------------------------------------------
# Payload floors (shared with jobs/ingest/fetch_unica_biweekly.py, which aliases these)
# ---------------------------------------------------------------------------

PDF_MAGIC = b"%PDF"
# Real bulletins are ~2.8 MB; the CMS and Wayback both signal a pruned bulletin with a 200 and
# a small placeholder, so the size floor is the real presence test.
MIN_PDF_BYTES = 50_000

# ---------------------------------------------------------------------------
# PDF URL parsing -- unicadata PDFs live at /arquivos/pdfs/YYYY/MM/{hash}.pdf
# ---------------------------------------------------------------------------

PDF_URL_RE = re.compile(r"/arquivos/pdfs/(\d{4})/(\d{2})/([0-9a-f]{16,})\.pdf", re.IGNORECASE)


def season_for_publication(pub_year: int, pub_month: int) -> str:
    """Season label ``YYYY/YYYY+1`` for a bulletin PUBLISHED in *pub_year*/*pub_month*.

    April..December publish the season that opened that April; January..March publish the
    closing bulletins of the season that opened the PRIOR April.  Delegates to
    ``leviathan.common.dates.current_harvest_season`` so the publication rule and the as-of rule
    can never drift apart -- they are arithmetically the same rule read from two different
    clocks.
    """
    return current_harvest_season(date(int(pub_year), int(pub_month), 1))


def idm_for_pdf_hash(pdf_hash: str) -> str:
    """The manifest/S3 ``idm`` for a bulletin known only by its PDF content hash."""
    return f"pdf_{pdf_hash}"


def parse_pdf_url(url: str) -> Optional[dict[str, Any]]:
    """Parse a unicadata bulletin PDF URL into its identity fields, or ``None`` if it is not one.

    Returns keys: ``pub_year``, ``pub_month``, ``pdf_hash``, ``published_ym`` (``YYYY/MM``),
    ``harvest_year`` (from the PUBLICATION month) and ``idm``.
    """
    match = PDF_URL_RE.search(url or "")
    if not match:
        return None
    pub_year, pub_month, pdf_hash = int(match.group(1)), int(match.group(2)), match.group(3)
    return {
        "pub_year": pub_year,
        "pub_month": pub_month,
        "pdf_hash": pdf_hash,
        "published_ym": f"{pub_year:04d}/{pub_month:02d}",
        "harvest_year": season_for_publication(pub_year, pub_month),
        "idm": idm_for_pdf_hash(pdf_hash),
    }


# ---------------------------------------------------------------------------
# The quarantine map (full story in the module docstring)
# ---------------------------------------------------------------------------

SEASON_RELABELS: dict[str, dict[str, str]] = {
    # Published 2026/04 -> the FIRST fortnight of 2026/2027, mislabelled 2025/2026 by the
    # loop-year-beats-evidence bug in _extract_current_bulletin.  The manifest row is already
    # corrected; the raw S3 object is NOT moved (owner decision D22), so the hive key still
    # says 2025_2026 and bronze must relabel on read.
    "32820684": {
        "labelled": "2025/2026",
        "correct": "2026/2027",
        "evidence": "published_ym=2026/04 (April opens the 2026/2027 crush)",
    },
}


def _match_shape(season: str, like: str) -> str:
    """Return *season* in the same separator shape as *like* (``YYYY/YYYY`` vs ``YYYY_YYYY``)."""
    return season.replace("/", "_") if "_" in (like or "") else season


def is_relabelled(idm: Optional[str]) -> bool:
    """True when *idm* carries a known-wrong season label."""
    return str(idm) in SEASON_RELABELS if idm is not None else False


def corrected_season(idm: Optional[str], labelled_season: Optional[str]) -> Optional[str]:
    """The season *idm* ACTUALLY belongs to, given the season it is currently *labelled* with.

    Format-preserving: an underscore-shaped hive value (``2025_2026``) comes back underscore
    shaped, a slash-shaped manifest value comes back slash shaped.  Unmapped bulletins are
    returned untouched, so this is safe to call unconditionally on every row.
    """
    fix = SEASON_RELABELS.get(str(idm)) if idm is not None else None
    if fix is None:
        return labelled_season
    return _match_shape(fix["correct"], labelled_season or "")


def relabel_reason(idm: Optional[str], labelled_season: Optional[str]) -> Optional[str]:
    """A one-line audit string when a relabel applies to *idm*, else ``None``."""
    fix = SEASON_RELABELS.get(str(idm)) if idm is not None else None
    if fix is None:
        return None
    corrected = corrected_season(idm, labelled_season)
    if str(labelled_season) == str(corrected):
        return None
    return (
        f"QUARANTINE RELABEL idm={idm}: {labelled_season} -> {corrected} "
        f"({fix['evidence']}; D-SG G2-1(a-iii))"
    )
