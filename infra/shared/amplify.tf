# Staging frontend. Persistent, like everything else in this stack: Amplify
# bills for build minutes and bytes served rather than for existing, so keeping
# it costs approximately nothing — while recreating it each staging cycle would
# hand out a new URL, and that URL is registered by hand in Google's OAuth
# console and used as Persona's return address.
#
# It serves `main`, so a merge that builds the backend image also refreshes the
# staging frontend. Pointing at a backend that is currently destroyed is
# expected and harmless: pages render, API calls fail until `make staging-up`.

# The frontend's session-hint cookie is signed with the same key the backend
# signs JWTs with. Reading the backend's secret here rather than asking a human
# to paste it twice is deliberate — a mismatch does not error anywhere, it just
# silently treats every visitor as logged out, which is a genuinely hard bug to
# see. The value lands in Terraform state, which is why the state bucket is
# private, versioned, and encrypted.
data "aws_secretsmanager_secret_version" "session_hint" {
  secret_id = aws_secretsmanager_secret.staging["SECRET_KEY"].id
}

module "staging_frontend" {
  source = "../modules/amplify"

  app_name       = "auracles-staging"
  repository_url = "https://github.com/${var.github_repository}"
  branch_name    = "main"
  stage          = "DEVELOPMENT"

  github_access_token = var.github_access_token

  # The repository's own build spec, so the app-level fallback copy stays in
  # step with the file that actually runs.
  build_spec = file("${path.module}/../../amplify.yml")

  environment_variables = {
    # Monorepo: the app is frontend/, not the repository root.
    AMPLIFY_MONOREPO_APP_ROOT = "frontend"

    # Must stay false. When true, Amplify compares the app root against the
    # previous build and skips BOTH build and deploy when it sees no
    # difference — which on a branch that has never deployed means shipping
    # nothing at all and serving Amplify's placeholder page. The waitlist app
    # has it on and this was diagnosed the hard way.
    AMPLIFY_DIFF_DEPLOY = "false"
  }

  branch_environment_variables = {
    # Server-side. amplify.yml must forward these into .env.production or they
    # do not exist at runtime — Amplify exposes env vars to SSR at build time
    # only.
    BACKEND_ORIGIN      = "https://api.staging.auracles.space"
    SESSION_HINT_SECRET = data.aws_secretsmanager_secret_version.session_hint.secret_string

    # Relative on purpose: the browser calls /api/* on the frontend's own
    # origin and next.config.ts rewrites it to BACKEND_ORIGIN, so auth cookies
    # stay first-party. An absolute URL here would make them third-party and
    # silently break login in browsers that block those.
    NEXT_PUBLIC_API_URL = "/api"

    # WebSockets are not proxied — CloudFront does not carry the upgrade — so
    # this one must address the backend directly.
    NEXT_PUBLIC_WS_URL = "wss://api.staging.auracles.space"

    # The whole point of a second app: this one is the real product, not the
    # waitlist. The live waitlist keeps its own app until launch.
    NEXT_PUBLIC_WAITLIST_MODE = "false"

    NEXT_PUBLIC_PLATFORM_CURRENCY = "NGN"

    # Publishable by design — it ships inside the client bundle either way.
    NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY = var.stripe_publishable_key
  }

  # Attaching the domain blocks on certificate validation, so it is a second
  # pass: bring the app up, confirm it builds and serves, then set
  # `staging_frontend_custom_domain = true` and apply again. Once it is live,
  # EMAIL_ASSET_BASE_URL can come out of the staging backend config — the
  # frontend will finally be serving its own images.
  custom_domain = var.staging_frontend_custom_domain ? local.staging_domain : null
}

output "staging_frontend_url" {
  description = "Public URL of the staging frontend. Register this (plus /api/v1/auth/google/callback) as an authorized redirect URI in the Google OAuth console."
  value       = module.staging_frontend.branch_url
}

output "staging_frontend_app_id" {
  description = "Amplify app id for the staging frontend, for `aws amplify start-job` and console links."
  value       = module.staging_frontend.app_id
}
