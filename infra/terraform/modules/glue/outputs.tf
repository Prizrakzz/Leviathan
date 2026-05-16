output "raw_to_bronze_nasa_power_job_name" {
  value       = module.raw_to_bronze_nasa_power.job_name
  description = "Name of the raw→bronze NASA POWER Glue job."
}

output "raw_to_bronze_faostat_job_name" {
  value       = module.raw_to_bronze_faostat.job_name
  description = "Name of the raw→bronze FAOSTAT Glue job."
}

output "bronze_to_silver_nasa_power_job_name" {
  value       = module.bronze_to_silver_nasa_power.job_name
  description = "Name of the bronze→silver NASA POWER Glue job."
}

output "bronze_to_silver_faostat_job_name" {
  value       = module.bronze_to_silver_faostat.job_name
  description = "Name of the bronze→silver FAOSTAT Glue job."
}

output "chirps_to_bronze_job_name" {
  value       = module.chirps_to_bronze.job_name
  description = "Name of the COG→bronze CHIRPS Glue job."
}

output "bronze_to_silver_chirps_job_name" {
  value       = module.bronze_to_silver_chirps.job_name
  description = "Name of the bronze→silver CHIRPS Glue job."
}

