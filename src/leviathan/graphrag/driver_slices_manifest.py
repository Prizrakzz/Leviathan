"""Tracked MIRROR of the untracked driver-slice vocabulary (EVIDENCE_INTEGRITY_WAVE_PLAN G2 / D-EI-1).

    python -m leviathan.graphrag.driver_slices_manifest --write     # regenerate after a term edit
    python -m leviathan.graphrag.driver_slices_manifest --check     # lint: exit 1 on drift

THE PROBLEM. `configs/graphrag/driver_slices.yaml` is the routing vocabulary for the whole driver layer --
109 slice specs, 68 dag_alias entries, 638 terms -- and it is invisible to review. `.gitignore:49` ignores
`configs/graphrag/` as a WHOLE DIRECTORY under the header "GraphRAG private IP", and `git log --all` for the
file is EMPTY: there is no history, no diff, no blame. A term edit re-routes populations across the layer
(class C1: the cerrado narrowing took `coffee_rust_crop` from 505 props to 20) and leaves nothing behind that
a reviewer could have seen. When the 2026-07-19/20 churn had to be attributed, the only way to rule the
config OUT was to hash three accidental copies found in old session scratchpads.

WHAT THIS IS AND IS NOT. It is a mirror, not the file. Per slice it records name, category, priority,
`max_props` and the TERM COUNT plus the sha256 of the sorted term list -- and never a term. Plus a file-level
sha256 and the spec / alias / waiver counts. That makes every term edit a reviewable diff line and a
lint-checkable invariant while disclosing not one term to a PUBLIC repo. D-EI-1 was ratified this way
explicitly: the alternative (`git add -f driver_slices.yaml`) buys a full diff at the cost of 638 private
terms, 109 slice names, 68 aliases and 142 waivers entering permanent public history.

THE PRECEDENT IS EXACT AND IN-REPO. `configs/sources/unica_biweekly_classified.json` is gitignored at
`.gitignore:38` while eleven `configs/sources/*_manifest.yaml` files are tracked. Ignored payload, tracked
manifest, same repo. This file follows it.

THE MIRROR IS TRACKED, SO IT MUST BE FORCE-ADDED. `configs/graphrag/driver_slices_manifest.yaml` is matched
by `.gitignore:49` like every other file in that directory; six files there are already tracked by exactly
this route (`params.yaml`, `eval_queries_pattern_records.yaml`, and the four `numbers/*.yaml` maps). Per-file
`git add -f` is the established in-directory precedent -- do NOT add a negation rule to .gitignore for it.

WHAT IT CANNOT SEE. The hash is over the term SET, so it detects that an edit happened -- never that two
slices claim the same prop. That is a different class with a different detector: G8's
`evidence.term_collision_warnings()`.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

MANIFEST_NAME = "driver_slices_manifest.yaml"
_OFF_ENV = "GRAPHRAG_DRIVER_MANIFEST"          # =off -> declare the mirror deliberately disabled (vacuous pass)
_VERSION = 1


def source_path():
    from leviathan.graphrag import evidence as ev
    return ev._DRIVER_PATH


def manifest_path():
    """The mirror lives BESIDE its source, derived from evidence._DRIVER_PATH rather than from ex._CFG
    directly. In production both resolve to configs/graphrag/; deriving it from the source is what makes the
    pair relocatable together, so a test (or any caller) that repoints _DRIVER_PATH at a synthetic config
    does not silently lint it against the real repo's mirror."""
    return source_path().parent / MANIFEST_NAME


def terms_sha256(terms) -> str:
    """sha256 over the SORTED, newline-joined term list, utf-8.

    Sorted so a pure re-ordering of the yaml (a curation tidy-up) is not reported as a routing change --
    `driver_matchers` builds one regex per slice and `_Matcher.__init__` sorts its own keys longest-first, so
    term ORDER is not load-bearing at runtime and must not be load-bearing here either. Newline-joined rather
    than json-dumped so the digest does not move if the yaml quoting style changes."""
    return hashlib.sha256("\n".join(sorted(str(t) for t in (terms or []))).encode("utf-8")).hexdigest()


def file_sha256() -> str | None:
    p = source_path()
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def build() -> dict:
    """The manifest document derived from the LIVE driver_slices.yaml. Pure config read, no S3, no network."""
    from leviathan.graphrag import evidence as ev
    raw = ev._driver_raw()
    specs = raw.get("drivers") or {}
    aliases = raw.get("dag_alias") or {}
    waivers = raw.get("waivers") or {}
    slices = {}
    n_terms = 0
    for name in sorted(specs):
        spec = specs[name] or {}
        terms = spec.get("terms") or []
        n_terms += len(terms)
        entry = {"category": spec.get("category"), "priority": spec.get("priority"),
                 "n_terms": len(terms), "terms_sha256": terms_sha256(terms)}
        if "max_props" in spec:                                # G5c: a declared cap is a reviewable number
            entry["max_props"] = spec.get("max_props")
        slices[name] = entry
    return {
        "manifest_version": _VERSION,
        "generated_by": "python -m leviathan.graphrag.driver_slices_manifest --write",
        "source": f"configs/graphrag/{source_path().name}",
        "file_sha256": file_sha256(),
        "counts": {"specs": len(specs), "dag_aliases": len(aliases), "waivers": len(waivers),
                   "terms": n_terms},
        "slices": slices,
    }


_HEADER = """# TRACKED MIRROR of configs/graphrag/driver_slices.yaml -- generated, do not hand-edit.
#
#   regenerate:  python -m leviathan.graphrag.driver_slices_manifest --write
#   verify:      python -m leviathan.graphrag.driver_slices_manifest --check
#
# The source file is gitignored whole-directory (.gitignore:49, "GraphRAG private IP") and has an EMPTY git
# log, so a term edit is invisible to review and re-routes populations across the driver layer with nothing
# left behind that says it happened (class C1 -- the cerrado narrowing took coffee_rust_crop 505 -> 20).
# This mirror carries per-slice metadata and the sha256 of each slice's SORTED term list -- and never a term
# -- so every edit is a reviewable diff line and a lint-time invariant, with zero vocabulary disclosed to a
# PUBLIC repo. Same shape as configs/sources/*_manifest.yaml beside their gitignored payloads.
#
# THIS FILE IS TRACKED PAST .gitignore:49 BY `git add -f`, like params.yaml and numbers/*.yaml. If it is
# missing from an image or a clean checkout, config_check's driver_slices lint FAILS by design -- "the file
# vanished" and "the mirror is off" must stay distinguishable (set GRAPHRAG_DRIVER_MANIFEST=off to declare
# it deliberately disabled).
#
# Enforced by leviathan.graphrag.evidence.check_driver_slices() leg (d), which config_check registers and
# submit_batch_evidence_maintenance chains AHEAD of every rebuild/reroute Batch job -- the only guard in the
# evidence-integrity wave that fires BEFORE any compute is spent.
"""


def render(doc: dict) -> str:
    """Deterministic YAML text for the manifest. Hand-rolled rather than yaml.safe_dump so the header
    comment survives and key order is stable across PyYAML versions (a manifest whose diff churns on
    serializer defaults is not a reviewable diff)."""
    def _scalar(v) -> str:
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        return json.dumps(str(v))                              # json string quoting is valid YAML

    lines = [_HEADER, f"manifest_version: {doc['manifest_version']}",
             f"generated_by: {_scalar(doc['generated_by'])}",
             f"source: {_scalar(doc['source'])}",
             f"file_sha256: {_scalar(doc['file_sha256'])}", "counts:"]
    for k in ("specs", "dag_aliases", "waivers", "terms"):
        lines.append(f"  {k}: {doc['counts'][k]}")
    lines.append("slices:")
    for name in sorted(doc["slices"]):
        e = doc["slices"][name]
        inner = ", ".join(f"{k}: {_scalar(e[k])}" for k in
                          ("category", "priority", "n_terms", "terms_sha256", "max_props") if k in e)
        lines.append(f"  {name}: {{{inner}}}")
    return "\n".join(lines) + "\n"


def load() -> dict | None:
    import yaml
    p = manifest_path()
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def write() -> str:
    p = manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(build()), encoding="utf-8")
    return str(p)


def check_manifest() -> list[str]:
    """Drift between the live driver_slices.yaml and its tracked mirror. [] == clean.

    Vacuous when there is no driver_slices.yaml at all (a clean checkout with no private configs -- the same
    posture check_driver_slices takes for a missing causal dir). NOT vacuous when the source exists and the
    mirror does not: that is the question_shapes lesson (F10) -- a tracked config under a gitignored
    directory goes missing on any fresh clone or image built from a clean checkout, and "the file vanished"
    read exactly like "the feature is off" until only an EXPLICIT env opt-out bought the vacuous pass."""
    if os.environ.get(_OFF_ENV, "").strip().lower() in ("off", "0", "false"):
        return []
    src = source_path()
    if not src.exists():                                       # no private vocab in this tree -> nothing to mirror
        return []
    doc = load()
    if doc is None:
        return [f"driver_slices manifest: {manifest_path()} is MISSING. It is the TRACKED mirror of the "
                f"gitignored routing vocabulary (D-EI-1) and must be `git add -f`-ed past .gitignore:49 like "
                f"params.yaml. Without it a term edit re-routes the whole driver layer with no reviewable "
                f"diff anywhere. Regenerate with `python -m leviathan.graphrag."
                f"driver_slices_manifest --write`, or set {_OFF_ENV}=off to declare the mirror deliberately "
                f"disabled."]
    live = build()
    errs: list[str] = []
    if int(doc.get("manifest_version") or 0) != _VERSION:
        errs.append(f"driver_slices manifest: manifest_version {doc.get('manifest_version')!r} != {_VERSION} "
                    f"-- regenerate with --write")
    m_slices = doc.get("slices") or {}
    l_slices = live["slices"]
    for name in sorted(set(l_slices) - set(m_slices)):
        errs.append(f"driver_slices manifest: slice {name!r} exists in the config but NOT in the mirror "
                    f"(a new slice was added without regenerating) -- run --write and review the diff")
    for name in sorted(set(m_slices) - set(l_slices)):
        errs.append(f"driver_slices manifest: slice {name!r} is in the mirror but GONE from the config "
                    f"(a slice was deleted; its S3 file is never rewritten and persists as a census retire "
                    f"orphan) -- run --write and review the diff")
    for name in sorted(set(m_slices) & set(l_slices)):
        want, got = l_slices[name], (m_slices[name] or {})
        if str(got.get("terms_sha256")) != want["terms_sha256"]:
            errs.append(f"driver_slices manifest: slice {name!r} TERM SET CHANGED "
                        f"(n_terms {got.get('n_terms')} -> {want['n_terms']}, sha256 "
                        f"{str(got.get('terms_sha256'))[:12]} -> {want['terms_sha256'][:12]}) with no "
                        f"manifest bump. A term edit re-routes populations (class C1) and stales "
                        f"timeline/episodes.json -- land it in the artifact-staling bundle, then --write")
            continue
        for field in sorted((set(want) | set(got)) - {"terms_sha256"}):
            if got.get(field) != want.get(field):             # covers an ADDED and a REMOVED max_props alike
                errs.append(f"driver_slices manifest: slice {name!r} field {field} "
                            f"{got.get(field)!r} -> {want.get(field)!r} with no manifest bump -- run --write")
    for k, v in live["counts"].items():
        if (doc.get("counts") or {}).get(k) != v:
            errs.append(f"driver_slices manifest: counts.{k} {(doc.get('counts') or {}).get(k)!r} -> {v!r} "
                        f"with no manifest bump -- run --write")
    if not errs and doc.get("file_sha256") != live["file_sha256"]:
        # Every per-slice digest matched, so no term, category, priority or cap moved: what changed is
        # comments, key order, whitespace or a block this mirror does not cover (dag_alias / waivers bodies).
        # Still a real drift -- the mirror's whole job is to be the thing a reviewer can trust.
        errs.append(f"driver_slices manifest: file_sha256 moved ({str(doc.get('file_sha256'))[:12]} -> "
                    f"{live['file_sha256'][:12]}) while every per-slice term digest matched -- a comment, "
                    f"formatting, dag_alias or waivers edit. Run --write to re-pin.")
    elif doc.get("file_sha256") != live["file_sha256"]:
        errs.append(f"driver_slices manifest: file_sha256 moved ({str(doc.get('file_sha256'))[:12]} -> "
                    f"{live['file_sha256'][:12]}) -- run --write")
    return errs


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Generate / verify the tracked driver_slices manifest mirror")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--write", action="store_true", help="regenerate the mirror from the live config")
    grp.add_argument("--check", action="store_true", help="lint: exit 1 on any drift (the Batch-chain gate)")
    args = ap.parse_args()
    if args.write:
        doc = build()
        path = write()
        print(f"driver_slices manifest -> {path}")
        print(f"  specs={doc['counts']['specs']} dag_aliases={doc['counts']['dag_aliases']} "
              f"waivers={doc['counts']['waivers']} terms={doc['counts']['terms']}")
        print(f"  file_sha256={doc['file_sha256']}")
        print("  REMINDER: this file is gitignored by .gitignore:49 -- `git add -f "
              f"configs/graphrag/{MANIFEST_NAME}` to track it (the params.yaml precedent).")
        return 0
    errs = check_manifest()
    for e in errs:
        print(f"FAIL driver_slices_manifest: {e}")
    if not errs:
        print("PASS driver_slices_manifest")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
