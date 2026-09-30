FIVE BANKED LIVE PAGES OF 2026-09-29, EACH A PER-ANSWER RECORD AND ITS PAGE AS SERVED, BANKED FOR
tests/unit/test_fix0929s4_lane_i.py (fix sitting 4, lane I, CONTRACT C4-20 / C4-21: the census rows of the
sitting's classes, the netting parts' names, the banked episode windows).

ORIGIN: the in-VPC smoke of 2026-09-29 (the re-smoke deck, treatment cells; run 1 cold and run 2 warm) and the
research probe of the same day (opus5_plain, the as-of deep page) -- both on tree 596f4452, whose producers are
byte-identical to HEAD 6ba0a87b outside the armed writer lane. Pulled read-only to the sitting's scratch. ONE
FILE PER PAGE:
  probe_deep_cocoa_asof_2026_04      the as-of 2026-04-15 cocoa page (the change row equal to its level, the row
                                     known after the as-of, the event printed with only its [E] receipt)
  smoke1_quick_palm_rapeoil          run 1 quick palm / rapeseed oil (bare-handle date stamps, long card labels,
                                     three threshold citations inside a noun, four markets on the ask head)
  smoke1_quick_corn_wheat            run 1 quick corn / wheat (the stored "(1000 MT)" spelling in prose)
  smoke1_max_soybeans_2026_09_07     run 1 max soybeans (an absence append beside a quorum's unread members)
  smoke2_deep_tariff_soybeans        run 2 deep China tariff (an absence append beside an unmeasured chain hop)
Each file carries `source` (which banked page), `source_sha256` (of the banked per-answer record, byte for byte),
`tree`, `reduction`, `record` (the reduced per-answer record) and `page` (the served body as the report printed
it, its Sources footer included, verbatim).

THE REDUCTION: a record keeps ONLY the keys the census's sitting-4 rows and the netting reader read, EVERY KEPT
VALUE VERBATIM (the banked value's json round-trip):
  top level       id, writer_seam, raw_draft, served_rows, state_board
  served_rows[]   table, metric, country, status, row_count, rows[] -> the call's FIRST row and the first row of
                  each other unit it served (each row verbatim) -- the value and every unit the call carried
  state_board     asof, ask_netting (verbatim); chains[] -> the RENDERED chains only, hops[] -> {driver_id,
                  measured}; block_sentences[] -> the SB-C (quorum) entries only, each verbatim
A key absent on the banked record stays absent -- nothing is filled, nothing is synthetic, no prose is changed.

The reducer is fix_sitting_4_0929/lane_i/reduce_fixture_s4.py in the sitting's scratch; it ASSERTS, per page, that
every sitting-4 row and the netting reading read the same on the reduced record as on the full banked one. These
pages were written AFTER sitting 3's fences and no sitting-4 builder tuned on them (the 09-15 negative-corpus law).
