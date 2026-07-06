# Phase 2 Subagent 08 - AI Slop, Stubs, And Comments

## Scope

Read-only assessment of vacuous tests, AI-generated residue, stale implementation breadcrumbs, and low-value comments. GraphRAG and AI-agent paths were excluded from cleanup recommendations.

No code edits, deletes, AWS calls, S3 mutations, Terraform applies, or formatting tools were run.

## Critical Assessment

The most important issues are not comments. They are two vacuous tests and source manifests containing `chatgpt.com` tracking query parameters. After those are fixed, comment cleanup should be narrow and not churn working UI code.

## High Confidence Findings

### Vacuous test assertions

The following tests contain assertions made true with `or True`:

- `tests/unit/test_storage_metadata.py`
- `tests/unit/test_nasa_power_ingestion.py`

Risk: tests look meaningful while accepting broken behavior.

Recommended fix: replace with real assertions or rename/remove as explicit no-exception smoke tests.

### Source manifest URLs contain ChatGPT tracking parameters

`configs/sources/unica_biweekly_manifest.yaml` includes URLs with:

- `utm_source=chatgpt.com`

Risk: unprofessional source metadata and possible duplicate-key confusion.

Recommended fix: strip tracking parameters after confirming bare URLs still resolve or are equivalent.

## Medium Confidence Findings

### No-op ICCO branch

`jobs/ingest/fetch_icco_qbcs_summary.py` contains an `if is_signed: pass` branch. The surrounding signed-row concept may be meaningful, but the branch and variable appear unused.

Recommended fix: remove the no-op branch while keeping any useful surplus/deficit mapping comment.

### Frontend phase breadcrumbs

The frontend contains phase/status comments such as:

- `5.6 W4`
- `Phase 6.2`
- `pre-5.6`
- `ChatGPT-style`

Risk: comments describe project history rather than current behavior.

Recommended fix: remove narrow breadcrumbs where they do not explain runtime behavior.

## Low Confidence Findings

`tests/unit/test_transforms_wasde_bronze.py` contains language like "Just check no crash". This may be acceptable for a parser smoke test but should be renamed if the test promises stronger behavior.

## Recommended Phase 3 Edits

1. Fix vacuous `or True` tests first.
2. Strip `utm_source=chatgpt.com` from UNICA manifest URLs after URL equivalence check.
3. Remove the ICCO no-op branch if parser tests pass.
4. Run a narrow frontend comment cleanup pass only on non-GraphRAG UI files.

## Validation

- `python -m pytest tests/unit/test_storage_metadata.py tests/unit/test_nasa_power_ingestion.py`
- Targeted ICCO parser tests if the ICCO file is touched.
- `rg "chatgpt\\.com|or True|always pass|ChatGPT-style|pre-5\\.6|Phase 6|5\\.6 W"`.
- Frontend `npm run lint && npm run test` if UI comments/code are touched.

