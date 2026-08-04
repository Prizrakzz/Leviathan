"""R7.1 -- THE FINGERPRINT-COMPARE LEG. What makes the weekly timeline rebuild safe to ENABLE.

THE LAW BEING PROTECTED: one rebuild = one full deck re-probe. Every deck "# PROBE" note asserts
something about the episodes the artifact carried when that probe ran, so when the episodes MOVE the
notes are stale and a human has to re-probe.

WHAT WOULD HAVE RETIRED IT: ``build_stamp`` embeds ``built_at``, so a naive weekly ``--run`` rewrites
the artifact's BYTES every Sunday even when the episode CONTENT is identical. Bytes-moved would stop
meaning content-moved; "every rebuild needs a re-probe" would fire 52 times a year on nothing; and a
signal that fires on nothing gets ignored. The law would die without anyone deciding to kill it --
which is precisely why infra/terraform/envs/dev/main.tf creates the R7b schedule DISABLED and names
this leg as precondition (b) for arming it.

Each test names the reversion that breaks it. No pg, no S3, no boto3, no LLM.
"""
from __future__ import annotations

import datetime as _dt
import json

import pytest

from leviathan.graphrag import timeline as tl

# Two artifacts' worth of episodes. B is A plus one node -- a real content move, not a reformat.
_EPS_A = {
    "drivers/frost": [
        {"start": "1994-06-10", "end": "1994-08-01", "dates": ["1994-06-10", "1994-08-01"]},
        {"start": "2021-06-01", "end": "2021-08-20",
         "dates": ["2021-06-01", "2021-07-10", "2021-08-20"]},
    ],
}
_EPS_B = {
    **_EPS_A,
    "drivers/black_sea_corridor": [
        {"start": "2023-07-17", "end": "2023-07-19", "dates": ["2023-07-17", "2023-07-19"]},
    ],
}

# An OLD built_at on the artifact under test, so that ANY write is byte-visible: built_at has
# second granularity, and a same-second rewrite would make the "bytes unchanged" assertion vacuous.
_OLD_BUILT = _dt.datetime(2026, 7, 4, 2, 11, 7, tzinfo=_dt.timezone.utc)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("GRAPHRAG_TIMELINE", "GRAPHRAG_TIMELINE_PATH", "EVIDENCE_S3"):
        monkeypatch.delenv(var, raising=False)
    # main() calls config.load_env(), which would otherwise pull the developer's real .env over the
    # EVIDENCE_S3 each test points at tmp_path.
    monkeypatch.setattr("leviathan.common.config.load_env", lambda *a, **k: None)
    tl.reset_cache()
    yield
    tl.reset_cache()


def _seed(tmp_path, episodes: dict) -> str:
    """Lay down a schema-2 artifact stamped in the PAST, at exactly the path _load() will read.

    EVIDENCE_S3 as a plain directory makes write_artifact and _load agree on one local file, so the
    test exercises the real read path rather than the GRAPHRAG_TIMELINE_PATH override."""
    path = tmp_path / tl._ARTIFACT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": tl._SCHEMA,
                                "stamp": tl.build_stamp(episodes, now=_OLD_BUILT),
                                "episodes": episodes}), encoding="utf-8")
    return str(path)


def _spy(monkeypatch) -> list:
    """A write-spy that still WRITES. A stub that only counted would make the changed-branch
    assertions untestable, and a counter with no delegation cannot prove the skip preserved bytes."""
    calls: list = []
    real = tl.write_artifact

    def _spied(episodes):
        calls.append(episodes)
        return real(episodes)

    monkeypatch.setattr(tl, "write_artifact", _spied)
    return calls


# =============================================================================================
# The tokens themselves. They are a MACHINE CONTRACT -- a log-metric-filter and the operator
# runbook both match on the literal string -- so they are pinned as literals, not as constants
# compared to themselves.
# =============================================================================================

def test_r7_token_strings_are_pinned():
    """A rename is a silent break: the Batch log filter and the runbook keep matching the old
    spelling and simply stop firing. Change these and this test tells you what else to change."""
    assert tl._TOK_UNCHANGED == "TIMELINE_UNCHANGED_SKIP"
    assert tl._TOK_REPROBE == "TIMELINE_REBUILT_REPROBE_REQUIRED"
    assert tl._TOK_UNCHANGED.isascii() and tl._TOK_REPROBE.isascii()
    assert tl._TOK_UNCHANGED != tl._TOK_REPROBE
    # Neither may be a substring of the other, or a filter on the shorter one matches both runs.
    assert tl._TOK_UNCHANGED not in tl._TOK_REPROBE
    assert tl._TOK_REPROBE not in tl._TOK_UNCHANGED


# =============================================================================================
# THE PREMISE. The compare is only meaningful if the fingerprint is CONTENT-ONLY.
# =============================================================================================

class TestFingerprintIsContentOnly:
    def test_r7_fingerprint_excludes_built_at(self):
        """THE LOAD-BEARING FACT. build_stamp hashes json.dumps(episodes, sort_keys=True) and nothing
        else, so two builds one month apart over identical episodes agree.

        Fold ANY non-content input into that hash -- built_at, a counter, a uuid -- and
        --run-if-changed degrades to --run: it would write every week and emit the re-probe token
        every week, which is the exact signal-death this leg exists to prevent."""
        early = tl.build_stamp(_EPS_A, now=_OLD_BUILT)
        late = tl.build_stamp(_EPS_A, now=_OLD_BUILT + _dt.timedelta(days=30, seconds=13))
        assert early["built_at"] != late["built_at"]          # the clock DID move
        assert early["fingerprint"] == late["fingerprint"]    # the content did not

    def test_r7_fingerprint_is_key_order_invariant(self):
        """sort_keys=True, so a dict-iteration reshuffle in derive() cannot forge a content change
        and trigger a re-probe nobody needed."""
        shuffled = {k: _EPS_B[k] for k in reversed(list(_EPS_B))}
        assert list(shuffled) != list(_EPS_B)
        assert tl.build_stamp(shuffled)["fingerprint"] == tl.build_stamp(_EPS_B)["fingerprint"]

    def test_r7_fingerprint_moves_on_a_real_content_change(self):
        """A fence that can only pass is not a fence."""
        assert tl.build_stamp(_EPS_A)["fingerprint"] != tl.build_stamp(_EPS_B)["fingerprint"]


# =============================================================================================
# BRANCH 1 -- UNCHANGED. The whole point: no write, no re-probe, exit 0.
# =============================================================================================

class TestUnchangedBranch:
    def test_r7_unchanged_skips_the_write_entirely(self, tmp_path, monkeypatch, capsys):
        """THE LAW, positive half. Same episodes in the store as in the artifact ->
        TIMELINE_UNCHANGED_SKIP, both fingerprints printed, rc 0, and NOT ONE BYTE written.

        Proven three ways, because one is not enough: the write-spy records zero calls (nothing
        called the writer), the file's bytes are identical (nothing wrote by another route), and the
        stamp still carries the ORIGINAL built_at (the clock did not move, so the freshness signal
        and the deck notes still describe the same artifact).

        Drop the fingerprint compare -- make --run-if-changed an alias of --run -- and all three
        fail at once."""
        art = _seed(tmp_path, _EPS_A)
        before = open(art, "rb").read()
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_A)
        calls = _spy(monkeypatch)

        rc = tl.main(["--run-if-changed"])
        out = capsys.readouterr().out

        assert rc == 0
        assert calls == []                                    # (1) the writer was never called
        assert open(art, "rb").read() == before               # (2) the bytes did not move
        assert json.loads(before)["stamp"]["built_at"] == \
            json.loads(open(art, encoding="utf-8").read())["stamp"]["built_at"]   # (3) nor the clock

        assert tl._TOK_UNCHANGED in out
        assert tl._TOK_REPROBE not in out                     # no re-probe demanded
        assert out.isascii()                                  # Windows console is cp1252

    def test_r7_unchanged_prints_BOTH_fingerprints(self, tmp_path, monkeypatch, capsys):
        """The token alone is an assertion; the two fingerprints beside it are the evidence. An
        operator reading the Sunday log must be able to see WHAT was compared, not just the verdict."""
        _seed(tmp_path, _EPS_A)
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_A)

        assert tl.main(["--run-if-changed"]) == 0
        out = capsys.readouterr().out
        fp = tl.build_stamp(_EPS_A)["fingerprint"]
        assert f"old={fp}" in out and f"new={fp}" in out
        assert fp.startswith("sha256:")
        tok = [ln for ln in out.splitlines() if tl._TOK_UNCHANGED in ln]
        assert len(tok) == 1                                  # ONE token line, greppable

    def test_r7_unchanged_does_not_print_a_pre_rebuild_report(self, tmp_path, monkeypatch, capsys):
        """Nothing is being replaced, so there is no "artifact being replaced" to report on. Printing
        the drift report anyway would put a FAIL block (this seeded stamp is 30d old) in the log of a
        run that did exactly the right thing -- the shape that trains an operator to ignore the log."""
        _seed(tmp_path, _EPS_A)
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_A)
        assert tl.main(["--run-if-changed"]) == 0
        out = capsys.readouterr().out
        assert "pre-rebuild state" not in out
        assert "FAIL" not in out

    def test_r7_unchanged_states_the_freshness_consequence(self, tmp_path, monkeypatch, capsys):
        """A skipped write does not move S3 LastModified, which is what the freshness poller reads.
        The consequence is STATED rather than left for someone to rediscover from a breaching alarm."""
        _seed(tmp_path, _EPS_A)
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_A)
        assert tl.main(["--run-if-changed"]) == 0
        assert "LastModified" in capsys.readouterr().out


# =============================================================================================
# BRANCH 2 -- CHANGED. Write, and say out loud that the deck is stale.
# =============================================================================================

class TestChangedBranch:
    def test_r7_changed_writes_and_demands_a_reprobe(self, tmp_path, monkeypatch, capsys):
        """THE LAW, negative half. The store now derives a node the artifact never carried ->
        write_artifact runs exactly once, the new artifact is the NEW content, and
        TIMELINE_REBUILT_REPROBE_REQUIRED carries the old and new fingerprints.

        Make the changed branch skip the write (invert the compare) and this fails on the payload."""
        art = _seed(tmp_path, _EPS_A)
        before = open(art, "rb").read()
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_B)
        calls = _spy(monkeypatch)

        rc = tl.main(["--run-if-changed"])
        out = capsys.readouterr().out

        assert rc == 0
        assert len(calls) == 1 and calls[0] == _EPS_B         # written ONCE, with the new content
        raw = json.loads(open(art, encoding="utf-8").read())
        assert open(art, "rb").read() != before
        assert raw["episodes"] == _EPS_B
        assert raw["stamp"]["fingerprint"] == tl.build_stamp(_EPS_B)["fingerprint"]
        assert raw["stamp"]["built_at"] != json.loads(before)["stamp"]["built_at"]

        assert tl._TOK_REPROBE in out
        assert tl._TOK_UNCHANGED not in out
        assert f"old={tl.build_stamp(_EPS_A)['fingerprint']}" in out
        assert f"new={tl.build_stamp(_EPS_B)['fingerprint']}" in out
        assert "re-probe" in out.lower()
        assert out.isascii()

    def test_r7_changed_still_reports_the_replaced_artifacts_drift(self, tmp_path, monkeypatch, capsys):
        """The --run behaviour that must survive the refactor: a rebuild says how far gone the thing
        it replaced was rather than erasing the evidence by overwriting it."""
        _seed(tmp_path, _EPS_A)
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_B)
        assert tl.main(["--run-if-changed"]) == 0
        out = capsys.readouterr().out
        assert "pre-rebuild state of the artifact being replaced" in out

    def test_r7_unstamped_artifact_is_CHANGED_not_unchanged(self, tmp_path, monkeypatch, capsys):
        """UNKNOWN IS NEVER UNCHANGED. A legacy (schema-1, bare-dict) artifact carries no fingerprint,
        so there is nothing to compare -- and "I could not compare" must fall to the side that writes
        and demands a re-probe, exactly as check_artifact treats an unmeasurable store as a FAIL.

        Coerce a missing fingerprint to "equal" and this fails: the first weekly run against today's
        real (unstamped) artifact would skip forever."""
        path = tmp_path / tl._ARTIFACT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_EPS_A), encoding="utf-8")      # legacy bare dict, no stamp
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_A)      # content IDENTICAL on purpose
        calls = _spy(monkeypatch)

        assert tl.main(["--run-if-changed"]) == 0
        out = capsys.readouterr().out
        assert len(calls) == 1                                     # it WROTE
        assert tl._TOK_REPROBE in out and tl._TOK_UNCHANGED not in out
        assert "old=none" in out

    def test_r7_absent_artifact_is_CHANGED(self, tmp_path, monkeypatch, capsys):
        """No artifact at all is the same class: unknowable, therefore write + re-probe. A first run
        into an empty prefix must produce an artifact, not a skip."""
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_B)
        calls = _spy(monkeypatch)

        assert tl.main(["--run-if-changed"]) == 0
        out = capsys.readouterr().out
        assert len(calls) == 1
        assert json.loads((tmp_path / tl._ARTIFACT).read_text(encoding="utf-8"))["episodes"] == _EPS_B
        assert tl._TOK_REPROBE in out and "old=none" in out

    def test_r7_unreadable_artifact_is_CHANGED(self, tmp_path, monkeypatch, capsys):
        """Corrupt bytes are unknowable too -- and a corrupt artifact is the one state where skipping
        would leave the layer permanently dead."""
        path = tmp_path / tl._ARTIFACT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json at all", encoding="utf-8")
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_A)
        calls = _spy(monkeypatch)

        assert tl.main(["--run-if-changed"]) == 0
        assert len(calls) == 1
        assert tl._TOK_REPROBE in capsys.readouterr().out


# =============================================================================================
# --run is UNCHANGED in behaviour, and must not learn to cry wolf.
# =============================================================================================

class TestPlainRunUnaffected:
    def test_r7_plain_run_still_always_writes(self, tmp_path, monkeypatch, capsys):
        """The hand-run mode is untouched by this leg: identical content, and it STILL rewrites. The
        operator who types --run is asking for a rebuild, not for an opinion about whether one is
        needed."""
        art = _seed(tmp_path, _EPS_A)
        before = open(art, "rb").read()
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_A)
        calls = _spy(monkeypatch)

        assert tl.main(["--run"]) == 0
        assert len(calls) == 1
        assert open(art, "rb").read() != before               # built_at moved: bytes moved
        out = capsys.readouterr().out
        assert "pre-rebuild state of the artifact being replaced" in out
        assert "derived 2 episodes across 1 slices" in out

    def test_r7_plain_run_does_NOT_emit_the_reprobe_token_on_identical_content(
            self, tmp_path, monkeypatch, capsys):
        """THE FALSE-ALARM GUARD. --run over identical episodes moves the BYTES but not the CONTENT,
        so demanding a re-probe there would be the conflation this whole leg deletes -- 52 spurious
        re-probes a year is how the law gets ignored. It says what happened instead, and names the
        mode that avoids the rewrite."""
        _seed(tmp_path, _EPS_A)
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_A)

        assert tl.main(["--run"]) == 0
        out = capsys.readouterr().out
        assert tl._TOK_REPROBE not in out
        assert tl._TOK_UNCHANGED not in out                   # nothing was skipped either
        assert "content UNCHANGED" in out and "--run-if-changed" in out

    def test_r7_plain_run_DOES_emit_the_reprobe_token_when_content_moved(
            self, tmp_path, monkeypatch, capsys):
        """One contract, both modes: the token means CONTENT MOVED, whoever asked for the rebuild."""
        _seed(tmp_path, _EPS_A)
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_B)
        assert tl.main(["--run"]) == 0
        assert tl._TOK_REPROBE in capsys.readouterr().out

    def test_r7_both_flags_degrade_toward_the_law(self, tmp_path, monkeypatch, capsys):
        """An ambiguous `--run --run-if-changed` takes the SAFER path (it can only write less), so a
        malformed scheduler override cannot silently re-arm the every-week rewrite."""
        _seed(tmp_path, _EPS_A)
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_A)
        calls = _spy(monkeypatch)
        assert tl.main(["--run", "--run-if-changed"]) == 0
        assert calls == []
        assert tl._TOK_UNCHANGED in capsys.readouterr().out


class TestCliSurface:
    def test_r7_bare_invocation_is_still_a_dry_noop_and_advertises_the_mode(self, capsys):
        """A mode nobody can discover is a mode nobody uses."""
        assert tl.main([]) == 0
        out = capsys.readouterr().out
        assert "dry:" in out and "--run-if-changed" in out
        assert out.isascii()

    def test_r7_run_if_changed_never_touches_the_check_path(self, tmp_path, monkeypatch, capsys):
        """--run-if-changed must not become a second --check: it does not measure the live store
        (live_counts hits pg) and it must not exit 2 on a stale-but-unchanged artifact. Booby-trapped
        rather than asserted on output."""
        _seed(tmp_path, _EPS_A)
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        monkeypatch.setattr(tl, "derive", lambda **k: _EPS_A)

        def _boom(**k):                                       # pragma: no cover - must never run
            raise AssertionError("--run-if-changed must not measure the store")

        monkeypatch.setattr(tl, "live_counts", _boom)
        assert tl.main(["--run-if-changed"]) == 0
        assert tl._TOK_UNCHANGED in capsys.readouterr().out
