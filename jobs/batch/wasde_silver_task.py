#!/usr/bin/env python
"""WASDE bronze->silver producer, controlled-publish edition (SILVER-F034 / F035).

Restores a coherent WASDE bronze->silver producer and routes EVERY write through the SILVER-F015
:class:`~leviathan.silver.publisher.ShadowPublisher` with the registered-partition strategy, so:

  * the default ``--publish-mode dry-run`` writes NOTHING (the manifest is a plan);
  * ``shadow`` stages validated objects under a NON-canonical shadow prefix, never promoting;
  * ``canonical`` requires the fail-closed publish-guard verdict + a signed approval (the gated
    B-wave; this task never selects it under a readiness identity);
  * each ``release_date`` partition is registered EXACTLY via
    :class:`~leviathan.silver.partition_publish.PartitionPublisher` -- never re-projected (INV-3),
    never accepted at a wrong location (F013).

The transform itself (:mod:`leviathan.transforms.bronze_to_silver.usda_wasde_silver`) is pure; this
module is the thin I/O + orchestration seam. The pure helpers ``stage_silver_objects`` /
``build_release_objects`` carry the testable logic; ``main`` wires argparse + the guard.

Read-only AWS is fine here; NO canonical mutation happens without a verified approval (the guard
raises first). ASCII only.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Optional, Sequence

from leviathan.common.logging import get_logger
from leviathan.silver.publisher import (
    PublishStrategy,
    ShadowPublisher,
    StagedObject,
    ValidationHooks,
)
from leviathan.silver.registry import load_registry
from leviathan.transforms.bronze_to_silver import usda_wasde_silver as W

logger = get_logger(__name__)

TABLE = "silver_wasde"


def build_release_objects(
    bronze_by_release: dict[str, Sequence[dict]],
    contract: dict,
    *,
    prior_series_state: Optional[dict] = None,
) -> tuple[list[StagedObject], list[W.SilverBuildResult]]:
    """Build one :class:`StagedObject` per release_date partition from bronze rows.

    Releases are processed in chronological order so the revision series thread correctly and an
    older release replayed on its own recomputes only its own series. Each object's canonical key is
    the registered-partition object under ``s3_root/release_date=<d>/part-000.parquet`` and it carries
    the INV-2 arrow bytes + the row/null metrics the publisher's validation hooks consume.
    """
    import io

    import pyarrow.parquet as pq

    root = contract["s3_root"].rstrip("/")
    bucket = contract["s3_bucket"]
    prefix = root.split(f"s3://{bucket}/", 1)[-1]
    state = dict(prior_series_state or {})
    objects: list[StagedObject] = []
    results: list[W.SilverBuildResult] = []

    for release_date in sorted(bronze_by_release):
        res = W.build_silver_frame(bronze_by_release[release_date], prior_series_state=state)
        state = res.series_state
        results.append(res)
        if not res.rows:
            continue
        table = W.to_arrow_table(res.rows, contract)
        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")
        body = buf.getvalue()
        canonical_key = f"{prefix}/{W.PARTITION_KEY}={release_date}/part-000.parquet"
        objects.append(StagedObject(
            canonical_key=canonical_key,
            body=body,
            partition_values=[release_date],
            row_count=table.num_rows,
            null_metrics=_null_metrics(table, contract),
        ))
    return objects, results


def _null_metrics(table, contract: dict) -> dict:
    """Per-value-column non-null fraction, for the publisher's V001-style value hook."""
    metrics: dict[str, float] = {}
    n = table.num_rows or 1
    for col in contract.get("value_columns", []):
        if col in table.column_names:
            metrics[col] = (n - table.column(col).null_count) / n
    return metrics


def stage_silver_objects(
    bronze_by_release: dict[str, Sequence[dict]],
    contract: dict,
    auth,
    s3_client: Any,
    glue_client: Any,
    *,
    shadow_prefix: Optional[str] = None,
    min_nonnull_frac: Optional[float] = None,
    manifest_store=None,
    run_id: Optional[str] = None,
):
    """Construct a REGISTERED-strategy :class:`ShadowPublisher` for the WASDE silver objects and run
    it under ``auth``. Returns ``(manifest, results)``. Nothing canonical is touched unless
    ``auth.may_mutate_canonical`` (the guard's canonical verdict)."""
    objects, results = build_release_objects(bronze_by_release, contract)
    floor = min_nonnull_frac if min_nonnull_frac is not None else contract.get("min_nonnull_frac", 0.0)
    publisher = ShadowPublisher(
        job="wasde_silver_task",
        table=TABLE,
        database=contract["glue_database"],
        bucket=contract["s3_bucket"],
        canonical_root=contract["s3_root"],
        auth=auth,
        s3_client=s3_client,
        glue_client=glue_client,
        strategy=PublishStrategy.REGISTERED,
        shadow_prefix=shadow_prefix,
        validation=ValidationHooks(min_rows=1, min_nonnull_frac=floor or 0.0),
        manifest_store=manifest_store,
        registry_schema_version=contract.get("schema_version"),
        run_id=run_id,
    )
    manifest = publisher.run(objects)
    return manifest, results


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="WASDE bronze->silver controlled publish (F034/F035)")
    p.add_argument("--environment", default="leviathan_dev")
    p.add_argument("--bucket", default=None)
    p.add_argument("--database", default="leviathan_dev")
    p.add_argument("--run-id", default=None)
    p.add_argument("--from", dest="from_date", default=None)
    p.add_argument("--to", dest="to_date", default=None)
    p.add_argument("--shadow-prefix", default=None)
    p.add_argument("--publish-mode", default="dry-run",
                   choices=["dry-run", "shadow", "canonical"],
                   help="default dry-run; canonical needs a signed approval (gated B-wave)")
    p.add_argument("--contract-version", default=None)
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    reg = load_registry()
    contract = reg.table(TABLE)
    logger.info(
        "wasde_silver_task: table=%s mode=%s (canonical is denied without a signed approval; "
        "this task stages+validates, it does not mutate the catalog in R2/R3)",
        TABLE, args.publish_mode,
    )
    # Live bronze read + real publish are the gated B-wave; R2/R3 ships the code + tests only.
    print("wasde_silver_task is a controlled-publish entrypoint; run under the gated backfill wave "
          "with a signed approval. No bronze read or canonical write is performed here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
