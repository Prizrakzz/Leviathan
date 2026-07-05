output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "task_security_group_id" {
  value       = aws_security_group.task.id
  description = "Serving task SG (allowed inbound from the ALB SG; added to the RDS SG on 5432)."
}

output "task_definition_arn" {
  value = aws_ecs_task_definition.this.arn
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}
