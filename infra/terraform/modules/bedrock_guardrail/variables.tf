variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "batch_job_role_name" {
  type        = string
  description = "The Batch job role that serving containers assume (gets bedrock:ApplyGuardrail)."
}
