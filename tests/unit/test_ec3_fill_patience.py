"""EC-3 METERED-TURN FILL PATIENCE -- the pre-registered gate, as a fault-injection unit suite.

NO REAL POSTGRES. The choke is the shipped `tests/unit/test_pgstore.py::tiny_pool` idiom -- a 1-slot
pool with `_POOL_WAIT_S` monkeypatched to 1s and `psycopg.connect` replaced by a dummy object -- so the
whole horizon arithmetic runs in SIMULATED time (a 1s legacy wait, an 8s or 2s horizon) instead of the
120s/300s the serving values would cost a test run. The RATIOS are what the gate asserts, and they are
the shipped ones: the horizon is a multiple of the single-borrow wait, and the legacy path is exactly
one `get(timeout=max(1, _POOL_WAIT_S))`.

THE FOUR GATE CLAUSES (EVIDENCE_CAPACITY_ITEMS.md, EC-3):
  (a) metered-completes-late  -- a choked pool + an installed horizon acquires LATE instead of flooring
  (b) unmetered-fast-fails    -- no horizon installed -> the legacy 120s (here 1s) wedge, byte-identical
  (c) exhaust -> terminal     -- the horizon is a BOUND: past it the wedge raises, carrying the horizon.
                                 The REFUND half of (c) lives in test_dmw_credit_seam.py (the floored
                                 turn prices 0 via the walk-stamp absence), where the pricing seam is.
  (d) un-choked no-regression -- with a free pool both paths acquire immediately, and the unmetered call
                                 is PROVEN legacy by recording the timeout argument.
"""
from __future__ import annotations

import os
import queue
import threading
import time

import psycopg
import pytest
from leviathan.graphrag import pgstore as pg

LEGACY_WAIT = 1                       # the monkeypatched stand-in for the shipped _POOL_WAIT_S=120


class _Conn:
    """A pool slot's worth of nothing: `_acquire` only ever tests `.closed`."""
    closed = False


@pytest.fixture()
def tiny_pool(monkeypatch):
    """A fresh 1-slot pool with a short wait and no patience installed -- the shipped test_pgstore
    fixture, plus the EC-3 thread-local cleared on BOTH sides so no test can leak a horizon into the
    next one (pytest reuses the main thread, which is exactly the pool-thread reuse hazard)."""
    monkeypatch.setattr(pg, "_POOL", None)
    monkeypatch.setattr(pg, "_POOL_SIZE", 1)
    monkeypatch.setattr(pg, "_POOL_WAIT_S", LEGACY_WAIT)
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: _Conn())
    monkeypatch.delenv(pg._PATIENCE_ENV, raising=False)
    pg._clear_patience()
    yield
    pg._clear_patience()
    pg._POOL = None                   # never leak the tiny pool into other tests


WEDGE = "pg pool exhausted"


# ══ (a) METERED COMPLETES LATE ═══════════════════════════════════════════════════════════════════════
def test_a_metered_turn_waits_past_the_legacy_wait_and_acquires_late(tiny_pool):
    """CLAUSE (a). The pool is pinned by a holder that frees the slot after ~2-3 legacy wait slices.
    An unmetered borrow would have raised at 1s; the metered borrow keeps waiting and gets a real
    connection -- LATE, which is the entire product decision (a paid turn degrades in latency, not in
    depth). The bound is asserted on BOTH sides: strictly later than the legacy fail, strictly inside
    the horizon."""
    held = pg._acquire()                                     # drain the single slot
    freed_at = LEGACY_WAIT * 2.5
    threading.Timer(freed_at, pg._release, args=(held,)).start()
    t0 = time.monotonic()
    with pg.set_patience(LEGACY_WAIT * 8):
        conn = pg._acquire()                                 # would raise at 1s without the horizon
    waited = time.monotonic() - t0
    assert conn is not None and not conn.closed
    assert waited > LEGACY_WAIT                              # ...past where the legacy path gives up
    assert waited < LEGACY_WAIT * 8                          # ...and inside the horizon
    pg._release(conn)


def test_the_patient_path_never_sleeps_between_attempts(tiny_pool, monkeypatch):
    """A slept-through slice hands the freed slot to some other thread while this one naps -- latency
    invented rather than spent. The wait must BE the `Queue.get(timeout=...)`, so nothing in the loop
    may call `time.sleep`. The shim is installed on `pgstore.time` ONLY -- patching the real
    `time.sleep` globally would reach every other thread in the process, including this test's own
    releaser timer."""
    class _NoSleep:
        monotonic = staticmethod(time.monotonic)

        @staticmethod
        def sleep(*a):
            raise AssertionError("the patient loop slept")

    monkeypatch.setattr(pg, "time", _NoSleep)
    held = pg._acquire()
    threading.Timer(LEGACY_WAIT * 1.5, pg._release, args=(held,)).start()
    with pg.set_patience(LEGACY_WAIT * 6):
        conn = pg._acquire()
    pg._release(conn)


class _Clock:
    """A monotonic clock the test drives, so the SHIPPED values (120s wait, 300s horizon) can be
    exercised exactly in zero wall time. `_acquire` reads `time` through the module attribute, and
    `sleep` is wired to fail: the patient loop must never call it."""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def monotonic(self) -> float:
        return self.t

    def sleep(self, *a):                                     # pragma: no cover - the failure IS the point
        raise AssertionError("the patient loop slept")


def _slice_trace(monkeypatch, wait_s: int, horizon_s: float) -> list:
    """Run one doomed borrow at `wait_s`/`horizon_s` on the fake clock and return the slice timeouts
    the loop asked the queue for. The queue is empty forever; every `get` advances the clock by exactly
    its own timeout and reports Empty, which is what a real starved pool does."""
    clock = _Clock()
    seen: list = []

    def rec_get(timeout=None):
        seen.append(timeout)
        clock.t += float(timeout)
        raise queue.Empty()

    slot: queue.Queue = queue.Queue()
    slot.get = rec_get                                       # type: ignore[method-assign]
    monkeypatch.setattr(pg, "time", clock)
    monkeypatch.setattr(pg, "_POOL", slot)
    monkeypatch.setattr(pg, "_POOL_WAIT_S", wait_s)
    with pg.set_patience(horizon_s):
        with pytest.raises(RuntimeError, match=WEDGE):
            pg._acquire()
    return seen


def test_each_slice_is_jittered_and_clamped_to_what_is_left(monkeypatch):
    """The slice arithmetic, read off the queue itself AT THE SHIPPED VALUES (120s wait, 300s horizon --
    the fixture's 1s wait would hide the jitter entirely under the `max(1.0, ...)` floor, which is a
    property of the tiny fixture and not of serving).

    JITTER (0.8-1.2x) keeps N workers that queued at the same instant from re-colliding in lockstep
    every wait. The CLAMP to `remaining` is what makes the horizon a real bound rather than a suggestion
    the last slice gets to overshoot -- and it is why the sum of the slices is the horizon, exactly."""
    pg._clear_patience()
    seen = _slice_trace(monkeypatch, 120, 300.0)
    assert len(seen) >= 2                                    # several slices, not one 300s get
    assert all(s <= 120 * 1.2 + 1e-9 for s in seen), seen    # no slice may exceed the jitter ceiling
    assert 120 * 0.8 <= seen[0] <= 120 * 1.2, seen           # the first is a FULL jittered slice
    assert abs(sum(seen) - 300.0) < 1e-6, seen               # clamped: the loop spends the horizon, exactly
    # ...and it is actually RANDOM: the same doomed borrow, run again, asks for different slices. Two
    # continuous draws colliding has probability ~0, so this pins jitter rather than tolerating it.
    again = _slice_trace(monkeypatch, 120, 300.0)
    assert seen[0] != again[0], (seen, again)


def test_the_shipped_horizon_is_spent_in_a_handful_of_slices(monkeypatch):
    """Sanity on the shape an operator will actually see in a log: 300s over 120s slices is a couple of
    waits and a remainder, not a busy-loop of hundreds of tiny gets (which would be a spin, and would
    hammer the queue's lock while the pool is already sick)."""
    pg._clear_patience()
    seen = _slice_trace(monkeypatch, 120, 300.0)
    assert 2 <= len(seen) <= 5, seen


# ══ (b) UNMETERED FAST-FAILS, BYTE-IDENTICALLY ═══════════════════════════════════════════════════════
def test_an_unmetered_turn_still_fast_fails_with_the_legacy_message(tiny_pool):
    """CLAUSE (b). No horizon installed = every unmetered turn, every eval arm, every loader. The wedge
    must arrive at `_POOL_WAIT_S` wearing the PRE-EC-3 message, character for character -- the message
    is a contract: `orchestrator._floor_cause` types the floor off it and operators grep for it."""
    held = pg._acquire()
    t0 = time.monotonic()
    with pytest.raises(RuntimeError) as ei:
        pg._acquire()
    waited = time.monotonic() - t0
    assert str(ei.value) == (f"pg pool exhausted: no connection freed in {LEGACY_WAIT}s "
                             f"(size=1) — leaked slot or wedged holder")
    assert ei.value.__cause__ is None and ei.value.__suppress_context__      # the `from None`
    assert LEGACY_WAIT <= waited < LEGACY_WAIT * 3
    pg._release(held)


def test_a_deadline_shorter_than_one_wait_takes_the_legacy_path(tiny_pool, monkeypatch):
    """The documented boundary: `remaining <= _POOL_WAIT_S` -> legacy. A horizon so nearly spent that one
    more slice would just be this wait wearing a new name gets the single get, and the message therefore
    reports `_POOL_WAIT_S` -- the accepted, bounded overshoot recorded in pgstore's docstring."""
    seen: list = []
    slot: queue.Queue = queue.Queue()
    slot.get = lambda timeout=None: (seen.append(timeout), (_ for _ in ()).throw(queue.Empty()))[0]  # noqa: E731
    monkeypatch.setattr(pg, "_POOL", slot)
    with pg.set_patience(LEGACY_WAIT * 0.5):                 # less than one legacy wait left
        with pytest.raises(RuntimeError, match=f"freed in {LEGACY_WAIT}s"):
            pg._acquire()
    assert seen == [LEGACY_WAIT]                             # exactly ONE get, at the legacy timeout


# ══ (c) EXHAUSTION IS TERMINAL, AND CARRIES THE HORIZON ══════════════════════════════════════════════
def test_a_burned_horizon_raises_the_wedge_carrying_the_total_horizon(tiny_pool):
    """CLAUSE (c). The holder NEVER releases. Patience is a bound, not a promise: past the horizon the
    same wedge raises -- degrade, never hang -- and the seconds slot reports the TOTAL horizon, so the
    log line says what was actually spent instead of repeating the per-borrow wait."""
    held = pg._acquire()
    horizon = LEGACY_WAIT * 2
    t0 = time.monotonic()
    with pg.set_patience(horizon):
        with pytest.raises(RuntimeError) as ei:
            pg._acquire()
    waited = time.monotonic() - t0
    assert str(ei.value).startswith(f"pg pool exhausted: no connection freed in {int(horizon)}s (size=1)")
    assert horizon <= waited < horizon + LEGACY_WAIT * 2     # it waited the horizon, then gave up
    pg._release(held)


def test_the_wedge_is_typed_to_the_pool_slug_not_other():
    """EC-3 item 4: the floor gets a MACHINE-READABLE cause. Before this build the wedge fell through to
    `other` (the EC-0 benchmark recorded it as an incidental), so the clause was grep-only. The slug is
    in the closed set, so no dimension value is minted at runtime."""
    from leviathan.graphrag import orchestrator as orch
    wedge = RuntimeError("pg pool exhausted: no connection freed in 300s "
                         "(size=8) — leaked slot or wedged holder")
    assert orch._floor_cause(wedge) == "pg_pool_exhausted"
    assert "pg_pool_exhausted" in orch._FLOOR_CAUSES
    # ...and the neighbours it must not steal: a statement-timeout cancel is still its own cause, and
    # unrelated prose is still `other` (prose is not a signal).
    assert orch._floor_cause(RuntimeError("canceling statement due to statement timeout")) \
        == "pg_statement_timeout"
    assert orch._floor_cause(RuntimeError("provider hard down")) == "other"


def test_expiry_mid_walk_raises_rather_than_hangs(tiny_pool):
    """The multi-borrow shape, which is the whole reason the horizon is TURN-scoped: borrow, hold, borrow
    again. The second borrow inherits the SAME deadline -- it does not get a fresh one -- so a walk of
    hundreds of borrows cannot compound its way past the bound."""
    horizon = LEGACY_WAIT * 2
    with pg.set_patience(horizon):
        first = pg._acquire()                                # instant: the slot is free
        t0 = time.monotonic()
        with pytest.raises(RuntimeError, match=WEDGE):
            pg._acquire()                                    # the pool is now empty and stays empty
        assert time.monotonic() - t0 < horizon + LEGACY_WAIT  # bounded by what was LEFT, not a new horizon
    pg._release(first)


# ══ (d) UN-CHOKED: NO REGRESSION, AND THE UNMETERED PATH IS PROVABLY LEGACY ══════════════════════════
def test_a_free_pool_serves_both_paths_immediately(tiny_pool):
    """CLAUSE (d). With a slot available neither path waits -- patience is dead weight on a healthy pool,
    which is what makes it safe to leave on by default."""
    t0 = time.monotonic()
    c1 = pg._acquire()                                       # unmetered
    pg._release(c1)
    with pg.set_patience(LEGACY_WAIT * 8):                   # metered
        c2 = pg._acquire()
    pg._release(c2)
    assert time.monotonic() - t0 < LEGACY_WAIT               # both instant; no slice was ever entered


def test_the_unmetered_call_path_is_exactly_one_legacy_get(tiny_pool, monkeypatch):
    """CLAUSE (d), the PROOF rather than the timing: with no deadline installed, `_acquire` makes ONE
    `Queue.get` at `max(1, _POOL_WAIT_S)`. Anything else -- a loop, a different timeout, a clamp -- is a
    behavior change on the 100%-of-turns-today path, and a wall-clock assertion would not see it."""
    seen: list = []
    slot: queue.Queue = queue.Queue()
    slot.put(None)
    real_get = slot.get

    def rec_get(timeout=None):
        seen.append(timeout)
        return real_get(timeout=timeout)

    slot.get = rec_get                                       # type: ignore[method-assign]
    monkeypatch.setattr(pg, "_POOL", slot)
    conn = pg._acquire()
    assert seen == [max(1, pg._POOL_WAIT_S)] == [LEGACY_WAIT]
    assert conn is not None
    # ...and the same proof at the shipped value, so the pin is not an artifact of the tiny fixture.
    monkeypatch.setattr(pg, "_POOL_WAIT_S", 120)
    seen.clear()
    slot.put(conn)
    pg._acquire()
    assert seen == [120]


# ══ THE THREAD-LOCAL SEAM: install, nest, restore, adopt ═════════════════════════════════════════════
def test_no_deadline_is_installed_by_default():
    """The default state of every thread in the estate. None is not an error anywhere."""
    pg._clear_patience()
    assert pg.patience_deadline() is None
    assert pg.current_patience_deadline() is None


def test_set_patience_installs_and_restores():
    pg._clear_patience()
    with pg.set_patience(5):
        dl = pg.patience_deadline()
        assert dl is not None and 0 < dl - time.monotonic() <= 5
    assert pg.patience_deadline() is None                    # restored to ABSENT, not to some epoch


def test_nested_set_patience_may_shorten_but_never_extend_and_restores():
    """ONE HORIZON PER TURN is the decision of record, so nesting is clamped: an inner block may cut the
    turn's remaining time short, but it can never mint more of it. Either way the outer horizon is the
    value after the inner block exits -- an exception inside a walk must not leave a pooled serving
    thread carrying a dead turn's deadline."""
    pg._clear_patience()
    with pg.set_patience(10):
        outer = pg.patience_deadline()
        with pg.set_patience(1):                             # SHORTER -> wins
            assert pg.patience_deadline() < outer
        assert pg.patience_deadline() == outer               # ...and the outer horizon is restored
        with pg.set_patience(1000):                          # LONGER -> clamped to the turn's horizon
            assert pg.patience_deadline() == outer
        assert pg.patience_deadline() == outer
    assert pg.patience_deadline() is None


def test_a_disabled_patience_block_is_a_no_op_in_both_directions():
    """`set_patience(0)` installs nothing (the knob is off) and CLEARS nothing (an outer horizon is not
    a thing a disabled inner block may cancel)."""
    pg._clear_patience()
    with pg.set_patience(0):
        assert pg.patience_deadline() is None
    with pg.set_patience(None):
        assert pg.patience_deadline() is None
    with pg.set_patience(3):
        with pg.set_patience(0):
            assert pg.patience_deadline() is not None        # the outer horizon survives
    assert pg.patience_deadline() is None


def test_a_worker_thread_sees_nothing_until_it_adopts():
    """THE MEASURED FINDING THIS API EXISTS FOR (planner.py records it): a thread-local does NOT reach a
    pool worker, and contextvars do not either. Capture on the parent, install on the worker."""
    pg._clear_patience()
    saw: dict = {}

    def worker(deadline=None):
        saw["bare"] = pg.patience_deadline()
        with pg.adopt_patience(deadline):
            saw["adopted"] = pg.patience_deadline()
        saw["after"] = pg.patience_deadline()

    with pg.set_patience(9):
        parent = pg.current_patience_deadline()
        t = threading.Thread(target=worker, kwargs={"deadline": parent})
        t.start()
        t.join()
    assert saw["bare"] is None                               # the un-adopted worker: pre-EC-3 behavior
    assert saw["adopted"] == parent                          # the parent's horizon, to the instant
    assert saw["after"] is None                              # cleared: pool threads are REUSED


def test_adopt_patience_is_nested_safe_and_fail_open():
    """`adopt_lane`'s exact contract, one thread-local over. A thread that already carries a deadline
    KEEPS it (the sequential branches of both pools run on the caller's own thread, where clearing would
    strip the turn's own horizon mid-walk), and adopting None is a no-op."""
    pg._clear_patience()
    with pg.set_patience(7):
        own = pg.patience_deadline()
        with pg.adopt_patience(own + 1000):                  # already carrying one -> unchanged
            assert pg.patience_deadline() == own
        assert pg.patience_deadline() == own
    with pg.adopt_patience(None):
        assert pg.patience_deadline() is None
    assert pg.patience_deadline() is None


def test_a_worker_that_adopts_actually_waits_late(tiny_pool):
    """The two halves joined: a POOL WORKER that adopted the parent's horizon acquires late where an
    un-adopted twin would floor. This is the property the walk depends on -- every borrow of a metered
    turn happens on one of these threads."""
    held = pg._acquire()
    threading.Timer(LEGACY_WAIT * 2.5, pg._release, args=(held,)).start()
    out: dict = {}

    def worker(deadline):
        try:
            with pg.adopt_patience(deadline):
                out["conn"] = pg._acquire()
        except BaseException as e:  # noqa: BLE001 - recorded, asserted on below
            out["exc"] = e

    with pg.set_patience(LEGACY_WAIT * 8):
        t = threading.Thread(target=worker, args=(pg.current_patience_deadline(),))
        t.start()
        t.join(timeout=LEGACY_WAIT * 10)
    assert "exc" not in out, out.get("exc")
    assert out["conn"] is not None
    pg._release(out["conn"])


# ══ THE KNOB ═════════════════════════════════════════════════════════════════════════════════════════
def test_the_patience_knob_grammar(monkeypatch):
    """ROLLBACK SEMANTICS, pinned. An EXPLICIT 0 (or a negative) disables -- that is someone reaching for
    the rollback, and it takes effect on the next turn with no deploy. Anything UNPARSEABLE falls back to
    the 300s default, because a typo must not silently un-ship the item and leave a floor rate nobody can
    explain. Read at CALL TIME: no re-import, no restart."""
    monkeypatch.delenv(pg._PATIENCE_ENV, raising=False)
    assert pg._fill_patience_s() == 300.0                    # absent -> the ratified default
    for bad in ("", "   ", "abc", "300s", "[]", "None"):
        monkeypatch.setenv(pg._PATIENCE_ENV, bad)
        assert pg._fill_patience_s() == 300.0, bad
    for off in ("0", "0.0", "-1", " 0 "):
        monkeypatch.setenv(pg._PATIENCE_ENV, off)
        assert pg._fill_patience_s() == 0.0, off
    monkeypatch.setenv(pg._PATIENCE_ENV, "45")
    assert pg._fill_patience_s() == 45.0
    monkeypatch.setenv(pg._PATIENCE_ENV, "90.5")             # same call, new value: call-time read
    assert pg._fill_patience_s() == 90.5
    assert pg._PATIENCE_ENV == "GRAPHRAG_FILL_PATIENCE_S"    # the name operators will type


def test_the_knob_default_matches_the_spec_horizon():
    """EC-3 as written: 120s -> up to 300s."""
    assert pg._PATIENCE_DEFAULT_S == 300.0
    assert os.environ.get(pg._PATIENCE_ENV) in (None, "")    # ...and nothing in the suite env pre-sets it


# ══ THE ORCHESTRATOR SEAM: metered installs, unmetered does not ══════════════════════════════════════
def test_the_orchestrator_installs_a_horizon_only_for_a_metered_tier(monkeypatch):
    """The adoption decision, at its seam. `_patience_ctx` is the ONE place that decides, it reads the
    HONORED mode (never the effective one -- an escalated turn is still a `deep` purchase), and every
    gate fails open to `nullcontext()`, i.e. to the pre-EC-3 function."""
    from leviathan.graphrag import orchestrator as orch
    from leviathan.graphrag import reasoning_modes as rm
    monkeypatch.delenv(pg._PATIENCE_ENV, raising=False)
    pg._clear_patience()
    with orch._patience_ctx(rm.DEEP):
        assert pg.patience_deadline() is not None            # the paid tier buys the horizon
    assert pg.patience_deadline() is None
    with orch._patience_ctx(rm.DEEP_HP):                     # the twin follows its base (D-HP H1 Z5(d))
        assert pg.patience_deadline() is not None
    for unmetered in (rm.QUICK, rm.STANDARD, rm.MAX, None, "nonsense"):
        with orch._patience_ctx(unmetered):
            assert pg.patience_deadline() is None, unmetered
    monkeypatch.setenv(pg._PATIENCE_ENV, "0")                # THE ROLLBACK: metered, but knob off
    with orch._patience_ctx(rm.DEEP):
        assert pg.patience_deadline() is None


def test_the_eval_lane_is_not_special_cased(monkeypatch):
    """STATED SO NOBODY ADDS ONE. The eval/Batch arms run `--mode max` (unpriced -> unmetered here) and
    `--mode esc` (priced, but never `honored`, and unmetered by the predicate's conservative read). Their
    protection from a 300s wait is the POOL-CONTENTION LAW -- arms never run concurrent with each other
    and carry pool 8 -- not a lane check in this code, and a lane check would be the thing that made the
    serving predicate lie."""
    import inspect

    from leviathan.graphrag import orchestrator as orch
    from leviathan.graphrag import reasoning_modes as rm
    # STRUCTURAL, not a grep: the decider takes exactly ONE argument, the honored mode. It cannot see a
    # lane, a jobdef, an arm name or a caller, so there is nowhere for a special case to be written.
    assert list(inspect.signature(orch._patience_ctx).parameters) == ["honored"]
    pg._clear_patience()
    for arm in (rm.MAX, rm.MAX_C0, rm.MAX_CC1, rm.ESC, rm.ESC_R):
        with orch._patience_ctx(arm):
            assert pg.patience_deadline() is None, arm


# ══ THE PLANNER SEAM: both pools capture on the parent and install per worker ════════════════════════
def test_both_pools_capture_and_adopt_the_parent_horizon():
    """The propagation, asserted on the planner's own helpers rather than by spinning a walk: capture
    reads the CALLER's thread, and `_adopt_parent` installs it on the worker beside the rerank lane --
    with neither captured it is an empty stack, i.e. the bare call."""
    from leviathan.graphrag import planner as pl
    pg._clear_patience()
    mod, dl = pl._capture_parent_patience()
    assert mod is pg and dl is None
    with pg.set_patience(6):
        mod, dl = pl._capture_parent_patience()
        assert dl == pg.patience_deadline()
    seen: dict = {}

    def worker():
        with pl._adopt_parent(None, None, mod, dl):
            seen["adopted"] = pg.patience_deadline()
        seen["after"] = pg.patience_deadline()
        with pl._adopt_parent(None, None, None, None):       # nothing captured -> the bare call
            seen["bare"] = pg.patience_deadline()

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert seen == {"adopted": dl, "after": None, "bare": None}


def test_the_fill_and_probe_pools_both_carry_the_capture():
    """Both borrow populations are wired, not just the loud one: the fill workers (~10 fetches) AND the
    probe workers (~24 round-trips) draw from the SAME pool, so a turn whose probes fast-failed would
    floor exactly as hard as one whose fills did."""
    import inspect

    from leviathan.graphrag import planner as pl
    fill = inspect.getsource(pl._parallel_fill)
    probes = inspect.getsource(pl.ground)
    assert "_capture_parent_patience()" in fill and "_adopt_parent(" in fill
    assert probes.count("_capture_parent_patience()") >= 1 and "_adopt_parent(" in probes


def test_the_numbers_lane_does_not_adopt(tiny_pool, monkeypatch):
    """DECLARED EXEMPTION, PINNED BEHAVIORALLY (rewritten 2026-08-15). `pgnumbers.pg_query` keeps the
    legacy fast-fail: its Athena fallback IS its patience, and making it wait 300s would trade a fast
    honest degrade for a slow one.

    WHY THE OLD PIN WAS NO PIN AT ALL. It asserted the numbers module never NAMES the patience API
    (`"adopt_patience" not in src`). But the deadline is AMBIENT -- `_acquire` reads a thread-local, no
    caller opts in -- so not naming the API is EXACTLY the state in which the lane silently inherits the
    horizon, which is what it did: the cascade-quantify legs call `numbers_lookup` sequentially on the
    WALK's thread inside `_patience_ctx`, so a metered turn's numbers lookup took the patient path. The
    old assertion was green in both worlds; a test that cannot fail for the behavior it names is a
    decoration. This one CHOKES the pool with a horizon installed ON THIS THREAD -- the exact failing
    configuration -- and reads what the borrow actually asked the queue for."""
    from leviathan.graphrag.numbers import pgnumbers
    seen: list = []
    slot: queue.Queue = queue.Queue()

    def rec_get(timeout=None):
        seen.append(timeout)
        raise queue.Empty()

    slot.get = rec_get                                       # type: ignore[method-assign]
    monkeypatch.setattr(pg, "_POOL", slot)
    with pg.set_patience(LEGACY_WAIT * 8):                   # a metered turn's horizon, on THIS thread
        outer = pg.patience_deadline()
        assert outer is not None                             # the failing configuration, confirmed present
        with pytest.raises(RuntimeError) as ei:
            pgnumbers.pg_query("select 1")
        assert pg.patience_deadline() == outer               # SUSPENDED, not cleared -- the walk keeps its bound
    assert seen == [max(1, pg._POOL_WAIT_S)] == [LEGACY_WAIT]  # ONE legacy get, not a patient loop
    # ...and the message reports the LEGACY wait, never the horizon: the patient path would say `in 8s`.
    assert str(ei.value) == (f"pg pool exhausted: no connection freed in {LEGACY_WAIT}s "
                             f"(size=1) — leaked slot or wedged holder")
    assert pg.patience_deadline() is None                    # the outer block still restores as before


def test_the_numbers_suspend_is_scoped_to_the_borrow_not_the_turn(monkeypatch):
    """THE OTHER HALF, and the reason the seam SUSPENDS instead of disabling: exempting the numbers lane
    must not disarm the walk that surrounds it. Same thread, shipped values, fake clock -- a numbers
    borrow (legacy, one 120s get) followed by a walk borrow (patient, several jittered slices summing to
    what is LEFT of the 300s horizon, not a fresh one). If the restore leaked, the second borrow would
    take the legacy path too; if it restored a fresh deadline, the bound would stop being a bound."""
    from leviathan.graphrag.numbers import pgnumbers
    pg._clear_patience()
    clock = _Clock()
    seen: list = []

    def rec_get(timeout=None):
        seen.append(timeout)
        clock.t += float(timeout)
        raise queue.Empty()

    slot: queue.Queue = queue.Queue()
    slot.get = rec_get                                       # type: ignore[method-assign]
    monkeypatch.setattr(pg, "time", clock)
    monkeypatch.setattr(pg, "_POOL", slot)
    monkeypatch.setattr(pg, "_POOL_WAIT_S", 120)
    with pg.set_patience(300.0):
        with pytest.raises(RuntimeError, match="freed in 120s"):
            pgnumbers.pg_query("select 1")                   # the numbers lane: ONE legacy get
        assert seen == [120]
        with pytest.raises(RuntimeError, match=WEDGE):
            pg._acquire()                                    # the walk, immediately after: still patient
    walk = seen[1:]
    assert len(walk) >= 2, seen                              # a patient loop, not a second legacy get
    assert abs(sum(walk) - 180.0) < 1e-6, seen               # 300 horizon MINUS the 120 the numbers leg spent
    pg._clear_patience()
