"""Local bronze backfill for USDA FAS ESR -- REFUSED since 2026-09-04 (THE VINTAGE LAW).

THE VINTAGE LAW (lane C verify-2 V2-NEW-1, 2026-09-04)
------------------------------------------------------
A bronze partition's ``as_of`` comes from the RAW KEY, or from the raw object's
``raw_meta`` sidecar -- NEVER from today's date.  This script broke that law in
its ONLY mode.  It read the UNDATED backfill keys
(``raw_esr_backfill_key(code, year)``, which carry no ``as_of=`` segment) and
wrote ``bronze_esr_key(code, year, <--ingest-date>)`` -- and ``--ingest-date``
DEFAULTED TO TODAY, so ``python jobs/ingest/backfill_bronze_usda_esr.py`` with no
arguments at all minted a whole point-in-time vintage that never existed, 44
codes x 1990..<this year>, into the same bronze prefix ``jobs/batch/esr_task.py``
writes.  MEASURED 2026-09-04: 8,474 of the 8,920 ESR bronze objects (95.0%) are
fabricated vintages minted exactly that way, 1,414 of them at as_of=20260904
alone.

It is the LOCAL TWIN of ``jobs/glue/raw_to_bronze_usda_esr.py``'s backfill mode,
refused the same day for the same mechanism -- and it is the path an operator
reaches for FIRST, because this file's own first line used to advertise it as the
way around Glue quota limits.  Like that twin it cannot date an undated key
honestly: it reads the raw OBJECT only, never the raw_meta sidecar.  A writer
that cannot obey a law must refuse under it.

USE INSTEAD -- the law-abiding writer, and it does this job:

    python jobs/batch/esr_task.py --include-backfill --backfill-as-of YYYYMMDD

``esr_task.py`` resolves an undated key's as_of in four branches -- the key's own
``as_of=`` segment, an explicit ``--backfill-as-of``, the raw_meta sidecar's
``download_timestamp``, else REFUSE -- and reads no clock in any of them.
``jobs/utils/esr_netcommitment_raw_census.py`` lists which vintages exist.

NO CLOCK DEFAULT SURVIVES IN THIS MODULE.  ``--ingest-date`` no longer defaults to
``datetime.date.today().isoformat()`` and ``--end-year`` no longer defaults to
``datetime.date.today().year``; nothing here reads a clock at all.  The flags are
still ACCEPTED so a pasted historical command line meets the law's message
instead of an argparse error, and every invocation shape refuses.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[2]

# Ensure the src package is importable when run from the project root.
sys.path.insert(0, str(_REPO_ROOT / "src"))
# ...and the repo root itself, so `jobs.ingest.fetch_usda_esr` resolves when this
# file is executed as a script (sys.path[0] is then jobs/ingest, not the root).
sys.path.insert(0, str(_REPO_ROOT))

from leviathan.common.logging import get_logger

from jobs.ingest.fetch_usda_esr import _TARGET_COMMODITY_CODES

logger = get_logger(__name__)

# D-EC 2026-08-20: IMPORTED, never re-typed.  This script used to hold its own
# copy of the legacy 10-code list, so the fetcher's widening to the measured
# 44-code universe would have left the backfill silently re-narrowing every run.
# The fetcher is the single authority on the universe.  It stays after the
# refusal because --help must keep telling the truth about the flag's shape, and
# because a unit test pins this list EQUAL to the fetcher's.
_DEFAULT_COMMODITY_CODES = list(_TARGET_COMMODITY_CODES)

# THE VINTAGE LAW's refusal, named so a console line says WHICH law stopped the run and WHICH
# writer to use instead.  Deliberately a STRING and not a collection: this file sits inside the
# F091 lint's SCAN_ROOTS and a module-level collection would move the raw-literal census
# (PIN_RAW_LITERALS) in a shared tree.
_BACKFILL_REFUSAL = (
    "REFUSING (ESR VINTAGE LAW): this local writer cannot re-bronze the UNDATED backfill keys. "
    "It reads the raw object only -- never the raw_meta sidecar -- so it used to pair every "
    "undated key with --ingest-date, which DEFAULTED TO TODAY: an unflagged run minted a "
    "point-in-time vintage that never existed. MEASURED 2026-09-04: 8,474 of 8,920 ESR bronze "
    "objects (95.0%) were minted that way, 1,414 of them at as_of=20260904 alone. Use the "
    "law-abiding writer instead: jobs/batch/esr_task.py --include-backfill --backfill-as-of "
    "YYYYMMDD, which resolves as_of from the key's own as_of= segment, an explicit operator "
    "date, or the raw_meta sidecar's download_timestamp, and REFUSES a key it cannot date. "
    "This module's Glue twin, jobs/glue/raw_to_bronze_usda_esr.py, refuses the same re-bronze "
    "for the same reason."
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    # ASCII only: the Windows console is cp1252 and a U+2192 here crashed --help.
    p = argparse.ArgumentParser(
        description="Local ESR raw -> bronze backfill -- REFUSED (ESR VINTAGE LAW)")
    p.add_argument("--commodity-codes", nargs="+", type=int, default=_DEFAULT_COMMODITY_CODES)
    p.add_argument("--start-year", type=int, default=1990)
    # NO CLOCK DEFAULT ANYWHERE.  --end-year defaulted to datetime.date.today().year and
    # --ingest-date to datetime.date.today().isoformat(); the second of those became the bronze
    # as_of.  Both are None now.  The flags are still parsed so a historical command line refuses
    # with the LAW's message rather than an argparse "unrecognized arguments" error.
    p.add_argument("--end-year", type=int, default=None)
    p.add_argument("--ingest-date", default=None,
                   help="ACCEPTED AND IGNORED. It is the INGEST date and was never a vintage; "
                        "the run refuses before it is read. See THE VINTAGE LAW.")
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def refuse_undated_backfill() -> None:
    """THE VINTAGE LAW at this writer's ONLY seam.  ALWAYS raises ``RuntimeError``.

    Unconditional, not a validation branch: there is no argument shape that makes this module
    lawful, because every raw key it can read is UNDATED and it has no route to a raw_meta
    sidecar.  ``--dry-run`` refuses too -- a dry run of an unlawful writer teaches the wrong
    recipe.  Raised before ``load_env()``, before boto3 and before any S3 call, so the refusal
    costs no LIST and no GET.
    """
    raise RuntimeError(_BACKFILL_REFUSAL)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parse_args()
    try:
        refuse_undated_backfill()
    except RuntimeError as exc:
        # The same refusal SHAPE the sibling local writer uses (jobs/ingest/
        # backfill_silver_usda_esr.py logs the refusal and exits 2), so an operator who has met
        # one has met both, and a wrapper script sees a non-zero STATUS rather than a traceback.
        # No "REFUSING:" prefix is added here: the message opens with its own, exactly as the
        # Glue twin's _BACKFILL_REFUSAL does, and doubling it reads like two findings.
        logger.error("%s", exc)
        sys.exit(2)


if __name__ == "__main__":
    main()
