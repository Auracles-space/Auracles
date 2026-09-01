# Connection material for the environment stack.

output "primary_endpoint" {
  description = "Hostname of the primary node."
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "port" {
  description = "Redis port."
  value       = 6379
}
