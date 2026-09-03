# Outputs consumed by the calling stack and by humans wiring external consoles.

output "app_id" {
  description = "Amplify app id. Needed for `aws amplify start-job` and for console URLs."
  value       = aws_amplify_app.this.id
}

output "default_domain" {
  description = "Amplify-assigned apex, e.g. d1234.amplifyapp.com. The branch is served at <branch>.<this>."
  value       = aws_amplify_app.this.default_domain
}

output "branch_url" {
  description = "Public HTTPS URL of the served branch. This is the value to register as an authorized redirect URI in the Google OAuth console and as the Persona return URL when no custom domain is attached."
  value       = "https://${aws_amplify_branch.this.branch_name}.${aws_amplify_app.this.default_domain}"
}

output "custom_domain_url" {
  description = "HTTPS URL of the custom domain when one is attached, otherwise null."
  value       = var.custom_domain == null ? null : "https://${var.custom_domain}"
}
