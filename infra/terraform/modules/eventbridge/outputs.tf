output "scheduler_role_arn" {
  value       = aws_iam_role.sfn_scheduler.arn
  description = "ARN of the EventBridge Scheduler role (states:StartExecution on the machine ARN)."
}

output "schedule_names" {
  value       = [for s in aws_scheduler_schedule.family : s.name]
  description = "Names of the per-family schedules (all DISABLED until A-W7)."
}

output "schedule_arns" {
  value       = { for k, s in aws_scheduler_schedule.family : k => s.arn }
  description = "family_key -> schedule ARN."
}
