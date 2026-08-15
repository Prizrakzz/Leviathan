"""EC-2 GATE CLAUSE (b): the evidence-set PARITY PIN -- batched reads vs per-node reads, offline.

    python jobs/utils/ec2_evidence_parity.py --self-test                       # local, no pg, no AWS
    python jobs/utils/ec2_evidence_parity.py --out data/ec2/parity_<ts>.json   # IN-VPC (needs the DSN)

THE CLAUSE, VERBATIM FROM THE SPEC: "evidence-set parity pin green across the full P6 + shape_esc decks
offline (every node's rows identical, order-normalized)". This is that pin, with ONE deliberate
strengthening: the comparison is on the ORDERED id sequence, NOT order-normalized. RRF ties are real
(1/(60+r) collides across the dense and lexical legs) and every sort after the fetch is STABLE, so fetch
order survives all the way to the prompt -- two reads that return the same SET in a different ORDER are
two different answers, and a set-equality pin would have called that green. The `, id` tiebreak landed in
the same commit as the batch precisely so this stricter comparison is a fair one.

THE POPULATION IS A SUPERSET, AND THAT IS STATED RATHER THAN HIDDEN. The pin needs the nodes a deck row's
walk would visit, and the walk is not reproducible offline -- it depends on the graph, the tau gate, the
node budget, the seed routing and (measured on 2026-08-14, the EC-0 record's walk-shape control) it is
not even byte-stable across days. So every row is run against the WHOLE evidence population: all
commodity nodes (`ev.all_nodes()`) plus every driver slice reachable through the alias map
(`drivers/<slice>` for each `ev.backed_slice_names()`). That is more nodes than any walk visits, never
fewer, so a parity defect cannot hide in a node this harness declined to ask about.

WHAT IT COMPARES, PER (ROW, NODE):
  * the ORDERED `id` sequence, exact;
  * every row dict key, exact -- INCLUDING the `vector` payload, which is the same stored column rendered
    by the same `::text` cast on both sides and must therefore be byte-identical;
  * EXCEPT `score` (the no-vector/probe shape only), compared by id/order within `--tol`: it is a
    single-precision pgvector distance expression, its ~7th-significant-digit drift is PRE-EXISTING and
    documented in pgstore's own docstring, and pinning it exactly would pin the FPU, not this change.

IT ALSO CAPTURES THE PLAN SHAPE: one `EXPLAIN (ANALYZE, BUFFERS)` of a batch statement and one of the
equivalent single-node statement, verbatim, as the record of what the LATERAL rewrite did to the plan.
The SQL is captured by wrapping the connection's cursor, so pgstore keeps building its own statements and
this file cannot drift from them.

HOW TO SUBMIT IT (in-VPC): the estate's evidence-build jobdef pattern --
`jobs/utils/register_evidence_jobdef.py` registers `leviathan-dev-evidence-build` on the embedder image
(torch + bge-m3 baked, which is what `ev.embed` needs) with `EVIDENCE_PG_DSN` injected from the
`leviathan/dev/evidence-pg-dsn` secret. Register a revision whose command is this script, submit it to
the same idle queue under the pool-contention law, and read the JSON artifact from `--out`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_P6_DECK = "configs/graphrag/eval_queries_cascade_downstream_v1.yaml"
_ESC_DECK = "configs/graphrag/eval_queries_shape_esc_v1.yaml"

# The two payload shapes pgstore serves. `fill` is the one EC-2 exists for (the walk's rerank+MMR arm,
# `p.vector::text`); `probe` is the F2 cheap shape (the scalar cosine) -- out of scope for BATCHING, in
# scope for parity, because `fetch_candidates_batch` serves it and a future caller will use it.
_SHAPES = {"fill": True, "probe": False}


# ── deck + node population ────────────────────────────────────────────────────────────────────────────
def _rows(path: str) -> list[dict]:
    """(id, question, asof) per deck row. `queries:` is the frozen deck schema both files share."""
    import yaml
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    out = []
    for q in (doc.get("queries") or []):
        if not isinstance(q, dict) or not q.get("id"):
            continue
        out.append({"id": str(q["id"]), "question": str(q.get("question") or q.get("query") or ""),
                    "asof": (str(q["asof"]) if q.get("asof") else None)})
    return [r for r in out if r["question"]]


def _population(limit: int | None = None) -> list[str]:
    """The node SUPERSET: every commodity node + every alias-reachable driver slice, sorted."""
    from leviathan.graphrag import evidence as ev
    nodes = sorted(set(ev.all_nodes()))
    slices = sorted({f"drivers/{s}" for s in ev.backed_slice_names()})
    pop = nodes + slices
    return pop[:limit] if limit else pop


# ── the SQL-capturing connection wrapper (so the harness never re-writes pgstore's statements) ────────
class _RecCur:
    def __init__(self, cur, owner):
        self._c, self._o = cur, owner

    def __enter__(self):
        self._c.__enter__()
        return self

    def __exit__(self, *a):
        return self._c.__exit__(*a)

    def execute(self, sql, params=None):
        self._o.sqls.append((sql, dict(params or {})))
        return self._c.execute(sql, params)

    def fetchall(self):
        return self._c.fetchall()


class _RecConn:
    """Passed to pgstore as an explicit `conn=`, so the statements are pgstore's own and this file only
    watches them go by. Also the EXPLAIN source: the last SQL of each kind is replayed under ANALYZE."""

    def __init__(self, conn):
        self._conn = conn
        self.sqls: list = []

    def cursor(self):
        return _RecCur(self._conn.cursor(), self)

    def explain(self, sql: str, params: dict) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + sql, params)
            return [r[0] for r in cur.fetchall()]


# ── the comparator ────────────────────────────────────────────────────────────────────────────────────
def compare_node(node: str, single: list[dict], batch: list[dict], *, tol: float) -> list[dict]:
    """Every divergence between one node's per-node rows and its batched rows, verbatim.

    Returns [] when the two reads are the same evidence set in the same order. Written as a free
    function with no pg in it so `--self-test` can prove it DETECTS injected divergences -- a comparator
    that has only ever been run on matching inputs is not evidence of anything (the EC-3 review's lesson
    about a pin that was green in the passing world and in the failing one alike)."""
    out: list[dict] = []
    ids_s = [r.get("id") for r in single]
    ids_b = [r.get("id") for r in batch]
    if ids_s != ids_b:
        out.append({"node": node, "kind": "id_sequence", "single": ids_s, "batch": ids_b})
        return out                                            # sequence differs -> per-row diffing is noise
    for i, (a, b) in enumerate(zip(single, batch)):
        if set(a) != set(b):
            out.append({"node": node, "kind": "keys", "row": i, "id": a.get("id"),
                        "single": sorted(a), "batch": sorted(b)})
            continue
        for key in sorted(a):
            av, bv = a[key], b[key]
            if key == "score":
                try:
                    if abs(float(av) - float(bv)) <= tol:
                        continue
                except (TypeError, ValueError):
                    pass
                out.append({"node": node, "kind": "score", "row": i, "id": a.get("id"),
                            "single": av, "batch": bv, "tol": tol})
            elif av != bv:
                out.append({"node": node, "kind": key, "row": i, "id": a.get("id"),
                            "single": av, "batch": bv})
    return out


# ── the run ───────────────────────────────────────────────────────────────────────────────────────────
def _run_deck(deck: str, rows: list[dict], pop: list[str], rc, *, fetch_k: int, chunk: int,
              shapes: list[str], tol: float, cap: int, explain_into: dict) -> dict:
    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag import pgstore as pgs
    res = {"deck": deck, "n_rows": len(rows), "n_nodes": len(pop), "shapes": shapes,
           "rows": [], "divergences": [], "n_divergences": 0, "divergences_truncated": 0}
    for row in rows:
        qv = ev.embed([row["question"]])[0]
        rowrec = {"id": row["id"], "asof": row["asof"], "n_divergences": 0, "shapes": {}}
        for shape in shapes:
            with_vectors = _SHAPES[shape]
            t0 = time.time()
            rc.sqls.clear()
            batch = pgs.fetch_candidates_batch(qv, row["question"], pop, asof=row["asof"],
                                               fetch_k=fetch_k, hybrid=True, with_vectors=with_vectors,
                                               chunk=chunk, conn=rc)
            n_batch_stmts = len(rc.sqls)
            if shape not in explain_into and rc.sqls:
                explain_into[shape] = {"batch_sql": rc.sqls[-1][0],
                                       "batch_plan": rc.explain(*rc.sqls[-1])}
            t1 = time.time()
            rc.sqls.clear()
            single = {}
            for n in pop:
                single[n] = pgs.fetch_candidates(qv, row["question"], n, asof=row["asof"],
                                                 fetch_k=fetch_k, hybrid=True, conn=rc,
                                                 with_vectors=with_vectors)
            n_single_stmts = len(rc.sqls)
            if rc.sqls and "single_sql" not in explain_into.get(shape, {}):
                explain_into.setdefault(shape, {})["single_sql"] = rc.sqls[-1][0]
                explain_into[shape]["single_plan"] = rc.explain(*rc.sqls[-1])
            t2 = time.time()
            divs: list[dict] = []
            # A node ABSENT from the batch map means its chunk's statement RAISED: the batch does not
            # re-fetch it (the caller does, at its own concurrency -- see fetch_candidates_batch). That is
            # a degrade, not a row-level disagreement, so it is counted and named as itself rather than
            # arriving as a pile of "missing row" divergences with no cause attached.
            unserved = [n for n in pop if n not in batch]
            for n in pop:
                if n in batch:
                    divs += compare_node(n, single.get(n, []), batch.get(n, []), tol=tol)
            for n in unserved:
                divs.append({"node": n, "kind": "chunk_unserved", "row": -1, "id": None,
                             "single": len(single.get(n, [])), "batch": None})
            n_rows_cmp = sum(len(v) for v in single.values())
            rowrec["shapes"][shape] = {
                "n_rows": n_rows_cmp, "n_divergences": len(divs), "n_unserved": len(unserved),
                "n_batch_statements": n_batch_stmts, "n_single_statements": n_single_stmts,
                "batch_s": round(t1 - t0, 3), "single_s": round(t2 - t1, 3),
                "nodes_with_rows": sum(1 for v in single.values() if v)}
            rowrec["n_divergences"] += len(divs)
            for d in divs:
                d = dict(d, row_id=row["id"], shape=shape)
                if len(res["divergences"]) < cap:
                    res["divergences"].append(d)
                else:
                    res["divergences_truncated"] += 1
            res["n_divergences"] += len(divs)
        res["rows"].append(rowrec)
        print(f"[ec2-parity] {deck} {row['id']}: divergences={rowrec['n_divergences']}", flush=True)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EC-2 batched-vs-per-node evidence parity pin")
    ap.add_argument("--decks", default=f"{_P6_DECK},{_ESC_DECK}")
    ap.add_argument("--rows", default="", help="comma-separated row ids to restrict to (default: all)")
    ap.add_argument("--shapes", default="fill,probe", help="fill (vector payload) and/or probe (cosine)")
    ap.add_argument("--fetch-k", type=int, default=60)
    ap.add_argument("--chunk", type=int, default=0, help="0 = pgstore's shipped _BATCH_CHUNK")
    ap.add_argument("--max-nodes", type=int, default=0, help="0 = the whole node superset")
    ap.add_argument("--tol", type=float, default=1e-6, help="float4 tolerance for the `score` key only")
    ap.add_argument("--max-divergences", type=int, default=200)
    ap.add_argument("--out", default="")
    ap.add_argument("--self-test", action="store_true", help="comparator self-test on synthetic rows; no pg")
    a = ap.parse_args(argv)

    if a.self_test:
        return _self_test()

    if not os.environ.get("EVIDENCE_PG_DSN"):
        print("EVIDENCE_PG_DSN is not set. This harness reads the evidence Postgres directly and can "
              "only run inside the VPC (submit it on the evidence-build jobdef, which injects the DSN "
              "secret). Run --self-test for the offline comparator check.")
        return 2

    import psycopg
    from leviathan.graphrag import pgstore as pgs
    shapes = [s.strip() for s in a.shapes.split(",") if s.strip() in _SHAPES]
    if not shapes:
        print("no valid --shapes (expected fill and/or probe)")
        return 2
    only = {r.strip() for r in a.rows.split(",") if r.strip()}
    pop = _population(a.max_nodes or None)
    chunk = a.chunk or pgs._BATCH_CHUNK
    conn = psycopg.connect(pgs.dsn(), autocommit=True)
    rc = _RecConn(conn)
    explain: dict = {}
    out = {"item": "EC-2", "clause": "(b) evidence-set parity, ordered", "ts": time.strftime("%Y%m%dT%H%M%SZ",
                                                                                            time.gmtime()),
           "table": pgs.table_name(), "fetch_k": a.fetch_k, "chunk": chunk, "tol": a.tol,
           "n_nodes": len(pop), "nodes": pop, "decks": [], "n_divergences": 0}
    for deck in [d.strip() for d in a.decks.split(",") if d.strip()]:
        rows = [r for r in _rows(deck) if not only or r["id"] in only]
        d = _run_deck(deck, rows, pop, rc, fetch_k=a.fetch_k, chunk=chunk, shapes=shapes, tol=a.tol,
                      cap=a.max_divergences, explain_into=explain)
        out["decks"].append(d)
        out["n_divergences"] += d["n_divergences"]
    out["explain"] = explain
    out["verdict"] = "PASS" if out["n_divergences"] == 0 else "FAIL"
    print(f"[ec2-parity] VERDICT={out['verdict']} divergences={out['n_divergences']} "
          f"nodes={len(pop)} decks={len(out['decks'])}", flush=True)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
        print(f"[ec2-parity] wrote {a.out}", flush=True)
    return 0 if out["n_divergences"] == 0 else 1


# ── --self-test: the comparator, on synthetic rows, offline ──────────────────────────────────────────
def _self_test() -> int:
    """Proves the comparator DETECTS each divergence class it claims to cover. Runs anywhere: no pg, no
    AWS, no embedder. A parity pin whose comparator has only ever seen matching inputs proves nothing."""
    def r(i, **over):
        row = {"id": f"a-{i}", "source": "GAIN", "source_key": f"s3://a/{i}", "date": "2021-07-20",
               "event_date": None, "text": f"row {i}", "vector": [1.0, 0.0]}
        row.update(over)
        return row

    base = [r(0), r(1), r(2)]
    checks = []
    checks.append(("identical", compare_node("a", base, [dict(x) for x in base], tol=1e-6), 0))
    checks.append(("reorder", compare_node("a", base, [base[1], base[0], base[2]], tol=1e-6), 1))
    checks.append(("missing_row", compare_node("a", base, base[:2], tol=1e-6), 1))
    checks.append(("text_drift", compare_node("a", base, [r(0), r(1, text="CHANGED"), r(2)], tol=1e-6), 1))
    checks.append(("vector_drift", compare_node("a", base, [r(0), r(1, vector=[1.0, 0.5]), r(2)],
                                                tol=1e-6), 1))
    checks.append(("keys", compare_node("a", [r(0)], [{k: v for k, v in r(0).items() if k != "text"}],
                                        tol=1e-6), 1))
    s = [{"id": "a-0", "score": 0.5000000}]
    checks.append(("score_within_tol", compare_node("a", s, [{"id": "a-0", "score": 0.5000001}],
                                                    tol=1e-6), 0))
    checks.append(("score_beyond_tol", compare_node("a", s, [{"id": "a-0", "score": 0.6}], tol=1e-6), 1))
    checks.append(("empty_both", compare_node("a", [], [], tol=1e-6), 0))
    checks.append(("empty_vs_rows", compare_node("a", base, [], tol=1e-6), 1))
    bad = 0
    for name, divs, want in checks:
        ok = len(divs) == want
        bad += 0 if ok else 1
        print(f"[self-test] {name}: divergences={len(divs)} expected={want} {'ok' if ok else 'FAILED'}")
    # ...and the deck reader, on the real frozen decks (pure yaml; no pg, no network).
    for deck in (_P6_DECK, _ESC_DECK):
        if os.path.exists(deck):
            rows = _rows(deck)
            print(f"[self-test] {deck}: rows={len(rows)} first={rows[0]['id'] if rows else '-'}")
            if not rows:
                bad += 1
    print(f"[self-test] {'PASS' if not bad else 'FAIL'} ({bad} failing checks)")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
