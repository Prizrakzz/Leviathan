"""Numbers layer — the observed-value SQL agent for GraphRAG v2.

Looks up the ACTUAL numbers (exports, PSD supply/demand, weather, production, balance sheets) from the Athena
data lake, point-in-time correct (as-known-at-asof), with per-value provenance. This is the observed data, NOT
the engineered `_z` features (which live in gold/feature_spine). The LLM never writes SQL — it emits a typed
NumberQuery; a deterministic builder turns it into leakage-safe Athena SQL.
"""
