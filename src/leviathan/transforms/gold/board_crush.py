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

Pure: pandas + the house contract map + the ONE roll rule.  No S3, no AWS, no
side effects -- ``jobs/batch/gold_board_crush_task.py`` is the I/O shell.
"""
from __future__ import annotations

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
        settle, ordered by date, with :data:`PHYSICAL_COLUMNS`.

    Raises:
        ValueError: if a required input column is missing, or if a leg's quoted
                    unit no longer matches the coefficients' assumption.

    THE THREE-LEG RULE.  A session is emitted only when beans, meal AND oil all
    have a front-month settle on that date.  A crush computed from two legs and
    a stale third is not a wider series, it is a wrong one -- so the missing
    session is DROPPED rather than forward-filled.  That is the same posture the
    price layer takes toward a straddling window: decline, never splice.
    """
    _assert_leg_units()

    if eod is None or len(eod) == 0:
        return empty_gold()
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
        return empty_gold()

    # THE ONE ROLL RULE.  Never a second copy: config_check.check_futures_roll
    # fails the build if a competing front-month implementation appears anywhere
    # under src/ jobs/ scripts/, and this transform is exactly the kind of place
    # a fourth inline copy would otherwise be born.
    if not FR.front_month_inputs_present(legs):
        logger.warning(
            "board crush: the roll rule's input contract is not satisfied by these rows "
            "(all three legs are GLBX, i.e. front-by-open-interest); emitting nothing "
            "rather than a crush selected by a degraded rule")
        return empty_gold()
    front = FR.front_month(legs)
    if front.empty:
        return empty_gold()

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
        return empty_gold()

    for role in CRUSH_LEGS:
        out[f"{role}_settle"] = pd.to_numeric(out[f"{role}_settle"], errors="coerce")
    out = out.dropna(subset=[f"{role}_settle" for role in CRUSH_LEGS])
    if out.empty:
        return empty_gold()

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
    out = out[PHYSICAL_COLUMNS]

    logger.info(
        "board crush: rows=%d first=%s last=%s rule=%s roll=%s",
        len(out), out["trade_date"].iloc[0], out["trade_date"].iloc[-1],
        CRUSH_RULE_VERSION, FR.ROLL_RULE_VERSION,
    )
    return out
