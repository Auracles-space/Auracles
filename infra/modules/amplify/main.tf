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
#
# Creating this app for the first time needs a GitHub token in
# TF_VAR_github_access_token (see variables.tf). Afterwards it does not: the
# token is ignored on update, so routine applies need nothing exported. Without
# it on create, the AWS provider rejects the empty value with a length error.

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# Server-side rendering runs as an Amplify-managed compute service, and that
# service writes the app's server logs to CloudWatch under its own identity —
# so an SSR app with no service role fails at BUILD with "Unable to assume
# specified IAM Role", before it ever reaches the deploy step. The console
# creates this role silently when you click through the SSR setup, which is why
# it is easy to miss when defining an app in Terraform instead.
resource "aws_iam_role" "ssr_logging" {
  name = "${var.app_name}-amplify-ssr-logging"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "amplify.amazonaws.com" }
        Action    = "sts:AssumeRole"
        # No aws:SourceAccount / aws:SourceArn condition, deliberately, after
        # trying one: Amplify does not supply those keys when it assumes this
        # role, and a StringEquals on an absent key fails closed. The build
        # then dies at its first step with "Unable to assume specified IAM
        # Role" and nothing indicating which condition was responsible. The
        # console-generated role has no condition either; the permissions
        # below are what keep the blast radius small.
      }
    ]
  })

  tags = {
    Name = "${var.app_name}-amplify-ssr-logging"
  }
}

resource "aws_iam_role_policy" "ssr_logging" {
  name = "push-ssr-logs"
  role = aws_iam_role.ssr_logging.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CreateLogGroup"
        Effect = "Allow"
        Action = "logs:CreateLogGroup"
        # /aws/amplify/* only: this identity exists to write one app's logs,
        # not to create log groups anywhere in the account.
        Resource = "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/amplify/*"
      },
      {
        Sid    = "PushLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/amplify/*:log-stream:*"
      },
      {
        Sid      = "DescribeLogGroups"
        Effect   = "Allow"
        Action   = "logs:DescribeLogGroups"
        Resource = "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:*"
      },
    ]
  })
}

resource "aws_amplify_app" "this" {
  name                 = var.app_name
  repository           = var.repository_url
  iam_service_role_arn = aws_iam_role.ssr_logging.arn

  # Only read when Amplify first connects the repository; rotating or dropping
  # the token afterwards does not disturb the connection, so this is not a
  # standing credential the app depends on. Null rather than "" so an unset
  # token produces the precondition message below instead of a length error
  # from the AWS provider.
  access_token = var.github_access_token == "" ? null : var.github_access_token

  lifecycle {
    # The token is a one-time handshake, not stored configuration: AWS never
    # returns it, so Terraform cannot tell whether the value it holds is still
    # the live one. Without this, every later apply would push whatever the
    # variable happens to contain — an empty or stale value would overwrite a
    # working connection for no reason. Reconnecting the repository is a
    # deliberate act: taint this resource, do not drift into it.
    ignore_changes = [access_token]
  }

  # WEB_COMPUTE is the SSR platform. The frontend server-renders Explore and
  # framework detail for SEO and reads cookies in middleware on every
  # authenticated route, so the static platform would break both.
  platform = "WEB_COMPUTE"

  # Amplify prefers amplify.yml from the repository when it is present, so this
  # copy is normally unused — but it cannot be left empty (the API rejects a
  # zero-length build spec), and a stale one is a trap: delete or rename
  # amplify.yml and the app silently falls back to whatever was last stored,
  # which may predate the Node pin or the secret forwarding. Feeding it the
  # same file keeps the fallback honest instead of ancient.
  build_spec = var.build_spec

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
