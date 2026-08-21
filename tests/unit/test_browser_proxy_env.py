"""The browser runtime has NO proxy surface — a WRITTEN REFUSAL, pinned (S2 law).

This file previously tested a ``proxy_settings_from_env`` / ``BROWSER_PROXY_*`` wiring that
``leviathan.ingest.browser_fetch`` never shipped. That absence is DELIBERATE, not drift: the S2
probe (2026-07-31, banked in the estate record) resolved that challenged venues detect
``navigator.webdriver``, NOT the IP class — so routing the browser through a proxy buys nothing
legitimate, and disguising the fetch vantage is bot evasion, which the estate REFUSES outright
(the same law that put the minagro capture on a residential run instead of a masked cloud one,
and left DCE/Bursa waiting for a legitimate route).

The module's own design carries the honest alternative: a challenge that never settles exits
``EXIT_CHALLENGE_FAILED`` so "this venue refuses this IP class" is a NAMED outcome, never a thing
to route around. This fence keeps the refusal true — if a proxy surface ever appears here, it must
arrive with an owner decision that overturns S2 in writing, and this test is where that decision
gets recorded.
"""
from __future__ import annotations

import inspect

from leviathan.ingest import browser_fetch


def test_no_proxy_settings_helper_exists():
    assert not hasattr(browser_fetch, "proxy_settings_from_env")


def test_module_source_carries_no_proxy_wiring():
    src = inspect.getsource(browser_fetch)
    assert "BROWSER_PROXY" not in src
    assert "proxy" not in src.lower()


def test_the_honest_alternative_is_the_named_exit_code():
    """The S2 design: a refusing venue is a NAMED outcome (ChallengeFailed -> its exit code),
    never a signal to change vantage."""
    assert hasattr(browser_fetch, "ChallengeFailed")
    assert hasattr(browser_fetch, "EXIT_CHALLENGE_FAILED")
