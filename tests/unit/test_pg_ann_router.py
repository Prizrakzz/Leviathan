"""D-HN: the gated per-slice ANN router — fail-closed pins (post-review wf_f7314d29). Hermetic.

THE GOLDEN PIN is the load-bearing one: with GRAPHRAG_PG_ANN unset, fetch_candidates must emit the
EXACT dense statement it emitted before this seam existed — byte-for-byte. The router routes ONLY
when mode == 'on' AND the node sits in a certified manifest whose built_on/ef/min_rows match this
process AND whose index name exists on THIS table (the reality join) AND the certified k covers the
caller's fetch_k. 'shadow' is DELETED from the accepted mode set (review fatal 3: it silently served
ANN rows) — it reads as 'off' until the dual-read rider exists.
"""
from __future__ import annotations

import json

import pytest

from leviathan.graphrag import pgstore as pg


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in ("GRAPHRAG_PG_ANN", "GRAPHRAG_PG_ANN_MANIFEST", "EVIDENCE_PG_TABLE",
              "GRAPHRAG_PG_ANN_EF", "GRAPHRAG_PG_ANN_MIN_ROWS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(pg, "_ANN_CACHE", ("", 0.0, None))
    yield
    pg._ANN_CACHE = ("", 0.0, None)


class _Cur:
    def __init__(self, outer):
        self.outer = outer

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.outer.calls.append((sql, dict(params or {})))

    def fetchall(self):
        return self.outer.rows.pop(0) if self.outer.rows else []


class _Conn:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or []

    def cursor(self):
        return _Cur(self)


def _fetch(conn, node="drivers/frost", k=5):
    return pg.fetch_candidates([0.0, 0.0], "q", node, asof=None, fetch_k=k, hybrid=False, conn=conn)


GOLDEN_DENSE = ("SELECT id, ROW_NUMBER() OVER (ORDER BY vector <=> %(qv)s::vector, id) AS rnk "
                "FROM evidence_props WHERE node = %(node)s "
                "ORDER BY vector <=> %(qv)s::vector, id LIMIT %(k)s")


def test_unset_emits_the_frozen_golden_dense_statement():
    conn = _Conn()
    _fetch(conn)
    sql, params = conn.calls[-1]
    assert GOLDEN_DENSE in sql and ") ann" not in sql
    assert "ok" not in params, "the exact path's params must not carry the ANN window key"


def _arm(monkeypatch, tmp_path, node="drivers/frost", rows=5000, recall=1.0, mode="on",
         cert_k=60, ef=100, min_rows=2000, built_on="evidence_props_shadow", index_live=True):
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps({
        "built_on": built_on, "ef_search": ef, "min_rows": min_rows,
        "slices": {node: {"index": "idx_a", "rows": rows, "recall": recall, "k": cert_k}}}),
        encoding="utf-8")
    monkeypatch.setenv("GRAPHRAG_PG_ANN", mode)
    monkeypatch.setenv("GRAPHRAG_PG_ANN_MANIFEST", str(mf))
    monkeypatch.setattr(pg, "_ann_live_hnsw_names",
                        lambda: {"idx_a"} if index_live else set())
    pg._ANN_CACHE = ("", 0.0, None)


def test_armed_certified_node_takes_the_ann_shape(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path)
    conn = _Conn()
    _fetch(conn)
    sql, params = conn.calls[0]          # calls[0] = routed; the empty fake result then trips the belt
    assert "LIMIT %(ok)s) ann" in sql and "ORDER BY d, id" in sql
    assert params["ok"] == 5 * pg._ANN_OVERFETCH


def test_shadow_mode_reads_as_off_and_serves_the_golden_exact(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, mode="shadow")
    conn = _Conn()
    _fetch(conn)
    assert len(conn.calls) == 1 and GOLDEN_DENSE in conn.calls[0][0]


def test_certified_k_gates_the_callers_fetch_k(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, cert_k=20)
    conn = _Conn()
    _fetch(conn, k=60)                    # asks beyond the certificate -> exact
    assert GOLDEN_DENSE in conn.calls[0][0]
    conn2 = _Conn()
    _fetch(conn2, k=20)                   # inside the certificate -> routed
    assert ") ann" in conn2.calls[0][0]


def test_reality_join_a_dropped_index_leaves_the_route_set(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, index_live=False)
    conn = _Conn()
    _fetch(conn)
    assert len(conn.calls) == 1 and GOLDEN_DENSE in conn.calls[0][0]


def test_manifest_config_mismatches_refuse_everything(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, ef=40)                     # process ef defaults 100 -> refuse
    assert not pg._ann_routes("drivers/frost")
    _arm(monkeypatch, tmp_path, built_on="other_table")    # foreign certificate -> refuse
    assert not pg._ann_routes("drivers/frost")
    _arm(monkeypatch, tmp_path, min_rows=999)              # filter mismatch -> refuse
    assert not pg._ann_routes("drivers/frost")


def test_low_recall_thin_slices_and_bad_manifests_route_nothing(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, recall=0.95)
    assert not pg._ann_routes("drivers/frost")
    _arm(monkeypatch, tmp_path, rows=10)
    assert not pg._ann_routes("drivers/frost")
    monkeypatch.setenv("GRAPHRAG_PG_ANN", "on")
    monkeypatch.delenv("GRAPHRAG_PG_ANN_MANIFEST", raising=False)
    pg._ANN_CACHE = ("", 0.0, None)
    assert not pg._ann_routes("drivers/frost")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("GRAPHRAG_PG_ANN_MANIFEST", str(bad))
    pg._ANN_CACHE = ("", 0.0, None)
    assert not pg._ann_routes("drivers/frost")


def test_short_result_belt_refetches_exact_and_only_without_asof(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path)
    conn = _Conn(rows=[[], []])
    _fetch(conn)                          # asof=None: ANN short -> belt -> exact refetch
    assert len(conn.calls) == 2
    assert ") ann" in conn.calls[0][0] and GOLDEN_DENSE in conn.calls[1][0]
    _arm(monkeypatch, tmp_path)
    conn2 = _Conn(rows=[[]])
    pg.fetch_candidates([0.0, 0.0], "q", "drivers/frost", asof="2020-01-01", fetch_k=5,
                        hybrid=False, conn=conn2)
    assert len(conn2.calls) == 1          # under asof a short result is the honest PIT answer


def test_batch_omits_routed_nodes_and_is_identity_when_off(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, node="drivers/frost")
    seen = {}

    def fake_batch_rows(t, qv, tsq, part, **kw):
        seen["part"] = list(part)
        return []

    monkeypatch.setattr(pg, "_batch_rows", fake_batch_rows)
    out = pg.fetch_candidates_batch([0.0, 0.0], "q", ["drivers/frost", "drivers/other"],
                                    asof=None, fetch_k=5, hybrid=False)
    assert seen["part"] == ["drivers/other"]
    assert "drivers/frost" not in out
    monkeypatch.delenv("GRAPHRAG_PG_ANN", raising=False)
    pg._ANN_CACHE = ("", 0.0, None)
    pg.fetch_candidates_batch([0.0, 0.0], "q", ["drivers/frost", "drivers/other"],
                              asof=None, fetch_k=5, hybrid=False)
    assert seen["part"] == ["drivers/frost", "drivers/other"]


def test_dense_templates_are_the_single_producer():
    # the certifier certifies pgstore.dense_exact_sql / dense_ann_sql VERBATIM; this pin keeps the
    # serving statements bound to the same producers so certificate and service can never drift.
    assert pg.dense_exact_sql("evidence_props", "node = %(node)s") == GOLDEN_DENSE
    ann = pg.dense_ann_sql("evidence_props", "node = %(node)s")
    assert "LIMIT %(ok)s) ann" in ann and ann.startswith("SELECT id, ROW_NUMBER() OVER (ORDER BY d, id)")
