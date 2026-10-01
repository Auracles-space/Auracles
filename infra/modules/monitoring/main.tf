# Per-environment alarms. The SNS topic they publish to lives in shared/ and is
# passed in: an email subscription is only live once a human clicks AWS's
# confirmation link, and a topic owned per environment owes that click again on
# every staging rebuild and once more when production is created. An
# unconfirmed subscription fires into silence while looking monitored.
#
# Before 2026-10-01 the project had no alarms and no SNS topics at all, which is
# how the Celery worker and beat both ran dead for 44 hours while ECS reported
# ACTIVE 1/1.

# A container that dies on startup writes a traceback and nothing else: no
# metric, no health transition for a crash-loop, and a service that still
# reports its desired count. Counting fatal log lines is the signal that
# actually distinguishes "restarting forever" from "running".
resource "aws_cloudwatch_log_metric_filter" "crash" {
  for_each = var.watched_log_groups

  name           = "auracles-${var.environment}-${each.key}-crash"
  log_group_name = each.value

  # Celery and uvicorn both print `Traceback` on an unhandled startup failure,
  # and `ImportError` catches the circular-import class specifically — that one
  # aborts before any application logging is configured.
  pattern = "?Traceback ?ImportError"

  metric_transformation {
    name      = "${each.key}_crashes"
    namespace = "Auracles/${var.environment}"
    value     = "1"
    # Absent is not zero here: with no traffic there are no log events at all,
    # and treating that as 0 keeps the alarm OK rather than INSUFFICIENT_DATA.
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "crash" {
  for_each = var.watched_log_groups

  alarm_name        = "auracles-${var.environment}-${each.key}-crashing"
  alarm_description = "The ${each.key} service is logging startup or runtime tracebacks. A crash-looping ECS task keeps reporting its desired count, so this is the only signal that it is not actually working."

  namespace   = "Auracles/${var.environment}"
  metric_name = "${each.key}_crashes"
  statistic   = "Sum"

  # A crash loop restarts every couple of minutes, so two consecutive 5-minute
  # periods with tracebacks is a loop rather than one unlucky restart. A single
  # period would page on any transient failure that recovered by itself.
  period              = 300
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [var.alerts_topic_arn]
  ok_actions    = [var.alerts_topic_arn]

  tags = {
    Name = "auracles-${var.environment}-${each.key}-crashing"
  }
}

# A service with no running tasks at all.
#
# The crash alarm above reads logs, so it only sees a service that is up enough
# to write them. A task that stops and never comes back writes nothing, and the
# log filter's `notBreaching` reads that silence as healthy — the one failure
# shape the rest of this module cannot see.
#
# `RunningTaskCount` would say this directly, but it is a Container Insights
# metric and the cluster leaves Insights off on purpose ("~$10+/mo of metrics
# nobody reads at pilot scale"). `CPUUtilization` is a standard metric and costs
# nothing, and ECS stops publishing it entirely when a service has no tasks — so
# missing data *is* the signal here, which is why this is the one alarm in the
# module that treats absence as breaching.
resource "aws_cloudwatch_metric_alarm" "no_running_tasks" {
  for_each = var.watched_services

  alarm_name        = "auracles-${var.environment}-${each.value}-not-running"
  alarm_description = "The ${each.value} service has published no CPU metric for 15 minutes, which means it is running no tasks. Container Insights is disabled by choice, so absence of this standard metric is the available signal."

  namespace   = "AWS/ECS"
  metric_name = "CPUUtilization"
  statistic   = "Average"

  dimensions = {
    ClusterName = var.cluster_name
    ServiceName = each.value
  }

  # 15 minutes of silence. A deploy legitimately leaves a gap — worker and beat
  # stop the old task before starting the new one, and the worker then waits on
  # clamav's 300s startup — so a shorter window would page on every release.
  period              = 300
  evaluation_periods  = 3
  threshold           = 0
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"

  alarm_actions = [var.alerts_topic_arn]
  ok_actions    = [var.alerts_topic_arn]

  tags = {
    Name = "auracles-${var.environment}-${each.value}-not-running"
  }
}

# The api, which the crash filter deliberately skips.
#
# FastAPI prints a traceback for every unhandled 500, so a log filter on the api
# would fire on ordinary bugs and train everyone to ignore the alarm. Target
# health is the honest signal: it says the api is not serving, without an
# opinion about why.
resource "aws_cloudwatch_metric_alarm" "api_unhealthy_targets" {
  alarm_name        = "auracles-${var.environment}-api-unhealthy"
  alarm_description = "The api target group has an unhealthy target. The ALB health check pings /v1/health, which touches the database and Redis, so this covers a dependency failure as well as a dead process."

  namespace   = "AWS/ApplicationELB"
  metric_name = "UnHealthyHostCount"
  statistic   = "Maximum"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.api_target_group_arn_suffix
  }

  # Two minutes. The api runs migrations on boot and has a 120s grace period
  # before the ALB counts failures, so a deploy does not register here at all.
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [var.alerts_topic_arn]
  ok_actions    = [var.alerts_topic_arn]

  tags = {
    Name = "auracles-${var.environment}-api-unhealthy"
  }
}

# 5xx raised by the load balancer itself, not by the application.
#
# `HTTPCode_ELB_5XX_Count` is what the ALB returns when it cannot reach a target
# at all — no healthy host, or a connection it could not complete. An
# application 500 is counted under `HTTPCode_Target_5XX_Count` and is
# deliberately not alarmed on, for the same reason the api is kept out of the
# log filter: ordinary bugs would bury the signal.
resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name        = "auracles-${var.environment}-alb-5xx"
  alarm_description = "The load balancer is returning 5xx without reaching a target, which is what a visitor sees when nothing healthy is behind it."

  namespace   = "AWS/ApplicationELB"
  metric_name = "HTTPCode_ELB_5XX_Count"
  statistic   = "Sum"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
  }

  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [var.alerts_topic_arn]
  ok_actions    = [var.alerts_topic_arn]

  tags = {
    Name = "auracles-${var.environment}-alb-5xx"
  }
}
