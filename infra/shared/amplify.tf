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

# ---------------------------------------------------------------------------
# Production frontend.
#
# Same repository and same branch as staging — `main` — but auto-build is OFF.
# The backend ships only on a `git tag v*`, so a frontend that rebuilt on every
# merge could go live calling an endpoint that has not been promoted yet.
# `release.yml` starts this build itself after the ECS roll succeeds, pinned to
# the tagged commit, so one tag moves both halves from the same source.
#
# Rolling backend-first is deliberate: migrations must stay compatible with the
# previously deployed version, so new-backend/old-frontend is the safe gap to
# have for the couple of minutes the build takes. The reverse is not.
# ---------------------------------------------------------------------------

# Signs the frontend's session-hint cookie with the same key the backend signs
# JWTs with. A mismatch does not error anywhere — it silently treats every
# visitor as logged out — so it is read here rather than pasted twice.
data "aws_secretsmanager_secret_version" "production_session_hint" {
  secret_id = aws_secretsmanager_secret.production["SECRET_KEY"].id
}

module "production_frontend" {
  source = "../modules/amplify"

  app_name       = "auracles-production"
  repository_url = "https://github.com/${var.github_repository}"
  branch_name    = "main"
  stage          = "PRODUCTION"

  enable_auto_build = false

  github_access_token = var.github_access_token

  build_spec = file("${path.module}/../../amplify.yml")

  environment_variables = {
    AMPLIFY_MONOREPO_APP_ROOT = "frontend"

    # Must stay false. True makes Amplify compare the app root against the
    # previous build and skip both build and deploy when it sees no change —
    # which on a branch that has never deployed means shipping nothing and
    # serving the placeholder page. Diagnosed the hard way on the waitlist app.
    AMPLIFY_DIFF_DEPLOY = "false"
  }

  branch_environment_variables = {
    # Server-side; amplify.yml forwards these into .env.production, because
    # Amplify exposes env vars to SSR at build time only.
    BACKEND_ORIGIN      = "https://${local.production_api_domain}"
    SESSION_HINT_SECRET = data.aws_secretsmanager_secret_version.production_session_hint.secret_string

    # Relative on purpose: the browser calls /api/* on the frontend's own
    # origin and next.config.ts rewrites it to BACKEND_ORIGIN, keeping auth
    # cookies first-party. An absolute URL makes them third-party and silently
    # breaks login in browsers that block those.
    NEXT_PUBLIC_API_URL = "/api"

    # WebSockets are not proxied — CloudFront does not carry the upgrade.
    NEXT_PUBLIC_WS_URL = "wss://${local.production_api_domain}"

    NEXT_PUBLIC_WAITLIST_MODE     = "false"
    NEXT_PUBLIC_PLATFORM_CURRENCY = "NGN"

    # Deliberately the same publishable key staging uses. Stripe is outside the
    # Nigeria pilot's scope — select_provider sends every NGN transaction to
    # Paystack — so no Stripe checkout renders. The key is present rather than
    # blank only so the client bundle never initialises Stripe.js with an empty
    # string. Replace it with a live publishable key if Stripe comes into scope.
    NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY = var.stripe_publishable_key
  }

  # The apex is not in Route 53, so Amplify cannot write its own records for it.
  # Attaching auracles.space is the launch switch — done by hand at Namecheap,
  # with moving it back as the rollback — so it stays null here.
  custom_domain = null
}

output "production_frontend_url" {
  description = "Public URL of the production frontend on its amplifyapp.com domain, before the apex is pointed at it."
  value       = module.production_frontend.branch_url
}

output "production_frontend_app_id" {
  description = "Amplify app id for the production frontend. release.yml looks the app up by name rather than reading this, so the workflow does not depend on Terraform state."
  value       = module.production_frontend.app_id
}
