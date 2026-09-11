"""Glue Python Shell: raw → bronze NASA POWER.

Downloads raw JSON files from S3, parses the NASA POWER payload into daily rows,
and writes bronze Parquet files. Processes files concurrently using a thread pool.

A bronze file is rewritten when the RAW OBJECT IT IS DERIVED FROM is newer than it
(``fresh_bronze_keys`` -- the SILVER-V002 rule, applied one layer up), not merely skipped because it
exists. ``--force_overwrite`` still reprocesses everything.

THE FREEZE THIS CLOSES (MEASURED 2026-09-11)
--------------------------------------------
``BaseRawToBronzeJob.run`` (storage/base_jobs.py:311-316) lists existing bronze and ``_process_one``
(:348-350) returns "skipped" on MERE EXISTENCE -- no mtime comparison anywhere. MEASURED on
``corn_cbot/united_states/us_corn_ohio/year=2026``: raw month=08 was refetched 2026-09-11T08:04:59Z and
carries 31 of 31 real T2M_MAX / T2M_MIN days, while bronze month=08 still held the 22 rows it was given
on 2026-08-22T11:30:14Z. Twenty days of green daily runs read the fresh raw and declined to rewrite the
bronze; silver carried the freeze faithfully, and ``gold_weather_z`` -- a SERVED numbers card -- tipped
at data month 2026-07 while its own card promised 2026-08.

WHY THIS OVERRIDE AND NOT ``base_jobs``. The precedent is one layer down and in this same family:
``jobs/glue/bronze_to_silver_nasa_power.py`` already carries its OWN ``run()`` that calls
``select_partitions_to_write`` for SILVER-V002 while the shared base class stays untouched. Blast
radius here is nasa_power only. The WIDE fix -- the mtime rule inside ``BaseRawToBronzeJob`` itself,
closing the whole raw->bronze class estate-wide the way ``select_partitions_to_write`` closed
bronze->silver -- is the better end state and is the OWNER'S CALL, not this lane's: ``base_jobs.py`` is
shared by every source family and a co-tenant lane is live in the tree.

NO SHRINK FLOOR HERE, AND THAT IS A DECISION, NOT AN OMISSION. The cpc lane's ``_rewrite_would_shrink``
guards a partition ASSEMBLED from many raw days, where one failed fetch silently shrinks the rewrite.
A nasa_power bronze object is 1:1 with exactly one raw object and is a total function of it, so a
smaller bronze can only mean a smaller RAW -- a fact of the raw layer that bronze must carry, not hide.

AND THE OPEN EDGE THAT DECISION LEAVES, STATED RATHER THAN SETTLED (found in review). Because bronze
now FOLLOWS raw instead of ignoring it, a partial raw payload propagates raw -> bronze -> silver, and
``weather_z._complete_months_only`` (transforms/gold/weather_z.py:259-272) then DROPS that month from
gold. ``jobs/ingest/fetch_nasa_power.py`` rewrites the CURRENT and PREVIOUS calendar months
unconditionally (``_is_trailing_window``), so inside that window the next day's refetch heals a partial
landing -- but a partial that lands on the LAST day a month is in the window (a bad 2026-09-30 fetch for
August) is never revisited and freezes that month out of gold. Pre-fix this could not happen only
because bronze was never rewritten AT ALL, which was the bug being repaired: it is a residual, not a
regression, and it is strictly smaller than the freeze it replaces. The mitigation belongs at the RAW
layer -- a floor in ``fetch_nasa_power.py`` that refuses to overwrite a complete raw month with a
shorter payload -- which is another lane's file, so it is named here and left open, not half-built.

Required args: --commodity, --bucket, --aws_region
Optional args: --ingest_date (default: today), --force_overwrite (default: false)
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from bootstrap import run_bootstrap

run_bootstrap()

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.common.validation import load_schema, validate_raw_json
from leviathan.storage.base_jobs import BaseRawToBronzeJob, filter_keys_by_year
from leviathan.storage.paths import bronze_weather_key, parse_hive_key
from leviathan.storage.s3 import list_s3_keys_with_mtime
from leviathan.transforms.raw_to_bronze.nasa_power import nasa_power_payload_to_daily_dataframe

logger = get_logger("raw_to_bronze_nasa_power")


def fresh_bronze_keys(raw_mtimes: dict, bronze_mtimes: dict, bronze_key_of) -> tuple[set, list]:
    """Which existing bronze keys may be SKIPPED, and which are stale and must be rewritten.

    Returns ``(fresh_keys, stale_keys)``. ``fresh_keys`` is handed to ``BaseRawToBronzeJob._process_one``
    as its ``existing_bronze`` set, so a stale key -- simply absent from that set -- takes the ordinary
    write path with no change to ``_process_one`` at all.

    THE YARDSTICK IS PER-FILE, NOT A PREFIX MAX. A nasa_power bronze key is 1:1 with the raw key it is
    derived from (``bronze_key(raw_key)``), so the only raw object whose age says anything about a given
    bronze object is its OWN source. A prefix-wide ``max(raw_mtime)`` -- the shape
    ``select_partitions_to_write`` uses one layer down, where a silver partition is assembled from many
    bronze files -- would mark all 3,843 of a commodity's 2026 bronze objects stale the moment ANY one
    raw file was refetched, i.e. a full rewrite of the layer every single day.

    EITHER TIMESTAMP MISSING => FRESH. An unknown is never grounds for a rewrite, the same reading
    ``select_partitions_to_write`` takes of a null ``bronze_max_mtime`` and ``_bronze_is_stale`` takes of
    a missing mtime: a benign no-op rerun stays a no-op (AV-12). A bronze key whose raw key is not in
    this listing at all (an orphan bronze from a retired raw object) is likewise left alone -- this
    function decides what to REWRITE, never what to delete.

    A RAW KEY THIS FUNCTION CANNOT MAP is skipped here rather than raised. ``bronze_key`` parses Hive
    segments and throws on a malformed key; before this override that throw happened INSIDE
    ``_process_one`` and became one dead-letter entry while the batch continued. Letting it escape from
    here would abort the whole commodity on one bad key -- strictly worse than the behaviour being
    repaired -- so the key is left out of both sets and ``_process_one`` meets it exactly as it used to."""
    fresh: set = set(bronze_mtimes)
    stale: list = []
    for raw_key, raw_mtime in raw_mtimes.items():
        try:
            bkey = bronze_key_of(raw_key)
        except Exception as exc:  # noqa: BLE001 -- the dead-letter path owns this, not the selector
            logger.warning("Cannot derive a bronze key for %s (%s: %s) -- leaving it to the "
                           "per-file dead-letter path", raw_key, type(exc).__name__, str(exc)[:160])
            continue
        bronze_mtime = bronze_mtimes.get(bkey)   # None == no bronze yet, or an unknown mtime
        if bronze_mtime is None or raw_mtime is None:
            continue
        if bronze_mtime < raw_mtime:
            fresh.discard(bkey)
            stale.append(bkey)
    return fresh, sorted(stale)


class NasaPowerRawToBronze(BaseRawToBronzeJob):
    source = "nasa_power"

    def __init__(self) -> None:
        super().__init__()
        self.ingest_date: str = self._parse_optional_str("ingest_date", default=date.today().isoformat())
        self._schema = load_schema(self.source)  # load once; validate_raw is called in the thread pool

    def bronze_key(self, raw_key: str) -> str:
        country = parse_hive_key(raw_key, "country")
        region = parse_hive_key(raw_key, "region")
        year = int(parse_hive_key(raw_key, "year"))
        month = int(parse_hive_key(raw_key, "month"))
        filename = raw_key.rsplit("/", 1)[-1].replace(".json", ".parquet")
        return bronze_weather_key("nasa_power", self.commodity, country, region, year, month, filename)

    def transform(self, raw_bytes: bytes, raw_key: str) -> pd.DataFrame:
        payload = json.loads(raw_bytes)
        country = parse_hive_key(raw_key, "country")
        region = parse_hive_key(raw_key, "region")
        return nasa_power_payload_to_daily_dataframe(
            payload=payload,
            source_file_name=raw_key.rsplit("/", 1)[-1],
            commodity=self.commodity,
            country=country,
            region=region,
            ingest_date=self.ingest_date,
        )

    def validate_raw(self, raw_bytes: bytes, raw_key: str) -> None:
        validate_raw_json(json.loads(raw_bytes), self._schema, context=raw_key)

    def run(self) -> None:
        """FRESHNESS-AWARE raw->bronze run (see the module docstring).

        The shape is the base class's own ``run()`` with ONE substitution: the ``existing_bronze`` set
        handed to ``_process_one`` is the set of bronze keys that are actually FRESH relative to their
        OWN raw object, not simply the set that exists. Everything else -- the thread pool, the
        per-file dead-letter path, the success/skipped/failed tally, the RuntimeError on any failure --
        is unchanged, and ``_process_one`` itself is untouched."""
        raw_objects = list_s3_keys_with_mtime(
            self.bucket, self.raw_prefix(), suffix=self.raw_suffix(), aws_region=self.aws_region
        )
        raw_keys = sorted(raw_objects)
        if self.year_window is not None:
            raw_keys = filter_keys_by_year(raw_keys, self.year_window)
        logger.info(
            "Found %d raw files for commodity=%s source=%s year_window=%s",
            len(raw_keys), self.commodity, self.source, self.year_window,
        )

        if self.force_overwrite:
            existing_bronze: set = set()
            logger.info("force_overwrite=true - reprocessing all files")
        else:
            bronze_objects = list_s3_keys_with_mtime(
                self.bucket, self.bronze_prefix(), suffix=".parquet", aws_region=self.aws_region
            )
            existing_bronze, stale = fresh_bronze_keys(
                {k: raw_objects[k] for k in raw_keys}, bronze_objects, self.bronze_key
            )
            logger.info(
                "%d existing bronze files: %d fresh (skipped), %d STALE and will be rewritten "
                "(bronze older than its own raw object)",
                len(bronze_objects), len(existing_bronze), len(stale),
            )
            for k in stale[:20]:
                logger.info("stale bronze -> rewrite: %s", k)

        success = skipped = failed = 0

        with ThreadPoolExecutor(max_workers=self._MAX_WORKERS) as pool:
            futures = {pool.submit(self._process_one, k, existing_bronze): k for k in raw_keys}
            for future in as_completed(futures):
                status, info = future.result()
                if status == "success":
                    success += 1
                elif status == "skipped":
                    skipped += 1
                else:
                    failed += 1
                    logger.error("Failed: %s", info)

        logger.info(
            "raw->bronze %s complete. success=%d  skipped=%d  failed=%d",
            self.source, success, skipped, failed,
        )
        if failed > 0:
            raise RuntimeError(
                f"{failed} files failed during raw->bronze {self.source} (commodity={self.commodity})."
            )


# Thin-contract entry (A-Wave-3): --commodity all (default) iterates every commodity discovered under
# the nasa_power raw prefix, self-windowed to the current year; a named --commodity in the Glue
# DefaultArguments preserves the single-commodity backfill (all years). Glue delivers job args in
# sys.argv, so the raw-argv thin-contract runner needs no getResolvedOptions here.
NasaPowerRawToBronze.run_thin_contract()
