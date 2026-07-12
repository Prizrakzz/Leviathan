#!/usr/bin/env python
"""SILVER-F060 + F061: the silver-prefix write-block + unclassified-object guard.

Enforces ``configs/silver/prefix_classification.yaml`` against an inventory of observed S3 keys:

  * a key under a live REGISTERED table root (F010 registry ``s3_prefix``) is the implicit `table`
    class -> OK.
  * a key that matches a classified prefix keeps that class; a `legacy_orphan`/`forbidden` prefix
    with ``write_block: true`` FAILS on any key NOT in that prefix's frozen inventory allowlist
    (a new write beneath a governed prefix -- the CONAB-orphan CI rule, plan L725).
  * a key under ``silver/`` that matches NEITHER a table root NOR a classified prefix is an
    UNCLASSIFIED violation (F061: every object has an unambiguous class).

Pure classification is AWS-free (:func:`classify_key`, :func:`evaluate_inventory`). The optional
``--live`` mode does a bounded read-only S3 LIST to build the inventory (INV-1: never a mutation,
never Athena). Emits reports/silver_readiness/R2R3_orphans/prefix_guard.{json,md} when ``--report``.

Usage:
    python scripts/silver/prefix_guard.py --inventory keys.txt --report
    python scripts/silver/prefix_guard.py --inventory keys.txt --strict   # exit 3 on any violation
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import yaml

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from leviathan.silver.registry import load_registry  # noqa: E402

CLASSIFICATION_PATH = _REPO / "configs" / "silver" / "prefix_classification.yaml"
OUT_DIR = _REPO / "reports" / "silver_readiness" / "R2R3_orphans"


@dataclass(frozen=True)
class KeyVerdict:
    key: str
    classification: str            # table | staging | metadata | archive | forbidden | legacy_orphan | unclassified
    matched_prefix: Optional[str]
    package: Optional[str]
    violation: Optional[str]       # None | write_block | unclassified


def load_classification(path: Optional[Path] = None) -> dict:
    path = path or CLASSIFICATION_PATH
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def table_roots(registry=None) -> dict[str, str]:
    """{s3_prefix (trailing '/'): table_name} for every registered silver table root."""
    reg = registry or load_registry()
    out: dict[str, str] = {}
    for name in reg.names():
        c = reg.table(name)
        pfx = (c.get("s3_prefix") or "").rstrip("/")
        if pfx:
            out[pfx + "/"] = name
    return out


def _frozen_allowlist(entry: dict) -> Optional[set[str]]:
    """A prefix may pin an explicit allowlist of frozen object keys (else None = block all-new)."""
    allow = entry.get("frozen_object_keys")
    return set(allow) if allow else None


def classify_key(key: str, classification: dict, roots: dict[str, str]) -> KeyVerdict:
    """Classify one S3 key against the table roots + the classification prefixes."""
    # 1. a live registered table root is the implicit `table` class.
    best_root = ""
    for root in roots:
        if key.startswith(root) and len(root) > len(best_root):
            best_root = root
    # 2. longest classified-prefix match (exact-match entries only match the whole key).
    best_entry: Optional[dict] = None
    best_len = -1
    for entry in classification.get("prefixes", []):
        pfx = entry["prefix"]
        if entry.get("match") == "exact":
            if key == pfx and len(pfx) > best_len:
                best_entry, best_len = entry, len(pfx)
        elif key.startswith(pfx) and len(pfx) > best_len:
            best_entry, best_len = entry, len(pfx)

    # A classified prefix that is MORE specific than the table root wins (e.g. a metadata run-log
    # inside a table prefix, or the CONAB legacy_orphan under silver/production/).
    if best_entry is not None and best_len >= len(best_root):
        cls = best_entry["classification"]
        pkg = best_entry.get("package")
        viol = None
        if best_entry.get("write_block"):
            allow = _frozen_allowlist(best_entry)
            if allow is None or key not in allow:
                viol = "write_block"
        return KeyVerdict(key, cls, best_entry["prefix"], pkg, viol)

    if best_root:
        return KeyVerdict(key, "table", best_root, roots[best_root], None)

    # 3. under silver/ but unclassified -> F061 violation.
    if key.startswith("silver/"):
        return KeyVerdict(key, "unclassified", None, None, "unclassified")
    return KeyVerdict(key, "out_of_scope", None, None, None)


def evaluate_inventory(keys: Iterable[str], classification: dict,
                       roots: dict[str, str]) -> list[KeyVerdict]:
    return [classify_key(k, classification, roots) for k in keys if k.strip()]


def _live_inventory(bucket: str, prefix: str = "silver/") -> list[str]:
    import boto3
    s3 = boto3.client("s3")
    keys: list[str] = []
    token = None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": 1000}
        if token:
            kw["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kw)
        keys.extend(o["Key"] for o in resp.get("Contents", []))
        if not resp.get("IsTruncated"):
            break
        token = resp["NextContinuationToken"]
    return keys


def run(keys: list[str], *, strict: bool = False, report: bool = False) -> int:
    classification = load_classification()
    roots = table_roots()
    verdicts = evaluate_inventory(keys, classification, roots)
    violations = [v for v in verdicts if v.violation]
    by_class: dict[str, int] = {}
    for v in verdicts:
        by_class[v.classification] = by_class.get(v.classification, 0) + 1

    if report:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "package": "SILVER-F060+F061",
            "keys_evaluated": len(verdicts),
            "by_classification": dict(sorted(by_class.items())),
            "violations": [v.__dict__ for v in violations],
        }
        (OUT_DIR / "prefix_guard.json").write_text(json.dumps(payload, indent=2, sort_keys=True),
                                                   encoding="utf-8")
        (OUT_DIR / "prefix_guard.md").write_text(_render_md(payload), encoding="utf-8")

    print(f"prefix_guard: {len(verdicts)} keys; classes={dict(sorted(by_class.items()))}; "
          f"violations={len(violations)}")
    for v in violations:
        print(f"  VIOLATION [{v.violation}] {v.key} (prefix={v.matched_prefix}, pkg={v.package})")
    return 3 if (strict and violations) else 0


def _render_md(payload: dict) -> str:
    lines = [
        "# SILVER-F060 + F061 -- silver prefix guard",
        "",
        f"Keys evaluated: **{payload['keys_evaluated']}**. Classes: {payload['by_classification']}. "
        f"Violations: **{len(payload['violations'])}**.",
        "",
        "A `write_block` violation is a NEW object beneath a governed `legacy_orphan`/`forbidden` "
        "prefix (the CONAB CI rule); an `unclassified` violation is an object under `silver/` that "
        "matches neither a registered table root nor a classified prefix.",
        "",
        "| key | classification | matched prefix | violation |",
        "|---|---|---|---|",
    ]
    for v in payload["violations"]:
        lines.append(f"| {v['key']} | {v['classification']} | {v['matched_prefix']} | {v['violation']} |")
    if not payload["violations"]:
        lines.append("| (none) | | | |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inventory", help="file of S3 keys (one per line) to classify")
    ap.add_argument("--live", metavar="BUCKET", help="bounded read-only S3 LIST under silver/ (INV-1)")
    ap.add_argument("--report", action="store_true", help="write the report artifacts")
    ap.add_argument("--strict", action="store_true", help="exit 3 on any violation")
    args = ap.parse_args()

    if args.inventory:
        keys = Path(args.inventory).read_text(encoding="utf-8").splitlines()
    elif args.live:
        keys = _live_inventory(args.live)
    else:
        ap.error("provide --inventory FILE or --live BUCKET")
        return 2
    return run(keys, strict=args.strict, report=args.report)


if __name__ == "__main__":
    raise SystemExit(main())
