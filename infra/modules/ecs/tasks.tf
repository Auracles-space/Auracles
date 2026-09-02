# Task definitions. Sizes per the infra design §2: api 0.5 vCPU/1 GB, worker
# 1 vCPU/4 GB (clamd's signature database alone needs ~2 GB), beat 0.25/0.5.

resource "aws_ecs_task_definition" "api" {
  family                   = "auracles-${var.environment}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

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

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.backend_image
      essential = true
      command   = ["celery", "-A", "app.workers.celery_app:app", "worker", "--loglevel=INFO", "--concurrency=2"]

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
