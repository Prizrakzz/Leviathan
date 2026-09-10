# SUBJECT RESOLVER DECK RUN -- subject_deck_v1.yaml

- generated: 20260910T124733Z
- rows: 104  graph: 99dc11409fe9  artifact: ok
- instrument: LIVE -- per-row vocab_status {'ok': 104} over 104 rows
- layers run: 1, 2, latency
- verdict vocabulary: {LAND-DARK, STOP} -- this deck cannot flip anything

## LAYER 1 -- the deterministic tiers (free)

floors FROZEN: CAND 0.52  AMBIG 0.78  TOP_K 5

| class | n | anyT2 | hit@1 | all-tiers | bar | verdict |
|---|---|---|---|---|---|---|
| exact | 10 | 10/10 | 10/10 | 10/10 (100.0%) | >= 100% | PASS |
| alias | 10 | 9/10 | 7/10 | 10/10 (100.0%) | >= 100% | PASS |
| synonym | 14 | 10/14 | 7/14 | 10/14 (71.4%) | >= 90% | MISS |
| misspelling | 14 | 13/14 | 13/14 | 13/14 (92.9%) | >= 85% | PASS |
| description | 14 | 14/14 | 10/14 | 14/14 (100.0%) | >= 75% | PASS |
| acronym | 10 | 10/10 | 7/10 | 10/10 (100.0%) | >= 100% | PASS |
| near_duplicate | 10 | 10/10 | 6/10 | 10/10 (100.0%) | - | - |
| multi | 8 | 8/8 | 8/8 | 8/8 (100.0%) | - | - |
| decoy | 14 | cand=7 | carry=0 | - | carry == 0 (FATAL) | PASS |
| ALL non-decoy | 90 | 93.3% | 75.6% | 94.4% | - | - |

lexical baseline, like for like: 30.0% any-hit / 23.3% hit@1 -- the shipped driver matcher over the recon's 30 synonym/misspelling/description phrases (BRIEF.md sec 6; reproduced 2026-09-10)

BARS ARE GRADED ON THE `all-tiers` COLUMN -- T0 exact UNION T1 alias UNION the frozen-floor top-5 -- which is wider than D9's literal 'in the top-5 candidates'. The `anyT2` column beside it is the strict top-5 reading; no bar's verdict differs between the two on either deck.

## LAYER 2 -- the planner (billed)

seat claude-sonnet-4-6  temperature 0  max_contracts 2  draws 3  (a row passes at >= 2 of 3)

| class | n | scored | passed | bar | verdict |
|---|---|---|---|---|---|
| exact | 10 | 10 | 9 (90.0%) | - | - |
| alias | 10 | 10 | 10 (100.0%) | - | - |
| synonym | 14 | 14 | 14 (100.0%) | >= 90% | PASS |
| misspelling | 14 | 14 | 14 (100.0%) | >= 85% | PASS |
| description | 14 | 14 | 13 (92.9%) | >= 70% | PASS |
| acronym | 10 | 10 | 9 (90.0%) | - | - |
| near_duplicate | 10 | 10 | 4 (40.0%) | >= 100% | MISS |
| multi | 8 | 8 | 5 (62.5%) | >= 100% | MISS |
| decoy | 14 | - | fired=2 | 0 picks on ANY draw (FATAL) | FATAL |
| ALL non-decoy | - | 90 | 78 (86.7%) | - | - |

calls 312 (errored 0), MEASURED $2.7889 from the usage fields

SEAT PIN, read back from the draws (never only printed): temperature declared 0 / observed 0; seat declared claude-sonnet-4-6 / billed claude-sonnet-4-6 -- PASS

## D10 -- the latency bar (free)

| population | p50 ms | p90 ms | n |
|---|---|---|---|
| flag_off_turn_embed_ms | 228.72 | 240.53 | 40 |
| flag_on_total_ms | 238.2 | 246.38 | 40 |
| added_wall_per_turn_ms | 9.99 | 17.69 | 40 |
| ms_board_subject_ms | 237.87 | 246.11 | 40 |
| hints_line_ms | 0.24 | 0.39 | 40 |

BAR added_wall_per_turn_ms.p90 <= 150 ms: measured 17.69 ms -- PASS

OFF = the walk's own cold embed of the verbatim query, which the turn pays either way. ON = resolve() (cold, it fills the same _Q_CACHE key) + hints_line() + the walk's now-warm embed. ADDED is the difference and is what D10 budgets. ms_board_subject_ms is the resolver's OWN wall -- the production counter -- and is dominated by that shared embed. THE LANE SPLIT IS STATED AND NOT HIDDEN: these figures are a WALKING lane's. A lane that never walks (numbers_only, trivial) pays ms_board_subject_ms in full and nobody pays it back, which is what resolve(allow_embed=False) is for -- and which the orchestrator cannot decide at this call site, because the lane is plan_turn's own output (D10 addendum A1). The model load and the artifact load are once per process and sit outside every figure here: both are paid on a sentinel phrase first.

## BARS

- **PASS** L2 SYNONYM >= 90% -- 14/14 = 100.0% at >= 2 of 3 draws
- **PASS** L2 MISSPELLING >= 85% -- 14/14 = 100.0% at >= 2 of 3 draws
- **PASS** L2 DESCRIPTION >= 70% -- 13/14 = 92.9% at >= 2 of 3 draws
- **MISS** L2 NEAR_DUPLICATE >= 100% -- 4/10 = 40.0% at >= 2 of 3 draws
- **MISS** L2 MULTI >= 100% -- 5/8 = 62.5% at >= 2 of 3 draws
- **STOP** L2 DECOY PICKS (0 on ANY draw, FATAL) -- 2 of 14 decoy rows had the planner pick a subject on at least one draw
- **PASS** L2 SEAT PIN (temperature and model, read back from every draw) -- temperature observed 0 against a declared 0; billed model claude-sonnet-4-6 against a declared claude-sonnet-4-6
- **PASS** L1 EXACT >= 100% -- 10/10 = 100.0% all-tiers
- **PASS** L1 ALIAS >= 100% -- 10/10 = 100.0% all-tiers
- **MISS** L1 SYNONYM >= 90% -- 10/14 = 71.4% all-tiers
- **PASS** L1 MISSPELLING >= 85% -- 13/14 = 92.9% all-tiers
- **PASS** L1 DESCRIPTION >= 75% -- 14/14 = 100.0% all-tiers
- **PASS** L1 ACRONYM >= 100% -- 10/10 = 100.0% all-tiers
- **PASS** L1 DECOY CARRY (0 at AMBIG_FLOOR, FATAL) -- 0 of 14 decoys carried (7 put a candidate above CAND_FLOOR in front of the planner)
- **PASS** D10 ADDED WALL p90 <= 150 ms -- 17.69 ms added per turn at p90 (the resolver's own wall is 246.11 ms at p90)

## VERDICT: STOP

failing bars: L1 SYNONYM >= 90%; L2 DECOY PICKS (0 on ANY draw, FATAL); L2 MULTI >= 100%; L2 NEAR_DUPLICATE >= 100%
