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

# --- Serving observability (Stage 5.2). All optional: unset -> the serving dashboard/alarms are skipped and
#     the module still emits only the Glue pipeline observability. -------------------------------------------
variable "alert_topic_arn" {
  type        = string
  description = "SNS topic ARN for alarm + ok actions (module.alerting). Empty = no alarm actions."
  default     = ""
}

variable "alb_arn" {
  type        = string
  description = "Serving ALB ARN — its suffix drives the ApplicationELB dashboard/alarm dimensions."
  default     = ""
}

variable "target_group_arn" {
  type        = string
  description = "Serving ALB target group ARN — its suffix drives the TargetGroup dimension."
  default     = ""
}

variable "ecs_cluster_name" {
  type        = string
  description = "Serving ECS cluster name — AWS/ECS dashboard/alarm dimension."
  default     = ""
}

variable "ecs_service_name" {
  type        = string
  description = "Serving ECS service name — AWS/ECS dashboard/alarm dimension."
  default     = ""
}

variable "waf_web_acl_name" {
  type        = string
  description = "Serving WAFv2 web ACL name — AWS/WAFV2 dashboard dimension."
  default     = ""
}
