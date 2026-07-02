"""pgvector evidence store — pure unit tests + integration against a local pgvector container.

Integration tests SKIP cleanly when no Postgres is reachable (CI). Locally: docker run pgvector/pgvector:pg17
on :5433 (password leviathan). They use a throwaway 4-dim table (dropped before + after) so the suite never
touches a real 1024-dim backfill.
"""
from __future__ import annotations

import os

import pytest

from leviathan.graphrag import pgstore as pg

DSN = os.environ.get("EVIDENCE_PG_DSN", "postgresql://postgres:leviathan@localhost:5433/leviathan")


# ── pure (no DB) ──────────────────────────────────────────────────────────────────────────
def test_tsquery_or_joins_tokens_keeps_codes():
    q = pg._tsquery("B40 mandate raises palm demand B40")
    assert q == "b40 | mandate | raises | palm | demand"          # deduped, OR-joined, code intact as one token


def test_prop_id_stable_and_slice_scoped():
    r = {"source_key": "s3://a", "text": "frost hit"}
    assert pg.prop_id("corn", r) == pg.prop_id("corn", r)          # deterministic
    assert pg.prop_id("corn", r) != pg.prop_id("drivers/frost", r)  # same prop in 2 slices = 2 rows (today's semantics)


def test_vector_literal_round_trip():
    v = [0.25, -1.5, 3.0]
    assert pg._vec_parse(pg._vec_lit(v)) == v


# ── integration (local pgvector container; skip if unreachable) ──────────────────────────
def _conn():
    import psycopg
    try:
        c = psycopg.connect(DSN, autocommit=True, connect_timeout=2)
    except Exception:  # noqa: BLE001
        pytest.skip("no local Postgres reachable (start pgvector/pgvector:pg17 on :5433)")
    return c


RECS = [  # 4-dim fake vectors; axis 0 = "frost-ness", axis 1 = "dollar-ness"
    {"source": "GAIN", "source_key": "s3://g1", "date": "2021-07-20", "text": "July frost hit Sul de Minas",
     "vector": [1.0, 0.0, 0.0, 0.0]},
    {"source": "WASDE", "source_key": "s3://w1", "date": "2021-06-10", "text": "stocks steady in June",
     "vector": [0.8, 0.1, 0.0, 0.0]},
    {"source": "FRED", "source_key": "s3://f1", "date": "2021-05-01", "text": "dollar strengthened broadly",
     "vector": [0.0, 1.0, 0.0, 0.0]},
    {"source": "GAIN", "source_key": "s3://g2", "date": "2022-01-05", "text": "B40 mandate lifts palm demand",
     "vector": [0.0, 0.0, 1.0, 0.0]},
    {"source": "GAIN", "source_key": "s3://g3", "date": "2021-09-01", "text": "FUTURE-dated frost note",
     "vector": [0.99, 0.0, 0.0, 0.0]},
]


@pytest.fixture()
def seeded():
    conn = _conn()
    conn.execute("DROP TABLE IF EXISTS evidence_props")
    pg.init_schema(conn, dim=4)
    pg.upsert("coffee", RECS, conn=conn)
    yield conn
    conn.execute("DROP TABLE IF EXISTS evidence_props")
    conn.close()


def test_dense_fetch_orders_by_cosine_and_filters_asof(seeded):
    rows = pg.fetch_candidates([1.0, 0.0, 0.0, 0.0], "frost", "coffee", asof="2021-08-01", fetch_k=10,
                               hybrid=False, conn=seeded)
    assert rows[0]["text"].startswith("July frost")                # nearest first (exact cosine)
    assert all(r["date"] <= "2021-08-01" for r in rows)            # leakage guard IN SQL
    assert not any("FUTURE" in r["text"] for r in rows)            # the 2021-09 row is invisible at this asof


def test_hybrid_lexical_leg_surfaces_exact_token(seeded):
    # dense query vector points AWAY from the B40 row; the FTS leg must still surface it via the token
    rows = pg.fetch_candidates([1.0, 0.0, 0.0, 0.0], "B40 mandate", "coffee", asof=None, fetch_k=10,
                               hybrid=True, conn=seeded)
    assert any("B40" in r["text"] for r in rows)


def test_upsert_idempotent(seeded):
    n1 = seeded.execute("SELECT count(*) FROM evidence_props").fetchone()[0]
    pg.upsert("coffee", RECS, conn=seeded)                         # reload the same slice
    n2 = seeded.execute("SELECT count(*) FROM evidence_props").fetchone()[0]
    assert n1 == n2 == len(RECS)


def test_pg_retrieve_parity_with_flatfile(seeded, monkeypatch):
    """The load-bearing check: same query, same records -> pg path and flat path pick the SAME evidence."""
    from leviathan.graphrag import evidence as ev

    def fake_embed(texts, **k):                                    # 'frost' -> axis 0; 'dollar' -> axis 1
        return [[1.0 if "frost" in t else 0.0, 1.0 if "dollar" in t else 0.0, 0.0, 0.0] for t in texts]

    monkeypatch.setattr(ev, "embed", fake_embed)
    flat = ev.retrieve("frost damage", "coffee", k=3, asof="2021-08-01", records=RECS)
    via_pg = pg.pg_retrieve("frost damage", "coffee", k=3, asof="2021-08-01", embed=fake_embed, conn=seeded)
    assert [r["source_key"] for r in via_pg] == [r["source_key"] for r in flat]


def test_env_switch_routes_retrieve_through_pg(seeded, monkeypatch):
    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag import pgstore as pgs
    called = {}

    def fake_pg_retrieve(query, node, **kw):
        called["node"] = node
        return [{"date": "2021-07-20", "source": "GAIN", "source_key": "s3://g1", "text": "x"}]

    monkeypatch.setenv("EVIDENCE_BACKEND", "pg")
    monkeypatch.setattr(pgs, "pg_retrieve", fake_pg_retrieve)
    out = ev.retrieve("frost", "coffee", k=3, asof="2021-08-01")   # records=None -> routed to pg
    assert called["node"] == "coffee" and out[0]["source"] == "GAIN"
    # explicit records= must stay local even with the env set (tests + injected fixtures rely on it)
    called.clear()
    monkeypatch.setattr(ev, "embed", lambda t, **k: [[1.0, 0.0, 0.0, 0.0] for _ in t])
    out2 = ev.retrieve("frost", "coffee", k=2, asof="2021-08-01", records=RECS)
    assert not called and len(out2) == 2
