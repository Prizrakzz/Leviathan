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
ROLL_RULE_VERSION = "front_month_v1"

# The four methods. "none" is not an absence of a rule; it is the ASSERTION that the question does
# not apply (cash references), which is why it is a first-class value rather than a missing key.
METHOD_OPEN_INTEREST = "open_interest"
METHOD_VOLUME = "volume"
METHOD_DELIVERY_CYCLE = "delivery_cycle"
METHOD_NONE = "none"
ROLL_METHODS: tuple[str, ...] = (
    METHOD_OPEN_INTEREST, METHOD_VOLUME, METHOD_DELIVERY_CYCLE, METHOD_NONE,
)

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
    # Settle-only bulletins: neither OI nor volume survives the publication, so the front month is
    # a curated calendar fact. DCE sits here for now -- the /dcereport JSON does carry volume, so
    # when the W1c producer lands and proves it, move DCE to METHOD_VOLUME (and bump the version).
    "bursa": METHOD_DELIVERY_CYCLE,
    "miax": METHOD_DELIVERY_CYCLE,
    "euronext_matif": METHOD_DELIVERY_CYCLE,
    "dce": METHOD_DELIVERY_CYCLE,
    # The two CEPEA cash references have no delivery month at all.
    "cepea": METHOD_NONE,
}

# Curated listing cycles for the delivery-cycle slugs: the delivery MONTH NUMBERS the venue lists.
# Front = the nearest listed month not yet in delivery. Every METHOD_DELIVERY_CYCLE slug must
# appear here and nothing else may (check_futures_roll asserts both directions).
DELIVERY_CYCLES: dict[str, tuple[int, ...]] = {
    # Bursa FCPO lists all twelve consecutive calendar months.
    "malaysian_crude_palm_oil_cme": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12),
    # MIAX (ex-MGEX) hard red spring wheat: the classic Mar/May/Jul/Sep/Dec grain cycle.
    "hard_red_spring_wheat_mgex": (3, 5, 7, 9, 12),
    # Euronext/MATIF listed cycles.
    "french_wheat_matif": (3, 5, 9, 12),
    "french_maize_matif": (3, 6, 8, 11),
    "french_rapeseed_matif": (2, 5, 8, 11),
    # DCE lists all twelve months but liquidity concentrates in the Jan/May/Sep "main" contracts;
    # a nearest-calendar-month rule would name a near-dead contract most of the year. This is the
    # weakest curation in the table and is explicitly PROVISIONAL -- it goes away when the W1c DCE
    # producer lands volume and the source moves to METHOD_VOLUME.
    "palm_olein_dce": (1, 5, 9),
    "soybean_meal_dce": (1, 5, 9),
    "soybean_oil_dce": (1, 5, 9),
    "soybeans_no_1_dce": (1, 5, 9),
    "soybeans_no_2_dce": (1, 5, 9),
}

FRONT_MONTH_COLUMNS: list[str] = [
    "leviathan_slug", "trade_date", "contract_month", "raw_symbol", "settle", "close",
    "volume", "open_interest", "unit", "currency", "settle_kind", "source",
    "roll_method", "roll_rule_version",
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

    # Eligibility: not yet in delivery, and (delivery-cycle slugs only) a LISTED month.
    work["_trade_month"] = work["trade_date"].values.astype("datetime64[M]")
    work = work[work["_month"] >= pd.to_datetime(work["_trade_month"])]
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


def legacy_volume_front(df: pd.DataFrame) -> pd.DataFrame:
    """FRONT-BY-VOLUME selection for the RETIREMENT-SOAK PARITY comparison ONLY. Not the D8 rule.

    MEASURED 2026-07-29 (corn, last 250 sessions, four-way comparison): the yfinance continuous
    lane ROLLS BY VOLUME and its daily "close" is the SETTLEMENT print --
    front-by-volume x settle reproduced silver_futures_prices.close with median |rel diff|
    0.00000 (exact), while the D8 front-by-OI choice sits ~2.1% away because the OI leader
    shifts to the next month days before the volume leader follows. A parity gate comparing
    the new table against that lane must therefore EMULATE THE LANE'S OWN SELECTION, or it
    measures a calendar spread instead of decode fidelity.

    Lives in THIS module -- the single home for roll selection (skeptic F-L: inline copies are
    the failure mode) -- and shares front_month's eligibility exactly (futures rows only, not
    yet in delivery). The serving rule remains front_month/ROLL_RULE_VERSION; this function is
    pinned to the legacy lane and RETIRES WITH IT."""
    cols = ["leviathan_slug", "trade_date", "contract_month"]
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=FRONT_MONTH_COLUMNS)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"legacy_volume_front: frame is missing {missing}")
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
    vol = pd.to_numeric(work["volume"], errors="coerce")
    work["_metric"] = vol.fillna(-1.0)
    work["roll_method"] = "legacy_volume"
    work = work.sort_values(
        ["leviathan_slug", "trade_date", "_metric", "_month", "contract_month"],
        ascending=[True, True, False, True, True], kind="mergesort")
    out = work.drop_duplicates(subset=["leviathan_slug", "trade_date"], keep="first").copy()
    out["roll_rule_version"] = ROLL_RULE_VERSION
    return out[FRONT_MONTH_COLUMNS].sort_values(
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
    return errs


# Import-time fail-closed, mirroring futures_eod_contracts: a malformed rule table must never
# reach gate 7, W3.3 or the straddle rule.
assert not lint_roll_rule(), "futures_roll rule tables are malformed: " + "; ".join(lint_roll_rule())
