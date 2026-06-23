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
  description = "S3 bucket name for MLflow artifact storage (mlflow/artifacts/ prefix)."
}

variable "subnet_id" {
  type        = string
  description = "Subnet to place the MLflow EC2 instance in. Must be in the same VPC as Batch and SageMaker Training Jobs."
}

variable "ami_id" {
  type        = string
  description = "Pinned AMI for the adopted MLflow/Airflow instance. Null uses the latest AL2023 AMI."
  default     = null
  nullable    = true
}

variable "root_volume_size_gib" {
  type        = number
  description = "Root volume size for the adopted dev instance."
  default     = 10
}
