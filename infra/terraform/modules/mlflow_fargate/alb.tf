# ---------------------------------------------------------------------------
# Problem 2 -- internet-facing authenticated endpoint for the MLflow UI.
#
# mlflow.leviathan.local:5000 (Cloud Map, main.tf) is private DNS -- not browser
# reachable. This file adds an internet-facing ALB so the user opens
# https://<mlflow_subdomain>.<public_domain> in a browser, authenticates against
# the EXISTING Cognito user pool (same Google sign-in as the serving app), and is
# then forwarded to the MLflow task on 5000.
#
# Reuses existing infra: the serving *.<domain> wildcard ACM cert, the public
# Route53 zone, and the Cognito user pool (a dedicated ALB app client is minted).
#
# Kill-switch: var.mlflow_public_https=false swaps the HTTPS:443 + Cognito default
# action for a plain HTTP:80 forward, and locks the ALB SG to var.mlflow_admin_cidrs
# (the documented fallback for a missing HTTPS/Cognito fact).
# ---------------------------------------------------------------------------

locals {
  alb_fqdn = "${var.mlflow_subdomain}.${var.public_domain}"

  # HTTPS path opens 80 (301 redirect) + 443 to the world (Cognito gates). Fallback opens only 80,
  # locked to the admin allow-list.
  alb_ingress_ports = var.mlflow_public_https ? [80, 443] : [80]
  alb_ingress_cidrs = var.mlflow_public_https ? ["0.0.0.0/0"] : var.mlflow_admin_cidrs
}

# ---------------------------------------------------------------------------
# ALB security group. HTTPS path: 80+443 from the world. Fallback: 80 from admin CIDRs only.
# ---------------------------------------------------------------------------
resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "MLflow ALB: 80+443 from the world (Cognito-gated) or 80 from admin CIDRs (fallback)."
  vpc_id      = var.vpc_id

  dynamic "ingress" {
    for_each = toset(local.alb_ingress_ports)
    content {
      description = "Client to MLflow ALB on ${ingress.value}"
      from_port   = ingress.value
      to_port     = ingress.value
      protocol    = "tcp"
      cidr_blocks = local.alb_ingress_cidrs
    }
  }

  egress {
    description = "ALB to the MLflow task (and anywhere)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.name}-alb" })
}

# The task SG (main.tf) already admits 5000 from the whole VPC CIDR (in-VPC training jobs). Add an
# explicit ALB-SG -> task rule on 5000 so the ALB path holds even if the VPC-CIDR rule is ever tightened.
resource "aws_security_group_rule" "task_from_alb" {
  type                     = "ingress"
  description              = "MLflow ALB to task on the tracking port"
  security_group_id        = aws_security_group.task.id
  source_security_group_id = aws_security_group.alb.id
  from_port                = var.container_port
  to_port                  = var.container_port
  protocol                 = "tcp"
}

# ---------------------------------------------------------------------------
# Internet-facing ALB + target group (target_type ip; Fargate awsvpc tasks register by IP).
# ---------------------------------------------------------------------------
resource "aws_lb" "this" {
  name               = "${local.name}-alb"
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.subnet_ids
  idle_timeout       = 300

  drop_invalid_header_fields = true

  tags = merge(local.common_tags, { Name = "${local.name}-alb" })
}

resource "aws_lb_target_group" "this" {
  name        = "${local.name}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  deregistration_delay = 30

  # MLflow exposes GET /health -> 200 "OK".
  health_check {
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# Dedicated Cognito app client for the ALB (authenticate-cognito). Confidential
# (generate_secret) as the ALB Cognito integration requires; the SPA client is
# untouched. Callback is the ALB-reserved /oauth2/idpresponse path.
# ---------------------------------------------------------------------------
resource "aws_cognito_user_pool_client" "alb" {
  count        = var.mlflow_public_https ? 1 : 0
  name         = "${local.name}-alb"
  user_pool_id = var.cognito_user_pool_id

  generate_secret = true # ALB authenticate-cognito uses a confidential client (secret kept ALB-side)

  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["Google"] # same federated Google sign-in as the serving app

  callback_urls = ["https://${local.alb_fqdn}/oauth2/idpresponse"]
  logout_urls   = ["https://${local.alb_fqdn}"]

  explicit_auth_flows           = ["ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED"
}

# ---------------------------------------------------------------------------
# Listeners.
#   HTTPS path: :80 -> 301 to :443; :443 terminates TLS, authenticate-cognito, then forwards.
#   Fallback:   :80 forwards straight to the target group (SG already locks it to admin CIDRs).
# ---------------------------------------------------------------------------
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  dynamic "default_action" {
    for_each = var.mlflow_public_https ? [1] : []
    content {
      type = "redirect"
      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }

  dynamic "default_action" {
    for_each = var.mlflow_public_https ? [] : [1]
    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.this.arn
    }
  }

  tags = local.common_tags
}

resource "aws_lb_listener" "https" {
  count             = var.mlflow_public_https ? 1 : 0
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  # Action 1: force Cognito auth (redirects an unauthenticated browser to the hosted Google login).
  default_action {
    type  = "authenticate-cognito"
    order = 1

    authenticate_cognito {
      user_pool_arn              = var.cognito_user_pool_arn
      user_pool_client_id        = aws_cognito_user_pool_client.alb[0].id
      user_pool_domain           = var.cognito_user_pool_domain
      on_unauthenticated_request = "authenticate"
      scope                      = "openid"
      session_timeout            = 3600
    }
  }

  # Action 2: once authenticated, forward to the MLflow task.
  default_action {
    type             = "forward"
    order            = 2
    target_group_arn = aws_lb_target_group.this.arn
  }

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# Route53 alias: <mlflow_subdomain>.<public_domain> -> the ALB.
# ---------------------------------------------------------------------------
resource "aws_route53_record" "mlflow" {
  zone_id = var.public_zone_id
  name    = local.alb_fqdn
  type    = "A"

  alias {
    name                   = aws_lb.this.dns_name
    zone_id                = aws_lb.this.zone_id
    evaluate_target_health = true
  }
}
