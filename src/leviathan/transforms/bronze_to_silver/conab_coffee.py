"""Silver transform for CONAB Brazil coffee bulletin XLS bronze data (SILVER-F024: 22 columns).

OP-4 close: the live physical parquet carries 22 columns (a rich revision/provenance vintage) while
the narrowed producer emitted only 10 -- and Glue under-declared those 10, so 12 columns were
invisible to Athena. This transform reproduces the full 22-column canonical contract pinned by the
SILVER-F010 registry (``configs/silver/tables/silver_conab_coffee.yaml``):

  * the 9 core measurement/identity columns + ``source`` (the pre-F024 set);
  * ``region_raw`` -- the raw bronze region string before canonicalization (provenance);
  * ``area_revision_ha`` / ``yield_revision_bags_per_ha`` / ``production_revision_thousand_bags`` --
    survey-over-survey deltas within (commodity, safra_year, region);
  * ``production_revision_pct`` -- the production revision as a percent of the prior survey
    (zero/absent prior => NaN, never a divide-by-zero);
  * ``production_revision_streak`` -- run length of consecutive same-sign production revisions
    (reset on a sign flip or a zero/absent revision);
  * ``is_repeated_survey`` / ``repeated_from_survey_number`` -- whether a survey's measured content
    is byte-stable-identical to an earlier survey of the same (commodity, safra_year), and which;
  * ``survey_content_fingerprint`` -- a stable, order-independent hash of a survey's measured content;
  * ``source_raw_key`` / ``source_file_etag`` / ``worksheet`` / ``parser_version`` -- Bronze
    provenance carried through (raw S3 key + ETag when Bronze supplies them; the source worksheet
    name; this transform's parser version).

The transform is pure (no AWS/IO). The batch task enforces the INV-2 arrow writer schema from the
registry contract before any write and routes through the shadow-first publisher.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

COUNTRY = "brazil"
SOURCE = "conab_xls"

# Bump when the revision/fingerprint/provenance algorithms below change in a value-affecting way.
PARSER_VERSION = "conab_coffee_silver_v2_f024"

OUTPUT_COLUMNS = [
    "commodity",
    "country",
    "safra_year",
    "survey_number",
    "region",
    "area_in_production_ha",
    "yield_bags_per_ha",
    "production_thousand_bags",
    "production_revision_thousand_bags",
    "source",
    "region_raw",
    "area_revision_ha",
    "yield_revision_bags_per_ha",
    "production_revision_pct",
    "production_revision_streak",
    "is_repeated_survey",
    "repeated_from_survey_number",
    "survey_content_fingerprint",
    "source_raw_key",
    "source_file_etag",
    "worksheet",
    "parser_version",
]

_METRIC_ELEMENTS = {
    "area_in_production_ha",
    "yield_bags_per_ha",
    "production_thousand_bags",
}

# Optional Bronze provenance columns carried through verbatim when present (a future Bronze
# enrichment / B-wave populates them; absent today => null, never fabricated).
_PROVENANCE_PASSTHROUGH = ("source_raw_key", "source_file_etag")

_STATE_NAMES = {
    "AC": "acre", "AL": "alagoas", "AP": "amapa", "AM": "amazonas", "BA": "bahia",
    "CE": "ceara", "DF": "distrito_federal", "ES": "espirito_santo", "GO": "goias",
    "MA": "maranhao", "MT": "mato_grosso", "MS": "mato_grosso_do_sul", "MG": "minas_gerais",
    "PA": "para", "PB": "paraiba", "PR": "parana", "PE": "pernambuco", "PI": "piaui",
    "RJ": "rio_de_janeiro", "RN": "rio_grande_do_norte", "RS": "rio_grande_do_sul",
    "RO": "rondonia", "RR": "roraima", "SC": "santa_catarina", "SP": "sao_paulo",
    "SE": "sergipe", "TO": "tocantins",
}


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def _canonical_region(value: object) -> str | None:
    raw = str(value).strip().upper()
    if raw == "BRASIL":
        return "brazil"
    return _STATE_NAMES.get(raw)


def _commodity_from_sheet(sheet_name: object) -> str | None:
    sheet = str(sheet_name).strip().lower()
    if sheet.startswith("2 "):
        return "arabica_coffee"
    if sheet.startswith("3 "):
        return "robusta_coffee"
    return None


def _dedupe_or_raise(df: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["safra_year", "survey_number", "commodity", "region", "element"]
    duplicate_mask = df.duplicated(subset=key_cols, keep=False)
    if not duplicate_mask.any():
        return df

    duplicates = df.loc[duplicate_mask].copy()
    conflicts = []
    for key, group in duplicates.groupby(key_cols, dropna=False):
        if group["value"].dropna().nunique() > 1:
            conflicts.append(key)

    if conflicts:
        preview = ", ".join(str(item) for item in conflicts[:5])
        raise ValueError(f"CONAB coffee bronze has conflicting duplicate metrics for {preview}")

    return df.drop_duplicates(subset=key_cols, keep="last").copy()


def _survey_fingerprint(group: pd.DataFrame) -> str:
    """Stable, order-independent sha256 of a survey's measured content.

    The content is the sorted list of ``(region, area, yield, production)`` tuples for one
    (commodity, safra_year, survey_number). Floats are rounded to 6 dp and NaN normalised to null so
    the hash is deterministic across pandas float noise and row ordering."""
    def _num(v: object) -> object:
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if np.isnan(f):
            return None
        return round(f, 6)

    payload = sorted(
        [
            str(r.region),
            _num(r.area_in_production_ha),
            _num(r.yield_bags_per_ha),
            _num(r.production_thousand_bags),
        ]
        for r in group.itertuples(index=False)
    )
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _same_sign_streak(revisions: pd.Series) -> list[int]:
    """Run length of consecutive same-sign, nonzero revisions (reset on sign flip / zero / NaN)."""
    out: list[int] = []
    prev_sign = 0
    run = 0
    for v in revisions:
        if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v) or float(v) == 0.0:
            run, prev_sign = 0, 0
        else:
            sign = 1 if float(v) > 0 else -1
            run = run + 1 if sign == prev_sign else 1
            prev_sign = sign
        out.append(run)
    return out


def transform_conab_coffee_bronze_to_silver(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot CONAB long bronze into the 22-column production/revision/provenance silver table.

    Silver keeps national Brazil plus state rows only. CONAB macroregions and sub-state coffee zones
    remain in bronze but are excluded from this table.
    """
    required = {"safra_year", "survey", "sheet_name", "region", "element", "value"}
    if missing := required - set(df.columns):
        raise ValueError(f"CONAB coffee bronze is missing columns: {missing}")
    if df.empty:
        return _empty()

    work = df.copy()
    work["region_raw"] = work["region"].astype(str).str.strip()
    work["worksheet"] = work["sheet_name"].astype(str)
    work["commodity"] = work["sheet_name"].map(_commodity_from_sheet)
    work["region"] = work["region"].map(_canonical_region)
    work["element"] = work["element"].astype(str)
    for col in _PROVENANCE_PASSTHROUGH:
        if col not in work.columns:
            work[col] = None
    work = work.loc[
        work["commodity"].notna()
        & work["region"].notna()
        & work["element"].isin(_METRIC_ELEMENTS)
    ].copy()
    if work.empty:
        return _empty()

    work["safra_year"] = pd.to_numeric(work["safra_year"], errors="coerce")
    work["survey_number"] = pd.to_numeric(work["survey"], errors="coerce")
    work["value"] = pd.to_numeric(work["value"], errors="coerce")
    work = work.dropna(subset=["safra_year", "survey_number"]).copy()
    work["safra_year"] = work["safra_year"].astype(int)
    work["survey_number"] = work["survey_number"].astype(int)

    work = _dedupe_or_raise(work)

    index_cols = ["commodity", "safra_year", "survey_number", "region"]
    silver = (
        work.pivot(index=index_cols, columns="element", values="value")
        .reset_index()
        .rename_axis(columns=None)
    )
    for metric in _METRIC_ELEMENTS:
        if metric not in silver.columns:
            silver[metric] = pd.NA
        silver[metric] = pd.to_numeric(silver[metric], errors="coerce").astype("Float64")

    # ---- provenance: first raw region / worksheet / passthrough per natural-key group ----
    prov_cols = ["region_raw", "worksheet", *_PROVENANCE_PASSTHROUGH]
    prov = (
        work.sort_values(index_cols + ["region_raw"], kind="stable")
        .groupby(index_cols, dropna=False)[prov_cols]
        .first()
        .reset_index()
    )
    silver = silver.merge(prov, on=index_cols, how="left")

    # ---- survey-over-survey revisions within (commodity, safra_year, region) ----
    silver = silver.sort_values(
        ["commodity", "safra_year", "region", "survey_number"], kind="stable"
    ).reset_index(drop=True)
    grp = silver.groupby(["commodity", "safra_year", "region"], dropna=False)
    silver["production_revision_thousand_bags"] = grp["production_thousand_bags"].diff().astype("Float64")
    silver["area_revision_ha"] = grp["area_in_production_ha"].diff().astype("Float64")
    silver["yield_revision_bags_per_ha"] = grp["yield_bags_per_ha"].diff().astype("Float64")

    prev_prod = grp["production_thousand_bags"].shift()
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = (
            silver["production_revision_thousand_bags"].astype("float64")
            / prev_prod.astype("float64")
            * 100.0
        )
    # zero / NaN prior => undefined revision percent (never +/-inf)
    pct = pct.replace([np.inf, -np.inf], np.nan)
    pct = pct.where(prev_prod.astype("float64").fillna(0.0) != 0.0, other=np.nan)
    silver["production_revision_pct"] = pd.Series(pct, index=silver.index).astype("Float64")

    streak_vals: list[int] = []
    for _, g in silver.groupby(["commodity", "safra_year", "region"], dropna=False, sort=False):
        streak_vals.extend(_same_sign_streak(g["production_revision_thousand_bags"]))
    # groupby(sort=False) preserves the stable-sorted order above, so positions align 1:1.
    silver["production_revision_streak"] = pd.array(streak_vals, dtype="Int64")

    # ---- repeated-survey detection within (commodity, safra_year) ----
    # Fingerprint the MEASURED content (region + the 3 measurement columns) of each survey, read
    # from the wide silver frame so a survey whose measurements repeat an earlier one is detectable.
    fp_src = silver[
        ["commodity", "safra_year", "survey_number", "region",
         "area_in_production_ha", "yield_bags_per_ha", "production_thousand_bags"]
    ]
    fps = (
        fp_src.groupby(["commodity", "safra_year", "survey_number"], dropna=False)
        .apply(_survey_fingerprint, include_groups=False)
        .rename("survey_content_fingerprint")
        .reset_index()
    )
    silver = silver.merge(fps, on=["commodity", "safra_year", "survey_number"], how="left")

    repeated_flag: dict[tuple, bool] = {}
    repeated_from: dict[tuple, object] = {}
    for (commodity, safra), g in fps.groupby(["commodity", "safra_year"], dropna=False):
        seen: dict[str, int] = {}
        for r in g.sort_values("survey_number").itertuples(index=False):
            key = (commodity, safra, r.survey_number)
            fp = r.survey_content_fingerprint
            if fp in seen:
                repeated_flag[key] = True
                repeated_from[key] = seen[fp]
            else:
                repeated_flag[key] = False
                repeated_from[key] = pd.NA
                seen[fp] = r.survey_number

    keys = list(zip(silver["commodity"], silver["safra_year"], silver["survey_number"]))
    silver["is_repeated_survey"] = [bool(repeated_flag.get(k, False)) for k in keys]
    silver["repeated_from_survey_number"] = pd.array(
        [repeated_from.get(k, pd.NA) for k in keys], dtype="Int64"
    )

    # ---- constants / stamps ----
    silver["country"] = COUNTRY
    silver["source"] = SOURCE
    silver["parser_version"] = PARSER_VERSION

    silver = silver[OUTPUT_COLUMNS].sort_values(
        ["safra_year", "survey_number", "commodity", "region"], kind="stable"
    )
    logger.info("CONAB coffee silver produced %d rows (22-col contract)", len(silver))
    return silver.reset_index(drop=True)
