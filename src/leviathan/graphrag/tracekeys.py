"""TRACE KEY REGISTRY (D-AM-3) — the one place a lifted trace/decision key is declared.

THE DEFECT THIS KILLS (the C2/U3 class, hit twice): a trace key stamped by answer.py or
orchestrator.py that is not ALSO named in eval.py's per-answer record reaches NO artifact —
silently. The registration lived only as literal lines inside eval.py's record dict, so every
new key needed a same-day edit there that nothing enforced.

CONTRACT:
- ``TRACE_RECORD_KEYS``: keys lifted VERBATIM from ``out["trace"]`` into every eval per-answer
  record, one column each, absent-as-None. eval.py builds these columns by LOOPING this tuple —
  adding a key here IS the registration.
- ``DECISION_RECORD_KEYS``: keys lifted from ``out["intent_decision"]``. Mapping is declared per
  entry as (decision_key, record_column) because history predates the registry: the Phase-C A/B
  scorer already reads ``response_contract_decision``, so that column name is pinned.
- Computed record fields (strip counters, judge axes, by_rule, cascade booleans...) are NOT in
  scope: they are derived by eval code that fails loudly when inputs vanish. The registry covers
  exactly the silent-lift class.
- LEAF MODULE: no leviathan imports (the response_contracts.py discipline). test_tracekeys.py
  asserts (a) eval.py actually loops these tuples, and (b) every key stamped by the known mint
  sites appears here.
"""

import os

# out["trace"] -> record[key], absent-as-None. ORDER IS THE ARTIFACT COLUMN ORDER — append, never sort.
TRACE_RECORD_KEYS: tuple[str, ...] = (
    "fork_basis",                # D-DT-2 c1: the fork-licensing basis (both mint sites)
    "episodes_model_authored",   # D-DT-1 component 6: report column, never a pin
    "episodes_scaffolded",       # ...and the stamp beside it (fired/restatement_dropped/declined)
    "tldr_direction",            # D-RC-12: absent when GRAPHRAG_TLDR_COHERENCE is off
    "record_through",            # D-RC-13: observational on every reasoning/hybrid row
    "response_contract",         # D-RC Phase B: the ACTIVE contract (answer-seam stamp)
    "synth_usage",               # D-AM-4: serving tokens {model,in,out,cache_read,cache_write}
    "mode_knobs",                # D-AM-11: the RESOLVED knob values a honored non-standard mode ran
    "composition_census",        # D-CC-1: {entities,n_entities,n_episode_windows,n_evidence}; absent when dark.
                                 # D-HP H0 BOUNDARY, RECORDED HERE BECAUSE THIS IS THE COLUMN'S CONSUMER NOTE
                                 # (10.9 residual 2): `n_evidence` changed DENOMINATOR at the H0 hoist on the
                                 # desk lanes -- it counted the PRE-DEDUP evidence list and now counts the
                                 # deduped `uniq` (answer._uniq_evidence), which is also what `n_ev` and the
                                 # rendered menu bind to. POST-H0 MEANING, PINNED: distinct evidence
                                 # DOCUMENTS (one row per source_key), not chunk appearances. A cross-boundary
                                 # read of this column pools two definitions -- artifacts written before
                                 # commit 82b213a0 are the pre-dedup population and are NOT comparable to
                                 # anything after it. Nothing gates on it (D-MW-17 recorded-only), so no gate
                                 # clause moves; the boundary is recorded so no later wave re-derives it wrong.
    "number_handles",            # D-PQ HANDLE-1: {substituted,handles_dropped,sentences_dropped,unresolvable}
                                 # ...ON THE CONTROL LANE. THE TREATMENT LANE STAMPS ELEVEN KEYS (H1 FIX
                                 # W4, finding NF-4): `answer._resolve_number_handles` adds SEVEN under
                                 # `handle_prose` -- grouped_in_slot, direction_sign_mismatch,
                                 # slot_scope_mismatch, scope_checked, direction_checked,
                                 # BINDING_REFUSED and EMPTY_ROW_ADDRESSED. The four-key byte-pin is CONTROL-
                                 # scoped, so the superset reds nothing; it is named here because this
                                 # registry is the one place every consumer already looks, and a counter
                                 # documented nowhere is a counter no gate reads.
                                 # `binding_refused` (H1 FIX Z2) is the one that MUST be found here: a
                                 # D-HP-13 / D-HP-14 refusal RESOLVED its receipt and this pass declined
                                 # to bind it -- the OPPOSITE of D-HP-17 item 4's `unresolvable` ("the
                                 # model addressed a receipt that does not exist"), which is why the two
                                 # may not share a counter. It is the ONLY record anywhere that a refusal
                                 # fired and removed prose: the class counters beside it say WHY, this one
                                 # says HOW MANY HANDLES. `scope_checked` / `direction_checked` are its
                                 # denominators (COMPARISONS, never attempts -- H1 FIX Z12a).
                                 # NOT BUDGETED BY ANY G1 CLAUSE TODAY, recorded as an open question at
                                 # plan 10.11: the two class counters it accompanies are budgeted at 15
                                 # pooled by R11 and this one is budgeted by nothing.
                                 # `empty_row_addressed` (G1 REMEDIATION-2 R2-a, plan 10.19) is the SECOND
                                 # counter split off `unresolvable` on the identical grounds: the model
                                 # addressed a menu row that EXISTS and carries no value, which is not
                                 # "a receipt that does not exist" either. The REMOVAL is unchanged (the
                                 # shipped drop/sever/kill ladder); only the accounting moved, so that
                                 # G1 clause (2)'s column reports holes in the page rather than the
                                 # writer's obedience. It is NOT a `by_rule` strip class and is in no
                                 # successor tuple -- see `answer._addresses_empty_row`. ALSO UNBUDGETED:
                                 # clause (2) must name it at the re-freeze (plan 10.19.5 item 1).
                                 # ── D-HP-25 V1 (2026-08-15, plan 10.30.3/10.30.6): the treatment lane
                                 # now stamps THIRTEEN keys. The two new ones are `GEO_CHECKED` and
                                 # `GEO_MISMATCH`, the geography axis of the binding verifier, and they
                                 # ride INSIDE this dict rather than as a new registered key so eval.py
                                 # gains them with no edit and no column shift (the `escalation_decision`
                                 # idiom: one registered key, one stamp site, one producer).
                                 # `geo_checked` is `geo_mismatch`'s DENOMINATOR and it counts
                                 # COMPARISONS, never ATTEMPTS -- the FIX Z12a contract that
                                 # `scope_checked` / `direction_checked` are already written against, so
                                 # the column can never read as coverage on a handle whose clause named
                                 # no geography at all. BOTH SIDES MUST SPEAK: the clause must OWN
                                 # exactly one canonical geography (its own consumption ledger, never
                                 # the period axis') and the receipt must name one through the SHIPPED
                                 # `from_number` rule (query country first, else a UNANIMOUS row country
                                 # on a table that is not destination-coded). `Citation.label` is NEVER
                                 # parsed -- the M1(b) fence, inherited verbatim.
                                 # `geo_mismatch` IS ALSO A `by_rule` CLASS, and the census key and the
                                 # class are ONE SPELLING on purpose (`answer._RENDER_LEDGER_CLASSES` is
                                 # read as both). It is DECLARED in `emf.G1_DECLARED_CLASSES` and in
                                 # `emf.MIS_BOUND_CLASSES`, so it consumes R11's frozen ceiling of 15.
                                 # A handle can be convicted by AT MOST ONE of the three [N] classes --
                                 # the geo check is seated inside the direction check's `else` -- so the
                                 # `MIS_BOUND_PROJECTION` dedup arithmetic is unaffected.
    "prose_debris_tidied",       # D-PQ HANDLE-3: True when a strip left a bracket/dash frame to close up
    "prose_orphans_tidied",      # CYCLE-5 TIDY-2: True when a strip left a headless paragraph to repair
    "number_rows_deduped",       # CYCLE-6 FIX-C: [N] indices re-pointed onto a full-identity twin's row
    "evidence_orphans_pruned",   # CYCLE-9 FIX 3: [E] refs removed for want of a `## Sources` row
    "cascade_closure",           # D-GD-1: per-node admission records + the open/closed edge census.
                                 # Stamped on EVERY walk, BOTH polarities of GRAPHRAG_CLOSURE_RESERVE --
                                 # `open` is the two arms' shared deterministic baseline, so the usual
                                 # absent-when-off idiom would leave the ON arm's number uncomparable.
    "rerank_lane",               # D-MW-6: {backends, requests, docs, fallbacks, throttles, short_counts,
                                 # ms} for the turn. THE GATE INSTRUMENT for the cohere parity gate -- EMF
                                 # carries no run/eval_set dimension, so "fallbacks == 0" is computable
                                 # from this column and from nowhere else. Stamped on EVERY turn that
                                 # reranks or could have (both polarities, same reason as cascade_closure).
    # ── D-MW P3. APPENDED, per the law above: the P3 build first INSERTED these two ahead of `rerank_lane`,
    # which shifts that column's position in every per-answer record (eval.py splats this registry in
    # order). "Append, never sort" is not a style note -- it is what keeps a stored artifact's columns
    # comparable across waves.
    "walk_shape",                # D-MW-13: {n_seeds, kept_by_depth, hop_contracts,
                                 # fenced_second_order_hops} -- the artifact source for four P3 RECORDED
                                 # quantities that previously had NONE (seeds and per-node depth never
                                 # reached the per-answer record). Stamped by planner.grounded_subgraph on
                                 # every walk, beside cascade_closure, both arms.
    "n_evidence_chars",          # D-MW-17: post-cap evidence char sum -- the design-time measurement for a
                                 # token-denominated budget. Recorded, never a behavior input in D-MW.
    # ── D-MW-30. APPENDED, per the law above (the 12f column-shift lesson).
    "escalation_decision",       # D-MW-30 (F10): {flagged, fired, suppressed_reason, planned_seeds,
                                 # xc_explicit, answer_mode_outlook} --
                                 # the planner-routed shape escalation, stamped by orchestrator._respond_walk
                                 # on EVERY turn, both polarities of GRAPHRAG_SHAPE_ESC. `flagged` is the
                                 # detection (the 30d read-(1) precision/recall gate reads it off the DEEP
                                 # arms, where `fired` is false by construction); `fired` is the delivery
                                 # signal the credit seam and the quality read pair with `walk_shape`.
                                 # THE LAST TWO ARE THE F12 TRIPWIRE, not decision inputs: the new
                                 # PLANNER_SYS section moves the DISPATCH PROMPT FOR EVERY TIER and shares
                                 # it with `xc_explicit` and `answer_mode_outlook`, so the 30d deck
                                 # pre-registers a per-row expectation for both and the adjudicator diffs
                                 # them off the deep arms. They ride INSIDE this dict rather than as two
                                 # DECISION_RECORD_KEYS entries so eval.py gains the columns with no edit
                                 # and no column shift -- one registered key, one stamp site, one producer.
    # ── D-HP H0 (D-HP-4). APPENDED at the tail, per the law above (the 12f column-shift lesson).
    "prose_handles",             # D-HP-4(a): the [E]-side census, a SIBLING of `number_handles`, NEVER a
                                 # fifth key inside it -- the [E] half may not ride the [N] half's dict.
                                 # Same four-key shape: {substituted, handles_dropped, sentences_dropped,
                                 # unresolvable}. (CORRECTED, H1 FIX W4: the original wording, "a four-key
                                 # dict pinned byte-for-byte by the suites", is CONTROL-lane true only --
                                 # see the treatment-lane superset named at `number_handles` above. The
                                 # sibling rule itself is unchanged and is about NAMESPACES, not arity.)
                                 # Absent (None) until D-HP-10's [E] resolution pass lands at H1.
                                 # D-HP G1 REMEDIATION D2(b) (2026-08-14): this census does NOT grow a
                                 # fifth key. G1 clause (2b)'s escape -- a RESOLVED [E] behind a value
                                 # cue -- is convicted by a SEPARATE pass seated AFTER the [E] prune
                                 # (`answer._drop_evidence_value_slot`), because the clause measures the
                                 # ASSEMBLED BODY and a conviction inside this pass pre-empted `ev_prune`.
                                 # Its record is `evidence_slot_dropped` at the tail of this list.
    "error",                     # D-HP-4(b): the LITERAL key, not the draft's `turn_error`. This registry
                                 # lifts keys VERBATIM BY THEIR OWN NAME (the contract above; eval.py's
                                 # `**{k: trace.get(k) ...}` has NO rename hook), so a `turn_error` entry
                                 # would lift a key nothing stamps -- an all-None column forever, a PERFECT
                                 # reproduction of the C2/U3 class this registry exists to kill. `error` IS
                                 # stamped: eval.py's outer except (:1771) and `_timeout_row` (:1225,
                                 # "watchdog_timeout" beside degraded_model), so the column separates CRASH
                                 # from WATCHDOG on arrival. Renaming the stamp is not the fix either --
                                 # `_timeout_row`'s docstring makes trace['error'] the AV2 transient-policy
                                 # discriminator.
    "floor_cause",               # D-HP-4(b): the orchestrator's deterministic floor (orchestrator.py:2314,
                                 # beside trace["floor"]="evidence_only" at :1597). A FLOORED turn is a
                                 # THIRD failure shape and was invisible in the per-answer record.
                                 # NB (AC3 correction 4a, MEASURED): these two ATTRIBUTE a failure, they do
                                 # not DETECT one. The four max-arm dead rows carry `error` None,
                                 # `floor_cause` absent, `answer` None and `mode_decision` POPULATED --
                                 # neither the except-branch nor the floor produced them. THE TRIPWIRE is
                                 # `walk_shape is not None` AND `synth_usage is not None` (both already
                                 # registered above); G1 clause (5) and G3 rung 4 read all four.
    "bare_digit_count",          # D-HP-4(c): RAW pre-sanitize digit escapes, in the counter-cluster idiom at
                                 # answer.py:2161-2169. ALWAYS ON, both polarities of the flag, gates nothing.
                                 # It is the digit-lint's ESCAPE COUNTER and it replaces `number_unbacked` as
                                 # the fabrication tripwire (248 of the 478 killed-class events are
                                 # `number_unbacked`, and D-HP-12 routes exactly those sentences here).
    "citation_resolved",         # D-HP-4(d): the verifier's `resolved` map projected onto the per-answer
                                 # record. WITHOUT IT NO [E] BINDING IS AUDITABLE FROM ANY STORED ARTIFACT --
                                 # the record carries `served_rows` (so an [N] handle -> row join exists) but
                                 # neither `resolved` nor the evidence list, so G1 clause (6)'s spot-audit is
                                 # not computable for [E] handles at all. GATE-BLOCKING for D-HP-21 (6).
    # ── D-HP H1 (D-HP-14). APPENDED at the tail, per the law above.
    "wrong_slot_audit",          # D-HP-14: THE WAVE'S #1 RISK EXPRESSED AS A COLUMN. A resolved-but-MIS-BOUND
                                 # handle prints a REAL, CITED, WRONG number -- today's fabricated number is
                                 # strippable, this one is invisible to every check in the tree, and no
                                 # instrument for it exists. SHAPE, FROZEN HERE BECAUSE FOUR CONSUMERS JOIN ON
                                 # IT: {scope_checked, scope_mismatch, direction_checked, direction_mismatch},
                                 # four ints, stamped by the [N]/[E] render passes on every handle-prose turn
                                 # (absent -> None on every control row, which is the arm's own OFF proof).
                                 # PER-ROW BY CONSTRUCTION, and that is a REQUIREMENT, not a side effect: R11's
                                 # tripwire records any single row with `mis_bound_count >= 3` BY ID, and
                                 # `mis_bound_count` = slot_scope_mismatch + direction_sign_mismatch +
                                 # wrong_slot_audit.scope_mismatch (D-HP-17 item 2c), so a per-RUN-only census
                                 # would make the ceiling of 15 uncheckable at the row level it is written at.
    # ── H1 FIX W2 (finding NF-2). APPENDED at the tail, per the law above (the 12f column-shift lesson).
    "slot_orphan_dropped",       # THE Z4/W1 REMEDY'S OWN RECORD: {sentences_dropped}, stamped by BOTH
                                 # serving bodies when a RECORDED verifier strip emptied a value slot and
                                 # the sentence went whole. Absent (never null) when it removed nothing,
                                 # and absent on every control row -- the pass is treatment-gated.
                                 # WHY IT HAD TO BE REGISTERED: this pass DELETES SENTENCES, and it was
                                 # the only removal in the stack with no counterpart anywhere -- no
                                 # `by_rule` class, no successor-family term, no column. A G2 fluency
                                 # delta it caused would have had no readable cause in any G1/G2 run,
                                 # which is the C2/U3 class this registry exists to kill, re-minted on the
                                 # one pass whose false-fire risk the H1 review measured at 314/32,557
                                 # before W1 scoped it to a recorded strip.
                                 # IT IS NOW DOUBLE-BOOKED ON PURPOSE: W2 also folds the same count into
                                 # the ONE strip ledger as `by_rule['slot_orphan']` (+`stripped`), so the
                                 # CLASS SCAN sees it without having to know this column exists. This key
                                 # is the per-turn census; the ledger class is the pooled instrument. They
                                 # come from one producer and must agree.
                                 # `bare_digit_dropped` is deliberately NOT registered beside it: that
                                 # remedy's magnitude is already recoverable from `by_rule['bare_digit']`
                                 # (verify's own charge for the same sentences), so it is shadowed rather
                                 # than silent. Recorded here so the asymmetry is a decision, not a gap.
    # ── H1b (D-HP-15). APPENDED at the tail, per the law above (the 12f column-shift lesson).
    "episode_spans_validated",   # D-HP-15 SELECT: {spans_checked, bullets_dropped}, stamped by BOTH
                                 # serving bodies when the span-membership pass had model episode
                                 # bullets to test. Absent (never null) on every CONTROL row -- the
                                 # mutation is treatment-gated -- and absent on any row whose mechanism
                                 # carried no '## Episodes' bullets at all.
                                 # THE DENOMINATOR RIDES WITH THE CHARGE, DELIBERATELY. `bullets_dropped`
                                 # alone is a numerator G1's (e-ep) ceiling cannot be read against: a run
                                 # with two drops over 4 bullets and one with two over 90 are the same
                                 # number and not the same fact. So a CLEAN treatment row still stamps
                                 # `{spans_checked: n, bullets_dropped: 0}` -- the one departure from the
                                 # absent-when-nothing-fired idiom, and it is what makes the ceiling
                                 # computable rather than merely stated.
                                 # DOUBLE-BOOKED ON PURPOSE, the `slot_orphan_dropped` pattern: the same
                                 # drops fold into the ONE strip ledger as `by_rule['episode_span_unbacked']`
                                 # (+ `stripped`), so the CLASS SCAN (G1 clause (4), where the class is
                                 # DECLARED) sees the removal without knowing this column exists. This key
                                 # is the per-turn census; the ledger class is the pooled instrument. One
                                 # producer (`answer._validate_episode_spans`), so they must agree.
                                 # IT IS IN NO `emf` SUCCESSOR TUPLE, for the reason stated beside
                                 # `emf.MIS_BOUND_CLASSES`.
    # -- D-HP G1 AMENDMENT A3 (2026-08-14). APPENDED AT THE TAIL, per the law at the head of this tuple
    # (the 12f column-shift lesson): every artifact written before this line keeps its column order, and
    # this column arrives last in every artifact written after it.
    "plan_tokens",               # A3: the SIZE of the popped `plan` region (answer._plan_tokens), stamped
                                 # by BOTH serving bodies beside `synth_usage`. A COUNT, NEVER THE TEXT --
                                 # `answer._pop_plan`'s privacy reason is the constraint on this column and
                                 # is restated at its producer: the region is the model's private
                                 # reasoning, and a key carrying its bytes would put that reasoning into a
                                 # stored artifact the judge, the adjudicators and the FE all read. No
                                 # consumer may extend this to a prefix, a sample or a first line.
                                 # WHY THE COLUMN EXISTS: the region is unrenderable, unstreamed and
                                 # unstored by construction, so its size was recoverable ONLY by regression
                                 # against a control arm -- which is literally how the G1 void was
                                 # diagnosed (the plan measured ~47% of treatment output, 767 to 3,748
                                 # tokens over four rows, ANTI-correlated with retained prose at r=-0.28).
                                 # ESTIMATED, NEVER BILLED: chars/4, the prose approximation; the billed
                                 # total is `synth_usage.out` and this is the share of it the scratchpad
                                 # took. Read the two together or neither.
                                 # ABSENT (never null) ON EVERY CONTROL ROW -- `plan` exists in the schema
                                 # only under `_answer_tool(handles=True)`, so the arm's OFF state is
                                 # proved by the column rather than asserted.
    # -- D-HP G1 REMEDIATION D2(b) (2026-08-14). APPENDED AT THE TAIL, per the law at the head of this
    # tuple: every artifact written before this line keeps its column order.
    "evidence_slot_dropped",     # G1 CLAUSE (2b)'s REMEDY, per turn: {convicted, handles_dropped,
                                 # sentences_dropped} from `answer._drop_evidence_value_slot` -- a
                                 # RESOLVED [E] handle standing behind a VALUE CUE, where the [N] grammar
                                 # owns the slot and an [E] payload (source/date/snippet) has no figure to
                                 # substitute. The clause had an instrument (`eval._bare_handle_escapes`)
                                 # and, until this window, NO remedy anywhere in the stack.
                                 # IT IS NOT AN `unresolvable` EVENT, and the distinction is
                                 # `binding_refused`'s exactly: the receipt EXISTS, resolved, and names
                                 # the right item -- what was convicted is the SLOT, never the address.
                                 # DOUBLE-BOOKED ON PURPOSE, the `slot_orphan_dropped` pattern: `convicted`
                                 # folds into the ONE strip ledger as `by_rule['evidence_handle_in_slot']`
                                 # (+ `stripped`), DECLARED in G1 clause (4)'s set, so the class scan sees
                                 # the removal without knowing this column exists. One producer, so the
                                 # two must agree.
                                 # ABSENT (never null) on every CONTROL row and on every treatment row
                                 # where nothing fired -- the pass is treatment-gated and the stamp is
                                 # conditional, so the OFF arm is byte-identical.
    # -- D-HP-25 THE BINDING VERIFIER (2026-08-15, plan 10.30). APPENDED AT THE TAIL, per the law at the
    # head of this tuple: every artifact written before this line keeps its column order, and this column
    # arrives last in every artifact written after it. APPEND-NEVER-SORT is the 12f law, and a sorted
    # insert re-keys every historical artifact comparison.
    "evidence_geo_dropped",      # V2's OWN RECORD, per turn: {convicted, handles_dropped,
                                 # sentences_dropped} from `answer._drop_evidence_geo_contradiction` --
                                 # a RESOLVED, SOLITARY [E] whose FULL STORED TEXT names a DIFFERENT
                                 # country than the sentence does. It is a POSITIVE-CONTRADICTION
                                 # detector: silence on absence, silence on aggregates, and a conviction
                                 # only when the receipt text positively names some OTHER country.
                                 # WHY IT IS NOT A FIFTH KEY INSIDE `evidence_slot_dropped`: different
                                 # class semantics. That pass convicts the SLOT an [E] stands in; this
                                 # one convicts the BINDING. Folding two classes into one census key
                                 # destroys the accounting the class scan reads (plan 10.30.4).
                                 # DOUBLE-BOOKED ON PURPOSE, the `slot_orphan_dropped` pattern:
                                 # `convicted` folds into the ONE strip ledger as
                                 # `by_rule['evidence_geo_contradiction']` (+ `stripped`), DECLARED in
                                 # `emf.G1_DECLARED_CLASSES` and -- unlike `evidence_handle_in_slot` --
                                 # ALSO in `emf.MIS_BOUND_CLASSES`, because a receipt naming the wrong
                                 # GEOGRAPHY is a wrong receipt. It therefore consumes R11's frozen
                                 # ceiling of 15 pooled per treatment arm, which is pre-registered at
                                 # plan 10.30.6 and is NOT a ceiling this wave may raise.
                                 # ABSENT (never null) on every CONTROL row and on every treatment row
                                 # where nothing fired -- the pass is treatment-gated and the stamp is
                                 # conditional, so the OFF arm is byte-identical.
                                 # THE [N] HALF OF THE SAME VERIFIER (V1) MINTS NO TOP-LEVEL KEY: its
                                 # two counters `geo_checked` / `geo_mismatch` ride INSIDE
                                 # `number_handles` beside the seven D-HP counters already there -- one
                                 # registered key, one stamp site, one producer, no column shift. They
                                 # are documented at `number_handles` above.
    # -- D-LD SITTING-A, THE USAGE CENSUS (2026-08-18). APPENDED AT THE TAIL, per the law at the head of
    # this tuple: every artifact written before this line keeps its column order, and this column arrives
    # last in every artifact written after it.
    "tables_queried",            # THE FIRST PER-TABLE RECORD ANYWHERE IN PRODUCTION. Lens C measured the
                                 # hole exactly: `Leviathan/Serving` has 43 metric names and NO `table`,
                                 # `card`, `metric_id` or `family` dimension in any of them; this registry
                                 # declared no table key either; and the numbers stack prints nothing per
                                 # lookup. The ONLY per-table record in the estate was `eval.py`'s own
                                 # per-call `{"table": ..., "metric": ...}` -- an offline artifact -- so
                                 # "which of the lit cards do users actually reach" was answerable from
                                 # evals and from nowhere else, for all 27 cards at once.
                                 # SHAPE: a SORTED, DE-DUPLICATED list of card ids (`numbers.agent
                                 # .tables_queried`, derived from the finished `calls` list -- the same
                                 # list every citation and [N] handle is built from, so the column can
                                 # never disagree with the provenance the reader was shown). REACH, NOT
                                 # VOLUME: a card read four times appears once, deliberately -- `MsNumbers`
                                 # is the lane's volume metric and it stays undimensioned by table.
                                 # `compute_stat` is EXCLUDED and is the only exclusion: it is a pseudo-
                                 # table minted by `_stat_calls`, in no registry, and would otherwise top
                                 # every usage census in the estate.
                                 # K9-5 (2026-09-09): THAT EXCLUSION STANDS, AND NOW HAS A SIBLING RATHER
                                 # THAN A HOLE. The stat belt is counted on its OWN metric --
                                 # `NumbersStatCalls`, dimensioned `{stat}` over the eight-name enum, with
                                 # `NumbersStatDeclined{floor}` beside it -- emitted from
                                 # `orchestrator._stat_touches` off the same finished `number_calls` list
                                 # this column is derived from. NO trace key was added: the per-answer
                                 # artifact already carries `served_rows`, from which the same census is
                                 # derivable, and appending here would re-anchor the negative-index tail
                                 # pins for a column no gate reads. Nothing about the reach census above
                                 # moves: a per-CARD panel must never carry a pseudo-table.
                                 # STAMPED ON BOTH LANES (the #144 precedent, carried the same way as
                                 # `futures_coverage_guard`): run_numbers_only copies it off the agent's
                                 # return, run_hybrid off the same payload through its join holder. A
                                 # single-lane stamp would have made the first per-table read blind to the
                                 # lane most numbers arrive on.
                                 # PRESENT-WITH-ZERO, NOT ABSENT-WHEN-EMPTY -- the ONE departure from this
                                 # file's usual idiom, and it is deliberate: a numbers turn that queried
                                 # nothing stamps `[]`, which is that turn's own zero and is precisely the
                                 # observation a reach census must be able to make (the `CascadeFired`
                                 # 0-semantics). ABSENT means the numbers lane never ran -- which on
                                 # HYBRID is never (the lane is always submitted), so there a swallowed
                                 # lane failure/timeout ALSO stamps `[]` rather than dropping the key
                                 # (review wf_051e926a F4): absence stays a numbers_only-didn't-run
                                 # signal, and a hybrid lane outage is not mistaken for a reasoning turn.
                                 # ITS EMF SIBLING IS NOT THIS COLUMN: `emf.emit_table_touches` emits
                                 # `NumbersTableTouched` on its OWN record under a `[["table"]]` dimension
                                 # set -- never on the turn emitter, whose (intent x model x mode) set the
                                 # R14 cost ruling forbids multiplying. The two come from one producer.
    "timing_ms",                 # Q-0 S0 (2026-08-28): latency as a FIRST-CLASS per-row column -- the
                                 # {total, fill, rest, borrows_*} dict orchestrator.respond stamps at
                                 # :1820. PRODUCED ONLY ON --via-orchestrator ROWS (answer() alone never
                                 # stamps it): the Q-0 law is that a row missing this column on an arm
                                 # that reads the latency axis is VOID, never zero. Closes the C/D
                                 # measurement hole (per-row latency lived only in log lines).
    "xc_open_pair",              # D-XT (2026-08-29): the resolved open-lane pick + its basis {focus,
                                 # n_seeds, focus_paired, first_paired_seed, n_pairs, n_realizable,
                                 # probes, probe_ms, capped, pair_id, target, rank, traversed?,
                                 # relevance?, fallback?}. ABSENT on every NAMED ask, every flag-off
                                 # turn and every decline.
    "xc_open_decline",           # D-XT: the SAME dict shape carrying `reason` in cascade.
                                 # XC_OPEN_DECLINES. Registering BOTH separates the FOUR outcomes a
                                 # census must read apart: NO MATCH (both absent, zero cost);
                                 # ATTEMPTED-AND-DECLINED; FIRED (xc_open_pair + quantify_reroute_v2);
                                 # and DEFERRED-BUT-NEVER-RESOLVED (xc_detect_decision.open_defer set,
                                 # both keys absent) -- the seam-never-ran tripwire, which must read 0
                                 # on --via-orchestrator reasoning/hybrid rows.
    "xc_regional_decline",       # RV-REGIONAL (2026-08-29, refute-v1 E3): the NON-FIRING regional
                                 # fork's decline channel -- {reason} from cascade.
                                 # XC_REGIONAL_DECLINES; a fired regional fork rides
                                 # quantify_reroute_v2 with regional:True instead. Same four-outcome
                                 # census argument as xc_open_decline above.
    "quantify_rv_reading_fenced",  # RV-READING: the leg-local register fence tripped and dropped the
                                 # whole reading block (the one decline that also writes a top-level
                                 # key -- the register discipline's own visibility rule).
    "quantify_derived_fenced",   # D-DA (2026-09-01): the balance-standing block's copy-surface lint
                                 # tripped and dropped the block WHOLE (fence-then-extend) -- same
                                 # visibility rule as the reading's fence key above. APPENDED at the
                                 # tail per the 12f law; the six positional tail pins re-anchor by one
                                 # in the same commit.
    "quantify_cascade_walk",     # CASCADE EPISODE WALK (charter v4, 2026-09-01): the leg's ONE
                                 # registered key (the one-key-per-producer discipline; the J4
                                 # fired==bool(key) precedent applies -- `outcome` in
                                 # {fired, declined, fenced} rides INSIDE, an ABSENT key means the
                                 # leg did not run, never that it declined). The payload carries the
                                 # whole ledger: root, order, path, firings (slice-keyed, A6),
                                 # per-cell records with per-cell `reads`, the K2 rectangle counts
                                 # (children_declared == priced + named), the counted declines, and
                                 # `grounded_tree_slices` -- the K1 diagnostic the A6 refute (M5)
                                 # required to ride INSIDE this key rather than as a second column.
                                 # APPENDED at the tail per the 12f law; the 23 negative-index tail
                                 # pins across 4 test files re-anchor by one in the SAME commit
                                 # (the refute's own count -- not six).
    "quantify_wave_reads",       # A2 (STEP-12 review minor, the D-AM-3 silent-lift class): the base
                                 # wave's spec count -- the single largest read producer on every
                                 # quantifying turn, stamped 0-included beside quantify_dark_refs
                                 # and overwritten with len(flat) after the fan. Without this column
                                 # K7's total-reads clause ('read from the counters, NEVER inferred')
                                 # is unmeasurable from any arm artifact. A plain int. APPENDED at
                                 # the tail in the SAME commit as quantify_cascade_walk, so the tail
                                 # pins re-anchor ONCE for both. `quantify_price_leg_decline` stays
                                 # deliberately UNREGISTERED (the quantify_chain_decline sibling
                                 # precedent; eval's price_leg_fired reads the FIRED key only).
    "quantify_extreme_locator",  # D-XL (E33): the LOCATOR's ONE registered key, written by the ENGINE
                                 # ONLY -- a DISPATCH decline rides decided['extreme_locator'] instead,
                                 # so an ABSENT key means the leg DID NOT RUN, never that it declined.
                                 # `outcome` in {fired, declined, fenced} and `kind` in
                                 # {extreme, windowed_extreme} both ride INSIDE it, which is why the
                                 # two kinds cost ONE key rather than two. Carries: board, label,
                                 # kind, direction, scope, since, located_date, value, unit,
                                 # contract_month, settle_kind, currency, span_start, span_end,
                                 # n_prints, recent{...} or window_* on the windowed path, reads,
                                 # rows_fenced, rendered, declines[].
    "extreme_second_hop",        # D-XL: the SECOND PRODUCER's own key. The hop runs in answer.py,
                                 # AFTER quantify, because `retr` never reaches cascade.py and the
                                 # Subgraph carries no query string -- so it is a second producer, not
                                 # a second field of the first. Carries: located_date, turn_asof,
                                 # gap_days, nodes[], episodes_per_node{}, receipts, retrieved,
                                 # ev_reads, declines[]. IT IS NEVER APPENDED TO episodes_injected.
                                 # BOTH keys land in ONE commit per the 12f law, so the negative-index
                                 # tail pins across the test files re-anchor ONCE, by two.
    "quantify_xc_fork",          # STATE ENGINE PHASE 0 (design sec 9.1 / 6.7): the CROSS-COMMODITY
                                 # FORK's closed tag, stamped by `cascade.quantify` on EVERY quantifying
                                 # turn -- `outcome` in {fired, declined, not_reached}, `reason` a member
                                 # of `cascade.XC_FORK_REASONS`, plus `path` (composer | standalone),
                                 # `pair_id`, and `legs: {reading|derived|regional: {outcome, reason,
                                 # reads}}` whose words are `XC_FORK_REASONS` / the producing leg's own
                                 # decline word / `cascade.XC_SUBLEG_ORCHESTRATOR_REASONS`.
                                 #
                                 # IT IS REGISTERED BECAUSE IT IS THE ONLY INSTRUMENT THAT CAN SEE THE
                                 # TREATMENT. The S5 build left it unregistered on the
                                 # `quantify_*_decline` sibling precedent, expecting phase 0's gate to be
                                 # a tier-1 render replay over the 7 composer-fired banked turns; the S5
                                 # review MEASURED that those artifacts carry per-answer COUNTERS ONLY
                                 # (no `calls`, no answer body, `quantify_transmission` null on every
                                 # row), so that replay does not exist at $0. And eval's four RV counters
                                 # (`rv_reading_rendered` / `_form` / `_decline` / `_fetches`) all read
                                 # `quantify_reroute_v2` or `quantify_comove`, NEITHER of which the
                                 # composer path writes -- so armed, those 7 turns would bank rows
                                 # identical to control while spending real reads and real prompt bytes.
                                 # Registration is what gives arm A a boolean that says the flag fired.
                                 # Absent on a non-quantifying turn, which lifts as None like every other
                                 # registered key on a turn that does not stamp it.
    "state_board",               # STATE ENGINE (design sec 6.7 / D10), REGISTERED AT S5 AND WRITTEN AT
                                 # S6. THE ONE key for the whole board: `legs: {leg: {outcome, reason,
                                 # reads}}` over EVERY leg the state walk orchestrates, `outcome` the
                                 # closed three-state `fired | declined | not_reached` and `reason` a
                                 # PER-LEG closed enum declared in the producing module (the
                                 # `XL_SUPPRESSED_REASONS` shape). `not_reached` is stamped by the
                                 # ORCHESTRATING walk for every leg it did not enter -- a leg cannot
                                 # stamp its own absence, which is the hole the reading's 4.8 measures
                                 # (`rv_reading_decline` None on 12 of 12 because the leg was never
                                 # REACHED on 10; this sitting re-measured the composer half of that as
                                 # 7 of 12).
                                 #
                                 # IT IS REGISTERED ONE SITTING BEFORE ITS FIRST WRITER, DELIBERATELY
                                 # (doctrine M-8, design 6.7's closing paragraph). Appending here reds
                                 # SEVEN test files' negative-index tail pins, MEASURED by running them
                                 # -- test_cascade_walk.py at TWO sites, test_dhp_episode_select.py,
                                 # test_dhp_binding_verifier.py, test_dmw_eval_instruments.py,
                                 # test_extreme_locator.py, test_orchestrator_telemetry.py and
                                 # test_dhp_handle_grammar.py (the seventh, which the design's own 9.4
                                 # census missed because two of its ten pins are SLICES -- `keys[-22:-17]`
                                 # and `keys[-10:-2]` -- that a grep for `KEYS[-n]` does not report).
                                 # Those re-pins belong in ONE commit with the registration rather than
                                 # spread across the sitting that finally writes the key. [S5 REVIEW]
                                 # TWO keys land in this one commit -- `quantify_xc_fork` above and this
                                 # one -- so those tail pins re-anchor ONCE, BY TWO, exactly as the XL
                                 # pair's own note two entries up describes. Until S6
                                 # writes it the column lifts as
                                 # None on every row, which is the SAME absent-as-None shape every
                                 # registered key has on a turn that does not stamp it; the offline
                                 # harness stamps the key `unregistered`-safe in the meantime.
                                 #
                                 # [S6] THE PAYLOAD IS NOW WRITTEN, and these are its fields --
                                 # `state.board.Board.trace()` is the ONE producer of every one of them:
                                 #   legs        {leg: {outcome, reason, reads}} over the eleven legs of
                                 #               `state.walk.ALL_LEGS` plus `board` itself. `board`'s own
                                 #               reason is the closed `pg_not_live | anchor_none |
                                 #               turn_spend_unknown | recency_facts_off |
                                 #               lane_off:<lane>` set, and the LANES that never reach
                                 #               the walk stamp it from OUTSIDE. TWO PRODUCERS, both
                                 #               calling ONE function:
                                 #                 `answer._state_board_lane_stamp` -- `anchor_none` at
                                 #                 the empty-route return and `lane_off:onehop` at the
                                 #                 one-hop body, the two lanes that DO enter that
                                 #                 module;
                                 #                 `orchestrator._state_board_off_lane_stamp` -- called
                                 #                 from `respond()`'s telemetry wrapper, the one seam
                                 #                 holding both the resolved intent and the trace, for
                                 #                 `numbers_only` / `trivial` / `refused` / `run_live`,
                                 #                 which return from `_respond` without an `answer()`
                                 #                 call at all.
                                 #               THE FIRST S6 BUILD ASSERTED THE SECOND HALF AND WROTE
                                 #               NONE OF IT -- this note and `answer.py`'s said the
                                 #               three lanes were stamped in `respond()` while grep
                                 #               found no such code -- so three of the four declared off
                                 #               lanes were structurally unreachable and 6.7's whole
                                 #               "declined versus never ran" split was open for them.
                                 #               `config_check.check_state_seam` clause (ix) now grades
                                 #               that every declared off lane is reachable from one of
                                 #               the two producers.
                                 #   anchors     the anchor slugs, and `anchor_source` the STRONGEST
                                 #               source word of `state.board.ANCHOR_SOURCES` -- the census
                                 #               column Amendment 2's four-named-markets pin and D26's
                                 #               cold-start count are both read from.
                                 #   net_reads   what the board SPENT, and `cap` what it DECLARED. BOTH
                                 #               are load-bearing at S6 rather than merely reported:
                                 #               `cascade._cw_turn_spent` adds `net_reads` as its SEVENTH
                                 #               enumerated term and `cascade._board_declared_cap` adds
                                 #               `cap` to the walk's own ceiling, so the two halves of D12
                                 #               read ONE key and can never come from two boards. A board
                                 #               that ran with no integer `net_reads` makes the walk
                                 #               decline `turn_spend_unknown` -- ABSENT IS NEVER ZERO, in
                                 #               its strong form.
                                 #   ledger      both wave rectangles (declared / read / deferred /
                                 #               declined / caps) and `rectangle`, the complaint list that
                                 #               is EMPTY when B1 holds on both waves.
                                 #   stage_ms    the two stamped stages separately, so arm A can name the
                                 #               pole per turn beside `timing_ms.fill / rest / numbers`.
                                 #   rank_rule   `d2` or `alternative` (P1), so no census row can be
                                 #               attributed to the tuple that did not produce it.
                                 #   counters    10.5's EMF block as MEASURED, carried here so `respond()`
                                 #               emits what the turn measured rather than re-deriving it
                                 #               from a board it no longer holds.
                                 #   rows / series / horizon_months / mode / asof / notes.
                                 # NO RENDERED LINE AND NO PROMPT BYTE RIDES THIS KEY. The prompt gets
                                 # fired rows and NAMED absences only; the trace gets every candidate's
                                 # tag -- the TRACE/PROMPT separation that answers `_reroute`'s standing
                                 # objection (design 6.7's closing paragraph).
    # ── THE COST CENSUS (lane F, 2026-09-17). THREE KEYS, ONE COMMIT, APPENDED AT THE TAIL per the
    # 12f law -- so the negative-index tail pins across the test files re-anchor ONCE, BY THREE
    # (the `quantify_xc_fork` + `state_board` pair's own note four entries up, same arithmetic).
    #
    # WHAT THEY CLOSE, MEASURED ON THE 2026-09-16 IN-VPC PRE-ARM SMOKE (COST_LATENCY.md sec 0-1):
    # `turn_cost_usd` is not the turn's cost, it is the WRITER's cost. Five smoke turns priced
    # $2.5643 in that column against a PROVEN floor of $3.9251 and a modelled $5.6656 -- so the one
    # $/turn column in the estate under-reports a hybrid turn by 35-55%, and every budget built by
    # scaling it is wrong by that much. The three seats it never saw are exactly these three keys:
    # the NUMBERS AGENT (claude-sonnet-5, 26 rounds over five turns, $1.2985 measured -- the LONG
    # POLE at 46-73% of wall clock and the largest unstamped seat in the estate), the DISPATCH
    # PLANNER (claude-sonnet-4-6, one call per turn, stamped NOWHERE: `_call_opus` tags `_usage` on
    # the reply in `answer._call_opus` and `dispatch._validate` normalises it away), and the DESK
    # REWRITE (claude-opus-5, ALREADY PRICED in `answer._desk_register_lint`, reaching the report
    # panel only). CITED BY SYMBOL AND NOT BY LINE, deliberately: the round-2 review caught both of
    # these as stale line numbers, and between that review and this fix the same two definitions
    # moved AGAIN (12068 -> 13060 -> 12958, 5100 -> 10732 -> 10665) as the other lanes wrote. A line
    # citation into a file six lanes are editing is a comment that is wrong by the time it is read.
    #
    # ALL THREE ARE ABSENT-WHEN-OFF AT THE STAMP, so a flag-off row's three new columns lift as None
    # -- the registry's own absent-as-None contract, identical in shape to `composition_census` on a
    # turn that stamps no census. NOTHING in `src/` writes `numbers_usage` or `plan_usage` unless
    # `GRAPHRAG_COST_CENSUS` is lit (declared in `configs/graphrag/arm_env_base.yaml` under
    # `arm_only`, CONSTANT ACROSS BOTH CELLS so it cannot touch a judged delta), and
    # `desk_register` is written under `GRAPHRAG_DESK_REGISTER` in `answer._desk_register_lint` and
    # nowhere else.
    # NO PROMPT BYTE, NO REQUEST KWARG AND NO RENDERED LINE RIDES ANY OF THE THREE.
    "numbers_usage",             # LANE C stamp, gated by GRAPHRAG_COST_CENSUS: a LIST, one entry per
                                 # numbers-agent round, each {model, in, out, cache_read, cache_write}
                                 # read with the same `getattr(..., 0)` grammar the existing
                                 # `[numbers-thinking]` print uses (in `numbers/agent.answer_numbers`,
                                 # CITED BY SYMBOL because a line number into another lane's file is
                                 # wrong by the time it is read -- round-2 review MAJOR-1). A LIST
                                 # and not a sum, deliberately: the agent's bill is dominated by ONE
                                 # 99,207-token cached prefix re-read once per round, and a per-round
                                 # shape is what makes a COLD write (cache_read == 0 on round 1,
                                 # $0.3720 a time) distinguishable from a warm one -- the single
                                 # cheapest lever found on arm A (~$3, ~9%, by staggering submits).
                                 # It reaches the trace through orchestrator's own guarded copy seam,
                                 # never the unguarded `_sk` tuple: see the `numbers_budget` note there.
    "plan_usage",                # THE DISPATCH PLANNER's tokens, popped at `dispatch.plan_turn` before
                                 # `_validate` drops them, gated by GRAPHRAG_COST_CENSUS. ~$0.012 warm /
                                 # $0.042 cold per turn on a 26,595-char system prompt at sonnet-4-6,
                                 # and 4.0-4.9 s of every turn's wall clock (dead flat across tiers).
                                 # NOT `plan_tokens`, WHICH IS A DIFFERENT QUANTITY AND ALWAYS WILL BE:
                                 # `answer._plan_tokens` counts the SIZE of the WRITER's own popped
                                 # `plan` scratchpad region (this registry's own `plan_tokens` entry
                                 # says so, a few dozen lines above) and was None on all five smoke
                                 # rows. Two keys, two producers, two seats -- never summed.
    "desk_register",             # S7b's REWRITE CENSUS, ALREADY STAMPED AND ALREADY PRICED
                                 # (`answer._desk_register_lint`, under `_desk_register_on()`): {outcome, sentences,
                                 # offered, rewritten, refused{}, hits_before, hits_after, usd,
                                 # over_ceiling, multiline_skipped}. The CHEAPEST entry in this commit --
                                 # one line here puts $0.40 of arm A's spend and the whole S7b remedy
                                 # census into the per-answer row, which until now reached `state_report`
                                 # and NO artifact column, so the arm's own remedy delta could not be
                                 # re-derived from a baseline without re-reading every trace.
                                 # IT IS ALSO THE DISCRIMINATOR `state_report` reads to split the
                                 # mandate's cross-cell lint (a row that carries this key ran under the
                                 # mandate), so registering it makes that split auditable from the
                                 # artifact rather than only from the report's prose.
    # ── THE WRITER SEAM (lane E, 2026-09-17), APPENDED IN THE SAME COMMIT as the three above, so the
    # negative-index tail pins across the test files re-anchor ONCE, BY FOUR rather than twice.
    "writer_seam",               # LANE E's ONE key, stamped identically on BOTH serving bodies
                                 # (`answer._answer_l2` and `answer.answer`) and ABSENT -- never null --
                                 # on any turn that did not run the lane. ITS GATE IS TWO THINGS AT ONCE:
                                 # `GRAPHRAG_STATE_BOARD` lit AND the citation verifier enabled, so on
                                 # the documented `GRAPHRAG_VERIFY=off` rollback the key is absent and
                                 # the lane DID NOT RUN -- never report a zero for it.
                                 # IT RIDES INSIDE ONE DICT, the `escalation_decision` idiom, in the
                                 # order `answer._writer_seam_lints` builds it: `outcome` (closed word:
                                 # ok | bad_shape | lint_failed:<Exc>), `prose_words`, `prose_ceiling`,
                                 # `prose_over_budget`, `superlatives_corrected`, `classes_corrected`,
                                 # `superlatives_seen`, `superlatives_unbound`, `classes_unbound`,
                                 # `superlative_articles_fixed`, `superlatives_negated`,
                                 # `stale_rows_dated`, `stale_sentences`, `lag_windows_checked`,
                                 # `lag_windows_corrected`, `lag_windows_subject_bound`,
                                 # `lag_windows_negated`, `watch_bullets`, `watch_figures_added`,
                                 # `watch_no_figure`, `watch_no_window`, `watch_no_falsifier`,
                                 # `watch_over_ceiling`, `watch_section_seen`, `watch_figures_rounded`,
                                 # `decline_words_corrected`, `metric_labels_corrected`,
                                 # `absence_claims_checked`, `absence_rows_appended`,
                                 # `served_row_duplicate_groups`, `served_rows_duplicated`
                                 # -- THIRTY-ONE fields for ONE column and NO further tail shift, which
                                 # is why the idiom exists. It was EIGHTEEN when this entry was written
                                 # and the enumeration above had gone stale by thirteen: lane E's round 2
                                 # added eleven and its round 3 added `superlatives_negated` and
                                 # `lag_windows_negated`, AND NO KEY MOVED -- which is the whole point of
                                 # the idiom. DO NOT COPY THE COUNT, MEASURE IT: run the seam once and
                                 # read `len(census)`. Measured 2026-09-17 07:12Z, `outcome == "ok"`: 31.
                                 # On a `bad_shape` turn the dict is the FIRST FOUR only (measured), so a
                                 # reader must check `outcome` before reading any counter as a zero.
                                 # `watch_section_seen` is 0/1 and is the PRECONDITION on the other six
                                 # watch fields: 0 means no `## What to watch` section was found, which
                                 # is a different fact from "no defects".
                                 # READ IT AS A DEFECT COUNT, NOT A FEATURE COUNT (lane E's own note):
                                 # `superlatives_corrected = 3` means the writer made three claims its
                                 # OWN cited rows denied. A cell with a LOWER number wrote a better
                                 # page, and a report that says "the lane fixed N things" without
                                 # saying the writer made N errors is reporting the wrong sign.
                                 # IT IS A TREATMENT-ONLY COLUMN AND THE CONTROL HAS NO DENOMINATOR:
                                 # the corrections are made WITH the board's rows, so the control cell
                                 # stamps nothing and there is no cross-cell delta to take. The one
                                 # exception is `prose_words`, computable from ANY cell's served body.
                                 # AND `watch_bullets` HERE IS NOT `state_board.coverage.watch_bullets`:
                                 # lane D's counter reads the whole rendered page, this one reads only
                                 # the `## What to watch` section of the MODEL's `mechanism` field,
                                 # post-verify and pre-splice. MEASURED on the 2026-09-16 smoke: 19
                                 # bullets here against the ten-reads table's 16. TWO COUNTERS OVER ONE
                                 # OBJECT -- never summed, and whichever a report prints, it must name.
    # ── THE LANE-0 STAMPS (09-23 fix round, lane A; CONTRACT C14), APPENDED AT THE TAIL IN ONE COMMIT, so
    # the negative-index tail pins across the test files re-anchor ONCE, BY THREE. THE DEFECT (D7 of the
    # 2026-09-23 re-smoke, CONFIRMED on ten of ten records): commit ee06f19c stamped all three on
    # `sg.trace` and its message said they "ride the re-smoke at zero cost" -- and NONE of the ten
    # per-answer records carried them, because a trace key that is not named HERE reaches no artifact
    # (the C2/U3 class this registry exists to kill, standing in the very commit that claimed to close
    # it). Registration IS the lift; eval.py is not edited. All three are L2-only stamps
    # (`answer._answer_l2`), so a one-hop or numbers-only row lifts them as None -- PRESENT-WITH-NULL,
    # the registry's own shape, never a fabricated zero. CITED BY SYMBOL, NEVER BY LINE.
    "board_n_start",             # the board's first [N] handle (`_board_n_start`), stamped beside
                                 # `state_board` only when the board RAN -- None on every board-off row.
                                 # The seat/board seam figure three recons had to infer from served_rows
                                 # position: handles below it are the numbers seat's, at and above it the
                                 # board's own calls (`quantify` appends them as a contiguous prefix).
    "injected_n",                # [N] rows injected into the writer's grounding ledger (`n_num`, the
                                 # W6.1-0 denominator the orchestrator's EMF already reads off the trace).
    "numbers_block_chars",       # len() of the hybrid numbers block (`extra_context`, orchestrator's
                                 # "SILVER NUMBERS" panel) as the writer received it -- the twin of the
                                 # board's own BoardBlockChars, so a seat-vs-board size is a measurement
                                 # rather than a +/-15% estimate. 0 on a turn that carried no block.
    # ── THE LEDGER / DISPLAY STAMPS (09-24 fix round 2, lane A; CONTRACT K20), APPENDED AT THE TAIL IN ONE
    # COMMIT, IN THIS ORDER, so the negative-index tail pins re-anchor ONCE, BY THREE. THE DEFECT: the three
    # facts every 09-24 [E] and precision finding had to be reconstructed from -- which addresses the ONE
    # evidence ledger issued past the menu (K1), what the writer DECLARED in its own sources ledger before
    # the verifier corrected it, and whether the numbers block the writer copied was stamped at analyst
    # precision (K7) -- reached no artifact. All three are stamped by `answer._answer_l2` ONLY under
    # GRAPHRAG_STATE_BOARD (the ledger key only when the board ran), so a control row lifts them as None --
    # PRESENT-WITH-NULL, the registry's own shape; the flag-off record is HEAD's columns plus three Nones.
    "evidence_ledger",           # `citations.EvidenceLedger.stamp()`: {menu_n, registered, extra_chunks,
                                 # unaddressed} -- menu_n is the [E] rows the MENU numbered, `registered`
                                 # the addresses the board's rows took, `unaddressed` the receipts that
                                 # carried no source_key and so printed no [E] at all.
    "sources_ledger",            # the writer's DECLARED `structured["sources"]`, taken BEFORE the verifier
                                 # corrects it: [{ref, source, date}] only (no snippet), so a
                                 # `ledger_declared_mismatch` can be read against what was declared.
    "numbers_display",           # {"stamped": bool, "calls": n}: whether the turn's number calls carried
                                 # CONTRACT C3's `display: "analyst"` stamp when the footer/seam read them,
                                 # and over how many calls (the orchestrator's seam edit 1 stamps the
                                 # writer's own numbers block the same way under the same flag).
)

# out["intent_decision"][decision_key] -> record[record_column].
DECISION_RECORD_KEYS: tuple[tuple[str, str], ...] = (
    ("response_contract", "response_contract_decision"),   # the DARK selector attribution (A/B tally)
    ("kind_history", "kind_history"),                      # D-AM-1: ordered routing-transition audit
    ("mode", "mode_decision"),                             # D-AM-9: {requested, honored, invalid}, every turn
    # D-XT (2026-08-29), APPENDED AT THE TAIL per the append-never-sort law:
    ("xc_detect", "xc_detect_decision"),                   # THE WHOLE DICT (the response_contract
                                                           # precedent): {tier, llm_consulted,
                                                           # target_span, route_probe?, open_defer?,
                                                           # open_rank?}. orchestrator has stamped this
                                                           # dict on EVERY reasoning/hybrid turn since
                                                           # RV2 W2 and eval.py:1480 hand-lifts ONLY
                                                           # .tier -- everything else reached NO
                                                           # artifact, silently: the exact class this
                                                           # registry exists to kill, standing in its
                                                           # own subject matter. detection_tier at
                                                           # eval.py:1480 is LEFT ALONE (no column
                                                           # shift; banked artifacts stay comparable).
    # D-XL (E33), APPENDED AT THE TAIL, same law and same reason: the WHOLE decision dict
    # {detected, fired, suppressed_reason, kind, board, direction, scope, since, confidence} is lifted
    # into the eval record, so the DISPATCH half of this lane is measurable with NO eval column edit and
    # no column shift -- and the engine-only-key law holds by construction, because the engine's own key
    # is never written on a dispatch decline.
    ("extreme_locator", "extreme_locator_decision"),
    # NUMBERS-SEAT RECON (2026-09-23), APPENDED AT THE TAIL: the one decision field that NAMES the table --
    # dispatch.family_names() (one family per visible card), validated against the live registry and
    # stamped on the decision every turn -- was absent from 1,455 banked per_answer rows. It is the
    # precondition for pricing the deterministic lookup lane: which families a turn asked for, before
    # any seat spent a round on them. eval.py gains the column with no edit (it loops this registry).
    ("data_families", "data_families_decision"),
)


# --- THE COST CENSUS's ONE FLAG READER (lane F, 2026-09-17, round-2 review M1) --------------------
# WHY A FLAG READER LIVES IN THE KEY REGISTRY. Three of the keys above -- `numbers_usage`,
# `plan_usage`, and `desk_register`'s reach into the per-answer record -- exist only while
# `GRAPHRAG_COST_CENSUS` is lit, and round 1 shipped TWO readers of that ONE flag with DIFFERENT
# grammars: `dispatch._cost_census_on` took the strict `on|1|true`, `numbers/agent._cost_census_on`
# also took `yes`. MEASURED, both readers in one process: `GRAPHRAG_COST_CENSUS=yes` read False in
# dispatch and True in the numbers agent -- a HALF-ARMED census that stamps the LARGEST seat ($8.84
# of a $35 arm) while the planner's pop and the judge's usage stay dark, and then prints a "total"
# that looks complete. `arm_env_base.yaml` already records what one spelling mismatch costs:
# `GRAPHRAG_STATE_BOARD=yes` ran a CONTROL turn at treatment price, named and logged as a full
# treatment, and only a post-spend precondition caught it.
# THIS MODULE IS THE ONE PLACE EVERY READER CAN REACH. It is the leaf -- it pulls in nothing from
# this package, so it can never be the near end of a cycle -- and it is already read by answer.py,
# orchestrator.py, planner.py, rankers.py, cascade.py, state/board.py, config_check.py, eval.py and
# dispatch.py. The flag's KEYS are declared here; its GRAMMAR now is too, and a second spelling
# anywhere is a test failure rather than a half-armed arm.
COST_CENSUS_ENV = "GRAPHRAG_COST_CENSUS"


def cost_census_on() -> bool:
    """THE cost-census kill-switch: default OFF, STRICT `on|1|true`.

    The four-of-five board-flag grammar, never `_stats_tool_on`'s fail-safe-ON one. `yes`, `YES`,
    `y`, `enabled` and every other near-miss are FALSE, deliberately: this ships OFF, it gates a
    trace-key change that reaches the serving lane, and a typo must never half-arm a measurement.
    Read at the seam on every call rather than cached, so a deck can set it per case."""
    return str(os.environ.get(COST_CENSUS_ENV) or "").strip().lower() in ("1", "true", "on")


# --- THE SPLAT REGISTRY (09-24, fix round FINAL_2; INTEGRATION O-2) --------------------------------
# THE SECOND IDIOM, REGISTERED HERE AT LAST INSTEAD OF REMEMBERED IN eval.py. `TRACE_RECORD_KEYS` above
# is PRESENT-WITH-NULL: a comprehension over a fixed tuple, so a key registered there is a column on
# every control row of every deck forever, and appending one re-anchors the negative-index tail pins in
# eight decks. The keys below are ABSENT-WHEN-OFF: `eval._per_answer_record` lifts each one VERBATIM
# from `out["trace"]` ONLY on a row whose trace carries it -- never None, never a fabricated zero -- so
# every flag-off artifact keeps `TRACE_RECORD_KEYS`' exact columns in their exact order (B11:
# `TRACE_RECORD_KEYS` is untouched and no tail pin moves), exactly as the hand-written `bridge_query` /
# `chain_lints` splats already do. REGISTRATION IS THE LIFT, as above: eval.py loops this tuple, and
# `eval.splat_census_report` reads the same keys for the arm report. ORDER IS THE COLUMN ORDER --
# append, never sort. LEAF: nothing here imports a producer; each producer is CITED BY SYMBOL.
#
# THE DEFECT IT CLOSES is the C2/U3 silent-lift class once more (INTEGRATION O-2, CLOSE_1 sec 6): the
# three records below were stamped by their producers and reached NO artifact -- above all a REFUSED
# RV pair (two legs whose units or currencies differ, e.g. a EUR/t futures settle against a USD/mt
# Pink Sheet print) was written to `answer_numbers`' own return and read by nobody, so an arm could
# count the spreads it minted and never the ones it refused (THREAT T-3, "refuse and count").
TRACE_SPLAT_KEYS: tuple[str, ...] = (
    "tldr_spine_deduped",        # 09-23 lane A, defect 5 (`answer._dedup_spine_tldr`, stamped on BOTH
                                 # bodies only when the de-dup did something): {sections,
                                 # sentences_removed, sentences_moved} -- the body served twice, corrected.
    "rv_pair_spread",            # the RV pair leg MINTED its row(s) (`numbers.agent.answer_numbers`):
                                 # {legs, markets}. Copied onto the trace by BOTH orchestrator lanes on a
                                 # guarded line of its own; present only where the leg was armed (the
                                 # board-flag kwarg or the dark GRAPHRAG_RV_PAIR_SPREAD) AND the question
                                 # named two markets.
    "rv_pair_uncomputed",        # ...or the leg REFUSED: {markets, reason}, the calculator's own sentence
                                 # (`numbers.agent.RV_PAIR_UNCOMPUTED_KEY`). EXACTLY ONE of the two rides a
                                 # turn whose leg ran, so minted + refused is the leg's own denominator.
    # 09-25 FIX ROUND 3 (lane A, item A-4), APPENDED AT THE TAIL: THE NUMBERS SEAT'S FAILURE. MEASURED on the
    # 09-25 tariff turn (job b372544e): the seat's one round stopped at max_tokens, the agent raised, the
    # hybrid lane swallowed the exception into `{"calls": [], "error": ...}` -- and the message reached NO
    # artifact, so a seat that ran 58 s and returned nothing read exactly like a seat that had nothing to
    # find. ABSENT on every turn whose seat returned (a splat, never a column), so every healthy record keeps
    # its exact columns (B11: `TRACE_RECORD_KEYS` untouched, no tail pin moves).
    "numbers_error",             # {kind, error, ms}: the exception's class name, its message (the swallow's
                                 # own 200 characters) and the seat's own wall time, stamped by
                                 # `orchestrator.run_hybrid` on a guarded line when the seat RAISED or its
                                 # join FAILED (kind = the join's exception, ms None). The spend the seat
                                 # made before it raised rides `numbers_usage` on the same turn, from the
                                 # caller-owned accumulator, wherever the agent declares `usage_sink`.
)
