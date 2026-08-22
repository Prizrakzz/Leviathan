"""gold_futures_spreads compute core -- same-unit two-leg futures spreads (GN-2 W2.3).

WHY THIS TABLE EXISTS. The causal DAGs carry `spread` refs the map refused for two measured reasons
(the C3 register): every served futures metric is a single-leg level, and a spread needs two contracts
in one leg. This table IS the two-contract leg: a derived gold series (the gold_board_crush shape,
copied deliberately -- front-month legs under the ONE roll rule, refusal ledger, rule versions on
every row) for the spread pairs whose BOTH legs the platform already serves.

THE V1 PAIRS, AND THE REFUSALS BESIDE THEM (the recon's measured roster):
  * kc_chi        -- hard_red_winter_wheat_kcbt minus soft_red_winter_wheat_cbot, US cents/bushel.
                     The HRW-SRW protein premium, the wheat desk's class-spread currency.
  * white_yellow  -- south_african_white_maize_jse minus south_african_yellow_maize_jse, ZAR/t.
                     The white-maize food premium over yellow feed maize.
  * arabica_robusta DEFERRED: the robusta leg's 14-session staleness would narrate a spread whose two
                     legs are two weeks apart -- a fabricated simultaneity. Lands when the staleness is
                     fixed at source, not papered over here.
  * palm/olein premiums BLOCKED: DCE/Bursa raw has never landed (KeyCount ZERO; the venue-acquisition
                     owner decision).

SAME-UNIT IS THE LAW OF THIS TABLE. A spread is subtraction, and subtraction is only meaningful inside
one unit and one currency: both legs' CONTRACT_MAP units are asserted EQUAL at runtime (the MIAX
cents-vs-dollars class -- a venue re-quote makes this transform REFUSE, never publish a number wrong by
a constant factor). Cross-currency spreads (the palm premium's future) need an FX leg this estate does
not convert at ingest -- refused here, on the record.

LONG SHAPE, ONE UNIT COLUMN. One row per (spread_id, trade_date); `unit` rides every row because the
table spans currencies ACROSS spreads (cents/bu vs ZAR/t) while each SPREAD is single-unit by the law
above. The numbers card serves per-spread units via unit_overrides (the DP-1 mechanism, built for
exactly this shape).

IS_ROLL_BOUNDARY from day one (the crush lesson, not relearned): '1' when either leg's front contract
differs from the previous emitted session's -- the series steps there because the CONTRACTS changed,
not the market. STRING '0'/'1' for the three-backend comparison identity (see the crush producer's
comment). The card's row_filters exclude those sessions from every served read.

THE PER-DATE INPUT CONTRACT (the crush's granularity decision, inherited): a session is emitted only
when BOTH legs printed a front-month settle AND the roll rule's own input contract was satisfied on
each; refused dates are WRITTEN (the ledger on ``.attrs``), never filled and never tie-broken around.

Pure: pandas + the house contract map + the ONE roll rule. No S3, no AWS --
``jobs/batch/gold_futures_spreads_task.py`` is the I/O shell.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC
from leviathan.silver import futures_roll as FR

logger = get_logger(__name__)

# BUMP on any change to a spread's definition (a leg, a sign, a selection rule). Never reuse a
# version for a changed definition -- the CRUSH_RULE_VERSION discipline.
SPREAD_RULE_VERSION = "futures_spreads_v1"

# The registry: spread_id -> (long leg, short leg). value = long_settle - short_settle.
SPREADS: dict[str, tuple[str, str]] = {
    "kc_chi": ("hard_red_winter_wheat_kcbt", "soft_red_winter_wheat_cbot"),
    "white_yellow": ("south_african_white_maize_jse", "south_african_yellow_maize_jse"),
}

PHYSICAL_COLUMNS: list[str] = [
    "spread_id",
    "trade_date",
    "spread_value",
    "unit",
    "long_slug",
    "short_slug",
    "long_contract_month",
    "short_contract_month",
    "long_settle",
    "short_settle",
    "settle_kind",
    "is_roll_boundary",
    "roll_rule_version",
    "spread_rule_version",
]

INPUT_COLUMNS: list[str] = [
    "leviathan_slug", "trade_date", "contract_month", "settle",
    "settle_kind", "unit", "open_interest", "volume", "instrument_kind", "source",
]

REFUSED_DATES = "futures_spreads_refused_dates"


@dataclass(frozen=True)
class SpreadLedger:
    """Per-spread partition of trade dates by the roll rule's input contract (the crush's
    DateContractLedger shape, per spread)."""

    spread_id: str = ""
    readable: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    refused_by_leg: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def render(self) -> str:
        span = (f"{self.refused[0]}..{self.refused[-1]}" if self.refused else "-")
        by_leg = " ".join(f"{slug}={len(days)}" for slug, days in self.refused_by_leg.items())
        return (f"{self.spread_id}: input contract REFUSED {len(self.refused)} of "
                f"{len(self.readable) + len(self.refused)} dates ({span}); per leg: {by_leg}")


def _assert_same_unit(spread_id: str, long_slug: str, short_slug: str) -> str:
    """Both legs' declared unit AND currency must be identical -- subtraction across either is a
    number wearing the wrong label. Returns the shared unit. Fail closed, loudly, at the top."""
    a, b = FC.CONTRACT_MAP.get(long_slug), FC.CONTRACT_MAP.get(short_slug)
    for slug, rec in ((long_slug, a), (short_slug, b)):
        if rec is None:
            raise ValueError(f"{spread_id}: leg {slug!r} is not in CONTRACT_MAP")
    if a["unit"] != b["unit"] or a.get("currency") != b.get("currency"):
        raise ValueError(
            f"{spread_id}: legs are quoted {a['unit']!r}/{a.get('currency')!r} vs "
            f"{b['unit']!r}/{b.get('currency')!r} -- a spread across units or currencies is "
            f"REFUSED (same-unit law; re-derive the pair and BUMP SPREAD_RULE_VERSION)"
        )
    return a["unit"]


def _eligible_candidates(legs: pd.DataFrame) -> pd.DataFrame:
    """The rows front_month will actually READ (the crush's eligibility mirror -- futures_roll's own
    ``_month_start``, never a second copy of the predicate)."""
    work = legs.copy()
    work["_trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    work = work[work["_trade_date"].notna()]
    work["_month"] = FR._month_start(work["contract_month"])
    work = work[work["_month"].notna()]
    if work.empty:
        return work
    work["_trade_month"] = work["_trade_date"].values.astype("datetime64[M]")
    return work[work["_month"] >= pd.to_datetime(work["_trade_month"])]


def _spread_ledger(spread_id: str, legs: pd.DataFrame, slugs: tuple[str, str]) -> SpreadLedger:
    """Ask front_month_inputs_present once per (leg, session); partition the dates by the answer."""
    elig = _eligible_candidates(legs)
    dates = sorted({d.strftime("%Y-%m-%d")
                    for d in pd.to_datetime(legs["trade_date"], errors="coerce").dropna()})
    if not dates:
        return SpreadLedger(spread_id=spread_id)
    satisfied = set()
    if len(elig):
        satisfied = {
            (str(slug), day.strftime("%Y-%m-%d"))
            for (slug, day), group in elig.groupby(["leviathan_slug", "_trade_date"], sort=False)
            if FR.front_month_inputs_present(group)
        }
    by_leg: dict[str, list[str]] = {s: [] for s in slugs}
    for slug in slugs:
        for day in dates:
            if (slug, day) not in satisfied:
                by_leg[slug].append(day)
    refused = sorted({d for days in by_leg.values() for d in days})
    refused_set = set(refused)
    return SpreadLedger(
        spread_id=spread_id,
        readable=tuple(d for d in dates if d not in refused_set),
        refused=tuple(refused),
        refused_by_leg={s: tuple(d) for s, d in by_leg.items()},
    )


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series([], dtype="float64" if c in
                        ("spread_value", "long_settle", "short_settle") else "object")
                         for c in PHYSICAL_COLUMNS})


def compute_futures_spreads(eod: pd.DataFrame) -> pd.DataFrame:
    """``silver_futures_eod`` rows -> the gold spread series for every registry pair.

    Returns PHYSICAL_COLUMNS rows ordered by (spread_id, trade_date); the per-spread ledgers ride
    ``.attrs[REFUSED_DATES]`` as {spread_id: SpreadLedger}. A pair whose legs are absent from the
    frame emits nothing for that pair (and its ledger says so); the OTHER pairs still emit --
    one venue's outage never silences another's spread."""
    ledgers: dict[str, SpreadLedger] = {}
    if eod is None or len(eod) == 0:
        out = _empty(); out.attrs[REFUSED_DATES] = ledgers
        return out
    missing = [c for c in ("leviathan_slug", "trade_date", "contract_month", "settle")
               if c not in eod.columns]
    if missing:
        raise ValueError(f"compute_futures_spreads: frame is missing {missing}")

    frames: list[pd.DataFrame] = []
    for spread_id, (long_slug, short_slug) in SPREADS.items():
        unit = _assert_same_unit(spread_id, long_slug, short_slug)
        legs = eod[eod["leviathan_slug"].isin((long_slug, short_slug))].copy()
        if legs.empty:
            ledgers[spread_id] = SpreadLedger(spread_id=spread_id)
            logger.warning("%s: no rows for either leg", spread_id)
            continue
        ledger = _spread_ledger(spread_id, legs, (long_slug, short_slug))
        ledgers[spread_id] = ledger
        if ledger.refused:
            logger.warning("%s", ledger.render())
        if not ledger.readable:
            continue
        keep = pd.to_datetime(legs["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        legs = legs[keep.isin(set(ledger.readable))]
        front = FR.front_month(legs)
        if front.empty:
            continue
        f = front[[c for c in ("leviathan_slug", "trade_date", "contract_month", "settle",
                               "settle_kind") if c in front.columns]].copy()
        f["trade_date"] = pd.to_datetime(f["trade_date"], errors="coerce")
        f = f[f["trade_date"].notna()]
        parts = {}
        for role, slug in (("long", long_slug), ("short", short_slug)):
            part = f[f["leviathan_slug"] == slug].drop(columns=["leviathan_slug"]).rename(columns={
                "settle": f"{role}_settle", "contract_month": f"{role}_contract_month",
                "settle_kind": f"{role}_settle_kind"})
            if part.duplicated(subset=["trade_date"]).any():
                raise ValueError(f"{spread_id}: leg {slug!r} has two front rows on one date")
            parts[role] = part
        out = parts["long"].merge(parts["short"], on="trade_date", how="inner")
        if out.empty:
            continue
        for role in ("long", "short"):
            out[f"{role}_settle"] = pd.to_numeric(out[f"{role}_settle"], errors="coerce")
        out = out.dropna(subset=["long_settle", "short_settle"])
        if out.empty:
            continue
        out["spread_value"] = out["long_settle"] - out["short_settle"]
        kinds = out[["long_settle_kind", "short_settle_kind"]].astype("string") \
            if "long_settle_kind" in out.columns and "short_settle_kind" in out.columns else None
        if kinds is not None:
            same = kinds.nunique(axis=1, dropna=False) == 1
            out["settle_kind"] = kinds["long_settle_kind"].where(same, "mixed")
        else:
            out["settle_kind"] = pd.NA
        out["spread_id"] = spread_id
        out["unit"] = unit
        out["long_slug"], out["short_slug"] = long_slug, short_slug
        out["roll_rule_version"] = FR.ROLL_RULE_VERSION
        out["spread_rule_version"] = SPREAD_RULE_VERSION
        out["trade_date"] = out["trade_date"].dt.strftime("%Y-%m-%d")
        out = out.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
        # is_roll_boundary: either leg's front contract changed vs the previous EMITTED session
        # (the crush's column, the crush's reasons, the crush's STRING type -- see its comment)
        mcols = ["long_contract_month", "short_contract_month"]
        stepped = (out[mcols] != out[mcols].shift(1)).any(axis=1)
        if len(stepped):
            stepped.iloc[0] = False
        out["is_roll_boundary"] = stepped.map({True: "1", False: "0"}).astype("object")
        frames.append(out[PHYSICAL_COLUMNS])
        logger.info("%s: rows=%d first=%s last=%s refused=%d", spread_id, len(out),
                    out["trade_date"].iloc[0], out["trade_date"].iloc[-1], len(ledger.refused))

    gold = (pd.concat(frames, ignore_index=True).sort_values(["spread_id", "trade_date"],
            kind="mergesort").reset_index(drop=True)) if frames else _empty()
    gold.attrs[REFUSED_DATES] = ledgers
    return gold
