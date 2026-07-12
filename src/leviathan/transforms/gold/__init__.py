"""Gold-tier transforms — small, serving-shaped derived tables built ON TOP of silver.

Distinct from the deferred MLOps feature layer (leviathan.features / gold.feature_spine): these gold
tables are tall, non-projected, mirror-friendly surfaces the numbers registry serves directly. The
cascade layer is doctrinally barred from reading gold.feature_spine (silverleg.py:16-20); it MAY read
these decoupled gold tables via the registry like any other silver table.
"""
