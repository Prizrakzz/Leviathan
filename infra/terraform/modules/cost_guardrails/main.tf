# ---------------------------------------------------------------------------
# Cost guardrails (Jul-2026 S3 LIST storm: 26.8M ListBucket = $134 billed
# silently over two days). A DAILY cost budget on the S3 service — the storm
# was ~$50-80/day vs a normal S3 day well under $1; alerts at 100% of $5/day
# ACTUAL spend, by email. Billing data lags ~a day (CE granularity) — the
# in-run tripwire is the eval report's Athena planning-time panel; this
# catches anything that slips past it within ~a day instead of an invoice.
#
# NOTE: account-wide CE anomaly detection already exists outside terraform
# (Default-Services-Monitor + a DAILY email subscription — an account allows
# only ONE dimensional monitor, so it is deliberately NOT managed here).
# ---------------------------------------------------------------------------

resource "aws_budgets_budget" "s3_daily" {
  name         = "${var.project_name}-${var.environment}-s3-daily-requests"
  budget_type  = "COST"
  limit_amount = "5.0"
  limit_unit   = "USD"
  time_unit    = "DAILY"

  cost_filter {
    name   = "Service"
    values = ["Amazon Simple Storage Service"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}

# Stage 5 (public exposure): the real runaway risk is authenticated turns burning Bedrock $ (open Google
# signup). A DAILY Bedrock budget alerts at 100% FORECASTED (early warning) + 100% ACTUAL. Budgets lag ~a
# day, so this is the backstop; WAF rate-limiting + the per-user turn cap are the real-time controls, and
# the manual SG kill-switch (public_ingress=false) is the incident lever.
resource "aws_budgets_budget" "bedrock_daily" {
  name         = "${var.project_name}-${var.environment}-bedrock-daily"
  budget_type  = "COST"
  limit_amount = tostring(var.bedrock_daily_limit)
  limit_unit   = "USD"
  time_unit    = "DAILY"

  cost_filter {
    name   = "Service"
    values = ["Amazon Bedrock"]
  }

  # DAILY budgets only support ACTUAL notifications (AWS constraint). Alert at 80% and 100% of the day's cap.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}
