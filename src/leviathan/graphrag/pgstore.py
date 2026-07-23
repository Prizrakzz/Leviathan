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
import re
import threading
from typing import Optional

DIM = 1024                                                   # bge-m3 (and Titan v2) embedding width

# Blue-green plumbing: every DDL/DML statement below resolves its table name through table_name() at CALL
# time (never at import), so a shadow rebuild can point the loader at `evidence_props_shadow`, verify it,
# then flip live<->shadow with a transactional rename (jobs/utils/pg_evidence_swap.py) — the pre-flip table
# is retained for rollback. Default stays `evidence_props`, so unset-env behavior is byte-identical.
_DEFAULT_TABLE = "evidence_props"
# A pg identifier we interpolate straight into DDL/DML (no bind-param path exists for table names). The
# strict lower-snake regex keeps SQL injection impossible: the only accepted characters are the ones a
# legitimate table name uses, so a hostile EVIDENCE_PG_TABLE can never smuggle a quote or a semicolon.
_TABLE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def table_name() -> str:
    """Resolve the evidence table from EVIDENCE_PG_TABLE (default `evidence_props`), validated at call time.

    Resolved per-call (NOT cached at import) so a subprocess/env flip — the loader's --table, the swap
    tool's guard query, a shadow eval's `--env EVIDENCE_PG_TABLE=evidence_props_shadow` — takes effect
    without a re-import, and so tests can monkeypatch the env. Rejects anything that isn't lower-snake:
    the name is interpolated into SQL and there is no bind-parameter form for an identifier, so validation
    is the injection barrier, not an f-string escape."""
    name = (os.environ.get("EVIDENCE_PG_TABLE") or _DEFAULT_TABLE).strip()
    if not _TABLE_RE.match(name):
        raise ValueError(f"EVIDENCE_PG_TABLE {name!r} is not a valid table name (^[a-z_][a-z0-9_]*$)")
    return name

_CONN = None
# The module connection is a SINGLE psycopg connection (not concurrency-safe). The L2 walk now fetches nodes
# in parallel (to overlap the managed-rerank round-trips), so serialize cursor use here — the SQL fetch is
# milliseconds, and the slow rerank happens OUTSIDE this lock, back in pg_retrieve.
_PG_LOCK = threading.Lock()

# Serving-path connection POOL: a turn issues ~34 round-trips (10 fill fetches + ~24 regime probes); one
# lock-serialized connection made that ~8.5s of the walk. A few pooled autocommit connections un-serialize it
# (RDS t4g.micro handles this comfortably). Callers that pass an explicit `conn` (tests, the loader) keep the
# old single-connection + lock path.
_POOL = None
_POOL_SIZE = int(os.environ.get("EVIDENCE_PG_POOL", "4"))
# Checkout wait ceiling: holders keep a conn for milliseconds (one execute+fetch), so a multi-minute wait
# means slots leaked or a holder wedged — fail the ONE caller loudly (pg_query degrades to its Athena
# fallback; a walk fetch errors its turn) instead of blocking every worker forever (Jul-11 stall autopsy).
_POOL_WAIT_S = int(os.environ.get("EVIDENCE_PG_POOL_WAIT_S", "120"))
# Server-side per-statement ceiling on POOLED SERVING connections (numbers lookups AND evidence-walk
# fetches — both draw from this pool). A pooled conn should hold its slot only for one execute()+fetch;
# without a server-side kill a pathological query (e.g. a bad plan on a freshly-reloaded, un-ANALYZEd
# mirror table) holds its slot for MINUTES, and because a turn's walk fans out GRAPHRAG_WALK_WORKERS
# fetches while several turns run at once, a couple of wedged holders starve every slot -> the 120s
# checkout wait above trips for everyone and turns floor. Worse, the eval watchdog ORPHANS a wedged
# worker WITHOUT releasing its slot, so the pool monotonically dies and never recovers (the 2026-07-22
# rev-51 gate: silver_wasde reloaded +18% rows -> ~800K, first heavy run of the new row_filters
# `col IN (...)` SQL wedged the pool at ~64min and 18 turns floored / the last 3 ran to the 4200s
# watchdog). Bounding each statement server-side keeps the hold to <=_STMT_TIMEOUT_MS: a numbers lookup
# catches the cancel and falls back to Athena on the SAME SQL (honest); an evidence fetch floors only
# its own turn; and an orphaned worker's query self-cancels so its finally frees the slot. The LOADER
# connects directly (never via _acquire), so a multi-minute bulk COPY stays unbounded. 0 disables.
#
# CEILING CALIBRATION (2026-07-23 floor RCA): the original 60s default CAUSED the very floors it
# guarded against — the fused hybrid retrieval (exact-scan by design, no ANN index, t4g.micro 2 vCPU)
# has a LEGITIMATE >60s tail on heavy multi-node hybrid turns (the walk fans out ~8 concurrent fused
# queries that contend for 2 vCPUs; solo turns still floor), so 19/30 judged rows died in
# fetch_candidates wearing the "model tier unavailable" banner while Sonnet was never even called.
# 300s clears the honest tail with headroom while still killing true wedges (the rev-51 wedge held
# slots for 64+ minutes). Do NOT tighten below the observed heavy-turn retrieval tail without
# measuring it first.
_STMT_TIMEOUT_MS = int(os.environ.get("EVIDENCE_PG_STATEMENT_TIMEOUT_MS", "300000"))


def _acquire():
    global _POOL
    import queue as _q

    import psycopg
    if _POOL is None:
        with _PG_LOCK:
            if _POOL is None:
                p: _q.Queue = _q.Queue()
                for _ in range(max(1, _POOL_SIZE)):
                    p.put(None)                          # lazy slots — connect on first checkout
                _POOL = p
    try:
        conn = _POOL.get(timeout=max(1, _POOL_WAIT_S))
    except _q.Empty:
        raise RuntimeError(f"pg pool exhausted: no connection freed in {_POOL_WAIT_S}s "
                           f"(size={_POOL_SIZE}) — leaked slot or wedged holder") from None
    if conn is None or conn.closed:
        try:
            kw = {"autocommit": True}
            if _STMT_TIMEOUT_MS > 0:
                # bound EVERY statement server-side via libpq options (atomic with connect, survives the
                # pooled conn's whole lifetime, no extra round-trip) so a wedged query is KILLED instead
                # of holding a pool slot for minutes (the rev-51 pool death). Read at call time so tests
                # and an env override take effect without re-import.
                kw["options"] = f"-c statement_timeout={int(_STMT_TIMEOUT_MS)}"
            conn = psycopg.connect(dsn(), **kw)
        except BaseException:
            _POOL.put(None)      # a failed connect returns the SLOT (lazy) — it must never shrink the pool
            raise
    return conn


def _release(conn) -> None:
    _POOL.put(conn)


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
    """Idempotent DDL for the resolved table (table_name()). `tsv` is a stored generated column ('simple'
    config: no stemming — B40/ZL/CIF stay whole). Indexes: btree(node, date) for the filtered exact scan +
    GIN(tsv) for the lexical leg. No HNSW on purpose.

    Index names are DERIVED from the table name (`<t>_node_date`, `<t>_tsv`) so building the shadow table
    while the live table exists doesn't collide on a shared index name. NB the swap tool renames the TABLE
    only — Postgres keeps indexes attached across a table rename but does NOT rename them, so post-flip the
    indexes carry their pre-flip (shadow-derived) names. That's cosmetic: they stay attached and functional,
    and the next rebuild's CREATE INDEX IF NOT EXISTS is keyed on the (new) table's own derived names."""
    conn = conn or connect()
    t = table_name()
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {t} (
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
    conn.execute(f"CREATE INDEX IF NOT EXISTS {t}_node_date ON {t} (node, date)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS {t}_tsv ON {t} USING gin (tsv)")


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
    t = table_name()
    sql = (f"INSERT INTO {t} (id,node,source,source_key,date,event_date,backend,text,meta,vector) "
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
    pooled = conn is None
    t = table_name()
    qv = _vec_lit(query_vec)
    where = "node = %(node)s" + (" AND date <= %(asof)s" if asof else "")
    params = {"node": node, "asof": asof, "qv": qv, "k": fetch_k, "tsq": _tsquery(query_text) if hybrid else ""}
    dense = (f"SELECT id, ROW_NUMBER() OVER (ORDER BY vector <=> %(qv)s::vector) AS rnk "
             f"FROM {t} WHERE {where} ORDER BY vector <=> %(qv)s::vector LIMIT %(k)s")
    if hybrid and params["tsq"]:
        lex = (f"SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(tsv, to_tsquery('simple', %(tsq)s)) DESC) AS rnk "
               f"FROM {t} WHERE {where} AND tsv @@ to_tsquery('simple', %(tsq)s) LIMIT %(k)s")
        fused = (f"WITH dense AS ({dense}), lex AS ({lex}), "
                 "fused AS (SELECT COALESCE(d.id, l.id) AS id, "
                 "COALESCE(1.0/(60+d.rnk),0) + COALESCE(1.0/(60+l.rnk),0) AS score "
                 "FROM dense d FULL OUTER JOIN lex l USING (id)) "
                 "SELECT p.id, p.source, p.source_key, p.date, p.event_date, p.text, p.vector::text "
                 f"FROM fused f JOIN {t} p USING (id) ORDER BY f.score DESC LIMIT %(k)s")
    else:
        fused = (f"WITH dense AS ({dense}) "
                 "SELECT p.id, p.source, p.source_key, p.date, p.event_date, p.text, p.vector::text "
                 f"FROM dense d JOIN {t} p USING (id) ORDER BY d.rnk LIMIT %(k)s")
    if pooled:                                               # serving path: pooled conns, concurrent fetches
        c = _acquire()
        try:
            with c.cursor() as cur:
                cur.execute(fused, params)
                rows = cur.fetchall()
        finally:
            _release(c)
    else:                                                    # explicit conn (tests/loader): serialized as before
        with _PG_LOCK, conn.cursor() as cur:
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
        cand = cand[:rk.RERANK_POOL]                          # same pool cap as evidence.retrieve
        relevance = rk.rerank_scores(query, [r["text"] for r in cand])
        order = sorted(range(len(cand)), key=lambda i: relevance[i], reverse=True)
        cand, relevance = [cand[i] for i in order], [relevance[i] for i in order]
    top = (rk.mmr_select(cand, relevance, k, mmr, same_source=same_source, fairness=fairness)
           if (mmr > 0 and len(cand) > k) else cand[:k])
    return [{"date": r["date"], "source": r["source"], "source_key": r["source_key"], "text": r["text"],
             "event_date": r.get("event_date"), "event_date_precision": r.get("event_date_precision")}
            for r in top]
