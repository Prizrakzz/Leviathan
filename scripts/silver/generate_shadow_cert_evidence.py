#!/usr/bin/env python
"""LANE OB shadow-cert evidence: run each restored/adopted producer through the DRY-RUN publisher
on a golden fixture and capture the manifest + parquet-footer value census (SILVER-V001).

This is the "isolated shadow certified" evidence bundle for SILVER-F053/F054/F055/F058/F059 + the
F062 MPOB adoption -- produced entirely offline (no canonical S3/Glue write, no Athena). For each
table it records: the INV-2 writer schema, the dry-run manifest state + validation result, and the
footer-derived value census gate (per value_column non-null fraction, all-nan / sentinel checks).

Writes reports/silver_readiness/R2R3_producers/shadow_cert/<table>.json + a summary.md.

READ-ONLY + AWS-FREE.
"""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from leviathan.common.publish_guard import Authorization, PublishMode  # noqa: E402
from leviathan.silver import value_census as vc  # noqa: E402
from leviathan.silver.flat_producer import build_flat_publish, encode_parquet  # noqa: E402
from leviathan.silver.mpoc.adapter import parse_tables  # noqa: E402
from leviathan.silver.registry import load_registry  # noqa: E402
from leviathan.transforms.bronze_to_silver.mpoc_exports_by_country import (  # noqa: E402
    MpocExportsRelease, transform_exports_by_country)
from leviathan.transforms.bronze_to_silver.mpoc_stock_comparison import (  # noqa: E402
    MpocStockRelease, transform_stock_comparison)
from leviathan.transforms.bronze_to_silver.mpoc_trade_stats_monthly import (  # noqa: E402
    MpocMonthlyRelease, transform_trade_stats_monthly)
from leviathan.transforms.bronze_to_silver.sagis_cec import (  # noqa: E402
    CecObservation, transform_sagis_cec)
from leviathan.transforms.bronze_to_silver.sagis_weekly_exports import (  # noqa: E402
    WeeklyExportRow, transform_weekly_exports)

OUT = _REPO / "reports" / "silver_readiness" / "R2R3_producers" / "shadow_cert"

_EXPORTS_HTML = """
<h3>Exports to Major Countries</h3>
<table><tr><th>Country</th><th>2023 (Tonnes)</th></tr>
<tr><td>China</td><td>2,500,000</td></tr><tr><td>India</td><td>1,800,000</td></tr>
<tr><td>Pakistan</td><td>1,100,000</td></tr><tr><td>Total</td><td>5,400,000</td></tr></table>
"""
_MONTHLY_HTML = """
<h3>Monthly Palm Oil Exports and Imports 2023</h3>
<table><tr><th>Month</th><th>Exports (Tonnes)</th><th>Imports (Tonnes)</th></tr>
""" + "".join(f"<tr><td>{m:02d}</td><td>{1_200_000+m}</td><td>{40_000+m}</td></tr>" for m in range(1, 13)) + "</table>"
_STOCK_HTML = """
<h3>Oils and Fats Ending Stocks</h3>
<table><tr><th>Country</th><th>Oil</th><th>Nov 2024</th><th>Dec 2024</th></tr>
<tr><td>China</td><td>Palm</td><td>600</td><td>620</td></tr>
<tr><td>China</td><td>Soybean</td><td>900</td><td>910</td></tr>
<tr><td>India</td><td>Palm</td><td>400</td><td>410</td></tr></table>
"""


def _cec_fixture():
    # 4 production years x 3 numbered estimates -> revision_t + revision_surprise clear the 0.5 floor.
    obs = []
    for yi, year in enumerate([2021, 2022, 2023, 2024]):
        base = 8000 + 1000 * yi
        for i, bump in enumerate([0, 400, 900]):
            obs.append(CecObservation(year, 10 + i, "maize", "commercial", i + 1,
                                      float(base + bump), release_date=f"{year}-{2+i:02d}-01"))
    return transform_sagis_cec(obs)


def _weekly_fixture():
    # 5 seasons at week 5 -> pct_of_prior_yr + z_vs_3yr_avg clear the 0.5 floor.
    rows = [WeeklyExportRow(season=s, crop="maize", week_number=5, prog_exports_mt=float(v),
                            snapshot_id=f"{s}-w52", snapshot_week=52)
            for s, v in [("2020-21", 90), ("2021-22", 100), ("2022-23", 110),
                         ("2023-24", 120), ("2024-25", 150)]]
    return transform_weekly_exports(rows)


def _build_frames():
    return {
        "silver_mpoc_exports_by_country":
            transform_exports_by_country([MpocExportsRelease(2023, parse_tables(_EXPORTS_HTML))]),
        "silver_mpoc_trade_stats_monthly":
            transform_trade_stats_monthly([MpocMonthlyRelease(2023, parse_tables(_MONTHLY_HTML))]),
        "silver_mpoc_stock_comparison":
            transform_stock_comparison(MpocStockRelease("2026-05-01", parse_tables(_STOCK_HTML))),
        "silver_sagis_cec": _cec_fixture(),
        "silver_sagis_weekly_exports": _weekly_fixture(),
    }


def _census(body: bytes, contract: dict) -> dict:
    md = pq.read_metadata(io.BytesIO(body))
    value_cols = contract.get("value_columns", [])
    by_col = {}
    for col in value_cols:
        stat = vc.file_column_stat(md, col)
        by_col[col] = vc.census_column([stat], col)
    # Match the census runner's floor layering (jobs/audit/value_census.py) -- without the
    # override layers this writer judged pct_harvested against the table scalar and would
    # now diverge from the gate in both directions depending on the month (review m-10).
    gate = vc.evaluate_gate(
        "t", by_col, value_cols, contract.get("min_nonnull_frac"),
        floor_overrides=contract.get("min_nonnull_frac_overrides") or None,
        season_floor_overrides=contract.get("min_nonnull_frac_season_overrides") or None,
        as_of_month=datetime.now(timezone.utc).month,
    )
    return {
        "value_columns": list(value_cols),
        "min_nonnull_frac": contract.get("min_nonnull_frac"),
        "columns": {c: cen.to_dict() for c, cen in by_col.items()},
        "gate_rows": [g.to_dict() for g in gate],
        "value_certified": len(gate) == 0,
    }


def main() -> int:
    reg = load_registry()
    frames = _build_frames()
    OUT.mkdir(parents=True, exist_ok=True)
    auth = Authorization(mode=PublishMode.DRY_RUN, may_mutate_canonical=False, readiness=True,
                         reason="readiness dry-run shadow-cert")
    summary = []
    for table, df in frames.items():
        contract = reg.table(table)
        body = encode_parquet(df, contract)
        plan = build_flat_publish(df=df, contract=contract,
                                  canonical_key=f"{contract['s3_prefix']}/part-000.parquet",
                                  auth=auth, s3_client=None, job=f"{table}_shadow_cert",
                                  run_id=f"{table}-shadowcert")
        manifest = plan.run()
        census = _census(body, contract)
        evidence = {
            "table": table,
            "package": (contract.get("drift_summary") or [{}])[0].get("owner_package")
                       or _owner(table),
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "publish_mode": "dry-run",
            "writer_schema_pinned": contract["writer_schema_pinned"],
            "inv2_schema": [(f.name, str(f.type), f.nullable) for f in plan.schema],
            "rows": int(len(df)),
            "manifest_state": manifest.state.value,
            "validation_ok": manifest.validation_result.get("ok", None),
            "value_census": census,
        }
        (OUT / f"{table}.json").write_text(json.dumps(evidence, indent=2, sort_keys=True),
                                           encoding="utf-8")
        summary.append(evidence)
        print(f"{table}: rows={len(df)} state={manifest.state.value} "
              f"value_certified={census['value_certified']}")

    (OUT / "summary.md").write_text(_render_summary(summary), encoding="utf-8")
    return 0


def _owner(table: str) -> str:
    return {
        "silver_mpoc_exports_by_country": "SILVER-F053",
        "silver_mpoc_trade_stats_monthly": "SILVER-F054",
        "silver_mpoc_stock_comparison": "SILVER-F055",
        "silver_sagis_cec": "SILVER-F058",
        "silver_sagis_weekly_exports": "SILVER-F059",
    }.get(table, "SILVER-F062")


def _render_summary(rows: list[dict]) -> str:
    lines = [
        "# LANE OB shadow-cert evidence (dry-run, offline)",
        "",
        "Each restored/adopted producer run through the SILVER-F015 publisher in DRY-RUN on a golden "
        "fixture: nothing canonical is written; the manifest stops at VALIDATED; the value census is "
        "read from the parquet FOOTER (SILVER-V001, never Athena).",
        "",
        "| table | package | rows | manifest | validation | value_certified |",
        "|---|---|--:|---|:--:|:--:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['table']} | {r['package']} | {r['rows']} | {r['manifest_state']} | "
            f"{'ok' if r['validation_ok'] else 'FAIL'} | "
            f"{'yes' if r['value_census']['value_certified'] else 'NO'} |")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
