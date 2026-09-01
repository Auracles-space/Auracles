# Connection material for the environment stack to compose secrets from.

output "endpoint" {
  description = "host:port of the instance."
  value       = aws_db_instance.this.endpoint
}

output "address" {
  description = "Hostname only."
  value       = aws_db_instance.this.address
}

output "database_name" {
  description = "Initial database."
  value       = aws_db_instance.this.db_name
}

output "master_username" {
  description = "Master role."
  value       = aws_db_instance.this.username
}

output "master_password" {
  description = "Generated master password. Sensitive; consumed only to compose the DATABASE_URL secret."
  value       = random_password.master.result
  sensitive   = true
}
