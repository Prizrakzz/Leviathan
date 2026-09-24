"""THE TRACE KEY REGISTRY's OWN DECK (lane F, 2026-09-17) -- the file `tracekeys.py`'s docstring has
named since D-AM-3 and which did not exist until today.

`tracekeys.py`'s MODULE DOCSTRING says, verbatim (cited by symbol, never by line -- the line citation
this sentence used to carry was already off by two when the round-2 reviewer read it, moved by this
lane's own `import os`): *"LEAF MODULE: no leviathan imports (the
response_contracts.py discipline). test_tracekeys.py asserts (a) eval.py actually loops these tuples,
and (b) every key stamped by the known mint sites appears here."* Grep found no such file. The two
assertions it promised live scattered across `test_dam_phase0.py` (the loop + five mints),
`test_cascade_walk.py` (three tail blocks), `test_dmw_eval_instruments.py` (fifteen negative indices)
and six other decks -- so the module's OWN contract had no home, and the ONE property that is
genuinely the registry's rather than any consumer's (the two idioms below, and which one a key takes)
was asserted nowhere at all.

WHAT THIS DECK OWNS, and deliberately not more -- the tail-INDEX pins stay where they are, in the decks
whose subject matter they belong to:

  THE TWO IDIOMS      a REGISTERED key is PRESENT-WITH-NULL on a turn that does not stamp it; a
                      CONDITIONAL SPLAT in `_per_answer_record` is ABSENT. `eval.py`'s own comment
                      claimed the registry gave "the same ABSENT-WHEN-OFF shape ... for free" -- that
                      sentence was FALSE against the code at the splat line and against
                      `test_dmw_eval_instruments.py`'s `is None  # absent-as-None` pin, and lane F
                      corrected it. The distinction decides whether a column lands on every control row
                      of every deck forever, so it is pinned here rather than remembered.
  THE LEAF LAW        no `leviathan` import in the module, at all. A registry that imported a producer
                      could not be read by a producer.
  THE APPEND LAW      "ORDER IS THE ARTIFACT COLUMN ORDER -- append, never sort." Pinned as a PREFIX
                      relation against the keys that existed before the last three appends, which is
                      the property a stored artifact's readers actually depend on.
  THE LIFT            `eval.py` really loops both tuples, by source text, so a rename cannot quietly
                      turn the registry into decoration.
  NO DUPLICATES       a duplicated name is a duplicated column.

NO NETWORK, NO AWS, NO LLM, NO pg.
"""
from __future__ import annotations

import pathlib

import pytest
from leviathan.graphrag import eval as ev
from leviathan.graphrag import tracekeys as tk

_SRC = pathlib.Path(tk.__file__).read_text(encoding="utf-8")
_EVAL_SRC = pathlib.Path(ev.__file__).read_text(encoding="utf-8")


def _turn(trace: dict) -> dict:
    """The minimal shape `_per_answer_record` needs for a 'single' row."""
    return {"q": {"id": "row-0"}, "out": {"trace": dict(trace)}}


# ── the module's own two promises ─────────────────────────────────────────────────────────────────
def test_eval_loops_both_tuples_so_registration_really_is_the_lift():
    """PROMISE (a). The C2/U3 class -- a trace key stamped by a producer and named nowhere in eval's
    record reaches NO artifact, silently -- is closed only while eval SPLATS the tuple. A hand-written
    list of columns that merely happened to match would satisfy every other test in the estate and
    reopen the defect the moment someone appended a key here."""
    assert "for k in tk.TRACE_RECORD_KEYS}" in _EVAL_SRC
    assert "for dk, col in tk.DECISION_RECORD_KEYS}" in _EVAL_SRC
    rec = ev._per_answer_record(_turn({}), "single")
    for k in tk.TRACE_RECORD_KEYS:
        assert k in rec, k                       # every registered key IS a column, on every row
    for _dk, col in tk.DECISION_RECORD_KEYS:
        assert col in rec, col


def test_every_known_mint_site_is_registered():
    """PROMISE (b), read against the producers that exist today. Each name below is stamped by a
    producer in `src/` and would reach no artifact if it left this tuple."""
    for key in ("fork_basis", "tldr_direction", "record_through", "response_contract", "synth_usage",
                "mode_knobs", "rerank_lane", "walk_shape", "escalation_decision", "cascade_closure",
                "state_board", "quantify_xc_fork",
                # LANE F 2026-09-17, the cost census -- the three seats `turn_cost_usd` never saw
                "numbers_usage", "plan_usage", "desk_register",
                # ...and LANE E's writer seam, appended in the SAME commit so the tail moves once
                "writer_seam"):
        assert key in tk.TRACE_RECORD_KEYS, key
    assert dict(tk.DECISION_RECORD_KEYS)["response_contract"] == "response_contract_decision"
    assert dict(tk.DECISION_RECORD_KEYS)["kind_history"] == "kind_history"
    assert dict(tk.DECISION_RECORD_KEYS)["mode"] == "mode_decision"


def test_the_registry_is_a_leaf_module():
    """`response_contracts.py` discipline, and it is load-bearing rather than stylistic: `answer.py`,
    `orchestrator.py`, `planner.py`, `rankers.py`, `cascade.py`, `state/board.py`, `config_check.py`
    and `eval.py` all import this module. One leviathan import here is an import cycle in eight files."""
    assert "from leviathan" not in _SRC and "import leviathan" not in _SRC


def test_no_duplicate_columns_in_either_tuple():
    assert len(set(tk.TRACE_RECORD_KEYS)) == len(tk.TRACE_RECORD_KEYS)
    cols = [col for _dk, col in tk.DECISION_RECORD_KEYS]
    assert len(set(cols)) == len(cols)
    assert not (set(tk.TRACE_RECORD_KEYS) & set(cols))      # a name may not be both a trace and a decision column


# ── the property that is the registry's own, and nobody else's ────────────────────────────────────
def test_a_registered_key_is_present_with_null_and_a_splat_is_absent():
    """THE SENTENCE THAT WAS WRONG, PINNED SO IT CANNOT COME BACK.

    `eval.py`'s `numbers_budget` note used to end "...the same ABSENT-WHEN-OFF shape that
    `**{k: ... for k in tk.TRACE_RECORD_KEYS}` gives a registered key for free". It does not. The
    registry splat is a comprehension over a FIXED tuple: it ALWAYS emits the key, with None when the
    trace has none. Measured on the 2026-09-16 in-VPC smoke, every row carries
    `"composition_census": null` -- a registered key no smoke turn stamped.

    THE CHOICE IS REAL AND IT IS THE WHOLE REASON THIS TEST EXISTS. Registering puts a permanent
    column on every deck forever AND re-anchors the negative-index tail pins in seven test files; a
    conditional splat puts a column only on the rows that have the thing and leaves every flag-off
    artifact byte-identical. `bridge_query` took the splat for exactly that reason
    (BRIDGE_VERDICT.md sec 4a); the cost census's three keys took the registry because the estate
    should always carry them."""
    off = ev._per_answer_record(_turn({}), "single")
    for k in ("composition_census", "state_board", "numbers_usage", "plan_usage",
              "desk_register", "writer_seam"):
        assert k in off and off[k] is None, k                    # REGISTERED -> present-with-null
    # LANE tracekeys (2026-09-22) adds `chain_lints` to the SPLAT side, and it is named here rather than
    # in `test_every_known_mint_site_is_registered` on purpose: that test asserts REGISTRATION, which is
    # the option this build measured and refused. `answer._chain_lints` stamps an eight-key census on
    # `sg.trace["chain_lints"]` and `_answer_l2` spreads the trace wholesale, so the key is a real mint
    # site -- it simply takes the splat, because registering it puts `"chain_lints": null` on every
    # control row of every deck forever AND re-anchors 60 negative-index tail pins across eight files,
    # while the splat leaves the flag-off record at its 209 columns in their existing order.
    for k in ("bridge_query", "numbers_budget", "turn_cost_total_usd", "turn_cost_by_seat_usd",
              "judge_usage", "chain_lints"):
        assert k not in off, k                                   # SPLAT -> absent
    assert "chain_lints" not in tk.TRACE_RECORD_KEYS              # ...and it is genuinely unregistered
    # ...and a registered key LIFTS VERBATIM, by its own name, with no rename hook anywhere
    on = ev._per_answer_record(_turn({"state_board": {"legs": {}}, "plan_usage": {"model": "m"}}),
                               "single")
    assert on["state_board"] == {"legs": {}} and on["plan_usage"] == {"model": "m"}


def test_the_order_is_the_column_order_and_appends_never_sort():
    """"ORDER IS THE ARTIFACT COLUMN ORDER -- append, never sort." The D-MW P3 note in the file records
    what happens when it is broken: that build INSERTED two keys ahead of `rerank_lane` and shifted
    that column's position in every per-answer record written afterwards, so two waves' artifacts
    stopped being comparable column-for-column.

    Pinned as a PREFIX relation, which is the property a stored reader depends on: every key that
    existed before an append must still sit at the same INDEX afterwards. `state_board` was the tail
    until lane F appended the cost census's three, so `state_board`'s index is the anchor."""
    keys = list(tk.TRACE_RECORD_KEYS)
    assert keys[0] == "fork_basis"                               # the first column, since D-DT-2
    assert keys[-8] == "state_board"                             # the S5/S6 tail, still at its index
    assert keys[-7:-3] == ["numbers_usage", "plan_usage", "desk_register", "writer_seam"]  # ONE commit
    assert keys[-3:] == ["board_n_start", "injected_n", "numbers_block_chars"]  # lane A 09-23: the three lane-0 stamps, ONE commit
    # the tail four are genuinely NEW names, not a re-spelling of something older that was moved
    assert keys.index("state_board") == len(keys) - 8
    assert sorted(keys) != keys                                  # never sorted -- the law, not a wish


# ── the cost census, as the registry sees it ──────────────────────────────────────────────────────
def test_the_cost_census_keys_carry_their_rationale_beside_them():
    """THE FILE'S OWN CONTRACT: "Per-key rationale lives beside each entry in tracekeys.py, not here"
    (eval.py's record comment). A key appended with no reason is a column nobody can interpret two
    waves later -- which is how `plan_tokens` and `plan_usage` come to look like the same quantity."""
    for key, must in (("numbers_usage", "GRAPHRAG_COST_CENSUS"),
                      ("plan_usage", "plan_tokens"),
                      # CITED BY SYMBOL, NOT BY LINE (round-2 review m8, re-stated MAJOR-1): the line
                      # citation this entry used to carry into `answer.py` moved TWICE in ONE sitting
                      # while the six lanes wrote, which is why no number is written here at all.
                      ("desk_register", "_desk_register_lint"),
                      ("writer_seam", "GRAPHRAG_STATE_BOARD")):
        # the entry's own block: from its name to the start of the next tuple entry (or the close)
        block = _SRC[_SRC.index(f'    "{key}",'):].split('\n    "')[0]
        assert must in block, (key, must)
        assert len(block) > 300, key                             # a rationale, not a word


@pytest.mark.parametrize("key", ["numbers_usage", "plan_usage", "desk_register", "writer_seam"])
def test_the_cost_census_keys_are_absent_from_a_dark_trace_and_lift_when_stamped(key):
    """ABSENT-AT-THE-STAMP is what keeps every flag-off TRACE byte-identical; absent-as-None is what
    the RECORD does with a key the trace does not carry. Both halves, one test, per key -- the two are
    different files' contracts and conflating them is how the wrong idiom gets chosen."""
    assert ev._per_answer_record(_turn({}), "single")[key] is None
    assert ev._per_answer_record(_turn({key: {"x": 1}}), "single")[key] == {"x": 1}


# ── the one flag grammar the registry's own keys ride on ──────────────────────────────────────────
def test_the_one_census_grammar_lives_here_and_is_strict(monkeypatch):
    """ROUND-2 REVIEW M1 -- WHY A FLAG READER BELONGS IN A KEY REGISTRY.

    Three of the keys above exist only while `GRAPHRAG_COST_CENSUS` is lit, and round 1 shipped TWO
    readers of that ONE flag with DIFFERENT grammars (`dispatch` strict, `numbers/agent` also taking
    `yes`). MEASURED in one process, `GRAPHRAG_COST_CENSUS=yes` read False in dispatch and True in the
    agent -- a HALF-ARMED census stamping the largest seat in the arm while the planner's pop and the
    judge's usage stayed dark, under a panel that printed a "total". This module is the ONE place every
    reader can reach: it is the leaf, and eight producers plus eval already read it.

    STRICT `on|1|true`, default OFF, and the near-misses are pinned FALSE by name -- this gates a
    trace-key change that reaches the serving lane, so a typo must never half-arm a measurement."""
    assert tk.COST_CENSUS_ENV == "GRAPHRAG_COST_CENSUS"
    for v, on in (("on", True), ("1", True), ("true", True), ("TRUE", True), (" on ", True),
                  ("yes", False), ("YES", False), ("y", False), ("enabled", False), ("off", False),
                  ("", False), ("0", False), ("no", False)):
        monkeypatch.setenv("GRAPHRAG_COST_CENSUS", v)
        assert tk.cost_census_on() is on, v
    monkeypatch.delenv("GRAPHRAG_COST_CENSUS")
    assert tk.cost_census_on() is False                       # DEFAULT OFF with no environment at all
    # ...and the leaf law survives it: the grammar reads the environment with the standard library and
    # imports nothing from this package, which `test_the_registry_is_a_leaf_module` above re-asserts.
    assert "\nimport os\n" in _SRC


# ── the OTHER roster eval.py reads, and the claim a build made about it ───────────────────────────
def test_no_chain_lint_counter_name_is_spelled_anywhere_in_eval_py():
    """LANE tracekeys ROUND 2 (2026-09-23) -- A SELF-REFUTATION ITEM TURNED INTO AN ASSERTION.

    The round-1 build report claimed "counter names SPELLED in eval.py: [] (none)" as one of its own
    refutation numbers. The review MEASURED THREE (`CHAIN_LINT_COUNTERS[0]`, `[3]` and `[4]`, as
    literals inside the very line whose words were "read off the roster and never spelled here"). A
    number in a build report that nobody can re-run is a number that drifts the day after it is
    written, so it lives here now and the build's claim is the deck's.

    WHY IT BELONGS IN THIS DECK: `chain_lints` is the SPLAT half of this file's own subject -- the
    registry decides whether a key is a column, and this roster decides whether a counter is a FIGURE.
    Both are "a name read off a producer, never re-spelled by a consumer", and this one has no other
    home: `state/lint.py` owns the tuple and cannot see `eval.py`'s prose.

    THE PIN CANNOT PASS BY DELETION. A file with no chain panel at all would spell no counter either,
    so the roster READ is asserted in the same breath, and the panel is run to prove every name still
    reaches the page."""
    from leviathan.graphrag.state import lint as LINT
    assert len(LINT.CHAIN_LINT_COUNTERS) >= 5
    for c in LINT.CHAIN_LINT_COUNTERS:
        assert c not in _EVAL_SRC, c                  # not in code, not in a comment, not in prose
    assert "_lint.CHAIN_LINT_COUNTERS" in _EVAL_SRC   # ...because the ROSTER is what it reads instead
    census = {"outcome": "ok", "sentences": 2, "corrected": 1}
    census.update({c: i + 1 for i, c in enumerate(LINT.CHAIN_LINT_COUNTERS)})
    line = [x for x in ev.state_report([{"out": {"trace": {"chain_lints": census}}}])
            if ("`%s`" % LINT.CHAIN_LINT_COUNTERS[0]) in x]
    assert len(line) == 1
    for i, c in enumerate(LINT.CHAIN_LINT_COUNTERS):
        assert ("`%s` %d" % (c, i + 1)) in line[0], c
    # AND THE DEAD READ IS GONE WITH IT: the one-hop figure counted a `trace["planner"]` value no
    # producer writes, so it could not leave 0 on any deck. The panel now reads the lane stamp's own
    # reason and the one-hop body's `regimes` key.
    #
    # PINNED ON THE AST AND NOT ON THE TEXT, and that is the whole point of the pin: a text scan
    # cannot tell the KEY `"planner"` from the panel's own sentence NAMING the key it deliberately
    # does not read, and the prose has to stay free to say which field was dead and why. A bare
    # `"planner"` constant inside this function is a lookup; the same word inside a sentence is not.
    import ast
    fn = next(x for x in ast.walk(ast.parse(_EVAL_SRC))
              if isinstance(x, ast.FunctionDef) and x.name == "state_report")
    consts = {c.value for c in ast.walk(fn) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    assert "planner" not in consts                   # no row in this panel is keyed on that field
    assert "lane_off:onehop" in consts and "regimes" in consts   # ...these two are what it reads


def test_lane0_the_seat_board_seam_is_stamped_and_data_families_is_the_registry_tail():
    """NUMBERS-SEAT RECON (2026-09-23), LANE 0 -- three trace facts that rode no artifact: the board's [N]
    origin (every seat/board seam figure in three recons was a positional inference), the numbers block's
    own size (BoardBlockChars had no twin), and the decision field that NAMES the table (absent from
    1,455 banked rows). The two answer.py stamps are read at source: `board_n_start` inside the block
    that stamps `state_board` (absent when the board never ran -- a flag-off trace is byte-identical);
    `numbers_block_chars` beside `injected_n`. The registry gains `data_families` AT THE TAIL."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "src" / "leviathan" / "graphrag" / "answer.py").read_text(encoding="utf-8")
    i = src.index('sg.trace["state_board"] = _sb["trace"]')
    assert 'sg.trace["board_n_start"] = int(_board_n_start or 0)' in src[i:i + 900], "stamped beside the board trace"
    j = src.index('sg.trace["injected_n"] = n_num')
    assert 'sg.trace["numbers_block_chars"] = len(extra_context or "")' in src[j:j + 700], "stamped beside injected_n"
    assert tk.DECISION_RECORD_KEYS[-1] == ("data_families", "data_families_decision")
    cols = [c for _k, c in tk.DECISION_RECORD_KEYS]
    assert len(set(cols)) == len(cols)


def test_lane0_stamps_are_REGISTERED_at_the_tail_and_ride_every_record():
    """09-23 FIX ROUND, LANE A (CONTRACT C14; THREAT_MODEL A-9 / B11). D7 of the 2026-09-23 re-smoke,
    CONFIRMED on ten of ten records: commit ee06f19c stamped `board_n_start`, `injected_n` and
    `numbers_block_chars` on `sg.trace` and said they "ride the re-smoke at zero cost" -- and not one of
    the ten per-answer records carried them, because registration IS the lift and they were never
    registered. They are appended AT THE TAIL, in that order, in ONE commit, so every negative-index tail
    pin in the estate re-anchors once, by three.

    B11's two invariants: HEAD's key list is a STRICT PREFIX of this one (nothing inserted, nothing
    moved: a stored artifact's columns stay comparable), and `chain_lints` stays a SPLAT -- absent,
    never None -- on a row that did not stamp it."""
    keys = list(tk.TRACE_RECORD_KEYS)
    assert keys[-3:] == ["board_n_start", "injected_n", "numbers_block_chars"]
    assert len(keys) == 50 and keys[-4] == "writer_seam" and keys[-8] == "state_board"
    # the three are stamped by the L2 body, and the registration is what lifts them
    rec = ev._per_answer_record(_turn({"board_n_start": 51, "injected_n": 94,
                                       "numbers_block_chars": 12034}), "single")
    assert (rec["board_n_start"], rec["injected_n"], rec["numbers_block_chars"]) == (51, 94, 12034)
    # a turn that stamped none (a board-off or one-hop row) lifts them PRESENT-WITH-NULL, the registry's
    # own shape -- never a fabricated zero
    off = ev._per_answer_record(_turn({}), "single")
    assert off["board_n_start"] is None and off["injected_n"] is None
    assert off["numbers_block_chars"] is None
    # ...and they are the record's LAST three registry columns, in the registry's order: the splat is
    # one dict comprehension over the tuple, so the column order is the tuple order
    reg_cols = [k for k in off if k in set(keys)]
    assert reg_cols[-3:] == ["board_n_start", "injected_n", "numbers_block_chars"]
    assert "chain_lints" not in off                        # B11: the splat stays a splat
    # the mint sites are still where the registry's own rationale says they are
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "src" / "leviathan" / "graphrag" / "answer.py"
           ).read_text(encoding="utf-8")
    for k in ("board_n_start", "injected_n", "numbers_block_chars"):
        assert ('sg.trace["%s"]' % k) in src, k
        assert ('"%s"' % k) in _SRC, k                      # ...and each carries its note here


# ── 09-24 (fix round FINAL_2, INTEGRATION O-2): THE SPLAT REGISTRY ─────────────────────────────────
def test_O2_the_splat_registry_is_its_own_tuple_and_the_record_registry_is_untouched():
    """The absent-when-off idiom, REGISTERED: a second tuple at the module's tail, disjoint from every
    column the record already has, so `TRACE_RECORD_KEYS` (B11: 50 keys, HEAD's 47 a strict prefix) and
    every negative-index tail pin in every deck stay exactly where they were."""
    assert tk.TRACE_SPLAT_KEYS == ("tldr_spine_deduped", "rv_pair_spread", "rv_pair_uncomputed")
    assert len(set(tk.TRACE_SPLAT_KEYS)) == len(tk.TRACE_SPLAT_KEYS)
    cols = {col for _dk, col in tk.DECISION_RECORD_KEYS}
    assert not (set(tk.TRACE_SPLAT_KEYS) & (set(tk.TRACE_RECORD_KEYS) | cols))
    off = ev._per_answer_record(_turn({}), "single")
    assert not (set(tk.TRACE_SPLAT_KEYS) & set(off))          # ...nor any column eval already emits
    assert len(tk.TRACE_RECORD_KEYS) == 50 and tk.TRACE_RECORD_KEYS[-1] == "numbers_block_chars"
    assert "for k in tk.TRACE_SPLAT_KEYS" in _EVAL_SRC        # registration IS the lift
    from leviathan.graphrag.numbers import agent as na
    assert na.RV_PAIR_UNCOMPUTED_KEY in tk.TRACE_SPLAT_KEYS   # the producer's own constant, not a copy


def test_O2_a_splat_key_is_ABSENT_when_off_and_lifts_VERBATIM_when_stamped():
    """ABSENT, NEVER None: a row whose trace does not carry the key has no column at all (the flag-off
    record keeps its exact columns in their exact order), and a stamped key rides verbatim with every
    other column unmoved."""
    off = ev._per_answer_record(_turn({}), "single")
    for k in tk.TRACE_SPLAT_KEYS:
        v = {"probe": k, "n": 1}
        on = ev._per_answer_record(_turn({k: v}), "single")
        assert on[k] == v, k
        assert [c for c in on if c != k] == list(off), k
        assert k not in ev._per_answer_record(_turn({k: None}), "single"), k


def test_O2_the_rv_records_ride_guarded_lines_and_never_the_unguarded_copy_tuple():
    """Both orchestrator lanes carry the RV pair leg's record on a GUARDED line of its own (the
    `numbers_usage` idiom): the `_sk` tuples are bare, unguarded copies, and a key placed there lands on
    every hybrid turn as an explicit None. Three carries: numbers_only's trace, hybrid's `_resolve` into
    `holder`, and hybrid's `holder` onto the trace. The spine census's one mint site is answer.py."""
    from leviathan.graphrag import orchestrator as orch
    src = pathlib.Path(orch.__file__).read_text(encoding="utf-8")
    for chunk in src.split("for _sk in (")[1:]:
        head = chunk.split("):")[0]
        assert "rv_pair" not in head and "RV_PAIR" not in head
    assert src.count('for _rk in ("rv_pair_spread", na.RV_PAIR_UNCOMPUTED_KEY):') == 3
    ans = (pathlib.Path(ev.__file__).parent / "answer.py").read_text(encoding="utf-8")
    assert 'sg.trace["tldr_spine_deduped"] = _spine' in ans


def test_m3_the_spine_census_is_minted_only_on_a_board_lit_turn_so_a_control_record_is_213_always():
    """09-24 (VERIFY_FINAL m3): `tldr_spine_deduped` was the one splat key a CONTROL row could carry -- the
    de-dup that mints it ran flag-independently, so a flag-off record gained a 214th column (at 77) and its
    served body differed from HEAD's. Both mint sites now run the de-dup under the board flag, IN THE SAME
    EXPRESSION as the key, so the two can never disagree; and a flag-off record is B11's 213 columns --
    HEAD's 210 in HEAD's order + the three C14 tail keys -- with no splat key, always. The functional
    drive through both real answer bodies lives in test_answer.py
    (`test_the_spine_dedup_and_its_key_ride_the_board_flag_on_both_bodies`)."""
    ans = (pathlib.Path(ev.__file__).parent / "answer.py").read_text(encoding="utf-8")
    assert ans.count("_dedup_spine_tldr(structured)") == 2
    assert ans.count("_spine = _dedup_spine_tldr(structured) if _state_board_on() else {}") == 2
    off = ev._per_answer_record(_turn({"planner": "l2"}), "single")
    assert len(off) == 213 and not (set(tk.TRACE_SPLAT_KEYS) & set(off))


@pytest.mark.parametrize("lane", ["run_numbers_only", "run_hybrid"])
def test_O2_a_REFUSED_pair_reaches_the_trace_on_both_lanes_and_a_dark_turn_carries_neither(lane, monkeypatch):
    """THE ONE THING THE ARM COULD NOT COUNT (INTEGRATION O-2, THREAT T-3 "refuse and count"). The 09-23
    palm/rapeseed question, the Pink Sheet palm print verbatim (USD/mt, unlabelled currency) and a ZCE
    rapeseed-oil settle in CNY/t: the REAL agent's RV leg refuses (two currencies are never differenced)
    and the refusal reaches the trace -- then the record -- on both lanes. With the board flag dark the
    leg never runs and neither key exists. The numbers MODEL is scripted; everything else is real."""
    import types

    from leviathan.graphrag import answer as an
    from leviathan.graphrag import orchestrator as orch
    from leviathan.graphrag.numbers import agent as na
    from leviathan.graphrag.state import __main__ as M
    zce = M.tape_fixture_rows("rapeseed_oil_zce", sessions=5, last="2026-09-22", base=9000.0)
    for r in zce:
        r["currency"], r["unit"] = "CNY", "CNY/t"
    mirror = M.mirror_query_fn({"silver_futures_eod": zce})
    palm = [{"period": None, "revision_stamp": "2026M09", "value": "1117.0", "unit": None, "country": None,
             "knowledge_date": "2026-08-01"}]

    def qfn(sql):
        return palm if "palm_oil_cpo_usd_t" in sql else (mirror(sql) if "futures_eod" in sql else [])

    def _use(inp, tid):
        return types.SimpleNamespace(type="tool_use", name=na.TOOL_NAME, input=inp, id=tid)

    class _Client:
        def __init__(self):
            q = [types.SimpleNamespace(content=[
                     _use({"table": "silver_pink_sheet", "metric": "palm_oil_cpo_usd_t", "agg": "latest"}, "a"),
                     _use({"table": "silver_futures_eod", "metric": "settle", "commodity": "rapeseed_oil_zce",
                           "agg": "latest"}, "b")], stop_reason="tool_use", usage=None),
                 types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="read both legs.")],
                                       stop_reason="end_turn", usage=None)]
            self.messages = types.SimpleNamespace(create=lambda **kw: q.pop(0))

    def _writer(query, *, extra_resolver=None, **kw):
        extra_resolver()                                   # the synthesis-time join, as the writer seam does
        return {"answer": "(writer stubbed)", "trace": {}}

    monkeypatch.setattr(an, "answer", _writer)
    monkeypatch.delenv("GRAPHRAG_RV_PAIR_SPREAD", raising=False)
    question = ("Set palm oil against rapeseed oil for me -- whose stocks position moved more this year, "
                "and how do the two read against each other from here?")

    def _run():
        kw = {"graph": None} if lane == "run_hybrid" else {}
        return getattr(orch, lane)(question, "2026-09-23", client=_Client(), query_fn=qfn, **kw)

    monkeypatch.setenv("GRAPHRAG_STATE_BOARD", "on")
    out = _run()
    tr = out.get("trace") or {}
    refusal = tr.get(na.RV_PAIR_UNCOMPUTED_KEY)
    assert refusal["markets"] == ["malaysian_crude_palm_oil_cme", "rapeseed_oil_zce"]
    assert isinstance(refusal.get("reason"), str) and refusal["reason"]
    assert "rv_pair_spread" not in tr                       # EXACTLY ONE of the two per turn whose leg ran
    rec = ev._per_answer_record({"q": {"id": "r"}, "out": out}, "single")
    assert rec[na.RV_PAIR_UNCOMPUTED_KEY] == refusal and "rv_pair_spread" not in rec
    monkeypatch.delenv("GRAPHRAG_STATE_BOARD")
    tr_off = _run().get("trace") or {}
    assert "rv_pair_spread" not in tr_off and na.RV_PAIR_UNCOMPUTED_KEY not in tr_off
