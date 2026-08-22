"""gold_board_crush compute core -- the CBOT soybean BOARD CRUSH, in USD per bushel.

WHY THIS TABLE EXISTS (D-EC DK-13)
----------------------------------
Board crush is the most-watched tradeable spread in the soy complex and it was a
DARK driver: sixteen causal-DAG instances across five margin ids
(``board_crush`` x4, ``soybean_crush_margin`` x8, ``rapeseed_crush_margin`` x2,
``import_crush_margin`` x1, ``canola_crush_margin`` x1), an entity_vocabulary
instrument entry -- and no numbers table behind any of them.  The corpus cannot
close that gap and never will: the outside-in census probed 449 documents for
desk market-mechanics language and found the phrase "board crush" in ZERO of
them (data/dec_p0/desk_ontology_diff.md, XC-3).  The instrument layer of the DAG
is unfeedable from text BY CONSTRUCTION, so it can only ever be numbers-bound.

Unlike almost every other dark driver this one needs no acquisition at all:
``silver_futures_eod`` already carries beans, meal and oil.  The card is
arithmetic.

WHY IT IS **gold** AND NOT silver
---------------------------------
This is the estate's first table derived from a published silver table, and the
naming follows the doctrine the estate already wrote down rather than inventing
a class for it.  ``configs/silver/tables/silver_futures_eod.yaml`` states:
"ROLL AND CONTINUOUS STAY OUT: no is_front_month, no is_roll_date, no
log_return, no adjusted series -- a stored front-month flag IS roll policy, and
roll policy is a QUERY-TIME decision; a continuous series would be a separate
derived **gold**_futures_continuous with its own roll_policy_version."
``futures_roll.py`` says the same thing in its module docstring.  A board-crush
row is exactly that object: a derived series that only exists once a roll policy
has been applied, and it therefore carries a ``roll_rule_version`` on every row.
``gold_weather_z`` is the shipped precedent for the shape -- ``lifecycle_class:
derived``, ``layer: gold``, flat, tiny, served straight from the numbers
registry -- and this table copies it file for file.

THE FORMULA, AND ITS UNITS
--------------------------
One bushel of soybeans weighs 60 lb and yields, on the standard board
convention, 44 lb of meal and 11 lb of oil::

    crush ($/bu) = 0.022 * meal   (USD per SHORT TON)
                 + 0.11  * oil    (US CENTS per POUND)
                 - 0.01  * beans  (US CENTS per BUSHEL)

Each coefficient is a unit conversion, not a fitted parameter:

  * meal  -- 44 lb = 44/2000 = **0.022** short ton, so tons x $/ton = $.
  * oil   -- 11 lb x (cents/lb) = 11 cents per cent-of-price; /100 to reach
             dollars gives **0.11**.
  * beans -- the CBOT bean quote is in CENTS per bushel; /100 gives **0.01**.

The three source units are read from ``futures_eod_contracts.CONTRACT_MAP`` and
asserted at runtime, so a venue re-quoting a leg (the MIAX cents-vs-dollars
class, corrected 2026-07-29) makes this transform REFUSE rather than silently
publish a number that is 100x wrong.

THE SECOND IMPLEMENTATION, NAMED RATHER THAN LEFT TO BE DISCOVERED
------------------------------------------------------------------
``leviathan.features.computations.sd_balance.compute_crush_margin_z`` already
computes this same margin with these same three coefficients, for the FEATURE
layer, off ``silver_futures_prices`` -- the yfinance continuous chain that W3
retires.  Two implementations of one number is precisely the failure mode
``futures_roll.py`` exists to prevent ("three rules, three answers, no version,
and a silent divergence the moment one of them is tweaked").

This module does NOT edit the feature layer: repointing a feature family changes
model inputs and is a separate, gated decision.  What it does instead is BIND
the two at the seam -- ``test_gold_board_crush.py`` asserts that the
coefficients here equal ``compute_crush_margin_z``'s defaults, so the two can
never drift apart silently, and the convergence (retire one, or repoint the
feature at this table when W3 lands) is recorded as a decision for the wave
owner rather than taken here.  The two are also honestly DIFFERENT objects
today: this one is a per-session LEVEL off per-delivery-month exchange
settlements under a named roll rule; that one is an annual z-score off a
continuous close.  They are versioned separately for that reason.

SCOPE: CBOT ONLY, DELIBERATELY
------------------------------
DK-13 also names the ZCE rapeseed crush and the DCE import crush.  Neither is
computable from what the platform holds: the DCE legs are quoted in CNY/t and
the ZCE legs in CNY/t, so a crush in those venues needs an FX leg and (for the
import crush) a freight leg, and this estate converts NOTHING at ingest -- units
are source-faithful by doctrine.  Those two are refused here, on the record,
rather than approximated.

THE INPUT CONTRACT IS ASKED PER TRADE DATE, NOT PER FRAME
---------------------------------------------------------
All three legs are ``databento_glbx_mdp3``, i.e. front-by-OPEN-INTEREST, and
``futures_roll.front_month_inputs_present`` fails closed when ANY candidate row
of such a slug carries no readable open interest.  That frame-level granularity
is CORRECT for the function's other callers and it is deliberately not changed
here -- but asked once over the whole 153,806-row history it is an all-or-nothing
question, and the measured tape answers NO: the first real fire refused
everything on it.

MEASURED 2026-08-20 over the full published tape (read-only S3, 153,806 rows,
4,184 distinct trade dates):

  * **2010-06-06 .. 2015-11-18 -- open interest does not exist at all.**  Not a
    sparse gap: ZERO of the three legs' rows carry OI in that window, on any
    contract, on any session (1,485 dates).  The GLBX ``statistics`` schema --
    the $1.76 buy that IS the front-by-OI rule's data dependency -- simply does
    not cover it.  Front-by-OI is an unanswerable question there, and this table
    says so rather than quietly rolling by nearness under front_month_v2's name.
  * **2015-11-19 onward -- OI is present, and 47 sessions in ten years are not.**
    Two shapes, both genuine absences: whole-session statistics blackouts (the
    year-end sessions Dec 30/31, plus one-offs like 2018-02-23, 2018-08-05,
    2020-02-27, 2026-08-03), and the final print of an EXPIRING contract, which
    is still eligible under the month-start rule and carries volume in the
    single digits but no OI (2016-05-13, 2017-05-12, 2024-01-12 ...).
  * The most recent session is routinely among them: OI lands a day behind the
    settlement, so a run at T sees T-1 as the last readable date.

So the crush is computable on 2,652 of 4,184 dates and genuinely uncomputable on
1,532.  The decision is therefore made PER TRADE DATE and it is BINARY: a date
whose every leg satisfies the rule's own input contract emits exactly as before;
a date where any leg does not is REFUSED, alone, and counted.  Nothing is
filled, no tie-break is worked around, and no partially-readable date is let
through -- which is the same refusal the frame-level check makes, at the
granularity the data actually varies on.  The refusal is WRITTEN
(:class:`DateContractLedger`, carried out on the returned frame's ``.attrs``
under :data:`REFUSED_DATES`), because 1,532 silently absent sessions and 1,532
declared ones are very different objects to a reader.

Pure: pandas + the house contract map + the ONE roll rule.  No S3, no AWS, no
side effects -- ``jobs/batch/gold_board_crush_task.py`` is the I/O shell.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC
from leviathan.silver import futures_roll as FR

logger = get_logger(__name__)

# BUMP THIS when the emitted number's definition changes (a coefficient, a leg, a
# selection rule).  A consumer that stored a crush under one version must not
# compare it against another.  Never reuse a version for a changed definition --
# the ROLL_RULE_VERSION discipline, applied to the arithmetic on top of it.
CRUSH_RULE_VERSION = "cbot_board_crush_v1"

# The three legs, by role.  Keys are the roles the formula names; values are the
# contract slugs.  CBOT only -- see the module docstring's SCOPE note.
CRUSH_LEGS: dict[str, str] = {
    "beans": "soybeans_cbot",
    "meal": "soybean_meal_cbot",
    "oil": "soybean_oil_cbot",
}

# The unit each leg MUST be quoted in for the coefficients below to be correct.
# Asserted at runtime against CONTRACT_MAP, which is the single source the
# physical `unit` column of silver_futures_eod is written from.
CRUSH_LEG_UNITS: dict[str, str] = {
    "beans": "US cents/bushel",
    "meal": "USD/short ton",
    "oil": "US cents/lb",
}

# Unit conversions, not fitted parameters.  See the docstring for the derivation
# of each.  Bound by test to features.computations.sd_balance's defaults.
MEAL_COEF = 0.022    # 44 lb meal / 2000 lb per short ton
OIL_COEF = 0.11      # 11 lb oil, cents -> dollars
BEAN_COEF = 0.01     # cents/bushel -> dollars/bushel

# The output's physical column order.  Declaration order IS writer order under
# the INV-2 pinned-schema doctrine, so this list is the contract.
PHYSICAL_COLUMNS: list[str] = [
    "trade_date",
    "crush_margin_usd_bu",
    "meal_value_usd_bu",
    "oil_value_usd_bu",
    "bean_cost_usd_bu",
    "beans_contract_month",
    "meal_contract_month",
    "oil_contract_month",
    "beans_settle",
    "meal_settle",
    "oil_settle",
    "settle_kind",
    "is_roll_boundary",
    "roll_rule_version",
    "crush_rule_version",
]

# The columns this transform needs off silver_futures_eod.  open_interest is not
# optional: all three legs are databento_glbx_mdp3, whose roll method is
# front-by-OPEN-INTEREST, and futures_roll.front_month_inputs_present fails
# closed without it.
INPUT_COLUMNS: list[str] = [
    "leviathan_slug", "trade_date", "contract_month", "settle",
    "settle_kind", "unit", "open_interest", "volume", "instrument_kind", "source",
]

# The ``.attrs`` key the per-date refusal ledger rides out on.  It is set on EVERY
# return path including the empty ones, so a total refusal is exactly as readable
# as a partial one -- an empty gold frame that cannot say WHY it is empty is the
# thing that cost this table its first fire.
REFUSED_DATES = "board_crush_refused_dates"


@dataclass(frozen=True)
class DateContractLedger:
    """WHICH trade dates the roll rule could be asked about, and which it could not.

    ``readable`` and ``refused`` partition the input's distinct trade dates; a date
    is in exactly one of them and never in both.  ``refused_by_role`` says WHICH
    leg or legs did the refusing (a date can be refused by more than one, so the
    per-role counts do not sum to ``n_refused``).  Dates are ``YYYY-MM-DD``
    strings, sorted, exactly as they are emitted on a crush row."""

    readable: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    refused_by_role: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def n_readable(self) -> int:
        return len(self.readable)

    @property
    def n_refused(self) -> int:
        return len(self.refused)

    @property
    def n_dates(self) -> int:
        return self.n_readable + self.n_refused

    def render(self) -> str:
        """The WRITTEN refusal, one ASCII line (the console is cp1252)."""
        if not self.n_dates:
            return "board crush: no trade dates in the input at all"
        by_leg = " ".join(
            f"{role}({CRUSH_LEGS[role]})={len(self.refused_by_role.get(role, ()))}"
            for role in CRUSH_LEGS
        )
        span = (f"{self.refused[0]}..{self.refused[-1]}" if self.refused else "-")
        read_span = (f"{self.readable[0]}..{self.readable[-1]}" if self.readable else "-")
        return (
            f"board crush: the roll rule's input contract REFUSED {self.n_refused} of "
            f"{self.n_dates} trade dates ({span}); per leg: {by_leg}; "
            f"readable {self.n_readable} ({read_span}). All three legs are GLBX, i.e. "
            f"front-by-open-interest -- a refused date has a leg whose eligible candidate "
            f"set carries no readable open interest, and emitting one would publish a "
            f"crush selected by a degraded rule."
        )


def _with_ledger(gold: pd.DataFrame, ledger: DateContractLedger) -> pd.DataFrame:
    """Attach the ledger to the frame.  Last thing before every return: pandas does
    not promise ``.attrs`` survives a column selection or a merge, so it is set once,
    on the object the caller actually receives."""
    gold.attrs[REFUSED_DATES] = ledger
    return gold


def _eligible_candidates(legs: pd.DataFrame) -> pd.DataFrame:
    """The rows :func:`futures_roll.front_month` will actually READ, with the trade
    date parsed into ``_trade_date``.

    Eligibility mirrors the rule's own: a contract not yet in delivery, i.e. its
    ``contract_month`` month-start is at or after the trade date's month-start.  The
    ``YYYY-MM`` parse is futures_roll's own ``_month_start`` rather than a second
    copy of it -- re-declaring the predicate here is exactly the F-L drift that
    module exists to prevent, and ``config_check.check_futures_roll``'s source fence
    would never see it.

    The rule's OTHER eligibility clause (a delivery-cycle slug's listed months) is
    not mirrored because no crush leg uses that method -- all three are GLBX.  If one
    ever did, this set would be a SUPERSET of what the rule reads, which errs toward
    refusing a date rather than toward emitting a degraded one."""
    work = legs.copy()
    work["_trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    work = work[work["_trade_date"].notna()]
    work["_month"] = FR._month_start(work["contract_month"])
    work = work[work["_month"].notna()]
    if work.empty:
        return work
    work["_trade_month"] = work["_trade_date"].values.astype("datetime64[M]")
    return work[work["_month"] >= pd.to_datetime(work["_trade_month"])]


def date_contract_ledger(legs: pd.DataFrame) -> DateContractLedger:
    """Ask the roll rule's input contract ONCE PER (trade date, leg), and partition
    the dates by the answer.

    The question is :func:`futures_roll.front_month_inputs_present`'s, unchanged and
    un-restated -- it is handed each leg's eligible candidate set for one session and
    its verdict is taken as-is.  A leg with NO eligible candidate on a date is refused
    by that same function (an empty frame is not a satisfied precondition), which is
    also what the three-leg inner join would do to the date one step later; counting
    it here just means the drop is written down.

    ``legs`` must already be narrowed to :data:`CRUSH_LEGS`.

    COST: one call to the contract per (leg, session) -- ~12,500 calls and ~17s
    over the full published tape.  That is deliberate and it is not worth
    optimising away: any vectorised shortcut here would be a second reading of
    METHOD_METRIC_COL, i.e. the F-L drift in the one place it is hardest to see,
    and this job runs once a day behind a 51-object S3 read."""
    elig = _eligible_candidates(legs)
    dates = sorted({d.strftime("%Y-%m-%d")
                    for d in pd.to_datetime(legs["trade_date"], errors="coerce").dropna()})
    if not dates:
        return DateContractLedger()

    by_role: dict[str, list[str]] = {role: [] for role in CRUSH_LEGS}
    if len(elig):
        satisfied = {
            (str(slug), day.strftime("%Y-%m-%d"))
            for (slug, day), group in elig.groupby(["leviathan_slug", "_trade_date"], sort=False)
            if FR.front_month_inputs_present(group)
        }
    else:
        satisfied = set()
    for role, slug in CRUSH_LEGS.items():
        for day in dates:
            if (slug, day) not in satisfied:
                by_role[role].append(day)

    refused = sorted({d for days in by_role.values() for d in days})
    refused_set = set(refused)
    return DateContractLedger(
        readable=tuple(d for d in dates if d not in refused_set),
        refused=tuple(refused),
        refused_by_role={role: tuple(days) for role, days in by_role.items()},
    )


def _assert_leg_units() -> None:
    """Refuse to compute if any leg is no longer quoted in the assumed unit.

    The coefficients ARE the unit conversion, so a venue re-quote silently makes
    every published number wrong by a factor of 100 (the MIAX cents-vs-dollars
    class, which measuring caught in the price wave).  Fail closed, loudly, at
    the top -- never scale a value to match a prior assumption."""
    for role, slug in CRUSH_LEGS.items():
        rec = FC.CONTRACT_MAP.get(slug)
        if rec is None:
            raise ValueError(
                f"board crush: leg {role!r} slug {slug!r} is not in CONTRACT_MAP -- the crush "
                f"cannot be computed against a contract the estate does not describe"
            )
        want = CRUSH_LEG_UNITS[role]
        if rec["unit"] != want:
            raise ValueError(
                f"board crush: leg {role!r} ({slug}) is quoted {rec['unit']!r}, but the "
                f"coefficients assume {want!r}. The coefficients ARE the unit conversion, so "
                f"this would publish a number wrong by a constant factor. Re-derive "
                f"MEAL_COEF/OIL_COEF/BEAN_COEF and BUMP CRUSH_RULE_VERSION; never rescale the "
                f"value to match the old assumption."
            )


def empty_gold() -> pd.DataFrame:
    """An empty frame with the exact output schema (dtypes included)."""
    return pd.DataFrame({
        "trade_date":           pd.Series([], dtype="object"),
        "crush_margin_usd_bu":  pd.Series([], dtype="float64"),
        "meal_value_usd_bu":    pd.Series([], dtype="float64"),
        "oil_value_usd_bu":     pd.Series([], dtype="float64"),
        "bean_cost_usd_bu":     pd.Series([], dtype="float64"),
        "beans_contract_month": pd.Series([], dtype="object"),
        "meal_contract_month":  pd.Series([], dtype="object"),
        "oil_contract_month":   pd.Series([], dtype="object"),
        "beans_settle":         pd.Series([], dtype="float64"),
        "meal_settle":          pd.Series([], dtype="float64"),
        "oil_settle":           pd.Series([], dtype="float64"),
        "settle_kind":          pd.Series([], dtype="object"),
        "is_roll_boundary":     pd.Series([], dtype="object"),
        "roll_rule_version":    pd.Series([], dtype="object"),
        "crush_rule_version":   pd.Series([], dtype="object"),
    })


def compute_board_crush(eod: pd.DataFrame) -> pd.DataFrame:
    """``silver_futures_eod`` rows -> the gold board-crush series.

    Args:
        eod: per-delivery-month EOD rows.  Must carry :data:`INPUT_COLUMNS`.
             Rows for slugs other than the three CBOT legs are ignored, so a
             caller may pass a wider frame.

    Returns:
        One row per ``trade_date`` on which ALL THREE legs printed a front-month
        settle AND the roll rule's input contract was satisfied, ordered by date,
        with :data:`PHYSICAL_COLUMNS`.  The :class:`DateContractLedger` for the
        call rides out on ``.attrs[REFUSED_DATES]``.

    Raises:
        ValueError: if a required input column is missing, or if a leg's quoted
                    unit no longer matches the coefficients' assumption.

    THE THREE-LEG RULE.  A session is emitted only when beans, meal AND oil all
    have a front-month settle on that date.  A crush computed from two legs and
    a stale third is not a wider series, it is a wrong one -- so the missing
    session is DROPPED rather than forward-filled.  That is the same posture the
    price layer takes toward a straddling window: decline, never splice.

    THE INPUT-CONTRACT RULE, one granularity down.  The roll rule can only be
    asked about a session whose every leg carries the input it reads; the
    measured tape has 1,532 sessions where it cannot be (see the module
    docstring).  Those dates are refused INDIVIDUALLY and written down, never
    filled and never tie-broken around, and their neighbours are unaffected.
    """
    _assert_leg_units()

    if eod is None or len(eod) == 0:
        return _with_ledger(empty_gold(), DateContractLedger())
    missing = [c for c in ("leviathan_slug", "trade_date", "contract_month", "settle")
               if c not in eod.columns]
    if missing:
        raise ValueError(
            f"compute_board_crush: frame is missing {missing} -- the crush reads "
            f"silver_futures_eod's own columns and cannot infer them"
        )

    legs = eod[eod["leviathan_slug"].isin(CRUSH_LEGS.values())].copy()
    if legs.empty:
        logger.warning("board crush: no rows for any of the three CBOT legs")
        return _with_ledger(empty_gold(), DateContractLedger())

    # THE ONE ROLL RULE.  Never a second copy: config_check.check_futures_roll
    # fails the build if a competing front-month implementation appears anywhere
    # under src/ jobs/ scripts/, and this transform is exactly the kind of place
    # a fourth inline copy would otherwise be born.  What IS decided here is only
    # the GRANULARITY the rule's own precondition is asked at -- per trade date,
    # because that is the axis the tape's open-interest coverage varies on.
    ledger = date_contract_ledger(legs)
    if ledger.n_refused:
        logger.warning("%s", ledger.render())
    if not ledger.readable:
        logger.warning(
            "board crush: EVERY one of the %d trade dates failed the roll rule's input "
            "contract; emitting nothing rather than a crush selected by a degraded rule",
            ledger.n_dates)
        return _with_ledger(empty_gold(), ledger)

    # Refused dates leave here and never come back: no fill, no carry, no
    # neighbour standing in for them.  front_month gets the FULL row set for the
    # dates that survive -- including any row its own eligibility filter will
    # drop -- because narrowing its candidate set here would be this module
    # selecting the contract, which is the one thing it must not do.
    keep = pd.to_datetime(legs["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    legs = legs[keep.isin(set(ledger.readable))]

    front = FR.front_month(legs)
    if front.empty:
        return _with_ledger(empty_gold(), ledger)

    keep = ["leviathan_slug", "trade_date", "contract_month", "settle", "settle_kind"]
    keep = [c for c in keep if c in front.columns]
    f = front[keep].copy()
    f["trade_date"] = pd.to_datetime(f["trade_date"], errors="coerce")
    f = f[f["trade_date"].notna()]

    parts: dict[str, pd.DataFrame] = {}
    for role, slug in CRUSH_LEGS.items():
        part = f[f["leviathan_slug"] == slug].drop(columns=["leviathan_slug"])
        part = part.rename(columns={
            "settle": f"{role}_settle",
            "contract_month": f"{role}_contract_month",
            "settle_kind": f"{role}_settle_kind",
        })
        # One front contract per (slug, trade_date) is front_month's own
        # guarantee; assert it rather than trusting it, because a silent
        # duplicate here would fan the crush out into a cross join.
        if part.duplicated(subset=["trade_date"]).any():
            raise ValueError(
                f"board crush: leg {role!r} has more than one front-month row on a trade date -- "
                f"front_month's per-(slug, date) uniqueness was violated"
            )
        parts[role] = part

    # INNER joins: the three-leg rule, enforced by the join itself.
    out = parts["beans"]
    for role in ("meal", "oil"):
        out = out.merge(parts[role], on="trade_date", how="inner")
    if out.empty:
        logger.warning("board crush: no session has all three legs; emitting nothing")
        return _with_ledger(empty_gold(), ledger)

    for role in CRUSH_LEGS:
        out[f"{role}_settle"] = pd.to_numeric(out[f"{role}_settle"], errors="coerce")
    out = out.dropna(subset=[f"{role}_settle" for role in CRUSH_LEGS])
    if out.empty:
        return _with_ledger(empty_gold(), ledger)

    out["meal_value_usd_bu"] = MEAL_COEF * out["meal_settle"]
    out["oil_value_usd_bu"] = OIL_COEF * out["oil_settle"]
    out["bean_cost_usd_bu"] = BEAN_COEF * out["beans_settle"]
    out["crush_margin_usd_bu"] = (
        out["meal_value_usd_bu"] + out["oil_value_usd_bu"] - out["bean_cost_usd_bu"]
    )

    # settle_kind travels with the number for the same reason it travels with a
    # futures_eod row: a crush built from session CLOSES is a different object
    # from one built from official SETTLEMENTS, and a reader must be able to
    # tell.  All three legs share a venue today, so the honest single label is
    # the shared one; a mixed session says so explicitly instead of picking one.
    kinds = [f"{role}_settle_kind" for role in CRUSH_LEGS
             if f"{role}_settle_kind" in out.columns]
    if kinds:
        stacked = out[kinds].astype("string")
        same = stacked.nunique(axis=1, dropna=False) == 1
        out["settle_kind"] = stacked[kinds[0]].where(same, "mixed")
    else:
        out["settle_kind"] = pd.NA

    out["roll_rule_version"] = FR.ROLL_RULE_VERSION
    out["crush_rule_version"] = CRUSH_RULE_VERSION
    out["trade_date"] = out["trade_date"].dt.strftime("%Y-%m-%d")

    out = out.sort_values("trade_date", kind="mergesort").reset_index(drop=True)

    # IS_ROLL_BOUNDARY (GN-2 W1.3, 2026-08-22).  '1' on a session where ANY leg's front contract
    # differs from that leg's front contract on the PREVIOUS EMITTED session, else '0'.  The crush
    # steps at every roll for reasons that are not market moves -- 2022-06-02's sole negative print
    # was old-crop beans against new-crop products for one session -- so a change window whose
    # endpoint lands on a roll step narrates a contract change as a market move.  The LEVEL still
    # emits (it is a real settled number); the column lets readers EXCLUDE these sessions
    # (Metric.row_filters on the card does exactly that for every served read).  A STRING '0'/'1',
    # not a bool and not an int, and that is load-bearing: build_sql's row_filters emit is a QUOTED
    # literal with no CAST (`col IN ('0')`), which errors on an Athena INT column and silently
    # diverges on a bool (Python str(True)='True' vs SQL 'true'); the pg mirror's type doctrine
    # routes every non-metric column to TEXT anyway, so a string is the ONE type all three backends
    # (Athena, pg, the pure-Python oracle) compare identically.
    # A gap of refused dates between two emitted rows still marks correctly: the comparison is
    # contract identity between consecutive EMITTED rows, which is the axis change math runs on.
    # The first emitted row is '0' (no prior row -- no change is computed from it either).
    # CRUSH_RULE_VERSION is NOT bumped: the emitted margin's definition is unchanged; this column
    # only DESCRIBES the roll structure the rule already produced.
    month_cols = [f"{role}_contract_month" for role in CRUSH_LEGS]
    stepped = (out[month_cols] != out[month_cols].shift(1)).any(axis=1)
    if len(stepped):
        stepped.iloc[0] = False
    out["is_roll_boundary"] = stepped.map({True: "1", False: "0"}).astype("object")

    out = out[PHYSICAL_COLUMNS]

    logger.info(
        "board crush: rows=%d first=%s last=%s rule=%s roll=%s refused_dates=%d",
        len(out), out["trade_date"].iloc[0], out["trade_date"].iloc[-1],
        CRUSH_RULE_VERSION, FR.ROLL_RULE_VERSION, ledger.n_refused,
    )
    return _with_ledger(out, ledger)
