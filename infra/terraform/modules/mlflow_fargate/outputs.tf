output "tracking_uri" {
  value       = local.tracking_uri
  description = "Stable in-VPC MLFLOW_TRACKING_URI (http://mlflow.leviathan.local:5000) for the training jobdefs."
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "task_definition_arn" {
  value = aws_ecs_task_definition.this.arn
}

output "task_security_group_id" {
  value       = aws_security_group.task.id
  description = "MLflow task SG (added to the RDS SG on 5432)."
}

output "namespace_id" {
  value       = aws_service_discovery_private_dns_namespace.this.id
  description = "Cloud Map private DNS namespace id (leviathan.local)."
}

output "service_discovery_service_arn" {
  value = aws_service_discovery_service.mlflow.arn
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}

output "mlflow_url" {
  value       = var.mlflow_public_https ? "https://${local.alb_fqdn}" : "http://${aws_lb.this.dns_name}"
  description = "Browser URL for the MLflow UI. HTTPS path -> Cognito-authenticated https://mlflow.<domain>; fallback -> the raw ALB HTTP DNS (admin-CIDR locked)."
}

output "alb_dns_name" {
  value       = aws_lb.this.dns_name
  description = "ALB DNS name (alias target of the mlflow.<domain> A record)."
}

output "alb_security_group_id" {
  value       = aws_security_group.alb.id
  description = "MLflow ALB SG (source of the task SG's 5000 ingress rule)."
}
