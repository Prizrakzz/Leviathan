"""PRICE_AND_PLAYBOOKS W1.0 / D4 -- the SINGLE-SOURCE per-contract map for ``silver_futures_eod``.

WHY THIS MODULE EXISTS (the FUTURES v1.5 lesson, generalized)
-------------------------------------------------------------
v1.5 had ONE unit fact living in three places (the transform ``UNIT_MAP``, the numbers card's
``unit_overrides``, and the tracked lint constant) and needed ``config_check.check_futures_lite`` to
bind them three-way so they could never drift. ``silver_futures_eod`` widens that problem hard: 31
slugs, 10 sources in the vocabulary, 9 with slugs (Bursa parked), four
settlement semantics, and TEN currencies -- and the unit vocabulary is no longer a US-exchange list
(EUR/t, CNY/t, MYR/t, ZAR/t, BRL/60-kg bag, CAD/t).

So the map is ``{slug: {unit, currency, settle_kind, source}}`` and it lives in EXACTLY one module.
It is deliberately NOT under ``transforms/raw_to_bronze/<vendor>.py`` (the v1.5 home): W1a/W1b/W1c/W2
land roughly ten producers against this one table, so a per-transform map is by construction not
single-source. Every consumer derives from here:

  * the physical ``unit`` / ``currency`` / ``settle_kind`` / ``source`` columns (the producers must
    read :data:`CONTRACT_MAP` and fail CLOSED on an unmapped slug -- never write a guessed unit);
  * the numbers card's ``metrics.settle.unit_overrides`` (the serving contract);
  * ``config_check._FUTURES_EOD_UNIT_OVERRIDES`` (the tracked lint constant);
  * :func:`lint_frame` -- the ROW-level conditional invariants (contract_month NULL iff
    instrument_kind is cash_index, plus the per-slug unit/currency/settle_kind/source coherence),
    which every producer must pass as ``build_partitioned_publish(row_validator=...)``.

``config_check.check_futures_eod`` binds all three to :data:`UNIT_MAP` (the projection of this map),
so drift in ANY direction fails the build.

DOCTRINE PINNED HERE (plan W1.0, lines 128-141)
-----------------------------------------------
* ``unit`` / ``currency`` are SOURCE-FAITHFUL exchange convention. There is NO FX conversion at
  ingest, ever -- a CNY/t settle stays CNY/t. A currency mutation is a serving/derivation concern.
* ``settle_kind`` is the honesty label riding the row: ``settlement`` (a true exchange settlement),
  ``mark_to_market`` (JSE MTM), ``cash_index`` (a CEPEA cash reference, not a futures contract), or
  ``close`` (a session close standing in for a settlement we did not buy -- the ICE case, where the
  ``statistics`` schema costs $1,960 and is excluded). It is the direct descendant of the W4.2 lint:
  no prose can mislabel the value because the label is ON the row.
* ``source`` is the publication channel, not the vendor's convenience name. It is what makes
  ``settle_kind`` auditable: the cross-tab source -> settle_kind is 1:1 by construction here.

Pure, import-free (stdlib only), AWS-free.
"""
from __future__ import annotations

from datetime import date

# The four settle_kind values the schema permits (plan line 124). ``settlement`` is a true exchange
# settlement price; ``mark_to_market`` is the JSE MTM; ``cash_index`` is a CEPEA cash reference
# (instrument_kind=cash_index, contract_month NULL); ``close`` is an honest stand-in where the
# settlement series was not purchased (ICE via Databento ohlcv-1d).
SETTLE_KINDS: frozenset[str] = frozenset({"settlement", "mark_to_market", "cash_index", "close"})

# DATA REPAIRS 0929 / FUT-2 -- WHAT EACH settle_kind MEANS, as DATA a reader can name the figure from.
# The store already carries settle_kind on every row (580,628 of 580,628, 1:1 with source); what was
# missing is the definition in a place a reader of the TABLE finds it: the generated declaration
# listed the four values and never said that a ``close`` is not a settlement. These definitions are
# the single source: the table declaration's notes are rendered from them by the generator
# (gen_registry_from_baseline.py, the integrator's curation), and the serving label reads the row's
# settle_kind against them (HANDOFF). Asserted complete against SETTLE_KINDS at import.
SETTLE_KIND_DEFINITIONS: dict[str, str] = {
    "settlement": ("the exchange's own daily settlement price for the delivery month, as the venue "
                   "published it (CME/CBOT: the GLBX.MDP3 statistics settlement, stat_type 3; CZCE, "
                   "DCE, MIAX and Euronext/MATIF: the settlement column of the venue's daily file)"),
    "mark_to_market": ("the JSE/SAFEX daily mark-to-market price from the exchange's MTM sheet -- a "
                       "clearing mark, not a traded settlement"),
    "cash_index": ("a CEPEA cash-market reference price (BRL per 60-kg bag) -- not a futures "
                   "contract: instrument_kind cash_index, no delivery month"),
    "close": ("the last-trade CLOSE of the session from the vendor's daily bar (Databento "
              "ohlcv-1d, the on-venue publisher's bar), written into settle because the venue's "
              "settlement series was not purchased -- it is NOT the exchange settlement price and can "
              "differ from it. Every ICE US and ICE Europe row carries it"),
}
assert set(SETTLE_KIND_DEFINITIONS) == SETTLE_KINDS, "SETTLE_KIND_DEFINITIONS must define every settle_kind"

# The ten publication sources (plan line 131). Databento datasets are named by their dataset id so
# `source` alone identifies the exact feed; free-first venues are named by the exchange.
SOURCES: frozenset[str] = frozenset({
    "databento_glbx_mdp3", "databento_ifus_impact", "databento_ifeu_impact",
    "czce", "jse_safex", "cepea", "bursa", "miax", "euronext_matif", "dce",
})

# The unit vocabulary (plan line 141 + the ICE canola CAD leg). Source-faithful strings, never
# normalized: "US cents/bushel" is what CBOT quotes and what the desk reads.
# "USD/bushel" is the MIAX (ex-MGEX) HRSW unit and it is NOT a duplicate of "US cents/bushel": the
# MIAX Public_Daily_Settlement_File CSV publishes DECIMAL DOLLARS per bushel (probed live
# 2026-07-28: MWEU6 settles 7.0250, MWEZ6 7.2525), while CBOT quotes the same grain in CENTS
# (corn ~430). The two differ by a factor of 100. The doctrine here is source-faithful units and
# NEVER a scaled value, exactly as canola widened the vocabulary to CAD/t rather than being FX-ed
# into USD -- so the vocabulary widens and the numbers stay as the venue published them. A
# consumer comparing MGEX to CBOT wheat must convert, and the `unit` column is what tells it to.
# SPELLING: the denominator is spelled OUT ("USD/bushel", not "USD/bu") so the whole vocabulary
# reads one way -- a consumer string-matching on "bushel" must not silently miss HRSW.
UNITS: frozenset[str] = frozenset({
    "US cents/bushel", "US cents/lb", "USD/short ton", "USD/metric ton", "USD/cwt", "USD/bushel",
    "EUR/t", "CNY/t", "MYR/t", "ZAR/t", "BRL/60-kg bag", "CAD/t",
})

# ---------------------------------------------------------------------------
# THE MAP. Keys are the 31 contract slugs (configs/commodities/*.yaml) -- exactly, no more, no
# fewer; check_futures_eod asserts that set equality, which is what makes "31" auditable rather
# than aspirational.
# ---------------------------------------------------------------------------
CONTRACT_MAP: dict[str, dict[str, str]] = {
    # -- CME/CBOT via Databento GLBX.MDP3 (true settlements; history from 2010-06-06) -----------
    "corn_cbot": {"unit": "US cents/bushel", "currency": "USD",
                  "settle_kind": "settlement", "source": "databento_glbx_mdp3"},
    "soybeans_cbot": {"unit": "US cents/bushel", "currency": "USD",
                      "settle_kind": "settlement", "source": "databento_glbx_mdp3"},
    "soft_red_winter_wheat_cbot": {"unit": "US cents/bushel", "currency": "USD",
                                   "settle_kind": "settlement", "source": "databento_glbx_mdp3"},
    # KE (KCBT -> CME migration): GLBX carries it from 2013, usable from 2014 (plan line 545).
    "hard_red_winter_wheat_kcbt": {"unit": "US cents/bushel", "currency": "USD",
                                   "settle_kind": "settlement", "source": "databento_glbx_mdp3"},
    "soybean_oil_cbot": {"unit": "US cents/lb", "currency": "USD",
                         "settle_kind": "settlement", "source": "databento_glbx_mdp3"},
    "soybean_meal_cbot": {"unit": "USD/short ton", "currency": "USD",
                          "settle_kind": "settlement", "source": "databento_glbx_mdp3"},
    "rough_rice_cbot": {"unit": "USD/cwt", "currency": "USD",
                        "settle_kind": "settlement", "source": "databento_glbx_mdp3"},
    # V2-4 (2026-09-02): the CME USD Malaysian Crude Palm Oil Calendar future (Globex CPO, rulebook
    # 204; 25 mt; USD/mt; tick 0.25) via the GLBX.MDP3 statistics schema -- a SETTLEMENT-MARK tape:
    # financially settled to the contract-month average of the Bursa third-forward FCPO settlement
    # at the KL USD/MYR 3:30pm fixing; Globex volume 0, OI in ClearPort swaps. The slug's NAME, its
    # CFTC code 037021 and its hierarchy row (exchange CME) always named this contract; only this
    # price record said Bursa/MYR under the note 'Databento CPO is a dead contract' -- REFUTED by
    # data/batch_runs/cpo_databento_probe_20260902.json. The Bursa MYR FCPO bulletin binding is
    # PARKED (REFUSED venue, zero rows): BURSA_CODE_MAP is EMPTY until a bursa slug is minted
    # (transforms/raw_to_bronze/bursa_fcpo.py). Usable history opens 2016-08-01 (ROOT_FIRST_DATE:
    # the tape has a Jan-Jul 2016 hole and an unverified 24-month regime before it).
    "malaysian_crude_palm_oil_cme": {"unit": "USD/metric ton", "currency": "USD",
                                     "settle_kind": "settlement", "source": "databento_glbx_mdp3"},
    # -- ICE US via Databento IFUS.IMPACT. settle_kind=close, NOT settlement: the ICE `statistics`
    #    schema (the real settlement series) costs $1,696 on IFUS and is EXCLUDED, so `settle` is
    #    the ohlcv-1d session close, labeled honestly (plan line 1652).
    "arabica_coffee": {"unit": "US cents/lb", "currency": "USD",
                       "settle_kind": "close", "source": "databento_ifus_impact"},
    "raw_sugar": {"unit": "US cents/lb", "currency": "USD",
                  "settle_kind": "close", "source": "databento_ifus_impact"},
    "cocoa": {"unit": "USD/metric ton", "currency": "USD",
              "settle_kind": "close", "source": "databento_ifus_impact"},
    "cotton": {"unit": "US cents/lb", "currency": "USD",
               "settle_kind": "close", "source": "databento_ifus_impact"},
    "frozen_orange_juice": {"unit": "US cents/lb", "currency": "USD",
                            "settle_kind": "close", "source": "databento_ifus_impact"},
    # canola lives in IFUS (plan line 552) and is quoted in CANADIAN dollars per tonne. No FX
    # conversion at ingest -- CAD/t is the truthful unit even though it widens the vocabulary
    # past the plan's illustrative list.
    "canola_ice": {"unit": "CAD/t", "currency": "CAD",
                   "settle_kind": "close", "source": "databento_ifus_impact"},
    # -- ICE Europe via Databento IFEU.IMPACT (same close-not-settlement posture; plus the F4
    #    system-priced-leg OHLCV caveat carried on the card).
    "robusta_coffee": {"unit": "USD/metric ton", "currency": "USD",
                       "settle_kind": "close", "source": "databento_ifeu_impact"},
    "white_sugar": {"unit": "USD/metric ton", "currency": "USD",
                    "settle_kind": "close", "source": "databento_ifeu_impact"},
    # -- CZCE (free daily FutureDataDaily.txt; RM = rapeseed MEAL, OI = rapeseed OIL) -----------
    "rapeseed_meal_zce": {"unit": "CNY/t", "currency": "CNY",
                          "settle_kind": "settlement", "source": "czce"},
    "rapeseed_oil_zce": {"unit": "CNY/t", "currency": "CNY",
                         "settle_kind": "settlement", "source": "czce"},
    # -- DCE (browser producer, W1c Option A; the /dcereport JSON API carries settlePrice) ------
    "palm_olein_dce": {"unit": "CNY/t", "currency": "CNY",
                       "settle_kind": "settlement", "source": "dce"},
    "soybean_meal_dce": {"unit": "CNY/t", "currency": "CNY",
                         "settle_kind": "settlement", "source": "dce"},
    "soybean_oil_dce": {"unit": "CNY/t", "currency": "CNY",
                        "settle_kind": "settlement", "source": "dce"},
    "soybeans_no_1_dce": {"unit": "CNY/t", "currency": "CNY",
                          "settle_kind": "settlement", "source": "dce"},
    "soybeans_no_2_dce": {"unit": "CNY/t", "currency": "CNY",
                          "settle_kind": "settlement", "source": "dce"},
    # -- JSE / SAFEX: the published number is a MARK-TO-MARKET, not a settlement (plan line 258).
    "south_african_white_maize_jse": {"unit": "ZAR/t", "currency": "ZAR",
                                      "settle_kind": "mark_to_market", "source": "jse_safex"},
    "south_african_yellow_maize_jse": {"unit": "ZAR/t", "currency": "ZAR",
                                       "settle_kind": "mark_to_market", "source": "jse_safex"},
    # -- CEPEA: the two CASH references. instrument_kind=cash_index, contract_month NULL -- these
    #    are the ONLY rows for which a null delivery month is legal rather than a defect.
    "brazilian_arabica_coffee": {"unit": "BRL/60-kg bag", "currency": "BRL",
                                 "settle_kind": "cash_index", "source": "cepea"},
    "campinas_corn_reference_bmf": {"unit": "BRL/60-kg bag", "currency": "BRL",
                                    "settle_kind": "cash_index", "source": "cepea"},
    # -- Bursa Malaysia FCPO daily settlement bulletin (W1b): NO slug while PARKED. The palm slug
    #    carried this binding (MYR/t) until V2-4 re-keyed it to the CME USD tape above; the venue
    #    is REFUSED (S2) and armed nowhere, and a bursa slug is a CONTRACT_MAP + configs/commodities
    #    decision (docket). 'bursa' stays in SOURCES so the parked parser keeps its vocabulary.
    # -- MIAX Futures (ex-MGEX) daily settlement file (W1b; absent from Databento entirely) -----
    #    UNIT CORRECTED 2026-07-29 from "US cents/bushel" to "USD/bushel" against the live file: the
    #    CSV publishes decimal DOLLARS/bushel (MWEU6 = 7.0250), not cents. The value is NEVER
    #    scaled to match a prior guess -- the label moves to the data. See the UNITS note above.
    "hard_red_spring_wheat_mgex": {"unit": "USD/bushel", "currency": "USD",
                                   "settle_kind": "settlement", "source": "miax"},
    # -- Euronext / MATIF (W1c browser producer; the SETTL. column after the ~18:30 CET publish) -
    "french_wheat_matif": {"unit": "EUR/t", "currency": "EUR",
                           "settle_kind": "settlement", "source": "euronext_matif"},
    "french_maize_matif": {"unit": "EUR/t", "currency": "EUR",
                           "settle_kind": "settlement", "source": "euronext_matif"},
    "french_rapeseed_matif": {"unit": "EUR/t", "currency": "EUR",
                              "settle_kind": "settlement", "source": "euronext_matif"},
}

# ---------------------------------------------------------------------------
# THE COLUMN SHAPE. One table, ~ten producers -- so the column lists live HERE, next to the map,
# and NOT in any one vendor's transform module. They were born in
# ``transforms/bronze_to_silver/databento_eod.py`` (W2, the only leg that existed then) and
# ``futures_eod_task.merge_with_canonical`` imported them from there; every free leg would have
# inherited an import of the Databento module for a list that is not Databento's. Moved verbatim --
# the values are unchanged and that module re-exports these names.
# ---------------------------------------------------------------------------
# The F010 contract's physical column order, verbatim from configs/silver/tables/
# silver_futures_eod.yaml (declaration order IS writer order under the INV-2 pinned schema).
PHYSICAL_COLUMNS: list[str] = [
    "trade_date", "contract_month", "instrument_kind", "raw_symbol", "settle", "settle_kind",
    "open", "high", "low", "close", "volume", "open_interest", "unit", "currency",
    "expiry_date", "source", "dataset",
]
# The two registered partition keys, in the contract's declared ORDER (Glue keys partitions
# positionally, so a transposed pair is silent at write time and unrecoverable afterwards).
PARTITION_COLUMNS: list[str] = ["leviathan_slug", "trade_year"]
SILVER_COLUMNS: list[str] = PHYSICAL_COLUMNS + PARTITION_COLUMNS

# The card projection: the numbers card's unit_overrides is dict[slug, str], the map is richer, so
# the bind is a PROJECTION equality (not a dict equality). Derived here so the card, the lint
# constant and the physical column can only ever disagree by failing check_futures_eod.
UNIT_MAP: dict[str, str] = {slug: rec["unit"] for slug, rec in CONTRACT_MAP.items()}

# The cash references -- the ONLY slugs whose rows may carry contract_month IS NULL (the
# instrument_kind discriminator, plan line 121). Producers assert this both ways.
CASH_INDEX_SLUGS: frozenset[str] = frozenset(
    slug for slug, rec in CONTRACT_MAP.items() if rec["settle_kind"] == "cash_index"
)

# ---------------------------------------------------------------------------
# W2b-D2 -- PRICE_COVERAGE_START: the per-contract floor of silver_futures_eod.
#
# MEASURED FROM THE CANONICAL BYTES on 2026-07-30 (min(trade_date) per leviathan_slug over the
# registered partitions), NOT copied from the plan's per-source prose -- and measuring caught two
# errors that prose would have shipped:
#   * the plan gives GLBX a blanket 2010-06-06, but hard_red_winter_wheat_kcbt actually begins
#     2014-01-02 (KCBT joined GLBX later). A blanket floor would have claimed 3.5 years of coverage
#     that does not exist -- the exact shape of the CEPEA nine-year hole.
#   * the ICE floor is 2018-12-24, not the plan's 2018-12-23; rough_rice_cbot is 2010-06-07, a day
#     after its GLBX siblings.
# Regenerate after any backfill that extends history by MEASURING the canonical bytes: per slug,
# MIN(trade_date) WHERE settle IS NOT NULL over the registered partitions (Athena or the pg
# mirror) -- the scratchpad/measure_coverage_floors.py this comment once named is not in the tree.
#
# V2-4 (2026-09-02 / 2026-09-03): malaysian_crude_palm_oil_cme's floor is the ONE entry in this map
# that is NOT yet measured from canonical bytes. It carries the root's own first usable date as a
# PROVISIONAL literal so the walk-side commit is atomic (check_cascade_walk clause (i) errors in
# BOTH directions -- a board label with no floor is a stale row, a floor with no label is a missing
# entry -- so the floor, the label and the tenor rule land together or not at all). The doctrine
# above is NOT relaxed: the literal must be RE-ANCHORED to the D9-measured first settle-bearing
# trade date before any serving rev is built from it, and the direction of the provisional error is
# fenced by a pin (the literal can never sit EARLIER than ROOT_FIRST_DATE['CPO'], which is the
# earliest date the fetch can even request), so a wrong provisional can only under-claim coverage.
# Until an image is built from this commit the entry is inert on serving: the live rev declines
# palm before any coverage read.
#
# FLIP CHECKLIST (review m3, 2026-09-03): the serving rev must not be registered until this literal
# equals the D9-measured MIN(trade_date) WHERE settle IS NOT NULL. This is a HARD gate on the flip,
# not a docket -- the pin in tests/unit/test_price_coverage.py fences only the DIRECTION of the
# provisional error (>= ROOT_FIRST_DATE['CPO'], so it can only under-claim), and no test can tell a
# provisional literal from a measured one. Nothing new is pinned here on purpose: the measurement
# lives in D9, and a second pin restating 2016-08-01 would have to be edited by the same hand that
# re-anchors the literal, which is exactly the check that would then not be checking anything.
#
# WHAT READS THIS (W2b-D3/D4): the coverage-aware decline guard and the event-study floor. The
# routing rule is deterministic -- a window entirely >= the floor serves from silver_futures_eod;
# entirely before it serves a LEVEL from the legacy continuous card with an explicit provenance
# sentence; STRADDLING declines rather than silently splicing two different series.
#
# ABSENT slug == NOT SERVED: a slug with no entry has no per-contract record at all (the DCE and
# Bursa browser venues are absent because their canonical data has not landed). Callers must treat
# a missing key as "no coverage", never as "covered since forever" -- coverage_start_for() below
# fails closed so that distinction cannot be fudged.
#
# D-PR-24 (2026-08-05) -- THE MATIF LEG WAS ARMED. Probe S3 resolved the SETTL. semantics (three
# captures, 08-04/08-05: intra-session the column shows the PRIOR completed settlement and the +/-
# computes against it; it rolls to the finished session's own settlement at the ~18:30 Paris evening
# publication, so the 22:30Z capture is same-day -- no T-1 risk). The euronext capture+silver legs
# ride futures_eod_free; the arm declaration, the probe record and the delisting runbook live at
# configs/silver/dags/unarmed/futures_eod_browser.json, pinned by
# tests/unit/silver/test_matif_arm_declaration.py.
#
# D-PR-24 THE ANSWER FLIP (2026-08-20) -- THE SECOND GATE IS NOW DISCHARGED TOO. The arm and the
# flip were deliberately separable: rows landing in silver never moved an answer by themselves,
# because a slug absent from this dict declines before any SQL compiles. The flip is executed by
# OWNER WORD ("what's stopping us from flipping it already?") after TWO CLEAN WEEKS of nightly
# fires -- MEASURED on the canonical bytes 2026-08-20: french_wheat_matif 108 rows,
# french_maize_matif 90, french_rapeseed_matif 90, trade_dates CONTINUOUS 2026-08-06 .. 2026-08-19,
# zero red fires on the leg. The floor is the FIRST BANKED TRADE DATE (2026-08-06), measured, not
# the arm date and not the first capture: the 2026-07-29 orphan captures were never promoted to
# canonical, so claiming them would be the CEPEA nine-year-hole shape in miniature.
# WHAT THE FLOOR BUYS AND WHAT IT DOES NOT: a window on or after 2026-08-06 now SERVES the
# per-delivery-month curve; a window entirely before it routes 'legacy', and because MATIF is not
# one of the continuous card's 12 unit_overrides that becomes 'uncovered' -- an honest decline that
# NAMES the floor instead of raising; a window straddling 2026-08-06 DECLINES as a straddle. The
# rapeseed_meal_zce / JSE precedent (a floor with no legacy lane) is the shape being followed.
# ---------------------------------------------------------------------------
PRICE_COVERAGE_START: dict[str, date] = {
    "arabica_coffee": date(2018, 12, 24),                 # databento_ifus_impact
    "brazilian_arabica_coffee": date(1996, 9, 2),         # cepea
    "campinas_corn_reference_bmf": date(2004, 8, 2),      # cepea
    "canola_ice": date(2018, 12, 24),                     # databento_ifus_impact
    "cocoa": date(2018, 12, 24),                          # databento_ifus_impact
    "corn_cbot": date(2010, 6, 6),                        # databento_glbx_mdp3
    "cotton": date(2018, 12, 24),                         # databento_ifus_impact
    # euronext_matif -- armed 2026-08-05 by owner word; ANSWER FLIP executed 2026-08-20 by owner
    # word after two clean weeks (108 / 90 / 90 rows measured, trade_dates 2026-08-06..2026-08-19
    # continuous, zero red fires). Floor = the FIRST BANKED TRADE DATE, not the arm date.
    "french_maize_matif": date(2026, 8, 6),               # euronext_matif
    "french_rapeseed_matif": date(2026, 8, 6),            # euronext_matif
    "french_wheat_matif": date(2026, 8, 6),               # euronext_matif
    "frozen_orange_juice": date(2018, 12, 24),            # databento_ifus_impact
    "hard_red_spring_wheat_mgex": date(2025, 9, 9),       # miax
    "hard_red_winter_wheat_kcbt": date(2014, 1, 2),       # databento_glbx_mdp3
    # PROVISIONAL = ROOT_FIRST_DATE; re-anchor to the D9-measured first settle before the serving rev
    "malaysian_crude_palm_oil_cme": date(2016, 8, 1),     # databento_glbx_mdp3
    "rapeseed_meal_zce": date(2015, 10, 8),               # czce
    "rapeseed_oil_zce": date(2015, 10, 8),                # czce
    "raw_sugar": date(2018, 12, 24),                      # databento_ifus_impact
    "robusta_coffee": date(2018, 12, 24),                 # databento_ifeu_impact
    "rough_rice_cbot": date(2010, 6, 7),                  # databento_glbx_mdp3
    "soft_red_winter_wheat_cbot": date(2010, 6, 6),       # databento_glbx_mdp3
    "south_african_white_maize_jse": date(2026, 7, 29),   # jse_safex
    "south_african_yellow_maize_jse": date(2026, 7, 29),  # jse_safex
    "soybean_meal_cbot": date(2010, 6, 6),                # databento_glbx_mdp3
    "soybean_oil_cbot": date(2010, 6, 6),                 # databento_glbx_mdp3
    "soybeans_cbot": date(2010, 6, 6),                    # databento_glbx_mdp3
    "white_sugar": date(2018, 12, 24),                    # databento_ifeu_impact
}


def coverage_start_for(slug: str) -> date:
    """The first date ``slug`` has a per-contract price record. FAIL CLOSED on an unmapped slug.

    Never returns a permissive default: an unknown slug raises rather than implying coverage, so a
    caller cannot accidentally serve a curve for a venue whose data has not landed."""
    got = PRICE_COVERAGE_START.get(slug)
    if got is None:
        raise ValueError(
            f"leviathan_slug {slug!r} has no PRICE_COVERAGE_START entry -- it has no per-contract "
            f"price record in silver_futures_eod. Do NOT infer coverage; land the data and "
            f"regenerate the map (scratchpad/measure_coverage_floors.py)"
        )
    return got


def covers(slug: str, start, end) -> str:
    """Route one date window against the coverage floor (W2b-D3), as one of three verdicts.

    ``"serve"``   -- the whole window is at or after the floor: silver_futures_eod answers it.
    ``"legacy"``  -- the whole window predates the floor: only a LEVEL from the roll-spliced
                     continuous card is honest, and it must carry the provenance sentence.
    ``"straddle"`` -- the window crosses the floor: DECLINE. Splicing a per-contract series onto a
                     roll-spliced continuous one produces a number that means neither thing, which
                     is why the plan bans it by lint rather than leaving it to judgement."""
    floor = coverage_start_for(slug)
    lo, hi = (start.date() if hasattr(start, "date") else start), (end.date() if hasattr(end, "date") else end)
    if lo >= floor:
        return "serve"
    if hi < floor:
        return "legacy"
    return "straddle"


_REQUIRED_FIELDS = ("unit", "currency", "settle_kind", "source")


def contract_for(slug: str) -> dict[str, str]:
    """The per-contract record for ``slug``. FAIL CLOSED -- an unmapped slug is never guessed.

    This is the accessor every producer must use to populate the physical unit / currency /
    settle_kind / source columns (mirrors the fail-closed
    ``transforms/bronze_to_silver/yfinance_futures.py`` UNIT_MAP lookup)."""
    rec = CONTRACT_MAP.get(slug)
    if rec is None:
        raise ValueError(
            f"leviathan_slug {slug!r} is missing from CONTRACT_MAP "
            f"(src/leviathan/silver/futures_eod_contracts.py) -- add the curated "
            f"unit/currency/settle_kind/source record; never write a guessed unit"
        )
    return dict(rec)


def lint_map() -> list[str]:
    """Structural problems with :data:`CONTRACT_MAP` (pure; the lint + an import-time assertion).

    Vocabulary-only: slug-set completeness against ``configs/commodities/`` is asserted by
    ``config_check.check_futures_eod``, which is where the repo's config surface lives."""
    errs: list[str] = []
    for slug in sorted(CONTRACT_MAP):
        rec = CONTRACT_MAP[slug]
        missing = [f for f in _REQUIRED_FIELDS if not (rec.get(f) or "").strip()]
        if missing:
            errs.append(f"{slug}: missing/blank field(s) {missing}")
            continue
        extra = sorted(set(rec) - set(_REQUIRED_FIELDS))
        if extra:
            errs.append(f"{slug}: unexpected field(s) {extra}")
        if rec["settle_kind"] not in SETTLE_KINDS:
            errs.append(f"{slug}: settle_kind {rec['settle_kind']!r} not in {sorted(SETTLE_KINDS)}")
        if rec["source"] not in SOURCES:
            errs.append(f"{slug}: source {rec['source']!r} not in {sorted(SOURCES)}")
        if rec["unit"] not in UNITS:
            errs.append(f"{slug}: unit {rec['unit']!r} not in the curated vocabulary {sorted(UNITS)}")
        cur = rec["currency"]
        if not (cur.isupper() and cur.isalpha() and len(cur) == 3):
            errs.append(f"{slug}: currency {cur!r} is not a 3-letter uppercase ISO-4217 code")
    return errs


# Import-time fail-closed: a malformed map must never reach a producer (the UNIT_MAP ==
# TICKER_MAP assertion precedent in transforms/raw_to_bronze/yfinance_futures.py).
assert not lint_map(), "futures_eod_contracts.CONTRACT_MAP is malformed: " + "; ".join(lint_map())


def _is_blank(val) -> bool:
    """None / NaN / NaT / pandas NA / whitespace-only -- WITHOUT importing pandas.

    NaN and NaT are the only values unequal to themselves; ``pandas.NA`` raises on ``bool()``
    instead of answering, and an unusable partition/label value either way. Mirrors
    ``leviathan.silver.partitioned_producer._is_null`` (duplicated rather than imported: that
    module pulls in pyarrow, and this one is deliberately stdlib-only)."""
    if val is None:
        return True
    try:
        if bool(val != val):
            return True
    except (TypeError, ValueError):  # noqa: BLE001 -- pandas.NA truth value is ambiguous
        return True
    return isinstance(val, str) and not val.strip()


_FRAME_REQUIRED_COLS = ("leviathan_slug", "instrument_kind", "contract_month",
                        "unit", "currency", "settle_kind", "source")
INSTRUMENT_KINDS: frozenset[str] = frozenset({"futures", "cash_index"})


def lint_frame(df) -> list[str]:
    """The CONDITIONAL invariants a producer frame must satisfy -- the ``required_nonnull_when``
    the F010 contract schema cannot express. Pure; duck-typed on the DataFrame like ``flat_producer``.

    Pass this as ``build_partitioned_publish(row_validator=...)``; every ``silver_futures_eod``
    producer MUST, and this is the ONLY place the rules live.

      1. ``contract_month IS NULL`` **if and only if** ``instrument_kind == 'cash_index'``. This is
         the whole load-bearing claim of the plan's discriminator (line 121): the delivery month is
         part of the natural key ``[leviathan_slug, contract_month, trade_date]``, so a futures
         producer that simply DROPS the month writes N rows that collapse to ONE key -- and the
         source-contract ``duplicate_check: full`` cannot see it, because SQL treats each NULL as a
         distinct value. Declaring ``contract_month`` merely ``nullable: true`` makes that legal.
      2. ``instrument_kind == 'cash_index'`` **if and only if** the slug is in
         :data:`CASH_INDEX_SLUGS` (the two CEPEA cash references, derived from the map).
      3. every slug is mapped, and its ``unit`` / ``currency`` / ``settle_kind`` / ``source`` equal
         :data:`CONTRACT_MAP` verbatim -- the row-level end of the three-way unit bind, so a
         producer cannot write a guessed unit past a green ``config_check``.
      4. ``instrument_kind`` is in :data:`INSTRUMENT_KINDS`.

    Set-based, so cost is one pass per column and the output is bounded by the 31-slug map however
    many millions of rows a backfill carries."""
    errs: list[str] = []
    cols = getattr(df, "columns", [])
    missing = [c for c in _FRAME_REQUIRED_COLS if c not in cols]
    if missing:
        return [f"frame is missing required column(s) {missing}"]
    if len(df) == 0:
        return errs
    slugs = list(df["leviathan_slug"])
    kinds = list(df["instrument_kind"])
    months = list(df["contract_month"])

    unknown = sorted({s for s in slugs if s not in CONTRACT_MAP})
    if unknown:
        errs.append(f"unmapped leviathan_slug(s) {unknown} -- add the curated CONTRACT_MAP record; "
                    f"never write a guessed unit")
    bad_kinds = sorted({k for k in kinds if k not in INSTRUMENT_KINDS})
    if bad_kinds:
        errs.append(f"instrument_kind vocabulary drift {bad_kinds} (legal: {sorted(INSTRUMENT_KINDS)})")

    # (1) the conditional-nullability invariant, both directions. At most 4 distinct combinations.
    for kind, is_null in sorted({(k, _is_blank(m)) for k, m in zip(kinds, months)}):
        if kind == "cash_index" and not is_null:
            errs.append("instrument_kind='cash_index' rows carry a NON-NULL contract_month -- a cash "
                        "reference has no delivery month")
        elif kind != "cash_index" and is_null:
            errs.append(f"instrument_kind={kind!r} rows carry a NULL contract_month -- the delivery "
                        f"month is part of the natural key, so N such rows collapse to ONE key and "
                        f"duplicate_check cannot see it (NULL != NULL)")

    # (2)+(3) per-slug coherence. Bounded by the 31-slug map.
    for slug, kind in sorted({(s, k) for s, k in zip(slugs, kinds) if s in CONTRACT_MAP}):
        want_kind = "cash_index" if slug in CASH_INDEX_SLUGS else "futures"
        if kind != want_kind:
            errs.append(f"{slug}: instrument_kind {kind!r} != {want_kind!r} (the map's settle_kind "
                        f"decides which slugs are cash references)")
    seen = {(s, u, c, k, src) for s, u, c, k, src in
            zip(slugs, df["unit"], df["currency"], df["settle_kind"], df["source"])
            if s in CONTRACT_MAP}
    for slug, unit, currency, settle_kind, source in sorted(seen):
        rec = CONTRACT_MAP[slug]
        got = {"unit": unit, "currency": currency, "settle_kind": settle_kind, "source": source}
        drift = {f: (got[f], rec[f]) for f in _REQUIRED_FIELDS if got[f] != rec[f]}
        if drift:
            errs.append(f"{slug}: row values {sorted(drift.items())} (got, expected) do not match "
                        f"CONTRACT_MAP -- unit/currency/settle_kind/source are map-derived, never "
                        f"source-parsed")
    return errs


# ---------------------------------------------------------------------------
# DATA REPAIRS 0929 / FUT-1 -- THE PRICE DOMAIN, DECLARED PER CONTRACT, AND THE GUARD AT THE WRITE.
#
# THE DEFECT, MEASURED ON THE CANONICAL BYTES (read-only copy of 2026-09-29, 580,628 rows, 26 slugs):
# 462 rows carried a 0 in settle / open / high / low / close -- 219 of them a settle of 0.0 -- every
# one on IFUS.IMPACT (arabica 170, cotton 98, raw sugar 83, cocoa 66, FCOJ 39, canola 6), in 43
# (leviathan_slug, trade_year) partitions; not one price below zero anywhere. All five 2026 cocoa
# deliveries on 2026-01-12 read open > 0, high > 0, low 0, close 0, settle 0 on real volume, and a
# served 63-session change on July-2026 cocoa read "+3,630, rising" for a contract that fell ~1,841.
#
# WHERE IT ENTERS: the vendor's ohlcv-1d bar carries a fixed-point 0 (NOT the UNDEF sentinel);
# ``raw_to_bronze.databento_eod.scale_fixed_price`` masks only UNDEF, so 0 -> 0.0; ``apply_ice_settle``
# copies the 0.0 close into ``settle``; ``bronze_to_silver`` passes it through; ``lint_frame`` has no
# positivity rule. The one guard that existed (``build_settlement_bronze``) nulls <= 0 marks on the
# CPO settlement tape only. Whether the 0 is the on-venue bar's own value or a degenerate bar the
# ICE double-bar rule kept is NOT provable from silver; ``probe_nonpositive_bars`` in the raw ->
# bronze module now measures it on the next run from raw (a count, never a rule).
#
# THE RULE (a fact per contract, never a slug list and never an inference from the unit): every
# contract DECLARES its price domain here, and the declaration is asserted COMPLETE against
# CONTRACT_MAP at import (a slug with no domain fails closed). A value of settle / open / high /
# low / close that is not finite, or lies outside its contract's domain, is stored as NaN WITH A
# REASON -- the row, its volume and its open interest stay (a zero volume and a zero open interest
# are real: 3,785 and 1,406 rows of them; neither column is ever touched). The guard runs at the ONE
# write seam (``jobs/batch/futures_eod_task.py`` publish) on the frame being written, i.e. AFTER
# ``merge_with_canonical``, so a canonical prior carrying a zero is repaired by the same pass.
#
# THE DOMAINS: ``positive`` = finite and > 0 (every exchange-listed outright on a physical commodity
# and both CEPEA cash references in this map: 0 of 580,628 stored rows is below zero, and a 0 has
# only ever been a non-price); ``signed`` = any finite value, for a contract whose price can
# legitimately print at or below zero (none today; the vocabulary exists so a declaration, not this
# code, decides -- a deck pins that a ``signed`` contract keeps a negative settle).
#
# The domain is kept OUTSIDE the CONTRACT_MAP records on purpose: lint_map refuses any extra field
# in a record and config_check binds the records by name, so a sibling declaration moves neither.
# ---------------------------------------------------------------------------
PRICE_COLUMNS: tuple[str, ...] = ("settle", "open", "high", "low", "close")
PRICE_DOMAINS: frozenset[str] = frozenset({"positive", "signed"})
PRICE_DOMAIN: dict[str, str] = {
    # CME / CBOT via GLBX.MDP3 (exchange settlements; the CPO settlement tape nulls its own 0 marks
    # upstream as well -- deepest-month placeholders, build_settlement_bronze)
    "corn_cbot": "positive",
    "soybeans_cbot": "positive",
    "soft_red_winter_wheat_cbot": "positive",
    "hard_red_winter_wheat_kcbt": "positive",
    "soybean_oil_cbot": "positive",
    "soybean_meal_cbot": "positive",
    "rough_rice_cbot": "positive",
    "malaysian_crude_palm_oil_cme": "positive",
    # ICE US / ICE Europe via Databento (session closes, settle_kind=close)
    "arabica_coffee": "positive",
    "raw_sugar": "positive",
    "cocoa": "positive",
    "cotton": "positive",
    "frozen_orange_juice": "positive",
    "canola_ice": "positive",
    "robusta_coffee": "positive",
    "white_sugar": "positive",
    # CZCE, DCE, JSE/SAFEX, MIAX, Euronext/MATIF (exchange settlements / MTM)
    "rapeseed_meal_zce": "positive",
    "rapeseed_oil_zce": "positive",
    "palm_olein_dce": "positive",
    "soybean_meal_dce": "positive",
    "soybean_oil_dce": "positive",
    "soybeans_no_1_dce": "positive",
    "soybeans_no_2_dce": "positive",
    "south_african_white_maize_jse": "positive",
    "south_african_yellow_maize_jse": "positive",
    "hard_red_spring_wheat_mgex": "positive",
    "french_wheat_matif": "positive",
    "french_maize_matif": "positive",
    "french_rapeseed_matif": "positive",
    # CEPEA cash references (BRL per 60-kg bag)
    "brazilian_arabica_coffee": "positive",
    "campinas_corn_reference_bmf": "positive",
}

# THE REASON (O-1 default): ONE additive nullable string column, written by the WRITE SEAM and never
# by a producer (the producers' SILVER_COLUMNS projection is unchanged, so the seven other bronze ->
# silver legs need no edit). NULL iff all five prices are present; otherwise one ``<column>:<cause>``
# token per missing price column, ';'-joined in PRICE_COLUMNS order. A cause names what the CODE
# SAW, never a guessed origin:
#   nonpositive_value  -- a value <= 0 under a ``positive`` domain, nulled by this guard;
#   nonfinite_value    -- +/-inf, nulled by this guard;
#   absent_on_arrival  -- the value reached the write seam already missing; the seam cannot see why
#                         (no bar, no settlement statistic, a settlement-tape row with no bar, a mark
#                         an upstream stage nulled). Not named "absent_in_source": for the CPO zero
#                         marks nulled in bronze the source DID carry a value.
# A token already on an arriving row (a canonical prior the guard wrote before) is CARRIED for a
# column that is still missing, so a second pass never downgrades nonpositive_value to
# absent_on_arrival. The column is declared by the table declaration (generator-owned); the write
# seam stages it only when the declaration carries it (futures_eod_task.write_columns).
PRICE_NULL_REASON_COLUMN = "price_null_reason"
WRITE_SEAM_COLUMNS: tuple[str, ...] = (PRICE_NULL_REASON_COLUMN,)
PRICE_NULL_CAUSES: frozenset[str] = frozenset(
    {"nonpositive_value", "nonfinite_value", "absent_on_arrival"})
# The denominators a declared failing share may name (O-6): the whole frame being written, one
# slug inside it, or one (slug, trade_date) inside it.
PRICE_GUARD_DENOMINATORS: tuple[str, ...] = ("run", "slug", "slug_day")


def lint_price_domain() -> list[str]:
    """PRICE_DOMAIN is complete against CONTRACT_MAP (both directions) and inside the vocabulary."""
    errs: list[str] = []
    missing = sorted(set(CONTRACT_MAP) - set(PRICE_DOMAIN))
    extra = sorted(set(PRICE_DOMAIN) - set(CONTRACT_MAP))
    if missing:
        errs.append(f"PRICE_DOMAIN declares no domain for {missing} -- every contract must declare "
                    f"one of {sorted(PRICE_DOMAINS)}; a missing declaration is never defaulted")
    if extra:
        errs.append(f"PRICE_DOMAIN names slug(s) absent from CONTRACT_MAP: {extra}")
    bad = sorted(f"{s}={d!r}" for s, d in PRICE_DOMAIN.items() if d not in PRICE_DOMAINS)
    if bad:
        errs.append(f"PRICE_DOMAIN value(s) outside {sorted(PRICE_DOMAINS)}: {bad}")
    return errs


assert not lint_price_domain(), "futures_eod_contracts.PRICE_DOMAIN is malformed: " + "; ".join(
    lint_price_domain())


def parse_price_null_reason(value) -> dict[str, str]:
    """``'settle:nonpositive_value;close:nonpositive_value'`` -> ``{column: cause}``. FAIL CLOSED on a
    token outside the vocabulary (the only writer is :func:`guard_prices`; an unknown token means the
    vocabulary moved without a migration)."""
    if _is_blank(value):
        return {}
    out: dict[str, str] = {}
    for tok in str(value).split(";"):
        col, sep, cause = tok.partition(":")
        if not sep or col not in PRICE_COLUMNS or cause not in PRICE_NULL_CAUSES or col in out:
            raise ValueError(f"{PRICE_NULL_REASON_COLUMN} token {tok!r} in {value!r} is not "
                             f"'<{'|'.join(PRICE_COLUMNS)}>:<{'|'.join(sorted(PRICE_NULL_CAUSES))}>' "
                             f"(or repeats a column)")
        out[col] = cause
    return out


def guard_prices(df):
    """THE WRITE GUARD (FUT-1): null every price outside its contract's declared domain, WITH a reason.

    Returns ``(frame, record)``. The frame is a copy of ``df`` whose five price columns carry NaN where
    a value was non-finite or outside the domain, plus the ``price_null_reason`` column (see above).
    NOTHING ELSE MOVES: no row is removed, no other column is read for a decision or written, and a
    value inside its domain is returned bit-identical. The record counts what the guard did -- per
    column and cause, per slug, and per (slug, trade_date) -- which is the census the declared failing
    share (:func:`price_guard_breaches`) is judged on and what the run log stamps.

    Imports pandas lazily so this module stays stdlib-only at import (the producers and config_check
    import it)."""
    import numpy as np
    import pandas as pd

    rec: dict = {"rows": 0, "rows_nulled": 0, "cells_nulled": {}, "reason_tokens_carried": 0,
                 "by_slug": {}, "slug_days": [], "examples": []}
    if df is None:
        raise ValueError("guard_prices: no frame")
    out = df.copy()
    if len(out) == 0:
        if PRICE_NULL_REASON_COLUMN not in out.columns:
            out[PRICE_NULL_REASON_COLUMN] = pd.Series([], dtype=object)
        return out, rec
    need = ("leviathan_slug", "trade_date", *PRICE_COLUMNS)
    missing = [c for c in need if c not in out.columns]
    if missing:
        raise ValueError(f"guard_prices: frame is missing {missing}")
    n = len(out)
    slugs = out["leviathan_slug"].astype("object").to_numpy()
    unknown = sorted({str(s) for s in slugs if _is_blank(s) or s not in PRICE_DOMAIN})
    if unknown:
        raise ValueError(f"guard_prices: slug(s) {unknown} have no declared PRICE_DOMAIN -- refusing "
                         f"to write a price whose domain is not declared")
    positive = np.fromiter((PRICE_DOMAIN[s] == "positive" for s in slugs), dtype=bool, count=n)

    # Tokens a prior pass wrote (a canonical row read back by the merge). Only a cause the seam could
    # NOT re-derive is worth carrying -- absent_on_arrival is what a NaN re-derives to anyway.
    carried_pos: dict[str, list[int]] = {c: [] for c in PRICE_COLUMNS}
    carried_cause: dict[str, list[str]] = {c: [] for c in PRICE_COLUMNS}
    if PRICE_NULL_REASON_COLUMN in out.columns:
        for pos, val in enumerate(out[PRICE_NULL_REASON_COLUMN].astype("object").to_numpy()):
            for col, cz in parse_price_null_reason(val).items():
                if cz != "absent_on_arrival":
                    carried_pos[col].append(pos)
                    carried_cause[col].append(cz)

    nulled_any = np.zeros(n, dtype=bool)
    reason = np.full(n, "", dtype=object)
    for col in PRICE_COLUMNS:
        vals = pd.to_numeric(out[col], errors="coerce").astype("float64").to_numpy(copy=True)
        arrived_missing = np.isnan(vals)
        nonfinite = np.isinf(vals)
        with np.errstate(invalid="ignore"):
            nonpositive = ~arrived_missing & ~nonfinite & positive & (vals <= 0.0)
        kill = nonfinite | nonpositive
        if kill.any():
            vals[kill] = np.nan
            out[col] = vals
            nulled_any |= kill
            by_cause = {}
            if nonpositive.any():
                by_cause["nonpositive_value"] = int(nonpositive.sum())
            if nonfinite.any():
                by_cause["nonfinite_value"] = int(nonfinite.sum())
            rec["cells_nulled"][col] = by_cause
        cause = np.full(n, None, dtype=object)
        cause[arrived_missing] = "absent_on_arrival"
        if carried_pos[col]:
            cp = np.asarray(carried_pos[col], dtype=np.int64)
            cc = np.asarray(carried_cause[col], dtype=object)
            still = arrived_missing[cp]
            cause[cp[still]] = cc[still]
            rec["reason_tokens_carried"] += int(still.sum())
        cause[nonpositive] = "nonpositive_value"
        cause[nonfinite] = "nonfinite_value"
        has = np.fromiter((c is not None for c in cause), dtype=bool, count=n)
        if has.any():
            tok = np.full(n, "", dtype=object)
            tok[has] = [f"{col}:{c}" for c in cause[has]]
            both = has & (reason != "")
            reason = np.where(both, reason + ";" + tok, np.where(has, tok, reason))
    out[PRICE_NULL_REASON_COLUMN] = pd.Series(
        np.where(reason == "", None, reason), index=out.index, dtype=object)

    rec["rows"] = int(n)
    rec["rows_nulled"] = int(nulled_any.sum())
    if rec["rows_nulled"]:
        work = pd.DataFrame({
            "slug": slugs,
            "day": pd.to_datetime(out["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d").to_numpy(),
            "nulled": nulled_any})
        per_slug = work.groupby("slug")["nulled"].agg(["size", "sum"])
        rec["by_slug"] = {str(s): {"rows": int(r["size"]), "rows_nulled": int(r["sum"])}
                          for s, r in per_slug.iterrows() if int(r["sum"])}
        hit = work[work["nulled"]][["slug", "day"]].drop_duplicates()
        per_day = work.merge(hit, on=["slug", "day"]).groupby(["slug", "day"])["nulled"].agg(
            ["size", "sum"])
        rec["slug_days"] = [
            {"leviathan_slug": str(s), "trade_date": str(d), "rows": int(r["size"]),
             "rows_nulled": int(r["sum"]), "share": round(int(r["sum"]) / int(r["size"]), 6)}
            for (s, d), r in per_day.iterrows()]
        ex = out.loc[nulled_any]
        for row in ex.head(10).itertuples(index=False):
            rec["examples"].append({
                "leviathan_slug": str(getattr(row, "leviathan_slug")),
                "contract_month": str(getattr(row, "contract_month", "")),
                "trade_date": str(getattr(row, "trade_date"))[:10],
                PRICE_NULL_REASON_COLUMN: str(getattr(row, PRICE_NULL_REASON_COLUMN))})
    return out, rec


def price_guard_rule(contract: dict):
    """The DECLARED failing share, read from the table declaration's ``range_rules.price_domain_guard``
    (generator-owned; never a number typed in code). ``None`` when the declaration carries none -- the
    guard then still nulls and reports, it only has no share to fail on. FAIL CLOSED on a malformed
    declaration."""
    rules = (contract or {}).get("range_rules") or {}
    rule = rules.get("price_domain_guard")
    if rule is None:
        return None
    if not isinstance(rule, dict):
        raise ValueError(f"range_rules.price_domain_guard must be a mapping, got {rule!r}")
    den = rule.get("denominator")
    share = rule.get("max_nulled_share")
    if den not in PRICE_GUARD_DENOMINATORS:
        raise ValueError(f"range_rules.price_domain_guard.denominator {den!r} not in "
                         f"{list(PRICE_GUARD_DENOMINATORS)}")
    if isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 < float(share) <= 1:
        raise ValueError(f"range_rules.price_domain_guard.max_nulled_share {share!r} must be a "
                         f"fraction in (0, 1]")
    return {"denominator": den, "max_nulled_share": float(share)}


def price_guard_breaches(rec: dict, rule) -> list[str]:
    """Every group whose share of guard-nulled rows EXCEEDS the declared share, named. Pure."""
    if not rule:
        return []
    den, cap = rule["denominator"], float(rule["max_nulled_share"])
    out: list[str] = []
    if den == "run":
        rows, hit = int(rec.get("rows") or 0), int(rec.get("rows_nulled") or 0)
        if rows and hit / rows > cap:
            out.append(f"run: {hit} of {rows} rows carried a price outside its declared domain "
                       f"({hit / rows:.4f} > {cap})")
    elif den == "slug":
        for slug, r in sorted((rec.get("by_slug") or {}).items()):
            if r["rows"] and r["rows_nulled"] / r["rows"] > cap:
                out.append(f"{slug}: {r['rows_nulled']} of {r['rows']} rows "
                           f"({r['rows_nulled'] / r['rows']:.4f} > {cap})")
    else:
        for r in rec.get("slug_days") or []:
            if r["share"] > cap:
                out.append(f"{r['leviathan_slug']} {r['trade_date']}: {r['rows_nulled']} of "
                           f"{r['rows']} rows ({r['share']:.4f} > {cap})")
    return out
