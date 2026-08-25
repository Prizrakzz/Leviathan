"""Raw -> bronze transform for the Frankfurter FX time series (SILVER-F040).

Produces the bronze feeding the ``silver_fred_fx`` table. Per ADR-003
(``docs/adr/ADR-003-fred-fx-source-identity.md``) the true source of record is
**Frankfurter** (frankfurter.dev, ECB reference-rate proxy), NOT FRED -- the
``fred`` in the table name is a documented legacy misnomer. This module stamps the
truthful provider (``source='frankfurter'``).

Upstream shape (``GET https://api.frankfurter.dev/v1/{start}..{end}?base=USD&symbols=BRL,ARS,CNY``)::

    {
      "amount": 1.0,
      "base": "USD",
      "start_date": "2004-12-31",
      "end_date": "2026-06-04",
      "rates": {
        "2004-12-31": {"BRL": 2.6577, "ARS": 2.9733, "CNY": 8.277},
        "2005-01-03": {"BRL": 2.6672, ...},
        ...
      }
    }

With ``base=USD`` each ``rates[date][X]`` is **units of currency X per 1 USD** -- i.e.
``BRL`` -> ``brl_usd`` directly (direction: local currency per USD; higher = weaker
local currency).

Bronze grain: one row per (observation date, currency) that the source actually
returns -- weekends/holidays are NOT synthesized (INV-4). Conflicting duplicate
records for the same (date, currency) fail closed.
"""
from __future__ import annotations

import json

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Explicit series mapping (ADR-003). FX-1 (projection wave, 2026-08-25) widened 3 -> 14: this dict
# decides what is FETCHED (frankfurter_fx_task derives the querystring from it) while the silver
# transform's _RATE_COLUMNS decides what is SERVED -- keep both in view when editing either.
# The 14 = the measured region_map DEMAND (+ GBP for D-3's cocoa cross) (19 declining legs across 13 boards: FX-4) + the incumbents.
# ARS is KEPT deliberately although DEAD at source since 2020-10-30 (FX-6/ADR-003: the column stays,
# the tripwire below names the dead symbol on every fire instead of six years of silence).
# The FURTHER widening to Frankfurter's full ~29-symbol universe is GATED ON THE FX-9(a) PROBE
# (network-parked: api.frankfurter.dev returns 403 from the sandbox) -- an unproven symbol in the
# querystring risks failing the WHOLE fetch, so no symbol enters here without a probe-confirmed
# first/last date. Add rows only in (symbol, column) pairs the probe has named.
SERIES_MAP: dict[str, str] = {
    "BRL": "brl_usd",
    "ARS": "ars_usd",
    "CNY": "cny_usd",
    "IDR": "idr_usd",
    "INR": "inr_usd",
    "MYR": "myr_usd",
    "THB": "thb_usd",
    "TRY": "try_usd",
    "AUD": "aud_usd",
    "CAD": "cad_usd",
    "ZAR": "zar_usd",
    "MXN": "mxn_usd",
    "EUR": "eur_usd",
    # D-3 (ratified 2026-08-25): the cocoa GBP_cross leg -- London/New York arbitrage needs the
    # pound. ECB-core symbol, full history expected; floors still ride the FX-9(a) probe.
    "GBP": "gbp_usd",
}

SOURCE = "frankfurter"

BRONZE_COLUMNS: list[str] = ["date", "currency", "rate_local_per_usd", "source"]


def extract_fx_bronze(raw_bytes: bytes) -> pd.DataFrame:
    """Parse a Frankfurter time-series JSON blob into a long-format bronze frame.

    Args:
        raw_bytes: The raw JSON bytes of a base=USD time-series response.

    Returns:
        DataFrame with :data:`BRONZE_COLUMNS`, one row per (date, currency) the source
        returned, sorted by (date, currency). ``rate_local_per_usd`` is float64.

    Raises:
        ValueError: If the payload is not base=USD, carries no ``rates``, yields no
            parseable observations, or contains a conflicting duplicate (date, currency).
    """
    payload = json.loads(raw_bytes.decode("utf-8", errors="replace"))
    base = str(payload.get("base", "")).upper()
    if base != "USD":
        raise ValueError(
            f"Frankfurter FX bronze: base must be USD for the local-per-USD convention, got {base!r}"
        )
    rates = payload.get("rates")
    if not isinstance(rates, dict) or not rates:
        raise ValueError("Frankfurter FX bronze: payload has no 'rates' object")

    records: list[dict] = []
    for date_str, per_ccy in rates.items():
        if not isinstance(per_ccy, dict):
            continue
        for symbol in SERIES_MAP:
            if symbol not in per_ccy:
                continue  # currency not returned on this date -> stays absent (INV-4)
            val = per_ccy[symbol]
            if val is None:
                continue
            try:
                rate = float(val)
            except (TypeError, ValueError):
                continue
            records.append({
                "date": str(date_str),
                "currency": symbol,
                "rate_local_per_usd": rate,
                "source": SOURCE,
            })

    if not records:
        raise ValueError("Frankfurter FX bronze: no parseable observations in 'rates'")

    # FX-1 DEAD-SYMBOL TRIPWIRE (projection wave, 2026-08-25; the f66e5a90 shape): a requested symbol
    # returning ZERO observations is named on every fire, never silently absent -- ARS died at source
    # on 2020-10-30 and nothing said so for six years (5 legs declined on a NULL while the 0.5 gate
    # passed at 73%). WARN, not raise: a single dead symbol must not kill the 12 live ones, and the
    # per-column floors (FX-2d) are the fail-closed half once the probe sets them.
    seen = {r["currency"] for r in records}
    for symbol in SERIES_MAP:
        if symbol not in seen:
            logger.warning(
                "Frankfurter FX bronze: requested symbol %s returned ZERO observations in this "
                "window -- dead at source or dropped from the API roster (the ARS class; see "
                "SERIES_MAP's FX-6 note)", symbol)

    df = pd.DataFrame(records)

    # Fail closed on a conflicting duplicate source record (same (date, currency), two rates).
    conflict = df.groupby(["date", "currency"])["rate_local_per_usd"].nunique()
    bad = conflict[conflict > 1]
    if len(bad):
        raise ValueError(
            f"Frankfurter FX bronze: conflicting duplicate rates for {list(bad.index)[:5]} "
            "-- refusing to blend source records"
        )
    # Drop exact-duplicate rows (same date/currency/rate) defensively.
    df = df.drop_duplicates(subset=["date", "currency"], keep="first")

    df["rate_local_per_usd"] = df["rate_local_per_usd"].astype("float64")
    df = df[BRONZE_COLUMNS].sort_values(["date", "currency"]).reset_index(drop=True)

    logger.info(
        "Frankfurter FX bronze: %d rows  dates=%d  currencies=%s  range=%s..%s",
        len(df), df["date"].nunique(), sorted(df["currency"].unique()),
        df["date"].min(), df["date"].max(),
    )
    return df
