# Staging environment. Grows slice by slice in the cutover order:
# networking (this slice) → RDS + ElastiCache → ECS + ALB → DNS records.
#
# Reads the shared stack's outputs (zone, certificate, ECR) through
# terraform_remote_state rather than data lookups by name, so the wiring
# breaks loudly at plan time if shared/ has not been applied yet.

data "terraform_remote_state" "shared" {
  backend = "s3"

  config = {
    bucket = var.state_bucket
    key    = "shared/terraform.tfstate"
    region = var.aws_region
  }
}

data "aws_caller_identity" "current" {}

module "networking" {
  source = "../../modules/networking"

  environment = "staging"
  vpc_cidr    = var.vpc_cidr
}

module "rds" {
  source = "../../modules/rds"

  environment        = "staging"
  private_subnet_ids = module.networking.private_subnet_ids
  security_group_id  = module.networking.rds_security_group_id

  # Ephemeral: destroy must succeed unattended, and a staging goodbye
  # snapshot is QA leftovers nobody will restore.
  deletion_protection   = false
  skip_final_snapshot   = true
  backup_retention_days = 0
}

module "redis" {
  source = "../../modules/redis"

  environment        = "staging"
  private_subnet_ids = module.networking.private_subnet_ids
  security_group_id  = module.networking.redis_security_group_id
}

module "s3" {
  source = "../../modules/s3"

  environment   = "staging"
  account_id    = data.aws_caller_identity.current.account_id
  force_destroy = true
  cors_allowed_origins = [
    "https://staging.auracles.space",
  ]
}

# ---------------------------------------------------------------------------
# Composed connection secrets. The application reads DATABASE_URL and
# REDIS_URL whole, so the URLs are assembled here — from module outputs the
# moment they exist — and stored in Secrets Manager for the ECS task
# definitions to reference by ARN. Human-entered secrets (Stripe, Paystack,
# Resend, ...) are NOT created here; they are made by hand once and looked up
# by the ECS slice, per the design doc.
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "database_url" {
  name = "auracles/staging/DATABASE_URL"
  # Ephemeral staging recreates this next cycle; the default 30-day
  # deletion window would make the name collide with its own ghost.
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  secret_string = format(
    "postgresql+asyncpg://%s:%s@%s/%s",
    module.rds.master_username,
    module.rds.master_password,
    module.rds.endpoint,
    module.rds.database_name,
  )
}

resource "aws_secretsmanager_secret" "redis_url" {
  name                    = "auracles/staging/REDIS_URL"
  recovery_window_in_days = 0
}

# Human-entered secrets (Stripe, Paystack, Resend, ...) are NOT here: their
# shells live in the SHARED stack, because these are filled by hand once and
# must survive the destroy that ends every staging cycle. Their ARNs arrive
# through the shared remote state below.

# ---------------------------------------------------------------------------
# Compute and edge.
# ---------------------------------------------------------------------------

module "alb" {
  source = "../../modules/alb"

  environment       = "staging"
  vpc_id            = module.networking.vpc_id
  public_subnet_ids = module.networking.public_subnet_ids
  security_group_id = module.networking.alb_security_group_id
  certificate_arn   = data.terraform_remote_state.shared.outputs.staging_certificate_arn
}

module "ecs" {
  source = "../../modules/ecs"

  environment = "staging"
  aws_region  = var.aws_region

  # Tag convention: the image pushed for staging QA carries the :staging tag.
  # Push before staging-up or all three services crash-loop on image pull.
  backend_image = "${data.terraform_remote_state.shared.outputs.ecr_backend_repository_url}:staging"

  public_subnet_ids        = module.networking.public_subnet_ids
  api_security_group_id    = module.networking.api_task_security_group_id
  worker_security_group_id = module.networking.worker_task_security_group_id
  beat_security_group_id   = module.networking.beat_task_security_group_id
  target_group_arn         = module.alb.target_group_arn

  s3_bucket_names = [
    module.s3.artifacts_bucket,
    module.s3.avatars_bucket,
    module.s3.reports_bucket,
    module.s3.thumbnails_bucket,
  ]

  environment_variables = {
    ENVIRONMENT          = "staging"
    LOG_FORMAT           = "json"
    AWS_DEFAULT_REGION   = var.aws_region
    CORS_ALLOWED_ORIGINS = "https://staging.auracles.space"
    TRUST_PROXY_HEADERS  = "true"
    S3_ARTIFACTS_BUCKET  = module.s3.artifacts_bucket
    S3_AVATARS_BUCKET    = module.s3.avatars_bucket
    S3_REPORTS_BUCKET    = module.s3.reports_bucket
    S3_THUMBNAILS_BUCKET = module.s3.thumbnails_bucket
    CLAMAV_HOST          = "localhost"
    CLAMAV_PORT          = "3310"
    PLATFORM_CURRENCY    = "NGN"
    # Staging QA must never send real email to seeded addresses; lifecycle
    # emails are logged instead, same as local dev.
    EMAIL_SEND_ENABLED = "false"
  }

  secret_arns = merge(
    data.terraform_remote_state.shared.outputs.staging_secret_arns,
    {
      DATABASE_URL = aws_secretsmanager_secret.database_url.arn
      REDIS_URL    = aws_secretsmanager_secret.redis_url.arn
    },
  )
}

# api.staging.auracles.space → ALB, inside the delegated zone. Recreated
# freely each cycle: the zone persists, the record is ephemeral like the ALB
# it points at, and the wildcard certificate covers the name.
resource "aws_route53_record" "api" {
  zone_id = data.terraform_remote_state.shared.outputs.staging_zone_id
  name    = "api.staging.auracles.space"
  type    = "A"

  alias {
    name                   = module.alb.dns_name
    zone_id                = module.alb.zone_id
    evaluate_target_health = false
  }
}

resource "aws_secretsmanager_secret_version" "redis_url" {
  secret_id = aws_secretsmanager_secret.redis_url.id
  # rediss:// — the cluster only accepts TLS (transit encryption is on), and
  # the app's URL builder carries ssl_cert_reqs for the scheme.
  secret_string = format(
    "rediss://%s:%d/0",
    module.redis.primary_endpoint,
    module.redis.port,
  )
}
