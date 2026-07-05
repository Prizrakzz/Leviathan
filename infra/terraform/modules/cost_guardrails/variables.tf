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

variable "bedrock_daily_limit" {
  type        = number
  description = "Daily Bedrock spend budget (USD) — the public-exposure spend backstop."
  default     = 20
}
