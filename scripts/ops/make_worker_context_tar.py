#!/usr/bin/env python
"""Build the WORKER image's kaniko build-context tar.gz from the COMMITTED tree (V2-4 M5).

    python scripts/ops/make_worker_context_tar.py --out <path>.tar.gz [--ref HEAD]
                                                   [--allow-untracked] [--dry-run]
                                                   [--allow-empty-overlay]

WHY THIS EXISTS. The scratchpad ``make_context_tar.py`` that built the 2026-09-01/02 embedder
contexts tarred the WORKING TREE as-is, and the kaniko build then stamped the image with
``BUILD_GIT_COMMIT=<HEAD>``: a dirty tree (modified tracked files, ~30 untracked modules under
src/ and jobs/ on 2026-09-02) would have ridden into ``leviathan-dev-leviathan-worker`` under a
commit's name -- the 'anonymous container' class the IMAGE_MANIFEST fence exists for, and the only
content fence the in-VPC smoke carries is the configs/silver/tables fingerprint, which cannot see
it. So this script:

  1. REFUSES to run when the paths the Dockerfile COPYs (pyproject.toml, src, jobs, configs, sql,
     scripts, docker) are dirty. Tracked files are judged on CONTENT, never on ``git status``:
     ``git diff --name-status HEAD`` (the working tree, run through the clean filters) plus
     ``git diff --cached --name-status HEAD`` (staged adds / deletes / renames) -- because on this
     autocrlf Windows tree ``git status --porcelain`` prints a phantom ``M`` for files whose blobs
     are byte-identical to HEAD immediately after a commit (recorded lesson), and the runbook's
     first post-commit tar must not refuse on a line-ending ghost (STEP-12 F12). A REAL modified /
     staged / deleted / renamed tracked file is refused unconditionally: it would NOT ride (the
     tar is ``git archive``) and the operator must not believe it did. Untracked files (the ``??``
     porcelain lines -- not a content question) are refused by default too; ``--allow-untracked``
     admits them (they never ride either -- the flag only says the operator has read the list).
  2. Builds the tar from ``git archive <ref>`` -- the TRACKED tree, byte-identical to the commit
     the image is stamped with -- restricted to the COPY set.
  3. OVERLAYS the gitignored ``configs/graphrag`` subtree from the working tree (the causal DAGs,
     commodity_hierarchy.yaml, driver slices, ...) -- exactly the files ``git ls-files --others
     --ignored --exclude-standard`` reports there, minus the .dockerignore'd
     ``evidence/``, ``eval/`` and ``pilot/`` subtrees and cache/pyc noise. Tracked files under
     configs/graphrag (numbers/tables.yaml, entity_vocabulary.yaml, ...) come from the archive.
     The overlay is listed and fingerprinted (sha256 over sorted relpath+bytes) in the run's
     summary so a build can be attributed to a config vintage.
  4. REFUSES a ZERO overlay (2026-09-04, lane C verify-2 V2-NEW-2). ``git worktree add``
     checks out TRACKED files only, so a BARE worktree resolves this subtree to 0 files and
     the image bakes ZERO gitignored configs -- the estate's recorded 'worktree builds bake
     ZERO gitignored configs' incident, onto a gate 26 rendered families share, and the only
     content fence the in-VPC smoke carries is the configs/silver/tables fingerprint, which
     cannot see a missing configs/graphrag. Until this refusal the count was a printed number
     with no floor and no branch. ``--allow-empty-overlay`` admits it deliberately (a repo
     that genuinely has no gitignored graphrag subtree); nothing else does.

The tar's member layout is what ``docker/leviathan_worker/Dockerfile`` expects at the context
root: ``pyproject.toml``, ``src/``, ``jobs/``, ``configs/``, ``sql/``, ``docker/`` (+ ``scripts/``).
ASCII-only output. No AWS calls: the upload is the operator's next line.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

# The Dockerfile's COPY set (docker/leviathan_worker/Dockerfile) plus the Dockerfile's own
# directory and scripts/ (kept for parity with the embedder context; harmless if unused).
COPY_PATHS: tuple[str, ...] = ("pyproject.toml", "src", "jobs", "configs", "sql", "scripts", "docker")
# The gitignored subtree the image NEEDS (config_check / graph / hierarchy lints read it at runtime).
OVERLAY_SUBTREE = "configs/graphrag"
# .dockerignore'd subtrees under the overlay: never context (evidence/ alone is ~469 MB).
OVERLAY_EXCLUDE_PREFIXES: tuple[str, ...] = (
    "configs/graphrag/evidence/", "configs/graphrag/eval/", "configs/graphrag/pilot/",
)
EXCLUDE_PARTS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".log", ".tmp")


def _git(repo: Path, *args: str, binary: bool = False):
    out = subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def porcelain(repo: Path, paths=COPY_PATHS) -> list[str]:
    """``git status --porcelain`` lines over the COPY set (untracked included, ignored excluded)."""
    text = _git(repo, "status", "--porcelain", "--untracked-files=all", "--", *paths)
    return [line for line in text.splitlines() if line.strip()]


def split_dirty(lines: list[str]) -> tuple[list[str], list[str]]:
    """``(tracked_changes, untracked)`` from porcelain lines (``?? path`` is untracked). The
    tracked half is INFORMATIONAL only (the phantom-dirty count); :func:`content_changes` is the
    refusal oracle for tracked files."""
    untracked = [line for line in lines if line.startswith("??")]
    tracked = [line for line in lines if not line.startswith("??")]
    return tracked, untracked


def content_changes(repo: Path, paths=COPY_PATHS) -> list[str]:
    """Tracked files under the COPY set whose CONTENT differs from ``HEAD``: ``git diff
    --name-status HEAD`` over the working tree (the worktree bytes go through the clean filters,
    so an autocrlf line-ending phantom is NOT a change) unioned with ``git diff --cached
    --name-status HEAD`` (a staged add / delete / rename the worktree alone cannot show). Lines
    are ``<status>\t<path>``. ``git status --porcelain`` is deliberately NOT the oracle here."""
    out: list[str] = []
    for extra in ((), ("--cached",)):
        text = _git(repo, "diff", *extra, "--name-status", "HEAD", "--", *paths)
        for line in text.splitlines():
            line = line.strip()
            if line and line not in out:
                out.append(line)
    return out


def _keep(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in EXCLUDE_PARTS for p in parts):
        return False
    if rel.endswith(EXCLUDE_SUFFIXES):
        return False
    if any(rel.startswith(pfx) for pfx in OVERLAY_EXCLUDE_PREFIXES):
        return False
    return True


def overlay_files(repo: Path) -> list[str]:
    """The gitignored files under the overlay subtree, from the WORKING tree, filtered."""
    text = _git(repo, "ls-files", "--others", "--ignored", "--exclude-standard", "--",
                OVERLAY_SUBTREE)
    rels = [line.strip().replace("\\", "/") for line in text.splitlines() if line.strip()]
    return sorted(r for r in rels if _keep(r) and (repo / r).is_file())


def archive_members(repo: Path, ref: str) -> tuple[bytes, list[str]]:
    """``git archive <ref>`` over the COPY set -> (tar bytes, member names).

    Only the COPY paths that EXIST at ``ref`` are passed (git archive errors on a pathspec that
    matches nothing), so a tree without e.g. scripts/ still archives."""
    present = [line.strip() for line in
               _git(repo, "ls-tree", "--name-only", ref, "--", *COPY_PATHS).splitlines()
               if line.strip()]
    if not present:
        raise SystemExit(f"REFUSING: none of the COPY paths {COPY_PATHS} exist at {ref}")
    blob = _git(repo, "archive", "--format=tar", ref, "--", *present, binary=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as tf:
        names = [m.name for m in tf.getmembers() if m.isfile()]
    return blob, names


def build(repo: Path, out: Path, *, ref: str = "HEAD", allow_untracked: bool = False,
          dry_run: bool = False, allow_empty_overlay: bool = False) -> dict:
    """The whole recipe. Returns the summary dict (also printed). Raises SystemExit on a dirty
    COPY set, and on a ZERO overlay unless ``allow_empty_overlay``."""
    tracked = content_changes(repo)
    porcelain_tracked, untracked = split_dirty(porcelain(repo))
    if tracked:
        raise SystemExit(
            "REFUSING: the COPY set has modified/staged tracked files (CONTENT differs from HEAD; "
            "a git-status phantom 'M' alone never refuses) -- they would NOT ride into the image "
            "(the context is `git archive`), so the image would not be what the tree says it is. "
            "Commit or stash first:\n  " + "\n  ".join(tracked))
    phantom = len(porcelain_tracked)
    if phantom:
        print(f"note: git status shows {phantom} tracked path(s) as modified whose CONTENT equals "
              f"HEAD (autocrlf phantom-dirty; `git add --renormalize` clears it) -- ignored:")
        for line in porcelain_tracked[:20]:
            print(f"  {line}")
    if untracked and not allow_untracked:
        raise SystemExit(
            "REFUSING: the COPY set has UNTRACKED files. They never ride (git archive), but the "
            "operator must acknowledge that with --allow-untracked:\n  " + "\n  ".join(untracked))

    commit = _git(repo, "rev-parse", ref).strip()
    short = commit[:8]
    blob, tracked_members = archive_members(repo, ref)
    tracked_set = set(tracked_members)
    overlay = overlay_files(repo)
    if not overlay and not allow_empty_overlay:
        raise SystemExit(
            "REFUSING: overlay_files: 0 -- the gitignored configs/graphrag overlay resolved to "
            f"0 files under --repo {repo}. "
            "`git ls-files --others --ignored --exclude-standard -- configs/graphrag` is EMPTY "
            "there, which is exactly what a BARE `git worktree add` looks like: a checkout "
            "materialises TRACKED files only. Building from it bakes ZERO gitignored configs "
            "(141 files / 4,751,532 bytes in the main tree on 2026-09-04, 69 of them causal "
            "DAGs) into an image that goes onto a gate 26 rendered families share, and the "
            "in-VPC smoke's configs/silver/tables fingerprint cannot see the absence. COPY the "
            "gitignored subtree from the MAIN tree into --repo first, then re-run. If a zero "
            "overlay is genuinely intended, say so with --allow-empty-overlay.")
    clash = sorted(set(overlay) & tracked_set)
    if clash:
        raise SystemExit("REFUSING: overlay files collide with tracked archive members: "
                         + ", ".join(clash[:10]))

    h = hashlib.sha256()
    total = 0
    for rel in overlay:
        data = (repo / rel).read_bytes()
        h.update(rel.encode("utf-8") + b"\0" + data + b"\0")
        total += len(data)
    summary = {
        "ref": ref, "commit": commit, "out": str(out),
        "tracked_members": len(tracked_members), "overlay_files": len(overlay),
        "overlay_bytes": total, "overlay_sha256": h.hexdigest(),
        "untracked_ignored": len(untracked), "phantom_dirty_ignored": phantom,
        "dry_run": bool(dry_run),
    }
    if dry_run:
        _print_summary(summary, overlay)
        return summary

    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(out), "w:gz") as dst:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as src:
            for m in src.getmembers():
                if not m.isfile():
                    continue
                if not _keep(m.name):
                    continue
                fobj = src.extractfile(m)
                dst.addfile(m, fobj)
        for rel in overlay:
            dst.add(str(repo / rel), arcname=rel)
    summary["tar_bytes"] = out.stat().st_size
    _print_summary(summary, overlay)
    return summary


def _print_summary(summary: dict, overlay: list[str]) -> None:
    print("worker context tar")
    for k in ("ref", "commit", "out", "tracked_members", "overlay_files", "overlay_bytes",
              "overlay_sha256", "untracked_ignored", "phantom_dirty_ignored", "tar_bytes",
              "dry_run"):
        if k in summary:
            print(f"  {k:<18s}: {summary[k]}")
    if overlay:
        print("  overlay (gitignored configs/graphrag from the working tree):")
        for rel in overlay[:40]:
            print(f"    {rel}")
        if len(overlay) > 40:
            print(f"    ... {len(overlay) - 40} more")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="the .tar.gz to write")
    ap.add_argument("--ref", default="HEAD", help="the git ref to archive (default HEAD)")
    ap.add_argument("--repo", default=None, help="repo root (default: this file's repo)")
    ap.add_argument("--allow-untracked", action="store_true",
                    help="admit UNTRACKED files in the COPY set (they never ride; the flag only "
                         "records that the operator read the list)")
    ap.add_argument("--allow-empty-overlay", action="store_true",
                    help="admit a ZERO configs/graphrag overlay. Without it a 0 REFUSES: that "
                         "is the bare-worktree shape, and the image would bake no gitignored "
                         "configs at all")
    ap.add_argument("--dry-run", action="store_true", help="print the summary, write nothing")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parents[2]
    build(repo, Path(args.out), ref=args.ref, allow_untracked=args.allow_untracked,
          dry_run=args.dry_run, allow_empty_overlay=args.allow_empty_overlay)
    return 0


if __name__ == "__main__":
    sys.exit(main())
