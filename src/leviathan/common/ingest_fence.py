"""Raw->bronze staleness fence for the scheduled ingest lane (D-SG G2-1).

Every raw->bronze task in this estate skipped when its bronze OBJECT EXISTED and
never asked whether the RAW behind it moved. For a source whose raw key is
REWRITTEN in place (unica annual HTML, pink sheet XLSX) or whose newest snapshot
lands under a NEW key that maps to the SAME bronze key (fgis
year={y}/as_of={d}/CY{y}.csv -> bronze year={y}/part-000.parquet), that predicate
is permanently true after the first run: the freshest raw is selected and then
discarded, and the job exits 0.

``bronze_is_current`` replaces the existence test with a LastModified comparison.
It fails toward REBUILDING on any uncertainty -- never toward the silent no-op it
exists to kill.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def object_last_modified(s3_client: Any, bucket: str, key: str) -> Optional[datetime]:
    """Return an S3 object's LastModified as tz-aware UTC, or None if absent/unreadable."""
    try:
        head = s3_client.head_object(Bucket=bucket, Key=key)
    except Exception:  # noqa: BLE001 -- 404 / AccessDenied / transport all mean "unknown"
        return None
    lm = head.get("LastModified")
    if lm is None:
        return None
    return lm if lm.tzinfo else lm.replace(tzinfo=timezone.utc)


def bronze_is_current(
    s3_client: Any,
    bucket: str,
    raw_key: str,
    bronze_key: str,
) -> bool:
    """True only when *bronze_key* exists AND is at least as new as *raw_key*.

    False when bronze is absent, when the raw mtime is unreadable, or when raw
    moved after bronze was written.
    """
    bronze_lm = object_last_modified(s3_client, bucket, bronze_key)
    if bronze_lm is None:
        return False
    raw_lm = object_last_modified(s3_client, bucket, raw_key)
    if raw_lm is None:
        return False
    return bronze_lm >= raw_lm
