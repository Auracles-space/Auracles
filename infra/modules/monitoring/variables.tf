# Inputs for the alerting path.

variable "environment" {
  description = "Deployment environment name, used in alarm and topic names."
  type        = string
}

variable "alert_email" {
  description = "Address that receives alarm notifications. An SNS email subscription must be confirmed once by clicking the link AWS sends; until then the alarm fires into silence."
  type        = string
}

variable "watched_log_groups" {
  description = "Log group names to raise crash alarms on, keyed by service name. Each gets a metric filter counting fatal startup and runtime errors, and an alarm on that count."
  type        = map(string)
}
