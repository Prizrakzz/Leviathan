"""Apply the P2 W1 alias curation to ``configs/graphrag/driver_slices.yaml``.

WHY this script exists
----------------------
The E1 darkness census exposed 269 causal-DAG driver ids that ``ground()`` could not resolve to any
populated evidence slice (``drivers/<id>.jsonl`` never existed for them), so their driver legs read
zero dated text. A 5-agent Opus curation (``docs/private/p2_w1_alias_curation.json``) dispositioned
every one: 125 get an ``alias`` onto an existing topical slice (a pure serving-read remap, ZERO data
movement), 30 are ``waiver_silver_only`` (FX crosses / teleconnection indices / computed spreads whose
only honest grounding is the observed silver leg), and 112 are ``waiver_deferred`` (a real corpus gap
that needs E1b/E2 or the paid chunk pass). This CLI is the single writer that turns that machine-checked
JSON into the two YAML edits, so the curation table and the live config can never silently drift.

WHAT it edits (and what it must NOT disturb)
--------------------------------------------
``driver_slices.yaml`` has three logical regions we care about, in file order:

    drivers:      <- the slice catalogue (READ-ONLY here; every alias target must already live here)
    dag_alias:    <- ``slice_name: [dag_id, ...]`` inverse map; we EXTEND RHS lists / add slice keys
    waivers:      <- NEW third top-level key ``waivers: {id: {category, note}}`` we create/extend

The file is gitignored PRIVATE IP and carries a hand-curated provenance comment block immediately above
``dag_alias:`` (the urea->area LAW that documents why fuzzy difflib matches were rejected). PyYAML's
``safe_dump`` would drop every comment, so we do NOT round-trip the whole document. Instead we parse the
file with ``safe_load`` for VALIDATION only, then rewrite by textual splice: everything up to and
including the ``dag_alias:`` header line is preserved BYTE-FOR-BYTE (comments intact), and only the
``dag_alias:`` body + a trailing ``waivers:`` block are regenerated from the merged data. This keeps the
provenance header alive without taking a ruamel dependency the repo does not ship (PyYAML only).

Idempotence contract
---------------------
Running ``--apply`` twice yields a byte-identical file: RHS lists are de-duplicated preserving first-seen
order, existing ids are never re-appended, slice keys keep their existing file order (new keys append in
first-seen curation order), and the ``waivers:`` block is emitted with sorted keys. ``--dry-run`` prints
an ASCII summary and writes nothing.

Validation (abort-before-write)
-------------------------------
  * every ``alias`` ``target_slice`` must exist as a key under ``drivers:`` (else the id resolves to a
    slice that ``driver_specs()`` cannot describe -> hard error);
  * no id may end up owned by 2+ DISTINCT slices' RHS after the merge (cross-slice double-ownership is
    the regression the W2 lint also guards -> hard error).
Both print an ASCII diagnostic and exit non-zero WITHOUT touching the file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

# Repo-root-relative defaults so the CLI works from any cwd. This file lives at jobs/utils/, so the
# root is two parents up.
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CURATION = _ROOT / "docs" / "private" / "p2_w1_alias_curation.json"
_DEFAULT_YAML = _ROOT / "configs" / "graphrag" / "driver_slices.yaml"

# The marker line whose content we preserve verbatim and after which we regenerate the body. Matched on
# the stripped line so leading/trailing whitespace variation never breaks the splice.
_DAG_ALIAS_KEY = "dag_alias:"
_WAIVERS_KEY = "waivers:"


class ApplyError(RuntimeError):
    """Raised for validation failures that must abort the write with a non-zero exit."""


def _load_curation(path: Path) -> list[dict]:
    """Return the ``assignments`` list from the curation JSON (the authoritative disposition)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    assignments = data.get("assignments")
    if not isinstance(assignments, list):
        raise ApplyError("curation JSON has no 'assignments' list: %s" % path)
    return assignments


def _split_header(text: str) -> tuple[str, list[str]]:
    """Split the YAML text into (preserved_prefix, tail_lines).

    ``preserved_prefix`` is every line up to AND INCLUDING the ``dag_alias:`` header, joined with '\\n'
    and terminated by a single '\\n' (comments above ``dag_alias:`` survive untouched). ``tail_lines`` is
    the raw list of lines AFTER that header (the existing ``dag_alias:`` body plus any later top-level
    blocks such as a prior ``waivers:``), used only to recover the existing RHS ordering.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == _DAG_ALIAS_KEY:
            prefix = "\n".join(lines[: i + 1]) + "\n"
            return prefix, lines[i + 1 :]
    raise ApplyError("'%s' header not found in %s" % (_DAG_ALIAS_KEY, "driver_slices.yaml"))


def _existing_dag_alias(doc: dict) -> "dict[str, list[str]]":
    """Return the parsed ``dag_alias:`` mapping (slice -> [dag_id, ...]) with insertion order preserved.

    PyYAML preserves mapping insertion order (Python dicts are ordered), so this hands back the slices in
    their current file order — the ordering we replay to keep unchanged rows byte-stable.
    """
    block = doc.get("dag_alias") or {}
    out: "dict[str, list[str]]" = {}
    for slice_name, ids in block.items():
        # RHS is always a flow-style list in this file; be defensive about a bare scalar just in case.
        if ids is None:
            out[str(slice_name)] = []
        elif isinstance(ids, list):
            out[str(slice_name)] = [str(x) for x in ids]
        else:
            out[str(slice_name)] = [str(ids)]
    return out


def _merge(
    existing: "dict[str, list[str]]",
    assignments: list[dict],
    drivers: "set[str]",
) -> "tuple[dict[str, list[str]], dict[str, dict], dict]":
    """Merge alias + waiver assignments into copies of the existing structures.

    Returns ``(merged_dag_alias, waivers, stats)``. Does NOT mutate ``existing``. Raises ``ApplyError``
    on a missing alias target or on cross-slice double-ownership (validation happens here, before any
    file is touched).
    """
    # Deep-copy the existing RHS lists so we never mutate the parsed doc; preserve slice key order.
    merged: "dict[str, list[str]]" = {k: list(v) for k, v in existing.items()}
    waivers: "dict[str, dict]" = {}

    n_alias_added = 0
    n_alias_present = 0
    n_waiver_added = 0
    missing_targets: "list[tuple[str, str]]" = []

    for a in assignments:
        action = a.get("action")
        dag_id = a.get("id")
        if not dag_id:
            continue
        if action == "alias":
            target = a.get("target_slice")
            if target not in drivers:
                # Validation deferred: collect ALL misses so the operator sees the full list, not just
                # the first, before we abort.
                missing_targets.append((str(dag_id), str(target)))
                continue
            rhs = merged.setdefault(str(target), [])
            if dag_id in rhs:
                n_alias_present += 1
            else:
                rhs.append(str(dag_id))
                n_alias_added += 1
        elif action in ("waiver_silver_only", "waiver_deferred"):
            category = "silver_only" if action == "waiver_silver_only" else "deferred"
            note = _short_note(a.get("rationale") or "")
            waivers[str(dag_id)] = {"category": category, "note": note}
            n_waiver_added += 1
        else:
            raise ApplyError("unknown action %r for id %r" % (action, dag_id))

    if missing_targets:
        detail = ", ".join("%s->%s" % (i, t) for i, t in missing_targets)
        raise ApplyError(
            "%d alias target_slice(s) absent from drivers: %s" % (len(missing_targets), detail)
        )

    # Cross-slice double-ownership guard: an id may appear on exactly one slice's RHS. A RHS entry equal
    # to its own slice name (self-alias, e.g. export_ban) is benign and does not count as a second owner.
    owners: "dict[str, set[str]]" = {}
    for slice_name, ids in merged.items():
        for i in ids:
            owners.setdefault(i, set()).add(slice_name)
    dupes = {i: sorted(s) for i, s in owners.items() if len(s) > 1}
    if dupes:
        detail = "; ".join("%s on %s" % (i, "+".join(s)) for i, s in sorted(dupes.items()))
        raise ApplyError("id(s) owned by 2+ distinct slices: %s" % detail)

    stats = {
        "n_alias_added": n_alias_added,
        "n_alias_present": n_alias_present,
        "n_waiver_added": n_waiver_added,
    }
    return merged, waivers, stats


def _short_note(rationale: str) -> str:
    """Trim a curation rationale to a short single-line waiver note (first clause, <=80 chars, ASCII).

    The rationale strings are provenance for humans; the waiver ``note`` just needs to say WHY at a
    glance. Take the text before the first ';' (the lead clause), collapse whitespace, and cap length.
    Non-ASCII is stripped so the YAML stays cp1252-safe like the rest of the config.
    """
    lead = rationale.split(";", 1)[0].strip()
    lead = " ".join(lead.split())
    lead = lead.encode("ascii", "ignore").decode("ascii")
    if len(lead) > 80:
        lead = lead[:77].rstrip() + "..."
    return lead


def _fmt_rhs(ids: list[str]) -> str:
    """Format a RHS id list as a flow-style YAML sequence matching the file's convention: [a, b, c]."""
    return "[" + ", ".join(ids) + "]"


def _render(prefix: str, merged: "dict[str, list[str]]", waivers: "dict[str, dict]") -> str:
    """Render the full new file text: preserved prefix + regenerated dag_alias body + waivers block.

    The ``dag_alias:`` header itself is already the last line of ``prefix``; here we emit only its body
    (two-space-indented ``slice: [ids]`` rows in ``merged`` order) followed by a blank line and the new
    top-level ``waivers:`` mapping (sorted keys for a stable, idempotent diff).
    """
    out = [prefix]
    for slice_name, ids in merged.items():
        out.append("  %s: %s\n" % (slice_name, _fmt_rhs(ids)))
    if waivers:
        out.append("\n")
        out.append("# ── waivers: dark ids with no text slice, now ACCOUNTED (P2 W1) ──────────────────────────────\n")
        out.append("# silver_only = FX crosses / teleconnection indices / computed spreads (grounded by the observed\n")
        out.append("# silver leg, never text); deferred = a real corpus gap awaiting E1b/E2 or the paid chunk pass.\n")
        out.append("# Additive: no existing reader consults this key; the W2 darkness lint treats a waiver entry as a\n")
        out.append("# legitimate resolution so a waivered id is 'accounted' rather than 'dark'.\n")
        out.append("%s\n" % _WAIVERS_KEY)
        for wid in sorted(waivers):
            entry = waivers[wid]
            note = _yaml_scalar(entry["note"])
            out.append("  %s: {category: %s, note: %s}\n" % (wid, entry["category"], note))
    return "".join(out)


def _yaml_scalar(text: str) -> str:
    """Emit a note string as a safe double-quoted YAML scalar (escape backslash + double-quote)."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % escaped


def _summary_lines(stats: dict, n_waivers_total: int, n_slices: int) -> list[str]:
    """Build the ASCII summary block (used by both --dry-run and --apply)."""
    return [
        "apply_dag_aliases summary",
        "-------------------------",
        "aliases added        : %d" % stats["n_alias_added"],
        "aliases already present: %d" % stats["n_alias_present"],
        "waivers written      : %d" % stats["n_waiver_added"],
        "dag_alias slices     : %d" % n_slices,
        "waivers total        : %d" % n_waivers_total,
    ]


def apply(curation_path: Path, yaml_path: Path, *, write: bool) -> dict:
    """Core routine: load, validate, merge, render, and (if ``write``) persist idempotently.

    Returns a stats dict. On ``write`` the file is only rewritten when the rendered text differs from the
    current text (so a no-op re-run leaves mtime and bytes untouched — belt-and-braces idempotence).
    """
    assignments = _load_curation(curation_path)
    text = yaml_path.read_text(encoding="utf-8")
    doc = yaml.safe_load(text) or {}
    drivers = set((doc.get("drivers") or {}).keys())
    existing = _existing_dag_alias(doc)

    prefix, _tail = _split_header(text)
    merged, waivers, stats = _merge(existing, assignments, drivers)
    rendered = _render(prefix, merged, waivers)

    if write:
        if rendered != text:
            yaml_path.write_text(rendered, encoding="utf-8", newline="\n")
        stats["written"] = rendered != text
    else:
        stats["written"] = False

    stats["n_slices"] = len(merged)
    stats["n_waivers_total"] = len(waivers)
    return stats


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply P2 W1 alias/waiver curation to driver_slices.yaml (idempotent, comment-safe)."
    )
    parser.add_argument("--curation", type=Path, default=_DEFAULT_CURATION, help="curation JSON path")
    parser.add_argument("--yaml", type=Path, default=_DEFAULT_YAML, help="driver_slices.yaml path")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print summary, write nothing")
    mode.add_argument("--apply", action="store_true", help="write the merged YAML")
    args = parser.parse_args(argv)

    try:
        stats = apply(args.curation, args.yaml, write=bool(args.apply))
    except ApplyError as exc:
        # ASCII-only stderr (Windows console is cp1252).
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2

    for line in _summary_lines(stats, stats["n_waivers_total"], stats["n_slices"]):
        print(line)
    if args.dry_run:
        print("(dry-run: no file written)")
    else:
        print("(written)" if stats.get("written") else "(no change: file already up to date)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
