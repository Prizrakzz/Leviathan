"""09-24 FIX ROUND 2, LANE C (CONTRACT K25, THREAT_MODEL B18) -- THE EVENT DATE'S PRECISION CROSSES THE STORE
PROJECTION ON BOTH FETCH SHAPES (hermetic: fake cursors, no Postgres).

THE MEASURED DEFECT: `pgstore.upsert` writes every non-core key of a proposition into the `meta` jsonb
(`_CORE`), so `event_date_precision` was always STORED; `_project` read the three span keys off `meta` and
never this one, so `pg_retrieve` emitted None on every row -- 393 of 393 chain hops on the ten 09-24 traces
carried precision "" (a month-precision "2025-02-01" printed as a day; a year-precision conditional forecast
scored as an open action). What is pinned here:

  * `_project` carries `event_date_precision` off `meta` on the SINGLE-node shape (off=0) and the BATCH
    shape (off=1, the node projected as a leading column), vector and score payloads alike;
  * an absent key, an empty `meta` and a NULL `meta` all stay None -- the legacy row keeps "no precision",
    never a precision inferred from the date's shape;
  * the value crosses `fetch_candidates`, `fetch_candidates_batch` and `pg_retrieve`'s OUTPUT projection
    unchanged, for every stored kind;
  * nothing else in the candidate dict moves (the nine keys HEAD projected are byte-equal).
"""
from __future__ import annotations

import pytest

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import pgstore as pg

_QV = [1.0, 0.0, 0.0, 0.0]
_ROWS = [
    # id, source, source_key, date, event_date, text, meta
    ("p1", "GAIN", "s3://tariff", "2025-03-19", "2025-02-01", "China imposed ...",
     {"char_start": 10, "char_end": 40, "offset_kind": "exact", "event_date_precision": "month"}),
    ("p2", "MPOC", "s3://mpoc", "2023-03-28", "2023-04-01", "If the blend rate is raised ...",
     {"event_date_precision": "month"}),
    ("p3", "GAIN", "s3://cotton", "2026-04-03", "2026-01-01", "If El Nino develops in 2026 ...",
     {"event_date_precision": "year"}),
    ("p4", "WASDE", "s3://wasde", "2026-09-11", "2026-09-11", "USDA lowered ...",
     {"event_date_precision": "day"}),
    ("p5", "FRED", "s3://legacy", "2019-05-01", None, "a pre-precision vintage", {}),
    ("p6", "FRED", "s3://nullmeta", "2019-05-01", None, "a row whose meta column is NULL", None),
]
_VEC = "[1.0,0.0,0.0,0.0]"


def _tuple(row, *, with_vectors: bool, node: str | None = None):
    base = row[:6] + (row[6],) + ((_VEC,) if with_vectors else (0.9,))
    return ((node,) + base) if node is not None else base


@pytest.mark.parametrize("with_vectors", [True, False])
def test_project_single_shape_reads_precision_off_meta(with_vectors):
    got = [pg._project(_tuple(r, with_vectors=with_vectors), with_vectors) for r in _ROWS]
    assert [g["event_date_precision"] for g in got] == ["month", "month", "year", "day", None, None]


@pytest.mark.parametrize("with_vectors", [True, False])
def test_project_batch_shape_reads_precision_off_meta(with_vectors):
    got = [pg._project(_tuple(r, with_vectors=with_vectors, node="soybeans"), with_vectors, off=1)
           for r in _ROWS]
    assert [g["event_date_precision"] for g in got] == ["month", "month", "year", "day", None, None]


def test_the_two_shapes_project_identical_metadata():
    """EC-2's parity claim, extended to the new key: one projection, two tuple layouts, one dict."""
    for r in _ROWS:
        a = pg._project(_tuple(r, with_vectors=False), False)
        b = pg._project(_tuple(r, with_vectors=False, node="n"), False, off=1)
        assert a == b


def test_nothing_else_in_the_candidate_moves():
    """The nine keys HEAD projected keep their values; the ONE added key is the precision."""
    r = _ROWS[0]
    got = pg._project(_tuple(r, with_vectors=False), False)
    assert {k: got[k] for k in ("id", "source", "source_key", "date", "event_date", "text",
                                "char_start", "char_end", "offset_kind")} == {
        "id": "p1", "source": "GAIN", "source_key": "s3://tariff", "date": "2025-03-19",
        "event_date": "2025-02-01", "text": "China imposed ...", "char_start": 10, "char_end": 40,
        "offset_kind": "exact"}
    assert set(got) == {"id", "source", "source_key", "date", "event_date", "text", "char_start",
                        "char_end", "offset_kind", "event_date_precision", "date_kind", "score"}


def test_precision_is_never_inferred_from_the_date_shape():
    """A "-01" day on an event date is NOT a month: with no stored precision the projection says None."""
    row = ("p9", "GAIN", "s3://x", "2025-03-19", "2025-02-01", "t", {"char_start": 1})
    assert pg._project(_tuple(row, with_vectors=False), False)["event_date_precision"] is None


# -- through the fetch paths and pg_retrieve's own OUTPUT projection (fake connection) ---------------------
class _Cur:
    def __init__(self, sink, batch=False):
        self._sink, self._batch = sink, batch

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self._sink["sql"], self._sink["params"] = sql, params

    def fetchall(self):
        vec = "p.vector::text" in self._sink["sql"]
        if self._batch:
            return [_tuple(r, with_vectors=vec, node="soybeans") for r in _ROWS]
        return [r[:6] + (r[6],) + ((_VEC,) if vec else (ev._cosine(_QV, pg._vec_parse(_VEC)),))
                for r in _ROWS]


class _Conn:
    def __init__(self, batch=False):
        self.sink: dict = {}
        self._batch = batch

    def cursor(self):
        return _Cur(self.sink, self._batch)


def _embed(texts, **kw):
    return [list(_QV) for _ in texts]


@pytest.mark.parametrize("with_vectors", [True, False])
def test_fetch_candidates_carries_precision(with_vectors):
    out = pg.fetch_candidates(_QV, "tariff", "soybeans", asof="2026-09-24", fetch_k=10, hybrid=False,
                              conn=_Conn(), with_vectors=with_vectors)
    assert {r["source_key"]: r["event_date_precision"] for r in out} == {
        "s3://tariff": "month", "s3://mpoc": "month", "s3://cotton": "year", "s3://wasde": "day",
        "s3://legacy": None, "s3://nullmeta": None}


def test_pg_retrieve_output_projection_emits_the_stored_precision():
    """`pg_retrieve`'s return rows already read `r.get("event_date_precision")`; with the projection
    fixed, that read finally sees the stored value instead of a key that was never there."""
    out = pg.pg_retrieve("tariff", "soybeans", k=6, asof="2026-09-24", embed=_embed, conn=_Conn())
    got = {r["source_key"]: r["event_date_precision"] for r in out}
    assert got == {"s3://tariff": "month", "s3://mpoc": "month", "s3://cotton": "year",
                   "s3://wasde": "day", "s3://legacy": None, "s3://nullmeta": None}
    # the output row shape is HEAD's (the key existed; only its value was always None)
    assert all(set(r) == {"date", "source", "source_key", "text", "event_date", "event_date_precision",
                          "date_kind", "char_start", "char_end", "offset_kind", "score"} for r in out)


def test_prefetched_batch_candidates_reach_pg_retrieve_with_their_precision():
    """The EC-2 path: rows projected by the BATCH shape and handed to pg_retrieve as `candidates=`."""
    cands = [pg._project(_tuple(r, with_vectors=False, node="soybeans"), False, off=1) for r in _ROWS]
    out = pg.pg_retrieve("tariff", "soybeans", k=6, asof="2026-09-24", embed=_embed, conn=_Conn(),
                         candidates=cands)
    assert {r["source_key"]: r["event_date_precision"] for r in out}["s3://cotton"] == "year"
