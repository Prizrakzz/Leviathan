# Phase 2 Subagent 05 - Weak Types

## Scope

Read-only assessment of weak or broad typing patterns. GraphRAG and AI-agent files were excluded from cleanup recommendations.

No code edits, deletes, AWS calls, S3 mutations, Terraform applies, or formatting tools were run.

## Critical Assessment

Weak typing is most risky at boundaries:

- frontend API/SSE payload parsing;
- ML model-ready manifests and certification reports;
- AWS/Athena/S3 row handling;
- YAML config loading.

The right fix is not to remove every `Any` or `unknown`. At external boundaries, `unknown` is correct until it is narrowed. The cleanup should replace unsafe casts and unstructured dict payloads with explicit runtime validation and stable internal types.

## High Confidence Findings

### Frontend JSON and SSE casts are too trusting

Examples:

- `apps/terminal/src/api/client.ts` casts `res.json()` as generic `T`.
- `apps/terminal/src/api/sse.ts` parses JSON and then casts downstream.
- Downstream casts appear in numbers, note, receipts, and related view code.

Risk: malformed or schema-drifted responses can reach UI state as trusted data.

### Model-ready and certification manifests use broad dict shapes

Examples:

- `jobs/batch/build_model_ready_datasets.py`
- `src/leviathan/training/certification.py`
- `jobs/batch/certify_snapshot_model_candidate.py`

Risk: manifest/schema drift can pass through as unstructured JSON and only fail in downstream jobs or MLflow review.

### AWS/Athena/S3 rows and clients are weakly typed

Examples:

- `jobs/utils/athena_utils.py`
- `scripts/certification/certify_sources.py`
- `src/leviathan/training/model_ready.py`
- `src/leviathan/storage/s3.py`

Risk: broad returns hide row-shape mistakes and AWS client assumptions.

## Medium Confidence Findings

- YAML config loaders validate at runtime but use raw `dict[str, Any]` internally in modules such as WASDE snapshot mapping, snapshot stages, version status, and source manifests.
- `src/leviathan/features/computations/__init__.py` uses a loose compute function type despite having an implied stable signature.

## Recommended Phase 3 Edits

1. Add JSON aliases in `src/leviathan/common/types.py`:
   - `JsonScalar`
   - `JsonValue`
   - `JsonDict`
   - `JsonList`
2. Add focused `TypedDict` or dataclass contracts for:
   - model-ready manifests;
   - commodity build results;
   - model-ready feature observations;
   - certification report payloads;
   - fold metric rows;
   - target alert metric rows;
   - Athena rows.
3. Use `TYPE_CHECKING` boto3 client aliases where boto3 stubs are available.
4. Add frontend runtime guard/normalizer functions rather than editing generated `types.gen.ts`.
5. Tighten the feature compute function protocol only after checking all compute functions.

## Do Not Change Yet

- Generated `apps/terminal/src/api/types.gen.ts`.
- GraphRAG API model types.
- External JSON/SSE boundary `unknown` before runtime narrowing.

## Validation

- Python mypy is currently noisy and not a useful global gate. Use targeted type checks if possible.
- Frontend `npm run typecheck`.
- Unit tests for manifest serializers/deserializers.
- Runtime tests for frontend API normalizers.

