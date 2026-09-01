# Persistent shared stack: delegated DNS zone and its wildcard certificate.
#
# Everything here outlives every environment stack. Staging is applied and
# destroyed repeatedly; these two resources must not be, for different reasons:
#
#   * The hosted zone is assigned four nameservers on creation. Destroying and
#     recreating it assigns different ones, invalidating the NS records added by
#     hand at Namecheap and taking staging DNS offline until someone notices.
#   * ACM validation is not instantaneous and, for a wildcard, is worth doing
#     once rather than at the head of every QA cycle.
#
# Nothing here touches auracles.space itself. Namecheap stays authoritative for
# the domain, including the mail records that registration and verification
# email depend on.

locals {
  staging_domain = "${var.staging_subdomain}.${var.root_domain}"
}

# Route 53 is authoritative only for this subtree. Namecheap refers queries
# here via the NS records described in the outputs.
resource "aws_route53_zone" "staging" {
  name    = local.staging_domain
  comment = "Delegated from Namecheap. Terraform owns records beneath it; the apex and mail records do not move."

  tags = {
    Name = local.staging_domain
  }

  # The delegation at Namecheap points at this zone's nameservers. Replacing
  # the zone changes them and silently breaks that delegation, so a plan that
  # wants to destroy this needs a human decision, not an apply.
  lifecycle {
    prevent_destroy = true
  }
}

# One certificate covers the subdomain apex and everything under it, so the ALB
# can serve staging.auracles.space and any per-service hostname without a
# certificate change on each staging cycle.
resource "aws_acm_certificate" "staging" {
  domain_name               = local.staging_domain
  subject_alternative_names = ["*.${local.staging_domain}"]
  validation_method         = "DNS"

  tags = {
    Name = local.staging_domain
  }

  # A certificate in use by a listener cannot be deleted. Create the
  # replacement and move the listener to it before the old one goes.
  lifecycle {
    create_before_destroy = true
  }
}

# DNS validation is automatic precisely because the subtree is delegated. The
# production certificate will not have this luxury: its records go in at
# Namecheap by hand.
resource "aws_route53_record" "staging_certificate_validation" {
  # Keyed by domain name because for_each keys must be known at plan time, and
  # the record names ACM assigns are not — they only exist once the certificate
  # does. A certificate covering both `staging.auracles.space` and its wildcard
  # yields two validation options carrying an *identical* record, so this map
  # deliberately holds two entries that write the same thing; allow_overwrite
  # below is what lets them coexist instead of fighting.
  for_each = {
    for option in aws_acm_certificate.staging.domain_validation_options :
    option.domain_name => {
      name   = option.resource_record_name
      record = option.resource_record_value
      type   = option.resource_record_type
    }
  }

  zone_id = aws_route53_zone.staging.zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.record]
  ttl     = 60

  # Load-bearing, not belt-and-braces: the apex and wildcard entries above
  # manage the same physical record, and this is what permits it.
  allow_overwrite = true
}

# Blocks until ACM observes the validation records, which it can only do once
# Namecheap actually delegates the subtree. That delegation is a manual step,
# and it cannot happen before the first apply because the nameservers to enter
# at Namecheap are an output of that apply.
#
# Hence the gate. Applying this stack is deliberately two passes:
#
#   1. `dns_delegation_complete = false` (the default) — creates the zone, the
#      certificate, and the validation records, then stops. Read the
#      `namecheap_ns_records` output and enter those four NS records.
#   2. Once `dig NS staging.auracles.space` returns them, set the variable true
#      and apply again. This resource then confirms the certificate.
#
# Without the gate the first apply would sit for fifteen minutes waiting on a
# delegation that does not exist yet, and then fail — which reads like a broken
# configuration rather than a step not yet taken.
resource "aws_acm_certificate_validation" "staging" {
  count = var.dns_delegation_complete ? 1 : 0

  certificate_arn         = aws_acm_certificate.staging.arn
  validation_record_fqdns = [for record in aws_route53_record.staging_certificate_validation : record.fqdn]

  timeouts {
    # Once the records resolve this takes minutes. If it has not finished in
    # fifteen, the delegation has not propagated and waiting longer will not
    # help — failing says so far more clearly than hanging.
    create = "15m"
  }
}
