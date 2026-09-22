"""LANE 6 / P14 -- the CEPEA 403 is TRANSIENT, and the producer must retry it.

WHY THIS FILE EXISTS, IN THE ESTATE'S OWN MEASUREMENTS
------------------------------------------------------
``jobs/ingest/fetch_cepea_daily.py`` carried a comment calling HTTP 403 "Cloudflare's static UA
filter. NOT retryable (retrying a UA block just hammers the origin)", and ``fetch_indicator``
raised on the FIRST 403 -- above, and therefore outside, the exponential-backoff loop written
directly below it. The schedule's own CloudWatch log falsifies the premise. Log group
``/aws/batch/leviathan-dev``, stream prefix ``futures-eod-free-fetch``, verbatim:

  * 2026-09-15 22:33:40 -- ``RuntimeError: ... returned HTTP 403``, indicator 23 AND indicator 77,
    **120 ms apart**: one request each, no sleep, no second attempt.
  * 2026-09-16 22:33:36 and 2026-09-17 22:33:33 -- the same, both indicators.
  * 2026-09-14, 09-18, 09-21 -- ``landed=2 ... verdict fresh`` with the BYTE-IDENTICAL pinned
    ``CEPEA_USER_AGENT``.

A user agent the origin accepts on three of eight days is not a static UA block. And this leg has
no history anywhere -- the ``.aspx`` series pages are closed by policy, the widget serves the last
published value only, and the archive one-shot leaves a ~9-year hole -- so every un-retried 403
destroyed a session permanently. CEPEA lost 11 of 36 sessions between 2026-08-04 and 2026-09-21.

WHAT IS PINNED, AND WHAT IS DELIBERATELY NOT
--------------------------------------------
Pinned: a 403 followed by a 200 LANDS the session (this fails on HEAD, where the first 403 raises);
the 403 rides the SAME backoff schedule as 429/5xx; and :data:`_MAX_ATTEMPTS` consecutive 403s
STILL raise a hard RuntimeError naming the status, because a fence that stopped failing closed
would be strictly worse than the defect it replaced -- a silent empty write on a table with no
freshness alarm.

NOT pinned, because the same log shows it is a different fix: 2026-09-10 and 2026-09-11 were lost
to HTTP 500, which was already retryable and already burned all three attempts (5 s then 10 s) and
still failed. No in-process retry survives a CEPEA origin outage; the complement is a catch-up
fire, which is a schedule change.

Hermetic: no network, no AWS, and ``time.sleep`` is patched in every test that can reach it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FETCH = _load("jobs/ingest/fetch_cepea_daily.py", "fetch_cepea_daily_403")

# The live widget payload's shape, reduced to what a caller of fetch_indicator receives. The
# function returns resp.content verbatim and validates nothing, so the bytes only have to be
# distinguishable from a challenge body.
_WIDGET = (b'document.write(`<table class="imagenet-widget-tabela"><tbody><tr>'
           b'<td>21/09/2026</td><td>Milho</td><td>R$ 1.782,18</td></tr></tbody></table>`)')
_CHALLENGE_BODY = b"<html><title>Just a moment...</title>cdn-cgi/content</html>"


class _Resp:
    """One scripted response. ``raise_for_status`` is the tripwire: the 403 path must never
    reach it, because ``HTTPError`` is a ``requests.RequestException`` and would be swallowed
    into ``last_error`` instead of raising the verbatim Cloudflare message."""

    def __init__(self, status: int, content: bytes):
        self.status_code = status
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(
                f"raise_for_status() reached on HTTP {self.status_code} -- the challenge and "
                f"retryable statuses must be handled inside the loop, never here"
            )
        return None


@pytest.fixture
def scripted(monkeypatch):
    """Drive ``fetch_indicator`` off a scripted status sequence; record the URLs, the headers and
    every backoff the loop actually slept."""
    state = {"calls": [], "sleeps": [], "headers": []}

    def _install(statuses: list[int]):
        queue = list(statuses)

        def _get(url, headers=None, timeout=None):
            state["calls"].append(url)
            state["headers"].append(dict(headers or {}))
            status = queue.pop(0)
            return _Resp(status, _WIDGET if status == 200 else _CHALLENGE_BODY)

        monkeypatch.setattr(FETCH.requests, "get", _get)
        monkeypatch.setattr(FETCH.time, "sleep", lambda s: state["sleeps"].append(s))
        return state

    return _install


class TestTheChallengeIsRetried:
    def test_a_transient_403_then_a_200_lands_the_session(self, scripted):
        """THE PIN. On HEAD the first 403 raises and the 2026-09-15/16/17 sessions die with it;
        here the loop retries and the payload comes back."""
        state = scripted([403, 200])
        assert FETCH.fetch_indicator(23) == _WIDGET
        assert len(state["calls"]) == 2, "the 403 must cost a SECOND request, not a raise"
        assert state["sleeps"] == [FETCH._BACKOFF_SECONDS]

    def test_two_403s_then_a_200_still_lands_within_the_attempt_budget(self, scripted):
        state = scripted([403, 403, 200])
        assert FETCH.fetch_indicator(77) == _WIDGET
        assert len(state["calls"]) == FETCH._MAX_ATTEMPTS
        assert state["sleeps"] == [FETCH._BACKOFF_SECONDS, FETCH._BACKOFF_SECONDS * 2]

    def test_the_403_rides_the_SAME_backoff_as_the_retryable_statuses(self, scripted):
        """The 403 is not given a schedule of its own: whatever 500 costs, 403 costs. This is the
        half that makes the fix a MOVE INTO the existing loop rather than a second loop."""
        state = scripted([500, 200])
        assert FETCH.fetch_indicator(23) == _WIDGET
        five_hundred = list(state["sleeps"])

        state["calls"].clear()
        state["sleeps"].clear()
        state = scripted([403, 200])
        assert FETCH.fetch_indicator(23) == _WIDGET
        assert state["sleeps"] == five_hundred

    def test_the_pinned_browser_user_agent_is_sent_on_the_RETRY_too(self, scripted):
        """A retry that quietly rotated or dropped the UA would be bot evasion AND would make the
        measurement above unrepeatable. Every attempt sends the same pinned header."""
        state = scripted([403, 200])
        FETCH.fetch_indicator(23)
        assert len(state["headers"]) == 2
        assert {h.get("User-Agent") for h in state["headers"]} == {FETCH.CEPEA_USER_AGENT}


class TestTheFenceStillFailsClosed:
    def test_a_403_on_every_attempt_raises_and_is_never_an_empty_result(self, scripted):
        """Fences CORRECT, they do not DELETE -- and they do not start fail-OPEN either. A real UA
        block still ends the run with the verbatim Cloudflare message, and the raise is a
        RuntimeError (never an HTTPError out of raise_for_status), so nothing downstream can read
        it as 'no data today'."""
        state = scripted([403] * FETCH._MAX_ATTEMPTS)
        with pytest.raises(RuntimeError) as exc:
            FETCH.fetch_indicator(23)
        msg = str(exc.value)
        assert "403" in msg
        assert "NOT an empty result" in msg
        assert FETCH.CEPEA_USER_AGENT.split("/")[0] in msg or "CEPEA_USER_AGENT" in msg
        assert len(state["calls"]) == FETCH._MAX_ATTEMPTS

    def test_the_hard_failure_names_the_attempt_budget_it_exhausted(self, scripted):
        """The operator reading the 3am log must be able to tell a real block from an edge hiccup,
        and the only difference is the COUNT -- so the message carries it."""
        scripted([403] * FETCH._MAX_ATTEMPTS)
        with pytest.raises(RuntimeError, match=rf"all {FETCH._MAX_ATTEMPTS} attempts"):
            FETCH.fetch_indicator(23)

    def test_the_challenge_status_carries_the_measurement_that_refuted_its_old_premise(self):
        """The falsified premise lived in a COMMENT, and a comment that merely FLIPPED its verdict
        would be reverted by the next reader who reached the 2026-07-29 probe first. So the pin is
        the EVIDENCE, not the wording: the constant's own comment must name the days the pinned UA
        landed and say, in the operative sentence, that the status is retryable.

        Note what this deliberately does NOT assert -- the absence of the old phrase. The comment
        QUOTES the claim it overturns, which is the only way the next reader learns why the raise
        moved, and a negative string check would ban the quotation along with the error."""
        src = (_REPO / "jobs/ingest/fetch_cepea_daily.py").read_text(encoding="utf-8")
        head = src.split("_CHALLENGE_STATUS = 403")[0]
        comment = head[head.rindex("# Cloudflare"):]
        assert "RETRYABLE" in comment, "the operative verdict must be stated, not implied"
        for landed in ("2026-09-14", "09-18", "09-21"):
            assert landed in comment, f"the comment must name {landed}, a day the pinned UA landed"
