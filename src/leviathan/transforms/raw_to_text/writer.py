from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from leviathan.transforms.raw_to_text.schema import DocumentJson

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

# --- Phase G / G2: the KEY-LAYOUT GATE, DARK behind CORPUS_LANE_GATES ------------------------------
# THE MEASURED TRIGGER. No document.json in this corpus carries a date field (schema.py:15-26), so
# the publication date the PIT filter reads is derived FROM THE KEY by `evidence.pub_date_layout`
# (evidence.py:236-289) -- seven layouts plus two documented refusals. What a key no rule recognises
# does TODAY is fall through `doc_date_detail` (evidence.py:318-324) to
# `y = bx._year_of(key); return date(int(y), 1, 1), "year_floor"`, and failing that to `epoch_floor`
# 1970-01-01. A floored date is always on or BEFORE the true release, i.e. leakage-PERMISSIVE in
# exactly the field the as-of filter compares (evidence.py:639). The D-EC P0c census measured 2,036
# of 7,056 documents (28.9%) on that fallback; the seven rules closed that class and the standing
# residue is 62 documents (conab 55 + mpob 7). `pub_date_layout`'s own docstring says an unknown
# layout "should be read as *add a rule*, not as *this document has no date*" -- and NOTHING enforced
# that until this gate.
#
# THE FENCE. When the flag is ARMED, a write whose key cannot be dated is REFUSED and COUNTED, and a
# NAMED refusal is refused too (that is the clause the design's draft was missing: conab and mpob
# floor BY CONSTRUCTION, so refusing only `unknown` would have let them keep minting floors).
#
# WHAT IT DOES NOT COVER, deliberately: it validates the KEY, never the body. A key that parses to a
# date the document's own printed header contradicts is the wrong-early class, and that is the SHADOW
# CENSUS's check 4 (day-equality for the five day-precision layouts, year-month equality for the two
# month-precision ones), not this gate's -- reading the header here would cost a parse per write on
# the producers' hot path.
#
# FLAG-OFF IS BYTE-IDENTICAL AND FREE: the env read below is the whole cost, and
# `leviathan.graphrag.corpus_coverage` (which reaches evidence.py -> extract.py -> yaml + pydantic)
# is imported ONLY when the flag is on. The flag name and the truthy set are duplicated from
# corpus_coverage rather than imported for exactly that reason, and the deck PINS the two copies
# equal so they cannot drift.
_GATE_FLAG = "CORPUS_LANE_GATES"
_TRUTHY = frozenset({"1", "true", "on", "yes"})


def _gate_armed() -> bool:
    return str(os.environ.get(_GATE_FLAG) or "").strip().lower() in _TRUTHY


def document_exists(s3_client: S3Client, bucket: str, key: str) -> bool:
    """Return True if a document.json already exists at *key* in *bucket*.

    Used as the idempotency gate before any extraction is attempted — covers
    pdfplumber, TXT decode, and Textract uniformly.
    """
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise


def write_document(
    s3_client: S3Client,
    bucket: str,
    key: str,
    doc: DocumentJson,
) -> None:
    """Serialise *doc* as compact JSON and write it to S3 at *key*.

    With ``CORPUS_LANE_GATES`` armed, the Phase-G key-layout gate runs FIRST and raises
    ``corpus_coverage.KeyLayoutRefused`` (counted, never silent) when *key*'s publication date cannot
    be parsed from the key -- an unknown layout, or one of the two named refusals that still floor to
    Jan-1. With the flag off this function is byte-for-byte what it was: same body, same put_object.
    """
    if _gate_armed():
        from leviathan.graphrag import corpus_coverage as _cc  # lazy: the dark path pays nothing
        _cc.assert_key_layout(key)
    body = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
    )
