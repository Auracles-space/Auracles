# Application Load Balancer: the single public entry point of an environment.
#
# Everything inbound — browsers, and the Stripe/Paystack/Persona webhooks —
# crosses this ALB or is dropped. HTTP exists only to 301 to HTTPS; the app
# never sees a cleartext request.

resource "aws_lb" "this" {
  name               = "auracles-${var.environment}"
  load_balancer_type = "application"
  security_groups    = [var.security_group_id]
  subnets            = var.public_subnet_ids

  # Ephemeral staging must destroy unattended; production flips this on.
  enable_deletion_protection = var.environment == "production"

  tags = {
    Name = "auracles-${var.environment}"
  }
}

resource "aws_lb_target_group" "api" {
  name        = "auracles-${var.environment}-api"
  port        = var.api_container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip" # Fargate tasks register by IP, not instance

  # /health pings the DB and Redis, so a passing check means the task is
  # actually serviceable, not merely running.
  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # Long enough for an in-flight download-URL mint or webhook write to finish
  # when a deploy drains the old task; short enough not to stall deploys.
  deregistration_delay = 30

  tags = {
    Name = "auracles-${var.environment}-api"
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  # Current AWS-recommended TLS policy floor; TLS 1.3 with 1.2 fallback.
  ssl_policy      = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
