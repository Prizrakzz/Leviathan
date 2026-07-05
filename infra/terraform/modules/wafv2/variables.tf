variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "alb_arn" {
  type        = string
  description = "ARN of the ALB to associate the Web ACL with."
}

variable "blocking_enabled" {
  type        = bool
  description = "false = COUNT mode (observe); true = BLOCK. Ship false, flip true after 24-48h observation."
  default     = false
}

variable "respond_rate_limit" {
  type        = number
  description = "Max /v1/respond* requests per IP per 5-min window (each is an expensive Bedrock turn)."
  default     = 30
}

variable "global_rate_limit" {
  type        = number
  description = "Max requests per IP per 5-min window across all paths (flood guard)."
  default     = 2000
}
