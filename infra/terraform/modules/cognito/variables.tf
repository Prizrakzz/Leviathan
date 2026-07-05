variable "project_name" {
  type        = string
  description = "Project name."
}

variable "environment" {
  type        = string
  description = "Environment name."
}

variable "aws_region" {
  type        = string
  description = "AWS region (for the Cognito hosted-domain URL)."
}

variable "domain_prefix" {
  type        = string
  description = "Cognito hosted-UI domain prefix (globally unique within the region)."
}

variable "google_client_id" {
  type        = string
  description = "Google OAuth 2.0 web client id."
}

variable "google_client_secret" {
  type        = string
  description = "Google OAuth 2.0 web client secret."
  sensitive   = true
}

variable "callback_urls" {
  type        = list(string)
  description = "Allowed OAuth callback URLs (the SPA's /auth/callback + localhost)."
}

variable "logout_urls" {
  type        = list(string)
  description = "Allowed sign-out redirect URLs."
}

variable "allowlist_emails" {
  type        = string
  description = "Comma-separated email allow-list for the pre-sign-up Lambda. Empty (default) = open signup."
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
