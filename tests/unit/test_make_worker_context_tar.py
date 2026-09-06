"""V2-4 M5 -- the worker kaniko context is built from the COMMITTED tree, never the working tree.

Hermetic: a throwaway git repository under tmp_path, no AWS, no kaniko. Every rule the script
carries has a passing case and a refusing case:

  * the tar is ``git archive HEAD`` restricted to the Dockerfile's COPY set;
  * the gitignored configs/graphrag subtree is OVERLAID from the working tree, minus the
    .dockerignore'd evidence/eval/pilot subtrees and cache noise;
  * a modified tracked file in the COPY set REFUSES the build (it would not ride);
  * an untracked file in the COPY set refuses unless the operator acknowledges it;
  * a ZERO overlay REFUSES unless --allow-empty-overlay is passed -- the bare-worktree shape,
    which bakes an image with no gitignored configs at all (lane C verify-2 V2-NEW-2);
  * the tracked-file refusal keys on CONTENT vs HEAD (``git diff``), never on ``git status``:
    an autocrlf phantom-'M' after a commit must not refuse the runbook's first tar (STEP-12 F12).
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "make_worker_context_tar", _REPO / "scripts" / "ops" / "make_worker_context_tar.py")
M = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(M)


def _git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@x")
    out = subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(repo), check=True,
                         capture_output=True, env=env)
    return out.stdout.decode("utf-8", "replace")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    (r / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (r / "src").mkdir()
    (r / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (r / "docker").mkdir()
    (r / "docker" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (r / "configs" / "graphrag" / "numbers").mkdir(parents=True)
    (r / "configs" / "graphrag" / "numbers" / "tables.yaml").write_text("t: 1\n", encoding="utf-8")
    (r / "tests").mkdir()
    (r / "tests" / "test_x.py").write_text("def test(): pass\n", encoding="utf-8")
    # the real repo's shape: configs/graphrag/ is ignored wholesale and a handful of files under
    # it are TRACKED EXCEPTIONS (force-added), e.g. numbers/tables.yaml.
    (r / ".gitignore").write_text("configs/graphrag/\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "add", "-f", "configs/graphrag/numbers/tables.yaml")
    _git(r, "commit", "-q", "-m", "init")
    # the gitignored overlay: a causal yaml (needed) + an evidence blob (never context)
    (r / "configs" / "graphrag" / "causal").mkdir(parents=True)
    (r / "configs" / "graphrag" / "causal" / "corn.yaml").write_text("c: 1\n", encoding="utf-8")
    (r / "configs" / "graphrag" / "evidence").mkdir(parents=True)
    (r / "configs" / "graphrag" / "evidence" / "big.json").write_text("{}", encoding="utf-8")
    (r / "configs" / "graphrag" / "causal" / "__pycache__").mkdir()
    (r / "configs" / "graphrag" / "causal" / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    return r


def _members(out: Path) -> list[str]:
    with tarfile.open(str(out), "r:gz") as tf:
        return sorted(m.name for m in tf.getmembers() if m.isfile())


class TestCleanTree:
    def test_the_tar_is_the_commit_plus_the_gitignored_overlay(self, repo, tmp_path):
        out = tmp_path / "ctx.tar.gz"
        summary = M.build(repo, out)
        names = _members(out)
        assert "pyproject.toml" in names and "src/a.py" in names
        assert "docker/Dockerfile" in names
        assert "configs/graphrag/numbers/tables.yaml" in names, "tracked, from the archive"
        assert "configs/graphrag/causal/corn.yaml" in names, "gitignored, from the overlay"
        assert not any(n.startswith("configs/graphrag/evidence/") for n in names)
        assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
        assert not any(n.startswith("tests/") for n in names), "tests/ is not in the COPY set"
        assert summary["overlay_files"] == 1 and summary["tracked_members"] >= 4
        assert len(summary["overlay_sha256"]) == 64
        assert summary["commit"] == _git(repo, "rev-parse", "HEAD").strip()

    def test_the_overlay_reflects_the_working_tree_not_the_commit(self, repo, tmp_path):
        (repo / "configs" / "graphrag" / "causal" / "corn.yaml").write_bytes(b"c: 2\n")
        out = tmp_path / "ctx.tar.gz"
        M.build(repo, out)
        with tarfile.open(str(out), "r:gz") as tf:
            body = tf.extractfile("configs/graphrag/causal/corn.yaml").read()
        assert body == b"c: 2\n", "the overlay carries the working tree's bytes verbatim"

    def test_a_tracked_exception_under_the_overlay_comes_from_the_archive(self, repo, tmp_path):
        # tables.yaml is tracked (force-added) -> it is an archive member, never an overlay file,
        # and editing it in the working tree is a DIRTY COPY SET, not an overlay change.
        assert M.overlay_files(repo) == ["configs/graphrag/causal/corn.yaml"]
        (repo / "configs" / "graphrag" / "numbers" / "tables.yaml").write_bytes(b"t: 2\n")
        with pytest.raises(SystemExit, match="modified/staged tracked"):
            M.build(repo, tmp_path / "ctx.tar.gz")

    def test_dry_run_writes_nothing(self, repo, tmp_path):
        out = tmp_path / "ctx.tar.gz"
        summary = M.build(repo, out, dry_run=True)
        assert summary["dry_run"] is True and not out.exists()


class TestDirtyTreeRefuses:
    def test_a_modified_tracked_file_in_the_copy_set_refuses(self, repo, tmp_path):
        (repo / "src" / "a.py").write_text("A = 2\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="modified/staged tracked"):
            M.build(repo, tmp_path / "ctx.tar.gz")
        assert not (tmp_path / "ctx.tar.gz").exists()

    def test_a_staged_file_refuses_too(self, repo, tmp_path):
        (repo / "src" / "b.py").write_text("B = 1\n", encoding="utf-8")
        _git(repo, "add", "src/b.py")
        with pytest.raises(SystemExit, match="modified/staged tracked"):
            M.build(repo, tmp_path / "ctx.tar.gz")

    def test_an_untracked_file_refuses_unless_acknowledged_and_never_rides(self, repo, tmp_path):
        (repo / "src" / "stray.py").write_text("S = 1\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="UNTRACKED"):
            M.build(repo, tmp_path / "ctx.tar.gz")
        out = tmp_path / "ctx.tar.gz"
        M.build(repo, out, allow_untracked=True)
        assert "src/stray.py" not in _members(out), "untracked files never ride (git archive)"

    def test_a_modified_file_outside_the_copy_set_is_ignored(self, repo, tmp_path):
        (repo / "tests" / "test_x.py").write_text("def test(): assert 1\n", encoding="utf-8")
        out = tmp_path / "ctx.tar.gz"
        M.build(repo, out)
        assert out.exists()


class TestContentNotPorcelain:
    """STEP-12 F12: the refusal is a CONTENT question. On this autocrlf Windows tree ``git status
    --porcelain`` prints a phantom 'M' for files byte-identical to HEAD right after a commit."""

    def test_a_phantom_porcelain_line_does_not_refuse_when_the_content_equals_head(
            self, repo, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(M, "porcelain",
                            lambda _repo, paths=M.COPY_PATHS: [" M src/a.py", " M pyproject.toml"])
        assert M.content_changes(repo) == []
        out = tmp_path / "ctx.tar.gz"
        summary = M.build(repo, out)
        assert out.exists() and summary["phantom_dirty_ignored"] == 2
        assert "phantom-dirty" in capsys.readouterr().out

    def test_a_crlf_only_difference_under_autocrlf_is_not_a_content_change(self, repo, tmp_path):
        _git(repo, "config", "core.autocrlf", "true")
        (repo / "src" / "a.py").write_bytes(b"A = 1\r\n")        # HEAD holds b"A = 1\n"
        assert M.content_changes(repo) == []
        out = tmp_path / "ctx.tar.gz"
        M.build(repo, out)
        assert out.exists()

    def test_content_changes_name_the_worktree_and_the_index(self, repo):
        (repo / "src" / "a.py").write_text("A = 2\n", encoding="utf-8")
        (repo / "src" / "b.py").write_text("B = 1\n", encoding="utf-8")
        _git(repo, "add", "src/b.py")
        (repo / "tests" / "test_x.py").write_text("def test(): assert 1\n", encoding="utf-8")
        got = M.content_changes(repo)
        assert "M\tsrc/a.py" in got and "A\tsrc/b.py" in got
        assert not any("tests/" in g for g in got), "outside the COPY set"

    def test_a_staged_deletion_with_the_file_still_on_disk_refuses(self, repo, tmp_path):
        _git(repo, "rm", "--cached", "-q", "src/a.py")
        assert any(line.startswith("D") for line in M.content_changes(repo))
        with pytest.raises(SystemExit, match="modified/staged tracked"):
            M.build(repo, tmp_path / "ctx.tar.gz")

    def test_a_clean_tree_reports_zero_phantoms(self, repo, tmp_path):
        summary = M.build(repo, tmp_path / "ctx.tar.gz", dry_run=True)
        assert summary["phantom_dirty_ignored"] == 0


class TestZeroOverlayRefuses:
    """V2-NEW-2. Before this, the overlay count was a printed number with NO floor and NO branch:
    ``build()`` returned 0 whatever it read, the only assertion anywhere was a POSITIVE one
    (``overlay_files == 1``, above), and the estate's last line of defence was a runbook sentence
    plus a grep that the sentence exists. A zero overlay is not a corner case -- it is exactly
    what ``git worktree add`` produces, because a checkout materialises TRACKED files only, and
    the image it builds goes onto a gate 26 rendered families share where the in-VPC smoke's
    only content fence (the configs/silver/tables fingerprint) cannot see a missing
    configs/graphrag.

    The fixture reaches zero the way a bare worktree does: the one gitignored overlay file is
    gone while the .dockerignore'd evidence blob and the __pycache__ noise remain, so the count
    is 0 because the KEPT set is empty, not because the subtree is.
    """

    @staticmethod
    def _empty_the_overlay(repo: Path) -> None:
        (repo / "configs" / "graphrag" / "causal" / "corn.yaml").unlink()

    def test_a_repo_with_no_gitignored_overlay_refuses_and_writes_nothing(self, repo, tmp_path):
        self._empty_the_overlay(repo)
        assert M.overlay_files(repo) == [], "the fixture is the bare-worktree shape"
        out = tmp_path / "ctx.tar.gz"
        with pytest.raises(SystemExit, match="overlay_files: 0") as exc:
            M.build(repo, out)
        message = str(exc.value)
        assert "--allow-empty-overlay" in message, (
            "a refusal must name the flag that admits it, or it is only an obstacle")
        assert "worktree" in message, "and it must name the mechanism that produced the 0"
        assert not out.exists()

    def test_a_DRY_RUN_refuses_too(self, repo, tmp_path):
        """The dry run is where an operator LOOKS at the count, so it is the last place a 0 may
        pass silently."""
        self._empty_the_overlay(repo)
        with pytest.raises(SystemExit, match="overlay_files: 0"):
            M.build(repo, tmp_path / "ctx.tar.gz", dry_run=True)

    def test_the_flag_admits_a_zero_overlay_and_the_tar_is_still_built(self, repo, tmp_path):
        self._empty_the_overlay(repo)
        out = tmp_path / "ctx.tar.gz"
        summary = M.build(repo, out, allow_empty_overlay=True)
        assert summary["overlay_files"] == 0 and out.exists()
        assert "configs/graphrag/numbers/tables.yaml" in _members(out), (
            "the TRACKED half still rides: the flag admits an empty overlay, nothing else")

    def test_a_NON_zero_overlay_never_needs_the_flag(self, repo, tmp_path):
        """The 141-file path the 2026-09-04 pink flip ran must be byte-identical to before: the
        refusal is reached only at 0."""
        out = tmp_path / "ctx.tar.gz"
        summary = M.build(repo, out)
        assert summary["overlay_files"] == 1 and out.exists()
        assert "configs/graphrag/causal/corn.yaml" in _members(out)

    def test_the_CLI_exits_NON_ZERO_on_a_zero_overlay_and_ZERO_with_the_flag(self, repo,
                                                                            tmp_path):
        """Driven as the operator drives it -- a real process, a real exit status. An in-process
        SystemExit proves the raise; only this proves the STATUS a runbook step would read."""
        self._empty_the_overlay(repo)
        script = str(_REPO / "scripts" / "ops" / "make_worker_context_tar.py")
        out = tmp_path / "cli.tar.gz"
        refused = subprocess.run(
            [sys.executable, script, "--repo", str(repo), "--out", str(out)],
            capture_output=True)
        assert refused.returncode != 0, refused.stdout.decode("utf-8", "replace")
        assert b"overlay_files: 0" in refused.stderr
        assert not out.exists()
        allowed = subprocess.run(
            [sys.executable, script, "--repo", str(repo), "--out", str(out),
             "--allow-empty-overlay"], capture_output=True)
        assert allowed.returncode == 0, allowed.stderr.decode("utf-8", "replace")
        assert out.exists()


def test_the_copy_set_matches_the_worker_dockerfile():
    """The script's COPY set must cover every path docker/leviathan_worker/Dockerfile COPYs."""
    text = (_REPO / "docker" / "leviathan_worker" / "Dockerfile").read_text(encoding="utf-8")
    copied = {line.split()[1].rstrip("/") for line in text.splitlines()
              if line.startswith("COPY ")}
    assert copied <= set(M.COPY_PATHS), copied - set(M.COPY_PATHS)
    assert M.OVERLAY_SUBTREE == "configs/graphrag"
