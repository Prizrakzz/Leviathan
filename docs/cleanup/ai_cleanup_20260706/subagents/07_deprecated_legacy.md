# Phase 2 Subagent 07 - Deprecated, Legacy, And Fallback Code

## Scope

Read-only research on deprecated, legacy, fallback, stale, and compatibility paths. GraphRAG and AI-agent files were excluded from cleanup findings.

No code edits, deletes, AWS calls, S3 mutations, Terraform applies, or formatting tools were run.

## Critical Assessment

Most "legacy" keyword hits are not stale. This project ingests historical commodity data, so older source layouts and compatibility code are often necessary. The cleanup target should be stale operational residue and broken reproduction instructions, not historical parsers.

## High Confidence Stale Findings

### Broken GAIN manifest-generation references

There are many references to missing `scratch/gain/*` scripts. `scratch/gain/` does not exist.

Examples:

- `jobs/ingest/fetch_gain.py`
- `jobs/ingest/fetch_gain_coffee.py`
- `configs/sources/usda_gain_*.yaml`

Risk: future operators cannot reproduce GAIN manifest generation from checked-in instructions.

### One-off GAIN migration and retry scripts are dangerous to keep as normal code

Examples:

- `scratch/submit_gain_rekey.py`
- `scratch/retry_gain_oom.py`
- `scratch/cleanup_gain_flat_keys.py`

Some submit Batch jobs or delete S3 keys.

Risk: accidental spend or destructive S3 cleanup if run without context.

### Tracked generated artifacts and logs should not live as normal source

Examples:

- tracked `logs/*.log`
- root `glue_log*.txt`
- `pytest_*`
- `mypy_phase2.txt`
- `tf_apply.txt`
- tracked Terraform plans under `infra/terraform/envs/dev/tfplan*`

Risk: noisy diffs, stale operational evidence, and accidental publishing of local state.

### Stale usage text in delete utility

`jobs/utils/delete_s3_prefix.py` documents `jobs/purge_s3_prefix.py`, which does not exist. The actual file is `jobs/utils/delete_s3_prefix.py`.

Risk: operator confusion around a destructive utility.

## Not Stale Despite Keywords

Keep these unless a later owner approves a specific removal:

- model dataset legacy controls in `configs/ml/model_dataset_versions.yaml`;
- WAP legacy EU exclusion;
- UNICA old-format PDF handling;
- MPOB legacy annual layout handling;
- FGIS legacy date columns;
- SAGIS old `.doc` and `.xls` support;
- World Bank Wayback fallback;
- frontend legacy-turn rendering in answer views;
- S3/Glue/Batch operational utilities.

## Recommended Phase 3 Edits

1. Update or remove stale `scratch/gain/*` generation instructions, or restore the missing helper scripts in a proper `jobs/` or `scripts/` location.
2. Move one-off GAIN migration scripts into a clearly labeled archive or delete them after manual approval.
3. Untrack/relocate generated logs and Terraform plan files after deciding what evidence must be preserved.
4. Fix the usage string in `jobs/utils/delete_s3_prefix.py`.
5. Add `.gitignore` coverage for future run artifacts if missing.

## Manual Approval Required

- Any S3 cleanup script changes.
- Any deletion of scratch scripts.
- Any SQL DDL, Terraform, Batch, or Glue utility retirement.

## Validation

- `rg "scratch/gain/" configs/sources jobs/ingest`
- `git ls-files logs scratch infra/terraform/envs/dev/tfplan*`
- Metadata-only Glue drift checker before any DDL retirement.
- Targeted tests for any ingestion workflow whose instructions change.

