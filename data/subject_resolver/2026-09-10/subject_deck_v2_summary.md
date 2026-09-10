# SUBJECT RESOLVER DECK RUN -- subject_deck_v2.yaml

- generated: 20260910T205950Z
- rows: 118  graph: 99dc11409fe9  artifact: ok
- instrument: LIVE -- per-row vocab_status {'ok': 118} over 118 rows
- layers run: 1, 2
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
| decoy | 28 | cand=17 | carry=1 | - | carry == 0 (FATAL) | FATAL |
| ALL non-decoy | 90 | 93.3% | 75.6% | 94.4% | - | - |

lexical baseline, like for like: 30.0% any-hit / 23.3% hit@1 -- the shipped driver matcher over the recon's 30 synonym/misspelling/description phrases (BRIEF.md sec 6; reproduced 2026-09-10)

BARS ARE GRADED ON THE `all-tiers` COLUMN -- T0 exact UNION T1 alias UNION the frozen-floor top-5 -- which is wider than D9's literal 'in the top-5 candidates'. The `anyT2` column beside it is the strict top-5 reading; no bar's verdict differs between the two on either deck.

THE SHIPPED CARRY, beside the bar's raw count: **2 of 5** rows at AMBIG_FLOOR would STOP A READER, and **0 of 1** of the DECOY rows the FATAL bar is stated over. The fence drops 0, the free-tier decline drops 3, and the group key narrows 1. THE BAR ABOVE IS UNMOVED and still grades the RAW count: retargeting a pre-registered bar inside the sitting whose change it grades is how an instrument stops being independent of what it measures. Pointing it at `SubjectHints.ambiguous` plus the seam's rule is a DOCKET item.

## LAYER 2 -- the planner (billed)

seat claude-sonnet-4-6  temperature 0  max_contracts 2  draws 3  (a row passes at >= 2 of 3)

| class | n | scored | passed (alternatives) | passed (shipped v1) | bar | verdict |
|---|---|---|---|---|---|---|
| exact | 10 | 10 | 10 (100.0%) | 10 (100.0%) | - | - |
| alias | 10 | 10 | 10 (100.0%) | 10 (100.0%) | - | - |
| synonym | 14 | 14 | 14 (100.0%) | 14 (100.0%) | >= 90% | PASS |
| misspelling | 14 | 14 | 14 (100.0%) | 14 (100.0%) | >= 85% | PASS |
| description | 14 | 14 | 14 (100.0%) | 14 (100.0%) | >= 70% | PASS |
| acronym | 10 | 10 | 10 (100.0%) | 10 (100.0%) | - | - |
| near_duplicate | 10 | 10 | 10 (100.0%) | 4 (40.0%) | >= 100% | PASS |
| multi | 8 | 8 | 8 (100.0%) | 5 (62.5%) | >= 100% | PASS |
| decoy | 28 | - | fired=2 | fired=2 | 0 picks on ANY draw (FATAL) | FATAL |
| ALL non-decoy | - | 90 | 90 (100.0%) | 81 (90.0%) | - | - |

THE VERDICT COLUMN IS `alternatives` -- a row's `expect` list names, for each cause the ask carries, the ids that would each be a right answer for it, and the picks must reach EXACTLY the row's concept count among the expected groups (near_duplicate 1, multi 2 unless the deck declares `concepts:`). `shipped v1` is the same draws under phase B's scorer, which read the list as a CONJUNCTION and so asked one pick to carry two group keys at once; the two columns coincide on every class but those two.

calls 354 (errored 0), MEASURED $3.1318 from the usage fields

SEAT PIN, read back from the draws (never only printed): temperature declared 0 / observed 0; seat declared claude-sonnet-4-6 / billed claude-sonnet-4-6 -- PASS

## BARS

- **PASS** L1 EXACT >= 100% -- 10/10 = 100.0% all-tiers
- **PASS** L1 ALIAS >= 100% -- 10/10 = 100.0% all-tiers
- **MISS** L1 SYNONYM >= 90% -- 10/14 = 71.4% all-tiers
- **PASS** L1 MISSPELLING >= 85% -- 13/14 = 92.9% all-tiers
- **PASS** L1 DESCRIPTION >= 75% -- 14/14 = 100.0% all-tiers
- **PASS** L1 ACRONYM >= 100% -- 10/10 = 100.0% all-tiers
- **STOP** L1 DECOY CARRY (0 at AMBIG_FLOOR, FATAL) -- 1 of 28 decoys carried (17 put a candidate above CAND_FLOOR in front of the planner)
- **PASS** L2 SYNONYM >= 90% -- 14/14 = 100.0% at >= 2 of 3 draws
- **PASS** L2 MISSPELLING >= 85% -- 14/14 = 100.0% at >= 2 of 3 draws
- **PASS** L2 DESCRIPTION >= 70% -- 14/14 = 100.0% at >= 2 of 3 draws
- **PASS** L2 NEAR_DUPLICATE >= 100% -- 10/10 = 100.0% at >= 2 of 3 draws
- **PASS** L2 MULTI >= 100% -- 8/8 = 100.0% at >= 2 of 3 draws
- **STOP** L2 DECOY PICKS (0 on ANY draw, FATAL) -- 2 of 28 decoy rows had the planner pick a subject on at least one draw
- **PASS** L2 SEAT PIN (temperature and model, read back from every draw) -- temperature observed 0 against a declared 0; billed model claude-sonnet-4-6 against a declared claude-sonnet-4-6

## VERDICT: STOP

failing bars: L1 DECOY CARRY (0 at AMBIG_FLOOR, FATAL); L1 SYNONYM >= 90%; L2 DECOY PICKS (0 on ANY draw, FATAL)
