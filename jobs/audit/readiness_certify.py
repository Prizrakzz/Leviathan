"""SILVER-F080 + SILVER-F083 runner -- the per-table readiness certification harness and
the global R4 Backfill-Ready certificate.

Assembles, for every one of the 43 registry tables, the FOUR-track :class:`TableEvidence`
from local artifacts ONLY (the F010 registry + the R1/R2/R3 report JSONs), evaluates it with
the pure :mod:`leviathan.silver.readiness` core, and emits::

    reports/silver_readiness/R4_certificate/
        R4_certificate.json          # the global SILVER-F083 certificate
        tables/<table>.json          # one SILVER-F080 per-table certificate each
        README.md                    # the honest human summary (reds == B-wave work orders)

READ-ONLY + DETERMINISTIC + AWS-FREE
------------------------------------
* No boto3, no Athena, no S3. Every track input is a checked-in artifact:
    - PRODUCER    : registry ``producer`` block + R2/R3 shadow-cert evidence.
    - CATALOG     : the R1 reconciliation lints (pure) + the F011 DDL diff report.
    - CURRENT_DATA: the V001 value_census_summary + V002 producer_coverage_gaps.
    - FRESHNESS   : an optional freshness_probe.json + a curated known-staleness map
                    (traceable to the R2 artifacts; freshness is otherwise DEFERRED to
                    the B-waves per plan design).
* The certificate is HONEST: it goes GREEN only when zero tables are BLOCKED -- which is
  NOT true today (36 tables have no census yet -> SILVER-V001; CHIRPS all-NaN -> BF-W1; ESR
  single-vintage -> BF-W2; six orphan producers -> R3 + BF-W3; conab hidden schema -> F024).

Usage:
    python jobs/audit/readiness_certify.py
    python jobs/audit/readiness_certify.py --evidence-dir reports/silver_readiness/R4_certificate
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from leviathan.silver import reconcile as rc  # noqa: E402
from leviathan.silver.readiness import (  # noqa: E402
    TableEvidence,
    _parse_pkg,
    certify_all,
    certify_table,
)
from leviathan.silver.registry import load_registry  # noqa: E402

REPORTS = _REPO_ROOT / "reports" / "silver_readiness"
F011_DDL_DIFF = REPORTS / "R1_F011_ddl_diff.json"
V001_SUMMARY = REPORTS / "R1_V001_value_census" / "value_census_summary.json"
V002_GAPS = REPORTS / "R1_V002_cert_contracts" / "producer_coverage_gaps.json"
SHADOW_CERT_R3 = REPORTS / "R3_OA_orphan_producers" / "evidence.json"
SHADOW_CERT_DIR = REPORTS / "R2R3_producers" / "shadow_cert"
DEFAULT_OUT = REPORTS / "R4_certificate"

ML_TABLE = "silver_model_predictions"

# Curated known-staleness map -> the B-wave that catches the table up. EMPTIED 2026-07-15 at the
# BF-W3 close: every entry's owning wave has CLOSED with a wave certificate -- BF-W1
# rebuilt/compacted/deprojected the weather trio (chirps/nasa_power/cpc_soil) to their raw tips
# (B1 close, 2026-07-14), and BF-W2 published the ESR per-week vintages (20 partitions, weekly
# EventBridge schedule ENABLED) + the WASDE catch-up (B2_wave/WAVE_CERTIFICATE.md). Freshness
# going forward is owned by the F082 alarm definitions + the ingest schedules, not this map.
# Re-add an entry ONLY with a fresh staleness census artifact naming the owning wave.
KNOWN_STALENESS: dict = {}

# Tables REGISTERED AHEAD OF THEIR PRODUCERS -> the wave that publishes them. The F010 contract for a
# new table lands first on purpose (schema ratified, generated, DDL'd and linted before a single byte
# is written), so between registration and the first canonical publish the table has zero objects and
# a value census is not merely missing but IMPOSSIBLE. Mapping it here makes the certificate name the
# work order that actually closes the row, instead of SILVER-V001 ("census the data that exists"), and
# it keeps the dishonest alternative -- fabricating a {"passed": true} census entry for a table with no
# objects -- off the table. The row stays BLOCKED and the certificate stays RED either way.
# REMOVE an entry the moment its table's first canonical publish + census land.
PRE_PUBLISH_PACKAGE: dict = {
    # PRICE_AND_PLAYBOOKS W1.0: silver_futures_eod is registered + serving-fenced; W1a (the free-first
    # venues) is the first wave that writes a canonical partition, and W2 completes the coverage.
    "silver_futures_eod": "PRICE-PLAYBOOKS-W1A",
    # BLACK SEA numbers cluster, 2026-08-20. silver_moex_agro_indices is registered ahead of its
    # producer: the raw fetcher and both transforms exist, no batch task does, and no jobdef or
    # schedule is armed -- so there are no objects and a value census is IMPOSSIBLE rather than
    # merely missing. The row stays BLOCKED and the certificate stays RED; this entry only makes it
    # name the work that closes the row. That work is the cloud-side backfill, which cannot run
    # until the worker image is rebuilt to carry jobs/ingest/fetch_moex_agro_indices.py --
    # iss.moex.com is reachable from AWS and not from a laptop. Mirrors
    # silver_alarms.PRE_PUBLISH_FAMILIES; REMOVE both the moment the first canonical publish +
    # census land.
    "silver_moex_agro_indices": "BLACK-SEA-MOEX-BACKFILL",
    # BLACK SEA freight backbone, same date, same shape and the OTHER HALF of a mirror this file is
    # named in: silver_alarms.PRE_PUBLISH_FAMILIES now carries `ams_gtr`, and its removal-trigger
    # comment points here. The GTR source is the most backfillable one in the cluster (seven SODA
    # datasets, measured spans back to 1996-01-01) -- the block is not the source, it is that no
    # bronze->silver batch task or jobdef exists yet, so there are zero objects and the census is
    # IMPOSSIBLE rather than missing. Naming the work order keeps the row from reading as
    # SILVER-V001 ("census the data that exists") when there is nothing to census. The row stays
    # BLOCKED and the certificate stays RED. REMOVE both halves the moment the first canonical
    # publish + census land.
    "silver_ams_gtr": "BLACK-SEA-GTR-FIRST-PUBLISH",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- a malformed evidence file must not crash the harness
        return None


# ---------------------------------------------------------------------------
# Artifact -> per-table lookups.
# ---------------------------------------------------------------------------
def _reconcile_by_table(reg) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for d in rc.unallowed(rc.reconcile_all(reg)):
        out.setdefault(d.table, []).append(
            {"check": d.check, "kind": d.kind, "detail": d.detail}
        )
    return out


def _ddl_diff_by_table() -> dict[str, list[dict]]:
    doc = _load_json(F011_DDL_DIFF) or {}
    out: dict[str, list[dict]] = {}
    for row in doc.get("rows", []):
        out.setdefault(row.get("table"), []).append(row)
    return out


def _census_by_table() -> dict[str, dict]:
    doc = _load_json(V001_SUMMARY) or {}
    return doc.get("tables", {}) or {}


def _producer_gap_pkg_by_table() -> dict[str, str]:
    doc = _load_json(V002_GAPS) or {}
    return {g.get("glue_table"): g.get("r3_package") for g in doc.get("gaps", [])}


def _shadow_cert_ok_by_table() -> dict[str, bool]:
    ok: dict[str, bool] = {}
    r3 = _load_json(SHADOW_CERT_R3) or {}
    for t, rec in (r3.get("tables") or {}).items():
        ok[t] = bool(rec.get("bit_for_bit_all_14_cols", True)) if isinstance(rec, dict) else True
    if SHADOW_CERT_DIR.exists():
        for p in SHADOW_CERT_DIR.glob("silver_*.json"):
            ok.setdefault(p.stem, True)
    return ok


def _freshness_probe_by_table(evidence_dir: Path) -> dict[str, dict]:
    doc = _load_json(evidence_dir / "freshness_probe.json") or {}
    return doc.get("tables", {}) or {}


# ---------------------------------------------------------------------------
# Evidence assembly.
# ---------------------------------------------------------------------------
def build_evidence(reg, *, evidence_dir: Path) -> list[TableEvidence]:
    reconciles = _reconcile_by_table(reg)
    ddl = _ddl_diff_by_table()
    census = _census_by_table()
    gap_pkg = _producer_gap_pkg_by_table()
    shadow = _shadow_cert_ok_by_table()
    probes = _freshness_probe_by_table(evidence_dir)

    out: list[TableEvidence] = []
    for name in reg.names():
        c = reg.table(name)
        prod = c.get("producer") or {}
        cen = census.get(name)
        max_lag = ((c.get("freshness_sla") or {}).get("max_lag_days"))
        # The R3 package that closes an orphan: the V002 gap map first, else the package the
        # registry producer.note records (e.g. unica -> SILVER-F062, not in the V002 list).
        producer_pkg = gap_pkg.get(name) or _parse_pkg(prod.get("note"))

        out.append(TableEvidence(
            table=name,
            is_ml=(name == ML_TABLE or c.get("lifecycle_class") == "generated"),
            # producer
            producer_status=prod.get("status", "producer"),
            transform=prod.get("transform"),
            batch_task=prod.get("batch_task"),
            shadow_cert_ok=shadow.get(name),
            producer_package=producer_pkg,
            # catalog
            reconcile_divergences=tuple(reconciles.get(name, [])),
            catalog_drift_rows=tuple(ddl.get(name, [])),
            placeholder_partition_count=int(
                (c.get("fingerprint") or {}).get("placeholder_partition_count", 0) or 0),
            catalog_migration_package=None,
            # current-data
            census_present=cen is not None,
            census_passed=(cen.get("passed") if cen else None),
            census_gate_kinds=tuple(cen.get("kinds", [])) if cen else (),
            current_data_package=PRE_PUBLISH_PACKAGE.get(name),
            # freshness
            freshness_probe=probes.get(name),
            max_lag_days=max_lag,
            staleness_package=KNOWN_STALENESS.get(name),
        ))
    return out


# ---------------------------------------------------------------------------
# README.
# ---------------------------------------------------------------------------
def _render_readme(cert: dict) -> str:
    lines: list[str] = []
    lines.append("# R4 Backfill-Ready certificate (SILVER-F080 + SILVER-F083)")
    lines.append("")
    lines.append(f"- verdict: **{cert['verdict']}**  (signed: {cert['signed']})")
    lines.append(f"- tables: {cert['table_count']}")
    lines.append(f"- state counts: {cert['state_counts']}")
    lines.append("")
    lines.append("The certificate distinguishes five correctness dimensions and stays RED "
                 "until every BLOCKED row's work order closes. Its reds ARE the B-wave backlog.")
    lines.append("")
    lines.append("## Per-track dimension tallies")
    for tr, counts in cert["correctness_dimensions"].items():
        lines.append(f"- {tr}: {counts}")
    lines.append("")
    lines.append("## Work orders (package -> tables it unblocks)")
    for pkg, tables in cert["work_orders"].items():
        lines.append(f"- **{pkg}** ({len(tables)}): {', '.join(tables)}")
    lines.append("")
    lines.append("## Tables by readiness state")
    for state, tables in cert["tables_by_state"].items():
        lines.append(f"### {state} ({len(tables)})")
        for t in tables:
            tc = cert["tables"][t]
            reds = [f"{k}={v['verdict']}" for k, v in tc["tracks"].items()
                    if v["verdict"] not in ("PASS", "NA")]
            suffix = f"  [{'; '.join(reds)}]" if reds else ""
            lines.append(f"- {t} -> {tc['label']}{suffix}")
        lines.append("")
    lines.append("_" + cert["honesty_note"] + "_")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Run.
# ---------------------------------------------------------------------------
def run(evidence_dir: Path) -> int:
    reg = load_registry()
    evidence = build_evidence(reg, evidence_dir=evidence_dir)
    cert = certify_all(evidence)
    cert["generated_at"] = _now()
    cert["baseline_id"] = "20260712_p65impl"

    tables_dir = evidence_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    for ev in evidence:
        tc = certify_table(ev).to_dict()
        (tables_dir / f"{ev.table}.json").write_text(
            json.dumps(tc, indent=2, sort_keys=True), encoding="utf-8")

    (evidence_dir / "R4_certificate.json").write_text(
        json.dumps(cert, indent=2, sort_keys=True), encoding="utf-8")
    (evidence_dir / "README.md").write_text(_render_readme(cert), encoding="utf-8")

    print(f"[R4] readiness certificate -> {evidence_dir}")
    print(f"[R4] verdict={cert['verdict']} signed={cert['signed']} tables={cert['table_count']}")
    print(f"[R4] state_counts={cert['state_counts']}")
    print(f"[R4] blocked={len(cert['blocked_tables'])}")
    for pkg, tables in cert["work_orders"].items():
        print(f"[R4]   work order {pkg}: {len(tables)} table(s)")
    return 0 if cert["verdict"] == "GREEN" else 2


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="SILVER-F080/F083 R4 readiness certification")
    ap.add_argument("--evidence-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)
    return run(Path(args.evidence_dir))


if __name__ == "__main__":
    # Exit 2 == honest RED (expected today); 0 == GREEN. Non-zero is not a crash.
    raise SystemExit(main())
