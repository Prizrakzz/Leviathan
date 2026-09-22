THE NEGATIVE CORPUS FOR THE CHAIN LINTS -- FIVE REAL SERVED BODIES, 2026-09-16
==============================================================================

WHAT THESE FIVE FILES ARE
-------------------------
The five answer bodies the 2026-09-16 PRE-ARM IN-VPC SMOKE actually served, verbatim, one file per
turn. They were written by the production writer seat on 2026-09-16, MONTHS before the three chain
lints in `answer._chain_lints` existed and against a board that carried no chain block at all, so
not one sentence in them was written for -- or against -- any rule they are used to grade.

    deep_rv_soybeans_state_2026_09_07.md    deep  RV, soybeans, state as of 2026-09-07
    max_rv_soybeans_state_2026_09_07.md     max   RV, soybeans, state as of 2026-09-07
    quick_rv_corn_wheat.md                  quick RV, CBOT corn + CBOT srw wheat
    quick_rv_palm_rapeoil.md                quick RV, Malaysian palm + rapeseed oil
    quick_rv_soyoil_palm.md                 quick RV, CBOT soybean oil + Malaysian palm

WHY THEY ARE BANKED HERE RATHER THAN READ FROM A SCRATCHPAD
-----------------------------------------------------------
Standing memory `feedback_negative_corpus_must_be_unseen_prose`: a fence's negative corpus must be
UNSEEN REAL-SEAT PROSE and never the author's own case list -- the S7b advice cut passed 4,000
hand-built sentences and then deleted readings on the first 149 fresh ones.

Until 2026-09-22 `tests/unit/test_chain_lints.py` read these bodies out of ONE session's temporary
scratchpad and called `pytest.skip` when they were absent. The deck reported GREEN on any machine
that did not have that session's temp directory, with the append-only law, the 10% fire-rate
ceiling, the idempotence pin and the register pin all silently skipped. They are banked here so the
law is graded everywhere and a missing corpus is a RED, never a quiet pass. The precedent is
`data/consequence_leg/xl_golden_seam_off.json`: a served block banked in the repo because a pin that
cannot find its evidence is not a pin.

ORIGIN, AND THE ONE TRANSFORMATION APPLIED
-------------------------------------------
Origin: the 2026-09-16 pre-arm in-VPC smoke, `.../scratchpad/prearm_smoke_0916/answers/*.md`
(the same directory the run's `*.trace.json` sit in; the traces are NOT banked -- the lints read
prose).

The bodies are byte-for-byte the served text with ONE transformation, applied so the corpus is ASCII
on a cp1252 console (standing memory `feedback_windows_console_cp1252`):

    U+2014 EM DASH   -> " -- "     77 occurrences over the five files
    U+2013 EN DASH   -> "-"         1 occurrence  (max_rv_soybeans)
    U+00F1 n-tilde   -> "n"         1 occurrence  (quick_rv_soyoil_palm, "El Nino")

Line endings are LF. Nothing else moved: no sentence, no handle, no digit, no heading, no Q line.

MEASURED, so the transformation is not taken on trust (r2d/A_corpus_delta.py, 2026-09-22): the
shipped pass was run over BOTH corpora on the SIX boards the deck grades -- quick/deep/max soybeans,
max soybean oil, max Malaysian palm and max corn+srw wheat -- 30 note x board cells in all. The
census dict (`corrected`, `chain_hops_unfigured`, `chain_hops_skipped`, `chain_unranked_narrated`,
`chain_hops_ambiguous`, `outcome`), the sentence count before, the sentence count after and the
exact number of characters the page grew are IDENTICAL on all 30 cells, and the six fire rates are
equal to four decimals (0.000 / 1.205 / 1.687 / 1.687 / 0.241 / 0.482 percent).

    src sha256 (served, UTF-8)                  banked sha256 (ASCII, LF)
    c5499e8e27932c75...  deep_rv_soybeans       af871b40c1297939...
    f189620e41e1036f...  max_rv_soybeans        4aa70c2a7cebfb9f...
    4432ca9aaa1c5f7c...  quick_rv_corn_wheat    cde636f4e3a9d2e7...
    cae6fb71d88f6bd5...  quick_rv_palm_rapeoil  509360243b532c02...
    6c2eee9a4bbc2355...  quick_rv_soyoil_palm   8f62fd8619fbad90...

WHO READS THEM
--------------
`tests/unit/test_chain_lints.py` (`_NOTES` / the `notes` fixture): the append-only law, the second-run
idempotence pin, DESIGN's 10% fire-rate ceiling on six cells, the register-cleanliness pin, and the
one-spelling routing of the same five bodies through `state.lint.chain_append_only_report`.

THEY ARE EVIDENCE, NOT INPUT. Nothing regenerates these files; a producer that rewrote them would
destroy exactly the property that makes them worth reading.
