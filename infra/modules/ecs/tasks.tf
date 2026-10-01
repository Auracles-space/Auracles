# Task definitions. Sizes per the infra design §2: api 0.5 vCPU/1 GB, worker
# 1 vCPU/4 GB (clamd's signature database alone needs ~2 GB), beat 0.25/0.5.
#
# ARM64 (Graviton) throughout: ~20% cheaper per vCPU than x86 Fargate, and the
# build machine is Apple Silicon, so images build natively instead of through
# emulation — this image carries LibreOffice and a spaCy model, so that is the
# difference between minutes and most of an hour. Requires every image to be
# arm64 (the official clamav image is multi-arch). If worker/beat ever fail to
# place on FARGATE_SPOT with a capacity error, ARM Spot availability in this
# region is the first suspect — flip use_spot off or this to X86_64.

resource "aws_ecs_task_definition" "api" {
  family                   = "auracles-${var.environment}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.backend_image
      essential = true

      portMappings = [
        { containerPort = var.api_container_port, protocol = "tcp" }
      ]

      environment = [for k, v in local.api_env : { name = k, value = v }]
      secrets     = local.secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.service["api"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "api"
        }
      }
    }
  ])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "auracles-${var.environment}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 4096
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.backend_image
      essential = true
      command   = ["celery", "-A", "app.workers.celery_app:app", "worker", "--loglevel=INFO", "--concurrency=2"]

      # Nothing asked whether this worker worked. It sits behind no load
      # balancer, so unlike the api there was no target-group check either, and
      # `describe-services` happily reported 1/1 running while it had executed
      # no task for 44 hours (2026-09-27 to 2026-09-29, a circular import).
      #
      # `inspect ping` round-trips through the broker to this node, so it fails
      # for the case a process check cannot see: a worker still up but no
      # longer consuming — broker unreachable, pool deadlocked, queue wedged.
      # A worker that exits on boot never reaches this check at all; the
      # deployment circuit breaker is what catches that, and both are needed.
      #
      # startPeriod covers the wait on clamav HEALTHY plus Celery's own import
      # of every task module, so a slow cold start is not read as a failure.
      #
      # `$(hostname)` rather than `$HOSTNAME`: Celery names its node
      # `celery@<hostname>`, and reading it from the command removes a
      # dependency on the runtime exporting that variable. The failure mode if
      # it were ever unset is a check that can never pass, which the circuit
      # breaker would turn into a worker that never deploys.
      healthCheck = {
        command     = ["CMD-SHELL", "celery -A app.workers.celery_app:app inspect ping -d celery@$(hostname) --timeout 10 || exit 1"]
        interval    = 30
        timeout     = 15
        retries     = 3
        startPeriod = 360
      }

      environment = [for k, v in local.worker_env : { name = k, value = v }]
      secrets     = local.secrets

      # awsvpc mode shares one network namespace across the task's
      # containers, so clamd is reachable at localhost:3310 — matching
      # CLAMAV_HOST=localhost in the shared env vars.
      dependsOn = [
        { containerName = "clamav", condition = "HEALTHY" }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.service["worker"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "worker"
        }
      }
    },
    {
      name      = "clamav"
      image     = var.clamav_image
      essential = true

      # clamd loads ~2 GB of signatures before answering; the health check
      # keeps the worker from accepting scan tasks until it can actually scan.
      healthCheck = {
        command     = ["CMD-SHELL", "clamdscan --ping 1 || exit 1"]
        interval    = 30
        timeout     = 10
        retries     = 3
        startPeriod = 300
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.service["worker"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "clamav"
        }
      }
    }
  ])
}

resource "aws_ecs_task_definition" "beat" {
  family                   = "auracles-${var.environment}-beat"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name      = "beat"
      image     = var.backend_image
      essential = true
      command   = ["celery", "-A", "app.workers.celery_app:app", "beat", "--loglevel=INFO"]

      environment = [for k, v in local.beat_env : { name = k, value = v }]
      secrets     = local.secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.service["beat"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "beat"
        }
      }
    }
  ])
}
