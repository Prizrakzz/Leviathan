output "alb_arn" {
  value = aws_lb.this.arn
}

output "alb_dns_name" {
  value       = aws_lb.this.dns_name
  description = "Public DNS name of the ALB — point the local terminal here (VITE_API_BASE) in Stage 1."
}

output "alb_zone_id" {
  value       = aws_lb.this.zone_id
  description = "Hosted-zone ID for a Route53 ALIAS to the ALB (Stage 4, api. subdomain)."
}

output "alb_security_group_id" {
  value       = aws_security_group.alb.id
  description = "ALB SG — the ECS task SG allows inbound only from this SG."
}

output "target_group_arn" {
  value       = aws_lb_target_group.this.arn
  description = "Target group the ECS service registers into."
}

output "listener_arn" {
  value = aws_lb_listener.this.arn
}
