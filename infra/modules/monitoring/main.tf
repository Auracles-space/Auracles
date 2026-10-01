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
