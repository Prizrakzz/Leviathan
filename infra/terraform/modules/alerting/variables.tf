variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "alert_email" {
  type        = string
  description = "Email that receives alarm notifications (must confirm the SNS subscription)."
}
