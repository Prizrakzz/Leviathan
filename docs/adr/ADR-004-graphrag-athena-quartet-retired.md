# ADR-004: The graphrag_* Athena quartet is retired on paper

Date: 2026-08-18 | Status: ACCEPTED (owner-ratified, D-LD Q4) | Deciders: owner + D-LD wave

## Context

Four Athena tables — `graphrag_forecasts`, `graphrag_sentiment`, `graphrag_entities`,
`graphrag_causal_edges` — hold 318 objects each under `s3://leviathan-dev-shahem-001/graphrag/*`
(partition `source=usda_wap`, monthly, last written 2026-05-30). The D-LD system-wide recon
(wf_14e22400, Lens D) measured: **zero readers**. Their only in-repo reference is the DDL
runner (`jobs/run_athena_ddl.py:33-36`); no F010 contract, no numbers card, no writer in the
tree, no serving code path. They are artifacts of the pre-pgvector evidence era — the pgvector
store (`EVIDENCE_BACKEND=pg`, S3 = truth) superseded the query pattern they were built for,
and no retirement decision was ever put on record.

## Decision

**Retired on paper. Nothing is deleted.**

- The S3 objects stay (storage is cents; deletion is irreversible; versioning conventions of
  this estate treat deletion as a separate, owner-executed act).
- The Glue tables and DDL files stay for now — a follow-up sweep may drop the DDL files from
  the runner's active set, as its own reviewed change.
- No new writer, reader, card, or contract may be built against these tables without
  superseding this ADR. A future need for forecast/sentiment/entity/edge *serving* goes
  through the current architecture (pgvector evidence store, F010 + numbers cards), never
  by reviving this quartet.

## Consequences

- The "4 Athena tables with data, zero readers" recon finding is closed as DELIBERATE with
  this record, rather than re-discovered by every future census.
- Any storage-cost sweep can cite this ADR when it proposes actual deletion to the owner.
