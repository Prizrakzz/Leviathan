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
``build_release_objects`` carry the transform logic; ``run_from_bronze`` is the bronze-read runner
(bounded release selection, ``prior_series_state`` seeding from bronze HISTORY for the F034
revision linkage, F033 published-axis region-gate refusal); ``main`` wires argparse + STS + the
guard around it (BF-W2 step 2).

Read-only AWS is fine here; NO canonical mutation happens without a verified approval (the guard
raises first). ASCII only.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from leviathan.common.config import load_env
from leviathan.common.logging import get_logger
from leviathan.common.publish_guard import PublishTarget, authorize_publish
from leviathan.silver.publisher import (
    ManifestState,
    PublishStrategy,
    ShadowPublisher,
    StagedObject,
    ValidationHooks,
)
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import parse_hive_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver import usda_wasde_silver as W

logger = get_logger(__name__)

TABLE = "silver_wasde"
_BRONZE_PREFIX = "bronze/production/source=usda_wasde/"
_CANONICAL_PREFIX = "silver/wasde/"
_READ_WORKERS = 16

# F034 QUARANTINE (D-SG G1-2 / owner decision 6.D3). A release whose bronze parse yields a
# divergent-value natural-key conflict is excluded from BOTH the publish window AND the history
# seed -- one ancient release must never block the current month. This is NOT a silent drop:
# every exclusion is logged at WARNING with its reason, the reasons are pinned here as the parse
# fix's own regression target, and an EXPLICIT --release-date naming a quarantined release raises
# WasdeQuarantineError rather than vanishing. A quarantined release never published (it cannot --
# resolve_conflicts raises before staging), so excluding it removes nothing from the canonical
# table; the only consequence is that release_sequence for later releases in the same series does
# not count it, which is exactly consistent with the PUBLISHED set.
# Re-derive the full conflict set for a full-history rebuild with scratch/f2_wasde_earlylist.py
# (read-only; it threads state across buildable releases and skips conflicts).
QUARANTINE_REASONS: dict[str, str] = {
    "1985-06-10": (
        "WasdeKeyConflict on natural key ('1985-06-10', "
        "'world_rice_supply_and_use_ending_stocks', 'rice', 'avg_farm_price_bu', '1984/85', "
        "'beginning_stocks', 'Milled Basis', 'projection', 'May'): divergent estimates 2.5 vs "
        "1.67 -- a Milled-Basis rice column mis-bind in the scanned-era parse. Observed on every "
        "fire 2026-08-08..2026-08-13 (job b01663ec0ded4021a7221a40d6c934f4). Parse fix is a "
        "follow-on; this release has NEVER been registered in Glue, so quarantine publishes "
        "nothing and un-publishes nothing."),
}
QUARANTINED_RELEASES: tuple[str, ...] = tuple(sorted(QUARANTINE_REASONS))


class WasdeBronzeNotReadyError(RuntimeError):
    """F032-style ordering guard: silver is never planned/staged from an empty bronze layer, an
    empty publish selection, or an explicitly requested release that bronze does not carry."""


class WasdeQuarantineError(RuntimeError):
    """An EXPLICITLY requested release_date is on the F034 quarantine list. Refused loudly: a
    quarantined release is skipped only when the caller asked for a WINDOW, never when the caller
    named it -- silently dropping a named release is the drop/keep-last failure mode one level up."""


class WasdeRegionGateError(RuntimeError):
    """The F033 region-cleanliness gate found a polluted PUBLISHED region axis. Staging is refused
    in EVERY publish mode (shadow included) -- parser/fixture work must precede a retry."""


# ---------------------------------------------------------------------------
# Bronze release selection + read (the runner's I/O seam; clients are injectable).
# ---------------------------------------------------------------------------
def select_bronze_keys(
    all_keys: Sequence[str],
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    release_dates: Optional[Sequence[str]] = None,
    seed_from: Optional[str] = None,
    quarantined: Optional[Sequence[str]] = None,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Split bronze keys into ``(publish, history)`` groups keyed by ``release_date``.

    publish = the bounded catch-up window: the inclusive ``[from_date, to_date]`` range (ISO dates
    compare lexically) or the explicit ``release_dates`` list. history = every EARLIER release --
    consumed only to seed ``prior_series_state`` for the F034 revision math, optionally bounded
    below by ``seed_from`` (an unbounded seed yields the true release_sequence; a bounded one
    counts from the seed window's start). Fails closed on empty bronze, an empty publish
    selection, or a requested release missing from bronze. ``quarantined`` release_dates (F034)
    are removed from BOTH groups; naming one explicitly raises instead.
    """
    by_release: dict[str, list[str]] = {}
    for key in all_keys:
        rd = parse_hive_key(key, "release_date")
        if rd:
            by_release.setdefault(rd, []).append(key)
    if not by_release:
        raise WasdeBronzeNotReadyError(
            f"no bronze WASDE release partitions under {_BRONZE_PREFIX} -- refusing to plan "
            "silver ahead of bronze (F032 ordering guard)")
    blocked_set = set(quarantined or ())
    if release_dates:
        named_blocked = sorted(set(release_dates) & blocked_set)
        if named_blocked:
            # checked BEFORE the bronze-membership check so the operator gets the true reason,
            # never the misleading "missing from bronze".
            raise WasdeQuarantineError(
                f"explicitly requested release_date(s) {named_blocked} are QUARANTINED: "
                + "; ".join(f"{d}: {QUARANTINE_REASONS.get(d, 'reason not recorded')}"
                            for d in named_blocked)
                + " -- fix the parse or remove the entry from QUARANTINE_REASONS; a named "
                  "release is never silently dropped")
    dropped = sorted(d for d in blocked_set if d in by_release)
    for d in dropped:
        del by_release[d]
    if dropped:
        logger.warning(
            "F034 QUARANTINE: excluding %d bronze release(s) from BOTH the publish window and "
            "the history seed: %s", len(dropped),
            {d: QUARANTINE_REASONS.get(d, "reason not recorded") for d in dropped})
    if release_dates:
        wanted = sorted(set(release_dates))
        missing = [d for d in wanted if d not in by_release]
        if missing:
            raise WasdeBronzeNotReadyError(
                f"requested release_date(s) missing from bronze: {missing}")
        publish = {d: sorted(by_release[d]) for d in wanted}
    else:
        publish = {
            d: sorted(ks) for d, ks in by_release.items()
            if (from_date is None or d >= from_date) and (to_date is None or d <= to_date)
        }
    if not publish:
        raise WasdeBronzeNotReadyError(
            f"no bronze release inside the publish window (from={from_date!r} to={to_date!r}); "
            f"bronze spans {min(by_release)}..{max(by_release)}")
    publish_min = min(publish)
    history = {
        d: sorted(ks) for d, ks in by_release.items()
        if d < publish_min and (seed_from is None or d >= seed_from)
    }
    return publish, history


def read_bronze_release_rows(
    keys_by_release: dict[str, list[str]],
    *,
    bucket: str,
    s3_client: Any,
    workers: int = _READ_WORKERS,
) -> dict[str, list[dict]]:
    """Download + decode the bronze long rows per release. ANY read failure raises: a silently
    absent history release would corrupt the revision series (wrong prior / sequence), so the
    ESR log-and-continue pattern is deliberately not reused here."""
    import pyarrow.parquet as pq

    flat = sorted(k for ks in keys_by_release.values() for k in ks)
    if not flat:
        return {}

    def _one(key: str) -> tuple[str, list[dict]]:
        data = s3_download_with_retry(bucket, key, s3_client)
        return key, pq.read_table(io.BytesIO(data)).to_pylist()

    rows_by_key: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=min(workers, len(flat))) as pool:
        for fut in as_completed([pool.submit(_one, k) for k in flat]):
            key, rows = fut.result()
            rows_by_key[key] = rows
    # keys stay in select_bronze_keys' sorted order so a multi-part release is deterministic.
    return {d: [r for k in ks for r in rows_by_key[k]] for d, ks in keys_by_release.items()}


def seed_series_state(history_by_release: dict[str, Sequence[dict]]) -> dict:
    """Thread the F034 revision series over PRIOR releases' bronze rows (chronological) and return
    the carried state for :func:`build_release_objects`. History rows are transformed but never
    staged; region-gate findings on history do not block (the gate protects the PUBLISHED axis),
    but a :class:`~leviathan.transforms.bronze_to_silver.usda_wasde_silver.WasdeKeyConflict` in
    history still raises -- an unreliable seed must never silently degrade."""
    state: dict = {}
    for release_date in sorted(history_by_release):
        res = W.build_silver_frame(history_by_release[release_date], prior_series_state=state)
        state = res.series_state
    return state


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
    prior_series_state: Optional[dict] = None,
):
    """Construct a REGISTERED-strategy :class:`ShadowPublisher` for the WASDE silver objects and run
    it under ``auth``. Returns ``(manifest, results)``. Nothing canonical is touched unless
    ``auth.may_mutate_canonical`` (the guard's canonical verdict). ``prior_series_state`` seeds the
    F034 revision series from bronze HISTORY (:func:`seed_series_state`), so a bounded catch-up
    links its revisions to the true predecessor releases instead of minting first-estimates."""
    objects, results = build_release_objects(
        bronze_by_release, contract, prior_series_state=prior_series_state)
    # F033 floor: the gate runs over the PUBLISHED region axis of each release; ANY finding refuses
    # the whole run BEFORE staging (shadow included) -- junk must be quarantined, never published.
    gate_red = {r.release_date: [g.to_dict() for g in r.region_gate] for r in results if r.region_gate}
    if gate_red:
        raise WasdeRegionGateError(
            f"F033 region-cleanliness gate red on the published axis; staging refused: {gate_red}")
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


def run_from_bronze(
    *,
    contract: dict,
    auth,
    s3_client: Any,
    glue_client: Any,
    bronze_keys: Sequence[str],
    bucket: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    release_dates: Optional[Sequence[str]] = None,
    seed_history: bool = True,
    seed_from: Optional[str] = None,
    quarantined: Optional[Sequence[str]] = None,
    shadow_prefix: Optional[str] = None,
    manifest_store=None,
    run_id: Optional[str] = None,
):
    """The bronze-read runner: bounded release selection -> ``prior_series_state`` seeding from
    bronze HISTORY -> F034 transform -> F015/F013 controlled publish. Returns
    ``(manifest, results)``; clients are injectable so the whole path is test-provable offline."""
    publish_keys, history_keys = select_bronze_keys(
        bronze_keys, from_date=from_date, to_date=to_date,
        release_dates=release_dates, seed_from=seed_from, quarantined=quarantined)
    logger.info(
        "wasde runner: publish releases=%s history releases=%d (seed_history=%s seed_from=%s)",
        sorted(publish_keys), len(history_keys), seed_history, seed_from)
    bronze_by_release = read_bronze_release_rows(publish_keys, bucket=bucket, s3_client=s3_client)
    prior_state = None
    if seed_history and history_keys:
        history_rows = read_bronze_release_rows(history_keys, bucket=bucket, s3_client=s3_client)
        prior_state = seed_series_state(history_rows)
    return stage_silver_objects(
        bronze_by_release, contract, auth, s3_client, glue_client,
        shadow_prefix=shadow_prefix, manifest_store=manifest_store, run_id=run_id,
        prior_series_state=prior_state)


def _publish_target(account_id: str, role_arn: str, bucket: str, database: str) -> PublishTarget:
    """The publish target the guard authorizes for this task: the canonical silver/wasde surface."""
    return PublishTarget(account_id=account_id, bucket=bucket, database=database,
                         prefix=_CANONICAL_PREFIX, role_arn=role_arn, table=TABLE)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="WASDE bronze->silver controlled publish (F034/F035)")
    p.add_argument("--environment", default="leviathan_dev")
    p.add_argument("--bucket", default=None)
    p.add_argument("--database", default=None)
    p.add_argument("--aws-region", dest="aws_region", default=None)
    p.add_argument("--run-id", default=None)
    p.add_argument("--from", dest="from_date", default=None,
                   help="inclusive lower release_date bound (ISO) of the publish window")
    p.add_argument("--to", dest="to_date", default=None,
                   help="inclusive upper release_date bound (ISO) of the publish window")
    p.add_argument("--since-days", dest="since_days", type=int, default=None,
                   help="INCREMENTAL PUBLISH: derive --from as today-N days. The scheduled fire "
                        "uses 75 (covers the current monthly release plus the two before it, so a "
                        "missed month still catches up on the next fire) instead of republishing "
                        "all 600+ releases. Mutually exclusive with --from.")
    p.add_argument("--release-date", dest="release_dates", action="append", default=None,
                   help="publish EXACTLY this bronze release (repeatable; overrides --from/--to)")
    p.add_argument("--seed-from", dest="seed_from", default=None,
                   help="lower bound for the history seed read (default: thread ALL prior bronze; "
                        "a bound trades true release_sequence for fewer reads)")
    p.add_argument("--no-history-seed", dest="no_history_seed", action="store_true",
                   help="skip prior_series_state seeding (per-release-local revision recompute)")
    p.add_argument("--quarantine-release", dest="quarantine_releases", action="append",
                   default=None,
                   help="ADDITIVE ad-hoc F034 quarantine (repeatable). Union'd with the pinned "
                        "QUARANTINED_RELEASES; use it to unblock a fire while the pinned entry "
                        "is being reviewed, then promote the date into QUARANTINE_REASONS with "
                        "its natural key and both divergent estimates.")
    p.add_argument("--shadow-prefix", default=None)
    p.add_argument("--publish-mode", default="dry-run",
                   choices=["dry-run", "shadow", "canonical"],
                   help="default dry-run; canonical needs a signed approval (gated B-wave)")
    p.add_argument("--contract-version", default=None)
    return p.parse_args(argv)


def _resolve_from_date(args: argparse.Namespace, *, today: Optional[date] = None) -> Optional[str]:
    """The publish window's lower bound: explicit --from, else today - --since-days, else None.

    Passing BOTH is a fail-closed configuration error (SystemExit): a rolling window silently
    overriding a pinned one, or vice versa, is exactly the class of ambiguity that let an
    unbounded scheduled command republish 624 releases a fire."""
    if args.from_date and args.since_days is not None:
        raise SystemExit("--from and --since-days are mutually exclusive: pass exactly one "
                         "(pin the window or roll it, never both)")
    if args.from_date:
        return args.from_date
    if args.since_days is None:
        return None
    if args.since_days < 1:
        raise SystemExit(f"--since-days must be >= 1, got {args.since_days}")
    return ((today or datetime.now(timezone.utc).date())
            - timedelta(days=args.since_days)).isoformat()


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()
    args = _parse_args(argv)
    reg = load_registry()
    contract = reg.table(TABLE)
    if args.contract_version is not None and str(args.contract_version) != str(contract.get("schema_version")):
        # a stale jobdef pin must fail loudly, never publish under a drifted contract.
        raise SystemExit(
            f"--contract-version {args.contract_version!r} != registry schema_version "
            f"{contract.get('schema_version')!r}")
    bucket = args.bucket or contract["s3_bucket"]
    database = args.database or contract["glue_database"]
    aws_region = args.aws_region or os.environ.get("AWS_REGION", "us-east-1")
    run_id = args.run_id or datetime.now(timezone.utc).strftime("wasde-silver-%Y%m%dT%H%M%SZ")

    import boto3

    # Guard FIRST (fail-closed, before any read): mode from argv > LEVIATHAN_PUBLISH_MODE > dry-run;
    # canonical additionally needs the env invariants + the signed LEVIATHAN_APPROVAL_JSON artifact
    # (loaded inside authorize_publish) verified against LEVIATHAN_APPROVAL_SECRET + STS identity.
    sts = boto3.client("sts", region_name=aws_region)
    ident = sts.get_caller_identity()
    auth = authorize_publish(
        _publish_target(ident["Account"], ident["Arn"], bucket, database),
        argv=list(argv) if argv is not None else sys.argv,
    )
    glue_client = boto3.client("glue", region_name=aws_region) if auth.may_mutate_canonical else None
    s3_client = get_thread_local_s3_client(aws_region)

    bronze_keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    logger.info("found %d bronze WASDE parquet objects under %s", len(bronze_keys), _BRONZE_PREFIX)

    from_date = _resolve_from_date(args)
    quarantined = tuple(sorted(set(QUARANTINED_RELEASES) | set(args.quarantine_releases or ())))
    logger.info("wasde window: from=%s to=%s (since_days=%s) seed_from=%s quarantined=%s",
                from_date, args.to_date, args.since_days, args.seed_from, list(quarantined))

    manifest, results = run_from_bronze(
        contract=contract, auth=auth, s3_client=s3_client, glue_client=glue_client,
        bronze_keys=bronze_keys, bucket=bucket,
        from_date=from_date, to_date=args.to_date, release_dates=args.release_dates,
        seed_history=not args.no_history_seed, seed_from=args.seed_from,
        quarantined=quarantined,
        shadow_prefix=args.shadow_prefix, run_id=run_id)

    for res in results:
        print(json.dumps(res.to_summary(), default=str))  # ensure_ascii default: cp1252-safe
    print(f"wasde_silver_task: mode={auth.mode.value} state={manifest.state.value} "
          f"releases={len(results)} from={from_date} quarantined={list(quarantined)} "
          f"run_id={run_id}")
    return 1 if manifest.state is ManifestState.FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
