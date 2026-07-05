output "web_acl_arn" {
  value       = aws_wafv2_web_acl.this.arn
  description = "The Web ACL ARN (for dashboards / reference)."
}
