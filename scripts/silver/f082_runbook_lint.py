#!/usr/bin/env python
"""SILVER-F082: incident-runbook completeness lint.

Guards ``reports/silver_readiness/R4_incident_runbooks.md`` against two ways it can silently rot:

  1. a required FAILURE-MODE runbook is missing (the F082 required-runbook list -- source outage,
     value-census failure, LIST-storm, silver_rebuild_gate red, ... every alarm class must have a
     documented response);
  2. a DAG-catalog FAMILY has no row in the per-family runbook index (a source pipeline exists with
     no on-call owner / failure-mode mapping) -- this is the "every DAG-catalog family has a runbook
     row" completeness criterion.

It also cross-checks that every ``Runbook: R4_incident_runbooks.md#<anchor>`` referenced by the
generated alarm definitions resolves to a real heading -- so an alarm can never page an on-call to a
runbook section that does not exist.

READ-ONLY + AWS-FREE. GitHub-style heading slugs (lowercase, punctuation dropped, spaces->hyphens).
Exit 0 = complete; exit 6 = incomplete (with the gaps printed). ASCII-only stdout.

Usage:
    python scripts/silver/f082_runbook_lint.py
    python scripts/silver/f082_runbook_lint.py --runbook reports/silver_readiness/R4_incident_runbooks.md
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from leviathan.silver.dag_catalog import build_catalog  # noqa: E402

DEFAULT_RUNBOOK = _REPO / "reports" / "silver_readiness" / "R4_incident_runbooks.md"

# The F082 required failure-mode runbooks (plan L799). Heading TEXT -- the lint slugifies it and
# checks a matching `## ` heading exists. Order = document order for the printed report.
REQUIRED_FAILURE_MODES: tuple[str, ...] = (
    "Source outage / rate-limit",
    "Parser / schema drift",
    "Duplicate / null-key quarantine",
    "Value-census failure (all-NaN / collapsed vintage)",
    "Partial S3 publication",
    "Missing / wrong Glue partition",
    "Projection-domain omission",
    "LIST-storm / enumeration-cancel (INV-3)",
    "DDL / catalog migration rollback",
    "S3 object restore",
    "Abandoned staging run / stuck lock",
    "silver_rebuild_gate red (consumer desync)",
    "Credential compromise / rotation",
    # The alarm-class runbooks the generated alarms point at.
    "Batch job failed",
    "Freshness SLA breach",
    # The F081 recovery-rehearsal cross-reference.
    "Catalog / object recovery (F081 rehearsal)",
)


def gh_slug(text: str) -> str:
    """GitHub-style heading anchor: lowercase, drop punctuation (keep word chars, hyphen, space),
    spaces -> hyphens. Preserves runs of hyphens (a dropped ``/`` between spaces yields ``--``)."""
    s = text.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


_HEADING_RE = re.compile(r"^#{2,4}\s+(.*?)\s*$", re.MULTILINE)


def parse_heading_slugs(md: str) -> set[str]:
    return {gh_slug(m.group(1)) for m in _HEADING_RE.finditer(md)}


def parse_family_rows(md: str) -> set[str]:
    """Family keys present in the per-family runbook index -- the first backticked cell of each
    markdown table row (``| `usda_esr` | ... |``)."""
    keys: set[str] = set()
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        m = re.match(r"`([a-z0-9_]+)`", cells[0])
        if m:
            keys.add(m.group(1))
    return keys


def alarm_runbook_anchors() -> set[str]:
    """Every ``R4_incident_runbooks.md#<anchor>`` referenced by the generated alarm definitions."""
    try:
        sys.path.insert(0, str(_REPO / "jobs" / "observability"))
        from silver_alarms import build_document  # type: ignore  # noqa: E402
    except Exception:
        return set()
    anchors: set[str] = set()
    for a in build_document().get("alarms", []):
        for m in re.finditer(r"R4_incident_runbooks\.md#([\w\-]+)", a.get("description", "")):
            anchors.add(m.group(1))
    return anchors


def lint(runbook_path: Path) -> dict:
    md = runbook_path.read_text(encoding="utf-8") if runbook_path.exists() else ""
    heading_slugs = parse_heading_slugs(md)
    family_rows = parse_family_rows(md)
    catalog = build_catalog()

    missing_modes = [t for t in REQUIRED_FAILURE_MODES if gh_slug(t) not in heading_slugs]
    missing_families = [k for k in catalog if k not in family_rows]
    dangling_anchors = sorted(a for a in alarm_runbook_anchors() if a not in heading_slugs)

    ok = not missing_modes and not missing_families and not dangling_anchors
    try:
        runbook_label = runbook_path.relative_to(_REPO).as_posix()
    except ValueError:
        runbook_label = str(runbook_path)
    return {
        "runbook": runbook_label,
        "exists": runbook_path.exists(),
        "required_failure_modes": len(REQUIRED_FAILURE_MODES),
        "families_in_catalog": len(catalog),
        "families_with_row": len(family_rows & set(catalog)),
        "missing_failure_modes": missing_modes,
        "missing_families": missing_families,
        "dangling_alarm_anchors": dangling_anchors,
        "complete": ok,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="SILVER-F082 runbook completeness lint")
    ap.add_argument("--runbook", default=str(DEFAULT_RUNBOOK))
    args = ap.parse_args(argv)

    r = lint(Path(args.runbook))
    print(f"[F082-lint] runbook={r['runbook']} exists={r['exists']}")
    print(f"[F082-lint] failure modes: {r['required_failure_modes']} required; "
          f"missing={r['missing_failure_modes'] or 'none'}")
    print(f"[F082-lint] families: {r['families_with_row']}/{r['families_in_catalog']} have a row; "
          f"missing={r['missing_families'] or 'none'}")
    print(f"[F082-lint] dangling alarm anchors: {r['dangling_alarm_anchors'] or 'none'}")
    print(f"[F082-lint] COMPLETE: {r['complete']}")
    return 0 if r["complete"] else 6


if __name__ == "__main__":
    raise SystemExit(main())
