"""``jobs/ingest/discover_unica_wayback.py`` must COMPILE -- the one pin that was missing.

The file entered the repo already broken (19b0285f, 2026-06-01): a lost newline merged its
``# -- Save results --`` comment box, ``RESULTS_PATH.parent.mkdir(...)`` and
``RESULTS_PATH.write_text(`` onto a single line, leaving an unmatched ``)`` at line 306. Nothing
imports the module -- ``backfill_unica_wayback.py`` and ``fetch_jse_safex_daily.py`` only cite it in
prose -- so no import-time test, no CI job and no lint saw it for 85 days; the manifest-discovery
run would have died at argv parse.

This pin is deliberately the cheapest thing that could have caught it. The estate-wide guard for
the CLASS is the SILVER-F091 source-universe lint, which AST-parses every file under the producer
roots and REPORTS a ``SyntaxError`` as a parse failure rather than skipping the file
(``tests/unit/silver/test_f091_source_universe_lint.py::TestSyntaxErrorIsReported`` pins that a
broken source is reported, and ``::test_every_producer_source_parses`` pins that the tree is clean).
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "jobs" / "ingest" / "discover_unica_wayback.py"


def test_discover_unica_wayback_parses():
    # utf-8-sig: the file carries a BOM, and plain utf-8 leaves it in the first token.
    ast.parse(_SCRIPT.read_text(encoding="utf-8-sig"), filename=str(_SCRIPT))


def test_the_repaired_save_block_is_three_statements():
    """The repair restored the LOST NEWLINES, nothing else: the comment box, the mkdir and the
    write_text each own their line again."""
    lines = _SCRIPT.read_text(encoding="utf-8-sig").splitlines()
    box = next(i for i, line in enumerate(lines) if "Save results" in line)
    assert lines[box].lstrip().startswith("#")
    assert lines[box + 1].strip() == "RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)"
    assert lines[box + 2].strip() == "RESULTS_PATH.write_text("
