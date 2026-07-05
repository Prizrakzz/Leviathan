output "user_pool_id" {
  value       = aws_cognito_user_pool.this.id
  description = "Cognito user pool id -> COGNITO_USER_POOL_ID on the serving task + VITE_COGNITO_USER_POOL_ID."
}

output "app_client_id" {
  value       = aws_cognito_user_pool_client.spa.id
  description = "SPA app client id -> COGNITO_APP_CLIENT_ID + VITE_COGNITO_CLIENT_ID."
}

output "hosted_domain" {
  value       = "https://${aws_cognito_user_pool_domain.this.domain}.auth.${var.aws_region}.amazoncognito.com"
  description = "Cognito OAuth base URL — the SPA redirects here with identity_provider=Google."
}

output "domain_prefix" {
  value = aws_cognito_user_pool_domain.this.domain
}
