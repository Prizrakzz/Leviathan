variable "project_name" {
  type        = string
  description = "Project name."
}

variable "environment" {
  type        = string
  description = "Environment name."
}

variable "repository_name" {
  type        = string
  description = "Short repository name. Will be prefixed with project_name and environment."
}
