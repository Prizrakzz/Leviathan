"""Append the clause (1b) fixture positive-control block to data/dhp_g1/manifest_d1.json.

DESIGN OF RECORD: plans 10.24 (design + pre-registration) / 10.25 (the read). CONSUMER: plan
10.29 / M-2, which re-reads this block. Reads the scored result written by dhp_1b_run.py.
Idempotent: rewrites the one key.

CLI: --root / --result / --manifest; all default off THIS FILE's location (repo root three levels
up, corpus + result + manifest under ROOT/data/dhp_g1), never off the process cwd.
"""
import argparse
import collections
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
# jobs/utils/dhp_census/<this file>  ->  repo root
REPO = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))


def build_block(res):
    f1 = res["F1_index_plus_1"]
    f2 = res["F2_e_real_but_wrong"]
    f3 = res["F3_out_of_range"]

    def t(a, k):
        return a["tally"].get(k, 0)

    # 10.24.5's frozen rule: PASS needs injected == caught AND zero innocent deletions AND the caught
    # cases accounted by the counters E.4's row names. The first conjunct fails on both scored halves.
    verdict = "FAIL"
    INNOCENT_DELETIONS_AFTER_ADJUDICATION = 0   # 7 flagged across 2,899 cases; all 7 are the CARRIER sentence

    block = {
        "record_kind": ("D-HP G1 CLAUSE (1b) -- THE FIXTURE POSITIVE CONTROL. Offline replay of the REAL "
                        "render stack (functions imported from source at HEAD 88090c46) over the r6 "
                        "TREATMENT artifacts' raw_draft.postverify_* prose, the exact seam answer.py feeds "
                        "the handle passes. $0, no Batch arm, no model call."),
        "recorded_at_utc": "2026-08-15",
        "plan_sections": ["10.24 (design + pre-registration, written BEFORE the run)",
                          "10.25 (the read)"],
        "code_under_test_commit": "88090c46",
        "verdict": verdict,
        "population": {
            "invocations": ["r6_inv3_deepv2_width_deep_hp_r1", "r6_inv4_deepv2_width_deep_hp_r2",
                            "r6_inv7_shape_esc_deep_hp_r1", "r6_inv8_shape_esc_deep_hp_r2",
                            "r6_cov_inv3_deep_hp_r1", "r6_cov_inv4_deep_hp_r2"],
            "answers_in_arm": 76,
            "answers_scored": 75,
            "struck_by_name": {
                "row": "shape_esc_episode_us_drought (r6_inv8_shape_esc_deep_hp_r2)",
                "reason": ("eval._served_rows caps its projection at _ROWS_PER_RECORD_CAP=400 rows per "
                           "record; this answer exhausts the budget so 51 of its calls project row_count>0 "
                           "with ZERO rows. It is the ONLY answer in the population with a phantom-empty "
                           "call. Struck for a lossy INPUT, before injection, not for its result."),
            },
        },
        "fidelity_anchor_arm_F0": {
            "note": ("the un-mutated replay scored against the artifacts' own recorded censuses over the 75 "
                     "surviving answers"),
            "number_handles_substituted": {"replay": 1052, "artifact": 1052, "verdict": "EXACT"},
            "number_handles_zero_classes": {
                "note": ("unresolvable / handles_dropped / sentences_dropped / slot_scope_mismatch / "
                         "direction_sign_mismatch / grouped_in_slot / binding_refused / "
                         "empty_row_addressed"),
                "replay": 0, "artifact": 0, "verdict": "EXACT"},
            "direction_checked": {"replay": 1053, "artifact": 1053, "verdict": "EXACT"},
            "scope_checked": {"replay": 184, "artifact": 238, "verdict": "-54, THE ONE GAP"},
            "prose_handles_all_four_keys": {"replay": 0, "artifact": 0, "verdict": "EXACT"},
            "the_one_gap": ("_receipt_period_text reads the QUERY's period AND the headline row's; "
                            "served_rows projects the row's and NOT the query's. The replay's scope "
                            "detector is therefore SILENT on 54 of 238 live comparisons. It can only "
                            "UNDER-catch, never over-catch: every CAUGHT is real, every MISSED is a "
                            "ceiling claim."),
            "verified_bytes_reproduced": "31 of 75 answers byte-exact; see plan 10.24.3 for the two causes",
        },
        "arms": {
            "F3_harness_liveness_out_of_range": {
                "injection": "each solitary [Nk] -> [N(len(calls)+50)], one at a time",
                "purpose": ("a negative control FOR the positive control: if the ladder does not fire here "
                            "the harness is dead and F1/F2 are void whatever they say"),
                "injected": t(f3, "injected"),
                "caught_by_the_frozen_rule": t(f3, "caught"),
                "off_the_page_after_adjudication": 1054,
                "reached_a_reader": 0,
                "innocent_deletions_after_adjudication": 0,
                "charges": f3["charges"],
                "the_four_the_frozen_rule_left_unscored": (
                    "ab_amb_elnino [N1]->[N62] and [N2]->[N62]: handles_dropped +1, unresolvable +1, token "
                    "GONE -- caught, but the ORIGINAL handle was never spliced so the rule's "
                    "`substituted <= -1` limb could not fire. shape_esc_chain_sugar_ethanol [N22]->[N76]: the "
                    "injection flipped _drop_bare_digit_sentences from SEVER to whole-sentence KILL. "
                    "dv_episode_lanina_arg [N1] (mechanism): the carrier sentence is dropped by the bare-digit "
                    "lint in BOTH arms, so every delta is zero and [N78] is verifiably absent from the page."),
                "verdict": "PASS -- the harness is LIVE and F1/F2 are readable",
            },
            "F1_N_index_plus_1": {
                "injection": "each solitary unsuffixed [Nk] -> [N(k+1)], one at a time",
                "injected": t(f1, "injected"),
                "caught": t(f1, "caught"),
                "missed": t(f1, "missed") + t(f1, "ambiguous"),
                "missed_note": ("835 scored MISSED by the frozen rule; the 2 it left unscored were re-run in "
                                "isolation and are the arm's WORST shape -- ab_amb_elnino [N1]->[N2] and "
                                "[N2]->[N3], where the correct handle rendered NO figure and the shifted one "
                                "rendered a real one from a different receipt (`substituted` went UP). Both "
                                "are counted as misses."),
                "innocent_deletions_after_adjudication": 0,
                "charges": f1["charges"],
                "charges_note": ("166 of the 217 land on counters E.4's (1b) row names (slot_scope_mismatch "
                                 "89 + unresolvable 77); 51 land on counters it does not name "
                                 "(empty_row_addressed 44, direction_sign_mismatch 7). The row's LITERAL "
                                 "spelling names prose_handles.unresolvable -- the [E] census -- which moved "
                                 "ZERO times, so the strict reading fails harder, not softer."),
                "decomposition_no_residual": ("121 dead shifted indices + 89 scope-disjoint + 7 "
                                              "direction-disjoint = 217, exactly the pre-computed census"),
                "verdict": "FAIL",
            },
            "F2_E_real_but_wrong": {
                "injection": ("each solitary [Ek] with k in the EMITTED set (citation_resolved) -> a "
                              "DIFFERENT EMITTED index -- a receipt the reader demonstrably received"),
                "injected": t(f2, "injected"),
                "caught": t(f2, "caught"),
                "missed": t(f2, "missed"),
                "innocent_deletions_after_adjudication": 0,
                "charges": f2["charges"],
                "note": ("ZERO coverage, not partial coverage -- and it is the behaviour the code documents: "
                         "_resolve_evidence_handles resolves POSITIONALLY, so an [E] index pointing at a "
                         "WRONG-BUT-REAL item resolves exactly as the right one does. prose_handles stayed "
                         "{0,0,0,0} on all 791. verify._check_evidence_handle would not have caught them "
                         "either: it convicts only on ZERO lexical overlap with the matched pool."),
                "verdict": "FAIL",
            },
        },
        "scope_gap_ceiling_for_F1": {
            "note": ("computed over all 1,054 solitary [N] occurrences, independent of the scored arms: the "
                     "MAXIMUM number of F1 misses that the missing query.period could conceivably convict "
                     "on a live Batch arm"),
            "shifted_index_dead_out_of_range_or_valueless": 121,
            "shifted_index_resolves": 933,
            "of_which_clause_names_no_declared_crop_year_scope": 710,
            "of_which_clause_speaks_and_replay_row_side_silent_THE_GAP": 117,
            "of_which_both_speak_and_overlap": 17,
            "of_which_both_speak_and_DISJOINT_convictable": 89,
            "consequence": ("even if ALL 117 gap cases convicted live, the [N] miss count stays in the "
                            "hundreds. A ~$1-3 Batch fixture arm cannot change the verdict, so none is "
                            "submitted."),
        },
        "innocent_deletion_conjunct": {
            "verdict": "PASS -- the ONE conjunct of clause (1b) that holds, and it holds cleanly",
            "genuine_innocent_deletions": INNOCENT_DELETIONS_AFTER_ADJUDICATION,
            "cases_injected_across_all_three_arms": 2899,
            "flagged_then_adjudicated_to_the_carrier_sentence": 7,
            "adjudication_rule": ("the carrier key is taken off the PRE-stack input while a lost key comes "
                                  "from the baseline OUTPUT, so a sentence the BASELINE itself trimmed is not "
                                  "byte-equal to its own carrier. Word-SUBSEQUENCE either way settles it; all "
                                  "7 are subsequences."),
            "instrument_self_check": ("the sentence key is self-consistent on 3,281 of 3,281 baseline "
                                      "sentences (every baseline sentence key is a contiguous substring of "
                                      "its own field key)"),
        },
        "materiality_of_the_F1_shift": {
            "note": ("computed independently of the scored arms over every solitary [N] occurrence whose +1 "
                     "shift RESOLVES: what the reader would actually receive if the renderer let it through"),
            "resolvable_shifts": 933,
            "renders_a_DIFFERENT_value": 920,
            "comes_from_a_DIFFERENT_table_metric": 622,
        },
        "verifier_would_not_have_rescued_it": (
            "verify._check_number_handle returns index_out_of_range only for an index outside "
            "1..len(number_calls) (the F3 shape, which the renderer already catches). Its other two "
            "verdicts, number_mismatch and number_unbacked, both read the digits the MODEL wrote "
            "(_claim_numbers_with_decimals over _HANDLE.sub('', sent)); under the handle-only contract the "
            "model writes none, so both are structurally silent for a CORRECT and for a MIS-BOUND in-range "
            "handle alike. Injecting at the postverify seam therefore costs nothing on the F1 shape."),
        "incidental_findings_recorded_not_fixed": [
            ("THE MIXED SEVER CAN GLUE ITS REMNANT ONTO THE PREVIOUS SENTENCE. When the convicted handle "
             "sits in the sentence's OPENING clause and the rest is backed, the cut spans that clause and "
             "its leading space, and the sentence's remnant begins with the separating comma -- which lands "
             "against the previous sentence's terminator ('per se., sitting just below ...'). _DEBRIS_RULES "
             "closes ',.' and ' ,' but has NO rule for '.,'. Minimal deterministic repro recorded at plan "
             "10.25.7 item 1. ZERO occurrences on the r6 treatment arm as it actually ran."),
            ("eval._served_rows can project a call as EMPTY that was not empty: _ROWS_PER_RECORD_CAP=400 is "
             "a per-RECORD budget spent in call order. One answer of 76 hit it. No clause reads served_rows."),
            ("An UNCLOSED handle bracket reached the post-verify prose on dv_sub_ddg_floor ('priced at [N1 is "
             "absent -- the ARS/USD row carries no value;'). _N_HANDLE_HP_RX cannot match it, so no handle "
             "pass can resolve, drop or count it."),
        ],
        "batch_arm_submitted": False,
        "spend_usd": 0.0,
        "code_touched": "NONE. Replay imports the render stack from source; mutants live in the scratchpad.",
        "git_operations": "NONE.",
    }
    return block, verdict


def main(argv=None):
    ap = argparse.ArgumentParser(description="write the clause (1b) block into manifest_d1.json")
    ap.add_argument("--root", default=None, help="repo root (default: derived from this file)")
    ap.add_argument("--result", default=None,
                    help="scored result json (default ROOT/data/dhp_g1/dhp_1b_result.json)")
    ap.add_argument("--manifest", default=None,
                    help="manifest to update (default ROOT/data/dhp_g1/manifest_d1.json)")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root) if args.root else REPO
    result = args.result or os.path.join(root, "data", "dhp_g1", "dhp_1b_result.json")
    man_path = args.manifest or os.path.join(root, "data", "dhp_g1", "manifest_d1.json")

    with open(result, encoding="utf-8") as fh:
        res = json.load(fh)
    block, verdict = build_block(res)

    with open(man_path, encoding="utf-8") as fh:
        man = json.load(fh, object_pairs_hook=collections.OrderedDict)
    man["clause_1b_fixture_positive_control"] = block
    with open(man_path, "w", encoding="utf-8", newline="") as fh:
        json.dump(man, fh, indent=1)
        fh.write("\n")
    print("manifest updated; verdict %s" % verdict)


if __name__ == "__main__":
    main()
