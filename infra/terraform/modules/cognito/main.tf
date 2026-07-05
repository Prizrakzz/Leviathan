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

  # Stage 5.2: pass-through pre-sign-up gate (allow-list capable later via the Lambda's ALLOWLIST_EMAILS env).
  lambda_config {
    pre_sign_up = aws_lambda_function.presignup.arn
  }

  tags = merge(var.tags, { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" })

  # The invoke permission must exist before Cognito validates lambda_config; the permission uses a wildcard
  # source_arn (no back-reference to this pool) to avoid a dependency cycle, so order it explicitly.
  depends_on = [aws_lambda_permission.presignup]
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

  # Map Google claims -> Cognito user attributes. name/given_name/picture (5.6 W1) flow into the ID token
  # so the UI can show the real user; they populate per user at that user's NEXT Google sign-in.
  attribute_mapping = {
    email      = "email"
    username   = "sub"
    name       = "name"
    given_name = "given_name"
    picture    = "picture"
  }

  # Cognito auto-populates the Google OIDC endpoint URLs (fixed for provider_type=Google) into
  # provider_details and returns them in state; our config doesn't set them, so every plan wants to null
  # them out — the well-known social-IdP perpetual diff. Ignore exactly those AWS-managed keys so an
  # unrelated apply (e.g. a serving deploy) never reapplies them against live Google sign-in. client_id,
  # client_secret, and authorize_scopes stay tracked (rotate a secret via -replace if ever needed).
  lifecycle {
    ignore_changes = [
      provider_details["attributes_url"],
      provider_details["authorize_url"],
      provider_details["oidc_issuer"],
      provider_details["token_request_method"],
      provider_details["token_url"],
    ]
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

# ---------------------------------------------------------------------------
# Pre-sign-up Lambda (Stage 5.2): a pass-through allow-list gate. Deployed
# ALLOW-ALL; to restrict signups later, set ALLOWLIST_EMAILS on the Lambda (no
# pool / SPA change). The one control that matters for an open Google-signup
# pool — advanced-security threat protection is skipped (federated-only = no
# passwords to protect + it needs the paid Plus tier).
# ---------------------------------------------------------------------------
data "aws_caller_identity" "current" {}

data "archive_file" "presignup" {
  type        = "zip"
  source_file = "${path.module}/lambda/presignup.py"
  output_path = "${path.module}/lambda/presignup.zip"
}

resource "aws_iam_role" "presignup" {
  name = "${local.name}-presignup"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  tags = merge(var.tags, { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" })
}

resource "aws_iam_role_policy_attachment" "presignup_basic" {
  role       = aws_iam_role.presignup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "presignup" {
  function_name    = "${local.name}-presignup"
  role             = aws_iam_role.presignup.arn
  handler          = "presignup.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.presignup.output_path
  source_code_hash = data.archive_file.presignup.output_base64sha256
  timeout          = 5

  environment {
    variables = { ALLOWLIST_EMAILS = var.allowlist_emails }
  }

  tags = merge(var.tags, { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" })
}

# Wildcard source_arn (any user pool in the account) — deliberately NOT a back-reference to
# aws_cognito_user_pool.this, so the pool can depend_on this permission without a cycle.
resource "aws_lambda_permission" "presignup" {
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.presignup.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = "arn:aws:cognito-idp:${var.aws_region}:${data.aws_caller_identity.current.account_id}:userpool/*"
}
