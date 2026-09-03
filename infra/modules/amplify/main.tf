# Amplify Hosting app for the Next.js frontend.
#
# Deliberately NOT ephemeral. Amplify bills for build minutes and data served,
# not for existing, so an idle app costs approximately nothing — while a
# recreated one would hand out a new *.amplifyapp.com URL every cycle. That URL
# is registered in Google's OAuth console as an authorized redirect target and
# is what Persona returns users to, so a URL that moves is a manual
# re-registration in two external consoles each time. Hence: this lives in the
# shared stack and survives the environment teardowns.
#
# The build itself is defined by amplify.yml at the repository root, not here.
# Amplify prefers that file over an app-level build spec whenever it exists, so
# setting one in Terraform would create a second source of truth that silently
# loses. Change the build by editing amplify.yml.

resource "aws_amplify_app" "this" {
  name       = var.app_name
  repository = var.repository_url

  # Only read when Amplify first connects the repository; rotating or dropping
  # the token afterwards does not disturb the connection, so this is not a
  # standing credential the app depends on. Null rather than "" so an unset
  # token produces the precondition message below instead of a length error
  # from the AWS provider.
  access_token = var.github_access_token == "" ? null : var.github_access_token

  lifecycle {
    precondition {
      condition     = var.github_access_token != ""
      error_message = "A GitHub token is required to connect the repository. Create a fine-grained personal access token with Contents: read-only and Webhooks: read+write on Auracles-space/Auracles, then export TF_VAR_github_access_token=<token> before applying. It is needed only for this first connection and can be revoked afterwards."
    }
  }

  # WEB_COMPUTE is the SSR platform. The frontend server-renders Explore and
  # framework detail for SEO and reads cookies in middleware on every
  # authenticated route, so the static platform would break both.
  platform = "WEB_COMPUTE"

  # Applies to every branch. Branch-level values in aws_amplify_branch win
  # where they overlap, which is how one app can serve two environments.
  environment_variables = var.environment_variables

  # Amplify's own default is to build every branch that appears in the repo.
  # Off, because this app must not start serving arbitrary feature branches:
  # each one would be a public URL running against a real backend.
  enable_branch_auto_build    = false
  enable_branch_auto_deletion = false

  tags = {
    Name = var.app_name
  }
}

# The one branch this app serves. Auto-build on: pushes to it are how the
# frontend deploys, mirroring the backend's "merge to main builds" half.
resource "aws_amplify_branch" "this" {
  app_id      = aws_amplify_app.this.id
  branch_name = var.branch_name

  framework = "Next.js - SSR"
  stage     = var.stage

  enable_auto_build = true

  # Values specific to this branch — the API origin above all. These are what
  # let a second branch later serve production from the same app without the
  # two environments sharing a backend.
  environment_variables = var.branch_environment_variables
}

# Custom domain. Optional because attaching one means waiting on certificate
# validation, which is worth doing once rather than on every experiment.
# Amplify manages the DNS records itself when the hosted zone is in the same
# account, which it is — the shared stack owns the delegated zone.
resource "aws_amplify_domain_association" "this" {
  count = var.custom_domain == null ? 0 : 1

  app_id      = aws_amplify_app.this.id
  domain_name = var.custom_domain

  # Serve the branch at the domain root. `prefix = ""` is the apex of the
  # delegated subtree (staging.auracles.space), not of auracles.space, which
  # stays at Namecheap and is not touched by any of this.
  sub_domain {
    branch_name = aws_amplify_branch.this.branch_name
    prefix      = ""
  }

  # Let Amplify create the verification and CNAME records in Route 53 rather
  # than requiring a human to copy them somewhere.
  enable_auto_sub_domain = false
}
