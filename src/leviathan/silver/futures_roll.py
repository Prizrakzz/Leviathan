"""PRICE_AND_PLAYBOOKS W2 / D8 -- THE named, versioned, QUERY-TIME front-month rule.

WHY THIS MODULE EXISTS (skeptic finding F-L)
--------------------------------------------
Three separate places need "which delivery month IS the market today": W2 gate 7 (the 12/12 parity
retirement gate against ``silver_futures_prices``), W3.3, and the W2b straddle rule. F-L's stated
failure mode is that each grows its OWN inline copy -- three rules, three answers, no version, and
a silent divergence the moment one of them is tweaked. So there is exactly ONE implementation, it
carries a VERSION, and ``config_check.check_futures_roll`` fails the build if a second copy appears
anywhere in ``src/`` / ``jobs/`` / ``scripts/``.

WHY IT IS QUERY-TIME AND NOT A STORED COLUMN
--------------------------------------------
``silver_futures_eod`` deliberately carries no ``is_front_month`` / ``is_roll_date`` / adjusted
series (registry notes, W1.0): a stored front-month flag IS roll policy, and roll policy is a
decision the reader makes. This module is the decision, applied at read time to the honest
per-delivery-month rows. A continuous series would be a separate derived ``gold_futures_continuous``
carrying its own ``roll_policy_version``; this is NOT that.

THE RULE (plan D8, verbatim in structure)
-----------------------------------------
* **front-by-OI** where open interest exists -- GLBX (via the $1.76 ``statistics`` buy, which is
  the concrete data dependency behind F-L), CZCE and JSE both publish it;
* **front-by-volume** otherwise -- the two ICE datasets, whose ``statistics`` schema is
  unaffordable ($1,960) so they carry no OI at all;
* **curated delivery-cycle** for settle-only sources with neither -- Bursa, MIAX, Euronext/MATIF
  and (for now) DCE;
* **no roll at all** for ``instrument_kind == 'cash_index'`` -- the two CEPEA cash references have
  no delivery-month axis, so "front month" is not a question that can be asked of them.

Ties break DETERMINISTICALLY on the nearest delivery month, then on the lexical month string, so
two runs over the same rows always name the same contract.

Pure: pandas + the contract map. AWS-free, import-free beyond the house map.
"""
from __future__ import annotations

import pandas as pd

from leviathan.silver import futures_eod_contracts as FC

# BUMP THIS when the rule's behaviour changes -- a consumer that stored a parity result under one
# version must not compare it against another. Never reuse a version for a changed rule.
# V2-4 (2026-09-03, review m2): FORWARD_MONTH_FLOOR changes front_month's eligibility predicate too,
# and this version is NOT bumped for the same reason OUTCOME_CONTRACT_RULE_VERSION is not -- the only
# floored slug is palm, palm is in NEITHER gold roster (gold_futures_spreads, gold_futures_outcomes),
# so no stored row on any version can differ; bump BOTH at the serving flip if the owner wants
# row-level provenance to name the floor.
ROLL_RULE_VERSION = "front_month_v2"

# OUTCOMES_JOIN J1.b -- the SECOND, SEPARATELY VERSIONED selection rule (survival-selected single
# contract, plan Option D / D-OJ-1). It is NOT front_month under another name: measured agreement with
# the front chain is 25.5-31.7% of anchors, so reusing ROLL_RULE_VERSION would make two DIFFERENT
# selections indistinguishable in provenance (plan item 32). It lives HERE because it reuses the D8
# eligibility predicate (_month_start / _cycle_eligible) verbatim, and a second copy of that predicate
# is exactly the F-L drift this module exists to prevent.
OUTCOME_CONTRACT_RULE_VERSION = "survivor_nearest_v1"

# The survival test's margin, in CALENDAR days past the horizon close. It is part of the PIT BOUNDARY,
# not only of the selection (plan item 46): a contract chosen by asking "does it still print five
# sessions past the endpoint?" was chosen with tape the asof may not have. Anything that clamps an
# outcome reads this constant -- the numbers card's publication_lag_days is lint-bound to it + the
# tape's own 1-day lag (leviathan.graphrag.numbers.outcomes.lint_outcome_card).
OUTCOME_SURVIVE_DAYS = 5

# The four methods. "none" is not an absence of a rule; it is the ASSERTION that the question does
# not apply (cash references), which is why it is a first-class value rather than a missing key.
METHOD_OPEN_INTEREST = "open_interest"
METHOD_VOLUME = "volume"
METHOD_DELIVERY_CYCLE = "delivery_cycle"
METHOD_NONE = "none"
ROLL_METHODS: tuple[str, ...] = (
    METHOD_OPEN_INTEREST, METHOD_VOLUME, METHOD_DELIVERY_CYCLE, METHOD_NONE,
)

# THE RULE'S INPUT CONTRACT: which COLUMN each method actually READS. Exported because a caller that
# must decide "can the rule even RUN on these rows?" would otherwise re-declare this mapping inline --
# a second INPUT CONTRACT. That is F-L in miniature and it is worse than a second implementation,
# because the config_check source fence only scans for a competing IMPLEMENTATION and would never see
# it: when a method's column changes (the DCE entry above moves from METHOD_DELIVERY_CYCLE to
# METHOD_VOLUME the moment the W1c producer proves its volume field), the stale inline copy either
# declines wrongly or waves through a degraded selection, silently.
# None = the method reads NO activity metric: a delivery-cycle front month is a curated calendar fact,
# and a cash reference has no delivery-month axis at all. Bound to ROLL_METHODS by lint_roll_rule.
METHOD_METRIC_COL: dict[str, str | None] = {
    METHOD_OPEN_INTEREST: "open_interest",
    METHOD_VOLUME: "volume",
    METHOD_DELIVERY_CYCLE: None,
    METHOD_NONE: None,
}

# Per PUBLICATION SOURCE, not per slug: the method is a property of what the feed CARRIES.
# check_futures_roll asserts this covers exactly futures_eod_contracts.SOURCES.
ROLL_METHOD_BY_SOURCE: dict[str, str] = {
    # OI is published: GLBX via the statistics schema, CZCE and JSE in their daily files.
    "databento_glbx_mdp3": METHOD_OPEN_INTEREST,
    "czce": METHOD_OPEN_INTEREST,
    "jse_safex": METHOD_OPEN_INTEREST,
    # ICE: ohlcv-1d carries volume but no OI (the statistics schema is $1,960 and excluded), so the
    # PRIMARY rule is unavailable by construction and the fallback is the rule, not a degradation.
    "databento_ifus_impact": METHOD_VOLUME,
    "databento_ifeu_impact": METHOD_VOLUME,
    # DCE publishes volume on BOTH payload kinds, so it uses the measured rule rather than a
    # curated calendar. PRECONDITION DISCHARGED 2026-07-30 (front_month_v2): the W1c producer
    # landed and proved it -- raw_to_bronze/dce_eod.py parses volume from the /dcereport quote JSON
    # (fixture: p2609 volume 127,012 on the live 2026-07-29 capture) AND from the year workbook
    # (fixture: p1601 volume 2,626 in the real 2016 file), and bronze_to_silver/dce_eod.py writes it
    # into the silver volume column. That retired the (1, 5, 9) curation this table used to carry
    # for the five DCE slugs, which was its weakest entry and always labelled PROVISIONAL.
    "dce": METHOD_VOLUME,
    # Settle-only bulletins: neither OI nor volume survives the publication, so the front month is
    # a curated calendar fact.
    "bursa": METHOD_DELIVERY_CYCLE,
    "miax": METHOD_DELIVERY_CYCLE,
    "euronext_matif": METHOD_DELIVERY_CYCLE,
    # The two CEPEA cash references have no delivery month at all.
    "cepea": METHOD_NONE,
}

# Curated listing cycles for the delivery-cycle slugs: the delivery MONTH NUMBERS the venue lists.
# Front = the nearest listed month not yet in delivery. Every METHOD_DELIVERY_CYCLE slug must
# appear here and nothing else may (check_futures_roll asserts both directions).
DELIVERY_CYCLES: dict[str, tuple[int, ...]] = {
    # (The Bursa FCPO twelve-month row for malaysian_crude_palm_oil_cme was RETIRED 2026-09-02 when
    # that slug moved to databento_glbx_mdp3 / METHOD_OPEN_INTEREST (V2-4); restore all-12 under a
    # bursa slug when the parked Bursa leg is minted -- lint_roll_rule refuses a cycle row on an
    # open_interest slug.)
    # MIAX (ex-MGEX) hard red spring wheat: the classic Mar/May/Jul/Sep/Dec grain cycle.
    "hard_red_spring_wheat_mgex": (3, 5, 7, 9, 12),
    # Euronext/MATIF listed cycles.
    "french_wheat_matif": (3, 5, 9, 12),
    "french_maize_matif": (3, 6, 8, 11),
    "french_rapeseed_matif": (2, 5, 8, 11),
    # (The five DCE slugs lived here under a PROVISIONAL (1, 5, 9) curation until 2026-07-30. They
    # are gone because DCE moved to METHOD_VOLUME once W1c proved the volume column -- and
    # check_futures_roll asserts BOTH directions, so leaving them would now be a hard failure.)
}

# FORWARD-MONTH FLOOR (V2-4 tenor rule): the minimum number of months the priced delivery month must
# sit FORWARD of the anchor month (front_month AND outcome_contract) and of the horizon-end month
# (outcome_contract).
#
# WHY 1 AND NOT 2 (RECALIBRATED 2026-09-03, STEP-12 review MAJ-2; the charter's "AT LEAST TWO MONTHS
# FORWARD" was the sitting owner's conservative reading of the CME spec, corrected by measurement).
# The contract for month M becomes a RUNNING AVERAGE only from M's own first business day -- before
# that its settle is a pure forward mark, exactly like every other board's. `month >= read_month + 1`
# therefore holds at BOTH reads the floor governs (the anchor and the endpoint), so floor 1 is
# NECESSARY -- floor 0 lets the endpoint's own month in, which is the partial-average read -- and
# SUFFICIENT: no month it admits can be accruing at either end. Floor 2 was margin with no rule
# behind it, and the review measured what the margin cost: 16 of 72 endpoint dates on the
# soyoil<->palm tenor fence (MAJOR-8, same-or-adjacent delivery month) and 14 of 72 on
# soybeans<->palm, because a parent at X or X+1 cannot be adjacent to a child pushed to X+2.
#
# WHY A CURATED PER-SLUG TABLE AND NOT A RULE: nothing in this module knows an expiry calendar --
# "expiry" is INFERRED from last_print_date (contract_last_print) -- so the survivor rule happily
# picks the endpoint's OWN delivery month whenever that month still prints past t2 + survive_days.
# For every board whose settle is a POINT-IN-TIME mark that is correct, and it is what the other 30
# slugs get. It is wrong for the CME USD Malaysian Crude Palm Oil CALENDAR future (rulebook 204),
# whose settle is the CUMULATIVE AVERAGE of its own contract month's Bursa third-forward FCPO
# settlements at the KL fixing: a contract read INSIDE its own month is a partial average, not a
# price, and differencing it against a forward mark at the anchor books the accrual as a move.
#
# AN ABSENT SLUG == 0 == THE SHIPPED RULE. The anchor filter with a zero offset is the shipped
# expression byte-for-byte, and the endpoint filter does not run at all when no row in the frame
# carries a floor -- so gold_futures_outcomes / pattern_records selections for the other 30 slugs
# are unchanged, which is why OUTCOME_CONTRACT_RULE_VERSION is NOT bumped here (no floored slug can
# produce a stored row until its coverage floor lands AND an image is built from this commit; the
# bump is the owner's call at the serving flip).
FORWARD_MONTH_FLOOR: dict[str, int] = {
    "malaysian_crude_palm_oil_cme": 1,
}


def forward_month_floor(slug: str) -> int:
    """Months the priced delivery month must sit forward of the anchor/endpoint month. 0 = the
    shipped rule (the accessor, so no caller reads the table directly and drifts from it)."""
    return int(FORWARD_MONTH_FLOOR.get(str(slug), 0))


def _floor_months(slugs: pd.Series):
    """Per-row forward-month floor, as an int64 month count (0 for every unlisted slug)."""
    return slugs.map(forward_month_floor).to_numpy(dtype="int64")


def _floored_month_bound(anchors: pd.Series, months):
    """``anchors`` truncated to its month start, pushed forward ``months`` months -- the lower bound
    a delivery month must clear. With an all-zero ``months`` this is month-start(anchors) exactly,
    which is the shipped eligibility expression."""
    return pd.Series(
        pd.to_datetime(anchors.to_numpy().astype("datetime64[M]")
                       + months.astype("timedelta64[M]")),
        index=anchors.index)

FRONT_MONTH_COLUMNS: list[str] = [
    "leviathan_slug", "trade_date", "contract_month", "raw_symbol", "settle", "close",
    "volume", "open_interest", "unit", "currency", "settle_kind", "source",
    "roll_method", "roll_rule_version",
]

# What outcome_contract returns per ANCHOR. `last_print_date` and `horizon_end` ride on the row because
# the survival test is the whole rule: a reader (or the PIT clamp) that cannot see which contract-life
# fact the selection turned on cannot audit it.
OUTCOME_CONTRACT_COLUMNS: list[str] = [
    "leviathan_slug", "trade_date", "contract_month", "raw_symbol", "settle",
    "unit", "currency", "settle_kind", "source",
    "horizon_end", "survive_days", "last_print_date", "outcome_rule_version",
]


def roll_method_for(slug: str) -> str:
    """The front-month method for one contract slug. FAIL CLOSED on an unmapped slug.

    Derived from the slug's SOURCE via :data:`ROLL_METHOD_BY_SOURCE`, so adding a contract to
    ``CONTRACT_MAP`` cannot silently leave it without a rule."""
    rec = FC.contract_for(slug)                    # raises on an unmapped slug
    if slug in FC.CASH_INDEX_SLUGS:
        return METHOD_NONE
    method = ROLL_METHOD_BY_SOURCE.get(rec["source"])
    if method is None:
        raise ValueError(
            f"source {rec['source']!r} (slug {slug!r}) has no entry in ROLL_METHOD_BY_SOURCE -- "
            f"add one HERE; never re-derive the front-month rule at a call site (skeptic F-L)"
        )
    return method


def delivery_cycle_for(slug: str) -> tuple[int, ...]:
    """The curated listed-month cycle for a delivery-cycle slug. FAIL CLOSED."""
    if roll_method_for(slug) != METHOD_DELIVERY_CYCLE:
        raise ValueError(f"{slug!r} does not use the delivery-cycle method")
    cycle = DELIVERY_CYCLES.get(slug)
    if not cycle:
        raise ValueError(f"{slug!r} uses the delivery-cycle method but has no curated cycle")
    return cycle


def _month_start(series: pd.Series) -> pd.Series:
    """``YYYY-MM`` strings -> the first day of that month, as datetimes."""
    return pd.to_datetime(series.astype("string") + "-01", errors="coerce")


def _cycle_eligible(slug: str, months: pd.Series) -> pd.Series:
    cycle = set(delivery_cycle_for(slug))
    return months.dt.month.isin(cycle)


def front_month_inputs_present(df: pd.DataFrame) -> bool:
    """True when EVERY candidate row carries the input ITS OWN slug's method reads -- the precondition
    :func:`front_month` deliberately cannot express, asked HERE so no caller re-declares the method ->
    column contract (:data:`METHOD_METRIC_COL`).

    ``front_month`` fills a missing activity metric with -1 so it can never outrank a real print. That
    is correct INSIDE the rule (a deterministic tie-break), but it means a frame carrying the metric on
    only SOME rows still returns a contract -- chosen by the nearest-month tie-break, i.e. a DIFFERENT,
    unnamed rule (precisely ``legacy_lane_front``'s convention) wearing ``front_month_v2``'s name. An
    ALL-missing frame is the obvious case; the PARTIAL frame is the dangerous one, because whichever
    expiry happened to carry a print wins by default and nothing about that is visible downstream. A
    caller that must not serve a degraded selection asks this first and declines when it is False.

    Rows whose method needs no metric (the delivery-cycle sources, and the cash references
    ``front_month`` drops outright) are vacuously present -- "is this even a front-month question?" is
    :func:`roll_method_for`'s job, not this one's. FAIL CLOSED: an unmapped slug raises (as
    ``roll_method_for`` does), a frame with no ``leviathan_slug`` column is False, and an empty frame is
    False (nothing to select from is not a satisfied precondition). Blank strings and NaN both count as
    ABSENT -- a row whose open interest arrived as '' is a row the rule cannot read."""
    if df is None or len(df) == 0 or "leviathan_slug" not in list(getattr(df, "columns", [])):
        return False
    for slug in sorted({str(s) for s in df["leviathan_slug"].dropna().tolist()}):
        need = METHOD_METRIC_COL[roll_method_for(slug)]    # KeyError on an unknown method: fail closed
        if need is None:
            continue
        if need not in df.columns:
            return False
        vals = pd.to_numeric(df.loc[df["leviathan_slug"].astype("string") == slug, need],
                             errors="coerce")
        if len(vals) == 0 or vals.isna().any():
            return False
    return True


def front_month(df: pd.DataFrame, *, rule_version: str = ROLL_RULE_VERSION) -> pd.DataFrame:
    """Pick THE front contract per ``(leviathan_slug, trade_date)`` from ``silver_futures_eod`` rows.

    ``df`` carries the silver columns (``leviathan_slug``, ``trade_date``, ``contract_month``,
    ``instrument_kind``, ``settle``/``close``, ``volume``, ``open_interest``, ``source`` ...).

    Rows whose slug rolls by :data:`METHOD_NONE` (``instrument_kind == 'cash_index'``) are DROPPED,
    not passed through: naming a front month for a cash reference would be a category error, and a
    silent passthrough would let a caller treat a CEPEA index as a futures front month.

    Only contracts NOT yet in delivery are eligible -- ``contract_month`` month-start must be
    >= the trade date's month start. That is what prevents the expiring month from staying "front"
    forever on a stale OI print.

    Returns one row per ``(slug, trade_date)`` with :data:`FRONT_MONTH_COLUMNS`, carrying the
    ``roll_method`` actually used and this module's ``roll_rule_version``."""
    if rule_version != ROLL_RULE_VERSION:
        raise ValueError(
            f"requested roll_rule_version {rule_version!r} != this module's {ROLL_RULE_VERSION!r} "
            f"-- there is exactly one implementation; a caller pinning an old version must pin the "
            f"MODULE, not ask this one to behave differently"
        )
    cols = ["leviathan_slug", "trade_date", "contract_month"]
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=FRONT_MONTH_COLUMNS)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"front_month: frame is missing {missing}")

    work = df.copy()
    for opt in ("settle", "close", "volume", "open_interest", "raw_symbol",
                "unit", "currency", "settle_kind", "source"):
        if opt not in work.columns:
            work[opt] = pd.NA
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    work = work[work["trade_date"].notna()]
    work["_month"] = _month_start(work["contract_month"])
    work = work[work["_month"].notna()]
    work["roll_method"] = work["leviathan_slug"].map(
        {s: roll_method_for(s) for s in sorted(set(work["leviathan_slug"]))})
    work = work[work["roll_method"] != METHOD_NONE]
    if work.empty:
        return pd.DataFrame(columns=FRONT_MONTH_COLUMNS)

    # Eligibility: not yet in delivery (plus the slug's FORWARD_MONTH_FLOOR, 0 for all but the
    # averaging boards -- so a CPO "front" is never the month whose average is still accruing), and
    # (delivery-cycle slugs only) a LISTED month.
    work["_trade_month"] = work["trade_date"].values.astype("datetime64[M]")
    work = work[work["_month"] >= _floored_month_bound(
        work["_trade_month"], _floor_months(work["leviathan_slug"]))]
    cyc = work["roll_method"] == METHOD_DELIVERY_CYCLE
    if cyc.any():
        keep = pd.Series(True, index=work.index)
        for slug in sorted(set(work.loc[cyc, "leviathan_slug"])):
            sel = cyc & (work["leviathan_slug"] == slug)
            keep.loc[sel[sel].index] = _cycle_eligible(slug, work.loc[sel, "_month"])
        work = work[keep]
    if work.empty:
        return pd.DataFrame(columns=FRONT_MONTH_COLUMNS)

    # The activity metric: OI where the method says so, volume where it says so, and NOTHING for
    # the delivery-cycle slugs (their front month is the nearest listed month, by definition).
    oi = pd.to_numeric(work["open_interest"], errors="coerce")
    vol = pd.to_numeric(work["volume"], errors="coerce")
    metric = pd.Series(float("nan"), index=work.index, dtype="float64")
    metric = metric.mask(work["roll_method"] == METHOD_OPEN_INTEREST, oi)
    metric = metric.mask(work["roll_method"] == METHOD_VOLUME, vol)
    # A missing metric must never outrank a real one, and must never win by accident: -1 sorts
    # below every legitimate non-negative OI/volume, so the tie-break (nearest month) decides.
    work["_metric"] = metric.fillna(-1.0)

    # Deterministic: highest metric, then NEAREST delivery month, then the lexical month string.
    work = work.sort_values(
        ["leviathan_slug", "trade_date", "_metric", "_month", "contract_month"],
        ascending=[True, True, False, True, True], kind="mergesort")
    out = work.drop_duplicates(subset=["leviathan_slug", "trade_date"], keep="first").copy()
    out["roll_rule_version"] = ROLL_RULE_VERSION
    return out[FRONT_MONTH_COLUMNS].sort_values(
        ["leviathan_slug", "trade_date"], kind="mergesort").reset_index(drop=True)


def legacy_lane_front(df: pd.DataFrame) -> pd.DataFrame:
    """NEAREST-ELIGIBLE-MONTH selection for the RETIREMENT-SOAK PARITY comparison ONLY.

    MEASURED 2026-07-29, twice. First pass (corn, four-way): front-by-volume x settle
    reproduced the yfinance lane exactly while D8's front-by-OI sat ~2.1% away -- but
    volume left soyoil/soymeal/cotton at 0.57%/0.66%/2.09% medians. Second pass: NEAREST
    eligible month reproduced soyoil and soymeal at median AND p90 0.00000 and cotton at
    0.1% median -- and it subsumes the corn result, because for grains the volume leader IS
    the nearest month on almost every session. The lane's actual convention is the simplest
    one: hold the nearest contract until expiry, print its settlement. One rule, twelve slugs.

    Lives in THIS module -- the single home for roll selection (skeptic F-L: inline copies
    are the failure mode) -- and shares front_month's eligibility exactly (futures rows only,
    not yet in delivery). The serving rule remains front_month/ROLL_RULE_VERSION; this
    function is pinned to the legacy lane and RETIRES WITH IT."""
    cols = ["leviathan_slug", "trade_date", "contract_month"]
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=FRONT_MONTH_COLUMNS)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"legacy_lane_front: frame is missing {missing}")
    work = df.copy()
    for opt in ("settle", "close", "volume", "open_interest", "raw_symbol",
                "unit", "currency", "settle_kind", "source"):
        if opt not in work.columns:
            work[opt] = pd.NA
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    work = work[work["trade_date"].notna()]
    work["_month"] = _month_start(work["contract_month"])
    work = work[work["_month"].notna()]
    # same category guard as front_month: a cash reference has no front month
    work["roll_method"] = work["leviathan_slug"].map(
        {s: roll_method_for(s) for s in sorted(set(work["leviathan_slug"]))})
    work = work[work["roll_method"] != METHOD_NONE]
    if work.empty:
        return pd.DataFrame(columns=FRONT_MONTH_COLUMNS)
    work["_trade_month"] = work["trade_date"].values.astype("datetime64[M]")
    work = work[work["_month"] >= pd.to_datetime(work["_trade_month"])]
    if work.empty:
        return pd.DataFrame(columns=FRONT_MONTH_COLUMNS)
    work["roll_method"] = "legacy_nearest"
    work = work.sort_values(
        ["leviathan_slug", "trade_date", "_month", "contract_month"],
        ascending=[True, True, True, True], kind="mergesort")
    out = work.drop_duplicates(subset=["leviathan_slug", "trade_date"], keep="first").copy()
    out["roll_rule_version"] = ROLL_RULE_VERSION
    return out[FRONT_MONTH_COLUMNS].sort_values(
        ["leviathan_slug", "trade_date"], kind="mergesort").reset_index(drop=True)


def contract_last_print(df: pd.DataFrame) -> pd.DataFrame:
    """``max(trade_date)`` per ``(leviathan_slug, contract_month)`` -- THE one derived input Option D
    needs, and the reason it needs one: ``expiry_date`` is NULL on all 455,421 tape rows (author-
    verified), so contract LIFE is inferable and nothing else.

    Returns ``[leviathan_slug, contract_month, last_print_date]`` (datetimes), one row per contract.
    Cash-index rows (NULL ``contract_month``) carry no delivery-month axis and are dropped -- Option E
    routes those slugs around the contract path entirely."""
    cols = ["leviathan_slug", "trade_date", "contract_month"]
    out_cols = ["leviathan_slug", "contract_month", "last_print_date"]
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=out_cols)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"contract_last_print: frame is missing {missing}")
    work = df[cols].copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    work["contract_month"] = work["contract_month"].astype("string")
    work = work[work["trade_date"].notna() & work["contract_month"].notna()]
    if work.empty:
        return pd.DataFrame(columns=out_cols)
    agg = (work.groupby(["leviathan_slug", "contract_month"], as_index=False)["trade_date"].max()
           .rename(columns={"trade_date": "last_print_date"}))
    return agg.sort_values(["leviathan_slug", "contract_month"], kind="mergesort").reset_index(drop=True)


def _resolve_horizon_end(work: pd.DataFrame, horizon_end) -> pd.Series:
    """Per-anchor nominal horizon close, as datetimes. Accepts a SCALAR (one close for the whole call)
    or a mapping keyed by the anchor date ``'YYYY-MM-DD'`` or by ``(slug, 'YYYY-MM-DD')``.

    FAIL CLOSED: an anchor with no entry RAISES. Silently dropping it would shrink the anchor set
    invisibly, and silently defaulting it would select a contract against the wrong horizon."""
    if isinstance(horizon_end, dict):
        keys_slug = list(zip(work["leviathan_slug"].astype("string"),
                             work["trade_date"].dt.strftime("%Y-%m-%d")))
        vals = []
        for slug, day in keys_slug:
            if (slug, day) in horizon_end:
                vals.append(horizon_end[(slug, day)])
            elif day in horizon_end:
                vals.append(horizon_end[day])
            else:
                raise ValueError(
                    f"outcome_contract: no horizon_end for anchor ({slug!r}, {day}) -- the survival "
                    f"test IS the rule, so an anchor with no horizon close cannot be selected for"
                )
        return pd.to_datetime(pd.Series(vals, index=work.index), errors="coerce")
    return pd.Series(pd.to_datetime(horizon_end), index=work.index)


def outcome_contract(df: pd.DataFrame, *, horizon_end, survive_days: int = OUTCOME_SURVIVE_DAYS,
                     last_print: pd.DataFrame | None = None,
                     rule_version: str = OUTCOME_CONTRACT_RULE_VERSION) -> pd.DataFrame:
    """OUTCOMES_JOIN J1 Option D -- pick the NEAREST ELIGIBLE expiry that still prints ``survive_days``
    past the horizon close, per ``(leviathan_slug, trade_date)`` anchor. ONE contract, TWO endpoints,
    so the splice is structurally zero rather than merely bounded.

    ``df`` carries the silver rows AT THE ANCHOR SESSIONS (one row per candidate delivery month per
    anchor). ``last_print`` is :func:`contract_last_print` over the FULL tape and is MANDATORY: deriving
    it from ``df`` would ask the anchor session whether a contract survives the horizon, which it can
    never answer, and the failure would look like "no contract qualified" rather than like a bug.

    ``horizon_end`` is the NOMINAL close ``t0 + H`` (calendar), never the realized endpoint. That is
    deliberate and it is the conservative direction: the realized ``t1`` is the last session at or
    before ``t0 + H`` (J1.c), so ``max(trade_date) >= horizon_end + survive_days`` IMPLIES the plan's
    ``>= t1 + survive_days`` -- and it breaks the circularity of choosing the contract from an endpoint
    that can only be found ON that contract. The same nominal term is what the PIT clamp compiles
    (``E + H + survive_days``, plan item 46), so selection and boundary read the SAME knob.

    THE THREE FILTERS, each a measured hazard:
      * **price fence** -- ``settle IS NOT NULL AND settle > 0`` at the anchor (10,200 unusable tape
        rows: 9,983 NULL + 217 exact zeros on high-volume front contracts; a zero denominator
        fabricates a -100% move).
      * **D8 eligibility** -- the contract month is not already in delivery, and for a delivery-cycle
        slug it is a LISTED month. Shared with ``front_month`` through ``_month_start`` /
        ``_cycle_eligible``; never re-stated.
      * **survival** -- ``last_print_date >= horizon_end + survive_days``. A contract with NO
        ``last_print`` entry is DROPPED (an unknown contract life is not a survival).

    Cash-index slugs (``METHOD_NONE``) are dropped exactly as ``front_month`` drops them: they have no
    delivery-month axis, and Option E (a straight self-join on ``(slug, trade_date)``) is their path.

    Ties break on the NEAREST delivery month then the lexical month string, so two runs over the same
    rows always name the same contract. Returns :data:`OUTCOME_CONTRACT_COLUMNS`, one row per anchor
    that had a qualifying contract; an anchor with none is simply ABSENT (its caller renders the
    decline -- this function never invents a fallback selection)."""
    if rule_version != OUTCOME_CONTRACT_RULE_VERSION:
        raise ValueError(
            f"requested outcome rule_version {rule_version!r} != this module's "
            f"{OUTCOME_CONTRACT_RULE_VERSION!r} -- there is exactly one implementation; a caller "
            f"pinning an old version must pin the MODULE, not ask this one to behave differently"
        )
    if isinstance(survive_days, bool) or not isinstance(survive_days, int) or survive_days < 0:
        raise ValueError(f"survive_days must be a non-negative int, got {survive_days!r}")
    cols = ["leviathan_slug", "trade_date", "contract_month", "settle"]
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=OUTCOME_CONTRACT_COLUMNS)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"outcome_contract: frame is missing {missing}")
    if last_print is None:
        raise ValueError(
            "outcome_contract: last_print is REQUIRED -- pass contract_last_print(<full tape>). The "
            "survival test is the rule; deriving contract life from the anchor frame would silently "
            "select the nearest ELIGIBLE month instead (a different, unnamed rule)"
        )

    work = df.copy()
    for opt in ("raw_symbol", "unit", "currency", "settle_kind", "source"):
        if opt not in work.columns:
            work[opt] = pd.NA
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    work = work[work["trade_date"].notna()]
    work["contract_month"] = work["contract_month"].astype("string")
    work["_month"] = _month_start(work["contract_month"])
    work = work[work["_month"].notna()]
    if work.empty:
        return pd.DataFrame(columns=OUTCOME_CONTRACT_COLUMNS)

    # Category guard, identical to front_month's: a cash reference has no delivery month to select.
    work["_roll_method"] = work["leviathan_slug"].map(
        {s: roll_method_for(s) for s in sorted(set(work["leviathan_slug"]))})
    work = work[work["_roll_method"] != METHOD_NONE]
    if work.empty:
        return pd.DataFrame(columns=OUTCOME_CONTRACT_COLUMNS)

    # THE PRICE FENCE -- both endpoints need a usable settle, and this is the t0 half.
    settle = pd.to_numeric(work["settle"], errors="coerce")
    work = work[settle.notna() & (settle > 0)]
    if work.empty:
        return pd.DataFrame(columns=OUTCOME_CONTRACT_COLUMNS)

    # D8 eligibility -- SHARED with front_month, never re-derived (FORWARD_MONTH_FLOOR included:
    # the ANCHOR half of the floor).
    work["_trade_month"] = work["trade_date"].values.astype("datetime64[M]")
    work = work[work["_month"] >= _floored_month_bound(
        work["_trade_month"], _floor_months(work["leviathan_slug"]))]
    cyc = work["_roll_method"] == METHOD_DELIVERY_CYCLE
    if cyc.any():
        keep = pd.Series(True, index=work.index)
        for slug in sorted(set(work.loc[cyc, "leviathan_slug"])):
            sel = cyc & (work["leviathan_slug"] == slug)
            keep.loc[sel[sel].index] = _cycle_eligible(slug, work.loc[sel, "_month"])
        work = work[keep]
    if work.empty:
        return pd.DataFrame(columns=OUTCOME_CONTRACT_COLUMNS)

    work["horizon_end"] = _resolve_horizon_end(work, horizon_end)
    if work["horizon_end"].isna().any():
        raise ValueError("outcome_contract: horizon_end did not parse as a date for every anchor")

    # THE ENDPOINT HALF OF THE FORWARD-MONTH FLOOR. The anchor half above cannot reach it: a span
    # runs forward, so a month that clears `anchor + floor` can still be the month the ENDPOINT sits
    # inside -- which for an averaging board is the partial-average read the floor exists to refuse.
    #
    # WHAT PROTECTS THE OTHER 30 SLUGS IS THE `~floored |` DISJUNCT, not the `.any()` (review m1, an
    # earlier comment here misattributed it). The bound this builds is month-start(horizon_end) for a
    # zero floor, which is NOT implied by the anchor filter and WOULD silently re-select -- so an
    # unfloored row has to be exempted ROW-WISE, and it is, which is what makes a MIXED frame (corn
    # and palm at one anchor) correct rather than merely rare. The `.any()` is an inert fast path: with
    # an all-zero `_fl`, `~floored` is all-True and the filter is already a no-op.
    _fl = _floor_months(work["leviathan_slug"])
    if _fl.any():
        floored = pd.Series(_fl > 0, index=work.index)
        bound = _floored_month_bound(work["horizon_end"], _fl)
        work = work[~floored | (work["_month"] >= bound)]
        if work.empty:
            return pd.DataFrame(columns=OUTCOME_CONTRACT_COLUMNS)

    lp = last_print.copy()
    if len(lp):
        lp["contract_month"] = lp["contract_month"].astype("string")
        lp["last_print_date"] = pd.to_datetime(lp["last_print_date"], errors="coerce")
    else:
        lp = pd.DataFrame(columns=["leviathan_slug", "contract_month", "last_print_date"])
    work = work.merge(lp, on=["leviathan_slug", "contract_month"], how="left")
    # THE SURVIVAL TEST. An unknown contract life is NOT a survival (notna() below is the fail-closed
    # half): the merge leaves NaT for a contract the tape never printed, and NaT >= x is False anyway,
    # but stating it makes the direction unmistakable to the next reader.
    need = work["horizon_end"] + pd.to_timedelta(int(survive_days), unit="D")
    work = work[work["last_print_date"].notna() & (work["last_print_date"] >= need)]
    if work.empty:
        return pd.DataFrame(columns=OUTCOME_CONTRACT_COLUMNS)

    work = work.sort_values(
        ["leviathan_slug", "trade_date", "_month", "contract_month"],
        ascending=[True, True, True, True], kind="mergesort")
    out = work.drop_duplicates(subset=["leviathan_slug", "trade_date"], keep="first").copy()
    out["survive_days"] = int(survive_days)
    out["outcome_rule_version"] = OUTCOME_CONTRACT_RULE_VERSION
    return out[OUTCOME_CONTRACT_COLUMNS].sort_values(
        ["leviathan_slug", "trade_date"], kind="mergesort").reset_index(drop=True)


def lint_roll_rule() -> list[str]:
    """Structural problems with the rule tables (pure; the config_check bind calls this).

    Covers exactly the drift a second inline copy would create anyway: an unmapped source, a
    cash reference that acquired a roll, a delivery-cycle slug with no curated cycle (or the
    reverse), and a bad month number."""
    errs: list[str] = []
    unknown = sorted(set(ROLL_METHOD_BY_SOURCE) - set(FC.SOURCES))
    if unknown:
        errs.append(f"ROLL_METHOD_BY_SOURCE names unknown source(s) {unknown}")
    uncovered = sorted(set(FC.SOURCES) - set(ROLL_METHOD_BY_SOURCE))
    if uncovered:
        errs.append(f"source(s) {uncovered} have NO front-month method -- every publication source "
                    f"must declare one here, never at a call site (F-L)")
    bad = sorted({m for m in ROLL_METHOD_BY_SOURCE.values() if m not in ROLL_METHODS})
    if bad:
        errs.append(f"unknown roll method(s) {bad} (legal: {list(ROLL_METHODS)})")
    # The INPUT CONTRACT covers exactly the methods -- a new method with no declared column would make
    # front_month_inputs_present raise (fail-closed) instead of answering, and a column declared for a
    # method that no longer exists is a stale contract nobody reads.
    if set(METHOD_METRIC_COL) != set(ROLL_METHODS):
        errs.append(f"METHOD_METRIC_COL keys {sorted(METHOD_METRIC_COL)} != the declared methods "
                    f"{sorted(ROLL_METHODS)} -- every method must name the column it READS (or None)")

    # The TABLE itself must agree with the cash-index short-circuit in roll_method_for. Without
    # this the 'cepea' entry could drift to 'volume' and nothing would notice, because
    # roll_method_for answers 'none' for those slugs before it ever reads the table.
    slugs_by_source: dict[str, set[str]] = {}
    for slug, rec in FC.CONTRACT_MAP.items():
        slugs_by_source.setdefault(rec["source"], set()).add(slug)
    for source, method in sorted(ROLL_METHOD_BY_SOURCE.items()):
        slugs = slugs_by_source.get(source, set())
        all_cash = bool(slugs) and slugs <= set(FC.CASH_INDEX_SLUGS)
        any_cash = bool(slugs & set(FC.CASH_INDEX_SLUGS))
        if all_cash and method != METHOD_NONE:
            errs.append(f"source {source!r} publishes only cash references {sorted(slugs)} but "
                        f"declares method {method!r} -- a cash index must never roll")
        if not any_cash and method == METHOD_NONE:
            errs.append(f"source {source!r} declares method 'none' but publishes futures "
                        f"{sorted(slugs)}")

    for slug in sorted(FC.CONTRACT_MAP):
        try:
            method = roll_method_for(slug)
        except ValueError as exc:
            errs.append(f"{slug}: {exc}")
            continue
        is_cash = slug in FC.CASH_INDEX_SLUGS
        if is_cash and method != METHOD_NONE:
            errs.append(f"{slug}: cash reference resolved to method {method!r} -- a cash index has "
                        f"no delivery-month axis and must never roll")
        if not is_cash and method == METHOD_NONE:
            errs.append(f"{slug}: futures contract resolved to method 'none'")
        if method == METHOD_DELIVERY_CYCLE and not DELIVERY_CYCLES.get(slug):
            errs.append(f"{slug}: delivery-cycle method with no curated DELIVERY_CYCLES entry")
        if method != METHOD_DELIVERY_CYCLE and slug in DELIVERY_CYCLES:
            errs.append(f"{slug}: has a DELIVERY_CYCLES entry but rolls by {method!r}")

    # V2-4 -- THE FORWARD-MONTH FLOOR TABLE, bound BOTH WAYS like DELIVERY_CYCLES above: every
    # floored slug is a real, non-cash contract carrying an int >= 1 (a 0 row is a lie -- it reads
    # as a curated decision and behaves as no rule at all), and the ACCESSOR agrees with the table
    # in both directions, so a caller can never read a floor the table does not declare.
    for slug, k in sorted(FORWARD_MONTH_FLOOR.items()):
        if slug not in FC.CONTRACT_MAP:
            errs.append(f"FORWARD_MONTH_FLOOR names unmapped slug {slug!r}")
        elif slug in FC.CASH_INDEX_SLUGS:
            errs.append(f"{slug}: a cash reference has no delivery-month axis to floor")
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            errs.append(f"{slug}: forward-month floor must be an int >= 1, got {k!r}")
        elif forward_month_floor(slug) != k:
            errs.append(f"{slug}: forward_month_floor() returns {forward_month_floor(slug)!r} "
                        f"but FORWARD_MONTH_FLOOR declares {k!r}")
    for slug in sorted(set(FC.CONTRACT_MAP) - set(FORWARD_MONTH_FLOOR)):
        if forward_month_floor(slug) != 0:
            errs.append(f"{slug}: has no FORWARD_MONTH_FLOOR row but the accessor returns "
                        f"{forward_month_floor(slug)!r} -- an unlisted slug IS the shipped rule")

    for slug, cycle in sorted(DELIVERY_CYCLES.items()):
        if slug not in FC.CONTRACT_MAP:
            errs.append(f"DELIVERY_CYCLES names unmapped slug {slug!r}")
            continue
        if not cycle or sorted(cycle) != list(cycle) or len(set(cycle)) != len(cycle):
            errs.append(f"{slug}: delivery cycle {cycle} must be non-empty, sorted and unique")
        outside = sorted({m for m in cycle if not 1 <= int(m) <= 12})
        if outside:
            errs.append(f"{slug}: delivery cycle carries non-month value(s) {outside}")
    if not ROLL_RULE_VERSION or not isinstance(ROLL_RULE_VERSION, str):
        errs.append("ROLL_RULE_VERSION must be a non-empty string")

    # OUTCOMES_JOIN J1.32: the survivor rule is a SECOND rule in this module and its provenance must be
    # distinguishable from the front-month rule's. Measured agreement between the two selections is only
    # 25.5-31.7% of anchors, so a shared version string would make two different answers look like one.
    if not OUTCOME_CONTRACT_RULE_VERSION or not isinstance(OUTCOME_CONTRACT_RULE_VERSION, str):
        errs.append("OUTCOME_CONTRACT_RULE_VERSION must be a non-empty string")
    if OUTCOME_CONTRACT_RULE_VERSION == ROLL_RULE_VERSION:
        errs.append(f"OUTCOME_CONTRACT_RULE_VERSION and ROLL_RULE_VERSION are both "
                    f"{ROLL_RULE_VERSION!r} -- the survivor selection is NOT front_month (measured "
                    f"agreement 25.5-31.7%); two rules, two version strings")
    if (isinstance(OUTCOME_SURVIVE_DAYS, bool) or not isinstance(OUTCOME_SURVIVE_DAYS, int)
            or OUTCOME_SURVIVE_DAYS < 1):
        errs.append(f"OUTCOME_SURVIVE_DAYS must be an int >= 1, got {OUTCOME_SURVIVE_DAYS!r} -- it is "
                    f"the survival MARGIN and it is half of the outcome PIT boundary")
    return errs


# Import-time fail-closed, mirroring futures_eod_contracts: a malformed rule table must never
# reach gate 7, W3.3 or the straddle rule.
assert not lint_roll_rule(), "futures_roll rule tables are malformed: " + "; ".join(lint_roll_rule())
