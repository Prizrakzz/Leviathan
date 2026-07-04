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
