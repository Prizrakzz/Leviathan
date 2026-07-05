# ---------------------------------------------------------------------------
# AWS WAFv2 on the serving ALB (Phase 5, public exposure). REGIONAL scope.
#
# The load-bearing rule is the rate-based rule SCOPED to /v1/respond* — each such
# request is a 30-90s Bedrock turn (real $), so per-IP velocity there is the money
# control. A separate global rate rule stops volumetric floods; AWS managed groups
# cover common exploits / bad inputs / bad-reputation IPs.
#
# COUNT-FIRST: ship with blocking_enabled=false (managed groups in count-override,
# rate rules in count action) so real traffic — including the SSE keepalive/reconnect
# pattern — is observed for 24-48h before flipping to block. Flip = blocking_enabled=true.
# ---------------------------------------------------------------------------

locals {
  name = "${var.project_name}-${var.environment}-serving"
}

resource "aws_wafv2_web_acl" "this" {
  name        = local.name
  description = "Serving ALB WAF - managed groups plus rate limits on the respond routes"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # --- AWS managed rule groups (block their own findings only when blocking_enabled) ---
  rule {
    name     = "AWSCommon"
    priority = 1
    dynamic "override_action" {
      for_each = var.blocking_enabled ? [] : [1]
      content {
        count {}
      }
    }
    dynamic "override_action" {
      for_each = var.blocking_enabled ? [1] : []
      content {
        none {}
      }
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSBadInputs"
    priority = 2
    dynamic "override_action" {
      for_each = var.blocking_enabled ? [] : [1]
      content {
        count {}
      }
    }
    dynamic "override_action" {
      for_each = var.blocking_enabled ? [1] : []
      content {
        none {}
      }
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-badinputs"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSIPReputation"
    priority = 3
    dynamic "override_action" {
      for_each = var.blocking_enabled ? [] : [1]
      content {
        count {}
      }
    }
    dynamic "override_action" {
      for_each = var.blocking_enabled ? [1] : []
      content {
        none {}
      }
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-ipreput"
      sampled_requests_enabled   = true
    }
  }

  # --- rate limit scoped to /v1/respond* (the expensive Bedrock turns) ---
  rule {
    name     = "RespondRateLimit"
    priority = 10
    dynamic "action" {
      for_each = var.blocking_enabled ? [] : [1]
      content {
        count {}
      }
    }
    dynamic "action" {
      for_each = var.blocking_enabled ? [1] : []
      content {
        block {}
      }
    }
    statement {
      rate_based_statement {
        limit                 = var.respond_rate_limit
        aggregate_key_type    = "IP"
        evaluation_window_sec = 300
        scope_down_statement {
          byte_match_statement {
            search_string         = "/v1/respond"
            positional_constraint = "STARTS_WITH"
            field_to_match {
              uri_path {}
            }
            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-respond-rate"
      sampled_requests_enabled   = true
    }
  }

  # --- global volumetric flood guard (all paths) ---
  rule {
    name     = "GlobalRateLimit"
    priority = 20
    dynamic "action" {
      for_each = var.blocking_enabled ? [] : [1]
      content {
        count {}
      }
    }
    dynamic "action" {
      for_each = var.blocking_enabled ? [1] : []
      content {
        block {}
      }
    }
    statement {
      rate_based_statement {
        limit                 = var.global_rate_limit
        aggregate_key_type    = "IP"
        evaluation_window_sec = 300
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-global-rate"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name}-waf"
    sampled_requests_enabled   = true
  }

  tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_wafv2_web_acl_association" "this" {
  resource_arn = var.alb_arn
  web_acl_arn  = aws_wafv2_web_acl.this.arn
}

# WAF logging -> CloudWatch (log group name MUST start with aws-waf-logs-).
resource "aws_cloudwatch_log_group" "waf" {
  name              = "aws-waf-logs-${local.name}"
  retention_in_days = 30
  tags              = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
}

resource "aws_wafv2_web_acl_logging_configuration" "this" {
  resource_arn            = aws_wafv2_web_acl.this.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]
}
