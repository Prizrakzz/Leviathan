#!/usr/bin/env python
"""PRICE_AND_PLAYBOOKS W1c / D2 -- the Euronext (MATIF) quote-table producer (raw landing only).

SOURCE
------
    https://live.euronext.com/en/product/commodities-futures/{PRODUCT}
        PRODUCT in {EBM-DPAR (milling wheat), EMA-DPAR (corn), ECO-DPAR (rapeseed)}

THE REQUEST RECIPE, AND WHY IT NEEDS A BROWSER WHEN THE PAGE DOES NOT
--------------------------------------------------------------------
Probed live 2026-07-29: there is **no WAF on this venue**. A plain-``requests`` GET of the product
page returns HTTP 200 and ~247 KB of HTML from BOTH a residential and a Fargate IP. The problem is
not access, it is that the payload does not contain the data: the quote table is CLIENT-RENDERED
out of an AES ``{ct,iv,s}`` blob, so ``table#future-prices-table`` exists only in a browser DOM.

So this producer drives headless Chromium, waits for the table to actually populate, and lands the
table's **outerHTML**. That makes the raw object a DOM SNAPSHOT rather than a wire response -- the
only such object in this estate -- and the ``raw_meta`` companion carries the true source URL so
the provenance survives the difference.

There is no API to prefer. The AES payload is decryptable only by the page's own JS, and rebuilding
that in Python would be a re-implementation of an undocumented client that the venue may rotate at
any time, with no error when it does. The DOM is the contract the venue actually supports.

THE PAGE CARRIES NO DATE, AND THAT SHAPES THE SCHEDULE
------------------------------------------------------
The table publishes a ``Time`` column (``18:31``) and nothing else temporal -- no session date
anywhere in the DOM. Unlike JSE (a header date inside the sheet) or CZCE (a date in the file's own
title line), there is nothing to cross-check the key against, so ``as_of_date`` IS the trade date.

Therefore the cadence is part of the CONTRACT, not a runbook preference: fire AFTER the ~18:30 CET
settlement publish and BEFORE local midnight. Firing early lands a pre-settlement table under a
date that claims it is a settlement; firing after midnight CET lands yesterday's session under
today's date. Neither is detectable downstream. The transform refuses a table where NOT ONE row
carries ``Settl.``, which catches the grossest form of the first mistake and nothing else.

A PARTIAL RENDER IS NOT A CAPTURE
---------------------------------
The table fills client-side, so "the tbody has rows" is a moment in a render rather than a fact
about the session. Both gates here therefore count TBODY rows against the product's own measured
expiry count (``EURONEXT_MIN_ROWS`` in the transform: EBM 12, EMA 10, ECO 10): the ready check WAITS
for the full curve instead of grabbing the first row that appears, and the capture sniff refuses to
land a short table. Without that, a three-of-twelve EBM lands, parses cleanly, and publishes as a
COMPLETE curve -- and the per-day silver floor cannot see it either, because a short EBM plus a full
EMA plus a full ECO still clears it.

IDEMPOTENCE
-----------
The raw key is deterministic per ``(product, as_of_date)`` and a product whose object already
exists is skipped WITHOUT a browser navigation (and, when every product is already landed, without
launching a browser at all). ``--force`` re-fetches.

THE EXIT-CODE CONTRACT (this run IS the residual S2 probe)
----------------------------------------------------------
``ChallengeFailed`` -- raised by ``BrowserSession.goto_and_settle`` when the page never reaches the
ready state within the budget -- exits with ``EXIT_CHALLENGE_FAILED`` (7) and one ASCII log line.
On THIS leg a 7 means "the DOM never produced the table" rather than "a WAF blocked us", because
there is no WAF here; either way it is the signal that the browser leg does not work from a
datacenter IP, and the first Fargate run of this job is what answers that question.

S3 LAYOUT
---------
    raw/production/source=euronext/product={PRODUCT}/as_of_date={YYYY-MM-DD}/table.html
    raw_meta/<that key>_meta.json      (sha256, size, the product page URL)

Usage
-----
    python jobs/ingest/fetch_euronext_eod.py
    python jobs/ingest/fetch_euronext_eod.py --product EBM-DPAR --as-of-date 2026-07-29
    python jobs/ingest/fetch_euronext_eod.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import (  # noqa: E402
    EURONEXT_TABLE_FILENAME,
    raw_euronext_key,
)
from leviathan.transforms.raw_to_bronze.euronext_eod import (  # noqa: E402
    EURONEXT_PRODUCT_MAP,
    EURONEXT_TABLE_ID,
    min_rows_for_product,
)

logger = get_logger("fetch_euronext_eod")

EURONEXT_BASE_URL = "https://live.euronext.com"
_PRODUCT_PATH_FMT = "/en/product/commodities-futures/{product}"
_SOURCE_LABEL = "euronext"
_CONTENT_TYPE = "text/html"

# Mirrored from leviathan.ingest.browser_fetch so this module's exit contract is readable without
# importing playwright. :func:`_browser` binds the two and FAILS if they ever drift -- a producer
# that exits 7 while the shared module means something else by 7 is worse than no code at all.
EXIT_CHALLENGE_FAILED = 7

# How long to wait for the client-side render before calling it a failure. The venue renders in
# ~5 s warm; 90 s is the shared default and is generous enough that a timeout means "broken", not
# "slow".
_DEFAULT_MAX_WAIT_S = 90

# A rendered table carries one row per listed expiry: 12 on EBM, 10 on EMA and ECO. Those counts
# are :data:`EURONEXT_MIN_ROWS`, pinned in the TRANSFORM beside the table id so the ready check, the
# capture sniff and the parse cannot disagree about what a complete table is.
#
# "at least one body row" is NOT that fact. The table is client-rendered, so one row is a moment in
# a render: the producer would stop waiting the instant the first expiry appeared, capture the
# half-filled tbody, and land a curve that parses cleanly and is simply MISSING months. Both gates
# below therefore count TBODY rows against the product's own measured expiry count -- not all
# ``<tr>`` (which silently includes the header row and turns a 4-row floor into a 3-row one).
#
# The counts themselves are NOT duplicated here: ``min_rows_for_product`` is imported, and a product
# added to the curated map without a count is an import-time assertion failure in the transform.

# The two page evaluations. Both go through the table id the TRANSFORM pins. ``_READY_JS`` is a
# TEMPLATE -- the row floor is per-product -- and :func:`_ready_js` fills it in.
_READY_JS = (
    "() => { const t = document.getElementById('%s');"
    " return !!t && t.querySelectorAll('tbody tr').length >= %%d; }" % EURONEXT_TABLE_ID
)
_OUTER_HTML_JS = (
    "() => { const t = document.getElementById('%s'); return t ? t.outerHTML : null; }"
    % EURONEXT_TABLE_ID
)

# The tbody slice and its rows, for the capture sniff. Anchored on the tag pair; ``<tr\b`` matches
# both ``<tr>`` and ``<tr data-...>`` and cannot match ``<track>`` or ``<trailer>``.
_TBODY_RE = re.compile(r"<tbody\b[^>]*>(.*?)</tbody>", re.IGNORECASE | re.DOTALL)
_TR_RE = re.compile(r"<tr\b", re.IGNORECASE)


def _browser():
    """The shared browser module, imported LAZILY.

    Lazy on purpose: playwright is a ``[batch]``/browser-image dependency, and the parser tests
    import this module to exercise the URL and sniff helpers on a laptop that has neither. The
    exit-code bind is asserted here rather than at import for the same reason."""
    from leviathan.ingest import browser_fetch

    if browser_fetch.EXIT_CHALLENGE_FAILED != EXIT_CHALLENGE_FAILED:
        raise RuntimeError(
            f"exit-code drift: browser_fetch.EXIT_CHALLENGE_FAILED is "
            f"{browser_fetch.EXIT_CHALLENGE_FAILED}, this producer mirrors {EXIT_CHALLENGE_FAILED}"
        )
    return browser_fetch


def product_path(product: str) -> str:
    """The product page path, e.g. ``/en/product/commodities-futures/EBM-DPAR``."""
    return _PRODUCT_PATH_FMT.format(product=str(product).strip().upper())


def product_url(product: str) -> str:
    """The absolute product page URL (recorded in raw_meta; the session navigates by path)."""
    return EURONEXT_BASE_URL + product_path(product)


def _ready_js(min_rows: int) -> str:
    """The ready-check JS for one product's row floor."""
    return _READY_JS % int(min_rows)


def table_is_rendered(product: str):
    """Build ``goto_and_settle``'s ready check for ONE product.

    Both halves matter, and the second is the one that had to change. The venue ships the empty
    ``<table>`` shell in the server HTML and fills the tbody from the decrypted payload, so "the
    element exists" is satisfied by a page that never received its data -- and "the tbody has a row"
    is satisfied by a page that is still receiving it. The check waits for the product's full
    measured expiry count, so a partially rendered table is a WAIT rather than a capture."""
    js = _ready_js(min_rows_for_product(product))

    def _check(page) -> bool:
        try:
            return bool(page.evaluate(js))
        except Exception:  # noqa: BLE001 -- a mid-navigation evaluate throws; that is "not yet"
            return False

    return _check


def table_outer_html(session) -> Optional[str]:
    """The rendered table's outerHTML via the session's page escape hatch, or None."""
    return session.page.evaluate(_OUTER_HTML_JS)


def tbody_rows(html: str) -> int:
    """How many ``<tr>`` the captured table's TBODY carries.

    Anchored on the tbody deliberately: counting every ``<tr>`` in the outerHTML includes the header
    row, so a "4 rows" floor is really a 3-row floor and a table that rendered three of twelve
    expiries passes it. Regex rather than BeautifulSoup because this is a SHAPE sniff and all
    parsing authority stays in the transform."""
    m = _TBODY_RE.search(html)
    return len(_TR_RE.findall(m.group(1))) if m else 0


def looks_like_a_quote_table(html: Optional[str], product: str) -> Optional[str]:
    """None if the captured HTML is a plausible rendered quote table, else the reason it is not.

    Structural only -- a body-row count and the presence of the header words -- and never a parse:
    all parsing authority stays in the transform so raw and bronze cannot disagree about what the
    page said. The transform's ``thead`` pin and its own completeness floor are the real checks and
    they run on the landed bytes; this one exists so a truncated capture is never LANDED, on a leg
    whose page publishes today's quotes and nothing earlier."""
    if not html:
        return f"{product}: the page produced no table#{EURONEXT_TABLE_ID} element at all"
    rows = tbody_rows(html)
    floor = min_rows_for_product(product)
    if rows < floor:
        return (f"{product}: the captured table has {rows} tbody <tr> element(s), expected >= "
                f"{floor} -- the tbody never finished populating, or the venue truncated the "
                f"curve. Landing it would publish a SHORT curve that parses cleanly")
    if "Settl" not in html:
        return (f"{product}: the captured table carries no 'Settl' header -- settlement is the "
                f"price of record on this leg and a table without it is not the quote table")
    return None


def land_bytes(bucket: str, key: str, data: bytes, *, source_url: str, region: str) -> None:
    """Upload one raw artifact + its ``write_raw_s3_metadata`` companion, after the size floor.

    The house raw-landing convention, copied from ``fetch_czce_eod.land_bytes``. NOTE that
    ``check_min_file_size`` returns SILENTLY when the source key is absent from
    ``MIN_RAW_FILE_SIZES`` -- a missing entry is a DISABLED floor, not an error -- so
    ``constants.MIN_RAW_FILE_SIZES['euronext']`` is part of this producer, not decoration."""
    from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
    from leviathan.storage.s3 import upload_bytes_to_s3

    check_min_file_size(data, _SOURCE_LABEL, context=key)
    upload_bytes_to_s3(data, bucket, key, region)
    write_raw_s3_metadata(bucket, key, data, source_url, _CONTENT_TYPE, region)
    logger.info("raw written -> s3://%s/%s (%d bytes)", bucket, key, len(data))


def raw_exists(bucket: str, key: str, region: str) -> bool:
    from leviathan.storage.s3 import get_thread_local_s3_client
    try:
        get_thread_local_s3_client(region).head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001 -- any head failure means "treat as absent"
        return False


def resolve_products(requested: Optional[list[str]]) -> list[str]:
    """The products to capture, validated against the curated map. Default: all three."""
    if not requested:
        return sorted(EURONEXT_PRODUCT_MAP)
    out: list[str] = []
    for token in requested:
        product = str(token).strip().upper()
        if product not in EURONEXT_PRODUCT_MAP:
            raise SystemExit(f"--product {token!r} is not one of {sorted(EURONEXT_PRODUCT_MAP)}")
        if product not in out:
            out.append(product)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    ap = argparse.ArgumentParser(
        description="Euronext/MATIF rendered quote tables -> raw S3 (W1c browser leg)")
    ap.add_argument("--product", action="append", dest="products", default=None,
                    help=f"repeatable; default all of {sorted(EURONEXT_PRODUCT_MAP)}")
    ap.add_argument("--as-of-date", "--as-of", default=None, dest="as_of",
                    help="the capture date used in the raw key AND as the trade date (default: "
                         "today, UTC). This page publishes no date of its own")
    # The flag SPELLINGS are the same across the three W1c producers on purpose: an operator or a
    # scheduler copying an invocation between dce/euronext/bursa must not get an argparse error, and
    # --force must mean the same thing in all three (it CLEARS skip-existing; it is not a second,
    # independent switch that has to be ANDed with it).
    ap.add_argument("--skip-existing", action="store_true", default=True, dest="skip_existing",
                    help="(the default) skip a product whose raw object for --as-of-date already "
                         "exists; --force overrides")
    ap.add_argument("--force", dest="skip_existing", action="store_false",
                    help="re-fetch and overwrite an already-landed capture")
    ap.add_argument("--headless", action="store_true", default=True, dest="headless",
                    help="(the default) run Chromium headless -- the mode probe S1 validated")
    ap.add_argument("--headful", "--headed", action="store_false", dest="headless",
                    help="local debugging only; NEVER on Fargate")
    ap.add_argument("--max-wait-s", type=int, default=_DEFAULT_MAX_WAIT_S, dest="max_wait_s",
                    help="seconds to wait for the client-side render before ChallengeFailed")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the URLs and keys; no browser, no writes")
    args = ap.parse_args(argv)

    products = resolve_products(args.products)
    as_of = args.as_of or datetime.now(tz=timezone.utc).date().isoformat()

    if args.dry_run:
        print(f"as_of    : {as_of}")
        print(f"products : {', '.join(products)}")
        for product in products:
            print(f"  {product}: {product_url(product)} "
                  f"(expects >= {min_rows_for_product(product)} expiries)")
            print(f"    -> {raw_euronext_key(product, as_of)}")
        print("(dry-run -- no browser, no writes)")
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    # Decide what is actually owed BEFORE launching a browser: on a re-run every product is already
    # landed and Chromium never has to start.
    todo: list[tuple[str, str]] = []
    skipped_existing = 0
    for product in products:
        key = raw_euronext_key(product, as_of, EURONEXT_TABLE_FILENAME)
        if args.skip_existing and raw_exists(bucket, key, aws_region):
            skipped_existing += 1
            continue
        todo.append((product, key))
    if not todo:
        logger.info("euronext %s: all %d product(s) already landed -- nothing to fetch "
                    "(use --force to re-capture)", as_of, skipped_existing)
        return 0

    bf = _browser()
    landed = 0
    failures: list[str] = []
    try:
        # ONE session for the venue, all products inside it. Euronext presents no challenge, so a
        # fresh context per product would buy nothing and cost a browser launch each time.
        with bf.BrowserSession(EURONEXT_BASE_URL, headless=args.headless) as session:
            for product, key in todo:
                try:
                    session.goto_and_settle(product_path(product),
                                            ready_check=table_is_rendered(product),
                                            max_wait_s=args.max_wait_s)
                    html = table_outer_html(session)
                    bad = looks_like_a_quote_table(html, product)
                    if bad:
                        raise ValueError(bad)
                    land_bytes(bucket, key, html.encode("utf-8"),
                               source_url=product_url(product), region=aws_region)
                    landed += 1
                except bf.ChallengeFailed:
                    raise
                except Exception as exc:  # noqa: BLE001 -- one product must not abort the others
                    logger.exception("FAILED euronext product %s", product)
                    failures.append(f"{product}: {type(exc).__name__}")
    except bf.ChallengeFailed as exc:
        # THE RESIDUAL S2 PROBE. One ASCII line, one dedicated exit code -- the first Fargate run of
        # this job is what tells us whether the browser leg works from a datacenter IP.
        logger.error("CHALLENGE_FAILED euronext: the quote table never rendered within %ds (%s)",
                     args.max_wait_s, type(exc).__name__)
        return EXIT_CHALLENGE_FAILED

    logger.info("euronext %s done: landed=%d skipped_existing=%d failed=%d",
                as_of, landed, skipped_existing, len(failures))
    if failures:
        logger.error("failed product(s): %s", ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
