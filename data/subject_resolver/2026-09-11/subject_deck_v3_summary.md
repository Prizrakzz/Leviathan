# SUBJECT RESOLVER DECK RUN -- subject_deck_v3.yaml

- generated: 20260911T103254Z
- rows: 118  graph: 99dc11409fe9  artifact: ok
- instrument: LIVE -- per-row vocab_status {'ok': 118} over 118 rows
- planner block sha256: d7ed2de860fc445fc74cf1a0190b72f32b54f4e5d01550b3fa205d4296ac01f3
- deck rows sha256: 7b079452fa9652362bcebdeba7441f298642dbfe889399d27c59cdf355ca1c86  (file 7f89ac368aeed6462f1feeb93d15f61b226d01f9482f10b1218c979c4914332f)
- layers run: 1, 2
- verdict vocabulary: {LAND-DARK, STOP} -- this deck cannot flip anything

## LAYER 1 -- the deterministic tiers (free)

floors FROZEN: CAND 0.52  AMBIG 0.78  TOP_K 5

| class | n | anyT2 | hit@1 | all-tiers | bar | verdict |
|---|---|---|---|---|---|---|
| exact | 10 | 10/10 | 10/10 | 10/10 (100.0%) | >= 100% | PASS |
| alias | 11 | 10/11 | 7/11 | 11/11 (100.0%) | >= 100% | PASS |
| synonym | 14 | 10/14 | 7/14 | 10/14 (71.4%) | >= 90% | MISS |
| misspelling | 14 | 13/14 | 13/14 | 13/14 (92.9%) | >= 85% | PASS |
| description | 14 | 14/14 | 10/14 | 14/14 (100.0%) | >= 75% | PASS |
| acronym | 10 | 10/10 | 7/10 | 10/10 (100.0%) | >= 100% | PASS |
| near_duplicate | 10 | 10/10 | 6/10 | 10/10 (100.0%) | - | - |
| multi | 8 | 8/8 | 8/8 | 8/8 (100.0%) | - | - |
| decoy | 27 | cand=16 | carry=1 | - | carry == 0 (FATAL) | FATAL |
| ALL non-decoy | 91 | 93.4% | 74.7% | 94.5% | - | - |

lexical baseline, like for like: 30.0% any-hit / 23.3% hit@1 -- the shipped driver matcher over the recon's 30 synonym/misspelling/description phrases (BRIEF.md sec 6; reproduced 2026-09-10)

BARS ARE GRADED ON THE `all-tiers` COLUMN -- T0 exact UNION T1 alias UNION the frozen-floor top-5 -- which is wider than D9's literal 'in the top-5 candidates'. The `anyT2` column beside it is the strict top-5 reading; no bar's verdict differs between the two on either deck.

THE SHIPPED CARRY, beside the bar's raw count: **2 of 5** rows at AMBIG_FLOOR would STOP A READER, and **0 of 1** of the DECOY rows the FATAL bar is stated over. The fence drops 0, the free-tier decline drops 3, and the group key narrows 1. THE BAR ABOVE IS UNMOVED and still grades the RAW count: retargeting a pre-registered bar inside the sitting whose change it grades is how an instrument stops being independent of what it measures. Pointing it at `SubjectHints.ambiguous` plus the seam's rule is a DOCKET item.

## THE LAYER-2 RUNS BANKED ON THIS DECK AND DATE -- 1

| # | file | record sha | stamp | block sha | graph | deck rows | draws x rows = calls | errored | $ | gate |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `subject_deck_v3_layer2_20260911T103254Z.json` | 4e5dbd503ad4 | 20260911T103254Z | d7ed2de860fc | 99dc11409fe9 | 7b079452fa96 | 3 x 118 = 354 | 0 | 3.1552 | HELD |

EACH FILE IS WRITTEN ONCE AND NEVER MERGED INTO, and each carries its own provenance BESIDE the measurement that provenance describes. THIS SUMMARY IS NOT A CERTIFICATE: it is a fixed path per deck per date and it merges, so the header at the top of this report names the LATEST run on this deck and date -- neither the LAYER 1 table above, which is carried forward from whichever run last measured it (its own stamp rides `layer1_generated_utc`, and is printed in the header when it differs), nor the layer 2 in any of the files above. The one-shot gate is graded on a per-run record and refuses this document by its artifact class. THE ATTEMPT COUNT IS THE LENGTH OF THIS LIST.

THE LATEST GATE VERDICT, COPIED FOR A HUMAN READER: **HELD** on `subject_deck_v3_layer2_20260911T103254Z.json` (stamped 20260911T103254Z) -- failing: DECOYS: 0 of 27 fired on ANY draw, and all 27 SCORED. It is a COPY and it names its own file: grade the file, never this line.

## BARS

- **PASS** L1 EXACT >= 100% -- 10/10 = 100.0% all-tiers
- **PASS** L1 ALIAS >= 100% -- 11/11 = 100.0% all-tiers
- **MISS** L1 SYNONYM >= 90% -- 10/14 = 71.4% all-tiers
- **PASS** L1 MISSPELLING >= 85% -- 13/14 = 92.9% all-tiers
- **PASS** L1 DESCRIPTION >= 75% -- 14/14 = 100.0% all-tiers
- **PASS** L1 ACRONYM >= 100% -- 10/10 = 100.0% all-tiers
- **STOP** L1 DECOY CARRY (0 at AMBIG_FLOOR, FATAL) -- 1 of 27 decoys carried (16 put a candidate above CAND_FLOOR in front of the planner)
- **PASS** L2 SYNONYM >= 90% -- 14/14 = 100.0% at >= 2 of 3 draws
- **PASS** L2 MISSPELLING >= 85% -- 14/14 = 100.0% at >= 2 of 3 draws
- **PASS** L2 DESCRIPTION >= 70% -- 14/14 = 100.0% at >= 2 of 3 draws
- **PASS** L2 NEAR_DUPLICATE >= 100% -- 10/10 = 100.0% at >= 2 of 3 draws
- **PASS** L2 MULTI >= 100% -- 8/8 = 100.0% at >= 2 of 3 draws
- **STOP** L2 DECOY PICKS (0 on ANY draw, FATAL) -- 1 of 27 decoy rows had the planner pick a subject on at least one draw; all 27 rows were SCORED
- **PASS** L2 SEAT PIN (temperature and model, read back from every draw) -- temperature observed 0 against a declared 0 (exact); billed model claude-sonnet-4-6 against a declared claude-sonnet-4-6 -- a model FAMILY test: 'claude-sonnet-4-6' must be a SUBSTRING of every billed model id -- a provider prefix or a dated suffix passes, another family does not

## VERDICT: STOP

failing bars: L1 DECOY CARRY (0 at AMBIG_FLOOR, FATAL); L2 DECOY PICKS (0 on ANY draw, FATAL); L1 SYNONYM >= 90%
