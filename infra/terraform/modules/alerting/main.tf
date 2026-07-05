# ---------------------------------------------------------------------------
# Alerting fan-out (Phase 5, public exposure). One SNS topic every alarm target
# consumes — CloudWatch serving alarms, WAF, future modules. Email subscription
# must be CONFIRMED (click the link) before alarms are trustworthy.
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-${var.environment}-alerts"
  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
