# dec_census — the D-EC census producers, rescued into git (2026-08-21)

These scripts produced every `data/dec_p0/` census artifact (edge_evidence, zero_route_clusters,
slice_census, graph_walk, doc_census, chunk_coverage, thin_slice_fill, projection_census
assembly) during the D-EC wave. They were authored as one-off agent scripts and survived ONLY in
a session temp scratchpad — a temp sweep away from destroying the graph-completion wave's step-1
instruments (the re-census scout's headline risk). Rescued verbatim, mirroring the
jobs/utils/dhp_census/ precedent. Scratchpad-era paths inside them are adjusted AT RE-RUN TIME
(the completion wave's re-census run book pins the exact edits: fresh chunk-cache dir, drop the
stale _raw/ leg from the co-mention corpus, widen graph_walk.ALL_NODES to ev.all_nodes(),
report forward-traversable via graph.py's production resolution, and write outputs to
data/dec_p1/ — NEVER over data/dec_p0/, the sole pre-X2 baseline).
