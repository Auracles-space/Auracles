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
