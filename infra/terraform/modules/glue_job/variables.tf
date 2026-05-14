variable "job_name" {
  type        = string
  description = "Name of the Glue job (must match the name used in the orchestrator)."
}

variable "script_local_path" {
  type        = string
  description = "Absolute local path to the Glue script. Used for S3 upload and filemd5 drift detection."
}

variable "bucket_name" {
  type        = string
  description = "S3 bucket used for script storage, temp dir, and job arguments."
}

variable "glue_role_arn" {
  type        = string
  description = "IAM role ARN that the Glue job assumes at runtime."
}

variable "aws_region" {
  type        = string
  description = "AWS region passed to the job as --aws_region."
}

variable "project_name" {
  type        = string
  description = "Project name tag applied to all resources."
}

variable "environment" {
  type        = string
  description = "Environment tag (e.g. dev, prod)."
}

variable "extra_default_args" {
  type        = map(string)
  default     = {}
  description = "Additional Glue default_arguments merged on top of the common set."
}

variable "max_concurrent_runs" {
  type        = number
  default     = 200
  description = "Maximum number of concurrent Glue job runs."
}

variable "max_capacity" {
  type        = number
  default     = 1.0
  description = "Glue Python Shell DPU capacity (0.0625 or 1.0)."
}
