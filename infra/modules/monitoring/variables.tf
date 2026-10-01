# Inputs for the alerting path.

variable "environment" {
  description = "Deployment environment name, used in alarm and topic names."
  type        = string
}

variable "alerts_topic_arn" {
  description = "SNS topic from shared/ that alarms publish to. Not created here: see the header for why it must outlive an environment."
  type        = string
}

variable "watched_log_groups" {
  description = "Log group names to raise crash alarms on, keyed by service name. Each gets a metric filter counting fatal startup and runtime errors, and an alarm on that count."
  type        = map(string)
}

variable "cluster_name" {
  description = "ECS cluster name, a dimension on the per-service task alarms."
  type        = string
}

variable "watched_services" {
  description = "ECS service names to alarm on when they stop running tasks at all."
  type        = set(string)
}

variable "alb_arn_suffix" {
  description = "Load balancer ARN suffix for ALB metric dimensions."
  type        = string
}

variable "api_target_group_arn_suffix" {
  description = "API target group ARN suffix for target-health metric dimensions."
  type        = string
}
