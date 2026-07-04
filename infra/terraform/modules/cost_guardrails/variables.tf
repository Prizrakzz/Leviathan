variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "alert_email" {
  type        = string
  description = "Where budget breaches and cost anomalies are sent."
}
