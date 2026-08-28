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
but does NOT rename the indexes themselves. ⚠ The original header called that "cosmetic only" and claimed
"the next rebuild's CREATE INDEX IF NOT EXISTS re-derives fresh names" — FALSE, and it cost real money
(INCIDENT 2026-08-27): IF NOT EXISTS is NAME-GLOBAL, so on the second blue-green cycle the fresh shadow's
derived name already existed attached to the LIVE table (a cycle-one rename survivor), init_schema silently
no-oped, and this tool swapped an INDEX-LESS shadow live — every per-node read became a full 16 GB seq
scan, the eval pool wedged at every size (~$12 of dead arm runs), prod degraded ~4h until CREATE INDEX
CONCURRENTLY repaired it. pgstore.init_schema now ensures indexes TABLE-SCOPED, and THIS tool now refuses
on index-parity mismatch (below) — belt and braces, because a slow flip is a silent flip.

GUARD: --swap REFUSES unless the shadow table exists AND has >0 rows AND carries every index SHAPE the live
table carries (definitions normalized — names and table dropped — so the leftover shadow-derived names never
confuse the comparison). A half-loaded, missing, or slower-than-live shadow flip is the exact failure mode
this tool exists to prevent. The guard runs OUTSIDE the swap transaction (a plain read), so a refusal
touches nothing.
"""
from __future__ import annotations

import argparse
import re
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


def normalize_indexdef(d: str) -> str:
    """An indexdef reduced to its SHAPE — '[UNIQUE ]USING <method> (<cols>)...' with the index name and
    table dropped — so rename-survivor names (incident 2026-08-27) can never confuse a comparison."""
    m = re.match(r"CREATE (UNIQUE )?INDEX \S+ ON \S+ (.+)$", d or "")
    return ((m.group(1) or "") + m.group(2)) if m else (d or "")


def index_parity_missing(live_defs: list, shadow_defs: list) -> list:
    """The live table's index shapes ABSENT from the shadow — [] is the only swappable answer. Pure
    (the guard's testable core): a shadow allowed extra indexes, never fewer.

    D-HN (2026-08-28): hnsw shapes are EXCLUDED from parity on BOTH sides. A partial hnsw index's
    normalized shape embeds its node predicate, so requiring the shadow to reproduce live's exact
    certified slice set would block every future blue-green cycle whose certification legitimately
    differs (review wf_f7314d29). ANN indexes are governed by the certified manifest, not by the
    canonical index contract — the router's manifest∩pg_indexes join fails closed on any mismatch."""
    shadow_n = {normalize_indexdef(d) for d in shadow_defs if "USING hnsw" not in (d or "")}
    live_n = {normalize_indexdef(d) for d in live_defs if "USING hnsw" not in (d or "")}
    return sorted(live_n - shadow_n)


def _index_defs(conn, table: str) -> list:
    return [r[0] for r in conn.execute(
        "SELECT indexdef FROM pg_indexes WHERE tablename = %s", (table,)).fetchall()]


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
            # INDEX PARITY (incident 2026-08-27): an index-less shadow flips live SLOWER than the table it
            # replaces — every per-node read a full seq scan, prod degraded, the eval pool wedged. Refuse.
            if _regclass_exists(conn, live):
                missing = index_parity_missing(_index_defs(conn, live), _index_defs(conn, shadow))
                if missing:
                    print(f"REFUSE swap: shadow table {shadow} is missing index shape(s) the live table carries:")
                    for m in missing:
                        print(f"  - {m}")
                    print("(build them on the shadow — pgstore.init_schema with EVIDENCE_PG_TABLE set, or "
                          "CREATE INDEX CONCURRENTLY — then re-run; incident 2026-08-27)")
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
