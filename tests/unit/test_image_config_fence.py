"""FENCE 1 (incident I-1) -- image-vs-config age. Every test here fails if the fence is removed.

WHAT THE FENCE IS FOR. On 2026-07-24 jobdef ``leviathan-dev-silver-gate`` ran image
``sha256:3590b188``, built from commit ``e0a33bf2``, which carried 43 files in
``configs/silver/tables/``. ``silver_futures_eod.yaml`` landed 2026-07-28, AFTER that build. The
scheduled gate was asked to gate ``silver_futures_eod`` and printed::

    FAIL silver_futures_eod (branch unknown): dispatch=table not in the F010 silver registry

That sentence names the CONFIG. The fault was the IMAGE. Cost: an 11-agent RCA and a week of
skipped canonical promotes.

The tests below replay that exact fire against the fenced code and assert the container now names
ITSELF -- its baked table count, its commit, its build date, the Glue corroboration and the
remedy -- rather than pointing at a file that was correct all along.

NO AWS, NO NETWORK, NO DOCKER. Every seam (registry loader, manifest loader, Glue probe) is
injected. The Dockerfile and .ps1 halves of the fence are covered structurally, because a
Dockerfile RUN line and a PowerShell assertion are otherwise untestable by pytest -- and an
untested half of a fence is the half that silently disappears.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from jobs.audit import silver_rebuild_gate as gate  # noqa: E402
from leviathan.common import image_stamp  # noqa: E402

FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "image_fence" / "baked_tables_e0a33bf2.json"
E0A33BF2 = json.loads(FIXTURE.read_text(encoding="utf-8"))
BAKED_43 = E0A33BF2["silver_tables"]

# The ask, verbatim from infra/terraform/envs/dev/dag_schedules.auto.tfvars.json, family
# futures_eod_databento: gate.command = [..., "--tables", "silver_futures_eod", ...]
ASKED = "silver_futures_eod"


# ---------------------------------------------------------------------------
# Stubs: the three seams the fence reaches through.
# ---------------------------------------------------------------------------
class _Reg:
    """Stand-in for leviathan.silver.registry.SilverRegistry."""

    def __init__(self, names):
        self.tables = {n: {"table_name": n} for n in names}


def _registry_loader(names):
    return lambda: _Reg(names)


def _manifest_e0a33bf2():
    """The manifest image sha256:3590b188 WOULD carry had it been built with the fence."""
    return lambda: {"schema": 1, "git_commit": "e0a33bf2", "build_time_utc": "2026-07-24T11:13:53Z",
                    "silver_tables": BAKED_43, "silver_tables_count": 43,
                    "silver_tables_fp": E0A33BF2["silver_tables_fp"]}


def _no_manifest():
    """What EVERY image in ECR today actually has: nothing."""
    return lambda: None


def _glue_present(created="2026-07-28T16:06:22Z"):
    return lambda t: {"state": "present", "database": "leviathan_dev", "created": created}


def _glue_absent():
    return lambda t: {"state": "absent", "database": "leviathan_dev", "created": None}


def _glue_error():
    def probe(t):
        raise RuntimeError("EndpointConnectionError: could not connect to glue")
    return probe


def _run_gate_main(tmp_path, capsys, monkeypatch, *, baked, manifest, probe, tables=ASKED):
    """Drive the REAL jobs.audit.silver_rebuild_gate.main() inside a simulated stale container.

    DELIBERATELY, NOTHING BELONGING TO THE FENCE IS STUBBED. The only things patched are the
    three seams that the PRE-fence code and the POST-fence code both go through:

      * ``leviathan.silver.registry.load_registry`` -- what the container has BAKED (43 tables,
        exactly commit e0a33bf2). Both ``image_stamp.preflight``'s default loader and the old
        ``_build_live_context`` resolve this at call time.
      * ``image_stamp.load_manifest`` / ``baked_silver_tables`` -- the container's provenance.
      * ``image_stamp.glue_probe`` -- the corroboration call, so no AWS is touched.

    That matters: strip the fence out of silver_rebuild_gate.py and main() still RUNS here, down
    the old BRANCH_UNKNOWN path, and prints the old sentence -- so the assertions below fail on
    their own merits rather than on a missing mock target.
    """
    from leviathan.silver import registry as sreg
    monkeypatch.setattr(sreg, "load_registry", lambda *a, **k: _Reg(baked))
    monkeypatch.setattr(image_stamp, "load_manifest", lambda *a, **k: manifest())
    monkeypatch.setattr(image_stamp, "baked_silver_tables",
                        lambda *a, **k: (list(baked), E0A33BF2["silver_tables_fp"]))
    monkeypatch.setattr(image_stamp, "glue_probe", probe)
    out = tmp_path / "bundle.json"
    rc = gate.main(["--tables", tables, "--asof", "2026-07-28T06:00:00Z", "--json", str(out)])
    return rc, capsys.readouterr().out, out


# ===========================================================================
# 1. THE INCIDENT REPLAY
# ===========================================================================
def test_incident_replay_e0a33bf2(tmp_path, capsys, monkeypatch):
    """Replay 2026-07-24 exactly: 43 baked tables, asked for silver_futures_eod, Glue HAS it.

    Deleting the preflight from main() leaves only the old
    ``dispatch=table not in the F010 silver registry`` line, which contains none of the strings
    asserted below -- so this test fails the moment the fence is reverted."""
    rc, out, bundle = _run_gate_main(tmp_path, capsys, monkeypatch, baked=BAKED_43,
                                     manifest=_manifest_e0a33bf2(), probe=_glue_present())

    # D-PR-8: the fence exit is EXIT_PREFLIGHT (71), NOT 1. Fail-closed is unchanged -- what changed is
    # that "the image is wrong" is no longer spelled the same way as "the gate refused the data".
    assert rc == gate.EXIT_PREFLIGHT, "the gate must still FAIL CLOSED -- canonical promote never runs"
    assert rc != gate.EXIT_REFUSAL, "an image fault must never be reported as a refusal (D-PR-8)"

    # It names the TABLE, the IMAGE COMMIT, the BAKED COUNT, the BUILD DATE and the REMEDY.
    for needle in ["silver_futures_eod", "e0a33bf2", "43", "2026-07-24", "rebuild", "repin"]:
        assert needle in out, "preflight output is missing %r:\n%s" % (needle, out)

    # It ranks the hypotheses instead of leaving the reader to guess.
    assert "THE CONFIG IS FINE" in out
    assert "IMAGE is stale" in out or "IMAGE IS STALE" in out
    # And it explicitly forbids the wrong fix -- the one the real RCA spent a week on.
    assert "Do NOT edit configs/silver/tables/silver_futures_eod.yaml" in out

    # The bundle records WHICH CONTAINER refused, which the 2026-07-24 bundles could not.
    b = json.loads(bundle.read_text(encoding="utf-8"))
    assert b["verdict"] == "FAIL"
    assert b["verdict_reason"] == "image_predates_config"
    assert b["image"]["git_commit"] == "e0a33bf2"
    assert b["image"]["silver_tables_count"] == 43
    assert b["banner"]["unknown"] == 1 and b["banner"]["red_tables"] == 1

    # ASCII-only (cp1252 console).
    out.encode("ascii")


def test_the_old_misleading_sentence_is_gone(tmp_path, capsys, monkeypatch):
    """The exact string that misdirected the RCA must never be emitted alone again."""
    _, out, _ = _run_gate_main(tmp_path, capsys, monkeypatch, baked=BAKED_43,
                               manifest=_manifest_e0a33bf2(), probe=_glue_present())
    assert "table not in the F010 silver registry" not in out


# ===========================================================================
# 2. ABSENCE IS EVIDENCE, NEVER SILENCE (the anti-I-2 property)
# ===========================================================================
def test_missing_manifest_is_stale_evidence_not_silence(tmp_path, capsys, monkeypatch):
    """No /app/IMAGE_MANIFEST.json -- i.e. every image in ECR right now.

    The fence must still FIRE. This is the direct inverse of incident I-2, where
    ``timeline._load``'s bare ``except Exception: _CACHE = {}`` turned a missing artifact into a
    silent green. Here a missing manifest degrades to "provenance UNKNOWN, treat as OLD" and the
    verdict is unchanged."""
    rc, out, bundle = _run_gate_main(tmp_path, capsys, monkeypatch, baked=BAKED_43,
                                     manifest=_no_manifest(), probe=_glue_present())
    assert rc == gate.EXIT_PREFLIGHT, "an unstamped image must NOT fail open"
    assert "manifest ABSENT" in out
    assert "treated as OLD" in out
    assert "silver_futures_eod" in out and "43" in out
    assert json.loads(bundle.read_text(encoding="utf-8"))["image"]["manifest_present"] is False


def test_banner_prints_on_the_happy_path_too(tmp_path, capsys, monkeypatch):
    """The provenance line is the cheap permanent record -- it must not be failure-only."""
    monkeypatch.setattr(image_stamp, "baked_silver_tables",
                        lambda *a, **k: (BAKED_43, E0A33BF2["silver_tables_fp"]))
    facts = image_stamp.image_facts(manifest_loader=_manifest_e0a33bf2())
    lines = image_stamp.banner("silver_rebuild_gate", facts)
    assert len(lines) == 1
    assert "commit=e0a33bf2" in lines[0]
    assert "configs/silver/tables=43" in lines[0]
    assert "age=" in lines[0]


# ===========================================================================
# 3. THE PROBE RANKS THE HYPOTHESES
# ===========================================================================
def test_glue_corroboration_ranks_the_hypotheses(tmp_path, capsys, monkeypatch):
    # (a) Glue HAS it -> the image is the fault.
    _, out_present, _ = _run_gate_main(tmp_path, capsys, monkeypatch, baked=BAKED_43,
                                       manifest=_manifest_e0a33bf2(), probe=_glue_present())
    assert "IMAGE is stale" in out_present

    # (b) Nobody has it, and it looks like a typo -> the ASK is the fault, not the image.
    rc, out_typo, _ = _run_gate_main(tmp_path, capsys, monkeypatch, baked=BAKED_43 + ["silver_futures_eod"],
                                     manifest=_manifest_e0a33bf2(), probe=_glue_absent(),
                                     tables="silver_futres_eod")
    assert rc == gate.EXIT_PREFLIGHT, "a typo'd ask must still fail closed"
    assert "suspect the ASK" in out_typo
    assert "did you mean silver_futures_eod" in out_typo

    # (c) Glue unreachable -> say so, and STILL fail closed. An unreachable probe must never be
    #     allowed to soften the verdict.
    rc_err, out_err, _ = _run_gate_main(tmp_path, capsys, monkeypatch, baked=BAKED_43,
                                        manifest=_manifest_e0a33bf2(), probe=_glue_error())
    assert rc_err == gate.EXIT_PREFLIGHT
    assert "could not corroborate" in out_err
    assert "EndpointConnectionError" in out_err


# ===========================================================================
# 4. THE OTHER HALF OF THE DISCRIMINATION
# ===========================================================================
def test_malformed_baked_yaml_says_config_not_image(tmp_path, capsys, monkeypatch):
    """A broken BAKED yaml is a CONFIG fault inside the image, not an age fault.

    The pre-fence code could not tell these apart: a RegistryError just tracebacked out of
    _build_live_context(). The fence must name the right one."""
    from leviathan.silver.registry import RegistryError

    def boom():
        raise RegistryError("silver_cot.yaml: schema: expected type ['string'], got int")

    pre = image_stamp.preflight([ASKED], registry_loader=boom,
                                manifest_loader=_manifest_e0a33bf2(),
                                probe=_glue_present(), tables_dir=None)
    text = "\n".join(pre["lines"])
    assert pre["ok"] is False
    assert pre["reason"] == "baked_registry_unloadable"
    assert "CONFIG PROBLEM IN THIS IMAGE" in text
    assert "NOT an image-age problem" in text
    assert "silver_cot.yaml" in text
    text.encode("ascii")


def test_main_renders_a_malformed_baked_registry_instead_of_tracebacking(tmp_path, capsys,
                                                                        monkeypatch):
    """End-to-end: a broken BAKED yaml must exit EXIT_PREFLIGHT with a NAMED cause, not a raw traceback.

    Before the fence, a RegistryError propagated uncaught out of _build_live_context() and the
    operator got a stack trace with no statement of what was wrong or what to do. D-PR-8 then moved
    this off exit 1: the yaml is broken INSIDE THE IMAGE, which is the same class as the preflight."""
    from leviathan.silver import registry as sreg

    def boom(*a, **k):
        raise sreg.RegistryError("silver_cot.yaml: schema: expected type ['string'], got int")

    monkeypatch.setattr(sreg, "load_registry", boom)
    monkeypatch.setattr(image_stamp, "load_manifest", lambda *a, **k: _manifest_e0a33bf2()())
    out = tmp_path / "b.json"
    rc = gate.main(["--tables", "silver_cot", "--asof", "2026-07-28", "--json", str(out)])
    text = capsys.readouterr().out
    assert rc == gate.EXIT_PREFLIGHT
    assert rc != gate.EXIT_REFUSAL
    assert "CONFIG PROBLEM IN THIS IMAGE" in text
    assert "silver_cot.yaml" in text
    assert "Traceback" not in text
    b = json.loads(out.read_text(encoding="utf-8"))
    assert b["verdict"] == "FAIL" and b["verdict_reason"] == "baked_registry_unloadable"


def test_preflight_default_path_does_not_parse_the_registry(monkeypatch):
    """COST GUARD. sreg.load_registry() is ~2.2s and _build_live_context() already pays it once.

    The preflight must decide from the baked FILENAMES (~40ms), never by parsing 45 yamls a second
    time. If someone reintroduces a registry load here, the gate's startup doubles and this fails.
    """
    from leviathan.silver import registry as sreg
    monkeypatch.setattr(sreg, "load_registry",
                        lambda *a, **k: pytest.fail("preflight parsed the registry -- that is a "
                                                    "second ~2.2s load per gate fire"))
    pre = image_stamp.preflight(["silver_cot"])
    assert pre["ok"] is True

    # ...and it is still correct: a table absent from the baked filenames still fires.
    bad = image_stamp.preflight([ASKED + "_nope"], probe=lambda t: {"state": "absent"})
    assert bad["ok"] is False and bad["reason"] == "image_predates_config"


# ===========================================================================
# 5. THE HAPPY PATH IS FREE
# ===========================================================================
def test_happy_path_makes_no_glue_call():
    """Every scheduled fire pays for this fence. It must cost ZERO AWS calls when all is well."""
    def never(table):
        raise AssertionError("glue_probe called on the happy path -- the fence is not free")

    pre = image_stamp.preflight(["silver_cot", "silver_psd"],
                                registry_loader=_registry_loader(["silver_cot", "silver_psd"]),
                                manifest_loader=_manifest_e0a33bf2(), probe=never)
    assert pre["ok"] is True and pre["reason"] == "ok" and pre["lines"] == []


def test_gate_module_import_is_aws_free():
    """jobs.audit.silver_rebuild_gate must stay importable with no boto3 client construction.

    The fence added an import to that module; if image_stamp ever pulls boto3 to module scope,
    the gate's AWS-free-at-import property (and every offline test that relies on it) breaks."""
    src = (_REPO_ROOT / "src" / "leviathan" / "common" / "image_stamp.py").read_text(encoding="utf-8")
    head = src.split("def glue_probe", 1)[0]
    assert "import boto3" not in head, "boto3 must be imported LAZILY inside glue_probe only"


# ===========================================================================
# 6. THE FINGERPRINT
# ===========================================================================
def test_fingerprint_is_content_sensitive(tmp_path):
    """Name-only fingerprinting would call an EDITED config identical.

    Between e0a33bf2 and 50a2ec3d, existing yamls were modified as well as added -- a name-set
    comparison alone would have reported those images as carrying the same configs."""
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        d.mkdir()
        (d / "silver_cot.yaml").write_text("table_name: silver_cot\n", encoding="utf-8")
        (d / "silver_psd.yaml").write_text("table_name: silver_psd\n", encoding="utf-8")
    names_a, fp_a = image_stamp.fingerprint_dir(a)
    names_b, fp_b = image_stamp.fingerprint_dir(b)
    assert names_a == names_b == ["silver_cot", "silver_psd"]
    assert fp_a == fp_b, "identical trees must fingerprint identically"

    (b / "silver_cot.yaml").write_text("table_name: silver_cot\nowner: x\n", encoding="utf-8")
    _, fp_b2 = image_stamp.fingerprint_dir(b)
    assert fp_b2 != fp_a, "an EDIT to an existing config must change the fingerprint"

    (b / "silver_new.yaml").write_text("table_name: silver_new\n", encoding="utf-8")
    names_b3, fp_b3 = image_stamp.fingerprint_dir(b)
    assert len(names_b3) == 3 and fp_b3 != fp_b2


def test_fingerprint_matches_the_live_tree():
    """The live baked list is computed from the container's OWN configs dir, not a manifest --
    that is what makes the fence work on images carrying no manifest at all."""
    from leviathan.silver import registry as sreg
    on_disk = sorted(p.stem for p in Path(sreg.TABLES_DIR).glob("*.yaml"))
    stems, fp = image_stamp.baked_silver_tables()
    assert stems == on_disk and len(stems) > 40
    assert fp.startswith("sha256:") and len(fp) == len("sha256:") + 16
    # The table the incident was about IS present in the current tree (the config was always fine).
    assert ASKED in stems


def test_e0a33bf2_fixture_is_the_real_incident_input():
    """Guard the fixture itself: 43 names, and silver_futures_eod deliberately absent."""
    assert len(BAKED_43) == 43 and len(set(BAKED_43)) == 43
    assert ASKED not in BAKED_43
    assert "silver_cot" in BAKED_43 and "gold_weather_z" in BAKED_43


# ===========================================================================
# 7. THE DOCKERFILE HALF
# ===========================================================================
# The two images that carry the fence (ARGs + the stamp RUN).
FENCED_DOCKERFILES = ["docker/leviathan_worker/Dockerfile",
                      "docker/leviathan_embedder/Dockerfile"]

# EVERY image in the repo, discovered rather than listed, so a new one is covered the day it lands.
ALL_DOCKERFILES = sorted(str(p.relative_to(_REPO_ROOT)).replace("\\", "/")
                         for p in (_REPO_ROOT / "docker").glob("*/Dockerfile"))

# The two build ARGs whose VALUE changes on every commit.
PROVENANCE_ARGS = ("BUILD_GIT_COMMIT", "BUILD_TIME")


def _parse_dockerfile(text):
    """[(start_line_index, folded_instruction_text)] -- backslash continuations folded into one.

    The index is the line the instruction STARTS on, which is the line an author actually moves
    when they hoist one. Folding matters: the worker's pip layer is
    ``RUN mkdir ... && \\`` / ``    pip install ...``, so a naive per-line scan would anchor the
    heavy layer to the CONTINUATION line and quietly tolerate an ARG wedged above the RUN.
    """
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        if not lines[i].strip() or lines[i].strip().startswith("#"):
            i += 1
            continue
        start, parts = i, []
        while i < len(lines):
            body = lines[i].strip()
            i += 1
            if body.startswith("#"):          # a comment INSIDE a continuation
                continue
            cont = body.endswith("\\")
            parts.append(body[:-1].strip() if cont else body)
            if not cont:
                break
        out.append((start, " ".join(p for p in parts if p)))
    return out


def _dockerfile_instructions(dockerfile):
    return _parse_dockerfile((_REPO_ROOT / dockerfile).read_text(encoding="utf-8"))


def _heavy_runs(instrs):
    """RUN layers whose cache key is worth hundreds of MB, identified STRUCTURALLY.

    ``pip install`` and ``playwright install`` are the two that dominate: 863 MB and 1.03 GB in
    the worker, the ~2 GB torch/[embed] layer in the embedder.
    """
    return [i for i, text in instrs
            if re.match(r"(?i)RUN\s", text)
            and ("pip install" in text or "playwright install" in text)]


def _provenance_args(instrs):
    """Indices of `ARG BUILD_GIT_COMMIT` / `ARG BUILD_TIME` declarations (with or without =default)."""
    out = []
    for i, text in instrs:
        m = re.match(r"(?i)ARG\s+(.*)$", text)
        if m and any(tok.split("=", 1)[0] in PROVENANCE_ARGS for tok in m.group(1).split()):
            out.append(i)
    return out


def _stamp_runs(instrs):
    return [i for i, text in instrs
            if "leviathan.common.image_stamp" in text and "--write" in text]


def _first_from(instrs):
    return next((i for i, text in instrs if re.match(r"(?i)FROM\s", text)), -1)


@pytest.mark.parametrize("dockerfile", FENCED_DOCKERFILES)
def test_provenance_args_stay_below_the_heavy_layers(dockerfile):
    """CACHE FENCE (2026-08-04). The ARGs must be SANDWICHED: below every heavy RUN, above the stamp.

    An ARG is in scope for every instruction that FOLLOWS it, and Docker keys a following RUN as
    though the arg were in that command's environment -- so BUILD_GIT_COMMIT, which is a new value
    on every commit, invalidates every heavy layer beneath it even though no command names it.
    Declared at the top of the file (the HEAD state) that cost a full pip + `playwright install`
    rebuild and a ~2 GB re-upload through the Docker Desktop proxy that breaks the pipe on GB PUTs.

    Both Dockerfiles carry a prose comment saying the ARGs "must never be hoisted back to the top
    of the file". A comment is not a fence. THIS is the fence: a hoist fails here.
    """
    instrs = _dockerfile_instructions(dockerfile)
    args, heavy, stamp = _provenance_args(instrs), _heavy_runs(instrs), _stamp_runs(instrs)

    assert args, "%s declares neither %s -- the fence is gone" % (dockerfile, " nor ".join(PROVENANCE_ARGS))
    assert heavy, "%s has no pip/playwright RUN -- the heavy-layer detector matched nothing" % dockerfile
    assert stamp, "%s does not stamp an IMAGE_MANIFEST" % dockerfile

    # Every heavy RUN is anchored to its own `RUN` line, never to a folded continuation.
    src = (_REPO_ROOT / dockerfile).read_text(encoding="utf-8").splitlines()
    for h in heavy:
        assert re.match(r"(?i)\s*RUN\s", src[h]), \
            "%s:%d is not a RUN line -- the continuation folding is wrong" % (dockerfile, h + 1)

    assert min(args) > max(heavy), (
        "%s declares a provenance ARG at line %d, ABOVE the heavy RUN at line %d. That ARG's value "
        "changes on every commit, so it re-keys that layer on every build and forces a ~2 GB "
        "re-upload. Move the ARG block back down, immediately above the image_stamp RUN."
        % (dockerfile, min(args) + 1, max(heavy) + 1))

    assert max(args) < min(stamp), (
        "%s declares a provenance ARG at line %d, BELOW the stamp RUN at line %d -- the stamp would "
        "read the unset value and the manifest would say 'unknown'."
        % (dockerfile, max(args) + 1, min(stamp) + 1))


@pytest.mark.parametrize("dockerfile", ALL_DOCKERFILES)
def test_no_image_declares_a_provenance_arg_above_a_heavy_layer(dockerfile):
    """The same rule, swept across EVERY image -- including the ones not fenced yet.

    leviathan_browser has the identical heavy pair (a pip layer and `playwright install --with-deps
    chromium`) and carries configs/ + sql/, so it is the next image someone will stamp. Whoever does
    that must not reach for the top of the file. Only in-stage ARGs are considered: a declaration
    above the first FROM is global scope and does not key a stage's layers.
    """
    instrs = _dockerfile_instructions(dockerfile)
    heavy = _heavy_runs(instrs)
    for a in [i for i in _provenance_args(instrs) if i > _first_from(instrs)]:
        below = [h for h in heavy if h > a]
        assert not below, (
            "%s:%d declares a provenance ARG above the heavy RUN at line %d -- see "
            "test_provenance_args_stay_below_the_heavy_layers for why that is a ~2 GB re-upload"
            % (dockerfile, a + 1, below[0] + 1))


def test_dockerfile_discovery_is_not_empty():
    """A glob that silently matches nothing turns the sweep above into a no-op."""
    assert set(FENCED_DOCKERFILES) <= set(ALL_DOCKERFILES)
    assert "docker/leviathan_browser/Dockerfile" in ALL_DOCKERFILES, \
        "the browser image (pip + playwright layers) dropped out of the sweep"
    assert len(ALL_DOCKERFILES) >= 3


def test_the_hoist_guard_is_not_vacuous():
    """Prove the assertion fires: replay the pre-fix shape and show the helpers see the violation.

    Without this, `min(args) > max(heavy)` could pass because the detectors match nothing.
    """
    hoisted = "\n".join([
        "FROM python:3.11-slim",
        "",
        "ARG BUILD_GIT_COMMIT=unknown",
        "ARG BUILD_TIME=unknown",
        "",
        "COPY pyproject.toml ./",
        "RUN mkdir -p src/leviathan && touch src/leviathan/__init__.py && \\",
        '    pip install --no-cache-dir -e ".[batch,biweekly,pg]"',
        "RUN playwright install --with-deps chromium",
        "COPY configs/ ./configs/",
        'RUN BUILD_GIT_COMMIT="$BUILD_GIT_COMMIT" \\',
        "    python -m leviathan.common.image_stamp --write /app/IMAGE_MANIFEST.json",
    ])
    instrs = _parse_dockerfile(hoisted)
    args, heavy, stamp = _provenance_args(instrs), _heavy_runs(instrs), _stamp_runs(instrs)
    assert args == [2, 3]
    assert heavy == [6, 8], "the folded pip RUN must anchor to line 7, not to its continuation"
    assert stamp == [10]
    assert min(args) < max(heavy), "the hoisted fixture must TRIP the fence"

    # ...and the same file with the ARG block moved down passes.
    fixed = "\n".join([
        "FROM python:3.11-slim",
        "COPY pyproject.toml ./",
        "RUN mkdir -p src/leviathan && \\",
        '    pip install --no-cache-dir -e "."',
        "RUN playwright install --with-deps chromium",
        "COPY configs/ ./configs/",
        "ARG BUILD_GIT_COMMIT=unknown",
        "ARG BUILD_TIME=unknown",
        'RUN BUILD_GIT_COMMIT="$BUILD_GIT_COMMIT" python -m leviathan.common.image_stamp --write /x',
    ])
    f = _parse_dockerfile(fixed)
    assert min(_provenance_args(f)) > max(_heavy_runs(f))
    assert max(_provenance_args(f)) < min(_stamp_runs(f))


def test_instruction_parser_skips_comments_and_blanks():
    """A comment BETWEEN the heavy RUN and the ARG block (both Dockerfiles have a 10-line one) must
    not shift either index, and a comment must never be mistaken for an instruction."""
    instrs = _parse_dockerfile("FROM x\n\n# ARG BUILD_GIT_COMMIT=hoisted-in-a-comment\nARG BUILD_TIME=unknown\n")
    assert [i for i, _ in instrs] == [0, 3]
    assert _provenance_args(instrs) == [3], "a commented-out ARG must not count as a declaration"


@pytest.mark.parametrize("dockerfile", FENCED_DOCKERFILES)
def test_dockerfiles_stamp_after_configs_copy(dockerfile):
    """The stamp RUN must exist AND come after `COPY configs/`.

    Stamping earlier would fingerprint an empty directory -- a manifest that LIES is worse than no
    manifest, because the auditor would trust it."""
    lines = (_REPO_ROOT / dockerfile).read_text(encoding="utf-8").splitlines()
    copy_idx = next(i for i, l in enumerate(lines) if l.strip().startswith("COPY configs/"))
    stamp_idx = next((i for i, l in enumerate(lines)
                      if "leviathan.common.image_stamp" in l and "--write" in l), None)
    assert stamp_idx is not None, "%s does not stamp an IMAGE_MANIFEST" % dockerfile
    assert stamp_idx > copy_idx, ("%s stamps at line %d BEFORE `COPY configs/` at line %d -- the "
                                  "manifest would fingerprint an empty dir"
                                  % (dockerfile, stamp_idx + 1, copy_idx + 1))
    text = "\n".join(lines)
    assert "ARG BUILD_GIT_COMMIT" in text, ".dockerignore excludes .git -- the commit MUST be an ARG"
    assert "ARG BUILD_TIME" in text


def test_dockerignore_still_excludes_git():
    """The premise of the ARG design. If .git ever became available in the build context this
    test tells you the simpler runtime `git rev-parse` is now possible."""
    di = (_REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert any(l.strip().rstrip("/") == ".git" for l in di)


# ===========================================================================
# 8. THE POWERSHELL HALF (a .ps1 is otherwise untested by pytest)
# ===========================================================================
@pytest.mark.parametrize("script", ["scripts/build_push_worker.ps1",
                                    "scripts/build_push_embedder.ps1"])
def test_build_scripts_assert_manifest(script):
    """Both build scripts must inject the provenance AND refuse to push an unstamped image.

    The two scripts drifting apart is exactly how half a fence ships."""
    text = (_REPO_ROOT / script).read_text(encoding="utf-8")
    assert "--build-arg" in text and "BUILD_GIT_COMMIT=" in text, \
        "%s does not inject the build commit" % script
    assert "rev-parse HEAD" in text
    assert "IMAGE_MANIFEST.json" in text, "%s does not verify the stamp" % script
    assert re.search(r"IMAGE_MANIFEST smoke FAILED", text), \
        "%s does not FAIL the build when the manifest is missing/wrong" % script
    assert "NOT pushing" in text
    # the host-vs-container fingerprint equality -- catches a stamp against the wrong tree
    assert "silver_tables_fp" in text and "host fp" in text
    assert "image_manifests/" in text, "%s does not publish the auditor's sidecar" % script


# ===========================================================================
# 9. THE FLEET AUDITOR (Tier C -- catches the class BEFORE the fire)
# ===========================================================================
def _auditor():
    sys.path.insert(0, str(_REPO_ROOT / "scripts" / "ops"))
    import importlib
    return importlib.import_module("check_ecr_pinned_digests")


def test_auditor_flags_asked_table_missing_from_baked_set(capsys):
    """The 2026-07-28 state of the world: the yaml is committed, the jobdef still pins the old
    digest, nothing has fired yet. The auditor must go RED four days before the gate log."""
    aud = _auditor()
    asks = {"leviathan-dev-silver-gate": {ASKED}}
    pins = {"leviathan-dev-silver-gate": ("digest", "leviathan-dev-leviathan-worker",
                                          "sha256:3590b188aaaaaaaa")}
    sidecars = {("leviathan-dev-leviathan-worker", "sha256:3590b188aaaaaaaa"):
                {"git_commit": "e0a33bf2", "build_time_utc": "2026-07-24T11:13:53Z",
                 "silver_tables": BAKED_43, "silver_tables_fp": E0A33BF2["silver_tables_fp"]}}
    rc = aud.run_config_drift(asks, pins, lambda r, d: sidecars.get((r, d)),
                              set(BAKED_43) | {ASKED}, "sha256:deadbeefdeadbeef")
    out = capsys.readouterr().out
    assert rc == 1
    assert "IMAGE-PREDATES-CONFIG" in out
    assert "leviathan-dev-silver-gate" in out and ASKED in out
    assert "e0a33bf2" in out and "rebuild + repin" in out
    out.encode("ascii")


def test_auditor_flags_digest_without_sidecar(capsys):
    """No sidecar == cannot PROVE the image is current == treat as stale. Unknown provenance
    must never read as OK -- that is the I-2 fail-open shape."""
    aud = _auditor()
    rc = aud.run_config_drift({"leviathan-dev-b3-flat-silver": {"silver_cot"}},
                              {"leviathan-dev-b3-flat-silver": ("digest", "repo", "sha256:beef")},
                              lambda r, d: None, {"silver_cot"}, "sha256:1111111111111111")
    out = capsys.readouterr().out
    assert rc == 1
    assert "UNKNOWN-PROVENANCE" in out and "leviathan-dev-b3-flat-silver" in out


def test_auditor_content_drift_is_yellow_not_red(capsys):
    """Scoping IS the design. A blanket fingerprint!=HEAD rule fires on ~33 jobdefs on every
    config commit; a fence that always fires gets muted."""
    aud = _auditor()
    sidecar = {"git_commit": "50a2ec3d", "build_time_utc": "2026-07-29T00:00:00Z",
               "silver_tables": ["silver_cot"], "silver_tables_fp": "sha256:aaaaaaaaaaaaaaaa"}
    rc = aud.run_config_drift({"jd": {"silver_cot"}}, {"jd": ("digest", "repo", "sha256:x")},
                              lambda r, d: sidecar, {"silver_cot"}, "sha256:bbbbbbbbbbbbbbbb")
    out = capsys.readouterr().out
    assert rc == 0, "content-only drift must NOT gate"
    assert "CONTENT-DRIFT" in out and "YELLOW" in out
    assert "RED" not in out


def test_auditor_tag_pinned_is_reported_not_audited(capsys):
    """~30 families are :latest tag-pinned. They never go stale but they move without a jobdef
    change -- report them, do not pretend to have audited them."""
    aud = _auditor()
    rc = aud.run_config_drift({"jd": {"silver_cot"}}, {"jd": ("tag", "acct.dkr.ecr/x:latest")},
                              lambda r, d: pytest.fail("must not fetch a sidecar for a tag pin"),
                              {"silver_cot"}, "sha256:1111111111111111")
    out = capsys.readouterr().out
    assert rc == 0 and "TAG-PINNED" in out


def test_auditor_derives_the_real_ask_from_the_scheduler_authority():
    """The ask must come from the SAME file the scheduler uses, not a hand-maintained list.

    This is what makes the auditor self-updating: a new gated family is covered the moment its
    tfvars entry is applied."""
    aud = _auditor()
    asks = aud.parse_dag_asks()
    assert "leviathan-dev-silver-gate" in asks, \
        "no gate ask derived from dag_schedules.auto.tfvars.json"
    assert ASKED in asks["leviathan-dev-silver-gate"], \
        "the incident's own table is not in the derived ask -- the parser missed it"
    assert len(asks["leviathan-dev-silver-gate"]) > 5

    # The TRANSFORM jobdefs read the same configs/silver/tables/<table>.yaml contract, so they
    # carry the identical trap. leviathan-dev-b3-flat-silver rev23 is still pinned to
    # sha256:3590b188 -- the exact digest that caused I-1 (measured 2026-07-31 via
    # describe-job-definitions). Its 31 asked tables all happen to exist at e0a33bf2, so today it
    # is YELLOW content-drift rather than RED; that is precisely why it must be IN SCOPE, because
    # nothing warns you the day one of those 31 configs gains a new sibling.
    assert "leviathan-dev-b3-flat-silver" in asks, \
        "phase/promote jobdefs are not audited -- b3-flat-silver (the I-1 digest) is invisible"
    assert len(asks["leviathan-dev-b3-flat-silver"]) > 10
    assert len(asks) > 20, "only %d jobdefs audited -- the fleet sweep is too narrow" % len(asks)


# ===========================================================================
# 10. THE ONE-LINE FORM, reachable without main()
# ===========================================================================
def test_dispatch_detail_never_blames_the_config_alone():
    """run_table() is reachable without main()'s preflight (any in-process caller). Its one-line
    detail must carry the same honesty."""
    facts = image_stamp.image_facts(manifest_loader=_manifest_e0a33bf2())
    line = image_stamp.dispatch_detail(ASKED, baked=BAKED_43, facts=facts)
    assert "BAKED INTO THIS CONTAINER" in line
    assert "e0a33bf2" in line and "43" in line
    assert "THE IMAGE IS STALE" in line
    assert "do NOT edit configs/silver/tables/%s.yaml" % ASKED in line
    line.encode("ascii")


def test_run_table_unknown_branch_uses_the_honest_detail(monkeypatch):
    monkeypatch.setattr(image_stamp, "load_manifest", lambda *a, **k: _manifest_e0a33bf2()())
    monkeypatch.setattr(image_stamp, "baked_silver_tables",
                        lambda *a, **k: (BAKED_43, E0A33BF2["silver_tables_fp"]))
    ctx = gate.GateContext(numbers_reg=None, silver_reg=_Reg(BAKED_43))
    res = gate.run_table(ASKED, ctx)
    assert res.branch == gate.BRANCH_UNKNOWN and res.ok is False
    detail = res.stages[0].detail
    assert "table not in the F010 silver registry" not in detail
    assert "BAKED INTO THIS CONTAINER" in detail and "e0a33bf2" in detail
