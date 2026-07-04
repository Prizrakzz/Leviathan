"""Event timeline — the Architecture-v2 layer-2 promise, derived free from the prop store.

The reasoner has 279K dated props but no EPISODE structure over them, so on temporal questions it
either fabricates dates or stays timid ("stays fully hypothetical" while the July-2021 frost sits in
our own corpus — the measured failure). This module clusters each slice's props into dated episodes
("frost@arabica: 1994-06..1994-08 (7 props), 2021-06..2021-08 (11 props)") once, offline, with zero
LLM spend and zero re-chunking; serving attaches a one-line episode list per grounded node.

POINT-IN-TIME BY CONSTRUCTION: the artifact stores each episode's PROP DATES, and serving recomputes
span/count from dates <= asof, dropping empty episodes — a future prop can never leak into a shown
count. Kill switch GRAPHRAG_TIMELINE=off; a missing/broken artifact renders nothing and breaks nothing.
"""
from __future__ import annotations

import datetime as _dt
import json
import os

from leviathan.graphrag import params as _pr

GAP_DAYS = int(_pr.get("serving.timeline.gap_days", 90))
MAX_PER_NODE = int(_pr.get("serving.timeline.max_per_node", 4))
_ARTIFACT = "timeline/episodes.json"
_CACHE: dict | None = None


def _parse(d) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(str(d)[:10])
    except (TypeError, ValueError):
        return None


def cluster(dates: list, gap_days: int = GAP_DAYS) -> list[dict]:
    """Sorted date strings -> episodes split where consecutive props are > gap_days apart."""
    ds = sorted({d for d in (_parse(x) for x in dates) if d})
    episodes, cur = [], []
    for d in ds:
        if cur and (d - cur[-1]).days > gap_days:
            episodes.append(cur)
            cur = []
        cur.append(d)
    if cur:
        episodes.append(cur)
    return [{"start": e[0].isoformat(), "end": e[-1].isoformat(),
             "dates": [x.isoformat() for x in e]} for e in episodes]


def derive(*, conn=None, query_fn=None) -> dict:
    """Build {slice: [episodes]} for EVERY slice in the prop store — one SQL over pg (S3 flat is the
    fallback path via evidence.load_index, but pg holds the same 279K props and answers in seconds).
    Uses event_date when the chunker recovered one (WHEN it happened), else the doc date."""
    rows = None
    if query_fn is not None:
        rows = query_fn("SELECT node, COALESCE(CAST(event_date AS varchar), CAST(date AS varchar)) AS d "
                        "FROM evidence_props")
    else:
        from leviathan.graphrag import pgstore as pg
        c = conn or pg.connect()
        with c.cursor() as cur:
            cur.execute("SELECT node, COALESCE(event_date, date) FROM evidence_props")
            rows = [{"node": r[0], "d": r[1]} for r in cur.fetchall()]
    by_node: dict[str, list] = {}
    for r in rows:
        by_node.setdefault(r["node"], []).append(r["d"])
    return {node: cluster(dates) for node, dates in sorted(by_node.items())}


def write_artifact(episodes: dict) -> str:
    """Persist to the evidence store (s3://.../graphrag_evidence/timeline/episodes.json)."""
    base = os.environ.get("EVIDENCE_S3", "")
    body = json.dumps(episodes)
    if base.startswith("s3://"):
        import boto3
        bucket, _, prefix = base[5:].partition("/")
        key = f"{prefix.rstrip('/')}/{_ARTIFACT}"
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))
        return f"s3://{bucket}/{key}"
    path = os.path.join(base or ".", _ARTIFACT)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            override = os.environ.get("GRAPHRAG_TIMELINE_PATH")
            base = os.environ.get("EVIDENCE_S3", "")
            if override:
                _CACHE = json.load(open(override, encoding="utf-8"))
            elif base.startswith("s3://"):
                import boto3
                bucket, _, prefix = base[5:].partition("/")
                obj = boto3.client("s3").get_object(Bucket=bucket, Key=f"{prefix.rstrip('/')}/{_ARTIFACT}")
                _CACHE = json.loads(obj["Body"].read())
            else:
                _CACHE = json.load(open(os.path.join(base or ".", _ARTIFACT), encoding="utf-8"))
        except Exception:  # noqa: BLE001 — no artifact -> no timeline lines, never a broken answer
            _CACHE = {}
    return _CACHE


def reset_cache() -> None:
    global _CACHE
    _CACHE = None


def episodes_for(node: str, asof, *, max_n: int = MAX_PER_NODE) -> list[dict]:
    """PIT-filtered episodes for a slice: recount from prop dates <= asof, drop empty, biggest first.
    No asof -> nothing (an undated 'now' cannot anchor a timeline honestly)."""
    if os.environ.get("GRAPHRAG_TIMELINE", "on") == "off":
        return []
    asof_d = _parse(asof)
    if asof_d is None:
        return []
    out = []
    for ep in _load().get(node) or []:
        vis = [d for d in ep.get("dates") or [] if (_parse(d) or _dt.date.max) <= asof_d]
        if vis:
            out.append({"start": vis[0], "end": vis[-1], "n": len(vis)})
    out.sort(key=lambda e: -e["n"])
    return out[:max_n]


def render_line(label: str, eps: list[dict]) -> str:
    spans = ", ".join(f"{e['start'][:7]}..{e['end'][:7]} ({e['n']} props)" for e in eps)
    return f"DATED EPISODES for {label} (as-known at the as-of): {spans}"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Derive the prop-store event timeline (free, no LLM)")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()
    if not args.run:
        print("dry: pass --run to derive + write the artifact")
        return 0
    from leviathan.common import config
    config.load_env()
    eps = derive()
    n_ep = sum(len(v) for v in eps.values())
    dest = write_artifact(eps)
    print(f"derived {n_ep} episodes across {len(eps)} slices -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
