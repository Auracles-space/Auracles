# The alerting destination, shared by every environment.
#
# This lives in shared/ and not in an environment stack because an SNS email
# subscription is only live once a human clicks the link AWS mails them. Per
# environment, that click is owed again on every staging rebuild — and staging
# is built to be destroyed unattended — and once more when production is first
# created. An unconfirmed subscription does not fail loudly: the alarms still
# exist and still fire, into nothing, which looks monitored and is not.
#
# One topic for all environments is deliberate. Alarm names carry their
# environment (`auracles-staging-worker-crashing`), so the mail already says
# which one broke. If production ever needs to reach someone staging does not,
# that is a second subscription on this topic rather than a second topic.

resource "aws_sns_topic" "alerts" {
  name = "auracles-alerts"

  tags = {
    Name = "auracles-alerts"
  }
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email

  # Terraform cannot complete the confirmation and cannot detect that it is
  # outstanding, so a green apply is not evidence of delivery. Check the
  # subscription has a real ARN rather than "PendingConfirmation", then prove
  # the path with `aws cloudwatch set-alarm-state`.
  lifecycle {
    # Replacing this re-sends the confirmation mail and silences alerts until
    # someone clicks it. Changing the address is a deliberate act; make it an
    # explicit two-step rather than a surprise inside an unrelated apply.
    prevent_destroy = true
  }
}
