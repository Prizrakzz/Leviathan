"""Shared MPOC (Malaysian Palm Oil Council) silver primitives (SILVER-F052 + F053/F054/F055).

The three ``silver_mpoc_*`` tables are C-WRONG-8 half-orphans: ``jobs/ingest/fetch_mpoc.py`` writes
raw HTML only; no bronze->silver producer was tracked. This package restores them on ONE shared
source/versioning + HTML-normalization adapter (F052) so a refresh cannot erase prior evidence and
country/unit/table-identity normalization has a single authority.
"""
