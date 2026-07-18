# Silver Feature-Engineering Readiness EDA

This directory is the source-only exploratory knowledge base for Leviathan's
42 registered Silver tables. Its purpose is simple: make each dataset easy to
understand before feature engineering.

Each `silver_*` folder contains:

- a reader-first notebook;
- `summary.json` with the computed evidence behind the notebook;
- `feature_candidates.yaml` with review-only feature ideas;
- `spec.yaml` with row meaning, column descriptions, chart plans, units, PIT
  notes, and anti-features;
- `manifest.json` binding the original immutable EDA campaign artifacts; and
- where applicable, `local_manifest.json` binding a later local correction.

The notebooks cover row meaning, shape, previews, `df.info()`, every-column
definitions, ordinary statistics, missingness, duplicates, temporal coverage,
simple source-appropriate charts, PIT risks, feature opportunities, and exact
repair work needed before prototyping.

## Current repository status

- All 42 Silver dossiers are present.
- 39 notebooks are executed and contain embedded outputs with no execution
  errors.
- `silver_esr`, `silver_esr_compact`, and `silver_nasa_power` contain corrected
  code and evidence but intentionally have cleared outputs. Open each notebook
  and choose **Run All** to render it locally.
- `silver_wasde` and `silver_nass_crop_progress` were corrected and re-executed
  locally.
- The root readiness notebook is the executed index from the completed source
  campaign. It predates the five local corrections and must not be treated as a
  refreshed post-correction index until the three prepared notebooks above are
  executed and the index is rebuilt.

The corrected ESR dossiers distinguish shared-key parity from coverage:
753,062 shared keys match exactly, raw-only keys are zero, and 783,388
compact-only keys are a later coverage extension rather than a parity failure.
`silver_esr_compact` still retains its genuine `changes_1000mt` completeness
blocker. NASS crop-progress curves break across missing calendar weeks. WASDE
shows the selected semantic series and reports its seven incomplete rows
without misleading rounding. NASA POWER reports its exact-source missingness
as 1,263 of 6,992,403 rows (0.0181%).

## Open and run locally

From the repository root:

```powershell
uv sync --extra eda
uv run jupyter lab eda
```

Equivalent `pip` setup:

```powershell
python -m pip install -e ".[eda]"
python -m jupyter lab eda
```

Executed notebooks can be read without rerunning them. A **Run All** loads the
notebook's immutable, hash-bound campaign snapshot from the `eda/silver/`
namespace in S3, so AWS read credentials for that snapshot are required. It
does not invoke a producer or reread live Silver.

The notebooks use `src/leviathan/eda/reader_charts.py` for bounded chart
computation and rendering. That small runtime is intentionally committed with
this directory; Docker, Terraform, Batch submission, cron, ingestion, and
producer infrastructure are not required to use these notebooks.

## Hard boundaries

- No Gold, legacy Gold, model-ready matrix, label, target, or target
  correlation is used.
- The notebooks do not write Silver or Gold.
- No ingestion producer, cron schedule, training run, or MLflow run is invoked.
- Feature candidates are review records only. EDA never edits production
  feature configuration.
- `silver_model_predictions` is output-plane QA only and remains
  `excluded_leakage` with zero feature candidates.
- Outliers are described and retained; they are not silently removed.
- Every statistic and chart states source rows, analyzed rows, plotted rows,
  and whether the result is exact, sampled, or footer-derived.

## Reader contract

Every table notebook follows the same compact narrative:

1. TL;DR, meaningful KPIs, and evidence-backed insights.
2. Dataset shape, row meaning, full small table or bounded preview, `df.info()`,
   and an every-column dictionary.
3. Familiar numeric/categorical statistics and a concise quality scorecard.
4. One to four useful charts selected for that table's data shape.
5. PIT explanation, review-only feature ideas, anti-features, and repair work.
6. Technical provenance and machine diagnostics in the appendix.

Trend charts require at least eight comparable time points. Scatter and
correlation claims require at least 20 observations. Small datasets are shown
directly instead of being padded with meaningless charts.

## Artifacts and review

`feature_candidate_catalog.yaml` and each table's
`feature_candidates.yaml` are proposals, not enabled features. Promotion into
production feature configuration is a separate reviewed step.

The original `manifest.json` files remain archival records of the completed
immutable campaign. A `local_manifest.json` never changes that source history;
it records whether a corrected notebook is executed or merely prepared, the
immutable snapshot it uses, artifact hashes, and explicit `false` flags for
Gold reads, live-Silver reads, S3 writes, training, targets, and producer
execution.

Schemas and display thresholds live under `_config/`; structural notebook
templates live under `_templates/`.
