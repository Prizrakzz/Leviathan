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
)

# out["intent_decision"][decision_key] -> record[record_column].
DECISION_RECORD_KEYS: tuple[tuple[str, str], ...] = (
    ("response_contract", "response_contract_decision"),   # the DARK selector attribution (A/B tally)
    ("kind_history", "kind_history"),                      # D-AM-1: ordered routing-transition audit
    ("mode", "mode_decision"),                             # D-AM-9: {requested, honored, invalid}, every turn
)
