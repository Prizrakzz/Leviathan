"""Blue-green flip of the pgvector evidence mirror — the transactional rename that makes a shadow rebuild live.

The evidence store has NO S3 fallback: a half-loaded table serves EMPTY evidence, so the mirror can never be
mutated in place under live traffic. The blue-green cycle instead builds a fully-loaded SHADOW table
(`<live>_shadow`, via `load_pg_evidence.py --table ...`), verifies its row counts, then swaps it in with a
single-transaction rename — pg DDL is transactional, so readers keep the old table until COMMIT and see the
new one immediately after, with zero window of empty evidence.

    python jobs/utils/pg_evidence_swap.py --swap --dry-run     # print the SQL, touch nothing
    python jobs/utils/pg_evidence_swap.py --swap               # flip shadow -> live (old live retained)
    python jobs/utils/pg_evidence_swap.py --rollback           # reverse the last flip (retained old -> live)
    (EVIDENCE_PG_DSN must point at the target Postgres; run in-VPC via the Batch submit.)

Table triplet (all derived from pgstore.table_name(), default `evidence_props`):
    live    = <t>            the table retrieve() reads
    shadow  = <t>_shadow     the freshly-loaded candidate (built + verified before the flip)
    old     = <t>_old        the pre-flip live table, RETAINED after a swap as the rollback artifact

SWAP (one transaction):
    DROP TABLE IF EXISTS <t>_old;                     -- discard the prior cycle's rollback artifact
    ALTER TABLE <t>        RENAME TO <t>_old;          -- current live becomes the new rollback artifact
    ALTER TABLE <t>_shadow RENAME TO <t>;              -- shadow becomes live

ROLLBACK (one transaction) — the exact reverse, restoring the pre-swap state:
    DROP TABLE IF EXISTS <t>_shadow;                  -- discard whatever now sits in the shadow slot
    ALTER TABLE <t>     RENAME TO <t>_shadow;          -- demote the (bad) live back to shadow
    ALTER TABLE <t>_old RENAME TO <t>;                 -- promote the retained old table back to live

INDEXES survive the rename: Postgres keeps every index attached to its table across ALTER TABLE ... RENAME TO
but does NOT rename the indexes themselves (verified against pgstore.init_schema, which derives index names
`<t>_node_date` / `<t>_tsv` from the table). So after a flip the live table carries indexes still named for
the shadow (`<t>_shadow_node_date`, etc.) — cosmetic only: they stay attached and functional, and the next
rebuild's `CREATE INDEX IF NOT EXISTS <shadow>_...` re-derives fresh names on the new shadow table. No index
DDL is needed here, and issuing any would risk a name clash with the retained `_old` table's indexes.

GUARD: --swap REFUSES unless the shadow table exists AND has >0 rows. A half-loaded (or missing) shadow flip
is the exact failure mode this tool exists to prevent — flipping empty evidence live is worse than not
flipping. The guard runs OUTSIDE the swap transaction (a plain read), so a refusal touches nothing.
"""
from __future__ import annotations

import argparse
import os
import sys

from leviathan.common import config

config.load_env()

from leviathan.graphrag import pgstore  # noqa: E402


def _names() -> tuple[str, str, str]:
    """(live, shadow, old) — all validated by pgstore.table_name() (lower-snake regex; injection-proof)."""
    live = pgstore.table_name()
    return live, f"{live}_shadow", f"{live}_old"


def swap_sql(live: str, shadow: str, old: str) -> list[str]:
    """The ordered statements of the flip. DROP the stale rollback artifact, demote live to old, promote
    shadow to live — the whole list runs inside ONE transaction so readers never see a torn state."""
    return [
        f"DROP TABLE IF EXISTS {old}",
        f"ALTER TABLE {live} RENAME TO {old}",
        f"ALTER TABLE {shadow} RENAME TO {live}",
    ]


def rollback_sql(live: str, shadow: str, old: str) -> list[str]:
    """The exact reverse of swap_sql: discard the current shadow slot, demote the (bad) live back to shadow,
    promote the retained old table back to live. One transaction."""
    return [
        f"DROP TABLE IF EXISTS {shadow}",
        f"ALTER TABLE {live} RENAME TO {shadow}",
        f"ALTER TABLE {old} RENAME TO {live}",
    ]


def _regclass_exists(conn, table: str) -> bool:
    """True iff `table` resolves to_regclass (a real relation in the search path). to_regclass returns NULL
    for a missing name instead of raising, so this is a safe existence probe."""
    row = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (table,)).fetchone()
    return bool(row[0])


def _row_count(conn, table: str) -> int:
    # table is regex-validated (lower-snake) and existence-checked before we reach here — safe to interpolate.
    return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def _run_txn(conn, stmts: list[str]) -> None:
    """Execute the ordered statements in ONE transaction. autocommit connections still honor an explicit
    BEGIN/COMMIT via conn.transaction() (psycopg3), so the rename set is atomic even on the pooled conn."""
    with conn.transaction():
        for s in stmts:
            conn.execute(s)


def main() -> int:
    ap = argparse.ArgumentParser(description="Blue-green flip of the pgvector evidence mirror (shadow <-> live).")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--swap", action="store_true", help="flip the shadow table live (retains the old live)")
    mode.add_argument("--rollback", action="store_true", help="reverse the last flip (retained old -> live)")
    ap.add_argument("--dry-run", action="store_true", help="print the SQL and exit; touch nothing")
    args = ap.parse_args()

    live, shadow, old = _names()
    stmts = swap_sql(live, shadow, old) if args.swap else rollback_sql(live, shadow, old)

    if args.dry_run:
        print(f"-- {'SWAP' if args.swap else 'ROLLBACK'} (one transaction): live={live} shadow={shadow} old={old}")
        print("BEGIN;")
        for s in stmts:
            print(f"  {s};")
        print("COMMIT;")
        return 0

    if not pgstore.dsn():
        print("EVIDENCE_PG_DSN not set")
        return 1

    import psycopg
    conn = psycopg.connect(pgstore.dsn(), autocommit=True)
    try:
        if args.swap:
            # GUARD: never flip a missing or empty shadow live — that would serve empty evidence.
            if not _regclass_exists(conn, shadow):
                print(f"REFUSE swap: shadow table {shadow} does not exist (load it first)")
                return 1
            rows = _row_count(conn, shadow)
            if rows == 0:
                print(f"REFUSE swap: shadow table {shadow} has 0 rows (a half-loaded flip is the failure mode)")
                return 1
            print(f"shadow {shadow} has {rows} rows; swapping live")
        else:
            if not _regclass_exists(conn, old):
                print(f"REFUSE rollback: retained table {old} does not exist (nothing to roll back to)")
                return 1
        _run_txn(conn, stmts)
        print(f"{'swapped' if args.swap else 'rolled back'}: live={live} (retained: "
              f"{old if args.swap else shadow})")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
