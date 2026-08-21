"""EC-2 BATCHED FILL READS -- the build's pin suite (no real Postgres, no AWS, no LLM).

THE IDIOM IS `tests/unit/test_pgstore.py`'s: a 1-slot pool, `psycopg.connect` monkeypatched to a dummy
object, and a cursor that RECORDS the SQL it was handed and replays canned tuples. Every claim EC-2 makes
about borrows is therefore counted, not asserted -- the same instrument the gate will read in-VPC
(`pgstore.borrow_ledger`) is what these tests read here.

WHAT THIS FILE PINS, in the order the item was built:
  * the SCATTER: one statement, many nodes, a per-node dict, and a node with no rows mapping to `[]`
    EXPLICITLY (the difference between "fetched, empty" and "not fetched" is the whole prefetch contract)
  * the CHUNK arithmetic: ceil(n/chunk) statements, ceil(n/chunk) borrows
  * the PER-CHUNK DEGRADE: a raising chunk OMITS its nodes so the CALLER re-fetches them at its own
    concurrency (the review's correction -- re-fetching them inside the batch serialized on the caller's
    thread what the fill pool runs `EVIDENCE_PG_POOL`-ways), and those per-node borrows are still COUNTED
    (a silently-degrading deploy must show up as a borrow count that never fell)
  * `candidates=` passthrough taking ZERO borrows -- the point of the exercise
  * THE RESIDENCY CONTRACT (`planner._Prefetch`): chunks pulled ON DEMAND by the fill workers, one
    statement per chunk however many workers race for it, rows DROPPED at their last consumer, and the
    whole handle emptied at the fill boundary -- a fill row is ~34-42 KB of live heap and an eager map of
    a wide walk measured 121.9 MB per concurrent turn
  * the `, id` TIEBREAK present in BOTH SQL builders, by source grep
  * THE DARK KNOB: with `GRAPHRAG_EVIDENCE_BATCH` off/absent, `_fill`'s call to the retriever is the
    shipped call, kwarg for kwarg (the recorded-call technique EC-3 used on `Queue.get`'s timeout)
  * the prefetch map is a LOCAL, never module state (workers-2/4 eval arms share one process)
  * a hermetic fake retriever that does not accept `candidates=` still works, knob ON
  * the LEDGER: fill vs rest, adoption across a worker, and two concurrent turns that do not blend
  * the flat-path refusal
"""
from __future__ import annotations

import functools
import inspect
import threading

import psycopg
import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as g
from leviathan.graphrag import pgstore as pg
from leviathan.graphrag import planner as pl

QV = [1.0, 0.0, 0.0, 0.0]
VEC = "[1.0,0.0,0.0,0.0]"


# ══ the fake pg: a cursor that records SQL and replays canned tuples ═════════════════════════════════
class _Cur:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, dict(params or {})))
        self._rows = self._conn.respond(sql, dict(params or {}))

    def fetchall(self):
        return self._rows


class _Conn:
    closed = False

    def __init__(self, respond):
        self.executed: list = []
        self.respond = respond

    def cursor(self):
        return _Cur(self)


def _is_batch(sql: str) -> bool:
    return "CROSS JOIN LATERAL" in sql


def _nodes_of(params: dict) -> list:
    """The node list a batch statement carried, in VALUES order."""
    return [params[f"n{i}"] for i in range(len(params)) if f"n{i}" in params]


def _row(node, i, *, with_vectors=True):
    payload = VEC if with_vectors else 0.5
    # Phase F: the projections gained a `meta` jsonb column (char_start/char_end/offset_kind ride it)
    # between text and payload -- the fake rows mirror the live tuple shape.
    return (node, f"{node}-{i}", "GAIN", f"s3://{node}/{i}", "2021-07-20", None, f"{node} row {i}", {}, payload)


@pytest.fixture()
def fake_pg(monkeypatch):
    """A 1-slot pool whose single connection is the recorder. Every borrow is a real `_acquire`, so the
    ledger counts exactly what serving would count."""
    holder: dict = {"conn": None}

    def make(respond):
        c = _Conn(respond)
        holder["conn"] = c
        monkeypatch.setattr(psycopg, "connect", lambda *a, **k: c)
        return c

    monkeypatch.setattr(pg, "_POOL", None)
    monkeypatch.setattr(pg, "_POOL_SIZE", 1)
    monkeypatch.setattr(pg, "_POOL_WAIT_S", 1)
    monkeypatch.setenv("EVIDENCE_PG_TABLE", "evidence_props")
    pg.close_borrow_ledger()
    yield make
    pg.close_borrow_ledger()
    pg._POOL = None


# ══ SCATTER ═════════════════════════════════════════════════════════════════════════════════════════
def test_the_batch_scatters_by_node_and_an_empty_node_maps_to_an_explicit_empty_list(fake_pg):
    """ONE statement, three nodes, and the node Postgres returned nothing for is PRESENT with `[]`.

    Presence is the contract `planner._fill` reads: `sp in prefetch` decides between passing
    `candidates=` and taking a legacy borrow, so a missing key would silently un-batch a node and an
    absent-vs-empty confusion would hand a node an empty evidence list it never asked for."""
    fake_pg(lambda sql, p: [_row("a", 0), _row("a", 1), _row("c", 0)])
    with pg.borrow_ledger() as led:
        out = pg.fetch_candidates_batch(QV, "frost", ["a", "b", "c"], asof="2021-08-01", fetch_k=60)
    assert set(out) == {"a", "b", "c"}
    assert out["b"] == []                                      # fetched, nothing there -- NOT absent
    assert [r["id"] for r in out["a"]] == ["a-0", "a-1"]        # scatter preserves SQL's row order
    assert [r["id"] for r in out["c"]] == ["c-0"]
    assert out["a"][0]["vector"] == QV and out["a"][0]["source_key"] == "s3://a/0"
    assert led["borrows"] == 1                                 # THREE nodes, ONE borrow


def test_the_batch_row_dict_is_the_single_node_row_dict(fake_pg):
    """Same keys, same values, both payload shapes -- the projection is literally shared (`_project`),
    which is what keeps the parity claim from decaying into two hand-written dicts drifting apart."""
    for with_vectors in (True, False):
        fake_pg(lambda sql, p: ([_row("a", 0, with_vectors=with_vectors)] if _is_batch(sql)
                                else [_row("a", 0, with_vectors=with_vectors)[1:]]))
        b = pg.fetch_candidates_batch(QV, "frost", ["a"], asof=None, fetch_k=60, with_vectors=with_vectors)
        s = pg.fetch_candidates(QV, "frost", "a", asof=None, fetch_k=60, with_vectors=with_vectors)
        assert b["a"] == s


def test_a_node_the_values_list_never_carried_still_lands(fake_pg):
    """Defensive scatter: a stray leading node cannot raise and cannot be dropped on the floor."""
    fake_pg(lambda sql, p: [_row("zz", 0)])
    out = pg.fetch_candidates_batch(QV, "frost", ["a"], asof=None, fetch_k=60)
    assert out["a"] == [] and [r["id"] for r in out["zz"]] == ["zz-0"]


# ══ CHUNK ARITHMETIC ════════════════════════════════════════════════════════════════════════════════
def test_chunking_is_ceil_n_over_chunk_statements_and_the_same_number_of_borrows(fake_pg):
    conn = fake_pg(lambda sql, p: [])
    nodes = ["a", "b", "c", "d", "e"]
    with pg.borrow_ledger() as led:
        out = pg.fetch_candidates_batch(QV, "frost", nodes, asof=None, fetch_k=60, chunk=2)
    assert len(conn.executed) == 3 == led["borrows"]            # ceil(5/2)
    assert [_nodes_of(p) for _, p in conn.executed] == [["a", "b"], ["c", "d"], ["e"]]
    assert set(out) == set(nodes) and all(v == [] for v in out.values())


def test_the_shipped_chunk_default_matches_the_recorded_payload_arithmetic():
    """20 x ~700 KB ~= 14 MB per statement -- inside the <=15-20 MB target the docstring states, and the
    number a later reader will check the arithmetic against.

    AND THE LIVE-HEAP HALF IS RECORDED TOO (the review's correction): the wire figure is not a residency
    bound, `_BATCH_CHUNK` bounds a STATEMENT and cannot bound a map the caller accumulates, and the
    caller that enforces the residency contract is NAMED so the next reader does not have to find it."""
    src = inspect.getsource(pg).split("_BATCH_CHUNK = 20")[0][-4000:]
    assert pg._BATCH_CHUNK == 20
    assert "700 KB" in src
    assert "LIVE HEAP" in src and "planner._Prefetch" in src


def test_a_duplicate_node_is_asked_for_once_and_an_empty_list_is_a_no_op(fake_pg):
    conn = fake_pg(lambda sql, p: [])
    pg.fetch_candidates_batch(QV, "frost", ["a", "a", "b"], asof=None, fetch_k=60)
    assert _nodes_of(conn.executed[0][1]) == ["a", "b"]
    assert pg.fetch_candidates_batch(QV, "frost", [], asof=None, fetch_k=60) == {}
    assert len(conn.executed) == 1


def test_the_asof_leakage_filter_rides_every_leg_of_the_batch(fake_pg):
    """PIT SAFETY IS THE LAW (the EC-2 spec's word). The filter must be SERVER-SIDE and per-node on both
    the dense and the lexical legs -- exactly as in the single-node statement."""
    conn = fake_pg(lambda sql, p: [])
    pg.fetch_candidates_batch(QV, "B40 mandate", ["a", "b"], asof="2021-08-01", fetch_k=60, hybrid=True)
    sql, params = conn.executed[0]
    assert params["asof"] == "2021-08-01"
    assert sql.count("date <= %(asof)s") == 2                  # dense leg + lexical leg
    assert sql.count("node = q.node") == 2                     # ...and both are node-scoped
    conn.executed.clear()
    pg.fetch_candidates_batch(QV, "frost", ["a"], asof=None, fetch_k=60, hybrid=False)
    assert "asof" not in conn.executed[0][0]                   # no as-of -> no filter, same as today


# ══ PER-CHUNK DEGRADE ═══════════════════════════════════════════════════════════════════════════════
def test_a_raising_chunk_omits_its_nodes_so_the_caller_refetches_them_at_its_own_concurrency(fake_pg):
    """DEGRADE, NEVER FLOOR -- AND NEVER SERIALIZE. The first chunk's statement blows up; its two nodes
    are ABSENT from the map and NO legacy statement is issued here. The SECOND chunk still batches.

    THE REVIEW'S CORRECTION, pinned: the first build re-fetched the failed chunk's nodes inside this
    function, i.e. up to `chunk` legacy statements STRICTLY SEQUENTIALLY on whatever thread called the
    batch -- while the path they degrade back to (`planner._fill` inside `_parallel_fill`) issues exactly
    those statements `EVIDENCE_PG_POOL`-ways concurrent, each one otherwise free to wait `_POOL_WAIT_S`
    alone. Absence is the whole signal: `planner._fill`'s omit-when-absent kwarg re-fetches them where the
    walk's concurrency lives, and those borrows are still counted there."""
    calls = {"n": 0}

    def respond(sql, p):
        if _is_batch(sql):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("no such operator (a plan the server disliked)")
            return [_row("c", 0)]
        raise AssertionError("the batch must NOT issue a legacy statement on the caller's thread")

    conn = fake_pg(respond)
    with pg.borrow_ledger() as led:
        out = pg.fetch_candidates_batch(QV, "frost", ["a", "b", "c"], asof=None, fetch_k=60, chunk=2)
    assert set(out) == {"c"}                                   # "a"/"b" ABSENT -> "not fetched"
    assert [r["id"] for r in out["c"]] == ["c-0"]
    assert [_is_batch(s) for s, _ in conn.executed] == [True, True]
    assert led["borrows"] == 2                                 # the failed chunk's borrow is still counted


def test_the_raising_chunk_writes_nothing_at_all(fake_pg):
    """`_batch_rows` is split out so a chunk that raises has NOT written a partial scatter -- half a
    chunk's rows plus the caller's own re-fetch would double rows into the same node."""
    fake_pg(lambda sql, p: (_ for _ in ()).throw(RuntimeError("boom")))
    out = pg.fetch_candidates_batch(QV, "frost", ["a"], asof=None, fetch_k=60)
    assert out == {}                                           # no key, no partial rows, no exception


# ══ candidates= PASSTHROUGH ═════════════════════════════════════════════════════════════════════════
def test_candidates_passthrough_returns_verbatim_and_takes_no_borrow(fake_pg):
    conn = fake_pg(lambda sql, p: [_row("a", 99)[1:]])
    rows = [{"id": "a-0", "source": "GAIN", "source_key": "s3://a/0", "date": "2021-07-20",
             "event_date": None, "text": "a row 0", "vector": QV}]
    with pg.borrow_ledger() as led:
        got = pg.fetch_candidates(QV, "frost", "a", asof="2021-08-01", fetch_k=60, candidates=rows)
    assert got == rows and got[0] is rows[0]                    # the SAME row objects, not a re-render
    assert got is not rows                                     # ...but not the caller's list object
    assert led["borrows"] == 0 and conn.executed == []          # no pool, no cursor, no SQL


def test_pg_retrieve_threads_candidates_and_still_runs_the_whole_post_fetch_pipeline(fake_pg, monkeypatch):
    """EC-2 moves WHERE rows come from and NOTHING about what happens to them: the same proximity score,
    the same order, the same output projection as the borrowing path on identical rows."""
    rows = [{"id": "a-0", "source": "GAIN", "source_key": "s3://a/0", "date": "2021-07-20",
             "event_date": None, "text": "frost hit", "vector": [1.0, 0.0, 0.0, 0.0]},
            {"id": "a-1", "source": "FRED", "source_key": "s3://a/1", "date": "2021-05-01",
             "event_date": None, "text": "dollar note", "vector": [0.0, 1.0, 0.0, 0.0]}]
    conn = fake_pg(lambda sql, p: [(r["id"], r["source"], r["source_key"], r["date"], r["event_date"],
                                    r["text"], {}, pg._vec_lit(r["vector"])) for r in rows])
    fake_embed = lambda t, **k: [QV for _ in t]                # noqa: E731
    borrowed = pg.pg_retrieve("frost", "a", k=2, asof=None, mmr=0.5, embed=fake_embed)
    conn.executed.clear()
    with pg.borrow_ledger() as led:
        prefetched = pg.pg_retrieve("frost", "a", k=2, asof=None, mmr=0.5, embed=fake_embed,
                                    candidates=[dict(r) for r in rows])
    assert prefetched == borrowed
    assert led["borrows"] == 0 and conn.executed == []


def test_a_mismatched_payload_shape_drops_the_prefetch_instead_of_flooring(fake_pg):
    """The guard: probe-shaped rows (`score`, no `vector`) handed to a vector-consuming arm are DISCARDED
    and the node takes one honest borrow, rather than raising a KeyError out of `_dense` mid-walk."""
    conn = fake_pg(lambda sql, p: [(f"a-{i}", "GAIN", f"s3://a/{i}", "2021-07-20", None, "t", {}, VEC)
                                   for i in range(2)])
    cheap = [{"id": "a-0", "source": "GAIN", "source_key": "s3://a/0", "date": "2021-07-20",
              "event_date": None, "text": "t", "score": 0.5}]
    with pg.borrow_ledger() as led:
        out = pg.pg_retrieve("frost", "a", k=2, asof=None, mmr=0.5, embed=lambda t, **k: [QV for _ in t],
                             candidates=cheap)
    assert len(out) == 2 and led["borrows"] == 1 and len(conn.executed) == 1


# ══ THE TIEBREAK ════════════════════════════════════════════════════════════════════════════════════
def test_the_id_tiebreak_is_present_in_BOTH_sql_builders():
    """RRF ties are real and fetch order is load-bearing, so without a total order the parity pin would
    be measuring Postgres' plan choice. Both builders, same commit, every ordering."""
    for fn in (pg.fetch_candidates, pg._batch_rows):
        src = inspect.getsource(fn)
        assert "vector <=> %(qv)s::vector, id) AS rnk" in src           # dense ROW_NUMBER
        assert "ORDER BY vector <=> %(qv)s::vector, id LIMIT" in src    # dense LIMIT
        assert "DESC, id) " in src                                      # lexical ROW_NUMBER
        assert "ORDER BY rnk LIMIT %(k)s" in src                        # lexical LIMIT (had NO order at all)
        assert "ORDER BY f.score DESC, p.id LIMIT" in src               # the fused final order
        assert "ORDER BY d.rnk, p.id LIMIT" in src                      # ...and the dense-only shape


# ══ THE BORROW LEDGER ═══════════════════════════════════════════════════════════════════════════════
def test_the_ledger_counts_borrows_and_is_absent_by_default(fake_pg):
    fake_pg(lambda sql, p: [])
    assert pg.current_borrow_ledger() is None                  # nothing installed -> `_acquire` is untouched
    c = pg._acquire()
    pg._release(c)
    with pg.borrow_ledger() as led:
        for _ in range(3):
            pg._release(pg._acquire())
    assert led["borrows"] == 3
    assert pg.current_borrow_ledger() is None                  # restored on exit


def test_two_concurrent_turns_do_not_blend_their_ledgers(fake_pg):
    """The thread-local is what makes the count PER TURN on a threaded server and in a --workers 4 eval
    process. Two threads, two ledgers, different borrow counts, no leakage either way."""
    fake_pg(lambda sql, p: [])
    seen: dict = {}
    ready = threading.Barrier(2)

    def turn(name, n):
        with pg.borrow_ledger() as led:
            ready.wait()
            for _ in range(n):
                pg._release(pg._acquire())
            seen[name] = led["borrows"]

    ts = [threading.Thread(target=turn, args=("a", 2)), threading.Thread(target=turn, args=("b", 5))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert seen == {"a": 2, "b": 5}


def test_a_worker_counts_into_the_parent_ledger_only_after_it_adopts(fake_pg):
    """The EC-3 propagation shape, one thread-local over: a bare worker's borrows vanish, an adopting
    worker's land in the turn's own count. Both pools capture on the parent for exactly this reason."""
    fake_pg(lambda sql, p: [])
    with pg.borrow_ledger() as led:
        parent = pg.current_borrow_ledger()

        def bare():
            pg._release(pg._acquire())

        def adopts():
            with pg.adopt_borrow_ledger(parent):
                pg._release(pg._acquire())
            assert pg.current_borrow_ledger() is None           # cleaned up on the worker

        for fn in (bare, adopts):
            t = threading.Thread(target=fn)
            t.start()
            t.join()
        assert led["borrows"] == 1                              # the adopting worker's, not the bare one's


def test_the_capture_carries_the_ledger_beside_the_deadline():
    """ONE capture for both thread-locals -- the reason the tuple grew instead of a second helper being
    added: a future pool seam that remembers one and forgets the other fails SILENTLY."""
    pg.close_borrow_ledger()
    mod, dl, ledger = pl._capture_parent_patience()
    assert mod is pg and dl is None and ledger is None
    with pg.borrow_ledger() as led:
        _mod, _dl, ledger = pl._capture_parent_patience()
        assert ledger is led
        seen: dict = {}

        def worker():
            with pl._adopt_parent(None, None, _mod, None, ledger):
                seen["in"] = pg.current_borrow_ledger()
            seen["out"] = pg.current_borrow_ledger()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        assert seen == {"in": led, "out": None}


def test_adopt_is_nested_safe_on_the_sequential_branch(fake_pg):
    """Both pools have a sequential branch that runs on the CALLER's thread, where install-and-clear
    would strip the region's own ledger mid-walk."""
    fake_pg(lambda sql, p: [])
    with pg.borrow_ledger() as led:
        other = {"borrows": 0}
        with pg.adopt_borrow_ledger(other):                     # already carrying one -> keeps it
            pg._release(pg._acquire())
        assert led["borrows"] == 1 and other["borrows"] == 0
        assert pg.current_borrow_ledger() is led


def test_a_leaked_ledger_is_replaced_not_accumulated():
    """`planner.ground` opens/closes rather than nesting a `with` around 320 lines, so a mid-walk
    exception can leave a ledger installed on a pooled serving thread. Replace-don't-nest is what makes
    that harmless: the next turn's open throws the stale dict away."""
    stale = pg.open_borrow_ledger()
    stale["borrows"] = 99
    fresh = pg.open_borrow_ledger()
    assert fresh is not stale and fresh["borrows"] == 0
    assert pg.close_borrow_ledger() == 0 and pg.close_borrow_ledger() is None


# ══ THE PLANNER SEAM: the dark knob, the omit-when-absent kwarg, the local map ═══════════════════════
_KW = ["frost", "substitute", "drought", "rain", "climate", "el", "nino", "damage", "demand"]


def _embed(texts, **k):
    return [[1.0 if kw in t.lower() else 0.0 for kw in _KW] for t in texts]


def _graph() -> g.CausalGraph:
    def _d(id, mech, **o):
        return cs.Driver(id=id, type=o.pop("type", "hazard"), sign=o.pop("sign", "+"), mechanism=mech, **o)

    arabica = cs.CausalContract(
        contract="arabica", aliases=["arabica"],
        drivers=[_d("el_nino", "el nino frost", type="climate_driver"),
                 _d("frost", "frost damage", parents=["el_nino"]),
                 _d("rain", "rain only", sign="-", type="climate_driver")],
        convergence=[cs.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=1,
                                          drivers=["frost", "el_nino"])])
    return g.CausalGraph({"arabica": arabica}, silver=set())


def _sg(gr):
    return pl.grounded_subgraph("frost substitute", gr, embed=_embed,
                                route_fn=lambda q, graph: ["arabica"], tau=0.35, depth=2)


class _Recorder:
    """A hermetic fake retriever that does NOT accept `candidates=` -- the injected-double contract."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, query, slice_, *, k, asof=None, near=None):
        self.calls.append({"slice": slice_, "k": k, "asof": asof, "near": near})
        return [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{slice_}", "text": "row"}]


def _ground(rec, **kw):
    gr = _graph()
    sg = _sg(gr)
    pl.ground(sg, "frost substitute", gr, retrieve=rec, silver_lookup=None,
              driver_slices={"frost", "el_nino", "rain"}, **kw)
    return sg


def test_the_knob_is_off_by_default_and_the_fill_call_is_the_shipped_call(monkeypatch):
    """EC-2 SHIPS DARK. With the knob absent, `_fill` calls the retriever with EXACTLY the four shipped
    keyword arguments and no `candidates` -- recorded, not inferred."""
    monkeypatch.delenv("GRAPHRAG_EVIDENCE_BATCH", raising=False)
    assert pl._ec2_enabled() is False
    rec = _Recorder()
    _ground(rec)
    assert rec.calls and all(set(c) == {"slice", "k", "asof", "near"} for c in rec.calls)


def test_a_hermetic_fake_retriever_never_sees_the_kwarg_even_with_the_knob_on(monkeypatch):
    """GATE (2): the prefetch only ever runs for the REAL `ev.retrieve`. An injected double is hermetic
    by contract -- it may not accept `candidates=`, and handing it one would be a TypeError mid-walk."""
    monkeypatch.setenv("GRAPHRAG_EVIDENCE_BATCH", "1")
    monkeypatch.setenv("EVIDENCE_BACKEND", "pg")
    rec = _Recorder()
    sg = _ground(rec)
    assert rec.calls and all("candidates" not in c for c in rec.calls)
    assert sg.trace["pool_borrows"] == {"fill": 0, "rest": 0}


def test_the_knob_grammar_and_the_three_gates(monkeypatch):
    monkeypatch.setenv("EVIDENCE_BACKEND", "pg")
    for raw, want in [("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
                      ("0", False), ("false", False), ("", False), ("maybe", False)]:
        monkeypatch.setenv("GRAPHRAG_EVIDENCE_BATCH", raw)
        assert pl._ec2_enabled() is want, raw
    gr = _graph()
    sg = _sg(gr)
    fs = lambda n: "arabica"                                   # noqa: E731 — every node eligible
    monkeypatch.setenv("GRAPHRAG_EVIDENCE_BATCH", "0")
    assert pl._ec2_prefetch(sg, "q", None, ev.retrieve, fs) is None          # gate (1)
    monkeypatch.setenv("GRAPHRAG_EVIDENCE_BATCH", "1")
    assert pl._ec2_prefetch(sg, "q", None, _Recorder(), fs) is None          # gate (2)
    monkeypatch.setenv("EVIDENCE_BACKEND", "flat")
    assert pl._ec2_prefetch(sg, "q", None, ev.retrieve, fs) is None          # gate (3)


def test_a_prefetch_failure_returns_none_and_the_walk_takes_the_shipped_path(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_EVIDENCE_BATCH", "1")
    monkeypatch.setenv("EVIDENCE_BACKEND", "pg")
    monkeypatch.setattr(ev, "embed", lambda t, **k: (_ for _ in ()).throw(RuntimeError("no embedder")))
    gr = _graph()
    assert pl._ec2_prefetch(_sg(gr), "q", None, ev.retrieve, lambda n: "arabica") is None


# ── the wired path: knob ON, real ev.retrieve partial, pg backend ────────────────────────────────────
@pytest.fixture()
def wired(monkeypatch):
    """The serving shape with the two pg leaves faked: `fetch_candidates_batch` returns a sentinel map,
    `pg_retrieve` records what `candidates=` it was handed."""
    monkeypatch.setenv("GRAPHRAG_EVIDENCE_BATCH", "1")
    monkeypatch.setenv("EVIDENCE_BACKEND", "pg")
    monkeypatch.setattr(ev, "embed", lambda t, **k: [QV for _ in t])
    seen: dict = {"batch": [], "retrieve": []}

    def fake_batch(qv, qt, nodes, **kw):
        seen["batch"].append({"nodes": list(nodes), **kw})
        return {n: [{"id": f"{n}-0", "vector": QV}] for n in nodes}

    def fake_pg_retrieve(query, node, **kw):
        seen["retrieve"].append({"node": node, "candidates": kw.get("candidates")})
        return [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{node}", "text": "row",
                 "event_date": None, "event_date_precision": None, "score": 1.0}]

    monkeypatch.setattr(pg, "fetch_candidates_batch", fake_batch)
    monkeypatch.setattr(pg, "pg_retrieve", fake_pg_retrieve)
    return seen


def test_the_wired_prefetch_batches_every_eligible_slice_once_and_threads_it_to_each_node(wired):
    """THE ITEM, end to end: ONE batched call over the DISTINCT slices in CONSUMPTION order, and each
    node's own rows handed to its retrieve -- so the borrowing that used to be per-node happened once."""
    retr = functools.partial(ev.retrieve, mode="hybrid", rerank=True, mmr=0.5, fairness=0.3)
    gr = _graph()
    sg = _sg(gr)
    pl.ground(sg, "frost substitute", gr, retrieve=retr, silver_lookup=None,
              driver_slices={"frost", "el_nino", "rain"}, probe_cap=0)
    assert len(wired["batch"]) == 1
    call = wired["batch"][0]
    assert call["nodes"] and len(call["nodes"]) == len(set(call["nodes"]))   # deduped
    assert call["hybrid"] is True and call["with_vectors"] is True      # read off the partial's knobs
    assert call["chunk"] == len(call["nodes"])                          # ONE statement for the chunk
    assert wired["retrieve"] and all(c["candidates"] is not None for c in wired["retrieve"])
    for c in wired["retrieve"]:
        assert c["candidates"] == [{"id": f"{c['node']}-0", "vector": QV}]


def test_the_chunks_are_pulled_by_the_fill_and_nothing_is_fetched_before_it(wired, monkeypatch):
    """RESIDENCY + CONCURRENCY, at the seam: `_ec2_prefetch` fetches NOTHING on the turn's thread, the
    chunks are pulled from inside `_parallel_fill`, and the plan is chunked by `pgstore._BATCH_CHUNK`.

    The first build issued ceil(width/20) statements serially on the caller's thread BEFORE any worker
    started, and held every slice's rows -- 1024 raw floats a row -- until `ground()` returned."""
    monkeypatch.setattr(pg, "_BATCH_CHUNK", 1)                 # every slice its own chunk
    order: list = []
    real_fill, real_batch = pl._parallel_fill, pg.fetch_candidates_batch
    monkeypatch.setattr(pl, "_parallel_fill", lambda *a, **k: (order.append("fill"), real_fill(*a, **k))[1])
    monkeypatch.setattr(pg, "fetch_candidates_batch",
                        lambda *a, **k: (order.append("batch"), real_batch(*a, **k))[1])
    retr = functools.partial(ev.retrieve, mode="hybrid", rerank=True, mmr=0.5)
    gr = _graph()
    sg = _sg(gr)
    pl.ground(sg, "frost substitute", gr, retrieve=retr, silver_lookup=None,
              driver_slices={"frost", "el_nino", "rain"}, probe_cap=0)
    n_slices = len({c["node"] for c in wired["retrieve"]})
    assert n_slices > 1
    assert len(wired["batch"]) == n_slices                     # one statement per chunk, chunk == 1 slice
    assert all(len(b["nodes"]) == 1 for b in wired["batch"])
    assert order and order[0] == "fill"                        # NOT ONE statement before the fill started
    assert order.count("batch") == n_slices


def test_the_prefetch_map_is_a_local_and_never_module_state(wired):
    """--workers 2/4 eval arms share ONE process. A module-level prefetch would let two concurrent turns
    -- different queries, different as-ofs -- read each other's evidence: a wrong-answer bug and a PIT
    bug at once. Pinned by looking for the map anywhere in the planner module's namespace."""
    retr = functools.partial(ev.retrieve, mode="hybrid", rerank=True, mmr=0.5)
    gr = _graph()
    sg = _sg(gr)
    pl.ground(sg, "frost substitute", gr, retrieve=retr, silver_lookup=None,
              driver_slices={"frost", "el_nino", "rain"}, probe_cap=0)
    handed = {id(c["candidates"]) for c in wired["retrieve"]}
    assert handed
    for name, val in list(vars(pl).items()):
        if isinstance(val, dict) and any(k in val for k in ("arabica", "drivers/frost")):
            raise AssertionError(f"planner.{name} is holding a prefetch map")


def test_a_slice_the_batch_could_not_serve_takes_its_own_borrow(wired, monkeypatch):
    """OMIT-WHEN-ABSENT is a degrade path too: a node missing from the map gets no `candidates=` kwarg
    at all and falls through to the ordinary per-node fetch."""
    monkeypatch.setattr(pg, "fetch_candidates_batch", lambda qv, qt, nodes, **kw: {})
    retr = functools.partial(ev.retrieve, mode="hybrid", rerank=True, mmr=0.5)
    gr = _graph()
    sg = _sg(gr)
    pl.ground(sg, "frost substitute", gr, retrieve=retr, silver_lookup=None,
              driver_slices={"frost", "el_nino", "rain"}, probe_cap=0)
    assert wired["retrieve"] and all(c["candidates"] is None for c in wired["retrieve"])


# ══ THE RESIDENCY CONTRACT: _Prefetch ═══════════════════════════════════════════════════════════════
def _handle(wants, *, chunk=2, fetch=None, calls=None):
    def _f(part):
        if calls is not None:
            calls.append(list(part))
        return {n: [{"id": f"{n}-0", "vector": QV}] for n in part}

    return pl._Prefetch(fetch or _f, list(wants), wants, chunk=chunk)


def test_a_slices_rows_are_dropped_by_its_last_consumer(monkeypatch):
    """THE RESIDENCY FIX. A fill row is ~34-42 KB of live heap (1024 boxed floats); an eager map of every
    slice a wide walk touches measured 121.9 MB live at 60 slices and ~242 MB at the ceiling, PER
    CONCURRENT TURN, alive until `ground()` returned. Here the map shrinks as it is read: a slice two
    nodes share survives the first take and is GONE after the second."""
    h = _handle({"a": 2, "b": 1})
    first = h.take("a")
    assert [r["id"] for r in first] == ["a-0"]
    assert "a" in h._ready                                     # a second node still wants it
    assert h.take("a") is first                                # the SAME rows, not a re-fetch
    assert "a" not in h._ready                                 # ...and now dropped
    assert h.take("a") is None                                 # a third asker takes its own borrow
    h.take("b")
    assert h._ready == {}                                      # nothing survives a fully-consumed fill


def test_close_empties_the_handle_and_a_straggler_take_returns_none():
    h = _handle({"a": 2})
    h.take("a")
    h.close()
    assert h._ready == {} and h._want == {} and h._chunks == []
    assert h.take("a") is None                                 # cannot re-populate after the boundary
    h.close()                                                  # idempotent


def test_only_the_chunk_a_worker_asks_for_is_fetched():
    calls: list = []
    h = _handle({"a": 1, "b": 1, "c": 1, "d": 1, "e": 1}, chunk=2, calls=calls)
    h.take("c")
    assert calls == [["c", "d"]]                               # chunk 2 only -- a/b/e never touched pg
    h.take("d")
    assert calls == [["c", "d"]]                               # ...and its chunk-mate rides it


def test_racing_workers_issue_ONE_statement_for_a_chunk():
    """The wait path: N workers wanting the same chunk borrow ONCE. Without it the batch would issue the
    same statement per worker and gate (a)'s borrow count would be a lie in the wrong direction."""
    started, release, calls = threading.Event(), threading.Event(), []

    def _slow(part):
        calls.append(list(part))
        started.set()
        release.wait(5)
        return {n: [{"id": f"{n}-0"}] for n in part}

    h = _handle({"a": 1, "b": 1}, chunk=2, fetch=_slow)
    got: dict = {}
    t = threading.Thread(target=lambda: got.__setitem__("b", h.take("b")))
    t2 = threading.Thread(target=lambda: got.__setitem__("a", h.take("a")))
    t.start()
    assert started.wait(5)
    t2.start()                                                 # arrives while the chunk is "fetching"
    release.set()
    t.join(5), t2.join(5)
    assert len(calls) == 1
    assert [r["id"] for r in got["a"]] == ["a-0"] and [r["id"] for r in got["b"]] == ["b-0"]


def test_a_raising_chunk_returns_none_for_all_its_slices_and_is_not_retried():
    """Fail-open, and ONCE: the nodes take their own borrows in their own workers (which is where today's
    concurrency lives), and the chunk is not re-attempted by every one of them in turn."""
    calls: list = []

    def _boom(part):
        calls.append(list(part))
        raise RuntimeError("a plan the server disliked")

    h = _handle({"a": 1, "b": 1}, chunk=2, fetch=_boom)
    assert h.take("a") is None and h.take("b") is None
    assert calls == [["a", "b"]]


def test_a_served_but_empty_slice_is_not_a_borrow():
    """`[]` (fetched, nothing there) must stay distinguishable from None (not fetched): one hands the
    retriever `candidates=[]` and takes no borrow, the other omits the kwarg and takes one."""
    h = _handle({"a": 1}, chunk=2, fetch=lambda part: {n: [] for n in part})
    assert h.take("a") == []


# ══ THE FLAT-PATH REFUSAL ═══════════════════════════════════════════════════════════════════════════
def test_the_flat_path_refuses_prefetched_rows(monkeypatch):
    """RAISED, not ignored: pg rows cannot be scored by the flat path, and a silent ignore would mean a
    caller believing it had batched while every node re-scanned its whole slice."""
    monkeypatch.delenv("EVIDENCE_BACKEND", raising=False)
    recs = [{"date": "2021-07-20", "source": "GAIN", "source_key": "s3://a", "text": "frost",
             "vector": [1.0, 0.0], "backend": "bge"}]
    with pytest.raises(ValueError, match="pg-backend argument"):
        ev.retrieve("frost", "arabica", k=1, records=recs, candidates=[{"id": "x"}])
    monkeypatch.setenv("EVIDENCE_BACKEND", "pg")               # ...and `records=` still wins on pg
    with pytest.raises(ValueError, match="pg-backend argument"):
        ev.retrieve("frost", "arabica", k=1, records=recs, candidates=[{"id": "x"}])


def test_the_trace_stamps_pool_borrows_beside_ground_ms(monkeypatch):
    """Gate (a)'s read lands on the same two boundaries as gate (c)'s."""
    monkeypatch.delenv("GRAPHRAG_EVIDENCE_BATCH", raising=False)
    sg = _ground(_Recorder())
    assert set(sg.trace["pool_borrows"]) == {"fill", "rest"} == set(sg.trace["ground_ms"])
