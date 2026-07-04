"""Registry <-> Glue projection lint — the config-time guardrail for the Jul-2026 S3 LIST storm class.

Athena PARTITION PROJECTION computes a candidate-partition grid instead of consulting the catalog;
any query that doesn't constrain a projected axis with a SARGABLE predicate makes Athena probe the
grid — one S3 LIST per candidate (silver_esr: 6.1M candidates over ~350 real partitions -> $134 in
two days; silver_wasde: 19.5K over 461). This lint FAILS when a numbers-registry table is projected
and the spec doesn't declare pruning discipline for every projected axis, so the next projected
table cannot silently join the registry unguarded.

Coverage rules per projected axis (column):
  - listed in spec.partition_cols        -> hard equality (raises at query build if missing)  OK
  - spec.commodity_code_col               -> equality emitted when the slug maps               OK
  - spec.vintage_partition_col            -> native (never CAST) as-of bound emitted           OK
  - spec.commodity_col / spec.period_col  -> plain equality lands ON the axis when the arg is
                                             given (silver_production) — conditional coverage  OK
  - spec.year_col (year_month semantics)  -> sargable bare-column bounds ride with the guard   OK
  - spec.month_col (year_month semantics) -> bounded via the year axis (<=12x residual)        OK
  - anything else                         -> FAIL

Run:  python -m leviathan.graphrag.numbers.lint     (needs Glue read access; ~free)
Exit 0 = every registry table safe; exit 1 = violations printed.
"""
from __future__ import annotations

import sys

from leviathan.graphrag.numbers.registry import TableSpec, load_registry

GLUE_DB = "leviathan_dev"


def _projected_axes(params: dict) -> list[str]:
    """Column names with projection.<col>.* config (only meaningful when projection.enabled=true)."""
    if str(params.get("projection.enabled", "")).lower() != "true":
        return []
    cols = {k.split(".")[1] for k in params if k.startswith("projection.") and k.count(".") >= 2}
    return sorted(cols)


def _covered(ts: TableSpec, col: str) -> bool:
    if col in ts.partition_cols or col == ts.commodity_code_col or col == ts.vintage_partition_col:
        return True
    if col in (ts.commodity_col, ts.period_col):
        return True                                   # plain equality lands ON the axis when given
    if col in (ts.year_col, ts.month_col) and ts.year_col:
        return True                                   # sargable year bounds always emitted when
    return False                                      # year_col is declared; month rides within them


def lint_registry(glue=None, *, db: str = GLUE_DB) -> list[str]:
    """Returns violation strings (empty = clean). `glue` injectable for tests."""
    if glue is None:
        import boto3
        glue = boto3.client("glue", region_name="us-east-1")
    problems: list[str] = []
    for tid, ts in sorted(load_registry().tables.items()):
        physical = ts.athena_table or tid
        try:
            params = glue.get_table(DatabaseName=db, Name=physical)["Table"].get("Parameters", {})
        except Exception as e:  # noqa: BLE001 — a missing table is itself a violation
            problems.append(f"{tid}: physical table {db}.{physical} not readable ({type(e).__name__})")
            continue
        for col in _projected_axes(params):
            if not _covered(ts, col):
                problems.append(
                    f"{tid}: {db}.{physical} projects partition axis '{col}' but the spec declares no "
                    f"pruning discipline for it (partition_cols / commodity_code_col / "
                    f"vintage_partition_col) — queries would enumerate the projected grid "
                    f"(S3 LISTs, Jul-2026 storm class)")
    return problems


def main() -> None:
    problems = lint_registry()
    if problems:
        print("REGISTRY PROJECTION LINT: FAIL")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("REGISTRY PROJECTION LINT: OK — every projected axis has pruning discipline")


if __name__ == "__main__":
    main()
