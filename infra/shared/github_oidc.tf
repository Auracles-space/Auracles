# GitHub Actions → AWS trust, via OIDC. Shared-stack because CI must keep
# working across every staging destroy.
#
# No AWS access keys are stored in GitHub. Instead, AWS is configured to trust
# identity tokens that GitHub signs for each workflow run. The trust is narrow
# on purpose: only this repository, and only runs on the main branch or a
# version tag, may assume the role — a pull request from a fork gets nothing.
# If the role is ever abused, the fix is `terraform destroy -target` here, not
# a key rotation scramble.

data "aws_caller_identity" "current" {}

# AWS-side registration of GitHub's token issuer. One per AWS account.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  # AWS has pinned GitHub's issuer to its root certificate authorities since
  # 2023, so these thumbprints are no longer consulted — but the argument is
  # still required. These are GitHub's two published values.
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

# The role CI assumes. The trust policy is the security boundary: GitHub's
# token carries a `sub` claim naming the repo and ref that produced it, and
# only main-branch and v*-tag runs of this repository match.
resource "aws_iam_role" "github_actions" {
  name = "auracles-github-actions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:${var.github_repository}:ref:refs/heads/main",
              "repo:${var.github_repository}:ref:refs/tags/v*",
            ]
          }
        }
      }
    ]
  })

  tags = {
    Name = "auracles-github-actions"
  }
}

# What CI may actually do once inside: push images to the one backend
# repository, and bounce the three known services onto a fresh image. It
# cannot read secrets, touch Terraform state, change task definitions, or
# reach any other resource — deploys stay "new image, same everything else",
# and everything else remains the human-applied Terraform.
resource "aws_iam_role_policy" "github_actions" {
  name = "ci-build-and-roll"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # The ECR login handshake is account-wide by design; the write
        # permissions below are what confine CI to the one repository.
        Sid      = "EcrLogin"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "EcrPushBackendImage"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
        ]
        Resource = aws_ecr_repository.backend.arn
      },
      {
        # forceNewDeployment only — the task definition (and therefore every
        # env var, secret ARN, and resource size) stays whatever Terraform
        # last applied. Covers both environments so the release workflow
        # needs no new IAM when production arrives.
        Sid    = "EcsRollKnownServices"
        Effect = "Allow"
        Action = [
          "ecs:UpdateService",
          "ecs:DescribeServices",
        ]
        Resource = [
          "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:service/auracles-staging/*",
          "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:service/auracles-production/*",
        ]
      },
    ]
  })
}

output "github_actions_role_arn" {
  description = "IAM role the GitHub workflows assume. Referenced by ARN in .github/workflows — update there if this ever changes."
  value       = aws_iam_role.github_actions.arn
}
