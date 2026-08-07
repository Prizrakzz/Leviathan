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
)

# out["intent_decision"][decision_key] -> record[record_column].
DECISION_RECORD_KEYS: tuple[tuple[str, str], ...] = (
    ("response_contract", "response_contract_decision"),   # the DARK selector attribution (A/B tally)
    ("kind_history", "kind_history"),                      # D-AM-1: ordered routing-transition audit
    ("mode", "mode_decision"),                             # D-AM-9: {requested, honored, invalid}, every turn
)
