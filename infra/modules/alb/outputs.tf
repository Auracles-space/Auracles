# Attachment points for ECS and DNS.

output "target_group_arn" {
  description = "Target group the api service registers into."
  value       = aws_lb_target_group.api.arn
}

output "dns_name" {
  description = "ALB hostname, for the Route 53 alias record."
  value       = aws_lb.this.dns_name
}

output "zone_id" {
  description = "ALB's canonical hosted zone id, required by alias records."
  value       = aws_lb.this.zone_id
}

output "https_listener_arn" {
  description = "HTTPS listener, dependency anchor for the ECS service."
  value       = aws_lb_listener.https.arn
}
