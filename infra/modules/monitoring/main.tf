# The alerting path. Before this the project had no alarms and no SNS topics at
# all, which is how the Celery worker and beat ran dead for 44 hours
# (2026-09-27 to 2026-09-29) with every dashboard green.
#
# This lives in its own module rather than inside `ecs` because the SNS topic is
# shared infrastructure: RDS, the ALB and the queue depth all want to publish to
# it later, and moving a topic between modules afterwards means state surgery.
# The metric filters take their log group names as input so this module never
# needs to know how `ecs` builds them.

resource "aws_sns_topic" "alerts" {
  name = "auracles-${var.environment}-alerts"

  tags = {
    Name = "auracles-${var.environment}-alerts"
  }
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email

  # AWS emails a confirmation link on create and the subscription stays
  # "PendingConfirmation" until someone clicks it. Terraform cannot complete
  # that, and it cannot detect it either, so a successful apply does not mean
  # alerts are being delivered — confirm the mail, then test the alarm.
}

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

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "auracles-${var.environment}-${each.key}-crashing"
  }
}
