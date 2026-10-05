# Outputs consumed by humans (the Namecheap step) and by the environment stacks.

output "namecheap_ns_records" {
  description = "The four nameservers to enter at Namecheap as NS records on host 'staging' of auracles.space. Do this after the first apply; nothing else in the build works until these resolve. Leave every other Namecheap record alone — the apex and its mail records are not moving."
  value       = aws_route53_zone.staging.name_servers
}

output "staging_domain" {
  description = "Fully qualified delegated domain."
  value       = local.staging_domain
}

output "staging_zone_id" {
  description = "Hosted zone id for the delegated subtree. The staging stack creates its ALB alias records here."
  value       = aws_route53_zone.staging.zone_id
}

output "staging_certificate_arn" {
  description = "ACM certificate covering the staging subdomain and its wildcard, for the ALB HTTPS listener. Issued only once dns_delegation_complete has been set and applied — attaching it to a listener before then fails."
  value       = aws_acm_certificate.staging.arn
}

output "staging_certificate_validated" {
  description = "Whether the ACM validation wait has been run. False means the delegation step is still outstanding and the staging stack is not yet safe to apply."
  value       = length(aws_acm_certificate_validation.staging) > 0
}

output "alerts_topic_arn" {
  description = "SNS topic every environment's alarms publish to. Confirmed once and outlives any environment rebuild."
  value       = aws_sns_topic.alerts.arn
}

output "namecheap_api_ns_records" {
  description = "The four nameservers to enter at Namecheap as NS records on host 'api' of auracles.space. Do this after the first apply of the production API block; the certificate cannot validate until they resolve. Leave every other Namecheap record alone — the apex, www, and the mail records are not moving."
  value       = aws_route53_zone.production_api.name_servers
}

output "production_api_domain" {
  description = "Fully qualified API hostname for production."
  value       = local.production_api_domain
}

output "production_api_zone_id" {
  description = "Hosted zone id for the delegated API subtree. The production stack creates its ALB alias record here."
  value       = aws_route53_zone.production_api.zone_id
}

output "production_api_certificate_arn" {
  description = "ACM certificate covering api.auracles.space and its wildcard, for the production ALB's HTTPS listener. Attaching it to a listener before validation has run fails."
  value       = aws_acm_certificate.production_api.arn
}

output "production_api_certificate_validated" {
  description = "Whether the production API certificate's validation wait has been run. False means the Namecheap delegation step is still outstanding and the production stack is not yet safe to apply."
  value       = length(aws_acm_certificate_validation.production_api) > 0
}
