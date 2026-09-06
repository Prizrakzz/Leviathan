#!/usr/bin/env python
"""READ-ONLY census: which ESR RAW vintages actually carry the five net-commitment keys.

    python jobs/utils/esr_netcommitment_raw_census.py --out data/esr_netcommitment/raw_key_census.json
    python jobs/utils/esr_netcommitment_raw_census.py --codes 401,801 --head-bytes 32768

WHY THIS EXISTS (C-M3). The SILVER-F030 BF-W2 rollout has to know the FIRST as_of vintage whose
raw payload carries ``accumulatedExports`` / ``currentMYNetSales`` / ``currentMYTotalCommitment``
/ ``nextMYOutstandingSales`` / ``nextMYNetSales``.  Asserting that date and then bounding the
re-bronze by it makes the downstream verdict CIRCULAR: "all five read 0.0 on every earlier
vintage" would be guaranteed by the re-bronze scope, not by the source, and a verdict sentence
that cannot fail is not a measurement.  The repo's own 2026-07-10 inventory audit already
contradicts a hand-picked August bound -- it records the live corn API exposing
``nextMYOutstandingSales`` / ``nextMYNetSales`` on 2026-07-02.  So the bound is MEASURED here, on
raw, before anything is re-bronzed.

WHAT IT DOES AND DOES NOT DO. It LISTs ``raw/production/source=usda_esr/`` and issues one RANGED
GET (default: the first 16 KB) per probed object, parses the FIRST JSON record out of that head,
and reports which of the five key names that record carries.  Presence of the KEY is the question
-- a key present with a null value still counts as published, because that is exactly what the
bronze INV-4 law preserves.  It reads only: every call against the data is ``list_objects_v2`` or
a ranged ``get_object``; it registers nothing, touches no catalog, and writes nothing anywhere
except the one census artifact the operator names with ``--out``.

COST.  One HTTP range request per probed object.  MEASURED 2026-09-04 against
``s3://leviathan-dev-shahem-001``: 1,901 raw JSON objects, 446 of them dated (12 distinct as_of
vintages) and 1,455 undated backfill objects; the default full dated sweep is 446 ranged GETs of
16 KB = ~7 MB.

IN-VPC USE.  If the operator's laptop has no route, this same file runs unchanged as a Batch
command on ``leviathan-dev-usda-esr-bronze`` (it is inside the worker image's ``jobs/`` COPY set),
with ``--out`` pointed at an ``s3://`` URI.  No override body larger than a few hundred bytes is
needed, so it does not hit the 8,192-character container-override ceiling.

ASCII-only output.  No mutation of any kind.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import defaultdict

import boto3

RAW_PREFIX = "raw/production/source=usda_esr/"
AS_OF_RE = re.compile(r"as_of=(\d{8})")
CODE_RE = re.compile(r"commodity_code=(\d+)")
YEAR_RE = re.compile(r"market_year=(\d+)")

# The five FAS API field names, in the frozen ADR's order.
NET_COMMITMENT_KEYS = (
    "accumulatedExports",
    "currentMYNetSales",
    "currentMYTotalCommitment",
    "nextMYOutstandingSales",
    "nextMYNetSales",
)


def _first_record(head: bytes) -> dict | None:
    """Parse the FIRST JSON object out of a truncated array body, or None.

    The payload is a JSON array of per-(country, week) records that all share one key set, so the
    first record answers the question without downloading the object.  A raw ``json.loads`` cannot
    be used on a truncated body: this walks braces (string-aware) to find record 0's extent.
    """
    text = head.decode("utf-8", "replace")
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start:i + 1])
                except ValueError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def list_raw(s3, bucket: str) -> tuple[list[str], list[str]]:
    """Return ``(dated_keys, undated_keys)`` under the ESR raw prefix."""
    dated: list[str] = []
    undated: list[str] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=RAW_PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".json"):
                continue
            (dated if AS_OF_RE.search(key) else undated).append(key)
    return sorted(dated), sorted(undated)


def probe_key(s3, bucket: str, key: str, head_bytes: int) -> dict:
    """One ranged GET -> which of the five keys record 0 carries."""
    out = {"key": key, "ok": False, "keys_present": [], "keys_nonnull": [], "note": ""}
    try:
        body = s3.get_object(Bucket=bucket, Key=key,
                             Range=f"bytes=0-{max(1, head_bytes) - 1}")["Body"].read()
    except Exception as exc:  # noqa: BLE001 -- a read-only probe reports, never crashes the sweep
        out["note"] = f"GET failed: {type(exc).__name__}"
        return out
    record = _first_record(body)
    if record is None:
        out["note"] = f"no complete record in the first {head_bytes} bytes"
        return out
    out["ok"] = True
    out["keys_present"] = [k for k in NET_COMMITMENT_KEYS if k in record]
    out["keys_nonnull"] = [k for k in NET_COMMITMENT_KEYS if record.get(k) is not None]
    out["record_key_count"] = len(record)
    return out


def build_census(s3, bucket: str, *, codes: set | None, head_bytes: int,
                 max_per_vintage: int) -> dict:
    dated, undated = list_raw(s3, bucket)
    by_vintage: dict = defaultdict(list)
    for key in dated:
        code = CODE_RE.search(key)
        if codes is not None and (code is None or int(code.group(1)) not in codes):
            continue
        by_vintage[AS_OF_RE.search(key).group(1)].append(key)

    per_vintage = {}
    per_commodity_first: dict = {}
    for as_of in sorted(by_vintage):
        keys = sorted(by_vintage[as_of], key=lambda k: (int(CODE_RE.search(k).group(1)),
                                                        -int(YEAR_RE.search(k).group(1))))
        if max_per_vintage:
            keys = keys[:max_per_vintage]
        probes = [probe_key(s3, bucket, k, head_bytes) for k in keys]
        readable = [p for p in probes if p["ok"]]
        all_five = [p for p in readable if len(p["keys_present"]) == len(NET_COMMITMENT_KEYS)]
        per_key_counts = {k: sum(1 for p in readable if k in p["keys_present"])
                          for k in NET_COMMITMENT_KEYS}
        per_vintage[as_of] = {
            "objects_probed": len(probes),
            "objects_readable": len(readable),
            "objects_with_all_five": len(all_five),
            "objects_with_any": sum(1 for p in readable if p["keys_present"]),
            "per_key_present_count": per_key_counts,
            "unreadable_notes": sorted({p["note"] for p in probes if not p["ok"]}),
        }
        for probe in readable:
            code = CODE_RE.search(probe["key"]).group(1)
            if probe["keys_present"] and code not in per_commodity_first:
                per_commodity_first[code] = {
                    "first_as_of_with_any": as_of,
                    "keys": probe["keys_present"],
                }

    first_all_five = next((a for a in sorted(per_vintage)
                           if per_vintage[a]["objects_with_all_five"] > 0), None)
    first_any = next((a for a in sorted(per_vintage)
                      if per_vintage[a]["objects_with_any"] > 0), None)
    per_key_first = {}
    for field in NET_COMMITMENT_KEYS:
        per_key_first[field] = next(
            (a for a in sorted(per_vintage)
             if per_vintage[a]["per_key_present_count"].get(field, 0) > 0), None)
    return {
        "bucket": bucket,
        "raw_prefix": RAW_PREFIX,
        "head_bytes": head_bytes,
        "fields": list(NET_COMMITMENT_KEYS),
        "raw_objects_total": len(dated) + len(undated),
        "raw_objects_dated": len(dated),
        "raw_objects_undated": len(undated),
        "vintages": sorted(by_vintage),
        "per_vintage": per_vintage,
        "per_commodity_first_as_of": per_commodity_first,
        "first_as_of_with_any_field": first_any,
        "first_as_of_with_all_five": first_all_five,
        "first_as_of_per_field": per_key_first,
    }


def render(census: dict) -> str:
    buf = io.StringIO()
    print(f"ESR raw net-commitment census  bucket={census['bucket']}", file=buf)
    print(f"  raw json objects   : {census['raw_objects_total']} "
          f"(dated {census['raw_objects_dated']} / undated {census['raw_objects_undated']})",
          file=buf)
    print(f"  as_of vintages     : {len(census['vintages'])} "
          f"[{census['vintages'][0] if census['vintages'] else '-'} .. "
          f"{census['vintages'][-1] if census['vintages'] else '-'}]", file=buf)
    print("", file=buf)
    print("  as_of      probed readable all5  any   " +
          "  ".join(k[:14] for k in census["fields"]), file=buf)
    for as_of in census["vintages"]:
        row = census["per_vintage"][as_of]
        counts = "  ".join(f"{row['per_key_present_count'][k]:>14d}" for k in census["fields"])
        print(f"  {as_of}  {row['objects_probed']:>6d} {row['objects_readable']:>8d} "
              f"{row['objects_with_all_five']:>4d} {row['objects_with_any']:>4d}   {counts}",
              file=buf)
    print("", file=buf)
    print(f"  FIRST as_of carrying ANY of the five : {census['first_as_of_with_any_field']}",
          file=buf)
    print(f"  FIRST as_of carrying ALL five        : {census['first_as_of_with_all_five']}",
          file=buf)
    for field, as_of in census["first_as_of_per_field"].items():
        print(f"    {field:<26s} first seen at as_of={as_of}", file=buf)
    return buf.getvalue()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bucket", default="leviathan-dev-shahem-001")
    ap.add_argument("--aws-region", default="us-east-1", dest="aws_region")
    ap.add_argument("--codes", default=None,
                    help="comma-separated commodity_code filter (default: every code present)")
    ap.add_argument("--head-bytes", type=int, default=16384, dest="head_bytes",
                    help="bytes of each object to range-GET (default 16384)")
    ap.add_argument("--max-per-vintage", type=int, default=0, dest="max_per_vintage",
                    help="cap objects probed per as_of (default 0 = all)")
    ap.add_argument("--out", default=None,
                    help="write the census JSON here (local path or s3:// URI)")
    args = ap.parse_args(argv)

    codes = None
    if args.codes:
        codes = {int(c) for c in args.codes.split(",") if c.strip()}

    s3 = boto3.client("s3", region_name=args.aws_region)
    census = build_census(s3, args.bucket, codes=codes, head_bytes=args.head_bytes,
                          max_per_vintage=args.max_per_vintage)
    sys.stdout.write(render(census))

    if args.out:
        blob = json.dumps(census, indent=2, sort_keys=True).encode("utf-8")
        if args.out.startswith("s3://"):
            bucket, _, key = args.out[5:].partition("/")
            s3.put_object(Bucket=bucket, Key=key, Body=blob,
                          ContentType="application/json")
            print(f"  wrote {args.out}")
        else:
            import pathlib
            path = pathlib.Path(args.out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
            print(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
