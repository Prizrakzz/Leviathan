"""LANE 6 / P14 -- the free futures chain's SILVER leg order is load-bearing, and is pinned.

THE MECHANISM, READ OUT OF THE STATE MACHINE ITSELF
----------------------------------------------------
``leviathan-dev-silver-thin-contract`` renders four ``Map`` states. All four are
``MaxConcurrency: 1``, and none carries ``ToleratedFailureCount``. They differ in ONE way that
decides whether leg order matters:

  * **Fetch** -- its ``ItemProcessor``'s ``BatchSyncFetch`` carries ``Catch`` entries
    (``States.ALL -> ClassifyFailureFetch``, the Batch/infra classes ->
    ``RecordInfraFailureFetch``). A failed leg therefore ends its iteration SUCCESSFULLY with a
    recorded verdict, the Map runs every later leg anyway, and ``AnyFetchLegFailed`` reads the
    whole scan AFTER the Map to choose ``DegradedNotify`` or ``FailNotify``. **Fetch order is
    immaterial**, which is why this file does not pin it and the descriptor leaves it alone.
  * **Silver** and **Promote** -- their ``ItemProcessor``s carry NO ``Catch`` at all. A job-level
    ``States.TaskFailed`` propagates straight out: ``MapIterationFailed`` ->
    ``TaskStateAborted`` -> ``MapStateFailed``, and at ``MaxConcurrency: 1`` every leg after the
    failing index NEVER RUNS. **Order is the whole mechanism.**

THE MEASUREMENT THAT PAID FOR THIS PIN
---------------------------------------
Execution ``futures_eod-sched-ae6ab1af...``, 2026-09-21 22:30Z: the 5-leg Silver Map completed,
the Promote Map entered four iterations, then ``MapIterationFailed {"name":"Promote","index":3}``.
Index 3 was **miax** under the original order (czce, jse, cepea, miax, euronext). The failing job's
``StatusReason`` was ``"Rate limit exceeded while preparing network interface to be attached to
instance"`` with ``ExitCode: None`` -- a PRE-START fault that says nothing about the data. euronext
sat at index 4 and never ran: its shadow held ``trade_date`` 2026-09-21 while canonical stayed at
2026-09-18 on ``french_wheat_matif``, ``french_maize_matif`` and ``french_rapeseed_matif``.

THE RULE
--------
The legs are ordered by WHAT A LOST SESSION COSTS, and the classification is DERIVED from the
descriptor rather than asserted from a list in this file: a venue whose FETCH command carries no
``--lookback-days`` is FORWARD-ONLY -- its page serves today and nothing earlier -- so a session it
misses is gone once the silver leg's own window rolls past it. Those legs run FIRST. The windowed
venues re-request five days on every fire and self-heal, so they run LAST.

This is a MITIGATION and the file says so out loud: the fix is ``ToleratedFailureCount`` on the
Silver and Promote Maps plus a narrow pre-start ``retryStrategy`` on
``leviathan-dev-futures-eod-silver``, both deferred. A reorder only decides WHO PAYS when the
untreated fault recurs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts" / "silver"))

import gen_sfn_inputs as G  # noqa: E402  (path-injected sibling; this file has no package)

STEM = "futures_eod_free"


@pytest.fixture(scope="module")
def desc() -> dict:
    return G.load_descriptors()[STEM]


def _silver_sources(desc: dict) -> list[str]:
    """The ``--source`` of each silver task, in descriptor order."""
    out: list[str] = []
    for phase in desc["phases"]:
        if phase["name"] != "silver":
            continue
        for t in phase["tasks"]:
            cmd = t["command"]
            out.append(cmd[cmd.index("--source") + 1])
    return out


def _windowed_sources(desc: dict) -> set[str]:
    """The venues whose FETCH leg takes a window -- i.e. the ones that can self-heal.

    Derived, never listed: the descriptor's own fetch commands are the evidence, so a future
    venue that gains or loses ``--lookback-days`` moves itself into the right class and this pin
    follows it instead of going stale."""
    windowed: set[str] = set()
    for phase in desc["phases"]:
        if phase["name"] != "fetch":
            continue
        for t in phase["tasks"]:
            if "--lookback-days" not in t["command"]:
                continue
            script = t["command"][0].rsplit("/", 1)[-1]
            for src in _silver_sources(desc):
                if src in script:
                    windowed.add(src)
    return windowed


class TestTheOrderIsByWhatALostSessionCosts:
    def test_every_forward_only_leg_runs_before_every_windowed_leg(self, desc):
        """THE PIN. On HEAD the order is czce, jse, cepea, miax, euronext -- czce (windowed, index
        0) runs before euronext (forward-only, index 4), which is the arrangement that lost the
        2026-09-21 MATIF promote."""
        order = _silver_sources(desc)
        windowed = _windowed_sources(desc)
        forward_only = [s for s in order if s not in windowed]

        assert windowed, "no fetch leg carries --lookback-days -- the classification broke"
        assert forward_only, "every leg is windowed -- the classification broke"

        last_forward_only = max(order.index(s) for s in forward_only)
        first_windowed = min(order.index(s) for s in windowed)
        assert last_forward_only < first_windowed, (
            f"silver leg order {order}: forward-only {sorted(forward_only)} must all precede "
            f"windowed {sorted(windowed)} -- a windowed leg that fails first aborts the Map "
            f"(MaxConcurrency 1, no Catch in the Silver/Promote ItemProcessors) and costs a "
            f"forward-only venue its session permanently"
        )

    def test_the_forward_only_set_is_the_one_the_measurement_names(self, desc):
        """Belt and braces on the DERIVATION: if a descriptor edit ever made euronext, jse or
        cepea look windowed, the rule above would still 'pass' while protecting nothing."""
        windowed = _windowed_sources(desc)
        assert windowed == {"czce", "miax"}
        assert set(_silver_sources(desc)) - windowed == {"euronext", "jse", "cepea"}

    def test_the_reorder_did_not_drop_or_duplicate_a_leg(self, desc):
        order = _silver_sources(desc)
        assert len(order) == len(set(order)) == 5
        assert set(order) == {"euronext", "jse", "cepea", "czce", "miax"}


class TestThePromoteMapInheritsIt:
    def test_the_rendered_promote_tasks_carry_the_same_order(self, desc):
        """The Promote Map's ``ItemsPath`` is ``$.promote.tasks``, and ``render_input`` builds that
        list by walking the silver phase in order -- so the silver reorder IS the promote reorder.
        Index 3 was miax on 2026-09-21; after this change index 3 is a windowed leg by
        construction and euronext is index 0."""
        ei = G.render_input(desc)
        assert ei["promote"]["mode"] == "autonomous"
        promote = [t["command"][t["command"].index("--source") + 1]
                   for t in ei["promote"]["tasks"]]
        assert promote == _silver_sources(desc)
        assert promote[0] == "euronext"

    def test_every_rendered_silver_leg_still_publishes_shadow_and_promotes_canonical(self, desc):
        ei = G.render_input(desc)
        for t in ei["phases"]["silver"]["tasks"]:
            assert t["command"][-2:] == ["--publish-mode", "shadow"]
        for t in ei["promote"]["tasks"]:
            assert t["command"][-2:] == ["--publish-mode", "canonical"]


class TestTheDescriptorStaysLintCleanAndSaysWhy:
    def test_the_house_lint_accepts_the_reordered_descriptor(self, desc):
        """``gen_sfn_inputs`` is order-agnostic by design; this states it rather than assuming it,
        because the reorder reaches production only through a generator run."""
        assert G.lint_descriptor(desc, STEM) == []
        assert G.scan_unresolved_placeholders({STEM: desc}) == []

    def test_the_order_note_carries_the_execution_that_proves_the_mechanism(self, desc):
        """A bare reordering reads like a cosmetic edit and gets 'tidied' back. The note is the
        only thing standing between the next reader and the 2026-09-21 loss."""
        note = desc.get("silver_leg_order_note", "")
        assert "MapIterationFailed" in note
        assert "2026-09-21" in note
        assert "dag_schedules.auto.tfvars.json" in note, (
            "the note must say that a descriptor edit alone changes nothing at 22:30Z"
        )
