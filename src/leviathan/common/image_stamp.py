"""IMAGE-AGE PREFLIGHT -- the fence for incident I-1 (stale image vs newer config).

THE INCIDENT. Batch jobdef ``leviathan-dev-silver-gate`` was pinned to image digest
``sha256:3590b188``, built from commit ``e0a33bf2`` which carried 43 files in
``configs/silver/tables/``. ``configs/silver/tables/silver_futures_eod.yaml`` landed 2026-07-28,
AFTER that image. The scheduled gate was then asked to gate ``silver_futures_eod``, could not
classify it, and printed::

    FAIL silver_futures_eod (branch unknown): dispatch=table not in the F010 silver registry

That sentence names the REGISTRY, so every reader opened
``configs/silver/tables/silver_futures_eod.yaml``, found it present and valid, and concluded the
CONFIG was broken. The real cause was that the CONTAINER's baked copy of that directory predated
the file. Cost: hours of misdiagnosis, an 11-agent RCA, and a week of skipped canonical promotes.

THE TRIGGER (and what it deliberately is NOT). The fence fires on a SEMANTIC MISMATCH: "a table I
am ASKED to gate is absent from the F010 registry BAKED INTO ME". It does NOT fire on image age --
16 jobdef families currently run a 2026-07-23 image and are entirely correct because nothing they
read changed. Age is EVIDENCE printed alongside, never the trigger. A fence that cries wolf gets
muted, and a muted fence is worse than none.

WHY THE BAKED LIST IS LIVE-COMPUTED. :func:`baked_silver_tables` always hashes the container's OWN
``configs/silver/tables/`` (``leviathan.silver.registry.TABLES_DIR``) rather than trusting a
manifest. That is load-bearing: the fence works on an image that carries NO manifest at all, which
is every image built before this module existed. The manifest (:func:`load_manifest`) is ADDITIVE
-- it supplies the one fact the RCA actually needed, the build commit and time.

ABSENCE IS EVIDENCE, NEVER SILENCE. A missing ``/app/IMAGE_MANIFEST.json`` degrades to "provenance
UNKNOWN, treat the baked configs as OLD" and the preflight STILL fails closed on a mismatch. This
is the direct anti-pattern of incident I-2 (``timeline._load``'s bare ``except -> _CACHE = {}``,
which turned a missing artifact into a silent green).

STDLIB + ASCII ONLY at import time. ``boto3`` is imported lazily inside :func:`glue_probe`, which
runs ONLY on the already-failing path, so the AWS-free-at-import property the gate relies on
(``jobs/audit/silver_rebuild_gate.py`` imports no AWS at module load) is preserved.

CLI (build time)::

    python -m leviathan.common.image_stamp --write /app/IMAGE_MANIFEST.json
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

# ---------------------------------------------------------------------------
# Manifest location + schema
# ---------------------------------------------------------------------------
MANIFEST_PATH = "/app/IMAGE_MANIFEST.json"
MANIFEST_ENV = "LEVIATHAN_IMAGE_MANIFEST"
MANIFEST_SCHEMA = 1

UNKNOWN = "unknown"

# The S3 sidecar the fleet auditor (scripts/ops/check_ecr_pinned_digests.py --config-drift) reads.
# Written after push, keyed by the pushed digest, so provenance is auditable WITHOUT pulling layers.
SIDECAR_BUCKET = "leviathan-dev-shahem-001"
SIDECAR_PREFIX = "image_manifests"


def sidecar_key(repo: str, digest: str) -> str:
    """S3 key of the manifest sidecar for one pushed image digest."""
    return "%s/%s/%s.json" % (SIDECAR_PREFIX, repo, digest.replace(":", "_"))


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------
def fingerprint_dir(directory, pattern: str = "*.yaml") -> tuple[list[str], str]:
    """Return ``(sorted_stems, "sha256:<16 hex>")`` for every ``pattern`` file in ``directory``.

    CONTENT-sensitive, not just name-sensitive: the digest covers each file's bytes, so an EDIT to
    an already-present config changes the fingerprint too. Between e0a33bf2 and 50a2ec3d five
    existing yamls were modified as well as two added -- a name-only fingerprint would have called
    those images identical. Order-insensitive (stems are sorted) so it does not depend on the
    filesystem's directory order.
    """
    d = Path(directory)
    stems: list[str] = []
    parts: list[str] = []
    if d.is_dir():
        for p in sorted(d.glob(pattern), key=lambda x: x.name):
            if not p.is_file():
                continue
            stems.append(p.stem)
            parts.append(p.stem + " " + hashlib.sha256(p.read_bytes()).hexdigest())
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    return stems, "sha256:" + digest


def silver_tables_dir() -> Path:
    """The container's OWN configs/silver/tables/ -- the ground truth for "what I was built with"."""
    from leviathan.silver import registry as sreg
    return Path(sreg.TABLES_DIR)


def baked_silver_tables(tables_dir=None) -> tuple[list[str], str]:
    """Live-computed ``(table names, fingerprint)`` of the silver contracts baked into THIS image."""
    return fingerprint_dir(tables_dir if tables_dir is not None else silver_tables_dir())


def configs_fingerprint(root=None) -> str:
    """Coarse fingerprint of the whole configs/silver tree (schema + known_drift + tables)."""
    from leviathan.silver import registry as sreg
    base = Path(root) if root is not None else Path(sreg.CONFIGS_SILVER_DIR)
    _, tables_fp = fingerprint_dir(base / "tables")
    _, top_fp = fingerprint_dir(base, "*.json")
    _, drift_fp = fingerprint_dir(base, "*.yaml")
    joined = "|".join([tables_fp, top_fp, drift_fp]).encode("utf-8")
    return "sha256:" + hashlib.sha256(joined).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Manifest read / write
# ---------------------------------------------------------------------------
def manifest_path() -> str:
    return os.environ.get(MANIFEST_ENV) or MANIFEST_PATH


def load_manifest(path=None) -> Optional[dict]:
    """Read ``/app/IMAGE_MANIFEST.json`` (or ``$LEVIATHAN_IMAGE_MANIFEST``). None when absent or
    unreadable -- callers MUST treat None as "provenance unknown", never as "fine"."""
    p = Path(path if path is not None else manifest_path())
    try:
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- a corrupt manifest is UNKNOWN provenance, not a crash
        return None
    return data if isinstance(data, dict) else None


def build_manifest(git_commit: Optional[str] = None, build_time: Optional[str] = None,
                   tables_dir=None) -> dict:
    stems, fp = baked_silver_tables(tables_dir)
    commit = (git_commit or os.environ.get("BUILD_GIT_COMMIT") or UNKNOWN).strip() or UNKNOWN
    when = (build_time or os.environ.get("BUILD_TIME") or "").strip()
    if not when:
        when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        configs_fp = configs_fingerprint()
    except Exception:  # noqa: BLE001
        configs_fp = UNKNOWN
    return {
        "schema": MANIFEST_SCHEMA,
        "git_commit": commit[:40],
        "build_time_utc": when,
        "silver_tables": stems,
        "silver_tables_count": len(stems),
        "silver_tables_fp": fp,
        "configs_fp": configs_fp,
    }


def write_manifest(dest, git_commit: Optional[str] = None, build_time: Optional[str] = None,
                   tables_dir=None) -> dict:
    m = build_manifest(git_commit, build_time, tables_dir)
    p = Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(m, indent=1, sort_keys=True), encoding="utf-8")
    return m


# ---------------------------------------------------------------------------
# Image facts (manifest + live fingerprint + age)
# ---------------------------------------------------------------------------
def _age_days(build_time: str, now: Optional[datetime] = None) -> Optional[float]:
    try:
        t = datetime.strptime(build_time[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None
    ref = now or datetime.now(timezone.utc)
    return round((ref - t).total_seconds() / 86400.0, 1)


def image_facts(*, manifest_loader: Optional[Callable] = None, tables_dir=None,
                now: Optional[datetime] = None) -> dict:
    """Everything this container can say about its own provenance. Never raises."""
    loader = manifest_loader or load_manifest
    try:
        m = loader()
    except Exception:  # noqa: BLE001
        m = None
    try:
        stems, fp = baked_silver_tables(tables_dir)
    except Exception:  # noqa: BLE001
        stems, fp = [], UNKNOWN
    build_time = str((m or {}).get("build_time_utc") or UNKNOWN)
    return {
        "manifest_present": m is not None,
        "git_commit": str((m or {}).get("git_commit") or UNKNOWN),
        "build_time_utc": build_time,
        "age_days": _age_days(build_time, now) if m else None,
        "silver_tables": stems,
        "silver_tables_count": len(stems),
        "silver_tables_fp": fp,
        "manifest_silver_tables_fp": str((m or {}).get("silver_tables_fp") or UNKNOWN),
    }


def banner(component: str, facts: Optional[dict] = None) -> list[str]:
    """Two ASCII lines stating what this container is, printed on EVERY run (pass or fail).

    On the happy path this is the cheap, permanent record that makes the next RCA one line long.
    """
    f = facts if facts is not None else image_facts()
    if f["manifest_present"]:
        age = "unknown" if f["age_days"] is None else ("%.1fd" % f["age_days"])
        return ["%s IMAGE: commit=%s built=%s age=%s configs/silver/tables=%d fp=%s"
                % (component, f["git_commit"], f["build_time_utc"], age,
                   f["silver_tables_count"], f["silver_tables_fp"])]
    return [
        "%s IMAGE: manifest ABSENT -- no %s in this container." % (component, manifest_path()),
        "    This image was built before the image-stamp fence, so its commit and build time are "
        "UNKNOWN and",
        "    its baked configs must be treated as OLD. live-computed configs/silver/tables=%d fp=%s"
        % (f["silver_tables_count"], f["silver_tables_fp"]),
    ]


# ---------------------------------------------------------------------------
# Glue corroboration (FAILURE PATH ONLY -- never called on the happy path)
# ---------------------------------------------------------------------------
def glue_probe(table: str, database: Optional[str] = None) -> dict:
    """Ask Glue whether the platform HAS this table. Ranks the two hypotheses:

      present -> the platform has it and this container does not  => THE IMAGE IS STALE
      absent  -> nobody has it                                    => the ASK is wrong (typo/unregistered)
      error   -> could not corroborate                            => image age is the only evidence

    Hard-bounded (connect 3s / read 5s / 1 attempt) so the fence can never hang a fire. The
    permission already exists: glue:GetTable at infra/terraform/modules/iam/main.tf:337
    (athena_validation policy, attached to the batch job role at :367). NO infra change needed.
    """
    db = database or os.environ.get("GLUE_DATABASE") or "leviathan_dev"
    try:
        import boto3
        from botocore.config import Config
        cfg = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1})
        client = boto3.client("glue", config=cfg)
        resp = client.get_table(DatabaseName=db, Name=table)
        created = resp.get("Table", {}).get("CreateTime")
        return {"state": "present", "database": db,
                "created": created.strftime("%Y-%m-%dT%H:%M:%SZ") if hasattr(created, "strftime")
                else str(created or UNKNOWN)}
    except Exception as e:  # noqa: BLE001
        name = type(e).__name__
        if "EntityNotFound" in name:
            return {"state": "absent", "database": db, "created": None}
        return {"state": "error", "database": db, "created": None,
                "error": "%s: %s" % (name, str(e)[:120])}


def close_matches(table: str, baked: Sequence[str]) -> list[str]:
    return difflib.get_close_matches(table, list(baked), n=2, cutoff=0.75)


# ---------------------------------------------------------------------------
# The verdict text
# ---------------------------------------------------------------------------
REMEDY_BUILD = "powershell scripts/build_push_worker.ps1 -Tag <datestamp>"
REMEDY_REPIN = ("then repin leviathan-dev-silver-gate (and leviathan-dev-b3-flat-silver, same "
                "digest family) to the new sha256 and re-register the jobdef.")


def dispatch_detail(table: str, *, baked: Optional[Sequence[str]] = None,
                    facts: Optional[dict] = None) -> str:
    """The ONE-LINE honest replacement for "table not in the F010 silver registry".

    The word "registry" never stands alone here: the sentence names the IMAGE, its provenance, and
    the remedy, so a reader cannot walk away believing the config file is at fault.
    """
    f = facts if facts is not None else image_facts()
    names = list(baked if baked is not None else f["silver_tables"])
    prov = ("image commit %s built %s" % (f["git_commit"], f["build_time_utc"])
            if f["manifest_present"] else "image provenance UNKNOWN (no manifest)")
    return ("%s is NOT among the %d silver table configs BAKED INTO THIS CONTAINER (%s). "
            "If the platform has this table, the CONFIG IS FINE -- THE IMAGE IS STALE: "
            "rebuild and repin the jobdef; do NOT edit configs/silver/tables/%s.yaml"
            % (table, len(names), prov, table))


def explain_missing(missing: Sequence[str], *, baked: Sequence[str], facts: dict,
                    probes: Optional[dict] = None, asked: int = 0) -> list[str]:
    """The multi-line preflight verdict. ASCII only."""
    probes = probes or {}
    names = list(baked)
    n_ask = asked or len(missing)
    out = ["FAIL silver_rebuild_gate PREFLIGHT (image-vs-config): %d of %d asked table(s) ABSENT "
           "from the F010 registry BAKED INTO THIS CONTAINER." % (len(missing), n_ask)]
    for t in missing:
        out.append("  %s -- not among the %d baked table configs." % (t, len(names)))
        pr = probes.get(t) or {}
        state = pr.get("state")
        if state == "present":
            out.append("    CORROBORATION: Glue %s DOES have %s (CreateTime %s)."
                       % (pr.get("database", UNKNOWN), t, pr.get("created", UNKNOWN)))
            out.append("    The platform has this table; this container does not. "
                       "THE CONFIG IS FINE -- THE IMAGE is stale.")
            if facts.get("manifest_present"):
                out.append("    This image was built from commit %s at %s (age %s days)."
                           % (facts["git_commit"], facts["build_time_utc"],
                              facts["age_days"] if facts["age_days"] is not None else UNKNOWN))
        elif state == "absent":
            out.append("    CORROBORATION: Glue %s does NOT have %s either -- suspect the ASK, "
                       "not the image." % (pr.get("database", UNKNOWN), t))
            cm = close_matches(t, names)
            if cm:
                out.append("    did you mean %s ?" % " or ".join(cm))
        else:
            out.append("    could not corroborate via Glue (%s); image age is the only evidence."
                       % (pr.get("error", "probe not run")))
        out.append("    REMEDY: rebuild and repin. Do NOT edit configs/silver/tables/%s.yaml" % t)
        out.append("      " + REMEDY_BUILD)
        out.append("      " + REMEDY_REPIN)
    shown = ", ".join(names[:8])
    out.append("  baked tables (%d): %s%s"
               % (len(names), shown, ", ..." if len(names) > 8 else ""))
    return out


def explain_bad_registry(err: str, *, facts: dict) -> list[str]:
    """The OTHER half of the discrimination the old code could not make.

    A malformed BAKED yaml is a CONFIG problem inside this image, not an age problem. Today this
    raises an uncaught traceback out of ``_build_live_context`` (silver_rebuild_gate.py:407); here
    it is a named, ASCII, fail-closed verdict."""
    return [
        "FAIL silver_rebuild_gate PREFLIGHT: CONFIG PROBLEM IN THIS IMAGE -- the baked F010 "
        "registry does not load.",
        "  This is NOT an image-age problem: the container's own configs/silver/tables/ "
        "(%d file(s), fp %s) is malformed." % (facts["silver_tables_count"],
                                               facts["silver_tables_fp"]),
        "  " + str(err)[:400].replace("\n", " | "),
        "  REMEDY: fix the offending configs/silver/tables/*.yaml, then rebuild + repin.",
    ]


# ---------------------------------------------------------------------------
# The preflight itself
# ---------------------------------------------------------------------------
def preflight(tables: Sequence[str], *, registry_loader: Optional[Callable] = None,
              manifest_loader: Optional[Callable] = None, probe: Optional[Callable] = None,
              tables_dir=None, now: Optional[datetime] = None) -> dict:
    """Decide, at the EARLIEST possible moment, whether this container can honour this ask.

    Returns ``{"ok", "reason", "lines", "red_tables", "image"}``. Never raises. ``probe`` is
    invoked ONLY for tables that are already missing, so the happy path makes ZERO AWS calls.
    """
    facts = image_facts(manifest_loader=manifest_loader, tables_dir=tables_dir, now=now)
    result = {"ok": True, "reason": "ok", "lines": [], "red_tables": [], "image": facts}

    # COST. The default path does NOT parse or validate the registry: the baked NAME set is the
    # set of yaml stems, already computed for the banner (~40 ms for 45 files). A full
    # sreg.load_registry() is ~2.2 s -- and silver_rebuild_gate._build_live_context() performs one
    # anyway a few lines later, so parsing here would have DOUBLED the gate's startup for a fact
    # the filenames already carry. registry.load_registry() lints stem == table_name, so for any
    # registry that loads at all the two sets are identical; for one that does NOT load, the
    # RegistryError surfaces at _build_live_context and main() renders it as the CONFIG verdict.
    #
    # ``registry_loader`` remains injectable: tests use it, and it is what proves the
    # malformed-baked-yaml branch below still discriminates.
    loader = registry_loader
    if loader is None and facts["silver_tables"]:
        known = set(facts["silver_tables"])
    else:
        if loader is None:
            # No stems at all -- the image may not carry configs/silver/tables/ whatsoever. Do not
            # guess: pay for the real load rather than red-flagging every table on an empty list.
            def loader():
                from leviathan.silver import registry as sreg
                return sreg.load_registry()
        try:
            reg = loader()
            known = set(getattr(reg, "tables", {}) or {})
        except Exception as e:  # noqa: BLE001 -- malformed BAKED config, NOT an age problem
            result["ok"] = False
            result["reason"] = "baked_registry_unloadable"
            result["lines"] = explain_bad_registry("%s: %s" % (type(e).__name__, e), facts=facts)
            result["red_tables"] = [(t, "baked F010 registry in this image does not load: %s: %s"
                                     % (type(e).__name__, str(e)[:160])) for t in tables]
            return result

    missing = [t for t in tables if t not in known]
    if not missing:
        return result

    probe_fn = probe or glue_probe
    probes = {}
    for t in missing:
        try:
            probes[t] = probe_fn(t)
        except Exception as e:  # noqa: BLE001 -- an unreachable Glue must not mask the verdict
            probes[t] = {"state": "error", "error": "%s: %s" % (type(e).__name__, str(e)[:120])}
    baked = facts["silver_tables"] or sorted(known)
    result["ok"] = False
    result["reason"] = "image_predates_config"
    result["lines"] = explain_missing(missing, baked=baked, facts=facts, probes=probes,
                                      asked=len(tables))
    result["red_tables"] = [(t, dispatch_detail(t, baked=baked, facts=facts)) for t in missing]
    result["probes"] = probes
    return result


# ---------------------------------------------------------------------------
# CLI (build time)
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="write/show the image provenance manifest")
    ap.add_argument("--write", default=None, help="destination path for IMAGE_MANIFEST.json")
    ap.add_argument("--commit", default=None, help="git commit (default $BUILD_GIT_COMMIT)")
    ap.add_argument("--build-time", default=None, help="ISO8601Z (default $BUILD_TIME or now)")
    a = ap.parse_args(argv)
    m = write_manifest(a.write, a.commit, a.build_time) if a.write \
        else build_manifest(a.commit, a.build_time)
    print("image_stamp commit=%s built=%s silver_tables=%d fp=%s"
          % (m["git_commit"], m["build_time_utc"], m["silver_tables_count"], m["silver_tables_fp"]))
    if a.write:
        print("image_stamp wrote %s" % a.write)
    return 0


if __name__ == "__main__":
    sys.exit(main())
