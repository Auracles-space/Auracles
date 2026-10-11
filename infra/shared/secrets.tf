# Human-entered secret SHELLS for staging. Terraform creates the ARN so task
# definitions can reference it, and never knows the value — fill each once:
#
#   aws secretsmanager put-secret-value \
#     --secret-id auracles/staging/STRIPE_SECRET_KEY --secret-string '...'
#
# They live in the shared stack, not the staging stack, for one reason:
# staging is destroyed at the end of every QA cycle, and hand-entered values
# must survive that. (The composed DATABASE_URL/REDIS_URL secrets correctly
# live in staging — they are regenerated from the fresh RDS/Redis each cycle.)
#
# A task referencing a shell with no value fails to start with a
# ResourceInitializationError naming the secret — loud, not subtle.

locals {
  secret_names = [
    "SECRET_KEY",
    "TOTP_ENCRYPTION_KEY",
    "PAYOUT_ACCOUNT_ENCRYPTION_KEY",
    "PARTNER_WEBHOOK_ENCRYPTION_KEY",
    "CONNECTOR_TOKEN_ENCRYPTION_KEY",
    "RESEND_API_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "PAYSTACK_SECRET_KEY",
    "PERSONA_API_KEY",
    "PERSONA_WEBHOOK_SECRET",
    "GOOGLE_CLIENT_SECRET",
    "BRAVE_SEARCH_API_KEY",
    # Password for the bootstrap admin account, consumed by
    # scripts.bootstrap_admin on a fresh database. It has to reach the task
    # definition rather than a run-task override, because ECS overrides can
    # inject plain environment values but not Secrets Manager references — and
    # passing a password as an override would put it in CloudTrail.
    "ADMIN_PASSWORD",
  ]
}

resource "aws_secretsmanager_secret" "staging" {
  for_each = toset(local.secret_names)

  name = "auracles/staging/${each.key}"
  # 7-day recovery, unlike staging's composed secrets: these hold values a
  # human typed, and an accidental shared-stack destroy should be recoverable.
  recovery_window_in_days = 7

  tags = {
    Name = "auracles/staging/${each.key}"
  }
}

resource "aws_secretsmanager_secret" "production" {
  for_each = toset(local.secret_names)

  name = "auracles/production/${each.key}"
  # 7-day recovery, like staging's hand-entered shells. These hold live
  # provider keys and freshly generated encryption keys, so an accidental
  # shared-stack destroy must be recoverable rather than final.
  recovery_window_in_days = 7

  tags = {
    Name = "auracles/production/${each.key}"
  }
}

output "production_secret_arns" {
  description = "name => ARN for the production task definitions' secret references. Terraform creates the shells and never knows the values; fill each once with `aws secretsmanager put-secret-value`."
  value       = { for name, secret in aws_secretsmanager_secret.production : name => secret.arn }
}

output "staging_secret_arns" {
  description = "name => ARN for the staging task definitions' secret references."
  value       = { for name, secret in aws_secretsmanager_secret.staging : name => secret.arn }
}


# ---------------------------------------------------------------------------
# INTERNAL_API_SECRET — generated here, not hand-entered.
#
# It proves a request came from our own server-side renderer, which earns that
# renderer a separate rate-limit bucket and nothing else. It is needed because
# every SSR render reaches the API from the frontend host, so per-IP limiting
# cannot tell one visitor's page load from another's: GPTBot crawling
# /explore's filter facets drained the shared bucket on 2026-10-11 and real
# visitors were shown "Catalog is temporarily unavailable".
#
# Unlike every secret above, Terraform owns this value. Two reasons:
#
#   1. Both halves must present the same string, and the API and Amplify read
#      it from different stacks. A hand-entered value is a value somebody
#      pastes twice, and a mismatch fails silently — the renderer simply drops
#      back to the public bucket, which is the incident this exists to prevent.
#   2. A hand-entered shell cannot be read in the same apply that creates it,
#      because `aws_secretsmanager_secret_version` as a *data* source needs a
#      version that does not exist yet. Generating the value removes that
#      ordering trap rather than documenting it.
#
# The value therefore lives in Terraform state. That is acceptable precisely
# because it grants a rate-limit bucket and no data access — do not reuse this
# pattern for a credential that authorizes anything.
# ---------------------------------------------------------------------------

resource "random_password" "internal_api_secret" {
  length = 48
  # Alphanumeric only: it travels as an HTTP header value and through an
  # Amplify environment variable, so punctuation buys nothing and risks
  # quoting surprises in either.
  special = false
}

resource "aws_secretsmanager_secret" "internal_api" {
  for_each = toset(["staging", "production"])

  name                    = "auracles/${each.key}/INTERNAL_API_SECRET"
  recovery_window_in_days = 7

  tags = {
    Name = "auracles/${each.key}/INTERNAL_API_SECRET"
  }
}

resource "aws_secretsmanager_secret_version" "internal_api" {
  for_each = aws_secretsmanager_secret.internal_api

  secret_id     = each.value.id
  secret_string = random_password.internal_api_secret.result
}

output "internal_api_secret_arns" {
  description = "environment => ARN of the generated internal-caller secret, for the task definitions."
  value       = { for env, secret in aws_secretsmanager_secret.internal_api : env => secret.arn }
}
