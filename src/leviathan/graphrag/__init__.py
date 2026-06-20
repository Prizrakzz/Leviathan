"""Leviathan GraphRAG — temporal knowledge graph over the document corpus.

Phase 1 (foundation) lives here: the data **contracts** (this package's `contracts`
module) are the single source of truth for every parquet artifact the indexing and
query layers exchange. The proprietary configuration (entity vocabulary, path
templates, params, gold sets) lives under the git-ignored ``configs/graphrag/`` — the
code is public; the domain knowledge is not. See GRAPHRAG_PLAN.md (git-ignored).
"""
