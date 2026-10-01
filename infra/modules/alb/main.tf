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

  access_logs {
    bucket  = aws_s3_bucket.access_logs.id
    prefix  = "alb"
    enabled = true
  }

  tags = {
    Name = "auracles-${var.environment}"
  }

  # Without this the load balancer can come up before the bucket will accept
  # writes, and logging silently stays off until something touches it again.
  depends_on = [aws_s3_bucket_policy.access_logs]
}

resource "aws_lb_target_group" "api" {
  name        = "auracles-${var.environment}-api"
  port        = var.api_container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip" # Fargate tasks register by IP, not instance

  # The health endpoint pings the DB and Redis, so a passing check means the
  # task is actually serviceable, not merely running. The path is /v1/health —
  # main.py mounts the health router under the /v1 prefix; CLAUDE.md's
  # "GET /health" describes the route name, not the mounted path. Getting this
  # wrong is a kill loop: the ALB 404s, declares the task unhealthy, and
  # replaces it forever.
  health_check {
    path                = "/v1/health"
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

# ALB access logs.
#
# Added after staging was found absorbing ~6 requests a second of randomised
# filter traffic against the public Explore search endpoints with no record of
# where it came from: uvicorn sees only the load balancer's private address, and
# nothing else captured the real client or its user agent. A per-IP rate limiter
# now caps any single source, but capping is not identifying.
#
# The bucket lives here rather than in the s3 module because it is part of this
# load balancer's own configuration, not an application bucket the app reads or
# writes. Nothing in the API ever touches it.

resource "aws_s3_bucket" "access_logs" {
  bucket = "auracles-alb-logs-${var.environment}-${var.account_id}"

  # Staging is destroyed and rebuilt routinely, and logs are disposable by
  # design; production keeps the bucket so a destroy cannot silently discard an
  # audit trail mid-incident.
  force_destroy = var.environment != "production"

  tags = {
    Name    = "auracles-alb-logs-${var.environment}"
    Purpose = "alb-access-logs"
  }
}

resource "aws_s3_bucket_public_access_block" "access_logs" {
  bucket                  = aws_s3_bucket.access_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    apply_server_side_encryption_by_default {
      # SSE-S3, not KMS: ALB log delivery cannot use a customer managed key,
      # and silently stops writing rather than erroring if one is required.
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    id     = "expire-access-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = var.access_logs_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# The delivery principal, not the legacy per-region ELB account id: load
# balancers in every current region write as this service, and the account-id
# form is only still needed for pre-2022 regions.
data "aws_iam_policy_document" "access_logs" {
  statement {
    sid    = "AllowALBLogDelivery"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logdelivery.elasticloadbalancing.amazonaws.com"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.access_logs.arn}/*"]

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
  }
}

resource "aws_s3_bucket_policy" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  policy = data.aws_iam_policy_document.access_logs.json

  # The public-access block must exist first: attaching a policy to a bucket
  # whose block is still settling can fail as a public-policy violation.
  depends_on = [aws_s3_bucket_public_access_block.access_logs]
}
