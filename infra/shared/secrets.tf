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
  staging_secret_names = [
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
  for_each = toset(local.staging_secret_names)

  name = "auracles/staging/${each.key}"
  # 7-day recovery, unlike staging's composed secrets: these hold values a
  # human typed, and an accidental shared-stack destroy should be recoverable.
  recovery_window_in_days = 7

  tags = {
    Name = "auracles/staging/${each.key}"
  }
}

output "staging_secret_arns" {
  description = "name => ARN for the staging task definitions' secret references."
  value       = { for name, secret in aws_secretsmanager_secret.staging : name => secret.arn }
}
