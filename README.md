# Leviathan Research

<p align="center">
  <img src="assets/Leviathan-Banner.png" alt="Leviathan Research" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue?style=flat-square&logo=python" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/AWS-Batch%20%7C%20Glue%20%7C%20Athena-orange?style=flat-square&logo=amazonaws" alt="AWS">
  <img src="https://img.shields.io/badge/Infrastructure-Terraform-purple?style=flat-square&logo=terraform" alt="Terraform">
  <img src="https://img.shields.io/badge/ML-XGBoost%20%2B%20SHAP-red?style=flat-square" alt="XGBoost">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License">
</p>

---

**Leviathan Research** is an open-source, AWS-native commodity intelligence platform that generates production-informed mispricing signals across **31 agricultural commodities**. It fuses a quantitative ML production forecasting layer with a qualitative GraphRAG knowledge graph to produce spread trading signals grounded in supply/demand fundamentals.

---

## The Thesis

> *Forecast what production will be this season, find every historical year where production was at that level, observe what price did in those environments, and identify when current price has not yet adjusted to what the fundamentals imply.*

This is not directional macro trading. It is:

- **Spread / relative value** — identify when country-level origin stress diverges between legs of a spread pair (arabica/robusta, CBOT corn/Campinas corn, CBOT soy/DCE soy), generating a fundamental basis trade.
- **Mispricing z-score** — when current price has not yet converged to what analogous production environments implied historically, sized by the weighted distribution of those historical outcomes.

The system fuses two independent layers that answer different questions:

**Quantitative layer** — weather + production data → ML production forecast → historical analogue lookup → mispricing signal. Tells you *that* a signal fired and *how large* the historical edge was.

**Temporal knowledge graph** — the part that makes this system genuinely different. A directed graph over ~4,900 analyst documents (USDA GAIN, CONAB, WASDE, WAP, FNC, MPOB, SAGIS) where every node carries a publication timestamp and every edge encodes a documented causal relationship. This enables:

- **Event-chain traversal** — given a stress event (Brazil arabica flowering failure, Indonesian palm export ban, La Niña onset), traverse the full documented cascade of downstream consequences with their historical lag times at each step. Not a single-hop answer — a multi-hop propagation sequence grounded in what analysts actually wrote, with citations.
- **Cascading effect analysis** — when Ukraine wheat exports are disrupted, the graph traces: which importers panic-buy → from which alternative origins → whether those origins draw down carry-in stocks → whether feed grain substitution tightens corn stocks-to-use. Each hop is a documented edge, not an inference.
- **Cross-source corroboration** — a signal that appears in one GAIN report is weak. The same signal corroborated independently by CONAB, a separate GAIN report, and a WASDE narrative within the same 30-day window is a different conviction level entirely. The graph scores this.
- **Point-in-time discipline** — every query can be time-gated to return only information published before a given date. This is the qualitative equivalent of walk-forward cross-validation: you can ask what the graph would have told you in October 2021, with zero look-ahead.

The quantitative layer tells you the signal exists. The knowledge graph tells you *why you believe it*, *what the documented historical consequence chain is*, and *whether independent sources agree* — the three things an investment committee actually needs.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA LAYER (Medallion)                       │
│                                                                     │
│  NASA POWER ──┐                                                     │
│  CHIRPS v3 ───┤──► S3 raw/ ──► S3 bronze/ ──► S3 silver/           │
│  FAOSTAT ─────┤     (JSON/    (Parquet,       (Parquet,             │
│  USDA PSD ────┤      CSV)      typed)          ML-ready)            │
│  WASDE ───────┤                                                     │
│  CONAB ───────┤  Compute: AWS Batch Fargate + AWS Glue Python Shell │
│  FGIS/ESR ────┘  Query:   Amazon Athena + Glue Data Catalog         │
└─────────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌─────────────────┐ ┌──────────────────┐ ┌──────────────────────────┐
│   TIER 1        │ │   TIER 2         │ │   TIER 3                 │
│  Origin Stress  │ │  S/D Balance     │ │  Spread Signal           │
│                 │ │                  │ │                          │
│  XGBoost per    │ │  XGBoost per     │ │  Mispricing z-score      │
│  country ×      │ │  commodity ×     │ │  vs. weighted historical │
│  commodity ×    │ │  marketing year  │ │  analogue distribution   │
│  crop year      │ │                  │ │                          │
│                 │ │  + WASDE/PSD     │ │  + COT positioning       │
│  Weather +      │ │  revision        │ │  + FX cross rate         │
│  crop-stage     │ │  surprise        │ │  + calendar spread z     │
│  features       │ │                  │ │                          │
└─────────────────┘ └──────────────────┘ └──────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │     GraphRAG Knowledge Graph  │
              │                               │
              │  GAIN + CONAB + WASDE + WAP   │
              │  + WMT + FNC + MPOB + SAGIS   │
              │                               │
              │  ~4,900 docs / ~49,500 pages  │
              │  Consequence chains · Analyst │
              │  accuracy · Tone escalation · │
              │  Point-in-time research       │
              └───────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │   LangGraph Agent + FastAPI   │
              │   React / TypeScript Chat UI  │
              └───────────────────────────────┘
```

---

## The 31 Commodities

| Group | Contracts |
|---|---|
| **Grains** | CBOT Corn, BMF Campinas Corn, MATIF Wheat, MATIF Corn, KCBT HRW Wheat, MGEX HRS Wheat, CBOT SRW Wheat, CBOT Rough Rice, JSE White Maize, JSE Yellow Maize |
| **Oilseeds** | CBOT Soybeans, CBOT Soybean Meal, CBOT Soybean Oil, DCE No.1 Soybeans, DCE No.2 Soybeans, DCE Soybean Meal, DCE Soybean Oil, MATIF Rapeseed, ICE Canola, ZCE Rapeseed Oil, ZCE Rapeseed Meal, CME Malaysian Palm Oil, DCE Palm Olein |
| **Softs** | ICE Arabica Coffee, BMF Brazilian Arabica, ICE Robusta Coffee, ICE Cotton, ICE Raw Sugar, LIFFE White Sugar, ICE Frozen OJ, ICE Cocoa |

---

## Feature Design Principles

### Crop-Stage-Aware Weather Features

All weather features are anchored to **biological crop stages**, not raw calendar months. A −2σ moisture anomaly during silking/pollination for corn has a categorically different yield consequence than the same anomaly during vegetative growth. Stage-split features let the model learn stage-specific sensitivities and produce directly interpretable SHAP attributions.

```
planting → emergence → vegetative → [critical reproductive stage] → grain fill → maturity → harvest
```

Every `chirps_precip_z`, `nasa_tmax_anomaly`, and `drought_consecutive_days` feature is computed over a **named phenological window** defined in `configs/sources/crop_calendars.yaml`.

### Tree Crop Capacity Recovery

Annual crops reset every season; tree crops do not. Arabica, robusta, cocoa, and palm oil models carry a **capacity recovery index** that decays across seasons following frost events, disease pressure, or extreme heat — damage to productive wood does not recover in one year.

### Look-Ahead Bias Prevention

All features use only data available at the point-in-time being forecast:

- CHIRPS/POWER z-scores use a **fixed 1981–2010 WMO climatological baseline** — never recomputed from the training set
- Walk-forward cross-validation: scaler and expanding baselines fitted inside each fold on training years only
- SageMaker Feature Store point-in-time retrieval enforces vintage discipline at inference time

---

## Data Sources

### Weather

| Source | Coverage |
|---|---|
| NASA POWER | All 31 commodities × all regions, daily, 1981–present |
| CHIRPS v3 | All regions, daily, 1981–present |
| MODIS NDVI (MOD13A1) | All crop regions, 16-day composites, 2000–present |
| NOAA CPC Soil Moisture | Global 0.5°, daily, 1948–present |
| NOAA ONI (ENSO) | Monthly, 1950–present |
| NOAA IOD (Indian Ocean Dipole) | Monthly, 1870–present |

### Production & Supply/Demand

| Source | Coverage |
|---|---|
| FAOSTAT QCL | 31 commodities, 188 countries, 1961–2024 |
| USDA PSD | All 31 commodities, 1960s–present |
| USDA WASDE | Monthly revisions, 1973–present |
| USDA NASS Crop Progress | US crops, weekly in-season, 1979–present |
| USDA NASS Annual | US corn, soy, cotton, wheat, rice |
| USDA FAS FGIS Export Inspections | US grain/oilseed weekly export volumes, 1983–present |
| USDA FAS ESR (Export Sales Reporting) | Weekly forward commitments, ~1990–present |
| USDA WAP (World Agricultural Production) | Monthly non-US production estimates, 1988–present |
| USDA GAIN Reports | Country crop intelligence, 3,689 PDFs across 15 commodity groups |
| CONAB | Brazil coffee bimonthly crop surveys, 2005–present |
| UNICA | Brazil CS sugarcane annual production, 1980/81–present |
| MPOB | Malaysian palm oil monthly statistics, 2010–present |
| FNC Colombia | Colombia coffee production and exports, 1913–present |
| SAGIS CEC | South Africa monthly crop estimates, 1999–present |
| SAGIS Weekly Deliveries | SA maize weekly producer flows, 2006/07–present |

### Price & Positioning

| Source | Coverage |
|---|---|
| World Bank Pink Sheet | Monthly commodity prices + input costs (urea, DAP), 1960–present |
| World Bank Food CPI | Domestic food inflation IND/RUS/IDN/UKR, 1960–present |
| CFTC COT (disaggregated) | Managed money positioning, 12 US/ICE contracts, weekly, 2006–present |
| yfinance | Front-month continuous futures, 12 US/ICE contracts, daily, 2000–present |
| FRED | BRL/USD and ARS/USD exchange rates, daily, 2005–present |

---

## Repository Layout

```
configs/
  commodities/          # Per-commodity modelling config (targets, grain, sources)
  geographies/          # Region definitions with lat/lon coordinates
  sources/              # crop_calendars.yaml, entity_vocabulary.yaml, faostat_item_map.yaml

docker/
  leviathan_worker/     # Fargate container image for batch ingestion

infra/terraform/
  envs/dev|prod/        # Environment entrypoints
  modules/              # batch, cloudwatch, ecr, glue, iam, s3, secrets, step_functions

jobs/
  batch/                # AWS Batch Fargate task entrypoints (one per data source)
  ingest/               # Ingestion scripts (NASA POWER, CONAB, FAOSTAT, FGIS, ESR, …)
  orchestrate/          # Pipeline orchestration scripts
  submit/               # Batch job submission helpers

src/leviathan/
  common/               # Logging, config loading
  ingestion/            # Source-specific API clients
  storage/              # S3 helpers, path builders (paths.py)
  transforms/
    raw_to_bronze/      # One module per data source
    bronze_to_silver/   # One module per data source

sql/
  athena/               # DDL and query templates

tests/
  unit/                 # Transform and utility tests
  integration/          # End-to-end pipeline tests
  data_quality/         # Silver layer quality assertions
```

---

## Getting Started

**Requirements:** Python 3.11+, AWS CLI configured, Terraform 1.5+

```bash
git clone https://github.com/Prizrakzz/Leviathan.git
cd Leviathan

python -m venv .venv
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows

pip install -e .
```

AWS credentials must have access to S3, Glue, Batch, and Athena. Configure the bucket name and region in `infra/terraform/envs/dev/terraform.tfvars`.

### Environment variables

```bash
export LEVIATHAN_BUCKET=your-s3-bucket-name
export AWS_REGION=us-east-1
```

---

## Infrastructure

```bash
cd infra/terraform/envs/dev
terraform init
terraform plan
terraform apply
```

Provisions: versioned S3 bucket, IAM roles, ECR repository, Batch compute environment and job queue, Glue jobs, and CloudWatch log groups. Glue scripts and the `leviathan` wheel are re-deployed automatically on content change.

---

## Running the Pipeline

### Weather (NASA POWER)

```bash
python jobs/submit/submit_batch_backfill_nasa_power.py \
  --commodity arabica_coffee \
  --start-year 1981 --end-year 2025
```

### Production data (FAOSTAT)

```bash
python jobs/upload_raw_faostat_qcl.py \
  --file /path/to/Production_Crops_Livestock_E_All_Data_(Normalized).zip

aws glue start-job-run --job-name leviathan-dev-raw-to-bronze-faostat
aws glue start-job-run --job-name leviathan-dev-bronze-to-silver-faostat
```

### Price & positioning data

```bash
# Front-month futures prices
python jobs/batch/yfinance_futures_task.py

# CFTC Commitments of Traders
python jobs/batch/cftc_cot_bronze_task.py
python jobs/batch/cftc_cot_silver_task.py

# World Bank Food CPI
python jobs/batch/food_cpi_task.py

# NOAA Indian Ocean Dipole
python jobs/batch/noaa_iod_task.py
```

### Glue transforms

```bash
aws glue start-job-run --job-name leviathan-dev-raw-to-bronze-nasa-power
aws glue start-job-run --job-name leviathan-dev-bronze-to-silver-nasa-power
```

All jobs are idempotent — existing partitions are skipped unless `--force-overwrite` is passed.

#### FAOSTAT derived product mapping

Several futures contracts correspond to processed products. FAOSTAT publishes primary crop statistics, so derived contracts map to their parent crop:

| Commodity | FAO item used | Relationship |
|---|---|---|
| `soybean_meal_cbot`, `soybean_meal_dce` | `Soya beans` | Meal is a crush by-product |
| `soybean_oil_cbot`, `soybean_oil_dce` | `Soya bean oil` | Direct FAO item |
| `rapeseed_oil_zce` | `Rapeseed or canola oil, crude` | Direct FAO item |
| `rapeseed_meal_zce` | `Rape or colza seed` | No separate FAO meal item |
| `white_sugar` | `Sugar cane` | Refined sugar uses cane production |

Mappings are defined in `configs/sources/faostat_item_map.yaml`.

---

## Three-Tier ML Model

| Tier | Input | Output | Model |
|---|---|---|---|
| **Tier 1 — Origin Stress** | Crop-stage weather z-scores, commodity-specific features, anomaly detection flags | `origin_stress_score` [0–1], `production_forecast` ± 80% CI | XGBoost, walk-forward CV (min 5yr OOS) |
| **Tier 2 — S/D Balance** | Aggregated Tier 1 scores, USDA PSD S/U ratio, WASDE revision surprise, export pace z-score | `ending_stock_forecast`, `su_ratio_surprise` | XGBoost, marketing-year grain |
| **Tier 3 — Spread Signal** | Tier 2 `su_ratio_surprise` per leg, COT net MM z-score, FX cross rate, calendar spread z | `spread_signal` z-score, `spread_conviction` [0–1] | Analogue lookup + weighted historical distribution |

**Spread conviction** replaces a binary fire/no-fire flag with a continuous score:

```
conviction = 1 − min(stress_leg_A, stress_leg_B) / max(stress_leg_A, stress_leg_B)
```

Pure asymmetric stress → conviction near 1. Equal bilateral stress → conviction near 0. Position sizing scales continuously rather than switching between full-size and no-trade.

---

## GraphRAG Knowledge Graph

The quantitative model tells you a signal fired. GraphRAG tells you *why you believe it* and *how convicted to be*.

Six research modes over ~4,900 documents (~49,500 pages) spanning USDA GAIN, CONAB, WASDE, WAP, FNC, MPOB, and SAGIS:

| Mode | Example Query |
|---|---|
| **Relative Value** | "When arabica and robusta are simultaneously stressed, which leg moves first?" |
| **Consequence Chain** | "Brazil CS sugar runs 6 MMT below forecast — walk through every documented downstream effect." |
| **Counterfactual** | "Show years where flowering stress was comparable to now but production did NOT miss. What separated them?" |
| **Analyst Accuracy** | "At what point in the season do GAIN attaché reports become directionally reliable for Brazil coffee?" |
| **Tone Escalation** | "Detect episodes where analyst tone shifted from neutral to concerned across 3+ consecutive reports before any quant signal." |
| **Point-in-Time** | "As of October 2021, what had been documented about Brazilian arabica flowering stress?" |

All graph nodes carry a `document_date` timestamp — queries can be time-gated to return only information available before a given date, enabling look-ahead-bias-free qualitative backtesting.

---

## Monthly Cost Estimate (Dev)

| Component | Est. Cost |
|---|---|
| S3 (~500 GB) | $12 |
| Glue (daily + monthly transform jobs) | $8 |
| Batch Fargate (inference + training + backfills) | $15 |
| SageMaker Feature Store offline | ~$1 |
| Athena queries | $3 |
| FastAPI on Fargate (always-on) | $35 |
| Bedrock (Claude Haiku + Sonnet synthesis) | $10–20 |
| CloudWatch + SNS | $5 |
| **Total** | **~$90–100 / month** |

No SageMaker inference endpoints. No persistent vector database. No RDS. All graph artifacts in S3 Parquet, loaded into memory at query time.

---

## Adding a New Commodity

1. Add `configs/commodities/<commodity>.yaml` — define targets, modelling grain, and sources.
2. Add `configs/geographies/<commodity>_regions.yaml` — define countries, regions, and coordinates.
3. Pass `--commodity <name>` to all Glue jobs and backfill scripts.
4. Define phenological windows and crop_year → marketing_year mapping in `configs/sources/crop_calendars.yaml`.

---

## Building the Package

The `leviathan` package is distributed as a wheel and bootstrapped into Glue at runtime:

```bash
pip install build
python -m build --wheel

aws s3 cp dist/leviathan-0.1.0-py3-none-any.whl \
  s3://<bucket>/glue-libs/leviathan-0.1.0-py3-none-any.whl
```

The wheel is also managed as a Terraform `aws_s3_object` resource and re-uploaded automatically on content change.

---

## Contributing

Contributions are welcome. Please open an issue before submitting a large pull request.

Areas where help is most valuable:

- **Bronze parsers** — CONAB PDF bulletins, WASDE structured tables, SAGIS/CEC crop estimates, NASS Citrus, ICCO quarterly bulletins
- **Feature engineering pipeline** — stage-aware z-score computation, SageMaker Feature Store integration
- **GraphRAG indexing** — propositional chunking, entity/relationship extraction, vocabulary tuning
- **Tests** — unit tests for transforms, integration tests against a local MinIO bucket

```bash
pip install -e ".[dev]"
pytest tests/unit/
```

---

## Detailed Specification

Full feature taxonomy, per-commodity specifications, anomaly detector definitions, GraphRAG indexing pipeline, LangGraph agent architecture, and MLOps stack are documented in [`desiredstate.md`](desiredstate.md).

---

## License

MIT License — see [LICENSE](LICENSE) for details.
