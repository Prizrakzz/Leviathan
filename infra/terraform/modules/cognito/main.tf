# ---------------------------------------------------------------------------
# Cognito user pool with Google federated sign-in (Phase 4 Stage 4).
#
# Sign up + sign in are the SAME "Continue with Google" OAuth authorization-code flow — Cognito
# auto-provisions the user on first Google login (open access). The SPA sends the Cognito-issued ID
# token (aud = app client id) as `Authorization: Bearer`; auth.py verifies it (RS256, iss/aud/exp).
# ---------------------------------------------------------------------------

locals {
  name = "${var.project_name}-${var.environment}-terminal"
}

resource "aws_cognito_user_pool" "this" {
  name                     = local.name
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # Federated users come from Google; a password policy is still required by the API even if unused.
  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = false
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  tags = merge(var.tags, { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" })
}

# Cognito-hosted OAuth domain: https://<prefix>.auth.<region>.amazoncognito.com (free; no cert/DNS needed).
resource "aws_cognito_user_pool_domain" "this" {
  domain       = var.domain_prefix
  user_pool_id = aws_cognito_user_pool.this.id
}

# Google as a federated identity provider. Secrets come from tfvars (gitignored) via variables.
resource "aws_cognito_identity_provider" "google" {
  user_pool_id  = aws_cognito_user_pool.this.id
  provider_name = "Google"
  provider_type = "Google"

  provider_details = {
    client_id                     = var.google_client_id
    client_secret                 = var.google_client_secret
    authorize_scopes              = "openid email profile"
    attributes_url_add_attributes = "true"
  }

  # Map Google claims -> Cognito user attributes.
  attribute_mapping = {
    email    = "email"
    username = "sub"
  }
}

resource "aws_cognito_user_pool_client" "spa" {
  name         = "${local.name}-spa"
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret = false # public SPA client — a browser cannot keep a secret

  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["Google"]

  callback_urls = var.callback_urls
  logout_urls   = var.logout_urls

  explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH"]

  # Reasonable token lifetimes for a research tool.
  access_token_validity  = 60 # minutes
  id_token_validity      = 60 # minutes
  refresh_token_validity = 30 # days
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  prevent_user_existence_errors = "ENABLED"

  # Google must be registered before the client can list it as a supported IdP.
  depends_on = [aws_cognito_identity_provider.google]
}
