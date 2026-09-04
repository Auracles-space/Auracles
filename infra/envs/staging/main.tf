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
    # Identity of the bootstrap admin. The matching password is a secret; this
    # half is just an address. Used by `make staging-bootstrap-admin`.
    ADMIN_EMAIL = "dev@auracles.space"
    # Real sending on (human decision 2026-09-02) so registration/verification
    # can be tested end to end with real inboxes. Caveat, accepted: the E2E
    # seeds use invented addresses, and bounces count against the domain's
    # sender reputation — flip to "false" before running the full automated
    # suite. Requires a real RESEND_API_KEY value in Secrets Manager.
    EMAIL_SEND_ENABLED = "true"
    # EMAIL_ASSET_BASE_URL is deliberately absent. It existed only while
    # staging had no frontend and email images had to load from the live apex.
    # staging.auracles.space now serves /images/* itself (verified 2026-09-04),
    # so images and action links both come from the staging origin, which is
    # what production will do too — one less way staging and production differ.
    # Persona hosted-flow config. The template id is an identifier, not a
    # credential — changing templates later is an edit here + apply. The
    # redirect points at the staging frontend's KYC page; the page not
    # existing yet only means Persona lands users on a 404 after verifying,
    # which is cosmetic until the staging frontend is up.
    PERSONA_INQUIRY_TEMPLATE_ID = "itmpl_AS7SnZZrGnYx7CrsGbuNvddFbqbD7Q"
    PERSONA_REDIRECT_URL        = "https://staging.auracles.space/settings/kyc"
    # Google OAuth. These two must match the "Authorized redirect URI" entries
    # in the Google Cloud console byte for byte — Google compares the string,
    # not the URL, so a trailing slash or a different host is a rejected login.
    # Both point at the FRONTEND: the callback sets host-only auth cookies, and
    # a cookie set by the API origin is invisible to the frontend's. The
    # frontend proxies /api/* through to the backend, keeping it same-origin.
    # See docs/external-endpoints.md.
    GOOGLE_REDIRECT_URI       = "https://staging.auracles.space/api/v1/auth/google/callback"
    GOOGLE_DRIVE_REDIRECT_URI = "https://staging.auracles.space/api/v1/integrations/connectors/google-drive/callback"
    # In plain sight deliberately: a client id is an identifier that ships in
    # every OAuth URL the browser follows, not a credential. Its partner
    # GOOGLE_CLIENT_SECRET is a real secret, lives in Secrets Manager, and
    # arrives through staging_secret_arns below.
    #
    # This is the same OAuth client local dev uses. Reusing one client across
    # environments is fine — a client holds a list of authorized redirect URIs,
    # so localhost and staging coexist. Production should get its own client,
    # so that a staging misconfiguration cannot affect real sign-ins.
    GOOGLE_CLIENT_ID = "464831374479-pu58s3c71o2bmjrhtk2pe1orsca3q2hu.apps.googleusercontent.com"
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
