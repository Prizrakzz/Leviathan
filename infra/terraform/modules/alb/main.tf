# ---------------------------------------------------------------------------
# Application Load Balancer for the GraphRAG serving API (Phase 4.1).
#
# The ALB is load-bearing for a specific reason, not scale: our SSE turns run
# 30-90s and API Gateway caps integration at ~30s (it would sever every turn).
# The ALB idle timeout is configurable into the thousands of seconds and passes
# streaming through, so it is what keeps the long turns alive. It also gives the
# stable HTTPS endpoint (Stage 4), health-based task replacement, and the WAF
# attach point.
#
# Stage 1 (private validation): HTTP:80 listener, SG inbound LOCKED to admin_cidrs
# (your IP) so nothing is world-reachable before Cognito + HTTPS (Stage 4).
# ---------------------------------------------------------------------------

locals {
  name = "${var.project_name}-${var.environment}-serving"

  # Which client ports the ALB accepts. HTTPS adds 443; :80 stays open (it only serves the 301 redirect).
  ingress_ports = var.enable_https ? [80, 443] : [var.listener_port]

  # Stage 5: public_ingress opens the world; otherwise IP-locked to admin_cidrs.
  ingress_cidrs = var.public_ingress ? ["0.0.0.0/0"] : var.admin_cidrs
}

resource "aws_security_group" "alb" {
  name = "${local.name}-alb"
  # NOTE: description is immutable — changing it forces SG replacement, which would orphan the ECS task
  # SG's ingress reference to this SG's id. Keep it as-is; ingress rules below still change in-place.
  description = "GraphRAG serving ALB: inbound only from admin_cidrs (Stage 1) / world (Stage 4)."
  vpc_id      = var.vpc_id

  dynamic "ingress" {
    for_each = toset(local.ingress_ports)
    content {
      description = "Client to ALB on ${ingress.value}"
      from_port   = ingress.value
      to_port     = ingress.value
      protocol    = "tcp"
      cidr_blocks = local.ingress_cidrs
    }
  }

  egress {
    description = "ALB to targets (and anywhere)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name        = "${local.name}-alb"
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

resource "aws_lb" "this" {
  name               = "${local.name}-alb"
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.subnet_ids
  idle_timeout       = var.idle_timeout

  # Serving turns are long and idempotent; keep the LB simple + resilient.
  drop_invalid_header_fields = true

  tags = merge(var.tags, {
    Name        = "${local.name}-alb"
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

resource "aws_lb_target_group" "this" {
  name        = "${local.name}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip" # Fargate awsvpc tasks register by IP

  # BGE reranker + graph load on cold start; give tasks time before draining.
  deregistration_delay = 30

  health_check {
    path                = var.health_check_path
    port                = "traffic-port"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

resource "aws_lb_listener" "this" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  # HTTPS on -> :80 becomes a 301 redirect to 443. HTTPS off (Stage 1) -> plain forward.
  dynamic "default_action" {
    for_each = var.enable_https ? [1] : []
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
    for_each = var.enable_https ? [] : [1]
    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.this.arn
    }
  }

  tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

# HTTPS:443 — terminates TLS with the ACM cert, forwards HTTP to the uvicorn target group.
resource "aws_lb_listener" "https" {
  count             = var.enable_https ? 1 : 0
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }

  tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}
