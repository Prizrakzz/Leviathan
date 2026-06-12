"""Feature engineering for the gold/feature_spine layer.

Modules
-------
calendar    — crop calendars: stage windows, crop-year date arithmetic
registry    — declarative feature registry loaded from configs/features/
visibility  — the single implementation of the point-in-time alignment rule
extractors  — silver readers with footer probing and input contracts
computations — pure feature functions, dispatched by family name
spine       — observation grid construction, assembly, output validation
ddl         — Athena DDL generation for gold_feature_spine
"""
