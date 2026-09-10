# SUBJECT RESOLVER DECK RUN -- subject_heldout_v1.yaml

- generated: 20260910T124534Z
- rows: 110  graph: 99dc11409fe9  artifact: ok
- instrument: LIVE -- per-row vocab_status {'ok': 110} over 110 rows
- layers run: 1
- verdict vocabulary: {LAND-DARK, STOP} -- this deck cannot flip anything

## LAYER 1 -- the deterministic tiers (free)

floors FROZEN: CAND 0.52  AMBIG 0.78  TOP_K 5

| class | n | anyT2 | hit@1 | all-tiers | bar | verdict |
|---|---|---|---|---|---|---|
| synonym | 16 | 13/16 | 9/16 | 14/16 (87.5%) | >= 90% | MISS |
| misspelling | 18 | 18/18 | 15/18 | 18/18 (100.0%) | >= 85% | PASS |
| description | 18 | 15/18 | 14/18 | 16/18 (88.9%) | >= 75% | PASS |
| acronym | 16 | 16/16 | 14/16 | 16/16 (100.0%) | >= 100% | PASS |
| near_duplicate | 12 | 10/12 | 9/12 | 10/12 (83.3%) | - | - |
| multi | 12 | 12/12 | 7/12 | 12/12 (100.0%) | - | - |
| decoy | 18 | cand=12 | carry=0 | - | carry == 0 (FATAL) | PASS |
| ALL non-decoy | 92 | 91.3% | 73.9% | 93.5% | - | - |

lexical baseline, like for like: 30.0% any-hit / 23.3% hit@1 -- the shipped driver matcher over the recon's 30 synonym/misspelling/description phrases (BRIEF.md sec 6; reproduced 2026-09-10)

BARS ARE GRADED ON THE `all-tiers` COLUMN -- T0 exact UNION T1 alias UNION the frozen-floor top-5 -- which is wider than D9's literal 'in the top-5 candidates'. The `anyT2` column beside it is the strict top-5 reading; no bar's verdict differs between the two on either deck.

## BARS

- **MISS** L1 SYNONYM >= 90% -- 14/16 = 87.5% all-tiers
- **PASS** L1 MISSPELLING >= 85% -- 18/18 = 100.0% all-tiers
- **PASS** L1 DESCRIPTION >= 75% -- 16/18 = 88.9% all-tiers
- **PASS** L1 ACRONYM >= 100% -- 16/16 = 100.0% all-tiers
- **PASS** L1 DECOY CARRY (0 at AMBIG_FLOOR, FATAL) -- 0 of 18 decoys carried (12 put a candidate above CAND_FLOOR in front of the planner)

## VERDICT: LAND-DARK

failing bars: L1 SYNONYM >= 90%
