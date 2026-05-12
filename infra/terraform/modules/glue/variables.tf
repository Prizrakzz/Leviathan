variable "project_name" {
  type        = string
  description = "Project name."
}

variable "environment" {
  type        = string
  description = "Environment name."
}

variable "aws_region" {
  type        = string
  description = "AWS region."
}

variable "bucket_name" {
  type        = string
  description = "S3 data lake bucket name."
}

variable "glue_job_role_arn" {
  type        = string
  description = "ARN of the IAM role assumed by Glue jobs."
}

variable "commodity" {
  type    = string
  default = "cocoa"
}