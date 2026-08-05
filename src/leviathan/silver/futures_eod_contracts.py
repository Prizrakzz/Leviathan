"""PRICE_AND_PLAYBOOKS W1.0 / D4 -- the SINGLE-SOURCE per-contract map for ``silver_futures_eod``.

WHY THIS MODULE EXISTS (the FUTURES v1.5 lesson, generalized)
-------------------------------------------------------------
v1.5 had ONE unit fact living in three places (the transform ``UNIT_MAP``, the numbers card's
``unit_overrides``, and the tracked lint constant) and needed ``config_check.check_futures_lite`` to
bind them three-way so they could never drift. ``silver_futures_eod`` widens that problem hard: 31
contracts across 10 publication sources, four settlement semantics, and TEN currencies -- and the
unit vocabulary is no longer a US-exchange list (EUR/t, CNY/t, MYR/t, ZAR/t, BRL/60-kg bag, CAD/t).

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
    # -- Bursa Malaysia FCPO daily settlement bulletin (W1b; Databento CPO is a dead contract) --
    "malaysian_crude_palm_oil_cme": {"unit": "MYR/t", "currency": "MYR",
                                     "settle_kind": "settlement", "source": "bursa"},
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
# Regenerate with scratchpad/measure_coverage_floors.py after any backfill that extends history.
#
# WHAT READS THIS (W2b-D3/D4): the coverage-aware decline guard and the event-study floor. The
# routing rule is deterministic -- a window entirely >= the floor serves from silver_futures_eod;
# entirely before it serves a LEVEL from the legacy continuous card with an explicit provenance
# sentence; STRADDLING declines rather than silently splicing two different series.
#
# ABSENT slug == NOT SERVED: a slug with no entry has no per-contract record at all (the three W1c
# browser venues are absent because their canonical data has not landed). Callers must treat a
# missing key as "no coverage", never as "covered since forever" -- coverage_start_for() below
# fails closed so that distinction cannot be fudged.
#
# D-PR-24 (2026-08-05) -- THE MATIF LEG IS ARMED; THE SERVING FLIP IS NOT. Probe S3 resolved the
# SETTL. semantics (three captures, 08-04/08-05: intra-session the column shows the PRIOR completed
# settlement and the +/- computes against it; it rolls to the finished session's own settlement at
# the ~18:30 Paris evening publication, so the 22:30Z capture is same-day -- no T-1 risk). The
# euronext capture+silver legs now ride futures_eod_free; the arm declaration, the probe record and
# the delisting runbook live at configs/silver/dags/unarmed/futures_eod_browser.json, pinned by
# tests/unit/silver/test_matif_arm_declaration.py.
# TWO GATES, NOT ONE -- and only the FIRST is discharged. Rows may now land in silver, but the
# three euronext_matif slugs stay ABSENT from this dict, so every MATIF lookup still declines
# before any SQL compiles. Adding their entries here is the separate serving FLIP: it happens only
# after landed canonical rows are measured (coverage start = first landed trade_date), which is
# exactly what makes arm and flip separable.
# ---------------------------------------------------------------------------
PRICE_COVERAGE_START: dict[str, date] = {
    "arabica_coffee": date(2018, 12, 24),                 # databento_ifus_impact
    "brazilian_arabica_coffee": date(1996, 9, 2),         # cepea
    "campinas_corn_reference_bmf": date(2004, 8, 2),      # cepea
    "canola_ice": date(2018, 12, 24),                     # databento_ifus_impact
    "cocoa": date(2018, 12, 24),                          # databento_ifus_impact
    "corn_cbot": date(2010, 6, 6),                        # databento_glbx_mdp3
    "cotton": date(2018, 12, 24),                         # databento_ifus_impact
    "frozen_orange_juice": date(2018, 12, 24),            # databento_ifus_impact
    "hard_red_spring_wheat_mgex": date(2025, 9, 9),       # miax
    "hard_red_winter_wheat_kcbt": date(2014, 1, 2),       # databento_glbx_mdp3
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
