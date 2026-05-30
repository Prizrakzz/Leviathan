"""Writer: converts ChunkExtractionResults to Parquet and writes to S3.

Four Parquet tables are written per (source, year, month) partition:
  - entities    → stress events
  - causal_edges → causal links
  - forecasts   → production forecasts
  - sentiment   → tone records + policy changes

Partition layout:
  graphrag/{table}/source={source}/year={year}/month={month:02d}/{table}.parquet

Idempotency: if entities.parquet already exists and force_overwrite=False,
the entire partition is skipped (entities is written last, so its presence
guarantees all four tables landed).
"""
from __future__ import annotations

import io
import logging
from typing import List

import boto3
import pyarrow as pa
import pyarrow.parquet as pq

from leviathan.transforms.text_to_graphrag.schema import ChunkExtractionResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Arrow schemas for each table
# ---------------------------------------------------------------------------

_ENTITY_SCHEMA = pa.schema([
    ("doc_key", pa.string()),
    ("document_date", pa.string()),
    ("source", pa.string()),
    ("section_name", pa.string()),
    ("chunk_index", pa.int32()),
    ("commodity", pa.string()),
    ("origin", pa.string()),
    ("stress_type", pa.string()),
    ("severity", pa.int8()),
    ("crop_year", pa.string()),
    ("time_window", pa.string()),
])

_CAUSAL_EDGE_SCHEMA = pa.schema([
    ("doc_key", pa.string()),
    ("document_date", pa.string()),
    ("source", pa.string()),
    ("section_name", pa.string()),
    ("chunk_index", pa.int32()),
    ("cause", pa.string()),
    ("effect", pa.string()),
    ("cause_commodity", pa.string()),
    ("cause_origin", pa.string()),
    ("effect_commodity", pa.string()),
    ("effect_origin", pa.string()),
    ("lag", pa.string()),
    ("marker", pa.string()),
    ("confidence", pa.string()),
])

_FORECAST_SCHEMA = pa.schema([
    ("doc_key", pa.string()),
    ("document_date", pa.string()),
    ("source", pa.string()),
    ("section_name", pa.string()),
    ("chunk_index", pa.int32()),
    ("commodity", pa.string()),
    ("origin", pa.string()),
    ("value", pa.float64()),
    ("unit", pa.string()),
    ("crop_year", pa.string()),
    ("direction", pa.string()),
])

_SENTIMENT_SCHEMA = pa.schema([
    ("doc_key", pa.string()),
    ("document_date", pa.string()),
    ("source", pa.string()),
    ("section_name", pa.string()),
    ("chunk_index", pa.int32()),
    # Tone fields
    ("commodity", pa.string()),
    ("origin", pa.string()),
    ("tone_score", pa.int8()),
    ("phrases", pa.string()),          # JSON-encoded list of phrases
    # Policy change fields (nullable when row is a pure tone record)
    ("policy_country", pa.string()),
    ("policy_commodity", pa.string()),
    ("policy_type", pa.string()),
    ("policy_direction", pa.string()),
])


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def partition_exists(
    s3_client,
    bucket: str,
    source: str,
    year: int,
    month: int,
) -> bool:
    """Return True if the entities Parquet file for this partition exists."""
    key = _s3_key("entities", source, year, month)
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except s3_client.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise


def write_partition(
    results: List[ChunkExtractionResult],
    s3_client,
    bucket: str,
    source: str,
    year: int,
    month: int,
) -> None:
    """Assemble four Parquet tables from results and write them to S3.

    Writes tables in order: causal_edges, forecasts, sentiment, entities.
    entities is written last so its presence acts as an idempotency marker.

    Args:
        results:   All ChunkExtractionResults for this (source, year, month).
        s3_client: boto3 S3 client.
        bucket:    Target S3 bucket name.
        source:    Source identifier (usda_wasde, usda_wap, …).
        year:      Publication year.
        month:     Publication month (1-12).
    """
    import json as _json

    # ---- Entities (stress events) ----------------------------------------
    entity_rows: list[dict] = []
    causal_rows: list[dict] = []
    forecast_rows: list[dict] = []
    sentiment_rows: list[dict] = []

    for r in results:
        base = {
            "doc_key": r["doc_key"],
            "document_date": r["document_date"],
            "source": r["source"],
            "section_name": r["section_name"],
            "chunk_index": r["chunk_index"],
        }

        for ev in r.get("stress_events") or []:
            entity_rows.append({
                **base,
                "commodity": ev.get("commodity") or "",
                "origin": ev.get("origin") or "",
                "stress_type": ev.get("stress_type") or "",
                "severity": int(ev.get("severity") or 0),
                "crop_year": ev.get("crop_year") or "",
                "time_window": ev.get("time_window") or "",
            })

        for lk in r.get("causal_links") or []:
            causal_rows.append({
                **base,
                "cause": lk.get("cause") or "",
                "effect": lk.get("effect") or "",
                "cause_commodity": lk.get("cause_commodity") or "",
                "cause_origin": lk.get("cause_origin") or "",
                "effect_commodity": lk.get("effect_commodity") or "",
                "effect_origin": lk.get("effect_origin") or "",
                "lag": lk.get("lag") or "",
                "marker": lk.get("marker") or "",
                "confidence": lk.get("confidence") or "",
            })

        for fc in r.get("production_forecasts") or []:
            val = fc.get("value")
            forecast_rows.append({
                **base,
                "commodity": fc.get("commodity") or "",
                "origin": fc.get("origin") or "",
                "value": float(val) if val is not None else None,
                "unit": fc.get("unit") or "",
                "crop_year": fc.get("crop_year") or "",
                "direction": fc.get("direction") or "",
            })

        # Tone record (one per chunk)
        tone = r.get("tone") or {}
        base_sentiment = {
            **base,
            "commodity": tone.get("commodity") or "",
            "origin": tone.get("origin") or "",
            "tone_score": int(tone.get("score") or 0),
            "phrases": _json.dumps(tone.get("phrases") or []),
        }

        # Each policy change gets its own row; orphan tone record included too
        policy_list = r.get("policy_changes") or []
        if policy_list:
            for pc in policy_list:
                sentiment_rows.append({
                    **base_sentiment,
                    "policy_country": pc.get("country") or "",
                    "policy_commodity": pc.get("commodity") or "",
                    "policy_type": pc.get("policy_type") or "",
                    "policy_direction": pc.get("direction") or "",
                })
        else:
            sentiment_rows.append({
                **base_sentiment,
                "policy_country": "",
                "policy_commodity": "",
                "policy_type": "",
                "policy_direction": "",
            })

    # ---- Write tables (entities last — idempotency marker) ----------------
    _write_table(causal_rows, _CAUSAL_EDGE_SCHEMA, "causal_edges",
                 s3_client, bucket, source, year, month)
    _write_table(forecast_rows, _FORECAST_SCHEMA, "forecasts",
                 s3_client, bucket, source, year, month)
    _write_table(sentiment_rows, _SENTIMENT_SCHEMA, "sentiment",
                 s3_client, bucket, source, year, month)
    _write_table(entity_rows, _ENTITY_SCHEMA, "entities",
                 s3_client, bucket, source, year, month)

    logger.info(
        "Wrote partition source=%s year=%d month=%02d: "
        "%d entities  %d causal_edges  %d forecasts  %d sentiment",
        source, year, month,
        len(entity_rows), len(causal_rows), len(forecast_rows), len(sentiment_rows),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _s3_key(table: str, source: str, year: int, month: int) -> str:
    return f"graphrag/{table}/source={source}/year={year}/month={month:02d}/{table}.parquet"


def _write_table(
    rows: list[dict],
    schema: pa.Schema,
    table_name: str,
    s3_client,
    bucket: str,
    source: str,
    year: int,
    month: int,
) -> None:
    """Convert rows → Arrow table → Snappy Parquet → S3."""
    if not rows:
        # Write an empty table so every partition always has 4 files
        table = pa.table({field.name: pa.array([], type=field.type) for field in schema})
    else:
        table = pa.Table.from_pylist(rows, schema=schema)

    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)

    key = _s3_key(table_name, source, year, month)
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.read())
    logger.debug("Uploaded s3://%s/%s (%d rows)", bucket, key, len(rows))
