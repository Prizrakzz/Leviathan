output "topic_arn" {
  value       = aws_sns_topic.alerts.arn
  description = "SNS topic ARN — pass to CloudWatch alarm_actions."
}
