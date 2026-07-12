"""SILVER-F011: registry-driven Athena DDL generation + structural DDL diffing.

Pure, deterministic, AWS-free. The SILVER-F010 registry
(``configs/silver/tables/<table>.yaml``, loaded by :mod:`leviathan.silver.registry`) is the
SINGLE authority for every silver/gold DDL -- this module RETIRES the first-parquet schema
inference in ``jobs/utils/generate_silver_ddls.py`` (which hard-coded ~24 tables and read a live
parquet header, and could flatten a projected table).

:func:`render_ddl` emits an idempotent ``CREATE EXTERNAL TABLE IF NOT EXISTS`` in the
``sql/athena/ddl/gold_weather_z.sql`` house style with a documented header, preserving each
table's flat / projected / registered behaviour and the Jul-2026 S3-LIST-storm safety comments:

* ``flat``       -> no ``PARTITIONED BY``; one LOCATION; no partition-enumeration surface.
* ``projected``  -> ``PARTITIONED BY`` + the ``projection.*`` / ``storage.location.template``
  TBLPROPERTIES from ``projection_domains`` (INV-3 legacy-quarantined; recovery reads S3 footers,
  never Athena).
* ``registered`` -> ``PARTITIONED BY`` with NO projection + the "do not re-project" safety note
  (the ESR/WASDE class; partitions carry explicit Glue locations, MSCK cannot repair them).

The DDL reflects the *live Glue catalog* schema: it emits ``physical_columns`` that carry a
concrete ``glue_type`` (catalog columns), in registry order, and DROPS ``glue_type: null`` columns
(physical-parquet-only "hidden schema" columns the catalog does not yet know -- an R2 add, surfaced
by the F011 drift report, never silently invented into a catalog type here).

The structural helpers (:func:`structured_from_contract`, :func:`structured_from_glue`,
:func:`parse_ddl`, :func:`diff_structured`) drive the ``R1_F011_ddl_diff`` report: they compare the
generated DDL against both the checked-in hand DDL and the R0 live-Glue baseline WITHOUT depending
on text formatting.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

__all__ = [
    "catalog_columns",
    "physical_only_columns",
    "partition_columns",
    "render_ddl",
    "Structured",
    "structured_from_contract",
    "structured_from_glue",
    "parse_ddl",
    "diff_structured",
]


# ---------------------------------------------------------------------------
# Registry -> column projections (the DDL sees the CATALOG schema only).
# ---------------------------------------------------------------------------
def catalog_columns(contract: dict) -> list[tuple[str, str]]:
    """Ordered ``(name, glue_type)`` for every non-partition column the Glue catalog carries.

    A ``physical_columns`` entry whose ``glue_type`` is ``None`` is a physical-parquet-only column
    (the writer emits it but the catalog has never registered it -- the CONAB "hidden schema"
    class). It is NOT a catalog column, has no Athena type, and is excluded from the DDL; the F011
    drift report records it as an R2 add.
    """
    return [
        (c["name"], c["glue_type"])
        for c in contract.get("physical_columns", [])
        if c.get("glue_type") is not None
    ]


def physical_only_columns(contract: dict) -> list[str]:
    """Physical-parquet-only columns (``glue_type is None``) absent from the live catalog."""
    return [
        c["name"]
        for c in contract.get("physical_columns", [])
        if c.get("glue_type") is None
    ]


def partition_columns(contract: dict) -> list[tuple[str, str]]:
    """Ordered ``(name, glue_type)`` for the Hive partition keys."""
    return [(pk["name"], pk["glue_type"]) for pk in contract.get("partition_keys", [])]


# ---------------------------------------------------------------------------
# DDL rendering (deterministic, house style).
# ---------------------------------------------------------------------------
_GENERATOR_CMD = "python scripts/silver/generate_ddls_from_registry.py --write"


def _header_lines(contract: dict) -> list[str]:
    name = contract["table_name"]
    mode = contract["partition_mode"]
    recovery = contract.get("recovery_strategy") or "(none recorded)"
    lines = [
        "-- %s - %s %s table (%s); SILVER-F011 registry-generated DDL."
        % (name, contract.get("domain", "?"), contract.get("layer", "?"),
           contract.get("lifecycle_class", "?")),
        "--",
        "-- GENERATED from the SILVER-F010 registry (configs/silver/tables/%s.yaml) by" % name,
        "-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT",
        "-- hand-edit; re-run:  %s" % _GENERATOR_CMD,
        "-- partition_mode = %s. recovery: %s" % (mode, recovery),
        "--",
    ]
    if mode == "registered":
        lines += [
            "-- REGISTERED partitions -- DO NOT re-add partition projection. The projected grid is",
            "-- the Jul-2026 S3 LIST-storm class ($134/2 days); partitions carry explicit Glue",
            "-- locations (MSCK cannot repair them). After a DROP+CREATE from this DDL, re-register:",
            "--     python jobs/utils/deproject_glue_table.py --register --tables %s" % name,
        ]
    elif mode == "projected":
        lines += [
            "-- LEGACY-QUARANTINED partition projection (INV-3): the projected grid enumerates every",
            "-- candidate partition (the Jul-2026 S3 LIST-storm class). NEVER DROP+CREATE this into a",
            "-- flat or re-projected shape; recovery reads S3 parquet footers, NEVER Athena.",
        ]
    else:
        lines += [
            "-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)",
            "-- surface; any hive-partition keys are also in-file data columns.",
        ]
    return lines


def render_ddl(contract: dict) -> str:
    """Render one deterministic ``CREATE EXTERNAL TABLE IF NOT EXISTS`` for ``contract``.

    Idempotent (``IF NOT EXISTS``) + byte-stable: calling twice on the same contract yields
    identical text. No AWS, no CWD dependence, no live-file read.
    """
    name = contract["table_name"]
    cols = catalog_columns(contract)
    if not cols:
        raise ValueError(f"{name}: no catalog columns (every physical column has glue_type=None)")
    width = max(len(n) for n, _ in cols)
    col_block = ",\n".join("    %s %s" % (n.ljust(width), t) for n, t in cols)

    body: list[str] = list(_header_lines(contract))
    body.append("CREATE EXTERNAL TABLE IF NOT EXISTS %s (" % name)
    body.append(col_block)
    body.append(")")

    pks = partition_columns(contract)
    if pks:
        body.append("PARTITIONED BY (%s)" % ", ".join("%s %s" % (n, t) for n, t in pks))

    body.append("STORED AS PARQUET")
    body.append("LOCATION '%s/'" % contract["s3_root"].rstrip("/"))

    tblprops = ["    'EXTERNAL' = 'TRUE'", "    'parquet.compression' = 'SNAPPY'"]
    if contract["partition_mode"] == "projected":
        domains = contract.get("projection_domains") or {}
        for key in sorted(domains):
            tblprops.append("    '%s' = '%s'" % (key, domains[key]))
    body.append("TBLPROPERTIES (")
    body.append(",\n".join(tblprops))
    body.append(");")

    return "\n".join(body) + "\n"


# ---------------------------------------------------------------------------
# Structural (format-independent) representation for diffing.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Structured:
    """The semantic content of a table DDL, independent of comment/whitespace formatting."""

    columns: tuple[tuple[str, str], ...] = ()          # ordered (name, athena_type)
    partition_keys: tuple[tuple[str, str], ...] = ()   # ordered (name, athena_type)
    partition_mode: str = "flat"                        # flat | projected | registered
    projection: tuple[tuple[str, str], ...] = ()        # sorted (key, value) items
    location: str = ""                                  # trailing slash normalised away
    physical_only: tuple[str, ...] = field(default=())  # registry-only info; unused for glue/hand


def _norm_loc(loc: str) -> str:
    return (loc or "").rstrip("/")


def _infer_mode(has_partition: bool, has_projection: bool) -> str:
    if has_projection:
        return "projected"
    if has_partition:
        return "registered"
    return "flat"


def structured_from_contract(contract: dict) -> Structured:
    proj = tuple(sorted((contract.get("projection_domains") or {}).items()))
    return Structured(
        columns=tuple(catalog_columns(contract)),
        partition_keys=tuple(partition_columns(contract)),
        partition_mode=contract["partition_mode"],
        projection=proj,
        location=_norm_loc(contract.get("s3_root", "")),
        physical_only=tuple(physical_only_columns(contract)),
    )


def structured_from_glue(glue: dict) -> Structured:
    """Structured form from an R0 baseline ``<table>.json`` ``glue`` block (live catalog truth)."""
    cols = tuple((c["name"], c["type"]) for c in glue.get("nonpartition_columns", []))
    pks = tuple((p["name"], p["type"]) for p in glue.get("partition_keys", []))
    proj = tuple(sorted((glue.get("projection_properties") or {}).items()))
    mode = glue.get("partition_mode") or _infer_mode(bool(pks), bool(proj))
    return Structured(
        columns=cols,
        partition_keys=pks,
        partition_mode=mode,
        projection=proj,
        location=_norm_loc(glue.get("location", "")),
    )


_CREATE_RE = re.compile(
    r"CREATE EXTERNAL TABLE(?:\s+IF NOT EXISTS)?\s+(?:\w+\.)?(\w+)\s*\(", re.IGNORECASE
)
_PARTITION_RE = re.compile(r"PARTITIONED BY\s*\((.*?)\)", re.IGNORECASE | re.DOTALL)
_LOCATION_RE = re.compile(r"LOCATION\s+'([^']+)'", re.IGNORECASE)
_PROJ_RE = re.compile(r"'((?:projection\.[^']+)|(?:storage\.location\.template))'\s*=\s*'([^']*)'")


def _split_name_type(token: str) -> Optional[tuple[str, str]]:
    """``"  col  TYPE,"`` -> ``("col", "type")``. Athena types are case-insensitive, so the type
    is lower-cased -- an uppercase hand DDL (e.g. silver_mpob's ``STRING``) is a formatting delta,
    never a semantic drift against the lower-cased registry/Glue types.
    """
    token = token.strip().rstrip(",").strip()
    if not token:
        return None
    parts = token.split()
    if len(parts) < 2:
        return None
    return parts[0], " ".join(parts[1:]).lower()


def parse_ddl(text: str) -> Structured:
    """Parse a checked-in hand DDL into its :class:`Structured` semantic content.

    Structural (no sqlglot dependency): reads the column block between the CREATE's ``(`` and the
    line that closes it, the optional ``PARTITIONED BY (...)``, the ``LOCATION``, and the
    ``projection.*`` / ``storage.location.template`` TBLPROPERTIES. Comments and alignment are
    ignored by construction.
    """
    m = _CREATE_RE.search(text)
    if not m:
        raise ValueError("no CREATE EXTERNAL TABLE statement found")
    # Column block: from the char after the matched '(' up to the line that is exactly ')'.
    start = m.end()
    tail = text[start:]
    lines = tail.splitlines()
    col_tokens: list[str] = []
    for ln in lines:
        if ln.strip() == ")":
            break
        col_tokens.append(ln)
    columns: list[tuple[str, str]] = []
    for tok in col_tokens:
        # a single physical line may hold "name type," -- one column per line in our DDLs.
        nt = _split_name_type(tok)
        if nt:
            columns.append(nt)

    pk_match = _PARTITION_RE.search(text)
    partition_keys: list[tuple[str, str]] = []
    if pk_match:
        for piece in pk_match.group(1).split(","):
            nt = _split_name_type(piece)
            if nt:
                partition_keys.append(nt)

    projection = tuple(sorted((k, v) for k, v in _PROJ_RE.findall(text)))
    loc_match = _LOCATION_RE.search(text)
    location = _norm_loc(loc_match.group(1) if loc_match else "")
    mode = _infer_mode(bool(partition_keys), bool(projection))
    return Structured(
        columns=tuple(columns),
        partition_keys=tuple(partition_keys),
        partition_mode=mode,
        projection=projection,
        location=location,
    )


def diff_structured(want: Structured, got: Structured) -> list[str]:
    """Semantic differences of ``got`` relative to ``want`` (empty == semantically identical).

    ``want`` is the authority (generated / live-Glue), ``got`` the thing being checked (hand DDL).
    Physical-only columns are NOT compared (they are registry metadata, not catalog schema).
    """
    out: list[str] = []
    if want.partition_mode != got.partition_mode:
        out.append("partition_mode: want=%s got=%s" % (want.partition_mode, got.partition_mode))
    if list(want.columns) != list(got.columns):
        wn = [n for n, _ in want.columns]
        gn = [n for n, _ in got.columns]
        if wn != gn:
            missing = [n for n in wn if n not in gn]
            extra = [n for n in gn if n not in wn]
            if missing:
                out.append("columns missing: %s" % missing)
            if extra:
                out.append("columns extra: %s" % extra)
            if not missing and not extra:
                out.append("column order differs")
        else:
            tdiff = [
                "%s(want=%s got=%s)" % (n, wt, gt)
                for (n, wt), (_, gt) in zip(want.columns, got.columns)
                if wt != gt
            ]
            if tdiff:
                out.append("column types differ: %s" % ", ".join(tdiff))
    if list(want.partition_keys) != list(got.partition_keys):
        out.append("partition_keys: want=%s got=%s"
                   % (list(want.partition_keys), list(got.partition_keys)))
    if list(want.projection) != list(got.projection):
        wk = dict(want.projection)
        gk = dict(got.projection)
        only_want = sorted(set(wk) - set(gk))
        only_got = sorted(set(gk) - set(wk))
        valdiff = sorted(k for k in set(wk) & set(gk) if wk[k] != gk[k])
        detail = []
        if only_want:
            detail.append("missing keys=%s" % only_want)
        if only_got:
            detail.append("extra keys=%s" % only_got)
        if valdiff:
            detail.append("value diffs=%s" % valdiff)
        out.append("projection: %s" % "; ".join(detail))
    if want.location != got.location:
        out.append("location: want=%s got=%s" % (want.location, got.location))
    return out
