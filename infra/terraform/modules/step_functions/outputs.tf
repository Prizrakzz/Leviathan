output "state_machine_arn" {
  value       = aws_sfn_state_machine.silver_thin_contract.arn
  description = "ARN of the silver thin-contract state machine (Scheduler target + orchestration-plane alarm dimension)."
}

output "state_machine_name" {
  value       = aws_sfn_state_machine.silver_thin_contract.name
  description = "Name of the silver thin-contract state machine."
}

output "exec_role_arn" {
  value       = aws_iam_role.sfn_exec.arn
  description = "ARN of the states execution role."
}

output "log_group_name" {
  value       = aws_cloudwatch_log_group.sfn.name
  description = "CloudWatch vended-log group for the state machine."
}
