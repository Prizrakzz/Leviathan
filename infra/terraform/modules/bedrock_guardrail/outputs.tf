output "guardrail_id" {
  value       = aws_bedrock_guardrail.graphrag_input.guardrail_id
  description = "Pass as GRAPHRAG_GUARDRAIL to enable the serving input pre-filter."
}

output "guardrail_arn" {
  value = aws_bedrock_guardrail.graphrag_input.guardrail_arn
}
