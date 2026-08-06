"""F2 -- the CONDITIONAL vector payload on pgstore's retrieve path (hermetic: a fake conn captures the SQL).

The convergence probes (rerank=False, mmr<=0) consumed nothing but the cosine ORDER, yet every probe shipped
60 x 1024 float4 rendered as text (~700 KB), parsed all of it, and then ran a pure-Python cosine over it --
TWICE per candidate. What is pinned here:

  * the no-vector SQL shape is chosen EXACTLY when the caller consumes no vectors, and the vector shape
    otherwise -- including on NEAR-DATED turns, where the originally-proposed `near is None` gate would have
    made F2 a silent no-op (proximity needs only the row's `date`, which both shapes return);
  * the two SQL shapes differ in the payload column and NOTHING else (leakage filter, CTEs, fusion, LIMIT);
  * fetch_candidates' six metadata columns are identical across the shapes, and the SQL `score` reproduces
    ev._cosine;
  * pg_retrieve's OWN return rows are key/type identical across the shapes, and content-identical on a
    probe-shaped arm -- so no caller can tell which payload ran;
  * the score is evaluated ONCE per candidate, not twice.
"""
from __future__ import annotations

import os

import pytest
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import pgstore as pg

# 4-dim fake props: axis 0 = "frost-ness", axis 1 = "dollar-ness". Kept in the SQL's own ORDER BY order.
_META = [("i1", "GAIN", "s3://g1", "2021-07-20", None, "July frost hit Sul de Minas"),
         ("i2", "WASDE", "s3://w1", "2021-06-10", None, "stocks steady in June"),
         ("i3", "FRED", "s3://f1", "2021-05-01", None, "dollar strengthened broadly")]
_VECS = ["[1.0,0.0,0.0,0.0]", "[0.8,0.1,0.0,0.0]", "[0.0,1.0,0.0,0.0]"]
_QV = [1.0, 0.0, 0.0, 0.0]
_NOVEC = "1 - (p.vector <=> %(qv)s::vector) AS cos_score"


def _embed(texts, **kw):
    return [list(_QV) for _ in texts]


class _Cur:
    """Serves whichever 7th column the captured SQL asked for -- the scalar branch returns exactly what
    pgvector would (`1 - cosine_distance`), so a shape difference can never hide behind a value difference."""

    def __init__(self, sink):
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self._sink["sql"], self._sink["params"] = sql, params

    def fetchall(self):
        vec = "p.vector::text" in self._sink["sql"]
        return [m + ((v,) if vec else (ev._cosine(_QV, pg._vec_parse(v)),)) for m, v in zip(_META, _VECS)]


class _Conn:
    def __init__(self):
        self.sink: dict = {}

    def cursor(self):
        return _Cur(self.sink)


@pytest.fixture()
def no_model(monkeypatch):
    """Stub the cross-encoder so the rerank arm is exercisable without loading bge (order = fetch order)."""
    from leviathan.graphrag import rankers as rk
    monkeypatch.setattr(rk, "rerank_scores", lambda q, texts: [float(len(texts) - i) for i in range(len(texts))])


# -- (a) the gate: which SQL shape, and exactly when ------------------------------------------------------
def test_needs_vectors_is_rerank_or_positive_mmr():
    assert pg.needs_vectors(rerank=False, mmr=0.0) is False
    assert pg.needs_vectors(rerank=False, mmr=-1.0) is False      # mmr<=0 is the documented "off" form
    assert pg.needs_vectors(rerank=True, mmr=0.0) is True
    assert pg.needs_vectors(rerank=False, mmr=0.5) is True


@pytest.mark.parametrize("kw,wants_vector", [
    ({}, False),                                                  # ev.retrieve defaults == the probe arm
    ({"mode": "hybrid"}, False),                                  # probe_retr's actual kwargs (answer.py:793)
    ({"mode": "hybrid", "near": "2021-07-01"}, False),            # NEAR-DATED: must NOT fall back to vectors
    ({"near": "2021"}, False),                                    # year-form near, same
    ({"mmr": 0.5}, True),
    ({"rerank": True}, True),
    ({"mode": "hybrid", "rerank": True, "mmr": 0.5}, True),       # the fill arm (answer._RETRIEVAL)
])
def test_payload_sql_shape_follows_the_gate(kw, wants_vector, no_model):
    c = _Conn()
    pg.pg_retrieve("frost", "coffee", k=2, asof="2021-08-01", embed=_embed, conn=c, **kw)
    sql = c.sink["sql"]
    assert ("p.vector::text" in sql) is wants_vector
    assert (_NOVEC in sql) is (not wants_vector)


def test_only_the_payload_column_differs_between_the_shapes():
    """Structural proof that F2 touched nothing else: with the payload column masked out, the two SQL
    strings are equal -- so the `date <= asof` leakage guard, both CTEs, the RRF fusion and the LIMITs are
    provably identical on the probe path."""
    a, b = _Conn(), _Conn()
    pg.pg_retrieve("frost damage", "coffee", k=2, asof="2021-08-01", mode="hybrid", embed=_embed, conn=a)
    pg.pg_retrieve("frost damage", "coffee", k=2, asof="2021-08-01", mode="hybrid", mmr=0.5, embed=_embed, conn=b)
    assert a.sink["sql"].replace(_NOVEC, "@P@") == b.sink["sql"].replace("p.vector::text", "@P@")
    assert a.sink["params"] == b.sink["params"]                   # same bind params, including the qv literal


# -- (b) row-dict parity: fetch_candidates rows and pg_retrieve rows -------------------------------------
def test_fetch_candidates_metadata_identical_and_score_reproduces_cosine():
    rich = pg.fetch_candidates(_QV, "frost", "coffee", asof="2021-08-01", fetch_k=10, hybrid=False,
                               conn=_Conn(), with_vectors=True)
    cheap = pg.fetch_candidates(_QV, "frost", "coffee", asof="2021-08-01", fetch_k=10, hybrid=False,
                                conn=_Conn(), with_vectors=False)
    meta = ("id", "source", "source_key", "date", "event_date", "text")
    assert [{k: r[k] for k in meta} for r in rich] == [{k: r[k] for k in meta} for r in cheap]
    assert [set(r) - set(meta) for r in rich] == [{"vector"}] * len(_META)
    assert [set(r) - set(meta) for r in cheap] == [{"score"}] * len(_META)
    for r, c in zip(rich, cheap):
        assert isinstance(c["score"], float)
        assert c["score"] == pytest.approx(ev._cosine(_QV, r["vector"]))


def test_pg_retrieve_return_rows_are_key_and_type_identical_across_shapes(no_model):
    cheap = pg.pg_retrieve("frost", "coffee", k=3, asof="2021-08-01", embed=_embed, conn=_Conn())
    rich = pg.pg_retrieve("frost", "coffee", k=3, asof="2021-08-01", rerank=True, embed=_embed, conn=_Conn())
    assert cheap and rich
    assert [set(r) for r in cheap] == [set(r) for r in rich]
    assert ([{k: type(v) for k, v in r.items()} for r in cheap]
            == [{k: type(v) for k, v in r.items()} for r in rich])
    assert "vector" not in cheap[0]                               # the PAYLOAD never leaks to the caller
    # D-DV-2: `score` is now a DELIBERATE output key on both shapes -- the FINAL relevance the row was
    # ranked on (rerank score on the rich arm, fused dense+proximity on the cheap one), not the raw SQL
    # candidate column it shadows. It is what the planner's score-aware cap reads.
    assert isinstance(cheap[0]["score"], float) and isinstance(rich[0]["score"], float)


@pytest.mark.parametrize("near", [None, "2021-07-01", "2021"])
def test_probe_arm_output_identical_whichever_payload_ran(monkeypatch, near):
    """The load-bearing parity check: identical rows, identical scoring, the ONLY difference is which
    payload SQL ran -> byte-identical evidence out, on every `near` form. (The gate is forced True to
    exercise the vector path on an arm that would otherwise take the scalar one.)"""
    kw = dict(k=2, asof="2021-08-01", near=near, mode="hybrid", embed=_embed)
    cheap = pg.pg_retrieve("frost damage", "coffee", conn=_Conn(), **kw)
    monkeypatch.setattr(pg, "needs_vectors", lambda **_: True)
    rich = pg.pg_retrieve("frost damage", "coffee", conn=_Conn(), **kw)
    assert cheap == rich


# -- the double-evaluation fix ---------------------------------------------------------------------------
def test_score_evaluated_once_per_candidate_not_twice(monkeypatch):
    """pgstore.py:281-282 ran the scorer TWICE per candidate -- once as sort key, once to build
    `relevance`. On the vector path each evaluation is a 1024-wide pure-Python cosine, so this halves the
    CPU even on the fill arm where F2 cannot apply."""
    calls = {"n": 0}
    real = ev._cosine

    def counted(a, b):
        calls["n"] += 1
        return real(a, b)

    monkeypatch.setattr(ev, "_cosine", counted)
    monkeypatch.setattr(pg, "needs_vectors", lambda **_: True)
    pg.pg_retrieve("frost", "coffee", k=2, asof="2021-08-01", embed=_embed, conn=_Conn())
    assert calls["n"] == len(_META)                               # 3 candidates -> 3 cosines (was 6)


# -- integration: the new SQL actually runs, on a real pgvector (skips when unreachable, as in test_pgstore) --
@pytest.fixture()
def seeded():
    import psycopg
    from leviathan.graphrag import pgstore as pgs
    dsn = os.environ.get("EVIDENCE_PG_DSN", "postgresql://postgres:leviathan@localhost:5433/leviathan")
    try:
        conn = psycopg.connect(dsn, autocommit=True, connect_timeout=2)
    except Exception:  # noqa: BLE001
        pytest.skip("no local Postgres reachable (start pgvector/pgvector:pg17 on :5433)")
    conn.execute("DROP TABLE IF EXISTS evidence_props")
    pgs.init_schema(conn, dim=4)
    pgs.upsert("coffee", [{"source": m[1], "source_key": m[2], "date": m[3], "text": m[5],
                           "vector": pgs._vec_parse(v)} for m, v in zip(_META, _VECS)], conn=conn)
    yield conn
    conn.execute("DROP TABLE IF EXISTS evidence_props")
    conn.close()


@pytest.mark.parametrize("hybrid", [False, True])
def test_scalar_payload_sql_executes_on_pgvector_and_matches_python_cosine(seeded, hybrid):
    """The unit tests above run against a fake cursor, so they cannot catch a SQL syntax/aliasing error. This
    runs BOTH shapes on a real pgvector — including the fused branch, where the outer projection sits next to
    the CTE's own `score` column — and checks pgvector's cosine against ev._cosine on the same rows."""
    kw = dict(asof="2021-08-01", fetch_k=10, hybrid=hybrid, conn=seeded)
    rich = pg.fetch_candidates(_QV, "frost damage", "coffee", with_vectors=True, **kw)
    cheap = pg.fetch_candidates(_QV, "frost damage", "coffee", with_vectors=False, **kw)
    assert rich and [r["source_key"] for r in rich] == [r["source_key"] for r in cheap]   # same rows, same order
    for r, c in zip(rich, cheap):
        assert c["score"] == pytest.approx(ev._cosine(_QV, r["vector"]), rel=1e-5)        # float4 accumulation


@pytest.mark.parametrize("near", [None, "2021-07-01"])
def test_pg_retrieve_probe_arm_matches_forced_vector_arm_on_pgvector(seeded, monkeypatch, near):
    kw = dict(k=2, asof="2021-08-01", near=near, mode="hybrid", embed=_embed, conn=seeded)
    cheap = pg.pg_retrieve("frost damage", "coffee", **kw)
    monkeypatch.setattr(pg, "needs_vectors", lambda **_: True)
    rich = pg.pg_retrieve("frost damage", "coffee", **kw)
    # D-DV-2 split the assertion in two, and the split is a REAL property, not a loosened pin: the emitted
    # `score` is pgvector's float4-accumulated cosine on the scalar arm and ev._cosine's float64 on the
    # vector arm (the sibling test above already compares those at rel=1e-5). Everything the answer is
    # built from -- rows, order, dates, text -- is still byte-identical.
    _bare = [{k: v for k, v in r.items() if k != "score"} for r in cheap]
    assert cheap and _bare == [{k: v for k, v in r.items() if k != "score"} for r in rich]
    for c, r in zip(cheap, rich):
        assert c["score"] == pytest.approx(r["score"], rel=1e-5)


def test_relevance_order_is_stable_on_tied_scores(monkeypatch):
    """sorted(reverse=True) must keep the fetch order of EQUAL scores, exactly like the list.sort(reverse=True)
    it replaced -- otherwise F2 would silently reshuffle tied candidates and could change which props a
    k=2 probe returns."""
    monkeypatch.setattr(pg, "fetch_candidates",
                        lambda *a, **k: [{"id": i, "source": "S", "source_key": f"s3://{i}", "date": "2021-01-01",
                                          "event_date": None, "text": f"t{i}", "score": 0.5} for i in range(6)])
    out = pg.pg_retrieve("q", "coffee", k=6, embed=_embed, conn=_Conn())
    assert [r["source_key"] for r in out] == [f"s3://{i}" for i in range(6)]
