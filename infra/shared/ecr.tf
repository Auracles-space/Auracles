# Container registry. Shared-stack, not per-environment: the same image that
# passed staging is what production runs, so both environments pull from one
# repository, and it must survive `terraform destroy` of any environment.

resource "aws_ecr_repository" "backend" {
  name = "auracles-backend"

  # Mutable so the one-time manual bootstrap push (cutover step: build, push,
  # prove /health before any pipeline exists) can be repeated while iterating.
  # The convention on top is stricter than the setting: CI pushes git-sha tags
  # and task definitions pin the sha, so no deploy depends on a mutable tag.
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "auracles-backend"
  }
}

# Untagged images are failed or superseded pushes; sha-tagged history beyond
# ~20 images is dead weight at ~$0.10/GB/mo. ECS holds a reference to the
# digest it runs, so expiry cannot pull an image out from under a live task.
resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the newest 20 tagged images"
        selection = {
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = 20
        }
        action = { type = "expire" }
      },
    ]
  })
}

output "ecr_backend_repository_url" {
  description = "Registry URL the build pushes to and task definitions pull from."
  value       = aws_ecr_repository.backend.repository_url
}
