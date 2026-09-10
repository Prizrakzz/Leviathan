# THE OWN-STRUCTURE FENCE, MEASURED -- the billed run the free re-score said it owed

- generated: 20260910T213559Z  deck: subject_deck_v2.yaml  graph: 99dc11409fe9
- seat claude-sonnet-4-6  temperature 0  max_contracts 2  draws 3  (identical to phase C's plan)
- fence: basis, calendar_spread  (state.subject.OWN_STRUCTURE_IDS; live_ids 403 of 405; lint unfenced: none)
- MEASURED $3.1318 over 354 calls, against phase C's $3.119 over the same 354 -- the fence is free.

## PREDICTED (the free re-score, a CEILING) vs MEASURED (this run)

| reading | phase C (no fence) | re-score predicted | phase D MEASURED |
|---|---|---|---|
| decoy ROWS that picked a subject | 7 of 28 | 1 | **2 of 28** (dc18, dc22) |
| decoy DRAWS that picked a subject | 16 of 84 | 3 | **5 of 84** |
| L2 non-decoy rows passed | 89 of 90 (98.9%) | not predicted | **90 of 90 (100.0%)** |
| L1, every class | -- | unchanged by construction | **byte-identical to phase C** |

## THE RE-SCORE WAS RIGHT ABOUT THE FENCE AND ONE ROW SHORT ABOUT THE PLANNER

Five of the six rows the fence was predicted to remove came back CLEAN on every draw -- dc08, dc16,
dc17, dc21, dc25 -- and the sixth, dc22, did not. It picked a fenced id on one draw of phase C and it
picks an UNFENCED cross-market instrument (`wheat_corn_spread`) on two draws of this one: the enum lost
the id the ask was reaching for and the planner reached for the nearest-shaped id still in it. That is
the substitution the re-score's own caveat reserved judgement on ("what a planner does with the shorter
list on those six rows is the next billed run's first obligation"), and it is the finding of this run:
AN ENUM FENCE REMOVES AN ID, NOT AN ASK. A market-structure question with no cause in it still wants an
instrument, and 23 cross-market instruments remain legitimately selectable by design.

dc18 is unchanged and is not a fence question: an open-interest-as-a-market-fact ask answered with
`cot_positioning` + `managed_money_positioning` on 3 of 3 draws, and positioning is subject-eligible by
D18 and by the owner's own scenario. It is a planner judgement, and the bar counts it.

## THE CARRY, MEASURED ON THE SHIPPED PATH

Five rows put a candidate at AMBIG_FLOOR. Two would STOP A READER. The fence drops none of them (no row
on this deck has a fenced-only candidate above the floor, as the constant's docstring predicted from 17
banked layer-1 runs), the FREE-TIER DECLINE drops three -- including the deck's ONE decoy carry, dc23 --
and the group key narrows one from two spellings to one driver. So the shipped decoy carry is 0 of 28
while the pre-registered bar, which grades the RAW count and is deliberately not retargeted inside the
sitting it grades, still reads 1 and still STOPs.

## VERDICT: STOP -- and the held-out one-shot was NOT spent

The gate was stated before the run: the held-out set is spent ONLY on a clean decoy bar. Two decoy rows
fired, so it was not spent and it stays unconsumed for the next sitting. The three paraphrase bars all
hold at layer 2 (synonym 14/14, misspelling 14/14, description 14/14) and L1 SYNONYM still MISSes at
71.4% -- identical to phase C's figure, so it is a standing tier gap and not a phase-D regression.
