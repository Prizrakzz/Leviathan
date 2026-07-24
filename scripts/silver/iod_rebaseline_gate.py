#!/usr/bin/env python
"""IOD re-baseline gate -- the Section-5 "Gates" artifact of ADR_IOD_SOURCE_SWITCH.

The ADR (RATIFIED 2026-07-24, Option B) re-baselines ``silver_noaa_iod`` from the FROZEN
HadISST1.1 DMI (last real observation 2025-04) onto NOAA CPC IODMI / ERSSTv5 (1950-01..present,
monthly, live). That is a full value rewrite of every served month, not a tail refresh, so the
shadow object must be certified BEFORE the atomic canonical swap. This tool is that certificate.

It emits the six checks the ADR asks for, against the SHADOW silver object and the FROZEN
HadISST snapshot (the ``_hadisst_frozen`` provenance object, or -- pre-swap -- the still-canonical
HadISST object, which is the same series):

  (a) census key delta      -- drop 960 pre-1950 keys, restate 904 (1950-01..2025-04), add >= 14
                               forward keys; the forward count GROWS monthly, so the assertion is
                               ">= 14 AND latest served key >= 2026-06", never an equality.
  (b) divergence vs frozen  -- bias / MAE / RMS / corr / sign+phase agreement on the restated
                               overlap (ADR Section 3 method). NOT pass/fail: the divergence is
                               real, material and RATIFIED (MAE ~0.22, corr ~0.80 over the full
                               overlap). Only ``corr >= 0.75`` gates, as a "these are still the
                               same geophysical index" sanity floor -- it catches a mis-pointed
                               URI or a scrambled parse, not the expected basis shift.
  (c) phase reclassification tally -- how many of the 904 restated months change ``iod_phase``
                               under the +/-0.4 band (ADR Section 3 measured ~1 in 4). Recorded,
                               not gated.
  (d) NO NAMED ANALOGUE LOST -- 1961, 1994, 1997, 2006, 2012, 2019 must all be present with
                               NON-NULL Sep/Oct/Nov ``dmi_value``. This is the assertion that
                               makes the pre-1950 loss acceptable (ADR Section 4, Option B "the
                               pre-1950 loss is nearly free"); if a named analogue's SON window
                               is missing the re-baseline is NOT free and must stop.
  (e) value-population floor -- ``dmi_value`` non-null fraction >= 0.99 across served keys (the
                               registry ``min_nonnull_frac`` is a provisional 0.5 uniform; a
                               dense monthly index must clear far more than that).
  (f) ASCII-only report to stdout, plus an optional JSON artifact upload (``--report-s3``).

READ-ONLY, and NO ATHENA (INV-3): both frames are read straight from parquet via boto3 +
pyarrow. Every data-plane boto3 call goes through an allowlist proxy (the ``day0_heartbeat.py`` /
``rehearse_recovery.py`` idiom); the ONLY write this tool can ever perform is the optional report
JSON, and that goes through a separate client whose key is refused if it lands under any data
prefix (raw/ bronze/ silver/ gold/).

Usage (Git-Bash needs MSYS_NO_PATHCONV=1):
    python scripts/silver/iod_rebaseline_gate.py \
        --shadow-uri s3://leviathan-dev-shahem-001/silver/weather/source=noaa_iod/_shadow/part-000.parquet \
        --frozen-uri s3://leviathan-dev-shahem-001/silver/weather/source=noaa_iod/part-000.parquet

Either URI may also be a local .parquet path (offline rehearsal). Exit code 0 iff VERDICT PASS.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import pyarrow.parquet as pq

# --- ADR-pinned expectations ------------------------------------------------------------------
# The frozen HadISST series is IMMUTABLE (upstream stopped publishing 2025-06-16, last real
# observation 2025-04), so the drop/restate arithmetic can never drift: 1870-01..1949-12 = 960
# months dropped, 1950-01..2025-04 = 904 months restated. Only the FORWARD count moves -- CPC
# publishes monthly, so it grows by one every month after ratification.
EXPECT_DROPPED = 960                    # 1870-01 .. 1949-12
EXPECT_RESTATED = 904                   # 1950-01 .. 2025-04 (the overlap)
MIN_ADDED = 14                          # 2025-05 .. 2026-06 at ratification; grows monthly
MIN_LATEST_KEY = (2026, 6)              # CPC latest at ratification (ADR Section 2 row c)
CUTOVER_YEAR = 1950                     # CPC IODMI history starts 1950-01
CORR_FLOOR = 0.75                       # sanity floor only (measured full-overlap corr 0.802)
NONNULL_FLOOR = 0.99                    # served dmi_value population floor
PHASE_BAND = 0.4                        # JMA threshold, basis-agnostic (ADR Section 6.6)

# Every NAMED positive-IOD analogue the platform's narrative is pinned to. All post-1950 -- which
# is exactly why dropping 1870-1949 is acceptable. SON is the IOD's peak season and the window the
# Ethiopia lag-4 / cascade legs read.
NAMED_ANALOGUES = (1961, 1994, 1997, 2006, 2012, 2019)
ANALOGUE_MONTHS = (9, 10, 11)

VALUE_COL = "dmi_value"
SECOND_VALUE_COL = "iod_dmi_3month_avg"
KEY_COLS = ("year", "month")

# Data prefixes the report artifact may NEVER be written under (the tool is a validator; it does
# not touch a data surface even by operator typo).
_FORBIDDEN_REPORT_PREFIXES = ("raw/", "bronze/", "silver/", "gold/")

# The ONLY boto3 methods the data-plane client may call. Fail-closed: anything else raises before
# the network is touched.
_ALLOWLIST = frozenset({"get_object", "list_objects_v2", "head_object", "get_paginator"})


class _ReadOnlyClient:
    def __init__(self, region: str):
        import boto3  # local import: the pure gate logic stays AWS-free for unit tests

        self._c = boto3.client("s3", region_name=region)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in _ALLOWLIST:
            raise RuntimeError(f"iod_rebaseline_gate is READ-ONLY: boto3 method '{name}' is not allowlisted")
        return getattr(self._c, name)


# ---------------------------------------------------------------------------------------------
# loading (the only impure lane)
# ---------------------------------------------------------------------------------------------
def split_s3_uri(uri: str) -> tuple[str, str]:
    """Split ``s3://bucket/key`` into ``(bucket, key)``; raise on anything else."""
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"not an s3 uri: {uri!r}")
    return parsed.netloc, parsed.path.lstrip("/")


def _read_parquet_bytes(body: bytes) -> pd.DataFrame:
    return pq.read_table(io.BytesIO(body)).to_pandas()


def load_frame(uri: str, s3=None) -> pd.DataFrame:
    """Read one silver frame from a parquet OBJECT, a flat parquet PREFIX, or a local path.

    A prefix read concatenates every ``.parquet`` directly under it. Staging/shadow subtrees are
    skipped UNLESS the caller asked for one explicitly (``--shadow-uri .../_shadow/``), so the
    canonical read never silently picks up an uncertified shadow part."""
    if not uri.startswith("s3://"):
        return _read_parquet_bytes(Path(uri).read_bytes())

    bucket, key = split_s3_uri(uri)
    if key.endswith(".parquet"):
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        return _read_parquet_bytes(body)

    prefix = key.rstrip("/") + "/"
    want_staged = "_shadow" in prefix or "_staging" in prefix
    frames = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if not k.endswith(".parquet"):
                continue
            if not want_staged and ("/_shadow/" in k or "/_staging/" in k):
                continue
            frames.append(_read_parquet_bytes(s3.get_object(Bucket=bucket, Key=k)["Body"].read()))
    if not frames:
        raise ValueError(f"no parquet objects under {uri}")
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------------------------
# (a) census key delta -- pure
# ---------------------------------------------------------------------------------------------
def series_keys(df: pd.DataFrame) -> list[tuple[int, int]]:
    """Sorted unique ``(year, month)`` natural keys of a silver IOD frame."""
    missing = set(KEY_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"IOD frame missing natural-key columns: {sorted(missing)}")
    pairs = {(int(y), int(m)) for y, m in zip(df["year"], df["month"])}
    return sorted(pairs)


@dataclass(frozen=True)
class KeyDelta:
    """The census delta between the frozen HadISST key set and the shadow CPC key set."""
    frozen_keys: tuple[tuple[int, int], ...]
    shadow_keys: tuple[tuple[int, int], ...]
    dropped: tuple[tuple[int, int], ...]     # in frozen, not in shadow
    restated: tuple[tuple[int, int], ...]    # in both
    added: tuple[tuple[int, int], ...]       # in shadow, not in frozen

    @property
    def latest_shadow_key(self) -> tuple[int, int] | None:
        return self.shadow_keys[-1] if self.shadow_keys else None

    @property
    def earliest_shadow_key(self) -> tuple[int, int] | None:
        return self.shadow_keys[0] if self.shadow_keys else None


def key_delta(frozen_keys, shadow_keys) -> KeyDelta:
    f, s = sorted(set(frozen_keys)), sorted(set(shadow_keys))
    fs, ss = set(f), set(s)
    return KeyDelta(
        frozen_keys=tuple(f),
        shadow_keys=tuple(s),
        dropped=tuple(k for k in f if k not in ss),
        restated=tuple(k for k in f if k in ss),
        added=tuple(k for k in s if k not in fs),
    )


def _fmt_key(k) -> str:
    return "none" if k is None else f"{k[0]:04d}-{k[1]:02d}"


def check_unique_keys(df: pd.DataFrame, label: str) -> list[str]:
    """A duplicated natural key would fan out the overlap join and corrupt every stat below.
    The producer already fails closed on it (SILVER-F041); the gate refuses to certify it too."""
    if not set(KEY_COLS) <= set(df.columns):
        return [f"(a) {label} frame missing natural-key columns"]
    dup = df.duplicated(subset=list(KEY_COLS), keep=False)
    if not bool(dup.any()):
        return []
    keys = sorted({(int(y), int(m)) for y, m in
                   zip(df.loc[dup, "year"], df.loc[dup, "month"])})
    return [f"(a) {label} frame has {len(keys)} duplicated (year, month) key(s), e.g. "
            f"{', '.join(_fmt_key(k) for k in keys[:5])}"]


def check_key_delta(delta: KeyDelta, *, expect_dropped: int = EXPECT_DROPPED,
                    expect_restated: int = EXPECT_RESTATED, min_added: int = MIN_ADDED,
                    min_latest: tuple[int, int] = MIN_LATEST_KEY,
                    cutover_year: int = CUTOVER_YEAR) -> list[str]:
    """Assert the ADR 4.1 key arithmetic. Returns failure strings (empty == pass)."""
    fails = []
    if len(delta.dropped) != expect_dropped:
        fails.append(f"(a) dropped keys = {len(delta.dropped)}, expected exactly {expect_dropped} "
                     "(pre-1950 HadISST tail)")
    # A dropped key at/after the cutover is a HOLE in the new series, not the accepted pre-1950
    # loss -- the one drop class the ADR does not sanction.
    late_drops = [k for k in delta.dropped if k[0] >= cutover_year]
    if late_drops:
        fails.append(f"(a) {len(late_drops)} dropped key(s) at/after {cutover_year} "
                     f"-- a hole in the re-baselined series, e.g. "
                     f"{', '.join(_fmt_key(k) for k in late_drops[:5])}")
    if len(delta.restated) != expect_restated:
        fails.append(f"(a) restated (overlap) keys = {len(delta.restated)}, expected exactly "
                     f"{expect_restated} ({cutover_year}-01 .. frozen tail)")
    if len(delta.added) < min_added:
        fails.append(f"(a) forward keys added = {len(delta.added)}, expected >= {min_added} "
                     "(count grows monthly; never an equality)")
    frozen_max = delta.frozen_keys[-1] if delta.frozen_keys else None
    if frozen_max is not None:
        back_adds = [k for k in delta.added if k <= frozen_max]
        if back_adds:
            fails.append(f"(a) {len(back_adds)} 'added' key(s) are NOT forward of the frozen tail "
                         f"{_fmt_key(frozen_max)}, e.g. "
                         f"{', '.join(_fmt_key(k) for k in back_adds[:5])}")
    latest = delta.latest_shadow_key
    if latest is None or latest < min_latest:
        fails.append(f"(a) latest served key = {_fmt_key(latest)}, expected >= {_fmt_key(min_latest)} "
                     "(a live CPC series must reach the ratification horizon)")
    return fails


# ---------------------------------------------------------------------------------------------
# (b) divergence + (c) phase reclassification -- pure
# ---------------------------------------------------------------------------------------------
def _band(val) -> str:
    """+/-0.4 JMA phase band -- the transform's classifier, replicated for frames without the column."""
    if val is None or pd.isna(val):
        return "unknown"
    if val >= PHASE_BAND:
        return "positive"
    if val <= -PHASE_BAND:
        return "negative"
    return "neutral"


def phase_series(df: pd.DataFrame, value_col: str = VALUE_COL) -> pd.Series:
    """Served ``iod_phase`` when present (gate what is actually served), else the band of the value."""
    if "iod_phase" in df.columns:
        return df["iod_phase"].astype("object")
    return df[value_col].map(_band)


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def _overlap(frozen: pd.DataFrame, shadow: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """Inner-join the two frames on (year, month), carrying value + phase from each side."""
    def _side(df, tag):
        out = df[list(KEY_COLS) + [value_col]].copy()
        out = out.rename(columns={value_col: f"{value_col}_{tag}"})
        out[f"phase_{tag}"] = phase_series(df, value_col).values
        return out

    merged = _side(frozen, "frozen").merge(_side(shadow, "shadow"), on=list(KEY_COLS), how="inner")
    return merged.sort_values(list(KEY_COLS)).reset_index(drop=True)


def divergence(frozen: pd.DataFrame, shadow: pd.DataFrame, value_col: str = VALUE_COL) -> dict:
    """ADR Section 3 divergence stats on the restated overlap. Sign convention: ours - candidate,
    i.e. ``frozen - shadow``, matching every published table in the ADR."""
    m = _overlap(frozen, shadow, value_col)
    a, b = m[f"{value_col}_frozen"], m[f"{value_col}_shadow"]
    both = a.notna() & b.notna()
    m, a, b = m[both].reset_index(drop=True), a[both].reset_index(drop=True), b[both].reset_index(drop=True)
    n = int(len(m))
    if n == 0:
        return {"n": 0, "bias": None, "mae": None, "rms": None, "corr": None,
                "sign_agree_frac": None, "phase_agree_frac": None,
                "worst_abs_diff": None, "worst_key": None}
    diff = a - b
    corr = a.corr(b)
    worst_i = int(diff.abs().idxmax())
    return {
        "n": n,
        "bias": round(float(diff.mean()), 4),
        "mae": round(float(diff.abs().mean()), 4),
        "rms": round(float((diff ** 2).mean() ** 0.5), 4),
        "corr": None if pd.isna(corr) else round(float(corr), 4),
        "sign_agree_frac": round(float(sum(_sign(x) == _sign(y) for x, y in zip(a, b)) / n), 4),
        "phase_agree_frac": round(float((m["phase_frozen"] == m["phase_shadow"]).sum() / n), 4),
        "worst_abs_diff": round(float(diff.abs().max()), 4),
        "worst_key": (int(m.at[worst_i, "year"]), int(m.at[worst_i, "month"])),
    }


def check_divergence(stats: dict, *, corr_floor: float = CORR_FLOOR) -> list[str]:
    """ONLY the correlation floor gates -- bias/MAE/RMS are recorded, never asserted (the ADR
    ratified a material divergence; failing on it would fail the decision itself)."""
    fails = []
    if not stats.get("n"):
        fails.append("(b) divergence has no comparable months -- the two frames do not overlap")
        return fails
    corr = stats.get("corr")
    if corr is None:
        fails.append("(b) correlation undefined on the overlap (degenerate series)")
    elif corr < corr_floor:
        fails.append(f"(b) corr = {corr:.4f} < sanity floor {corr_floor} -- the shadow is not the "
                     "same geophysical index (mis-pointed uri or a broken parse), not a basis shift")
    return fails


def phase_reclassification(frozen: pd.DataFrame, shadow: pd.DataFrame,
                           value_col: str = VALUE_COL) -> dict:
    """(c) how the +/-0.4 phase class moves across the restated overlap, plus the served mix."""
    m = _overlap(frozen, shadow, value_col)
    transitions: dict[str, int] = {}
    changed = 0
    for pf, ps in zip(m["phase_frozen"], m["phase_shadow"]):
        if pf == ps:
            continue
        changed += 1
        transitions[f"{pf}->{ps}"] = transitions.get(f"{pf}->{ps}", 0) + 1
    n = int(len(m))
    mix = phase_series(shadow, value_col).value_counts().to_dict()
    return {
        "n": n,
        "changed": changed,
        "changed_frac": round(changed / n, 4) if n else None,
        "transitions": dict(sorted(transitions.items(), key=lambda kv: (-kv[1], kv[0]))),
        "shadow_phase_mix": {str(k): int(v) for k, v in sorted(mix.items())},
    }


# ---------------------------------------------------------------------------------------------
# (d) named-analogue survival -- pure
# ---------------------------------------------------------------------------------------------
def analogue_report(shadow: pd.DataFrame, *, years=NAMED_ANALOGUES, months=ANALOGUE_MONTHS,
                    value_col: str = VALUE_COL) -> dict:
    """Per named analogue year: which SON months carry a NON-NULL value, and the SON peak."""
    out = {}
    for year in years:
        sub = shadow[(shadow["year"] == year) & (shadow["month"].isin(list(months)))]
        present = sorted(int(m) for m in sub["month"].unique())
        nonnull = sorted(int(m) for m in sub.loc[sub[value_col].notna(), "month"].unique())
        peak = sub[value_col].max() if not sub[value_col].dropna().empty else None
        out[str(year)] = {
            "months_present": present,
            "months_nonnull": nonnull,
            "missing_months": [int(m) for m in months if m not in nonnull],
            "son_peak": None if peak is None or pd.isna(peak) else round(float(peak), 4),
        }
    return out


def check_analogues(report: dict, *, expect_years=NAMED_ANALOGUES) -> list[str]:
    """The 'no NAMED analogue lost' assertion -- the load-bearing justification for the pre-1950
    loss. Any named year missing a non-null Sep/Oct/Nov reading fails the gate."""
    fails = []
    for year, rec in report.items():
        if rec["missing_months"]:
            miss = ", ".join(f"{year}-{m:02d}" for m in rec["missing_months"])
            fails.append(f"(d) named analogue {year} lost -- no non-null {VALUE_COL} at {miss}")
    covered = {str(y) for y in expect_years} - set(report)
    if covered:
        fails.append(f"(d) analogue report omits named year(s): {', '.join(sorted(covered))}")
    return fails


# ---------------------------------------------------------------------------------------------
# (e) value-population floor -- pure
# ---------------------------------------------------------------------------------------------
def value_population(shadow: pd.DataFrame, cols=(VALUE_COL, SECOND_VALUE_COL)) -> dict:
    out = {}
    total = int(len(shadow))
    for col in cols:
        if col not in shadow.columns:
            continue
        nonnull = int(shadow[col].notna().sum())
        out[col] = {"nonnull": nonnull, "total": total,
                    "frac": round(nonnull / total, 4) if total else None}
    return out


def check_value_population(pop: dict, *, floor: float = NONNULL_FLOOR,
                           col: str = VALUE_COL) -> list[str]:
    """Only the raw index column is gated: the 3-month mean is NaN for the first month by
    construction (min_periods=2) and can never reach 1.0."""
    rec = pop.get(col)
    if rec is None:
        return [f"(e) served frame has no {col} column"]
    if not rec["total"]:
        return [f"(e) served frame is EMPTY -- refusing to certify a zero-row re-baseline"]
    if rec["frac"] < floor:
        return [f"(e) {col} non-null frac = {rec['frac']:.4f} < floor {floor} "
                f"({rec['nonnull']}/{rec['total']} served keys)"]
    return []


# ---------------------------------------------------------------------------------------------
# evaluate + render
# ---------------------------------------------------------------------------------------------
def _source_stamps(df: pd.DataFrame) -> list[str]:
    if "source" not in df.columns:
        return []
    return sorted(str(v) for v in df["source"].dropna().unique())


def evaluate(shadow: pd.DataFrame, frozen: pd.DataFrame, *, shadow_uri: str = "", frozen_uri: str = "",
             min_added: int = MIN_ADDED, min_latest: tuple[int, int] = MIN_LATEST_KEY,
             corr_floor: float = CORR_FLOOR, nonnull_floor: float = NONNULL_FLOOR) -> dict:
    """Run all six checks and build the gate artifact. PURE -- no AWS, no clock-dependent logic
    beyond the generated_at stamp."""
    delta = key_delta(series_keys(frozen), series_keys(shadow))
    div = divergence(frozen, shadow)
    phases = phase_reclassification(frozen, shadow)
    analogues = analogue_report(shadow)
    pop = value_population(shadow)

    fails = (check_unique_keys(shadow, "shadow")
             + check_unique_keys(frozen, "frozen")
             + check_key_delta(delta, min_added=min_added, min_latest=min_latest)
             + check_divergence(div, corr_floor=corr_floor)
             + check_analogues(analogues)
             + check_value_population(pop, floor=nonnull_floor))

    return {
        "gate": "iod_rebaseline_gate",
        "adr": "docs/private/ADR_IOD_SOURCE_SWITCH.md",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "shadow_uri": shadow_uri,
        "frozen_uri": frozen_uri,
        "shadow_source_stamps": _source_stamps(shadow),
        "frozen_source_stamps": _source_stamps(frozen),
        "key_delta": {
            "frozen_count": len(delta.frozen_keys),
            "shadow_count": len(delta.shadow_keys),
            "frozen_first": _fmt_key(delta.frozen_keys[0] if delta.frozen_keys else None),
            "frozen_last": _fmt_key(delta.frozen_keys[-1] if delta.frozen_keys else None),
            "shadow_first": _fmt_key(delta.earliest_shadow_key),
            "shadow_last": _fmt_key(delta.latest_shadow_key),
            "dropped": len(delta.dropped),
            "restated": len(delta.restated),
            "added": len(delta.added),
            "added_keys": [_fmt_key(k) for k in delta.added],
            "expect_dropped": EXPECT_DROPPED,
            "expect_restated": EXPECT_RESTATED,
            "min_added": min_added,
            "min_latest": _fmt_key(min_latest),
        },
        "divergence": {**div, "worst_key": _fmt_key(div["worst_key"]), "corr_floor": corr_floor,
                       "gating": "corr only -- bias/MAE/RMS are RECORDED (ratified divergence)"},
        "phase_reclassification": phases,
        "named_analogues": analogues,
        "value_population": {**pop, "floor": nonnull_floor, "gated_column": VALUE_COL},
        "failures": fails,
        "verdict": "PASS" if not fails else "FAIL",
    }


def render_report(art: dict) -> str:
    """ASCII-only gate report (Windows console is cp1252 -- no non-ASCII may reach stdout)."""
    kd, dv, ph, pop = art["key_delta"], art["divergence"], art["phase_reclassification"], art["value_population"]

    def ok(cond) -> str:
        return "PASS" if cond else "FAIL"

    L = []
    L.append("=== IOD re-baseline gate (ADR_IOD_SOURCE_SWITCH Section 5) ===")
    L.append(f"generated_at : {art['generated_at']}")
    L.append(f"shadow       : {art['shadow_uri']}  source={','.join(art['shadow_source_stamps']) or 'n/a'}")
    L.append(f"frozen       : {art['frozen_uri']}  source={','.join(art['frozen_source_stamps']) or 'n/a'}")
    L.append("")
    L.append("(a) census key delta")
    L.append(f"  frozen keys        : {kd['frozen_count']:5d}  ({kd['frozen_first']} .. {kd['frozen_last']})")
    L.append(f"  shadow keys        : {kd['shadow_count']:5d}  ({kd['shadow_first']} .. {kd['shadow_last']})")
    L.append(f"  dropped (pre-1950) : {kd['dropped']:5d}  expect == {kd['expect_dropped']:<6d} "
             f"[{ok(kd['dropped'] == kd['expect_dropped'])}]")
    L.append(f"  restated (overlap) : {kd['restated']:5d}  expect == {kd['expect_restated']:<6d} "
             f"[{ok(kd['restated'] == kd['expect_restated'])}]")
    L.append(f"  added (forward)    : {kd['added']:5d}  expect >= {kd['min_added']:<6d} "
             f"[{ok(kd['added'] >= kd['min_added'])}]")
    # zero-padded YYYY-MM sorts lexicographically; 'none' (empty frame) must never read as PASS.
    L.append(f"  latest served key  : {kd['shadow_last']}  expect >= {kd['min_latest']}      "
             f"[{ok(kd['shadow_last'] != 'none' and kd['shadow_last'] >= kd['min_latest'])}]")
    L.append("")
    L.append("(b) divergence vs frozen HadISST on the restated overlap (ours - candidate)")
    L.append(f"  n={dv['n']}  bias={dv['bias']}  MAE={dv['mae']}  RMS={dv['rms']}  corr={dv['corr']}")
    L.append(f"  sign_agree={dv['sign_agree_frac']}  phase_agree={dv['phase_agree_frac']}  "
             f"worst_abs_diff={dv['worst_abs_diff']} at {dv['worst_key']}")
    L.append(f"  RECORDED, not gated -- the divergence is ratified. corr floor {dv['corr_floor']} "
             f"[{ok(dv['corr'] is not None and dv['corr'] >= dv['corr_floor'])}]")
    L.append("")
    L.append(f"(c) phase reclassification over the overlap (n={ph['n']})")
    L.append(f"  changed: {ph['changed']} ({(ph['changed_frac'] or 0) * 100:.1f} pct) -- recorded, not gated")
    for k, v in ph["transitions"].items():
        L.append(f"    {k:22s} {v:5d}")
    L.append(f"  shadow served phase mix: "
             f"{', '.join(f'{k}={v}' for k, v in ph['shadow_phase_mix'].items()) or 'n/a'}")
    L.append("")
    L.append("(d) no NAMED analogue lost (non-null Sep-Nov)")
    for year, rec in art["named_analogues"].items():
        L.append(f"  {year}: nonnull_months={rec['months_nonnull']} son_peak={rec['son_peak']} "
                 f"[{ok(not rec['missing_months'])}]")
    L.append("")
    L.append("(e) value-population floor across served keys")
    for col, rec in pop.items():
        if not isinstance(rec, dict):
            continue
        gated = col == pop["gated_column"]
        tag = (f"floor {pop['floor']} [{ok((rec['frac'] or 0) >= pop['floor'])}]"
               if gated else "(informational)")
        L.append(f"  {col:22s} {rec['nonnull']}/{rec['total']} = {rec['frac']}  {tag}")
    L.append("")
    if art["failures"]:
        L.append("FAILURES:")
        for f in art["failures"]:
            L.append(f"  - {f}")
    L.append(f"VERDICT: {art['verdict']}")
    return "\n".join(L)


def _put_report(uri: str, art: dict, region: str) -> str:
    """Upload the JSON artifact. Refused outright if the key lands under a DATA prefix -- this
    tool is a validator and must never be able to write a data surface."""
    import boto3

    bucket, key = split_s3_uri(uri)
    if any(key.startswith(p) for p in _FORBIDDEN_REPORT_PREFIXES):
        raise SystemExit(f"--report-s3 key '{key}' is under a data prefix "
                         f"({'/'.join(p.rstrip('/') for p in _FORBIDDEN_REPORT_PREFIXES)}) -- refused")
    boto3.client("s3", region_name=region).put_object(
        Bucket=bucket, Key=key,
        Body=json.dumps(art, indent=2, sort_keys=True).encode("utf-8"),
        ContentType="application/json")
    return uri


def _parse_month(s: str) -> tuple[int, int]:
    y, m = s.split("-")
    return (int(y), int(m))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="IOD re-baseline gate (read-only; no Athena)")
    ap.add_argument("--shadow-uri", required=True,
                    help="s3 uri (object or flat prefix) or local path of the SHADOW silver object")
    ap.add_argument("--frozen-uri", required=True,
                    help="s3 uri or local path of the frozen HadISST silver series "
                         "(the _hadisst_frozen snapshot, or the pre-swap canonical object)")
    ap.add_argument("--min-added", type=int, default=MIN_ADDED,
                    help=f"minimum forward keys added (default {MIN_ADDED}; grows monthly)")
    ap.add_argument("--min-latest", default=f"{MIN_LATEST_KEY[0]:04d}-{MIN_LATEST_KEY[1]:02d}",
                    help="minimum latest served key, YYYY-MM")
    ap.add_argument("--corr-floor", type=float, default=CORR_FLOOR)
    ap.add_argument("--nonnull-floor", type=float, default=NONNULL_FLOOR)
    ap.add_argument("--report-s3", default=None, help="optional s3 uri for the JSON gate artifact")
    ap.add_argument("--aws-region", default="us-east-1")
    args = ap.parse_args(argv)

    needs_s3 = args.shadow_uri.startswith("s3://") or args.frozen_uri.startswith("s3://")
    s3 = _ReadOnlyClient(args.aws_region) if needs_s3 else None
    shadow = load_frame(args.shadow_uri, s3)
    frozen = load_frame(args.frozen_uri, s3)

    art = evaluate(shadow, frozen, shadow_uri=args.shadow_uri, frozen_uri=args.frozen_uri,
                   min_added=args.min_added, min_latest=_parse_month(args.min_latest),
                   corr_floor=args.corr_floor, nonnull_floor=args.nonnull_floor)
    print(render_report(art))
    if args.report_s3:
        print(f"report artifact -> {_put_report(args.report_s3, art, args.aws_region)}")
    return 0 if art["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
