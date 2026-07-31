"""FENCE 2 -- the timeline artifact must prove it is ALIVE, and prove it still describes the store
it came from. (Incident I-2, root-caused 2026-07-31.)

WHAT WENT WRONG, and what each test here would have caught:

  (a) FAIL-OPEN. ``timeline._load()`` ended in a bare ``except Exception: _CACHE = {}``, so a MISSING
      or unreadable artifact was byte-indistinguishable from "this corpus has no episodes": flag on,
      zero episodes, exit 0, nobody told. A separate lane measured exactly that live on 2026-07-31 --
      flag on, artifact absent, zero episodes, paragraph shipped anyway. Pinned by T1/T2/T3.

  (b) AGE / DRIFT. The artifact was built 2026-07-04 from 17,355 dated props. By 2026-07-31 the store
      held 30,162 (+73.8%) and NOTHING measured that. An age check alone would not have been enough:
      at a generous 30d SLA the clock leg reads "27.4d ok" on the exact incident state. Pinned by
      T5-T9, where the DRIFT leg is the one that fires on the real numbers.

Every test below fails if its fence is removed or the bug is reintroduced -- the specific reversion
that breaks it is named in each docstring. No pg, no S3, no boto3, no LLM.
"""
from __future__ import annotations

import builtins
import datetime as _dt
import json
import logging
import sys
import types

import pytest

from leviathan.graphrag import timeline as tl

# The measured incident numbers. These are not illustrative -- they are what the 2026-07-31 RCA found.
INCIDENT_STAMPED_PROPS = 17355        # what the 2026-07-04 build was derived from
INCIDENT_LIVE_PROPS = 30162           # what the store held on 2026-07-31
INCIDENT_NODES = 116

_EPISODES = {
    "drivers/frost": [
        {"start": "1994-06-10", "end": "1994-08-01", "dates": ["1994-06-10", "1994-08-01"]},
        {"start": "2021-06-01", "end": "2021-08-20",
         "dates": ["2021-06-01", "2021-07-10", "2021-08-20"]},
    ],
    "arabica_coffee": [
        {"start": "2010-03-02", "end": "2010-03-02", "dates": ["2010-03-02"]},
    ],
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts from a cold cache and an environment with NO timeline wiring at all."""
    for var in ("GRAPHRAG_TIMELINE", "GRAPHRAG_TIMELINE_PATH", "EVIDENCE_S3"):
        monkeypatch.delenv(var, raising=False)
    tl.reset_cache()
    yield
    tl.reset_cache()


def _stamp(**over) -> dict:
    """A well-formed stamp, freshly built, that check_artifact PASSES -- then perturbed per test."""
    s = {
        "built_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_table": "evidence_props",
        "gap_days": tl.GAP_DAYS,
        "n_nodes": INCIDENT_NODES,
        "n_episodes": 1462,
        "n_prop_dates": INCIDENT_STAMPED_PROPS,
        "fingerprint": "sha256:" + "0" * 64,
    }
    s.update(over)
    return s


# =============================================================================================
# LEG 1 -- the fail-open half. A dead artifact must SAY SO, and must say so ONLY when the flag is on.
# =============================================================================================

class TestLoudFailure:
    def test_t1_dead_artifact_is_loud_and_still_degrades(self, tmp_path, monkeypatch, caplog):
        """T1 -- THE INCIDENT, read path. Flag ON, artifact ABSENT.

        Three things must all hold at once: no raise (serving keeps answering), a fixed grep token
        at ERROR (a log-metric-filter can be hung off it), and a machine-readable status (an eval
        lane asserts on data, not on the absence of output).

        REVERT `except Exception: _CACHE = {}` and this FAILS on all three: no record is emitted and
        load_status() stays {"state": "unread"} -- which is exactly the state the incident lived in.
        """
        monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
        monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(tmp_path / "does-not-exist.json"))
        tl.reset_cache()

        with caplog.at_level(logging.DEBUG, logger="leviathan.graphrag.timeline"):
            got = tl.episodes_for("drivers/frost", "2026-07-31")

        assert got == []                                     # DEGRADES -- never a dead turn
        st = tl.load_status()
        assert st["state"] == "absent"
        assert st["err"] == "FileNotFoundError"
        assert st["stamp"] is None

        recs = [r for r in caplog.records if tl._TOK_DEAD in r.getMessage()]
        assert len(recs) == 1                                # emitted, and emitted ONCE
        assert recs[0].levelno == logging.ERROR
        msg = recs[0].getMessage()
        assert "state=absent" in msg
        assert "ZERO episodes" in msg
        assert "timeline --run" in msg                       # the remedy, verbatim
        assert msg.isascii()                                 # Windows console is cp1252

    def test_t1b_unreadable_is_distinguished_from_absent(self, tmp_path, monkeypatch, caplog):
        """A CORRUPT artifact and a MISSING one are both fatal but have different remedies
        (investigate vs rebuild), so the status must not collapse them into one bucket."""
        art = tmp_path / "episodes.json"
        art.write_text("{not json at all", encoding="utf-8")
        monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
        monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(art))
        tl.reset_cache()

        with caplog.at_level(logging.DEBUG, logger="leviathan.graphrag.timeline"):
            assert tl.episodes_for("drivers/frost", "2026-07-31") == []
        assert tl.load_status()["state"] == "unreadable"
        assert any(tl._TOK_DEAD in r.getMessage() for r in caplog.records)

    def test_t1c_log_is_emitted_once_not_per_call(self, tmp_path, monkeypatch, caplog):
        """The loud failure sits inside `if _CACHE is None`, so a 40-node turn logs once, not 40
        times. A per-call log would be muted within a week, which is how a fence dies."""
        monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
        monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(tmp_path / "nope.json"))
        tl.reset_cache()
        with caplog.at_level(logging.DEBUG, logger="leviathan.graphrag.timeline"):
            for _ in range(20):
                tl.episodes_for("drivers/frost", "2026-07-31")
        assert len([r for r in caplog.records if tl._TOK_DEAD in r.getMessage()]) == 1

    def test_t2_flag_off_is_byte_identical(self, tmp_path, monkeypatch, caplog):
        """T2 -- THE DEFAULT PATH IS UNTOUCHED. GRAPHRAG_TIMELINE unset.

        The layer is default-off and must stay so: the fence may not log, may not open a file, and
        may not import boto3 when the feature is off. Enforced structurally -- builtins.open and
        boto3 are booby-trapped to raise if the flag gate at timeline.py:290 is ever bypassed.

        Hoist ANY of the new behaviour above that gate and this FAILS.
        """
        monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(tmp_path / "nope.json"))
        tl.reset_cache()

        def _boom(*a, **k):                                   # pragma: no cover - must never run
            raise AssertionError("flag is OFF: the artifact must not be touched")

        fake_boto3 = types.ModuleType("boto3")
        fake_boto3.client = _boom
        monkeypatch.setattr(builtins, "open", _boom)
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        with caplog.at_level(logging.DEBUG, logger="leviathan.graphrag.timeline"):
            got = tl.episodes_for("drivers/frost", "2026-07-31")
        monkeypatch.undo()                                    # restore open() before pytest needs it

        assert got == []
        assert caplog.records == []                           # SILENT when off
        assert tl.load_status()["state"] == "unread"          # never even attempted

    def test_t3_legacy_bare_dict_still_serves_but_warns(self, tmp_path, monkeypatch, caplog):
        """T3 -- NO SERVING REGRESSION. Today's real artifact is a bare {node: [episodes]} map with
        no stamp. It must keep serving (a fence that breaks production on rollout gets reverted),
        while saying out loud that its provenance is unknowable.

        Drop the legacy branch of _unpack and this FAILS: episodes vanish.
        """
        art = tmp_path / "episodes.json"
        art.write_text(json.dumps(_EPISODES), encoding="utf-8")
        monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
        monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(art))
        tl.reset_cache()

        with caplog.at_level(logging.DEBUG, logger="leviathan.graphrag.timeline"):
            eps = tl.episodes_for("drivers/frost", "2026-07-31")

        assert [e["n"] for e in eps] == [3, 2]                # SERVES, unchanged
        st = tl.load_status()
        assert st["state"] == "legacy" and st["stamp"] is None and st["n_nodes"] == 2
        warns = [r for r in caplog.records if tl._TOK_UNSTAMPED in r.getMessage()]
        assert len(warns) == 1 and warns[0].levelno == logging.WARNING
        assert "UNKNOWABLE" in warns[0].getMessage()

    def test_t4_stamped_envelope_serves_identically_to_legacy(self, tmp_path, monkeypatch):
        """T4 -- the envelope is a WRAPPER, not a data change. Same episodes in, byte-identical
        episodes out. A schema change that quietly altered served content would be a far worse
        regression than the hole it closes."""
        legacy = tmp_path / "legacy.json"
        legacy.write_text(json.dumps(_EPISODES), encoding="utf-8")
        envelope = tmp_path / "envelope.json"
        envelope.write_text(json.dumps(
            {"schema": tl._SCHEMA, "stamp": tl.build_stamp(_EPISODES), "episodes": _EPISODES}),
            encoding="utf-8")
        monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")

        monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(legacy))
        tl.reset_cache()
        a = [tl.episodes_for(n, "2026-07-31") for n in _EPISODES]
        assert tl.load_status()["state"] == "legacy"

        monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(envelope))
        tl.reset_cache()
        b = [tl.episodes_for(n, "2026-07-31") for n in _EPISODES]
        st = tl.load_status()

        assert a == b
        assert st["state"] == "ok" and st["stamp"]["n_prop_dates"] == 6

    def test_load_status_is_a_copy_not_the_live_dict(self):
        """The status is a CONTRACT other lanes read; handing out the mutable global would let a
        caller corrupt the next reader's verdict."""
        s = tl.load_status()
        s["state"] = "tampered"
        assert tl.load_status()["state"] == "unread"


# =============================================================================================
# LEG 2 -- the fail-closed half. Does this artifact still describe the store it came from?
# =============================================================================================

class TestCheckArtifact:
    def test_t5_the_incident_content_drift_fails_closed(self):
        """T5 -- THE INCIDENT ITSELF, in its real numbers: an artifact stamped at 17,355 dated props
        against a store that now holds 30,162 (+73.80%).

        Note WHERE it is caught: the DRIFT leg, not the clock leg. built_at here is 27.4 days old and
        the SLA is a deliberately generous 30 days -- so the age leg reads "ok" and the fence STILL
        fails. That is the whole argument for making drift primary.

        Delete the drift legs and this FAILS: ok becomes True on the exact incident state.
        """
        built = _dt.datetime(2026, 7, 4, 2, 11, 7, tzinfo=_dt.timezone.utc)
        now = _dt.datetime(2026, 7, 31, 12, 0, 0, tzinfo=_dt.timezone.utc)
        res = tl.check_artifact(
            stamp=_stamp(built_at=built.strftime("%Y-%m-%dT%H:%M:%SZ")),
            state="ok",
            live_prop_dates=INCIDENT_LIVE_PROPS, live_nodes=INCIDENT_NODES,
            age_sla_days=30.0,                     # GENEROUS on purpose -- age must not be the catcher
            now=now,
        )
        assert res["ok"] is False
        by_leg = {leg["leg"]: leg for leg in res["legs"]}
        assert by_leg["age"]["ok"] is True                    # 27.4d < 30d SLA -- the clock says fine
        assert by_leg["drift:n_nodes"]["ok"] is True          # node count did NOT move
        assert by_leg["drift:n_prop_dates"]["ok"] is False    # the content did

        # The message must carry the MEASURED numbers, not a bare "stale": +73.79% is
        # (30162 - 17355) / 17355, i.e. 12,807 dated props the artifact never saw.
        blob = " ".join(res["reasons"])
        assert "drift" in blob
        assert "+73.79%" in blob
        assert str(INCIDENT_STAMPED_PROPS) in blob
        assert str(INCIDENT_LIVE_PROPS) in blob

    def test_t6_legacy_unstamped_artifact_fails(self):
        """T6 -- an artifact with no stamp is not "probably fine", it is UNKNOWABLE. Today's real
        artifact is exactly this, so the first `--check` after rollout must go red."""
        res = tl.check_artifact(stamp=None, state="legacy",
                                live_prop_dates=INCIDENT_LIVE_PROPS, live_nodes=INCIDENT_NODES)
        assert res["ok"] is False
        assert "no build stamp" in res["reasons"][0]
        assert "unknowable" in res["reasons"][0]

    def test_t6b_absent_artifact_fails_with_its_own_reason(self):
        """An artifact that could not be READ must not report the same remedy as one that is merely
        old -- "predates the stamp fence" would send the operator down the wrong path."""
        res = tl.check_artifact(stamp=None, state="absent", live_prop_dates=1, live_nodes=1)
        assert res["ok"] is False
        assert "could NOT BE READ" in res["reasons"][0]

    def test_t7_age_sla_breach_fails_when_counts_match(self):
        """T7 -- the LIVENESS backstop, isolated. Counts identical, so drift is clean; only the clock
        has moved. This is the "is anything still building this?" leg -- it is what catches the
        REBUILDER itself being dead, which is the I-1-shaped way this recurs."""
        built = _dt.datetime(2026, 7, 4, 2, 11, 7, tzinfo=_dt.timezone.utc)
        now = _dt.datetime(2026, 7, 31, 12, 0, 0, tzinfo=_dt.timezone.utc)
        res = tl.check_artifact(stamp=_stamp(built_at=built.strftime("%Y-%m-%dT%H:%M:%SZ")),
                                state="ok",
                                live_prop_dates=INCIDENT_STAMPED_PROPS, live_nodes=INCIDENT_NODES,
                                age_sla_days=10.0, now=now)
        assert res["ok"] is False
        by_leg = {leg["leg"]: leg for leg in res["legs"]}
        assert by_leg["age"]["ok"] is False
        assert "age 27" in by_leg["age"]["detail"]
        assert by_leg["drift:n_prop_dates"]["ok"] is True     # ONLY the clock breached

    def test_t7b_corrupt_built_at_fails(self):
        res = tl.check_artifact(stamp=_stamp(built_at="last tuesday"), state="ok",
                                live_prop_dates=INCIDENT_STAMPED_PROPS, live_nodes=INCIDENT_NODES)
        assert res["ok"] is False
        assert "unparseable built_at" in " ".join(res["reasons"])

    def test_t8_gap_days_mismatch_fails(self):
        """T8 -- the I-1-class fence riding along for free. If serving.timeline.gap_days is edited in
        params, the artifact's clustering silently stops matching what serving expects: newer config
        against an older artifact, which is precisely incident I-1's shape."""
        res = tl.check_artifact(stamp=_stamp(gap_days=45), state="ok",
                                live_prop_dates=INCIDENT_STAMPED_PROPS, live_nodes=INCIDENT_NODES)
        assert res["ok"] is False
        blob = " ".join(res["reasons"])
        assert "gap_days" in blob and "45" in blob and str(tl.GAP_DAYS) in blob

    def test_t9_a_healthy_artifact_passes(self):
        """T9 -- A FENCE THAT CAN ONLY FAIL IS AS USELESS AS ONE THAT CAN ONLY PASS. Fresh stamp,
        matching counts, matching gap -> green. Without this, a check hard-wired to False would look
        like coverage."""
        res = tl.check_artifact(stamp=_stamp(), state="ok",
                                live_prop_dates=INCIDENT_STAMPED_PROPS, live_nodes=INCIDENT_NODES)
        assert res["ok"] is True
        assert res["reasons"] == []
        assert all(leg["ok"] for leg in res["legs"])

    def test_drift_within_the_ceiling_passes(self):
        """The store grows continuously between rebuilds. Exact equality would fire every day and
        get muted -- muted is how a fence becomes theatre. 4% passes, 6% does not."""
        ok = tl.check_artifact(stamp=_stamp(), state="ok",
                               live_prop_dates=int(INCIDENT_STAMPED_PROPS * 1.04),
                               live_nodes=INCIDENT_NODES)
        bad = tl.check_artifact(stamp=_stamp(), state="ok",
                                live_prop_dates=int(INCIDENT_STAMPED_PROPS * 1.06),
                                live_nodes=INCIDENT_NODES)
        assert ok["ok"] is True and bad["ok"] is False

    def test_drift_catches_SHRINKAGE_too(self):
        """A store that LOST 74% of its props is at least as alarming as one that gained it -- the
        comparison is on absolute drift, not on growth."""
        res = tl.check_artifact(stamp=_stamp(n_prop_dates=INCIDENT_LIVE_PROPS), state="ok",
                                live_prop_dates=INCIDENT_STAMPED_PROPS, live_nodes=INCIDENT_NODES)
        assert res["ok"] is False
        assert "-42" in " ".join(res["reasons"])

    def test_unmeasurable_store_FAILS_rather_than_skips(self):
        """"Could not measure the store" is NOT evidence of freshness. A check that quietly passes
        when its input is missing is the exact fail-open shape this fence exists to delete."""
        res = tl.check_artifact(stamp=_stamp(), state="ok",
                                live_prop_dates=None, live_nodes=None)
        assert res["ok"] is False
        assert "could not be measured" in " ".join(res["reasons"])

    def test_check_artifact_never_raises_on_garbage(self):
        """The check returns a VERDICT; only its CLI caller turns that into rc=2. A raise here would
        make the preflight itself the outage."""
        for junk in ({}, {"built_at": None}, {"gap_days": "ninety"}, {"n_prop_dates": "many"}):
            res = tl.check_artifact(stamp=junk, state="ok", live_prop_dates=1, live_nodes=1)
            assert res["ok"] is False


# =============================================================================================
# The stamp itself -- it must be recomputable FROM THE ARTIFACT, or it is a claim rather than proof.
# =============================================================================================

class TestBuildStamp:
    def test_t10_write_artifact_round_trip_is_self_verifying(self, tmp_path, monkeypatch):
        """T10 -- ONE PutObject carries stamp AND payload (a sidecar meta.json can tear, leaving a
        stamp that describes bytes no longer there). n_prop_dates is derived FROM THE EPISODES, so a
        reader can recompute it with no pg and no S3 -- that is what makes the stamp self-verifying.

        Revert write_artifact to `json.dumps(episodes)` and this FAILS: there is no stamp to check.
        """
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        dest = tl.write_artifact(_EPISODES)
        raw = json.loads(open(dest, encoding="utf-8").read())

        assert raw["schema"] == tl._SCHEMA
        assert raw["episodes"] == _EPISODES                   # payload untouched
        s = raw["stamp"]
        assert s["n_nodes"] == 2
        assert s["n_episodes"] == 3
        assert s["n_prop_dates"] == sum(len(ep["dates"])
                                        for eps in _EPISODES.values() for ep in eps) == 6
        assert s["gap_days"] == tl.GAP_DAYS
        assert s["source_table"] == "evidence_props"
        assert s["built_at"].endswith("Z") and len(s["built_at"]) == 20

        # Recomputable from the artifact alone -> the stamp is evidence, not an assertion.
        assert tl.build_stamp(raw["episodes"])["fingerprint"] == s["fingerprint"]
        assert s["fingerprint"].startswith("sha256:")

    def test_fingerprint_moves_when_content_moves(self, tmp_path, monkeypatch):
        other = {k: v for k, v in _EPISODES.items() if k != "arabica_coffee"}
        assert tl.build_stamp(_EPISODES)["fingerprint"] != tl.build_stamp(other)["fingerprint"]

    def test_written_artifact_loads_as_ok_and_serves(self, tmp_path, monkeypatch):
        """End to end: what write_artifact emits is what _load accepts, at state "ok"."""
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        dest = tl.write_artifact(_EPISODES)
        monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
        monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", dest)
        tl.reset_cache()
        assert [e["n"] for e in tl.episodes_for("drivers/frost", "2026-07-31")] == [3, 2]
        assert tl.load_status()["state"] == "ok"

    def test_stamp_is_json_serializable(self):
        json.dumps(tl.build_stamp(_EPISODES))                  # it is written to S3; it must survive


# =============================================================================================
# The CLI -- fail-CLOSED here, where a hard stop costs nothing (unlike inside a serving turn).
# =============================================================================================

class TestCheckCli:
    def test_check_returns_rc2_on_the_incident_and_prints_the_remedy(self, tmp_path, monkeypatch, capsys):
        """`timeline --check` is the fail-closed caller. Today's real (unstamped) artifact must exit
        2, and the output must carry the one-command remedy verbatim -- a red gate with no remedy
        gets waived."""
        art = tmp_path / "episodes.json"
        art.write_text(json.dumps(_EPISODES), encoding="utf-8")     # legacy: no stamp
        monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(art))
        monkeypatch.setattr(tl, "live_counts", lambda **k: (INCIDENT_LIVE_PROPS, INCIDENT_NODES))
        monkeypatch.setattr("leviathan.common.config.load_env", lambda *a, **k: None)

        rc = tl.main(["--check"])
        out = capsys.readouterr().out

        assert rc == 2
        assert "FAIL" in out
        assert "no build stamp" in out
        assert "python -m leviathan.graphrag.timeline --run" in out
        assert out.isascii()                                   # Windows console is cp1252

    def test_check_returns_rc0_on_a_healthy_artifact(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        dest = tl.write_artifact(_EPISODES)
        monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", dest)
        monkeypatch.setattr(tl, "live_counts", lambda **k: (6, 2))
        monkeypatch.setattr("leviathan.common.config.load_env", lambda *a, **k: None)
        rc = tl.main(["--check"])
        out = capsys.readouterr().out
        assert rc == 0 and "PASS" in out

    def test_check_fails_closed_when_the_store_is_unreachable(self, tmp_path, monkeypatch, capsys):
        """pg down != artifact fine. An unmeasurable store must go red, not green."""
        monkeypatch.setenv("EVIDENCE_S3", str(tmp_path))
        dest = tl.write_artifact(_EPISODES)
        monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", dest)

        def _down(**k):
            raise RuntimeError("could not connect to server")

        monkeypatch.setattr(tl, "live_counts", _down)
        monkeypatch.setattr("leviathan.common.config.load_env", lambda *a, **k: None)
        rc = tl.main(["--check"])
        out = capsys.readouterr().out
        assert rc == 2
        assert "could not measure the prop store" in out

    def test_bare_invocation_is_still_a_dry_noop(self, capsys):
        assert tl.main([]) == 0
        assert "dry:" in capsys.readouterr().out


class TestLiveCounts:
    def test_counts_distinct_node_date_pairs(self):
        """The drift comparison must be apples-to-apples: cluster() de-duplicates dates, so the live
        side has to count DISTINCT (node, date), not raw rows. A raw count(*) would read as
        permanent drift against a correct artifact and get the fence muted."""
        seen = {}

        def fake(sql):
            seen["sql"] = " ".join(sql.split())
            return (30162, 116)

        assert tl.live_counts(query_fn=fake) == (30162, 116)
        assert "SELECT DISTINCT node, COALESCE(event_date, date)" in seen["sql"]
        assert "evidence_props" in seen["sql"]
        assert "d IS NOT NULL" in seen["sql"]
