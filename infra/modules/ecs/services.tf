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

  # Same reasoning as worker and beat, and required by §5 of the infra design:
  # a deploy that cannot produce a task passing the ALB health check reverts to
  # the task definition that was serving, rather than leaving the old tasks
  # draining against a replacement that never arrives.
  #
  # The grace period above is what makes this safe alongside migration-on-boot:
  # failures are not counted until it elapses. A migration that outruns 120s
  # therefore becomes a rollback instead of a stall — which is the outcome to
  # want, since the alternative is an unreachable api and no clear signal.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

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
    for_each = local.worker_strategy
    content {
      capacity_provider = capacity_provider_strategy.value.capacity_provider
      weight            = capacity_provider_strategy.value.weight
    }
  }

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  # A deploy that cannot produce a healthy worker rolls itself back.
  #
  # Without this, the deploy that introduced a circular import on 2026-09-27
  # crash-looped for 44 hours: ECS kept replacing the task, every replacement
  # died on boot, and the service reported ACTIVE throughout. The breaker
  # counts those failed launches and reverts to the last image that ran, which
  # would have ended that outage in minutes instead of two days.
  #
  # Paired with the container health check, not instead of it: the breaker only
  # watches deployments, so a worker that stops consuming in steady state is
  # the health check's job.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

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
    for_each = local.beat_strategy
    content {
      capacity_provider = capacity_provider_strategy.value.capacity_provider
      weight            = capacity_provider_strategy.value.weight
    }
  }

  # The singleton guarantee lives here — see the header.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  # No health check on beat, deliberately: `celery inspect ping` addresses
  # workers and beat is not one, and its scheduler syncs its schedule file only
  # every few minutes, so a freshness probe on that file could fail spuriously
  # and leave beat permanently un-deployable. The breaker needs no health check
  # to do the job that matters here — the 2026-09-27 outage was a deploy that
  # could not produce a working task, and this reverts that within minutes.
  # Steady-state death is covered by the crash alarm in the monitoring module.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [var.beat_security_group_id]
    assign_public_ip = true
  }

  tags = {
    Name = "auracles-${var.environment}-beat"
  }
}
