variable "project_name" {
  type        = string
  description = "Project name."
}

variable "environment" {
  type        = string
  description = "Environment name (e.g. dev, prod)."
}

variable "aws_region" {
  type        = string
  description = "AWS region."
}
