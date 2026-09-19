# Two roles per the ECS split of responsibilities:
#
#   * The EXECUTION role is what the ECS agent uses to *start* a task: pull
#     the image, create log streams, read the secrets it injects as env vars.
#   * The TASK role is what the application code holds at runtime: S3 access
#     for artifact operations, nothing else. It cannot read Secrets Manager —
#     secrets arrive injected, and a compromised app process should not be
#     able to enumerate the rest of the vault.

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "auracles-${var.environment}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The managed policy covers ECR and logs; secret injection needs an explicit
# grant, scoped to exactly the secrets the task definitions reference.
data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = values(var.secret_arns)
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "read-injected-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

resource "aws_iam_role" "task" {
  name               = "auracles-${var.environment}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# S3 only, and only the four application buckets. Presigned URLs are minted
# with these same credentials, so download/upload authority stays inside this
# grant.
data "aws_iam_policy_document" "task_s3" {
  statement {
    sid = "ObjectRW"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [for name in var.s3_bucket_names : "arn:aws:s3:::${name}/*"]
  }

  # Delete is granted only on the buckets the application legitimately erases
  # from: GDPR erasure (KYC documents in artifacts, export bundles in reports),
  # the artifact orphan sweep, replaced framework files, and withdrawn trial
  # submissions. Avatars and thumbnails are overwritten by key, never deleted,
  # so they stay outside this grant.
  statement {
    sid       = "ObjectDelete"
    actions   = ["s3:DeleteObject"]
    resources = [for name in var.s3_delete_bucket_names : "arn:aws:s3:::${name}/*"]
  }

  statement {
    sid       = "List"
    actions   = ["s3:ListBucket"]
    resources = [for name in var.s3_bucket_names : "arn:aws:s3:::${name}"]
  }
}

resource "aws_iam_role_policy" "task_s3" {
  name   = "app-buckets"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_s3.json
}
