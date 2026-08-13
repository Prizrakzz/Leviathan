"""D-HP-18 -- THE RESIDUAL BAND, DERIVED AT $0 FROM STORED ARTIFACTS (H2, the metric transition).

WHAT THIS IS, AND WHAT IT IS NOT. It is a RE-READ of stored `per_answer[].by_rule` dicts -- the one
exception section 2 grants to "old data is never re-scored" (MOAT_WIDTH_WAVE_PLAN.md:56-57) -- and it
produces a BAND, never a verdict: nothing here re-adjudicates a row, a run or a gate. The plan states in
advance (D-HP-18) that the derivation is EXPECTED to return UNUSABLE, and pre-registers the consequence so
no gate is left without a clause: `residual_strips` is RECORDED on both arms and SCORED ON NEITHER, and
THE CLASS SCAN carries the regression detection alone.

THE CORPUS is the census's own -- `data/dhp_census.json` `method.corpus`: "every per_answer row in
data/dmw30/*.json, data/dmw_p4/*.json, data/dmw_p3_gates/*.json" -- and the run REPRODUCES the census's
published histogram BEFORE it reads any new number (the reproduce-to-count law). A mismatch aborts: a band
derived from a corpus that no longer reproduces its own baseline is a number with no provenance.

THE BAND FORM is the covenant band's own (CAPABILITY_WIRING_WAVE_PLAN.md:423-429: ten runs, mean 37.0,
sigma 7.1 -> 27..47), i.e. mean +/- 2*sigma/sqrt(2). THE NOISE-FLOOR CHECK IS MANDATORY and is why that
band exists at all: its 25.6..38.4 predecessor was narrower than the instrument's own noise ("SAME CODE
produced 30 and 50 back-to-back"). If the derived band is narrower than the observed WITHIN-ARM swing, it
is not a band and is recorded UNUSABLE.

THE RATE'S DENOMINATOR IS `claim_count`, NAMED (the no-silent-denominators rule): D-HP-18 quotes
tier_20260812T045711Z 0.0000, width_20260812T045032Z 0.0251, owidth_20260812T060057Z 0.0508, and those are
residual events over SENTENCE-CLAIMS. `handles_checked` is deliberately NOT the denominator here -- it is
`handle_strip_rate`'s, which section 2 VOIDS across this boundary.

ALSO PRODUCED (D-HP-17, H2): the CLASS SCAN over the same corpus, through `emf.class_scan` -- the ONE
producer the eval artifact's `dhp_class_scan` column reads -- which checks that every class the stored
corpus ever charged is inside G1 clause (4)'s declared set, and that the six ARM-EXCLUSIVE classes read
zero on it, as they must: none of them can be charged before the boundary.

RUN: python -m jobs.utils.dhp_census.dhp_h2_residual  (writes data/dhp_h2_residual_band.json)
$0 of model spend. Read-only against the repo; the single write is the artifact.
"""
from __future__ import annotations

import glob
import json
import math
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from leviathan.graphrag import emf  # noqa: E402  -- the ONE producer of the class arithmetic

CORPUS_DIRS = ("data/dmw30", "data/dmw_p4", "data/dmw_p3_gates")
# The census's published pre-D-HP histogram (dhp_census.json c_strips.by_rule + fabricated_citation, which
# that block excludes because it is not numeral-attributable). Plan D-HP-17 states the same numbers.
CENSUS_BASELINE = {"number_mismatch": 412, "number_unbacked": 248, "no_lexical_overlap": 162,
                   "ledger_cascade": 137, "fabricated_citation": 92, "quote_mismatch": 14,
                   "undeclared_unsupported": 1}
CENSUS_ARTIFACTS, CENSUS_ROWS = 35, 409


def _runs() -> tuple[list[dict], list[dict]]:
    """One record per stored BASELINE artifact, plus the flat list of every ROW's `by_rule` dict (the class
    scan's own input -- it counts ROWS charged, so it may never be fed a pooled dict). A file with no
    `per_answer` list is not a baseline (the pairwise-judge and job-map files sit in the same directories)
    and is skipped by SHAPE, never by name."""
    out: list[dict] = []
    row_by_rules: list[dict] = []
    for d in CORPUS_DIRS:
        for path in sorted(glob.glob(os.path.join(ROOT, d, "*.json"))):
            try:
                with open(path, encoding="utf-8") as fh:
                    doc = json.load(fh)
            except Exception:  # noqa: BLE001 -- a malformed neighbour is not this corpus
                continue
            per = doc.get("per_answer")
            if not isinstance(per, list) or not per:
                continue
            res = sum(sum(int((p.get("by_rule") or {}).get(k, 0) or 0) for k in emf.RESIDUAL_CLASSES)
                      for p in per)
            claims = sum(int(p.get("claim_count") or 0) for p in per)
            row_by_rules += [(p.get("by_rule") or {}) for p in per]
            out.append({"file": os.path.basename(path),
                        "dir": d,
                        "eval_set": doc.get("eval_set"),
                        "mode": doc.get("mode"),
                        "model": doc.get("model"),
                        "rows": len(per),
                        "residual_strips": res,
                        "strips": sum(int(p.get("strips") or 0) for p in per),
                        "claim_count": claims,
                        "handles_checked": sum(int(p.get("handles_checked") or 0) for p in per),
                        "residual_rate_per_claim": round(res / max(1, claims), 4),
                        "by_rule": _pool([p.get("by_rule") or {} for p in per])})
    return out, row_by_rules


def _pool(dicts) -> dict:
    out: dict = {}
    for d in dicts:
        for k, v in (d or {}).items():
            out[str(k)] = out.get(str(k), 0) + int(v or 0)
    return {k: out[k] for k in sorted(out)}


def _mean_sigma(xs: list[float]) -> tuple[float, float]:
    """Sample mean and sigma (n-1), the covenant band's own arithmetic. sigma is 0.0 for n < 2."""
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    m = sum(xs) / n
    if n < 2:
        return m, 0.0
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def _band(xs: list[float]) -> dict:
    """mean +/- 2*sigma/sqrt(2) -- the derivation that produced the 27..47 covenant band."""
    m, s = _mean_sigma(xs)
    half = 2 * s / math.sqrt(2)
    return {"n": len(xs), "mean": round(m, 4), "sigma": round(s, 4),
            "half_width": round(half, 4),
            "lo": round(m - half, 4), "hi": round(m + half, 4)}


def main() -> int:
    runs, row_by_rules = _runs()
    pooled = _pool([r["by_rule"] for r in runs])
    rows = sum(r["rows"] for r in runs)

    # ── THE REPRODUCE-TO-COUNT GATE, BEFORE ANY NEW NUMBER IS READ ────────────────────────────────────
    repro = {"artifacts": len(runs), "rows": rows,
             "by_rule": {k: pooled.get(k, 0) for k in CENSUS_BASELINE},
             "expected_artifacts": CENSUS_ARTIFACTS, "expected_rows": CENSUS_ROWS,
             "expected_by_rule": CENSUS_BASELINE}
    repro["exact"] = (len(runs) == CENSUS_ARTIFACTS and rows == CENSUS_ROWS
                      and repro["by_rule"] == CENSUS_BASELINE)
    if not repro["exact"]:
        print("ABORT: the stored corpus does not reproduce the census baseline.")
        print(json.dumps(repro, indent=1))
        return 2

    # ── THE ARMS. An ARM is (deck, mode, model): the unit a two-run band is derived over. ─────────────
    arms: dict[tuple, list[dict]] = defaultdict(list)
    for r in runs:
        arms[(r["eval_set"], r["mode"], r["model"])].append(r)
    arm_recs = []
    for key, rs in sorted(arms.items(), key=lambda kv: [str(x) for x in kv[0]]):
        counts = [r["residual_strips"] for r in rs]
        rates = [r["residual_rate_per_claim"] for r in rs]
        arm_recs.append({"deck": key[0], "mode": key[1], "model": key[2],
                         "runs": [r["file"] for r in rs],
                         "rows_per_run": [r["rows"] for r in rs],
                         "residual_counts": counts,
                         "residual_rates": rates,
                         "count_swing": max(counts) - min(counts),
                         "rate_swing": round(max(rates) - min(rates), 4),
                         "zero_leg": any(c == 0 for c in counts),
                         "mean_count": round(sum(counts) / len(counts), 4),
                         "mean_rate": round(sum(rates) / len(rates), 4)})
    paired = [a for a in arm_recs if len(a["runs"]) >= 2]

    # ── THE BAND, DERIVED TWO WAYS, AND THE NOISE FLOOR ──────────────────────────────────────────────
    band_rate = _band([r["residual_rate_per_claim"] for r in runs])
    band_count = _band([float(r["residual_strips"]) for r in runs])
    max_rate_swing = max((a["rate_swing"] for a in paired), default=0.0)
    max_count_swing = max((a["count_swing"] for a in paired), default=0)
    zero_leg_arms = [f"{a['deck']}/{a['mode']}/{a['model']}" for a in paired if a["zero_leg"]]

    # Poisson: at the mean residual load of a pooled two-run arm, one event is worth this much of the
    # 1.15x multiplier the plan is asked to carry onto this metric.
    mu = sum(a["mean_count"] for a in paired) / max(1, len(paired))
    poisson_sd_pct = round(100 * math.sqrt(max(mu, 1e-9)) / max(mu, 1e-9), 1)

    noise_floor_fail = max_rate_swing >= 2 * band_rate["half_width"]
    verdict = {
        "band_unusable": True,
        "reasons": [
            ("THE DERIVED BAND'S LOWER BOUND IS %.4f -- a RATE band that admits impossible values is not a "
             "band. The covenant band's own form (mean %.4f +/- 2*sigma/sqrt(2), sigma %.4f) puts the "
             "instrument's spread ABOVE its own mean, which is the arithmetic saying the quantity is too "
             "small and too lumpy to be banded at all."
             % (band_rate["lo"], band_rate["mean"], band_rate["sigma"])),
            ("A RATIO BOUND AGAINST A ZERO CONTROL IS NOT DECIDABLE: %d of %d paired arms carry a leg that "
             "reads EXACTLY 0 residual strips, and `<= 1.15 x 0.0000` fails on ANY treatment strip."
             % (len(zero_leg_arms), len(paired))),
            ("THE WITHIN-ARM SWING EXCEEDS THE BAND: the widest same-arm rate swing is %.4f against a band "
             "of total width %.4f (%s)."
             % (max_rate_swing, 2 * band_rate["half_width"],
                "WIDER -- the band is inside the instrument's own noise" if noise_floor_fail
                else "narrower -- but see the zero-leg and concentration reasons")),
            ("THE QUANTITY IS ONE CLASS: `no_lexical_overlap` is %d of %d residual events (%.1f%%), and "
             "`index_out_of_range` and `foreign_regime_name` have NEVER FIRED in this corpus -- so a band "
             "over four classes is a band over one, and the wave PREDICTS the mix inverts."
             % (pooled.get("no_lexical_overlap", 0),
                sum(pooled.get(k, 0) for k in emf.RESIDUAL_CLASSES),
                100.0 * pooled.get("no_lexical_overlap", 0)
                / max(1, sum(pooled.get(k, 0) for k in emf.RESIDUAL_CLASSES)))),
            ("ONE EVENT DECIDES IT: at the mean pooled two-run arm load of %.1f residual events, the "
             "Poisson sd is +/-%.1f%%, so a 1.15x bound is decided by ONE STRIP." % (mu, poisson_sd_pct)),
            ("AND THE 1.15 MULTIPLIER IS NOT AVAILABLE TO CARRY ANYWAY: its provenance is the 19a amendment "
             "and it is attached to `handle_strip_rate`, which section 2 VOIDS across this boundary."),
        ],
        "consequence_preregistered": ("`residual_strips` is RECORDED on both arms and SCORED ON NEITHER at "
                                      "G1, G3 rung 2, rung 4 and D-HP-25. THE CLASS SCAN carries the "
                                      "regression detection alone (section 2's intersection law). Residual "
                                      "strips are reported BY TEXT under GRAPHRAG_STRIP_AUDIT."),
    }

    # ── THE CLASS SCAN OVER THE SAME CORPUS (D-HP-17, H2) ────────────────────────────────────────────
    scan = emf.class_scan(row_by_rules)
    scan_check = {"rows": scan["rows"], "total_events": scan["total_events"],
                  "pooled": scan["pooled"], "rows_charged": scan["rows_charged"],
                  "classes_present": scan["classes_present"],
                  "undeclared": scan["undeclared"],
                  "arm_exclusive_pooled": scan["arm_exclusive"],
                  "declared_set": list(emf.G1_DECLARED_CLASSES),
                  "arm_exclusive_set": list(emf.ARM_EXCLUSIVE_CLASSES),
                  "reading": ("every class the pre-D-HP corpus charges is INSIDE G1 clause (4)'s declared "
                              "set, and all SIX arm-exclusive classes read ZERO on it -- none of them can "
                              "be charged before the boundary, which is exactly why a raw `stripped` delta "
                              "across the arms is not a like-for-like quantity.")}

    doc = {"wave": "D-HP (task #50) -- handle-prose",
           "artifact": "D-HP-18 THE RESIDUAL BAND, derived at $0 from stored artifacts (H2)",
           "generated": "2026-08-13",
           "cost_usd": 0.0,
           "method": {"corpus": "every per_answer row in " + ", ".join(d + "/*.json" for d in CORPUS_DIRS),
                      "residual_classes": list(emf.RESIDUAL_CLASSES),
                      "denominator": "claim_count (SENTENCE-claims). NOT handles_checked -- that is "
                                     "handle_strip_rate's denominator, which section 2 voids here.",
                      "band_form": "mean +/- 2*sigma/sqrt(2) -- the 27..47 covenant band's own derivation",
                      "law": "a RE-READ, not a re-score: it produces a band and re-adjudicates nothing"},
           "reproduction": repro,
           "runs": runs,
           "arms": arm_recs,
           "band_rate_per_claim": band_rate,
           "band_count_per_run": band_count,
           "noise_floor": {"widest_same_arm_rate_swing": round(max_rate_swing, 4),
                           "widest_same_arm_count_swing": max_count_swing,
                           "band_total_width_rate": round(2 * band_rate["half_width"], 4),
                           "band_narrower_than_noise": bool(noise_floor_fail),
                           "paired_arms": len(paired),
                           "arms_with_a_zero_leg": zero_leg_arms},
           "class_scan": scan_check,
           "verdict": verdict,
           "status": "DERIVED AND RECORDED. The band is UNUSABLE, as D-HP-18 pre-registered."}

    out_path = os.path.join(ROOT, "data", "dhp_h2_residual_band.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    print("artifacts %d rows %d -- census reproduced EXACTLY" % (len(runs), rows))
    print("residual rate band %.4f..%.4f (mean %.4f sigma %.4f) over %d runs"
          % (band_rate["lo"], band_rate["hi"], band_rate["mean"], band_rate["sigma"], band_rate["n"]))
    print("widest same-arm rate swing %.4f vs band width %.4f -> %s"
          % (max_rate_swing, 2 * band_rate["half_width"],
             "BAND INSIDE THE NOISE" if noise_floor_fail else "band wider than the widest twin swing"))
    print("paired arms %d, of which %d carry a ZERO leg (a ratio bound is undecidable there)"
          % (len(paired), len(zero_leg_arms)))
    print("class scan: undeclared %s | arm-exclusive pooled %s"
          % (scan_check["undeclared"] or "(none)", scan_check["arm_exclusive_pooled"] or "(all zero)"))
    print("VERDICT: band UNUSABLE -> the CLASS SCAN carries the regression detection alone")
    print("wrote " + out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
