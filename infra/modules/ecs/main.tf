# Cluster, log groups, task definitions, and services.
#
# One image, three commands: api (uvicorn), worker (celery worker + clamd
# sidecar), beat (celery beat, singleton). The deploy story depends on this —
# a release is one image promoted, not three builds coordinated.

locals {
  # Per-service DB pool sizing (infra design §4): the api serves short
  # request-scoped sessions; the worker runs few concurrent tasks; beat only
  # dispatches. Layered over the shared env vars so the caller states policy
  # once and the split lives next to the services it sizes.
  api_env    = merge(var.environment_variables, { DB_POOL_SIZE = "5", DB_MAX_OVERFLOW = "5" })
  worker_env = merge(var.environment_variables, { DB_POOL_SIZE = "3", DB_MAX_OVERFLOW = "2" })
  beat_env   = merge(var.environment_variables, { DB_POOL_SIZE = "1", DB_MAX_OVERFLOW = "1" })

  secrets = [
    for name, arn in var.secret_arns : { name = name, valueFrom = arn }
  ]

  # Capacity split per the 2026-09-01 decision: user-facing api on-demand,
  # everything idempotent on Spot.
  spot_strategy = [
    {
      capacity_provider = var.use_spot ? "FARGATE_SPOT" : "FARGATE"
      weight            = 1
    }
  ]
}

resource "aws_ecs_cluster" "this" {
  name = "auracles-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "disabled" # ~$10+/mo of metrics nobody reads at pilot scale
  }

  tags = {
    Name = "auracles-${var.environment}"
  }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

resource "aws_cloudwatch_log_group" "service" {
  for_each = toset(["api", "worker", "beat"])

  name              = "/ecs/auracles-${var.environment}/${each.key}"
  retention_in_days = var.log_retention_days
}
