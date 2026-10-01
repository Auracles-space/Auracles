output "alerts_topic_arn" {
  description = "SNS topic every alarm publishes to. Pass this to future alarms rather than creating another topic."
  value       = aws_sns_topic.alerts.arn
}
