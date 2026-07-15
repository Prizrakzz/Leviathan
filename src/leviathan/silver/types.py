"""Pure type helpers for the silver operational registry (SILVER-F010, Milestone R1).

INV-2 doctrine (explicit writer schemas everywhere): the registry pins, for every column,
BOTH the current-physical arrow type observed in the R0 baseline AND the INV-2 *target* writer
type the widen-migration must eventually write. The rules are dictated by INV-2:

  * integer columns  -> ``int64``  (no int8/int16/int32 fragments across write eras)
  * measure columns  -> ``float64`` (no float32 fragments)
  * text columns     -> ``string``  (never ``large_string`` -- pin one arrow string type)
  * date columns     -> stay ``date32[day]`` when already a real date; string-typed date
                        columns (e.g. ``as_of_date`` stored as text) stay ISO ``string``.

These helpers are shared by the generator (which reads the R0 per-table JSON) and the loader/
tests (which read the emitted YAML), so the target math has a single authority. They are pure
functions over strings -- no AWS, no I/O, ASCII only.
"""
from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Canonical target tokens (the INV-2 writer schema vocabulary).
# ---------------------------------------------------------------------------
TARGET_INT = "int64"
TARGET_FLOAT = "float64"
TARGET_STRING = "string"
TARGET_BOOL = "bool"
TARGET_DATE = "date32[day]"
TARGET_TIMESTAMP = "timestamp[us]"

# The four drift kinds the R0 baseline flags as genuine read/write hazards. ``string_normalize``
# (large_string -> string) is applied to the target silently and is NOT a hazard (Athena reads
# both BYTE_ARRAY string types identically), so it does not enter drift_summary.
DRIFT_WIDEN_INT = "widen_int"
DRIFT_WIDEN_FLOAT = "widen_float"
DRIFT_NULL_TYPED = "null_typed"
DRIFT_GLUE_CATALOG_MISMATCH = "glue_catalog_mismatch"
DRIFT_KINDS = (
    DRIFT_WIDEN_INT,
    DRIFT_WIDEN_FLOAT,
    DRIFT_NULL_TYPED,
    DRIFT_GLUE_CATALOG_MISMATCH,
)


def _base_arrow(arrow: Optional[str]) -> str:
    """Return a normalized ``(base:width)`` family token for an arrow type string.

    e.g. ``int16`` -> ``int:16``, ``float`` -> ``float:32``, ``large_string`` -> ``string:0``,
    ``double`` -> ``float:64``, ``date32[day]`` -> ``date:32``, ``null`` -> ``null:0``.
    """
    if not arrow:
        return "null:0"
    a = arrow.strip().lower()
    if a in ("null",):
        return "null:0"
    if a.startswith("date"):
        return "date:32"
    if a.startswith("timestamp"):
        return "timestamp:0"
    if a in ("bool", "boolean"):
        return "bool:0"
    if a in ("string", "utf8", "str"):
        return "string:0"
    if a in ("large_string", "large_utf8"):
        return "string:0"
    if a.startswith("decimal"):
        return "float:64"
    if a in ("double", "float64"):
        return "float:64"
    if a in ("float", "float32", "real"):
        return "float:32"
    if a in ("halffloat", "float16"):
        return "float:16"
    for w in ("64", "32", "16", "8"):
        if a in (f"int{w}", f"uint{w}"):
            return f"int:{w}"
    if a in ("int", "integer"):
        return "int:32"
    if a in ("bigint",):
        return "int:64"
    if a in ("smallint",):
        return "int:16"
    if a in ("tinyint",):
        return "int:8"
    return a  # unknown -- pass through, treated opaquely


def _base_glue(glue: Optional[str]) -> str:
    """Return the width-aware ``(base:width)`` family token for a Glue/Athena type string.

    Width is preserved so a Glue ``int`` (int32) vs physical ``int64`` reads as a mismatch
    (the WASDE ``months_to_marketing_year_end`` C-WRONG-6 read hazard)."""
    if not glue:
        return "null:0"
    g = glue.strip().lower()
    g = g.split("(")[0]  # decimal(10,2) -> decimal
    if g in ("string", "varchar", "char"):
        return "string:0"
    if g == "double":
        return "float:64"
    if g in ("float", "real"):
        return "float:32"
    if g in ("int", "integer"):
        return "int:32"
    if g == "bigint":
        return "int:64"
    if g == "smallint":
        return "int:16"
    if g == "tinyint":
        return "int:8"
    if g in ("boolean", "bool"):
        return "bool:0"
    if g == "date":
        return "date:32"
    if g.startswith("timestamp"):
        return "timestamp:0"
    if g == "decimal":
        return "float:64"
    return g


def target_arrow_type(arrow: Optional[str], glue: Optional[str]) -> str:
    """The INV-2 target writer arrow type for a column.

    Prefers the physical arrow family; falls back to the Glue type when the physical column is
    null-typed/absent. Widens ints to int64 and floats to float64, normalizes large_string to
    string, and keeps real dates as date32[day]."""
    fam = _base_arrow(arrow)
    if fam == "null:0":
        fam = _base_glue(glue)
    base = fam.split(":", 1)[0]
    if base == "int":
        return TARGET_INT
    if base == "float":
        return TARGET_FLOAT
    if base == "string":
        return TARGET_STRING
    if base == "bool":
        return TARGET_BOOL
    if base == "date":
        return TARGET_DATE
    if base == "timestamp":
        return TARGET_TIMESTAMP
    # unknown / opaque -- keep the physical token verbatim, else the glue token.
    return (arrow or glue or "unknown").strip().lower()


def classify_drift(arrow: Optional[str], glue: Optional[str]) -> list[str]:
    """Return the ordered list of hazard drift kinds for a column (empty if none).

    Only the genuine read/write hazards the R0 baseline flags are returned:
    null-typed physical columns, Glue-vs-physical catalog mismatches, and int/float narrowing
    vs the INV-2 target. large_string->string normalization is intentionally NOT a hazard.
    """
    kinds: list[str] = []
    phys = _base_arrow(arrow)
    gfam = _base_glue(glue)
    target = target_arrow_type(arrow, glue)

    if phys == "null:0":
        kinds.append(DRIFT_NULL_TYPED)
    else:
        pbase, pwidth = phys.split(":", 1)
        # Glue catalog mismatch: the declared Glue type would misread the physical bytes.
        if gfam != "null:0":
            gbase, gwidth = gfam.split(":", 1)
            if pbase in ("int", "float", "date", "bool", "timestamp"):
                if gbase != pbase:
                    kinds.append(DRIFT_GLUE_CATALOG_MISMATCH)
                elif pbase in ("int", "float") and gwidth != pwidth:
                    kinds.append(DRIFT_GLUE_CATALOG_MISMATCH)
        # Widening vs the INV-2 target.
        if pbase == "int" and target == TARGET_INT and pwidth != "64":
            kinds.append(DRIFT_WIDEN_INT)
        elif pbase == "float" and target == TARGET_FLOAT and pwidth != "64":
            kinds.append(DRIFT_WIDEN_FLOAT)
    return kinds


# ---------------------------------------------------------------------------
# Illegal-type-change detection (loader guard: a registry edit may never narrow a column).
# ---------------------------------------------------------------------------
_TARGET_RANK = {TARGET_INT: 3, TARGET_FLOAT: 3, TARGET_STRING: 2, TARGET_BOOL: 1}


def is_narrowing_change(old_target: str, new_target: str) -> bool:
    """True when changing a column's target type from ``old`` to ``new`` is an illegal narrowing
    or an incompatible base change (int64->int32, string->int64, float64->int64, ...).

    A no-op (equal) is never a narrowing. Same-base widenings are allowed. Any change to/from a
    date/timestamp base, or between incompatible bases, is treated as illegal here (registry type
    changes must go through a reviewed migration, never a silent edit)."""
    if old_target == new_target:
        return False
    # Any base change is disallowed at the registry edit surface.
    if _norm_base(old_target) != _norm_base(new_target):
        return True
    # Same base, different width: compare bit widths -- a WIDEN (int32 -> int64) is legal, a
    # narrow is not. The old direction-blind refusal also blocked legitimate widen applies
    # (live-caught at the BF-W3 ONI T7 flag widen; B2's F036 int->bigint had to detour through
    # restore_table for the same false NARROW). Unparseable widths (date/timestamp units,
    # string variants) stay fail-closed: reviewed migration, never a silent edit.
    ow, nw = _bit_width(old_target), _bit_width(new_target)
    if ow is None or nw is None:
        return True
    return nw < ow


def _bit_width(target: str) -> Optional[int]:
    t = target.lower()
    base = _norm_base(target)
    if base not in ("int", "float"):
        return None
    digits = ""
    for ch in t.split(":", 1)[0].split("[", 1)[0][::-1]:
        if ch.isdigit():
            digits = ch + digits
        else:
            break
    return int(digits) if digits else None


def _norm_base(target: str) -> str:
    t = target.lower()
    if t.startswith("int"):
        return "int"
    if t.startswith("float") or t.startswith("double") or t.startswith("decimal"):
        return "float"
    if t.startswith("string") or t.startswith("large_string") or t.startswith("utf8"):
        return "string"
    if t.startswith("bool"):
        return "bool"
    if t.startswith("date"):
        return "date"
    if t.startswith("timestamp"):
        return "timestamp"
    return t
