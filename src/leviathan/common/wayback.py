"""Wayback replay: PIN a capture from the CDX index, then VERIFY the capture SERVED.

THE ESTATE LAW THIS MODULE EXISTS TO ENFORCE
--------------------------------------------
A wayback timestamp is a REQUEST, not a guarantee.  ``/web/{ts}id_/{url}`` does NOT 404 when
``ts`` has no capture -- it silently 200s with the NEAREST capture, and those bytes then wear
the requested timestamp in the raw key forever.

The law was banked the expensive way (2026-07-29, W1a/CEPEA): the first cut of
``fetch_cepea_wayback_history`` asked for two 2025 timestamps that do not exist in the CDX
index; Wayback served the 2017 captures; they landed under 2025-shaped keys and the docstring
claimed thirteen months of coverage over what was actually a nine-year hole.  Row counts looked
plausible, so nothing tripped.

Hence the two-step contract every wayback-sourced leg in this estate must follow:

  1. PIN from the CDX index -- ``timestamp`` (and, where available, ``digest``) of a capture
     that provably EXISTS.  Never a wished-for date.
  2. VERIFY the SERVED capture off the response itself and REFUSE to land bytes whose served
     capture is not the pinned one.

``served_capture_ts`` reads the capture Wayback actually served off the final URL and
cross-checks it against ``Memento-Datetime``; ``capture_drift`` turns the pinned-vs-served
comparison into a refusal reason.  Both are duck-typed on the response (``.url`` +
``.headers.get``), so they work with ``requests`` and with a test double alike, and neither
touches the network.

PROVENANCE OF THIS CODE.  ``jobs/ingest/fetch_cepea_wayback_history.py`` carries the original,
CEPEA-shaped implementation (``served_capture_ts`` / ``wrong_capture``, pinned by
``tests/unit/test_cepea_eod.py``).  This module is that logic lifted out source-shape-for-
source-shape so a second wayback-sourced leg -- ``jobs/ingest/backfill_unica_wayback.py`` --
does not have to re-derive the law from the incident report.  Migrating the CEPEA leg onto this
module is a deliberate follow-up, NOT done here: it is a shipped, test-pinned one-shot and this
wave has no business editing it.
"""
from __future__ import annotations

import re
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

# The ``id_`` suffix asks Wayback for the ORIGINAL bytes without its rewriting banner --
# mandatory whenever the artifact is a binary (PDF, workbook) rather than a page.
REPLAY_FMT = "https://web.archive.org/web/{ts}id_/{target}"

_CAPTURE_IN_URL_RE = re.compile(r"/web/(\d{14})(?:id_)?/")


def replay_url(ts: str, target: str) -> str:
    """The raw-bytes replay URL for capture *ts* of *target*."""
    return REPLAY_FMT.format(ts=str(ts), target=target)


def served_capture_ts(resp: Any) -> Optional[str]:
    """The capture Wayback ACTUALLY served, or ``None`` if the response does not say.

    Wayback redirects an unmatched timestamp to the nearest capture, so the served timestamp
    lives in the FINAL url (``/web/{ts}id_/``).  ``Memento-Datetime`` carries the same instant
    in RFC-1123 and is used as a cross-check.

    Raises:
        ValueError: when the URL and ``Memento-Datetime`` name DIFFERENT captures -- a response
            that disagrees with itself cannot establish provenance at all.
    """
    served: Optional[str] = None
    match = _CAPTURE_IN_URL_RE.search(getattr(resp, "url", "") or "")
    if match:
        served = match.group(1)

    headers = getattr(resp, "headers", None) or {}
    memento = headers.get("Memento-Datetime")
    if memento:
        try:
            stamp = (
                parsedate_to_datetime(memento)
                .astimezone(timezone.utc)
                .strftime("%Y%m%d%H%M%S")
            )
        except (TypeError, ValueError):
            stamp = None
        if stamp and served and stamp != served:
            raise ValueError(
                f"wayback disagrees with itself: URL says capture {served}, "
                f"Memento-Datetime says {stamp}"
            )
        served = served or stamp
    return served


def capture_drift(
    pinned: str,
    served: Optional[str],
    *,
    what: str = "these bytes",
) -> Optional[str]:
    """``None`` when the served capture IS the pinned one, else why *what* must not be landed.

    This is the guard whose absence cost CEPEA nine years.  An unmatched timestamp does not
    404 -- it 200s with the nearest capture.
    """
    if served is None:
        return (
            "the response carries neither a capture timestamp in its URL nor a "
            "Memento-Datetime header, so the capture it came from cannot be established"
        )
    if str(served) != str(pinned):
        return (
            f"wayback served capture {served}, not the pinned {pinned} -- an unmatched "
            f"timestamp silently redirects to the NEAREST capture, so {what} are some other "
            f"day's bytes. Re-pin from the CDX index rather than landing them under the "
            f"wrong provenance"
        )
    return None
