"""PRICE_AND_PLAYBOOKS W1c -- the shared headless-browser runtime for the three challenged venues.

WHAT THIS MODULE OWNS
---------------------
One synchronous Playwright/Chromium session, and the four operations the W1c producers need on top
of it:

  * :meth:`BrowserSession.goto_and_settle` -- navigate, then WAIT for the venue's JS challenge to
    settle, decided by a caller-supplied ``ready_check(page)`` rather than by a sleep;
  * :meth:`BrowserSession.fetch_json` / :meth:`BrowserSession.fetch_text` -- an IN-PAGE
    ``window.fetch``, so the request carries the session cookies the challenge just minted and the
    venue sees a same-origin XHR from a real browser context;
  * :meth:`BrowserSession.download` -- inject an ``<a href download>`` and click it, so a
    ``content-disposition: attachment`` URL lands as BYTES rather than as a navigation;
  * :attr:`BrowserSession.page` -- the escape hatch, for the one leg (Euronext) whose payload is a
    rendered DOM table and not an API response.

Three venues, three different reasons this exists (all probed live 2026-07-29, see
``tests/fixtures/w1c/capture_notes.md``): DCE answers 412 to plain ``requests`` from BOTH residential
and datacenter IPs (Ruishu WAF); Bursa answers 403 + ``Cf-Mitigated: challenge`` everywhere
(Cloudflare); Euronext has no WAF at all but renders its quote table client-side, so the numbers
exist only in a DOM. All three CLEAR in headless Chromium.

THE EXIT-CODE CONTRACT IS THE PROBE
-----------------------------------
S1 (does the challenge clear in headless?) is answered: yes, from a residential IP. S2 (does it
clear from a DATACENTER IP?) is NOT answered and cannot be answered from this laptop. So the design
decision is to make the first Fargate run BE the S2 probe: a challenge that never settles raises
:class:`ChallengeFailed`, every producer catches it and exits :data:`EXIT_CHALLENGE_FAILED` (7), and
that one exit code separates "the venue refused this IP class" from every other failure mode
(rc 1 = a real error, rc 5 = the DCE not-ready guard). Nobody has to read a traceback to learn the
answer, and no retry storm is spent discovering it.

Which is why a page that could not be REACHED raises :class:`NavigationFailed` (rc 1) and not
ChallengeFailed. A Fargate egress or DNS problem exiting 7 would be read -- by a human skimming
CloudWatch, and by any metric filter on the exit code -- as a negative answer to the very question
the run exists to answer. A broken route is not evidence about a WAF.

WHY SYNC AND NOT ASYNC
----------------------
``fetch_unica_biweekly.py`` drives ``async_playwright`` because its discovery walk is a long
interactive sequence. These three producers are "settle once, then pull N artifacts", which is
straight-line code; the sync API keeps the producers readable and keeps the retry/landing idioms
identical to the plain-``requests`` W1a legs (``fetch_czce_eod.py``, ``fetch_jse_safex_daily.py``).

THE IMPORT IS LAZY, AND THAT IS LOAD-BEARING
--------------------------------------------
``playwright`` is a ``[biweekly]`` extra, absent from the laptop and from the default worker image.
It is imported INSIDE :meth:`BrowserSession.__enter__`, never at module scope, so:

  * the parser tests import the producers without installing a browser (W1c tests are
    fixture-level by design -- no browser is ever launched in CI);
  * a missing playwright fails at the one place that actually needs it, naming the image.

EVERY LOG LINE IS ASCII
-----------------------
The Windows console is cp1252 and a non-ASCII ``print`` CRASHES python. Chromium error text and
venue page content are routinely Chinese/French, so anything that could carry venue text goes
through :func:`ascii_safe` before it reaches a log record.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# The residual-S2 exit code. Reserved across every W1c producer: a process that exits 7 is saying
# "the venue's challenge did not settle for this IP class", and nothing else.
EXIT_CHALLENGE_FAILED = 7


class ChallengeFailed(RuntimeError):
    """The venue's JS challenge never SETTLED within the budget.

    NOT a parse error, NOT an empty session, NOT a 404, and -- since the navigation split below --
    NOT a network failure either. Producers translate it into :data:`EXIT_CHALLENGE_FAILED` and
    nothing else does, which is what makes rc 7 a clean answer to the residual S2 question."""


class NavigationFailed(RuntimeError):
    """The page could not be REACHED at all: DNS, egress, TLS, or three chrome-error landings.

    Deliberately NOT a :class:`ChallengeFailed` subclass. Both used to raise ChallengeFailed, so a
    Fargate networking or egress problem on the first run exited 7 -- and rc 7 is read as "the venue
    refused this IP class", i.e. a NEGATIVE answer to the exact residual-S2 question that run exists
    to answer. A broken egress route is not evidence about the WAF. This falls through to rc 1 (a
    real failure, retryable) via :func:`navigation_failed_exit`."""


# Chromium in a container: no user namespaces and a 64 MB /dev/shm by default. Both flags are
# required on Fargate and harmless on a laptop.
_LAUNCH_ARGS = ("--no-sandbox", "--disable-dev-shm-usage")

_DEFAULT_NAV_TIMEOUT_S = 45
_DEFAULT_MAX_WAIT_S = 90
# Chromium renders its own error document at this scheme when a navigation fails at the network
# layer. It is a 200-less "success" as far as page.goto is concerned on some failure classes, so the
# URL is checked explicitly rather than trusting the absence of an exception.
_CHROME_ERROR_SCHEME = "chrome-error://"
_NAV_ATTEMPTS = 3
_NAV_BACKOFF_S = 4
# The challenge dance measured ~5-10s on DCE and ~4-6s on Bursa. Polling every 4s costs at most one
# wasted probe and keeps the loop cheap; the wait is bounded by max_wait_s, never by the poll count.
_SETTLE_POLL_S = 4.0
_DOWNLOAD_TIMEOUT_FLOOR_MS = 120_000

# One in-page GET. `credentials: 'include'` is explicit rather than relying on the same-origin
# default: the whole point of fetching from inside the page is that the challenge cookie rides along.
_FETCH_JS = """
async (args) => {
  const opts = {credentials: 'include', headers: {}};
  if (args.accept) { opts.headers['Accept'] = args.accept; }
  const r = await fetch(args.url, opts);
  const body = await r.text();
  return {status: r.status, url: r.url, body: body};
}
"""

# An anchor with a `download` attribute, clicked. A plain page.goto on an attachment URL is a
# navigation Chromium may or may not turn into a download depending on the response headers; this
# always produces a Download object, which is what expect_download waits on.
_DOWNLOAD_JS = """
(url) => {
  const a = document.createElement('a');
  a.href = url;
  a.setAttribute('download', '');
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  a.remove();
}
"""


def ascii_safe(value: Any, limit: int = 400) -> str:
    """``value`` rendered as pure ASCII, escaped and truncated -- safe for a cp1252 console.

    Venue text (Chinese contract names, French product labels) reaches this module through Chromium
    error messages and response bodies; a log record carrying it crashes the Windows console."""
    text = str(value)
    if len(text) > limit:
        text = text[:limit] + "..."
    return text.encode("ascii", "backslashreplace").decode("ascii")


class BrowserSession:
    """One headless Chromium context, bound to ``base_url``.

    Use as a context manager -- teardown runs on EVERY exit path, including an exception, because a
    leaked Chromium process on Fargate holds the task's memory until the task itself is reaped::

        with BrowserSession("http://www.dce.com.cn") as sess:
            sess.goto_and_settle("/", ready_check=_quote_api_answers)
            payload = sess.fetch_text("/dcereport/quote/delay/futureData?variety=p")
    """

    def __init__(self, base_url: str, *, headless: bool = True,
                 nav_timeout_s: int = _DEFAULT_NAV_TIMEOUT_S,
                 user_agent: Optional[str] = None) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.headless = bool(headless)
        self.nav_timeout_ms = int(nav_timeout_s * 1000)
        self.user_agent = user_agent
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    # -- lifecycle ----------------------------------------------------------
    def __enter__(self) -> "BrowserSession":
        # LAZY. playwright is a [biweekly] extra and absent from the parser-test environment by
        # design -- see the module docstring.
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is not installed -- this producer needs the BROWSER image "
                "(docker/leviathan_browser), not the worker image. "
                "pip install 'leviathan[biweekly]' && playwright install --with-deps chromium"
            ) from exc
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(headless=self.headless,
                                                     args=list(_LAUNCH_ARGS))
            ctx_kwargs: dict = {"accept_downloads": True}
            if self.user_agent:
                ctx_kwargs["user_agent"] = self.user_agent
            self._context = self._browser.new_context(**ctx_kwargs)
            self._context.set_default_timeout(self.nav_timeout_ms)
            self._context.set_default_navigation_timeout(self.nav_timeout_ms)
            self._page = self._context.new_page()
        except Exception:
            self.close()
            raise
        logger.info("browser session up: %s (headless=%s)", self.base_url, self.headless)
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        """Tear down page -> context -> browser -> driver. Never raises."""
        for name in ("_page", "_context", "_browser"):
            obj = getattr(self, name, None)
            if obj is None:
                continue
            try:
                obj.close()
            except Exception as err:  # noqa: BLE001 -- teardown must not mask the real failure
                logger.debug("browser teardown: %s.close() failed: %s", name, ascii_safe(err))
            setattr(self, name, None)
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception as err:  # noqa: BLE001
                logger.debug("browser teardown: playwright.stop() failed: %s", ascii_safe(err))
            self._pw = None

    @property
    def page(self):
        """The live page. The escape hatch for DOM scraping (Euronext reads a rendered table)."""
        if self._page is None:
            raise RuntimeError("BrowserSession is not open -- use it as a context manager "
                               "(`with BrowserSession(url) as sess:`)")
        return self._page

    # -- urls ---------------------------------------------------------------
    def url_for(self, path: str) -> str:
        """``'/a/b'`` -> ``base_url + '/a/b'``; an absolute URL is returned unchanged."""
        p = str(path)
        if p.startswith("http://") or p.startswith("https://"):
            return p
        return self.base_url + (p if p.startswith("/") else "/" + p)

    # -- navigation ---------------------------------------------------------
    def goto_and_settle(self, url: str, *, ready_check: Callable[[Any], bool],
                        max_wait_s: int = _DEFAULT_MAX_WAIT_S) -> None:
        """Navigate to ``url`` and block until ``ready_check(page)`` is true.

        Two phases, deliberately separate:

        1. NAVIGATION, retried up to three times on a transient failure -- a network-layer error, a
           timeout, or a landing on ``chrome-error://``. The challenge itself is NOT a navigation
           failure (the WAF answers 200 with a JS document), so it never lands here.
        2. SETTLE. The challenge redirects the page one or more times and only then serves content,
           and how long that takes is a property of the venue and the IP, not of this code. So the
           readiness question is delegated: ``ready_check(page)`` is polled every ~4s until it
           answers true. A ready_check that RAISES counts as "not ready yet" -- while the WAF is up,
           an in-page probe fetch legitimately throws -- so probes stay simple and need no try/except
           of their own.

        The wait uses ``page.wait_for_timeout`` rather than ``time.sleep``: the challenge's own
        JavaScript has to run in the page for the session cookie to be minted, and a blocking sleep
        in the driver does not pump it.

        The two phases raise two DIFFERENT exceptions, and that separation is the point:
        :class:`NavigationFailed` when the page could not be reached at all (rc 1 -- a network or
        egress problem, which says nothing about the WAF), :class:`ChallengeFailed` when
        ``max_wait_s`` elapses with the probe still false (rc 7 -- the venue refused this session).
        Only the second one is the S2 answer; see the module docstring."""
        target = self.url_for(url)
        page = self.page
        last_error: Optional[BaseException] = None
        for attempt in range(1, _NAV_ATTEMPTS + 1):
            last_error = None
            try:
                page.goto(target, wait_until="domcontentloaded", timeout=self.nav_timeout_ms)
            except Exception as exc:  # noqa: BLE001 -- playwright.Error, without importing it
                last_error = exc
                logger.warning("nav %s failed (attempt %d/%d): %s", target, attempt,
                               _NAV_ATTEMPTS, ascii_safe(exc))
            else:
                if not str(page.url).startswith(_CHROME_ERROR_SCHEME):
                    break
                last_error = RuntimeError(f"navigation landed on {ascii_safe(page.url)}")
                logger.warning("nav %s landed on a chrome error page (attempt %d/%d)",
                               target, attempt, _NAV_ATTEMPTS)
            if attempt < _NAV_ATTEMPTS:
                time.sleep(_NAV_BACKOFF_S * attempt)
        if last_error is not None:
            raise NavigationFailed(
                f"{target}: navigation did not complete in {_NAV_ATTEMPTS} attempt(s) -- "
                f"{ascii_safe(last_error)}")

        started = time.monotonic()
        deadline = started + max(1, int(max_wait_s))
        checks = 0
        while True:
            checks += 1
            try:
                if ready_check(page):
                    logger.info("settled %s after %d check(s) in %.1fs", target, checks,
                                time.monotonic() - started)
                    return
            except Exception as exc:  # noqa: BLE001 -- a raising probe means "not ready yet"
                logger.debug("ready_check %d for %s not satisfied: %s", checks, target,
                             ascii_safe(exc))
            if time.monotonic() >= deadline:
                break
            page.wait_for_timeout(int(_SETTLE_POLL_S * 1000))
        raise ChallengeFailed(
            f"{target}: the challenge did not settle within {max_wait_s}s ({checks} probe(s)) -- "
            f"the venue is refusing this session")

    # -- payloads -----------------------------------------------------------
    def fetch_text(self, path: str, *, accept: Optional[str] = None) -> str:
        """One in-page ``window.fetch`` GET; the response body as text. Non-200 raises."""
        target = self.url_for(path)
        result = self.page.evaluate(_FETCH_JS, {"url": target, "accept": accept})
        status = int((result or {}).get("status") or 0)
        body = (result or {}).get("body") or ""
        if status != 200:
            raise RuntimeError(
                f"in-page GET {target} returned HTTP {status} ({len(body)} byte(s) of body): "
                f"{ascii_safe(body, 200)}")
        logger.info("in-page GET %s -> 200 (%d char(s))", target, len(body))
        return body

    def fetch_json(self, path: str) -> dict:
        """One in-page ``window.fetch`` GET, parsed as JSON. Non-200 or non-JSON raises."""
        body = self.fetch_text(path, accept="application/json")
        try:
            return json.loads(body)
        except ValueError as exc:
            raise ValueError(
                f"{self.url_for(path)} returned HTTP 200 but the body is not JSON "
                f"({len(body)} char(s), head {ascii_safe(body, 200)!r})") from exc

    def download(self, path: str, *, timeout_s: Optional[int] = None) -> bytes:
        """Trigger a ``content-disposition: attachment`` download and return its BYTES.

        Read from the driver's temp file and then deleted: the bytes belong to the raw landing, not
        to a filesystem the next producer step has to know about."""
        target = self.url_for(path)
        page = self.page
        timeout_ms = int(timeout_s * 1000) if timeout_s else max(self.nav_timeout_ms,
                                                                 _DOWNLOAD_TIMEOUT_FLOOR_MS)
        with page.expect_download(timeout=timeout_ms) as info:
            page.evaluate(_DOWNLOAD_JS, target)
        download = info.value
        failure = download.failure()
        if failure:
            raise RuntimeError(f"download {target} failed: {ascii_safe(failure)}")
        local = download.path()
        if local is None:
            raise RuntimeError(f"download {target} produced no local artifact")
        data = Path(local).read_bytes()
        try:
            download.delete()
        except Exception as err:  # noqa: BLE001 -- the bytes are already in hand
            logger.debug("download cleanup failed: %s", ascii_safe(err))
        logger.info("download %s -> %d byte(s) (suggested name %s)", target, len(data),
                    ascii_safe(download.suggested_filename))
        return data


def challenge_failed_exit(leg: str, exc: BaseException) -> int:
    """The ONE line every W1c producer logs before exiting :data:`EXIT_CHALLENGE_FAILED`.

    Kept here so the three producers cannot word the residual-S2 answer three different ways, and
    so the string is ASCII by construction."""
    logger.error("CHALLENGE_FAILED %s: %s -- exiting rc %d (this run IS the residual S2 probe: the "
                 "venue challenge did not settle for this IP class)",
                 leg, ascii_safe(exc), EXIT_CHALLENGE_FAILED)
    return EXIT_CHALLENGE_FAILED


def navigation_failed_exit(leg: str, exc: BaseException) -> int:
    """The counterpart line, for a page that could not be REACHED. Always rc 1, never rc 7.

    The distinction is the whole reason :class:`NavigationFailed` exists: rc 7 means "the venue
    refused this IP class" and a CloudWatch metric filter reads it as the S2 answer. An egress or
    DNS failure exiting 7 would answer that question wrongly, unattended."""
    logger.error("NAV_FAILED %s: %s -- exiting rc 1. This is a NETWORK/EGRESS failure, NOT the "
                 "venue challenge: it says nothing about whether the challenge clears from this IP "
                 "class, and it is retryable as-is", leg, ascii_safe(exc))
    return 1
