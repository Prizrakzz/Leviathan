output "raw_to_bronze_nasa_power_job_name" {
  value       = aws_glue_job.raw_to_bronze_nasa_power.name
  description = "Name of the raw→bronze NASA POWER Glue job."
}

output "raw_to_bronze_faostat_job_name" {
  value       = aws_glue_job.raw_to_bronze_faostat.name
  description = "Name of the raw→bronze FAOSTAT Glue job."
}

output "bronze_to_silver_nasa_power_job_name" {
  value       = aws_glue_job.bronze_to_silver_nasa_power.name
  description = "Name of the bronze→silver NASA POWER Glue job."
}

output "bronze_to_silver_faostat_job_name" {
  value       = aws_glue_job.bronze_to_silver_faostat.name
  description = "Name of the bronze→silver FAOSTAT Glue job."
}
