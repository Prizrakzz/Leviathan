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
    "composition_census",        # D-CC-1: {entities,n_entities,n_episode_windows,n_evidence}; absent when dark
    "number_handles",            # D-PQ HANDLE-1: {substituted,handles_dropped,sentences_dropped,unresolvable}
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
)

# out["intent_decision"][decision_key] -> record[record_column].
DECISION_RECORD_KEYS: tuple[tuple[str, str], ...] = (
    ("response_contract", "response_contract_decision"),   # the DARK selector attribution (A/B tally)
    ("kind_history", "kind_history"),                      # D-AM-1: ordered routing-transition audit
    ("mode", "mode_decision"),                             # D-AM-9: {requested, honored, invalid}, every turn
)
