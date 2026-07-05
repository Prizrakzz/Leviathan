output "table_name" {
  value       = aws_dynamodb_table.store.name
  description = "Terminal store table name -> GRAPHRAG_STORE_TABLE on the serving task."
}

output "table_arn" {
  value       = aws_dynamodb_table.store.arn
  description = "Table ARN for the task-role IAM policy."
}
