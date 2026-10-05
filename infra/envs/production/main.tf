# Production environment.
#
# Identical modules to staging — only flag values differ, which is what keeps
# the two environments honest about each other. Where they diverge, they
# diverge because production holds real money and real user files:
#
#   * RDS refuses API-level deletion and keeps a final snapshot.
#   * The buckets refuse to be emptied by a destroy.
#   * beat runs on-demand rather than Spot, because a reclaimed scheduler
#     silently skips a payout sweep and nothing re-queues a tick.
#   * Schema changes wait for the maintenance window instead of applying
#     immediately (`apply_immediately` is keyed off the environment name in
#     the RDS module).
#
# Reads the shared stack's outputs through terraform_remote_state rather than
# data lookups by name, so the wiring breaks loudly at plan time if shared/ has
# not been applied yet.

data "terraform_remote_state" "shared" {
  backend = "s3"

  config = {
    bucket = var.state_bucket
    key    = "shared/terraform.tfstate"
    region = var.aws_region
  }
}

data "aws_caller_identity" "current" {}

locals {
  # The frontend's public origins. The apex is the product; www redirects to
  # it at Amplify. Both are listed for CORS and for browser-direct S3 uploads,
  # because a presigned PUT is checked against the exact Origin header sent.
  frontend_origins = [
    "https://auracles.space",
    "https://www.auracles.space",
  ]
}

module "networking" {
  source = "../../modules/networking"

  environment = "production"
  vpc_cidr    = var.vpc_cidr
}

module "rds" {
  source = "../../modules/rds"

  environment        = "production"
  private_subnet_ids = module.networking.private_subnet_ids
  security_group_id  = module.networking.rds_security_group_id

  # Single-AZ for the pilot (decision 2026-10-04). A standby only earns its
  # cost once the api is also multi-task across AZs; with one api task in one
  # AZ, an AZ loss would leave a surviving database with nothing to talk to.
  # Flip this together with api desired_count >= 2, not before.
  multi_az       = false
  instance_class = "db.t4g.micro"

  # 14 days rather than the module's 7 (decision 2026-10-04). A data bug on a
  # platform holding escrow, licences and payout records is often noticed days
  # after it landed; 7 days can already be gone by the time anyone looks.
  backup_retention_days = 14

  # The two that make a mistaken destroy survivable.
  deletion_protection = true
  skip_final_snapshot = false
}

module "redis" {
  source = "../../modules/redis"

  environment        = "production"
  private_subnet_ids = module.networking.private_subnet_ids
  security_group_id  = module.networking.redis_security_group_id
}

module "s3" {
  source = "../../modules/s3"

  environment = "production"
  account_id  = data.aws_caller_identity.current.account_id

  # A destroy that would lose real user artifacts must fail instead.
  force_destroy = false

  cors_allowed_origins = local.frontend_origins
}

# ---------------------------------------------------------------------------
# Composed connection secrets. The application reads DATABASE_URL and
# REDIS_URL whole, so the URLs are assembled here from module outputs and
# stored in Secrets Manager for the task definitions to reference by ARN.
#
# Human-entered secrets (Stripe, Paystack, Resend, ...) are NOT here: their
# shells live in the SHARED stack, filled once by hand, and arrive through the
# remote state below.
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "database_url" {
  name = "auracles/production/DATABASE_URL"
  # 7 days, unlike staging's 0. Staging recreates this every cycle, so a
  # recovery window would make the name collide with its own ghost. Production
  # is never torn down on purpose, so if this secret is ever deleted it was a
  # mistake and should be recoverable.
  recovery_window_in_days = 7

  tags = {
    Name = "auracles/production/DATABASE_URL"
  }
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
  name                    = "auracles/production/REDIS_URL"
  recovery_window_in_days = 7

  tags = {
    Name = "auracles/production/REDIS_URL"
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

# ---------------------------------------------------------------------------
# Compute and edge.
# ---------------------------------------------------------------------------

module "alb" {
  source = "../../modules/alb"

  environment       = "production"
  account_id        = data.aws_caller_identity.current.account_id
  vpc_id            = module.networking.vpc_id
  public_subnet_ids = module.networking.public_subnet_ids
  security_group_id = module.networking.alb_security_group_id

  # The certificate issued in the shared stack for api.auracles.space and its
  # wildcard. Deletion protection on the load balancer itself is keyed off the
  # environment name inside the module.
  certificate_arn = data.terraform_remote_state.shared.outputs.production_api_certificate_arn
}

module "monitoring" {
  source = "../../modules/monitoring"

  environment      = "production"
  alerts_topic_arn = data.terraform_remote_state.shared.outputs.alerts_topic_arn

  # Worker and beat only, same reasoning as staging: FastAPI prints a traceback
  # for any unhandled 500, so an api log filter would fire on ordinary
  # application bugs and train everyone to ignore the alarm. The api is covered
  # by the ALB's unhealthy-target and 5xx alarms instead, which are real
  # signals rather than a stack trace.
  watched_log_groups = {
    for name, group in module.ecs.log_group_names : name => group
    if name != "api"
  }

  # Every service, api included: "running no tasks" is unambiguous.
  cluster_name     = module.ecs.cluster_name
  watched_services = toset(keys(module.ecs.log_group_names))

  alb_arn_suffix              = module.alb.arn_suffix
  api_target_group_arn_suffix = module.alb.target_group_arn_suffix
}

module "ecs" {
  source = "../../modules/ecs"

  environment = "production"
  aws_region  = var.aws_region

  # The :production tag, which release.yml re-points at the sha-<commit> image
  # that main's build already produced. Production therefore runs the exact
  # bytes QA passed on staging, not a fresh compile that might differ. The tag
  # must exist before the first apply or all three services crash-loop on image
  # pull — `make prod-promote-image` puts it there.
  backend_image = "${data.terraform_remote_state.shared.outputs.ecr_backend_repository_url}:production"

  public_subnet_ids        = module.networking.public_subnet_ids
  api_security_group_id    = module.networking.api_task_security_group_id
  worker_security_group_id = module.networking.worker_task_security_group_id
  beat_security_group_id   = module.networking.beat_task_security_group_id
  target_group_arn         = module.alb.target_group_arn

  # Capacity split (decision 2026-10-04). A reclaimed worker returns its
  # Celery job to the queue and it reruns; a reclaimed beat skips whatever was
  # due, because nothing queues a tick that never fired and beat is the only
  # scheduler there is.
  worker_use_spot = true
  beat_use_spot   = false

  s3_bucket_names = [
    module.s3.artifacts_bucket,
    module.s3.avatars_bucket,
    module.s3.reports_bucket,
    module.s3.thumbnails_bucket,
  ]

  # Only these two are erased from; avatars and thumbnails are overwritten.
  s3_delete_bucket_names = [
    module.s3.artifacts_bucket,
    module.s3.reports_bucket,
  ]

  environment_variables = {
    ENVIRONMENT          = "production"
    LOG_FORMAT           = "json"
    AWS_DEFAULT_REGION   = var.aws_region
    CORS_ALLOWED_ORIGINS = join(",", local.frontend_origins)

    # Not optional. The API sits behind an ALB, so without this every per-IP
    # rate limit keys on the load balancer's address and collapses into one
    # bucket that protects nothing.
    TRUST_PROXY_HEADERS = "true"

    S3_ARTIFACTS_BUCKET  = module.s3.artifacts_bucket
    S3_AVATARS_BUCKET    = module.s3.avatars_bucket
    S3_REPORTS_BUCKET    = module.s3.reports_bucket
    S3_THUMBNAILS_BUCKET = module.s3.thumbnails_bucket

    CLAMAV_HOST = "localhost"
    CLAMAV_PORT = "3310"

    # Naira is the primary rail; select_provider sends every NGN transaction to
    # Paystack. Stripe stays integrated but carries no pilot traffic.
    PLATFORM_CURRENCY = "NGN"

    # Identity of the bootstrap admin, consumed by `make prod-bootstrap-admin`.
    # Its password is a Secrets Manager value, never set here. This mailbox
    # must actually receive mail — it is the password-reset path for the only
    # account that exists on day one.
    ADMIN_EMAIL = "dev@auracles.space"

    EMAIL_SEND_ENABLED = "true"

    # Explicit rather than relying on the default, because the alternative
    # runs real identity checks on real people. Persona is shelved (2026-09-06)
    # and admin document review is the live path, so no PERSONA_* config
    # appears in this stack at all.
    KYC_PROVIDER = "manual"

    # Google OAuth. These must match the "Authorized redirect URI" entries in
    # the Google console byte for byte — Google compares the string, not the
    # URL, so a trailing slash is a rejected login. Both point at the FRONTEND:
    # the callback sets host-only auth cookies, and a cookie set by the API
    # origin is invisible to the frontend's. The frontend proxies /api/*
    # through to the backend, keeping it same-origin.
    GOOGLE_REDIRECT_URI       = "https://auracles.space/api/v1/auth/google/callback"
    GOOGLE_DRIVE_REDIRECT_URI = "https://auracles.space/api/v1/integrations/connectors/google-drive/callback"

    # Reusing staging's OAuth client (human decision 2026-10-05). One client
    # holds several redirect URIs, so localhost, staging and production
    # coexist. The accepted cost: a misconfiguration on that client affects
    # real sign-ins too. A client id is an identifier that ships in every
    # OAuth URL the browser follows, not a credential; its partner
    # GOOGLE_CLIENT_SECRET is a real secret and arrives through the ARNs below.
    GOOGLE_CLIENT_ID = "464831374479-pu58s3c71o2bmjrhtk2pe1orsca3q2hu.apps.googleusercontent.com"
  }

  secret_arns = merge(
    data.terraform_remote_state.shared.outputs.production_secret_arns,
    {
      DATABASE_URL = aws_secretsmanager_secret.database_url.arn
      REDIS_URL    = aws_secretsmanager_secret.redis_url.arn
    },
  )
}

# api.auracles.space → ALB, at the apex of the delegated zone. Terraform owns
# this record, so if the load balancer is ever rebuilt the address follows
# without anyone editing DNS by hand.
resource "aws_route53_record" "api" {
  zone_id = data.terraform_remote_state.shared.outputs.production_api_zone_id
  name    = data.terraform_remote_state.shared.outputs.production_api_domain
  type    = "A"

  alias {
    name                   = module.alb.dns_name
    zone_id                = module.alb.zone_id
    evaluate_target_health = false
  }
}
