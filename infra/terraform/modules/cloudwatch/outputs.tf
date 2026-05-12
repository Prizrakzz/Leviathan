output "dashboard_name" {
  value       = aws_cloudwatch_dashboard.pipeline.dashboard_name
  description = "Name of the CloudWatch pipeline dashboard."
}

output "dashboard_arn" {
  value       = aws_cloudwatch_dashboard.pipeline.dashboard_arn
  description = "ARN of the CloudWatch pipeline dashboard."
}
