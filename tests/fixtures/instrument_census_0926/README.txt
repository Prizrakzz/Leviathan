THE ARM-A (2026-09-26) PER-ANSWER RECORDS, BOTH CELLS, BANKED FOR tests/unit/test_fix0926s2_lane_i.py (fix
sitting 2, lane I, CONTRACT Y15: the deck-level NON-VACUOUS instrument pin).

ORIGIN: the six baselines of arm A, s3://leviathan-dev-shahem-001/graphrag_evidence/eval/
baseline_eval_queries_state_resmoke_v1_anthropic_20260926T10*.json (image = 9750ae3e), pulled read-only to the
sitting's scratch. ONE FILE PER SOURCE BASELINE, named <cell>_<mode>_<the source's timestamp>.json (short, so
a Windows path stays under MAX_PATH); each carries `source` (the banked file's own S3 key), `source_sha256` (of
the banked file, byte for byte), `cell`, `mode`, `git_commit` and `per_answer`. The CELL is read off the
artefact (TREATMENT when any record carries a non-empty `state_board`), never off a timestamp:
  control    20260926T101143Z deep (6), 20260926T101215Z max (1), 20260926T101613Z quick (3)
  treatment  20260926T101303Z deep (6), 20260926T101610Z max (1), 20260926T101809Z quick (3)

THE REDUCTION (threat I1-b -- the fixture never drifts from the served shape): a record keeps ONLY the keys the
instrument census (src/leviathan/graphrag/eval.py `instrument_census`) reads, and EVERY KEPT VALUE IS VERBATIM
(the banked value's json round-trip, key order kept). Where a container is reduced its entries keep only the
census-read keys, each verbatim:
  top level      id, intent, intent_ok, kind_history, mode_decision, tldr_direction, register_leaks,
                 desk_register, writer_seam, bridge_query, raw_draft, served_rows, state_board
  raw_draft      verified_tldr, verified_mechanism, postverify_tldr, postverify_mechanism, body_pre_sanitize
                 (only the post-verify pair is on these records)
  served_rows[]  table, metric, country, status, row_count, rows[] -> {country, _fold}
  state_board    counters, coverage, chain_counts, analogs, watch_rows, served_counts, retention,
                 numbers_ledger (where present); chains[] -> {rendered, side}; row_states[] -> {side}, kept only
                 where an entry carries `side` (none does at 9750ae3e, so no record keeps row_states)
A key absent on the banked record stays absent -- nothing is filled, nothing is synthetic. No transformation of
prose (the drafts are the banked strings, non-ASCII escaped by json only). One record per line.

The reducer is fix_sitting_2_0926/lane_i/reduce_fixture.py in the sitting's scratch; it asserts, per record,
that every kept top-level value equals the banked value. These records are UNSEEN real-seat pages for every
reader the census gained after they were written (the 09-15 negative-corpus law).
