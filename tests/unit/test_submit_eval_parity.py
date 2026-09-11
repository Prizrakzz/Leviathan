"""Unit tests for the submit_eval serving-parity guard (Lane L5, FIX 3).

Covers the PURE diff helper `parity_warnings` + the taskdef env extractor `_graphrag_env_from_taskdef`
+ the `_is_flag_on` value classifier, all without any real boto3 traffic. The guard exists because the
judged-30 submit omitted GRAPHRAG_REROUTE_V2=on, silently making the rv2 eval dimension vacuous while
prod serving (rev-50 taskdef) had the flag ON. `parity_warnings` flags serving-ON GRAPHRAG_* keys that
are ABSENT from the job env (advisory WARN only -- some divergence, e.g. session/provider env, is legit).

jobs/ is not an importable package (pytest pythonpath = ["src"] only), so we load the wrapper by file
path -- mirroring test_submit_evidence_wrappers.py.
"""
from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path

import pytest

_SUBMIT_DIR = Path(__file__).resolve().parents[2] / "jobs" / "submit"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SUBMIT_DIR / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


se = _load("submit_eval")


# --- _is_flag_on ---------------------------------------------------------------------------------

def test_is_flag_on_truthy_values():
    for v in ("on", "1", "true", "yes", "ON", "  True ", "Yes"):
        assert se._is_flag_on(v), v


def test_is_flag_on_falsey_values():
    for v in ("off", "0", "false", "no", "", None, "maybe", "onish"):
        assert not se._is_flag_on(v), v


# --- _graphrag_env_from_taskdef ------------------------------------------------------------------

def test_graphrag_env_extract_filters_prefix_and_joins_containers():
    taskdef = {
        "containerDefinitions": [
            {"environment": [
                {"name": "GRAPHRAG_REROUTE_V2", "value": "on"},
                {"name": "AWS_REGION", "value": "us-east-1"},          # non-GRAPHRAG dropped
                {"name": "GRAPHRAG_CASCADE_QUANT", "value": "on"},
            ]},
            {"environment": [
                {"name": "GRAPHRAG_PROVIDER", "value": "bedrock"},
            ]},
        ]
    }
    assert se._graphrag_env_from_taskdef(taskdef) == {
        "GRAPHRAG_REROUTE_V2": "on",
        "GRAPHRAG_CASCADE_QUANT": "on",
        "GRAPHRAG_PROVIDER": "bedrock",
    }


def test_graphrag_env_extract_tolerates_missing_keys():
    assert se._graphrag_env_from_taskdef({}) == {}
    assert se._graphrag_env_from_taskdef({"containerDefinitions": [{}]}) == {}
    assert se._graphrag_env_from_taskdef({"containerDefinitions": [{"environment": None}]}) == {}


# --- parity_warnings (the load-bearing diff) -----------------------------------------------------

def test_parity_warnings_flags_serving_on_flag_absent_from_job():
    serving = {"GRAPHRAG_REROUTE_V2": "on", "GRAPHRAG_CASCADE_QUANT": "on"}
    job = {"GRAPHRAG_CASCADE_QUANT": "off"}                            # present (even if off) -> not flagged
    assert se.parity_warnings(serving, job) == ["GRAPHRAG_REROUTE_V2"]


def test_parity_warnings_ignores_serving_off_flags():
    # A serving flag that is OFF being absent from the job env is a non-issue (nothing to measure).
    serving = {"GRAPHRAG_REROUTE_V2": "off", "GRAPHRAG_EXPERIMENTAL": "0"}
    assert se.parity_warnings(serving, {}) == []


def test_parity_warnings_present_key_never_flagged_regardless_of_value():
    serving = {"GRAPHRAG_REROUTE_V2": "on"}
    assert se.parity_warnings(serving, {"GRAPHRAG_REROUTE_V2": "on"}) == []
    assert se.parity_warnings(serving, {"GRAPHRAG_REROUTE_V2": "off"}) == []   # divergence != absence


def test_parity_warnings_only_graphrag_prefix():
    serving = {"SOME_OTHER_FLAG": "on", "GRAPHRAG_REROUTE_V2": "on"}
    assert se.parity_warnings(serving, {}) == ["GRAPHRAG_REROUTE_V2"]


def test_parity_warnings_sorted_and_multiple():
    serving = {"GRAPHRAG_ZED": "on", "GRAPHRAG_ALPHA": "on", "GRAPHRAG_MID": "off"}
    assert se.parity_warnings(serving, {}) == ["GRAPHRAG_ALPHA", "GRAPHRAG_ZED"]


def test_parity_warnings_empty_when_serving_env_empty():
    # describe failure yields {} -> no warnings, guard is silent.
    assert se.parity_warnings({}, {"GRAPHRAG_REROUTE_V2": "on"}) == []


def test_default_job_env_ships_reroute_v2_on():
    # Regression: the whole point of FIX 3(a) -- rv2 must be defaulted ON in the submitted job env.
    assert se.DEFAULT_JOB_ENV.get("GRAPHRAG_REROUTE_V2") == "on"


# --- parity_warnings: the never_copy half (S7) -----------------------------------------------------

def test_parity_warnings_honours_never_copy_and_defaults_to_the_shipped_behaviour():
    """A GUARD THAT CRIES ON KEYS NOBODY WILL EVER COPY TRAINS ITS READER TO IGNORE IT. GRAPHRAG_AUTH,
    GRAPHRAG_CREDITS and GRAPHRAG_STORE are serving-ON and must NEVER enter a job env, so they are not
    findings -- while GRAPHRAG_RECENCY_FACTS absent from an arm is the one line that matters.

    The default is EMPTY, so every call without a base is byte-identical to the guard that shipped."""
    serving = {"GRAPHRAG_AUTH": "on", "GRAPHRAG_CREDITS": "on", "GRAPHRAG_RECENCY_FACTS": "on"}
    assert se.parity_warnings(serving, {}) == ["GRAPHRAG_AUTH", "GRAPHRAG_CREDITS",
                                               "GRAPHRAG_RECENCY_FACTS"]
    assert se.parity_warnings(serving, {}, never_copy=("GRAPHRAG_AUTH", "GRAPHRAG_CREDITS")) == \
        ["GRAPHRAG_RECENCY_FACTS"]


# --- parity_mismatches: the half the original guard could not see ----------------------------------

def test_parity_mismatches_sees_a_present_but_DIFFERENT_value():
    """THE FAILURE THAT BIT. GRAPHRAG_MODES=quick,deep against a serving quick,deep,max is PRESENT, so
    `parity_warnings` says nothing -- and a --mode max row is then requested and never honored."""
    serving = {"GRAPHRAG_MODES": "quick,deep,max", "GRAPHRAG_NUMBERS_THINKING": "adaptive"}
    job = {"GRAPHRAG_MODES": "quick,deep", "GRAPHRAG_NUMBERS_THINKING": "adaptive"}
    assert se.parity_warnings(serving, job) == []                       # absence-only guard is blind
    assert se.parity_mismatches(serving, job) == [
        "GRAPHRAG_MODES: job 'quick,deep' != serving 'quick,deep,max'"]


def test_parity_mismatches_allows_a_DECIDED_divergence_and_skips_never_copy():
    """STRIP_AUDIT IS ON IN BOTH ARMS AND OFF IN SERVING, and the design says so. A mismatch a human
    already decided is not a finding; listing it is how the decision is recorded, not re-argued."""
    serving = {"GRAPHRAG_STRIP_AUDIT": "off", "GRAPHRAG_STORE": "dynamo"}
    job = {"GRAPHRAG_STRIP_AUDIT": "on", "GRAPHRAG_STORE": "memory"}
    assert len(se.parity_mismatches(serving, job)) == 2
    assert se.parity_mismatches(serving, job, allow=("GRAPHRAG_STRIP_AUDIT",),
                                never_copy=("GRAPHRAG_STORE",)) == []


def test_parity_mismatches_only_graphrag_and_only_present_keys():
    serving = {"OTHER": "a", "GRAPHRAG_X": "a", "GRAPHRAG_Y": "a"}
    assert se.parity_mismatches(serving, {"OTHER": "b", "GRAPHRAG_X": "b"}) == \
        ["GRAPHRAG_X: job 'b' != serving 'a'"]
    assert se.parity_mismatches({}, {"GRAPHRAG_X": "b"}) == []          # describe failure -> silent


# --- the STORED ARM ENV BASE (S7) ------------------------------------------------------------------
# The base was reconstructed BY HAND for every paid arm until 2026-09-11 and its only record was the
# post-hoc `env_overrides` blob in the run record. These pins grade the FILE: every var the arm needs
# present, every forbidden one absent, and the provenance that lets a run be reproduced.

_REPO = Path(__file__).resolve().parents[2]
_BASE_PATH = _REPO / "configs" / "graphrag" / "arm_env_base.yaml"
_DECK_PATH = _REPO / "configs" / "graphrag" / "eval_queries_state_arm_a_v1.yaml"
#: The reconstructed PRIOR base's own record -- the ONE field of it this deck reads, TRACKED.
_PRIOR_RUN_RECORD = (_REPO / "tests" / "fixtures" / "arm_env_base"
                     / "prior_run_record_2026-09-01_env_overrides.json")
#: Where that fixture was copied from. UNTRACKED (`.gitignore:39 data/batch_runs/`), so it is read
#: only as a drift check when it happens to be present -- never as a precondition of the deck.
_PRIOR_RUN_RECORD_SOURCE = (_REPO / "data" / "batch_runs"
                            / "eval_2026-09-01T10-04-53.025564+00-00.json")

#: THIS DECK NOW RUNS FROM ITS OWN COMMIT, WITH NO SKIPS, AND THAT IS THE WHOLE POINT OF THE CHANGE.
#: Until 2026-09-11 it read three inputs NONE of which were in the repository: `arm_env_base.yaml` and
#: `eval_queries_state_arm_a_v1.yaml` under `.gitignore`'s `configs/graphrag/*`, and a
#: `data/batch_runs/` run record under `.gitignore:39`. On a fresh clone the module fixture raised
#: FileNotFoundError, so the deck ERRORED -- and the first repair, a `pytest.skip` naming a
#: `git add -f`, only traded a red for a green-looking silence on five pins. Both halves are closed
#: properly now: the two configs are NAMED BACK IN by `.gitignore` (the negations beside the three
#: subject decks, written in the rule where a reader can find them rather than carried by an invisible
#: `git add -f`), and the run record is replaced by the small TRACKED fixture above.
#: SO AN ABSENT INPUT IS A FAILURE, NOT A SKIP. All three paths are tracked; a tracked file that is
#: gone is a working tree someone broke, and the message says the one command that fixes it.
_MISSING_INPUT = ("{path} is absent. It is a TRACKED input of this deck ({rule}) -- restore it with "
                  "`git checkout -- {rel}`. This is a FAILURE and not a skip on purpose: a skip here "
                  "would report green for five pins that graded nothing.")


def _require(path: Path, rule: str):
    if not path.exists():
        pytest.fail(_MISSING_INPUT.format(path=path.name, rule=rule,
                                          rel=path.relative_to(_REPO).as_posix()))
    return path


@pytest.fixture(scope="module")
def base():
    return se.load_env_base(_require(_BASE_PATH, ".gitignore negation beside the subject decks"))


@pytest.fixture(scope="module")
def deck():
    import yaml
    text = _require(_DECK_PATH, ".gitignore negation beside the subject decks").read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def test_the_base_parses_and_names_the_taskdef_revision_it_came_from(base):
    """AN ARM WHOSE ENV CAME FROM AN UNNAMED REVISION CANNOT BE REPRODUCED. The file's own provenance
    is graded, not trusted: family, revision, the read date, and the job definition an arm must pass."""
    assert base["schema"].startswith("arm_env_base/")
    td = base["taskdef"]
    assert td["family"] == "leviathan-dev-serving" and int(td["revision"]) >= 133
    assert str(td["read_utc"]) >= "2026-09-11"
    jd = base["job_definition"]
    # THE FIRST HARD BLOCKER THIS FILE EXISTS TO NAME: submit_eval's own default carries ZERO
    # GRAPHRAG_* flags and an image that predates the state-board wiring.
    assert jd["submit_eval_default"] == "leviathan-dev-evidence-build"
    assert jd["arm"] == "leviathan-dev-graphrag-eval" and jd["arm"] != jd["submit_eval_default"]
    # SECRETS CANNOT BE SET THROUGH A containerOverrides AT ALL -- they must be on the jobdef.
    assert set(jd["secrets_required_on_jobdef"]) == {"ANTHROPIC_API_KEY", "EVIDENCE_PG_DSN"}


def test_every_var_the_arm_needs_is_in_the_base(base):
    """THE FIVE THAT DECIDE ARM A, each named with what its absence would cost, plus the four dark legs
    the design lights in BOTH cells and the arm's own flag kept OUT of the base on purpose."""
    env = se.env_from_base(base)
    # the seats, and the two that silently gut a cell
    assert env["GRAPHRAG_SYNTH_MODEL"] == "claude-opus-5"
    assert env["GRAPHRAG_NUMBERS_MODEL"] == "claude-sonnet-5"
    assert env["GRAPHRAG_NUMBERS_THINKING"] == "adaptive"   # the V2-3/V2-5 arms ran this OFF
    assert env["GRAPHRAG_RECENCY_FACTS"] == "on"            # else the board declines recency_facts_off
    assert env["GRAPHRAG_RESPONSE_CONTRACT"].startswith("verification,ranking,")
    assert env["GRAPHRAG_PROVIDER"] == "anthropic"          # bedrock disarms adaptive thinking
    # the tier allowlist: the prior base's `quick,deep` requested `max` and never honored it
    assert env["GRAPHRAG_MODES"] == "quick,deep,max"
    # in-VPC or the board declines pg_not_live on every turn
    assert env["GRAPHRAG_NUMBERS_BACKEND"] == "pg"
    # the FOUR dark legs, lit in BOTH cells so the board is measured against the estate it lives in
    for leg in ("GRAPHRAG_EXTREME_LOCATOR", "GRAPHRAG_RV_REGIONAL", "GRAPHRAG_COT_OUTCOMES",
                "GRAPHRAG_CASCADE_CONTEXT"):
        assert env[leg] == "on", leg
    assert env["GRAPHRAG_STRIP_AUDIT"] == "on"              # a DECIDED divergence from serving's off
    # THE ARM'S OWN FLAG IS NOT IN THE BASE: it is the treatment, passed per cell, so the two cells
    # differ by exactly one --env and the control's flag-off turn stays byte-identical.
    assert base["arm_flag"] == "GRAPHRAG_STATE_BOARD"
    assert "GRAPHRAG_STATE_BOARD" not in env


def test_the_forbidden_vars_are_absent_from_the_base_env(base):
    """NEVER_COPY IS A LIST OF THINGS THE BUILT ENV MUST NOT CONTAIN, and it is asserted against the
    BUILT env rather than read back out of its own section -- the two could disagree, and only one of
    them is what a container receives."""
    env = se.env_from_base(base)
    never = base["never_copy"]
    assert len(never) == 25
    assert not (set(env) & set(never)), sorted(set(env) & set(never))
    # THE CLASSES THAT WOULD DO REAL DAMAGE, named rather than counted
    for k in ("GRAPHRAG_METER_EXEMPT_SUBS",                 # a real Cognito sub = a user identity
              "GRAPHRAG_STORE", "GRAPHRAG_STORE_TABLE", "GRAPHRAG_SESSIONS_TABLE",  # production writes
              "GRAPHRAG_CREDITS_LIMIT", "GRAPHRAG_TURN_QUOTA",    # a 34-turn arm halts mid-deck
              "GRAPHRAG_FRONT_EXPIRY_METRICS",              # pollutes the production dashboards
              "GRAPHRAG_GUARDRAIL", "GRAPHRAG_RERANK_BACKEND"):
        assert k in never and k not in env, k
        assert isinstance(never[k], str) and len(never[k]) > 20, k   # every one carries its reason
    # NO KEY IS IN TWO SECTIONS -- `load_env_base` refuses that shape, and this says why it matters.
    assert not (set(base["copy_from_taskdef"]) & set(never))
    assert not (set(base["arm_only"]) & set(never))


def test_the_base_refuses_a_drifted_taskdef_and_shows_an_unclassified_one(base):
    """THE FILE IS THE RECORD, THE TASKDEF IS THE AUTHORITY. Drift is an ERROR (an arm measuring a seat
    nobody serves); a NEW serving flag is a WARNING (a decision nobody has made yet). The asymmetry is
    the point: an unmade decision must be shown, never guessed either way."""
    live = dict(base["copy_from_taskdef"])
    assert se.base_drift(base, live) == []
    assert se.base_new_in_serving(base, live) == []
    assert se.base_drift(base, dict(live, GRAPHRAG_NUMBERS_THINKING="off")) == \
        ["GRAPHRAG_NUMBERS_THINKING: base 'adaptive' != live 'off'"]
    gone = {k: v for k, v in live.items() if k != "GRAPHRAG_RECENCY_FACTS"}
    assert se.base_drift(base, gone) == \
        ["GRAPHRAG_RECENCY_FACTS: in the stored base, ABSENT from the live taskdef"]
    # A DESCRIBE FAILURE YIELDS NO DRIFT: the caller decides whether to proceed without the authority.
    assert se.base_drift(base, {}) == []
    assert se.base_new_in_serving(base, dict(live, GRAPHRAG_BRAND_NEW="on")) == ["GRAPHRAG_BRAND_NEW"]
    # arm_only counts as CLASSIFIED even though serving carries it at another value
    assert se.base_new_in_serving(base, dict(live, GRAPHRAG_STRIP_AUDIT="off")) == []


def test_load_env_base_refuses_shapes_that_would_submit_an_arm_with_no_parity(tmp_path):
    """A BASE THAT SILENTLY PARSED TO {} WOULD SUBMIT AN ARM WITH NO PARITY AT ALL -- the exact failure
    the file exists to close. Every refusal below is that one sentence in a different costume."""
    def _w(text):
        p = tmp_path / "b.yaml"
        p.write_text(text, encoding="utf-8")
        return p
    with pytest.raises(FileNotFoundError):
        se.load_env_base(tmp_path / "nope.yaml")
    with pytest.raises(ValueError):
        se.load_env_base(_w("schema: something_else/v1\n"))
    with pytest.raises(ValueError):                        # no provenance
        se.load_env_base(_w("schema: arm_env_base/v1\ntaskdef:\n  family: x\n"))
    with pytest.raises(ValueError):                        # both demanded and forbidden
        se.load_env_base(_w("schema: arm_env_base/v1\ntaskdef:\n  family: x\n  revision: 1\n"
                            "copy_from_taskdef:\n  A: 'on'\nnever_copy:\n  A: why\n"))


def test_the_diff_against_the_prior_base_is_recorded_and_names_the_one_changed_key(base):
    """THE PRIOR BASE HAD NO FILE, so it is reconstructed and recorded here in full -- a future refresh
    diffs against a real predecessor rather than against nothing. The ONE changed key is the trap."""
    prior, diff = base["prior_base"], base["diff_vs_prior_base"]
    assert prior["distinct_names"] == 33 and len(prior["sources"]) == 3
    assert len(diff["added"]) == 17 and len(diff["added_arm_only"]) == 4
    assert diff["removed"] == []
    assert set(diff["changed"]) == {"GRAPHRAG_MODES"}
    assert diff["changed"]["GRAPHRAG_MODES"]["prior"] == "quick,deep"
    assert diff["changed"]["GRAPHRAG_MODES"]["now"] == "quick,deep,max"
    # every ADDED name really is in the new base, and none of them was in the prior one's job env
    env = se.env_from_base(base)
    # THE THIRD UNTRACKED INPUT, NOW TRACKED. This was a `data/batch_runs/` run record ignored by
    # `.gitignore:39` and read with a bare `.read_text()`, so these pins skipped on every clone. The
    # fixture carries that record's `env_overrides` field VERBATIM and nothing else.
    fixture = json.loads(_require(_PRIOR_RUN_RECORD, "tests/fixtures/, tracked")
                         .read_text(encoding="utf-8"))
    prior_env = fixture["env_overrides"]
    assert fixture["_verbatim"] is True and len(prior_env) == 25
    # A COPY THAT NOBODY CHECKS IS A COPY THAT DRIFTS. When the original happens to be on this machine
    # (it is untracked, so usually only on the machine that ran the arm) the two are compared. This is
    # an EXTRA assertion under an `if`, never a skip: its absence must not weaken the pins above.
    if _PRIOR_RUN_RECORD_SOURCE.exists():
        original = json.loads(_PRIOR_RUN_RECORD_SOURCE.read_text(encoding="utf-8"))
        assert original["env_overrides"] == prior_env, "the tracked fixture has drifted from the record"
        assert original["run_id"] == fixture["run_id"]
    for k in list(diff["added"]) + list(diff["added_arm_only"]):
        assert k in env, k
        assert k not in prior_env, k


def test_the_run_record_carries_the_arms_identity_and_the_cli_names_the_base():
    """AN ARM'S IDENTITY BELONGS IN ITS ARTIFACT. `env_overrides` alone records what was TYPED, not
    what was RUN -- read from the SOURCE, because the write itself needs a live boto3 submit."""
    src = (_SUBMIT_DIR / "submit_eval.py").read_text(encoding="utf-8")
    for key in ('"job_definition": job_definition', '"env_base_file": args.env_base',
                '"taskdef_rev": taskdef_rev', '"job_env": dict(job_env)'):
        assert key in src, key
    for flag in ('"--job-definition"', '"--env-base"', '"--from-taskdef"'):
        assert flag in src, flag
    # THE DEFAULT IS UNCHANGED so nothing existing moves: an arm OPTS IN to the right jobdef.
    assert 'job_definition = f"{project}-{env}-evidence-build"' in src
    assert se.DEFAULT_ENV_BASE == "configs/graphrag/arm_env_base.yaml"
    # PRECEDENCE IS ONE SENTENCE: DEFAULT_JOB_ENV -> base -> --env (the user always wins).
    assert src.index("job_env: dict[str, str] = dict(DEFAULT_JOB_ENV)") \
        < src.index("job_env.update(env_from_base(base_doc))") \
        < src.index("job_env.update({k: v for k, v in env_pairs})")


# --- THE FIX ROUND (2026-09-11): the guard's own blind spots -------------------------------------

def test_the_bases_UNDECIDED_keys_are_loud_and_the_submit_refuses_until_each_is_named(base):
    """THE ONE UNDECIDED KEY WAS SILENCED BY CONSTRUCTION, and this test MEASURES that silence before
    pinning the fix.

    `GRAPHRAG_RERANK_BACKEND` is parked in `open_decisions` as "unresolved" and the base's own words
    call it "a GENUINE parity var". It is also -- correctly, the eval jobdef carries no COHERE_API_KEY
    -- in `never_copy`, and `never_copy` is the ONE section that `parity_warnings` SKIPS, `base_drift`
    never walks, and `base_new_in_serving` counts as CLASSIFIED. All three are asserted below against a
    serving env that carries the key at prod's own value: every existing guard says nothing at all.

    So the decision is made LOUD at the one place left -- `main()` -- and a submission REFUSES until
    the operator names each open key with `--accept-open-decision`, whose acceptance then rides the run
    record. The A/B delta survives either way (the key is constant across both cells); what does not
    survive silence is the arm report's obligation to say WHICH retrieval it measured."""
    assert se.open_decision_keys(base) == ["GRAPHRAG_RERANK_BACKEND"]
    assert se.open_decision_keys({}) == [] and se.open_decision_keys({"open_decisions": [None]}) == []
    key = "GRAPHRAG_RERANK_BACKEND"
    assert key in base["never_copy"]
    # MEASURED SILENCE: serving sets it ON-ish, the job env does not carry it, and no guard speaks.
    serving = {key: "cohere", "GRAPHRAG_RECENCY_FACTS": "on"}
    never = tuple(base["never_copy"])
    assert se.parity_warnings(serving, {"GRAPHRAG_RECENCY_FACTS": "on"}, never_copy=never) == []
    assert se.parity_mismatches(serving, {key: "bge"}, never_copy=never) == []
    assert key not in se.base_new_in_serving(base, serving)
    assert not any(k.startswith(key) for k in se.base_drift(base, serving))
    # AND THE ONE PLACE THAT DOES SPEAK. The refusal runs where the base is loaded -- BEFORE the
    # dry-run return -- so a $0 rehearsal exercises the real check, exactly like `--from-taskdef`.
    src = (_SUBMIT_DIR / "submit_eval.py").read_text(encoding="utf-8")
    assert '"--accept-open-decision"' in src
    assert "open_decision_keys(base_doc)" in src
    assert 'refusing to submit: {args.env_base} parks' in src
    assert '"open_decisions_accepted": list(args.accept_open_decisions or [])' in src
    assert src.index("open_decision_keys(base_doc)") < src.index("if args.dry_run:")


def test_the_unclassified_scan_sees_EVERY_prefix_and_not_only_the_graphrag_half(base):
    """A PREFIX FILTER DECLARED THE GUARD BLIND TO A CLASS THE BASE ITSELF DECIDES. The file classifies
    TEN non-GRAPHRAG serving keys by hand (three COGNITO_*, two EVIDENCE_PG_*, and the jobdef's baked
    PYTHONPATH / AWS_REGION / LEVIATHAN_* / EVIDENCE_*), so a scan over `GRAPHRAG_*` alone could not
    see a NEW `EVIDENCE_*`, `COGNITO_*` or bare serving key at all.

    MEASURED against `leviathan-dev-serving:133` on 2026-09-11: all 73 keys (63 GRAPHRAG_*, 10 others)
    classify, so widening the scan reports ZERO new lines today -- it costs nothing but visibility."""
    live = dict(base["copy_from_taskdef"])
    assert se.base_new_in_serving(base, live) == []
    # the already-classified non-GRAPHRAG halves stay silent, from all three sections that hold them
    for k in ("COGNITO_REGION", "EVIDENCE_PG_POOL"):          # never_copy
        assert se.base_new_in_serving(base, dict(live, **{k: "x"})) == [], k
    for k in ("PYTHONPATH", "EVIDENCE_S3"):                   # container_env_on_jobdef
        assert se.base_new_in_serving(base, dict(live, **{k: "x"})) == [], k
    # AND THE NEW ONES ARE SEEN, whatever their prefix -- this is the half that was invisible.
    assert se.base_new_in_serving(base, dict(live, EVIDENCE_BRAND_NEW="x")) == ["EVIDENCE_BRAND_NEW"]
    assert se.base_new_in_serving(base, dict(live, COGNITO_NEW_POOL="x", GRAPHRAG_NEW="on")) == \
        ["COGNITO_NEW_POOL", "GRAPHRAG_NEW"]


def test_the_classification_fetch_reads_every_env_key_and_the_flag_guard_keeps_its_filter():
    """TWO READERS, TWO SCOPES, and the split is deliberate. `--from-taskdef` CLASSIFIES, so it needs
    the whole env (see the test above). The advisory parity guard grades FLAGS, so it keeps its
    `GRAPHRAG_` filter -- it has no opinion about `AWS_REGION` and should not learn one."""
    taskdef = {"containerDefinitions": [
        {"environment": [{"name": "GRAPHRAG_A", "value": "on"}, {"name": "AWS_REGION", "value": "us-east-1"}]},
        {"environment": [{"name": "EVIDENCE_S3", "value": "s3://x"}, {"name": "", "value": "dropped"}]},
    ]}
    assert se._all_env_from_taskdef(taskdef) == {"GRAPHRAG_A": "on", "AWS_REGION": "us-east-1",
                                                 "EVIDENCE_S3": "s3://x"}
    assert se._graphrag_env_from_taskdef(taskdef) == {"GRAPHRAG_A": "on"}
    assert se._all_env_from_taskdef({}) == {}


def test_one_authority_one_family_and_two_distinguishable_cells():
    """THE THREE SUBMISSION-TIME AMBIGUITIES, closed together because they are the same mistake.

    (1) TWO AUTHORITIES: `--from-taskdef` refused against the NAMED revision, then the parity warning
        re-described `leviathan-dev-serving` with NO revision -- the LATEST ACTIVE one. A revision
        registered but not deployed made the refusal and the warning disagree about "live", at the
        cost of a second describe call. The fetched env is passed down instead.
    (2) TWO FAMILIES: nothing compared `--from-taskdef`'s ref against the base's own
        `taskdef.family`, so a base banked at `leviathan-dev-serving:133` could be "verified" against
        any family whose env happens not to drift. Family mismatch REFUSES; a revision that MOVED is a
        loud warning (every copied key has just been graded against the live one) and BOTH numbers now
        ride the run record, so the file can no longer claim a revision nobody checked.
    (3) TWO CELLS, ONE NAME: only GRAPHRAG_PROVIDER contributed a job-name suffix, so an arm's
        treatment (`--env GRAPHRAG_STATE_BOARD=on`) and its control both rendered
        `eval-eval-queries-state-arm-a-v1-claude-opus-5-deep` -- the very ambiguity `--mode` and
        `--only-ids` were given suffixes to fix. The suffix is keyed on the BASE's own `arm_flag`, so
        every submission without a base is byte-identical to what shipped."""
    src = (_SUBMIT_DIR / "submit_eval.py").read_text(encoding="utf-8")
    # (1) one authority
    assert "serving_env: dict[str, str] | None = None" in src
    assert "_emit_parity_warning(aws_region, job_env, base=base_doc, serving_env=_serving_env)" in src
    assert src.count("_fetch_serving_graphrag_env(region)") == 1     # the no-base path only
    # (2) one family, and both revisions recorded
    assert "refusing to submit: --env-base" in src and "grades nothing." in src
    assert "TASKDEF REVISION MOVED" in src
    assert '"taskdef_rev_in_base": taskdef_rev_in_base' in src
    # (3) two distinguishable cells
    assert '_arm_flag = str((base_doc or {}).get("arm_flag") or "")' in src
    assert src.index('if args.mode:') < src.index("_arm_flag = str(")


# --- ROUND 2 (2026-09-11): THE BASE'S THREE PRECONDITIONS, AND THE OPEN DECISION IN THE HEADER -----
# The base's `job_definition:` block states three facts about the VENUE an arm must run in -- the job
# definition, the queue and the secrets that definition has to carry -- and until this round the
# submitter read the file for its env sections ONLY. Prose nobody grades is prose that drifts, which
# is the same sentence this whole file exists to answer, one block down the same YAML.

def test_the_base_states_three_venue_preconditions_and_the_submitter_now_reads_all_three(base):
    """WHAT THE FILE CLAIMS, read back through the accessors the submitter uses. Each one is a fact
    about WHERE an arm runs, and each failure mode is different: the wrong definition measures a tree
    with no board, the wrong queue is reclaimed mid-deck, a missing secret cannot be repaired at all."""
    assert se.required_jobdef(base) == "leviathan-dev-graphrag-eval"
    assert se.required_queue(base) == "leviathan-dev-queue-ondemand"
    assert se.required_secrets(base) == ["ANTHROPIC_API_KEY", "EVIDENCE_PG_DSN"]
    # the accessors are total: no base, no `job_definition:` block, no preconditions
    assert se.required_jobdef({}) == "" and se.required_queue({}) == "" and se.required_secrets({}) == []
    assert se.required_jobdef({"job_definition": {}}) == ""
    # a family compares as a FAMILY, however the reference was spelled
    assert se.jobdef_family("leviathan-dev-graphrag-eval:15") == "leviathan-dev-graphrag-eval"
    assert se.jobdef_family("arn:aws:batch:us-east-1:1:job-definition/leviathan-dev-graphrag-eval:15") \
        == "leviathan-dev-graphrag-eval"
    assert se.jobdef_family("") == ""


def test_the_jobdef_precondition_refuses_the_silent_default_and_makes_a_departure_say_so(base):
    """TWO REFUSALS FOR TWO MISTAKES. Falling through to submit_eval's own default is the silent one --
    `leviathan-dev-evidence-build` carries ZERO GRAPHRAG_* flags and an image older than the board, so
    the arm bills in full and measures a tree with no board in it. Naming ANOTHER definition on purpose
    is a decision, and a decision only has to be said out loud."""
    dflt = "leviathan-dev-evidence-build"
    msg = se.jobdef_refusal(base, job_definition=dflt, explicit=False)
    assert msg and "ZERO GRAPHRAG_* flags" in msg and "--job-definition leviathan-dev-graphrag-eval" in msg
    # named on purpose, but not acknowledged -> still refused, and the refusal names the token
    msg2 = se.jobdef_refusal(base, job_definition="some-other-def:3", explicit=True)
    assert msg2 and "--accept-open-decision job_definition" in msg2
    # `ALL` IS NOT A VENUE TOKEN. ALL accepts the base's open_decisions KEYS; a venue departure is not
    # one of them, and a flag that quietly widened would be the fence deleting itself.
    assert se.jobdef_refusal(base, job_definition="some-other-def:3", explicit=True, accepted=("ALL",))
    # THE TOKEN ALONE ACQUITS NOTHING -- the rule is `--job-definition` AND the token, and this is the
    # pin the first round did not have. Round 1 shipped an OR (the token returned None before `explicit`
    # was read), so `--accept-open-decision job_definition` with NO `--job-definition` waved through the
    # SILENT fall-through to `leviathan-dev-evidence-build`: measured end to end at --dry-run as EXIT 0,
    # "VENUE DEPARTURE [ACCEPTED]", "[DRY RUN] would submit" -- the zero-GRAPHRAG_*, pre-board-wiring
    # venue this very function's docstring calls the silent one, acquitted by a token whose own sentence
    # says a departure is a decision and not a typo. The deck was green over the hole because it pinned
    # explicit=False+no-token and explicit=True+token and never this third cell. There is no decision in
    # a fall-through to acknowledge, so the token cannot reach it.
    msg3 = se.jobdef_refusal(base, job_definition=dflt, explicit=False, accepted=("job_definition",))
    assert msg3 and "ZERO GRAPHRAG_* flags" in msg3
    assert "does NOT cover this either" in msg3       # and the refusal SAYS why the token did not help
    assert se.jobdef_refusal(base, job_definition=dflt, explicit=False,
                             accepted=("job_definition", "ALL")) is not None
    # named AND acknowledged -> allowed
    assert se.jobdef_refusal(base, job_definition="some-other-def:3", explicit=True,
                             accepted=("job_definition",)) is None
    # the base's own definition passes, pinned or not
    assert se.jobdef_refusal(base, job_definition="leviathan-dev-graphrag-eval:15", explicit=True) is None
    assert se.jobdef_refusal(base, job_definition="leviathan-dev-graphrag-eval", explicit=True) is None
    # NO BASE -> NO PRECONDITION: every submission that predates S7 is unchanged.
    assert se.jobdef_refusal({}, job_definition=dflt, explicit=False) is None


def test_the_queue_precondition_has_NO_acknowledgement_token(base):
    """THE ASYMMETRY IS THE POINT. `leviathan-dev-queue` is SPOT and is submit_eval's own default, so
    the failure is the quiet one: an arm submitted with no `--queue` at all can be reclaimed mid-deck
    and bill in full for a half-populated artifact. There is no token to wave that through -- the base
    NAMES the queue, and running somewhere else means re-banking the base, which leaves a record."""
    msg = se.queue_refusal(base, job_queue="leviathan-dev-queue")
    assert msg and "SPOT" in msg and "--queue leviathan-dev-queue-ondemand" in msg
    assert "NO --accept-open-decision token" in msg
    assert se.queue_refusal(base, job_queue="leviathan-dev-queue-ondemand") is None
    assert se.queue_refusal({}, job_queue="leviathan-dev-queue") is None      # no base, no precondition
    # AN ARN NAMING THE BASE'S OWN QUEUE IS THE BASE'S OWN QUEUE. The jobdef check next door already
    # collapses ARN/family/revision through `jobdef_family`; round 1 compared queues by raw string, so
    # an operator who spelled the right queue as an ARN was refused by a sentence telling him to pass
    # the queue he had just passed. A refusal an operator cannot act on is a fence that gets deleted.
    assert se.queue_name("arn:aws:batch:us-east-1:1:job-queue/leviathan-dev-queue-ondemand") \
        == "leviathan-dev-queue-ondemand"
    assert se.queue_name("leviathan-dev-queue-ondemand") == "leviathan-dev-queue-ondemand"
    assert se.queue_name("") == ""
    assert se.queue_refusal(
        base, job_queue="arn:aws:batch:us-east-1:1:job-queue/leviathan-dev-queue-ondemand") is None
    # and the SPOT queue spelled as an ARN is still refused -- the collapse widens nothing
    assert se.queue_refusal(base, job_queue="arn:aws:batch:us-east-1:1:job-queue/leviathan-dev-queue")
    # the signature itself carries the ruling: there is no `accepted` parameter to pass one
    import inspect
    assert "accepted" not in inspect.signature(se.queue_refusal).parameters


def test_the_departure_token_name_is_reserved_and_the_base_does_not_collide_with_it(base):
    """ONE FLAG, TWO NAMESPACES. `--accept-open-decision` takes the base's `open_decisions` KEYS and one
    non-key token, `job_definition`. A base that ever parked an open decision under that literal key
    would make one token mean two things at the same prompt. Nothing does today -- and this pin is what
    makes that a measured fact rather than an assumption, with the rule stated in the flag's own help."""
    assert se._JOBDEF_DEPARTURE_TOKEN == "job_definition"
    assert se.open_decision_keys(base) == ["GRAPHRAG_RERANK_BACKEND"]
    assert se._JOBDEF_DEPARTURE_TOKEN not in se.open_decision_keys(base)
    src = (_SUBMIT_DIR / "submit_eval.py").read_text(encoding="utf-8")
    assert "RESERVED TOKEN NAME" in src           # the rule a future base author reads before naming a key
    # the bare-family secrets lookup walks EVERY page: `max(revision)` over page 1 of a family with more
    # than one page of ACTIVE revisions would grade a revision Batch would not run, in the one place
    # whose whole job is to grade the right one. (Measured benign today: evidence-build 135, eval 14.)
    i = src.index("def _fetch_jobdef_secrets(")
    body = src[i:src.index("\ndef ", i + 1)]
    assert "nextToken" in body and "while True:" in body


def test_the_secrets_precondition_refuses_what_no_flag_at_the_prompt_could_repair(base):
    """A BATCH `containerOverrides` CANNOT SET SECRETS AT ALL. A definition missing ANTHROPIC_API_KEY
    or EVIDENCE_PG_DSN therefore dies at container start, or -- worse, because it looks like a result
    -- serves a board that declines `pg_not_live` on every single turn, the artifact class with three
    prior instances. An EMPTY secrets block is the full refusal list, never a quiet pass."""
    assert se.missing_jobdef_secrets(base, ["EVIDENCE_PG_DSN", "ANTHROPIC_API_KEY"]) == []
    assert se.missing_jobdef_secrets(base, ["ANTHROPIC_API_KEY"]) == ["EVIDENCE_PG_DSN"]
    assert se.missing_jobdef_secrets(base, []) == ["ANTHROPIC_API_KEY", "EVIDENCE_PG_DSN"]
    assert se.missing_jobdef_secrets(base, None) == ["ANTHROPIC_API_KEY", "EVIDENCE_PG_DSN"]
    assert se.missing_jobdef_secrets({}, []) == []                            # no base, no precondition


def test_the_three_preconditions_run_before_the_dry_run_return_and_only_under_a_base():
    """A $0 REHEARSAL MUST EXERCISE THE REAL CHECKS -- the `--from-taskdef` idiom, applied to the venue.
    All three live inside the `--env-base` guard (so every pre-S7 submission is byte-identical) and all
    three run BEFORE the dry-run return (so the six dry runs an arm rehearses are the six it submits)."""
    src = (_SUBMIT_DIR / "submit_eval.py").read_text(encoding="utf-8")
    i_base, i_dry = src.index("    if args.env_base:"), src.index("if args.dry_run:")
    for call in ("jobdef_refusal(base_doc", "queue_refusal(base_doc", "_fetch_jobdef_secrets(aws_region"):
        assert i_base < src.index(call) < i_dry, call
    # the jobdef describe RAISES rather than degrading: an unverified precondition before a paid arm
    # is a stop, not a shrug (the same ruling `_fetch_taskdef` carries one function up).
    assert "def _fetch_jobdef_secrets(" in src and "raise SystemExit" in src
    # and the venue rides the run record, measured rather than typed
    assert '"jobdef_revision": jobdef_rev' in src and '"jobdef_secrets": list(jobdef_secrets)' in src


def test_an_open_decision_is_never_silenced_by_never_copy_and_is_printed_in_the_run_header(base, caplog):
    """THE TWO SECTIONS SAY DIFFERENT THINGS and the second must outrank the first inside a guard whose
    whole job is visibility: `never_copy` says "the arm must not carry this", `open_decisions` says
    "nobody has decided". So the parity guard's skip set is never_copy MINUS the open keys.

    MEASURED, AND IT IS WHY THE HEADER LINE EXISTS: on `leviathan-dev-serving:133` the one open key is
    `GRAPHRAG_RERANK_BACKEND=cohere`, and `_is_flag_on("cohere")` is False -- so the ABSENCE guard has
    no opinion about it even after the widening. The header line does not depend on the value being
    flag-ish, and it is the half that always fires."""
    assert not se._is_flag_on("cohere")                    # the measured value, and it reads as OFF
    key = "GRAPHRAG_RERANK_BACKEND"
    assert se.open_decision_keys(base) == [key]
    open_base = {"never_copy": {key: "a reason"}, "open_decisions": [{"key": key}]}
    closed_base = {"never_copy": {key: "a reason"}}
    # with the key merely never_copied, the guard is silent; with it ALSO open, the guard speaks
    for doc, expect_seen in ((closed_base, False), (open_base, True)):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="submit_eval"):
            se._emit_parity_warning("us-east-1", {}, base=doc, serving_env={key: "on"})
        assert (key in caplog.text) is expect_seen, (doc, caplog.text)
    src = (_SUBMIT_DIR / "submit_eval.py").read_text(encoding="utf-8")
    assert "_open = set(open_decision_keys(base or {}))" in src
    # THE RUN HEADER, at every submission -- not only in the block that fires once when the base loads.
    assert "OPEN DECISION IN THIS RUN" in src
    assert src.index("OPEN DECISION IN THIS RUN") < src.index("if args.dry_run:")
    assert '"open_decisions_effective": dict(_open_effective)' in src


# --- ROUND 2: THE SEVENTH DECK ROW ---------------------------------------------------------------

def test_the_arm_deck_carries_seven_rows_and_the_seventh_flags_its_own_provenance(deck):
    """DESIGN 10.3/10.4 SAY SEVEN and the blind panel's arithmetic (7 pairs x 2 judges + 1 tally = 15
    agents, the workflow cap) only closes at seven. The seventh is the arc's ORIGIN turn -- the OWNER's
    own 2026-09-07 Cascade turn on soybeans, which is also the design's sec 0.3 Scenario 1 and the
    shipped harness scenario `soybeans_now`.

    IT IS FLAGGED `owner_verbatim: true`, AND THE ROUND-1 `false` IS THE THING THIS PIN EXISTS TO STOP
    COMING BACK. Round 1 searched THE TREE, found only agent-authored renderings, and then wrote a claim
    about THE RECORD: "no source ... says these are the words the OWNER TYPED". The living memory's
    D-EC wave file records the owner's own live stream request at :2041 -- `GET /v1/respond/stream ...
    mode=max on '<this exact string>'` at 09-07 10:47-10:49Z on rev 131, with his read of that answer at
    :2044 -- so the string in this deck IS the operator's, byte for byte, at the right date and tier.
    The pin therefore grades BOTH halves: the flag is true, and the provenance still NAMES the memory
    record, because a true flag with no citation is the same unmarked attribution in the other
    direction. A logged request is not a keystroke capture and the deck's header says so; what it
    cannot say is that no such record exists."""
    rows = deck["queries"]
    assert len(rows) == 7 and len({r["id"] for r in rows}) == 7
    seventh = rows[-1]
    assert seventh["id"] == "rv_soybeans_state_2026_09_07"
    assert seventh["contract"] == "soybeans_cbot" and seventh["category"] == "state_arm_a"
    assert seventh["expected_intent"] == "reasoning" and seventh["expect"]["needs_evidence"] is True
    assert seventh["owner_verbatim"] is True
    prov = seventh["provenance"]
    assert "project_dec_evidence_corpus.md:2041" in prov      # the owner's own stream request
    assert "OWNER CASCADE SMOKE #2" in prov and "2044" in prov
    assert "STATE_ENGINE_DESIGN_2026-09-07.md" in prov        # the two corroborating renderings
    assert "state/__main__.py" in prov
    # AND THE HEADER STATES THE GRADE OF EVIDENCE rather than asserting a transcript exists: the record
    # is a logged request from the owner's stream, which was weighed, not skipped.
    hdr = _DECK_PATH.read_text(encoding="utf-8")
    assert "LOGGED REQUEST" in hdr and "not a keystroke capture" in hdr
    # NO PINNED asof ON ANY ROW: the rv reading rides the price_replay belt (a historical as-of drops
    # it whole) and design 10.3 binds both cells to the LIVE as-of inside one calendar window.
    assert not any("asof" in r for r in rows)
    # THE QUESTION IS THE ONE THE TREE SHIPS, byte for byte -- not a paraphrase of it. Both sources are
    # checked where they exist, because a copy nobody compares is a copy that drifts.
    q = seventh["question"]
    assert q == "what is the situation on soybeans now? how is it looking 3 months from now?"
    harness = _REPO / "src" / "leviathan" / "graphrag" / "state" / "__main__.py"
    assert q in harness.read_text(encoding="utf-8")
    design = _REPO / "docs" / "private" / "STATE_ENGINE_DESIGN_2026-09-07.md"
    if design.exists():                                   # docs/private/ is not in the repository
        assert q in design.read_text(encoding="utf-8")


def test_the_scan_cost_probe_trio_still_names_rows_this_deck_carries(deck):
    """THE PROBE IS A NAMED SUBSET OF THIS DECK, so `--only-ids` must resolve against it -- an unknown
    id is a hard error inside the container, AFTER the job has been billed for its start. The trio is
    unchanged by the seventh row and still spans three different fans (vegoil / grain / palm), so the
    cost row stays attributable to three boards rather than three rows off one."""
    ids = {r["id"] for r in deck["queries"]}
    trio = ["rv_soyoil_palm", "rv_corn_wheat", "rv_palm_rapeoil"]
    assert set(trio) <= ids
    assert len({r["contract"] for r in deck["queries"] if r["id"] in trio}) == 3
    # the deck's header prints the probe line; it must name the same three
    text = _DECK_PATH.read_text(encoding="utf-8")
    assert "--mode quick --only-ids " + ",".join(trio) in text
