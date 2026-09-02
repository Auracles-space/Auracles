# The three services.
#
# Deployment shapes differ by what a brief doubling would mean:
#   * api: standard rolling (a second api task during deploy is harmless).
#   * worker: rolling is fine (two workers is just more throughput; tasks are
#     idempotent by project rule).
#   * beat: NEVER two at once — two schedulers double-fire every periodic job,
#     including payout sweeps. min 0 / max 100 means deploys stop the old one
#     before starting the new: a scheduling gap over a scheduling overlap.

resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1

  # User-facing: on-demand always, never Spot.
  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [var.api_security_group_id]
    assign_public_ip = true # no NAT; the public IP is the outbound path
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "api"
    container_port   = var.api_container_port
  }

  # The api runs alembic upgrade on boot; give a slow migration room before
  # the ALB starts counting health-check failures against the task.
  health_check_grace_period_seconds = 120

  tags = {
    Name = "auracles-${var.environment}-api"
  }
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1

  dynamic "capacity_provider_strategy" {
    for_each = local.spot_strategy
    content {
      capacity_provider = capacity_provider_strategy.value.capacity_provider
      weight            = capacity_provider_strategy.value.weight
    }
  }

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [var.worker_security_group_id]
    assign_public_ip = true
  }

  tags = {
    Name = "auracles-${var.environment}-worker"
  }
}

resource "aws_ecs_service" "beat" {
  name            = "beat"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.beat.arn
  desired_count   = 1

  dynamic "capacity_provider_strategy" {
    for_each = local.spot_strategy
    content {
      capacity_provider = capacity_provider_strategy.value.capacity_provider
      weight            = capacity_provider_strategy.value.weight
    }
  }

  # The singleton guarantee lives here — see the header.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [var.beat_security_group_id]
    assign_public_ip = true
  }

  tags = {
    Name = "auracles-${var.environment}-beat"
  }
}
