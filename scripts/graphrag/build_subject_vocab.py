"""SUBJECT RESOLVER -- the DRIVER VOCABULARY artifact (design: docs/private/SUBJECT_RESOLVER_SITTING_2026-09-09.md D7).

WHY AN ARTIFACT AND NOT A BOOT COMPUTATION. The resolver's semantic tier scores a user's phrase against every
driver's own prose with the SERVING embedder (bge-m3, in-process, `EVIDENCE_EMBED_BACKEND=bge_local`). Measured
2026-09-09 on a CPU box: 1.4 texts/s -> the 4,000-text vocabulary would take 20-48 minutes at boot against an ECS
health-check grace of 300 s. So the matrix is built HERE, once per graph, stamped with `graph.causal_graph_version()`
(a sha over the causal YAML bytes), and shipped beside the DAGs it was built from: `configs/graphrag/` is the
gitignored overlay the serving image bakes from the live tree, so the artifact rides the SAME image as the graph
that produced it, and a hash mismatch at load is a stale artifact by construction (the loader declines the semantic
tier and says so; `config_check` reds the build).

WHAT IS EMBEDDED. For every driver INSTANCE on every board, four texts: the id in reader form ('El_Nino' -> 'El
Nino'), the blurb, the mechanism and the evidence_query. Distinct (id, field, text) rows are kept -- the same id
carries a DIFFERENT blurb on each board it sits on (166 of 405 ids; El_Nino carries 35), and the resolver scores an
id by the MAX over its rows, never a mean, so no board's phrasing is lost and none dilutes another. 33 ids are opaque
acronyms (HLB, RFS, DMO, ...) reachable ONLY through their prose -- the reason the id string alone is not enough.

THE CONTRACT (the loader in state/subject.py reads exactly this):
  <out>.npz              V          float32 [n_rows, 1024], unit-norm rows (cosine == dot)
                         ids        <U       driver id per row
                         fields     <U       one of id | blurb | mechanism | evidence_query
                         texts      <U       the embedded text per row
                         graph_hash 0-d <U   graph.causal_graph_version() of the YAMLs read
                         model      0-d <U   the embedder name
  <out>.meta.json        the same stamp plus counts, wall seconds and the max_seq_length used

USAGE (ASCII stdout; ~30-50 min on a CPU laptop for the full vocabulary):
  python scripts/graphrag/build_subject_vocab.py                 # -> configs/graphrag/subject_vocab.npz
  python scripts/graphrag/build_subject_vocab.py --check         # 0 if the artifact matches the live graph
  python scripts/graphrag/build_subject_vocab.py --limit 40 --out <tmp>.npz   # a smoke build for tests
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_OUT = ROOT / "configs" / "graphrag" / "subject_vocab.npz"
FIELDS = ("id", "blurb", "mechanism", "evidence_query")
CHUNK = 128


def say(msg: str) -> None:
    print(msg.encode("ascii", "replace").decode(), flush=True)


def reader_form(driver_id: str) -> str:
    """'El_Nino' -> 'El Nino'; 'USD_index' -> 'USD index'. Case is kept: an acronym stays an acronym."""
    return driver_id.replace("_", " ").strip()


def vocabulary_rows(contracts: dict) -> list[tuple[str, str, str]]:
    """Distinct (driver_id, field, text) rows over every driver instance, in a deterministic order."""
    seen: set[tuple[str, str, str]] = set()
    rows: list[tuple[str, str, str]] = []
    for cid in sorted(contracts):
        for d in contracts[cid].drivers:
            cand = (("id", reader_form(d.id)), ("blurb", d.blurb), ("mechanism", d.mechanism),
                    ("evidence_query", d.evidence_query))
            for field, text in cand:
                text = (text or "").strip()
                if not text:
                    continue
                key = (d.id, field, text)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(key)
    return rows


def artifact_status(path: Path = DEFAULT_OUT) -> tuple[str, str, str]:
    """('ok' | 'missing' | 'stale' | 'unreadable', artifact_hash, live_hash) -- the loader's and lint's one question."""
    from leviathan.graphrag import graph as G
    live = G.causal_graph_version()
    meta = Path(str(path).replace(".npz", ".meta.json"))
    if not path.exists() or not meta.exists():
        return "missing", "", live
    try:
        stamped = json.loads(meta.read_text(encoding="utf-8")).get("graph_hash", "")
    except Exception:  # noqa: BLE001 -- a corrupt sidecar is 'unreadable', never a crash at import time
        return "unreadable", "", live
    return ("ok" if stamped == live else "stale"), stamped, live


def build(out: Path, limit: int | None = None) -> dict:
    import numpy as np
    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag import graph as G

    backend = os.environ.get("EVIDENCE_EMBED_BACKEND", "bge_local")
    if backend != "bge_local":
        raise SystemExit("the vocabulary must be embedded by the SERVING embedder (bge_local); got %r" % backend)
    t0 = time.time()
    contracts = G.load_contracts()
    graph_hash = G.causal_graph_version()
    rows = vocabulary_rows(contracts)
    n_ids_all = len({r[0] for r in rows})
    if limit:
        rows = rows[:limit]
    say("graph %s: %d contracts, %d distinct driver ids, %d vocabulary rows%s" % (
        graph_hash, len(contracts), n_ids_all, len(rows), (" (limit %d)" % limit) if limit else ""))
    per_field = {f: sum(1 for r in rows if r[1] == f) for f in FIELDS}
    say("rows per field: " + ", ".join("%s=%d" % kv for kv in per_field.items()))

    texts = [r[2] for r in rows]
    ev._bge_local(["warm"])                                    # load the singleton once, single-threaded
    tok = ev._bge.tokenizer
    max_tokens = max(len(x) for x in tok(texts, truncation=False, add_special_tokens=True)["input_ids"])
    seq = int(min(512, max(64, max_tokens + 4)))
    ev._bge.max_seq_length = seq                               # short texts: attention cost falls with the pad width
    say("model %s loaded in %.1fs; longest text %d tokens -> max_seq_length %d" % (
        ev.BGE_MODEL, time.time() - t0, max_tokens, seq))

    vecs = []
    t1 = time.time()
    for i in range(0, len(texts), CHUNK):
        chunk = texts[i:i + CHUNK]
        if len(chunk) == 1:                                    # never the single-text memo path
            chunk = chunk + chunk
            vecs.extend(ev.embed(chunk)[:1])
        else:
            vecs.extend(ev.embed(chunk))
        done = min(i + CHUNK, len(texts))
        rate = done / max(time.time() - t1, 1e-6)
        say("  embedded %d / %d  (%.1f texts/s, eta %.0fs)" % (done, len(texts), rate, (len(texts) - done) / max(rate, 1e-6)))
    V = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(V, axis=1)
    if V.shape[1] != 1024 or not np.allclose(norms, 1.0, atol=1e-3):
        raise SystemExit("embedder contract broken: shape %s, norm range %.4f..%.4f" % (V.shape, norms.min(), norms.max()))

    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, V=V, ids=np.array([r[0] for r in rows]), fields=np.array([r[1] for r in rows]),
             texts=np.array(texts), graph_hash=np.array(graph_hash), model=np.array(ev.BGE_MODEL))
    meta = {"graph_hash": graph_hash, "model": ev.BGE_MODEL, "dim": int(V.shape[1]), "n_rows": int(V.shape[0]),
            "n_ids": len({r[0] for r in rows}), "n_ids_in_graph": n_ids_all, "n_contracts": len(contracts),
            "per_field": per_field, "max_seq_length": seq, "limit": limit,
            "built_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "seconds": round(time.time() - t0, 1), "producer": "scripts/graphrag/build_subject_vocab.py"}
    Path(str(out).replace(".npz", ".meta.json")).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    say("WROTE %s (%.1f MB) + sidecar; %d rows x %d; %.0fs total" % (
        out, out.stat().st_size / 1e6, V.shape[0], V.shape[1], meta["seconds"]))
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--limit", type=int, default=None, help="embed only the first N rows (smoke builds)")
    ap.add_argument("--check", action="store_true", help="report the artifact's status against the live graph and exit")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if a.check:
        status, stamped, live = artifact_status(out)
        say("subject_vocab %s: artifact=%s live=%s (%s)" % (status.upper(), stamped or "-", live, out))
        return 0 if status == "ok" else 1
    build(out, a.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
