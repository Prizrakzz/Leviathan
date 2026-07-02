"""pgvector evidence store — the indexed backend for retrieve() (EVIDENCE_BACKEND=pg).

Replaces the flat-file path's per-call full-slice scan (JSONL -> pure-Python cosine over 15-23K props) with ONE
SQL round-trip per node: a dense CTE (exact cosine via `vector <=>`, filtered `node = :n AND date <= :asof`) fused
with a lexical CTE (Postgres FTS, 'simple' dict so finance codes like B40/ZL stay whole tokens) by Reciprocal
Rank Fusion — mirroring the flat path's hybrid semantics. Everything AFTER candidate fetch is byte-identical to
the flat path: episode-proximity re-scoring, the bge cross-encoder rerank, and source-aware MMR all run
in-process on the returned candidates (rankers.py untouched, as its docstring promised).

Design choices (deliberate):
  - NO ANN index. Slices are small (thousands of props once filtered), so a btree(node, date) prefilter + exact
    cosine is milliseconds with ZERO recall loss. HNSW is a later option if the corpus 10x-es.
  - Postgres is a DISPOSABLE derived index — S3 stays the source of truth. Drop/rebuild anytime via the loader,
    which reuses the slices' inline vectors (never re-embed, never re-chunk).
  - Leakage-safety in SQL: `date <= asof` is part of the candidate query itself, mirroring retrieve()'s
    filter-FIRST rule.

DSN from EVIDENCE_PG_DSN (e.g. postgresql://postgres:...@host:5432/leviathan). psycopg3; the query vector rides
as a '[f1,f2,...]' literal cast ::vector, so no extra adapter package is needed.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

DIM = 1024                                                   # bge-m3 (and Titan v2) embedding width

_CONN = None


def dsn() -> Optional[str]:
    return os.environ.get("EVIDENCE_PG_DSN")


def connect():
    """Module-cached autocommit connection (single-process serving/eval); reconnects if the old one died."""
    global _CONN
    import psycopg
    if _CONN is not None and not _CONN.closed:
        return _CONN
    _CONN = psycopg.connect(dsn(), autocommit=True)
    return _CONN


def init_schema(conn=None, *, dim: int = DIM) -> None:
    """Idempotent DDL. `tsv` is a stored generated column ('simple' config: no stemming — B40/ZL/CIF stay whole).
    Indexes: btree(node, date) for the filtered exact scan + GIN(tsv) for the lexical leg. No HNSW on purpose."""
    conn = conn or connect()
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS evidence_props (
            id         text PRIMARY KEY,
            node       text NOT NULL,
            source     text,
            source_key text,
            date       text,
            event_date text,
            backend    text,
            text       text NOT NULL,
            meta       jsonb,
            vector     vector({dim}) NOT NULL,
            tsv        tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS evidence_props_node_date ON evidence_props (node, date)")
    conn.execute("CREATE INDEX IF NOT EXISTS evidence_props_tsv ON evidence_props USING gin (tsv)")


def prop_id(node: str, rec: dict) -> str:
    """Stable content id — idempotent reloads, and a prop duplicated across slices keeps per-slice rows
    (matching today's slice semantics exactly)."""
    return hashlib.md5(f"{node}|{rec.get('source_key')}|{rec.get('text')}".encode("utf-8")).hexdigest()


def _vec_lit(v) -> str:
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def _vec_parse(t: str) -> list[float]:
    return [float(x) for x in t.strip("[]").split(",")] if t else []


_CORE = {"source", "source_key", "date", "event_date", "backend", "text", "vector"}


def upsert(node: str, records: list[dict], conn=None, *, batch: int = 500) -> int:
    """Load a slice's records (REUSING their inline vectors). ON CONFLICT updates date/meta so a restamped slice
    reloads cleanly. Returns rows written."""
    conn = conn or connect()
    n = 0
    sql = ("INSERT INTO evidence_props (id,node,source,source_key,date,event_date,backend,text,meta,vector) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector) "
           "ON CONFLICT (id) DO UPDATE SET date=EXCLUDED.date, event_date=EXCLUDED.event_date, meta=EXCLUDED.meta")
    with conn.cursor() as cur:
        for i in range(0, len(records), batch):
            rows = []
            for r in records[i:i + batch]:
                meta = {k: v for k, v in r.items() if k not in _CORE}
                rows.append((prop_id(node, r), node, r.get("source"), r.get("source_key"), r.get("date"),
                             r.get("event_date"), r.get("backend"), r.get("text"),
                             json.dumps(meta) if meta else None, _vec_lit(r["vector"])))
            cur.executemany(sql, rows)
            n += len(rows)
    return n


def _tsquery(query: str) -> str:
    """OR the query's tokens ('simple'-config lexemes) — BM25-style recall, not AND-of-everything."""
    from leviathan.graphrag import rankers as rk
    return " | ".join(dict.fromkeys(rk.tokenize(query))) or ""


def fetch_candidates(query_vec, query_text: str, node: str, *, asof: Optional[str], fetch_k: int,
                     hybrid: bool = True, conn=None) -> list[dict]:
    """ONE round-trip: dense CTE + (optionally) lexical CTE, RRF-fused in SQL (c=60, same as rankers.rrf_fuse).
    Rows come back with their vectors so rerank/MMR run in-process unchanged."""
    conn = conn or connect()
    qv = _vec_lit(query_vec)
    where = "node = %(node)s" + (" AND date <= %(asof)s" if asof else "")
    params = {"node": node, "asof": asof, "qv": qv, "k": fetch_k, "tsq": _tsquery(query_text) if hybrid else ""}
    dense = (f"SELECT id, ROW_NUMBER() OVER (ORDER BY vector <=> %(qv)s::vector) AS rnk "
             f"FROM evidence_props WHERE {where} ORDER BY vector <=> %(qv)s::vector LIMIT %(k)s")
    if hybrid and params["tsq"]:
        lex = (f"SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(tsv, to_tsquery('simple', %(tsq)s)) DESC) AS rnk "
               f"FROM evidence_props WHERE {where} AND tsv @@ to_tsquery('simple', %(tsq)s) LIMIT %(k)s")
        fused = (f"WITH dense AS ({dense}), lex AS ({lex}), "
                 "fused AS (SELECT COALESCE(d.id, l.id) AS id, "
                 "COALESCE(1.0/(60+d.rnk),0) + COALESCE(1.0/(60+l.rnk),0) AS score "
                 "FROM dense d FULL OUTER JOIN lex l USING (id)) "
                 "SELECT p.id, p.source, p.source_key, p.date, p.event_date, p.text, p.vector::text "
                 "FROM fused f JOIN evidence_props p USING (id) ORDER BY f.score DESC LIMIT %(k)s")
    else:
        fused = (f"WITH dense AS ({dense}) "
                 "SELECT p.id, p.source, p.source_key, p.date, p.event_date, p.text, p.vector::text "
                 "FROM dense d JOIN evidence_props p USING (id) ORDER BY d.rnk LIMIT %(k)s")
    with conn.cursor() as cur:
        cur.execute(fused, params)
        rows = cur.fetchall()
    return [{"id": r[0], "source": r[1], "source_key": r[2], "date": r[3], "event_date": r[4],
             "text": r[5], "vector": _vec_parse(r[6])} for r in rows]


def pg_retrieve(query: str, node: str, *, k: int = 5, asof: str | None = None, near: str | None = None,
                beta: float = 0.25, mode: str = "dense", rerank: bool = False, mmr: float = 0.0,
                same_source: bool = True, fairness: float = 0.30, fetch_k: int = 60,
                embed=None, conn=None) -> list[dict]:
    """The pg twin of evidence.retrieve(): same knobs, same output shape, same post-fetch pipeline.
    Candidates come from SQL; proximity/rerank/MMR are computed in-process exactly like the flat path."""
    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag import rankers as rk
    embed = embed or ev.embed
    qv = embed([query])[0]
    cand = fetch_candidates(qv, query, node, asof=asof, fetch_k=fetch_k, hybrid=(mode == "hybrid"), conn=conn)
    if not cand:
        return []

    def _dense(r):                                            # identical scoring to evidence.retrieve
        return ev._cosine(qv, r["vector"]) + (beta * ev._proximity(r["date"], near) if near else 0.0)

    cand.sort(key=_dense, reverse=True)
    relevance = [_dense(r) for r in cand]
    if rerank and cand:
        relevance = rk.rerank_scores(query, [r["text"] for r in cand])
        order = sorted(range(len(cand)), key=lambda i: relevance[i], reverse=True)
        cand, relevance = [cand[i] for i in order], [relevance[i] for i in order]
    top = (rk.mmr_select(cand, relevance, k, mmr, same_source=same_source, fairness=fairness)
           if (mmr > 0 and len(cand) > k) else cand[:k])
    return [{"date": r["date"], "source": r["source"], "source_key": r["source_key"], "text": r["text"]}
            for r in top]
