"""F3 -- the 24 convergence probes run CONCURRENTLY, but WHICH ones run stays deterministic by construction.

The probe loop was 24 strictly-serial pg round-trips at ~630 ms each (serial-sum == the `rest` stage wall to
0.3%). Parallelising it naively over the shared `budget["left"]` counter would make the ADMITTED probe set
depend on thread completion order -> different fired_regimes -> different answers, so the fix freezes the
admitted list on a pure-CPU pass first and only then fans out.

The four live trace keys the serving path publishes off this loop -- fired_regimes, regime_basis, silver_veto,
n_probes -- are compared as JSON BYTES (dict insertion order included), because `silver_veto` and
`regime_basis` are dicts whose key order rides into the answer payload.

Pinned here:
  * the frozen list equals the sequential selection under a BINDING budget and a non-binding one;
  * the silver-first verdicts (observed / normal-veto) still consume NO probe budget, so they shift which
    drivers the binding budget admits -- and the veto dict's insertion order is unchanged;
  * consumption follows the FROZEN order even when the futures complete in exactly reverse order;
  * a probe exception surfaces the FIRST failure in frozen order, like the serial loop.
"""
from __future__ import annotations

import concurrent.futures as cf
import json

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag import planner as pl

_KW = ["frost", "substitute", "drought"]
_A_DRIVERS = ["a_alpha", "a_bravo", "a_charlie", "a_delta", "a_echo"]
_R_DRIVERS = ["r_alpha", "r_bravo"]
# The frozen probe order IS sorted(contract) x sorted(required driver) -- spelled out so a regression in
# either loop level is visible as a diff, not as a re-derived expectation.
_FROZEN = [f"drivers/{d}" for d in _A_DRIVERS] + [f"drivers/{d}" for d in _R_DRIVERS]
_ASOF = "2021-08-01"


def _embed(texts):
    return [[1.0 if kw in t.lower() else 0.0 for kw in _KW] for t in texts]


def _d(id_, mech):
    return cs.Driver(id=id_, type="hazard", sign="+", mechanism=mech)


def _graph() -> g.CausalGraph:
    """arabica -> robusta over a query-relevant tracked edge, with BOTH contracts' convergence drivers scored
    irrelevant to the query. tau prunes every driver from the walk, so every required driver reaches the
    firing loop as a PROBE (no walk-evidence pre-seed short-circuits it) -- the shape RC3 measured."""
    arabica = cs.CausalContract(
        contract="arabica", aliases=["arabica"],
        drivers=[_d(x, "unrelated mechanism") for x in _A_DRIVERS],
        convergence=[cs.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=1,
                                          drivers=list(_A_DRIVERS))],
        inter_commodity=[cs.InterCommodityEdge(driver_commodity="robusta", relation="substitutes_for",
                                              sign="-", mechanism="frost substitute")])
    robusta = cs.CausalContract(
        contract="robusta", aliases=["robusta"],
        drivers=[_d(x, "unrelated mechanism") for x in _R_DRIVERS],
        convergence=[cs.ConvergenceSignal(name="glut", direction="-", requires_any_n_of=1,
                                          drivers=list(_R_DRIVERS))])
    return g.CausalGraph({"arabica": arabica, "robusta": robusta}, silver=set())


class _Run:
    """One ground() execution plus what we observed about it."""

    def __init__(self):
        self.probed: list[str] = []            # slices handed to `probe`, in CALL order
        self.completed: list[str] = []         # slices whose result was PRODUCED, in completion order
        self.sg = None

    @property
    def keys4(self) -> str:
        t = self.sg.trace
        return json.dumps([self.sg.fired_regimes, t["regime_basis"], t["silver_veto"], t["n_probes"]])


class _RevPool:
    """A ThreadPoolExecutor stand-in that completes submitted work in exactly REVERSE submit order (the whole
    queue drains on the first .result()), so "consumed in frozen order" cannot be an accident of timing.
    `map` is provided because the walk's evidence fill shares cf.ThreadPoolExecutor."""

    def __init__(self, max_workers=None):
        self._q: list = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def map(self, fn, items):
        return [fn(i) for i in items]

    def shutdown(self, wait=True, cancel_futures=False):
        """_run_probes owns its pool EXPLICITLY (not via `with`), so the stand-in needs the same surface --
        see test_failing_probe_does_not_drain_the_queued_probes for why the `with` form is wrong here."""
        return None

    def submit(self, fn, *a, **kw):
        h = _Handle(self, fn, a, kw)
        self._q.append(h)
        return h

    def _drain(self):
        for h in reversed(self._q):
            if not h.done:
                h.value, h.done = h.fn(*h.a, **h.kw), True


class _Handle:
    def __init__(self, pool, fn, a, kw):
        self.pool, self.fn, self.a, self.kw = pool, fn, a, kw
        self.done, self.value = False, None

    def result(self):
        self.pool._drain()
        return self.value


def _ground(monkeypatch, *, probe_cap, workers, silver=None, pool=None, boom=(), run=None) -> _Run:
    r = run or _Run()
    monkeypatch.setattr(pl, "_PROBE_WORKERS", workers)
    if pool is not None:
        monkeypatch.setattr(cf, "ThreadPoolExecutor", pool)

    def retrieve(query, slice_, *, k, asof=None, near=None):
        if slice_.startswith("drivers/"):
            r.probed.append(slice_)
            if slice_ in boom:
                raise RuntimeError(f"probe blew up on {slice_}")
            r.completed.append(slice_)
            return [{"date": "2021-06-01", "source": "NOAA", "source_key": f"s3://{slice_}", "text": "chatter"}]
        return []                                                  # contract slices: no walk evidence

    graph = _graph()
    sg = pl.grounded_subgraph("frost substitute", graph, embed=_embed,
                              route_fn=lambda q, gr: ["arabica"], tau=0.35, depth=2)
    assert sorted({n.contract for n in sg.nodes}) == ["arabica", "robusta"]     # fixture guard: both contracts
    assert not any(n.kind == "driver" for n in sg.nodes)                        # ...and zero walked drivers
    r.sg = pl.ground(sg, "frost substitute", graph, retrieve=retrieve, silver_lookup=silver, asof=_ASOF,
                     probe_cap=probe_cap, driver_slices=set(_A_DRIVERS) | set(_R_DRIVERS))
    return r


# -- (c) the frozen list equals the sequential selection -------------------------------------------------
@pytest.mark.parametrize("probe_cap,admitted", [
    (4, _FROZEN[:4]),                      # BINDING: the cap cuts inside arabica, robusta never gets a probe
    (6, _FROZEN[:6]),                      # BINDING across the contract boundary
    (24, _FROZEN),                         # NON-binding (the reasoning-turn regime: n_probes=7 < cap)
])
def test_frozen_probe_list_equals_serial_selection(monkeypatch, probe_cap, admitted):
    seq = _ground(monkeypatch, probe_cap=probe_cap, workers=1)
    par = _ground(monkeypatch, probe_cap=probe_cap, workers=8)
    assert seq.probed == admitted                                  # sequential path IS the frozen order
    assert sorted(par.probed) == sorted(admitted)                  # same SET under concurrency
    assert par.sg.trace["n_probes"] == len(admitted) == seq.sg.trace["n_probes"]
    assert par.keys4 == seq.keys4                                  # fired_regimes/basis/veto/n_probes bytes


def test_non_binding_budget_leaves_headroom(monkeypatch):
    """Correctness must not rest on the cap binding: a turn under the cap (the measured n_probes=11 reasoning
    case) probes every required driver and still reports n_probes from the same arithmetic."""
    par = _ground(monkeypatch, probe_cap=24, workers=8)
    assert par.sg.trace["n_probes"] == len(_FROZEN) < 24
    assert set(par.sg.trace["regime_basis"]) == {"arabica", "robusta"}
    assert {(f["contract"], f["name"]) for f in par.sg.fired_regimes} == {("arabica", "squeeze"),
                                                                         ("robusta", "glut")}


def test_silver_verdicts_consume_no_budget_and_keep_veto_order(monkeypatch):
    """The budget arithmetic is entangled with the silver-first branch: an observed/normal verdict resolves a
    driver WITHOUT a probe, so it shifts which drivers a binding cap admits. Phase 1 walks that branch in the
    original serial order, so both the admitted set and silver_veto's insertion order survive."""
    def silver(cid, did, asof):
        if did == "a_bravo":
            return {"live": True, "verdict": "observed", "value": 2.1, "unit": "z", "z": 2.1,
                    "knowledge_date": "2021-07-01", "ref": "frost_z", "detail": ""}
        if did in ("a_charlie", "r_alpha"):
            return {"live": True, "verdict": "normal", "value": 0.1, "unit": "z", "z": 0.1,
                    "knowledge_date": "2021-07-02", "ref": "frost_z"}
        return {"live": False}

    seq = _ground(monkeypatch, probe_cap=3, workers=1, silver=silver)
    par = _ground(monkeypatch, probe_cap=3, workers=8, silver=silver)
    # a_bravo (observed) and a_charlie (vetoed) pay nothing -> the 3 probes land on alpha/delta/echo.
    assert seq.probed == ["drivers/a_alpha", "drivers/a_delta", "drivers/a_echo"]
    assert seq.sg.trace["n_probes"] == 3
    assert list(seq.sg.trace["silver_veto"]) == ["arabica", "robusta"]          # outer insertion order
    assert sorted(par.probed) == sorted(seq.probed)
    assert par.keys4 == seq.keys4


# -- (d) consumption order is the frozen order, not the completion order ---------------------------------
def test_consumption_follows_frozen_order_not_completion_order(monkeypatch):
    seq = _ground(monkeypatch, probe_cap=24, workers=1)
    rev = _ground(monkeypatch, probe_cap=24, workers=8, pool=_RevPool)
    assert rev.probed == list(reversed(_FROZEN))                   # the futures really did invert
    assert rev.keys4 == seq.keys4                                  # ...and nothing observable moved


def test_probe_exception_surfaces_first_failure_in_frozen_order(monkeypatch):
    """The serial loop propagated the FIRST failing probe out of ground(). Results are read by index, so a
    later failure can never mask an earlier one."""
    with pytest.raises(RuntimeError, match="a_bravo"):
        _ground(monkeypatch, probe_cap=24, workers=8, boom=("drivers/a_bravo", "drivers/a_delta"))


def test_failing_probe_does_not_drain_the_queued_probes(monkeypatch):
    """A raising probe must abort the turn as FAST as the serial loop did -- it must not first wait out
    every probe already queued behind it.

    This is the pg-starvation shape RC4 measured: the probe that raises is a 300,000 ms statement timeout,
    and every queued probe behind it is another one. `with ThreadPoolExecutor(...)` calls shutdown(wait=True)
    on the way out of the block, so the 16 probes still queued behind a width-8 fan-out would run in two
    further waves -- a floor turn 3x SLOWER than the serial loop it replaced. _run_probes therefore owns the
    pool explicitly and shuts it down with cancel_futures.

    Pinned WITHOUT a stopwatch: with width 2, at most (2 running + the 1 that raised) probes may ever have
    STARTED. Under the `with` form all 7 start."""
    import threading

    gate, started = threading.Event(), []

    def retrieve(query, slice_, *, k, asof=None, near=None):
        if not slice_.startswith("drivers/"):
            return []
        started.append(slice_)
        if slice_ == _FROZEN[0]:
            raise RuntimeError("statement timeout")
        gate.wait(timeout=2.0)                                     # bounded, so a regression is slow not hung
        return []

    graph = _graph()
    sg = pl.grounded_subgraph("frost substitute", graph, embed=_embed,
                              route_fn=lambda q, gr: ["arabica"], tau=0.35, depth=2)
    monkeypatch.setattr(pl, "_PROBE_WORKERS", 2)
    try:
        with pytest.raises(RuntimeError, match="statement timeout"):
            pl.ground(sg, "frost substitute", graph, retrieve=retrieve, asof=_ASOF, probe_cap=24,
                      driver_slices=set(_A_DRIVERS) | set(_R_DRIVERS))
        assert len(started) <= 3 < len(_FROZEN)                    # queued probes were CANCELLED, not run
    finally:
        gate.set()                                                 # release the two in-flight workers


def test_width_one_takes_the_sequential_path(monkeypatch):
    """_PROBE_WORKERS<=1 must not build a pool at all -- hermetic callers keep the exact pre-F3 call
    pattern, and the knob stays a real kill-switch."""
    def _no_pool(*a, **k):
        raise AssertionError("width<=1 must not construct a ThreadPoolExecutor")

    monkeypatch.setattr(cf, "ThreadPoolExecutor", _no_pool)
    monkeypatch.setattr(pl, "_WALK_WORKERS", 1)                    # the evidence fill shares the executor
    r = _ground(monkeypatch, probe_cap=24, workers=1)
    assert r.probed == _FROZEN
