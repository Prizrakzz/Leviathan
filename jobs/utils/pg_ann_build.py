"""D-HN: build + CERTIFY per-slice partial hnsw indexes on the SHADOW table, and write the manifest.

REVIEW wf_f7314d29, every objection honoured in this rewrite:
  * NEVER `CREATE INDEX IF NOT EXISTS` with a derived name (the 2026-08-27 rename-survivor class,
    which HERE decays into a FALSE CERTIFICATE): the ensure is TABLE-SCOPED via pg_indexes with
    collision-free numeric suffixing, the ACTUAL name is recorded, and certification REFUSES unless
    an EXPLAIN of the approx leg shows the index in use (a recall-1.0 obtained via seq scan REJECTS).
  * Certified AT THE SERVING k: k = evidence._FETCH_K, window = k * pgstore._ANN_OVERFETCH, both
    IMPORTED, both recorded per slice; the router refuses any fetch above the certified k.
  * THE PRODUCTION STATEMENTS VERBATIM: both legs run pgstore.dense_exact_sql / dense_ann_sql --
    the same one-producer templates fetch_candidates emits -- so the certificate is about the
    statement the router serves, tie behaviour included.
  * THE asof LEG IS EXERCISED: each slice certifies at asof=None AND at --asof (default 2026-02-15,
    the eval decks' pinned as-of); the WORST recall decides.
  * EXACT LEG FIRST, INDEX SECOND: exact tops are computed BEFORE the index exists (the btree plan
    -- no enable_* de-optimization against the production instance), then CREATE + EXPLAIN + approx
    run inside ONE TRANSACTION committed only on certification -- a crash leaves no index at all.
  * POSITIVE REFUSE: --table must be exactly f"{pgstore.table_name()}_shadow".
  * Sampling: ORDER BY random(), 48 vectors (a one-off cost against a permanent routing decision).

    python jobs/utils/pg_ann_build.py --table evidence_props_shadow \
        --out s3://leviathan-dev-shahem-001/graphrag_evidence/eval/pg_ann_manifest.json
    (in-VPC via Batch on the evidence-build jobdef -- submit with a command override, image must
     carry this commit: push -> build -> register_evidence_jobdef -> submit, the digest-pin law.)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time

from leviathan.common import config

config.load_env()

from leviathan.graphrag import evidence as ev  # noqa: E402
from leviathan.graphrag import pgstore  # noqa: E402

M, EF_CONSTRUCTION = 24, 128   # 08-28 round-2: recall@60 needs a better graph than 16/64 built
SAMPLE_QUERIES = 48


def _free_index_name(conn, t: str, node: str) -> str:
    base = f"{t}_ann_{hashlib.sha1(node.encode()).hexdigest()[:10]}"
    name, i = base, 1
    while conn.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (name,)).fetchone():
        i += 1
        name = f"{base}_{i}"
    return name


def _table_has_slice_index(conn, t: str, node: str):
    row = conn.execute(
        "SELECT indexname FROM pg_indexes WHERE tablename = %s AND indexdef LIKE '%%USING hnsw%%' "
        "AND indexdef LIKE %s", (t, f"%%node = '{node}'%%")).fetchone()
    return row[0] if row else None


def _dense_ids(conn, sql: str, params: dict) -> list:
    return [r[0] for r in conn.execute(sql, params).fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Build + certify per-slice partial hnsw indexes (shadow only)")
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", required=True, help="manifest destination (s3://... or local path)")
    ap.add_argument("--min-rows", type=int, default=None)
    ap.add_argument("--ef", type=int, default=None)
    ap.add_argument("--asof", default="2026-02-15", help="the historical PIT leg both shapes certify at")
    args = ap.parse_args()

    live = pgstore.table_name()
    if args.table != f"{live}_shadow":
        print(f"REFUSE: --table must be the shadow twin ({live}_shadow); got {args.table}")
        return 1
    if not pgstore.dsn():
        print("EVIDENCE_PG_DSN not set")
        return 1
    min_rows = args.min_rows if args.min_rows is not None else pgstore._ann_min_rows()
    ef = args.ef if args.ef is not None else pgstore._ann_ef()
    k = int(ev._FETCH_K)
    ok = k * pgstore._ANN_OVERFETCH

    import psycopg
    from psycopg import sql as S
    conn = psycopg.connect(pgstore.dsn(), autocommit=True)
    try:
        assert conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone(), "no pgvector"
        conn.execute("SET statement_timeout = 0")
        conn.execute("SET hnsw.ef_search = %s" % int(ef))
        conn.execute("SET hnsw.iterative_scan = 'strict_order'")
        conn.execute("SET hnsw.max_scan_tuples = %s" % int(pgstore._ann_mst()))
        t = args.table

        cand = conn.execute(
            S.SQL("SELECT node, count(*) FROM {} GROUP BY node HAVING count(*) >= %s "
                  "ORDER BY count(*) DESC").format(S.Identifier(t)), (min_rows,)).fetchall()
        print(f"candidate slices (>= {min_rows} rows): {len(cand)}", flush=True)

        manifest: dict = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                          "built_on": t, "ef_search": ef, "min_rows": min_rows,
                          "max_scan_tuples": pgstore._ann_mst(),
                          "m": M, "ef_construction": EF_CONSTRUCTION,
                          "k": k, "overfetch": pgstore._ANN_OVERFETCH,
                          "certified_asofs": [None, args.asof], "slices": {}}
        kept = dropped = 0
        for node, n in cand:
            if _table_has_slice_index(conn, t, node):
                print(f"  SKIP {node}: an hnsw index already exists on {t} for this slice "
                      f"(re-certify by dropping it first)", flush=True)
                continue
            # sample the probe vectors + compute BOTH asof-legs' EXACT tops BEFORE the index
            # exists: the btree(node,date) plan, i.e. production's own exact path, no de-optimizing
            qvecs = [r[0] for r in conn.execute(
                S.SQL("SELECT vector FROM {} WHERE node = %s ORDER BY random() LIMIT %s")
                .format(S.Identifier(t)), (node, SAMPLE_QUERIES)).fetchall()]
            legs = []          # (params, exact_ids) per (qv x asof-leg)
            for qv in qvecs:
                for asof in (None, args.asof):
                    where = "node = %(node)s" + (" AND date <= %(asof)s" if asof else "")
                    p = {"node": node, "asof": asof, "qv": qv, "k": k, "ok": ok}
                    legs.append((where, p, _dense_ids(conn, pgstore.dense_exact_sql(t, where), p)))
            idx = _free_index_name(conn, t, node)
            t0 = time.time()
            worst, certified, worst_leg = 1.0, False, "-"
            with conn.transaction():               # crash/reject -> ROLLBACK -> no index at all
                conn.execute(S.SQL(
                    "CREATE INDEX {} ON {} USING hnsw (vector vector_cosine_ops) "
                    "WITH (m = {}, ef_construction = {}) WHERE node = {}").format(
                    S.Identifier(idx), S.Identifier(t), S.Literal(M),
                    S.Literal(EF_CONSTRUCTION), S.Literal(node)))
                # the certificate is VOID unless the approx leg actually rides the index
                plan = json.dumps(conn.execute(
                    "EXPLAIN (FORMAT JSON) " + pgstore.dense_ann_sql(t, "node = %(node)s"),
                    {"node": node, "qv": qvecs[0], "k": k, "ok": ok}).fetchone()[0])
                if idx not in plan:
                    worst = -1.0                   # a seq-scan "recall 1.0" must REJECT, never certify
                    raise psycopg.Rollback()
                for where, p, exact in legs:
                    approx = _dense_ids(conn, pgstore.dense_ann_sql(t, where), p)
                    recall = len(set(exact) & set(approx)) / max(1, len(exact))
                    if recall < worst:
                        worst = recall
                        worst_leg = "asof" if p.get("asof") else "none"
                    if worst < 1.0:
                        break
                if worst < 1.0:
                    raise psycopg.Rollback()
                certified = True
            build_s = round(time.time() - t0, 1)
            if certified:
                manifest["slices"][node] = {"index": idx, "rows": int(n), "recall": 1.0, "k": k}
                kept += 1
                print(f"  CERTIFIED {node} rows={n} k={k} asof-legs=2 build+certify={build_s}s", flush=True)
            else:
                dropped += 1
                print(f"  REJECTED {node} rows={n} worst_recall={worst:.3f} leg={worst_leg} -- "
                      f"rolled back, stays exact", flush=True)

        body = json.dumps(manifest, indent=1).encode()
        if args.out.startswith("s3://"):
            import boto3
            b, key = args.out[5:].split("/", 1)
            boto3.client("s3").put_object(Bucket=b, Key=key, Body=body)
        else:
            open(args.out, "wb").write(body)
        print(f"manifest -> {args.out}  certified={kept} rejected={dropped}", flush=True)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
