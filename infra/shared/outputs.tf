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
