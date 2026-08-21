"""Run an evidence_batch verb with a raised per-window output ceiling — process-local, tree untouched.

WHY (2026-08-21, the (A)-batch WASDE rechunk leg): the 139 stale-chunk WASDE docs are the dense-table
class the X2 pass measured truncating at the 4,096 ceiling (34.2% overall; the 2,062-window lost tail
was 86% usda_wasde). The 32k demand probe (msgbatch_01KQuD2dsJ9C6W23m3wA3RaF) measured TRUE output
demand for that class: median ~10k tokens, max 28,425 — so a fill submitted at the stock 4,096 would
knowingly re-mint a lost tail on exactly the docs D14 repaired. Output is billed AS GENERATED, not by
ceiling, so the raise costs nothing on windows that finish early.

evidence_batch._MAX_OUTPUT_TOKENS is a bare module constant with no env override — DELIBERATELY (its
:41 comment + the test_chunking mirror law keep the standing 13k-request cost shape pinned). This
wrapper rebinds it for ONE process only; the file on disk stays 4,096 and both mirror tests stay green.

Used for BOTH legs of the fill (the ceiling must match in each process):
    python jobs/utils/evidence_fill_ceiling.py --max-output-tokens 32768 -- --fill --sources usda_wasde --dry-run
    python jobs/utils/evidence_fill_ceiling.py --max-output-tokens 32768 -- --fill --sources usda_wasde
    python jobs/utils/evidence_fill_ceiling.py --max-output-tokens 32768 -- --retrieve <bid>
(--retrieve needs it too: the inline lost-window retry builds NEW requests reading the global at call
time, and those halves deserve the same headroom.)
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="evidence_batch with a raised output ceiling (process-local)")
    ap.add_argument("--max-output-tokens", type=int, required=True)
    ap.add_argument("rest", nargs=argparse.REMAINDER,
                    help="args for evidence_batch.main(), after a literal --")
    args = ap.parse_args()
    rest = args.rest[1:] if args.rest[:1] == ["--"] else args.rest
    if not rest:
        raise SystemExit("nothing to run: pass evidence_batch args after --")

    from leviathan.graphrag import evidence_batch as eb
    eb._MAX_OUTPUT_TOKENS = args.max_output_tokens
    print(f"[ceiling wrapper] evidence_batch._MAX_OUTPUT_TOKENS = {args.max_output_tokens} "
          f"(process-local; tree stays 4096)", flush=True)
    sys.argv = ["evidence_batch"] + rest
    return eb.main()


if __name__ == "__main__":
    sys.exit(main())
