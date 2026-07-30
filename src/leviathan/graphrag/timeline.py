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

# W4 / skeptic F-I. The marker rendered IN PLACE of a receipt for an episode the retrieved top-K
# carried no in-window prop for. It is the whole F-I mitigation: the episode is NOT dropped (its `n`
# is a PIT recount of real prop dates, so dropping would make the corpus look THINNER than it is and
# would silently delete exactly the old/thin/single-source episodes W4's honesty leg exists to
# enumerate), it is STATED. Absence stated beats absence hidden. The wording is deliberately an
# instruction, not a label -- it is the last thing the reasoner reads about that episode.
_NO_RECEIPT = "NO CITABLE ITEM IN THIS WINDOW -- state that and do not narrate what happened"


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


def episodes_for(node: str, asof, *, max_n: int = MAX_PER_NODE, evidence: list | None = None) -> list[dict]:
    """PIT-filtered episodes for a slice: recount from prop dates <= asof, drop empty, biggest first.
    No asof -> nothing (an undated 'now' cannot anchor a timeline honestly).

    DEFAULT OFF (measured 2026-07-04: episode COUNTS without content invited uncited confabulation —
    the reasoner narrated "what happened" in an episode it had no text for; +10 halluc on 19 turns
    while citation-integrity strips stayed flat). Set GRAPHRAG_TIMELINE=on to enable the RECEIPTED
    path: `evidence` (the dated props ground() already fetched for this node) supplies one in-window
    prop per episode as a citable RECEIPT, so the reasoner has text to cite instead of invent.

    THE RECEIPT IS BEST-EFFORT, AND IT FAILS ASYMMETRICALLY (skeptic F-I, 2026-07-29). `evidence` is a
    semantic top-K over the QUERY, so the episodes least likely to contain an in-window prop are the
    old, thin, single-source ones -- Brazil frost 1994 (11 props, wb_cmo_outlook only), USSR 1972-79
    (33), grain-deal suspension 2023 (14). Those are precisely the episodes W4's honesty leg is built
    around, and a counted-but-unreceipted episode IS the original +10-hallucination mode rather than
    the fix for it. MITIGATION CHOSEN: state the absence (`_NO_RECEIPT` in render_line), do NOT drop
    the episode. Dropping was rejected because `n` is a PIT RECOUNT of real prop dates, not a
    retrieval result -- a receipt-less 1994 frost would vanish from the count and the answer's own
    "the record holds N episodes" headline would understate the corpus it is meant to be honest
    about. Every emitted episode therefore carries a receipt OR a rendered statement that it has
    none; nothing is emitted silently."""
    if os.environ.get("GRAPHRAG_TIMELINE", "off") != "on":
        return []
    asof_d = _parse(asof)
    if asof_d is None:
        return []
    ev_by_date = sorted(((str(h.get("date") or "")[:10], (h.get("text") or "")) for h in (evidence or [])
                         if _parse(h.get("date"))), key=lambda x: x[0])
    out = []
    for ep in _load().get(node) or []:
        vis = [d for d in ep.get("dates") or [] if (_parse(d) or _dt.date.max) <= asof_d]
        if not vis:
            continue
        start, end = vis[0], vis[-1]
        receipt = None                                             # newest evidence prop inside [start, end]
        for d, txt in ev_by_date:
            if start <= d <= end and txt:
                receipt = {"date": d, "text": txt[:180]}
        out.append({"start": start, "end": end, "n": len(vis), "receipt": receipt})
    out.sort(key=lambda e: -e["n"])
    return out[:max_n]


def render_line(label: str, eps: list[dict]) -> str:
    """One prompt line per node. Every episode renders EITHER its citable receipt OR `_NO_RECEIPT` --
    a bare count is never emitted (F-I: the bare count with no marker was the confabulation invitation)."""
    parts = []
    for e in eps:
        span = f"{e['start'][:7]}..{e['end'][:7]} ({e['n']} reports"
        r = e.get("receipt")
        span += f'; e.g. {r["date"]}: "{r["text"]}")' if r else f"; {_NO_RECEIPT})"
        parts.append(span)
    return "DATED EPISODES for " + label + " (report TIMESTAMPS, not descriptions): " + ", ".join(parts)


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
