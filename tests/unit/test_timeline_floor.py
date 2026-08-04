"""R3 (D-EI-8) -- THE EPISODE CORROBORATION FLOOR, its absence emitter, and the stamp knob.

WHAT THE FLOOR IS. An episode's `n` is DISTINCT PROP DATES -- `cluster()` builds each one from
`sorted({...})` over the dates, so `n` counts dated DOCUMENTS, not props (measured 1.17-2.75 props per
date across seven live driver slices). On the live artifact 2,070 of 3,735 episodes (55.4%) are
single-date, i.e. ONE dated document rendered as an "episode". `serving.timeline.min_props` (default 2)
drops those at read time, after the PIT recount and before `max_per_node`.

WHY THE EMITTER IS THE LOAD-BEARING HALF, and why half this file is about it. `answer._l2_blocks` gates
the whole episode block on `if n.episodes:`, so a node whose windows were ALL floored would inject
nothing -- no line, no trace record -- and be BYTE-IDENTICAL to a dead artifact for that node. That is
exactly the incident I-2 indistinguishability the timeline fences were built to kill, so a floor without
an emitter does not tighten the layer, it re-opens the incident. Measured at N>=2: 8 nodes go fully dark
AND 22 more fall from 4 rendered lines to 1-3 -- the partial case is 2.75x the node count, which is why
leg 2 (the suffix) is pinned here as hard as leg 1.

Each test names the reversion that breaks it. All offline: no pg, no S3, no boto3, no LLM. ASCII only
(Windows console is cp1252).
"""
from __future__ import annotations

import json

import pytest
from leviathan.graphrag import answer as an
from leviathan.graphrag import params as _pr
from leviathan.graphrag import timeline as tl

# Four windows on one node, sized like the floor's most-cited casualty: black_sea_corridor renders
# [6,5,2,1] today and [6,5,2] under the floor -- the slice behind six deck rows, and the reason leg 2
# exists at all. The 1994 window is a SINGLE dated document dressed as an episode.
_PARTIAL = {
    "drivers/black_sea": [
        {"start": "1994-06-10", "end": "1994-06-10", "dates": ["1994-06-10"]},
        {"start": "2010-08-05", "end": "2011-09-30",
         "dates": ["2010-08-05", "2010-11-02", "2011-01-15", "2011-04-20", "2011-07-01", "2011-09-30"]},
        {"start": "2022-02-24", "end": "2022-07-22",
         "dates": ["2022-02-24", "2022-03-15", "2022-04-10", "2022-06-01", "2022-07-22"]},
        {"start": "2023-07-17", "end": "2023-08-30", "dates": ["2023-07-17", "2023-08-30"]},
    ],
}

# Three windows, every one of them a single dated document: the fully-dark class (8 slices at N>=2,
# among them indian_ocean_dipole and harmattan).
_FULL = {
    "drivers/harmattan": [
        {"start": "2016-01-01", "end": "2016-01-01", "dates": ["2016-01-01"]},
        {"start": "2025-01-01", "end": "2025-01-01", "dates": ["2025-01-01"]},
        {"start": "2025-04-14", "end": "2025-04-14", "dates": ["2025-04-14"]},
    ],
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Cold cache, no timeline wiring -- the test_timeline_fence.py convention."""
    for var in ("GRAPHRAG_TIMELINE", "GRAPHRAG_TIMELINE_PATH", "EVIDENCE_S3"):
        monkeypatch.delenv(var, raising=False)
    tl.reset_cache()
    yield
    tl.reset_cache()


def _artifact(tmp_path, monkeypatch, episodes: dict, *, on: bool = True) -> None:
    """Hold a legacy (schema-1) artifact under GRAPHRAG_TIMELINE_PATH.

    SCHEMA-1 ON PURPOSE. The artifact live in production today is unstamped, the floor ships BEFORE the
    rebuild by design (D-EI-11: the floor canaries on the OLD artifact), and `episodes_for` operates
    POST-load -- so the floor must work artifact-schema-agnostically or it does not work on the only
    artifact that exists."""
    art = tmp_path / "episodes.json"
    art.write_text(json.dumps(episodes), encoding="utf-8")
    monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(art))
    if on:
        monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
    tl.reset_cache()


# =============================================================================================
# THE FLOOR -- it cuts on the PIT RECOUNT, not on what the artifact stored.
# =============================================================================================

class TestFloor:
    def test_floor_suppresses_single_date_windows(self, tmp_path, monkeypatch):
        """[6,5,2,1] -> [6,5,2]. The single-date window is 55.4% of the live artifact's episodes and
        exactly one dated document; the floor is what stops that rendering as an 'episode'.

        Delete the floor filter and this FAILS: the 1994 window comes back."""
        _artifact(tmp_path, monkeypatch, _PARTIAL)
        eps = tl.episodes_for("drivers/black_sea", "2026-07-31")
        assert [e["n"] for e in eps] == [6, 5, 2]
        assert all(e["start"] != "1994-06-10" for e in eps)

    def test_the_floor_cuts_the_PIT_RECOUNT_not_the_stored_count(self, tmp_path, monkeypatch):
        """THE REASON THE FLOOR LIVES IN episodes_for AND NOT IN derive() (R3.5). The 2022 window holds
        FIVE stored dates but only ONE is <= this as-of, so at this as-of it is a single-document window
        and must be floored. A build-time floor would have kept it on its pre-as-of count of 5 and the
        threshold would mean something different at every as-of.

        Hoist the filter into derive()/write_artifact and this FAILS: the window survives with n=1."""
        _artifact(tmp_path, monkeypatch, _PARTIAL)
        eps, meta = tl.episodes_for("drivers/black_sea", "2022-03-01", with_meta=True)
        assert [e["n"] for e in eps] == [6]                 # only the 2010-11 window still clears
        # the 1994 window (n=1 always) AND the 2022 one (5 stored dates, ONE visible here) are both
        # floored; the 2023 window has no visible date at all and never reaches the floor.
        assert meta["n_suppressed"] == 2
        # ... and the SAME window at a later as-of is not floored -- the cut is as-of dependent by design
        assert any(e["start"] == "2022-02-24"
                   for e in tl.episodes_for("drivers/black_sea", "2026-07-31"))

    def test_floor_zero_and_one_disable_it(self, tmp_path, monkeypatch):
        """A threshold whose OFF setting does not turn it off is not a knob. 0 and 1 both mean 'render
        everything': every PIT-surviving episode has n >= 1 by construction."""
        _artifact(tmp_path, monkeypatch, _PARTIAL)
        for floor in (0, 1):
            eps, meta = tl.episodes_for("drivers/black_sea", "2026-07-31",
                                        min_props=floor, with_meta=True)
            assert [e["n"] for e in eps] == [6, 5, 2, 1]
            assert meta == {"n_rendered": 4, "n_suppressed": 0, "floor": floor}
        # and a fully-dark node renders in full with the floor off -> no absence line is emitted for it
        _artifact(tmp_path, monkeypatch, _FULL)
        assert len(tl.episodes_for("drivers/harmattan", "2026-07-31", min_props=1)) == 3

    def test_a_higher_floor_takes_more(self, tmp_path, monkeypatch):
        """The knob is a knob in both directions. N>=3 was rejected on a collision, not on taste, so the
        code must still be able to express it."""
        _artifact(tmp_path, monkeypatch, _PARTIAL)
        eps, meta = tl.episodes_for("drivers/black_sea", "2026-07-31", min_props=3, with_meta=True)
        assert [e["n"] for e in eps] == [6, 5]
        assert meta["n_suppressed"] == 2

    def test_n_suppressed_counts_the_FLOOR_never_the_max_n_tail(self, tmp_path, monkeypatch):
        """The emitter's sentence says 'below the corroboration floor'. A count that quietly folded in
        the max_per_node truncation would make that sentence FALSE for a node's 5th-biggest window --
        an honesty regression dressed as a bigger number."""
        _artifact(tmp_path, monkeypatch, _PARTIAL)
        eps, meta = tl.episodes_for("drivers/black_sea", "2026-07-31", max_n=2, with_meta=True)
        assert [e["n"] for e in eps] == [6, 5]              # the n=2 window was TRUNCATED, not floored
        assert meta == {"n_rendered": 2, "n_suppressed": 1, "floor": tl.MIN_PROPS}

    def test_the_default_floor_is_the_params_knob(self):
        """The floor is `serving.timeline.min_props`, resolved the way gap_days and max_per_node are.
        The sentinel default proves the key is IN params.yaml rather than only in the code default --
        a knob that exists only as a fallback cannot be tuned without a redeploy."""
        assert _pr.get("serving.timeline.min_props", -1) == 2
        assert tl.MIN_PROPS == 2


class TestSuppressionMeta:
    def test_meta_rides_the_returned_list_and_the_list_is_still_a_list(self, tmp_path, monkeypatch):
        """The meta reaches answer.py THROUGH planner (`n.episodes = tl.episodes_for(...)`), which is why
        it rides the list rather than a second return value. Every list contract every existing caller
        relies on must therefore still hold."""
        _artifact(tmp_path, monkeypatch, _PARTIAL)
        eps = tl.episodes_for("drivers/black_sea", "2026-07-31")
        assert isinstance(eps, list) and len(eps) == 3 and bool(eps) is True
        assert json.loads(json.dumps(eps)) == list(eps)          # survives serialization
        assert tl.suppression(eps) == {"n_rendered": 3, "n_suppressed": 1, "floor": 2}
        assert tl.episodes_for("drivers/nope", "2026-07-31") == []   # equality with a plain list holds

    def test_suppression_of_a_plain_list_is_None_not_zero(self):
        """None ("nothing floored this list") and 0 ("a floor ran and took nothing") are DIFFERENT facts.
        Collapsing them would make every hand-built fixture and every future producer look like a floor
        result, and would change the trace record of turns no floor ever touched."""
        assert tl.suppression([{"start": "2021-06-01", "end": "2021-08-20", "n": 3}]) is None
        assert tl.suppression([]) is None
        assert tl.suppression(None) is None

    def test_with_meta_returns_a_pair_and_a_copy(self, tmp_path, monkeypatch):
        """The explicit opt-in path, for a caller that wants the pair rather than an attribute. The dict
        is a COPY: the meta is a contract other lanes read, and handing out the live one would let a
        caller corrupt the next reader's count (the load_status precedent)."""
        _artifact(tmp_path, monkeypatch, _FULL)
        eps, meta = tl.episodes_for("drivers/harmattan", "2026-07-31", with_meta=True)
        assert eps == [] and meta == {"n_rendered": 0, "n_suppressed": 3, "floor": 2}
        meta["n_suppressed"] = 999
        assert tl.suppression(eps)["n_suppressed"] == 3

    def test_flag_off_and_no_asof_report_zero_suppression(self, tmp_path, monkeypatch):
        """DEFAULT-OFF STAYS BYTE-IDENTICAL. With the kill-switch off (or no as-of) nothing was read and
        nothing was floored, so n_suppressed is 0 and the emitter below stays silent. A floor that
        reported phantom suppressions on the OFF arm would inject an absence line into the arm whose
        entire purpose is to be unchanged."""
        _artifact(tmp_path, monkeypatch, _FULL, on=False)
        off = tl.episodes_for("drivers/harmattan", "2026-07-31")
        assert off == [] and tl.suppression(off)["n_suppressed"] == 0
        monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
        tl.reset_cache()
        none_asof = tl.episodes_for("drivers/harmattan", None)
        assert none_asof == [] and tl.suppression(none_asof)["n_suppressed"] == 0


# =============================================================================================
# R3.1 -- THE NOUN. The threshold and the prompt must agree about what was counted.
# =============================================================================================

def test_render_line_says_report_dates_not_reports():
    """`n` is distinct prop DATES. The line used to print "(3 reports)", a different quantity -- and the
    floor is a threshold on this very number, so a wrong noun has the prompt and the threshold
    disagreeing about the unit.

    Revert the noun and this FAILS."""
    line = tl.render_line("drivers/frost", [
        {"start": "2021-06-01", "end": "2021-08-20", "n": 3, "receipt": None},
        {"start": "1994-06-10", "end": "1994-08-01", "n": 1, "receipt": None}])
    assert "(3 report dates;" in line
    assert "(1 report dates;" in line                    # invariant form: no pluralisation branch to drift
    assert "reports" not in line
    assert line.isascii()


# =============================================================================================
# R3.4 -- THE EMITTER. Without it the floor is absence HIDDEN and re-opens I-2.
# =============================================================================================

def _node(node_id: str, eps):
    from leviathan.graphrag import planner as pl
    return pl.GroundedNode(kind="driver", id=node_id, contract="arabica_coffee", depth=1,
                           relevance=0.9, episodes=eps)


def _blocks(monkeypatch, node):
    from leviathan.graphrag import planner as pl
    monkeypatch.setattr(an, "_context_block", lambda g, c: f"CTX {c}")
    sg = pl.Subgraph(seeds=["arabica_coffee"], nodes=[node])
    _stable, volatile = an._l2_blocks(sg, None, "2026-07-31")
    return sg, "\n".join(volatile)


class TestEmitterLeg2Partial:
    def test_partial_suppression_appends_the_suffix_to_the_EXISTING_block(self, tmp_path, monkeypatch):
        """LEG 2, the larger half (22 nodes at N>=2 versus 8 fully dark). The block already renders, so
        the suppression fact is a string append at the SAME seam -- no new gate, no new paragraph, no
        second LINE_PREFIX line.

        Drop the suffix and this FAILS: [6,5,2,1] -> [6,5,2] is silent, and the reader cannot tell
        'this node has 3 windows' from 'its 4th was thin'."""
        _artifact(tmp_path, monkeypatch, _PARTIAL)
        eps = tl.episodes_for("drivers/black_sea", "2026-07-31")
        sg, vp = _blocks(monkeypatch, _node("drivers/black_sea", eps))

        assert vp.count(tl.LINE_PREFIX) == 1                     # ONE line, not two
        assert "1 further window(s) below the corroboration floor of 2 report dates" in vp
        assert "2010-08..2011-09" in vp and "1994-06" not in vp  # the kept windows, and not the floored one
        assert vp.isascii()

    def test_the_partial_trace_record_carries_the_pair_and_the_line_the_model_saw(self, tmp_path,
                                                                                  monkeypatch):
        """R3.4 leg 3. An eval must be able to assert on {rendered, suppressed} rather than infer
        suppression from a line count that has two causes -- a thin node and a floored one render the
        same number of lines. And `line` must be the string INCLUDING the suffix: the record's whole job
        is to be what the model was shown."""
        _artifact(tmp_path, monkeypatch, _PARTIAL)
        eps = tl.episodes_for("drivers/black_sea", "2026-07-31")
        sg, vp = _blocks(monkeypatch, _node("drivers/black_sea", eps))

        rec, = sg.trace["episodes_injected"]
        assert rec["n_rendered"] == 3 and rec["n_suppressed"] == 1 and rec["floor"] == 2
        # R6 fold: the suffix's imperative is scoped to the HIDDEN windows and re-affirms the shown
        # ones -- the old "do not enumerate or narrate them" tail read as a section-level ban and
        # cost five deck rows their '## Episodes' section (adjudication record, 2026-08-04).
        assert rec["line"] in vp and rec["line"].endswith(
            "still render every window shown on this line as its own bullet")
        assert "never name or count those hidden windows" in rec["line"]
        assert "floored" not in rec                              # partial is NOT the fully-dark case
        assert rec["spans"] == ["2010-08..2011-09", "2022-02..2022-07", "2023-07..2023-08"]
        assert [w["n"] for w in rec["windows"]] == [6, 5, 2]

    def test_no_suppression_means_no_suffix(self, tmp_path, monkeypatch):
        """A node the floor did not touch must render EXACTLY as it did pre-R3. A suffix that appeared
        with a zero in it would be noise on 117 of 125 slices."""
        _artifact(tmp_path, monkeypatch, _PARTIAL)
        eps = tl.episodes_for("drivers/black_sea", "2026-07-31", min_props=1)
        sg, vp = _blocks(monkeypatch, _node("drivers/black_sea", eps))
        assert "corroboration floor" not in vp
        assert tl.render_line("drivers/black_sea", eps) in vp
        rec, = sg.trace["episodes_injected"]
        assert rec["n_suppressed"] == 0 and rec["n_rendered"] == 4


class TestEmitterLeg1Full:
    def test_fully_floored_node_emits_a_LINE_PREFIX_absence_line(self, tmp_path, monkeypatch):
        """LEG 1, THE I-2 LEG. `if n.episodes:` alone injects NOTHING for a fully floored node, making it
        byte-identical to a dead artifact for that node. The line must carry tl.LINE_PREFIX so the
        '## Episodes' persona gate (which tests that constant in the ASSEMBLED VOLATILE PROMPT) still
        fires and the reader is told the windows were THIN rather than absent.

        Delete the elif branch and this FAILS on every assertion: the node vanishes silently."""
        _artifact(tmp_path, monkeypatch, _FULL)
        eps = tl.episodes_for("drivers/harmattan", "2026-07-31")
        assert eps == []                                          # nothing survives the floor ...
        sg, vp = _blocks(monkeypatch, _node("drivers/harmattan", eps))

        assert tl.LINE_PREFIX in vp                               # ... and yet the node SPEAKS
        assert an._episodes_on(vp) is True                        # the persona gate still fires
        assert "3 of them" in vp and "corroboration floor of 2 report dates" in vp
        assert "thin and uncorroborated" in vp
        assert "write no bullet for it" in vp                     # it carries no window to enumerate
        assert vp.isascii()

    def test_the_floored_trace_record_is_marked_and_carries_the_pair(self, tmp_path, monkeypatch):
        """A floored node and a node that never had any window both carry zero spans. `floored` is the
        only thing that separates them, so eval can tell 'suppressed' from 'never had any' instead of
        reading a deck's min_episode_lines drop as a corpus fact."""
        _artifact(tmp_path, monkeypatch, _FULL)
        eps = tl.episodes_for("drivers/harmattan", "2026-07-31")
        sg, vp = _blocks(monkeypatch, _node("drivers/harmattan", eps))

        rec, = sg.trace["episodes_injected"]
        assert rec["floored"] is True
        assert rec["n_rendered"] == 0 and rec["n_suppressed"] == 3 and rec["floor"] == 2
        assert rec["spans"] == [] and rec["windows"] == []        # present-and-empty, never missing
        assert rec["line"] in vp and rec["node"] == "drivers/harmattan"

    def test_the_floored_record_is_inert_for_every_existing_consumer(self, tmp_path, monkeypatch):
        """The new record shape rides the EXISTING trace plumbing, so it must be a no-op for the readers
        that were there first rather than a new crash surface: eval._injected_episodes yields no window
        from it (it enumerated none), and eval._judge_episodes_panel shows the judge the honest line."""
        from leviathan.graphrag import eval as ev
        _artifact(tmp_path, monkeypatch, _FULL)
        eps = tl.episodes_for("drivers/harmattan", "2026-07-31")
        sg, _vp = _blocks(monkeypatch, _node("drivers/harmattan", eps))
        out = {"trace": dict(sg.trace)}

        assert ev._injected_episodes(out) == []                   # no window was shown, so none is gradeable
        panel = ev._judge_episodes_panel(out)
        assert tl.LINE_PREFIX in panel and "corroboration floor" in panel

    def test_a_node_that_never_had_a_window_still_emits_NOTHING(self, tmp_path, monkeypatch):
        """THE FALSE-POSITIVE GUARD, and the reason `n_suppressed` gates the branch rather than the mere
        presence of meta. Absence-stated is only honest when there was something to suppress: an
        unbacked node, a dead artifact and the OFF arm must all stay silent, or the emitter becomes the
        confabulation surface it was added to close."""
        _artifact(tmp_path, monkeypatch, _FULL)
        empty = tl.episodes_for("drivers/no-such-node", "2026-07-31")     # artifact alive, node absent
        assert tl.suppression(empty) == {"n_rendered": 0, "n_suppressed": 0, "floor": 2}
        sg, vp = _blocks(monkeypatch, _node("drivers/no-such-node", empty))
        assert tl.LINE_PREFIX not in vp
        assert "episodes_injected" not in sg.trace
        assert an._episodes_on(vp) is False

        sg2, vp2 = _blocks(monkeypatch, _node("drivers/plain", []))       # a plain [] (no meta at all)
        assert tl.LINE_PREFIX not in vp2 and "episodes_injected" not in sg2.trace


# =============================================================================================
# LEG 1's PERSONA HALF -- the '## Episodes' directive must know about a line with NO window.
#
# Leg 1 makes the persona gate fire on a turn that carries ZERO enumerable windows: floored_line
# carries LINE_PREFIX by design (that IS the I-2 fix -- a floored node speaks rather than vanishes),
# so `_SYSTEM_EPISODES` ships beside a line whose own text says "write no bullet for it". Until the
# persona said the same thing, the model was told BOTH to enumerate every injected episode and to
# write nothing, in one system prompt. Both resolutions of that contradiction are defects: an empty
# '## Episodes' heading (zero lines -> min_episode_lines and episode_magnitude_or_absence red on a
# turn that behaved correctly) or a bullet minted from a bare count -- the +10-hallucination mode.
# =============================================================================================

class TestPersonaFlooredLineCarveOut:
    def test_the_persona_and_the_injected_line_agree_on_the_floored_case(self, tmp_path, monkeypatch):
        """THE CONTRADICTION TEST, end to end on the artifact that produces it. The same turn ships
        both strings, so they must not instruct opposite things.

        Revert the persona paragraph and this FAILS: the prompt says 'write no bullet for it' and the
        persona says every injected episode gets its own bullet and never drop one for being thin."""
        _artifact(tmp_path, monkeypatch, _FULL)
        eps = tl.episodes_for("drivers/harmattan", "2026-07-31")
        _sg, vp = _blocks(monkeypatch, _node("drivers/harmattan", eps))

        assert eps == [] and an._episodes_on(vp) is True           # the gate fires on zero windows
        assert "write no bullet for it" in vp                      # ...the injected line's own rule
        persona = an._system(episodes=True)
        assert an._SYSTEM_EPISODES in persona                      # ...and the persona actually ships
        assert "A 'DATED EPISODES' LINE THAT CARRIES NO WINDOW IS NOT AN EPISODE." in persona
        assert "write NO bullet for it" in persona
        assert persona.isascii()

    def test_the_persona_omits_the_section_when_no_line_carries_a_window(self):
        """The all-floored turn has nothing to enumerate, so the honest output is NO SECTION -- not an
        empty heading (which reds both W4 deck pins) and not a bullet minted to fill it (which is the
        confabulation the whole timeline layer exists to close). The thinness is prose, not a bullet."""
        s = an._SYSTEM_EPISODES
        assert "OMIT the '## Episodes' section ENTIRELY" in s
        assert "an empty heading is a defect" in s
        assert "in prose in '## The record'" in s
        # ...and the gate sentence no longer keys on a LINE being present, which is what made the
        # floored line -- a line by construction -- read as an instruction to render the section.
        assert "Render '## Episodes' ONLY when an injected line carries at least one window" in s
        assert "Render '## Episodes' ONLY when a 'DATED EPISODES' line is present" not in s

    def test_the_bullet_rules_are_scoped_to_WINDOWS_not_to_LINES(self):
        """The three rules that contradicted the floored line are each scoped to the window now. The
        'never drop an episode for being thin' rule stays -- it is the honesty leg W4 exists to reward --
        but THIN is defined as 'no citable item inside the window', never 'the floor withheld it'."""
        s = an._SYSTEM_EPISODES
        assert "ONE '- ' bullet per injected episode WINDOW" in s
        assert "EVERY INJECTED EPISODE WINDOW GETS ITS OWN BULLET" in s
        assert "Never drop a window for being thin" in s
        assert "never a window the floor withheld and did not show you" in s
        assert "count of suppressed windows into an episode" in s   # the bare count is not a window

    def test_a_windowed_turn_is_unaffected_by_the_carve_out(self, tmp_path, monkeypatch):
        """The carve-out must not switch the section off on the ordinary turn: a node with surviving
        windows still injects them, and the persona still orders the enumeration."""
        _artifact(tmp_path, monkeypatch, _PARTIAL)
        eps = tl.episodes_for("drivers/black_sea", "2026-07-31")
        _sg, vp = _blocks(monkeypatch, _node("drivers/black_sea", eps))
        assert [e["n"] for e in eps] == [6, 5, 2]
        assert an._episodes_on(vp) is True
        assert "write no bullet for it" not in vp                   # no floor-absence line here
        assert "ENUMERATE those windows in a dedicated '## Episodes' section" in an._SYSTEM_EPISODES


# =============================================================================================
# D-EI-8 -- THE STAMP. A knob outside the stamp reopens the I-1 class for the new parameter.
# =============================================================================================

class TestStampKnobs:
    def test_build_stamp_carries_min_props_and_max_per_node(self):
        """Both ride beside gap_days, which is in the stamp precisely so a silent params edit FAILS
        check_artifact instead of quietly re-cutting what the reader sees. max_per_node was an existing,
        smaller instance of the same gap and joins in the same change."""
        s = tl.build_stamp(_PARTIAL)
        assert s["gap_days"] == tl.GAP_DAYS
        assert s["min_props"] == tl.MIN_PROPS == 2
        assert s["max_per_node"] == tl.MAX_PER_NODE == 4
        json.dumps(s)                                             # it is written to S3; it must survive

    def test_the_stamp_describes_the_STORE_and_the_floor_does_not_shrink_it(self):
        """R3.5 leg 3: n_episodes / n_prop_dates keep describing the STORE, which is the only thing that
        makes the stamp self-verifying (recomputable from the artifact alone). The floor is a READ-time
        knob, so a floored artifact and an unfloored one have identical counts and fingerprints -- and
        the threshold can move with no rebuild, which is the whole cost the sequencing law minimises."""
        s = tl.build_stamp(_PARTIAL)
        assert s["n_episodes"] == 4                               # all four, including the floored one
        assert s["n_prop_dates"] == 14
        assert tl.build_stamp(_PARTIAL)["fingerprint"] == s["fingerprint"]

    def test_check_artifact_rejects_a_stamp_MISSING_the_new_keys(self):
        """NO BACK-COMPAT SHIM (ratified): no schema-2 artifact exists in production yet, so a tolerated
        absence could only mean 'written by a build that predates this fence' -- the unknowable state
        leg L-a already refuses. A missing key fails exactly like a mismatch."""
        base = tl.build_stamp(_PARTIAL)
        for missing in ("min_props", "max_per_node"):
            stamp = {k: v for k, v in base.items() if k != missing}
            res = tl.check_artifact(stamp=stamp, state="ok", live_prop_dates=14, live_nodes=1)
            assert res["ok"] is False
            by_leg = {leg["leg"]: leg for leg in res["legs"]}
            assert by_leg[missing]["ok"] is False
            assert "None" in by_leg[missing]["detail"]

    def test_check_artifact_rejects_a_MISMATCHED_knob_the_way_it_rejects_gap_days(self):
        """One shape for all three legs: the message names the stamped value AND the serving value, so
        the operator can see which side moved without opening params.yaml."""
        for field, bad in (("gap_days", 45), ("min_props", 3), ("max_per_node", 8)):
            stamp = dict(tl.build_stamp(_PARTIAL))
            stamp[field] = bad
            res = tl.check_artifact(stamp=stamp, state="ok", live_prop_dates=14, live_nodes=1)
            assert res["ok"] is False
            blob = " ".join(res["reasons"])
            assert field in blob and str(bad) in blob
            assert str(getattr(tl, field.upper())) in blob

    def test_a_freshly_stamped_artifact_still_PASSES(self):
        """A fence that can only fail is as useless as one that can only pass. The stamp this code
        writes must be the stamp this code accepts -- otherwise the first --check after the rebuild is
        red for a reason nobody can act on."""
        res = tl.check_artifact(stamp=tl.build_stamp(_PARTIAL), state="ok",
                                live_prop_dates=14, live_nodes=1)
        assert res["ok"] is True and res["reasons"] == []

    def test_check_artifact_still_never_raises_on_garbage(self):
        """The check returns a VERDICT; only its CLI caller turns that into rc=2. Three legs where there
        were one is three more chances for a raise inside a preflight."""
        for junk in ({}, {"min_props": "two"}, {"max_per_node": None}, {"gap_days": []}):
            assert tl.check_artifact(stamp=junk, state="ok",
                                     live_prop_dates=1, live_nodes=1)["ok"] is False
