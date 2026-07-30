output "backfill_orchestrator_job_definition_arn" {
  value       = aws_batch_job_definition.backfill_orchestrator.arn
  description = "ARN of the backfill orchestrator Batch job definition."
}

output "job_queue_arn" {
  value       = aws_batch_job_queue.this.arn
  description = "ARN of the shared Batch job queue."
}

output "job_queue_name" {
  value       = aws_batch_job_queue.this.name
  description = "Name of the shared Batch job queue."
}

output "ondemand_job_queue_arn" {
  value       = aws_batch_job_queue.ondemand.arn
  description = "ARN of the on-demand Fargate Batch job queue."
}

output "ondemand_job_queue_name" {
  value       = aws_batch_job_queue.ondemand.name
  description = "Name of the on-demand Fargate Batch job queue."
}

output "chirps_to_bronze_backfill_job_definition_arn" {
  value       = aws_batch_job_definition.chirps_to_bronze_backfill.arn
  description = "ARN of the CHIRPS COG → bronze backfill job definition."
}

output "nasa_power_backfill_job_definition_arn" {
  value       = aws_batch_job_definition.nasa_power_backfill.arn
  description = "ARN of the NASA POWER backfill job definition."
}

output "log_group_name" {
  value       = aws_cloudwatch_log_group.batch.name
  description = "CloudWatch log group for Batch jobs."
}

output "cpc_soil_to_raw_job_definition_arn" {
  value       = aws_batch_job_definition.cpc_soil_to_raw.arn
  description = "ARN of the CPC Soil Moisture → raw S3 job definition."
}

output "cpc_soil_raw_to_bronze_job_definition_arn" {
  value       = aws_batch_job_definition.cpc_soil_raw_to_bronze.arn
  description = "ARN of the CPC Soil Moisture raw S3 → bronze job definition."
}

output "cpc_soil_bronze_to_silver_job_definition_arn" {
  value       = aws_batch_job_definition.cpc_soil_bronze_to_silver.arn
  description = "ARN of the CPC Soil Moisture bronze → silver job definition."
}

output "modis_ndvi_raw_to_bronze_job_definition_arn" {
  value       = aws_batch_job_definition.modis_ndvi_raw_to_bronze.arn
  description = "ARN of the MODIS NDVI raw CSV → bronze Parquet job definition."
}

output "modis_ndvi_bronze_to_silver_job_definition_arn" {
  value       = aws_batch_job_definition.modis_ndvi_bronze_to_silver.arn
  description = "ARN of the MODIS NDVI bronze Parquet → silver Parquet (z-scores) job definition."
}

output "fgis_silver_job_definition_arn" {
  value       = aws_batch_job_definition.fgis_silver.arn
  description = "ARN of the USDA FGIS bronze -> silver job definition."
}

output "mpob_silver_job_definition_arn" {
  value       = aws_batch_job_definition.mpob_silver.arn
  description = "ARN of the MPOB bronze -> silver job definition."
}

output "mpob_overview_text_job_definition_arn" {
  value       = aws_batch_job_definition.mpob_overview_text.arn
  description = "ARN of the MPOB overview PDFs -> text/ job definition."
}

output "mpob_overview_bronze_job_definition_arn" {
  value       = aws_batch_job_definition.mpob_overview_bronze.arn
  description = "ARN of the MPOB overview PDFs -> bronze/ job definition."
}

output "mpob_annual_silver_job_definition_arn" {
  value       = aws_batch_job_definition.mpob_annual_silver.arn
  description = "ARN of the MPOB overview_pdf bronze -> annual silver job definition."
}

output "usda_nass_annual_silver_job_definition_arn" {
  value       = aws_batch_job_definition.usda_nass_annual_silver.arn
  description = "ARN of the USDA NASS annual bronze Parquet -> silver Parquet job definition."
}

output "usda_nass_crop_progress_silver_job_definition_arn" {
  value       = aws_batch_job_definition.usda_nass_crop_progress_silver.arn
  description = "ARN of the USDA NASS crop-progress bronze Parquet -> silver Parquet job definition."
}

output "fnc_colombia_silver_job_definition_arn" {
  value       = aws_batch_job_definition.fnc_colombia_silver.arn
  description = "ARN of the FNC Colombia bronze Parquet -> silver Parquet job definition."
}

output "conab_coffee_silver_job_definition_arn" {
  value       = aws_batch_job_definition.conab_coffee_silver.arn
  description = "ARN of the CONAB coffee bronze Parquet -> silver Parquet job definition."
}

output "usda_esr_fetch_job_definition_arn" {
  value       = one(aws_batch_job_definition.usda_esr_fetch[*].arn)
  description = "ARN of the USDA FAS ESR weekly fetch job definition (Phase D D-W1). null until fas_api_key_secret_arn is wired."
}

output "pattern_records_sweep_job_definition_arn" {
  value       = one(aws_batch_job_definition.pattern_records_sweep[*].arn)
  description = "ARN of the T2B pattern-records sweep job definition. null until pattern_records_image is pinned (rollout step 3)."
}

output "pattern_records_sweep_job_definition_name" {
  value       = "${var.project_name}-${var.environment}-pattern-records-sweep"
  description = "NAME of the T2B pattern-records sweep jobdef. Deliberately NOT derived from the count-gated resource: the schedule + the submit wrapper reference the jobdef BY NAME (so a re-registration tracks the latest ACTIVE revision), and the name is stable whether or not the digest is pinned yet."
}

# --- PRICE_AND_PLAYBOOKS W1a + W2: the two futures_eod chains ---------------
# The NAME outputs are what the DAG descriptors + dag_schedules.auto.tfvars.json
# consume (gen_sfn_inputs._unversion strips the descriptors' ":1" so the schedule
# tracks the latest ACTIVE revision). They are rendered from the two root variables
# rather than from the count-gated resources on purpose: the name a schedule must
# reference is stable whether or not the image digest / secret is pinned yet, and a
# null there would make the tfvars unrenderable exactly when it is being authored.
# The ARN outputs are null until their lane is gated in.

output "futures_eod_free_fetch_job_definition_name" {
  value       = "${var.project_name}-${var.environment}-futures-eod-free-fetch"
  description = "NAME of the futures_eod free-venue fetch jobdef (czce/jse/cepea/miax; referenced by configs/silver/dags/futures_eod_free.json)."
}

output "futures_eod_free_fetch_job_definition_arn" {
  value       = one(aws_batch_job_definition.futures_eod_free_fetch[*].arn)
  description = "ARN of the futures_eod free-venue fetch jobdef. null until futures_eod_image_digest is pinned."
}

output "databento_fetch_job_definition_name" {
  value       = "${var.project_name}-${var.environment}-databento-fetch"
  description = "NAME of the Databento raw-DBN fetch jobdef (referenced by configs/silver/dags/futures_eod_databento.json)."
}

output "databento_fetch_job_definition_arn" {
  value       = one(aws_batch_job_definition.databento_fetch[*].arn)
  description = "ARN of the Databento fetch jobdef. null until BOTH futures_eod_image_digest and databento_api_key_secret_arn are wired."
}

output "futures_eod_silver_job_definition_name" {
  value       = "${var.project_name}-${var.environment}-futures-eod-silver"
  description = "NAME of the shared silver_futures_eod producer jobdef -- referenced by BOTH futures_eod descriptors' silver phases."
}

output "futures_eod_silver_job_definition_arn" {
  value       = one(aws_batch_job_definition.futures_eod_silver[*].arn)
  description = "ARN of the shared silver_futures_eod producer jobdef. null until BOTH futures_eod_image_digest and silver_publisher_job_role_arn are wired."
}
