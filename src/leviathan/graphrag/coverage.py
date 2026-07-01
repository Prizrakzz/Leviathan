"""Per-node x per-source coverage of the evidence store (free, from S3).

Reads the UNEMBEDDED chunks/ cache (no vectors -> light), re-routes each proposition through the SAME
commodity + driver matchers rebuild_slices uses, and tallies props + unique docs per (node x source). The
honest answer to "which nodes/sources are thin" — instead of arguing whether a 90-doc sample is enough.

    EVIDENCE_S3=s3://... python -m leviathan.graphrag.coverage    # -> configs/graphrag/eval/coverage_node_source.md
"""
from __future__ import annotations

import collections
from concurrent.futures import ThreadPoolExecutor

from leviathan.graphrag import answer as an
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import evidence_batch as eb
from leviathan.graphrag import extract as ex
from leviathan.graphrag import harvest as hv

_OUT = ex._CFG / "eval"
_THIN_PROPS = 500                                        # a commodity slice below this is flagged thin


def _cell():
    return [0, set()]                                    # [prop_count, {doc_keys}]


def node_source_matrix(*, workers: int = 16):
    """Route the whole chunks/ cache -> ({node: {source: cell}} commodity, {driver: {source: cell}} , n_docs).
    Uses the commodity + driver matchers, so the counts mirror what the serving slices actually contain."""
    nodes = ev.all_nodes()
    matchers = {n: hv.build_matcher(ev.match_forms(n)) for n in nodes}
    comm: dict = collections.defaultdict(lambda: collections.defaultdict(_cell))
    drv: dict = collections.defaultdict(lambda: collections.defaultdict(_cell))
    hashes = sorted(eb._cached_hashes())

    with ThreadPoolExecutor(max_workers=workers) as pool:                 # chunk loads are 1285 small S3 GETs
        for recs in pool.map(lambda h: ev.load_index(f"chunks/{h}"), hashes):
            for p in recs:
                src, key, text = p.get("source") or "?", p.get("source_key") or "", p.get("text") or ""
                for n in nodes:
                    if matchers[n].search(text):
                        c = comm[n][src]; c[0] += 1; c[1].add(key)
                for dn in ev.driver_slices_for(text):
                    c = drv[dn][src]; c[0] += 1; c[1].add(key)
    return comm, drv, len(hashes)


def _totals(cells: dict) -> tuple[int, int, list]:
    """(props, unique-docs, tiers-present) for one node's {source: cell} map."""
    props = sum(c[0] for c in cells.values())
    docs = len(set().union(*[c[1] for c in cells.values()])) if cells else 0
    tiers = sorted({an.source_tier(s) for s in cells})
    return props, docs, tiers


def report(comm: dict, drv: dict, ndocs: int) -> str:
    L = ["# Evidence coverage — per-node x per-source", "",
         f"Routed the **{ndocs}-doc** chunk cache through the commodity + driver matchers (props mirror the "
         "serving slices). `Tn` = source-trust tier (T1 official balance-sheet > T4 macro outlook).", ""]

    # ── commodity nodes ──────────────────────────────────────────────────────────
    L += ["## Commodity nodes", "", "| node | props | docs | #src | tiers | top sources (props) |",
          "|---|--|--|--|--|---|"]
    thin, no_t1 = [], []
    for n in sorted(comm):
        cells = comm[n]
        props, docs, tiers = _totals(cells)
        top = sorted(cells.items(), key=lambda kv: -kv[1][0])[:3]
        L.append(f"| {n} | {props} | {docs} | {len(cells)} | {','.join('T'+str(t) for t in tiers)} "
                 f"| {', '.join(f'{s}:{c[0]}' for s, c in top)} |")
        if props < _THIN_PROPS:
            thin.append(f"{n}({props})")
        if 1 not in tiers:
            no_t1.append(n)

    # ── sources (across all commodity nodes) ─────────────────────────────────────
    src_props: dict = collections.Counter()
    src_docs: dict = collections.defaultdict(set)
    src_nodes: dict = collections.defaultdict(set)
    for n, cells in comm.items():
        for s, c in cells.items():
            src_props[s] += c[0]; src_docs[s] |= c[1]; src_nodes[s].add(n)
    L += ["", "## Sources (across commodity nodes)", "", "| source | tier | props | docs | #nodes |",
          "|---|--|--|--|--|"]
    for s, p in src_props.most_common():
        L.append(f"| {s} | T{an.source_tier(s)} | {p} | {len(src_docs[s])} | {len(src_nodes[s])} |")

    # ── driver slices (summary — 92 of them) ─────────────────────────────────────
    dr_rows = sorted(((dn, *_totals(cells)) for dn, cells in drv.items()), key=lambda r: -r[1])
    L += ["", f"## Driver / cascade slices ({len(drv)} populated)", "",
          "| driver slice | props | docs | tiers | (top 15 by props) |", "|---|--|--|--|--|"]
    for dn, props, docs, tiers in dr_rows[:15]:
        L.append(f"| {dn} | {props} | {docs} | {','.join('T'+str(t) for t in tiers)} | |")

    # ── thin flags (the decision output) ─────────────────────────────────────────
    L += ["", "## Thin flags (candidates for a targeted fill / re-route)", "",
          f"- **commodity nodes < {_THIN_PROPS} props:** {', '.join(thin) or 'none'}",
          f"- **commodity nodes with NO T1 (official balance-sheet) source:** {', '.join(no_t1) or 'none'}",
          f"- **single-source commodity nodes:** "
          f"{', '.join(n for n in sorted(comm) if len(comm[n]) <= 1) or 'none'}"]
    return "\n".join(L)


def main() -> int:
    from leviathan.common import config
    config.load_env()
    comm, drv, ndocs = node_source_matrix()
    _OUT.mkdir(parents=True, exist_ok=True)
    out = _OUT / "coverage_node_source.md"
    out.write_text(report(comm, drv, ndocs), encoding="utf-8")
    # ASCII-only stdout summary
    print(f"coverage: {len(comm)} commodity nodes, {len(drv)} driver slices, {ndocs} docs -> {out}")
    thinnest = sorted(comm, key=lambda n: _totals(comm[n])[0])[:5]
    print("  thinnest commodity nodes:", ", ".join(f"{n}={_totals(comm[n])[0]}" for n in thinnest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
