"""Macro-climate and market-positioning feature computations.

Four families:
  oni_climate          — ENSO anomaly + phase flags at the month before crop-year start
  iod_climate          — Indian Ocean Dipole DMI at the month before crop-year start
  cot_mm_positioning   — CFTC managed-money net position z-scores at crop-year start
  pink_sheet_input_costs — World Bank fertilizer + energy input-cost z-scores

All are point-in-time correct: only observations whose timestamp is strictly
before the crop-year start date are eligible, so no future information leaks
into the feature value.

None of these signals have a country dimension — the same scalar is emitted
for every country in the commodity's geography list.  The model learns which
commodities are sensitive to each macro signal.
"""
from __future__ import annotations

import pandas as pd

from leviathan.features.computations.base import (
    FeatureContext,
    empty_result,
    make_result,
)

# ---------------------------------------------------------------------------
# ONI / ENSO
# ---------------------------------------------------------------------------

def compute_oni_climate(ctx: FeatureContext, spec) -> pd.DataFrame:
    """ENSO state at the month immediately before crop-year start.

    Emits three features per (country, crop_year):
      oni_anom_prior     — ONI anomaly (°C) at that month
      oni_el_nino_flag   — 1 if El Niño active, 0 otherwise
      oni_la_nina_flag   — 1 if La Niña active, 0 otherwise
    """
    df = ctx.inputs.get("oni")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    cys = ctx.calendar.crop_year_start_month
    rows: list[tuple[str, int, str, float]] = []

    for crop_year in ctx.crop_years:
        # Month immediately before crop year starts
        if cys == 1:
            lookup_year, lookup_month = crop_year - 1, 12
        else:
            lookup_year, lookup_month = crop_year, cys - 1

        row = df[(df["year"] == lookup_year) & (df["month"] == lookup_month)]
        if row.empty:
            continue
        row = row.iloc[0]

        anom = float(row["oni_anom"]) if pd.notna(row["oni_anom"]) else None
        el_nino = float(row["el_nino_flag"]) if pd.notna(row["el_nino_flag"]) else None
        la_nina = float(row["la_nina_flag"]) if pd.notna(row["la_nina_flag"]) else None

        for country in ctx.countries:
            if anom is not None:
                rows.append((country, crop_year, "oni_anom_prior", anom))
            if el_nino is not None:
                rows.append((country, crop_year, "oni_el_nino_flag", el_nino))
            if la_nina is not None:
                rows.append((country, crop_year, "oni_la_nina_flag", la_nina))

    return make_result(rows)


# Commodities whose dominant origin is Brazil / Argentina — they get the
# region-specific La Niña teleconnection flags already computed in ONI silver.
_BRAZIL_TELECONNECTION: frozenset[str] = frozenset({
    "arabica_coffee", "brazilian_arabica_coffee", "robusta_coffee",
    "raw_sugar", "soybeans_cbot", "soybean_meal_cbot", "soybean_oil_cbot",
    "campinas_corn_reference_bmf",
})
_ARGENTINA_TELECONNECTION: frozenset[str] = frozenset({
    "soybeans_cbot", "soybean_meal_cbot", "soybean_oil_cbot", "corn_cbot",
})


def compute_oni_lag(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Lagged ENSO + region-specific La Niña teleconnection flags.

    ENSO's effect on crops lags the SST anomaly by a season or more (planting
    decisions and rainfall regimes respond with delay).  The ONI silver already
    carries ``oni_lag3`` / ``oni_lag6`` and origin-specific La Niña flags; this
    surfaces them at the month before crop-year start (point-in-time), where the
    base ``oni_climate`` family only exposed the contemporaneous anomaly.

    Emits per (country, crop_year):
      oni_lag3_prior / oni_lag6_prior          — ENSO anomaly at 3 / 6-month lag
      oni_la_nina_brazil_flag (Brazil origins) — Brazil-specific La Niña
      oni_la_nina_argentina_flag (Argentina origins)
    """
    df = ctx.inputs.get("oni")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    cys = ctx.calendar.crop_year_start_month
    emit_brazil = ctx.commodity in _BRAZIL_TELECONNECTION
    emit_argentina = ctx.commodity in _ARGENTINA_TELECONNECTION
    rows: list[tuple[str, int, str, float]] = []

    for crop_year in ctx.crop_years:
        if cys == 1:
            lookup_year, lookup_month = crop_year - 1, 12
        else:
            lookup_year, lookup_month = crop_year, cys - 1

        row = df[(df["year"] == lookup_year) & (df["month"] == lookup_month)]
        if row.empty:
            continue
        row = row.iloc[0]

        lag3 = row.get("oni_lag3")
        lag6 = row.get("oni_lag6")
        brazil = row.get("la_nina_brazil_flag")
        argentina = row.get("argentina_la_nina_flag")

        for country in ctx.countries:
            if pd.notna(lag3):
                rows.append((country, crop_year, "oni_lag3_prior", float(lag3)))
            if pd.notna(lag6):
                rows.append((country, crop_year, "oni_lag6_prior", float(lag6)))
            if emit_brazil and pd.notna(brazil):
                rows.append((country, crop_year, "oni_la_nina_brazil_flag", float(brazil)))
            if emit_argentina and pd.notna(argentina):
                rows.append((country, crop_year, "oni_la_nina_argentina_flag", float(argentina)))

    return make_result(rows)


# ---------------------------------------------------------------------------
# IOD
# ---------------------------------------------------------------------------

def compute_iod_climate(ctx: FeatureContext, spec) -> pd.DataFrame:
    """Indian Ocean Dipole state at the month before crop-year start.

    Emits:
      iod_dmi_prior  — 3-month average DMI value at that month
    """
    df = ctx.inputs.get("iod")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    cys = ctx.calendar.crop_year_start_month
    rows: list[tuple[str, int, str, float]] = []

    for crop_year in ctx.crop_years:
        if cys == 1:
            lookup_year, lookup_month = crop_year - 1, 12
        else:
            lookup_year, lookup_month = crop_year, cys - 1

        row = df[(df["year"] == lookup_year) & (df["month"] == lookup_month)]
        if row.empty:
            continue

        dmi = row["iod_dmi_3month_avg"].iloc[0]
        if pd.isna(dmi):
            continue
        for country in ctx.countries:
            rows.append((country, crop_year, "iod_dmi_prior", float(dmi)))

    return make_result(rows)


# ---------------------------------------------------------------------------
# COT managed-money positioning
# ---------------------------------------------------------------------------

def compute_cot_mm_positioning(ctx: FeatureContext, spec) -> pd.DataFrame:
    """CFTC managed-money net position z-scores at the most recent report
    before the crop-year start.

    Emits:
      cot_mm_net_z       — net long position 3-year rolling z-score
      cot_mm_pct_oi_z    — net % of open interest 3-year rolling z-score
    """
    df = ctx.inputs.get("cot")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    # COT data is keyed by leviathan_slug — use the commodity name directly.
    slug_df = df[df["leviathan_slug"] == ctx.commodity].copy()
    if slug_df.empty:
        return empty_result()

    slug_df["report_date"] = pd.to_datetime(slug_df["report_date"], errors="coerce")
    slug_df = slug_df.dropna(subset=["report_date"]).sort_values("report_date")

    rows: list[tuple[str, int, str, float]] = []

    for crop_year in ctx.crop_years:
        cutoff = pd.Timestamp(ctx.calendar.crop_year_start(crop_year))
        eligible = slug_df[slug_df["report_date"] < cutoff]
        if eligible.empty:
            continue
        latest = eligible.iloc[-1]

        net_z = latest.get("mm_net_z_3yr")
        pct_z = latest.get("mm_pct_oi_z_3yr")

        for country in ctx.countries:
            if pd.notna(net_z):
                rows.append((country, crop_year, "cot_mm_net_z", float(net_z)))
            if pd.notna(pct_z):
                rows.append((country, crop_year, "cot_mm_pct_oi_z", float(pct_z)))

    return make_result(rows)


# ---------------------------------------------------------------------------
# Pink Sheet — fertilizer + energy input costs
# ---------------------------------------------------------------------------

def compute_pink_sheet_input_costs(ctx: FeatureContext, spec) -> pd.DataFrame:
    """World Bank Pink Sheet input-cost z-scores at the most recent monthly
    observation before the crop-year start.

    Emits:
      pink_sheet_npk_z     — blended NPK fertilizer index 5-year z-score
      pink_sheet_energy_z  — Brent crude 5-year z-score (energy / transport proxy)
    """
    df = ctx.inputs.get("pink_sheet")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    df2 = df.copy()
    df2["date"] = pd.to_datetime(df2["date"], errors="coerce")
    df2 = df2.dropna(subset=["date"]).sort_values("date")

    rows: list[tuple[str, int, str, float]] = []

    for crop_year in ctx.crop_years:
        cutoff = pd.Timestamp(ctx.calendar.crop_year_start(crop_year))
        eligible = df2[df2["date"] < cutoff]
        if eligible.empty:
            continue
        latest = eligible.iloc[-1]

        npk_z = latest.get("blended_npk_index_zscore_5yr")
        energy_z = latest.get("brent_crude_usd_bbl_zscore_5yr")
        urea_z = latest.get("urea_usd_mt_zscore_5yr")
        dap_z = latest.get("dap_usd_mt_zscore_5yr")

        for country in ctx.countries:
            if pd.notna(npk_z):
                rows.append((country, crop_year, "pink_sheet_npk_z", float(npk_z)))
            if pd.notna(energy_z):
                rows.append((country, crop_year, "pink_sheet_energy_z", float(energy_z)))
            if pd.notna(urea_z):
                rows.append((country, crop_year, "pink_sheet_urea_z", float(urea_z)))
            if pd.notna(dap_z):
                rows.append((country, crop_year, "pink_sheet_dap_z", float(dap_z)))

    return make_result(rows)


# ---------------------------------------------------------------------------
# FRED FX — BRL and CNY 90-day pct change at crop-year start
# ---------------------------------------------------------------------------

# Commodities where BRL matters (Brazil is the dominant exporter/producer).
_BRL_COMMODITIES: frozenset[str] = frozenset({
    "arabica_coffee", "brazilian_arabica_coffee", "robusta_coffee",
    "raw_sugar",
    "soybeans_cbot", "soybean_meal_cbot", "soybean_oil_cbot",
})

# Commodities where CNY matters (China is the dominant importer).
_CNY_COMMODITIES: frozenset[str] = frozenset({
    "soybeans_cbot", "soybean_meal_cbot", "soybean_oil_cbot",
    "soybeans_no_1_dce", "soybeans_no_2_dce",
    "soybean_meal_dce", "soybean_oil_dce",
    "corn_cbot",
    "malaysian_crude_palm_oil_cme", "palm_olein_dce",
})


def compute_fred_fx(ctx: FeatureContext, spec) -> pd.DataFrame:
    """BRL/USD and CNY/USD 90-day pct change at the most recent trading day
    before the crop-year start.

    Currency impacts:
      brl_fx_pct_90d — BRL depreciation raises Brazil's USD-denominated
                        export competitiveness; relevant for coffee, sugar,
                        and US-vs-Brazil soy competition.
      cny_fx_pct_90d — CNY depreciation reduces China's purchasing power
                        for USD-priced imports: soybeans, corn, palm.

    Emits only the currency (or currencies) relevant to ctx.commodity.
    """
    df = ctx.inputs.get("fred_fx")
    if df is None or df.empty or ctx.calendar is None:
        return empty_result()

    df2 = df.copy()
    df2["date"] = pd.to_datetime(df2["date"], errors="coerce")
    df2 = df2.dropna(subset=["date"]).sort_values("date")

    emit_brl = ctx.commodity in _BRL_COMMODITIES
    emit_cny = ctx.commodity in _CNY_COMMODITIES
    if not emit_brl and not emit_cny:
        return empty_result()

    rows: list[tuple[str, int, str, float]] = []

    for crop_year in ctx.crop_years:
        cutoff = pd.Timestamp(ctx.calendar.crop_year_start(crop_year))
        eligible = df2[df2["date"] < cutoff]
        if eligible.empty:
            continue
        latest = eligible.iloc[-1]

        brl = latest.get("brl_usd_pct_change_90d")
        cny = latest.get("cny_usd_pct_change_90d")

        for country in ctx.countries:
            if emit_brl and pd.notna(brl):
                rows.append((country, crop_year, "brl_fx_pct_90d", float(brl)))
            if emit_cny and pd.notna(cny):
                rows.append((country, crop_year, "cny_fx_pct_90d", float(cny)))

    return make_result(rows)
