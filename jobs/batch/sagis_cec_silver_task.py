"""SILVER-F058 batch task: SAGIS CEC raw -> silver_sagis_cec (D6=(a) raw->silver-direct).

Task #118, wave W2/W3. Reads the intact raw CEC workbooks (pdf / legacy ``.doc`` / ``.xls``) DIRECTLY
from S3, parses them IN-PROCESS via the era-aware W1 parser
(:func:`leviathan.transforms.raw_to_bronze.sagis_cec.parse_cec_report_detailed`), reconciles
estimate numbers across the whole corpus (D2), selects the authoritative estimate per natural key,
computes the no-lookahead revision metrics, and publishes shadow-first (``--publish-mode`` default
dry-run).

There is NO bronze hop. Folding the era-aware parser into the silver read path is the ratified
architecture (D6=(a), the ``sagis_deliveries_task`` precedent): it structurally removes the
live-bronze correction gap that DEFERRED this task on 2026-07-17. The old out-of-band bronze
mislabeled the developing sector as ``commercial`` and collapsed physically-distinct sector rows onto
one natural key (61 conflict keys), so ``transform_sagis_cec`` correctly failed closed; re-parsing
from intact raw removes the mislabels at the source.

Fail-closed per file: a report whose era signature is unknown (:class:`CecEraError`), whose sector
rows collapse (:class:`CecCollapseError`), whose era reader is deliberately not built
(:class:`CecNotImplementedEra` -- winter-only / preliminary layouts), or that cannot establish its
production_year/report_month (:class:`CecParseError`) QUARANTINES THAT FILE (counted, named) and the
rest of the corpus proceeds. Byte-identical re-fetched duplicates (the 2026-07-16 renamed-duplicate
raw, D5) are deduped by raw-content hash, keeping the first source_key in sorted-key order so
re-runs are byte-identical. A corpus-level D2 contradiction (:class:`CecEstimateError` from
``reconcile_estimate_numbers``: a later release carrying a lower printed estimate number) is NOT
swallowed -- it fails the run.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from dataclasses import dataclass, field
from typing import Iterable

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import (
    add_standard_producer_args,
    authorize_for_contract,
    build_flat_publish,
    null_metrics_for,
)
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_sagis_cec_key
from leviathan.transforms.bronze_to_silver.sagis_cec import (
    CecObservation,
    transform_sagis_cec,
)
from leviathan.transforms.raw_to_bronze.sagis_cec import (
    CecParseError,
    QuarantineRecord,
    parse_cec_report_detailed,
    reconcile_estimate_numbers,
)

logger = get_logger("sagis_cec_silver_task")

TABLE = "silver_sagis_cec"
_RAW_PREFIX = "raw/production/source=sagis_cec/"
_REPORT_SUFFIXES = (".pdf", ".doc", ".xls")

# Genuine programming errors are re-raised (never masked as a quarantine); everything else a
# per-file parse can throw (a corrupt object with valid magic -> pdfplumber/xlrd/olefile/struct
# error) is an UNREADABLE source and is quarantined so one bad raw object cannot kill the corpus run.
_LOGIC_BUGS = (TypeError, KeyError, IndexError, AttributeError, NameError)


def _ascii(s: str) -> str:
    """cp1252-console-safe rendering of free text for logs (source labels can be accented)."""
    return (s or "").encode("ascii", "replace").decode("ascii")


def _is_report_key(key: str) -> bool:
    """True for a raw CEC report object (pdf/.doc/.xls), excluding the admin schedule files.

    The fetch already excludes ``CEC_Dates_YYYY.*`` (its download regex uses ``CEC(?!_Dates_)``);
    this is a defensive second gate so a stray admin object can never reach the era detector."""
    name = key.rsplit("/", 1)[-1].lower()
    if not name.endswith(_REPORT_SUFFIXES):
        return False
    if name.startswith("cec_dates"):
        return False
    return True


@dataclass
class RawParseCensus:
    """Per-run parse census: what was seen, parsed, quarantined, and deduped (the W2 quantify step)."""

    n_files: int = 0
    n_parsed: int = 0
    era_counts: dict[str, int] = field(default_factory=dict)
    quarantined_files: list[tuple[str, str, str]] = field(default_factory=list)  # (key, err_type, detail)
    deduped_files: list[tuple[str, str]] = field(default_factory=list)           # (key, kept_key)
    row_quarantine: list[QuarantineRecord] = field(default_factory=list)


def parse_raw_reports(items: Iterable[tuple[str, bytes]]) -> tuple[list[CecObservation], RawParseCensus]:
    """Parse an ORDERED stream of ``(source_key, raw_bytes)`` into observations + a census.

    Pure (AWS-free): the caller supplies the bytes. Fail-closed per file -- a :class:`CecParseError`
    (or any subclass: unknown era, collapse, not-implemented era, missing year/month) quarantines that
    file (counted + named) and the loop continues. Byte-identical re-fetched duplicates (D5) are
    deduped by raw-content sha256, keeping the FIRST source_key in the input order; callers pass keys
    sorted, so the kept key is deterministic and re-runs are byte-identical."""
    obs: list[CecObservation] = []
    census = RawParseCensus()
    seen_hashes: dict[str, str] = {}
    for source_key, data in items:
        census.n_files += 1
        digest = hashlib.sha256(data).hexdigest()
        first = seen_hashes.get(digest)
        if first is not None:
            census.deduped_files.append((source_key, first))
            continue
        seen_hashes[digest] = source_key
        try:
            result = parse_cec_report_detailed(data, source_key=source_key)
        except CecParseError as exc:
            # ratified fail-closed (unknown era / collapse / not-implemented era / missing y-m).
            census.quarantined_files.append((source_key, type(exc).__name__, _ascii(str(exc))))
            continue
        except _LOGIC_BUGS:
            raise  # a genuine bug -- surface it, do NOT hide it behind a quarantine
        except Exception as exc:  # noqa: BLE001 -- an unreadable/corrupt raw object; keep the corpus alive
            census.quarantined_files.append(
                (source_key, f"unreadable:{type(exc).__name__}", _ascii(str(exc))))
            continue
        obs.extend(result.observations)
        census.row_quarantine.extend(result.quarantined)
        census.era_counts[result.era] = census.era_counts.get(result.era, 0) + 1
        census.n_parsed += 1
    return obs, census


def _log_census(census: RawParseCensus) -> None:
    logger.info("CEC raw parse: %d report files seen, %d parsed, %d files quarantined, %d deduped",
                census.n_files, census.n_parsed, len(census.quarantined_files),
                len(census.deduped_files))
    for era, n in sorted(census.era_counts.items()):
        logger.info("  era %-12s %d reports", era, n)
    for key, err_type, detail in census.quarantined_files:
        logger.warning("  QUARANTINE file %s: %s: %s", _ascii(key), err_type, detail)
    for q in census.row_quarantine:
        logger.warning("  QUARANTINE row [%s] %s (%s): %s",
                       _ascii(q.era), q.reason, _ascii(q.source_key), _ascii(q.detail))
    for key, kept in census.deduped_files:
        logger.info("  DEDUP file %s (byte-identical to %s)", _ascii(key), _ascii(kept))


def load_observations(bucket: str, aws_region: str, s3=None) -> list[CecObservation]:
    """List + download every raw CEC report and parse it in-process into ``CecObservation`` records.

    Reads ``raw/production/source=sagis_cec/`` (NOT bronze). Keys are sorted so the parse order --
    and hence the D5 dedup tie-break and any byte-level output ordering -- is deterministic."""
    from leviathan.storage.s3 import (
        get_thread_local_s3_client,
        list_s3_keys,
        s3_download_with_retry,
    )

    s3 = s3 or get_thread_local_s3_client(aws_region)
    keys = sorted(k for k in list_s3_keys(bucket, _RAW_PREFIX, aws_region=aws_region)
                  if _is_report_key(k))

    def _stream() -> Iterable[tuple[str, bytes]]:
        for key in keys:
            yield key, s3_download_with_retry(bucket, key, s3)

    obs, census = parse_raw_reports(_stream())
    _log_census(census)
    return obs


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SAGIS CEC raw -> silver")
    add_standard_producer_args(parser)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    args = _parse_args()
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    contract = load_registry().table(TABLE)
    # D2 corpus step: reconcile estimate numbers from release-date ordering (with the D2a source_key
    # tie-break) BEFORE authoritative selection, then transform to the silver revision metrics.
    observations = reconcile_estimate_numbers(load_observations(bucket, aws_region))
    df = transform_sagis_cec(observations)
    logger.info("silver rows: %d", len(df))
    if df.empty:
        logger.error("empty silver output; aborting")
        return 1

    # Quantify the value-column non-null fractions vs the contract floor (the D4 recalibration input:
    # if revision_t / revision_surprise breach min_nonnull_frac at the shadow hook, add
    # min_nonnull_frac_overrides to the contract and re-run -- the hook is already wired below).
    value_columns = list(contract.get("value_columns", []))
    floor = contract.get("min_nonnull_frac")
    for col, frac in null_metrics_for(df, value_columns).items():
        logger.info("value column %-18s non-null fraction %.4f (floor %s)", col, frac, floor)

    auth = authorize_for_contract(contract, publish_mode=args.publish_mode)
    from leviathan.storage.s3 import get_thread_local_s3_client
    publish_s3 = None if args.publish_mode == "dry-run" else get_thread_local_s3_client(aws_region)
    plan = build_flat_publish(
        df=df, contract=contract, canonical_key=silver_sagis_cec_key(),
        auth=auth, s3_client=publish_s3, job="sagis_cec_silver", run_id=args.run_id,
    )
    manifest = plan.run()
    logger.info("publish %s state=%s mode=%s rows=%d", TABLE, manifest.state.value,
                args.publish_mode, len(df))
    return 0


if __name__ == "__main__":
    sys.exit(main())
